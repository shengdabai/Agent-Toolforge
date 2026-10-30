import json
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from slim import slim, token_est, TRUNC_MARKER  # noqa: E402


class TestTokenEst(unittest.TestCase):
    def test_token_est_is_ceil_len_over_4(self):
        for obj in ({"a": 1}, [1, 2, 3], "hello world", 42):
            s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
            self.assertEqual(token_est(obj), math.ceil(len(s) / 4))

    def test_token_est_empty(self):
        self.assertEqual(token_est({}), math.ceil(len("{}") / 4))


class TestWhitelist(unittest.TestCase):
    def test_malformed_field_entries_raise_instead_of_dropping_data(self):
        payload = {"name": "visible", "extra": 1}
        for fields in ([None], [1], [False], [""], ["name", None], ("name", "")):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                slim(payload, {"fields": fields})
        self.assertEqual(payload, {"name": "visible", "extra": 1})

    def test_drop_nulls_requires_a_boolean(self):
        for value in ("false", "true", 0, 1, [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                slim({"keep": None}, {"drop_nulls": value})

    def test_drop_nulls_null_means_unset(self):
        self.assertEqual(slim({"keep": None}, {"drop_nulls": None})[0], {"keep": None})

    def test_valid_boolean_and_empty_field_rules_are_preserved(self):
        payload = {"keep": None, "other": 1}
        for fields in (None, [], (), ["keep"], ("keep",)):
            with self.subTest(fields=fields):
                expected = {"keep": None} if fields else payload
                self.assertEqual(slim(payload, {"fields": fields, "drop_nulls": False})[0], expected)
        self.assertEqual(slim(payload, {"drop_nulls": True})[0], {"other": 1})

    def test_keeps_only_whitelisted_fields(self):
        payload = {"a": 1, "b": 2, "c": 3}
        out, _ = slim(payload, {"fields": ["a", "c"]})
        self.assertEqual(out, {"a": 1, "c": 3})

    def test_whitelist_applies_inside_list_of_dicts(self):
        payload = [{"a": 1, "b": 2}, {"a": 9, "b": 8}]
        out, _ = slim(payload, {"fields": ["a"]})
        self.assertEqual(out, [{"a": 1}, {"a": 9}])


class TestDottedPath(unittest.TestCase):
    def test_dotted_path_projection(self):
        payload = {"user": {"name": "x", "secret": "y", "id": 7}, "extra": 1}
        out, _ = slim(payload, {"fields": ["user.name"]})
        self.assertEqual(out, {"user": {"name": "x"}})

    def test_dotted_paths_sharing_prefix_merge(self):
        payload = {"user": {"name": "x", "id": 7, "drop": "z"}}
        out, _ = slim(payload, {"fields": ["user.name", "user.id"]})
        self.assertEqual(out, {"user": {"name": "x", "id": 7}})

    def test_mixed_bare_and_dotted(self):
        payload = {"user": {"name": "x", "id": 7}, "meta": {"k": "v"}}
        out, _ = slim(payload, {"fields": ["user.name", "meta"]})
        self.assertEqual(out, {"user": {"name": "x"}, "meta": {"k": "v"}})

    def test_parent_field_keeps_subtree_regardless_of_path_order(self):
        payload = {"user": {"name": "x", "id": 7}, "drop": 1}
        for fields in (["user", "user.name"], ["user.name", "user"]):
            with self.subTest(fields=fields):
                out, _ = slim(payload, {"fields": fields})
                self.assertEqual(out, {"user": payload["user"]})
                self.assertIsNot(out["user"], payload["user"])

    def test_nested_parent_path_dominates_children_and_still_applies_limits(self):
        payload = {"user": {"profile": {"name": "long", "ids": [1, 2]}, "drop": 1}}
        for fields in (["user.profile.name", "user.profile"],
                       ["user.profile", "user.profile.name"]):
            with self.subTest(fields=fields):
                out, _ = slim(payload, {"fields": fields, "max_items": 1})
                self.assertEqual(out, {"user": {"profile": {"name": "long", "ids": [1]}}})


class TestMaxItems(unittest.TestCase):
    def test_truncates_list(self):
        payload = {"items": [1, 2, 3, 4, 5]}
        out, _ = slim(payload, {"max_items": 2})
        self.assertEqual(out, {"items": [1, 2]})

    def test_max_items_zero(self):
        out, _ = slim([1, 2, 3], {"max_items": 0})
        self.assertEqual(out, [])

    def test_max_items_applies_to_nested_lists(self):
        payload = {"a": {"b": [1, 2, 3, 4]}}
        out, _ = slim(payload, {"max_items": 1})
        self.assertEqual(out, {"a": {"b": [1]}})


class TestMaxChars(unittest.TestCase):
    def test_truncates_long_string(self):
        payload = {"text": "abcdefghij"}  # len 10
        out, _ = slim(payload, {"max_chars": 4})
        self.assertEqual(out["text"], "abcd" + TRUNC_MARKER.format(n=6))

    def test_short_string_untouched(self):
        payload = {"text": "abc"}
        out, _ = slim(payload, {"max_chars": 10})
        self.assertEqual(out, {"text": "abc"})

    def test_exact_length_untouched(self):
        payload = {"text": "abcd"}
        out, _ = slim(payload, {"max_chars": 4})
        self.assertEqual(out, {"text": "abcd"})


class TestDropNulls(unittest.TestCase):
    def test_drops_none_values(self):
        payload = {"a": 1, "b": None, "c": None, "d": 4}
        out, _ = slim(payload, {"drop_nulls": True})
        self.assertEqual(out, {"a": 1, "d": 4})

    def test_drop_nulls_nested(self):
        payload = {"x": {"a": None, "b": 2}}
        out, _ = slim(payload, {"drop_nulls": True})
        self.assertEqual(out, {"x": {"b": 2}})

    def test_nulls_kept_when_flag_off(self):
        payload = {"a": None}
        out, _ = slim(payload, {})
        self.assertEqual(out, {"a": None})


class TestReductionPct(unittest.TestCase):
    def test_reduction_pct_correct(self):
        big_str = "x" * 400
        payload = {"keep": "ok", "drop": big_str}
        out, meta = slim(payload, {"fields": ["keep"]})
        orig = token_est(payload)
        slim_t = token_est(out)
        expected = round((1 - slim_t / orig) * 100, 2)
        self.assertEqual(meta["orig_tokens_est"], orig)
        self.assertEqual(meta["slim_tokens_est"], slim_t)
        self.assertEqual(meta["reduction_pct"], expected)
        self.assertGreater(meta["reduction_pct"], 0)

    def test_meta_keys_present(self):
        _, meta = slim({"a": 1}, {})
        self.assertEqual(
            set(meta.keys()),
            {"orig_tokens_est", "slim_tokens_est", "reduction_pct"},
        )

    def test_no_reduction_is_zero_pct(self):
        payload = {"a": 1, "b": 2}
        _, meta = slim(payload, {})
        self.assertEqual(meta["reduction_pct"], 0.0)


class TestEmptyRules(unittest.TestCase):
    def test_none_rules_passthrough(self):
        payload = {"a": [1, 2, {"b": None}], "c": "long string here"}
        out, meta = slim(payload, None)
        self.assertEqual(out, payload)
        self.assertEqual(meta["reduction_pct"], 0.0)

    def test_empty_dict_rules_passthrough(self):
        payload = {"a": [1, 2, 3], "b": {"c": 4}}
        out, _ = slim(payload, {})
        self.assertEqual(out, payload)

    def test_returns_copy_not_same_object(self):
        payload = {"a": {"b": 1}}
        out, _ = slim(payload, {})
        self.assertEqual(out, payload)
        self.assertIsNot(out["a"], payload["a"])


class TestCombinedRules(unittest.TestCase):
    def test_all_rules_together(self):
        payload = {
            "results": [
                {"id": 1, "body": "y" * 100, "nil": None},
                {"id": 2, "body": "z" * 100, "nil": None},
                {"id": 3, "body": "w" * 100, "nil": None},
            ],
            "ignored": "x" * 100,
        }
        rules = {
            "fields": ["results"],
            "max_items": 2,
            "max_chars": 10,
            "drop_nulls": True,
        }
        out, meta = slim(payload, rules)
        self.assertNotIn("ignored", out)
        self.assertEqual(len(out["results"]), 2)
        for item in out["results"]:
            self.assertNotIn("nil", item)
            self.assertTrue(item["body"].startswith("y" * 10) or item["body"].startswith("z" * 10))
            self.assertIn("chars]", item["body"])
        self.assertGreater(meta["reduction_pct"], 0)


class TestB11RuleValidation(unittest.TestCase):
    def test_negative_limits_rejected_not_sliced_from_end(self):
        for rules in ({"max_items": -1}, {"max_chars": -1}):
            with self.assertRaises(ValueError):
                slim({"xs": [1, 2, 3], "s": "abc"}, rules)

    def test_non_integer_limits_rejected(self):
        for bad in (True, 1.5, "2"):
            with self.assertRaises(ValueError):
                slim([1, 2, 3], {"max_items": bad})

    def test_fields_must_be_a_list(self):
        with self.assertRaises(ValueError):
            slim({"user": {"name": "n"}}, {"fields": "user.name"})
        out, _ = slim({"user": {"name": "n"}, "u": 1}, {"fields": ["user.name"]})
        self.assertEqual(out, {"user": {"name": "n"}})

    def test_rules_must_be_a_dict(self):
        with self.assertRaises(ValueError):
            slim([1], ["max_items"])

    def test_empty_non_dict_rules_are_rejected(self):
        for rules in (False, 0, "", [], ()):
            with self.subTest(rules=rules), self.assertRaises(ValueError):
                slim({"keep": 1}, rules)


if __name__ == "__main__":
    unittest.main()
