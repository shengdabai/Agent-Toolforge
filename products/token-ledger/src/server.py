"""Thin MCP server wrapping the token-ledger core.

The core logic lives in ledger.py (pure stdlib, fully testable without this
file). MCP is an optional dependency: if it cannot be imported, the core
remains usable and its tests still pass.
"""
from __future__ import annotations

from typing import List, Mapping

from ledger import PRICING, attribute, cost, detect_spikes

try:
    from mcp.server.fastmcp import FastMCP

    _MCP_AVAILABLE = True
except Exception:  # pragma: no cover - exercised only when mcp is absent
    FastMCP = None  # type: ignore
    _MCP_AVAILABLE = False


def build_server():
    """Construct and return the FastMCP server. Raises if mcp is unavailable."""
    if not _MCP_AVAILABLE:
        raise RuntimeError(
            "The 'mcp' package is not installed. Install it with "
            "`pip install mcp` to run the server; the ledger core works "
            "without it."
        )

    mcp = FastMCP("token-ledger")

    @mcp.tool()
    def attribute_cost(events: List[Mapping], by: str = "session") -> List[dict]:
        """Attribute total spend across events, grouped by session/model/tag.

        Args:
            events: list of {model, input_tokens, output_tokens, session?, tag?}.
            by: grouping key, one of "session", "model", "tag".

        Returns a list of {key, cost, input_tokens, output_tokens, events}
        sorted by cost descending.
        """
        return attribute(events, by=by, pricing=PRICING)

    @mcp.tool()
    def event_cost(event: Mapping) -> float:
        """Return the USD cost of a single event using the default pricing."""
        return cost(event, PRICING)

    @mcp.tool()
    def find_spikes(series: List[Mapping], z: float = 2.0) -> List[dict]:
        """Flag cost-series points exceeding mean + z*stddev as spikes."""
        return detect_spikes(series, z=z)

    return mcp


def main() -> None:  # pragma: no cover - process entry point
    build_server().run()


if __name__ == "__main__":  # pragma: no cover
    main()
