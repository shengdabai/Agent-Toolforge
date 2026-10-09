"""Pure-Python multimodal file reader (standard library only).

The official Filesystem MCP `read_file` tool degrades binary/image/PDF content
into garbled text. This module classifies a path into one of four kinds
(text / image / pdf / binary) using both file extension and magic bytes, and
returns a structured payload appropriate to each kind:

    - text   -> {"kind": "text", "text": <decoded str>}
    - image  -> {"kind": "image", "mime": <str>, "base64": <str>}
    - pdf    -> {"kind": "pdf", "text": <str>, "pages": <int>}        # pypdf present
               {"kind": "pdf", "note": "pypdf not installed", "pages": None}  # degraded
    - binary -> {"kind": "binary", "size": <int>, "note": <str>}

All logic is stdlib-only and never touches the network. pypdf is an optional
enhancement: if it is not installed, PDF reading degrades gracefully instead of
raising.
"""

import base64
import os

# --- Magic-byte signatures -------------------------------------------------
# Each entry: (signature_bytes, kind, mime). Order matters: longer / more
# specific signatures should be checked first.
_IMAGE_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
    # WEBP: "RIFF....WEBP" — handled specially below.
)

_PDF_MAGIC = b"%PDF-"

# --- Extension maps --------------------------------------------------------
_TEXT_EXTS = frozenset(
    {
        ".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".log",
        ".json", ".jsonl", ".yaml", ".yml", ".toml", ".ini", ".cfg",
        ".xml", ".html", ".htm", ".css", ".js", ".ts", ".jsx", ".tsx",
        ".py", ".rb", ".go", ".rs", ".java", ".c", ".h", ".cpp", ".hpp",
        ".sh", ".bash", ".zsh", ".sql", ".env", ".gitignore", ".tex",
    }
)

_IMAGE_EXT_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
    ".ico": "image/x-icon",
}

_PDF_EXTS = frozenset({".pdf"})

_MAGIC_READ_BYTES = 16


def _read_magic(path):
    """Read the leading bytes of a file for magic-byte detection."""
    with open(path, "rb") as fh:
        return fh.read(_MAGIC_READ_BYTES)


def _magic_image_mime(head):
    """Return an image MIME type if the header matches a known image signature."""
    for sig, mime in _IMAGE_MAGIC:
        if head.startswith(sig):
            return mime
    # WEBP: bytes 0..3 == "RIFF" and bytes 8..11 == "WEBP".
    if len(head) >= 12 and head[0:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def _ext(path):
    return os.path.splitext(path)[1].lower()


def _ensure_exists(path):
    if not os.path.isfile(path):
        raise FileNotFoundError(f"No such file: {path}")


def detect_kind(path):
    """Classify a file path as one of: 'text', 'image', 'pdf', 'binary'.

    Detection combines magic bytes (authoritative) with file extension as a
    fallback. Magic bytes win when they unambiguously identify a format, so a
    PNG saved with a misleading ``.dat`` extension is still detected as image.

    Raises FileNotFoundError if the path does not exist.
    """
    _ensure_exists(path)
    head = _read_magic(path)

    # 1. Magic bytes are authoritative for binary formats.
    image_mime = _magic_image_mime(head)
    if image_mime is not None:
        return "image"
    if head.startswith(_PDF_MAGIC):
        return "pdf"

    # 2. Extension-based classification.
    ext = _ext(path)
    if ext in _IMAGE_EXT_MIME:
        return "image"
    if ext in _PDF_EXTS:
        return "pdf"
    if ext in _TEXT_EXTS:
        return "text"

    # 3. Heuristic: if the head decodes cleanly as UTF-8 and has no NUL bytes,
    #    treat it as text; otherwise binary.
    if head and b"\x00" not in head:
        try:
            head.decode("utf-8")
            return "text"
        except UnicodeDecodeError:
            pass
    return "binary"


def _image_mime_for(path, head):
    """Best-effort MIME for an image: prefer magic bytes, fall back to extension."""
    mime = _magic_image_mime(head)
    if mime is not None:
        return mime
    return _IMAGE_EXT_MIME.get(_ext(path), "application/octet-stream")


def _read_text(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    # Decode as UTF-8 with replacement so a near-text file never crashes.
    return {"kind": "text", "text": raw.decode("utf-8", errors="replace")}


def _read_image(path, head):
    with open(path, "rb") as fh:
        raw = fh.read()
    return {
        "kind": "image",
        "mime": _image_mime_for(path, head),
        "base64": base64.b64encode(raw).decode("ascii"),
    }


def _read_pdf(path):
    """Extract PDF text via pypdf if available, otherwise degrade gracefully."""
    try:
        import pypdf  # type: ignore
    except ImportError:
        return {"kind": "pdf", "note": "pypdf not installed", "pages": None}

    try:
        reader_obj = pypdf.PdfReader(path)
        pages = reader_obj.pages
        if len(pages) > 100:
            return {"kind": "pdf", "pages": len(pages), "note": "PDF exceeds 100-page extraction limit"}
        chunks = []
        remaining = 200_000
        for page in pages:
            try:
                text = page.extract_text() or ""
                chunks.append(text[:remaining])
                remaining -= len(chunks[-1])
                if remaining <= 0:
                    break
            except Exception:  # pragma: no cover - per-page extraction quirk
                chunks.append("")
        return {
            "kind": "pdf",
            "text": "\n".join(chunks),
            "pages": len(pages),
            "truncated": remaining <= 0,
        }
    except Exception as exc:  # pragma: no cover - malformed PDF
        return {
            "kind": "pdf",
            "note": f"pdf parse failed: {exc}",
            "pages": None,
        }


def _read_binary(path):
    size = os.path.getsize(path)
    return {
        "kind": "binary",
        "size": size,
        "note": "binary content not rendered; returned metadata only",
    }


def read_path(path):
    """Read a file and return a kind-appropriate structured payload.

    Raises FileNotFoundError if the path does not exist.
    """
    _ensure_exists(path)
    head = _read_magic(path)

    image_mime = _magic_image_mime(head)
    if image_mime is not None:
        return _read_image(path, head)
    if head.startswith(_PDF_MAGIC):
        return _read_pdf(path)

    ext = _ext(path)
    if ext in _IMAGE_EXT_MIME:
        return _read_image(path, head)
    if ext in _PDF_EXTS:
        return _read_pdf(path)
    if ext in _TEXT_EXTS:
        return _read_text(path)

    if head and b"\x00" not in head:
        try:
            head.decode("utf-8")
            return _read_text(path)
        except UnicodeDecodeError:
            pass
    return _read_binary(path)
