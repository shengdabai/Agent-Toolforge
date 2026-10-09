"""Tests for the thin server block-translation layer (no mcp dependency)."""

import base64
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from multimodal_fs import server  # noqa: E402

_PNG_1X1 = base64.b64decode(
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGNgAAIAAAUAAen63NgAAAAASUVORK5CYII="
)


def _write_temp(suffix, data):
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    return path


class ReadFileBlocksTests(unittest.TestCase):
    def test_text_block(self):
        path = _write_temp(".txt", b"hello")
        self.addCleanup(os.remove, path)
        blocks = server.read_file_blocks(path)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["type"], "text")
        self.assertEqual(blocks[0]["text"], "hello")

    def test_image_block(self):
        path = _write_temp(".png", _PNG_1X1)
        self.addCleanup(os.remove, path)
        blocks = server.read_file_blocks(path)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["type"], "image")
        self.assertEqual(blocks[0]["mimeType"], "image/png")
        self.assertEqual(base64.b64decode(blocks[0]["data"]), _PNG_1X1)

    def test_binary_block(self):
        data = bytes([0x00, 0x01, 0xFF, 0x00])
        path = _write_temp(".dat", data)
        self.addCleanup(os.remove, path)
        blocks = server.read_file_blocks(path)
        self.assertEqual(blocks[0]["type"], "text")
        self.assertIn("Binary file", blocks[0]["text"])
        self.assertIn(str(len(data)), blocks[0]["text"])

    def test_missing_path_returns_error_block_not_raise(self):
        blocks = server.read_file_blocks("/no/such/path.xyz")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["type"], "text")
        self.assertIn("Error", blocks[0]["text"])


if __name__ == "__main__":
    unittest.main()
