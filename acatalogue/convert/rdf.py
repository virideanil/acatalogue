"""SKOS, SKOS-XL and OWL vocabularies published as RDF: N-Triples, N-Quads or RDF/XML (plain or
compressed, alone or in archives) -> lean.

Two passes. The triples stream into a staging database (IRIs interned as integers); then the things
the vocabulary is about are chosen by type (skos:Concept, ConceptScheme, Collection, owl:Class, …)
and read out subject by subject: labels (SKOS, SKOS-XL literal forms, rdfs:label, OBO synonyms),
hierarchy in one direction (broader; narrower is turned round; member and top-concept links placed
under their collection or scheme), related once, notes (including notes published as resources
with rdf:value), notations, deprecation and replacement, mappings and every other link. A predicate
the converter does not know is kept, as an attribute (literal) or a relation or link (thing), under
its own name: nothing a vocabulary states is dropped for being unfamiliar.

Options (registry, JSON): term_types (extra type IRIs), iri_prefix (the vocabulary's namespace, when
the most common one is not it), members ('*.nt' …, which archive members to read), base (for RDF/XML).
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin

from . import Input, members, text_lines

RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
OWL = "http://www.w3.org/2002/07/owl#"
SKOS = "http://www.w3.org/2004/02/skos/core#"
SKOSXL = "http://www.w3.org/2008/05/skos-xl#"
DCT = "http://purl.org/dc/terms/"
DC = "http://purl.org/dc/elements/1.1/"
XSD = "http://www.w3.org/2001/XMLSchema#"
OBO = "http://purl.obolibrary.org/obo/"
OBOINOWL = "http://www.geneontology.org/formats/oboInOwl#"
ISOTHES = "http://purl.org/iso25964/skos-thes#"
PREFIXES = {RDF: "rdf", RDFS: "rdfs", OWL: "owl", SKOS: "skos", SKOSXL: "skosxl", DCT: "dct", DC: "dc", XSD: "xsd",
            OBO: "obo", OBOINOWL: "oboInOwl", ISOTHES: "isothes", "http://xmlns.com/foaf/0.1/": "foaf",
            "http://schema.org/": "schema", "https://schema.org/": "schema", "http://www.w3.org/ns/prov#": "prov",
            "http://www.geonames.org/ontology#": "gn", "http://www.w3.org/2003/01/geo/wgs84_pos#": "wgs84",
            "http://rdfs.org/ns/void#": "void", "http://purl.org/vocab/vann/": "vann",
            "http://creativecommons.org/ns#": "cc", "http://www.wikidata.org/prop/direct/": "wdt",
            "http://lexvo.org/ontology#": "lexvo", "http://vocab.getty.edu/ontology#": "gvp",
            "http://www.w3.org/ns/dcat#": "dcat", "http://purl.org/ontology/bibo/": "bibo"}

TERM_TYPES = [SKOS + "Concept", SKOS + "ConceptScheme", SKOS + "Collection", SKOS + "OrderedCollection",
              ISOTHES + "ConceptGroup", ISOTHES + "ThesaurusArray", OWL + "Class", RDFS + "Class"]
LABELS = {SKOS + "prefLabel": "pref", SKOS + "altLabel": "alt", SKOS + "hiddenLabel": "hidden",
          OBOINOWL + "hasExactSynonym": "alt", OBOINOWL + "hasBroadSynonym": "broader",
          OBOINOWL + "hasNarrowSynonym": "narrower", OBOINOWL + "hasRelatedSynonym": "related"}
XL_LABELS = {SKOSXL + "prefLabel": "pref", SKOSXL + "altLabel": "alt", SKOSXL + "hiddenLabel": "hidden"}
SECOND_NAMES = (RDFS + "label", DCT + "title", DC + "title")          # a name when no prefLabel says otherwise
BROADER_UP = (SKOS + "broader", RDFS + "subClassOf", ISOTHES + "superGroup")       # s narrower than o
BROADER_DOWN = (SKOS + "narrower", ISOTHES + "subGroup")                            # o narrower than s
UNDER_O = (SKOS + "topConceptOf",)                                   # s placed under o (its scheme)
UNDER_S = (SKOS + "hasTopConcept", SKOS + "member")                  # o placed under s
# an inverse is stored as the predicate it mirrors, so a vocabulary stating both directions gives one row
INVERSE_OF = {SKOS + "narrower": SKOS + "broader", ISOTHES + "subGroup": ISOTHES + "superGroup",
              SKOS + "hasTopConcept": SKOS + "topConceptOf"}
DERIVED = (SKOS + "broaderTransitive", SKOS + "narrowerTransitive")  # entailments: not stored
RELATED = (SKOS + "related",)
MATCH = {SKOS + "exactMatch": "exactMatch", SKOS + "closeMatch": "closeMatch", SKOS + "broadMatch": "broadMatch",
         SKOS + "narrowMatch": "narrowMatch", SKOS + "relatedMatch": "relatedMatch", OWL + "sameAs": "exactMatch",
         OWL + "equivalentClass": "exactMatch"}
NOTES = (SKOS + "definition", SKOS + "scopeNote", SKOS + "note", SKOS + "example", SKOS + "historyNote",
         SKOS + "editorialNote", SKOS + "changeNote", RDFS + "comment", DCT + "description", OBO + "IAO_0000115")
NOTATION = SKOS + "notation"
REPLACED = (DCT + "isReplacedBy", OBO + "IAO_0100001")
DBXREF = OBOINOWL + "hasDbXref"
NUMERIC = {XSD + t: int for t in ("integer", "int", "long", "short", "nonNegativeInteger", "positiveInteger",
                                  "negativeInteger", "nonPositiveInteger", "unsignedInt", "unsignedLong")}
NUMERIC.update({XSD + t: float for t in ("decimal", "double", "float")})
_CODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\-]*")


# ─── parsing: triples as (s, p, o, literal?, lang, datatype) ────────────────

_NT = re.compile(
    r'\s*(<[^>]*>|_:\S+)\s+(<[^>]*>)\s+'
    r'(<[^>]*>|_:\S+|"(?:[^"\\]|\\.)*"(?:@[A-Za-z]+(?:-[A-Za-z0-9]+)*|\^\^<[^>]*>)?)'
    r'(?:\s+(?:<[^>]*>|_:\S+))?\s*\.\s*(?:#.*)?$')
_LIT = re.compile(r'"((?:[^"\\]|\\.)*)"(?:@([A-Za-z]+(?:-[A-Za-z0-9]+)*)|\^\^<([^>]*)>)?$')
_ESC = re.compile(r'\\(?:u([0-9A-Fa-f]{4})|U([0-9A-Fa-f]{8})|(.))')
_SIMPLE = {"t": "\t", "b": "\b", "n": "\n", "r": "\r", "f": "\f", '"': '"', "'": "'", "\\": "\\"}


def _unescape(s: str) -> str:
    if "\\" not in s:
        return s
    return _ESC.sub(lambda m: chr(int(m.group(1) or m.group(2), 16)) if (m.group(1) or m.group(2))
                    else _SIMPLE.get(m.group(3), m.group(3)), s)


def ntriples(stream, doc: int):
    """N-Triples / N-Quads lines (the graph of a quad is set aside)."""
    for n, line in enumerate(text_lines(stream), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _NT.match(line)
        if not m:
            raise ValueError(f"N-Triples line {n} does not parse: {line[:120]!r}")
        s, p, o = m.group(1), m.group(2), m.group(3)
        s = f"_:{doc}:{s[2:]}" if s.startswith("_:") else _unescape(s[1:-1])
        p = _unescape(p[1:-1])
        if o.startswith("<"):
            yield s, p, _unescape(o[1:-1]), False, None, None
        elif o.startswith("_:"):
            yield s, p, f"_:{doc}:{o[2:]}", False, None, None
        else:
            lm = _LIT.match(o)
            yield s, p, _unescape(lm.group(1)), True, lm.group(2), lm.group(3)


def rdfxml(stream, doc: int, base: str = ""):
    """RDF/XML, streamed: node and property elements, rdf:about/ID/nodeID/resource, typed nodes,
    property attributes, parseType Resource/Literal/Collection, xml:lang and xml:base."""
    XML_LANG, XML_BASE = "{http://www.w3.org/XML/1998/namespace}lang", "{http://www.w3.org/XML/1998/namespace}base"
    counter = [0]

    def bnode(label: str | None = None) -> str:
        if label is None:
            counter[0] += 1
            label = f"g{counter[0]}"
        return f"_:{doc}:{label}"

    def iri(tag: str) -> str:
        return tag[1:].replace("}", "", 1) if tag.startswith("{") else tag

    stack: list[dict] = []         # frames: {"type": node|prop|coll, "s", "p", "lang", "base", ...}
    root = None
    li = {}
    for event, el in ET.iterparse(stream, events=("start", "end")):
        if event == "start":
            if root is None:
                root = el
            parent = stack[-1] if stack else None
            lang = el.get(XML_LANG, parent["lang"] if parent else None)
            b = urljoin(parent["base"] if parent else base, el.get(XML_BASE)) if el.get(XML_BASE) else \
                (parent["base"] if parent else base)
            tag = iri(el.tag)
            if parent is None and tag == RDF + "RDF":
                stack.append({"type": "rdf", "lang": lang, "base": b})
                continue
            if parent is None or parent["type"] in ("rdf", "prop", "coll"):          # a node element
                if el.get(f"{{{RDF}}}about") is not None:
                    s = urljoin(b, el.get(f"{{{RDF}}}about"))
                elif el.get(f"{{{RDF}}}ID") is not None:
                    s = urljoin(b, "#" + el.get(f"{{{RDF}}}ID"))
                elif el.get(f"{{{RDF}}}nodeID") is not None:
                    s = bnode(el.get(f"{{{RDF}}}nodeID"))
                else:
                    s = bnode()
                if tag != RDF + "Description":
                    yield s, RDF + "type", tag, False, None, None
                for k, v in el.attrib.items():
                    k = iri(k)
                    if not k.startswith((RDF, "http://www.w3.org/XML/1998/namespace")):
                        yield s, k, v, True, lang, None
                if parent is not None and parent["type"] == "prop":
                    yield parent["s"], parent["p"], s, False, None, None
                    parent["filled"] = True
                elif parent is not None and parent["type"] == "coll":
                    parent["items"].append(s)
                stack.append({"type": "node", "s": s, "lang": lang, "base": b})
                continue
            # a property element (child of a node)
            p = tag
            if p == RDF + "li":
                li[parent["s"]] = li.get(parent["s"], 0) + 1
                p = f"{RDF}_{li[parent['s']]}"
            frame = {"type": "prop", "s": parent["s"], "p": p, "lang": lang, "base": b, "filled": False,
                     "dt": el.get(f"{{{RDF}}}datatype"), "parse": el.get(f"{{{RDF}}}parseType")}
            res, nid = el.get(f"{{{RDF}}}resource"), el.get(f"{{{RDF}}}nodeID")
            if res is not None:
                yield parent["s"], p, urljoin(b, res), False, None, None
                frame["filled"] = True
            elif nid is not None:
                yield parent["s"], p, bnode(nid), False, None, None
                frame["filled"] = True
            if frame["parse"] == "Resource":
                o = bnode()
                yield parent["s"], p, o, False, None, None
                stack.append({"type": "node", "s": o, "lang": lang, "base": b, "prop_of": True})
                continue
            if frame["parse"] == "Collection":
                frame.update(type="coll", items=[])
                stack.append(frame)
                continue
            extra = {iri(k): v for k, v in el.attrib.items()
                     if not iri(k).startswith((RDF, "http://www.w3.org/XML/1998/namespace"))}
            if extra:                                   # property attributes on an empty property element
                o = urljoin(b, res) if res is not None else bnode(nid) if nid else bnode()
                if not frame["filled"]:
                    yield parent["s"], p, o, False, None, None
                    frame["filled"] = True
                for k, v in extra.items():
                    yield o, k, v, True, lang, None
            stack.append(frame)
        else:
            frame = stack.pop()
            if frame["type"] == "prop" and not frame["filled"]:
                if frame["parse"] == "Literal":
                    text = (el.text or "") + "".join(ET.tostring(c, encoding="unicode") for c in el)
                    yield frame["s"], frame["p"], text, True, None, RDF + "XMLLiteral"
                else:
                    dt = urljoin(frame["base"], frame["dt"]) if frame["dt"] else None
                    yield frame["s"], frame["p"], el.text or "", True, None if dt else frame["lang"], dt
            elif frame["type"] == "coll":
                head = RDF + "nil"
                for item in reversed(frame["items"]):
                    cell = bnode()
                    yield cell, RDF + "first", item, False, None, None
                    yield cell, RDF + "rest", head, False, None, None
                    head = cell
                yield frame["s"], frame["p"], head, False, None, None
            if len(stack) <= 1 and root is not None:    # a top-level node is done: free its tree
                el.clear()
                if stack and stack[0]["type"] == "rdf":
                    root.clear()


def triples(inp: Input, doc: int, options: dict):
    pattern = options.get("members", "*")
    for name, stream in members(inp, pattern):
        low = name.lower()
        for ext in (".gz", ".bz2", ".xz"):
            if low.endswith(ext):
                low = low[: -len(ext)]
        if low.endswith((".nt", ".nq", ".ntriples", ".nquads")):
            yield from ntriples(stream, doc)
        elif low.endswith((".rdf", ".xml", ".owl", ".skos")):
            yield from rdfxml(stream, doc, options.get("base") or inp.url or "")
        else:
            raise ValueError(f"{name}: not a format this converter reads (N-Triples, N-Quads, RDF/XML)")
        doc += 1


# ─── staging and extraction ─────────────────────────────────────────────────


def curie(iri: str) -> str:
    for ns, prefix in PREFIXES.items():
        if iri.startswith(ns) and len(iri) > len(ns):
            return f"{prefix}:{iri[len(ns):]}"
    return iri


def _split(iri: str) -> tuple[str, str]:
    cut = max(iri.rfind("/"), iri.rfind("#"), iri.rfind(":") if "://" not in iri else -1)
    return iri[:cut + 1], iri[cut + 1:]


def convert(inputs: list[Input], w, options: dict, progress=print) -> None:
    stage_path = Path(str(w.path) + ".stage")
    stage_path.unlink(missing_ok=True)
    st = sqlite3.connect(stage_path, isolation_level=None)
    st.execute("PRAGMA journal_mode = OFF")
    st.execute("PRAGMA synchronous = OFF")
    st.execute("CREATE TABLE t (s INTEGER, p INTEGER, o INTEGER, lit TEXT, lang TEXT, dt INTEGER)")
    st.execute("BEGIN")
    nodes: dict[str, int] = {}

    def nid(v: str) -> int:
        i = nodes.get(v)
        if i is None:
            i = nodes[v] = len(nodes) + 1
        return i

    n = 0
    buf = []
    try:
        for k, inp in enumerate(inputs):
            for s, p, o, is_lit, lang, dt in triples(inp, k * 1000, options):
                buf.append((nid(s), nid(p), None if is_lit else nid(o), o if is_lit else None,
                            lang, nid(dt) if dt else None))
                n += 1
                if len(buf) >= 100_000:
                    st.executemany("INSERT INTO t VALUES (?,?,?,?,?,?)", buf)
                    buf.clear()
                    if n % 1_000_000 == 0:
                        progress(f"    {n:,} triples")
        if buf:
            st.executemany("INSERT INTO t VALUES (?,?,?,?,?,?)", buf)
        st.execute("CREATE INDEX t_s ON t(s)")
        st.execute("COMMIT")
        progress(f"    {n:,} triples, {len(nodes):,} nodes staged")
        _extract(st, nodes, w, options, progress)
    finally:
        st.close()
        stage_path.unlink(missing_ok=True)


def _extract(st: sqlite3.Connection, nodes: dict[str, int], w, options: dict, progress) -> None:
    name_of = {i: v for v, i in nodes.items()}
    I = nodes.get
    types = [I(t) for t in TERM_TYPES + list(options.get("term_types", [])) if I(t)]
    if not types:
        raise ValueError("no skos:Concept, owl:Class or other term type in these files; "
                         "name the vocabulary's types in the registry options (term_types)")
    rdf_type = I(RDF + "type")
    marks = ",".join(map(str, types))
    type_rank = {t: k for k, t in enumerate(types)}
    first_type: dict[int, int] = {}
    for s, o in st.execute(f"SELECT s, o FROM t WHERE p = ? AND o IN ({marks}) ORDER BY s", (rdf_type,)):
        if not name_of[s].startswith("_:") and (s not in first_type or type_rank[o] < type_rank[first_type[s]]):
            first_type[s] = o
    terms = sorted(first_type)                       # the vocabulary's order of first mention
    # codes: the local part of each IRI; the most common namespace (or iri_prefix) makes the template
    spaces = Counter(_split(name_of[t])[0] for t in terms)
    ns = options.get("iri_prefix") or (spaces.most_common(1)[0][0] if spaces else "")
    w.meta["iri_template"] = ns + "{code}" if ns else None
    code_of: dict[int, str] = {}
    taken: set[str] = set()
    for t in terms:
        iri = name_of[t]
        local = iri[len(ns):] if ns and iri.startswith(ns) else _split(iri)[1]
        if not _CODE.fullmatch(local) or local in taken:
            local = "x" + hashlib.sha256(iri.encode()).hexdigest()[:20]
        taken.add(local)
        code_of[t] = local
    kinds = {t: w.kind(_split(name_of[t])[1] or name_of[t], name_of[t]) for t in types}
    for t in terms:
        iri = name_of[t]
        w.term(code_of[t], kind=kinds[first_type[t]], iri=None if ns and iri == ns + code_of[t] else iri)
    progress(f"    {len(terms):,} terms of {len(types)} types")

    def props(node: int):
        return st.execute("SELECT p, o, lit, lang, dt FROM t WHERE s = ?", (node,)).fetchall()

    def literals_of(node: int, pred: str):
        pi = I(pred)
        return [(lit, lang) for p, o, lit, lang, dt in props(node) if p == pi and lit is not None] if pi else []

    def typed(lit: str, dt: int | None):
        cast = NUMERIC.get(name_of.get(dt, "")) if dt else None
        if cast:
            try:
                return cast(lit)
            except ValueError:
                return lit
        return lit

    preds: dict[tuple[int, str], int] = {}
    named: set[str] = set()

    def pred(p: int, role: str, map: str | None = None, suffix: str = "") -> int:
        """One predicate per (IRI, role): an IRI used with literals and with things gets two names."""
        key = (p, role + suffix)
        if key not in preds:
            iri = name_of[p]
            nm = curie(iri) + suffix
            if nm in named:
                nm = f"{nm}#{role}"
            named.add(nm)
            preds[key] = w.pred(nm, role, iri=iri, map=map)
        return preds[key]

    def up(p: int) -> int:        # a relation read upwards: narrower -> broader
        iri = name_of[p]
        if iri in INVERSE_OF:     # the mirrored predicate itself (interned even if the files never use it)
            mirror = INVERSE_OF[iri]
            if mirror not in nodes:
                nodes[mirror] = len(nodes) + 1
                name_of[nodes[mirror]] = mirror
            return pred(nodes[mirror], "broader")
        if iri in BROADER_DOWN or iri in UNDER_S:                    # no named inverse: '^-1' marks the turn
            return pred(p, "broader", suffix="^-1")
        return pred(p, "broader")

    deprecated_iris = {OWL + "deprecated"}
    termset = set(terms)
    for k, t in enumerate(terms, 1):
        code = code_of[t]
        rows = props(t)
        have_pref = {lang or "" for p, o, lit, lang, dt in rows if name_of[p] == SKOS + "prefLabel" and lit is not None}
        status = 0
        for p, o, lit, lang, dt in rows:
            pi = name_of[p]
            if pi == RDF + "type":
                if o is not None and name_of[o] == OWL + "DeprecatedClass":
                    status = 1
                continue
            if lit is not None:
                if pi in LABELS:
                    w.label(code, lit, lang, LABELS[pi])
                elif pi in SECOND_NAMES:
                    w.label(code, lit, lang, "alt" if (lang or "") in have_pref else "pref")
                elif pi in NOTES:
                    w.attr(code, pred(p, "note"), lit, lang)
                elif pi == NOTATION:
                    w.attr(code, pred(p, "notation"), typed(lit, dt))
                elif pi in deprecated_iris:
                    status = 1 if lit.strip().lower() in ("true", "1") else status
                elif pi == DBXREF:
                    w.link(code, pred(p, "link", "relatedMatch"), lit)
                else:
                    w.attr(code, pred(p, "attr"), typed(lit, dt), lang)
                continue
            target = name_of[o]
            if pi in XL_LABELS:                                    # SKOS-XL: the label is a resource
                for text, lang in literals_of(o, SKOSXL + "literalForm"):
                    w.label(code, text, lang, XL_LABELS[pi])
            elif pi in NOTES:                                      # a note published as a resource
                for text, lang in literals_of(o, RDF + "value"):
                    w.attr(code, pred(p, "note"), text, lang)
            elif pi in DERIVED:
                continue
            elif pi in BROADER_UP or pi in UNDER_O:
                if pi == RDFS + "subClassOf" and target.startswith("_:"):
                    _restriction(st, o, code, code_of, name_of, w, pred, I)
                elif o in termset:
                    w.rel(code, up(p), code_of[o])
                else:
                    w.link(code, up(p), target)
            elif pi in BROADER_DOWN or pi in UNDER_S:
                if o in termset:
                    w.rel(code_of[o], up(p), code)
            elif pi in RELATED:
                if o in termset:
                    w.rel(code, pred(p, "related"), code_of[o])
                else:
                    w.link(code, pred(p, "related"), target)
            elif pi in MATCH:
                w.link(code, pred(p, "link", MATCH[pi]), target)
            elif pi in REPLACED:
                w.attr(code, pred(p, "replacedBy"), code_of.get(o, target))
            elif o in termset:
                w.rel(code, pred(p, "relation"), code_of[o])
            elif not target.startswith("_:"):
                w.link(code, pred(p, "link"), target)
        if status:
            w.term(code, status=1)
        if k % 50_000 == 0:
            progress(f"    {k:,} of {len(terms):,} terms read")


def _restriction(st, b, code, code_of, name_of, w, pred, I) -> None:
    """rdfs:subClassOf an owl:Restriction (onProperty P, someValuesFrom C): the relation P to C."""
    rows = st.execute("SELECT p, o FROM t WHERE s = ?", (b,)).fetchall()
    on = next((o for p, o in rows if name_of[p] == OWL + "onProperty"), None)
    some = next((o for p, o in rows if name_of[p] == OWL + "someValuesFrom"), None)
    if on is not None and some is not None and some in code_of:
        w.rel(code, pred(on, "relation"), code_of[some])
