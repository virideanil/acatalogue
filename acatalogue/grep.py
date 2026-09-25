"""The SQL grepper.

Three modes over the same catalogue, and every answer carries the exact SQL that produced it:

  words      FTS5 query syntax (AND / OR / NOT, "phrases", prefix*, NEAR(...)), ranked by BM25;
             combining marks stay inside words; a query with Chinese, Japanese or Korean text is
             matched through an index of overlapping character pairs, so two-character words are found
  substring  a literal, case-insensitive in exactly the sense of Python's re.IGNORECASE on NFC text;
             candidates come from a trigram index over each text's case key (textkeys.py), and every
             candidate is checked with Python — so İstanbul is found by "istanbul", and nothing is missed
  regex      a Python regular expression; a trigram query is extracted from the pattern (Russ Cox's
             method) to narrow the candidates whenever the pattern allows it, otherwise every row is
             scanned; the regex itself decides every hit

`grep_any` greps every text column of any SQLite file (read-only), for databases that are not
catalogues at all.
"""
from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .db import register_functions
from .textkeys import KEY_VERSION, cjk_query, fts_phrase, has_cjk, literal_query, nfc, trigram_query

MODES = ("words", "substring", "regex")
SCOPES = ("all", "concepts", "passages", "labels")
START, END = "\x02", "\x03"
_CJK_PAIR = re.compile(r"^[぀-ヿ㐀-䶿一-鿿豈-﫿가-힯]{2}$")


@dataclass
class Hit:
    target: str
    type: str
    title: str
    parts: list[dict]
    score: float
    concepts: list[str] = field(default_factory=list)
    lang: str | None = None

    @property
    def snippet(self) -> str:
        return "".join(p["t"] for p in self.parts)


@dataclass
class GrepResult:
    query: str
    mode: str
    scope: str
    sql: list[str]
    elapsed_ms: float
    hits: list[Hit]
    error: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.hits)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["total"] = self.total
        return d


class GrepError(ValueError):
    pass


# ─── snippets ────────────────────────────────────────────────────────────────


def parts_from_markers(text: str) -> list[dict]:
    """FTS5 snippet()/highlight() output with START/END markers -> [{'t', 'm'}]."""
    out: list[dict] = []
    for i, chunk in enumerate(re.split(f"[{START}{END}]", text or "")):
        if chunk:
            out.append({"t": chunk, "m": i % 2 == 1})
    return out


def parts_from_spans(text: str, spans: list[tuple[int, int]], context: int = 70) -> list[dict]:
    """A window of `text` around the first match, with every match inside it marked."""
    if not spans:
        return [{"t": text[: 2 * context] + ("…" if len(text) > 2 * context else ""), "m": False}]
    a = max(0, spans[0][0] - context)
    b = min(len(text), spans[0][1] + context)
    if a > 0:
        sp = text.find(" ", a, spans[0][0])
        a = sp + 1 if sp != -1 else a
    if b < len(text):
        sp = text.rfind(" ", spans[0][1], b)
        b = sp if sp != -1 else b
    out: list[dict] = [{"t": "…", "m": False}] if a > 0 else []
    pos = a
    for s, e in spans:
        if s < a or e > b:
            continue
        if s > pos:
            out.append({"t": text[pos:s], "m": False})
        out.append({"t": text[s:e], "m": True})
        pos = e
    if pos < b:
        out.append({"t": text[pos:b], "m": False})
    if b < len(text):
        out.append({"t": "…", "m": False})
    return out


def _spans_literal(text: str, needle: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in re.finditer(re.escape(nfc(needle)), text, re.IGNORECASE)][:20]


def _spans_regex(text: str, rx: re.Pattern) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in rx.finditer(text) if m.end() > m.start()][:20]


def _spans_tokens(text: str, query: str) -> list[tuple[int, int]]:
    spans = []
    for tok in nfc(query).split():
        tok = tok.strip('"()*')
        if tok and tok.upper() not in ("AND", "OR", "NOT"):
            spans += [(m.start(), m.end()) for m in re.finditer(re.escape(tok), text, re.IGNORECASE)]
    return sorted(spans)[:20]


def plain_words(query: str) -> str:
    """Fallback when a query is not valid FTS5 syntax: every whitespace token becomes a phrase."""
    return " ".join(fts_phrase(t) for t in query.split())


# ─── query helpers ───────────────────────────────────────────────────────────


def _subtree_cte(under: str | None) -> tuple[str, list]:
    if not under:
        return "", []
    return ("WITH RECURSIVE sub(id) AS (SELECT ? UNION SELECT b.child FROM broader b JOIN sub ON b.parent = sub.id) ",
            [under])


def _concepts_of_docs(conn: sqlite3.Connection, doc_ids: list[str]) -> dict[str, list[str]]:
    if not doc_ids:
        return {}
    marks = ",".join("?" * len(doc_ids))
    out: dict[str, list[str]] = {}
    for d, c in conn.execute(f"SELECT doc_id, concept_id FROM document_concept WHERE doc_id IN ({marks})"
                             " ORDER BY concept_id", doc_ids):
        out.setdefault(d, []).append(c)
    return out


def _keys_current(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT value FROM meta WHERE key = 'key_version'").fetchone()
    return row is not None and row[0] == KEY_VERSION


# ─── the grepper ─────────────────────────────────────────────────────────────


def grep(conn: sqlite3.Connection, pattern: str, *, mode: str = "words", scope: str = "all", limit: int = 50,
         under: str | None = None, lang: str | None = None, context: int = 70) -> GrepResult:
    if mode not in MODES:
        raise GrepError(f"mode must be one of {MODES}")
    if scope not in SCOPES:
        raise GrepError(f"scope must be one of {SCOPES}")
    if not pattern or not pattern.strip():
        raise GrepError("empty pattern")
    limit = max(1, min(int(limit), 500))
    t0 = time.perf_counter()
    res = GrepResult(query=pattern, mode=mode, scope=scope, sql=[], elapsed_ms=0.0, hits=[])
    rx = None
    if mode == "regex":
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            raise GrepError(f"invalid regular expression: {exc}") from exc
    use_keys = mode == "words" or _keys_current(conn)
    if not use_keys:
        res.notes.append(f"the case-key index was built for another Unicode/Python version than {KEY_VERSION}:"
                         " every row is scanned (rebuild with `acat build` to use the index)")
    scopes = ("concepts", "passages", "labels") if scope == "all" else (scope,)
    for sc in scopes:
        if mode == "words":
            _words(conn, res, sc, pattern, limit, under, lang, context)
        elif mode == "substring":
            _substring(conn, res, sc, nfc(pattern), limit, under, lang, context, use_keys)
        else:
            _regex(conn, res, sc, pattern, rx, limit, under, lang, context, use_keys)
    res.elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
    return res


def _run(conn: sqlite3.Connection, res: GrepResult, sql: str, params: list) -> list[sqlite3.Row]:
    res.sql.append(" ".join(sql.split()))
    return conn.execute(sql, params).fetchall()


def _note(res: GrepResult, note: str) -> None:
    if note not in res.notes:
        res.notes.append(note)


def _fts(conn, res: GrepResult, sql: str, before: list, q: str, after: list) -> list[sqlite3.Row]:
    try:
        return _run(conn, res, sql, before + [q] + after)
    except sqlite3.OperationalError as exc:
        # FTS5 reports bad query syntax in several ways ('syntax error', 'no such column' for a
        # hyphenated word read as a column filter, ...). Retry once as plain words; a real fault
        # fails again and propagates.
        fallback = plain_words(q)
        _note(res, f"not valid FTS5 syntax ({exc}); searched as plain words: {fallback}")
        res.sql.pop()
        return _run(conn, res, sql, before + [fallback] + after)


def _words(conn, res: GrepResult, sc: str, q: str, limit: int, under, lang, context: int) -> None:
    q = nfc(q)
    cte, cte_p = _subtree_cte(under)
    if sc == "concepts":
        sql = (cte + "SELECT f.id, f.label, snippet(concept_fts, -1, ?, ?, '…', 24) AS snip,"
               " bm25(concept_fts, 0.0, 10.0, 5.0, 1.0) AS rank FROM concept_fts f"
               " WHERE concept_fts MATCH ?" + (" AND f.id IN (SELECT id FROM sub)" if under else "") +
               " ORDER BY rank LIMIT ?")
        for r in _fts(conn, res, sql, cte_p + [START, END], q, [limit]):
            res.hits.append(Hit(target=r[0], type="concept", title=r[1], parts=parts_from_markers(r[2]),
                                score=round(-r[3], 4), concepts=[r[0]]))
    elif sc == "passages":
        sql = (cte + "SELECT p.id, p.doc_id, p.ord, d.title, snippet(passage_fts, 0, ?, ?, '…', 32) AS snip,"
               " bm25(passage_fts) AS rank FROM passage_fts JOIN passage p ON p.id = passage_fts.rowid"
               " JOIN document d ON d.id = p.doc_id WHERE passage_fts MATCH ? AND d.superseded_by IS NULL" +
               (" AND p.doc_id IN (SELECT doc_id FROM document_concept WHERE concept_id IN (SELECT id FROM sub))"
                if under else "") + " ORDER BY rank LIMIT ?")
        rows = _fts(conn, res, sql, cte_p + [START, END], q, [limit])
        concepts = _concepts_of_docs(conn, [r[1] for r in rows])
        for r in rows:
            res.hits.append(Hit(target=f"{r[1]}#p{r[2]}", type="passage", title=r[3], parts=parts_from_markers(r[4]),
                                score=round(-r[5], 4), concepts=concepts.get(r[1], [])))
    elif has_cjk(q):
        _note(res, "Chinese/Japanese/Korean text in the query: labels matched through the character-pair index")
        sql = (cte + "SELECT l.concept_id, l.lang, l.text, c.label, bm25(label_cjk) AS rank FROM label_cjk"
               " JOIN label l ON l.id = label_cjk.rowid JOIN concept c ON c.id = l.concept_id"
               " WHERE label_cjk MATCH ? AND c.scheme <> 'wd'" + (" AND l.lang = ?" if lang else "") +
               (" AND l.concept_id IN (SELECT id FROM sub)" if under else "") + " ORDER BY rank LIMIT ?")
        for cid, lng, text, label, rank in _fts(conn, res, sql, cte_p, cjk_query(q), ([lang] if lang else []) + [limit]):
            res.hits.append(Hit(target=cid, type="label", title=label,
                                parts=parts_from_spans(text, _spans_tokens(text, q), context),
                                score=round(-rank, 4), concepts=[cid], lang=lng))
    else:
        sql = (cte + "SELECT l.concept_id, l.lang, l.kind, highlight(label_fts, 3, ?, ?) AS hl, bm25(label_fts) AS rank,"
               " c.label FROM label_fts l JOIN concept c ON c.id = l.concept_id"
               " WHERE label_fts MATCH ? AND c.scheme <> 'wd'" + (" AND l.lang = ?" if lang else "") +
               (" AND l.concept_id IN (SELECT id FROM sub)" if under else "") + " ORDER BY rank LIMIT ?")
        for r in _fts(conn, res, sql, cte_p + [START, END], q, ([lang] if lang else []) + [limit]):
            res.hits.append(Hit(target=r[0], type="label", title=r[5], parts=parts_from_markers(r[3]),
                                score=round(-r[4], 4), concepts=[r[0]], lang=r[1]))


def _substring(conn, res: GrepResult, sc: str, needle: str, limit: int, under, lang, context: int,
               use_keys: bool) -> None:
    cte, cte_p = _subtree_cte(under)
    lit = literal_query(needle) if use_keys else None
    pair = use_keys and sc == "labels" and bool(_CJK_PAIR.match(needle))
    if lit:
        _note(res, f"case-key trigram index narrows candidates ({lit}); each one is checked with Python re")
    elif pair:
        _note(res, "two-character CJK needle: the character-pair index narrows the labels")
    else:
        _note(res, "no index can narrow this needle: every row is checked with Python re")
    if sc == "concepts":
        src = "concept_key k JOIN concept c ON c.id = k.id"
        where = ("concept_key MATCH ? AND " if lit else "") + "acat_icontains(k.text, ?)"
        sql = (cte + f"SELECT k.id, c.label, k.text FROM {src} WHERE {where}" +
               (" AND k.id IN (SELECT id FROM sub)" if under else "") + " ORDER BY length(c.label), k.id LIMIT ?")
        rows = _run(conn, res, sql, cte_p + ([lit] if lit else []) + [needle, limit])
        for cid, label, text in rows:
            res.hits.append(Hit(target=cid, type="concept", title=label,
                                parts=parts_from_spans(text, _spans_literal(text, needle), context),
                                score=1.0, concepts=[cid]))
    elif sc == "passages":
        src = "passage_key JOIN passage p ON p.id = passage_key.rowid" if lit else "passage p"
        sql = (cte + f"SELECT p.id, p.doc_id, p.ord, d.title, p.text FROM {src} JOIN document d ON d.id = p.doc_id"
               " WHERE " + ("passage_key MATCH ? AND " if lit else "") +
               "acat_icontains(p.text, ?) AND d.superseded_by IS NULL" +
               (" AND p.doc_id IN (SELECT doc_id FROM document_concept WHERE concept_id IN (SELECT id FROM sub))"
                if under else "") + " ORDER BY p.doc_id, p.ord LIMIT ?")
        rows = _run(conn, res, sql, cte_p + ([lit] if lit else []) + [needle, limit])
        concepts = _concepts_of_docs(conn, [r[1] for r in rows])
        for pid, doc, ord_, title, text in rows:
            res.hits.append(Hit(target=f"{doc}#p{ord_}", type="passage", title=title,
                                parts=parts_from_spans(text, _spans_literal(text, needle), context),
                                score=1.0, concepts=concepts.get(doc, [])))
    else:
        if lit:
            src, pre, params = "label_key JOIN label l ON l.id = label_key.rowid", "label_key MATCH ? AND ", [lit]
        elif pair:
            src, pre, params = "label_cjk JOIN label l ON l.id = label_cjk.rowid", "label_cjk MATCH ? AND ", \
                [fts_phrase(needle)]
        else:
            src, pre, params = "label l", "", []
        sql = (cte + f"SELECT l.concept_id, l.lang, l.text, c.label FROM {src} JOIN concept c ON c.id = l.concept_id"
               f" WHERE {pre}acat_icontains(l.text, ?) AND c.scheme <> 'wd'" + (" AND l.lang = ?" if lang else "") +
               (" AND l.concept_id IN (SELECT id FROM sub)" if under else "") +
               " ORDER BY length(l.text), l.concept_id LIMIT ?")
        rows = _run(conn, res, sql, cte_p + params + [needle] + ([lang] if lang else []) + [limit])
        for cid, lng, text, label in rows:
            res.hits.append(Hit(target=cid, type="label", title=label,
                                parts=parts_from_spans(text, _spans_literal(text, needle), context),
                                score=1.0, concepts=[cid], lang=lng))


def _regex(conn, res: GrepResult, sc: str, pattern: str, rx: re.Pattern, limit: int, under, lang,
           context: int, use_keys: bool) -> None:
    cte, cte_p = _subtree_cte(under)
    q = trigram_query(pattern) if use_keys else None
    _note(res, f"trigram query from the regex narrows candidates ({q}); the regex decides every hit" if q
          else "the regex gives no usable trigram: every row is checked with REGEXP")
    pre = [q] if q else []
    if sc == "concepts":
        sql = (cte + "SELECT k.id, c.label, k.text FROM concept_key k JOIN concept c ON c.id = k.id WHERE " +
               ("concept_key MATCH ? AND " if q else "") + "k.text REGEXP ?" +
               (" AND k.id IN (SELECT id FROM sub)" if under else "") + " ORDER BY length(c.label), k.id LIMIT ?")
        for cid, label, text in _run(conn, res, sql, cte_p + pre + [pattern, limit]):
            text = nfc(text)
            res.hits.append(Hit(target=cid, type="concept", title=label,
                                parts=parts_from_spans(text, _spans_regex(text, rx), context), score=1.0,
                                concepts=[cid]))
    elif sc == "passages":
        src = "passage_key JOIN passage p ON p.id = passage_key.rowid" if q else "passage p"
        sql = (cte + f"SELECT p.id, p.doc_id, p.ord, d.title, p.text FROM {src} JOIN document d ON d.id = p.doc_id"
               " WHERE " + ("passage_key MATCH ? AND " if q else "") + "p.text REGEXP ? AND d.superseded_by IS NULL" +
               (" AND p.doc_id IN (SELECT doc_id FROM document_concept WHERE concept_id IN (SELECT id FROM sub))"
                if under else "") + " ORDER BY p.doc_id, p.ord LIMIT ?")
        rows = _run(conn, res, sql, cte_p + pre + [pattern, limit])
        concepts = _concepts_of_docs(conn, [r[1] for r in rows])
        for pid, doc, ord_, title, text in rows:
            text = nfc(text)
            res.hits.append(Hit(target=f"{doc}#p{ord_}", type="passage", title=title,
                                parts=parts_from_spans(text, _spans_regex(text, rx), context), score=1.0,
                                concepts=concepts.get(doc, [])))
    else:
        src = "label_key JOIN label l ON l.id = label_key.rowid" if q else "label l"
        sql = (cte + f"SELECT l.concept_id, l.lang, l.text, c.label FROM {src} JOIN concept c ON c.id = l.concept_id"
               " WHERE " + ("label_key MATCH ? AND " if q else "") + "l.text REGEXP ? AND c.scheme <> 'wd'" +
               (" AND l.lang = ?" if lang else "") + (" AND l.concept_id IN (SELECT id FROM sub)" if under else "") +
               " ORDER BY length(l.text), l.concept_id LIMIT ?")
        for cid, lng, text, label in _run(conn, res, sql, cte_p + pre + [pattern] + ([lang] if lang else []) + [limit]):
            text = nfc(text)
            res.hits.append(Hit(target=cid, type="label", title=label,
                                parts=parts_from_spans(text, _spans_regex(text, rx), context), score=1.0,
                                concepts=[cid], lang=lng))


# ─── grep any SQLite file ────────────────────────────────────────────────────

_FTS_SHADOW = re.compile(r"_(data|idx|content|docsize|config)$")


@dataclass
class AnyHit:
    table: str
    column: str
    key: str
    parts: list[dict]


def grep_any(path: str | Path, pattern: str, *, mode: str = "substring", limit_per_column: int = 20,
             tables: list[str] | None = None, context: int = 60) -> tuple[list[AnyHit], list[str]]:
    """Grep every text column of every ordinary table in any SQLite file, read-only, with the same
    case-insensitive semantics as `grep` (Python re.IGNORECASE on NFC text)."""
    conn = sqlite3.connect(f"file:{Path(path)}?mode=ro", uri=True)
    register_functions(conn)
    conn.execute("PRAGMA query_only = 1")
    rx = re.compile(pattern) if mode == "regex" else None
    hits: list[AnyHit] = []
    sqls: list[str] = []
    try:
        objs = conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                            " ORDER BY name").fetchall()
        virtual = {n for n, s in objs if s and s.upper().startswith("CREATE VIRTUAL")}
        for name, _sql in objs:
            if name in virtual or (tables and name not in tables):
                continue
            if any(name.startswith(v + "_") and _FTS_SHADOW.search(name) for v in virtual):
                continue
            q = '"' + name.replace('"', '""') + '"'
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({q})")]
            try:
                conn.execute(f"SELECT rowid FROM {q} LIMIT 0")
                key_expr = "rowid"
            except sqlite3.OperationalError:          # WITHOUT ROWID table: use its primary key
                pk = [r[1] for r in conn.execute(f"PRAGMA table_info({q})") if r[5]]
                key_expr = " || '|' || ".join('"' + c.replace('"', '""') + '"' for c in pk) or "NULL"
            for col in cols:
                cq = '"' + col.replace('"', '""') + '"'
                test = f"{cq} REGEXP ?" if mode == "regex" else f"acat_icontains({cq}, ?)"
                sql = f"SELECT {key_expr}, {cq} FROM {q} WHERE typeof({cq}) = 'text' AND {test} LIMIT ?"
                sqls.append(sql)
                for key, text in conn.execute(sql, (pattern, limit_per_column)):
                    text = nfc(text)
                    spans = _spans_regex(text, rx) if rx else _spans_literal(text, pattern)
                    hits.append(AnyHit(table=name, column=col, key=str(key),
                                       parts=parts_from_spans(text, spans, context)))
    finally:
        conn.close()
    return hits, sqls
