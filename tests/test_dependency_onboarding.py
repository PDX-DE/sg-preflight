from __future__ import annotations

import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any
import unittest
from unittest import mock

from tests.operator_helpers import write_text


def _completed(
    command: list[str] | None = None,
    *,
    returncode: int = 0,
    stdout: str = "ok\n",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=command or ["python"], returncode=returncode, stdout=stdout, stderr=stderr)


def _write_bmw_ci_python(repo_root: Path) -> Path:
    return write_text(repo_root / ".venv_bmw_ci" / "Scripts" / "python.exe", "python\n")


def _hold_auto_persistence_transaction(
    workspace: str,
    detected_gui: str,
    write_entered: Any,
    release_write: Any,
) -> None:
    from sg_preflight import dependency_onboarding as onboarding

    original_write = onboarding._write_dependency_onboarding_state

    def wait_before_write(workspace_arg: Path | str, state: dict[str, Any]) -> dict[str, Any]:
        write_entered.set()
        if not release_write.wait(15):
            raise TimeoutError("Timed out waiting to release dependency-state auto persistence")
        return original_write(workspace_arg, state)

    detected_state: dict[str, Any] = {
        "registered_paths": {"raco_gui": detected_gui},
        "source": "dependency onboarding fast-path",
        "last_auto_registered_key": "raco_gui",
    }
    with mock.patch.object(
        onboarding,
        "_write_dependency_onboarding_state",
        side_effect=wait_before_write,
    ):
        onboarding._persist_auto_detected_dependency_paths(
            workspace,
            original_paths={},
            detected_state=detected_state,
        )


def _record_explicit_paths(
    workspace: str,
    operator_gui: str,
    operator_python: str,
    record_started: Any,
    record_finished: Any,
) -> None:
    from sg_preflight import dependency_onboarding as onboarding

    original_acquire = onboarding._acquire_dependency_state_file_lock

    def signal_before_acquire(handle: Any) -> None:
        record_started.set()
        original_acquire(handle)

    with mock.patch.object(
        onboarding,
        "_acquire_dependency_state_file_lock",
        side_effect=signal_before_acquire,
    ):
        onboarding.record_dependency_path(workspace=workspace, key="raco_gui", path=operator_gui)
        onboarding.record_dependency_path(
            workspace=workspace,
            key="bmw_pipeline_python",
            path=operator_python,
        )
    record_finished.set()


class TestDependencyOnboarding(unittest.TestCase):
    def test_status_batches_auto_registered_paths_into_one_state_write(self) -> None:
        from sg_preflight import dependency_onboarding as onboarding

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raco_root = root / "external" / "ramses"
            raco_bin = raco_root / "bin" / "RelWithDebInfo"
            gui = raco_bin / "RamsesComposer.exe"
            headless = raco_bin / "RaCoHeadless.exe"
            blender = root / "external" / "blender" / "blender.exe"
            for path in (gui, headless, blender):
                write_text(path, "fixture\n")

            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(onboarding, "_raco_install_roots", return_value=[raco_root]):
                    with mock.patch.object(onboarding, "_onedrive_raco_sources", return_value=[]):
                        with mock.patch.object(onboarding, "_blender_path_candidates", return_value=[blender]):
                            with mock.patch.object(onboarding, "_candidate_bmw_repo_paths", return_value=[]):
                                with mock.patch.object(onboarding, "_candidate_idc23_repo_paths", return_value=[]):
                                    with mock.patch.object(onboarding, "_find_executable", return_value=None):
                                        with mock.patch.object(
                                            onboarding,
                                            "_write_dependency_onboarding_state",
                                            wraps=onboarding._write_dependency_onboarding_state,
                                        ) as write_state:
                                            payload = onboarding.build_dependency_onboarding_status(workspace=root)
            state = onboarding.load_dependency_onboarding_state(root)

        self.assertEqual(write_state.call_count, 1)
        self.assertEqual(payload["counts"]["available"], 3)
        self.assertEqual(Path(state["registered_paths"]["raco_gui"]), gui.resolve())
        self.assertEqual(Path(state["registered_paths"]["raco_headless"]), headless.resolve())
        self.assertEqual(Path(state["registered_paths"]["blender"]), blender.resolve())

    def test_status_auto_registration_preserves_interleaved_explicit_paths(self) -> None:
        from sg_preflight import dependency_onboarding as onboarding

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raco_root = root / "external" / "ramses"
            raco_bin = raco_root / "bin" / "RelWithDebInfo"
            detected_gui = raco_bin / "RamsesComposer.exe"
            detected_headless = raco_bin / "RaCoHeadless.exe"
            detected_blender = root / "external" / "blender" / "blender.exe"
            operator_gui = root / "operator-tools" / "RamsesComposer.exe"
            operator_python = root / "operator-tools" / "python.exe"
            for path in (
                detected_gui,
                detected_headless,
                detected_blender,
                operator_gui,
                operator_python,
            ):
                write_text(path, "fixture\n")

            original_blender_status = onboarding._blender_status

            def register_paths_during_detection(state: dict[str, Any], workspace: Path) -> dict[str, Any]:
                onboarding.record_dependency_path(workspace=root, key="raco_gui", path=operator_gui)
                onboarding.record_dependency_path(
                    workspace=root,
                    key="bmw_pipeline_python",
                    path=operator_python,
                )
                return original_blender_status(state, workspace)

            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(onboarding, "_raco_install_roots", return_value=[raco_root]):
                    with mock.patch.object(onboarding, "_onedrive_raco_sources", return_value=[]):
                        with mock.patch.object(onboarding, "_blender_path_candidates", return_value=[detected_blender]):
                            with mock.patch.object(onboarding, "_candidate_bmw_repo_paths", return_value=[]):
                                with mock.patch.object(onboarding, "_candidate_idc23_repo_paths", return_value=[]):
                                    with mock.patch.object(onboarding, "_find_executable", return_value=None):
                                        with mock.patch.object(
                                            onboarding,
                                            "_blender_status",
                                            side_effect=register_paths_during_detection,
                                        ):
                                            onboarding.build_dependency_onboarding_status(workspace=root)
            state = onboarding.load_dependency_onboarding_state(root)

        registered_paths = state["registered_paths"]
        self.assertEqual(Path(registered_paths["raco_gui"]), operator_gui.resolve())
        self.assertEqual(Path(registered_paths["raco_headless"]), detected_headless.resolve())
        self.assertEqual(Path(registered_paths["blender"]), detected_blender.resolve())
        self.assertEqual(Path(registered_paths["bmw_pipeline_python"]), operator_python.resolve())
        self.assertFalse(any(str(key).startswith("_") for key in state))

    def test_auto_and_explicit_persistence_share_a_cross_process_transaction_lock(self) -> None:
        from sg_preflight import dependency_onboarding as onboarding

        self.assertTrue(hasattr(onboarding, "_persist_auto_detected_dependency_paths"))
        self.assertTrue(hasattr(onboarding, "_acquire_dependency_state_file_lock"))
        context = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            detected_gui = root / "detected" / "RamsesComposer.exe"
            operator_gui = root / "operator" / "RamsesComposer.exe"
            operator_python = root / "operator" / "python.exe"
            for path in (detected_gui, operator_gui, operator_python):
                write_text(path, "fixture\n")
            write_entered = context.Event()
            release_write = context.Event()
            record_started = context.Event()
            record_finished = context.Event()
            auto_process = context.Process(
                target=_hold_auto_persistence_transaction,
                args=(str(root), str(detected_gui.resolve()), write_entered, release_write),
            )
            record_process = context.Process(
                target=_record_explicit_paths,
                args=(
                    str(root),
                    str(operator_gui.resolve()),
                    str(operator_python.resolve()),
                    record_started,
                    record_finished,
                ),
            )

            auto_process.start()
            auto_reached_write = write_entered.wait(15)
            lock_path = root / "operator_state" / "dependency_onboarding.lock"
            lock_identity_while_held = lock_path.stat().st_ino if lock_path.is_file() else None
            if auto_reached_write:
                record_process.start()
            record_reached_transaction = auto_reached_write and record_started.wait(15)
            record_finished_before_release = record_finished.wait(1) if record_reached_transaction else False
            release_write.set()
            auto_process.join(20)
            if record_process.pid is not None:
                record_process.join(20)
            for process in (auto_process, record_process):
                if process.pid is not None and process.is_alive():
                    process.terminate()
                    process.join(5)

            state = onboarding.load_dependency_onboarding_state(root)
            lock_identity_after = lock_path.stat().st_ino if lock_path.is_file() else None

        self.assertTrue(auto_reached_write)
        self.assertTrue(record_reached_transaction)
        self.assertFalse(record_finished_before_release)
        self.assertEqual(auto_process.exitcode, 0)
        self.assertEqual(record_process.exitcode, 0)
        self.assertIsNotNone(lock_identity_while_held)
        self.assertEqual(lock_identity_after, lock_identity_while_held)
        registered_paths = state["registered_paths"]
        self.assertEqual(Path(registered_paths["raco_gui"]), operator_gui.resolve())
        self.assertEqual(Path(registered_paths["bmw_pipeline_python"]), operator_python.resolve())

    def test_state_write_retries_one_transient_replace_permission_error(self) -> None:
        from sg_preflight import dependency_onboarding as onboarding

        original_replace = Path.replace
        replace_attempts = 0

        def replace_once_denied(source: Path, target: Path) -> Path:
            nonlocal replace_attempts
            replace_attempts += 1
            if replace_attempts == 1:
                raise PermissionError("transient destination lock")
            return original_replace(source, target)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with mock.patch.object(Path, "replace", new=replace_once_denied):
                with mock.patch.object(onboarding.time, "sleep") as sleep:
                    try:
                        result = onboarding._write_dependency_onboarding_state(root, {"source": "test"})
                    except PermissionError:
                        self.fail("A transient replace PermissionError should be retried")
            saved = onboarding.load_dependency_onboarding_state(root)

        self.assertEqual(replace_attempts, 2)
        sleep.assert_called_once_with(0.01)
        self.assertEqual(saved, result)

    def test_state_write_cleans_temp_file_when_replace_retries_are_exhausted(self) -> None:
        from sg_preflight import dependency_onboarding as onboarding

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with mock.patch.object(Path, "replace", side_effect=PermissionError("destination locked")) as replace:
                with mock.patch.object(onboarding.time, "sleep") as sleep:
                    with self.assertRaises(PermissionError):
                        onboarding._write_dependency_onboarding_state(root, {"source": "test"})
            state_root = onboarding.operator_state_root(root)
            temp_paths = list(state_root.glob(".dependency_onboarding.json.*.tmp"))

        self.assertEqual(replace.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertFalse(temp_paths)

    def test_status_marks_missing_dependencies_and_first_run_without_writing_state(self) -> None:
        from sg_preflight import dependency_onboarding as onboarding

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(onboarding, "_raco_install_roots", return_value=[]):
                    with mock.patch.object(onboarding, "_onedrive_raco_sources", return_value=[]):
                        with mock.patch.object(onboarding, "_blender_path_candidates", return_value=[]):
                            with mock.patch.object(onboarding, "_candidate_bmw_repo_paths", return_value=[]):
                                with mock.patch.object(onboarding, "_candidate_idc23_repo_paths", return_value=[]):
                                    with mock.patch.object(onboarding, "_find_executable", return_value=None):
                                        payload = onboarding.build_dependency_onboarding_status(workspace=root)

        self.assertEqual(payload["status"], "incomplete")
        self.assertTrue(payload["first_run"])
        self.assertFalse((root / "operator_state").exists())
        self.assertEqual(payload["counts"]["available"], 0)
        self.assertEqual(payload["counts"]["missing"], 6)
        self.assertEqual([item["key"] for item in payload["items"]], [
            "raco_gui",
            "raco_headless",
            "blender",
            "digital_3d_car_repo",
            "digital_3d_car_repo_idc23",
            "bmw_ci_requirements",
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
            idc23_root = root / "digital-3d-car-models-idc23"
            bmw_ci_python = root / "tools" / "bmw-ci-python.exe"
            for path in (gui, headless, blender):
                write_text(path, "fixture\n")
            write_text(bmw_ci_python, "python\n")
            (bmw_root / "cars" / "BMW").mkdir(parents=True)
            write_text(idc23_root / "ci" / "scripts" / "test" / "main.py", "print('fixture')\n")
            (idc23_root / "cars" / "BMW" / "_Shared").mkdir(parents=True)
            onboarding.record_dependency_path(workspace=root, key="raco_gui", path=gui)
            onboarding.record_dependency_path(workspace=root, key="raco_headless", path=headless)
            onboarding.record_dependency_path(workspace=root, key="blender", path=blender)
            onboarding.record_dependency_path(workspace=root, key="bmw_pipeline_python", path=bmw_ci_python)

            with mock.patch.dict(
                os.environ,
                {
                    "Digital-3D-Car-Repo": str(bmw_root),
                    "Digital-3D-Car-Repo-IDC23": str(idc23_root),
                },
                clear=True,
            ):
                with mock.patch.object(onboarding, "_find_executable", return_value=None):
                    with mock.patch.object(onboarding.subprocess, "run", return_value=_completed()):
                        payload = onboarding.build_dependency_onboarding_status(workspace=root)

        self.assertTrue(payload["first_run"])
        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["counts"]["available"], 6)
        self.assertFalse(payload["actions"])

    def test_state_write_retries_transient_replace_permission_error(self) -> None:
        from sg_preflight import dependency_onboarding as onboarding

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            gui = root / "tools" / "ramses" / "RamsesComposer.exe"
            write_text(gui, "fixture\n")
            state_path_type = type(onboarding.dependency_onboarding_state_path(root))
            original_replace = state_path_type.replace
            calls = {"count": 0}

            def flaky_replace(self: Path, target: Path) -> Path:
                if Path(target).name == onboarding.ONBOARDING_STATE_FILENAME and calls["count"] == 0:
                    calls["count"] += 1
                    raise PermissionError("target locked")
                return original_replace(self, target)

            with mock.patch.object(state_path_type, "replace", flaky_replace):
                with mock.patch.object(onboarding.time, "sleep") as sleep:
                    state = onboarding.record_dependency_path(workspace=root, key="raco_gui", path=gui)

            self.assertEqual(calls["count"], 1)
            sleep.assert_called_once()
            self.assertEqual(Path(state["registered_paths"]["raco_gui"]), gui.resolve())
            self.assertTrue(onboarding.dependency_onboarding_state_path(root).is_file())

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
            idc23_root = root / "digital-3d-car-models-idc23"
            for path in (gui, headless, blender):
                write_text(path, "fixture\n")
            (bmw_root / "cars" / "BMW" / "G70_EVO").mkdir(parents=True)
            _write_bmw_ci_python(bmw_root)
            write_text(idc23_root / "ci" / "scripts" / "test" / "main.py", "print('fixture')\n")
            (idc23_root / "cars" / "BMW" / "_Shared").mkdir(parents=True)
            write_text(bmw_root / "ci" / "scripts" / "car_manager.py", "print('fixture')\n")
            write_text(
                bmw_root / "ci" / "scripts" / "common" / "models_build_config.yaml",
                """allCars:
  - name: G70_EVO
    type: build
    interface_version: 24
""",
            )

            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(onboarding, "_onedrive_raco_sources", return_value=[]):
                    with mock.patch.object(onboarding, "_candidate_idc23_repo_paths", return_value=[idc23_root]):
                        with mock.patch.object(onboarding, "_find_executable", return_value=None):
                            with mock.patch.object(onboarding.subprocess, "run", return_value=_completed()):
                                setup_payload = onboarding.build_dependency_onboarding_status(workspace=root)
            state = onboarding.load_dependency_onboarding_state(root)
            state_path = onboarding.dependency_onboarding_state_path(root)
            state_text = state_path.read_text(encoding="utf-8")
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(onboarding, "_onedrive_raco_sources", return_value=[]):
                    with mock.patch.object(onboarding, "_candidate_idc23_repo_paths", return_value=[idc23_root]):
                        with mock.patch.object(onboarding, "_find_executable", return_value=None):
                            with mock.patch.object(onboarding.subprocess, "run", return_value=_completed()):
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
        self.assertTrue(second_setup_payload["first_run"])
        self.assertEqual(second_state_text, state_text)
        self.assertEqual(Path(registered_paths["raco_gui"]), gui.resolve())
        self.assertEqual(Path(registered_paths["raco_headless"]), headless.resolve())
        self.assertEqual(Path(registered_paths["blender"]), blender.resolve())
        self.assertEqual(Path(registered_paths["digital_3d_car_repo"]), bmw_root.resolve())
        self.assertEqual(Path(registered_paths["digital_3d_car_repo_idc23"]), idc23_root.resolve())
        self.assertEqual(Path(registered_paths["digital_3d_car_repo_assets_idc23"]), idc23_root.resolve())
        checks = {item["key"]: item for item in preflight["checks"]}
        self.assertTrue(preflight["can_run"])
        self.assertEqual(preflight["profile_id"], "G70")
        self.assertEqual(checks["digital_3d_car_repo"]["status"], "available")
        self.assertEqual(checks["raco"]["status"], "available")
        self.assertEqual(checks["raco_headless"]["status"], "available")
        self.assertEqual(checks["blender"]["status"], "available")

    def test_only_explicit_dismissal_or_completion_ends_first_run_guidance(self) -> None:
        from sg_preflight import dependency_onboarding as onboarding

        for resolution in ("dismissed", "completed"):
            with self.subTest(resolution=resolution), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                tool = root / "tools" / "RamsesComposer.exe"
                write_text(tool, "fixture\n")

                onboarding.record_dependency_path(workspace=root, key="raco_gui", path=tool)
                self.assertTrue(onboarding.first_run_guidance_eligible(root))

                onboarding.finish_first_run_guidance(
                    workspace=root,
                    resolution=resolution,
                )
                state = onboarding.load_dependency_onboarding_state(root)

                self.assertFalse(onboarding.first_run_guidance_eligible(root))
                self.assertEqual(
                    state["first_run_guidance"],
                    {
                        "finished": True,
                        "resolution": resolution,
                        "finished_at_utc": mock.ANY,
                    },
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaisesRegex(ValueError, "completed or dismissed"):
                onboarding.finish_first_run_guidance(
                    workspace=root,
                    resolution="auto_detected",
                )
            self.assertFalse(onboarding.dependency_onboarding_state_path(root).exists())

            onboarding._write_dependency_onboarding_state(
                root,
                {"first_run_guidance": {"finished": "true"}},
            )
            self.assertTrue(onboarding.first_run_guidance_eligible(root))

    def test_fast_path_detection_prefers_newly_detected_paths_over_old_registrations(self) -> None:
        from sg_preflight import dependency_onboarding as onboarding

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old_gui = root / "old-tools" / "RamsesComposer.exe"
            old_headless = root / "old-tools" / "RaCoHeadless.exe"
            old_blender = root / "old-tools" / "blender.exe"
            old_bmw_root = root / "old-digital-3d-car-models"
            old_idc23_root = root / "old-digital-3d-car-models-idc23"
            new_raco_root = root / "external" / "ramses" / "bin" / "RelWithDebInfo"
            new_gui = new_raco_root / "RamsesComposer.exe"
            new_headless = new_raco_root / "RaCoHeadless.exe"
            new_blender = root / "external" / "blender" / "blender.exe"
            new_bmw_root = root / "digital-3d-car-models"
            new_idc23_root = root / "digital-3d-car-models-idc23"
            for path in (old_gui, old_headless, old_blender, new_gui, new_headless, new_blender):
                write_text(path, "fixture\n")
            (old_bmw_root / "cars" / "BMW").mkdir(parents=True)
            write_text(old_idc23_root / "ci" / "scripts" / "test" / "main.py", "print('old')\n")
            (old_idc23_root / "cars" / "BMW" / "_Shared").mkdir(parents=True)
            (new_bmw_root / "cars" / "BMW").mkdir(parents=True)
            _write_bmw_ci_python(new_bmw_root)
            write_text(new_idc23_root / "ci" / "scripts" / "test" / "main.py", "print('new')\n")
            (new_idc23_root / "cars" / "BMW" / "_Shared").mkdir(parents=True)
            onboarding.record_dependency_path(workspace=root, key="raco_gui", path=old_gui)
            onboarding.record_dependency_path(workspace=root, key="raco_headless", path=old_headless)
            onboarding.record_dependency_path(workspace=root, key="blender", path=old_blender)
            onboarding.record_dependency_path(workspace=root, key="digital_3d_car_repo", path=old_bmw_root)
            onboarding.record_dependency_path(workspace=root, key="digital_3d_car_repo_idc23", path=old_idc23_root)

            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(onboarding, "_onedrive_raco_sources", return_value=[]):
                    with mock.patch.object(onboarding, "_candidate_idc23_repo_paths", return_value=[new_idc23_root]):
                        with mock.patch.object(onboarding, "_find_executable", return_value=None):
                            with mock.patch.object(onboarding.subprocess, "run", return_value=_completed()):
                                payload = onboarding.build_dependency_onboarding_status(workspace=root)
            state = onboarding.load_dependency_onboarding_state(root)

        registered_paths = state["registered_paths"]
        self.assertEqual(payload["status"], "available")
        self.assertEqual(Path(registered_paths["raco_gui"]), new_gui.resolve())
        self.assertEqual(Path(registered_paths["raco_headless"]), new_headless.resolve())
        self.assertEqual(Path(registered_paths["blender"]), new_blender.resolve())
        self.assertEqual(Path(registered_paths["digital_3d_car_repo"]), new_bmw_root.resolve())
        self.assertEqual(Path(registered_paths["digital_3d_car_repo_idc23"]), new_idc23_root.resolve())

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
                                with mock.patch.object(onboarding, "_candidate_idc23_repo_paths", return_value=[]):
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
                with mock.patch.object(onboarding, "_candidate_bmw_repo_paths", return_value=[]):
                    with mock.patch.object(onboarding, "_candidate_idc23_repo_paths", return_value=[]):
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

    def test_idc23_worktree_setup_creates_sets_env_verifies_shared_and_registers(self) -> None:
        from sg_preflight import dependency_onboarding as onboarding

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bmw_root = root / "digital-3d-car-models"
            target = root / "worktrees" / "assets-idc23"
            fake_git = root / "git.exe"
            write_text(fake_git, "git\n")
            (bmw_root / "cars" / "BMW").mkdir(parents=True)
            commands: list[list[str]] = []

            def _find_executable(name: str) -> Path | None:
                if name in {"git.exe", "git"}:
                    return fake_git
                return None

            def _run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                self.assertIn("creationflags", kwargs)
                commands.append(command)
                if command[3:5] == ["worktree", "add"]:
                    write_text(target / "ci" / "scripts" / "test" / "main.py", "print('fixture')\n")
                    (target / "cars" / "BMW" / "_Shared").mkdir(parents=True)
                return subprocess.CompletedProcess(args=command, returncode=0, stdout="ok\n", stderr="")

            with mock.patch.dict(os.environ, {"Digital-3D-Car-Repo": str(bmw_root)}, clear=True):
                with mock.patch.object(onboarding.sys, "platform", "win32"):
                    with mock.patch.object(onboarding, "_find_executable", side_effect=_find_executable):
                        with mock.patch.object(onboarding.subprocess, "run", side_effect=_run):
                            result = onboarding.run_dependency_setup_action(
                                action_id="setup-digital-3d-car-repo-idc23",
                                workspace=root,
                                operator_confirmed=True,
                                target_path=target,
                            )
            state = onboarding.load_dependency_onboarding_state(root)

        self.assertEqual(result["status"], "recorded")
        self.assertFalse(result["is_approval"])
        self.assertTrue(result["git_worktree_add_invoked"])
        self.assertTrue(result["setx_invoked"])
        self.assertEqual(result["shared_root_status"], "available")
        self.assertTrue(any(command[1:4] == ["-C", str(bmw_root.resolve()), "worktree"] for command in commands))
        self.assertTrue(any(command[:2] == ["setx", onboarding.DIGITAL_3D_CAR_REPO_IDC23_ENV] for command in commands))
        self.assertEqual(Path(state["registered_paths"]["digital_3d_car_repo_idc23"]), target.resolve())
        self.assertEqual(Path(state["registered_paths"]["digital_3d_car_repo_assets_idc23"]), target.resolve())

    def test_existing_idc23_worktree_fast_path_records_without_git_worktree_add(self) -> None:
        from sg_preflight import dependency_onboarding as onboarding

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bmw_root = root / "digital-3d-car-models"
            idc23_root = root / "digital-3d-car-models-idc23"
            (bmw_root / "cars" / "BMW").mkdir(parents=True)
            write_text(idc23_root / "ci" / "scripts" / "test" / "main.py", "print('fixture')\n")
            (idc23_root / "cars" / "BMW" / "_Shared").mkdir(parents=True)
            commands: list[list[str]] = []

            def _run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                self.assertIn("creationflags", kwargs)
                commands.append(command)
                return subprocess.CompletedProcess(args=command, returncode=0, stdout="ok\n", stderr="")

            with mock.patch.dict(os.environ, {"Digital-3D-Car-Repo": str(bmw_root)}, clear=True):
                with mock.patch.object(onboarding.sys, "platform", "win32"):
                    with mock.patch.object(onboarding.subprocess, "run", side_effect=_run):
                        result = onboarding.run_dependency_setup_action(
                            action_id="setup-digital-3d-car-repo-idc23",
                            workspace=root,
                            operator_confirmed=True,
                            target_path=idc23_root,
                        )
            state = onboarding.load_dependency_onboarding_state(root)

        self.assertEqual(result["status"], "recorded")
        self.assertFalse(result["git_worktree_add_invoked"])
        self.assertTrue(result["setx_invoked"])
        self.assertFalse(any("worktree" in command for command in commands))
        self.assertTrue(any(command[:2] == ["setx", onboarding.DIGITAL_3D_CAR_REPO_IDC23_ENV] for command in commands))
        self.assertEqual(Path(state["registered_paths"]["digital_3d_car_repo_idc23"]), idc23_root.resolve())

    def test_bmw_ci_requirements_status_emits_setup_action_for_missing_imports(self) -> None:
        from sg_preflight import dependency_onboarding as onboarding

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bmw_root = root / "digital-3d-car-models"
            idc23_root = root / "worktrees" / "assets-idc23"
            (bmw_root / "cars" / "BMW").mkdir(parents=True)
            write_text(bmw_root / "ci" / "scripts" / "requirements.txt", "PyYAML\nPillow\n")
            write_text(idc23_root / "ci" / "scripts" / "test" / "main.py", "print('fixture')\n")
            (idc23_root / "cars" / "BMW" / "_Shared").mkdir(parents=True)

            with mock.patch.dict(
                os.environ,
                {
                    "Digital-3D-Car-Repo": str(bmw_root),
                    "Digital-3D-Car-Repo-IDC23": str(idc23_root),
                },
                clear=True,
            ):
                with mock.patch.object(onboarding, "_raco_install_roots", return_value=[]):
                    with mock.patch.object(onboarding, "_onedrive_raco_sources", return_value=[]):
                        with mock.patch.object(onboarding, "_blender_path_candidates", return_value=[]):
                            with mock.patch.object(onboarding, "_find_executable", return_value=None):
                                payload = onboarding.build_dependency_onboarding_status(workspace=root)

        item = next(item for item in payload["items"] if item["key"] == "bmw_ci_requirements")
        action = item["setup_action"]
        self.assertEqual(item["status"], "missing")
        self.assertEqual(action["id"], "setup-bmw-ci-requirements")
        self.assertTrue(action["requires_confirmation"])
        self.assertIn(".venv_bmw_ci", action["command_preview"])
        self.assertIn("pip install -r", action["command_preview"])

    def test_bmw_ci_base_python_uses_py313_launcher_when_frozen(self) -> None:
        from sg_preflight import dependency_onboarding as onboarding

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            py_launcher = root / "Windows" / "py.exe"
            py313 = root / "Python313" / "python.exe"
            fallback_python = root / "WindowsApps" / "python.exe"
            write_text(py_launcher, "launcher\n")
            write_text(py313, "python\n")
            write_text(fallback_python, "python\n")

            def _find_executable(name: str) -> Path | None:
                if name == "py.exe":
                    return py_launcher
                if name == "python.exe":
                    return fallback_python
                return None

            def _run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                self.assertEqual(command[1], "-3.13")
                self.assertIn("creationflags", kwargs)
                return _completed(command, stdout=f"{py313}\n")

            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(onboarding.sys, "frozen", True, create=True):
                    with mock.patch.object(onboarding.sys, "executable", r"C:\bundle\sgfx-preflight.exe"):
                        with mock.patch.object(onboarding, "_find_executable", side_effect=_find_executable):
                            with mock.patch.object(onboarding.subprocess, "run", side_effect=_run):
                                base_python = onboarding._base_python_for_bmw_ci_venv()

        self.assertEqual(base_python, py313.resolve())

    def test_bmw_ci_requirements_setup_builds_venv_installs_existing_requirements_and_records_python(self) -> None:
        from sg_preflight import dependency_onboarding as onboarding

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            base_python = root / "sgfx-venv" / "python.exe"
            path_python = root / "system" / "python.exe"
            bmw_root = root / "digital-3d-car-models"
            idc23_root = root / "worktrees" / "assets-idc23"
            idc23_requirements = idc23_root / "ci" / "scripts" / "requirements.txt"
            write_text(base_python, "python\n")
            write_text(path_python, "python\n")
            (bmw_root / "cars" / "BMW").mkdir(parents=True)
            write_text(idc23_requirements, "PyYAML\nPillow\n")
            write_text(idc23_root / "ci" / "scripts" / "test" / "main.py", "print('fixture')\n")
            (idc23_root / "cars" / "BMW" / "_Shared").mkdir(parents=True)
            commands: list[list[str]] = []

            def _find_executable(name: str) -> Path | None:
                return path_python if name in {"python.exe", "python", "py.exe", "py"} else None

            def _run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                self.assertIn("stdin", kwargs)
                commands.append(command)
                if command[1:3] == ["-m", "venv"]:
                    _write_bmw_ci_python(idc23_root)
                return _completed(command)

            with mock.patch.dict(
                os.environ,
                {
                    "Digital-3D-Car-Repo": str(bmw_root),
                    "Digital-3D-Car-Repo-IDC23": str(idc23_root),
                },
                clear=True,
            ):
                with mock.patch.object(onboarding, "_raco_install_roots", return_value=[]):
                    with mock.patch.object(onboarding, "_onedrive_raco_sources", return_value=[]):
                        with mock.patch.object(onboarding, "_blender_path_candidates", return_value=[]):
                            with mock.patch.object(onboarding, "_find_executable", side_effect=_find_executable):
                                with mock.patch.object(onboarding.sys, "frozen", False, create=True):
                                    with mock.patch.object(onboarding.sys, "executable", str(base_python)):
                                        with mock.patch.object(onboarding.subprocess, "run", side_effect=_run):
                                            result = onboarding.run_dependency_setup_action(
                                                action_id="setup-bmw-ci-requirements",
                                                workspace=root,
                                                operator_confirmed=True,
                                            )
            state = onboarding.load_dependency_onboarding_state(root)
            venv_python = idc23_root / ".venv_bmw_ci" / "Scripts" / "python.exe"

        self.assertEqual(result["status"], "recorded")
        self.assertEqual(Path(result["path"]), venv_python.resolve())
        self.assertEqual(Path(state["registered_paths"]["bmw_pipeline_python"]), venv_python.resolve())
        missing_requirements = {Path(path).resolve() for path in result["missing_requirements"]}
        self.assertIn((bmw_root / "ci" / "scripts" / "requirements.txt").resolve(), missing_requirements)
        venv_commands = [command for command in commands if command[1:3] == ["-m", "venv"]]
        self.assertTrue(venv_commands)
        self.assertEqual(Path(venv_commands[0][0]), base_python.resolve())
        self.assertIn("--clear", venv_commands[0])
        self.assertTrue(any(command[1:4] == ["-m", "pip", "install"] for command in commands))
        self.assertTrue(any(command[-1] == onboarding.BMW_CI_IMPORT_PROBE for command in commands))

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
                with mock.patch.object(onboarding, "_candidate_bmw_repo_paths", return_value=[]):
                    with mock.patch.object(onboarding, "_candidate_idc23_repo_paths", return_value=[]):
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
                with mock.patch.object(onboarding, "_candidate_bmw_repo_paths", return_value=[]):
                    with mock.patch.object(onboarding, "_candidate_idc23_repo_paths", return_value=[]):
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
