# The founding brief and what became of it

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
