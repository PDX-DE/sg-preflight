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
        self.assertIn('"shellModel"', source)
        self.assertIn('"desktopController"', source)
        self.assertIn("rootObjects()", source)
        self.assertIn("runtime_asset_path", source)
        self.assertNotIn("QQuickWidget", source)
        self.assertNotIn("QApplication", source)
        self.assertNotIn("QWidget", source)
        self.assertNotIn("sg_preflight.dashboard.main", source)

    def test_qml_is_a_real_navigation_container_without_mock_pages(self) -> None:
        source = (ROOT / "sg_preflight" / "desktop" / "qml" / "Main.qml").read_text(encoding="utf-8")
        components = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "sg_preflight" / "desktop" / "qml" / "components").glob("*.qml")
        )
        shell_source = source + components

        self.assertIn("ApplicationWindow", source)
        self.assertIn("required property var surfaceModel", source)
        self.assertIn("required property var shellModel", source)
        self.assertIn("required property var desktopController", source)
        self.assertIn("ListView", shell_source)
        self.assertIn("model: root.shellModel", shell_source)
        self.assertIn("desktopController.navigate", shell_source)
        self.assertIn("desktopController.pageTitle", source)
        self.assertIn("desktopController.pageSubtitle", source)
        self.assertIn("desktopController.currentPayload", source)
        self.assertIn("Component.onCompleted: desktopController.initialize()", source)
        self.assertIn('objectName: "pageContentHost"', source)
        self.assertIn("NumberAnimation", shell_source)
        self.assertIn("ScrollView", shell_source)
        self.assertNotIn("dummy", source.casefold())
        self.assertNotIn("sample data", source.casefold())
        self.assertNotIn("QQuickWidget", source)


class TestQtQuickShell(unittest.TestCase):
    def _run_headless(self, script: str, *, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["QT_QPA_PLATFORM"] = "offscreen"
        environment["QSG_RHI_BACKEND"] = "software"
        environment["QT_QUICK_CONTROLS_STYLE"] = "Basic"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [sys.executable, "-B", "-c", textwrap.dedent(script)],
            cwd=cwd,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

    def test_shell_qml_uses_registry_components_theme_accessibility_and_local_overlays(self) -> None:
        qml_root = ROOT / "sg_preflight" / "desktop" / "qml"
        expected = {
            "Main.qml",
            "components/NavigationSidebar.qml",
            "components/HomePage.qml",
            "components/JumpPalette.qml",
            "components/ShortcutHelp.qml",
            "components/StatusBadge.qml",
            "SGFX/Theme.qml",
            "SGFX/qmldir",
        }
        self.assertTrue(all((qml_root / relative).is_file() for relative in expected))
        main = (qml_root / "Main.qml").read_text(encoding="utf-8")
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((qml_root / "components").glob("*.qml"))
        )
        theme = (qml_root / "SGFX" / "Theme.qml").read_text(encoding="utf-8")
        qmldir = (qml_root / "SGFX" / "qmldir").read_text(encoding="utf-8")
        self.assertIn("import SGFX 1.0", main)
        self.assertIn("required property var shellModel", main)
        self.assertIn("model: root.shellModel", combined)
        self.assertIn("Accessible.name", combined)
        self.assertIn("Accessible.role", combined)
        self.assertIn("activeFocus", combined)
        self.assertIn("ScrollView", combined)
        self.assertIn("profileOptions", main + combined)
        self.assertNotIn("TextField", main.split("components.HomePage", 1)[0])
        for token in ("motionMicro", "motionFeedback", "motionShort", "motionStandard", "motionEmphasis", "motionStagger"):
            self.assertIn(token, theme)
        self.assertIn("readonly property int motionStagger: 70", theme)
        for color in ("#f14c4c", "#cca700", "#89d185", "#8b949e"):
            self.assertIn(color, theme)
        self.assertEqual(qmldir.splitlines(), ["module SGFX", "singleton Theme 1.0 Theme.qml"])
        for shortcut in ("F1", "F2", "F5", "F12", "Esc", 'sequence: "/"'):
            self.assertIn(shortcut, main)

    @unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
    def test_runtime_shell_has_exact_groups_tiles_geometry_and_overlay_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_headless(
                f"""
                import json
                from PySide6.QtCore import QMetaObject, Q_ARG
                from PySide6.QtTest import QTest
                from sg_preflight.desktop.qt_quick_app import create_qt_quick_runtime
                runtime = create_qt_quick_runtime(workspace={temp_dir!r}, initial_profile_id="G65", argv=["sgfx-test"])
                root = runtime.engine.rootObjects()[0]
                runtime.application.processEvents()
                QTest.qWait(50)
                QMetaObject.invokeMethod(root, "updateHomeTileMetrics")
                print(json.dumps({{
                    "groups": root.property("navigationGroupTitles"),
                    "tiles": root.property("homeTileIds").toVariant(),
                    "more": root.property("moreGroupVisible"),
                    "scale": root.property("referenceScale"),
                    "offsetX": root.property("referenceOffsetX"),
                    "offsetY": root.property("referenceOffsetY"),
                    "targetWidth": root.property("firstHomeTileWidth"),
                    "targetHeight": root.property("firstHomeTileHeight"),
                    "layoutValid": root.property("homeTileLayoutValid"),
                    "reduced": [root.property("reducedMotionDuration"), root.property("reducedMotionTravel"), root.property("reducedMotionStagger")],
                }}))
                root.setWidth(1024)
                root.setHeight(640)
                runtime.application.processEvents()
                print(root.property("referenceScale"), root.property("referenceOffsetY"))
                for key in ("F1", "F12", "/", "Esc", "Esc", "Esc", "Esc", "Esc"):
                    QMetaObject.invokeMethod(root, "handleShortcut", Q_ARG(str, key))
                    runtime.application.processEvents()
                print(root.property("jumpOpen"), root.property("helpOpen"), root.property("diagnosticsOpen"), root.property("exitGuidanceVisible"))
                runtime.close()
                """
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        lines = result.stdout.splitlines()
        payload = __import__("json").loads(lines[0])
        self.assertEqual(payload["groups"], ["Daily work", "Delivery", "Screenshots & coverage", "Reviews & digests", "Setup & help"])
        self.assertEqual(payload["tiles"], list(("full-qa-pass", "delivery-checklist", "screenshot-test-state", "manual-review", "daily-digest", "setup-doctor")))
        self.assertFalse(payload["more"])
        self.assertEqual((payload["scale"], payload["offsetX"], payload["offsetY"]), (1, 0, 0))
        self.assertGreaterEqual(payload["targetWidth"], 50)
        self.assertGreaterEqual(payload["targetHeight"], 50)
        self.assertTrue(payload["layoutValid"])
        self.assertEqual(payload["reduced"], [120, 8, 0])
        scale, offset = (float(value) for value in lines[1].split())
        self.assertAlmostEqual(scale, 0.8, places=3)
        self.assertAlmostEqual(offset, 32.0, places=3)
        self.assertEqual(lines[2], "False False False True")

    @unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
    def test_sgfx_singleton_loads_with_developer_import_paths_cleared_outside_checkout(self) -> None:
        qml_root = ROOT / "sg_preflight" / "desktop" / "qml"
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_headless(
                f"""
                import os
                from pathlib import Path
                from PySide6.QtCore import QUrl
                from PySide6.QtGui import QGuiApplication
                from PySide6.QtQml import QQmlComponent, QQmlEngine
                os.environ.pop("QML2_IMPORT_PATH", None)
                os.environ.pop("QML_IMPORT_PATH", None)
                app = QGuiApplication(["sgfx-module-test"])
                engine = QQmlEngine()
                engine.setImportPathList([path for path in engine.importPathList() if {str(ROOT)!r} not in path])
                engine.addImportPath({str(qml_root)!r})
                source = Path({temp_dir!r}) / "Probe.qml"
                source.write_text('import QtQuick\\nimport SGFX 1.0\\nQtObject {{ property int stagger: Theme.motionStagger }}\\n', encoding='utf-8')
                component = QQmlComponent(engine, QUrl.fromLocalFile(str(source)))
                obj = component.create()
                if obj is None:
                    raise SystemExit(" | ".join(error.toString() for error in component.errors()))
                print(obj.property("stagger"))
                obj.deleteLater()
                """,
                cwd=Path(temp_dir),
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        self.assertEqual(result.stdout.strip(), "70")

    @unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
    def test_shortcuts_filter_enter_focus_refresh_active_route_and_home_are_write_free(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_headless(
                f"""
                import json
                from pathlib import Path
                import time
                from PySide6.QtCore import QMetaObject, Q_ARG, QObject, Qt
                from PySide6.QtTest import QTest
                from sg_preflight.desktop.qt_quick_app import create_qt_quick_runtime
                workspace = Path({temp_dir!r})
                before = sorted(str(path.relative_to(workspace)) for path in workspace.rglob("*") if path.is_file())
                runtime = create_qt_quick_runtime(workspace=workspace, initial_profile_id="G65", argv=["sgfx-test"])
                root = runtime.engine.rootObjects()[0]
                deadline = time.monotonic() + 5
                while runtime.controller.pageState == "loading" and time.monotonic() < deadline:
                    runtime.application.processEvents()
                    time.sleep(0.005)
                invoked_f2 = QMetaObject.invokeMethod(root, "handleShortcut", Q_ARG(str, "F2"))
                runtime.application.processEvents()
                f2_focused = root.property("profileSelectorFocused")
                generation = runtime.controller._generation
                invoked_f5 = QMetaObject.invokeMethod(root, "handleShortcut", Q_ARG(str, "F5"))
                refresh_identity = runtime.controller._current_identity
                deadline = time.monotonic() + 5
                while runtime.controller.pageState == "loading" and time.monotonic() < deadline:
                    runtime.application.processEvents()
                    time.sleep(0.005)
                after_home = sorted(str(path.relative_to(workspace)) for path in workspace.rglob("*") if path.is_file())
                invoked_jump = QMetaObject.invokeMethod(root, "handleShortcut", Q_ARG(str, "/"))
                runtime.application.processEvents()
                jump_filter = root.findChild(QObject, "jumpFilter")
                jump_filter.setProperty("text", "risk score")
                QMetaObject.invokeMethod(jump_filter, "forceActiveFocus")
                runtime.application.processEvents()
                QTest.keyClick(root, Qt.Key_Return)
                runtime.application.processEvents()
                print(json.dumps({{
                    "invoked": [invoked_f2, invoked_f5, invoked_jump],
                    "f2Focused": f2_focused,
                    "generationAdvanced": refresh_identity.generation > generation,
                    "refreshTuple": [refresh_identity.profile_id, refresh_identity.page_id, refresh_identity.operation],
                    "jumpClosed": not root.property("jumpOpen"),
                    "route": runtime.controller.currentRouteId,
                    "activeRoute": root.property("activeNavigationRouteId"),
                    "before": before,
                    "afterHome": after_home,
                }}))
                deadline = time.monotonic() + 5
                while runtime.controller.pageState == "loading" and time.monotonic() < deadline:
                    runtime.application.processEvents()
                    time.sleep(0.005)
                runtime.close()
                """
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        payload = __import__("json").loads(result.stdout)
        self.assertEqual(payload["invoked"], [True, True, True])
        self.assertTrue(payload["f2Focused"])
        self.assertTrue(payload["generationAdvanced"])
        self.assertEqual(payload["refreshTuple"], ["G65", "home", "shell_context"])
        self.assertTrue(payload["jumpClosed"])
        self.assertEqual((payload["route"], payload["activeRoute"]), ("risk-score", "risk-score"))
        self.assertEqual(payload["before"], payload["afterHome"])

    @unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
    def test_status_badges_map_semantic_text_and_color_at_runtime(self) -> None:
        qml_root = ROOT / "sg_preflight" / "desktop" / "qml"
        probe_source = b"""import QtQuick
import "components" as Components
Item {
    Components.StatusBadge { objectName: "bad"; status: "error" }
    Components.StatusBadge { objectName: "warn"; status: "incomplete" }
    Components.StatusBadge { objectName: "good"; status: "available" }
    Components.StatusBadge { objectName: "neutral"; status: "not_run" }
}
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_headless(
                f"""
                import json
                import time
                from PySide6.QtCore import QObject, QUrl
                from PySide6.QtQml import QQmlComponent
                from sg_preflight.desktop.qt_quick_app import create_qt_quick_runtime
                runtime = create_qt_quick_runtime(workspace={temp_dir!r}, initial_profile_id="G65", argv=["sgfx-test"])
                deadline = time.monotonic() + 5
                while runtime.controller.pageState == "loading" and time.monotonic() < deadline:
                    runtime.application.processEvents()
                    time.sleep(0.005)
                component = QQmlComponent(runtime.engine)
                component.setData({probe_source!r}, QUrl.fromLocalFile({str(qml_root)!r} + "/"))
                probe = component.create()
                if probe is None:
                    raise SystemExit(" | ".join(error.toString() for error in component.errors()))
                values = {{}}
                for name in ("bad", "warn", "good", "neutral"):
                    badge = probe.findChild(QObject, name)
                    values[name] = [badge.property("statusText"), badge.property("statusColor").name()]
                print(json.dumps(values))
                probe.deleteLater()
                runtime.close()
                """
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        self.assertEqual(
            __import__("json").loads(result.stdout),
            {
                "bad": ["Needs attention", "#f14c4c"],
                "warn": ["Review needed", "#cca700"],
                "good": ["Available", "#89d185"],
                "neutral": ["Not run", "#8b949e"],
            },
        )

    @unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
    def test_profile_selector_tracks_async_initial_and_session_profile_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_headless(
                f"""
                import json
                import time
                from sg_preflight.desktop.qt_quick_app import create_qt_quick_runtime
                runtime = create_qt_quick_runtime(workspace={temp_dir!r}, initial_profile_id="G70", argv=["sgfx-test"])
                root = runtime.engine.rootObjects()[0]
                deadline = time.monotonic() + 5
                while runtime.controller.pageState == "loading" and time.monotonic() < deadline:
                    runtime.application.processEvents()
                    time.sleep(0.005)
                runtime.application.processEvents()
                time.sleep(0.02)
                runtime.application.processEvents()
                initial = [runtime.controller.currentProfileId, root.property("selectedProfileValue")]
                alternative = next(option["id"] for option in runtime.controller.profileOptions if option["id"] != "G70")
                accepted = runtime.controller.selectProfile(alternative)
                deadline = time.monotonic() + 5
                while runtime.controller.pageState == "loading" and time.monotonic() < deadline:
                    runtime.application.processEvents()
                    time.sleep(0.005)
                runtime.application.processEvents()
                print(json.dumps({{
                    "initial": initial,
                    "accepted": accepted,
                    "changed": [runtime.controller.currentProfileId, root.property("selectedProfileValue")],
                }}))
                runtime.close()
                """
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        payload = __import__("json").loads(result.stdout)
        self.assertEqual(payload["initial"], ["G70", "G70"])
        self.assertTrue(payload["accepted"])
        self.assertEqual(payload["changed"][0], payload["changed"][1])
        self.assertNotEqual(payload["changed"][0], "G70")


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
                print(runtime.controller.currentRouteId)
                print(runtime.controller.currentPageId)
                print(runtime.controller.pageTitle)
                print(root.property("surfaceModel") is runtime.surface_model)
                print(root.property("desktopController") is runtime.controller)
                print(root.property("shellModel") is runtime.shell_model)
                print(runtime.surface_model.parent() is runtime.engine)
                print(runtime.shell_model.parent() is runtime.engine)
                print(runtime.controller.parent() is runtime.engine)
                print(runtime.task_coordinator.parent() is runtime.engine)
                runtime.close()
                """
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["sgfxQtQuickWindow", "19", "home", "", "Home", "True", "True", "True", "True", "True", "True", "True"],
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
            shell_model=object(),
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

            def addImportPath(self, path: str) -> None:
                self.import_path = path

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

        class ShellModel:
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
                                with mock.patch.object(qt_quick_app, "ShellRegistryModel", ShellModel):
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
        self.assertIs(context_bindings["shellModel"], initial_properties["shellModel"])
        self.assertIs(context_bindings["desktopController"], initial_properties["desktopController"])

    def test_factory_construction_failure_cleans_every_created_owner_and_sanitizes(self) -> None:
        from sg_preflight.desktop import qt_quick_app

        events: list[str] = []

        class Engine:
            def addImportPath(self, path: str) -> None:
                self.import_path = path

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
                                with mock.patch.object(qt_quick_app, "ShellRegistryModel"):
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
