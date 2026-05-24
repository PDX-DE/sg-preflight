from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TestNativeScaffold(unittest.TestCase):
    def _load_clean_harness_module(self):
        harness_path = ROOT / "scripts" / "walkthrough_harness" / "capture_clean_pages.py"
        spec = importlib.util.spec_from_file_location("capture_clean_pages_for_test", harness_path)
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

        text = script_path.read_text(encoding="utf-8")
        self.assertIn("--onedir", text)
        self.assertNotIn("--onefile", text)
        self.assertIn("--windowed", text)
        self.assertIn("sgfx-preflight", text)
        self.assertIn("desktop_native/resources/exe_ico.ico", text)
        self.assertIn("sg_preflight/exe_entry.py", text)
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
        ):
            self.assertIn(asset_name, text)

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
