from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from tests.operator_helpers import write_text


def _write_model_config(root: Path, body: str) -> None:
    write_text(root / "ci" / "scripts" / "common" / "models_build_config.yaml", body.strip() + "\n")


def _idcevo_config(*names: str) -> str:
    return "\n".join(
        f"""
- name: {name}
  brand: BMW
  type: retarget
  target: PINT
""".strip()
        for name in names
    )


def _idc23_config(*names: str) -> str:
    return "\n".join(
        f"""
- name: {name}
  brand: BMW
  type: build
  hmi:
    interface_version: 12
""".strip()
        for name in names
    )


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


class TestScreenshotCapture(unittest.TestCase):
    def test_capture_command_prefers_car_manager_screenshots_with_diff(self) -> None:
        from sg_preflight.screenshot_capture import resolve_screenshot_capture_command

        with tempfile.TemporaryDirectory() as temp_dir:
            bmw_root = Path(temp_dir) / "digital-3d-car-models"
            script = bmw_root / "ci" / "scripts" / "car_manager.py"
            write_text(script, "print('fixture')\n")
            _write_model_config(bmw_root, _idcevo_config("G70_EVO"))

            payload = resolve_screenshot_capture_command(profile_id="G70", bmw_root=bmw_root)

        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["strategy"], "car_manager_screenshots")
        self.assertEqual(payload["lane"], "idc_evo")
        self.assertEqual(payload["profile_id"], "G70")
        self.assertEqual(payload["bmw_profile_id"], "G70_EVO")
        self.assertEqual(payload["command"][-3:], ["screenshots", "--diff", "G70_EVO"])
        self.assertEqual(Path(payload["script_path"]).name, "car_manager.py")

    def test_capture_command_routes_idc23_to_assets_worktree_main_screenshots(self) -> None:
        from sg_preflight.screenshot_capture import resolve_screenshot_capture_command

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bmw_root = root / "digital-3d-car-models-master"
            idc23_root = root / "digital-3d-car-models-idc23"
            _write_model_config(bmw_root, _idc23_config("F70"))
            script = idc23_root / "ci" / "scripts" / "test" / "main.py"
            write_text(script, "print('fixture')\n")
            (idc23_root / "cars" / "BMW" / "_Shared").mkdir(parents=True)
            (idc23_root / "cars" / "BMW" / "F70").mkdir(parents=True)

            with mock.patch.dict(os.environ, {"Digital-3D-Car-Repo-IDC23": str(idc23_root)}):
                payload = resolve_screenshot_capture_command(profile_id="F70", bmw_root=bmw_root)

        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["strategy"], "idc23_test_main_screenshots")
        self.assertEqual(payload["lane"], "idc_23")
        self.assertEqual(payload["profile_id"], "F70")
        self.assertEqual(payload["bmw_profile_id"], "F70")
        self.assertEqual(payload["command"][-3:], ["screenshots", "--diff", "F70"])
        self.assertEqual(Path(payload["script_path"]).name, "main.py")
        self.assertEqual(Path(payload["cwd"]).resolve(), idc23_root.resolve())

    def test_capture_command_prefers_registered_python_path(self) -> None:
        from sg_preflight.screenshot_capture import resolve_screenshot_capture_command

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bmw_root = root / "digital-3d-car-models"
            script = bmw_root / "ci" / "scripts" / "car_manager.py"
            python_path = root / "tools" / "python.exe"
            write_text(script, "print('fixture')\n")
            _write_model_config(bmw_root, _idc23_config("F70"))
            idc23_root = root / "digital-3d-car-models-idc23"
            write_text(idc23_root / "ci" / "scripts" / "test" / "main.py", "print('fixture')\n")
            (idc23_root / "cars" / "BMW" / "_Shared").mkdir(parents=True)
            (idc23_root / "cars" / "BMW" / "F70").mkdir(parents=True)
            write_text(python_path, "fixture\n")
            write_text(
                root / "operator_state" / "dependency_onboarding.json",
                json.dumps({"registered_paths": {"bmw_pipeline_python": str(python_path)}}),
            )

            with mock.patch.dict(os.environ, {"Digital-3D-Car-Repo-IDC23": str(idc23_root)}):
                payload = resolve_screenshot_capture_command(profile_id="F70", bmw_root=bmw_root, workspace=root)

        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["command"][0], str(python_path.resolve()))
        self.assertEqual(payload["command"][-3:], ["screenshots", "--diff", "F70"])

    @unittest.skipUnless(
        os.environ.get("SGFX_REAL_BMW_PIPELINE_AVAILABLE") == "1",
        "real BMW pipeline smoke skipped; set SGFX_REAL_BMW_PIPELINE_AVAILABLE=1 to run",
    )
    def test_real_bmw_pipeline_screenshot_dry_run_uses_resolved_profile(self) -> None:
        from sg_preflight.screenshot_capture import resolve_screenshot_capture_command

        bmw_root = Path(os.environ.get("Digital-3D-Car-Repo", r"C:\3D Car git\digital-3d-car-models"))
        if not (bmw_root / "ci" / "scripts" / "car_manager.py").is_file():
            self.skipTest(f"BMW car_manager.py not found under {bmw_root}")

        payload = resolve_screenshot_capture_command(profile_id="G65", bmw_root=bmw_root)
        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["bmw_profile_id"], "G65_EVO")
        command = list(payload["command"])
        command.insert(-1, "--dry-run")
        completed = subprocess.run(
            command,
            cwd=str(payload["cwd"]),
            capture_output=True,
            text=True,
            timeout=180,
        )
        self.assertEqual(
            completed.returncode,
            0,
            msg=(completed.stdout or "") + "\n" + (completed.stderr or ""),
        )

    def test_capture_preflight_uses_registered_dependency_paths(self) -> None:
        from sg_preflight import screenshot_capture as capture

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bmw_root = root / "digital-3d-car-models"
            write_text(bmw_root / "ci" / "scripts" / "car_manager.py", "print('fixture')\n")
            _write_model_config(bmw_root, _idcevo_config("G70_EVO"))
            (bmw_root / "cars" / "BMW" / "G70_EVO" / "export" / "tests").mkdir(parents=True)
            registered_paths = {
                "digital_3d_car_repo": bmw_root,
                "bmw_pipeline_python": root / "tools" / "python.exe",
                "raco_headless": root / "tools" / "RaCoHeadless.exe",
                "blender": root / "tools" / "blender.exe",
            }
            for path in registered_paths.values():
                if path.suffix:
                    write_text(path, "fixture\n")
            write_text(
                root / "operator_state" / "dependency_onboarding.json",
                json.dumps({"registered_paths": {key: str(path) for key, path in registered_paths.items()}}),
            )

            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch("sg_preflight.delivery_workbook_generation._find_executable", return_value=""):
                    payload = capture.check_screenshot_capture_environment(
                        profile_id="G70",
                        workspace=root,
                        min_free_bytes=1,
                    )

        checks = {item["key"]: item for item in payload["checks"]}
        self.assertTrue(payload["can_run"])
        self.assertEqual(checks["digital_3d_car_repo"]["status"], "available")
        self.assertEqual(checks["bmw_pipeline_python"]["status"], "available")
        self.assertEqual(checks["raco_headless"]["status"], "available")
        self.assertEqual(checks["blender"]["status"], "available")
        self.assertEqual(checks["bmw_screenshot_script"]["status"], "available")
        self.assertIn("actual/diff", payload["confirmation_message"])

    def test_start_capture_requires_operator_confirmation(self) -> None:
        from sg_preflight.screenshot_capture import start_screenshot_capture

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ValueError):
                start_screenshot_capture(
                    profile_id="G70",
                    workspace=Path(temp_dir),
                    operator_confirmed=False,
                )

    def test_poll_capture_marks_available_after_actual_or_diff_output_exists(self) -> None:
        from sg_preflight import screenshot_capture as capture

        # wrapper-layer-only: subprocess.Popen is mocked; the real subprocess smoke is gated above.
        fake_process = _FakeProcess(returncode=0)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bmw_root = root / "digital-3d-car-models"
            tests_root = bmw_root / "cars" / "BMW" / "G70_EVO" / "export" / "tests"
            write_text(bmw_root / "ci" / "scripts" / "car_manager.py", "print('fixture')\n")
            _write_model_config(bmw_root, _idcevo_config("G70_EVO"))
            write_text(tests_root / "actuals" / "front.png", "fake\n")
            with mock.patch.dict(os.environ, {"Digital-3D-Car-Repo": str(bmw_root)}):
                with mock.patch(
                    "sg_preflight.delivery_workbook_generation._find_executable",
                    return_value=r"C:\tools\tool.exe",
                ):
                    with mock.patch.object(capture.subprocess, "Popen", return_value=fake_process) as popen:
                        job = capture.start_screenshot_capture(
                            profile_id="G70",
                            workspace=root,
                            operator_confirmed=True,
                        )
                        result = capture.poll_screenshot_capture(job)

        popen.assert_called_once()
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["actual_count"], 1)
        self.assertFalse(result["is_approval"])
        self.assertTrue(result["recorded_by_tool"])
        self.assertIn("car_manager.py", " ".join(result["command"]))
        self.assertEqual(result["command"][-1], "G70_EVO")

    def test_poll_capture_keeps_diff_evidence_available_when_bmw_exits_nonzero(self) -> None:
        from sg_preflight import screenshot_capture as capture

        # wrapper-layer-only: subprocess.Popen is mocked; the real subprocess smoke is gated above.
        fake_process = _FakeProcess(returncode=1)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bmw_root = root / "digital-3d-car-models"
            tests_root = bmw_root / "cars" / "BMW" / "G65_EVO" / "export" / "tests"
            write_text(bmw_root / "ci" / "scripts" / "car_manager.py", "print('fixture')\n")
            _write_model_config(bmw_root, _idcevo_config("G65_EVO"))
            write_text(tests_root / "expected" / "front.png", "fake\n")
            write_text(tests_root / "actuals" / "front.png", "fake\n")
            write_text(tests_root / "diff" / "front_color.png", "fake\n")
            with mock.patch.dict(os.environ, {"Digital-3D-Car-Repo": str(bmw_root)}):
                with mock.patch(
                    "sg_preflight.delivery_workbook_generation._find_executable",
                    return_value=r"C:\tools\tool.exe",
                ):
                    with mock.patch.object(capture.subprocess, "Popen", return_value=fake_process):
                        job = capture.start_screenshot_capture(
                            profile_id="G65",
                            workspace=root,
                            operator_confirmed=True,
                        )
                        result = capture.poll_screenshot_capture(job)

        self.assertIsNotNone(result)
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["actual_count"], 1)
        self.assertEqual(result["diff_count"], 1)
        self.assertTrue(result["data_available"])
        self.assertIn("actual/diff evidence", result["summary"])
        self.assertIn("Manual review remains required", result["summary"])
        self.assertNotIn("approval", result["summary"].lower())

    def test_poll_capture_reports_live_stdout_tail_and_file_activity(self) -> None:
        from sg_preflight import screenshot_capture as capture

        # wrapper-layer-only: subprocess.Popen is mocked; the real subprocess smoke is gated above.
        fake_process = _FakeProcess(returncode=None)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bmw_root = root / "digital-3d-car-models"
            tests_root = bmw_root / "cars" / "BMW" / "G70_EVO" / "export" / "tests"
            write_text(bmw_root / "ci" / "scripts" / "car_manager.py", "print('fixture')\n")
            _write_model_config(bmw_root, _idcevo_config("G70_EVO"))
            (tests_root / "actuals").mkdir(parents=True)
            with mock.patch.dict(os.environ, {"Digital-3D-Car-Repo": str(bmw_root)}):
                with mock.patch(
                    "sg_preflight.delivery_workbook_generation._find_executable",
                    return_value=r"C:\tools\tool.exe",
                ):
                    with mock.patch.object(capture.subprocess, "Popen", return_value=fake_process):
                        job = capture.start_screenshot_capture(
                            profile_id="G70",
                            workspace=root,
                            operator_confirmed=True,
                        )
                        write_text(tests_root / "actuals" / "front.png", "fake\n")
                        write_text(job.stdout_path, "\n".join(f"line {index:02d}" for index in range(25)) + "\n")
                        result = capture.poll_screenshot_capture(job)

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "running")
        self.assertFalse(result["completed"])
        self.assertEqual(result["typical_range"], "typical 2-10 min")
        self.assertEqual(result["stdout_tail_lines"][0], "line 05")
        self.assertEqual(result["stdout_tail_lines"][-1], "line 24")
        self.assertEqual(result["file_activity"][0]["relative_path"], "actuals/front.png")
        self.assertFalse(result["is_approval"])
        self.assertTrue(result["recorded_by_tool"])


if __name__ == "__main__":
    unittest.main()
