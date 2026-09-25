"""The ledger: an append-only, hash-chained record of every action on the catalogue.

Each row's hash is SHA-512 over the previous row's hash and this row's fields, so any
edit to history breaks the chain and `acat verify` reports exactly where.
"""
from __future__ import annotations

import sqlite3

from .util import cjson, sha512_bytes, utcnow

GENESIS = "0" * 128
SEP = "\x1f"


def _row_hash(prev_hash: str, at: str, actor: str, action: str, target: str | None,
              detail: str | None, receipt: str | None, undo: str | None) -> str:
    fields = [prev_hash, at, actor, action, target or "", detail or "", receipt or "", undo or ""]
    return sha512_bytes(SEP.join(fields).encode("utf-8"))


def head(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT hash FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()
    return row[0] if row else GENESIS


def record(conn: sqlite3.Connection, actor: str, action: str, *, target: str | None = None,
           detail: dict | None = None, receipt: str | None = None, undo: str | None = None) -> str:
    """Append one row. The caller owns the transaction (commit happens with its work)."""
    at = utcnow()
    prev = head(conn)
    detail_s = cjson(detail) if detail is not None else None
    h = _row_hash(prev, at, actor, action, target, detail_s, receipt, undo)
    conn.execute(
        "INSERT INTO ledger(at, actor, action, target, detail, receipt, undo, prev_hash, hash)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (at, actor, action, target, detail_s, receipt, undo, prev, h),
    )
    return h


def verify(conn: sqlite3.Connection) -> tuple[bool, int, str]:
    """Recompute the chain. Returns (ok, rows checked, message)."""
    prev = GENESIS
    n = 0
    for row in conn.execute(
        "SELECT seq, at, actor, action, target, detail, receipt, undo, prev_hash, hash FROM ledger ORDER BY seq"
    ):
        seq, at, actor, action, target, detail, receipt, undo, prev_hash, h = tuple(row)
        if prev_hash != prev:
            return False, n, f"row {seq}: prev_hash does not match the previous row's hash"
        expect = _row_hash(prev, at, actor, action, target, detail, receipt, undo)
        if expect != h:
            return False, n, f"row {seq}: contents do not match its hash"
        prev = h
        n += 1
    return True, n, f"ledger intact: {n} rows, head {prev[:16]}…"
