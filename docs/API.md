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
      "xy": [0.12, -0.40]
    }
  ],
  "edges": [
    {"s": 12, "t": 3, "k": "broader", "w": 1.0}
  ]
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
  "mappings":  [{"id": "wd/Q413", "label": "physics", "relation": "exactMatch", "method": "search+review", "status": "accepted"}],
  "documents": [{"id": "doc/…/Physics", "title": "Physics", "lang": "en", "url": "https://en.wikipedia.org/wiki/Physics", "license": "CC BY-SA 4.0", "excerpt": "…", "sha512": "…"}],
  "claims":    [{"subject": "wd/Q413", "predicate": "wd/P279", "predicate_label": "subclass of", "object": "wd/Q336", "object_label": "science", "epistemic": "epistemic/attributed", "rank": "normal", "source": "src/sha512:…"}],
  "neighbors": [{"id": "acat/chemistry", "label": "Chemistry", "score": 0.71, "model": "lsa-tfidf-svd"}],
  "provenance": [{"source": "seed/compendium/acat/01-matter.tsv", "sha512": "…", "kind": "seed"}]
}
```

Every list may be empty. `labels` can hold hundreds of entries (one or more per language).

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
  "notes": ["…"]
}
```

## `GET /api/stats`

```json
{"db": "data/acatalogue.sqlite", "counts": {"concept": 1200, "passage": 900}, "ledger_head": "sha512…", "built_at": "…"}
```

## Static mode

`acat export-graph viz/data/graph.json` writes the `/api/graph` payload to a file. When the
API is unreachable, the particle field loads `data/graph.json` next to `index.html` and
falls back to a client-side label search, clearly labelled as offline.
