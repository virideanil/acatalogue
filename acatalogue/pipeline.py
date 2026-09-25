"""Download, seal, convert and integrate the selected sources: each stage starts as soon as its input
is ready, so conversions run while other files are still downloading.

  download   threads (per-host politeness in download.py); a source's files land in raw/<source>/<day>/
  seal       when every file of a source is in, its manifest (store/corpora/<snapshot>) records each
             file's SHA-512, size, URL, time and licence, and is sealed
  convert    worker processes: sealed manifest -> lean file (store/lean/<source>/), inputs re-verified
  integrate  the catalogue's one writer: lean file -> catalogue (acatalogue/integrate.py), then the
             search indexes and statistics are rebuilt once

Every stage is resumable: partial downloads continue, a finished conversion of the same manifest by the
same converter version is reused, and integrating the same lean file again does nothing. State lives in
store.sqlite (download, job, event); the catalogue's ledger records every integration.
"""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import json
import multiprocessing
import os
import threading
import traceback
from pathlib import Path

from .corpusfile import CorpusFile
from .download import Downloader, Task
from .util import sha512_file, today_compact, utcnow


def snapshot_for(store, source: str, *, refresh: bool = False) -> tuple[str, bool]:
    """(snapshot name, already sealed?): the unsealed one being downloaded, else the newest sealed one,
    else (or with refresh) a new dated one."""
    rows = sorted(p.parent.name for p in (store.root / "corpora").glob(f"{source}-*/corpus.sqlite")
                  if p.parent.name[len(source) + 1:].split("-")[0].isdigit())
    newest_sealed = None
    for name in reversed(rows):
        c = CorpusFile(store.corpus_path(name), readonly=True)
        try:
            if not c.sealed:
                return name, False
            newest_sealed = newest_sealed or name
        finally:
            c.close()
    if newest_sealed and not refresh:
        return newest_sealed, True
    day = today_compact()
    name, k = f"{source}-{day}", 2
    while store.corpus_path(name).exists():
        name, k = f"{source}-{day}-{k}", k + 1
    return name, False


def _day(snapshot: str, source: str) -> str:
    return snapshot[len(source) + 1:]


def open_manifest(store, reg, source: str, snapshot: str) -> CorpusFile:
    path = store.corpus_path(snapshot)
    e = reg.sources[source]
    c = CorpusFile(path, create=not path.exists(), name=snapshot, title=e["title"], license=e.get("license"),
                   description=f"{e.get('publisher') or ''}: files of {source} as published".strip(": "))
    raw = store.raw_dir(source, _day(snapshot, source))
    c.set_external_root(os.path.relpath(raw, path.parent))
    return c


def seal(store, reg, source: str, snapshot: str) -> str:
    """Record every downloaded file (re-hashed) in the manifest and seal it."""
    c = open_manifest(store, reg, source, snapshot)
    try:
        if not c.sealed:
            e = reg.sources[source]
            for d in store.conn.execute("SELECT * FROM download WHERE snapshot = ? ORDER BY name", (snapshot,)):
                if d["state"] != "done":
                    raise RuntimeError(f"{snapshot}: {d['name']} is {d['state']}")
                c.add_external(d["name"], d["sha512"], d["bytes_done"], url=d["url"], content_type=d["content_type"],
                               retrieved_at=d["finished_at"], license=e.get("license"),
                               attribution=e.get("publisher"))
            c.seal()
            store.event(source, "seal", "info", f"{snapshot} sealed: manifest {c.manifest()[:16]}…")
        return c.meta()["manifest_sha512"]
    finally:
        c.close()


def convert_job(args: dict) -> dict:
    """Run in a worker process: sealed manifest -> lean file. Inputs are re-verified before reading."""
    from .convert import VERSION, Input, registry
    from .lean import LeanWriter
    c = CorpusFile(args["manifest_path"], readonly=True)
    inputs = []
    try:
        for it in c.items():
            path = c.external_path(it["name"])
            digest, n = sha512_file(path)
            if (digest, n) != (it["sha512"], it["bytes"]):
                raise ValueError(f"{path}: bytes differ from the sealed manifest")
            inputs.append(Input(it["name"], path, digest, n, it["url"], it["retrieved_at"]))
    finally:
        c.close()
    e = args["entry"]
    out = Path(args["out"])
    w = LeanWriter(out, source=e["id"], title=e["title"], converter=e["converter"], version=VERSION,
                   license=e.get("license"), attribution=e.get("publisher"), homepage=e.get("homepage"),
                   snapshot=args["snapshot"], manifest_sha512=args["manifest_sha512"])
    lines: list[str] = []
    try:
        for i in inputs:
            w.input(i.name, i.sha512, i.bytes, i.url, i.retrieved_at)
        registry()[e["converter"]](inputs, w, json.loads(e.get("options") or "{}"), lines.append)
        res = w.finish()
    except BaseException:
        w.abort()
        raise
    res["log"] = lines
    return res


class Pipeline:
    def __init__(self, store, reg, *, db_path=None, workers: int = 4, converters: int | None = None,
                 per_host: int = 1, min_interval: float = 1.0, integrate: bool = True, refresh: bool = False,
                 progress=print):
        self.store, self.reg = store, reg
        self.db_path = db_path
        self.workers = workers
        self.converters = converters or max(1, min(2, (os.cpu_count() or 2) - 1))
        self.integrate_after = integrate
        self.refresh = refresh
        self.say = progress
        self.dl = Downloader(store, per_host=per_host, min_interval=min_interval, progress=progress)
        self.lock = threading.Lock()

    # ── plan ──
    def plan(self, sources: list[str]) -> list[dict]:
        out = []
        for s in sources:
            snap, sealed = snapshot_for(self.store, s, refresh=self.refresh)
            files = self.reg.files.get(s, [])
            done = {r["name"] for r in self.store.conn.execute(
                "SELECT name FROM download WHERE snapshot = ? AND state = 'done'", (snap,))}
            job = self.store.conn.execute("SELECT state, output FROM job WHERE snapshot = ? AND stage = 'convert'",
                                          (snap,)).fetchone()
            known = [int(f["bytes"]) for f in files if (f.get("bytes") or "").isdigit()]
            out.append({"source": s, "snapshot": snap, "sealed": sealed, "files": len(files),
                        "downloaded": len(done) if not sealed else len(files),
                        "bytes": sum(known) if len(known) == len(files) else None,
                        "converted": bool(job and job["state"] == "done" and Path(self.store.abs(job["output"])).exists()),
                        "license": self.reg.sources[s].get("license"), "mode": self.reg.mode(s)})
        return out

    # ── run ──
    def run(self, sources: list[str]) -> dict:
        skipped = [s for s in sources if not self.reg.files.get(s)]
        for s in skipped:
            self.say(f"  {s}: no public file to download ({self.reg.sources[s].get('access') or 'none'}); skipped")
        sources = [s for s in sources if s not in skipped]
        results: dict[str, dict] = {s: {} for s in sources}
        snaps = {s: snapshot_for(self.store, s, refresh=self.refresh) for s in sources}
        pending_files: dict[str, int] = {}
        ctx = multiprocessing.get_context("spawn")        # never fork a process that has download threads
        with cf.ThreadPoolExecutor(self.workers, thread_name_prefix="dl") as dpool, \
                cf.ProcessPoolExecutor(self.converters, mp_context=ctx) as cpool:
            conversions: dict[cf.Future, str] = {}

            def start_conversion(s: str) -> None:
                snap, _ = snaps[s]
                try:
                    manifest = seal(self.store, self.reg, s, snap)
                except Exception as exc:
                    results[s]["error"] = f"seal: {exc}"
                    self.store.event(s, "seal", "error", str(exc))
                    return
                results[s]["manifest_sha512"] = manifest
                if self.reg.sources[s].get("converter") == "raw":
                    self.say(f"  {s}: downloaded and sealed ({snap}); no converter yet")
                    results[s]["sealed_only"] = True
                    return
                from .convert import VERSION
                recipe = hashlib.sha256(json.dumps([self.reg.sources[s]["converter"],
                                                    json.loads(self.reg.sources[s].get("options") or "{}")],
                                                   sort_keys=True).encode()).hexdigest()[:16]
                key = f"{manifest}|{VERSION}|{recipe}"      # the same bytes, read the same way
                job = self.store.conn.execute("SELECT * FROM job WHERE snapshot = ? AND stage = 'convert'",
                                              (snap,)).fetchone()
                if job and job["state"] == "done" and job["input"] == key and \
                        Path(self.store.abs(job["output"])).exists():
                    results[s]["lean"] = self.store.abs(job["output"])
                    self.say(f"  {s}: converted already ({Path(job['output']).name})")
                    return
                # named by the reading too: another converter version or other options never overwrite a file
                # an earlier integration names (the same reading gives the same bytes, so it may)
                out = self.store.lean_dir(s) / f"{snap}-{VERSION}-{recipe[:8]}.sqlite"
                self.store.conn.execute(
                    "INSERT INTO job(snapshot, stage, source, state, input, output, started_at) VALUES (?,?,?,?,?,?,?)"
                    " ON CONFLICT(snapshot, stage) DO UPDATE SET state = 'running', input = excluded.input,"
                    " started_at = excluded.started_at, error = NULL",
                    (snap, "convert", s, "running", key, self.store.rel(out), utcnow()))
                self.say(f"  {s}: converting {snap} ({self.reg.sources[s]['converter']})")
                fut = cpool.submit(convert_job, {"manifest_path": str(self.store.corpus_path(snap)),
                                                 "entry": dict(self.reg.sources[s]), "snapshot": snap,
                                                 "manifest_sha512": manifest, "out": str(out)})
                conversions[fut] = s

            def downloaded(fut: cf.Future, s: str, f: dict, raw: Path) -> None:
                name = f["name"]
                try:
                    fut.result()
                    if (f.get("format") or "").startswith("manifest:"):
                        # a publisher's manifest names the parts of this release: they join the snapshot
                        for t in self.expand(s, snaps[s][0], f, raw):
                            with self.lock:
                                pending_files[s] += 1
                            nf = dpool.submit(self.dl.fetch, t)
                            nf.add_done_callback(lambda fu, s=s, pf={"name": t.name}: downloaded(fu, s, pf, raw))
                            futures.append((s, nf))
                except Exception as exc:
                    with self.lock:
                        results[s].setdefault("failed_files", []).append(f"{name}: {exc}")
                    self.say(f"  {s}/{name}: FAILED {exc}")
                with self.lock:
                    pending_files[s] -= 1

            futures = []
            for s in sources:
                snap, sealed = snaps[s]
                if sealed:
                    continue
                files = self.reg.files.get(s, [])
                pending_files[s] = len(files)
                raw = self.store.raw_dir(s, _day(snap, s))
                for f in files:
                    t = Task(s, snap, f["name"], f["url"], raw / f["name"], checksum=f.get("checksum") or None,
                             expected_bytes=int(f["bytes"]) if (f.get("bytes") or "").isdigit() else None,
                             license=self.reg.sources[s].get("license"), attribution=self.reg.sources[s].get("publisher"))
                    fut = dpool.submit(self.dl.fetch, t)
                    fut.add_done_callback(lambda fu, s=s, f=f, raw=raw: downloaded(fu, s, f, raw))
                    futures.append((s, fut))
                self.say(f"  {s}: {len(files)} file(s) queued into {self.store.rel(raw)}")
            started: set[str] = set()
            integrated: set[str] = set()
            for s in sources:                             # sealed earlier: straight to conversion
                if snaps[s][1]:
                    start_conversion(s)
                    started.add(s)
            try:
                while True:
                    if self.integrate_after:              # one writer: each ready source goes in now
                        for s in sources:
                            if s not in integrated and results[s].get("lean") is not None:
                                integrated.add(s)
                                self._integrate_ready(s, results)
                    for s in sources:
                        with self.lock:
                            ready = s not in started and pending_files.get(s) == 0
                        if ready:
                            started.add(s)
                            if results[s].get("failed_files"):
                                self.say(f"  {s}: not converted: {len(results[s]['failed_files'])} file(s) failed")
                                continue
                            start_conversion(s)
                    done, _ = cf.wait(list(conversions), timeout=0.5, return_when=cf.FIRST_COMPLETED) \
                        if conversions else (set(), set())
                    for fut in done:
                        s = conversions.pop(fut)
                        self._converted(s, snaps[s][0], fut, results)
                    if len(started) == len(sources) and not conversions and not (
                            self.integrate_after and any(s not in integrated and results[s].get("lean") is not None
                                                         for s in sources)):
                        break
                    if not conversions and not done:
                        cf.wait([f for _, f in futures], timeout=0.5, return_when=cf.FIRST_COMPLETED)
            except KeyboardInterrupt:
                self.dl.stop.set()
                self.say("  interrupted: partial downloads stay as .part files and resume next time")
                raise
        if self.integrate_after:
            results["_integration"] = self._finish_integration()
        return results

    # ── integration, one source at a time as each is ready ──
    def _conn(self):
        if getattr(self, "_cat", None) is None:
            from . import db as dbm
            self._cat = dbm.connect(self.db_path) if self.db_path else dbm.connect()
            dbm.init_schema(self._cat)
            self._integrated: dict[str, dict] = {}
        return self._cat

    def _integrate_ready(self, s: str, results: dict) -> None:
        try:
            out = self.integrate_one(self._conn(), s)
        except Exception as exc:
            err = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            results[s]["error"] = f"integrate: {err}"
            self.store.event(s, "integrate", "error", err[:500])
            self.say(f"  {s}: integration FAILED: {err}")
            return
        if out is not None:
            self._integrated[s] = out

    def _finish_integration(self) -> dict:
        from .build import compute_stats, rebuild_search
        conn = getattr(self, "_cat", None)
        if conn is None:
            return {}
        try:
            if any(not v.get("skipped") for v in self._integrated.values()):
                conn.execute("BEGIN")
                self.say("  rebuilding search indexes and statistics")
                rebuild_search(conn)
                compute_stats(conn)
                conn.commit()
        finally:
            conn.close()
            self._cat = None
        return self._integrated

    def expand(self, s: str, snap: str, f: dict, raw: Path) -> list[Task]:
        """The part files a downloaded manifest names (OpenAlex: s3:// URLs served over HTTPS)."""
        kind = f["format"].split(":", 1)[1]
        if kind != "openalex":
            raise ValueError(f"unknown manifest kind {kind!r}")
        data = json.loads((raw / f["name"]).read_bytes())
        rewrite = self.reg.options(s).get("manifest_rewrite")
        stem = f["name"].rsplit("-manifest", 1)[0]
        tasks = []
        for entry in data.get("files", []):
            url = entry["url"].replace("s3://openalex/", "https://openalex.s3.amazonaws.com/")
            if rewrite:
                url = url.replace(*rewrite)
            part = url.rstrip("/").split("/")
            name = f"{stem}-{part[-2].replace('updated_date=', '')}-{part[-1]}"
            size = (entry.get("meta") or {}).get("content_length")
            tasks.append(Task(s, snap, name, url, raw / name, expected_bytes=size,
                              license=self.reg.sources[s].get("license"),
                              attribution=self.reg.sources[s].get("publisher")))
        self.say(f"  {s}: {f['name']} names {len(tasks)} part(s)")
        return tasks

    def _converted(self, s: str, snap: str, fut: cf.Future, results: dict) -> None:
        try:
            res = fut.result()
        except Exception as exc:
            err = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            self.store.conn.execute("UPDATE job SET state = 'failed', error = ?, finished_at = ? WHERE snapshot = ?"
                                    " AND stage = 'convert'", (err[:2000], utcnow(), snap))
            self.store.event(s, "convert", "error", err[:500])
            results[s]["error"] = f"convert: {err}"
            self.say(f"  {s}: conversion FAILED: {err}")
            return
        self.store.conn.execute("UPDATE job SET state = 'done', output_sha512 = ?, finished_at = ?, detail = ?"
                                " WHERE snapshot = ? AND stage = 'convert'",
                                (res["sha512"], utcnow(), json.dumps({"counts": res["counts"], "dropped": res["dropped"],
                                                                      "bytes": res["bytes"], "seconds": res["seconds"]}),
                                 snap))
        for line in res.get("log", []):
            self.say(f"  {s}:{line}")
        self.store.event(s, "convert", "info", f"{snap}: {res['counts']}")
        results[s]["lean"] = Path(res["path"])
        c = res["counts"]
        self.say(f"  {s}: converted: {c['term']:,} terms, {c['label']:,} names, {c['rel']:,} relations,"
                 f" {c['attr']:,} attributes, {c['link']:,} links ({res['bytes'] / 1e6:,.1f} MB)")

    # ── integrate ──
    def integrate(self, sources: list[str]) -> dict:
        """Integrate these sources' latest lean files now (then rebuild the search indexes once)."""
        for s in sources:
            self._integrate_ready(s, {s: {}})
        return self._finish_integration()

    def integrate_one(self, conn, s: str) -> dict | None:
        from .integrate import Resolver, integrate
        lean, snap, manifest = self.latest_lean(s)
        if lean is None:
            return None
        if getattr(self, "_resolver", None) is None:
            self._resolver = Resolver(list(self.reg.sources.values()))
        selected = self.store.selected()
        mode = self.reg.mode(s, selected[s]["mode"] if s in selected else None)
        self.say(f"  {s}: integrating ({mode})")
        conn.execute("BEGIN")
        try:
            out = integrate(conn, lean, self.reg.sources[s], snapshot=snap, manifest_sha512=manifest,
                            mode=mode, resolver=self._resolver, store_path=self.store.rel(lean), progress=self.say)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        self.store.conn.execute(
            "INSERT INTO job(snapshot, stage, source, state, input, finished_at, detail) VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(snapshot, stage) DO UPDATE SET state = 'done', input = excluded.input,"
            " finished_at = excluded.finished_at, detail = excluded.detail",
            (snap, "integrate", s, "done", out.get("lean_sha512"), utcnow(),
             json.dumps({k: v for k, v in out.items() if isinstance(v, (int, str))})))
        return out

    def latest_lean(self, s: str) -> tuple[Path | None, str | None, str | None]:
        row = self.store.conn.execute(
            "SELECT snapshot, output, input FROM job WHERE source = ? AND stage = 'convert' AND state = 'done'"
            " ORDER BY finished_at DESC LIMIT 1", (s,)).fetchone()
        if row is None or not self.store.abs(row["output"]).exists():
            return None, None, None
        return self.store.abs(row["output"]), row["snapshot"], (row["input"] or "").split("|")[0]


def integrate_store(conn, *, actor: str = "acat build", say=print) -> dict:
    """For `acat build` (inside its transaction): every selected source whose conversion is done is
    integrated (nothing to do when its lean file is already current), and every integrated source that
    is no longer selected is retired. A missing store means there is nothing to integrate."""
    from .integrate import Resolver, integrate, retire
    from .registry import read
    from .store import Store, root
    if not (root() / "store.sqlite").exists():
        return {}
    store = Store()
    try:
        reg = read(store)
        if reg.problems:
            raise ValueError("source registry problems:\n  " + "\n  ".join(reg.problems[:20]))
        sel = store.selected()
        resolver = Resolver(list(reg.sources.values()))
        p = Pipeline(store, reg, integrate=False, progress=say)
        out = {}
        for s, row in sel.items():
            if s not in reg.sources:
                say(f"sources: {s} is selected but no longer in the registry; skipped")
                continue
            lean, snap, manifest = p.latest_lean(s)
            if lean is None:
                continue
            out[s] = integrate(conn, lean, reg.sources[s], snapshot=snap, manifest_sha512=manifest,
                               mode=reg.mode(s, row["mode"]), resolver=resolver, store_path=store.rel(lean),
                               actor=actor, progress=say)
        for scheme, source, mode in conn.execute("SELECT scheme, source, mode FROM v_lean_source").fetchall():
            if mode != "removed" and source not in sel:
                out[source] = retire(conn, scheme, source, actor)
        return out
    finally:
        store.close()
