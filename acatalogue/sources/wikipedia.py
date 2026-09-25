"""English Wikipedia introductions for reconciled concepts — the first text corpus.

Licence: CC BY-SA 4.0. Every document keeps its page URL and revision id for attribution, and
anything derived from these texts must be shared under the same licence.
"""
from __future__ import annotations

import json
import re
import sqlite3
import urllib.parse

from .. import ledger
from ..corpusfile import CorpusFile, corpus_path
from ..fetch import Fetcher
from ..util import today_compact, utcnow

API = "https://en.wikipedia.org/w/api.php"
LICENSE = "CC BY-SA 4.0"


def fetch_intros(titles: list[str], name: str | None = None) -> CorpusFile:
    name = name or f"wikipedia-en-intros-{today_compact()}"
    corpus = CorpusFile(corpus_path(name), create=True, name=name,
                        title="English Wikipedia introductions of reconciled concepts",
                        license=LICENSE,
                        description="MediaWiki API responses (extracts, plain-text intro), 20 pages per item, exact bytes.")
    f = Fetcher(corpus, min_interval=1.0)
    titles = sorted(set(titles))
    for n, start in enumerate(range(0, len(titles), 20), 1):
        batch = titles[start:start + 20]
        q = {"action": "query", "format": "json", "formatversion": "2", "prop": "extracts|info",
             "exintro": "1", "explaintext": "1", "exlimit": "20", "redirects": "1", "inprop": "url",
             "titles": "|".join(batch)}
        f.fetch(f"intros/batch-{n:03d}.json", f"{API}?{urllib.parse.urlencode(q)}", license=LICENSE,
                attribution="Wikipedia contributors")
    return corpus


def split_passages(text: str) -> list[tuple[int, int, str]]:
    """Paragraphs as (start, end, text) with offsets into the document text."""
    out = []
    for m in re.finditer(r"[^\n]+", text):
        chunk = m.group(0).strip()
        if chunk:
            out.append((m.start(), m.end(), chunk))
    return out


def import_documents(conn: sqlite3.Connection, corpus: CorpusFile, title_to_concepts: dict[str, list[str]],
                     actor: str = "acat build") -> dict:
    """Documents + passages from every batch; links each document to the concepts whose reconciled
    Wikidata item names this page as its English sitelink."""
    stats = {"documents": 0, "passages": 0, "linked": 0, "empty": 0}
    for it in corpus.items():
        digest = it["sha512"]
        conn.execute(
            "INSERT INTO source(sha512, bytes, kind, name, corpus, uri, retrieved_at, content_type, license,"
            " attribution, first_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(sha512) DO NOTHING",
            (digest, it["bytes"], "fetch", f"{corpus.name}:{it['name']}", corpus.name, it["url"],
             it["retrieved_at"], it["content_type"], LICENSE, "Wikipedia contributors", utcnow()))
        data = json.loads(corpus.get(it["name"]))["query"]
        # map requested titles through normalization and redirects to the final page title
        alias: dict[str, str] = {}
        for step in ("normalized", "redirects"):
            for r in data.get(step, []):
                alias[r["to"]] = alias.get(r["from"], r["from"])
        for page in data.get("pages", []):
            text = (page.get("extract") or "").strip()
            if page.get("missing") or not text:
                stats["empty"] += 1
                continue
            title = page["title"]
            name = title.replace(" ", "_")
            doc_id = f"doc/{corpus.name}/{name}"
            attribution = (f"Wikipedia contributors, \"{title}\", English Wikipedia, revision {page.get('lastrevid')}, "
                           f"{LICENSE}")
            conn.execute(
                "INSERT INTO document(id, corpus, name, title, lang, url, license, attribution, source_sha512, text,"
                " n_chars) VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET text=excluded.text,"
                " n_chars=excluded.n_chars, url=excluded.url, attribution=excluded.attribution,"
                " source_sha512=excluded.source_sha512",
                (doc_id, corpus.name, name, title, "en", page.get("fullurl"), LICENSE, attribution, digest, text,
                 len(text)))
            conn.execute("DELETE FROM passage WHERE doc_id = ?", (doc_id,))
            for ord_, (a, b, chunk) in enumerate(split_passages(text)):
                conn.execute("INSERT INTO passage(doc_id, ord, start, end, text) VALUES (?,?,?,?,?)",
                             (doc_id, ord_, a, b, chunk))
                stats["passages"] += 1
            stats["documents"] += 1
            requested = {title, alias.get(title, title)}
            for t in requested:
                for cid in title_to_concepts.get(t, []):
                    conn.execute("INSERT OR IGNORE INTO document_concept(doc_id, concept_id, relation, method)"
                                 " VALUES (?,?,?,?)", (doc_id, cid, "about", "wikidata-enwiki-sitelink"))
                    stats["linked"] += 1
    ledger.record(conn, actor, "import-documents", target=f"doc/{corpus.name}", detail=stats,
                  receipt=f"manifest:{corpus.manifest()}",
                  undo="documents are rebuilt from the corpus; remove the corpus file and rebuild to drop them")
    return stats
