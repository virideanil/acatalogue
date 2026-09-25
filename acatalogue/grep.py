"""The SQL grepper.

Three modes over the same catalogue, and every answer carries the exact SQL that produced it:

  words      FTS5 query syntax (AND / OR / NOT, "phrases", prefix*, NEAR(...)), ranked by BM25
  substring  a literal, case-insensitive; accelerated by the trigram index (works inside words and
             in scripts without spaces, e.g. Chinese or Japanese); patterns under three characters
             fall back to a full scan
  regex      a Python regular expression; when the pattern provably contains a literal run of three
             or more characters (case-sensitive, no top-level alternation) the trigram index narrows
             the candidates first, otherwise every row is scanned — never a missed match

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

MODES = ("words", "substring", "regex")
SCOPES = ("all", "concepts", "passages", "labels")
START, END = "\x02", "\x03"


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
    return [(m.start(), m.end()) for m in re.finditer(re.escape(needle), text, re.IGNORECASE)]


def _spans_regex(text: str, rx: re.Pattern) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in rx.finditer(text) if m.end() > m.start()][:20]


# ─── query helpers ───────────────────────────────────────────────────────────


def fts_phrase(literal: str) -> str:
    """A literal as one FTS5 string (double quotes doubled)."""
    return '"' + literal.replace('"', '""') + '"'


def plain_words(query: str) -> str:
    """Fallback when a query is not valid FTS5 syntax: every whitespace token becomes a phrase."""
    return " ".join(fts_phrase(t) for t in query.split())


def required_literal(pattern: str) -> str | None:
    """The longest literal run (>= 3 chars) that every match of `pattern` must contain, or None.
    Conservative: only top-level literal runs, only for case-sensitive patterns without top-level
    alternation — so a trigram prefilter built from it can never exclude a true match."""
    try:
        from re import _constants as C, _parser as P      # Python >= 3.11
    except ImportError:                                  # pragma: no cover
        import sre_constants as C                        # type: ignore
        import sre_parse as P                            # type: ignore
    try:
        parsed = P.parse(pattern)
    except Exception:
        return None
    if parsed.state.flags & re.IGNORECASE:
        return None
    best, run = "", []
    for op, av in parsed:
        if op is C.LITERAL:
            run.append(chr(av))
            continue
        if op is C.BRANCH:
            return None
        if len(run) > len(best):
            best = "".join(run)
        run = []
    if len(run) > len(best):
        best = "".join(run)
    return best if len(best) >= 3 else None


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
    scopes = ("concepts", "passages", "labels") if scope == "all" else (scope,)
    for sc in scopes:
        if mode == "words":
            _words(conn, res, sc, pattern, limit, under, lang)
        elif mode == "substring":
            _substring(conn, res, sc, pattern, limit, under, lang, context)
        else:
            _regex(conn, res, sc, pattern, rx, limit, under, lang, context)
    res.elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
    return res


def _run(conn: sqlite3.Connection, res: GrepResult, sql: str, params: list) -> list[sqlite3.Row]:
    res.sql.append(" ".join(sql.split()))
    return conn.execute(sql, params).fetchall()


def _words(conn, res: GrepResult, sc: str, q: str, limit: int, under, lang) -> None:
    cte, cte_p = _subtree_cte(under)
    if sc == "concepts":
        sql = (cte + "SELECT f.id, f.label, snippet(concept_fts, -1, ?, ?, '…', 24) AS snip,"
               " bm25(concept_fts, 0.0, 10.0, 5.0, 1.0) AS rank FROM concept_fts f"
               " WHERE concept_fts MATCH ?" + (" AND f.id IN (SELECT id FROM sub)" if under else "") +
               " ORDER BY rank LIMIT ?")
        rows = _fts(conn, res, sql, cte_p + [START, END], q, [limit])
        for r in rows:
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
    else:
        sql = (cte + "SELECT l.concept_id, l.lang, l.kind, highlight(label_fts, 3, ?, ?) AS hl, bm25(label_fts) AS rank,"
               " c.label FROM label_fts l JOIN concept c ON c.id = l.concept_id"
               " WHERE label_fts MATCH ? AND c.scheme <> 'wd'" + (" AND l.lang = ?" if lang else "") +
               (" AND l.concept_id IN (SELECT id FROM sub)" if under else "") + " ORDER BY rank LIMIT ?")
        rows = _fts(conn, res, sql, cte_p + [START, END], q, ([lang] if lang else []) + [limit])
        for r in rows:
            res.hits.append(Hit(target=r[0], type="label", title=r[5], parts=parts_from_markers(r[3]),
                                score=round(-r[4], 4), concepts=[r[0]], lang=r[1]))


def _fts(conn, res: GrepResult, sql: str, before: list, q: str, after: list) -> list[sqlite3.Row]:
    try:
        return _run(conn, res, sql, before + [q] + after)
    except sqlite3.OperationalError as exc:
        # FTS5 reports bad query syntax in several ways ('syntax error', 'no such column' for a
        # hyphenated word read as a column filter, ...). Retry once as plain words; a real fault
        # fails again and propagates.
        fallback = plain_words(q)
        note = f"not valid FTS5 syntax ({exc}); searched as plain words: {fallback}"
        if note not in res.notes:
            res.notes.append(note)
        res.sql.pop()
        return _run(conn, res, sql, before + [fallback] + after)


def _substring(conn, res: GrepResult, sc: str, needle: str, limit: int, under, lang, context: int) -> None:
    cte, cte_p = _subtree_cte(under)
    use_tri = len(needle) >= 3
    if not use_tri and not any("full scan" in n for n in res.notes):
        res.notes.append("pattern shorter than 3 characters: full scan instead of the trigram index")
    if sc == "concepts":
        where = "concept_tri MATCH ?" if use_tri else "casefold_contains(t.text, ?)"
        sql = (cte + "SELECT t.id, c.label, t.text FROM concept_tri t JOIN concept c ON c.id = t.id WHERE " + where +
               (" AND t.id IN (SELECT id FROM sub)" if under else "") + " ORDER BY length(c.label), t.id LIMIT ?")
        rows = _run(conn, res, sql, cte_p + [fts_phrase(needle) if use_tri else needle, limit])
        for cid, label, text in rows:
            res.hits.append(Hit(target=cid, type="concept", title=label,
                                parts=parts_from_spans(text, _spans_literal(text, needle), context),
                                score=1.0, concepts=[cid]))
    elif sc == "passages":
        where = "passage_tri MATCH ?" if use_tri else "casefold_contains(p.text, ?)"
        src = ("passage_tri JOIN passage p ON p.id = passage_tri.rowid" if use_tri else "passage p")
        sql = (cte + f"SELECT p.id, p.doc_id, p.ord, d.title, p.text FROM {src} JOIN document d ON d.id = p.doc_id"
               f" WHERE {where} AND d.superseded_by IS NULL" +
               (" AND p.doc_id IN (SELECT doc_id FROM document_concept WHERE concept_id IN (SELECT id FROM sub))"
                if under else "") + " ORDER BY p.doc_id, p.ord LIMIT ?")
        rows = _run(conn, res, sql, cte_p + [fts_phrase(needle) if use_tri else needle, limit])
        concepts = _concepts_of_docs(conn, [r[1] for r in rows])
        for pid, doc, ord_, title, text in rows:
            res.hits.append(Hit(target=f"{doc}#p{ord_}", type="passage", title=title,
                                parts=parts_from_spans(text, _spans_literal(text, needle), context),
                                score=1.0, concepts=concepts.get(doc, [])))
    else:
        where = "label_tri MATCH ?" if use_tri else "casefold_contains(l.text, ?)"
        sql = (cte + "SELECT l.concept_id, l.lang, l.text, c.label FROM label_tri l JOIN concept c ON c.id = l.concept_id"
               f" WHERE {where} AND c.scheme <> 'wd'" + (" AND l.lang = ?" if lang else "") +
               (" AND l.concept_id IN (SELECT id FROM sub)" if under else "") +
               " ORDER BY length(l.text), l.concept_id LIMIT ?")
        rows = _run(conn, res, sql, cte_p + [fts_phrase(needle) if use_tri else needle] + ([lang] if lang else [])
                    + [limit])
        for cid, lng, text, label in rows:
            res.hits.append(Hit(target=cid, type="label", title=label,
                                parts=parts_from_spans(text, _spans_literal(text, needle), context),
                                score=1.0, concepts=[cid], lang=lng))


def _regex(conn, res: GrepResult, sc: str, pattern: str, rx: re.Pattern, limit: int, under, lang,
           context: int) -> None:
    cte, cte_p = _subtree_cte(under)
    lit = required_literal(pattern)
    note = (f"trigram prefilter on the literal {lit!r}, then REGEXP" if lit
            else "no safe literal to prefilter on: every row is scanned with REGEXP")
    if note not in res.notes:
        res.notes.append(note)
    pre = [fts_phrase(lit)] if lit else []
    if sc == "concepts":
        sql = (cte + "SELECT t.id, c.label, t.text FROM concept_tri t JOIN concept c ON c.id = t.id WHERE " +
               ("concept_tri MATCH ? AND " if lit else "") + "t.text REGEXP ?" +
               (" AND t.id IN (SELECT id FROM sub)" if under else "") + " ORDER BY length(c.label), t.id LIMIT ?")
        rows = _run(conn, res, sql, cte_p + pre + [pattern, limit])
        for cid, label, text in rows:
            res.hits.append(Hit(target=cid, type="concept", title=label,
                                parts=parts_from_spans(text, _spans_regex(text, rx), context), score=1.0,
                                concepts=[cid]))
    elif sc == "passages":
        src = "passage_tri JOIN passage p ON p.id = passage_tri.rowid" if lit else "passage p"
        sql = (cte + f"SELECT p.id, p.doc_id, p.ord, d.title, p.text FROM {src} JOIN document d ON d.id = p.doc_id"
               " WHERE " + ("passage_tri MATCH ? AND " if lit else "") + "p.text REGEXP ? AND d.superseded_by IS NULL" +
               (" AND p.doc_id IN (SELECT doc_id FROM document_concept WHERE concept_id IN (SELECT id FROM sub))"
                if under else "") + " ORDER BY p.doc_id, p.ord LIMIT ?")
        rows = _run(conn, res, sql, cte_p + pre + [pattern, limit])
        concepts = _concepts_of_docs(conn, [r[1] for r in rows])
        for pid, doc, ord_, title, text in rows:
            res.hits.append(Hit(target=f"{doc}#p{ord_}", type="passage", title=title,
                                parts=parts_from_spans(text, _spans_regex(text, rx), context), score=1.0,
                                concepts=concepts.get(doc, [])))
    else:
        sql = (cte + "SELECT l.concept_id, l.lang, l.text, c.label FROM label_tri l JOIN concept c ON c.id = l.concept_id"
               " WHERE " + ("label_tri MATCH ? AND " if lit else "") + "l.text REGEXP ? AND c.scheme <> 'wd'" +
               (" AND l.lang = ?" if lang else "") + (" AND l.concept_id IN (SELECT id FROM sub)" if under else "") +
               " ORDER BY length(l.text), l.concept_id LIMIT ?")
        rows = _run(conn, res, sql, cte_p + pre + [pattern] + ([lang] if lang else []) + [limit])
        for cid, lng, text, label in rows:
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
    """Grep every text column of every ordinary table in any SQLite file, read-only."""
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
                test = f"{cq} REGEXP ?" if mode == "regex" else f"casefold_contains({cq}, ?)"
                sql = (f"SELECT {key_expr}, {cq} FROM {q} WHERE typeof({cq}) = 'text' AND {test} LIMIT ?")
                sqls.append(sql)
                for key, text in conn.execute(sql, (pattern, limit_per_column)):
                    spans = _spans_regex(text, rx) if rx else _spans_literal(text, pattern)
                    hits.append(AnyHit(table=name, column=col, key=str(key),
                                       parts=parts_from_spans(text, spans, context)))
    finally:
        conn.close()
    return hits, sqls
