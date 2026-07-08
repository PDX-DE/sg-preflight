from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from sg_preflight.rca_reference_integrity import (
    build_rca_reference_board,
    rca_reference_board_markdown,
    read_rca_external_projects,
    write_rca_reference_board,
)


def _make_rca(path: Path, external_projects: dict | None) -> None:
    payload: dict = {"racoVersion": "2.9.0", "instances": []}
    if external_projects is not None:
        payload["externalProjects"] = external_projects
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("project.json", json.dumps(payload))


class RcaReferenceIntegrityTests(unittest.TestCase):
    def test_resolves_existing_relative_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_rca(root / "_Shared" / "UI_Camera" / "UI_Camera.rca", None)
            _make_rca(
                root / "Ambient" / "Main" / "Ambient.rca",
                {"uuid-1": {"name": "UI_Camera", "path": "../../_Shared/UI_Camera/UI_Camera.rca"}},
            )

            refs = read_rca_external_projects(root / "Ambient" / "Main" / "Ambient.rca")

        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["name"], "UI_Camera")
        self.assertEqual(refs[0]["status"], "resolved")

    def test_flags_missing_relative_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_rca(
                root / "Ambient" / "Main" / "Ambient.rca",
                {"uuid-1": {"name": "GoneCamera", "path": "../../_Shared/Gone/Gone.rca"}},
            )

            refs = read_rca_external_projects(root / "Ambient" / "Main" / "Ambient.rca")

        self.assertEqual(refs[0]["status"], "missing")
        self.assertTrue(refs[0]["resolved_path"].endswith("Gone.rca"))

    def test_rca_without_external_projects_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rca = Path(tmp) / "Solo.rca"
            _make_rca(rca, None)
            self.assertEqual(read_rca_external_projects(rca), [])

    def test_non_rca_file_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plain = Path(tmp) / "notes.txt"
            plain.write_text("not a zip", encoding="utf-8")
            self.assertEqual(read_rca_external_projects(plain), [])

    def test_board_counts_resolved_and_broken_across_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_rca(root / "_Shared" / "Cam" / "Cam.rca", None)
            _make_rca(
                root / "A" / "A.rca",
                {"u1": {"name": "Cam", "path": "../_Shared/Cam/Cam.rca"}},
            )
            _make_rca(
                root / "B" / "B.rca",
                {"u2": {"name": "Cam", "path": "../_Shared/Cam/Cam.rca"},
                 "u3": {"name": "Prefab", "path": "../_Shared/Missing/Prefab.rca"}},
            )
            _make_rca(root / "C" / "C.rca", None)

            board = build_rca_reference_board(root)

        self.assertEqual(board["state"], "ok")
        self.assertEqual(board["scanned_files"], 4)
        self.assertEqual(board["files_with_references"], 2)
        self.assertEqual(board["total_references"], 3)
        self.assertEqual(board["resolved"], 2)
        self.assertEqual(board["missing"], 1)
        self.assertEqual(len(board["broken"]), 1)
        self.assertEqual(board["broken"][0]["name"], "Prefab")
        self.assertIn("Missing", board["broken"][0]["resolved_path"])

    def test_board_reports_no_rca_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = build_rca_reference_board(tmp)
        self.assertEqual(board["state"], "no_rca_found")
        self.assertEqual(board["scanned_files"], 0)

    def test_scan_limit_is_reported_when_truncated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index in range(3):
                _make_rca(root / f"p{index}" / f"p{index}.rca", None)
            board = build_rca_reference_board(root, scan_limit=2)
        self.assertTrue(board["truncated"])
        self.assertEqual(board["scanned_files"], 2)

    def test_markdown_headline_reflects_broken_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_rca(
                root / "A" / "A.rca",
                {"u1": {"name": "Gone", "path": "../missing.rca"}},
            )
            board = build_rca_reference_board(root)
            text = rca_reference_board_markdown(board)
            out = write_rca_reference_board(board, root / "out" / "board.md")

            self.assertIn("1 of 1 external reference(s) are broken.", text)
            self.assertIn("## Broken references", text)
            self.assertTrue(out.is_file())


if __name__ == "__main__":
    unittest.main()
