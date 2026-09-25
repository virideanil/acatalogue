"""Bias audit against declared baselines. The numbers make skew visible; they never certify its absence,
and they are never collapsed into one score.

Regional representation: each ACAT concept tagged with places counts once, split evenly over the
regions its places fall in (fractional counting). Its share per region is compared with three declared
baselines (population, land area, equal shares): log2 representation ratios with Wilson intervals,
Jensen-Shannon divergence with a bootstrap interval and a random-sampling null, normalized entropy,
and the Gini coefficient of the ratios. Sibling parity compares concepts that share a parent.
Attention counts Wikipedia editions without the bot-generated Cebuano and Waray ones.

Every run is stored (audit_run, audit_metric) with the ledger head it describes.
"""
from __future__ import annotations

import json
import math
import random
import sqlite3
import statistics
from collections import defaultdict

from . import ledger
from .review import reviewer_kind
from .util import utcnow

SEED = 20260925
BOOTSTRAP = 2000
Z = 1.959964                      # two-sided 95%
BASELINES = ("population", "land_area", "equal")
BOT_WIKIS = ("cebwiki", "warwiki")
PARITY_QUANTITIES = ("subtree", "scope_note_chars", "alt_labels", "mappings", "label_langs")
PRIORITY_DOMAINS = ("acat/belief", "acat/past", "acat/society", "acat/language")


# ─── statistics ─────────────────────────────────────────────────────────────


def wilson(p: float, n: float, z: float = Z) -> tuple[float, float]:
    """Wilson score interval for a proportion (Wilson 1927)."""
    if n <= 0:
        return 0.0, 1.0
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def jsd(p: list[float], q: list[float]) -> float:
    """Jensen-Shannon divergence in bits (Lin 1991); 0 = identical, 1 = disjoint."""
    total = 0.0
    for a, b in zip(p, q):
        m = (a + b) / 2
        if a > 0:
            total += 0.5 * a * math.log2(a / m)
        if b > 0:
            total += 0.5 * b * math.log2(b / m)
    return max(0.0, total)


def entropy_norm(p: list[float]) -> float | None:
    """Shannon entropy divided by its maximum, log2 K: 1 = perfectly even over the K groups."""
    k = len(p)
    if k < 2:
        return None
    return -sum(x * math.log2(x) for x in p if x > 0) / math.log2(k)


def gini(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    if not xs or sum(xs) == 0:
        return None
    mean = sum(xs) / len(xs)
    return sum(abs(a - b) for a in xs for b in xs) / (2 * len(xs) ** 2 * mean)


def percentile(xs: list[float], q: float) -> float:
    s = sorted(xs)
    i = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[i]


# ─── regions ────────────────────────────────────────────────────────────────


def _children(conn: sqlite3.Connection) -> dict[str, list[str]]:
    kids: dict[str, list[str]] = defaultdict(list)
    for child, parent in conn.execute("SELECT b.child, b.parent FROM broader b JOIN concept c ON c.id = b.child"
                                      " WHERE c.scheme = 'space' AND c.status = 'active' ORDER BY 1"):
        kids[parent].append(child)
    return kids


def _groups(conn: sqlite3.Connection, level: int, kids: dict[str, list[str]]) -> list[str]:
    """Level 1: the UN M49 regions (and Antarctica, which has none). Level 2: their sub-regions."""
    top = kids.get("space/m49-001", [])
    if level == 1:
        return top
    out = []
    for g in top:
        out.extend(kids.get(g) or [g])            # an area without sub-regions stands for itself
    return out


def _descendants(start: str, kids: dict[str, list[str]]) -> set[str]:
    seen, stack = {start}, [start]
    while stack:
        for k in kids.get(stack.pop(), []):
            if k not in seen:
                seen.add(k)
                stack.append(k)
    return seen


def regional(conn: sqlite3.Connection, level: int, rng: random.Random) -> dict:
    kids = _children(conn)
    groups = _groups(conn, level, kids)
    members = {g: _descendants(g, kids) for g in groups}
    group_of: dict[str, str] = {}
    for g, ms in members.items():
        for m in ms:
            group_of[m] = g
    labels = dict(conn.execute("SELECT id, label FROM concept WHERE scheme = 'space'"))

    # which groups each ACAT concept's places fall in
    tagged: dict[str, set[str]] = defaultdict(set)
    region_only = set()
    for cid, place in conn.execute(
            "SELECT f.concept_id, f.facet_id FROM facet f JOIN concept c ON c.id = f.concept_id"
            " WHERE c.scheme = 'acat' AND c.status = 'active' AND f.facet_id LIKE 'space/%' ORDER BY 1, 2"):
        if place in group_of:
            tagged[cid].add(group_of[place])
        elif place != "space/m49-001":
            region_only.add(cid)                  # tagged above this level (e.g. 'Asia' at sub-region level)
    concepts = sorted(c for c, gs in tagged.items() if gs)
    region_only -= set(concepts)
    n = len(concepts)
    k = len(groups)
    index = {g: i for i, g in enumerate(groups)}
    weights = []
    for c in concepts:
        w = [0.0] * k
        for g in tagged[c]:
            w[index[g]] += 1 / len(tagged[c])
        weights.append(w)

    def shares(ws: list[list[float]]) -> list[float]:
        tot = [sum(col) for col in zip(*ws)] if ws else [0.0] * k
        return [t / len(ws) for t in tot] if ws else [0.0] * k

    s = shares(weights)

    # baselines: sums over the countries and areas inside each group
    base: dict[str, list[float | None]] = {}
    coverage: dict[str, dict] = {}
    for dim in ("population", "land_area"):
        values = dict(conn.execute("SELECT group_id, value FROM baseline WHERE dimension = ?", (dim,)))
        as_of = conn.execute("SELECT max(as_of) FROM baseline WHERE dimension = ?", (dim,)).fetchone()[0]
        sums = [sum(values.get(m, 0.0) for m in members[g]) for g in groups]
        total = sum(sums)
        base[dim] = [x / total for x in sums] if total else [None] * k
        leaves = [m for g in groups for m in members[g] if not kids.get(m)]
        coverage[dim] = {"as_of": as_of, "areas_with_value": sum(1 for m in leaves if m in values),
                         "areas": len(leaves),
                         "without_value": sorted(labels.get(m, m) for m in leaves if m not in values)}
    base["equal"] = [1 / k] * k

    # bootstrap (resampling concepts) and the null (sampling from the baseline itself)
    boot = [shares([weights[rng.randrange(n)] for _ in range(n)]) for _ in range(BOOTSTRAP)] if n else []
    out_groups = []
    for i, g in enumerate(groups):
        lo, hi = wilson(s[i], n)
        row = {"id": g, "label": labels.get(g, g), "share": s[i], "share_lo": lo, "share_hi": hi,
               "count": sum(w[i] for w in weights), "vs": {}}
        for dim in BASELINES:
            b = base[dim][i]
            if not b:
                row["vs"][dim] = {"baseline": b, "rr": None, "log2_rr": None, "rr_lo": None, "rr_hi": None}
                continue
            rr = s[i] / b
            row["vs"][dim] = {"baseline": b, "rr": rr, "log2_rr": math.log2(rr) if rr > 0 else None,
                              "rr_lo": lo / b, "rr_hi": hi / b}
        out_groups.append(row)
    dist = {}
    for dim in BASELINES:
        q = base[dim]
        if any(x is None for x in q):
            dist[dim] = None
            continue
        observed = jsd(s, q)
        boots = sorted(jsd(bs, q) for bs in boot)
        null = []
        for _ in range(BOOTSTRAP if n else 0):
            counts = [0] * k
            for j in rng.choices(range(k), weights=q, k=n):
                counts[j] += 1
            null.append(jsd([c / n for c in counts], q))
        ratios = [r["vs"][dim]["rr"] for r in out_groups if r["vs"][dim]["rr"] is not None]
        positive = [r for r in ratios if r > 0]
        dist[dim] = {"jsd_bits": observed, "jsd_distance": math.sqrt(observed),
                     "jsd_lo": percentile(boots, 0.025) if boots else None,
                     "jsd_hi": percentile(boots, 0.975) if boots else None,
                     "null_p95": percentile(null, 0.95) if null else None,
                     "exceeds_null": bool(null) and observed > percentile(null, 0.95),
                     "gini_rr": gini(ratios),
                     "max_min_rr": (max(positive) / min(positive)) if len(positive) > 1 else None,
                     "zero_share_groups": sum(1 for r in ratios if r == 0)}
    return {"level": level, "n": n, "k": k, "groups": out_groups, "entropy_norm": entropy_norm(s),
            "distribution": dist, "baseline_coverage": coverage, "tagged_above_level": len(region_only),
            "untagged": conn.execute("SELECT count(*) FROM concept c WHERE c.scheme = 'acat' AND c.status = 'active'"
                                     " AND NOT EXISTS (SELECT 1 FROM facet f WHERE f.concept_id = c.id"
                                     " AND f.facet_id LIKE 'space/%')").fetchone()[0]}


# ─── siblings ───────────────────────────────────────────────────────────────


def sibling_parity(conn: sqlite3.Connection) -> list[dict]:
    """For every ACAT parent with two or more children: how evenly its children are treated."""
    rows = conn.execute(
        "SELECT b.parent, c.id, c.label, coalesce(s.descendants, 0) + 1, length(coalesce(c.scope_note, '')),"
        " (SELECT count(*) FROM label l WHERE l.concept_id = c.id AND l.lang = 'en' AND l.kind = 'alt'),"
        " (SELECT count(*) FROM mapping m WHERE m.from_id = c.id AND m.status = 'accepted'),"
        " coalesce(s.label_langs, 0)"
        " FROM broader b JOIN concept c ON c.id = b.child LEFT JOIN concept_stat s ON s.concept_id = c.id"
        " JOIN concept p ON p.id = b.parent"
        " WHERE c.scheme = 'acat' AND p.scheme = 'acat' AND c.status = 'active' ORDER BY b.parent, c.id").fetchall()
    sets: dict[str, list] = defaultdict(list)
    for parent, *child in rows:
        sets[parent].append(child)
    labels = dict(conn.execute("SELECT id, label FROM concept WHERE scheme = 'acat'"))
    out = []
    for parent, kids in sets.items():
        if len(kids) < 2:
            continue
        entry = {"parent": parent, "label": labels.get(parent, parent), "children": len(kids), "quantities": {},
                 "flags": []}
        for qi, qname in enumerate(PARITY_QUANTITIES):
            xs = [k[2 + qi] for k in kids]
            mean = statistics.fmean(xs)
            cv = statistics.pstdev(xs) / mean if mean else None
            positive = [x for x in xs if x > 0]
            entry["quantities"][qname] = {"cv": cv, "max_min": max(positive) / min(positive) if positive and
                                          min(positive) > 0 and len(positive) == len(xs) else None,
                                          "min": min(xs), "max": max(xs), "median": statistics.median(xs)}
        med = statistics.median(k[2] for k in kids)
        for cid, label, subtree, *_ in kids:
            if subtree >= 3 * max(med, 1) and subtree >= 4:
                entry["flags"].append({"id": cid, "label": label, "subtree": subtree, "median": med,
                                       "why": "subtree at least 3x the sibling median"})
        out.append(entry)
    out.sort(key=lambda e: -(e["quantities"]["subtree"]["cv"] or 0))
    return out


# ─── attention, review ──────────────────────────────────────────────────────


def attention(conn: sqlite3.Connection) -> dict:
    """Wikipedia editions per ACAT concept, with and without the bot-generated Cebuano and Waray ones."""
    rows = conn.execute(
        "SELECT m.from_id, max(CAST(a.value AS INTEGER)), max(CAST(r.value AS INTEGER)) FROM mapping m"
        " JOIN attribute a ON a.concept_id = m.to_id AND a.key = 'sitelinks'"
        " LEFT JOIN attribute r ON r.concept_id = m.to_id AND r.key = 'sitelinks_all'"
        " WHERE m.status = 'accepted' AND m.relation IN ('exactMatch', 'closeMatch') AND m.to_id LIKE 'wd/%'"
        " GROUP BY m.from_id").fetchall()
    changed = [(c, a, r) for c, a, r in rows if r is not None and r != a]
    return {"concepts": len(rows), "excluded_editions": list(BOT_WIKIS),
            "median": statistics.median(a for _, a, _ in rows) if rows else None,
            "median_all": statistics.median((r if r is not None else a) for _, a, r in rows) if rows else None,
            "concepts_with_bot_editions": len(changed),
            "largest_differences": [{"id": c, "without": a, "with": r} for c, a, r in
                                    sorted(changed, key=lambda x: (x[1] - x[2], x[0]))[:10]]}


def evidence(conn: sqlite3.Connection) -> dict:
    """How many current source statements cite a source (not only 'imported from Wikimedia project')."""
    def count(where: str) -> dict:
        n, refd, sourced = conn.execute(
            "SELECT count(*), sum(e.references_n > 0), sum(e.sourced) FROM claim c JOIN v_claim_evidence e"
            f" ON e.claim_id = c.id WHERE c.statement_id IS NOT NULL AND c.superseded_at IS NULL {where}").fetchone()
        return {"statements": n, "with_reference": refd or 0, "sourced": sourced or 0,
                "sourced_share": (sourced or 0) / n if n else None}
    return {"all": count(""),
            "hierarchy": count("AND c.predicate IN ('wd/P31', 'wd/P279', 'wd/P361', 'wd/P1269')"),
            "definition": "sourced = some reference names more than P143/P4656 (imported from a Wikimedia "
                          "project) and P813 (retrieved)"}


def review_coverage(conn: sqlite3.Connection) -> dict:
    """Who decided each accepted crosswalk. An AI agent's decision is a proposal until a person reviews it."""
    by: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for reviewer, method, relation, n in conn.execute(
            "SELECT reviewer, method, relation, count(*) FROM mapping WHERE status = 'accepted' GROUP BY 1, 2, 3"):
        by[reviewer_kind(reviewer, method)][relation] += n
    human_reviews = conn.execute("SELECT count(*) FROM review WHERE reviewer_kind = 'human'").fetchone()[0] \
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'review'").fetchone() else 0
    return {"accepted_by_decider": {k: dict(v) for k, v in sorted(by.items())}, "human_reviews": human_reviews}


# ─── the run ────────────────────────────────────────────────────────────────


def run(conn: sqlite3.Connection, actor: str = "acat build") -> dict:
    rng = random.Random(SEED)
    result = {"generated_at": utcnow(), "ledger_head": ledger.head(conn),
              "params": {"seed": SEED, "bootstrap": BOOTSTRAP, "z": Z, "baselines": list(BASELINES),
                         "excluded_editions": list(BOT_WIKIS)},
              "regions": regional(conn, 1, rng), "subregions": regional(conn, 2, rng),
              "siblings": sibling_parity(conn), "attention": attention(conn), "evidence": evidence(conn),
              "review": review_coverage(conn)}
    cur = conn.execute("INSERT INTO audit_run(at, ledger_head, params, report) VALUES (?,?,?,?)",
                       (result["generated_at"], result["ledger_head"], json.dumps(result["params"], sort_keys=True),
                        json.dumps(result, sort_keys=True, ensure_ascii=False)))
    run_id = cur.lastrowid
    rows = []
    for dim in ("regions", "subregions"):
        r = result[dim]
        rows.append((run_id, dim, "", "entropy_norm", "", r["entropy_norm"], None, None, r["n"]))
        for g in r["groups"]:
            rows.append((run_id, dim, g["id"], "share", "", g["share"], g["share_lo"], g["share_hi"], r["n"]))
            for b, v in g["vs"].items():
                rows.append((run_id, dim, g["id"], "log2_rr", b, v["log2_rr"],
                             math.log2(v["rr_lo"]) if v["rr_lo"] else None,
                             math.log2(v["rr_hi"]) if v["rr_hi"] else None, r["n"]))
        for b, d in r["distribution"].items():
            if d:
                rows.append((run_id, dim, "", "jsd_bits", b, d["jsd_bits"], d["jsd_lo"], d["jsd_hi"], r["n"]))
                rows.append((run_id, dim, "", "jsd_null_p95", b, d["null_p95"], None, None, r["n"]))
                rows.append((run_id, dim, "", "gini_rr", b, d["gini_rr"], None, None, r["n"]))
    for s in result["siblings"]:
        for qname, q in s["quantities"].items():
            rows.append((run_id, f"siblings:{s['parent']}", "", f"cv_{qname}", "", q["cv"], q["min"], q["max"],
                         s["children"]))
        for f in s["flags"]:
            rows.append((run_id, f"siblings:{s['parent']}", f["id"], "subtree_flag", "", f["subtree"], None, None,
                         f["median"]))
    a = result["attention"]
    rows.append((run_id, "attention", "", "median_editions", "without_bot_editions", a["median"], None, None,
                 a["concepts"]))
    rows.append((run_id, "attention", "", "median_editions", "all_editions", a["median_all"], None, None,
                 a["concepts"]))
    for scope, e in result["evidence"].items():
        if isinstance(e, dict):
            rows.append((run_id, "evidence", scope, "sourced_share", "", e["sourced_share"], None, None,
                         e["statements"]))
    for kind, rels in result["review"]["accepted_by_decider"].items():
        for rel, n in rels.items():
            rows.append((run_id, "review", kind, f"accepted_{rel}", "", n, None, None, None))
    conn.executemany("INSERT INTO audit_metric(run_id, dimension, group_id, metric, baseline, value, lo, hi, n)"
                     " VALUES (?,?,?,?,?,?,?,?,?)", rows)
    ledger.record(conn, actor, "audit", target=f"audit_run/{run_id}",
                  detail={"metrics": len(rows), "regions_n": result["regions"]["n"],
                          "exceeds_null": {b: (d or {}).get("exceeds_null") for b, d in
                                           result["regions"]["distribution"].items()}},
                  receipt=f"ledger-head:{result['ledger_head'][:32]}",
                  undo="audit runs are measurements; later runs are added beside them")
    result["run_id"] = run_id
    return result


def latest(conn: sqlite3.Connection) -> dict | None:
    """The newest stored run as `run` returned it. The audit_metric rows are the queryable record;
    audit_run.report is their presentation copy for the API."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'audit_run'").fetchone():
        return None
    r = conn.execute("SELECT id, report FROM audit_run ORDER BY id DESC LIMIT 1").fetchone()
    if r is None or not r[1]:
        return None
    return {**json.loads(r[1]), "run_id": r[0]}
