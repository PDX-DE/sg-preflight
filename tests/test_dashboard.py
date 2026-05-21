from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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

    def test_dashboard_snapshot_contains_four_operator_pages_and_guardrails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from sg_preflight.dashboard.main import build_dashboard_snapshot

            snapshot = build_dashboard_snapshot("", tmp)

        page_ids = [page["id"] for page in snapshot["pages"]]
        self.assertEqual(
            page_ids,
            [
                "delivery-checklist",
                "screenshot-test-state",
                "daily-digest",
                "manual-review",
            ],
        )
        self.assertEqual(snapshot["profile_id"], "G70")
        self.assertEqual(snapshot["profile_options"][0]["id"], "G70")
        self.assertTrue(snapshot["profile_known"])
        self.assertEqual(snapshot["theme"], "clean")
        self.assertEqual(snapshot["workspace_label"], Path(tmp).name)
        self.assertEqual(
            snapshot["navigation"],
            [
                {"id": "delivery-checklist", "label": "Delivery Checklist"},
                {"id": "screenshot-test-state", "label": "Screenshot Test State"},
                {"id": "daily-digest", "label": "Daily Digest"},
                {"id": "manual-review", "label": "Manual Review Companion"},
            ],
        )
        self.assertEqual(
            snapshot["shortcuts"],
            ["F1 Help", "F2 Profile switch", "F5 Refresh page", "F12 Diagnostic", "Esc Quit"],
        )
        self.assertEqual(snapshot["pages"][0]["tagline"], "Workbook evidence per delivery profile (read-only).")
        self.assertEqual(snapshot["pages"][1]["tagline"], "BMW + MINI baseline / actual / diff counts per brand.")
        self.assertEqual(snapshot["pages"][2]["tagline"], "Morning status snapshot for the SG Daily standup.")
        self.assertEqual(
            snapshot["pages"][3]["tagline"],
            "Step through the 7 Quality-Hero review steps. Operator verdict per step.",
        )
        self.assertIn("Manual review remains required.", snapshot["guardrails"])
        self.assertIn("Decision: not approval — evidence only.", snapshot["guardrails"])
        self.assertIn("BMW Git access is read-only. SGFX never modifies BMW source.", snapshot["guardrails"])
        self.assertIn("Activity log is local-only — never posted to Jira, SVN, or BMW Git.", snapshot["guardrails"])
        manual_page = next(page for page in snapshot["pages"] if page["id"] == "manual-review")
        self.assertEqual(manual_page["status"], "not_run")
        self.assertTrue(all(item["status"] == "not_run" for item in manual_page["items"]))
        self.assertTrue(all(step["verdict"] == "not_run" for step in manual_page["payload"]["steps"]))
        for forbidden in ("approved", "cleared", "signed-off", "production-ready"):
            self.assertNotIn(forbidden, json.dumps(snapshot, ensure_ascii=False).casefold())

    def test_dashboard_source_uses_available_vocab_for_shortcut_status(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "sg_preflight" / "dashboard" / "main.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("Shortcuts available", source)
        self.assertNotIn("Shortcuts ready", source)

    def test_dashboard_source_wires_sgfx_icon_and_header_logo(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "sg_preflight" / "dashboard" / "main.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("runtime_asset_path", source)
        self.assertIn("sgfx_icon.png", source)
        self.assertIn("framework_sgfx_logo.png", source)
        self.assertIn('kwargs["favicon"]', source)
        self.assertIn("/sgfx-dashboard-assets", source)

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
                                with self.assertRaisesRegex(RuntimeError, "embedded Clean desktop shell"):
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

            snapshot = build_dashboard_snapshot("G70", tmp)

        delivery = next(page for page in snapshot["pages"] if page["id"] == "delivery-checklist")
        self.assertEqual(delivery["status"], "unavailable")
        self.assertEqual(len(delivery["actions"]), 1)
        action = delivery["actions"][0]
        self.assertEqual(action["id"], GENERATE_WORKBOOK_ACTION_ID)
        self.assertTrue(action["requires_confirmation"])
        self.assertTrue(action["disabled"])
        self.assertFalse(action["preflight"]["can_run"])
        self.assertIn("This will run the BMW pipeline for G70", action["confirmation_message"])
        checks = {item["key"]: item for item in action["preflight"]["checks"]}
        self.assertIn("digital_3d_car_repo", checks)

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
        self.assertEqual(len(actions), 1)
        action = actions[0]
        self.assertEqual(action["id"], DAILY_DIGEST_BUILD_PACKAGE_ACTION_ID)
        self.assertEqual(action["label"], DAILY_DIGEST_BUILD_PACKAGE_ACTION_LABEL)
        self.assertTrue(action["requires_ticket_id"])
        self.assertEqual(action["ticket_id_hint"], DAILY_DIGEST_TICKET_ID_PLACEHOLDER)

    def test_daily_digest_page_action_carries_active_ticket_id_hint(self) -> None:
        from sg_preflight.dashboard.main import _daily_digest_page

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            with mock.patch(
                "sg_preflight.dashboard.main.build_latest_daily_digest",
                return_value={"status": "no_review_package", "data_available": False, "sections": {}},
            ):
                page = _daily_digest_page(workspace, "G65", active_ticket_id="IDCEVODEV-1005738")

        self.assertEqual(page["actions"][0]["ticket_id_hint"], "IDCEVODEV-1005738")
        self.assertEqual(page["payload"]["active_ticket_id"], "IDCEVODEV-1005738")

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
        self.assertIn("ci/scripts/car_manager.py screenshots", screenshot_page["ownership_note"])
        self.assertIn("SGFX reads the output", screenshot_page["ownership_note"])

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

        run_mock.assert_called_once()
        cmd, _kwargs = run_mock.call_args.args, run_mock.call_args.kwargs
        command = cmd[0]
        self.assertIn("ticket-review", command)
        self.assertIn("IDCEVODEV-1005738", command)
        self.assertIn("--workspace", command)
        self.assertIn(str(workspace.resolve()), command)
        self.assertIn("--profile-ids", command)
        self.assertIn("G65", command)
        self.assertIn("--json", command)
        self.assertEqual(result["outcome"], "recorded")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["ticket_id"], "IDCEVODEV-1005738")
        self.assertEqual(result["profile_id"], "G65")
        self.assertTrue(result["recorded_by_tool"])

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
