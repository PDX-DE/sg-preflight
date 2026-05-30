from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
NATIVE_SRC = ROOT / "desktop_native" / "src"
SHELL_SRC = NATIVE_SRC / "sgfx_shell"


class TestNativeShellReplacement(unittest.TestCase):
    def test_native_entrypoint_is_thin_and_uses_replacement_shell(self) -> None:
        main_source = (NATIVE_SRC / "main.cpp").read_text(encoding="utf-8")

        self.assertLess(main_source.count("\n"), 90)
        self.assertIn("#include \"sgfx_shell/sgfx_shell_app.hpp\"", main_source)
        self.assertIn("sg_preflight::sgfx_shell::RunShell", main_source)
        self.assertNotIn("DrawInstallerCanvasBackground", main_source)
        self.assertNotIn("RenderIntroductionScreen", main_source)
        self.assertNotIn("RenderCurrentScreen", main_source)
        self.assertNotIn("DrawBackdropChrome", main_source)
        self.assertNotIn("InstallerCanvasLayout", main_source)
        self.assertNotIn("DiscoverResourceRoot", main_source)

    def test_replacement_shell_sources_are_in_cmake_build(self) -> None:
        cmake_source = (ROOT / "desktop_native" / "CMakeLists.txt").read_text(encoding="utf-8")

        expected_sources = [
            "src/sgfx_shell/sgfx_shell_app.cpp",
            "src/sgfx_shell/sgfx_menu_manager.cpp",
            "src/sgfx_shell/sgfx_menu_base.cpp",
            "src/sgfx_shell/sgfx_shared_resources.cpp",
            "src/sgfx_shell/sgfx_menu_background.cpp",
            "src/sgfx_shell/sgfx_menu_scrolling.cpp",
            "src/sgfx_shell/sgfx_menu_controls_display.cpp",
            "src/sgfx_shell/sgfx_main_menu.cpp",
            "src/sgfx_shell/sgfx_workflow_menu.cpp",
            "src/sgfx_shell/sgfx_evidence_summary_menu.cpp",
            "src/sgfx_shell/sgfx_settings_menu.cpp",
            "src/sgfx_shell/sgfx_quick_actions_menu.cpp",
            "src/sgfx_shell/sgfx_digest_menu.cpp",
            "src/sgfx_shell/sgfx_clean_status_menu.cpp",
            "src/sgfx_shell/sgfx_diagnostic_overlay.cpp",
        ]

        for source in expected_sources:
            with self.subTest(source=source):
                self.assertIn(source, cmake_source)

    def test_shell_actions_are_rewired_to_sgfx_python_surfaces(self) -> None:
        shell_text = "\n".join(
            path.read_text(encoding="utf-8") for path in SHELL_SRC.glob("sgfx_*.cpp")
        )

        expected_commands = [
            "delivery-checklist read",
            "screenshot-test-state read",
            "daily-digest latest",
            "export-size-analysis read",
            "bmw-git-readiness read",
            "qa-hero-readiness read",
            "review-board latest",
            "template list",
            "activity-log read",
        ]

        for command in expected_commands:
            with self.subTest(command=command):
                self.assertIn(command, shell_text)

        self.assertIn("Manual review remains required.", shell_text)
        self.assertIn("Decision: not approval — evidence only.", shell_text)

    def test_grafiks_mode_replaces_sgfx_mode_label_with_backward_alias(self) -> None:
        shell_source = (SHELL_SRC / "sgfx_shell_app.cpp").read_text(encoding="utf-8")
        web_base = (ROOT / "sg_preflight" / "templates" / "base.html").read_text(encoding="utf-8")
        web_js = (ROOT / "sg_preflight" / "static" / "operator.js").read_text(encoding="utf-8")

        self.assertIn('value == L"grafiks"', shell_source)
        self.assertIn('value == L"sgfx"', shell_source)
        self.assertIn("Grafiks mode", shell_source)
        self.assertNotIn("SGFX mode", shell_source)
        self.assertIn('uiMode === "grafiks"', web_base)
        self.assertIn('mode === "grafiks"', web_js)
        self.assertIn("Grafiks mode", web_js)
        self.assertNotIn("SGFX mode", web_js)

    def test_repurposes_are_real_not_followup_stubs(self) -> None:
        shell_text = "\n".join(
            path.read_text(encoding="utf-8") for path in SHELL_SRC.glob("sgfx_*.cpp")
        )

        self.assertIn("@toggle-mode", shell_text)
        self.assertIn("@font-size", shell_text)
        self.assertIn("@dpi-scale", shell_text)
        self.assertIn("@contrast", shell_text)
        self.assertIn("openpyxl", shell_text)
        self.assertIn("requests", shell_text)
        self.assertIn("raco_headless", shell_text)
        self.assertIn("blender", shell_text)
        self.assertNotIn("append hooks are a follow-up", shell_text)

    def test_shell_creates_window_before_slow_python_preload(self) -> None:
        shell_source = (SHELL_SRC / "sgfx_shell_app.cpp").read_text(encoding="utf-8")
        run_body = shell_source[
            shell_source.index("int SgfxShellApp::run(") : shell_source.index("void SgfxShellApp::parse_command_line")
        ]

        self.assertLess(run_body.index("create_window(show_command)"), run_body.index("load_backend_state()"))
        self.assertLess(run_body.index("create_window(show_command)"), run_body.index("diagnostic_.refresh"))
        self.assertIn("InvalidateRect(window_, nullptr, TRUE);", run_body)

    def test_phase2a_assets_are_available_to_the_replacement_shell(self) -> None:
        assets = ROOT / "desktop_native" / "assets"
        expected_files = [
            "images/common/raw/general_window.png",
            "images/common/raw/select.png",
            "images/common/raw/light.png",
            "images/common/raw/options_static.png",
            "images/common/raw/options_static_flash.png",
            "sounds/ui_cursor.wav",
            "sounds/ui_confirm.wav",
            "sounds/ui_cancel.wav",
            "sounds/ui_panel_open.wav",
            "sounds/ui_panel_close.wav",
            "sounds/ui_page.wav",
        ]

        for relative_path in expected_files:
            with self.subTest(relative_path=relative_path):
                self.assertTrue((assets / relative_path).exists())

        shared_resources = (SHELL_SRC / "sgfx_shared_resources.cpp").read_text(encoding="utf-8")
        for relative_path in expected_files:
            with self.subTest(source_reference=relative_path):
                self.assertIn(relative_path.replace("/", "\\\\"), shared_resources)

    def test_replacement_shell_source_has_no_parked_or_upstream_brand_tokens(self) -> None:
        production_files = [
            path
            for path in SHELL_SRC.rglob("*")
            if path.suffix.lower() in {".cpp", ".hpp", ".h"}
        ]
        self.assertGreater(len(production_files), 10)

        fragments = [
            ("So", "nic"),
            ("s3", "air"),
            ("Oxy", "gen"),
            ("Man", "ia"),
            ("SE", "GA"),
            ("Egg", "man"),
            ("Tai", "ls"),
            ("Knuck", "les"),
            ("Robot", "nik"),
            ("RS", "DK"),
            ("Un", "leashed"),
            ("SW", "ARD"),
            ("Plug", "bot"),
            ("BA", "Chef"),
            ("Project ", "HMI"),
            ("SER", "GFX"),
        ]
        pattern = re.compile("|".join(re.escape("".join(parts)) for parts in fragments), re.IGNORECASE)

        for path in production_files:
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIsNone(pattern.search(path.name))
                self.assertIsNone(pattern.search(path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
