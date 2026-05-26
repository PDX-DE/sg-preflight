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


class TestDeliveryWorkbookGeneration(unittest.TestCase):
    def test_workbook_trigger_wraps_preflight_without_starting_generation(self) -> None:
        from sg_preflight import delivery_workbook_generation as generation

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bmw_root = root / "digital-3d-car-models"
            (bmw_root / "cars" / "BMW").mkdir(parents=True)
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch("sg_preflight.delivery_workbook_generation._find_executable", return_value=""):
                    payload = generation.build_delivery_workbook_trigger(
                        profile_id="G70",
                        workspace=root,
                        bmw_root=bmw_root,
                    )

        self.assertEqual(payload["status"], "available")
        self.assertFalse(payload["can_start"])
        self.assertFalse(payload["started"])
        self.assertTrue(payload["manual_review_required"])
        self.assertFalse(payload["records_operator_verdict"])
        self.assertFalse(payload["is_approval"])
        self.assertTrue(payload["blockers"])
        self.assertIn("Manual review remains required.", payload["guardrails"])
        markdown = generation.render_delivery_workbook_trigger_markdown(payload)
        self.assertIn("Delivery workbook trigger", markdown)
        self.assertIn("Manual review required: yes", markdown)
        self.assertIn("Decision: not approval", markdown)

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
            write_text(bmw_root / "ci" / "scripts" / "car_manager.py", "print('fixture')\n")
            _write_model_config(bmw_root, _idcevo_config("G70_EVO"))
            (bmw_root / "cars" / "BMW" / "G70_EVO").mkdir(parents=True)
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
        self.assertEqual(payload["status"], "unavailable")
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
            write_text(bmw_root / "ci" / "scripts" / "car_manager.py", "print('fixture')\n")
            _write_model_config(bmw_root, _idcevo_config("G70_EVO"))
            (bmw_root / "cars" / "BMW" / "G70_EVO").mkdir(parents=True)
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
        self.assertIn("out", payload["target_write_path"])
        self.assertIn("delivery-workbook", payload["target_write_path"])
        self.assertIn("Cars", payload["native_output_path"])
        self.assertIn("copies the generated workbook evidence", payload["confirmation_message"])
        self.assertTrue(all(item["status"] == "available" for item in payload["checks"]))

    def test_generation_command_prefers_car_manager_export(self) -> None:
        from sg_preflight.delivery_workbook_generation import resolve_delivery_workbook_generation_command

        with tempfile.TemporaryDirectory() as temp_dir:
            bmw_root = Path(temp_dir) / "digital-3d-car-models"
            script = bmw_root / "ci" / "scripts" / "car_manager.py"
            write_text(script, "print('fixture')\n")
            _write_model_config(bmw_root, _idcevo_config("G70_EVO"))
            (bmw_root / "cars" / "BMW" / "G70_EVO").mkdir(parents=True)

            payload = resolve_delivery_workbook_generation_command(profile_id="G70", bmw_root=bmw_root)

        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["strategy"], "car_manager_export")
        self.assertEqual(payload["lane"], "idc_evo")
        self.assertEqual(payload["profile_id"], "G70")
        self.assertEqual(payload["bmw_profile_id"], "G70_EVO")
        self.assertEqual(payload["command"][-2:], ["export", "G70_EVO"])
        self.assertEqual(Path(payload["script_path"]).name, "car_manager.py")

    def test_generation_command_routes_idc23_to_assets_worktree_test_main_export(self) -> None:
        from sg_preflight.delivery_workbook_generation import resolve_delivery_workbook_generation_command

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
                payload = resolve_delivery_workbook_generation_command(profile_id="F70", bmw_root=bmw_root)

        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["strategy"], "idc23_test_main_export")
        self.assertEqual(payload["lane"], "idc_23")
        self.assertEqual(payload["profile_id"], "F70")
        self.assertEqual(payload["bmw_profile_id"], "F70")
        self.assertEqual(payload["command"][-2:], ["export", "F70"])
        self.assertEqual(Path(payload["script_path"]).name, "main.py")
        self.assertEqual(Path(payload["cwd"]).resolve(), idc23_root.resolve())

    def test_generation_command_routes_idc23_from_dependency_registration(self) -> None:
        from sg_preflight.dependency_onboarding import record_dependency_path
        from sg_preflight.delivery_workbook_generation import resolve_delivery_workbook_generation_command

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bmw_root = root / "digital-3d-car-models-master"
            idc23_root = root / "digital-3d-car-models-idc23"
            _write_model_config(bmw_root, _idc23_config("F70"))
            write_text(idc23_root / "ci" / "scripts" / "test" / "main.py", "print('fixture')\n")
            (idc23_root / "cars" / "BMW" / "_Shared").mkdir(parents=True)
            (idc23_root / "cars" / "BMW" / "F70").mkdir(parents=True)
            record_dependency_path(workspace=root, key="digital_3d_car_repo_idc23", path=idc23_root)

            with mock.patch.dict(os.environ, {}, clear=True):
                payload = resolve_delivery_workbook_generation_command(
                    profile_id="F70",
                    bmw_root=bmw_root,
                    workspace=root,
                )

        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["strategy"], "idc23_test_main_export")
        self.assertEqual(Path(payload["cwd"]).resolve(), idc23_root.resolve())

    def test_generation_command_reports_missing_idc23_worktree(self) -> None:
        from sg_preflight.delivery_workbook_generation import resolve_delivery_workbook_generation_command

        with tempfile.TemporaryDirectory() as temp_dir:
            bmw_root = Path(temp_dir) / "digital-3d-car-models"
            _write_model_config(bmw_root, _idc23_config("F70"))

            with mock.patch.dict(os.environ, {}, clear=True):
                payload = resolve_delivery_workbook_generation_command(profile_id="F70", bmw_root=bmw_root)

        self.assertEqual(payload["status"], "unavailable")
        self.assertEqual(payload["lane"], "idc_23")
        self.assertIn("Digital-3D-Car-Repo-IDC23", payload["summary"])
        self.assertIn("assets/idc23", payload["remediation"])

    def test_generation_command_reports_registered_car_missing_from_lane_worktree(self) -> None:
        from sg_preflight.delivery_workbook_generation import resolve_delivery_workbook_generation_command

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bmw_root = root / "digital-3d-car-models-master"
            idc23_root = root / "digital-3d-car-models-idc23"
            _write_model_config(
                bmw_root,
                """
- name: U25
  brand: MINI
  type: build
  hmi:
    interface_version: 12
""",
            )
            write_text(idc23_root / "ci" / "scripts" / "test" / "main.py", "print('fixture')\n")
            (idc23_root / "cars" / "BMW" / "_Shared").mkdir(parents=True)

            with mock.patch.dict(os.environ, {"Digital-3D-Car-Repo-IDC23": str(idc23_root)}):
                payload = resolve_delivery_workbook_generation_command(profile_id="MINI_U25", bmw_root=bmw_root)

        self.assertEqual(payload["status"], "unavailable")
        self.assertEqual(payload["lane"], "idc_23")
        self.assertEqual(payload["bmw_profile_id"], "U25")
        self.assertIn("cars", payload["summary"])
        self.assertIn("MINI", payload["summary"])
        self.assertIn("Data-prep team operation", payload["summary"])

    def test_generation_command_uses_python_launcher_when_frozen(self) -> None:
        from sg_preflight import delivery_workbook_generation as generation

        with tempfile.TemporaryDirectory() as temp_dir:
            bmw_root = Path(temp_dir) / "digital-3d-car-models"
            script = bmw_root / "ci" / "scripts" / "car_manager.py"
            write_text(script, "print('fixture')\n")
            _write_model_config(bmw_root, _idcevo_config("G70_EVO"))
            (bmw_root / "cars" / "BMW" / "G70_EVO").mkdir(parents=True)

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
        self.assertEqual(payload["command"][-2:], ["export", "G70_EVO"])

    def test_generation_command_prefers_python_launcher_over_source_venv(self) -> None:
        from sg_preflight import delivery_workbook_generation as generation

        with tempfile.TemporaryDirectory() as temp_dir:
            bmw_root = Path(temp_dir) / "digital-3d-car-models"
            script = bmw_root / "ci" / "scripts" / "car_manager.py"
            write_text(script, "print('fixture')\n")
            _write_model_config(bmw_root, _idcevo_config("G70_EVO"))
            (bmw_root / "cars" / "BMW" / "G70_EVO").mkdir(parents=True)

            def fake_which(executable_name: str) -> str:
                return r"C:\Windows\py.exe" if executable_name == "py.exe" else ""

            with mock.patch.object(generation.sys, "frozen", False, create=True):
                with mock.patch.object(generation.sys, "executable", r"C:\sgfx\.venv\Scripts\python.exe"):
                    with mock.patch.object(generation.shutil, "which", side_effect=fake_which):
                        payload = generation.resolve_delivery_workbook_generation_command(
                            profile_id="G70",
                            bmw_root=bmw_root,
                        )

        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["command"][0], r"C:\Windows\py.exe")
        self.assertNotEqual(payload["command"][0], r"C:\sgfx\.venv\Scripts\python.exe")
        self.assertEqual(payload["command"][-2:], ["export", "G70_EVO"])

    def test_generation_command_prefers_registered_python_path(self) -> None:
        from sg_preflight.delivery_workbook_generation import resolve_delivery_workbook_generation_command

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bmw_root = root / "digital-3d-car-models"
            script = bmw_root / "ci" / "scripts" / "car_manager.py"
            python_path = root / "tools" / "python.exe"
            write_text(script, "print('fixture')\n")
            _write_model_config(bmw_root, _idcevo_config("G70_EVO"))
            (bmw_root / "cars" / "BMW" / "G70_EVO").mkdir(parents=True)
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
        self.assertEqual(payload["command"][-2:], ["export", "G70_EVO"])

    @unittest.skipUnless(
        os.environ.get("SGFX_REAL_BMW_PIPELINE_AVAILABLE") == "1",
        "real BMW pipeline smoke skipped; set SGFX_REAL_BMW_PIPELINE_AVAILABLE=1 to run",
    )
    def test_real_bmw_pipeline_export_dry_run_uses_resolved_profile(self) -> None:
        from sg_preflight.delivery_workbook_generation import resolve_delivery_workbook_generation_command

        bmw_root = Path(os.environ.get("Digital-3D-Car-Repo", r"C:\3D Car git\digital-3d-car-models"))
        if not (bmw_root / "ci" / "scripts" / "car_manager.py").is_file():
            self.skipTest(f"BMW car_manager.py not found under {bmw_root}")

        payload = resolve_delivery_workbook_generation_command(profile_id="G65", bmw_root=bmw_root)
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

        # wrapper-layer-only: subprocess.Popen is mocked; the real subprocess smoke is gated above.
        fake_process = _FakeProcess(returncode=0)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bmw_root = root / "digital-3d-car-models"
            (bmw_root / "cars" / "BMW").mkdir(parents=True)
            write_text(bmw_root / "ci" / "scripts" / "car_manager.py", "print('fixture')\n")
            _write_model_config(bmw_root, _idcevo_config("G70_EVO"))
            (bmw_root / "cars" / "BMW" / "G70_EVO").mkdir(parents=True)
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
        self.assertEqual(result["copied_evidence"]["status"], "recorded")
        self.assertEqual(result["copied_evidence"]["file_count"], 2)
        self.assertIn("delivery-workbook", result["sgfx_output_root"])
        self.assertIn("Cars", result["native_output_path"])
        self.assertFalse(result["is_approval"])
        self.assertTrue(result["recorded_by_tool"])
        self.assertIn("car_manager.py", " ".join(result["command"]))
        self.assertEqual(result["command"][-1], "G70_EVO")

    def test_poll_generation_reports_actionable_escalation_when_workbook_is_still_missing(self) -> None:
        from sg_preflight import delivery_workbook_generation as generation

        fake_process = _FakeProcess(returncode=0)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bmw_root = root / "digital-3d-car-models"
            (bmw_root / "cars" / "BMW").mkdir(parents=True)
            write_text(bmw_root / "ci" / "scripts" / "car_manager.py", "print('fixture')\n")
            _write_model_config(bmw_root, _idcevo_config("G70_EVO"))
            (bmw_root / "cars" / "BMW" / "G70_EVO").mkdir(parents=True)
            with mock.patch.dict(os.environ, {"Digital-3D-Car-Repo": str(bmw_root)}):
                with mock.patch(
                    "sg_preflight.delivery_workbook_generation._find_executable",
                    return_value=r"C:\tools\tool.exe",
                ):
                    with mock.patch.object(generation.subprocess, "Popen", return_value=fake_process):
                        with mock.patch.object(
                            generation,
                            "read_delivery_checklist",
                            return_value={"status": "unavailable", "summary": "no workbook"},
                        ):
                            job = generation.start_delivery_workbook_generation(
                                profile_id="G70",
                                workspace=root,
                                operator_confirmed=True,
                            )
                            result = generation.poll_delivery_workbook_generation(job)

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(
            result["escalation"]["expected_path"],
            r"C:\repositories\trunk\Cars\size_analysis\G70_*.xlsx",
        )
        self.assertIn("Delivery Checklist", result["summary"])
        self.assertIn("Decision: not approval", result["summary"])
        self.assertFalse(result["is_approval"])

    def test_poll_generation_copies_workbook_evidence_to_sgfx_output_root(self) -> None:
        from sg_preflight import delivery_workbook_generation as generation

        fake_process = _FakeProcess(returncode=0)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bmw_root = root / "digital-3d-car-models"
            workbook = root / "Cars" / "size_analysis" / "G70_20260524.xlsx"
            (bmw_root / "cars" / "BMW").mkdir(parents=True)
            write_text(bmw_root / "ci" / "scripts" / "car_manager.py", "print('fixture')\n")
            _write_model_config(bmw_root, _idcevo_config("G70_EVO"))
            (bmw_root / "cars" / "BMW" / "G70_EVO").mkdir(parents=True)
            write_text(workbook, "fake workbook\n")
            with mock.patch.dict(os.environ, {"Digital-3D-Car-Repo": str(bmw_root)}):
                with mock.patch(
                    "sg_preflight.delivery_workbook_generation._find_executable",
                    return_value=r"C:\tools\tool.exe",
                ):
                    with mock.patch.object(generation.subprocess, "Popen", return_value=fake_process):
                        with mock.patch.object(
                            generation,
                            "read_delivery_checklist",
                            return_value={
                                "status": "available",
                                "summary": "Delivery checklist G70: generated workbook found.",
                                "workbook_path": str(workbook),
                            },
                        ):
                            job = generation.start_delivery_workbook_generation(
                                profile_id="G70",
                                workspace=root,
                                operator_confirmed=True,
                            )
                            write_text(job.stdout_path, "stdout\n")
                            write_text(job.stderr_path, "")
                            result = generation.poll_delivery_workbook_generation(job)

        self.assertEqual(result["status"], "available")
        copied = result["copied_evidence"]
        self.assertEqual(copied["status"], "recorded")
        self.assertEqual(copied["file_count"], 3)
        copied_paths = [Path(item["path"]) for item in copied["files"]]
        self.assertTrue(any(path.name == "G70_20260524.xlsx" for path in copied_paths))
        self.assertTrue(any("out" in path.parts and "delivery-workbook" in path.parts for path in copied_paths))

    def test_poll_generation_reports_live_stdout_tail_and_file_activity(self) -> None:
        from sg_preflight import delivery_workbook_generation as generation

        # wrapper-layer-only: subprocess.Popen is mocked; the real subprocess smoke is gated above.
        fake_process = _FakeProcess(returncode=None)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bmw_root = root / "digital-3d-car-models"
            (bmw_root / "cars" / "BMW").mkdir(parents=True)
            write_text(bmw_root / "ci" / "scripts" / "car_manager.py", "print('fixture')\n")
            _write_model_config(bmw_root, _idcevo_config("G70_EVO"))
            (bmw_root / "cars" / "BMW" / "G70_EVO").mkdir(parents=True)
            with mock.patch.dict(os.environ, {"Digital-3D-Car-Repo": str(bmw_root)}):
                with mock.patch(
                    "sg_preflight.delivery_workbook_generation._find_executable",
                    return_value=r"C:\tools\tool.exe",
                ):
                    with mock.patch.object(generation.subprocess, "Popen", return_value=fake_process) as popen:
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
        self.assertEqual(popen.call_args.kwargs["env"]["PYTHONUNBUFFERED"], "1")
        self.assertEqual(popen.call_args.kwargs["env"]["PYTHONIOENCODING"], "utf-8")

    def test_poll_generation_streams_stdout_and_stderr_tail_lines(self) -> None:
        from sg_preflight import delivery_workbook_generation as generation

        fake_process = _FakeProcess(returncode=None)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bmw_root = root / "digital-3d-car-models"
            (bmw_root / "cars" / "BMW").mkdir(parents=True)
            write_text(bmw_root / "ci" / "scripts" / "car_manager.py", "print('fixture')\n")
            _write_model_config(bmw_root, _idcevo_config("G70_EVO"))
            (bmw_root / "cars" / "BMW" / "G70_EVO").mkdir(parents=True)
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
                        write_text(job.stdout_path, "Exporting G70_EVO\nGetting asset paths\n")
                        write_text(job.stderr_path, "Ramses warning: fixture\n")
                        result = generation.poll_delivery_workbook_generation(job)

        self.assertEqual(result["status"], "running")
        self.assertIn("Exporting G70_EVO", result["stdout_tail_lines"])
        self.assertIn("stderr: Ramses warning: fixture", result["stdout_tail_lines"])


if __name__ == "__main__":
    unittest.main()
