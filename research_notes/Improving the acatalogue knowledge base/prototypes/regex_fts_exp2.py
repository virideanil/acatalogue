"""Real-data measurements on data/acatalogue.sqlite (opened read-only) + more FTS5 edge cases."""
import re, sqlite3, time, unicodedata, random, os, sys
import _sre
from re import _casefix
sys.path.insert(0, "/home/user/acatalogue")
from acatalogue.db import register_functions

DB = "/home/user/acatalogue/data/acatalogue.sqlite"
S = "/tmp/claude-0/-home-user-acatalogue/0c6b5ec4-d312-5493-9173-1d9be46979db/scratchpad"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
register_functions(conn)
print("db size MB", round(os.path.getsize(DB) / 1e6, 1))
print([r[0] for r in conn.execute("SELECT sql FROM sqlite_master WHERE name IN ('label_fts','label','passage')")])
try:
    rows = conn.execute("SELECT name, SUM(pgsize) FROM dbstat WHERE name LIKE '%fts%' OR name LIKE '%tri%' OR name IN ('label','passage','concept') GROUP BY name ORDER BY 2 DESC").fetchall()
    print("dbstat:", [(n, round(s / 1e6, 2)) for n, s in rows][:20])
except sqlite3.Error as e:
    print("dbstat unavailable:", e)

labels = [r[0] for r in conn.execute("SELECT text FROM label")]
passages = [r[0] for r in conn.execute("SELECT text FROM passage")]
print("labels", len(labels), "passages", len(passages))
def has(pred, xs): return sum(1 for x in xs if pred(x))
cats = lambda s: {unicodedata.category(ch) for ch in s}
print("labels with U+0130 İ:", has(lambda s: "İ" in s, labels), " with U+0131 ı:", has(lambda s: "ı" in s, labels))
print("labels with Mn/Mc marks:", has(lambda s: bool(cats(s) & {"Mn", "Mc"}), labels),
      " passages with Mn/Mc:", has(lambda s: bool(cats(s) & {"Mn", "Mc"}), passages))
isCJK = lambda ch: ("぀" <= ch <= "ヿ") or ("㐀" <= ch <= "鿿") or ("가" <= ch <= "힯") or ("\U00020000" <= ch <= "\U0003134f")
print("labels with CJK/kana/hangul:", has(lambda s: any(isCJK(c) for c in s), labels))
print("labels with Thai:", has(lambda s: any("฀" <= c <= "๿" for c in s), labels))
print("labels not NFC:", has(lambda s: not unicodedata.is_normalized("NFC", s), labels),
      " passages not NFC:", has(lambda s: not unicodedata.is_normalized("NFC", s), passages))
short = [s for s in labels if len(s) < 3]
print("labels shorter than 3 chars:", len(short), short[:10])
cjk_short = [s for s in labels if any(isCJK(c) for c in s) and len(s) <= 2]
print("CJK labels of <=2 chars:", len(cjk_short))

# Python re.I class key vs SQLite trigram fold: labels containing a char whose class SQLite does not unify
lower = _sre.unicode_tolower; EXTRA = _casefix._EXTRA_CASES
def pykey(cp):
    lo = lower(cp); return min((lo,) + EXTRA.get(lo, ()))
m = sqlite3.connect(":memory:")
m.execute("CREATE VIRTUAL TABLE f USING fts5(x, tokenize='trigram')")
m.execute("CREATE VIRTUAL TABLE v USING fts5vocab(f, 'instance')")
chars = sorted({ord(c) for s in labels + passages for c in s})
m.executemany("INSERT INTO f(rowid,x) VALUES (?,?)", [(cp, chr(cp) * 3) for cp in chars if cp])
sq = {doc: ord(term[0]) for term, doc in m.execute("SELECT term, doc FROM v")}
bykey = {}
for cp in chars:
    if cp in sq: bykey.setdefault(pykey(cp), set()).add(sq[cp])
split_keys = {k for k, v in bykey.items() if len(v) > 1}
print("distinct chars in data:", len(chars), "; re.I classes present in data that SQLite folds apart:",
      [(chr(k), sorted(chr(x) for x in bykey[k])) for k in split_keys][:12])
aff = has(lambda s: any(pykey(ord(c)) in split_keys for c in s), labels)
print("labels containing such chars:", aff)

# Substring semantics mismatch on real data: trigram MATCH vs Python re.I vs casefold, random needles
random.seed(7)
def tri_hits(needle):
    return {r[0] for r in conn.execute("SELECT rowid FROM label_tri WHERE label_tri MATCH ?", ('"' + needle.replace('"', '""') + '"',))}
lab_rows = conn.execute("SELECT rowid, text FROM label").fetchall()
needles = []
cand = [s for s in labels if any(c in s for c in "İıIi") and len(s) >= 5]
for s in random.sample(cand, 150):
    i = random.randrange(0, len(s) - 3); needles.append(s[i:i + 4].lower())
mis_rei = mis_cf = 0; ex = []
t0 = time.perf_counter()
for nd in needles:
    th = tri_hits(nd)
    rx = re.compile(re.escape(nd), re.I)
    py = {rid for rid, t in lab_rows if rx.search(t)}
    cf = {rid for rid, t in lab_rows if nd.casefold() in t.casefold()}
    if py - th: mis_rei += 1; ex.append((nd, len(py - th)))
    if cf - th: mis_cf += 1
print(f"needles={len(needles)} (4-char windows around I/i/İ/ı); trigram MATCH misses rows that re.I finds for {mis_rei}; "
      f"that casefold finds for {mis_cf}; examples {ex[:6]}")

# Timings on real data
def tm(sql, p, n=3):
    best = 1e9
    for _ in range(n):
        t0 = time.perf_counter(); r = conn.execute(sql, p).fetchall(); best = min(best, time.perf_counter() - t0)
    return round(best * 1000, 1), len(r)
print("time full REGEXP scan labels 'stanbul':", tm("SELECT rowid FROM label WHERE text REGEXP ?", ("stanbul",)))
print("time full REGEXP scan labels '(?i)stanbul':", tm("SELECT rowid FROM label WHERE text REGEXP ?", ("(?i)stanbul",)))
print("time prefiltered label_tri MATCH + REGEXP:", tm("SELECT l.rowid FROM label_tri l WHERE label_tri MATCH ? AND l.text REGEXP ?", ('"stanbul"', "stanbul")))
print("time casefold_contains full scan labels 'ab':", tm("SELECT rowid FROM label WHERE casefold_contains(text, ?)", ("ab",)))
print("time passages full REGEXP scan:", tm("SELECT id FROM passage WHERE text REGEXP ?", (r"\bneural\w*",)))
print("time passages casefold_contains:", tm("SELECT id FROM passage WHERE casefold_contains(text, ?)", ("ne",)))

# Edge cases of MATCH strings built from regex literals
e = sqlite3.connect(":memory:")
e.execute("CREATE VIRTUAL TABLE tri USING fts5(x, tokenize='trigram')")
e.execute("CREATE VIRTUAL TABLE rd USING fts5(x, tokenize='trigram remove_diacritics 1')")
e.execute("CREATE VIRTUAL TABLE u USING fts5(x, tokenize=\"unicode61 remove_diacritics 2 categories 'L* N* Co M*'\")")
for tb in ("tri", "rd", "u"):
    e.executemany(f"INSERT INTO {tb} VALUES (?)", [("istanbul",), ("a*b(c) NEAR x",), ("οδός Việt",), ("العَرَبِيَّة",), (" ́abc",)])
def q(sql, *p):
    try: return [r[0] for r in e.execute(sql, p)]
    except sqlite3.Error as ex: return f"ERROR {ex}"
print("AND with 2-char phrase:", q("SELECT x FROM tri WHERE tri MATCH ?", '"ista" AND "ul"'))
print("OR with 2-char phrase:", q("SELECT x FROM tri WHERE tri MATCH ?", '"ul" OR "zzz"'))
print("quoted specials:", q("SELECT x FROM tri WHERE tri MATCH ?", '"a*b(c) NEAR"'))
print("rd greek no-tonos 'οδος':", q("SELECT x FROM rd WHERE rd MATCH ?", '"οδος"'), " rd 'viet':", q("SELECT x FROM rd WHERE rd MATCH ?", '"viet"'))
print("rd arabic without harakat:", q("SELECT x FROM rd WHERE rd MATCH ?", '"العربية"'))
print("u61 M* stray mark row tokens:", [r[0] for r in e.execute("SELECT term FROM (SELECT 1) , (SELECT 1) WHERE 0")] or "n/a")
e.execute("CREATE VIRTUAL TABLE uv USING fts5vocab(u, 'row')")
print("u61 M* vocab:", [r[0] for r in e.execute("SELECT term FROM uv")])
# Size of index variants on the real label texts (built in a scratch DB)
p = f"{S}/sizes.sqlite"
for spec, extra in [("trigram", ""), ("trigram", ", detail=column"), ("trigram", ", detail=none"),
                    ("unicode61 remove_diacritics 2", ""), ("unicode61 remove_diacritics 2", ", prefix='2 3'"),
                    ("unicode61 remove_diacritics 2 categories 'L* N* Co M*'", "")]:
    if os.path.exists(p): os.remove(p)
    d = sqlite3.connect(p)
    d.execute(f"CREATE VIRTUAL TABLE f USING fts5(x, tokenize=\"{spec}\"{extra})")
    d.executemany("INSERT INTO f VALUES (?)", [(s,) for s in labels]); d.commit()
    d.execute("INSERT INTO f(f) VALUES('optimize')"); d.commit(); d.execute("VACUUM"); d.close()
    base = sum(len(s.encode()) for s in labels)
    print(f"size labels [{spec}{extra}]: {round(os.path.getsize(p)/1e6,2)} MB (raw UTF-8 text {round(base/1e6,2)} MB, incl. content copy)")
os.remove(p)
