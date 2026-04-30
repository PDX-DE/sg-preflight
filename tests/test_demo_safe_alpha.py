from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]

TEAM_FACING_FILES = (
    Path("README.md"),
    Path("NOTICE.md"),
    Path("desktop_native/README.md"),
    Path("docs/native-alpha-demo-brief.md"),
    Path("docs/operator-ui-workflow.md"),
    Path("docs/teammate-pilot-playbook.md"),
    Path("docs/sg-preflight-status-2026-04-14.md"),
    Path("docs/TEAM_DEMO_PLAN.md"),
    Path("docs/JANA_SYNC_PREP.md"),
    Path("docs/ROADMAP_NEXT.md"),
    Path("docs/SWARD_TO_SGFX_BOUNDARY.md"),
    Path("docs/AGENT_HANDOFF.md"),
    Path("docs/TEAM_FEEDBACK_CAPTURE.md"),
    Path("docs/TEAMS_DAILY_STATUS.md"),
    Path("docs/ALPHA_REMAINING_WORK.md"),
)

FORBIDDEN_TEAM_FACING_PATTERNS = (
    re.compile(r"\bsonic\b", re.IGNORECASE),
    re.compile(r"\bsega\b", re.IGNORECASE),
    re.compile(r"\bunleashed\b", re.IGNORECASE),
    re.compile(r"\bunleashedrecomp\b", re.IGNORECASE),
    re.compile(r"reverse[- ]engineering", re.IGNORECASE),
    re.compile(r"game[- ]ui[- ]porting", re.IGNORECASE),
    re.compile(r"\beaster[- ]egg", re.IGNORECASE),
    re.compile(r"\bbachef", re.IGNORECASE),
)
BOUNDARY_ONLY_PATTERNS = (
    re.compile(r"\bsward\b", re.IGNORECASE),
)


class TestDemoSafeAlpha(unittest.TestCase):
    def test_team_facing_docs_exist_and_use_safe_language(self) -> None:
        missing: list[str] = []
        risky: list[str] = []
        for relative_path in TEAM_FACING_FILES:
            path = ROOT / relative_path
            if not path.exists():
                missing.append(str(relative_path))
                continue
            text = path.read_text(encoding="utf-8")
            for pattern in FORBIDDEN_TEAM_FACING_PATTERNS:
                if pattern.search(text):
                    risky.append(f"{relative_path}: {pattern.pattern}")
            if relative_path != Path("docs/SWARD_TO_SGFX_BOUNDARY.md"):
                for pattern in BOUNDARY_ONLY_PATTERNS:
                    if pattern.search(text):
                        risky.append(f"{relative_path}: {pattern.pattern}")

        self.assertEqual(missing, [])
        self.assertEqual(risky, [])

    def test_web_home_keeps_review_board_easy_to_reach(self) -> None:
        base = (ROOT / "sg_preflight" / "templates" / "base.html").read_text(encoding="utf-8")
        home = (ROOT / "sg_preflight" / "templates" / "home.html").read_text(encoding="utf-8")

        self.assertIn('href="/ui/review-board"', base)
        self.assertIn("Review Board", base)
        self.assertIn('href="/ui/review-board"', home)
        self.assertIn("IDCEVODEV-960073", home)

    def test_native_defaults_and_bundle_script_are_demo_safe(self) -> None:
        native = (ROOT / "desktop_native" / "src" / "main.cpp").read_text(encoding="utf-8")
        build_script = (ROOT / "scripts" / "build_native_shell.ps1").read_text(encoding="utf-8")
        package_script = (ROOT / "scripts" / "package_native_shell_bundle.ps1").read_text(encoding="utf-8")
        verifier = (ROOT / "scripts" / "verify_native_shell_bundle.ps1").read_text(encoding="utf-8")

        self.assertIn('ensure_value(L"display_mode", L"work");', native)
        self.assertIn('ensure_value(L"music_enabled", L"0");', native)
        self.assertIn('L"display_mode",\n        L"work",', native)
        self.assertIn("g_shell_display_mode = LoadDisplayModePreferenceFromIni();", native)

        self.assertIn("display_mode=work", build_script)
        self.assertIn("music_enabled=0", build_script)
        self.assertIn("display_mode=work", package_script)
        self.assertIn('$musicEnabledValue = if ($IncludeMusic) { "1" } else { "0" }', package_script)
        self.assertNotIn("CHANGELOG.md", package_script)
        self.assertNotIn("game_icon.png", package_script)
        self.assertNotIn("BAChef", package_script)
        self.assertNotIn("Unleashed", package_script)
        self.assertIn("Optional reference UI resources were omitted by default.", package_script)
        self.assertIn("Optional reference UI resources were omitted by default.", verifier)

    def test_feedback_capture_docs_keep_alpha_validation_actionable(self) -> None:
        feedback = (ROOT / "docs" / "TEAM_FEEDBACK_CAPTURE.md").read_text(encoding="utf-8")
        status = (ROOT / "docs" / "TEAMS_DAILY_STATUS.md").read_text(encoding="utf-8")

        required_feedback_prompts = [
            "Would this help you review a 3D Car delivery faster?",
            "What is unclear?",
            "What would you still do manually?",
            "Which output would you trust?",
            "Which output would you ignore?",
            "What is missing before this becomes useful in daily work?",
        ]
        for prompt in required_feedback_prompts:
            self.assertIn(prompt, feedback)

        self.assertIn("Trusted teammate", feedback)
        self.assertIn("Follow-up ticket", feedback)
        self.assertIn("Do not ask whether they like the UI", feedback)

        self.assertIn("SGFX Quality-Hero", status)
        self.assertIn("not production workflow yet", status)
        self.assertIn("Jira access is still missing", status)
        self.assertIn("Review Board workflow", status)

    def test_remaining_work_doc_separates_done_next_and_blocked_items(self) -> None:
        remaining = (ROOT / "docs" / "ALPHA_REMAINING_WORK.md").read_text(encoding="utf-8")

        self.assertIn("Done In Repo", remaining)
        self.assertIn("Tool-Side Next", remaining)
        self.assertIn("Human Or Access Blocked", remaining)
        self.assertIn("Do Not Start Yet", remaining)
        self.assertIn("Review Board workflow validation", remaining)
        self.assertIn("Jira access", remaining)
        self.assertIn("Do not resend", remaining)

    def test_jana_sync_has_requested_one_page_structure_and_safe_cpp_framing(self) -> None:
        jana = (ROOT / "docs" / "JANA_SYNC_PREP.md").read_text(encoding="utf-8")

        for heading in [
            "What Is Already Done",
            "What Was Proven On Real Work",
            "What Is Still Prototype",
            "What I Need",
            "If Asked Why C++",
        ]:
            self.assertIn(heading, jana)

        self.assertIn("The Python layer remains the QA backend", jana)
        self.assertIn("native operator surface", jana)
        self.assertNotIn("High-Performance Computing", jana)
        self.assertNotIn("FPS drops", jana)


if __name__ == "__main__":
    unittest.main()
