# acatalogue

A curated, attributed catalogue of knowledge:

- **a database** — one SQLite file, rebuilt in seconds from reviewed seed files and sealed source corpora;
- **named corpora** — dated, sealed SQLite files holding the exact bytes of every source, addressed by SHA-512;
- **a compendium** — a faceted classification of all knowledge: thirteen domains on a circle (no domain on top),
  599 concepts with scope notes, labels in 489 languages, crosswalks to UDC, DDC, LCC, the Propædia and Wikidata;
- **a SQL grepper** — word, substring and regex search over concepts, passages and labels in every language,
  showing the SQL it ran; it can also grep any SQLite file;
- **a particle field** — the whole catalogue as a physical system you can search and explore in the browser;
- **a bias audit and a review ledger** — coverage measured against declared baselines with intervals, and
  every machine proposal kept apart from the people who approve, revise or object to it.

Why it is built this way — and what "without bias" can honestly mean — is in [docs/DESIGN.md](docs/DESIGN.md).
The requests and what became of each part of them are in [docs/BRIEF.md](docs/BRIEF.md); the research
behind the second round is in [reports/](reports/Improving%20the%20acatalogue%20knowledge%20base.md).

## Quick start

Python 3.11+ with its standard library is all you need (numpy only for the semantic layer).

```sh
./bin/acat build                 # seed/ + corpora/  ->  data/acatalogue.sqlite   (~9 s, no network)
./bin/acat semantic              # optional: LSA neighbours and layout (needs numpy)
./bin/acat bake                  # optional: bake the particle layout with the browser's own physics (needs Node)
./bin/acat serve                 # http://127.0.0.1:8765/  — the particle field + JSON API
```

Or install it: `pip install -e .` (add `[semantic]` for numpy), then use `acat` directly.

## The grepper

```sh
acat grep quantum                          # FTS5 words, ranked, over concepts + passages + labels
acat grep 'NEAR(sky god, 5)' -s passages   # FTS5 query syntax
acat grep -F fizik -s labels --lang tr     # substring, any script (trigram index)
acat grep -F 物理 -s labels                 # works without spaces between words
acat grep -E 'Leviath[a-z]+' --explain     # regex; --explain prints the SQL that ran
acat grep --under acat/belief sky          # only inside one subtree
acat grep-db ~/some/other.sqlite 'pattern' # grep every text column of any SQLite file, read-only
acat sql "SELECT id, label FROM concept WHERE scheme = 'space' LIMIT 5"
```

## Other commands

```sh
acat show acat/tengrism        # everything about one id: labels, parents, mappings, documents, claims, neighbours, provenance
acat tree acat/belief -d 2     # the compendium as a tree
acat audit                     # coverage and bias against declared baselines (stored per build)
acat review queue              # machine-proposed crosswalks awaiting a person, exactMatch first
acat review approve acat/physics wd/Q413 --reviewer "Your Name" --human [--perspective …]
acat review revise  acat/x wd/Q1 --relation closeMatch --reviewer "…" --human --rationale "…"
acat review object  acat/x wd/Q1 --reviewer "…" --human --rationale "…"    # decisions go to seed/reviews/<name>.tsv
acat eval                      # leave-one-language-out retrieval evaluation (stored in eval_* tables)
acat embed                     # optional: dense multilingual label vectors (onnxruntime + the pinned model)
acat verify                    # validate seeds, re-hash every corpus, check the ledger chain
acat stats                     # counts, corpora, ledger head
acat compendium-md             # regenerate docs/COMPENDIUM.md
acat export-graph              # write viz/data/graph.json for the particle field without a server
acat fetch m49|external|wikidata|wikidata-statements|wikipedia|worldbank   # new dated, sealed corpus (network)
```

## Sources: choose, download, integrate

129 open sources are registered in `seed/sources/` (researched and checked live; who publishes each,
its licence, languages and perspective, and how it is read). Choose a starting point, add your own,
and let one command download, verify, convert and integrate them:

```sh
acat sources presets                       # starter, languages, places-and-time, library-subjects, …
acat sources list --preset starter         # size, licence, languages, mode and perspective of each
acat sources select preset:starter         # or individual ids; --mode full|attach
acat sources add mydb --path ~/my.sqlite --converter sqlite --options '{"tables": [...]}'   # your own
acat sources plan                          # what will be downloaded, how big, under which licence
acat sources run                           # download (resumable, SHA-512) → seal → convert → integrate
acat sources status                        # downloads, conversions, integrations, recent events
acat sources search istanbul               # search every integrated source in place (attach mode too)
acat sources term geonames/745044          # everything a source says about one of its terms
```

Downloads, sealed manifests and converted lean files live in the local store (`store/`, or
`$ACAT_STORE`), never in git. `acat build` integrates the store's selection; `acat verify` re-hashes it.

## Layout

| Path | What |
|---|---|
| `seed/schemes.tsv` | the concept schemes and their licences |
| `seed/compendium/acat/*.tsv` | the ACAT compendium, one concept per line (edit these) |
| `seed/schemes/*.tsv` | facet vocabularies (kind, epistemic) and external scheme top classes |
| `seed/crosswalk/*.tsv` | crosswalks: ACAT ↔ UDC/DDC/LCC/Propædia, ACAT ↔ Wikidata (proposals, with who proposed them) |
| `seed/reviews/<name>.tsv` | people's decisions on those proposals (`acat review`); applied on top at build |
| `seed/sources/*.tsv` | the source registry, its files and presets (`research_notes/Open knowledge sources registry/curate.py`) |
| `store/` | this machine's downloads, sealed manifests and lean files (not in git; `$ACAT_STORE`) |
| `corpora/<name>-<yyyymmdd>/corpus.sqlite` | sealed named corpora: exact bytes (SQLite Archive table), fetch log, manifest |
| `acatalogue/` | the Python package (standard library only) |
| `acatalogue/schema.sql` | the catalogue schema and its enforced invariants |
| `viz/` | the particle field (TypeScript source in `viz/src`, compiled JS in `viz/dist`) |
| `docs/` | design, API contract, compendium, brief |
| `reports/`, `research_notes/` | the research report and the notes and prototypes behind it |
| `tests/` | `python3 -m unittest discover -s tests` |
| `data/` | the built database (not in git; `acat build` recreates it) |

## Data licences

Code and authored seeds: see the repository licence (to be chosen by the owner). Imported data keeps
its own licence, recorded per source in the database: Wikidata (CC0), Wikipedia text (CC BY-SA 4.0 —
anything redistributed from `corpora/wikipedia-en-intros-*` must carry attribution and the same
licence; every document stores its page URL and revision), UN M49 (UNSD public standard), UDC Summary
(CC BY-SA 3.0), LCC (U.S. Government work), DDC (© OCLC; only class numbers and captions are cited),
World Bank WDI (CC BY 4.0). Sources integrated from the local store keep theirs: each registry row
states the licence, and each integrated scheme and lean file carries it (ShareAlike sources such as the
UNESCO Thesaurus stay under their licence when redistributed). The optional dense model, multilingual-e5-large-instruct (MIT), is not stored
in the repository: `acat embed` verifies the pinned files' SHA-256 before using them.
