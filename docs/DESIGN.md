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

This repository ingests five of these today — UN M49, Wikidata (entity summaries and, since the
second round, every statement of the reconciled items with its qualifiers and references), English
Wikipedia, the top classes of UDC/DDC/LCC/Propædia, and World Bank population and land area as the
audit's declared baselines — and is designed so the rest plug into the same pipeline.

## 2. The layers

Each layer has one job and one invariant, enforced in the schema (`acatalogue/schema.sql`), not by
convention.

| Layer | What it holds | Invariant | Where |
|---|---|---|---|
| **Bytes** | the exact bytes of every input (seed file, fetched response) | addressed by SHA-512; never changed, never deleted | `source`, corpus `sqlar` |
| **Named corpora** | dated collections of sources, e.g. `wikipedia-en-intros-20260925` | sealed after fetching; a sealed corpus refuses writes | `corpora/*/corpus.sqlite` |
| **Text** | documents and passages extracted from corpora | offsets point back into the document text; each document names its source hash | `document`, `passage` |
| **Compendium** | concept schemes: labels in every language, broader (several parents allowed), related, crosswalks, facets | identities are deprecated, never deleted | `scheme`, `concept`, `label`, `broader`, `related`, `mapping`, `facet` |
| **Claims** | statements: subject – predicate – object/value, one row per source statement (its id, rank, snak type — value, "unknown value" or "no value" — and a JSON Pointer into the source bytes); qualifiers and references as ordered rows | every claim names its source bytes and carries an epistemic status and two times (when true in the world, with integer day bounds that sort correctly across BCE; when recorded, from the bytes' retrieval time); a newer reading supersedes, never deletes | `claim`, `claim_qualifier`, `claim_reference`, `v_claim_*` |
| **Review** | people's decisions on machine proposals: approve, revise, object — with reviewer, declared perspective, date and rationale | proposals and decisions are separate records; an agent's review is never decisive | `seed/reviews/`, `review` |
| **Semantic** | vectors, neighbours and a 2-D layout, labelled by the method that made them; the particle layout baked by the browser's own physics | a new method is added beside, never silently swapped | `model`, `embedding`, `neighbor`, `layout` |
| **Measurement** | bias audits against declared baselines; retrieval evaluations | every run is stored with the ledger head it describes | `baseline`, `audit_*`, `eval_*` |
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
3. **Measured coverage, against declared baselines.** `acat audit` measures skew instead of
   asserting balance, and every build stores the run (`audit_run`, `audit_metric`). A count alone
   says nothing — "13 African concepts" is only skewed relative to something — so each region's share
   of the place-tagged concepts is compared with three declared baselines: its share of the world's
   population (World Bank 2024), of land area (2023), and an equal share. Ratios come with 95% Wilson
   intervals; the divergence of the whole distribution (Jensen–Shannon, in bits) comes with a
   bootstrap interval and is compared with what random sampling from the baseline itself produces.
   From this build (65 place-tagged concepts; 534 carry no place, itself a finding):
   - against population, Asia is below parity (0.67×, interval 0.48–0.87×) and Oceania far above
     (23×, 12–41×); Africa, the Americas and Europe cannot be told apart from parity at this size;
   - against equal shares Asia is above parity (2.4×) — the same catalogue reads as over- or
     under-weighting Asia depending on the baseline, which is why no single "bias score" is given;
   - the divergence exceeds random sampling against all three baselines at region level;
   - sibling parity flags subtrees three or more times their siblings' median (for example
     *Religious and spiritual traditions*, 26 concepts, among siblings with a median of 1);
   - only 8,222 of 48,210 current Wikidata statements about these concepts cite a source beyond
     "imported from a Wikimedia project"; for the hierarchy statements the check below compares
     against, 247 of 2,441;
   - Wikidata also states 161 of 481 ACAT parent links between matched items; the other 320 are
     not stated there (which is not the same as a disagreement).
4. **Visible, reversible process.** Every reconciliation decision records its method and who made
   it; a machine's proposal and a person's decision are separate records (`acat review`), and the
   audit counts them: today 572 accepted crosswalks were decided by an AI agent and none has yet been
   reviewed by a person. Every build and import is a ledger row with a receipt and an undo instruction.

### Known biases of this version (so that nobody has to discover them)

- The compendium was authored and the Wikidata reconciliation decided by one AI agent in one
  session (the `reviewer` column says so; the audit counts it). It needs human review, ideally by
  several people from different traditions and regions; `acat review queue` lists what awaits them,
  `exactMatch` first because it is transitive.
- Identifiers and scope notes are English. Labels exist in 489 languages, but the authored text
  and the ids privilege English.
- The first text corpus is English Wikipedia, whose coverage is itself skewed by region, gender
  and language.
- `space` is the UN statistical view of places. Disputed territories appear as the UN lists
  them; other views (ISO 3166, national, historical) should be added as further schemes.
- "Wikipedia language editions" measures encyclopedic attention, not importance. It leaves out the
  Cebuano and Waray editions, which a bot (Lsjbot) generated en masse; 310 concepts' counts change.
  Two concepts matched thin Wikidata items (probability and statistics; geometry and topology) and
  show artificially low coverage — a curation task the audit surfaced.
- Only 65 of 599 concepts carry a place; the regional audit describes those 65, and its intervals
  are wide. The population and area baselines lack 33 of 248 UN M49 areas (the World Bank does not
  report them), and the World Bank's aggregates are excluded by its own classification.
- The semantic layer is fit on English text, so its neighbourhoods are English-shaped.

## 5. Keeping it updated and finely curated

- **Sources are immutable and dated.** `acat fetch <source>` writes a new sealed corpus named
  `<family>-<yyyymmdd>`; old corpora stay, and a corpus that is not sealed never feeds a build.
  Fetching is polite: a policy-format User-Agent, `maxlag=5` for Wikimedia APIs, gzip (the decoded
  bytes are what is hashed), `Retry-After` honoured, and busy signals waited out with backoff. Every
  response passes a check before it is stored: MediaWiki and the World Bank report errors inside HTTP
  200 bodies, and such a body is logged as refused, never sealed as data (the 2026-09-25 statements
  fetch refused eleven `maxlag` bodies). Every attempt is logged in the corpus.
- **Statements, not summaries.** Wikidata claims are read from entity JSON, one per statement, with
  its id, rank, snak type, the entity revision and a JSON Pointer to it in the stored bytes;
  qualifiers and references are rows. The earlier query-service summaries of the same entities are
  superseded (kept, marked), per entity and only by a newer reading.
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
- **The curation loop.** propose (automatic, strict rules; the proposer is recorded) → a person
  reviews (`acat review approve|revise|object`, with a declared perspective and a rationale; the
  decision goes to `seed/reviews/<name>.tsv`) → build (the latest human decision applies on top of
  the proposal; an objection takes a mapping out of use, a revision can change its relation) →
  audit → the audit's thinnest areas and sibling-parity flags become the next backlog. Views
  (`v_claim_current`, `v_claim_truthy`, `v_claim_evidence`) filter instead of deleting.
- **Integrity on demand.** `acat verify` validates the seeds, re-hashes every stored byte in every
  corpus against its manifest, and recomputes the ledger chain.

## 6. The SQL grepper

`acat grep` searches concepts, corpus passages and labels in every language, and always shows the
SQL it ran (`--explain`, and the `sql` field in the API):

- `words` — FTS5 syntax (`AND`, `OR`, `NOT`, `"phrases"`, `prefix*`, `NEAR(sky god, 5)`), ranked by
  BM25; invalid syntax falls back to plain words and says so. Combining marks stay inside words
  (Devanagari, Tamil, vocalised Arabic are no longer split), and a query in Chinese, Japanese or
  Korean is matched through an index of overlapping character pairs, so two-character words are found;
- `substring` (`-F`) — case-insensitive in exactly one sense everywhere: Python's `re.IGNORECASE` on
  NFC-normalised text (so "istanbul" finds "İstanbul" and "ARI" finds "arı"). A trigram index over
  each text's *case key* narrows the candidates and Python checks each one;
- `regex` (`-E`) — Python regular expressions; a trigram query is extracted from the pattern with
  Russ Cox's method (alternations and case-insensitive patterns included), and the regex decides
  every hit. Patterns that require nothing indexable scan every row;
- no missed matches is a tested property, not a promise: `tests/test_grep.py` compares the indexed
  paths with a plain Python scan over all labels for randomised needles and regexes;
- `--under acat/belief` limits hits to a subtree; `--lang tr` limits labels to a language.

`acat grep-db <file.sqlite> <pattern>` greps every text column of *any* SQLite file read-only —
for databases that are not catalogues at all.

### 6.1 Semantic search, measured before it is trusted

"Semantically" is a claim about retrieval, so it is measured. `acat eval` runs a leave-one-language-
out test: for each of 28 languages chosen across scripts and regions (Spanish, German, Turkish,
Vietnamese, Indonesian, Russian, Kazakh, Greek, Armenian, Georgian, Arabic, Persian, Urdu, Hebrew,
Hindi, Bengali, Tamil, Chinese, Japanese, Korean, Thai, Burmese, Swahili, Hausa, Yoruba, Amharic,
Quechua, Māori), every ACAT concept's preferred label in that language becomes a query whose one
right answer is the concept, and every label in that language — and in its variants (Chinese hides
zh-hans, zh-tw …; German hides de-ch; Kazakh hides kk-cyrl …) — is left out of the index while it
runs: the lexical indexes are rebuilt without them, so they take no candidate slot and count in no
statistic. A system has to find the concept through the other languages' names — the situation of a
reader whose language the catalogue covers thinly. English is left out: the catalogue is written
in it. Every query and every rank is stored (`eval_*` tables); intervals are stratified bootstrap
percentiles, comparisons paired randomization tests.

The systems compared: FTS5 words (bm25); character-trigram similarity (cognates and
transliterations); the LSA layer, folding the query in; multilingual-e5-large-instruct, a dense
multilingual model run locally from its own ONNX export and pinned by revision and file hashes
(`acat embed`; each vector is keyed by the SHA-256 of its text, so the labels a build regenerates
find their vectors again and no vector can drift onto another label); and reciprocal rank fusion
(k = 60). All but LSA search the same index: the
preferred and alternative labels of the ACAT concepts.

Results (run 2, 11,486 queries; macro MRR@10 over the 28 languages, 95% intervals):

| System | MRR@10 | Recall@10 | Worst language |
|---|---|---|---|
| dense (multilingual-e5-large-instruct) | **0.775** [0.768, 0.783] | 0.862 | Māori 0.130 |
| fusion of words, trigrams and dense | 0.585 [0.577, 0.593] | 0.755 | Māori 0.093 |
| character trigrams | 0.388 [0.381, 0.395] | 0.445 | Korean 0.012 |
| fusion of words and trigrams | 0.381 [0.373, 0.388] | 0.448 | Korean 0.012 |
| FTS5 words | 0.277 [0.269, 0.283] | 0.310 | Korean 0.006 |
| LSA (English text) | 0.016 [0.013, 0.018] | 0.021 | Amharic 0.000 |

What it says:

- **The dense model is the semantic layer this catalogue lacked.** It beats words by +0.499 and
  the best lexical system by +0.395 (p < 0.001, paired randomization). The gap is widest where names
  share no letters across scripts: Greek 0.886 against 0.071 with trigrams, Korean 0.849 against
  0.012, Thai 0.856 against 0.018.
- **Plain rank fusion hurts.** Fusing the dense ranking with the weak lexical rankings loses 0.190
  against dense alone (p < 0.001). Equal-weight fusion is not a default to adopt blindly.
- **The model is itself a bias, now measured.** Its six worst languages are Māori 0.130, Quechua
  0.167, Yoruba 0.398, Hausa 0.466, Amharic 0.570 and Swahili 0.628, against 0.97–0.99 for Spanish,
  Russian, German and Chinese. Speakers of the languages with the least training text are served
  worst, so the catalogue will not call the dense layer neutral.
- **LSA is not a cross-language system.** It is fit on English text and scores 0.016; it stays as a
  labelled baseline.
- **The leak that was fixed.** Run 1 hid only the exact language tag. Chinese queries then found
  their own string under zh-hans in 400 of 536 cases, and words scored 0.866 for Chinese instead of
  0.670. Run 1 stays stored, marked by run 2's parameters; the dense model moved by 0.010 at most,
  because it finds concepts through the other languages anyway.

Adopting dense search in the grepper, alone or with weighted fusion, is a decision for the
catalogue's owner. These numbers are its evidence.

## 7. The particle field

`acat serve` opens the database read-only and serves the particle field (`viz/`, TypeScript,
compiled to `viz/dist/`). Each concept is a particle; hierarchy, relations, crosswalks and semantic
neighbours are springs; everything repels everything else (Barnes–Hut); the thirteen domains carry a
radial spring toward a ring, so the circle of learning emerges from the physics instead of being
drawn. Motion is integrated, never tweened.

The layout is **baked**: `acat bake` runs the same compiled physics in Node from the same
deterministic placement until the field rests (2,656 steps — exactly the steps Chromium needs live),
and stores the positions as a layout model named by the physics' SHA-512. The page adopts them and
opens at rest in about 0.2 s instead of 23 s of settling, and every viewer sees the same layout
whatever their engine's floating point; the physics then only answers disturbances (drags). A
**Pause motion** control (key `p`, WCAG 2.2.2) stops everything that moves on its own. A **tree
view** (ARIA tree pattern, keyboard operable, lazily expanded) gives the hierarchy a non-visual
route and follows the selection. Links between clusters are drawn for the particle under the
pointer or selected, or all at once on request, so the structure is not hidden under its
cross-links. The audit panel draws the representation ratios against the chosen baseline as
dots with intervals and a parity line, with a table view beside them. Domains are identified by position and direct labels,
not by thirteen hues (a scatter of this kind cannot keep more than three colours distinguishable);
colour is reserved for emphasis (search hits, selection) and for one sequential lens: how many
Wikipedia language editions cover each concept — the bias view, made visible.

## 8. The path to "entire world"

| Stage | Scale | What changes |
|---|---|---|
| v0.1 | ~1,000 concepts, 2,705 Wikidata items, 1,935 passages, 121,717 labels, 4,045 claims; 67 MB; 8 s build | — |
| v0.2 (this) | the same compendium; 10,131 Wikidata items named, 48,210 statements with 19,771 qualifiers and 10,168 references; audits and evaluations stored; 9 s build | statement-level claims, declared baselines, a review ledger, a baked layout, a measured search |
| Depth | 10⁴–10⁵ concepts | expand the compendium from Wikidata subclass trees and domain vocabularies, reviewed in batches; add OpenAlex topics (free API key) as a crosswalked scheme |
| Breadth | 10⁶–10⁷ entities | entities (people, places, works, events) with the `kind` facet; claims from Wikidata dumps; SQLite shards per corpus family, attached at query time |
| All of Wikidata | ~10⁸ items, ~10⁹ statements | keep bytes in object storage or a dataset host rather than git, with the same manifests; query the full graph with a dedicated engine (e.g. QLever) or columnar files (DuckDB/Parquet); keep this SQLite catalogue as the curated core |
| Meaning across languages | — | add a multilingual embedding model as a second `model` beside LSA, with a vector index |

At every stage the same five disciplines hold: exact bytes with SHA-512, named sealed corpora,
reviewed text for decisions, a rebuildable database, and a hash-chained ledger.
