// Barnes-Hut quadtree over point charges, stored as flat typed arrays (no per-node
// objects, no garbage per step). Rebuilt every physics step.
//
// Node layout:
//   head[n]  >= 0 : leaf; first particle of its linked list (next[]), `size[n]` long
//            = -1 : empty leaf (only an empty tree has one)
//            = -2 : internal node; children[4n..4n+3] hold child node ids (-1 = none)
//   cx, cy, half : the cell square (center, half side)
//   q            : total charge in the cell
//   qx, qy       : charge-weighted center of the cell
// Leaves hold up to `bucket` particles. After a build, the particles are also laid out
// contiguously leaf by leaf (perm, px, py, pq; a leaf owns [start, start + size)), and
// every leaf carries the tight bounding box of its particles (bx0..by1). The force pass
// walks the tree once per leaf (a group), not once per particle.
export const LEAF_EMPTY = -1;
export const INTERNAL = -2;
export class QuadTree {
    /** Nodes in use after the last build. */
    count = 0;
    /** Particles in the last build. */
    n = 0;
    /** Deepest subdivision; below it, particles share a leaf. */
    maxDepth;
    /** Particles a leaf holds before it splits. */
    bucket;
    children = new Int32Array(0);
    head = new Int32Array(0);
    depth = new Uint8Array(0);
    size = new Int32Array(0);
    start = new Int32Array(0);
    cx = new Float64Array(0);
    cy = new Float64Array(0);
    half = new Float64Array(0);
    q = new Float64Array(0);
    qx = new Float64Array(0);
    qy = new Float64Array(0);
    bx0 = new Float64Array(0);
    bx1 = new Float64Array(0);
    by0 = new Float64Array(0);
    by1 = new Float64Array(0);
    /** Per particle: next particle in the same leaf, or -1. */
    next = new Int32Array(0);
    /** Particle ids in leaf order, and their positions and charges in that order. */
    perm = new Int32Array(0);
    px = new Float64Array(0);
    py = new Float64Array(0);
    pq = new Float64Array(0);
    /** Non-empty leaves, in depth-first order. */
    leaves = new Int32Array(0);
    leafCount = 0;
    /** Scratch stack for traversals (depth-first: at most 3 * maxDepth + 4 entries). */
    stack;
    /** Scratch interaction lists for the force pass (sized to the node capacity). */
    near = new Int32Array(0);
    far = new Int32Array(0);
    capacity = 0;
    constructor(maxDepth = 30, bucket = 12) {
        this.maxDepth = maxDepth;
        this.bucket = Math.max(1, bucket);
        this.stack = new Int32Array(4 * (maxDepth + 2));
    }
    grow(min) {
        const cap = Math.max(min, Math.ceil(this.capacity * 1.6), 64);
        const i32 = (a, len) => {
            const b = new Int32Array(len);
            b.set(a.subarray(0, Math.min(a.length, len)));
            return b;
        };
        const f64 = (a) => {
            const b = new Float64Array(cap);
            b.set(a.subarray(0, Math.min(a.length, cap)));
            return b;
        };
        this.children = i32(this.children, cap * 4);
        this.head = i32(this.head, cap);
        this.size = i32(this.size, cap);
        this.start = i32(this.start, cap);
        const d = new Uint8Array(cap);
        d.set(this.depth.subarray(0, Math.min(this.depth.length, cap)));
        this.depth = d;
        this.cx = f64(this.cx);
        this.cy = f64(this.cy);
        this.half = f64(this.half);
        this.q = f64(this.q);
        this.qx = f64(this.qx);
        this.qy = f64(this.qy);
        this.bx0 = f64(this.bx0);
        this.bx1 = f64(this.bx1);
        this.by0 = f64(this.by0);
        this.by1 = f64(this.by1);
        this.near = new Int32Array(cap);
        this.far = new Int32Array(cap);
        this.capacity = cap;
    }
    alloc(cx, cy, half, depth) {
        if (this.count >= this.capacity)
            this.grow(this.count + 1);
        const n = this.count++;
        const c = n * 4;
        this.children[c] = -1;
        this.children[c + 1] = -1;
        this.children[c + 2] = -1;
        this.children[c + 3] = -1;
        this.head[n] = LEAF_EMPTY;
        this.size[n] = 0;
        this.start[n] = 0;
        this.depth[n] = depth;
        this.cx[n] = cx;
        this.cy[n] = cy;
        this.half[n] = half;
        this.q[n] = 0;
        this.qx[n] = cx;
        this.qy[n] = cy;
        return n;
    }
    /** Allocate the child in quadrant `quad` (bit 0: +x, bit 1: +y) of `node`. */
    child(node, quad) {
        const h = this.half[node] * 0.5;
        const cx = this.cx[node] + (quad & 1 ? h : -h);
        const cy = this.cy[node] + (quad & 2 ? h : -h);
        const c = this.alloc(cx, cy, h, this.depth[node] + 1);
        this.children[node * 4 + quad] = c;
        return c;
    }
    build(x, y, charge, n) {
        this.count = 0;
        this.n = n;
        if (this.next.length < n) {
            const len = Math.max(n, 16);
            this.next = new Int32Array(len);
            this.perm = new Int32Array(len);
            this.px = new Float64Array(len);
            this.py = new Float64Array(len);
            this.pq = new Float64Array(len);
            this.leaves = new Int32Array(len);
        }
        if (this.capacity < 2 * n + 8)
            this.grow(2 * n + 8);
        let minX = Infinity;
        let minY = Infinity;
        let maxX = -Infinity;
        let maxY = -Infinity;
        for (let i = 0; i < n; i++) {
            const xi = x[i];
            const yi = y[i];
            if (xi < minX)
                minX = xi;
            if (xi > maxX)
                maxX = xi;
            if (yi < minY)
                minY = yi;
            if (yi > maxY)
                maxY = yi;
        }
        if (!(maxX >= minX) || !(maxY >= minY)) {
            minX = minY = -1;
            maxX = maxY = 1;
        }
        const span = Math.max(maxX - minX, maxY - minY, 1e-6);
        this.alloc((minX + maxX) * 0.5, (minY + maxY) * 0.5, span * 0.5 * (1 + 1e-9) + 1e-9, 0);
        const next = this.next;
        const bucket = this.bucket;
        for (let i = 0; i < n; i++) {
            const xi = x[i];
            const yi = y[i];
            let node = 0;
            for (;;) {
                if (this.head[node] === INTERNAL) {
                    const quad = (xi >= this.cx[node] ? 1 : 0) | (yi >= this.cy[node] ? 2 : 0);
                    let c = this.children[node * 4 + quad];
                    if (c === -1)
                        c = this.child(node, quad);
                    node = c;
                    continue;
                }
                // Leaf: take the particle while there is room, at the depth limit, or when every
                // particle here sits on exactly the same point (no split could separate them).
                const h = this.head[node];
                let fits = this.size[node] < bucket || this.depth[node] >= this.maxDepth;
                if (!fits) {
                    fits = true;
                    for (let j = h; j !== -1; j = next[j]) {
                        if (x[j] !== xi || y[j] !== yi) {
                            fits = false;
                            break;
                        }
                    }
                }
                if (fits) {
                    next[i] = h;
                    this.head[node] = i;
                    this.size[node]++;
                    break;
                }
                // Split: move the leaf's particles one level down, then retry from this node.
                this.head[node] = INTERNAL;
                this.size[node] = 0;
                for (let j = h; j !== -1;) {
                    const after = next[j];
                    const quad = (x[j] >= this.cx[node] ? 1 : 0) | (y[j] >= this.cy[node] ? 2 : 0);
                    let c = this.children[node * 4 + quad];
                    if (c === -1)
                        c = this.child(node, quad);
                    next[j] = this.head[c];
                    this.head[c] = j;
                    this.size[c]++;
                    j = after;
                }
            }
        }
        // Depth-first layout: leaves in order, each leaf's particles contiguous, with the
        // tight bounding box of every leaf.
        const perm = this.perm;
        const px = this.px;
        const py = this.py;
        const pq = this.pq;
        const stack = this.stack;
        let k = 0;
        let leafCount = 0;
        let sp = 0;
        if (n > 0)
            stack[sp++] = 0;
        while (sp > 0) {
            const node = stack[--sp];
            const h = this.head[node];
            if (h === INTERNAL) {
                const c0 = node * 4;
                for (let c = 3; c >= 0; c--) {
                    const ch = this.children[c0 + c];
                    if (ch >= 0)
                        stack[sp++] = ch;
                }
                continue;
            }
            if (h < 0)
                continue;
            this.start[node] = k;
            let x0 = Infinity;
            let x1 = -Infinity;
            let y0 = Infinity;
            let y1 = -Infinity;
            for (let j = h; j !== -1; j = next[j]) {
                const xj = x[j];
                const yj = y[j];
                perm[k] = j;
                px[k] = xj;
                py[k] = yj;
                pq[k] = charge[j];
                k++;
                if (xj < x0)
                    x0 = xj;
                if (xj > x1)
                    x1 = xj;
                if (yj < y0)
                    y0 = yj;
                if (yj > y1)
                    y1 = yj;
            }
            this.bx0[node] = x0;
            this.bx1[node] = x1;
            this.by0[node] = y0;
            this.by1[node] = y1;
            this.leaves[leafCount++] = node;
        }
        this.leafCount = leafCount;
        // Aggregate charge and charge-weighted centers, children before parents.
        const q = this.q;
        const qx = this.qx;
        const qy = this.qy;
        for (let node = this.count - 1; node >= 0; node--) {
            const h = this.head[node];
            let sq = 0;
            let sx = 0;
            let sy = 0;
            if (h === INTERNAL) {
                const c0 = node * 4;
                for (let c = 0; c < 4; c++) {
                    const ch = this.children[c0 + c];
                    if (ch < 0)
                        continue;
                    const qc = q[ch];
                    sq += qc;
                    sx += qc * qx[ch];
                    sy += qc * qy[ch];
                }
            }
            else if (h >= 0) {
                const s = this.start[node];
                const e = s + this.size[node];
                for (let m = s; m < e; m++) {
                    const qm = pq[m];
                    sq += qm;
                    sx += qm * px[m];
                    sy += qm * py[m];
                }
            }
            q[node] = sq;
            if (sq > 0) {
                qx[node] = sx / sq;
                qy[node] = sy / sq;
            }
            else {
                qx[node] = this.cx[node];
                qy[node] = this.cy[node];
            }
        }
    }
}
//# sourceMappingURL=quadtree.js.map