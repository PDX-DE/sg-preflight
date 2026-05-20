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
        self.assertIn("Decision: not approval - evidence only.", snapshot["guardrails"])
        self.assertIn("BMW Git access is read-only. SGFX never modifies BMW source.", snapshot["guardrails"])
        self.assertIn("Activity log is local-only - never posted to Jira, SVN, or BMW Git.", snapshot["guardrails"])
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
        self.assertNotIn(str(Path(tmp).resolve()), delivery["summary"])
        self.assertIn(Path(tmp).name, delivery["summary"])

    def test_manual_review_state_save_is_operator_local_and_rejects_approval_words(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from sg_preflight.dashboard.main import save_manual_review_state

            payload = save_manual_review_state(
                profile_id="G65",
                workspace=tmp,
                step_slug="blender_visual_check",
                status="captured",
                note="Checked Blender and RaCo side by side.",
            )
            path = Path(tmp) / "operator_state" / "manual_review_G65.json"

            self.assertTrue(path.is_file())
            self.assertEqual(payload["profile_id"], "G65")
            self.assertEqual(payload["steps"]["blender_visual_check"]["status"], "captured")
            self.assertEqual(payload["steps"]["blender_visual_check"]["recorded_by_tool"], False)

            with self.assertRaises(ValueError):
                save_manual_review_state(
                    profile_id="G65",
                    workspace=tmp,
                    step_slug="blender_visual_check",
                    status="approved",
                    note="bad",
                )


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
