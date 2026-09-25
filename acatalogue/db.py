"""Opening the catalogue database: schema, pragmas, and the SQL functions the grepper needs."""
from __future__ import annotations

import re
import sqlite3
from functools import lru_cache
from pathlib import Path

from .textkeys import fold_key, icontains, nfc
from .util import REPO_ROOT

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
DEFAULT_DB = REPO_ROOT / "data" / "acatalogue.sqlite"
MIN_SQLITE = (3, 38, 0)


@lru_cache(maxsize=256)
def _compiled(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


def _regexp(pattern: str | None, text: str | None) -> int:
    """SQL: `text REGEXP pattern` (SQLite calls regexp(pattern, text)); matched on NFC text."""
    if pattern is None or text is None:
        return 0
    return 1 if _compiled(pattern).search(nfc(text)) else 0


def _icontains(text: str | None, needle: str | None) -> int:
    """SQL: acat_icontains(text, needle) — the one case-insensitive substring test (textkeys.icontains)."""
    return 1 if icontains(text, needle) else 0


def register_functions(conn: sqlite3.Connection) -> None:
    conn.create_function("regexp", 2, _regexp, deterministic=True)
    conn.create_function("acat_icontains", 2, _icontains, deterministic=True)
    conn.create_function("acat_key", 1, lambda s: None if s is None else fold_key(nfc(s)), deterministic=True)


def check_sqlite() -> None:
    if sqlite3.sqlite_version_info < MIN_SQLITE:
        raise RuntimeError(
            f"SQLite {sqlite3.sqlite_version} is too old; acatalogue needs >= "
            + ".".join(map(str, MIN_SQLITE))
            + " (FTS5 trigram tokenizer)."
        )
    probe = sqlite3.connect(":memory:")
    try:
        probe.execute("CREATE VIRTUAL TABLE t USING fts5(x, tokenize='trigram')")
    except sqlite3.OperationalError as exc:  # pragma: no cover - depends on the build
        raise RuntimeError(f"this SQLite build lacks FTS5 with the trigram tokenizer: {exc}") from exc
    finally:
        probe.close()


def connect(path: str | Path = DEFAULT_DB, *, readonly: bool = False, create: bool = False) -> sqlite3.Connection:
    """Open the catalogue. Read-only connections cannot write even by accident."""
    path = Path(path)
    if readonly:
        if not path.exists():
            raise FileNotFoundError(f"{path} does not exist — run `acat build` first")
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
        conn.execute("PRAGMA query_only = 1")
    else:
        if not path.exists() and not create:
            raise FileNotFoundError(f"{path} does not exist — run `acat build` first")
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    register_functions(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    check_sqlite()
    from .migrate import migrate
    migrate(conn)                      # upgrade an older database in place first (rows copied, ledgered)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


def is_catalogue(conn: sqlite3.Connection) -> bool:
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    return {"concept", "passage", "ledger", "source"} <= names
