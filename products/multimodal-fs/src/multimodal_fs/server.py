"""Thin MCP server exposing multimodal-aware file reading.

This is a thin wrapper over the pure-logic core in ``reader.py``. The MCP
dependency is imported lazily inside ``main`` so that the core module and its
test suite remain fully importable and testable even when ``mcp`` is not
installed.

Run with::

    python3 -m multimodal_fs.server

Requires the optional ``mcp`` package (``pip install mcp``). Without it the
core ``reader`` module still works for direct programmatic use and tests.
"""

from . import reader
from .access import FileAccess
import argparse
import tempfile


def _build_text_block(text):
    return {"type": "text", "text": text}


def _build_image_block(mime, b64):
    return {"type": "image", "mimeType": mime, "data": b64}


def read_file_blocks(path):
    """Translate a ``reader.read_path`` result into MCP content blocks.

    Returns a list of content-block dicts:
      - text  -> a single text block
      - image -> a single image block (mimeType + base64 data)
      - pdf   -> text block with extracted text, or a note when degraded
      - binary-> text block describing the binary (size + note)

    Raised FileNotFoundError from the core is converted into an error text
    block so the MCP tool returns a clean message instead of crashing.
    """
    try:
        result = reader.read_path(path)
    except FileNotFoundError as exc:
        return [_build_text_block(f"Error: {exc}")]

    kind = result["kind"]
    if kind == "text":
        return [_build_text_block(result["text"])]
    if kind == "image":
        return [_build_image_block(result["mime"], result["base64"])]
    if kind == "pdf":
        if "text" in result:
            header = f"[PDF, {result.get('pages')} page(s)]\n"
            return [_build_text_block(header + result["text"])]
        return [_build_text_block(f"[PDF] {result.get('note', 'unavailable')}")]
    if kind == "binary":
        return [
            _build_text_block(
                f"[Binary file] size={result['size']} bytes. {result['note']}"
            )
        ]
    # Defensive fallback for any future kind.
    return [_build_text_block(str(result))]


def main():
    """Start the MCP server over stdio (requires the optional ``mcp`` package)."""
    parser = argparse.ArgumentParser(description="Read files only inside an explicitly permitted directory")
    parser.add_argument("--root", required=True, help="Permitted directory; symlinks and credential files are denied")
    args = parser.parse_args()
    access = FileAccess(args.root)
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:  # pragma: no cover - exercised only without mcp installed
        raise SystemExit(
            "The 'mcp' package is required to run the server.\n"
            "Install it with: pip install mcp\n"
            "(The core 'multimodal_fs.reader' module works without it.)"
        )

    mcp_app = FastMCP("multimodal-fs")

    @mcp_app.tool()
    def read_file(path: str) -> list:
        """Read a file as multimodal content.

        Unlike a plain text read, images are returned as image blocks
        (base64 + mime), PDFs are returned as extracted text (when pypdf is
        available), and unknown binaries return safe metadata instead of
        garbled bytes.
        """
        return read_authorized_blocks(access, path)

    try:
        mcp_app.run()
    finally:
        access.close()


def read_authorized_blocks(access, path):
    """Take a bounded descriptor-based copy before passing it to a parser."""
    try:
        data, suffix = access.read(path)
        with tempfile.NamedTemporaryFile(suffix=suffix) as copy:
            copy.write(data)
            copy.flush()
            return read_file_blocks(copy.name)
    except (OSError, ValueError, TypeError):
        return [_build_text_block("Error: file unavailable or outside the permitted read scope")]


if __name__ == "__main__":  # pragma: no cover
    main()
