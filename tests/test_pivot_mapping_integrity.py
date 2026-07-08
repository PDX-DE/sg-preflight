from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sg_preflight.pivot_mapping_integrity import (
    broken_aliases,
    build_pivot_mapping_board,
    pivot_mapping_board_markdown,
    read_pivot_transforms,
    read_position_mapping,
    write_pivot_mapping_board,
)


def _write_profile(root: Path, profile: str, mapping: dict, transforms: list[str]) -> None:
    d = root / "cars" / "BMW" / profile / "_Workfiles" / "json"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{profile}_Position_Mapping.json").write_text(
        json.dumps({"positionMapping": mapping}), encoding="utf-8"
    )
    (d / f"{profile}_Pivot_Master.json").write_text(
        json.dumps({"TRANSFORMS": {t: {} for t in transforms}}), encoding="utf-8"
    )


class PivotMappingUnitTests(unittest.TestCase):
    def test_broken_aliases_ignores_self_maps_and_empty(self) -> None:
        mapping = {"Static": "Static", "Lid_F": "Lid_F_L", "Skip": "", "Door_F": "Door_F_L"}
        transforms = {"Static", "Door_F_L"}
        result = broken_aliases(mapping, transforms)
        self.assertEqual(result, [{"position": "Lid_F", "target": "Lid_F_L"}])

    def test_read_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_profile(root, "G65", {"Lid_F": "Lid_F_L"}, ["Lid_F_L", "Static"])
            base = root / "cars" / "BMW" / "G65" / "_Workfiles" / "json"
            self.assertEqual(read_position_mapping(base / "G65_Position_Mapping.json"), {"Lid_F": "Lid_F_L"})
            self.assertEqual(read_pivot_transforms(base / "G65_Pivot_Master.json"), {"Lid_F_L", "Static"})


class PivotMappingBoardTests(unittest.TestCase):
    def test_board_flags_broken_and_cross_references_siblings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # G65 defines Lid_F_L; F70 aliases to it but does not define it.
            _write_profile(root, "G65", {"Lid_F": "Lid_F_L", "Static": "Static"}, ["Lid_F_L", "Static"])
            _write_profile(root, "F70", {"Lid_F": "Lid_F_L", "Static": "Static"}, ["Lid_B_R", "Static"])
            board = build_pivot_mapping_board(root)

        self.assertEqual(board["state"], "ok")
        self.assertEqual(board["profiles_scanned"], 2)
        self.assertEqual(board["profiles_paired"], 2)
        self.assertEqual(board["profiles_with_broken"], 1)
        self.assertEqual(board["total_broken"], 1)
        self.assertEqual(board["broken_by_profile"][0]["profile"], "F70")

        target = next(t for t in board["targets"] if t["target"] == "Lid_F_L")
        self.assertEqual(target["missing_in"], ["F70"])
        self.assertEqual(target["present_in"], ["G65"])

    def test_all_resolved_reports_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_profile(root, "G65", {"Lid_F": "Lid_F_L"}, ["Lid_F_L"])
            board = build_pivot_mapping_board(root)
        self.assertEqual(board["total_broken"], 0)
        self.assertIn("Every position alias resolves", pivot_mapping_board_markdown(board))

    def test_unpaired_profile_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = root / "cars" / "BMW" / "X99" / "_Workfiles" / "json"
            d.mkdir(parents=True, exist_ok=True)
            (d / "X99_Position_Mapping.json").write_text(json.dumps({"positionMapping": {"a": "b"}}), encoding="utf-8")
            board = build_pivot_mapping_board(root)
        self.assertEqual(board["unpaired"], ["X99"])
        self.assertEqual(board["profiles_paired"], 0)

    def test_no_mapping_found_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = build_pivot_mapping_board(tmp)
        self.assertEqual(board["state"], "no_mapping_found")

    def test_markdown_and_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_profile(root, "G65", {"Lid_F": "Lid_F_L"}, ["Lid_F_L"])
            _write_profile(root, "F70", {"Lid_F": "Lid_F_L"}, ["Lid_B_R"])
            board = build_pivot_mapping_board(root)
            text = pivot_mapping_board_markdown(board)
            out = write_pivot_mapping_board(board, root / "out" / "pivot.md")
            self.assertIn("Unresolved aliases by profile", text)
            self.assertIn("Where each missing target is defined", text)
            self.assertTrue(out.is_file())


if __name__ == "__main__":
    unittest.main()
