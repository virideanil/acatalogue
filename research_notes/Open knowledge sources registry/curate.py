"""Curate the four research registries into seed/sources/{registry,files,presets}.tsv.

Run from the repository root:  python3 "research_notes/Open knowledge sources registry/curate.py"

The research rows (a-, b-, c-, d-*.tsv beside this file) are what four researchers verified live on
2026-09-25: URLs, sizes, licences, languages, perspectives. This script adds the curation decisions, one
entry per source in DECISIONS: which converter reads it, which catalogue scheme it becomes, how its
identifiers look (IRI and CURIE prefixes, the Wikidata property that holds them, as checked against
the catalogue's own Wikidata statements), full or attach, and a recommendation. Sources that cannot
be downloaded (restricted, blocked, a form) stay in the registry with no files, so the landscape,
including its gaps, stays visible. The reviewer of every entry is named: an AI agent, this session.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
from acatalogue.registry import COLUMNS, FILE_COLUMNS, PRESET_COLUMNS  # noqa: E402

REVIEWER = "claude (AI agent, session 2026-09-25)"
OBO = "http://purl.obolibrary.org/obo/"
SKOS_NS = "http://www.w3.org/2004/02/skos/core#"
GNDO = "https://d-nb.info/standards/elementset/gnd#"
QUDT = "http://qudt.org/schema/qudt/"


def obo_ids(prefix: str) -> dict:
    return {"iri_prefixes": f"{OBO}{prefix}_|{prefix}_{{rest}}", "curie_prefixes": f"{prefix}|{prefix}_{{rest}}"}


def file(url, name=None, bytes_="", checksum="", fmt="", role="") -> dict:
    return {"url": url, "name": name or re.sub(r"[?#].*$", "", url).rstrip("/").rsplit("/", 1)[-1], "bytes": str(bytes_),
            "checksum": checksum, "format": fmt, "role": role}


# id -> decisions. "files" replaces the research row's single URL; "merge" folds other research rows in.
DECISIONS: dict[str, dict] = {
    # ── encyclopedic, lexical, scholarly ──
    "wikidata-json-all": {"converter": "wikidata-json", "scheme": "wikidata-dump", "integrate": "attach",
                          "options": {"min_sitelinks": 100, "members": "*"}, "recommend": "no",
                          "why": "103 GB compressed; the converter streams it and keeps items with 100+ sitelinks"},
    "wikidata-truthy-nt": {"converter": "raw", "recommend": "no"},
    "wikidata-lexemes": {"converter": "raw", "recommend": "later"},
    "wikipedia-cirrus-en": {"converter": "raw", "recommend": "no"},
    "wikipedia-cirrus-tr": {"converter": "raw", "recommend": "no"},
    "wikipedia-cirrus-sw": {"converter": "raw", "recommend": "later"},
    "wikipedia-xml-en": {"converter": "raw", "recommend": "no"},
    "wikipedia-xml-tr": {"converter": "raw", "recommend": "no"},
    "wikipedia-categories-en": {"converter": "rdf", "scheme": "enwiki-categories", "integrate": "attach",
                                "options": {"term_types": ["https://www.mediawiki.org/ontology#Category"],
                                            "broader_predicates": ["https://www.mediawiki.org/ontology#isInCategory"]},
                                "iri_prefixes": "https://en.wikipedia.org/wiki/", "recommend": "later",
                                "why": "editorial, with cycles and maintenance categories: never merged into ACAT"},
    "abstract-wikipedia": {"converter": "raw", "recommend": "no"},
    "wikifunctions": {"converter": "raw", "recommend": "no"},
    "dbpedia-ontology": {"converter": "rdf", "scheme": "dbpedia-ontology", "integrate": "full",
                         "iri_prefixes": "http://dbpedia.org/ontology/", "recommend": "yes",
                         "files": [file("https://databus.dbpedia.org/ontologies/dbpedia.org/ontology/2024.08.01-180007/ontology_type=parsed.nt",
                                        "dbpedia-ontology.nt", 9858392,
                                        "sha256:33408e32640911a0d32575054d1c8d02a6d7725878f56b73758674d3af9e1d05")]},
    "dbpedia-kg-instance-types-en": {"converter": "raw", "recommend": "no"},
    "yago-4.6-taxonomy": {"converter": "rdf", "scheme": "yago", "integrate": "attach", "recommend": "yes",
                          "options": {"term_types": ["http://www.w3.org/2000/01/rdf-schema#Class",
                                                     "http://www.w3.org/2002/07/owl#Class"],
                                      "label_predicates": {"http://schema.org/alternateName": "alt"}},
                          "iri_prefixes": "http://yago-knowledge.org/resource/", "merge": ["yago-4.6-schema"],
                          "files": [file("https://yago-knowledge.org/data/yago4.6/yago-4.6-schema.zip", bytes_=19471),
                                    file("https://yago-knowledge.org/data/yago4.6/yago-4.6-taxonomy.zip", bytes_=41519942)]},
    "yago-4.6-facts": {"converter": "raw", "recommend": "no"},
    "kbpedia": {"converter": "rdf", "scheme": "kbpedia", "integrate": "attach", "recommend": "later",
                "iri_prefixes": "http://kbpedia.org/kko/rc/", "why": "stale since 2020; useful for its disjoint typologies"},
    "conceptnet-5.7": {"converter": "raw", "recommend": "later"},
    "oewn-2025-plus": {"converter": "wn-lmf", "scheme": "wn", "integrate": "full", "recommend": "starter",
                       "iri_prefixes": "http://ili.globalwordnet.org/ili/"},
    "omw-2.0": {"converter": "wn-lmf", "scheme": "wn", "integrate": "attach", "recommend": "yes",
                "title": "Open Multilingual Wordnet 2.0 with the Open English WordNet (joined by the Interlingual Index)",
                "iri_prefixes": "http://ili.globalwordnet.org/ili/",
                "files": [file("https://en-word.net/downloads/english-wordnet-2025-plus.xml.gz", bytes_=12925887),
                          file("https://github.com/omwn/omw-data/releases/download/v2.0/omw-2.0.tar.xz", bytes_=55846636)],
                "why": "31 languages; most were built by translating the English wordnet, so the hierarchy is English-centred"},
    "kaikki-enwiktionary-all": {"converter": "raw", "recommend": "no"},
    "kaikki-en-turkish": {"converter": "raw", "recommend": "later"},
    "kaikki-trwiktionary": {"converter": "raw", "recommend": "later"},
    "dbnary-en": {"converter": "raw", "recommend": "later"},
    "babelnet": {"converter": "raw", "access": "restricted", "files": [], "recommend": "no"},
    "openalex-topics": {"converter": "openalex", "scheme": "openalex", "integrate": "full", "recommend": "starter",
                        "options": {"members": "*.gz"}, "iri_prefixes": "https://openalex.org/",
                        "wikidata_property": "P10283", "merge": ["openalex-subfields", "openalex-fields", "openalex-domains"],
                        "title": "OpenAlex research classification (domains, fields, subfields, topics)",
                        "files": [file(f"https://openalex.s3.amazonaws.com/data/jsonl/{e}/manifest.json", f"{e}-manifest.json",
                                       fmt="manifest:openalex") for e in ("domains", "fields", "subfields", "topics")]},
    "openalex-concepts": {"converter": "openalex", "scheme": "openalex-concepts", "integrate": "attach", "recommend": "yes",
                          "options": {"members": "*.gz", "manifest_rewrite": ["/data/concepts/", "/legacy-data/concepts/"]},
                          "wikidata_property": "P10283|{rest}|^C",
                          "files": [file("https://openalex.s3.amazonaws.com/legacy-data/concepts/manifest",
                                         "concepts-manifest.json", fmt="manifest:openalex")]},
    "crossref-public-data-2026": {"converter": "raw", "recommend": "no", "access": "blocked", "files": [],
                                  "why": "a torrent only (223 GB): no plain HTTPS copy"},
    "schema-org": {"converter": "rdf", "scheme": "schema-org", "integrate": "full", "recommend": "starter",
                   "options": {"default_lang": "en"}, "iri_prefixes": "https://schema.org/ http://schema.org/"},
    "ror": {"converter": "ror", "scheme": "ror", "integrate": "attach", "recommend": "yes",
            "iri_prefixes": "https://ror.org/", "wikidata_property": "P6782",
            "files": [file("https://zenodo.org/records/22902037/files/v2.13-2026-09-22-ror-data.zip?download=1",
                           "ror-data.zip", 37540961, "md5:a935217de21e7983b977f5419f1a6b20")]},
    "physh": {"converter": "rdf", "scheme": "physh", "integrate": "full", "recommend": "starter",
              "iri_prefixes": "https://doi.org/10.29172/"},
    # ── libraries, classifications, thesauri ──
    "lcsh": {"converter": "rdf", "scheme": "lcsh", "integrate": "attach", "recommend": "yes",
             "iri_prefixes": "http://id.loc.gov/authorities/subjects/", "wikidata_property": "P244|{rest}|^sh",
             "why": "the LC checksum files hash the decompressed .nt, so none is pinned here"},
    "lcc-mdsconnect": {"converter": "raw", "recommend": "no"},
    "lcgft": {"converter": "rdf", "scheme": "lcgft", "integrate": "full", "recommend": "starter",
              "iri_prefixes": "http://id.loc.gov/authorities/genreForms/", "wikidata_property": "P244|{rest}|^gf"},
    "lc-childrens-subjects": {"converter": "rdf", "scheme": "lc-childrens", "integrate": "full", "recommend": "later",
                              "iri_prefixes": "http://id.loc.gov/authorities/childrensSubjects/"},
    "fast-topical": {"converter": "rdf", "access": "blocked", "files": [], "recommend": "no",
                     "why": "Cloudflare refuses scripted downloads (403)"},
    "gnd-subjects": {"converter": "rdf", "scheme": "gnd", "integrate": "attach", "recommend": "yes",
                     "options": {"term_if_predicate": [GNDO + "preferredNameForTheSubjectHeading"],
                                 "label_predicates": {GNDO + "preferredNameForTheSubjectHeading": "pref",
                                                      GNDO + "variantNameForTheSubjectHeading": "alt"},
                                 "broader_predicates": [GNDO + s for s in ("broaderTermGeneral", "broaderTermGeneric",
                                                                           "broaderTermPartitive", "broaderTermInstantial")],
                                 "related_predicates": [GNDO + "relatedTerm"], "note_predicates": [GNDO + "definition"],
                                 "default_lang": "de"},
                     "iri_prefixes": "https://d-nb.info/gnd/", "wikidata_property": "P227"},
    "rameau": {"converter": "rdf", "access": "form", "files": [], "recommend": "later",
               "why": "downloadable only through a form on the BnF file share"},
    "ndlsh": {"converter": "rdf", "scheme": "ndlsh", "integrate": "full", "recommend": "starter",
              "options": {"members": "*.rdf"},
              "iri_prefixes": "http://id.ndl.go.jp/auth/ndlsh/ https://id.ndl.go.jp/auth/ndlsh/",
              "wikidata_property": "P349"},
    "ndc9-jla": {"converter": "rdf", "scheme": "ndc9", "integrate": "full", "recommend": "starter",
                 "options": {"members": "*.ttl"}, "iri_prefixes": "http://jla.or.jp/data/ndc9#"},
    "yso": {"converter": "rdf", "scheme": "yso", "integrate": "full", "recommend": "yes",
            "options": {"lang_aliases": {"sme": "se"}}, "iri_prefixes": "http://www.yso.fi/onto/yso/",
            "wikidata_property": "P2347|p{rest}"},
    "koko": {"converter": "rdf", "scheme": "koko", "integrate": "attach", "recommend": "later",
             "iri_prefixes": "http://www.yso.fi/onto/koko/"},
    "udc-summary": {"converter": "raw", "access": "restricted", "files": [], "recommend": "no",
                    "why": "CC BY-NC 4.0 from 2026 and its linked data is offline; the catalogue's ten UDC main-class "
                           "captions predate this and need the owner's check"},
    "ddc-oclc": {"converter": "raw", "access": "restricted", "files": [], "recommend": "no",
                 "why": "OCLC's terms forbid storing material amounts; the ten DDC captions in seed/ need the owner's check"},
    "iconclass": {"converter": "raw", "recommend": "later"},
    "getty-aat-explicit": {"converter": "rdf", "scheme": "aat", "integrate": "attach", "recommend": "later",
                           "options": {"broader_predicates": ["http://vocab.getty.edu/ontology#broaderPreferred"],
                                       "members": "*.nt"},
                           "iri_prefixes": "http://vocab.getty.edu/aat/", "wikidata_property": "P1014",
                           "why": "the explicit export materializes no skos:broader: the converter reads gvp:broaderPreferred"},
    "getty-tgn-explicit": {"converter": "raw", "recommend": "no"},
    "getty-ulan-explicit": {"converter": "raw", "recommend": "no"},
    "unesco-thesaurus": {"converter": "rdf", "scheme": "unesco", "integrate": "full", "recommend": "starter",
                         "iri_prefixes": "http://vocabularies.unesco.org/thesaurus/", "wikidata_property": "P3916"},
    "un-thesaurus": {"converter": "rdf", "scheme": "unbist", "integrate": "full", "recommend": "no",
                     "why": "non-commercial terms"},
    "eurovoc": {"converter": "rdf", "scheme": "eurovoc", "integrate": "full", "recommend": "yes",
                "options": {"members": "*.rdf"}, "iri_prefixes": "http://eurovoc.europa.eu/", "wikidata_property": "P5437",
                "files": [file("https://op.europa.eu/o/opportal-service/euvoc-download-handler?cellarURI=http%3A%2F%2Fpublications.europa.eu%2Fresource%2Fcellar%2F9f2bd600-ae7b-11e7-837e-01aa75ed71a1.0001.09%2FDOC_1&fileName=eurovoc_in_skos_core_concepts.zip",
                               "eurovoc_in_skos_core_concepts.zip", 8769552)],
                "why": "the download id changes between releases: re-read the DCAT record each time"},
    "agrovoc": {"converter": "rdf", "scheme": "agrovoc", "integrate": "attach", "recommend": "yes",
                "iri_prefixes": "http://aims.fao.org/aos/agrovoc/", "wikidata_property": "P8061"},
    "gemet": {"converter": "rdf", "scheme": "gemet", "integrate": "full", "recommend": "starter",
              "iri_prefixes": "http://www.eionet.europa.eu/gemet/concept/"},
    "stw": {"converter": "rdf", "scheme": "stw", "integrate": "full", "recommend": "starter",
            "iri_prefixes": "http://zbw.eu/stw/descriptor/", "wikidata_property": "P3911"},
    "thesoz": {"converter": "rdf", "scheme": "thesoz", "integrate": "full", "recommend": "yes",
               "iri_prefixes": "https://data.gesis.org/thesoz/",
               "files": [file("https://zenodo.org/api/records/18773539/files/thesoz.ttl/content", "thesoz.ttl", 19333985)]},
    "mesh-xml": {"converter": "mesh-xml", "scheme": "mesh", "integrate": "full", "recommend": "starter",
                 "iri_prefixes": "http://id.nlm.nih.gov/mesh/", "curie_prefixes": "MESH MSH mesh", "wikidata_property": "P486",
                 "files": [file("https://nlmpubs.nlm.nih.gov/projects/mesh/MESH_FILES/xmlmesh/desc2026.gz",
                                "desc2026.xml.gz", 16812612)]},
    "mesh-rdf": {"converter": "rdf", "scheme": "mesh-rdf", "integrate": "attach", "recommend": "no",
                 "why": "the same descriptors as mesh-xml"},
    "decs": {"converter": "raw", "access": "restricted", "files": [], "recommend": "no"},
    "nalt": {"converter": "rdf", "scheme": "nalt", "integrate": "attach", "recommend": "yes",
             "iri_prefixes": "https://lod.nal.usda.gov/nalt/", "wikidata_property": "P2004"},
    "eric-thesaurus": {"converter": "raw", "recommend": "later"},
    "msc2020": {"converter": "raw", "recommend": "no"},
    "acm-ccs-2012": {"converter": "raw", "access": "blocked", "files": [], "recommend": "no"},
    "jel": {"converter": "raw", "recommend": "no"},
    "arxiv-taxonomy": {"converter": "raw", "recommend": "no"},
    "homosaurus": {"converter": "rdf", "scheme": "homosaurus", "integrate": "full", "recommend": "no",
                   "why": "CC BY-NC-ND; its community governs its use"},
    "maori-subject-headings": {"converter": "raw", "access": "blocked", "files": [], "recommend": "no",
                               "why": "consult Ngā Upoko Tukutuku's governing body before any ingest"},
    "brian-deer-xwi7xwa": {"converter": "raw", "access": "restricted", "files": [], "recommend": "no",
                           "why": "a PDF without a licence; consult the Xwi7xwa Library before any ingest"},
    "aiatsis-pathways": {"converter": "raw", "access": "blocked", "files": [], "recommend": "no",
                         "why": "consult AIATSIS before any ingest"},
    "austlang": {"converter": "raw", "recommend": "later", "why": "unreachable from this container today (502)"},
    "ascl-african-studies-thesaurus": {"converter": "raw", "access": "restricted", "files": [], "recommend": "no"},
    # ── places, languages, time ──
    "geonames-cities15000": {"converter": "geonames", "scheme": "geonames", "integrate": "full", "recommend": "starter",
                             "options": {"places": "cities15000.txt"},
                             "merge": ["geonames-countryinfo", "geonames-admin1", "geonames-hierarchy",
                                       "geonames-alternatenames-v2", "geonames-admin2"],
                             "title": "GeoNames: cities over 15,000 people, with their names in every language",
                             "files": "geonames:cities15000.zip"},
    "geonames-cities5000": {"converter": "geonames", "scheme": "geonames", "integrate": "full", "recommend": "yes",
                            "options": {"places": "cities5000.txt"}, "files": "geonames:cities5000.zip"},
    "geonames-cities1000": {"converter": "geonames", "scheme": "geonames", "integrate": "attach", "recommend": "yes",
                            "options": {"places": "cities1000.txt"}, "files": "geonames:cities1000.zip"},
    "geonames-allcountries": {"converter": "geonames", "scheme": "geonames", "integrate": "attach", "recommend": "yes",
                              "options": {"places": "allCountries.txt"}, "files": "geonames:allCountries.zip"},
    "wof-admin-sqlite": {"converter": "raw", "recommend": "no"},
    "naturalearth-admin0-countries": {"converter": "raw", "recommend": "later"},
    "naturalearth-admin1-states-provinces": {"converter": "raw", "recommend": "later"},
    "naturalearth-populated-places": {"converter": "raw", "recommend": "later"},
    "pleiades-gis-csv": {"converter": "raw", "recommend": "later"},
    "pleiades-places-json": {"converter": "raw", "recommend": "later"},
    "whg-datasets": {"converter": "raw", "access": "registration", "files": [], "recommend": "no"},
    "osmnames-planet": {"converter": "raw", "recommend": "no"},
    "sil-iso639-3-code-tables": {"converter": "iso639-3", "scheme": "iso639-3", "integrate": "full", "recommend": "later",
                                 "wikidata_property": "P220",
                                 "why": "SIL's terms forbid redistributing the tables: local use only; the IANA "
                                        "registry carries the same codes under CC0"},
    "glottolog-cldf": {"converter": "raw", "recommend": "later"},
    "glottolog-languoid-csv": {
        "converter": "csv", "scheme": "glottolog", "integrate": "full", "recommend": "starter",
        "iri_prefixes": "https://glottolog.org/resource/languoid/id/", "wikidata_property": "P1394",
        "options": {"iri_template": "https://glottolog.org/resource/languoid/id/{code}", "tables": [{
            "members": "languoid.csv", "code": "id", "kind_column": "level",
            "facets": {"family": "kind/symbol-system", "language": "kind/symbol-system", "dialect": "kind/symbol-system"},
            "where": {"column": "bookkeeping", "in": ["False"]},
            "labels": [{"column": "name", "lang": "en"}], "broader": [{"column": "parent_id", "name": "parent"}],
            "relations": [{"column": "family_id", "name": "family"}],
            "attrs": [{"column": "level"}, {"column": "latitude", "type": "real"}, {"column": "longitude", "type": "real"},
                      {"column": "country_ids"}],
            "notes": [{"column": "description", "name": "description", "lang": "en"}],
            "links": [{"column": "iso639P3code", "name": "iso639-3", "prefix": "iso639-3:", "map": "exactMatch"}]}]}},
    "wals-cldf": {"converter": "raw", "recommend": "later"},
    "iana-language-subtag-registry": {"converter": "iana-subtags", "scheme": "bcp47", "integrate": "full",
                                      "recommend": "starter", "curie_prefixes": "bcp47"},
    "cldr-localenames-full": {"converter": "cldr-names", "scheme": "cldr", "integrate": "full", "recommend": "starter",
                              "options": {"members": "*.json"}, "merge": ["cldr-core-supplemental"],
                              "title": "Unicode CLDR: names of languages, territories and scripts in every locale",
                              "files": [file("https://registry.npmjs.org/cldr-localenames-full/-/cldr-localenames-full-48.2.0.tgz",
                                             bytes_=1958951, checksum="sha1:b4a4e9c43346713306be1f543ef4d6f7217a88ae"),
                                        file("https://registry.npmjs.org/cldr-core/-/cldr-core-48.2.0.tgz", bytes_=205098)]},
    "iso15924-codes": {"converter": "raw", "recommend": "no"},
    "debian-iso-codes": {"converter": "raw", "recommend": "later"},
    "periodo-dataset": {"converter": "periodo", "scheme": "periodo", "integrate": "full", "recommend": "starter",
                        "iri_prefixes": "http://n2t.net/ark:/99152/", "wikidata_property": "P9350",
                        "files": [file("https://n2t.net/ark:/99152/p0dataset.json", "p0dataset.json", 7806288)]},
    "cliopatria-polities": {"converter": "raw", "recommend": "later"},
    "dila-time-authority": {"converter": "raw", "recommend": "later"},
    "un-wpp2024-total-population": {"converter": "raw", "recommend": "later",
                                    "why": "fills 20 of the 33 areas the World Bank baseline lacks; its converter "
                                           "will write claims onto the space/ concepts"},
    "un-wpp2024-demographic-indicators": {"converter": "raw", "recommend": "later"},
    "owid-population-longrun": {"converter": "raw", "recommend": "later"},
    "dplace-societies": {"converter": "raw", "recommend": "no"},
    "epr-core-2021": {"converter": "raw", "recommend": "no"},
    # ── sciences, life, health, statistics ──
    "gene-ontology-basic": {"converter": "obo", "scheme": "go", "integrate": "full", "recommend": "starter",
                            "options": {"id_prefix": "GO"}, **obo_ids("GO"), "wikidata_property": "P686|GO_{rest}"},
    "chebi-full": {"converter": "obo", "scheme": "chebi", "integrate": "attach", "recommend": "yes",
                   "options": {"id_prefix": "CHEBI"}, **obo_ids("CHEBI"), "wikidata_property": "P683|CHEBI_{rest}",
                   "files": [file("https://ftp.ebi.ac.uk/pub/databases/chebi/ontology/chebi.obo.gz", bytes_=47162742)]},
    "chebi-lite": {"converter": "obo", "scheme": "chebi", "integrate": "full", "recommend": "no",
                   "options": {"id_prefix": "CHEBI"}},
    "uberon-basic": {"converter": "obo", "scheme": "uberon", "integrate": "full", "recommend": "yes",
                     "options": {"id_prefix": "UBERON"}, **obo_ids("UBERON"), "wikidata_property": "P1554|UBERON_{rest}"},
    "cell-ontology-basic": {"converter": "obo", "scheme": "cl", "integrate": "full", "recommend": "yes",
                            "options": {"id_prefix": "CL"}, **obo_ids("CL"), "wikidata_property": "P7963|CL_{rest}"},
    "disease-ontology": {"converter": "obo", "scheme": "doid", "integrate": "full", "recommend": "starter",
                         "options": {"id_prefix": "DOID"}, **obo_ids("DOID"), "wikidata_property": "P699|DOID_{rest}"},
    "mondo": {"converter": "obo", "scheme": "mondo", "integrate": "full", "recommend": "yes",
              "options": {"id_prefix": "MONDO"}, **obo_ids("MONDO"), "wikidata_property": "P5270"},
    "human-phenotype-ontology": {"converter": "obo", "scheme": "hp", "integrate": "full", "recommend": "no",
                                 "why": "its licence forbids altering content or relationships"},
    "environment-ontology": {"converter": "obo", "scheme": "envo", "integrate": "full", "recommend": "starter",
                             "options": {"id_prefix": "ENVO"}, **obo_ids("ENVO"), "wikidata_property": "P3859|ENVO_{rest}"},
    "ncit-flat": {"converter": "csv", "scheme": "ncit", "integrate": "attach", "recommend": "yes",
                  "iri_prefixes": "http://ncicb.nci.nih.gov/xml/owl/EVS/Thesaurus.owl#", "curie_prefixes": "NCIT NCI",
                  "wikidata_property": "P1748",
                  "options": {"iri_template": "http://ncicb.nci.nih.gov/xml/owl/EVS/Thesaurus.owl#{code}", "tables": [{
                      "members": "Thesaurus.txt", "delimiter": "\t", "header": False, "quoting": "none", "code": 0,
                      "kind": "NCIt concept", "labels": [{"column": 5, "lang": "en", "kind": "pref"},
                                                          {"column": 3, "lang": "en", "kind": "alt", "split": "|"}],
                      "broader": [{"column": 2, "name": "parent", "split": "|"}],
                      "notes": [{"column": 4, "name": "definition", "lang": "en"}],
                      "attrs": [{"column": 6, "name": "concept_status"}, {"column": 7, "name": "semantic_type"}],
                      "status": {"column": 6, "deprecated": ["Obsolete_Concept", "Retired_Concept"]}}]}},
    "ncbi-taxonomy": {"converter": "ncbi-taxdump", "scheme": "ncbitaxon", "integrate": "attach", "recommend": "yes",
                      "iri_prefixes": f"{OBO}NCBITaxon_", "curie_prefixes": "NCBITaxon taxon", "wikidata_property": "P685",
                      "files": [file("https://ftp.ncbi.nlm.nih.gov/pub/taxonomy/taxdump.tar.gz", bytes_="",
                                     checksum="url:https://ftp.ncbi.nlm.nih.gov/pub/taxonomy/taxdump.tar.gz.md5")],
                      "why": "rebuilt daily (its size changed twice on 2026-09-25): verified against its .md5"},
    "catalogue-of-life-coldp": {"converter": "raw", "recommend": "no"},
    "gbif-backbone-taxonomy": {"converter": "raw", "recommend": "no"},
    "icd-11-mms": {"converter": "raw", "recommend": "no"},
    "snomed-ct": {"converter": "raw", "access": "registration", "files": [], "recommend": "no"},
    "umls-metathesaurus": {"converter": "raw", "access": "registration", "files": [], "recommend": "no"},
    "qudt-units": {"converter": "rdf", "scheme": "qudt", "integrate": "full", "recommend": "yes",
                   "options": {"term_types": [QUDT + "Unit", QUDT + "QuantityKind"]}, "iri_prefixes": "http://qudt.org/vocab/"},
    "unified-astronomy-thesaurus": {"converter": "rdf", "scheme": "uat", "integrate": "full", "recommend": "starter",
                                    "iri_prefixes": "http://astrothesaurus.org/uat/", "wikidata_property": "P4527"},
    "gcmd-science-keywords": {"converter": "rdf", "scheme": "gcmd", "integrate": "full", "recommend": "starter",
                              "iri_prefixes": "https://gcmd.earthdata.nasa.gov/kms/concept/",
                              "files": [file(f"https://gcmd.earthdata.nasa.gov/kms/concepts/concept_scheme/sciencekeywords/?format=rdf&page_num={n}&page_size=2000",
                                             f"gcmd-sciencekeywords-{n}.rdf") for n in (1, 2)]},
    "sweet-ontology": {"converter": "raw", "recommend": "no"},
    "ipcc-ar6-reference-regions": {"converter": "raw", "recommend": "later"},
    "oeis-names": {"converter": "csv", "scheme": "oeis", "integrate": "attach", "recommend": "yes",
                   "iri_prefixes": "https://oeis.org/", "wikidata_property": "P829",
                   "options": {"iri_template": "https://oeis.org/{code}", "tables": [{
                       "maxsplit": 1, "delimiter": " ", "header": False, "skip_prefix": "#", "code": 0,
                       "kind": "Integer sequence", "facet": "kind/mathematical-object",
                       "labels": [{"column": 1, "lang": "en"}]}]}},
    "pubchem-periodic-table": {
        "converter": "csv", "scheme": "elements", "integrate": "full", "recommend": "starter",
        "title": "The chemical elements (PubChem periodic table)",
        "options": {"iri_template": "https://pubchem.ncbi.nlm.nih.gov/element/{code}", "tables": [{
            "code": "AtomicNumber", "kind": "Chemical element", "facet": "kind/substance",
            "labels": [{"column": "Name", "lang": "en"}, {"column": "Symbol", "lang": "", "kind": "alt"}],
            "attrs": [{"column": c, "type": t} for c, t in (
                ("Symbol", None), ("AtomicMass", "real"), ("ElectronConfiguration", None), ("Electronegativity", "real"),
                ("AtomicRadius", "real"), ("IonizationEnergy", "real"), ("ElectronAffinity", "real"),
                ("OxidationStates", None), ("StandardState", None), ("MeltingPoint", "real"), ("BoilingPoint", "real"),
                ("Density", "real"), ("GroupBlock", None), ("YearDiscovered", None))]}]},
        "files": [file("https://pubchem.ncbi.nlm.nih.gov/rest/pug/periodictable/CSV", "pubchem-periodictable.csv", 15017)]},
    "iupac-gold-book": {"converter": "raw", "access": "blocked", "files": [], "recommend": "no"},
    "owid-co2-ghg": {"converter": "raw", "recommend": "later"},
    "un-sdg-global-database": {"converter": "raw", "recommend": "no"},
    "un-wpp-2024-indicators": {"skip": "the same file as un-wpp2024-demographic-indicators"},
    "eurostat-toc": {"converter": "raw", "recommend": "later"},
    "ieee-thesaurus": {"converter": "raw", "access": "restricted", "files": [], "recommend": "no"},
    "spdx-license-list": {"converter": "raw", "recommend": "later"},
    "iana-media-types": {"converter": "raw", "recommend": "later"},
    "unicode-ucd": {"converter": "raw", "recommend": "later",
                    "files": [file("https://www.unicode.org/Public/18.0.0/ucd/UCD.zip", bytes_=5657953)],
                    "why": "the 'latest' path moves: pinned to 18.0.0"},
    "github-linguist-languages": {"converter": "raw", "recommend": "later"},
}

GEONAMES_BASE = "https://download.geonames.org/export/dump/"
GEONAMES_COMMON = [("countryInfo.txt", 31678), ("admin1CodesASCII.txt", 151583), ("hierarchy.zip", 2132453),
                   ("alternateNamesV2.zip", 204799163)]
GEONAMES_SIZES = {"cities15000.zip": 3359528, "cities5000.zip": 5707443, "cities1000.zip": 11051618,
                  "allCountries.zip": 421992046}

PRESETS = {
    "starter": ("A small, open, varied starting point: every domain, many languages and several traditions "
                "of ordering knowledge, about 340 MB", None),
    "languages": ("Languages and their names", ["iana-language-subtag-registry", "cldr-localenames-full",
                                                "glottolog-languoid-csv", "oewn-2025-plus"]),
    "places-and-time": ("Places and periods", ["geonames-cities15000", "cldr-localenames-full", "periodo-dataset"]),
    "library-subjects": ("Subject systems of libraries and thesauri, from several countries",
                         ["unesco-thesaurus", "lcsh", "lcgft", "gnd-subjects", "ndlsh", "ndc9-jla", "yso", "eurovoc",
                          "agrovoc", "gemet", "stw", "thesoz", "nalt", "mesh-xml"]),
    "life-and-health": ("Life and health ontologies", ["gene-ontology-basic", "disease-ontology", "environment-ontology",
                                                       "mondo", "uberon-basic", "cell-ontology-basic", "chebi-full",
                                                       "mesh-xml", "ncit-flat", "ncbi-taxonomy"]),
    "sciences": ("Classifications of the sciences and their objects",
                 ["openalex-topics", "openalex-concepts", "physh", "unified-astronomy-thesaurus",
                  "gcmd-science-keywords", "qudt-units", "pubchem-periodic-table", "oeis-names"]),
    "encyclopedic": ("Upper ontologies and encyclopedic classes", ["schema-org", "dbpedia-ontology",
                                                                   "yago-4.6-taxonomy", "omw-2.0", "ror"]),
}


def read_research() -> dict[str, dict]:
    rows: dict[str, dict] = {}
    csv.field_size_limit(sys.maxsize)
    for fn in sorted(HERE.glob("[a-d]-*.tsv")):
        for r in csv.DictReader(open(fn, encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE):
            if r["id"] not in rows:                         # physh and getty-tgn were researched twice
                rows[r["id"]] = {**r, "_file": fn.name}
    return rows


def clean(v) -> str:
    return re.sub(r"[\t\r\n]+", " ", str(v or "")).strip()


def main() -> None:
    research = read_research()
    merged_away = {m for d in DECISIONS.values() for m in d.get("merge", [])}
    missing = [i for i in research if i not in DECISIONS and i not in merged_away]
    if missing:
        raise SystemExit(f"no curation decision for: {missing}")
    reg, files, presets = [], [], []
    for sid, d in DECISIONS.items():
        if "skip" in d:
            continue
        r = research[sid]
        why = d.get("why", "")
        row = {
            "id": sid, "title": d.get("title") or r["title"], "publisher": r["publisher"],
            "perspective": r["perspective"], "domains": " ".join(x.strip() for x in re.split(r"[;,\s]+", r["domains"]) if x.strip()),
            "kind": r["kind"], "languages": r["languages"], "license": r["license"], "license_url": r["license_url"],
            "homepage": r["homepage"], "update": r["update"], "access": d.get("access", r["access"]),
            "converter": d["converter"], "options": json.dumps(d.get("options", {}), ensure_ascii=False, sort_keys=True),
            "scheme": d.get("scheme", ""), "integrate": d.get("integrate", ""), "iri_prefixes": d.get("iri_prefixes", ""),
            "curie_prefixes": d.get("curie_prefixes", ""), "wikidata_property": d.get("wikidata_property", ""),
            "size": r["bytes"], "recommend": d["recommend"], "reviewer": REVIEWER,
            "verified": clean(r["verified"]),
            "notes": clean((why + ". " if why else "") + (f"Merged rows: {', '.join(d['merge'])}. " if d.get('merge') else "")
                           + f"Research: {r['_file']}. " + r["notes"])}
        if not row["scheme"]:
            row["scheme"] = sid.replace(".", "-")
        reg.append({k: clean(row[k]) if k != "options" else row[k] for k in COLUMNS})
        fs = d.get("files")
        if fs is None:
            chk = r["checksum_url"]
            use = f"url:{chk}" if re.search(r"(\.md5|\.sha\d+|SUMS|[Cc]hecksum\.txt)$", chk or "") else ""
            fs = [file(r["url"], bytes_=r["bytes"], checksum=use)]
        elif isinstance(fs, str) and fs.startswith("geonames:"):
            main_file = fs.split(":", 1)[1]
            fs = [file(GEONAMES_BASE + n, bytes_=b) for n, b in GEONAMES_COMMON[:2]] + \
                 [file(GEONAMES_BASE + main_file, bytes_=GEONAMES_SIZES[main_file])] + \
                 [file(GEONAMES_BASE + n, bytes_=b) for n, b in GEONAMES_COMMON[2:]]
        for f in fs:
            files.append({"source": sid, **{k: clean(v) for k, v in f.items()}, "verified": clean(r["verified"])[:200]})
    starter = [x["id"] for x in reg if x["recommend"] == "starter"]
    for name, (note, ids) in PRESETS.items():
        for sid in (ids if ids is not None else starter):
            presets.append({"preset": name, "source": sid, "note": note})
    open_ids = [x["id"] for x in reg if x["recommend"] in ("starter", "yes") and x["access"] == "open"]
    for sid in open_ids:
        presets.append({"preset": "everything-recommended", "source": sid,
                        "note": "every source recommended for use: several GB; large ones attach instead of merging"})
    out = ROOT / "seed" / "sources"
    out.mkdir(parents=True, exist_ok=True)
    for name, cols, rows in (("registry.tsv", COLUMNS, reg), ("files.tsv", FILE_COLUMNS, files),
                             ("presets.tsv", PRESET_COLUMNS, presets)):
        with open(out / name, "w", encoding="utf-8", newline="") as fh:
            fh.write("\t".join(cols) + "\n")
            for x in rows:
                fh.write("\t".join(clean(x.get(c, "")) if c != "options" else x.get(c, "") for c in cols) + "\n")
    print(f"{len(reg)} sources ({len(starter)} in the starter preset, {len(open_ids)} recommended), "
          f"{len(files)} files, {len(PRESETS) + 1} presets -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
