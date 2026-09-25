"""Polite HTTP into a named corpus: every response is stored as exact bytes, every attempt is logged.

Resumable: an item name that already exists in the corpus is returned from the corpus,
not fetched again, so an interrupted run continues where it stopped.
"""
from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request

from .corpusfile import CorpusFile
from .util import utcnow

USER_AGENT = "acatalogue/0.1 (+https://github.com/virideanil/acatalogue; knowledge catalogue builder)"


class FetchError(RuntimeError):
    pass


class Fetcher:
    def __init__(self, corpus: CorpusFile, *, min_interval: float = 1.0, max_retries: int = 6,
                 max_wait: float = 120.0, timeout: float = 60.0, verbose: bool = True):
        self.corpus = corpus
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.max_wait = max_wait
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
              license: str | None = None, attribution: str | None = None) -> bytes:
        if self.corpus.has(item_name):
            return self.corpus.get(item_name)
        body = urllib.parse.urlencode(data).encode("utf-8") if data is not None else None
        hdrs = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
        if headers:
            hdrs.update(headers)
        method = "POST" if body is not None else "GET"
        delay = 2.0
        for attempt in range(1, self.max_retries + 1):
            self._pace()
            req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
            retrieved_at = utcnow()
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read()
                    status = resp.status
                    ctype = resp.headers.get("Content-Type")
            except urllib.error.HTTPError as exc:
                status = exc.code
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                self.corpus.log(url, status, note=f"attempt {attempt}; retry-after={retry_after}")
                if status in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    wait = delay
                    if retry_after and retry_after.isdigit():
                        wait = max(wait, float(retry_after))
                    if wait > self.max_wait:
                        raise FetchError(f"{url}: server asked us to wait {wait:.0f}s (> {self.max_wait:.0f}s)")
                    self._say(f"  {status} on {item_name}; waiting {wait:.0f}s (attempt {attempt})")
                    time.sleep(wait)
                    delay = min(delay * 2, self.max_wait)
                    continue
                raise FetchError(f"{url}: HTTP {status}") from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                self.corpus.log(url, None, note=f"attempt {attempt}; {exc}")
                if attempt < self.max_retries:
                    self._say(f"  network error on {item_name}: {exc}; retrying in {delay:.0f}s")
                    time.sleep(delay)
                    delay = min(delay * 2, self.max_wait)
                    continue
                raise FetchError(f"{url}: {exc}") from exc
            digest = self.corpus.add(item_name, raw, url=url, method=method,
                                     request_body=body.decode("utf-8") if body else None, status=status,
                                     content_type=ctype, retrieved_at=retrieved_at,
                                     license=license, attribution=attribution)
            self.corpus.log(url, status, sha512=digest, note=f"attempt {attempt}; stored as {item_name}")
            return raw
        raise FetchError(f"{url}: gave up after {self.max_retries} attempts")
