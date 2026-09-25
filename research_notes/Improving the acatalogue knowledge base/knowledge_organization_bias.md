# Knowledge organization and bias measurement: evidence for improving the acatalogue compendium

Scope and method. These notes cover classification theory (facets, citation order, notation), SKOS/SKOS-XL practice, critiques of universal classification, Indigenous and decolonizing knowledge organization, and how content bias in Wikipedia/Wikidata is measured. Section 6 ends with prioritized recommendations for acatalogue. Dashboards were checked live on 2026-09-25. Where a claim rests only on a search-engine summary of a page I did not fetch, it is marked "(search summary)". Facts about acatalogue itself cite repository files (paths relative to this notes file).

Current acatalogue baseline, for reference:
- Labels have three kinds: `pref`, `alt`, `desc`. There is no hidden-label kind — [acatalogue/schema.sql](../../acatalogue/schema.sql).
- Concepts have `status` (`active`/`deprecated`) and `replaced_by`. A trigger blocks deletion ("concepts are never deleted; set status = deprecated"). Mappings are limited to the five SKOS mapping relations and carry `method`, `status` and `reviewer` — [acatalogue/schema.sql](../../acatalogue/schema.sql); [seed/crosswalk/acat-wikidata.tsv](../../seed/crosswalk/acat-wikidata.tsv).
- Compendium seed columns are `code, broader, label, alt, scope_note, related, facets, notation, when` — [seed/compendium/acat/belief.tsv](../../seed/compendium/acat/belief.tsv).
- `acat audit` currently reports:
  - per-domain concept counts, Wikidata reconciliation, and median and minimum sitelinks;
  - the 25 "thinnest" concepts;
  - concepts tagged per UN M49 region;
  - label-language counts;
  - unmatched concepts;
  - "hierarchy_vs_wikidata": stated vs. not-stated parent links, noting that "'Not stated' is not 'disagrees'" — [acatalogue/views.py](../../acatalogue/views.py).
- The epistemic-status facet is defined on statements, not topics: "How a statement stored in the catalogue is known. Every claim carries exactly one status…" — [seed/schemes/epistemic.tsv](../../seed/schemes/epistemic.tsv).

---

## 1. Faceted classification in practice (Colon Classification/PMEST, FAST, UDC auxiliaries, BC2): lessons for facet design, citation order and notation

### Takeaway
Facet theory has several lessons that hold up:
- **One characteristic per facet.** Each facet uses one characteristic of division, and facets are mutually exclusive and can be combined independently.
- **A declared citation order with inverted filing.** PMEST and BC2 both run from concrete to abstract and end with space then time. Filing inverts that order so that general sorts before specific.
- **Self-indicating notation.** Notation that marks each facet makes it obvious which facets are present and which are absent.

Two limits apply. In post-coordinate digital systems, citation order mostly affects display and sorting. And the schemes' own histories show that maintenance and governance decide adoption more than theoretical elegance does.

### Cited Findings
**Colon Classification (CC) and PMEST**
- Ranganathan is credited with introducing the term "facet" into knowledge organization around the mid-20th century — [ISKO Encyclopedia: Facet](https://www.isko.org/cyclo/facet) (search summary).
- PMEST stands for Personality, Matter, Energy, Space, Time. In the entry's words, "categories are arranged in order of decreasing concreteness: [P] Personality is the most concrete and [T] Time the most abstract" — [ISKO: Colon Classification (M.P. Satija)](https://www.isko.org/cyclo/colon_classification).
- Notation changed across editions — [ISKO: Colon Classification](https://www.isko.org/cyclo/colon_classification):
  - Editions 1–3 (1933–1950) joined every facet with a colon, so absent categories needed dummy colons (e.g., `2::::N`).
  - Editions 4–7 (1952–1987) gave each category its own connecting symbol: comma = Personality, semicolon = Matter, colon = Energy, dot = Space, apostrophe = Time. Hence "the absence or presence of any category was self, or automatically indicated."
  - Edition 7's notation uses 74 symbols: 60 semantic and 14 indicator.
- Rounds and levels let a category recur within one subject. Space and Time occur only in the last round, and Energy completes a round — [ISKO: Colon Classification](https://www.isko.org/cyclo/colon_classification).
- Phase relations between subjects have indicator digits: general (a), bias (b), comparison (c), difference (d), tool (e), influencing (g) — [ISKO: Colon Classification](https://www.isko.org/cyclo/colon_classification).
- Ranganathan's canons — [ISKO: Colon Classification](https://www.isko.org/cyclo/colon_classification):
  - Arrays: exhaustiveness; exclusiveness ("an entity should belong to one and only one array"); helpful sequence.
  - Chains: decreasing extension; modulation ("no link in the chain should be missed").
  - Characteristics must be relevant to the purpose, objective, and permanent.
  - The whole theory runs to "55 canons, 22 principles, 13 postulates, and 10 devices."
- Status and criticism — [ISKO: Colon Classification](https://www.isko.org/cyclo/colon_classification):
  - The 6th edition (1960) "remains the most popular, used and stable edition."
  - The 7th edition (1987) is "considered by many to be confused and inconsistent" and was "discarded by the Indian library profession." "No new library is adopting it."
  - Its notation is lengthy and "unpopular, even dreaded."
  - Parrochia and Neuville argue that "the same subject may be classified in many different ways."
  - The success of schemes is "related less to their theoretical and research based qualities than to the strength of support for maintaining systems."

**Facet analysis and the Classification Research Group (CRG)**
- Hjørland (2013) defines facet analysis as "the sorting of terms in a given field of knowledge into homogeneous, mutually exclusive facets, each derived from single characteristic of division" — [ISKO: Facet analysis (Hjørland)](https://www.isko.org/cyclo/facet_analysis). The same entry gives these rules:
  - Apply one characteristic of division at a time, and divide exhaustively.
  - Keep facets mutually exclusive and independent.
  - Citation order differs from filing order through inversion.
  - Synthetic notation is "composed of sections, each of which stands for a special aspect."
- B.C. Vickery (CRG) proposed 13 fundamental categories: Substance, Organ, Constituent, Structure, Shape, Property, Object of Action, Action, Operation, Process, Agent, Space, Time. Broughton found such categories "sufficient for almost all areas of knowledge" — [ISKO: Facet analysis](https://www.isko.org/cyclo/facet_analysis).
- On digital systems, "sequence or order of concepts in combination is less vital in a digital context" — [ISKO: Facet analysis](https://www.isko.org/cyclo/facet_analysis).
- Critiques — [ISKO: Facet analysis](https://www.isko.org/cyclo/facet_analysis):
  - Facet analysis is rationalist and a priori.
  - It neglects domain analysis: semantic primitives "are models constructed by specialists in specific domains."
  - It gives no guidance on fitting a scheme to particular collections, users or purposes.
  - Miksa argues its logical base "narrowed the base for investigating" classification.

**Bliss Bibliographic Classification, 2nd edition (BC2)**
- Jack Mills and Vanda Broughton edited BC2, published from 1977 — [ISKO: BC2 (Broughton)](https://www.isko.org/cyclo/bc2):
  - 15 volumes have been published, including P Religion (1977), K Society (1984), W The Arts (2007) and C Chemistry (2012).
  - Draft schedules for about 12 more classes are on the Bliss Classification Association (BCA) website.
- Citation order as reported by the entry: "Thing – kind – part – material – property – process – operation – agent – space – time". It follows decreasing concreteness and dependency: operations depend on entities to operate on — [ISKO: BC2](https://www.isko.org/cyclo/bc2).
- Filing order reverses citation order ("principle of inversion") so that general comes before special. For example, "sixteenth century English poetry" files after "English poetry" — [ISKO: BC2](https://www.isko.org/cyclo/bc2).
- Notation — [ISKO: BC2](https://www.isko.org/cyclo/bc2):
  - It is fully faceted, retroactive and non-expressive. This gives short class marks but "complicates digital retrieval and machine interpretation."
  - Intercalators confuse classifiers.
- Maintenance — [ISKO: BC2](https://www.isko.org/cyclo/bc2):
  - There is "no formal provision" for updates; the scheme depends on volunteer effort.
  - It arrived "too late" to compete with the "monolithic unity" and centralized revision of DDC and LCC.
- Influence — [ISKO: BC2](https://www.isko.org/cyclo/bc2):
  - UDC converted BC2 structures for health (Class H mapping) and for Religion. For Religion, a special auxiliary replaced colon devices and produced briefer numbers.
  - BC2 served as the "terminological foundation" for several thesauri.

**Universal Decimal Classification (UDC)**
- UDC has main classes 0–9, with class 4 vacant — [UDC Consortium: Structure and Tables](https://udcc.org/index.php/site/page?view=about_structure).
- Its common auxiliary tables are — [UDC Consortium: Structure and Tables](https://udcc.org/index.php/site/page?view=about_structure):
  - 1a: `+`, `/` (coordination, consecutive extension)
  - 1b: `:`, `::`, `[ ]` (relation, order-fixing, subgrouping)
  - 1c: `=` (language)
  - 1d: `(0…)` (form)
  - 1e: `(1/9)` (place)
  - 1f: `(=…)` (human ancestry, ethnic grouping, nationality)
  - 1g: `"…"` (time)
  - 1k: `-02`, `-03`, `-04`, `-05` (properties, materials, relations/processes, persons)
  - 1h: `*`, `A/Z` (non-UDC notation, alphabetical extension)
- Class 2 Religion was "completely revised" from 2000 (Extensions and Corrections 22), with later updates for Buddhism (2001), Eastern Christianity (2002) and Islam (2006–2011). It now treats all religions with equal standing — [UDC Consortium: Major Revisions](https://udcc.org/index.php/site/page?view=major_revisions). Other revisions from the same source:
  - Place auxiliaries were revised 1993–2013 for geopolitical change (the USSR, Yugoslavia, and South Sudan in 2011).
  - The "Point of view" table was cancelled in 1999 and replaced by `-02`, `-05` and colon combinations.
- The 2000 Class 2 schedule introduced a single special auxiliary table built on facet analysis and usable in any class of the main table — [ResearchGate: "UDC class 2: theology and religion – new schedule"](https://www.researchgate.net/publication/50247520_UDC_class_2_theology_and_religion_-_new_schedule) (search summary):
  - Its auxiliaries include `-1` Theory and philosophy of religion, `-2` Evidence of religion, and `-23` Sacred books.
  - Religions are arranged historically, related religions sit next to each other, and religious groups are ranked equally.

**FAST (Faceted Application of Subject Terminology)**
- The current OCLC page describes FAST as follows — [OCLC Research: FAST](https://www.oclc.org/research/areas/data-science/fast.html):
  - It is derived from LCSH, developed by OCLC Research and the Library of Congress, with work beginning in "late 1998."
  - It is "a nine-facet vocabulary with a universe of approximately 1.8 million headings across all facets."
  - Its facets "are designed to be used in tandem, but each may also be used independently."
  - "Any valid set of LC subject headings can be converted to FAST headings."
- The November 2019 FAQ says "FAST has eight FACETS" — [OCLC FAST FAQ (Nov 2019)](https://www.oclc.org/content/dam/oclc/fast/FAST-FAQ-Nov2019.pdf):
  - Seven describe what a resource is about: Topical, Personal Names, Corporate Names, Event, Uniform Titles, Chronological ("controlled terms that identify time periods"), Geographic.
  - One, Form/Genre, describes what the resource is.
  - FAST data files are licensed ODC-By.
- The two OCLC sources disagree: eight facets in the 2019 FAQ, nine on the current page. See Gaps.

### Inferences
- **acatalogue's facets align with the most stable cross-scheme facets.** Place and time recur in every tradition surveyed: PMEST's S and T, BC2's space and time, UDC tables 1e/1g, FAST Geographic and Chronological. Two further facets have strong precedent:
  - language (UDC 1c);
  - form/genre for documents (UDC 1d; FAST Form/Genre).

  A "people/ethnic grouping" facet (UDC 1f) has precedent too, but it is ethically sensitive (see section 4).
- **Keep each facet to one characteristic.** acatalogue already attaches epistemic status to claims, not to topics. That keeps topical and epistemic characteristics apart, as facet analysis requires. "Kind" should stay a single ontological characteristic, not a mix of ontology and genre.
- **Declare a citation order and an inverted filing order.** These are for human-readable composite strings and sort keys; they are not needed for storage. A defensible order, following PMEST and BC2 from concrete to abstract with space and time last, is: compendium concept → kind → where → when → epistemic status. In lists, show the bare concept before its faceted compounds.
- **Use expressive, self-delimiting facet notation.** Use key–value or indicator-based notation rather than positional codes, e.g. `acat/music | m49:002 | y:1900..1999 | kind:practice`. The CC lesson is that presence or absence of a facet should be self-evident. The BC2 lesson is that non-expressive notation hinders machine use. The 13 domain codes should stay nominal slugs, never ordinals, so that no rank is implied.
- **Adopt the UDC Class 2 pattern: equal siblings plus shared cross-cutting "aspects".** One aspect facet applies uniformly to every tradition (theory, texts, practice, institutions, places, history). This takes the "equal siblings" rule below the top level, because every tradition gets the same subdivisions.
- **Poly-hierarchy is a deliberate departure from the canon of exclusiveness.** It is supported by SKOS (section 2) and by critical theory (section 3), but it should be audited: report the number of parents per concept and the cross-domain parents.
- **Epistemic status fails the canon of "permanence".** Status assignments change, so every assignment needs a date and a history.
- **Answer Hjørland's critique with a recorded warrant for each sibling array.** For example, UN M49 is the warrant for regions; a named authority for language families; a tradition's self-description for tradition subdivisions.
- **Maintenance decides survival.** CC and BC2 stalled without institutional maintenance. acatalogue needs a documented maintenance cycle (versions, change lists, comment windows) more than it needs a more elaborate facet theory.

### Gaps
- BC2's citation order: the ISKO summary lists "material" before "property" and omits patient, product and by-product. Other BC2 literature may differ, and I did not verify a primary Mills/Broughton text.
- The ninth FAST facet named on the current OCLC page was not identified; the 2019 FAQ lists eight.
- Ranganathan's primary texts (Prolegomena, CC 6th ed.) were not consulted; CC facts come from the ISKO entry.
- The UDC Summary's licence and language coverage were not verified this session.

---

## 2. SKOS and SKOS-XL: concept schemes, labels, notes, mappings, collections, versioning/deprecation

### Takeaway
SKOS already gives acatalogue a contract for labels, notes, hierarchy, mappings and collections. Several of its formal integrity conditions (S13, S14, S27, S46, and the unique-notation convention) can become automated tests.

SKOS says nothing about versioning. Community practice fills that gap: `owl:deprecated`, `dct:isReplacedBy`, `skos:historyNote`/`skos:changeNote` and `owl:versionInfo`. SKOS-XL is the standard way to record provenance per label, which matters for community-preferred names and for disputed names.

### Cited Findings
- The SKOS Reference became a W3C Recommendation on 18 August 2009 — [W3C SKOS Reference](https://www.w3.org/TR/skos-reference/).
- **Labels:**
  - S13: `skos:prefLabel`, `skos:altLabel` and `skos:hiddenLabel` are "pairwise disjoint properties."
  - S14: "A resource has no more than one value of `skos:prefLabel` per language tag."
  - Language tags are distinct strings: "'en', 'en-US' and 'en-GB' are three different language tags" (Example 18).

  — [W3C SKOS Reference §5](https://www.w3.org/TR/skos-reference/)
- **Hidden labels** serve text search. "The user may, for example, enter mis-spelled words … If the mis-spelled query can be matched against a hidden label, the user will be able to find the relevant concept, but the hidden label won't otherwise be visible to the user" — [W3C SKOS Reference §5.1](https://www.w3.org/TR/skos-reference/).
- **Notation:**
  - `skos:notation` is assigned as a typed literal (S15).
  - "By convention, no two concepts in the same concept scheme are given the same notation" (§6.5.3).

  — [W3C SKOS Reference §6](https://www.w3.org/TR/skos-reference/)
- **Notes:** `skos:note` has six sub-properties: `changeNote`, `definition`, `editorialNote`, `example`, `historyNote`, `scopeNote` (S16–S17). There is "no restriction on the nature of this information." The framework can be "extended by third parties" (§7.1) — [W3C SKOS Reference §7](https://www.w3.org/TR/skos-reference/).
- **Hierarchy and association** — [W3C SKOS Reference §8](https://www.w3.org/TR/skos-reference/):
  - `skos:broader` is not itself transitive (§8.6.6). It is a sub-property of the transitive `skos:broaderTransitive` (S22, S24), which serves for inference, not assertion (§8.1).
  - `skos:related` is symmetric (S23) and disjoint with `skos:broaderTransitive` (S27).
  - "Polyhierarchy allowed": there is no condition requiring only one path between two nodes (§8.6.9).
- **Concept schemes** — [W3C SKOS Reference §4](https://www.w3.org/TR/skos-reference/):
  - `skos:topConceptOf` is a sub-property of `skos:inScheme` and the inverse of `skos:hasTopConcept` (S7–S8).
  - A concept may belong to "zero, one, or more than one concept scheme" (§4.6.1).
- **Collections** — [W3C SKOS Reference §9](https://www.w3.org/TR/skos-reference/):
  - `skos:Collection` and `skos:OrderedCollection` (with `skos:memberList`, an `rdf:List`) are disjoint from `skos:Concept` and `skos:ConceptScheme` (S37).
  - Collections therefore cannot take part in semantic relations with concepts (§9.6.4).
- **Mapping properties** — [W3C SKOS Reference §10](https://www.w3.org/TR/skos-reference/):
  - `broadMatch`, `narrowMatch` and `relatedMatch` are sub-properties of `broader`, `narrower` and `related` (S41).
  - `exactMatch` is a sub-property of `closeMatch` (S42), is transitive (S45), and is disjoint with `broadMatch` and `relatedMatch` (S46).
  - "By convention, the SKOS mapping properties are only used to link concepts in different concept schemes" (§10.6.1).
- **SKOS-XL** exists because "some applications require additional functionality relating to labels, for example allowing the description of those labels or the definition of additional relations between the labels (such as acronyms)." Each `skosxl:Label` has exactly one `skosxl:literalForm`. `skosxl:prefLabel`, `skosxl:altLabel` and `skosxl:hiddenLabel` can be "dumbed down" to the plain SKOS label properties (B.3.4.2) — [W3C SKOS Reference, Appendix B](https://www.w3.org/TR/skos-reference/).
- **Versioning** is out of scope: the SKOS Reference defines no versioning or deprecation properties — [W3C SKOS Reference](https://www.w3.org/TR/skos-reference/) (fetched and checked for such terms).
- **Deprecation in practice:**
  - Skosmos detects a deprecated concept when its data includes `owl:deprecated true`, optionally with `dcterms:isReplacedBy` pointing to replacements — [Skosmos Data Model wiki](https://github.com/NatLibFi/Skosmos/wiki/Data-Model).
  - Skosmos PR #2071 displays deprecated concepts that have no `isReplacedBy` with strikethrough — [NatLibFi/Skosmos PR #2071](https://github.com/NatLibFi/Skosmos/pull/2071).
  - Practitioner guidance recommends `owl:deprecated` + `dct:isReplacedBy` + `skos:historyNote` ("records the why"). It also lists `dcterms:created`/`modified`, `dcterms:replaces`, `owl:priorVersion`, `owl:versionInfo` and `skos:changeNote` — [Heimsbakk, "SKOS in the Pipeline"](https://veronahe.substack.com/p/skos-in-the-pipeline); [arXiv 2111.03910](https://arxiv.org/pdf/2111.03910) (search summary; I could not attribute each item to one of these two sources).
- **Scheme versioning** is a recognised research problem in knowledge organization — [Tennis, "Scheme Versioning in the Semantic Web" (reprinted 2013)](https://doi.org/10.4324/9780203052051-10) (bibliographic record only; not read).

### Inferences
- **Turn SKOS integrity conditions into tests** (`tests/test_invariants.py`):
  - S13: a label string must not be both pref and alt/hidden in the same language.
  - S14: at most one pref label per concept and language tag.
  - S27: no `related` pair that is also linked by any broader path.
  - S46: no `exactMatch` alongside `broadMatch`/`relatedMatch` to the same target.
  - §6.5.3: notations unique within a scheme.
  - §10.6.1: mapping relations only between different schemes.
- **Label model changes:**
  - Add a `hidden` label kind. It keeps misspellings and superseded or offensive historical terms findable without displaying them.
  - Move labels toward SKOS-XL semantics: a label row gets an id and records source, authority (which community or institution uses it), date, status and inter-label relations (endonym/exonym, acronym, former name).
  - The existing `desc` kind is a Wikidata-style disambiguating description. Export it as `skos:definition` only where it really defines the concept; otherwise use a generic note.
- **Add a `note` table** with columns `concept_id, kind ∈ {definition, scope, history, change, editorial, example}, lang, text, author, date, source`. Every edit to a label, placement or scope note then writes a `changeNote`, and deprecations write a `historyNote`.
- **Model the 13-domain circle as an unordered `skos:Collection`** and/or as `skos:hasTopConcept` of the `acat` scheme, not as a hierarchy. An unordered collection formally encodes "no ranking."
  - Use `skos:OrderedCollection` only where order carries meaning, such as dated spans.
  - Sibling arrays that are only node labels (e.g., "by tradition") should be Collections, which SKOS keeps out of the broader/narrower graph (S37).
- **Deprecation workflow:** set `status=deprecated` and `replaced_by`, add a `historyNote`, export `owl:deprecated true` and `dct:isReplacedBy`, and bump the scheme version (`owl:versionInfo`, `dct:modified`). acatalogue's never-delete trigger already matches this practice.
- **Mapping hygiene:**
  - Because `exactMatch` is transitive and symmetric, chains across Wikidata, UDC, DDC and LCC can spread one error. Default to `closeMatch` unless the scope notes match.
  - Run S46 conflict checks in `acat audit`.

### Gaps
- The SKOS Primer and ISO 25964 were not consulted this session.
- Tennis's paper on scheme versioning was identified but not read.
- No standard SKOS vocabulary for label provenance beyond SKOS-XL plus generic Dublin Core/PROV was verified.

---

## 3. Critiques of universal classification (Olson, Bowker & Star, Berman; documented DDC/LCC/LCSH biases and revisions) and the design principles that follow

### Takeaway
The critiques agree on the problems:
- Universal schemes encode a default viewpoint: Christian, Western, dominant-group norms are left unmarked.
- They marginalize through residual or "other" placements and outdated terms.
- They change slowly, and they can change quickly under political direction.

The remedies proposed fall into three groups:
- **Structural:** distributed residuals, equal ranking, faceted structure.
- **Procedural:** transparent, contestable, versioned change with comment periods and a record of who classified what.
- **Epistemic:** make the scheme's constructedness visible, and accept that correction is never final.

These support acatalogue's stance that bias can be exposed, measured and made plural, but not eliminated.

### Cited Findings
**Olson**
- Olson (1998), "Mapping Beyond Dewey's Boundaries: Constructing Classificatory Space for Marginalized Knowledge Domains," *Library Trends* 47(2): 233–254 — [ERIC EJ584212](https://eric.ed.gov/?id=EJ584212):
  - The article develops "spatial imagery as a metaphorical mechanism with the ability to discover the processes by which powerful and privileged discourses shape information and with the potential to inform change," within a DDC project.
  - It uses Gillian Rose's "paradoxical spaces," which are "simultaneously or alternately in the center and at the margin, same and other" — [Semantic Scholar](https://www.semanticscholar.org/paper/Mapping-Beyond-Dewey's-Boundaries:-Constructing-for-Olson/2b79858ee0786feb7cfdb15b324e35e89b15fa38) (search summary).
- Olson (2001), "The Power to Name: Representation in Library Catalogs," *Signs* 26(3): 639–668 — [doi:10.1086/495624](https://doi.org/10.1086/495624) (bibliographic record verified; text not read).
- Olson & Schlegl (2001), "Standardization, Objectivity, and User Focus: A Meta-Analysis of Subject Access Critiques," *CCQ* 32(2): 61–80 — [doi:10.1300/j104v32n02_06](https://doi.org/10.1300/j104v32n02_06) (record verified; not read).

**Bowker & Star, *Sorting Things Out* (MIT Press, 1999)** — [PDF (hcommons)](https://hcommons.org/app/uploads/sites/1001532/2020/03/Bowker-1999-Sorting-Things-Out-Classification-and-Its-Consequences.pdf); page numbers are print pages inferred from running heads.
- Definition (p. 10): "A classification is a spatial, temporal, or spatio-temporal segmentation of the world." "In an abstract, ideal sense," a classification system has three properties:
  - "consistent, unique classificatory principles in operation";
  - "The categories are mutually exclusive";
  - it is complete.

  AcaWiki summarizes that it is difficult to find a system that meets these requirements — [AcaWiki summary](https://acawiki.org/Sorting_Things_Out:_Classification_and_Its_Consequences) (search summary).
- On the ICD (≈p. 25): "One of the simple but important rules of thumb to try to control for this degree of uncertainty is to distribute the residual categories. 'Not elsewhere classified' appears throughout the entire ICD, but nowhere as a top-level category … its effects will remain as local as possible."
- ≈p. 175: "So one can have an 'other' or residual category, but at some point even the garbage can will have to be ordered when it becomes large enough."
- pp. 300–301: "all things inhabit someone's residual category in some category system."
- Design exigencies (pp. 324–325):
  1. "**Recognizing the balancing act of classifying.** Classification schemes always represent multiple constituencies. They can do so most effectively through the incorporation of ambiguity—leaving certain terms open for multiple definitions across different social worlds: they are in this sense boundary objects."
  2. "**Rendering voice retrievable.** … By keeping the voices of classifiers and their constituents present, the system can retain maximum political flexibility," including the ability "to change with changing natural, organizational, and political imperatives."
  3. "**Being sensitive to exclusions.** … the distribution of residual categories (who gets to determine what is 'other'). Classification systems always have other categories, to which actants … who remain effectively invisible to the scheme are assigned."
- Star & Bowker (2007), "Enacting silence: Residual categories as a challenge for ethics, information systems, and communication," *Ethics and Information Technology* 9(4): 273–280 — [doi:10.1007/s10676-007-9141-7](https://doi.org/10.1007/s10676-007-9141-7) (record verified).

**Berman and LCSH**
- Berman's *Prejudices and Antipathies* (1971) listed 225 headings with proposed changes — [Knowlton 2005, CCQ 40(2), doi:10.1300/J104v40n02_08](https://www.sanfordberman.org/biblinks/knowlton.pdf).
- By 2005, per Knowlton — [Knowlton 2005](https://www.sanfordberman.org/biblinks/knowlton.pdf):
  - 88 (39%) had been changed "almost exactly as he suggested";
  - 54 (24%) had been changed in ways that partially reflect his suggestions;
  - "The 80 items that remain unchanged (some 36% of Berman's suggestions) show some patterns of thought that persist … for example, many subject headings pertaining to the Christian religion remain unglossed."

**LCSH "Illegal aliens"** — chronology from [Wikipedia: Illegal aliens (LCSH)](https://en.wikipedia.org/wiki/Illegal_aliens_(Library_of_Congress_Subject_Heading)), [LC 2016 decision](https://www.loc.gov/catdir/cpso/illegal-aliens-decision.pdf), [ALA news, Nov 2021](https://www.ala.org/news/2021/11/ala-welcomes-removal-offensive-illegal-aliens-subject-headings), [SUNY OLIS guide](https://sunyolis.libguides.com/c.php?g=986218&p=7623203) (search summary):
- 2014: Dartmouth students petitioned for a change.
- February 2015: LC declined.
- January 2016: ALA Council resolution.
- March 2016: LC announced replacement by "Noncitizens" and "Unauthorized immigration."
- June 2016: House appropriations language required LC to publicize its heading-change process.
- 2019: the documentary *Change the Subject*.
- 12 November 2021: LC announced replacement by "Noncitizens" and "Illegal immigration," covering related headings (e.g., "Women illegal aliens").
- By December 2021, OCLC had updated about 41,000 WorldCat records.
- ALA's president called the old headings "outdated and dehumanizing."
- A letter from Senator Cruz to LC dated 17 November 2021 concerning the heading is published at [cruz.senate.gov](https://www.cruz.senate.gov/download/20211117_--letter-to-loc-re-alien-subject-heading-and-search-classification1?download=1) (content not reviewed).

**2025–2026 politically directed LCSH changes**
- On 14 March 2025, LCSH changed Gulf of Mexico → Gulf of America and Denali → McKinley. LC stated it "defers to the United States Board on Geographic Names (BGN)" — [CCC Libraries DEIAA blog](https://ccclibraries.org/blogs/deiaa_workgroup/blog/library-of-congress-changes-gulf-of-mexico-and-mount-denali-subject-headings); [Classweb Tentative List 2412a](https://classweb.org/tentative-subjects/2412a.html).
- The process was compressed — [CCC Libraries blog](https://ccclibraries.org/blogs/deiaa_workgroup/blog/library-of-congress-changes-gulf-of-mexico-and-mount-denali-subject-headings); [Stephen's Lighthouse](https://stephenslighthouse.com/2025/02/18/and-this-is-what-it-can-look-like-has-anyone-ever-seen-a-single-day-notice-for-comments-from-loc-the-tentative-list-for-changes-to-the-library-of-congress-subject-headings-which-i-believe-was/); [ACRLog, 28 Mar 2025](https://acrlog.org/2025/03/28/anticipatory-obedience-at-the-library-of-congress/):
  - The special list was backdated to 13 February, with notice and comment deadline both on 18 February: under 24 hours to comment.
  - "The regular procedure for revisions to LCSH includes a three week comment period."
- ACRLog (12 September 2026) reports that after an 27 August 2026 executive order, LC proposed on 3 September changing "Ontario, Lake (N.Y. and Ont.)" to "America, Lake (N.Y. and Ont.)" and approved it on 11 September — [ACRLog, "Library of Congress: 'POTUS pawns'"](https://acrlog.org/2026/09/12/library-of-congress-potus-pawns/). This is a single-source search summary; I could not load the page text or verify it independently.

**DDC 200 Religion**
- OCLC acknowledges "Christian bias in the standard notational sequence for the Bible and specific religions" — [OCLC: 200 Religion Class](https://www.oclc.org/en/dewey/resources/religion.html):
  - It offers an optional chronological/regional arrangement for 220–290, prepared with Ia C. McIlwaine (former UDC editor-in-chief) and based on "a similar development introduced in the UDC in 2000."
  - The arrangement is published as Appendix A of the print *200 Religion Class*, as a Manual note in WebDewey, and through the Dewey Religion Browser.
- In the standard DDC 200s, 220–280 are Christian, and many other religions share 290; Hinduism, Jainism and Buddhism fall under 294 — [Video Librarian essay](https://videolibrarian.com/articles/essays/examining-the-problematic-roots-dewey-decimal-system/) (secondary source; search summary).

**Drabinski (2013)**
- "Queering the Catalog: Queer Theory and the Politics of Correction," *Library Quarterly* 83(2) — [doi:10.1086/669547](https://doi.org/10.1086/669547); [ERIC EJ1004129](https://eric.ed.gov/?id=EJ1004129) (search summary):
  - Classification and subject language cannot be finally "corrected."
  - Queer theory shifts responsibility toward teaching users to "dialogically engage the catalog as a complex and biased text."
  - Systems can be designed so that users see the constructedness of classification.

### Inferences
Design principles for acatalogue that follow:
1. **No unmarked default.**
   - Every tradition-specific concept is qualified the same way ("Christian theology," "Islamic jurisprudence," "Buddhist philosophy").
   - Generic concepts ("Theology," "Scripture," "Law") get scope notes that are genuinely cross-traditional.
   - Evidence: unglossed Christian headings (Knowlton) and DDC 200s asymmetry.
2. **Distribute residuals, and measure them.** The "no Other X" rule matches Bowker & Star's ICD rule of thumb. Residual categories cannot be abolished, only distributed and watched, so the audit should report residual rates: items that attach to no concept or only to a domain root.
3. **Render voice retrievable.**
   - Every placement, label and scope note records who authored or approved it (currently one AI agent), when, and why.
   - The interface shows alternative placements from UDC, DDC, LCC, Propaedia and Wikidata side by side, making the catalogue's own view one among several.
   - Evidence: Bowker & Star pp. 324–325; Drabinski.
4. **Let boundary objects stay open.** Where communities define a term differently (e.g., "religion," "philosophy," "science," "art"), allow several attributed scope notes rather than one arbitrated definition.
5. **Make change contestable and versioned.** Publish proposed changes as tentative lists with a comment window of at least three weeks (the LCSH norm). Record decisions, and never rename silently.
6. **Handle disputed names as plural labels with provenance.**
   - When a single authority renames something (2025–2026 LCSH episodes), keep all names as labels, each with the authority using it and a date.
   - Choose the display label by a published, neutral rule; do not defer to one government.
   - SKOS-XL label provenance makes this machine-readable.
7. **Correction is never final.** Keep the history visible (history notes, deprecated concepts), and treat the audit as ongoing rather than a certification of neutrality.

### Gaps
- The full texts of Olson (2001; 2002 book), the Olson & Schlegl meta-analysis and Berman (1971) were not read; claims about them are limited to verified abstracts and records.
- LCC-specific bias cases (e.g., the BL–BX religion span) were not verified this session.
- The 2026 "Lake America" report is unverified beyond one blog summary.
- Which DDC editions (21/22/23) made specific 200s changes was not confirmed from OCLC.

---

## 4. Indigenous and decolonizing knowledge organization: representing traditions in their own terms and giving communities authority

### Takeaway
The working models share four moves:
1. Self-names and community languages as preferred terms.
2. Community-derived structure: relationship- and land-based order, and geographic rather than alphabetical grouping of Nations.
3. Community governance of terms: hui/wānanga consultation, custodial authority.
4. Machine-actionable signals of authority, provenance and conditions of use: CARE; TK/BC Labels and Notices.

Each maps onto an implementable acatalogue feature: label provenance, alternative views, custodial reviewer authority, and protocol and provenance fields.

### Cited Findings
**Brian Deer Classification and the Xwi7xwa Library**
- Brian Deer, a Kahnawake Mohawk librarian, created the classification in the 1970s (1974) for the National Indian Brotherhood — [Xwi7xwa Library: Indigenous Knowledge Organization](https://xwi7xwa.library.ubc.ca/collections/indigenous-knowledge-organization/); [Wikipedia: Brian Deer Classification System](https://en.wikipedia.org/wiki/Brian_Deer_Classification_System) (search summary).
- X̱wi7x̱wa (UBC) uses a British Columbia variant developed by founding librarian Gene Joseph (Wet'suwet'en – Nadleh Whut'en) — [Xwi7xwa Library](https://xwi7xwa.library.ubc.ca/collections/indigenous-knowledge-organization/). The library also:
  - uses First Nations House of Learning (FNHL) subject headings, which "follow a standard order of [topic]–[subtopic]–[place]–[chronology]";
  - uses LCSH alongside them;
  - maintains a "Names for BC First Nations in BC" list that will "continue to be expanded and revised to best reflect the preferences of First Nations."
- The structure prioritizes relationships "between and among people, animals, and the land." It groups First Nations geographically rather than alphabetically — [UBC Research Guide: Brian Deer Classification](https://guides.library.ubc.ca/Indiglibrarianship/briandeer) (search summary).
- Using a Nation's preferred name as the subject heading is described as a way of saying "these are our names and these our people" — [YES! Magazine (2019)](https://www.yesmagazine.org/social-justice/2019/03/22/decolonize-western-bias-indigenous-library-books) (search summary).
- Doyle, Lawson & Dupont (2015), "Indigenization of Knowledge Organization at the Xwi7xwa Library," *Journal of Library and Information Studies* 13(2) — [doi:10.6182/jlis.2015.13(2).107](https://doi.org/10.6182/jlis.2015.13(2).107) (DOI resolves; not read).

**Ngā Upoko Tukutuku / Māori Subject Headings (MSH)**
- Sponsors: the National Library of New Zealand, LIANZA and Te Rōpū Whakahau — [Te Rōpū Whakahau: Ngā Ūpoko Tukutuku](https://trw.org.nz/professional-development/nga-upoko-tukutuku-maori-subject-headings/).
- Timeline — [Te Rōpū Whakahau](https://trw.org.nz/professional-development/nga-upoko-tukutuku-maori-subject-headings/):
  - 1998: working party formed.
  - June–August 2004: hui wānanga consultation.
  - October 2004: iwi–hapū names list, "based on the names of waka, iwi and hapū."
  - April 2005: project team announced.
  - September 2005: initial headings launched at the LIANZA conference.
- Size: "over 1,400 heading terms" with further additions. The team included te reo and tikanga consultants alongside cataloguing advisors — [Te Rōpū Whakahau](https://trw.org.nz/professional-development/nga-upoko-tukutuku-maori-subject-headings/).
- Other sources describe MSH as launched in 2006, as "the first indigenous thesaurus in the world," and as having "more than 2000 terms." It provides subject access in te reo Māori and "a structured path to a Māori world view" — [LIANZA paper "Te Wero i te Ūpoko Tukutuku"](https://lianza.org.nz/wp-content/uploads/2020/01/TaalaT_Maori_subject_headings.pdf); [Otago guide](https://otago.libguides.com/nga_upoko_tukutuku) (search summary; the launch date and term count conflict with the TRW page).
- Lilley (2015), "Ka Pō, Ka Ao, Ka Awatea: The Interface between Epistemology and Māori Subject Headings," *CCQ* 53(5–6): 479–495 — [doi:10.1080/01639374.2015.1009671](https://doi.org/10.1080/01639374.2015.1009671) (record verified).

**Mashantucket Pequot Thesaurus of American Indian Terminology**
- Launched in 1995 under Cheryl A. Metoyer to bring an Indigenous perspective into mainstream controlled vocabularies — [UCLA AISC project page](https://www.aisc.ucla.edu/research/mashantucket.aspx); [Littletree & Metoyer (2015), *CCQ* 53(5–6): 640–657, doi:10.1080/01639374.2015.1010113](https://doi.org/10.1080/01639374.2015.1010113) (search summary).
- It is designed to be user-centred, reflecting "the information-seeking behavior of Native and non-Native scholars and researchers" — [Littletree & Metoyer (2015), Semantic Scholar record](https://www.semanticscholar.org/paper/Knowledge-Organization-from-an-Indigenous-The-of-Littletree-Metoyer/dd44244cea4c275513a5eaa81e46b82a5cfab31f) (search summary).

**AIATSIS (Australia)**
- The Pathways thesauri (Topical and Place) "contain culturally appropriate terms" following ATSILIRN protocols. The US Library of Congress "has approved the Language, Place and Subject thesaurus for use worldwide in bibliographic records" — [AIATSIS: Pathways thesauri](https://aiatsis.gov.au/publication/35114) (search summary).
- AustLang is a thesaurus of headings and synonyms for Aboriginal and Torres Strait Islander language and people groups. It has pages for more than 1,200 languages, with names and spellings, speaker numbers and classifications. People-group headings are being migrated from Pathways to AustLang — [AIATSIS: AustLang](https://aiatsis.gov.au/research/languages/austlang) (search summary).

**CARE Principles for Indigenous Data Governance** (RDA International Indigenous Data Sovereignty Interest Group, September 2019; GIDA) — [CARE one-pagers (PDF)](https://www.gida-global.org/s/CAREPrinciples_OnePagersFINAL_Oct_17_2019.pdf); [Carroll et al. 2020, *Data Science Journal* 19, doi:10.5334/dsj-2020-043](https://doi.org/10.5334/dsj-2020-043)
- The principles are framed as a complement to FAIR. FAIR is said to focus on data sharing "while ignoring power differentials and historical contexts."
- **Collective Benefit:** C1 inclusive development and innovation; C2 improved governance and citizen engagement; C3 equitable outcomes.
- **Authority to Control:** "Indigenous data governance enables Indigenous Peoples and governing bodies to determine how Indigenous Peoples, as well as Indigenous lands, territories, resources, knowledges and geographical indicators, are represented and identified within data."
  - A1: rights and interests, including "free, prior, and informed consent."
  - A2: "data that are relevant to their world views."
  - A3: the "right to develop cultural governance protocols … and be active leaders in the stewardship of, and access to, Indigenous data."
- **Responsibility:**
  - R1: relationships of "respect, reciprocity, trust, and mutual understanding, as defined by the Indigenous Peoples."
  - R2: capability and capacity.
  - R3: "data grounded in the languages, worldviews, and lived experiences."
- **Ethics:**
  - E1: "Ethical data are data that do not stigmatize or portray Indigenous Peoples, cultures, or knowledges in terms of deficit."
  - E2: "Ethical processes must include representation from relevant Indigenous communities."
  - E3: "Metadata should acknowledge the provenance and purpose and any limitations or obligations in secondary use inclusive of issues of consent."

**Local Contexts: TK and BC Labels and Notices**
- TK Labels define attribution, access and use rights for Indigenous cultural heritage. BC Labels define community expectations about use of collections and data — [Local Contexts: Labels](https://localcontexts.org/labels/about-the-labels/); [DataCite: Local Contexts Notices and Labels](https://support.datacite.org/docs/local-contexts-notices-and-labels) (search summary).
- Labels come in three categories: Provenance (who holds primary cultural authority), Protocol (traditional access protocols) and Permission (approved uses) — [Local Contexts](https://localcontexts.org/labels/about-the-labels/) (search summary).
- Notices are applied by institutions or researchers and act as placeholders until a community applies a Label. Labels are generated and applied by Indigenous communities through the Local Contexts Hub — [DataCite docs](https://support.datacite.org/docs/local-contexts-notices-and-labels) (search summary).

### Inferences
- **Self-names as preferred labels, with recorded authority.**
  - For peoples, Nations, languages and traditions, store the self-name as the preferred label in the community's language. English or other exonyms become alt labels.
  - Each label records its authority, such as an MSH heading, an AustLang code, the FNHL names list, or a community statement.
  - Superseded or offensive exonyms can be kept as hidden labels with a history note, so old queries still find the concept but the term is never displayed (SKOS §5.1).
  - Evidence: FNHL names list; MSH iwi–hapū–waka names; AustLang; CARE A1–A2 and R3.
- **Custodial authority per concept (CARE A3, E2).**
  - Add a `custodian` field (community or body with cultural authority) and a `requires_custodian_approval` flag to concepts about specific peoples, sacred sites, ceremonies or traditional knowledge.
  - Until a custodian is engaged, show a Notice-style statement: "described externally (AI-authored, not community-reviewed); community review invited." This mirrors Local Contexts Notices, which institutions apply as placeholders.
- **Plural arrangements as separate views, not replacements.**
  - A community's own structure, such as a Brian Deer–style relationship and land-based view or FNHL's topic–subtopic–place–chronology order, can be a separate SKOS scheme or collection, crosswalked to the compendium with SKOS mapping relations.
  - Within Indigenous-peoples concepts, group Nations geographically (via M49 and finer place data), not alphabetically.
- **Protocol and use-obligation fields (CARE E3; TK Protocol Labels).**
  - Add fields recording provenance, purpose, and limitations or obligations on reuse.
  - Do not ingest restricted or sacred content; honour protocol labels if documents are added later.
- **Symmetry of epistemic status (CARE E1).** The status "held within a tradition" must be applied symmetrically. If Indigenous cosmologies are "held within a tradition," so are the doctrines of every other tradition. Section 6 gives the audit for this.
- **User and community warrant alongside literary warrant.** The Mashantucket Pequot Thesaurus was built on the information-seeking of Native and non-Native researchers, and MSH on hui wānanga consultation. Review of Belief, Language and Past concepts should include people from within the traditions described.

### Gaps
- The Brian Deer top-level class list and the 2018 X̱wi7x̱wa schedule PDF were not retrieved.
- MSH's current term count, launch year and licensing conflict across sources, and the natlib.govt.nz page did not render.
- The Mashantucket Pequot Thesaurus's current availability and maintenance status is unknown.
- AIATSIS licensing terms for reuse were not verified.
- Whether acatalogue can recruit community custodians is an organizational question outside the literature.

---

## 5. Measuring content bias in Wikipedia/Wikidata (gender, geography, language, topic, citation geography): metrics, baselines, dashboard status and pitfalls

### Takeaway
Standard practice measures two things per group: **selection** (how much content exists) and **extent** (how developed it is). Results are normalized against a baseline: population, speakers, area, or an "expected" level from covariates such as Internet access. They are summarized with ratios, Gini and normalized entropy.

As of 2026-09-25, the dedicated gender dashboards are stale or offline:
- Humaniki is up, but its latest snapshot is 2025-06-23.
- Denelezh and WHGI do not respond.

acatalogue should therefore compute its own metrics from dated Wikidata snapshots.

The main pitfalls are:
- the choice of denominator;
- incomplete or binary-coded gender data;
- ethnicity that cannot be measured;
- sitelink counts inflated by bots;
- a mismatch between language and place;
- notability gatekeeping, which makes "coverage" partly a measure of prior bias.

### Cited Findings
**Dashboard status (checked 2026-09-25)**
- Humaniki merged WHGI (Maximilian Klein) and Denelezh (Envel Le Hir). It reports gender by date of birth, country, occupation and project, using Wikidata P21, P27, P19, P569 and P106 — [MediaWiki: Humaniki](https://www.mediawiki.org/wiki/Humaniki), last edited 18 March 2023.
  - It computes statistics by downloading and parsing the full Wikidata dump, which takes about 3 days — [Humaniki FAQ](https://www.mediawiki.org/wiki/Humaniki/FAQ) (search summary).
  - The site describes its data as "updated daily."
- Humaniki's API lists 224 weekly snapshots, from 2020-12-21 to the latest, **2025-06-23** — [Humaniki API: available_snapshots](https://humaniki.wmcloud.org/api/v1/available_snapshots/). No snapshot is newer than June 2025, so the data are about 15 months stale.
- Humaniki's 2025-06-23 snapshot, computed from the [Humaniki gap API (≥1 sitelink)](https://humaniki.wmcloud.org/api/v1/gender/gap/latest/gte_one_sitelink/properties) and [Humaniki gap API (all Wikidata)](https://humaniki.wmcloud.org/api/v1/gender/gap/latest/all_wikidata/properties):

  | Population | Humans with a gender value | Female | Male | All other gender values |
  |---|---|---|---|---|
  | Humans with ≥1 Wikipedia/Wikimedia sitelink | 4,635,044 | 882,033 (**19.03%**) | 3,748,429 (80.87%) | ≈0.10% |
  | All Wikidata humans | 9,992,532 | 2,633,209 (**26.35%**) | 7,351,939 (73.57%) | ≈0.07% |

  The API also returns a bucket keyed "-1" (1,136 and 2,062 people), which the API does not explain; I included it in the totals.
- Denelezh: `denelezh.org` redirects to `denelezh.wmcloud.org`, which returns the Wikimedia Cloud error "This web service cannot be reached" — [denelezh.org](https://www.denelezh.org/) (checked 2026-09-25).
- WHGI: `whgi.wmflabs.org` returns HTTP 503 — [whgi.wmflabs.org](https://whgi.wmflabs.org/) (checked 2026-09-25).
- WikiProject Women in Red, citing Humaniki, reports women's share of English Wikipedia biographies:
  - 15.53% in October 2014;
  - **20.003%** on 16 December 2024.

  — [Wikipedia: WikiProject Women in Red](https://en.wikipedia.org/wiki/Wikipedia:WikiProject_Women_in_Red)
- The Wikipedia Gender Dashboard (WGD, 2025) is built in Power BI from Wikipedia APIs, DBpedia and Wikidata. It finds "female articles only represent around 17% of English Wikipedia" — [arXiv 2501.12610](https://arxiv.org/abs/2501.12610). Its maintenance status is unknown.
- WMF Knowledge Gaps Index — [Meta: Knowledge Gaps Index/Measurement](https://meta.wikimedia.org/wiki/Research:Knowledge_Gaps_Index/Measurement):
  - Content metrics are the **Selection-Score** ("number of articles for each category of the gap") and the **Extent-Score** ("quality of articles based on length, # sections, # images").
  - Proposed aggregations are max/min representation ratios, the Gini coefficient, normalized entropy and cumulative distributions over time.
  - As of July 2024, metrics existed for only 5 of 11 content gaps. Language, socio-economic status, cultural background and topics were still unmapped.
- The gap data sets use categories such as gender, `geography_wmf_region`, `geography_cultural_region`, `geography_continent` and `geography_country` — [Meta: Knowledge Gaps Index/Datasets](https://meta.wikimedia.org/wiki/Research:Knowledge_Gaps_Index/Datasets) (search summary).
- Redi et al.'s taxonomy of knowledge gaps (second draft) is based on more than 250 references. It classifies gaps in readership, contributorship and content, and serves as the basis for the Knowledge Gaps Index — [arXiv 2008.12314](https://arxiv.org/abs/2008.12314).

**Gender measurement: methods and pitfalls**
- WHGI research is published in Klein et al. (2016), OpenSym — [doi:10.1145/2957792.2957798](https://doi.org/10.1145/2957792.2957798) — and Konieczny & Klein (2018), *New Media & Society* 20(12): 4608–4633 — [doi:10.1177/1461444818779080](https://doi.org/10.1177/1461444818779080). It found that "gender disparities in biographies mirror 'traditional' gender-disparity indices (GDI, GEI, GGGI and SIGI)" — [MediaWiki: Humaniki](https://www.mediawiki.org/wiki/Humaniki).
- Wagner, Graells-Garrido, Garcia & Menczer (2016) study gender asymmetry along notability, topical focus, linguistic bias, structural properties and metadata presentation. They find women in Wikipedia "more notable than men," which they read as a glass-ceiling effect — [EPJ Data Science, doi:10.1140/epjds/s13688-016-0066-4](https://link.springer.com/article/10.1140/epjds/s13688-016-0066-4) (search summary).
- Tripodi (2021/2023) reports that English Wikipedia has "more than 1.5 million biographies … but less than 19% of these biographies are about women." Biographies of women who meet inclusion criteria "are more frequently considered non-notable and nominated for deletion" — [New Media & Society, doi:10.1177/14614448211023772](https://doi.org/10.1177/14614448211023772).
- Mandiberg (2023) finds that the share of biographies about people from Indigenous and non-dominant ethnic groups cannot be precisely measured, "because most articles lack ethnicity information." Whiteness is "unverifiable in Wikipedia's white epistemology" — [Social Text 41(1), doi:10.1215/01642472-10174954](https://doi.org/10.1215/01642472-10174954).

**Geographic coverage and source localness**
- Graham, Hogan, Straumann & Medhat (2014) — [pre-print PDF](https://ora.ox.ac.uk/objects/uuid:7d4449ab-59a9-468a-826e-e0dc7a7d3975/files/m3ececf4e6253825bb1a7d7e90a65abb8); [doi:10.1080/00045608.2014.910087](https://doi.org/10.1080/00045608.2014.910087):
  - Geotagged Wikipedia content shows "uneven and clustered geographies."
  - "The vast majority of differences between places can be explained by relatively simple factors relating to access to the Internet"; their model "explains a substantial 71 percent of variance."
  - Countries with "considerably fewer articles than predicted" tend to be in MENA.
  - "In the Middle East, we see only one country (Syria) with more articles in Arabic than any other language."
- Graham, Straumann & Hogan (2015) map geographic participation in Wikipedia editing — ["Digital Divisions of Labor and Informational Magnetism", doi:10.1080/00045608.2015.1072791](https://doi.org/10.1080/00045608.2015.1072791) (record verified).
- Sen et al. (CHI 2015) studied articles on geographic entities in 79 language editions — [PDF](https://brenthecht.com/publications/localnessgeography_CHI2015.pdf); [doi:10.1145/2702123.2702170](https://doi.org/10.1145/2702123.2702170):
  - Editors and cited sources are less local where socio-economic status and local media are weaker.
  - "If you read about a place in a language that is not commonly spoken in that place, you are unlikely to be reading locally-produced VGI or even VGI that references local sources."
  - "The degree of a country's source localness primarily reflects the strength of its scholarly media networks."
- Ford, Sen, Musicant & Miller (2013) analysed which kinds of sources Wikipedia cites and compared them with policy. They found wide use of primary and non-scholarly sources — [OpenSym 2013 PDF](https://opensym.org/wsos2013/proceedings/p0203-ford.pdf) (search summary).
- A 2026 study of more than 1.2 million policy documents from 185 countries found that most foreign evidence cited is produced in the Global North, "even in documents authored by governments in the Global South" — [Nature Human Behaviour (2026)](https://www.nature.com/articles/s41562-026-02464-x) (search summary). This is a design precedent for source-geography audits; it does not concern Wikipedia.

**Language and culture**
- Kaffee et al. (OpenSym 2017) compared Wikidata's label languages with the distribution of native speakers and found "an existing language maldistribution, which is less urgent in the ontology." "Only 11 languages hold almost 50% of all language knowledge in Wikidata" — [PDF](https://www.opensym.org/wp-content/uploads/2017/08/a14-kaffee.pdf); [ACM DL](https://dl.acm.org/doi/10.1145/3125433.3125465).
- Miquel-Ribé & Laniado (2018) studied 40 language editions. "Almost a quarter of each Wikipedia language edition (mean 23.2% …)" is about that language's own cultural context — [Frontiers in Physics, doi:10.3389/fphy.2018.00054](https://doi.org/10.3389/fphy.2018.00054).
- Lsjbot, Sverker Johansson's bot, created about 9.5 million articles by January 2019, two-thirds of them in Cebuano. It initially created nearly all Cebuano Wikipedia articles and most Waray articles, mostly on species and geographic places. Mass creation stopped in 2020 — [Wikipedia: Lsjbot](https://en.wikipedia.org/wiki/Lsjbot); [ABC News (2025)](https://www.abc.net.au/news/science/2025-04-15/wikipedia-cebuano-lsjbot-ai-article-generation-non-english/105123090) (search summary).

**Related dataset-audit precedent**
- Shankar et al. (2017) found "observable amerocentric and eurocentric representation bias" in two open image data sets. "China and India – the two most populous countries in the world – were represented with only 1% and 2% of the images" — [arXiv 1711.08536](https://arxiv.org/abs/1711.08536).

### Inferences
- **Baselines are choices, and should be declared and switchable.** Use several:
  - population share (UN World Population Prospects) for people-centred coverage;
  - area share for physical-geography coverage;
  - speaker share for languages;
  - an equal share (1/K) as a neutral reference;
  - an "expected given covariates" model, following Graham et al., to separate structural causes (Internet access) from editorial ones.
- **Denominators change headline numbers substantially.** Women's share is 19.03% among Wikidata humans with ≥1 sitelink but 26.35% among all Wikidata humans (Humaniki, 2025-06-23). It is 20.003% on English Wikipedia per Women in Red, and "around 17%" per WGD. Every figure acatalogue reports needs its population definition and snapshot date.
- **Coverage-based baselines inherit bias.** Tripodi shows gatekeeping at deletion; Wagner et al. show a higher notability bar for women. Treat Wikipedia/Wikidata distributions as a reference, never as a target.
- **Sitelink counts are inflated by bots.** Lsjbot mass-created Cebuano, Waray and Swedish articles on species and places. acatalogue's "N Wikipedias" figure should also be reported with bot-heavy editions excluded (at least `cebwiki`, `warwiki`, and ideally `svwiki` for species and geography items). Alongside the count, report the diversity of editions, such as the number of distinct language regions.
- **Language editions encode local perspectives.** About 23% of each edition is its own cultural context (Miquel-Ribé & Laniado), and place content in non-local languages is non-local (Sen et al.). So the English intros corpus is one perspective among several. The audit should report what share of acatalogue's text evidence comes from English.
- **Some dimensions cannot be measured honestly.** Ethnicity cannot be measured reliably from Wikidata (Mandiberg). acatalogue should state such dimensions as unmeasurable rather than publish misleading numbers.

### Gaps
- The Knowledge Gaps Index dashboards and API were not verified for 2026.
- No verified per-capita or per-area geotagged-article figures by country or region for 2024–2026 were found. Graham 2014 is older and its data predate 2014.
- There is no verified Wikipedia-specific quantitative citation-geography figure; Sen et al.'s findings on source localness are qualitative in these notes.
- Hecht & Gergle (2010) and Callahan & Herring (2011) on cross-language coverage were identified ([doi:10.1145/1753326.1753370](https://doi.org/10.1145/1753326.1753370); [doi:10.1002/asi.21577](https://doi.org/10.1002/asi.21577)) but not read.
- Meta-Wiki "articles per speaker" tables were not consulted.

---

## 6. Practical bias-audit designs (representation ratios, coverage-vs-population indices, divergence measures, uncertainty) and prioritized recommendations for acatalogue

### Takeaway
A defensible audit reports five things for each dimension:
1. the catalogue's distribution **P** over groups;
2. one or more declared baselines **Q**;
3. representation ratios with Wilson intervals;
4. a bounded divergence (Jensen–Shannon, in bits) with bootstrap intervals and a sampling-noise reference;
5. a diversity or inequality summary (normalized entropy, Gini, max/min).

It should say plainly that baselines are choices, and that a single composite "bias score" would hide more than it shows.

### Cited Findings
- **Aggregations:** the WMF Knowledge Gaps Index proposes max/min representation ratios, Gini, normalized entropy and cumulative distributions over time — [Meta: KGI/Measurement](https://meta.wikimedia.org/wiki/Research:Knowledge_Gaps_Index/Measurement).
- **Divergence:**
  - Lin (1991), "Divergence measures based on the Shannon entropy," introduced the Jensen–Shannon family. Unlike Kullback–Leibler divergence, it does not require absolute continuity and it is bounded — [IEEE Trans. Inf. Theory 37(1): 145–151, doi:10.1109/18.61115](https://doi.org/10.1109/18.61115).
  - Endres & Schindelin (2003), "A new metric for probability distributions," show that the square root of JSD is a metric — [IEEE Trans. Inf. Theory, doi:10.1109/TIT.2003.813506](https://doi.org/10.1109/TIT.2003.813506).
- **Proportion intervals:**
  - Wilson (1927) introduced the score interval — [JASA 22(158): 209–212, doi:10.1080/01621459.1927.10502953](https://doi.org/10.1080/01621459.1927.10502953).
  - Agresti & Coull (1998), "Approximate is better than 'exact' for interval estimation of binomial proportions" — [doi:10.1080/00031305.1998.10480550](https://doi.org/10.1080/00031305.1998.10480550).
- **Resampling:** Efron (1979) introduced the bootstrap — [Annals of Statistics 7(1), doi:10.1214/aos/1176344552](https://doi.org/10.1214/aos/1176344552).
- **Small-sample bias:** plug-in (maximum-likelihood) entropy estimates are biased in small samples, so divergences at acatalogue's scale (n ≈ 600) must be read against their sampling distribution — [Paninski (2003), Neural Computation 15(6): 1191–1253, doi:10.1162/089976603321780272](https://doi.org/10.1162/089976603321780272).
- **Ranking and search audits:**
  - Fairness in rankings can be framed as the exposure allocated to groups — [Singh & Joachims (2018), "Fairness of Exposure in Rankings," KDD, doi:10.1145/3219819.3220088](https://doi.org/10.1145/3219819.3220088).
  - Search-result representation audits compare the groups shown in results — [Kay, Matuszek & Munson (2015), "Unequal Representation and Gender Stereotypes in Image Search Results for Occupations," CHI, doi:10.1145/2702123.2702520](https://doi.org/10.1145/2702123.2702520).
- **Precedents for "share vs population":** image data sets (China and India at 1% and 2% of images) — [Shankar et al. 2017](https://arxiv.org/abs/1711.08536); geotagged Wikipedia articles modelled on population and connectivity — [Graham et al. 2014](https://ora.ox.ac.uk/objects/uuid:7d4449ab-59a9-468a-826e-e0dc7a7d3975/files/m3ececf4e6253825bb1a7d7e90a65abb8).
- **What acatalogue's audit does today:** counts per M49 region, sitelink medians and minima per domain, label languages, unmatched concepts and Wikidata hierarchy agreement. It computes no baselines, intervals or divergences — [acatalogue/views.py](../../acatalogue/views.py).

### Inferences

**Metric definitions** (implementable in Python over SQLite)
- **Notation:**
  - C = active `acat` concepts.
  - T(c) = set of UN M49 groups tagged on concept c (directly or via a place inside the group).
  - K = number of groups at the chosen level: 5 regions, or about 22 sub-regions.
- **Fractional regional share:**
  - Weight: w(c,r) = 1/|T(c)| if r ∈ T(c), else 0.
  - Share: s_r = Σ_c w(c,r) / N_loc, where N_loc = |{c : T(c) ≠ ∅}|.
  - Report untagged (global or unlocated) concepts separately. Fractional counting stops multi-region concepts from being counted twice.
- **Representation ratio:**
  - RR_r = s_r / b_r, displayed as log2 RR_r: 0 = parity, +1 = double, −1 = half.
  - Baselines b_r: population share (UN WPP), area share, equal share (1/K), or Wikidata's own geolocated-item share. The last is a reference, not a target.
- **Wilson 95% interval for s_r** (z = 1.96, n = N_loc, p = s_r):
  - centre = (p + z²/2n) / (1 + z²/n)
  - half-width = z·√(p(1−p)/n + z²/4n²) / (1 + z²/n)
  - Divide both bounds by b_r to get the interval for RR_r. With fractional counts, n is approximate; say so in the output.
- **Jensen–Shannon divergence (bits):**
  - JSD(P‖Q) = ½ Σ_r P_r log2(P_r/M_r) + ½ Σ_r Q_r log2(Q_r/M_r), where M = ½(P + Q). Its range is [0, 1].
  - Report √JSD as a distance.
  - Uncertainty: bootstrap by resampling concepts with replacement, B = 2000, percentile 95% interval.
  - Null reference: draw N_loc labels from Multinomial(Q) B times and compute JSD each time. Report whether the observed JSD exceeds the null's 95th percentile.
- **Normalized entropy:** H(P)/log2 K (1 = perfectly even).
- **Gini** over the K shares or ratios: G = Σ_i Σ_j |x_i − x_j| / (2K²·mean(x)). Also report the max/min ratio.
- **Sibling-parity index** for "equal siblings":
  - For each sibling set S (children of one parent, e.g. religious traditions, language families, regional histories), compute per sibling i:
    - subtree size n_i = 1 + number of descendants;
    - scope-note length;
    - number of alt labels;
    - number of accepted external mappings;
    - label-language count.
  - Report CV_S = sd/mean and max/min for each quantity, and flag outliers. This detects the DDC-200s pattern (one sibling with far more subdivisions) that the "no Other" rule cannot detect.
- **Attention without bot inflation:**
  - A_c = sitelinks excluding `cebwiki` and `warwiki` (and `svwiki` for species and geography items).
  - Language-region diversity D_c = Shannon entropy of c's sitelinked editions, grouped by each language's primary UN M49 region.
  - Keep the existing caveat: "attention, not importance."
- **Label language vs speakers:**
  - cov_L = |{c : pref label in L}| / |C|.
  - Speaker share q_L from Wikidata P1098 (number of speakers), stating L1 or L1+L2 and the snapshot date.
  - Compare JSD(cov_L normalized ‖ q_L) and list the largest shortfalls (Kaffee et al. method).
- **Epistemic-status symmetry:**
  - For each group g (region, tradition), compute P(status | g) and JSD(P(status|g) ‖ P(status)).
  - Flag groups where "held within a tradition," "fiction," "superseded" or "refuted" is over-represented (CARE E1; Knowlton's unmarked-default finding).
- **Residual rate** per domain: the share of documents or entities linked to no concept or only to a depth-0 domain (Bowker & Star, "distribute the residual categories").
- **Review coverage:**
  - share of concepts with ≥1 human approval;
  - share with ≥2 approvals from reviewers of different declared perspective or region, required for Belief, Past, Society and Language;
  - median age of unreviewed AI-authored text.
- **Search exposure** (once search or browse ranking matters):
  - For a fixed panel of neutral queries, exposure_g = Σ over top-k results in group g of 1/log2(1 + rank).
  - Compare each group's exposure share with its catalogue base rate (Singh & Joachims framing). The DCG-style discount is a design choice.
- **Persons (future) — gender:**
  - Female share among person entities with P21, with a Wilson interval.
  - Reference values: 50% parity, Humaniki 19.03% (≥1 sitelink, 2025-06-23) and 26.35% (all humans).
  - Cross by region and period. Do not publish ethnicity metrics (Mandiberg).

**Prioritized recommendations** (P1 = do first; each item lists its evidence)
- **P1 — Baseline-aware regional audit.** Add representation ratios, Wilson intervals, JSD with bootstrap and null reference, normalized entropy and Gini for UN M49 regions and sub-regions. Use population (UN WPP), equal-share and area baselines.
  - Implementation:
    - `seed/baselines/wpp-population-m49.tsv` (group, year, value, source URL) and `seed/baselines/area-m49.tsv`, loaded as sources with SHA-512 in the existing ledger.
    - New tables `baseline(dimension, group_id, value, unit, as_of, source_sha512)` and `audit_metric(run_id, dimension, group_id, metric, value, lo, hi, baseline)`.
    - `acat audit --baseline population|equal|area`.
  - Evidence: KGI aggregations; Lin 1991; Wilson 1927; Efron 1979; Paninski 2003; Graham et al. 2014.
  - Data sources: [UN M49](https://unstats.un.org/unsd/methodology/m49/); [UN World Population Prospects](https://population.un.org/wpp/).
- **P1 — Sibling-parity audit** of every "equal siblings" array (traditions, language families, regional histories, world-history spans). Output a flagged list for human review.
  - Evidence: DDC 200s bias acknowledged by OCLC; UDC 2000 equal-ranking revision; Knowlton's unglossed Christian headings.
- **P1 — Human review ledger and change process.**
  - `seed/reviews/*.tsv` with columns `target (concept/label/note/mapping), reviewer, declared_perspective, date, decision ∈ {approve, revise, object}, rationale`.
  - `seed/proposals/*.tsv` with opening and closing dates, using a comment window of at least 3 weeks.
  - Every accepted change writes a SKOS changeNote or historyNote.
  - Priority order for review: Belief → Past → Society → Language → the rest.
  - Evidence: Bowker & Star, "rendering voice retrievable"; the three-week LCSH norm and the 2025 shortcut; Drabinski.
- **P1 — SKOS contract tests and model upgrades.**
  - Tests for S13, S14, S27 and S46, unique notations, and cross-scheme-only mappings.
  - Add the `hidden` label kind, a `note` table, and label provenance (SKOS-XL semantics).
  - Export `owl:deprecated`, `dct:isReplacedBy` and `owl:versionInfo`.
  - Evidence: W3C SKOS Reference; Skosmos practice.
- **P2 — Sitelinks corrected for bot inflation, plus language-region diversity per concept.**
  - Evidence: Lsjbot; Miquel-Ribé & Laniado; Sen et al.
- **P2 — Label-language coverage vs speaker share,** using Wikidata P1098 with the snapshot recorded.
  - Evidence: Kaffee et al. 2017.
- **P2 — Terminology watchlist.**
  - A TSV lexicon of terms flagged in the literature. Each entry cites its source; for example, "illegal aliens," replaced by LCSH in 2021.
  - Scan labels and scope notes and route hits to the review queue; never edit automatically.
  - Evidence: Berman/Knowlton; LCSH 2021.
- **P2 — Epistemic-status symmetry cross-tab** by region and tradition.
  - Evidence: CARE E1; Knowlton.
- **P2 — Plural view and disputed names.**
  - Show alternative placements (UDC, DDC, LCC, Propaedia, Wikidata) and "why is this here" provenance on every concept page.
  - Store disputed names as multiple labels, each tagged with the authority that uses it.
  - Evidence: Bowker & Star; Drabinski; 2025–2026 LCSH renamings.
- **P2 — Residual-rate monitor** per domain.
  - Evidence: Bowker & Star on ICD residuals.
- **P3 — Custodial authority and Indigenous-data protocol fields.**
  - Add `custodian`, `requires_custodian_approval` and a use-obligations field.
  - Apply institution-style Notices until community Labels exist.
  - Crosswalk to MSH, AustLang and FNHL names where licences allow.
  - Evidence: CARE A1–A3 and E3; Local Contexts; MSH, AIATSIS and X̱wi7x̱wa practice.
- **P3 — Facet additions and composite notation.**
  - Add a language facet, and a form/genre facet for documents.
  - Treat a people/community facet as custodian-governed only.
  - Declare the display citation order (concept → kind → where → when → status) with inverted filing, and use self-delimiting facet indicators.
  - Evidence: CC editions 4–7; UDC tables 1c/1d/1e/1f/1g; FAST; BC2 inversion.
- **P3 — Person and search audits** once person entities or ranking exist: gender with intervals against declared references, intersections by region and period, and exposure-based search audits.
  - Evidence: Humaniki; Wagner et al.; Tripodi; Singh & Joachims; Kay et al.

**Presentation rules**
- Every metric shows its snapshot date, population definition, baseline and interval.
- Show several baselines side by side. Never merge metrics into a single "bias score."
- Carry the existing plain-language caveats forward ("attention, not importance"; "not stated is not disagrees").
- Mark dimensions that cannot be measured honestly (ethnicity) as such.

### Gaps
- No peer-reviewed standard prescribes which baseline to use for a *topical* concept scheme; the choice of population, area or equal share remains a normative decision acatalogue must document.
- Wilson intervals with fractional counts are approximate; I found no source prescribing intervals for fractional multi-label shares.
- UN WPP and M49 files, and Wikidata P1098 speaker counts, were not fetched this session, so their exact formats and current releases are unverified. Speaker counts are known to vary by source; the L1 vs L2 choice must be stated.
- I found no literature on search-exposure audits specifically for knowledge-organization browsing interfaces.
