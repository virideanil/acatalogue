"""Converters: a source's published files -> one lean database (acatalogue/lean.py).

Every converter has the same signature, `convert(inputs, writer, options, progress)`, where `inputs`
are the verified files of one sealed manifest and `options` come from the registry (a JSON object).
Archives are read as streams (zip, gzip, bzip2, xz, tar): nothing is unpacked to disk.
"""
from __future__ import annotations

import bz2
import fnmatch
import gzip
import io
import lzma
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable, Iterator

VERSION = "1"            # bumped when any converter's output changes for the same inputs


@dataclass(frozen=True)
class Input:
    name: str
    path: Path
    sha512: str
    bytes: int
    url: str | None = None
    retrieved_at: str | None = None


class _Keep(io.BufferedIOBase):
    """A stream passed through as it is, whose closing leaves the underlying stream to its owner."""

    def __init__(self, f):
        self.f = f

    def readable(self) -> bool:
        return True

    def read(self, n: int = -1) -> bytes:
        return self.f.read(n)

    def read1(self, n: int = -1) -> bytes:
        return self.f.read1(n) if hasattr(self.f, "read1") else self.f.read(n)

    def readinto(self, b) -> int:
        data = self.read(len(b))
        b[:len(data)] = data
        return len(data)


def _decompress(f: BinaryIO, name: str) -> BinaryIO:
    low = name.lower()
    if low.endswith(".gz") or low.endswith(".tgz"):
        return gzip.GzipFile(fileobj=f)
    if low.endswith(".bz2"):
        return bz2.BZ2File(f)
    if low.endswith(".xz"):
        return lzma.LZMAFile(f)
    return _Keep(f)


class _Raw(io.RawIOBase):
    """A plain reader over a stream that can only read (a member of a streamed tar archive)."""

    def __init__(self, f):
        self.f = f

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:
        data = self.f.read(len(b))
        b[:len(data)] = data
        return len(data)


def members(inp: Input, pattern: str = "*") -> Iterator[tuple[str, BinaryIO]]:
    """(member name, binary stream) for every member of an archive matching `pattern` (the file itself,
    decompressed, when it is not an archive), in the archive's own order."""
    low = inp.name.lower()
    if low.endswith(".zip"):
        with zipfile.ZipFile(inp.path) as z:
            for info in z.infolist():
                if not info.is_dir() and fnmatch.fnmatch(info.filename, pattern):
                    with z.open(info) as f, _decompress(f, info.filename) as d:
                        yield info.filename, d
        return
    if low.endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz")):
        with tarfile.open(inp.path, "r|*") as t:                 # streaming: members in order
            for m in t:
                if m.isfile() and fnmatch.fnmatch(m.name, pattern):
                    f = t.extractfile(m)
                    if f is not None:
                        with io.BufferedReader(_Raw(f), 1 << 20) as b, _decompress(b, m.name) as d:
                            yield m.name, d
        return
    with open(inp.path, "rb") as raw, _decompress(raw, inp.name) as d:
        yield inp.name, d


def one(inputs: list[Input], pattern: str) -> Input:
    """The single input whose name matches `pattern`."""
    found = [i for i in inputs if fnmatch.fnmatch(i.name, pattern)]
    if len(found) != 1:
        raise ValueError(f"expected one input matching {pattern!r}, found {[i.name for i in found]}")
    return found[0]


def text_lines(stream: BinaryIO, encoding: str = "utf-8") -> Iterator[str]:
    """Lines of a binary stream; the stream stays open (its owner closes it)."""
    text = io.TextIOWrapper(stream, encoding=encoding, errors="strict", newline="")
    try:
        yield from text
    finally:
        text.detach()


def registry() -> dict[str, Callable]:
    from . import obo, rdf, sources, tables
    return {"rdf": rdf.convert, "obo": obo.convert, "csv": tables.convert_csv, "sqlite": tables.convert_sqlite,
            **sources.CONVERTERS}
