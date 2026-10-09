"""Tests for verify.read_back — confirm a file was actually written."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from verify import read_back  # noqa: E402


class ReadBackHit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "config.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write('{"model": "opus", "enabled": true}')

    def test_single_substring_present(self):
        result = read_back(self.path, must_contain="opus")
        self.assertTrue(result["passed"])
        self.assertEqual(result["missing"], [])

    def test_multiple_substrings_all_present(self):
        result = read_back(self.path, must_contain=["opus", "enabled"])
        self.assertTrue(result["passed"])
        self.assertEqual(result["missing"], [])


class ReadBackMiss(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "config.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write('{"model": "opus"}')

    def test_substring_absent_fails_and_lists_missing(self):
        result = read_back(self.path, must_contain="sonnet")
        self.assertFalse(result["passed"])
        self.assertIn("sonnet", result["missing"])

    def test_partial_match_lists_only_missing(self):
        result = read_back(self.path, must_contain=["opus", "sonnet", "haiku"])
        self.assertFalse(result["passed"])
        self.assertEqual(set(result["missing"]), {"sonnet", "haiku"})


class ReadBackMissingFile(unittest.TestCase):
    def test_nonexistent_file_fails(self):
        result = read_back("/no/such/path/xyz.txt", must_contain="anything")
        self.assertFalse(result["passed"])
        self.assertFalse(result["exists"])
        # everything is "missing" because the file isn't there
        self.assertIn("anything", result["missing"])


class ReadBackNeedleValidation(unittest.TestCase):
    def test_empty_needle_rejected(self):
        # b11 regression: "" is in every file, so it used to "confirm" anything.
        for bad in ("", ["ok", ""], [5]):
            with self.assertRaises(ValueError):
                read_back("/no/such/path/xyz.txt", must_contain=bad)


if __name__ == "__main__":
    unittest.main()
