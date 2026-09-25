"""Converters for sources with formats of their own. Each reads the publisher's files as published.

  geonames      GeoNames gazetteer dump: places (allCountries, citiesNNNN or a country file), their names in
                every language (alternateNamesV2, with preferred/short/colloquial/historic flags and dates),
                the administrative hierarchy, countries and first-level divisions, GeoNames' own links to
                Wikidata and Wikipedia
  iso639-3      ISO 639-3 code tables (SIL): languages, macrolanguage membership, names, retirements
  ncbi-taxdump  NCBI Taxonomy (taxdump.tar.gz): taxa, ranks, the tree, scientific and common names
  cldr-names    Unicode CLDR JSON: names of languages, territories and scripts in every locale, the
                territory containment tree, and territory facts (population, languages spoken, shares)
  periodo       PeriodO: periods as defined by named scholarly authorities, with their spatial and
                temporal extents; each authority's periodization stays its own
  mesh-xml      MeSH descriptors (NLM XML): tree numbers as hierarchy, concepts' terms by relation, notes
  wikidata-json a Wikidata JSON dump, streamed and filtered (by id list, by class, by sitelinks)
"""
from __future__ import annotations

import io
import json
import re
import xml.etree.ElementTree as ET

from . import Input, members, text_lines

# ─── GeoNames ───────────────────────────────────────────────────────────────

GN = "https://sws.geonames.org/{code}/"
GN_CLASSES = {"A": "country, state, region", "H": "stream, lake", "L": "parks, area", "P": "city, village",
              "R": "road, railroad", "S": "spot, building, farm", "T": "mountain, hill, rock", "U": "undersea",
              "V": "forest, heath"}
GN_COLUMNS = ("geonameid", "name", "asciiname", "alternatenames", "latitude", "longitude", "feature_class",
              "feature_code", "country_code", "cc2", "admin1_code", "admin2_code", "admin3_code", "admin4_code",
              "population", "elevation", "dem", "timezone", "modification_date")
GN_SPECIAL = {"post": "postal_code", "iata": "iata", "icao": "icao", "faac": "faac", "abbr": "abbreviation",
              "unlc": "un_locode", "phon": "pronunciation", "piny": "pinyin", "tcid": "tcid", "fr_1793": "fr_1793"}


def _tsv(stream, encoding="utf-8"):
    for line in text_lines(stream, encoding):
        if line.startswith("#") or not line.strip():
            continue
        yield line.rstrip("\r\n").split("\t")


def geonames(inputs: list[Input], w, options: dict, progress=print) -> None:
    w.meta["iri_template"] = GN
    kinds = {c: w.kind(f"{c}: {d}", f"http://www.geonames.org/ontology#{c}", "kind/place") for c, d in GN_CLASSES.items()}
    kinds[""] = w.kind("feature", None, "kind/place")
    P = {c: w.pred(c, "attr", f"http://www.geonames.org/ontology#{c}",
                   "real" if c in ("latitude", "longitude") else "int" if c in ("population", "elevation", "dem") else None)
         for c in ("latitude", "longitude", "feature_code", "country_code", "admin1_code", "admin2_code",
                   "population", "elevation", "dem", "timezone", "modification_date")}
    parent = w.pred("parentFeature", "broader", "http://www.geonames.org/ontology#parentFeature")
    wikidata = w.pred("wikidata", "link", "http://www.wikidata.org/entity/", map="exactMatch")
    wikipedia = w.pred("wikipediaArticle", "link", "http://www.geonames.org/ontology#wikipediaArticle")
    historic = w.pred("historic_name", "attr")
    specials = {k: w.pred(v, "attr") for k, v in GN_SPECIAL.items()}
    admin1: dict[str, str] = {}                       # 'TR.34' -> geonameid
    country: dict[str, str] = {}                      # 'TR' -> geonameid

    def files(pattern):
        for inp in inputs:
            for name, stream in members(inp, pattern):
                yield name, stream

    # countries and first-level divisions first: the places hang under them
    for name, stream in files(options.get("countries", "countryInfo.txt")):
        info = w.pred("country_info", "attr")
        for row in _tsv(stream):
            if len(row) >= 17 and row[16].strip():
                gid = row[16].strip()
                country[row[0]] = gid
                w.term(gid, kind=kinds["A"])
                w.label(gid, row[4], "en", "pref")
                w.attr(gid, P["country_code"], row[0])
                w.attr(gid, info, json.dumps({"iso3": row[1], "iso_numeric": row[2], "capital": row[5],
                                              "area_km2": row[6], "population": row[7], "continent": row[8],
                                              "currency": row[10], "languages": row[15], "neighbours": row[17]
                                              if len(row) > 17 else ""}, ensure_ascii=False, sort_keys=True))
    for name, stream in files(options.get("admin1", "admin1CodesASCII.txt")):
        for row in _tsv(stream):
            if len(row) >= 4:
                gid = row[3].strip()
                admin1[row[0]] = gid
                w.term(gid, kind=kinds["A"])
                w.label(gid, row[1], "", "pref")
                cc = row[0].split(".")[0]
                if cc in country:
                    w.rel(gid, parent, country[cc])
    n = 0
    for name, stream in files(options.get("places", "cities15000.txt")):
        for row in _tsv(stream):
            if len(row) < 19:
                continue
            r = dict(zip(GN_COLUMNS, row))
            gid = r["geonameid"]
            w.term(gid, kind=kinds.get(r["feature_class"], kinds[""]))
            w.label(gid, r["name"], "", "pref")         # the local name as GeoNames writes it, no language stated
            if r["asciiname"] != r["name"]:
                w.label(gid, r["asciiname"], "", "hidden")
            for c in ("latitude", "longitude", "population", "elevation", "dem"):
                if r[c] not in ("", None):
                    try:
                        w.attr(gid, P[c], float(r[c]) if c in ("latitude", "longitude") else int(r[c]))
                    except ValueError:
                        w.attr(gid, P[c], r[c])
            for c in ("feature_code", "country_code", "admin1_code", "admin2_code", "timezone", "modification_date"):
                if r[c]:
                    w.attr(gid, P[c], f"{r['feature_class']}.{r[c]}" if c == "feature_code" else r[c])
            up = admin1.get(f"{r['country_code']}.{r['admin1_code']}") if r["admin1_code"] else None
            if r["feature_code"] not in ("ADM1", "PCLI", "PCLD", "PCLF", "PCLS", "PCLIX", "PCL") and (up or r["country_code"] in country):
                w.rel(gid, parent, up or country[r["country_code"]])
            n += 1
            if n % 1_000_000 == 0:
                progress(f"    {n:,} places")
    progress(f"    {n:,} places, {len(country)} countries, {len(admin1)} first-level divisions")
    for name, stream in files(options.get("hierarchy", "hierarchy.txt")):
        kinds_rel = {}
        for row in _tsv(stream):
            if len(row) >= 2 and w.has(row[1]):
                typ = row[2] if len(row) > 2 and row[2] else "ADM"
                if typ == "ADM":
                    w.rel(row[1], parent, row[0])
                else:
                    if typ not in kinds_rel:
                        kinds_rel[typ] = w.pred(f"parent:{typ}", "relation")
                    w.rel(row[1], kinds_rel[typ], row[0])
    names = 0
    for name, stream in files(options.get("names", "alternateNamesV2.txt")):
        for row in _tsv(stream):
            if len(row) < 4 or not w.has(row[1]):
                continue
            gid, lang, text = row[1], row[2], row[3]
            flags = row[4:8] + [""] * (8 - len(row[4:8]))
            preferred, short, colloquial, hist = (f == "1" for f in flags[:4])
            if lang == "wkdt":
                w.link(gid, wikidata, "http://www.wikidata.org/entity/" + text)
            elif lang == "link":
                w.link(gid, wikipedia, text)
            elif lang in specials:
                w.attr(gid, specials[lang], text)
            else:
                w.label(gid, text, lang, "pref" if preferred and not (hist or colloquial) else "alt")
                if hist:
                    w.attr(gid, historic, json.dumps({"name": text, "lang": lang, "from": row[8] if len(row) > 8 else "",
                                                      "to": row[9] if len(row) > 9 else ""}, ensure_ascii=False,
                                                     sort_keys=True))
            names += 1
            if names % 2_000_000 == 0:
                progress(f"    {names:,} names of known places")
    progress(f"    {names:,} names read for the places kept")


# ─── ISO 639-3 ──────────────────────────────────────────────────────────────

ISO_SCOPE = {"I": "individual", "M": "macrolanguage", "S": "special"}
ISO_TYPE = {"A": "ancient", "C": "constructed", "E": "extinct", "H": "historical", "L": "living", "S": "special"}


def iso639_3(inputs: list[Input], w, options: dict, progress=print) -> None:
    w.meta["iri_template"] = "https://iso639-3.sil.org/code/{code}"
    kind = w.kind("Language", "http://lexvo.org/ontology#Language", "kind/symbol-system")
    P = {k: w.pred(k, "attr") for k in ("scope", "type", "part1", "part2b", "part2t", "retirement")}
    note = w.pred("comment", "note")
    macro = w.pred("macrolanguage", "broader")
    replaced = w.pred("change_to", "replacedBy")

    def tab(pattern):
        for inp in inputs:
            for name, stream in members(inp, pattern):
                rows = _tsv(stream, "utf-8-sig")
                header = next(rows)
                for row in rows:
                    yield dict(zip(header, row + [""] * (len(header) - len(row))))

    n = 0
    for r in tab("*iso-639-3.tab"):
        code = r["Id"]
        w.term(code, kind=kind)
        w.label(code, r["Ref_Name"], "en", "pref")
        w.attr(code, P["scope"], ISO_SCOPE.get(r["Scope"], r["Scope"]))
        w.attr(code, P["type"], ISO_TYPE.get(r["Language_Type"], r["Language_Type"]))
        for col, key in (("Part1", "part1"), ("Part2b", "part2b"), ("Part2t", "part2t")):
            if r.get(col):
                w.attr(code, P[key], r[col])
        if r.get("Comment"):
            w.attr(code, note, r["Comment"], "en")
        n += 1
    for r in tab("*iso-639-3_Name_Index.tab"):
        for col in ("Print_Name", "Inverted_Name"):
            if r.get(col):
                w.label(r["Id"], r[col], "en", "alt")
    for r in tab("*iso-639-3-macrolanguages.tab"):
        if r.get("I_Status", "A") == "A":
            w.rel(r["I_Id"], macro, r["M_Id"])
    retired = 0
    for r in tab("*iso-639-3_Retirements.tab"):
        code = r["Id"]
        w.term(code, kind=kind, status=1)
        w.label(code, r["Ref_Name"], "en", "pref")
        w.attr(code, P["retirement"], json.dumps({"reason": r.get("Ret_Reason"), "remedy": r.get("Ret_Remedy"),
                                                  "effective": r.get("Effective")}, sort_keys=True))
        if r.get("Change_To"):
            w.attr(code, replaced, r["Change_To"])
        retired += 1
    progress(f"    {n:,} codes, {retired:,} retired")


# ─── NCBI Taxonomy ──────────────────────────────────────────────────────────


def _dmp(stream):
    for line in text_lines(stream):
        line = line.rstrip("\n")
        if line.endswith("\t|"):
            line = line[:-2]
        yield line.split("\t|\t")


def ncbi_taxdump(inputs: list[Input], w, options: dict, progress=print) -> None:
    w.meta["iri_template"] = "https://www.ncbi.nlm.nih.gov/Taxonomy/Browser/wwwtax.cgi?id={code}"
    parent = w.pred("parent", "broader", "http://purl.obolibrary.org/obo/RO_0002350")
    rank = w.pred("rank", "attr")
    division = w.pred("division", "attr")
    authority = w.pred("authority", "attr")
    kinds: dict[str, int] = {}
    divisions = {}
    n = 0
    for inp in inputs:
        for name, stream in members(inp, "*division.dmp"):
            for row in _dmp(stream):
                divisions[row[0]] = row[2]
    for inp in inputs:                                  # taxdump.tar.gz: names.dmp comes before nodes.dmp
        for name, stream in members(inp, "*nodes.dmp"):
            for row in _dmp(stream):
                tid, par, rk = row[0], row[1], row[2]
                if rk not in kinds:
                    kinds[rk] = w.kind(f"taxon ({rk})")
                w.term(tid, kind=kinds[rk])
                w.attr(tid, rank, rk)
                if len(row) > 4 and row[4] in divisions:
                    w.attr(tid, division, divisions[row[4]])
                if par != tid:
                    w.rel(tid, parent, par)
                n += 1
    kind_of = {"scientific name": ("mul", "pref"), "synonym": ("mul", "alt"), "equivalent name": ("mul", "alt"),
               "genbank common name": ("en", "alt"), "common name": ("en", "alt"), "blast name": ("en", "hidden"),
               "acronym": ("en", "hidden"), "includes": ("mul", "narrower"), "in-part": ("mul", "related"),
               "misspelling": ("mul", "hidden"), "genbank synonym": ("mul", "alt"), "type material": None}
    for inp in inputs:
        for name, stream in members(inp, "*names.dmp"):
            for row in _dmp(stream):
                tid, text, cls = row[0], row[1], row[3] if len(row) > 3 else ""
                if cls == "authority":
                    w.attr(tid, authority, text)
                    continue
                how = kind_of.get(cls, ("mul", "hidden"))
                if how:
                    w.label(tid, text, how[0], how[1])
    progress(f"    {n:,} taxa")


# ─── Unicode CLDR ───────────────────────────────────────────────────────────


def cldr_names(inputs: list[Input], w, options: dict, progress=print) -> None:
    """Names of languages, territories and scripts, each named in every CLDR locale."""
    w.meta["iri_template"] = None
    K = {"language": w.kind("Language", "http://lexvo.org/ontology#Language", "kind/symbol-system"),
         "territory": w.kind("Territory", None, "kind/place"),
         "script": w.kind("Script", "http://lexvo.org/ontology#Script", "kind/symbol-system")}
    contains = w.pred("containedIn", "broader", "https://unicode.org/reports/tr35/#Territory_Containment")
    grouping = w.pred("groupingContainedIn", "relation")
    facts = w.pred("territory_info", "attr")
    lang_pop = w.pred("language_population", "attr")

    def code(kind: str, c: str) -> str:
        return f"{kind}.{c}"

    locales, labels = set(), 0
    files = {"languages": "language", "territories": "territory", "scripts": "script"}
    for inp in inputs:
        for name, stream in members(inp, options.get("members", "*.json")):
            base = name.rsplit("/", 1)[-1]
            if base == "territoryContainment.json":
                data = json.load(stream)["supplemental"]["territoryContainment"]
                for parent, v in data.items():
                    grouping_only = "-status-grouping" in parent or "-status-deprecated" in parent
                    p = parent.split("-status-")[0]
                    w.term(code("territory", p), kind=K["territory"])
                    for child in v.get("_contains", []):
                        w.term(code("territory", child), kind=K["territory"])
                        w.rel(code("territory", child), grouping if grouping_only else contains, code("territory", p))
                continue
            if base == "territoryInfo.json":
                for t, info in json.load(stream)["supplemental"]["territoryInfo"].items():
                    c = code("territory", t)
                    w.term(c, kind=K["territory"])
                    langs = info.pop("languagePopulation", {})
                    w.attr(c, facts, json.dumps(info, sort_keys=True))
                    for lg, v in sorted(langs.items()):
                        w.attr(c, lang_pop, json.dumps({"language": lg, **v}, sort_keys=True))
                continue
            stem = base[:-5]
            if stem not in files:
                continue
            doc = json.load(stream)
            for locale, body in doc.get("main", {}).items():
                names = body.get("localeDisplayNames", {}).get(stem, {})
                locales.add(locale)
                for key, text in names.items():
                    c, _, alt = key.partition("-alt-")
                    kind = files[stem]
                    w.term(code(kind, c), kind=K[kind])
                    w.label(code(kind, c), text, locale, "alt" if alt else "pref")
                    labels += 1
    progress(f"    {labels:,} names in {len(locales)} locales")


# ─── PeriodO ────────────────────────────────────────────────────────────────


def periodo(inputs: list[Input], w, options: dict, progress=print) -> None:
    """Every period stays inside the authority that defined it: the same label from two authorities is
    two periods, because they disagree about when and where it was."""
    w.meta["iri_template"] = "http://n2t.net/ark:/99152/{code}"
    Ka, Kp = w.kind("Authority"), w.kind("Period", None, "kind/time-period")
    within = w.pred("definedBy", "broader")
    broader = w.pred("broader", "broader", "http://www.w3.org/2004/02/skos/core#broader")
    spatial = w.pred("spatialCoverage", "link", "http://purl.org/dc/terms/spatial")
    P = {k: w.pred(k, "attr") for k in ("start_label", "stop_label", "start_earliest", "start_latest",
                                         "stop_earliest", "stop_latest", "spatial_description", "language",
                                         "source", "url")}
    note, ed = w.pred("note", "note"), w.pred("editorialNote", "note")
    same = w.pred("sameAs", "link", "http://www.w3.org/2002/07/owl#sameAs", map="exactMatch")
    derived = w.pred("derivedFrom", "relation", "http://www.w3.org/ns/prov#wasDerivedFrom")

    def years(term: str, which: str, v: dict) -> None:
        if not isinstance(v, dict):
            return
        if v.get("label"):
            w.attr(term, P[f"{which}_label"], v["label"])
        inn = v.get("in", {})
        for k, col in (("year", ("earliest", "latest")), ("earliestYear", ("earliest",)), ("latestYear", ("latest",))):
            if inn.get(k) not in (None, ""):
                for c in col:
                    try:
                        w.attr(term, P[f"{which}_{c}"], int(inn[k]))
                    except (TypeError, ValueError):
                        w.attr(term, P[f"{which}_{c}"], str(inn[k]))

    n = 0
    for inp in inputs:
        for name, stream in members(inp, options.get("members", "*")):
            doc = json.load(stream)
            for aid, a in sorted(doc.get("authorities", {}).items()):
                w.term(aid, kind=Ka)
                src = a.get("source", {})
                title = src.get("title") or src.get("citation") or aid
                w.label(aid, title, "en", "pref")
                w.attr(aid, P["source"], json.dumps(src, ensure_ascii=False, sort_keys=True))
                for pid, p in sorted(a.get("periods", {}).items()):
                    w.term(pid, kind=Kp)
                    lang = p.get("languageTag") or ""
                    w.label(pid, p.get("label"), lang, "pref")
                    for lg, labs in (p.get("localizedLabels") or {}).items():
                        for k, text in enumerate(labs):
                            w.label(pid, text, lg, "pref" if k == 0 and lg != lang else "alt")
                    w.rel(pid, within, aid)
                    for b in p.get("broader", []) if isinstance(p.get("broader"), list) else \
                            ([p["broader"]] if p.get("broader") else []):
                        w.rel(pid, broader, b.rsplit("/", 1)[-1] if isinstance(b, str) else b)
                    years(pid, "start", p.get("start"))
                    years(pid, "stop", p.get("stop"))
                    for place in p.get("spatialCoverage", []):
                        if place.get("id"):
                            w.link(pid, spatial, place["id"])
                    if p.get("spatialCoverageDescription"):
                        w.attr(pid, P["spatial_description"], p["spatialCoverageDescription"])
                    for key, pred in (("note", note), ("editorialNote", ed)):
                        if p.get(key):
                            w.attr(pid, pred, p[key], "en")
                    for s in p.get("sameAs", []) if isinstance(p.get("sameAs"), list) else \
                            ([p["sameAs"]] if p.get("sameAs") else []):
                        w.link(pid, same, s)
                    for d in p.get("derivedFrom", []) if isinstance(p.get("derivedFrom"), list) else []:
                        w.rel(pid, derived, d.rsplit("/", 1)[-1])
                    if p.get("url"):
                        w.attr(pid, P["url"], p["url"])
                    n += 1
    progress(f"    {n:,} periods")


# ─── MeSH ───────────────────────────────────────────────────────────────────


def mesh_xml(inputs: list[Input], w, options: dict, progress=print) -> None:
    w.meta["iri_template"] = "http://id.nlm.nih.gov/mesh/{code}"
    kind = w.kind("Descriptor", "http://id.nlm.nih.gov/mesh/vocab#TopicalDescriptor")
    tree = w.pred("treeNumber", "attr", "http://id.nlm.nih.gov/mesh/vocab#treeNumber")
    broader = w.pred("broaderDescriptor", "broader", "http://id.nlm.nih.gov/mesh/vocab#broaderDescriptor")
    scope = w.pred("scopeNote", "note", "http://www.w3.org/2004/02/skos/core#scopeNote")
    annotation = w.pred("annotation", "note")
    history = w.pred("historyNote", "note", "http://www.w3.org/2004/02/skos/core#historyNote")
    see_also = w.pred("seeAlso", "related", "http://id.nlm.nih.gov/mesh/vocab#seeAlso")
    action = w.pred("pharmacologicalAction", "relation", "http://id.nlm.nih.gov/mesh/vocab#pharmacologicalAction")
    by_tree: dict[str, str] = {}
    trees: dict[str, list[str]] = {}
    rel_name = {"NRW": "narrower", "BRD": "broader", "REL": "related"}
    n = 0
    for inp in inputs:
        for name, stream in members(inp, options.get("members", "*.xml")):
            for event, el in ET.iterparse(stream, events=("end",)):
                if el.tag != "DescriptorRecord":
                    continue
                ui = el.findtext("DescriptorUI")
                w.term(ui, kind=kind)
                w.label(ui, el.findtext("DescriptorName/String"), "en", "pref")
                for tn in el.findall("TreeNumberList/TreeNumber"):
                    by_tree[tn.text] = ui
                    trees.setdefault(ui, []).append(tn.text)
                    w.attr(ui, tree, tn.text)
                for c in el.findall("ConceptList/Concept"):
                    preferred = c.get("PreferredConceptYN") == "Y"
                    how = "alt"
                    if not preferred:
                        rel = c.find("ConceptRelationList/ConceptRelation")
                        how = rel_name.get(rel.get("RelationName"), "related") if rel is not None else "related"
                    for t in c.findall("TermList/Term"):
                        text = t.findtext("String")
                        if not (preferred and t.get("RecordPreferredTermYN") == "Y"):
                            w.label(ui, text, "en", how)
                    if preferred and c.findtext("ScopeNote"):
                        w.attr(ui, scope, c.findtext("ScopeNote").strip(), "en")
                for tag, pred in (("Annotation", annotation), ("HistoryNote", history)):
                    if el.findtext(tag):
                        w.attr(ui, pred, el.findtext(tag).strip(), "en")
                for s in el.findall("SeeRelatedList/SeeRelatedDescriptor/DescriptorReferredTo/DescriptorUI"):
                    w.rel(ui, see_also, s.text)
                for s in el.findall("PharmacologicalActionList/PharmacologicalAction/DescriptorReferredTo/DescriptorUI"):
                    w.rel(ui, action, s.text)
                el.clear()
                n += 1
    for ui, tns in trees.items():                     # C04.557 is under C04: the tree is the hierarchy
        for tn in tns:
            if "." in tn and tn.rsplit(".", 1)[0] in by_tree:
                w.rel(ui, broader, by_tree[tn.rsplit(".", 1)[0]])
    progress(f"    {n:,} descriptors")


# ─── Wikidata JSON dump ─────────────────────────────────────────────────────

HIERARCHY = {"P279": "broader", "P131": "broader", "P361": "broader"}


def wikidata_json(inputs: list[Input], w, options: dict, progress=print) -> None:
    """Keep an entity when its id is listed, when it is a direct instance of a listed class, or when it
    has at least `min_sitelinks` Wikipedia/Wikimedia links. Statements: hierarchy properties become
    broader, other items relations, external identifiers links ('P1566:2643743'), the rest attributes."""
    w.meta["iri_template"] = "http://www.wikidata.org/entity/{code}"
    want_ids = set(options.get("ids", []))
    classes = set(options.get("instance_of", []))
    min_links = options.get("min_sitelinks")
    langs = set(options.get("languages", [])) or None
    kind_item = w.kind("Item", "http://wikiba.se/ontology#Item")
    desc = w.pred("description", "note", "http://schema.org/description")
    sitelinks = w.pred("sitelinks", "attr", "http://wikiba.se/ontology#sitelinks", "int")
    preds: dict[str, int] = {}

    def pred(pid: str, role: str) -> int:
        key = f"{pid}#{role}"
        if key not in preds:
            preds[key] = w.pred(pid if role != "link" else f"{pid}:id", role,
                                f"http://www.wikidata.org/prop/direct/{pid}")
        return preds[key]

    seen = kept = 0
    for inp in inputs:
        for name, stream in members(inp, options.get("members", "*")):
            for line in text_lines(stream):
                line = line.strip().rstrip(",")
                if not line.startswith("{"):
                    continue
                seen += 1
                e = json.loads(line)
                claims = e.get("claims", {})
                p31 = {s["mainsnak"].get("datavalue", {}).get("value", {}).get("id")
                       for s in claims.get("P31", []) if s["mainsnak"].get("snaktype") == "value"}
                if not (e["id"] in want_ids or (classes and p31 & classes)
                        or (min_links is not None and len(e.get("sitelinks", {})) >= min_links)):
                    continue
                kept += 1
                q = e["id"]
                w.term(q, kind=kind_item)
                for lg, v in e.get("labels", {}).items():
                    if langs is None or lg in langs:
                        w.label(q, v["value"], lg, "pref")
                for lg, vs in e.get("aliases", {}).items():
                    if langs is None or lg in langs:
                        for v in vs:
                            w.label(q, v["value"], lg, "alt")
                for lg, v in e.get("descriptions", {}).items():
                    if langs is None or lg in langs:
                        w.attr(q, desc, v["value"], lg)
                w.attr(q, sitelinks, len(e.get("sitelinks", {})))
                for pid, statements in claims.items():
                    for s in statements:
                        if s.get("rank") == "deprecated" or s["mainsnak"].get("snaktype") != "value":
                            continue
                        dv = s["mainsnak"]["datavalue"]
                        dt = s["mainsnak"].get("datatype")
                        if dv["type"] == "wikibase-entityid":
                            o = dv["value"].get("id")
                            w.rel(q, pred(pid, HIERARCHY.get(pid, "relation")), o)
                        elif dt == "external-id":
                            w.link(q, pred(pid, "link"), f"{pid}:{dv['value']}")
                        else:
                            w.attr(q, pred(pid, "attr"), dv["value"] if isinstance(dv["value"], str)
                                   else json.dumps(dv["value"], sort_keys=True, ensure_ascii=False))
                if kept % 100_000 == 0:
                    progress(f"    {kept:,} kept of {seen:,}")
    progress(f"    {kept:,} entities kept of {seen:,} read")


CONVERTERS = {"geonames": geonames, "iso639-3": iso639_3, "ncbi-taxdump": ncbi_taxdump, "cldr-names": cldr_names,
              "periodo": periodo, "mesh-xml": mesh_xml, "wikidata-json": wikidata_json}
