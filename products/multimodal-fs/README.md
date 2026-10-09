# multimodal-fs

Multimodal-aware file reading for AI agents — an MCP server that fixes the
classic `read_file` problem (official Filesystem MCP #533): images and PDFs come
back as garbled text instead of usable content.

`multimodal-fs` classifies each file by **magic bytes + extension** and returns
the right representation:

- **text** → decoded UTF-8 text
- **image** (PNG/JPEG/GIF/BMP/WEBP/…) → base64 + mime, surfaced as an MCP **image block** so the agent can actually see it
- **pdf** → extracted text (via optional `pypdf`), with graceful degradation if `pypdf` is missing
- **binary** → safe metadata (size + note), never garbled bytes

## Why

`read_file` decoding a PNG as a string is useless. This wraps a pure-Python
classifier in a thin MCP layer so an agent gets an image block for an image and
real text for a PDF.

## Layout

```
multimodal-fs/
├── SPEC.md
├── README.md
├── src/multimodal_fs/
│   ├── __init__.py
│   ├── reader.py      # pure stdlib core: detect_kind / read_path
│   ├── access.py      # FileAccess: --root boundary used by the MCP entrypoint
│   └── server.py      # thin MCP wrapper (optional `mcp` dependency)
└── tests/
    ├── test_access.py
    ├── test_reader.py
    └── test_server.py
```

The core (`reader.py`) is **standard-library only** and never touches the
network. `pypdf` (for PDF text) and `mcp` (for the server) are optional — the
core and its tests run without either.

## Install

No install needed for the core. Clone and use directly:

```bash
# Optional enhancements:
pip install pypdf   # PDF text extraction (otherwise PDFs degrade gracefully)
pip install mcp     # required only to run the MCP server
```

## Usage — core (stdlib only)

```python
import sys
sys.path.insert(0, "src")
from multimodal_fs import reader

reader.detect_kind("photo.png")        # -> "image"
reader.read_path("notes.txt")          # -> {"kind": "text", "text": "..."}
img = reader.read_path("photo.png")    # -> {"kind": "image", "mime": "image/png", "base64": "..."}
reader.read_path("doc.pdf")            # -> {"kind": "pdf", "text": "...", "pages": 3}  (pypdf present)
                                       #    {"kind": "pdf", "note": "pypdf not installed", "pages": None}
reader.read_path("blob.bin")           # -> {"kind": "binary", "size": 1024, "note": "..."}
```

A missing path raises `FileNotFoundError`.

Other PDF results: more than 100 pages returns
`{"kind": "pdf", "pages": N, "note": "PDF exceeds 100-page extraction limit"}`
(no text); text is capped at about 200,000 characters and then
`"truncated": true`; a PDF that `pypdf` cannot parse returns
`{"kind": "pdf", "note": "pdf parse failed: ...", "pages": None}`.

## Usage — MCP server

```bash
pip install mcp
PYTHONPATH=src python3 -m multimodal_fs.server --root /path/to/permitted/workspace
```

Exposes a single tool, `read_file(path)`, returning MCP content blocks
(image block for images, text block for everything else). Wire it into your MCP
client config as a stdio server.

## Test

```bash
cd products/multimodal-fs
python3 -m unittest discover -s tests -p 'test_*.py'
```

All core tests are stdlib-only and run green with no third-party packages. The
PDF "happy path" test self-skips when `pypdf` is absent.

## MCP file boundary

The stdio entrypoint requires `--root`. It opens the directory once and reads only descendant regular files through no-follow directory descriptors. Traversal, symlinks, hardlinks, special files, common credential names and files over 8 MiB are denied. This boundary requires POSIX `dir_fd` and `O_NOFOLLOW`; unsupported systems fail closed.

The permitted file is copied from its open descriptor into a private temporary file before parsing. PDF extraction stops at 100 pages / approximately 200,000 characters. These limits do not isolate the PDF parser from decompression or CPU attacks; use a process sandbox for hostile PDFs. Library functions `reader.read_path` and `server.read_file_blocks` remain trusted-caller APIs; only the MCP entrypoint enforces `FileAccess`.

A denied read (outside `--root`, `..`, symlink, hardlink, special file, credential
name, over 8 MiB) raises `PermissionError`, which the MCP tool reports as an error.

Existing MCP launch configurations must explicitly add the intended `--root`; no home-directory default is inferred.
