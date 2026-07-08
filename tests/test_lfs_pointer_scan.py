from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sg_preflight.lfs_pointer_scan import (
    lfs_extensions_from_gitattributes,
    lfs_pointer_scan_markdown,
    scan_lfs_pointers,
    write_lfs_pointer_scan,
)

GITATTRS = """\
*.png filter=lfs diff=lfs merge=lfs -text
*.ramses filter=lfs diff=lfs merge=lfs -text
unity-stage/**/*.fbx filter=lfs diff=lfs merge=lfs -text
*.txt text
"""

POINTER = b"version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 123\n"


class ExtensionParseTests(unittest.TestCase):
    def test_extracts_only_lfs_extensions(self) -> None:
        exts = lfs_extensions_from_gitattributes(GITATTRS)
        self.assertEqual(exts, {".png", ".ramses", ".fbx"})

    def test_ignores_comments_and_non_lfs(self) -> None:
        exts = lfs_extensions_from_gitattributes("# comment\n*.md text\n*.bin filter=lfs\n")
        self.assertEqual(exts, {".bin"})


class ScanTests(unittest.TestCase):
    def _repo(self, root: Path) -> None:
        (root / ".gitattributes").write_text(GITATTRS, encoding="utf-8")
        (root / "assets").mkdir(parents=True, exist_ok=True)
        (root / "assets" / "real.png").write_bytes(b"\x89PNG\r\n\x1a\n real image bytes")
        (root / "assets" / "real.ramses").write_bytes(b"[RamsesVersion:28.15.1] binary payload")
        (root / "assets" / "unpulled.png").write_bytes(POINTER)

    def test_flags_pointer_stub_and_passes_real_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._repo(root)
            board = scan_lfs_pointers(root)
        self.assertEqual(board["state"], "lfs_pointers_detected")
        self.assertEqual(board["scanned_files"], 3)
        self.assertEqual(board["pointer_stub_count"], 1)
        self.assertEqual(board["pointer_files"], ["assets/unpulled.png"])

    def test_clean_checkout_is_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".gitattributes").write_text(GITATTRS, encoding="utf-8")
            (root / "a.png").write_bytes(b"\x89PNG real")
            board = scan_lfs_pointers(root)
        self.assertEqual(board["state"], "ok")
        self.assertEqual(board["pointer_stub_count"], 0)

    def test_no_gitattributes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = scan_lfs_pointers(tmp)
        self.assertEqual(board["state"], "no_gitattributes")

    def test_gitattributes_without_lfs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".gitattributes").write_text("*.txt text\n", encoding="utf-8")
            board = scan_lfs_pointers(root)
        self.assertEqual(board["state"], "no_lfs_tracked")

    def test_markdown_and_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._repo(root)
            board = scan_lfs_pointers(root)
            text = lfs_pointer_scan_markdown(board)
            out = write_lfs_pointer_scan(board, root / "out" / "lfs.md")
            self.assertIn("un-pulled pointer stubs", text)
            self.assertIn("git lfs pull", text)
            self.assertTrue(out.is_file())


if __name__ == "__main__":
    unittest.main()
