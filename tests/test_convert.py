"""Converters: each source format -> the lean layout, on small fixtures in the publishers' own formats."""
import gzip
import io
import json
import sqlite3
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from acatalogue.convert import Input, registry
from acatalogue.lean import LeanReader, LeanWriter
from acatalogue.util import sha512_file

SKOS_NT = r'''
<http://ex.org/v/scheme> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/2004/02/skos/core#ConceptScheme> .
<http://ex.org/v/scheme> <http://www.w3.org/2004/02/skos/core#prefLabel> "Test scheme"@en .
<http://ex.org/v/c1> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/2004/02/skos/core#Concept> .
<http://ex.org/v/c1> <http://www.w3.org/2004/02/skos/core#prefLabel> "Science"@en .
<http://ex.org/v/c1> <http://www.w3.org/2004/02/skos/core#prefLabel> "Bilim"@tr .
<http://ex.org/v/c1> <http://www.w3.org/2004/02/skos/core#altLabel> "Sciences"@en .
<http://ex.org/v/c1> <http://www.w3.org/2004/02/skos/core#topConceptOf> <http://ex.org/v/scheme> .
<http://ex.org/v/c1> <http://www.w3.org/2004/02/skos/core#narrower> <http://ex.org/v/c2> .
<http://ex.org/v/c1> <http://www.w3.org/2004/02/skos/core#definition> "Systematic knowledge.\nWith \"quotes\" and é."@en .
<http://ex.org/v/c1> <http://www.w3.org/2004/02/skos/core#notation> "5" .
<http://ex.org/v/c1> <http://www.w3.org/2004/02/skos/core#exactMatch> <http://www.wikidata.org/entity/Q336> .
<http://ex.org/v/c2> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/2004/02/skos/core#Concept> .
<http://ex.org/v/c2> <http://www.w3.org/2008/05/skos-xl#prefLabel> _:l1 .
_:l1 <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/2008/05/skos-xl#Label> .
_:l1 <http://www.w3.org/2008/05/skos-xl#literalForm> "Physics"@en .
<http://ex.org/v/c2> <http://www.w3.org/2004/02/skos/core#broader> <http://ex.org/v/c1> .
<http://ex.org/v/c2> <http://www.w3.org/2004/02/skos/core#related> <http://ex.org/v/c3> .
<http://ex.org/v/c3> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/2004/02/skos/core#Concept> .
<http://ex.org/v/c3> <http://www.w3.org/2004/02/skos/core#prefLabel> "Chemistry"@en .
<http://ex.org/v/c3> <http://www.w3.org/2004/02/skos/core#related> <http://ex.org/v/c2> .
<http://ex.org/v/c3> <http://www.w3.org/2004/02/skos/core#scopeNote> <http://ex.org/v/note/1> .
<http://ex.org/v/note/1> <http://www.w3.org/1999/02/22-rdf-syntax-ns#value> "Of substances."@en .
<http://ex.org/v/c3> <http://www.w3.org/2002/07/owl#deprecated> "true"^^<http://www.w3.org/2001/XMLSchema#boolean> .
<http://ex.org/v/c3> <http://purl.org/dc/terms/isReplacedBy> <http://ex.org/v/c2> .
<http://ex.org/v/c3> <http://www.w3.org/2004/02/skos/core#broader> <http://other.org/x/9> .
<http://ex.org/v/c3> <http://ex.org/custom#weight> "12"^^<http://www.w3.org/2001/XMLSchema#integer> .
<http://ex.org/v/g> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/2004/02/skos/core#Collection> .
<http://ex.org/v/g> <http://www.w3.org/2004/02/skos/core#prefLabel> "Group"@en .
<http://ex.org/v/g> <http://www.w3.org/2004/02/skos/core#member> <http://ex.org/v/c3> .
'''

SKOS_XML = '''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE rdf:RDF [ <!ENTITY v "http://ex.org/v/"> ]>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:skos="http://www.w3.org/2004/02/skos/core#"
         xmlns:skosxl="http://www.w3.org/2008/05/skos-xl#" xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:dct="http://purl.org/dc/terms/" xmlns:c="http://ex.org/custom#" xml:base="http://ex.org/v/">
  <skos:ConceptScheme rdf:about="scheme"><skos:prefLabel xml:lang="en">Test scheme</skos:prefLabel></skos:ConceptScheme>
  <skos:Concept rdf:about="&v;c1" xml:lang="en">
    <skos:prefLabel>Science</skos:prefLabel>
    <skos:prefLabel xml:lang="tr">Bilim</skos:prefLabel>
    <skos:altLabel>Sciences</skos:altLabel>
    <skos:topConceptOf rdf:resource="scheme"/>
    <skos:narrower><skos:Concept rdf:about="c2">
      <skosxl:prefLabel><skosxl:Label><skosxl:literalForm xml:lang="en">Physics</skosxl:literalForm></skosxl:Label></skosxl:prefLabel>
      <skos:broader rdf:resource="c1"/>
      <skos:related rdf:resource="c3"/>
    </skos:Concept></skos:narrower>
    <skos:definition>Systematic knowledge.
With "quotes" and &#233;.</skos:definition>
    <skos:notation xml:lang="">5</skos:notation>
    <skos:exactMatch rdf:resource="http://www.wikidata.org/entity/Q336"/>
  </skos:Concept>
  <rdf:Description rdf:about="c3">
    <rdf:type rdf:resource="http://www.w3.org/2004/02/skos/core#Concept"/>
    <skos:prefLabel xml:lang="en">Chemistry</skos:prefLabel>
    <skos:related rdf:resource="c2"/>
    <skos:scopeNote><rdf:Description rdf:about="note/1"><rdf:value xml:lang="en">Of substances.</rdf:value></rdf:Description></skos:scopeNote>
    <owl:deprecated rdf:datatype="http://www.w3.org/2001/XMLSchema#boolean">true</owl:deprecated>
    <dct:isReplacedBy rdf:resource="c2"/>
    <skos:broader rdf:resource="http://other.org/x/9"/>
    <c:weight rdf:datatype="http://www.w3.org/2001/XMLSchema#integer">12</c:weight>
  </rdf:Description>
  <skos:Collection rdf:about="g"><skos:prefLabel xml:lang="en">Group</skos:prefLabel>
    <skos:member rdf:resource="c3"/></skos:Collection>
</rdf:RDF>
'''

Q3 = '"' * 3
SKOS_TTL = ("""@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix skosxl: <http://www.w3.org/2008/05/skos-xl#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix dct: <http://purl.org/dc/terms/> .
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
@base <http://ex.org/v/> .
<scheme> a skos:ConceptScheme ; skos:prefLabel "Test scheme"@en .
<c1> a skos:Concept ;
    skos:prefLabel "Science"@en, "Bilim"@tr ;
    skos:altLabel "Sciences"@en ;
    skos:topConceptOf <scheme> ;
    skos:narrower <c2> ;
    skos:definition """ + Q3 + "Systematic knowledge.\nWith \"quotes\" and \\u00e9." + Q3 + """@en ;
    skos:notation "5" ;
    skos:exactMatch <http://www.wikidata.org/entity/Q336> .
<c2> a skos:Concept ; skosxl:prefLabel [ a skosxl:Label ; skosxl:literalForm "Physics"@en ] ;
    skos:broader <c1> ; skos:related <c3> .
<c3> a skos:Concept ; skos:prefLabel 'Chemistry'@en ; skos:related <c2> ;
    skos:scopeNote <note/1> ; owl:deprecated true ; dct:isReplacedBy <c2> ;
    skos:broader <http://other.org/x/9> ; <http://ex.org/custom#weight> 12 .
<note/1> rdf:value "Of substances."@en .
<g> a skos:Collection ; skos:prefLabel "Group"@en ; skos:member <c3> .
""")

OBO = '''format-version: 1.2
data-version: releases/2026-09-01
ontology: go

[Term]
id: GO:0000001
name: mitochondrion inheritance
namespace: biological_process
def: "The distribution of \\"mitochondria\\"." [GOC:mcc, PMID:10873824]
synonym: "mitochondrial inheritance" EXACT []
synonym: "organelle inheritance" BROAD [GOC:x]
is_a: GO:0048308 ! organelle inheritance
relationship: part_of GO:0048311 ! mitochondrion distribution
relationship: regulates GO:0048308
xref: Wikipedia:Mitochondrion

[Term]
id: GO:0048308
name: organelle inheritance

[Term]
id: GO:0048311
name: mitochondrion distribution

[Term]
id: GO:0000002
name: obsolete thing
is_obsolete: true
replaced_by: GO:0000001

[Typedef]
id: part_of
name: part of
xref: BFO:0000050
'''


def inp(path: Path, name: str | None = None, url: str | None = None) -> Input:
    digest, n = sha512_file(path)
    return Input(name or path.name, path, digest, n, url, "2026-09-25T00:00:00Z")


def run(conv: str, inputs, options=None, tmp=None):
    tmp = tmp or Path(tempfile.mkdtemp())
    w = LeanWriter(tmp / "out.sqlite", source="t", title="t", converter=conv, version="1")
    for i in inputs:
        w.input(i.name, i.sha512, i.bytes, i.url, i.retrieved_at)
    registry()[conv](inputs, w, options or {}, lambda *_: None)
    out = w.finish()
    return LeanReader(out["path"]), out


def content(r: LeanReader) -> dict:
    """Everything a lean file says, by codes and names (ids aside)."""
    c = r.conn
    code = dict(c.execute("SELECT id, code FROM term"))
    pred = dict(c.execute("SELECT id, name FROM pred"))
    lang = dict(c.execute("SELECT id, tag FROM lang"))
    return {
        "terms": sorted((t, k, s) for t, k, s in c.execute(
            "SELECT t.code, k.name, t.status FROM term t LEFT JOIN kind k ON k.id = t.kind")),
        "labels": sorted((code[t], lang[lg], k, x) for t, lg, k, x in c.execute("SELECT term, lang, kind, text FROM label")),
        "rel": sorted((code[s], pred[p], code[o]) for s, p, o in c.execute("SELECT s, p, o FROM rel")),
        "attr": sorted((code[t], pred[p], lang[lg], str(v)) for t, p, lg, v in c.execute("SELECT term, p, lang, value FROM attr")),
        "link": sorted((code[t], pred[p], x) for t, p, x in c.execute("SELECT term, p, target FROM link")),
    }


class RdfTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def nt(self):
        p = self.tmp / "v.nt.gz"
        p.write_bytes(gzip.compress(SKOS_NT.encode()))
        return run("rdf", [inp(p)], tmp=self.tmp / "a")

    def test_skos_in_ntriples(self):
        r, out = self.nt()
        c = content(r)
        self.assertEqual([t[0] for t in c["terms"]], ["c1", "c2", "c3", "g", "scheme"])
        self.assertIn(("c3", "Concept", 1), c["terms"], "owl:deprecated")
        self.assertIn(("c1", "tr", 0, "Bilim"), c["labels"])
        self.assertIn(("c1", "en", 1, "Sciences"), c["labels"])
        self.assertIn(("c2", "en", 0, "Physics"), c["labels"], "SKOS-XL literal form")
        # narrower stated once and broader stated once: one row, under skos:broader
        self.assertEqual([x for x in c["rel"] if x[0] == "c2" and x[2] == "c1"], [("c2", "skos:broader", "c1")])
        self.assertIn(("c1", "skos:topConceptOf", "scheme"), c["rel"])
        self.assertIn(("c3", "skos:member^-1", "g"), c["rel"], "a member placed under its collection")
        self.assertEqual([x for x in c["rel"] if x[1] == "skos:related"], [("c2", "skos:related", "c3")],
                         "symmetric: stored once")
        self.assertIn(("c3", "skos:broader", "http://other.org/x/9"), c["link"], "an outside broader is kept")
        self.assertIn(("c1", "skos:exactMatch", "http://www.wikidata.org/entity/Q336"), c["link"])
        self.assertIn(("c1", "skos:definition", "en", 'Systematic knowledge.\nWith "quotes" and é.'), c["attr"])
        self.assertIn(("c3", "skos:scopeNote", "en", "Of substances."), c["attr"], "a note published as a resource")
        self.assertIn(("c3", "dct:isReplacedBy", "", "c2"), c["attr"])
        self.assertIn(("c3", "http://ex.org/custom#weight", "", "12"), c["attr"])
        weight = r.conn.execute("SELECT typeof(value) FROM attr a JOIN pred p ON p.id = a.p"
                                " WHERE p.name = 'http://ex.org/custom#weight'").fetchone()[0]
        self.assertEqual(weight, "integer", "xsd:integer kept as a number")
        self.assertEqual(r.meta["iri_template"], "http://ex.org/v/{code}")
        self.assertEqual(r.iri("c1", None), "http://ex.org/v/c1")
        roles = dict(r.conn.execute("SELECT name, role FROM pred"))
        self.assertEqual((roles["skos:broader"], roles["skos:exactMatch"], roles["skos:notation"]),
                         ("broader", "link", "notation"))
        self.assertEqual(r.conn.execute("SELECT count(*) FROM label_fts WHERE label_fts MATCH 'physics'").fetchone()[0], 1)

    def test_the_same_bytes_convert_to_the_same_file(self):
        a = self.nt()[1]
        b = run("rdf", [inp(self.tmp / "v.nt.gz")], tmp=self.tmp / "again")[1]
        self.assertEqual(a["sha512"], b["sha512"], "a lean file is a function of its inputs and its reading")

    def test_rdfxml_and_turtle_read_the_same_as_ntriples(self):
        a = content(self.nt()[0])
        p = self.tmp / "v.rdf"
        p.write_text(SKOS_XML, encoding="utf-8")
        self.assertEqual(content(run("rdf", [inp(p)], tmp=self.tmp / "b")[0]), a)
        t = self.tmp / "v.ttl.gz"
        t.write_bytes(gzip.compress(SKOS_TTL.encode()))
        self.assertEqual(content(run("rdf", [inp(t)], tmp=self.tmp / "c")[0]), a)


class OboTests(unittest.TestCase):
    def test_gene_ontology_stanzas(self):
        tmp = Path(tempfile.mkdtemp())
        p = tmp / "go-basic.obo"
        p.write_text(OBO)
        r, out = run("obo", [inp(p)])
        c = content(r)
        self.assertIn(("GO_0000001", "en", 0, "mitochondrion inheritance"), c["labels"])
        self.assertIn(("GO_0000001", "en", 1, "mitochondrial inheritance"), c["labels"], "EXACT: a synonym")
        self.assertIn(("GO_0000001", "en", 3, "organelle inheritance"), c["labels"], "BROAD: a broader name")
        self.assertIn(("GO_0000001", "is_a", "GO_0048308"), c["rel"])
        self.assertIn(("GO_0000001", "part_of", "GO_0048311"), c["rel"])
        roles = dict(r.conn.execute("SELECT name, role FROM pred"))
        self.assertEqual((roles["part_of"], roles["regulates"]), ("broader", "relation"))
        self.assertEqual(r.conn.execute("SELECT iri FROM pred WHERE name = 'part_of'").fetchone()[0],
                         "http://purl.obolibrary.org/obo/BFO_0000050")
        self.assertIn(("GO_0000001", "definition", "en", 'The distribution of "mitochondria".'), c["attr"])
        self.assertIn(("GO_0000001", "definition_source", "", "PMID:10873824"), c["attr"])
        self.assertIn(("GO_0000001", "xref", "Wikipedia:Mitochondrion"), c["link"])
        self.assertIn(("GO_0000002", "Class", 1), c["terms"])
        self.assertIn(("GO_0000002", "replaced_by", "", "GO_0000001"), c["attr"])
        self.assertEqual(r.meta["obo_data_version"], "releases/2026-09-01")
        self.assertEqual(r.iri("GO_0000001", None), "http://purl.obolibrary.org/obo/GO_0000001")


class TableTests(unittest.TestCase):
    OPTIONS = {"tables": [{"members": "languoid.csv", "code": "id", "kind": "Languoid", "facet": "kind/symbol-system",
                           "labels": [{"column": "name", "lang": "en"}],
                           "broader": [{"column": "parent_id", "name": "parent"}],
                           "attrs": [{"column": "latitude", "type": "real"}, {"column": "level"}],
                           "links": [{"column": "iso639P3code", "name": "iso639-3", "prefix": "iso639-3:",
                                      "map": "exactMatch"}],
                           "status": {"column": "bookkeeping", "deprecated": ["True"]}}]}

    def test_a_declared_csv_mapping(self):
        tmp = Path(tempfile.mkdtemp())
        z = tmp / "glottolog_languoid.csv.zip"
        with zipfile.ZipFile(z, "w") as f:
            f.writestr("languoid.csv", "id,parent_id,name,level,latitude,iso639P3code,bookkeeping\n"
                                       "turk1311,,Turkic,family,,,False\n"
                                       "nucl1301,turk1311,Turkish,language,39.87,tur,False\n"
                                       "book1242,,Bookkeeping,family,,,True\n")
        r, out = run("csv", [inp(z)], self.OPTIONS)
        c = content(r)
        self.assertIn(("nucl1301", "parent", "turk1311"), c["rel"])
        self.assertIn(("nucl1301", "iso639-3", "iso639-3:tur"), c["link"])
        self.assertIn(("book1242", "Languoid", 1), c["terms"])
        self.assertEqual(r.conn.execute("SELECT value, typeof(value) FROM attr a JOIN pred p ON p.id = a.p"
                                        " WHERE p.name = 'latitude'").fetchone(), (39.87, "real"))
        self.assertEqual(r.conn.execute("SELECT facet FROM kind").fetchone()[0], "kind/symbol-system")
        self.assertEqual(sum(1 for a in c["attr"] if a[0] == "turk1311" and a[1] == "latitude"), 0,
                         "an empty cell is an absent value")

    def test_a_local_sqlite_database(self):
        tmp = Path(tempfile.mkdtemp())
        db = tmp / "mine.sqlite"
        con = sqlite3.connect(db)
        con.executescript("CREATE TABLE wish(id INTEGER PRIMARY KEY, title TEXT, parent INTEGER, note TEXT);"
                          "INSERT INTO wish VALUES (1, 'Fly', NULL, 'the first'), (2, 'Fly higher', 1, NULL);")
        con.commit()
        con.close()
        opts = {"tables": [{"sql": "SELECT id, title, parent, note FROM wish ORDER BY id", "code": "id",
                            "kind": "Wish", "labels": [{"column": "title", "lang": "en"}],
                            "broader": [{"column": "parent"}], "notes": [{"column": "note", "name": "note"}]}]}
        c = content(run("sqlite", [inp(db)], opts)[0])
        self.assertEqual(c["rel"], [("2", "parent", "1")])
        self.assertIn(("1", "note", "", "the first"), c["attr"])


def zipped(path: Path, files: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        for k, v in files.items():
            z.writestr(k, v)
    return path


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_geonames(self):
        t = self.tmp
        (t / "countryInfo.txt").write_text("#ISO\tISO3\n" + "\t".join(
            ["TR", "TUR", "792", "TU", "Türkiye", "Ankara", "783562", "85000000", "AS", ".tr", "TRY", "Lira", "90",
             "#####", "", "tr-TR,ku,diq,az,av", "298795", "SY,GE,IQ"]) + "\n")
        (t / "admin1CodesASCII.txt").write_text("TR.34\tIstanbul\tIstanbul\t745042\n")
        row = ["745044", "İstanbul", "Istanbul", "", "41.01384", "28.94966", "P", "PPLA", "TR", "", "34", "", "", "",
               "14804116", "", "39", "Europe/Istanbul", "2026-01-01"]
        cities = zipped(t / "cities15000.zip", {"cities15000.txt": "\t".join(row) + "\n"})
        names = zipped(t / "alternateNamesV2.zip", {"alternateNamesV2.txt": "\n".join("\t".join(r) for r in [
            ["1", "745044", "en", "Istanbul", "1", "", "", "", "", ""],
            ["2", "745044", "el", "Κωνσταντινούπολη", "", "", "", "1", "", "1930"],
            ["3", "745044", "wkdt", "Q406", "", "", "", "", "", ""],
            ["4", "745044", "link", "https://en.wikipedia.org/wiki/Istanbul", "", "", "", "", "", ""],
            ["5", "745044", "post", "34000", "", "", "", "", "", ""],
            ["6", "999999", "en", "Nowhere kept", "1", "", "", "", "", ""]]) + "\n"})
        inputs = [inp(t / "countryInfo.txt"), inp(t / "admin1CodesASCII.txt"), inp(cities), inp(names)]
        r, out = run("geonames", inputs, tmp=t / "out")
        c = content(r)
        self.assertIn(("745044", "parentFeature", "745042"), c["rel"])
        self.assertIn(("745042", "parentFeature", "298795"), c["rel"])
        self.assertIn(("745044", "en", 0, "Istanbul"), c["labels"])
        self.assertIn(("745044", "el", 1, "Κωνσταντινούπολη"), c["labels"], "a historic name is a name")
        self.assertTrue(any(a[1] == "historic_name" and '"to": "1930"' in a[3] for a in c["attr"]),
                        "and keeps its dates")
        self.assertIn(("745044", "wikidata", "http://www.wikidata.org/entity/Q406"), c["link"])
        self.assertIn(("745044", "postal_code", "", "34000"), c["attr"])
        self.assertFalse(any(x[0] == "999999" for x in c["labels"]), "names of places not kept are not kept")
        self.assertEqual(r.conn.execute("SELECT count(DISTINCT facet) FROM kind").fetchone()[0], 1)
        self.assertEqual(json.loads(r.meta["dropped"])["labels_unknown_term"], 0,
                         "the converter skips unknown places itself")

    def test_iso639_3(self):
        z = zipped(self.tmp / "iso-639-3_Code_Tables.zip", {
            "iso-639-3.tab": "Id\tPart2b\tPart2t\tPart1\tScope\tLanguage_Type\tRef_Name\tComment\n"
                             "tur\ttur\ttur\ttr\tI\tL\tTurkish\t\nzho\tchi\tzho\tzh\tM\tL\tChinese\t\n"
                             "cmn\t\t\t\tI\tL\tMandarin Chinese\t\n",
            "iso-639-3_Name_Index.tab": "Id\tPrint_Name\tInverted_Name\ncmn\tMandarin Chinese\tChinese, Mandarin\n",
            "iso-639-3-macrolanguages.tab": "M_Id\tI_Id\tI_Status\nzho\tcmn\tA\n",
            "iso-639-3_Retirements.tab": "Id\tRef_Name\tRet_Reason\tChange_To\tRet_Remedy\tEffective\n"
                                         "mol\tMoldavian\tM\tron\t\t2008-11-03\n"})
        c = content(run("iso639-3", [inp(z)])[0])
        self.assertIn(("cmn", "macrolanguage", "zho"), c["rel"])
        self.assertIn(("cmn", "en", 1, "Chinese, Mandarin"), c["labels"])
        self.assertIn(("mol", "Language", 1), c["terms"])
        self.assertIn(("mol", "change_to", "", "ron"), c["attr"])
        self.assertIn(("tur", "part1", "", "tr"), c["attr"])

    def test_ncbi_taxdump(self):
        tgz = self.tmp / "taxdump.tar.gz"
        with tarfile.open(tgz, "w:gz") as tf:
            for name, body in (("division.dmp", "0\t|\tBCT\t|\tBacteria\t|\t\t|\n"),
                               ("names.dmp", "1\t|\troot\t|\t\t|\tscientific name\t|\n"
                                             "9606\t|\tHomo sapiens\t|\t\t|\tscientific name\t|\n"
                                             "9606\t|\thuman\t|\t\t|\tgenbank common name\t|\n"
                                             "9606\t|\tHomo sapiens Linnaeus, 1758\t|\t\t|\tauthority\t|\n"),
                               ("nodes.dmp", "1\t|\t1\t|\tno rank\t|\t\t|\t8\t|\n"
                                             "9606\t|\t1\t|\tspecies\t|\tHS\t|\t0\t|\n")):
                data = body.encode()
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
        c = content(run("ncbi-taxdump", [inp(tgz)])[0])
        self.assertIn(("9606", "parent", "1"), c["rel"])
        self.assertNotIn(("1", "parent", "1"), c["rel"], "the root is not its own parent")
        self.assertIn(("9606", "mul", 0, "Homo sapiens"), c["labels"])
        self.assertIn(("9606", "en", 1, "human"), c["labels"])
        self.assertIn(("9606", "authority", "", "Homo sapiens Linnaeus, 1758"), c["attr"])

    def test_cldr_names(self):
        t = self.tmp
        files = {
            "package/main/tr/languages.json": json.dumps({"main": {"tr": {"localeDisplayNames": {"languages": {
                "en": "İngilizce", "tr": "Türkçe", "en-GB-alt-short": "Birleşik Krallık İngilizcesi"}}}}}),
            "package/main/ja/territories.json": json.dumps({"main": {"ja": {"localeDisplayNames": {"territories": {
                "TR": "トルコ", "142": "アジア"}}}}}),
            "package/supplemental/territoryContainment.json": json.dumps({"supplemental": {"territoryContainment": {
                "142": {"_contains": ["145"]}, "145": {"_contains": ["TR"]},
                "EU": {"_contains": ["DE"]}, "EU-status-grouping": {"_contains": ["FR"]}}}}),
            "package/supplemental/territoryInfo.json": json.dumps({"supplemental": {"territoryInfo": {
                "TR": {"_population": "85000000", "languagePopulation": {"tr": {"_populationPercent": "86"}}}}}})}
        tgz = t / "cldr.tgz"
        with tarfile.open(tgz, "w:gz") as tf:
            for name, body in files.items():
                data = body.encode()
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
        r, _ = run("cldr-names", [inp(tgz)])
        c = content(r)
        self.assertIn(("language.tr", "tr", 0, "Türkçe"), c["labels"])
        self.assertIn(("language.en-GB", "tr", 1, "Birleşik Krallık İngilizcesi"), c["labels"])
        self.assertIn(("territory.TR", "ja", 0, "トルコ"), c["labels"])
        self.assertIn(("territory.TR", "containedIn", "territory.145"), c["rel"])
        self.assertIn(("territory.FR", "groupingContainedIn", "territory.EU"), c["rel"], "a grouping is not a parent")
        self.assertTrue(any(a[1] == "language_population" and '"language": "tr"' in a[3] for a in c["attr"]))

    def test_periodo(self):
        doc = {"authorities": {"p0abc": {"id": "p0abc", "source": {"title": "An atlas of Anatolia"}, "periods": {
            "p0abcdef": {"id": "p0abcdef", "label": "Tunç Çağı", "languageTag": "tr",
                         "localizedLabels": {"tr": ["Tunç Çağı"], "en": ["Bronze Age"]},
                         "spatialCoverage": [{"id": "http://www.wikidata.org/entity/Q43", "label": "Turkey"}],
                         "start": {"label": "3000 BC", "in": {"year": "-2999"}},
                         "stop": {"label": "1200 BC", "in": {"earliestYear": "-1250", "latestYear": "-1150"}}}}}}}
        p = self.tmp / "p0d.json"
        p.write_text(json.dumps(doc, ensure_ascii=False))
        c = content(run("periodo", [inp(p)])[0])
        self.assertIn(("p0abcdef", "definedBy", "p0abc"), c["rel"], "a period stays inside its authority")
        self.assertIn(("p0abcdef", "en", 0, "Bronze Age"), c["labels"])
        self.assertIn(("p0abcdef", "start_earliest", "", "-2999"), c["attr"])
        self.assertIn(("p0abcdef", "stop_latest", "", "-1150"), c["attr"])
        self.assertIn(("p0abcdef", "spatialCoverage", "http://www.wikidata.org/entity/Q43"), c["link"])

    def test_mesh(self):
        xml = """<DescriptorRecordSet>
          <DescriptorRecord><DescriptorUI>D002477</DescriptorUI><DescriptorName><String>Cells</String></DescriptorName>
            <TreeNumberList><TreeNumber>A11</TreeNumber></TreeNumberList>
            <ConceptList><Concept PreferredConceptYN="Y"><ConceptUI>M1</ConceptUI><ScopeNote>The basic unit.</ScopeNote>
              <TermList><Term RecordPreferredTermYN="Y"><String>Cells</String></Term>
                        <Term RecordPreferredTermYN="N"><String>Cell</String></Term></TermList></Concept></ConceptList>
          </DescriptorRecord>
          <DescriptorRecord><DescriptorUI>D002460</DescriptorUI><DescriptorName><String>Cell Line</String></DescriptorName>
            <TreeNumberList><TreeNumber>A11.251</TreeNumber></TreeNumberList>
            <ConceptList><Concept PreferredConceptYN="N"><ConceptUI>M2</ConceptUI>
              <ConceptRelationList><ConceptRelation RelationName="NRW"/></ConceptRelationList>
              <TermList><Term><String>Cell Lines, Tumor</String></Term></TermList></Concept></ConceptList>
          </DescriptorRecord></DescriptorRecordSet>"""
        p = self.tmp / "desc2026.xml"
        p.write_text(xml)
        c = content(run("mesh-xml", [inp(p)])[0])
        self.assertIn(("D002460", "broaderDescriptor", "D002477"), c["rel"])
        self.assertIn(("D002477", "en", 1, "Cell"), c["labels"])
        self.assertIn(("D002460", "en", 4, "Cell Lines, Tumor"), c["labels"], "a narrower concept's term")
        self.assertIn(("D002477", "scopeNote", "en", "The basic unit."), c["attr"])

    def test_wikidata_dump_filter(self):
        ents = [{"id": "Q406", "labels": {"en": {"value": "Istanbul"}, "tr": {"value": "İstanbul"}},
                 "aliases": {"en": [{"value": "Constantinople"}]}, "descriptions": {"en": {"value": "city"}},
                 "sitelinks": {"enwiki": {}, "trwiki": {}},
                 "claims": {"P31": [{"rank": "normal", "mainsnak": {"snaktype": "value", "datatype": "wikibase-item",
                                     "datavalue": {"type": "wikibase-entityid", "value": {"id": "Q515"}}}}],
                            "P131": [{"rank": "normal", "mainsnak": {"snaktype": "value", "datatype": "wikibase-item",
                                      "datavalue": {"type": "wikibase-entityid", "value": {"id": "Q43"}}}}],
                            "P1566": [{"rank": "normal", "mainsnak": {"snaktype": "value", "datatype": "external-id",
                                       "datavalue": {"type": "string", "value": "745044"}}}]}},
                {"id": "Q1", "labels": {"en": {"value": "universe"}}, "sitelinks": {}, "claims": {}}]
        text = "[\n" + ",\n".join(json.dumps(e) for e in ents) + "\n]\n"
        p = self.tmp / "latest-all.json.gz"
        p.write_bytes(gzip.compress(text.encode()))
        c = content(run("wikidata-json", [inp(p)], {"instance_of": ["Q515"]})[0])
        self.assertEqual([t[0] for t in c["terms"]], ["Q406"])
        self.assertIn(("Q406", "P131", "Q43"), c["link"], "a broader item outside the selection is kept as a link")
        self.assertIn(("Q406", "P1566:id", "P1566:745044"), c["link"])
        self.assertIn(("Q406", "en", 1, "Constantinople"), c["labels"])


if __name__ == "__main__":
    unittest.main()
