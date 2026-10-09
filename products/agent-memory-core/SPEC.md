# agent-memory-core — SPEC

## Problem

Existing "memory" MCP servers store and retrieve blobs but do not:
- extract structured facts/entities from free text,
- link facts to the entities they mention,
- rank recall by relevance and recency.

`agent-memory-core` is a cross-session structured memory: an agent writes
natural-language facts, the system auto-extracts entities, and later recalls
the most relevant facts by keyword overlap with a recency tie-break, optionally
filtered to a single entity.

## Core module: `memory.py` (stdlib only, sqlite3)

### `class Memory(db_path: str)`

Opens/creates a SQLite database at `db_path`. Schema:

- `facts(id INTEGER PK, text TEXT NOT NULL, ts REAL NOT NULL)`
- `entities(fact_id INTEGER, entity TEXT)` — many rows per fact

Persistent: reopening `Memory` on the same `db_path` recalls prior facts.

### `add_fact(text: str, ts: float | None = None) -> int`

- Stores the fact text and a timestamp. If `ts` is `None`, uses current time
  (`time.time()`).
- Auto-extracts entities with simple deterministic rules:
  - Capitalized tokens (a word starting with an uppercase letter).
  - Tokens inside double quotes `"..."`.
  - Tokens inside backticks `` `...` ``.
- Entities are normalized to a canonical surface form (stripped of surrounding
  punctuation) and de-duplicated per fact.
- Returns the new fact id.

### `recall(query: str, limit: int = 5, entity: str | None = None) -> list[dict]`

- Tokenizes `query` into lowercased word tokens. ASCII words are unchanged;
  non-ASCII letters form words too, and each CJK/kana/hangul character is one
  token (no segmentation), so non-English facts are recallable.
- Scores each fact by the number of distinct query tokens that also appear in
  the fact's tokens (keyword overlap intersection size).
- Facts with score 0 are excluded (an unrelated query returns nothing).
- If `entity` is given, only facts linked to that entity (case-insensitive) are
  considered.
- Sort order: by score descending, then by `ts` descending (newer first) as a
  tie-break, then by id descending for full determinism.
- Returns up to `limit` facts, each a dict:
  `{"id": int, "text": str, "ts": float, "score": int, "entities": list[str]}`.

## Interface contract (acceptance)

1. After `add_fact`, a `recall` with overlapping keywords returns that fact.
2. A `recall` whose tokens do not overlap any stored fact returns `[]`.
3. `recall(..., entity=E)` returns only facts whose extracted entities include E.
4. When two facts tie on score, the one with the newer `ts` ranks first.
5. Persistence: a fresh `Memory(db_path)` on the same file still recalls facts.

## Server form

`server.py` exposes two MCP tools `add_fact` and `recall` over the core module.
The MCP import is wrapped in `try/except`; if `mcp`/`fastmcp` is not installed,
the core module and its tests are unaffected.
