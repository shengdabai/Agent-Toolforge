# SPEC — checkpoint-resume

## Problem (requirements fill-in-the-blank)

- WHO: An AI agent (or any long-running batch script) that processes a large
  ordered list of work items (documents, URLs, rows, files).
- PAIN: When item #201 of 500 crashes, the whole job restarts from #1. All prior
  work is lost or redundantly redone, burning tokens / API calls / wall time.
- WANT: A crash-survivable checkpoint file that records progress atomically so a
  re-run continues from the next unfinished item instead of from zero.
- NON-GOALS: Distributed locking, multi-writer concurrency, networked storage.
  Single-process, single-writer, local-disk only.

## Core contract — `checkpoint.Checkpoint`

```
Checkpoint(path: str, initial_state: dict | None = None)
```

A checkpoint persisted as a single JSON file at `path`. On-disk schema:

```json
{ "index": <int>, "state": <dict>, "done": [<item_id>, ...] }
```

### Methods

| Method | Behavior |
|--------|----------|
| `save(index: int, state: dict) -> None` | Atomically persist `index` + `state`, preserving the current `done` list. Atomic = write temp file in same dir, `os.replace` into place. A crash mid-write must NEVER leave a half-written / corrupt main file. |
| `load() -> dict` | Read the file back, returning `{"index", "state", "done"}`. If the file is missing, return the initial snapshot (`index=0`, `state=initial_state`, `done=[]`). If the file is corrupt/unreadable, degrade gracefully to the initial snapshot (never raise). |
| `mark_done(item_id) -> None` | Add `item_id` to the `done` set (idempotent — no duplicates) and persist atomically. |
| `is_done(item_id) -> bool` | True iff `item_id` has been marked done. |
| `resume_index() -> int` | Return the next index to process: the persisted `index`. After `save(i, ...)` is interpreted as "items `< i` are complete", so resume starts at `i`. |

### Invariants

1. Atomic writes: no partial main file is ever observable. Temp files are cleaned up.
2. `done` membership is order-independent and deduplicated.
3. `load()` and all readers never raise on a missing or corrupt file.
4. Pure standard library. No network, no third-party packages.

## Acceptance tests (see `tests/`)

- save → load round-trips `index` and `state` exactly.
- Atomic write leaves no leftover temp/half files in the directory.
- `mark_done` / `is_done` work and are idempotent.
- `resume_index` returns the saved index; skips already-completed items.
- A corrupted checkpoint file degrades to the initial snapshot instead of raising.
- Before a write replaces a corrupt/unreadable checkpoint, the old file is renamed to `<path>.corrupt` (then `.corrupt.1`, ...) so prior progress stays recoverable; healthy files are never quarantined.
- `save` rejects a negative `index` with `ValueError`; a negative stored index loads as 0. `done` entries may be unhashable JSON values (lists/dicts).
