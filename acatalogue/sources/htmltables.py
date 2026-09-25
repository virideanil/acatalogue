"""Extract tables from HTML with the standard library parser (no regex over markup)."""
from __future__ import annotations

from html.parser import HTMLParser


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: dict[str, list[list[str]]] = {}
        self._stack: list[tuple[str, list[list[str]]]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._anon = 0

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            ident = dict(attrs).get("id") or f"table-{self._anon}"
            self._anon += 1
            rows: list[list[str]] = []
            self._stack.append((ident.strip(), rows))
        elif tag == "tr" and self._stack:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None and self._stack:
            self._stack[-1][1].append(self._row)
            self._row = None
        elif tag == "table" and self._stack:
            ident, rows = self._stack.pop()
            self.tables[ident] = rows

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def tables(html_text: str) -> dict[str, list[list[str]]]:
    p = _TableParser()
    p.feed(html_text)
    p.close()
    return p.tables
