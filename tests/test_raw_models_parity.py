from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from sg_preflight.raw_models_parity import (
    STATUS_DELIVERY_ONLY,
    STATUS_MATCHED,
    STATUS_SOURCE_ONLY,
    build_raw_models_parity_board,
    raw_models_parity_markdown,
    write_raw_models_parity_board,
)


def _make_raw_profile(root: Path, brand: str, name: str, *, folder: str = "_WorkFiles") -> None:
    workfiles = root / "cars" / brand / name / folder
    (workfiles / "blender").mkdir(parents=True, exist_ok=True)
    (workfiles / "blender" / f"{name}_Exterior.blend").write_bytes(b"BLENDER-fixture")
    (workfiles / "json").mkdir(parents=True, exist_ok=True)
    (workfiles / "json" / f"{name}_Pivot_Master.json").write_text("{}", encoding="utf-8")


def _make_models_profile(root: Path, brand: str, name: str) -> None:
    profile = root / "cars" / brand / name
    (profile / "export").mkdir(parents=True, exist_ok=True)
    (profile / "resources").mkdir(parents=True, exist_ok=True)
    (profile / "CHANGELOG.md").write_text("## [1.0.0] - 2026-06-01\n", encoding="utf-8")


def _parity_fixture(root: Path) -> tuple[Path, Path]:
    raw = root / "digital-3d-car-raw"
    models = root / "digital-3d-car-models"
    _make_raw_profile(raw, "BMW", "G65")
    _make_raw_profile(raw, "BMW", "F70", folder="_Workfiles")
    _make_raw_profile(raw, "BMW", "G05")
    _make_raw_profile(raw, "MINI", "J01")
    (raw / "cars" / "BMW" / "_Shared" / "_WorkFiles").mkdir(parents=True, exist_ok=True)
    (raw / "cars" / "BMW" / "Docs").mkdir(parents=True, exist_ok=True)
    _make_models_profile(models, "BMW", "G65_EVO")
    _make_models_profile(models, "BMW", "F70")
    _make_models_profile(models, "BMW", "NA7_EVO")
    _make_models_profile(models, "MINI", "J01_BEV")
    (models / "cars" / "BMW" / "_Shared").mkdir(parents=True, exist_ok=True)
    (models / "cars" / "BMW" / "randomdir").mkdir(parents=True, exist_ok=True)
    (models / "cars" / "BMW" / "perspectives_CID.json").write_text("{}", encoding="utf-8")
    return raw, models


class TestRawModelsParity(unittest.TestCase):
    def test_board_matches_renamed_profiles_and_flags_orphans_both_ways(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            raw, models = _parity_fixture(Path(temp_dir))
            board = build_raw_models_parity_board(raw_root=raw, models_root=models)

        self.assertEqual(board["raw_state"], "ready")
        self.assertEqual(board["models_state"], "ready")
        rows = {
            (row["brand"], row["raw_profile"] or row["models_profile"]): row
            for row in board["entries"]
        }
        self.assertEqual(rows[("BMW", "G65")]["status"], STATUS_MATCHED)
        self.assertEqual(rows[("BMW", "G65")]["models_profile"], "G65_EVO")
        self.assertEqual(rows[("BMW", "F70")]["status"], STATUS_MATCHED)
        self.assertEqual(rows[("BMW", "F70")]["models_profile"], "F70")
        self.assertEqual(rows[("MINI", "J01")]["models_profile"], "J01_BEV")
        self.assertEqual(rows[("BMW", "G05")]["status"], STATUS_SOURCE_ONLY)
        self.assertEqual(rows[("BMW", "NA7_EVO")]["status"], STATUS_DELIVERY_ONLY)
        self.assertEqual(board["counts"][STATUS_MATCHED], 3)
        self.assertEqual(board["counts"][STATUS_SOURCE_ONLY], 1)
        self.assertEqual(board["counts"][STATUS_DELIVERY_ONLY], 1)
        self.assertEqual(rows[("BMW", "G65")]["raw_workfiles"], {"blender": 1, "json": 1})
        self.assertIn("CHANGELOG.md", rows[("BMW", "G65")]["models_markers"])

    def test_board_keeps_unknown_and_skipped_buckets_visible(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            raw, models = _parity_fixture(Path(temp_dir))
            board = build_raw_models_parity_board(raw_root=raw, models_root=models)

        unknown_paths = [item["path"] for item in board["raw_unknown"]]
        skipped_paths = [item["path"] for item in board["models_skipped"]]
        self.assertIn("BMW/Docs", unknown_paths)
        self.assertIn("BMW/randomdir", skipped_paths)
        self.assertIn("BMW/_Shared", board["raw_shared"])
        self.assertIn("BMW/_Shared", board["models_shared"])

    def test_missing_repositories_are_reported_not_crashed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            board = build_raw_models_parity_board(
                raw_root=root / "no-raw", models_root=root / "no-models"
            )

        self.assertEqual(board["raw_state"], "missing")
        self.assertEqual(board["models_state"], "missing")
        self.assertEqual(board["counts"]["total"], 0)
        self.assertEqual(board["raw_lfs_health"]["state"], "not_present")

    def test_markdown_and_writer_render_rows_and_buckets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            raw, models = _parity_fixture(Path(temp_dir))
            board = build_raw_models_parity_board(raw_root=raw, models_root=models)
            paths = write_raw_models_parity_board(board, Path(temp_dir) / "out")

            markdown = raw_models_parity_markdown(board)
            self.assertIn("Raw vs Models Parity Board", markdown)
            self.assertIn("| BMW | G65 | G65_EVO | matched |", markdown)
            self.assertIn("Unclassified raw folders", markdown)
            self.assertIn("Skipped models folders", markdown)
            self.assertTrue(Path(paths["json_path"]).exists())
            self.assertTrue(Path(paths["markdown_path"]).exists())


if __name__ == "__main__":
    unittest.main()
