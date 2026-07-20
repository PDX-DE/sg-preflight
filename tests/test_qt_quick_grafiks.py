from __future__ import annotations

from dataclasses import replace
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock


PYSIDE_AVAILABLE = importlib.util.find_spec("PySide6") is not None

if PYSIDE_AVAILABLE:
    from PySide6.QtCore import QObject, Signal


    class _FakeProcess(QObject):
        started = Signal()
        errorOccurred = Signal(object)
        finished = Signal(int, object)

        def __init__(self) -> None:
            super().__init__()
            self.program = ""
            self.arguments: list[str] = []
            self.working_directory = ""
            self.start_calls = 0
            self.kill_calls = 0
            self.deleted = False

        def setProgram(self, program: str) -> None:
            self.program = program

        def setArguments(self, arguments: list[str]) -> None:
            self.arguments = list(arguments)

        def setWorkingDirectory(self, working_directory: str) -> None:
            self.working_directory = working_directory

        def start(self) -> None:
            self.start_calls += 1

        def kill(self) -> None:
            self.kill_calls += 1

        def deleteLater(self) -> None:
            self.deleted = True


    class _FakeElapsedTimer:
        def __init__(self) -> None:
            self.valid = False
            self.elapsed_ms = 0

        def start(self) -> None:
            self.valid = True

        def isValid(self) -> bool:
            return self.valid

        def elapsed(self) -> int:
            return self.elapsed_ms


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
class TestGrafiksLaunchSpec(unittest.TestCase):
    def test_missing_and_invalid_runtime_fail_closed_without_paths_in_errors(self) -> None:
        from sg_preflight.desktop.qt_quick_grafiks import build_grafiks_launch_spec

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            private_exe = root / "private" / "sgfx_screens.exe"
            private_exe.parent.mkdir()
            private_exe.write_bytes(b"fixture")
            with mock.patch(
                "sg_preflight.desktop.qt_quick_grafiks._resolve_grafiks_shell_exe",
                return_value=None,
            ):
                missing = build_grafiks_launch_spec(
                    "G65",
                    workspace=root,
                    bmw_root=None,
                )
            with (
                mock.patch(
                    "sg_preflight.desktop.qt_quick_grafiks._resolve_grafiks_shell_exe",
                    return_value=private_exe,
                ),
                mock.patch(
                    "sg_preflight.desktop.qt_quick_grafiks._grafiks_runtime_issue",
                    return_value="companions_4",
                ),
            ):
                invalid = build_grafiks_launch_spec(
                    "G65",
                    workspace=root,
                    bmw_root=None,
                )

        self.assertEqual(missing.error_code, "grafiks_missing")
        self.assertIsNone(missing.executable)
        self.assertEqual(invalid.error_code, "grafiks_runtime_invalid")
        self.assertNotIn(str(private_exe), missing.safe_detail + invalid.safe_detail)

    def test_valid_spec_retains_the_exact_confirmed_executable_and_arguments(self) -> None:
        from sg_preflight.desktop.qt_quick_grafiks import build_grafiks_launch_spec

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            exe = root / "Release" / "sgfx_screens.exe"
            exe.parent.mkdir()
            exe.write_bytes(b"fixture")
            command = [str(exe.resolve()), "--profile", "G65"]
            with (
                mock.patch(
                    "sg_preflight.desktop.qt_quick_grafiks._resolve_grafiks_shell_exe",
                    return_value=exe,
                ) as resolver,
                mock.patch(
                    "sg_preflight.desktop.qt_quick_grafiks._grafiks_runtime_issue",
                    return_value="",
                ),
                mock.patch(
                    "sg_preflight.desktop.qt_quick_grafiks._grafiks_shell_command",
                    return_value=command,
                ) as command_builder,
            ):
                spec = build_grafiks_launch_spec(
                    "G65",
                    workspace=root,
                    bmw_root=root / "bmw",
                )

        self.assertEqual(spec.executable, exe.resolve())
        self.assertEqual(spec.arguments, ("--profile", "G65"))
        self.assertEqual(spec.error_code, "")
        resolver.assert_called_once_with(root.resolve())
        command_builder.assert_called_once_with(
            exe.resolve(),
            profile_id="G65",
            bmw_root=(root / "bmw").resolve(),
        )


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
class TestGrafiksHostAdapter(unittest.TestCase):
    def _adapter(
        self,
        *,
        builder: object,
        process: _FakeProcess | None = None,
        timer: _FakeElapsedTimer | None = None,
    ) -> tuple[object, object, _FakeProcess, _FakeElapsedTimer]:
        from sg_preflight.desktop.qt_quick_grafiks import GrafiksHostAdapter
        from tests.test_qt_quick_core import _FakeTaskCoordinator

        coordinator = _FakeTaskCoordinator()
        owned_process = process or _FakeProcess()
        elapsed_timer = timer or _FakeElapsedTimer()
        adapter = GrafiksHostAdapter(
            coordinator=coordinator,
            workspace=Path("workspace"),
            bmw_root=Path("bmw"),
            launch_spec_builder=builder,
            process_factory=lambda _parent: owned_process,
            elapsed_timer=elapsed_timer,
        )
        return adapter, coordinator, owned_process, elapsed_timer

    def test_validation_runs_only_inside_the_coordinator_operation(self) -> None:
        from sg_preflight.desktop.qt_quick_grafiks import GrafiksLaunchSpec

        builder = mock.Mock(
            return_value=GrafiksLaunchSpec(
                None,
                (),
                "grafiks_missing",
                "Grafiks is unavailable in this installation.",
            )
        )
        adapter, coordinator, process, _timer = self._adapter(builder=builder)
        self.assertTrue(adapter.launch("G65"))
        builder.assert_not_called()
        self.assertEqual(adapter.state, "validating")
        identity, operation = coordinator.requests[-1]
        self.assertNotIn("self", operation.__code__.co_freevars)

        spec = operation()
        builder.assert_called_once_with(
            "G65",
            workspace=Path("workspace"),
            bmw_root=Path("bmw"),
        )
        coordinator.succeed(identity, spec)

        self.assertEqual(adapter.state, "failed")
        self.assertEqual(adapter.errorCode, "grafiks_missing")
        self.assertEqual(process.start_calls, 0)

    def test_confirmed_start_hides_then_sustained_exit_restores(self) -> None:
        from sg_preflight.desktop.qt_quick_grafiks import GrafiksLaunchSpec

        with tempfile.TemporaryDirectory() as temp_dir:
            exe = Path(temp_dir) / "sgfx_screens.exe"
            exe.write_bytes(b"fixture")
            spec = GrafiksLaunchSpec(exe.resolve(), ("--profile", "G65"))
            adapter, coordinator, process, timer = self._adapter(
                builder=mock.Mock(return_value=spec)
            )
            hidden: list[bool] = []
            restored: list[bool] = []
            adapter.hideRequested.connect(lambda: hidden.append(True))
            adapter.restoreRequested.connect(lambda: restored.append(True))

            self.assertTrue(adapter.launch("G65"))
            identity, operation = coordinator.requests[-1]
            coordinator.succeed(identity, operation())
            self.assertEqual(adapter.state, "starting")
            self.assertEqual(process.program, str(exe.resolve()))
            self.assertEqual(process.arguments, ["--profile", "G65"])
            self.assertEqual(process.working_directory, str(exe.resolve().parent))
            self.assertEqual(hidden, [])

            process.started.emit()
            self.assertEqual(adapter.state, "running")
            self.assertEqual(hidden, [True])
            timer.elapsed_ms = 1600
            process.finished.emit(0, object())

        self.assertEqual(adapter.state, "idle")
        self.assertEqual(adapter.errorCode, "")
        self.assertEqual(restored, [True])
        self.assertTrue(process.deleted)

    def test_immediate_zero_and_nonzero_exit_are_both_classified_and_restored(self) -> None:
        from sg_preflight.desktop.qt_quick_grafiks import GrafiksLaunchSpec

        for exit_code in (0, 23):
            with self.subTest(exit_code=exit_code):
                with tempfile.TemporaryDirectory() as temp_dir:
                    exe = Path(temp_dir) / "sgfx_screens.exe"
                    exe.write_bytes(b"fixture")
                    spec = GrafiksLaunchSpec(exe.resolve(), ())
                    adapter, coordinator, process, timer = self._adapter(
                        builder=mock.Mock(return_value=spec)
                    )
                    restored: list[bool] = []
                    adapter.restoreRequested.connect(lambda: restored.append(True))
                    adapter.launch("G65")
                    identity, operation = coordinator.requests[-1]
                    coordinator.succeed(identity, operation())
                    process.started.emit()
                    timer.elapsed_ms = 100
                    process.finished.emit(exit_code, object())

                self.assertEqual(adapter.state, "failed")
                self.assertEqual(adapter.errorCode, "grafiks_early_exit")
                self.assertEqual(restored, [True])

    def test_spawn_failure_keeps_the_qt_window_visible(self) -> None:
        from sg_preflight.desktop.qt_quick_grafiks import GrafiksLaunchSpec

        with tempfile.TemporaryDirectory() as temp_dir:
            exe = Path(temp_dir) / "sgfx_screens.exe"
            exe.write_bytes(b"fixture")
            adapter, coordinator, process, _timer = self._adapter(
                builder=mock.Mock(return_value=GrafiksLaunchSpec(exe.resolve(), ()))
            )
            hidden: list[bool] = []
            restored: list[bool] = []
            adapter.hideRequested.connect(lambda: hidden.append(True))
            adapter.restoreRequested.connect(lambda: restored.append(True))
            adapter.launch("G65")
            identity, operation = coordinator.requests[-1]
            coordinator.succeed(identity, operation())

            process.errorOccurred.emit(object())

        self.assertEqual(adapter.state, "failed")
        self.assertEqual(adapter.errorCode, "grafiks_spawn_failed")
        self.assertEqual(hidden, [])
        self.assertEqual(restored, [])

    def test_stale_process_signals_cannot_release_a_retry(self) -> None:
        from sg_preflight.desktop.qt_quick_grafiks import GrafiksHostAdapter, GrafiksLaunchSpec
        from tests.test_qt_quick_core import _FakeTaskCoordinator

        with tempfile.TemporaryDirectory() as temp_dir:
            exe = Path(temp_dir) / "sgfx_screens.exe"
            exe.write_bytes(b"fixture")
            spec = GrafiksLaunchSpec(exe.resolve(), ())
            coordinator = _FakeTaskCoordinator()
            first_process = _FakeProcess()
            retry_process = _FakeProcess()
            processes = iter((first_process, retry_process))
            adapter = GrafiksHostAdapter(
                coordinator=coordinator,
                workspace=Path("workspace"),
                launch_spec_builder=mock.Mock(return_value=spec),
                process_factory=lambda _parent: next(processes),
                elapsed_timer=_FakeElapsedTimer(),
            )

            self.assertTrue(adapter.launch("G65"))
            first_identity, first_operation = coordinator.requests[-1]
            coordinator.succeed(first_identity, first_operation())
            first_process.started.emit()
            first_process.errorOccurred.emit(object())
            self.assertEqual(adapter.state, "failed")

            self.assertTrue(adapter.launch("G65"))
            retry_identity, retry_operation = coordinator.requests[-1]
            coordinator.succeed(retry_identity, retry_operation())
            self.assertEqual(adapter.state, "starting")

            first_process.finished.emit(1, object())

        self.assertEqual(adapter.state, "starting")
        self.assertFalse(retry_process.deleted)

    def test_stale_validation_is_ignored_and_shutdown_kills_without_waiting(self) -> None:
        from sg_preflight.desktop.qt_quick_grafiks import GrafiksLaunchSpec

        with tempfile.TemporaryDirectory() as temp_dir:
            exe = Path(temp_dir) / "sgfx_screens.exe"
            exe.write_bytes(b"fixture")
            spec = GrafiksLaunchSpec(exe.resolve(), ())
            adapter, coordinator, process, _timer = self._adapter(
                builder=mock.Mock(return_value=spec)
            )
            hidden: list[bool] = []
            restored: list[str] = []
            adapter.hideRequested.connect(lambda: hidden.append(True))
            adapter.restoreRequested.connect(lambda: restored.append(adapter.state))
            adapter.launch("G65")
            identity, operation = coordinator.requests[-1]
            coordinator.succeed(replace(identity, generation=identity.generation + 1), operation())
            self.assertEqual(process.start_calls, 0)
            coordinator.succeed(identity, spec)
            process.started.emit()
            adapter.shutdown()
            process.finished.emit(0, object())

        self.assertEqual(process.kill_calls, 1)
        self.assertEqual(restored, ["idle"])
        self.assertEqual(adapter.state, "idle")

    def test_idle_shutdown_notifies_can_launch_and_rejects_later_work(self) -> None:
        adapter, coordinator, process, _timer = self._adapter(builder=mock.Mock())
        notifications: list[bool] = []
        adapter.stateChanged.connect(lambda: notifications.append(adapter.canLaunch))

        self.assertTrue(adapter.canLaunch)
        adapter.shutdown()

        self.assertFalse(adapter.canLaunch)
        self.assertEqual(notifications, [False])
        self.assertFalse(adapter.launch("G65"))
        self.assertEqual(coordinator.requests, [])
        self.assertEqual(process.kill_calls, 0)


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
class TestGrafiksControllerAndHostBindings(unittest.TestCase):
    def test_capability_handoff_uses_only_the_canonical_current_profile(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from tests.test_qt_quick_core import _FakeTaskCoordinator

        host = mock.Mock()
        host.launch.return_value = True
        controller = DesktopController(
            workspace=Path("workspace"),
            initial_profile_id="G65",
            task_coordinator=_FakeTaskCoordinator(),
            grafiks_host=host,
        )

        self.assertFalse(controller.invokeCapability("grafiks.launch", {"profile_id": "G70"}))
        self.assertEqual(controller.capabilityError, "The 3D inspection profile selection is invalid.")
        host.launch.assert_not_called()
        self.assertTrue(controller.invokeCapability("grafiks.launch", {"profile_id": "g65"}))
        self.assertEqual(controller.capabilityError, "")
        self.assertEqual(controller.capabilityState, "completed")
        self.assertEqual(controller.activeActionLabel, "Open 3D inspection")
        self.assertEqual(
            controller.lastActionResult,
            {
                "capabilityId": "grafiks.launch",
                "label": "Open 3D inspection",
                "status": "completed",
                "lines": [],
                "outputRoot": "",
            },
        )
        host.launch.assert_called_once_with("G65")

        host.launch.return_value = False
        self.assertFalse(controller.invokeCapability("grafiks.launch", {"profile_id": "G65"}))
        self.assertEqual(controller.capabilityState, "failed")
        self.assertEqual(controller.activeActionLabel, "Open 3D inspection")
        self.assertEqual(controller.lastActionResult, {})
        controller.shutdown()

    def test_controller_exposes_only_the_typed_launch_slot(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from tests.test_qt_quick_core import _FakeTaskCoordinator

        host = mock.Mock()
        host.launch.return_value = True
        controller = DesktopController(
            workspace=Path("workspace"),
            initial_profile_id="G65",
            task_coordinator=_FakeTaskCoordinator(),
            grafiks_host=host,
        )
        self.assertTrue(controller.launchGrafiks())
        host.launch.assert_called_once_with("G65")
        methods = {
            bytes(controller.metaObject().method(index).methodSignature()).decode("ascii")
            for index in range(controller.metaObject().methodOffset(), controller.metaObject().methodCount())
        }
        self.assertIn("launchGrafiks()", methods)
        rendered = "\n".join(methods).casefold()
        self.assertNotIn("executable", rendered)
        self.assertNotIn("process", rendered)
        self.assertNotIn("path", rendered)
        controller.shutdown()
        host.shutdown.assert_called_once_with()

    def test_qml_binds_launch_state_without_receiving_a_path_or_process(self) -> None:
        qml = (
            Path(__file__).resolve().parents[1]
            / "sg_preflight"
            / "desktop"
            / "qml"
            / "Main.qml"
        ).read_text(encoding="utf-8")

        self.assertIn('objectName: "grafiksLaunchControl"', qml)
        self.assertIn('desktopController.invokeCapability("grafiks.launch"', qml)
        self.assertNotIn("desktopController.launchGrafiks", qml)
        self.assertIn("grafiksHost.state", qml)
        self.assertIn("grafiksHost.errorSummary", qml)
        self.assertNotIn("grafiksHost.executable", qml)
        self.assertNotIn("grafiksHost.process", qml)

    def test_operator_copy_uses_3d_inspection_while_internal_ids_remain_stable(self) -> None:
        root = Path(__file__).resolve().parents[1]
        main = (root / "sg_preflight" / "desktop" / "qml" / "Main.qml").read_text(encoding="utf-8")
        home = (root / "sg_preflight" / "desktop" / "qml" / "components" / "HomePage.qml").read_text(encoding="utf-8")
        controller = (root / "sg_preflight" / "desktop" / "qt_quick_controller.py").read_text(encoding="utf-8")
        adapter = (root / "sg_preflight" / "desktop" / "qt_quick_grafiks.py").read_text(encoding="utf-8")

        self.assertIn("Open 3D inspection", main + home)
        self.assertIn('"grafiks.launch"', main + controller)
        self.assertIn("GrafiksHostAdapter", adapter)
        for source in (main, home, controller, adapter):
            self.assertNotIn('"Grafiks', source)
            self.assertNotIn("'Grafiks", source)

    def test_host_window_helpers_hide_only_on_request_and_restore_fully(self) -> None:
        from sg_preflight.desktop.qt_quick_app import _hide_qt_windows, _restore_qt_windows

        root = mock.Mock()
        engine = mock.Mock()
        engine.rootObjects.return_value = [root]

        _hide_qt_windows(engine)
        root.hide.assert_called_once_with()
        root.show.assert_not_called()
        _restore_qt_windows(engine)
        root.show.assert_called_once_with()
        root.raise_.assert_called_once_with()
        root.requestActivate.assert_called_once_with()

        self.assertIs(engine.rootObjects.return_value[0], root)
        root.refresh.assert_not_called()
        root.initialize.assert_not_called()
        root.navigate.assert_not_called()
        root.selectProfile.assert_not_called()

    def test_adapter_source_has_no_blocking_wait_or_poll_loop(self) -> None:
        source_path = (
            Path(__file__).resolve().parents[1]
            / "sg_preflight"
            / "desktop"
            / "qt_quick_grafiks.py"
        )
        source = source_path.read_text(encoding="utf-8") if source_path.exists() else ""

        self.assertNotIn("waitForFinished", source)
        self.assertNotIn("waitForStarted", source)
        self.assertNotIn("time.sleep", source)
        self.assertNotIn("processEvents", source)


if __name__ == "__main__":
    unittest.main()
