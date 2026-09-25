"""Human review: decisions by named people, kept apart from the machine proposals they judge.

The crosswalk seed (seed/crosswalk/acat-wikidata.tsv) records what was proposed and who proposed it;
today that is an AI agent for almost every Wikidata link. People record decisions in
seed/reviews/<reviewer>.tsv, one row per decision (`acat review approve|revise|object`). The build
applies the latest human decision on top of the proposal: an objection takes a mapping out of use, a
revision can change its relation. Nothing is overwritten: the proposal stays in the crosswalk, every
review is a row, and the effective mapping names both in its method and note.

A review by an agent is recorded like any other but never changes the effective state: a machine's
second opinion is still a machine's.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from . import ledger
from .compendium import SEED_DIR, SeedError, SeedFile, read_tsv, upsert_source_seed
from .util import utcnow

REVIEW_DIR = SEED_DIR / "reviews"
COLUMNS = ["target", "decision", "relation", "reviewer", "reviewer_kind", "perspective", "decided_at", "rationale"]
DECISIONS = ("approve", "revise", "object")
RELATIONS = ("exactMatch", "closeMatch", "broadMatch", "narrowMatch", "relatedMatch")
_ISO = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")


def mapping_target(frm: str, to: str) -> str:
    return f"mapping:{frm}|{to}"


def row_problems(r: dict, where: str) -> list[str]:
    out = []
    if not re.fullmatch(r"(mapping|concept|label):\S.*", r["target"]):
        out.append(f"{where}: target must start with mapping:, concept: or label:")
    if r["decision"] not in DECISIONS:
        out.append(f"{where}: decision must be one of {', '.join(DECISIONS)}")
    if r["relation"] and (r["decision"] != "revise" or r["relation"] not in RELATIONS):
        out.append(f"{where}: a relation goes only with 'revise' and must be one of {', '.join(RELATIONS)}")
    if not r["reviewer"] or r["reviewer_kind"] not in ("human", "agent"):
        out.append(f"{where}: a named reviewer and reviewer_kind human|agent are required")
    if not _ISO.fullmatch(r["decided_at"]):
        out.append(f"{where}: decided_at must be UTC like 2026-09-25T18:00:00Z")
    if r["decision"] in ("revise", "object") and not r["rationale"]:
        out.append(f"{where}: a revision or objection needs a rationale")
    for k in COLUMNS:
        if "\t" in r[k] or "\n" in r[k]:
            out.append(f"{where}: {k} cannot contain tabs or line breaks")
    return out


def read_reviews(directory: Path | None = None) -> tuple[list[SeedFile], list[str]]:
    files, problems = [], []
    for path in sorted((directory or REVIEW_DIR).glob("*.tsv")):
        try:
            sf = read_tsv(path, COLUMNS)
        except SeedError as exc:
            problems.append(str(exc))
            continue
        for r in sf.rows:
            problems += row_problems(r, f"{sf.rel}:{r['_line']}")
        files.append(sf)
    return files, problems


def apply_to_decisions(decisions: list[dict], files: list[SeedFile]) -> list[dict]:
    """The effective crosswalk: each proposal with the latest human decision about it applied."""
    latest: dict[str, tuple[dict, SeedFile]] = {}
    for sf in files:
        for r in sf.rows:
            if r["reviewer_kind"] == "human" and r["target"].startswith("mapping:"):
                prev = latest.get(r["target"])
                if prev is None or r["decided_at"] >= prev[0]["decided_at"]:
                    latest[r["target"]] = (r, sf)
    out = []
    for d in decisions:
        hit = latest.get(mapping_target(d["from"], d["to"]))
        if hit is None:
            out.append(d)
            continue
        r, sf = hit
        proposed = f"proposed {d['relation']}/{d['status']} by {d['reviewer'] or 'seed'}"
        said = f"{r['decision']} by {r['reviewer']} {r['decided_at'][:10]}" + (f": {r['rationale']}" if r["rationale"] else "")
        e = {**d, "reviewer": r["reviewer"], "note": "; ".join(x for x in (d["note"], proposed, said) if x),
             "review_sha512": sf.sha512}
        if r["decision"] == "approve":
            e.update(status="accepted", method=f"{d['method']}+human-approved")
        elif r["decision"] == "revise":
            e.update(status="accepted", relation=r["relation"] or d["relation"], method=f"{d['method']}+human-revised")
        else:
            e.update(status="rejected", method=f"{d['method']}+human-objected")
        out.append(e)
    return out


def load(conn: sqlite3.Connection, files: list[SeedFile], actor: str = "acat build") -> dict:
    """Review rows into the review table (regenerated from the seed files on every build)."""
    conn.execute("DELETE FROM review WHERE source_sha512 IN (SELECT sha512 FROM source WHERE kind = 'seed'"
                 " AND name LIKE 'seed/reviews/%')")
    stats = {"files": len(files), "reviews": 0, "human": 0, "dangling": []}
    for sf in files:
        upsert_source_seed(conn, sf)
        for r in sf.rows:
            kind, _, ref = r["target"].partition(":")
            if kind == "mapping":
                frm, _, to = ref.partition("|")
                ok = conn.execute("SELECT 1 FROM mapping WHERE from_id = ? AND to_id = ?", (frm, to)).fetchone()
            elif kind == "concept":
                ok = conn.execute("SELECT 1 FROM concept WHERE id = ?", (ref,)).fetchone()
            else:
                cid, lang, text = (ref.split("|", 2) + ["", ""])[:3]
                ok = conn.execute("SELECT 1 FROM label WHERE concept_id = ? AND lang = ? AND text = ?",
                                  (cid, lang, text)).fetchone()
            if not ok:
                stats["dangling"].append(f"{sf.rel}:{r['_line']} {r['target']}")
            conn.execute("INSERT OR REPLACE INTO review(target, reviewer, reviewer_kind, perspective, decided_at,"
                         " decision, relation, rationale, source_sha512) VALUES (?,?,?,?,?,?,?,?,?)",
                         (r["target"], r["reviewer"], r["reviewer_kind"], r["perspective"] or None, r["decided_at"],
                          r["decision"], r["relation"] or None, r["rationale"] or None, sf.sha512))
            stats["reviews"] += 1
            stats["human"] += r["reviewer_kind"] == "human"
    if files:
        ledger.record(conn, actor, "load-reviews", target="seed/reviews",
                      detail={k: (len(v) if isinstance(v, list) else v) for k, v in stats.items()},
                      receipt=";".join(f"{sf.rel}:{sf.sha512[:32]}" for sf in files),
                      undo="reviews are regenerated from seed/reviews/ on every build")
    return stats


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "reviewer"


def append(reviewer: str, target: str, decision: str, *, relation: str = "", kind: str = "human",
           perspective: str = "", rationale: str = "", directory: Path | None = None) -> Path:
    """Append one decision to the reviewer's file (created with its header if new)."""
    row = dict(zip(COLUMNS, [target, decision, relation, reviewer, kind, perspective, utcnow(), rationale]))
    problems = row_problems(row, "new review")
    if problems:
        raise SeedError("\n".join(problems))              # nothing is written
    directory = directory or REVIEW_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{slug(reviewer)}.tsv"
    new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        if new:
            f.write("\t".join(COLUMNS) + "\n")
        f.write("\t".join(row[k] for k in COLUMNS) + "\n")
    return path


def reviewer_kind(reviewer: str | None) -> str:
    """Who stands behind a crosswalk decision, read from its reviewer field."""
    r = (reviewer or "").lower()
    if not r:
        return "none"
    if r == "seed":
        return "seed file (no named reviewer)"
    if "ai agent" in r or r.startswith("claude"):
        return "AI agent"
    return "human"
