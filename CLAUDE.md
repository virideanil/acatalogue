# Working in acatalogue

A curated, attributed catalogue of knowledge. Read `docs/DESIGN.md` before changing structure.

## Invariants (the schema enforces most of them; do not work around it)

- `seed/**/*.tsv` is the curated truth: the compendium, facet schemes, crosswalks and the reviewed
  Wikidata decisions. Change knowledge by editing these files, one decision per line.
- `corpora/<name>-<yyyymmdd>/corpus.sqlite` files are sealed. Never modify one; fetch a new dated
  corpus with `acat fetch …` instead. Their bytes are the provenance of everything imported.
- `data/acatalogue.sqlite` is built, not edited: `./bin/acat build` (≈8 s, no network).
- Sources, concepts, claims and ledger rows are never deleted. Concepts are deprecated; claims and
  documents are superseded.
- Every automated proposal (e.g. a Wikidata match) is reviewed before it enters a seed file, and the
  `reviewer` column names who reviewed it — including when that was a model.
- Evaluations do not go into scope notes; they are claims with a source and an epistemic status.

## Before pushing

```sh
python3 -m unittest discover -s tests      # Python: invariants, seeds, grepper, API, updates
./bin/acat build && ./bin/acat verify      # seeds valid, corpora re-hash, ledger chain intact
cd viz && npm test                         # particle field: build + physics tests
```

`viz/dist/` is committed (the page runs without Node); rebuild it with `npm run build` after
changing `viz/src/`.
