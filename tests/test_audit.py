"""The bias audit: its statistics against known values, and a stored run over a real build."""
import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from acatalogue import db as dbm
from acatalogue.audit import entropy_norm, gini, jsd, latest, wilson


class StatisticsTests(unittest.TestCase):
    def test_wilson_matches_published_values(self):
        lo, hi = wilson(0.5, 100)                       # 50 of 100
        self.assertAlmostEqual(lo, 0.4038, places=4)
        self.assertAlmostEqual(hi, 0.5962, places=4)
        lo, hi = wilson(0.0, 10)                        # 0 of 10: never a zero-width interval
        self.assertEqual(lo, 0.0)
        self.assertAlmostEqual(hi, 0.2775, places=4)

    def test_jsd(self):
        self.assertEqual(jsd([0.5, 0.5], [0.5, 0.5]), 0.0)
        self.assertAlmostEqual(jsd([1.0, 0.0], [0.0, 1.0]), 1.0)          # disjoint: the maximum, in bits
        p, q = [0.7, 0.2, 0.1], [0.2, 0.3, 0.5]
        self.assertAlmostEqual(jsd(p, q), jsd(q, p))                       # symmetric
        self.assertEqual(jsd([0.5, 0.5, 0.0], [0.5, 0.5, 0.0]), 0.0)       # empty groups are fine

    def test_entropy_and_gini(self):
        self.assertAlmostEqual(entropy_norm([0.25] * 4), 1.0)
        self.assertEqual(entropy_norm([1.0, 0.0, 0.0]), 0.0)
        self.assertEqual(gini([1, 1, 1, 1]), 0.0)
        self.assertAlmostEqual(gini([0, 0, 0, 1]), 0.75)


class StoredRunTests(unittest.TestCase):
    """Builds a fresh catalogue from seed/ and corpora/ and reads the audit the build stored."""

    @classmethod
    def setUpClass(cls):
        from acatalogue.build import build
        cls.tmp = Path(cls.enterClassContext(tempfile.TemporaryDirectory()))
        with mock.patch.dict(os.environ, {"ACAT_STORE": str(cls.tmp / "store")}):   # never this machine's downloads
            build(cls.tmp / "cat.sqlite", verbose=False)
        cls.conn = dbm.connect(cls.tmp / "cat.sqlite", readonly=True)
        cls.audit = latest(cls.conn)

    def test_shares_are_a_distribution(self):
        for level in ("regions", "subregions"):
            r = self.audit[level]
            self.assertGreater(r["n"], 20)
            self.assertAlmostEqual(sum(g["share"] for g in r["groups"]), 1.0, places=9)
            for g in r["groups"]:
                self.assertLessEqual(g["share_lo"], g["share"])
                self.assertGreaterEqual(g["share_hi"], g["share"])

    def test_baselines_are_declared_and_consistent(self):
        r = self.audit["regions"]
        for name in ("population", "land_area", "equal"):
            total = sum(g["vs"][name]["baseline"] or 0 for g in r["groups"])
            self.assertAlmostEqual(total, 1.0, places=9)
            for g in r["groups"]:
                v = g["vs"][name]
                if v["rr"]:
                    self.assertAlmostEqual(v["log2_rr"], math.log2(g["share"] / v["baseline"]))
        antarctica = next(g for g in r["groups"] if g["id"] == "space/m49-010")
        self.assertIsNone(antarctica["vs"]["population"]["rr"], "no World Bank value: no ratio, not zero")

    def test_run_is_reproducible_and_queryable(self):
        from acatalogue.audit import regional
        import random
        again = regional(self.conn, 1, random.Random(20260925))
        self.assertEqual(again["distribution"]["population"]["jsd_lo"],
                         self.audit["regions"]["distribution"]["population"]["jsd_lo"])
        n = self.conn.execute("SELECT count(*) FROM audit_metric WHERE run_id = ? AND metric = 'log2_rr'",
                              (self.audit["run_id"],)).fetchone()[0]
        self.assertEqual(n, 3 * (len(self.audit["regions"]["groups"]) + len(self.audit["subregions"]["groups"])))

    def test_decisions_are_attributed_to_their_decider(self):
        by = self.audit["review"]["accepted_by_decider"]
        self.assertIn("AI agent", by)
        self.assertEqual(self.audit["review"]["human_reviews"], 0)

    def test_sitelinks_leave_out_bot_editions(self):
        rows = self.conn.execute("SELECT a.value, r.value FROM attribute a JOIN attribute r ON r.concept_id ="
                                 " a.concept_id AND r.key = 'sitelinks_all' WHERE a.key = 'sitelinks'").fetchall()
        self.assertTrue(rows)
        self.assertTrue(all(int(a) <= int(r) for a, r in rows))
        self.assertTrue(any(int(a) < int(r) for a, r in rows))


if __name__ == "__main__":
    unittest.main()
