// The JSON contract with the acatalogue API (docs/API.md), its loaders, and runtime
// validation. Every response is parsed from `unknown`: fields are checked, bad records
// are dropped and counted (never silently), and text is kept as plain strings for the
// UI to render as text nodes.

import type { EdgeKind } from "./physics.js";

// ---------------------------------------------------------------- types (docs/API.md)

export interface SchemeInfo {
  id: string;
  title: string;
  origin: string;
  n: number;
}

export interface GraphNode {
  id: string;
  label: string;
  scheme: string;
  root: string;
  depth: number;
  mass: number;
  /** Wikipedia language editions with an article; null = unknown / not reconciled. */
  langs: number | null;
  docs: number;
  /** Optional semantic seed position in [-1, 1]^2. */
  xy: [number, number] | null;
}

export interface GraphEdge {
  s: number;
  t: number;
  k: EdgeKind;
  w: number;
}

export interface GraphPayload {
  version: number;
  generated_at: string;
  schemes: SchemeInfo[];
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export type GrepMode = "words" | "substring" | "regex";
export type GrepScope = "all" | "concepts" | "passages" | "labels";
export type HitType = "concept" | "passage" | "label";

export interface GrepPart {
  t: string;
  m: boolean;
}

export interface GrepHit {
  target: string;
  type: HitType;
  title: string;
  parts: GrepPart[];
  score: number;
  concepts: string[];
}

export interface GrepResponse {
  query: string;
  mode: GrepMode;
  scope: GrepScope;
  sql: string[];
  elapsed_ms: number;
  total: number;
  hits: GrepHit[];
  error: string | null;
}

export interface NodeRef {
  id: string;
  label: string;
}

export interface LabelEntry {
  lang: string;
  kind: string;
  text: string;
  source: string;
}

export interface MappingEntry {
  id: string;
  label: string;
  relation: string;
  method: string;
  status: string;
}

export interface DocumentEntry {
  id: string;
  title: string;
  lang: string;
  url: string;
  license: string;
  excerpt: string;
  sha512: string;
}

export interface ClaimEntry {
  subject: string;
  predicate: string;
  predicate_label: string;
  object: string;
  object_label: string;
  epistemic: string;
  rank: string;
  source: string;
}

export interface NeighborEntry {
  id: string;
  label: string;
  score: number;
  model: string;
}

export interface ProvenanceEntry {
  source: string;
  sha512: string;
  kind: string;
}

export interface NodeRecord {
  id: string;
  scheme: string;
  code: string;
  label: string;
  scope_note: string;
  status: string;
  labels: LabelEntry[];
  n_label_langs: number;
  langs: number | null;
  broader: NodeRef[];
  narrower: NodeRef[];
  related: NodeRef[];
  mappings: MappingEntry[];
  documents: DocumentEntry[];
  claims: ClaimEntry[];
  neighbors: NeighborEntry[];
  provenance: ProvenanceEntry[];
}

export interface AuditDomain {
  id: string;
  label: string;
  concepts: number;
  reconciled: number;
  docs: number;
  median_langs: number | null;
  min_langs: number | null;
  min_langs_id: string;
}

export interface AuditResponse {
  generated_at: string;
  domains: AuditDomain[];
  thinnest: Array<{ id: string; label: string; langs: number | null }>;
  regions: Array<{ id: string; label: string; tagged: number }>;
  label_languages: Array<{ lang: string; concepts: number }>;
  notes: string[];
}

export interface StatsResponse {
  db: string;
  counts: Record<string, number>;
  ledger_head: string;
  built_at: string;
}

// ------------------------------------------------------------------ small coercers

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const str = (v: unknown, fallback = ""): string => (typeof v === "string" ? v : typeof v === "number" ? String(v) : fallback);
const num = (v: unknown, fallback = 0): number => (typeof v === "number" && Number.isFinite(v) ? v : fallback);
const numOrNull = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const list = <T>(v: unknown, f: (o: Obj) => T): T[] => arr(v).filter(isObj).map(f);

const EDGE_KINDS: ReadonlySet<string> = new Set(["broader", "related", "mapping", "semantic"]);

// ------------------------------------------------------------------ graph

export interface ParsedGraph {
  payload: GraphPayload;
  /** Records that could not be used, with reasons (shown in the UI, never hidden). */
  droppedNodes: number;
  droppedEdges: number;
  mergedDuplicates: number;
  warnings: string[];
}

/** Validate an /api/graph payload. Throws only when it is not a graph at all. */
export function parseGraph(json: unknown): ParsedGraph {
  if (!isObj(json) || !Array.isArray(json.nodes)) throw new Error("not a graph payload (no nodes array)");
  const warnings: string[] = [];
  const nodes: GraphNode[] = [];
  const oldToNew = new Int32Array(json.nodes.length).fill(-1);
  const byId = new Map<string, number>();
  let droppedNodes = 0;
  let mergedDuplicates = 0;
  json.nodes.forEach((raw, k) => {
    if (!isObj(raw) || typeof raw.id !== "string" || raw.id.length === 0) {
      droppedNodes++;
      return;
    }
    const seen = byId.get(raw.id);
    if (seen !== undefined) {
      oldToNew[k] = seen; // duplicate id: its edges attach to the first occurrence
      mergedDuplicates++;
      return;
    }
    const langs = numOrNull(raw.langs);
    const xyRaw = raw.xy;
    const xy: [number, number] | null =
      Array.isArray(xyRaw) && xyRaw.length === 2 && typeof xyRaw[0] === "number" && typeof xyRaw[1] === "number" && Number.isFinite(xyRaw[0]) && Number.isFinite(xyRaw[1])
        ? [xyRaw[0], xyRaw[1]]
        : null;
    const node: GraphNode = {
      id: raw.id,
      label: str(raw.label, raw.id) || raw.id,
      scheme: str(raw.scheme, raw.id.split("/")[0] ?? ""),
      root: str(raw.root, raw.id),
      depth: Math.max(0, Math.floor(num(raw.depth, 0))),
      mass: Math.max(1, num(raw.mass, 1)),
      langs: langs === null ? null : Math.max(0, Math.round(langs)),
      docs: Math.max(0, Math.floor(num(raw.docs, 0))),
      xy,
    };
    oldToNew[k] = nodes.length;
    byId.set(node.id, nodes.length);
    nodes.push(node);
  });
  if (droppedNodes > 0) warnings.push(`${droppedNodes} node record(s) without a usable id were dropped`);
  if (mergedDuplicates > 0) warnings.push(`${mergedDuplicates} duplicate node id(s) merged into their first occurrence`);

  const edges: GraphEdge[] = [];
  let droppedEdges = 0;
  for (const raw of arr(json.edges)) {
    if (!isObj(raw)) {
      droppedEdges++;
      continue;
    }
    const s = raw.s;
    const t = raw.t;
    const k = raw.k;
    if (typeof s !== "number" || typeof t !== "number" || !Number.isInteger(s) || !Number.isInteger(t) || typeof k !== "string" || !EDGE_KINDS.has(k)) {
      droppedEdges++;
      continue;
    }
    const ns = s >= 0 && s < oldToNew.length ? oldToNew[s]! : -1;
    const nt = t >= 0 && t < oldToNew.length ? oldToNew[t]! : -1;
    if (ns < 0 || nt < 0 || ns === nt) {
      droppedEdges++;
      continue;
    }
    const w = num(raw.w, 1);
    edges.push({ s: ns, t: nt, k: k as EdgeKind, w: w > 0 ? Math.min(w, 1) : 1 });
  }
  if (droppedEdges > 0) warnings.push(`${droppedEdges} edge(s) with a bad index, kind or a self loop were dropped`);

  const schemes = list(json.schemes, (o) => ({ id: str(o.id), title: str(o.title, str(o.id)), origin: str(o.origin), n: num(o.n) })).filter((s) => s.id.length > 0);
  for (const n of nodes) {
    if (!schemes.some((s) => s.id === n.scheme)) schemes.push({ id: n.scheme, title: n.scheme, origin: "", n: 0 });
  }
  return {
    payload: { version: num(json.version, 0), generated_at: str(json.generated_at), schemes, nodes, edges },
    droppedNodes,
    droppedEdges,
    mergedDuplicates,
    warnings,
  };
}

export type GraphSource = "api" | "static" | "override";

export interface LoadedGraph extends ParsedGraph {
  source: GraphSource;
  url: string;
  /** Why each earlier source failed (kept for the status line). */
  attempts: string[];
}

async function fetchJson(url: string, signal?: AbortSignal): Promise<{ status: number; json: unknown }> {
  const init: RequestInit = { headers: { Accept: "application/json" } };
  if (signal) init.signal = signal;
  const res = await fetch(url, init);
  let json: unknown = null;
  const text = await res.text();
  try {
    json = JSON.parse(text);
  } catch {
    throw new ApiError(res.ok ? `${url}: response is not JSON` : `${url}: HTTP ${res.status}`, res.status);
  }
  return { status: res.status, json };
}

export class ApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

/**
 * Load the graph: `?graph=<url>` if given (testing), else `/api/graph`, else
 * `data/graph.json` next to index.html.
 */
export async function loadGraph(location: Location): Promise<LoadedGraph> {
  const attempts: string[] = [];
  const override = new URLSearchParams(location.search).get("graph");
  const tryUrl = async (url: string, source: GraphSource): Promise<LoadedGraph | null> => {
    try {
      const { status, json } = await fetchJson(url);
      if (status < 200 || status >= 300) {
        attempts.push(`${url}: HTTP ${status}`);
        return null;
      }
      return { ...parseGraph(json), source, url, attempts: [...attempts] };
    } catch (err) {
      attempts.push(`${url}: ${err instanceof Error ? err.message : String(err)}`);
      return null;
    }
  };
  if (override !== null && override.length > 0) {
    const url = new URL(override, location.href).href;
    const got = await tryUrl(url, "override");
    if (got) return got;
    throw new Error(`could not load ?graph=${override} (${attempts.join("; ")})`);
  }
  const api = await tryUrl(new URL("/api/graph", location.href).href, "api");
  if (api) return api;
  const staticUrl = new URL("data/graph.json", location.href).href;
  const stat = await tryUrl(staticUrl, "static");
  if (stat) return stat;
  throw new Error(`no graph: ${attempts.join("; ")}`);
}

/** True when the API answers /api/stats with JSON. */
export async function probeApi(timeoutMs = 2500): Promise<boolean> {
  const ctrl = new AbortController();
  const timer = globalThis.setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const { status, json } = await fetchJson("/api/stats", ctrl.signal);
    return status >= 200 && status < 300 && isObj(json);
  } catch {
    return false;
  } finally {
    globalThis.clearTimeout(timer);
  }
}

// ------------------------------------------------------------------ grep

function parseParts(v: unknown): GrepPart[] {
  return list(v, (o) => ({ t: str(o.t), m: o.m === true }));
}

export function parseGrep(json: unknown): GrepResponse {
  const o = isObj(json) ? json : {};
  const mode = str(o.mode, "words");
  const scope = str(o.scope, "all");
  return {
    query: str(o.query),
    mode: mode === "substring" || mode === "regex" ? mode : "words",
    scope: scope === "concepts" || scope === "passages" || scope === "labels" ? scope : "all",
    sql: arr(o.sql).map((s) => str(s)),
    elapsed_ms: num(o.elapsed_ms),
    total: num(o.total),
    hits: list(o.hits, (h) => {
      const type = str(h.type, "concept");
      return {
        target: str(h.target),
        type: type === "passage" || type === "label" ? type : "concept",
        title: str(h.title),
        parts: parseParts(h.parts),
        score: num(h.score),
        concepts: arr(h.concepts).map((c) => str(c)).filter((c) => c.length > 0),
      } satisfies GrepHit;
    }),
    error: typeof o.error === "string" ? o.error : null,
  };
}

export interface GrepRequest {
  q: string;
  mode: GrepMode;
  scope: GrepScope;
  limit?: number;
  under?: string;
}

/** GET /api/grep. A 400 (bad pattern) resolves with `error` filled; other failures throw. */
export async function grep(req: GrepRequest, signal?: AbortSignal): Promise<GrepResponse> {
  const params = new URLSearchParams({ q: req.q, mode: req.mode, scope: req.scope, limit: String(req.limit ?? 50) });
  if (req.under) params.set("under", req.under);
  const { status, json } = await fetchJson(`/api/grep?${params.toString()}`, signal);
  const parsed = parseGrep(json);
  if (status === 400) return { ...parsed, error: parsed.error ?? (isObj(json) ? str(json.error, "bad pattern") : "bad pattern"), hits: [] };
  if (status < 200 || status >= 300) throw new ApiError(isObj(json) ? str(json.error, `HTTP ${status}`) : `HTTP ${status}`, status);
  return parsed;
}

/** Split `text` around every case-insensitive occurrence of `query` (length-preserving fold). */
export function splitMatches(text: string, query: string): GrepPart[] {
  const fold = (s: string): string => {
    let out = "";
    for (const ch of s) {
      const low = ch.toLowerCase();
      out += low.length === ch.length ? low : ch;
    }
    return out;
  };
  const hay = fold(text);
  const needle = fold(query);
  const parts: GrepPart[] = [];
  if (needle.length === 0) return [{ t: text, m: false }];
  let from = 0;
  for (;;) {
    const at = hay.indexOf(needle, from);
    if (at < 0) break;
    if (at > from) parts.push({ t: text.slice(from, at), m: false });
    parts.push({ t: text.slice(at, at + needle.length), m: true });
    from = at + needle.length;
  }
  if (from < text.length) parts.push({ t: text.slice(from), m: false });
  return parts;
}

/**
 * Offline fallback: case-insensitive substring match over node labels, shaped like a
 * grep response so the same renderer shows it. Ranked: exact, prefix, earliest match,
 * heavier node, then label.
 */
export function localLabelSearch(nodes: readonly GraphNode[], query: string, limit = 200): GrepResponse {
  const q = query.trim();
  const t0 = performance.now();
  const scored: Array<{ i: number; rank: number; at: number }> = [];
  if (q.length > 0) {
    const needle = q.toLowerCase();
    nodes.forEach((n, i) => {
      const hay = n.label.toLowerCase();
      const at = hay.indexOf(needle);
      if (at < 0) return;
      const rank = hay === needle ? 0 : at === 0 ? 1 : 2;
      scored.push({ i, rank, at });
    });
  }
  scored.sort((a, b) => a.rank - b.rank || a.at - b.at || nodes[b.i]!.mass - nodes[a.i]!.mass || (nodes[a.i]!.label < nodes[b.i]!.label ? -1 : 1));
  const hits: GrepHit[] = scored.slice(0, limit).map(({ i, rank }) => {
    const n = nodes[i]!;
    return { target: n.id, type: "label", title: n.label, parts: splitMatches(n.label, q), score: 3 - rank, concepts: [n.id] };
  });
  return {
    query: q,
    mode: "substring",
    scope: "labels",
    sql: [],
    elapsed_ms: Math.round((performance.now() - t0) * 100) / 100,
    total: scored.length,
    hits,
    error: null,
  };
}

// ------------------------------------------------------------------ node, audit

const refs = (v: unknown): NodeRef[] => list(v, (o) => ({ id: str(o.id), label: str(o.label, str(o.id)) }));

export function parseNode(json: unknown): NodeRecord {
  const o = isObj(json) ? json : {};
  return {
    id: str(o.id),
    scheme: str(o.scheme),
    code: str(o.code),
    label: str(o.label, str(o.id)),
    scope_note: str(o.scope_note),
    status: str(o.status),
    labels: list(o.labels, (l) => ({ lang: str(l.lang, "und"), kind: str(l.kind), text: str(l.text), source: str(l.source) })),
    n_label_langs: num(o.n_label_langs),
    langs: numOrNull(o.langs),
    broader: refs(o.broader),
    narrower: refs(o.narrower),
    related: refs(o.related),
    mappings: list(o.mappings, (m) => ({ id: str(m.id), label: str(m.label, str(m.id)), relation: str(m.relation), method: str(m.method), status: str(m.status) })),
    documents: list(o.documents, (d) => ({
      id: str(d.id),
      title: str(d.title, str(d.id)),
      lang: str(d.lang),
      url: str(d.url),
      license: str(d.license),
      excerpt: str(d.excerpt),
      sha512: str(d.sha512),
    })),
    claims: list(o.claims, (c) => ({
      subject: str(c.subject),
      predicate: str(c.predicate),
      predicate_label: str(c.predicate_label, str(c.predicate)),
      object: str(c.object),
      object_label: str(c.object_label, str(c.object)),
      epistemic: str(c.epistemic),
      rank: str(c.rank),
      source: str(c.source),
    })),
    neighbors: list(o.neighbors, (n) => ({ id: str(n.id), label: str(n.label, str(n.id)), score: num(n.score), model: str(n.model) })),
    provenance: list(o.provenance, (p) => ({ source: str(p.source), sha512: str(p.sha512), kind: str(p.kind) })),
  };
}

export async function fetchNode(id: string, signal?: AbortSignal): Promise<NodeRecord> {
  const { status, json } = await fetchJson(`/api/node?${new URLSearchParams({ id }).toString()}`, signal);
  if (status < 200 || status >= 300) throw new ApiError(isObj(json) ? str(json.error, `HTTP ${status}`) : `HTTP ${status}`, status);
  return parseNode(json);
}

export function parseAudit(json: unknown): AuditResponse {
  const o = isObj(json) ? json : {};
  return {
    generated_at: str(o.generated_at),
    domains: list(o.domains, (d) => ({
      id: str(d.id),
      label: str(d.label, str(d.id)),
      concepts: num(d.concepts),
      reconciled: num(d.reconciled),
      docs: num(d.docs),
      median_langs: numOrNull(d.median_langs),
      min_langs: numOrNull(d.min_langs),
      min_langs_id: str(d.min_langs_id),
    })),
    thinnest: list(o.thinnest, (t) => ({ id: str(t.id), label: str(t.label, str(t.id)), langs: numOrNull(t.langs) })),
    regions: list(o.regions, (r) => ({ id: str(r.id), label: str(r.label, str(r.id)), tagged: num(r.tagged) })),
    label_languages: list(o.label_languages, (l) => ({ lang: str(l.lang), concepts: num(l.concepts) })),
    notes: arr(o.notes).map((n) => str(n)).filter((n) => n.length > 0),
  };
}

export async function fetchAudit(signal?: AbortSignal): Promise<AuditResponse> {
  const { status, json } = await fetchJson("/api/audit", signal);
  if (status < 200 || status >= 300) throw new ApiError(isObj(json) ? str(json.error, `HTTP ${status}`) : `HTTP ${status}`, status);
  return parseAudit(json);
}

/** Offline audit: what can be computed from the loaded graph alone. */
export function auditFromGraph(g: GraphPayload, primaryScheme: string): AuditResponse {
  const byRoot = new Map<string, GraphNode[]>();
  for (const n of g.nodes) {
    if (n.scheme !== primaryScheme) continue;
    (byRoot.get(n.root) ?? byRoot.set(n.root, []).get(n.root)!).push(n);
  }
  const label = new Map(g.nodes.map((n) => [n.id, n.label]));
  const domains: AuditDomain[] = [...byRoot.entries()]
    .map(([id, members]) => {
      const known = members.filter((m) => m.langs !== null).sort((a, b) => a.langs! - b.langs!);
      const median = known.length === 0 ? null : known.length % 2 === 1 ? known[(known.length - 1) / 2]!.langs! : (known[known.length / 2 - 1]!.langs! + known[known.length / 2]!.langs!) / 2;
      return {
        id,
        label: label.get(id) ?? id,
        concepts: members.length,
        reconciled: known.length,
        docs: members.reduce((s, m) => s + m.docs, 0),
        median_langs: median,
        min_langs: known[0]?.langs ?? null,
        min_langs_id: known[0]?.id ?? "",
      };
    })
    .sort((a, b) => (a.id < b.id ? -1 : 1));
  const thinnest = g.nodes
    .filter((n) => n.langs !== null && n.scheme === primaryScheme)
    .sort((a, b) => a.langs! - b.langs! || (a.id < b.id ? -1 : 1))
    .slice(0, 12)
    .map((n) => ({ id: n.id, label: n.label, langs: n.langs }));
  return {
    generated_at: "",
    domains,
    thinnest,
    regions: [],
    label_languages: [],
    notes: [
      "Computed in the browser from the loaded graph because the API is not reachable.",
      "'With langs' counts concepts whose language coverage is known (langs not null); the API's 'reconciled' may differ.",
      "Regions and label languages need the API.",
    ],
  };
}
