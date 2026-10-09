# cron-guard — Specification

## Problem

Scheduled AI-agent jobs (cron, launchd, systemd timers, CI schedules) fail in
three recurring ways:

1. **Overlap** — a slow run is still alive when the next tick fires, so two
   copies run at once and corrupt shared state or double-spend.
2. **Runaway cost** — a bug puts a paid API call in a loop with no ceiling.
3. **No accountability** — nobody can tell whether a job ran, when, or why it
   skipped/failed.

`cron-guard` is a pure-stdlib Python module providing locking, budgeting, and
audit primitives, plus a `guard_run` orchestrator, with cron/launchd wrappers.

## Requirements (fill-in)

| # | Requirement | Default | Status |
|---|-------------|---------|--------|
| R1 | Lock acquisition is atomic (no TOCTOU race) | `O_CREAT|O_EXCL` | done |
| R2 | Lock files record holder pid for diagnostics | pid + host + token + ts | done |
| R3 | Stale locks (dead holder pid / corrupt file) auto-reclaimed | `os.kill(pid,0)` liveness | done |
| R4 | A process cannot release a lock it does not own | token match required | done |
| R5 | Budget total survives process restarts | JSON state file | done |
| R6 | Over-cap charge is rejected and NOT persisted (fail closed) | return False | done |
| R7 | Over-cap charge can optionally raise | `raise_on_exceed=True` | done |
| R8 | Audit log is append-only, one JSON object per line | JSONL | done |
| R9 | Audit records carry a timestamp | auto-injected `ts` | done |
| R10 | `guard_run` releases the lock on every exit path (incl. exceptions) | `try/finally` | done |
| R11 | Zero third-party deps for core logic | stdlib only | done |

## Interface contract

```text
acquire_lock(lock_path: str) -> str | None
    Atomically create lock_path. Returns an opaque token on success.
    Returns None if a LIVE process already holds it. A lock owned by a
    dead pid, or an unparseable lock file, is reclaimed and acquisition
    succeeds. Creates parent dirs as needed.

release_lock(lock_path: str, token: str) -> bool
    Remove lock_path ONLY if its stored token == token. Returns True if
    removed, False otherwise (wrong token / missing file).

class BudgetGuard(state_path: str, cap: float | None)
    Persistent capped spend counter. cap < 0 or non-finite raises ValueError.
    .spend(n, raise_on_exceed=False) -> bool
        n < 0 or non-finite raises ValueError; a corrupt/unreadable state
        file raises ValueError (never silently reset). Returns True and persists if
        total + n <= cap. Returns False (and does NOT persist) if it would
        exceed cap; raises BudgetExceeded instead when raise_on_exceed=True.
        cap=None means unlimited.
    .total() -> float        current running total (0 if no state file;
                             ValueError if the file is corrupt)
    .reset() -> None         zero the counter

audit_log(log_path: str, record: dict) -> dict
    Append record as one JSON line. Injects ts (epoch sec) if absent.
    Creates parent dirs. Returns the record actually written.

read_audit_log(log_path: str) -> list[dict]
    Parse the JSONL log into a list. Returns [] if the file is missing.

guard_run(name, work_fn, lock_path, budget_state, cap, cost=1,
          audit_path=None) -> Any | GuardAborted
    Orchestrate: acquire lock -> budget.spend(cost) -> work_fn() -> audit
    -> release lock (always).
    - lock held by live process -> GuardAborted.LOCK_HELD (status skipped_locked)
    - budget would exceed cap   -> GuardAborted.BUDGET_EXCEEDED (status skipped_budget)
    - work_fn() raises           -> audited as "error", lock released, re-raised
    - success                    -> returns work_fn()'s value (status "ok")
```

### Exported symbols

`acquire_lock`, `release_lock`, `BudgetGuard`, `BudgetExceeded`, `audit_log`,
`read_audit_log`, `guard_run`, `GuardAborted`, `LockHeld`.

### Audit status vocabulary

`ok` · `error` · `skipped_locked` · `skipped_budget`

## Non-goals

- Distributed/cross-host locking (lock is host-local; pid liveness is local).
- Scheduling itself — cron/launchd remain the scheduler; this only guards runs.
- PID-reuse detection: liveness is `os.kill(pid, 0)` only (a reused pid keeps a
  stale lock looking held; no lock timeout).
- Real currency accounting — `cost` is an abstract unit chosen by the caller.
