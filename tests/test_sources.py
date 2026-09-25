"""The source pipeline end to end, on a local server: select, download, seal, convert, integrate into a
real catalogue build; run again (nothing repeated); link across sources; deselect (retired, not deleted)."""
import hashlib
import json
import os
import tempfile
import threading
import unittest
import zipfile
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from acatalogue import db as dbm, registry as registry_mod
from acatalogue.integrate import Resolver
from acatalogue.pipeline import Pipeline, integrate_store
from acatalogue.registry import COLUMNS, FILE_COLUMNS, PRESET_COLUMNS, conflicts, read
from acatalogue.store import Store

VOCAB = "\n".join(f"<http://ex.org/v/{a}> <http://www.w3.org/{b}> {c} ." for a, b, c in [
    ("c1", "1999/02/22-rdf-syntax-ns#type", "<http://www.w3.org/2004/02/skos/core#Concept>"),
    ("c1", "2004/02/skos/core#prefLabel", '"Rivers"@en'),
    ("c1", "2004/02/skos/core#prefLabel", '"Nehirler"@tr'),
    ("c1", "2004/02/skos/core#definition", '"Natural flowing watercourses."@en'),
    ("c2", "1999/02/22-rdf-syntax-ns#type", "<http://www.w3.org/2004/02/skos/core#Concept>"),
    ("c2", "2004/02/skos/core#prefLabel", '"Deltas"@en'),
    ("c2", "2004/02/skos/core#hiddenLabel", '"Deltaa"@en'),
    ("c2", "2004/02/skos/core#broader", "<http://ex.org/v/c1>"),
    ("c2", "2004/02/skos/core#exactMatch", "<http://www.wikidata.org/entity/Q43197>"),
    ("c2", "2004/02/skos/core#closeMatch", "<https://places.example/p/7>"),
]) + "\n"


def tsv(path: Path, columns, rows) -> None:
    path.write_text("\t".join(columns) + "\n" + "".join("\t".join(r.get(c, "") for c in columns) + "\n" for r in rows),
                    encoding="utf-8")


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from acatalogue.build import build
        cls.tmp = Path(cls.enterClassContext(tempfile.TemporaryDirectory()))
        www = cls.tmp / "www"
        www.mkdir()
        (www / "vocab.nt").write_text(VOCAB)
        with zipfile.ZipFile(www / "places.zip", "w") as z:
            z.writestr("places.csv", "id,name,parent,river\n7,Nile Delta,,http://ex.org/v/c2\n8,Rosetta,7,\n")
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(_Quiet, directory=str(www)))
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls.reg_dir = cls.tmp / "sources"
        cls.reg_dir.mkdir()
        common = {"license": "CC0", "reviewer": "test", "publisher": "Example", "domains": "acat/earth"}
        tsv(cls.reg_dir / "registry.tsv", COLUMNS, [
            {"id": "exvocab", "title": "Example vocabulary", "converter": "rdf", "scheme": "exvocab",
             "iri_prefixes": "http://ex.org/v/", "wikidata_property": "P9999", "integrate": "full", **common},
            {"id": "explaces", "title": "Example places", "converter": "csv", "scheme": "explaces",
             "iri_prefixes": "https://places.example/p/", "integrate": "full",
             "options": json.dumps({"tables": [{"members": "places.csv", "code": "id", "kind": "Place",
                                                "facet": "kind/place", "labels": [{"column": "name", "lang": "en"}],
                                                "broader": [{"column": "parent"}],
                                                "links": [{"column": "river", "name": "river", "map": "relatedMatch"}]}]}),
             **common},
            {"id": "explaces-big", "title": "Example places, all", "converter": "csv", "scheme": "explaces", **common}])
        vocab_sha = hashlib.sha256((www / "vocab.nt").read_bytes()).hexdigest()
        tsv(cls.reg_dir / "files.tsv", FILE_COLUMNS, [
            {"source": "exvocab", "name": "vocab.nt", "url": f"{base}/vocab.nt", "checksum": f"sha256:{vocab_sha}"},
            {"source": "explaces", "name": "places.zip", "url": f"{base}/places.zip"},
            {"source": "explaces-big", "name": "places.zip", "url": f"{base}/places.zip"}])
        tsv(cls.reg_dir / "presets.tsv", PRESET_COLUMNS, [{"preset": "starter", "source": "exvocab"},
                                                          {"preset": "starter", "source": "explaces"}])
        cls.db = cls.tmp / "cat.sqlite"
        cls.store_dir = cls.tmp / "store"
        cls.env = mock.patch.dict(os.environ, {"ACAT_STORE": str(cls.store_dir)})
        cls.env.start()
        cls.regpatch = mock.patch.object(registry_mod, "SOURCE_DIR", cls.reg_dir)
        cls.regpatch.start()
        build(cls.db, verbose=False)                   # the store is still empty: nothing integrated
        cls.store = Store(cls.store_dir)
        cls.reg = read(cls.store)
        for s in cls.reg.expand(["preset:starter"]):
            cls.store.select(s, via="preset:starter")
        cls.log = []
        cls.pipe = Pipeline(cls.store, cls.reg, db_path=cls.db, min_interval=0, progress=cls.log.append)
        cls.first = cls.pipe.run(list(cls.store.selected()))

    @classmethod
    def tearDownClass(cls):
        cls.store.close()
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.env.stop()
        cls.regpatch.stop()

    def conn(self):
        return dbm.connect(self.db, readonly=True)

    def test_registry_is_valid_and_schemes_do_not_collide(self):
        self.assertEqual(self.reg.problems, [])
        self.assertTrue(conflicts(self.reg, ["explaces", "explaces-big"]), "two sizes of one scheme")

    def test_files_are_verified_sealed_and_converted(self):
        d = {r["name"]: r for r in self.store.conn.execute("SELECT * FROM download")}
        self.assertEqual(d["vocab.nt"]["checksum_ok"], 1)
        from acatalogue.corpusfile import CorpusFile
        snap = self.store.conn.execute("SELECT snapshot FROM download WHERE name = 'vocab.nt'").fetchone()[0]
        c = CorpusFile(self.store.corpus_path(snap), readonly=True)
        self.assertTrue(c.sealed)
        self.assertTrue(c.verify()[0])
        c.close()
        jobs = {(r["source"], r["stage"]): r["state"] for r in self.store.conn.execute("SELECT * FROM job")}
        self.assertEqual(jobs[("exvocab", "convert")], "done")
        self.assertEqual(jobs[("explaces", "integrate")], "done")

    def test_concepts_names_and_hierarchy_in_the_catalogue(self):
        c = self.conn()
        self.assertEqual(c.execute("SELECT label, scope_note FROM concept WHERE id = 'exvocab/c1'").fetchone()[:],
                         ("Rivers", "Natural flowing watercourses."))
        self.assertEqual(c.execute("SELECT count(*) FROM broader WHERE child = 'exvocab/c2' AND parent = 'exvocab/c1'")
                         .fetchone()[0], 1)
        self.assertEqual(c.execute("SELECT kind FROM label WHERE concept_id = 'exvocab/c2' AND text = 'Deltaa'")
                         .fetchone()[0], "hidden")
        self.assertEqual(c.execute("SELECT kind FROM label WHERE concept_id = 'exvocab/c1' AND lang = 'en'"
                                   " AND text LIKE 'Natural%'").fetchone()[0], "desc")
        self.assertEqual(c.execute("SELECT count(*) FROM facet WHERE concept_id = 'explaces/7' AND facet_id = 'kind/place'")
                         .fetchone()[0], 1)
        # the grepper finds them: the search indexes were rebuilt
        from acatalogue.grep import grep
        res = grep(c, "Nehirler", scope="labels")
        self.assertIn("exvocab/c1", [cid for h in res.hits for cid in [h.target, *h.concepts]])

    def test_links_across_sources_resolve_and_stay_proposed(self):
        c = self.conn()
        m = {(r[0], r[1]): (r[2], r[3], r[4]) for r in c.execute(
            "SELECT from_id, to_id, relation, status, method FROM mapping WHERE from_id LIKE 'ex%'")}
        self.assertEqual(m[("exvocab/c2", "wd/Q43197")][:2], ("exactMatch", "proposed"))
        self.assertEqual(m[("exvocab/c2", "explaces/7")][0], "closeMatch", "an IRI of another selected source")
        self.assertEqual(m[("explaces/7", "exvocab/c2")][0], "relatedMatch")
        self.assertTrue(all(v[1] == "proposed" for v in m.values()), "a source's own links are its claims")

    def test_every_integration_is_recorded_and_ledgered(self):
        c = self.conn()
        rows = c.execute("SELECT scheme, mode, lean_sha512 FROM v_lean_source ORDER BY scheme").fetchall()
        self.assertEqual([r[:2] for r in rows], [("explaces", "full"), ("exvocab", "full")])
        for _, _, sha in rows:
            self.assertEqual(c.execute("SELECT kind FROM source WHERE sha512 = ?", (sha,)).fetchone()[0], "file")
        self.assertEqual(c.execute("SELECT count(*) FROM ledger WHERE action = 'integrate-source'").fetchone()[0], 2)
        ok, _, msg = __import__("acatalogue.ledger", fromlist=["verify"]).verify(c)
        self.assertTrue(ok, msg)

    def test_a_second_run_repeats_nothing(self):
        before = self.store.conn.execute("SELECT count(*) FROM download").fetchone()[0]
        log = []
        again = Pipeline(self.store, self.reg, db_path=self.db, min_interval=0, progress=log.append).run(
            list(self.store.selected()))
        self.assertEqual(self.store.conn.execute("SELECT count(*) FROM download").fetchone()[0], before)
        self.assertTrue(any("converted already" in x for x in log))
        self.assertTrue(all(v.get("skipped") for v in again["_integration"].values()))

    def test_resolver(self):
        r = Resolver([{"id": "go", "iri_prefixes": "http://purl.obolibrary.org/obo/GO_|GO_{rest}",
                       "curie_prefixes": "GO|GO_{rest} MSH", "wikidata_property": "P686|GO_{rest}"},
                      {"id": "yso", "wikidata_property": "P2347|p{rest}"},
                      {"id": "geonames", "iri_prefixes": "https://sws.geonames.org/"}])
        self.assertEqual(r("http://purl.obolibrary.org/obo/GO_0008150"), "go/GO_0008150")
        self.assertEqual(r("GO:0008150"), "go/GO_0008150")
        self.assertEqual(r("MSH:D002453"), "go/D002453")
        self.assertEqual(r("P686:GO:0007568"), "go/GO_0007568")          # Wikidata's own value form
        self.assertEqual(r("P2347:10238"), "yso/p10238")
        self.assertEqual(r("https://sws.geonames.org/745044/"), "geonames/745044")
        self.assertEqual(r("http://www.wikidata.org/entity/Q1"), "wd/Q1")
        self.assertIsNone(r("https://unknown.example/x"))

    def test_y_attach_mode_reads_in_place(self):
        from acatalogue.leansearch import record, search
        from acatalogue.views import linked_sources, node, source_node
        conn = dbm.connect(self.db)
        try:
            srcs = {x["id"] for x in linked_sources(conn, "exvocab/c2")}
            self.assertIn("explaces/7", srcs, "a concept shows where else it is")
            self.store.select("explaces", mode="attach")
            conn.execute("BEGIN")
            integrate_store(conn, say=lambda *_: None)
            conn.commit()
            self.assertEqual(conn.execute("SELECT status FROM concept WHERE id = 'explaces/7'").fetchone()[0],
                             "deprecated", "attached: the catalogue carries none of it")
            hits = search(conn, "Nile Delta")
            self.assertEqual(hits[0]["id"], "explaces/7")
            self.assertEqual(hits[0]["mode"], "attach")
            rec = record(conn, "explaces/8")
            self.assertEqual([b["id"] for b in rec["broader"]], ["explaces/7"])
            self.assertEqual(source_node(conn, "explaces/7")["label"], "Nile Delta")
            self.assertIsNotNone(node(conn, "exvocab/c2"))
        finally:
            self.store.select("explaces", mode="full")
            conn.close()
        self.store.conn.execute("UPDATE selection SET mode = 'full' WHERE source = 'explaces'")
        conn = dbm.connect(self.db)
        conn.execute("BEGIN")
        integrate_store(conn, say=lambda *_: None)
        conn.commit()
        self.assertEqual(conn.execute("SELECT status FROM concept WHERE id = 'explaces/7'").fetchone()[0], "active")
        conn.close()

    def test_z_deselecting_retires_without_deleting(self):
        self.store.deselect("explaces")
        conn = dbm.connect(self.db)
        conn.execute("BEGIN")
        out = integrate_store(conn, say=lambda *_: None)
        conn.commit()
        self.assertIn("explaces", out)
        self.assertEqual(conn.execute("SELECT status FROM concept WHERE id = 'explaces/7'").fetchone()[0], "deprecated")
        self.assertEqual(conn.execute("SELECT count(*) FROM label WHERE concept_id = 'explaces/7'").fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT mode FROM v_lean_source WHERE scheme = 'explaces'").fetchone()[0], "removed")
        self.assertEqual(conn.execute("SELECT count(*) FROM concept WHERE scheme = 'explaces'").fetchone()[0], 2,
                         "concepts are never deleted")
        self.store.select("explaces")                   # and back: the same lean file, carried again
        conn.execute("BEGIN")
        integrate_store(conn, say=lambda *_: None)
        conn.commit()
        self.assertEqual(conn.execute("SELECT status FROM concept WHERE id = 'explaces/7'").fetchone()[0], "active")
        conn.close()


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class AddedSourceTests(unittest.TestCase):
    def test_a_users_own_file(self):
        from acatalogue.cli import main
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        csv_path = tmp / "notes.csv"
        csv_path.write_text("id,title\na,First note\nb,Second note\n")
        store = tmp / "store"
        opts = json.dumps({"tables": [{"code": "id", "labels": [{"column": "title", "lang": "en"}]}]})
        with mock.patch.dict(os.environ, {"ACAT_STORE": str(store)}):
            rc = main(["--db", str(tmp / "none.sqlite"), "sources", "add", "mynotes", "--path", str(csv_path),
                       "--converter", "csv", "--options", opts, "--license", "mine"])
            self.assertEqual(rc, 0)
            s = Store(store)
            reg = read(s)
            self.assertEqual(reg.sources["mynotes"]["origin"], "user")
            self.assertIn("mynotes", s.selected())
            res = Pipeline(s, reg, integrate=False, min_interval=0, progress=lambda *_: None).run(["mynotes"])
            self.assertTrue(res["mynotes"]["lean"].exists())
            s.close()


if __name__ == "__main__":
    unittest.main()
