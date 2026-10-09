# SPEC — verify-done

## Problem

AI agents routinely claim a task is "done" after only writing code, without
running anything. The result is silent failure: tests reported green while the
actual product was broken. This skill makes verification mechanical and forces
evidence before a completion claim.

## Form

Skill (SKILL.md with trigger frontmatter) + a stdlib-only Python helper module
(`verify.py`) + unittest suite.

## Requirements (fill-in answers)

- **Who triggers it?** An agent (or the user) about to claim done/fixed/complete,
  or anyone asking to verify / smoke test / read-back a change.
- **What does it produce?** A pass/fail report per check and an aggregate
  verdict; plus a file-content read-back result.
- **Dependencies?** Python 3 standard library only. No network, no pip.
- **How is it tested without a shell?** A `runner` callable is injected into
  `run_checks`; tests pass a fake runner. `read_back` is tested against real
  temp files (stdlib `tempfile`).

## Interface contract

### `run_checks(checks, runner=None) -> report`

Input `checks`: list of dicts.

| key            | type | required | default | meaning                                   |
|----------------|------|----------|---------|-------------------------------------------|
| `name`         | str  | no\*     | `cmd`   | human label (falls back to the command)   |
| `cmd`          | str  | yes      | —       | command string passed to the runner       |
| `expect_exit`  | int  | no       | `0`     | exit code that counts as success          |
| `expect_substr`| str  | no       | none    | if set, must appear in the output         |

A malformed expectation raises `ValueError` (like a missing `cmd`): `expect_exit`
must be a non-bool int and `expect_substr` a non-empty string. A runner that
returns a bool exit code never matches.

`runner(cmd) -> (exit_code: int, output: str)`. Defaults to a shell runner
(`subprocess`, stdout+stderr merged). Injectable for tests.

Output `report`:

```python
{
  "all_passed": bool,            # True iff every check passed (empty -> True)
  "results": [
    {
      "name": str,
      "passed": bool,
      "actual_exit": int | None, # None if the runner raised
      "output_snippet": str,     # tail-truncated to 2000 chars
      "reason": str,             # "ok" or the failure reason(s)
    },
    ...
  ],
}
```

Behavior:
- Missing `cmd` key -> raises `ValueError`.
- Runner raising an exception -> that check fails (not crash); `actual_exit` is
  `None`, `output_snippet` carries the exception text.
- A check passes iff `actual_exit == expect_exit` AND (no `expect_substr` or it
  is present in output).

### `read_back(path, must_contain) -> result`

`must_contain` is a string or list of strings.

```python
{
  "passed": bool,        # exists AND no missing substrings
  "exists": bool,        # whether the file could be read
  "missing": [str, ...], # required substrings not found (all of them if absent)
}
```

Behavior:
- Missing/unreadable file -> `passed=False`, `exists=False`, every required
  substring listed in `missing`.

## Out of scope

- Parallel check execution (run sequentially; deterministic order).
- Parsing structured test reports (substring match is intentionally simple).
- Performing restarts (the protocol documents it; the helper does not automate).
