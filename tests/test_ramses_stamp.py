from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sg_preflight.ramses_stamp import (
    build_ramses_stamp_board,
    ramses_stamp_board_markdown,
    read_ramses_stamp,
    write_ramses_stamp_board,
)


def _write_ramses(path: Path, version: str, git: str = "abc123", level: str = "2") -> None:
    # Mirror the real binary header: bracketed fields separated by non-printable bytes.
    header = (
        f"[RamsesVersion:{version}]".encode("ascii")
        + b"\x00\x01"
        + f"[GitHash:{git}]".encode("ascii")
        + b"\x00\x02"
        + f"[FeatureLevel:{level}]".encode("ascii")
        + b"\x00" * 32
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header)


class RamsesStampReadTests(unittest.TestCase):
    def test_reads_stamp_with_binary_separators(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scene = Path(tmp) / "Stage.ramses"
            _write_ramses(scene, "28.14.0", "15e266db8f", "2")
            stamp = read_ramses_stamp(scene)
        self.assertEqual(stamp, {"ramses_version": "28.14.0", "git_hash": "15e266db8f", "feature_level": "2"})

    def test_returns_none_for_unstamped_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plain = Path(tmp) / "notstamped.ramses"
            plain.write_bytes(b"\x00\x01\x02 no stamp here")
            self.assertIsNone(read_ramses_stamp(plain))


class RamsesConsistencyBoardTests(unittest.TestCase):
    def test_uniform_tree_reports_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_ramses(root / "F70" / "export" / "exported.ramses", "28.15.1", "hashA", "2")
            _write_ramses(root / "G70" / "export" / "exported.ramses", "28.15.1", "hashB", "2")
            board = build_ramses_stamp_board(root)
        self.assertEqual(board["state"], "ok")
        self.assertEqual(board["scanned_files"], 2)
        self.assertEqual(board["ramses_versions"], ["28.15.1"])
        self.assertEqual(board["feature_levels"], ["2"])
        self.assertFalse(board["mixed_versions"])
        self.assertFalse(board["mixed_feature_levels"])
        self.assertEqual(len(board["breakdown"]), 1)
        self.assertEqual(board["breakdown"][0]["count"], 2)

    def test_differing_git_hash_alone_is_not_a_mix(self) -> None:
        # Per-profile outputs share a name and engine version but differ on git hash;
        # that must not be reported as inconsistency.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for profile, git in (("F70", "aaa"), ("G70", "bbb"), ("NA8", "ccc")):
                _write_ramses(root / profile / "export" / "exported.ramses", "28.15.1", git, "2")
            board = build_ramses_stamp_board(root)
        self.assertFalse(board["mixed_versions"])
        self.assertFalse(board["mixed_feature_levels"])
        self.assertEqual(len(board["breakdown"]), 1)
        self.assertEqual(board["breakdown"][0]["count"], 3)

    def test_feature_level_split_is_surfaced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_ramses(root / "F70" / "exported.ramses", "28.15.1", "a", "1")
            _write_ramses(root / "G45" / "exported.ramses", "28.15.1", "b", "1")
            _write_ramses(root / "G70" / "exported.ramses", "28.15.1", "c", "2")
            board = build_ramses_stamp_board(root)
        self.assertFalse(board["mixed_versions"])
        self.assertTrue(board["mixed_feature_levels"])
        self.assertEqual(board["feature_levels"], ["1", "2"])
        counts = {(b["ramses_version"], b["feature_level"]): b["count"] for b in board["breakdown"]}
        self.assertEqual(counts[("28.15.1", "1")], 2)
        self.assertEqual(counts[("28.15.1", "2")], 1)

    def test_version_skew_is_surfaced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_ramses(root / "old" / "s.ramses", "28.14.0", "a", "2")
            _write_ramses(root / "new" / "s.ramses", "28.16.0", "b", "2")
            board = build_ramses_stamp_board(root)
        self.assertTrue(board["mixed_versions"])
        self.assertEqual(board["ramses_versions"], ["28.14.0", "28.16.0"])

    def test_no_ramses_found_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = build_ramses_stamp_board(tmp)
        self.assertEqual(board["state"], "no_ramses_found")

    def test_markdown_consistent_and_mixed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_ramses(root / "a" / "s.ramses", "28.15.1", "a", "2")
            _write_ramses(root / "b" / "s.ramses", "28.15.1", "b", "2")
            consistent = ramses_stamp_board_markdown(build_ramses_stamp_board(root))
            self.assertIn("All 2 scene(s) export at RAMSES 28.15.1, feature level 2.", consistent)

            _write_ramses(root / "c" / "s.ramses", "28.15.1", "c", "1")
            board = build_ramses_stamp_board(root)
            mixed = ramses_stamp_board_markdown(board)
            out = write_ramses_stamp_board(board, root / "out" / "stamps.md")
            self.assertIn("feature levels", mixed)
            self.assertIn("By engine version and feature level", mixed)
            self.assertTrue(out.is_file())


if __name__ == "__main__":
    unittest.main()
