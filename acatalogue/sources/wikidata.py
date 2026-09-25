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
from ..fetch import Fetcher
from ..util import REPO_ROOT, today_compact, utcnow

API = "https://www.wikidata.org/w/api.php"
SPARQL = "https://query.wikidata.org/sparql"
LICENSE = "CC0 1.0 (Wikidata)"
ATTRIBUTION = "Wikidata contributors"
DECISIONS = REPO_ROOT / "seed" / "crosswalk" / "acat-wikidata.tsv"
DECISION_COLUMNS = ["from", "to", "relation", "status", "method", "reviewer", "note"]
LABEL_RELATIONS = {"exactMatch", "closeMatch"}   # only these donate their labels to our concept
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
         "type": "item", "limit": "7", "format": "json"}
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
        raw = f.fetch(f"search/{code}/label", _search_url(label), license=LICENSE, attribution=ATTRIBUTION)
        hits = json.loads(raw).get("search", [])
        if alts and not any(_is_exact(h, label, alts) for h in hits):
            f.fetch(f"search/{code}/alt", _search_url(alts[0]), license=LICENSE, attribution=ATTRIBUTION)
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
                headers={"Accept": "application/sparql-results+json"}, license=LICENSE, attribution=ATTRIBUTION)


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
             "format": "json"}
        f.fetch(f"entities/batch-{n:03d}.json", f"{API}?{urllib.parse.urlencode(q)}",
                license=LICENSE, attribution=ATTRIBUTION)
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
                headers={"Accept": "application/sparql-results+json"}, license=LICENSE, attribution=ATTRIBUTION)


def _register_source(conn: sqlite3.Connection, corpus: CorpusFile, item_name: str) -> str:
    it = corpus.item(item_name)
    conn.execute(
        "INSERT INTO source(sha512, bytes, kind, name, corpus, uri, retrieved_at, content_type, license,"
        " attribution, first_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(sha512) DO NOTHING",
        (it["sha512"], it["bytes"], "fetch", f"{corpus.name}:{item_name}", corpus.name, it["url"],
         it["retrieved_at"], it["content_type"], LICENSE, ATTRIBUTION, utcnow()))
    return it["sha512"]


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
                rows.append((lang, "pref", v["value"]))
            for lang, vs in ent.get("aliases", {}).items():
                rows += [(lang, "alt", v["value"]) for v in vs]
            for lang, v in ent.get("descriptions", {}).items():
                rows.append((lang, "desc", v["value"]))
            # Labels are stored once, on the concept that uses them (exact/close matches only). The wd/
            # item keeps its English name in concept.label; its full label set stays in the corpus bytes.
            stats["labels"] += len(rows)
            for target in [d["from"] for d in by_qid.get(qid, []) if d["relation"] in LABEL_RELATIONS]:
                for lang, kind, text in rows:
                    # our own English preferred label stays ours: Wikidata's English label becomes an alt
                    if lang == "en" and kind == "pref":
                        kind = "alt"
                    conn.execute("INSERT OR IGNORE INTO label(concept_id, lang, kind, text, source_sha512)"
                                 " VALUES (?,?,?,?,?)", (target, lang, kind, text, digest))
                    stats["copied_labels"] += 1
            sitelinks = ent.get("sitelinks", {})
            wikis = [k for k in sitelinks if k.endswith("wiki") and k not in ("commonswiki", "specieswiki",
                                                                                  "metawiki", "mediawikiwiki",
                                                                                  "wikidatawiki", "sourceswiki")]
            conn.execute("INSERT OR REPLACE INTO attribute(concept_id, key, value, source_sha512) VALUES (?,?,?,?)",
                         (f"wd/{qid}", "sitelinks", str(len(wikis)), digest))
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
                 " AND name = 'seed/crosswalk/acat-wikidata.tsv')")
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
             d["note"] or None, seed_sha512))
        n += 1
    return n


def import_claims(conn: sqlite3.Connection, corpus: CorpusFile, actor: str = "acat build") -> dict:
    stats = {"claims": 0, "new": 0}
    now = utcnow()
    for pid, label in CLAIM_PROPERTIES.items():
        conn.execute("INSERT INTO concept(id, scheme, code, label) VALUES (?,?,?,?) ON CONFLICT(id) DO NOTHING",
                     (f"wd/{pid}", "wd", pid, label))
    for it in corpus.items():
        if not it["name"].startswith("sparql/"):
            continue
        digest = _register_source(conn, corpus, it["name"])
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
            cur = conn.execute(
                "INSERT OR IGNORE INTO claim(subject, predicate, object, rank, epistemic, source_sha512, recorded_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (f"wd/{subj}", f"wd/{b['pid']['value']}", f"wd/{obj}", rank,
                 "epistemic/superseded" if rank == "deprecated" else "epistemic/attributed", digest, now))
            stats["claims"] += 1
            stats["new"] += cur.rowcount
    ledger.record(conn, actor, "import-wikidata-claims", target=f"doc/{corpus.name}", detail=stats,
                  receipt=f"manifest:{corpus.manifest()}",
                  undo="claims are never deleted; a later corpus supersedes them")
    return stats
