"""Text keys for search: one definition of "case-insensitive", and trigram queries from regexes.

Case-insensitive, everywhere in acatalogue, means exactly what Python's `re.IGNORECASE` means on
NFC-normalised text. SQLite's own folding (Unicode 6.1 tables) is narrower — with it, "istanbul"
does not find "İstanbul" — so the trigram indexes are built over a *key*: each code point replaced
by one representative of its `re.IGNORECASE` equivalence class, indexed with
`trigram case_sensitive 1`. Key folding is length-preserving and per code point, so any string that
matches under `re.IGNORECASE` has a key that is a substring of the text's key: the index can only
over-select, and every candidate is then checked with Python's `re`. No true match is ever dropped.

`trigram_query()` follows Russ Cox, "Regular Expression Matching with a Trigram Index" (2012, the
algorithm behind Google Code Search), over Python's own regex parse tree and in key space. It never
emits a string shorter than three characters and an OR is unindexable if any branch is.
"""
from __future__ import annotations

import re
import unicodedata

try:                                            # Python >= 3.11
    import _sre
    from re import _casefix, _constants as C, _parser as P
except ImportError:                             # pragma: no cover
    raise RuntimeError("acatalogue needs Python >= 3.11 (re._parser / re._casefix)")

KEY_VERSION = f"py-re-ignorecase/unicode-{unicodedata.unidata_version}"
_lower = _sre.unicode_tolower
_EXTRA = _casefix._EXTRA_CASES
_KEY: dict[int, int] = {}


def nfc(s: str) -> str:
    return s if unicodedata.is_normalized("NFC", s) else unicodedata.normalize("NFC", s)


def key_cp(cp: int) -> int:
    k = _KEY.get(cp)
    if k is None:
        lo = _lower(cp)
        k = _KEY[cp] = min((lo,) + _EXTRA.get(lo, ()))
    return k


def fold_key(s: str) -> str:
    """The case key of an (already NFC) string: same length, one code point per code point."""
    return "".join(chr(key_cp(ord(ch))) for ch in s)


def closure_violations(limit: int = 20) -> list[int]:
    """Code points whose key differs from the key of upper(lower(c)); must be empty for soundness."""
    bad = []
    for cp in range(0x110000):
        if 0xD800 <= cp <= 0xDFFF:
            continue
        up = chr(_lower(cp)).upper()
        if len(up) == 1 and key_cp(ord(up)) != key_cp(cp):
            bad.append(cp)
            if len(bad) >= limit:
                break
    return bad


def icontains(text: str | None, needle: str | None) -> bool:
    """The single case-insensitive substring test: Python re.IGNORECASE on NFC text."""
    if text is None or needle is None:
        return False
    return re.search(re.escape(nfc(needle)), nfc(text), re.IGNORECASE) is not None


def fts_phrase(s: str) -> str:
    return '"' + s.replace('"', '""') + '"'


def literal_query(needle: str) -> str | None:
    """FTS5 query over a key index for a case-insensitive literal, or None (too short to index)."""
    k = fold_key(nfc(needle))
    return fts_phrase(k) if len(k) >= 3 else None


# ─── Chinese / Japanese / Korean: overlapping character pairs for word search ──────────────────

_CJK = re.compile(r"[぀-ヿㇰ-ㇿ㐀-䶿一-鿿豈-﫿가-힯"
                  r"ᄀ-ᇿ㄰-㆏\U00020000-\U0003134f]+")


def has_cjk(s: str) -> bool:
    return _CJK.search(s) is not None


def cjk_bigrams(s: str) -> str:
    """Replace each run of CJK characters by its overlapping pairs ('物理学' -> '物理 理学'), so a
    word tokenizer can match two-character words that unicode61 would bury inside a longer run."""
    def pairs(m: re.Match) -> str:
        run = m.group(0)
        return run if len(run) < 2 else " " + " ".join(run[i:i + 2] for i in range(len(run) - 1)) + " "
    return _CJK.sub(pairs, s)


def cjk_query(q: str) -> str:
    """An FTS5 query for the pair index: each whitespace token becomes a phrase of its pairs."""
    parts = []
    for tok in nfc(q).split():
        bi = cjk_bigrams(tok).split()
        if bi:
            parts.append(fts_phrase(" ".join(bi)))
    return " ".join(parts)


# ─── Cox trigram queries from regular expressions ──────────────────────────────────────────────

MAX_EXACT, MAX_SET, MAX_CLASS = 7, 20, 30
ALL = ("ALL",)


def _q_and(a, b):
    if a == ALL:
        return b
    if b == ALL:
        return a
    parts = set()
    for x in (a, b):
        parts |= set(x[1]) if x[0] == "AND" else {x}
    return ("AND", frozenset(parts)) if len(parts) > 1 else next(iter(parts))


def _q_or(a, b):
    if a == ALL or b == ALL:
        return ALL
    parts = set()
    for x in (a, b):
        parts |= set(x[1]) if x[0] == "OR" else {x}
    return ("OR", frozenset(parts)) if len(parts) > 1 else next(iter(parts))


def _and_strings(q, strs):
    """q AND (one of strs occurs). Sound only when every string has at least three characters."""
    if not strs or min(len(s) for s in strs) < 3:
        return q
    o = None
    for s in sorted(strs):
        ph = ("PH", s)
        o = ph if o is None else _q_or(o, ph)
    return _q_and(q, o)


class _Info:
    __slots__ = ("can_empty", "exact", "prefix", "suffix", "match")

    def __init__(self, can_empty, exact, prefix, suffix, match=ALL):
        self.can_empty, self.exact, self.prefix, self.suffix, self.match = can_empty, exact, prefix, suffix, match


def _any_char():
    return _Info(False, None, {""}, {""})


def _any_match():
    return _Info(True, None, {""}, {""})


def _empty():
    return _Info(True, {""}, None, None)


def _exact(ss):
    return _Info(False, set(ss), None, None)


def _clean(t, suffix):
    out = []
    for s in sorted(t, key=lambda x: (x[::-1] if suffix else x)):
        if out and (s.endswith(out[-1]) if suffix else s.startswith(out[-1])):
            continue
        out.append(s)
    return set(out)


def _simplify_set(info, attr, suffix):
    t = getattr(info, attr)
    info.match = _and_strings(info.match, t)
    n = 3
    while n == 3 or len(t) > MAX_SET:
        t = {(s[len(s) - n + 1:] if suffix else s[:n - 1]) if len(s) >= n else s for s in t}
        n -= 1
    setattr(info, attr, _clean(t, suffix))


def _add_exact(info):
    if info.exact is not None:
        info.match = _and_strings(info.match, info.exact)


def _simplify(info, force):
    if info.exact is not None:
        ml = min((len(s) for s in info.exact), default=0)
        if len(info.exact) > MAX_EXACT or (ml >= 3 and force) or ml >= 4:
            _add_exact(info)
            info.prefix, info.suffix = set(), set()
            for s in info.exact:
                info.prefix.add(s if len(s) < 3 else s[:2])
                info.suffix.add(s if len(s) < 3 else s[-2:])
            info.exact = None
    if info.exact is None:
        _simplify_set(info, "prefix", False)
        _simplify_set(info, "suffix", True)
    return info


def _pfx(i):
    return set(i.exact) if i.exact is not None else set(i.prefix)


def _sfx(i):
    return set(i.exact) if i.exact is not None else set(i.suffix)


def _cross(a, b):
    return {x + y for x in a for y in b}


def _concat(x, y):
    xy = _Info(x.can_empty and y.can_empty, None, None, None, _q_and(x.match, y.match))
    if x.exact is not None and y.exact is not None:
        xy.exact = _cross(x.exact, y.exact)
    else:
        xy.prefix = (_cross(x.exact, y.prefix) if x.exact is not None
                     else (x.prefix | _pfx(y) if x.can_empty else set(x.prefix)))
        xy.suffix = (_cross(x.suffix, y.exact) if y.exact is not None
                     else (y.suffix | _sfx(x) if y.can_empty else set(y.suffix)))
    if (x.exact is None and y.exact is None and not x.can_empty and not y.can_empty
            and len(x.suffix) <= MAX_SET and len(y.prefix) <= MAX_SET
            and min(map(len, x.suffix)) + min(map(len, y.prefix)) >= 3):
        xy.match = _and_strings(xy.match, _cross(x.suffix, y.prefix))
    return _simplify(xy, False)


def _alternate(x, y):
    xy = _Info(x.can_empty or y.can_empty, None, None, None)
    if x.exact is not None and y.exact is not None:
        xy.exact = x.exact | y.exact
    elif x.exact is not None:
        xy.prefix, xy.suffix = x.exact | y.prefix, x.exact | y.suffix
        _add_exact(x)
    elif y.exact is not None:
        xy.prefix, xy.suffix = x.prefix | y.exact, x.suffix | y.exact
        _add_exact(y)
    else:
        xy.prefix, xy.suffix = x.prefix | y.prefix, x.suffix | y.suffix
    xy.match = _q_or(x.match, y.match)
    return _simplify(xy, False)


def _as_prefix_suffix(info):
    if info.exact is not None:
        info = _Info(info.can_empty, None, set(info.exact), set(info.exact), info.match)
    return info


def _class_members(av):
    out = set()
    for op, a in av:
        if op is C.LITERAL:
            out.add(chr(key_cp(a)))
        elif op is C.RANGE:
            lo, hi = a
            if hi - lo > MAX_CLASS:
                return None
            out |= {chr(key_cp(c)) for c in range(lo, hi + 1)}
        else:                                   # NEGATE, CATEGORY, ...: unbounded
            return None
        if len(out) > MAX_CLASS:
            return None
    return out


def _analyze_seq(items):
    info = _empty()
    for op, av in items:
        info = _concat(info, _analyze(op, av))
    return info


def _analyze(op, av):
    if op is C.LITERAL:
        return _exact({chr(key_cp(av))})
    if op is C.IN:
        m = _class_members(av)
        return _exact(m) if m else _any_char()
    if op in (C.ANY, C.NOT_LITERAL):
        return _any_char()
    if op in (C.AT, C.ASSERT, C.ASSERT_NOT):
        return _empty()                         # zero-width: no information
    if op is C.SUBPATTERN:
        return _analyze_seq(av[-1])
    if op is C.ATOMIC_GROUP:
        return _analyze_seq(av)
    if op is C.BRANCH:
        alts = [_analyze_seq(b) for b in av[1]]
        info = alts[0]
        for a in alts[1:]:
            info = _alternate(info, a)
        return info
    if op in (C.MAX_REPEAT, C.MIN_REPEAT, C.POSSESSIVE_REPEAT):
        lo, hi, sub = av
        if lo == 0:
            return _alternate(_analyze_seq(sub), _empty()) if hi == 1 else _any_match()
        info = _analyze_seq(sub)
        k = min(lo, 3)
        for _ in range(k - 1):
            info = _concat(info, _analyze_seq(sub))
        if hi != k:
            info = _concat(_as_prefix_suffix(info), _any_match())
        return info
    return _any_match()                         # back-references, conditionals, anything unknown


def _to_fts(q) -> str:
    if q[0] == "PH":
        return fts_phrase(q[1])
    if q[0] in ("AND", "OR"):
        return "(" + f" {q[0]} ".join(sorted(_to_fts(x) for x in q[1])) + ")"
    raise ValueError(q)


def trigram_query(pattern: str) -> str | None:
    """FTS5 MATCH expression (over a key index) that every match of `pattern` must satisfy,
    or None when the pattern gives no usable trigram (the caller then scans every row)."""
    try:
        parsed = P.parse(pattern)
    except Exception:
        return None
    info = _analyze_seq(parsed)
    _simplify(info, True)
    _add_exact(info)
    return None if info.match == ALL else _to_fts(info.match)
