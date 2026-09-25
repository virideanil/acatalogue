# acatalogue HTTP API — contract between the database and the particle field

`acat serve` (Python, stdlib only) opens the catalogue database **read-only** and serves:

| Path | What |
|---|---|
| `GET /` | `viz/index.html` (the particle field) |
| `GET /dist/*`, `/style.css`, … | static files under `viz/` |
| `GET /api/graph` | every concept as a node plus every edge (below) |
| `GET /api/grep` | the SQL grepper (below) |
| `GET /api/node?id=<scoped id>` | everything known about one id, with provenance |
| `GET /api/audit` | coverage / bias measurements |
| `GET /api/stats` | row counts and the database's identity |

All responses are UTF-8 JSON. Errors are `{"error": "<message>"}` with a 4xx/5xx status.
Nothing in any response is HTML: text is plain, and the client must render it as text
(never `innerHTML`).

## Identifiers

Every record has a **scoped, resolvable id**: `<scope>/<code>`.

| Scope | Example | Meaning |
|---|---|---|
| `acat` | `acat/physics` | a concept in the authored ACAT compendium |
| `space` | `space/m49-002` | a UN M49 region / country (the *where* facet) |
| `kind` | `kind/person` | ontological kind facet (what sort of thing) |
| `epistemic` | `epistemic/attributed` | epistemic status facet (how we know / how sure) |
| `udc`, `ddc`, `lcc`, `propaedia` | `udc/5` | top classes of external schemes, kept for crosswalks |
| `wd` | `wd/Q413` | a Wikidata item or property |
| `doc` | `doc/wikipedia-en-intros-20260925/Physics` | a document in a named corpus |
| `src` | `src/sha512:3f2a…` | exact source bytes, addressed by SHA-512 |

## `GET /api/graph`

```json
{
  "version": 1,
  "generated_at": "2026-09-25T16:00:00Z",
  "schemes": [
    {"id": "acat", "title": "ACAT Compendium", "origin": "authored", "n": 612}
  ],
  "nodes": [
    {
      "id": "acat/physics",
      "label": "Physics",
      "scheme": "acat",
      "root": "acat/matter",
      "depth": 1,
      "mass": 3.2,
      "langs": 187,
      "docs": 1,
      "xy": [0.12, -0.40],
      "pos": [-214.3, 87.9]
    }
  ],
  "edges": [
    {"s": 12, "t": 3, "k": "broader", "w": 1.0}
  ],
  "layout": {"model": "layout/physics-731c56d68b6d8d37", "steps": 2656, "asleep": true,
             "complete": true, "stale": false}
}
```

Node fields:

- `id` — scoped id (unique).
- `label` — display label (English preferred label for now; labels in other
  languages come from `/api/node`).
- `scheme` — scheme id; one of `schemes[].id`.
- `root` — the top concept of this node's scheme that it descends from (for a
  top concept, itself). With several parents, the first by id order.
- `depth` — 0 for top concepts; shortest distance to a top concept otherwise.
- `mass` — `>= 1`, already log-scaled (descendants + documents). Size ∝ `sqrt(mass)`.
- `langs` — number of Wikipedia language editions with an article on this concept
  (from the reconciled Wikidata item's sitelinks). `null` = unknown / not reconciled.
  This is the input of the *coverage lens*.
- `docs` — number of corpus documents attached.
- `xy` — optional semantic seed position in `[-1, 1]²` (from the semantic layer), or `null`.
- `pos` — position baked offline by `acat bake` (world units of the physics), or `null`.

`layout` (or `null` when nothing is baked): the layout model the positions come from, named by the
SHA-512 of the physics modules that computed them; `steps` it took; `asleep` — it ended at rest, not at
its step limit; `complete` — every node has a `pos`; `stale` — it was computed for a different graph
(the positions remain a good start, and the browser relaxes from them). The browser adopts a complete
layout and starts at rest; otherwise it settles live.

Edge fields: `s`, `t` are indices into `nodes`. `k` is one of:

- `broader` — `s` is narrower than `t` (hierarchy; poly-hierarchy allowed).
- `related` — non-hierarchical association inside a scheme.
- `mapping` — crosswalk between schemes (e.g. `acat/physics` ↔ `udc/5`).
- `semantic` — nearest neighbours from the semantic layer; `w` = cosine similarity in `(0, 1]`.

`w` is a weight in `(0, 1]`.

## `GET /api/grep`

Query parameters:

| Param | Values | Default |
|---|---|---|
| `q` | the pattern | required |
| `mode` | `words` (FTS5 query syntax: AND/OR/NOT, `"phrase"`, `prefix*`, `NEAR()`), `substring` (literal, trigram-accelerated), `regex` (Python `re`) | `words` |
| `scope` | `all`, `concepts`, `passages`, `labels` | `all` |
| `limit` | 1–500 | 50 |
| `under` | a concept id: only hits attached to that concept or its descendants | none |

```json
{
  "query": "quantum",
  "mode": "words",
  "scope": "all",
  "sql": ["SELECT … FROM concept_fts WHERE concept_fts MATCH ? …"],
  "elapsed_ms": 4.1,
  "total": 23,
  "hits": [
    {
      "target": "acat/quantum-mechanics",
      "type": "concept",
      "title": "Quantum mechanics",
      "parts": [{"t": "branch of physics describing ", "m": false}, {"t": "quantum", "m": true}, {"t": " systems…", "m": false}],
      "score": 7.3,
      "concepts": ["acat/quantum-mechanics"]
    }
  ],
  "error": null
}
```

- `sql` is the exact SQL that ran — the grepper is transparent by design.
- `parts` is the snippet split into segments; `m: true` marks a match. Render each
  segment as a text node (matches emphasised). No offsets, no HTML.
- `type` is `concept`, `passage` or `label`.
- `concepts` lists the concept ids a hit belongs to — the particle field lights these up.
- On a bad pattern (invalid FTS syntax or regex), status 400 with `error` filled and
  `hits: []`.

## `GET /api/node?id=acat/physics`

```json
{
  "id": "acat/physics",
  "scheme": "acat",
  "code": "physics",
  "label": "Physics",
  "scope_note": "…",
  "status": "active",
  "labels": [{"lang": "tr", "kind": "pref", "text": "Fizik", "source": "src/sha512:…"}],
  "n_label_langs": 180,
  "langs": 187,
  "broader":   [{"id": "acat/matter", "label": "Matter & Energy"}],
  "narrower":  [{"id": "acat/mechanics", "label": "Mechanics"}],
  "related":   [{"id": "acat/chemistry", "label": "Chemistry"}],
  "mappings":  [{"id": "wd/Q413", "label": "physics", "relation": "exactMatch", "method": "sparql-label+review",
                 "status": "accepted", "reviewer": "claude (AI agent, session 2026-09-25)", "decided_by": "AI agent", "note": "…"}],
  "documents": [{"id": "doc/…/Physics", "title": "Physics", "lang": "en", "url": "https://en.wikipedia.org/wiki/Physics", "license": "CC BY-SA 4.0", "excerpt": "…", "sha512": "…"}],
  "claims":    [{"subject": "wd/Q413", "predicate": "wd/P279", "predicate_label": "subclass of", "object": "wd/Q336",
                 "object_label": "science", "value": null, "snak_type": "value", "datatype": "wikibase-item",
                 "statement_id": "Q413$…", "pointer": "/entities/Q413/claims/P279/0", "qualifiers": 0,
                 "references": 1, "sourced": true, "valid_from": null, "valid_to": null,
                 "epistemic": "epistemic/attributed", "rank": "normal", "source": "src/sha512:…"}],
  "neighbors": [{"id": "acat/chemistry", "label": "Chemistry", "score": 0.71, "model": "lsa-tfidf-svd"}],
  "provenance": [{"source": "seed/compendium/acat/01-matter.tsv", "sha512": "…", "kind": "seed"}]
}
```

Every list may be empty. `labels` can hold hundreds of entries (one or more per language).

- `mappings[].decided_by` — who stands behind the decision: `AI agent`, `human` (after a review in
  `seed/reviews/`), or `seed file (no named reviewer)`. `note` names the original proposal when a person
  revised it.
- `claims` — current claims only (superseded ones stay in the database). For statement-level claims:
  `statement_id` is Wikidata's statement GUID and `pointer` an RFC 6901 JSON Pointer into the stored
  source bytes (`source`); `snak_type` is `value`, `somevalue` ("unknown value") or `novalue` ("no
  value"); `value` holds a literal (text, or canonical JSON for time, quantity, monolingual text and
  coordinates) when `object` is null; `sourced` is true when some reference says more than "imported
  from a Wikimedia project"; `valid_from`/`valid_to` are ISO 8601 / EDTF text (astronomical years).
- `reviews` — decisions recorded about this concept, its labels or its mappings.

## `GET /api/audit`

```json
{
  "generated_at": "…",
  "domains": [
    {"id": "acat/matter", "label": "Matter & Energy", "concepts": 45, "reconciled": 40,
     "docs": 38, "median_langs": 95, "min_langs": 3, "min_langs_id": "acat/…"}
  ],
  "thinnest": [{"id": "acat/…", "label": "…", "langs": 2}],
  "regions":  [{"id": "space/m49-002", "label": "Africa", "tagged": 12}],
  "label_languages": [{"lang": "en", "concepts": 600}],
  "notes": ["…"],
  "baseline_audit": {
    "run_id": 4, "generated_at": "…", "ledger_head": "…",
    "params": {"seed": 20260925, "bootstrap": 2000, "baselines": ["population", "land_area", "equal"]},
    "regions": {
      "n": 65, "k": 6, "entropy_norm": 0.87, "tagged_above_level": 0, "untagged": 534,
      "groups": [{"id": "space/m49-142", "label": "Asia", "share": 0.392, "share_lo": 0.283, "share_hi": 0.514,
                  "vs": {"population": {"baseline": 0.588, "rr": 0.667, "log2_rr": -0.58, "rr_lo": 0.48, "rr_hi": 0.87}}}],
      "distribution": {"population": {"jsd_bits": 0.076, "jsd_lo": 0.039, "jsd_hi": 0.139, "null_p95": 0.027,
                                      "exceeds_null": true, "gini_rr": 0.66}},
      "baseline_coverage": {"population": {"as_of": "2024", "areas_with_value": 215, "areas": 248, "without_value": ["…"]}}
    },
    "subregions": {"…": "same shape"},
    "siblings": [{"parent": "acat/philosophy", "label": "Philosophy", "children": 10, "quantities": {"subtree": {"cv": 1.29}},
                  "flags": [{"id": "acat/philosophical-traditions", "subtree": 11, "median": 1}]}],
    "attention": {"median": 85, "median_all": 85, "concepts_with_bot_editions": 310, "excluded_editions": ["cebwiki", "warwiki"]},
    "evidence": {"all": {"statements": 48210, "sourced": 8222}, "hierarchy": {"statements": 2441, "sourced": 247}},
    "review": {"accepted_by_decider": {"AI agent": {"exactMatch": 399}}, "human_reviews": 0}
  }
}
```

`baseline_audit` is the newest run stored by `acat build` (tables `audit_run`, `audit_metric`), or
`null`. Shares count each place-tagged concept once, split evenly over its regions; `rr` is the share
divided by the baseline's share (`null` when the baseline has no value); intervals are 95% Wilson
intervals; `jsd_*` is the Jensen–Shannon divergence in bits with a bootstrap interval, compared with
the 95th percentile of random samples drawn from the baseline itself. The three baselines are
declared choices: none is "the fair one".

## `GET /api/stats`

```json
{"db": "data/acatalogue.sqlite", "counts": {"concept": 1200, "passage": 900}, "ledger_head": "sha512…", "built_at": "…"}
```

## Static mode

`acat export-graph viz/data/graph.json` writes the `/api/graph` payload to a file. When the
API is unreachable, the particle field loads `data/graph.json` next to `index.html` and
falls back to a client-side label search, clearly labelled as offline.
