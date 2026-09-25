"""Integrity checks for `acat verify`: the database file, its search indexes, and the SKOS integrity
conditions of the W3C SKOS Reference that a catalogue of concept schemes must satisfy.

  S13  a concept never has the same literal as both its preferred and an alternative label
  S14  a concept has at most one preferred label per language
  S27  skos:related is disjoint from skos:broaderTransitive (no related link to an ancestor)
  S46  exactMatch is disjoint from broadMatch and relatedMatch for the same pair
  plus: a notation is unique within its scheme
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict

from .textkeys import KEY_VERSION

FTS_EXTERNAL = ("label_fts", "passage_fts")


def database_checks(conn: sqlite3.Connection) -> list[str]:
    """Problems with the file and its indexes (empty list = sound). Needs a writable connection
    for the FTS5 'integrity-check' command, which reads only."""
    problems = []
    res = [r[0] for r in conn.execute("PRAGMA integrity_check")]
    if res != ["ok"]:
        problems += [f"integrity_check: {r}" for r in res[:10]]
    for t in FTS_EXTERNAL:
        try:
            conn.execute(f"INSERT INTO {t}({t}, rank) VALUES ('integrity-check', 1)")
        except sqlite3.DatabaseError as exc:
            problems.append(f"{t}: index does not match its content ({exc})")
    for t in ("concept_fts", "concept_key", "label_key", "label_cjk", "passage_key"):
        try:
            conn.execute(f"INSERT INTO {t}({t}) VALUES ('integrity-check')")
        except sqlite3.DatabaseError as exc:
            problems.append(f"{t}: {exc}")
    row = conn.execute("SELECT value FROM meta WHERE key = 'key_version'").fetchone()
    if row is None or row[0] != KEY_VERSION:
        problems.append(f"case keys were built as {row[0] if row else 'nothing'}, this Python needs {KEY_VERSION}:"
                        " substring/regex search scans instead of using the index until `acat build` runs")
    return problems


def skos_checks(conn: sqlite3.Connection) -> dict[str, list]:
    out: dict[str, list] = {}
    out["S13 pref/alt disjoint"] = [tuple(r) for r in conn.execute(
        "SELECT a.concept_id, a.lang, a.text FROM label a JOIN label b ON b.concept_id = a.concept_id"
        " AND b.lang = a.lang AND b.text = a.text WHERE a.kind = 'pref' AND b.kind = 'alt' LIMIT 50")]
    out["S14 one pref per language"] = [tuple(r) for r in conn.execute(
        "SELECT concept_id, lang, count(*) FROM label WHERE kind = 'pref' GROUP BY concept_id, lang"
        " HAVING count(*) > 1 LIMIT 50")]
    parents: dict[str, set[str]] = defaultdict(set)
    for child, parent in conn.execute("SELECT child, parent FROM broader"):
        parents[child].add(parent)

    def ancestors(c: str) -> set[str]:
        seen, stack = set(), list(parents.get(c, ()))
        while stack:
            x = stack.pop()
            if x not in seen:
                seen.add(x)
                stack.extend(parents.get(x, ()))
        return seen

    out["S27 related vs broaderTransitive"] = [
        (a, b) for a, b in conn.execute("SELECT a, b FROM related") if b in ancestors(a) or a in ancestors(b)][:50]
    rel: dict[tuple[str, str], set[str]] = defaultdict(set)
    for f, t, r in conn.execute("SELECT from_id, to_id, relation FROM mapping WHERE status = 'accepted'"):
        rel[tuple(sorted((f, t)))].add(r)
    out["S46 exactMatch vs broad/related"] = [
        (k, sorted(v)) for k, v in rel.items() if "exactMatch" in v and v & {"broadMatch", "relatedMatch"}][:50]
    out["unique notation per scheme"] = [tuple(r) for r in conn.execute(
        "SELECT scheme, notation, count(*) FROM concept WHERE notation IS NOT NULL AND status = 'active'"
        " GROUP BY scheme, notation HAVING count(*) > 1 LIMIT 50")]
    return out
