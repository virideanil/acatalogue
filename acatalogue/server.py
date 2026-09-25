"""`acat serve`: the JSON API of docs/API.md plus the particle field, standard library only.

The database is opened read-only for every request; nothing a browser sends can write to it.
Binds to 127.0.0.1 unless told otherwise.
"""
from __future__ import annotations

import json
import mimetypes
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import db as dbm
from .grep import GrepError, grep
from .util import REPO_ROOT
from .views import audit, graph, node, stats

VIZ_ROOT = REPO_ROOT / "viz"
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("application/json", ".json")
mimetypes.add_type("text/css", ".css")


class _Cache:
    """Results that only change when the database file changes."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.lock = threading.Lock()
        self.stamp = None
        self.values: dict[str, bytes] = {}

    def get(self, key: str, make) -> bytes:
        stamp = self.db_path.stat().st_mtime_ns
        with self.lock:
            if stamp != self.stamp:
                self.values.clear()
                self.stamp = stamp
            if key not in self.values:
                self.values[key] = make()
            return self.values[key]


def _json(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "acatalogue/0.1"
    db_path: Path = dbm.DEFAULT_DB
    cache: _Cache

    def log_message(self, fmt: str, *args) -> None:  # quieter than the default, still on stderr
        sys.stderr.write(f"{self.address_string()} {fmt % args}\n")

    def _send(self, status: int, body: bytes, ctype: str, *, cache: str = "no-store") -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _api_json(self, obj, status: int = 200) -> None:
        self._send(status, obj if isinstance(obj, bytes) else _json(obj), "application/json; charset=utf-8")

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        url = urlparse(self.path)
        try:
            if url.path.startswith("/api/"):
                self._api(url.path, parse_qs(url.query))
            else:
                self._static(url.path)
        except BrokenPipeError:
            pass
        except Exception as exc:  # report, never hide
            self._api_json({"error": f"{type(exc).__name__}: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _api(self, path: str, q: dict[str, list[str]]) -> None:
        def arg(name: str, default: str | None = None) -> str | None:
            return q.get(name, [default])[0]

        if not self.db_path.exists():
            self._api_json({"error": f"{self.db_path} does not exist — run `acat build`"}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        conn = dbm.connect(self.db_path, readonly=True)
        try:
            if path == "/api/graph":
                self._api_json(self.cache.get("graph", lambda: _json(graph(conn))))
            elif path == "/api/audit":
                self._api_json(self.cache.get("audit", lambda: _json(audit(conn))))
            elif path == "/api/stats":
                self._api_json(stats(conn, str(self.db_path)))
            elif path == "/api/node":
                ident = arg("id")
                rec = node(conn, ident) if ident else None
                if rec is None and ident:                  # a term of an attached source, read in place
                    from .views import source_node
                    rec = source_node(conn, ident)
                if rec is None:
                    self._api_json({"error": f"no concept {ident!r}"}, HTTPStatus.NOT_FOUND)
                else:
                    self._api_json(rec)
            elif path == "/api/grep":
                pattern = arg("q", "")
                try:
                    res = grep(conn, pattern, mode=arg("mode", "words"), scope=arg("scope", "all"),
                               limit=int(arg("limit", "50")), under=arg("under"), lang=arg("lang"))
                except (GrepError, ValueError) as exc:
                    self._api_json({"query": pattern, "error": str(exc), "hits": [], "sql": []},
                                   HTTPStatus.BAD_REQUEST)
                    return
                self._api_json(res.as_dict())
            elif path == "/api/sources":
                from .leansearch import sources
                self._api_json({"sources": sources(conn)})
            elif path == "/api/sources/search":
                from .leansearch import search
                schemes = [x for x in (arg("scheme") or "").split(",") if x]
                self._api_json({"query": arg("q", ""), "hits": search(conn, arg("q", ""), schemes=schemes or None,
                                                                       limit=int(arg("limit", "20")))})
            elif path == "/api/sources/record":
                from .leansearch import record
                rec = record(conn, arg("id") or "")
                if rec is None:
                    self._api_json({"error": f"no term {arg('id')!r} in an integrated source"}, HTTPStatus.NOT_FOUND)
                else:
                    self._api_json(rec)
            else:
                self._api_json({"error": f"unknown endpoint {path}"}, HTTPStatus.NOT_FOUND)
        finally:
            conn.close()

    def _static(self, path: str) -> None:
        rel = path.lstrip("/") or "index.html"
        target = (VIZ_ROOT / rel).resolve()
        if VIZ_ROOT.resolve() not in target.parents and target != VIZ_ROOT.resolve():
            self._send(HTTPStatus.FORBIDDEN, b"forbidden", "text/plain; charset=utf-8")
            return
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain; charset=utf-8")
            return
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/json",):
            ctype += "; charset=utf-8"
        self._send(HTTPStatus.OK, target.read_bytes(), ctype, cache="no-cache")


def serve(db_path: str | Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    db_path = Path(db_path).resolve()
    handler = type("BoundHandler", (Handler,), {"db_path": db_path, "cache": _Cache(db_path)})
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"acatalogue: http://{host}:{port}/  (database {db_path}, read-only)", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
