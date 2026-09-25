"""Dense multilingual embeddings: a published model's own ONNX export and tokenizer, run with ONNX Runtime.

The model is pinned by repository revision and by the SHA-256 of every file used, verified before
use (Hugging Face publishes these hashes for LFS files). Vectors are unit-length float32 stored as
SQLite BLOBs under a model id that names the model and its revision, and searched exactly (numpy);
the LSA layer stays beside it as a labelled baseline, never silently replaced.

Optional dependencies (only for this module): onnxruntime, tokenizers, numpy.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import struct
import time
from pathlib import Path

from . import ledger
from .util import utcnow

CACHE = Path(os.environ.get("ACAT_MODELS", Path.home() / ".cache" / "acatalogue" / "models"))
MODELS = {
    "e5-large-instruct": {
        "repo": "intfloat/multilingual-e5-large-instruct",
        "revision": "274baa43b0e13e37fafa6428dbc7938e62e5c439",
        "licence": "MIT",
        "files": {
            "onnx/model.onnx": "e3aeea5355352d826bd952a9a96fab206c6c72d1a429c8773c9da5ac16e44af5",
            "onnx/model.onnx_data": "4c13ca44e40a7ee86b461398cdee003d656e39f3fa87e1b3152fbada3e61b506",
            "onnx/tokenizer.json": "f59925fcb90c92b894cb93e51bb9b4a6105c5c249fe54ce1c704420ac39b81af",
        },
        "dim": 1024,
        "pooling": "the export's sentence_embedding output (mean over tokens), L2-normalised",
        # E5-instruct: queries carry a one-sentence task instruction, documents none. For matching a
        # name across languages the closest trained task is bitext mining, whose instruction this is.
        "query_prompt": "Instruct: Retrieve parallel sentences.\nQuery: ",
        "document_prompt": "",
        "max_tokens": 64,
    },
}


def model_dir(name: str) -> Path:
    m = MODELS[name]
    return CACHE / m["repo"] / m["revision"]


def fetch_command(name: str) -> str:
    m = MODELS[name]
    return "\n".join(f"curl -L -o {model_dir(name) / f} https://huggingface.co/{m['repo']}/resolve/{m['revision']}/{f}"
                     for f in m["files"])


def verify(name: str) -> dict[str, str]:
    """SHA-256 of every model file against the pinned values; raises when one is missing or differs."""
    out = {}
    for rel, want in MODELS[name]["files"].items():
        path = model_dir(name) / rel
        if not path.exists():
            raise FileNotFoundError(f"{path} is missing; fetch the pinned files:\n{fetch_command(name)}")
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest() != want:
            raise ValueError(f"{rel}: SHA-256 {h.hexdigest()} is not the pinned {want}")
        out[rel] = h.hexdigest()
    return out


def model_id(name: str) -> str:
    return f"dense/{name}@{MODELS[name]['revision'][:12]}"


class Encoder:
    def __init__(self, name: str = "e5-large-instruct", threads: int | None = None):
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer
        self.np = np
        self.name = name
        self.spec = MODELS[name]
        self.hashes = verify(name)
        d = model_dir(name)
        self.tok = Tokenizer.from_file(str(d / "onnx/tokenizer.json"))
        self.tok.enable_truncation(max_length=self.spec["max_tokens"])
        self.tok.enable_padding(pad_id=1, pad_token="<pad>")
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads or os.cpu_count() or 1
        self.session = ort.InferenceSession(str(d / "onnx/model.onnx"), opts, providers=["CPUExecutionProvider"])
        self.runtime = f"onnxruntime {ort.__version__}, CPUExecutionProvider, fp32"

    def encode(self, texts: list[str], *, query: bool, batch: int = 64):
        np = self.np
        prompt = self.spec["query_prompt"] if query else self.spec["document_prompt"]
        out = np.zeros((len(texts), self.spec["dim"]), dtype=np.float32)
        # batches of similar length waste less padding
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
        for start in range(0, len(order), batch):
            idx = order[start:start + batch]
            enc = self.tok.encode_batch([prompt + texts[i] for i in idx])
            ids = np.array([e.ids for e in enc], dtype=np.int64)
            mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
            vec = self.session.run(["sentence_embedding"], {"input_ids": ids, "attention_mask": mask})[0]
            norms = np.linalg.norm(vec, axis=1, keepdims=True)
            out[idx] = vec / np.where(norms == 0, 1, norms)
        return out


def label_texts(conn: sqlite3.Connection, kinds: tuple[str, ...] = ("pref",)) -> list[tuple[int, str, str, str]]:
    """(label id, concept id, lang, text) of the ACAT concepts' labels of these kinds."""
    marks = ",".join("?" * len(kinds))
    return conn.execute(
        f"SELECT l.id, l.concept_id, l.lang, l.text FROM label l JOIN concept c ON c.id = l.concept_id"
        f" WHERE c.scheme = 'acat' AND c.status = 'active' AND l.kind IN ({marks}) ORDER BY l.id", kinds).fetchall()


def embed_labels(conn: sqlite3.Connection, name: str = "e5-large-instruct", kinds: tuple[str, ...] = ("pref",),
                 actor: str = "acat embed", progress=print) -> dict:
    """Document-side vectors for every label of these kinds, stored as label/<id> under the model id.
    Resumable: labels that already have a vector under this model are skipped."""
    enc = Encoder(name)
    mid = model_id(name)
    spec = enc.spec
    params = {"repo": spec["repo"], "revision": spec["revision"], "licence": spec["licence"], "files": enc.hashes,
              "runtime": enc.runtime, "dim": spec["dim"], "pooling": spec["pooling"], "max_tokens": spec["max_tokens"],
              "query_prompt": spec["query_prompt"], "document_prompt": spec["document_prompt"],
              "targets": f"label/<id> for ACAT labels of kinds {','.join(kinds)}"}
    conn.execute("INSERT INTO model(id, method, params, input_manifest, created_at) VALUES (?,?,?,?,?)"
                 " ON CONFLICT(id) DO UPDATE SET params = excluded.params",
                 (mid, f"dense multilingual text embedding ({spec['repo']}), neural; ONNX export run locally",
                  json.dumps(params, sort_keys=True), None, utcnow()))
    have = {r[0] for r in conn.execute("SELECT target FROM embedding WHERE model = ?", (mid,))}
    todo = [r for r in label_texts(conn, kinds) if f"label/{r[0]}" not in have]
    t0 = time.time()
    chunk = 2048
    for start in range(0, len(todo), chunk):
        part = todo[start:start + chunk]
        vecs = enc.encode([r[3] for r in part], query=False)
        conn.executemany("INSERT OR REPLACE INTO embedding(target, model, dim, vec) VALUES (?,?,?,?)",
                         [(f"label/{r[0]}", mid, spec["dim"], vecs[k].astype("<f4").tobytes()) for k, r in enumerate(part)])
        conn.commit()
        done = start + len(part)
        rate = done / max(1e-9, time.time() - t0)
        progress(f"  embedded {done}/{len(todo)} labels ({rate:.0f}/s)")
    stats = {"model": mid, "embedded": len(todo), "already_had": len(have), "seconds": round(time.time() - t0, 1)}
    ledger.record(conn, actor, "embed-labels", target=mid, detail=stats,
                  receipt=f"model-files-sha256:{hashlib.sha256(json.dumps(enc.hashes, sort_keys=True).encode()).hexdigest()[:32]}",
                  undo=f"DELETE FROM embedding WHERE model = '{mid}'")
    conn.commit()
    return stats


def unpack(blob: bytes, dim: int):
    import numpy as np
    return np.frombuffer(blob, dtype="<f4", count=dim)


def load_label_vectors(conn: sqlite3.Connection, name: str = "e5-large-instruct"):
    """(label ids, matrix) of the stored document-side vectors."""
    import numpy as np
    mid = model_id(name)
    rows = conn.execute("SELECT target, vec FROM embedding WHERE model = ? AND target LIKE 'label/%'", (mid,)).fetchall()
    ids = [int(t.split("/", 1)[1]) for t, _ in rows]
    mat = np.frombuffer(b"".join(v for _, v in rows), dtype="<f4").reshape(len(rows), MODELS[name]["dim"]) if rows else \
        np.zeros((0, MODELS[name]["dim"]), dtype=np.float32)
    return ids, mat


__all__ = ["Encoder", "MODELS", "embed_labels", "load_label_vectors", "model_id", "verify", "struct"]
