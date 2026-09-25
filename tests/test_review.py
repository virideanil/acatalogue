"""Human review kept apart from machine proposals: decisions layer on top, nothing is overwritten."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from acatalogue import db as dbm, review
from acatalogue.compendium import SeedError

PROPOSALS = [
    {"from": "acat/a", "to": "wd/Q1", "relation": "exactMatch", "status": "accepted", "method": "m",
     "reviewer": "claude (AI agent, session 2026-09-25)", "note": ""},
    {"from": "acat/b", "to": "wd/Q2", "relation": "exactMatch", "status": "accepted", "method": "m",
     "reviewer": "claude (AI agent, session 2026-09-25)", "note": "matched 'b'"},
    {"from": "acat/c", "to": "wd/Q3", "relation": "closeMatch", "status": "accepted", "method": "m",
     "reviewer": "claude (AI agent, session 2026-09-25)", "note": ""},
]


class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        guard = mock.patch.object(review, "REVIEW_DIR", Path(tempfile.mkdtemp()) / "must-stay-empty")
        guard.start()
        self.addCleanup(guard.stop)

    def effective(self):
        files, problems = review.read_reviews(self.dir)
        self.assertEqual(problems, [])
        return {d["from"]: d for d in review.apply_to_decisions([dict(p) for p in PROPOSALS], files)}

    def test_human_decisions_layer_on_proposals(self):
        review.append("Ada Reviewer", review.mapping_target("acat/a", "wd/Q1"), "approve", perspective="Istanbul",
                      directory=self.dir)
        review.append("Ada Reviewer", review.mapping_target("acat/b", "wd/Q2"), "revise", relation="closeMatch",
                      rationale="Wikidata's item is broader in scope", directory=self.dir)
        review.append("Ada Reviewer", review.mapping_target("acat/a", "wd/Q1"), "approve", directory=self.dir)
        review.append("Ada Reviewer", review.mapping_target("acat/c", "wd/Q3"), "object",
                      rationale="a different sense of the word", directory=self.dir)
        e = self.effective()
        self.assertEqual((e["acat/a"]["status"], e["acat/a"]["reviewer"]), ("accepted", "Ada Reviewer"))
        self.assertEqual(e["acat/b"]["relation"], "closeMatch")
        self.assertIn("proposed exactMatch/accepted by claude", e["acat/b"]["note"])   # the proposal is named
        self.assertIn("matched 'b'", e["acat/b"]["note"])                               # and its note kept
        self.assertEqual(e["acat/c"]["status"], "rejected")
        self.assertTrue(e["acat/c"]["method"].endswith("+human-objected"))

    def test_agent_reviews_never_decide(self):
        review.append("another model", review.mapping_target("acat/a", "wd/Q1"), "object", kind="agent",
                      rationale="looks wrong", directory=self.dir)
        self.assertEqual(self.effective()["acat/a"]["status"], "accepted")

    def test_latest_human_decision_wins(self):
        target = review.mapping_target("acat/a", "wd/Q1")
        with mock.patch("acatalogue.review.utcnow", return_value="2026-09-25T10:00:00Z"):
            review.append("Ada", target, "object", rationale="first look", directory=self.dir)
        with mock.patch("acatalogue.review.utcnow", return_value="2026-09-26T10:00:00Z"):
            review.append("Ada", target, "approve", directory=self.dir)
        self.assertEqual(self.effective()["acat/a"]["status"], "accepted")

    def test_invalid_rows_are_never_written(self):
        with self.assertRaises(SeedError):
            review.append("Ada", review.mapping_target("acat/a", "wd/Q1"), "object", directory=self.dir)  # no why
        with self.assertRaises(SeedError):
            review.append("Ada", "acat/a", "approve", directory=self.dir)                    # not a target
        with self.assertRaises(SeedError):
            review.append("Ada", review.mapping_target("acat/a", "wd/Q1"), "approve", rationale="a\tb",
                          directory=self.dir)
        self.assertEqual(list(self.dir.glob("*.tsv")), [])

    def test_reviewer_kind(self):
        self.assertEqual(review.reviewer_kind("claude (AI agent, session 2026-09-25)"), "AI agent")
        self.assertEqual(review.reviewer_kind("seed"), "seed file (no named reviewer)")
        self.assertEqual(review.reviewer_kind("Ada Reviewer"), "human")


class BuildTests(unittest.TestCase):
    """A real build with a person's review file: objections stop label copying, revisions change relations."""

    @classmethod
    def setUpClass(cls):
        from acatalogue.build import build
        cls.tmp = Path(tempfile.mkdtemp())
        reviews = cls.tmp / "reviews"
        review.append("Ada Reviewer", review.mapping_target("acat/abjads", "wd/Q185087"), "object",
                      rationale="test objection", directory=reviews)
        review.append("Ada Reviewer", review.mapping_target("acat/abugidas", "wd/Q335806"), "revise",
                      relation="closeMatch", rationale="test revision", directory=reviews)
        review.append("Ada Reviewer", review.mapping_target("acat/acoustics", "wd/Q82811"), "approve",
                      perspective="test", directory=reviews)
        with mock.patch.object(review, "REVIEW_DIR", reviews):
            cls.report = build(cls.tmp / "cat.sqlite", verbose=False)
        cls.conn = dbm.connect(cls.tmp / "cat.sqlite", readonly=True)

    def mapping(self, frm, to):
        return self.conn.execute("SELECT relation, status, reviewer, method, note FROM mapping WHERE from_id = ?"
                                 " AND to_id = ?", (frm, to)).fetchone()

    def test_effective_mappings(self):
        self.assertEqual(self.mapping("acat/abjads", "wd/Q185087")[1], "rejected")
        self.assertEqual(self.mapping("acat/abugidas", "wd/Q335806")[:3], ("closeMatch", "accepted", "Ada Reviewer"))
        self.assertEqual(self.mapping("acat/acoustics", "wd/Q82811")[2], "Ada Reviewer")
        self.assertEqual(self.report["reviews"]["dangling"], [])

    def test_objected_mapping_donates_no_labels(self):
        n = self.conn.execute("SELECT count(*) FROM label l JOIN source s ON s.sha512 = l.source_sha512"
                              " WHERE l.concept_id = 'acat/abjads' AND s.corpus LIKE 'wikidata-entities-%'").fetchone()[0]
        self.assertEqual(n, 0)
        n = self.conn.execute("SELECT count(*) FROM label l JOIN source s ON s.sha512 = l.source_sha512"
                              " WHERE l.concept_id = 'acat/abugidas' AND s.corpus LIKE 'wikidata-entities-%'").fetchone()[0]
        self.assertGreater(n, 0, "closeMatch still donates labels")

    def test_reviews_are_rows_and_audited(self):
        from acatalogue.audit import latest
        from acatalogue.views import node
        self.assertEqual(self.conn.execute("SELECT count(*) FROM review WHERE reviewer_kind = 'human'").fetchone()[0], 3)
        audit = latest(self.conn)
        self.assertEqual(audit["review"]["human_reviews"], 3)
        self.assertIn("human", audit["review"]["accepted_by_decider"])
        n = node(self.conn, "acat/abugidas")
        self.assertEqual([(r["decision"], r["relation"]) for r in n["reviews"]], [("revise", "closeMatch")])
        self.assertEqual(next(m for m in n["mappings"] if m["id"] == "wd/Q335806")["decided_by"], "human")


if __name__ == "__main__":
    unittest.main()
