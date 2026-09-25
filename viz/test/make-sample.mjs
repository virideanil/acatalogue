#!/usr/bin/env node
// Generator for a SYNTHETIC graph in the /api/graph shape (docs/API.md).
//
// The output is for tests, screenshots and performance runs only. Every label is a
// neutral placeholder ("Domain 01", "Topic 03.2.1", "Region 4"), every number comes
// from a seeded PRNG, and the scheme titles say "synthetic". It is never real data.
//
// Usage (from viz/):
//   node test/make-sample.mjs                         # writes test/fixtures/graph.sample.json
//   node test/make-sample.mjs --nodes 6000 --space 200 --out /tmp/graph.6000.json
// Options: --nodes <acat nodes, default 600>  --space <space nodes, default 60>
//          --seed <uint32, default 20260925>   --out <path>
//
// The same arguments always produce byte-identical output.

import { writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

/** mulberry32: small, fast, seeded PRNG returning floats in [0, 1). */
export function mulberry32(seed) {
  let a = seed >>> 0;
  return function next() {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const pad2 = (n) => String(n).padStart(2, "0");

/**
 * Split `total` items over `bins` bins with seeded random weights; every bin gets at
 * least `min` when the total allows it.
 */
function split(total, bins, rand, min = 0) {
  const out = new Array(bins).fill(0);
  if (bins === 0) return out;
  let left = total;
  if (total >= bins * min) {
    for (let i = 0; i < bins; i++) out[i] = min;
    left -= bins * min;
  }
  const w = [];
  let sw = 0;
  for (let i = 0; i < bins; i++) {
    const v = 0.35 + rand() * 1.3;
    w.push(v);
    sw += v;
  }
  let given = 0;
  for (let i = 0; i < bins; i++) {
    const k = Math.floor((left * w[i]) / sw);
    out[i] += k;
    given += k;
  }
  for (let r = left - given, i = 0; r > 0; r--, i = (i + 1) % bins) out[Math.floor(rand() * bins)] += 1;
  return out;
}

/** Log-uniform integer in [lo, hi]. */
function logUniform(rand, lo, hi) {
  return Math.max(lo, Math.min(hi, Math.round(Math.exp(Math.log(lo) + rand() * (Math.log(hi) - Math.log(lo))))));
}

/**
 * Build one scheme's tree: `roots` top concepts, `total` nodes including roots,
 * `maxDepth` levels below the roots.
 */
function buildTree(rand, { scheme, roots, total, maxDepth, rootId, rootLabel, childId, childLabel }) {
  const nodes = [];
  const parentOf = new Map();
  const rootNodes = [];
  for (let r = 1; r <= roots; r++) {
    const n = { id: rootId(r), label: rootLabel(r), scheme, depth: 0, path: [r] };
    nodes.push(n);
    rootNodes.push(n);
  }
  const budgets = split(total - roots, roots, rand, maxDepth);
  rootNodes.forEach((root, ri) => {
    const budget = budgets[ri];
    // Per-level counts: the first level is small, deeper levels take the rest.
    const n1 = Math.max(1, Math.min(budget, Math.round(Math.cbrt(budget) * (1.1 + rand() * 0.6))));
    const counts = [n1];
    let left = budget - n1;
    for (let d = 2; d <= maxDepth; d++) {
      const share = d === maxDepth ? left : Math.round(left * (0.5 + rand() * 0.15));
      counts.push(share);
      left -= share;
    }
    let level = [root];
    counts.forEach((count, li) => {
      const per = split(count, level.length, rand, li === 0 ? 0 : 0);
      const next = [];
      level.forEach((parent, pi) => {
        for (let c = 1; c <= per[pi]; c++) {
          const path = [...parent.path, c];
          const n = { id: childId(path), label: childLabel(path), scheme, depth: li + 1, path };
          nodes.push(n);
          parentOf.set(n.id, [parent.id]);
          next.push(n);
        }
      });
      level = next.length > 0 ? next : level;
    });
  });
  return { nodes, parentOf, rootNodes };
}

export function makeSample({ acatNodes = 600, spaceNodes = 60, seed = 20260925 } = {}) {
  const rand = mulberry32(seed);
  const acat = buildTree(rand, {
    scheme: "acat",
    roots: 13,
    total: acatNodes,
    maxDepth: 3,
    rootId: (r) => `acat/domain-${pad2(r)}`,
    rootLabel: (r) => `Domain ${pad2(r)}`,
    childId: (p) => `acat/domain-${pad2(p[0])}.${p.slice(1).join(".")}`,
    childLabel: (p) => `Topic ${pad2(p[0])}.${p.slice(1).join(".")}`,
  });
  const space = buildTree(rand, {
    scheme: "space",
    roots: 5,
    total: spaceNodes,
    maxDepth: 2,
    rootId: (r) => `space/region-${r}`,
    rootLabel: (r) => `Region ${r}`,
    childId: (p) => `space/region-${p[0]}.${p.slice(1).join(".")}`,
    childLabel: (p) => (p.length === 2 ? `Area ${p.join(".")}` : `Place ${p.join(".")}`),
  });

  const all = [...acat.nodes, ...space.nodes];
  const parentOf = new Map([...acat.parentOf, ...space.parentOf]);
  const byId = new Map(all.map((n) => [n.id, n]));

  // A little poly-hierarchy: some deep acat nodes get a second parent one level up.
  const deep = acat.nodes.filter((n) => n.depth >= 2);
  const polyCount = Math.max(3, Math.round(deep.length * 0.015));
  for (let k = 0; k < polyCount; k++) {
    const n = deep[Math.floor(rand() * deep.length)];
    const candidates = acat.nodes.filter((m) => m.depth === n.depth - 1 && !parentOf.get(n.id).includes(m.id));
    if (candidates.length === 0) continue;
    const p = candidates[Math.floor(rand() * candidates.length)];
    parentOf.get(n.id).push(p.id);
  }

  // root = the root reached through the first parent by id order (docs/API.md).
  const rootOf = (id) => {
    const n = byId.get(id);
    if (n.depth === 0) return id;
    const parents = [...parentOf.get(id)].sort();
    return rootOf(parents[0]);
  };

  // Descendant counts (unique) for mass.
  const children = new Map();
  for (const [c, ps] of parentOf) for (const p of ps) (children.get(p) ?? children.set(p, []).get(p)).push(c);
  const descendants = (id, seen = new Set()) => {
    for (const c of children.get(id) ?? []) if (!seen.has(c)) { seen.add(c); descendants(c, seen); }
    return seen;
  };

  const nodesOut = all.map((n) => {
    const nullLangs = rand() < 0.12;
    const lang = [
      [140, 320],
      [50, 260],
      [12, 160],
      [1, 90],
    ][Math.min(n.depth, 3)];
    const docs = n.depth === 0 ? 1 + Math.floor(rand() * 3) : rand() < 0.45 ? Math.floor(rand() * 3) : 0;
    const desc = descendants(n.id).size;
    const hasXY = rand() < 0.5;
    const xy = hasXY ? [Math.round((rand() * 2 - 1) * 1000) / 1000, Math.round((rand() * 2 - 1) * 1000) / 1000] : null;
    return {
      id: n.id,
      label: n.label,
      scheme: n.scheme,
      root: rootOf(n.id),
      depth: n.depth,
      mass: Math.round((1 + Math.log1p(desc + docs)) * 1000) / 1000,
      langs: nullLangs ? null : logUniform(rand, lang[0], lang[1]),
      docs,
      xy,
    };
  });
  nodesOut.sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  const index = new Map(nodesOut.map((n, i) => [n.id, i]));

  const edges = [];
  const seenPair = new Set();
  const addEdge = (s, t, k, w) => {
    const key = s < t ? `${s}:${t}` : `${t}:${s}`;
    if (s === t || seenPair.has(key)) return false;
    seenPair.add(key);
    edges.push({ s, t, k, w: Math.round(w * 1000) / 1000 });
    return true;
  };
  for (const [c, ps] of parentOf) for (const p of ps) addEdge(index.get(c), index.get(p), "broader", 1);

  const acatIdx = nodesOut.flatMap((n, i) => (n.scheme === "acat" ? [i] : []));
  const spaceIdx = nodesOut.flatMap((n, i) => (n.scheme === "space" ? [i] : []));
  const pick = (arr) => arr[Math.floor(rand() * arr.length)];
  const scale = acatNodes / 600;
  for (let k = 0, made = 0; made < Math.round(40 * scale) && k < 10000; k++) {
    if (addEdge(pick(acatIdx), pick(acatIdx), "related", 0.4 + rand() * 0.6)) made++;
  }
  for (let k = 0, made = 0; made < Math.round(25 * scale) && k < 10000; k++) {
    if (addEdge(pick(acatIdx), pick(spaceIdx), "mapping", 0.5 + rand() * 0.5)) made++;
  }
  for (let k = 0, made = 0; made < Math.round(150 * scale) && k < 20000; k++) {
    const a = pick(acatIdx);
    // Mostly within the same domain, sometimes across.
    const sameRoot = acatIdx.filter((i) => nodesOut[i].root === nodesOut[a].root);
    const b = rand() < 0.7 ? pick(sameRoot) : pick(acatIdx);
    if (addEdge(a, b, "semantic", 0.3 + rand() * 0.65)) made++;
  }
  const kindOrder = { broader: 0, related: 1, mapping: 2, semantic: 3 };
  edges.sort((a, b) => kindOrder[a.k] - kindOrder[b.k] || a.s - b.s || a.t - b.t);

  const count = (scheme) => nodesOut.filter((n) => n.scheme === scheme).length;
  return {
    version: 1,
    generated_at: "2026-09-25T00:00:00Z",
    note: `SYNTHETIC TEST FIXTURE generated by viz/test/make-sample.mjs (seed ${seed}). Placeholder labels and seeded random numbers; not real data.`,
    schemes: [
      { id: "acat", title: "Synthetic placeholder compendium (not real data)", origin: "synthetic", n: count("acat") },
      { id: "space", title: "Synthetic placeholder regions (not real data)", origin: "synthetic", n: count("space") },
    ],
    nodes: nodesOut,
    edges,
  };
}

/** One node / edge per line: small diffs when the generator changes. */
export function serialize(payload) {
  const { nodes, edges, ...head } = payload;
  const headJson = JSON.stringify(head, null, 1).replace(/\n}$/, "");
  return (
    headJson +
    ',\n "nodes": [\n' +
    nodes.map((n) => "  " + JSON.stringify(n)).join(",\n") +
    '\n ],\n "edges": [\n' +
    edges.map((e) => "  " + JSON.stringify(e)).join(",\n") +
    "\n ]\n}\n"
  );
}

function main(argv) {
  const opts = { acatNodes: 600, spaceNodes: 60, seed: 20260925 };
  let out = resolve(dirname(fileURLToPath(import.meta.url)), "fixtures/graph.sample.json");
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const v = argv[i + 1];
    if (a === "--nodes") (opts.acatNodes = Number(v)), i++;
    else if (a === "--space") (opts.spaceNodes = Number(v)), i++;
    else if (a === "--seed") (opts.seed = Number(v) >>> 0), i++;
    else if (a === "--out") (out = resolve(v)), i++;
    else throw new Error(`unknown argument: ${a}`);
  }
  if (!(opts.acatNodes >= 13 * 4) || !(opts.spaceNodes >= 5 * 3)) throw new Error("too few nodes");
  const payload = makeSample(opts);
  writeFileSync(out, serialize(payload));
  const counts = payload.edges.reduce((m, e) => ((m[e.k] = (m[e.k] ?? 0) + 1), m), {});
  console.log(`wrote ${out}: ${payload.nodes.length} nodes, ${payload.edges.length} edges ${JSON.stringify(counts)}`);
}

// Run only when invoked directly, never when `node --test` sweeps the test/ directory.
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url) && !process.env.NODE_TEST_CONTEXT) {
  main(process.argv.slice(2));
}
