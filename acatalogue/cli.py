"""`acat` — the command line. Run `acat -h` or `acat <command> -h`."""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

from . import db as dbm
from .db import DEFAULT_DB

ANSI_MATCH, ANSI_DIM, ANSI_ID, ANSI_OFF = "\x1b[1;31m", "\x1b[2m", "\x1b[36m", "\x1b[0m"


def _color(flag: str) -> bool:
    if flag == "always":
        return True
    if flag == "never" or os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


def _render(parts: list[dict], color: bool) -> str:
    out = []
    for p in parts:
        t = p["t"].replace("\n", " ")
        out.append(f"{ANSI_MATCH}{t}{ANSI_OFF}" if (p["m"] and color) else (f"[{t}]" if p["m"] else t))
    return "".join(out)


def _ro(args) -> "dbm.sqlite3.Connection":
    return dbm.connect(args.db, readonly=True)


# ─── commands ────────────────────────────────────────────────────────────────


def cmd_build(args) -> int:
    from .build import build
    report = build(args.db)
    dangling = report["links"]["facets_dangling"] + report["links"]["mappings_dangling"]
    print(f"built {args.db}")
    if dangling:
        print(f"{len(dangling)} links point at concepts that do not exist:", *dangling[:20], sep="\n  ")
        return 1
    return 0


def cmd_semantic(args) -> int:
    from . import semantic
    conn = dbm.connect(args.db)
    with conn:
        print(json.dumps(semantic.build(conn, dims=args.dims, k=args.k), indent=2))
    return 0


def cmd_grep(args) -> int:
    from .grep import GrepError, grep
    color = _color(args.color)
    conn = _ro(args)
    try:
        res = grep(conn, args.pattern, mode=args.mode, scope=args.scope, limit=args.limit, under=args.under,
                   lang=args.lang)
    except GrepError as exc:
        print(f"acat grep: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(res.as_dict(), ensure_ascii=False, indent=None if args.jsonl else 2))
        return 0 if res.hits else 1
    if args.explain:
        for s in res.sql:
            print(f"{ANSI_DIM if color else ''}-- {s}{ANSI_OFF if color else ''}")
        for n in res.notes:
            print(f"{ANSI_DIM if color else ''}-- note: {n}{ANSI_OFF if color else ''}")
    if args.count:
        counts: dict[str, int] = {}
        for h in res.hits:
            counts[h.type] = counts.get(h.type, 0) + 1
        for k, v in sorted(counts.items()):
            print(f"{k}\t{v}")
        return 0 if res.hits else 1
    seen = set()
    for h in res.hits:
        if args.files_only:
            if h.target not in seen:
                seen.add(h.target)
                print(h.target)
            continue
        tag = h.type + (f"[{h.lang}]" if h.lang else "")
        ident = f"{ANSI_ID}{h.target}{ANSI_OFF}" if color else h.target
        print(f"{ident}\t{tag}\t{h.title}\t{_render(h.parts, color)}")
    if not args.json and sys.stderr.isatty():
        print(f"{res.total} hits in {res.elapsed_ms} ms", file=sys.stderr)
    return 0 if res.hits else 1


def cmd_grep_db(args) -> int:
    from .grep import grep_any
    color = _color(args.color)
    hits, sqls = grep_any(args.file, args.pattern, mode="regex" if args.regex else "substring",
                          limit_per_column=args.limit, tables=args.table or None)
    if args.explain:
        for s in sqls:
            print(f"-- {s}")
    if args.json:
        print(json.dumps([h.__dict__ for h in hits], ensure_ascii=False, indent=2))
    else:
        for h in hits:
            print(f"{h.table}.{h.column}[{h.key}]\t{_render(h.parts, color)}")
    return 0 if hits else 1


def cmd_sql(args) -> int:
    conn = _ro(args)
    cur = conn.execute(args.query)
    cols = [d[0] for d in cur.description or []]
    rows = cur.fetchmany(args.limit)
    if args.json:
        print(json.dumps([dict(zip(cols, r)) for r in rows], ensure_ascii=False, indent=2, default=str))
    else:
        print("\t".join(cols))
        for r in rows:
            print("\t".join("" if v is None else str(v) for v in r))
    return 0


def cmd_show(args) -> int:
    from .views import resolve
    conn = _ro(args)
    rec = resolve(conn, args.id)
    if rec is None:
        print(f"acat show: nothing is called {args.id!r}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(rec, ensure_ascii=False, indent=2, default=str))
        return 0
    if rec["kind"] != "concept":
        for k, v in rec.items():
            print(f"{k:14s} {v}")
        return 0
    print(f"{rec['label']}  ({rec['id']})  [{rec['status']}]")
    if rec.get("scope_note"):
        print(f"  {rec['scope_note']}")
    if rec.get("time_from") is not None or rec.get("time_to") is not None:
        print(f"  when: {rec.get('time_from')} .. {rec.get('time_to')} (astronomical years)")
    print(f"  labels: {len(rec['labels'])} in {rec['n_label_langs']} languages; Wikipedia editions: {rec['langs']}")
    wanted = {"tr", "ar", "zh", "hi", "sw", "es", "ru", "fr", "yo", "id"}
    sample = [f"{l['lang']}:{l['text']}" for l in rec["labels"] if l["kind"] == "pref" and l["lang"] in wanted]
    if sample:
        print("  e.g. " + " · ".join(sample))
    for key in ("broader", "narrower", "related", "facets"):
        if rec[key]:
            print(f"  {key}: " + ", ".join(f"{x['label']} ({x['id']})" for x in rec[key][:25]))
    for m in rec["mappings"]:
        print(f"  mapping: {m['relation']} {m['id']} {m['label']} [{m['method']}, {m['status']}]")
    for d in rec["documents"]:
        print(f"  document: {d['id']} — {d['license']} — {d['url']}")
    for c in rec["claims"][:20]:
        print(f"  claim: {c['subject']} {c['predicate_label'] or c['predicate']} {c['object_label'] or c['value']}"
              f"  [{c['epistemic']}, rank {c['rank']}]")
    for n in rec["neighbors"]:
        print(f"  near: {n['label']} ({n['id']}) {n['score']:.3f} [{n['model']}]")
    for p in rec["provenance"]:
        print(f"  from: {p['source']} sha512:{p['sha512'][:16]}…")
    return 0


def cmd_tree(args) -> int:
    from .views import tree
    for line in tree(_ro(args), args.root, args.depth, args.scheme):
        print(line)
    return 0


def cmd_stats(args) -> int:
    from .views import stats
    print(json.dumps(stats(_ro(args), str(args.db)), ensure_ascii=False, indent=2))
    return 0


def _rr_cell(v: dict) -> str:
    if v["rr"] is None:
        return "no baseline"
    if v["rr"] == 0:
        return "none tagged"
    lo = f"{math.log2(v['rr_lo']):+.1f}" if v["rr_lo"] else "-inf"
    return f"{v['log2_rr']:+.2f} [{lo},{math.log2(v['rr_hi']):+.1f}]"


def _print_baseline_audit(b: dict | None) -> None:
    if not b:
        print("\n(no stored baseline audit: run `acat build`)")
        return
    for level, title in (("regions", "UN M49 regions"), ("subregions", "UN M49 sub-regions")):
        r = b[level]
        print(f"\n{title}: {r['n']} place-tagged concepts, each split evenly over its regions.")
        print("log2 representation ratio vs each baseline (0 = parity, +1 = twice the baseline share),"
              " [95% Wilson interval]")
        names = list(r["groups"][0]["vs"]) if r["groups"] else []
        print(f"{'group':34s} {'share':>6s}  " + "  ".join(f"{n:>20s}" for n in names))
        for g in r["groups"]:
            print(f"{g['label'][:34]:34s} {g['share']:6.1%}  " + "  ".join(f"{_rr_cell(g['vs'][n]):>20s}"
                                                                         for n in names))
        for name, d in r["distribution"].items():
            if d:
                verdict = "beyond" if d["exceeds_null"] else "within"
                print(f"  vs {name}: JSD {d['jsd_bits']:.3f} bits [{d['jsd_lo']:.3f}, {d['jsd_hi']:.3f}], "
                      f"{verdict} random sampling (null p95 {d['null_p95']:.3f}); Gini of ratios {d['gini_rr']:.2f}")
        print(f"  normalized entropy {r['entropy_norm']:.2f}; tagged only above this level: {r['tagged_above_level']};"
              f" concepts with no place: {r['untagged']}")
        for dim, cov in r["baseline_coverage"].items():
            print(f"  {dim} ({cov['as_of']}): {cov['areas_with_value']}/{cov['areas']} areas have a value")
    print("\nSibling parity (children of one parent; CV = spread of subtree sizes):")
    for s in b["siblings"][:10]:
        q = s["quantities"]["subtree"]
        flags = ", ".join(f"{f['label']} ({f['subtree']})" for f in s["flags"])
        print(f"  CV {q['cv']:.2f}  {s['label'][:40]:40s} {s['children']:3d} children, sizes {q['min']}-{q['max']}"
              + (f"; look at: {flags}" if flags else ""))
    at = b["attention"]
    print(f"\nAttention: median Wikipedia editions {at['median']} without {'/'.join(at['excluded_editions'])}"
          f" ({at['median_all']} with them); {at['concepts_with_bot_editions']} concepts change")
    ev = b.get("evidence")
    if ev:
        print(f"\nEvidence: {ev['all']['sourced']} of {ev['all']['statements']} current Wikidata statements cite a"
              f" source; hierarchy statements: {ev['hierarchy']['sourced']} of {ev['hierarchy']['statements']}"
              f" ({ev['definition']})")
    print("\nWho decided the accepted crosswalks:")
    for kind, rels in b["review"]["accepted_by_decider"].items():
        print(f"  {kind:32s} " + ", ".join(f"{k} {v}" for k, v in sorted(rels.items())))
    print(f"  human reviews recorded: {b['review']['human_reviews']}")


def cmd_audit(args) -> int:
    from .views import audit
    a = audit(_ro(args))
    if args.json:
        print(json.dumps(a, ensure_ascii=False, indent=2))
        return 0
    print("Coverage by domain (langs = Wikipedia language editions of the matched item)")
    print(f"{'domain':34s} {'concepts':>8s} {'matched':>8s} {'docs':>6s} {'median':>7s} {'min':>5s}  thinnest")
    for d in a["domains"]:
        print(f"{d['label'][:34]:34s} {d['concepts']:8d} {d['reconciled']:8d} {d['docs']:6d} "
              f"{str(d['median_langs']):>7s} {str(d['min_langs']):>5s}  {d['min_langs_id']}")
    print("\nThinnest coverage (fewest language editions):")
    for t in a["thinnest"][:15]:
        print(f"  {t['langs']:4d}  {t['label']} ({t['id']})")
    print("\nConcepts tagged per world region (UN M49):")
    for r in a["regions"]:
        print(f"  {r['tagged']:4d}  {r['label']}")
    h = a["hierarchy_vs_wikidata"]
    print(f"\nACAT parent links also stated by Wikidata: {h['stated']}; not stated: {h['not_stated']}")
    _print_baseline_audit(a.get("baseline_audit"))
    print(f"Label languages: {a['label_language_count']}; concepts without a Wikidata match: {len(a['unmatched'])}")
    for n in a["notes"]:
        print(f"note: {n}")
    return 0


def cmd_verify(args) -> int:
    from . import ledger
    from .compendium import read_all
    from .corpusfile import CorpusFile, list_corpora
    ok = True
    _, problems = read_all()
    print(f"seeds: {'valid' if not problems else f'{len(problems)} problems'}")
    for p in problems:
        print("  ", p)
    ok &= not problems
    for path in list_corpora():
        c = CorpusFile(path, readonly=True)
        good, msg = c.verify()
        print(f"corpus: {msg}" + ("" if c.sealed else "  (NOT sealed)"))
        ok &= good and c.sealed
    if Path(args.db).exists():
        from .checks import database_checks, skos_checks
        good, n, msg = ledger.verify(_ro(args))
        print(f"ledger: {msg}")
        ok &= good
        rw = dbm.connect(args.db)                 # FTS5 integrity-check is issued as an INSERT; it reads only
        try:
            problems = database_checks(rw)
            print("database: " + ("integrity and search indexes OK" if not problems else f"{len(problems)} problems"))
            for p in problems:
                print("  ", p)
            ok &= not problems
            for name, found in skos_checks(rw).items():
                print(f"skos {name}: " + ("OK" if not found else f"{len(found)} violations, e.g. {found[:3]}"))
                ok &= not found
        finally:
            rw.close()
    return 0 if ok else 1


def cmd_serve(args) -> int:
    from .server import serve
    serve(args.db, host=args.host, port=args.port)
    return 0


def cmd_export_graph(args) -> int:
    from .views import audit, graph
    conn = _ro(args)
    g = graph(conn)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(g, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {args.out}: {len(g['nodes'])} nodes, {len(g['edges'])} edges")
    # the stored audit beside it, so a static page can show it without the API
    a = out.with_name("audit.json")
    a.write_text(json.dumps(audit(conn), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {a}")
    return 0


def cmd_compendium_md(args) -> int:
    from .docs import write_compendium_md
    n = write_compendium_md(_ro(args), Path(args.out))
    print(f"wrote {args.out}: {n} concepts")
    return 0


def _wikidata_descriptions(qids: set[str]) -> dict[str, tuple[str, int]]:
    """English description and Wikipedia-edition count of Wikidata items, from the latest entities corpus."""
    from .build import latest_corpus
    from .sources.wikidata import wikipedia_editions
    ents = latest_corpus("wikidata-entities")
    out: dict[str, tuple[str, int]] = {}
    if ents is None:
        return out
    for it in ents.items():
        if it["name"].startswith("entities/"):
            for qid, e in json.loads(ents.get(it["name"])).get("entities", {}).items():
                if qid in qids:
                    desc = e.get("descriptions", {}).get("en", {}).get("value", "")
                    out[qid] = (desc, len(wikipedia_editions(e.get("sitelinks", {}))))
    return out


def cmd_review(args) -> int:
    from . import review
    from .sources import wikidata
    decisions = wikidata.read_decisions()
    files, problems = review.read_reviews()
    if problems:
        print("review files are invalid:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 2
    if args.action != "queue":
        if not args.reviewer:
            print("acat review: --reviewer is required (the person deciding)", file=sys.stderr)
            return 2
        if args.human == args.agent:
            print("acat review: say who decides: --human (a person) or --agent (an AI agent; recorded, never"
                  " decisive)", file=sys.stderr)
            return 2
        if not any(d["from"] == args.frm and d["to"] == args.to for d in decisions):
            print(f"acat review: no proposal {args.frm} -> {args.to} in {wikidata.DECISIONS.name}", file=sys.stderr)
            return 2
        try:
            path = review.append(args.reviewer, review.mapping_target(args.frm, args.to), args.action,
                                 relation=args.relation or "", kind="agent" if args.agent else "human",
                                 perspective=args.perspective or "", rationale=args.rationale or "")
        except review.SeedError as exc:
            print(f"acat review: {exc}", file=sys.stderr)
            return 2
        print(f"recorded in {path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path};"
              " run `acat build` to apply it")
        return 0
    reviewed = {r["target"] for sf in files for r in sf.rows if r["reviewer_kind"] == "human"}
    pending = [d for d in decisions if d["status"] == "accepted" and d["to"]
               and review.reviewer_kind(d["reviewer"]) == "AI agent"
               and review.mapping_target(d["from"], d["to"]) not in reviewed
               and (not args.relation or d["relation"] == args.relation)]
    conn = _ro(args)
    if args.under:
        sub = {r[0] for r in conn.execute(
            "WITH RECURSIVE s(id) AS (SELECT ? UNION SELECT b.child FROM broader b JOIN s ON b.parent = s.id)"
            " SELECT id FROM s", (args.under,))}
        pending = [d for d in pending if d["from"] in sub]
    order = {"exactMatch": 0, "closeMatch": 1}
    pending.sort(key=lambda d: (order.get(d["relation"], 2), d["from"]))
    total_ai = sum(1 for d in decisions if review.reviewer_kind(d["reviewer"]) == "AI agent" and d["status"] == "accepted")
    print(f"{len(pending)} AI decisions await a person ({total_ai - len(pending)} of {total_ai} reviewed)."
          " exactMatch first: it is transitive, so one wrong link spreads.\n")
    shown = pending[:args.limit]
    wd = _wikidata_descriptions({d["to"][3:] for d in shown if d["to"].startswith("wd/")})
    for i, d in enumerate(shown, 1):
        ours = conn.execute("SELECT label, coalesce(scope_note, '') FROM concept WHERE id = ?", (d["from"],)).fetchone()
        theirs = conn.execute("SELECT label FROM concept WHERE id = ?", (d["to"],)).fetchone()
        desc, editions = wd.get(d["to"][3:], ("", 0))
        print(f"[{i}] {d['relation']}  {d['from']} \"{ours[0] if ours else '?'}\"  ->  {d['to']}"
              f" \"{theirs[0] if theirs else '?'}\"")
        if ours and ours[1]:
            print(f"      ours:     {ours[1][:150]}")
        print(f"      Wikidata: {desc[:150] or '(no English description)'}; {editions} Wikipedia editions")
        print(f"      proposed by {d['reviewer']} via {d['method']}" + (f": {d['note']}" if d["note"] else ""))
        print(f"      acat review approve {d['from']} {d['to']} --reviewer \"<your name>\" --human\n")
    return 0


def cmd_eval(args) -> int:
    from .evaluate import PANEL, run
    conn = dbm.connect(args.db)
    dbm.init_schema(conn)
    langs = tuple(args.langs.split(",")) if args.langs else PANEL
    systems = tuple(args.systems.split(",")) if args.systems else None
    res = run(conn, langs, systems, boot=args.boot, perms=args.perms)
    missing = [lang for lang in langs if lang not in res["langs"]]
    print(f"\nrun {res['run_id']}: {res['queries']} known-item queries in {len(res['langs'])} languages, each language"
          " and its variants left out of the index while its queries run (95% bootstrap intervals)"
          + (f"; no queries in {', '.join(missing)}" if missing else ""))
    print(f"{'system':12s} {'MRR@10':>22s} {'Recall@10':>10s} {'nDCG@10':>8s}  worst language")
    for s, v in res["summary"].items():
        macro = {m: (val, lo, hi) for lang, m, val, lo, hi, n in v["rows"] if lang == ""}
        worst = [r for r in v["rows"] if r[0] == "*worst"]
        mrr = macro["mrr@10"]
        print(f"{s:12s} {mrr[0]:8.3f} [{mrr[1]:.3f}, {mrr[2]:.3f}] {macro['recall@10'][0]:10.3f} {macro['ndcg@10'][0]:8.3f}"
              f"  {worst[1][1].split(':')[1]} {worst[0][2]:.3f}")
    for t in res["tests"]:
        print(f"  {t['a']} vs {t['b']}: macro MRR@10 difference {t['diff']:+.3f}, paired randomization p = {t['p']:.4f}")
    return 0


def cmd_embed(args) -> int:
    from .embed import embed_labels
    conn = dbm.connect(args.db)
    stats = embed_labels(conn, args.model, tuple(args.kinds.split(",")))
    print(f"{stats['model']}: {stats['labels']} labels, {stats['distinct_texts']} distinct texts; {stats['embedded']}"
          f" embedded now, {stats['already_had']} already had vectors ({stats['seconds']} s)")
    return 0


def cmd_bake(args) -> int:
    from .bake import bake
    conn = dbm.connect(args.db)
    stats = bake(conn, max_steps=args.steps)
    print(f"baked {stats['model']}: {stats['nodes']} particles, {stats['steps']} steps"
          f" ({'at rest' if stats['asleep'] else 'step limit reached'}), {stats['ms']} ms in Node")
    return 0


def cmd_fetch(args) -> int:
    from .sources import external, m49, wikidata, wikipedia
    if args.source == "m49":
        c = m49.fetch()
    elif args.source == "external":
        c = external.fetch()
    elif args.source == "worldbank":
        from .sources import worldbank
        c = worldbank.fetch()
    elif args.source == "wikidata-statements":
        decisions = wikidata.read_decisions()
        qids = sorted({d["to"][3:] for d in decisions if d["status"] == "accepted" and d["to"].startswith("wd/")},
                      key=lambda q: int(q[1:]))
        c = wikidata.fetch_statements(qids)
        c.seal()
    elif args.source == "wikidata":
        decisions = wikidata.read_decisions()
        qids = sorted({d["to"][3:] for d in decisions if d["status"] == "accepted" and d["to"].startswith("wd/")},
                      key=lambda q: int(q[1:]))
        c = wikidata.fetch_entities(qids)
        wikidata.fetch_claims(qids, c)
        c.seal()
    else:
        from .build import latest_corpus
        decisions = wikidata.read_decisions()
        wanted = {d["to"][3:] for d in decisions if d["status"] == "accepted"
                  and d["relation"] in wikidata.LABEL_RELATIONS}
        ents = latest_corpus("wikidata-entities")
        if ents is None:
            print("fetch wikidata entities first", file=sys.stderr)
            return 1
        titles = []
        for it in ents.items():
            if it["name"].startswith("entities/"):
                for qid, e in json.loads(ents.get(it["name"]))["entities"].items():
                    if qid in wanted and "enwiki" in e.get("sitelinks", {}):
                        titles.append(e["sitelinks"]["enwiki"]["title"])
        c = wikipedia.fetch_intros(titles)
        c.seal()
    print(f"{c.name}: {len(c.items())} items, sealed={c.sealed}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="acat", description="acatalogue: a curated, attributed catalogue of knowledge")
    ap.add_argument("--db", type=Path, default=Path(os.environ.get("ACAT_DB", DEFAULT_DB)),
                    help="catalogue database (default: data/acatalogue.sqlite, or $ACAT_DB)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("build", help="seeds + sealed corpora -> the catalogue database")
    p.set_defaults(fn=cmd_build)
    p = sub.add_parser("semantic", help="build the LSA semantic layer (needs numpy)")
    p.add_argument("--dims", type=int, default=48)
    p.add_argument("--k", type=int, default=6, help="neighbours per concept")
    p.set_defaults(fn=cmd_semantic)

    p = sub.add_parser("grep", help="the SQL grepper over concepts, passages and labels")
    p.add_argument("pattern")
    p.add_argument("-m", "--mode", choices=["words", "substring", "regex"], default="words")
    p.add_argument("-F", dest="mode", action="store_const", const="substring", help="same as --mode substring")
    p.add_argument("-E", dest="mode", action="store_const", const="regex", help="same as --mode regex")
    p.add_argument("-s", "--scope", choices=["all", "concepts", "passages", "labels"], default="all")
    p.add_argument("-n", "--limit", type=int, default=20, help="max hits per scope")
    p.add_argument("--under", help="only hits under this concept (subtree)")
    p.add_argument("--lang", help="labels scope: only this language")
    p.add_argument("-c", "--count", action="store_true", help="count hits per type")
    p.add_argument("-l", "--files-only", action="store_true", help="print matching ids only")
    p.add_argument("--explain", action="store_true", help="print the SQL that ran")
    p.add_argument("--json", action="store_true")
    p.add_argument("--jsonl", action="store_true", help="with --json: one line")
    p.add_argument("--color", choices=["auto", "always", "never"], default="auto")
    p.set_defaults(fn=cmd_grep)

    p = sub.add_parser("grep-db", help="grep every text column of any SQLite file (read-only)")
    p.add_argument("file")
    p.add_argument("pattern")
    p.add_argument("-E", "--regex", action="store_true")
    p.add_argument("-t", "--table", action="append", help="only this table (repeatable)")
    p.add_argument("-n", "--limit", type=int, default=20, help="max hits per column")
    p.add_argument("--explain", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--color", choices=["auto", "always", "never"], default="auto")
    p.set_defaults(fn=cmd_grep_db)

    p = sub.add_parser("sql", help="run one read-only SQL statement")
    p.add_argument("query")
    p.add_argument("-n", "--limit", type=int, default=1000)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_sql)

    p = sub.add_parser("show", help="resolve any scoped id (acat/…, space/…, wd/…, doc/…, src/sha512:…)")
    p.add_argument("id")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("tree", help="print the compendium as a tree")
    p.add_argument("root", nargs="?")
    p.add_argument("-d", "--depth", type=int, default=1)
    p.add_argument("--scheme", default="acat")
    p.set_defaults(fn=cmd_tree)

    p = sub.add_parser("stats", help="row counts, corpora, ledger head")
    p.set_defaults(fn=cmd_stats)
    p = sub.add_parser("audit", help="coverage and bias measurements")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_audit)
    p = sub.add_parser("verify", help="validate seeds, re-hash every corpus, check the ledger chain")
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("serve", help="HTTP API + the particle field")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(fn=cmd_serve)
    p = sub.add_parser("export-graph", help="write the /api/graph payload to a file (static mode)")
    p.add_argument("out", nargs="?", default="viz/data/graph.json")
    p.set_defaults(fn=cmd_export_graph)
    p = sub.add_parser("compendium-md", help="write the compendium as Markdown")
    p.add_argument("out", nargs="?", default="docs/COMPENDIUM.md")
    p.set_defaults(fn=cmd_compendium_md)

    p = sub.add_parser("eval", help="leave-one-language-out retrieval evaluation, stored in eval_* tables")
    p.add_argument("--langs", help="comma-separated panel (default: 28 languages across scripts and regions)")
    p.add_argument("--systems", help="comma-separated: words,trigram,lsa,dense,rrf-lexical,rrf-all")
    p.add_argument("--boot", type=int, default=1000)
    p.add_argument("--perms", type=int, default=10000)
    p.set_defaults(fn=cmd_eval)

    p = sub.add_parser("embed", help="dense multilingual label vectors (needs onnxruntime, tokenizers, the pinned model)")
    p.add_argument("--model", default="e5-large-instruct")
    p.add_argument("--kinds", default="pref", help="label kinds to embed, comma-separated (default pref)")
    p.set_defaults(fn=cmd_embed)

    p = sub.add_parser("bake", help="bake the particle layout with the browser's own physics (needs Node)")
    p.add_argument("--steps", type=int, default=20000, help="step limit (default 20000)")
    p.set_defaults(fn=cmd_bake)

    p = sub.add_parser("review", help="human review of machine-proposed crosswalks (seed/reviews/)")
    p.add_argument("action", choices=["queue", "approve", "revise", "object"])
    p.add_argument("frm", nargs="?", metavar="from", help="our concept, e.g. acat/physics")
    p.add_argument("to", nargs="?", help="the mapped concept, e.g. wd/Q413")
    p.add_argument("--reviewer", help="the person deciding (their file is seed/reviews/<name>.tsv)")
    p.add_argument("--relation", help="revise: the relation it should have; queue: only this relation")
    p.add_argument("--perspective", help="your declared perspective, tradition or region (optional)")
    p.add_argument("--rationale", help="why (required to revise or object)")
    p.add_argument("--human", action="store_true", help="the reviewer is a person (their decision applies)")
    p.add_argument("--agent", action="store_true", help="the reviewer is an AI agent (recorded, never decisive)")
    p.add_argument("--under", help="queue: only concepts under this one")
    p.add_argument("-n", "--limit", type=int, default=10)
    p.set_defaults(fn=cmd_review)

    p = sub.add_parser("fetch", help="fetch a source into a new dated, sealed corpus")
    p.add_argument("source", choices=["m49", "external", "wikidata", "wikidata-statements", "wikipedia",
                                      "worldbank"])
    p.set_defaults(fn=cmd_fetch)

    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except FileNotFoundError as exc:
        print(f"acat: {exc}", file=sys.stderr)
        return 2
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    sys.exit(main())
