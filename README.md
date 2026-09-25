# acatalogue

A curated, attributed catalogue of knowledge:

- **a database** — one SQLite file, rebuilt in seconds from reviewed seed files and sealed source corpora;
- **named corpora** — dated, sealed SQLite files holding the exact bytes of every source, addressed by SHA-512;
- **a compendium** — a faceted classification of all knowledge: thirteen domains on a circle (no domain on top),
  599 concepts with scope notes, labels in 489 languages, crosswalks to UDC, DDC, LCC, the Propædia and Wikidata;
- **a SQL grepper** — word, substring and regex search over concepts, passages and labels in every language,
  showing the SQL it ran; it can also grep any SQLite file;
- **a particle field** — the whole catalogue as a physical system you can search and explore in the browser.

Why it is built this way — and what "without bias" can honestly mean — is in [docs/DESIGN.md](docs/DESIGN.md).
The founding request and what became of each part of it is in [docs/BRIEF.md](docs/BRIEF.md).

## Quick start

Python 3.11+ with its standard library is all you need (numpy only for the semantic layer).

```sh
./bin/acat build                 # seed/ + corpora/  ->  data/acatalogue.sqlite   (~8 s, no network)
./bin/acat semantic              # optional: LSA neighbours and layout (needs numpy)
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
acat audit                     # coverage and bias measurements
acat verify                    # validate seeds, re-hash every corpus, check the ledger chain
acat stats                     # counts, corpora, ledger head
acat compendium-md             # regenerate docs/COMPENDIUM.md
acat export-graph              # write viz/data/graph.json for the particle field without a server
acat fetch m49|external|wikidata|wikipedia   # fetch a source into a new dated, sealed corpus (network)
```

## Layout

| Path | What |
|---|---|
| `seed/schemes.tsv` | the concept schemes and their licences |
| `seed/compendium/acat/*.tsv` | the ACAT compendium, one concept per line (edit these) |
| `seed/schemes/*.tsv` | facet vocabularies (kind, epistemic) and external scheme top classes |
| `seed/crosswalk/*.tsv` | reviewed crosswalks: ACAT ↔ UDC/DDC/LCC/Propædia, ACAT ↔ Wikidata |
| `corpora/<name>-<yyyymmdd>/corpus.sqlite` | sealed named corpora: exact bytes (SQLite Archive table), fetch log, manifest |
| `acatalogue/` | the Python package (standard library only) |
| `acatalogue/schema.sql` | the catalogue schema and its enforced invariants |
| `viz/` | the particle field (TypeScript source in `viz/src`, compiled JS in `viz/dist`) |
| `docs/` | design, API contract, compendium, brief |
| `tests/` | `python3 -m unittest discover -s tests` |
| `data/` | the built database (not in git; `acat build` recreates it) |

## Data licences

Code and authored seeds: see the repository licence (to be chosen by the owner). Imported data keeps
its own licence, recorded per source in the database: Wikidata (CC0), Wikipedia text (CC BY-SA 4.0 —
anything redistributed from `corpora/wikipedia-en-intros-*` must carry attribution and the same
licence; every document stores its page URL and revision), UN M49 (UNSD public standard), UDC Summary
(CC BY-SA 3.0), LCC (U.S. Government work), DDC (© OCLC; only class numbers and captions are cited).
