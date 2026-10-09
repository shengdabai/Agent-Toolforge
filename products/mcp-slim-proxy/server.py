"""mcp-slim-proxy MCP server — thin wrapper over slim.py.

Exposes one tool, ``slim_response``, that projects/truncates an oversized JSON
payload down to a token budget. All real logic lives in slim.py (stdlib only);
this file only adapts it to the Model Context Protocol.

The MCP import is guarded so the core module and its unittest suite run even
when ``mcp`` is not installed. Run the server with::

    pip install "mcp[cli]"
    python3 server.py
"""

from __future__ import annotations

from typing import Any, Optional

from slim import slim

try:
    from mcp.server.fastmcp import FastMCP

    _MCP_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without mcp installed
    FastMCP = None  # type: ignore[assignment]
    _MCP_AVAILABLE = False


def slim_response(payload: Any, rules: Optional[dict] = None) -> dict:
    """Slim ``payload`` per ``rules`` and return {"data", "meta"}.

    rules (all optional):
        fields:    list of field names; supports dotted paths like "user.name"
        max_items: cap each list to its first N elements
        max_chars: truncate long strings to N chars with an ellipsis marker
        drop_nulls: drop dict keys whose value is null

    Returns a dict so the caller gets both the slimmed payload and the
    token-reduction report in a single MCP tool result.
    """
    data, meta = slim(payload, rules)
    return {"data": data, "meta": meta}


def build_server() -> "FastMCP":
    """Construct the FastMCP server and register the slim_response tool."""
    if not _MCP_AVAILABLE:
        raise RuntimeError(
            "The 'mcp' package is not installed. Install it with "
            "`pip install \"mcp[cli]\"` to run the server."
        )
    server = FastMCP("mcp-slim-proxy")
    server.tool()(slim_response)
    return server


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
