"""External classification schemes: the pages their captions were checked against.

The captions of UDC, DDC, LCC and Propædia classes are typed into seed/schemes/*.tsv. This module
stores the publishers' (or Wikipedia's) pages as exact bytes and verifies that every caption
really occurs there, so each external class carries a receipt instead of a memory.
"""
from __future__ import annotations

import html
import json
import re
import sqlite3
import unicodedata

from .. import ledger
from ..corpusfile import CorpusFile, corpus_path
from ..fetch import Fetcher
from ..util import today_compact, utcnow

PAGES = {
    "udc": ("udc-summary-en.html", "https://udcsummary.info/php/index.php?lang=en",
            "UDC Summary, UDC Consortium, CC BY-SA 3.0"),
    "lcc": ("lcc-outline.html", "https://www.loc.gov/aba/cataloging/classification/lcco/",
            "Library of Congress, U.S. Government work"),
    "ddc": ("wikipedia-list-of-dewey-decimal-classes.json",
            "https://en.wikipedia.org/w/api.php?action=parse&page=List_of_Dewey_Decimal_classes&prop=wikitext"
            "&format=json&formatversion=2", "Wikipedia contributors, CC BY-SA 4.0"),
    "propaedia": ("wikipedia-propaedia.json",
                  "https://en.wikipedia.org/w/api.php?action=parse&page=Prop%C3%A6dia&prop=wikitext"
                  "&format=json&formatversion=2", "Wikipedia contributors, CC BY-SA 4.0"),
}


def fetch(name: str | None = None) -> CorpusFile:
    name = name or f"external-schemes-{today_compact()}"
    corpus = CorpusFile(corpus_path(name), create=True, name=name,
                        title="Pages the external scheme captions were checked against",
                        license="mixed; see each item",
                        description="UDC Summary, LC Classification Outline, and Wikipedia pages for DDC and Propædia.")
    f = Fetcher(corpus, min_interval=1.0)
    for scheme, (item, url, lic) in PAGES.items():
        f.fetch(item, url, license=lic, attribution=lic)
    corpus.seal()
    return corpus


def _flat(text: str) -> str:
    t = html.unescape(re.sub(r"<[^>]+>", " ", text))
    t = unicodedata.normalize("NFKC", t).casefold()
    t = t.replace("'''", " ").replace("[[", " ").replace("]]", " ")
    return " ".join(re.sub(r"[^\w.,()&-]+", " ", t).split())


def verify(conn: sqlite3.Connection, corpus: CorpusFile, actor: str = "acat build") -> dict:
    """Every label or alt label of each external class must occur in its scheme's stored page."""
    report = {"checked": 0, "verified": 0, "unverified": []}
    for scheme, (item, url, lic) in PAGES.items():
        it = corpus.item(item)
        raw = corpus.get(item).decode("utf-8", errors="replace")
        if item.endswith(".json"):
            raw = json.loads(raw)["parse"]["wikitext"]
        hay = _flat(raw)
        digest = it["sha512"]
        conn.execute(
            "INSERT INTO source(sha512, bytes, kind, name, corpus, uri, retrieved_at, content_type, license,"
            " attribution, first_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(sha512) DO NOTHING",
            (digest, it["bytes"], "fetch", f"{corpus.name}:{item}", corpus.name, url, it["retrieved_at"],
             it["content_type"], lic, lic, utcnow()))
        rows = conn.execute(
            "SELECT c.id, c.label, group_concat(l.text, '\x1f') FROM concept c"
            " LEFT JOIN label l ON l.concept_id = c.id AND l.lang = 'en'"
            " WHERE c.scheme = ? AND c.code <> ? GROUP BY c.id", (scheme, scheme)).fetchall()
        for cid, label, texts in rows:
            report["checked"] += 1
            candidates = {label, *(texts.split("\x1f") if texts else [])}
            candidates = {re.sub(r"\s*\([A-Z]\)$", "", c) for c in candidates}   # 'History of the Americas (E)'
            if any(_flat(c) in hay for c in candidates if c):
                report["verified"] += 1
                conn.execute("INSERT OR REPLACE INTO attribute(concept_id, key, value, source_sha512) VALUES (?,?,?,?)",
                             (cid, "verified-in", f"src/sha512:{digest}", digest))
            else:
                report["unverified"].append(cid)
    ledger.record(conn, actor, "verify-external-captions", target=f"doc/{corpus.name}",
                  detail={"checked": report["checked"], "verified": report["verified"],
                          "unverified": report["unverified"]},
                  receipt=f"manifest:{corpus.manifest()}", undo="read-only check; nothing to undo")
    return report
