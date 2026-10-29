"""mcp-slim-proxy core logic — slim down oversized JSON payloads.

Pure standard-library module. No network, no third-party dependencies.

Public API:
    slim(payload, rules) -> (slimmed_payload, meta)
    token_est(obj)       -> int   (ceil(len(compact_json) / 4))
"""

from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Optional, Tuple

# Marker appended to truncated strings. `{n}` = number of dropped characters.
TRUNC_MARKER = "…[+{n} chars]"


def token_est(obj: Any) -> int:
    """Estimate token count of a JSON-serializable object.

    Uses the heuristic token_est = ceil(len(json_str) / 4), where json_str is
    the compact (no whitespace) JSON encoding. Non-serializable objects fall
    back to their ``str()`` length.
    """
    try:
        s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        s = str(obj)
    if not s:
        return 0
    return math.ceil(len(s) / 4)


def _truncate_str(value: str, max_chars: int) -> str:
    """Truncate ``value`` to ``max_chars`` and append the dropped-count marker."""
    if max_chars < 0 or len(value) <= max_chars:
        return value
    dropped = len(value) - max_chars
    return value[:max_chars] + TRUNC_MARKER.format(n=dropped)


def _build_field_tree(fields: List[str]) -> Dict[str, Optional[dict]]:
    """Turn a list of (possibly dotted) field paths into a nested keep-tree.

    A leaf maps to ``None`` (keep the whole subtree). An intermediate node maps
    to a nested dict describing which children to keep. Sibling paths sharing a
    prefix merge automatically.

    Example: ["user.name", "user.id", "meta"] ->
        {"user": {"name": None, "id": None}, "meta": None}
    """
    tree: Dict[str, Optional[dict]] = {}
    for path in fields:
        if not isinstance(path, str) or path == "":
            continue
        parts = path.split(".")
        node = tree
        for i, part in enumerate(parts):
            is_last = i == len(parts) - 1
            if is_last:
                # Selecting a parent includes all its children, regardless of
                # whether a narrower path was listed before it.
                node[part] = None
            else:
                if part in node and node[part] is None:
                    break  # This whole subtree is already selected.
                if part not in node:
                    node[part] = {}
                node = node[part]
    return tree


def _apply_field_tree(value: Any, tree: Dict[str, Optional[dict]]) -> Any:
    """Project ``value`` through the keep-tree.

    Applies the whitelist to dict nodes. If the node is a list, the tree is
    applied to each element (so a list of dicts gets each dict projected).
    Scalars pass through unchanged.
    """
    if isinstance(value, list):
        return [_apply_field_tree(item, tree) for item in value]
    if not isinstance(value, dict):
        return value
    out: Dict[str, Any] = {}
    for key, subtree in tree.items():
        if key not in value:
            continue
        if subtree is None:
            out[key] = value[key]
        else:
            out[key] = _apply_field_tree(value[key], subtree)
    return out


def _walk(value: Any, max_items: Optional[int], max_chars: Optional[int],
          drop_nulls: bool) -> Any:
    """Recursively apply list-cap, string-truncate and null-drop rules."""
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for key, sub in value.items():
            if drop_nulls and sub is None:
                continue
            out[key] = _walk(sub, max_items, max_chars, drop_nulls)
        return out
    if isinstance(value, list):
        items = value if max_items is None else value[:max_items]
        return [_walk(item, max_items, max_chars, drop_nulls) for item in items]
    if isinstance(value, str) and max_chars is not None:
        return _truncate_str(value, max_chars)
    return value


def slim(payload: Any, rules: Optional[dict] = None) -> Tuple[Any, dict]:
    """Slim a JSON-serializable ``payload`` according to ``rules``.

    rules (all optional):
        fields:    list[str]  field whitelist; supports dotted paths "a.b"
        max_items: int        max list length kept (>= 0)
        max_chars: int        max string length before truncation (>= 0)
        drop_nulls: bool      drop dict keys whose value is None

    Returns (slimmed_payload, meta) where meta carries token estimates and the
    reduction percentage.
    """
    orig_tokens = token_est(payload)

    if rules is None:
        rules = {}
    if not isinstance(rules, dict):
        raise ValueError("rules must be a dict")
    fields = rules.get("fields")
    max_items = rules.get("max_items")
    max_chars = rules.get("max_chars")
    drop_nulls = bool(rules.get("drop_nulls", False))

    # Reject malformed rules instead of silently dropping data: a negative
    # max_items would slice from the end, and a bare string for ``fields``
    # would be split into single characters and project everything away.
    if fields is not None and (
        isinstance(fields, (str, bytes)) or not isinstance(fields, (list, tuple))
    ):
        raise ValueError("rules['fields'] must be a list of field paths")
    for key, limit in (("max_items", max_items), ("max_chars", max_chars)):
        if limit is None:
            continue
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
            raise ValueError("rules[%r] must be an integer >= 0" % key)

    # Field projection first (top-level dict whitelist), then recursive walk.
    if fields:
        tree = _build_field_tree(list(fields))
        projected = _apply_field_tree(payload, tree)
    else:
        projected = payload

    slimmed = _walk(projected, max_items, max_chars, drop_nulls)

    slim_tokens = token_est(slimmed)
    if orig_tokens == 0:
        reduction_pct = 0.0
    else:
        reduction_pct = round((1 - slim_tokens / orig_tokens) * 100, 2)

    meta = {
        "orig_tokens_est": orig_tokens,
        "slim_tokens_est": slim_tokens,
        "reduction_pct": reduction_pct,
    }
    return slimmed, meta
