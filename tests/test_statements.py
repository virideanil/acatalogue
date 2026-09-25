"""Statement-level Wikidata claims from entity JSON: identity, snak types, times, qualifiers, references,
pointers back into the stored bytes, and supersession of the WDQS summaries."""
import json
import tempfile
import unittest
from pathlib import Path

from acatalogue import db as dbm, ledger
from acatalogue.corpusfile import CorpusFile
from acatalogue.sources import wikidata
from acatalogue.sources.wikidata import JULIAN, _jdn, day_bounds, snak_parts, validity, wd_time, wd_time_parts

GREGORIAN = "http://www.wikidata.org/entity/Q1985727"


def item(qid: str) -> dict:
    return {"type": "wikibase-entityid", "value": {"entity-type": "item", "numeric-id": int(qid[1:]), "id": qid}}


def time(t: str, precision: int, calendar: str = GREGORIAN) -> dict:
    return {"type": "time", "value": {"time": t, "precision": precision, "timezone": 0, "before": 0, "after": 0,
                                      "calendarmodel": calendar}}


def snak(pid: str, datavalue: dict | None, datatype: str, kind: str = "value") -> dict:
    s = {"snaktype": kind, "property": pid, "datatype": datatype}
    if datavalue is not None:
        s["datavalue"] = datavalue
    return s


ENTITIES = {"entities": {
    "Q1": {"id": "Q1", "lastrevid": 123, "modified": "2026-01-15T00:00:00Z", "claims": {
        "P279": [
            {"id": "Q1$AAA", "rank": "normal", "type": "statement",
             "mainsnak": snak("P279", item("Q2"), "wikibase-item"),
             "qualifiers": {"P580": [snak("P580", time("-0500-00-00T00:00:00Z", 9, JULIAN), "time")],
                            "P582": [snak("P582", time("+1582-10-05T00:00:00Z", 11, JULIAN), "time")]},
             "qualifiers-order": ["P580", "P582"],
             "references": [{"hash": "abc123", "snaks-order": ["P248", "P854"], "snaks": {
                 "P248": [snak("P248", item("Q5"), "wikibase-item")],
                 "P854": [snak("P854", {"type": "string", "value": "https://example.org/x"}, "url")]}}]},
            # the same value again, as a different statement (another period): must not collide
            {"id": "Q1$BBB", "rank": "deprecated", "type": "statement",
             "mainsnak": snak("P279", item("Q2"), "wikibase-item"),
             "qualifiers": {"P585": [snak("P585", time("+1905-06-00T00:00:00Z", 10), "time")]},
             "qualifiers-order": ["P585"]}],
        "P1082": [{"id": "Q1$CCC", "rank": "preferred", "type": "statement",
                   "mainsnak": snak("P1082", {"type": "quantity", "value": {"amount": "+8", "unit": "1"}},
                                    "quantity")}],
        "P244": [{"id": "Q1$DDD", "rank": "normal", "type": "statement",
                  "mainsnak": snak("P244", {"type": "string", "value": "sh85101653"}, "external-id")}],
        "P2348": [{"id": "Q1$EEE", "rank": "normal", "type": "statement",
                   "mainsnak": snak("P2348", None, "wikibase-item", "somevalue")}],
        "P1889": [{"id": "Q1$FFF", "rank": "normal", "type": "statement",
                   "mainsnak": snak("P1889", None, "wikibase-item", "novalue")}]}},
    "Q999": {"id": "Q999", "missing": ""}}}

LABELS = {"entities": {
    "Q2": {"id": "Q2", "labels": {"en": {"language": "en", "value": "Wissenschaft"}}},
    "Q5": {"id": "Q5", "labels": {"mul": {"language": "mul", "value": "Encyclopædia"}}},
    "P279": {"id": "P279", "labels": {"en": {"language": "en", "value": "subclass of"}}},
    "Q7": {"id": "Q7", "missing": ""}}}


SPARQL_LABELS = {"results": {"bindings": [
    {"e": {"type": "uri", "value": "http://www.wikidata.org/entity/P2348"},
     "l": {"type": "literal", "xml:lang": "mul", "value": "time period"}},
    {"e": {"type": "uri", "value": "http://www.wikidata.org/entity/P2348"},
     "l": {"type": "literal", "xml:lang": "en", "value": "time period (en)"}}]}}


def summary_corpus(root: Path, name: str, triples, retrieved_at: str) -> CorpusFile:
    c = CorpusFile(root / name / "corpus.sqlite", create=True, name=name, title="test summaries")
    bindings = [{"item": {"value": f"http://www.wikidata.org/entity/{s}"}, "pid": {"value": p},
                 "value": {"value": f"http://www.wikidata.org/entity/{o}"}, "valueLabel": {"value": o},
                 "rank": {"value": "http://wikiba.se/ontology#NormalRank"}} for s, p, o in triples]
    c.add("sparql/claims-001.json", json.dumps({"results": {"bindings": bindings}}).encode(),
          url="https://query.wikidata.org/sparql", retrieved_at=retrieved_at)
    c.seal()
    return c


def statements_corpus(root: Path, name: str, retrieved_at: str) -> CorpusFile:
    c = CorpusFile(root / name / "corpus.sqlite", create=True, name=name, title="test statements")
    c.add("entities/batch-001.json", json.dumps(ENTITIES).encode(), url="https://www.wikidata.org/w/api.php",
          retrieved_at=retrieved_at)
    c.add("labels/batch-0001.json", json.dumps(LABELS).encode(), url="https://www.wikidata.org/w/api.php",
          retrieved_at=retrieved_at)
    c.add("labels/sparql-001.json", json.dumps(SPARQL_LABELS).encode(), url="https://query.wikidata.org/sparql",
          retrieved_at=retrieved_at)
    c.seal()
    return c


class ValueTests(unittest.TestCase):
    def test_times(self):
        self.assertEqual(wd_time(time("-0001-00-00T00:00:00Z", 9)["value"]), ("0000", 9))      # 1 BCE
        self.assertEqual(wd_time(time("-0500-00-00T00:00:00Z", 9, JULIAN)["value"]), ("-0499", 9))
        self.assertEqual(wd_time(time("+1582-10-05T00:00:00Z", 11, JULIAN)["value"]), ("1582-10-15", 11))
        self.assertEqual(wd_time(time("+2000-01-01T00:00:00Z", 11)["value"]), ("2000-01-01", 11))
        self.assertEqual(wd_time(time("+1905-06-00T00:00:00Z", 10)["value"]), ("1905-06", 10))
        self.assertEqual(wd_time(time("+1500-03-00T00:00:00Z", 10, JULIAN)["value"]), ("1500", 9))
        self.assertEqual(wd_time(time("+1900-00-00T00:00:00Z", 7)["value"]), ("1900", 7))     # century: code kept
        self.assertEqual(wd_time(time("+2001-02-03T04:05:06Z", 14)["value"]), ("2001-02-03", 11))
        self.assertIsNone(wd_time({"time": "garbage"}))

    def test_julian_conversion_agrees_with_known_dates(self):
        from acatalogue.sources.wikidata import _julian_to_gregorian
        self.assertEqual(_julian_to_gregorian(1582, 10, 5), (1582, 10, 15))     # the Gregorian reform
        self.assertEqual(_julian_to_gregorian(1917, 10, 25), (1917, 11, 7))     # October Revolution
        self.assertEqual(_julian_to_gregorian(-43, 3, 15), (-43, 3, 13))        # Ides of March, 44 BCE

    def test_snak_parts(self):
        self.assertEqual(snak_parts(snak("P1", item("Q2"), "wikibase-item")), ("value", "wd/Q2", None, "wikibase-item"))
        self.assertEqual(snak_parts(snak("P1", None, "string", "novalue")), ("novalue", None, None, "string"))
        kind, obj, value, dt = snak_parts(snak("P1", {"type": "quantity", "value": {"unit": "1", "amount": "+8"}},
                                               "quantity"))
        self.assertEqual(value, '{"amount":"+8","unit":"1"}')                   # canonical JSON

    def test_validity_needs_one_known_value(self):
        start = snak("P580", time("+1900-00-00T00:00:00Z", 9), "time")
        self.assertEqual(validity({"P580": [start]}), ("1900", None, 9, _jdn(1900, 1, 1), None))
        self.assertEqual(validity({"P580": [start, start]}), (None, None, None, None, None))
        self.assertEqual(validity({"P580": [snak("P580", None, "time", "somevalue")]}),
                         (None, None, None, None, None))

    def test_day_bounds_sort_across_bce_and_follow_wikidata_centuries(self):
        def bounds(t, p, cal=GREGORIAN):
            return day_bounds(wd_time_parts(time(t, p, cal)["value"]))
        self.assertEqual(_jdn(2000, 1, 1), 2451545)                              # the J2000 epoch day
        self.assertEqual(_jdn(-4713, 11, 24), 0)                                 # JDN 0, proleptic Gregorian
        self.assertEqual(bounds("+1900-00-00T00:00:00Z", 7), (_jdn(1801, 1, 1), _jdn(1900, 12, 31)))
        self.assertEqual(bounds("+2000-00-00T00:00:00Z", 6), (_jdn(1001, 1, 1), _jdn(2000, 12, 31)))
        self.assertEqual(bounds("-0500-00-00T00:00:00Z", 7), (_jdn(-499, 1, 1), _jdn(-400, 12, 31)))  # 5th c. BCE
        self.assertEqual(bounds("-0001-00-00T00:00:00Z", 7), (_jdn(-99, 1, 1), _jdn(0, 12, 31)))      # 1st c. BCE
        self.assertEqual(bounds("+1960-00-00T00:00:00Z", 8), (_jdn(1960, 1, 1), _jdn(1969, 12, 31)))
        self.assertEqual(bounds("+2024-02-00T00:00:00Z", 10), (_jdn(2024, 2, 1), _jdn(2024, 2, 29)))  # leap
        self.assertEqual(bounds("-13798000000-00-00T00:00:00Z", 3), (None, None))  # beyond calendar arithmetic
        # text sorts BCE backwards; day numbers do not
        a, b = bounds("-0500-00-00T00:00:00Z", 9), bounds("-0100-00-00T00:00:00Z", 9)
        self.assertGreater(wd_time(time("-0500-00-00T00:00:00Z", 9)["value"])[0],
                           wd_time(time("-0100-00-00T00:00:00Z", 9)["value"])[0])
        self.assertLess(a[0], b[0])


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.conn = dbm.connect(self.tmp / "t.sqlite", create=True)
        dbm.init_schema(self.conn)
        self.summaries = summary_corpus(self.tmp, "wikidata-entities-20260101",
                                        [("Q1", "P279", "Q2"), ("Q3", "P279", "Q4")], "2026-01-01T00:00:00Z")
        self.statements = statements_corpus(self.tmp, "wikidata-statements-20260201", "2026-02-01T00:00:00Z")
        wikidata.import_claims(self.conn, self.summaries)
        self.stats = wikidata.import_statements(self.conn, self.statements)

    def claim(self, statement_id: str) -> dict:
        self.conn.row_factory = None
        cur = self.conn.execute("SELECT * FROM claim WHERE statement_id = ?", (statement_id,))
        names = [d[0] for d in cur.description]
        return dict(zip(names, cur.fetchone()))

    def test_every_statement_is_its_own_claim(self):
        self.assertEqual(self.stats["entities"], 1)
        self.assertEqual(self.stats["missing"], 1)
        self.assertEqual(self.stats["new"], 6)
        a, b = self.claim("Q1$AAA"), self.claim("Q1$BBB")
        self.assertEqual((a["subject"], a["predicate"], a["object"]), (b["subject"], b["predicate"], b["object"]))
        self.assertEqual((a["rank"], b["rank"]), ("normal", "deprecated"))
        self.assertEqual(a["source_revision"], 123)
        self.assertEqual(a["recorded_at"], "2026-02-01T00:00:00Z")          # record time comes from the bytes

    def test_snak_types_and_values(self):
        self.assertEqual(self.claim("Q1$EEE")["snak_type"], "somevalue")
        self.assertEqual(self.claim("Q1$FFF")["snak_type"], "novalue")
        self.assertIsNone(self.claim("Q1$FFF")["object"])
        self.assertEqual(self.claim("Q1$DDD")["value"], "sh85101653")
        self.assertEqual(self.claim("Q1$DDD")["datatype"], "external-id")
        self.assertEqual(json.loads(self.claim("Q1$CCC")["value"]), {"amount": "+8", "unit": "1"})

    def test_world_time(self):
        a, b = self.claim("Q1$AAA"), self.claim("Q1$BBB")
        self.assertEqual((a["valid_from"], a["valid_to"], a["time_precision"]), ("-0499", "1582-10-15", 9))
        self.assertEqual((a["valid_from_day"], a["valid_to_day"]), (_jdn(-499, 1, 1), _jdn(1582, 10, 15)))
        self.assertEqual((b["valid_from"], b["valid_to"], b["time_precision"]), ("1905-06", "1905-06", 10))
        self.assertEqual((b["valid_from_day"], b["valid_to_day"]), (_jdn(1905, 6, 1), _jdn(1905, 6, 30)))

    def test_qualifiers_and_references_are_rows(self):
        cid = self.claim("Q1$AAA")["id"]
        q = self.conn.execute("SELECT ord, property, datatype FROM claim_qualifier WHERE claim_id = ? ORDER BY ord",
                              (cid,)).fetchall()
        self.assertEqual([tuple(r) for r in q], [(0, "wd/P580", "time"), (1, "wd/P582", "time")])
        r = self.conn.execute("SELECT ref_hash, ord, property, object, value FROM claim_reference WHERE claim_id = ?"
                              " ORDER BY ord", (cid,)).fetchall()
        self.assertEqual([tuple(x) for x in r], [("abc123", 0, "wd/P248", "wd/Q5", None),
                                                  ("abc123", 1, "wd/P854", None, "https://example.org/x")])

    def test_pointer_resolves_in_the_stored_bytes(self):
        for sid in ("Q1$AAA", "Q1$BBB", "Q1$CCC"):
            c = self.claim(sid)
            src = self.conn.execute("SELECT name FROM source WHERE sha512 = ?", (c["source_sha512"],)).fetchone()[0]
            node = json.loads(self.statements.get(src.split(":", 1)[1]))
            for part in c["source_pointer"].lstrip("/").split("/"):
                node = node[int(part)] if isinstance(node, list) else node[part.replace("~1", "/").replace("~0", "~")]
            self.assertEqual(node["id"], sid)

    def test_labels_for_named_entities(self):
        labels = dict(self.conn.execute("SELECT id, label FROM concept WHERE id IN ('wd/Q2', 'wd/Q5', 'wd/Q7')"))
        self.assertEqual(labels["wd/Q5"], "Encyclopædia")                      # 'mul' when there is no English
        self.assertNotIn("wd/Q7", labels)                                      # missing entity: no row
        p = self.conn.execute("SELECT label FROM concept WHERE id = 'wd/P2348'").fetchone()[0]
        self.assertEqual(p, "time period (en)")                                # query-service rows: en first

    def test_summaries_of_covered_entities_are_superseded(self):
        rows = dict(self.conn.execute("SELECT subject, superseded_at FROM claim WHERE statement_id IS NULL"))
        self.assertEqual(rows["wd/Q1"], "2026-02-01T00:00:00Z")
        self.assertIsNone(rows["wd/Q3"], "not in the statements corpus: stays current")
        self.assertEqual(self.conn.execute("SELECT count(*) FROM claim").fetchone()[0], 8, "nothing deleted")
        ok, _, msg = ledger.verify(self.conn)
        self.assertTrue(ok, msg)

    def test_reimport_is_idempotent(self):
        again = wikidata.import_statements(self.conn, self.statements)
        self.assertEqual(again["new"], 0)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM claim_qualifier").fetchone()[0], 3)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM claim_reference").fetchone()[0], 2)

    def test_a_later_summary_is_not_superseded_by_older_statements(self):
        later = summary_corpus(self.tmp, "wikidata-entities-20260301", [("Q1", "P361", "Q9")], "2026-03-01T00:00:00Z")
        wikidata.import_claims(self.conn, later)
        wikidata.import_statements(self.conn, self.statements)
        row = self.conn.execute("SELECT superseded_at FROM claim WHERE predicate = 'wd/P361'").fetchone()
        self.assertIsNone(row[0])


if __name__ == "__main__":
    unittest.main()
