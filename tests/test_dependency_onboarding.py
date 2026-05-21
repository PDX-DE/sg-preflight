from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from tests.operator_helpers import write_text


class TestDependencyOnboarding(unittest.TestCase):
    def test_status_marks_missing_dependencies_and_first_run_without_writing_state(self) -> None:
        from sg_preflight import dependency_onboarding as onboarding

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(onboarding, "_raco_install_roots", return_value=[]):
                    with mock.patch.object(onboarding, "_onedrive_raco_sources", return_value=[]):
                        with mock.patch.object(onboarding, "_blender_path_candidates", return_value=[]):
                            with mock.patch.object(onboarding, "_candidate_bmw_repo_paths", return_value=[]):
                                with mock.patch.object(onboarding, "_find_executable", return_value=None):
                                    payload = onboarding.build_dependency_onboarding_status(workspace=root)

        self.assertEqual(payload["status"], "incomplete")
        self.assertTrue(payload["first_run"])
        self.assertFalse((root / "operator_state").exists())
        self.assertEqual(payload["counts"]["available"], 0)
        self.assertEqual(payload["counts"]["missing"], 4)
        self.assertEqual([item["key"] for item in payload["items"]], [
            "raco_gui",
            "raco_headless",
            "blender",
            "digital_3d_car_repo",
        ])
        self.assertTrue(all(action["requires_confirmation"] for action in payload["actions"]))
        self.assertIn("Manual review remains required.", payload["guardrails"])
        self.assertIn("Decision: not approval — evidence only.", payload["guardrails"])

    def test_status_uses_registered_tool_paths_and_documented_env_var(self) -> None:
        from sg_preflight import dependency_onboarding as onboarding

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raco_root = root / "tools" / "ramses" / "bin" / "RelWithDebInfo"
            gui = raco_root / "RamsesComposer.exe"
            headless = raco_root / "RaCoHeadless.exe"
            blender = root / "tools" / "Blender 4.1" / "blender.exe"
            bmw_root = root / "digital-3d-car-models"
            for path in (gui, headless, blender):
                write_text(path, "fixture\n")
            (bmw_root / "cars" / "BMW").mkdir(parents=True)
            onboarding.record_dependency_path(workspace=root, key="raco_gui", path=gui)
            onboarding.record_dependency_path(workspace=root, key="raco_headless", path=headless)
            onboarding.record_dependency_path(workspace=root, key="blender", path=blender)

            with mock.patch.dict(os.environ, {"Digital-3D-Car-Repo": str(bmw_root)}, clear=True):
                with mock.patch.object(onboarding, "_find_executable", return_value=None):
                    payload = onboarding.build_dependency_onboarding_status(workspace=root)

        self.assertFalse(payload["first_run"])
        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["counts"]["available"], 4)
        self.assertFalse(payload["actions"])

    def test_detected_bmw_checkout_without_env_var_offers_setx_action(self) -> None:
        from sg_preflight import dependency_onboarding as onboarding

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bmw_root = root / "digital-3d-car-models"
            (bmw_root / "cars" / "BMW").mkdir(parents=True)
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(onboarding, "_raco_install_roots", return_value=[]):
                    with mock.patch.object(onboarding, "_onedrive_raco_sources", return_value=[]):
                        with mock.patch.object(onboarding, "_blender_path_candidates", return_value=[]):
                            payload = onboarding.build_dependency_onboarding_status(
                                workspace=root,
                                bmw_root=bmw_root,
                            )

        bmw_item = next(item for item in payload["items"] if item["key"] == "digital_3d_car_repo")
        self.assertEqual(bmw_item["status"], "incomplete")
        self.assertIn("Digital-3D-Car-Repo is not set", bmw_item["detail"])
        self.assertEqual(bmw_item["setup_action"]["id"], "setup-digital-3d-car-repo")
        self.assertIn("setx Digital-3D-Car-Repo", bmw_item["setup_action"]["command_preview"])

    def test_set_bmw_repo_env_action_is_confirmation_gated_and_hidden(self) -> None:
        from sg_preflight import dependency_onboarding as onboarding

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bmw_root = root / "digital-3d-car-models"
            (bmw_root / "cars" / "BMW").mkdir(parents=True)
            with self.assertRaises(ValueError):
                onboarding.run_dependency_setup_action(
                    action_id="setup-digital-3d-car-repo",
                    workspace=root,
                    operator_confirmed=False,
                    target_path=bmw_root,
                )

            completed = subprocess.CompletedProcess(args=["setx"], returncode=0, stdout="ok\n", stderr="")
            with mock.patch.object(onboarding.sys, "platform", "win32"):
                with mock.patch.object(onboarding.subprocess, "run", return_value=completed) as run_mock:
                    result = onboarding.run_dependency_setup_action(
                        action_id="setup-digital-3d-car-repo",
                        workspace=root,
                        operator_confirmed=True,
                        target_path=bmw_root,
                    )
            state_path = root / "operator_state" / "dependency_onboarding.json"
            self.assertTrue(state_path.is_file())

        self.assertEqual(result["status"], "recorded")
        self.assertFalse(result["is_approval"])
        run_mock.assert_called_once()
        kwargs = run_mock.call_args.kwargs
        self.assertIn("creationflags", kwargs)
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)

    def test_raco_setup_copies_folder_and_records_gui_and_headless(self) -> None:
        from sg_preflight import dependency_onboarding as onboarding

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "shared" / "Ramses_Composer_Current" / "bin" / "RelWithDebInfo"
            gui = source / "RamsesComposer.exe"
            headless = source / "RaCoHeadless.exe"
            write_text(gui, "gui\n")
            write_text(headless, "headless\n")
            target = root / "local_tools"
            with mock.patch.object(onboarding, "_onedrive_raco_sources", return_value=[]):
                with mock.patch.object(onboarding, "_raco_install_roots", return_value=[]):
                    with mock.patch.object(onboarding, "_find_executable", return_value=None):
                        with mock.patch.dict(os.environ, {}, clear=True):
                            result = onboarding.run_dependency_setup_action(
                                action_id="setup-raco-from-shared-tools",
                                workspace=root,
                                operator_confirmed=True,
                                source_path=source.parent.parent,
                                target_path=target,
                            )
            state = onboarding.load_dependency_onboarding_state(root)
            self.assertEqual(result["status"], "recorded")
            self.assertTrue(Path(state["registered_paths"]["raco_gui"]).is_file())
            self.assertTrue(Path(state["registered_paths"]["raco_headless"]).is_file())
            self.assertIn("RamsesComposer.exe", state["registered_paths"]["raco_gui"])

    def test_blender_disallowed_version_is_incomplete(self) -> None:
        from sg_preflight import dependency_onboarding as onboarding

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            blender = root / "Blender 4.2" / "blender.exe"
            write_text(blender, "fixture\n")
            with mock.patch.object(onboarding, "_blender_path_candidates", return_value=[blender]):
                with mock.patch.object(onboarding, "_find_executable", return_value=None):
                    payload = onboarding.build_dependency_onboarding_status(workspace=root)

        blender_item = next(item for item in payload["items"] if item["key"] == "blender")
        self.assertEqual(blender_item["status"], "incomplete")
        self.assertIn("not to use Blender 4.2 or greater", blender_item["detail"])

    def test_start_dependency_setup_action_spawns_hidden_worker_and_reports_progress_tail(self) -> None:
        from sg_preflight import dependency_onboarding as onboarding

        class FakeProcess:
            returncode = None

            def poll(self) -> None:
                return None

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bmw_root = root / "digital-3d-car-models"
            (bmw_root / "cars" / "BMW").mkdir(parents=True)
            fake_process = FakeProcess()
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(onboarding.subprocess, "Popen", return_value=fake_process) as popen_mock:
                    with mock.patch.object(onboarding.sys, "platform", "win32"):
                        job = onboarding.start_dependency_setup_action(
                            action_id="setup-digital-3d-car-repo",
                            workspace=root,
                            operator_confirmed=True,
                            target_path=bmw_root,
                        )
            write_text(job.stdout_path, "\n".join(f"line {index:02d}" for index in range(25)))
            result = onboarding.poll_dependency_setup_action(job)

        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["phase"], "running")
        self.assertEqual(result["typical_range"], onboarding.ENV_SETUP_TYPICAL_RANGE_LABEL)
        self.assertEqual(result["stdout_tail_lines"][0], "line 05")
        self.assertEqual(result["stdout_tail_lines"][-1], "line 24")
        command = popen_mock.call_args.args[0]
        self.assertIn("dependency-setup-worker", command)
        self.assertIn("--target-path", command)
        self.assertEqual(popen_mock.call_args.kwargs["stdin"], subprocess.DEVNULL)

    def test_poll_dependency_setup_action_parses_worker_payload(self) -> None:
        from sg_preflight import dependency_onboarding as onboarding

        class FakeProcess:
            returncode = 0

            def poll(self) -> int:
                return 0

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bmw_root = root / "digital-3d-car-models"
            (bmw_root / "cars" / "BMW").mkdir(parents=True)
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(onboarding.subprocess, "Popen", return_value=FakeProcess()):
                    with mock.patch.object(onboarding.sys, "platform", "win32"):
                        job = onboarding.start_dependency_setup_action(
                            action_id="setup-digital-3d-car-repo",
                            workspace=root,
                            operator_confirmed=True,
                            target_path=bmw_root,
                        )
            write_text(
                job.stdout_path,
                'progress\n{"status":"recorded","action_id":"setup-digital-3d-car-repo","summary":"ok"}\n',
            )
            result = onboarding.poll_dependency_setup_action(job)

        self.assertTrue(result["completed"])
        self.assertEqual(result["status"], "recorded")
        self.assertEqual(result["summary"], "ok")
        self.assertFalse(result["is_approval"])


if __name__ == "__main__":
    unittest.main()
