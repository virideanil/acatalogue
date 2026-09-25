"""Prototype: Cox trigram-query extraction over Python's re parse tree, in a Python-folded 'key' space,
checked for false negatives against a full scan of the real labels. Plus tokenizer recall/precision checks."""
import re, sqlite3, time, unicodedata, random, os, sys, statistics
import _sre
from re import _casefix, _parser as P, _constants as C

DB = "/home/user/acatalogue/data/acatalogue.sqlite"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
rows = conn.execute("SELECT rowid, text, lang FROM label").fetchall()
texts = {rid: t for rid, t, _ in rows}

# ---- key fold: representative of Python re.IGNORECASE class (length-preserving, per code point)
lower = _sre.unicode_tolower; EXTRA = _casefix._EXTRA_CASES
_KEY = {}
def kc(cp):
    k = _KEY.get(cp)
    if k is None:
        lo = lower(cp); k = _KEY[cp] = min((lo,) + EXTRA.get(lo, ()))
    return k
def key(s): return "".join(chr(kc(ord(ch))) for ch in s)

# closure check needed for IGNORECASE ranges (sre tests lower(ch) and upper(lower(ch)))
bad = [cp for cp in range(0x110000) if not 0xD800 <= cp <= 0xDFFF
       and len(chr(lower(cp)).upper()) == 1 and kc(ord(chr(lower(cp)).upper())) != kc(cp)]
print("closure violations key(upper(lower(c))) != key(c):", len(bad), [hex(b) for b in bad[:8]])

# ---- Cox algorithm (after google/codesearch index/regexp.go), character trigrams, FTS5 phrases
MAX_EXACT, MAX_SET, MAX_CLASS = 7, 20, 30
ALL = ("ALL",)
def q_and(a, b):
    if a == ALL: return b
    if b == ALL: return a
    parts = set()
    for x in (a, b): parts |= set(x[1]) if x[0] == "AND" else {x}
    return ("AND", frozenset(parts)) if len(parts) > 1 else next(iter(parts))
def q_or(a, b):
    if a == ALL or b == ALL: return ALL
    parts = set()
    for x in (a, b): parts |= set(x[1]) if x[0] == "OR" else {x}
    return ("OR", frozenset(parts)) if len(parts) > 1 else next(iter(parts))
def and_strings(q, strs):
    """q AND (OR over s in strs of phrase(s)); only sound when every s has >= 3 chars."""
    if not strs or min(len(s) for s in strs) < 3: return q
    o = None
    for s in strs:
        ph = ("PH", s); o = ph if o is None else q_or(o, ph)
    return q_and(q, o)

class Info:
    __slots__ = ("can_empty", "exact", "prefix", "suffix", "match")
    def __init__(s, can_empty, exact, prefix, suffix, match=ALL):
        s.can_empty, s.exact, s.prefix, s.suffix, s.match = can_empty, exact, prefix, suffix, match
def any_char(): return Info(False, None, {""}, {""})
def any_match(): return Info(True, None, {""}, {""})
def empty(): return Info(True, {""}, None, None)
def exact_set(ss): return Info(False, set(ss), None, None)

def clean(t, suffix):
    """drop strings that have another member as a prefix (suffix) - they add no information"""
    out = []
    for s in sorted(t, key=lambda x: (x[::-1] if suffix else x)):
        if out and (s.endswith(out[-1]) if suffix else s.startswith(out[-1])): continue
        out.append(s)
    return set(out)
def simplify_set(info, attr, suffix):
    t = getattr(info, attr)
    info.match = and_strings(info.match, t)
    n = 3
    while n == 3 or len(t) > MAX_SET:
        t = {(s[len(s) - n + 1:] if suffix else s[:n - 1]) if len(s) >= n else s for s in t}
        n -= 1
    setattr(info, attr, clean(t, suffix))
def add_exact(info):
    if info.exact is not None: info.match = and_strings(info.match, info.exact)
def simplify(info, force):
    if info.exact is not None:
        ml = min((len(s) for s in info.exact), default=0)
        if len(info.exact) > MAX_EXACT or (ml >= 3 and force) or ml >= 4:
            add_exact(info)
            info.prefix, info.suffix = set(), set()
            for s in info.exact:
                info.prefix.add(s if len(s) < 3 else s[:2]); info.suffix.add(s if len(s) < 3 else s[-2:])
            info.exact = None
    if info.exact is None:
        simplify_set(info, "prefix", False); simplify_set(info, "suffix", True)
    return info
def pfx(i): return set(i.exact) if i.exact is not None else set(i.prefix)
def sfx(i): return set(i.exact) if i.exact is not None else set(i.suffix)
def cross(a, b): return {x + y for x in a for y in b}
def concat(x, y):
    xy = Info(x.can_empty and y.can_empty, None, None, None, q_and(x.match, y.match))
    if x.exact is not None and y.exact is not None:
        xy.exact = cross(x.exact, y.exact)
    else:
        xy.prefix = cross(x.exact, y.prefix) if x.exact is not None else (x.prefix | pfx(y) if x.can_empty else set(x.prefix))
        xy.suffix = cross(x.suffix, y.exact) if y.exact is not None else (y.suffix | sfx(x) if y.can_empty else set(y.suffix))
    if (x.exact is None and y.exact is None and not x.can_empty and not y.can_empty
            and len(x.suffix) <= MAX_SET and len(y.prefix) <= MAX_SET
            and min(map(len, x.suffix)) + min(map(len, y.prefix)) >= 3):
        xy.match = and_strings(xy.match, cross(x.suffix, y.prefix))
    return simplify(xy, False)
def alternate(x, y):
    xy = Info(x.can_empty or y.can_empty, None, None, None)
    if x.exact is not None and y.exact is not None:
        xy.exact = x.exact | y.exact
    elif x.exact is not None:
        xy.prefix, xy.suffix = x.exact | y.prefix, x.exact | y.suffix; add_exact(x)
    elif y.exact is not None:
        xy.prefix, xy.suffix = x.prefix | y.exact, x.suffix | y.exact; add_exact(y)
    else:
        xy.prefix, xy.suffix = x.prefix | y.prefix, x.suffix | y.suffix
    xy.match = q_or(x.match, y.match)
    return simplify(xy, False)
def as_prefix_suffix(info):  # exact -> prefix/suffix (for x+ and for x{n,} tails)
    if info.exact is not None:
        info = Info(info.can_empty, None, set(info.exact), set(info.exact), info.match)
    return info

def class_members(av):
    """keys of the characters an IN node can match, or None if unbounded/unknown."""
    out = set()
    for op, a in av:
        if op is C.LITERAL: out.add(chr(kc(a)))
        elif op is C.RANGE:
            lo, hi = a
            if hi - lo > MAX_CLASS: return None
            out |= {chr(kc(c)) for c in range(lo, hi + 1)}
        else:  # NEGATE, CATEGORY, ...
            return None
        if len(out) > MAX_CLASS: return None
    return out

def analyze_seq(items):
    info = empty()
    for op, av in items:
        info = concat(info, analyze(op, av))
    return info
def analyze(op, av):
    if op is C.LITERAL: return exact_set({chr(kc(av))})
    if op is C.IN:
        m = class_members(av); return exact_set(m) if m else any_char()
    if op in (C.ANY, C.NOT_LITERAL): return any_char()
    if op in (C.AT, C.ASSERT, C.ASSERT_NOT): return empty()          # zero-width
    if op is C.SUBPATTERN: return analyze_seq(av[-1])
    if op is C.ATOMIC_GROUP: return analyze_seq(av)
    if op is C.BRANCH:
        alts = [analyze_seq(b) for b in av[1]]
        info = alts[0]
        for a in alts[1:]: info = alternate(info, a)
        return info
    if op in (C.MAX_REPEAT, C.MIN_REPEAT, C.POSSESSIVE_REPEAT):
        lo, hi, sub = av
        if lo == 0:
            return alternate(analyze_seq(sub), empty()) if hi == 1 else any_match()
        x = analyze_seq(sub); k = min(lo, 3)
        info = x
        for _ in range(k - 1): info = concat(info, analyze_seq(sub))
        if hi != k: info = concat(as_prefix_suffix(info), any_match())
        return info
    return any_match()   # GROUPREF, GROUPREF_EXISTS, anything unknown: no information

def trigram_query(pattern):
    info = analyze_seq(P.parse(pattern))
    simplify(info, True); add_exact(info)
    return info.match
def to_fts(q):
    if q[0] == "PH": return '"' + q[1].replace('"', '""') + '"'
    if q[0] in ("AND", "OR"): return "(" + f" {q[0]} ".join(sorted(to_fts(x) for x in q[1])) + ")"
    raise ValueError(q)

# ---- key-space trigram index over real labels (case_sensitive 1: no SQLite folding at all)
k = sqlite3.connect(":memory:")
k.execute("CREATE VIRTUAL TABLE kt USING fts5(k, tokenize='trigram case_sensitive 1', content='', detail=full)")
t0 = time.perf_counter()
k.executemany("INSERT INTO kt(rowid, k) VALUES (?, ?)", [(rid, key(t)) for rid, t, _ in rows])
print("built key trigram index in", round(time.perf_counter() - t0, 1), "s")

# current acatalogue rule for comparison
def required_literal(pattern):
    parsed = P.parse(pattern)
    if parsed.state.flags & re.IGNORECASE: return None
    best, run = "", []
    for op, av in parsed:
        if op is C.LITERAL: run.append(chr(av)); continue
        if op is C.BRANCH: return None
        if len(run) > len(best): best = "".join(run)
        run = []
    if len(run) > len(best): best = "".join(run)
    return best if len(best) >= 3 else None

# ---- fuzz: random regexes built from real label fragments
random.seed(11)
pool = [t for _, t, _ in rows if len(t) >= 6]
def frag():
    s = random.choice(pool); i = random.randrange(0, len(s) - 3); return s[i:i + random.randint(2, 6)]
def lit(s): return re.escape(s)
def rand_regex():
    kind = random.random()
    a, b, c = frag(), frag(), frag()
    choices = [
        lambda: lit(a),
        lambda: "(?i)" + lit(a.upper() if random.random() < .5 else a.lower()),
        lambda: f"(?:{lit(a)}|{lit(b)})",
        lambda: f"{lit(a)}.*{lit(b)}",
        lambda: f"{lit(a)}\\w+{lit(b)}",
        lambda: f"(?i:{lit(a)})[{lit(b[:2])}]{lit(c)}",
        lambda: f"{lit(a)}(?:{lit(b)})?{lit(c)}",
        lambda: f"^{lit(a)}",
        lambda: f"\\b{lit(a)}\\b",
        lambda: f"({lit(a)})+{lit(b)}",
        lambda: f"{lit(a[:1])}[a-z]{{2,5}}{lit(b)}",
        lambda: f"(?i)(?:{lit(a)}|{lit(b)}){lit(c)}",
        lambda: f"(?:{lit(a)}){{2}}",
        lambda: f"{lit(a)}(?={lit(b)})",
        lambda: f"(?<={lit(a[:2])}){lit(b)}",
        lambda: f"({lit(a)}).*\\1",
        lambda: f"[^ ]{lit(a)}[^ ]",
        lambda: f"(?i)[İI]{lit(a)}",
        lambda: f"(?i){lit(a)}|{lit(b)}",
        lambda: f"{lit(a)}\\d*{lit(b)}?",
    ]
    return random.choice(choices)()

N = 400
fn = 0; stats = []; cur_used = cox_used = 0; examples = []
t_full = t_pref = 0.0
for i in range(N):
    pat = rand_regex()
    try: rx = re.compile(pat)
    except re.error: continue
    t0 = time.perf_counter(); truth = {rid for rid, t in texts.items() if rx.search(t)}; t_full += time.perf_counter() - t0
    q = trigram_query(pat)
    if q == ALL:
        cand = None
    else:
        t0 = time.perf_counter()
        cand = {r[0] for r in k.execute("SELECT rowid FROM kt WHERE kt MATCH ?", (to_fts(q),))}
        _ = [rid for rid in cand if rx.search(texts[rid])]; t_pref += time.perf_counter() - t0
        cox_used += 1
        if truth - cand:
            fn += 1; examples.append((pat, to_fts(q), len(truth - cand)))
        stats.append(len(cand))
    if required_literal(pat): cur_used += 1
print(f"patterns={N} false-negative patterns={fn} {examples[:3]}")
print(f"prefilter available: current rule {cur_used}/{N}, Cox-style {cox_used}/{N}")
print(f"candidate rows when prefiltered: median {statistics.median(stats)}, p90 {sorted(stats)[int(.9*len(stats))]}, max {max(stats)} of {len(rows)}")
print(f"total time full scans {round(t_full,2)} s vs prefilter+verify {round(t_pref,2)} s (for the prefiltered subset)")
for pat in [r"(?i)istanbul", r"(?:colou?r|hue)s?", r"(?i)neur(?:al|on)\w* net", r"[İI]stanbul|Ankara", r"\bpsych\w+", r"(?i)ſtraße",
            r"x{3}", r"(?i)ᏣᎳᎩ", r"东京|東京都", r"a.c", r"(ab|cd)(ef|gh)ij"]:
    q = trigram_query(pat); print("  ", repr(pat), "->", "FULL SCAN" if q == ALL else to_fts(q))
