from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TestNativeScaffold(unittest.TestCase):
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
        self.assertIn("launch-action", text)
        self.assertIn("desktop-state", text)
        self.assertIn("does not replace the Python core", text)
        self.assertIn("Review Board", text)
        self.assertIn("manual review", text)
        self.assertIn("does not run RaCo or Blender automatically", text)

    def test_native_shell_consumes_python_owned_operator_overview(self) -> None:
        bridge_header = (ROOT / "desktop_native" / "src" / "backend_bridge.hpp").read_text(encoding="utf-8")
        bridge_source = (ROOT / "desktop_native" / "src" / "backend_bridge.cpp").read_text(encoding="utf-8")
        main_source = (ROOT / "desktop_native" / "src" / "main.cpp").read_text(encoding="utf-8")

        self.assertIn("OperatorOverview", bridge_header)
        self.assertIn("LoadOperatorOverview", bridge_header)
        self.assertIn('L"overview"', bridge_source)
        self.assertIn("desktop-state", bridge_source)
        self.assertIn("overview unavailable", main_source.lower())
        self.assertIn("RenderOperatorOverviewPanel", main_source)
        self.assertIn("export_size_analysis_status", bridge_header)
        self.assertIn("export_size_analysis_variant_count", bridge_header)
        self.assertIn("Export-size analysis", main_source)

    def test_native_shell_exposes_clean_ui_mode_without_dropping_cinematic_mode(self) -> None:
        main_source = (ROOT / "desktop_native" / "src" / "main.cpp").read_text(encoding="utf-8")

        self.assertIn("ShellDisplayMode::Clean", main_source)
        self.assertIn("ShellDisplayMode::Cinematic", main_source)
        self.assertIn('L"--ui-mode"', main_source)
        self.assertIn('L"--display-mode"', main_source)
        self.assertIn('display_mode=clean', main_source)
        self.assertIn('value == L"work"', main_source)
        self.assertIn("DrawDisplayModeQuickToggle", main_source)
        self.assertIn("Clean mode", main_source)
        self.assertIn("Cinematic mode", main_source)

    def test_native_bundle_script_is_present(self) -> None:
        script_path = ROOT / "scripts" / "package_native_shell_bundle.ps1"
        self.assertTrue(script_path.exists())
        text = script_path.read_text(encoding="utf-8")
        self.assertIn("workspace", text)
        self.assertIn("python", text)
        self.assertIn("resources", text)
        self.assertIn("sg_preflight_native_shell.exe", text)


if __name__ == "__main__":
    unittest.main()
