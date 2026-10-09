"""checkpoint-resume — crash-survivable progress checkpoints for long batch jobs.

Pure standard library. No network, no third-party dependencies.

A long-running agent processes an ordered list of work items. If it crashes at
item N, a re-run should continue from the next unfinished item instead of
restarting from zero. ``Checkpoint`` persists progress as a single JSON file,
written atomically so a crash mid-write can never corrupt the saved state.

On-disk schema::

    {"index": <int>, "state": <dict>, "done": [<item_id>, ...]}

Typical loop::

    ck = Checkpoint("progress.json")
    for i in range(ck.resume_index(), len(items)):
        item = items[i]
        if ck.is_done(item.id):
            continue
        process(item)
        ck.mark_done(item.id)
        ck.save(i + 1, {"last_id": item.id})
"""
from __future__ import annotations

import os
import json
import tempfile
from typing import Any, Dict, Hashable, List, Optional

__all__ = ["Checkpoint"]


class Checkpoint:
    """A single-writer, crash-survivable JSON progress checkpoint."""

    def __init__(self, path: str, initial_state: Optional[Dict[str, Any]] = None):
        if not path:
            raise ValueError("Checkpoint requires a non-empty file path")
        self.path = path
        # Store an independent copy so external mutation of the passed dict
        # cannot retroactively change our fallback snapshot.
        self._initial_state: Dict[str, Any] = dict(initial_state or {})

    # ----------------------------------------------------------------- read

    def _initial_snapshot(self) -> Dict[str, Any]:
        return {"index": 0, "state": dict(self._initial_state), "done": []}

    def load(self) -> Dict[str, Any]:
        """Return ``{"index", "state", "done"}``.

        Missing file -> initial snapshot. Corrupt / wrong-shape file -> initial
        snapshot. Never raises for a missing or unreadable checkpoint.
        """
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (FileNotFoundError, ValueError, OSError, UnicodeDecodeError,
                RecursionError):
            return self._initial_snapshot()

        if not isinstance(raw, dict):
            return self._initial_snapshot()

        index = raw.get("index", 0)
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            index = 0

        state = raw.get("state", None)
        if not isinstance(state, dict):
            state = dict(self._initial_state)

        done = raw.get("done", [])
        if not isinstance(done, list):
            done = []
        # Deduplicate while preserving first-seen order.
        # Entries may be unhashable (JSON lists/dicts), so compare by value
        # for those instead of raising from a reader.
        seen = set()
        deduped: List[Any] = []
        for item in done:
            try:
                if item in seen:
                    continue
                seen.add(item)
            except TypeError:
                if item in deduped:
                    continue
            deduped.append(item)

        return {"index": index, "state": state, "done": deduped}

    def resume_index(self) -> int:
        """Return the next index to process (items below it are complete)."""
        return self.load()["index"]

    def is_done(self, item_id: Hashable) -> bool:
        """True iff ``item_id`` has been marked done."""
        return item_id in self.load()["done"]

    # ---------------------------------------------------------------- write

    def _quarantine_if_corrupt(self) -> Optional[str]:
        """Move an existing but unusable checkpoint aside before overwriting.

        ``load()`` degrades a corrupt/unreadable file to the initial snapshot.
        Without this step the next write would silently replace that file and
        destroy the only copy of the previous progress. The file is renamed to
        ``<path>.corrupt`` (or ``.corrupt.N``) so it stays recoverable. Returns
        the quarantine path, or None when the file is missing or healthy.
        """
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            if isinstance(raw, dict):
                return None
        except FileNotFoundError:
            return None
        except (ValueError, OSError, UnicodeDecodeError, RecursionError):
            pass
        target = self.path + ".corrupt"
        n = 0
        while os.path.lexists(target):
            n += 1
            target = "%s.corrupt.%d" % (self.path, n)
        os.replace(self.path, target)
        return target

    def _atomic_write(self, payload: Dict[str, Any]) -> None:
        """Write ``payload`` as JSON atomically.

        Strategy: write to a temp file in the SAME directory (so ``os.replace``
        is an atomic same-filesystem rename), fsync, then replace the target.
        On any failure, remove the temp file and re-raise — the existing target
        file is left untouched.
        """
        directory = os.path.dirname(os.path.abspath(self.path)) or "."
        os.makedirs(directory, exist_ok=True)

        fd, tmp_path = tempfile.mkstemp(
            prefix=".ckpt-", suffix=".tmp", dir=directory
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            # Only after the new payload is safely on disk: keep a corrupt
            # predecessor recoverable instead of overwriting it.
            self._quarantine_if_corrupt()
            os.replace(tmp_path, self.path)  # atomic on the same filesystem
        except Exception:
            # Clean up the temp file so a failed write leaves no debris.
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
            raise

    def save(self, index: int, state: Dict[str, Any]) -> None:
        """Atomically persist ``index`` and ``state``, preserving ``done``."""
        if not isinstance(index, int) or isinstance(index, bool):
            raise TypeError("index must be an int")
        if index < 0:
            raise ValueError("index must be >= 0")
        if not isinstance(state, dict):
            raise TypeError("state must be a dict")
        current = self.load()
        payload = {"index": index, "state": state, "done": current["done"]}
        self._atomic_write(payload)

    def mark_done(self, item_id: Hashable) -> None:
        """Add ``item_id`` to the done set (idempotent) and persist atomically."""
        current = self.load()
        if item_id not in current["done"]:
            current["done"].append(item_id)
        self._atomic_write(current)
