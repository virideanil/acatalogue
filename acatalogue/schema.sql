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

PRAGMA user_version = 1;

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

-- word search (FTS5 query syntax) and substring search (trigram) over passages
CREATE VIRTUAL TABLE IF NOT EXISTS passage_fts USING fts5(
  text, content='passage', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
CREATE VIRTUAL TABLE IF NOT EXISTS passage_tri USING fts5(
  text, content='passage', content_rowid='id', tokenize='trigram');

CREATE TRIGGER IF NOT EXISTS passage_ai AFTER INSERT ON passage BEGIN
  INSERT INTO passage_fts(rowid, text) VALUES (new.id, new.text);
  INSERT INTO passage_tri(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS passage_ad AFTER DELETE ON passage BEGIN
  INSERT INTO passage_fts(passage_fts, rowid, text) VALUES ('delete', old.id, old.text);
  INSERT INTO passage_tri(passage_tri, rowid, text) VALUES ('delete', old.id, old.text);
END;
CREATE TRIGGER IF NOT EXISTS passage_au AFTER UPDATE ON passage BEGIN
  INSERT INTO passage_fts(passage_fts, rowid, text) VALUES ('delete', old.id, old.text);
  INSERT INTO passage_tri(passage_tri, rowid, text) VALUES ('delete', old.id, old.text);
  INSERT INTO passage_fts(rowid, text) VALUES (new.id, new.text);
  INSERT INTO passage_tri(rowid, text) VALUES (new.id, new.text);
END;

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
  concept_id    TEXT NOT NULL REFERENCES concept(id),
  lang          TEXT NOT NULL,         -- Wikimedia / BCP 47 language code
  kind          TEXT NOT NULL CHECK (kind IN ('pref', 'alt', 'desc')),
  text          TEXT NOT NULL,
  source_sha512 TEXT REFERENCES source(sha512),
  PRIMARY KEY (concept_id, lang, kind, text)
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
  id UNINDEXED, label, alts, scope_note, tokenize='unicode61 remove_diacritics 2');
CREATE VIRTUAL TABLE IF NOT EXISTS concept_tri USING fts5(
  id UNINDEXED, text, tokenize='trigram');
-- label indexes read their text from the label table itself (external content): no second copy
CREATE VIRTUAL TABLE IF NOT EXISTS label_fts USING fts5(
  concept_id UNINDEXED, lang UNINDEXED, kind UNINDEXED, text, content='label',
  tokenize='unicode61 remove_diacritics 2');
CREATE VIRTUAL TABLE IF NOT EXISTS label_tri USING fts5(
  concept_id UNINDEXED, lang UNINDEXED, kind UNINDEXED, text, content='label', tokenize='trigram');

-- ─── claims: attributed statements ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS claim (
  id            INTEGER PRIMARY KEY,
  subject       TEXT NOT NULL,          -- scoped id
  predicate     TEXT NOT NULL,          -- scoped id, e.g. 'wd/P279'
  object        TEXT,                   -- scoped id when the value is a thing
  value         TEXT,                   -- literal when it is not
  qualifiers    TEXT,                   -- JSON object
  rank          TEXT,                   -- the source's own rank (Wikidata: preferred/normal/deprecated)
  epistemic     TEXT NOT NULL DEFAULT 'epistemic/attributed',
  perspective   TEXT,                   -- whose account this is, when it is one account among several
  valid_from    TEXT,                   -- world time (ISO 8601 / EDTF); NULL = not stated
  valid_to      TEXT,
  source_sha512 TEXT NOT NULL REFERENCES source(sha512),
  recorded_at   TEXT NOT NULL,          -- record time: when this catalogue learned it
  superseded_at TEXT,                   -- record time: when a newer statement replaced it
  CHECK ((object IS NULL) <> (value IS NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS claim_identity
  ON claim(subject, predicate, coalesce(object, ''), coalesce(value, ''), source_sha512);
CREATE INDEX IF NOT EXISTS claim_subject ON claim(subject);
CREATE INDEX IF NOT EXISTS claim_object ON claim(object);
CREATE TRIGGER IF NOT EXISTS claim_never_deleted BEFORE DELETE ON claim
BEGIN SELECT RAISE(ABORT, 'claims are never deleted; set superseded_at'); END;

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
