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


def integrated_schemes(conn: sqlite3.Connection) -> set[str]:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'v_lean_source'").fetchone():
        return set()
    return {r[0] for r in conn.execute("SELECT scheme FROM v_lean_source WHERE mode <> 'removed'")}


def skos_checks(conn: sqlite3.Connection, *, sources: bool = False) -> dict[str, list]:
    """Violations in the catalogue's own schemes, or (sources=True) in the integrated sources' own data.
    Each check stops at 50 violations, counted separately for each side so neither hides the other."""
    integrated = integrated_schemes(conn)
    conn.execute("DROP TABLE IF EXISTS temp._integrated")
    conn.execute("CREATE TEMP TABLE _integrated(scheme TEXT PRIMARY KEY)")
    conn.executemany("INSERT INTO temp._integrated VALUES (?)", [(x,) for x in sorted(integrated)])
    side = "IN" if sources else "NOT IN"
    of = f"substr({{col}}, 1, instr({{col}}, '/') - 1) {side} (SELECT scheme FROM temp._integrated)"

    def mine(cid: str) -> bool:
        return (cid.split("/", 1)[0] in integrated) == sources
    out: dict[str, list] = {}
    out["S13 pref/alt disjoint"] = [tuple(r) for r in conn.execute(
        "SELECT a.concept_id, a.lang, a.text FROM label a JOIN label b ON b.concept_id = a.concept_id"
        " AND b.lang = a.lang AND b.text = a.text WHERE a.kind = 'pref' AND b.kind = 'alt' AND "
        + of.format(col="a.concept_id") + " LIMIT 50")]
    out["S14 one pref per language"] = [tuple(r) for r in conn.execute(
        "SELECT concept_id, lang, count(*) FROM label WHERE kind = 'pref' AND " + of.format(col="concept_id")
        + " GROUP BY concept_id, lang HAVING count(*) > 1 LIMIT 50")]
    parents: dict[str, set[str]] = defaultdict(set)
    for child, parent in conn.execute("SELECT child, parent FROM broader"):
        parents[child].add(parent)
    memo: dict[str, frozenset[str]] = {}

    def ancestors(c: str) -> frozenset[str]:
        """All ancestors (memoized; a cycle in a source's hierarchy ends the walk, never loops it)."""
        if c in memo:
            return memo[c]
        seen, stack = set(), list(parents.get(c, ()))
        while stack:
            x = stack.pop()
            if x not in seen:
                seen.add(x)
                if x in memo:
                    seen |= memo[x]
                else:
                    stack.extend(parents.get(x, ()))
        memo[c] = frozenset(seen)
        return memo[c]
    out["S27 related vs broaderTransitive"] = []
    for a, b in conn.execute("SELECT a, b FROM related"):
        if mine(a) and (b in ancestors(a) or a in ancestors(b)):
            out["S27 related vs broaderTransitive"].append((a, b))
            if len(out["S27 related vs broaderTransitive"]) >= 50:
                break
    rel: dict[tuple[str, str], set[str]] = defaultdict(set)
    for f, t, r in conn.execute("SELECT from_id, to_id, relation FROM mapping WHERE status = 'accepted'"):
        if mine(f):
            rel[tuple(sorted((f, t)))].add(r)
    out["S46 exactMatch vs broad/related"] = [
        (k[0], k[1], sorted(v)) for k, v in rel.items() if "exactMatch" in v and v & {"broadMatch", "relatedMatch"}][:50]
    out["unique notation per scheme"] = [(f"{r[0]}/", r[1], r[2]) for r in conn.execute(
        "SELECT scheme, notation, count(*) FROM concept WHERE notation IS NOT NULL AND status = 'active' AND scheme "
        + side + " (SELECT scheme FROM temp._integrated) GROUP BY scheme, notation HAVING count(*) > 1 LIMIT 50")]
    return out
