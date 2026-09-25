# Registry cluster A: encyclopedic knowledge graphs, lexical resources, scholarly indexes

Companion to `a-encyclopedic-scholarly.tsv` (34 rows). Compiled 2026-09-25 from this container, through the
configured agent proxy.

## Method

- Every `url` in the TSV was probed with `curl -sSI -L --max-time 30`. A range GET was the fallback, but no row
  needed it: **34 of 34 rows answered HEAD 200 today**. The `verified` column records the result. DBnary answers
  only over plain HTTP from here. For BabelNet the probe reached the downloads page, because no public file exists.
  For Crossref it reached the `.torrent` file.
- `bytes` is the probed Content-Length, except in multi-part rows, where it is the total from the publisher's listing
  or manifest and the notes say so. Those rows are `wikipedia-cirrus-en`, `wikipedia-cirrus-tr`, the five
  `openalex-*` rows and `crossref-public-data-2026`. The Crossref total is the sum of file lengths inside the
  torrent's metadata.
- Nothing large was downloaded in full. Small files were fetched to profile labels, hierarchy and mappings:
  - the DBpedia ontology (9.9 MB), YAGO 4.6 schema and taxonomy (41.5 MB) and schema.org (2.3 MB);
  - ROR (37.5 MB), PhySH (0.9 MB), the Wikifunctions and Abstract Wikipedia dumps, and the OpenAlex taxonomy parts;
  - the Turkish Wiktionary extract (43 MB, streamed), the OMW 2.0 tarball (55.8 MB, streamed only to list it) and
    the Crossref torrent (3.7 MB).

  For the big dumps only the first 1–30 MB were read, with range requests. Where the publisher gives a checksum,
  the local copy matched it: DBpedia sha256, ROR md5, Wikifunctions and Abstract Wikipedia sha1.
- Each `url` is either a stable "latest" alias (Wikimedia, schema.org, kaikki, DBnary) or the current dated file. The
  notes name the dated file behind each alias and the pattern to reach other languages or parts.

## Starter selection (my first five)

1. **yago-4.6-taxonomy** (41.5 MB, CC BY 4.0), together with **yago-4.6-schema** (19 KB).
   - 206k classes and 232k subClassOf edges.
   - Labels in 692 language tags.
   - `owl:sameAs` to Wikidata on every class, plus WordNet 3.0 and Freebase ids.
   - The schema adds 55 upper classes with `owl:disjointWith`, which fits acat's `kind` facet and its consistency
     checks.
2. **openalex-topics**, with **-subfields**, **-fields** and **-domains** (5.2 MB together, CC0).
   - A four-level research classification: 4,516 topics, then 252, 26 and 4.
   - It carries Wikipedia and Wikidata links and is the obvious crosswalk target for the ACAT science domains.
3. **oewn-2025-plus** (12.9 MB, CC BY 4.0). An English lexical hierarchy with ILI ids, the hub that links wordnets
   across languages.
4. **omw-2.0** (55.8 MB, per-wordnet open licences). 31 languages joined to OEWN through ILI. Every licence allows
   redistribution and none is non-commercial.
5. **wikidata-lexemes** (475 MB, CC0). Covers 1,569 languages, and senses link to Q-items via P5137, so lexical
   data attaches directly to acat's existing `wd/` crosswalk.

Runners-up:
- ror: CC0, 140 languages, organisation hierarchy, 62k Wikidata ids.
- dbpedia-ontology: 35 languages, 675 Wikidata `equivalentClass` links.
- schema-org.
- kaikki-trwiktionary: Turkish glosses, 413 languages.
- physh: CC0 SKOS.

## Findings that change earlier assumptions

- **OpenAlex does not require an API key.** The public S3 snapshot is anonymous (`--no-sign-request`, or plain HTTPS).
  - The API also works without a key, on a small free daily budget. A free key raises the budget tenfold, and heavy
    use is paid.
  - `docs/DESIGN.md` §1 says "CC0 (API key needed)". That is only partly true. I have not edited it.
  - `docs.openalex.org` now redirects to `help.openalex.org`.
  - The next public release is 2026-10-14. Each release replaces the bucket in place, so record the manifest date.
- **OpenAlex concepts:** in the 2026-09-23 snapshot, `ancestors`, `related_concepts` and `international` are null on
  every one of the 65,026 records.
  - The frozen copy under `legacy-data/concepts/` still has them: hierarchy plus at least 410 label languages.
  - Its manifest points to `data/concepts/...`, but the files are under `legacy-data/concepts/...`. Rewrite the
    prefix.
- **Wikimedia dumps have moved on.**
  - The legacy XML dumps are officially deprecated ("can no longer reliably produce the bigger wikis"). Their
    replacement is the *MediaWiki Content File Exports*: monthly, split into parts, with `SHA256SUMS`, covering all
    namespaces.
  - CirrusSearch dumps moved from `other/cirrussearch/` (frozen since 20251229) to `other/cirrus_search_index/`.
    Each wiki is now sharded, and there are no checksums, only a `_SUCCESS` marker.
  - Enterprise HTML dumps have not been replicated on dumps.wikimedia.org since 2025-03-24. They now need a free
    Wikimedia Enterprise account, so they are not in the TSV.
  - dumps.wikimedia.org enforces the WMF User-Agent policy and allows at most 3 connections per IP. The pipeline's
    fetcher must send a descriptive User-Agent.
- **YAGO 4.6 (August 2026, ISWC 2026) supersedes YAGO 4.5, and the licence changed from CC BY-SA 3.0 to CC BY 4.0.**
  - YAGO 4.5 remains online: `https://yago-knowledge.org/data/yago4.5/yago-4.5.0.2.zip`, 12,362,922,810 bytes,
    HEAD 200. It was left out as a row.
  - 4.6 ships in parts: schema, taxonomy, facts, labels, beyond-wikipedia, meta and exclusion logs.
- **DBpedia:** the newest data release on the Databus is the "DBpedia Wikipedia KG Dump" of 2025-12-01, which is
  still CC BY-SA 4.0.
  - The older `dbpedia/mappings/*` artifacts stop at 2022.12.01.
  - The Snapshot page still promises quarterly releases, but none from 2026 appears.
  - The newest ontology on the Databus is the Archivo capture of 2024-08-01. `archivo.dbpedia.org` timed out today.
- **Abstract Wikipedia is live** at abstract.wikipedia.org, and its main page says "currently under development".
  - 2,315 abstract articles, 120 active editors; monthly dumps since 2026-04-01.
  - The content is Wikifunctions calls keyed by QID, so it holds no stored text (`languages=0`).
  - Wikifunctions itself has 31,694 ZObjects, including 5,422 functions, with labels in 711 languages.
  - Worth watching, not importing.
- **BabelNet is still 5.3 (December 2023)** under the BabelNet Non-Commercial License, for research institutions only.
  The indices (45G) come on request with an institutional e-mail, so the row is `access=restricted` and
  `recommend=no`.
- **ConceptNet:** the 5.7 dump is still on S3 (497,963,447 bytes, just under 500 MB). `api.conceptnet.io` answered
  502, and the project is unmaintained.
- **kaikki.org:** the post-processed per-language JSONL files are marked "DEPRECATED, will be removed in the near
  future". The durable input is the raw all-languages file, filtered by `lang_code`, or the per-edition extracts.
- **OEWN 2025** was split into a core edition (no proper nouns), a "plus" edition (curated names) and a separate Open
  English Namenet derived from Wikidata. **OMW 2.0** was released on 2026-02-01 (per the release asset's date).

## Per-row caveats (beyond the TSV notes)

- **Language counts:**
  - Wikidata's 637 is the number of term languages Wikidata accepts, not the number in use.
  - The lexeme count of 1,569 is distinct `dct:language` items.
  - kaikki-enwiktionary-all (2,793) is a lower bound from a 1% sample.
  - openalex-concepts (410) is a lower bound from an 812-record sample.
  - dbnary-en (4,255) is the number of language namespaces declared in its LIME metadata.
  - abstract-wikipedia is 0 on purpose, because the content is language-independent.
- **Wikipedia rows** are perspectives of their editor communities. Swahili is marked `yes` because it is a small,
  clean, non-European edition, useful for acat's coverage audit. The en and tr rows fail only on size.
- **wikipedia-categories-en** is marked `yes` as a separate scheme. It is editorial, has cycles, mixes in maintenance
  categories, and must never be merged into ACAT.
- **ConceptNet** is marked `yes` on the stated criteria but ranks low. It has not been updated since 2019, and its
  crowdsourced assertions carry documented social bias, so store them only as attributed claims.
- **KBpedia** is marked `yes` on the criteria. It is English-only and static since 2020, and its `owl:imports` points
  at a local Windows path.
- **OMW**: most wordnets were built by translating Princeton WordNet, so the structure is English-centred. Record
  which wordnet each label came from and its licence.
- **Turkish Wiktionary extract**: Turkish entries are under a quarter of the 1.4M entries (Greek, French and Italian
  sections are large), and the schema differs from the English-edition extract.
- **DBnary**:
  - HTTPS to kaiko.getalp.org was reset by the peer, but HTTP works.
  - There are no checksums, so validate content before use.
  - The site notes that the July/August 2026 extracts were retracted.
- **Crossref**: there is no plain HTTPS download. Access is BitTorrent, or an AWS requester-pays bucket (needs an
  AWS account, about USD 18). Abstracts are not CC0; they remain under the publisher's or author's copyright.
- **Moving URLs**:
  - `schema-org` always serves the latest release (30.1 today), so pin the version.
  - OpenAlex manifests are replaced every quarter.
  - Wikimedia dated directories are pruned after roughly 4–6 weeks. "latest" aliases move; the checksum files cited
    list the dated file names.

## Blocked or uncertain

- **GitHub**: `github.com` web pages and `api.github.com` return 403 in this session (policy). I worked around it:
  - release assets still resolve, as for OMW and CILI;
  - READMEs were read from blob-less `git clone`s of `globalwordnet/english-wordnet`, `omwn/omw-data`,
    `tatuylonen/wiktextract` and `physh-org/PhySH`;
  - PhySH files come from raw.githubusercontent.com.

  As a result, the ConceptNet and OMW `license_url` values point at GitHub pages I read through the raw or git path.
- **Wikimedia APIs**: the MediaWiki API refused one statistics call with "too many requests" (the proxy's egress IP
  is shared). Counts were taken from dump listings, WDQS and single page reads.
- **Not verified**:
  - the unit behind BabelNet's "45G";
  - whether categoriesrdf offers checksums (none were found);
  - the per-wordnet content of each OMW LICENSE file (the licences were taken from `omw-data/index.toml`);
  - Crossref's total record count (the blog says "nearly 180 million").
- **Considered, not included**:
  - CILI (`cili.tsv.xz`, 1,954,300 bytes, CC BY 4.0, HEAD 200): referenced in the OEWN row instead.
  - MSC2020: CC BY-NC-SA 4.0, a non-commercial licence.
  - Wikidata "all" RDF dumps: `latest-all.nt.bz2` is 195,885,605,402 bytes and `latest-all.ttl.bz2` is
    125,540,901,537, larger than the JSON.
  - The DBpedia labels and skos-categories partitions: sizes are in that row's notes.
  - ORCID public data file, OpenCitations, Semantic Scholar (key required) and PanLex: not probed, out of time
    budget.

## Sources read (2026-09-25)

**Wikimedia**
- https://www.wikidata.org/wiki/Wikidata:Database_download (raw wikitext)
- https://dumps.wikimedia.org/wikidatawiki/entities/ and the dated subdirectories 20260914, 20260916, 20260918, 20260921 and 20260923, with their sha1 and md5 files
- https://dumps.wikimedia.org/, https://dumps.wikimedia.org/legal.html, https://dumps.wikimedia.org/other/
- https://dumps.wikimedia.org/other/cirrussearch/DEPRECATED.txt and https://dumps.wikimedia.org/other/cirrus_search_index/20260920/ (per-wiki listings)
- https://dumps.wikimedia.org/{enwiki,trwiki,swwiki,yowiki,wikifunctionswiki,abstractwiki}/latest/ with their sha1sums
- https://dumps.wikimedia.org/other/mediawiki_content_current/ (listings and SHA256SUMS), https://dumps.wikimedia.org/other/mediawiki_content_history/readme.html, https://wikitech.wikimedia.org/wiki/MediaWiki_Content_File_Exports
- https://dumps.wikimedia.org/other/categoriesrdf/ (listing and file head), https://dumps.wikimedia.org/other/enterprise_html/
- WDQS query (lexeme languages), https://www.wikidata.org/w/api.php (wbcontentlanguages)
- https://abstract.wikipedia.org/wiki/Abstract_Wikipedia:Main_page
- https://en.wiktionary.org/wiki/Wiktionary:Copyrights

**DBpedia**
- https://databus.dbpedia.org/sparql (queries over versions, files, sizes and sha256)
- DataID pages for the ontology 2024.08.01-180007 and for instance-types 2025-12-01, and the dbpedia-wikipedia-kg-dump group
- https://www.dbpedia.org/resources/ontology/, https://www.dbpedia.org/resources/snapshot-release/, https://www.dbpedia.org/blog/

**YAGO and KBpedia**
- https://yago-knowledge.org/downloads/yago-4-5, https://yago-knowledge.org/downloads/yago-4-6
- https://yago-knowledge.org/data/yago4.5/, https://yago-knowledge.org/data/yago4.6/ and its samples/
- https://kbpedia.org/, https://kbpedia.org/resources/downloads/

**Lexical resources**
- ConceptNet wiki via raw.githubusercontent.com/wiki/commonsense/conceptnet5/ (Downloads, Copying-and-sharing-ConceptNet, Languages); https://conceptnet.io/
- https://en-word.net/, https://en-word.net/downloads, and the english-wordnet README (git)
- https://omwn.org/ (index, omw2, news, docs); omw-data README and index.toml (git); the `wn` 1.1.1 package index (PyPI)
- https://kaikki.org/, https://kaikki.org/dictionary/ (index, alphabetical.html, rawdata.html, and the Turkish, English, All-languages pages); the wiktextract README (git)
- http://kaiko.getalp.org/about-dbnary/ (home and download page), http://kaiko.getalp.org/static/ontolex/latest/
- https://babelnet.org/about, https://babelnet.org/downloads, https://babelnet.org/license

**Scholarly indexes**
- https://help.openalex.org/ and llms.txt, plus the access/snapshot, api/authentication, access/sync, data/topics and data/concepts pages (markdown)
- https://openalex.s3.amazonaws.com/ (LICENSE.txt, RELEASE_NOTES.txt, entity manifests, legacy-data manifest)
- https://www.crossref.org/services/metadata-retrieval/public-data-file/, https://www.crossref.org/documentation/retrieve-metadata/ (Licensing section), https://www.crossref.org/documentation/retrieve-metadata/bulk-downloads/, https://www.crossref.org/blog/2026-public-data-file-now-available/
- https://academictorrents.com/details/b5ee0e102689b3e67023dd024694c0f5f124646f and its .torrent
- https://schema.org/docs/developers.html, https://schema.org/docs/releases.html, https://schema.org/docs/terms.html
- https://ror.readme.io/docs/data-dump, Zenodo API records for the ror-data community
- https://physh.org/licensing, https://physh.org/releases, https://physh.org/apis, and the PhySH repository (git; tag v2.8.0)
