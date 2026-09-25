"""The SQL grepper: pure helpers, and an integration run over a catalogue built from the committed corpora."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from acatalogue import db as dbm
from acatalogue.grep import (GrepError, grep, grep_any, parts_from_markers, parts_from_spans, plain_words,
                             required_literal)
from acatalogue.sources.wikidata import _JUNK


class HelperTests(unittest.TestCase):
    def test_required_literal_is_conservative(self):
        self.assertEqual(required_literal("Leviath[a-z]+"), "Leviath")
        self.assertEqual(required_literal("xyz(abc|def)"), "xyz")
        self.assertIsNone(required_literal("Leviathan|Behemoth"))     # top-level alternation
        self.assertIsNone(required_literal("(?i)physics"))            # case-insensitive
        self.assertIsNone(required_literal("abc?d"))                  # no required run of 3
        self.assertIsNone(required_literal("(unclosed"))

    def test_parts(self):
        self.assertEqual(parts_from_markers("a \x02b\x03 c"), [{"t": "a ", "m": False}, {"t": "b", "m": True},
                                                              {"t": " c", "m": False}])
        text = "the sky god Tengri and the sky"
        parts = parts_from_spans(text, [(4, 7), (27, 30)], context=100)
        self.assertEqual("".join(p["t"] for p in parts), text)
        self.assertEqual([p["t"] for p in parts if p["m"]], ["sky", "sky"])

    def test_plain_words_quotes_everything(self):
        self.assertEqual(plain_words('Indo-European "x'), '"Indo-European" """x"')

    def test_junk_filter_does_not_hide_real_topics(self):
        cases = {
            "study of the synthesis and behavior of inorganic and organometallic compounds": False,
            "process for reproducing text and images using a master form or template": False,
            "stories, books, magazines, and poems that are primarily written for children": False,
            "category of architecture based on local needs": False,
            "building in Dekemhare, Eritrea": True,
            "1962 film produced by James Beveridge": True,
            "Wikimedia disambiguation page": True,
            "Swedish term in coinage": True,
        }
        for desc, junk in cases.items():
            with self.subTest(desc=desc):
                self.assertEqual(bool(_JUNK.search(desc)), junk)


class CatalogueTests(unittest.TestCase):
    """Builds a fresh catalogue from seed/ and corpora/ (no network) and searches it."""

    @classmethod
    def setUpClass(cls):
        from acatalogue.build import build
        cls.tmp = Path(tempfile.mkdtemp())
        cls.db = cls.tmp / "cat.sqlite"
        cls.report = build(cls.db, verbose=False)
        cls.conn = dbm.connect(cls.db, readonly=True)

    def test_build_links_resolve(self):
        self.assertEqual(self.report["links"]["facets_dangling"], [])
        self.assertEqual(self.report["links"]["mappings_dangling"], [])
        self.assertEqual(self.report["external"]["unverified"], [])

    def test_words(self):
        res = grep(self.conn, "quantum", scope="concepts")
        self.assertIn("acat/quantum-physics", [h.target for h in res.hits])
        self.assertTrue(res.sql and "MATCH" in res.sql[0])

    def test_bad_fts_syntax_falls_back(self):
        res = grep(self.conn, "Indo-European", scope="concepts")
        self.assertIn("acat/indo-european-languages", [h.target for h in res.hits])
        self.assertTrue(res.notes)

    def test_substring_finds_labels_in_other_scripts(self):
        tr = grep(self.conn, "fizik", mode="substring", scope="labels", lang="tr")
        self.assertIn("acat/physics", [h.target for h in tr.hits])
        zh = grep(self.conn, "物理", mode="substring", scope="labels")   # two characters: full scan
        self.assertIn("acat/physics", [h.target for h in zh.hits])

    def test_regex_prefilter_and_scan_agree(self):
        a = grep(self.conn, "Leviath[a-z]+", mode="regex", scope="concepts")
        b = grep(self.conn, "(Leviath[a-z]+|Behemoth)", mode="regex", scope="concepts")
        self.assertIn("acat/legendary-creatures", [h.target for h in a.hits])
        self.assertIn("acat/legendary-creatures", [h.target for h in b.hits])
        self.assertIn("MATCH", a.sql[0])
        self.assertNotIn("MATCH", b.sql[0])

    def test_under_limits_to_subtree(self):
        res = grep(self.conn, "sky", scope="passages", under="acat/belief", limit=50)
        self.assertTrue(res.hits)
        belief = {r[0] for r in self.conn.execute(
            "WITH RECURSIVE sub(id) AS (SELECT 'acat/belief' UNION SELECT b.child FROM broader b JOIN sub"
            " ON b.parent = sub.id) SELECT id FROM sub")}
        for h in res.hits:
            self.assertTrue(set(h.concepts) & belief, h.target)

    def test_invalid_regex(self):
        with self.assertRaises(GrepError):
            grep(self.conn, "(unclosed", mode="regex")

    def test_grep_any_sqlite_file(self):
        hits, sqls = grep_any(self.db, "Tengrism", tables=["concept"])
        self.assertTrue(any(h.table == "concept" for h in hits))
        self.assertTrue(all(s.startswith("SELECT") for s in sqls))

    def test_http_api(self):
        from http.server import ThreadingHTTPServer
        from acatalogue.server import Handler, _Cache
        handler = type("H", (Handler,), {"db_path": self.db, "cache": _Cache(self.db),
                                         "log_message": lambda *a: None})
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        try:
            g = json.load(urllib.request.urlopen(base + "/api/graph"))
            self.assertGreater(len(g["nodes"]), 900)
            for e in g["edges"][:200]:
                self.assertIn(e["k"], {"broader", "related", "mapping", "semantic"})
            n = json.load(urllib.request.urlopen(base + "/api/node?id=acat/physics"))
            self.assertEqual(n["id"], "acat/physics")
            with self.assertRaises(urllib.error.HTTPError) as err:
                urllib.request.urlopen(base + "/api/grep?q=(bad&mode=regex")
            self.assertEqual(err.exception.code, 400)
        finally:
            httpd.shutdown()


if __name__ == "__main__":
    unittest.main()
