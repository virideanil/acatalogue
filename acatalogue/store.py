"""The local store: where selected sources are downloaded, sealed, converted and kept, on this machine.

    store/                       ACAT_STORE overrides the place (default: <repo>/store, gitignored)
      store.sqlite               selection, sources added here, downloads, jobs, events (SQLite, not JSON)
      raw/<source>/<yyyymmdd>/   the files exactly as published (a .part file while one is downloading)
      corpora/<source>-<date>/   a sealed manifest per completed download: every file's SHA-512, size,
                                 URL, time and licence; the bytes stay in raw/ (external items)
      lean/<source>/             converted lean databases (acatalogue/lean.py), one per sealed manifest
      tmp/                       scratch for converters

Nothing here is edited by hand. Raw files are never modified once complete; a newer download of a
source is a new dated directory and a new manifest. Removing raw bytes is `acat sources prune`, which
ledgers what it removed (the manifests keep their SHA-512s).
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from .util import REPO_ROOT, utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
-- the sources chosen as this store's starting point
CREATE TABLE IF NOT EXISTS selection (
  source      TEXT PRIMARY KEY,
  selected_at TEXT NOT NULL,
  via         TEXT NOT NULL,                -- 'user' or 'preset:<name>'
  mode        TEXT CHECK (mode IN ('full', 'attach'))   -- NULL: the registry's default
);
-- sources added on this machine (a URL or a local file), with the registry's columns
CREATE TABLE IF NOT EXISTS user_source (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, publisher TEXT, perspective TEXT, domains TEXT, kind TEXT,
  languages TEXT, license TEXT, license_url TEXT, homepage TEXT, "update" TEXT, access TEXT,
  converter TEXT NOT NULL, options TEXT, scheme TEXT, integrate TEXT, iri_prefixes TEXT, curie_prefixes TEXT,
  wikidata_property TEXT, notes TEXT, added_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_file (
  source TEXT NOT NULL, name TEXT NOT NULL, url TEXT NOT NULL, format TEXT, bytes INTEGER, checksum TEXT,
  role TEXT, PRIMARY KEY (source, name)
);
-- one row per file of a snapshot; resumable (bytes_done, validators) and verified (sha512, checksum)
CREATE TABLE IF NOT EXISTS download (
  source        TEXT NOT NULL,
  snapshot      TEXT NOT NULL,              -- '<source>-<yyyymmdd>' (the manifest's name)
  name          TEXT NOT NULL,              -- file name inside the snapshot
  url           TEXT NOT NULL,
  path          TEXT NOT NULL,              -- relative to the store (or absolute, for a local file)
  state         TEXT NOT NULL CHECK (state IN ('pending', 'running', 'done', 'failed')),
  bytes_total   INTEGER,
  bytes_done    INTEGER NOT NULL DEFAULT 0,
  etag          TEXT,
  last_modified TEXT,
  content_type  TEXT,
  sha512        TEXT,
  checksum      TEXT,                       -- the publisher's, e.g. 'sha256:<hex>'
  checksum_ok   INTEGER,                    -- 1 matched, 0 differed, NULL none published
  attempts      INTEGER NOT NULL DEFAULT 0,
  started_at    TEXT,
  finished_at   TEXT,
  error         TEXT,
  PRIMARY KEY (snapshot, name)
);
-- pipeline stages per snapshot: convert (raw -> lean) and integrate (lean -> catalogue)
CREATE TABLE IF NOT EXISTS job (
  snapshot      TEXT NOT NULL,
  stage         TEXT NOT NULL CHECK (stage IN ('convert', 'integrate')),
  source        TEXT NOT NULL,
  state         TEXT NOT NULL CHECK (state IN ('pending', 'running', 'done', 'failed')),
  input         TEXT,                       -- manifest SHA-512 (convert) or lean file SHA-512 (integrate)
  output        TEXT,                       -- lean file path (convert)
  output_sha512 TEXT,
  started_at    TEXT,
  finished_at   TEXT,
  detail        TEXT,                       -- JSON counts
  error         TEXT,
  PRIMARY KEY (snapshot, stage)
);
CREATE TABLE IF NOT EXISTS event (
  seq     INTEGER PRIMARY KEY AUTOINCREMENT,
  at      TEXT NOT NULL,
  source  TEXT,
  stage   TEXT,
  level   TEXT NOT NULL CHECK (level IN ('info', 'warn', 'error')),
  message TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS event_append_only_u BEFORE UPDATE ON event
  BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS event_append_only_d BEFORE DELETE ON event
  BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
"""


def root() -> Path:
    return Path(os.environ.get("ACAT_STORE") or (REPO_ROOT / "store")).resolve()


class Store:
    """The store directory and its database. One writer at a time per process; threads share it
    through `lock`-free short statements (sqlite3 serializes; busy timeout covers other processes)."""

    def __init__(self, path: str | Path | None = None):
        self.root = Path(path).resolve() if path else root()
        for d in ("raw", "corpora", "lean", "tmp"):
            (self.root / d).mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "store.sqlite"
        self.conn = sqlite3.connect(self.db_path, timeout=60.0, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self.conn.executescript(SCHEMA)
        if self.conn.execute("SELECT value FROM meta WHERE key = 'created_at'").fetchone() is None:
            self.conn.execute("INSERT INTO meta(key, value) VALUES ('created_at', ?), ('format', 'acatalogue-store/1')",
                              (utcnow(),))

    # ── paths ──
    def rel(self, p: Path) -> str:
        """A path inside the store as a store-relative POSIX string; outside it, absolute."""
        p = Path(p).resolve()
        try:
            return p.relative_to(self.root).as_posix()
        except ValueError:
            return str(p)

    def abs(self, stored: str) -> Path:
        p = Path(stored)
        return p if p.is_absolute() else self.root / p

    def raw_dir(self, source: str, day: str) -> Path:
        return self.root / "raw" / source / day

    def corpus_path(self, snapshot: str) -> Path:
        return self.root / "corpora" / snapshot / "corpus.sqlite"

    def lean_dir(self, source: str) -> Path:
        return self.root / "lean" / source

    # ── selection ──
    def selected(self) -> dict[str, sqlite3.Row]:
        return {r["source"]: r for r in self.conn.execute("SELECT * FROM selection ORDER BY source")}

    def select(self, source: str, via: str = "user", mode: str | None = None) -> bool:
        cur = self.conn.execute("INSERT INTO selection(source, selected_at, via, mode) VALUES (?,?,?,?)"
                                " ON CONFLICT(source) DO UPDATE SET mode = coalesce(excluded.mode, selection.mode)",
                                (source, utcnow(), via, mode))
        self.event(source, "select", "info", f"selected via {via}" + (f", mode {mode}" if mode else ""))
        return cur.rowcount > 0

    def deselect(self, source: str) -> bool:
        cur = self.conn.execute("DELETE FROM selection WHERE source = ?", (source,))
        if cur.rowcount:
            self.event(source, "select", "info", "deselected")
        return cur.rowcount > 0

    # ── events ──
    def event(self, source: str | None, stage: str | None, level: str, message: str) -> None:
        self.conn.execute("INSERT INTO event(at, source, stage, level, message) VALUES (?,?,?,?,?)",
                          (utcnow(), source, stage, level, message))

    def close(self) -> None:
        self.conn.close()
