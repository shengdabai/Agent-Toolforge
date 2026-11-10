"""Test suite for cronguard (stdlib unittest only)."""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

# Make the package root importable when run via `python3 -m unittest discover -s tests`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cronguard import (  # noqa: E402
    BudgetExceeded,
    BudgetGuard,
    GuardAborted,
    LockHeld,
    acquire_lock,
    audit_log,
    guard_run,
    read_audit_log,
    release_lock,
)


class SecureStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / 'budget.json'
        self.budget = BudgetGuard(str(self.state), cap=10)

    def test_predictable_temp_symlink_cannot_overwrite_target(self):
        target = self.root / 'other.txt'
        target.write_text('keep')
        trap = Path('{}.{}.tmp'.format(self.state, os.getpid()))
        trap.symlink_to(target)
        self.assertTrue(self.budget.spend(1))
        self.assertEqual(target.read_text(), 'keep')
        self.assertTrue(trap.is_symlink())

    def test_budget_is_private_even_with_permissive_umask(self):
        old = os.umask(0)
        try:
            self.budget.spend(1)
        finally:
            os.umask(old)
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o600)

    def test_failed_store_preserves_budget_and_removes_temp(self):
        self.budget.spend(2)
        for operation in ('json.dump', 'os.fsync', 'os.replace'):
            before = set(self.root.iterdir())
            with self.subTest(operation=operation):
                with mock.patch('cronguard.' + operation, side_effect=OSError('failed')):
                    with self.assertRaises(OSError):
                        self.budget.spend(1)
                self.assertEqual(self.budget.total(), 2)
                self.assertEqual(set(self.root.iterdir()), before)

    def test_fsync_happens_before_replace(self):
        with mock.patch('cronguard.os.fsync', wraps=os.fsync) as sync:
            replace = os.replace
            def checked_replace(src, dst):
                sync.assert_called_once()
                self.assertEqual(json.loads(Path(src).read_text()), {'total': 1})
                replace(src, dst)
            with mock.patch('cronguard.os.replace', side_effect=checked_replace):
                self.budget.spend(1)

    def test_append_targets_reject_symlinks_and_fifos(self):
        target = self.root / 'other.txt'
        target.write_text('keep')
        for name in ('audit.jsonl', 'job.lock.mutex', 'budget.json.mutex'):
            path = self.root / name
            for kind in ('symlink', 'fifo'):
                with self.subTest(name=name, kind=kind):
                    if kind == 'symlink':
                        path.symlink_to(target)
                    else:
                        os.mkfifo(path)
                    try:
                        # A subprocess bounds the test if opening a FIFO blocks.
                        code = ("from cronguard import *; " +
                                ("audit_log(%r, {})" % str(path) if name == 'audit.jsonl'
                                 else "acquire_lock(%r)" % str(self.root / 'job.lock')
                                 if name == 'job.lock.mutex'
                                 else "BudgetGuard(%r, 10).spend(1)" % str(self.state)))
                        proc = subprocess.run([sys.executable, '-B', '-c', code],
                                              cwd=Path(__file__).resolve().parents[1],
                                              capture_output=True, text=True, timeout=3)
                        self.assertNotEqual(proc.returncode, 0)
                        self.assertIn('OSError', proc.stderr)
                        self.assertEqual(target.read_text(), 'keep')
                    finally:
                        path.unlink()

    def test_new_lock_mutex_and_audit_are_private(self):
        lock = str(self.root / 'job.lock')
        log = str(self.root / 'audit.jsonl')
        old = os.umask(0)
        try:
            token = acquire_lock(lock)
            audit_log(log, {})
        finally:
            os.umask(old)
        for path in (lock, lock + '.mutex', log):
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertTrue(release_lock(lock, token))

    def _wrapper(self, state_dir=None):
        env = dict(os.environ, HOME=str(self.root), TMPDIR=str(self.root) + '/',
                   PYTHON_BIN=sys.executable, PYTHONDONTWRITEBYTECODE='1',
                   CRONGUARD_CAP='2', CRONGUARD_COST='1')
        env.pop('CRONGUARD_STATE_DIR', None)
        if state_dir is not None:
            env['CRONGUARD_STATE_DIR'] = str(state_dir)
        return subprocess.run(['bash', str(Path(__file__).resolve().parents[1] / 'wrapper.sh')],
                              env=env, capture_output=True, text=True, timeout=5)

    def test_wrapper_default_is_private_persistent_and_enforces_budget(self):
        for _ in range(3):
            proc = self._wrapper()
            self.assertEqual(proc.returncode, 0, proc.stderr)
        state = self.root / '.local/state/cron-guard'
        self.assertEqual(stat.S_IMODE(state.stat().st_mode), 0o700)
        self.assertEqual(json.loads((state / 'example-job.budget.json').read_text()),
                         {'total': 2})
        self.assertIn('budget cap', proc.stdout)

    def test_wrapper_honors_override_and_rejects_unsafe_directory(self):
        custom = self.root / 'custom'
        self.assertEqual(self._wrapper(custom).returncode, 0)
        self.assertTrue((custom / 'example-job.budget.json').exists())
        custom.chmod(0o777)
        self.assertNotEqual(self._wrapper(custom).returncode, 0)
        custom.chmod(0o700)
        link = self.root / 'linked'
        link.symlink_to(custom, target_is_directory=True)
        self.assertNotEqual(self._wrapper(link).returncode, 0)


class AcquireLockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lock_path = os.path.join(self.tmp.name, "job.lock")

    def tearDown(self):
        self.tmp.cleanup()

    def test_acquire_creates_lock_with_pid(self):
        token = acquire_lock(self.lock_path)
        self.assertIsNotNone(token)
        self.assertTrue(os.path.exists(self.lock_path))
        with open(self.lock_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["pid"], os.getpid())

    def test_second_acquire_fails_while_held(self):
        first = acquire_lock(self.lock_path)
        self.assertIsNotNone(first)
        second = acquire_lock(self.lock_path)
        self.assertIsNone(second)

    def test_release_allows_reacquire(self):
        token = acquire_lock(self.lock_path)
        self.assertIsNotNone(token)
        release_lock(self.lock_path, token)
        self.assertFalse(os.path.exists(self.lock_path))
        again = acquire_lock(self.lock_path)
        self.assertIsNotNone(again)

    def test_stale_lock_from_dead_pid_is_reclaimed(self):
        # Write a lock file owned by a guaranteed-dead pid.
        dead_pid = 999999999
        with open(self.lock_path, "w", encoding="utf-8") as f:
            json.dump({"pid": dead_pid, "ts": 0, "host": "x"}, f)
        token = acquire_lock(self.lock_path)
        self.assertIsNotNone(token)
        with open(self.lock_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["pid"], os.getpid())

    def test_release_with_wrong_token_does_not_remove(self):
        token = acquire_lock(self.lock_path)
        released = release_lock(self.lock_path, "not-the-token")
        self.assertFalse(released)
        self.assertTrue(os.path.exists(self.lock_path))
        # Correct token still works.
        self.assertTrue(release_lock(self.lock_path, token))


class BudgetGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_path = os.path.join(self.tmp.name, "budget.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_spend_accumulates(self):
        guard = BudgetGuard(self.state_path, cap=10)
        self.assertTrue(guard.spend(3))
        self.assertTrue(guard.spend(4))
        self.assertEqual(guard.total(), 7)

    def test_spend_over_cap_returns_false(self):
        guard = BudgetGuard(self.state_path, cap=5)
        self.assertTrue(guard.spend(5))
        self.assertFalse(guard.spend(1))
        # Rejected spend is not persisted.
        self.assertEqual(guard.total(), 5)

    def test_spend_over_cap_can_raise(self):
        guard = BudgetGuard(self.state_path, cap=5)
        guard.spend(5)
        with self.assertRaises(BudgetExceeded):
            guard.spend(1, raise_on_exceed=True)

    def test_state_persists_across_instances(self):
        g1 = BudgetGuard(self.state_path, cap=100)
        g1.spend(40)
        g2 = BudgetGuard(self.state_path, cap=100)
        self.assertEqual(g2.total(), 40)
        self.assertTrue(g2.spend(10))
        self.assertEqual(g2.total(), 50)

    def test_negative_spend_rejected(self):
        guard = BudgetGuard(self.state_path, cap=10)
        with self.assertRaises(ValueError):
            guard.spend(-1)

    def test_reset_clears_total(self):
        guard = BudgetGuard(self.state_path, cap=10)
        guard.spend(5)
        guard.reset()
        self.assertEqual(guard.total(), 0)


class AuditLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log_path = os.path.join(self.tmp.name, "audit.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def test_append_and_read_back(self):
        audit_log(self.log_path, {"name": "job-a", "status": "ok"})
        audit_log(self.log_path, {"name": "job-b", "status": "skipped"})
        records = read_audit_log(self.log_path)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["name"], "job-a")
        self.assertEqual(records[1]["status"], "skipped")
        # ts is injected automatically.
        self.assertIn("ts", records[0])

    def test_each_record_is_valid_json_line(self):
        audit_log(self.log_path, {"name": "x", "status": "ok"})
        with open(self.log_path, "r", encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        self.assertEqual(len(lines), 1)
        json.loads(lines[0])  # must not raise

    def test_explicit_ts_is_preserved(self):
        audit_log(self.log_path, {"name": "x", "status": "ok", "ts": 12345})
        records = read_audit_log(self.log_path)
        self.assertEqual(records[0]["ts"], 12345)


class GuardRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lock_path = os.path.join(self.tmp.name, "job.lock")
        self.budget_state = os.path.join(self.tmp.name, "budget.json")
        self.audit_path = os.path.join(self.tmp.name, "audit.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def test_successful_run_returns_result_and_logs_ok(self):
        result = guard_run(
            name="daily",
            work_fn=lambda: 42,
            lock_path=self.lock_path,
            budget_state=self.budget_state,
            cap=10,
            cost=1,
            audit_path=self.audit_path,
        )
        self.assertEqual(result, 42)
        records = read_audit_log(self.audit_path)
        statuses = [r["status"] for r in records]
        self.assertIn("ok", statuses)
        # Lock released after run.
        self.assertFalse(os.path.exists(self.lock_path))

    def test_concurrent_run_is_rejected_while_lock_held(self):
        observed = {}

        def slow_work():
            # While inside work_fn the lock is held; a nested guard_run must be skipped.
            inner = guard_run(
                name="daily",
                work_fn=lambda: "should-not-run",
                lock_path=self.lock_path,
                budget_state=self.budget_state,
                cap=10,
                cost=1,
                audit_path=self.audit_path,
            )
            observed["inner"] = inner
            return "outer-done"

        outer = guard_run(
            name="daily",
            work_fn=slow_work,
            lock_path=self.lock_path,
            budget_state=self.budget_state,
            cap=10,
            cost=1,
            audit_path=self.audit_path,
        )
        self.assertEqual(outer, "outer-done")
        # Nested call could not acquire the lock -> returns the skipped sentinel.
        self.assertIs(observed["inner"], GuardAborted.LOCK_HELD)
        records = read_audit_log(self.audit_path)
        statuses = [r["status"] for r in records]
        self.assertIn("skipped_locked", statuses)

    def test_budget_exceeded_aborts_before_work(self):
        ran = {"called": False}

        def work():
            ran["called"] = True
            return "done"

        # Pre-spend the entire cap.
        BudgetGuard(self.budget_state, cap=5).spend(5)
        result = guard_run(
            name="costly",
            work_fn=work,
            lock_path=self.lock_path,
            budget_state=self.budget_state,
            cap=5,
            cost=1,
            audit_path=self.audit_path,
        )
        self.assertIs(result, GuardAborted.BUDGET_EXCEEDED)
        self.assertFalse(ran["called"])
        records = read_audit_log(self.audit_path)
        statuses = [r["status"] for r in records]
        self.assertIn("skipped_budget", statuses)
        # Lock must be released even on budget abort.
        self.assertFalse(os.path.exists(self.lock_path))

    def test_work_exception_logs_error_and_releases_lock(self):
        def boom():
            raise RuntimeError("kaboom")

        with self.assertRaises(RuntimeError):
            guard_run(
                name="explode",
                work_fn=boom,
                lock_path=self.lock_path,
                budget_state=self.budget_state,
                cap=10,
                cost=1,
                audit_path=self.audit_path,
            )
        records = read_audit_log(self.audit_path)
        statuses = [r["status"] for r in records]
        self.assertIn("error", statuses)
        self.assertFalse(os.path.exists(self.lock_path))

    def test_lock_held_exception_type_exists(self):
        # Sanity: exported symbols are usable.
        self.assertTrue(issubclass(LockHeld, Exception))




class BoundaryRegressionTests(unittest.TestCase):
    def test_corrupt_budget_and_nonfinite_spend_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'budget.json')
            for contents in ['{broken', '[]', '{"total":-1}', '{"total":NaN}']:
                with open(path, 'w') as file: file.write(contents)
                with self.assertRaises(ValueError): BudgetGuard(path, 10).spend(1)
                with open(path) as file: self.assertEqual(file.read(), contents)
            os.unlink(path)
            with self.assertRaises(ValueError): BudgetGuard(path, 10).spend(float('nan'))

    def test_partial_lock_write_never_grants_two_owners(self):
        import cronguard
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'job.lock')
            started, release = threading.Event(), threading.Event()
            original = cronguard._write_lock_payload
            def delayed(fd, token):
                started.set()
                self.assertTrue(release.wait(3))
                original(fd, token)
            with ThreadPoolExecutor(2) as pool, patch.object(cronguard, '_write_lock_payload', delayed):
                first = pool.submit(acquire_lock, path)
                try:
                    self.assertTrue(started.wait(2))
                    second = pool.submit(acquire_lock, path)
                finally: release.set()
                token = first.result(timeout=3)
                self.assertIsNotNone(token)
                self.assertIsNone(second.result(timeout=3))
            self.assertTrue(release_lock(path, token))

    def test_shared_budget_serializes_separate_processes(self):
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'budget.json')
            source = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            code = 'import sys;sys.path.insert(0,sys.argv[1]);from cronguard import BudgetGuard;g=BudgetGuard(sys.argv[2],10);print(sum(g.spend(1) for _ in range(20)))'
            processes = [subprocess.Popen([sys.executable,'-B','-c',code,source,path],stdout=subprocess.PIPE,text=True) for _ in range(3)]
            totals=[]
            for process in processes:
                stdout,_=process.communicate(timeout=10);self.assertEqual(process.returncode,0);totals.append(int(stdout.strip()))
            self.assertEqual(sum(totals),10)
            self.assertEqual(BudgetGuard(path,10).total(),10)

    def test_crashed_partial_lock_can_recover_under_mutex(self):
        with tempfile.TemporaryDirectory() as directory:
            path=os.path.join(directory,'job.lock')
            with open(path,'w') as file:file.write('{partial')
            token=acquire_lock(path)
            self.assertIsNotNone(token)
            self.assertTrue(release_lock(path,token))

    def test_budget_overflow_does_not_corrupt_state(self):
        with tempfile.TemporaryDirectory() as directory:
            guard=BudgetGuard(os.path.join(directory,'budget.json'),None)
            self.assertTrue(guard.spend(1e308))
            with self.assertRaises(ValueError):guard.spend(1e308)
            self.assertEqual(guard.total(),1e308)

if __name__ == "__main__":
    unittest.main()
