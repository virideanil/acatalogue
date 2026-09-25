"""Bake the particle layout: run the browser's own compiled physics (viz/dist/physics.js) in Node, from
its deterministic placement, until the field rests; store the positions in `layout`.

The layout model is named by the SHA-512 of the physics modules, so a changed physics is a different
model, and it records the SHA-512 of the graph it was computed for, so a stale layout is visible.
The browser adopts a complete layout and starts at rest; it never treats its own run as canonical.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from . import ledger
from .util import REPO_ROOT, utcnow

VIZ = REPO_ROOT / "viz"
# the modules the bake executes: what the positions depend on
MODULES = ("dist/physics.js", "dist/quadtree.js", "dist/grid.js", "dist/rng.js", "dist/data.js", "bake.mjs")


def graph_digest(g: dict) -> str:
    """SHA-512 over what the physics sees: node ids, schemes, roots, depths, masses, and edges."""
    body = json.dumps({"nodes": [[n["id"], n["scheme"], n["root"], n["depth"], n["mass"]] for n in g["nodes"]],
                       "edges": [[e["s"], e["t"], e["k"], e["w"]] for e in g["edges"]]},
                      separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha512(body.encode("utf-8")).hexdigest()


def physics_manifest() -> tuple[str, dict[str, str]]:
    files = {m: hashlib.sha512((VIZ / m).read_bytes()).hexdigest() for m in MODULES}
    body = "\n".join(f"{name}\t{digest}" for name, digest in sorted(files.items()))
    return hashlib.sha512(body.encode("utf-8")).hexdigest(), files


def bake(conn: sqlite3.Connection, max_steps: int = 20000, actor: str = "acat bake") -> dict:
    from .views import graph
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("baking needs Node.js (the same engine family as the browser) on PATH")
    g = graph(conn, with_layout=False)
    manifest, files = physics_manifest()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "graph.json"
        path.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
        out = subprocess.run([node, str(VIZ / "bake.mjs"), str(path), str(max_steps)], capture_output=True,
                             text=True, check=True, cwd=VIZ)
    result = json.loads(out.stdout)
    model_id = f"layout/physics-{manifest[:16]}"
    params = {"max_steps": max_steps, "steps": result["steps"], "asleep": result["asleep"], "node": result["node"],
              "physics_manifest_sha512": manifest, "modules": files}
    conn.execute("INSERT INTO model(id, method, params, input_manifest, created_at) VALUES (?,?,?,?,?)"
                 " ON CONFLICT(id) DO UPDATE SET params = excluded.params, input_manifest = excluded.input_manifest,"
                 " created_at = excluded.created_at",
                 (model_id, "particle positions at rest after the fixed steps of viz/dist/physics.js from its "
                            "deterministic placement (baked in Node)", json.dumps(params, sort_keys=True),
                  graph_digest(g), utcnow()))
    conn.execute("DELETE FROM layout WHERE model = ?", (model_id,))
    conn.executemany("INSERT INTO layout(target, model, x, y) VALUES (?,?,?,?)",
                     [(cid, model_id, x, y) for cid, (x, y) in sorted(result["positions"].items())])
    stats = {"model": model_id, "nodes": result["nodes"], "edges": result["edges"], "steps": result["steps"],
             "asleep": result["asleep"], "ms": result["ms"], "graph_sha512": graph_digest(g)[:32]}
    ledger.record(conn, actor, "bake-layout", target=f"model/{model_id}", detail=stats,
                  receipt=f"physics-manifest:{manifest[:32]}",
                  undo=f"DELETE FROM layout WHERE model = '{model_id}' (the browser then settles live)")
    conn.commit()
    return stats
