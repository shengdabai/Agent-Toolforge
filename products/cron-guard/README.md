# cron-guard

Defensive scheduling primitives for AI-agent cron/launchd jobs. Prevents
**overlapping runs**, caps **runaway cost**, and keeps an **audit trail** — all
in one pure-stdlib Python module, packaged as an agent Skill.

## Why

Schedulers like cron and launchd fire a job on a timer but do nothing to stop a
new run from starting while the previous one is still alive, nothing to stop a
buggy loop from spending without limit, and nothing to tell you afterward what
happened. `cron-guard` adds those three guarantees.

## What's inside

| File | Purpose |
|------|---------|
| `cronguard.py` | Core logic: locking, budget, audit, `guard_run` (stdlib only) |
| `SKILL.md` | Agent Skill manifest + locking/budget/audit protocol + wrappers |
| `SPEC.md` | Requirements and interface contract |
| `wrapper.sh` | Runnable cron/launchd shell wrapper template |
| `tests/` | `unittest` test suite |

## Install

No installation needed for the core — it's a single file with no third-party
dependencies. Copy `cronguard.py` next to your job, or add this directory to
`PYTHONPATH`.

As a Skill: place this directory under your agent's skills path; the
`SKILL.md` frontmatter triggers on scheduling / overlap / budget / audit
intents.

## Usage

```python
from pathlib import Path
from cronguard import guard_run, GuardAborted

state = Path.home() / ".local/state/cron-guard"
state.mkdir(mode=0o700, parents=True, exist_ok=True)

def work():
    # the actual job
    return "done"

result = guard_run(
    name="daily-digest",
    work_fn=work,
    lock_path=str(state / "daily-digest.lock"),
    budget_state=str(state / "daily-digest.budget.json"),
    cap=100,            # at most 100 cost-units total
    cost=1,             # this run costs 1 unit
    audit_path=str(state / "daily-digest.audit.jsonl"),
)

if result is GuardAborted.LOCK_HELD:
    print("already running; skipped")
elif result is GuardAborted.BUDGET_EXCEEDED:
    print("budget exhausted; skipped")
else:
    print("ran:", result)
```

Lower-level primitives (`acquire_lock`, `release_lock`, `BudgetGuard`,
`audit_log`, `read_audit_log`) are documented in `SKILL.md` and `SPEC.md`.

### Wiring into cron / launchd

Use `wrapper.sh` as the program the scheduler invokes. It calls a
`guard_run`-protected Python entry point, so overlap/budget/audit are enforced
regardless of how the scheduler behaves. See `SKILL.md` for the `.plist` and
crontab templates.

The wrapper now defaults to `$HOME/.local/state/cron-guard`, which persists
across temporary-directory cleanup. `CRONGUARD_STATE_DIR` overrides this path.
It creates the state directory with mode `0700` and refuses existing symlinks,
directories owned by another user, or group/other-accessible directories.
Keep the directory and its parents under trusted control; direct Python callers
must enforce the same directory requirements themselves. New state files use
mode `0600`; audit and mutex append targets reject symlinks and non-regular files.

When upgrading from the old temporary-directory default, stop scheduled jobs
and copy the existing budget into the private directory before restarting.
Preserve the previous total: a missing budget starts at zero. Keep a backup
of the old state until the new path and total have been verified.

## Test

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
# or simply:
python3 -m unittest
```

All tests use only the Python standard library and temporary directories — no
network, no writes outside `tempfile`.

## Design notes

- **Atomic lock**: `os.open(..., O_CREAT | O_EXCL)` — the create-or-fail is a
  single syscall, so two processes can't both win. Acquire/release (and budget
  updates) are additionally serialized with a POSIX `flock` on a sidecar file
  `<lock_path>.mutex` / `<budget_state>.mutex`, so reclaiming a stale or
  half-written lock cannot race another process.
- **Stale-lock reclaim**: a lock whose holder pid is dead (or whose file is
  corrupt) is removed and re-acquired, so a crash doesn't wedge the schedule
  forever.
- **Token-guarded release**: only the holder (matching token) can release,
  preventing accidental cross-release.
- **Fail-closed budget**: a charge that would exceed the cap is rejected and
  not written, so partial/over-spend can't sneak in. Bad inputs and bad state
  fail closed too: a negative or non-finite `cap` / spend amount raises
  `ValueError`, and an unreadable or corrupt budget file makes `total()` /
  `spend()` raise `ValueError` ("refusing to reset spending") instead of
  silently restarting from 0. `cap=None` means unlimited.
- **Always-release**: `guard_run` releases the lock in a `finally`, even when
  the job raises.

## 已知限制 (known limitations)

Current behaviour, documented rather than changed:

- **PID reuse**: liveness is checked only with `os.kill(pid, 0)`. If a crashed
  job's pid has since been reused by an unrelated live process, its lock still
  looks held, so `acquire_lock` returns `None` / `guard_run` returns
  `GuardAborted.LOCK_HELD` until that pid exits or the lock file is removed by
  hand. The stored `host`, `ts` and process start time are not used to detect
  this, and there is no lock timeout.
- **Host-local, POSIX only**: pid liveness is local and the mutex uses
  `fcntl.flock`; it is not a distributed lock and not available on Windows.
- **Budget is charged before the work runs** and is not refunded if `work_fn`
  raises. The total never resets by itself; call `BudgetGuard.reset()` at the
  start of each billing window.
- **Sidecar files**: the `.mutex` files are intentionally never deleted.
- `read_audit_log` raises `ValueError` if a line is not valid JSON (for
  example a half-written last line after a crash).
