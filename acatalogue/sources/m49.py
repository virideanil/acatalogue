"""UN M49 — the *where* facet, from the UN Statistics Division's own table, in the six UN languages."""
from __future__ import annotations

import sqlite3

from .. import ledger
from ..corpusfile import CorpusFile, corpus_path
from ..fetch import Fetcher, contains_check
from ..textkeys import nfc
from ..util import today_compact, utcnow
from .htmltables import tables

URL = "https://unstats.un.org/unsd/methodology/m49/overview/"
ITEM = "m49-overview.html"
LICENSE = "UN Statistics Division public standard (cited, unmodified)"
ATTRIBUTION = "Standard country or area codes for statistical use (M49), United Nations Statistics Division"
TABLE_LANGS = {"downloadTableEN": "en", "downloadTableZH": "zh", "downloadTableRU": "ru",
               "downloadTableFR": "fr", "downloadTableES": "es", "downloadTableAR": "ar"}
HEADER = ["Global Code", "Global Name", "Region Code", "Region Name", "Sub-region Code", "Sub-region Name",
          "Intermediate Region Code", "Intermediate Region Name", "Country or Area", "M49 Code",
          "ISO-alpha2 Code", "ISO-alpha3 Code"]


def fetch(name: str | None = None) -> CorpusFile:
    name = name or f"un-m49-{today_compact()}"
    corpus = CorpusFile(corpus_path(name), create=True, name=name,
                        title="UN M49 standard country or area codes (all six UN languages)",
                        license=LICENSE,
                        description="The UNSD M49 overview page as served, exact bytes.")
    Fetcher(corpus).fetch(ITEM, URL, license=LICENSE, attribution=ATTRIBUTION,
                          check=contains_check(*(t.encode() for t in TABLE_LANGS)))
    corpus.seal()
    return corpus


def parse(html_bytes: bytes) -> dict[str, list[dict[str, str]]]:
    found = tables(html_bytes.decode("utf-8", errors="replace"))
    out: dict[str, list[dict[str, str]]] = {}
    for table_id, lang in TABLE_LANGS.items():
        rows = found.get(table_id)
        if not rows:
            raise ValueError(f"M49 page: table {table_id} not found")
        header = rows[0]
        if header[: len(HEADER)] != HEADER:
            raise ValueError(f"M49 page: unexpected header in {table_id}: {header[:12]}")
        out[lang] = [dict(zip(header, r)) for r in rows[1:] if len(r) >= len(HEADER)]
    return out


def import_into(conn: sqlite3.Connection, corpus: CorpusFile, actor: str = "acat build") -> dict:
    item = corpus.item(ITEM)
    raw = corpus.get(ITEM)
    digest = item["sha512"]
    by_lang = parse(raw)
    conn.execute(
        "INSERT INTO source(sha512, bytes, kind, name, corpus, uri, retrieved_at, content_type, license,"
        " attribution, first_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(sha512) DO NOTHING",
        (digest, item["bytes"], "fetch", f"{corpus.name}:{ITEM}", corpus.name, item["url"], item["retrieved_at"],
         item["content_type"], LICENSE, ATTRIBUTION, utcnow()))

    names: dict[str, dict[str, str]] = {}      # m49 code -> lang -> name
    parent: dict[str, str] = {}
    iso3: dict[str, str] = {}
    levels = [("Global Code", "Global Name"), ("Region Code", "Region Name"),
              ("Sub-region Code", "Sub-region Name"), ("Intermediate Region Code", "Intermediate Region Name")]
    for lang, rows in by_lang.items():
        for r in rows:
            chain = []
            for code_col, name_col in levels:
                code = r.get(code_col, "").strip()
                if code:
                    names.setdefault(code, {})[lang] = r[name_col].strip()
                    chain.append(code)
            area = r["M49 Code"].strip()
            names.setdefault(area, {})[lang] = r["Country or Area"].strip()
            if r.get("ISO-alpha3 Code"):
                iso3[area] = r["ISO-alpha3 Code"].strip()
            chain.append(area)
            for child, par in zip(chain[1:], chain[:-1]):
                parent.setdefault(child, par)

    n = 0
    for code, langs in sorted(names.items()):
        cid = f"space/m49-{code}"
        label = langs.get("en") or next(iter(langs.values()))
        exists = conn.execute("SELECT 1 FROM concept WHERE id = ?", (cid,)).fetchone()
        if exists:
            conn.execute("UPDATE concept SET label=?, notation=?, status='active', source_sha512=? WHERE id=?",
                         (label, iso3.get(code, code), digest, cid))
        else:
            conn.execute("INSERT INTO concept(id, scheme, code, label, notation, source_sha512) VALUES (?,?,?,?,?,?)",
                         (cid, "space", f"m49-{code}", label, iso3.get(code, code), digest))
        n += 1
    # labels and edges from any M49 corpus are regenerated from the newest one
    for table in ("label", "broader"):
        conn.execute(f"DELETE FROM {table} WHERE source_sha512 IN"
                     " (SELECT sha512 FROM source WHERE corpus LIKE 'un-m49-%')")
    for code, langs in names.items():
        for lang, text in langs.items():
            if text:
                conn.execute("INSERT OR IGNORE INTO label(concept_id, lang, kind, text, source_sha512)"
                             " VALUES (?,?,?,?,?)", (f"space/m49-{code}", lang, "pref", nfc(text), digest))
    for child, par in parent.items():
        conn.execute("INSERT OR IGNORE INTO broader(child, parent, source_sha512) VALUES (?,?,?)",
                     (f"space/m49-{child}", f"space/m49-{par}", digest))
    ledger.record(conn, actor, "import-m49", target=f"doc/{corpus.name}",
                  detail={"concepts": n, "languages": sorted(by_lang)},
                  receipt=f"sha512:{digest}",
                  undo="concepts are never deleted; re-import an earlier M49 corpus to restore its labels")
    return {"concepts": n, "languages": sorted(by_lang), "edges": len(parent)}
