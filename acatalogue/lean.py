"""The lean layout: every converted source is one SQLite file of the same shape.

  meta    source, title, licence, attribution, homepage, converter and version, converted_at, the
          manifest converted from, iri_template, counts
  input   every input file: name, SHA-512, size, URL, retrieval time
  lang    language tags, interned: BCP 47, lower case, '-' separated ('' = no language, e.g. a code)
  kind    kinds of terms (Concept, Class, Place, Language, Taxon, Period …) and the catalogue kind
          facet each one is (kind/place …) when the converter can say
  pred    predicates, interned: name, IRI, role (how the catalogue reads it), datatype, mapping relation
  term    the source's things: integer ids in the source's own order; code = the source's identifier;
          iri only where meta.iri_template applied to the code does not give it
  label   names: term, lang, kind, NFC text. Kinds: 0 preferred, 1 alternative (a true synonym),
          2 hidden (searchable, not shown: misspellings, old forms), 3 a broader name, 4 a narrower name,
          5 a related name (OBO's BROAD/NARROW/RELATED synonyms; shown nowhere as the thing's name)
  rel     relations between terms, each in one canonical direction (broader: narrower -> broader;
          related: stored once, lower id first); nothing is stored twice as its own inverse
  attr    literal values: term, predicate, language, value in SQLite's own type (integer, real, text)
  link    links out of the source: IRIs or codes of other schemes, with the predicate that says how
  label_fts  word index over the labels (derived; rebuilt by `finish`)

Roles of predicates (what the catalogue does with them, acatalogue/integrate.py):
  broader    -> broader edges        related  -> related edges     relation -> claims (thing-valued)
  attr       -> claims (literal)     note     -> descriptions, scope notes or claims
  notation   -> the concept's notation          link -> mappings, when the target's scheme is known
  replacedBy -> the concept's replaced_by

The writer stages rows and resolves them at `finish`, so relations may point forward to terms defined
later; every row is deduplicated and written in a canonical order; a relation whose object never
became a term is kept as a link (nothing is dropped silently: every drop is counted in meta).
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

from .textkeys import nfc
from .util import sha512_file, utcnow

LAYOUT_VERSION = 1
APPLICATION_ID = 0x61636174          # 'acat'
ROLES = ("broader", "related", "relation", "attr", "note", "notation", "link", "replacedBy")
LABEL_KINDS = {"pref": 0, "alt": 1, "hidden": 2, "broader": 3, "narrower": 4, "related": 5}
MAPPINGS = ("exactMatch", "closeMatch", "broadMatch", "narrowMatch", "relatedMatch")
WORDS_TOKENIZER = "unicode61 remove_diacritics 2 categories 'L* N* Co M*'"

SCHEMA = f"""
PRAGMA application_id = {APPLICATION_ID};
PRAGMA user_version = {LAYOUT_VERSION};
CREATE TABLE meta  (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
CREATE TABLE input (name TEXT PRIMARY KEY, sha512 TEXT NOT NULL CHECK (length(sha512) = 128),
                    bytes INTEGER NOT NULL, url TEXT, retrieved_at TEXT) WITHOUT ROWID;
CREATE TABLE lang  (id INTEGER PRIMARY KEY, tag TEXT NOT NULL UNIQUE);
CREATE TABLE kind  (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, iri TEXT, facet TEXT);
CREATE TABLE pred  (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, iri TEXT,
                    role TEXT NOT NULL CHECK (role IN {ROLES}), datatype TEXT,
                    map TEXT CHECK (map IS NULL OR map IN {MAPPINGS}));
CREATE TABLE term  (id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, kind INTEGER REFERENCES kind(id),
                    status INTEGER NOT NULL DEFAULT 0 CHECK (status IN (0, 1)), iri TEXT);
CREATE TABLE label (id INTEGER PRIMARY KEY, term INTEGER NOT NULL REFERENCES term(id),
                    lang INTEGER NOT NULL REFERENCES lang(id), kind INTEGER NOT NULL CHECK (kind BETWEEN 0 AND 5),
                    text TEXT NOT NULL);
CREATE TABLE rel   (s INTEGER NOT NULL, p INTEGER NOT NULL, o INTEGER NOT NULL, PRIMARY KEY (s, p, o),
                    CHECK (s <> o)) WITHOUT ROWID;
CREATE TABLE attr  (id INTEGER PRIMARY KEY, term INTEGER NOT NULL, p INTEGER NOT NULL, lang INTEGER NOT NULL,
                    value NOT NULL);
CREATE TABLE link  (term INTEGER NOT NULL, p INTEGER NOT NULL, target TEXT NOT NULL,
                    PRIMARY KEY (term, p, target)) WITHOUT ROWID;
CREATE TABLE _label (term INTEGER, lang INTEGER, kind INTEGER, text TEXT);
CREATE TABLE _rel   (s TEXT, p INTEGER, o TEXT);
CREATE TABLE _attr  (term INTEGER, p INTEGER, lang INTEGER, value);
CREATE TABLE _link  (term INTEGER, p INTEGER, target TEXT);
"""
INDEXES = """
CREATE INDEX label_term ON label(term);
CREATE INDEX rel_o ON rel(o, p);
CREATE INDEX attr_term ON attr(term, p);
CREATE INDEX link_target ON link(target);
"""


def norm_lang(tag: str | None) -> str:
    """BCP 47-ish tag in the catalogue's form: lower case, '-' separated ('' = none)."""
    return (tag or "").strip().replace("_", "-").lower()


class LeanWriter:
    BATCH = 50_000

    def __init__(self, path: str | Path, *, source: str, title: str, converter: str, version: str,
                 license: str | None = None, attribution: str | None = None, homepage: str | None = None,
                 iri_template: str | None = None, snapshot: str | None = None, manifest_sha512: str | None = None):
        self.path = Path(path)
        self.partial = self.path.with_name(self.path.name + ".partial")
        self.partial.parent.mkdir(parents=True, exist_ok=True)
        self.partial.unlink(missing_ok=True)
        self.conn = sqlite3.connect(self.partial, isolation_level=None)
        self.conn.execute("PRAGMA journal_mode = OFF")          # a partial file is thrown away on failure
        self.conn.execute("PRAGMA synchronous = OFF")
        self.conn.execute("PRAGMA temp_store = FILE")
        self.conn.execute("PRAGMA cache_size = -200000")
        self.conn.executescript(SCHEMA)
        self.conn.execute("BEGIN")
        self.meta = {"source": source, "title": title, "converter": converter, "converter_version": version,
                     "layout_version": str(LAYOUT_VERSION), "license": license, "attribution": attribution,
                     "homepage": homepage, "iri_template": iri_template, "snapshot": snapshot,
                     "manifest_sha512": manifest_sha512}
        self.ids: dict[str, int] = {}
        self._langs: dict[str, int] = {}
        self._kinds: dict[str, int] = {}
        self._preds: dict[str, tuple[int, str]] = {}
        self._buf: dict[str, list] = {"_label": [], "_rel": [], "_attr": [], "_link": []}
        self.dropped = {"labels_unknown_term": 0, "attrs_unknown_term": 0, "links_unknown_term": 0,
                        "empty_labels": 0}
        self.t0 = time.monotonic()

    # ── interning ──
    def lang(self, tag: str | None) -> int:
        t = norm_lang(tag)
        i = self._langs.get(t)
        if i is None:
            i = self._langs[t] = len(self._langs) + 1
            self.conn.execute("INSERT INTO lang(id, tag) VALUES (?, ?)", (i, t))
        return i

    def kind(self, name: str, iri: str | None = None, facet: str | None = None) -> int:
        i = self._kinds.get(name)
        if i is None:
            i = self._kinds[name] = len(self._kinds) + 1
            self.conn.execute("INSERT INTO kind(id, name, iri, facet) VALUES (?,?,?,?)", (i, name, iri, facet))
        return i

    def pred(self, name: str, role: str, iri: str | None = None, datatype: str | None = None,
             map: str | None = None) -> int:
        hit = self._preds.get(name)
        if hit is not None:
            if hit[1] != role:
                raise ValueError(f"predicate {name!r} declared as {hit[1]} and as {role}")
            return hit[0]
        if role not in ROLES:
            raise ValueError(f"unknown role {role!r}")
        i = len(self._preds) + 1
        self._preds[name] = (i, role)
        self.conn.execute("INSERT INTO pred(id, name, iri, role, datatype, map) VALUES (?,?,?,?,?,?)",
                          (i, name, iri, role, datatype, map))
        return i

    def role(self, pred_id: int) -> str:
        return next(r for i, r in self._preds.values() if i == pred_id)

    # ── rows ──
    def input(self, name: str, sha512: str, size: int, url: str | None = None, retrieved_at: str | None = None) -> None:
        self.conn.execute("INSERT OR REPLACE INTO input(name, sha512, bytes, url, retrieved_at) VALUES (?,?,?,?,?)",
                          (name, sha512, size, url, retrieved_at))

    def term(self, code: str, kind: int | None = None, iri: str | None = None, status: int = 0) -> int:
        """The id of the term with this code, created if new (in the order terms are first met)."""
        code = str(code)
        i = self.ids.get(code)
        if i is None:
            i = self.ids[code] = len(self.ids) + 1
            self.conn.execute("INSERT INTO term(id, code, kind, status, iri) VALUES (?,?,?,?,?)",
                              (i, code, kind, status, iri))
        elif kind is not None or iri is not None or status:
            self.conn.execute("UPDATE term SET kind = coalesce(?, kind), iri = coalesce(?, iri),"
                              " status = max(status, ?) WHERE id = ?", (kind, iri, status, i))
        return i

    def has(self, code: str) -> bool:
        return str(code) in self.ids

    def _id(self, t: int | str) -> int | None:
        return t if isinstance(t, int) else self.ids.get(str(t))

    def _push(self, table: str, row: tuple) -> None:
        buf = self._buf[table]
        buf.append(row)
        if len(buf) >= self.BATCH:
            self._flush(table)

    def _flush(self, table: str) -> None:
        buf = self._buf[table]
        if buf:
            marks = ",".join("?" * len(buf[0]))
            self.conn.executemany(f"INSERT INTO {table} VALUES ({marks})", buf)
            buf.clear()

    def label(self, t: int | str, text: str | None, lang: str | None = "", kind: str = "pref") -> None:
        i = self._id(t)
        if i is None:
            self.dropped["labels_unknown_term"] += 1
            return
        text = nfc((text or "").strip())
        if not text:
            self.dropped["empty_labels"] += 1
            return
        self._push("_label", (i, self.lang(lang), LABEL_KINDS[kind], text))

    def rel(self, s: str, pred: int, o: str) -> None:
        """A relation by codes; resolved at finish, so either end may be defined later."""
        self._push("_rel", (str(s), pred, str(o)))

    def attr(self, t: int | str, pred: int, value, lang: str | None = "") -> None:
        i = self._id(t)
        if i is None:
            self.dropped["attrs_unknown_term"] += 1
            return
        if isinstance(value, str):
            value = nfc(value.strip())
            if not value:
                return
        if value is None:
            return
        self._push("_attr", (i, pred, self.lang(lang), value))

    def link(self, t: int | str, pred: int, target: str) -> None:
        i = self._id(t)
        if i is None:
            self.dropped["links_unknown_term"] += 1
            return
        target = (target or "").strip()
        if target:
            self._push("_link", (i, pred, target))

    # ── finishing ──
    def finish(self) -> dict:
        for table in self._buf:
            self._flush(table)
        c = self.conn
        c.execute("INSERT INTO label(term, lang, kind, text) SELECT DISTINCT term, lang, kind, text FROM _label"
                  " ORDER BY term, kind, lang, text")
        related = [i for i, r in self._preds.values() if r == "related"]
        marks = ",".join(str(i) for i in related) or "NULL"
        c.execute("CREATE TEMP TABLE _resolved AS SELECT ts.id AS s, r.p AS p, tob.id AS o, r.o AS o_code FROM _rel r"
                  " JOIN term ts ON ts.code = r.s LEFT JOIN term tob ON tob.code = r.o")
        n_rel_in = c.execute("SELECT count(*) FROM _rel").fetchone()[0]
        n_resolved = c.execute("SELECT count(*) FROM _resolved").fetchone()[0]
        c.execute(f"INSERT OR IGNORE INTO rel(s, p, o) SELECT CASE WHEN p IN ({marks}) THEN min(s, o) ELSE s END, p,"
                  f" CASE WHEN p IN ({marks}) THEN max(s, o) ELSE o END FROM _resolved WHERE o IS NOT NULL AND s <> o"
                  f" ORDER BY 1, 2, 3")
        self_loops = c.execute("SELECT count(*) FROM _resolved WHERE o IS NOT NULL AND s = o").fetchone()[0]
        # an object that never became a term is kept as a link, not dropped
        c.execute("INSERT INTO _link SELECT s, p, o_code FROM _resolved WHERE o IS NULL")
        dangling = c.execute("SELECT count(*) FROM _resolved WHERE o IS NULL").fetchone()[0]
        c.execute("INSERT INTO attr(term, p, lang, value) SELECT DISTINCT term, p, lang, value FROM _attr"
                  " ORDER BY term, p, lang, value")
        c.execute("INSERT OR IGNORE INTO link(term, p, target) SELECT term, p, target FROM _link ORDER BY term, p, target")
        for t in ("_label", "_rel", "_attr", "_link"):
            c.execute(f"DROP TABLE {t}")
        c.execute("DROP TABLE temp._resolved")
        for stmt in filter(str.strip, INDEXES.split(";")):          # (executescript would commit first)
            c.execute(stmt)
        c.execute(f"CREATE VIRTUAL TABLE label_fts USING fts5(text, content='label', content_rowid='id',"
                  f" tokenize=\"{WORDS_TOKENIZER}\")")
        c.execute("INSERT INTO label_fts(label_fts) VALUES ('rebuild')")
        counts = {t: c.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                  for t in ("term", "label", "rel", "attr", "link", "lang", "pred", "kind")}
        counts["deprecated"] = c.execute("SELECT count(*) FROM term WHERE status = 1").fetchone()[0]
        self.dropped.update({"relations_subject_unknown": n_rel_in - n_resolved, "relations_self": self_loops,
                             "relations_kept_as_links": dangling})
        # nothing time-dependent goes into the file: the same inputs read the same way give the same bytes
        meta = {**{k: v for k, v in self.meta.items() if v is not None},
                "counts": json.dumps(counts, sort_keys=True), "dropped": json.dumps(self.dropped, sort_keys=True)}
        c.executemany("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", sorted(meta.items()))
        c.execute("COMMIT")
        c.execute("ANALYZE")
        c.execute("VACUUM")
        c.close()
        os.replace(self.partial, self.path)
        digest, size = sha512_file(self.path)
        return {"path": str(self.path), "sha512": digest, "bytes": size, "counts": counts, "dropped": self.dropped,
                "converted_at": utcnow(), "seconds": round(time.monotonic() - self.t0, 1)}

    def abort(self) -> None:
        try:
            self.conn.close()
        finally:
            self.partial.unlink(missing_ok=True)


class LeanReader:
    """Read access to a lean file (read-only)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        if self.conn.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
            raise ValueError(f"{path} is not a lean acatalogue source file")
        self.meta = dict(self.conn.execute("SELECT key, value FROM meta"))

    def counts(self) -> dict:
        return json.loads(self.meta.get("counts", "{}"))

    def iri(self, code: str, iri: str | None) -> str | None:
        if iri:
            return iri
        tpl = self.meta.get("iri_template")
        return tpl.replace("{code}", code) if tpl else None

    def close(self) -> None:
        self.conn.close()
