"""Updates never overwrite or delete: newer corpora supersede, removed concepts are deprecated."""
import json
import tempfile
import unittest
from pathlib import Path

from acatalogue import compendium, db as dbm, ledger
from acatalogue.compendium import CONCEPT_COLUMNS, read_scheme
from acatalogue.corpusfile import CorpusFile
from acatalogue.grep import grep
from acatalogue.sources import wikidata, wikipedia


def fresh(tmp: Path):
    conn = dbm.connect(tmp / "t.sqlite", create=True)
    dbm.init_schema(conn)
    return conn


def intro_corpus(root: Path, name: str, pages: list[tuple[str, str]]) -> CorpusFile:
    c = CorpusFile(root / name / "corpus.sqlite", create=True, name=name, title="test intros")
    body = {"query": {"pages": [{"title": t, "extract": x, "lastrevid": i,
                                 "fullurl": f"https://en.wikipedia.org/wiki/{t}"} for i, (t, x) in enumerate(pages)]}}
    c.add("intros/batch-001.json", json.dumps(body).encode(), url="https://en.wikipedia.org/w/api.php")
    c.seal()
    return c


def claims_corpus(root: Path, name: str, triples: list[tuple[str, str, str]]) -> CorpusFile:
    c = CorpusFile(root / name / "corpus.sqlite", create=True, name=name, title="test claims")
    bindings = [{"item": {"value": f"http://www.wikidata.org/entity/{s}"}, "pid": {"value": p},
                 "value": {"value": f"http://www.wikidata.org/entity/{o}"}, "valueLabel": {"value": o},
                 "rank": {"value": "http://wikiba.se/ontology#NormalRank"}} for s, p, o in triples]
    c.add("sparql/claims-001.json", json.dumps({"results": {"bindings": bindings}}).encode(),
          url="https://query.wikidata.org/sparql")
    c.seal()
    return c


class SupersessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.conn = fresh(self.tmp)

    def test_newer_intros_supersede_older_same_name(self):
        old = intro_corpus(self.tmp, "wikipedia-en-intros-20260101",
                           [("Physics", "Physics used to be described like this."), ("Old page", "Only here.")])
        new = intro_corpus(self.tmp, "wikipedia-en-intros-20260201", [("Physics", "Physics is described anew.")])
        for c in (old, new):
            self.conn.execute("INSERT INTO corpus(name, title, path, imported_at) VALUES (?, 't', ?, 'now')",
                              (c.name, str(c.path)))
            wikipedia.import_documents(self.conn, c, {})
        rows = dict(self.conn.execute("SELECT id, superseded_by FROM document").fetchall())
        self.assertEqual(rows["doc/wikipedia-en-intros-20260101/Physics"], "doc/wikipedia-en-intros-20260201/Physics")
        self.assertIsNone(rows["doc/wikipedia-en-intros-20260201/Physics"])
        self.assertIsNone(rows["doc/wikipedia-en-intros-20260101/Old_page"], "no successor: stays current")
        self.assertEqual(len(rows), 3, "nothing deleted")
        self.conn.execute("INSERT INTO passage_fts(passage_fts) VALUES ('rebuild')")
        hits = grep(self.conn, "Physics", scope="passages").hits
        self.assertEqual([h.target.split("#")[0] for h in hits], ["doc/wikipedia-en-intros-20260201/Physics"])

    def test_newer_claims_supersede_older(self):
        old = claims_corpus(self.tmp, "wikidata-entities-20260101", [("Q1", "P279", "Q2"), ("Q1", "P361", "Q3")])
        new = claims_corpus(self.tmp, "wikidata-entities-20260201", [("Q1", "P279", "Q2")])
        wikidata.import_claims(self.conn, old)
        wikidata.import_claims(self.conn, new)
        rows = self.conn.execute("SELECT s.corpus, c.predicate, c.superseded_at IS NOT NULL FROM claim c"
                                 " JOIN source s ON s.sha512 = c.source_sha512 ORDER BY 1, 2").fetchall()
        self.assertEqual([tuple(r) for r in rows], [
            ("wikidata-entities-20260101", "wd/P279", 1), ("wikidata-entities-20260101", "wd/P361", 1),
            ("wikidata-entities-20260201", "wd/P279", 0)])


class DeprecationTests(unittest.TestCase):
    def test_removed_concept_is_deprecated_and_ledgered(self):
        tmp = Path(tempfile.mkdtemp())
        conn = fresh(tmp)
        conn.execute("INSERT INTO scheme(id, title, origin) VALUES ('t', 'T', 'authored')")
        header = "\t".join(CONCEPT_COLUMNS) + "\n"
        seed = tmp / "seed" / "compendium" / "t.tsv"
        seed.parent.mkdir(parents=True)
        seed.write_text(header + "a\t\tA\t\t\t\t\t\t\nb\ta\tB\t\t\t\t\t\t\n", encoding="utf-8")
        compendium.load_concepts(conn, {"t": read_scheme("t", [seed])})
        seed.write_text(header + "a\t\tA\t\t\t\t\t\t\n", encoding="utf-8")
        stats = compendium.load_concepts(conn, {"t": read_scheme("t", [seed])})
        self.assertEqual(stats["deprecated"], 1)
        self.assertEqual(conn.execute("SELECT status FROM concept WHERE id = 't/b'").fetchone()[0], "deprecated")
        self.assertEqual(conn.execute("SELECT count(*) FROM broader").fetchone()[0], 0,
                         "edges from the earlier seed version are regenerated, not left behind")
        self.assertEqual(conn.execute("SELECT count(*) FROM ledger WHERE action = 'deprecate'").fetchone()[0], 1)
        ok, _, msg = ledger.verify(conn)
        self.assertTrue(ok, msg)


if __name__ == "__main__":
    unittest.main()
