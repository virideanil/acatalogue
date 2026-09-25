"""Search and read integrated sources where they sit, in their lean files.

An attached source is never copied into the catalogue: its lean file is searched with its own word
index and read record by record. A fully integrated source can be read the same way, with everything
its lean file holds (every relation, attribute and link), not only what the catalogue carries.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .lean import LeanReader
from .textkeys import nfc

KIND_NAMES = {0: "pref", 1: "alt", 2: "hidden", 3: "broader name", 4: "narrower name", 5: "related name"}
DISPLAY = ("en", "mul", "", "und")


def _path(stored: str) -> Path:
    from .store import root
    p = Path(stored)
    return p if p.is_absolute() else root() / p


def sources(conn: sqlite3.Connection) -> list[dict]:
    """The current integration of every scheme: where its lean file is, in which mode, with what counts."""
    import json
    out = []
    for scheme, source, snapshot, sha, path, mode, counts, at in conn.execute(
            "SELECT scheme, source, snapshot, lean_sha512, lean_path, mode, counts, at FROM v_lean_source"
            " WHERE mode <> 'removed' ORDER BY scheme"):
        p = _path(path)
        out.append({"scheme": scheme, "source": source, "snapshot": snapshot, "lean_sha512": sha, "mode": mode,
                    "counts": json.loads(counts or "{}"), "integrated_at": at, "lean_path": str(p),
                    "present": p.exists()})
    return out


def _display(names: dict[str, str], code: str) -> str:
    return next((names[l] for l in DISPLAY if l in names), None) or (names[sorted(names)[0]] if names else code)


def _labels(rc, term_ids: list[int]) -> dict[int, str]:
    if not term_ids:
        return {}
    marks = ",".join("?" * len(term_ids))
    names: dict[int, dict[str, str]] = {}
    for t, tag, text in rc.execute(f"SELECT l.term, g.tag, l.text FROM label l JOIN lang g ON g.id = l.lang"
                                   f" WHERE l.kind = 0 AND l.term IN ({marks}) ORDER BY l.term, g.tag, l.text", term_ids):
        names.setdefault(t, {}).setdefault(tag, text)
    codes = dict(rc.execute(f"SELECT id, code FROM term WHERE id IN ({marks})", term_ids))
    return {t: _display(names.get(t, {}), codes.get(t, str(t))) for t in term_ids}


def search(conn: sqlite3.Connection, pattern: str, *, schemes: list[str] | None = None, limit: int = 20) -> list[dict]:
    """Words search over the names in every integrated source (or those named), best matches first."""
    from .evaluate import tokens
    toks = tokens(pattern)[:16]
    if not toks:
        return []
    match = " ".join('"' + t.replace('"', '""') + '"' for t in toks)
    hits = []
    for s in sources(conn):
        if (schemes and s["scheme"] not in schemes) or not s["present"]:
            continue
        r = LeanReader(s["lean_path"])
        try:
            # best-scoring name per term (a term named alike in many languages takes one place, not many)
            terms = r.conn.execute(
                "WITH m AS MATERIALIZED (SELECT rowid AS id, bm25(label_fts) AS score FROM label_fts"
                " WHERE label_fts MATCH ?) SELECT l.term, g.tag, l.kind, l.text, min(m.score) FROM m"
                " JOIN label l ON l.id = m.id JOIN lang g ON g.id = l.lang GROUP BY l.term"
                " ORDER BY min(m.score), l.term LIMIT ?", (match, limit)).fetchall()
            display = _labels(r.conn, [t[0] for t in terms])
            codes = dict(r.conn.execute(f"SELECT id, code FROM term WHERE id IN ({','.join('?' * len(terms))})",
                                        [t[0] for t in terms])) if terms else {}
            for t, tag, kind, text, score in terms:
                hits.append({"id": f"{s['scheme']}/{codes[t]}", "scheme": s["scheme"], "code": codes[t],
                             "label": display[t], "matched": text, "lang": tag, "kind": KIND_NAMES.get(kind, kind),
                             "score": round(score, 3), "mode": s["mode"], "iri": r.iri(codes[t], None)})
        finally:
            r.close()
    hits.sort(key=lambda h: h["score"])
    return hits[:limit * max(1, len(schemes or [1]))]


def record(conn: sqlite3.Connection, ident: str) -> dict | None:
    """Everything a source's lean file says about one of its terms, by scoped id '<scheme>/<code>'."""
    scheme, _, code = ident.partition("/")
    s = next((x for x in sources(conn) if x["scheme"] == scheme), None)
    if s is None or not s["present"]:
        return None
    r = LeanReader(s["lean_path"])
    try:
        rc = r.conn
        row = rc.execute("SELECT t.id, t.code, t.status, t.iri, k.name, k.facet FROM term t LEFT JOIN kind k"
                         " ON k.id = t.kind WHERE t.code = ?", (nfc(code),)).fetchone()
        if row is None:
            return None
        tid = row[0]
        labels = [{"lang": tag, "kind": KIND_NAMES.get(k, k), "text": text} for tag, k, text in rc.execute(
            "SELECT g.tag, l.kind, l.text FROM label l JOIN lang g ON g.id = l.lang WHERE l.term = ?"
            " ORDER BY l.kind, g.tag, l.text", (tid,))]
        out_rel = rc.execute("SELECT p.name, p.role, r.o FROM rel r JOIN pred p ON p.id = r.p WHERE r.s = ?"
                             " ORDER BY p.name, r.o", (tid,)).fetchall()
        in_rel = rc.execute("SELECT p.name, p.role, r.s FROM rel r JOIN pred p ON p.id = r.p WHERE r.o = ?"
                            " ORDER BY p.name, r.s LIMIT 500", (tid,)).fetchall()
        others = _labels(rc, sorted({x[2] for x in out_rel} | {x[2] for x in in_rel}))
        codes = dict(rc.execute("SELECT id, code FROM term WHERE id IN (%s)" % ",".join("?" * len(others)),
                                list(others))) if others else {}

        def ref(t: int) -> dict:
            return {"id": f"{scheme}/{codes[t]}", "label": others[t]}
        attrs = [{"predicate": p, "role": role, "lang": tag, "value": v} for p, role, tag, v in rc.execute(
            "SELECT p.name, p.role, g.tag, a.value FROM attr a JOIN pred p ON p.id = a.p JOIN lang g ON g.id = a.lang"
            " WHERE a.term = ? ORDER BY p.name, g.tag", (tid,))]
        links = [{"predicate": p, "map": m, "target": x} for p, m, x in rc.execute(
            "SELECT p.name, p.map, l.target FROM link l JOIN pred p ON p.id = l.p WHERE l.term = ? ORDER BY p.name, l.target",
            (tid,))]
        prefs = {x["lang"]: x["text"] for x in labels if x["kind"] == "pref"}
        return {"id": f"{scheme}/{row[1]}", "scheme": scheme, "code": row[1], "label": _display(prefs, row[1]),
                "iri": r.iri(row[1], row[3]), "kind": row[4], "facet": row[5], "status": "deprecated" if row[2] else "active",
                "source": s["source"], "mode": s["mode"], "lean_sha512": s["lean_sha512"],
                "license": r.meta.get("license"), "attribution": r.meta.get("attribution"), "labels": labels,
                "broader": [ref(o) for p, role, o in out_rel if role == "broader"],
                "narrower": [ref(x) for p, role, x in in_rel if role == "broader"],
                "related": [ref(o) for p, role, o in out_rel if role == "related"]
                + [ref(x) for p, role, x in in_rel if role == "related"],
                "relations": [{"predicate": p, **ref(o)} for p, role, o in out_rel if role == "relation"],
                "attributes": attrs, "links": links}
    finally:
        r.close()
