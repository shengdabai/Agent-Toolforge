import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from multimodal_fs.access import FileAccess, MAX_BYTES
from multimodal_fs.server import read_authorized_blocks


class AccessBoundary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "allowed"
        self.root.mkdir()
        (self.root / "ok.txt").write_text("fixture")
        (self.base / "outside.txt").write_text("outside fixture")
        self.access = FileAccess(self.root)

    def tearDown(self):
        self.access.close()
        self.temp.cleanup()

    def test_valid_text_block(self):
        self.assertEqual(read_authorized_blocks(self.access, "ok.txt"), [{"type": "text", "text": "fixture"}])

    def test_traversal_absolute_and_secret_paths(self):
        (self.root / ".env.fixture").write_text("synthetic, not a real credential")
        for path in ["../outside.txt", str(self.base / "outside.txt"), ".env.fixture", "auth.json", ".ssh/key", "credentials.json"]:
            with self.subTest(path=path):
                self.assertTrue(read_authorized_blocks(self.access, path)[0]["text"].startswith("Error:"))

    def test_symlink_files_and_directories_rejected(self):
        (self.root / "link.txt").symlink_to(self.base / "outside.txt")
        (self.root / "dir").symlink_to(self.base, target_is_directory=True)
        for path in ["link.txt", "dir/outside.txt"]:
            self.assertTrue(read_authorized_blocks(self.access, path)[0]["text"].startswith("Error:"))

    def test_hardlink_fifo_and_oversize_rejected(self):
        os.link(self.base / "outside.txt", self.root / "hard.txt")
        os.mkfifo(self.root / "pipe")
        with (self.root / "large.txt").open("wb") as f:
            f.truncate(MAX_BYTES + 1)
        for path in ["hard.txt", "pipe", "large.txt"]:
            self.assertTrue(read_authorized_blocks(self.access, path)[0]["text"].startswith("Error:"))

    def test_root_descriptor_stays_pinned(self):
        moved = self.base / "moved"
        self.root.rename(moved)
        self.root.symlink_to(self.base, target_is_directory=True)
        self.assertEqual(self.access.read("ok.txt")[0], b"fixture")
        self.assertTrue(read_authorized_blocks(self.access, "outside.txt")[0]["text"].startswith("Error:"))

    def test_credential_directory_roots_rejected(self):
        for name in [".ssh", ".aws"]:
            sensitive = self.base / name
            nested = sensitive / "nested"
            nested.mkdir(parents=True)
            for root in [sensitive, nested]:
                with self.assertRaises(PermissionError):
                    FileAccess(root)


if __name__ == "__main__":
    unittest.main()
