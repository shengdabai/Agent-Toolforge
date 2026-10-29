# toolcall-guard

A gatekeeper for AI agent tool calls. It stops the expensive infinite-retry
loop that happens when a model emits arguments that don't match a tool's
schema or that contain broken JSON.

`toolcall-guard` does three things:

1. **Validate** arguments against a minimal JSON-Schema subset and report
   precise, structured errors.
2. **Hint** — turn those errors into a model-friendly correction note that
   names every offending field so the next attempt converges.
3. **Repair** — fix common JSON breakage (trailing commas, single quotes,
   missing closing brackets) so a near-miss doesn't need a retry at all.

The core (`guard.py`) is pure Python, standard library only. The MCP server
(`server.py`) is a thin optional layer on top.

## Install

No installation needed for the core or the tests — they use only the Python
standard library.

To run the MCP server you need the optional `mcp` package:

```bash
pip install mcp
```

## Usage

### Core library

```python
from guard import validate, correction_hint, repair_json

schema = {
    "type": "object",
    "required": ["name", "age"],
    "properties": {
        "name": {"type": "string"},
        "age": {"type": "integer"},
        "role": {"type": "string", "enum": ["admin", "user", "guest"]},
    },
}

errors = validate({"name": "Ada", "role": "superuser"}, schema)
# [
#   {"path": "age", "message": "required field 'age' is missing", "kind": "required"},
#   {"path": "role", "message": "value 'superuser' is not one of [...]", "kind": "enum"},
# ]

print(correction_hint(errors))
# Found 2 problem(s) with the tool-call arguments. Fix each field below and resubmit:
#   1. field 'age' [required]: required field 'age' is missing
#   2. field 'role' [enum]: value 'superuser' is not one of ['admin', 'user', 'guest']
#   Only change the listed fields; keep all other fields exactly as they were.

ok, obj = repair_json("{'a': [1, 2,], 'b': 'x'")
# (True, {"a": [1, 2], "b": "x"})
```

### MCP server

```bash
python3 server.py
```

Exposes two tools:

- `validate_call(name, args, schema) -> {tool, valid, errors, hint}`
- `repair_call_json(raw) -> {repaired, value}`

## Supported JSON-Schema subset

| Keyword       | Behaviour |
|---------------|-----------|
| `type`        | `object array string number integer boolean null` (integer/number reject booleans). A list such as `["string", "null"]` is a union: the value must match at least one member. An unknown type name is not an error (it matches anything) |
| `required`    | object-level list of required property names |
| `properties`  | per-key sub-schemas, validated recursively (paths are dotted, e.g. `addr.zip`) |
| `enum`        | value must be one of the listed literals. JSON-aware: `true` does not match `1` and `false` does not match `0`, including inside arrays and objects. Numeric `1` and `1.0` still match. A non-list `enum` matches nothing |

Unsupported keywords are ignored, so richer schemas pass through without
false errors.

`valid: true` therefore means "passed this subset", not full JSON-Schema
validation (no `items`, `additionalProperties`, `minimum`, `pattern`, ...).

## Repair behaviour

`repair_json(s)` returns `(True, value)` or `(False, None)`; it never raises. It
returns `(False, None)` for empty / non-string input, for input it cannot fix,
and for pathologically deep nesting (e.g. `"[" * 200000`, which used to raise
`RecursionError` and crash the MCP tool). Note that Python's `json` still
accepts `NaN` / `Infinity` literals, so a repaired value can contain them.
Escaped apostrophes inside single-quoted strings are preserved as apostrophes.
Missing container closers can be appended, but an unterminated string returns
`(False, None)`; the helper cannot determine the intended missing text.

## Tests

```bash
cd products/toolcall-guard
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

All tests use only `unittest` from the standard library — no `pip install`
required.
