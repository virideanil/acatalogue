// DOM-free particle system for the knowledge field.
//
// Everything that moves is integrated on a fixed timestep (semi-implicit Euler):
//   (a) Barnes-Hut repulsion between all particles (softened 2D Coulomb, smooth cutoff)
//   (b) Hooke springs along edges, rest length and stiffness by edge kind
//   (c) weak centering gravity
//   (d) the "circle of learning": depth-0 roots feel a radial spring toward a ring
//       radius plus a strong mutual repulsion, so the domains spread around a circle.
//       Roots are never pinned; their angles emerge from the forces, starting from
//       equal angles in id-sorted order.
// plus a stiff, critically damped drag spring from a grabbed particle to the pointer,
// viscous damping, a velocity clamp, kinetic-energy tracking, and sleep/wake.
// The glow energy E of each particle obeys dE/dt = -E/tau, integrated per step.
import { QuadTree, LEAF_EMPTY } from "./quadtree.js";
import { rngFor } from "./rng.js";
export const EDGE_KINDS = ["broader", "related", "mapping", "semantic"];
export const KIND_BROADER = 0;
export const KIND_RELATED = 1;
export const KIND_MAPPING = 2;
export const KIND_SEMANTIC = 3;
export const KIND_CODE = {
    broader: KIND_BROADER,
    related: KIND_RELATED,
    mapping: KIND_MAPPING,
    semantic: KIND_SEMANTIC,
};
/** Every physics constant, in one place. */
export const PHYSICS = Object.freeze({
    dt: 1 / 120,
    maxStepsPerFrame: 4,
    maxFrameSeconds: 0.1,
    frameBudgetMs: 10,
    damping: 4.5,
    maxSpeed: 1500,
    repulsion: 600,
    softening: 6,
    theta: 0.8,
    cutoffInner: 35,
    cutoffOuter: 65,
    gravity: 0.01,
    springs: Object.freeze({
        broader: { rest: 20, k: 12, reach: 80 },
        related: { rest: 60, k: 0.5, reach: 60 },
        mapping: { rest: 110, k: 0.25, reach: 80 },
        semantic: { rest: 70, k: 0.15, reach: 60 },
    }),
    ring: Object.freeze({
        primaryScheme: "acat",
        k: 30,
        rootRepulsion: 150000,
        rootSoftening: 20,
        nodeArea: 700,
        gap: 0.6,
        outerClearance: 60,
        minRadius: 120,
        crossRootFactor: 0.2,
    }),
    dragOmega: 24,
    sleep: Object.freeze({ meanKE: 0.5, steps: 90 }),
    glow: Object.freeze({ tau: 0.9, floor: 0.01 }),
});
const TAU = Math.PI * 2;
/**
 * Pairwise repulsion kernel shared by Barnes-Hut and brute force: returns the scalar
 * f such that the force on i is f * (dx, dy), per unit (k qi) - i.e. qj / (r^2 + eps^2)
 * times a C1 switching function that fades it to zero between the cutoff radii.
 */
function kernel(qj, r2, eps2, r1sq, rcsq, invDen) {
    let f = qj / (r2 + eps2);
    if (r2 > r1sq) {
        const a = rcsq - r2;
        f *= a * a * (rcsq + 2 * r2 - 3 * r1sq) * invDen;
    }
    return f;
}
function cutoffTerms(p) {
    if (!Number.isFinite(p.cutoffOuter))
        return { r1sq: Infinity, rcsq: Infinity, invDen: 0 };
    const inner = Math.min(p.cutoffInner, p.cutoffOuter * 0.999);
    const r1sq = inner * inner;
    const rcsq = p.cutoffOuter * p.cutoffOuter;
    return { r1sq, rcsq, invDen: 1 / Math.pow(rcsq - r1sq, 3) };
}
/**
 * Deterministic, antisymmetric separation direction (length 1e-3) for exactly
 * coincident particles i and j: split(i, j) = -split(j, i).
 */
function splitAngle(i, j) {
    const lo = i < j ? i : j;
    const hi = i < j ? j : i;
    return ((lo * 0.6180339887 + hi * 0.4142135623) % 1) * TAU;
}
function splitX(i, j) {
    return (i < j ? -1e-3 : 1e-3) * Math.cos(splitAngle(i, j));
}
function splitY(i, j) {
    return (i < j ? -1e-3 : 1e-3) * Math.sin(splitAngle(i, j));
}
/**
 * Barnes-Hut repulsion: adds k qi sum_j qj (xi - xj) / (|xi - xj|^2 + eps^2), faded by
 * the smooth cutoff, to fx and fy.
 *
 * The tree is walked once per leaf (a group of up to `bucket` nearby particles) and the
 * walk yields two lists shared by the whole group: cells far enough to act as one
 * pseudo-particle at their charge center (cell side < theta x the distance from the
 * charge center to the group's bounding box, and the whole cell inside the cutoff for
 * every group member), and leaves whose particles interact directly. Cells entirely
 * beyond the cutoff are skipped.
 */
export function repulsionBarnesHut(tree, x, y, q, n, p, fx, fy) {
    tree.build(x, y, q, n);
    if (n === 0)
        return;
    const { r1sq, rcsq, invDen } = cutoffTerms(p);
    const finite = rcsq !== Infinity;
    const eps2 = p.eps2;
    const theta2 = p.theta * p.theta;
    const head = tree.head;
    const children = tree.children;
    const cx = tree.cx;
    const cy = tree.cy;
    const half = tree.half;
    const cq = tree.q;
    const cqx = tree.qx;
    const cqy = tree.qy;
    const start = tree.start;
    const size = tree.size;
    const bx0 = tree.bx0;
    const bx1 = tree.bx1;
    const by0 = tree.by0;
    const by1 = tree.by1;
    const perm = tree.perm;
    const px = tree.px;
    const py = tree.py;
    const pq = tree.pq;
    const stack = tree.stack;
    const near = tree.near;
    const far = tree.far;
    const leaves = tree.leaves;
    for (let l = 0; l < tree.leafCount; l++) {
        const leaf = leaves[l];
        const gx0 = bx0[leaf];
        const gx1 = bx1[leaf];
        const gy0 = by0[leaf];
        const gy1 = by1[leaf];
        let nNear = 0;
        let nFar = 0;
        let sp = 0;
        stack[sp++] = 0;
        while (sp > 0) {
            const node = stack[--sp];
            const hw = half[node];
            const nx0 = cx[node] - hw;
            const nx1 = cx[node] + hw;
            const ny0 = cy[node] - hw;
            const ny1 = cy[node] + hw;
            if (finite) {
                const dx = nx0 > gx1 ? nx0 - gx1 : gx0 > nx1 ? gx0 - nx1 : 0;
                const dy = ny0 > gy1 ? ny0 - gy1 : gy0 > ny1 ? gy0 - ny1 : 0;
                if (dx * dx + dy * dy >= rcsq)
                    continue;
            }
            const h = head[node];
            if (h >= 0) {
                near[nNear++] = node;
                continue;
            }
            if (h === LEAF_EMPTY)
                continue;
            const ccx = cqx[node];
            const ccy = cqy[node];
            const ex = ccx < gx0 ? gx0 - ccx : ccx > gx1 ? ccx - gx1 : 0;
            const ey = ccy < gy0 ? gy0 - ccy : ccy > gy1 ? ccy - gy1 : 0;
            const w = 2 * hw;
            if (w * w < theta2 * (ex * ex + ey * ey)) {
                let inside = true;
                if (finite) {
                    const fdx = Math.max(nx1 - gx0, gx1 - nx0);
                    const fdy = Math.max(ny1 - gy0, gy1 - ny0);
                    inside = fdx * fdx + fdy * fdy < rcsq;
                }
                if (inside) {
                    far[nFar++] = node;
                    continue;
                }
            }
            const c0 = node * 4;
            let c = children[c0];
            if (c >= 0)
                stack[sp++] = c;
            c = children[c0 + 1];
            if (c >= 0)
                stack[sp++] = c;
            c = children[c0 + 2];
            if (c >= 0)
                stack[sp++] = c;
            c = children[c0 + 3];
            if (c >= 0)
                stack[sp++] = c;
        }
        const s0 = start[leaf];
        const s1 = s0 + size[leaf];
        for (let a = s0; a < s1; a++) {
            const xi = px[a];
            const yi = py[a];
            let ax = 0;
            let ay = 0;
            for (let t = 0; t < nNear; t++) {
                const nb = near[t];
                const b0 = start[nb];
                const b1 = b0 + size[nb];
                for (let b = b0; b < b1; b++) {
                    if (b === a)
                        continue;
                    let dx = xi - px[b];
                    let dy = yi - py[b];
                    let r2 = dx * dx + dy * dy;
                    if (r2 >= rcsq)
                        continue;
                    if (r2 === 0) {
                        dx = splitX(perm[a], perm[b]);
                        dy = splitY(perm[a], perm[b]);
                        r2 = dx * dx + dy * dy;
                    }
                    let f = pq[b] / (r2 + eps2);
                    if (r2 > r1sq) {
                        const u = rcsq - r2;
                        f *= u * u * (rcsq + 2 * r2 - 3 * r1sq) * invDen;
                    }
                    ax += f * dx;
                    ay += f * dy;
                }
            }
            for (let t = 0; t < nFar; t++) {
                const c = far[t];
                const dx = xi - cqx[c];
                const dy = yi - cqy[c];
                const r2 = dx * dx + dy * dy;
                let f = cq[c] / (r2 + eps2);
                if (r2 > r1sq) {
                    const u = rcsq - r2;
                    f *= u * u * (rcsq + 2 * r2 - 3 * r1sq) * invDen;
                }
                ax += f * dx;
                ay += f * dy;
            }
            const i = perm[a];
            const sc = p.k * pq[a];
            fx[i] += sc * ax;
            fy[i] += sc * ay;
        }
    }
}
/** O(n^2) reference for the same force law (used by the tests). */
export function repulsionBrute(x, y, q, n, p, fx, fy) {
    const { r1sq, rcsq, invDen } = cutoffTerms(p);
    for (let i = 0; i < n; i++) {
        let ax = 0;
        let ay = 0;
        for (let j = 0; j < n; j++) {
            if (j === i)
                continue;
            let dx = x[i] - x[j];
            let dy = y[i] - y[j];
            let r2 = dx * dx + dy * dy;
            if (r2 >= rcsq)
                continue;
            if (r2 === 0) {
                dx = splitX(i, j);
                dy = splitY(i, j);
                r2 = dx * dx + dy * dy;
            }
            const f = kernel(q[j], r2, p.eps2, r1sq, rcsq, invDen);
            ax += f * dx;
            ay += f * dy;
        }
        fx[i] += p.k * q[i] * ax;
        fy[i] += p.k * q[i] * ay;
    }
}
export class Sim {
    cfg;
    n;
    ids;
    // Structure of arrays.
    x;
    y;
    vx;
    vy;
    fx;
    fy;
    mass;
    invMass;
    charge;
    /** Glow energy per particle, dE/dt = -E/tau. */
    energy;
    /** 1 while something holds a particle's glow up (e.g. hover): a constant source. */
    glowHold;
    depth;
    /** Depth-0 particles, id-sorted within their ring: inner ring first, then outer. */
    roots;
    /** Per node: slot in `roots` of the root it descends from (-1 if unknown). */
    rootSlot;
    /** Per root slot: ring radius target and ring (0 inner, 1 outer). */
    ringRadius;
    ringOf;
    /** Per root slot: charge in the root-root repulsion, proportional to its cluster's radius. */
    ringCharge;
    innerRadius;
    outerRadius;
    /** The scheme whose roots sit on the inner ring (the domains). */
    primaryScheme;
    /** Mass-weighted centroid of each root's cluster (per root slot), see updateCentroids(). */
    centroidX;
    centroidY;
    /** Mass-weighted RMS distance of each cluster's particles from its centroid. */
    clusterRadius;
    centroidMass;
    // Edges.
    m;
    es;
    et;
    ekind;
    erest;
    ek;
    /** Per edge: stretch beyond which tension is constant. */
    ereach;
    /** Edges dropped at construction (index out of range or a self loop). */
    droppedEdges;
    /** Semantic springs are optional (off by default). */
    semantic = false;
    // Integrator state.
    awake = true;
    /** Consecutive calm steps (mean KE below the sleep threshold). */
    calm = 0;
    kinetic = 0;
    peakKinetic = 0;
    stepCount = 0;
    accumulator = 0;
    /** Number of particles with glow energy above the floor. */
    glowing = 0;
    /** Running estimate of one dynamics step's wall time, ms (for the frame budget). */
    stepMs = 0;
    // Drag state.
    dragIndex = -1;
    dragX = 0;
    dragY = 0;
    tree = new QuadTree();
    repulsionParams;
    constructor(graph, cfg = PHYSICS) {
        this.cfg = cfg;
        const nodes = graph.nodes;
        const n = nodes.length;
        this.n = n;
        this.ids = nodes.map((d) => d.id);
        this.x = new Float64Array(n);
        this.y = new Float64Array(n);
        this.vx = new Float64Array(n);
        this.vy = new Float64Array(n);
        this.fx = new Float64Array(n);
        this.fy = new Float64Array(n);
        this.mass = new Float64Array(n);
        this.invMass = new Float64Array(n);
        this.charge = new Float64Array(n);
        this.energy = new Float64Array(n);
        this.glowHold = new Uint8Array(n);
        this.depth = new Int32Array(n);
        for (let i = 0; i < n; i++) {
            const d = nodes[i];
            const m = Number.isFinite(d.mass) && d.mass >= 1 ? d.mass : 1;
            this.mass[i] = m;
            this.invMass[i] = 1 / m;
            this.charge[i] = Math.sqrt(m);
            this.depth[i] = Number.isFinite(d.depth) && d.depth >= 0 ? Math.floor(d.depth) : 0;
        }
        this.repulsionParams = {
            k: cfg.repulsion,
            eps2: cfg.softening * cfg.softening,
            theta: cfg.theta,
            cutoffInner: cfg.cutoffInner,
            cutoffOuter: cfg.cutoffOuter,
        };
        // Edges.
        const keep = [];
        for (const e of graph.edges) {
            if (Number.isInteger(e.s) && Number.isInteger(e.t) && e.s >= 0 && e.t >= 0 && e.s < n && e.t < n && e.s !== e.t && e.k in KIND_CODE) {
                keep.push(e);
            }
        }
        this.droppedEdges = graph.edges.length - keep.length;
        const m = keep.length;
        this.m = m;
        this.es = new Int32Array(m);
        this.et = new Int32Array(m);
        this.ekind = new Uint8Array(m);
        this.erest = new Float64Array(m);
        this.ek = new Float64Array(m);
        this.ereach = new Float64Array(m);
        // A node with several parents splits its attachment between them.
        const parents = new Int32Array(n);
        for (const d of keep)
            if (d.k === "broader")
                parents[d.s]++;
        for (let e = 0; e < m; e++) {
            const d = keep[e];
            const spec = cfg.springs[d.k];
            const w = Number.isFinite(d.w) && d.w > 0 ? Math.min(d.w, 1) : 1;
            this.es[e] = d.s;
            this.et[e] = d.t;
            this.ekind[e] = KIND_CODE[d.k];
            this.erest[e] = spec.rest;
            this.ek[e] = (spec.k * w) / (d.k === "broader" ? Math.max(1, parents[d.s]) : 1);
            this.ereach[e] = spec.reach;
        }
        // Roots and rings.
        const index = new Map();
        for (let i = 0; i < n; i++)
            if (!index.has(this.ids[i]))
                index.set(this.ids[i], i);
        const schemeCount = new Map();
        for (const d of nodes)
            schemeCount.set(d.scheme, (schemeCount.get(d.scheme) ?? 0) + 1);
        let primary = cfg.ring.primaryScheme;
        if (!schemeCount.has(primary)) {
            let best = -1;
            for (const [s, c] of schemeCount)
                if (c > best || (c === best && s < primary))
                    [primary, best] = [s, c];
        }
        const byId = (a, b) => (this.ids[a] < this.ids[b] ? -1 : this.ids[a] > this.ids[b] ? 1 : a - b);
        const inner = [];
        const outer = [];
        for (let i = 0; i < n; i++) {
            if (this.depth[i] !== 0)
                continue;
            (nodes[i].scheme === primary ? inner : outer).push(i);
        }
        inner.sort(byId);
        outer.sort(byId);
        this.primaryScheme = primary;
        const roots = [...inner, ...outer];
        this.roots = Int32Array.from(roots);
        const slotOfNode = new Map();
        roots.forEach((r, s) => slotOfNode.set(r, s));
        this.rootSlot = new Int32Array(n).fill(-1);
        const clusterSize = new Float64Array(roots.length);
        for (let i = 0; i < n; i++) {
            const r = index.get(nodes[i].root);
            const slot = r === undefined ? undefined : slotOfNode.get(r);
            if (slot !== undefined) {
                this.rootSlot[i] = slot;
                clusterSize[slot] += 1;
            }
            else if (slotOfNode.has(i)) {
                this.rootSlot[i] = slotOfNode.get(i);
                clusterSize[slotOfNode.get(i)] += 1;
            }
        }
        const blob = (slot) => Math.sqrt((Math.max(1, clusterSize[slot]) * cfg.ring.nodeArea) / Math.PI);
        let sumInner = 0;
        let maxInner = 0;
        for (let s = 0; s < inner.length; s++) {
            sumInner += 2 * blob(s);
            maxInner = Math.max(maxInner, blob(s));
        }
        let sumOuter = 0;
        let maxOuter = 0;
        for (let s = inner.length; s < roots.length; s++) {
            sumOuter += 2 * blob(s);
            maxOuter = Math.max(maxOuter, blob(s));
        }
        const innerRadius = inner.length <= 1 ? 0 : Math.max(cfg.ring.minRadius, ((1 + cfg.ring.gap) * sumInner) / TAU);
        const outerRadius = outer.length === 0
            ? 0
            : Math.max(innerRadius + maxInner + maxOuter + cfg.ring.outerClearance, ((1 + cfg.ring.gap) * sumOuter) / TAU);
        this.innerRadius = innerRadius;
        this.outerRadius = outerRadius;
        this.ringRadius = new Float64Array(roots.length);
        this.ringOf = new Uint8Array(roots.length);
        this.ringCharge = new Float64Array(roots.length);
        let meanBlob = 0;
        for (let s = 0; s < roots.length; s++)
            meanBlob += blob(s) / roots.length;
        for (let s = 0; s < roots.length; s++) {
            const isInner = s < inner.length;
            this.ringRadius[s] = isInner ? innerRadius : outerRadius;
            this.ringOf[s] = isInner ? 0 : 1;
            // Bigger clusters claim more of the circle.
            this.ringCharge[s] = blob(s) / (meanBlob || 1);
        }
        this.centroidX = new Float64Array(roots.length);
        this.centroidY = new Float64Array(roots.length);
        this.clusterRadius = new Float64Array(roots.length);
        this.centroidMass = new Float64Array(roots.length);
        // Edges between different roots' clusters are weaker (see crossRootFactor).
        for (let e = 0; e < m; e++) {
            const a = this.rootSlot[this.es[e]];
            const b = this.rootSlot[this.et[e]];
            if (a !== b)
                this.ek[e] *= cfg.ring.crossRootFactor;
        }
        this.place(inner, outer);
        this.updateCentroids();
    }
    /**
     * Deterministic initial placement. Roots sit at equal angles on their ring in id
     * order; each root's tree is laid out radially around it (every subtree gets an
     * angular wedge proportional to its size), so the simulation starts near a calm
     * state instead of exploding. Nodes with no path to a root get a seeded scatter.
     */
    place(inner, outer) {
        const n = this.n;
        const placed = new Uint8Array(n);
        const putRing = (list, radius) => {
            list.forEach((r, k) => {
                const a = -Math.PI / 2 + (TAU * (k + 0.5)) / list.length;
                this.x[r] = radius * Math.cos(a);
                this.y[r] = radius * Math.sin(a);
                placed[r] = 1;
            });
        };
        putRing(inner, this.innerRadius);
        putRing(outer, this.outerRadius);
        // Primary parent: the broader target with the smallest depth, then the smallest id.
        const parent = new Int32Array(n).fill(-1);
        for (let e = 0; e < this.m; e++) {
            if (this.ekind[e] !== KIND_BROADER)
                continue;
            const s = this.es[e];
            const t = this.et[e];
            const p = parent[s];
            if (p === -1 || this.depth[t] < this.depth[p] || (this.depth[t] === this.depth[p] && this.ids[t] < this.ids[p]))
                parent[s] = t;
        }
        for (let s = 0; s < this.roots.length; s++)
            parent[this.roots[s]] = -1;
        const kids = Array.from({ length: n }, () => []);
        for (let i = 0; i < n; i++)
            if (parent[i] >= 0)
                kids[parent[i]].push(i);
        for (const list of kids)
            list.sort((a, b) => (this.ids[a] < this.ids[b] ? -1 : 1));
        // Subtree sizes by an explicit post-order walk from the roots (cycle-safe: only
        // nodes reached from a root are counted, each once).
        const size = new Float64Array(n);
        const seen = new Uint8Array(n);
        const post = [];
        for (let s = 0; s < this.roots.length; s++) {
            const stack = [this.roots[s]];
            seen[this.roots[s]] = 1;
            while (stack.length > 0) {
                const v = stack.pop();
                post.push(v);
                for (const c of kids[v]) {
                    if (seen[c])
                        continue;
                    seen[c] = 1;
                    stack.push(c);
                }
            }
        }
        for (let k = post.length - 1; k >= 0; k--) {
            const v = post[k];
            size[v] += 1;
            if (parent[v] >= 0 && seen[parent[v]])
                size[parent[v]] += size[v];
        }
        // Level radii: at least one spring length apart, and wide enough that the disk up
        // to each level holds its nodes at a packed density (big trees start spread out).
        const step = this.cfg.springs.broader.rest * 1.15;
        const packedArea = this.cfg.ring.nodeArea * 0.6;
        for (let s = 0; s < this.roots.length; s++) {
            const r = this.roots[s];
            const levels = [[r]];
            for (let L = 0; L < levels.length && L < 64; L++) {
                const nextLevel = [];
                for (const v of levels[L])
                    for (const c of kids[v])
                        if (!placed[c] && seen[c])
                            nextLevel.push(c);
                if (nextLevel.length > 0)
                    levels.push(nextLevel);
            }
            const radius = [0];
            let cumulative = 1;
            for (let L = 1; L < levels.length; L++) {
                cumulative += levels[L].length;
                radius.push(Math.max(radius[L - 1] + step, Math.sqrt((cumulative * packedArea) / Math.PI)));
            }
            const phase = rngFor(this.ids[r], 7)() * TAU;
            // Breadth-first: each entry is a node with its wedge [a0, a0 + span) and level.
            const queue = [[r, phase, TAU, 0]];
            for (let q = 0; q < queue.length; q++) {
                const [v, a0, span, level] = queue[q];
                const list = kids[v].filter((c) => !placed[c]);
                let total = 0;
                for (const c of list)
                    total += size[c] > 0 ? size[c] : 1;
                let a = a0;
                for (const c of list) {
                    const share = (span * (size[c] > 0 ? size[c] : 1)) / total;
                    const mid = a + share / 2;
                    const rand = rngFor(this.ids[c]);
                    const rr = (radius[level + 1] ?? radius[radius.length - 1] + step) * (0.95 + 0.1 * rand());
                    const jitter = (rand() - 0.5) * Math.min(share, 0.2) * 0.5;
                    this.x[c] = this.x[r] + rr * Math.cos(mid + jitter);
                    this.y[c] = this.y[r] + rr * Math.sin(mid + jitter);
                    placed[c] = 1;
                    queue.push([c, a, share, level + 1]);
                    a += share;
                }
            }
        }
        // Anything not reached from a root: near its declared root if placed, else scattered.
        const spread = Math.max(this.outerRadius, this.innerRadius, 200);
        for (let i = 0; i < n; i++) {
            if (placed[i])
                continue;
            const rand = rngFor(this.ids[i]);
            const slot = this.rootSlot[i];
            const r = slot >= 0 ? this.roots[slot] : -1;
            const a = rand() * TAU;
            if (r >= 0 && placed[r]) {
                const d = step * (1 + 2 * rand());
                this.x[i] = this.x[r] + d * Math.cos(a);
                this.y[i] = this.y[r] + d * Math.sin(a);
            }
            else {
                const d = spread * Math.sqrt(rand());
                this.x[i] = d * Math.cos(a);
                this.y[i] = d * Math.sin(a);
            }
            placed[i] = 1;
        }
    }
    /** Recompute the mass-weighted centroid of each root's cluster. */
    updateCentroids() {
        const R = this.roots.length;
        const sx = this.centroidX;
        const sy = this.centroidY;
        const sm = this.centroidMass;
        const rr = this.clusterRadius;
        sx.fill(0);
        sy.fill(0);
        sm.fill(0);
        rr.fill(0);
        for (let i = 0; i < this.n; i++) {
            const s = this.rootSlot[i];
            if (s < 0)
                continue;
            const m = this.mass[i];
            sx[s] += m * this.x[i];
            sy[s] += m * this.y[i];
            sm[s] += m;
        }
        for (let s = 0; s < R; s++) {
            if (sm[s] > 0) {
                sx[s] /= sm[s];
                sy[s] /= sm[s];
            }
            else {
                const r = this.roots[s];
                sx[s] = this.x[r];
                sy[s] = this.y[r];
            }
        }
        for (let i = 0; i < this.n; i++) {
            const s = this.rootSlot[i];
            if (s < 0)
                continue;
            const dx = this.x[i] - sx[s];
            const dy = this.y[i] - sy[s];
            rr[s] += this.mass[i] * (dx * dx + dy * dy);
        }
        for (let s = 0; s < R; s++)
            rr[s] = sm[s] > 0 ? Math.sqrt(rr[s] / sm[s]) : 0;
    }
    wake() {
        this.awake = true;
        this.calm = 0;
    }
    sleep() {
        this.awake = false;
        this.calm = 0;
        this.vx.fill(0);
        this.vy.fill(0);
        this.kinetic = 0;
    }
    /** Put the simulation to sleep now (reduced motion: freeze after pre-settling). */
    freeze() {
        this.sleep();
    }
    setSemantic(on) {
        if (this.semantic !== on) {
            this.semantic = on;
            this.wake();
        }
    }
    /** Attach particle i to the pointer (world coordinates) with a stiff spring. */
    grab(i, wx, wy) {
        if (i < 0 || i >= this.n)
            return;
        this.dragIndex = i;
        this.dragX = wx;
        this.dragY = wy;
        this.wake();
    }
    moveGrab(wx, wy) {
        this.dragX = wx;
        this.dragY = wy;
        if (this.dragIndex >= 0)
            this.wake();
    }
    release() {
        this.dragIndex = -1;
    }
    /** Inject glow energy (an impulse): E = max(E, amount). */
    excite(i, amount = 1) {
        if (i < 0 || i >= this.n)
            return;
        if (this.energy[i] < amount) {
            if (this.energy[i] < this.cfg.glow.floor)
                this.glowing++;
            this.energy[i] = amount;
        }
    }
    /** Hold (or stop holding) a particle's glow at 1: a constant source while held. */
    hold(i, on) {
        if (i < 0 || i >= this.n)
            return;
        this.glowHold[i] = on ? 1 : 0;
        if (on)
            this.excite(i, 1);
    }
    clearGlow() {
        this.energy.fill(0);
        this.glowHold.fill(0);
        this.glowing = 0;
    }
    /** One fixed step of the dynamics (forces + semi-implicit Euler). Always integrates. */
    step() {
        const n = this.n;
        const cfg = this.cfg;
        const { x, y, vx, vy, fx, fy } = this;
        fx.fill(0);
        fy.fill(0);
        // (a) Barnes-Hut repulsion.
        repulsionBarnesHut(this.tree, x, y, this.charge, n, this.repulsionParams, fx, fy);
        // (d) Stronger mutual repulsion between roots on the same ring.
        const roots = this.roots;
        const R = roots.length;
        const krr = cfg.ring.rootRepulsion;
        const rs2 = cfg.ring.rootSoftening * cfg.ring.rootSoftening;
        for (let a = 0; a < R; a++) {
            const i = roots[a];
            for (let b = a + 1; b < R; b++) {
                if (this.ringOf[a] !== this.ringOf[b])
                    continue;
                const j = roots[b];
                let dx = x[i] - x[j];
                let dy = y[i] - y[j];
                let r2 = dx * dx + dy * dy;
                if (r2 === 0) {
                    dx = splitX(i, j);
                    dy = splitY(i, j);
                    r2 = dx * dx + dy * dy;
                }
                const f = (krr * this.ringCharge[a] * this.ringCharge[b]) / (r2 + rs2);
                fx[i] += f * dx;
                fy[i] += f * dy;
                fx[j] -= f * dx;
                fy[j] -= f * dy;
            }
        }
        // (b) Hooke springs.
        const es = this.es;
        const et = this.et;
        const ekind = this.ekind;
        const erest = this.erest;
        const ek = this.ek;
        const ereach = this.ereach;
        const semantic = this.semantic;
        for (let e = 0; e < this.m; e++) {
            if (ekind[e] === KIND_SEMANTIC && !semantic)
                continue;
            const s = es[e];
            const t = et[e];
            let dx = x[t] - x[s];
            let dy = y[t] - y[s];
            let r = Math.sqrt(dx * dx + dy * dy);
            if (r < 1e-9) {
                dx = splitX(t, s);
                dy = splitY(t, s);
                r = Math.sqrt(dx * dx + dy * dy);
            }
            let stretch = r - erest[e];
            if (stretch > ereach[e])
                stretch = ereach[e];
            const f = (ek[e] * stretch) / r;
            fx[s] += f * dx;
            fy[s] += f * dy;
            fx[t] -= f * dx;
            fy[t] -= f * dy;
        }
        // (d) Radial ring spring on roots, (c) weak centering gravity on everyone.
        const g = cfg.gravity;
        for (let i = 0; i < n; i++) {
            const m = this.mass[i];
            fx[i] -= g * m * x[i];
            fy[i] -= g * m * y[i];
        }
        const kr = cfg.ring.k;
        for (let s = 0; s < R; s++) {
            const i = roots[s];
            const target = this.ringRadius[s];
            const r = Math.hypot(x[i], y[i]);
            const m = this.mass[i];
            if (r > 1e-9) {
                const f = (-kr * m * (r - target)) / r;
                fx[i] += f * x[i];
                fy[i] += f * y[i];
            }
            else if (target > 0) {
                const a = -Math.PI / 2 + (TAU * (s + 0.5)) / R;
                fx[i] += kr * m * target * Math.cos(a);
                fy[i] += kr * m * target * Math.sin(a);
            }
        }
        // Drag: a stiff, critically damped spring from the grabbed particle to the pointer.
        const d = this.dragIndex;
        if (d >= 0) {
            const m = this.mass[d];
            const w = cfg.dragOmega;
            fx[d] += m * (w * w * (this.dragX - x[d]) - 2 * w * vx[d]);
            fy[d] += m * (w * w * (this.dragY - y[d]) - 2 * w * vy[d]);
        }
        // Semi-implicit Euler: v += a dt; v *= exp(-gamma dt); clamp |v|; x += v dt.
        const dt = cfg.dt;
        const damp = Math.exp(-cfg.damping * dt);
        const vmax = cfg.maxSpeed;
        const vmax2 = vmax * vmax;
        let ke = 0;
        for (let i = 0; i < n; i++) {
            const im = this.invMass[i];
            let vxi = (vx[i] + fx[i] * im * dt) * damp;
            let vyi = (vy[i] + fy[i] * im * dt) * damp;
            if (!(vxi === vxi) || !(vyi === vyi)) {
                vxi = 0;
                vyi = 0;
            }
            let s2 = vxi * vxi + vyi * vyi;
            if (s2 > vmax2) {
                const c = vmax / Math.sqrt(s2);
                vxi *= c;
                vyi *= c;
                s2 = vmax2;
            }
            vx[i] = vxi;
            vy[i] = vyi;
            x[i] += vxi * dt;
            y[i] += vyi * dt;
            ke += 0.5 * this.mass[i] * s2;
        }
        this.kinetic = ke;
        if (ke > this.peakKinetic)
            this.peakKinetic = ke;
        this.stepCount++;
        // Sleep after a sustained calm; never while a particle is held.
        if (d < 0 && n > 0 && ke / n < cfg.sleep.meanKE) {
            if (++this.calm >= cfg.sleep.steps)
                this.sleep();
        }
        else {
            this.calm = 0;
        }
    }
    /** Glow decay for one fixed step: E *= exp(-dt / tau) (exact for dE/dt = -E/tau). */
    stepGlow() {
        if (this.glowing === 0)
            return;
        const decay = Math.exp(-this.cfg.dt / this.cfg.glow.tau);
        const floor = this.cfg.glow.floor;
        const E = this.energy;
        let active = 0;
        for (let i = 0; i < this.n; i++) {
            let e = E[i];
            if (e === 0)
                continue;
            e = this.glowHold[i] ? 1 : e * decay;
            if (e < floor)
                e = 0;
            else
                active++;
            E[i] = e;
        }
        this.glowing = active;
    }
    /**
     * Feed one frame's wall time into the fixed-step accumulator and run the steps it
     * pays for. The frame time is clamped, and the backlog is dropped (the simulation
     * then runs slower than the wall clock) when the step count or the time budget runs
     * out, so a slow frame cannot snowball into slower ones: no spiral of death.
     */
    advance(frameSeconds) {
        const cfg = this.cfg;
        const dt = cfg.dt;
        this.accumulator += Math.min(Math.max(frameSeconds, 0), cfg.maxFrameSeconds);
        let steps = 0;
        let moved = false;
        let clamped = false;
        const t0 = performance.now();
        while (this.accumulator >= dt) {
            if (steps > 0) {
                const nextCost = this.awake ? this.stepMs : 0;
                if (steps >= cfg.maxStepsPerFrame || performance.now() - t0 + nextCost > cfg.frameBudgetMs) {
                    this.accumulator = 0;
                    clamped = true;
                    break;
                }
            }
            if (this.awake) {
                const ts = performance.now();
                this.step();
                this.stepMs = this.stepMs * 0.8 + (performance.now() - ts) * 0.2;
                moved = true;
            }
            this.stepGlow();
            this.accumulator -= dt;
            steps++;
        }
        return { steps, moved, clamped };
    }
    /** Step until asleep or `maxSteps` (used to pre-settle under reduced motion). */
    settle(maxSteps) {
        let k = 0;
        while (this.awake && k < maxSteps) {
            this.step();
            k++;
        }
        return k;
    }
    meanKinetic() {
        return this.n > 0 ? this.kinetic / this.n : 0;
    }
}
//# sourceMappingURL=physics.js.map