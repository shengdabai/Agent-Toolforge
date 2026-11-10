"""Tests for verify.run_checks — the core check runner.

A fake runner is injected so no real shell is spawned. The fake runner
mimics subprocess behaviour: given a command, it returns (exit_code, output).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from verify import run_checks  # noqa: E402


def make_runner(table):
    """Build a fake runner from a {cmd: (exit_code, output)} table."""

    def runner(cmd):
        if cmd not in table:
            raise AssertionError("unexpected command: %r" % (cmd,))
        return table[cmd]

    return runner


class RunChecksAllPass(unittest.TestCase):
    def test_all_pass_sets_all_passed_true(self):
        checks = [
            {"name": "build", "cmd": "make build", "expect_exit": 0},
            {"name": "tests", "cmd": "pytest", "expect_exit": 0},
        ]
        runner = make_runner({"make build": (0, "ok"), "pytest": (0, "5 passed")})

        report = run_checks(checks, runner=runner)

        self.assertTrue(report["all_passed"])
        self.assertEqual(len(report["results"]), 2)
        self.assertTrue(all(r["passed"] for r in report["results"]))

    def test_default_expect_exit_is_zero(self):
        # expect_exit omitted -> defaults to 0
        checks = [{"name": "lint", "cmd": "ruff check"}]
        runner = make_runner({"ruff check": (0, "All checks passed")})

        report = run_checks(checks, runner=runner)

        self.assertTrue(report["all_passed"])
        self.assertEqual(report["results"][0]["actual_exit"], 0)


class RunChecksExitFailure(unittest.TestCase):
    def test_nonzero_exit_fails_and_flags_offending_check(self):
        checks = [
            {"name": "build", "cmd": "make build", "expect_exit": 0},
            {"name": "tests", "cmd": "pytest", "expect_exit": 0},
        ]
        runner = make_runner(
            {"make build": (0, "ok"), "pytest": (1, "1 failed, 4 passed")}
        )

        report = run_checks(checks, runner=runner)

        self.assertFalse(report["all_passed"])
        failed = [r for r in report["results"] if not r["passed"]]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["name"], "tests")
        self.assertEqual(failed[0]["actual_exit"], 1)

    def test_custom_expect_exit_nonzero_passes_when_matched(self):
        # A check that intentionally expects a non-zero exit code.
        checks = [{"name": "should-error", "cmd": "false", "expect_exit": 1}]
        runner = make_runner({"false": (1, "")})

        report = run_checks(checks, runner=runner)

        self.assertTrue(report["all_passed"])
        self.assertTrue(report["results"][0]["passed"])

    def test_output_snippet_captured_on_failure(self):
        checks = [{"name": "tests", "cmd": "pytest", "expect_exit": 0}]
        runner = make_runner({"pytest": (2, "boom traceback line")})

        report = run_checks(checks, runner=runner)

        self.assertFalse(report["all_passed"])
        self.assertIn("boom", report["results"][0]["output_snippet"])


class RunChecksSubstr(unittest.TestCase):
    def test_expect_substr_match_passes(self):
        checks = [
            {
                "name": "tests",
                "cmd": "pytest",
                "expect_exit": 0,
                "expect_substr": "passed",
            }
        ]
        runner = make_runner({"pytest": (0, "5 passed in 0.1s")})

        report = run_checks(checks, runner=runner)

        self.assertTrue(report["all_passed"])

    def test_expect_substr_missing_fails_even_with_exit_zero(self):
        checks = [
            {
                "name": "tests",
                "cmd": "pytest",
                "expect_exit": 0,
                "expect_substr": "5 passed",
            }
        ]
        # Exit code is fine, but the expected substring is absent.
        runner = make_runner({"pytest": (0, "0 passed, all skipped")})

        report = run_checks(checks, runner=runner)

        self.assertFalse(report["all_passed"])
        result = report["results"][0]
        self.assertFalse(result["passed"])
        self.assertEqual(result["actual_exit"], 0)
        # reason should mention substring mismatch
        self.assertIn("substr", result["reason"].lower())


class RunChecksEdge(unittest.TestCase):
    def test_actual_exit_requires_integer_excluding_bool(self):
        for value in (0.0, 1.0, 0j, 1+0j, True, False, None, '0', '1'):
            for expected in (0, 1):
                with self.subTest(value=value, expected=expected):
                    report = run_checks(
                        [{'name': 'x', 'cmd': 'c', 'expect_exit': expected}],
                        runner=lambda c: (value, 'ok'))
                    self.assertFalse(report['all_passed'])
                    self.assertIn('exit', report['results'][0]['reason'])

    def test_integer_exit_codes_still_match(self):
        for value in (-15, 0, 1, 255):
            with self.subTest(value=value):
                self.assertTrue(run_checks(
                    [{'name': 'x', 'cmd': 'c', 'expect_exit': value}],
                    runner=lambda c: (value, ''))['all_passed'])

    def test_empty_checks_is_vacuously_passed(self):
        report = run_checks([], runner=make_runner({}))
        self.assertTrue(report["all_passed"])
        self.assertEqual(report["results"], [])

    def test_runner_exception_is_caught_as_failure(self):
        def boom_runner(cmd):
            raise OSError("command not found")

        checks = [{"name": "missing", "cmd": "nonexistent-bin"}]
        report = run_checks(checks, runner=boom_runner)

        self.assertFalse(report["all_passed"])
        self.assertFalse(report["results"][0]["passed"])
        self.assertIn("not found", report["results"][0]["output_snippet"])

    def test_missing_cmd_key_raises_valueerror(self):
        with self.assertRaises(ValueError):
            run_checks([{"name": "bad"}], runner=make_runner({}))

    # --- b11 regressions: malformed expectations must not pass or crash ---
    def test_bool_expect_exit_rejected(self):
        with self.assertRaises(ValueError):
            run_checks([{"name": "x", "cmd": "c", "expect_exit": True}],
                       runner=lambda c: (1, ""))

    def test_non_string_or_empty_expect_substr_rejected(self):
        for bad in (5, "", ["a"]):
            with self.assertRaises(ValueError):
                run_checks([{"name": "x", "cmd": "c", "expect_substr": bad}],
                           runner=lambda c: (0, "5"))

    def test_bool_actual_exit_never_matches(self):
        report = run_checks([{"name": "x", "cmd": "c", "expect_exit": 1}],
                            runner=lambda c: (True, ""))
        self.assertFalse(report["all_passed"])

    def test_non_string_output_does_not_crash(self):
        report = run_checks([{"name": "x", "cmd": "c", "expect_substr": "ok"}],
                            runner=lambda c: (0, b"ok"))
        self.assertIn("passed", report["results"][0])


if __name__ == "__main__":
    unittest.main()
