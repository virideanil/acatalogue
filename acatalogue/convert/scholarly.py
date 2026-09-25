"""Scholarly infrastructure.

  openalex   OpenAlex's research classification from its public snapshot (JSON lines): topics under
             subfields under fields under domains, or the legacy concept hierarchy with names in many
             languages; Wikipedia and Wikidata links kept. Siblings are not stored: they are the
             children of one parent, which the hierarchy already says
  ror        the Research Organization Registry (v2 JSON): organizations with their names in every
             language given, types, parents, places (GeoNames), and identifiers elsewhere (Wikidata,
             ISNI, GRID, Crossref Funder)
"""
from __future__ import annotations

import json

from . import Input, members, text_lines


def _oa_code(url: str) -> str:
    """https://openalex.org/T13676 -> T13676; https://openalex.org/subfields/1710 -> subfields.1710"""
    return url.rstrip("/").split("openalex.org/", 1)[-1].replace("/", ".")


def openalex(inputs: list[Input], w, options: dict, progress=print) -> None:
    w.meta["iri_template"] = "https://openalex.org/{code}"
    kinds = {k: w.kind(k, None, "kind/field") for k in ("domain", "field", "subfield", "topic", "concept")}
    parent = w.pred("parent", "broader")
    desc = w.pred("description", "note", "http://schema.org/description")
    keyword = w.pred("keyword", "attr")
    works = w.pred("works_count", "attr", datatype="int")
    level = w.pred("level", "attr", datatype="int")
    wikidata = w.pred("wikidata", "link", map="exactMatch")
    wikipedia = w.pred("wikipedia", "link")
    related = w.pred("related_concept", "related")
    n = 0
    for inp in inputs:
        for name, stream in members(inp, options.get("members", "*")):
            for line in text_lines(stream):
                if not line.strip():
                    continue
                r = json.loads(line)
                code = _oa_code(r["id"])
                entity = code.split(".")[0] if "." in code else ("topic" if code.startswith("T") else "concept")
                entity = {"domains": "domain", "fields": "field", "subfields": "subfield"}.get(entity, entity)
                iri = r["id"] if "." in code else None
                w.term(code, kind=kinds.get(entity), iri=iri)
                w.label(code, r.get("display_name"), "en", "pref")
                for alt in r.get("display_name_alternatives") or []:
                    w.label(code, alt, "en", "alt")
                for lg, text in ((r.get("international") or {}).get("display_name") or {}).items():
                    w.label(code, text, lg, "pref" if lg != "en" else "alt")
                if r.get("description"):
                    w.attr(code, desc, r["description"], "en")
                for lg, text in ((r.get("international") or {}).get("description") or {}).items():
                    if lg != "en":
                        w.attr(code, desc, text, lg)
                for k in r.get("keywords") or []:
                    w.attr(code, keyword, k, "en")
                if r.get("works_count") is not None:
                    w.attr(code, works, int(r["works_count"]))
                if r.get("level") is not None:
                    w.attr(code, level, int(r["level"]))
                ids = r.get("ids") or {}
                wd = ids.get("wikidata") or r.get("wikidata")
                if wd:
                    w.link(code, wikidata, wd if wd.startswith("http") else f"http://www.wikidata.org/entity/{wd}")
                if ids.get("wikipedia"):
                    w.link(code, wikipedia, ids["wikipedia"])
                up = {"topic": "subfield", "subfield": "field", "field": "domain"}.get(entity)
                if up and isinstance(r.get(up), dict) and r[up].get("id"):
                    w.rel(code, parent, _oa_code(r[up]["id"]))
                for a in r.get("ancestors") or []:          # legacy concepts: a DAG, parents one level up
                    if a.get("level") is not None and r.get("level") is not None and a["level"] == r["level"] - 1:
                        w.rel(code, parent, _oa_code(a["id"]))
                for c in r.get("related_concepts") or []:
                    w.rel(code, related, _oa_code(c["id"]))
                n += 1
    progress(f"    {n:,} records")


def ror(inputs: list[Input], w, options: dict, progress=print) -> None:
    w.meta["iri_template"] = "https://ror.org/{code}"
    kinds: dict[str, int] = {}
    parent = w.pred("parent", "broader")
    related = w.pred("related", "related")
    rel_other = {t: w.pred(t, "relation") for t in ("predecessor", "successor")}
    located = w.pred("location", "link")
    wikidata = w.pred("wikidata", "link", map="exactMatch")
    other_ids = {t: w.pred(t, "link", map="exactMatch") for t in ("isni", "grid", "fundref")}
    P = {k: w.pred(k, "attr") for k in ("type", "status", "established", "website", "domain")}
    n = 0
    for inp in inputs:
        for name, stream in members(inp, options.get("members", "*.json")):
            if name.endswith("_schema_v2.json") or "schema" in name.rsplit("/", 1)[-1]:
                continue
            for org in json.load(stream):
                code = org["id"].rsplit("/", 1)[-1]
                types = org.get("types") or []
                t0 = types[0] if types else "organization"
                if t0 not in kinds:
                    kinds[t0] = w.kind(t0, None, "kind/group")
                w.term(code, kind=kinds[t0], status=0 if org.get("status", "active") == "active" else 1)
                display_done = set()
                for nm in org.get("names") or []:
                    lang = nm.get("lang") or ("en" if "ror_display" in nm.get("types", []) else "")
                    t = nm.get("types") or []
                    if "ror_display" in t or ("label" in t and lang not in display_done):
                        w.label(code, nm["value"], lang, "pref" if lang not in display_done else "alt")
                        display_done.add(lang)
                    elif "acronym" in t:
                        w.label(code, nm["value"], lang, "hidden")
                    else:
                        w.label(code, nm["value"], lang, "alt")
                for t in types:
                    w.attr(code, P["type"], t)
                w.attr(code, P["status"], org.get("status"))
                if org.get("established"):
                    w.attr(code, P["established"], int(org["established"]))
                for ln in org.get("links") or []:
                    if ln.get("type") == "website":
                        w.attr(code, P["website"], ln.get("value"))
                for d in org.get("domains") or []:
                    w.attr(code, P["domain"], d)
                for loc in org.get("locations") or []:
                    if loc.get("geonames_id"):
                        w.link(code, located, f"https://sws.geonames.org/{loc['geonames_id']}/")
                for rel in org.get("relationships") or []:
                    other = rel["id"].rsplit("/", 1)[-1]
                    if rel["type"] == "parent":
                        w.rel(code, parent, other)
                    elif rel["type"] == "related":
                        w.rel(code, related, other)
                    elif rel["type"] in rel_other:
                        w.rel(code, rel_other[rel["type"]], other)
                for x in org.get("external_ids") or []:
                    for v in x.get("all") or []:
                        if x["type"] == "wikidata":
                            w.link(code, wikidata, f"http://www.wikidata.org/entity/{v}")
                        elif x["type"] in other_ids:
                            w.link(code, other_ids[x["type"]], f"{x['type']}:{v}")
                n += 1
    progress(f"    {n:,} organizations")
