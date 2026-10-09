"""TDD tests for the agent-memory-core Memory module (stdlib unittest only)."""
import os
import sys
import tempfile
import unittest

# Make the product root importable regardless of cwd.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory import Memory  # noqa: E402


class MemoryTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        # Remove so Memory creates a fresh DB; keep the unique path.
        os.remove(self.db_path)
        self.mem = Memory(self.db_path)

    def tearDown(self):
        try:
            self.mem.close()
        except Exception:
            pass
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_add_then_recall_hits_relevant_fact(self):
        self.mem.add_fact("Alice deployed the payment service on Friday", ts=100.0)
        results = self.mem.recall("payment service deploy")
        self.assertTrue(results, "recall should return at least one matching fact")
        self.assertIn("payment service", results[0]["text"])
        self.assertGreaterEqual(results[0]["score"], 1)

    def test_unrelated_query_returns_nothing(self):
        self.mem.add_fact("Alice deployed the payment service", ts=100.0)
        results = self.mem.recall("quantum banana helicopter")
        self.assertEqual(results, [])

    def test_entity_extraction_captures_caps_quotes_backticks(self):
        fid = self.mem.add_fact(
            'Bob shipped "Project Phoenix" using the `migrate` command', ts=50.0
        )
        ents = set(self.mem.entities_of(fid))
        self.assertIn("Bob", ents)
        self.assertIn("Project Phoenix", ents)
        self.assertIn("migrate", ents)

    def test_entity_filter_only_returns_facts_with_that_entity(self):
        self.mem.add_fact("Alice reviewed the report", ts=10.0)
        self.mem.add_fact("Bob reviewed the report", ts=20.0)
        results = self.mem.recall("reviewed report", entity="Bob")
        self.assertEqual(len(results), 1)
        self.assertIn("Bob", results[0]["text"])
        self.assertIn("Bob", results[0]["entities"])

    def test_entity_filter_case_insensitive(self):
        self.mem.add_fact("Carol merged the branch", ts=10.0)
        results = self.mem.recall("merged branch", entity="carol")
        self.assertEqual(len(results), 1)
        self.assertIn("Carol", results[0]["text"])

    def test_tie_break_newer_ts_ranks_first(self):
        # Same query-overlap (both contain "release"), so scores tie -> newer first.
        self.mem.add_fact("old release notes", ts=100.0)
        self.mem.add_fact("new release notes", ts=200.0)
        results = self.mem.recall("release notes")
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["score"], results[1]["score"])
        self.assertEqual(results[0]["ts"], 200.0)
        self.assertIn("new", results[0]["text"])

    def test_higher_overlap_outranks_recency(self):
        self.mem.add_fact("alpha beta gamma", ts=999.0)  # 1 overlap, newest
        self.mem.add_fact("alpha beta delta epsilon", ts=1.0)  # 2 overlaps, oldest
        results = self.mem.recall("alpha beta delta")
        self.assertEqual(results[0]["text"], "alpha beta delta epsilon")
        self.assertGreater(results[0]["score"], results[1]["score"])

    def test_limit_caps_returned_facts(self):
        for i in range(5):
            self.mem.add_fact(f"task number {i} done", ts=float(i))
        results = self.mem.recall("task done", limit=3)
        self.assertEqual(len(results), 3)

    def test_persistence_across_reopen(self):
        self.mem.add_fact("Dana finished the audit", ts=42.0)
        self.mem.close()
        reopened = Memory(self.db_path)
        try:
            results = reopened.recall("audit finished")
            self.assertTrue(results)
            self.assertIn("audit", results[0]["text"])
        finally:
            reopened.close()

    def test_default_ts_is_set_when_omitted(self):
        fid = self.mem.add_fact("Eve pushed a hotfix")
        results = self.mem.recall("hotfix")
        self.assertTrue(results)
        self.assertEqual(results[0]["id"], fid)
        self.assertGreater(results[0]["ts"], 0.0)

    def test_recall_result_shape(self):
        self.mem.add_fact("Frank tagged release v2", ts=5.0)
        r = self.mem.recall("release v2")[0]
        self.assertEqual(
            set(r.keys()), {"id", "text", "ts", "score", "entities"}
        )
        self.assertIsInstance(r["entities"], list)

    # --- b11 regressions ---
    def test_non_ascii_facts_are_recallable(self):
        cn = self.mem.add_fact("用户偏好 简体中文 输出", ts=1.0)
        fr = self.mem.add_fact("the café is closed", ts=2.0)
        self.mem.add_fact("unrelated english fact", ts=3.0)
        self.assertEqual([r["id"] for r in self.mem.recall("简体中文")], [cn])
        self.assertEqual([r["id"] for r in self.mem.recall("café")], [fr])
        self.assertEqual(self.mem.recall("日本語"), [])

    def test_ascii_tokenization_unchanged(self):
        from memory import _tokenize
        self.assertEqual(_tokenize("Deploy_v2 to prod-3!"),
                         ["deploy_v2", "to", "prod", "3"])

    def test_non_finite_ts_rejected_before_write(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(ValueError):
                self.mem.add_fact("Alice likes tea", ts=bad)
        self.assertEqual(self.mem.recall("alice"), [])

    def test_bool_limit_rejected(self):
        with self.assertRaises(ValueError):
            self.mem.recall("x", limit=True)


if __name__ == "__main__":
    unittest.main()
