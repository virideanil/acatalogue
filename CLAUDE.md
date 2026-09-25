# Working in acatalogue

A curated, attributed catalogue of knowledge. Read `docs/DESIGN.md` before changing structure.

## Invariants (the schema enforces most of them; do not work around it)

- `seed/**/*.tsv` is the curated truth: the compendium, facet schemes, crosswalks and the reviewed
  Wikidata decisions. Change knowledge by editing these files, one decision per line.
- `corpora/<name>-<yyyymmdd>/corpus.sqlite` files are sealed. Never modify one; fetch a new dated
  corpus with `acat fetch …` instead. Their bytes are the provenance of everything imported.
- `data/acatalogue.sqlite` is built, not edited: `./bin/acat build` (≈9 s, no network). A corpus that is
  not sealed (a fetch still running or interrupted) is skipped by the build.
- Sources, concepts, claims and ledger rows are never deleted. Concepts are deprecated; claims and
  documents are superseded.
- A machine's proposal (e.g. a Wikidata match) is recorded as a proposal: the crosswalk's `reviewer`
  column names who proposed it, including when that was a model. People's decisions go into
  `seed/reviews/<name>.tsv` through `acat review approve|revise|object`, and the build applies them on
  top. Never write a review in a person's name; an agent's review uses `--agent` and never decides.
- Fetchers pass a response check (`fetch.py`): an error body is never sealed as data.
- Evaluations do not go into scope notes; they are claims with a source and an epistemic status.

## Before pushing

```sh
python3 -m unittest discover -s tests      # Python: invariants, seeds, grepper, API, updates
./bin/acat build && ./bin/acat verify      # seeds valid, corpora re-hash, ledger chain intact
cd viz && npm test                         # particle field: build + physics tests
```

`viz/dist/` is committed (the page runs without Node); rebuild it with `npm run build` after
changing `viz/src/`. After changing the physics (the modules listed in `acatalogue/bake.py`), run
`./bin/acat bake` so the served layout is the one this physics computes (its model id is their hash).

Optional, heavier: `./bin/acat embed` (dense label vectors; needs onnxruntime, tokenizers and the
pinned model, verified by SHA-256) and `./bin/acat eval` (leave-one-language-out retrieval evaluation).
