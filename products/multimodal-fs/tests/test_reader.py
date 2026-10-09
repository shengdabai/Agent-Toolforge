"""Tests for the multimodal-fs reader core (stdlib-only)."""

import base64
import os
import sys
import tempfile
import unittest

# Make the package importable when running `python3 -m unittest` from the
# product root or via discover.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from multimodal_fs import reader  # noqa: E402


# A minimal but valid PNG file: 1x1 transparent pixel.
# Bytes start with the PNG signature 89 50 4E 47 0D 0A 1A 0A.
_PNG_1X1 = base64.b64decode(
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGNgAAIAAAUAAen63NgAAAAASUVORK5CYII="
)

# A minimal JPEG header (SOI + APP0/JFIF marker). Enough magic bytes for detection.
_JPEG_HEADER = bytes(
    [0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01]
)

# A minimal PDF header.
_PDF_HEADER = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"

# A minimal but fully valid, parseable PDF (one empty page, no text).
_PDF_VALID = (
    b"%PDF-1.4\n"
    b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>\nendobj\n"
    b"xref\n0 4\n"
    b"0000000000 65535 f \n"
    b"0000000009 00000 n \n"
    b"0000000058 00000 n \n"
    b"0000000115 00000 n \n"
    b"trailer\n<< /Size 4 /Root 1 0 R >>\n"
    b"startxref\n190\n"
    b"%%EOF\n"
)


def _write_temp(suffix, data):
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    return path


class DetectKindTests(unittest.TestCase):
    def test_text_extension(self):
        path = _write_temp(".txt", b"hello world")
        self.addCleanup(os.remove, path)
        self.assertEqual(reader.detect_kind(path), "text")

    def test_markdown_extension(self):
        path = _write_temp(".md", b"# title")
        self.addCleanup(os.remove, path)
        self.assertEqual(reader.detect_kind(path), "text")

    def test_png_by_extension_and_magic(self):
        path = _write_temp(".png", _PNG_1X1)
        self.addCleanup(os.remove, path)
        self.assertEqual(reader.detect_kind(path), "image")

    def test_jpeg_by_extension(self):
        path = _write_temp(".jpg", _JPEG_HEADER)
        self.addCleanup(os.remove, path)
        self.assertEqual(reader.detect_kind(path), "image")

    def test_png_by_magic_even_with_wrong_extension(self):
        # Magic bytes should win when extension is misleading.
        path = _write_temp(".dat", _PNG_1X1)
        self.addCleanup(os.remove, path)
        self.assertEqual(reader.detect_kind(path), "image")

    def test_pdf_by_extension(self):
        path = _write_temp(".pdf", _PDF_HEADER)
        self.addCleanup(os.remove, path)
        self.assertEqual(reader.detect_kind(path), "pdf")

    def test_pdf_by_magic(self):
        path = _write_temp(".bin", _PDF_HEADER)
        self.addCleanup(os.remove, path)
        self.assertEqual(reader.detect_kind(path), "pdf")

    def test_unknown_binary(self):
        path = _write_temp(".dat", bytes([0x00, 0x01, 0x02, 0xFF, 0xFE, 0x00]))
        self.addCleanup(os.remove, path)
        self.assertEqual(reader.detect_kind(path), "binary")

    def test_missing_path_raises(self):
        with self.assertRaises(FileNotFoundError):
            reader.detect_kind("/no/such/file/at/all.xyz")


class ReadPathTests(unittest.TestCase):
    def test_read_text(self):
        path = _write_temp(".txt", b"hello world")
        self.addCleanup(os.remove, path)
        result = reader.read_path(path)
        self.assertEqual(result["kind"], "text")
        self.assertEqual(result["text"], "hello world")

    def test_read_text_utf8(self):
        path = _write_temp(".txt", "中文内容".encode("utf-8"))
        self.addCleanup(os.remove, path)
        result = reader.read_path(path)
        self.assertEqual(result["kind"], "text")
        self.assertEqual(result["text"], "中文内容")

    def test_read_png_returns_base64_and_mime(self):
        path = _write_temp(".png", _PNG_1X1)
        self.addCleanup(os.remove, path)
        result = reader.read_path(path)
        self.assertEqual(result["kind"], "image")
        self.assertEqual(result["mime"], "image/png")
        # base64 must round-trip back to the original bytes.
        self.assertEqual(base64.b64decode(result["base64"]), _PNG_1X1)

    def test_read_jpeg_mime(self):
        path = _write_temp(".jpg", _JPEG_HEADER)
        self.addCleanup(os.remove, path)
        result = reader.read_path(path)
        self.assertEqual(result["kind"], "image")
        self.assertEqual(result["mime"], "image/jpeg")
        self.assertEqual(base64.b64decode(result["base64"]), _JPEG_HEADER)

    def test_read_pdf_graceful_when_pypdf_missing(self):
        path = _write_temp(".pdf", _PDF_HEADER)
        self.addCleanup(os.remove, path)
        result = reader.read_path(path)
        self.assertEqual(result["kind"], "pdf")
        # Three valid outcomes, all graceful (never raises):
        #  a) pypdf not installed       -> note + pages None
        #  b) pypdf present, parse fail  -> note + pages None  (minimal header)
        #  c) pypdf present, parse ok    -> text + int pages
        if "note" in result:
            # Degraded path (pypdf missing OR header not a full valid PDF).
            self.assertIsNone(result["pages"])
        else:
            self.assertIn("text", result)
            self.assertIsInstance(result.get("pages"), int)

    def test_read_valid_pdf_when_pypdf_present(self):
        try:
            import pypdf  # noqa: F401
        except ImportError:
            self.skipTest("pypdf not installed")
        path = _write_temp(".pdf", _PDF_VALID)
        self.addCleanup(os.remove, path)
        result = reader.read_path(path)
        self.assertEqual(result["kind"], "pdf")
        # A valid 1-page PDF must parse to text + page count, no degradation note.
        self.assertNotIn("note", result)
        self.assertIn("text", result)
        self.assertEqual(result["pages"], 1)

    def test_read_unknown_binary(self):
        data = bytes([0x00, 0x01, 0x02, 0xFF, 0xFE, 0x00, 0x42])
        path = _write_temp(".dat", data)
        self.addCleanup(os.remove, path)
        result = reader.read_path(path)
        self.assertEqual(result["kind"], "binary")
        self.assertEqual(result["size"], len(data))
        self.assertIn("note", result)

    def test_read_missing_path_raises(self):
        with self.assertRaises(FileNotFoundError):
            reader.read_path("/no/such/file/at/all.xyz")


if __name__ == "__main__":
    unittest.main()
