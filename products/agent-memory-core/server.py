"""MCP server for agent-memory-core.

Thin wrapper over the pure-Python `memory.Memory` core. The MCP/FastMCP import
is guarded so the core module and its unittest suite work even when no MCP
runtime is installed.

Run:
    python3 server.py            # starts the MCP server (requires `mcp`)
Env:
    AGENT_MEMORY_DB    path to the SQLite db (default: ./agent_memory.db)
"""
from __future__ import annotations

import os
from typing import List, Optional

from memory import Memory

_DB_PATH = os.environ.get("AGENT_MEMORY_DB", "agent_memory.db")

try:
    from mcp.server.fastmcp import FastMCP  # type: ignore

    _MCP_AVAILABLE = True
except Exception:  # pragma: no cover - exercised only without mcp installed
    FastMCP = None  # type: ignore
    _MCP_AVAILABLE = False


def _get_memory() -> Memory:
    """One Memory instance per process, lazily created."""
    global _MEMORY
    try:
        return _MEMORY
    except NameError:
        pass
    _MEMORY = Memory(_DB_PATH)  # type: ignore[name-defined]
    return _MEMORY


def add_fact(text: str, ts: Optional[float] = None) -> dict:
    """Store a natural-language fact; auto-extract entities. Returns id+entities."""
    mem = _get_memory()
    fact_id = mem.add_fact(text, ts=ts)
    return {"id": fact_id, "entities": mem.entities_of(fact_id)}


def recall(query: str, limit: int = 5, entity: Optional[str] = None) -> List[dict]:
    """Recall facts ranked by keyword overlap with a recency tie-break."""
    mem = _get_memory()
    return mem.recall(query, limit=limit, entity=entity)


def build_server():
    """Construct and return a FastMCP server exposing add_fact / recall."""
    if not _MCP_AVAILABLE:
        raise RuntimeError(
            "mcp/fastmcp is not installed. Install with `pip install mcp` "
            "to run the server. The core module (memory.py) works without it."
        )
    mcp = FastMCP("agent-memory-core")
    mcp.tool()(add_fact)
    mcp.tool()(recall)
    return mcp


def main() -> None:  # pragma: no cover - runtime entrypoint
    server = build_server()
    server.run()


if __name__ == "__main__":  # pragma: no cover
    main()
