"""Hashing, time, identifiers, and canonical JSON — the small things every layer shares."""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# ─── SHA-512 at the exact-byte boundary ──────────────────────────────────────


def sha512_bytes(data: bytes) -> str:
    return hashlib.sha512(data).hexdigest()


def sha512_file(path: str | Path, chunk: int = 1 << 20) -> tuple[str, int]:
    """Return (hex digest, byte count) of a file, streamed."""
    h = hashlib.sha512()
    n = 0
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
            n += len(block)
    return h.hexdigest(), n


def manifest_sha512(pairs: list[tuple[str, str]]) -> str:
    """Stable identity of a collection: SHA-512 over sorted 'name<TAB>sha512<LF>' lines."""
    lines = "".join(f"{name}\t{digest}\n" for name, digest in sorted(pairs))
    return sha512_bytes(lines.encode("utf-8"))


# ─── time ────────────────────────────────────────────────────────────────────


def utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today_compact() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d")


# ─── canonical JSON (for hashing and for stable diffs) ───────────────────────


def cjson(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


# ─── scoped, resolvable identifiers ──────────────────────────────────────────

SCOPES = {
    "acat": "a concept in the authored ACAT compendium",
    "space": "a UN M49 region, country or area (where)",
    "kind": "an ontological kind (what sort of thing)",
    "epistemic": "an epistemic status (how it is known)",
    "udc": "a main class of the Universal Decimal Classification",
    "ddc": "a main class of the Dewey Decimal Classification",
    "lcc": "a class of the Library of Congress Classification",
    "propaedia": "a part of the Britannica Propaedia outline of knowledge",
    "wd": "a Wikidata item or property",
    "doc": "a document in a named corpus",
    "src": "exact source bytes, addressed by SHA-512",
}

_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]*$")


def scoped(scope: str, code: str) -> str:
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope!r}")
    if scope != "doc" and not _CODE_RE.match(code):
        raise ValueError(f"bad code {code!r} for scope {scope!r}")
    return f"{scope}/{code}"


def split_id(identifier: str) -> tuple[str, str]:
    scope, sep, code = identifier.partition("/")
    if not sep or scope not in SCOPES or not code:
        raise ValueError(f"not a scoped id: {identifier!r}")
    return scope, code


def src_id(digest: str) -> str:
    return f"src/sha512:{digest}"


def slugify(text: str) -> str:
    """ASCII slug. Used for new codes only; codes never change once minted."""
    norm = unicodedata.normalize("NFKD", text)
    ascii_ = norm.encode("ascii", "ignore").decode("ascii").lower()
    ascii_ = re.sub(r"[^a-z0-9]+", "-", ascii_).strip("-")
    return ascii_ or "x"
