"""`acat build`: seeds + sealed corpora -> the catalogue database, in one transaction.

The catalogue is a pure function of what is in git (seed/*.tsv, corpora/*/corpus.sqlite) plus its
own ledger. Nothing is fetched here; fetching happens in `acat fetch …` and lands in corpora first.
"""
from __future__ import annotations

import re
import sqlite3
from collections import defaultdict, deque
from pathlib import Path

from . import compendium, ledger
from .corpusfile import CORPORA_DIR, CorpusFile
from .db import DEFAULT_DB, connect, init_schema
from .sources import external, m49, wikidata, wikipedia
from .textkeys import KEY_VERSION, cjk_bigrams, fold_key, has_cjk, nfc
from .util import REPO_ROOT, utcnow

ACTOR = "acat build"


def latest_corpus(family: str) -> CorpusFile | None:
    """Newest sealed corpus named '<family>-<yyyymmdd>'."""
    found = []
    for p in CORPORA_DIR.glob(f"{family}-*/corpus.sqlite"):
        m = re.fullmatch(rf"{re.escape(family)}-(\d{{8}})", p.parent.name)
        if m:
            found.append((m.group(1), p))
    if not found:
        return None
    return CorpusFile(sorted(found)[-1][1], readonly=True)


def register_corpus(conn: sqlite3.Connection, corpus: CorpusFile) -> None:
    meta = corpus.meta()
    conn.execute(
        "INSERT INTO corpus(name, title, description, license, path, manifest_sha512, items, sealed_at, imported_at)"
        " VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET title=excluded.title,"
        " description=excluded.description, license=excluded.license, manifest_sha512=excluded.manifest_sha512,"
        " items=excluded.items, sealed_at=excluded.sealed_at, imported_at=excluded.imported_at",
        (meta["name"], meta["title"], meta.get("description"), meta.get("license"),
         corpus.path.resolve().relative_to(REPO_ROOT).as_posix(), corpus.manifest(), len(corpus.items()),
         meta.get("sealed_at"), utcnow()))


def rebuild_search(conn: sqlite3.Connection) -> dict:
    """Word indexes over NFC text, and case-key trigram indexes for substring/regex search
    (see textkeys.py). All derived: rebuilt from the tables on every build."""
    conn.execute("DELETE FROM concept_fts")
    conn.execute("DELETE FROM concept_key")
    rows = conn.execute(
        "SELECT c.id, c.label,"
        " (SELECT group_concat(text, ' | ') FROM label l WHERE l.concept_id = c.id AND l.lang = 'en' AND l.kind = 'alt'),"
        " c.scope_note FROM concept c WHERE c.status = 'active' AND c.scheme <> 'wd' ORDER BY c.id").fetchall()
    for cid, label, alts, note in rows:
        label, alts, note = nfc(label), nfc(alts or ""), nfc(note or "")
        conn.execute("INSERT INTO concept_fts(id, label, alts, scope_note) VALUES (?,?,?,?)", (cid, label, alts, note))
        text = f"{label} | {alts} | {note}"
        conn.execute("INSERT INTO concept_key(id, text, k) VALUES (?,?,?)", (cid, text, fold_key(text)))
    conn.execute("INSERT INTO label_fts(label_fts) VALUES ('rebuild')")
    for t in ("label_key", "label_cjk", "passage_key"):
        conn.execute(f"INSERT INTO {t}({t}) VALUES ('delete-all')")
    labels = conn.execute("SELECT id, text FROM label ORDER BY id").fetchall()
    conn.executemany("INSERT INTO label_key(rowid, k) VALUES (?, ?)", [(i, fold_key(nfc(t))) for i, t in labels])
    conn.executemany("INSERT INTO label_cjk(rowid, k) VALUES (?, ?)",
                     [(i, cjk_bigrams(nfc(t))) for i, t in labels if has_cjk(t)])
    conn.execute("INSERT INTO passage_fts(passage_fts) VALUES ('rebuild')")
    passages = conn.execute("SELECT id, text FROM passage ORDER BY id").fetchall()
    conn.executemany("INSERT INTO passage_key(rowid, k) VALUES (?, ?)", [(i, fold_key(nfc(t))) for i, t in passages])
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('key_version', ?)", (KEY_VERSION,))
    return {"concepts": len(rows), "labels": len(labels), "passages": len(passages),
            "cjk_labels": sum(1 for _, t in labels if has_cjk(t)), "key_version": KEY_VERSION}


def compute_stats(conn: sqlite3.Connection) -> int:
    """root, depth, descendants, docs, sitelinks and label languages for every concept."""
    concepts = {r[0]: r[1] for r in conn.execute("SELECT id, scheme FROM concept WHERE status = 'active'")}
    parents: dict[str, list[str]] = defaultdict(list)
    children: dict[str, list[str]] = defaultdict(list)
    for child, parent in conn.execute("SELECT child, parent FROM broader"):
        if child in concepts and parent in concepts and concepts[child] == concepts[parent]:
            parents[child].append(parent)
            children[parent].append(child)
    roots = sorted(c for c in concepts if not parents.get(c))
    depth: dict[str, int] = {}
    root_of: dict[str, str] = {}
    queue = deque()
    for r in roots:                      # multi-source BFS; ties go to the smaller root id
        depth[r], root_of[r] = 0, r
        queue.append(r)
    while queue:
        node = queue.popleft()
        for ch in sorted(children.get(node, [])):
            if ch not in depth:
                depth[ch], root_of[ch] = depth[node] + 1, root_of[node]
                queue.append(ch)
    descendants: dict[str, int] = {}
    for c in concepts:
        seen: set[str] = set()
        stack = list(children.get(c, []))
        while stack:
            x = stack.pop()
            if x not in seen:
                seen.add(x)
                stack.extend(children.get(x, []))
        descendants[c] = len(seen)
    docs = dict(conn.execute("SELECT concept_id, count(*) FROM document_concept GROUP BY concept_id").fetchall())
    langs = dict(conn.execute("SELECT concept_id, count(DISTINCT lang) FROM label GROUP BY concept_id").fetchall())
    sitelinks: dict[str, int] = {}
    for cid, value in conn.execute("SELECT concept_id, value FROM attribute WHERE key = 'sitelinks'"):
        sitelinks[cid] = int(value)
    for frm, to in conn.execute("SELECT from_id, to_id FROM mapping WHERE status = 'accepted'"
                                " AND relation IN ('exactMatch', 'closeMatch') AND to_id LIKE 'wd/%'"):
        if to in sitelinks:
            sitelinks[frm] = max(sitelinks.get(frm, 0), sitelinks[to])
    conn.execute("DELETE FROM concept_stat")
    conn.executemany(
        "INSERT INTO concept_stat(concept_id, root, depth, descendants, docs, sitelinks, label_langs)"
        " VALUES (?,?,?,?,?,?,?)",
        [(c, root_of.get(c), depth.get(c), descendants[c], docs.get(c, 0), sitelinks.get(c), langs.get(c, 0))
         for c in concepts])
    return len(concepts)


def build(db_path: str | Path = DEFAULT_DB, *, verbose: bool = True) -> dict:
    say = print if verbose else (lambda *a, **k: None)
    schemes, problems = compendium.read_all()
    if problems:
        raise compendium.SeedError("seed files are invalid:\n  " + "\n  ".join(problems))
    conn = connect(db_path, create=True)
    init_schema(conn)
    report: dict = {}
    try:
        conn.execute("BEGIN")
        ledger.record(conn, ACTOR, "build-start", detail={"db": str(db_path)})
        reg = compendium.load_scheme_registry(conn)
        report["concepts"] = compendium.load_concepts(conn, schemes)
        say(f"compendium: {report['concepts']}")

        for p in sorted(CORPORA_DIR.glob("*/corpus.sqlite")):
            c = CorpusFile(p, readonly=True)
            register_corpus(conn, c)
            c.close()

        if (c := latest_corpus("un-m49")) is not None:
            report["m49"] = m49.import_into(conn, c, ACTOR)
            say(f"M49 ({c.name}): {report['m49']}")
        if (c := latest_corpus("external-schemes")) is not None:
            rep = external.verify(conn, c, ACTOR)
            report["external"] = {"checked": rep["checked"], "verified": rep["verified"],
                                  "unverified": rep["unverified"]}
            say(f"external captions ({c.name}): {report['external']}")

        decisions = wikidata.read_decisions()
        if decisions:
            sf = compendium.read_tsv(wikidata.DECISIONS, wikidata.DECISION_COLUMNS)
            compendium.upsert_source_seed(conn, sf)
            if (c := latest_corpus("wikidata-entities")) is not None:
                report["wikidata"] = wikidata.import_entities(conn, c, decisions, ACTOR)
                report["claims"] = wikidata.import_claims(conn, c, ACTOR)
                say(f"wikidata ({c.name}): {report['wikidata']} claims: {report['claims']}")
            report["wikidata_mappings"] = wikidata.import_decisions(conn, decisions, sf.sha512)

        if (c := latest_corpus("wikipedia-en-intros")) is not None:
            title_to_concepts: dict[str, list[str]] = defaultdict(list)
            for cid, title in conn.execute(
                    "SELECT m.from_id, a.value FROM mapping m JOIN attribute a ON a.concept_id = m.to_id"
                    " AND a.key = 'enwiki' WHERE m.status = 'accepted' AND m.relation IN ('exactMatch','closeMatch')"):
                title_to_concepts[title].append(cid)
            report["documents"] = wikipedia.import_documents(conn, c, title_to_concepts, ACTOR)
            say(f"documents ({c.name}): {report['documents']}")

        link = compendium.link_facets_and_mappings(conn, schemes)
        report["links"] = {"facets": link["facets"], "mappings": link["mappings"],
                           "facets_dangling": link["facets_dangling"],
                           "mappings_dangling": link["mappings_dangling"]}
        say(f"facets/mappings: {report['links']}")

        report["search"] = rebuild_search(conn)
        report["stats"] = compute_stats(conn)
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('built_at', ?)", (utcnow(),))
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('schemes_seed_sha512', ?)", (reg.sha512,))
        ledger.record(conn, ACTOR, "build-end",
                      detail={"concepts": report["concepts"], "search": report["search"]},
                      receipt=f"ledger-head-before:{ledger.head(conn)[:32]}",
                      undo="rebuilds are idempotent; check out the previous seeds/corpora and run `acat build`")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    return report
