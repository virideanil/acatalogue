"""Tables -> lean, by a declared mapping: CSV/TSV files (in archives or not) and SQLite databases,
including a user's own. The registry's options say which column is what; no code per source.

    {"tables": [                                  # read in order; later tables may only add to terms
      {"members": "languoid.csv",                 # archive member(s), fnmatch pattern
       "delimiter": ",", "header": true,          # columns by name (header) or by 0-based index
       "encoding": "utf-8", "skip_prefix": "#",   # lines starting so are comments
       "code": "id",                              # the term's code (required)
       "creates": true,                           # rows create terms (false: only annotate known ones)
       "kind": "Languoid", "kind_iri": "…", "facet": "kind/symbol-system", "kind_column": "level",
       "labels": [{"column": "name", "lang": "en", "kind": "pref"},
                  {"column": "alt", "split": ";", "lang_column": "lang", "kind": "alt"}],
       "broader": [{"column": "parent_id", "name": "parent"}],     # code of a broader term
       "relations": [{"column": "family_id", "name": "family"}],   # code of another term
       "attrs": [{"column": "latitude", "type": "real"}, {"column": "level"}],
       "notes": [{"column": "description", "name": "definition", "lang": "en"}],
       "links": [{"column": "iso639P3code", "name": "iso639-3", "prefix": "iso639-3:", "map": "exactMatch"}],
       "status": {"column": "status", "deprecated": ["retired"]},
       "where": {"column": "level", "in": ["language", "dialect"]}}],
     "iri_template": "https://glottolog.org/resource/languoid/id/{code}"}

For SQLite: {"tables": [{"sql": "SELECT id, name, parent FROM things", "code": "id", …}]} — the query
runs read-only on the verified copy in the store. Empty cells are absent values, never empty strings.
"""
from __future__ import annotations

import csv
import sqlite3
import sys

from . import Input, members, text_lines

csv.field_size_limit(sys.maxsize)


def _cast(v, typ: str | None):
    if typ == "int":
        try:
            return int(v)
        except (TypeError, ValueError):
            return v
    if typ == "real":
        try:
            return float(v)
        except (TypeError, ValueError):
            return v
    return v


class _Mapper:
    def __init__(self, w, spec: dict):
        self.w, self.spec = w, spec
        self.kind = w.kind(spec["kind"], spec.get("kind_iri"), spec.get("facet")) if spec.get("kind") else None
        self.kinds: dict[str, int] = {}
        self.preds: dict[tuple[str, str], int] = {}
        self.creates = spec.get("creates", True)
        self.rows = 0
        self.skipped = 0

    def pred(self, name: str, role: str, iri: str | None = None, map: str | None = None, datatype=None) -> int:
        key = (name, role)
        if key not in self.preds:
            self.preds[key] = self.w.pred(name, role, iri, datatype, map)
        return self.preds[key]

    def row(self, get) -> None:
        s, w = self.spec, self.w
        cond = s.get("where")
        if cond and get(cond["column"]) not in cond["in"]:
            self.skipped += 1
            return
        code = get(s["code"])
        if code in (None, ""):
            self.skipped += 1
            return
        code = str(code).strip()
        if self.creates:
            kind = self.kind
            if s.get("kind_column") and get(s["kind_column"]):
                k = str(get(s["kind_column"]))
                if k not in self.kinds:
                    self.kinds[k] = w.kind(k, None, s.get("facets", {}).get(k, s.get("facet")))
                kind = self.kinds[k]
            status = 0
            st = s.get("status")
            if st and str(get(st["column"]) or "") in st["deprecated"]:
                status = 1
            w.term(code, kind=kind, status=status)
        elif not w.has(code):
            self.skipped += 1
            return
        self.rows += 1
        for lab in s.get("labels", []):
            v = get(lab["column"])
            if v in (None, ""):
                continue
            lang = get(lab["lang_column"]) if lab.get("lang_column") else lab.get("lang", "")
            for text in (str(v).split(lab["split"]) if lab.get("split") else [str(v)]):
                w.label(code, text, lang, lab.get("kind", "pref"))
        for b in s.get("broader", []):
            v = get(b["column"])
            if v not in (None, ""):
                for o in (str(v).split(b["split"]) if b.get("split") else [str(v)]):
                    if o.strip():
                        w.rel(code, self.pred(b.get("name", "parent"), "broader", b.get("iri")), o.strip())
        for r in s.get("relations", []):
            v = get(r["column"])
            if v not in (None, ""):
                for o in (str(v).split(r["split"]) if r.get("split") else [str(v)]):
                    if o.strip():
                        w.rel(code, self.pred(r.get("name", r["column"]), "relation", r.get("iri")), o.strip())
        for a in s.get("attrs", []):
            v = get(a["column"])
            if v not in (None, ""):
                w.attr(code, self.pred(a.get("name", str(a["column"])), "attr", a.get("iri"), datatype=a.get("type")),
                       _cast(v, a.get("type")), a.get("lang", ""))
        for n in s.get("notes", []):
            v = get(n["column"])
            if v not in (None, ""):
                w.attr(code, self.pred(n.get("name", str(n["column"])), "note", n.get("iri")), str(v), n.get("lang", ""))
        for ln in s.get("links", []):
            v = get(ln["column"])
            if v not in (None, ""):
                for t in (str(v).split(ln["split"]) if ln.get("split") else [str(v)]):
                    if t.strip():
                        w.link(code, self.pred(ln.get("name", str(ln["column"])), "link", ln.get("iri"), ln.get("map")),
                               ln.get("prefix", "") + t.strip())


def convert_csv(inputs: list[Input], w, options: dict, progress=print) -> None:
    if options.get("iri_template"):
        w.meta["iri_template"] = options["iri_template"]
    for spec in options["tables"]:
        m = _Mapper(w, spec)
        pattern = spec.get("members", "*")
        for inp in inputs:
            if spec.get("input") and spec["input"] != inp.name:
                continue
            for name, stream in members(inp, pattern):
                skip = spec.get("skip_prefix")
                lines = (ln for ln in text_lines(stream, spec.get("encoding", "utf-8-sig"))
                         if not (skip and ln.startswith(skip)))
                if spec.get("maxsplit") is not None:        # 'A000045 Fibonacci numbers.': split once, no quoting
                    reader = (ln.rstrip("\r\n").split(spec.get("delimiter", " "), spec["maxsplit"]) for ln in lines)
                else:
                    reader = csv.reader(lines, delimiter=spec.get("delimiter", ","),
                                        quoting=csv.QUOTE_NONE if spec.get("quoting") == "none" else csv.QUOTE_MINIMAL)
                header = next(reader) if spec.get("header", True) else None
                index = {h.strip(): k for k, h in enumerate(header)} if header else {}
                for row in reader:
                    def get(col, row=row):
                        k = index.get(col) if isinstance(col, str) else col
                        if k is None:
                            if isinstance(col, str) and header is not None:
                                raise KeyError(f"{name}: no column {col!r} (has {list(index)[:20]})")
                            return None
                        return row[k].strip() if k < len(row) and row[k] != "" else None
                    m.row(get)
                progress(f"    {name}: {m.rows:,} rows mapped, {m.skipped:,} skipped")


def convert_sqlite(inputs: list[Input], w, options: dict, progress=print) -> None:
    if options.get("iri_template"):
        w.meta["iri_template"] = options["iri_template"]
    for inp in inputs:
        db = sqlite3.connect(f"file:{inp.path}?mode=ro", uri=True)
        db.execute("PRAGMA query_only = 1")
        try:
            for spec in options["tables"]:
                m = _Mapper(w, spec)
                cur = db.execute(spec["sql"])
                cols = {d[0]: k for k, d in enumerate(cur.description)}
                for row in cur:
                    m.row(lambda col, row=row: (row[cols[col]] if isinstance(col, str) else row[col])
                          if (row[cols[col]] if isinstance(col, str) else row[col]) != "" else None)
                progress(f"    {inp.name}: {m.rows:,} rows mapped, {m.skipped:,} skipped")
        finally:
            db.close()
