"""Named corpora: dated, self-describing SQLite files that hold exact source bytes.

A corpus lives at `corpora/<name>/corpus.sqlite`, where the name ends in its creation date
(`wikipedia-en-intros-20260925`). Inside:

  meta       name, title, license, description, created_at, sealed_at, manifest_sha512
  sqlar      the bytes, in the standard SQLite Archive table (`sqlite3 corpus.sqlite -Atv`
             lists them); each entry is named `sha512/<hex>` so identical bytes are stored once
  item       named items -> sha512, with where/when/how each was obtained and its license
  fetch_log  every attempt, including refusals and retries

Once sealed, triggers refuse any further change: a sealed corpus is a fixed point you can
cite. New data goes into a new dated corpus; nothing is overwritten.
"""
from __future__ import annotations

import sqlite3
import zlib
from pathlib import Path

from .util import REPO_ROOT, manifest_sha512, sha512_bytes, utcnow

CORPORA_DIR = REPO_ROOT / "corpora"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sqlar (name TEXT PRIMARY KEY, mode INT, mtime INT, sz INT, data BLOB);
CREATE TABLE IF NOT EXISTS item (
  name          TEXT PRIMARY KEY,
  sha512        TEXT NOT NULL CHECK (length(sha512) = 128),
  bytes         INTEGER NOT NULL,
  url           TEXT,
  method        TEXT,
  request_body  TEXT,
  status        INTEGER,
  content_type  TEXT,
  retrieved_at  TEXT NOT NULL,
  license       TEXT,
  attribution   TEXT
);
CREATE TABLE IF NOT EXISTS fetch_log (
  seq    INTEGER PRIMARY KEY AUTOINCREMENT,
  at     TEXT NOT NULL,
  url    TEXT NOT NULL,
  status INTEGER,
  sha512 TEXT,
  note   TEXT
);
CREATE TRIGGER IF NOT EXISTS item_sealed_i BEFORE INSERT ON item
  WHEN (SELECT value FROM meta WHERE key = 'sealed_at') IS NOT NULL
  BEGIN SELECT RAISE(ABORT, 'corpus is sealed'); END;
CREATE TRIGGER IF NOT EXISTS item_sealed_u BEFORE UPDATE ON item
  WHEN (SELECT value FROM meta WHERE key = 'sealed_at') IS NOT NULL
  BEGIN SELECT RAISE(ABORT, 'corpus is sealed'); END;
CREATE TRIGGER IF NOT EXISTS item_never_deleted BEFORE DELETE ON item
  BEGIN SELECT RAISE(ABORT, 'corpus items are never deleted'); END;
CREATE TRIGGER IF NOT EXISTS sqlar_sealed_i BEFORE INSERT ON sqlar
  WHEN (SELECT value FROM meta WHERE key = 'sealed_at') IS NOT NULL
  BEGIN SELECT RAISE(ABORT, 'corpus is sealed'); END;
CREATE TRIGGER IF NOT EXISTS sqlar_no_update BEFORE UPDATE ON sqlar
  BEGIN SELECT RAISE(ABORT, 'stored bytes never change'); END;
CREATE TRIGGER IF NOT EXISTS sqlar_never_deleted BEFORE DELETE ON sqlar
  BEGIN SELECT RAISE(ABORT, 'stored bytes are never deleted'); END;
CREATE TRIGGER IF NOT EXISTS meta_sealed_u BEFORE UPDATE ON meta
  WHEN (SELECT value FROM meta WHERE key = 'sealed_at') IS NOT NULL
  BEGIN SELECT RAISE(ABORT, 'corpus is sealed'); END;
"""


def corpus_path(name: str) -> Path:
    return CORPORA_DIR / name / "corpus.sqlite"


class CorpusFile:
    def __init__(self, path: str | Path, *, create: bool = False, name: str | None = None,
                 title: str | None = None, license: str | None = None, description: str | None = None,
                 readonly: bool = False):
        self.path = Path(path)
        if not self.path.exists():
            if not create:
                raise FileNotFoundError(self.path)
            if not (name and title):
                raise ValueError("a new corpus needs a name and a title")
            self.path.parent.mkdir(parents=True, exist_ok=True)
        if readonly:
            self.conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        else:
            self.conn = sqlite3.connect(self.path)
            self.conn.executescript(_SCHEMA)
        self.conn.row_factory = sqlite3.Row
        if create and not readonly and self.meta().get("name") is None:
            now = utcnow()
            rows = {"name": name, "title": title, "created_at": now, "format": "acatalogue-corpus/1"}
            if license:
                rows["license"] = license
            if description:
                rows["description"] = description
            self.conn.executemany("INSERT INTO meta(key, value) VALUES (?, ?)", rows.items())
            self.conn.commit()

    # ── reading ──
    def meta(self) -> dict[str, str]:
        return {r["key"]: r["value"] for r in self.conn.execute("SELECT key, value FROM meta")}

    @property
    def name(self) -> str:
        return self.meta()["name"]

    @property
    def sealed(self) -> bool:
        return "sealed_at" in self.meta()

    def has(self, item_name: str) -> bool:
        return self.conn.execute("SELECT 1 FROM item WHERE name = ?", (item_name,)).fetchone() is not None

    def items(self) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM item ORDER BY name"))

    def item(self, item_name: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM item WHERE name = ?", (item_name,)).fetchone()

    def blob(self, digest: str) -> bytes:
        row = self.conn.execute("SELECT sz, data FROM sqlar WHERE name = ?", (f"sha512/{digest}",)).fetchone()
        if row is None:
            raise KeyError(digest)
        sz, data = row
        raw = data if len(data) == sz else zlib.decompress(data)
        if sha512_bytes(raw) != digest:
            raise ValueError(f"stored bytes for {digest[:16]}… fail their SHA-512 check")
        return raw

    def get(self, item_name: str) -> bytes:
        row = self.item(item_name)
        if row is None:
            raise KeyError(item_name)
        return self.blob(row["sha512"])

    # ── writing ──
    def add(self, item_name: str, data: bytes, *, url: str | None = None, method: str = "GET",
            request_body: str | None = None, status: int | None = 200, content_type: str | None = None,
            retrieved_at: str | None = None, license: str | None = None, attribution: str | None = None) -> str:
        digest = sha512_bytes(data)
        existing = self.item(item_name)
        if existing is not None:
            if existing["sha512"] != digest:
                raise ValueError(f"item {item_name!r} already holds different bytes; use a new item name")
            return digest
        packed = zlib.compress(data, 9)
        stored = packed if len(packed) < len(data) else data
        self.conn.execute(
            "INSERT OR IGNORE INTO sqlar(name, mode, mtime, sz, data) VALUES (?, ?, strftime('%s','now'), ?, ?)",
            (f"sha512/{digest}", 0o100644, len(data), stored),
        )
        self.conn.execute(
            "INSERT INTO item(name, sha512, bytes, url, method, request_body, status, content_type,"
            " retrieved_at, license, attribution) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (item_name, digest, len(data), url, method, request_body, status, content_type,
             retrieved_at or utcnow(), license, attribution),
        )
        self.conn.commit()
        return digest

    def log(self, url: str, status: int | None, *, sha512: str | None = None, note: str | None = None) -> None:
        self.conn.execute("INSERT INTO fetch_log(at, url, status, sha512, note) VALUES (?,?,?,?,?)",
                          (utcnow(), url, status, sha512, note))
        self.conn.commit()

    def manifest(self) -> str:
        return manifest_sha512([(r["name"], r["sha512"]) for r in self.conn.execute("SELECT name, sha512 FROM item")])

    def seal(self) -> str:
        if self.sealed:
            return self.meta()["manifest_sha512"]
        digest = self.manifest()
        n = self.conn.execute("SELECT count(*) FROM item").fetchone()[0]
        self.conn.executemany("INSERT INTO meta(key, value) VALUES (?, ?)",
                              [("items", str(n)), ("manifest_sha512", digest), ("sealed_at", utcnow())])
        self.conn.commit()
        self.conn.execute("VACUUM")
        return digest

    def verify(self) -> tuple[bool, str]:
        """Re-hash every stored item and compare with the sealed manifest."""
        bad = []
        for r in self.conn.execute("SELECT name, sha512 FROM item"):
            try:
                self.blob(r["sha512"])
            except (KeyError, ValueError) as exc:
                bad.append(f"{r['name']}: {exc}")
        if bad:
            return False, "; ".join(bad[:5])
        m = self.meta()
        if "manifest_sha512" in m and m["manifest_sha512"] != self.manifest():
            return False, "manifest does not match the sealed manifest_sha512"
        return True, f"{self.name}: every item re-hashed OK"

    def close(self) -> None:
        self.conn.close()


def list_corpora() -> list[Path]:
    return sorted(CORPORA_DIR.glob("*/corpus.sqlite"))
