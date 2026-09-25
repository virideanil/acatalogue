"""The source registry: which open sources exist, what they hold, where they come from, how to read them.

  seed/sources/registry.tsv   one row per source: who publishes it and from where (its perspective),
                              domains, languages, licence, the converter and its options, the catalogue
                              scheme it becomes, how its identifiers look (IRI and CURIE prefixes, the
                              Wikidata property that holds them), the default mode (full or attach),
                              who reviewed the entry and what was verified live
  seed/sources/files.tsv      one row per downloadable file: URL, format, size, the publisher's checksum
  seed/sources/presets.tsv    named starting points (a preset is a list of sources)

A user adds sources of their own to their store (`acat sources add`): a URL, or a file on their own
machine (a SQLite database, a CSV, an RDF dump). They sit beside the reviewed registry with the same
columns and never replace a reviewed entry.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .compendium import SEED_DIR, SeedError, read_tsv

SOURCE_DIR = SEED_DIR / "sources"
COLUMNS = ["id", "title", "publisher", "perspective", "domains", "kind", "languages", "license", "license_url",
           "homepage", "update", "access", "converter", "options", "scheme", "integrate", "iri_prefixes",
           "curie_prefixes", "wikidata_property", "size", "recommend", "reviewer", "verified", "notes"]
FILE_COLUMNS = ["source", "name", "url", "format", "bytes", "checksum", "role", "verified"]
PRESET_COLUMNS = ["preset", "source", "note"]
DOMAINS = {f"acat/{d}" for d in ("arts", "belief", "earth", "everyday", "health", "language", "life", "matter", "mind",
                                 "past", "society", "technology", "thought")}
_ID = re.compile(r"[a-z0-9][a-z0-9\-]*")
_SCHEME = re.compile(r"[a-z0-9][a-z0-9\-]*")
RESERVED = {"acat", "space", "kind", "epistemic", "udc", "ddc", "lcc", "propaedia", "wd", "doc", "src"}


@dataclass
class Registry:
    sources: dict[str, dict] = field(default_factory=dict)
    files: dict[str, list[dict]] = field(default_factory=dict)
    presets: dict[str, list[str]] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    shas: dict[str, str] = field(default_factory=dict)

    def scheme(self, sid: str) -> str:
        return self.sources[sid].get("scheme") or sid

    def options(self, sid: str) -> dict:
        raw = self.sources[sid].get("options") or "{}"
        return json.loads(raw)

    def mode(self, sid: str, chosen: str | None = None) -> str:
        return chosen or self.sources[sid].get("integrate") or "full"

    def expand(self, names: list[str]) -> list[str]:
        """Source ids for a list of source ids and 'preset:<name>' entries."""
        out = []
        for n in names:
            if n.startswith("preset:"):
                p = n.split(":", 1)[1]
                if p not in self.presets:
                    raise KeyError(f"no preset {p!r} (have: {', '.join(sorted(self.presets))})")
                out += self.presets[p]
            elif n in self.sources:
                out.append(n)
            else:
                raise KeyError(f"no source {n!r} in the registry or this store")
        return list(dict.fromkeys(out))


def row_problems(r: dict, where: str, converters: set[str]) -> list[str]:
    out = []
    if not _ID.fullmatch(r["id"]):
        out.append(f"{where}: id must be lower-case letters, digits and '-'")
    for k in ("title", "license", "converter", "reviewer"):
        if not r.get(k):
            out.append(f"{where}: {k} is required")
    if r.get("converter") and r["converter"] not in converters:
        out.append(f"{where}: converter {r['converter']!r} is not one of {', '.join(sorted(converters))}")
    try:
        opts = json.loads(r.get("options") or "{}")
        if not isinstance(opts, dict):
            out.append(f"{where}: options must be a JSON object")
    except ValueError as exc:
        out.append(f"{where}: options are not JSON ({exc})")
    scheme = r.get("scheme") or r["id"]
    if not _SCHEME.fullmatch(scheme) or scheme in RESERVED:
        out.append(f"{where}: scheme {scheme!r} must be a new lower-case id (not one of {', '.join(sorted(RESERVED))})")
    if r.get("integrate") and r["integrate"] not in ("full", "attach"):
        out.append(f"{where}: integrate must be full or attach")
    for d in filter(None, (r.get("domains") or "").split()):
        if d not in DOMAINS:
            out.append(f"{where}: unknown domain {d!r}")
    if r.get("wikidata_property") and not re.fullmatch(r"P\d+", r["wikidata_property"]):
        out.append(f"{where}: wikidata_property must look like P1566")
    if r.get("recommend") and r["recommend"] not in ("starter", "yes", "later", "no"):
        out.append(f"{where}: recommend must be starter, yes, later or no")
    return out


def file_problems(f: dict, where: str) -> list[str]:
    out = []
    if not f["name"] or "/" in f["name"] or f["name"].startswith("."):
        out.append(f"{where}: name must be a plain file name")
    if not re.match(r"(https?://|file://|/)", f["url"]):
        out.append(f"{where}: url must be http(s)://, file:// or an absolute path")
    if f.get("bytes") and not f["bytes"].isdigit():
        out.append(f"{where}: bytes must be an integer")
    c = f.get("checksum") or ""
    if c and not re.fullmatch(r"(md5:[0-9a-f]{32}|sha1:[0-9a-f]{40}|sha256:[0-9a-f]{64}|sha512:[0-9a-f]{128}|url:https?://\S+)", c):
        out.append(f"{where}: checksum must be md5|sha1|sha256|sha512:<hex> or url:<checksum file URL>")
    return out


def read(store=None, directory: Path | None = None) -> Registry:
    from .convert import registry as converter_registry
    converters = set(converter_registry())
    d = directory or SOURCE_DIR
    reg = Registry()
    if (d / "registry.tsv").exists():
        try:
            sf = read_tsv(d / "registry.tsv", COLUMNS)
            reg.shas["registry"] = sf.sha512
            for r in sf.rows:
                where = f"{sf.rel}:{r['_line']}"
                reg.problems += row_problems(r, where, converters)
                if r["id"] in reg.sources:
                    reg.problems.append(f"{where}: duplicate id {r['id']}")
                reg.sources[r["id"]] = {**r, "origin": "registry"}
        except SeedError as exc:
            reg.problems.append(str(exc))
    if (d / "files.tsv").exists():
        try:
            sf = read_tsv(d / "files.tsv", FILE_COLUMNS)
            reg.shas["files"] = sf.sha512
            for f in sf.rows:
                where = f"{sf.rel}:{f['_line']}"
                reg.problems += file_problems(f, where)
                if f["source"] not in reg.sources:
                    reg.problems.append(f"{where}: no source {f['source']!r} in registry.tsv")
                reg.files.setdefault(f["source"], []).append(f)
        except SeedError as exc:
            reg.problems.append(str(exc))
    if (d / "presets.tsv").exists():
        try:
            sf = read_tsv(d / "presets.tsv", PRESET_COLUMNS)
            reg.shas["presets"] = sf.sha512
            for p in sf.rows:
                if p["source"] not in reg.sources:
                    reg.problems.append(f"{sf.rel}:{p['_line']}: preset {p['preset']} names unknown source {p['source']}")
                reg.presets.setdefault(p["preset"], []).append(p["source"])
        except SeedError as exc:
            reg.problems.append(str(exc))
    for sid, entry in reg.sources.items():
        if not reg.files.get(sid):
            reg.problems.append(f"source {sid}: no files in files.tsv")
        names = [f["name"] for f in reg.files.get(sid, [])]
        if len(names) != len(set(names)):
            reg.problems.append(f"source {sid}: two files share a name")
    if store is not None:                                   # the user's own sources, beside the reviewed ones
        for r in store.conn.execute("SELECT * FROM user_source ORDER BY id"):
            r = dict(r)
            if r["id"] in reg.sources:
                reg.problems.append(f"store: {r['id']} is already a registry source; choose another id")
                continue
            reg.sources[r["id"]] = {**{k: r.get(k) or "" for k in COLUMNS}, "reviewer": "the store's owner",
                                    "origin": "user"}
            reg.files[r["id"]] = [{**{k: "" for k in FILE_COLUMNS}, **{k: (str(v) if v is not None else "")
                                                                       for k, v in dict(f).items()}}
                                  for f in store.conn.execute("SELECT * FROM user_file WHERE source = ? ORDER BY name",
                                                              (r["id"],))]
    return reg


def conflicts(reg: Registry, selected: list[str]) -> list[str]:
    """Two selected sources that would write the same catalogue scheme (e.g. two sizes of GeoNames)."""
    by: dict[str, list[str]] = {}
    for s in selected:
        by.setdefault(reg.scheme(s), []).append(s)
    return [f"{', '.join(v)} all become scheme {k!r}: select one" for k, v in by.items() if len(v) > 1]
