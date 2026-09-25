"""The retrieval evaluation: metrics, fusion, the hidden language, and a stored run over a real build."""
import tempfile
import unittest
from pathlib import Path

from acatalogue import db as dbm
from acatalogue.evaluate import Lexical, paired_test, per_query, queries, rrf, run


class MetricTests(unittest.TestCase):
    def test_per_query(self):
        self.assertEqual(per_query(1), {"mrr@10": 1.0, "recall@10": 1.0, "ndcg@10": 1.0})
        m = per_query(3)
        self.assertAlmostEqual(m["mrr@10"], 1 / 3)
        self.assertAlmostEqual(m["ndcg@10"], 0.5)                 # 1 / log2(3 + 1)
        self.assertEqual(per_query(11), {"mrr@10": 0.0, "recall@10": 0.0, "ndcg@10": 0.0})
        self.assertEqual(per_query(None)["recall@10"], 0.0)

    def test_rrf(self):
        # a is 1st and 3rd, b is 2nd and 1st: a = 1/61 + 1/63, b = 1/62 + 1/61
        self.assertEqual(rrf(["a", "b", "c"], ["b", "x", "a"])[:2], ["b", "a"])

    def test_a_system_against_itself(self):
        qs = [{"qid": i, "lang": "tr" if i % 2 else "zh"} for i in range(20)]
        ranks = {i: (i % 4) + 1 for i in range(20)}
        t = paired_test(qs, ranks, ranks, 500, 1)
        self.assertEqual(t["diff"], 0.0)
        self.assertEqual(t["p"], 1.0)


class DenseHidingTests(unittest.TestCase):
    """Dense ranking on a tiny synthetic space: a label in the query's language never contributes."""

    def make(self, keep_rows):
        import numpy as np
        from acatalogue.evaluate import Dense
        M = np.array([[1, 0, 0, 0], [0.9, 0.1, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]], dtype=np.float32)
        lang = np.array(["tr", "de", "de", "zh"], dtype=object)
        concept = np.array(["acat/a", "acat/a", "acat/b", "acat/c"], dtype=object)
        d = Dense.__new__(Dense)
        d.M, d.lang, d.concept = M[keep_rows], lang[keep_rows], concept[keep_rows]
        d.Q = np.array([[1, 0, 0, 0], [0, 0, 1, 0]], dtype=np.float32)
        return d

    def test_hidden_equals_absent(self):
        qs = [{"qid": 0, "lang": "tr"}, {"qid": 1, "lang": "zh"}]
        hidden = self.make([0, 1, 2, 3]).rank_all(qs)
        absent_tr = self.make([1, 2, 3]).rank_all(qs[:1])
        absent_zh = self.make([0, 1, 2]).rank_all(qs[1:])
        self.assertEqual(hidden[0], absent_tr[0])
        self.assertEqual(hidden[1], absent_zh[0])
        self.assertEqual(hidden[0][0], "acat/a", "found through its German label")
        self.assertNotIn("acat/c", hidden[1], "its only label is in the hidden language")


class RunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from acatalogue.build import build
        cls.tmp = Path(tempfile.mkdtemp())
        build(cls.tmp / "cat.sqlite", verbose=False)
        cls.conn = dbm.connect(cls.tmp / "cat.sqlite")

    def test_the_query_language_is_hidden(self):
        c = self.conn
        c.execute("INSERT INTO concept(id, scheme, code, label) VALUES ('acat/zz-test', 'acat', 'zz-test', 'Zz test')")
        c.execute("INSERT INTO label(concept_id, lang, kind, text) VALUES ('acat/zz-test', 'tr', 'pref', 'Qwxzbenzersiz')")
        for t in ("label_fts", ):
            c.execute(f"INSERT INTO {t}({t}) VALUES ('rebuild')")
        from acatalogue.textkeys import fold_key
        lid = c.execute("SELECT id FROM label WHERE concept_id = 'acat/zz-test'").fetchone()[0]
        c.execute("INSERT INTO label_key(rowid, k) VALUES (?, ?)", (lid, fold_key("Qwxzbenzersiz")))
        q = next(x for x in queries(c, ("tr",)) if x["target"] == "acat/zz-test")
        lex = Lexical(c)
        self.assertNotIn("acat/zz-test", lex.words(q), "its only matching label is in the hidden language")
        self.assertNotIn("acat/zz-test", lex.trigram(q))
        # the same name as another language's label: now it must be found, first
        c.execute("INSERT INTO label(concept_id, lang, kind, text) VALUES ('acat/zz-test', 'de', 'alt', 'Qwxzbenzersiz')")
        c.execute("INSERT INTO label_fts(label_fts) VALUES ('rebuild')")
        lid2 = c.execute("SELECT id FROM label WHERE concept_id = 'acat/zz-test' AND lang = 'de'").fetchone()[0]
        c.execute("INSERT INTO label_key(rowid, k) VALUES (?, ?)", (lid2, fold_key("Qwxzbenzersiz")))
        self.assertEqual(lex.words(q)[0], "acat/zz-test")
        self.assertEqual(lex.trigram(q)[0], "acat/zz-test")
        c.rollback()

    def test_a_stored_run(self):
        res = run(self.conn, ("tr", "zh"), ("words", "trigram", "lsa", "rrf-lexical"), boot=50, perms=200,
                  progress=lambda *_: None)
        rid = res["run_id"]
        c = self.conn
        nq = c.execute("SELECT count(*) FROM eval_query WHERE run_id = ?", (rid,)).fetchone()[0]
        self.assertEqual(nq, res["queries"])
        self.assertGreater(nq, 800)
        self.assertEqual(c.execute("SELECT count(*) FROM eval_rank WHERE run_id = ?", (rid,)).fetchone()[0], 4 * nq)
        for s in ("words", "trigram", "lsa", "rrf-lexical"):
            v, lo, hi = c.execute("SELECT value, lo, hi FROM eval_metric WHERE run_id = ? AND system = ? AND lang = ''"
                                  " AND metric = 'mrr@10'", (rid, s)).fetchone()
            self.assertLessEqual(lo, v)
            self.assertLessEqual(v, hi)
        worst = c.execute("SELECT metric FROM eval_metric WHERE run_id = ? AND lang = '*worst' AND metric LIKE 'lang:%'"
                          " AND system = 'words'", (rid,)).fetchone()[0]
        self.assertIn(worst, ("lang:tr", "lang:zh"))
        self.assertTrue(res["tests"])
        self.assertEqual(c.execute("SELECT count(*) FROM ledger WHERE action = 'eval-retrieval'").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
