"""Polite HTTP into a named corpus: every response is stored as exact bytes, every attempt is logged.

Resumable: an item name that already exists in the corpus is returned from the corpus, not fetched
again, so an interrupted run continues where it stopped.

Nothing that is not data is ever stored as data: a `check` callback inspects each 200 response and
can ask for a retry (e.g. MediaWiki's maxlag, which arrives as HTTP 200) or refuse it (an API error
body); refused bodies are logged, never sealed into a corpus. Responses are requested gzip-encoded;
the stored, hashed bytes are the decoded body.
"""
from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from .corpusfile import CorpusFile
from .util import utcnow

# Wikimedia User-Agent policy format: <client>/<version> (<contact>) <library>/<version>
USER_AGENT = f"acatalogue/0.2 (https://github.com/virideanil/acatalogue) Python-urllib/{urllib.request.__version__}"

# (verdict, seconds to wait, message): verdict is 'ok', 'retry' or 'fail'
Check = Callable[[bytes], tuple[str, float | None, str | None]]


class FetchError(RuntimeError):
    pass


def mediawiki_check(raw: bytes) -> tuple[str, float | None, str | None]:
    """MediaWiki Action API bodies report errors with HTTP 200: never store them as data."""
    try:
        data = json.loads(raw)
    except ValueError:
        return "fail", None, "response is not JSON"
    err = data.get("error") if isinstance(data, dict) else None
    if not err:
        return "ok", None, None
    code = err.get("code", "?")
    if code == "maxlag":
        return "retry", max(5.0, float(err.get("lag") or 5)), f"maxlag: {err.get('info', '')}"
    if code in ("ratelimited", "readonly", "internal_api_error_DBConnectionError"):
        return "retry", 30.0, f"{code}: {err.get('info', '')}"
    return "fail", None, f"API error {code}: {err.get('info', '')}"


def contains_check(*needles: bytes) -> Check:
    """For pages scraped as served: an interstitial, captcha or error page must not be sealed as the page."""
    def check(raw: bytes) -> tuple[str, float | None, str | None]:
        missing = [n.decode("utf-8", "replace") for n in needles if n not in raw]
        return ("fail", None, f"expected content not found: {', '.join(missing)}") if missing else ("ok", None, None)
    return check


def sparql_check(raw: bytes) -> tuple[str, float | None, str | None]:
    try:
        data = json.loads(raw)
    except ValueError:
        return "fail", None, "SPARQL response is not JSON"
    if not isinstance(data, dict) or "results" not in data:
        return "fail", None, "SPARQL response has no results"
    return "ok", None, None


class Fetcher:
    """`max_retries` bounds attempts after errors (5xx other than 503, network failures). Signals that
    the server is busy (429, 503, maxlag, rate limits) are waited out with exponential backoff, honouring
    Retry-After and the reported lag, for up to `patience` seconds in total per item."""

    def __init__(self, corpus: CorpusFile, *, min_interval: float = 1.0, max_retries: int = 6,
                 max_wait: float = 120.0, patience: float = 900.0, timeout: float = 60.0, verbose: bool = True):
        self.corpus = corpus
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.max_wait = max_wait
        self.patience = patience
        self.timeout = timeout
        self.verbose = verbose
        self._last = 0.0

    def _say(self, msg: str) -> None:
        if self.verbose:
            print(msg, flush=True)

    def _pace(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def fetch(self, item_name: str, url: str, *, data: dict | None = None, headers: dict | None = None,
              license: str | None = None, attribution: str | None = None, check: Check | None = None) -> bytes:
        if self.corpus.has(item_name):
            return self.corpus.get(item_name)
        body = urllib.parse.urlencode(data).encode("utf-8") if data is not None else None
        hdrs = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
        if headers:
            hdrs.update(headers)
        method = "POST" if body is not None else "GET"
        backoff, waited, errors, attempt = 2.0, 0.0, 0, 0

        def wait(seconds: float, why: str, busy: bool) -> None:
            """Sleep before the next attempt, or raise when the budget for this kind of trouble is spent."""
            nonlocal backoff, waited, errors
            if busy:
                seconds = min(max(seconds, backoff), self.max_wait)
                if waited + seconds > self.patience:
                    raise FetchError(f"{url}: still busy after waiting {waited:.0f}s: {why}")
            else:
                errors += 1
                if errors >= self.max_retries:
                    raise FetchError(f"{url}: gave up after {errors} failed attempts: {why}")
                seconds = min(max(seconds, backoff), self.max_wait)
            self._say(f"  {why} on {item_name}; waiting {seconds:.0f}s (attempt {attempt})")
            time.sleep(seconds)
            waited += seconds
            backoff = min(backoff * 2, self.max_wait)

        while True:
            attempt += 1
            self._pace()
            req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
            retrieved_at = utcnow()
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read()
                    status = resp.status
                    ctype = resp.headers.get("Content-Type")
                    encoding = (resp.headers.get("Content-Encoding") or "").lower()
                    retry_after = resp.headers.get("Retry-After")
                if encoding == "gzip":
                    raw = gzip.decompress(raw)
            except urllib.error.HTTPError as exc:
                status = exc.code
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                self.corpus.log(url, status, note=f"attempt {attempt}; retry-after={retry_after}")
                if status in (429, 500, 502, 503, 504):
                    asked = float(retry_after) if retry_after and retry_after.isdigit() else 0.0
                    wait(asked, f"HTTP {status}", busy=status in (429, 503))
                    continue
                raise FetchError(f"{url}: HTTP {status}") from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                self.corpus.log(url, None, note=f"attempt {attempt}; {exc}")
                wait(0.0, f"network error ({exc})", busy=False)
                continue
            if check is not None:
                verdict, asked, message = check(raw)
                if verdict != "ok":
                    self.corpus.log(url, status, note=f"attempt {attempt}; not stored: {message}")
                    if verdict == "retry":
                        if retry_after and retry_after.isdigit():
                            asked = max(asked or 0.0, float(retry_after))
                        wait(asked or 0.0, message or "retry", busy=True)
                        continue
                    raise FetchError(f"{url}: {message}")
            digest = self.corpus.add(item_name, raw, url=url, method=method,
                                     request_body=body.decode("utf-8") if body else None, status=status,
                                     content_type=ctype, retrieved_at=retrieved_at,
                                     license=license, attribution=attribution)
            note = f"attempt {attempt}; stored as {item_name}" + ("; gzip decoded before hashing" if encoding == "gzip" else "")
            self.corpus.log(url, status, sha512=digest, note=note)
            return raw
