from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest import mock

from openpyxl import Workbook

from sg_preflight.desktop.evidence_model import (
    desktop_action_snapshot,
    desktop_actions_for_profile,
    desktop_blocker_items,
    desktop_environment_doctor,
    desktop_operator_overview,
    desktop_profiles,
    desktop_recent_actions,
    desktop_recent_runs,
    desktop_run_snapshot,
    desktop_surface_items,
    latest_action_snapshot_for_profile,
)
from sg_preflight.desktop.file_ops import build_open_command, build_reveal_command, normalize_local_path
from sg_preflight.qa_actions import execute_operator_action, get_operator_action
from tests.operator_helpers import create_temp_g65_profile, write_text
from tests.test_qa_actions import ROOT, _create_checker_files


def _write_export_size_analysis_workbook(path: Path, *, profile: str = "G65") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Overview"
    sheet.append([profile])
    sheet.append([])
    sheet.append(["VARIANT", "TextureCube", "Mesh", "TOTAL"])
    sheet.append(["BEV-Basis", 5616, 23049.11, 28665.11])
    sheet.append(["PHEV-MSP", 5620, 23100.55, 28720.55])
    workbook.save(path)


class TestDesktopEvidenceModel(unittest.TestCase):
    def test_desktop_shell_source_carries_sgfx_header_toggle_and_guardrails(self) -> None:
        main_window_source = (ROOT / "sg_preflight" / "desktop" / "main_window.py").read_text(encoding="utf-8")

        self.assertNotIn("SGFX: Project Quality-Hero", main_window_source)
        self.assertNotIn("Clean Operator Console", main_window_source)
        self.assertNotIn("Grafiks Operator Console", main_window_source)
        self.assertIn('DESKTOP_WINDOW_TITLE = "Seriengrafik: Project Quality-Hero"', main_window_source)
        self.assertIn("GRAFIKS_WIP_NOTICE", main_window_source)
        self.assertIn("Grafiks mode is experimental — recommend Clean mode for daily work.", main_window_source)
        self.assertIn("clean_mode_button", main_window_source)
        self.assertIn("grafiks_mode_button", main_window_source)
        self.assertIn("_set_presentation_mode", main_window_source)
        self.assertIn("Manual review remains required.", main_window_source)
        self.assertIn("Decision: not approval — evidence only.", main_window_source)
        self.assertIn("BMW Git access is read-only. SGFX never modifies BMW source.", main_window_source)
        self.assertIn("Activity log is local-only — never posted to Jira, SVN, or BMW Git.", main_window_source)
        self.assertIn('"available" if action.ready else "unavailable"', main_window_source)
        self.assertNotIn('"ready" if action.ready else "blocked"', main_window_source)

    def test_grafiks_shell_mirrors_dependency_setup_surface(self) -> None:
        main_window_source = (ROOT / "sg_preflight" / "desktop" / "main_window.py").read_text(encoding="utf-8")

        self.assertIn("Dependency Setup", main_window_source)
        self.assertIn("build_dependency_onboarding_status", main_window_source)
        self.assertIn("start_dependency_setup_action", main_window_source)
        self.assertIn("poll_dependency_setup_action", main_window_source)
        self.assertIn("cancel_dependency_setup_action", main_window_source)
        self.assertIn("setup_action_selector", main_window_source)
        self.assertIn("setup_run_button", main_window_source)
        self.assertIn("setup_cancel_button", main_window_source)
        self.assertIn("QDialogButtonBox", main_window_source)
        self.assertIn("Source path", main_window_source)
        self.assertIn("Target path", main_window_source)
        self.assertIn("operator_confirmed=True", main_window_source)

    def test_grafiks_shell_sets_window_icon_and_header_logo(self) -> None:
        app_source = (ROOT / "sg_preflight" / "desktop" / "app.py").read_text(encoding="utf-8")
        main_window_source = (ROOT / "sg_preflight" / "desktop" / "main_window.py").read_text(encoding="utf-8")
        widgets_source = (ROOT / "sg_preflight" / "desktop" / "widgets.py").read_text(encoding="utf-8")

        self.assertIn("QIcon", app_source)
        self.assertIn("setWindowIcon", app_source)
        self.assertIn('initial_mode: str = "clean"', app_source)
        self.assertIn("desktop_native/resources/exe_ico.ico", app_source)
        self.assertIn("_desktop_tooltip_stylesheet", app_source)
        self.assertIn("_windows", app_source)
        self.assertIn("prewarm", app_source)
        self.assertIn("hide()", app_source)
        self.assertIn('runtime_asset_path("logo_sgfx.png")', main_window_source)
        self.assertIn("scaledToWidth(240", main_window_source)
        self.assertIn("debug_icon.png", main_window_source)
        self.assertIn("GRAFIKS_HOTKEY_MESSAGES", main_window_source)
        self.assertIn("keyPressEvent", main_window_source)
        self.assertIn("_show_about_dialog", main_window_source)
        self.assertIn("setToolTip", main_window_source)
        self.assertIn('ABOUT_CONTENT.get("data_handling_disclosure"', main_window_source)
        self.assertIn("addWidget(disclosure_label)", main_window_source)
        self.assertIn("QPixmap", widgets_source)
        self.assertIn("logo_path", widgets_source)
        self.assertIn("scaledToWidth(\n                100", widgets_source)

    def test_clean_host_embeds_nicegui_without_external_browser(self) -> None:
        host_source = (ROOT / "sg_preflight" / "desktop" / "clean_host.py").read_text(encoding="utf-8")
        app_source = (ROOT / "sg_preflight" / "desktop" / "app.py").read_text(encoding="utf-8")

        self.assertIn("QWebEngineView", host_source)
        self.assertIn("--no-native", host_source)
        self.assertIn("stdout=subprocess.DEVNULL", host_source)
        self.assertIn("hidden_subprocess_kwargs", host_source)
        self.assertIn("switch_requested", host_source)
        self.assertNotIn("sg_preflight.dashboard.main", host_source)
        self.assertIn("CleanDashboardWindow", app_source)
        self.assertIn("desktop_native/resources/exe_ico.ico", host_source)
        self.assertIn("Dashboard ready", host_source)
        self.assertNotIn("Clean " + "dashboard", host_source)
        self.assertNotIn("Clean Operator " + "Console", host_source)

    def test_desktop_surface_items_exposes_clean_mode_evidence_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = create_temp_g65_profile(root)
            _create_checker_files(root)

            surfaces = desktop_surface_items(profile.profile_id, root)

        self.assertEqual(
            [item.key for item in surfaces],
            [
                "delivery-checklist",
                "screenshot-test-state",
                "risk-score",
                "daily-digest",
                "team-digest-board",
                "manual-review",
            ],
        )
        self.assertEqual([item.label for item in surfaces][0], "Delivery Checklist")
        self.assertTrue(all(item.state for item in surfaces))
        self.assertTrue(all(item.summary for item in surfaces))
        self.assertIn("Quality-Hero", surfaces[-1].summary)
        self.assertEqual(surfaces[-1].state, "not_run")
        self.assertIn("Manual review session not started", surfaces[-1].summary)
        self.assertTrue(all(str(root.resolve()) not in item.summary for item in surfaces))
        self.assertFalse(any(item.summary.startswith("{") for item in surfaces))

    def test_desktop_profiles_show_real_svn_slices_without_bundle_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "Cars_IDCevo" / "BMW" / "G70").mkdir(parents=True)

            profiles = desktop_profiles(root)

        self.assertIn("G70", [item.profile_id for item in profiles])

    def test_desktop_actions_for_profile_exposes_primary_shell_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = create_temp_g65_profile(root)
            _create_checker_files(root)

            with mock.patch.dict(
                os.environ,
                {
                    "SG_RACO_HEADLESS": str(root / "missing" / "RaCoHeadless.exe"),
                    "SG_CARMODELS_REPO": str(root / "missing" / "digital-3d-car-models"),
                },
                clear=False,
            ):
                with mock.patch("sg_preflight.services.shutil.which", return_value=None):
                    actions = desktop_actions_for_profile(profile.profile_id, root, profiles=[profile])

        action_ids = [item.action_id for item in actions]
        self.assertEqual(
            action_ids,
            [
                "qa_stack__g65",
                "repo_checker_profile__g65",
                "scene_check__g65",
                "unused_resources__g65",
                "delivery_checklist__g65",
            ],
        )
        self.assertTrue(actions[0].ready)
        self.assertFalse(actions[2].ready)

    def test_operator_overview_summarizes_native_startup_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = create_temp_g65_profile(root)
            _create_checker_files(root)
            _write_export_size_analysis_workbook(
                root / "repositories" / "trunk" / "Cars" / "size_analysis" / "G65_20251002.xlsx"
            )

            with mock.patch.dict(
                os.environ,
                {
                    "SG_RACO_HEADLESS": str(root / "missing" / "RaCoHeadless.exe"),
                    "SG_CARMODELS_REPO": str(root / "missing" / "digital-3d-car-models"),
                },
                clear=False,
            ):
                with mock.patch("sg_preflight.services.shutil.which", return_value=None):
                    overview = desktop_operator_overview(root, profile_id="G65", profiles=[profile])

        self.assertFalse((root / "out").exists())
        self.assertEqual(overview.recommended_profile_id, "G65")
        self.assertEqual(overview.recommended_action_id, "qa_stack__g65")
        self.assertGreaterEqual(overview.ready_profile_count, 1)
        self.assertGreaterEqual(overview.action_count, 5)
        self.assertGreaterEqual(overview.ready_action_count, 1)
        self.assertGreaterEqual(overview.blocked_action_count, 1)
        self.assertGreaterEqual(overview.blocker_count, 1)
        self.assertGreaterEqual(overview.manual_card_count, 1)
        self.assertEqual(overview.export_size_analysis_status, "available")
        self.assertEqual(overview.export_size_analysis_variant_count, 2)
        self.assertEqual(overview.export_size_analysis_workbook_date, "2025-10-02")
        self.assertIn("read-only", overview.export_size_analysis_summary.casefold())
        self.assertIn("available", overview.environment_state_counts)
        self.assertNotIn("ready", overview.environment_state_counts)
        self.assertIn("G65", overview.summary_line)

    def test_environment_doctor_is_read_only_for_workspace_output_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            items = desktop_environment_doctor(root)

        self.assertFalse((root / "out").exists())
        output_item = next(item for item in items if item.key == "output_write_access")
        self.assertEqual(output_item.state, "not_run")
        self.assertIn("not probed", output_item.summary)

    def test_action_snapshot_reads_aggregated_checker_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = create_temp_g65_profile(root)
            _create_checker_files(root)
            (root / "config").mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / "config" / "sg_rules_live_g65.json", root / "config" / "sg_rules_live_g65.json")

            with mock.patch.dict(
                os.environ,
                {
                    "SG_RACO_HEADLESS": str(root / "missing" / "RaCoHeadless.exe"),
                    "SG_CARMODELS_REPO": str(root / "missing" / "digital-3d-car-models"),
                },
                clear=False,
            ):
                action = get_operator_action("qa_stack__g65", root, profiles=[profile])

                with mock.patch(
                    "sg_preflight.qa_actions.subprocess.run",
                    side_effect=[
                        subprocess.CompletedProcess(
                            args=["python"],
                            returncode=1,
                            stdout="checked 8 files (src: 3; fmt: 7; license: 7)\ndetected 2 style guide issues\n",
                            stderr="",
                        ),
                        subprocess.CompletedProcess(
                            args=["python"],
                            returncode=0,
                            stdout="starting luacheck on 12 files\n0 errors found\n",
                            stderr="",
                        ),
                        subprocess.CompletedProcess(
                            args=["python"],
                            returncode=0,
                            stdout=str(profile.project_root / "resources" / "textures" / "unused_diffuse.png"),
                            stderr="",
                        ),
                    ],
                ):
                    record = execute_operator_action(action, root)

            snapshot = desktop_action_snapshot(record.run_id, root)
            run_snapshot = desktop_run_snapshot(snapshot.linked_run_id, root)
            latest = latest_action_snapshot_for_profile("G65", root, preferred_action_id="qa_stack__g65")
            recent = desktop_recent_actions(root, profile_id="G65", limit=4)
            recent_runs = desktop_recent_runs(root, profile_id="G65", limit=4)
            blockers = desktop_blocker_items("G65", root, profiles=[profile])

            self.assertEqual(snapshot.run_id, record.run_id)
            self.assertEqual(snapshot.top_paths[0].path, str(profile.project_root / "resources" / "textures" / "unused_diffuse.png"))
            self.assertTrue(snapshot.current_command)
            self.assertTrue(snapshot.log_path)
            self.assertTrue(any(item.label == "Copy Jira note" for item in snapshot.copy_items))
            self.assertTrue(any(item.key == "pre_delivery" for item in snapshot.copy_items))
            self.assertTrue(snapshot.latest_run_links.html_report.endswith(".html"))
            self.assertTrue(snapshot.linked_run_id)
            self.assertEqual(run_snapshot.profile_id, "G65")
            self.assertFalse(run_snapshot.initializing)
            self.assertTrue(run_snapshot.output_root)
            self.assertTrue(any(item.label == "HTML report" for item in run_snapshot.artifacts))
            self.assertTrue(any(item.label == "Scene Hierarchy" for item in run_snapshot.source_files))
            self.assertIsNotNone(latest)
            self.assertEqual(latest.run_id, record.run_id)
            self.assertEqual(recent[0].run_id, record.run_id)
            self.assertIn("Standard preflight:", recent[0].summary)
            self.assertEqual(recent_runs[0].profile_id, "G65")
            self.assertTrue(recent_runs[0].summary.startswith("Counts:"))
            self.assertTrue(any(item.key == "bmw_screenshot_smoke" for item in blockers))
            self.assertFalse(any(item.state == "ready" for item in blockers))

    def test_run_snapshot_returns_initializing_placeholder_for_transient_missing_nested_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transient_run_id = "123e4567-e89b-12d3-a456-426614174000"

            snapshot = desktop_run_snapshot(transient_run_id, root)

        self.assertEqual(snapshot.run_id, transient_run_id)
        self.assertEqual(snapshot.status, "queued")
        self.assertTrue(snapshot.initializing)
        self.assertEqual(snapshot.summary_title, "Action record is initializing")
        self.assertIn("waiting for the nested action bundle", snapshot.summary_lines[1].lower())


class TestDesktopFileOps(unittest.TestCase):
    def test_normalize_local_path_keeps_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sample.txt"
            write_text(path, "hello\n")
            normalized = normalize_local_path(path)
            self.assertIsNotNone(normalized)
            self.assertEqual(normalized, path.resolve())

    def test_build_open_and_reveal_commands_match_windows_expectations(self) -> None:
        path = Path(r"C:\repo\repositories\trunk\Cars_IDCevo\BMW\G65\main.rca")
        self.assertEqual(
            build_open_command(path, platform_name="win32"),
            ("cmd", "/c", "start", "", str(path)),
        )
        self.assertEqual(
            build_reveal_command(path, platform_name="win32"),
            ("explorer", "/select,", str(path)),
        )


if __name__ == "__main__":
    unittest.main()
