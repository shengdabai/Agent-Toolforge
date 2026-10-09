# verify-done

Prove a task is actually done before claiming it. A Claude Code / agent skill
plus a stdlib-only Python helper that turns "I'm done" into evidence.

> "14,400 tests green while the money bled." Writing code is not the same as the
> code working.

## What it does

- **`run_checks`** — run a batch of verification checks (build, tests, smoke
  test, ...) and return a per-check pass/fail report with an aggregate verdict.
  An `expect_substr` guard catches the "exit 0 but wrong output" trap.
- **`read_back`** — confirm a file you just wrote actually exists and contains
  the content you intended.
- **`SKILL.md`** — a three-step verification protocol (read-back →
  restart-aware → smoke test) that an agent loads before claiming completion.

## Install

No installation needed for the core logic — it is pure Python standard library.

- **As a skill:** copy this directory into your skills folder (e.g.
  `~/.claude/skills/verify-done/`). The agent picks it up via `SKILL.md`.
- **As a library:** import `verify.py` directly, or copy it into your project.

```python
from verify import run_checks, read_back
```

## Usage

```python
from verify import run_checks, read_back

# 1. Read-back: did the write land?
rb = read_back("config.json", must_contain=["model", "opus"])
if not rb["passed"]:
    print("write incomplete, missing:", rb["missing"])

# 2 & 3. Restart the service, then smoke test.
report = run_checks([
    {"name": "build", "cmd": "make build", "expect_exit": 0},
    {"name": "tests", "cmd": "pytest -q",  "expect_exit": 0, "expect_substr": "passed"},
    {"name": "smoke", "cmd": "curl -fsS localhost:8080/health", "expect_substr": "ok"},
])

print("all_passed:", report["all_passed"])
for r in report["results"]:
    if not r["passed"]:
        print(r["name"], "FAILED:", r["reason"])
        print(r["output_snippet"])
```

### Testing your own logic without a shell

`run_checks` accepts an injectable `runner(cmd) -> (exit_code, output)`, so you
can unit-test verification flows without spawning real processes:

```python
def fake_runner(cmd):
    return (0, "5 passed")

run_checks([{"name": "t", "cmd": "pytest"}], runner=fake_runner)
```

## Input contract

Malformed input raises `ValueError` instead of silently passing:

- `run_checks`: a check without `cmd`; `expect_exit` that is not an `int` (a
  `bool` such as `True` is rejected, since `True == 1`); `expect_substr` that is
  not a non-empty string. The whole call raises, so no partial report is
  returned.
- `read_back`: any `must_contain` entry that is not a non-empty string (an empty
  string is a substring of everything and would "confirm" nothing).
- A runner that returns a `bool` exit code never matches `expect_exit`; a runner
  that returns non-`str` output has it converted with `str()`; a runner that
  raises yields a failed check with `reason: "runner raised: <ExceptionName>"`.
- `read_back` on a missing or unreadable (non-UTF-8) file returns
  `{"passed": False, "exists": False, "missing": [...all required...]}` rather
  than raising.

## 已知限制 (known limitations)

Current behaviour, documented rather than changed:

- **`run_checks([])` returns `all_passed=True`.** An empty check list is
  vacuously "passed" (this is what `SPEC.md` specifies and a test pins). It is
  zero evidence, so callers must make sure the list is not empty before treating
  `all_passed` as proof of completion.
- The default runner has no timeout: a command that hangs blocks `run_checks`
  forever. Use an injected `runner` (or `timeout` in the command itself) for
  anything that may hang.
- The default runner uses `shell=True`; only pass trusted commands.
- Only the last 2,000 characters of output are kept in `output_snippet`.

## Test

```bash
cd products/verify-done
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

All tests use only the Python standard library (`unittest`, `tempfile`). No
network, no third-party packages, no `pip install`.

## Files

| File                       | Purpose                                  |
|----------------------------|------------------------------------------|
| `verify.py`                | Core logic: `run_checks`, `read_back`    |
| `SKILL.md`                 | Skill definition + verification protocol |
| `SPEC.md`                  | Requirements and interface contract      |
| `tests/test_run_checks.py` | Tests for `run_checks`                    |
| `tests/test_read_back.py`  | Tests for `read_back`                     |
