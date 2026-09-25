# Data models, provenance and validation in large open knowledge bases, applied to acatalogue

*Research date: 2026-09-25. "Local" findings come from reading `acatalogue/schema.sql` and from read-only queries of `data/acatalogue.sqlite` in this repository on that date (SQLite 3.45.1 in the Python runtime). **[OLDER]** marks a past state of a project. **[SUPERSEDED]** marks a replaced proposal. **(excerpt)** marks a fact taken from a search-result excerpt that I did not read in the full page.*

---

## 1. How do Wikidata, YAGO 4.5, DBpedia, BabelNet and KBpedia model statements, time, uncertainty and provenance? What do they drop or clean, and why?

### Takeaway
Wikidata has the richest statement model of the five. A statement has an identity (a GUID), a main snak, ordered qualifiers and hash-identified references. Each snak is one of three types (value, unknown value, no value). Statements carry one of three ranks, dates carry a precision and a calendar, and quantities carry bounds. Every downstream knowledge base simplifies this model:
- **YAGO 4.5** keeps only "truthy" facts that pass its schema checks. It removes about 6% of facts on domain and range. It drops all references and the bounds and units of quantities, and it removes whole families of entities. Start and end times survive as RDF-star annotations.
- **DBpedia** moves triples that fail type checks into separate "disjoint" files instead of deleting them.
- **BabelNet and KBpedia** integrate concepts and words. Neither has statement-level qualifiers.

acatalogue already keeps Wikidata's rank for each claim. Today it drops qualifiers, references, snak types, date precision and statement identity.

### Cited Findings

**Wikidata / Wikibase (the reference model)**
- A statement consists of a main snak, qualifier snaks, a list of references and a rank. "Every Statement refers to one particular Entity, called the subject of the Statement." — [Wikibase/DataModel (mediawiki.org, last updated 8 Apr 2026)](https://www.mediawiki.org/wiki/Wikibase/DataModel)
- There are three kinds of snak:
  - **PropertyValueSnak**: a normal value.
  - **PropertySomeValueSnak** ("unknown value"): "Ambrose Bierce (subject) has an unknown date of death (property), yet we can be certain that he is not among the living persons."
  - **PropertyNoValueSnak** ("no value"): "Circle (subject) has no angle (property)."
  — [Wikibase/DataModel](https://www.mediawiki.org/wiki/Wikibase/DataModel)
- A reference is a set of snaks. It can be "simple (single Snak, e.g., URL)" or "complex (title, author, publisher, chapter, page)". — [Wikibase/DataModel](https://www.mediawiki.org/wiki/Wikibase/DataModel)
- In the JSON serialization:
  - A statement has `id` (a GUID such as `Q60$5083E43C-228B-4E3E-B82A-4CB20A22A3FB`), `mainsnak`, `type` (`"statement"`; historically `"claim"`), `rank` (preferred/normal/deprecated), `qualifiers`, `qualifiers-order` and `references`.
  - Each reference has `hash`, `snaks` and `snaks-order`.
  - `snaktype` is `value`, `somevalue` or `novalue`. `datavalue` is present only when the snak type is `value`.
  - Qualifier snaks and reference snaks carry a `hash`.
  — [Wikibase JSON format docs](https://doc.wikimedia.org/Wikibase/master/php/docs_topics_json.html)
- I checked a live entity on 2026-09-25. The Special:EntityData JSON for Q4115189 has top-level `lastrevid` (2549002145) and `modified` (2026-09-24T10:35:11Z). One statement had:
  - id `Q4115189$9fa7b6ce-463e-4505-9025-afee37abef55`;
  - a 40-hex-character main-snak hash;
  - one reference with a 40-hex `hash`, plus `snaks` and `snaks-order` (reference property P3452 "inferred from").
  — [Special:EntityData/Q4115189.json](https://www.wikidata.org/wiki/Special:EntityData/Q4115189.json)
- The Time datatype has these fields:
  - `time`: ISO 8601 style, with a signed year of 1–16 digits.
  - `timezone`: an offset in minutes.
  - `before` / `after`.
  - `precision`: 0–14, where 0 is a billion years, 8 a decade, 9 a year, 10 a month, 11 a day, 12 an hour, 13 a minute and 14 a second.
  - `calendarmodel`: the display calendar. Data is saved in the proleptic Gregorian calendar.
  — [Wikibase/DataModel](https://www.mediawiki.org/wiki/Wikibase/DataModel)
  The JSON docs describe `before`/`after` as "Currently unused, may be dropped in the future". — [Wikibase JSON docs](https://doc.wikimedia.org/Wikibase/master/php/docs_topics_json.html)
- Help:Dates covers storage, calendars, uncertainty and pitfalls. — [Help:Dates](https://www.wikidata.org/wiki/Help:Dates)
  - **Storage.** Coarse precisions are stored with zeroed parts: "+2026-09-00T00:00:00Z" for a month and "+2026-00-00T00:00:00Z" for a year. Precisions 12–14 (hour, minute, second) are "not currently supported"; a feature request exists.
  - **Calendars.** The proleptic Gregorian calendar (Q1985727) is used from 1583 on; the proleptic Julian calendar (Q1985786) before 1583. If the calendar is unknown, add the qualifier "sourcing circumstances (P1480) = unspecified calendar (Q18195782)".
  - **Uncertain dates.** "Circa" is P1480 = circa (Q5727902). Ranges use earliest date (P1319) and latest date (P1326). Refine date (P4241) expresses "beginning of", seasons and similar.
  - **Year 0.** The RDF export follows XSD 1.1, where year 0 is 1 BCE. The JSON export writes 1 BCE as -0001.
  - **Pitfall.** Century (precision 7) and millennium (precision 6) are read in the strict historical sense, running from a year ending in 01 to a year ending in 00.
- A Quantity has `amount`, `lowerBound`, `upperBound` and `unit` (for example "12300 +/- 50") — [Wikibase/DataModel](https://www.mediawiki.org/wiki/Wikibase/DataModel). In JSON, amounts are signed decimal strings (such as "+10.38") and the unit is "1" for unitless values — [Wikibase JSON docs](https://doc.wikimedia.org/Wikibase/master/php/docs_topics_json.html)
- Ranks — [Help:Ranking](https://www.wikidata.org/wiki/Help:Ranking):
  - **Preferred**: "the most current statement or statements that best represent consensus (be it scientific consensus or the Wikidata community consensus)".
  - **Normal**: the default. It implies "no judgement or evaluation of a value's accuracy".
  - **Deprecated**: for statements "known to include errors… or that represent outdated knowledge", including information "that was never correct, but was at some point thought to be". It is not for accurate historical data that carries time qualifiers.
  - Reason qualifiers: P7452 "reason for preferred rank" and P2241 "reason for deprecated rank".
  - Verifiability: "All statements, including deprecated ones, must be verifiable in the sense that a source makes the claim whether or not the claim is true."
- P2241 values must be instances of "Wikibase reason for deprecated rank" and are limited by a one-of constraint; a statement can carry several. — [Property:P2241](https://www.wikidata.org/wiki/Property:P2241) Values include:
  - withdrawn identifier value (Q21441764)
  - incorrect value (Q41755623)
  - error in referenced source (Q29998666)
  - superseded by later scholarship (Q80122004)
  - typographical error (Q734832)
  - link rot (Q1193907)
  - conflation (Q14946528)
  - refers to different subject (Q28091153)
  - deprecated identifier value (Q67125514)
  - demolished or destroyed (Q56556915)
  - does not exactly match (Q42415624)
- P1480 "sourcing circumstances" is "Qualification of the truth or accuracy of a source". It can be used as a qualifier or in references. — [Property:P1480](https://www.wikidata.org/wiki/Property:P1480) Values include:
  - circa (Q5727902), near (Q21818619), approximately (Q60070514), estimate (Q37113960)
  - presumably (Q18122778), possibly (Q30230067), probably (Q56644435), hypothetically (Q18603603), allegedly (Q32188232)
  - disputed (Q18912752), according to some sources (Q59783740)
  - posthumous, unofficial
- The RDF mapping — [Wikibase RDF Dump Format](https://www.mediawiki.org/wiki/Wikibase/Indexing/RDF_Dump_Format):
  - Statements become nodes (`wds:`) linked through `p:`/`ps:`/`pq:`. References hang off `prov:wasDerivedFrom`.
  - "Truthy statements represent statements that have the best non-deprecated rank for a given property". Preferred statements win if any exist, otherwise normal ones; they are typed `wikibase:BestRank`.
  - "No value" becomes a `wdno:` class defined with `owl:complementOf`. "Unknown value" becomes a blank node, or a Skolem IRI in the Wikidata Query Service (WDQS).
  - References are `wdref:` nodes named by a content hash: "The same reference will be usually represented with single node, though duplicate reference nodes are possible".
  - Full value nodes carry `wikibase:timePrecision`, `timeCalendarModel`, `quantityUpperBound`, `quantityLowerBound` and `quantityUnit`.
- Help:Sources — [Help:Sources](https://www.wikidata.org/wiki/Help:Sources):
  - Use "stated in" (P248) for publications and "reference URL" (P854) for websites and databases. Supporting properties include retrieved (P813), title (P1476), language of work (P407), page(s) (P304), archive URL (P1065), archive date (P2960) and quotation (P1683).
  - Create an item for any source that is not a webpage, so the source's metadata sits on the source item rather than in each reference.
  - "Statements that are only supported by 'imported from Wikimedia project (P143)' are not considered sourced statements."
  - "It is recommended to not add a second reference which is explicitly based on the same source".
- Lexemes — [Lexicographical data documentation](https://www.wikidata.org/wiki/Wikidata:Lexicographical_data/Documentation):
  - A lexeme has an L-id, lemmas (with IETF language tags), a language item, a lexical-category item and statements.
  - Forms (`L…-F…`) carry representations and grammatical features.
  - Senses (`L…-S…`) carry glosses and link to items through "item for this sense (P5137)".
  - The main, Property, Lexeme and EntitySchema namespaces are CC0.
- Scale:
  - Wikidata:Statistics showed "123,431,511 items" when I retrieved it on 2026-09-25. The page's own dating is inconsistent. — [Wikidata:Statistics](https://www.wikidata.org/wiki/Wikidata:Statistics)
  - "As of early 2025, Wikidata had 1.65 billion item statements". This is a secondary source. — [Wikipedia: Wikidata](https://en.wikipedia.org/wiki/Wikidata)
  - The December 2020 dump had 1,149,471,184 statements. — [Shenoy et al.](https://arxiv.org/abs/2107.00156)
  - The dump was "766 GB as of April 2023". — [YAGO 4.5](https://arxiv.org/abs/2308.11884)
- Reference coverage:
  - "About 68% of Wikidata statements have at least one reference", from a study of six topical subsets comparing 2016 and 2021 dumps. — [Beghaeiraveri, Gray & McNeill, "Reference Statistics in Wikidata Topical Subsets"](https://researchportal.hw.ac.uk/files/53252708/Reference_Statistics_in_Wikidata_Topical_Subsets_corrected_version.pdf) (excerpt)
  - RQSS (Semantic Web Journal, 2024) says "About 73% of Wikidata statements have provenance metadata". It scores overall referencing quality in the evaluated subsets at "0.58 out of 1", using 40 metrics grouped into 22 aspects and 6 categories. — [RQSS](https://www.semantic-web-journal.net/content/rqss-referencing-quality-scoring-system-wikidata)
  - The 68% and 73% figures disagree. The RQSS page's reviews also flag the paper's inconsistent phrasing.
- Wikidata quality — [Shenoy, Ilievski, Garijo, Schwabe & Szekely, J. Web Semantics 2021](https://arxiv.org/abs/2107.00156):
  - 76.5M statements were removed, describing 26.2M distinct subjects.
  - There were 10M deprecated statements in the January 2021 dump.
  - More than 2M redirected nodes affect more than 20M statements (26% of removed statements).
  - Violation ratios for mandatory constraints were 0.08% (type) and 0.03% (value type). For normal-status constraints they were 0.76% and 0.65%. For suggested type constraints they reached "as many as 20%".
  - Mandatory item-requires-statement constraints were violated at 0.02% and inverse constraints at 1.9%. Suggested item-requires-statement constraints peaked at 8%.

**YAGO 4.5** (SIGIR 2024; data version yago-4.5.0.2)
- The paper lists these problems with Wikidata's taxonomy — [YAGO 4.5 paper](https://arxiv.org/abs/2308.11884):
  - "more than 2.7M classes of which only 3% are instantiated";
  - 1M subclasses of chemical entity that have no instance;
  - 47 pairs of classes that are subclasses of each other, and 15 cycles of length 3 or more;
  - "constraints are defined but not enforced";
  - classes and instances mixed: scientist (Q901) is both a subclass of person and an instance of profession.
- **[OLDER]** YAGO 4 took instances from Wikidata but classes from Schema.org, "abandoning nearly the entire class taxonomy of Wikidata". YAGO 4.5 brings Wikidata's lower taxonomy back under a hand-curated Schema.org upper taxonomy. It keeps 8 Schema.org top-level classes: CreativeWork, Event, Organization, Taxon, Person, Place, Product and Intangible. "All top-level classes are declared disjoint (except places/organizations, and products/creative works)". A ninth class, `yago:FictionalEntity`, is disjoint with nothing, because anything can also exist in fiction. There are 41 upper classes in all, "expressed as SHACL constraints". — [YAGO 4.5](https://arxiv.org/abs/2308.11884)
- Taxonomy cleaning — [YAGO 4.5](https://arxiv.org/abs/2308.11884):
  - 57 loops removed;
  - 40k redundant transitive links removed;
  - 9k links removed that would have made a class a subclass of two disjoint top-level classes;
  - 1.3M classes without instances removed;
  - for places, 2,861 of 29,826 classes and 137k of 19M instances discarded;
  - excluded: Wikimedia housekeeping classes, linguistic objects (about 700k entities), abstract objects, and scholarly articles (39M entities).
- Fact cleaning — [YAGO 4.5](https://arxiv.org/abs/2308.11884):
  - SHACL constraints were added by hand: 31 maximum-cardinality constraints, 9 literal patterns (for example ISBN) and domain and range for every relation.
  - "A fact is accepted only if both its subject and its object conform to the domain and range constraints (this removes roughly 6% of facts in our dataset)."
  - "We take only the facts that Wikidata labels as 'truthy' (which exclude disputed statements)."
  - Time stamps come from the full dump, not the truthy one, and are attached "in the RDF-star model".
  - Quantities were simplified: "while these were previously values with a range and a unit, they are now simple literals".
  - Removed properties: inverses (6), scholarly (4), biochemical (11) and literal-describing (6).
- Sizes — [YAGO 4.5](https://arxiv.org/abs/2308.11884):

  | | Entities | Classes | Predicates | Facts | Meta facts | Dump |
  |---|---|---|---|---|---|---|
  | Wikidata | 103M | 2.8M | 11k | 500M | 12M | 766 GB |
  | YAGO 4.5 | 49M | 133k | 108 | 132M | 7M | 142 GB |

  YAGO 4.5 averages 2.6 paths to the root, against 44 in Wikidata, and 7.8 classes per entity. It ships separate files: Schema (including the SHACL shapes), Taxonomy, Facts, Beyond Wikipedia, and Meta (the RDF-star temporal annotations).
- Engineering — [YAGO 4.5](https://arxiv.org/abs/2308.11884):
  - The code was rewritten in Python with a roughly 500-line Turtle parser of its own, because RDFLib failed on some URIs.
  - Intermediate files are TSV, so the pipeline "can attach more information to each fact (time stamp, source, etc.) in the form of supplementary columns".
  - There are 6 steps. Each has test inputs with gold-standard outputs.
  - A full run takes about 12 hours on 90 CPUs with 800 GB RAM. Logical consistency was checked with Pellet (4 h) and the SHACL shapes with Jena SHACL (1 h 30).

**DBpedia**
- DBpedia's type-consistency post-processing sorts out statements that conflict with the ontology. If the subject's type is disjoint with the property's rdfs:domain, the statement goes to a `_disjointDomain` file. If the object is disjoint with rdfs:range, it goes to `_disjointRange`. These statements "were filtered out from the 'mappingbased-objects' datasets as errors, but are still provided". — [DBpedia Post-Processing](http://dev.dbpedia.org/Post-Processing); [extraction-framework postprocessing.md](https://raw.githubusercontent.com/dbpedia/extraction-framework/master/documentation/postprocessing.md) (excerpt)
- Test-driven quality checking (RDFUnit) — [RDFUnit wiki](https://github.com/AKSW/RDFUnit/wiki/Overview):
  - It uses "SPARQL query templates expressing certain common error conditions", for example someone who died before being born.
  - Tests are generated automatically from schema axioms: rdfs:domain and rdfs:range; min, max and exact cardinality; functional and inverse-functional properties; disjoint classes; propertyDisjointWith; complementOf; asymmetric and irreflexive properties.
  - It also supports SHACL.
- The RDFUnit paper is Kontokostas et al., WWW 2014 — [ACM DL](https://dl.acm.org/doi/10.1145/2566486.2568002). A secondary summary reports more than 63M errors in dbpedia.org, mostly rdfs:domain (31M) and rdfs:range (26M) violations — [liner.com summary](https://liner.com/review/testdriven-evaluation-linked-data-quality). I did not check these numbers against the paper.
- DBpedia releases through the Databus. "Data, metadata, and license statements are signed by the users via private key and verified on upload via .X509 certificates and WebID". Metadata uses DCAT and DataID. The model "distinguishes the abstract identity of a dataset from the individual versions (e.g. monthly snapshot)". — [DBpedia Databus](https://www.dbpedia.org/resources/databus/)

**BabelNet**
- BabelNet 5.3 has "about 23 million" synsets in 600 languages, built from November 2023 dumps. — [BabelNet — About](https://babelnet.org/about)
  - **Sources:** WordNet 3.0, Open English WordNet, Wikipedia, OmegaWiki, Wiktionary, Wikidata, GeoNames, ImageNet, Open Multilingual WordNet, BabelPic, VerbAtlas and others.
  - **License:** the "BabelNet Non-Commercial License limited to research institutions".
- Wikipedia instead gives the license as CC BY-NC-SA 3.0. It also describes the model as WordNet-style synsets extended with multilingual lexicalizations. — [Wikipedia: BabelNet](https://en.wikipedia.org/wiki/BabelNet). The two license statements conflict; I prefer the primary source.

**KBpedia** — **[OLDER]**: the current version is 2.50, from 2020.
- KBpedia has "more than 58,000 reference concepts", "mapped linkages to about 40 million entities (most from Wikidata)" and "5,000 relations and properties". They are organized in about 70 "largely disjoint typologies" and written mainly in OWL 2. New candidates are tested "using a rigorous suite of logic and consistency tests" before acceptance. — [kbpedia.org](https://kbpedia.org/)
- The older GitHub README gives about 30M entities and about 75 typologies. It lists UMBEL among the seven integrated knowledge bases, where the homepage lists UNSPSC. — [KBpedia README](https://github.com/Cognonto/kbpedia/blob/master/README.org) (excerpt)
- "Disjointness enables powerful reasoning and subset selection (filtering)". — [KBpedia typologies](https://kbpedia.org/docs/30-typologies/) (excerpt)

**acatalogue today (local)**
- The `claim` table has one `(subject, predicate, object | value)` row. `qualifiers` is a JSON text column; `rank` and `epistemic` are text; `valid_from` and `valid_to` are text ("ISO 8601 / EDTF"). `CHECK ((object IS NULL) <> (value IS NULL))` requires exactly one of object and value. The unique index `claim_identity` covers `(subject, predicate, coalesce(object,''), coalesce(value,''), source_sha512)`. — [schema.sql](/home/user/acatalogue/acatalogue/schema.sql)
- Current contents of the database — local read-only query of `data/acatalogue.sqlite` (2026-09-25):
  - 4,045 claims. Rank: normal 3,938, preferred 26, deprecated 81. Epistemic: attributed 3,964, superseded 81. All 81 deprecated claims are mapped to `epistemic/superseded`.
  - 0 claims have qualifiers, 0 have `valid_from`, and 0 have literal values.
  - Top predicates: P31 (1,112), P279 (1,033), P527 (871), P2579 (345), P361 (296).
  - All 4,045 claims trace back to only 3 source blobs: WDQS SPARQL-results JSON files `claims-001/002/003.json` of 966,778, 720,522 and 475,308 bytes.
- The epistemic scheme defines its statuses as follows. — local `concept` table, scheme `epistemic`
  - `superseded`: "The source itself later withdrew or replaced it."
  - `refuted`: "Contradicted by strong evidence according to cited sources".
  - The scheme's rule: "every status other than 'attributed' must itself cite who judged it and by what rule".

### Inferences
- The projects handle Wikidata's messiness in three different ways:
  - **Filter destructively** for logical consistency (YAGO).
  - **Quarantine** failing triples into queryable side files (DBpedia).
  - **Map concepts** and ignore statement detail (BabelNet, KBpedia).

  acatalogue's rules (never delete, keep exact bytes) match DBpedia's quarantine approach. They also match Wikidata's own practice of keeping sourced-but-wrong claims as deprecated. YAGO-style cleaning belongs in views and validation flags, not in deletion.
- acatalogue's Wikidata import is currently thinner than YAGO in one respect: it has no time annotations. Because it reads WDQS result tables rather than entity JSON, it loses statement GUIDs, qualifiers (including start and end times), references, snak types and revision pins. Those are the parts of Wikidata that matter most to an *attributed* catalogue.
- Mapping every deprecated claim to `epistemic/superseded` over-interprets Wikidata's rank:
  - Deprecated covers both "outdated" and "never correct" (Help:Ranking), and P2241 separates the two.
  - The epistemic scheme requires every non-`attributed` status to cite who judged it and by what rule.
  - A defensible default is `epistemic/attributed` with `rank='deprecated'`. Move to superseded or refuted only through a recorded rule over P2241 reasons.
- BabelNet's non-commercial, research-only license makes it unsuitable as a store-of-record input for an open catalogue. At most, it could serve as an external mapping target.
- KBpedia's and YAGO's declared disjointness among top-level types is a cheap, strong error detector. acatalogue's facet schemes (for example `kind`) could declare disjoint pairs and flag concepts or claims that fall under both.

### Gaps
- I did not verify how BabelNet records per-sense or per-edge provenance; the about page does not say.
- I did not verify DBpedia's per-triple provenance quads (for example page revision IDs) this session.
- I found no primary source for Wikidata's statement count as of September 2026. The 1.65B figure is early 2025, via Wikipedia.
- The fetched documentation does not say how Wikidata computes reference and snak hashes. Only their 40-hex length was observed.

---

## 2. Current standards for statement-level provenance and time (PROV-O, nanopublications, RDF 1.2 / RDF-star, singleton properties, n-ary relations). Which map cleanly onto a relational (SQLite) claim table?

### Takeaway
The n-ary "statement node" pattern that Wikidata's own RDF uses maps one-to-one onto a claim row with child tables for qualifiers and references. So does the RDF 1.2 reifier: the claim id is the reifier and `(subject, predicate, object)` is the triple term. PROV-O maps cleanly onto acatalogue's source, fetch, ledger and time columns, and a nanopublication maps onto "claim + provenance + ledger row".

Two options should be avoided:
- **Singleton properties**, because 4 of 5 SPARQL engines struggled with the many unique predicates they create.
- **Named graphs per claim**, because 4store struggled with large numbers of graphs; beyond that it is merely optional.

On benchmarks, a keyed relational layout (Statement + Qualifier tables) answered Wikidata-style lookups faster than the RDF stores and Neo4j it was compared with. RDF 1.2 is still a Candidate Recommendation (April 2026), so use it for export, not storage.

### Cited Findings
- **PROV-O** has been a W3C Recommendation since 30 April 2013. — [PROV-O](https://www.w3.org/TR/prov-o/)
  - Starting-point classes: Entity ("A physical, digital, conceptual, or other kind of thing with some fixed aspects"), Activity and Agent.
  - Starting-point properties: `wasGeneratedBy`, `wasDerivedFrom`, `wasAttributedTo`, `used`, `wasAssociatedWith`, `actedOnBehalfOf`, `startedAtTime`, `endedAtTime`, `wasInformedBy`.
  - Expanded terms: `generatedAtTime`, `invalidatedAtTime`, `wasRevisionOf`, `wasQuotedFrom`, `hadPrimarySource`, `alternateOf`, `specializationOf`, `value`, `atLocation`, plus the classes `Bundle` and `Collection`.
  - Qualified pattern: `qualifiedDerivation` goes through a `Derivation` node with `hadActivity`/`hadGeneration`; `qualifiedAttribution` goes through `Attribution` with `hadRole`/`hadPlan`.
- **Nanopublications** — [Nanopublication Guidelines](https://nanopub.net/guidelines/working_draft/):
  - A head graph links the three parts.
  - The assertion graph "contains such statements that form the main claim".
  - The provenance graph describes the assertion and "MUST contain a link to the assertion graph identifier".
  - The publication-info graph covers the nanopublication itself and "SHOULD contain attribution and timestamp".
  - "Trusty URIs [5] are the recommended way of assigning integrity keys to nanopublications."
- "More than 10 million such nanopublications have been published", mostly in the life sciences (2018). — [Kuhn et al., arXiv:1809.06532](https://arxiv.org/abs/1809.06532)
- A decentralized server network replicates nanopublications that have trusty URIs, through a REST API. — [Kuhn et al., PeerJ CS 2015](https://peerj.com/articles/cs-78/) (excerpt)
- Signing keys must be declared in an "introduction" nanopublication, which the declared key itself can sign. — [nanopub-js](https://github.com/Nanopublication/nanopub-js) (excerpt)
- The ESWC 2025 nanopublication tutorial covered "the Nanopub Registry and quotas for scalable and robust publishing infrastructure". — [ESWC 2025 tutorial programme](https://nanopub.net/docs/tutorials/eswc2025program/)
- **RDF 1.2** — [RDF 1.2 Concepts](https://www.w3.org/TR/rdf12-concepts/)
  - **Status:** "W3C Candidate Recommendation Snapshot", 07 April 2026, "not expected to advance to Recommendation any earlier than 05 May 2026". The W3C has invited implementations — [W3C news](https://www.w3.org/news/2026/w3c-invites-implementations-of-rdf-1-2-concepts-and-abstract-data-model-and-rdf-1-2-semantics).
  - **Triple term:** "An RDF triple used as the object of another triple is called a triple term". Triple terms appear only in the object position.
  - **Reifier:** "A reifying triple is a triple where the predicate is `rdf:reifies` and the object is a triple term. The subject of that triple is called a reifier."
  - **Conformance levels:** "Full" supports triple terms; "Basic" (version label `1.2-basic`) does not.
- Other RDF 1.2 documents were at different stages as of September 2026: RDF 1.2 Turtle was a Working Draft dated 14 September 2026 — [RDF 1.2 Turtle WD](https://www.w3.org/TR/2026/WD-rdf12-turtle-20260914/). "What's New in RDF 1.2" (14 July 2026) and the Primer (26 August 2026) were Draft Notes — [What's New](https://www.w3.org/TR/2026/DNOTE-rdf12-new-20260714/), [Primer](https://www.w3.org/TR/2026/DNOTE-rdf12-primer-20260826/).
- **[SUPERSEDED] RDF\*.** RDF-star goes back to Hartig and Thompson's "Foundations of an alternative approach to reification in RDF" ([arXiv:1406.3399](http://arxiv.org/abs/1406.3399), cited in [Hernández et al. 2015](https://aidanhogan.com/docs/reification-wikidata-rdf-sparql.pdf)). YAGO 4.5 still publishes its temporal annotations "in the RDF-star model" — [YAGO 4.5](https://arxiv.org/abs/2308.11884). RDF 1.2's object-only triple terms with `rdf:reifies` reifiers are the standards-track successor — [RDF 1.2 Concepts](https://www.w3.org/TR/rdf12-concepts/).
- **SHACL 1.2 Core** adds constraints for RDF 1.2 reifiers: `sh:reifierShape` and `sh:reificationRequired`. — [SHACL 1.2 Core WD, 18 Sep 2026](https://www.w3.org/TR/shacl12-core/)
- **N-ary relations** are a W3C Working Group Note of 12 April 2006. Pattern 1 introduces "an individual that represents the relation instance itself, with links to all participants". Its use case 1 is extra attributes of a relation, such as probability. — [Defining N-ary Relations on the Semantic Web](https://www.w3.org/TR/swbp-n-aryRelations/)
- **Hernández, Hogan & Krötzsch (SSWS 2015)** compared four ways of encoding Wikidata's qualifiers in RDF, using the Wikidata dump of 2015-02-23. — [Reifying RDF: What Works Well With Wikidata?](https://aidanhogan.com/docs/reification-wikidata-rdf-sparql.pdf)
  - **Size:** for n = 57,088,184 quads with p = 1,311 properties, the encodings need these numbers of tuples:

    | Encoding | Formula | Tuples |
    |---|---|---|
    | Standard reification | 3n | 171,264,552 |
    | n-ary relations | 2(n+p) | 114,178,990 |
    | Singleton properties | 2n | 114,176,368 |
    | Named graphs | n | 57,088,184 |

  - **Findings:** singleton properties "offered the most concise representation on a triple level". "n-ary predicates was the only model with built-in support for SPARQL property paths". 4store, BlazeGraph, GraphDB and Jena "struggled with the high number of unique predicates generated by singleton properties". 4store also struggled with many named graphs. Otherwise there was "no clear winner between standard reification, n-ary predicates and named graphs".
  - The singleton-property proposal itself is Nguyen, Bodenreider and Sheth, WWW 2014, as cited in the same paper.
- **Relational layout (Hernández, Hogan, Riveros, Rojas & Zerega)** — ["Querying Wikidata: Comparing SPARQL, Relational and Graph Databases"](https://aidanhogan.com/docs/wikidata-sparql-relational-graph.pdf)
  - **Schema:** three tables. "Statement stores the primary relation and a statement id; Qualifier associates one or more qualifiers with a statement id; and Label associates each entity and property with one or more multilingual labels". Typed values: "We currently use JSON strings to serialise datatype values, along with their meta-information, and store different types in different columns" (`odate`/`vdate`).
  - **Results:** "PostgreSQL performs best for all but three patterns, and is often an order of magnitude faster than the next closest result". It "benefits from its explicit physical schema" (indexed primary and foreign keys). Of 94 example queries on the Wikidata Query Service, 11 used qualifiers.

### Inferences
How each construct maps onto the SQLite claim model:

| Construct | acatalogue relational equivalent | Fit |
|---|---|---|
| Wikidata n-ary statement node (`wds:`, `p:`/`ps:`/`pq:`) | `claim` row (id = statement node), `claim_qualifier` rows, `claim_reference` rows | Exact, 1:1 (the Hernández relational schema is this) |
| RDF 1.2 reifier + `rdf:reifies <<( s p o )>>` | `claim.id` is the reifier; `(subject, predicate, object)` is the triple term; qualifiers become reifier triples | Clean for export. Several claims from different sources about one triple become several reifiers. Literal-valued claims also work, since triple terms only need to be objects. |
| Nanopublication (assertion / provenance / pubinfo) | assertion = claim row + qualifiers; provenance = `source_sha512` + locator + Wikidata references; pubinfo = `recorded_at` + ledger row (actor, hash) | Clean. A nanopub is a natural export unit for one claim or a small bundle. |
| PROV-O | `source` = prov:Entity; fetch = prov:Activity (`startedAtTime`, `used` the URI); ledger `actor` = prov:Agent; claim `wasDerivedFrom` source; Wikidata reference = `hadPrimarySource` (or `wasQuotedFrom` when a P1683 quotation is present); `recorded_at` = `generatedAtTime`; `superseded_at` = `invalidatedAtTime`; superseding claim `wasRevisionOf` the old one | Clean, with no storage change. PROV-O is an export vocabulary for the ledger and source tables. |
| Named graph per claim | a quad whose graph IRI is the claim id | Works, but adds nothing over the n-ary row. Avoid graph-per-claim at scale (4store evidence). |
| Singleton properties | a unique predicate id per claim | Avoid: it breaks predicate indexing and "all P31 claims" queries, and engines struggled with it. |
| Standard reification (`rdf:Statement`) | 3 extra triples per claim | Export only, if a consumer requires it. |

- Store in SQLite. Export to RDF 1.2 Full (reifiers) for modern consumers, and to the Wikidata-style n-ary layout, which works in RDF 1.1 and RDF 1.2 Basic, for everyone else. That avoids betting the storage layer on a specification that is still a Candidate Recommendation.
- YAGO's TSV intermediates, which add time stamp and source as "supplementary columns", show that a flat, keyed, columnar layout for annotated facts works at Wikidata scale in pure Python.

### Gaps
- I did not verify whether the 2021 RDF-star Community Group report allowed quoted triples in the subject position, which RDF 1.2 now disallows.
- I did not verify whether RDF 1.2 formally allows several reifiers for one triple term. The quoted definitions do not forbid it.
- I found no current (2026) count of published nanopublications, nor the Registry's scale. The 10M figure is from 2018.

---

## 3. Shape and constraint validation (ShEx, SHACL, Wikidata EntitySchemas, Wikidata property constraints): how are they used in practice, and how could the same checks be written as SQL over SQLite?

### Takeaway
In practice, Wikidata's error-finding runs on about 32 property-constraint types. They are advisory, have exceptions, carry a mandatory or suggestion status, and are checked by bespoke code; W3C shape languages are not used. Research shows the following:
- SHACL-Core cannot express 6 of the 32 types fully.
- More than 72K constraint definitions exceed what existing SHACL validators can handle at scale.
- SPARQL can express all 32. SQL, with recursive CTEs, arithmetic and a regexp user function, is at least as expressive.

acatalogue should therefore:
- store the constraints as sourced data;
- implement each constraint type as a versioned SQL template;
- log violations append-only with SHACL-style severities and Wikidata-style exceptions;
- report three-valued results, because the catalogue is a subset of Wikidata.

### Cited Findings
- **Wikidata property constraints in practice** — [Help:Property constraints portal](https://www.wikidata.org/wiki/Help:Property_constraints_portal):
  - They are advisory: "Constraints are hints, not firm restrictions" and "They can have exceptions".
  - Status is mandatory (Q21502408) or suggestion (Q62026391).
  - Exceptions: "Exception to constraint (P2303) lists known exceptions to the constraint. On the items listed under this parameter, the constraint is not checked."
  - Constraint scope (P4680) says which part of a statement the constraint applies to.
  - Setting a constraint's rank to deprecated hides it from checking.
  - Reports are produced by the WikibaseQualityConstraints extension (Special:ConstraintReport) and by bot-maintained violation reports.
  - Types named on the portal include: single-value (Q19474404), distinct-values (Q21502410), format (Q21502404), subject type (Q21503250), value-type (Q21510865), multi-value (Q21510857), symmetric (Q21510862), inverse, one-of, none-of, conflicts-with, item-requires-statement, value-requires-statement, contemporary, label/description in language, single-best-value, allowed units, integer, no-bounds, range, difference-within-range and property scope.
- **Ferranti, De Souza, Ahmetaj & Polleres (Semantic Web Journal, 2024)** — [paper](https://journals.sagepub.com/doi/full/10.3233/SW-243611), [PDF](https://www.semantic-web-journal.net/system/files/swj3533.pdf):
  - **Coverage of constraints:** "We estimate that 99% of Wikidata properties are affected by at least one property constraint". Class-level constraint projects cover only about 0.2% of classes. "none of these projects deploys the current W3C recommendation for validating RDF graphs against constraints, namely, SHACL".
  - **Expressibility in SHACL-Core:** 26 of the 32 types can be written in SHACL-Core. Six cannot, fully:
    - not expressible: difference-within-range (Q21510854), which needs arithmetic, and single-best-value (Q52060874);
    - not reasonably expressible: allowed qualifiers (Q21510851);
    - partially verifiable: allowed entity types (Q52004125);
    - only partially expressible: single-value (Q19474404) and distinct-values (Q21502410).

    The authors write SPARQL queries "for all 32 current Wikidata constraint types".
  - **Scale:** "there were over 72K constraint definitions in total at the time of writing". Checking them all "goes beyond the scalability (and feature coverage) of existing SHACL validators". Also, "non-core features are unfortunately not mandatorily (and thus rarely) implemented by SHACL validators".
  - **Parameters:** constraints are parameterized by qualifiers on the property's constraint statement: P2305 (item), P2306 (property), P2308 (class), P2309 (relation), P2313/P2312 (min/max value), P2310/P2311 (min/max date), P4155 (separator), P2304 (group by), P2303 (exception) and P2241 (a deprecated constraint).
  - **Separators:** separator qualifiers act like a composite key, allowing several values that differ in the separator values. The capital (P36) of the USA with start and end times is the example. Help text: "specifies that a property generally only has a single value. [...] A qualifier can be defined as a separator".
  - **Wikidata's own reports:** the violation reports are "only available in HTML format, and moreover, the code behind is not publicly available". They list at most 5,001 violations per (property, constraint type) pair. Some types can only be partially evaluated because Wikidata's own RDF dump is incomplete.
  - **History:** constraint types grew "from 19 in 2015 to 32 in 2023". **[SUPERSEDED]** "used for values only" (Q21528958), "used as reference" (Q21528959) and "used as qualifier" (Q21510863) were merged into property scope (Q53869507).
  - **Most violated (16 Dec 2022):** one-of (Q21510859), item-requires-statement (Q21503247), single value (Q19474404 and Q52060874), required qualifier (Q21510856) and value-requires-statement (Q21510864).
- Measured violation ratios by constraint status (mandatory 0.03–0.08%, normal 0.65–0.76%, suggested up to 20% for type constraints) are given in Section 1 — [Shenoy et al.](https://arxiv.org/abs/2107.00156)
- **EntitySchemas** are written in ShExC ("Shape Expressions (ShEx) is a concise, formal modeling and validation language for RDF structures"), with E-numbered ids such as E10. They are checked with tools like ShExStatements and WikiShape. "An alternative approach to schemas are property constraints". — [WikiProject Schemas](https://www.wikidata.org/wiki/Wikidata:WikiProject_Schemas)
- **ShEx:** ShEx 2.1 is specified at [shex.io](https://shex.io/shex-semantics/). IEEE P3330 (Shape Expression Schemas) is an active PAR approved 2022-12-03 and reached Draft 3 in October 2024. — [IEEE SA P3330](https://standards.ieee.org/ieee/3330/11119), [P3330 WG](https://sagroups.ieee.org/p3330) (excerpt)
- **SHACL:** SHACL (1.0) is the W3C Recommendation — [SHACL](https://www.w3.org/TR/shacl/). SHACL 1.2 Core was a Working Draft on 18 September 2026. — [SHACL 1.2 Core](https://www.w3.org/TR/shacl12-core/)
  - New constraints: `sh:singleLine`; list constraints `sh:memberShape`, `sh:minListLength`, `sh:maxListLength`, `sh:uniqueMembers`; reifier constraints `sh:reifierShape`, `sh:reificationRequired`.
  - Five severities: `sh:Trace`, `sh:Debug`, `sh:Info`, `sh:Warning`, `sh:Violation` (the default).
  - Companion First Public Working Drafts appeared in 2026: Node Expressions ([news](https://www.w3.org/news/2026/first-public-working-draft-shacl-1-2-node-expressions/)), Profiling (2 Jul 2026, [WD](https://www.w3.org/TR/2026/WD-shacl12-profiling-20260702/)) and UI (26 May 2026, [WD](https://www.w3.org/TR/2026/WD-shacl12-ui-20260526/)).
- **SHACL at KB scale:** YAGO 4.5 ships its SHACL shapes with the data and validated them with Jena SHACL in 1 h 30. — [YAGO 4.5](https://arxiv.org/abs/2308.11884)
- **SQLite and Python building blocks:**
  - REGEXP: "No regexp() user function is defined by default … If an application-defined SQL function named 'regexp' is added at run-time, then the 'X REGEXP Y' operator will be implemented as a call to 'regexp(Y, X)'" — [SQLite expressions](https://www.sqlite.org/lang_expr.html). Python registers such functions with `Connection.create_function` — [Python sqlite3](https://docs.python.org/3/library/sqlite3.html).
  - JSON functions have been "built into SQLite by default, as of SQLite version 3.38.0 (2022-02-22)". — [SQLite JSON](https://www.sqlite.org/json1.html)
  - JSONB (binary JSON stored as a BLOB) arrived in 3.45.0 (2024-01-15). It is "intended for internal use by SQLite only. Applications should not use JSONB outside of SQLite". — [SQLite JSON](https://www.sqlite.org/json1.html)
  - STRICT tables need 3.37.0 (2021-11-27) or later — [STRICT tables](https://www.sqlite.org/stricttables.html). Generated columns need 3.31.0 (2020-01-22) or later — [generated columns](https://www.sqlite.org/gencol.html).

### Inferences
- **Rule design.** Store every constraint as a row with the following:
  - its type (the Wikidata constraint Q-id, or an acatalogue rule id);
  - its parameters as JSON;
  - a severity: violation / warning / info, following SHACL 1.2 names, with mandatory→violation and suggestion→warning;
  - its exceptions (P2303), in their own table;
  - the SHA-512 of the exact SQL text that implements it;
  - the `source_sha512` of the bytes it came from, for example the property's P2302 statements in Wikidata's entity JSON.

  Each validation run records the ledger head and a hash of the rule set. Its violations go to an append-only table. The same run over the same data is then reproducible and verifiable, which matches the ledger's philosophy.
- **Three-valued results.** acatalogue holds a subset of Wikidata (2,705 items). A value-type or item-requires-statement check on a value item that was never fetched must return *unknown*, not *violation*. This is the same partial-evaluation problem Ferranti et al. hit with Wikidata's incomplete RDF dump, only worse.
- **SQL templates** (sketches that assume the proposed `claim_qualifier`, `rule_exception` and time tables in Section 6):
  ```sql
  -- single-value (Q19474404) honouring separator qualifiers (P4155) and exceptions (P2303)
  WITH v AS (
    SELECT c.id, c.subject,
           (SELECT group_concat(k, '|') FROM (
              SELECT q.property || '=' || coalesce(q.object, q.value, q.snaktype) AS k
              FROM claim_qualifier q
              WHERE q.claim_id = c.id
                AND q.property IN (SELECT value FROM json_each(:separators))
              ORDER BY k)) AS sepkey
    FROM claim c
    WHERE c.predicate = :p AND c.superseded_at IS NULL AND c.rank <> 'deprecated'
      AND c.subject NOT IN (SELECT focus FROM rule_exception WHERE rule_id = :rule))
  SELECT subject, sepkey, count(*) AS n FROM v GROUP BY subject, sepkey HAVING n > 1;

  -- value-type (Q21510865), relation = instance of: the value must be an instance of a subclass of :classes
  WITH RECURSIVE cls(c) AS (
    SELECT value FROM json_each(:classes)
    UNION
    SELECT s.subject FROM claim s JOIN cls ON s.object = cls.c
     WHERE s.predicate = 'wd/P279' AND s.superseded_at IS NULL AND s.rank <> 'deprecated')
  SELECT v.id, v.object,
         CASE WHEN NOT EXISTS (SELECT 1 FROM claim t WHERE t.subject = v.object AND t.predicate = 'wd/P31')
              THEN 'unknown' ELSE 'violation' END AS outcome        -- open world: value item not fetched
  FROM claim v
  WHERE v.predicate = :p AND v.object IS NOT NULL AND v.superseded_at IS NULL
    AND NOT EXISTS (SELECT 1 FROM claim t WHERE t.subject = v.object AND t.predicate = 'wd/P31'
                    AND t.superseded_at IS NULL AND t.object IN (SELECT c FROM cls));

  -- difference-within-range (Q21510854), which SHACL-Core cannot express; precision-aware:
  -- flag only if even the most favourable reading of both dates' bounds is out of range
  SELECT d.subject FROM claim d JOIN claim b ON b.subject = d.subject
    JOIN time_value td ON td.claim_id = d.id JOIN time_value tb ON tb.claim_id = b.id
  WHERE d.predicate = :later_p AND b.predicate = :earlier_p
    AND ((td.hi_jdn - tb.lo_jdn) < :min_days OR (td.lo_jdn - tb.hi_jdn) > :max_days);

  -- taxonomy cycles in broader (YAGO found 47 two-cycles and 15 longer ones in Wikidata)
  WITH RECURSIVE reach(start, node) AS (
    SELECT child, parent FROM broader
    UNION SELECT r.start, b.parent FROM reach r JOIN broader b ON b.child = r.node)
  SELECT DISTINCT start FROM reach WHERE start = node;

  -- redundant transitive broader links (YAGO removed 40k): child->parent also reachable through another parent
  WITH RECURSIVE reach(start, node) AS (
    SELECT child, parent FROM broader
    UNION SELECT r.start, b.parent FROM reach r JOIN broader b ON b.child = r.node)
  SELECT d.child, d.parent FROM broader d
  WHERE EXISTS (SELECT 1 FROM broader o JOIN reach r ON r.start = o.parent
                WHERE o.child = d.child AND o.parent <> d.parent AND r.node = d.parent);
  ```
  Format constraints (Q21502404) can use `value REGEXP :pattern` once a `regexp` function is registered from Python's `re` module.

  The `UNION`-based closures terminate on cyclic graphs but use memory proportional to the reachable pairs. For millions of classes, compute strongly connected components or the closure in Python (Tarjan's algorithm) and store the result as a derived, rebuildable table.
- **Don't make SHACL or ShEx the validator of record.** SHACL 1.2 is still a Working Draft, ShEx's IEEE standard is still a draft, SHACL-Core cannot express 6 of Wikidata's 32 types, and SHACL validators did not scale to Wikidata's constraint set. Keep SQL as the canonical implementation. Optionally export SHACL or ShEx shapes generated from the rule table for interchange, as YAGO ships SHACL shapes with its data.
- **Quarantine, don't drop.** Violations remain ordinary rows. Consumers can use a YAGO-like "clean view" (for example `v_claim_clean`, which excludes claims with open violations of severity *violation*). This follows DBpedia's "filtered out … as errors, but are still provided" pattern and satisfies acatalogue's never-delete rule.
- **Auto-generate tests** from acatalogue's own axioms, RDFUnit-style: facet disjointness, required labels, one preferred label per language, acyclic `broader`, and `related` never duplicating `broader`. Add YAGO-style gold-standard fixtures for each pipeline step.

### Gaps
- I did not verify whether Wikidata format constraints require a full-string regex match. Check the Help page before implementing.
- I did not find a published SQL (as opposed to SPARQL) formalization of Wikidata constraints. The SQL above is my own translation sketch.
- I did not verify the date or count of Wikidata EntitySchemas as of 2026.

---

## 4. How do these projects handle "unknown value", "no value", uncertainty (date precision, EDTF), contested or plural values, and deprecated rank? What does acatalogue's model lack?

### Takeaway
Wikidata represents uncertainty in five ways:
- snak types for the unknown (`somevalue`) and the absent (`novalue`);
- a precision code (0–14) and a calendar on every date;
- earliest-date and latest-date qualifiers, plus "sourcing circumstances" (circa, disputed, …);
- plural or contested values as several statements separated by rank, with reasons for preferred and deprecated rank;
- verifiable-but-wrong claims kept as deprecated rather than deleted.

YAGO throws most of this away: truthy facts only, no disputed statements, and bare numbers in place of quantities. acatalogue can represent none of it today: its CHECK forbids unknown and no-value claims, its text dates carry no precision, and its `claim_identity` index can merge two distinct statements.

### Cited Findings
- Snak semantics:
  - `somevalue` means a value exists but is unknown, as in the Ambrose Bierce example; `novalue` asserts that there is no value, as in the circle example — [Wikibase/DataModel](https://www.mediawiki.org/wiki/Wikibase/DataModel).
  - In RDF, `novalue` becomes a `wdno:` class (`owl:complementOf`) and `somevalue` becomes a blank node or a Skolem IRI — [RDF Dump Format](https://www.mediawiki.org/wiki/Wikibase/Indexing/RDF_Dump_Format).
- Dates have precision codes 0–14 ([DataModel](https://www.mediawiki.org/wiki/Wikibase/DataModel)). Hours, minutes and seconds are not yet supported; the Julian calendar is used before 1583; P1319/P1326 give bounds; P4241 refines a date; P1480 = circa marks approximations; century and millennium are read strictly ([Help:Dates](https://www.wikidata.org/wiki/Help:Dates)). `before`/`after` are "Currently unused" ([JSON docs](https://doc.wikimedia.org/Wikibase/master/php/docs_topics_json.html)).
- **Year 0.** The RDF/XSD form writes 1 BCE as year 0. The JSON form writes 1 BCE as -0001 ([Help:Dates](https://www.wikidata.org/wiki/Help:Dates); [RDF Dump Format](https://www.mediawiki.org/wiki/Wikibase/Indexing/RDF_Dump_Format)).
- **EDTF** — [Library of Congress EDTF, 4 Feb 2019](https://www.loc.gov/standards/datetime/):
  - Level 0 covers "features of ISO 8601-1". Levels 1 and 2 cover features of ISO 8601-2.
  - Level 1 adds uncertain `1984?`, approximate `2004-06~`, both `2004-06-11%`, unspecified digits `201X` and `2004-XX`, open and unknown interval ends (`1985-04-12/..`, `../1985`, `1985-04/`), long years `Y170000002` and seasons `2001-21`.
  - Level 2 adds "one of a set" `[1667,1668,1670..1672]`, "all members" `{…}`, significant digits `1950S2`, per-component qualification `?2004-06-~11` and `156X-12-25`.
- **Deprecated rank and its reasons:** see Section 1 ([Help:Ranking](https://www.wikidata.org/wiki/Help:Ranking), [P2241](https://www.wikidata.org/wiki/Property:P2241)).
- **The truthy/best-rank rule:** preferred beats normal; deprecated is never truthy ([RDF Dump Format](https://www.mediawiki.org/wiki/Wikibase/Indexing/RDF_Dump_Format)). The single-best-value constraint (Q52060874) expects exactly one best-ranked statement per property ([Ferranti et al.](https://journals.sagepub.com/doi/full/10.3233/SW-243611)).
- **Contested values** can be marked with P1480 = disputed (Q18912752) or "according to some sources" (Q59783740) — [P1480](https://www.wikidata.org/wiki/Property:P1480). YAGO keeps "only the facts that Wikidata labels as 'truthy' (which exclude disputed statements)" — [YAGO 4.5](https://arxiv.org/abs/2308.11884).
- **Plural values that differ only in qualifiers** (for example two start/end periods of the same office) are separate statements, distinguished by separator qualifiers in single-value checks — [Ferranti et al.](https://journals.sagepub.com/doi/full/10.3233/SW-243611). The relational benchmark schema keys qualifiers on the *statement id* — [Hernández et al.](https://aidanhogan.com/docs/wikidata-sparql-relational-graph.pdf).
- **Quantities:** YAGO 4.5 replaced range-and-unit quantities with "simple literals" — [YAGO 4.5](https://arxiv.org/abs/2308.11884). Wikibase keeps `lowerBound`, `upperBound` and `unit` — [DataModel](https://www.mediawiki.org/wiki/Wikibase/DataModel).
- **What acatalogue can represent today** — [schema.sql](/home/user/acatalogue/acatalogue/schema.sql); local DB query:
  - The CHECK `(object IS NULL) <> (value IS NULL)` leaves no room for `somevalue`/`novalue`.
  - There are no precision, calendar or bounds columns.
  - The `claim_identity` unique key omits any statement id or qualifier key.
  - No qualifiers, dates or references are populated: 0 of 4,045 claims have qualifiers or `valid_from`.

### Inferences
What acatalogue's model lacks, from most to least urgent:
1. **Statement identity.** Two Wikidata statements with the same `(subject, predicate, object)` and the same source blob but different qualifiers, such as the same office held twice, collide on `claim_identity`. The second is rejected or merged. This is a real data-loss path once qualifiers are imported.
2. **Snak type.** Unknown and no-value claims cannot be stored. Faking them as NULL or empty-string values would wrongly turn "no value" (a negative fact) and "unknown" (an existential fact) into absent data. Two `somevalue` claims must never be joined as equal.
3. **Qualifiers as rows.** The empty JSON column cannot be indexed or constrained well. Required-qualifier, allowed-qualifier, separator and time-scoped queries all need rows.
4. **The reference chain.** Provenance currently stops at "a 1 MB SPARQL result file". It lacks both the exact location of the claim inside those bytes and Wikidata's own cited references (stated in, reference URL, retrieved, quotation). That second level of attribution is exactly what an attributed catalogue promises.
5. **Date precision, calendar and bounds.**
   - Bare text in `valid_from`/`valid_to` cannot say "1879 ± year precision", "circa 1500", "Julian" or "between 1667 and 1672".
   - Lexical comparison of signed ISO years gives the wrong order for BCE dates: `'-0500' > '-0100'` as strings, but -500 < -100.
   - The concept table already uses astronomical years (1 BCE = 0), which matches the RDF/XSD form but not the JSON form (-0001 for 1 BCE). An importer reading entity JSON must shift BCE years by 1.
6. **EDTF mapping.** Wikidata precisions 11, 10 and 9 map to EDTF `YYYY-MM-DD`, `YYYY-MM` and `YYYY`. Precision 8 (decade) maps to `YYYX`. Precision 7 (century) must *not* map to `YYXX`, because Wikidata's strict century runs 1801–1900 while `18XX` means 1800–1899; use an explicit interval such as `1801/1900`. Precisions 0–6 need interval bounds, or EDTF Level 2 significant digits. Keep the verbatim Wikibase value as the record of truth, with EDTF as a derived rendering.
7. **Quantity bounds and units.** Not needed yet, since there are no literal claims, but the design should not repeat YAGO's simplification. Store decimal strings, not REAL.
8. **Rank versus epistemic status.** Covered in Section 1. A deprecated claim that has no P2241 reason should stay `attributed` with `rank='deprecated'`.
9. **Contested and plural values.** acatalogue's `epistemic/contested` and `perspective` are *richer* than Wikidata's ranks, and they are the right place for this. Map P1480 values (disputed, allegedly, presumably, …) into qualifier rows first, and derive epistemic status only through recorded rules.
10. **Lexemes.** Not needed for a concept catalogue unless word-level (lexicographic) use cases appear. The `label` table is not a lexicon.

### Gaps
- I did not verify whether Wikidata's "statement disputed by" property is still recommended practice, or its property id.
- I did not verify how often `somevalue` and `novalue` snaks occur in Wikidata; no statistic was found.
- I did not verify the Python EDTF libraries (maintenance status, license). A small standard-library parser covering Levels 0–1 is the conservative choice.

---

## 5. Content-addressed and hash-verifiable provenance in practice (trusty URIs, Merkle structures, signed releases): what is proven to work at scale?

### Takeaway
The following are proven at scale:
- Hash-in-the-identifier, as in trusty URIs: 10M+ nanopublications, and files up to 177 GB.
- Merkle DAGs: Software Heritage's archive, reported at more than 50 billion artifacts, with SWHID standardized as ISO/IEC 18670:2025.
- Append-only Merkle logs with inclusion and consistency proofs: Certificate Transparency, RFC 9162.
- Canonicalize-then-hash for RDF: RDFC-1.0, a W3C Recommendation since 2024.
- Signed dataset releases: DBpedia Databus.

acatalogue already has the basic pieces: SHA-512 bytes, sealed corpora with a manifest hash, and a hash-chained ledger. It lacks a per-claim content hash, a precise pointer from each claim into its source bytes, O(log n) inclusion proofs, and signed or externally anchored checkpoints.

### Cited Findings
- **Trusty URIs** (Kuhn & Dumontier, ESWC 2014) — [slides PDF](https://pdfs.semanticscholar.org/74ce/57f3a4d62c53bbb2f89a02c6ee8f22531059.pdf):
  - The hash is embedded in the URI. There are two modules: "FA: Plain files (i.e. byte sequences)" and "RA: Sets of RDF graphs".
  - "Trusty URI artifacts are immutable, as any change in the content also changes its URI, thereby making it a new artifact".
  - The same trusty URI results from TriG, N-Quads and TriX serializations of one nanopub, so the hash does not depend on the format.
  - About 150,000 nanopubs were checked at about 0.001 s each. Corrupted copies failed validation, apart from under 1% harmless TriX cases. Bio2RDF files up to 177 GB took 29 h to transform and 3 h to check.
  - Blank nodes are Skolemized from the hash. The design was inspired by git and can be mapped to `ni:` URIs.
- More than 10M nanopublications had been published by 2018 — [arXiv:1809.06532](https://arxiv.org/abs/1809.06532). The guidelines recommend trusty URIs as integrity keys — [Nanopub guidelines](https://nanopub.net/guidelines/working_draft/).
- **RDF Dataset Canonicalization (RDFC-1.0)** is a W3C Recommendation of 21 May 2024. — [RDFC-1.0](https://www.w3.org/TR/rdf-canon/)
  - It canonically labels blank nodes and produces canonical N-Quads.
  - "The default hash algorithm used by RDFC-1.0, namely, SHA-256". Implementations "MUST support SHA-256 and SHA-384".
  - Uses: isomorphism checks, "Digital signing of graphs (datasets) independent of serialization", diffs and change sets.
- **Certificate Transparency** (RFC 9162, December 2021, Experimental, obsoletes RFC 6962) — [RFC 9162](https://www.rfc-editor.org/rfc/rfc9162.html):
  - "A log is a single, append-only Merkle Tree of submitted certificate and precertificate entries".
  - Inclusion proofs give "the shortest list of additional nodes in the Merkle Tree required to compute the Merkle Tree Hash".
  - "Merkle consistency proofs prove the append-only property of the tree".
  - Logs periodically sign their tree head, producing a signed tree head (STH). The hash algorithm is a log parameter.
- **SWHID / Software Heritage:**
  - SWHID was adopted as ISO/IEC 18670:2025 on 23 April 2025 — [ISO](https://www.iso.org/standard/89985.html); [swhid.org news](https://www.swhid.org/news/2025-04-23-swhid-standardized-as-iso-iec-18670/).
  - Identifiers are computed over a Merkle DAG. Software Heritage's archive is described as one enormous Merkle DAG of more than 50 billion artifacts. — [swhid.org](https://www.swhid.org/); [SWH "One year of SWHID as ISO/IEC 18670"](https://www.softwareheritage.org/2026/04/23/one-year-swhid-iso-iec-18670-standard/) (excerpt)
- **Signed releases:** DBpedia Databus signs data, metadata and license statements with private keys, verified by X.509 and WebID, and keeps dataset identity separate from its versions. — [DBpedia Databus](https://www.dbpedia.org/resources/databus/)
- **Wikidata's own hashes** are identifiers for deduplication, not integrity proofs: "The same reference will be usually represented with single node, though duplicate reference nodes are possible" — [RDF Dump Format](https://www.mediawiki.org/wiki/Wikibase/Indexing/RDF_Dump_Format). The live JSON shows 40-hex snak and reference hashes — [EntityData Q4115189](https://www.wikidata.org/wiki/Special:EntityData/Q4115189.json).
- **JSON Pointer** (RFC 6901, April 2013, Standards Track): "a string syntax for identifying a specific value within a JavaScript Object Notation (JSON) document". `~` is escaped as `~0` and `/` as `~1`. — [RFC 6901](https://www.rfc-editor.org/rfc/rfc6901.html)
- **Python's standard library:** the Cryptographic Services chapter ("The modules described in this chapter implement various algorithms of a cryptographic nature") offers hashing and HMAC but no public-key signature module. — [Python crypto services](https://docs.python.org/3/library/crypto.html)

### Inferences
- **Keep SHA-512.** Nothing in these systems suggests changing it, and SHA-512 is stronger than the SHA-256 that trusty URIs and RDFC use. For interchange (nanopub or trusty-URI export, RDFC hashes), compute SHA-256 at export time. Do not re-key the store.
- **Per-claim content hash** (the trusty-URI idea applied to claims). Define a canonical claim serialization, for example JSON with sorted keys, UTF-8 and no insignificant whitespace, covering:
  - subject, predicate, snaktype, object or value, typed datavalue;
  - ordered qualifier snaks and their references' hashes;
  - rank, `valid_*`, `source_sha512` and `source_locator`.

  Store its SHA-512 as `claim.content_sha512`. This gives an intrinsic claim identifier that stays stable across re-imports. It lets the catalogue detect an unchanged statement cheaply when a corpus is refreshed, and it makes single claims citable and verifiable. Keep hashed canonical JSON as text: SQLite's JSONB is an internal, non-portable format.
- **Exact-byte locator.** Add `source_locator` (an RFC 6901 JSON Pointer such as `/entities/Q42/claims/P31/0`, or a byte range for non-JSON sources). Verification then means: fetch the bytes by SHA-512, re-hash them, resolve the pointer, and compare with the claim row. Today 4,045 claims point at 3 blobs with no locator, which is coarse.
- **Merkle-ized corpus manifests.** The current `manifest_sha512` is one flat hash over sorted (name, sha512) lines. That is fine for sealing, but proving that one item belongs to a corpus means rehashing the whole list. Replacing it, or adding an RFC 9162-style Merkle root with domain-separated leaf and node hashing over the same sorted list, gives:
  - O(log n) inclusion proofs for single sources, which matters for corpora of millions of Wikidata entities;
  - consistency proofs between successive dated corpora.

  This needs only `hashlib`.
- **Anchored and signed checkpoints.** The ledger's hash chain proves order but not that its head was not silently rewritten. Periodically publish the ledger's `(seq, hash)` head and the corpus Merkle roots somewhere append-only and outside the database, such as a signed git tag or commit in the repository, or a Databus-style signed release manifest.
  - The standard library cannot sign with public keys. Use an external signer such as git's or OpenSSH's signing (my suggestion, not researched here), or add one small, well-maintained dependency. Treat signing as optional; anchoring the hash is the essential step.

### Gaps
- I did not verify whether SWHID's hash (git-compatible SHA-1 in earlier versions) changed in V1.2.
- I found no evidence of a knowledge base publishing per-statement Merkle proofs at Wikidata scale. Nanopublications (10M+) are the closest proven case of per-statement hashes.
- I did not verify the Nanopub Registry's current size or design.

---

## 6. Prioritized recommendations for acatalogue's schema and validation layer (add / change / keep), each with its evidence

### Takeaway
First fix identity and fidelity, before scaling toward all of Wikidata:
1. Key claims by Wikidata statement GUID and entity revision.
2. Ingest from entity JSON with a JSON-Pointer locator.
3. Add snak types.
4. Stop equating "deprecated" with "superseded".

Then make qualifiers, references and precise time first-class rows. Build a SQL rule layer that imports Wikidata's own constraints as data. Finally add claim hashes, Merkle manifests and RDF 1.2 / PROV-O / nanopub exports.

Keep the exact-byte source table, the never-delete triggers, the bitemporal columns, the hash-chained ledger and the richer epistemic vocabulary. They already match best practice (nanopub immutability, Wikidata's deprecate-don't-delete policy, DBpedia's quarantine).

### Cited Findings
The evidence for each recommendation is in Sections 1–5. The most load-bearing items:
- A statement GUID exists for every Wikidata statement. The entity JSON carries `lastrevid` and `modified`. — [Wikibase JSON docs](https://doc.wikimedia.org/Wikibase/master/php/docs_topics_json.html); [EntityData Q4115189](https://www.wikidata.org/wiki/Special:EntityData/Q4115189.json)
- Qualifiers can distinguish statements that share a value (separators). — [Ferranti et al.](https://journals.sagepub.com/doi/full/10.3233/SW-243611)
- The relational Statement/Qualifier schema, keyed by statement id, benchmarked fastest. — [Hernández et al.](https://aidanhogan.com/docs/wikidata-sparql-relational-graph.pdf)
- Deprecated ≠ superseded; P2241 reasons separate the cases. — [Help:Ranking](https://www.wikidata.org/wiki/Help:Ranking); [P2241](https://www.wikidata.org/wiki/Property:P2241)
- Truthy/best rank semantics, `wdno:`/somevalue, and hash-identified references. — [RDF Dump Format](https://www.mediawiki.org/wiki/Wikibase/Indexing/RDF_Dump_Format)
- Only about 68–73% of statements are referenced, referencing quality scores 0.58/1, and P143-only statements count as unsourced. — [Reference stats](https://researchportal.hw.ac.uk/files/53252708/Reference_Statistics_in_Wikidata_Topical_Subsets_corrected_version.pdf); [RQSS](https://www.semantic-web-journal.net/content/rqss-referencing-quality-scoring-system-wikidata); [Help:Sources](https://www.wikidata.org/wiki/Help:Sources)
- Wikidata publishes 32 constraint types and more than 72K definitions. They are advisory, carry exceptions and statuses, and SHACL-Core falls short on 6 types. — [Ferranti et al.](https://journals.sagepub.com/doi/full/10.3233/SW-243611); [constraints portal](https://www.wikidata.org/wiki/Help:Property_constraints_portal)
- YAGO's taxonomy defects and cleaning rules. — [YAGO 4.5](https://arxiv.org/abs/2308.11884)
- DBpedia keeps filtered errors in separate files. — [DBpedia Post-Processing](http://dev.dbpedia.org/Post-Processing)
- Trusty URIs, RDFC-1.0, RFC 9162, SWHID and Databus signing. — see Section 5.
- SQLite features: JSON built-in (3.38), JSONB internal-only (3.45), STRICT (3.37), generated columns (3.31), REGEXP via a user function. — [json1](https://www.sqlite.org/json1.html), [STRICT](https://www.sqlite.org/stricttables.html), [gencol](https://www.sqlite.org/gencol.html), [lang_expr](https://www.sqlite.org/lang_expr.html)
- Local facts: 4,045 claims from 3 SPARQL blobs; 0 qualifiers; 0 dates; 81 deprecated→superseded. — local DB query; [schema.sql](/home/user/acatalogue/acatalogue/schema.sql)

### Inferences (recommendations)

**P0: fix before any large import (correctness and provenance fidelity)**
1. **CHANGE the claim identity.**
   - Add `ext_id TEXT` (Wikidata statement GUID) and `ext_rev INTEGER` (entity `lastrevid`).
   - Rebuild `claim_identity` to include `coalesce(ext_id,'')`, or add `UNIQUE(source_sha512, ext_id) WHERE ext_id IS NOT NULL`. Dropping and recreating an index deletes no data.

   Without this, the first import of qualified statements, such as two terms in the same office, silently merges distinct statements. *Evidence:* JSON GUIDs; Ferranti's separators; Hernández's statement-id key.
2. **CHANGE the Wikidata ingest source to entity JSON.** Use Special:EntityData or wbgetentities for small sets, and JSON dumps at scale. Store one source row per entity revision. Add `source_locator TEXT` (RFC 6901 JSON Pointer) to `claim`.
   - WDQS result tables are a derived, truthy-oriented projection and lack GUIDs, qualifiers, references, snak types and revision pins.
   - YAGO needed the *full* dump, not the truthy one, to recover time stamps.

   *Evidence:* EntityData fields; RDF truthy definition; YAGO 4.5; RFC 6901; local: 3 blobs for 4,045 claims.
3. **ADD `snaktype`** (`value` | `somevalue` | `novalue`) and relax the CHECK to:

   `(snaktype='value' AND (object IS NULL) <> (value IS NULL)) OR (snaktype<>'value' AND object IS NULL AND value IS NULL)`

   In SQLite this needs a one-time table rebuild. Record it in the ledger with before and after row counts and a digest of all rows, because rows are copied, not deleted. *Evidence:* the DataModel snak types; the RDF `wdno:` and blank-node mappings.
4. **CHANGE the rank → epistemic mapping.**
   - Keep `rank` verbatim.
   - Default deprecated claims to `epistemic/attributed`.
   - Assign `superseded` (for example P2241 = superseded by later scholarship, or withdrawn/deprecated identifier) or `refuted` (for example incorrect value, error in referenced source, typographical error, conflation, refers to different subject) only through a named, ledgered rule, as the epistemic scheme requires.

   *Evidence:* Help:Ranking; P2241 values; the local scheme definitions.

**P1: first-class structure (additive tables; STRICT for new tables)**

5. **ADD `claim_qualifier`.** It follows Hernández's relational schema and Wikibase `qualifiers-order`.
   ```sql
   CREATE TABLE claim_qualifier (
     claim_id  INTEGER NOT NULL REFERENCES claim(id),
     ord       INTEGER NOT NULL,           -- position from qualifiers-order + list index
     property  TEXT NOT NULL,              -- 'wd/P580'
     snaktype  TEXT NOT NULL CHECK (snaktype IN ('value','somevalue','novalue')),
     object    TEXT, value TEXT,           -- entity id | lexical form
     datatype  TEXT,                       -- 'time','quantity','wikibase-item',...
     datavalue TEXT,                       -- verbatim datavalue JSON (text, not JSONB)
     snak_hash TEXT,                       -- Wikidata's snak hash, if present
     PRIMARY KEY (claim_id, ord)) STRICT;
   CREATE INDEX claim_qualifier_prop ON claim_qualifier(property, object);
   ```
   Keep `claim.qualifiers` only as a derived cache, or retire it. Most WDQS example queries (80 of 94) were tree-shaped with a bound predicate, and 11 of 94 used qualifiers (Hernández et al.), so plain indexes on `(predicate, subject)`, `(predicate, object)` and `claim_qualifier(property, object)` cover the common patterns.
6. **ADD references as deduplicated rows**, mirroring Wikidata's hash-identified `wdref:` nodes.
   ```sql
   CREATE TABLE reference (hash TEXT PRIMARY KEY,          -- Wikidata ref hash, or SHA-512 of canonical snaks
                           first_source_sha512 TEXT NOT NULL REFERENCES source(sha512)) STRICT;
   CREATE TABLE reference_snak (ref_hash TEXT NOT NULL REFERENCES reference(hash), ord INTEGER NOT NULL,
                                property TEXT NOT NULL, snaktype TEXT NOT NULL, object TEXT, value TEXT,
                                datatype TEXT, datavalue TEXT, PRIMARY KEY (ref_hash, ord)) STRICT;
   CREATE TABLE claim_reference (claim_id INTEGER NOT NULL REFERENCES claim(id),
                                 ref_hash TEXT NOT NULL REFERENCES reference(hash), ord INTEGER NOT NULL,
                                 PRIMARY KEY (claim_id, ref_hash)) STRICT;
   ```
   Derive `is_sourced`, which is false when a claim's only references are P143 "imported from Wikimedia project". This gives two provenance levels:
   - **acatalogue level:** exact source bytes plus locator, i.e. what Wikidata said and when.
   - **Wikidata level:** stated in, reference URL, retrieved, quotation, i.e. what Wikidata cites.

   In PROV-O terms these are `wasDerivedFrom` versus `hadPrimarySource` or `wasQuotedFrom`. *Evidence:* Help:Sources; the RDF dump's `wdref:`; reference-coverage studies; PROV-O.
7. **ADD typed time.** Either add columns (`valid_from_precision`, `valid_to_precision`, `calendar`, `valid_from_lo`, `valid_to_hi`) or add a `time_value` table.
   ```sql
   CREATE TABLE time_value (claim_id INTEGER NOT NULL REFERENCES claim(id),
     role TEXT NOT NULL,                  -- 'value' | 'valid_from' | 'valid_to' | 'qualifier:<P>'
     wikibase_time TEXT NOT NULL,         -- verbatim '+1879-03-14T00:00:00Z'
     precision INTEGER NOT NULL CHECK (precision BETWEEN 0 AND 14),
     calendar TEXT NOT NULL CHECK (calendar IN ('gregorian','julian','unspecified')),
     edtf TEXT,                           -- derived rendering (Level 0/1; interval for century)
     lo_jdn INTEGER, hi_jdn INTEGER,      -- inclusive day bounds from value+precision (+P1319/P1326)
     PRIMARY KEY (claim_id, role)) STRICT;
   ```
   - Populate `valid_from` and `valid_to` from start-time and end-time qualifiers (P580/P582, as in the Lincoln example in Hernández et al.).
   - Compute the bounds in pure Python (Julian Day Numbers work across BCE and deep time), applying the JSON-versus-RDF year-0 shift and the strict century and millennium reading.
   - Query "what was true in year X" with the integer bounds, never with string comparison.

   *Evidence:* the DataModel precision codes; Help:Dates; EDTF; YAGO's retention of time stamps.
8. **ADD quantity fields when literal claims arrive:** `amount`, `lower`, `upper` (decimal strings) and a `unit` entity id. Never store them as REAL, and never simplify them away. *Evidence:* the DataModel and JSON docs; YAGO's lossy simplification.
9. **ADD views, not deletions:**
   - `v_claim_current` (`superseded_at IS NULL`);
   - `v_claim_truthy` (best non-deprecated rank per `(subject, predicate)`, `snaktype='value'`);
   - `v_claim_clean` (truthy minus open *violation*-severity findings);
   - an as-of query over `recorded_at` and `superseded_at`.

   *Evidence:* the RDF truthy definition; YAGO's truthy-only policy; DBpedia's quarantine.

**P1: validation layer**

10. **ADD a rule engine in SQL.** Tables: `rule` (type Q-id, property, params JSON, severity, `sql_sha512`, `source_sha512`), `rule_exception` (from P2303), `validation_run` (ledger seq, ruleset hash) and an append-only `violation` table (run, rule, focus, claim, outcome ∈ violation / warning / info / unknown).
    - Import Wikidata's P2302 constraint statements for every property in use, as sourced data.
    - Implement templates in the order of observed violation frequency and cost: one-of, item-requires-statement, single-value (with separators) and single-best-value, required qualifier, value-requires-statement, then value-type, subject type, format (regexp UDF), distinct-values, conflicts-with, range, difference-within-range, allowed qualifiers, property scope, inverse/symmetric, integer, allowed units.
    - Use Ferranti et al.'s SPARQL formalization for all 32 types as the specification.

    *Evidence:* Ferranti et al.; the constraints portal; Shenoy et al.; the SHACL 1.2 severity names.
11. **ADD taxonomy integrity checks** based on YAGO 4.5 and KBpedia: `broader` and P279 cycles; redundant transitive links; classes under two disjoint facets or top concepts (declare disjointness in the facet schemes); items that are both instance and class (P31 plus P279, i.e. punning); classes with no instances or descendants. Flag them only; deprecate a concept only through a ledgered decision. *Evidence:* YAGO 4.5's counts (57 loops, 40k transitive links, 9k disjointness links, 1.3M empty classes); KBpedia's disjoint typologies.
12. **ADD RDFUnit-style auto-generated tests** from acatalogue's own axioms, plus YAGO-style gold-standard fixtures for each pipeline step, in `tests/`. *Evidence:* RDFUnit; YAGO 4.5.
13. **Do not adopt SHACL or ShEx as the store's validator.** Optionally generate SHACL shapes (with SHACL 1.2 `sh:reifierShape` for claim reifiers) or ShEx for export. *Evidence:* SHACL-Core's gaps and scale limits (Ferranti); SHACL 1.2 is a Working Draft; IEEE P3330 is a draft.

**P2: integrity and interchange**

14. **ADD `claim.content_sha512`** over a documented canonical JSON of the claim, its qualifiers, reference hashes and locator, giving a trusty-URI-like intrinsic identity. *Evidence:* trusty URIs; nanopub guidelines; RDFC-1.0's rationale.
15. **ADD a Merkle root** (RFC 9162-style) to `corpus` next to `manifest_sha512`, and give each source its inclusion proof on demand. Periodically anchor and optionally sign `(ledger head, corpus roots)` outside the database, for example in a signed git tag or a release manifest. *Evidence:* RFC 9162; SWHID/Software Heritage; Databus signing; Python's lack of public-key signing.
16. **ADD exporters (no storage change):**
    - RDF 1.2 Full, with the claim id as reifier and `rdf:reifies`;
    - a Wikidata-compatible n-ary layout, which works under RDF 1.1 and RDF 1.2 Basic;
    - PROV-O for sources, fetch activities and the ledger;
    - nanopublications per claim or bundle, with SHA-256 trusty URIs computed at export.

    Avoid singleton properties. *Evidence:* RDF 1.2 CR status and conformance levels; Hernández et al. 2015; PROV-O; nanopub guidelines.

**P3: later or conditional**

17. **Subsetting policy for "all of Wikidata".** Express YAGO-like exclusions (scholarly articles, 39M entities; linguistic objects, about 700k; Wikimedia housekeeping classes) as recorded filter rules and views, not deletions, and decide deliberately which ones to fetch at all. *Evidence:* YAGO 4.5; Wikidata's scale (123M items; 1.65B statements in early 2025).
18. **Lexeme layer** (L/F/S with P5137 links), only if lexicographic features are wanted. It is CC0. *Evidence:* the lexicographical data documentation.
19. **SQLite hygiene.**
    - Use STRICT for new tables.
    - Use generated columns for fields extracted from verbatim JSON (for example `json_extract(datavalue,'$.value.precision')`).
    - Hash and cite text JSON only; use JSONB solely in rebuildable caches.
    - Register `regexp` from Python.

    *Evidence:* the SQLite docs cited in Section 3.

**KEEP (already best practice)**
- **The exact-byte `source` table keyed by SHA-512, with delete-blocking triggers.** It is stronger than Wikidata's deduplication hashes and is in the spirit of trusty URIs and SWHID.
- **Never-delete claims and concepts** (superseded or deprecated instead). This matches Wikidata's policy that deprecated statements stay verifiable and are not removed, nanopublications' immutability, and DBpedia's retention of filtered errors.
- **Bitemporal columns** (world time and record time). They are the right skeleton; they only need precision and bounds (P1 item 7).
- **The append-only, hash-chained ledger.** Add anchoring and Merkle proofs (P2), but keep the chain.
- **The epistemic vocabulary and `perspective`.** They express attribution, contestation and tradition beyond Wikidata's three ranks and P1480. Keep ranks and P1480 as source facts, and derive epistemic status only through recorded rules.

### Gaps
- I did not measure the storage and index cost of the proposed tables at Wikidata scale (1.65B statements, plus qualifiers and references). This needs a benchmark on a sample dump.
- I did not verify whether Special:EntityData accepts a revision parameter for re-fetching an exact past revision.
- The recommended P2241 → epistemic mapping is my proposal; it has not been validated against real deprecated statements.
- I have no evidence on how often acatalogue's current P31/P279/P527 claims carry qualifiers in Wikidata, which would size the immediate benefit of P0 items 1–2. Sample 100 entity JSONs to measure it.
