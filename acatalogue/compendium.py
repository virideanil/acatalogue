"""Loading the authored compendium (seed/*.tsv) into the catalogue, with validation.

Seed files are the human-reviewed source of truth for the compendium: one concept per line,
diffable in git. Each load records the file's SHA-512, so every concept row in the catalogue
can be traced to the exact bytes it came from.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from . import ledger
from .textkeys import nfc
from .util import REPO_ROOT, sha512_bytes, utcnow

SEED_DIR = REPO_ROOT / "seed"
# every version of every concept seed file ever loaded (their rows are regenerated on each build)
SEED_CONCEPT_SOURCES = ("SELECT sha512 FROM source WHERE kind = 'seed'"
                        " AND (name LIKE '%seed/compendium/%' OR name LIKE '%seed/schemes/%')")
CONCEPT_COLUMNS = ["code", "broader", "label", "alt", "scope_note", "related", "facets", "notation", "when"]
ACTOR = "acat build"


class SeedError(ValueError):
    pass


@dataclass
class SeedFile:
    path: Path
    rel: str
    sha512: str
    size: int
    rows: list[dict]


@dataclass
class ConceptRow:
    scheme: str
    code: str
    broader: list[str]
    label: str
    alt: list[str]
    scope_note: str | None
    related: list[str]
    facets: list[str]
    notation: str | None
    time_from: int | None
    time_to: int | None
    source: SeedFile = field(repr=False)
    line: int = 0

    @property
    def id(self) -> str:
        return f"{self.scheme}/{self.code}"


def _split(value: str) -> list[str]:
    return [v.strip() for v in value.split("|") if v.strip()] if value else []


def parse_when(value: str, where: str) -> tuple[int | None, int | None]:
    """'-2999/-2000', '2001/..', '../-3000' -> astronomical years (None = open)."""
    if not value:
        return None, None
    left, sep, right = value.partition("/")
    if not sep:
        raise SeedError(f"{where}: 'when' must be an interval 'from/to', got {value!r}")

    def one(v: str) -> int | None:
        v = v.strip()
        if v in ("", ".."):
            return None
        try:
            return int(v)
        except ValueError as exc:
            raise SeedError(f"{where}: bad year {v!r} in 'when'") from exc

    a, b = one(left), one(right)
    if a is not None and b is not None and a > b:
        raise SeedError(f"{where}: 'when' runs backwards ({a} > {b})")
    return a, b


def read_tsv(path: Path, expect: list[str]) -> SeedFile:
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    lines = text.split("\n")
    if not lines or not lines[0].strip():
        raise SeedError(f"{path}: empty file")
    header = lines[0].rstrip("\r").split("\t")
    if header != expect:
        raise SeedError(f"{path}: header {header} != expected {expect}")
    rows = []
    for n, line in enumerate(lines[1:], start=2):
        line = line.rstrip("\r")
        if not line.strip() or line.startswith("#"):
            continue
        cells = line.split("\t")
        if len(cells) > len(expect):
            raise SeedError(f"{path}:{n}: {len(cells)} fields, at most {len(expect)} allowed (stray tab?)")
        cells += [""] * (len(expect) - len(cells))
        row = {k: v.strip() for k, v in zip(expect, cells)}
        row["_line"] = n
        rows.append(row)
    try:
        rel = path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:                      # a seed file outside the repository keeps its absolute path
        rel = path.resolve().as_posix()
    return SeedFile(path=path, rel=rel, sha512=sha512_bytes(raw), size=len(raw), rows=rows)


def scheme_files() -> dict[str, list[Path]]:
    """scheme id -> its concept seed files."""
    out: dict[str, list[Path]] = {"acat": sorted((SEED_DIR / "compendium" / "acat").glob("*.tsv"))}
    for p in sorted((SEED_DIR / "schemes").glob("*.tsv")):
        out[p.stem] = [p]
    return out


def read_scheme(scheme: str, paths: list[Path]) -> list[ConceptRow]:
    concepts: list[ConceptRow] = []
    for p in paths:
        sf = read_tsv(p, CONCEPT_COLUMNS)
        for r in sf.rows:
            where = f"{sf.rel}:{r['_line']}"
            if not r["code"] or not r["label"]:
                raise SeedError(f"{where}: code and label are required")
            a, b = parse_when(r["when"], where)
            concepts.append(ConceptRow(
                scheme=scheme, code=r["code"], broader=_split(r["broader"]), label=r["label"],
                alt=_split(r["alt"]), scope_note=r["scope_note"] or None, related=_split(r["related"]),
                facets=_split(r["facets"]), notation=r["notation"] or None, time_from=a, time_to=b,
                source=sf, line=r["_line"]))
    return concepts


def validate_scheme(scheme: str, rows: list[ConceptRow]) -> list[str]:
    """Structural checks inside one scheme. Returns a list of problems (empty = valid)."""
    problems: list[str] = []
    by_code: dict[str, ConceptRow] = {}
    for r in rows:
        if r.code in by_code:
            first = by_code[r.code]
            problems.append(f"{r.source.rel}:{r.line}: duplicate code {r.code!r} (first at {first.source.rel}:{first.line})")
        else:
            by_code[r.code] = r
    for r in rows:
        for b in r.broader:
            if b not in by_code:
                problems.append(f"{r.source.rel}:{r.line}: {r.code} has unknown broader {b!r}")
            if b == r.code:
                problems.append(f"{r.source.rel}:{r.line}: {r.code} is its own broader")
        for rel in r.related:
            if rel not in by_code:
                problems.append(f"{r.source.rel}:{r.line}: {r.code} has unknown related {rel!r}")
            if rel in r.broader:
                problems.append(f"{r.source.rel}:{r.line}: {r.code} lists {rel!r} as both broader and related")
    # cycles in the broader graph (iterative DFS with colours)
    WHITE, GREY, BLACK = 0, 1, 2
    colour = {c: WHITE for c in by_code}
    for start in by_code:
        if colour[start] != WHITE:
            continue
        stack = [(start, iter(by_code[start].broader))]
        colour[start] = GREY
        while stack:
            node, it = stack[-1]
            nxt = next((b for b in it if b in by_code), None)
            if nxt is None:
                colour[node] = BLACK
                stack.pop()
            elif colour[nxt] == GREY:
                path = [n for n, _ in stack] + [nxt]
                problems.append(f"{scheme}: cycle in broader: {' -> '.join(path)}")
                colour[nxt] = BLACK
            elif colour[nxt] == WHITE:
                colour[nxt] = GREY
                stack.append((nxt, iter(by_code[nxt].broader)))
    if not any(not r.broader for r in rows):
        problems.append(f"{scheme}: no top concept (every concept has a broader)")
    # SKOS S27: a related link must not restate the hierarchy (no related link to an ancestor)
    ancestors: dict[str, set[str]] = {}

    def ancestors_of(code: str) -> set[str]:
        if code not in ancestors:
            ancestors[code] = set()                      # guard against cycles, reported above
            out: set[str] = set()
            for b in by_code[code].broader if code in by_code else []:
                if b in by_code:
                    out |= {b} | ancestors_of(b)
            ancestors[code] = out
        return ancestors[code]
    for r in rows:
        for rel in r.related:
            if rel in by_code and (rel in ancestors_of(r.code) or r.code in ancestors_of(rel)):
                problems.append(f"{r.source.rel}:{r.line}: {r.code} lists {rel!r} as related, but one is an"
                                f" ancestor of the other (SKOS S27)")
    return problems


def read_all() -> tuple[dict[str, list[ConceptRow]], list[str]]:
    schemes: dict[str, list[ConceptRow]] = {}
    problems: list[str] = []
    for scheme, paths in scheme_files().items():
        rows = read_scheme(scheme, paths)
        problems += validate_scheme(scheme, rows)
        schemes[scheme] = rows
    return schemes, problems


# ─── loading ────────────────────────────────────────────────────────────────


def upsert_source_seed(conn: sqlite3.Connection, sf: SeedFile) -> None:
    conn.execute(
        "INSERT INTO source(sha512, bytes, kind, name, uri, license, first_seen) VALUES (?,?,?,?,?,?,?)"
        " ON CONFLICT(sha512) DO NOTHING",
        (sf.sha512, sf.size, "seed", sf.rel, sf.rel, "authored in this repository", utcnow()),
    )


def load_scheme_registry(conn: sqlite3.Connection) -> SeedFile:
    sf = read_tsv(SEED_DIR / "schemes.tsv", ["id", "title", "origin", "license", "homepage", "description"])
    upsert_source_seed(conn, sf)
    for r in sf.rows:
        conn.execute(
            "INSERT INTO scheme(id, title, description, origin, license, homepage, source_sha512)"
            " VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,"
            " description=excluded.description, origin=excluded.origin, license=excluded.license,"
            " homepage=excluded.homepage, source_sha512=excluded.source_sha512",
            (r["id"], r["title"], r["description"] or None, r["origin"], r["license"] or None,
             r["homepage"] or None, sf.sha512),
        )
    return sf


def load_concepts(conn: sqlite3.Connection, schemes: dict[str, list[ConceptRow]]) -> dict:
    """Upsert concepts, their English labels, broader and related edges. Facets and
    mappings are linked later, once corpora have supplied the concepts they point to."""
    stats = {"new": 0, "changed": 0, "unchanged": 0, "deprecated": 0, "edges": 0, "related": 0}
    seen_sources: set[str] = set()
    for scheme, rows in schemes.items():
        present = {r.id for r in rows}
        for r in rows:
            if r.source.sha512 not in seen_sources:
                upsert_source_seed(conn, r.source)
                seen_sources.add(r.source.sha512)
            old = conn.execute(
                "SELECT label, scope_note, notation, time_from, time_to, status, source_sha512 FROM concept WHERE id = ?",
                (r.id,)).fetchone()
            new = (r.label, r.scope_note, r.notation, r.time_from, r.time_to, "active", r.source.sha512)
            if old is None:
                conn.execute(
                    "INSERT INTO concept(id, scheme, code, label, scope_note, notation, time_from, time_to, status,"
                    " source_sha512) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (r.id, scheme, r.code, *new))
                stats["new"] += 1
            elif tuple(old) != new:
                conn.execute(
                    "UPDATE concept SET label=?, scope_note=?, notation=?, time_from=?, time_to=?, status=?,"
                    " source_sha512=? WHERE id = ?", (*new, r.id))
                stats["changed"] += 1
            else:
                stats["unchanged"] += 1
        # identities never disappear: anything no longer in the seeds is deprecated
        for (cid,) in conn.execute(
                "SELECT id FROM concept WHERE scheme = ? AND status = 'active'", (scheme,)).fetchall():
            if cid not in present and _is_seed_owned(conn, cid):
                conn.execute("UPDATE concept SET status = 'deprecated' WHERE id = ?", (cid,))
                ledger.record(conn, ACTOR, "deprecate", target=cid,
                              detail={"reason": "no longer present in the seed files"},
                              undo=f"restore the row for {cid} in its seed file and run `acat build`")
                stats["deprecated"] += 1
    # seed-derived English labels and edges are regenerated from the current seeds; rows from
    # any earlier version of a concept seed file go too (they are reproducible from git history)
    for table in ("label", "broader", "related"):
        conn.execute(f"DELETE FROM {table} WHERE source_sha512 IN ({SEED_CONCEPT_SOURCES})")
    for scheme, rows in schemes.items():
        for r in rows:
            conn.execute("INSERT OR IGNORE INTO label(concept_id, lang, kind, text, source_sha512) VALUES (?,?,?,?,?)",
                         (r.id, "en", "pref", nfc(r.label), r.source.sha512))
            for a in r.alt:
                conn.execute("INSERT OR IGNORE INTO label(concept_id, lang, kind, text, source_sha512)"
                             " VALUES (?,?,?,?,?)", (r.id, "en", "alt", nfc(a), r.source.sha512))
            for b in r.broader:
                conn.execute("INSERT OR IGNORE INTO broader(child, parent, source_sha512) VALUES (?,?,?)",
                             (r.id, f"{scheme}/{b}", r.source.sha512))
                stats["edges"] += 1
            for rel in r.related:
                a, b = sorted((r.id, f"{scheme}/{rel}"))
                conn.execute("INSERT OR IGNORE INTO related(a, b, source_sha512) VALUES (?,?,?)",
                             (a, b, r.source.sha512))
                stats["related"] += 1
    return stats


def _is_seed_owned(conn: sqlite3.Connection, cid: str) -> bool:
    row = conn.execute("SELECT s.kind FROM concept c JOIN source s ON s.sha512 = c.source_sha512 WHERE c.id = ?",
                       (cid,)).fetchone()
    return row is not None and row[0] == "seed"


def link_facets_and_mappings(conn: sqlite3.Connection, schemes: dict[str, list[ConceptRow]]) -> dict:
    """Second pass, after corpora are imported: facets (e.g. space/m49-002) and authored crosswalks."""
    stats = {"facets": 0, "facets_dangling": [], "mappings": 0, "mappings_dangling": []}
    conn.execute(f"DELETE FROM facet WHERE source_sha512 IN ({SEED_CONCEPT_SOURCES})")
    for rows in schemes.values():
        for r in rows:
            for f in r.facets:
                if conn.execute("SELECT 1 FROM concept WHERE id = ?", (f,)).fetchone() is None:
                    stats["facets_dangling"].append(f"{r.id} -> {f}")
                    continue
                conn.execute("INSERT OR IGNORE INTO facet(concept_id, facet_id, source_sha512) VALUES (?,?,?)",
                             (r.id, f, r.source.sha512))
                stats["facets"] += 1
    cw_path = SEED_DIR / "crosswalk" / "acat-external.tsv"
    sf = read_tsv(cw_path, ["from", "to", "relation", "note"])
    upsert_source_seed(conn, sf)
    conn.execute("DELETE FROM mapping WHERE source_sha512 IN (SELECT sha512 FROM source WHERE kind = 'seed'"
                 " AND name = ?)", (sf.rel,))
    for r in sf.rows:
        missing = [x for x in (r["from"], r["to"])
                   if conn.execute("SELECT 1 FROM concept WHERE id = ?", (x,)).fetchone() is None]
        if missing:
            stats["mappings_dangling"].append(f"{sf.rel}:{r['_line']}: unknown {', '.join(missing)}")
            continue
        conn.execute(
            "INSERT INTO mapping(from_id, to_id, relation, method, status, reviewer, note, source_sha512)"
            " VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(from_id, to_id) DO UPDATE SET relation=excluded.relation,"
            " method=excluded.method, status=excluded.status, note=excluded.note, source_sha512=excluded.source_sha512",
            (r["from"], r["to"], r["relation"], "authored", "accepted", "seed", r["note"] or None, sf.sha512))
        stats["mappings"] += 1
    return stats
