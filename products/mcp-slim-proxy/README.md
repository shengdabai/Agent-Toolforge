# mcp-slim-proxy

A Model Context Protocol response-slimming proxy. Many MCP servers dump raw
upstream JSON straight into the agent's context window — a single tool response
can run ~67,000 tokens and blow past a 25,000-token budget. `mcp-slim-proxy`
projects that payload down to just the fields, list items, and string previews
the agent actually needs, and reports how much it saved.

## What it does

Given a JSON payload and a declarative `rules` object, `slim()`:

- **Field whitelist** — keep only named fields; supports dotted paths
  (`"user.name"`) for deep projection.
- **List cap** — truncate any list to its first `max_items` elements.
- **String truncation** — clip long strings to `max_chars`, appending an
  `…[+N chars]` marker.
- **Null drop** — optionally remove keys whose value is `null`.
- **Token report** — returns a `meta` block with estimated original tokens,
  slimmed tokens, and the reduction percentage.

Token estimate is `ceil(len(compact_json) / 4)`.

## Layout

| File | Purpose |
|------|---------|
| `slim.py` | Pure stdlib core logic (`slim`, `token_est`). No deps. |
| `server.py` | Thin FastMCP wrapper exposing the `slim_response` tool. |
| `tests/test_slim.py` | unittest suite (stdlib only). |
| `SPEC.md` | Requirements + interface contract. |

## Install

The core module has **zero dependencies** — clone and use directly. To run it
as an MCP server you additionally need the `mcp` package:

```bash
pip install "mcp[cli]"
```

## Usage

### As a library

```python
from slim import slim

payload = {
    "results": [
        {"id": 1, "title": "Alpha", "body": "...very long...", "debug": None},
        {"id": 2, "title": "Beta",  "body": "...very long...", "debug": None},
    ],
    "internal_trace": "...thousands of tokens...",
}

slimmed, meta = slim(payload, {
    "fields": ["results.id", "results.title"],
    "max_items": 5,
    "max_chars": 80,
    "drop_nulls": True,
})

print(meta)  # {'orig_tokens_est': ..., 'slim_tokens_est': ..., 'reduction_pct': ...}
```

### As an MCP server

Register `server.py` with your MCP client (e.g. Claude Desktop config):

```json
{
  "mcpServers": {
    "slim-proxy": {
      "command": "python3",
      "args": ["/absolute/path/to/server.py"]
    }
  }
}
```

The server exposes one tool:

```
slim_response(payload, rules) -> {"data": <slimmed>, "meta": <report>}
```

## Rules reference

| Key | Type | Effect |
|-----|------|--------|
| `fields` | `list[str]` (or tuple) | Whitelist of fields to keep; dotted paths supported. An empty list means no projection. Entries that are not non-empty strings are ignored. |
| `max_items` | `int >= 0` | Keep only the first N items of every list. `0` empties every list. |
| `max_chars` | `int >= 0` | Truncate strings longer than N chars. `0` keeps only the marker. |
| `drop_nulls` | `bool` | Drop dict keys whose value is `null`. |

An empty or omitted `rules` returns a structural copy of the payload unchanged.

### Invalid rules raise `ValueError`

Malformed rules are rejected instead of silently dropping data (this replaced
the earlier lenient behaviour):

- `rules` is not a dict (and not empty/`None`);
- `fields` is a bare string (e.g. `"user.name"`) or any other non-list/tuple —
  it used to be split into single characters and project the payload away;
- `max_items` / `max_chars` is not an integer, is a `bool` (`True` used to act
  as `1`), or is negative (`-1` used to slice off the last item).

Callers that relied on the old lenient behaviour must now pass valid rules.
Through the MCP tool, the `ValueError` surfaces as a tool error.

## Known limitations

- `fields` that overlap (`["user", "user.name"]` vs `["user.name", "user"]`) can
  yield different projections depending on order.
- The truncation marker `…[+N chars]` can make a very short string longer than
  the original.
- When a list is truncated by `max_items`, `meta` does not report that items
  were dropped; only the token estimate changes.

## Test

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

No `pip install` required for the tests — they use only the Python standard
library.
