// Data-layer tests: payload validation, the offline label search, response coercion.
// Runs against dist/ (built by `npm test`).

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { auditFromGraph, localLabelSearch, parseGraph, parseGrep, parseNode, splitMatches } from "../dist/data.js";

const fixture = JSON.parse(readFileSync(new URL("./fixtures/graph.sample.json", import.meta.url), "utf8"));

test("parseGraph keeps a valid payload intact", () => {
  const g = parseGraph(fixture);
  assert.equal(g.payload.nodes.length, fixture.nodes.length);
  assert.equal(g.payload.edges.length, fixture.edges.length);
  assert.equal(g.droppedNodes + g.droppedEdges + g.mergedDuplicates, 0);
  assert.deepEqual(g.warnings, []);
});

test("parseGraph drops and counts bad records, remapping edge indices", () => {
  const raw = {
    version: 1,
    generated_at: "x",
    schemes: [{ id: "acat", title: "A", origin: "authored", n: 3 }],
    nodes: [
      { id: "acat/a", label: "A", scheme: "acat", root: "acat/a", depth: 0, mass: 2, langs: 10, docs: 1, xy: null },
      { label: "no id" },
      { id: "acat/b", label: "B", scheme: "acat", root: "acat/a", depth: 1, mass: "heavy", langs: "many", docs: -3, xy: [0.1, "y"] },
      { id: "acat/a", label: "duplicate of A" },
    ],
    edges: [
      { s: 2, t: 0, k: "broader", w: 1 }, // B -> A (index 2 becomes 1)
      { s: 1, t: 0, k: "broader", w: 1 }, // points at the dropped node
      { s: 3, t: 2, k: "related", w: 0.5 }, // the duplicate attaches to the first A
      { s: 0, t: 0, k: "related", w: 1 }, // self loop
      { s: 0, t: 2, k: "sideways", w: 1 }, // unknown kind
    ],
  };
  const g = parseGraph(raw);
  assert.deepEqual(g.payload.nodes.map((n) => n.id), ["acat/a", "acat/b"]);
  assert.equal(g.droppedNodes, 1);
  assert.equal(g.mergedDuplicates, 1);
  assert.equal(g.droppedEdges, 3);
  assert.deepEqual(g.payload.edges, [
    { s: 1, t: 0, k: "broader", w: 1 },
    { s: 0, t: 1, k: "related", w: 0.5 },
  ]);
  const b = g.payload.nodes[1];
  assert.equal(b.mass, 1, "non-numeric mass falls back to 1");
  assert.equal(b.langs, null, "non-numeric langs is unknown, not zero");
  assert.equal(b.docs, 0);
  assert.equal(b.xy, null);
  assert.equal(g.warnings.length, 3);
});

test("parseGraph refuses something that is not a graph", () => {
  assert.throws(() => parseGraph({ hello: "world" }), /not a graph/);
  assert.throws(() => parseGraph(null), /not a graph/);
});

test("splitMatches marks every case-insensitive occurrence and keeps the original text", () => {
  const parts = splitMatches("Topic 04.2 and topic 4", "TOPIC");
  assert.deepEqual(parts, [
    { t: "Topic", m: true },
    { t: " 04.2 and ", m: false },
    { t: "topic", m: true },
    { t: " 4", m: false },
  ]);
  assert.equal(parts.map((p) => p.t).join(""), "Topic 04.2 and topic 4");
  // Characters whose lower case has another length do not shift the offsets.
  const tricky = splitMatches("İstanbul Physik", "physik");
  assert.equal(tricky.map((p) => p.t).join(""), "İstanbul Physik");
  assert.deepEqual(tricky.at(-1), { t: "Physik", m: true });
});

test("offline label search: substring, case-insensitive, exact before prefix before inside", () => {
  const nodes = parseGraph(fixture).payload.nodes;
  const r = localLabelSearch(nodes, "domain 0");
  assert.equal(r.mode, "substring");
  assert.equal(r.scope, "labels");
  assert.deepEqual(r.sql, []);
  assert.equal(r.total, 9);
  assert.ok(r.hits.every((h) => h.title.toLowerCase().includes("domain 0")));
  const exact = localLabelSearch(nodes, "Topic 04.2");
  assert.equal(exact.hits[0].title, "Topic 04.2");
  assert.ok(exact.hits.slice(1).every((h) => h.title.startsWith("Topic 04.2")));
  assert.equal(localLabelSearch(nodes, "   ").total, 0);
});

test("grep and node responses are coerced to the documented shape", () => {
  const g = parseGrep({ query: "q", hits: [{ target: "acat/x", parts: [{ t: "a", m: true }, { t: 3 }], concepts: ["acat/x", 7] }], sql: ["SELECT 1"] });
  assert.equal(g.mode, "words");
  assert.equal(g.error, null);
  assert.deepEqual(g.hits[0].parts, [
    { t: "a", m: true },
    { t: "3", m: false },
  ]);
  assert.deepEqual(g.hits[0].concepts, ["acat/x", "7"]);
  const n = parseNode({ id: "acat/x", labels: [{ lang: "tr", text: "X" }], documents: [{ title: "T", url: "javascript:alert(1)" }] });
  assert.equal(n.label, "acat/x");
  assert.equal(n.langs, null);
  assert.equal(n.labels[0].kind, "");
  assert.equal(n.documents[0].url, "javascript:alert(1)", "kept as text; the UI only links http(s)");
  assert.deepEqual(n.claims, []);
});

test("offline audit is computed from the graph and says so", () => {
  const g = parseGraph(fixture).payload;
  const a = auditFromGraph(g, "acat");
  assert.equal(a.domains.length, 13);
  const total = a.domains.reduce((s, d) => s + d.concepts, 0);
  assert.equal(total, g.nodes.filter((n) => n.scheme === "acat").length);
  assert.ok(a.notes.some((n) => /computed in the browser/i.test(n)));
  assert.ok(a.thinnest.length > 0 && a.thinnest.every((t, k, xs) => k === 0 || xs[k - 1].langs <= t.langs));
});
