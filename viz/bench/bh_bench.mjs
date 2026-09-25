// Times acatalogue's own repulsionBarnesHut (viz/dist/physics.js) on synthetic uniform discs
// at the layout's packing density (ring.nodeArea = 700 world units^2 per particle).
import { repulsionBarnesHut, PHYSICS } from "../dist/physics.js";
import { QuadTree } from "../dist/quadtree.js";

function mulberry32(a) { return () => { a |= 0; a = (a + 0x6d2b79f5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }

function run(n, cutoff, reps) {
  const rnd = mulberry32(42);
  const R = Math.sqrt((n * PHYSICS.ring.nodeArea) / Math.PI);
  const x = new Float64Array(n), y = new Float64Array(n), q = new Float64Array(n).fill(1);
  for (let i = 0; i < n; i++) { const r = R * Math.sqrt(rnd()), a = rnd() * 2 * Math.PI; x[i] = r * Math.cos(a); y[i] = r * Math.sin(a); }
  const fx = new Float64Array(n), fy = new Float64Array(n);
  const p = { k: PHYSICS.repulsion, eps2: PHYSICS.softening ** 2, theta: PHYSICS.theta,
              cutoffInner: cutoff ? PHYSICS.cutoffInner : Infinity, cutoffOuter: cutoff ? PHYSICS.cutoffOuter : Infinity };
  const tree = new QuadTree();
  repulsionBarnesHut(tree, x, y, q, n, p, fx, fy); // warm-up
  const t0 = performance.now();
  for (let r = 0; r < reps; r++) { fx.fill(0); fy.fill(0); repulsionBarnesHut(tree, x, y, q, n, p, fx, fy); }
  return (performance.now() - t0) / reps;
}
console.log(`node ${process.version}; dt=${PHYSICS.dt}s; theta=${PHYSICS.theta}; cutoff ${PHYSICS.cutoffInner}-${PHYSICS.cutoffOuter}`);
for (const n of [1000, 10000, 100000, 1000000]) {
  const reps = n >= 1000000 ? 3 : n >= 100000 ? 5 : 20;
  const c = run(n, true, reps);
  const u = n <= 100000 ? run(n, false, Math.max(2, reps >> 1)) : NaN;
  console.log(`n=${n.toString().padStart(8)}  cutoff-BH ${c.toFixed(2).padStart(9)} ms/step   no-cutoff-BH ${isNaN(u) ? "   (skipped)" : u.toFixed(2).padStart(9) + " ms/step"}`);
}
