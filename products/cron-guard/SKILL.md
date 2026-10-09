---
name: cron-guard
description: "Defensive wrapper for scheduled AI-agent jobs. Use when setting up or hardening recurring tasks under cron or launchd (定时, 调度, agent 定时任务, scheduled agent), preventing overlapping runs (防重叠), capping runaway cost (预算上限, budget cap) or keeping an audit log. Provides atomic lock files, a persistent budget counter, JSONL audit logging, a guard_run orchestrator and launchd/cron wrapper templates."
---

# cron-guard

Stop scheduled agents from stepping on themselves, burning money, or running
without a paper trail. Three primitives plus one orchestrator, all pure
stdlib Python (`cronguard.py`).

## When to use

- An agent job runs on a timer (cron / launchd / systemd timer / CI schedule).
- A previous run can still be alive when the next tick fires (slow job + tight
  schedule) → you need **overlap protection**.
- The job calls a paid API in a loop and a bug could spend without bound → you
  need a **budget cap**.
- You need to answer "did it run, when, and what happened?" → you need an
  **audit log**.

## The three protocols

### 1. Locking (no overlapping runs)

`acquire_lock(lock_path)` atomically creates the lock file with
`O_CREAT | O_EXCL` and writes the holder's pid + a random token.

- Already held by a **live** process → returns `None` (caller should skip).
- Held by a **dead** pid, or a corrupt lock file → treated as **stale** and
  reclaimed automatically (liveness checked via `os.kill(pid, 0)`).
  Caveat: a dead job's pid that was reused by an unrelated live process still
  looks held (no lock timeout), so the run is skipped until that pid exits or
  the lock file is removed manually.

`release_lock(lock_path, token)` removes the lock **only** if the stored token
matches, so a process can never release a lock it doesn't own.

```python
from cronguard import acquire_lock, release_lock

token = acquire_lock("/tmp/myjob.lock")
if token is None:
    raise SystemExit("another run is in progress; skipping")
try:
    do_work()
finally:
    release_lock("/tmp/myjob.lock", token)
```

### 2. Budget (no runaway cost)

`BudgetGuard(state_path, cap)` keeps a running total in a JSON file that
survives restarts. `spend(n)` returns `False` when the charge would exceed the
cap (and does **not** persist the rejected charge — fail closed). Pass
`raise_on_exceed=True` to raise `BudgetExceeded` instead. A negative or
non-finite `cap` or spend amount raises `ValueError`; so does an unreadable /
corrupt state file (it is never silently reset to 0). `cap=None` = unlimited.

```python
from cronguard import BudgetGuard

budget = BudgetGuard("/var/lib/myjob/budget.json", cap=100)
if not budget.spend(1):          # one unit per run, max 100
    raise SystemExit("monthly budget exhausted")
# reset the counter at the start of each billing window:
# budget.reset()
```

### 3. Audit (paper trail)

`audit_log(log_path, record)` appends one JSON object per line (JSONL). A `ts`
epoch timestamp is injected automatically. `read_audit_log(log_path)` reads it
all back.

```python
from cronguard import audit_log, read_audit_log

audit_log("/var/log/myjob.audit.jsonl", {"name": "myjob", "status": "ok"})
records = read_audit_log("/var/log/myjob.audit.jsonl")
```

## One-call orchestrator: guard_run

`guard_run` wires all three together in the right order:

> acquire lock → budget check → run `work_fn` → audit → release lock (always).

```python
from cronguard import guard_run, GuardAborted

def work():
    # ... the actual job; return anything
    return "done"

result = guard_run(
    name="daily-digest",
    work_fn=work,
    lock_path="/tmp/daily-digest.lock",
    budget_state="/var/lib/daily-digest/budget.json",
    cap=100,
    cost=1,
    audit_path="/var/log/daily-digest.audit.jsonl",
)

if result is GuardAborted.LOCK_HELD:
    ...   # a previous run is still going; skipped, audited as skipped_locked
elif result is GuardAborted.BUDGET_EXCEEDED:
    ...   # cap reached; skipped, audited as skipped_budget
else:
    ...   # work ran; result is work_fn's return value, audited as ok
```

Exceptions raised by `work_fn` are audited as `error` and re-raised after the
lock is released — the guard never swallows your job's failures. The cost is
charged before `work_fn` runs and is not refunded on failure.

Audit `status` values: `ok`, `error`, `skipped_locked`, `skipped_budget`.

## launchd wrapper template (macOS)

`launchd` itself does not prevent overlapping runs when a job runs long. Wrap
the entry point with `guard_run`. Minimal `.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>          <string>com.example.daily-digest</string>
  <key>ProgramArguments</key>
  <array>
    <string>/path/to/wrapper.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key>  <string>/tmp/daily-digest.out.log</string>
  <key>StandardErrorPath</key><string>/tmp/daily-digest.err.log</string>
</dict>
</plist>
```

Load: `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.example.daily-digest.plist`

## cron wrapper template (Linux)

```cron
# Run hourly; wrapper.sh handles overlap, budget, and audit internally.
0 * * * * /path/to/wrapper.sh >> /tmp/daily-digest.cron.log 2>&1
```

See `wrapper.sh` in this directory for a runnable shell wrapper that invokes a
`guard_run`-protected Python entry point.

## Tests

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

No third-party dependencies; stdlib only.
