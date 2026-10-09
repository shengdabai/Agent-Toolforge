"""toolcall-guard MCP server — a thin wrapper over the pure-Python core.

The MCP runtime (``mcp`` / FastMCP) is an optional dependency. The import is
guarded so the core logic and its unit tests remain fully usable even when the
MCP package is not installed.

Run as an MCP server (stdio transport)::

    pip install mcp
    python3 server.py
"""

from __future__ import annotations

from guard import validate, correction_hint, repair_json

try:
    from mcp.server.fastmcp import FastMCP
    _MCP_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without mcp installed
    FastMCP = None  # type: ignore[assignment]
    _MCP_AVAILABLE = False


def _build_validate_result(name: str, args: dict, schema: dict) -> dict:
    """Pure helper: validate a tool call and package an MCP-friendly result.

    Kept dependency-free so it can be unit-tested without the MCP runtime.
    """
    errors = validate(args, schema)
    return {
        "tool": name,
        "valid": not errors,
        "errors": errors,
        "hint": correction_hint(errors),
    }


def _build_repair_result(raw: str) -> dict:
    """Pure helper: attempt to repair raw JSON for an MCP-friendly result."""
    ok, obj = repair_json(raw)
    return {"repaired": ok, "value": obj}


if _MCP_AVAILABLE:
    mcp = FastMCP("toolcall-guard")

    @mcp.tool()
    def validate_call(name: str, args: dict, schema: dict) -> dict:
        """Validate a tool call's arguments against a JSON-Schema subset.

        Returns ``{tool, valid, errors, hint}`` where ``hint`` is a structured
        correction note the model can act on to avoid retry loops.
        """
        return _build_validate_result(name, args, schema)

    @mcp.tool()
    def repair_call_json(raw: str) -> dict:
        """Best-effort repair of broken JSON tool-call arguments.

        Returns ``{repaired: bool, value: object | None}``.
        """
        return _build_repair_result(raw)


def main() -> None:
    if not _MCP_AVAILABLE:
        raise SystemExit(
            "The 'mcp' package is not installed. Install it with "
            "`pip install mcp` to run the MCP server. The core guard.py "
            "module works without it."
        )
    mcp.run()


if __name__ == "__main__":
    main()
