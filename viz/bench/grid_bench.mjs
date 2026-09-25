// O(n) cell-list (uniform grid, counting sort) for acatalogue's finite-cutoff repulsion kernel,
// verified against viz/dist/physics.js repulsionBrute, timed against repulsionBarnesHut.
import { repulsionBarnesHut, repulsionBrute, PHYSICS } from "../dist/physics.js";
import { QuadTree } from "../dist/quadtree.js";
function mulberry32(a) { return () => { a |= 0; a = (a + 0x6d2b79f5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
const P = { k: PHYSICS.repulsion, eps2: PHYSICS.softening ** 2, theta: PHYSICS.theta, cutoffInner: PHYSICS.cutoffInner, cutoffOuter: PHYSICS.cutoffOuter };
const r1sq = P.cutoffInner ** 2, rcsq = P.cutoffOuter ** 2, invDen = 1 / Math.pow(rcsq - r1sq, 3);
function makeGrid() { return { cellStart: new Int32Array(0), order: new Int32Array(0), cellOf: new Int32Array(0) }; }
function repulsionGrid(g, x, y, q, n, fx, fy) {
  const h = P.cutoffOuter; let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (let i = 0; i < n; i++) { if (x[i] < minX) minX = x[i]; if (x[i] > maxX) maxX = x[i]; if (y[i] < minY) minY = y[i]; if (y[i] > maxY) maxY = y[i]; }
  const cols = Math.floor((maxX - minX) / h) + 1, rows = Math.floor((maxY - minY) / h) + 1, cells = cols * rows;
  if (g.cellStart.length < cells + 1) g.cellStart = new Int32Array(cells + 1);
  if (g.order.length < n) { g.order = new Int32Array(n); g.cellOf = new Int32Array(n); }
  const cs = g.cellStart, order = g.order, cellOf = g.cellOf; cs.fill(0, 0, cells + 1);
  for (let i = 0; i < n; i++) { const c = Math.floor((y[i] - minY) / h) * cols + Math.floor((x[i] - minX) / h); cellOf[i] = c; cs[c + 1]++; }
  for (let c = 0; c < cells; c++) cs[c + 1] += cs[c];
  const fill = cs.slice(0, cells); for (let i = 0; i < n; i++) order[fill[cellOf[i]]++] = i; // stable: ascending i within a cell
  for (let i = 0; i < n; i++) {
    const cxi = Math.floor((x[i] - minX) / h), cyi = Math.floor((y[i] - minY) / h); let ax = 0, ay = 0;
    for (let gy = Math.max(0, cyi - 1); gy <= Math.min(rows - 1, cyi + 1); gy++)
      for (let gx = Math.max(0, cxi - 1); gx <= Math.min(cols - 1, cxi + 1); gx++) {
        const c = gy * cols + gx;
        for (let s = cs[c]; s < cs[c + 1]; s++) {
          const j = order[s]; if (j === i) continue;
          const dx = x[i] - x[j], dy = y[i] - y[j], r2 = dx * dx + dy * dy; if (r2 >= rcsq) continue;
          let f = q[j] / (r2 + P.eps2); if (r2 > r1sq) { const a = rcsq - r2; f *= a * a * (rcsq + 2 * r2 - 3 * r1sq) * invDen; }
          ax += f * dx; ay += f * dy; // (coincident-point split omitted in this sketch)
        }
      }
    fx[i] += P.k * q[i] * ax; fy[i] += P.k * q[i] * ay;
  }
}
function disc(n) { const rnd = mulberry32(42), R = Math.sqrt((n * PHYSICS.ring.nodeArea) / Math.PI);
  const x = new Float64Array(n), y = new Float64Array(n), q = new Float64Array(n).fill(1);
  for (let i = 0; i < n; i++) { const r = R * Math.sqrt(rnd()), a = rnd() * 2 * Math.PI; x[i] = r * Math.cos(a); y[i] = r * Math.sin(a); } return { x, y, q }; }
// correctness vs brute force
{ const n = 5000, { x, y, q } = disc(n); const bx = new Float64Array(n), by = new Float64Array(n), gx = new Float64Array(n), gy = new Float64Array(n), hx = new Float64Array(n), hy = new Float64Array(n);
  repulsionBrute(x, y, q, n, P, bx, by); repulsionGrid(makeGrid(), x, y, q, n, gx, gy); repulsionBarnesHut(new QuadTree(), x, y, q, n, P, hx, hy);
  let eg = 0, eh = 0, m = 0; for (let i = 0; i < n; i++) { m = Math.max(m, Math.hypot(bx[i], by[i])); eg = Math.max(eg, Math.hypot(gx[i] - bx[i], gy[i] - by[i])); eh = Math.max(eh, Math.hypot(hx[i] - bx[i], hy[i] - by[i])); }
  console.log(`n=5000 max|F|=${m.toExponential(3)}  max err grid=${eg.toExponential(2)}  max err BH(theta=0.8)=${eh.toExponential(2)}`); }
for (const n of [10000, 100000, 1000000]) {
  const { x, y, q } = disc(n), fx = new Float64Array(n), fy = new Float64Array(n), g = makeGrid(), t = new QuadTree();
  const reps = n >= 1000000 ? 3 : 8;
  repulsionGrid(g, x, y, q, n, fx, fy); let t0 = performance.now(); for (let r = 0; r < reps; r++) repulsionGrid(g, x, y, q, n, fx, fy); const tg = (performance.now() - t0) / reps;
  repulsionBarnesHut(t, x, y, q, n, P, fx, fy); t0 = performance.now(); for (let r = 0; r < reps; r++) repulsionBarnesHut(t, x, y, q, n, P, fx, fy); const tb = (performance.now() - t0) / reps;
  console.log(`n=${String(n).padStart(8)}  grid ${tg.toFixed(2).padStart(8)} ms/step   BH ${tb.toFixed(2).padStart(8)} ms/step   speedup x${(tb / tg).toFixed(1)}`);
}
