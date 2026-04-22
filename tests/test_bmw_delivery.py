from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from sg_preflight.bmw_delivery import discover_bmw_models_repo, inspect_bmw_screenshot_surface
from sg_preflight.services import prerequisite_status
from tests.operator_helpers import write_text


class TestBmwDelivery(unittest.TestCase):
    def test_discover_bmw_models_repo_prefers_repo_local_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "digital-3d-car-models"
            write_text(repo_root / "ci" / "scripts" / "README.md", "fixture\n")

            detected = discover_bmw_models_repo(root)

            self.assertEqual(detected.resolve(), repo_root.resolve())

    def test_inspect_bmw_screenshot_surface_reports_empty_payload_truthfully(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "digital-3d-car-models"
            sg_project_root = root / "repositories" / "trunk" / "Cars_IDCevo" / "BMW" / "G50"
            tests_root = repo_root / "cars" / "BMW" / "G50_EVO" / "export" / "tests"

            write_text(repo_root / "ci" / "scripts" / "README.md", "fixture\n")
            write_text(repo_root / "ci" / "scripts" / "car_manager.py", "print('fixture')\n")
            write_text(tests_root / "test_config_tmp.lua", "-- fixture\n")
            (tests_root / "actuals").mkdir(parents=True, exist_ok=True)
            (tests_root / "diff").mkdir(parents=True, exist_ok=True)

            surface = inspect_bmw_screenshot_surface("G50", workspace_root=root, sg_project_root=sg_project_root)

            self.assertEqual(surface.bmw_profile_id, "G50_EVO")
            self.assertEqual(surface.actual_count, 0)
            self.assertEqual(surface.diff_count, 0)
            self.assertFalse(surface.sg_expected_root)
            self.assertIn("test_config_tmp.lua", surface.test_config_path)
            self.assertTrue(any("no screenshot payload" in note.lower() for note in surface.notes))

    def test_prerequisite_status_exposes_repo_local_bmw_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "digital-3d-car-models"
            write_text(repo_root / "ci" / "scripts" / "README.md", "fixture\n")
            write_text(repo_root / "ci" / "scripts" / "car_manager.py", "print('fixture')\n")

            status_map = {item["key"]: item for item in prerequisite_status(root)}

            self.assertEqual(status_map["bmw_models_repo"]["status"], "available")
            self.assertEqual(status_map["bmw_car_manager_script"]["status"], "available")
            self.assertEqual(Path(status_map["bmw_models_repo"]["path"]).resolve(), repo_root.resolve())


if __name__ == "__main__":
    unittest.main()
