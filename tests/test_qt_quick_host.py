from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
PYSIDE_AVAILABLE = importlib.util.find_spec("PySide6") is not None


class TestQtQuickHostSource(unittest.TestCase):
    def test_python_host_uses_a_standalone_qml_engine_without_widgets(self) -> None:
        source = (ROOT / "sg_preflight" / "desktop" / "qt_quick_app.py").read_text(encoding="utf-8")

        self.assertIn("QGuiApplication", source)
        self.assertIn("QQmlApplicationEngine", source)
        self.assertIn("setContextProperty", source)
        self.assertIn("setInitialProperties", source)
        self.assertIn('"surfaceModel"', source)
        self.assertIn('"desktopController"', source)
        self.assertIn("rootObjects()", source)
        self.assertIn("runtime_asset_path", source)
        self.assertNotIn("QQuickWidget", source)
        self.assertNotIn("QApplication", source)
        self.assertNotIn("QWidget", source)
        self.assertNotIn("sg_preflight.dashboard.main", source)

    def test_qml_is_a_real_navigation_container_without_mock_pages(self) -> None:
        source = (ROOT / "sg_preflight" / "desktop" / "qml" / "Main.qml").read_text(encoding="utf-8")

        self.assertIn("ApplicationWindow", source)
        self.assertIn("required property var surfaceModel", source)
        self.assertIn("required property var desktopController", source)
        self.assertIn("ListView", source)
        self.assertIn("model: window.surfaceModel", source)
        self.assertIn("desktopController.navigate", source)
        self.assertIn("desktopController.pageTitle", source)
        self.assertIn("desktopController.pageSubtitle", source)
        self.assertIn("desktopController.currentPayload", source)
        self.assertIn("Component.onCompleted: desktopController.initialize()", source)
        self.assertIn('objectName: "pageContentHost"', source)
        self.assertIn("states:", source)
        self.assertIn("transitions:", source)
        self.assertIn("NumberAnimation", source)
        self.assertIn("BusyIndicator", source)
        self.assertNotIn("dummy", source.casefold())
        self.assertNotIn("sample data", source.casefold())
        self.assertNotIn("QQuickWidget", source)


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
class TestQtQuickHostRuntime(unittest.TestCase):
    def _run_headless(self, script: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["QT_QPA_PLATFORM"] = "offscreen"
        environment["QSG_RHI_BACKEND"] = "software"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [sys.executable, "-B", "-c", textwrap.dedent(script)],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )

    def test_runtime_factory_loads_root_binds_bridges_and_owns_qobjects(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_headless(
                f"""
                from sg_preflight.desktop.qt_quick_app import create_qt_quick_runtime
                runtime = create_qt_quick_runtime(
                    workspace={temp_dir!r},
                    initial_profile_id="G65",
                    argv=["sgfx-test"],
                )
                root = runtime.engine.rootObjects()[0]
                print(root.objectName())
                print(runtime.surface_model.rowCount())
                print(runtime.controller.currentPageId)
                print(runtime.controller.pageTitle)
                print(root.property("surfaceModel") is runtime.surface_model)
                print(root.property("desktopController") is runtime.controller)
                print(runtime.surface_model.parent() is runtime.engine)
                print(runtime.controller.parent() is runtime.engine)
                print(runtime.task_coordinator.parent() is runtime.engine)
                runtime.close()
                """
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["sgfxQtQuickWindow", "19", "about", "About", "True", "True", "True", "True", "True"],
        )

    def test_runtime_resolves_an_omitted_profile_after_qml_completion_without_writing_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_headless(
                f"""
                from pathlib import Path
                import time
                from sg_preflight.desktop.qt_quick_app import create_qt_quick_runtime
                workspace = Path({temp_dir!r})
                runtime = create_qt_quick_runtime(workspace=workspace, argv=["sgfx-test"])
                deadline = time.monotonic() + 5
                while not runtime.controller.currentProfileId and time.monotonic() < deadline:
                    runtime.application.processEvents()
                    time.sleep(0.005)
                print(runtime.controller.currentProfileId)
                print(sum(1 for path in workspace.rglob("*") if path.is_file()))
                runtime.close()
                """
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        profile_id, file_count = result.stdout.splitlines()
        self.assertRegex(profile_id, r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
        self.assertEqual(file_count, "0")

    def test_runtime_close_has_exact_order_and_is_idempotent(self) -> None:
        from sg_preflight.desktop.qt_quick_app import QtQuickRuntime

        events: list[str] = []

        class Recorder:
            def __init__(self, name: str) -> None:
                self.name = name

            def shutdown(self, *args: object, **kwargs: object) -> None:
                events.append(self.name)

            def close(self) -> None:
                events.append(self.name)

        class Engine:
            def rootObjects(self) -> list[Recorder]:
                return [Recorder("root")]

            def clearComponentCache(self) -> None:
                events.append("engine")

        class Application:
            def processEvents(self) -> None:
                events.append("application")

        runtime = QtQuickRuntime(
            application=Application(),
            engine=Engine(),
            surface_model=object(),
            controller=Recorder("controller"),
            task_coordinator=Recorder("coordinator"),
        )

        runtime.close()
        runtime.close()

        self.assertEqual(events, ["controller", "coordinator", "root", "engine", "application"])

    def test_existing_qml_without_a_root_cleans_controller_then_coordinator(self) -> None:
        from sg_preflight.desktop import qt_quick_app

        events: list[str] = []
        context_bindings: dict[str, object] = {}
        initial_properties: dict[str, object] = {}

        class Context:
            def setContextProperty(self, name: str, value: object) -> None:
                context_bindings[name] = value

        class Engine:
            def __init__(self) -> None:
                self.context = Context()

            def rootContext(self) -> Context:
                return self.context

            def setInitialProperties(self, properties: dict[str, object]) -> None:
                initial_properties.update(properties)

            def load(self, source: object) -> None:
                events.append("load")

            def rootObjects(self) -> list[object]:
                return []

        class Coordinator:
            def __init__(self, *, parent: object) -> None:
                self.parent = parent

            def shutdown(self, *args: object, **kwargs: object) -> None:
                events.append("coordinator")

        class Controller:
            def __init__(self, **kwargs: object) -> None:
                self.kwargs = kwargs

            def shutdown(self) -> None:
                events.append("controller")

        class SurfaceModel:
            def __init__(self, *, parent: object) -> None:
                self.parent = parent

        with tempfile.TemporaryDirectory() as temp_dir:
            qml_path = Path(temp_dir) / "Main.qml"
            qml_path.write_text("fixture\n", encoding="utf-8")
            with mock.patch.object(qt_quick_app, "_application", return_value=object()):
                with mock.patch.object(qt_quick_app, "QQmlApplicationEngine", Engine):
                    with mock.patch.object(qt_quick_app, "PageTaskCoordinator", Coordinator):
                        with mock.patch.object(qt_quick_app, "DesktopController", Controller):
                            with mock.patch.object(qt_quick_app, "SurfaceRegistryModel", SurfaceModel):
                                with self.assertRaisesRegex(
                                    RuntimeError,
                                    "The Qt Quick interface could not be initialized.",
                                ):
                                    qt_quick_app.create_qt_quick_runtime(
                                        workspace=temp_dir,
                                        qml_path=qml_path,
                                        argv=["sgfx-test"],
                                    )

        self.assertEqual(events, ["load", "controller", "coordinator"])
        self.assertIs(context_bindings["surfaceModel"], initial_properties["surfaceModel"])
        self.assertIs(context_bindings["desktopController"], initial_properties["desktopController"])

    def test_factory_construction_failure_cleans_every_created_owner_and_sanitizes(self) -> None:
        from sg_preflight.desktop import qt_quick_app

        events: list[str] = []

        class Engine:
            pass

        class Coordinator:
            def __init__(self, *, parent: object) -> None:
                self.parent = parent

            def shutdown(self, *args: object, **kwargs: object) -> None:
                events.append("coordinator")

        class Controller:
            def __init__(self, **kwargs: object) -> None:
                self.kwargs = kwargs

            def shutdown(self) -> None:
                events.append("controller")

        with tempfile.TemporaryDirectory() as temp_dir:
            qml_path = Path(temp_dir) / "Main.qml"
            qml_path.write_text("fixture\n", encoding="utf-8")
            with mock.patch.object(qt_quick_app, "_application", return_value=object()):
                with mock.patch.object(qt_quick_app, "QQmlApplicationEngine", Engine):
                    with mock.patch.object(qt_quick_app, "PageTaskCoordinator", Coordinator):
                        with mock.patch.object(qt_quick_app, "DesktopController", Controller):
                            with mock.patch.object(
                                qt_quick_app,
                                "SurfaceRegistryModel",
                                side_effect=RuntimeError(r"C:\private\operator detail"),
                            ):
                                with self.assertRaisesRegex(
                                    RuntimeError,
                                    "^The Qt Quick interface could not be initialized[.]$",
                                ) as captured:
                                    qt_quick_app.create_qt_quick_runtime(
                                        workspace=temp_dir,
                                        qml_path=qml_path,
                                        argv=["sgfx-test"],
                                    )

        self.assertEqual(events, ["controller", "coordinator"])
        self.assertNotIn("private", str(captured.exception).casefold())

    def test_missing_qml_is_sanitized_before_runtime_construction(self) -> None:
        from sg_preflight.desktop import qt_quick_app

        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "private" / "Missing.qml"
            with mock.patch.object(qt_quick_app, "QQmlApplicationEngine") as engine:
                with self.assertRaisesRegex(
                    RuntimeError,
                    "^The Qt Quick interface files are unavailable[.]$",
                ) as captured:
                    qt_quick_app.create_qt_quick_runtime(
                        workspace=temp_dir,
                        qml_path=missing,
                        argv=["sgfx-test"],
                    )

        engine.assert_not_called()
        self.assertNotIn(str(missing), str(captured.exception))

    def test_run_host_retains_runtime_and_closes_it_in_finally(self) -> None:
        from sg_preflight.desktop import qt_quick_app

        runtime = mock.Mock()
        runtime.application.exec.side_effect = RuntimeError("event loop stopped")
        with mock.patch.object(qt_quick_app, "create_qt_quick_runtime", return_value=runtime) as factory:
            with self.assertRaisesRegex(RuntimeError, "event loop stopped"):
                qt_quick_app.run_qt_quick_app(
                    workspace=Path(r"C:\workspace"),
                    initial_profile_id="G65",
                    bmw_root=Path(r"C:\bmw"),
                )

        factory.assert_called_once_with(
            workspace=Path(r"C:\workspace"),
            initial_profile_id="G65",
            bmw_root=Path(r"C:\bmw"),
        )
        runtime.close.assert_called_once_with()


class TestQtQuickOptionalDependency(unittest.TestCase):
    def test_missing_optional_pyside_dependency_becomes_a_sanitized_runtime_error(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                "-c",
                textwrap.dedent(
                    f"""
                    import builtins
                    import sys
                    sys.path.insert(0, {str(ROOT)!r})
                    original_import = builtins.__import__
                    def guarded_import(name, *args, **kwargs):
                        if name == "PySide6" or name.startswith("PySide6."):
                            raise ModuleNotFoundError("blocked optional dependency")
                        return original_import(name, *args, **kwargs)
                    builtins.__import__ = guarded_import
                    from sg_preflight.desktop.app import run_desktop_app
                    try:
                        run_desktop_app(workspace={str(ROOT)!r}, initial_mode="qt-quick")
                    except RuntimeError as exc:
                        print(str(exc))
                    else:
                        raise SystemExit("missing dependency unexpectedly accepted")
                    """
                ),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )

        combined = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, msg=combined)
        self.assertIn("PySide6", result.stdout)
        self.assertIn(".[desktop]", result.stdout)
        self.assertNotIn("traceback", combined.casefold())


if __name__ == "__main__":
    unittest.main()
