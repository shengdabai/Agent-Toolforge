"""Runnable demo: a 5-step job that crashes at step 3, then resumes.

Run it twice (the script does both runs for you):

    python3 demo.py

Run 1 processes steps 0,1,2 then raises a simulated crash before finishing
step 2's checkpoint of step 3. Run 2 builds a fresh Checkpoint from the same
file and continues from where it left off — it does NOT redo steps 0-2.
"""
import os
import tempfile

from checkpoint import Checkpoint

ITEMS = ["alpha", "beta", "gamma", "delta", "epsilon"]


class SimulatedCrash(Exception):
    pass


def run_job(path, crash_at=None):
    ck = Checkpoint(path)
    start = ck.resume_index()
    print(f"  resume_index() -> {start}")
    processed = []
    for i in range(start, len(ITEMS)):
        item = ITEMS[i]
        if ck.is_done(item):
            print(f"  [skip] step {i} ({item}) already done")
            continue

        # --- the real work would happen here ---
        print(f"  [work] step {i} -> processing {item!r}")
        processed.append(item)

        if crash_at is not None and i == crash_at:
            # Crash AFTER the work but BEFORE checkpointing this step.
            raise SimulatedCrash(f"boom at step {i} ({item})")

        # Checkpoint AFTER the side effect succeeds.
        ck.mark_done(item)
        ck.save(i + 1, {"last": item})
    return processed


def main():
    tmp = tempfile.mkdtemp(prefix="ckpt_demo_")
    path = os.path.join(tmp, "progress.json")
    try:
        print("=== RUN 1 (will crash at step 2 before checkpointing step) ===")
        # Steps 0,1 checkpoint fine; step 2 crashes before its checkpoint.
        try:
            run_job(path, crash_at=2)
        except SimulatedCrash as exc:
            print(f"  CRASH: {exc}")

        saved = Checkpoint(path).load()
        print(f"  on-disk after crash: index={saved['index']} done={saved['done']}")

        print("\n=== RUN 2 (resume from checkpoint) ===")
        done_second = run_job(path)
        print(f"\nRun 2 processed: {done_second}")

        final = Checkpoint(path).load()
        print(f"final: index={final['index']} done={final['done']}")

        assert final["index"] == len(ITEMS), "job did not complete"
        assert set(final["done"]) == set(ITEMS), "not all items done"
        # Run 2 must have resumed at index 2 (gamma), not redone alpha/beta.
        assert done_second[0] == "gamma", "did not resume at the right step"
        assert "alpha" not in done_second and "beta" not in done_second
        print("\nOK — resumed from step 2, no rework of steps 0-1.")
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
