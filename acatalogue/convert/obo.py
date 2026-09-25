"""OBO flat-file ontologies (Gene Ontology, ChEBI, Uberon, HPO, Disease Ontology, Mondo …) -> lean.

  [Term] id           the term; code GO_0008150, IRI http://purl.obolibrary.org/obo/GO_0008150
         name         preferred label (en)
         synonym      EXACT -> alternative; BROAD/NARROW/RELATED -> broader/narrower/related names
         def          the definition (a note), its cited sources kept as attributes
         comment      a note
         is_a         broader (subclass of)
         relationship part_of -> broader (partitive); every other relation kept under its own name
         intersection_of / union_of / disjoint_from   kept as attributes (the logical definition)
         xref         links (CURIEs such as MSH:D002453, Wikipedia:Cell_cycle)
         alt_id, subset, namespace, created_by, creation_date, property_value   attributes
         is_obsolete  deprecated; replaced_by -> replacement; consider -> links
  [Typedef]           names and IRIs of the relations (part_of = BFO_0000050 …)

Options: broader_relations (default ["part_of"]): relationship types read as hierarchy; id_prefix
(e.g. "MONDO"): keep only the ontology's own terms, not those it imports for its logical definitions.
"""
from __future__ import annotations

import re

from . import Input, members, text_lines

OBO_PURL = "http://purl.obolibrary.org/obo/"
_QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"\s*(.*)$')
_XREFS = re.compile(r"\[(.*)\]\s*(\{.*\})?\s*$")


def code_of(curie: str) -> str:
    """GO:0008150 -> GO_0008150 (the OBO Foundry's IRI form); other ids keep their shape."""
    return curie.strip().replace(":", "_", 1) if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*:[A-Za-z0-9_.\-]+", curie.strip()) \
        else curie.strip()


def _unq(s: str) -> str:
    return re.sub(r"\\(.)", r"\1", s)


def _strip_comment(v: str) -> str:
    """Values end at ' ! comment' (outside quotes) and trailing modifiers {…}."""
    out, q, i = [], False, 0
    while i < len(v):
        ch = v[i]
        if ch == "\\" and i + 1 < len(v):
            out.append(v[i:i + 2])
            i += 2
            continue
        if ch == '"':
            q = not q
        if not q and ch == "!" and (i == 0 or v[i - 1] == " "):
            break
        out.append(ch)
        i += 1
    return re.sub(r"\s*\{[^}]*\}\s*$", "", "".join(out)).strip()


def stanzas(lines):
    """(kind, [(tag, value)]) for the header ('header') and each stanza."""
    kind, tags = "header", []
    for line in lines:
        line = line.rstrip("\r\n")
        if not line.strip() or line.startswith("!"):
            continue
        if line.startswith("[") and line.rstrip().endswith("]"):
            yield kind, tags
            kind, tags = line.strip()[1:-1], []
            continue
        tag, sep, value = line.partition(":")
        if sep:
            tags.append((tag.strip(), value.strip()))
    yield kind, tags


def convert(inputs: list[Input], w, options: dict, progress=print) -> None:
    broader_rel = set(options.get("broader_relations", ["part_of"]))
    kind_term = w.kind("Class", "http://www.w3.org/2002/07/owl#Class")
    P = {
        "is_a": w.pred("is_a", "broader", "http://www.w3.org/2000/01/rdf-schema#subClassOf"),
        "def": w.pred("definition", "note", OBO_PURL + "IAO_0000115"),
        "def_xref": w.pred("definition_source", "attr", "http://www.geneontology.org/formats/oboInOwl#hasDbXref"),
        "comment": w.pred("comment", "note", "http://www.w3.org/2000/01/rdf-schema#comment"),
        "xref": w.pred("xref", "link", "http://www.geneontology.org/formats/oboInOwl#hasDbXref", map="relatedMatch"),
        "consider": w.pred("consider", "link", "http://www.geneontology.org/formats/oboInOwl#consider"),
        "replaced_by": w.pred("replaced_by", "replacedBy", OBO_PURL + "IAO_0100001"),
    }
    attr_tags = ("alt_id", "subset", "namespace", "created_by", "creation_date", "intersection_of", "union_of",
                 "disjoint_from", "equivalent_to")
    synonym_kind = {"EXACT": "alt", "BROAD": "broader", "NARROW": "narrower", "RELATED": "related"}
    typedefs: dict[str, dict] = {}
    rel_preds: dict[str, int] = {}
    header: dict[str, str] = {}
    pending: list[tuple] = []                   # relations: kept until the typedefs are known

    def rel_pred(name: str) -> int:
        if name not in rel_preds:
            td = typedefs.get(name, {})
            iri = td.get("iri")
            role = "broader" if name in broader_rel else "relation"
            rel_preds[name] = w.pred(name, role, iri)
        return rel_preds[name]

    n = 0
    for inp in inputs:
        for _, stream in members(inp, options.get("members", "*")):
            for kind, tags in stanzas(text_lines(stream)):
                if kind == "header":
                    header.update({k: v for k, v in tags if k in ("format-version", "data-version", "ontology",
                                                                    "date", "default-namespace")})
                    continue
                ids = [v for k, v in tags if k == "id"]
                if not ids:
                    continue
                if kind == "Typedef":
                    td = {"name": next((v for k, v in tags if k == "name"), ids[0])}
                    for k, v in tags:
                        if k == "xref" and re.fullmatch(r"BFO:\d+|RO:\d+", _strip_comment(v)):
                            td.setdefault("iri", OBO_PURL + code_of(_strip_comment(v)))
                    typedefs[ids[0]] = td
                    continue
                if kind != "Term":
                    continue
                if options.get("id_prefix") and not ids[0].startswith(options["id_prefix"] + ":"):
                    continue
                code = code_of(ids[0])
                w.term(code, kind=kind_term)
                n += 1
                for k, v in tags:
                    if k == "name":
                        w.label(code, v, "en", "pref")
                    elif k == "synonym":
                        m = _QUOTED.match(v)
                        if m:
                            rest = m.group(2).split()
                            scope = rest[0] if rest and rest[0] in synonym_kind else "RELATED"
                            w.label(code, _unq(m.group(1)), "en", synonym_kind[scope])
                    elif k == "def":
                        m = _QUOTED.match(v)
                        if m:
                            w.attr(code, P["def"], _unq(m.group(1)), "en")
                            x = _XREFS.search(m.group(2))
                            for ref in (x.group(1).split(",") if x else []):
                                if ref.strip():
                                    w.attr(code, P["def_xref"], ref.strip())
                    elif k == "comment":
                        w.attr(code, P["comment"], v, "en")
                    elif k == "is_a":
                        w.rel(code, P["is_a"], code_of(_strip_comment(v).split()[0]))
                    elif k == "relationship":
                        parts = _strip_comment(v).split()
                        if len(parts) >= 2:
                            pending.append((code, parts[0], code_of(parts[1])))
                    elif k == "xref":
                        w.link(code, P["xref"], _strip_comment(v).split(" ")[0])
                    elif k == "is_obsolete" and v.strip().lower() == "true":
                        w.term(code, status=1)
                    elif k == "replaced_by":
                        w.attr(code, P["replaced_by"], code_of(_strip_comment(v)))
                    elif k == "consider":
                        w.link(code, P["consider"], _strip_comment(v))
                    elif k in attr_tags:
                        w.attr(code, w.pred(k, "attr"), _strip_comment(v))
                    elif k == "property_value":
                        parts = _strip_comment(v).split(" ", 1)
                        if len(parts) == 2:
                            val = parts[1].strip()
                            m = _QUOTED.match(val)
                            w.attr(code, w.pred(parts[0], "attr"), _unq(m.group(1)) if m else val.split(" ")[0])
    for s, relname, o in pending:
        w.rel(s, rel_pred(relname), o)
    ont = header.get("ontology")
    w.meta["iri_template"] = OBO_PURL + "{code}"
    for k, v in header.items():
        w.meta[f"obo_{k.replace('-', '_')}"] = v
    progress(f"    {n:,} terms (ontology {ont or '?'}, version {header.get('data-version', '?')})")
