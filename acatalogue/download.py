"""Streaming downloads into the local store: resumable, verified, polite.

- Resumable: bytes land in `<file>.part`; an interrupted download continues with an HTTP Range request
  guarded by If-Range (the ETag or Last-Modified of the first response), so a file that changed on
  the server starts over instead of being spliced.
- Verified: SHA-512 is computed while the bytes stream (including the part already on disk), and
  checked again when the file is recorded in its manifest. A publisher's checksum (md5, sha1,
  sha256 or sha512, pinned in the registry or read from the publisher's checksum file) must match,
  or the file is kept aside as `<file>.rejected` and never sealed.
- Polite: one connection per host at a time by default, a pause between requests to the same host,
  429/503 and Retry-After waited out with backoff (bounded by `patience`), other errors retried at
  most `max_retries` times. The User-Agent names the project, never a person.
- Exact: `Accept-Encoding: identity`, so the stored bytes are the published file itself.
- Local files (a path or file:// URL) are copied in; SQLite files through SQLite's backup API, so a
  database that is in use is copied consistently.
"""
from __future__ import annotations

import email.utils
import hashlib
import http.client
import os
import re
import shutil
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .fetch import USER_AGENT
from .util import sha512_file, utcnow

CHUNK = 1 << 20
_ALGOS = {32: "md5", 40: "sha1", 64: "sha256", 128: "sha512"}


class DownloadError(RuntimeError):
    pass


@dataclass
class Task:
    source: str
    snapshot: str
    name: str                      # file name in the snapshot
    url: str                       # http(s)://, file://, or an absolute local path
    dest: Path                     # final path of the file
    checksum: str | None = None    # 'sha256:<hex>' pinned, or 'url:<checksum file URL>'
    expected_bytes: int | None = None
    license: str | None = None
    attribution: str | None = None
    result: dict = field(default_factory=dict)


def parse_checksum_file(text: str, name: str) -> str | None:
    """The hex digest for `name` in a checksum file: GNU ('<hex>  name' / '<hex> *name'), BSD
    ('SHA256 (name) = <hex>'), or a file holding a single digest."""
    base = name.rsplit("/", 1)[-1]
    for line in text.splitlines():
        line = line.strip()
        m = re.fullmatch(r"([0-9a-fA-F]{32,128})\s+\*?(.+)", line)
        if m and m.group(2).rsplit("/", 1)[-1] == base:
            return m.group(1).lower()
        m = re.fullmatch(r"[A-Za-z0-9-]+\s*\((.+)\)\s*=\s*([0-9a-fA-F]{32,128})", line)
        if m and m.group(1).rsplit("/", 1)[-1] == base:
            return m.group(2).lower()
    words = text.split()                       # a file that holds only the digest
    if len(words) == 1 and re.fullmatch(r"[0-9a-fA-F]{32,128}", words[0]):
        return words[0].lower()
    return None


def is_local(url: str) -> bool:
    return url.startswith("file://") or url.startswith("/")


def local_path(url: str) -> Path:
    return Path(urllib.parse.unquote(urllib.parse.urlparse(url).path) if url.startswith("file://") else url)


class Downloader:
    def __init__(self, store, *, per_host: int = 1, min_interval: float = 1.0, timeout: float = 60.0,
                 max_retries: int = 6, patience: float = 900.0, progress: Callable[[str], None] = print,
                 report_every: float = 10.0):
        self.store = store
        self.per_host = per_host
        self.min_interval = min_interval
        self.timeout = timeout
        self.max_retries = max_retries
        self.patience = patience
        self.progress = progress
        self.report_every = report_every
        self._hosts: dict[str, threading.Semaphore] = {}
        self._last: dict[str, float] = {}
        self._guard = threading.Lock()
        self.stop = threading.Event()

    # ── politeness ──
    def _host(self, url: str) -> threading.Semaphore:
        host = urllib.parse.urlparse(url).netloc.lower()
        with self._guard:
            return self._hosts.setdefault(host, threading.Semaphore(self.per_host))

    def _pace(self, url: str) -> None:
        host = urllib.parse.urlparse(url).netloc.lower()
        with self._guard:
            wait = self._last.get(host, 0.0) + self.min_interval - time.monotonic()
            self._last[host] = time.monotonic() + max(0.0, wait)
        if wait > 0:
            time.sleep(wait)

    def _open(self, url: str, headers: dict[str, str], method: str = "GET"):
        req = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT,
                                                                  "Accept-Encoding": "identity", **headers})
        return urllib.request.urlopen(req, timeout=self.timeout)

    # ── state ──
    def _row(self, t: Task):
        return self.store.conn.execute("SELECT * FROM download WHERE snapshot = ? AND name = ?",
                                       (t.snapshot, t.name)).fetchone()

    def _set(self, t: Task, **cols) -> None:
        keys = ", ".join(f"{k} = ?" for k in cols)
        self.store.conn.execute(f"UPDATE download SET {keys} WHERE snapshot = ? AND name = ?",
                                (*cols.values(), t.snapshot, t.name))

    def register(self, t: Task) -> None:
        self.store.conn.execute(
            "INSERT INTO download(source, snapshot, name, url, path, state, bytes_total, checksum)"
            " VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(snapshot, name) DO NOTHING",
            (t.source, t.snapshot, t.name, t.url, self.store.rel(t.dest), "pending", t.expected_bytes, t.checksum))

    # ── checksums ──
    def _publisher_digest(self, t: Task) -> tuple[str, str] | None:
        """(algorithm, hex) the publisher states for this file, or None."""
        if not t.checksum:
            return None
        kind, _, value = t.checksum.partition(":")
        if kind in ("md5", "sha1", "sha256", "sha512"):
            return kind, value.lower()
        if kind == "url":
            self._pace(value)
            with self._host(value):
                with self._open(value, {}) as r:
                    text = r.read(1 << 20).decode("utf-8", "replace")
            hexd = parse_checksum_file(text, t.url.rsplit("/", 1)[-1]) or parse_checksum_file(text, t.name)
            if hexd is None:
                raise DownloadError(f"{value} names no checksum for {t.name}")
            if len(hexd) not in _ALGOS:
                raise DownloadError(f"{value}: a {len(hexd)}-digit checksum is not one this can check")
            return _ALGOS[len(hexd)], hexd
        raise DownloadError(f"unknown checksum form {t.checksum!r}")

    # ── the download ──
    def fetch(self, t: Task) -> dict:
        self.register(t)
        row = self._row(t)
        if row["state"] == "done" and t.dest.exists():
            return {"sha512": row["sha512"], "bytes": row["bytes_done"], "skipped": True}
        self._set(t, state="running", started_at=row["started_at"] or utcnow(), error=None)
        try:
            out = self._copy_local(t) if is_local(t.url) else self._http(t)
        except BaseException as exc:
            self._set(t, state="failed", error=f"{type(exc).__name__}: {exc}"[:500])
            self.store.event(t.source, "download", "error", f"{t.name}: {exc}")
            raise
        self._set(t, state="done", sha512=out["sha512"], bytes_done=out["bytes"], bytes_total=out["bytes"],
                  finished_at=utcnow(), checksum_ok=out.get("checksum_ok"), content_type=out.get("content_type"),
                  etag=out.get("etag"), last_modified=out.get("last_modified"))
        self.store.event(t.source, "download", "info",
                         f"{t.name}: {out['bytes']} bytes, sha512 {out['sha512'][:16]}…"
                         + ({1: ", publisher checksum matched", None: ""}.get(out.get("checksum_ok"), "")))
        return out

    def _copy_local(self, t: Task) -> dict:
        src = local_path(t.url)
        if not src.is_file():
            raise DownloadError(f"{src} is not a file")
        t.dest.parent.mkdir(parents=True, exist_ok=True)
        part = t.dest.with_name(t.dest.name + ".part")
        with open(src, "rb") as f:
            is_sqlite = f.read(16) == b"SQLite format 3\x00"
        if is_sqlite:                                  # a consistent copy even of a database in use
            part.unlink(missing_ok=True)
            with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as a, sqlite3.connect(part) as b:
                a.backup(b)
            b.close()
            a.close()
        else:
            shutil.copyfile(src, part)
        digest, n = sha512_file(part)
        os.replace(part, t.dest)
        self.progress(f"  {t.source}: copied {src} ({n:,} bytes){' via SQLite backup' if is_sqlite else ''}")
        return {"sha512": digest, "bytes": n, "checksum_ok": None,
                "content_type": "application/vnd.sqlite3" if is_sqlite else None}

    def _http(self, t: Task) -> dict:
        t.dest.parent.mkdir(parents=True, exist_ok=True)
        part = t.dest.with_name(t.dest.name + ".part")
        want = self._publisher_digest(t)
        busy_waited = 0.0
        errors = 0
        while True:
            if self.stop.is_set():
                raise DownloadError("stopped")
            row = self._row(t)
            have = part.stat().st_size if part.exists() else 0
            sha = hashlib.sha512()
            pub = hashlib.new(want[0]) if want else None
            if have:                                   # the part already on disk is hashed first
                with open(part, "rb") as f:
                    for block in iter(lambda: f.read(CHUNK), b""):
                        sha.update(block)
                        if pub:
                            pub.update(block)
            headers = {}
            validator = row["etag"] or row["last_modified"]
            if have and validator:
                headers = {"Range": f"bytes={have}-", "If-Range": validator}
            elif have:                                 # no validator: a range could splice two versions
                part.unlink()
                have = 0
                sha, pub = hashlib.sha512(), (hashlib.new(want[0]) if want else None)
            self._set(t, attempts=row["attempts"] + 1)
            try:
                self._pace(t.url)
                with self._host(t.url):
                    with self._open(t.url, headers) as r:
                        status = r.status
                        info = r.headers
                        if have and status == 200:     # range ignored or the file changed: start over
                            part.unlink()
                            have = 0
                            sha, pub = hashlib.sha512(), (hashlib.new(want[0]) if want else None)
                        elif status == 206:
                            m = re.match(r"bytes (\d+)-(\d+)/(\d+|\*)", info.get("Content-Range", ""))
                            if not m or int(m.group(1)) != have:
                                raise DownloadError(f"unexpected Content-Range {info.get('Content-Range')!r}")
                        total = self._total(info, status, have)
                        self._set(t, bytes_total=total, etag=info.get("ETag") or row["etag"],
                                  last_modified=info.get("Last-Modified") or row["last_modified"],
                                  content_type=info.get("Content-Type"))
                        self._stream(t, r, part, sha, pub, have, total)
            except urllib.error.HTTPError as exc:
                if exc.code == 416 and have:           # nothing left to send: the part may be whole
                    total = self._range_total(exc.headers)
                    if total == have:
                        return self._finish(t, part, sha, pub, want, have)
                    part.unlink()
                    continue
                if exc.code in (429, 503):
                    wait = self._retry_after(exc.headers) or min(300.0, 5.0 * 2 ** min(errors + 1, 6))
                    if busy_waited + wait > self.patience:
                        raise DownloadError(f"{t.url}: server busy for longer than {self.patience:.0f} s") from exc
                    busy_waited += wait
                    self.progress(f"  {t.source}/{t.name}: HTTP {exc.code}, waiting {wait:.0f} s")
                    time.sleep(wait)
                    continue
                if 500 <= exc.code < 600 and errors < self.max_retries:
                    errors += 1
                    time.sleep(min(120.0, 2.0 ** errors))
                    continue
                raise DownloadError(f"{t.url}: HTTP {exc.code}") from exc
            except (urllib.error.URLError, http.client.HTTPException, TimeoutError, ConnectionError, OSError) as exc:
                if errors < self.max_retries:           # a dropped connection resumes from the part
                    errors += 1
                    self.progress(f"  {t.source}/{t.name}: {type(exc).__name__}: {exc}; resuming")
                    time.sleep(min(120.0, 2.0 ** errors))
                    continue
                raise DownloadError(f"{t.url}: {exc}") from exc
            have = part.stat().st_size
            info_total = self._row(t)["bytes_total"]
            if info_total is not None and have < info_total:
                errors += 1                            # the connection ended early: resume from here
                if errors > self.max_retries:
                    raise DownloadError(f"{t.url}: ended at {have} of {info_total} bytes")
                continue
            return self._finish(t, part, sha, pub, want, have)

    @staticmethod
    def _total(info, status: int, have: int) -> int | None:
        if status == 206:
            m = re.match(r"bytes \d+-\d+/(\d+)", info.get("Content-Range", ""))
            return int(m.group(1)) if m else None
        n = info.get("Content-Length")
        return int(n) if n and n.isdigit() else None

    @staticmethod
    def _range_total(info) -> int | None:
        m = re.match(r"bytes \*/(\d+)", (info or {}).get("Content-Range", "") if info else "")
        return int(m.group(1)) if m else None

    @staticmethod
    def _retry_after(info) -> float | None:
        v = (info or {}).get("Retry-After") if info else None
        if not v:
            return None
        if v.strip().isdigit():
            return float(v)
        try:
            return max(0.0, email.utils.parsedate_to_datetime(v).timestamp() - time.time())
        except (TypeError, ValueError):
            return None

    def _stream(self, t: Task, r, part: Path, sha, pub, have: int, total: int | None) -> None:
        t0, last = time.monotonic(), time.monotonic()
        done = have
        with open(part, "ab") as f:
            while True:
                if self.stop.is_set():
                    raise DownloadError("stopped")
                block = r.read(CHUNK)
                if not block:
                    break
                f.write(block)
                sha.update(block)
                if pub:
                    pub.update(block)
                done += len(block)
                now = time.monotonic()
                if now - last >= self.report_every:
                    last = now
                    self._set(t, bytes_done=done)
                    rate = (done - have) / max(1e-9, now - t0)
                    pct = f" {100 * done / total:5.1f}%" if total else ""
                    self.progress(f"  {t.source}/{t.name}: {done / 1e6:,.1f} MB{pct} ({rate / 1e6:.1f} MB/s)")
            f.flush()
            os.fsync(f.fileno())
        self._set(t, bytes_done=done)

    def _finish(self, t: Task, part: Path, sha, pub, want, size: int) -> dict:
        if t.expected_bytes is not None and size != t.expected_bytes:
            self.progress(f"  {t.source}/{t.name}: {size} bytes, the registry expected {t.expected_bytes}"
                          " (recorded as found)")
        ok = None
        if want:
            got = pub.hexdigest()
            if got != want[1]:
                rejected = t.dest.with_name(t.dest.name + ".rejected")
                os.replace(part, rejected)
                raise DownloadError(f"{t.name}: {want[0]} {got} is not the publisher's {want[1]}; kept as {rejected.name}")
            ok = 1
        os.replace(part, t.dest)
        row = self._row(t)
        return {"sha512": sha.hexdigest(), "bytes": size, "checksum_ok": ok, "etag": row["etag"],
                "last_modified": row["last_modified"], "content_type": row["content_type"]}

    # ── probing (for plans) ──
    def probe(self, url: str) -> dict:
        """Size, validators and range support from a HEAD request (nothing is downloaded)."""
        if is_local(url):
            p = local_path(url)
            return {"bytes": p.stat().st_size if p.exists() else None, "ranges": True, "status": 200 if p.exists() else 404}
        self._pace(url)
        try:
            with self._host(url):
                with self._open(url, {}, method="HEAD") as r:
                    n = r.headers.get("Content-Length")
                    return {"status": r.status, "bytes": int(n) if n and n.isdigit() else None,
                            "ranges": r.headers.get("Accept-Ranges", "").lower() == "bytes",
                            "etag": r.headers.get("ETag"), "last_modified": r.headers.get("Last-Modified"),
                            "content_type": r.headers.get("Content-Type")}
        except urllib.error.HTTPError as exc:
            return {"status": exc.code, "bytes": None}
