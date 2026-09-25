"""Empirical checks of FTS5 trigram/unicode61 behaviour vs Python re on SQLite 3.45.1 / Python 3.11."""
import re, sqlite3, sys, unicodedata, time, os
from collections import defaultdict
import _sre
from re import _casefix

print("python", sys.version.split()[0], "unicodedata", unicodedata.unidata_version, "sqlite", sqlite3.sqlite_version)
m = sqlite3.connect(":memory:")

# E1: options accepted?
for spec in ["trigram", "trigram case_sensitive 1", "trigram remove_diacritics 1",
             "trigram case_sensitive 1 remove_diacritics 1", "trigram case_sensitive 0 remove_diacritics 1"]:
    try:
        m.execute(f"CREATE VIRTUAL TABLE t_{abs(hash(spec))} USING fts5(x, tokenize=\"{spec}\")"); print("E1 ok   ", spec)
    except sqlite3.Error as e:
        print("E1 FAIL ", spec, "->", e)

# helper: tokens produced by a tokenizer spec for a text
def tokens(spec, text):
    c = sqlite3.connect(":memory:")
    c.execute(f"CREATE VIRTUAL TABLE f USING fts5(x, tokenize=\"{spec}\")")
    c.execute("CREATE VIRTUAL TABLE v USING fts5vocab(f, 'instance')")
    c.execute("INSERT INTO f VALUES (?)", (text,))
    return [r[0] for r in c.execute("SELECT term FROM v ORDER BY offset")]

# E2: SQLite fold (trigram, case-insensitive) vs Python re IGNORECASE equivalence
lower = _sre.unicode_tolower
EXTRA = _casefix._EXTRA_CASES
def pykey(cp):
    lo = lower(cp)
    return min((lo,) + EXTRA.get(lo, ()))
classes = defaultdict(list)
for cp in range(0x110000):
    if 0xD800 <= cp <= 0xDFFF: continue
    classes[pykey(cp)].append(cp)
multi = {k: v for k, v in classes.items() if len(v) > 1}
members = sorted({cp for v in multi.values() for cp in v})
c = sqlite3.connect(":memory:")
c.execute("CREATE VIRTUAL TABLE f USING fts5(x, tokenize='trigram')")
c.execute("CREATE VIRTUAL TABLE v USING fts5vocab(f, 'instance')")
c.executemany("INSERT INTO f(rowid, x) VALUES (?, ?)", [(cp, chr(cp) * 3) for cp in members])
sqfold = {doc: term[0] for term, doc in c.execute("SELECT term, doc FROM v")}
bad = []
for k, v in multi.items():
    folds = {sqfold[cp] for cp in v}
    if len(folds) > 1:
        bad.append((k, v, folds))
print(f"E2 python IGNORECASE classes with >1 member: {len(multi)} ({len(members)} code points); "
      f"classes SQLite trigram fold does NOT unify: {len(bad)}")
def nm(cp):
    try: return unicodedata.name(chr(cp))
    except ValueError: return "?"
blocks = defaultdict(int)
for k, v, folds in bad:
    blocks[nm(v[0]).split(" ")[0]] += 1
print("E2 by script (first word of name):", dict(sorted(blocks.items(), key=lambda x: -x[1])[:15]))
for probe in [0x69, 0x73, 0x6B, 0xB5, 0x3C3, 0xDF, 0x3B8, 0x1C90 - 0x1C90 + 0x10D0, 0x13A0, 0x104B0, 0x1E900, 0x10400]:
    k = pykey(probe); v = classes[k]
    print("   class of", hex(probe), [f"U+{x:04X} {chr(x)}" for x in v], "-> sqlite folds",
          sorted({f'U+{ord(sqfold[x]):04X}' for x in v}) if all(x in sqfold for x in v) else "n/a")

# direct probes of special chars through the trigram tokenizer
for s in ["İstanbul", "ıstanbul", "ISTANBUL", "Kelvin", "ſtraße", "STRASSE", "ΟΔΟΣ", "οδος", "ᏣᎳᎩ", "ꭣꬳꬩ",
          "\U000104B0\U000104B1\U000104B2", "\U0001E900\U0001E901\U0001E902", "Ǆemal", "ǅemal", "ﬁne"]:
    print("E2b trigram tokens", repr(s), tokens("trigram", s)[:2])

# E3: unicode61 tokenization across scripts (default categories, remove_diacritics 2 like acatalogue)
samples = {
    "hindi": "हिन्दी भाषा", "thai": "ภาษาไทยเป็นภาษาราชการ", "arabic_harakat": "اللُّغَةُ العَرَبِيَّة",
    "arabic_plain": "اللغة العربية", "hebrew_niqqud": "עִבְרִית", "japanese": "東京都庁の日本語", "chinese": "中华人民共和国",
    "korean": "한국어 위키백과", "nfd_latin": "Café crème", "nfc_latin": "Café crème", "turkish": "İstanbul ISPARTA ılık",
    "german": "Straße STRASSE", "greek": "ΟΔΟΣ οδός", "vietnamese": "Việt Nam", "tamil": "தமிழ்", "bengali": "বাংলা",
}
for spec in ["unicode61 remove_diacritics 2", "unicode61 remove_diacritics 2 categories 'L* N* Co M*'"]:
    print("E3", spec)
    for k, s in samples.items():
        print(f"   {k:15s} {tokens(spec, s)}")

# E4: trigram behaviours
t = sqlite3.connect(":memory:")
t.execute("CREATE VIRTUAL TABLE tri USING fts5(x, tokenize='trigram')")
t.execute("CREATE VIRTUAL TABLE tri_cs USING fts5(x, tokenize='trigram case_sensitive 1')")
t.execute("CREATE VIRTUAL TABLE tri_rd USING fts5(x, tokenize='trigram remove_diacritics 1')")
rows = ["İstanbul", "istanbul", "ISTANBUL", "Café au lait", "Café noir", "abcdefghij KLMNOPQRST", "東京都", "東京"]
for tb in ("tri", "tri_cs", "tri_rd"):
    t.executemany(f"INSERT INTO {tb} VALUES (?)", [(r,) for r in rows])
def q(sql, *p):
    try: return [r[0] for r in t.execute(sql, p)]
    except sqlite3.Error as e: return f"ERROR {e}"
def plan(sql, *p):
    return " | ".join(r[3] for r in t.execute("EXPLAIN QUERY PLAN " + sql, p))
print("E4 MATCH 'ab' (2 chars):", q("SELECT x FROM tri WHERE tri MATCH ?", '"ab"'))
print("E4 MATCH '東京' (2 chars):", q("SELECT x FROM tri WHERE tri MATCH ?", '"東京"'))
print("E4 MATCH 'istanbul' on tri:", q("SELECT x FROM tri WHERE tri MATCH ?", '"istanbul"'))
print("E4 MATCH 'İSTANBUL' on tri:", q("SELECT x FROM tri WHERE tri MATCH ?", '"İSTANBUL"'))
print("E4 MATCH 'café' on tri (NFC query; rows NFC+NFD):", q("SELECT x FROM tri WHERE tri MATCH ?", '"café"'))
print("E4 MATCH 'café' on tri_rd:", q("SELECT x FROM tri_rd WHERE tri_rd MATCH ?", '"café"'))
print("E4 MATCH 'cafe' on tri_rd:", q("SELECT x FROM tri_rd WHERE tri_rd MATCH ?", '"cafe"'))
for tb in ("tri", "tri_cs", "tri_rd"):
    for op, pat in (("LIKE", "%stanb%"), ("LIKE", "%st%"), ("GLOB", "*stanb*"), ("GLOB", "*[Ss]tanb*")):
        sql = f"SELECT x FROM {tb} WHERE x {op} ?"
        print(f"E4 {tb:6s} {op} {pat!r:12s} plan=[{plan(sql, pat)}] rows={q(sql, pat)}")
print("E4 LIKE '%İSTANBUL%' on tri (core LIKE re-check):", q("SELECT x FROM tri WHERE x LIKE ?", "%İSTANBUL%"))
print("E4 LIKE with ESCAPE plan:", plan("SELECT x FROM tri WHERE x LIKE ? ESCAPE '\\'", "%stanb%"))
print("E4 highlight trigram:", q("SELECT highlight(tri, 0, '[', ']') FROM tri WHERE tri MATCH ?", '"stanb"'))
print("E4 highlight trigram AND:", q("SELECT highlight(tri, 0, '[', ']') FROM tri WHERE tri MATCH ?", '"cdefg" AND "pqr"'))
print("E4 snippet trigram 8 tokens:", q("SELECT snippet(tri, 0, '[', ']', '…', 8) FROM tri WHERE tri MATCH ?", '"klmno"'))
print("E4 unindexed OR query:", q("SELECT x FROM tri WHERE tri MATCH ?", '("ista" AND "bul") OR "東京都"'))
