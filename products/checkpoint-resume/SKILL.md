---
name: checkpoint-resume
description: Crash-survivable checkpointing for long, ordered batch jobs. Use when a long task / batch process / pipeline crashed partway through (e.g. document 201 of 500 failed) and you must resume from the next unfinished item instead of restarting from zero. Trigger on "断点续跑", "resume", "长任务", "批处理", "batch", "checkpoint", "crashed midway", "pick up where it left off". Provides a stdlib-only Checkpoint helper that atomically persists progress (index + state + done set) so re-runs skip completed work.
---

# checkpoint-resume

Make any long, ordered batch job survive crashes. Persist progress to a single
JSON file written atomically, so a re-run continues from the next unfinished
item instead of redoing everything.

## When to use

- A loop over many items (documents, URLs, rows, files, API calls) that may
  crash, hit a usage limit, or get killed partway through.
- You are burning tokens / API quota / wall time by restarting from item #1.
- You want "process item -> checkpoint -> repeat" with safe resume semantics.

## Core helper: `checkpoint.py`

```python
from checkpoint import Checkpoint

ck = Checkpoint("progress.json", initial_state={"phase": "ingest"})

ck.save(index, state)   # atomic write: {index, state, done}, preserves done
                        # index: int >= 0 (TypeError/ValueError otherwise); state: dict
ck.load()               # -> {"index", "state", "done"}; safe on missing/corrupt
ck.mark_done(item_id)   # add to done set (idempotent), persist atomically
ck.is_done(item_id)     # bool
ck.resume_index()       # next index to process (items below it are complete)
```

Stdlib only. Atomic write = temp file in the same dir + `os.replace`, so a crash
mid-write never leaves a half-written main file. Missing or corrupt files
degrade gracefully to the initial snapshot (never raise). Before the next write
replaces a corrupt file, it is renamed to `<path>.corrupt` (`.corrupt.N` if
taken) so the old progress is not destroyed — check for it after a crash.
Single writer only (no cross-process lock); `.corrupt.N` files are not cleaned
up automatically.

## Protocol 1 — checkpoint-every-N

For very long jobs, checkpoint every N items instead of every item to cut I/O,
while bounding worst-case rework to N items.

```python
ck = Checkpoint("progress.json")
start = ck.resume_index()
N = 25
for i in range(start, len(items)):
    process(items[i])
    if (i + 1) % N == 0 or i + 1 == len(items):
        ck.save(i + 1, {"last": items[i].id})
```

After a crash, at most the last `< N` items are reprocessed. Make `process()`
idempotent (or guard with `is_done`) so reprocessing is harmless.

## Protocol 2 — per-item done set (exact resume)

When each item has a stable id and reprocessing is expensive or unsafe, mark
each one done and skip on resume — exact, no rework:

```python
ck = Checkpoint("progress.json")
for i in range(ck.resume_index(), len(items)):
    item = items[i]
    if ck.is_done(item.id):
        continue
    process(item)
    ck.mark_done(item.id)
    ck.save(i + 1, {})
```

## Crash-then-resume protocol

1. On start, ALWAYS build the checkpoint from the same `path` and call
   `resume_index()` — do not assume index 0.
2. Skip any `is_done(id)` items even at/after the resume index (covers items
   completed but not yet reflected in `index`).
3. Checkpoint AFTER the side effect succeeds, never before — otherwise you may
   mark work done that never happened.
4. Keep `state` small and JSON-serializable (cursors, counts, last id), not the
   payloads themselves.

## Files

- `checkpoint.py` — the helper (import this).
- `tests/test_checkpoint.py` — unittest suite (`python3 -m unittest`).
- `demo.py` — runnable 5-step demo that crashes partway and resumes from the next unfinished step.
