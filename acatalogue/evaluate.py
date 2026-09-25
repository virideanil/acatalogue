"""Retrieval evaluation: can the catalogue find a concept from its name in a language it has hidden?

Known-item queries. For each language L of a panel, every ACAT concept's preferred label in L is a
query whose one relevant answer is that concept. While it runs, every label in L is hidden from the
index (leave one language out), so a system must find the concept through the other languages.
English is not in the panel: it is the language the catalogue is written in (and LSA is fit on it).

Systems: FTS5 words (bm25), character-trigram similarity (cognates, transliterations), LSA fold-in,
a dense multilingual model when its vectors exist, and reciprocal rank fusion (k = 60) of lexical
systems alone and of all of them. Metrics: MRR@10, Recall@10 and nDCG@10 per language, their
macro-average over languages and the worst language, with bootstrap 95% intervals (queries resampled
within each language) and paired randomization tests. Every query and every rank is stored
(eval_run, eval_query, eval_rank, eval_metric, eval_test) with the ledger head it describes.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import defaultdict

from . import ledger
from .textkeys import cjk_bigrams, fold_key, has_cjk, nfc
from .util import utcnow

PANEL = tuple("es de tr vi id ru kk el hy ka ar fa ur he hi bn ta zh ja ko th my sw ha yo am qu mi".split())
K = 10
DEPTH = 100
RRF_K = 60
SEED = 20260925
_SPLIT = re.compile(r"[\s!-/:-@\[-`{-~ -¿ -⁯　-〿＀-／：-＠]+")


def tokens(text: str) -> list[str]:
    return [t for t in _SPLIT.split(nfc(text)) if t]


def queries(conn: sqlite3.Connection, langs: tuple[str, ...] = PANEL) -> list[dict]:
    out = []
    for lang in langs:
        for cid, text in conn.execute(
                "SELECT l.concept_id, min(l.text) FROM label l JOIN concept c ON c.id = l.concept_id"
                " WHERE c.scheme = 'acat' AND c.status = 'active' AND l.kind = 'pref' AND l.lang = ?"
                " GROUP BY l.concept_id ORDER BY l.concept_id", (lang,)):
            out.append({"qid": len(out), "lang": lang, "text": text, "target": cid})
    return out


def _unique(ids) -> list[str]:
    seen, out = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
            if len(out) >= DEPTH:
                break
    return out


# ─── systems: each maps a query to a ranked list of concept ids ─────────────


class Lexical:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def words(self, q: dict) -> list[str]:
        toks = tokens(q["text"])[:32]
        if not toks:
            return []
        match = " OR ".join('"' + t.replace('"', '""') + '"' for t in toks)
        rows = self.conn.execute(
            "SELECT concept_id FROM label_fts WHERE label_fts MATCH ? AND lang <> ? AND kind IN ('pref', 'alt')"
            " AND concept_id LIKE 'acat/%' ORDER BY bm25(label_fts) LIMIT 1000", (match, q["lang"])).fetchall()
        return _unique(r[0] for r in rows)

    def trigram(self, q: dict) -> list[str]:
        """Jaccard similarity of character trigrams of the case keys (pairs for CJK text)."""
        text = nfc(q["text"])
        if has_cjk(text):
            grams = set(cjk_bigrams(text).split())
            table, gram_of = "label_cjk", lambda s: set(cjk_bigrams(s).split())
        else:
            key = fold_key(text)
            grams = {key[i:i + 3] for i in range(len(key) - 2)}
            table, gram_of = "label_key", lambda s: {k[i:i + 3] for k in (fold_key(s),) for i in range(len(k) - 2)}
        if not grams:
            return []
        match = " OR ".join('"' + g.replace('"', '""') + '"' for g in sorted(grams)[:64])
        # the candidate cap applies before the hidden language is removed (the contentless index has no
        # language column): the query's own language can only take candidate slots, never add a match
        rows = self.conn.execute(
            f"SELECT l.concept_id, l.text FROM (SELECT rowid AS id FROM {table} WHERE {table} MATCH ?"
            f" ORDER BY rank LIMIT 3000) m JOIN label l ON l.id = m.id"
            f" WHERE l.lang <> ? AND l.kind IN ('pref', 'alt') AND l.concept_id LIKE 'acat/%'",
            (match, q["lang"])).fetchall()
        scored = []
        for cid, t in rows:
            g = gram_of(nfc(t))
            if g:
                scored.append((len(grams & g) / len(grams | g), cid))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return _unique(cid for s, cid in scored if s > 0)


class Lsa:
    def __init__(self, conn: sqlite3.Connection):
        from .semantic import fit
        self.fit = fit(conn)

    def rank(self, q: dict) -> list[str]:
        import numpy as np
        v = self.fit.embed(q["text"])
        if not np.any(v):
            return []
        s = self.fit.Vn @ v
        return [self.fit.ids[i] for i in np.argsort(-s, kind="stable")[:DEPTH] if s[i] > 0]


class Dense:
    """Cosine over the stored label vectors (document side); queries encoded with the query prompt."""

    def __init__(self, conn: sqlite3.Connection, qs: list[dict], name: str = "e5-large-instruct"):
        import numpy as np
        from .embed import Encoder, load_label_vectors, model_id
        self.model = model_id(name)
        ids, self.M = load_label_vectors(conn, name)
        # the same index as the lexical systems: every preferred and alternative label of an ACAT concept
        want = {r[0] for r in conn.execute(
            "SELECT l.id FROM label l JOIN concept c ON c.id = l.concept_id WHERE c.scheme = 'acat'"
            " AND c.status = 'active' AND l.kind IN ('pref', 'alt')")}
        missing = len(want - set(ids))
        if missing:
            raise LookupError(f"{missing} index labels have no vector under {self.model}: "
                              "run `acat embed --kinds pref,alt` first")
        keep_rows = [k for k, i in enumerate(ids) if i in want]
        ids = [ids[k] for k in keep_rows]
        self.M = self.M[keep_rows]
        meta = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT id, concept_id, lang FROM label")}
        self.concept = np.array([meta[i][0] for i in ids], dtype=object)
        self.lang = np.array([meta[i][1] for i in ids], dtype=object)
        enc = Encoder(name)
        self.Q = enc.encode([q["text"] for q in qs], query=True)

    def rank_all(self, qs: list[dict]) -> list[list[str]]:
        """Scores for a block of queries in one product; the query language's labels are set to -inf."""
        import numpy as np
        out: list[list[str]] = [[] for _ in qs]
        by_lang: dict[str, list[int]] = defaultdict(list)
        for k, q in enumerate(qs):
            by_lang[q["lang"]].append(k)
        n = self.M.shape[0]
        keep = min(1500, n)                              # the same cut-off whatever the index size
        for lang, ks in by_lang.items():
            hidden = self.lang == lang
            for start in range(0, len(ks), 256):
                block = ks[start:start + 256]
                S = self.Q[block] @ self.M.T
                S[:, hidden] = -np.inf
                top = (np.argpartition(-S, keep - 1, axis=1)[:, :keep] if keep < n
                       else np.tile(np.arange(n), (len(block), 1)))
                for row, k in enumerate(block):
                    t = top[row][np.argsort(-S[row, top[row]], kind="stable")]
                    out[k] = _unique(c for c, s in zip(self.concept[t], S[row, t]) if s != -np.inf)
        return out


def rrf(*rankings: list[str]) -> list[str]:
    score: dict[str, float] = defaultdict(float)
    for r in rankings:
        for pos, cid in enumerate(r, 1):
            score[cid] += 1.0 / (RRF_K + pos)
    return [c for c, _ in sorted(score.items(), key=lambda x: (-x[1], x[0]))][:DEPTH]


# ─── metrics ────────────────────────────────────────────────────────────────


def per_query(rank: int | None) -> dict[str, float]:
    hit = rank is not None and rank <= K
    return {"mrr@10": 1.0 / rank if hit else 0.0, "recall@10": 1.0 if hit else 0.0,
            "ndcg@10": 1.0 / math.log2(rank + 1) if hit else 0.0}


METRICS = ("mrr@10", "recall@10", "ndcg@10")


def summarize(qs: list[dict], ranks: dict[int, int | None], seed: int, boot: int) -> list[tuple]:
    """(lang, metric, value, lo, hi, n) rows: per language, macro (''), and the worst language ('*worst').
    Intervals: stratified bootstrap (queries resampled within each language), percentile 95%."""
    import numpy as np
    gen = np.random.default_rng(seed)
    by_lang: dict[str, list[list[float]]] = defaultdict(list)
    for q in qs:
        m = per_query(ranks[q["qid"]])
        by_lang[q["lang"]].append([m[k] for k in METRICS])
    langs = sorted(by_lang)
    vals = {lang: np.array(v) for lang, v in by_lang.items()}                    # (n_L, 3)
    means = {lang: v.mean(axis=0) for lang, v in vals.items()}
    boots = {lang: v[gen.integers(0, len(v), size=(boot, len(v)))].mean(axis=1) for lang, v in vals.items()}  # (boot, 3)
    macro_b = np.mean([boots[lang] for lang in langs], axis=0)                  # (boot, 3)

    def ci(xs) -> tuple[float, float]:
        return float(np.percentile(xs, 2.5)), float(np.percentile(xs, 97.5))
    rows = []
    for lang in langs:
        for j, m in enumerate(METRICS):
            lo, hi = ci(boots[lang][:, j])
            rows.append((lang, m, float(means[lang][j]), lo, hi, len(vals[lang])))
    for j, m in enumerate(METRICS):
        lo, hi = ci(macro_b[:, j])
        rows.append(("", m, float(np.mean([means[lang][j] for lang in langs])), lo, hi, len(qs)))
    worst = min(langs, key=lambda lang: (means[lang][0], lang))
    lo, hi = ci(boots[worst][:, 0])
    rows.append(("*worst", "mrr@10", float(means[worst][0]), lo, hi, len(vals[worst])))
    rows.append(("*worst", f"lang:{worst}", None, None, None, len(vals[worst])))
    return rows


def paired_test(qs: list[dict], a: dict[int, int | None], b: dict[int, int | None], perms: int, seed: int) -> dict:
    """Randomization test on the macro MRR@10 difference: each query's pair of scores is swapped with p = 1/2."""
    import numpy as np
    n_lang: dict[str, int] = defaultdict(int)
    for q in qs:
        n_lang[q["lang"]] += 1
    w = np.array([1.0 / (len(n_lang) * n_lang[q["lang"]]) for q in qs])
    d = np.array([per_query(a[q["qid"]])["mrr@10"] - per_query(b[q["qid"]])["mrr@10"] for q in qs])
    observed = float(w @ d)
    gen = np.random.default_rng(seed)
    extreme = 0
    for start in range(0, perms, 1000):
        signs = gen.integers(0, 2, size=(min(1000, perms - start), len(qs)), dtype=np.int8) * 2 - 1
        extreme += int(np.sum(np.abs(signs @ (w * d)) >= abs(observed) - 1e-12))
    return {"diff": observed, "p": (extreme + 1) / (perms + 1), "perms": perms}


# ─── the run ────────────────────────────────────────────────────────────────


def run(conn: sqlite3.Connection, langs: tuple[str, ...] = PANEL, systems: tuple[str, ...] | None = None,
        boot: int = 1000, perms: int = 10000, actor: str = "acat eval", progress=print) -> dict:
    qs = queries(conn, langs)
    lex = Lexical(conn)
    have_dense = conn.execute("SELECT 1 FROM model WHERE id LIKE 'dense/%' LIMIT 1").fetchone() is not None
    systems = systems or tuple(s for s in ("words", "trigram", "lsa", "dense", "rrf-lexical", "rrf-all")
                               if have_dense or s not in ("dense", "rrf-all"))
    results: dict[str, list[list[str]]] = {}
    if "words" in systems or "rrf-lexical" in systems or "rrf-all" in systems:
        results["words"] = [lex.words(q) for q in qs]
        progress(f"  words: {len(qs)} queries")
    if "trigram" in systems or "rrf-lexical" in systems or "rrf-all" in systems:
        results["trigram"] = [lex.trigram(q) for q in qs]
        progress(f"  trigram: {len(qs)} queries")
    if "lsa" in systems:
        lsa = Lsa(conn)
        results["lsa"] = [lsa.rank(q) for q in qs]
        progress(f"  lsa: {len(qs)} queries")
    dense_model = None
    if "dense" in systems or "rrf-all" in systems:
        dense = Dense(conn, qs)
        dense_model = dense.model
        results["dense"] = dense.rank_all(qs)
        progress(f"  dense ({dense.model}): {len(qs)} queries")
    if "rrf-lexical" in systems:
        results["rrf-lexical"] = [rrf(results["words"][k], results["trigram"][k]) for k in range(len(qs))]
    if "rrf-all" in systems:
        results["rrf-all"] = [rrf(results["words"][k], results["trigram"][k], results["dense"][k]) for k in range(len(qs))]
    results = {s: r for s, r in results.items() if s in systems}

    ranks = {s: {q["qid"]: (r.index(q["target"]) + 1 if q["target"] in r else None) for q, r in zip(qs, rs)}
             for s, rs in results.items()}
    params = {"langs": list(langs), "k": K, "depth": DEPTH, "rrf_k": RRF_K, "seed": SEED, "bootstrap": boot,
              "permutations": perms, "systems": list(results), "dense_model": dense_model,
              "index": "ACAT preferred and alternative labels (the same for every system but LSA, which is "
                       "fit on English concept text), every label in the query's language hidden",
              "queries": "each ACAT concept's preferred label in each panel language; one relevant answer"}
    cur = conn.execute("INSERT INTO eval_run(at, ledger_head, params) VALUES (?,?,?)",
                       (utcnow(), ledger.head(conn), json.dumps(params, sort_keys=True)))
    run_id = cur.lastrowid
    conn.executemany("INSERT INTO eval_query(run_id, qid, lang, text, target) VALUES (?,?,?,?,?)",
                     [(run_id, q["qid"], q["lang"], q["text"], q["target"]) for q in qs])
    summary: dict[str, dict] = {}
    for s in results:
        conn.executemany("INSERT INTO eval_rank(run_id, system, qid, rank) VALUES (?,?,?,?)",
                         [(run_id, s, qid, r) for qid, r in ranks[s].items()])
        rows = summarize(qs, ranks[s], SEED, boot)
        conn.executemany("INSERT INTO eval_metric(run_id, system, lang, metric, value, lo, hi, n) VALUES (?,?,?,?,?,?,?,?)",
                         [(run_id, s, *r) for r in rows])
        summary[s] = {"rows": rows}
    tests = []
    pairs = [("rrf-lexical", "words"), ("trigram", "words"), ("lsa", "words"), ("dense", "words"),
             ("dense", "rrf-lexical"), ("rrf-all", "dense"), ("rrf-all", "rrf-lexical")]
    for a, b in pairs:
        if a in ranks and b in ranks:
            t = paired_test(qs, ranks[a], ranks[b], perms, SEED)
            conn.execute("INSERT INTO eval_test(run_id, a, b, metric, diff, p, permutations) VALUES (?,?,?,?,?,?,?)",
                         (run_id, a, b, "mrr@10 (macro)", t["diff"], t["p"], perms))
            tests.append({"a": a, "b": b, **t})
    ledger.record(conn, actor, "eval-retrieval", target=f"eval_run/{run_id}",
                  detail={"queries": len(qs), "langs": len(langs), "systems": list(results),
                          "macro_mrr@10": {s: round(next(r[2] for r in v["rows"] if r[0] == "" and r[1] == "mrr@10"), 4)
                                           for s, v in summary.items()}},
                  receipt=f"ledger-head:{ledger.head(conn)[:32]}",
                  undo="evaluation runs are measurements; later runs are added beside them")
    conn.commit()
    return {"run_id": run_id, "queries": len(qs), "summary": summary, "tests": tests, "params": params}
