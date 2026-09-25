// Cache-friendly cell list: counting-sort particles into cell order (sorted copies sx, sy, sq), then
// sweep cells in order so the 3x3 neighbourhood stays in cache. Same kernel; verified vs brute force.
import { repulsionBarnesHut, repulsionBrute, PHYSICS } from "../dist/physics.js";
import { QuadTree } from "../dist/quadtree.js";
function mulberry32(a) { return () => { a |= 0; a = (a + 0x6d2b79f5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
const P = { k: PHYSICS.repulsion, eps2: PHYSICS.softening ** 2, theta: PHYSICS.theta, cutoffInner: PHYSICS.cutoffInner, cutoffOuter: PHYSICS.cutoffOuter };
const r1sq = P.cutoffInner ** 2, rcsq = P.cutoffOuter ** 2, invDen = 1 / Math.pow(rcsq - r1sq, 3), eps2 = P.eps2;
class CellList {
  constructor() { this.cap = 0; this.cells = 0; }
  ensure(n, cells) {
    if (n > this.cap) { this.cap = n; this.order = new Int32Array(n); this.cellOf = new Int32Array(n); this.sx = new Float64Array(n); this.sy = new Float64Array(n); this.sq = new Float64Array(n); this.ax = new Float64Array(n); this.ay = new Float64Array(n); }
    if (cells + 1 > this.cells) { this.cells = cells + 1; this.start = new Int32Array(cells + 1); this.fill = new Int32Array(cells + 1); }
  }
  run(x, y, q, n, fx, fy) {
    const h = P.cutoffOuter; let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (let i = 0; i < n; i++) { const a = x[i], b = y[i]; if (a < minX) minX = a; if (a > maxX) maxX = a; if (b < minY) minY = b; if (b > maxY) maxY = b; }
    const cols = Math.floor((maxX - minX) / h) + 1, rows = Math.floor((maxY - minY) / h) + 1, cells = cols * rows;
    this.ensure(n, cells); const st = this.start, fl = this.fill, order = this.order, cellOf = this.cellOf, sx = this.sx, sy = this.sy, sq = this.sq, ax = this.ax, ay = this.ay;
    st.fill(0, 0, cells + 1);
    for (let i = 0; i < n; i++) { const c = Math.floor((y[i] - minY) / h) * cols + Math.floor((x[i] - minX) / h); cellOf[i] = c; st[c + 1]++; }
    for (let c = 0; c < cells; c++) st[c + 1] += st[c];
    fl.set(st.subarray(0, cells));
    for (let i = 0; i < n; i++) { const s = fl[cellOf[i]]++; order[s] = i; sx[s] = x[i]; sy[s] = y[i]; sq[s] = q[i]; }
    ax.fill(0, 0, n); ay.fill(0, 0, n);
    for (let cy = 0; cy < rows; cy++) for (let cx = 0; cx < cols; cx++) {
      const c = cy * cols + cx, a0 = st[c], a1 = st[c + 1]; if (a0 === a1) continue;
      const y0 = cy > 0 ? cy - 1 : 0, y1 = cy < rows - 1 ? cy + 1 : cy, x0 = cx > 0 ? cx - 1 : 0, x1 = cx < cols - 1 ? cx + 1 : cx;
      for (let a = a0; a < a1; a++) {
        const xi = sx[a], yi = sy[a]; let fxa = 0, fya = 0;
        for (let gy = y0; gy <= y1; gy++) { const b0 = st[gy * cols + x0], b1 = st[gy * cols + x1 + 1]; // row of 3 cells is contiguous
          for (let b = b0; b < b1; b++) { if (b === a) continue; const dx = xi - sx[b], dy = yi - sy[b], r2 = dx * dx + dy * dy; if (r2 >= rcsq) continue;
            let f = sq[b] / (r2 + eps2); if (r2 > r1sq) { const t = rcsq - r2; f *= t * t * (rcsq + 2 * r2 - 3 * r1sq) * invDen; } fxa += f * dx; fya += f * dy; } }
        ax[a] = fxa; ay[a] = fya;
      }
    }
    for (let a = 0; a < n; a++) { const i = order[a]; fx[i] += P.k * sq[a] * ax[a]; fy[i] += P.k * sq[a] * ay[a]; }
  }
}
function disc(n) { const rnd = mulberry32(42), R = Math.sqrt((n * PHYSICS.ring.nodeArea) / Math.PI);
  const x = new Float64Array(n), y = new Float64Array(n), q = new Float64Array(n).fill(1);
  for (let i = 0; i < n; i++) { const r = R * Math.sqrt(rnd()), a = rnd() * 2 * Math.PI; x[i] = r * Math.cos(a); y[i] = r * Math.sin(a); } return { x, y, q }; }
{ const n = 5000, { x, y, q } = disc(n); const bx = new Float64Array(n), by = new Float64Array(n), gx = new Float64Array(n), gy = new Float64Array(n);
  repulsionBrute(x, y, q, n, P, bx, by); new CellList().run(x, y, q, n, gx, gy);
  let e = 0; for (let i = 0; i < n; i++) e = Math.max(e, Math.hypot(gx[i] - bx[i], gy[i] - by[i])); console.log(`n=5000 max err sorted-grid vs brute = ${e.toExponential(2)}`); }
for (const n of [10000, 100000, 1000000]) {
  const { x, y, q } = disc(n), fx = new Float64Array(n), fy = new Float64Array(n), g = new CellList(), t = new QuadTree(); const reps = n >= 1000000 ? 3 : 8;
  g.run(x, y, q, n, fx, fy); let t0 = performance.now(); for (let r = 0; r < reps; r++) g.run(x, y, q, n, fx, fy); const tg = (performance.now() - t0) / reps;
  repulsionBarnesHut(t, x, y, q, n, P, fx, fy); t0 = performance.now(); for (let r = 0; r < reps; r++) repulsionBarnesHut(t, x, y, q, n, P, fx, fy); const tb = (performance.now() - t0) / reps;
  console.log(`n=${String(n).padStart(8)}  sorted-grid ${tg.toFixed(2).padStart(8)} ms/step   BH ${tb.toFixed(2).padStart(8)} ms/step   speedup x${(tb / tg).toFixed(1)}`);
}
