"""The semantic layer: latent semantic analysis (LSA) over each concept's text.

What the numbers are, plainly: TF-IDF term weights over the concept's labels, scope note and
attached corpus text, reduced by a truncated singular value decomposition. It is a classical,
transparent method, not a neural embedding model; the `model` table says so, and every vector is
stored under that model id so a different method can be added side by side, never silently swapped.
"""
from __future__ import annotations

import json
import re
import sqlite3
import struct

from . import ledger
from .util import manifest_sha512, sha512_bytes, utcnow

STOPWORDS = set("""
a about above after again against all also am an and any are as at be because been before being below between
both but by can could did do does doing down during each few for from further had has have having he her here hers
herself him himself his how i if in into is it its itself just me more most my myself no nor not now of off on once
only or other our ours ourselves out over own same she should so some such than that the their theirs them
themselves then there these they this those through to too under until up very was we were what when where which
while who whom why will with would you your yours yourself yourselves known called used use such many often may
including include includes one two three first second new however within among around across well also various
""".split())
TOKEN = re.compile(r"[^\W\d_][\w'-]*[^\W_]|[^\W\d_]", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return [t for t in (m.group(0).lower() for m in TOKEN.finditer(text)) if len(t) > 2 and t not in STOPWORDS]


def concept_texts(conn: sqlite3.Connection, scheme: str = "acat") -> list[tuple[str, str]]:
    rows = conn.execute(
        "SELECT c.id, c.label, coalesce(c.scope_note, ''),"
        " coalesce((SELECT group_concat(text, ' ') FROM label WHERE concept_id = c.id AND lang = 'en'"
        "   AND kind IN ('alt', 'desc')), ''),"
        " coalesce((SELECT group_concat(d.text, ' ') FROM document d JOIN document_concept dc ON dc.doc_id = d.id"
        "   WHERE dc.concept_id = c.id), '')"
        " FROM concept c WHERE c.scheme = ? AND c.status = 'active' ORDER BY c.id", (scheme,)).fetchall()
    # the label counts three times: it is the most deliberate text a concept has
    return [(r[0], " ".join([r[1]] * 3 + [r[2], r[3], r[4]])) for r in rows]


def build(conn: sqlite3.Connection, dims: int = 48, k: int = 6, actor: str = "acat semantic") -> dict:
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("the semantic layer needs numpy (pip install numpy); everything else works without it") from exc
    items = concept_texts(conn)
    ids = [i for i, _ in items]
    docs = [tokenize(t) for _, t in items]
    n = len(docs)
    df: dict[str, int] = {}
    for toks in docs:
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    vocab = sorted(t for t, c in df.items() if 2 <= c <= 0.5 * n)
    col = {t: j for j, t in enumerate(vocab)}
    A = np.zeros((n, len(vocab)))
    idf = np.array([np.log((1 + n) / (1 + df[t])) + 1.0 for t in vocab])
    for i, toks in enumerate(docs):
        counts: dict[int, int] = {}
        for t in toks:
            j = col.get(t)
            if j is not None:
                counts[j] = counts.get(j, 0) + 1
        for j, c in counts.items():
            A[i, j] = (1.0 + np.log(c)) * idf[j]
    norms = np.linalg.norm(A, axis=1, keepdims=True)
    A = A / np.where(norms == 0, 1, norms)
    # truncated SVD through the small Gram matrix: A Aᵀ = U S² Uᵀ
    evals, evecs = np.linalg.eigh(A @ A.T)
    order = np.argsort(evals)[::-1][:dims]
    evals, U = np.clip(evals[order], 0, None), evecs[:, order]
    signs = np.sign(U[np.abs(U).argmax(axis=0), np.arange(U.shape[1])])
    U = U * np.where(signs == 0, 1, signs)                 # deterministic sign per component
    V = U * np.sqrt(evals)
    vn = np.linalg.norm(V, axis=1, keepdims=True)
    Vn = V / np.where(vn == 0, 1, vn)
    S = Vn @ Vn.T
    np.fill_diagonal(S, -1.0)
    # 2-D seed layout: principal components of the concept vectors, scaled into [-1, 1]
    Vc = Vn - Vn.mean(axis=0)
    _, _, Wt = np.linalg.svd(Vc, full_matrices=False)
    xy = Vc @ Wt[:2].T
    xy = xy / max(1e-9, np.abs(xy).max())
    model_id = f"lsa-tfidf-svd-{dims}"
    manifest = manifest_sha512([(i, sha512_bytes(t.encode("utf-8"))) for i, t in items])
    params = {"dims": dims, "k": k, "vocabulary": len(vocab), "documents": n,
              "text": "label x3 + scope note + English alt labels and descriptions + attached corpus text",
              "weighting": "sublinear tf x smoothed idf, rows L2-normalised; df in [2, n/2]",
              "licence_note": "fit partly on CC BY-SA Wikipedia text; vectors are derived statistics"}
    for t in ("layout", "neighbor", "embedding"):
        conn.execute(f"DELETE FROM {t} WHERE model = ?", (model_id,))
    conn.execute("INSERT OR REPLACE INTO model(id, method, params, input_manifest, created_at) VALUES (?,?,?,?,?)",
                 (model_id, "latent semantic analysis (TF-IDF + truncated SVD); not a neural model",
                  json.dumps(params, sort_keys=True), manifest, utcnow()))
    for i, cid in enumerate(ids):
        conn.execute("INSERT INTO embedding(target, model, dim, vec) VALUES (?,?,?,?)",
                     (cid, model_id, dims, struct.pack(f"<{V.shape[1]}f", *Vn[i])))
        conn.execute("INSERT INTO layout(target, model, x, y) VALUES (?,?,?,?)",
                     (cid, model_id, float(xy[i, 0]), float(xy[i, 1])))
        for rank, j in enumerate(np.argsort(S[i])[::-1][:k]):
            if S[i, j] <= 0:
                break
            conn.execute("INSERT INTO neighbor(target, other, model, score, rank) VALUES (?,?,?,?,?)",
                         (cid, ids[j], model_id, float(S[i, j]), rank))
    explained = float(evals.sum() / max(1e-12, np.trace(A @ A.T)))
    ledger.record(conn, actor, "semantic-build", target=model_id,
                  detail={**params, "variance_kept": round(explained, 4)}, receipt=f"input-manifest:{manifest}",
                  undo=f"DELETE the rows of model {model_id} from embedding, neighbor and layout")
    return {"model": model_id, "concepts": n, "vocabulary": len(vocab), "variance_kept": round(explained, 4)}


def unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))
