# Registry cluster D: sciences, life, health, earth and space, technology, statistics

Companion to `d-sciences-health-statistics.tsv` (33 rows). Compiled and probed from this
container on 2026-09-25.

## Method

- Every URL was taken from a publisher page, file header or listing I read (named below), then
  probed with `curl -sSI -L --max-time 30`, falling back to a 1 KiB range GET when HEAD did not
  end in 200. The `verified` column holds that result. Where a bare HEAD status would mislead, the
  column says so instead: GCMD (HEAD unsupported, GET 200), the UN SDG archive (POST only),
  UMLS (302 to a login page), SNOMED CT (portal page only), IEEE (viewer page) and the Gold Book (403).
- `bytes` is the Content-Length of that probe. It is empty when the server sends none (chunked)
  or the file sits behind a login; measured sizes are then given in `notes`.
- No large file was downloaded whole. Archive members were listed by range-reading the zip
  central directory (COL ColDP, GBIF Backbone, ICD-11, UCD). Two members were extracted by range
  to count vernacular languages: COL `VernacularName.tsv` (2.8 MB compressed) and GBIF
  `VernacularName.tsv` (14.5 MB). OBO files were sampled in 2 MB ranges for tag, relation,
  synonym-scope and xref-prefix tallies. Only small files were fetched whole (QUDT unit graph
  4.1 MB, UAT 3.2 MB, GCMD pages, SPDX, IANA, Linguist, PubChem CSV, and GEMET 7.4 MB while
  assessing it).
- `languages` counts label languages actually seen in the data. Where it is an estimate, the
  row's notes say how it was derived.

## Starter selection (open, lean, clean, spread over domains)

1. **ncbi-taxonomy**: public domain, 80 MB, daily. The only open taxonomy of life under the
   500 MB bar; COL is better but 1.02 GB.
2. **mondo**: CC BY 4.0. Its xrefs tagged `MONDO:equivalentTo` give ready exactMatch crosswalks
   to OMIM, Orphanet, DO, NCIt, MeSH, UMLS and ICD-11.
3. **qudt-units**: CC BY 4.0, 6.9 MB, 24 label languages, with Wikidata/DBpedia/UCUM/IEC
   crosswalks.
4. **chebi-full**: CC BY 4.0, 47 MB gzipped OBO, with synonyms and xrefs. Filter to 3-star
   entities for a first pass.
5. **gcmd-science-keywords**: CC0, 3,780 SKOS concepts in 2 pages. Its topic tree parallels the
   acat/earth subtree.

Alternates: environment-ontology (CC0, 2.9 MB OBO), gene-ontology-basic, ncit-flat,
unicode-ucd, and un-wpp-2024-indicators as a replacement for the audit's population baseline (it
is statistics, not a vocabulary).

## Overlaps with the other cluster files (checked read-only on 2026-09-25)

- **GEMET and PhySH** were assessed here but left out: `b-libraries-thesauri.tsv` has `gemet`
  (same URL), and both `a-encyclopedic-scholarly.tsv` and `b-libraries-thesauri.tsv` have
  `physh` (tag v2.8.0, `physh.nt.gz`). For PhySH, the SKOS-flavoured
  `physh_skos_compat.ttl` (1,414,383 B) is an alternative file. GEMET has 36 label languages
  (checked).
- **un-wpp-2024-indicators** has the same URL as `un-wpp2024-demographic-indicators` in
  `c-places-languages-time.tsv`; keep one. This row adds converter facts: multi-member gzip,
  LocID/ParentID semantics, and the Togo update.
- No id collides with the a-, b- or c- files.

## Sources read (publisher pages, headers, listings)

- OBO Foundry registry `https://obofoundry.org/registry/ontologies.jsonld` (products and licences);
  OBO file headers (`data-version`, `terms:license`) of GO, ChEBI, UBERON, CL, DO, Mondo, HPO and
  ENVO; GO download and citation-policy pages and `release.geneontology.org`; ChEBI FTP `README`
  and `LICENSE`; the licence files in the UBERON, CL and ENVO repositories; DO's about page;
  Mondo's download page; the HPO licence page (human-phenotype-ontology.github.io).
- NCIt EVS `ReadMe.txt`, `ThesaurusTermsofUse.pdf` and `/ftp1/thesaurus-latest`; NCBI taxonomy FTP
  listing, `taxdump_readme.txt` and the NCBI policies page.
- COL download and cite pages, ChecklistBank dataset 316321 (API), and the listings of
  download.catalogueoflife.org; GBIF hosted-datasets listing and README, GBIF dataset API, and
  the GBIF data blog (2026-06-23) on the move to COL XR.
- WHO ICD-11 browse pages (2026-01, 15 languages), the ICD-11 licence PDF; SNOMED
  `get-snomed` and `gps` pages, MLDS; UMLS downloads, licence agreement and 2026AA statistics pages.
- qudt.org home page and catalog, and the `dcterms:rights` in the unit graph; astrothesaurus.org
  (home, about, version-release posts) and the UAT repository listing (via WebFetch); GCMD KMS
  (`/kms/concept_schemes`, CSV and RDF), the Earthdata GCMD keyword viewer page (CC0 statement)
  and the Keyword Community Guide PDF; the SWEET README and LICENSE and `sweetAll`; the GEMET
  download page; the IPCC-WG1 Atlas README and reference-regions README, the folder listing
  (WebFetch) and Zenodo record 5171760; physh.org licensing and releases pages and the PhySH
  CHANGELOG and LICENSE.
- oeis.org LICENSE/EULA, Welcome and Download wiki pages; PubChem periodic-table CSV and PUG-View
  element records; NLM web policies; the IUPAC FAIR Chemistry Cookbook pages (PubChem periodic
  table, Gold Book API).
- OWID FAQ, docs.owid.io Tables API, and the co2-data README; the UNSD SDG portal bundle and API
  (`ArchiveData/GetArchiveTable`, `Goal/List`) and the UN website terms of use; the WPP site bundle
  and `/wpp/assets/downloads.json`; the Eurostat bulk-download page, user guide, copyright notice
  and TOC in en/de/fr.
- The IEEE thesaurus widen.net page and the IEEE Taxonomy 2022 PDF (a copy hosted at
  apmc-mwe.org); the SPDX list page, `licenses.json`, `accessingLicenses.md` and SPDX spec 2.3
  front matter; the IANA licensing terms and `media-types.xml`; Unicode `ReadMe.txt` and
  `license.txt`; Linguist README, CONTRIBUTING and LICENSE.

## Caveats a converter author must know

- **Imported terms.** `mondo.obo` (GO, HP, CHEBI, CL, ENVO…) and `envo.obo` (CHEBI) embed terms
  from other ontologies. Filter on the ontology's own id prefix, or use `mondo-simple.obo` or
  `envo-basic.obo`. In Mondo, `excluded_subClassOf` is a relationship, not a hierarchy edge.
- **Branch heads, not releases.** The DO and ENVO PURLs resolve to branch heads on
  raw.githubusercontent.com, and UAT, IPCC and Linguist are served from branches. Record
  the `data-version` or the commit, not just the URL.
- **ChEBI licence wording.** The README once says "Attribution-ShareAlike 4.0", but its LICENSE
  file, the OBO header and the OBO registry say CC BY 4.0. The README also misspells the file
  names (hyphen instead of underscore).
- **HPO** is free but its licence forbids altering content or logical relationships and requires
  showing the version. The licence URL in the file header (hpo.jax.org) is a single-page app that
  answers 404 to curl.
- **ICD-11** is CC BY-ND 3.0 IGO. WHO's terms exclude crosswalks and translations, which need a
  written agreement. SNOMED CT needs an affiliate licence. UMLS is free but source-restricted:
  levels 0 to 4, plus level 9 used for SNOMED CT.
- **GBIF Backbone** is frozen at 2023-08-28, and GBIF now defaults to the COL Extended Release.
- **NCBI taxdump** is rebuilt more than once a day (79,614,555 B at 19:30 GMT, 79,615,599 B at
  20:30 GMT). Always fetch the `.md5` alongside it.
- **GCMD KMS** answers HEAD with 404 and paginates RDF at a maximum of 2,000 concepts per page:
  the science keywords take 2 pages.
- **QUDT** carries a UCUM notice: UCUM codes and definitions stay under Regenstrief's licence.
- **Open but restricted in part.** For OWID, third-party columns keep their licences (see the
  codebook). For Eurostat, non-EU/EFTA/candidate-country and third-party data may not be reused
  commercially. For PubChem, IUPAC-contributed element data is CC BY-NC-ND 4.0.
- **UN SDG database** states no open licence; the portal links the general UN terms (personal,
  non-commercial). Bulk download is POST-only: form field `archiveId`.
- **IPCC regions.** The file has 58 regions, but the README prose says 46 land and 14 ocean.
- **SPDX** states no licence for the data files; the spec, whose Annex A is the list, is CC BY 3.0.
- **Unicode** `latest` moved to 18.0.0 (files dated 2026-09-01). Pin `/Public/18.0.0/`.
- **UAT** 6.1.0 was announced for spring 2026 but is not published; 6.0.0 is current.
- **WPP** CSV `.gz` files are multi-member gzip. Countries' `LocID` equals the M49 code, but
  `ParentID` uses WPP's own region ids (for example 906), and special aggregates come first.

## Blocked or uncertain

- **goldbook.iupac.org** sits behind a Cloudflare challenge (403) for curl and WebFetch. The
  licence (CC BY-NC-ND 4.0) and endpoint are quoted from IUPAC's own cookbook (2023), not
  re-verified today.
- **ieee.org** returns an AWS WAF challenge (HTTP 202). The thesaurus licence was inferred from
  the IEEE Taxonomy PDF (CC BY-NC-ND 4.0). The thesaurus PDF itself is reported as
  password-protected.
- **GitHub HTML and API** are not enabled for this session. I used raw.githubusercontent.com,
  release download redirects, and WebFetch for three folder listings. I did not attach
  third-party repositories.
- **www.catalogueoflife.org and www.un.org** refuse non-browser user agents (403). I read them
  with a browser user agent; the download hosts themselves accept any user agent.
- **Not checked or estimated:**
  - SNOMED release cadence and its Spanish Edition count.
  - ChEBI `languages=3`, estimated from untagged INN synonym forms.
  - The OEIS sequence count, which is not given.
  - The SDG archive, whose size is known only from response headers of a POST that was aborted
    before the body.
- **Not included:**
  - MeSH (library cluster).
  - ACM CCS (elsewhere).
  - MSC2020, EDAM and AGROVOC (other clusters or niche).
  - ITIS (inside COL).
  - UO (named as the lean alternative in the QUDT row).
  - Wikidata-derived software vocabularies: no publisher bulk file; noted in the Linguist row.
