import re, sqlite3, unicodedata, random, os, time
DB = "/home/user/acatalogue/data/acatalogue.sqlite"
S = "/tmp/claude-0/-home-user-acatalogue/0c6b5ec4-d312-5493-9173-1d9be46979db/scratchpad"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
rows = conn.execute("SELECT rowid, text, lang FROM label").fetchall()
labels = [t for _, t, _ in rows]
def cnt(lo, hi): return sum(1 for s in labels if any(lo <= ord(c) <= hi for c in s))
print("labels with Cherokee:", cnt(0x13A0, 0x13FF) + 0, " Adlam:", cnt(0x1E900, 0x1E95F), " Georgian Mtavruli:", cnt(0x1C90, 0x1CBF),
      " Osage:", cnt(0x104B0, 0x104FF), " Deseret:", cnt(0x10400, 0x1044F))

def build(spec, texts, name):
    c = sqlite3.connect(":memory:")
    c.execute(f"CREATE VIRTUAL TABLE f USING fts5(x, tokenize=\"{spec}\")")
    c.executemany("INSERT INTO f(rowid, x) VALUES (?, ?)", texts)
    return c
def hits(c, q):
    try: return {r[0] for r in c.execute("SELECT rowid FROM f WHERE f MATCH ?", (q,))}
    except sqlite3.Error: return set()

# (b) Devanagari word precision/recall: default categories vs + M*
PUNCT = lambda ch: unicodedata.category(ch)[0] in "PZS"
def words(s):
    out, cur = [], []
    for ch in s:
        if PUNCT(ch):
            if cur: out.append("".join(cur)); cur = []
        else: cur.append(ch)
    if cur: out.append("".join(cur))
    return out
deva = [(rid, t) for rid, t, _ in rows if any("ऀ" <= ch <= "ॿ" for ch in t)]
print("labels with Devanagari:", len(deva))
d_def = build("unicode61 remove_diacritics 2", deva, "d")
d_m = build("unicode61 remove_diacritics 2 categories 'L* N* Co M*'", deva, "m")
random.seed(3)
vocab = sorted({w for _, t in deva for w in words(t) if len(w) >= 3 and any("ऀ" <= ch <= "ॿ" for ch in w)})
sample = random.sample(vocab, 150)
wordsets = {rid: set(words(t)) for rid, t in deva}
P = {"default": [0, 0, 0], "M*": [0, 0, 0]}   # returned, correct, relevant
for w in sample:
    truth = {rid for rid, ws in wordsets.items() if w in ws}
    for name, c in (("default", d_def), ("M*", d_m)):
        h = hits(c, '"' + w + '"')
        P[name][0] += len(h); P[name][1] += len(h & truth); P[name][2] += len(truth)
for name, (ret, ok, rel) in P.items():
    print(f"Devanagari whole-word queries (150): {name:8s} returned={ret} correct={ok} precision={ok/ret:.3f} recall={ok/rel:.3f}")

# (a) CJK: word mode recall for 2-char CJK words vs substring truth; bigram pre-segmentation fix
isCJK = lambda ch: ("぀" <= ch <= "ヿ") or ("㐀" <= ch <= "鿿") or ("가" <= ch <= "힯")
cjk = [(rid, t) for rid, t, _ in rows if any(isCJK(c) for c in t)]
def bigrams(s):
    out, run = [], []
    def flush():
        if len(run) == 1: out.append(run[0])
        else: out.extend(run[i] + run[i + 1] for i in range(len(run) - 1))
        run.clear()
    for ch in s:
        if isCJK(ch): run.append(ch)
        else:
            if run: flush()
            out.append(ch if not ch.isspace() else " ")
    if run: flush()
    # join: CJK bigrams separated by spaces; other text kept
    return " ".join(x if len(x) > 1 or isCJK(x) else x for x in out)
c_def = build("unicode61 remove_diacritics 2", cjk, "c")
c_bi = build("unicode61 remove_diacritics 2", [(rid, bigrams(t)) for rid, t in cjk], "b")
two = sorted({t for _, t in cjk if len(t) == 2 and all(isCJK(ch) for ch in t)})
random.seed(5); smp = random.sample(two, 100)
rw = rb = rel = retb = okb = 0
for w in smp:
    truth = {rid for rid, t in cjk if w in t}
    hw = hits(c_def, '"' + w + '"'); hb = hits(c_bi, '"' + w + '"')
    rel += len(truth); rw += len(hw & truth); rb += len(hb & truth); retb += len(hb); okb += len(hb & truth)
print(f"CJK 2-char queries (100): substring-truth rows={rel}; word mode (unicode61) finds {rw} (recall {rw/rel:.3f}); "
      f"bigram-segmented column finds {rb} (recall {rb/rel:.3f}, precision {okb/max(retb,1):.3f})")
# (d) sizes of index variants on real label text (separate files, after optimize + VACUUM)
import _sre
from re import _casefix
lower = _sre.unicode_tolower; EXTRA = _casefix._EXTRA_CASES
def key(s): return "".join(chr(min((lower(ord(ch)),) + EXTRA.get(lower(ord(ch)), ()))) for ch in s)
base = sum(len(s.encode()) for s in labels)
print("raw label text UTF-8 MB", round(base / 1e6, 2))
variants = [("trigram", "", None), ("trigram", ", detail=column", None), ("trigram", ", detail=none", None),
            ("trigram case_sensitive 1", ", content=''", key),
            ("unicode61 remove_diacritics 2", ", content=''", None), ("unicode61 remove_diacritics 2", ", content='', prefix='2 3'", None),
            ("unicode61 remove_diacritics 2 categories 'L* N* Co M*'", ", content=''", None),
            ("unicode61 remove_diacritics 2", ", content=''", "bigram")]
for spec, extra, fn in variants:
    p = f"{S}/sizes.sqlite"
    if os.path.exists(p): os.remove(p)
    d = sqlite3.connect(p)
    d.execute(f"CREATE VIRTUAL TABLE f USING fts5(x, tokenize=\"{spec}\"{extra})")
    data = [(i, (key(s) if fn is key else bigrams(s) if fn == "bigram" else s)) for i, s in enumerate(labels, 1)]
    d.executemany("INSERT INTO f(rowid, x) VALUES (?, ?)", data); d.commit()
    d.execute("INSERT INTO f(f) VALUES('optimize')"); d.commit(); d.execute("VACUUM"); d.close()
    tag = "key-folded " if fn is key else "bigram-segmented " if fn == "bigram" else ""
    print(f"size {tag}[{spec}{extra}]: {round(os.path.getsize(p)/1e6, 2)} MB")
    os.remove(p)
e = sqlite3.connect(":memory:")
e.execute("CREATE VIRTUAL TABLE u USING fts5(x, tokenize=\"unicode61 remove_diacritics 2 categories 'L* N* Co M*'\")")
e.execute("CREATE VIRTUAL TABLE uv USING fts5vocab(u, 'row')")
e.executemany("INSERT INTO u VALUES (?)", [(" ́abc x ́",), ("ّ",)])
print("M* vocab with stray combining marks:", [r[0] for r in e.execute("SELECT term FROM uv")])
