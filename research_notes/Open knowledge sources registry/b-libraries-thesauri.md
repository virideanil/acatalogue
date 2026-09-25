# Registry cluster B: library subject systems, classifications and thesauri

Companion to `b-libraries-thesauri.tsv`, which has 40 rows. I compiled it on 2026-09-25 from this container, through the
configured agent proxy. The reviewer was an AI agent (Claude); a person should check these rows before they go into
`seed/sources/`.

## Method

- **Probing.** Every `url` was probed with `curl -sSI -L --max-time 30`, with `-r 0-1023` as the fallback. The
  `verified` column records each outcome.
  - **35 of 40 URLs answered 200 or 206.** 31 of those are the bulk file itself. The other four are landing pages of
    systems that have no public dump: UDC Summary, DDC, DeCS and the ASC Leiden thesaurus.
  - **Five are blocked from here.** FAST and ACM CCS sit behind a Cloudflare challenge. NLNZ Māori Subject Headings
    serves an Incapsula challenge. AIATSIS returns a Cloudflare 403. For `api.aiatsis.gov.au` the proxy rejected the
    CONNECT with a 502.
- **Sizes.** `bytes` is the Content-Length from the probe, with these exceptions:
  - Homosaurus, the Brian Deer PDF and EuroVoc sent no Content-Length (EuroVoc also ignores Range). Their size is the
    length of a complete GET of these small files.
  - UNESCO's size comes from Content-Range.
  - RAMEAU's size is the Content-Length of a form-driven download, which I stopped after 256 KB.
  - AUSTLANG's size comes from the data.gov.au listing.
- **What was downloaded.** Nothing large was downloaded in full.
  - Small files (up to about 25 MB) were fetched to profile them: LCGFT, LC Children's, GND subjects, NDLSH, NDC9,
    UNESCO, EuroVoc, GEMET, STW, NALT, ERIC, MSC2020, JEL, PhySH, Homosaurus, Iconclass and the Brian Deer PDF.
    Getty label languages were counted with small SPARQL queries.
  - Large dumps were read only through Range requests: the first 0.3–3 MB, or the zip central directory at the end
    (Getty, AGROVOC).
- **Checksums checked.**
  - GND: the SHA-256 of the TTL matches `001_Pruefsumme_Checksum.txt`.
  - Iconclass: the md5 matches the Zenodo record.
  - LC: the SHA-1 published in the `.json` info files is **of the decompressed .nt, not of the .gz** it is attached to. I
    confirmed this on the LCGFT and Children's files. For single-part uploads the S3 ETag equals the MD5 of the `.gz`.
    A pipeline that hashes the downloaded bytes has to decompress before comparing.

## Starter selection (my first five)

1. **agrovoc** (74 MB zipped, CC BY 4.0). FAO is a UN perspective, and the vocabulary has labels in about 55 languages,
   many of them African and Asian. Its VoID lists linksets to LCSH, DDC, GND, RAMEAU, EuroVoc, GEMET, UNESCO, STW,
   TheSoz, MeSH, YSO, NALT and Wikidata, which makes it a second crosswalk hub. Use `agrovoc_lod.nt.zip` if you want
   `skos:prefLabel` materialised.
2. **gnd-subjects** (24 MB, CC0). It gives a German-language perspective. Every record carries mappings: closeMatch to
   LCSH, RAMEAU, BNE, STW, TheSoz, AGROVOC and MeSH, and owl:sameAs to Wikidata. It also cites DDC numbers and uses its
   own GND-Systematik. Normalise NFD to NFC.
3. **lcsh** (101 MB, public domain). This is the reference point that most other rows map to (GND, RAMEAU, NDLSH, YSO,
   NALT, AAT, Homosaurus). Because the crosswalks run to it, the catalogue can show where other traditions diverge from
   it.
4. **ndlsh** (4 MB, reuse permitted with credit, updated daily), together with **ndc9-jla** (1 MB, CC BY). This is a
   Japanese perspective: NDLSH links to LCSH and to NDC/NDLC, and NDC9 links back to NDLSH. Treat the two as one choice.
5. **unesco-thesaurus** (8.9 MB, CC BY-SA 3.0 IGO). It gives a UN/UNESCO perspective with Arabic, Russian, Spanish,
   French and English labels. Because the licence is ShareAlike, redistributed label tables must stay under CC BY-SA.

Close runners-up:

- **yso**: fi, sv, en and Northern Sámi, with Wikidata and LCSH links, CC BY 4.0.
- **eurovoc**: 27 languages.
- **getty-aat-explicit**: multilingual art and material culture, ODC-By. It needs the Getty inference steps.
- **rameau**: French, with rich mappings. The download goes through a form.

## Caveats a converter author needs

- **Not SKOS, or SKOS only in part:**
  - GND uses GNDO properties.
  - Getty explicit exports hold only explicit statements. Hierarchy is reified `gvp:broaderPreferred`, and labels hang
    on SKOS-XL term nodes, so `skos:broader` and `skos:prefLabel` must be inferred. The alternative is the stale
    `full.zip`.
  - MeSH RDF uses `meshv:`.
  - ERIC is Nstein XML whose relations point to term names, not ids.
  - Iconclass is a custom text format.
  - MSC2020 is named `.csv` but is tab-separated, Latin-1 and CRLF.
  - AGROVOC core has SKOS-XL labels only.
- **URI drift:**
  - TheSoz moved from `http://lod.gesis.org/thesoz/concept/<id>` to `https://data.gesis.org/thesoz/concept_<id>`. The
    GND, AGROVOC and STW mappings still use the old form, so join on the numeric id.
  - GND writes `https://id.loc.gov/...` where LC itself writes `http://`.
  - YSO tags Northern Sámi both as `se` and as `sme`.
- **Stale or moving endpoints:**
  - NLM's download page still points "current year" RDF at `rdf/2025/`. The row uses `rdf/2026/`.
  - The UN Thesaurus S3 bucket stops at 2023-11-17. Current files are in the UN Digital Library, which serves an AWS WAF
    challenge from here.
  - LCC is available as bulk data only in the 2016 MDSConnect set.
  - GEMET's latest version is 4.2.3 (2021).
  - The Iconclass Zenodo snapshot is from 2022; the live data is in the GitHub repository.
  - The Getty `full.zip` files date from January 2025. The explicit AAT file is from August 2026; TGN and ULAN from
    January 2026.
- **Licences that constrain an open catalogue:**
  - UN Thesaurus: non-commercial only.
  - MSC2020: CC BY-NC-SA.
  - Homosaurus: CC BY-NC-ND.
  - ACM CCS: educational and research use only.
  - JEL: all rights reserved.
  - DeCS: licence agreement required, with no separate redistribution.
  - DDC: proprietary; the Dewey Linked Data terms forbid harvesting and "material amounts" in a database.
  - **The UDC Summary moved from CC BY-SA 3.0 to CC BY-NC 4.0 "from 2026".** udcdata.info still shows the old licence.
    The repo stores UDC and DDC top-class captions today. That is probably minimal quotation, but a human should check
    it against these terms.
- **Duplicates across clusters.** `physh` duplicates cluster A's row, and `getty-tgn-explicit` duplicates cluster C's
  row. Both use the same id and URL, so keep one of each when merging.
- **Indigenous and community vocabularies.** These are Ngā Upoko Tukutuku, Brian Deer/Xwi7xwa, AIATSIS and Homosaurus.
  Their governance and consent expectations go beyond the licence. Contact the governing bodies before ingesting, and
  record their preferred attribution.

## Blocked or uncertain items

| Item | What happened | What remains to do |
|---|---|---|
| FAST (researchworks.oclc.org) | Cloudflare challenge (403) on HEAD and GET. The download page itself was readable. | Re-probe from another network. Sizes are from the publisher's listing. |
| ACM CCS (dl.acm.org, acm.org) | Cloudflare 403, also through the web-fetch tool. web.archive.org was unreachable. | Get the direct SKOS file URL from a browser. |
| Ngā Upoko Tukutuku (natlib.govt.nz) | Incapsula challenge. The MARC download and the terms are known only from a search-engine extract. data.govt.nz was also bot-blocked. | Confirm the file and the terms with NLNZ. |
| AIATSIS Pathways (aiatsis.gov.au) | Cloudflare 403. The CC BY 4.0 licence and the three-thesaurus structure come from search extracts. | Confirm formats and licence. |
| AUSTLANG (api.aiatsis.gov.au) | The proxy rejected the CONNECT (502). The data.gov.au listing was read. | Re-probe elsewhere. |
| TheSoz (gesis.org) | Cloudflare challenge on www.gesis.org; certificate failure on https://lod.gesis.org. | None: the Zenodo deposit (GESIS DOI 10.7802/2912) is the verified source. |
| RAMEAU (pef.bnf.fr) | No direct URL. Downloads need the JSF form sequence described in the notes. data.bnf.fr and api.bnf.fr reset connections intermittently. | Script the form sequence. |
| id.loc.gov | HTML pages returned 403 except /download/ and /about/. Bulk files were fine. The LCC "embeddings" on the download page are not the classification. | None. |
| github.com | The HTML and API are blocked by this session's policy. raw.githubusercontent.com works; it served the Iconclass, PhySH and arxiv-base files. | None. |
| Getty | Only http:// works; https to `*downloads.getty.edu` resets. The SPARQL endpoint refused full aggregate queries on TGN ("Service temporarily degraded"), so TGN's language count uses Getty's documented estimate and a 50,000-label sample. | None. |
| BNE / datos.bne.es | Blocked by BNE's security page. I added no row; the GND–EMBNE mapping from DNB is a way in. | Retry from another network. |
| National Library of Korea LOD (lod.nl.go.kr) | Upstream unreachable (503). | Check whether a dump exists. |

## Regional coverage: what exists and what does not

- **East Asia.** NDLSH and NDC9 are open and verified. For Korea (NLK LOD) I could not reach the server or find a dump.
  I found no open dump of the Chinese Library Classification.
- **South Asia.** I found no open national subject system; the Colon Classification has no open dump that I could find.
  Labels exist in AGROVOC (Hindi, Bengali, Marathi, Nepali, Sinhala, Telugu, Malayalam) and in UDC Summary translations
  (Bengali, Tamil, Kannada, Hindi), but the UDC Summary is now NC and not downloadable.
- **Arab world.** I found no open Arabic subject-heading dump. Arabic labels are available through UNESCO, the UN
  Thesaurus (NC), AGROVOC, GEMET and AAT.
- **Africa.** I found no open subject system published from Africa. AGROVOC has Swahili labels. The African Studies
  Thesaurus of ASC Leiden (Netherlands) is web-only and all rights reserved. I added it as a `restricted` row because it
  covers about 1,000 ethnic groups, 500 languages and 340 polities.
- **Latin America.** DeCS (BIREME/PAHO, São Paulo) is the major system, but it needs a licence agreement. It includes
  3,923 descriptors of its own on homeopathy, public health and traditional medicine. Spanish and Portuguese labels are
  otherwise available through AGROVOC, UNESCO and EuroVoc. Spain's BNE was blocked from here.
- **Indigenous perspectives.** Ngā Upoko Tukutuku (Aotearoa), the Xwi7xwa Brian Deer variant (with the KPU and UBCIC
  variants in the notes), AIATSIS and AUSTLANG (Australia), and Homosaurus's labels in Indigenous languages.

## Sources read (publisher pages and listings)

- **Library of Congress:**
  - https://id.loc.gov/download/ and https://id.loc.gov/about/
  - the `.json` info files
  - https://www.loc.gov/cds/products/marcDist.php, https://www.loc.gov/cds/products/MDSConnect-classification.html and
    MDSConnect_FAQs.pdf
  - https://www.loc.gov/aba/publications/FreeLCC/freelcc.html
- **OCLC:**
  - https://www.oclc.org/research/areas/data-science/fast/download.html
  - https://www.oclc.org/en/dewey.html
  - https://entities.oclc.org/worldcat/ddc/
  - https://policies.oclc.org/en/terms/dewey-linked-data.html
- **DNB:** https://data.dnb.de/opendata/ and `001_Pruefsumme_Checksum.txt`.
- **BnF:**
  - https://data.bnf.fr/fr/opendata
  - https://api.bnf.fr/fr/dumps-de-databnffr
  - the PEF share (file list, LICENCE.txt, listeAll.txt)
  - https://www.bnf.fr/fr/conditions-de-reutilisations-des-donnees-de-la-bnf
- **NDL and JLA:**
  - https://id.ndl.go.jp/information/download_en/ and https://id.ndl.go.jp/information/use_en/
  - https://www.jla.or.jp/committees/bunrui/ndc-data/
- **Finto:** https://finto.fi/yso/en/ and https://finto.fi/koko/en/.
- **UDC:**
  - https://udcdata.info/
  - https://udcsummary.info/php/index.php, exports.htm, about.htm and the translation statistics
  - https://udcc.org/index.php/site/page?view=licences
- **Iconclass:**
  - https://iconclass.org/help/lod and https://iconclass.org/help/terms
  - the raw iconclass/data README and LICENSE
  - the Zenodo record 7074601
- **Getty:**
  - https://www.getty.edu/research-conservation/tools-databases/vocabularies/data-services/
  - https://vocab.getty.edu/ and https://vocab.getty.edu/doc/
  - the Getty SPARQL endpoint
- **UNESCO:** https://vocabularies.unesco.org/en/about.
- **UN Thesaurus:** https://research.un.org/en/thesaurus/downloads, https://metadata.un.org/skosmos/thesaurus/en/ and the
  unbis-thesaurus S3 listing.
- **EuroVoc:** https://data.europa.eu/api/hub/search/datasets/eurovoc (DCAT).
- **FAO:**
  - https://www.fao.org/agrovoc/releases and https://www.fao.org/agrovoc/about
  - the FAO CKAN package agrovoc-release
  - http://aims.fao.org/aos/agrovoc/void.ttl
- **GEMET:** https://www.eionet.europa.eu/gemet/en/exports/rdf/latest and /en/changes/.
- **STW:** https://zbw.eu/stw/version/latest/download/about.en.html.
- **TheSoz:** https://data.gesis.org/cvbrowser/thesoz/en/ and the Zenodo record 18773539.
- **NLM:** https://www.nlm.nih.gov/databases/download/mesh.html, the MeSH terms page and the nlmpubs directory listings.
- **DeCS:** https://decs.bvsalud.org/en/for-developers/, /conditions-for-downloading-decs-mesh-data/ and /about-decs/.
- **NALT:** https://lod.nal.usda.gov/en/, /nalt/en/ and /nalt-core/en/.
- **ERIC:** https://eric.ed.gov/?download and ?copyright.
- **MSC2020:** https://msc2020.org/.
- **PhySH:** https://physh.org/licensing, /releases and /apis.
- **JEL:** https://www.aeaweb.org/econlit/jelCodes.php.
- **arXiv:** https://arxiv.org/category_taxonomy, https://info.arxiv.org/help/api/tou.html and the arxiv-base raw files.
- **Homosaurus:** https://homosaurus.org/, /v5 and /releases.
- **Xwi7xwa:** https://xwi7xwa.library.ubc.ca/collections/indigenous-knowledge-organization/ and the PDF itself.
- **Te Rōpū Whakahau:** https://trw.org.nz/professional-development/nga-upoko-tukutuku-maori-subject-headings/.
- **AUSTLANG:** the data.gov.au CKAN record austlang-dataset-001.
- **ASC Leiden:** https://thesaurus.ascleiden.nl/thes.php?mnu=1.
