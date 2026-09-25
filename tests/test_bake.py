"""The baked layout: the browser's own physics run in Node, deterministic, and marked stale when the graph moves on."""
import shutil
import tempfile
import unittest
from pathlib import Path

from acatalogue import db as dbm


@unittest.skipIf(shutil.which("node") is None, "baking needs Node.js")
class BakeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from acatalogue.bake import bake
        from acatalogue.build import build
        cls.tmp = Path(tempfile.mkdtemp())
        cls.path = cls.tmp / "cat.sqlite"
        build(cls.path, verbose=False)
        cls.conn = dbm.connect(cls.path)
        cls.first = bake(cls.conn)
        cls.pos1 = dict((t, (x, y)) for t, x, y in cls.conn.execute(
            "SELECT target, x, y FROM layout WHERE model = ?", (cls.first["model"],)))
        cls.second = bake(cls.conn)
        cls.pos2 = dict((t, (x, y)) for t, x, y in cls.conn.execute(
            "SELECT target, x, y FROM layout WHERE model = ?", (cls.second["model"],)))

    def test_deterministic(self):
        self.assertEqual(self.first["model"], self.second["model"], "same physics, same model id")
        self.assertEqual(self.first["steps"], self.second["steps"])
        self.assertEqual(self.pos1, self.pos2, "two bakes of one graph give identical positions")

    def test_at_rest_and_complete(self):
        from acatalogue.views import graph
        self.assertTrue(self.first["asleep"], "the field came to rest within the step limit")
        g = graph(self.conn)
        self.assertEqual(g["layout"]["model"], self.first["model"])
        self.assertTrue(g["layout"]["complete"])
        self.assertFalse(g["layout"]["stale"])
        self.assertTrue(all(n["pos"] is not None for n in g["nodes"]))

    def test_semantic_model_is_not_confused_with_a_layout_or_a_vector_set(self):
        from acatalogue.views import graph
        before = graph(self.conn)
        self.assertFalse((before["semantic_model"] or "").startswith("layout/"))
        # a newer model without neighbours (e.g. dense label vectors) must not take its place
        self.conn.execute("INSERT INTO model(id, method, created_at) VALUES ('dense/x', 'test vectors', '2999-01-01T00:00:00Z')")
        after = graph(self.conn)
        self.assertEqual(after["semantic_model"], before["semantic_model"])
        self.assertEqual(len(after["edges"]), len(before["edges"]))
        self.assertFalse(after["layout"]["stale"])
        self.conn.rollback()

    def test_a_changed_graph_marks_the_layout_stale(self):
        from acatalogue.views import graph
        c = dbm.connect(self.tmp / "changed.sqlite", create=True)
        self.conn.backup(c)                     # WAL-safe copy (a file copy would miss the -wal pages)
        a, b = [r[0] for r in c.execute("SELECT id FROM concept WHERE scheme = 'acat' ORDER BY id LIMIT 2")]
        c.execute("INSERT INTO related(a, b) VALUES (?, ?)", (a, b))
        self.assertTrue(graph(c)["layout"]["stale"])


if __name__ == "__main__":
    unittest.main()
