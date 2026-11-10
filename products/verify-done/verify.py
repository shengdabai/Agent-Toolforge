"""verify-done core: turn "I'm done" into evidence.

Pure stdlib. No network, no third-party packages. The check runner is
injectable so tests can prove the logic without spawning a real shell.

Public API
----------
run_checks(checks, runner=None) -> report
    checks: list of dicts, each:
        name         (str, required)  human label
        cmd          (str, required)  the command to run
        expect_exit  (int, optional)  default 0
        expect_substr(str, optional)  if set, must appear in output
    report:
        {"all_passed": bool, "results": [ {name, passed, actual_exit,
          output_snippet, reason}, ... ]}

read_back(path, must_contain) -> result
    Confirm a file exists and contains the required substring(s).
        {"passed": bool, "exists": bool, "missing": [str, ...]}
"""

import subprocess

SNIPPET_LIMIT = 2000


def _default_runner(cmd):
    """Run cmd in a shell, return (exit_code, combined_output).

    Used only when no runner is injected. stdout and stderr are merged so a
    single snippet captures everything an agent would need to diagnose.
    """
    proc = subprocess.run(
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    return proc.returncode, proc.stdout or ""


def _snippet(text):
    text = text or ""
    if len(text) <= SNIPPET_LIMIT:
        return text
    # Keep the tail — failures usually surface at the end of output.
    return "...(truncated)...\n" + text[-SNIPPET_LIMIT:]


def _run_one(check, runner):
    name = check.get("name")
    cmd = check.get("cmd")
    if not cmd:
        raise ValueError("check is missing required 'cmd' key: %r" % (check,))
    if name is None:
        name = cmd

    expect_exit = check.get("expect_exit", 0)
    expect_substr = check.get("expect_substr")
    # A malformed expectation must never be able to pass (True == 1 in
    # Python) or crash the run with an unrelated TypeError mid-report.
    if not isinstance(expect_exit, int) or isinstance(expect_exit, bool):
        raise ValueError("check %r: 'expect_exit' must be an int" % (name,))
    if expect_substr is not None and (
        not isinstance(expect_substr, str) or expect_substr == ""
    ):
        raise ValueError(
            "check %r: 'expect_substr' must be a non-empty string" % (name,)
        )

    try:
        actual_exit, output = runner(cmd)
    except Exception as exc:  # runner blew up (e.g. binary not found)
        return {
            "name": name,
            "passed": False,
            "actual_exit": None,
            "output_snippet": _snippet(str(exc)),
            "reason": "runner raised: %s" % (exc.__class__.__name__,),
        }

    if not isinstance(output, str):
        output = "" if output is None else str(output)
    passed = True
    reasons = []

    if not isinstance(actual_exit, int) or isinstance(actual_exit, bool):
        passed = False
        reasons.append("runner exit code must be an int (excluding bool)")
    elif actual_exit != expect_exit:
        passed = False
        reasons.append("exit %r != expected %r" % (actual_exit, expect_exit))

    if expect_substr is not None and expect_substr not in output:
        passed = False
        reasons.append("expect_substr %r not found in output" % (expect_substr,))

    return {
        "name": name,
        "passed": passed,
        "actual_exit": actual_exit,
        "output_snippet": _snippet(output),
        "reason": "ok" if passed else "; ".join(reasons),
    }


def run_checks(checks, runner=None):
    """Run every check, collect per-check results, and an aggregate verdict."""
    if runner is None:
        runner = _default_runner

    results = [_run_one(check, runner) for check in checks]
    all_passed = all(r["passed"] for r in results)
    return {"all_passed": all_passed, "results": results}


def read_back(path, must_contain):
    """Verify `path` exists and contains every required substring.

    `must_contain` may be a single string or a list of strings. Returns a
    result with the list of substrings that were NOT found.
    """
    if isinstance(must_contain, str):
        required = [must_contain]
    else:
        required = list(must_contain)
    # "" is a substring of everything; accepting it would confirm nothing.
    for needle in required:
        if not isinstance(needle, str) or needle == "":
            raise ValueError("must_contain entries must be non-empty strings")

    try:
        with open(path, "r", encoding="utf-8") as fh:
            content = fh.read()
        exists = True
    except (OSError, UnicodeDecodeError):
        # Missing file (or unreadable) -> nothing can be confirmed present.
        return {"passed": False, "exists": False, "missing": required}

    missing = [needle for needle in required if needle not in content]
    return {
        "passed": exists and not missing,
        "exists": exists,
        "missing": missing,
    }
