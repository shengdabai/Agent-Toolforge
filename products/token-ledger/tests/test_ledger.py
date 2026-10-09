"""TDD tests for the token-ledger pure-logic core (stdlib unittest only)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from ledger import PRICING, cost, attribute, detect_spikes  # noqa: E402


class TestCost(unittest.TestCase):
    def test_exact_cost_hand_aligned(self):
        # pricing: input $0.01/1k, output $0.03/1k
        pricing = {"m": {"input": 0.01, "output": 0.03}}
        ev = {"model": "m", "input_tokens": 1000, "output_tokens": 2000}
        # 1.0*0.01 + 2.0*0.03 = 0.01 + 0.06 = 0.07
        self.assertAlmostEqual(cost(ev, pricing), 0.07, places=10)

    def test_partial_thousand(self):
        pricing = {"m": {"input": 0.50, "output": 1.50}}
        ev = {"model": "m", "input_tokens": 500, "output_tokens": 250}
        # 0.5*0.50 + 0.25*1.50 = 0.25 + 0.375 = 0.625
        self.assertAlmostEqual(cost(ev, pricing), 0.625, places=10)

    def test_unknown_model_is_not_reported_as_free(self):
        ev = {"model": "does-not-exist", "input_tokens": 9999, "output_tokens": 9999}
        with self.assertRaisesRegex(ValueError, "Pricing unavailable"):
            cost(ev, PRICING)

    def test_missing_token_fields_default_zero(self):
        pricing = {"m": {"input": 1.0, "output": 1.0}}
        self.assertEqual(cost({"model": "m"}, pricing), 0.0)
        # only input present
        self.assertAlmostEqual(
            cost({"model": "m", "input_tokens": 1000}, pricing), 1.0, places=10
        )

    def test_none_token_fields_treated_as_zero(self):
        pricing = {"m": {"input": 1.0, "output": 1.0}}
        ev = {"model": "m", "input_tokens": None, "output_tokens": None}
        self.assertEqual(cost(ev, pricing), 0.0)

    def test_incomplete_and_invalid_pricing_rejected(self):
        for rates in [{"input":1}, {"output":1}, {"input":float('nan'),"output":1}, {"input":-1,"output":1}]:
            with self.assertRaises(ValueError):cost({"model":"m","input_tokens":1000},{"m":rates})

    def test_default_pricing_table_present(self):
        # at least a few placeholder models exist and are well-formed
        self.assertGreaterEqual(len(PRICING), 3)
        for name, rates in PRICING.items():
            self.assertIn("input", rates)
            self.assertIn("output", rates)


class TestAttribute(unittest.TestCase):
    def setUp(self):
        self.pricing = {
            "cheap": {"input": 0.001, "output": 0.002},
            "pricey": {"input": 0.01, "output": 0.03},
        }
        self.events = [
            {"model": "cheap", "input_tokens": 1000, "output_tokens": 1000,
             "session": "s1", "tag": "chat"},
            {"model": "pricey", "input_tokens": 1000, "output_tokens": 1000,
             "session": "s1", "tag": "code"},
            {"model": "cheap", "input_tokens": 2000, "output_tokens": 0,
             "session": "s2", "tag": "chat"},
        ]

    def test_group_by_session_sum_and_sort(self):
        res = attribute(self.events, by="session", pricing=self.pricing)
        # s1 cost = cheap(0.001+0.002=0.003) + pricey(0.01+0.03=0.04) = 0.043
        # s2 cost = cheap input 2000 -> 2*0.001 = 0.002
        self.assertEqual([r["key"] for r in res], ["s1", "s2"])
        self.assertAlmostEqual(res[0]["cost"], 0.043, places=10)
        self.assertAlmostEqual(res[1]["cost"], 0.002, places=10)
        # token sums
        self.assertEqual(res[0]["input_tokens"], 2000)
        self.assertEqual(res[0]["output_tokens"], 2000)
        self.assertEqual(res[0]["events"], 2)
        self.assertEqual(res[1]["events"], 1)

    def test_descending_cost_order(self):
        res = attribute(self.events, by="model", pricing=self.pricing)
        costs = [r["cost"] for r in res]
        self.assertEqual(costs, sorted(costs, reverse=True))
        # pricey should be first (more expensive)
        self.assertEqual(res[0]["key"], "pricey")

    def test_group_by_tag(self):
        res = attribute(self.events, by="tag", pricing=self.pricing)
        keys = {r["key"] for r in res}
        self.assertEqual(keys, {"chat", "code"})

    def test_missing_group_key_bucketed_unknown(self):
        events = [{"model": "cheap", "input_tokens": 1000, "output_tokens": 0}]
        res = attribute(events, by="session", pricing=self.pricing)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["key"], "unknown")

    def test_empty_input_returns_empty(self):
        self.assertEqual(attribute([], by="session", pricing=self.pricing), [])

    def test_tie_break_by_key_ascending(self):
        events = [
            {"model": "cheap", "input_tokens": 1000, "output_tokens": 0, "session": "b"},
            {"model": "cheap", "input_tokens": 1000, "output_tokens": 0, "session": "a"},
        ]
        res = attribute(events, by="session", pricing=self.pricing)
        # equal cost -> key ascending
        self.assertEqual([r["key"] for r in res], ["a", "b"])


class TestDetectSpikes(unittest.TestCase):
    def test_flags_obvious_outlier(self):
        # Many baseline points keep mean+stddev low so a single large point
        # clearly clears mean + z*stddev (avoids single-outlier masking).
        series = [{"key": f"s{i}", "cost": 1.0} for i in range(12)]
        series.append({"key": "spike", "cost": 20.0})
        spikes = detect_spikes(series, z=2.0)
        keys = [s["key"] for s in spikes]
        self.assertIn("spike", keys)
        self.assertNotIn("s1", keys)
        for s in spikes:
            self.assertTrue(s["spike"])
            self.assertIn("z_score", s)

    def test_no_spike_when_uniform(self):
        series = [{"key": f"s{i}", "cost": 5.0} for i in range(6)]
        self.assertEqual(detect_spikes(series, z=2.0), [])

    def test_empty_returns_empty(self):
        self.assertEqual(detect_spikes([], z=2.0), [])

    def test_single_point_returns_empty(self):
        self.assertEqual(detect_spikes([{"key": "s1", "cost": 42.0}], z=2.0), [])

    def test_threshold_strict_greater(self):
        # mean=2, stddev with values [1,1,1,3] population:
        # mean=1.5, var=((.5^2)*3 + 1.5^2)/4 = (0.75+2.25)/4=0.75, sd~0.866
        # threshold at z=1 -> 1.5+0.866=2.366; the 3.0 point exceeds it
        series = [
            {"key": "a", "cost": 1.0},
            {"key": "b", "cost": 1.0},
            {"key": "c", "cost": 1.0},
            {"key": "d", "cost": 3.0},
        ]
        spikes = detect_spikes(series, z=1.0)
        self.assertEqual([s["key"] for s in spikes], ["d"])


if __name__ == "__main__":
    unittest.main()
