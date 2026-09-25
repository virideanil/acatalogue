// Wiring: data -> simulation -> camera -> renderer, the requestAnimationFrame loop with
// its fixed-timestep accumulators, pointer and keyboard input, search, selection.

import { Sim, KIND_BROADER, KIND_MAPPING, KIND_RELATED, KIND_SEMANTIC } from "./physics.js";
import { Camera, CAMERA } from "./camera.js";
import { Renderer, type Emphasis, type Lens } from "./render.js";
import { PointGrid } from "./grid.js";
import {
  ApiError,
  auditFromGraph,
  fetchAudit,
  fetchNode,
  grep,
  loadGraph,
  localLabelSearch,
  probeApi,
  type GrepHit,
  type GrepMode,
  type GrepResponse,
  type GrepScope,
  type LoadedGraph,
  type NodeRecord,
  type NodeRef,
} from "./data.js";
import { Ui } from "./ui.js";
import { effectiveTheme, readTheme, restoreTheme, toggleTheme, watchTheme } from "./theme.js";

/** Minimum pointer hit radius, CSS px. */
const HIT_RADIUS = 24;
/** Movement (px) under which a press counts as a click. */
const CLICK_SLOP = 5;
/** Search results larger than this get no glow impulse (the accent highlight remains). */
const GLOW_MAX_HITS = 40;
/** Typing pause before a search runs, ms (API and offline). */
const SEARCH_DEBOUNCE_MS = { api: 200, offline: 120 };
/** Reduced-motion pre-settle limits (whichever comes first, then the layout freezes). */
const PRESETTLE = { maxSteps: 4000, maxMs: 5000 };
/** Remembered per viewer: whether motion is paused (WCAG 2.2.2 Pause, Stop, Hide). */
const PAUSE_KEY = "acatalogue.paused";

function readPaused(): boolean | null {
  try {
    const v = window.localStorage.getItem(PAUSE_KEY);
    return v === "1" ? true : v === "0" ? false : null;
  } catch {
    return null;
  }
}

function storePaused(on: boolean): void {
  try {
    window.localStorage.setItem(PAUSE_KEY, on ? "1" : "0");
  } catch {
    // storage can be unavailable (private windows, blocked site data); the choice holds for this visit
  }
}

type DragMode = "none" | "pan" | "particle" | "pinch";

interface DragState {
  mode: DragMode;
  pointer: number;
  startX: number;
  startY: number;
  moved: boolean;
  index: number;
  worldX: number;
  worldY: number;
  pinchDist: number;
}

class App {
  readonly ui: Ui;
  readonly canvas: HTMLCanvasElement;
  readonly field: HTMLElement;
  readonly camera = new Camera();
  graph: LoadedGraph | null = null;
  sim: Sim | null = null;
  renderer: Renderer | null = null;
  readonly index = new Map<string, number>();

  lens: Lens = "structure";
  selected = -1;
  hovered = -1;
  neighbors: Uint8Array | null = null;
  hits: Uint8Array | null = null;
  hitOrder: Int32Array | null = null;
  showSemantic = false;
  /** Draw every link between clusters (otherwise only the selected or hovered particle's). */
  allLinks = false;
  /** Motion paused by the viewer: no physics steps, no glow animation. */
  paused = false;
  /** The field started from positions baked offline by the same physics. */
  bakedLayout = false;
  apiOnline = false;
  reducedMotion: boolean;
  /** The camera keeps the whole field in view until the user moves it. */
  autoFit = true;
  obstacles: Array<[number, number, number, number]> = [];

  private dirty = true;
  /** Nothing is painted until the first layout is ready (pre-settled under reduced motion). */
  private ready = false;
  private running = false;
  private lastTime = 0;
  private drawCount = 0;
  private gridAt = -1;
  private readonly pointGrid = new PointGrid();
  private readonly pointers = new Map<number, { x: number; y: number }>();
  private drag: DragState = { mode: "none", pointer: -1, startX: 0, startY: 0, moved: false, index: -1, worldX: 0, worldY: 0, pinchDist: 0 };
  private searchTimer = 0;
  private searchSeq = 0;
  private searchAbort: AbortController | null = null;
  private nodeAbort: AbortController | null = null;
  private auditAbort: AbortController | null = null;
  /** Rolling diagnostics (read by window.__acat). */
  readonly perf = { frames: 0, draws: 0, physicsMs: 0, renderMs: 0, clamped: 0, fps: 0, windowStart: 0, windowFrames: 0 };

  constructor() {
    this.canvas = document.getElementById("canvas") as HTMLCanvasElement;
    this.field = document.getElementById("field") as HTMLElement;
    this.reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    this.camera.instant = this.reducedMotion;
    this.ui = new Ui({
      onSearch: (q, mode, scope) => this.onSearch(q, mode, scope),
      onPickHit: (hit) => this.onPickHit(hit),
      onSelectId: (id) => this.inspectId(id, true),
      onLens: (lens) => {
        this.lens = lens;
        this.renderKey();
        this.kick();
      },
      onSemantic: (on) => {
        this.showSemantic = on;
        this.sim?.setSemantic(on);
        this.renderKey();
        this.kick();
      },
      onFit: () => this.fit(),
      onTheme: () => {
        toggleTheme();
      },
      onAuditOpen: () => this.loadAudit(),
      onPause: () => this.setPaused(!this.paused),
      onAllLinks: (on) => {
        this.allLinks = on;
        this.kick();
      },
      onTreeSelect: (id) => this.inspectId(id, true),
    });
    this.ui.setThemeLabel(effectiveTheme());
    this.paused = readPaused() ?? false;
    this.ui.setPaused(this.paused);
  }

  // ------------------------------------------------------------ startup

  async start(): Promise<void> {
    this.ui.setSource("Loading the graph…");
    let loaded: LoadedGraph;
    try {
      loaded = await loadGraph(window.location);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      this.ui.setSource("No graph loaded.");
      this.ui.setFieldStatus(
        `No graph could be loaded (${msg}). Serve this page with \`acat serve\`, or export data/graph.json next to index.html, or pass ?graph=<url>.`,
      );
      this.ui.setOffline(true);
      return;
    }
    this.graph = loaded;
    const nodes = loaded.payload.nodes;
    nodes.forEach((n, i) => this.index.set(n.id, i));
    const sim = new Sim(loaded.payload);
    this.sim = sim;
    // Start from the layout baked offline by this same physics when the payload has one for
    // every particle; a stale one (computed for a slightly different graph) relaxes from there.
    const layout = loaded.payload.layout;
    this.bakedLayout = layout !== null && layout.complete && sim.adopt(nodes.map((n) => n.pos));
    if (this.bakedLayout && layout!.stale) sim.wake();
    this.renderer = new Renderer(this.canvas, nodes, sim, readTheme(), sim.primaryScheme);
    this.ui.setTree({
      ids: nodes.map((n) => n.id),
      labels: nodes.map((n) => n.label),
      roots: Array.from(sim.roots),
      ...this.hierarchy(),
    });

    this.apiOnline = loaded.source === "api" ? true : await probeApi();
    this.ui.setOffline(!this.apiOnline);
    this.describeSource();
    this.canvas.setAttribute(
      "aria-label",
      `Particle field of ${nodes.length} concepts in ${sim.roots.length} top concepts. The panel on the left gives the same data as text: search, inspector and audit tables.`,
    );

    watchTheme(() => this.onThemeChange());
    window.matchMedia("(prefers-reduced-motion: reduce)").addEventListener("change", (e) => {
      this.reducedMotion = e.matches;
      this.camera.instant = e.matches;
      if (e.matches) this.sim?.clearGlow();
      this.kick();
    });
    new ResizeObserver(() => this.onResize()).observe(this.field);
    this.exposeDiagnostics();
    this.installInput();
    this.renderKey();
    this.onResize();

    if (this.reducedMotion && sim.awake) await this.presettle();
    this.fitTarget();
    this.camera.cut();
    this.ready = true;
    this.kick();
  }

  private describeSource(): void {
    const g = this.graph!;
    const sim = this.sim!;
    let file = g.url;
    try {
      file = new URL(g.url, window.location.href).pathname.split("/").pop() || g.url;
    } catch {
      // keep the raw url
    }
    const where = g.source === "api" ? "live API" : g.source === "static" ? "static data/graph.json" : `${file} (?\u2060graph)`;
    const synthetic = g.payload.schemes.some((s) => /synthetic/i.test(s.title) || s.origin === "synthetic") ? " · SYNTHETIC test data" : "";
    const parts = [`${g.payload.nodes.length.toLocaleString("en")} concepts`, `${sim.m.toLocaleString("en")} links`, where + synthetic];
    const lay = g.payload.layout;
    if (this.bakedLayout) parts.push(`layout baked offline${lay?.steps ? ` (${lay.steps.toLocaleString("en")} steps)` : ""}${lay?.stale ? ", relaxing to this graph" : ""}`);
    else parts.push("layout settling live");
    if (!this.apiOnline) parts.push("API not reachable");
    const warn = [...g.warnings];
    if (sim.droppedEdges > 0) warn.push(`${sim.droppedEdges} edge(s) unusable by the physics`);
    this.ui.setSource(parts.join(" · ") + (warn.length > 0 ? ` · warnings: ${warn.join("; ")}` : ""), `Loaded from ${g.url}${g.payload.generated_at ? `, generated ${g.payload.generated_at}` : ""}`);
  }

  /**
   * Reduced motion: run the simulation off-screen until it rests (or for at most
   * PRESETTLE limits), then freeze it and draw once.
   */
  private async presettle(): Promise<void> {
    const sim = this.sim!;
    const t0 = performance.now();
    let done = 0;
    const more = (): boolean => sim.awake && done < PRESETTLE.maxSteps && performance.now() - t0 < PRESETTLE.maxMs;
    this.ui.setFieldStatus("Settling the layout before drawing (reduced motion)…");
    while (more()) {
      const t = performance.now();
      while (more() && performance.now() - t < 30) {
        sim.step();
        done++;
      }
      this.ui.setFieldStatus(`Settling the layout before drawing (reduced motion): ${done} steps`);
      await new Promise<void>((resolve) => window.setTimeout(resolve, 0));
    }
    sim.freeze();
    this.ui.setFieldStatus(null);
  }

  /** Children and parents along broader links (child -> parent), for the tree view. */
  private hierarchy(): { children: number[][]; parents: number[][] } {
    const sim = this.sim!;
    const labels = this.graph!.payload.nodes.map((n) => n.label);
    const children: number[][] = Array.from({ length: sim.n }, () => []);
    const parents: number[][] = Array.from({ length: sim.n }, () => []);
    for (let e = 0; e < sim.m; e++) {
      if (sim.ekind[e] !== KIND_BROADER) continue;
      children[sim.et[e]!]!.push(sim.es[e]!);
      parents[sim.es[e]!]!.push(sim.et[e]!);
    }
    const byLabel = (a: number, b: number): number => labels[a]!.localeCompare(labels[b]!, "en");
    for (const c of children) c.sort(byLabel);
    // primary parent first: the shallowest, then the smallest id (as the physics places it)
    const nodes = this.graph!.payload.nodes;
    for (const p of parents) p.sort((a, b) => nodes[a]!.depth - nodes[b]!.depth || (nodes[a]!.id < nodes[b]!.id ? -1 : 1));
    return { children, parents };
  }

  setPaused(on: boolean): void {
    this.paused = on;
    storePaused(on);
    this.ui.setPaused(on);
    this.describeSource();
    this.kick();
  }

  private exposeDiagnostics(): void {
    const app = this;
    Object.defineProperty(window, "__acat", {
      configurable: true,
      value: Object.freeze({
        get stats() {
          const sim = app.sim;
          return {
            nodes: sim?.n ?? 0,
            edges: sim?.m ?? 0,
            awake: sim?.awake ?? false,
            paused: app.paused,
            bakedLayout: app.bakedLayout,
            steps: sim?.stepCount ?? 0,
            meanKE: sim ? sim.meanKinetic() : 0,
            stepMs: sim?.stepMs ?? 0,
            renderMs: app.renderer?.stats.ms ?? 0,
            labels: app.renderer?.stats.labels ?? 0,
            rootLabelSize: app.renderer?.stats.rootLabelSize ?? 0,
            rootOverlaps: app.renderer?.stats.rootOverlaps ?? 0,
            fps: app.perf.fps,
            frames: app.perf.frames,
            draws: app.perf.draws,
            clamped: app.perf.clamped,
            apiOnline: app.apiOnline,
            source: app.graph?.source ?? null,
            selected: app.selected >= 0 ? app.graph!.payload.nodes[app.selected]!.id : null,
            cameraResting: app.camera.resting,
          };
        },
        /** Screen position (CSS px, relative to the canvas) of a node id, for tests. */
        screenOf(id: string): { x: number; y: number } | null {
          const i = app.index.get(id);
          if (i === undefined || !app.renderer) return null;
          return { x: app.renderer.sx[i]!, y: app.renderer.sy[i]! };
        },
      }),
    });
  }

  // ------------------------------------------------------------ loop

  kick(): void {
    this.dirty = true;
    if (this.ready && !this.running && this.sim) {
      this.running = true;
      this.lastTime = 0;
      window.requestAnimationFrame(this.tick);
    }
  }

  private readonly tick = (now: number): void => {
    const sim = this.sim!;
    const cam = this.camera;
    const dt = this.lastTime > 0 ? (now - this.lastTime) / 1000 : 1 / 60;
    this.lastTime = now;
    this.perf.frames++;
    const t0 = performance.now();
    const res = this.paused ? { steps: 0, moved: false, clamped: false } : sim.advance(dt);
    this.perf.physicsMs = performance.now() - t0;
    if (res.clamped) this.perf.clamped++;
    if (this.autoFit && res.moved) this.fitTarget();
    const camMoved = cam.advance(dt);
    const glowChanged = !this.paused && sim.glowFading > 0;
    if (res.moved || camMoved || glowChanged || this.dirty) this.draw();
    // fps over a rolling one-second window
    if (this.perf.windowStart === 0) this.perf.windowStart = now;
    this.perf.windowFrames++;
    if (now - this.perf.windowStart >= 1000) {
      this.perf.fps = (this.perf.windowFrames * 1000) / (now - this.perf.windowStart);
      this.perf.windowStart = now;
      this.perf.windowFrames = 0;
    }
    const active = (sim.awake && !this.paused) || !cam.resting || glowChanged || this.dirty || this.drag.mode !== "none";
    if (active) window.requestAnimationFrame(this.tick);
    else {
      this.running = false;
      this.perf.windowStart = 0;
      this.perf.windowFrames = 0;
    }
  };

  private draw(): void {
    const r = this.renderer!;
    if (r.resize()) this.onViewportChange();
    const em: Emphasis = {
      lens: this.lens,
      selected: this.selected,
      hovered: this.hovered,
      neighbors: this.neighbors,
      hits: this.hits,
      hitOrder: this.hitOrder,
      showSemantic: this.showSemantic,
      allLinks: this.allLinks,
      glow: !this.reducedMotion,
      obstacles: this.obstacles,
    };
    r.draw(this.sim!, this.camera, em);
    this.perf.renderMs = r.stats.ms;
    this.perf.draws++;
    this.drawCount++;
    this.dirty = false;
  }

  // ------------------------------------------------------------ view

  private bounds(): [number, number, number, number] {
    const sim = this.sim!;
    let x0 = Infinity;
    let y0 = Infinity;
    let x1 = -Infinity;
    let y1 = -Infinity;
    for (let i = 0; i < sim.n; i++) {
      const x = sim.x[i]!;
      const y = sim.y[i]!;
      if (x < x0) x0 = x;
      if (x > x1) x1 = x;
      if (y < y0) y0 = y;
      if (y > y1) y1 = y;
    }
    if (!(x1 >= x0)) return [-100, -100, 100, 100];
    return [x0, y0, x1, y1];
  }

  /** Point the camera target at the whole field (the camera follows physically). */
  private fitTarget(): void {
    const [x0, y0, x1, y1] = this.bounds();
    const t = this.camera.fitTarget(x0, y0, x1, y1);
    this.camera.setLimits(t.scale, x0, y0, x1, y1);
    this.camera.setTarget(t.x, t.y, t.scale);
  }

  fit(): void {
    this.autoFit = true;
    this.fitTarget();
    this.kick();
  }

  private onResize(): void {
    const r = this.renderer;
    if (!r) return;
    r.resize();
    this.onViewportChange();
    this.kick();
  }

  private onViewportChange(): void {
    const r = this.renderer!;
    this.camera.setViewport(r.width, r.height);
    this.updateObstacles();
    if (this.autoFit) {
      this.fitTarget();
      if (this.drawCount === 0) this.camera.cut();
    }
  }

  private updateObstacles(): void {
    const k = this.ui.keyRect();
    const c = this.canvas.getBoundingClientRect();
    this.obstacles = k.width > 0 ? [[k.left - c.left - 4, k.top - c.top - 4, k.right - c.left + 4, k.bottom - c.top + 4]] : [];
    // When the key spans most of the field's width (narrow screens), fit the data above it.
    this.camera.insetBottom = k.width > 0.5 * c.width ? Math.max(0, c.bottom - k.top + 4 - 40) : 0;
  }

  private renderKey(): void {
    const r = this.renderer;
    if (!r) return;
    this.ui.renderKey(this.lens, { min: r.langsMin, max: r.langsMax, known: r.langsKnown, total: r.n, ramp: readTheme().ramp }, this.showSemantic);
    this.updateObstacles();
  }

  private onThemeChange(): void {
    this.renderer?.setTheme(readTheme());
    this.ui.setThemeLabel(effectiveTheme());
    this.renderKey();
    this.kick();
  }

  // ------------------------------------------------------------ selection

  private computeNeighbors(i: number): Uint8Array {
    const sim = this.sim!;
    const nb = new Uint8Array(sim.n);
    for (let e = 0; e < sim.m; e++) {
      if (sim.ekind[e] === KIND_SEMANTIC && !this.showSemantic) continue;
      const a = sim.es[e]!;
      const b = sim.et[e]!;
      if (a === i) nb[b] = 1;
      else if (b === i) nb[a] = 1;
    }
    return nb;
  }

  select(i: number, fly: boolean): void {
    const sim = this.sim!;
    if (i < 0 || i >= sim.n) {
      this.clearSelection();
      return;
    }
    this.selected = i;
    this.neighbors = this.computeNeighbors(i);
    if (!this.reducedMotion && !this.paused) sim.excite(i, 1);
    if (!this.paused) sim.wake();
    this.ui.revealInTree(i);
    if (fly) {
      this.autoFit = false;
      const cur = this.camera.targetScale;
      const [x0, y0, x1, y1] = this.bounds();
      const fitS = this.camera.fitScale(x0, y0, x1, y1);
      this.camera.setTarget(sim.x[i]!, sim.y[i]!, Math.max(cur, fitS * 2.2));
    }
    void this.loadInspector(i);
    this.kick();
  }

  clearSelection(): void {
    this.selected = -1;
    this.neighbors = null;
    this.nodeAbort?.abort();
    this.ui.clearInspector();
    this.ui.clearTreeSelection();
    this.kick();
  }

  /** Select an id if it is in the field; otherwise show its record (API) without a selection. */
  inspectId(id: string, fly: boolean): void {
    const i = this.index.get(id);
    if (i !== undefined) {
      this.select(i, fly);
      return;
    }
    if (!this.apiOnline) return;
    this.selected = -1;
    this.neighbors = null;
    this.ui.showInspectorLoading(id, id);
    this.fetchRecord(id, id);
    this.kick();
  }

  private fetchRecord(id: string, label: string): void {
    this.nodeAbort?.abort();
    const ctrl = new AbortController();
    this.nodeAbort = ctrl;
    fetchNode(id, ctrl.signal)
      .then((rec) => {
        if (ctrl.signal.aborted) return;
        this.ui.showNode(rec, (x) => this.index.has(x), null);
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        const msg = err instanceof ApiError ? err.message : err instanceof Error ? `API not reachable (${err.message})` : String(err);
        this.ui.showInspectorError(label, id, msg);
      });
  }

  private async loadInspector(i: number): Promise<void> {
    const node = this.graph!.payload.nodes[i]!;
    if (!this.apiOnline) {
      this.ui.showNode(this.offlineRecord(i), (x) => this.index.has(x), "offline: from the loaded graph. Labels, documents, claims and provenance need the API.");
      return;
    }
    this.ui.showInspectorLoading(node.label, node.id);
    this.fetchRecord(node.id, node.label);
  }

  /** What the graph alone says about a node (used when the API is not reachable). */
  private offlineRecord(i: number): NodeRecord {
    const sim = this.sim!;
    const nodes = this.graph!.payload.nodes;
    const n = nodes[i]!;
    const ref = (j: number): NodeRef => ({ id: nodes[j]!.id, label: nodes[j]!.label });
    const broader: NodeRef[] = [];
    const narrower: NodeRef[] = [];
    const related: NodeRef[] = [];
    const mappings: NodeRecord["mappings"] = [];
    const neighbors: NodeRecord["neighbors"] = [];
    for (let e = 0; e < sim.m; e++) {
      const a = sim.es[e]!;
      const b = sim.et[e]!;
      if (a !== i && b !== i) continue;
      const other = a === i ? b : a;
      const k = sim.ekind[e]!;
      if (k === KIND_BROADER) (a === i ? broader : narrower).push(ref(other));
      else if (k === KIND_RELATED) related.push(ref(other));
      else if (k === KIND_MAPPING) mappings.push({ ...ref(other), relation: "mapping", method: "graph edge", status: "", decided_by: "", reviewer: "", note: "" });
      else neighbors.push({ ...ref(other), score: sim.ek[e]! > 0 ? this.edgeWeight(a, b) : 0, model: "semantic edge in the graph" });
    }
    const byLabel = (x: NodeRef, y: NodeRef): number => (x.label < y.label ? -1 : x.label > y.label ? 1 : 0);
    broader.sort(byLabel);
    narrower.sort(byLabel);
    related.sort(byLabel);
    neighbors.sort((x, y) => y.score - x.score);
    return {
      id: n.id,
      scheme: n.scheme,
      code: n.id.includes("/") ? n.id.slice(n.id.indexOf("/") + 1) : n.id,
      label: n.label,
      scope_note: "",
      status: `depth ${n.depth} · ${n.docs} document${n.docs === 1 ? "" : "s"}`,
      labels: [],
      n_label_langs: 0,
      langs: n.langs,
      broader,
      narrower,
      related,
      mappings,
      documents: [],
      claims: [],
      neighbors,
      provenance: [],
      reviews: [],
      sources: [],
    };
  }

  private edgeWeight(a: number, b: number): number {
    for (const e of this.graph!.payload.edges) if ((e.s === a && e.t === b) || (e.s === b && e.t === a)) return e.w;
    return 0;
  }

  // ------------------------------------------------------------ search

  private onSearch(q: string, mode: GrepMode, scope: GrepScope): void {
    window.clearTimeout(this.searchTimer);
    const query = q.trim();
    if (query.length === 0) {
      this.clearSearch();
      return;
    }
    if (!this.apiOnline) {
      this.searchTimer = window.setTimeout(() => this.applyResults(localLabelSearch(this.graph!.payload.nodes, query)), SEARCH_DEBOUNCE_MS.offline);
      return;
    }
    this.ui.showSearching(query);
    this.searchTimer = window.setTimeout(() => void this.runGrep(query, mode, scope), SEARCH_DEBOUNCE_MS.api);
  }

  private async runGrep(q: string, mode: GrepMode, scope: GrepScope): Promise<void> {
    this.searchAbort?.abort();
    const ctrl = new AbortController();
    this.searchAbort = ctrl;
    const seq = ++this.searchSeq;
    try {
      const resp = await grep({ q, mode, scope, limit: 200 }, ctrl.signal);
      if (seq !== this.searchSeq) return;
      if (resp.error) {
        this.setHits(null);
        this.ui.showSearchError(`Bad pattern: ${resp.error}`, resp);
        return;
      }
      this.applyResults(resp);
    } catch (err) {
      if (ctrl.signal.aborted || seq !== this.searchSeq) return;
      if (err instanceof ApiError) {
        this.setHits(null);
        this.ui.showSearchError(`Search failed: ${err.message}`, null);
        return;
      }
      // Network failure: the API went away. Fall back, and say so.
      this.apiOnline = false;
      this.ui.setOffline(true);
      this.describeSource();
      this.applyResults(localLabelSearch(this.graph!.payload.nodes, q));
    }
  }

  private setHits(order: number[] | null): void {
    const sim = this.sim!;
    const previous = this.hits;
    if (order === null || order.length === 0) {
      this.hits = null;
      this.hitOrder = null;
    } else {
      const hits = new Uint8Array(sim.n);
      for (const i of order) hits[i] = 1;
      this.hits = hits;
      this.hitOrder = Int32Array.from(order);
      // Light up what just arrived; a broad match (every keystroke of a word) stays a
      // static highlight instead of flashing the whole field.
      if (!this.reducedMotion && order.length <= GLOW_MAX_HITS) {
        for (const i of order) if (!previous || previous[i] !== 1) sim.excite(i, 1);
      }
    }
    this.kick();
  }

  private applyResults(resp: GrepResponse): void {
    const order: number[] = [];
    const seen = new Set<number>();
    for (const hit of resp.hits) {
      for (const c of hit.concepts) {
        const i = this.index.get(c);
        if (i === undefined || seen.has(i)) continue;
        seen.add(i);
        order.push(i);
      }
    }
    this.setHits(order);
    this.ui.showResults(resp, (id) => this.index.has(id));
  }

  private clearSearch(): void {
    window.clearTimeout(this.searchTimer);
    this.searchAbort?.abort();
    this.searchSeq++;
    this.setHits(null);
    this.ui.clearResults();
  }

  private onPickHit(hit: GrepHit): void {
    const inField = hit.concepts.find((c) => this.index.has(c));
    if (inField) this.inspectId(inField, true);
    else this.inspectId(hit.concepts[0] ?? hit.target, true);
  }

  // ------------------------------------------------------------ audit

  private loadAudit(): void {
    const g = this.graph;
    if (!g) return;
    const inField = (id: string): boolean => this.index.has(id);
    if (!this.apiOnline) {
      // a static snapshot may carry the stored audit next to its graph (acat export-graph writes both)
      let url = "";
      try {
        url = new URL("audit.json", new URL(g.url, window.location.href)).href;
      } catch {
        url = "";
      }
      const offline = (): void => this.ui.showAudit(auditFromGraph(g.payload, this.sim!.primaryScheme), true, inField);
      if (g.source === "api" || !url) {
        offline();
        return;
      }
      fetchAudit(undefined, url)
        .then((a) => this.ui.showAudit(a, false, inField))
        .catch(offline);
      return;
    }
    this.auditAbort?.abort();
    const ctrl = new AbortController();
    this.auditAbort = ctrl;
    this.ui.showAuditLoading();
    fetchAudit(ctrl.signal)
      .then((a) => {
        if (!ctrl.signal.aborted) this.ui.showAudit(a, false, inField);
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        this.ui.showAuditError(`Audit failed: ${err instanceof Error ? err.message : String(err)}. Showing what the graph alone gives.`);
        this.ui.showAudit(auditFromGraph(g.payload, this.sim!.primaryScheme), true, inField);
      });
  }

  // ------------------------------------------------------------ input

  private local(e: PointerEvent | WheelEvent | MouseEvent): { x: number; y: number } {
    const r = this.canvas.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  }

  private hitTest(x: number, y: number): number {
    const r = this.renderer!;
    if (this.gridAt !== this.drawCount) {
      this.pointGrid.build(r.sx, r.sy, r.vis, r.n, r.width, r.height, HIT_RADIUS);
      this.gridAt = this.drawCount;
    }
    return this.pointGrid.nearest(x, y, HIT_RADIUS, r.sx, r.sy, r.sr);
  }

  private setHover(i: number, x: number, y: number): void {
    const sim = this.sim!;
    if (i !== this.hovered) {
      if (this.hovered >= 0) sim.hold(this.hovered, false);
      this.hovered = i;
      if (i >= 0 && !this.reducedMotion) sim.hold(i, true);
      this.kick();
    }
    if (i < 0) {
      this.ui.hideTooltip();
      this.canvas.style.cursor = "";
      return;
    }
    this.canvas.style.cursor = "pointer";
    const n = this.graph!.payload.nodes[i]!;
    const scheme = this.graph!.payload.schemes.find((s) => s.id === n.scheme);
    const lines = [
      n.langs === null ? "language coverage unknown" : `${n.langs.toLocaleString("en")} Wikipedia language editions`,
      `${scheme ? scheme.title : n.scheme} · ${n.id}`,
    ];
    this.ui.showTooltip(x, y, n.label, lines, this.renderer!.width, this.renderer!.height);
  }

  private installInput(): void {
    const c = this.canvas;
    c.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 && e.pointerType === "mouse") return;
      const p = this.local(e);
      this.pointers.set(e.pointerId, p);
      c.setPointerCapture(e.pointerId);
      if (!this.paused) this.sim!.wake();
      if (this.pointers.size === 2) {
        // Two fingers: pinch zoom around their midpoint.
        const [a, b] = [...this.pointers.values()] as [{ x: number; y: number }, { x: number; y: number }];
        if (this.drag.mode === "particle") this.sim!.release();
        this.drag = { ...this.drag, mode: "pinch", pinchDist: Math.hypot(a.x - b.x, a.y - b.y), moved: true };
        this.autoFit = false;
        return;
      }
      const i = this.hitTest(p.x, p.y);
      const wx = this.camera.screenToWorldX(p.x);
      const wy = this.camera.screenToWorldY(p.y);
      // paused: a drag that starts on a particle pans (nothing moves on its own); a click still selects
      this.drag = { mode: i >= 0 && !this.paused ? "particle" : "pan", pointer: e.pointerId, startX: p.x, startY: p.y, moved: false, index: i, worldX: wx, worldY: wy, pinchDist: 0 };
      this.ui.hideTooltip();
      this.kick();
    });
    c.addEventListener("pointermove", (e) => {
      const p = this.local(e);
      if (this.pointers.has(e.pointerId)) this.pointers.set(e.pointerId, p);
      const d = this.drag;
      if (d.mode === "none") {
        if (e.pointerType === "mouse") this.setHover(this.hitTest(p.x, p.y), p.x, p.y);
        return;
      }
      if (d.mode === "pinch") {
        if (this.pointers.size < 2) return;
        const [a, b] = [...this.pointers.values()] as [{ x: number; y: number }, { x: number; y: number }];
        const dist = Math.hypot(a.x - b.x, a.y - b.y);
        if (d.pinchDist > 0 && dist > 0) this.camera.zoomAt((a.x + b.x) / 2, (a.y + b.y) / 2, dist / d.pinchDist);
        d.pinchDist = dist;
        this.kick();
        return;
      }
      if (e.pointerId !== d.pointer) return;
      if (!d.moved && Math.hypot(p.x - d.startX, p.y - d.startY) > CLICK_SLOP) {
        d.moved = true;
        if (d.mode === "particle") {
          this.autoFit = false;
          this.sim!.grab(d.index, this.camera.screenToWorldX(p.x), this.camera.screenToWorldY(p.y));
        } else {
          this.autoFit = false;
          this.camera.omega = CAMERA.omegaDrag;
        }
      }
      if (!d.moved) return;
      if (d.mode === "particle") {
        this.sim!.moveGrab(this.camera.screenToWorldX(p.x), this.camera.screenToWorldY(p.y));
      } else {
        this.camera.holdPoint(d.worldX, d.worldY, p.x, p.y);
      }
      this.kick();
    });
    const end = (e: PointerEvent): void => {
      this.pointers.delete(e.pointerId);
      const d = this.drag;
      if (d.mode === "pinch") {
        if (this.pointers.size === 0) this.drag = { ...d, mode: "none" };
        return;
      }
      if (e.pointerId !== d.pointer) return;
      if (d.mode === "particle") this.sim!.release();
      this.camera.omega = CAMERA.omega;
      const click = !d.moved && e.type === "pointerup";
      this.drag = { ...d, mode: "none", pointer: -1 };
      if (click) {
        if (d.index >= 0) this.select(d.index, false);
        else this.clearSelection();
      }
      this.kick();
    };
    c.addEventListener("pointerup", end);
    c.addEventListener("pointercancel", end);
    c.addEventListener("pointerleave", (e) => {
      if (this.drag.mode === "none" && e.pointerType === "mouse") this.setHover(-1, 0, 0);
    });
    c.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        const p = this.local(e);
        const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? this.renderer!.height : 1;
        const delta = Math.max(-240, Math.min(240, e.deltaY * unit));
        this.autoFit = false;
        if (!this.paused) this.sim!.wake();
        this.camera.zoomAt(p.x, p.y, Math.exp(-delta * CAMERA.wheelZoom));
        this.kick();
      },
      { passive: false },
    );

    document.addEventListener("keydown", (e) => {
      const t = e.target as HTMLElement | null;
      const typing = !!t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA" || t.isContentEditable);
      if (e.key === "Escape") {
        this.clearSelection();
        this.ui.clearSearchBox();
        this.clearSearch();
        if (typing) t!.blur();
        return;
      }
      if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
      const r = this.renderer;
      if (!r) return;
      const step = CAMERA.keyPanFraction;
      let handled = true;
      switch (e.key) {
        case "/":
          this.ui.focusSearch();
          break;
        case "ArrowLeft":
          this.autoFit = false;
          this.camera.panBy(-r.width * step, 0);
          break;
        case "ArrowRight":
          this.autoFit = false;
          this.camera.panBy(r.width * step, 0);
          break;
        case "ArrowUp":
          this.autoFit = false;
          this.camera.panBy(0, -r.height * step);
          break;
        case "ArrowDown":
          this.autoFit = false;
          this.camera.panBy(0, r.height * step);
          break;
        case "+":
        case "=":
          this.autoFit = false;
          this.camera.zoomAt(r.width / 2, r.height / 2, 1.25);
          break;
        case "-":
        case "_":
          this.autoFit = false;
          this.camera.zoomAt(r.width / 2, r.height / 2, 0.8);
          break;
        case "0":
          this.fit();
          break;
        case "p":
          this.setPaused(!this.paused);
          break;
        default:
          handled = false;
      }
      if (handled) {
        e.preventDefault();
        if (!this.paused) this.sim?.wake();
        this.kick();
      }
    });
  }
}


restoreTheme();
const app = new App();
app.start().catch((err: unknown) => {
  app.ui.setFieldStatus(`Something failed while starting: ${err instanceof Error ? err.message : String(err)}`);
  console.error(err);
});
