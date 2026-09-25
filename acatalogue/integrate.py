"""Lean sources into the catalogue: provenance first, then concepts, names, hierarchy, links, statements.

Modes (the registry's default, or the user's choice per source):
  full    every term becomes a concept `<scheme>/<code>`: its names (preferred, alternative, hidden; its
          definitions as descriptions), broader and related edges, kind facets, the mappings its links
          declare when the target's scheme is known, and every other statement as an attributed claim
  attach  the source is registered (scheme, exact bytes, counts) and stays in its lean file, where it is
          searched and read (`acat grep --source`, /api/sources); only mappings from Wikidata items
          enter the catalogue

Links between sources: a link's target (an IRI, a CURIE such as MSH:D002453, or a Wikidata external
identifier such as P1566:745044) becomes a scoped id when the registry says which scheme owns it.
Wikidata is the hub: every current Wikidata statement with a source's identifier property (GeoNames
P1566, MeSH P486 …) becomes a mapping from that item to the source's concept. Mappings declared by a
source are its assertions: they are recorded as proposed, never as accepted, until a person reviews them.

Re-integration is idempotent (the same lean file: nothing to do) and version-aware (a newer lean file
of the scheme: concepts updated, vanished ones deprecated, names and edges regenerated, claims
superseded). Nothing identity-bearing is deleted: concepts are deprecated, claims superseded.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from . import ledger
from .lean import LeanReader
from .textkeys import nfc
from .util import sha512_file, utcnow

_CODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\-]*")
DEFINITIONS = {"http://www.w3.org/2004/02/skos/core#definition", "http://purl.obolibrary.org/obo/IAO_0000115",
               "http://schema.org/description"}
SCOPE_NOTES = {"http://www.w3.org/2004/02/skos/core#scopeNote"}
LABEL_KIND = {0: "pref", 1: "alt", 2: "hidden", 3: "hidden", 4: "hidden", 5: "hidden"}
DISPLAY_LANGS = ("en", "mul", "", "und")


class Resolver:
    """Link targets -> scoped ids, from what the registry says about each scheme's identifiers:
    iri_prefixes ('https://sws.geonames.org/' or 'http://purl.obolibrary.org/obo/GO_|GO_{rest}'),
    curie_prefixes ('MSH', 'GO|GO_{rest}') and wikidata_property ('P1566')."""

    def __init__(self, entries: list[dict]):
        iri, curie, wdp = [("http://www.wikidata.org/entity/", "wd", "{rest}"),
                           ("https://www.wikidata.org/wiki/", "wd", "{rest}")], {}, {}
        for e in entries:
            scheme = e.get("scheme") or e["id"]
            for item in (e.get("iri_prefixes") or "").split():
                prefix, _, tpl = item.partition("|")
                iri.append((prefix, scheme, tpl or "{rest}"))
            for item in (e.get("curie_prefixes") or "").split():
                prefix, _, tpl = item.partition("|")
                curie[prefix.lower()] = (scheme, tpl or "{rest}")
            if e.get("wikidata_property"):
                wdp[e["wikidata_property"]] = scheme
        self.iri = sorted(iri, key=lambda x: -len(x[0]))
        self.curie = curie
        self.wdp = wdp

    def __call__(self, target: str) -> str | None:
        t = target.strip()
        for prefix, scheme, tpl in self.iri:
            if t.startswith(prefix):
                code = tpl.format(rest=t[len(prefix):].strip("/"))
                return f"{scheme}/{code}" if _CODE.fullmatch(code) else None
        m = re.fullmatch(r"(P\d+):(.+)", t)
        if m and m.group(1) in self.wdp:
            code = m.group(2).strip()
            return f"{self.wdp[m.group(1)]}/{code}" if _CODE.fullmatch(code) else None
        m = re.fullmatch(r"([A-Za-z][A-Za-z0-9_.\-]*):(\S+)", t)
        if m and not t.lower().startswith(("http:", "https:", "urn:")) and m.group(1).lower() in self.curie:
            scheme, tpl = self.curie[m.group(1).lower()]
            code = tpl.format(rest=m.group(2))
            return f"{scheme}/{code}" if _CODE.fullmatch(code) else None
        return None


def _register(conn, sha: str, size: int, kind: str, name: str, corpus: str | None, uri: str | None,
              retrieved_at: str | None, license: str | None, attribution: str | None,
              content_type: str | None = None) -> None:
    conn.execute("INSERT OR IGNORE INTO source(sha512, bytes, kind, name, corpus, uri, retrieved_at, content_type,"
                 " license, attribution, first_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 (sha, size, kind, name, corpus, uri, retrieved_at, content_type, license, attribution, utcnow()))


def _previous(conn, scheme: str) -> list[str]:
    return [r[0] for r in conn.execute("SELECT DISTINCT lean_sha512 FROM lean_integration WHERE scheme = ?", (scheme,))]


def _clear_regenerable(conn, scheme: str, shas: list[str]) -> dict:
    """Names, edges, facets and mappings a previous lean file of this scheme wrote (all regenerable)."""
    out = {}
    if not shas:
        return out
    marks = ",".join("?" * len(shas))
    for table in ("label", "broader", "related", "facet", "mapping"):
        out[table] = conn.execute(f"DELETE FROM {table} WHERE source_sha512 IN ({marks})", shas).rowcount
    return out


def integrate(conn: sqlite3.Connection, lean_path: str | Path, entry: dict, *, snapshot: str,
              manifest_sha512: str | None, mode: str, resolver: Resolver, store_path: str | None = None,
              actor: str = "acat sources", progress=print) -> dict:
    """One lean file into the catalogue (inside the caller's transaction)."""
    lean_path = Path(lean_path)
    scheme = entry.get("scheme") or entry["id"]
    lean_sha, size = sha512_file(lean_path)
    cur = conn.execute("SELECT lean_sha512, mode FROM v_lean_source WHERE scheme = ?", (scheme,)).fetchone()
    if cur is not None and tuple(cur) == (lean_sha, mode):
        return {"scheme": scheme, "skipped": "already integrated"}
    r = LeanReader(lean_path)
    try:
        return _integrate(conn, r, entry, scheme, lean_sha, size, snapshot, manifest_sha512, mode, resolver,
                          store_path or str(lean_path), actor, progress)
    finally:
        r.close()


def _integrate(conn, r: LeanReader, entry, scheme, lean_sha, size, snapshot, manifest_sha512, mode, resolver,
               lean_where, actor, progress) -> dict:
    now = utcnow()
    lic, attribution = entry.get("license") or r.meta.get("license"), entry.get("attribution") or r.meta.get("attribution")
    inputs = r.conn.execute("SELECT name, sha512, bytes, url, retrieved_at FROM input ORDER BY name").fetchall()
    for name, sha, n, url, at in inputs:
        _register(conn, sha, n, "fetch" if url and url.startswith("http") else "file", f"{snapshot}:{name}",
                  snapshot, url, at, lic, attribution)
    _register(conn, lean_sha, size, "file", f"lean:{scheme}:{Path(lean_where).name}", snapshot, lean_where, None,
              lic, attribution, "application/vnd.sqlite3")
    recorded = max((i[4] for i in inputs if i[4]), default=now)
    conn.execute("INSERT INTO scheme(id, title, description, origin, license, homepage, source_sha512)"
                 " VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title = excluded.title,"
                 " description = excluded.description, license = excluded.license, homepage = excluded.homepage,"
                 " source_sha512 = excluded.source_sha512",
                 (scheme, entry.get("title") or r.meta.get("title") or scheme,
                  entry.get("description") or entry.get("notes"), "external", lic,
                  entry.get("homepage") or r.meta.get("homepage"), lean_sha))
    previous = [s for s in _previous(conn, scheme) if s != lean_sha]
    cleared = _clear_regenerable(conn, scheme, previous + [lean_sha])
    stats: dict = {"scheme": scheme, "mode": mode, "lean_sha512": lean_sha, "cleared": cleared}
    if mode == "full":
        stats.update(_full(conn, r, scheme, lean_sha, recorded, resolver, progress))
        # claims of this very file set aside by an earlier attach or deselection are carried again
        stats["claims_restored"] = conn.execute("UPDATE claim SET superseded_at = NULL WHERE source_sha512 = ?"
                                                " AND superseded_at IS NOT NULL", (lean_sha,)).rowcount
        stats["superseded_claims"] = _supersede(conn, previous, now)
    else:                                       # attach: the lean file holds it; the catalogue carries none of it
        stats["deprecated"] = _deprecate_all(conn, scheme)
        stats["superseded_claims"] = _supersede(conn, previous + [lean_sha], now)
    stats["hub_mappings"] = _hub(conn, scheme, entry.get("wikidata_property"))
    counts = r.counts()
    conn.execute("INSERT INTO lean_integration(scheme, source, snapshot, manifest_sha512, lean_sha512, lean_path,"
                 " mode, counts, at) VALUES (?,?,?,?,?,?,?,?,?)",
                 (scheme, entry["id"], snapshot, manifest_sha512, lean_sha, lean_where, mode,
                  json.dumps({**counts, **{k: v for k, v in stats.items() if isinstance(v, int)}}, sort_keys=True), now))
    ledger.record(conn, actor, "integrate-source", target=f"scheme/{scheme}", detail=stats,
                  receipt=f"lean-sha512:{lean_sha[:32]};manifest:{(manifest_sha512 or '')[:32]}",
                  undo=f"`acat sources deselect {entry['id']}` then `acat build`: concepts deprecated, claims "
                       "superseded, names and edges removed (the lean file and raw bytes stay in the store)")
    return stats


def _full(conn, r: LeanReader, scheme: str, lean_sha: str, recorded: str, resolver: Resolver, progress) -> dict:
    rc = r.conn
    lang = dict(rc.execute("SELECT id, tag FROM lang"))
    preds = {i: {"name": n, "iri": iri, "role": role, "datatype": dt, "map": mp}
             for i, n, iri, role, dt, mp in rc.execute("SELECT id, name, iri, role, datatype, map FROM pred")}
    kinds = {i: facet for i, facet in rc.execute("SELECT id, facet FROM kind")}
    codes = dict(rc.execute("SELECT id, code FROM term"))
    cid = {i: f"{scheme}/{c}" for i, c in codes.items()}
    stats = {"concepts": 0, "new": 0, "labels": 0, "labels_demoted": 0, "labels_dropped_as_pref": 0,
             "broader": 0, "related": 0, "facets": 0, "mappings": 0, "links_unresolved": 0, "claims": 0}

    # names: one preferred per language (the first, in canonical order); an alternative equal to it goes
    prefs: dict[int, dict[str, str]] = {}
    label_rows = []
    seen_pref: set[tuple[int, str]] = set()
    pref_text: dict[tuple[int, str], str] = {}
    for t, lg, k, text in rc.execute("SELECT term, lang, kind, text FROM label ORDER BY term, kind, lang, text"):
        tag = lang[lg]
        kind = LABEL_KIND[k]
        if kind == "pref":
            if (t, tag) in seen_pref:
                kind = "alt"
                stats["labels_demoted"] += 1
            else:
                seen_pref.add((t, tag))
                pref_text[(t, tag)] = text
                prefs.setdefault(t, {})[tag] = text
        elif pref_text.get((t, tag)) == text:
            stats["labels_dropped_as_pref"] += 1
            continue
        label_rows.append((cid[t], tag, kind, nfc(text), lean_sha))
    # notes, notations, replacements; everything else literal is a claim
    scope: dict[int, tuple[int, str]] = {}
    notation: dict[int, str] = {}
    replaced: dict[int, str] = {}
    claims = []
    for t, p, lg, value in rc.execute("SELECT term, p, lang, value FROM attr ORDER BY term, p, lang, value"):
        pr, tag = preds[p], lang[lg]
        role, iri = pr["role"], pr["iri"] or ""
        if role == "note" and (iri in DEFINITIONS or pr["name"] in ("definition", "skos:definition")):
            label_rows.append((cid[t], tag, "desc", nfc(str(value)), lean_sha))
            rank = 0 if tag == "en" else 2
            if t not in scope or rank < scope[t][0]:
                scope[t] = (rank, str(value))
            continue
        if role == "note" and (iri in SCOPE_NOTES or pr["name"] in ("scopeNote", "skos:scopeNote")):
            rank = 1 if tag == "en" else 3
            if t not in scope or rank < scope[t][0]:
                scope[t] = (rank, str(value))
        if role == "notation" and t not in notation:
            notation[t] = str(value)
            continue
        if role == "replacedBy":
            v = str(value)
            replaced[t] = f"{scheme}/{v}" if r.conn.execute("SELECT 1 FROM term WHERE code = ?", (v,)).fetchone() \
                else (resolver(v) or v)
            continue
        claims.append(_literal_claim(cid[t], f"{scheme}/@{pr['name']}", value, tag, pr["datatype"], lean_sha, recorded))

    # concepts, in the source's order
    existing = {row[0]: row[1] for row in conn.execute("SELECT id, status FROM concept WHERE scheme = ?", (scheme,))}
    rows = []
    for t, code, kind, status in rc.execute("SELECT id, code, kind, status FROM term ORDER BY id"):
        names = prefs.get(t, {})
        label = next((names[l] for l in DISPLAY_LANGS if l in names), None) or \
            (names[sorted(names)[0]] if names else code)
        rows.append((cid[t], scheme, code, nfc(label), scope.get(t, (0, None))[1], notation.get(t),
                     "deprecated" if status else "active", replaced.get(t), lean_sha))
        stats["new"] += cid[t] not in existing
    conn.executemany(
        "INSERT INTO concept(id, scheme, code, label, scope_note, notation, status, replaced_by, source_sha512)"
        " VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET label = excluded.label,"
        " scope_note = excluded.scope_note, notation = excluded.notation, status = excluded.status,"
        " replaced_by = excluded.replaced_by, source_sha512 = excluded.source_sha512", rows)
    stats["concepts"] = len(rows)
    present = {row[0] for row in rows}
    gone = [c for c, s in existing.items() if s == "active" and c not in present]
    conn.executemany("UPDATE concept SET status = 'deprecated' WHERE id = ?", [(c,) for c in gone])
    stats["deprecated_vanished"] = len(gone)
    conn.executemany("INSERT OR IGNORE INTO label(concept_id, lang, kind, text, source_sha512) VALUES (?,?,?,?,?)",
                     label_rows)
    stats["labels"] = len(label_rows)
    progress(f"    {stats['concepts']:,} concepts ({stats['new']:,} new), {stats['labels']:,} names")

    # facets from kinds
    facet_ok = {f for f in set(kinds.values()) if f and conn.execute("SELECT 1 FROM concept WHERE id = ?", (f,)).fetchone()}
    conn.executemany("INSERT OR IGNORE INTO facet(concept_id, facet_id, source_sha512) VALUES (?,?,?)",
                     [(cid[t], kinds[k], lean_sha) for t, k in rc.execute("SELECT id, kind FROM term WHERE kind IS NOT NULL")
                      if kinds.get(k) in facet_ok])
    stats["facets"] = conn.execute("SELECT count(*) FROM facet WHERE source_sha512 = ?", (lean_sha,)).fetchone()[0]

    # relations inside the source
    broader, related = [], []
    for s, p, o in rc.execute("SELECT s, p, o FROM rel ORDER BY s, p, o"):
        role = preds[p]["role"]
        if role == "broader":
            broader.append((cid[s], cid[o], lean_sha))
        elif role == "related":
            a, b = sorted((cid[s], cid[o]))
            related.append((a, b, lean_sha))
        else:
            claims.append((cid[s], f"{scheme}/@{preds[p]['name']}", cid[o], None, "wikibase-item", lean_sha, recorded))
    conn.executemany("INSERT OR IGNORE INTO broader(child, parent, source_sha512) VALUES (?,?,?)", broader)
    conn.executemany("INSERT OR IGNORE INTO related(a, b, source_sha512) VALUES (?,?,?)", related)
    stats["broader"], stats["related"] = len(broader), len(related)

    # links out of the source: declared mappings (proposed), other links as claims
    maps = []
    for t, p, target in rc.execute("SELECT term, p, target FROM link ORDER BY term, p, target"):
        pr = preds[p]
        to = resolver(target)
        relation = pr["map"] or {"broader": "broadMatch", "related": "relatedMatch"}.get(pr["role"])
        if relation:
            if to and to != cid[t]:
                maps.append((cid[t], to, relation, f"declared:{scheme} ({pr['name']})", "proposed", None,
                             None, lean_sha))
            else:
                stats["links_unresolved"] += 1
            continue
        claims.append((cid[t], f"{scheme}/@{pr['name']}", to, None if to else target,
                       "wikibase-item" if to else ("url" if target.startswith(("http:", "https:")) else "external-id"),
                       lean_sha, recorded))
    conn.executemany("INSERT OR IGNORE INTO mapping(from_id, to_id, relation, method, status, reviewer, note,"
                     " source_sha512) VALUES (?,?,?,?,?,?,?,?)", maps)
    stats["mappings"] = len(maps)
    conn.executemany("INSERT OR IGNORE INTO claim(subject, predicate, object, value, datatype, epistemic,"
                     " source_sha512, recorded_at) VALUES (?,?,?,?,?,'epistemic/attributed',?,?)", claims)
    stats["claims"] = len(claims)
    progress(f"    {stats['broader']:,} broader, {stats['related']:,} related, {stats['mappings']:,} mappings,"
             f" {stats['claims']:,} claims")
    return stats


def _literal_claim(subject, predicate, value, lang, datatype, sha, recorded) -> tuple:
    if isinstance(value, bool) or value is None:
        value = str(value)
    if isinstance(value, int):
        return subject, predicate, None, str(value), "int", sha, recorded
    if isinstance(value, float):
        return subject, predicate, None, repr(value), "real", sha, recorded
    if lang:
        return (subject, predicate, None, json.dumps({"text": value, "language": lang}, ensure_ascii=False,
                                                     sort_keys=True), "monolingualtext", sha, recorded)
    return subject, predicate, None, str(value), datatype or "string", sha, recorded


def _supersede(conn, previous: list[str], now: str) -> int:
    if not previous:
        return 0
    marks = ",".join("?" * len(previous))
    return conn.execute(f"UPDATE claim SET superseded_at = ? WHERE superseded_at IS NULL AND source_sha512 IN ({marks})",
                        (now, *previous)).rowcount


def _deprecate_all(conn, scheme: str) -> int:
    return conn.execute("UPDATE concept SET status = 'deprecated' WHERE scheme = ? AND status = 'active'",
                        (scheme,)).rowcount


def _hub(conn, scheme: str, prop: str | None) -> int:
    """Mappings from Wikidata items to this scheme's concepts, read from Wikidata's own statements."""
    if not prop:
        return 0
    method = f"declared:wikidata ({prop})"
    conn.execute("DELETE FROM mapping WHERE method = ? AND to_id LIKE ?", (method, f"{scheme}/%"))
    rows = [(s, f"{scheme}/{v.strip()}", "exactMatch", method, "proposed", None, None, sha)
            for s, v, sha in conn.execute("SELECT subject, value, source_sha512 FROM claim WHERE predicate = ?"
                                          " AND superseded_at IS NULL AND value IS NOT NULL AND snak_type = 'value'",
                                          (f"wd/{prop}",))
            if _CODE.fullmatch(v.strip())]
    conn.executemany("INSERT OR IGNORE INTO mapping(from_id, to_id, relation, method, status, reviewer, note,"
                     " source_sha512) VALUES (?,?,?,?,?,?,?,?)", [r for r in rows
                                                                    if conn.execute("SELECT 1 FROM concept WHERE id = ?", (r[0],)).fetchone()])
    return conn.execute("SELECT count(*) FROM mapping WHERE method = ? AND to_id LIKE ?",
                        (method, f"{scheme}/%")).fetchone()[0]


def retire(conn: sqlite3.Connection, scheme: str, source: str, actor: str = "acat sources") -> dict:
    """A deselected source leaves the catalogue's current view: its concepts deprecated, its names, edges,
    facets and mappings removed (regenerable), its claims superseded; the record of it stays."""
    cur = conn.execute("SELECT lean_sha512, snapshot, lean_path, mode FROM v_lean_source WHERE scheme = ?",
                       (scheme,)).fetchone()
    if cur is None or cur[3] == "removed":
        return {"scheme": scheme, "skipped": "not integrated"}
    shas = _previous(conn, scheme)
    now = utcnow()
    stats = {"scheme": scheme, "cleared": _clear_regenerable(conn, scheme, shas),
             "deprecated": _deprecate_all(conn, scheme), "superseded_claims": _supersede(conn, shas, now)}
    conn.execute("DELETE FROM mapping WHERE method LIKE 'declared:wikidata (%' AND to_id LIKE ?", (f"{scheme}/%",))
    conn.execute("INSERT INTO lean_integration(scheme, source, snapshot, manifest_sha512, lean_sha512, lean_path, mode,"
                 " counts, at) VALUES (?,?,?,NULL,?,?,'removed','{}',?)", (scheme, source, cur[1], cur[0], cur[2], now))
    ledger.record(conn, actor, "retire-source", target=f"scheme/{scheme}", detail=stats,
                  undo=f"`acat sources select {source}` then `acat build`")
    return stats
