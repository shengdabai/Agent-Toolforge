#!/usr/bin/env bash
#
# cron-guard wrapper template.
#
# Use this as the program your scheduler (cron / launchd) invokes. It runs an
# inline Python entry point that protects the real job with guard_run, so
# overlap, budget, and audit are enforced no matter how the scheduler behaves.
#
# Customize:
#   JOB_NAME, the work() body, and the four paths below.
#
# launchd: point ProgramArguments at this script.
# cron:    0 * * * * /path/to/wrapper.sh >> /tmp/job.cron.log 2>&1

set -euo pipefail

# --- configuration ---------------------------------------------------------
JOB_NAME="example-job"
# Directory containing cronguard.py (defaults to this script's own directory).
GUARD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

STATE_DIR="${CRONGUARD_STATE_DIR:-${TMPDIR:-/tmp}}"
LOCK_PATH="${STATE_DIR%/}/${JOB_NAME}.lock"
BUDGET_STATE="${STATE_DIR%/}/${JOB_NAME}.budget.json"
AUDIT_PATH="${STATE_DIR%/}/${JOB_NAME}.audit.jsonl"
BUDGET_CAP="${CRONGUARD_CAP:-100}"
RUN_COST="${CRONGUARD_COST:-1}"

PYTHON_BIN="${PYTHON_BIN:-python3}"

# --- run -------------------------------------------------------------------
PYTHONPATH="${GUARD_DIR}:${PYTHONPATH:-}" "${PYTHON_BIN}" - "$JOB_NAME" \
  "$LOCK_PATH" "$BUDGET_STATE" "$AUDIT_PATH" "$BUDGET_CAP" "$RUN_COST" <<'PYEOF'
import sys
from cronguard import guard_run, GuardAborted

name, lock_path, budget_state, audit_path, cap, cost = sys.argv[1:7]
cap = float(cap)
cost = float(cost)


def work():
    # ---------------------------------------------------------------------
    # Replace this body with the real job. Anything returned here is recorded
    # in the audit log's "total" context and returned by guard_run.
    # ---------------------------------------------------------------------
    print("[{}] doing work".format(name))
    return "ok"


result = guard_run(
    name=name,
    work_fn=work,
    lock_path=lock_path,
    budget_state=budget_state,
    cap=cap,
    cost=cost,
    audit_path=audit_path,
)

if result is GuardAborted.LOCK_HELD:
    print("[{}] another run in progress; skipped".format(name))
    sys.exit(0)
if result is GuardAborted.BUDGET_EXCEEDED:
    print("[{}] budget cap {} reached; skipped".format(name, cap))
    sys.exit(0)

print("[{}] completed: {}".format(name, result))
PYEOF
