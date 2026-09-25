"""World Bank World Development Indicators: population and land area per country, the reference
distributions the bias audit compares regional coverage against (CC BY 4.0).

A baseline is a declared choice, not a target: population says "as many as people live there",
land area "as much as the ground covers", and the audit also compares against equal shares.
"""
from __future__ import annotations

import json
import sqlite3

from .. import ledger
from ..corpusfile import CorpusFile, corpus_path
from ..fetch import Fetcher
from ..util import today_compact, utcnow

LICENSE = "CC BY 4.0 (World Bank)"
ATTRIBUTION = "World Bank, World Development Indicators"
API = "https://api.worldbank.org/v2"
# indicator -> (baseline dimension, unit, reference year): the latest year with near-complete coverage
INDICATORS = {"SP.POP.TOTL": ("population", "persons", "2024"), "AG.LND.TOTL.K2": ("land_area", "km2", "2023")}


def worldbank_check(raw: bytes) -> tuple[str, float | None, str | None]:
    """The API answers errors with HTTP 200 and a one-element list carrying 'message'."""
    try:
        data = json.loads(raw)
    except ValueError:
        return "fail", None, "response is not JSON"
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        return "fail", None, "unexpected response shape"
    if "message" in data[0]:
        return "fail", None, f"API error: {data[0]['message']}"
    if len(data) != 2 or not isinstance(data[1], list) or data[0].get("pages") != 1:
        return "fail", None, "response is not a single complete page"
    return "ok", None, None


def fetch(name: str | None = None) -> CorpusFile:
    name = name or f"worldbank-wdi-{today_compact()}"
    corpus = CorpusFile(corpus_path(name), create=True, name=name,
                        title="World Bank WDI: population and land area per economy (audit baselines)",
                        license=LICENSE,
                        description="The economies list (to tell countries from aggregates) and one indicator "
                                    "per item for its reference year, exact bytes.")
    f = Fetcher(corpus, min_interval=1.0)
    f.fetch("countries.json", f"{API}/country?format=json&per_page=500", license=LICENSE,
            attribution=ATTRIBUTION, check=worldbank_check)
    for indicator, (_, _, year) in INDICATORS.items():
        f.fetch(f"{indicator}/{year}.json", f"{API}/country/all/indicator/{indicator}?date={year}&format=json"
                f"&per_page=500", license=LICENSE, attribution=ATTRIBUTION, check=worldbank_check)
    corpus.seal()
    return corpus


def _register(conn: sqlite3.Connection, corpus: CorpusFile, item_name: str) -> str:
    it = corpus.item(item_name)
    conn.execute(
        "INSERT INTO source(sha512, bytes, kind, name, corpus, uri, retrieved_at, content_type, license,"
        " attribution, first_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(sha512) DO NOTHING",
        (it["sha512"], it["bytes"], "fetch", f"{corpus.name}:{item_name}", corpus.name, it["url"],
         it["retrieved_at"], it["content_type"], LICENSE, ATTRIBUTION, utcnow()))
    return it["sha512"]


def import_baselines(conn: sqlite3.Connection, corpus: CorpusFile, actor: str = "acat build") -> dict:
    """One baseline row per UN M49 country or area whose ISO 3166 alpha-3 code the World Bank reports.
    Economies the M49 table does not list, and M49 areas the World Bank does not cover, are reported."""
    by_iso3 = {n: cid for cid, n in conn.execute(
        "SELECT id, notation FROM concept WHERE scheme = 'space' AND status = 'active'"
        " AND notation GLOB '[A-Z][A-Z][A-Z]'")}
    economies = {c["id"]: c for c in json.loads(corpus.get("countries.json"))[1]}
    aggregates = {iso for iso, c in economies.items() if c.get("region", {}).get("id") == "NA"}
    report: dict = {"rows": 0, "not_in_m49": [], "no_value": {}}
    for indicator, (dimension, unit, year) in INDICATORS.items():
        item = f"{indicator}/{year}.json"
        if not corpus.has(item):
            continue
        digest = _register(conn, corpus, item)
        seen = set()
        for r in json.loads(corpus.get(item))[1]:
            iso = r.get("countryiso3code") or ""
            if iso in aggregates or not iso:
                continue
            if iso not in by_iso3:
                if dimension == "population" and r["value"] is not None:
                    report["not_in_m49"].append(f"{iso} {r['country']['value']}")
                continue
            if r["value"] is None:
                continue
            seen.add(iso)
            conn.execute("INSERT OR REPLACE INTO baseline(dimension, group_id, value, unit, as_of, source_sha512)"
                         " VALUES (?,?,?,?,?,?)", (dimension, by_iso3[iso], float(r["value"]), unit, year, digest))
            report["rows"] += 1
        report["no_value"][dimension] = sorted(by_iso3[i].split("-")[-1] + " " + i for i in by_iso3 if i not in seen)
    report["not_in_m49"].sort()
    ledger.record(conn, actor, "import-baselines", target=f"doc/{corpus.name}",
                  detail={"rows": report["rows"], "not_in_m49": len(report["not_in_m49"]),
                          "no_value": {k: len(v) for k, v in report["no_value"].items()}},
                  receipt=f"manifest:{corpus.manifest()}",
                  undo="baselines are regenerated from the corpus on every build")
    return report
