# SPEC — multimodal-fs

## Problem

The official Filesystem MCP `read_file` tool (issue #533) returns every file as
plain text. When an agent points it at a PNG, a JPEG, or a PDF, it gets garbled
bytes decoded as a string instead of usable multimodal content. The agent
cannot "see" the image or read the PDF.

## Goal

A multimodal-aware reader that classifies a file and returns the right
representation: text as text, images as base64 + mime (so they become MCP image
blocks), PDFs as extracted text, and unknown binaries as safe metadata.

## Requirements (fill-in / answered)

| # | Question | Decision |
|---|----------|----------|
| R1 | How is file kind determined? | Magic bytes (authoritative) + extension fallback + UTF-8 heuristic. |
| R2 | What if a PNG has a wrong extension? | Magic bytes win — detected as image. |
| R3 | What if `pypdf` is not installed? | Graceful degradation: `{kind:'pdf', note:'pypdf not installed', pages:None}`. No crash. |
| R4 | What about a malformed PDF? | Graceful: `{kind:'pdf', note:'pdf parse failed: ...', pages:None}`. No crash. |
| R5 | What about a missing path? | Raise `FileNotFoundError` from the core; the server converts it to an error text block. |
| R6 | Network / heavy deps allowed in core? | No. Core is stdlib-only. `pypdf` and `mcp` are optional. |
| R7 | Text encoding? | UTF-8 with `errors='replace'` so near-text never crashes. |

## Interface Contract

### `reader.detect_kind(path: str) -> str`

Returns one of `"text" | "image" | "pdf" | "binary"`.
Raises `FileNotFoundError` if `path` does not exist.

### `reader.read_path(path: str) -> dict`

Returns a kind-tagged dict. Raises `FileNotFoundError` if `path` is missing.

| kind | shape |
|------|-------|
| text | `{"kind": "text", "text": str}` |
| image | `{"kind": "image", "mime": str, "base64": str}` |
| pdf (pypdf ok) | `{"kind": "pdf", "text": str, "pages": int}` |
| pdf (degraded) | `{"kind": "pdf", "note": str, "pages": None}` |
| binary | `{"kind": "binary", "size": int, "note": str}` |

`base64` round-trips: `base64.b64decode(result["base64"]) == original_bytes`.

### `server.read_file_blocks(path: str) -> list[dict]`

Translates a `read_path` result into MCP content blocks:
- text/pdf/binary → `{"type": "text", "text": ...}`
- image → `{"type": "image", "mimeType": ..., "data": <base64>}`
- missing path → single error text block (never raises).

### MCP tool `read_file(path: str) -> list`

Exposed by `server.main()` via FastMCP over stdio. Returns the blocks above.

## Supported formats

- Images: PNG, JPEG, GIF, BMP, WEBP (magic) + SVG/TIFF/ICO (extension).
- PDF: via optional `pypdf`.
- Text: common source/markup/data extensions + UTF-8 heuristic.
- Everything else: binary metadata.

## Out of scope

- Image resizing / OCR.
- Office documents (docx/xlsx).
- Directory traversal (single-file reads only).
