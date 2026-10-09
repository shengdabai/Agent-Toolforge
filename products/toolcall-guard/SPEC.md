# toolcall-guard — SPEC

## Problem

AI agents frequently emit malformed tool calls: arguments that violate the
declared schema, or JSON that is syntactically broken (trailing commas, single
quotes, missing closing brackets). When the host blindly rejects these, the
model retries the same broken output, producing an expensive infinite-retry
loop. `toolcall-guard` sits in front of tool execution and:

1. Validates arguments against a minimal JSON-Schema subset.
2. Produces a structured, model-friendly correction hint so the next attempt
   converges instead of looping.
3. Repairs common JSON breakage so a near-miss does not require a retry at all.

## Scope

- Pure-Python core (`guard.py`), stdlib only. No network, no third-party deps.
- A thin MCP server (`server.py`) exposing one tool, `validate_call`.

## Requirements (fill-in contract)

| ID | Requirement |
|----|-------------|
| R1 | Compliant `args` against `schema` → empty error list |
| R2 | A `required` key missing → one error with `path` pointing at the key and `kind == "required"` |
| R3 | A value whose type differs from `properties[key].type` → error with `kind == "type"` |
| R4 | A value not in `properties[key].enum` → error with `kind == "enum"` |
| R5 | `repair_json` fixes a trailing comma in objects/arrays |
| R6 | `repair_json` converts single-quoted JSON to valid double-quoted JSON |
| R7 | `repair_json` appends missing closing brackets/braces |
| R8 | `repair_json` on irreparable garbage → `(False, None)` |
| R9 | `correction_hint(errors)` returns a string containing each field path |

## Interface contract

```python
def validate(args: dict, schema: dict) -> list[dict]:
    """Return a list of error dicts. Each error:
       {"path": str, "message": str, "kind": str}
       kind in {"type", "required", "enum", "properties", "schema"}
       Empty list means valid.
    """

def correction_hint(errors: list[dict]) -> str:
    """Render errors into a structured natural-language correction note that
       names every offending field path. Empty errors → an 'all good' note."""

def repair_json(s: str) -> tuple[bool, object | None]:
    """Best-effort repair of common broken JSON.
       Returns (True, parsed_obj) on success, (False, None) on failure."""
```

### Supported JSON-Schema subset

- `type`: one of `object array string number integer boolean null`, or a list
  of those (union, e.g. `["string", "null"]` — value must match at least one)
- `required`: list of property names (object-level)
- `properties`: per-key sub-schemas (recursively validated)
- `enum`: list of allowed literal values (JSON semantics: `true` is not `1`)

`repair_json` returns `(False, None)` for pathologically deep nesting instead of
raising `RecursionError`.

Unsupported keywords are ignored (forward-compatible, never error).

## MCP tool

`validate_call(name: str, args: dict, schema: dict) -> dict`
Returns `{"tool": name, "valid": bool, "errors": [...], "hint": str}`.
