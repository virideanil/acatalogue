-- acatalogue catalogue schema (SQLite >= 3.38, FTS5 with the trigram tokenizer)
--
-- Layers, bottom to top:
--   source        exact bytes of every input, addressed by SHA-512 (seeds, fetched responses)
--   corpus        named, dated, sealed collections of sources  -> document -> passage (+ FTS)
--   scheme        concept schemes: the authored compendium, facets, external schemes
--   concept       SKOS-like concepts: labels in any language, broader (poly-hierarchy),
--                 related, mappings (crosswalks), facets
--   claim         attributed statements with epistemic status and two times
--                 (world time: valid_from/valid_to; record time: recorded_at/superseded_at)
--   embedding     derived vectors, labelled by the model that made them
--   ledger        append-only, hash-chained record of every action on this database
--
-- Invariants enforced here, not by convention:
--   * ledger rows can never be updated or deleted (triggers)
--   * sources (bytes) and concepts (identities) can never be deleted; concepts are deprecated
--   * claims are never deleted; they are superseded
-- Derived tables (passages, FTS indexes, stats, embeddings, layout) may be rebuilt.

-- user_version is the schema version; acatalogue/migrate.py upgrades older databases in place
-- (copying every row that must never be lost) before this file runs.
PRAGMA user_version = 4;

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- ─── exact bytes ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS source (
  sha512       TEXT PRIMARY KEY CHECK (length(sha512) = 128),
  bytes        INTEGER NOT NULL CHECK (bytes >= 0),
  kind         TEXT NOT NULL CHECK (kind IN ('seed', 'fetch', 'file')),
  name         TEXT NOT NULL,          -- seed path, or '<corpus>:<item name>'
  corpus       TEXT,                   -- corpus name when the bytes live in a corpus file
  uri          TEXT,                   -- URL fetched, or repository path
  retrieved_at TEXT,                   -- ISO 8601 UTC, for fetches
  content_type TEXT,
  license      TEXT,
  attribution  TEXT,
  first_seen   TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS source_never_deleted BEFORE DELETE ON source
BEGIN SELECT RAISE(ABORT, 'sources are exact bytes and are never deleted'); END;

-- ─── named corpora ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS corpus (
  name            TEXT PRIMARY KEY,    -- e.g. 'wikipedia-en-intros-20260925'
  title           TEXT NOT NULL,
  description     TEXT,
  license         TEXT,
  path            TEXT NOT NULL,       -- repository-relative path of the corpus file
  manifest_sha512 TEXT,                -- SHA-512 over the sorted (item name, item sha512) lines
  items           INTEGER NOT NULL DEFAULT 0,
  sealed_at       TEXT,
  imported_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS document (
  id            TEXT PRIMARY KEY,      -- 'doc/<corpus>/<name>'
  corpus        TEXT NOT NULL REFERENCES corpus(name),
  name          TEXT NOT NULL,
  title         TEXT,
  lang          TEXT,
  url           TEXT,
  license       TEXT,
  attribution   TEXT,
  source_sha512 TEXT NOT NULL REFERENCES source(sha512),
  text          TEXT NOT NULL,
  n_chars       INTEGER NOT NULL,
  superseded_by TEXT,                  -- a newer document id; NULL = current
  UNIQUE (corpus, name)
);

CREATE TABLE IF NOT EXISTS passage (
  id     INTEGER PRIMARY KEY,
  doc_id TEXT NOT NULL REFERENCES document(id),
  ord    INTEGER NOT NULL,
  start  INTEGER NOT NULL,             -- character offsets into document.text
  end    INTEGER NOT NULL,
  text   TEXT NOT NULL,
  UNIQUE (doc_id, ord)
);

-- Search indexes over passages, rebuilt by `acat build` (derived, so no triggers):
--   passage_fts  word search; combining marks stay inside words (Devanagari, Tamil, vocalised Arabic)
--   passage_key  substring/regex prefilter over the case key of the text (see acatalogue/textkeys.py);
--                case_sensitive 1 because the key itself carries Python's case-insensitivity
CREATE VIRTUAL TABLE IF NOT EXISTS passage_fts USING fts5(
  text, content='passage', content_rowid='id',
  tokenize="unicode61 remove_diacritics 2 categories 'L* N* Co M*'");
CREATE VIRTUAL TABLE IF NOT EXISTS passage_key USING fts5(
  k, content='', detail=full, tokenize='trigram case_sensitive 1');

-- which concepts a document is about (how that was decided is recorded in `method`)
CREATE TABLE IF NOT EXISTS document_concept (
  doc_id     TEXT NOT NULL REFERENCES document(id),
  concept_id TEXT NOT NULL REFERENCES concept(id),
  relation   TEXT NOT NULL DEFAULT 'about',
  method     TEXT NOT NULL,
  PRIMARY KEY (doc_id, concept_id)
);

-- ─── the compendium: schemes and concepts (SKOS-like) ───────────────────────
CREATE TABLE IF NOT EXISTS scheme (
  id            TEXT PRIMARY KEY,      -- 'acat', 'space', 'kind', 'epistemic', 'udc', 'wd', ...
  title         TEXT NOT NULL,
  description   TEXT,
  origin        TEXT NOT NULL CHECK (origin IN ('authored', 'external')),
  license       TEXT,
  homepage      TEXT,
  source_sha512 TEXT REFERENCES source(sha512)
);

CREATE TABLE IF NOT EXISTS concept (
  id            TEXT PRIMARY KEY,      -- '<scheme>/<code>' : scoped and resolvable
  scheme        TEXT NOT NULL REFERENCES scheme(id),
  code          TEXT NOT NULL,
  label         TEXT NOT NULL,         -- preferred display label (English for now)
  scope_note    TEXT,
  notation      TEXT,                  -- a scheme's own notation (UDC '5', ISO 'TUR', ...)
  time_from     INTEGER,               -- world-time span in astronomical years (1 BCE = 0,
  time_to       INTEGER,               --   2000 BCE = -1999); NULL = timeless or open
  status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'deprecated')),
  replaced_by   TEXT,
  source_sha512 TEXT REFERENCES source(sha512),
  UNIQUE (scheme, code)
);
CREATE TRIGGER IF NOT EXISTS concept_never_deleted BEFORE DELETE ON concept
BEGIN SELECT RAISE(ABORT, 'concepts are never deleted; set status = deprecated'); END;

CREATE TABLE IF NOT EXISTS label (
  id            INTEGER PRIMARY KEY,   -- stable rowid: the label indexes point at it (VACUUM-safe)
  concept_id    TEXT NOT NULL REFERENCES concept(id),
  lang          TEXT NOT NULL,         -- Wikimedia / BCP 47 language code
  kind          TEXT NOT NULL CHECK (kind IN ('pref', 'alt', 'desc')),
  text          TEXT NOT NULL,         -- NFC-normalised
  source_sha512 TEXT REFERENCES source(sha512),
  UNIQUE (concept_id, lang, kind, text)
);
CREATE INDEX IF NOT EXISTS label_lang ON label(lang);

CREATE TABLE IF NOT EXISTS broader (      -- child is narrower than parent; several parents allowed
  child         TEXT NOT NULL REFERENCES concept(id),
  parent        TEXT NOT NULL REFERENCES concept(id),
  source_sha512 TEXT REFERENCES source(sha512),
  PRIMARY KEY (child, parent),
  CHECK (child <> parent)
);
CREATE INDEX IF NOT EXISTS broader_parent ON broader(parent);

CREATE TABLE IF NOT EXISTS related (      -- symmetric; stored once with a < b
  a             TEXT NOT NULL REFERENCES concept(id),
  b             TEXT NOT NULL REFERENCES concept(id),
  source_sha512 TEXT REFERENCES source(sha512),
  PRIMARY KEY (a, b),
  CHECK (a < b)
);

CREATE TABLE IF NOT EXISTS mapping (      -- crosswalks between schemes (SKOS mapping relations)
  from_id       TEXT NOT NULL REFERENCES concept(id),
  to_id         TEXT NOT NULL,           -- may point outside the catalogue (e.g. an unfetched wd item)
  relation      TEXT NOT NULL CHECK (relation IN
                  ('exactMatch', 'closeMatch', 'broadMatch', 'narrowMatch', 'relatedMatch')),
  method        TEXT NOT NULL,           -- 'authored', 'wbsearch+review', ...
  status        TEXT NOT NULL CHECK (status IN ('proposed', 'accepted', 'rejected')),
  reviewer      TEXT,
  note          TEXT,
  source_sha512 TEXT REFERENCES source(sha512),
  PRIMARY KEY (from_id, to_id)
);
CREATE INDEX IF NOT EXISTS mapping_to ON mapping(to_id);

CREATE TABLE IF NOT EXISTS facet (        -- a concept placed on another scheme's axis (where, what kind, ...)
  concept_id    TEXT NOT NULL REFERENCES concept(id),
  facet_id      TEXT NOT NULL REFERENCES concept(id),
  source_sha512 TEXT REFERENCES source(sha512),
  PRIMARY KEY (concept_id, facet_id)
);

CREATE TABLE IF NOT EXISTS attribute (    -- small typed facts about a record, each with its source
  concept_id    TEXT NOT NULL,            -- e.g. 'wd/Q413'
  key           TEXT NOT NULL,            -- e.g. 'sitelinks', 'enwiki', 'verified-in'
  value         TEXT NOT NULL,
  source_sha512 TEXT REFERENCES source(sha512),
  PRIMARY KEY (concept_id, key)
);

-- search indexes over the compendium (rebuilt by `acat build`)
CREATE VIRTUAL TABLE IF NOT EXISTS concept_fts USING fts5(
  id UNINDEXED, label, alts, scope_note,
  tokenize="unicode61 remove_diacritics 2 categories 'L* N* Co M*'");
-- concept text for substring/regex search: `text` is what matches are checked against, `k` its case key
CREATE VIRTUAL TABLE IF NOT EXISTS concept_key USING fts5(
  id UNINDEXED, text UNINDEXED, k, tokenize='trigram case_sensitive 1');
-- label word index reads its text from the label table itself (external content): no second copy
CREATE VIRTUAL TABLE IF NOT EXISTS label_fts USING fts5(
  concept_id UNINDEXED, lang UNINDEXED, kind UNINDEXED, text, content='label', content_rowid='id',
  tokenize="unicode61 remove_diacritics 2 categories 'L* N* Co M*'");
-- label case-key trigram index and CJK character-pair index (contentless; rowid = label.id)
CREATE VIRTUAL TABLE IF NOT EXISTS label_key USING fts5(
  k, content='', detail=full, tokenize='trigram case_sensitive 1');
CREATE VIRTUAL TABLE IF NOT EXISTS label_cjk USING fts5(
  k, content='', detail=full, tokenize="unicode61 categories 'L* N* Co M*'");

-- ─── claims: attributed statements ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS claim (
  id              INTEGER PRIMARY KEY,
  subject         TEXT NOT NULL,        -- scoped id
  predicate       TEXT NOT NULL,        -- scoped id, e.g. 'wd/P279'
  snak_type       TEXT NOT NULL DEFAULT 'value'
                  CHECK (snak_type IN ('value', 'somevalue', 'novalue')),  -- a value / "unknown value" / "no value"
  object          TEXT,                 -- scoped id when the value is a thing
  value           TEXT,                 -- literal (JSON for structured values) when it is not
  datatype        TEXT,                 -- the source's datatype, e.g. 'time', 'quantity', 'string'
  qualifiers      TEXT,                 -- JSON summary for simple sources; see claim_qualifier
  rank            TEXT,                 -- the source's own rank (Wikidata: preferred/normal/deprecated)
  statement_id    TEXT,                 -- the source's own statement identifier (Wikidata statement GUID)
  source_revision INTEGER,              -- the revision of the source record the statement was read from
  source_pointer  TEXT,                 -- RFC 6901 JSON Pointer into the source bytes
  epistemic       TEXT NOT NULL DEFAULT 'epistemic/attributed',
  perspective     TEXT,                 -- whose account this is, when it is one account among several
  valid_from      TEXT,                 -- world time (ISO 8601 / EDTF / Wikidata time); NULL = not stated
  valid_to        TEXT,
  time_precision  INTEGER,              -- Wikidata precision code (9 year, 10 month, 11 day …)
  valid_from_day  INTEGER,              -- Julian Day Numbers bounding the widest interval the stated
  valid_to_day    INTEGER,              --   precisions allow: sortable, and correct across BCE
  source_sha512   TEXT NOT NULL REFERENCES source(sha512),
  recorded_at     TEXT NOT NULL,        -- record time: when this catalogue learned it
  superseded_at   TEXT,                 -- record time: when a newer statement replaced it
  CHECK (snak_type <> 'value' OR ((object IS NULL) <> (value IS NULL))),
  CHECK (snak_type = 'value' OR (object IS NULL AND value IS NULL))
);
-- two statements with the same value but different qualifiers are different statements
CREATE UNIQUE INDEX IF NOT EXISTS claim_statement ON claim(statement_id, source_sha512)
  WHERE statement_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS claim_identity
  ON claim(subject, predicate, coalesce(object, ''), coalesce(value, ''), source_sha512)
  WHERE statement_id IS NULL;
CREATE INDEX IF NOT EXISTS claim_subject ON claim(subject);
CREATE INDEX IF NOT EXISTS claim_object ON claim(object);
CREATE TRIGGER IF NOT EXISTS claim_never_deleted BEFORE DELETE ON claim
BEGIN SELECT RAISE(ABORT, 'claims are never deleted; set superseded_at'); END;

CREATE TABLE IF NOT EXISTS claim_qualifier (   -- first-class qualifiers, in the source's order
  claim_id  INTEGER NOT NULL REFERENCES claim(id),
  ord       INTEGER NOT NULL,
  property  TEXT NOT NULL,
  snak_type TEXT NOT NULL CHECK (snak_type IN ('value', 'somevalue', 'novalue')),
  object    TEXT,
  value     TEXT,
  datatype  TEXT,
  PRIMARY KEY (claim_id, ord)
);
CREATE TABLE IF NOT EXISTS claim_reference (   -- the source's references for a statement
  claim_id  INTEGER NOT NULL REFERENCES claim(id),
  ref_hash  TEXT NOT NULL,              -- the source's own reference hash
  ord       INTEGER NOT NULL,
  property  TEXT NOT NULL,              -- e.g. 'wd/P248' stated in, 'wd/P854' reference URL
  snak_type TEXT NOT NULL CHECK (snak_type IN ('value', 'somevalue', 'novalue')),
  object    TEXT,
  value     TEXT,
  datatype  TEXT,
  PRIMARY KEY (claim_id, ref_hash, ord)
);
CREATE TRIGGER IF NOT EXISTS claim_qualifier_never_deleted BEFORE DELETE ON claim_qualifier
BEGIN SELECT RAISE(ABORT, 'qualifiers belong to claims and are never deleted'); END;
CREATE TRIGGER IF NOT EXISTS claim_reference_never_deleted BEFORE DELETE ON claim_reference
BEGIN SELECT RAISE(ABORT, 'references belong to claims and are never deleted'); END;

-- ─── claim views: nothing is deleted, so readers filter ─────────────────────
DROP VIEW IF EXISTS v_claim_current;
CREATE VIEW v_claim_current AS SELECT * FROM claim WHERE superseded_at IS NULL;
-- Wikidata's "truthy" reading: current, not deprecated, and preferred when a preferred one exists
DROP VIEW IF EXISTS v_claim_truthy;
CREATE VIEW v_claim_truthy AS
  SELECT c.* FROM claim c WHERE c.superseded_at IS NULL AND coalesce(c.rank, 'normal') <> 'deprecated'
    AND (c.rank = 'preferred' OR NOT EXISTS (
      SELECT 1 FROM claim p WHERE p.subject = c.subject AND p.predicate = c.predicate
        AND p.rank = 'preferred' AND p.superseded_at IS NULL));
-- sourced: some reference says more than "imported from a Wikimedia project" (P143, P4656) and a
-- retrieval date (P813); such imports name where a value was copied from, not a source for it
DROP VIEW IF EXISTS v_claim_evidence;
CREATE VIEW v_claim_evidence AS
  SELECT c.id AS claim_id,
    (SELECT count(DISTINCT r.ref_hash) FROM claim_reference r WHERE r.claim_id = c.id) AS references_n,
    EXISTS (SELECT 1 FROM claim_reference r WHERE r.claim_id = c.id
            AND r.property NOT IN ('wd/P143', 'wd/P4656', 'wd/P813')) AS sourced
  FROM claim c;

-- ─── review: who decided, from which perspective ────────────────────────────
CREATE TABLE IF NOT EXISTS review (
  id            INTEGER PRIMARY KEY,
  target        TEXT NOT NULL,        -- 'mapping:<from>|<to>', 'concept:<id>', 'label:<concept>|<lang>|<text>'
  reviewer      TEXT NOT NULL,
  reviewer_kind TEXT NOT NULL CHECK (reviewer_kind IN ('human', 'agent')),
  perspective   TEXT,                 -- the reviewer's declared perspective, tradition or region
  decided_at    TEXT NOT NULL,
  decision      TEXT NOT NULL CHECK (decision IN ('approve', 'revise', 'object')),
  relation      TEXT,                 -- revise: the relation the mapping should have
  rationale     TEXT,
  source_sha512 TEXT NOT NULL REFERENCES source(sha512),   -- the review file it was read from
  UNIQUE (target, reviewer, decided_at)
);

-- ─── audit: declared baselines and stored measurements ──────────────────────
CREATE TABLE IF NOT EXISTS baseline (   -- reference distributions an audit compares coverage against
  dimension     TEXT NOT NULL,          -- 'population', 'land_area'
  group_id      TEXT NOT NULL,          -- scoped id of the country or area
  value         REAL NOT NULL,
  unit          TEXT NOT NULL,
  as_of         TEXT NOT NULL,          -- the source's reference year
  source_sha512 TEXT NOT NULL REFERENCES source(sha512),
  PRIMARY KEY (dimension, group_id, as_of)
);
CREATE TABLE IF NOT EXISTS audit_run (
  id          INTEGER PRIMARY KEY,
  at          TEXT NOT NULL,
  ledger_head TEXT NOT NULL,            -- the catalogue state the numbers describe
  params      TEXT NOT NULL,            -- JSON: seed, bootstrap size, baselines, exclusions
  report      TEXT                      -- JSON presentation copy of the run for the API
);
CREATE TABLE IF NOT EXISTS audit_metric (
  run_id    INTEGER NOT NULL REFERENCES audit_run(id),
  dimension TEXT NOT NULL,              -- 'regions', 'subregions', 'siblings:<parent>', 'attention', 'review'
  group_id  TEXT NOT NULL,              -- the group measured; '' for a whole-distribution metric
  metric    TEXT NOT NULL,              -- 'share', 'log2_rr', 'jsd_bits', 'gini_rr', 'cv_subtree', ...
  baseline  TEXT NOT NULL DEFAULT '',   -- 'population', 'land_area', 'equal', or ''
  value     REAL,
  lo        REAL,                       -- interval bounds where the metric has one
  hi        REAL,
  n         REAL,                       -- the denominator the value came from
  PRIMARY KEY (run_id, dimension, group_id, metric, baseline)
);

-- ─── derived: statistics, semantic vectors, layout ──────────────────────────
CREATE TABLE IF NOT EXISTS concept_stat (
  concept_id  TEXT PRIMARY KEY REFERENCES concept(id),
  root        TEXT,                     -- top concept it descends from (first by id)
  depth       INTEGER,
  descendants INTEGER NOT NULL DEFAULT 0,
  docs        INTEGER NOT NULL DEFAULT 0,
  sitelinks   INTEGER,                  -- Wikipedia language editions (NULL = unknown)
  label_langs INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS model (
  id              TEXT PRIMARY KEY,     -- e.g. 'lsa-tfidf-svd-48'
  method          TEXT NOT NULL,        -- plain description of what the numbers are
  params          TEXT,                 -- JSON
  input_manifest  TEXT,                 -- SHA-512 over the exact texts it was fit on
  created_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS embedding (
  target TEXT NOT NULL,
  model  TEXT NOT NULL REFERENCES model(id),
  dim    INTEGER NOT NULL,
  vec    BLOB NOT NULL,                 -- little-endian float32
  PRIMARY KEY (target, model)
);
CREATE TABLE IF NOT EXISTS neighbor (
  target TEXT NOT NULL,
  other  TEXT NOT NULL,
  model  TEXT NOT NULL REFERENCES model(id),
  score  REAL NOT NULL,
  rank   INTEGER NOT NULL,
  PRIMARY KEY (target, model, other)
);
CREATE TABLE IF NOT EXISTS layout (
  target TEXT NOT NULL,
  model  TEXT NOT NULL REFERENCES model(id),
  x      REAL NOT NULL,
  y      REAL NOT NULL,
  PRIMARY KEY (target, model)
);

-- ─── the ledger ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ledger (
  seq       INTEGER PRIMARY KEY AUTOINCREMENT,
  at        TEXT NOT NULL,
  actor     TEXT NOT NULL,
  action    TEXT NOT NULL,
  target    TEXT,
  detail    TEXT,                       -- JSON
  receipt   TEXT,                       -- what proves it happened (hashes, counts)
  undo      TEXT,                       -- how to reverse it
  prev_hash TEXT NOT NULL,
  hash      TEXT NOT NULL UNIQUE        -- SHA-512 over prev_hash and this row's fields
);
CREATE TRIGGER IF NOT EXISTS ledger_no_update BEFORE UPDATE ON ledger
BEGIN SELECT RAISE(ABORT, 'the ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS ledger_no_delete BEFORE DELETE ON ledger
BEGIN SELECT RAISE(ABORT, 'the ledger is append-only'); END;

-- ─── views ──────────────────────────────────────────────────────────────────
CREATE VIEW IF NOT EXISTS v_concept AS
  SELECT c.id, c.scheme, c.code, c.label, c.status, s.root, s.depth, s.descendants,
         s.docs, s.sitelinks, s.label_langs, c.scope_note
  FROM concept c LEFT JOIN concept_stat s ON s.concept_id = c.id;
