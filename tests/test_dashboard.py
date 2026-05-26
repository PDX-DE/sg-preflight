from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.operator_helpers import write_text


class NiceGuiDashboardLazyImportTests(unittest.TestCase):
    def test_cli_import_and_parser_do_not_import_nicegui(self) -> None:
        sys.modules.pop("nicegui", None)
        sys.modules.pop("sg_preflight.dashboard.main", None)

        from sg_preflight.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "dashboard",
                "run",
                "--workspace",
                r"C:\repositories\trunk",
                "--no-native",
                "--port",
                "0",
            ]
        )

        self.assertEqual(args.command, "dashboard")
        self.assertEqual(args.dashboard_command, "run")
        self.assertEqual(args.profile, "")
        self.assertNotIn("nicegui", sys.modules)
        self.assertNotIn("sg_preflight.dashboard.main", sys.modules)


class NiceGuiDashboardModelTests(unittest.TestCase):
    def test_runtime_asset_helper_finds_sgfx_branding_files(self) -> None:
        from sg_preflight.assets import runtime_asset_dir, runtime_asset_path

        for asset_name in (
            "sgfx_icon.png",
            "framework_sgfx_logo.png",
            "logo_sgfx.png",
            "exe_ico.png",
            "debug_icon.png",
            "desktop_native/resources/exe_ico.ico",
            "desktop_native/resources/debug_icon.ico",
        ):
            with self.subTest(asset_name=asset_name):
                self.assertTrue(runtime_asset_path(asset_name).is_file())
        self.assertTrue(runtime_asset_dir("sg_preflight/dashboard").is_dir())
        self.assertTrue(runtime_asset_dir("sg_preflight/static").is_dir())

    def test_choice_options_are_nicegui_compatible_lists(self) -> None:
        from sg_preflight.dashboard.main import MANUAL_REVIEW_STATUSES, THEME_CHOICES

        self.assertIsInstance(THEME_CHOICES, list)
        self.assertEqual(THEME_CHOICES, ["clean"])
        self.assertIsInstance(MANUAL_REVIEW_STATUSES, list)

    def test_dashboard_snapshot_contains_ten_operator_pages_and_guardrails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from sg_preflight.dashboard.main import build_dashboard_snapshot

            snapshot = build_dashboard_snapshot("", tmp)

        page_ids = [page["id"] for page in snapshot["pages"]]
        self.assertEqual(
            page_ids,
            [
                "full-qa-pass",
                "delivery-checklist",
                "onboarding-guide",
                "screenshot-test-state",
                "risk-score",
                "cross-car-comparison",
                "daily-digest",
                "team-digest-board",
                "operator-handoff",
                "manual-review",
            ],
        )
        self.assertEqual(snapshot["profile_id"], snapshot["profile_options"][0]["id"])
        self.assertTrue(snapshot["profile_known"])
        self.assertIn("profile_options_all", snapshot)
        self.assertIn("profile_registry", snapshot)
        self.assertGreaterEqual(snapshot["profile_registry"]["total_count"], len(snapshot["profile_options"]))
        self.assertEqual(snapshot["theme"], "clean")
        self.assertEqual(snapshot["workspace_label"], Path(tmp).name)
        self.assertEqual(snapshot["output_root"], str(Path(tmp).resolve() / "out" / "operator-ui"))
        self.assertEqual(snapshot["output_root_label"], "operator-ui")
        self.assertEqual(
            snapshot["navigation"],
            [
                {"id": "full-qa-pass", "label": "Full QA Pass"},
                {"id": "delivery-checklist", "label": "Delivery Checklist"},
                {"id": "onboarding-guide", "label": "Onboarding Guide"},
                {"id": "screenshot-test-state", "label": "Screenshot Test State"},
                {"id": "risk-score", "label": "Risk Score"},
                {"id": "cross-car-comparison", "label": "Cross-Car Comparison"},
                {"id": "daily-digest", "label": "Daily Digest"},
                {"id": "team-digest-board", "label": "Team Digest Board"},
                {"id": "operator-handoff", "label": "Operator Handoff"},
                {"id": "manual-review", "label": "Manual Review Companion"},
                {"id": "about", "label": "About"},
            ],
        )
        self.assertEqual(
            snapshot["shortcuts"],
            ["F1 Help", "F2 Profile switch", "F5 Refresh page", "F12 Diagnostic", "Esc Quit"],
        )
        self.assertEqual(
            snapshot["pages"][0]["tagline"],
            "One local pass through setup, evidence, review assist, and handoff status.",
        )
        self.assertEqual(snapshot["pages"][1]["tagline"], "Workbook evidence per delivery profile (read-only).")
        self.assertEqual(
            snapshot["pages"][2]["tagline"],
            "New-operator path through setup, evidence pages, manual review, and handoff.",
        )
        self.assertEqual(snapshot["pages"][3]["tagline"], "BMW + MINI baseline / actual / diff counts per brand.")
        self.assertEqual(
            snapshot["pages"][4]["tagline"],
            "Per-car review focus signal with delta since latest local manual review.",
        )
        self.assertEqual(snapshot["pages"][5]["tagline"], "G70 vs G65 risk-score widget side by side.")
        self.assertEqual(snapshot["pages"][6]["tagline"], "Morning status snapshot for the SG Daily standup.")
        self.assertEqual(
            snapshot["pages"][7]["tagline"],
            "Local snapshot for standup review across selected car profiles.",
        )
        self.assertEqual(
            snapshot["pages"][8]["tagline"],
            "Record the stopping point before a shift handoff.",
        )
        self.assertEqual(
            snapshot["pages"][9]["tagline"],
            "Step through the 7 Quality-Hero review steps. Operator verdict per step.",
        )
        self.assertIn("Manual review remains required.", snapshot["guardrails"])
        self.assertIn("Decision: not approval — evidence only.", snapshot["guardrails"])
        self.assertIn("BMW Git access is read-only. SGFX never modifies BMW source.", snapshot["guardrails"])
        self.assertIn("Activity log is local-only — never posted to Jira, SVN, or BMW Git.", snapshot["guardrails"])
        full_pass_page = next(page for page in snapshot["pages"] if page["id"] == "full-qa-pass")
        self.assertIn("steps", full_pass_page["payload"])
        self.assertTrue(full_pass_page["payload"]["manual_review_required"])
        self.assertFalse(full_pass_page["payload"]["records_operator_verdict"])
        self.assertFalse(full_pass_page["payload"]["is_approval"])
        manual_page = next(page for page in snapshot["pages"] if page["id"] == "manual-review")
        self.assertEqual(manual_page["status"], "not_run")
        self.assertIn("Manual review session not started", manual_page["empty_state_note"])
        self.assertTrue(manual_page["confluence_anchors"])
        self.assertTrue(all(item["status"] == "not_run" for item in manual_page["items"]))
        self.assertTrue(all(step["verdict"] == "not_run" for step in manual_page["payload"]["steps"]))
        onboarding_page = next(page for page in snapshot["pages"] if page["id"] == "onboarding-guide")
        self.assertEqual(onboarding_page["payload"]["status"], "available")
        self.assertTrue(onboarding_page["payload"]["manual_review_required"])
        self.assertFalse(onboarding_page["payload"]["is_approval"])
        self.assertIn("dependency-setup", {item["key"] for item in onboarding_page["payload"]["steps"]})
        risk_page = next(page for page in snapshot["pages"] if page["id"] == "risk-score")
        self.assertIn("risk_score", risk_page["payload"])
        self.assertFalse(risk_page["payload"]["is_approval"])
        self.assertTrue(risk_page["payload"]["manual_review_required"])
        comparison_page = next(page for page in snapshot["pages"] if page["id"] == "cross-car-comparison")
        self.assertEqual(comparison_page["payload"]["comparison_axis"], "risk-score")
        self.assertEqual(comparison_page["payload"]["profiles"], ["G70", "G65"])
        self.assertFalse(comparison_page["payload"]["is_approval"])
        team_page = next(page for page in snapshot["pages"] if page["id"] == "team-digest-board")
        self.assertEqual(team_page["payload"]["share_decision"]["selected_model"], "local_snapshot")
        self.assertFalse(team_page["payload"]["is_approval"])
        handoff_page = next(page for page in snapshot["pages"] if page["id"] == "operator-handoff")
        self.assertEqual(handoff_page["payload"]["status"], "not_run")
        self.assertFalse(handoff_page["payload"]["is_approval"])
        self.assertIn("stopping point", handoff_page["empty_state_note"].casefold())
        for forbidden in ("approved", "cleared", "signed-off", "production-ready"):
            self.assertNotIn(forbidden, json.dumps(snapshot, ensure_ascii=False).casefold())

    def test_dashboard_snapshot_exposes_default_and_show_all_profile_sets_from_bmw_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from sg_preflight.dashboard.main import _write_dashboard_profile_preference, build_dashboard_snapshot

            root = Path(tmp)
            bmw_root = root / "digital-3d-car-models"
            records = []
            for name in ["F70", *[f"B{index:02d}" for index in range(16)]]:
                records.append(
                    f"""
- name: {name}
  brand: BMW
  type: build
  hmi:
    interface_version: 12
""".strip()
                )
            for name in ["G50_EVO", *[f"E{index:02d}_EVO" for index in range(8)]]:
                records.append(
                    f"""
- name: {name}
  brand: BMW
  type: build
  hmi:
    interface_version: 24
""".strip()
                )
            for name in ["U25", "F66"]:
                records.append(
                    f"""
- name: {name}
  brand: MINI
  type: build
  hmi:
    interface_version: 12
""".strip()
                )
            for name in ["G58_EVO", *[f"R{index:02d}_EVO" for index in range(47)]]:
                records.append(
                    f"""
- name: {name}
  brand: BMW
  type: retarget
  target: PINT
""".strip()
                )
            write_text(bmw_root / "ci" / "scripts" / "common" / "models_build_config.yaml", "\n\n".join(records) + "\n")

            default_snapshot = build_dashboard_snapshot("", root, bmw_root=bmw_root)
            retarget_snapshot = build_dashboard_snapshot("G58", root, bmw_root=bmw_root)
            _write_dashboard_profile_preference(root, "G58")
            persisted_snapshot = build_dashboard_snapshot("", root, bmw_root=bmw_root)

        self.assertEqual(default_snapshot["profile_registry"]["status"], "available")
        self.assertEqual(default_snapshot["profile_registry"]["default_count"], 28)
        self.assertEqual(default_snapshot["profile_registry"]["total_count"], 76)
        self.assertEqual(len(default_snapshot["profile_options"]), 28)
        self.assertEqual(len(default_snapshot["profile_options_all"]), 76)
        default_ids = {option["id"] for option in default_snapshot["profile_options"]}
        all_options = {option["id"]: option for option in default_snapshot["profile_options_all"]}
        self.assertIn("MINI_U25", default_ids)
        self.assertIn("G58", all_options)
        self.assertNotIn("G58", default_ids)
        self.assertEqual(all_options["G58"]["select_label"], "BMW / idc_evo / G58 -> PINT")
        self.assertTrue(retarget_snapshot["profile_known"])
        self.assertTrue(retarget_snapshot["profile_show_all"])
        self.assertEqual(persisted_snapshot["profile_id"], "G58")
        self.assertTrue(persisted_snapshot["profile_show_all"])

    def test_dashboard_source_uses_available_vocab_for_shortcut_status(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "sg_preflight" / "dashboard" / "main.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("Shortcuts available", source)
        self.assertNotIn("Shortcuts ready", source)
        self.assertNotIn("MANUAL_REVIEW_DASHBOARD_TICKET_ID", source)
        self.assertIn("_dashboard_active_ticket_id", source)

    def test_dashboard_snapshot_uses_operator_state_profile_and_ticket_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from sg_preflight.dashboard.main import build_dashboard_snapshot

            state_root = Path(tmp) / "operator_state"
            state_root.mkdir(parents=True)
            (state_root / "dashboard_preferences.json").write_text(
                json.dumps({"theme": "clean", "profile_id": "NA8"}),
                encoding="utf-8",
            )
            (state_root / "dashboard_context.json").write_text(
                json.dumps({"active_ticket_id": "IDCEVODEV-1005738"}),
                encoding="utf-8",
            )
            snapshot = build_dashboard_snapshot("", tmp)

        self.assertEqual(snapshot["profile_id"], "NA8")
        daily_page = next(page for page in snapshot["pages"] if page["id"] == "daily-digest")
        manual_page = next(page for page in snapshot["pages"] if page["id"] == "manual-review")
        self.assertEqual(daily_page["actions"][0]["ticket_id_hint"], "IDCEVODEV-1005738")
        self.assertEqual(daily_page["actions"][0]["ticket_id_default"], "IDCEVODEV-1005738")
        self.assertEqual(daily_page["actions"][0]["ticket_id_source"], "operator_state")
        self.assertEqual(daily_page["payload"]["active_ticket_id"], "IDCEVODEV-1005738")
        self.assertEqual(manual_page["payload"]["ticket_id"], "IDCEVODEV-1005738")

    def test_dashboard_snapshot_prefers_active_ticket_file_for_daily_digest_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from sg_preflight.dashboard.main import build_dashboard_snapshot

            state_root = Path(tmp) / "operator_state"
            state_root.mkdir(parents=True)
            (state_root / "active_ticket.json").write_text(
                json.dumps({"active_ticket_id": "IDCEVODEV-1005738"}),
                encoding="utf-8",
            )
            snapshot = build_dashboard_snapshot("G70", tmp)

        daily_page = next(page for page in snapshot["pages"] if page["id"] == "daily-digest")
        action = daily_page["actions"][0]
        self.assertEqual(action["ticket_id_default"], "IDCEVODEV-1005738")
        self.assertEqual(action["ticket_id_hint"], "IDCEVODEV-1005738")
        self.assertEqual(action["ticket_id_source"], "active_ticket_file")
        self.assertEqual(daily_page["payload"]["active_ticket_id"], "IDCEVODEV-1005738")

    def test_dashboard_snapshot_is_profile_agnostic_for_phase_f_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from sg_preflight.dashboard.main import build_dashboard_snapshot

            snapshots = {
                profile_id: build_dashboard_snapshot(profile_id, tmp)
                for profile_id in ("G70", "NA8", "F70", "U10", "G65")
            }

        for profile_id, snapshot in snapshots.items():
            with self.subTest(profile_id=profile_id):
                self.assertEqual(snapshot["profile_id"], profile_id)
                self.assertTrue(snapshot["profile_known"])
                self.assertEqual(len(snapshot["pages"]), 10)

    def test_dashboard_source_wires_sgfx_icon_and_header_logo(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "sg_preflight" / "dashboard" / "main.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("runtime_asset_path", source)
        self.assertIn("sgfx_icon.png", source)
        self.assertIn('DASHBOARD_BRAND_LOGO_ASSET = "logo_sgfx.png"', source)
        self.assertIn(".sgfx-sidebar-logo { width: 200px;", source)
        self.assertIn(".sgfx-brand-logo { height: 96px;", source)
        self.assertIn(".sgfx-about-logo { width: 240px;", source)
        self.assertIn('kwargs["favicon"]', source)
        self.assertIn("/sgfx-dashboard-assets", source)

    def test_dashboard_source_removes_redundant_headers_and_enables_dark_mode(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "sg_preflight" / "dashboard" / "main.py").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("SGFX: Project Quality-Hero", source)
        self.assertNotIn("Welcome to SGFX QA Preflight", source)
        self.assertNotIn('ui.label("Mode: Clean")', source)
        self.assertNotIn('ui.label("Mode: Grafiks")', source)
        self.assertNotIn("DASHBOARD_HEADER", source)
        self.assertIn('DASHBOARD_TITLE = "Seriengrafik: Project Quality-Hero"', source)
        self.assertIn("ui.dark_mode().enable()", source)
        self.assertIn("--sgfx-bg:", source)
        self.assertIn("ABOUT_CONTENT", source)
        self.assertIn("_render_about_panel", source)
        self.assertIn('elif active_page_id == "about"', source)
        self.assertIn("Confluence anchors", source)
        self.assertIn('"data_handling_disclosure"', source)
        self.assertIn("deterministic local filesystem probe", source)
        self.assertIn("disclosure_lines = tuple(payload.get(\"data_handling_disclosure\"", source)
        self.assertIn("sgfx-sidebar-logo", source)
        self.assertIn("sgfx-about-logo", source)
        self.assertIn("debug_icon.png", source)
        self.assertIn("sgfx-hotkey-popup", source)
        self.assertIn("sgfx-thinking-tooltip", source)

    def test_dashboard_source_accepts_profile_query_for_walkthrough_harness(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "sg_preflight" / "dashboard" / "main.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('def _index(profile: str = "")', source)
        self.assertIn('query_profile = str(profile or "").strip()', source)
        self.assertIn("defer_daily_digest=True", source)
        self.assertIn("defer_team_digest_board=True", source)
        self.assertIn('page_id in {"daily-digest", "team-digest-board"}', source)

    def test_dashboard_tooltips_are_verbose_opt_in(self) -> None:
        from sg_preflight.dashboard import main

        class FakeTooltip:
            def __init__(self, text: str) -> None:
                self.text = text
                self.props_value = ""
                self.classes_value = ""

            def props(self, value: str) -> "FakeTooltip":
                self.props_value = value
                return self

            def classes(self, value: str) -> "FakeTooltip":
                self.classes_value = value
                return self

        class FakeUi:
            def __init__(self) -> None:
                self.tooltips: list[FakeTooltip] = []

            def tooltip(self, text: str) -> FakeTooltip:
                tooltip = FakeTooltip(text)
                self.tooltips.append(tooltip)
                return tooltip

        class FakeElement:
            def __init__(self) -> None:
                self.enter_count = 0

            def __enter__(self) -> "FakeElement":
                self.enter_count += 1
                return self

            def __exit__(self, *_args: object) -> None:
                return None

        with mock.patch.dict(os.environ, {"SGFX_DASHBOARD_VERBOSE_TOOLTIPS": ""}, clear=False):
            ui = FakeUi()
            element = FakeElement()
            self.assertIs(main._attach_tooltip(ui, element, "Hidden by default"), element)
            self.assertEqual(ui.tooltips, [])
            self.assertEqual(element.enter_count, 0)

        with mock.patch.dict(os.environ, {"SGFX_DASHBOARD_VERBOSE_TOOLTIPS": "1"}, clear=False):
            ui = FakeUi()
            element = FakeElement()
            self.assertIs(main._attach_tooltip(ui, element, "Visible in verbose mode"), element)
            self.assertEqual(element.enter_count, 1)
            self.assertEqual(ui.tooltips[0].text, "Visible in verbose mode")
            self.assertEqual(ui.tooltips[0].props_value, "delay=900")
            self.assertEqual(ui.tooltips[0].classes_value, "sgfx-thinking-tooltip")

    def test_dashboard_source_routes_delivery_page_to_live_generation_renderer(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "sg_preflight" / "dashboard" / "main.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('active_page_id == "delivery-checklist"', source)
        self.assertIn("on_setup_completed=_refresh_snapshot", source)
        self.assertIn("Live output", source)
        self.assertIn("File activity", source)
        self.assertIn("typical 1-10 min", source)

    def test_dashboard_source_opens_screenshot_viewer_inline_for_operator_path(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "sg_preflight" / "dashboard" / "main.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("data-sgfx-inline-viewer", source)
        self.assertIn("sgfx-viewer-dialog-card", source)
        self.assertIn("sgfx-viewer-iframe", source)
        self.assertIn("_open_inline_viewer", source)
        self.assertIn("viewer_dialog.open()", source)
        self.assertIn("sanitize=False", source)
        self.assertNotIn("window.open", source)

    def test_dashboard_source_exposes_quality_report_jira_attach_flow(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "sg_preflight" / "dashboard" / "main.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("Build Quality-Hero report", source)
        self.assertIn("Attach to Jira ticket", source)
        self.assertIn("Ticket picker", source)
        self.assertIn("Post to Jira?", source)
        self.assertIn("--attach-ticket", source)
        self.assertIn("--auto-confirm", source)

    def test_dashboard_source_exposes_full_qa_wizard_actions(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "sg_preflight" / "dashboard" / "main.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("sgfx-wizard-card", source)
        self.assertIn("sgfx-wizard-overlay", source)
        self.assertIn("Confirm local tool action", source)
        self.assertIn("Skip current", source)
        self.assertIn("Full QA Pass summary", source)
        self.assertIn("Trusted tool mode is active for local tool actions only.", source)
        self.assertIn("record_operator_handoff", source)
        self.assertIn("start_delivery_workbook_generation", source)
        self.assertIn("start_screenshot_capture", source)
        self.assertIn("Cancel running action", source)
        self.assertIn("Manual-review state still has", source)
        self.assertIn("_full_qa_display_status", source)
        self.assertIn('str(step.get("id", "")) == "screenshot-test-state"', source)
        self.assertIn("expected > 0 and actual == 0 and diff == 0", source)
        self.assertIn('action=f"skip:{step_id}", outcome="ok"', source)
        self.assertNotIn('outcome="skipped"', source)
        self.assertNotIn("trusted_auto_queue", source)

    def test_dashboard_snapshot_exposes_first_run_setup_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from sg_preflight.dashboard.main import build_dashboard_snapshot

            fake_setup = {
                "status": "incomplete",
                "summary": "1/4 dependency item(s) available; setup actions require operator confirmation.",
                "first_run": True,
                "items": [
                    {
                        "key": "raco_headless",
                        "label": "RaCoHeadless",
                        "status": "missing",
                        "detail": "RaCoHeadless.exe is not configured.",
                        "path": "",
                    }
                ],
                "actions": [
                    {
                        "id": "setup-raco-from-shared-tools",
                        "label": "Set up RaCo",
                        "requires_confirmation": True,
                        "effects": [r"Copies or extracts files under C:\dev\software."],
                    }
                ],
                "counts": {"available": 1, "missing": 3, "incomplete": 0},
            }
            with mock.patch("sg_preflight.dashboard.main.build_dependency_onboarding_status", return_value=fake_setup):
                snapshot = build_dashboard_snapshot("G70", tmp)

        self.assertTrue(snapshot["welcome"]["show"])
        self.assertEqual(snapshot["welcome"]["setup_page_id"], "delivery-checklist")
        delivery = next(page for page in snapshot["pages"] if page["id"] == "delivery-checklist")
        self.assertEqual(delivery["setup_status"], fake_setup)
        self.assertEqual(delivery["setup_status"]["actions"][0]["label"], "Set up RaCo")

    def test_dashboard_snapshot_can_defer_team_digest_board_for_fast_profile_switch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from sg_preflight.dashboard.main import build_dashboard_snapshot

            with mock.patch("sg_preflight.dashboard.main.build_team_daily_digest_board") as team_board:
                snapshot = build_dashboard_snapshot("G70", tmp, defer_team_digest_board=True)

        team_board.assert_not_called()
        self.assertEqual(len(snapshot["pages"]), 10)
        team_page = next(page for page in snapshot["pages"] if page["id"] == "team-digest-board")
        self.assertTrue(team_page["deferred"])
        self.assertEqual(team_page["status"], "not_run")
        self.assertIn("refreshes when opened", team_page["summary"])

    def test_dashboard_snapshot_can_defer_daily_digest_for_fast_profile_switch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from sg_preflight.dashboard.main import build_dashboard_snapshot

            with mock.patch("sg_preflight.dashboard.main.build_latest_daily_digest") as daily_digest:
                snapshot = build_dashboard_snapshot("G70", tmp, defer_daily_digest=True)

        daily_digest.assert_not_called()
        self.assertEqual(len(snapshot["pages"]), 10)
        daily_page = next(page for page in snapshot["pages"] if page["id"] == "daily-digest")
        self.assertTrue(daily_page["deferred"])
        self.assertEqual(daily_page["status"], "not_run")
        self.assertIn("refreshes when opened", daily_page["summary"])
        self.assertEqual(daily_page["actions"][0]["id"], "build-review-package")

    def test_dashboard_snapshot_suppresses_welcome_setup_action_when_none_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from sg_preflight.dashboard.main import build_dashboard_snapshot

            fake_setup = {
                "status": "available",
                "summary": "4/4 dependency item(s) available; setup actions require operator confirmation.",
                "first_run": True,
                "items": [],
                "actions": [],
                "counts": {"available": 4, "missing": 0, "incomplete": 0},
            }
            with mock.patch("sg_preflight.dashboard.main.build_dependency_onboarding_status", return_value=fake_setup):
                snapshot = build_dashboard_snapshot("G70", tmp)

        self.assertTrue(snapshot["welcome"]["show"])
        self.assertEqual(snapshot["welcome"]["setup_action_count"], 0)
        self.assertEqual(
            snapshot["welcome"]["setup_complete_note"],
            "Setup complete — go to evidence pages to start your QA Hero workflow.",
        )

    def test_dashboard_source_renders_dependency_setup_consent_panel(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "sg_preflight" / "dashboard" / "main.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("Dependency setup", source)
        self.assertIn("System changes", source)
        self.assertIn("Run setup", source)
        self.assertIn("start_dependency_setup_action", source)
        self.assertIn("poll_dependency_setup_action", source)
        self.assertIn("Live setup output", source)
        self.assertIn("Source path", source)
        self.assertIn("Target path", source)
        self.assertIn("update:model-value", source)
        self.assertIn("leave optional installer sources blank", source)
        self.assertIn("on_setup_completed: Callable[[], None] | None = None", source)
        self.assertIn("Re-reading dependency status.", source)
        self.assertIn("on_setup_completed()", source)

    def test_dashboard_source_renders_build_review_package_progress_panel(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "sg_preflight" / "dashboard" / "main.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("start_dashboard_review_package_build", source)
        self.assertIn("poll_dashboard_review_package_build", source)
        self.assertIn("cancel_dashboard_review_package_build", source)
        self.assertIn("Live package output", source)
        self.assertIn("Build review package running.", source)
        self.assertIn("typical 1-5 min", source)

    def test_dashboard_source_uses_parentless_poll_timer_for_long_running_jobs(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "sg_preflight" / "dashboard" / "main.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("from nicegui.timer import Timer", source)
        self.assertIn("_start_background_poll_timer", source)
        self.assertIn("_cancel_background_poll_timer", source)
        self.assertIn("_parent_slot_deleted", source)
        self.assertIn("except RuntimeError as exc", source)
        self.assertNotIn("ui.timer(", source)
        self.assertNotIn("poll_timer.active", source)

    def test_non_native_dashboard_defaults_to_free_local_port(self) -> None:
        from sg_preflight.dashboard.main import _dashboard_run_port

        with mock.patch("sg_preflight.dashboard.main._find_open_dashboard_port", return_value=8123) as finder:
            self.assertEqual(_dashboard_run_port(native=False, port=0), 8123)

        finder.assert_called_once_with()
        self.assertEqual(_dashboard_run_port(native=True, port=0), 0)
        self.assertEqual(_dashboard_run_port(native=False, port=8877), 8877)

    def test_non_native_dashboard_does_not_auto_open_browser(self) -> None:
        from sg_preflight.dashboard.main import run_dashboard

        ui = mock.Mock()
        app = object()
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch("sg_preflight.dashboard.dependency.require_nicegui", return_value=(ui, app)):
                with mock.patch("sg_preflight.dashboard.main._render_dashboard"):
                    result = run_dashboard(workspace=Path(temp_dir), native=False, port=8124)

        self.assertEqual(result, 0)
        ui.run.assert_called_once()
        self.assertFalse(ui.run.call_args.kwargs["native"])
        self.assertFalse(ui.run.call_args.kwargs["show"])

    def test_native_dashboard_attempts_native_window_when_webview2_is_available(self) -> None:
        from sg_preflight.dashboard.main import run_dashboard

        ui = mock.Mock()
        app = object()
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch("sg_preflight.dashboard.dependency.require_nicegui", return_value=(ui, app)):
                with mock.patch("sg_preflight.dashboard.main._render_dashboard"):
                    with mock.patch("sg_preflight.dashboard.main.webview2_runtime_available", return_value=True):
                        with mock.patch("sg_preflight.dashboard.main.monotonic", side_effect=[0.0, 10.0]):
                            result = run_dashboard(workspace=Path(temp_dir), native=True, port=0)

        self.assertEqual(result, 0)
        ui.run.assert_called_once()
        self.assertTrue(ui.run.call_args.kwargs["native"])
        self.assertTrue(ui.run.call_args.kwargs["show"])

    def test_native_dashboard_falls_back_to_browser_when_native_returns_immediately(self) -> None:
        from sg_preflight.dashboard.main import run_dashboard

        ui = mock.Mock()
        app = object()
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch("sg_preflight.dashboard.dependency.require_nicegui", return_value=(ui, app)):
                with mock.patch("sg_preflight.dashboard.main._render_dashboard"):
                    with mock.patch("sg_preflight.dashboard.main.webview2_runtime_available", return_value=True):
                        with mock.patch("sg_preflight.dashboard.main._find_open_dashboard_port", return_value=8127):
                            with mock.patch("sg_preflight.dashboard.main._launch_browser_fallback_process", return_value=0) as fallback:
                                with mock.patch("sg_preflight.dashboard.main.monotonic", side_effect=[0.0, 0.2]):
                                    result = run_dashboard(workspace=Path(temp_dir), native=True, port=0)

        self.assertEqual(result, 0)
        ui.run.assert_called_once()
        self.assertTrue(ui.run.call_args.kwargs["native"])
        fallback.assert_called_once()
        self.assertEqual(fallback.call_args.kwargs["fallback_port"], 8127)

    def test_frozen_native_dashboard_suppresses_browser_fallback_without_native_attempt(self) -> None:
        import sg_preflight.dashboard.main as dashboard_main
        from sg_preflight.dashboard.main import run_dashboard

        ui = mock.Mock()
        app = object()
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch("sg_preflight.dashboard.dependency.require_nicegui", return_value=(ui, app)):
                with mock.patch("sg_preflight.dashboard.main._render_dashboard"):
                    with mock.patch.object(dashboard_main.sys, "frozen", True, create=True):
                        with mock.patch("sg_preflight.dashboard.main._find_open_dashboard_port", return_value=8128):
                            with mock.patch("sg_preflight.dashboard.main._launch_browser_fallback_process", return_value=0) as fallback:
                                with self.assertRaisesRegex(RuntimeError, "embedded desktop shell"):
                                    run_dashboard(workspace=Path(temp_dir), native=True, port=0)

        ui.run.assert_not_called()
        fallback.assert_not_called()

    def test_native_dashboard_falls_back_to_browser_when_webview2_is_missing(self) -> None:
        from sg_preflight.dashboard.main import run_dashboard

        ui = mock.Mock()
        app = object()
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch("sg_preflight.dashboard.dependency.require_nicegui", return_value=(ui, app)):
                with mock.patch("sg_preflight.dashboard.main._render_dashboard"):
                    with mock.patch("sg_preflight.dashboard.main.webview2_runtime_available", return_value=False):
                        with mock.patch("sg_preflight.dashboard.main._find_open_dashboard_port", return_value=8125):
                            result = run_dashboard(workspace=Path(temp_dir), native=True, port=0)

        self.assertEqual(result, 0)
        ui.run.assert_called_once()
        self.assertFalse(ui.run.call_args.kwargs["native"])
        self.assertTrue(ui.run.call_args.kwargs["show"])
        self.assertEqual(ui.run.call_args.kwargs["port"], 8125)

    def test_native_dashboard_falls_back_to_browser_after_native_error(self) -> None:
        from sg_preflight.dashboard.main import run_dashboard

        ui = mock.Mock()
        ui.run.side_effect = [RuntimeError("native failed"), None]
        app = object()
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch("sg_preflight.dashboard.dependency.require_nicegui", return_value=(ui, app)):
                with mock.patch("sg_preflight.dashboard.main._render_dashboard"):
                    with mock.patch("sg_preflight.dashboard.main.webview2_runtime_available", return_value=True):
                        with mock.patch("sg_preflight.dashboard.main._find_open_dashboard_port", return_value=8126):
                            with mock.patch("sg_preflight.dashboard.main._launch_browser_fallback_process", return_value=0) as fallback:
                                result = run_dashboard(workspace=Path(temp_dir), native=True, port=0)

        self.assertEqual(result, 0)
        ui.run.assert_called_once()
        self.assertTrue(ui.run.call_args.kwargs["native"])
        fallback.assert_called_once()
        self.assertEqual(fallback.call_args.kwargs["fallback_port"], 8126)

    def test_dashboard_snapshot_marks_unknown_profile_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from sg_preflight.dashboard.main import build_dashboard_snapshot

            snapshot = build_dashboard_snapshot("XYZ", tmp)

        self.assertEqual(snapshot["profile_id"], "XYZ")
        self.assertFalse(snapshot["profile_known"])
        self.assertIn("not in the current profile registry", snapshot["profile_warning"])

    def test_dashboard_stays_clean_when_old_grafiks_preference_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from sg_preflight.dashboard.main import (
                build_dashboard_snapshot,
                save_dashboard_preference,
            )

            save_dashboard_preference(tmp, "grafiks")
            persisted = build_dashboard_snapshot("", tmp)
            forced = build_dashboard_snapshot("", tmp, ui_mode="clean")

        self.assertEqual(persisted["theme"], "clean")
        self.assertEqual(forced["theme"], "clean")

    def test_dashboard_snapshot_exposes_shortcut_actions_for_keyboard_wiring(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from sg_preflight.dashboard.main import build_dashboard_snapshot

            snapshot = build_dashboard_snapshot("", tmp)

        actions = {item["key"]: item["message"] for item in snapshot["shortcut_actions"]}
        self.assertIn("F1", actions)
        self.assertIn("F2", actions)
        self.assertIn("F5", actions)
        self.assertIn("F12", actions)
        self.assertIn("Esc", actions)
        self.assertIn("Profile", actions["F2"])

    def test_dashboard_snapshot_abbreviates_visible_workspace_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from sg_preflight.dashboard.main import build_dashboard_snapshot

            snapshot = build_dashboard_snapshot("G70", tmp)

        delivery = next(page for page in snapshot["pages"] if page["id"] == "delivery-checklist")
        self.assertEqual(delivery["status"], "unavailable")
        self.assertNotIn(str(Path(tmp).resolve()), delivery["summary"])
        self.assertIn(Path(tmp).name, delivery["summary"])

    def test_delivery_unavailable_page_exposes_generation_action_with_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from sg_preflight.dashboard.main import build_dashboard_snapshot
            from sg_preflight.delivery_workbook_generation import GENERATE_WORKBOOK_ACTION_ID

            fake_preflight = {
                "can_run": False,
                "checks": [{"key": "digital_3d_car_repo", "status": "missing"}],
                "confirmation_message": "This will run the BMW pipeline for G70.",
            }
            fake_trigger = {
                "trigger_status": "incomplete",
                "summary": "Delivery workbook generation is not available yet.",
                "preflight": fake_preflight,
                "manual_review_required": True,
                "is_approval": False,
            }
            with mock.patch(
                "sg_preflight.dashboard.main.build_delivery_workbook_trigger",
                return_value=fake_trigger,
            ):
                snapshot = build_dashboard_snapshot("G70", tmp)

        delivery = next(page for page in snapshot["pages"] if page["id"] == "delivery-checklist")
        self.assertEqual(delivery["status"], "unavailable")
        self.assertIn("No size-analysis workbook yet", delivery["empty_state_note"])
        self.assertEqual(delivery["workbook_trigger"], fake_trigger)
        self.assertEqual(len(delivery["actions"]), 1)
        action = delivery["actions"][0]
        self.assertEqual(action["id"], GENERATE_WORKBOOK_ACTION_ID)
        self.assertTrue(action["requires_confirmation"])
        self.assertTrue(action["disabled"])
        self.assertFalse(action["preflight"]["can_run"])
        self.assertIn("This will run the BMW pipeline for G70", action["confirmation_message"])
        checks = {item["key"]: item for item in action["preflight"]["checks"]}
        self.assertIn("digital_3d_car_repo", checks)

    def test_screenshot_page_exposes_capture_action_with_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from sg_preflight.dashboard.main import build_dashboard_snapshot
            from sg_preflight.screenshot_capture import SCREENSHOT_CAPTURE_ACTION_ID

            fake_preflight = {
                "can_run": False,
                "checks": [{"key": "bmw_screenshot_script", "status": "missing"}],
                "confirmation_message": "This will run BMW pipeline screenshot capture for G70.",
            }
            with mock.patch(
                "sg_preflight.dashboard.main.check_screenshot_capture_environment",
                return_value=fake_preflight,
            ):
                snapshot = build_dashboard_snapshot("G70", tmp)

        screenshot_page = next(page for page in snapshot["pages"] if page["id"] == "screenshot-test-state")
        self.assertIn("No captured screenshots yet", screenshot_page["empty_state_note"])
        self.assertEqual(len(screenshot_page["actions"]), 1)
        action = screenshot_page["actions"][0]
        self.assertEqual(action["id"], SCREENSHOT_CAPTURE_ACTION_ID)
        self.assertTrue(action["requires_confirmation"])
        self.assertTrue(action["disabled"])
        self.assertFalse(action["preflight"]["can_run"])
        self.assertIn("screenshot capture for G70", action["confirmation_message"])
        checks = {item["key"]: item for item in action["preflight"]["checks"]}
        self.assertIn("bmw_screenshot_script", checks)

    def test_dashboard_snapshot_adds_empty_state_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from sg_preflight.dashboard.main import build_dashboard_snapshot

            with mock.patch(
                "sg_preflight.dashboard.main.read_bmw_screenshot_state",
                return_value={
                    "status": "available",
                    "data_available": True,
                    "summary": "0 expected / 0 actual / 0 diff screenshot file(s)",
                    "actual_count": 0,
                    "diff_count": 0,
                },
            ):
                snapshot = build_dashboard_snapshot("G70", tmp)

        pages = {page["id"]: page for page in snapshot["pages"]}
        self.assertIn("No captured screenshots yet", pages["screenshot-test-state"]["empty_state_note"])
        self.assertIn("No review package on this workspace yet", pages["daily-digest"]["empty_state_note"])
        self.assertIn("Manual review session not started", pages["manual-review"]["empty_state_note"])
        self.assertIn("review_templates", pages["manual-review"]["payload"])
        self.assertIn("evidence_checklist", pages["manual-review"]["payload"])
        self.assertEqual(pages["manual-review"]["payload"]["default_family_id"], "bmw_idcevo")

    def test_delivery_available_page_does_not_offer_generation_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from sg_preflight.dashboard.main import build_dashboard_snapshot

            with mock.patch(
                "sg_preflight.dashboard.main.read_delivery_checklist",
                return_value={
                    "status": "available",
                    "data_available": True,
                    "summary": "Delivery checklist G70: workbook found.",
                    "checks": [],
                    "is_approval": False,
                },
            ):
                snapshot = build_dashboard_snapshot("G70", tmp)

        delivery = next(page for page in snapshot["pages"] if page["id"] == "delivery-checklist")
        self.assertEqual(delivery["status"], "available")
        self.assertEqual(delivery.get("actions", []), [])

    def test_manual_review_state_save_is_operator_local_and_rejects_approval_words(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from sg_preflight.dashboard.main import save_manual_review_state

            payload = save_manual_review_state(
                profile_id="G65",
                workspace=tmp,
                step_slug="blender_visual_check",
                status="not_run",
                note="Not started yet.",
            )
            self.assertEqual(payload["steps"]["blender_visual_check"]["status"], "not_run")

            payload = save_manual_review_state(
                profile_id="G65",
                workspace=tmp,
                step_slug="blender_visual_check",
                status="recorded",
                note="Checked Blender and RaCo side by side.",
            )
            path = Path(tmp) / "operator_state" / "manual_review_G65.json"

            self.assertTrue(path.is_file())
            self.assertEqual(payload["profile_id"], "G65")
            self.assertEqual(payload["steps"]["blender_visual_check"]["status"], "recorded")
            self.assertEqual(payload["steps"]["blender_visual_check"]["recorded_by_tool"], False)

            with self.assertRaises(ValueError):
                save_manual_review_state(
                    profile_id="G65",
                    workspace=tmp,
                    step_slug="blender_visual_check",
                    status="approved",
                    note="bad",
                )

    def test_manual_review_dashboard_recording_persists_operator_verdict_to_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from sg_preflight.dashboard.main import (
                build_dashboard_snapshot,
                record_manual_review_dashboard_step,
            )

            updated = record_manual_review_dashboard_step(
                profile_id="G65",
                workspace=tmp,
                step_slug="blender_visual_check",
                verdict="passed",
                note="Operator checked logos and lights.",
            )
            snapshot = build_dashboard_snapshot("G65", tmp)

        self.assertEqual(updated["status"], "recorded")
        step = next(item for item in updated["steps"] if item["slug"] == "blender_visual_check")
        self.assertEqual(step["verdict"], "passed")
        self.assertEqual(step["note"], "Operator checked logos and lights.")
        self.assertTrue(step["recorded_at_utc"])
        self.assertFalse(step["recorded_by_tool"])

        manual_page = next(page for page in snapshot["pages"] if page["id"] == "manual-review")
        self.assertEqual(manual_page["status"], "recorded")
        self.assertIn("1/7 manual-review steps recorded locally.", manual_page["summary"])
        item = next(item for item in manual_page["items"] if item["label"] == "Blender Visual Check")
        self.assertEqual(item["status"], "recorded")
        self.assertIn("passed", item["detail"])
        recorded_step = next(item for item in manual_page["payload"]["steps"] if item["slug"] == "blender_visual_check")
        self.assertEqual(recorded_step["verdict"], "passed")
        self.assertFalse(recorded_step["recorded_by_tool"])

    def test_manual_review_page_surfaces_evidence_without_preselecting_verdicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from sg_preflight.dashboard.main import build_dashboard_snapshot

            root = Path(tmp)
            project = root / "repositories" / "trunk" / "Cars_IDCevo" / "BMW" / "G70"
            write_text(project / "_WorkFiles" / "scene.blend", "blend fixture\n")
            write_text(
                root
                / "operator_state"
                / "manual_review_suggestions"
                / "g70"
                / "functionality_test_raco.passed",
                "operator marker\n",
            )

            snapshot = build_dashboard_snapshot("G70", root)

        manual_page = next(page for page in snapshot["pages"] if page["id"] == "manual-review")
        blender_step = next(item for item in manual_page["payload"]["steps"] if item["slug"] == "blender_visual_check")
        self.assertEqual(blender_step["verdict"], "not_run")
        self.assertEqual(blender_step["suggested_verdict"], "")
        self.assertEqual(blender_step["evidence_status"], "available")
        self.assertEqual(blender_step["auto_check_status"], "available")
        self.assertEqual(blender_step["auto_check_kind"], "file_presence")
        self.assertTrue(blender_step["manual_review_required"])
        self.assertFalse(blender_step["suggestion_is_approval"])
        item = next(item for item in manual_page["items"] if item["label"] == "Blender Visual Check")
        self.assertIn("Auto-check available", item["detail"])
        self.assertIn("Manual review remains required", item["detail"])
        review_assist = manual_page["payload"]["review_assist"]
        self.assertEqual(review_assist["assist_status"], "available")
        self.assertTrue(review_assist["operator_confirmation_required"])
        self.assertFalse(review_assist["records_operator_verdict"])
        assist_steps = {item["slug"]: item for item in review_assist["steps"]}
        self.assertEqual(assist_steps["functionality_test_raco"]["suggested_verdict"], "passed")
        self.assertEqual(assist_steps["blender_visual_check"]["suggested_verdict"], "incomplete")

    def test_manual_review_dashboard_recording_stores_suggested_and_operator_verdicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from sg_preflight.dashboard.main import record_manual_review_dashboard_step

            updated = record_manual_review_dashboard_step(
                profile_id="G70",
                workspace=tmp,
                step_slug="blender_visual_check",
                verdict="incomplete",
                suggested_verdict="passed",
                note="Operator saw missing trimline coverage.",
            )

        step = next(item for item in updated["steps"] if item["slug"] == "blender_visual_check")
        self.assertEqual(step["verdict"], "incomplete")
        self.assertEqual(step["operator_verdict"], "incomplete")
        self.assertEqual(step["suggested_verdict"], "passed")
        self.assertFalse(step["recorded_by_tool"])


class DashboardDualModeLaunchTests(unittest.TestCase):
    def test_dashboard_grafiks_mode_dispatches_to_pyside_shell(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from sg_preflight.cli import main

            with mock.patch("sg_preflight.dashboard.main.run_dashboard", return_value=11) as clean_runner:
                with mock.patch("sg_preflight.desktop.app.run_desktop_app", return_value=9) as grafiks_runner:
                    result = main(
                        [
                            "dashboard",
                            "run",
                            "--profile",
                            "NA8",
                            "--workspace",
                            tmp,
                            "--ui-mode",
                            "grafiks",
                            "--no-native",
                        ]
                    )

        self.assertEqual(result, 9)
        clean_runner.assert_not_called()
        grafiks_runner.assert_called_once_with(workspace=Path(tmp), initial_profile_id="NA8", initial_mode="grafiks")

    def test_frozen_clean_dashboard_dispatches_to_desktop_shell(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            import sg_preflight.cli as cli

            with mock.patch.object(cli.sys, "frozen", True, create=True):
                with mock.patch("sg_preflight.dashboard.main.run_dashboard", return_value=11) as clean_runner:
                    with mock.patch("sg_preflight.desktop.app.run_desktop_app", return_value=9) as desktop_runner:
                        result = cli.main(
                            [
                                "dashboard",
                                "run",
                                "--profile",
                                "NA8",
                                "--workspace",
                                tmp,
                                "--ui-mode",
                                "clean",
                            ]
                        )

        self.assertEqual(result, 9)
        clean_runner.assert_not_called()
        desktop_runner.assert_called_once_with(workspace=Path(tmp), initial_profile_id="NA8", initial_mode="clean")

    def test_frozen_clean_dashboard_no_native_keeps_server_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            import sg_preflight.cli as cli

            with mock.patch.object(cli.sys, "frozen", True, create=True):
                with mock.patch("sg_preflight.dashboard.main.run_dashboard", return_value=11) as clean_runner:
                    with mock.patch("sg_preflight.desktop.app.run_desktop_app", return_value=9) as desktop_runner:
                        result = cli.main(
                            [
                                "dashboard",
                                "run",
                                "--profile",
                                "NA8",
                                "--workspace",
                                tmp,
                                "--ui-mode",
                                "clean",
                                "--no-native",
                            ]
                        )

        self.assertEqual(result, 11)
        desktop_runner.assert_not_called()
        clean_runner.assert_called_once()

    def test_desktop_alias_accepts_workspace_and_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from sg_preflight.cli import main

            with mock.patch("sg_preflight.desktop.app.run_desktop_app", return_value=5) as runner:
                result = main(["desktop", "--profile", "G70", "--workspace", tmp])

        self.assertEqual(result, 5)
        runner.assert_called_once_with(workspace=Path(tmp), initial_profile_id="G70", initial_mode="clean")


# Phase B-3 + B-4 — Daily Digest action + partial-artifact surfacing + Screenshot Test State ownership note.
# Appended below the earlier Phase B classes to avoid line-range overlaps with their additions.


class TestDailyDigestPage(unittest.TestCase):
    def test_daily_digest_page_exposes_build_review_package_action(self) -> None:
        from sg_preflight.dashboard.main import (
            DAILY_DIGEST_BUILD_PACKAGE_ACTION_ID,
            DAILY_DIGEST_BUILD_PACKAGE_ACTION_LABEL,
            DAILY_DIGEST_TICKET_ID_PLACEHOLDER,
            _daily_digest_page,
        )

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            with mock.patch(
                "sg_preflight.dashboard.main.build_latest_daily_digest",
                return_value={"status": "no_review_package", "data_available": False, "sections": {}},
            ):
                page = _daily_digest_page(workspace, "G65")

        actions = page.get("actions", [])
        self.assertEqual(len(actions), 2)
        action = next(item for item in actions if item["id"] == DAILY_DIGEST_BUILD_PACKAGE_ACTION_ID)
        self.assertEqual(action["id"], DAILY_DIGEST_BUILD_PACKAGE_ACTION_ID)
        self.assertEqual(action["label"], DAILY_DIGEST_BUILD_PACKAGE_ACTION_LABEL)
        self.assertTrue(action["requires_ticket_id"])
        self.assertEqual(action["ticket_id_hint"], DAILY_DIGEST_TICKET_ID_PLACEHOLDER)
        report_action = next(item for item in actions if item["id"] == "build-quality-hero-report")
        self.assertEqual(report_action["label"], "Build Quality-Hero report")
        self.assertTrue(report_action["requires_ticket_id"])

    def test_daily_digest_page_action_carries_active_ticket_id_hint(self) -> None:
        from sg_preflight.dashboard.main import _daily_digest_page

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            with mock.patch(
                "sg_preflight.dashboard.main.build_latest_daily_digest",
                return_value={"status": "no_review_package", "data_available": False, "sections": {}},
            ):
                page = _daily_digest_page(workspace, "G65", active_ticket_id="IDCEVODEV-1005738")

        for action in page["actions"]:
            self.assertEqual(action["ticket_id_hint"], "IDCEVODEV-1005738")
            self.assertEqual(action["ticket_id_default"], "IDCEVODEV-1005738")
        self.assertEqual(page["payload"]["active_ticket_id"], "IDCEVODEV-1005738")

    def test_daily_digest_ticket_context_prefers_git_branch_before_activity_log(self) -> None:
        from sg_preflight.dashboard.main import _daily_digest_ticket_context
        from sg_preflight.activity_log import append_activity_entry

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            append_activity_entry(
                workspace,
                verb="ran",
                surface="daily-digest",
                profile="G70",
                outcome="ok",
                note="Build review package for IDCEVODEV-1005738",
            )
            with mock.patch(
                "sg_preflight.dashboard.main._dashboard_ticket_from_git_branch",
                return_value="IDCEVODEV-2000001",
            ):
                context = _daily_digest_ticket_context(workspace)

        self.assertEqual(context["active_ticket_id"], "IDCEVODEV-2000001")
        self.assertEqual(context["ticket_id_source"], "git_branch")
        self.assertIn("IDCEVODEV-1005738", context["recent_ticket_ids"])

    def test_daily_digest_ticket_context_uses_last_activity_ticket_when_no_state_or_branch(self) -> None:
        from sg_preflight.dashboard.main import _daily_digest_ticket_context
        from sg_preflight.activity_log import append_activity_entry

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            append_activity_entry(
                workspace,
                verb="ran",
                surface="daily-digest",
                profile="G70",
                outcome="ok",
                note="Build review package for IDCEVODEV-1005738",
            )
            with mock.patch("sg_preflight.dashboard.main._dashboard_ticket_from_git_branch", return_value=""):
                context = _daily_digest_ticket_context(workspace)

        self.assertEqual(context["active_ticket_id"], "IDCEVODEV-1005738")
        self.assertEqual(context["ticket_id_source"], "activity_log")

    def test_daily_digest_page_flips_to_incomplete_when_partial_sections_have_data(self) -> None:
        from sg_preflight.dashboard.main import _daily_digest_page

        digest = {
            "status": "no_review_package",
            "data_available": False,
            "sections": {
                "what_landed_today": {"heading": "What landed today", "count": 2, "empty_message": ""},
                "workflow_status": {"heading": "Workflow status", "count": 6, "empty_message": ""},
                "evidence_prepared": {"heading": "Evidence prepared", "count": 0, "empty_message": "No evidence."},
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            with mock.patch(
                "sg_preflight.dashboard.main.build_latest_daily_digest",
                return_value=digest,
            ):
                page = _daily_digest_page(workspace, "G65")

        self.assertEqual(page["status"], "incomplete")
        self.assertTrue(page["data_available"])
        items_by_label = {item["label"]: item for item in page["items"]}
        self.assertEqual(items_by_label["What landed today"]["status"], "2")
        self.assertEqual(items_by_label["Workflow status"]["status"], "6")
        self.assertEqual(items_by_label["Evidence prepared"]["status"], "0")

    def test_daily_digest_page_keeps_missing_when_no_review_package_and_no_partial_signal(self) -> None:
        from sg_preflight.dashboard.main import _daily_digest_page

        digest = {
            "status": "no_review_package",
            "data_available": False,
            "sections": {
                "what_landed_today": {"heading": "What landed today", "count": 0, "empty_message": "No commits."},
                "workflow_status": {"heading": "Workflow status", "count": 0, "empty_message": "No items."},
                "evidence_prepared": {"heading": "Evidence prepared", "count": 0, "empty_message": "No evidence."},
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            with mock.patch(
                "sg_preflight.dashboard.main.build_latest_daily_digest",
                return_value=digest,
            ):
                page = _daily_digest_page(workspace, "G65")

        self.assertEqual(page["status"], "missing")
        self.assertFalse(page["data_available"])


class TestScreenshotTestStateOwnershipNote(unittest.TestCase):
    def test_screenshot_test_state_page_renders_ownership_note(self) -> None:
        from sg_preflight.dashboard.main import (
            SCREENSHOT_TEST_STATE_OWNERSHIP_NOTE,
            build_dashboard_snapshot,
        )

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            snapshot = build_dashboard_snapshot("G65", workspace)

        screenshot_page = next(
            page for page in snapshot["pages"] if page["id"] == "screenshot-test-state"
        )
        self.assertEqual(screenshot_page["ownership_note"], SCREENSHOT_TEST_STATE_OWNERSHIP_NOTE)
        self.assertIn("lane-correct BMW Git pipeline script", screenshot_page["ownership_note"])
        self.assertIn("SGFX reads the output", screenshot_page["ownership_note"])
        self.assertTrue(screenshot_page["confluence_anchors"])
        self.assertTrue(screenshot_page["actions"][0]["confluence_anchor"])

    def test_other_pages_have_empty_ownership_note(self) -> None:
        from sg_preflight.dashboard.main import build_dashboard_snapshot

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            snapshot = build_dashboard_snapshot("G65", workspace)

        delivery_page = next(
            page for page in snapshot["pages"] if page["id"] == "delivery-checklist"
        )
        self.assertEqual(delivery_page.get("ownership_note", ""), "")


class TestBuildDashboardReviewPackage(unittest.TestCase):
    def test_build_dashboard_review_package_rejects_empty_ticket_id(self) -> None:
        from sg_preflight.dashboard.main import build_dashboard_review_package

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                build_dashboard_review_package(
                    workspace=Path(tmp), profile_id="G65", ticket_id="   "
                )

    def test_build_dashboard_review_package_rejects_empty_profile_id(self) -> None:
        from sg_preflight.dashboard.main import build_dashboard_review_package

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                build_dashboard_review_package(
                    workspace=Path(tmp), profile_id="", ticket_id="IDCEVODEV-1005738"
                )

    def test_build_dashboard_review_package_invokes_ticket_review_cli_via_subprocess(self) -> None:
        from sg_preflight.dashboard import main as dashboard_main

        fake_completed = mock.Mock(returncode=0, stdout='{"ticket_id": "IDCEVODEV-1005738"}', stderr="")
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            with mock.patch.object(dashboard_main.subprocess, "run", return_value=fake_completed) as run_mock:
                result = dashboard_main.build_dashboard_review_package(
                    workspace=workspace,
                    profile_id="G65",
                    ticket_id="IDCEVODEV-1005738",
                )
            active_ticket = json.loads(
                (workspace / "operator_state" / "active_ticket.json").read_text(encoding="utf-8")
            )
            activity_log = (workspace / "operator_state" / "activity_log.jsonl").read_text(encoding="utf-8")

        run_mock.assert_called_once()
        cmd, _kwargs = run_mock.call_args.args, run_mock.call_args.kwargs
        command = cmd[0]
        self.assertIn("ticket-review", command)
        self.assertIn("IDCEVODEV-1005738", command)
        self.assertIn("--workspace", command)
        self.assertIn(str(workspace.resolve()), command)
        self.assertIn("--profile", command)
        self.assertIn("G65", command)
        self.assertIn("--json", command)
        self.assertEqual(result["outcome"], "recorded")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["ticket_id"], "IDCEVODEV-1005738")
        self.assertEqual(result["profile_id"], "G65")
        self.assertTrue(result["recorded_by_tool"])
        self.assertEqual(active_ticket["active_ticket_id"], "IDCEVODEV-1005738")
        self.assertIn("IDCEVODEV-1005738", activity_log)

    def test_build_dashboard_review_package_command_uses_frozen_exe_directly(self) -> None:
        from sg_preflight.dashboard import main as dashboard_main

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            with mock.patch.object(dashboard_main.sys, "frozen", True, create=True):
                with mock.patch.object(dashboard_main.sys, "executable", r"C:\bundle\sgfx-preflight.exe"):
                    command = dashboard_main._dashboard_review_package_command(
                        workspace=workspace,
                        profile_id="NA0",
                        ticket_id="IDCEVODEV-1009239",
                    )

        self.assertEqual(command[:2], [r"C:\bundle\sgfx-preflight.exe", "ticket-review"])
        self.assertNotIn("-m", command)
        self.assertNotIn("sg_preflight", command)
        self.assertIn("IDCEVODEV-1009239", command)
        self.assertIn("NA0", command)

    def test_build_quality_hero_report_invokes_cli_without_jira_attachment(self) -> None:
        from sg_preflight.dashboard import main as dashboard_main

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            markdown_path = workspace / "out" / "quality" / "quality-hero-review-g70.md"
            json_path = workspace / "out" / "quality" / "quality-hero-review-g70.json"
            markdown_path.parent.mkdir(parents=True)
            markdown_path.write_text("# report\n", encoding="utf-8")
            markdown_size = markdown_path.stat().st_size
            json_path.write_text("{}", encoding="utf-8")
            fake_completed = mock.Mock(
                returncode=0,
                stdout=json.dumps({"markdown_path": str(markdown_path), "json_path": str(json_path)}),
                stderr="",
            )
            with mock.patch.object(dashboard_main.subprocess, "run", return_value=fake_completed) as run_mock:
                result = dashboard_main.build_dashboard_quality_hero_report(
                    workspace=workspace,
                    profile_id="G70",
                    ticket_id="IDCEVODEV-1009244",
                )

        command = run_mock.call_args.args[0]
        self.assertIn("quality-hero-report", command)
        self.assertIn("generate", command)
        self.assertIn("--ticket", command)
        self.assertIn("IDCEVODEV-1009244", command)
        self.assertNotIn("--attach-ticket", command)
        self.assertEqual(result["outcome"], "recorded")
        self.assertEqual(result["markdown_size_bytes"], markdown_size)
        self.assertEqual(result["markdown_path"], str(markdown_path))

    def test_build_quality_hero_report_attachment_requires_operator_confirmation(self) -> None:
        from sg_preflight.dashboard import main as dashboard_main

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                dashboard_main.build_dashboard_quality_hero_report(
                    workspace=Path(tmp),
                    profile_id="G70",
                    ticket_id="IDCEVODEV-1009244",
                    attach_ticket="IDCEVODEV-1009244",
                    operator_confirmed=False,
                )

    def test_build_quality_hero_report_attach_uses_auto_confirmed_cli_path(self) -> None:
        from sg_preflight.dashboard import main as dashboard_main

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            markdown_path = workspace / "out" / "quality" / "quality-hero-review-g70.md"
            json_path = workspace / "out" / "quality" / "quality-hero-review-g70.json"
            markdown_path.parent.mkdir(parents=True)
            markdown_path.write_text("# report\n", encoding="utf-8")
            json_path.write_text("{}", encoding="utf-8")
            fake_completed = mock.Mock(
                returncode=0,
                stdout=json.dumps(
                    {
                        "markdown_path": str(markdown_path),
                        "json_path": str(json_path),
                        "jira_attachment": {
                            "status": "recorded",
                            "response": [{"id": "11915479", "self": "https://jira.example/attachment/11915479"}],
                        },
                    }
                ),
                stderr="",
            )
            with mock.patch.object(dashboard_main.subprocess, "run", return_value=fake_completed) as run_mock:
                result = dashboard_main.build_dashboard_quality_hero_report(
                    workspace=workspace,
                    profile_id="G70",
                    ticket_id="IDCEVODEV-1009244",
                    output_root=workspace / "out" / "quality",
                    attach_ticket="IDCEVODEV-1009244",
                    operator_confirmed=True,
                )

        command = run_mock.call_args.args[0]
        self.assertIn("--attach-ticket", command)
        self.assertIn("--auto-confirm", command)
        self.assertEqual(result["attachment_id"], "11915479")
        self.assertEqual(result["jira_url"], "https://jira.example/attachment/11915479")

    def test_build_dashboard_review_package_marks_failed_outcome_on_nonzero_exit(self) -> None:
        from sg_preflight.dashboard import main as dashboard_main

        fake_completed = mock.Mock(returncode=1, stdout="", stderr="ticket-review failed: example")
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            with mock.patch.object(dashboard_main.subprocess, "run", return_value=fake_completed):
                result = dashboard_main.build_dashboard_review_package(
                    workspace=workspace,
                    profile_id="G65",
                    ticket_id="IDCEVODEV-1005738",
                )

        self.assertEqual(result["outcome"], "failed")
        self.assertEqual(result["exit_code"], 1)
        self.assertIn("ticket-review failed", result["stderr_tail"])

    def test_start_build_review_package_reports_progress_tail(self) -> None:
        from sg_preflight.dashboard import main as dashboard_main

        class FakeProcess:
            returncode = None

            def poll(self) -> None:
                return None

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            fake_process = FakeProcess()
            with mock.patch.object(dashboard_main.subprocess, "Popen", return_value=fake_process) as popen_mock:
                job = dashboard_main.start_dashboard_review_package_build(
                    workspace=workspace,
                    profile_id="G70",
                    ticket_id="IDCEVODEV-1005738",
                    operator_confirmed=True,
                )
            write_text(job.stdout_path, "\n".join(f"line {index:02d}" for index in range(25)))
            result = dashboard_main.poll_dashboard_review_package_build(job)

        self.assertEqual(result["status"], "running")
        self.assertFalse(result["completed"])
        self.assertEqual(result["typical_range"], "typical 1-5 min")
        self.assertEqual(result["stdout_tail_lines"][0], "line 05")
        self.assertEqual(result["stdout_tail_lines"][-1], "line 24")
        command = popen_mock.call_args.args[0]
        self.assertIn("ticket-review", command)
        self.assertIn("IDCEVODEV-1005738", command)
        self.assertEqual(popen_mock.call_args.kwargs["stdin"], subprocess.DEVNULL)

    def test_poll_build_review_package_persists_ticket_on_success(self) -> None:
        from sg_preflight.dashboard import main as dashboard_main

        class FakeProcess:
            returncode = 0

            def poll(self) -> int:
                return 0

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            with mock.patch.object(dashboard_main.subprocess, "Popen", return_value=FakeProcess()):
                job = dashboard_main.start_dashboard_review_package_build(
                    workspace=workspace,
                    profile_id="G70",
                    ticket_id="IDCEVODEV-1005738",
                    operator_confirmed=True,
                )
            write_text(workspace / "out" / "IDCEVODEV-1005738-review-package" / "manifest.md", "fixture\n")
            result = dashboard_main.poll_dashboard_review_package_build(job)
            active_ticket = json.loads(
                (workspace / "operator_state" / "active_ticket.json").read_text(encoding="utf-8")
            )
            activity_log = (workspace / "operator_state" / "activity_log.jsonl").read_text(encoding="utf-8")

        self.assertTrue(result["completed"])
        self.assertEqual(result["outcome"], "recorded")
        self.assertEqual(active_ticket["active_ticket_id"], "IDCEVODEV-1005738")
        self.assertIn("IDCEVODEV-1005738", activity_log)
        self.assertTrue(any("manifest.md" in item["relative_path"] for item in result["file_activity"]))
