"""The retrieval evaluation: metrics, fusion, the hidden language, and a stored run over a real build."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
        M = np.array([[1, 0, 0, 0], [0.9, 0.1, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0.1, 0.9, 0]],
                     dtype=np.float32)
        lang = np.array(["tr", "de", "de", "zh", "zh-hans"], dtype=object)
        concept = np.array(["acat/a", "acat/a", "acat/b", "acat/c", "acat/c"], dtype=object)
        d = Dense.__new__(Dense)
        d.M, d.lang, d.concept = M[keep_rows], lang[keep_rows], concept[keep_rows]
        # the two query vectors differ in every coordinate that matters, so using the wrong one shows
        d.Q = np.array([[1, 0, 0, 0], [0, 0, 1, 0]], dtype=np.float32)
        d.row = {0: 0, 1: 1}
        return d

    def test_hidden_equals_absent(self):
        qs = [{"qid": 0, "lang": "tr"}, {"qid": 1, "lang": "zh"}]
        hidden = self.make([0, 1, 2, 3, 4]).rank_all(qs)
        absent_tr = self.make([1, 2, 3, 4]).rank_all(qs[:1])
        absent_zh = self.make([0, 1, 2]).rank_all(qs[1:])              # zh and its variant zh-hans left out
        self.assertEqual(hidden[0], absent_tr[0])
        self.assertEqual(hidden[1], absent_zh[0])
        self.assertEqual(hidden[0][0], "acat/a", "found through its German label")
        self.assertNotIn("acat/c", hidden[1], "its labels are in the hidden language and a variant of it")

    def test_queries_are_scored_with_their_own_vector(self):
        d = self.make([0, 1, 2, 3, 4])
        alone = d.rank_all([{"qid": 1, "lang": "tr"}])[0]
        self.assertEqual(alone[0], "acat/c", "query 1's vector points at acat/c's zh labels")


class RunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from acatalogue.build import build
        cls.tmp = Path(cls.enterClassContext(tempfile.TemporaryDirectory()))
        with mock.patch.dict(os.environ, {"ACAT_STORE": str(cls.tmp / "store")}):   # never this machine's downloads
            build(cls.tmp / "cat.sqlite", verbose=False)
        cls.conn = dbm.connect(cls.tmp / "cat.sqlite")

    def add(self, cid, labels):
        c = self.conn
        c.execute("INSERT INTO concept(id, scheme, code, label) VALUES (?, 'acat', ?, ?)", (cid, cid[5:], cid))
        c.executemany("INSERT INTO label(concept_id, lang, kind, text) VALUES (?,?,?,?)",
                      [(cid, lang, kind, text) for lang, kind, text in labels])

    def found(self, lang, target):
        """(words, trigram) rankings of `target`'s query in `lang`, over an index hiding `lang`."""
        q = next(x for x in queries(self.conn, (lang,)) if x["target"] == target)
        lex = Lexical(self.conn)
        lex.hide(lang)
        return lex.words(q), lex.trigram(q)

    def test_the_query_language_and_its_variants_are_hidden(self):
        try:
            self.add("acat/zz-test", [("tr", "pref", "Qwxzbenzersiz")])
            self.add("acat/zz-cjk", [("zh", "pref", "奇異測詞甲乙"), ("zh-hans", "alt", "奇異測詞甲乙"),
                                     ("zh-tw", "alt", "奇異測詞甲乙")])
            for words, tri in (self.found("tr", "acat/zz-test"), self.found("zh", "acat/zz-cjk")):
                self.assertNotIn("acat/zz-test", words + tri, "its only matching label is hidden")
                self.assertNotIn("acat/zz-cjk", words + tri, "zh hides zh-hans and zh-tw")
            # the same name as another language's label: now it must be found, first
            self.conn.execute("INSERT INTO label(concept_id, lang, kind, text) VALUES"
                              " ('acat/zz-test', 'de', 'alt', 'Qwxzbenzersiz'), ('acat/zz-cjk', 'ja', 'alt', '奇異測詞甲乙')")
            for target, lang in (("acat/zz-test", "tr"), ("acat/zz-cjk", "zh")):
                words, tri = self.found(lang, target)
                self.assertEqual(words[0], target)
                self.assertEqual(tri[0], target)
        finally:
            self.conn.rollback()

    def test_hidden_labels_are_absent_from_the_index(self):
        lex = Lexical(self.conn)
        n = lex.hide("zh")
        leaked = self.conn.execute("SELECT count(*) FROM temp.ev_words WHERE rowid IN (SELECT id FROM label"
                                   " WHERE lang = 'zh' OR lang LIKE 'zh-%')").fetchone()[0]
        self.assertEqual(leaked, 0)
        rows = self.conn.execute("SELECT count(*) FROM temp.ev_words").fetchone()[0]
        self.assertEqual(rows, n)                                    # bm25 counts only these
        self.assertEqual(n, sum(1 for r in lex.labels if not (r[2] == "zh" or r[2].startswith("zh-"))))
        self.assertLess(n, len(lex.labels))

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
        params = json.loads(c.execute("SELECT params FROM eval_run WHERE id = ?", (rid,)).fetchone()[0])
        self.assertIn("variants", params["hidden"])
        self.assertEqual(params["langs_with_queries"], ["tr", "zh"])
        self.assertEqual(params["fused"]["rrf-lexical"], ["words", "trigram"])


if __name__ == "__main__":
    unittest.main()
