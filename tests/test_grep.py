"""The SQL grepper: pure helpers, and an integration run over a catalogue built from the committed corpora."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import random
import re
import shutil

from acatalogue import db as dbm
from acatalogue.grep import GrepError, grep, grep_any, parts_from_markers, parts_from_spans, plain_words
from acatalogue.sources.wikidata import _JUNK
from acatalogue.textkeys import (closure_violations, cjk_bigrams, fold_key, icontains, literal_query, nfc,
                                 trigram_query)


class TextKeyTests(unittest.TestCase):
    def test_key_fold_is_closed_over_all_of_unicode(self):
        self.assertEqual(closure_violations(), [])

    def test_one_definition_of_case_insensitive(self):
        for text, needle in [("İstanbul", "istanbul"), ("arı kovanı", "ARI"), ("ISPARTA", "ısparta"),
                             ("Kelvin 5K", "5k"), ("Café", "CAFÉ")]:
            with self.subTest(text=text, needle=needle):
                self.assertEqual(icontains(text, needle),
                                 re.search(re.escape(needle), text, re.IGNORECASE) is not None)
                if icontains(text, needle):
                    self.assertIn(fold_key(nfc(needle)), fold_key(nfc(text)))

    def test_nfc(self):
        self.assertTrue(icontains("Café", "Café"))              # decomposed text, composed needle

    def test_trigram_queries(self):
        self.assertIn("levi", trigram_query("Leviath[a-z]+"))
        self.assertIn(" OR ", trigram_query("Leviathan|Behemoth"))    # alternation is indexable now
        self.assertIsNotNone(trigram_query("(?i)physics"))            # so is case-insensitivity
        self.assertEqual(trigram_query("abc?d"), '("abcd" OR "abd")')
        self.assertIsNone(trigram_query("a.*b"))                      # nothing required: scan
        self.assertIsNone(trigram_query("(unclosed"))
        self.assertIsNone(literal_query("ab"))                        # never a string under 3 characters

    def test_cjk_pairs(self):
        self.assertEqual(cjk_bigrams("物理学").split(), ["物理", "理学"])


class HelperTests(unittest.TestCase):

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
        c = grep(self.conn, "Levi.*than", mode="regex", scope="concepts")
        for r in (a, b, c):
            self.assertIn("acat/legendary-creatures", [h.target for h in r.hits])
        self.assertIn("MATCH", a.sql[0])
        self.assertIn("MATCH", b.sql[0])                             # alternation: OR of trigram sets

    def test_dotted_capital_i(self):
        texts = [t for (t,) in self.conn.execute("SELECT text FROM label WHERE text LIKE '%İ%' LIMIT 5")]
        self.assertTrue(texts)
        needle = texts[0].replace("İ", "i")[:8]
        res = grep(self.conn, needle, mode="substring", scope="labels", limit=100)
        self.assertTrue(any(needle.casefold()[:3] in h.snippet.replace("İ", "i").casefold() for h in res.hits))

    def test_combining_marks_stay_inside_words(self):
        res = grep(self.conn, "विज्ञान", scope="labels", limit=20)
        self.assertIn("acat/science", [h.target for h in res.hits])

    def test_two_character_cjk_words(self):
        words = grep(self.conn, "物理", scope="labels", limit=20)
        sub = grep(self.conn, "物理", mode="substring", scope="labels", limit=20)
        self.assertIn("acat/physics", [h.target for h in words.hits])
        self.assertIn("acat/physics", [h.target for h in sub.hits])
        self.assertIn("label_cjk", sub.sql[0])

    def test_no_missed_matches_against_brute_force(self):
        """Property test: the indexed paths return every label a plain Python scan finds."""
        labels = self.conn.execute("SELECT l.concept_id, l.text FROM label l JOIN concept c ON c.id = l.concept_id"
                                   " WHERE c.scheme <> 'wd'").fetchall()
        pool = [t for _, t in labels if len(t) >= 6]
        rnd = random.Random(20260925)

        def frag():
            s = rnd.choice(pool)
            i = rnd.randrange(0, len(s) - 3)
            return s[i:i + rnd.randint(2, 6)]
        compared = 0
        for _ in range(60):
            needle = rnd.choice([str.upper, str.lower, str.swapcase, lambda s: s])(frag())
            hits = grep(self.conn, needle, mode="substring", scope="labels", limit=500).hits
            if len(hits) < 500:                        # the limit caps rows; compare only uncapped answers
                want = {c for c, t in labels if icontains(t, needle)}
                self.assertEqual(want - {h.target for h in hits}, set(), f"substring {needle!r} missed matches")
                compared += 1
            a, b = re.escape(frag()), re.escape(frag())
            pattern = rnd.choice([a, f"(?i){a}", f"{a}|{b}", f"{a}.{{0,5}}{b}", f"(?:{a})+", f"{a}\\w*"])
            rx = re.compile(pattern)
            hits = grep(self.conn, pattern, mode="regex", scope="labels", limit=500).hits
            if len(hits) < 500:
                want = {c for c, t in labels if rx.search(nfc(t))}
                self.assertEqual(want - {h.target for h in hits}, set(), f"regex {pattern!r} missed matches")
                compared += 1
        self.assertGreater(compared, 60, "too few uncapped cases to mean anything")

    def test_label_indexes_survive_vacuum(self):
        copy = self.tmp / "vacuumed.sqlite"
        shutil.copy(self.db, copy)
        w = dbm.connect(copy)
        w.execute("VACUUM")
        for t in ("label_fts", "passage_fts"):                         # index still agrees with its content
            w.execute(f"INSERT INTO {t}({t}, rank) VALUES ('integrity-check', 1)")
        w.close()
        c = dbm.connect(copy, readonly=True)
        for cid, text in c.execute("SELECT concept_id, text FROM label WHERE lang = 'tr' ORDER BY id LIMIT 30"):
            if len(text) >= 3:
                self.assertIn(cid, [h.target for h in grep(c, text, mode="substring", scope="labels", limit=500).hits])

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
