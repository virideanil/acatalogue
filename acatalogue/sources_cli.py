"""`acat sources …`: choose sources, add your own, download, convert and integrate them."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .registry import COLUMNS, conflicts, read
from .store import Store
from .util import utcnow


def _mb(n) -> str:
    if n in (None, ""):
        return "?"
    n = int(n)
    return f"{n / 1e9:,.1f} GB" if n >= 1e9 else f"{n / 1e6:,.1f} MB" if n >= 1e5 else f"{n / 1e3:,.0f} kB"


def _size(reg, sid: str) -> int | None:
    """Download size: the files' sizes when all are known, else the registry's estimate."""
    known = [int(f["bytes"]) for f in reg.files.get(sid, []) if str(f.get("bytes") or "").isdigit()]
    if known and len(known) == len(reg.files.get(sid, [])):
        return sum(known)
    est = str(reg.sources[sid].get("size") or "")
    return int(est) if est.isdigit() else None


def cmd_sources(args) -> int:
    store = Store(args.store) if getattr(args, "store", None) else Store()
    reg = read(store)
    if reg.problems and args.action not in ("list", "show", "presets"):
        print("the registry has problems:\n  " + "\n  ".join(reg.problems[:30]), file=sys.stderr)
        return 2
    return {"list": _list, "show": _show, "presets": _presets, "select": _select, "deselect": _deselect,
            "add": _add, "plan": _plan, "run": _run, "status": _status, "verify": _verify, "search": _search,
            "term": _term}[args.action](args, store, reg)


def _search(args, store, reg) -> int:
    from . import db as dbm
    from .leansearch import search
    if not args.ids:
        print("acat sources search <words>", file=sys.stderr)
        return 2
    conn = dbm.connect(args.db, readonly=True)
    hits = search(conn, " ".join(args.ids), schemes=args.scheme.split(",") if args.scheme else None,
                  limit=args.limit)
    for h in hits:
        extra = f"  ({h['kind']} {h['lang'] or '-'}: {h['matched']})" if h["matched"] != h["label"] else ""
        print(f"{h['id']:36s} {h['label']}{extra}  [{h['mode']}]")
    return 0 if hits else 1


def _term(args, store, reg) -> int:
    from . import db as dbm
    from .leansearch import record
    conn = dbm.connect(args.db, readonly=True)
    for ident in args.ids:
        rec = record(conn, ident)
        if rec is None:
            print(f"{ident}: not in any integrated source", file=sys.stderr)
            return 1
        print(json.dumps(rec, ensure_ascii=False, indent=2))
    return 0


def _list(args, store, reg) -> int:
    sel = store.selected()
    rows = [s for s in reg.sources.values()
            if (not args.selected or s["id"] in sel) and (not args.domain or args.domain in (s.get("domains") or "").split())
            and (not args.preset or s["id"] in reg.presets.get(args.preset, []))]
    print(f"{'':2}{'id':28s} {'size':>9s}  {'licence':22s} {'langs':>5s}  {'mode':6s} perspective")
    for s in sorted(rows, key=lambda s: (s.get("recommend") != "starter", s["id"])):
        mark = "* " if s["id"] in sel else "  "
        lg = (s.get("languages") or "").strip()
        langs = lg if lg.isdigit() else (str(len(lg.split())) if lg else "?")
        print(f"{mark}{s['id']:28s} {_mb(_size(reg, s['id'])):>9s}  {(s.get('license') or '')[:22]:22s} {langs:>5s}  "
              f"{reg.mode(s['id'], sel[s['id']]['mode'] if s['id'] in sel else None):6s} "
              f"{(s.get('perspective') or '')[:70]}")
    print(f"\n{len(rows)} sources ({sum(1 for s in rows if s['id'] in sel)} selected: *)."
          f" Presets: {', '.join(sorted(reg.presets))}. `acat sources select preset:<name>` to start from one.")
    if reg.problems:
        print(f"registry problems: {len(reg.problems)} (run `acat verify`)", file=sys.stderr)
    return 0


def _show(args, store, reg) -> int:
    for sid in args.ids:
        if sid not in reg.sources:
            print(f"no source {sid!r}", file=sys.stderr)
            return 2
        s = reg.sources[sid]
        for k in COLUMNS:
            if s.get(k):
                print(f"{k:18s} {s[k]}")
        print("files:")
        for f in reg.files.get(sid, []):
            print(f"  {f['name']:36s} {_mb(f.get('bytes')):>9s}  {f['url']}" + (f"  [{f['checksum'][:24]}…]" if f.get("checksum") else ""))
        for d in store.conn.execute("SELECT snapshot, name, state, bytes_done, sha512 FROM download WHERE source = ?"
                                    " ORDER BY snapshot, name", (sid,)):
            print(f"  downloaded {d['snapshot']}/{d['name']}: {d['state']}, {_mb(d['bytes_done'])}"
                  + (f", sha512 {d['sha512'][:16]}…" if d["sha512"] else ""))
        for j in store.conn.execute("SELECT * FROM job WHERE source = ? ORDER BY snapshot, stage", (sid,)):
            print(f"  {j['stage']} {j['snapshot']}: {j['state']}" + (f" -> {j['output']}" if j["output"] else "")
                  + (f"  ({j['error'][:120]})" if j["error"] else ""))
        print()
    return 0


def _presets(args, store, reg) -> int:
    for name, ids in sorted(reg.presets.items()):
        total = sum(_size(reg, i) or 0 for i in ids)
        print(f"{name:20s} {len(ids):3d} sources, about {_mb(total)}: {', '.join(ids)}")
    return 0


def _select(args, store, reg) -> int:
    try:
        ids = reg.expand(args.ids)
    except KeyError as exc:
        print(f"acat sources: {exc.args[0]}", file=sys.stderr)
        return 2
    now = list(store.selected())
    problems = conflicts(reg, list(dict.fromkeys(now + ids)))
    if problems:
        print("acat sources: " + "; ".join(problems) + " (deselect the other one first)", file=sys.stderr)
        return 2
    via = next((n for n in args.ids if n.startswith("preset:")), "user")
    closed = [i for i in ids if not reg.files.get(i)]
    for i in closed:
        s = reg.sources[i]
        print(f"  {i}: not selected: no public file ({s.get('access') or 'none'}; {s.get('license') or 'licence unknown'})."
              f" See {s.get('homepage') or 'its homepage'}", file=sys.stderr)
    ids = [i for i in ids if i not in closed]
    for i in ids:
        store.select(i, via=via, mode=args.mode)
    total = sum(_size(reg, i) or 0 for i in ids)
    print(f"selected {len(ids)}: {', '.join(ids)} (about {_mb(total)} to download)."
          " Next: `acat sources plan`, then `acat sources run`.")
    return 0


def _deselect(args, store, reg) -> int:
    for i in args.ids:
        print(f"{i}: {'deselected' if store.deselect(i) else 'was not selected'}")
    print("`acat build` takes deselected sources out of the catalogue's current view (deprecated, superseded,"
          " never deleted); their bytes stay in the store.")
    return 0


def _add(args, store, reg) -> int:
    sid = args.ids[0]
    if sid in reg.sources:
        print(f"acat sources: {sid!r} exists; choose another id", file=sys.stderr)
        return 2
    urls = list(args.url or []) + [str(Path(p).resolve()) for p in (args.path or [])]
    if not urls:
        print("acat sources add: give --url (repeatable) or --path (a file on this machine)", file=sys.stderr)
        return 2
    if args.options:
        json.loads(args.options)
    row = {"id": sid, "title": args.title or sid, "publisher": args.publisher or "", "perspective": args.perspective or "",
           "domains": args.domains or "", "kind": "", "languages": args.languages or "", "license": args.license or "unknown",
           "license_url": "", "homepage": args.homepage or "", "update": "", "access": "local" if args.path else "open",
           "converter": args.converter, "options": args.options or "{}", "scheme": args.scheme or sid,
           "integrate": args.mode or "full", "iri_prefixes": args.iri_prefixes or "", "curie_prefixes": "",
           "wikidata_property": "", "notes": args.notes or "", "added_at": utcnow()}
    from .registry import row_problems
    from .convert import registry as converters
    problems = row_problems({**row, "reviewer": "the store's owner"}, "new source", set(converters()))
    if problems:
        print("acat sources add:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 2
    cols = [k for k in row]
    quoted = ", ".join('"' + c + '"' for c in cols)
    store.conn.execute(f"INSERT INTO user_source({quoted}) VALUES ({','.join('?' * len(cols))})",
                       [row[c] for c in cols])
    for u in urls:
        name = args.name if (args.name and len(urls) == 1) else Path(u.split("?")[0].rstrip("/")).name
        store.conn.execute("INSERT INTO user_file(source, name, url, format) VALUES (?,?,?,?)",
                           (sid, name, u, Path(name).suffix.lstrip(".")))
    store.select(sid, via="user", mode=args.mode)
    print(f"added and selected {sid} ({len(urls)} file(s), converter {args.converter}). It lives in this store only;"
          " `acat sources run` downloads (or copies) and integrates it.")
    return 0


def _plan(args, store, reg) -> int:
    from .pipeline import Pipeline
    sel = list(store.selected())
    if not sel:
        print("nothing selected: `acat sources list`, then `acat sources select <id>|preset:<name>`")
        return 0
    rows = Pipeline(store, reg, integrate=False, refresh=args.refresh).plan(sel)
    total = 0
    print(f"{'source':28s} {'snapshot':30s} {'files':>5s} {'size':>9s}  state")
    for r in rows:
        state = ("converted" if r["converted"] else "sealed, to convert" if r["sealed"]
                 else f"{r['downloaded']}/{r['files']} downloaded")
        total += r["bytes"] or 0
        print(f"{r['source']:28s} {r['snapshot']:30s} {r['files']:5d} {_mb(r['bytes']):>9s}  {state}; {r['mode']}; {r['license']}")
    print(f"\n{len(rows)} sources, about {_mb(total)} in total, into {store.root}")
    return 0


def _run(args, store, reg) -> int:
    from .pipeline import Pipeline
    sel = list(store.selected())
    if args.only:
        sel = [s for s in args.only.split(",") if s in sel]
    if not sel:
        print("nothing selected to run")
        return 0
    p = Pipeline(store, reg, db_path=args.db, workers=args.workers, per_host=args.per_host,
                 integrate=not args.no_integrate, refresh=args.refresh)
    print(f"running {len(sel)} source(s) into {store.root}")
    res = p.run(sel)
    failed = {s: r for s, r in res.items() if not s.startswith("_") and (r.get("error") or r.get("failed_files"))}
    for s, r in res.get("_integration", {}).items():
        print(f"  {s}: " + (r.get("skipped") or f"{r.get('concepts', 0):,} concepts, {r.get('labels', 0):,} names,"
                                                f" {r.get('mappings', 0):,} mappings, {r.get('claims', 0):,} claims,"
                                                f" {r.get('hub_mappings', 0):,} via Wikidata ({r.get('mode')})"))
    for s, r in failed.items():
        print(f"  {s}: FAILED " + (r.get("error") or "; ".join(r.get("failed_files", []))), file=sys.stderr)
    return 1 if failed else 0


def _status(args, store, reg) -> int:
    for d in store.conn.execute("SELECT snapshot, name, state, bytes_done, bytes_total, attempts, error FROM download"
                                " ORDER BY snapshot, name"):
        pct = f"{100 * d['bytes_done'] / d['bytes_total']:5.1f}%" if d["bytes_total"] else "     "
        print(f"download  {d['snapshot']:30s} {d['name']:34s} {d['state']:8s} {pct} {_mb(d['bytes_done']):>9s}"
              f"  tries {d['attempts']}" + (f"  {d['error'][:80]}" if d["error"] else ""))
    for j in store.conn.execute("SELECT snapshot, stage, state, finished_at, error FROM job ORDER BY snapshot, stage"):
        print(f"{j['stage']:9s} {j['snapshot']:30s} {j['state']:8s} {j['finished_at'] or ''}"
              + (f"  {j['error'][:100]}" if j["error"] else ""))
    print("\nrecent events:")
    for e in store.conn.execute("SELECT * FROM event ORDER BY seq DESC LIMIT 12"):
        print(f"  {e['at']} {e['level']:5s} {e['source'] or '':24s} {e['stage'] or '':9s} {e['message'][:100]}")
    return 0


def _verify(args, store, reg) -> int:
    from .corpusfile import CorpusFile
    from .util import sha512_file
    ok = True
    for p in sorted((store.root / "corpora").glob("*/corpus.sqlite")):
        c = CorpusFile(p, readonly=True)
        good, msg = c.verify()
        print(f"manifest: {msg}" + ("" if c.sealed else "  (not sealed: still downloading)"))
        ok &= good
        c.close()
    for j in store.conn.execute("SELECT snapshot, output, output_sha512 FROM job WHERE stage = 'convert' AND state = 'done'"):
        path = store.abs(j["output"])
        if not path.exists():
            print(f"lean: {j['snapshot']}: file not on this machine")
            continue
        good = sha512_file(path)[0] == j["output_sha512"]
        print(f"lean: {path.name}: {'SHA-512 OK' if good else 'SHA-512 DIFFERS from the conversion record'}")
        ok &= good
    return 0 if ok else 1


def add_parser(sub) -> None:
    p = sub.add_parser("sources", help="choose open sources (or add your own), download, convert and integrate them")
    p.add_argument("action", choices=["list", "show", "presets", "select", "deselect", "add", "plan", "run", "status",
                                      "verify", "search", "term"])
    p.add_argument("-n", "--limit", type=int, default=20, help="search: hits per source")
    p.add_argument("ids", nargs="*", help="source ids or preset:<name>")
    p.add_argument("--store", type=Path, help="the local store (default: $ACAT_STORE or ./store)")
    p.add_argument("--preset", help="list: only this preset's sources")
    p.add_argument("--domain", help="list: only sources in this domain (e.g. acat/language)")
    p.add_argument("--selected", action="store_true", help="list: only selected sources")
    p.add_argument("--mode", choices=["full", "attach"], help="select/add: integrate fully, or attach (search in place)")
    p.add_argument("--workers", type=int, default=4, help="run: parallel downloads (default 4)")
    p.add_argument("--per-host", type=int, default=1, help="run: connections per host (default 1)")
    p.add_argument("--only", help="run: comma-separated subset of the selection")
    p.add_argument("--no-integrate", action="store_true", help="run: download and convert only")
    p.add_argument("--refresh", action="store_true", help="plan/run: take a new dated snapshot of every source")
    p.add_argument("--url", action="append", help="add: a file URL (repeatable)")
    p.add_argument("--path", action="append", help="add: a file on this machine (repeatable)")
    p.add_argument("--name", help="add: the file's name in the store")
    p.add_argument("--converter", default="csv", help="add: rdf, obo, csv, sqlite, geonames, … (default csv)")
    p.add_argument("--options", help="add: the converter's options as JSON")
    for k in ("title", "publisher", "perspective", "license", "homepage", "languages", "domains", "scheme",
              "iri-prefixes", "notes"):
        p.add_argument(f"--{k}", help=f"add: the source's {k.replace('-', ' ')}"
                       + ("; search: only these schemes (comma-separated)" if k == "scheme" else ""))
    p.set_defaults(fn=cmd_sources)
