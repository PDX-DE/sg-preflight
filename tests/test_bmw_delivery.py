from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from sg_preflight.bmw_delivery import (
    detect_lane,
    discover_bmw_models_repo,
    inspect_bmw_screenshot_surface,
    load_bmw_registry,
    read_bmw_screenshot_state,
    resolve_svn_profile_id,
)
from sg_preflight.services import prerequisite_status
from tests.operator_helpers import write_text


class TestBmwDelivery(unittest.TestCase):
    def _write_registry_snapshot(self, root: Path) -> None:
        records: list[str] = []
        for name in ["F70", *[f"B{index:02d}" for index in range(16)]]:
            records.append(
                f"""
- name: {name}
  brand: BMW
  type: build
  hmi:
    interface_version: 12
""".strip()
            )
        for name in ["G50_EVO", *[f"E{index:02d}_EVO" for index in range(8)]]:
            records.append(
                f"""
- name: {name}
  brand: BMW
  type: build
  hmi:
    interface_version: 24
""".strip()
            )
        for name in ["U25", "F66"]:
            records.append(
                f"""
- name: {name}
  brand: MINI
  type: build
  hmi:
    interface_version: 12
""".strip()
            )
        for name in ["G58_EVO", *[f"R{index:02d}_EVO" for index in range(47)]]:
            records.append(
                f"""
- name: {name}
  brand: BMW
  type: retarget
  target: PINT
""".strip()
            )
        write_text(root / "ci" / "scripts" / "common" / "models_build_config.yaml", "\n\n".join(records) + "\n")

    def test_load_bmw_registry_parses_76_model_snapshot_with_lanes_and_brands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_registry_snapshot(root)

            entries = load_bmw_registry(root)

        self.assertEqual(len(entries), 76)
        self.assertEqual(len({entry.profile_id for entry in entries}), 76)
        by_id = {entry.profile_id: entry for entry in entries}
        self.assertEqual(by_id["F70"].bmw_profile_id, "F70")
        self.assertEqual(by_id["F70"].lane, "idc_23")
        self.assertTrue(by_id["F70"].active_build)
        self.assertEqual(by_id["G50"].bmw_profile_id, "G50_EVO")
        self.assertEqual(by_id["G50"].lane, "idc_evo")
        self.assertEqual(by_id["G58"].bmw_profile_id, "G58_EVO")
        self.assertEqual(by_id["G58"].model_type, "retarget")
        self.assertEqual(by_id["G58"].target, "PINT")
        self.assertFalse(by_id["G58"].active_build)
        self.assertEqual(by_id["MINI_U25"].brand, "MINI")
        self.assertEqual(by_id["MINI_U25"].bmw_profile_id, "U25")

    def test_detect_lane_reads_bmw_model_config_source_of_truth(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "ci" / "scripts" / "common" / "models_build_config.yaml"
            write_text(
                config,
                """
- name: F70
  brand: BMW
  type: build
  hmi:
    interface_version: 12

- name: PINT
  brand: BMW
  type: build
  hmi:
    interface_version: 24

- name: G58_EVO
  brand: BMW
  type: retarget
  target: PINT
""".strip()
                + "\n",
            )

            self.assertEqual(detect_lane("F70", bmw_root=root), "idc_23")
            self.assertEqual(detect_lane("PINT", bmw_root=root), "idc_evo")
            self.assertEqual(detect_lane("G58", bmw_root=root), "idc_evo")
            self.assertEqual(detect_lane("UNKNOWN", bmw_root=root), "unknown")

    def test_detect_lane_returns_unknown_when_model_config_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertEqual(detect_lane("F70", bmw_root=Path(temp_dir)), "unknown")

    def test_resolve_svn_profile_id_strips_evo_suffix_only_for_svn_paths(self) -> None:
        self.assertEqual(resolve_svn_profile_id("G65_EVO"), "G65")
        self.assertEqual(resolve_svn_profile_id("g70"), "G70")
        self.assertEqual(resolve_svn_profile_id("PINT_SUV"), "PINT_SUV")

    def test_discover_bmw_models_repo_prefers_repo_local_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "digital-3d-car-models"
            write_text(repo_root / "ci" / "scripts" / "README.md", "fixture\n")

            detected = discover_bmw_models_repo(root)

            self.assertEqual(detected.resolve(), repo_root.resolve())

    def test_discover_bmw_models_repo_accepts_delivery_tool_env_var(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "Digital-3D-Car-Repo"
            write_text(repo_root / "ci" / "scripts" / "README.md", "fixture\n")

            with unittest.mock.patch.dict("os.environ", {"Digital-3D-Car-Repo": str(repo_root)}):
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

    def test_read_bmw_screenshot_state_counts_expected_actuals_diff_and_disabled_tests(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "digital-3d-car-models"
            tests_root = repo_root / "cars" / "BMW" / "G65_EVO" / "export" / "tests"
            write_text(repo_root / "ci" / "scripts" / "README.md", "fixture\n")
            write_text(tests_root / "expected" / "front.png", "fake\n")
            write_text(tests_root / "expected" / "rear.jpg", "fake\n")
            write_text(tests_root / "actuals" / "front.png", "fake\n")
            write_text(tests_root / "diff" / "rear.png", "fake\n")
            write_text(
                tests_root / "test_config.lua",
                'disableTest("irrelevant_trimline")\n',
            )

            payload = read_bmw_screenshot_state("G65", workspace=root)

            self.assertEqual(payload["status"], "available")
            self.assertEqual(payload["profile_id"], "G65")
            self.assertEqual(payload["matched_profile_id"], "G65_EVO")
            self.assertEqual(payload["expected_count"], 2)
            self.assertEqual(payload["actual_count"], 1)
            self.assertEqual(payload["diff_count"], 1)
            self.assertEqual(payload["disabled_test_count"], 1)
            self.assertEqual(payload["sg_expected_count"], 0)
            self.assertFalse(payload["is_approval"])
            self.assertIn("Read-only screenshot test state", payload["note"])
            self.assertNotIn("approved", payload["note"].lower())

    def test_read_bmw_screenshot_state_resolves_mini_profile_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "digital-3d-car-models"
            tests_root = repo_root / "cars" / "MINI" / "F66" / "export" / "tests"
            write_text(repo_root / "ci" / "scripts" / "README.md", "fixture\n")
            write_text(tests_root / "expected" / "front.png", "fake\n")
            write_text(tests_root / "actuals" / "front.png", "fake\n")
            write_text(tests_root / "test_config.lua", 'disableTest("mini_variant")\n')

            payload = read_bmw_screenshot_state("F66", workspace=root)

            self.assertEqual(payload["status"], "available")
            self.assertEqual(payload["brand"], "MINI")
            self.assertEqual(payload["matched_profile_id"], "F66")
            self.assertEqual(payload["expected_count"], 1)
            self.assertEqual(payload["actual_count"], 1)
            self.assertEqual(payload["disabled_test_count"], 1)
            self.assertEqual(payload["sg_expected_count"], 0)
            self.assertTrue(any("MINI export/tests surface" in note for note in payload["notes"]))
            self.assertFalse(payload["is_approval"])
            self.assertNotIn("approved", payload["note"].lower())

    def test_read_bmw_screenshot_state_uses_retarget_target_surface(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "digital-3d-car-models"
            write_text(
                repo_root / "ci" / "scripts" / "common" / "models_build_config.yaml",
                """
- name: G58_EVO
  brand: BMW
  type: retarget
  target: PINT
""".strip()
                + "\n",
            )
            tests_root = repo_root / "cars" / "BMW" / "PINT" / "export" / "tests"
            write_text(tests_root / "expected" / "front.png", "fake\n")
            write_text(tests_root / "actuals" / "front.png", "fake\n")
            write_text(tests_root / "diff" / "front.png", "fake\n")

            payload = read_bmw_screenshot_state("G58", workspace=root, bmw_root=repo_root)

        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["matched_profile_id"], "G58_EVO")
        self.assertTrue(payload["car_root"].endswith(str(Path("cars") / "BMW" / "PINT")))
        self.assertEqual(payload["expected_count"], 1)
        self.assertEqual(payload["actual_count"], 1)
        self.assertEqual(payload["diff_count"], 1)

    def test_read_bmw_screenshot_state_discovers_latest_sg_prespectives_tests_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old_root = (
                root
                / ".pdx"
                / "checkers"
                / "prespectivesTests"
                / "G70"
                / "perspectives_CID_2to1"
                / "20260401"
            )
            latest_root = (
                root
                / ".pdx"
                / "checkers"
                / "prespectivesTests"
                / "G70"
                / "perspectives_CID_2to1"
                / "20260520"
            )
            write_text(old_root / "old.png", "fake\n")
            write_text(latest_root / "front.png", "fake\n")
            write_text(latest_root / "rear.jpg", "fake\n")
            write_text(latest_root / "comparison" / "front_diff.png", "fake\n")

            payload = read_bmw_screenshot_state("G70", workspace=root)

        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["sg_perspectives_screenshot_count"], 3)
        self.assertEqual(payload["sg_perspectives_comparison_count"], 1)
        self.assertTrue(payload["sg_perspectives_latest_folder"].endswith("20260520"))
        self.assertIn("SG prespectivesTests latest folder", payload["summary"])
        self.assertTrue(any("prespectivesTests output is present" in note for note in payload["notes"]))
        self.assertFalse(payload["is_approval"])

    def test_read_bmw_screenshot_state_returns_zero_when_no_sg_prespectives_folder_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "digital-3d-car-models"
            tests_root = repo_root / "cars" / "BMW" / "G65_EVO" / "export" / "tests"
            write_text(tests_root / "expected" / "front.png", "fake\n")
            write_text(root / "unrelated.png", "fake\n")

            payload = read_bmw_screenshot_state("G65", workspace=root, sg_project_root=root)

        self.assertEqual(payload["status"], "incomplete")
        self.assertTrue(payload["data_available"])
        self.assertEqual(payload["expected_count"], 1)
        self.assertEqual(payload["sg_perspectives_screenshot_count"], 0)
        self.assertEqual(payload["sg_perspectives_comparison_count"], 0)
        self.assertEqual(payload["sg_perspectives_root"], "")
        self.assertEqual(payload["sg_perspectives_latest_folder"], "")
        self.assertNotIn("prespectivesTests latest folder", payload["summary"])
        self.assertIn("No actual screenshots captured yet", payload["summary"])
        self.assertTrue(any("No SG prespectivesTests output" in note for note in payload["notes"]))

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
