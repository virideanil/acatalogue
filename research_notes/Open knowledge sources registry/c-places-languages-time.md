# Cluster C: places, peoples' languages and time — companion notes

Registry rows: `c-places-languages-time.tsv` (35 sources). Compiled 2026-09-25 from this container through
the agent proxy. Every URL in the TSV came from a publisher page, listing or manifest read that day. Each was
probed live, first with `curl -sSI -L`. Where HEAD gave no length, a 1 KiB range GET was used; where that was
also ignored, a full GET of the small file.

## How the numbers were obtained

- **bytes** is the `Content-Length` of the final HEAD response. There are four exceptions:
  - IANA registry and `iso15924.txt`: the server sends no length, so the size is from a full GET.
  - The two npm tarballs: the size is the total in a `Content-Range` answer.
  - WHG: blank, because the download needs a login.
- **Counts in notes** (rows, columns, languages) were read from the files themselves:
  - Small files were downloaded in full: GeoNames text and cities files, Natural Earth DBFs, CLDR tarballs,
    iso-codes, PeriodO, WPP total population, EPR, the Glottolog languoid table, DILA.
  - Large archives were read through HTTP range requests on their zip central directory and single members:
    Glottolog CLDF, WALS, D-PLACE, Cliopatria, Pleiades GIS, the GeoNames zips.
- **No whole file over 20 MB was downloaded.** One larger read was partial: a 32 MB range (16%) of
  `alternateNamesV2.zip`, used to count name languages.
- **languages** columns that are estimates or lower bounds:

  | Source | Value | Basis |
  |---|---|---|
  | GeoNames alternate names | 406 (lower bound) | Base codes in the first 16% of rows; still rising (348 at 4%) |
  | Who's On First | 292 (lower bound) | Languages in the Andorra file alone |
  | Getty TGN | about 220 (estimate) | Getty's own LOD documentation: "AAT about 105, TGN about 115 more" |
  | WHG | 1 (floor) | Varies per dataset |

## Sources read

- **GeoNames**
  - https://download.geonames.org/export/dump/ (listing) and `readme.txt`, which carries the licence and the column definitions.
- **Who's On First**
  - https://whosonfirst.org/download/ and https://whosonfirst.org/docs/licenses/
  - The `LICENSE.md` of the data repositories.
  - https://data.geocode.earth/wof/dist/sqlite/inventory.json, which gives the size and SHA-256 of 478 files.
- **Natural Earth**
  - The 10m admin-0 download page, `/downloads/` (it links naciscdn.org) and `/about/terms-of-use/`.
  - The GitHub README and `VERSION` on raw.githubusercontent.com.
- **Pleiades**
  - https://pleiades.stoa.org/downloads, the atlantides.org directory listings and the GIS package README.
  - Zenodo, for the numbered releases.
- **World Historical Gazetteer**
  - The home page, `/licenses/` and dataset pages.
  - The docs site (search index, the APIs page and the FAQ).
  - `GET /api/sources/`.
- **OSMNames**: https://osmnames.org/download/
- **Getty**
  - The Data & Services page, which states ODC-By 1.0.
  - The LOD documentation https://vocab.getty.edu/doc/, which gives the export URLs and the language note.
  - The TGN "about" page, which gives the record counts.
- **SIL**: https://iso639-3.sil.org/code_tables/download_tables, which carries the terms of use.
- **Glottolog**
  - https://glottolog.org/meta/downloads, which gives the version 5.3 bitstreams and the licence.
  - The Zenodo API: concept 3260727, versions listed.
- **WALS**: https://wals.info/download and the Zenodo API (concept 3606197).
- **IANA**: the registry file and https://www.iana.org/help/licensing-terms (CC0).
- **CLDR**
  - https://cldr.unicode.org/index/downloads and `/downloads/cldr-48`.
  - https://unicode.org/Public/cldr/
  - npm registry metadata for the `cldr-*` packages.
  - https://www.unicode.org/copyright.html
- **ISO 15924**: the Unicode RA pages `iso15924/`, `codelists.html` and `iso15924-text.html`.
- **iso-codes**
  - The Debian pool listing and the `.dsc` checksums.
  - The Salsa API (tags and releases) and `REUSE.toml`.
- **PeriodO**
  - https://perio.do/en/ (its download links) and https://perio.do/license/
  - ARK redirects to data.perio.do.
- **Cliopatria**: the Zenodo API (concept 13363120), plus the README and LICENSE inside the release.
- **DILA**
  - https://authority.dila.edu.tw/docs/open_content/download.php
  - The README and SCHEMA inside the archive.
- **UN WPP**: https://population.un.org/wpp/ is a single-page app. Its download list and licence footer are in
  https://population.un.org/wpp/assets/downloads.json, found through the app's JavaScript bundle.
- **Our World in Data**
  - The chart page, `population.metadata.json` and the indicator metadata API.
  - https://ourworldindata.org/faqs, which gives the licence.
- **D-PLACE**: the Zenodo API, plus `LICENSE` and `cldf/README.md` inside the archive.
- **EPR**: https://icr.ethz.ch/data/epr/core/
- **This repository**: `docs/DESIGN.md` §1–§4. `data/acatalogue.sqlite` was opened **read-only** (`mode=ro`)
  to test WPP's coverage of the 248 M49 areas.

## Caveats that matter for acatalogue

- **Licences that are not open, or not clear**
  - **SIL ISO 639-3**: the product must not "provide a means to redistribute the code set". Use IANA (CC0)
    or Glottolog's `ISO639P3code` for anything republished.
  - **ISO 15924 RA file**: "All Rights Reserved" and outside Unicode's openly licensed directories. The same
    codes are in IANA (CC0), CLDR and iso-codes.
  - **WHG**: the aggregate database is CC BY-NC 4.0, on top of each dataset's own licence.
  - **D-PLACE**: CC BY-NC 4.0, except component sets such as Carneiro, which are CC BY 4.0.
  - **EPR**: no licence is stated anywhere on its page.
  - **DILA**: the download page says CC BY-SA 2.5 Taiwan, while the README in the archive says CC BY-SA 3.0 Unported.
  - **iso-codes**: LGPL-2.1-or-later. It redistributes ISO 639-3, which SIL's terms do not allow; that
    tension is Debian's to resolve, but record it.
  - **Pleiades**: the site says CC BY 3.0. The Zenodo label differs between releases (4.0 shows CC BY 4.0,
    4.1 shows CC BY 3.0).
- **Freshness**
  - OSMNames' newest planet file is years old.
  - Getty says TGN is "refreshed monthly", but `full.zip` is dated 2025-01-19 and `explicit.zip` 2026-01-04.
  - The DILA time authority dates from 2012.
  - Natural Earth 5.1.x dates from 2022.
  - wals.info still names v2020.4, although v2020.5 (2026-07-16) is on Zenodo.
  - CLDR JSON 48.2.1 (2026-07-08, a TZDB 2026c fix) exists only as a GitHub tag. The npm packages are still
    48.2.0, and CLDR 49 is in beta.
- **Time encodings differ; normalise to astronomical years on import**
  - PeriodO: ISO 8601 style with a year 0.
  - CLDR eras: proleptic Gregorian with year 0.
  - DILA: Julian Day Numbers.
  - Pleiades: "N BC/AD" text for periods and integers on names.
  - Cliopatria: negative integers for BCE. It is unstated whether 1 BCE is -1 or 0.
  - OWID: integers from -10000.
- **Joins to the existing place facet**
  - Codes that are UN M49: GeoNames `ISO-Numeric`, Natural Earth `UN_A3` (with -99/-099 nulls), WPP `LocID`,
    and CLDR's numeric territory and region codes.
  - WPP 2024 covers 235 of the 248 M49 areas and 20 of the 33 that the World Bank baseline lacks.
  - The remaining 13 are 010 074 086 162 166 239 248 260 334 574 581 612 744. For those, CLDR
    `territoryInfo` has only rough figures.
- **Crosswalk keys**
  - Wikidata QIDs: GeoNames `wkdt` rows, Natural Earth `WIKIDATAID`, WOF `wd:id`, Pleiades references,
    PeriodO `spatialCoverage`, Cliopatria `Wikidata`.
  - Glottocodes: Glottolog, WALS, D-PLACE.
  - ISO 639-3 codes: IANA, Glottolog, iso-codes.
- **Perspective data worth keeping**
  - Natural Earth's 31 point-of-view columns and files. For example, Kosovo and Northern Cyprus are
    "Admin-0 country" in `FCLASS_TR` but "Unrecognized" in `FCLASS_ISO`.
  - WOF's supersedes/superseded_by lifecycle.
  - PeriodO's authority-attributed, overlapping periods.
  - All of these fit acatalogue's rule that claims are attributed and nothing is deleted.

## Peoples and ethnic groups (sensitivities)

Only two vocabularies are included, both marked `recommend=no`:

- **D-PLACE societies** (CC BY-NC). These are ethnographic units at a focal year, mostly described by outside
  observers. Some names are exonyms. Some are being replaced by self-designations, such as Syilx for "Okanagan".
- **EPR** (no licence stated). These are expert codings of "politically relevant" groups and of their access
  to power.

Neither is a list of identities to label people with. If they are used at all, they should enter as attributed,
dated claims with an epistemic status (`attributed` or `contested`), never as categories in the compendium.

Considered and not included:

- **Native Land and CHGIS**: WHG's sources API flags both as licence-restricted (HTTP 451 for redistribution).
  Native Land also concerns Indigenous territorial claims, which need consent-aware handling.
- **Ethnologue and Joshua Project**: not probed in this pass.

## Blocked or uncertain (retry from another network or with credentials)

- **GitHub**: release pages, `expanded_assets` and `api.github.com` answered 403, because this session is bound
  to its configured repository. Consequences:
  - The cldr-json release zip names for 48.2.0 and 48.2.1 could not be listed, so the CLDR rows use the npm
    tarballs.
  - The OSMNames release date could not be read.
  - Release-asset downloads themselves worked (OSMNames HEAD 200).
- **Natural Earth**: the `naturalearthdata.com/http//…/download/…` link answered 500 (a WordPress error).
  naciscdn.org worked and is the CDN the publisher's downloads page links to.
- **Who's On First**: `dist.whosonfirst.org` answered 502 through the proxy. The download page's live links
  point to `data.geocode.earth`.
- **Getty**
  - The SPARQL endpoint answered "Service temporarily degraded" (HTTP 499) twice, so the TGN language count
    stays an estimate.
  - Per-record JSON answered 403.
  - `https://tgndownloads.getty.edu` failed TLS; `http://` works.
- **HYDE 3.3**: the country-level indicator files on Utrecht's Yoda vault sit behind a proof-of-work bot
  challenge ("Making sure you're not a bot!"). Not probed. OWID's series carries HYDE for years before 1800.
- **World Historical Gazetteer**
  - Downloads need a free account: the TSV export answered 401.
  - The site refuses curl's default User-Agent.
  - There is no bulk dump; the API needs a token.
- **ChronOntology (DAI)**: only a paged JSON API (`/data/period`) was found, no bulk dump. Not listed.
- **UN WPP**: deep links such as `/wpp/downloads` return 404 to non-browsers because the site is a
  single-page app. The file URLs in `downloads.json` answer 200.

## First five for a starter selection

1. **`glottolog-cldf`**: 27,177 languoids with hierarchy, coordinates, ISO 639-3 codes, and 120k alternative
   names in 249 tagged languages. CC BY 4.0, 49.6 MB. Its Glottocodes join WALS and D-PLACE.
2. **`cldr-localenames-full`**: names of languages, territories and scripts in 766 locales (323 languages).
   Territory keys include M49 regions, so it plugs straight into `space/m49-*`. Unicode License v3, 2 MB.
3. **`periodo-dataset`**: 9,446 attributed period definitions with Wikidata-linked spatial coverage,
   astronomical years and labels in 52 languages. Public domain, 7.8 MB.
4. **`un-wpp2024-total-population`**: M49-keyed population for 1950–2100. It closes 20 of the 33 gaps in
   the current baseline. CC BY 3.0 IGO, 17 MB.
5. **`naturalearth-populated-places`**, with **`naturalearth-admin0-countries`** as its companion: public
   domain places and countries with Wikidata, GeoNames and WOF ids, names in 25 languages, and 31 national
   points of view on disputed areas. Under 8 MB together.

Next in line are `geonames-cities15000` + `geonames-alternatenames-v2`, `pleiades-gis-csv`,
`iana-language-subtag-registry` and `debian-iso-codes`.
