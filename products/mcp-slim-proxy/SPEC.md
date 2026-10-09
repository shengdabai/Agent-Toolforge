# SPEC — mcp-slim-proxy

## Problem

MCP servers frequently pour raw upstream JSON into the agent context window. A
single tool response can be ~67,000 tokens, blowing past a 25,000-token tool
budget. The agent only needs a fraction of the fields, a fraction of the list
items, and short string previews — not megabytes of verbatim payload.

`mcp-slim-proxy` is a response-slimming layer. It takes an arbitrary
JSON-serializable payload plus a declarative `rules` object and returns a
shrunken payload plus a `meta` block reporting the token reduction.

## Requirements (fill-in contract)

| # | Requirement | Acceptance |
|---|-------------|------------|
| R1 | Field whitelist | Given `fields=["a","c"]`, only keys `a` and `c` survive on each dict; all other keys are dropped. |
| R2 | Dotted-path projection | `fields=["user.name"]` keeps `user` as `{"name": ...}`, dropping sibling keys of `user`. |
| R3 | List item cap | `max_items=N` truncates any list to its first `N` elements. |
| R4 | Long-string truncation | `max_chars=N` truncates any string longer than `N` to `N` chars and appends an ellipsis marker. |
| R5 | Optional null drop | `drop_nulls=True` removes dict keys whose value is `None`. |
| R6 | Token estimate | `token_est(s) = ceil(len(json_str(s)) / 4)`. `meta` reports `orig_tokens_est`, `slim_tokens_est`, `reduction_pct`. |
| R7 | Empty rules passthrough | Empty / `None` rules returns a structural copy of the payload unchanged (apart from being a copy). |
| R8 | Recursive application | Rules apply at every nesting depth (lists of dicts, nested dicts). |

## Interface contract

```python
def slim(payload, rules=None) -> tuple[Any, dict]:
    """Return (slimmed_payload, meta).

    rules keys (all optional):
      - fields:    list[str]  field whitelist; supports dotted paths "a.b"
      - max_items: int        max list length kept (>=0)
      - max_chars: int        max string length kept before truncation (>=0)
      - drop_nulls: bool       drop dict keys whose value is None

    Malformed rules raise ValueError instead of silently dropping data:
    non-dict rules, `fields` that is not a list (a bare string is rejected),
    and max_items/max_chars that are negative, bool, or non-int.

    meta = {
      "orig_tokens_est": int,
      "slim_tokens_est": int,
      "reduction_pct":   float,   # 0.0 .. 100.0, rounded to 2 dp
    }
    """
```

### Semantics

- `fields` whitelist applies to **dict** nodes only. Lists and scalars pass
  through (their dict children are filtered if/when reached).
- A dotted path `"a.b.c"` keeps the chain `a -> b -> c`. Multiple paths sharing
  a prefix merge (e.g. `["user.name","user.id"]` keeps both under `user`).
- A bare field `"a"` keeps the entire subtree under `a` (then recursively
  slimmed by the other rules such as `max_items` / `max_chars`).
- Truncation marker for strings is the constant `"…[+{n} chars]"` where `n` is
  the number of dropped characters.
- `reduction_pct = round((1 - slim/orig) * 100, 2)`; if `orig == 0` it is `0.0`.

## Form

MCP server. Pure logic lives in `slim.py` (stdlib only). `server.py` is a thin
FastMCP wrapper exposing one tool `slim_response(payload, rules)`. The server
import is guarded so the core module and its tests run without `mcp` installed.

## Test command

```
python3 -m unittest discover -s tests -p 'test_*.py' -v
```
