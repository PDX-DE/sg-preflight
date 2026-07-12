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
        self.assertIn("onFrameSwapped:", source)
        self.assertIn("Qt.callLater(desktopController.initialize)", source)
        self.assertNotIn("Component.onCompleted: desktopController.initialize()", source)
        self.assertIn("active: window.jumpOpen", source)
        self.assertIn("active: window.helpOpen", source)
        self.assertIn('active: window.desktopController.currentRouteId !== "home"', source)
        self.assertIn('running: root.pageState !== "idle"', components)
        self.assertIn('objectName: "pageContentHost"', source)
        self.assertIn("NumberAnimation", shell_source)
        self.assertIn("ScrollView", shell_source)
        self.assertNotIn("dummy", source.casefold())
        self.assertNotIn("sample data", source.casefold())
        self.assertNotIn("QQuickWidget", source)


class TestQtQuickTask10QmlContract(unittest.TestCase):
    RENDERERS = {
        "overview": "OverviewRenderer.qml",
        "matrix": "MatrixRenderer.qml",
        "evidence": "EvidenceRenderer.qml",
        "workflow": "WorkflowRenderer.qml",
        "review": "ReviewRenderer.qml",
        "about": "AboutRenderer.qml",
    }
    READY_STATES = {
        "empty": ("not_run", False),
        "partial": ("partial", True),
        "blocked": ("blocked", True),
        "failed": ("failed", True),
        "available": ("available", True),
    }

    def _run_headless(self, script: str, *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["QT_QPA_PLATFORM"] = "offscreen"
        environment["QSG_RHI_BACKEND"] = "software"
        environment["QT_QUICK_CONTROLS_STYLE"] = "Basic"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [sys.executable, "-B", "-c", textwrap.dedent(script)],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )

    def test_task10_sources_package_page_frame_and_six_scrollable_renderers(self) -> None:
        qml_root = ROOT / "sg_preflight" / "desktop" / "qml"
        page_frame_path = qml_root / "components" / "PageFrame.qml"
        self.assertTrue(page_frame_path.is_file(), msg=str(page_frame_path))
        page_frame = page_frame_path.read_text(encoding="utf-8")
        for state in ("idle", "loading", "ready", "error"):
            with self.subTest(page_frame_state=state):
                self.assertIn(f'"{state}"', page_frame)

        for renderer_kind, filename in self.RENDERERS.items():
            with self.subTest(renderer_kind=renderer_kind):
                path = qml_root / "renderers" / filename
                self.assertTrue(path.is_file(), msg=str(path))
                source = path.read_text(encoding="utf-8")
                self.assertRegex(source, r"readonly\s+property\s+string\s+rendererKind\b")
                self.assertIn(f'"{renderer_kind}"', source)
                self.assertRegex(source, r"readonly\s+property\s+int\s+renderedItemCount\b")
                self.assertRegex(source, r"readonly\s+property\s+string\s+renderedStatus\b")
                self.assertIn("visibleItems", source)
                self.assertIn('objectName: "primaryPayloadText"', source)
                self.assertRegex(source, r"\b(?:ScrollView|Flickable)\b")

        review = (qml_root / "renderers" / "ReviewRenderer.qml").read_text(encoding="utf-8")
        self.assertRegex(review, r"\benabled\s*:")
        self.assertRegex(review, r"\breadOnly\s*:")

    def test_task10_main_dispatches_through_page_frame_without_task9_placeholder(self) -> None:
        main = (ROOT / "sg_preflight" / "desktop" / "qml" / "Main.qml").read_text(encoding="utf-8")

        self.assertIn("Components.PageFrame", main)
        self.assertIn("pageState: window.desktopController.pageState", main)
        self.assertIn("window.desktopController.currentPayload", main)
        self.assertIn("window.desktopController.errorSummary", main)
        self.assertNotIn("Page content is loaded lazily from local evidence.", main)

    @unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
    def test_task10_ready_renderers_load_and_bind_canonical_visible_items_exactly(self) -> None:
        qml_root = ROOT / "sg_preflight" / "desktop" / "qml"
        result = self._run_headless(
            f"""
            import json
            from PySide6.QtCore import QObject, QUrl
            from PySide6.QtGui import QGuiApplication
            from PySide6.QtQml import QQmlComponent, QQmlEngine

            app = QGuiApplication(["sgfx-task10-renderer-test"])
            engine = QQmlEngine()
            engine.addImportPath({str(qml_root)!r})
            renderer_files = {self.RENDERERS!r}
            ready_states = {self.READY_STATES!r}
            observed = {{}}
            for kind, filename in renderer_files.items():
                path = {str(qml_root)!r} + "/renderers/" + filename
                component = QQmlComponent(engine, QUrl.fromLocalFile(path))
                for state_name, (status, data_available) in ready_states.items():
                    sentinel = f"Task 10 {{kind}} {{state_name}} primary payload"
                    provenance_source = f"Task 10 {{kind}} provenance source"
                    revision = f"task10-{{kind}}-revision"
                    visible_items = [] if state_name == "empty" else [
                        {{
                            "itemId": f"{{kind}}-{{state_name}}-primary",
                            "sectionId": "main",
                            "label": "Primary evidence",
                            "value": sentinel,
                            "detail": "",
                            "status": status,
                            "expected": "",
                            "actual": "",
                            "diff": "",
                            "source": provenance_source,
                            "revision": revision,
                        }},
                        {{
                            "itemId": f"{{kind}}-{{state_name}}-secondary",
                            "sectionId": "main",
                            "label": "Secondary evidence",
                            "value": f"Task 10 {{kind}} {{state_name}} secondary payload",
                            "detail": "",
                            "status": status,
                            "expected": "",
                            "actual": "",
                            "diff": "",
                            "source": "",
                            "revision": "",
                        }},
                    ]
                    page = {{
                        "surfaceId": f"task10-{{kind}}-{{state_name}}",
                        "rendererKind": kind,
                        "title": "Chrome must not satisfy the payload assertion",
                        "subtitle": "Chrome subtitle",
                        "status": status,
                        "dataAvailable": data_available,
                        "primaryText": sentinel,
                        "visibleItems": visible_items,
                        "visibleItemCount": len(visible_items),
                        "sections": [{{"sectionId": "main", "title": "Evidence", "status": status, "items": visible_items}}],
                        "actions": [],
                        "artifacts": [],
                        "provenance": {{"source": provenance_source, "revision": revision}},
                        "ownershipNote": "Operator-owned review",
                        "readOnly": True,
                        "isApproval": False,
                        "manualReviewRequired": kind == "review",
                        "recordsOperatorVerdict": False,
                    }}
                    root = component.createWithInitialProperties({{"page": page}})
                    if root is None:
                        raise SystemExit(kind + "/" + state_name + ": " + " | ".join(error.toString() for error in component.errors()))
                    root.setProperty("width", 720)
                    root.setProperty("height", 480)
                    app.processEvents()
                    primary = root.findChild(QObject, "primaryPayloadText")
                    detail = root.findChild(QObject, "payloadDetailRegion")
                    detail_texts = []
                    if detail is not None:
                        for child in detail.findChildren(QObject):
                            text = child.property("text")
                            if isinstance(text, str) and text:
                                detail_texts.append(text)
                    key = kind + "/" + state_name
                    observed[key] = {{
                        "rendererKind": root.property("rendererKind"),
                        "renderedItemCount": root.property("renderedItemCount"),
                        "renderedStatus": root.property("renderedStatus"),
                        "primaryExists": primary is not None,
                        "primaryVisible": primary is not None and bool(primary.property("visible")),
                        "primaryText": None if primary is None else primary.property("text"),
                        "detailExists": detail is not None,
                        "detailTexts": detail_texts,
                    }}
                    if kind == "review" and state_name == "available":
                        verdict = root.findChild(QObject, "reviewVerdictControl")
                        note = root.findChild(QObject, "reviewNoteControl")
                        observed[key]["verdictDisabled"] = verdict is not None and not bool(verdict.property("enabled"))
                        observed[key]["noteReadOnly"] = note is not None and bool(note.property("readOnly"))
                    root.deleteLater()
            print(json.dumps(observed, sort_keys=True))
            """
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        observed = __import__("json").loads(result.stdout)
        for renderer_kind in self.RENDERERS:
            for state_name, (status, _data_available) in self.READY_STATES.items():
                with self.subTest(renderer_kind=renderer_kind, state=state_name):
                    renderer = observed[f"{renderer_kind}/{state_name}"]
                    self.assertEqual(renderer["rendererKind"], renderer_kind)
                    self.assertEqual(renderer["renderedItemCount"], 0 if state_name == "empty" else 2)
                    self.assertEqual(renderer["renderedStatus"], status)
                    self.assertTrue(renderer["primaryExists"])
                    self.assertTrue(renderer["primaryVisible"])
                    self.assertEqual(
                        renderer["primaryText"],
                        f"Task 10 {renderer_kind} {state_name} primary payload",
                    )
                    if state_name == "available":
                        self.assertTrue(renderer["detailExists"])
                        detail_text = "\n".join(renderer["detailTexts"])
                        self.assertIn(f"Task 10 {renderer_kind} provenance source", detail_text)
                        self.assertIn(f"task10-{renderer_kind}-revision", detail_text)
        review = observed["review/available"]
        self.assertTrue(review["verdictDisabled"])
        self.assertTrue(review["noteReadOnly"])

    @unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
    def test_task10_all_real_surfaces_instantiate_the_declared_renderer(self) -> None:
        qml_root = ROOT / "sg_preflight" / "desktop" / "qml"
        result = self._run_headless(
            f"""
            import json
            import os
            from pathlib import Path
            import tempfile
            from unittest import mock
            from PySide6.QtCore import QObject, QUrl
            from PySide6.QtGui import QGuiApplication
            from PySide6.QtQml import QQmlComponent, QQmlEngine
            from sg_preflight import dashboard_preferences
            from sg_preflight.dashboard.main import build_dashboard_page
            from sg_preflight.desktop.page_presenter import present_page_payload
            from sg_preflight.desktop.payload_adapter import adapt_page_payload
            from sg_preflight.desktop.qt_quick_controller import load_dashboard_surface
            from sg_preflight.surface_registry import SURFACE_DESCRIPTORS, get_surface_descriptor

            app = QGuiApplication(["sgfx-task10-real-surface-test"])
            engine = QQmlEngine()
            engine.addImportPath({str(qml_root)!r})
            renderer_files = {self.RENDERERS!r}
            observed = []
            with tempfile.TemporaryDirectory() as temp_dir:
                isolated = Path(temp_dir)
                workspace = isolated / "workspace"
                bmw_root = isolated / "bmw"
                source_root = isolated / "source"
                workspace.mkdir()
                bmw_root.mkdir()
                (source_root / "Cars").mkdir(parents=True)
                with (
                    mock.patch.dict(
                        os.environ,
                        {{"SG_SOURCE_REPO_ROOT": str(source_root), "SG_REPO": str(source_root)}},
                        clear=False,
                    ),
                    mock.patch.object(
                        dashboard_preferences,
                        "CANONICAL_SOURCE_REPO_ROOT",
                        source_root,
                    ),
                ):
                    descriptors = [item for item in SURFACE_DESCRIPTORS if item.operational]
                    for descriptor in descriptors:
                        raw = build_dashboard_page(
                            page_id=descriptor.surface_id,
                            profile_id="G65",
                            workspace=workspace,
                            bmw_root=bmw_root,
                            ui_mode="clean",
                            persist_dependency_state=False,
                        )
                        page = present_page_payload(
                            descriptor,
                            adapt_page_payload(raw, workspace=workspace),
                        )
                        component = QQmlComponent(
                            engine,
                            QUrl.fromLocalFile(
                                {str(qml_root)!r} + "/renderers/" + renderer_files[descriptor.renderer_kind]
                            ),
                        )
                        root = component.createWithInitialProperties({{"page": page}})
                        if root is None:
                            raise SystemExit(
                                descriptor.surface_id + ": " + " | ".join(error.toString() for error in component.errors())
                            )
                        root.setProperty("width", 720)
                        root.setProperty("height", 480)
                        app.processEvents()
                        primary = root.findChild(QObject, "primaryPayloadText")
                        observed.append([
                            descriptor.surface_id,
                            root.property("rendererKind"),
                            root.property("renderedItemCount"),
                            root.property("renderedStatus"),
                            primary is not None and bool(primary.property("visible")),
                            None if primary is None else primary.property("text"),
                            page["visibleItemCount"],
                            page["status"],
                            page["primaryText"],
                        ])
                        root.deleteLater()

                    descriptor = get_surface_descriptor("about")
                    raw = load_dashboard_surface("about", "G65", workspace, bmw_root=bmw_root)
                    page = present_page_payload(
                        descriptor,
                        adapt_page_payload(raw, workspace=workspace),
                    )
                    component = QQmlComponent(
                        engine,
                        QUrl.fromLocalFile({str(qml_root)!r} + "/renderers/AboutRenderer.qml"),
                    )
                    root = component.createWithInitialProperties({{"page": page}})
                    if root is None:
                        raise SystemExit("about: " + " | ".join(error.toString() for error in component.errors()))
                    root.setProperty("width", 720)
                    root.setProperty("height", 480)
                    app.processEvents()
                    primary = root.findChild(QObject, "primaryPayloadText")
                    observed.append([
                        "about",
                        root.property("rendererKind"),
                        root.property("renderedItemCount"),
                        root.property("renderedStatus"),
                        primary is not None and bool(primary.property("visible")),
                        None if primary is None else primary.property("text"),
                        page["visibleItemCount"],
                        page["status"],
                        page["primaryText"],
                    ])
                    root.deleteLater()
            print(json.dumps(observed))
            """,
            timeout=180,
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        observed = __import__("json").loads(result.stdout)
        self.assertEqual(len(observed), 19)
        expected_kinds = {
            descriptor.surface_id: descriptor.renderer_kind
            for descriptor in __import__("sg_preflight.surface_registry", fromlist=["SURFACE_DESCRIPTORS"]).SURFACE_DESCRIPTORS
        }
        for surface_id, kind, count, status, primary_visible, primary_text, expected_count, expected_status, expected_text in observed:
            with self.subTest(surface_id=surface_id):
                self.assertEqual(kind, expected_kinds[surface_id])
                self.assertEqual(count, expected_count)
                self.assertGreater(count, 0)
                self.assertEqual(status, expected_status)
                self.assertTrue(primary_visible)
                self.assertEqual(primary_text, expected_text)

    @unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
    def test_task10_page_frame_alone_owns_loading_and_error_states(self) -> None:
        qml_root = ROOT / "sg_preflight" / "desktop" / "qml"
        result = self._run_headless(
            f"""
            import json
            from PySide6.QtCore import QObject, QUrl
            from PySide6.QtGui import QGuiApplication
            from PySide6.QtQml import QQmlComponent, QQmlEngine
            from PySide6.QtQuick import QQuickItem

            app = QGuiApplication(["sgfx-task10-page-frame-test"])
            engine = QQmlEngine()
            engine.addImportPath({str(qml_root)!r})
            component = QQmlComponent(
                engine,
                QUrl.fromLocalFile({str(qml_root / "components" / "PageFrame.qml")!r}),
            )

            def create_frame(state, page=None, error_summary=""):
                frame = component.createWithInitialProperties({{
                    "pageState": state,
                    "page": page or {{}},
                    "errorCode": "page_reader_failed" if state == "error" else "",
                    "errorSummary": error_summary,
                    "reducedMotion": True,
                }})
                if frame is None:
                    raise SystemExit(state + ": " + " | ".join(error.toString() for error in component.errors()))
                frame.setProperty("width", 720)
                frame.setProperty("height", 480)
                app.processEvents()
                texts = []
                for child in frame.findChildren(QQuickItem):
                    text = child.property("text")
                    if child.isVisible() and isinstance(text, str) and text:
                        texts.append(text)
                primary = frame.findChild(QObject, "primaryPayloadText")
                return frame, texts, primary

            idle, idle_texts, idle_primary = create_frame("idle")
            loading, loading_texts, loading_primary = create_frame("loading")
            error, error_texts, error_primary = create_frame(
                "error",
                error_summary="Task 10 exact PageFrame error",
            )
            print(json.dumps({{
                "idleHasPrimary": idle_primary is not None,
                "loadingHasPrimary": loading_primary is not None,
                "loadingTexts": loading_texts,
                "errorHasPrimary": error_primary is not None,
                "errorTexts": error_texts,
            }}, sort_keys=True))
            idle.deleteLater()
            loading.deleteLater()
            error.deleteLater()
            """
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        observed = __import__("json").loads(result.stdout)
        self.assertFalse(observed["idleHasPrimary"])
        self.assertFalse(observed["loadingHasPrimary"])
        self.assertTrue(any("loading" in text.casefold() for text in observed["loadingTexts"]))
        self.assertFalse(observed["errorHasPrimary"])
        self.assertIn("Task 10 exact PageFrame error", observed["errorTexts"])


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
            "components/QaPipelineSpine.qml",
            "components/QaGateDetail.qml",
            "components/QaContextPreview.qml",
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
        home = (qml_root / "components" / "HomePage.qml").read_text(encoding="utf-8")
        qmldir = (qml_root / "SGFX" / "qmldir").read_text(encoding="utf-8")
        self.assertIn("import SGFX 1.0", main)
        self.assertIn("required property var shellModel", main)
        self.assertIn("model: root.shellModel", combined)
        self.assertIn("Accessible.name", combined)
        self.assertIn("Accessible.role", combined)
        self.assertIn("activeFocus", combined)
        self.assertIn("ScrollView", combined)
        self.assertIn("profileOptions", main + combined)
        self.assertNotIn("homeTileRepeater", home)
        self.assertIn("QaPipelineSpine", home)
        self.assertIn("QaGateDetail", home)
        self.assertIn("QaContextPreview", home)
        self.assertNotIn("Grafiks", main)
        self.assertIn("Open 3D inspection", main)
        self.assertIn('objectName: "presentationViewControl"', main)
        self.assertIn("property bool presentationView: false", main)
        self.assertIn("function setPresentation(enabled: bool)", main)
        self.assertIn("Inter.ttf", main)
        self.assertIn("Fredoka.ttf", main)
        self.assertNotIn(".replaceAll(", combined)
        self.assertNotIn("TextField", main.split("components.HomePage", 1)[0])
        for token in ("motionMicro", "motionFeedback", "motionShort", "motionStandard", "motionEmphasis", "motionStagger"):
            self.assertIn(token, theme)
        self.assertIn("readonly property int motionStagger: 70", theme)
        for token in (
            "operationalFont",
            "displayFont",
            "space1",
            "space2",
            "space3",
            "space4",
            "focusDuration",
            "panelDuration",
            "routeDuration",
            "entranceLimit",
            "entranceStagger",
        ):
            self.assertIn(token, theme)
        for color in ("#f14c4c", "#cca700", "#89d185", "#8b949e"):
            self.assertIn(color, theme)
        self.assertEqual(qmldir.splitlines(), ["module SGFX", "singleton Theme 1.0 Theme.qml"])
        for shortcut in ("F1", "F2", "F5", "F12", "Esc", 'sequence: "/"'):
            self.assertIn(shortcut, main)

    @unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
    def test_runtime_shell_has_exact_groups_pipeline_geometry_and_overlay_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_headless(
                f"""
                import json
                from PySide6.QtCore import QMetaObject, Q_ARG
                from PySide6.QtTest import QTest
                from sg_preflight.desktop.qt_quick_app import create_qt_quick_runtime
                runtime = create_qt_quick_runtime(workspace={temp_dir!r}, initial_profile_id="", argv=["sgfx-test"])
                root = runtime.engine.rootObjects()[0]
                deadline = __import__("time").monotonic() + 5
                while runtime.controller.pageState not in {{"ready", "error"}} and __import__("time").monotonic() < deadline:
                    runtime.application.processEvents()
                    QTest.qWait(5)
                print(json.dumps({{
                    "groups": root.property("navigationGroupTitles"),
                    "gates": root.property("pipelineGateIds").toVariant(),
                    "more": root.property("moreGroupVisible"),
                    "scale": root.property("referenceScale"),
                    "offsetX": root.property("referenceOffsetX"),
                    "offsetY": root.property("referenceOffsetY"),
                    "primaryActionLabel": root.property("primaryActionLabel"),
                    "primaryActionEnabled": root.property("primaryActionEnabled"),
                    "selectedGateId": root.property("selectedGateId"),
                    "visibleCheckRowCount": root.property("visibleCheckRowCount"),
                    "reduced": [root.property("reducedMotionDuration"), root.property("reducedMotionTravel"), root.property("reducedMotionStagger")],
                }}))
                root.setWidth(1024)
                root.setHeight(640)
                runtime.application.processEvents()
                print(root.property("referenceScale"), root.property("referenceOffsetY"), root.property("visibleCheckRowCount"))
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
        self.assertEqual(payload["gates"], ["context", "asset", "interface", "variants", "visual", "review", "delivery"])
        self.assertFalse(payload["more"])
        self.assertEqual((payload["scale"], payload["offsetX"], payload["offsetY"]), (1, 0, 0))
        self.assertEqual(payload["primaryActionLabel"], "Choose profile")
        self.assertFalse(payload["primaryActionEnabled"])
        self.assertEqual(payload["selectedGateId"], "context")
        self.assertLessEqual(payload["visibleCheckRowCount"], 4)
        self.assertEqual(payload["reduced"], [120, 8, 0])
        scale, offset, compact_rows = (float(value) for value in lines[1].split())
        self.assertAlmostEqual(scale, 0.8, places=3)
        self.assertAlmostEqual(offset, 32.0, places=3)
        self.assertLessEqual(compact_rows, 4)
        self.assertEqual(lines[2], "False False False True")

    @unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
    def test_presentation_view_preserves_the_exact_qa_truth_and_starts_no_work(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_headless(
                f"""
                import json
                import time
                from PySide6.QtCore import QMetaObject, Q_ARG, QObject
                from sg_preflight.desktop.qt_quick_app import (
                    _hide_qt_windows,
                    _restore_qt_windows,
                    create_qt_quick_runtime,
                )
                runtime = create_qt_quick_runtime(workspace={temp_dir!r}, initial_profile_id="G65", argv=["sgfx-test"])
                root = runtime.engine.rootObjects()[0]
                deadline = time.monotonic() + 5
                while runtime.controller.pageState not in {{"ready", "error"}} and time.monotonic() < deadline:
                    runtime.application.processEvents()
                    time.sleep(0.005)
                home = root.findChild(QObject, "qaControlCenterHome")
                home.setProperty("selectedGateOverride", "visual")
                runtime.application.processEvents()

                def truth():
                    payload = runtime.controller.currentPayload
                    return [
                        runtime.controller.currentProfileId,
                        runtime.controller.currentRouteId,
                        root.property("selectedGateId"),
                        json.dumps(payload.get("gates", []), sort_keys=True),
                        json.dumps(payload.get("actions", []), sort_keys=True),
                    ]

                before = truth()
                generation = runtime.controller._generation
                inspection_generation = runtime.grafiks_host._generation
                active_count = runtime.task_coordinator.active_count
                invoked_on = QMetaObject.invokeMethod(root, "setPresentation", Q_ARG(bool, True))
                runtime.application.processEvents()
                during = truth()
                presentation_state = [root.property("presentationView"), root.property("sidebarOpen")]
                invoked_off = QMetaObject.invokeMethod(root, "handleShortcut", Q_ARG(str, "Esc"))
                runtime.application.processEvents()
                after = truth()
                restored_state = [root.property("presentationView"), root.property("sidebarOpen")]
                _hide_qt_windows(runtime.engine)
                _restore_qt_windows(runtime.engine)
                runtime.application.processEvents()
                after_inspection = truth()
                print(json.dumps({{
                    "invoked": [invoked_on, invoked_off],
                    "truth": [before, during, after, after_inspection],
                    "presentationState": presentation_state,
                    "restoredState": restored_state,
                    "generation": [generation, runtime.controller._generation],
                    "inspectionGeneration": [inspection_generation, runtime.grafiks_host._generation],
                    "activeCount": [active_count, runtime.task_coordinator.active_count],
                }}))
                runtime.close()
                """
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        payload = __import__("json").loads(result.stdout)
        self.assertEqual(payload["invoked"], [True, True])
        self.assertEqual(payload["truth"], [payload["truth"][0]] * 4)
        self.assertEqual(payload["truth"][0][2], "visual")
        self.assertEqual(payload["presentationState"], [True, False])
        self.assertEqual(payload["restoredState"], [False, True])
        self.assertEqual(payload["generation"][0], payload["generation"][1])
        self.assertEqual(payload["inspectionGeneration"][0], payload["inspectionGeneration"][1])
        self.assertEqual(payload["activeCount"][0], payload["activeCount"][1])

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
                root.requestUpdate()
                deadline = time.monotonic() + 5
                while runtime.controller.pageState not in {{"ready", "error"}} and time.monotonic() < deadline:
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
                root.requestUpdate()
                deadline = time.monotonic() + 5
                while runtime.controller.pageState not in {{"ready", "error"}} and time.monotonic() < deadline:
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
    def test_qml_observes_matching_page_state_and_operation_transitions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_headless(
                f"""
                import json
                import threading
                import time
                from PySide6.QtCore import QUrl
                from PySide6.QtQml import QQmlComponent
                from sg_preflight.desktop.qt_quick_app import create_qt_quick_runtime

                runtime = create_qt_quick_runtime(workspace={temp_dir!r}, initial_profile_id="G65", argv=["sgfx-test"])
                root = runtime.engine.rootObjects()[0]
                root.requestUpdate()
                deadline = time.monotonic() + 5
                while runtime.controller.pageState not in {{"ready", "error"}} and time.monotonic() < deadline:
                    runtime.application.processEvents()
                    time.sleep(0.005)

                component = QQmlComponent(runtime.engine)
                component.setData(
                    b'import QtQml\\nQtObject {{ required property var controller; property string observedState: controller.pageState; property string observedOperation: controller.currentOperation }}\\n',
                    QUrl(),
                )
                probe = component.createWithInitialProperties({{"controller": runtime.controller}})
                if probe is None:
                    raise SystemExit(" | ".join(error.toString() for error in component.errors()))

                gate = threading.Event()
                payload = dict(runtime.controller.currentPayload)

                def delayed_shell_context(**_kwargs):
                    gate.wait(2)
                    return payload

                runtime.controller._shell_loader = delayed_shell_context
                accepted = runtime.controller.refresh()
                runtime.application.processEvents()
                started = [probe.property("observedState"), probe.property("observedOperation")]
                gate.set()
                deadline = time.monotonic() + 5
                while runtime.controller.pageState == "loading" and time.monotonic() < deadline:
                    runtime.application.processEvents()
                    time.sleep(0.005)
                runtime.application.processEvents()
                completed = [probe.property("observedState"), probe.property("observedOperation")]
                print(json.dumps({{"accepted": accepted, "started": started, "completed": completed}}))
                probe.deleteLater()
                runtime.close()
                """
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        self.assertEqual(
            __import__("json").loads(result.stdout),
            {
                "accepted": True,
                "started": ["loading", "shell_context"],
                "completed": ["ready", ""],
            },
        )


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
                print(root.property("grafiksHost") is runtime.grafiks_host)
                print(runtime.surface_model.parent() is runtime.engine)
                print(runtime.shell_model.parent() is runtime.engine)
                print(runtime.controller.parent() is runtime.engine)
                print(runtime.task_coordinator.parent() is runtime.engine)
                print(runtime.grafiks_host.parent() is runtime.engine)
                runtime.close()
                """
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "sgfxQtQuickWindow",
                "19",
                "home",
                "",
                "Home",
                "True",
                "True",
                "True",
                "True",
                "True",
                "True",
                "True",
                "True",
                "True",
            ],
        )

    def test_runtime_keeps_an_omitted_profile_empty_after_qml_completion_without_writing_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_headless(
                f"""
                import json
                from pathlib import Path
                import time
                from sg_preflight.desktop.qt_quick_app import create_qt_quick_runtime
                workspace = Path({temp_dir!r})
                runtime = create_qt_quick_runtime(workspace=workspace, argv=["sgfx-test"])
                deadline = time.monotonic() + 5
                while runtime.controller.pageState not in {{"ready", "error"}} and time.monotonic() < deadline:
                    runtime.application.processEvents()
                    time.sleep(0.005)
                print(json.dumps({{
                    "profile": runtime.controller.currentProfileId,
                    "state": runtime.controller.pageState,
                    "files": sum(1 for path in workspace.rglob("*") if path.is_file()),
                }}))
                runtime.close()
                """
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        payload = __import__("json").loads(result.stdout)
        self.assertEqual(payload, {"profile": "", "state": "ready", "files": 0})

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
                self.kwargs["grafiks_host"].shutdown()

        class GrafiksHost:
            def __init__(self, **kwargs: object) -> None:
                self.kwargs = kwargs

            def shutdown(self) -> None:
                events.append("grafiks")

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
                        with mock.patch.object(qt_quick_app, "GrafiksHostAdapter", GrafiksHost):
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

        self.assertEqual(events, ["load", "controller", "grafiks", "coordinator"])
        self.assertIs(context_bindings["surfaceModel"], initial_properties["surfaceModel"])
        self.assertIs(context_bindings["shellModel"], initial_properties["shellModel"])
        self.assertIs(context_bindings["desktopController"], initial_properties["desktopController"])
        self.assertIs(context_bindings["grafiksHost"], initial_properties["grafiksHost"])

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
                self.kwargs["grafiks_host"].shutdown()

        class GrafiksHost:
            def __init__(self, **kwargs: object) -> None:
                self.kwargs = kwargs

            def shutdown(self) -> None:
                events.append("grafiks")

        with tempfile.TemporaryDirectory() as temp_dir:
            qml_path = Path(temp_dir) / "Main.qml"
            qml_path.write_text("fixture\n", encoding="utf-8")
            with mock.patch.object(qt_quick_app, "_application", return_value=object()):
                with mock.patch.object(qt_quick_app, "QQmlApplicationEngine", Engine):
                    with mock.patch.object(qt_quick_app, "PageTaskCoordinator", Coordinator):
                        with mock.patch.object(qt_quick_app, "GrafiksHostAdapter", GrafiksHost):
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

        self.assertEqual(events, ["controller", "grafiks", "coordinator"])
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
