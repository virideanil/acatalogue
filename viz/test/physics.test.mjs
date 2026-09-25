// Physics tests. They run against the compiled ES modules in dist/ (`npm test` builds
// first). The graph is the synthetic fixture from test/make-sample.mjs, not real data.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { Sim, PHYSICS, repulsionBarnesHut, repulsionBrute } from "../dist/physics.js";
import { QuadTree } from "../dist/quadtree.js";
import { mulberry32 } from "../dist/rng.js";

const fixture = JSON.parse(readFileSync(new URL("./fixtures/graph.sample.json", import.meta.url), "utf8"));

/** One simulation run for 3000 steps, shared by the tests that only read it. */
let shared = null;
function run3000() {
  if (shared) return shared;
  const sim = new Sim(fixture);
  const ke = [];
  for (let k = 0; k < 3000; k++) {
    sim.step();
    ke.push(sim.kinetic);
  }
  shared = { sim, ke };
  return shared;
}

test("fixture: synthetic, ~600 acat nodes under 13 placeholder domains plus a small space scheme", () => {
  const acat = fixture.nodes.filter((n) => n.scheme === "acat");
  const space = fixture.nodes.filter((n) => n.scheme === "space");
  const roots = acat.filter((n) => n.depth === 0);
  assert.equal(roots.length, 13);
  assert.ok(roots.every((n) => /^Domain \d\d$/.test(n.label)), "root labels are placeholders");
  assert.ok(acat.length >= 580 && acat.length <= 620, `acat nodes: ${acat.length}`);
  assert.ok(space.length >= 50 && space.length <= 70, `space nodes: ${space.length}`);
  assert.ok(fixture.schemes.every((s) => /synthetic/i.test(s.title)), "schemes say synthetic");
  const kinds = new Set(fixture.edges.map((e) => e.k));
  for (const k of ["broader", "related", "mapping", "semantic"]) assert.ok(kinds.has(k), `has ${k} edges`);
  assert.ok(fixture.nodes.some((n) => n.langs === null), "some langs are null");
});

test("no NaN or Infinity after 3000 steps on the 600-node graph", () => {
  const { sim } = run3000();
  for (const [name, arr] of Object.entries({ x: sim.x, y: sim.y, vx: sim.vx, vy: sim.vy })) {
    for (let i = 0; i < arr.length; i++) assert.ok(Number.isFinite(arr[i]), `${name}[${i}] = ${arr[i]}`);
  }
  assert.ok(Number.isFinite(sim.kinetic));
});

test("kinetic energy ends far below its early peak", (t) => {
  const { sim, ke } = run3000();
  const early = Math.max(...ke.slice(0, 600));
  const last = ke[ke.length - 1];
  t.diagnostic(`early peak KE ${early.toFixed(1)}, final KE ${last.toFixed(4)}, ratio ${(last / early).toExponential(2)}, asleep: ${!sim.awake}`);
  assert.ok(early > 0);
  assert.ok(last < early * 1e-3, `final ${last} vs early peak ${early}`);
});

test("spring-connected pairs sit closer than random unconnected pairs", (t) => {
  const { sim } = run3000();
  const connected = new Set();
  let sum = 0;
  let count = 0;
  for (let e = 0; e < sim.m; e++) {
    const s = sim.es[e];
    const u = sim.et[e];
    connected.add(s < u ? `${s}:${u}` : `${u}:${s}`);
    if (sim.ekind[e] === 3 && !sim.semantic) continue; // semantic springs are off by default
    sum += Math.hypot(sim.x[s] - sim.x[u], sim.y[s] - sim.y[u]);
    count++;
  }
  const rand = mulberry32(7);
  let rsum = 0;
  let rcount = 0;
  while (rcount < 5000) {
    const a = Math.floor(rand() * sim.n);
    const b = Math.floor(rand() * sim.n);
    if (a === b || connected.has(a < b ? `${a}:${b}` : `${b}:${a}`)) continue;
    rsum += Math.hypot(sim.x[a] - sim.x[b], sim.y[a] - sim.y[b]);
    rcount++;
  }
  const meanConnected = sum / count;
  const meanRandom = rsum / rcount;
  t.diagnostic(`mean connected ${meanConnected.toFixed(1)}, mean random unconnected ${meanRandom.toFixed(1)}`);
  assert.ok(meanConnected < meanRandom);
});

function randomCloud(n, seed, radius) {
  const rand = mulberry32(seed);
  const x = new Float64Array(n);
  const y = new Float64Array(n);
  const q = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    const r = radius * Math.sqrt(rand());
    const a = rand() * Math.PI * 2;
    x[i] = r * Math.cos(a);
    y[i] = r * Math.sin(a);
    q[i] = Math.sqrt(1 + rand() * 4);
  }
  return { x, y, q };
}

function forceError(n, x, y, q, params) {
  const bx = new Float64Array(n);
  const by = new Float64Array(n);
  const tx = new Float64Array(n);
  const ty = new Float64Array(n);
  repulsionBrute(x, y, q, n, params, bx, by);
  repulsionBarnesHut(new QuadTree(), x, y, q, n, params, tx, ty);
  let num = 0;
  let den = 0;
  const per = [];
  for (let i = 0; i < n; i++) {
    const d = Math.hypot(tx[i] - bx[i], ty[i] - by[i]);
    const m = Math.hypot(bx[i], by[i]);
    num += d;
    den += m;
    if (m > 0) per.push(d / m);
  }
  per.sort((a, b) => a - b);
  return { aggregate: num / den, p95: per[Math.floor(per.length * 0.95)] ?? 0, max: per[per.length - 1] ?? 0 };
}

test("Barnes-Hut force within 5% of brute force on a random 300-node sample", (t) => {
  const n = 300;
  const base = { k: PHYSICS.repulsion, eps2: PHYSICS.softening ** 2, cutoffInner: PHYSICS.cutoffInner, cutoffOuter: PHYSICS.cutoffOuter };
  // A cloud wide enough that the cutoff matters, and one where it does not.
  const cases = [
    { name: "cutoff on, radius 260", cloud: randomCloud(n, 11, 260), params: { ...base, theta: 0.3 } },
    { name: "cutoff off, radius 400", cloud: randomCloud(n, 12, 400), params: { ...base, theta: 0.3, cutoffInner: Infinity, cutoffOuter: Infinity } },
  ];
  for (const c of cases) {
    const err = forceError(n, c.cloud.x, c.cloud.y, c.cloud.q, c.params);
    t.diagnostic(`${c.name}, theta 0.3: aggregate ${(err.aggregate * 100).toFixed(3)}%, p95 ${(err.p95 * 100).toFixed(3)}%, max ${(err.max * 100).toFixed(3)}%`);
    assert.ok(err.aggregate < 0.05, `${c.name}: aggregate error ${err.aggregate}`);
    assert.ok(err.p95 < 0.05, `${c.name}: p95 error ${err.p95}`);
  }
  // At the working theta (0.8) the error is reported, and bounded loosely.
  const c = cases[1];
  const err = forceError(n, c.cloud.x, c.cloud.y, c.cloud.q, { ...c.params, theta: PHYSICS.theta });
  t.diagnostic(`cutoff off, theta ${PHYSICS.theta}: aggregate ${(err.aggregate * 100).toFixed(3)}%, p95 ${(err.p95 * 100).toFixed(3)}%`);
  assert.ok(err.aggregate < 0.15);
});

test("deterministic: two runs from the same data give identical positions", () => {
  const a = new Sim(fixture);
  const b = new Sim(structuredClone(fixture));
  assert.deepEqual(Buffer.from(a.x.buffer), Buffer.from(b.x.buffer), "initial x");
  for (let k = 0; k < 1500; k++) {
    a.step();
    b.step();
  }
  assert.ok(Buffer.from(a.x.buffer).equals(Buffer.from(b.x.buffer)), "x after 1500 steps");
  assert.ok(Buffer.from(a.y.buffer).equals(Buffer.from(b.y.buffer)), "y after 1500 steps");
});

test("ring spring holds every root within ±15% of its ring radius", (t) => {
  const { sim } = run3000();
  const report = [];
  for (let s = 0; s < sim.roots.length; s++) {
    const i = sim.roots[s];
    const r = Math.hypot(sim.x[i], sim.y[i]);
    const R = sim.ringRadius[s];
    report.push((r / R).toFixed(3));
    assert.ok(Math.abs(r / R - 1) <= 0.15, `${sim.ids[i]}: r/R = ${r / R}`);
  }
  t.diagnostic(`inner R ${sim.innerRadius.toFixed(1)}, outer R ${sim.outerRadius.toFixed(1)}, r/R: ${report.join(" ")}`);
  // Roots start at equal angles in id order and are not pinned: the angles moved.
  const fresh = new Sim(fixture);
  let moved = 0;
  for (let s = 0; s < sim.roots.length; s++) {
    const i = sim.roots[s];
    const a0 = Math.atan2(fresh.y[i], fresh.x[i]);
    const a1 = Math.atan2(sim.y[i], sim.x[i]);
    moved = Math.max(moved, Math.abs(Math.atan2(Math.sin(a1 - a0), Math.cos(a1 - a0))));
  }
  assert.ok(moved > 1e-4, "root angles are free to move");
});

test("sleeps when calm, wakes on a grab, and the grabbed particle follows a spring", () => {
  const sim = new Sim(fixture);
  sim.settle(20000);
  assert.equal(sim.awake, false, "asleep after settling");
  const i = sim.roots[0];
  const x0 = sim.x[i];
  const y0 = sim.y[i];
  sim.grab(i, x0 + 60, y0);
  assert.equal(sim.awake, true, "awake after grab");
  sim.step();
  const first = Math.hypot(sim.x[i] - x0, sim.y[i] - y0);
  assert.ok(first < 10, `no teleport: moved ${first} in one step`);
  for (let k = 0; k < 240; k++) sim.step();
  const gap = Math.hypot(sim.x[i] - (x0 + 60), sim.y[i] - y0);
  assert.ok(gap < 15, `follows the pointer: ${gap} away after 2 s`);
  sim.release();
  sim.settle(20000);
  assert.equal(sim.awake, false, "asleep again after release");
});

test("frame accumulator: fixed steps, and a long frame is clamped", () => {
  const sim = new Sim(fixture);
  const a = sim.advance(1 / 60);
  assert.equal(a.steps, 2, "1/60 s at dt 1/120 is two steps");
  const b = sim.advance(10);
  assert.ok(b.steps <= PHYSICS.maxStepsPerFrame, `steps ${b.steps}`);
  assert.ok(sim.accumulator < PHYSICS.dt, "backlog dropped");
});

test("glow energy decays as dE/dt = -E/tau", () => {
  const sim = new Sim(fixture);
  sim.excite(3, 1);
  const steps = 60;
  for (let k = 0; k < steps; k++) sim.stepGlow();
  const expected = Math.exp((-steps * PHYSICS.dt) / PHYSICS.glow.tau);
  assert.ok(Math.abs(sim.energy[3] - expected) < 1e-12, `${sim.energy[3]} vs ${expected}`);
  sim.hold(5, true);
  for (let k = 0; k < steps; k++) sim.stepGlow();
  assert.equal(sim.energy[5], 1, "a held glow stays at 1");
});

test("bad edges are dropped, not fatal", () => {
  const g = {
    nodes: fixture.nodes.slice(0, 20),
    edges: [
      { s: 0, t: 1, k: "broader", w: 1 },
      { s: 0, t: 99, k: "broader", w: 1 },
      { s: 2, t: 2, k: "related", w: 1 },
      { s: 3, t: 4, k: "nonsense", w: 1 },
    ],
  };
  const sim = new Sim(g);
  assert.equal(sim.m, 1);
  assert.equal(sim.droppedEdges, 3);
  for (let k = 0; k < 200; k++) sim.step();
  assert.ok(Array.from(sim.x).every(Number.isFinite));
});
