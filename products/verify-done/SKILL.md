---
name: verify-done
description: "Prove a task is actually done before claiming it. Use whenever you are about to say \"done\", \"fixed\", \"complete\", \"shipped\" or \"it works\", or when asked to verify, confirm, smoke test, read-back or double-check a change (\"is it really working\", \"did it actually pass\"). Enforces read-back, restart-aware check and smoke test so success is never reported on unproven work."
---

# verify-done

"14,400 tests green while the money bled." Writing code is not the same as the
code working. This skill turns "I'm done" into evidence.

## Iron law

Writing != done. You may not claim success until you have run the checks and
read the real output. If you cannot run a check, say so explicitly — never
assume success.

## The three-step protocol

Run these in order before any completion claim.

### 1. Read-back

Re-open the artifact you just wrote and confirm the intended content is there.

```python
from verify import read_back

r = read_back("config.json", must_contain=["model", "opus"])
assert r["passed"], "still missing: %s" % r["missing"]
```

A write that "succeeded" but produced the wrong content is a silent failure.
`read_back` catches it: it reports `exists` and the list of `missing`
substrings so you know exactly what went wrong.

### 2. Restart-aware

Config that lives in a running process is not live until the process reloads
it. Before smoke-testing, restart whatever caches the value:

- gateways / model routers (in-memory model selection)
- launchd / systemd services (`unload` + `load`)
- MCP servers (restart the server)
- the editor/app that may overwrite the file you just changed

If nothing caches the change, record "no restart needed" — but say it.

### 3. Smoke test

Run a minimal end-to-end check and assert on the *actual* output, not just the
exit code. Use `run_checks` to batch them:

```python
from verify import run_checks

report = run_checks([
    {"name": "build",  "cmd": "make build",  "expect_exit": 0},
    {"name": "tests",  "cmd": "pytest -q",   "expect_exit": 0, "expect_substr": "passed"},
    {"name": "smoke",  "cmd": "curl -fsS localhost:8080/health", "expect_substr": "ok"},
])

if not report["all_passed"]:
    for r in report["results"]:
        if not r["passed"]:
            print(r["name"], "FAILED:", r["reason"])
            print(r["output_snippet"])
```

`expect_substr` is the anti-"green-but-wrong" guard: exit 0 with the wrong
output still fails the check.

Input is validated strictly: a check without `cmd`, an `expect_exit` that is not
an int (booleans are rejected), or an `expect_substr` that is not a non-empty
string raises `ValueError`. `read_back` likewise raises `ValueError` for empty or
non-string `must_contain` entries, and returns `exists: False` for a missing or
unreadable file.

**Caveat: `run_checks([])` returns `all_passed=True`** (vacuous pass, per SPEC).
An empty list is not evidence — never report "verified" off an empty check list.
The default runner also has no timeout and uses `shell=True`.

## Completion report format

When you do claim done, paste the evidence:

```
Read-back: <key snippet from the file>
Restart:   <service restarted, or "no restart needed">
Smoke test: <command + observed output, or "not run, reason: ...">
Verdict:   all_passed=<true/false>
```

If `all_passed` is false, you are not done. Keep iterating.

## Anti-patterns

- Saying "done" / "fixed" after only an edit, with no read-back.
- Trusting exit 0 alone when the output is what actually matters.
- Forgetting that a cached config needs a restart to take effect.
- Claiming "verified" when you never ran the command — say "not run" instead.

Scope: pairs with fresh-eyes-review (independent review) and cron-guard (scheduled jobs); this skill only proves a change works.

## Helper module

`verify.py` (stdlib only) provides:

- `run_checks(checks, runner=None)` — run a list of checks, return
  `{all_passed, results}`. Inject `runner` to test without a shell.
- `read_back(path, must_contain)` — confirm a file exists and contains the
  required substring(s), return `{passed, exists, missing}`.

See `README.md` for install and test commands.
