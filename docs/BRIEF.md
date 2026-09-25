# The requests and what became of them

## The request, verbatim (2026-09-25)

> we need a database and we need to create a sql grepper and a named corpus as well as a compendium
> for all the categories and everything to use as to create this whole world information as
> semantically and without any bias of any sort.  we basically need to build a particle based
> visualized system where we will try to create (how do you think we can make a database of entire
> world knowledge and how can we categorize it?) a godlike dataset that can be updated so well and so
> fine curated?

## Dispositions

Ordered from truth and loss (D1) to cosmetic (D7). Each line says what it relates to and its receipt.

| D | Part of the request | Disposition | Receipt |
|---|---|---|---|
| D1 | "without any bias of any sort" | **Answered honestly, not promised.** Bias cannot be removed from any selection of knowledge; the design makes it visible and plural instead: attributed claims with epistemic status, contested accounts kept side by side, neutrality rules on the compendium (tested), coverage measured by `acat audit`, and a written list of this version's known biases. | [DESIGN.md §4](DESIGN.md#4-without-any-bias--the-honest-version); `tests/test_seeds.py`; `acat audit` |
| D1 | "can be updated so well and so fine curated" | **Built.** Sealed dated corpora (exact bytes, SHA-512), reviewed seed files as the curated truth, a rebuild in ~8 s, deprecate-not-delete, supersession across corpora, claims with world time and record time, a hash-chained append-only ledger. | `acat verify`; `tests/test_invariants.py`, `tests/test_updates.py` |
| D1 | "we need a database" | **Built.** One SQLite catalogue: 3,671 concepts, 121,717 labels in 489 languages, 4,045 attributed claims, 538 documents / 1,935 passages. | `acatalogue/schema.sql`; `acat stats` |
| D2 | "a named corpus" | **Built.** Five named, dated, sealed corpora holding the exact bytes of every source: `un-m49-20260925`, `external-schemes-20260925`, `wikidata-reconcile-20260925`, `wikidata-entities-20260925`, `wikipedia-en-intros-20260925` (3.9 MB together). | `corpora/`; `acat verify` re-hashes every item |
| D3 | "a compendium for all the categories and everything" / "how can we categorize it?" | **Built (v0.1) and answered.** Thirteen domains on a circle, 599 concepts with scope notes, facets for where (UN M49), when (years), kind and epistemic status, crosswalks to UDC, DDC, LCC, Propædia (captions verified 50/50) and Wikidata (572 reconciled after review). "All categories" is open-ended: depth grows by reviewed expansion. | `seed/`; [COMPENDIUM.md](COMPENDIUM.md); [DESIGN.md §3](DESIGN.md#3-how-to-categorize) |
| D3 | "(how do you think we can make a database of entire world knowledge …?)" | **Answered.** Federate and reconcile open sources over a spine of scoped ids with byte-level provenance; the staged path to all of Wikidata and beyond is written out. | [DESIGN.md §0–2, §8](DESIGN.md) |
| D4 | "a sql grepper" | **Built.** `acat grep`: FTS5 words, trigram substring (any script), regex with a provably safe prefilter, subtree and language filters, the executed SQL shown; `acat grep-db` greps any SQLite file. | `acatalogue/grep.py`; `tests/test_grep.py` |
| D5 | "as semantically" | **Partly.** A semantic layer exists and is named for what it is — LSA (TF-IDF + truncated SVD) over English text — giving neighbours and a seed layout. Multilingual neural embeddings are the next model, to be added beside it, not in its place. | `acatalogue/semantic.py`; `model` table |
| D6 | "a particle based visualized system" | **Built; visual verdict is yours.** TypeScript particle field (compiled, no runtime dependencies): concepts as particles, relations as springs, Barnes–Hut repulsion, the circle of domains emerging from a radial spring, motion integrated not tweened; search through the grepper API; coverage lens. | `viz/`; `acat serve` |
| D7 | "a godlike dataset" | **Aspiration kept, scale stated plainly.** This is a seed of about a thousand concepts, not the world; every mechanism it uses is chosen to hold at the scale of all of Wikidata. | [DESIGN.md §8](DESIGN.md#8-the-path-to-entire-world) |

## Not done in this session, and why

- **Grounding on the owner's existing holdings** (gr8base, `pdf-corpus-20260923/corpus.sqlite`,
  `wish-ledger-20260923/wishes.sqlite`): they live on the owner's machine, which this cloud session
  cannot reach. `acat grep-db <file.sqlite> <pattern>` is ready to search them read-only, and a
  corpus importer for them is the natural next step once their schemas are known.
- **OpenAlex topics**: the API now requires a (free) key; the shared anonymous budget was exhausted.
- **Human review of the compendium and the reconciliation**: both were done by one AI agent in one
  session and are marked as such in the data.

## The second request, verbatim (2026-09-25)

> please do further improvements on it with first proper research and then implementation with
> proper skills please.

## Dispositions of the second request

Research first: six researchers, then one report —
[reports/Improving the acatalogue knowledge base.md](../reports/Improving%20the%20acatalogue%20knowledge%20base.md)
(49 changes ranked D1 → D7, 146 external sources; notes and prototypes in `research_notes/`). Then the
changes below, in that order. Skills used: *deep-research* (the research), *dataviz* (the audit chart:
palette validated with its script on the Papyrus and Sea surfaces), *run* (the particle field driven
live in Chromium against the API, screenshots checked); an independent reviewer read the code.

| D | What | Disposition | Receipt |
|---|---|---|---|
| D1 | Error bodies sealed as data | **Fixed.** Every fetch passes a response check; MediaWiki/World Bank errors inside HTTP 200 are logged and refused; `maxlag=5`, gzip, policy-format User-Agent, patient backoff. | `tests/test_fetch.py`; the statements corpus' fetch log shows 11 refused `maxlag` bodies; every committed response passes the checks |
| D1 | Claims read from query summaries lost statement identity, qualifiers, references, "unknown/no value", revisions | **Fixed.** 48,210 statements from entity JSON, one claim each, with GUID, rank, snak type, revision and a JSON Pointer; 19,771 qualifiers and 10,168 references as rows; summaries superseded per entity. | `tests/test_statements.py`; 500/500 sampled pointers resolve in the sealed bytes |
| D1 | Dates: BCE off by one, Julian dates, text sorting | **Fixed.** Astronomical years, Julian day dates converted, Wikidata century/millennium spans, integer day bounds. | known anchors in `tests/test_statements.py` (1582 reform, October Revolution, Ides of March 44 BCE, J2000) |
| D1 | Search correctness (case folding, combining marks, CJK pairs, regex prefilter, label rowids) | **Fixed** (first commit of the round). | `tests/test_grep.py`: 0 misses against a brute-force scan on randomized needles and regexes |
| D1 | In-place schema upgrade without loss | **Built.** v1 → v4 migrations, each copying or adding and ledgered. | migration tests; the real database kept all 4,045 claims through v2 → v4 |
| D2 | Bias: counts without baselines | **Built.** Regional shares vs population, land area and equal shares, Wilson intervals, JSD with bootstrap and a random-sampling null, entropy, Gini; sibling parity; sourced-statement share; stored per build. Sitelinks without the bot-generated Cebuano and Waray editions. | `tests/test_audit.py` (Wilson values match published ones); `acat audit`; `corpora/worldbank-wdi-20260925` |
| D2 | Machine proposals indistinguishable from human decisions | **Built.** A review ledger (`seed/reviews/`, `acat review`), applied on top of proposals; agent reviews never decide; the audit counts deciders (572 AI, 0 human so far). | `tests/test_review.py` (a real build where an objection stops label copying) |
| D3 | "as semantically": is the semantic layer any good across languages? | **Measured, then extended.** Leave-one-language-out over 28 languages (11,486 queries): the local dense model finds a concept from its name in a hidden language with MRR@10 0.775 [0.768, 0.783], against 0.388 for the best lexical system and 0.016 for LSA. Its weakest languages (Māori 0.130, Quechua 0.167, Yoruba 0.398) are recorded as a bias of the model, and fusing it with the lexical rankings lowers the score (−0.190). A leak found in review (language variants such as zh-hans stayed visible) was fixed before these numbers. | `acat eval` run 2; `tests/test_eval.py`; [DESIGN.md §6.1](DESIGN.md#61-semantic-search-measured-before-it-is-trusted) |
| D5 | Particle field: settling time, no pause, no non-visual route, hairball | **Built; the visual verdict is yours.** Baked layout (0.2 s to first paint instead of 23 s; the same 2,656 steps in Node and Chromium), Pause motion, an ARIA tree view, cross-cluster links on demand, numbers on the coverage ramp, the audit chart, statement claims with their evidence, no overlapping labels on phones. | 26 viz tests; 4 bake tests (two bakes identical); live Playwright run with no console errors |

### Not done in this round, and why

- **Your review.** Every crosswalk decision is still an AI agent's; the queue is ready
  (`acat review queue`). Whether unreviewed `exactMatch` links should be downgraded to `closeMatch`
  until a person looks at them is a policy choice for you, not for me.
- **The Sea theme's surface colour** is still the assumed `#0f1c21`.
- **Constraint checks from Wikidata's own property constraints (report 2.4), tamper evidence beyond the
  hash chain (2.8), dumps and EventStreams for scale (tier 4), WebGL and workers (6.3–6.7)**: planned in
  the report, not needed at today's size, not built.
- **Language-region diversity per concept and label coverage against speaker shares** (report 3.5,
  second half) need a language → region table with a source; not built.

## The third request, verbatim (2026-09-25)

> use all of those sources as well as a lot more (selectable by user to add to their starting point
> too) to then naturally download and meanwhile make ready of the systems and unpack our structure as
> pristinely ready to integrate those downloaded databases (perfectly orderedfully ıntegrated to sql,
> with perfect structuring.) converted to ensure made lean and gotten most semantic info while also
> making it local.

## Dispositions of the third request

Research first: four researchers checked 142 candidate sources live on 2026-09-25 (URL, size, licence,
languages, perspective). Their rows, and the script that curated them into the registry, are in
`research_notes/Open knowledge sources registry/`. Then the machinery, then a real run of the starter
preset into this machine's catalogue.

| D | Part of the request | Disposition | Receipt |
|---|---|---|---|
| D1 | "naturally download" | **Built and run.** Resumable downloads (HTTP Range with If-Range), SHA-512 computed while streaming, publisher checksums checked (a file that fails is kept aside, never sealed), one connection per host, 429/503 waited out. Each source's files are sealed as a dated manifest that `acat verify` re-hashes. | `tests/test_download.py` (10); starter run: 21 sources, 336 MB downloaded and sealed |
| D1 | "perfectly ordered, integrated to SQL, with perfect structuring" | **Built and run.** One lean layout for every source (terms in source order, interned languages and predicates, one direction per relation, typed attributes). Integration records provenance: every raw file and lean file by SHA-512, each integration in `lean_integration`, and one ledger row per integration. A new version supersedes the old one; deselecting retires a source; nothing is deleted. | `tests/test_convert.py` (13; the same vocabulary gives the same lean content in N-Triples, RDF/XML and Turtle; the same bytes give the same file); `tests/test_sources.py` (10, end to end into a real build); real counts match the publishers' (Glottolog 27,177 − 380 bookkeeping = 26,797; GCMD 3,780; IANA 9,296; OEWN hypernymy 93,395) |
| D2 | "use all of those sources as well as a lot more" | **Registered: 129 sources.** 45 are recommended and 21 make up the starter preset. The rest are listed with the reason they are not recommended: a licence (non-commercial, no derivatives), access (a login, a form, a blocked site), size, or the need to consult the community that governs them. | `seed/sources/registry.tsv`; `acat sources list` |
| D2 | "selectable by user to add to their starting point too" | **Built.** 8 presets; `select` and `deselect`; `add` for sources of your own (a URL, or a file on your machine: a SQLite database is copied through the backup API) with a declared column mapping. | `acat sources add …`; `test_a_users_own_file` |
| D3 | "gotten most semantic info" | **Built.** The layout keeps: names in every language and of every kind (hidden, broader, narrower and related names); typed relations; definitions and notes; outward links. Links resolve across sources through the registry's identifier prefixes, with Wikidata as the hub. Wordnets are keyed by the Interlingual Index. | Starter: 385,565 concepts, 2,773,359 names in 1,135 languages, 403,194 broader edges, 69,449 proposed mappings (1,137 through Wikidata's identifiers) |
| D3 | "made lean" | **Built and measured.** Nothing is stored twice: inverses are folded, symmetric relations stored once, derivable siblings dropped. Every drop is counted in the file. | Starter lean files: 343 MB with word indexes, against 1,465 MB of uncompressed downloads (336 MB compressed) |
| D4 | "while also making it local" | **Built.** The store, the catalogue and the search all run on this machine. Once downloaded, nothing needs the network. | `store/` (or `$ACAT_STORE`); `acat sources search` reads lean files in place |
| D4 | "meanwhile make ready of the systems" | **Built.** The stages overlap: downloads run in threads, conversion runs in processes as each source lands, and each source is integrated as soon as it is converted. | the starter run's log: conversions began while GeoNames' 205 MB of names were still downloading |
| D5 | the catalogue's surfaces | **Built.** The inspector lists "In other sources" for a concept, and attached terms open in place. | `/api/sources`, `/api/sources/search`, `/api/sources/record`; viz tests 26 |

### Not done, and why

- **PubChem's periodic table.** For 15 minutes PubChem's front end answered this Python client with 503
  and Retry-After, while curl, with the same User-Agent, got 200. The refusal is respected: the source
  is out of the starter, and a hand-downloaded copy can be added with `acat sources add --path`.
- **70 registered sources have no converter yet** (`raw`). They download and seal, and wait for a
  converter. Candidates by value: Glottolog CLDF and WALS, Pleiades, Natural Earth, UN WPP (as claims
  on the M49 places), Wiktionary extracts, ConceptNet.
- **Licence checks for the owner.** UDC Summary moved to CC BY-NC 4.0 in 2026, and OCLC's terms limit
  storing DDC. The catalogue already quotes ten main-class captions of each; someone with authority
  should decide.
- **Consent before ingest.** Māori subject headings (Ngā Upoko Tukutuku), the Brian Deer classification
  (Xwi7xwa) and AIATSIS thesauri are listed without files. Their communities come first.
- **Regional gap.** The research found no open subject system published from Africa, the Arab world
  or South Asia. DeCS (Latin America) needs a licence agreement. The starter's publishers are mostly in
  the USA and Europe, with two Japanese institutions (NDL, JLA) and several international bodies.
- **Turkish dotted capital İ.** The word index keeps combining marks inside words (Devanagari and Tamil
  need that), so "İstanbul" does not match "istanbul" in words search. Substring search folds it
  correctly.
- **Build time.** With the starter integrated, `acat build` rebuilds the search indexes over 2.8
  million names, which takes minutes rather than 9 s. Attach mode keeps large sources out of the
  catalogue.
- **A privacy incident, reported plainly.** One researcher's first request to the Wikidata API
  carried the owner's e-mail address in its User-Agent, against the owner's instruction. Every later
  request, and every request the downloader makes, names only the project.
