// The work panel (left): grepper, results, executed SQL, inspector, lens switcher,
// audit tables, theme toggle; plus the key, tooltip and status over the field.
// Every piece of data is inserted as text (textContent / text nodes). innerHTML is
// never used.

import type { AuditResponse, BaselineAudit, ClaimEntry, GrepHit, GrepMode, GrepPart, GrepResponse, GrepScope, NodeRecord, NodeRef, RegionLevel } from "./data.js";
import type { Lens } from "./render.js";

export interface UiCallbacks {
  onSearch(q: string, mode: GrepMode, scope: GrepScope): void;
  onPickHit(hit: GrepHit): void;
  onSelectId(id: string): void;
  onLens(lens: Lens): void;
  onSemantic(on: boolean): void;
  onFit(): void;
  onTheme(): void;
  onAuditOpen(): void;
  onPause(): void;
  onAllLinks(on: boolean): void;
  onTreeSelect(id: string): void;
}

/** The hierarchy for the tree view: node indices, broader links both ways (primary parent first). */
export interface TreeModel {
  ids: readonly string[];
  labels: readonly string[];
  roots: readonly number[];
  children: ReadonlyArray<readonly number[]>;
  parents: ReadonlyArray<readonly number[]>;
}

export interface CoverageLegend {
  min: number;
  max: number;
  known: number;
  total: number;
  ramp: readonly string[];
}

function byId<T extends HTMLElement>(id: string, ctor: new () => T): T {
  const el = document.getElementById(id);
  if (!(el instanceof ctor)) throw new Error(`#${id} missing or not a ${ctor.name}`);
  return el;
}

/** Create an element with optional class and text. */
function h<K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, text?: string): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (text !== undefined) el.textContent = text;
  return el;
}

const SVG_NS = "http://www.w3.org/2000/svg";

/** A small inline-SVG swatch whose colours are CSS variables (so it follows the theme). */
function swatch(kind: "dot" | "ring" | "selected" | "hollow" | "line", color: string, opacity = 1): SVGSVGElement {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("width", kind === "line" ? "18" : "14");
  svg.setAttribute("height", "14");
  svg.setAttribute("aria-hidden", "true");
  svg.classList.add("swatch");
  const circle = (r: number): SVGCircleElement => {
    const c = document.createElementNS(SVG_NS, "circle");
    c.setAttribute("cx", "7");
    c.setAttribute("cy", "7");
    c.setAttribute("r", String(r));
    return c;
  };
  if (kind === "line") {
    const l = document.createElementNS(SVG_NS, "line");
    l.setAttribute("x1", "1");
    l.setAttribute("y1", "7");
    l.setAttribute("x2", "17");
    l.setAttribute("y2", "7");
    l.style.stroke = color;
    l.style.strokeOpacity = String(opacity);
    l.style.strokeWidth = "1.5";
    svg.append(l);
  } else if (kind === "dot") {
    const c = circle(4);
    c.style.fill = color;
    c.style.fillOpacity = String(opacity);
    svg.append(c);
  } else if (kind === "hollow") {
    const c = circle(3.6);
    c.style.fill = "none";
    c.style.stroke = color;
    c.style.strokeWidth = "1.25";
    svg.append(c);
  } else if (kind === "ring") {
    const dot = circle(3);
    dot.style.fill = "var(--ramp-mid)";
    const ring = circle(5.8);
    ring.style.fill = "none";
    ring.style.stroke = color;
    ring.style.strokeWidth = "1.5";
    svg.append(dot, ring);
  } else {
    const dot = circle(3);
    dot.style.fill = color;
    const ring = circle(6);
    ring.style.fill = "none";
    ring.style.stroke = color;
    ring.style.strokeWidth = "1.6";
    svg.append(dot, ring);
  }
  return svg;
}

export function renderParts(parts: readonly GrepPart[]): DocumentFragment {
  const frag = document.createDocumentFragment();
  for (const p of parts) {
    if (p.m) {
      const m = document.createElement("mark");
      m.textContent = p.t;
      frag.append(m);
    } else {
      frag.append(document.createTextNode(p.t));
    }
  }
  return frag;
}

/** Only http(s) links become anchors; anything else is shown as text. */
function safeHref(url: string): string | null {
  try {
    const u = new URL(url);
    return u.protocol === "http:" || u.protocol === "https:" ? u.href : null;
  } catch {
    return null;
  }
}

const fmt = new Intl.NumberFormat("en");

const BASELINE_NAMES: Record<string, string> = { population: "population", land_area: "land area", equal: "equal shares" };

type RrState = "over" | "under" | "neutral" | "none";

/** Above parity (interval entirely above 1x), below (entirely below), or cannot tell (it spans 1x). */
function rrState(lo: number | null, hi: number | null, rr: number | null): RrState {
  if (rr === null) return "none";
  if (lo !== null && lo > 1) return "over";
  if (hi !== null && hi < 1) return "under";
  return "neutral";
}

const RR_READING: Record<RrState, string> = {
  over: "above parity",
  under: "below parity",
  neutral: "cannot tell from parity",
  none: "no baseline value",
};
/** The same reading, short enough for a table cell. */
const RR_SHORT: Record<RrState, string> = { over: "above", under: "below", neutral: "spans 1×", none: "no baseline" };

function ratioText(r: number): string {
  if (r === 0) return "0×";
  const num = (v: number): string => (v >= 10 || Math.abs(v - Math.round(v)) < 1e-9 ? String(Math.round(v)) : v.toFixed(1));
  return r >= 1 ? `${num(r)}×` : `1/${num(1 / r)}×`;
}

function svgEl<K extends keyof SVGElementTagNameMap>(tag: K, attrs: Record<string, string | number>): SVGElementTagNameMap[K] {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  return el;
}

/**
 * Dot-and-interval chart of log2 representation ratios (dataviz: one axis, 2px interval lines,
 * r=4 dots with a 2px surface ring, recessive hairline grid, a parity reference line, text in
 * text tokens). Colour is the diverging pair plus a neutral and never works alone: the position
 * against the parity line says the same, and the table under the chart lists every value.
 */
function rrChart(level: RegionLevel, baseline: string, tip: HTMLElement): SVGSVGElement {
  const W = 340;
  const labelW = 122;
  const x0 = labelW + 8;
  const x1 = W - 10;
  const rowH = 20;
  const top = 22;
  const rows = level.groups;
  const H = top + rows.length * rowH + 26;
  let lo = 0;
  let hi = 0;
  for (const g of rows) {
    const v = g.vs[baseline];
    if (!v || v.rr === null || v.rr === 0) continue;
    if (v.rr_lo !== null && v.rr_lo > 0) lo = Math.min(lo, Math.log2(v.rr_lo));
    else if (v.log2_rr !== null) lo = Math.min(lo, v.log2_rr);
    if (v.rr_hi !== null && v.rr_hi > 0) hi = Math.max(hi, Math.log2(v.rr_hi));
  }
  lo = Math.max(-10, Math.floor(lo));
  hi = Math.min(14, Math.ceil(hi));
  if (hi - lo < 2) hi = lo + 2;
  const span = hi - lo;
  const step = span <= 6 ? 1 : span <= 12 ? 2 : 4;
  const x = (v: number): number => x0 + ((Math.min(hi, Math.max(lo, v)) - lo) / span) * (x1 - x0);
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "rr-chart", role: "group" });
  svg.setAttribute("aria-label", `Representation ratio against ${BASELINE_NAMES[baseline] ?? baseline} for ${rows.length} groups; the same values are in the table below.`);
  const axisY = top + rows.length * rowH;
  for (let t = Math.ceil(lo / step) * step; t <= hi; t += step) {
    svg.append(svgEl("line", { x1: x(t), x2: x(t), y1: top - 4, y2: axisY, class: t === 0 ? "rr-parity" : "rr-grid" }));
    const label = svgEl("text", { x: x(t), y: axisY + 14, class: "rr-tick", "text-anchor": "middle" });
    label.textContent = ratioText(2 ** t);
    svg.append(label);
  }
  const parity = svgEl("text", { x: x(0), y: top - 8, class: "rr-tick", "text-anchor": "middle" });
  parity.textContent = "parity";
  svg.append(parity);
  rows.forEach((g, k) => {
    const v = g.vs[baseline] ?? { baseline: null, rr: null, log2_rr: null, rr_lo: null, rr_hi: null };
    const cy = top + k * rowH + rowH / 2;
    const state = rrState(v.rr_lo, v.rr_hi, v.rr);
    const row = svgEl("g", { class: "rr-row", tabindex: 0 });
    const reading = v.rr === null ? "no baseline value" : v.rr === 0 ? "none tagged" :
      `${ratioText(v.rr)} its ${BASELINE_NAMES[baseline] ?? baseline} share (95%: ${v.rr_lo !== null ? ratioText(v.rr_lo) : "?"} to ${v.rr_hi !== null ? ratioText(v.rr_hi) : "?"}), ${RR_READING[state]}`;
    row.setAttribute("aria-label", `${g.label}: ${reading}`);
    row.append(svgEl("rect", { x: 0, y: cy - rowH / 2, width: W, height: rowH, class: "rr-hit" }));
    const name = svgEl("text", { x: labelW, y: cy + 4, class: "rr-label", "text-anchor": "end" });
    name.textContent = g.label.length > 20 ? `${g.label.slice(0, 19)}…` : g.label;
    row.append(name);
    if (v.rr === null || v.rr === 0) {
      const t = svgEl("text", { x: x0 + 2, y: cy + 4, class: "rr-none" });
      t.textContent = v.rr === null ? "no baseline value" : "none tagged";
      row.append(t);
    } else {
      const a = v.rr_lo !== null && v.rr_lo > 0 ? Math.log2(v.rr_lo) : lo;
      const b = v.rr_hi !== null && v.rr_hi > 0 ? Math.log2(v.rr_hi) : hi;
      row.append(svgEl("line", { x1: x(a), x2: x(b), y1: cy, y2: cy, class: `rr-ci rr-${state}` }));
      row.append(svgEl("circle", { cx: x(v.log2_rr ?? 0), cy, r: 4, class: `rr-dot rr-${state}` }));
    }
    const show = (): void => {
      tip.replaceChildren(h("strong", undefined, v.rr === null || v.rr === 0 ? (v.rr === null ? "no baseline" : "none tagged") : ratioText(v.rr)), h("span", undefined, g.label),
        h("span", undefined, `share ${(g.share * 100).toFixed(1)}% (95% ${(g.share_lo * 100).toFixed(1)}–${(g.share_hi * 100).toFixed(1)}%)`),
        h("span", undefined, `${BASELINE_NAMES[baseline] ?? baseline} share ${v.baseline === null ? "unknown" : `${(v.baseline * 100).toFixed(1)}%`}`),
        h("span", undefined, RR_READING[state]));
      tip.hidden = false;
    };
    row.addEventListener("pointerenter", show);
    row.addEventListener("focus", show);
    row.addEventListener("pointerleave", () => resetTip(tip));
    row.addEventListener("blur", () => resetTip(tip));
    svg.append(row);
  });
  return svg;
}

function resetTip(tip: HTMLElement): void {
  tip.replaceChildren(h("span", undefined, "Point at a row, or tab to it, for its numbers."));
}

const PRECISION_NAMES: Record<number, string> = {
  8: "decade",
  7: "century",
  6: "millennium",
  5: "ten millennia",
  4: "hundred thousand years",
  3: "million years",
  2: "ten million years",
  1: "hundred million years",
  0: "billion years",
};

/** A claim's value as text: things by label; dates, quantities and texts read from their JSON. */
export function claimValue(c: ClaimEntry): string {
  if (c.snak_type === "novalue") return "no value";
  if (c.snak_type === "somevalue") return "unknown value";
  if (c.object) return c.object_label || c.object;
  let v: unknown = null;
  if (c.value.startsWith("{")) {
    try {
      v = JSON.parse(c.value);
    } catch {
      v = null;
    }
  }
  if (v !== null && typeof v === "object") {
    const o = v as Record<string, unknown>;
    if (typeof o.time === "string") {
      // the source's own value, in its own calendar: 1 BCE is written -0001 there
      const m = /^([+-])(\d+)-(\d\d)-(\d\d)/.exec(o.time);
      const p = typeof o.precision === "number" ? o.precision : 9;
      if (m) {
        const bce = m[1] === "-";
        const year = bce ? `${Number(m[2])} BCE` : String(Number(m[2])).padStart(4, "0");
        const cal = typeof o.calendarmodel === "string" && o.calendarmodel.endsWith("Q1985786") ? " (Julian)" : "";
        if (p >= 11) return bce ? `${year}, ${m[3]}-${m[4]}${cal}` : `${year}-${m[3]}-${m[4]}${cal}`;
        if (p === 10) return bce ? `${year}, month ${m[3]}${cal}` : `${year}-${m[3]}${cal}`;
        if (p === 9) return year;
        return `${year} (${PRECISION_NAMES[p] ?? `precision ${p}`})`;
      }
    }
    if (typeof o.amount === "string") {
      const unit = typeof o.unit === "string" && o.unit !== "1" ? ` ${o.unit.replace(/^.*\//, "")}` : "";
      return `${o.amount.replace(/^\+/, "")}${unit}`;
    }
    if (typeof o.text === "string") return `${o.text}${typeof o.language === "string" ? ` (${o.language})` : ""}`;
    if (typeof o.latitude === "number" && typeof o.longitude === "number") return `${o.latitude}, ${o.longitude}`;
  }
  return c.value;
}

export class Ui {
  readonly source = byId("source", HTMLElement);
  readonly q = byId("q", HTMLInputElement);
  readonly mode = byId("mode", HTMLSelectElement);
  readonly scope = byId("scope", HTMLSelectElement);
  private readonly form = byId("search-form", HTMLFormElement);
  private readonly searchStatus = byId("search-status", HTMLElement);
  private readonly results = byId("results", HTMLOListElement);
  private readonly sql = byId("sql", HTMLDetailsElement);
  private readonly sqlText = byId("sql-text", HTMLElement);
  private readonly inspector = byId("inspector", HTMLElement);
  private readonly audit = byId("audit", HTMLDetailsElement);
  private readonly auditBody = byId("audit-body", HTMLElement);
  private readonly key = byId("key", HTMLElement);
  private readonly tooltip = byId("tooltip", HTMLElement);
  private readonly fieldStatus = byId("field-status", HTMLElement);
  private readonly themeButton = byId("theme-toggle", HTMLButtonElement);
  private readonly panelToggle = byId("panel-toggle", HTMLButtonElement);
  private readonly panelBody = byId("panel-body", HTMLElement);
  private readonly semantic = byId("semantic", HTMLInputElement);
  private readonly pauseButton = byId("pause", HTMLButtonElement);
  private readonly allLinks = byId("all-links", HTMLInputElement);
  private readonly treePanel = byId("tree-panel", HTMLDetailsElement);
  private readonly tree = byId("tree", HTMLUListElement);
  private treeModel: TreeModel | null = null;
  /** The node to reveal once the tree is opened. */
  private pendingReveal = -1;
  private offline = false;
  private hits: GrepHit[] = [];
  /** Baseline audit chart state (kept across re-renders). */
  private rrBaseline = "population";
  private rrLevel: "regions" | "subregions" = "regions";

  constructor(cb: UiCallbacks) {
    const fire = (): void => cb.onSearch(this.q.value, this.mode.value as GrepMode, this.scope.value as GrepScope);
    this.form.addEventListener("submit", (e) => {
      e.preventDefault();
      fire();
    });
    this.q.addEventListener("input", fire);
    this.mode.addEventListener("change", fire);
    this.scope.addEventListener("change", fire);
    this.results.addEventListener("click", (e) => {
      const btn = (e.target as Element | null)?.closest("button[data-hit]");
      if (!(btn instanceof HTMLButtonElement)) return;
      const hit = this.hits[Number(btn.dataset.hit)];
      if (hit) cb.onPickHit(hit);
    });
    const onIdClick = (e: Event): void => {
      const btn = (e.target as Element | null)?.closest("button[data-id]");
      if (btn instanceof HTMLButtonElement && btn.dataset.id) cb.onSelectId(btn.dataset.id);
    };
    this.inspector.addEventListener("click", onIdClick);
    this.auditBody.addEventListener("click", onIdClick);
    for (const radio of document.querySelectorAll<HTMLInputElement>('input[name="lens"]')) {
      radio.addEventListener("change", () => {
        if (radio.checked) cb.onLens(radio.value === "coverage" ? "coverage" : "structure");
      });
    }
    this.semantic.addEventListener("change", () => cb.onSemantic(this.semantic.checked));
    this.allLinks.addEventListener("change", () => cb.onAllLinks(this.allLinks.checked));
    this.pauseButton.addEventListener("click", () => cb.onPause());
    this.treePanel.addEventListener("toggle", () => {
      if (!this.treePanel.open) return;
      this.renderTreeRoots();
      if (this.pendingReveal >= 0) this.revealInTree(this.pendingReveal);
    });
    this.tree.addEventListener("click", (e) => {
      const li = (e.target as Element | null)?.closest('li[role="treeitem"]');
      if (!(li instanceof HTMLLIElement)) return;
      e.stopPropagation();
      if ((e.target as Element).closest(".twisty")) {
        this.expand(li, li.getAttribute("aria-expanded") !== "true");
        this.focusItem(li);
        return;
      }
      this.focusItem(li);
      this.markSelected(li);
      cb.onTreeSelect(this.treeModel!.ids[Number(li.dataset.i)]!);
    });
    this.tree.addEventListener("keydown", (e) => this.onTreeKey(e, cb));
    byId("fit", HTMLButtonElement).addEventListener("click", () => cb.onFit());
    this.themeButton.addEventListener("click", () => cb.onTheme());
    this.audit.addEventListener("toggle", () => {
      if (this.audit.open) cb.onAuditOpen();
    });
    this.panelToggle.addEventListener("click", () => this.setPanelOpen(this.panelBody.hidden !== false));
    // Narrow screens stack the panel above the field: start with its lower part folded so
    // the field is in view; the search stays open. Wide screens always show everything.
    const narrow = window.matchMedia("(max-width: 760px)");
    this.setPanelOpen(!narrow.matches);
    narrow.addEventListener("change", () => this.setPanelOpen(!narrow.matches));
  }

  /** WCAG 2.2.2: a visible, keyboard-reachable way to stop all motion. */
  setPaused(on: boolean): void {
    this.pauseButton.setAttribute("aria-pressed", String(on));
    this.pauseButton.textContent = on ? "Resume motion" : "Pause motion";
  }

  // ------------------------------------------------------------ tree view (ARIA APG tree, lazy)

  setTree(model: TreeModel): void {
    this.treeModel = model;
    this.tree.replaceChildren();
    if (this.treePanel.open) this.renderTreeRoots();
  }

  private renderTreeRoots(): void {
    const m = this.treeModel;
    if (!m || this.tree.childElementCount > 0) return;
    const items = m.roots.map((i, k) => this.treeItem(i, 1, k + 1, m.roots.length));
    this.tree.append(...items);
    if (items[0]) items[0].tabIndex = 0;
  }

  private treeItem(i: number, level: number, pos: number, size: number): HTMLLIElement {
    const m = this.treeModel!;
    const li = h("li", "tree-item");
    li.setAttribute("role", "treeitem");
    li.setAttribute("aria-level", String(level));
    li.setAttribute("aria-posinset", String(pos));
    li.setAttribute("aria-setsize", String(size));
    li.setAttribute("aria-selected", "false");
    li.tabIndex = -1;
    li.dataset.i = String(i);
    const kids = m.children[i]!.length;
    const row = h("span", "tree-row");
    const twisty = h("span", "twisty", kids > 0 ? "▸" : "");
    twisty.setAttribute("aria-hidden", "true");
    row.append(twisty, h("span", "tree-label", m.labels[i]!));
    if (kids > 0) {
      li.setAttribute("aria-expanded", "false");
      row.append(h("span", "tree-count", String(kids)));
    }
    li.append(row);
    return li;
  }

  private expand(li: HTMLLIElement, open: boolean): void {
    if (!li.hasAttribute("aria-expanded")) return;
    li.setAttribute("aria-expanded", String(open));
    const twisty = li.querySelector(":scope > .tree-row > .twisty");
    if (twisty) twisty.textContent = open ? "▾" : "▸";
    let group = li.querySelector<HTMLUListElement>(":scope > ul");
    if (open && !group) {
      const m = this.treeModel!;
      const kids = m.children[Number(li.dataset.i)]!;
      const level = Number(li.getAttribute("aria-level")) + 1;
      const g = h("ul", "tree-group");
      g.setAttribute("role", "group");
      kids.forEach((c, k) => g.append(this.treeItem(c, level, k + 1, kids.length)));
      li.append(g);
      group = g;
    }
    if (group) group.hidden = !open;
  }

  private visibleItems(): HTMLLIElement[] {
    return [...this.tree.querySelectorAll<HTMLLIElement>('li[role="treeitem"]')].filter((li) => !li.closest("ul[hidden]"));
  }

  private focusItem(li: HTMLLIElement): void {
    for (const x of this.tree.querySelectorAll<HTMLLIElement>('li[tabindex="0"]')) x.tabIndex = -1;
    li.tabIndex = 0;
    li.focus();
  }

  private markSelected(li: HTMLLIElement): void {
    for (const x of this.tree.querySelectorAll('li[aria-selected="true"]')) x.setAttribute("aria-selected", "false");
    li.setAttribute("aria-selected", "true");
  }

  private onTreeKey(e: KeyboardEvent, cb: UiCallbacks): void {
    const li = (e.target as Element | null)?.closest('li[role="treeitem"]');
    if (!(li instanceof HTMLLIElement)) return;
    const items = this.visibleItems();
    const k = items.indexOf(li);
    let handled = true;
    switch (e.key) {
      case "ArrowDown":
        if (k < items.length - 1) this.focusItem(items[k + 1]!);
        break;
      case "ArrowUp":
        if (k > 0) this.focusItem(items[k - 1]!);
        break;
      case "ArrowRight":
        if (li.getAttribute("aria-expanded") === "false") this.expand(li, true);
        else if (li.getAttribute("aria-expanded") === "true") {
          const first = li.querySelector<HTMLLIElement>(':scope > ul > li[role="treeitem"]');
          if (first) this.focusItem(first);
        }
        break;
      case "ArrowLeft":
        if (li.getAttribute("aria-expanded") === "true") this.expand(li, false);
        else {
          const parent = li.parentElement?.closest<HTMLLIElement>('li[role="treeitem"]');
          if (parent) this.focusItem(parent);
        }
        break;
      case "Home":
        if (items[0]) this.focusItem(items[0]);
        break;
      case "End":
        if (items.length > 0) this.focusItem(items[items.length - 1]!);
        break;
      case "Enter":
      case " ":
        this.markSelected(li);
        cb.onTreeSelect(this.treeModel!.ids[Number(li.dataset.i)]!);
        break;
      default:
        handled = false;
    }
    if (handled) {
      e.preventDefault();
      e.stopPropagation(); // arrows here move in the tree, not the camera
    }
  }

  /** Expand the path to a node (primary parents) and mark it selected; deferred while the tree is closed. */
  revealInTree(i: number): void {
    const m = this.treeModel;
    this.pendingReveal = i;
    if (!m || !this.treePanel.open) return;
    this.renderTreeRoots();
    const path = [i];
    const seen = new Set(path);
    for (let cur = i; (m.parents[cur]?.length ?? 0) > 0; ) {
      cur = m.parents[cur]![0]!;
      if (seen.has(cur)) break;
      seen.add(cur);
      path.unshift(cur);
    }
    let container: Element = this.tree;
    let li: HTMLLIElement | null = null;
    for (let k = 0; k < path.length; k++) {
      li = container.querySelector<HTMLLIElement>(`:scope > li[data-i="${path[k]}"]`);
      if (!li) return;
      if (k < path.length - 1) {
        this.expand(li, true);
        container = li.querySelector(":scope > ul")!;
      }
    }
    if (!li) return;
    this.markSelected(li);
    for (const x of this.tree.querySelectorAll<HTMLLIElement>('li[tabindex="0"]')) x.tabIndex = -1;
    li.tabIndex = 0;
    li.scrollIntoView({ block: "nearest" });
  }

  setPanelOpen(open: boolean): void {
    this.panelBody.hidden = !open;
    this.panelToggle.setAttribute("aria-expanded", String(open));
    this.panelToggle.textContent = open ? "Hide panel" : "Show panel";
  }

  // ------------------------------------------------------------ status

  setSource(text: string, detail = ""): void {
    this.source.textContent = text;
    this.source.title = detail;
  }

  setThemeLabel(current: "light" | "dark"): void {
    this.themeButton.textContent = current === "dark" ? "Light theme" : "Dark theme";
    this.themeButton.setAttribute("aria-label", `Switch to the ${current === "dark" ? "light" : "dark"} theme`);
  }

  setFieldStatus(text: string | null): void {
    this.fieldStatus.hidden = text === null;
    this.fieldStatus.textContent = text ?? "";
  }

  /** Offline: the grepper falls back to label search and says so. */
  setOffline(offline: boolean): void {
    this.offline = offline;
    this.mode.disabled = offline;
    this.scope.disabled = offline;
    this.q.placeholder = offline ? "Search labels (offline)" : "Grep the catalogue";
    if (offline) this.setSearchStatus("offline: label search only (API not reachable)", "offline");
    else this.setSearchStatus("", null);
  }

  private setSearchStatus(text: string, tone: "offline" | "error" | null): void {
    this.searchStatus.textContent = text;
    this.searchStatus.dataset.tone = tone ?? "";
  }

  focusSearch(): void {
    this.q.focus();
    this.q.select();
  }

  clearSearchBox(): void {
    this.q.value = "";
  }

  // ------------------------------------------------------------ results

  showSearching(q: string): void {
    this.setSearchStatus(`Searching for “${q}”…`, null);
  }

  clearResults(): void {
    this.hits = [];
    this.results.replaceChildren();
    this.sql.hidden = true;
    this.sqlText.textContent = "";
    this.setOffline(this.offline);
  }

  showSearchError(message: string, resp: GrepResponse | null): void {
    this.hits = [];
    this.results.replaceChildren();
    this.setSearchStatus(message, "error");
    this.showSql(resp);
  }

  private showSql(resp: GrepResponse | null): void {
    if (!resp || resp.sql.length === 0) {
      this.sql.hidden = true;
      this.sqlText.textContent = "";
      return;
    }
    this.sql.hidden = false;
    const summary = this.sql.querySelector("summary");
    if (summary) summary.textContent = `SQL (${resp.sql.length} statement${resp.sql.length === 1 ? "" : "s"}, ${resp.elapsed_ms} ms)`;
    this.sqlText.textContent = resp.sql.join(";\n\n");
  }

  /** Render hits from their `parts` (text nodes; <mark> for matches). */
  showResults(resp: GrepResponse, inField: (id: string) => boolean): void {
    this.hits = resp.hits;
    const items = resp.hits.map((hit, k) => {
      const li = h("li");
      const btn = h("button", "hit");
      btn.type = "button";
      btn.dataset.hit = String(k);
      const head = h("span", "hit-head");
      head.append(h("span", "hit-title", hit.title || hit.target), h("span", "hit-type", hit.type));
      const snippet = h("span", "hit-snippet");
      snippet.append(renderParts(hit.parts));
      const where = hit.concepts.find(inField);
      const meta = h("span", "hit-id", where ? hit.target : `${hit.target} (not in the field)`);
      btn.append(head, snippet, meta);
      li.append(btn);
      return li;
    });
    this.results.replaceChildren(...items);
    const shown = resp.hits.length;
    const total = resp.total;
    const prefix = this.offline ? "offline: label search only (API not reachable) · " : "";
    const count = total > shown ? `${fmt.format(shown)} of ${fmt.format(total)} hits` : `${fmt.format(shown)} hit${shown === 1 ? "" : "s"}`;
    this.setSearchStatus(`${prefix}${count}${this.offline ? "" : ` · ${resp.elapsed_ms} ms`}`, this.offline ? "offline" : null);
    this.showSql(resp);
  }

  // ------------------------------------------------------------ inspector

  clearInspector(): void {
    this.inspector.replaceChildren(h("p", "hint", "Click a particle or a result to inspect it."));
  }

  showInspectorLoading(label: string, id: string): void {
    this.inspector.replaceChildren(this.inspectorHead(label, id, ""), h("p", "hint", "Loading the record…"));
  }

  showInspectorError(label: string, id: string, message: string): void {
    this.inspector.replaceChildren(this.inspectorHead(label, id, ""), h("p", "status error", message));
  }

  private inspectorHead(label: string, id: string, extra: string): HTMLElement {
    const head = h("header", "inspector-head");
    head.append(h("h2", undefined, label || id), h("p", "node-id", extra ? `${id} · ${extra}` : id));
    return head;
  }

  private refList(title: string, refs: readonly NodeRef[], inField: (id: string) => boolean): HTMLElement {
    const sec = h("section", "rel");
    sec.append(h("h3", undefined, `${title} (${refs.length})`));
    if (refs.length === 0) {
      sec.append(h("p", "none", "none"));
      return sec;
    }
    const ul = h("ul", "chips");
    for (const r of refs) {
      const li = h("li");
      if (inField(r.id)) {
        const b = h("button", "link", r.label || r.id);
        b.type = "button";
        b.dataset.id = r.id;
        b.title = r.id;
        li.append(b);
      } else {
        li.append(h("span", "plain", r.label || r.id));
        li.title = r.id;
      }
      ul.append(li);
    }
    sec.append(ul);
    return sec;
  }

  private collapsible(title: string, count: number, body: () => HTMLElement, open = false): HTMLElement {
    const d = h("details", "sub");
    d.open = open;
    d.append(h("summary", undefined, `${title} (${count})`));
    if (count === 0) d.append(h("p", "none", "none"));
    else d.append(body());
    return d;
  }

  showNode(rec: NodeRecord, inField: (id: string) => boolean, offlineNote: string | null): void {
    const parts: HTMLElement[] = [];
    parts.push(this.inspectorHead(rec.label, rec.id, [rec.scheme, rec.status].filter(Boolean).join(" · ")));
    if (offlineNote) parts.push(h("p", "status offline", offlineNote));
    if (rec.scope_note) parts.push(h("p", "scope-note", rec.scope_note));
    const facts = h("dl", "facts");
    const fact = (k: string, v: string): void => {
      facts.append(h("dt", undefined, k), h("dd", undefined, v));
    };
    fact("Coverage", rec.langs === null ? "unknown (not reconciled)" : `${fmt.format(rec.langs)} Wikipedia language editions`);
    if (!offlineNote) fact("Labels", `${fmt.format(rec.labels.length)} in ${fmt.format(rec.n_label_langs)} languages`);
    if (rec.code) fact("Code", rec.code);
    parts.push(facts);

    parts.push(this.refList("Broader", rec.broader, inField));
    parts.push(this.refList("Narrower", rec.narrower, inField));
    parts.push(this.refList("Related", rec.related, inField));

    parts.push(
      this.collapsible("Mappings", rec.mappings.length, () => {
        const ul = h("ul", "rows");
        for (const m of rec.mappings) {
          const li = h("li");
          if (inField(m.id)) {
            const b = h("button", "link", m.label || m.id);
            b.type = "button";
            b.dataset.id = m.id;
            li.append(b);
          } else li.append(h("span", "plain", m.label || m.id));
          li.append(h("span", "meta", ` ${m.id} · ${[m.relation, m.status].filter(Boolean).join(" · ")}`));
          if (m.decided_by === "AI agent") li.append(h("p", "badge agent", "Proposed by an AI agent; no person has reviewed it yet."));
          else if (m.decided_by === "human") li.append(h("p", "badge human", `Decided by ${m.reviewer}.`));
          else if (m.decided_by) li.append(h("p", "badge", "Authored in the seed files."));
          if (m.method) li.append(h("p", "meta", `method: ${m.method}${m.note ? ` · ${m.note}` : ""}`));
          ul.append(li);
        }
        return ul;
      }, rec.mappings.length > 0 && rec.mappings.length <= 6),
    );
    if (rec.reviews.length > 0) {
      parts.push(
        this.collapsible("Reviews", rec.reviews.length, () => {
          const ul = h("ul", "rows");
          for (const r of rec.reviews) {
            const li = h("li");
            li.append(h("span", "plain", `${r.decision}${r.relation ? ` as ${r.relation}` : ""} · ${r.reviewer}${r.reviewer_kind === "agent" ? " (AI agent, not decisive)" : ""}`));
            li.append(h("span", "meta", ` ${r.decided_at.slice(0, 10)}${r.perspective ? ` · perspective: ${r.perspective}` : ""} · ${r.target}`));
            if (r.rationale) li.append(h("p", "excerpt", r.rationale));
            ul.append(li);
          }
          return ul;
        }, true),
      );
    }

    if (!offlineNote) {
      // Labels grouped by language, collapsed (there can be hundreds).
      parts.push(
        this.collapsible(`Labels in ${fmt.format(rec.n_label_langs || new Set(rec.labels.map((l) => l.lang)).size)} languages`, rec.labels.length, () => {
          const groups = new Map<string, typeof rec.labels>();
          for (const l of rec.labels) (groups.get(l.lang) ?? groups.set(l.lang, []).get(l.lang)!).push(l);
          const dl = h("dl", "labels");
          for (const lang of [...groups.keys()].sort()) {
            dl.append(h("dt", undefined, lang));
            const dd = h("dd");
            groups.get(lang)!.forEach((l, k) => {
              if (k > 0) dd.append(document.createTextNode(" · "));
              dd.append(h("span", l.kind === "pref" ? "pref" : "alt", l.text));
              if (l.kind && l.kind !== "pref") dd.append(h("span", "meta", ` (${l.kind})`));
            });
            dl.append(dd);
          }
          return dl;
        }),
      );
      parts.push(
        this.collapsible("Documents", rec.documents.length, () => {
          const ul = h("ul", "rows docs");
          for (const d of rec.documents) {
            const li = h("li");
            const href = safeHref(d.url);
            if (href) {
              const a = h("a", undefined, d.title || d.id);
              a.href = href;
              a.target = "_blank";
              a.rel = "noopener noreferrer";
              li.append(a);
            } else li.append(h("span", "plain", d.title || d.id));
            li.append(h("span", "meta", ` · ${[d.lang, d.license || "license unknown"].filter(Boolean).join(" · ")}`));
            if (d.excerpt) li.append(h("p", "excerpt", d.excerpt));
            const src = h("p", "meta");
            src.append(document.createTextNode(href ? "Source: " : "Source (not a web link): "));
            src.append(h("span", "mono", href ?? d.url ?? d.id));
            if (d.sha512) src.append(document.createTextNode(` · sha512 ${d.sha512.slice(0, 16)}…`));
            src.title = d.sha512;
            li.append(src);
            ul.append(li);
          }
          return ul;
        }, rec.documents.length > 0 && rec.documents.length <= 3),
      );
      const claimRows = (list: readonly ClaimEntry[]): HTMLElement => {
        const ul = h("ul", "rows claims");
        for (const c of list) {
          const li = h("li", c.rank === "deprecated" ? "deprecated" : undefined);
          li.append(h("span", "plain", `${c.predicate_label || c.predicate} → ${claimValue(c)}`));
          const meta = [
            c.rank && c.rank !== "normal" ? `${c.rank} rank` : "",
            c.epistemic && c.epistemic !== "epistemic/attributed" ? c.epistemic.replace(/^epistemic\//, "") : "",
            c.valid_from || c.valid_to ? `${c.valid_from || "…"} – ${c.valid_to || "…"}` : "",
            c.qualifiers ? `${c.qualifiers} qualifier${c.qualifiers === 1 ? "" : "s"}` : "",
            c.statement_id ? (c.sourced ? `${c.references} reference${c.references === 1 ? "" : "s"}` : c.references ? "only imported-from references" : "no reference") : "",
          ].filter(Boolean);
          if (meta.length > 0) li.append(h("span", "meta", ` ${meta.join(" · ")}`));
          li.title = [c.statement_id ? `statement ${c.statement_id}` : "", c.pointer ? `at ${c.pointer}` : "", c.source ? `in ${c.source}` : ""].filter(Boolean).join("\n");
          ul.append(li);
        }
        return ul;
      };
      const relations = rec.claims.filter((c) => c.object || (c.snak_type !== "value" && c.datatype !== "external-id" && /item|property/.test(c.datatype)));
      const identifiers = rec.claims.filter((c) => c.datatype === "external-id");
      const values = rec.claims.filter((c) => !relations.includes(c) && !identifiers.includes(c));
      parts.push(this.collapsible("Claims: relations", relations.length, () => claimRows(relations), relations.length > 0 && relations.length <= 12));
      parts.push(this.collapsible("Claims: values", values.length, () => claimRows(values)));
      parts.push(this.collapsible("Claims: identifiers in other databases", identifiers.length, () => claimRows(identifiers)));
    }
    parts.push(
      this.collapsible("Neighbours", rec.neighbors.length, () => {
        const ul = h("ul", "rows");
        for (const nb of rec.neighbors) {
          const li = h("li");
          if (inField(nb.id)) {
            const b = h("button", "link", nb.label || nb.id);
            b.type = "button";
            b.dataset.id = nb.id;
            li.append(b);
          } else li.append(h("span", "plain", nb.label || nb.id));
          li.append(h("span", "meta", ` ${nb.score.toFixed(2)}${nb.model ? ` · ${nb.model}` : ""}`));
          ul.append(li);
        }
        return ul;
      }),
    );
    if (!offlineNote) {
      parts.push(
        this.collapsible("Provenance", rec.provenance.length, () => {
          const ul = h("ul", "rows");
          for (const p of rec.provenance) {
            const li = h("li");
            li.append(h("span", "mono", p.source));
            li.append(h("span", "meta", ` · ${p.kind}${p.sha512 ? ` · sha512 ${p.sha512.slice(0, 16)}…` : ""}`));
            li.title = p.sha512;
            ul.append(li);
          }
          return ul;
        }),
      );
    }
    this.inspector.replaceChildren(...parts);
  }

  // ------------------------------------------------------------ lens and key

  setLens(lens: Lens): void {
    for (const radio of document.querySelectorAll<HTMLInputElement>('input[name="lens"]')) radio.checked = radio.value === lens;
  }

  setSemantic(on: boolean): void {
    this.semantic.checked = on;
  }

  /** The key always explains the marks of the current lens. */
  renderKey(lens: Lens, legend: CoverageLegend, showSemantic: boolean): void {
    const rows: HTMLElement[] = [];
    const row = (mark: SVGSVGElement | null, text: string): HTMLElement => {
      const r = h("div", "key-row");
      if (mark) r.append(mark);
      r.append(h("span", undefined, text));
      return r;
    };
    if (lens === "structure") {
      rows.push(h("p", "key-title", "Structure"));
      rows.push(row(swatch("dot", "var(--ink)"), "concept · size ∝ descendants + documents"));
      rows.push(row(swatch("dot", "var(--accent)"), "search hit / hover"));
      rows.push(row(swatch("selected", "var(--accent-2)"), "selected (always labelled)"));
      rows.push(row(swatch("line", "var(--ink)", 0.4), "broader (hierarchy)"));
      rows.push(row(swatch("line", "var(--ink)", 0.2), `${showSemantic ? "related · mapping · semantic" : "related · mapping"} (between clusters: on hover or selection, or All links)`));
      rows.push(h("p", "key-note", "Domains: cluster + label at its centre, not colour."));
    } else {
      rows.push(h("p", "key-title", "Coverage: Wikipedia language editions"));
      const bar = h("div", "ramp");
      bar.setAttribute("role", "img");
      bar.setAttribute("aria-label", `Sequential scale from ${legend.min} to ${legend.max} language editions, log scale`);
      for (const c of legend.ramp) {
        const step = h("span", "ramp-step");
        step.style.background = c;
        bar.append(step);
      }
      // numbers beside the colours (colour is never the only carrier): evenly spaced in the ramp's
      // own log(1 + editions) space, so each number sits where its colour is
      const lo = Math.log1p(legend.min);
      const hi = Math.log1p(legend.max);
      const ticks = h("div", "ramp-ticks");
      for (const t of [0, 0.25, 0.5, 0.75, 1]) ticks.append(h("span", undefined, fmt.format(Math.round(Math.expm1(lo + t * (hi - lo))))));
      rows.push(bar, ticks, h("p", "ramp-scale", "editions, log scale"));
      rows.push(row(swatch("hollow", "var(--muted)"), `no data (${fmt.format(legend.total - legend.known)} of ${fmt.format(legend.total)})`));
      rows.push(row(swatch("ring", "var(--ink)"), "search hit / hover (ink ring)"));
      rows.push(row(swatch("selected", "var(--accent-2)"), "selected (always labelled)"));
    }
    this.key.replaceChildren(...rows);
  }

  keyRect(): DOMRect {
    return this.key.getBoundingClientRect();
  }

  // ------------------------------------------------------------ tooltip

  showTooltip(x: number, y: number, title: string, lines: readonly string[], fieldW: number, fieldH: number): void {
    const tip = this.tooltip;
    tip.replaceChildren(h("strong", undefined, title), ...lines.map((l) => h("span", undefined, l)));
    tip.hidden = false;
    const w = tip.offsetWidth;
    const ht = tip.offsetHeight;
    let left = x + 14;
    let top = y + 14;
    if (left + w > fieldW - 8) left = Math.max(8, x - w - 14);
    if (top + ht > fieldH - 8) top = Math.max(8, y - ht - 14);
    tip.style.left = `${left}px`;
    tip.style.top = `${top}px`;
  }

  hideTooltip(): void {
    this.tooltip.hidden = true;
  }

  // ------------------------------------------------------------ audit

  auditIsOpen(): boolean {
    return this.audit.open;
  }

  showAuditLoading(): void {
    this.auditBody.replaceChildren(h("p", "hint", "Loading the audit…"));
  }

  showAuditError(message: string): void {
    this.auditBody.replaceChildren(h("p", "status error", message));
  }

  showAudit(a: AuditResponse, offline: boolean, inField: (id: string) => boolean): void {
    const out: HTMLElement[] = [];
    if (offline) out.push(h("p", "status offline", "offline: computed from the loaded graph (API not reachable)"));
    else if (a.generated_at) out.push(h("p", "meta", `Generated ${a.generated_at}`));
    const idCell = (id: string, label: string): HTMLElement => {
      if (inField(id)) {
        const b = h("button", "link", label || id);
        b.type = "button";
        b.dataset.id = id;
        b.title = id;
        return b;
      }
      const s = h("span", undefined, label || id);
      s.title = id;
      return s;
    };
    const table = (caption: string, head: string[], rows: Array<Array<string | HTMLElement>>, numeric: boolean[]): HTMLElement => {
      const wrap = h("div", "table-wrap");
      const t = h("table");
      t.append(h("caption", undefined, caption));
      const thead = h("thead");
      const tr = h("tr");
      head.forEach((c, k) => {
        const th = h("th", numeric[k] ? "num" : undefined, c);
        th.scope = "col";
        tr.append(th);
      });
      thead.append(tr);
      const tbody = h("tbody");
      for (const r of rows) {
        const row = h("tr");
        r.forEach((c, k) => {
          const td = h("td", numeric[k] ? "num" : undefined);
          if (typeof c === "string") td.textContent = c;
          else td.append(c);
          row.append(td);
        });
        tbody.append(row);
      }
      t.append(thead, tbody);
      wrap.append(t);
      return wrap;
    };
    const n = (v: number | null): string => (v === null ? "—" : fmt.format(Math.round(v * 10) / 10));
    if (a.baseline) out.push(this.baselineSection(a.baseline, idCell, table));
    if (a.domains.length > 0) {
      out.push(
        table(
          "Domains (langs: Wikipedia language editions per concept)",
          ["Domain", "Concepts", offline ? "Known" : "Reconciled", "Docs", "Median", "Min"],
          a.domains.map((d) => [idCell(d.id, d.label), n(d.concepts), n(d.reconciled), n(d.docs), n(d.median_langs), d.min_langs_id ? idCell(d.min_langs_id, n(d.min_langs)) : n(d.min_langs)]),
          [false, true, true, true, true, true],
        ),
      );
    }
    if (a.thinnest.length > 0) {
      out.push(table("Thinnest coverage", ["Concept", "Langs"], a.thinnest.map((t) => [idCell(t.id, t.label), n(t.langs)]), [false, true]));
    }
    if (a.regions.length > 0) {
      out.push(table("Regions (where facet)", ["Region", "Tagged"], a.regions.map((r) => [idCell(r.id, r.label), n(r.tagged)]), [false, true]));
    }
    if (a.label_languages.length > 0) {
      out.push(table("Label languages", ["Language", "Concepts"], a.label_languages.map((l) => [l.lang, n(l.concepts)]), [false, true]));
    }
    if (a.notes.length > 0) {
      const ul = h("ul", "notes");
      for (const note of a.notes) ul.append(h("li", undefined, note));
      out.push(ul);
    }
    if (out.length === 0) out.push(h("p", "none", "The audit is empty."));
    this.auditBody.replaceChildren(...out);
  }

  private baselineSection(
    b: BaselineAudit,
    idCell: (id: string, label: string) => HTMLElement,
    table: (caption: string, head: string[], rows: Array<Array<string | HTMLElement>>, numeric: boolean[]) => HTMLElement,
  ): HTMLElement {
    const sec = h("section", "baseline-audit");
    sec.append(h("h3", undefined, "Where the catalogue looks: regions against declared baselines"));
    const controls = h("div", "chart-controls");
    const select = (label: string, options: Array<[string, string]>, value: string, onChange: (v: string) => void): HTMLElement => {
      const l = h("label", undefined, `${label} `);
      const s = h("select");
      for (const [v, t] of options) {
        const o = h("option", undefined, t);
        o.value = v;
        s.append(o);
      }
      s.value = value;
      s.addEventListener("change", () => onChange(s.value));
      l.append(s);
      return l;
    };
    const body = h("div", "chart-body");
    const render = (): void => {
      const level = this.rrLevel === "regions" ? b.regions : b.subregions;
      if (!level) {
        body.replaceChildren(h("p", "none", "No stored run for this level."));
        return;
      }
      const wrap = h("div", "chart-wrap");
      // the readout sits under the chart, never over the marks it describes
      const tip = h("div", "chart-tip");
      tip.setAttribute("role", "status");
      resetTip(tip);
      wrap.append(rrChart(level, this.rrBaseline, tip), tip);
      const key = h("div", "chart-key");
      for (const [state, text] of [["over", "above parity: the whole interval is above 1×"], ["under", "below parity: the whole interval is below 1×"], ["neutral", "cannot tell: the interval includes 1×"]] as const) {
        const k = h("span", "chart-key-item");
        const sw = svgEl("svg", { width: 14, height: 10, "aria-hidden": "true" });
        sw.append(svgEl("line", { x1: 1, x2: 13, y1: 5, y2: 5, class: `rr-ci rr-${state}` }), svgEl("circle", { cx: 7, cy: 5, r: 3.2, class: `rr-dot rr-${state}` }));
        k.append(sw, h("span", undefined, text));
        key.append(k);
      }
      const d = level.distribution[this.rrBaseline];
      const cov = level.coverage[this.rrBaseline];
      const lines: string[] = [
        `${fmt.format(level.n)} concepts carry a place, each split evenly over its ${this.rrLevel === "regions" ? "regions" : "sub-regions"}; ${fmt.format(level.untagged)} have none${level.tagged_above_level ? `, ${fmt.format(level.tagged_above_level)} only above this level` : ""}. Dot: ratio of the catalogue's share to the baseline's; line: 95% Wilson interval.`,
      ];
      if (d) lines.push(`Jensen–Shannon divergence ${d.jsd_bits.toFixed(3)} bits (bootstrap 95% ${d.jsd_lo?.toFixed(3) ?? "?"}–${d.jsd_hi?.toFixed(3) ?? "?"}), ${d.exceeds_null ? "beyond" : "within"} what random sampling from the baseline gives (95th percentile ${d.null_p95?.toFixed(3) ?? "?"}). Gini of the ratios ${d.gini_rr?.toFixed(2) ?? "?"}.`);
      if (cov) lines.push(`Baseline: World Bank ${this.rrBaseline === "population" ? "population" : "land area"} ${cov.as_of}; ${fmt.format(cov.with_value)} of ${fmt.format(cov.areas)} UN M49 areas have a value.`);
      if (this.rrBaseline === "equal") lines.push("Equal shares: every group gets 1/K, whatever its size.");
      lines.push("Which baseline is fair is a choice, not a fact: read the three together, never as one score.");
      const notes = h("ul", "notes");
      for (const l of lines) notes.append(h("li", undefined, l));
      const rows = level.groups.map((g) => {
        const v = g.vs[this.rrBaseline];
        const state = v ? rrState(v.rr_lo, v.rr_hi, v.rr) : "none";
        return [
          idCell(g.id, g.label),
          `${(g.share * 100).toFixed(1)}%`,
          v && v.baseline !== null ? `${(v.baseline * 100).toFixed(1)}%` : "—",
          v && v.rr !== null ? `${ratioText(v.rr)}${v.rr_lo !== null && v.rr_hi !== null ? ` ${ratioText(v.rr_lo)}–${ratioText(v.rr_hi)}` : ""}` : "—",
          RR_SHORT[state],
        ];
      });
      body.replaceChildren(key, wrap, notes, table(`Table view: ${BASELINE_NAMES[this.rrBaseline]}, ${this.rrLevel === "regions" ? "UN M49 regions" : "UN M49 sub-regions"}`, ["Group", "Share", "Base", "Ratio, 95%", "Reading"], rows, [false, true, true, true, false]));
    };
    controls.append(
      select("Baseline", [["population", "Population (2024)"], ["land_area", "Land area (2023)"], ["equal", "Equal shares"]], this.rrBaseline, (v) => {
        this.rrBaseline = v;
        render();
      }),
      select("Level", [["regions", "UN M49 regions"], ["subregions", "Sub-regions"]], this.rrLevel, (v) => {
        this.rrLevel = v === "subregions" ? "subregions" : "regions";
        render();
      }),
    );
    sec.append(controls, body);
    render();

    if (b.sibling_flags.length > 0) {
      const who = (f: (typeof b.sibling_flags)[number]): HTMLElement => {
        const cell = h("span");
        cell.append(idCell(f.id, f.label), h("span", "meta", " under "), idCell(f.parent, f.parent_label));
        return cell;
      };
      sec.append(table("Sibling parity: a subtree at least 3× its siblings' median (a look, not a verdict)", ["Concept", "Size", "Median"],
        b.sibling_flags.slice(0, 15).map((f) => [who(f), String(f.subtree), String(f.median)]), [false, true, true]));
    }
    const facts: string[] = [];
    if (b.evidence) facts.push(`${fmt.format(b.evidence.sourced)} of ${fmt.format(b.evidence.statements)} current Wikidata statements about these concepts cite a source; for the hierarchy statements (instance of, subclass of, part of, facet of) ${fmt.format(b.evidence.hierarchy_sourced)} of ${fmt.format(b.evidence.hierarchy_statements)}.`);
    if (b.attention) facts.push(`Attention: median ${b.attention.median ?? "?"} Wikipedia language editions without the bot-generated ${b.attention.excluded.join(" and ")} editions (${b.attention.median_all ?? "?"} with them; ${fmt.format(b.attention.changed)} concepts change).`);
    const ai = b.decided.filter((d) => d.decider === "AI agent").reduce((s, d) => s + d.n, 0);
    const human = b.decided.filter((d) => d.decider === "human").reduce((s, d) => s + d.n, 0);
    facts.push(`Crosswalk decisions: ${fmt.format(ai)} by an AI agent, ${fmt.format(human)} by people; ${fmt.format(b.human_reviews)} human reviews recorded (acat review queue).`);
    const ul = h("ul", "notes");
    for (const f of facts) ul.append(h("li", undefined, f));
    sec.append(ul);
    return sec;
  }
}
