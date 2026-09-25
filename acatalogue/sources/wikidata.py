"""Wikidata: reconciliation (search -> proposal -> human review), entities (multilingual labels,
sitelinks) and a few attributed claims via SPARQL. Every response is kept as exact bytes."""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
import urllib.parse
from pathlib import Path

from .. import ledger
from ..corpusfile import CorpusFile, corpus_path
from ..fetch import Fetcher, mediawiki_check, sparql_check
from ..textkeys import nfc
from ..util import REPO_ROOT, today_compact, utcnow

API = "https://www.wikidata.org/w/api.php"
MAXLAG = "5"      # Wikimedia asks automated clients to back off while replication lags
SPARQL = "https://query.wikidata.org/sparql"
LICENSE = "CC0 1.0 (Wikidata)"
ATTRIBUTION = "Wikidata contributors"
DECISIONS = REPO_ROOT / "seed" / "crosswalk" / "acat-wikidata.tsv"
DECISION_COLUMNS = ["from", "to", "relation", "status", "method", "reviewer", "note"]
LABEL_RELATIONS = {"exactMatch", "closeMatch"}   # only these donate their labels to our concept
# Lsjbot mass-generated the Cebuano and Waray editions (species and places), so their sitelinks
# measure a bot's reach, not human attention: the attention count leaves them out (raw count kept)
BOT_WIKIS = ("cebwiki", "warwiki")
PROJECT_WIKIS = ("commonswiki", "specieswiki", "metawiki", "mediawikiwiki", "wikidatawiki", "sourceswiki")


def wikipedia_editions(sitelinks: dict, *, with_bot_editions: bool = False) -> list[str]:
    """Language editions of Wikipedia among an item's sitelinks (not Commons, Wikispecies, etc.)."""
    return [k for k in sitelinks if k.endswith("wiki") and k not in PROJECT_WIKIS
            and (with_bot_editions or k not in BOT_WIKIS)]
CLAIM_PROPERTIES = {
    "P31": "instance of", "P279": "subclass of", "P361": "part of", "P527": "has part(s)",
    "P2578": "studies", "P2579": "studied by", "P1269": "facet of",
}
# A candidate is set aside (never silently dropped: reviewers still see the full list) when its
# description names a Wikimedia page type or begins by naming a work, a person name or a place.
# Anchored at the start on purpose: 'study of the synthesis …' must not trip on 'thesis'.
_JUNK_ANYWHERE = re.compile(
    r"Wikimedia (disambiguation|category|template|list|project)|scholarly article|scientific article|"
    r"\bfamily name\b|\bgiven name\b|\bsurname\b", re.I)
_JUNK_START = re.compile(
    r"^(\d{4}s?\S*\s+)?([\w-]+\s+)?"
    r"(film|album|song|single|novel|book|short story|painting|sculpture|statue|lithograph|photograph|"
    r"journal|academic journal|magazine|newspaper|periodical|company|band|musical group|record label|"
    r"video game|television|tv series|reality|episode|play|opera|podcast|comic|manga|extended play|"
    r"software|village|commune|municipality|town|ghost town|locality|building|river|mountain|lake|"
    r"asteroid|genus|species|doctoral thesis|thesis|chapter|encyclopedia article|term in coinage|"
    r"category of heraldic)\b", re.I)


class _Junk:
    @staticmethod
    def search(desc: str):
        return _JUNK_ANYWHERE.search(desc) or _JUNK_START.search(desc.strip())


_JUNK = _Junk()


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).casefold().replace("&", " and ")
    t = re.sub(r"[^\w\s]", " ", t)
    return " ".join(t.split())


# ─── reconciliation ─────────────────────────────────────────────────────────


def _search_url(text: str) -> str:
    q = {"action": "wbsearchentities", "search": text, "language": "en", "uselang": "en",
         "type": "item", "limit": "7", "format": "json", "maxlag": MAXLAG}
    return f"{API}?{urllib.parse.urlencode(q)}"


def search(concepts: list[tuple[str, str, list[str]]], name: str | None = None) -> CorpusFile:
    """concepts: (code, label, alts). One search per label; a second per concept on its first alt
    label when the label found no exact match. Resumable: stored items are not refetched."""
    name = name or f"wikidata-reconcile-{today_compact()}"
    corpus = CorpusFile(corpus_path(name), create=True, name=name,
                        title="Wikidata search responses used to reconcile the ACAT compendium",
                        license=LICENSE, description="wbsearchentities responses, exact bytes, one item per query.")
    f = Fetcher(corpus, min_interval=0.5)
    for i, (code, label, alts) in enumerate(concepts, 1):
        raw = f.fetch(f"search/{code}/label", _search_url(label), license=LICENSE, attribution=ATTRIBUTION,
                      check=mediawiki_check)
        hits = json.loads(raw).get("search", [])
        if alts and not any(_is_exact(h, label, alts) for h in hits):
            f.fetch(f"search/{code}/alt", _search_url(alts[0]), license=LICENSE, attribution=ATTRIBUTION,
                    check=mediawiki_check)
        if i % 50 == 0:
            print(f"  searched {i}/{len(concepts)}", flush=True)
    return corpus


def _is_exact(hit: dict, label: str, alts: list[str]) -> bool:
    ours = {_norm(label), *(_norm(a) for a in alts)}
    theirs = {_norm(hit.get("label", ""))}
    match = hit.get("match") or {}
    if match.get("language", "en") == "en" and match.get("text"):
        theirs.add(_norm(match["text"]))
    return bool(ours & theirs)


def propose(concepts: list[tuple[str, str, list[str]]], corpus: CorpusFile) -> list[dict]:
    """For each concept: the automatic pick (or none) and the other candidates, for review."""
    out = []
    for code, label, alts in concepts:
        cands: list[dict] = []
        for part in ("label", "alt"):
            key = f"search/{code}/{part}"
            if corpus.has(key):
                for h in json.loads(corpus.get(key)).get("search", []):
                    if all(c["id"] != h["id"] for c in cands):
                        cands.append({"id": h["id"], "label": h.get("label", ""),
                                      "description": h.get("description", ""),
                                      "exact": _is_exact(h, label, alts),
                                      "junk": bool(_JUNK.search(h.get("description", "") or ""))})
        pick = next((c for c in cands if c["exact"] and not c["junk"]), None)
        out.append({"code": code, "label": label, "pick": pick,
                    "others": [c for c in cands if c is not pick and not c["junk"]][:3]})
    return out


def _terms(label: str, alts: list[str]) -> list[tuple[str, str]]:
    """Label spellings to look up: as written, with a lower-case first letter, all lower case
    (Wikidata writes common nouns in lower case). Returns (term, 'label' | 'alt')."""
    out: list[tuple[str, str]] = []
    for origin, texts in (("label", [label]), ("alt", alts)):
        for t in texts:
            for v in (t, t[:1].lower() + t[1:], t.lower()):
                if v and (v, origin) not in out and all(v != x for x, _ in out):
                    out.append((v, origin))
    return out


def _sparql_literal(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"@en'


def reconcile_sparql(concepts: list[tuple[str, str, list[str]]], corpus: CorpusFile, batch: int = 150) -> None:
    """Exact English-label lookups in batches (the search API rate-limits shared addresses).
    Each response is stored as exact bytes in the reconcile corpus."""
    f = Fetcher(corpus, min_interval=2.0)
    terms = sorted({t for _, label, alts in concepts for t, _ in _terms(label, alts)})
    for n, start in enumerate(range(0, len(terms), batch), 1):
        values = " ".join(_sparql_literal(t) for t in terms[start:start + batch])
        query = ("SELECT ?term ?item ?desc ?sl WHERE {\n"
                 f"  VALUES ?term {{ {values} }}\n"
                 "  ?item rdfs:label ?term .\n"
                 "  ?item wikibase:sitelinks ?sl .\n"
                 "  FILTER(?sl > 0)\n"
                 '  OPTIONAL { ?item schema:description ?desc FILTER(lang(?desc) = "en") }\n'
                 "}")
        f.fetch(f"sparql/labels-{n:03d}.json", SPARQL, data={"query": query, "format": "json"},
                headers={"Accept": "application/sparql-results+json"}, license=LICENSE, attribution=ATTRIBUTION,
                check=sparql_check)


def propose_sparql(concepts: list[tuple[str, str, list[str]]], corpus: CorpusFile) -> list[dict]:
    """Candidates per concept from the stored label lookups; the automatic pick is the non-junk
    candidate matched on our own label (before alt labels) with the most sitelinks."""
    by_term: dict[str, list[dict]] = {}
    for it in corpus.items():
        if not it["name"].startswith("sparql/labels-"):
            continue
        for b in json.loads(corpus.get(it["name"]))["results"]["bindings"]:
            by_term.setdefault(b["term"]["value"], []).append({
                "id": b["item"]["value"].rsplit("/", 1)[-1],
                "description": b.get("desc", {}).get("value", ""),
                "sitelinks": int(b["sl"]["value"]),
            })
    out = []
    for code, label, alts in concepts:
        cands: dict[str, dict] = {}
        for term, origin in _terms(label, alts):
            for c in by_term.get(term, []):
                prev = cands.get(c["id"])
                rank = 0 if origin == "label" else 1
                if prev is None or rank < prev["rank"]:
                    cands[c["id"]] = {**c, "term": term, "rank": rank,
                                      "junk": bool(_JUNK.search(c["description"] or ""))}
        ordered = sorted(cands.values(), key=lambda c: (c["junk"], c["rank"], -c["sitelinks"], int(c["id"][1:])))
        pick = next((c for c in ordered if not c["junk"]), None)
        out.append({"code": code, "label": label, "pick": pick,
                    "others": [c for c in ordered if c is not pick and not c["junk"]][:3]})
    return out


def read_decisions(path: Path = DECISIONS) -> list[dict]:
    from ..compendium import read_tsv
    if not path.exists():
        return []
    return read_tsv(path, DECISION_COLUMNS).rows


# ─── entities ───────────────────────────────────────────────────────────────


def fetch_entities(qids: list[str], name: str | None = None) -> CorpusFile:
    name = name or f"wikidata-entities-{today_compact()}"
    corpus = CorpusFile(corpus_path(name), create=True, name=name,
                        title="Wikidata entities for reconciled concepts: labels, descriptions, aliases, sitelinks",
                        license=LICENSE, description="wbgetentities responses in batches of 50, exact bytes.")
    f = Fetcher(corpus, min_interval=1.5)
    qids = sorted(set(qids), key=lambda q: int(q[1:]))
    for n, start in enumerate(range(0, len(qids), 50), 1):
        batch = qids[start:start + 50]
        q = {"action": "wbgetentities", "ids": "|".join(batch), "props": "labels|descriptions|aliases|sitelinks",
             "format": "json", "maxlag": MAXLAG}
        f.fetch(f"entities/batch-{n:03d}.json", f"{API}?{urllib.parse.urlencode(q)}",
                license=LICENSE, attribution=ATTRIBUTION, check=mediawiki_check)
    return corpus


def fetch_claims(qids: list[str], corpus: CorpusFile) -> None:
    """One SPARQL query per 200 items for a handful of structural properties, with ranks."""
    f = Fetcher(corpus, min_interval=2.0)
    qids = sorted(set(qids), key=lambda q: int(q[1:]))
    props = " ".join(f'(p:{p} ps:{p} "{p}")' for p in CLAIM_PROPERTIES)
    for n, start in enumerate(range(0, len(qids), 200), 1):
        values = " ".join(f"wd:{q}" for q in qids[start:start + 200])
        query = (
            "SELECT ?item ?pid ?value ?valueLabel ?rank WHERE {\n"
            f"  VALUES ?item {{ {values} }}\n"
            f"  VALUES (?p ?ps ?pid) {{ {props} }}\n"
            "  ?item ?p ?st . ?st ?ps ?value . ?st wikibase:rank ?rank .\n"
            "  FILTER(isIRI(?value))\n"
            '  SERVICE wikibase:label { bd:serviceParam wikibase:language "en,mul". }\n'
            "}")
        f.fetch(f"sparql/claims-{n:03d}.json", SPARQL, data={"query": query, "format": "json"},
                headers={"Accept": "application/sparql-results+json"}, license=LICENSE, attribution=ATTRIBUTION,
                check=sparql_check)


# ─── statements (entity JSON) ───────────────────────────────────────────────


def _entity_key(eid: str) -> tuple[str, int]:
    return eid[0], int(eid[1:])


def referenced_entities(payload: dict) -> set[str]:
    """Every item and property a wbgetentities payload names: predicates, and the item/property values of
    main snaks, qualifiers and references. (Lexemes and entity schemas cannot be fetched with it.)"""
    out: set[str] = set()

    def snak(s: dict) -> None:
        out.add(s["property"])
        dv = s.get("datavalue") if s.get("snaktype") == "value" else None
        if dv and dv.get("type") == "wikibase-entityid":
            eid = _entity_id(dv["value"])
            if re.fullmatch(r"[QP]\d+", eid):
                out.add(eid)

    for ent in payload.get("entities", {}).values():
        for statements in ent.get("claims", {}).values():
            for st in statements:
                snak(st["mainsnak"])
                for snaks in st.get("qualifiers", {}).values():
                    for s in snaks:
                        snak(s)
                for ref in st.get("references", []):
                    for snaks in ref.get("snaks", {}).values():
                        for s in snaks:
                            snak(s)
    return out


def fetch_statements(qids: list[str], name: str | None = None) -> CorpusFile:
    """Entity JSON for the reconciled items: every statement with its id, rank, qualifiers and references,
    and the entity's revision id. Then the English and multilingual ('mul') labels of every item and
    property those statements name, so claims can be read without another lookup. Resumable."""
    name = name or f"wikidata-statements-{today_compact()}"
    corpus = CorpusFile(corpus_path(name), create=True, name=name,
                        title="Wikidata statements of reconciled concepts, with qualifiers, references and revisions",
                        license=LICENSE,
                        description="wbgetentities props=claims|info in batches of 50 (entities/), then labels in en "
                                    "and mul for every item and property they reference (labels/). Exact bytes.")
    f = Fetcher(corpus, min_interval=1.5)
    qids = sorted(set(qids), key=_entity_key)
    for n, start in enumerate(range(0, len(qids), 50), 1):
        q = {"action": "wbgetentities", "ids": "|".join(qids[start:start + 50]), "props": "claims|info",
             "format": "json", "maxlag": MAXLAG}
        f.fetch(f"entities/batch-{n:03d}.json", f"{API}?{urllib.parse.urlencode(q)}",
                license=LICENSE, attribution=ATTRIBUTION, check=mediawiki_check)
    named: set[str] = set()
    for it in corpus.items():
        if it["name"].startswith("entities/"):
            named |= referenced_entities(json.loads(corpus.get(it["name"])))
    # Labels come from the query service, 2,000 entities per query: a few requests instead of hundreds of
    # API calls. (The 2026-09-25 corpus also holds 19 earlier API label batches; those ids are skipped.)
    for it in corpus.items():
        if it["name"].startswith("labels/batch-"):
            named -= set(json.loads(corpus.get(it["name"])).get("entities", {}))
    todo = sorted(named, key=_entity_key)
    print(f"  {len(qids)} entities fetched; {len(todo)} referenced items and properties to label", flush=True)
    f = Fetcher(corpus, min_interval=2.0)
    for n, start in enumerate(range(0, len(todo), 2000), 1):
        values = " ".join(f"wd:{e}" for e in todo[start:start + 2000])
        query = ("SELECT ?e ?l WHERE {\n"
                 f"  VALUES ?e {{ {values} }}\n"
                 '  ?e rdfs:label ?l . FILTER(LANG(?l) = "en" || LANG(?l) = "mul")\n'
                 "}")
        f.fetch(f"labels/sparql-{n:03d}.json", SPARQL, data={"query": query, "format": "json"},
                headers={"Accept": "application/sparql-results+json"}, license=LICENSE, attribution=ATTRIBUTION,
                check=sparql_check)
    return corpus


def _entity_id(v: dict) -> str:
    if v.get("id"):
        return v["id"]
    prefix = {"item": "Q", "property": "P", "lexeme": "L"}.get(v.get("entity-type", "item"), "Q")
    return f"{prefix}{v['numeric-id']}"


def _register_source(conn: sqlite3.Connection, corpus: CorpusFile, item_name: str) -> str:
    it = corpus.item(item_name)
    conn.execute(
        "INSERT INTO source(sha512, bytes, kind, name, corpus, uri, retrieved_at, content_type, license,"
        " attribution, first_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(sha512) DO NOTHING",
        (it["sha512"], it["bytes"], "fetch", f"{corpus.name}:{item_name}", corpus.name, it["url"],
         it["retrieved_at"], it["content_type"], LICENSE, ATTRIBUTION, utcnow()))
    return it["sha512"]


def _ensure_scheme(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO scheme(id, title, origin, license, homepage) VALUES"
                 " ('wd', 'Wikidata', 'external', 'CC0 1.0', 'https://www.wikidata.org/') ON CONFLICT(id) DO NOTHING")


def _ensure_wd_concept(conn: sqlite3.Connection, qid: str, label: str, digest: str) -> None:
    conn.execute(
        "INSERT INTO concept(id, scheme, code, label, source_sha512) VALUES (?,?,?,?,?)"
        " ON CONFLICT(id) DO UPDATE SET label = excluded.label, source_sha512 = excluded.source_sha512",
        (f"wd/{qid}", "wd", qid, label or qid, digest))


def import_entities(conn: sqlite3.Connection, corpus: CorpusFile, decisions: list[dict],
                    actor: str = "acat build") -> dict:
    """wd/Q… concepts with all their labels; labels are also copied onto our concept when the
    reviewed mapping is exactMatch or closeMatch (each copied label keeps the Wikidata source hash)."""
    by_qid: dict[str, list[dict]] = {}
    for d in decisions:
        if d["status"] == "accepted" and d["to"].startswith("wd/"):
            by_qid.setdefault(d["to"][3:], []).append(d)
    stats = {"items": 0, "labels": 0, "copied_labels": 0, "missing": []}
    _ensure_scheme(conn)
    # labels from any Wikidata entities corpus are regenerated from the newest one and the current decisions
    conn.execute("DELETE FROM label WHERE source_sha512 IN"
                 " (SELECT sha512 FROM source WHERE corpus LIKE 'wikidata-entities-%')")
    for it in corpus.items():
        if not it["name"].startswith("entities/"):
            continue
        digest = _register_source(conn, corpus, it["name"])
        entities = json.loads(corpus.get(it["name"])).get("entities", {})
        for qid, ent in entities.items():
            if "missing" in ent:
                stats["missing"].append(qid)
                continue
            labels = ent.get("labels", {})
            en = labels.get("en", {}).get("value") or labels.get("mul", {}).get("value") or qid
            _ensure_wd_concept(conn, qid, en, digest)
            stats["items"] += 1
            rows = []
            for lang, v in labels.items():
                rows.append((lang, "pref", nfc(v["value"])))
            for lang, vs in ent.get("aliases", {}).items():
                rows += [(lang, "alt", nfc(v["value"])) for v in vs]
            for lang, v in ent.get("descriptions", {}).items():
                rows.append((lang, "desc", nfc(v["value"])))
            # Labels are stored once, on the concept that uses them (exact/close matches only). The wd/
            # item keeps its English name in concept.label; its full label set stays in the corpus bytes.
            stats["labels"] += len(rows)
            for target in [d["from"] for d in by_qid.get(qid, []) if d["relation"] in LABEL_RELATIONS]:
                prefs = {lang: text for lang, kind, text in rows if kind == "pref"}
                prefs.update(dict(conn.execute("SELECT lang, text FROM label WHERE concept_id = ? AND kind = 'pref'",
                                               (target,)).fetchall()))
                for lang, kind, text in rows:
                    # our own English preferred label stays ours: Wikidata's English label becomes an alt
                    if lang == "en" and kind == "pref":
                        kind = "alt"
                    # SKOS S13: the same literal is never both the preferred and an alternative label
                    if kind == "alt" and prefs.get(lang) == text:
                        continue
                    conn.execute("INSERT OR IGNORE INTO label(concept_id, lang, kind, text, source_sha512)"
                                 " VALUES (?,?,?,?,?)", (target, lang, kind, text, digest))
                    stats["copied_labels"] += 1
            sitelinks = ent.get("sitelinks", {})
            conn.execute("INSERT OR REPLACE INTO attribute(concept_id, key, value, source_sha512) VALUES (?,?,?,?)",
                         (f"wd/{qid}", "sitelinks", str(len(wikipedia_editions(sitelinks))), digest))
            conn.execute("INSERT OR REPLACE INTO attribute(concept_id, key, value, source_sha512) VALUES (?,?,?,?)",
                         (f"wd/{qid}", "sitelinks_all",
                          str(len(wikipedia_editions(sitelinks, with_bot_editions=True))), digest))
            if "enwiki" in sitelinks:
                conn.execute("INSERT OR REPLACE INTO attribute(concept_id, key, value, source_sha512)"
                             " VALUES (?,?,?,?)", (f"wd/{qid}", "enwiki", sitelinks["enwiki"]["title"], digest))
    ledger.record(conn, actor, "import-wikidata-entities", target=f"doc/{corpus.name}",
                  detail={k: (v if not isinstance(v, list) else len(v)) for k, v in stats.items()},
                  receipt=f"manifest:{corpus.manifest()}",
                  undo="labels are regenerated from the corpus on every build; remove the corpus from "
                       "corpora/ and rebuild to drop them")
    return stats


def import_decisions(conn: sqlite3.Connection, decisions: list[dict], seed_sha512: str) -> int:
    n = 0
    conn.execute("DELETE FROM mapping WHERE source_sha512 IN (SELECT sha512 FROM source WHERE kind = 'seed'"
                 " AND (name = 'seed/crosswalk/acat-wikidata.tsv' OR name LIKE 'seed/reviews/%'))")
    for d in decisions:
        # 'unmatched' rows record that a concept was reviewed and nothing equivalent was found;
        # they are kept in the seed file as curation history but create no mapping
        if not d["to"] or d["status"] not in ("accepted", "proposed", "rejected"):
            continue
        if conn.execute("SELECT 1 FROM concept WHERE id = ?", (d["from"],)).fetchone() is None:
            continue
        conn.execute(
            "INSERT INTO mapping(from_id, to_id, relation, method, status, reviewer, note, source_sha512)"
            " VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(from_id, to_id) DO UPDATE SET relation=excluded.relation,"
            " method=excluded.method, status=excluded.status, reviewer=excluded.reviewer, note=excluded.note,"
            " source_sha512=excluded.source_sha512",
            (d["from"], d["to"], d["relation"], d["method"], d["status"], d["reviewer"] or None,
             d["note"] or None, d.get("review_sha512") or seed_sha512))
        n += 1
    return n


def corpus_time(corpus: CorpusFile, prefix: str = "") -> str:
    """When the catalogue learned what a corpus says: the last retrieval among its items (named with
    `prefix`). Record time comes from the bytes, so rebuilding the database does not move it."""
    times = [it["retrieved_at"] for it in corpus.items() if it["name"].startswith(prefix)]
    return max(times) if times else (corpus.meta().get("sealed_at") or utcnow())


def import_claims(conn: sqlite3.Connection, corpus: CorpusFile, actor: str = "acat build") -> dict:
    """Claims read from WDQS result tables (subject, property, value, rank): the summary form, without
    statement ids, qualifiers or references. `import_statements` supersedes them where it has the entity."""
    stats = {"claims": 0, "new": 0}
    now = corpus_time(corpus, "sparql/claims-")
    _ensure_scheme(conn)
    for pid, label in CLAIM_PROPERTIES.items():
        conn.execute("INSERT INTO concept(id, scheme, code, label) VALUES (?,?,?,?) ON CONFLICT(id) DO NOTHING",
                     (f"wd/{pid}", "wd", pid, label))
    for it in corpus.items():
        if not it["name"].startswith("sparql/"):
            continue
        digest = _register_source(conn, corpus, it["name"])
        recorded = it["retrieved_at"]
        data = json.loads(corpus.get(it["name"]))
        for b in data["results"]["bindings"]:
            subj = b["item"]["value"].rsplit("/", 1)[-1]
            obj = b["value"]["value"].rsplit("/", 1)[-1]
            if not re.fullmatch(r"Q\d+", obj):
                continue
            rank = b["rank"]["value"].rsplit("#", 1)[-1].replace("Rank", "").lower()
            obj_label = b.get("valueLabel", {}).get("value", obj)
            conn.execute("INSERT INTO concept(id, scheme, code, label, source_sha512) VALUES (?,?,?,?,?)"
                         " ON CONFLICT(id) DO NOTHING", (f"wd/{obj}", "wd", obj, obj_label, digest))
            # Wikidata's deprecated rank is kept as the source's own rank; it is not a withdrawal by the
            # source (it also marks "never correct" values), so the epistemic status stays attributed
            cur = conn.execute(
                "INSERT OR IGNORE INTO claim(subject, predicate, object, rank, epistemic, source_sha512, recorded_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (f"wd/{subj}", f"wd/{b['pid']['value']}", f"wd/{obj}", rank, "epistemic/attributed", digest,
                 recorded))
            stats["claims"] += 1
            stats["new"] += cur.rowcount
    # record time moves on: claims read from an older Wikidata corpus are superseded by this one
    # (kept, never deleted; the new corpus restates whatever is still true)
    cur = conn.execute(
        "UPDATE claim SET superseded_at = ? WHERE superseded_at IS NULL AND source_sha512 IN"
        " (SELECT sha512 FROM source WHERE corpus LIKE 'wikidata-entities-%' AND corpus < ?)", (now, corpus.name))
    stats["superseded"] = cur.rowcount
    ledger.record(conn, actor, "import-wikidata-claims", target=f"doc/{corpus.name}", detail=stats,
                  receipt=f"manifest:{corpus.manifest()}",
                  undo="claims are never deleted; a later corpus supersedes them")
    return stats


# ─── statements: values, times, import ──────────────────────────────────────

_TIME = re.compile(r"([+-])(\d+)-(\d\d)-(\d\d)T")
JULIAN = "http://www.wikidata.org/entity/Q1985786"


def _julian_to_gregorian(year: int, month: int, day: int) -> tuple[int, int, int]:
    """Julian calendar date -> proleptic Gregorian, both with astronomical years (via the Julian day number)."""
    a = (14 - month) // 12
    y, m = year + 4800 - a, month + 12 * a - 3
    jdn = day + (153 * m + 2) // 5 + 365 * y + y // 4 - 32083
    a = jdn + 32044
    b = (4 * a + 3) // 146097
    c = a - 146097 * b // 4
    d = (4 * c + 3) // 1461
    e = c - 1461 * d // 4
    m = (5 * e + 2) // 153
    return 100 * b + d - 4800 + m // 10, m + 3 - 12 * (m // 10), e - (153 * m + 2) // 5 + 1


def _raw_time(v: dict) -> tuple[int, int, int, int, bool] | None:
    """(astronomical year, month, day, precision, stated in the Julian calendar?) of a Wikidata time value,
    as stated. The JSON counts 1 BCE as -0001, so negative years shift by one."""
    m = _TIME.match(v.get("time", ""))
    if not m:
        return None
    sign, y, mo, d = m.groups()
    year = int(y)
    if sign == "-":
        year = 1 - year
    return year, int(mo), int(d), int(v.get("precision", 9)), v.get("calendarmodel") == JULIAN


def wd_time_parts(v: dict) -> tuple[int, int, int, int] | None:
    """A Wikidata time value as (year, month, day, precision) with astronomical years (1 BCE = 0), cut to
    what the value states. Day-precision Julian dates are converted to the proleptic Gregorian calendar;
    a Julian month cannot be named in the Gregorian calendar, so it is cut to its year, and a Julian year
    keeps its number (its days are counted in its own calendar by time_bounds). Precisions coarser than a
    year keep their code."""
    r = _raw_time(v)
    if r is None:
        return None
    year, month, day, prec, julian = r
    if prec >= 11 and month and day and not (julian and year < -4700):
        if julian:
            year, month, day = _julian_to_gregorian(year, month, day)
        return year, month, day, 11
    if prec >= 10 and month and not julian:
        return year, month, 0, 10
    return year, 0, 0, min(prec, 9)


def format_time(parts: tuple[int, int, int, int]) -> str:
    """ISO 8601 / EDTF text of (year, month, day, precision), cut to the precision."""
    year, month, day, prec = parts
    text = f"{year:04d}" if year >= 0 else f"-{-year:04d}"
    if prec >= 10:
        text += f"-{month:02d}"
    if prec >= 11:
        text += f"-{day:02d}"
    return text


def wd_time(v: dict) -> tuple[str, int] | None:
    """ISO 8601 / EDTF text of a Wikidata time value and the precision of that text."""
    parts = wd_time_parts(v)
    return None if parts is None else (format_time(parts), parts[3])


def _jdn(year: int, month: int, day: int) -> int:
    """Julian Day Number of a proleptic Gregorian date (astronomical year)."""
    a = (14 - month) // 12
    y, m = year + 4800 - a, month + 12 * a - 3
    return day + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045


def _jdn_julian(year: int, month: int, day: int) -> int:
    """Julian Day Number of a Julian-calendar date (astronomical year)."""
    a = (14 - month) // 12
    y, m = year + 4800 - a, month + 12 * a - 3
    return day + (153 * m + 2) // 5 + 365 * y + y // 4 - 32083


def _year_span(year: int, prec: int) -> tuple[int, int] | None:
    """First and last astronomical year a year of this precision covers. Decades run 1960-1969 and, before
    the common era, count down the way their names do (the 1000s BCE are 1009-1000 BCE; the decades next to
    the missing year zero are 9-1 BCE and 1-9 CE); centuries and millennia count as Wikidata does (1900 at
    century precision is 1801-1900)."""
    if prec >= 9:
        return year, year
    if prec == 8:
        if year > 0:
            return max(year // 10 * 10, 1), year // 10 * 10 + 9
        d = (1 - year) // 10 * 10                  # the decade in historical BCE years
        return 1 - (d + 9), 1 - max(d, 1)
    if prec in (6, 7):
        size = 100 if prec == 7 else 1000
        if year > 0:
            n = (year + size - 1) // size
            return (n - 1) * size + 1, n * size
        n = (1 - year + size - 1) // size          # counted in historical BCE years
        return 1 - n * size, -(n - 1) * size
    return None


def day_bounds(parts: tuple[int, int, int, int], julian: bool = False) -> tuple[int | None, int | None]:
    """(first, last) Julian Day Number of the interval a time value of its precision covers, counted in the
    calendar it was stated in (a Julian year begins about ten days after the Gregorian year of its number)."""
    year, month, day, prec = parts
    jdn = _jdn_julian if julian else _jdn
    if prec >= 10 and year < -4700:
        return None, None
    if prec >= 11:
        return jdn(year, month, day), jdn(year, month, day)
    if prec == 10:
        nxt = (year + 1, 1) if month == 12 else (year, month + 1)
        return jdn(year, month, 1), jdn(*nxt, 1) - 1
    span = _year_span(year, prec)
    if span is None or span[0] < -4700:
        return None, None
    return jdn(span[0], 1, 1), jdn(span[1] + 1, 1, 1) - 1


def time_bounds(v: dict) -> tuple[int | None, int | None]:
    """Day bounds of a Wikidata time value exactly as stated: at its precision, in its own calendar (so a
    Julian month keeps its exact days even though its text is cut to the year)."""
    r = _raw_time(v)
    if r is None:
        return None, None
    year, month, day, prec, julian = r
    if prec >= 11 and not (month and day):
        prec = 10 if month else 9
    if prec == 10 and not month:
        prec = 9
    return day_bounds((year, month, day, min(prec, 11)), julian=julian)


def snak_parts(s: dict) -> tuple[str, str | None, str | None, str | None]:
    """(snak type, object id, literal value, datatype) of one snak. Things become scoped ids; strings are
    kept exactly; structured values (time, quantity, monolingual text, coordinates) as canonical JSON."""
    kind, dt = s["snaktype"], s.get("datatype")
    if kind != "value":
        return kind, None, None, dt
    dv = s["datavalue"]
    if dv["type"] == "wikibase-entityid":
        return kind, f"wd/{_entity_id(dv['value'])}", None, dt
    if dv["type"] == "string":
        return kind, None, dv["value"], dt
    return kind, None, json.dumps(dv["value"], ensure_ascii=False, sort_keys=True, separators=(",", ":")), dt


def validity(qualifiers: dict) -> tuple[str | None, str | None, int | None, int | None, int | None]:
    """World time of a statement from its start time (P580), end time (P582) or point in time (P585)
    qualifiers, only when each is a single known value; everything else stays in claim_qualifier.
    Returns (from text, to text, coarsest precision, first day, last day) with Julian Day Numbers."""
    def one(pid: str):
        snaks = qualifiers.get(pid, [])
        if len(snaks) != 1 or snaks[0]["snaktype"] != "value" or snaks[0]["datavalue"]["type"] != "time":
            return None
        v = snaks[0]["datavalue"]["value"]
        parts = wd_time_parts(v)
        return None if parts is None else (parts, time_bounds(v))
    start, end, point = one("P580"), one("P582"), one("P585")
    if point and not (start or end):
        start = end = point
    precisions = [p[0][3] for p in (start, end) if p]
    return (format_time(start[0]) if start else None, format_time(end[0]) if end else None,
            min(precisions) if precisions else None,
            start[1][0] if start else None, end[1][1] if end else None)


def _pointer(*parts: str | int) -> str:
    """RFC 6901 JSON Pointer."""
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def import_statements(conn: sqlite3.Connection, corpus: CorpusFile, actor: str = "acat build") -> dict:
    """Every statement of the fetched entities, one claim each: statement id, rank, snak type, the
    entity revision it was read from and a JSON Pointer to it in the stored bytes; qualifiers and
    references as rows. Claims read earlier for the same entities (WDQS summaries, older statement
    corpora) are superseded, never deleted."""
    _ensure_scheme(conn)
    stats = {"entities": 0, "missing": 0, "claims": 0, "new": 0, "qualifiers": 0, "references": 0,
             "labelled": 0, "with_time": 0, "retimed": 0}
    retimed: list[dict] = []                   # derived world-time read anew from the same bytes
    for it in corpus.items():                   # display labels for the items and properties claims name
        if not it["name"].startswith("labels/"):
            continue
        digest = _register_source(conn, corpus, it["name"])
        data = json.loads(corpus.get(it["name"]))
        found: dict[str, dict[str, str]] = {}
        if it["name"].startswith("labels/sparql-"):     # query service rows: one per entity and language
            for b in data["results"]["bindings"]:
                found.setdefault(b["e"]["value"].rsplit("/", 1)[-1], {})[b["l"].get("xml:lang", "")] = b["l"]["value"]
        else:                                           # wbgetentities batches
            for eid, ent in data.get("entities", {}).items():
                if "missing" not in ent:
                    found[eid] = {lang: v["value"] for lang, v in ent.get("labels", {}).items()}
        for eid, labels in found.items():
            text = labels.get("en") or labels.get("mul")
            if text:
                cur = conn.execute("INSERT INTO concept(id, scheme, code, label, source_sha512) VALUES (?,?,?,?,?)"
                                   " ON CONFLICT(id) DO NOTHING", (f"wd/{eid}", "wd", eid, nfc(text), digest))
                stats["labelled"] += cur.rowcount
    covered: set[tuple[str, str]] = set()      # (entity, retrieval time of a batch that holds it)
    for it in corpus.items():
        if not it["name"].startswith("entities/"):
            continue
        digest = _register_source(conn, corpus, it["name"])
        recorded = it["retrieved_at"]
        for qid, ent in json.loads(corpus.get(it["name"])).get("entities", {}).items():
            if "missing" in ent:
                stats["missing"] += 1
                continue
            stats["entities"] += 1
            covered.add((f"wd/{qid}", recorded))
            for pid, statements in ent.get("claims", {}).items():
                for i, st in enumerate(statements):
                    kind, obj, value, dt = snak_parts(st["mainsnak"])
                    valid_from, valid_to, precision, from_day, to_day = validity(st.get("qualifiers", {}))
                    cur = conn.execute(
                        "INSERT OR IGNORE INTO claim(subject, predicate, snak_type, object, value, datatype, rank,"
                        " statement_id, source_revision, source_pointer, epistemic, valid_from, valid_to,"
                        " time_precision, valid_from_day, valid_to_day, source_sha512, recorded_at)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (f"wd/{qid}", f"wd/{pid}", kind, obj, value, dt, st.get("rank"), st["id"],
                         ent.get("lastrevid"), _pointer("entities", qid, "claims", pid, i), "epistemic/attributed",
                         valid_from, valid_to, precision, from_day, to_day, digest, recorded))
                    stats["claims"] += 1
                    if not cur.rowcount:                         # already imported from these bytes
                        # the world-time columns are this code's reading of the qualifiers; when the
                        # reading has been corrected, the stored claim follows it (old values ledgered)
                        row = conn.execute(
                            "SELECT id, valid_from, valid_to, time_precision, valid_from_day, valid_to_day FROM claim"
                            " WHERE statement_id = ? AND source_sha512 = ?", (st["id"], digest)).fetchone()
                        now_read = (valid_from, valid_to, precision, from_day, to_day)
                        if row is not None and tuple(row[1:]) != now_read:
                            conn.execute("UPDATE claim SET valid_from = ?, valid_to = ?, time_precision = ?,"
                                         " valid_from_day = ?, valid_to_day = ? WHERE id = ?", (*now_read, row[0]))
                            stats["retimed"] += 1
                            retimed.append({"claim": row[0], "statement": st["id"], "was": list(row[1:]),
                                            "now": list(now_read)})
                        continue
                    stats["new"] += 1
                    stats["with_time"] += valid_from is not None or valid_to is not None
                    claim_id = cur.lastrowid
                    rows = [(claim_id, n, f"wd/{s['property']}", *snak_parts(s)) for n, s in enumerate(
                        s for p in st.get("qualifiers-order", st.get("qualifiers", {}))
                        for s in st.get("qualifiers", {}).get(p, []))]
                    conn.executemany("INSERT OR IGNORE INTO claim_qualifier(claim_id, ord, property, snak_type,"
                                     " object, value, datatype) VALUES (?,?,?,?,?,?,?)", rows)
                    stats["qualifiers"] += len(rows)
                    for ref in st.get("references", []):
                        rows = [(claim_id, ref["hash"], n, f"wd/{s['property']}", *snak_parts(s)) for n, s in
                                enumerate(s for p in ref.get("snaks-order", ref.get("snaks", {}))
                                          for s in ref["snaks"].get(p, []))]
                        conn.executemany("INSERT OR IGNORE INTO claim_reference(claim_id, ref_hash, ord, property,"
                                         " snak_type, object, value, datatype) VALUES (?,?,?,?,?,?,?,?)", rows)
                        stats["references"] += 1
    # record time moves on for the covered entities, each as of the batch that read it: their WDQS
    # summaries recorded no later than that reading, and any older statement corpus, are superseded then
    conn.execute("DROP TABLE IF EXISTS temp._covered")
    conn.execute("CREATE TEMP TABLE _covered(id TEXT NOT NULL, at TEXT NOT NULL, PRIMARY KEY (id, at))")
    conn.executemany("INSERT INTO _covered(id, at) VALUES (?, ?)", sorted(covered))
    stats["superseded_summaries"] = conn.execute(
        "UPDATE claim SET superseded_at = (SELECT min(c.at) FROM _covered c WHERE c.id = claim.subject"
        " AND c.at >= claim.recorded_at) WHERE superseded_at IS NULL AND statement_id IS NULL"
        " AND EXISTS (SELECT 1 FROM _covered c WHERE c.id = claim.subject AND c.at >= claim.recorded_at)"
        " AND source_sha512 IN (SELECT sha512 FROM source WHERE corpus LIKE 'wikidata-entities-%'"
        " AND name LIKE '%:sparql/claims-%')").rowcount
    # supersessions an earlier reading dated by the corpus's last batch instead of the batch that read
    # the entity: moved to the right time (or undone, when no batch read it after the summary)
    last = corpus_time(corpus, "entities/")
    moved = conn.execute(
        "SELECT id, superseded_at, (SELECT min(c.at) FROM _covered c WHERE c.id = claim.subject"
        " AND c.at >= claim.recorded_at) FROM claim WHERE superseded_at = ? AND statement_id IS NULL"
        " AND subject IN (SELECT id FROM _covered) AND source_sha512 IN (SELECT sha512 FROM source"
        " WHERE corpus LIKE 'wikidata-entities-%' AND name LIKE '%:sparql/claims-%')", (last,)).fetchall()
    moved = [(cid, was, at) for cid, was, at in moved if at != was]
    conn.executemany("UPDATE claim SET superseded_at = ? WHERE id = ?", [(at, cid) for cid, _, at in moved])
    stats["resuperseded"] = len(moved)
    if retimed or moved:
        ledger.record(conn, actor, "retime-claims", target=f"doc/{corpus.name}",
                      detail={"world_time": len(retimed), "record_time": len(moved),
                              "world_time_changes": retimed[:200],
                              "record_time_changes": [{"claim": c, "was": w, "now": a} for c, w, a in moved[:200]]},
                      receipt=f"manifest:{corpus.manifest()}",
                      undo="the previous values are listed here (the first 200 of each); the qualifiers they "
                           "were read from are unchanged in claim_qualifier")
    stats["superseded_statements"] = conn.execute(
        "UPDATE claim SET superseded_at = (SELECT min(c.at) FROM _covered c WHERE c.id = claim.subject)"
        " WHERE superseded_at IS NULL AND subject IN (SELECT id FROM _covered) AND source_sha512 IN"
        " (SELECT sha512 FROM source WHERE corpus LIKE 'wikidata-statements-%' AND corpus < ?)",
        (corpus.name,)).rowcount
    ledger.record(conn, actor, "import-wikidata-statements", target=f"doc/{corpus.name}", detail=stats,
                  receipt=f"manifest:{corpus.manifest()}",
                  undo="claims are never deleted; superseded rows keep their text and source, and a later "
                       "corpus supersedes these in turn")
    return stats
