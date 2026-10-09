"""toolcall-guard core — pure-Python tool-call validation and JSON repair.

Standard library only. No network, no third-party dependencies.

Public API:
    validate(args, schema)      -> list[dict]   (errors; empty == valid)
    correction_hint(errors)     -> str
    repair_json(s)              -> tuple[bool, object | None]
"""

from __future__ import annotations

import json
from typing import Any

__all__ = ["validate", "correction_hint", "repair_json"]


# --------------------------------------------------------------------------- #
# Type checking for the supported JSON-Schema subset.
# --------------------------------------------------------------------------- #

def _matches_type(value: Any, expected: Any) -> bool:
    """Return True if ``value`` matches the JSON-Schema ``type`` keyword.

    Note: ``bool`` is a subclass of ``int`` in Python, so integer/number
    types must explicitly reject booleans to match JSON semantics.
    ``expected`` may be a list of type names (JSON-Schema union, e.g.
    ``["string", "null"]``): the value must match at least one of them.
    """
    if isinstance(expected, (list, tuple)):
        return any(_matches_type(value, item) for item in expected)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    # Unknown type keyword: do not fabricate an error (forward-compatible).
    return True


def _in_enum(value: Any, enum: Any) -> bool:
    """JSON-aware membership: ``True`` must not equal ``1`` (nor False 0)."""
    if not isinstance(enum, (list, tuple)):
        return False
    for candidate in enum:
        if isinstance(value, bool) != isinstance(candidate, bool):
            continue
        if value == candidate:
            return True
    return False


def _join_path(prefix: str, key: str) -> str:
    return f"{prefix}.{key}" if prefix else key


def _validate_node(value: Any, schema: dict, path: str, errors: list) -> None:
    """Recursively validate ``value`` against ``schema``, appending errors."""
    if not isinstance(schema, dict):
        return

    expected_type = schema.get("type")
    if expected_type is not None:
        if not _matches_type(value, expected_type):
            errors.append({
                "path": path or "<root>",
                "message": (
                    f"expected type '{expected_type}', "
                    f"got '{type(value).__name__}'"
                ),
                "kind": "type",
            })
            # Type is wrong; deeper structural checks would be noise.
            return

    enum = schema.get("enum")
    if enum is not None and not _in_enum(value, enum):
        errors.append({
            "path": path or "<root>",
            "message": f"value {value!r} is not one of {enum!r}",
            "kind": "enum",
        })

    properties = schema.get("properties")
    required = schema.get("required")

    if isinstance(value, dict):
        if isinstance(required, list):
            for key in required:
                if key not in value:
                    errors.append({
                        "path": _join_path(path, key),
                        "message": f"required field '{key}' is missing",
                        "kind": "required",
                    })
        if isinstance(properties, dict):
            for key, subschema in properties.items():
                if key in value:
                    _validate_node(
                        value[key], subschema, _join_path(path, key), errors
                    )


def validate(args: dict, schema: dict) -> list:
    """Validate ``args`` against the supported JSON-Schema subset.

    Returns a list of error dicts, each shaped as::

        {"path": str, "message": str, "kind": str}

    ``kind`` is one of ``type``, ``required``, ``enum``, ``schema``.
    An empty list means the arguments are valid.
    """
    if not isinstance(schema, dict):
        return [{
            "path": "<root>",
            "message": "schema must be an object",
            "kind": "schema",
        }]
    errors: list = []
    _validate_node(args, schema, "", errors)
    return errors


# --------------------------------------------------------------------------- #
# Correction hint generation.
# --------------------------------------------------------------------------- #

def correction_hint(errors: list) -> str:
    """Render ``errors`` into a structured correction note for the model.

    The note names every offending field path so the model can target its
    next attempt instead of regenerating the whole payload blindly.
    """
    if not errors:
        return "All arguments are valid. No corrections needed."

    lines = [
        f"Found {len(errors)} problem(s) with the tool-call arguments. "
        "Fix each field below and resubmit:"
    ]
    for i, e in enumerate(errors, 1):
        path = e.get("path", "<unknown>")
        kind = e.get("kind", "error")
        message = e.get("message", "")
        lines.append(f"  {i}. field '{path}' [{kind}]: {message}")
    lines.append(
        "Only change the listed fields; keep all other fields exactly as they were."
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Best-effort JSON repair.
# --------------------------------------------------------------------------- #

def _strip_trailing_commas(s: str) -> str:
    """Remove commas that directly precede a closing ``}`` or ``]``.

    Skips characters inside string literals so commas in strings survive.
    """
    out: list = []
    in_string = False
    quote = ""
    escaped = False
    n = len(s)
    for idx, ch in enumerate(s):
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                in_string = False
            continue

        if ch in ('"', "'"):
            in_string = True
            quote = ch
            out.append(ch)
            continue

        if ch == ",":
            # Look ahead past whitespace for a closing bracket.
            j = idx + 1
            while j < n and s[j] in " \t\r\n":
                j += 1
            if j < n and s[j] in "}]":
                continue  # drop this trailing comma
        out.append(ch)
    return "".join(out)


def _convert_single_quotes(s: str) -> str:
    """Convert single-quoted string literals to double-quoted ones.

    Escapes any embedded double quotes so the result stays valid JSON.
    Double-quoted regions are passed through untouched.
    """
    out: list = []
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch == '"':
            # Copy an existing double-quoted string verbatim.
            out.append(ch)
            i += 1
            while i < n:
                c = s[i]
                out.append(c)
                if c == "\\" and i + 1 < n:
                    out.append(s[i + 1])
                    i += 2
                    continue
                i += 1
                if c == '"':
                    break
            continue
        if ch == "'":
            # Rewrite a single-quoted string as double-quoted.
            out.append('"')
            i += 1
            while i < n:
                c = s[i]
                if c == "\\" and i + 1 < n:
                    out.append(c)
                    out.append(s[i + 1])
                    i += 2
                    continue
                if c == "'":
                    i += 1
                    break
                if c == '"':
                    out.append('\\"')
                    i += 1
                    continue
                out.append(c)
                i += 1
            out.append('"')
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _balance_brackets(s: str) -> str:
    """Append closing brackets/braces for any left open outside of strings."""
    stack: list = []
    in_string = False
    quote = ""
    escaped = False
    for ch in s:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                in_string = False
            continue
        if ch in ('"', "'"):
            in_string = True
            quote = ch
        elif ch in "{[":
            stack.append(ch)
        elif ch == "}":
            if stack and stack[-1] == "{":
                stack.pop()
        elif ch == "]":
            if stack and stack[-1] == "[":
                stack.pop()
    closers = {"{": "}", "[": "]"}
    suffix = "".join(closers[c] for c in reversed(stack))
    return s + suffix


def repair_json(s: str):
    """Best-effort repair of common broken JSON.

    Handles trailing commas, single-quoted strings, and missing closing
    brackets/braces (in that order, then re-balancing after stripping commas).

    Returns ``(True, parsed_obj)`` on success or ``(False, None)`` on failure.
    """
    if not isinstance(s, str) or not s.strip():
        return (False, None)

    # Fast path: already valid.
    try:
        return (True, json.loads(s))
    except RecursionError:
        # Pathologically deep nesting: refuse instead of crashing the caller.
        return (False, None)
    except (ValueError, TypeError):
        pass

    candidate = s
    try:
        candidate = _convert_single_quotes(candidate)
        candidate = _strip_trailing_commas(candidate)
        candidate = _balance_brackets(candidate)
        # Balancing may have exposed a fresh trailing comma; strip once more.
        candidate = _strip_trailing_commas(candidate)
        return (True, json.loads(candidate))
    except (ValueError, TypeError, RecursionError):
        return (False, None)
