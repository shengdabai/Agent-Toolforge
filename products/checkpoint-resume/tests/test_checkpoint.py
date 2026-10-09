"""TDD tests for the checkpoint-resume core helper.

Standard library only. Run with:
    python3 -m unittest discover -s tests -p 'test_*.py'
"""
import os
import sys
import json
import tempfile
import shutil
import unittest

# Make the package root importable regardless of cwd.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from checkpoint import Checkpoint  # noqa: E402


class CheckpointTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ckpt_test_")
        self.path = os.path.join(self.tmp, "progress.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _dir_entries(self):
        return sorted(os.listdir(self.tmp))


class TestSaveLoad(CheckpointTestBase):
    def test_save_then_load_roundtrips(self):
        ck = Checkpoint(self.path)
        ck.save(5, {"cursor": "abc", "count": 3})
        loaded = Checkpoint(self.path).load()
        self.assertEqual(loaded["index"], 5)
        self.assertEqual(loaded["state"], {"cursor": "abc", "count": 3})
        self.assertEqual(loaded["done"], [])

    def test_load_missing_returns_initial(self):
        ck = Checkpoint(self.path, initial_state={"seed": 1})
        loaded = ck.load()
        self.assertEqual(loaded["index"], 0)
        self.assertEqual(loaded["state"], {"seed": 1})
        self.assertEqual(loaded["done"], [])
        # load() must not have created the file as a side effect of reading.
        self.assertFalse(os.path.exists(self.path))

    def test_load_missing_default_state_is_empty_dict(self):
        loaded = Checkpoint(self.path).load()
        self.assertEqual(loaded["state"], {})

    def test_save_preserves_existing_done(self):
        ck = Checkpoint(self.path)
        ck.mark_done("item-1")
        ck.save(2, {"x": 1})
        loaded = Checkpoint(self.path).load()
        self.assertIn("item-1", loaded["done"])
        self.assertEqual(loaded["index"], 2)


class TestAtomicWrite(CheckpointTestBase):
    def test_atomic_no_leftover_temp_files(self):
        ck = Checkpoint(self.path)
        ck.save(1, {"a": 1})
        ck.save(2, {"a": 2})
        ck.mark_done("z")
        # Only the final main file should remain — no .tmp / partial files.
        entries = self._dir_entries()
        self.assertEqual(entries, ["progress.json"])

    def test_on_disk_is_valid_json_schema(self):
        ck = Checkpoint(self.path)
        ck.save(3, {"k": "v"})
        with open(self.path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        self.assertEqual(set(raw.keys()), {"index", "state", "done"})
        self.assertEqual(raw["index"], 3)

    def test_existing_file_not_corrupted_when_write_fails(self):
        # Simulate a failed write: a good file already exists, then a write
        # raises before os.replace. The original good file must survive intact.
        ck = Checkpoint(self.path)
        ck.save(7, {"good": True})

        original_replace = os.replace

        def boom(src, dst):
            # Drop the temp file like a crash, then fail before swapping in.
            try:
                os.remove(src)
            except OSError:
                pass
            raise OSError("simulated crash before replace")

        os.replace = boom
        try:
            with self.assertRaises(OSError):
                ck.save(99, {"good": False})
        finally:
            os.replace = original_replace

        # Old file must still be the valid index=7 snapshot.
        loaded = Checkpoint(self.path).load()
        self.assertEqual(loaded["index"], 7)
        self.assertEqual(loaded["state"], {"good": True})
        # No leftover temp file.
        self.assertEqual(self._dir_entries(), ["progress.json"])


class TestDoneTracking(CheckpointTestBase):
    def test_mark_and_is_done(self):
        ck = Checkpoint(self.path)
        self.assertFalse(ck.is_done("doc-42"))
        ck.mark_done("doc-42")
        self.assertTrue(ck.is_done("doc-42"))

    def test_mark_done_idempotent_no_duplicates(self):
        ck = Checkpoint(self.path)
        ck.mark_done("doc-1")
        ck.mark_done("doc-1")
        ck.mark_done("doc-1")
        loaded = ck.load()
        self.assertEqual(loaded["done"].count("doc-1"), 1)

    def test_is_done_survives_reload(self):
        Checkpoint(self.path).mark_done("persisted")
        self.assertTrue(Checkpoint(self.path).is_done("persisted"))


class TestResumeIndex(CheckpointTestBase):
    def test_resume_index_default_zero(self):
        self.assertEqual(Checkpoint(self.path).resume_index(), 0)

    def test_resume_index_returns_saved_index(self):
        ck = Checkpoint(self.path)
        ck.save(3, {})
        self.assertEqual(Checkpoint(self.path).resume_index(), 3)

    def test_resume_skips_completed_items(self):
        items = ["a", "b", "c", "d", "e"]
        ck = Checkpoint(self.path)
        # Process first 3, checkpointing after each.
        for i in range(3):
            ck.mark_done(items[i])
            ck.save(i + 1, {"last": items[i]})

        # Re-run from a fresh instance.
        resumed = Checkpoint(self.path)
        start = resumed.resume_index()
        self.assertEqual(start, 3)
        remaining = [it for it in items[start:] if not resumed.is_done(it)]
        self.assertEqual(remaining, ["d", "e"])


class TestCorruptionRecovery(CheckpointTestBase):
    def test_corrupt_file_degrades_to_initial(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{ this is not valid json ::::")
        ck = Checkpoint(self.path, initial_state={"fallback": True})
        loaded = ck.load()  # must not raise
        self.assertEqual(loaded["index"], 0)
        self.assertEqual(loaded["state"], {"fallback": True})
        self.assertEqual(loaded["done"], [])

    def test_corrupt_file_resume_index_is_zero(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("\x00\x00garbage")
        ck = Checkpoint(self.path)
        self.assertEqual(ck.resume_index(), 0)
        self.assertFalse(ck.is_done("anything"))

    def test_wrong_shape_json_degrades(self):
        # Valid JSON but not the expected object schema.
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump([1, 2, 3], fh)
        loaded = Checkpoint(self.path).load()
        self.assertEqual(loaded["index"], 0)
        self.assertEqual(loaded["done"], [])

    def test_save_after_corruption_recovers(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("garbage")
        ck = Checkpoint(self.path)
        ck.save(10, {"recovered": True})  # overwrites the corrupt file
        loaded = Checkpoint(self.path).load()
        self.assertEqual(loaded["index"], 10)
        self.assertEqual(loaded["state"], {"recovered": True})

    def test_corrupt_file_is_quarantined_not_destroyed(self):
        # Regression (b11): a truncated checkpoint used to be silently
        # replaced on the next write, destroying the previous progress.
        original = '{"index": 7, "done": ["a", "b", "c"], "state": {}'
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(original)
        Checkpoint(self.path).mark_done("z")
        self.assertEqual(Checkpoint(self.path).load()["done"], ["z"])
        with open(self.path + ".corrupt", "r", encoding="utf-8") as fh:
            self.assertEqual(fh.read(), original)
        # A second corruption must not clobber the first quarantine file.
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("again")
        Checkpoint(self.path).save(1, {})
        with open(self.path + ".corrupt", "r", encoding="utf-8") as fh:
            self.assertEqual(fh.read(), original)
        with open(self.path + ".corrupt.1", "r", encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "again")

    def test_healthy_file_is_never_quarantined(self):
        ck = Checkpoint(self.path)
        ck.save(1, {"a": 1})
        ck.mark_done("x")
        self.assertFalse(os.path.exists(self.path + ".corrupt"))

    def test_unhashable_done_entries_do_not_raise(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"index": 1, "state": {},
                       "done": [["x", 1], "a", ["x", 1], "a"]}, fh)
        ck = Checkpoint(self.path)
        self.assertEqual(ck.load()["done"], [["x", 1], "a"])
        ck.mark_done("b")  # write path must also survive
        self.assertEqual(ck.load()["done"], [["x", 1], "a", "b"])

    def test_negative_index_rejected_and_degraded(self):
        ck = Checkpoint(self.path)
        with self.assertRaises(ValueError):
            ck.save(-1, {})
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"index": -5, "state": {}, "done": []}, fh)
        self.assertEqual(ck.resume_index(), 0)


if __name__ == "__main__":
    unittest.main()
