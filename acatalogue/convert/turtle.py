"""Turtle (RDF 1.1), streamed: a tokenizer over a growing buffer and a recursive-descent parser.

Covers the whole Turtle grammar: @prefix/@base and SPARQL-style PREFIX/BASE, prefixed names with
escapes, `a`, predicate lists (;) and object lists (,), blank-node labels, [] and [ … ] property lists,
( … ) collections, short and long strings in either quote, language tags, datatypes, and numeric and
boolean literals. Yields the same tuples as the N-Triples reader: (s, p, o, literal?, lang, datatype).
"""
from __future__ import annotations

import io
import re
from urllib.parse import urljoin

RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
XSD = "http://www.w3.org/2001/XMLSchema#"

_PN = ("A-Za-z0-9_\u00B7\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u037D\u037F-\u1FFF\u200C-\u200D\u203F-\u2040"
       "\u2070-\u218F\u2C00-\u2FEF\u3001-\uD7FF\uF900-\uFDCF\uFDF0-\uFFFD\U00010000-\U000EFFFF\\-")
_ESC = r"\\[_~.\-!$&'()*+,;=/?#@%]"
_PLX = "(?:[" + _PN + ":]|%[0-9A-Fa-f]{2}|" + _ESC + ")"
Q3D = '"' * 3
Q3S = "'" * 3
_LONG_D = Q3D + r'(?:[^"\\]|\\.|"(?!"")|""(?!"))*' + Q3D
_LONG_S = Q3S + r"(?:[^'\\]|\\.|'(?!'')|''(?!'))*" + Q3S
_TOKEN = re.compile(
    r"(?P<ws>(?:\s+|#[^\n]*(?:\n|\Z))+)"
    r'|(?P<iri><(?:[^<>"{}|^`\\\x00-\x20]|\\u[0-9A-Fa-f]{4}|\\U[0-9A-Fa-f]{8})*>)'
    "|(?P<long>" + _LONG_D + "|" + _LONG_S + ")"
    r'|(?P<str>"(?:[^"\\\n\r]|\\.)*"' + r"|'(?:[^'\\\n\r]|\\.)*')"
    r"|(?P<lang>@[A-Za-z]+(?:-[A-Za-z0-9]+)*)"
    r"|(?P<dt>\^\^)"
    "|(?P<bnode>_:[" + _PN + "](?:[" + _PN + ".]*[" + _PN + "])?)"
    r"|(?P<num>[+-]?(?:\d+\.\d*[eE][+-]?\d+|\.\d+[eE][+-]?\d+|\d+[eE][+-]?\d+|\d*\.\d+|\d+))"
    "|(?P<pname>(?:[A-Za-z\u00C0-\uFFFD](?:[" + _PN + ".]*[" + _PN + "])?)?:"
    "(?:" + _PLX + "(?:(?:" + _PLX + r"|\.)*" + _PLX + ")?)?)"
    r"|(?P<punct>[.,;()\[\]])"
    r"|(?P<word>[A-Za-z]+)")
_UESC = re.compile(r'\\(?:u([0-9A-Fa-f]{4})|U([0-9A-Fa-f]{8})|(.))')
_SIMPLE = {"t": "\t", "b": "\b", "n": "\n", "r": "\r", "f": "\f", '"': '"', "'": "'", "\\": "\\"}


def _unescape(s: str) -> str:
    if "\\" not in s:
        return s
    return _UESC.sub(lambda m: chr(int(m.group(1) or m.group(2), 16)) if (m.group(1) or m.group(2))
                     else _SIMPLE.get(m.group(3), m.group(3)), s)


def tokens(stream):
    """(kind, text) tokens; reads on while a token could still be growing at the end of the buffer."""
    reader = io.TextIOWrapper(stream, encoding="utf-8", errors="strict", newline="")
    buf, pos, eof = "", 0, False
    try:
        while True:
            if not eof and len(buf) - pos < 1 << 16:
                chunk = reader.read(1 << 20)
                buf, pos, eof = buf[pos:] + chunk, 0, not chunk
            if pos >= len(buf):
                if eof:
                    return
                continue
            m = _TOKEN.match(buf, pos)
            if (m is None or m.end() == len(buf)) and not eof:
                chunk = reader.read(1 << 20)             # the token may continue past the buffer
                buf, pos, eof = buf[pos:] + chunk, 0, not chunk
                continue
            if m is None:
                raise ValueError(f"Turtle: cannot read {buf[pos:pos + 80]!r}")
            pos = m.end()
            if m.lastgroup != "ws":
                yield m.lastgroup, m.group()
    finally:
        reader.detach()


def _string(tok: str) -> str:
    body = tok[3:-3] if tok[:3] in (Q3D, Q3S) else tok[1:-1]
    return _unescape(body)


def parse(stream, doc: int, base: str = ""):
    toks = tokens(stream)
    look: list[tuple[str, str]] = []
    prefixes: dict[str, str] = {}
    base_ = [base]
    counter = [0]
    out: list[tuple] = []

    def peek():
        if not look:
            nxt = next(toks, None)
            if nxt is None:
                return None
            look.append(nxt)
        return look[0]

    def take():
        if peek() is None:
            raise ValueError("Turtle: unexpected end of file")
        return look.pop(0)

    def expect(text: str) -> None:
        t = take()
        if t[1] != text:
            raise ValueError(f"Turtle: expected {text!r}, found {t[1]!r}")

    def fresh() -> str:
        counter[0] += 1
        return f"_:{doc}:t{counter[0]}"

    def iri_of(kind: str, text: str) -> str:
        if kind == "iri":
            v = _unescape(text[1:-1])
            return urljoin(base_[0], v) if base_[0] else v
        if kind != "pname":
            raise ValueError(f"Turtle: expected an IRI, found {text!r}")
        pre, _, local = text.partition(":")
        if pre not in prefixes:
            raise ValueError(f"Turtle: undeclared prefix {pre!r}")
        return prefixes[pre] + re.sub(r"\\(.)", r"\1", local)

    def term(position: str):
        kind, text = take()
        if kind in ("iri", "pname"):
            return iri_of(kind, text), False, None, None
        if kind == "bnode":
            return f"_:{doc}:{text[2:]}", False, None, None
        if text == "[":
            node = fresh()
            if peek() and peek()[1] == "]":
                take()
                return node, False, None, None
            predicate_objects(node)
            expect("]")
            return node, False, None, None
        if text == "(":
            items = []
            while peek() and peek()[1] != ")":
                items.append(term("object"))
            take()
            head = RDF + "nil"
            for item in reversed(items):
                cell = fresh()
                out.append((cell, RDF + "first", *item))
                out.append((cell, RDF + "rest", head, False, None, None))
                head = cell
            return head, False, None, None
        if position == "object":
            if kind in ("str", "long"):
                value = _string(text)
                nxt = peek()
                if nxt and nxt[0] == "lang":
                    take()
                    return value, True, nxt[1][1:], None
                if nxt and nxt[0] == "dt":
                    take()
                    k, t = take()
                    return value, True, None, iri_of(k, t)
                return value, True, None, None
            if kind == "num":
                dt = "double" if re.search("[eE]", text) else "decimal" if "." in text else "integer"
                return text, True, None, XSD + dt
            if kind == "word" and text in ("true", "false"):
                return text, True, None, XSD + "boolean"
        raise ValueError(f"Turtle: unexpected {text!r}")

    def predicate_objects(subject: str) -> None:
        while True:
            kind, text = take()
            pred = RDF + "type" if (kind == "word" and text == "a") else iri_of(kind, text)
            while True:
                obj = term("object")
                out.append((subject, pred, *obj))
                if peek() and peek()[1] == ",":
                    take()
                    continue
                break
            while peek() and peek()[1] == ";":
                take()
            nxt = peek()
            if nxt is None or nxt[1] in (".", "]"):
                return

    while peek() is not None:
        kind, text = peek()
        if (kind == "lang" and text in ("@prefix", "@base")) or (kind == "word" and text.upper() in ("PREFIX", "BASE")):
            take()
            if text.lower().endswith("prefix"):
                _, name = take()
                k2, iri = take()
                prefixes[name[:-1]] = iri_of(k2, iri)
            else:
                k2, iri = take()
                base_[0] = iri_of(k2, iri)
            if text.startswith("@"):
                expect(".")
            continue
        subject = term("subject")[0]
        if peek() and peek()[1] != ".":
            predicate_objects(subject)
        expect(".")
        yield from out
        out.clear()
