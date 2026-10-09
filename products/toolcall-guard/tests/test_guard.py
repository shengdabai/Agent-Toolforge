import os
import sys
import unittest

# Make the package root importable without installation.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from guard import validate, correction_hint, repair_json  # noqa: E402


PERSON_SCHEMA = {
    "type": "object",
    "required": ["name", "age"],
    "properties": {
        "name": {"type": "string"},
        "age": {"type": "integer"},
        "role": {"type": "string", "enum": ["admin", "user", "guest"]},
    },
}


class TestValidateCompliant(unittest.TestCase):
    def test_fully_compliant_args_yield_no_errors(self):
        errors = validate({"name": "Ada", "age": 36, "role": "admin"}, PERSON_SCHEMA)
        self.assertEqual(errors, [])

    def test_optional_field_absent_is_fine(self):
        errors = validate({"name": "Ada", "age": 36}, PERSON_SCHEMA)
        self.assertEqual(errors, [])


class TestValidateRequired(unittest.TestCase):
    def test_missing_required_is_flagged_with_path(self):
        errors = validate({"name": "Ada"}, PERSON_SCHEMA)
        kinds = {e["kind"] for e in errors}
        self.assertIn("required", kinds)
        paths = {e["path"] for e in errors if e["kind"] == "required"}
        self.assertIn("age", paths)

    def test_required_error_has_all_three_keys(self):
        errors = validate({"name": "Ada"}, PERSON_SCHEMA)
        self.assertTrue(errors)
        for e in errors:
            self.assertIn("path", e)
            self.assertIn("message", e)
            self.assertIn("kind", e)


class TestValidateType(unittest.TestCase):
    def test_type_mismatch_is_flagged(self):
        errors = validate({"name": "Ada", "age": "thirty"}, PERSON_SCHEMA)
        type_errors = [e for e in errors if e["kind"] == "type"]
        self.assertTrue(type_errors)
        self.assertIn("age", {e["path"] for e in type_errors})

    def test_integer_rejects_bool(self):
        # bool is a subclass of int in Python; integer type must reject True.
        errors = validate({"name": "Ada", "age": True}, PERSON_SCHEMA)
        self.assertTrue(any(e["kind"] == "type" and e["path"] == "age" for e in errors))

    def test_number_accepts_int_and_float(self):
        schema = {"type": "object", "properties": {"x": {"type": "number"}}}
        self.assertEqual(validate({"x": 3}, schema), [])
        self.assertEqual(validate({"x": 3.5}, schema), [])

    def test_nested_object_type_path_is_dotted(self):
        schema = {
            "type": "object",
            "properties": {
                "addr": {
                    "type": "object",
                    "properties": {"zip": {"type": "string"}},
                }
            },
        }
        errors = validate({"addr": {"zip": 12345}}, schema)
        self.assertTrue(any(e["path"] == "addr.zip" and e["kind"] == "type" for e in errors))


class TestValidateEnum(unittest.TestCase):
    def test_value_not_in_enum_is_flagged(self):
        errors = validate({"name": "Ada", "age": 36, "role": "superuser"}, PERSON_SCHEMA)
        enum_errors = [e for e in errors if e["kind"] == "enum"]
        self.assertTrue(enum_errors)
        self.assertIn("role", {e["path"] for e in enum_errors})


class TestRepairJson(unittest.TestCase):
    def test_trailing_comma_in_object(self):
        ok, obj = repair_json('{"a": 1, "b": 2,}')
        self.assertTrue(ok)
        self.assertEqual(obj, {"a": 1, "b": 2})

    def test_trailing_comma_in_array(self):
        ok, obj = repair_json('[1, 2, 3,]')
        self.assertTrue(ok)
        self.assertEqual(obj, [1, 2, 3])

    def test_single_quotes_converted(self):
        ok, obj = repair_json("{'name': 'Ada', 'age': 36}")
        self.assertTrue(ok)
        self.assertEqual(obj, {"name": "Ada", "age": 36})

    def test_missing_closing_brace_appended(self):
        ok, obj = repair_json('{"a": 1, "b": 2')
        self.assertTrue(ok)
        self.assertEqual(obj, {"a": 1, "b": 2})

    def test_missing_closing_bracket_appended(self):
        ok, obj = repair_json('[1, 2, 3')
        self.assertTrue(ok)
        self.assertEqual(obj, [1, 2, 3])

    def test_combined_breakage(self):
        ok, obj = repair_json("{'a': [1, 2,], 'b': 'x'")
        self.assertTrue(ok)
        self.assertEqual(obj, {"a": [1, 2], "b": "x"})

    def test_already_valid_passes_through(self):
        ok, obj = repair_json('{"a": 1}')
        self.assertTrue(ok)
        self.assertEqual(obj, {"a": 1})

    def test_irreparable_garbage_returns_false_none(self):
        ok, obj = repair_json("this is not json at all <<>>")
        self.assertFalse(ok)
        self.assertIsNone(obj)

    def test_empty_string_returns_false_none(self):
        ok, obj = repair_json("")
        self.assertFalse(ok)
        self.assertIsNone(obj)


class TestCorrectionHint(unittest.TestCase):
    def test_hint_contains_each_field_path(self):
        errors = validate({"name": "Ada", "role": "superuser"}, PERSON_SCHEMA)
        hint = correction_hint(errors)
        self.assertIsInstance(hint, str)
        for e in errors:
            self.assertIn(e["path"], hint)

    def test_hint_mentions_kinds(self):
        errors = validate({"name": 1, "age": "x"}, PERSON_SCHEMA)
        hint = correction_hint(errors)
        self.assertIn("type", hint)

    def test_empty_errors_hint_is_nonempty(self):
        hint = correction_hint([])
        self.assertIsInstance(hint, str)
        self.assertTrue(hint.strip())


class TestB11Regressions(unittest.TestCase):
    def test_union_type_is_enforced(self):
        schema = {"type": "object",
                  "properties": {"a": {"type": ["string", "null"]}}}
        self.assertEqual(validate({"a": "x"}, schema), [])
        self.assertEqual(validate({"a": None}, schema), [])
        errors = validate({"a": 5}, schema)
        self.assertEqual([e["kind"] for e in errors], ["type"])
        self.assertEqual(errors[0]["path"], "a")

    def test_union_with_unknown_member_stays_forward_compatible(self):
        schema = {"type": ["string", "future-type"]}
        self.assertEqual(validate(5, schema), [])

    def test_enum_does_not_confuse_bool_and_int(self):
        schema = {"type": "object", "properties": {"a": {"enum": [1, 2]}}}
        self.assertEqual(validate({"a": 1}, schema), [])
        self.assertEqual([e["kind"] for e in validate({"a": True}, schema)],
                         ["enum"])
        schema = {"type": "object", "properties": {"a": {"enum": [True]}}}
        self.assertEqual(validate({"a": True}, schema), [])
        self.assertTrue(validate({"a": 1}, schema))

    def test_pathologically_deep_json_fails_closed(self):
        self.assertEqual(repair_json("[" * 200000), (False, None))
        self.assertEqual(repair_json("{'a':" * 50000), (False, None))


if __name__ == "__main__":
    unittest.main()
