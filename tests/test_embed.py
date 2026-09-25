"""Dense vectors are keyed by text, so a rebuild that renumbers labels cannot misattach them."""
import struct
import tempfile
import unittest
from pathlib import Path

from acatalogue import db as dbm
from acatalogue.embed import load_label_vectors, model_id, rekey_label_vectors, text_key

MID = model_id("e5-large-instruct")


def vec(*xs):
    v = list(xs) + [0.0] * (1024 - len(xs))
    return struct.pack("<1024f", *v)


class EmbeddingKeyTests(unittest.TestCase):
    def setUp(self):
        self.conn = dbm.connect(Path(self.enterContext(tempfile.TemporaryDirectory())) / "t.sqlite", create=True)
        dbm.init_schema(self.conn)
        c = self.conn
        c.execute("INSERT INTO scheme(id, title, origin) VALUES ('acat', 'ACAT', 'authored')")
        for cid in ("acat/a", "acat/b"):
            c.execute("INSERT INTO concept(id, scheme, code, label) VALUES (?, 'acat', ?, ?)", (cid, cid[5:], cid))
        c.execute("INSERT INTO model(id, method, created_at) VALUES (?, 'test', '2026-09-25T19:00:00Z')", (MID,))

    def labels(self, rows):
        self.conn.execute("DELETE FROM label")
        self.conn.executemany("INSERT INTO label(id, concept_id, lang, kind, text) VALUES (?,?,?,?,?)", rows)

    def test_text_key(self):
        self.assertEqual(text_key("Fizik"), text_key("Fizik"))
        self.assertNotEqual(text_key("Fizik"), text_key("fizik"))
        self.assertTrue(text_key("物理").startswith("text/sha256:"))

    def test_vectors_follow_the_text_across_a_rebuild(self):
        self.labels([(1, "acat/a", "tr", "pref", "Fizik"), (2, "acat/b", "de", "pref", "Chemie")])
        self.conn.execute("INSERT INTO embedding(target, model, dim, vec) VALUES (?,?,?,?)", (text_key("Fizik"), MID, 1024, vec(1)))
        self.conn.execute("INSERT INTO embedding(target, model, dim, vec) VALUES (?,?,?,?)", (text_key("Chemie"), MID, 1024, vec(0, 1)))
        # a rebuild regenerates the labels with other ids (here: swapped)
        self.labels([(2, "acat/a", "tr", "pref", "Fizik"), (1, "acat/b", "de", "pref", "Chemie"),
                     (3, "acat/a", "az", "pref", "Fizik")])
        ids, M = load_label_vectors(self.conn)
        got = {i: tuple(M[k][:2]) for k, i in enumerate(ids)}
        self.assertEqual(got, {2: (1.0, 0.0), 1: (0.0, 1.0), 3: (1.0, 0.0)})   # by text, whatever the ids

    def test_rekey_only_when_row_ids_are_trustworthy(self):
        self.labels([(7, "acat/a", "tr", "pref", "Fizik")])
        self.conn.execute("INSERT INTO embedding(target, model, dim, vec) VALUES ('label/7', ?, 1024, ?)", (MID, vec(1)))
        self.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('built_at', '2026-09-25T18:00:00Z')")
        st = rekey_label_vectors(self.conn, MID)                      # built before the vectors: ids valid
        self.assertEqual((st["rekeyed"], st["dropped"]), (1, 0))
        self.assertEqual(self.conn.execute("SELECT count(*) FROM embedding WHERE target = ?", (text_key("Fizik"),)).fetchone()[0], 1)
        self.conn.execute("INSERT INTO embedding(target, model, dim, vec) VALUES ('label/7', ?, 1024, ?)", (MID, vec(1)))
        self.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('built_at', '2026-09-25T20:00:00Z')")
        st = rekey_label_vectors(self.conn, MID)                      # rebuilt since: ids may name other labels
        self.assertEqual((st["rekeyed"], st["dropped"]), (0, 1))
        self.assertEqual(self.conn.execute("SELECT count(*) FROM embedding WHERE target LIKE 'label/%'").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
