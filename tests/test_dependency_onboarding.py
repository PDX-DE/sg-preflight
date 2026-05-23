from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
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

    def test_fast_path_detection_auto_registers_paths_for_g70_generation_preflight(self) -> None:
        from sg_preflight import dependency_onboarding as onboarding
        from sg_preflight import delivery_workbook_generation as generation

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raco_root = root / "external" / "ramses" / "bin" / "RelWithDebInfo"
            gui = raco_root / "RamsesComposer.exe"
            headless = raco_root / "RaCoHeadless.exe"
            blender = root / "external" / "blender" / "blender.exe"
            bmw_root = root / "digital-3d-car-models"
            for path in (gui, headless, blender):
                write_text(path, "fixture\n")
            (bmw_root / "cars" / "BMW").mkdir(parents=True)

            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(onboarding, "_onedrive_raco_sources", return_value=[]):
                    with mock.patch.object(onboarding, "_find_executable", return_value=None):
                        setup_payload = onboarding.build_dependency_onboarding_status(workspace=root)
            state = onboarding.load_dependency_onboarding_state(root)
            state_path = onboarding.dependency_onboarding_state_path(root)
            state_text = state_path.read_text(encoding="utf-8")
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(onboarding, "_onedrive_raco_sources", return_value=[]):
                    with mock.patch.object(onboarding, "_find_executable", return_value=None):
                        second_setup_payload = onboarding.build_dependency_onboarding_status(workspace=root)
            second_state_text = state_path.read_text(encoding="utf-8")

            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(generation, "_find_executable", return_value=""):
                    with mock.patch.object(generation.sys, "frozen", False, create=True):
                        with mock.patch.object(generation.sys, "executable", sys.executable):
                            with mock.patch.object(generation.shutil, "which", return_value=""):
                                preflight = generation.check_delivery_workbook_generation_environment(
                                    profile_id="G70",
                                    workspace=root,
                                    min_free_bytes=1,
                                )

        registered_paths = state["registered_paths"]
        self.assertEqual(setup_payload["status"], "available")
        self.assertTrue(setup_payload["first_run"])
        self.assertEqual(second_setup_payload["status"], "available")
        self.assertFalse(second_setup_payload["first_run"])
        self.assertEqual(second_state_text, state_text)
        self.assertEqual(Path(registered_paths["raco_gui"]), gui.resolve())
        self.assertEqual(Path(registered_paths["raco_headless"]), headless.resolve())
        self.assertEqual(Path(registered_paths["blender"]), blender.resolve())
        self.assertEqual(Path(registered_paths["digital_3d_car_repo"]), bmw_root.resolve())
        checks = {item["key"]: item for item in preflight["checks"]}
        self.assertTrue(preflight["can_run"])
        self.assertEqual(preflight["profile_id"], "G70")
        self.assertEqual(checks["digital_3d_car_repo"]["status"], "available")
        self.assertEqual(checks["raco"]["status"], "available")
        self.assertEqual(checks["raco_headless"]["status"], "available")
        self.assertEqual(checks["blender"]["status"], "available")

    def test_fast_path_detection_prefers_newly_detected_paths_over_old_registrations(self) -> None:
        from sg_preflight import dependency_onboarding as onboarding

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old_gui = root / "old-tools" / "RamsesComposer.exe"
            old_headless = root / "old-tools" / "RaCoHeadless.exe"
            old_blender = root / "old-tools" / "blender.exe"
            old_bmw_root = root / "old-digital-3d-car-models"
            new_raco_root = root / "external" / "ramses" / "bin" / "RelWithDebInfo"
            new_gui = new_raco_root / "RamsesComposer.exe"
            new_headless = new_raco_root / "RaCoHeadless.exe"
            new_blender = root / "external" / "blender" / "blender.exe"
            new_bmw_root = root / "digital-3d-car-models"
            for path in (old_gui, old_headless, old_blender, new_gui, new_headless, new_blender):
                write_text(path, "fixture\n")
            (old_bmw_root / "cars" / "BMW").mkdir(parents=True)
            (new_bmw_root / "cars" / "BMW").mkdir(parents=True)
            onboarding.record_dependency_path(workspace=root, key="raco_gui", path=old_gui)
            onboarding.record_dependency_path(workspace=root, key="raco_headless", path=old_headless)
            onboarding.record_dependency_path(workspace=root, key="blender", path=old_blender)
            onboarding.record_dependency_path(workspace=root, key="digital_3d_car_repo", path=old_bmw_root)

            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(onboarding, "_onedrive_raco_sources", return_value=[]):
                    with mock.patch.object(onboarding, "_find_executable", return_value=None):
                        payload = onboarding.build_dependency_onboarding_status(workspace=root)
            state = onboarding.load_dependency_onboarding_state(root)

        registered_paths = state["registered_paths"]
        self.assertEqual(payload["status"], "available")
        self.assertEqual(Path(registered_paths["raco_gui"]), new_gui.resolve())
        self.assertEqual(Path(registered_paths["raco_headless"]), new_headless.resolve())
        self.assertEqual(Path(registered_paths["blender"]), new_blender.resolve())
        self.assertEqual(Path(registered_paths["digital_3d_car_repo"]), new_bmw_root.resolve())

    def test_detected_bmw_checkout_without_env_var_uses_existing_install_fast_path(self) -> None:
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
        self.assertEqual(bmw_item["status"], "available")
        self.assertIn("Existing checkout detected", bmw_item["detail"])
        self.assertEqual(bmw_item["setup_action"], {})

    def test_existing_raco_install_does_not_require_onedrive_source_for_green_status(self) -> None:
        from sg_preflight import dependency_onboarding as onboarding

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raco_root = root / "RamsesComposerWindows" / "bin" / "RelWithDebInfo"
            gui = raco_root / "RamsesComposer.exe"
            headless = raco_root / "RaCoHeadless.exe"
            write_text(gui, "gui\n")
            write_text(headless, "headless\n")
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(onboarding, "_raco_install_roots", return_value=[raco_root.parent.parent]):
                    with mock.patch.object(onboarding, "_onedrive_raco_sources", return_value=[]):
                        with mock.patch.object(onboarding, "_blender_path_candidates", return_value=[]):
                            with mock.patch.object(onboarding, "_candidate_bmw_repo_paths", return_value=[]):
                                with mock.patch.object(onboarding, "_find_executable", return_value=None):
                                    payload = onboarding.build_dependency_onboarding_status(workspace=root)

        raco_items = [item for item in payload["items"] if item["key"] in {"raco_gui", "raco_headless"}]
        self.assertTrue(all(item["status"] == "available" for item in raco_items))
        self.assertTrue(all(item["setup_action"] == {} for item in raco_items))
        self.assertTrue(all("fallback for missing installs" in item["detail"] for item in raco_items))
        self.assertFalse(any("was not found locally" in item["detail"] for item in raco_items))

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

    def test_blender_setup_runs_installer_and_records_detected_executable(self) -> None:
        from sg_preflight import dependency_onboarding as onboarding

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            installer = root / "Blender-4.1.1-windows-x64.msi"
            installed = root / "Program Files" / "Blender Foundation" / "Blender 4.1" / "blender.exe"
            write_text(installer, "installer\n")
            write_text(installed, "blender\n")
            completed = subprocess.CompletedProcess(args=["msiexec"], returncode=0, stdout="", stderr="")
            with mock.patch.object(onboarding.sys, "platform", "win32"):
                with mock.patch.object(onboarding.subprocess, "run", return_value=completed) as run_mock:
                    with mock.patch.object(onboarding, "_blender_path_candidates", return_value=[installed]):
                        result = onboarding.run_dependency_setup_action(
                            action_id="setup-blender-411",
                            workspace=root,
                            operator_confirmed=True,
                            source_path=installer,
                        )

        self.assertEqual(result["status"], "recorded")
        self.assertEqual(result["path"], str(installed.resolve()))
        command = run_mock.call_args.args[0]
        self.assertEqual(command[:2], ["msiexec", "/i"])
        self.assertIn("creationflags", run_mock.call_args.kwargs)

    def test_blender_setup_downloads_official_installer_when_source_is_blank(self) -> None:
        from sg_preflight import dependency_onboarding as onboarding

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            installed = root / "Program Files" / "Blender Foundation" / "Blender 4.1" / "blender.exe"
            write_text(installed, "blender\n")
            completed = subprocess.CompletedProcess(args=["msiexec"], returncode=0, stdout="", stderr="")

            def _download(_url: str, filename: str) -> tuple[str, object | None]:
                write_text(Path(filename), "installer\n")
                return filename, None

            with mock.patch.object(onboarding.sys, "platform", "win32"):
                with mock.patch.object(onboarding.urllib.request, "urlretrieve", side_effect=_download) as download:
                    with mock.patch.object(onboarding.subprocess, "run", return_value=completed) as run_mock:
                        with mock.patch.object(onboarding, "_blender_path_candidates", return_value=[installed]):
                            result = onboarding.run_dependency_setup_action(
                                action_id="setup-blender-411",
                                workspace=root,
                                operator_confirmed=True,
                            )

        self.assertEqual(result["status"], "recorded")
        self.assertEqual(result["path"], str(installed.resolve()))
        self.assertEqual(result["download_url"], onboarding.BLENDER_INSTALLER_URL)
        download.assert_called_once()
        self.assertEqual(download.call_args.args[0], onboarding.BLENDER_INSTALLER_URL)
        command = run_mock.call_args.args[0]
        self.assertEqual(command[:2], ["msiexec", "/i"])
        self.assertIn(onboarding.BLENDER_INSTALLER_FILENAME, command[2])

    def test_missing_bmw_checkout_clone_action_runs_git_lfs_and_records_env(self) -> None:
        from sg_preflight import dependency_onboarding as onboarding

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fake_git = root / "git.exe"
            fake_lfs = root / "git-lfs.exe"
            write_text(fake_git, "git\n")
            write_text(fake_lfs, "lfs\n")
            clone_parent = root / "clone-target"
            repo_root = clone_parent / "digital-3d-car-models"
            commands: list[list[str]] = []

            def _find_executable(name: str) -> Path | None:
                if name in {"git.exe", "git"}:
                    return fake_git
                if name in {"git-lfs.exe", "git-lfs"}:
                    return fake_lfs
                return None

            def _run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                del kwargs
                commands.append(command)
                if "clone" in command:
                    (repo_root / "cars" / "BMW").mkdir(parents=True)
                return subprocess.CompletedProcess(args=command, returncode=0, stdout="ok\n", stderr="")

            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(onboarding.sys, "platform", "win32"):
                    with mock.patch.object(onboarding, "_candidate_bmw_repo_paths", return_value=[]):
                        with mock.patch.object(onboarding, "_find_executable", side_effect=_find_executable):
                            with mock.patch.object(onboarding.subprocess, "run", side_effect=_run):
                                result = onboarding.run_dependency_setup_action(
                                    action_id="clone-digital-3d-car-repo",
                                    workspace=root,
                                    operator_confirmed=True,
                                    target_path=clone_parent,
                                )
            repo_exists = (repo_root / "cars" / "BMW").is_dir()
            resolved_repo_root = str(Path(result["path"]))

        self.assertEqual(result["status"], "recorded")
        self.assertTrue(repo_exists)
        self.assertTrue(any("clone" in command for command in commands))
        self.assertTrue(any(command[1:4] == ["-C", resolved_repo_root, "lfs"] for command in commands))
        self.assertTrue(any(command[:2] == ["setx", onboarding.DIGITAL_3D_CAR_REPO_ENV] for command in commands))

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
