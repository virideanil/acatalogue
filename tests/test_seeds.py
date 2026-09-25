"""The compendium seeds: structural validity, the validator itself, and neutrality lints."""
import re
import tempfile
import unittest
from pathlib import Path

from acatalogue import compendium
from acatalogue.compendium import CONCEPT_COLUMNS, SeedError, parse_when, read_scheme, validate_scheme

HEADER = "\t".join(CONCEPT_COLUMNS) + "\n"


class ValidatorTests(unittest.TestCase):
    def rows(self, text):
        p = Path(tempfile.mkdtemp()) / "x.tsv"
        p.write_text(HEADER + text, encoding="utf-8")
        return read_scheme("t", [p])

    def test_valid_tree(self):
        rows = self.rows("a\t\tA\t\t\t\t\t\t\nb\ta\tB\t\t\t\t\t\t\n")
        self.assertEqual(validate_scheme("t", rows), [])

    def test_duplicate_unknown_and_cycle(self):
        rows = self.rows("a\t\tA\t\t\t\t\t\t\nb\tc\tB\t\t\t\t\t\t\nc\tb\tC\t\t\t\t\t\t\nb\ta\tB2\t\t\t\t\t\t\n"
                         "d\tzz\tD\t\t\t\t\t\t\n")
        problems = " | ".join(validate_scheme("t", rows))
        self.assertIn("duplicate code 'b'", problems)
        self.assertIn("unknown broader 'zz'", problems)
        self.assertIn("cycle", problems)

    def test_stray_tab_is_refused(self):
        with self.assertRaises(SeedError):
            self.rows("a\t\tA\t\t\t\t\t\t\textra\n")

    def test_when(self):
        self.assertEqual(parse_when("-2999/-2000", "x"), (-2999, -2000))
        self.assertEqual(parse_when("2001/..", "x"), (2001, None))
        self.assertEqual(parse_when("../-3000", "x"), (None, -3000))
        with self.assertRaises(SeedError):
            parse_when("1900/1800", "x")


class RealSeedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schemes, cls.problems = compendium.read_all()
        cls.acat = cls.schemes["acat"]

    def test_seeds_are_valid(self):
        self.assertEqual(self.problems, [])

    def test_thirteen_domains_in_a_circle(self):
        roots = sorted(r.code for r in self.acat if not r.broader)
        self.assertEqual(len(roots), 13, roots)
        for root in roots:
            self.assertTrue(any(root in r.broader for r in self.acat), f"domain {root} has no children")

    def test_every_concept_has_a_scope_note(self):
        missing = [r.code for r in self.acat if not r.scope_note]
        self.assertEqual(missing, [])

    def test_no_residual_other_category(self):
        """Neutrality lint: no 'Other X' bucket that turns everything outside one tradition into a remainder."""
        bad = [r.code for r in self.acat if re.search(r"\bothers?\b", r.label, re.I)]
        self.assertEqual(bad, [])

    def test_regional_history_is_tagged_with_m49(self):
        by_code = {r.code: r for r in self.acat}

        def under(r, top):
            return any(b == top or under(by_code[b], top) for b in r.broader)

        hist = [r for r in self.acat if under(r, "history-by-region") and r.code != "history-of-the-oceans"]
        self.assertGreaterEqual(len(hist), 25)
        untagged = [r.code for r in hist if not any(f.startswith("space/m49-") for f in r.facets)]
        self.assertEqual(untagged, [])

    def test_traditions_are_siblings(self):
        children = [r for r in self.acat if r.broader == ["religious-traditions"]]
        self.assertGreaterEqual(len(children), 20)
        grandkids = [r.code for r in self.acat if any(b in {c.code for c in children} for b in r.broader)]
        self.assertEqual(grandkids, [], "no tradition is subdivided while others are not")

    def test_periods_are_dated(self):
        periods = [r for r in self.acat if r.code.startswith("period-")]
        self.assertTrue(periods)
        self.assertTrue(all(r.time_from is not None or r.time_to is not None for r in periods))


if __name__ == "__main__":
    unittest.main()
