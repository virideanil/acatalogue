"""Lexical and code resources.

  wn-lmf        wordnets in the Global WordNet Association's LMF XML (Open English WordNet, the Open
                Multilingual Wordnet's 31 languages …). With key "ili" (the default) a synset is keyed by
                its Interlingual Index id, so every language's words for one meaning land on one term:
                one concept, named in every wordnet that has it. Hypernymy is the hierarchy (hyponym
                turned round, never stored twice); meronymy and the other relations are kept one way
                each; definitions and examples in their wordnet's language.
  iana-subtags  the IANA Language Subtag Registry (BCP 47; CC0): languages, extlangs, scripts, regions,
                variants, grandfathered and redundant tags, with macrolanguages, deprecations and the
                preferred replacements
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from . import Input, members, text_lines

# relation -> (stored name, role, turn round?): each inverse pair is stored once, in one direction
WN_RELATIONS = {
    "hypernym": ("hypernym", "broader", False), "hyponym": ("hypernym", "broader", True),
    "instance_hypernym": ("instance_hypernym", "broader", False),
    "instance_hyponym": ("instance_hypernym", "broader", True),
    "holo_member": ("holo_member", "relation", False), "mero_member": ("holo_member", "relation", True),
    "holo_part": ("holo_part", "relation", False), "mero_part": ("holo_part", "relation", True),
    "holo_substance": ("holo_substance", "relation", False), "mero_substance": ("holo_substance", "relation", True),
    "domain_topic": ("domain_topic", "relation", False), "has_domain_topic": ("domain_topic", "relation", True),
    "domain_region": ("domain_region", "relation", False), "has_domain_region": ("domain_region", "relation", True),
    "exemplifies": ("exemplifies", "relation", False), "is_exemplified_by": ("exemplifies", "relation", True),
    "entails": ("entails", "relation", False), "is_entailed_by": ("entails", "relation", True),
    "causes": ("causes", "relation", False), "is_caused_by": ("causes", "relation", True),
    "similar": ("similar", "related", False), "also": ("also", "related", False),
    "antonym": ("antonym", "related", False),
}


SYMMETRIC = {"derivation"}                     # (related-role relations are ordered by the writer)


def wn_lmf(inputs: list[Input], w, options: dict, progress=print) -> None:
    key_ili = options.get("key", "ili") == "ili"
    w.meta["iri_template"] = "http://ili.globalwordnet.org/ili/{code}" if key_ili else None
    kind = w.kind("Synset", "http://www.w3.org/ns/lemon/ontolex#LexicalConcept")
    definition = w.pred("definition", "note", "http://www.w3.org/2004/02/skos/core#definition")
    example = w.pred("example", "note", "http://www.w3.org/2004/02/skos/core#example")
    pos_p = w.pred("partOfSpeech", "attr")
    lexfile = w.pred("lexfile", "attr")
    synset_id = w.pred("synset", "link", map="exactMatch")
    preds: dict[str, int] = {}
    code_of: dict[str, str] = {}              # synset id -> term code (its ILI when keyed by ILI)
    pending: list[tuple[str, str, str]] = []  # (synset, relType, target synset), resolved at the end
    sense_synset: dict[str, str] = {}
    lexicons = []
    n_syn = n_words = 0
    for inp in inputs:
        for name, stream in members(inp, options.get("members", "*.xml*")):
            lang, words = None, {}
            for event, el in ET.iterparse(stream, events=("start", "end")):
                tag = el.tag
                if event == "start":
                    if tag == "Lexicon":
                        lang = el.get("language")
                        lexicons.append(f"{el.get('id')}:{lang}:{el.get('version')}")
                    continue
                if tag == "LexicalEntry":
                    lemma = el.find("Lemma")
                    form = lemma.get("writtenForm") if lemma is not None else None
                    for sense in el.findall("Sense"):
                        sense_synset[sense.get("id")] = sense.get("synset")
                        if form:
                            words.setdefault(sense.get("synset"), []).append((el.get("id"), form))
                        for rel in sense.findall("SenseRelation"):
                            pending.append((sense.get("synset"), rel.get("relType"), "sense:" + rel.get("target")))
                    el.clear()
                elif tag == "Synset":
                    sid = el.get("id")
                    ili = el.get("ili") or ""
                    code = ili if key_ili and re.fullmatch(r"i\d+", ili) else sid
                    code_of[sid] = code
                    w.term(code, kind=kind)
                    if code != sid:
                        w.link(code, synset_id, sid)
                    members_order = (el.get("members") or "").split()
                    entries = words.pop(sid, [])
                    forms = [f for _, f in entries]
                    if members_order:                  # the wordnet's own order: its first member heads it
                        rank = {m: k for k, m in enumerate(members_order)}
                        forms = [f for _, f in sorted(entries, key=lambda e: rank.get(e[0], 1 << 30))]
                    for k, f in enumerate(dict.fromkeys(forms)):
                        w.label(code, f.replace("_", " "), lang, "pref" if k == 0 else "alt")
                        n_words += 1
                    for d in el.findall("Definition"):
                        w.attr(code, definition, d.text, d.get("language") or lang)
                    for x in el.findall("Example"):
                        w.attr(code, example, x.text, x.get("language") or lang)
                    if el.get("partOfSpeech"):
                        w.attr(code, pos_p, el.get("partOfSpeech"))
                    if el.get("lexfile"):
                        w.attr(code, lexfile, el.get("lexfile"))
                    for rel in el.findall("SynsetRelation"):
                        pending.append((sid, rel.get("relType"), rel.get("target")))
                    n_syn += 1
                    el.clear()
    for s, rel, t in pending:
        if t.startswith("sense:"):
            t = sense_synset.get(t[6:])
        if s not in code_of or t not in code_of or code_of[s] == code_of[t]:
            continue
        name, role, turn = WN_RELATIONS.get(rel, (rel, "relation", False))
        if name not in preds:
            preds[name] = w.pred(name, role, f"https://globalwordnet.github.io/gwadoc/#{name}")
        a, b = (code_of[t], code_of[s]) if turn else (code_of[s], code_of[t])
        if name in SYMMETRIC:                          # one row per pair, whichever side stated it
            a, b = sorted((a, b))
        w.rel(a, preds[name], b)
    w.meta["lexicons"] = " ".join(lexicons)
    progress(f"    {n_syn:,} synsets, {n_words:,} words, {len(lexicons)} lexicons")


# ─── IANA Language Subtag Registry ──────────────────────────────────────────


def _records(stream):
    rec, key = {}, None
    for line in text_lines(stream):
        line = line.rstrip("\r\n")
        if line == "%%":
            if rec:
                yield rec
            rec, key = {}, None
        elif line[:1] in (" ", "\t") and key:
            rec[key][-1] += " " + line.strip()
        elif ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            rec.setdefault(key, []).append(value.strip())
    if rec:
        yield rec


def iana_subtags(inputs: list[Input], w, options: dict, progress=print) -> None:
    w.meta["iri_template"] = None
    facets = {"language": "kind/symbol-system", "extlang": "kind/symbol-system", "script": "kind/symbol-system",
              "region": "kind/place", "variant": "kind/symbol-system", "grandfathered": "kind/symbol-system",
              "redundant": "kind/symbol-system"}
    kinds = {t: w.kind(t, None, f) for t, f in facets.items()}
    macro = w.pred("macrolanguage", "broader")
    prefix = w.pred("prefix", "relation")
    suppress = w.pred("suppressScript", "relation")
    preferred = w.pred("preferredValue", "replacedBy")
    comments = w.pred("comments", "note")
    P = {k: w.pred(k, "attr") for k in ("added", "deprecated", "scope")}
    m49 = w.pred("m49", "link", map="exactMatch")
    n = 0
    pending = []
    for inp in inputs:
        for name, stream in members(inp, options.get("members", "*")):
            for rec in _records(stream):
                if "Type" not in rec:
                    if "File-Date" in rec:
                        w.meta["file_date"] = rec["File-Date"][0]
                    continue
                typ = rec["Type"][0]
                sub = (rec.get("Subtag") or rec.get("Tag"))[0]
                code = f"{typ}.{sub}"
                w.term(code, kind=kinds.get(typ), status=1 if rec.get("Deprecated") else 0)
                for k, d in enumerate(rec.get("Description", [])):
                    w.label(code, d, "en", "pref" if k == 0 else "alt")
                for k, attr in (("Added", "added"), ("Deprecated", "deprecated"), ("Scope", "scope")):
                    for v in rec.get(k, []):
                        w.attr(code, P[attr], v)
                for c in rec.get("Comments", []):
                    w.attr(code, comments, c, "en")
                if rec.get("Preferred-Value"):
                    ptype = "language" if typ in ("extlang", "grandfathered", "redundant") else typ
                    w.attr(code, preferred, f"{ptype}.{rec['Preferred-Value'][0]}")
                for m in rec.get("Macrolanguage", []):
                    pending.append((code, macro, f"language.{m}"))
                for p in rec.get("Prefix", []):
                    first = p.split("-")[0]
                    pending.append((code, prefix if typ != "extlang" else macro, f"language.{first}"))
                for s in rec.get("Suppress-Script", []):
                    pending.append((code, suppress, f"script.{s}"))
                if typ == "region" and sub.isdigit():
                    w.link(code, m49, f"m49:{sub}")
                n += 1
    for s, p, o in pending:
        w.rel(s, p, o)
    progress(f"    {n:,} records")
