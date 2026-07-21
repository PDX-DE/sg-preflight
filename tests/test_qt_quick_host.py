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
        self.assertIn('objectName: "workspaceOrientationText"', source)
        self.assertIn("desktopController.workspaceStatus", source)
        self.assertIn("Workspace unresolved · Candidate:", source)
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
            "SGFX/StatusPresentation.qml",
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
        self.assertNotIn("FontLoader", main)
        self.assertIn("sgfxProductFonts", theme)
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
        self.assertEqual(
            qmldir.splitlines(),
            [
                "module SGFX",
                "singleton Theme 1.0 Theme.qml",
                "singleton StatusPresentation 1.0 StatusPresentation.qml",
            ],
        )
        for shortcut in ("F1", "F2", "F5", "F12", "Esc", 'sequence: "/"'):
            self.assertIn(shortcut, main)

    def test_control_center_uses_host_registered_fonts_and_finite_accessible_motion(self) -> None:
        app = (ROOT / "sg_preflight" / "desktop" / "qt_quick_app.py").read_text(encoding="utf-8")
        qml_root = ROOT / "sg_preflight" / "desktop" / "qml"
        main = (qml_root / "Main.qml").read_text(encoding="utf-8")
        home = (qml_root / "components" / "HomePage.qml").read_text(encoding="utf-8")
        preview = (qml_root / "components" / "QaContextPreview.qml").read_text(encoding="utf-8")
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                qml_root / "Main.qml",
                qml_root / "components" / "HomePage.qml",
                qml_root / "components" / "QaPipelineSpine.qml",
                qml_root / "components" / "QaGateDetail.qml",
                qml_root / "components" / "QaContextPreview.qml",
            )
        )

        self.assertIn("QFontDatabase", app)
        self.assertIn("def _load_product_fonts() -> dict[str, str]:", app)
        self.assertIn('context.setContextProperty("sgfxProductFonts"', app)
        self.assertNotIn("FontLoader", main)
        self.assertNotIn(".ttf", main)
        self.assertNotIn("Animation.Infinite", combined)
        self.assertNotRegex(combined, r"loops\s*:\s*-1")
        self.assertIn("focusProductStart", main)
        self.assertIn("focusPrimaryAction", home)
        self.assertIn("focusFirstCheck", combined)
        self.assertIn("focusFirstAction", preview)

    def test_keyboard_modal_and_reduced_motion_sources_are_explicit(self) -> None:
        qml_root = ROOT / "sg_preflight" / "desktop" / "qml"
        main = (qml_root / "Main.qml").read_text(encoding="utf-8")
        jump = (qml_root / "components" / "JumpPalette.qml").read_text(encoding="utf-8")
        help_source = (qml_root / "components" / "ShortcutHelp.qml").read_text(encoding="utf-8")
        gate = (qml_root / "components" / "QaGateDetail.qml").read_text(encoding="utf-8")
        review = (qml_root / "renderers" / "ReviewRenderer.qml").read_text(encoding="utf-8")
        workflow = (qml_root / "renderers" / "WorkflowRenderer.qml").read_text(encoding="utf-8")

        self.assertIn("function openOverlay(kind: string)", main)
        self.assertIn("function closeOverlay()", main)
        self.assertIn("overlayReturnFocus", main)
        self.assertIn("restoreOverlayFocus", main)
        self.assertIn("KeyNavigation.tab: presentationViewControl", main)
        self.assertIn("KeyNavigation.backtab: profileSelector", main)
        self.assertIn('objectName: "diagnosticsCloseControl"', main)
        self.assertIn("Accessible.role: Accessible.Dialog", main)
        for source, close_name in (
            (jump, "jumpCloseControl"),
            (help_source, "helpCloseControl"),
        ):
            with self.subTest(close_name=close_name):
                self.assertIn("FocusScope", source)
                self.assertIn("Accessible.role: Accessible.Dialog", source)
                self.assertIn(f'objectName: "{close_name}"', source)
                self.assertIn("KeyNavigation.tab", source)
                self.assertIn("KeyNavigation.backtab", source)
        self.assertIn("activeFocusOnTab: checkRow.routing", gate)
        self.assertIn("Accessible.StaticText", gate)
        self.assertIn('objectName: "reviewStepControl" + reviewDelegate.index', review)
        self.assertIn("activeFocusOnTab: root.canRecord", review)
        self.assertIn("Accessible.selected", review)
        self.assertIn("Keys.onSpacePressed", review)
        self.assertIn("KeyNavigation.tab: recordReviewControl", review)
        self.assertIn("KeyNavigation.tab: recordHandoffControl", workflow)
        self.assertNotIn("Animation.Infinite", main + jump + help_source + gate + review + workflow)

    @unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
    def test_sidebar_focus_starts_with_current_session_then_manual_review(self) -> None:
        result = self._run_headless(
            """
            import json
            from PySide6.QtCore import QMetaObject, QObject, Qt
            from PySide6.QtTest import QTest
            from sg_preflight.desktop.qt_quick_app import create_qt_quick_runtime

            runtime = create_qt_quick_runtime(workspace=".", initial_profile_id="G45", argv=["sgfx-sidebar-focus-test"])
            root = runtime.engine.rootObjects()[0]
            root.setProperty("shellInitializationStarted", True)
            runtime.application.processEvents()
            sidebar = root.findChild(QObject, "navigationSidebar")
            QMetaObject.invokeMethod(sidebar, "focusFirst")
            runtime.application.processEvents()
            focus_order = []
            for _index in range(6):
                focused = runtime.application.focusObject()
                focus_order.append(focused.property("text") if focused is not None else "")
                QTest.keyClick(root, Qt.Key_Tab)
                runtime.application.processEvents()
            print(json.dumps(focus_order))
            runtime.close()
            """
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        self.assertEqual(
            __import__("json").loads(result.stdout),
            [
                "Jump to page  /",
                "QA overview",
                "Selected-Car Checks",
                "Manual Review Companion",
                "Screenshot Test State",
                "Country Variants",
            ],
        )

    @unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
    def test_home_emphasizes_selected_car_and_links_existing_work_areas(self) -> None:
        snapshot = {
            "schemaVersion": 1,
            "scopeLabel": "3D Car QA",
            "selectedProfile": {"id": "G45", "label": "BMW G45"},
            "gates": [
                {
                    "id": "asset",
                    "label": "Asset integrity",
                    "state": "findings",
                    "summary": "Local QA result: 1 errors, 1 warnings, 2 info.",
                    "ownerLabel": "Seriengrafik",
                    "checks": [
                        {
                            "id": "local-preflight",
                            "label": "Open selected-car checks",
                            "state": "findings",
                            "summary": "Local QA result: 1 errors, 1 warnings, 2 info.",
                            "routeId": "full-qa-pass",
                        }
                    ],
                }
            ],
            "selectedGateId": "asset",
            "latestLocalRun": {
                "state": "findings",
                "errors": 1,
                "warnings": 1,
                "info": 2,
                "findings": [
                    {
                        "severity": "error",
                        "message": "Wheel diameter differs from the expected value",
                        "location": "rim_diameter_in.Basis.front",
                        "expected": "20.0",
                        "actual": "19.5",
                    }
                ],
            },
            "nextAction": {
                "kind": "review",
                "capabilityId": "page.navigate",
                "actionId": "",
                "routeId": "full-qa-pass",
                "label": "Review local findings",
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_headless(
                f"""
                import json
                from PySide6.QtCore import QMetaObject, QObject
                from PySide6.QtTest import QTest
                from sg_preflight.desktop.qt_quick_app import create_qt_quick_runtime

                runtime = create_qt_quick_runtime(workspace={temp_dir!r}, initial_profile_id="G45", argv=["sgfx-home-work-areas-test"])
                root = runtime.engine.rootObjects()[0]
                root.setProperty("shellInitializationStarted", True)
                runtime.application.processEvents()
                QTest.qWait(0)
                runtime.application.processEvents()
                controller = runtime.controller
                controller._generation += 1
                controller._set_current_identity(None)
                controller._accept_shell_profile({{
                    "schemaVersion": 1,
                    "profileOptions": [{{"id": "G45", "label": "BMW G45"}}],
                    "selectedProfile": {{"id": "G45", "label": "BMW G45"}},
                }})
                controller._set_route("home")
                controller._set_ready_payload({snapshot!r})
                runtime.application.processEvents()
                QTest.qWait(0)
                runtime.application.processEvents()

                names = [
                    "homeSelectedCarTitle",
                    "homeLatestOutcome",
                    "homeFindingsLink",
                    "homeManualReviewLink",
                    "homeEvidenceLink",
                    "homeHistoryLink",
                ]
                objects = {{name: root.findChild(QObject, name) for name in names}}
                primary = root.findChild(QObject, "qaPrimaryAction")
                home = root.findChild(QObject, "qaControlCenterHome")
                finding_preview = root.findChild(QObject, "homeFindingPreview")
                requested_routes = []
                home.routeRequested.connect(requested_routes.append)
                present = {{name: objects[name] is not None for name in names}}
                selected_car = "" if objects["homeSelectedCarTitle"] is None else objects["homeSelectedCarTitle"].property("text")
                latest_outcome = "" if objects["homeLatestOutcome"] is None else objects["homeLatestOutcome"].property("text")
                primary_text = primary.property("text")
                primary_height = primary.property("height")
                secondary_heights = [objects[name].property("height") for name in names[2:] if objects[name] is not None]
                secondary_flat = [objects[name].property("flat") for name in names[2:] if objects[name] is not None]
                accessible = root.property("allAccessibleNamesPresent")
                finding_visible = finding_preview is not None and "Wheel diameter differs" in str(finding_preview.property("text"))
                if all(objects.values()):
                    for name in names[2:]:
                        controller._generation += 1
                        controller._set_current_identity(None)
                        controller._set_route("home")
                        controller._set_ready_payload({snapshot!r})
                        runtime.application.processEvents()
                        QMetaObject.invokeMethod(objects[name], "click")
                        runtime.application.processEvents()
                print(json.dumps({{
                    "present": present,
                    "selectedCar": selected_car,
                    "latestOutcome": latest_outcome,
                    "findingVisible": finding_visible,
                    "primaryText": primary_text,
                    "primaryHeight": primary_height,
                    "secondaryHeights": secondary_heights,
                    "secondaryFlat": secondary_flat,
                    "routes": requested_routes,
                    "accessible": accessible,
                }}))
                runtime.close()
                """
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        payload = __import__("json").loads(result.stdout)
        self.assertTrue(all(payload["present"].values()), msg=payload)
        self.assertEqual(payload["selectedCar"], "BMW G45")
        self.assertIn("1 error", payload["latestOutcome"])
        self.assertIn("1 warning", payload["latestOutcome"])
        self.assertTrue(payload["findingVisible"], msg=payload)
        self.assertEqual(payload["primaryText"], "Review local findings")
        self.assertTrue(all(payload["primaryHeight"] > height for height in payload["secondaryHeights"]))
        self.assertEqual(payload["secondaryFlat"], [True, True, True, True])
        self.assertEqual(
            payload["routes"],
            ["full-qa-pass", "manual-review", "delivery-checklist", "batch-full-qa-pass"],
        )
        self.assertTrue(payload["accessible"])

    @unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
    def test_control_center_viewports_accessibility_fonts_and_focus_order(self) -> None:
        checks = [
            {
                "id": f"check-{index}",
                "label": f"Check {index + 1}",
                "summary": "Recorded local evidence",
                "state": "not_recorded",
                "routeId": "risk-score" if index == 0 else "",
            }
            for index in range(4)
        ]
        gates = [
            {
                "id": gate_id,
                "label": label,
                "state": "not_recorded",
                "summary": "No local evidence recorded.",
                "ownerLabel": "Operator",
                "checks": checks,
            }
            for gate_id, label in (
                ("context", "Context"),
                ("asset", "Asset"),
                ("interface", "Interface"),
                ("variants", "Variants"),
                ("visual", "Visual"),
                ("review", "Review"),
                ("delivery", "Delivery"),
            )
        ]
        snapshot = {
            "schemaVersion": 1,
            "scopeLabel": "BMW G45",
            "selectedProfile": {"id": "G45", "label": "BMW G45"},
            "gates": gates,
            "selectedGateId": "context",
            "latestLocalRun": {},
            "nextAction": {
                "capabilityId": "diagnostic.run",
                "actionId": "sgfx_preflight__g45",
                "label": "Run local QA",
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_headless(
                f"""
                import json
                from PySide6.QtCore import QMetaObject, QObject, Qt
                from PySide6.QtTest import QTest
                from sg_preflight.desktop.qt_quick_app import create_qt_quick_runtime
                runtime = create_qt_quick_runtime(workspace={temp_dir!r}, initial_profile_id="G45", argv=["sgfx-task10-test"])
                root = runtime.engine.rootObjects()[0]
                root.setProperty("shellInitializationStarted", True)
                runtime.application.processEvents()
                QTest.qWait(0)
                runtime.application.processEvents()
                controller = runtime.controller
                controller._generation += 1
                controller._set_current_identity(None)
                controller._accept_shell_profile({{
                    "schemaVersion": 1,
                    "profileOptions": [{{"id": "G45", "label": "BMW G45"}}],
                    "selectedProfile": {{"id": "G45", "label": "BMW G45"}},
                }})
                controller._set_route("home")
                controller._set_ready_payload({snapshot!r})
                runtime.application.processEvents()

                QMetaObject.invokeMethod(root, "focusProductStart")
                runtime.application.processEvents()
                focus_order = []
                for _index in range(12):
                    focused = runtime.application.focusObject()
                    focused_name = focused.objectName() if focused is not None else ""
                    focus_order.append(focused_name)
                    QTest.keyClick(root, Qt.Key_Tab)
                    runtime.application.processEvents()

                viewports = []
                for width, height in ((1280, 720), (1024, 640)):
                    root.setWidth(width)
                    root.setHeight(height)
                    QMetaObject.invokeMethod(root, "openProfilePopover")
                    runtime.application.processEvents()
                    viewports.append({{
                        "size": [width, height],
                        "gateCount": root.property("gateCount"),
                        "allAccessibleNamesPresent": root.property("allAccessibleNamesPresent"),
                        "primaryActionVisible": root.property("primaryActionVisible"),
                        "layoutWithinViewport": root.property("layoutWithinViewport"),
                        "profilePopoverOpen": root.property("profilePopoverOpen"),
                        "visibleCheckRowCount": root.property("visibleCheckRowCount"),
                        "entranceDuration": root.property("entranceDuration"),
                        "reducedTravel": root.property("reducedMotionTravel"),
                        "reducedStagger": root.property("reducedMotionStagger"),
                    }})
                    QMetaObject.invokeMethod(root, "closeProfilePopover")
                fonts = root.property("productFontFamilies")
                if hasattr(fonts, "toVariant"):
                    fonts = fonts.toVariant()
                print(json.dumps({{
                    "fonts": fonts,
                    "focusOrder": focus_order,
                    "viewports": viewports,
                }}))
                runtime.close()
                """
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        payload = __import__("json").loads(result.stdout)
        self.assertTrue(payload["fonts"]["operational"])
        self.assertTrue(payload["fonts"]["display"])
        self.assertEqual(
            payload["focusOrder"],
            [
                "profileSelector",
                "presentationViewControl",
                "grafiksLaunchControl",
                "qaPrimaryAction",
                "homeFindingsLink",
                "homeManualReviewLink",
                "homeEvidenceLink",
                "homeHistoryLink",
                "qaPipelineSpine",
                "qaCheckRow0",
                "qaInspectionAction",
                "navigationJumpAction",
            ],
            msg=payload,
        )
        for viewport in payload["viewports"]:
            self.assertEqual(viewport["gateCount"], 7)
            self.assertTrue(viewport["allAccessibleNamesPresent"])
            self.assertTrue(viewport["primaryActionVisible"])
            self.assertTrue(viewport["layoutWithinViewport"])
            self.assertTrue(viewport["profilePopoverOpen"])
            self.assertEqual(viewport["visibleCheckRowCount"], 4)
            self.assertLessEqual(viewport["entranceDuration"], 700)
            self.assertEqual(viewport["reducedTravel"], 8)
            self.assertEqual(viewport["reducedStagger"], 0)

    @unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
    def test_modal_overlays_trap_and_restore_focus(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_headless(
                f"""
                import json
                from PySide6.QtCore import QMetaObject, Q_ARG, QObject, Qt
                from PySide6.QtTest import QTest
                from sg_preflight.desktop.qt_quick_app import create_qt_quick_runtime

                runtime = create_qt_quick_runtime(workspace={temp_dir!r}, initial_profile_id="G65", argv=["sgfx-modal-focus-test"])
                root = runtime.engine.rootObjects()[0]
                root.setProperty("shellInitializationStarted", True)
                runtime.application.processEvents()
                QTest.qWait(0)
                runtime.application.processEvents()
                controller = runtime.controller
                controller._generation += 1
                controller._set_current_identity(None)
                controller._accept_shell_profile({{
                    "schemaVersion": 1,
                    "profileOptions": [{{"id": "G65", "label": "BMW G65"}}],
                    "selectedProfile": {{"id": "G65", "label": "BMW G65"}},
                }})
                runtime.application.processEvents()

                def focused_name():
                    focused = runtime.application.focusObject()
                    return "" if focused is None else focused.objectName()

                profile = root.findChild(QObject, "profileSelector")
                presentation = root.findChild(QObject, "presentationViewControl")

                profile.forceActiveFocus(Qt.TabFocusReason)
                QMetaObject.invokeMethod(root, "handleShortcut", Q_ARG(str, "F1"))
                runtime.application.processEvents()
                help_open = focused_name()
                QTest.keyClick(root, Qt.Key_Tab)
                runtime.application.processEvents()
                help_tab = focused_name()
                QMetaObject.invokeMethod(root, "handleShortcut", Q_ARG(str, "Esc"))
                runtime.application.processEvents()
                help_restored = focused_name()

                presentation.forceActiveFocus(Qt.TabFocusReason)
                QMetaObject.invokeMethod(root, "handleShortcut", Q_ARG(str, "/"))
                runtime.application.processEvents()
                jump_open = focused_name()
                QTest.keyClick(root, Qt.Key_Backtab)
                runtime.application.processEvents()
                jump_backtab = focused_name()
                QTest.keyClick(root, Qt.Key_Tab)
                runtime.application.processEvents()
                jump_tab = focused_name()
                QMetaObject.invokeMethod(root, "handleShortcut", Q_ARG(str, "Esc"))
                runtime.application.processEvents()
                jump_restored = focused_name()

                presentation.forceActiveFocus(Qt.TabFocusReason)
                QMetaObject.invokeMethod(root, "handleShortcut", Q_ARG(str, "F12"))
                runtime.application.processEvents()
                diagnostics_open = focused_name()
                QTest.keyClick(root, Qt.Key_Tab)
                runtime.application.processEvents()
                diagnostics_tab = focused_name()
                QMetaObject.invokeMethod(root, "handleShortcut", Q_ARG(str, "Esc"))
                runtime.application.processEvents()
                diagnostics_restored = focused_name()

                print(json.dumps({{
                    "help": [help_open, help_tab, help_restored],
                    "jump": [jump_open, jump_backtab, jump_tab, jump_restored],
                    "diagnostics": [diagnostics_open, diagnostics_tab, diagnostics_restored],
                    "openStates": [root.property("jumpOpen"), root.property("helpOpen"), root.property("diagnosticsOpen")],
                }}))
                runtime.close()
                """
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        payload = __import__("json").loads(result.stdout)
        self.assertEqual(payload["help"], ["helpCloseControl", "helpCloseControl", "profileSelector"])
        self.assertEqual(
            payload["jump"],
            ["jumpFilter", "jumpCloseControl", "jumpFilter", "presentationViewControl"],
        )
        self.assertEqual(
            payload["diagnostics"],
            ["diagnosticsCloseControl", "diagnosticsCloseControl", "presentationViewControl"],
        )
        self.assertEqual(payload["openStates"], [False, False, False])

    @unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
    def test_review_steps_have_truthful_keyboard_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_headless(
                f"""
                import json
                import time
                from PySide6.QtCore import QObject, Qt
                from PySide6.QtTest import QTest
                from sg_preflight.desktop.qt_quick_app import create_qt_quick_runtime

                runtime = create_qt_quick_runtime(workspace={temp_dir!r}, initial_profile_id="G65", argv=["sgfx-keyboard-order-test"])
                root = runtime.engine.rootObjects()[0]
                root.setProperty("shellInitializationStarted", True)
                runtime.application.processEvents()
                QTest.qWait(0)
                runtime.application.processEvents()
                controller = runtime.controller
                controller._generation += 1
                controller._set_current_identity(None)
                controller._accept_shell_profile({{
                    "schemaVersion": 1,
                    "profileOptions": [{{"id": "G65", "label": "BMW G65"}}],
                    "selectedProfile": {{"id": "G65", "label": "BMW G65"}},
                }})
                items = [
                    {{
                        "itemId": "review-1", "sectionId": "main", "label": "Review 1",
                        "value": "Pending", "detail": "", "status": "pending", "expected": "",
                        "actual": "", "diff": "", "source": "", "revision": ""
                    }},
                    {{
                        "itemId": "review-2", "sectionId": "main", "label": "Review 2",
                        "value": "Pending", "detail": "", "status": "pending", "expected": "",
                        "actual": "", "diff": "", "source": "", "revision": ""
                    }},
                ]
                page = {{
                    "surfaceId": "manual-review", "rendererKind": "review", "title": "Review",
                    "subtitle": "Review", "status": "pending", "dataAvailable": True,
                    "primaryText": "Review evidence", "visibleItems": items, "visibleItemCount": 2,
                    "sections": [], "artifacts": [], "provenance": {{}}, "ownershipNote": "Operator owned",
                    "readOnly": True, "isApproval": False, "manualReviewRequired": True,
                    "recordsOperatorVerdict": True,
                    "actions": [{{
                        "capabilityId": "manual_review.record", "label": "Record", "enabled": True,
                        "actionId": "", "effectClass": "tool_output_only"
                    }}]
                }}
                controller._cache[(controller.currentProfileId, "manual-review")] = page
                accepted = controller.navigate("manual-review")
                deadline = time.monotonic() + 20
                while controller.pageState == "loading" and time.monotonic() < deadline:
                    runtime.application.processEvents()
                    QTest.qWait(5)
                rows_deadline = time.monotonic() + 2
                repeater = root.findChild(QObject, "reviewRows")
                while (repeater is None or repeater.property("count") < 2) and time.monotonic() < rows_deadline:
                    runtime.application.processEvents()
                    QTest.qWait(5)
                    repeater = root.findChild(QObject, "reviewRows")
                renderer = root.findChild(QObject, "reviewRenderer")
                first_row = None
                pending_items = [root.contentItem()]
                while pending_items:
                    visual_item = pending_items.pop()
                    pending_items.extend(visual_item.childItems())
                    if visual_item.objectName() == "reviewStepControl0":
                        first_row = visual_item
                if first_row is not None:
                    first_row.forceActiveFocus(Qt.TabFocusReason)
                    runtime.application.processEvents()
                first_focus = runtime.application.focusObject()
                first_focus_name = first_focus.objectName() if first_focus is not None else ""
                review_result = [
                    accepted,
                    first_focus_name == "reviewStepControl0",
                    repeater is not None and repeater.property("count") == 2,
                ]
                if all(review_result) and renderer is not None:
                    QTest.keyClick(root, Qt.Key_Tab)
                    runtime.application.processEvents()
                    tab_focus = runtime.application.focusObject()
                    QTest.keyClick(root, Qt.Key_Space)
                    runtime.application.processEvents()
                    note = root.findChild(QObject, "reviewNoteControl")
                    note.forceActiveFocus(Qt.TabFocusReason)
                    QTest.keyClick(root, Qt.Key_Tab)
                    runtime.application.processEvents()
                    note_tab = runtime.application.focusObject()
                    review_result.extend([
                        "" if tab_focus is None else tab_focus.objectName(),
                        renderer.property("selectedStepIndex"),
                        "" if note_tab is None else note_tab.objectName(),
                    ])
                print(json.dumps({{"review": review_result}}))
                runtime.close()
                """
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        payload = __import__("json").loads(result.stdout)
        self.assertEqual(
            payload["review"],
            [True, True, True, "reviewStepControl1", 1, "recordManualReviewControl"],
            msg=payload,
        )

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
                deadline = __import__("time").monotonic() + 20
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
        self.assertEqual(payload["groups"], ["Current Session", "Manual Review", "Evidence", "History", "Tools"])
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
                deadline = time.monotonic() + 20
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
                deadline = time.monotonic() + 20
                while runtime.controller.pageState not in {{"ready", "error"}} and time.monotonic() < deadline:
                    runtime.application.processEvents()
                    time.sleep(0.005)
                invoked_f2 = QMetaObject.invokeMethod(root, "handleShortcut", Q_ARG(str, "F2"))
                runtime.application.processEvents()
                f2_focused = root.property("profileSelectorFocused")
                generation = runtime.controller._generation
                invoked_f5 = QMetaObject.invokeMethod(root, "handleShortcut", Q_ARG(str, "F5"))
                refresh_identity = runtime.controller._current_identity
                deadline = time.monotonic() + 20
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
                deadline = time.monotonic() + 20
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
        self.assertEqual(payload["refreshTuple"], ["G65", "home", "refresh"])
        self.assertTrue(payload["jumpClosed"])
        self.assertEqual((payload["route"], payload["activeRoute"]), ("risk-score", "risk-score"))
        self.assertEqual(payload["before"], payload["afterHome"])

    @unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
    def test_non_home_orientation_and_escape_keep_the_selected_car_and_return_home(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_headless(
                f"""
                import json
                import time
                from PySide6.QtCore import QMetaObject, Q_ARG, QObject, Qt
                from PySide6.QtTest import QTest
                from sg_preflight.desktop.qt_quick_app import create_qt_quick_runtime

                runtime = create_qt_quick_runtime(workspace={temp_dir!r}, initial_profile_id="G65", argv=["sgfx-orientation-test"])
                root = runtime.engine.rootObjects()[0]
                root.requestUpdate()

                def wait_for_page():
                    deadline = time.monotonic() + 20
                    while runtime.controller.pageState == "loading" and time.monotonic() < deadline:
                        runtime.application.processEvents()
                        time.sleep(0.005)

                initial_deadline = time.monotonic() + 20
                while runtime.controller.pageState not in {{"ready", "error"}} and time.monotonic() < initial_deadline:
                    runtime.application.processEvents()
                    time.sleep(0.005)
                runtime.controller.navigate("setup-doctor")
                wait_for_page()
                home_control = root.findChild(QObject, "pageHomeControl")
                breadcrumb = root.findChild(QObject, "pageBreadcrumbText")
                profile_badge = root.findChild(QObject, "pageProfileBadge")
                before = {{
                    "route": runtime.controller.currentRouteId,
                    "homeVisible": home_control is not None and bool(home_control.property("visible")),
                    "breadcrumb": "" if breadcrumb is None else breadcrumb.property("text"),
                    "profile": "" if profile_badge is None else profile_badge.property("text"),
                }}
                profile_selector = root.findChild(QObject, "profileSelector")
                profile_selector.forceActiveFocus(Qt.TabFocusReason)
                runtime.application.processEvents()
                focused_before_tab = runtime.application.focusObject()
                tab_origin = "" if focused_before_tab is None else focused_before_tab.objectName()
                profile_focus_state = {{
                    "enabled": bool(profile_selector.property("enabled")),
                    "visible": bool(profile_selector.property("visible")),
                    "activeFocus": bool(profile_selector.property("activeFocus")),
                }}
                QTest.keyClick(root, Qt.Key_Tab)
                runtime.application.processEvents()
                focused = runtime.application.focusObject()
                tab_target = "" if focused is None else focused.objectName()

                QMetaObject.invokeMethod(root, "setPresentation", Q_ARG(bool, True))
                runtime.application.processEvents()
                presentation = {{
                    "enabled": root.property("presentationView"),
                    "homeVisible": home_control is not None and bool(home_control.property("visible")),
                    "breadcrumbVisible": breadcrumb is not None and bool(breadcrumb.property("visible")),
                    "profileVisible": profile_badge is not None and bool(profile_badge.property("visible")),
                    "profile": "" if profile_badge is None else profile_badge.property("text"),
                }}

                QMetaObject.invokeMethod(root, "handleShortcut", Q_ARG(str, "Esc"))
                runtime.application.processEvents()
                after_presentation = [
                    runtime.controller.currentRouteId,
                    root.property("presentationView"),
                    root.property("sidebarOpen"),
                ]
                QMetaObject.invokeMethod(root, "handleShortcut", Q_ARG(str, "Esc"))
                runtime.application.processEvents()
                after_home = [
                    runtime.controller.currentRouteId,
                    root.property("sidebarOpen"),
                    root.property("exitGuidanceVisible"),
                ]
                print(json.dumps({{
                    "before": before,
                    "profileFocusState": profile_focus_state,
                    "tabOrigin": tab_origin,
                    "tabTarget": tab_target,
                    "presentation": presentation,
                    "afterPresentation": after_presentation,
                    "afterHome": after_home,
                }}))
                runtime.close()
                """
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        payload = __import__("json").loads(result.stdout)
        self.assertEqual(payload["before"]["route"], "setup-doctor")
        self.assertTrue(payload["before"]["homeVisible"])
        self.assertEqual(payload["before"]["breadcrumb"], "QA overview / Setup Doctor")
        self.assertEqual(payload["before"]["profile"], "Selected car: G65")
        self.assertEqual(payload["profileFocusState"], {"enabled": True, "visible": True, "activeFocus": True})
        self.assertEqual(payload["tabOrigin"], "profileSelector", msg=payload)
        self.assertEqual(payload["tabTarget"], "presentationViewControl")
        self.assertEqual(
            payload["presentation"],
            {
                "enabled": True,
                "homeVisible": True,
                "breadcrumbVisible": True,
                "profileVisible": True,
                "profile": "Selected car: G65",
            },
        )
        self.assertEqual(payload["afterPresentation"], ["setup-doctor", False, True])
        self.assertEqual(payload["afterHome"], ["home", True, False])

    @unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
    def test_status_badges_map_semantic_text_and_color_at_runtime(self) -> None:
        qml_root = ROOT / "sg_preflight" / "desktop" / "qml"
        probe_source = b"""import QtQuick
import "components" as Components
Item {
    Components.StatusBadge { objectName: "failed"; status: "failed" }
    Components.StatusBadge { objectName: "findings"; status: "findings" }
    Components.StatusBadge { objectName: "queued"; status: "queued" }
    Components.StatusBadge { objectName: "running"; status: "running" }
    Components.StatusBadge { objectName: "recorded"; status: "recorded" }
    Components.StatusBadge { objectName: "notRecorded"; status: "not_recorded" }
    Components.StatusBadge { objectName: "external"; status: "external" }
    Components.StatusBadge { objectName: "humanReview"; status: "human_review" }
    Components.StatusBadge { objectName: "passed"; status: "passed" }
    Components.StatusBadge { objectName: "available"; status: "available" }
    Components.StatusBadge { objectName: "unknown"; status: "custom<script> state" }
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
                deadline = time.monotonic() + 20
                while runtime.controller.pageState == "loading" and time.monotonic() < deadline:
                    runtime.application.processEvents()
                    time.sleep(0.005)
                component = QQmlComponent(runtime.engine)
                component.setData({probe_source!r}, QUrl.fromLocalFile({str(qml_root)!r} + "/"))
                probe = component.create()
                if probe is None:
                    raise SystemExit(" | ".join(error.toString() for error in component.errors()))
                values = {{}}
                for name in (
                    "failed", "findings", "queued", "running", "recorded", "notRecorded",
                    "external", "humanReview", "passed", "available", "unknown"
                ):
                    badge = probe.findChild(QObject, name)
                    values[name] = [
                        badge.property("statusText"), badge.property("statusTone"),
                        badge.property("statusColor").name()
                    ]
                print(json.dumps(values))
                probe.deleteLater()
                runtime.close()
                """
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        self.assertEqual(
            __import__("json").loads(result.stdout),
            {
                "failed": ["Failed", "bad", "#f14c4c"],
                "findings": ["Findings", "warn", "#cca700"],
                "queued": ["Queued", "active", "#6cb6ff"],
                "running": ["Running", "active", "#6cb6ff"],
                "recorded": ["Evidence recorded", "evidence", "#4ec9b0"],
                "notRecorded": ["Not recorded", "neutral", "#8b949e"],
                "external": ["External evidence", "neutral", "#8b949e"],
                "humanReview": ["Human review", "warn", "#cca700"],
                "passed": ["Passed", "good", "#89d185"],
                "available": ["Available", "evidence", "#4ec9b0"],
                "unknown": ["Custom script state", "neutral", "#8b949e"],
            },
        )

    @unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
    def test_home_status_aggregates_findings_without_claiming_availability(self) -> None:
        snapshot = {
            "schemaVersion": 1,
            "scopeLabel": "BMW G65",
            "selectedProfile": {"id": "G65", "label": "BMW G65"},
            "gates": [
                {"id": "context", "label": "Context", "state": "available", "checks": []},
                {"id": "asset", "label": "Asset", "state": "findings", "checks": []},
            ],
            "selectedGateId": "asset",
            "latestLocalRun": {},
            "nextAction": {},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_headless(
                f"""
                import json
                from PySide6.QtCore import QObject
                from sg_preflight.desktop.qt_quick_app import create_qt_quick_runtime
                runtime = create_qt_quick_runtime(workspace={temp_dir!r}, initial_profile_id="G65", argv=["sgfx-status-test"])
                root = runtime.engine.rootObjects()[0]
                root.setProperty("shellInitializationStarted", True)
                controller = runtime.controller
                controller._generation += 1
                controller._set_current_identity(None)
                controller._accept_shell_profile({{
                    "schemaVersion": 1,
                    "profileOptions": [{{"id": "G65", "label": "BMW G65"}}],
                    "selectedProfile": {{"id": "G65", "label": "BMW G65"}},
                }})
                controller._set_route("home")
                controller._set_ready_payload({snapshot!r})
                runtime.application.processEvents()
                badge = root.findChild(QObject, "shellStatus")
                print(json.dumps([
                    badge.property("status"), badge.property("statusText"),
                    badge.property("statusTone"), badge.property("statusColor").name()
                ]))
                runtime.close()
                """
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        self.assertEqual(
            __import__("json").loads(result.stdout),
            ["findings", "Findings", "warn", "#cca700"],
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
                deadline = time.monotonic() + 20
                while runtime.controller.pageState not in {{"ready", "error"}} and time.monotonic() < deadline:
                    runtime.application.processEvents()
                    time.sleep(0.005)
                runtime.application.processEvents()
                time.sleep(0.02)
                runtime.application.processEvents()
                initial = [runtime.controller.currentProfileId, root.property("selectedProfileValue")]
                alternative = next(option["id"] for option in runtime.controller.profileOptions if option["id"] != "G70")
                accepted = runtime.controller.selectProfile(alternative)
                deadline = time.monotonic() + 20
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
                deadline = time.monotonic() + 20
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
                deadline = time.monotonic() + 20
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
                "started": ["loading", "refresh"],
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
                print(runtime.preview_coordinator.parent() is runtime.engine)
                print(runtime.preview_image_provider.token_count)
                print(runtime.controller.previewState)
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
                "QA overview",
                "True",
                "True",
                "True",
                "True",
                "True",
                "True",
                "True",
                "True",
                "True",
                "True",
                "0",
                "fallback",
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
                deadline = time.monotonic() + 20
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

        preview = Recorder("preview")

        class Controller(Recorder):
            def shutdown(self) -> None:
                super().shutdown()
                preview.shutdown()

        runtime = QtQuickRuntime(
            application=Application(),
            engine=Engine(),
            surface_model=object(),
            shell_model=object(),
            controller=Controller("controller"),
            task_coordinator=Recorder("coordinator"),
            preview_coordinator=preview,
            preview_image_provider=object(),
        )

        runtime.close()
        runtime.close()

        self.assertEqual(events, ["controller", "preview", "coordinator", "root", "engine", "application"])

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

            def addImageProvider(self, name: str, provider: object) -> None:
                self.image_provider = (name, provider)

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
                self.kwargs["preview_coordinator"].shutdown()

        class GrafiksHost:
            def __init__(self, **kwargs: object) -> None:
                self.kwargs = kwargs

            def shutdown(self) -> None:
                events.append("grafiks")

        class PreviewProvider:
            pass

        class PreviewCoordinator:
            def __init__(self, **kwargs: object) -> None:
                self.kwargs = kwargs

            def shutdown(self) -> None:
                events.append("preview")

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
                            with mock.patch.object(qt_quick_app, "PreviewImageProvider", PreviewProvider):
                                with mock.patch.object(qt_quick_app, "PreviewCoordinator", PreviewCoordinator):
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

        self.assertEqual(events, ["load", "controller", "grafiks", "preview", "coordinator"])
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

            def addImageProvider(self, name: str, provider: object) -> None:
                self.image_provider = (name, provider)

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
                self.kwargs["preview_coordinator"].shutdown()

        class GrafiksHost:
            def __init__(self, **kwargs: object) -> None:
                self.kwargs = kwargs

            def shutdown(self) -> None:
                events.append("grafiks")

        class PreviewProvider:
            pass

        class PreviewCoordinator:
            def __init__(self, **kwargs: object) -> None:
                self.kwargs = kwargs

            def shutdown(self) -> None:
                events.append("preview")

        with tempfile.TemporaryDirectory() as temp_dir:
            qml_path = Path(temp_dir) / "Main.qml"
            qml_path.write_text("fixture\n", encoding="utf-8")
            with mock.patch.object(qt_quick_app, "_application", return_value=object()):
                with mock.patch.object(qt_quick_app, "QQmlApplicationEngine", Engine):
                    with mock.patch.object(qt_quick_app, "PageTaskCoordinator", Coordinator):
                        with mock.patch.object(qt_quick_app, "GrafiksHostAdapter", GrafiksHost):
                            with mock.patch.object(qt_quick_app, "PreviewImageProvider", PreviewProvider):
                                with mock.patch.object(qt_quick_app, "PreviewCoordinator", PreviewCoordinator):
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

        self.assertEqual(events, ["controller", "grafiks", "preview", "coordinator"])
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
