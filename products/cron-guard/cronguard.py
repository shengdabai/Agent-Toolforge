"""cronguard — defensive scheduling primitives for AI agent cron/launchd jobs.

Pure stdlib. Three concerns, composable:

1. Locking      — atomic O_CREAT|O_EXCL lock files with liveness-aware
                  stale-lock reclaim, to prevent overlapping runs.
2. Budget       — a persistent spend counter with a hard cap, to prevent
                  runaway cost from a misbehaving loop.
3. Audit        — append-only JSONL log of every guarded run, for after-the
                  -fact accountability.

`guard_run` wires all three into a single safe entry point:

    acquire lock -> budget check -> run work_fn -> audit -> release lock

No network, no third-party packages, no global state.
"""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import math
import enum
import errno
import json
import os
import socket
import time
import uuid

__all__ = [
    "BudgetExceeded",
    "BudgetGuard",
    "GuardAborted",
    "LockHeld",
    "acquire_lock",
    "audit_log",
    "guard_run",
    "read_audit_log",
    "release_lock",
]


# --------------------------------------------------------------------------- #
# Errors / sentinels
# --------------------------------------------------------------------------- #
class LockHeld(Exception):
    """Raised when a lock is held by a live process and reclaim is not allowed."""


class BudgetExceeded(Exception):
    """Raised by BudgetGuard.spend when raise_on_exceed=True and cap is hit."""


class GuardAborted(enum.Enum):
    """Sentinel return values from guard_run when work_fn never ran."""

    LOCK_HELD = "lock_held"
    BUDGET_EXCEEDED = "budget_exceeded"


# --------------------------------------------------------------------------- #
# Liveness
# --------------------------------------------------------------------------- #
def _pid_alive(pid: int) -> bool:
    """Best-effort check whether a pid is a live process on this host."""
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError as exc:
        if exc.errno == errno.ESRCH:  # No such process.
            return False
        if exc.errno == errno.EPERM:  # Exists but not ours -> alive.
            return True
        return False
    return True


# --------------------------------------------------------------------------- #
# Locking
# --------------------------------------------------------------------------- #
def _write_lock_payload(fd: int, token: str) -> None:
    payload = {
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "token": token,
        "ts": time.time(),
    }
    os.write(fd, json.dumps(payload).encode("utf-8"))


def _read_lock_payload(lock_path: str):
    try:
        with open(lock_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


@contextmanager
def _state_mutex(path):
    """POSIX advisory mutex. Keep this inode; unlinking it breaks coordination."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def acquire_lock(lock_path: str):
    with _state_mutex(lock_path + ".mutex"):
        return _acquire_lock_unlocked(lock_path)


def _acquire_lock_unlocked(lock_path: str):
    """Atomically acquire a lock file.

    Returns an opaque token string on success, or None if another live
    process already holds the lock. A known dead pid is reclaimed.
    Corrupt metadata is reclaimed under the mutex after a crashed writer.
    Coordination uses POSIX flock (macOS/Linux).

    The token must be passed back to release_lock to release the lock.
    """
    token = uuid.uuid4().hex
    parent = os.path.dirname(lock_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    for _attempt in range(2):
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            payload = _read_lock_payload(lock_path)
            holder_pid = payload.get("pid") if isinstance(payload, dict) else None
            if not isinstance(payload, dict) or not isinstance(holder_pid, int) or holder_pid <= 0 or not _pid_alive(holder_pid):
                # Known stale lock -> reclaim under the sidecar mutex.
                try:
                    os.unlink(lock_path)
                except FileNotFoundError:
                    pass  # Someone else cleaned it; retry will create fresh.
                continue
            # Held by a live process.
            return None
        else:
            try:
                _write_lock_payload(fd, token)
            finally:
                os.close(fd)
            return token
    return None


def release_lock(lock_path: str, token: str) -> bool:
    with _state_mutex(lock_path + ".mutex"):
        return _release_lock_unlocked(lock_path, token)


def _release_lock_unlocked(lock_path: str, token: str) -> bool:
    """Release a lock previously acquired with acquire_lock.

    Only removes the lock file when its stored token matches `token`, so a
    process cannot accidentally release a lock it does not own. Returns True
    if the lock was removed, False otherwise.
    """
    payload = _read_lock_payload(lock_path)
    if not isinstance(payload, dict):
        return False
    if payload.get("token") != token:
        return False
    try:
        os.unlink(lock_path)
    except FileNotFoundError:
        return False
    return True


# --------------------------------------------------------------------------- #
# Budget
# --------------------------------------------------------------------------- #
class BudgetGuard:
    """A persistent, capped spend counter.

    State is stored as JSON at state_path so the running total survives across
    process restarts (exactly the launchd/cron use case). spend(n) returns
    False when n would push the total past the cap and does not persist the
    rejected charge, so the guard fails closed.
    """

    def __init__(self, state_path: str, cap):
        if cap is not None and (not math.isfinite(cap) or cap < 0):
            raise ValueError("cap must be non-negative")
        self.state_path = state_path
        self.cap = cap
        parent = os.path.dirname(state_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    def _load(self) -> float:
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            total = data.get("total") if isinstance(data, dict) else None
            if isinstance(total, bool) or not isinstance(total, (int, float)) or not math.isfinite(total) or total < 0:
                raise ValueError("Invalid persisted budget total")
            return float(total)
        except FileNotFoundError:
            return 0.0
        except (OSError, ValueError) as error:
            raise ValueError("Budget state unreadable or corrupt; refusing to reset spending") from error

    def _store(self, total: float) -> None:
        tmp = "{}.{}.tmp".format(self.state_path, os.getpid())
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"total": total}, f)
        os.replace(tmp, self.state_path)

    def total(self) -> float:
        return self._load()

    def spend(self, n, raise_on_exceed: bool = False) -> bool:
        with _state_mutex(self.state_path + ".mutex"):
            return self._spend_unlocked(n, raise_on_exceed)

    def _spend_unlocked(self, n, raise_on_exceed: bool = False) -> bool:
        """Charge n against the budget.

        Returns True when the charge fits under the cap (and persists it),
        False when it would exceed the cap (rejected, not persisted). When
        raise_on_exceed is True, raises BudgetExceeded instead of returning
        False.
        """
        if not math.isfinite(n) or n < 0:
            raise ValueError("spend amount must be non-negative")
        current = self._load()
        proposed = current + n
        if not math.isfinite(proposed):
            raise ValueError("Budget total overflow")
        if self.cap is not None and proposed > self.cap:
            if raise_on_exceed:
                raise BudgetExceeded(
                    "spend of {} would exceed cap {} (current {})".format(
                        n, self.cap, current
                    )
                )
            return False
        self._store(proposed)
        return True

    def reset(self) -> None:
        with _state_mutex(self.state_path + ".mutex"):
            self._store(0.0)


# --------------------------------------------------------------------------- #
# Audit
# --------------------------------------------------------------------------- #
def audit_log(log_path: str, record: dict) -> dict:
    """Append a single JSON record as one line to the audit JSONL log.

    A `ts` (epoch seconds) field is injected automatically when the record
    does not already carry one. Returns the record actually written.
    """
    parent = os.path.dirname(log_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    entry = dict(record)
    entry.setdefault("ts", time.time())
    line = json.dumps(entry, ensure_ascii=False)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    return entry


def read_audit_log(log_path: str) -> list:
    """Read an audit JSONL log back into a list of dict records."""
    records = []
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                records.append(json.loads(line))
    except FileNotFoundError:
        return []
    return records


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def guard_run(
    name,
    work_fn,
    lock_path,
    budget_state,
    cap,
    cost=1,
    audit_path=None,
):
    """Run work_fn under lock + budget + audit protection.

    Sequence:
        1. acquire_lock        — if held by a live process, skip (no overlap).
        2. budget check        — if cost would exceed cap, skip (no runaway).
        3. work_fn()           — the actual job.
        4. audit               — record outcome (ok / error / skipped_*).
        5. release_lock        — always, even on exception.

    Returns work_fn's return value on success, or a GuardAborted sentinel
    (LOCK_HELD / BUDGET_EXCEEDED) when the job was skipped. Re-raises any
    exception thrown by work_fn after auditing it as "error" and releasing
    the lock.
    """
    token = acquire_lock(lock_path)
    if token is None:
        if audit_path:
            audit_log(audit_path, {"name": name, "status": "skipped_locked"})
        return GuardAborted.LOCK_HELD

    try:
        guard = BudgetGuard(budget_state, cap=cap)
        if not guard.spend(cost):
            if audit_path:
                audit_log(
                    audit_path,
                    {
                        "name": name,
                        "status": "skipped_budget",
                        "cost": cost,
                        "total": guard.total(),
                        "cap": cap,
                    },
                )
            return GuardAborted.BUDGET_EXCEEDED

        try:
            result = work_fn()
        except Exception as exc:  # noqa: BLE001 — audit then re-raise.
            if audit_path:
                audit_log(
                    audit_path,
                    {
                        "name": name,
                        "status": "error",
                        "error": "{}: {}".format(type(exc).__name__, exc),
                    },
                )
            raise

        if audit_path:
            audit_log(
                audit_path,
                {"name": name, "status": "ok", "cost": cost, "total": guard.total()},
            )
        return result
    finally:
        release_lock(lock_path, token)
