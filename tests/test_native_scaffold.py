from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(
    (ROOT / "desktop_native").exists(),
    "curated source-review bundle excludes native R&D sources",
)
class TestNativeScaffold(unittest.TestCase):
    def _load_clean_harness_module(self):
        harness_path = ROOT / "scripts" / "walkthrough_harness" / "capture_clean_pages.py"
        spec = importlib.util.spec_from_file_location("capture_clean_pages_for_test", harness_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _load_build_exe_module(self):
        script_path = ROOT / "scripts" / "build_sgfx_exe.py"
        spec = importlib.util.spec_from_file_location("build_sgfx_exe_for_test", script_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_native_shell_cmake_scaffold_is_present(self) -> None:
        cmake_path = ROOT / "desktop_native" / "CMakeLists.txt"
        self.assertTrue(cmake_path.exists())
        text = cmake_path.read_text(encoding="utf-8")
        self.assertIn("sg_preflight_native_shell", text)
        self.assertIn("v1.92.7-docking", text)
        self.assertIn("nlohmann_json", text)

    def test_native_shell_readme_documents_python_core_contract(self) -> None:
        readme_path = ROOT / "desktop_native" / "README.md"
        self.assertTrue(readme_path.exists())
        text = readme_path.read_text(encoding="utf-8")
        self.assertIn("Deprecated 2026-05-19", text.splitlines()[2])
        self.assertIn("Python desktop shell at `sg_preflight/desktop/` is the operator UI going forward.", text)
        self.assertIn("launch-action", text)
        self.assertIn("desktop-state", text)
        self.assertIn("does not replace the Python core", text)
        self.assertIn("SGFX QA Status Board", text)
        self.assertIn("manual review", text)
        self.assertIn("does not run RaCo or Blender automatically", text)

    def test_native_shell_consumes_python_owned_operator_overview(self) -> None:
        bridge_header = (ROOT / "desktop_native" / "src" / "backend_bridge.hpp").read_text(encoding="utf-8")
        bridge_source = (ROOT / "desktop_native" / "src" / "backend_bridge.cpp").read_text(encoding="utf-8")
        shell_source = (ROOT / "desktop_native" / "src" / "sgfx_shell" / "sgfx_shell_app.cpp").read_text(encoding="utf-8")

        self.assertIn("OperatorOverview", bridge_header)
        self.assertIn("LoadOperatorOverview", bridge_header)
        self.assertIn('L"overview"', bridge_source)
        self.assertIn("desktop-state", bridge_source)
        self.assertIn("overview unavailable", shell_source.lower())
        self.assertIn("LoadOperatorOverview", shell_source)
        self.assertIn("export_size_analysis_status", bridge_header)
        self.assertIn("export_size_analysis_variant_count", bridge_header)
        self.assertIn("Export-size analysis", shell_source)

    def test_native_shell_exposes_clean_ui_mode_without_dropping_grafiks_mode(self) -> None:
        shell_source = (ROOT / "desktop_native" / "src" / "sgfx_shell" / "sgfx_shell_app.cpp").read_text(encoding="utf-8")

        self.assertIn("SgfxUiMode::Clean", shell_source)
        self.assertIn("SgfxUiMode::Branded", shell_source)
        self.assertIn('L"--ui-mode"', shell_source)
        self.assertIn('L"--display-mode"', shell_source)
        self.assertIn('display_mode=clean', shell_source)
        self.assertIn('value == L"work"', shell_source)
        self.assertIn("Clean mode", shell_source)
        self.assertIn("Grafiks mode", shell_source)

    def test_native_bundle_script_is_present(self) -> None:
        script_path = ROOT / "scripts" / "package_native_shell_bundle.ps1"
        self.assertTrue(script_path.exists())
        text = script_path.read_text(encoding="utf-8")
        self.assertIn("workspace", text)
        self.assertIn("python", text)
        self.assertIn("resources", text)
        self.assertIn("sg_preflight_native_shell.exe", text)

    def test_windows_exe_build_script_and_packaging_extra_are_present(self) -> None:
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        script_path = ROOT / "scripts" / "build_sgfx_exe.py"

        self.assertTrue(script_path.exists())
        self.assertIn("packaging = [", pyproject)
        self.assertIn("PyInstaller>=6.20,<7", pyproject)
        self.assertIn("data/*.json", pyproject)
        self.assertIn('requires-python = ">=3.10"', pyproject)
        self.assertEqual(pyproject.count('"keyring>=25,<26"'), 1)
        self.assertEqual(
            pyproject.count('"pywin32-ctypes>=0.2.2,<1; platform_system == \'Windows\'"'),
            1,
        )
        self.assertEqual(pyproject.count('"desktop/qml/*.qml"'), 1)
        self.assertEqual(pyproject.count('"desktop/qml/**/*.qml"'), 1)
        self.assertEqual(pyproject.count('"desktop/qml/**/qmldir"'), 1)

        text = script_path.read_text(encoding="utf-8")
        self.assertIn("--onedir", text)
        self.assertNotIn("--onefile", text)
        self.assertIn("--windowed", text)
        self.assertIn("sgfx-preflight", text)
        self.assertIn("desktop_native/resources/exe_ico.ico", text)
        self.assertIn("sg_preflight/exe_entry.py", text)
        self.assertIn("GRAFIKS_RUNTIME_FILES", text)
        self.assertIn("sgfx_cine_cinematic_shell.exe", text)
        self.assertIn("ramses-shared-lib-headless.dll", text)
        self.assertIn("STAGING_DIST_PATH", text)
        self.assertIn("validate_staged_bundle", text)
        self.assertIn("swap_staged_bundle", text)
        self.assertIn('bundle_dir / "_internal"', text)
        self.assertEqual(text.count('"PySide6.QtQml"'), 1)
        self.assertEqual(text.count('"PySide6.QtQuick"'), 1)
        self.assertEqual(text.count('"PySide6.QtQuickControls2"'), 1)
        self.assertIn(".[packaging,desktop]", text)
        self.assertNotIn("clean_stale_outputs", text)
        for asset_name in (
            "sgfx_icon.png",
            "framework_sgfx_logo.png",
            "logo_sgfx.png",
            "exe_ico.png",
            "debug_icon.png",
            "desktop_native/resources/exe_ico.ico",
            "desktop_native/resources/debug_icon.ico",
            "sg_preflight/static",
            "sg_preflight/templates",
            "sg_preflight/dashboard",
            "sg_preflight/data",
            "sg_preflight/desktop/qml",
        ):
            self.assertIn(asset_name, text)
        self.assertIn('rglob("*.qml")', text)
        self.assertIn('rglob("qmldir")', text)
        self.assertLess(
            text.index("copy_grafiks_runtime(staged_bundle)"),
            text.index("copy_operator_console_shell(staged_bundle)"),
        )
        self.assertLess(
            text.index("copy_operator_console_shell(staged_bundle)"),
            text.index("swap_staged_bundle(staged_bundle)"),
        )

    def test_qml_package_inputs_include_nested_components_singleton_and_qmldir(self) -> None:
        module = self._load_build_exe_module()

        inputs = {
            path.relative_to(ROOT / "sg_preflight" / "desktop" / "qml").as_posix()
            for path in module.qml_package_inputs()
        }

        self.assertIn("Main.qml", inputs)
        self.assertIn("components/HomePage.qml", inputs)
        self.assertIn("components/PageFrame.qml", inputs)
        self.assertEqual(
            {
                "renderers/OverviewRenderer.qml",
                "renderers/MatrixRenderer.qml",
                "renderers/EvidenceRenderer.qml",
                "renderers/WorkflowRenderer.qml",
                "renderers/ReviewRenderer.qml",
                "renderers/AboutRenderer.qml",
            },
            {path for path in inputs if path.startswith("renderers/")},
        )
        self.assertIn("SGFX/Theme.qml", inputs)
        self.assertIn("SGFX/qmldir", inputs)
        self.assertTrue(all(path.suffix == ".qml" or path.name == "qmldir" for path in module.qml_package_inputs()))

    @staticmethod
    def _windows_backend(*, priority: int | BaseException = 5) -> mock.Mock:
        backend = mock.Mock()
        backend_type = mock.Mock()
        if isinstance(priority, BaseException):
            descriptor = mock.PropertyMock(side_effect=priority)
        else:
            descriptor = mock.PropertyMock(return_value=priority)
        type(backend_type).priority = descriptor
        backend.WinVaultKeyring = backend_type
        return backend

    def test_packaging_import_probe_requires_keyring_and_positive_windows_backend(self) -> None:
        from sg_preflight import exe_entry

        backend = self._windows_backend(priority=5)
        with mock.patch.dict(os.environ, {exe_entry.PACKAGING_IMPORT_PROBE_ENV: "1"}):
            with mock.patch.object(
                exe_entry.importlib,
                "import_module",
                side_effect=[mock.Mock(), backend],
            ) as importer:
                self.assertEqual(exe_entry.run_packaging_import_probe(), 0)

        self.assertEqual(
            exe_entry.PACKAGING_REQUIRED_IMPORTS,
            ("keyring", "keyring.backends.Windows"),
        )
        self.assertEqual(
            [call.args[0] for call in importer.call_args_list],
            list(exe_entry.PACKAGING_REQUIRED_IMPORTS),
        )

        for priority in (0, -1):
            with self.subTest(priority=priority):
                backend = self._windows_backend(priority=priority)
                with mock.patch.dict(os.environ, {exe_entry.PACKAGING_IMPORT_PROBE_ENV: "1"}):
                    with mock.patch.object(
                        exe_entry.importlib,
                        "import_module",
                        side_effect=[mock.Mock(), backend],
                    ):
                        self.assertEqual(exe_entry.run_packaging_import_probe(), 86)

        with mock.patch.dict(os.environ, {exe_entry.PACKAGING_IMPORT_PROBE_ENV: "1"}):
            with mock.patch.object(
                exe_entry.importlib,
                "import_module",
                side_effect=ImportError("private import detail"),
            ):
                self.assertEqual(exe_entry.run_packaging_import_probe(), 86)

        backend = self._windows_backend(priority=RuntimeError("missing backend"))
        with mock.patch.dict(os.environ, {exe_entry.PACKAGING_IMPORT_PROBE_ENV: "1"}):
            with mock.patch.object(
                exe_entry.importlib,
                "import_module",
                side_effect=[mock.Mock(), backend],
            ):
                self.assertEqual(exe_entry.run_packaging_import_probe(), 86)

    def test_packaging_probe_short_circuits_before_cli_startup(self) -> None:
        from sg_preflight import exe_entry

        with mock.patch.dict(os.environ, {exe_entry.PACKAGING_IMPORT_PROBE_ENV: "1"}):
            with mock.patch.object(exe_entry, "run_packaging_import_probe", return_value=86) as probe:
                with mock.patch("sg_preflight.cli.main") as cli_main:
                    self.assertEqual(exe_entry.main([]), 86)

        probe.assert_called_once_with()
        cli_main.assert_not_called()

    def test_windows_exe_build_validates_keyring_before_collection(self) -> None:
        module = self._load_build_exe_module()

        backend = self._windows_backend(priority=5)
        with mock.patch.object(
            module.importlib,
            "import_module",
            side_effect=[mock.Mock(), backend],
        ) as importer:
            module.validate_build_environment()
        self.assertEqual(
            [call.args[0] for call in importer.call_args_list],
            ["keyring", "keyring.backends.Windows"],
        )

        for priority in (0, -1):
            with self.subTest(priority=priority):
                backend = self._windows_backend(priority=priority)
                with mock.patch.object(
                    module.importlib,
                    "import_module",
                    side_effect=[mock.Mock(), backend],
                ):
                    with self.assertRaisesRegex(SystemExit, "required runtime dependencies"):
                        module.validate_build_environment()

        with mock.patch.object(
            module.importlib,
            "import_module",
            side_effect=ImportError("private import detail"),
        ):
            with self.assertRaisesRegex(SystemExit, "required runtime dependencies"):
                module.validate_build_environment()

    def test_build_print_args_does_not_require_runtime_imports(self) -> None:
        module = self._load_build_exe_module()

        with mock.patch.object(
            module,
            "validate_build_environment",
            side_effect=AssertionError("print-only mode must stay import-free"),
        ) as validator:
            with mock.patch("builtins.print"):
                self.assertEqual(module.main(["--print-args"]), 0)

        validator.assert_not_called()

    def test_staged_bundle_probe_uses_bounded_hidden_process_controls(self) -> None:
        module = self._load_build_exe_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            module.STAGING_DIST_PATH = root / "staging"
            bundle = module.STAGING_DIST_PATH / "sgfx-preflight"
            bundle.mkdir(parents=True)
            exe = bundle / "sgfx-preflight.exe"
            exe.write_text("fixture", encoding="utf-8")

            completed = mock.Mock(returncode=0)
            with mock.patch.object(module.subprocess, "run", return_value=completed) as runner:
                self.assertEqual(module.validate_staged_bundle(), bundle)

            self.assertEqual(runner.call_args.args[0], [str(exe)])
            kwargs = runner.call_args.kwargs
            self.assertEqual(kwargs["cwd"], bundle)
            self.assertEqual(kwargs["timeout"], 30)
            self.assertIs(kwargs["stdout"], subprocess.DEVNULL)
            self.assertIs(kwargs["stderr"], subprocess.DEVNULL)
            self.assertFalse(kwargs["check"])
            self.assertEqual(
                kwargs["creationflags"],
                getattr(module.subprocess, "CREATE_NO_WINDOW", 0),
            )
            self.assertEqual(kwargs["env"][module.PACKAGING_IMPORT_PROBE_ENV], "1")

            with mock.patch.object(module.subprocess, "run", return_value=mock.Mock(returncode=86)):
                with self.assertRaisesRegex(SystemExit, "runtime dependency validation failed"):
                    module.validate_staged_bundle()

            with mock.patch.object(
                module.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired([str(exe)], 30),
            ):
                with self.assertRaisesRegex(SystemExit, "runtime dependency validation timed out"):
                    module.validate_staged_bundle()

    def test_windows_exe_build_script_swaps_staged_bundle_after_success(self) -> None:
        module = self._load_build_exe_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            module.DIST_PATH = root / "dist"
            module.WORK_PATH = root / "work"
            module.BACKUP_BUNDLE_PATH = root / "backup"
            module.BACKUP_SINGLE_FILE_PATH = root / "backup.exe"
            staged_bundle = root / "staging" / "sgfx-preflight"
            final_bundle = module.DIST_PATH / "sgfx-preflight"
            staged_bundle.mkdir(parents=True)
            final_bundle.mkdir(parents=True)
            (staged_bundle / "sgfx-preflight.exe").write_text("new", encoding="utf-8")
            (final_bundle / "sgfx-preflight.exe").write_text("old", encoding="utf-8")
            (module.DIST_PATH / "sgfx-preflight.exe").write_text("old onefile", encoding="utf-8")

            module.swap_staged_bundle(staged_bundle)

            self.assertEqual((final_bundle / "sgfx-preflight.exe").read_text(encoding="utf-8"), "new")
            self.assertFalse(staged_bundle.exists())
            self.assertFalse((module.DIST_PATH / "sgfx-preflight.exe").exists())
            self.assertFalse(module.BACKUP_BUNDLE_PATH.exists())
            self.assertFalse(module.BACKUP_SINGLE_FILE_PATH.exists())

    def test_windows_exe_build_script_restores_existing_bundle_after_swap_failure(self) -> None:
        module = self._load_build_exe_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            module.DIST_PATH = root / "dist"
            module.WORK_PATH = root / "work"
            module.BACKUP_BUNDLE_PATH = root / "backup"
            module.BACKUP_SINGLE_FILE_PATH = root / "backup.exe"
            staged_bundle = root / "staging" / "sgfx-preflight"
            final_bundle = module.DIST_PATH / "sgfx-preflight"
            staged_bundle.mkdir(parents=True)
            final_bundle.mkdir(parents=True)
            (staged_bundle / "sgfx-preflight.exe").write_text("new", encoding="utf-8")
            (final_bundle / "sgfx-preflight.exe").write_text("old", encoding="utf-8")

            with mock.patch.object(module.shutil, "move", side_effect=RuntimeError("swap failed")):
                with self.assertRaisesRegex(RuntimeError, "swap failed"):
                    module.swap_staged_bundle(staged_bundle)

            self.assertEqual((final_bundle / "sgfx-preflight.exe").read_text(encoding="utf-8"), "old")
            self.assertTrue(staged_bundle.exists())
            self.assertFalse(module.BACKUP_BUNDLE_PATH.exists())

    def test_bundle_script_copies_python_exe_and_sgfx_icon_assets(self) -> None:
        script_path = ROOT / "scripts" / "package_native_shell_bundle.ps1"
        text = script_path.read_text(encoding="utf-8")

        self.assertIn("dist\\sgfx-preflight", text)
        self.assertIn("dist\\sgfx-preflight\\sgfx-preflight.exe", text)
        self.assertIn("sgfx-preflight.exe", text)
        for asset_name in (
            "sgfx_icon.png",
            "framework_sgfx_logo.png",
            "logo_sgfx.png",
            "exe_ico.png",
            "desktop_native\\resources\\exe_ico.ico",
            "desktop_native\\resources\\debug_icon.ico",
        ):
            self.assertIn(asset_name, text)
        self.assertNotIn("desktop_native\\" + "assets", text)
        self.assertNotIn("general_" + "window.png", text)
        self.assertIn("SGFX Preflight - Clean Mode.lnk", text)
        self.assertIn("SGFX Preflight - Grafiks Mode.lnk", text)
        self.assertNotIn("SGFX Preflight - Web Review Board.lnk", text)
        self.assertIn('"operator_state"', text)
        self.assertIn('"jira_pat.json"', text)
        self.assertIn('"*credentials*.json"', text)
        self.assertIn('"*pat*.json"', text)
        self.assertIn('"*token*.json"', text)

    def test_walkthrough_harness_reattaches_to_dependency_setup_panel(self) -> None:
        harness_path = ROOT / "scripts" / "walkthrough_harness" / "uia_readiness.ps1"
        probe_path = ROOT / "scripts" / "walkthrough_harness" / "probe_grafiks_setup_uia.ps1"
        self.assertTrue(harness_path.exists())
        self.assertTrue(probe_path.exists())
        text = harness_path.read_text(encoding="utf-8")
        probe_text = probe_path.read_text(encoding="utf-8")

        self.assertIn("Wait-SgfxUiElement", text)
        self.assertIn("AutomationIdProperty", text)
        self.assertIn("NameProperty", text)
        self.assertIn("Wait-SgfxDependencySetupPanel", text)
        self.assertIn("Wait-SgfxSetupControlsAfterDialogClose", text)
        self.assertIn("Get-SgfxProcessWindowElement", text)
        self.assertIn("Wait-SgfxSetupControlsAfterDialogClose", probe_text)
        self.assertIn("grafiks", probe_text)
        self.assertIn('"Seriengrafik: Project Quality-Hero"', probe_text)
        self.assertIn("[string[]]$Profiles", probe_text)
        self.assertIn("Get-SgfxProbeProfiles", probe_text)
        self.assertIn('"G65", "G70", "NA8", "F70", "U10"', probe_text)
        self.assertIn("grafiks-setup-uia-probes.json", probe_text)
        self.assertIn("minimum_profile_set_covered", probe_text)
        self.assertIn("buggy_profile_covered", probe_text)
        self.assertIn('"Dependency Setup"', text)
        self.assertNotIn("failed_to_switch_by_automation_coordinates", text)

    def test_clean_playwright_harness_waits_for_dashboard_readiness(self) -> None:
        harness_path = ROOT / "scripts" / "walkthrough_harness" / "capture_clean_pages.py"
        self.assertTrue(harness_path.exists())
        text = harness_path.read_text(encoding="utf-8")

        self.assertIn("wait_for_clean_dashboard_ready", text)
        self.assertIn("wait_for_dashboard_page", text)
        self.assertIn("page.get_by_role", text)
        self.assertIn("page.get_by_text", text)
        self.assertIn('locator(".sgfx-panel-title").filter(has_text="Dependency setup").first', text)
        self.assertIn('PHASE_F_HARNESS_PROFILES = ("G65", "G70", "NA8", "F70", "U10")', text)
        self.assertIn("profile_contracts", text)
        self.assertIn("multi_profile_assertions", text)
        self.assertIn("cross_panel_dependency_consistency", text)
        self.assertIn("minimum_profile_set_covered", text)
        self.assertIn("buggy_profile_covered", text)
        self.assertIn("cross_panel_preflight_exercised", text)
        self.assertIn('evidence_dir / "profiles" / profile', text)
        self.assertIn("wait_for_load_state", text)
        self.assertIn('action.get("requires_confirmation") is True', text)
        self.assertNotIn('action.get("confirmation_required")', text)
        self.assertNotIn('get_by_text("Dependency setup", exact=False)', text)
        self.assertNotIn("wait_for_timeout", text)

    def test_clean_playwright_harness_profile_sequence_and_cross_panel_contract(self) -> None:
        module = self._load_clean_harness_module()

        self.assertEqual(
            module._harness_profile_sequence(["G70"]),
            ["G70", "G65", "NA8", "F70", "U10"],
        )
        snapshot = {
            "pages": [
                {
                    "id": "delivery-checklist",
                    "setup_status": {
                        "items": [
                            {"key": "raco_gui", "status": "available"},
                            {"key": "raco_headless", "status": "available"},
                            {"key": "blender", "status": "available"},
                            {"key": "digital_3d_car_repo", "status": "available"},
                        ]
                    },
                    "actions": [
                        {
                            "id": "generate-delivery-workbook",
                            "preflight": {
                                "checks": [
                                    {"key": "raco", "status": "available"},
                                    {"key": "raco_headless", "status": "available"},
                                    {"key": "blender", "status": "available"},
                                    {"key": "digital_3d_car_repo", "status": "available"},
                                ]
                            },
                        }
                    ],
                }
            ]
        }

        result = module._cross_panel_dependency_consistency(snapshot)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(len(result["compared"]), 4)

        snapshot["pages"][0]["actions"][0]["preflight"]["checks"][0]["status"] = "missing"
        result = module._cross_panel_dependency_consistency(snapshot)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["mismatches"][0]["setup_key"], "raco_gui")

    def test_reviewer_sweep_template_requires_multi_profile_runtime_evidence(self) -> None:
        template_path = ROOT / "scripts" / "walkthrough_harness" / "reviewer_sweep_template.md"
        self.assertTrue(template_path.exists())
        text = template_path.read_text(encoding="utf-8")

        self.assertIn("G65", text)
        self.assertIn("G70", text)
        self.assertIn("NA8", text)
        self.assertIn("F70", text)
        self.assertIn("U10", text)
        self.assertIn("Do not accept G65-only evidence", text)
        self.assertIn("cross_panel_preflight_exercised", text)
        self.assertIn("cross_panel_consistency", text)
        self.assertIn("grafiks-setup-uia-probes.json", text)
        self.assertIn("Manual review remains required.", text)
        self.assertIn("Decision: not approval — evidence only.", text)

    def test_reviewer_sweep_template_requires_frozen_exe_smoke(self) -> None:
        template_path = ROOT / "scripts" / "walkthrough_harness" / "reviewer_sweep_template.md"
        text = template_path.read_text(encoding="utf-8")

        self.assertIn("Frozen-.exe Smoke per Subprocess-Spawning Feature", text)
        self.assertIn("dist/sgfx-preflight/sgfx-preflight.exe", text)
        self.assertIn("subprocess_utils.install_no_window_subprocess_patch()", text)
        self.assertIn("creationflags_no_window: true", text)
        self.assertIn("frozen_exe_path", text)
        self.assertIn("frozen_exe_sha256", text)
        self.assertIn("frozen-exe-smoke/index.json", text)
        self.assertIn("spawned_interpreter", text)
        self.assertIn("_MEIPASS", text)
        self.assertIn("is_approval: false", text)

    def test_native_shell_font_discovery_ignores_archives(self) -> None:
        shell_source = (ROOT / "desktop_native" / "src" / "sgfx_shell" / "sgfx_shared_resources.cpp").read_text(encoding="utf-8")

        self.assertIn("bool IsFontFileCandidate", shell_source)
        self.assertIn(".otf", shell_source)
        self.assertIn(".ttf", shell_source)
        self.assertIn("IsFontFileCandidate(entry.path())", shell_source)
        self.assertNotIn(".zip", shell_source)
        self.assertNotIn(".7z", shell_source)


if __name__ == "__main__":
    unittest.main()
