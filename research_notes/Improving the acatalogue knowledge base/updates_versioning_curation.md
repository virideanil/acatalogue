# Keeping large open knowledge bases current, versioned and curated: update feeds, dumps, rate limits, versioned-data tooling, review workflows and scale architecture, applied to acatalogue (current to 25 September 2026)

Method: I fetched primary pages (Wikimedia, Wikidata, OpenAlex, SQLite, DuckDB, Hugging Face, DoltHub, lakeFS/DVC, W3C CG, GO/ODK) on 2026-09-25. I also read live listings directly: the dumps.wikimedia.org directory indexes, the EventStreams OpenAPI spec, a 400 KB range read of the current Wikidata JSON dump, and one Special:EntityData response. For comparison I read acatalogue's own fetch code. Where a statement comes from a live observation and not a document, it says "observed".

## 1. Wikidata update channels, dumps, query services and API etiquette in 2026, and how to mirror or incrementally sync a subset

### Takeaway
As of September 2026, Wikidata's own guidance gives this pattern for a subset mirror. Take a baseline from the weekly JSON entity dump (latest-all.json.gz is about 156 GB, and every entity line carries `lastrevid` and `modified`). Then follow changes on EventStreams, which has 7–31 days of replay, and fetch exact revisions from `Special:EntityData/Q…json?revision=N`. The Action API and WDQS are now for small, targeted lookups. They sit under new 2026 limits: 10 requests/min unidentified, 200/min for a compliant User-Agent, 2,000/min for established authenticated editors, with bots exempt. WDQS allows 60 s of query time per minute per User-Agent+IP and 5 parallel queries per IP.

### Cited Findings
**Update channels**
- EventStreams base URL: `https://stream.wikimedia.org/v2/stream/`. Depending on the stream, "between 7 and 31 days of history" are available. You can replay with the `since` parameter (ISO-8601) or the `Last-Event-ID` header. — [EventStreams HTTP Service](https://wikitech.wikimedia.org/wiki/Event_Platform/EventStreams_HTTP_Service)
- EventStreams limits and handling: the connection is terminated after a 15-minute timeout, and clients should auto-reconnect with `Last-Event-ID`. There is no server-side filtering, so filtering happens in the client. Discard events where `meta.domain === 'canary'`. Suggested Python clients are `requests-sse` and `pywikibot`. — [EventStreams HTTP Service](https://wikitech.wikimedia.org/wiki/Event_Platform/EventStreams_HTTP_Service)
- The live EventStreams OpenAPI spec (service version 0.20.0, observed 2026-09-25) lists these streams, among others:
  - `mediawiki.recentchange`, `recentchange`
  - `mediawiki.revision-create`, `revision-create`
  - `mediawiki.page_change.v1`
  - `mediawiki.page-create`, `mediawiki.page-delete`, `mediawiki.page-undelete`, `mediawiki.page-move`
  - `mediawiki.page-links-change`, `mediawiki.page-properties-change`, `mediawiki.revision-visibility-change`
  - `rdf-streaming-updater.mutation.v2`, `rdf-streaming-updater.mutation-main.v2`, `rdf-streaming-updater.mutation-scholarly.v2`
  - `mediainfo-streaming-updater.mutation.v2`
  - several ML prediction streams, for example `mediawiki.page_revert_risk_wikidata_prediction_change.v1`

  — [EventStreams spec](https://stream.wikimedia.org/?spec)
- `Last-Event-ID` carries Kafka topic/partition/offset triples. For `since`: "If the timestamp given does not have any corresponding offsets, it will be ignored, and the data will begin streaming from the latest position". This means a client that falls behind the retention window silently skips events. — [EventStreams spec](https://stream.wikimedia.org/?spec)
- The docs say "The list of streams that are available will change over time". — [EventStreams HTTP Service](https://wikitech.wikimedia.org/wiki/Event_Platform/EventStreams_HTTP_Service)
- `mediawiki.page_change.v1` is a versioned stream. Its `performer` field is no longer required and is omitted, for example, for suppressed RevisionDelete. — [wikitech-l, via mail-archive](https://www.mail-archive.com/wikitech-l@lists.wikimedia.org/msg96169.html)
- Recent changes API (`list=recentchanges`):
  - `rclimit` is "between 1 and 500".
  - `rcstart` "may not be more than [$wgRCMaxAge] into the past, which on Wikimedia wikis is 30 days". The same fetch also saw a "90 days" mention elsewhere on the page, so treat 30 days as the operative Wikimedia value.
  - Rows can be inserted "slightly out of order", so add overlap between polls.

  — [API:RecentChanges](https://www.mediawiki.org/wiki/API:RecentChanges)
- Wikidata's own guidance for each access route: — [Wikidata:Data access](https://www.wikidata.org/wiki/Wikidata:Data_access)
  - **EventStreams:** "Real-time updates or maintaining local copies". It covers all wikis, so filter Wikidata client-side.
  - **Linked Data Interface:** `Special:EntityData/Q{ID}` supports `.json/.rdf/.ttl/.nt/.jsonld`, `?revision=` for a specific version, and `?flavor=dump|simple|full`. Best "for individual entities already known to you".
  - **Action API:** "up to 50 entities per request".
  - **Wikibase REST API:** "still under development" but meant to "functionally replace the Action API".
  - **Dumps:** for "very large" result sets.
- Observed live: `Special:EntityData/Q42.json` returned `lastrevid: 2547848680` and `modified: 2026-09-20T02:17:41Z` alongside labels, claims and sitelinks. — [Special:EntityData/Q42.json](https://www.wikidata.org/wiki/Special:EntityData/Q42.json)

**Dumps**
- Formats: — [Wikidata:Database download](https://www.wikidata.org/wiki/Wikidata:Database_download)
  - JSON (recommended): one entity per line inside a single array, under the Stable Interface Policy.
  - RDF: Turtle and N-Triples, as "all" and "truthy" (best-rank only) variants, plus lexemes.
  - XML dumps: "format of the JSON data embedded in the XML dumps is subject to change".
  - Cadence: "dumps are being created on a weekly basis".
  - Incremental dumps at `/other/incr/wikidatawiki/` "cover last 24 hours of changes".
  - Licence: main/Property/Lexeme/EntitySchema data is CC0.
  - The example torrent `wikidata-20240101-all.json.gz` is 130.53 GiB.
- Tools listed on the same page — [Wikidata:Database download](https://www.wikidata.org/wiki/Wikidata:Database_download):
  - JsonDumpReader (PHP)
  - gitlab.com/tozd/go/mediawiki (Go)
  - WDSub (Scala)
  - simple-wikidata-db (Python)
  - qwikidata (Python)
  - wd2sql (Rust), which produces a "90% smaller SQLite database"
  - WDumper, for custom filtered RDF dumps
- Current sizes (listing observed 2026-09-25): — [dumps.wikimedia.org/wikidatawiki/entities](https://dumps.wikimedia.org/wikidatawiki/entities/)

  | File | Bytes | ≈ Size | Dated |
  |---|---|---|---|
  | `latest-all.json.gz` | 156,251,408,231 | 156.3 GB | 24-Sep-2026 |
  | `latest-all.json.bz2` | 103,222,517,992 | 103.2 GB | |
  | `latest-all.ttl.gz` | 154,097,496,855 | 154.1 GB | |
  | `latest-all.nt.gz` | 253,694,082,314 | 253.7 GB | |
  | `latest-truthy.nt.bz2` | 43,458,740,693 | 43.5 GB | |
  | `latest-lexemes.json.gz` | 644,771,563 | 0.64 GB | |

  The newest dated directories are 20260918, 20260921 and 20260923.
- Observed with an HTTP range request on the first 400 KB of `latest-all.json.gz` (2026-09-25): — [latest-all.json.gz](https://dumps.wikimedia.org/wikidatawiki/entities/latest-all.json.gz)
  - The file is multi-member gzip: the first member holds only `[\n`.
  - Each following line is one entity. The first is Q31, 867,609 characters long.
  - Each entity line ends with `"lastrevid":…,"modified":…`, for example Q31 `lastrevid 2548173641`, `modified 2026-09-21T16:13:48Z`.
  - The server honoured the byte range.
- Incremental XML dumps are produced daily (directories 20260920 to 20260924 observed). For example, `wikidatawiki-20260923-pages-meta-hist-incr.xml.bz2` is 1,241,549,266 bytes and the stubs file is 33,322,592 bytes. An md5sums file is published. — [dumps.wikimedia.org/other/incr/wikidatawiki](https://dumps.wikimedia.org/other/incr/wikidatawiki/)
- Wikimedia Enterprise also snapshots Wikidata: — [Enterprise Snapshot API docs](https://enterprise.wikimedia.com/docs/snapshot/)
  - An `items` bundle of "~76 million records, ~105 GB" and a `properties` bundle of about 16,000 records.
  - The free tier gets monthly snapshots.
  - "<1%" of records are duplicates; resolve them by the highest `version.identifier`.
  - No diff or incremental snapshots are mentioned.

**Query services**
- WDQS graph split: on **9 May 2025** WDQS was split. `query.wikidata.org` serves the "main graph". `query-scholarly.wikidata.org` serves scholarly articles, meaning items with non-deprecated "instance of: scholarly article" or "publication type of scholarly work". `query-legacy-full.wikidata.org` was to be available "until December 2025". — [WDQS graph split](https://www.wikidata.org/wiki/Wikidata:SPARQL_query_service/WDQS_graph_split)
  - Reasons given: the graph is "over 16 billion triples" and grows about "1 billion triples per year"; reloads take "between 1 and 2 months"; timeouts were increasing.
  - Queries that need both graphs must use SPARQL federation.
- WDQS limits: — [WDQS User Manual](https://www.mediawiki.org/wiki/Wikidata_Query_Service/User_Manual)
  - 60 s query timeout.
  - "One client (user agent + IP) is allowed 60 seconds of processing time each 60 seconds".
  - 30 error queries per minute.
  - "5 parallel queries per IP".
  - Excess requests get HTTP 429 with `Retry-After`; clients that ignore 429s can be "temporarily banned".
  - Clients that don't follow the User-Agent policy "may be blocked completely".
- QLever: — [QLever GitHub](https://github.com/ad-freiburg/qlever)
  - A graph database implementing RDF and SPARQL, with "full SPARQL 1.1 … including … updates".
  - Claims to scale "to more than a trillion triples on a single commodity machine".
  - Apache 2.0 licence; public demos at qlever.dev.
- QLever on Wikidata (page last edited 8 February 2025): — [Wikidata: Benchmarking/QLever](https://www.wikidata.org/wiki/Wikidata:Scaling_Wikidata/Benchmarking/QLever)
  - Indexing "takes about 4 hours" and uses "about 20 threads and 40GB of memory" in its first phase.
  - Recommended machine: "12-core Ryzen CPU with 64GB of memory". The index is "about 450GB".
  - Built from `wikidata-20241028-all-BETA.ttl.bz2`.
  - Older docs cited about 20 hours for a full build (search snippet; superseded). — [QLever wikidata.md (older fork docs)](https://github.com/Buchhold/QLever/blob/master/docs/wikidata.md)

**Etiquette, rate limits and authentication (2026)**
- New global API rate limits were announced on **2 March 2026** (Jonathan Tweed, WMF). — [wikitech-l announcement](https://lists.wikimedia.org/hyperkitty/list/wikitech-l@lists.wikimedia.org/thread/GBFZTN3A233IR6F4HEENCIUCVI2ZH6YB/)
  - Early March 2026: "low limits" for anonymous API requests from outside Toolforge/WMCS and from browsers.
  - Early April 2026: "higher limits" for identified traffic, meaning OAuth 2.0 or session cookies, a policy-compliant User-Agent, or bot rights.
  - Bot-group accounts, known clients and Toolforge/WMCS are exempt.
- Current tiers, in requests per minute (the page says they are "new in 2026 and subject to experimentation and change"): — [Wikimedia APIs/Rate limits](https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits)

  | Client | Limit |
  |---|---|
  | Unidentified (IP only) | 10 |
  | Browser | 200 |
  | User-Agent-compliant, unauthenticated | 200 |
  | Authenticated new/few-edit users | 200 |
  | Authenticated established editors | 2,000 |
  | Bot-flagged, extended global rights, WMCS, known clients | exempt |

  - The limits apply to the Action API and REST APIs and are "enforced per user".
  - Excess requests get 429, usually with `Retry-After`.
  - Enterprise APIs are the route for higher volume.
- The rate-limits FAQ adds: — [Rate limits FAQ](https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits/FAQ)
  - WDQS is not yet in this framework ("We intend to explore the feasibility of cost-based or concurrency limits for Wikidata Query Service").
  - OAuth 2.0 is preferred; single-user bots may use bot passwords or owner-only tokens.
  - For substantial data needs "it's likely that the project should be using dumps".
  - Automated traffic was around 40% of page views in early 2026.
- Robot policy (last edited 16 March 2026): — [Robot policy](https://wikitech.wikimedia.org/wiki/Robot_policy)
  - Action API, unauthenticated: concurrency 1, below 5 req/s. Authenticated: concurrency 3, 10 req/s.
  - REST API, unauthenticated: concurrency 3, below 5 req/s. Authenticated: 10 req/s.
  - Crawling: fewer than 10 concurrent requests, average below 20 req/s.
  - Use dumps for bulk; bots that evade limits "may be blocked".
- User-Agent policy (last edited 27 March 2026): — [Policy:User-Agent policy](https://foundation.wikimedia.org/wiki/Policy:User-Agent_policy)
  - Format `<client name>/<version> (<contact information>) <library>/<version>`, for example `CoolBot/0.0 (https://example.org/coolbot/; coolbot@example.org) generic-library/0.0`.
  - Generic agents such as `python-requests` may be blocked, with HTTP 403.
- API:Etiquette: — [API:Etiquette](https://www.mediawiki.org/wiki/API:Etiquette)
  - Make requests serially.
  - Batch with `|`.
  - Send `Accept-Encoding: gzip`.
  - Use `maxlag` for non-interactive tasks.
  - Use GET for reads; if POSTing a read, send `Promise-Non-Write-API-Action: true`.
  - Check your limits with `meta=userinfo&uiprop=ratelimits`.
  - Use exponential backoff on `ratelimited` errors.
- Maxlag: — [Manual:Maxlag parameter](https://www.mediawiki.org/wiki/Manual:Maxlag_parameter)
  - Recommended value is `maxlag=5`, which is the Pywikibot default.
  - A lag error comes back as **HTTP 200** with error code `maxlag`, plus `Retry-After` and `X-Database-Lag` headers.
  - Pause "at least 5 seconds" before retrying.
- The API Portal (`api.wikimedia.org`) is being retired: — [API Portal/Deprecation](https://wikitech.wikimedia.org/wiki/API_Portal/Deprecation)
  - The portal wiki went read-only on 15 June 2026.
  - Its Core, Feed, Link Recommendation and Page Description endpoints are deprecated gradually from July 2026 to June 2027.
  - Replacements live on the wiki domain, for example `{wiki}/w/rest.php/v1/page/{title}`.

**acatalogue today (local code)**
- User-Agent is `acatalogue/0.1 (+https://github.com/virideanil/acatalogue; knowledge catalogue builder)`: a URL, but no email address and no library token. Requests are paced at `min_interval = 1.0` s. — [fetch.py L16, L24–30](/home/user/acatalogue/acatalogue/fetch.py)
- Requests send `Accept-Encoding: identity`. Retries happen on HTTP 429/5xx and honour `Retry-After`. No `maxlag` is sent. — [fetch.py L49–82](/home/user/acatalogue/acatalogue/fetch.py)
- Entities come from `wbgetentities` in batches of 50 with `props=labels|descriptions|aliases|sitelinks`, so no claims are fetched. Labels are looked up on WDQS in batches of 150. — [sources/wikidata.py L131–198](/home/user/acatalogue/acatalogue/sources/wikidata.py)

### Inferences
- The API cannot sustain "all of Wikidata". Even using Enterprise's figure of ~76M items, `wbgetentities` at 50 ids per call needs about 1.5M calls. At the 200/min identified tier that is about 5.3 days of nonstop requests, which contradicts the FAQ and Robot policy advice to use dumps. The weekly JSON dump is the only reasonable baseline.
- The 429s acatalogue saw on a shared IP fit limits keyed partly by IP: WDQS allows "5 parallel queries per IP", and the unidentified tier is "IP only". Authenticating with an OAuth 2.0 owner-only consumer should move Action API calls to per-account limits (200/min, or 2,000/min for an established editor account). The docs do not say exactly how unauthenticated clients are keyed; see Gaps.
- The Robot policy's "<5 req/s" and the 200/min tier (about 3.3 req/s) overlap. Follow the stricter one. acatalogue's 1 req/s serial pacing is already compliant, so its problem is shared-IP attribution, not speed.
- Recommended subset sync, all standard-library Python:
  1. **Baseline.** Stream `latest-all.json.gz` once and gunzip it member by member with `zlib` (it is multi-member, as observed). Keep the lines whose QID is in the tracked set, or all lines. Store each line's exact bytes, its SHA-512, the dump URL and date, and its `lastrevid`/`modified`.
  2. **Delta.** Subscribe to `mediawiki.recentchange` (or `mediawiki.page_change.v1`) and filter on `wiki == wikidatawiki` and the tracked QIDs. Persist `Last-Event-ID` in the corpus metadata and reconnect every ≤15 min.
  3. **Content.** For each changed `(QID, revid)`, GET `Special:EntityData/Q….json?revision=N&flavor=dump`. The response is immutable per revision, so it is naturally content-addressable.
  4. **Gap detection.** If the first replayed event is newer than the requested `since`, events were lost. Fall back to `list=recentchanges` (30 days), else re-baseline from the next weekly dump.
  5. **Weekly audit.** Compare the new dump's `lastrevid` with the local copy. Any mismatch is a missed event.
- The daily incremental XML dumps (~1.24 GB bz2/day) are a file-based alternative to EventStreams. They give sealed, checksummed daily files, which suits exact-byte provenance, but their embedded JSON format "is subject to change".
- The `rdf-streaming-updater.mutation-main.v2` and `-scholarly.v2` streams mirror the graph split. They could feed a local RDF engine such as QLever, but I did not research their schema.

### Gaps
- How unauthenticated "identified" traffic is keyed (IP, or IP+User-Agent) under the 2026 limits is not documented in the pages I fetched.
- Whether `Special:EntityData` requests count against the new API-gateway limits is not stated. It is a special page, not an API endpoint.
- I did not verify whether the entity-dump directories publish md5/sha1 files for the JSON dumps (the incremental dumps do), or the exact dated file naming in 2026 directories.
- Event volume of `recentchange` / `page_change.v1` (events per second, wikidatawiki share), and the deprecation status of the legacy stream names that exist alongside the `mediawiki.*` ones, were not found.
- I did not confirm whether `query-legacy-full.wikidata.org` was actually shut down after December 2025.
- I found no documentation of QLever's public endpoint usage limits or of incremental update support for a Wikidata mirror.

## 2. Wikipedia article text in many languages (dumps, REST API, Enterprise) and CC BY-SA obligations for a redistributed dataset

### Takeaway
In 2026, bulk multilingual text comes from dumps, not APIs. The main sources are:
- the XML dumps (enwiki `pages-articles-multistream.xml.bz2` is about 26.8 GB, with runs on the 1st of each month in 2026);
- the rebuilt weekly CirrusSearch index dumps, at a new location since January 2026;
- Wikimedia Enterprise snapshots (free tier: monthly, 30 snapshot requests and 50,000 on-demand requests a month; records include `abstract`, HTML and wikitext).

The Enterprise HTML dumps are no longer mirrored on dumps.wikimedia.org, and the api.wikimedia.org Core API is being retired. Reuse is under CC BY-SA 4.0:
- attribute with a URL or author list;
- include a licence notice and link;
- indicate modifications;
- license modifications under CC BY-SA 4.0 or later.

### Cited Findings
- Enterprise HTML dumps on dumps.wikimedia.org "were an experimental service that, as of 24 March 2025, are no longer replicated on this site". The 2025 archives stay available; current HTML is served through the Enterprise Snapshot and On-demand APIs. — [dumps.wikimedia.org/other/enterprise_html](https://dumps.wikimedia.org/other/enterprise_html/)
- Enterprise free-tier upgrade, published 2 June 2026: — [Enterprise blog: enhanced free API](https://enterprise.wikimedia.com/blog/enhanced-free-api/)
  - On-demand requests rose to 50,000 a month (from 5,000).
  - Snapshot requests rose to 30 a month (from 15).
  - Structured Contents snapshots, previously paid, are now free.
  - Snapshots are monthly; "the first monthly Snapshot run on 1 July 2026"; credits reset on the 1st.
- Enterprise Snapshot format: — [Enterprise Snapshot API docs](https://enterprise.wikimedia.com/docs/snapshot/)
  - A `.tar.gz` containing one `.ndjson`.
  - Fields include `name`, `identifier`, `abstract`, `date_modified`, `url`, `version.identifier`, `version.editor`, `article_body.html`, `article_body.wikitext`, `license[]` and `event`.
  - Namespaces are identified like `enwiki_namespace_0`.
  - Free tier: once a month on the 1st, "30 snapshot + 1,500 chunk downloads/month". Paid plans get weekly or daily.
- CirrusSearch dumps moved: `/other/cirrussearch/` is "no longer being updated" (DEPRECATED.txt dated 7 January 2026). The new location is `/other/cirrus_search_index/`. — [cirrussearch DEPRECATED.txt](https://dumps.wikimedia.org/other/cirrussearch/DEPRECATED.txt)
  - The old weekly job "would take 7 or 8 days to produce a weekly dump". The new orchestration "publishes the full dump approximately 12 hours after starting".
  - Dumps are "sharded into smaller files", for example into 1 GB chunks.
- New CirrusSearch location (observed 2026-09-25): weekly directories 20260830, 20260906, 20260913 and 20260920, with per-index subdirectories such as `index_name=enwiki_content/` and `index_name=enwiki_general/`. — [cirrus_search_index](https://dumps.wikimedia.org/other/cirrus_search_index/)
- The older CirrusSearch JSON format carried an `opening_text` field (lead text) per page. This is a search snippet describing the old format. — [dumps.wikimedia.org/other/cirrussearch](https://dumps.wikimedia.org/other/cirrussearch/)
- enwiki XML dumps (listing observed 2026-09-25): — [enwiki/latest](https://dumps.wikimedia.org/enwiki/latest/)
  - `pages-articles-multistream.xml.bz2`: 26,797,495,184 bytes (3 Sep 2026)
  - `pages-articles.xml.bz2`: 25,680,955,982 bytes
  - `pages-meta-current.xml.bz2`: 46,491,809,796 bytes
  - `page_props.sql.gz`: 470,958,111 bytes
  - `wbc_entity_usage.sql.gz`: 489,349,225 bytes
  - `all-titles-in-ns0.gz`: 109,282,359 bytes
- Visible enwiki run directories in 2026 are only 20260301, 20260401 … 20260901, the 1st of each month. — [dumps.wikimedia.org/enwiki](https://dumps.wikimedia.org/enwiki/)
- REST replacements for the retired Core API: `{wiki}/w/rest.php/v1/search/page` and `{wiki}/w/rest.php/v1/page/{title}`. Feeds stay at `{wiki}/api/rest_v1/feed/featured/...`. — [API Portal/Deprecation](https://wikitech.wikimedia.org/wiki/API_Portal/Deprecation)
- Licensing: — [Wikipedia:Reusing Wikipedia content](https://en.wikipedia.org/wiki/Wikipedia:Reusing_Wikipedia_content)
  - Text is CC BY-SA 4.0 and GFDL; text published before 15 June 2009 is also GFDL.
  - Attribution is "a) a hyperlink (where possible) or URL to the page or pages you are re-using", or a link to a stable conforming copy, or a list of all authors.
  - Include a licence notice linking to creativecommons.org/licenses/by-sa/4.0/.
  - "If you make modifications or additions … you must license them under the Creative Commons Attribution-Share-Alike License 4.0 or later".
  - "you must indicate in a reasonable fashion that the original work has been modified".
  - Fair-use media may not be fair use in another context.
- Enterprise's own site content is CC BY-SA 4.0; photo credits follow each creator's licence. — [Enterprise blog](https://enterprise.wikimedia.com/blog/enhanced-free-api/)
- acatalogue today: — [sources/wikipedia.py L30–34](/home/user/acatalogue/acatalogue/sources/wikipedia.py); [README](/home/user/acatalogue/README.md)
  - Intros come from the Action API TextExtracts module (`prop=extracts|info`, `exintro=1`, `explaintext=1`, 20 titles per request, `inprop=url`).
  - The README says every document stores its page URL and revision, and that redistributed Wikipedia text must carry attribution and the same licence.

### Inferences
- To scale intros to hundreds of languages, the weekly CirrusSearch index dumps are the most direct source, if the new sharded format still has `opening_text`. Enterprise snapshots are the provenance-rich alternative: they carry `abstract`, `version.identifier` and `license` per record, but free-tier cadence is monthly and an account is needed.
- Either way, acatalogue should seal the exact shard or tarball bytes, or the exact NDJSON line, keyed by SHA-512, rather than per-title API responses.
- acatalogue calls `en.wikipedia.org/w/api.php`, not api.wikimedia.org, so the portal retirement doesn't affect it. Any new REST code should target `{wiki}/w/rest.php/v1/`.
- For CC BY-SA compliance in a redistributed SQLite catalogue:
  - keep CC BY-SA text in a separately labelled table and export, with its own licence notice;
  - store per-passage page URL and revision ID;
  - add a modification notice, such as "segmented into passages; whitespace normalised". Splitting text into passages plausibly counts as modification.

### Gaps
- Whether the new `cirrus_search_index` shards keep `opening_text`, and their exact file format, was not verified.
- I did not fetch the Enterprise terms of service on redistributing snapshot content, or which languages the free Structured Contents tier covers.
- I found no official announcement explaining why only 1st-of-month enwiki runs are visible in 2026. This is an observation, not a documented cadence.
- How CC BY-SA 4.0 treats a database (adaptation vs. collection; sui generis database rights) was not researched from the legal code.
- The TextExtracts `exlimit` maximum is not sourced; the value 20 comes from acatalogue's own code.

## 3. OpenAlex in 2026: API keys, free-tier limits, snapshot availability, topics taxonomy and licence

### Takeaway
Since 13 February 2026, OpenAlex requires a free API key for real use. Usage is metered in dollars:
- $1/day free with a key; $0.10/day without;
- single-entity lookups are free;
- list+filter costs $0.10 per 1,000 calls; search $1 per 1,000; content $10 per 1,000;
- 100 requests/s maximum; 429 when the budget runs out, reset at midnight UTC.

The public CC0 snapshot is now **quarterly** (`s3://openalex`, JSONL ≈745 GB plus Parquet ≈770 GB, about 626M records), with daily snapshots for paid members. Topics form a four-level hierarchy of 4 domains, 26 fields, 252 subfields and 4,516 topics.

### Cited Findings
- Announcement of 14 January 2026 by Jason Priem: "API calls will require a key starting one month from today (Feb 13)". — [openalex-users announcement](https://groups.google.com/g/openalex-users/c/rI1GIAySpVQ)
  - Without a key: 100 credits/day, "fine for testing and demos but not for real work". With a key: 100,000 credits/day.
  - Initial costs: singleton 1 credit, list 10 credits. The announcement said these "aren't final".
  - The data "remains CC0 and free to download in its entirety any time".
- Current help centre (last updated 9 August 2026) — [OpenAlex example costs](https://help.openalex.org/access/example-costs/):
  - Single entity by ID or DOI: free.
  - List+filter: $0.10 per 1,000 calls.
  - Full-text search and semantic search: $1 per 1,000.
  - Content/PDF: $10 per 1,000.
  - Free allowance: $1/day with a key, $0.10/day without.
  - $1 buys "10,000 list+filter calls (yielding ~1,000,000 results)". A worked example: "All works from Harvard" took 8,707 calls, returned 870,627 results and cost $0.87.
  - This supersedes the January credit figures.
- Authentication: pass the key as `api_key=` or `Authorization: Bearer`. — [OpenAlex authentication](https://help.openalex.org/api/authentication/)
  - 429 comes from "exceeding your daily budget, or making more than 100 requests per second"; the budget resets at midnight UTC.
  - Hard limits: 100 OR-values per filter; `per_page` at most 100; `sample` at most 10,000; basic paging stops at 10,000 results, so use cursor paging.
- Pricing (updated 11 August 2026): — [OpenAlex pricing](https://help.openalex.org/access/pricing/)
  - Free: $1/day. Pay-as-you-go top-ups in $1 increments expire after 3 months.
  - Member: $5,000/yr ($20/day).
  - Member+: $10,000/yr ($100/day, includes "daily sync").
  - Partner: $20,000+/yr.
- Snapshot — [OpenAlex snapshot](https://help.openalex.org/access/snapshot/):
  - Public `s3://openalex`, free and needing no account; AWS Open Data covers about $70 of transfer per download.
  - Paid daily snapshot at `s3://openalex-snapshots`.
  - Two identical copies: JSON Lines (gzip, about 745 GB) and Parquet (snappy, about 770 GB), "about 626 million records" as of the September 2026 release.
  - Public cadence is **quarterly**, on the second Wednesday of January, April, July and October.
  - A works deletion log `deleted_ids.csv.gz` has shipped daily since 2026-08-15, and in the public bucket since 23 September 2026.
  - Entities cover works, authors, sources, institutions, publishers, funders, awards, topics, keywords, concepts, subfields, fields, domains, countries, languages, licences, SDGs and others.
- Older descriptions of a monthly snapshot of about 330 GB appear in search snippets from older OpenAlex docs pages. These are superseded by the pages above. The old `docs.openalex.org` pages now 301-redirect to help.openalex.org (observed). — [OpenAlex download to machine (older)](https://developers.openalex.org/download/download-to-machine); [AWS registry](https://registry.opendata.aws/openalex/)
- Snapshot format — [OpenAlex snapshot format](https://help.openalex.org/download/snapshot-format):
  - Layout `s3://openalex/data/{format}/{entity}/updated_date=YYYY-MM-DD/part_NNNN.*`.
  - Each partition "holds the records that last changed on that date", in parts of up to 400,000 records.
  - Per-entity manifests give `record_count`, `content_length` and per-file `url`/`meta`. "If the manifest is present, the data for that format is complete". This design "makes incremental updates cheap".
- Topics: — [OpenAlex topics](https://help.openalex.org/data/topics/)
  - Counts: 4 domains, 26 fields, 252 subfields, 4,516 topics.
  - Built with CWTS Leiden: citation clustering, then LLM-generated names and descriptions, then mapping to Scopus ASJC categories.
  - A deep-learning classifier assigns up to 3 topics per work, one of them `primary_topic`.
  - Topics have `keywords`, `siblings`, `created_date` and `updated_date`.
  - About 12% of works lack topics ("39.6M of 322M as of mid-2026").

### Inferences
- acatalogue's refusal ("daily budget exhausted") fits the keyless $0.10/day, which is about 1,000 list calls. A free key alone fixes this for acatalogue's scale.
- Fetching the whole topic hierarchy is cheap with a free key. At `per_page=100` it takes about 51 list calls: 46 for topics, 3 for subfields, 1 each for fields and domains. That costs about $0.005 of the $1/day, and singleton look-ups are free.
- The snapshot's `updated_date` partitions, manifests (`record_count`, `content_length`) and deletion log map naturally onto sealed, dated corpora. Each part file is sealed with its SHA-512 and the manifest, and a later release only needs the new partitions. It is quarterly for free users, so the API with a key covers freshness between releases.
- OpenAlex says its data is CC0. The topic hierarchy is mapped onto Elsevier's ASJC scheme, so confirm that the ASJC-derived labels carry no extra terms before redistributing them.

### Gaps
- No explicit licence or download location was found for the topic-taxonomy file itself. The GitHub repo `ourresearch/openalex-topic-classification` appeared in search results but was not fetched. Topic ID stability and versioning since 2024 are also not documented in what I read.
- Keyless behaviour after the budget runs out: the help centre says 429. One summary of the January announcement mentioned a different code, which I treat as unverified.
- Merge handling (`merged_ids`) for non-work entities was not detailed in the pages I fetched.

## 4. Versioned-data tooling: Dolt/DoltLite, DVC, lakeFS, Hugging Face (Xet, dataset cards), Git LFS; fit for a SQLite-centred catalogue that must never lose history

### Takeaway
DoltLite (beta since 31 August 2026) is the only one of these tools that versions SQLite itself. Its database files are not SQLite page files, and it needs a custom library. Dolt proper is a separate database engine. DVC (Apache 2.0, stewarded by lakeFS since November 2025) and Git LFS version files. lakeFS switched to the Business Source Licence from v1.87.0 (22 September 2026). Hugging Face's Xet backend deduplicates at the chunk level (about 64 KB) and suits publishing dated snapshots, but it allows destructive history squashing. acatalogue's sealed corpora, git-tracked seeds and hash-chained ledger already guarantee no-loss history. These tools are best used for distribution or derived diffs, not as the system of record.

### Cited Findings
- Dolt is "a SQL database that you can fork, clone, branch, merge, push and pull just like a Git repository", built on the prolly tree, "a content-addressed B-tree". — [Dolt on GitHub](https://github.com/dolthub/dolt); [dbdb.io: Dolt](https://dbdb.io/db/dolt)
- DoltLite beta (31 August 2026, v0.50.0) — [DoltHub blog: DoltLite Beta](https://www.dolthub.com/blog/2026-08-31-doltlite-beta/):
  - "a fork of SQLite" whose "B-tree layer is swapped out for a Prolly Tree backed by a single file chunk store".
  - Supports branches, merges, diffs, rebases, cherry-picks, resets, and push/pull/clone/fetch to DoltHub or a custom remote.
  - File-backed databases are "at parity on reads and 10% slower on batched writes". Small autocommit writes are "3.1X slower than SQLite" (~125 µs vs ~400 µs).
  - The storage format is now "stable".
- DoltLite repo — [dolthub/doltlite](https://github.com/dolthub/doltlite):
  - Apache-2.0 licence.
  - Exposes SQLite's `sqlite3_*` API plus `doltlite.h`, so you must link `libdoltlite`.
  - "Stock SQLite files are detected by their header and opened on SQLite's original B-tree engine". But "A DoltLite database is one content-addressed chunk-store file, not SQLite pages".
  - Functions include `dolt_commit`, `dolt_log`, `dolt_diff_<table>`, `dolt_history_<table>`, `dolt_blame_<table>`, `dolt_merge` and `dolt_tag`.
  - "No rollback journal, WAL, or shared-memory sidecars".
- DoltHub reports that for many similar JSON documents Dolt uses "significantly less storage space than SQLite" thanks to deduplication and compression (search summary of the post). — [DoltHub: JSON Showdown Dolt vs SQLite](https://www.dolthub.com/blog/2024-11-18-json-sqlite-vs-dolt/)
- lakeFS acquired the DVC open-source project from Iterative, announced **18 November 2025**. DVC is positioned as a "lightweight Git-based tool for small-to-medium data science projects"; lakeFS "supports enterprise-grade version control for petabyte-scale data lakes". — [DVC blog: DVC joins lakeFS](https://dvc.org/blog/dvc-joins-lakefs-your-questions-answered/); [lakeFS press release](https://lakefs.io/media-mentions/lakefs-acquires-dvc-uniting-data-version-control-pioneers/)
- lakeFS licence change — [lakeFS blog: BSL](https://lakefs.io/blog/lakefs-business-source-license/):
  - From **v1.87.0 (22 September 2026)** lakeFS moved from Apache 2.0 to the Business Source License. Each release converts to Apache 2.0 "4 years after it ships".
  - "You cannot use a modified lakeFS system in production", nor offer it as a service to anyone outside your organisation.
  - "DVC stays under Apache 2.0 as well, with no changes at all".
- Hugging Face Xet — [HF Xet deduplication](https://huggingface.co/docs/hub/xet/deduplication); [HF Xet overview](https://huggingface.co/docs/hub/xet/index):
  - Content-defined chunking at "~64KB" per chunk. New chunks are grouped "into 64 MB blocks", each "stored once in a content-addressed store (CAS), keyed by its hash".
  - "when you … append rows to a dataset, only the modified portions need to be uploaded and stored".
  - Git LFS is still supported for backward compatibility.
- Hub storage and repo limits — [HF storage limits](https://huggingface.co/docs/hub/storage-limits):
  - Free accounts get "best-effort" public storage and 100 GB private. PRO gets up to 10 TB public.
  - Recommended: files under 200 GB (500 GB hard limit), under 100k files per repo, under 10k entries per folder.
  - The experience "starts to degrade after a few thousand" commits.
  - `super_squash_history` is "non-revertible" and removes LFS file history.
  - Large datasets require a dataset card; Parquet or WebDataset are preferred.
  - LFS pointers record `oid sha256:` and size.
- GitHub Git LFS maximum file size: 2 GB (Free and Pro), 4 GB (Team), 5 GB (Enterprise Cloud). — [GitHub Docs: About Git LFS](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-git-large-file-storage)

### Inferences
- **Fit for acatalogue:**

  | Tool | Fit |
  |---|---|
  | git (seeds) | Correct already: small, reviewed TSV text with line diffs. |
  | Sealed SQLite corpora + SHA-512 + ledger | Already content-addressed and append-only. The best system of record under stdlib-only. |
  | HF dataset repo (Xet) | Good *mirror and distribution channel* for corpora and build snapshots, with dataset card and Parquet export. Never super-squash; record the HF commit SHA in the ledger. |
  | Git LFS on GitHub | Only for small corpora (2 GB/file on free). Wikidata-dump-derived shards will exceed it. |
  | DVC | Apache 2.0 and file-level. Adds a dependency and largely duplicates acatalogue's manifest+ledger. Optional. |
  | lakeFS | BSL since v1.87.0 and aimed at object-store data lakes. Avoid as a core dependency of an open project. |
  | DoltLite | Attractive for branch/diff of the *curated* layer or for build-to-build diffs, but beta, needs a custom native library (breaks stdlib-only), and its files can't be opened by stock `sqlite3`. Revisit as an optional derived view. |
- Sealed corpora never change, so Xet's chunk dedup mainly helps when a new dated corpus repeats bytes from an older one, such as identical entity lines. For rebuilt catalogue files, dedup depends on page layout and may be modest. This is an inference; I did not measure it.

### Gaps
- DoltLite Python bindings and storage overhead numbers; the current DVC version; Git LFS storage/bandwidth billing; the details of HF dataset revisions and tags. None of these were fetched.
- No measurement of Xet dedup ratios on successive SQLite builds.

## 5. Curation workflows at scale: constraints, Mix'n'match, the Reconciliation API, GO/OBO GitHub curation, review queues and agreement

### Takeaway
Mature projects keep machine proposals and human decisions in separate, auditable states:
- Mix'n'match separates "preliminarily matched" (a system guess awaiting a person) from "fully matched" (a user's decision, written to Wikidata as that user's edit).
- The Reconciliation API separates a candidate's `score` and `features` from the service's `match` assertion.
- Wikidata constraints are data on properties, with mandatory or suggestion status and explicit exceptions, surfaced as reports.
- GO and other OBO ontologies require a ticket, a branch, CI checks and a second reviewer for every change.

Agreement between reviewers should be measured with chance-corrected coefficients such as kappa or alpha.

### Cited Findings
- Wikidata property constraints are statements on properties using `property constraint (P2302)`. — [Help:Property constraints portal](https://www.wikidata.org/wiki/Help:Property_constraints_portal)
  - Types include single-value (Q19474404), distinct-values (Q21502410), format (Q21502404), value-type (Q21510865), subject type (Q21503250), one-of and conflicts-with.
  - `constraint status (P2316)` marks a constraint as mandatory (Q21502408) or suggestion (Q62026391).
  - Exceptions are listed with `exception to constraint (P2303)`.
  - Violations show on Special:ConstraintReport, through the WikibaseQualityConstraints extension (on entity pages for logged-in users), and in KrBot database reports.
- Ferranti, de Souza, Ahmetaj and Polleres (Semantic Web Journal 15(6), 2024) found SHACL-Core too weak to express all Wikidata constraint types. They provide SPARQL queries detecting violations for "all 32 current Wikidata constraint types", and discuss the limits of evaluating them on the public endpoint at scale. — [SWJ / SAGE: Formalizing and validating Wikidata's property constraints](https://journals.sagepub.com/doi/10.3233/SW-243611); [code](https://github.com/nicolasferranti/wikidata-constraints-formalization)
- Mix'n'match entry states: — [Mix'n'match/Manual](https://meta.wikimedia.org/wiki/Mix'n'match/Manual)
  - "Fully matched": "a user has matched this catalogue entry to a Wikidata item".
  - "Preliminarily matched": "the system has guessed one or more possible match … but a person needs to verify or reject it".
  - "Not applicable": duplicate, placeholder, redirect or off-topic.
  - "Unmatched": no automated suggestion.
  - "Not on Wikidata" is deprecated.
  - Confirmed matches automatically update Wikidata and "show up as an edit in your contributions".
  - Catalogues are imported from a spreadsheet or a scraper. The manual says "over 2,500 catalogues"; one search snippet claimed over 5,800 datasets but I could not confirm its source.
- Reconciliation Service API versions — [v0.1](https://www.w3.org/community/reports/reconciliation/CG-FINAL-specs-0.1-20230321/); [v0.2](https://w3.org/community/reports/reconciliation/CG-FINAL-specs-0.2-20230410); [1.0-draft](https://reconciliation-api.github.io/specs/1.0-draft/):
  - v0.1 (W3C Entity Reconciliation CG Final Report, 21 March 2023) documents the API "as implemented in OpenRefine 2.8 to 3.2".
  - v0.2 (Final CG Report, 10 April 2023; editors Delpeuch, Pohl, Steeg, Guidry and Suominen).
  - 1.0-draft adds a service manifest and batched POST queries to `/match`.
  - In 1.0-draft, candidates carry `id`, `name`, `type` and `match` (boolean), with optional `description`, `score`, `features` and `image`. `match` means "whether the service considers this candidate good enough to be chosen as a correct match".
  - 1.0-draft also defines optional `/suggest/*`, `/preview` and `/extend` services, RFC 6570 URI templates, mandatory CORS, and changed query/response formats.
- Gene Ontology tracks ontology changes on the `go-ontology` GitHub tracker (new terms, definitions, hierarchy position, subsets) and annotation problems on `go-annotation`. — [GO: How to submit requests](https://geneontology.org/docs/how-to-submit-requests/)
- The ODK editors' workflow, used by OBO ontologies: — [ODK Editors Workflow (COB)](https://obofoundry.org/COB/odk-workflows/EditorsWorkflow/); [Cell Ontology](https://obophenotype.github.io/cell-ontology/odk-workflows/EditorsWorkflow/)
  - "no change to the ontology should be performed without a good ticket".
  - Use a feature branch per issue and a PR citing "fixes #23".
  - ODK tests run in GitHub Actions; "Once all the automatic tests have passed, it is important to put a second set of eyes on the pull request".
- Artstein & Poesio (Computational Linguistics 34(4):555–596, 2008) survey agreement coefficients (Cohen's kappa, Scott's pi, Krippendorff's alpha). They argue that weighted, alpha-like coefficients may suit many annotation tasks better. — [ACL Anthology J08-4004](https://aclanthology.org/J08-4004/)

### Inferences
- **Proposal and decision states.** acatalogue should hold proposals in a derived table that is reproducible from sealed corpora and never hand-edited. Decisions live in reviewed TSV seeds. The states would mirror Mix'n'match:
  - `unmatched`
  - `proposed` (machine: method, score, features)
  - `accepted` / `rejected` / `not_applicable` (human: reviewer, date, note)

  The build should refuse to publish an `exactMatch` that has no decision row.
- **Reconciliation API shape.** Shaping proposals as 1.0-draft candidates (`id`, `name`, `type`, `score`, `match`, `features`) buys two things. acatalogue can consume any reconciliation service. It can also expose its own `/reconcile` endpoint, so OpenRefine users can reconcile their data against the acatalogue compendium.
- **Auto-accept.** Allow it only when `match` is true, the label is exact and unique, and the type constraint holds. Still record it as `method=auto:<rule>` with an empty reviewer, and include it in audit samples.
- **Constraints.** Adopt Wikidata-style constraints as data:
  - single-value: one exactMatch QID per concept;
  - distinct-values: one concept per QID;
  - type/value-type: concept kind against P31/P279 of the QID;
  - format: `^Q[1-9][0-9]*$`.

  Give each a mandatory or suggestion status and an explicit exception list. Report violations from `acat verify` as a work queue, as KrBot and ConstraintReport do.
- **Measure agreement.** Double-review a random sample, say 50–100 decisions per batch, and compute Cohen's kappa or Krippendorff's alpha. Both are easy in the standard library. Use the result to set auto-accept thresholds.
- **Adopt the GO/ODK practice.** One issue per curation change, a PR with CI running `acat verify` and the constraint report, and a second reviewer.

### Gaps
- No quantitative data found on Wikidata's constraint-violation backlog or review throughput, or on KrBot report cadence.
- I did not confirm the current Mix'n'match catalogue count (conflicting figures) or the hosted Wikidata reconciliation endpoint and its limits.

## 6. SQLite at scale (limits, FTS5, WAL, concurrency, ATTACH sharding), when to use DuckDB/Parquet, and content-addressed storage

### Takeaway
SQLite's hard limits do not bind at Wikidata scale: 281 TB per database, a 1,000,000,000-byte default BLOB limit, and 10 attached databases by default (125 maximum). What binds is:
- a single writer at a time;
- WAL behaviour for huge transactions (slower above ~100 MB, may fail above ~1 GB);
- FTS5 index size: `detail=full`, `column` and `none` gave 743, 340 and 134 MiB on a 1,636 MiB corpus;
- full-rebuild time.

DuckDB can ATTACH SQLite files directly for analytics, and Parquet is the preferred distribution format on the HF Hub. Content addressing is the common pattern for deduplication plus integrity: hash-keyed chunks and blocks in Xet, prolly trees in Dolt, sha256 OIDs in Git LFS.

### Cited Findings
- SQLite limits — [SQLite limits](https://www.sqlite.org/limits.html):
  - Maximum database size is about 2.8e14 bytes (281 TB) with 64 KiB pages.
  - `SQLITE_MAX_PAGE_COUNT` is 4,294,967,294 by default since 3.45.0.
  - Default maximum string/BLOB length is 1,000,000,000 bytes (absolute maximum 2,147,483,645).
  - `SQLITE_MAX_ATTACHED` defaults to 10, with a hard upper limit of 125.
  - Maximum columns: 2,000 by default (up to 32,767).
  - Practical row ceiling is about 2e13.
- WAL — [SQLite WAL](https://www.sqlite.org/wal.html):
  - Readers and writers don't block each other, but "there can only be one writer at a time".
  - Auto-checkpoint happens at 1,000 pages.
  - Checkpoint starvation: with continuous overlapping readers, "the WAL file will grow without bound".
  - WAL doesn't work over network filesystems.
  - For transactions above about 100 MB, rollback journal modes "will likely be faster". Above a gigabyte, "WAL mode may fail with an I/O or disk-full error".
  - Read-only WAL databases can be opened with the `immutable` parameter, among other ways.
  - The WAL-reset bug affects versions 3.7.0 through 3.51.2 and is fixed in **3.51.3 (2026-03-13)**. It needs concurrent writes and checkpoints from separate connections, and is very rarely observed.
- FTS5 — [SQLite FTS5](https://www.sqlite.org/fts5.html):
  - Table types:
    - External-content tables store only index entries, saving "significant database space", but you must keep them consistent yourself, for example with triggers.
    - Contentless tables (`content=''`) don't support UPDATE/DELETE.
    - `contentless_delete=1` tables support DELETE and REPLACE.
  - Index size by `detail` on a 1,636 MiB email corpus: 743 MiB with `detail=full`, 340 MiB with `column`, 134 MiB with `none`. `column` and `none` lose phrase and NEAR queries.
  - `columnsize=0` saves space.
  - Trigram tokenizer: case-sensitive and `remove_diacritics` options. It matches nothing shorter than 3 characters. With `detail=none` or `column`, full-text query tokens are limited to 3 characters and LIKE/GLOB is slower.
  - Merge controls: `optimize`, `merge`, `automerge` (default 4), `crisismerge` (default 16), `pgsz` (default 4050).
  - `secure-delete` needs FTS5 from SQLite 3.42.0 or later to read afterwards.
- DuckDB's SQLite extension — [DuckDB SQLite extension](https://duckdb.org/docs/current/core_extensions/sqlite.html):
  - `ATTACH 'file.db' (TYPE sqlite)` queries SQLite tables in place.
  - SQLite's weak typing can clash with DuckDB's strict types; `SET sqlite_all_varchar = true` avoids that.
  - It supports writes (CREATE, INSERT, UPDATE, DELETE, ALTER, DROP). "Only a single thread or process can write to the database at one time."
- The HF Hub favours Parquet and WebDataset for large datasets, and its viewer works best with them. — [HF storage limits](https://huggingface.co/docs/hub/storage-limits)
- Content-addressed patterns — [HF Xet deduplication](https://huggingface.co/docs/hub/xet/deduplication); [Dolt](https://github.com/dolthub/dolt); [dolthub/doltlite](https://github.com/dolthub/doltlite); [HF storage limits (LFS pointer example)](https://huggingface.co/docs/hub/storage-limits):
  - Xet blocks are "stored once in a content-addressed store (CAS), keyed by its hash".
  - Dolt uses a "content addressable" prolly tree.
  - DoltLite is "one content-addressed chunk-store file".
  - Git LFS pointers carry `oid sha256:<hash>` and size.
- Local environment: Python 3.11.15 ships SQLite **3.45.1** (observed), which is older than the WAL-reset fix. acatalogue's corpora use SQLite Archive (`sqlar`) tables plus `meta`, `item` and `fetch_log` (observed in `corpora/*/corpus.sqlite`). — [README](/home/user/acatalogue/README.md)

### Inferences
- **Sharding.** Keep one sealed SQLite file per source and date, and shard very large sources, such as the full Wikidata dump, by QID range. Don't design queries that ATTACH more than 10 corpora at once; the build should iterate over shards instead.
- **Incremental builds.** The ~8 s full rebuild won't survive all of Wikidata. Make builds incremental:
  - key catalogue rows by source SHA-512;
  - rebuild only concepts whose inputs changed;
  - keep a periodic full rebuild as a verification job that compares hashes.
- **Build and serve.** Write the catalogue in `journal_mode=OFF` or `DELETE` into a temporary file, then rename it atomically. Serve readers with `mode=ro` or `immutable=1`. That avoids WAL's large-transaction risks and checkpoint starvation. If WAL is used with concurrent connections, bundle SQLite 3.51.3 or later.
- **FTS5.** Use external-content FTS5 over passages and labels, `detail=column` where phrase/NEAR search isn't needed, trigram only on labels (substring search), and run `optimize` after each build.
- **Analytics.** Use DuckDB as an optional analytics tool for audits and large joins, via ATTACH on SQLite or a Parquet export. Also export Parquet for distribution, while SQLite stays the canonical format.

### Gaps
- No published FTS5 benchmarks at 100M+ rows were found.
- I did not re-verify the `sqlar` compression details or the SQLite session extension and `sqldiff` for build-to-build changesets.
- The DuckDB docs page shown did not state a version.

## 7. Prioritized recommendations for acatalogue: incremental updates, review queues and scaling

### Takeaway
Build in this order:
1. Fetch hygiene: User-Agent, maxlag, gzip, OAuth, OpenAlex key.
2. A dump-based Wikidata baseline corpus.
3. An EventStreams → `EntityData?revision=` delta sync with gap detection.
4. A proposal/decision review queue with Reconciliation-API-shaped candidates, constraint reports and agreement sampling.
5. Incremental builds with external-content FTS5.
6. Dump- and snapshot-based Wikipedia and OpenAlex ingestion.
7. Publication of sealed corpora and builds to a Xet-backed dataset repo.

Throughout, git seeds, sealed corpora and the hash-chained ledger stay the system of record.

### Cited Findings (evidence summary)
- Bulk use of APIs is discouraged, and dumps are the sanctioned route. — [Rate limits FAQ](https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits/FAQ); [Robot policy](https://wikitech.wikimedia.org/wiki/Robot_policy); [Wikidata:Data access](https://www.wikidata.org/wiki/Wikidata:Data_access)
- Dump entity lines carry `lastrevid` and `modified`; the dump is multi-member gzip and range-readable (observed). — [latest-all.json.gz](https://dumps.wikimedia.org/wikidatawiki/entities/latest-all.json.gz)
- EventStreams replay spans 7–31 days, and `since` is silently ignored beyond retention. — [EventStreams HTTP Service](https://wikitech.wikimedia.org/wiki/Event_Platform/EventStreams_HTTP_Service); [EventStreams spec](https://stream.wikimedia.org/?spec)
- The recentchanges API goes back 30 days. — [API:RecentChanges](https://www.mediawiki.org/wiki/API:RecentChanges)
- 2026 rate tiers: 10/200/2,000 per minute, bots exempt. — [Wikimedia APIs/Rate limits](https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits)
- `maxlag=5` errors arrive as HTTP 200 with `Retry-After`. — [Manual:Maxlag](https://www.mediawiki.org/wiki/Manual:Maxlag_parameter)
- Mix'n'match states and the Reconciliation API `match` flag. — [Mix'n'match/Manual](https://meta.wikimedia.org/wiki/Mix'n'match/Manual); [Reconciliation 1.0-draft](https://reconciliation-api.github.io/specs/1.0-draft/)
- Constraints: mandatory or suggestion status, with exceptions. — [Help:Property constraints portal](https://www.wikidata.org/wiki/Help:Property_constraints_portal)
- Ticket + PR + second reviewer. — [ODK Editors Workflow](https://obofoundry.org/COB/odk-workflows/EditorsWorkflow/)
- Measuring agreement with kappa or alpha. — [Artstein & Poesio 2008](https://aclanthology.org/J08-4004/)
- OpenAlex: $1/day with a key, singletons free, quarterly CC0 snapshot with manifests. — [OpenAlex example costs](https://help.openalex.org/access/example-costs/); [OpenAlex snapshot](https://help.openalex.org/access/snapshot/)
- SQLite ATTACH, WAL and FTS5 facts. — [SQLite limits](https://www.sqlite.org/limits.html); [SQLite WAL](https://www.sqlite.org/wal.html); [SQLite FTS5](https://www.sqlite.org/fts5.html)
- Xet chunk dedup, Hub limits, destructive squash. — [HF Xet deduplication](https://huggingface.co/docs/hub/xet/deduplication); [HF storage limits](https://huggingface.co/docs/hub/storage-limits)
- lakeFS BSL; DoltLite beta and file format. — [lakeFS BSL](https://lakefs.io/blog/lakefs-business-source-license/); [DoltLite](https://github.com/dolthub/doltlite)

### Inferences (the recommendations, in priority order)

**P1. Fetch hygiene** (days; unblocks everything; evidence: User-Agent policy, Etiquette, Maxlag, 2026 rate limits, OpenAlex authentication)
- Change the User-Agent to `acatalogue/<ver> (https://github.com/virideanil/acatalogue; <contact email>) Python-urllib/3.11`.
- Send `maxlag=5` on Action API calls, and treat a JSON `error.code == "maxlag"` inside an HTTP 200 as retryable, honouring `Retry-After`. The current code retries only on HTTP 429/5xx, so a maxlag error would be sealed as if it were data.
- Switch to `Accept-Encoding: gzip`. Record `Content-Encoding` and the SHA-512 of the decoded body in `fetch_log`, so exact-byte provenance survives.
- Use an OAuth 2.0 owner-only token for any remaining Action API work. This gives per-account limits instead of shared-IP limits.
- Register a free OpenAlex key, kept in an environment variable and never in git.
- Stop using WDQS or `wbsearchentities` for bulk label matching. P2 provides a local label index instead.

**P2. `acat fetch wikidata-dump`: baseline corpus from the weekly JSON dump** (1–2 weeks; evidence: Database download, dump listing, observed `lastrevid`)
- Stream the pinned dated `…-all.json.gz` with `urllib` and `zlib`, handling multi-member gzip, and filter by a tracked-QID set. The set would be the reconciled concepts plus their P31/P279 closure and linked items, or everything.
- For each entity, store the exact line bytes without the trailing comma, its SHA-512, `lastrevid`, `modified`, and the source URL, dump date and gzip-member offset.
- Shard by QID range into several sealed SQLite corpora.
- Also build a local multilingual **label/alias index** from the dump, so reconciliation proposals stop hitting WDQS.
- If scholarly items matter, the WDQS split means they must be selected explicitly. They are in the dump, but queries need `query-scholarly`.

**P3. `acat sync wikidata`: delta corpora from EventStreams** (1–2 weeks; evidence: EventStreams docs and spec, Data access, RecentChanges)
- Consume `mediawiki.recentchange`, filtered to `wikidatawiki`, the item/property namespaces and the tracked QIDs. Persist `Last-Event-ID` in `meta` and reconnect within 15 minutes.
- For each `(QID, revid)`, fetch `Special:EntityData/Q….json?revision=N&flavor=dump` serially at ≤1 req/s.
- Seal one delta corpus per day. Derived claims get record time = fetch time; earlier claims are *superseded*, never deleted.
- Model redirects, merges and deletions as supersession events that open **review items**, never as silent rewrites of decisions.
- Detect gaps: if the first replayed event is newer than the requested `since`, backfill from `list=recentchanges` (≤30 days), else rebase on the next dump.
- Add a weekly audit that compares the dump's `lastrevid` with the local copy.

**P4. Review queue that separates proposals from decisions** (1–2 weeks; evidence: Mix'n'match, Reconciliation API, Wikidata constraints, GO/ODK, Artstein & Poesio)
- Add a derived `proposal` table: candidate `id`/`name`/`type`/`score`/`match`/`features`, with `method` and the source corpus SHA-512.
- Add `acat review next` to emit batched queue TSVs, and `acat review apply` to write decisions into `seed/crosswalk/*.tsv` with reviewer, date and method.
- Use the states `unmatched`/`proposed`/`accepted`/`rejected`/`not_applicable`. The build fails if a published match lacks a decision.
- Add a constraint report (single-value, distinct-values, type, format; mandatory or suggestion; exceptions) to `acat verify`.
- Double-review a random sample of about 10% and report kappa or alpha in `acat audit`.
- Run PR-based review with CI and a second reviewer.
- Optionally expose a Reconciliation API 1.0-draft endpoint from `acat serve`, so OpenRefine can drive review.

**P5. Incremental catalogue build and search indexes** (1–2 weeks; evidence: SQLite limits, WAL, FTS5)
- Build incrementally, keyed by input SHA-512, with a periodic full rebuild to verify hashes.
- Write to a temporary file without WAL, then rename atomically; serve readers with `mode=ro`/`immutable=1`.
- Use external-content FTS5 with `detail=column` where phrase search isn't needed, trigram on labels only, and `optimize` after each build.
- Don't rely on more than 10 ATTACHed corpora.
- Bundle or require SQLite ≥3.51.3 if WAL and concurrency are ever used; the local version is 3.45.1.

**P6. Wikipedia intros from dumps, in many languages** (1–2 weeks; evidence: CirrusSearch deprecation notice and new location, Enterprise snapshot docs, Reusing Wikipedia content)
- Prototype on one weekly `cirrus_search_index/<date>/index_name=<lang>wiki_content/` shard, and check that `opening_text` is present.
- Alternatively, use Enterprise Structured Contents monthly snapshots (`abstract`, `version.identifier`, `license`).
- Seal the exact shard or tarball bytes.
- Keep CC BY-SA text in a separately licensed layer, with per-passage URL and revision and a modification notice.

**P7. OpenAlex topics** (days; evidence: OpenAlex pricing, example costs, topics, snapshot)
- Fetch domains, fields, subfields and topics with a key: about 51 list calls, about $0.005.
- Seal the responses and propose crosswalks from ACAT to OpenAlex topics through the P4 queue.
- Use the quarterly snapshot (manifests, `updated_date` partitions, `deleted_ids`) for anything at works scale.

**P8. Local full-graph querying** (optional; evidence: QLever benchmark, WDQS limits and graph split)
- For graph-wide consistency checks, such as P279 closure or constraint sweeps, run QLever locally on a dump rather than using WDQS. Reported resources: about 4 h to index, 64 GB RAM recommended, about 450 GB of index.

**P9. Distribution and versioning** (days; evidence: HF Xet and storage limits, GitHub LFS limits, lakeFS BSL, DoltLite)
- Mirror sealed corpora and dated catalogue builds to a public HF dataset repo, with a dataset card and a Parquet export of the catalogue tables.
- Record each HF commit SHA in the ledger. Never use `super_squash_history`.
- Keep GitHub for code and seeds only; LFS allows 2 GB per file on free plans.
- Skip lakeFS (BSL) and DVC (redundant). Revisit DoltLite once it leaves beta, and only as an optional derived diff view.

### Gaps
Things to verify before building:
- whether the new CirrusSearch shards keep `opening_text`, and their format;
- whether entity dumps publish checksum files, and their dated file naming;
- whether `Special:EntityData` counts against the 2026 API limits;
- how unauthenticated clients are keyed under the 2026 limits;
- event volumes on `mediawiki.recentchange` for sizing the P3 consumer;
- the Enterprise terms of service on redistribution;
- the licence of the OpenAlex topic-taxonomy file and its ASJC-derived labels;
- DoltLite's Python bindings.
