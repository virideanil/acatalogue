// Canvas 2D renderer for the field.
//
// Encoding (see README): domains are not colour-coded; a domain is its spatial cluster
// plus a direct label at the cluster's mass-weighted centroid. Particles are neutral
// ink (alpha falls gently with depth, radius ~ sqrt(mass)); edges are solid hairlines.
// Colour is reserved for emphasis (accent: search hits and hover; accent-2: the one
// selected node, which always carries a visible label) and for the coverage lens
// (one sequential hue on log(langs); langs == null is a hollow ring).
//
// Particles are batched by style into one path per style; labels are placed greedily
// in a screen-space collision grid so they never overlap.
import { KIND_BROADER, KIND_SEMANTIC } from "./physics.js";
import { RectGrid } from "./grid.js";
export const RENDER = Object.freeze({
    /** Particle radius: radiusBase * sqrt(mass) * zoom^radiusZoomExponent (roots x rootFactor). */
    radiusBase: 2.4,
    /** Marks grow slower than the world when zooming (map-symbol scaling), so the overview stays legible. */
    radiusZoomExponent: 0.6,
    rootFactor: 1.45,
    minScreenRadius: 1.3,
    maxScreenRadius: 15,
    /** Emphasised marks never shrink below these (screen px). */
    hitMinRadius: 3,
    selectedMinRadius: 3.5,
    /** Alpha by depth 0, 1, 2, 3+. */
    depthAlpha: [1, 0.84, 0.7, 0.58],
    /** "Highlight one, gray the rest": everything outside the selection's neighbourhood. */
    selectionMuted: 0.25,
    /** Non-hits while a search is active. */
    searchMuted: 0.4,
    edgeAlpha: { broader: 0.16, related: 0.08, mapping: 0.08, semantic: 0.07 },
    /** Edges touching the selected node. */
    edgeAlphaIncident: 0.55,
    hairline: 1,
    /** Domain label sizes, tried largest first until no two domain labels overlap. */
    rootFontSizes: [13, 12, 11, 10],
    labelFontSize: 11.5,
    selectedFontSize: 12.5,
    /** A non-domain label is considered once its particle's screen radius reaches this. */
    labelMinRadius: 3.4,
    maxLabels: 140,
    maxLabelChars: 42,
    halo: 3.5,
    glowAlpha: 0.32,
    glowGrow: 11,
    ringGap: 2,
    ringWidth: 2,
    /** Surface-coloured outline around emphasised marks (the 2px surface ring). */
    surfaceRing: 1.5,
    /** Marks smaller than this radius in device pixels are drawn as area-matched squares (raster cost). */
    squareBelowRadius: 1.75,
});
// Style keys: layer * 256 + colour * 16 + alpha level.
const C_INK = 0;
const C_ACCENT = 1;
const C_ACCENT2 = 2;
const C_HOLLOW = 3;
const C_RAMP = 4; // ramp step k -> C_RAMP + k (up to 12 steps)
const A_FULL = 12;
const A_SEL_MUTED = 13;
const A_SEARCH_MUTED = 14;
const LAYERS = 4;
const KEYS = LAYERS * 256;
// Label fonts.
const F_ROOT = 0;
const F_LABEL = 1;
const F_SELECTED = 2;
const F_OTHER_ROOT = 3;
export class Renderer {
    canvas;
    ctx;
    theme;
    width = 1;
    height = 1;
    dpr = 1;
    n;
    /** Screen position and radius of every particle from the last draw (CSS px). */
    sx;
    sy;
    sr;
    vis;
    nodes;
    radiusW;
    covBin;
    langsMin;
    langsMax;
    langsKnown;
    labelText;
    /** Label widths at the label font and at the 13 px domain font (scaled for other sizes). */
    labelW;
    rootW;
    massOrder;
    primaryRootSlot;
    keys;
    counts;
    order;
    grid = new RectGrid();
    trial = new RectGrid();
    /** Domain label size chosen by the last draw. */
    rootSize = 13;
    /** World-to-screen transform of the last draw: screen = world * s + (ox, oy). */
    s = 1;
    ox = 0;
    oy = 0;
    /** Diagnostics from the last draw. */
    stats = { particles: 0, edges: 0, labels: 0, rootLabelSize: 13, rootOverlaps: 0, ms: 0 };
    constructor(canvas, nodes, sim, theme, primaryScheme) {
        this.canvas = canvas;
        const ctx = canvas.getContext("2d", { alpha: false });
        if (!ctx)
            throw new Error("Canvas 2D is not available");
        this.ctx = ctx;
        this.theme = theme;
        this.nodes = nodes;
        const n = nodes.length;
        this.n = n;
        this.sx = new Float32Array(n);
        this.sy = new Float32Array(n);
        this.sr = new Float32Array(n);
        this.vis = new Uint8Array(n);
        this.radiusW = new Float32Array(n);
        for (let i = 0; i < n; i++) {
            const d = nodes[i];
            this.radiusW[i] = RENDER.radiusBase * Math.sqrt(Math.max(1, d.mass)) * (sim.depth[i] === 0 ? RENDER.rootFactor : 1);
        }
        let lo = Infinity;
        let hi = -Infinity;
        let known = 0;
        for (const d of nodes) {
            if (d.langs === null)
                continue;
            known++;
            lo = Math.min(lo, d.langs);
            hi = Math.max(hi, d.langs);
        }
        this.langsMin = known > 0 ? lo : 0;
        this.langsMax = known > 0 ? hi : 0;
        this.langsKnown = known;
        this.covBin = new Int8Array(n);
        this.binCoverage();
        this.labelText = nodes.map((d) => (d.label.length > RENDER.maxLabelChars ? d.label.slice(0, RENDER.maxLabelChars - 1) + "…" : d.label));
        this.labelW = new Float32Array(n).fill(-1);
        this.rootW = new Float32Array(n).fill(-1);
        this.massOrder = Int32Array.from({ length: n }, (_, i) => i).sort((a, b) => nodes[b].mass - nodes[a].mass || (nodes[a].id < nodes[b].id ? -1 : 1));
        this.primaryRootSlot = new Uint8Array(sim.roots.length);
        for (let s = 0; s < sim.roots.length; s++)
            this.primaryRootSlot[s] = nodes[sim.roots[s]].scheme === primaryScheme ? 1 : 0;
        this.keys = new Uint16Array(n);
        this.counts = new Int32Array(KEYS + 1);
        this.order = new Int32Array(n);
    }
    /** Ramp step per node on log(1 + langs); -1 for unknown. */
    binCoverage() {
        const steps = Math.max(1, Math.min(12, this.theme.ramp.length));
        const a = Math.log1p(this.langsMin);
        const b = Math.log1p(this.langsMax);
        for (let i = 0; i < this.n; i++) {
            const L = this.nodes[i].langs;
            if (L === null) {
                this.covBin[i] = -1;
                continue;
            }
            const t = b > a ? (Math.log1p(L) - a) / (b - a) : 1;
            this.covBin[i] = Math.min(steps - 1, Math.max(0, Math.floor(t * steps)));
        }
    }
    setTheme(theme) {
        const fontChanged = theme.font !== this.theme.font;
        this.theme = theme;
        this.binCoverage();
        if (fontChanged) {
            this.labelW.fill(-1);
            this.rootW.fill(-1);
        }
    }
    /** Match the backing store to the element size and devicePixelRatio. Returns true if changed. */
    resize() {
        const dpr = Math.max(1, Math.min(3, window.devicePixelRatio || 1));
        const w = Math.max(1, this.canvas.clientWidth);
        const h = Math.max(1, this.canvas.clientHeight);
        const bw = Math.round(w * dpr);
        const bh = Math.round(h * dpr);
        if (bw === this.canvas.width && bh === this.canvas.height && dpr === this.dpr && w === this.width && h === this.height)
            return false;
        this.canvas.width = bw;
        this.canvas.height = bh;
        this.width = w;
        this.height = h;
        this.dpr = dpr;
        return true;
    }
    fontSize(kind) {
        if (kind === F_ROOT)
            return this.rootSize;
        if (kind === F_OTHER_ROOT)
            return Math.max(10, this.rootSize - 1);
        if (kind === F_SELECTED)
            return RENDER.selectedFontSize;
        return RENDER.labelFontSize;
    }
    font(kind) {
        const weight = kind === F_ROOT || kind === F_SELECTED ? 600 : kind === F_OTHER_ROOT ? 500 : 400;
        return `${weight} ${this.fontSize(kind)}px ${this.theme.font}`;
    }
    /** Text width of node i's label in a label font (domain widths scale from 13 px). */
    measure(i, kind) {
        if (kind === F_ROOT || kind === F_OTHER_ROOT) {
            if (this.rootW[i] < 0) {
                this.ctx.font = `600 13px ${this.theme.font}`;
                this.rootW[i] = this.ctx.measureText(this.labelText[i]).width;
            }
            return (this.rootW[i] * this.fontSize(kind)) / 13 + 1;
        }
        if (kind === F_LABEL) {
            if (this.labelW[i] < 0) {
                this.ctx.font = this.font(F_LABEL);
                this.labelW[i] = this.ctx.measureText(this.labelText[i]).width;
            }
            return this.labelW[i];
        }
        this.ctx.font = this.font(kind);
        return this.ctx.measureText(this.labelText[i]).width;
    }
    draw(sim, cam, em) {
        const t0 = performance.now();
        const ctx = this.ctx;
        const th = this.theme;
        const W = this.width;
        const H = this.height;
        const n = this.n;
        ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
        ctx.globalAlpha = 1;
        ctx.fillStyle = th.surface;
        ctx.fillRect(0, 0, W, H);
        // Screen positions: screen = world * s + (ox, oy); mark radii scale as s^exponent.
        const s = cam.scale;
        const ox = W / 2 - cam.x * s;
        const oy = H / 2 - cam.y * s;
        this.s = s;
        this.ox = ox;
        this.oy = oy;
        const markScale = Math.pow(s, RENDER.radiusZoomExponent);
        const { sx, sy, sr, vis } = this;
        const x = sim.x;
        const y = sim.y;
        const minR = RENDER.minScreenRadius;
        const maxR = RENDER.maxScreenRadius;
        const hits = em.hits;
        const sel = em.selected;
        let visible = 0;
        for (let i = 0; i < n; i++) {
            const px = x[i] * s + ox;
            const py = y[i] * s + oy;
            let r = this.radiusW[i] * markScale;
            r = r < minR ? minR : r > maxR ? maxR : r;
            if (hits !== null && hits[i] === 1 && r < RENDER.hitMinRadius)
                r = RENDER.hitMinRadius;
            if ((i === sel || i === em.hovered) && r < RENDER.selectedMinRadius)
                r = RENDER.selectedMinRadius;
            sx[i] = px;
            sy[i] = py;
            sr[i] = r;
            const v = px > -r - 40 && px < W + r + 40 && py > -r - 40 && py < H + r + 40 ? 1 : 0;
            vis[i] = v;
            visible += v;
        }
        this.drawEdges(sim, em, W, H);
        if (em.glow && sim.glowing > 0)
            this.drawGlow(sim, sel);
        this.drawParticles(sim, em);
        // Rings: hits and hover in the coverage lens (ink), hover in structure (accent),
        // the selection (accent-2), each separated from its mark by a surface gap.
        ctx.globalAlpha = 1;
        if (em.lens === "coverage" && hits)
            this.ringBatch((i) => hits[i] === 1 && vis[i] === 1, th.ink, 1.5);
        if (em.hovered >= 0 && vis[em.hovered] && em.hovered !== sel) {
            const hv = em.hovered;
            this.ringBatch((i) => i === hv, em.lens === "coverage" ? th.ink : th.accent, 1.5);
        }
        if (sel >= 0 && vis[sel])
            this.ringBatch((i) => i === sel, th.accent2, RENDER.ringWidth);
        this.drawLabels(sim, em, W, H);
        this.stats.particles = visible;
        this.stats.ms = performance.now() - t0;
    }
    drawEdges(sim, em, W, H) {
        const ctx = this.ctx;
        const { sx, sy } = this;
        const es = sim.es;
        const et = sim.et;
        const kind = sim.ekind;
        const sel = em.selected;
        const hasSel = sel >= 0;
        const dim = hasSel ? RENDER.selectionMuted : em.hits ? 0.6 : 1;
        ctx.strokeStyle = this.theme.ink;
        ctx.lineWidth = RENDER.hairline;
        ctx.lineCap = "butt";
        let drawn = 0;
        // 0: broader, 1: related + mapping, 2: semantic (only when toggled on)
        const groups = em.showSemantic ? 3 : 2;
        for (let g = 0; g < groups; g++) {
            ctx.globalAlpha = (g === 0 ? RENDER.edgeAlpha.broader : g === 1 ? RENDER.edgeAlpha.related : RENDER.edgeAlpha.semantic) * dim;
            ctx.beginPath();
            for (let e = 0; e < sim.m; e++) {
                const k = kind[e];
                const group = k === KIND_BROADER ? 0 : k === KIND_SEMANTIC ? 2 : 1;
                if (group !== g)
                    continue;
                const a = es[e];
                const b = et[e];
                if (hasSel && (a === sel || b === sel))
                    continue;
                const ax = sx[a];
                const ay = sy[a];
                const bx = sx[b];
                const by = sy[b];
                if ((ax < 0 && bx < 0) || (ax > W && bx > W) || (ay < 0 && by < 0) || (ay > H && by > H))
                    continue;
                ctx.moveTo(ax, ay);
                ctx.lineTo(bx, by);
                drawn++;
            }
            ctx.stroke();
        }
        if (hasSel) {
            ctx.globalAlpha = RENDER.edgeAlphaIncident;
            ctx.beginPath();
            for (let e = 0; e < sim.m; e++) {
                const a = es[e];
                const b = et[e];
                if (a !== sel && b !== sel)
                    continue;
                if (kind[e] === KIND_SEMANTIC && !em.showSemantic)
                    continue;
                ctx.moveTo(sx[a], sy[a]);
                ctx.lineTo(sx[b], sy[b]);
                drawn++;
            }
            ctx.stroke();
        }
        ctx.globalAlpha = 1;
        this.stats.edges = drawn;
    }
    /** Halo of radius and opacity proportional to each particle's glow energy E. */
    drawGlow(sim, sel) {
        const ctx = this.ctx;
        const E = sim.energy;
        const { sx, sy, sr, vis } = this;
        const levels = 8;
        const TAU = Math.PI * 2;
        for (let pass = 0; pass < 2; pass++) {
            ctx.fillStyle = pass === 0 ? this.theme.accent : this.theme.accent2;
            for (let q = 1; q <= levels; q++) {
                const lo = (q - 1) / levels;
                const hi = q / levels;
                let any = false;
                ctx.beginPath();
                for (let i = 0; i < this.n; i++) {
                    const e = E[i];
                    if (e <= lo || e > hi || !vis[i])
                        continue;
                    if ((i === sel) !== (pass === 1))
                        continue;
                    const r = sr[i] + 2 + RENDER.glowGrow * e;
                    ctx.moveTo(sx[i] + r, sy[i]);
                    ctx.arc(sx[i], sy[i], r, 0, TAU);
                    any = true;
                }
                if (any) {
                    ctx.globalAlpha = RENDER.glowAlpha * ((lo + hi) / 2);
                    ctx.fill();
                }
            }
        }
        ctx.globalAlpha = 1;
    }
    alphaOf(level) {
        const d = RENDER.depthAlpha;
        if (level < 4)
            return d[level];
        if (level < 8)
            return d[level - 4] * RENDER.searchMuted;
        if (level < 12)
            return d[level - 8] * RENDER.selectionMuted;
        if (level === A_FULL)
            return 1;
        if (level === A_SEL_MUTED)
            return RENDER.selectionMuted;
        return RENDER.searchMuted;
    }
    colorOf(c) {
        const th = this.theme;
        if (c === C_INK)
            return th.ink;
        if (c === C_ACCENT)
            return th.accent;
        if (c === C_ACCENT2)
            return th.accent2;
        if (c === C_HOLLOW)
            return th.muted;
        return th.ramp[c - C_RAMP] ?? th.ink;
    }
    drawParticles(sim, em) {
        const ctx = this.ctx;
        const { sx, sy, sr, vis, keys, counts, order } = this;
        const n = this.n;
        const sel = em.selected;
        const hasSel = sel >= 0;
        const nb = em.neighbors;
        const hits = em.hits;
        const coverage = em.lens === "coverage";
        counts.fill(0);
        for (let i = 0; i < n; i++) {
            if (!vis[i])
                continue;
            const depth = Math.min(3, sim.depth[i]);
            const isHit = hits !== null && hits[i] === 1;
            const isNb = hasSel && nb !== null && nb[i] === 1;
            let layer = 1;
            let color;
            let alpha;
            if (coverage) {
                const bin = this.covBin[i];
                color = bin < 0 ? C_HOLLOW : C_RAMP + bin;
                alpha = A_FULL;
                if (i === sel || i === em.hovered)
                    layer = 3;
                else if (hasSel && !isNb) {
                    alpha = A_SEL_MUTED;
                    layer = 0;
                }
                else if (hits !== null && !isHit && !hasSel) {
                    alpha = A_SEARCH_MUTED;
                    layer = 0;
                }
                else if (isHit || isNb)
                    layer = 2;
            }
            else {
                color = C_INK;
                alpha = depth;
                if (i === sel) {
                    color = C_ACCENT2;
                    alpha = A_FULL;
                    layer = 3;
                }
                else if (i === em.hovered) {
                    color = C_ACCENT;
                    alpha = A_FULL;
                    layer = 3;
                }
                else if (isHit) {
                    color = C_ACCENT;
                    alpha = A_FULL;
                    layer = 2;
                }
                else if (hasSel) {
                    if (isNb) {
                        alpha = A_FULL;
                        layer = 2;
                    }
                    else {
                        alpha = 8 + depth;
                        layer = 0;
                    }
                }
                else if (hits !== null) {
                    alpha = 4 + depth;
                    layer = 0;
                }
            }
            const key = layer * 256 + color * 16 + alpha;
            keys[i] = key;
            counts[key + 1]++;
        }
        for (let k = 1; k <= KEYS; k++)
            counts[k] += counts[k - 1];
        const total = counts[KEYS];
        for (let i = 0; i < n; i++) {
            if (!vis[i])
                continue;
            order[counts[keys[i]]++] = i;
        }
        const TAU = Math.PI * 2;
        // Device pixels decide: on a dense screen the same mark stays a disc.
        const squareBelow = RENDER.squareBelowRadius / this.dpr;
        let k = 0;
        while (k < total) {
            const key = keys[order[k]];
            const layer = key >> 8;
            const color = (key >> 4) & 15;
            const alpha = key & 15;
            const hollow = color === C_HOLLOW;
            ctx.beginPath();
            let j = k;
            while (j < total && keys[order[j]] === key) {
                const i = order[j];
                const r = hollow ? Math.max(1.6, sr[i] - 0.6) : sr[i];
                if (!hollow && r < squareBelow) {
                    // Sub-2px marks: an area-matched square rasterises far cheaper than an arc and
                    // is indistinguishable at this size.
                    const h = r * 0.886;
                    ctx.rect(sx[i] - h, sy[i] - h, 2 * h, 2 * h);
                }
                else {
                    ctx.moveTo(sx[i] + r, sy[i]);
                    ctx.arc(sx[i], sy[i], r, 0, TAU);
                }
                j++;
            }
            if (layer >= 2 && !hollow) {
                // Emphasised marks sit on a thin surface-coloured ring, so they stay legible on top of neighbours.
                ctx.globalAlpha = 1;
                ctx.strokeStyle = this.theme.surface;
                ctx.lineWidth = RENDER.surfaceRing * 2;
                ctx.stroke();
            }
            ctx.globalAlpha = this.alphaOf(alpha);
            if (hollow) {
                ctx.strokeStyle = this.colorOf(color);
                ctx.lineWidth = 1.25;
                ctx.stroke();
            }
            else {
                ctx.fillStyle = this.colorOf(color);
                ctx.fill();
            }
            k = j;
        }
        ctx.globalAlpha = 1;
    }
    /** A ring around matching particles, separated from the mark by a surface-coloured gap. */
    ringBatch(test, color, width) {
        const ctx = this.ctx;
        const { sx, sy, sr } = this;
        const TAU = Math.PI * 2;
        ctx.beginPath();
        let any = false;
        for (let i = 0; i < this.n; i++) {
            if (!test(i))
                continue;
            const r = sr[i] + RENDER.ringGap + width / 2;
            ctx.moveTo(sx[i] + r, sy[i]);
            ctx.arc(sx[i], sy[i], r, 0, TAU);
            any = true;
        }
        if (!any)
            return;
        ctx.globalAlpha = 1;
        ctx.strokeStyle = this.theme.surface;
        ctx.lineWidth = width + 2 * RENDER.ringGap;
        ctx.stroke();
        ctx.strokeStyle = color;
        ctx.lineWidth = width;
        ctx.stroke();
    }
    /**
     * Domain labels: centered on each cluster's mass-weighted centroid, else just above or
     * below the cluster. Tried at each size in rootFontSizes until none overlap; returns
     * the rectangles and positions, or null when this size does not fit.
     */
    placeDomains(sim, fixed, em, W, H, size) {
        this.rootSize = size;
        const trial = this.trial;
        trial.reset(W, H, 48);
        for (const r of em.obstacles)
            trial.add(r[0], r[1], r[2], r[3]);
        for (const r of fixed)
            trial.add(r[0], r[1], r[2], r[3]);
        const out = [];
        const pad = 2;
        const h = size * 1.2;
        // Bigger domains claim the centered position first.
        const slots = [];
        for (let slot = 0; slot < sim.roots.length; slot++)
            if (this.primaryRootSlot[slot] === 1 && sim.roots[slot] !== em.selected)
                slots.push(slot);
        slots.sort((a, b) => sim.clusterRadius[b] - sim.clusterRadius[a] || a - b);
        for (const slot of slots) {
            const r = sim.roots[slot];
            const px = sim.centroidX[slot] * this.s + this.ox;
            const py = sim.centroidY[slot] * this.s + this.oy;
            if (px < -60 || px > W + 60 || py < -20 || py > H + 20)
                continue;
            const w = this.measure(r, F_ROOT);
            // Centered on the centroid, else just above or below the cluster (a full line clear).
            const line = h + 2 * pad + 2;
            const off = Math.max(line, sim.clusterRadius[slot] * this.s * 0.9 + h / 2);
            let placed = false;
            for (const dy of [0, -off, off, -off - line, off + line]) {
                const cy = py + dy;
                const rect = [px - w / 2 - pad, cy - h / 2 - pad, px + w / 2 + pad, cy + h / 2 + pad];
                if (trial.collides(rect[0], rect[1], rect[2], rect[3]))
                    continue;
                trial.add(rect[0], rect[1], rect[2], rect[3]);
                out.push({ slot, rect, x: px, y: cy });
                placed = true;
                break;
            }
            if (!placed)
                return null;
        }
        return out;
    }
    drawLabels(sim, em, W, H) {
        const th = this.theme;
        const grid = this.grid;
        grid.reset(W, H, 48);
        for (const r of em.obstacles)
            grid.add(r[0], r[1], r[2], r[3]);
        const placed = [];
        const fixed = [];
        const { sx, sy, sr, vis } = this;
        const sel = em.selected;
        const hasSel = sel >= 0;
        const nb = em.neighbors;
        const hits = em.hits;
        const pad = 2;
        const byParticle = (i, kind, color, force) => {
            if (!vis[i])
                return false;
            const w = this.measure(i, kind);
            const h = this.fontSize(kind) * 1.2;
            const cy = sy[i];
            const gap = sr[i] + (i === sel ? RENDER.ringGap + RENDER.ringWidth + 4 : 4);
            const right = [sx[i] + gap - pad, cy - h / 2 - pad, sx[i] + gap + w + pad, cy + h / 2 + pad];
            const left = [sx[i] - gap - w - pad, cy - h / 2 - pad, sx[i] - gap + pad, cy + h / 2 + pad];
            const inView = (r) => r[0] >= 0 && r[2] <= W && r[1] >= 0 && r[3] <= H;
            const options = [
                [right, "left"],
                [left, "right"],
            ];
            for (const [rect, align] of options) {
                if (!force && (!inView(rect) || grid.collides(rect[0], rect[1], rect[2], rect[3])))
                    continue;
                if (force && !inView(rect) && rect === right && inView(left))
                    continue;
                grid.add(rect[0], rect[1], rect[2], rect[3]);
                if (force)
                    fixed.push(rect);
                placed.push({ text: this.labelText[i], x: align === "left" ? rect[0] + pad : rect[2] - pad, y: cy, font: kind, color, align });
                return true;
            }
            return false;
        };
        // 1. The selected node always carries a visible label.
        if (hasSel)
            byParticle(sel, F_SELECTED, th.ink, true);
        // 2. Domain labels (always drawn): the largest size at which none overlap.
        sim.updateCentroids();
        let domains = null;
        for (const size of RENDER.rootFontSizes) {
            domains = this.placeDomains(sim, fixed, em, W, H, size);
            if (domains)
                break;
        }
        let overlaps = 0;
        if (!domains) {
            // Last resort: smallest size, centered, overlaps counted (reported in stats).
            this.rootSize = RENDER.rootFontSizes[RENDER.rootFontSizes.length - 1];
            domains = [];
            const h = this.rootSize * 1.2;
            for (let slot = 0; slot < sim.roots.length; slot++) {
                if (this.primaryRootSlot[slot] !== 1 || sim.roots[slot] === sel)
                    continue;
                const px = sim.centroidX[slot] * this.s + this.ox;
                const py = sim.centroidY[slot] * this.s + this.oy;
                const w = this.measure(sim.roots[slot], F_ROOT);
                const rect = [px - w / 2 - pad, py - h / 2 - pad, px + w / 2 + pad, py + h / 2 + pad];
                if (grid.collides(rect[0], rect[1], rect[2], rect[3]))
                    overlaps++;
                grid.add(rect[0], rect[1], rect[2], rect[3]);
                domains.push({ slot, rect, x: px, y: py });
            }
        }
        else {
            for (const d of domains)
                grid.add(d.rect[0], d.rect[1], d.rect[2], d.rect[3]);
        }
        for (const d of domains) {
            placed.push({ text: this.labelText[sim.roots[d.slot]], x: d.x, y: d.y, font: F_ROOT, color: th.ink, align: "center" });
        }
        // Other schemes' top concepts: same place, but only where they fit.
        for (let slot = 0; slot < sim.roots.length; slot++) {
            if (this.primaryRootSlot[slot] !== 0)
                continue;
            const r = sim.roots[slot];
            if (r === sel)
                continue;
            const px = sim.centroidX[slot] * this.s + this.ox;
            const py = sim.centroidY[slot] * this.s + this.oy;
            const w = this.measure(r, F_OTHER_ROOT);
            const h = this.fontSize(F_OTHER_ROOT) * 1.2;
            const rect = [px - w / 2 - pad, py - h / 2 - pad, px + w / 2 + pad, py + h / 2 + pad];
            if (rect[2] < 0 || rect[0] > W || rect[3] < 0 || rect[1] > H)
                continue;
            if (grid.collides(rect[0], rect[1], rect[2], rect[3]))
                continue;
            grid.add(rect[0], rect[1], rect[2], rect[3]);
            placed.push({ text: this.labelText[r], x: px, y: py, font: F_OTHER_ROOT, color: th.ink, align: "center" });
        }
        // 3. Search hits in rank order, 4. neighbours of the selection, 5. the rest by mass
        // once their marks are big enough on screen. All collision-checked.
        let budget = RENDER.maxLabels;
        if (em.hitOrder) {
            for (let k = 0; k < em.hitOrder.length && budget > 0; k++) {
                const i = em.hitOrder[k];
                if (i === sel || sim.depth[i] === 0)
                    continue;
                if (byParticle(i, F_LABEL, th.ink, false))
                    budget--;
            }
        }
        if (hasSel && nb) {
            for (let k = 0; k < this.n && budget > 0; k++) {
                const i = this.massOrder[k];
                if (nb[i] !== 1 || i === sel || sim.depth[i] === 0)
                    continue;
                if (byParticle(i, F_LABEL, th.ink2, false))
                    budget--;
            }
        }
        if (!hits) {
            for (let k = 0; k < this.n && budget > 0; k++) {
                const i = this.massOrder[k];
                if (!vis[i] || sim.depth[i] === 0 || i === sel)
                    continue;
                if (sr[i] < RENDER.labelMinRadius)
                    continue;
                if (hasSel && !(nb && nb[i] === 1))
                    continue;
                if (byParticle(i, F_LABEL, th.ink2, false))
                    budget--;
            }
        }
        // Draw: halos first (surface stroke), then text, grouped by font.
        const ctx = this.ctx;
        ctx.globalAlpha = 1;
        ctx.textBaseline = "middle";
        ctx.lineJoin = "round";
        ctx.lineWidth = RENDER.halo;
        ctx.strokeStyle = th.surface;
        for (const kind of [F_LABEL, F_OTHER_ROOT, F_ROOT, F_SELECTED]) {
            const group = placed.filter((p) => p.font === kind);
            if (group.length === 0)
                continue;
            ctx.font = this.font(kind);
            for (const p of group) {
                ctx.textAlign = p.align;
                ctx.strokeText(p.text, p.x, p.y);
            }
            for (const p of group) {
                ctx.textAlign = p.align;
                ctx.fillStyle = p.color;
                ctx.fillText(p.text, p.x, p.y);
            }
        }
        this.stats.labels = placed.length;
        this.stats.rootLabelSize = this.rootSize;
        this.stats.rootOverlaps = overlaps;
    }
}
//# sourceMappingURL=render.js.map