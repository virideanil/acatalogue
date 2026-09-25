"""Invariants the catalogue promises: nothing is lost, every row can be traced, history is tamper-evident."""
import sqlite3
import tempfile
import unittest
import zlib
from pathlib import Path

from acatalogue import db as dbm, ledger
from acatalogue.corpusfile import CorpusFile
from acatalogue.util import sha512_bytes, utcnow


def fresh_db(tmp: Path) -> sqlite3.Connection:
    conn = dbm.connect(tmp / "t.sqlite", create=True)
    dbm.init_schema(conn)
    return conn


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.conn = fresh_db(self.tmp)
        for i in range(5):
            ledger.record(self.conn, "test", "act", target=f"acat/x{i}", detail={"i": i}, receipt=f"r{i}", undo="u")
        self.conn.commit()

    def test_chain_verifies(self):
        ok, n, msg = ledger.verify(self.conn)
        self.assertTrue(ok, msg)
        self.assertEqual(n, 5)

    def test_update_and_delete_are_refused(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("UPDATE ledger SET actor = 'mallory' WHERE seq = 2")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("DELETE FROM ledger WHERE seq = 2")

    def test_tampering_is_detected(self):
        # simulate someone bypassing the trigger: the hash chain still exposes it
        self.conn.execute("DROP TRIGGER ledger_no_update")
        self.conn.execute("UPDATE ledger SET receipt = 'forged' WHERE seq = 3")
        ok, n, msg = ledger.verify(self.conn)
        self.assertFalse(ok)
        self.assertIn("row 3", msg)


class NeverDeletedTests(unittest.TestCase):
    def setUp(self):
        self.conn = fresh_db(Path(tempfile.mkdtemp()))
        sha = sha512_bytes(b"x")
        self.conn.execute("INSERT INTO source(sha512, bytes, kind, name, first_seen) VALUES (?,1,'seed','x',?)",
                          (sha, utcnow()))
        self.conn.execute("INSERT INTO scheme(id, title, origin) VALUES ('acat', 'A', 'authored')")
        self.conn.execute("INSERT INTO concept(id, scheme, code, label) VALUES ('acat/a', 'acat', 'a', 'A')")
        self.conn.execute("INSERT INTO claim(subject, predicate, value, source_sha512, recorded_at)"
                          " VALUES ('acat/a', 'wd/P31', 'v', ?, ?)", (sha, utcnow()))
        self.conn.commit()

    def test_sources_concepts_claims_survive_delete(self):
        for table in ("source", "concept", "claim"):
            with self.subTest(table=table), self.assertRaises(sqlite3.IntegrityError):
                self.conn.execute(f"DELETE FROM {table}")

    def test_claim_needs_exactly_one_of_object_or_value(self):
        sha = self.conn.execute("SELECT sha512 FROM source").fetchone()[0]
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO claim(subject, predicate, object, value, source_sha512, recorded_at)"
                              " VALUES ('acat/a', 'wd/P31', 'wd/Q1', 'v', ?, ?)", (sha, utcnow()))


class CorpusTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "c" / "corpus.sqlite"
        self.c = CorpusFile(self.path, create=True, name="test-20260101", title="t")

    def test_roundtrip_and_dedup(self):
        data = b"hello world " * 100
        d1 = self.c.add("a", data)
        d2 = self.c.add("b", data)
        self.assertEqual(d1, d2)
        self.assertEqual(self.c.get("a"), data)
        n_blobs = self.c.conn.execute("SELECT count(*) FROM sqlar").fetchone()[0]
        self.assertEqual(n_blobs, 1, "identical bytes are stored once")
        stored = self.c.conn.execute("SELECT data FROM sqlar").fetchone()[0]
        self.assertEqual(zlib.decompress(stored), data, "sqlar convention: zlib when smaller")

    def test_same_name_different_bytes_is_refused(self):
        self.c.add("a", b"one")
        with self.assertRaises(ValueError):
            self.c.add("a", b"two")

    def test_sealed_corpus_refuses_writes_and_verifies(self):
        self.c.add("a", b"payload")
        manifest = self.c.seal()
        self.assertEqual(len(manifest), 128)
        with self.assertRaises(sqlite3.IntegrityError):
            self.c.add("b", b"late")
        ok, msg = self.c.verify()
        self.assertTrue(ok, msg)

    def test_corrupted_bytes_are_detected(self):
        self.c.add("a", b"payload that is long enough " * 10)
        self.c.conn.execute("DROP TRIGGER sqlar_no_update")
        self.c.conn.execute("UPDATE sqlar SET data = ?", (zlib.compress(b"tampered"),))
        ok, msg = self.c.verify()
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
