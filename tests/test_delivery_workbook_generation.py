from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tests.operator_helpers import write_text


class _FakeProcess:
    def __init__(self, returncode: int | None = 0) -> None:
        self.returncode = returncode
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: int | None = None) -> int | None:
        return self.returncode


class TestDeliveryWorkbookGeneration(unittest.TestCase):
    def test_tool_check_prefers_registered_raco_path_when_not_on_path(self) -> None:
        from sg_preflight import delivery_workbook_generation as generation

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            registered = root / "tools" / "RamsesComposer.exe"
            write_text(registered, "fixture\n")
            state_path = root / "operator_state" / "dependency_onboarding.json"
            write_text(
                state_path,
                json.dumps({"registered_paths": {"raco_gui": str(registered)}}),
            )

            with mock.patch("sg_preflight.delivery_workbook_generation._find_executable", return_value=""):
                payload = generation._tool_check("raco", "RaCo", workspace=root)

        self.assertEqual(payload["key"], "raco")
        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["path"], str(registered.resolve()))
        self.assertIn("dependency setup registration", payload["detail"])

    def test_preflight_prefers_registered_dependency_paths(self) -> None:
        from sg_preflight import delivery_workbook_generation as generation

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bmw_root = root / "digital-3d-car-models"
            (bmw_root / "cars" / "BMW").mkdir(parents=True)
            registered_paths = {
                "digital_3d_car_repo": bmw_root,
                "bmw_pipeline_python": root / "tools" / "python.exe",
                "raco_gui": root / "tools" / "RamsesComposer.exe",
                "raco_headless": root / "tools" / "RaCoHeadless.exe",
                "blender": root / "tools" / "blender.exe",
            }
            for path in registered_paths.values():
                if path.suffix:
                    write_text(path, "fixture\n")
            state_path = root / "operator_state" / "dependency_onboarding.json"
            write_text(
                state_path,
                json.dumps({"registered_paths": {key: str(path) for key, path in registered_paths.items()}}),
            )

            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch("sg_preflight.delivery_workbook_generation._find_executable", return_value=""):
                    with mock.patch.object(generation.shutil, "which", return_value=""):
                        payload = generation.check_delivery_workbook_generation_environment(
                            profile_id="G70",
                            workspace=root,
                            min_free_bytes=1,
                        )

        checks = {item["key"]: item for item in payload["checks"]}
        self.assertTrue(payload["can_run"])
        self.assertEqual(checks["digital_3d_car_repo"]["status"], "available")
        self.assertEqual(checks["bmw_pipeline_python"]["status"], "available")
        self.assertEqual(checks["raco"]["status"], "available")
        self.assertEqual(checks["raco_headless"]["status"], "available")
        self.assertEqual(checks["blender"]["status"], "available")

    def test_preflight_blocks_when_digital_3d_car_repo_env_var_is_missing(self) -> None:
        from sg_preflight.delivery_workbook_generation import check_delivery_workbook_generation_environment

        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch(
                    "sg_preflight.delivery_workbook_generation._find_executable",
                    return_value=r"C:\tools\tool.exe",
                ):
                    payload = check_delivery_workbook_generation_environment(
                        profile_id="G70",
                        workspace=Path(temp_dir),
                        min_free_bytes=1,
                    )

        self.assertFalse(payload["can_run"])
        self.assertEqual(payload["status"], "failed")
        checks = {item["key"]: item for item in payload["checks"]}
        self.assertEqual(checks["digital_3d_car_repo"]["status"], "missing")
        self.assertEqual(checks["raco_headless"]["status"], "available")
        self.assertIn("Digital-3D-Car-Repo", checks["digital_3d_car_repo"]["detail"])

    def test_preflight_passes_with_bmw_repo_tools_and_disk_headroom(self) -> None:
        from sg_preflight.delivery_workbook_generation import check_delivery_workbook_generation_environment

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bmw_root = root / "digital-3d-car-models"
            (bmw_root / "cars" / "BMW").mkdir(parents=True)
            with mock.patch.dict(os.environ, {"Digital-3D-Car-Repo": str(bmw_root)}):
                with mock.patch(
                    "sg_preflight.delivery_workbook_generation._find_executable",
                    return_value=r"C:\tools\tool.exe",
                ):
                    payload = check_delivery_workbook_generation_environment(
                        profile_id="g70",
                        workspace=root,
                        min_free_bytes=1,
                    )

        self.assertTrue(payload["can_run"])
        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["profile_id"], "G70")
        self.assertIn("This will run the BMW pipeline for G70", payload["confirmation_message"])
        self.assertIn("Cars", payload["target_write_path"])
        self.assertTrue(all(item["status"] == "available" for item in payload["checks"]))

    def test_generation_command_prefers_car_manager_export(self) -> None:
        from sg_preflight.delivery_workbook_generation import resolve_delivery_workbook_generation_command

        with tempfile.TemporaryDirectory() as temp_dir:
            bmw_root = Path(temp_dir) / "digital-3d-car-models"
            script = bmw_root / "ci" / "scripts" / "car_manager.py"
            write_text(script, "print('fixture')\n")

            payload = resolve_delivery_workbook_generation_command(profile_id="G70", bmw_root=bmw_root)

        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["strategy"], "car_manager_export")
        self.assertEqual(payload["command"][-2:], ["export", "G70"])
        self.assertEqual(Path(payload["script_path"]).name, "car_manager.py")

    def test_generation_command_falls_back_to_legacy_test_main_export(self) -> None:
        from sg_preflight.delivery_workbook_generation import resolve_delivery_workbook_generation_command

        with tempfile.TemporaryDirectory() as temp_dir:
            bmw_root = Path(temp_dir) / "digital-3d-car-models"
            script = bmw_root / "ci" / "scripts" / "test" / "main.py"
            write_text(script, "print('fixture')\n")

            payload = resolve_delivery_workbook_generation_command(profile_id="NA8", bmw_root=bmw_root)

        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["strategy"], "legacy_test_main_export")
        self.assertEqual(payload["command"][-2:], ["export", "NA8"])
        self.assertEqual(Path(payload["script_path"]).name, "main.py")

    def test_generation_command_uses_python_launcher_when_frozen(self) -> None:
        from sg_preflight import delivery_workbook_generation as generation

        with tempfile.TemporaryDirectory() as temp_dir:
            bmw_root = Path(temp_dir) / "digital-3d-car-models"
            script = bmw_root / "ci" / "scripts" / "car_manager.py"
            write_text(script, "print('fixture')\n")

            def fake_which(executable_name: str) -> str:
                return r"C:\Windows\py.exe" if executable_name == "py.exe" else ""

            with mock.patch.object(generation.sys, "frozen", True, create=True):
                with mock.patch.object(generation.sys, "executable", r"C:\bundle\sgfx-preflight.exe"):
                    with mock.patch.object(generation.shutil, "which", side_effect=fake_which):
                        payload = generation.resolve_delivery_workbook_generation_command(
                            profile_id="G70",
                            bmw_root=bmw_root,
                        )

        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["command"][0], r"C:\Windows\py.exe")
        self.assertNotEqual(payload["command"][0], r"C:\bundle\sgfx-preflight.exe")
        self.assertEqual(payload["command"][-2:], ["export", "G70"])

    def test_generation_command_prefers_registered_python_path(self) -> None:
        from sg_preflight.delivery_workbook_generation import resolve_delivery_workbook_generation_command

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bmw_root = root / "digital-3d-car-models"
            script = bmw_root / "ci" / "scripts" / "car_manager.py"
            python_path = root / "tools" / "python.exe"
            write_text(script, "print('fixture')\n")
            write_text(python_path, "fixture\n")
            write_text(
                root / "operator_state" / "dependency_onboarding.json",
                json.dumps({"registered_paths": {"bmw_pipeline_python": str(python_path)}}),
            )

            payload = resolve_delivery_workbook_generation_command(
                profile_id="G70",
                bmw_root=bmw_root,
                workspace=root,
            )

        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["command"][0], str(python_path.resolve()))
        self.assertEqual(payload["command"][-2:], ["export", "G70"])

    def test_start_generation_requires_operator_confirmation(self) -> None:
        from sg_preflight.delivery_workbook_generation import start_delivery_workbook_generation

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ValueError):
                start_delivery_workbook_generation(
                    profile_id="G70",
                    workspace=Path(temp_dir),
                    operator_confirmed=False,
                )

    def test_poll_generation_marks_available_only_after_delivery_reader_returns_available(self) -> None:
        from sg_preflight import delivery_workbook_generation as generation

        fake_process = _FakeProcess(returncode=0)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bmw_root = root / "digital-3d-car-models"
            (bmw_root / "cars" / "BMW").mkdir(parents=True)
            write_text(bmw_root / "ci" / "scripts" / "car_manager.py", "print('fixture')\n")
            with mock.patch.dict(os.environ, {"Digital-3D-Car-Repo": str(bmw_root)}):
                with mock.patch(
                    "sg_preflight.delivery_workbook_generation._find_executable",
                    return_value=r"C:\tools\tool.exe",
                ):
                    with mock.patch.object(generation.subprocess, "Popen", return_value=fake_process) as popen:
                        with mock.patch.object(
                            generation,
                            "read_delivery_checklist",
                            return_value={
                                "status": "available",
                                "summary": "Delivery checklist G70: generated workbook found.",
                            },
                        ):
                            job = generation.start_delivery_workbook_generation(
                                profile_id="G70",
                                workspace=root,
                                operator_confirmed=True,
                            )
                            result = generation.poll_delivery_workbook_generation(job)

        popen.assert_called_once()
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["checklist_status"], "available")
        self.assertFalse(result["is_approval"])
        self.assertTrue(result["recorded_by_tool"])
        self.assertIn("car_manager.py", " ".join(result["command"]))

    def test_poll_generation_reports_live_stdout_tail_and_file_activity(self) -> None:
        from sg_preflight import delivery_workbook_generation as generation

        fake_process = _FakeProcess(returncode=None)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bmw_root = root / "digital-3d-car-models"
            (bmw_root / "cars" / "BMW").mkdir(parents=True)
            write_text(bmw_root / "ci" / "scripts" / "car_manager.py", "print('fixture')\n")
            with mock.patch.dict(os.environ, {"Digital-3D-Car-Repo": str(bmw_root)}):
                with mock.patch(
                    "sg_preflight.delivery_workbook_generation._find_executable",
                    return_value=r"C:\tools\tool.exe",
                ):
                    with mock.patch.object(generation.subprocess, "Popen", return_value=fake_process):
                        job = generation.start_delivery_workbook_generation(
                            profile_id="G70",
                            workspace=root,
                            operator_confirmed=True,
                        )
                        output_file = root / "Cars" / "size_analysis" / "G70_20260521.xlsx"
                        write_text(output_file, "fake workbook\n")
                        write_text(
                            job.stdout_path,
                            "\n".join(f"line {index:02d}" for index in range(25)) + "\n",
                        )
                        result = generation.poll_delivery_workbook_generation(job)

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "running")
        self.assertFalse(result["completed"])
        self.assertEqual(result["exit_code"], None)
        self.assertEqual(result["typical_range"], "typical 1-10 min")
        self.assertEqual(result["stdout_tail_lines"][0], "line 05")
        self.assertEqual(result["stdout_tail_lines"][-1], "line 24")
        self.assertEqual(result["file_activity"][0]["relative_path"], "G70_20260521.xlsx")
        self.assertIn("G70_20260521.xlsx", result["file_activity"][0]["summary"])
        self.assertFalse(result["is_approval"])
        self.assertTrue(result["recorded_by_tool"])


if __name__ == "__main__":
    unittest.main()
