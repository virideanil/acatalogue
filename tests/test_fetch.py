"""The fetcher against a local server: only data is sealed as data, and every attempt is logged."""
import gzip
import hashlib
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from acatalogue.corpusfile import CorpusFile
from acatalogue.fetch import FetchError, Fetcher, contains_check, mediawiki_check, sparql_check

MAXLAG = json.dumps({"error": {"code": "maxlag", "info": "Waiting for a replica: 7 seconds lagged",
                               "lag": 7}}).encode()
BADVALUE = json.dumps({"error": {"code": "badvalue", "info": "Unrecognized value for parameter"}}).encode()
OK = json.dumps({"entities": {"Q1": {"id": "Q1"}}}).encode()


class _Handler(BaseHTTPRequestHandler):
    script: dict[str, list[tuple[int, dict, bytes]]] = {}
    hits: dict[str, int] = {}

    def do_GET(self):
        self.hits[self.path] = self.hits.get(self.path, 0) + 1
        queue = self.script[self.path]
        status, headers, body = queue.pop(0) if len(queue) > 1 else queue[0]
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class FetcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.corpus = CorpusFile(self.tmp / "c.sqlite", create=True, name="test-fetch", title="fetch tests")
        self.fetcher = Fetcher(self.corpus, min_interval=0, verbose=False)
        self.sleep = mock.patch("acatalogue.fetch.time.sleep").start()
        self.addCleanup(mock.patch.stopall)
        _Handler.script.clear()
        _Handler.hits.clear()

    def log(self):
        return [dict(r) for r in self.corpus.conn.execute("SELECT status, sha512, note FROM fetch_log ORDER BY seq")]

    def test_gzip_is_decoded_before_hashing(self):
        body = "Leviathan ağırdır — 物理学".encode() * 50
        _Handler.script["/gz"] = [(200, {"Content-Encoding": "gzip", "Content-Type": "text/plain"}, gzip.compress(body))]
        got = self.fetcher.fetch("gz", self.base + "/gz")
        self.assertEqual(got, body)
        self.assertEqual(self.corpus.get("gz"), body)
        self.assertEqual(self.corpus.item("gz")["sha512"], hashlib.sha512(body).hexdigest())
        self.assertIn("gzip decoded before hashing", self.log()[-1]["note"])

    def test_maxlag_in_http_200_is_retried_and_never_stored(self):
        _Handler.script["/api"] = [(200, {}, MAXLAG), (200, {}, OK)]
        got = self.fetcher.fetch("e", self.base + "/api", check=mediawiki_check)
        self.assertEqual(got, OK)
        self.assertEqual(_Handler.hits["/api"], 2)
        self.assertGreaterEqual(self.sleep.call_args_list[-1].args[0], 7)      # waits at least the reported lag
        first, second = self.log()
        self.assertIn("not stored: maxlag", first["note"])
        self.assertIsNone(first["sha512"])
        self.assertEqual(second["sha512"], hashlib.sha512(OK).hexdigest())
        self.assertEqual([it["name"] for it in self.corpus.items()], ["e"])

    def test_api_error_body_is_refused(self):
        _Handler.script["/bad"] = [(200, {}, BADVALUE)]
        with self.assertRaises(FetchError):
            self.fetcher.fetch("bad", self.base + "/bad", check=mediawiki_check)
        self.assertFalse(self.corpus.has("bad"))
        self.assertEqual(_Handler.hits["/bad"], 1)                             # a real error is not retried
        self.assertIn("not stored: API error badvalue", self.log()[-1]["note"])

    def test_retry_after_is_honoured(self):
        _Handler.script["/busy"] = [(503, {"Retry-After": "9"}, b"busy"), (200, {}, OK)]
        self.assertEqual(self.fetcher.fetch("busy", self.base + "/busy"), OK)
        self.assertEqual(self.sleep.call_args_list[-1].args[0], 9)
        self.assertEqual([r["status"] for r in self.log()], [503, 200])

    def test_sparql_without_results_is_refused(self):
        _Handler.script["/sparql"] = [(200, {}, b"<html>Query timeout</html>")]
        with self.assertRaises(FetchError):
            self.fetcher.fetch("q", self.base + "/sparql", check=sparql_check)
        self.assertFalse(self.corpus.has("q"))

    def test_page_without_its_content_is_refused(self):
        _Handler.script["/page"] = [(200, {}, b"<html>Please enable JavaScript</html>")]
        with self.assertRaises(FetchError):
            self.fetcher.fetch("p", self.base + "/page", check=contains_check(b"downloadTableEN"))
        self.assertFalse(self.corpus.has("p"))

    def test_persistent_lag_is_waited_out_with_backoff(self):
        _Handler.script["/lag"] = [(200, {}, MAXLAG)] * 9 + [(200, {}, OK)]
        self.assertEqual(self.fetcher.fetch("lag", self.base + "/lag", check=mediawiki_check), OK)
        self.assertEqual(_Handler.hits["/lag"], 10)                            # more than max_retries attempts
        waits = [c.args[0] for c in self.sleep.call_args_list]
        self.assertEqual(waits, sorted(waits))                                 # backing off, never hammering
        self.assertLessEqual(max(waits), self.fetcher.max_wait)

    def test_patience_runs_out(self):
        _Handler.script["/stuck"] = [(200, {}, MAXLAG)]
        f = Fetcher(self.corpus, min_interval=0, verbose=False, patience=60)
        with self.assertRaises(FetchError):
            f.fetch("stuck", self.base + "/stuck", check=mediawiki_check)
        self.assertFalse(self.corpus.has("stuck"))
        self.assertLessEqual(sum(c.args[0] for c in self.sleep.call_args_list), 60)

    def test_errors_are_bounded_by_max_retries(self):
        _Handler.script["/down"] = [(500, {}, b"oops")]
        with self.assertRaises(FetchError):
            self.fetcher.fetch("down", self.base + "/down")
        self.assertEqual(_Handler.hits["/down"], self.fetcher.max_retries)

    def test_resumable(self):
        _Handler.script["/once"] = [(200, {}, OK)]
        self.fetcher.fetch("once", self.base + "/once", check=mediawiki_check)
        self.fetcher.fetch("once", self.base + "/once", check=mediawiki_check)
        self.assertEqual(_Handler.hits["/once"], 1)


class StoredResponsesTests(unittest.TestCase):
    """The checks applied retroactively: no committed corpus holds an error body sealed as data."""

    def test_committed_responses_pass_the_checks(self):
        from acatalogue.corpusfile import list_corpora
        checked = 0
        for path in list_corpora():
            c = CorpusFile(path, readonly=True)
            if not c.name.startswith(("wikidata-", "wikipedia-", "worldbank-")):
                continue
            for it in c.items():
                if c.name.startswith("worldbank-"):
                    from acatalogue.sources.worldbank import worldbank_check as check
                elif it["name"].startswith(("sparql/", "labels/sparql-")):   # query-service responses
                    check = sparql_check
                else:
                    check = mediawiki_check
                verdict, _, message = check(c.get(it["name"]))
                self.assertEqual(verdict, "ok", f"{c.name}:{it['name']}: {message}")
                checked += 1
        self.assertGreater(checked, 50)


if __name__ == "__main__":
    unittest.main()
