"""Read-side queries shared by the CLI and the HTTP API (see docs/API.md for the shapes)."""
from __future__ import annotations

import json
import math
import sqlite3
import statistics

from . import ledger
from .review import reviewer_kind
from .util import utcnow

GRAPH_SCHEMES = ("acat", "space", "kind", "epistemic", "udc", "ddc", "lcc", "propaedia")


def _one(conn: sqlite3.Connection, sql: str, params=()) -> sqlite3.Row | None:
    return conn.execute(sql, params).fetchone()


def resolve(conn: sqlite3.Connection, ident: str) -> dict | None:
    """Any scoped id -> the record it names (concept, document or source), or None."""
    if ident.startswith("src/sha512:"):
        r = _one(conn, "SELECT * FROM source WHERE sha512 = ?", (ident.split(":", 1)[1],))
        return {"kind": "source", **dict(r)} if r else None
    if ident.startswith("doc/"):
        base = ident.split("#", 1)[0]
        r = _one(conn, "SELECT id, corpus, name, title, lang, url, license, attribution, source_sha512, n_chars"
                       " FROM document WHERE id = ?", (base,))
        if not r:
            return None
        d = {"kind": "document", **dict(r)}
        d["concepts"] = [x[0] for x in conn.execute("SELECT concept_id FROM document_concept WHERE doc_id = ?", (base,))]
        d["passages"] = conn.execute("SELECT count(*) FROM passage WHERE doc_id = ?", (base,)).fetchone()[0]
        return d
    n = node(conn, ident)
    return {"kind": "concept", **n} if n else None


def node(conn: sqlite3.Connection, cid: str) -> dict | None:
    c = _one(conn, "SELECT c.*, s.sitelinks, s.label_langs FROM concept c LEFT JOIN concept_stat s"
                   " ON s.concept_id = c.id WHERE c.id = ?", (cid,))
    if c is None:
        return None

    def labelled(sql: str, params) -> list[dict]:
        return [{"id": r[0], "label": r[1]} for r in conn.execute(sql, params)]

    labels = [{"lang": r[0], "kind": r[1], "text": r[2], "source": f"src/sha512:{r[3]}" if r[3] else None}
              for r in conn.execute("SELECT lang, kind, text, source_sha512 FROM label WHERE concept_id = ?"
                                    " ORDER BY lang, CASE kind WHEN 'pref' THEN 0 WHEN 'alt' THEN 1 ELSE 2 END, text",
                                    (cid,))]
    mapped_wd = [r[0] for r in conn.execute(
        "SELECT to_id FROM mapping WHERE from_id = ? AND status = 'accepted' AND to_id LIKE 'wd/%'", (cid,))]
    subjects = [cid] + mapped_wd
    marks = ",".join("?" * len(subjects))
    claims = [{
        "subject": r[0], "predicate": r[1], "predicate_label": r[2], "object": r[3], "object_label": r[4],
        "value": r[5], "epistemic": r[6], "rank": r[7], "source": f"src/sha512:{r[8]}",
        "valid_from": r[9], "valid_to": r[10], "snak_type": r[11], "datatype": r[12], "statement_id": r[13],
        "pointer": r[14], "qualifiers": r[15], "references": r[16], "sourced": bool(r[17])}
        for r in conn.execute(
            f"SELECT cl.subject, cl.predicate, p.label, cl.object, o.label, cl.value, cl.epistemic, cl.rank,"
            f" cl.source_sha512, cl.valid_from, cl.valid_to, cl.snak_type, cl.datatype, cl.statement_id,"
            f" cl.source_pointer, (SELECT count(*) FROM claim_qualifier q WHERE q.claim_id = cl.id),"
            f" ev.references_n, ev.sourced FROM claim cl JOIN v_claim_evidence ev ON ev.claim_id = cl.id"
            f" LEFT JOIN concept p ON p.id = cl.predicate LEFT JOIN concept o ON o.id = cl.object"
            f" WHERE cl.subject IN ({marks}) AND cl.superseded_at IS NULL"
            f" ORDER BY cl.datatype = 'external-id', coalesce(p.label, cl.predicate), o.label, cl.value", subjects)]
    documents = [{
        "id": r[0], "title": r[1], "lang": r[2], "url": r[3], "license": r[4], "attribution": r[5],
        "excerpt": (r[6] or "")[:600], "sha512": r[7]}
        for r in conn.execute(
            "SELECT d.id, d.title, d.lang, d.url, d.license, d.attribution, d.text, d.source_sha512 FROM document d"
            " JOIN document_concept dc ON dc.doc_id = d.id WHERE dc.concept_id = ? ORDER BY d.id", (cid,))]
    neighbors = [{"id": r[0], "label": r[1], "score": round(r[2], 4), "model": r[3]}
                 for r in conn.execute(
                     "SELECT n.other, c.label, n.score, n.model FROM neighbor n JOIN concept c ON c.id = n.other"
                     " WHERE n.target = ? ORDER BY n.model, n.rank", (cid,))]
    prov = []
    if c["source_sha512"]:
        s = _one(conn, "SELECT name, kind, uri, license FROM source WHERE sha512 = ?", (c["source_sha512"],))
        if s:
            prov.append({"source": s["name"], "sha512": c["source_sha512"], "kind": s["kind"], "uri": s["uri"],
                         "license": s["license"]})
    attrs = {r[0]: r[1] for r in conn.execute("SELECT key, value FROM attribute WHERE concept_id = ?", (cid,))}
    return {
        "id": c["id"], "scheme": c["scheme"], "code": c["code"], "label": c["label"], "scope_note": c["scope_note"],
        "notation": c["notation"], "status": c["status"], "time_from": c["time_from"], "time_to": c["time_to"],
        "labels": labels, "n_label_langs": c["label_langs"] or 0, "langs": c["sitelinks"],
        "broader": labelled("SELECT b.parent, c.label FROM broader b JOIN concept c ON c.id = b.parent"
                            " WHERE b.child = ? ORDER BY b.parent", (cid,)),
        "narrower": labelled("SELECT b.child, c.label FROM broader b JOIN concept c ON c.id = b.child"
                             " WHERE b.parent = ? AND c.status = 'active' ORDER BY b.child", (cid,)),
        "related": labelled("SELECT CASE WHEN r.a = ? THEN r.b ELSE r.a END AS o, c.label FROM related r"
                            " JOIN concept c ON c.id = (CASE WHEN r.a = ? THEN r.b ELSE r.a END)"
                            " WHERE r.a = ? OR r.b = ? ORDER BY o", (cid, cid, cid, cid)),
        "facets": labelled("SELECT f.facet_id, c.label FROM facet f JOIN concept c ON c.id = f.facet_id"
                           " WHERE f.concept_id = ? ORDER BY f.facet_id", (cid,)),
        "mappings": [{"id": r[0], "label": r[1], "relation": r[2], "method": r[3], "status": r[4], "reviewer": r[5],
                      "decided_by": reviewer_kind(r[5]), "note": r[6]}
                     for r in conn.execute(
                         "SELECT m.to_id, coalesce(c.label, m.to_id), m.relation, m.method, m.status, m.reviewer, m.note"
                         " FROM mapping m LEFT JOIN concept c ON c.id = m.to_id WHERE m.from_id = ?"
                         " UNION ALL SELECT m.from_id, c.label, m.relation || ' (inverse)', m.method, m.status,"
                         " m.reviewer, m.note FROM mapping m JOIN concept c ON c.id = m.from_id WHERE m.to_id = ?"
                         " ORDER BY 1", (cid, cid))],
        "documents": documents, "claims": claims, "neighbors": neighbors, "attributes": attrs, "provenance": prov,
        "reviews": [{"target": r[0], "reviewer": r[1], "reviewer_kind": r[2], "perspective": r[3], "decided_at": r[4],
                     "decision": r[5], "relation": r[6], "rationale": r[7]}
                    for r in conn.execute(
                        "SELECT target, reviewer, reviewer_kind, perspective, decided_at, decision, relation, rationale"
                        " FROM review"
                        " WHERE target = ? OR target LIKE ? OR target LIKE ? ORDER BY decided_at",
                        (f"concept:{cid}", f"mapping:{cid}|%", f"label:{cid}|%"))],
    }


def graph(conn: sqlite3.Connection, schemes: tuple[str, ...] = GRAPH_SCHEMES, *, with_layout: bool = True) -> dict:
    marks = ",".join("?" * len(schemes))
    # the semantic model drawn as neighbour springs: the newest one that has neighbours (not a baked
    # layout, not a vector set without neighbours such as the dense label vectors)
    model = _one(conn, "SELECT m.id FROM model m WHERE EXISTS (SELECT 1 FROM neighbor n WHERE n.model = m.id)"
                       " ORDER BY m.created_at DESC LIMIT 1")
    model_id = model[0] if model else None
    rows = conn.execute(
        f"SELECT c.id, c.label, c.scheme, s.root, s.depth, s.descendants, s.docs, s.sitelinks, l.x, l.y"
        f" FROM concept c LEFT JOIN concept_stat s ON s.concept_id = c.id"
        f" LEFT JOIN layout l ON l.target = c.id AND l.model = ?"
        f" WHERE c.status = 'active' AND c.scheme IN ({marks}) ORDER BY c.scheme, c.id", (model_id, *schemes)).fetchall()
    index = {r[0]: i for i, r in enumerate(rows)}
    nodes = []
    for r in rows:
        desc, docs = r[5] or 0, r[6] or 0
        nodes.append({
            "id": r[0], "label": r[1], "scheme": r[2], "root": r[3] or r[0], "depth": r[4] or 0,
            "mass": round(1.0 + math.log1p(desc) + 0.5 * math.log1p(docs), 3), "langs": r[7], "docs": docs,
            "xy": [round(r[8], 4), round(r[9], 4)] if r[8] is not None else None})
    edges = []

    def add(a: str, b: str, kind: str, w: float) -> None:
        if a in index and b in index and a != b:
            edges.append({"s": index[a], "t": index[b], "k": kind, "w": round(w, 4)})

    for child, parent in conn.execute("SELECT child, parent FROM broader ORDER BY child, parent"):
        add(child, parent, "broader", 1.0)
    for a, b in conn.execute("SELECT a, b FROM related ORDER BY a, b"):
        add(a, b, "related", 0.5)
    for a, b in conn.execute("SELECT from_id, to_id FROM mapping WHERE status = 'accepted' ORDER BY from_id, to_id"):
        add(a, b, "mapping", 0.4)
    for a, b in conn.execute("SELECT concept_id, facet_id FROM facet ORDER BY concept_id, facet_id"):
        add(a, b, "mapping", 0.3)
    if model_id:
        seen = set()
        for a, b, s in conn.execute("SELECT target, other, score FROM neighbor WHERE model = ? ORDER BY target, rank",
                                    (model_id,)):
            key = tuple(sorted((a, b)))
            if key not in seen:
                seen.add(key)
                add(a, b, "semantic", max(0.01, min(1.0, s)))
    schemes_out = [{"id": r[0], "title": r[1], "origin": r[2], "n": r[3]} for r in conn.execute(
        f"SELECT s.id, s.title, s.origin, count(c.id) FROM scheme s LEFT JOIN concept c ON c.scheme = s.id"
        f" AND c.status = 'active' WHERE s.id IN ({marks}) GROUP BY s.id ORDER BY s.id", schemes)]
    out = {"version": 1, "generated_at": utcnow(), "semantic_model": model_id, "schemes": schemes_out,
           "nodes": nodes, "edges": edges, "layout": None}
    if with_layout:
        _attach_layout(conn, out)
    return out


def _attach_layout(conn: sqlite3.Connection, g: dict) -> None:
    """Baked positions (see bake.py) as node 'pos', and whether they were computed for this very graph."""
    from .bake import graph_digest
    lay = _one(conn, "SELECT id, params, input_manifest FROM model WHERE id LIKE 'layout/%'"
                     " ORDER BY created_at DESC LIMIT 1")
    if lay is None:
        return
    pos = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT target, x, y FROM layout WHERE model = ?", (lay[0],))}
    for n in g["nodes"]:
        p = pos.get(n["id"])
        n["pos"] = [round(p[0], 3), round(p[1], 3)] if p else None
    params = json.loads(lay[1] or "{}")
    g["layout"] = {"model": lay[0], "steps": params.get("steps"), "asleep": params.get("asleep"),
                   "complete": all(n["pos"] is not None for n in g["nodes"]),
                   "stale": lay[2] != graph_digest(g)}


def audit(conn: sqlite3.Connection) -> dict:
    """Coverage measurements. They make skew visible; they do not claim its absence."""
    roots = conn.execute("SELECT c.id, c.label FROM concept c JOIN concept_stat s ON s.concept_id = c.id"
                         " WHERE c.scheme = 'acat' AND s.depth = 0 AND c.status = 'active' ORDER BY c.id").fetchall()
    domains = []
    for rid, label in roots:
        sub = [r[0] for r in conn.execute(
            "WITH RECURSIVE sub(id) AS (SELECT ? UNION SELECT b.child FROM broader b JOIN sub ON b.parent = sub.id)"
            " SELECT id FROM sub", (rid,))]
        marks = ",".join("?" * len(sub))
        langs = [r[0] for r in conn.execute(f"SELECT sitelinks FROM concept_stat WHERE concept_id IN ({marks})"
                                            " AND sitelinks IS NOT NULL", sub)]
        low = _one(conn, f"SELECT concept_id, sitelinks FROM concept_stat WHERE concept_id IN ({marks})"
                         " AND sitelinks IS NOT NULL ORDER BY sitelinks, concept_id LIMIT 1", sub)
        domains.append({
            "id": rid, "label": label, "concepts": len(sub),
            "reconciled": conn.execute(f"SELECT count(DISTINCT from_id) FROM mapping WHERE from_id IN ({marks})"
                                       " AND status = 'accepted' AND to_id LIKE 'wd/%'", sub).fetchone()[0],
            "docs": conn.execute(f"SELECT count(DISTINCT doc_id) FROM document_concept WHERE concept_id IN ({marks})",
                                 sub).fetchone()[0],
            "median_langs": statistics.median(langs) if langs else None,
            "min_langs": low[1] if low else None, "min_langs_id": low[0] if low else None})
    thinnest = [{"id": r[0], "label": r[1], "langs": r[2]} for r in conn.execute(
        "SELECT c.id, c.label, s.sitelinks FROM concept c JOIN concept_stat s ON s.concept_id = c.id"
        " WHERE c.scheme = 'acat' AND s.sitelinks IS NOT NULL ORDER BY s.sitelinks, c.id LIMIT 25")]
    regions = []
    for rid, label in conn.execute(
            "SELECT c.id, c.label FROM concept c JOIN broader b ON b.child = c.id WHERE b.parent = 'space/m49-001'"
            " ORDER BY c.id"):
        n = conn.execute(
            "WITH RECURSIVE sub(id) AS (SELECT ? UNION SELECT b.child FROM broader b JOIN sub ON b.parent = sub.id)"
            " SELECT count(DISTINCT f.concept_id) FROM facet f WHERE f.facet_id IN (SELECT id FROM sub)",
            (rid,)).fetchone()[0]
        regions.append({"id": rid, "label": label, "tagged": n})
    label_languages = [{"lang": r[0], "concepts": r[1]} for r in conn.execute(
        "SELECT l.lang, count(DISTINCT l.concept_id) FROM label l JOIN concept c ON c.id = l.concept_id"
        " WHERE c.scheme = 'acat' AND l.kind = 'pref' GROUP BY l.lang ORDER BY 2 DESC, 1 LIMIT 60")]
    n_langs = conn.execute("SELECT count(DISTINCT l.lang) FROM label l JOIN concept c ON c.id = l.concept_id"
                           " WHERE c.scheme = 'acat'").fetchone()[0]
    unmatched = [r[0] for r in conn.execute(
        "SELECT c.id FROM concept c WHERE c.scheme = 'acat' AND c.status = 'active' AND NOT EXISTS"
        " (SELECT 1 FROM mapping m WHERE m.from_id = c.id AND m.to_id LIKE 'wd/%' AND m.status = 'accepted')"
        " ORDER BY c.id")]
    stated = unstated = 0
    unstated_pairs = []
    for child, parent in conn.execute(
            "SELECT b.child, b.parent FROM broader b JOIN concept c ON c.id = b.child WHERE c.scheme = 'acat'"
            " ORDER BY b.child"):
        wc = [r[0] for r in conn.execute("SELECT to_id FROM mapping WHERE from_id = ? AND to_id LIKE 'wd/%' AND"
                                         " relation IN ('exactMatch','closeMatch') AND status = 'accepted'", (child,))]
        wp = [r[0] for r in conn.execute("SELECT to_id FROM mapping WHERE from_id = ? AND to_id LIKE 'wd/%' AND"
                                         " relation IN ('exactMatch','closeMatch') AND status = 'accepted'", (parent,))]
        if not wc or not wp:
            continue
        hit = conn.execute(
            f"SELECT 1 FROM claim WHERE subject IN ({','.join('?' * len(wc))}) AND object IN ({','.join('?' * len(wp))})"
            " AND predicate IN ('wd/P279', 'wd/P361', 'wd/P31', 'wd/P1269') AND superseded_at IS NULL"
            " AND coalesce(rank, 'normal') <> 'deprecated' LIMIT 1", wc + wp).fetchone()
        if hit:
            stated += 1
        else:
            unstated += 1
            if len(unstated_pairs) < 40:
                unstated_pairs.append({"child": child, "parent": parent})
    from .audit import latest
    return {
        "generated_at": utcnow(), "domains": domains, "thinnest": thinnest, "regions": regions,
        "label_languages": label_languages, "label_language_count": n_langs, "unmatched": unmatched,
        "hierarchy_vs_wikidata": {"stated": stated, "not_stated": unstated, "examples_not_stated": unstated_pairs},
        "baseline_audit": latest(conn),
        "notes": [
            "langs = Wikipedia language editions with an article on the matched Wikidata item, leaving out the "
            "bot-generated Cebuano and Waray editions: a measure of encyclopedic attention across languages, "
            "not of importance.",
            "baseline_audit compares regional shares with declared baselines (population, land area, equal "
            "shares). A ratio of 1 is parity with that baseline, not a verdict: which baseline is fair is a choice.",
            "regions counts ACAT concepts tagged with a UN M49 region or any place inside it.",
            "hierarchy_vs_wikidata counts ACAT parent links that Wikidata also states (subclass of, part of, "
            "instance of, facet of) between the matched items. 'Not stated' is not 'disagrees': Wikidata may be "
            "silent, or the schemes may draw the line differently.",
        ]}


def stats(conn: sqlite3.Connection, db_path: str) -> dict:
    tables = ["source", "corpus", "document", "passage", "scheme", "concept", "label", "broader", "related", "mapping",
              "facet", "claim", "embedding", "neighbor", "ledger"]
    counts = {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}
    by_scheme = dict(conn.execute("SELECT scheme, count(*) FROM concept WHERE status = 'active' GROUP BY scheme"))
    built = _one(conn, "SELECT value FROM meta WHERE key = 'built_at'")
    return {"db": db_path, "built_at": built[0] if built else None, "counts": counts, "concepts_by_scheme": by_scheme,
            "label_languages": conn.execute("SELECT count(DISTINCT lang) FROM label").fetchone()[0],
            "ledger_head": ledger.head(conn),
            "corpora": [dict(r) for r in conn.execute("SELECT name, items, manifest_sha512, sealed_at, license, path"
                                                      " FROM corpus ORDER BY name")]}


def tree(conn: sqlite3.Connection, root: str | None, max_depth: int = 2, scheme: str = "acat") -> list[str]:
    if root:
        tops = [(root, (_one(conn, "SELECT label FROM concept WHERE id = ?", (root,)) or [root])[0])]
    else:
        tops = conn.execute("SELECT c.id, c.label FROM concept c JOIN concept_stat s ON s.concept_id = c.id"
                            " WHERE c.scheme = ? AND s.depth = 0 AND c.status = 'active' ORDER BY c.id",
                            (scheme,)).fetchall()
    lines: list[str] = []

    def walk(cid: str, label: str, depth: int, seen: frozenset) -> None:
        st = _one(conn, "SELECT sitelinks, docs FROM concept_stat WHERE concept_id = ?", (cid,))
        extra = f"  [{st[0]} langs]" if st and st[0] is not None else ""
        lines.append(f"{'  ' * depth}{label}  ({cid}){extra}")
        if depth >= max_depth or cid in seen:
            return
        for child, clabel in conn.execute("SELECT b.child, c.label FROM broader b JOIN concept c ON c.id = b.child"
                                          " WHERE b.parent = ? AND c.status = 'active' ORDER BY b.child", (cid,)):
            walk(child, clabel, depth + 1, seen | {cid})

    for cid, label in tops:
        walk(cid, label, 0, frozenset())
    return lines
