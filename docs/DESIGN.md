# How to build a database of world knowledge, and how to categorize it

This document answers the founding question of the repository — *how can we make a database of
entire world knowledge, categorize it, keep it free of bias, and keep it updated and finely
curated?* — and shows what is already built here to test each answer. Every number in this
document comes from the build of 2026-09-25 (`acat stats`, `acat audit`); rerun them to check.

## 0. The short answer

1. **Nobody can type the world in. Federate it.** The world's knowledge is already partly
   structured in open sources — Wikidata, Wikipedia in 300+ languages, library authority files,
   national statistics, scholarly indexes, domain ontologies. A world-knowledge database is a
   *reconciliation spine* over them: stable identifiers, every statement traced to the exact
   bytes it came from, and a curation layer that records every decision.
2. **Categorize with facets on a circle, not one tree with a top.** Knowledge has several
   independent axes — *what field* (domain), *what sort of thing* (kind), *where*, *when*,
   *how it is known* (epistemic status) and *whose account* (perspective). A single tree forces
   one axis to dominate and one tradition to be the centre. Domains go on a circle; the other axes
   are facets; many classification schemes live side by side, connected by crosswalks.
3. **"Without any bias" cannot be delivered, so do not claim it — measure and expose bias
   instead.** Every choice of what to include, what to call it and what to list first is a
   viewpoint. What a database *can* do is attribute every claim, keep contested accounts side by
   side, count its own skew (coverage per region, language, domain), and make every curation
   step visible and reversible.
4. **Updatable and curated means append-only with receipts.** Sources are immutable, dated,
   SHA-512-addressed corpora; new data arrives as a new corpus, never an overwrite; the curated
   parts are human-reviewable text in git; the database is rebuilt from them in seconds; every
   action lands in a hash-chained ledger; identities are deprecated, never deleted.

## 1. What "all world knowledge" can and cannot mean

A database of *all* knowledge in the literal sense does not exist and cannot: knowledge is open-ended,
contested, tacit, and much of it is not written down. What can exist is a catalogue that
(a) knows where knowledge is recorded, (b) holds a reconciled, attributed core of it, and
(c) says clearly what it does not cover. The open sources are large enough to make that core
serious:

| Source | What it contributes | Licence |
|---|---|---|
| Wikidata | more than 100 million items with multilingual labels, statements with ranks and references | CC0 |
| Wikipedia (300+ editions) | prose; the number of editions covering a topic is a measure of attention | CC BY-SA |
| Library classifications and authority files (UDC, DDC, LCC, subject headings, national libraries) | 150 years of subject cataloguing | varies |
| Scholarly indexes (e.g. OpenAlex) | works, authors and research topics | CC0 (API key needed) |
| Statistical standards (UN M49, ISO 3166, ISO 639) | places, languages | public standards |
| Domain ontologies (medicine, biology, agriculture, heritage…) | deep, expert vocabularies | varies |

This repository ingests four of these today — UN M49, Wikidata, English Wikipedia and the top
classes of UDC/DDC/LCC/Propædia — and is designed so the rest plug into the same pipeline.

## 2. The layers

Each layer has one job and one invariant, enforced in the schema (`acatalogue/schema.sql`), not by
convention.

| Layer | What it holds | Invariant | Where |
|---|---|---|---|
| **Bytes** | the exact bytes of every input (seed file, fetched response) | addressed by SHA-512; never changed, never deleted | `source`, corpus `sqlar` |
| **Named corpora** | dated collections of sources, e.g. `wikipedia-en-intros-20260925` | sealed after fetching; a sealed corpus refuses writes | `corpora/*/corpus.sqlite` |
| **Text** | documents and passages extracted from corpora | offsets point back into the document text; each document names its source hash | `document`, `passage` |
| **Compendium** | concept schemes: labels in every language, broader (several parents allowed), related, crosswalks, facets | identities are deprecated, never deleted | `scheme`, `concept`, `label`, `broader`, `related`, `mapping`, `facet` |
| **Claims** | statements: subject – predicate – object/value | every claim names its source bytes and carries an epistemic status and two times (when true in the world; when recorded) | `claim` |
| **Semantic** | vectors, neighbours and a 2-D layout, labelled by the method that made them | a new method is added beside, never silently swapped | `model`, `embedding`, `neighbor`, `layout` |
| **Ledger** | every action on the database | append-only (triggers) and hash-chained (SHA-512 over the previous row) | `ledger` |
| **Views** | grepper, API, particle field, audit | read-only | `grep.py`, `server.py`, `viz/` |

Identifiers are scoped and resolvable: `acat/physics`, `space/m49-792`, `wd/Q413`,
`doc/wikipedia-en-intros-20260925/Physics`, `src/sha512:…`. `acat show <id>` resolves any of them.

## 3. How to categorize

### 3.1 Why one tree fails

Single-tree schemes put one viewpoint at the centre. Two examples, checked against the stored
source pages in `corpora/external-schemes-20260925`:

- **DDC 200 Religion** — divisions 220 to 280 (the Bible, Christianity, Christian practice, orders,
  theology, history and denominations) all concern Christianity, and 290 is "Other religions".
- **LCC** gives the history of the Americas two classes (E and F) and the rest of the world one (D).

These are not failures of care; they are what a tree does when it is grown from one library's
collection. The fix is structural.

### 3.2 A circle of domains

The ACAT compendium has thirteen domains, modelled on the Propædia's "circle of learning" (any
part can be the starting point, none is on top). They are ordered by code only:

| Code | Domain | Covers |
|---|---|---|
| `arts` | Arts & Expression | literature, music, visual and performing arts, film, architecture, design |
| `belief` | Belief & Worldviews | religions and spiritual traditions as siblings, non-religious worldviews, mythology, divination |
| `earth` | Earth | geology, water, atmosphere and climate, physical geography, resources, hazards |
| `everyday` | Everyday Life & Leisure | food, clothing, home, rites of passage, festivals, sport, games, travel |
| `health` | Health & the Human Body | the body, medicine, diseases, public health, traditional medical systems |
| `language` | Language & Communication | linguistics, the language families of the world, writing systems, media |
| `life` | Life | cells, genes, evolution, ecology, the diversity of organisms |
| `matter` | Matter & Energy | physics, chemistry, astronomy, measurement |
| `mind` | Mind & Behaviour | psychology, neuroscience, cognition, development |
| `past` | Human Past | prehistory, history by dated period, by region, by theme; archaeology; method |
| `society` | Society | groups, economy, politics, law, education |
| `technology` | Technology & Making | engineering, computing, energy, industry, agriculture, transport |
| `thought` | Thought & Knowledge | philosophy (all traditions), logic, mathematics, science's methods, traditional knowledge, information science |

599 concepts in three levels below them, each with a scope note, in `seed/compendium/acat/*.tsv`
(readable form: [COMPENDIUM.md](COMPENDIUM.md)). A concept may have several parents
(biochemistry is under chemistry *and* molecular biology).

### 3.3 Facets: the other axes

| Facet | Scheme | Source | State in v0.1 |
|---|---|---|---|
| **Where** | `space` — 278 UN M49 regions, countries and areas, in the six UN languages | UN Statistics Division page, stored as exact bytes | applied: 80 concepts tagged |
| **When** | numeric years on concepts (`time_from`, `time_to`, astronomical numbering) | authored | applied to dated periods |
| **Kind** | `kind` — person, place, event, process, practice, work, idea, norm, symbol system… | authored | defined; applied when entities arrive |
| **How known** | `epistemic` — attributed, corroborated, consensus, contested, hypothesis, held within a tradition, normative, fiction, superseded, refuted | authored | applied: every claim carries one |
| **Language** | label language codes | Wikidata, UN | 489 label languages |

### 3.4 Many schemes, crosswalked

The ACAT circle is one scheme among several. UDC, DDC, LCC and Propædia top classes are stored
beside it, with their captions verified against the publishers' pages (50 of 50 verified), and
connected by SKOS mapping relations (`exactMatch`, `closeMatch`, `broadMatch`, `narrowMatch`,
`relatedMatch`). 572 of 599 ACAT concepts are reconciled with Wikidata (399 exact, 148 close,
22 narrower, 1 broader, 2 related) after a reviewed, three-round process; 27 are recorded as
reviewed-and-unmatched. Only exact and close matches donate their labels in other languages.

### 3.5 Neutrality rules applied to the compendium itself

These are checked by tests (`tests/test_seeds.py`) where they can be:

- **No residual bucket.** No "Other X". Religious traditions (25), philosophical traditions (10)
  and the 24 groupings of the world's languages are equal siblings in alphabetical order.
- **Symmetry from an external standard.** History by region follows the UN M49 regions and
  subregions (5 African, 4 American, 5 Asian, 4 European, 4 Oceanian, plus Antarctica and the
  oceans), not an authored notion of which places matter.
- **Numbers before names for time.** World history is divided into dated spans (3rd millennium
  BCE … 21st century). Named periods such as "Middle Ages" or "Edo period" are regional labels and
  belong to regions.
- **Descent before convenience.** Language families are grouped by established descent;
  groupings that are regional rather than genealogical are labelled "(regional grouping)"; proposed
  families whose unity is debated (Nilo-Saharan) say so.
- **Description, not verdict.** Scope notes say what something is. Evaluations (whether a medical
  tradition works, whether a phenomenon exists) belong in attributed claims with an epistemic
  status, not in the category.

## 4. "Without any bias" — the honest version

Bias cannot be removed from a knowledge base, because a knowledge base *is* a set of choices. The
design goal is therefore **bias-transparency with plurality**:

1. **Attribution over assertion.** The database does not store naked facts. It stores "source S
   (bytes with SHA-512 H) states P". The 4,045 Wikidata claims in this build each name the exact
   response they came from, with Wikidata's own rank.
2. **Plurality instead of a verdict.** A contested matter keeps every account, each attributed
   (`epistemic/contested`); a belief held within a tradition is recorded as that tradition's
   account (`epistemic/tradition`), not judged.
3. **Measured coverage.** `acat audit` counts skew instead of asserting balance. From this build:
   - concepts tagged per UN M49 region: Asia 28, Africa 13, Europe 10, Americas 9, Oceania 9, Antarctica 1;
   - the median number of Wikipedia language editions per domain ranges from 42 (Human Past) to
     118.5 (Life); regional-history items are thinly linked across languages;
   - Wikidata also states 161 of 481 ACAT parent links between matched items; the other 320 are
     not stated there (which is not the same as a disagreement).
4. **Visible, reversible process.** Every reconciliation decision records its method and reviewer;
   every build and import is a ledger row with a receipt and an undo instruction.

### Known biases of this version (so that nobody has to discover them)

- The compendium was authored and the Wikidata reconciliation reviewed by one AI agent in one
  session (the `reviewer` column says so). It needs human review, ideally by several people from
  different traditions and regions.
- Identifiers and scope notes are English. Labels exist in 489 languages, but the authored text
  and the ids privilege English.
- The first text corpus is English Wikipedia, whose coverage is itself skewed by region, gender
  and language.
- `space` is the UN statistical view of places. Disputed territories appear as the UN lists
  them; other views (ISO 3166, national, historical) should be added as further schemes.
- "Wikipedia language editions" measures encyclopedic attention, not importance; two concepts
  matched thin Wikidata items (probability and statistics; geometry and topology) and show
  artificially low coverage — a curation task the audit surfaced.
- The semantic layer is fit on English text, so its neighbourhoods are English-shaped.

## 5. Keeping it updated and finely curated

- **Sources are immutable and dated.** `acat fetch <source>` writes a new sealed corpus named
  `<family>-<yyyymmdd>`; old corpora stay. Fetching is polite (paced, `Retry-After` honoured) and
  every attempt, including refusals, is logged in the corpus.
- **Curated decisions are reviewable text.** The compendium (`seed/compendium/`), the external
  crosswalk and the Wikidata decisions (`seed/crosswalk/acat-wikidata.tsv`) are TSV files: one
  decision per line, diffable, mergeable, reviewable in a pull request. The database is a pure
  function of these files plus the corpora; `acat build` takes about 8 seconds.
- **Nothing is lost.** A concept removed from a seed is deprecated with a ledger entry; sources,
  concepts, claims and ledger rows cannot be deleted (triggers); regenerable rows (labels, edges,
  indexes) are rebuilt from their sources on every build.
- **Two times per claim.** `valid_from`/`valid_to` say when a statement is true of the world;
  `recorded_at`/`superseded_at` say when the catalogue believed it. Both "what was true in 1900?"
  and "what did we believe last year?" stay answerable.
- **The curation loop.** propose (automatic, strict rules) → review (human or model; the
  reviewer is recorded) → accept or reject into the seed files → build → audit → the audit's
  thinnest areas become the next backlog.
- **Integrity on demand.** `acat verify` validates the seeds, re-hashes every stored byte in every
  corpus against its manifest, and recomputes the ledger chain.

## 6. The SQL grepper

`acat grep` searches concepts, corpus passages and labels in every language, and always shows the
SQL it ran (`--explain`, and the `sql` field in the API):

- `words` — FTS5 syntax (`AND`, `OR`, `NOT`, `"phrases"`, `prefix*`, `NEAR(sky god, 5)`), ranked by
  BM25; invalid syntax falls back to plain words and says so;
- `substring` (`-F`) — case-insensitive literals through a trigram index, so it works inside words
  and in scripts without spaces (`物理` finds physics); shorter than three characters, a full scan;
- `regex` (`-E`) — Python regular expressions; the trigram index narrows candidates only when the
  pattern provably contains a required literal, so a match is never missed;
- `--under acat/belief` limits hits to a subtree; `--lang tr` limits labels to a language.

`acat grep-db <file.sqlite> <pattern>` greps every text column of *any* SQLite file read-only —
for databases that are not catalogues at all.

## 7. The particle field

`acat serve` opens the database read-only and serves the particle field (`viz/`, TypeScript,
compiled to `viz/dist/`). Each concept is a particle; hierarchy, relations, crosswalks and semantic
neighbours are springs; everything repels everything else (Barnes–Hut); the thirteen domains carry a
radial spring toward a ring, so the circle of learning emerges from the physics instead of being
drawn. Motion is integrated, never tweened. Domains are identified by position and direct labels,
not by thirteen hues (a scatter of this kind cannot keep more than three colours distinguishable);
colour is reserved for emphasis (search hits, selection) and for one sequential lens: how many
Wikipedia language editions cover each concept — the bias view, made visible.

## 8. The path to "entire world"

| Stage | Scale | What changes |
|---|---|---|
| v0.1 (this) | ~1,000 concepts, 2,705 Wikidata items, 1,935 passages, 121,717 labels, 4,045 claims; 67 MB; 8 s build | — |
| Depth | 10⁴–10⁵ concepts | expand the compendium from Wikidata subclass trees and domain vocabularies, reviewed in batches; add OpenAlex topics (free API key) as a crosswalked scheme |
| Breadth | 10⁶–10⁷ entities | entities (people, places, works, events) with the `kind` facet; claims from Wikidata dumps; SQLite shards per corpus family, attached at query time |
| All of Wikidata | ~10⁸ items, ~10⁹ statements | keep bytes in object storage or a dataset host rather than git, with the same manifests; query the full graph with a dedicated engine (e.g. QLever) or columnar files (DuckDB/Parquet); keep this SQLite catalogue as the curated core |
| Meaning across languages | — | add a multilingual embedding model as a second `model` beside LSA, with a vector index |

At every stage the same five disciplines hold: exact bytes with SHA-512, named sealed corpora,
reviewed text for decisions, a rebuildable database, and a hash-chained ledger.
