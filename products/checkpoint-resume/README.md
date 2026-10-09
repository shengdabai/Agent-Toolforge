# checkpoint-resume

Crash-survivable checkpointing for long, ordered batch jobs. When item #201 of
500 crashes, resume from the next unfinished item instead of restarting from #1.

A single JSON file tracks `{index, state, done}`. Writes are atomic (temp file +
`os.replace`), so a crash mid-write never corrupts saved progress. Missing or
corrupt files degrade gracefully to the initial snapshot — readers never raise.
A corrupt file is **not** silently overwritten: the next write renames it to
`<path>.corrupt` first (see "Corrupt files" below).

## Why

Long agent / batch jobs (process N documents, crawl N URLs, transform N rows)
fail partway through. Restarting from zero wastes tokens, API quota, and time.
This helper makes "process item -> checkpoint -> repeat" safely resumable.

## Install

No installation. Pure Python standard library (Python 3.7+). Copy `checkpoint.py`
next to your code, or import it from this directory:

```python
from checkpoint import Checkpoint
```

There is also a `SKILL.md` so this can be loaded as an agent skill.

## Usage

```python
from checkpoint import Checkpoint

ck = Checkpoint("progress.json", initial_state={"phase": "ingest"})

items = load_work_items()                  # your ordered list
for i in range(ck.resume_index(), len(items)):
    item = items[i]
    if ck.is_done(item.id):                # already finished in a prior run
        continue
    process(item)                          # the real work / side effect
    ck.mark_done(item.id)                  # record completion (idempotent)
    ck.save(i + 1, {"last_id": item.id})   # atomic checkpoint
```

Re-running the same script after a crash continues from `resume_index()` and
skips anything already in the `done` set.

### API

| Method | Description |
|--------|-------------|
| `Checkpoint(path, initial_state=None)` | Open/declare a checkpoint at `path`. |
| `save(index, state)` | Atomically persist `index` + `state`, keeping `done`. `index` must be an int >= 0 (else `TypeError` / `ValueError`); `state` must be a dict (else `TypeError`). |
| `load()` | Return `{"index", "state", "done"}`; safe on missing/corrupt files. A negative or non-int `index` on disk loads as `0`; `done` entries may be any JSON value (unhashable ones are de-duplicated by value). |
| `mark_done(item_id)` | Add to the done set (idempotent), persist atomically. |
| `is_done(item_id)` | `True` if the item was marked done. |
| `resume_index()` | Next index to process (items below it are complete). |

### Two patterns

- **checkpoint-every-N** — checkpoint every N items to reduce I/O; worst-case
  rework is bounded to N items. Make `process()` idempotent.
- **per-item done set** — `mark_done(id)` + `is_done(id)` for exact resume with
  no rework, when each item has a stable id.

See `SKILL.md` for the full protocols.

## Corrupt files

If the checkpoint file exists but cannot be parsed (truncated JSON, not a JSON
object), readers return the initial snapshot. The first `save()` / `mark_done()`
after that moves the damaged file to `<path>.corrupt` (or `<path>.corrupt.1`,
`.2`, ... if that name is taken) before writing the new checkpoint, so the old
progress stays recoverable by hand. A healthy file is never moved.

## Known limitations

- Single writer: there is no cross-process locking; two processes sharing one
  checkpoint file can overwrite each other's progress.
- `.corrupt.N` files are never cleaned up automatically; repeated corruption
  accumulates them.
- The containing directory is not fsynced after `os.replace`.

## Demo

```bash
python3 demo.py
```

Runs a 5-step job that crashes at step 2 before checkpointing, then a second run
that resumes from step 2 — proving steps 0-1 are not redone.

## Test

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
# or simply:
python3 -m unittest
```

Standard-library `unittest` only — no `pip install`, no network.

## Files

```
checkpoint.py          core helper (stdlib only)
demo.py                crash-and-resume walkthrough
tests/test_checkpoint.py   unittest suite
SPEC.md                requirements + interface contract
SKILL.md               agent skill (frontmatter + protocols)
```
