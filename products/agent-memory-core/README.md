# agent-memory-core

Cross-session **structured** memory for AI agents.

Most "memory" MCP servers only store and retrieve blobs. `agent-memory-core`
goes further: it **extracts entities** from each fact, **links** facts to those
entities, and **ranks recall** by keyword relevance with a recency tie-break.

## Why

| Capability                 | Plain memory MCP | agent-memory-core |
| -------------------------- | ---------------- | ----------------- |
| Store / retrieve text      | yes              | yes               |
| Auto-extract entities      | no               | yes               |
| Link facts to entities     | no               | yes               |
| Relevance + recency rank   | no               | yes               |
| Filter recall by entity    | no               | yes               |

## Architecture

- `memory.py` — pure-Python core (stdlib `sqlite3` only). All logic + tests
  live here; no network, no third-party deps.
- `server.py` — thin MCP wrapper exposing two tools (`add_fact`, `recall`).
  The MCP import is guarded by `try/except`, so the core works even when no MCP
  runtime is installed.

## Install

Core (zero dependencies, Python 3.8+):

```bash
# nothing to install — uses the Python standard library
python3 -c "from memory import Memory; print('ok')"
```

Server (only if you want to run it as an MCP server):

```bash
pip install mcp        # FastMCP runtime
```

## Usage (core module)

```python
from memory import Memory

mem = Memory("agent_memory.db")

mem.add_fact('Alice shipped "Project Phoenix" via the `deploy` command', ts=1000.0)
mem.add_fact("Bob reviewed the report", ts=1001.0)

# Relevance + recency ranked recall:
hits = mem.recall("project phoenix deploy")
# -> [{"id": 1, "text": "...", "ts": 1000.0, "score": 3,
#      "entities": ["Project Phoenix", "deploy", "Alice"]}]

# Filter to a single entity (case-insensitive):
bob = mem.recall("reviewed report", entity="bob")

mem.close()
```

### `add_fact(text, ts=None) -> int`
Stores the fact, auto-extracts entities (capitalized tokens, `"quoted"` spans,
`` `backticked` `` spans), returns the new fact id. `ts` defaults to now.
Raises `ValueError` for empty / non-string `text`, and for a `ts` that is not a
number or is not finite (`NaN` / `inf`).

### `recall(query, limit=5, entity=None) -> list[dict]`
Returns facts whose tokens overlap the query, scored by intersection size,
sorted by `(score desc, ts desc, id desc)`. Score-0 facts are excluded. Pass
`entity` to restrict to facts linked to that entity. Each result is
`{"id", "text", "ts", "score", "entities"}`.

`limit` must be a positive integer (`bool`, zero and negatives raise
`ValueError`); a non-string `query` raises `ValueError`; a query with no word
tokens returns `[]`.

**Tokenization.** Overlap is computed on lowercased word tokens. ASCII words are
unchanged. Other alphabets (e.g. `café`, `Москва`) form words too, and every
CJK / kana / hangul character is its own token (no word segmentation), so
Chinese, Japanese and Korean facts can be recalled. Because scoring is per
character for those scripts, CJK recall is coarse: a query can match facts that
share only common characters.

`Memory` is also a context manager (`with Memory(path) as mem:`), and
`entities_of(fact_id)` returns the stored entities of one fact.

## Run as MCP server

```bash
AGENT_MEMORY_DB=./agent_memory.db python3 server.py
```

Exposes MCP tools `add_fact` and `recall`.

## Tests

Standard-library `unittest` only — no `pip install` required:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
# or simply
python3 -m unittest
```

## License

MIT.
