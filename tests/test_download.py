"""Streaming downloads into the local store, against a local server: resume, validators, checksums,
busy servers, local files, and manifests whose bytes live outside the corpus file."""
import hashlib
import sqlite3
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from acatalogue.corpusfile import CorpusFile
from acatalogue.download import DownloadError, Downloader, Task, parse_checksum_file
from acatalogue.store import Store

BODY = bytes(range(256)) * 4096                      # 1 MiB, every byte value


class _Files(BaseHTTPRequestHandler):
    files: dict[str, dict] = {}                      # path -> {"body", "etag", "drop", "busy", "then"}
    seen: list[tuple[str, str, dict]] = []

    def _entry(self):
        return self.files.get(self.path.split("?")[0])

    def do_HEAD(self):
        e = self._entry()
        if e is None:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(e["body"])))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("ETag", e["etag"])
        self.end_headers()

    def do_GET(self):
        e = self._entry()
        self.seen.append(("GET", self.path, dict(self.headers)))
        if e is None:
            self.send_error(404)
            return
        if e.get("busy"):
            e["busy"] -= 1
            self.send_response(429)
            self.send_header("Retry-After", "3")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body, start = e["body"], 0
        rng, if_range = self.headers.get("Range"), self.headers.get("If-Range")
        if rng and (if_range is None or if_range == e["etag"]):
            start = int(rng.split("=")[1].split("-")[0])
            if start >= len(body):
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{len(body)}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(body) - 1}/{len(body)}")
        else:
            self.send_response(200)
        self.send_header("Content-Length", str(len(body) - start))
        self.send_header("ETag", e["etag"])
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        drop = e.pop("drop", None)
        if drop is not None:                          # send part of the body, then hang up
            self.wfile.write(body[start:start + drop])
            self.wfile.flush()
            self.close_connection = True
            if "then" in e:                           # the file changes on the server meanwhile
                e["body"], e["etag"] = e.pop("then")
            return
        self.wfile.write(body[start:])

    def log_message(self, *args):
        pass


class DownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Files)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store = Store(self.tmp / "store")
        self.addCleanup(self.store.close)
        self.sleep = mock.patch("acatalogue.download.time.sleep").start()
        self.addCleanup(mock.patch.stopall)
        self.dl = Downloader(self.store, min_interval=0, progress=lambda *_: None)
        _Files.files.clear()
        _Files.seen.clear()

    def task(self, name, **kw):
        return Task("test", "test-20260925", name, f"{self.base}/{name}",
                    self.store.raw_dir("test", "20260925") / name, **kw)

    def row(self, name):
        return self.store.conn.execute("SELECT * FROM download WHERE name = ?", (name,)).fetchone()

    def test_a_whole_file(self):
        _Files.files["/a.bin"] = {"body": BODY, "etag": '"v1"'}
        out = self.dl.fetch(self.task("a.bin"))
        self.assertEqual(out["sha512"], hashlib.sha512(BODY).hexdigest())
        self.assertEqual((self.row("a.bin")["state"], self.row("a.bin")["bytes_done"]), ("done", len(BODY)))
        self.assertEqual(_Files.seen[0][2].get("Accept-Encoding"), "identity")
        self.assertNotIn("@", _Files.seen[0][2].get("User-Agent"), "the User-Agent names no person")
        self.assertTrue(self.dl.fetch(self.task("a.bin")).get("skipped"), "a finished file is not fetched again")

    def test_an_interrupted_download_resumes_with_a_range(self):
        _Files.files["/b.bin"] = {"body": BODY, "etag": '"v1"', "drop": 300_000}
        out = self.dl.fetch(self.task("b.bin"))
        self.assertEqual(out["sha512"], hashlib.sha512(BODY).hexdigest())
        second = _Files.seen[1][2]
        self.assertEqual(second.get("Range"), "bytes=300000-")
        self.assertEqual(second.get("If-Range"), '"v1"')
        self.assertEqual(self.row("b.bin")["attempts"], 2)

    def test_a_file_that_changed_meanwhile_starts_over(self):
        new = BODY[::-1]
        _Files.files["/c.bin"] = {"body": BODY, "etag": '"v1"', "drop": 300_000, "then": (new, '"v2"')}
        out = self.dl.fetch(self.task("c.bin"))
        self.assertEqual(out["sha512"], hashlib.sha512(new).hexdigest(), "no splice of two versions")
        self.assertEqual((self.store.raw_dir("test", "20260925") / "c.bin").read_bytes(), new)

    def test_publisher_checksums(self):
        _Files.files["/d.bin"] = {"body": BODY, "etag": '"v1"'}
        good = hashlib.sha256(BODY).hexdigest()
        self.assertEqual(self.dl.fetch(self.task("d.bin", checksum=f"sha256:{good}"))["checksum_ok"], 1)
        _Files.files["/e.bin"] = {"body": BODY, "etag": '"v1"'}
        with self.assertRaises(DownloadError):
            self.dl.fetch(self.task("e.bin", checksum="sha256:" + "0" * 64))
        d = self.store.raw_dir("test", "20260925")
        self.assertFalse((d / "e.bin").exists(), "a file that fails its checksum is never in place")
        self.assertTrue((d / "e.bin.rejected").exists(), "it is kept aside for inspection")
        self.assertEqual(self.row("e.bin")["state"], "failed")

    def test_a_checksum_file(self):
        _Files.files["/f.bin"] = {"body": BODY, "etag": '"v1"'}
        _Files.files["/SHA512SUMS"] = {"body": f"{'1' * 128}  other.bin\n{hashlib.sha512(BODY).hexdigest()}  f.bin\n"
                                       .encode(), "etag": '"s"'}
        out = self.dl.fetch(self.task("f.bin", checksum=f"url:{self.base}/SHA512SUMS"))
        self.assertEqual(out["checksum_ok"], 1)

    def test_a_busy_server_is_waited_out(self):
        _Files.files["/g.bin"] = {"body": BODY, "etag": '"v1"', "busy": 2}
        self.dl.fetch(self.task("g.bin"))
        waits = [c.args[0] for c in self.sleep.call_args_list]
        self.assertEqual(waits.count(3.0), 2, "Retry-After honoured")

    def test_a_missing_file_fails_and_says_so(self):
        with self.assertRaises(DownloadError):
            self.dl.fetch(self.task("nothing.bin"))
        self.assertEqual(self.row("nothing.bin")["state"], "failed")
        self.assertIn("404", self.row("nothing.bin")["error"])

    def test_a_local_database_in_use_is_copied_consistently(self):
        live = self.tmp / "mine.sqlite"
        a = sqlite3.connect(live)
        a.execute("PRAGMA journal_mode = WAL")
        a.execute("CREATE TABLE t(x)")
        a.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(1000)])
        a.commit()                                    # committed, still in the WAL (not checkpointed)
        t = Task("mine", "mine-20260925", "mine.sqlite", str(live), self.store.raw_dir("mine", "20260925") / "mine.sqlite")
        self.dl.fetch(t)
        b = sqlite3.connect(t.dest)
        self.assertEqual(b.execute("SELECT count(*) FROM t").fetchone()[0], 1000)
        b.close()
        a.close()

    def test_parse_checksum_files(self):
        h = "ab" * 32
        self.assertEqual(parse_checksum_file(f"{h}  dir/x.zip\n", "x.zip"), h)
        self.assertEqual(parse_checksum_file(f"{h} *x.zip", "x.zip"), h)
        self.assertEqual(parse_checksum_file(f"SHA256 (x.zip) = {h}", "x.zip"), h)
        self.assertEqual(parse_checksum_file(h, "x.zip"), h)
        self.assertIsNone(parse_checksum_file(f"{h}  y.zip", "x.zip"))


class ExternalManifestTests(unittest.TestCase):
    def test_external_items_are_hashed_and_verified(self):
        tmp = Path(tempfile.mkdtemp())
        raw = tmp / "raw" / "s" / "20260925"
        raw.mkdir(parents=True)
        (raw / "x.bin").write_bytes(BODY)
        c = CorpusFile(tmp / "corpora" / "s-20260925" / "corpus.sqlite", create=True, name="s-20260925", title="t")
        c.set_external_root("../../raw/s/20260925")
        digest = hashlib.sha512(BODY).hexdigest()
        with self.assertRaises(ValueError):
            c.add_external("x.bin", "0" * 128, len(BODY))            # a manifest never names unseen bytes
        c.add_external("x.bin", digest, len(BODY), url="https://example.org/x.bin")
        c.seal()
        self.assertTrue(c.verify()[0])
        self.assertEqual(c.get("x.bin"), BODY)
        (raw / "x.bin").write_bytes(BODY[:-1] + b"\x00")
        self.assertFalse(c.verify()[0], "changed bytes are caught")
        (raw / "x.bin").unlink()
        ok, msg = c.verify()
        self.assertTrue(ok)
        self.assertIn("pruned", msg)


if __name__ == "__main__":
    unittest.main()
