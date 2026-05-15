from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import unittest
from unittest import mock

from openpyxl import Workbook

from sg_preflight.cli import main
from sg_preflight.qa_actions import build_action_record, get_operator_action, save_action_record
from sg_preflight.services import RunRequest, execute_profile_run
from tests.operator_helpers import create_review_package_fixture, create_temp_g65_profile, write_text
from tests.test_qa_actions import _create_checker_files


ROOT = Path(__file__).resolve().parents[1]


def _write_delivery_checklist_workbook(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Delivery"
    worksheet.append(
        [
            "Car",
            "Last Tested",
            "SVN Revision",
            "Changelog Revision",
            "Export Size",
            "Screenshots",
            "Interface",
            "Perspectives",
        ]
    )
    worksheet.append(["G65_EVO", "2026-05-14 08:30", "r12345", "r12340", "OK", "Fail", "n/a", "Blocked"])
    workbook.save(path)


def _write_export_size_analysis_workbook(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Overview"
    worksheet.append(["G65", None, None, None, None, None, None])
    worksheet.append(["Variant", "TextureCube", "Texture2D", "ArrayResource", "Effect", "Total", "Valeo est."])
    worksheet.append(["BEV-Basis", 5616, 11935.61, 10677.94, 435.56, 28665.11, 25225.3])
    worksheet.append(["ICE-MPP", 5616, 11935.61, 10677.94, 435.56, 28666.11, 25226.3])
    workbook.save(path)


def _write_screenshot_test_state(root: Path) -> None:
    tests_root = root / "digital-3d-car-models" / "cars" / "BMW" / "G65_EVO" / "export" / "tests"
    write_text(root / "digital-3d-car-models" / "ci" / "scripts" / "README.md", "fixture\n")
    write_text(tests_root / "expected" / "front.png", "fake\n")
    write_text(tests_root / "expected" / "rear.png", "fake\n")
    write_text(tests_root / "actuals" / "front.png", "fake\n")
    write_text(tests_root / "diff" / "rear.png", "fake\n")
    write_text(tests_root / "test_config.lua", 'disableTest("country_variant_extra")\n')


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _write_bmw_git_readiness_state(root: Path) -> None:
    repo = root / "digital-3d-car-models"
    car_root = repo / "cars" / "BMW" / "G65_EVO"
    write_text(repo / "cars" / "BMW" / "README_IDCevo.md", "brand readme\n")
    write_text(car_root / "README.md", "profile readme\n")
    write_text(car_root / "_Workfiles" / ".keep", "\n")
    write_text(car_root / "main" / "Main_G65.rca", "scene\n")
    write_text(car_root / "export" / "tests" / "test_config.lua", "-- config\n")
    write_text(car_root / "perspectives_CID180_LHD.json", "{}\n")
    write_text(car_root / "CHANGELOG.md", "# Changelog\n")
    write_text(car_root / "lids.json", "{}\n")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    _git(repo, "config", "user.name", "David Erik Garcia Arena")
    _git(repo, "config", "user.email", "88119698+Hawaiiiiii@users.noreply.github.com")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture profile")


class TestCLI(unittest.TestCase):
    def test_list_profiles_includes_live_registry(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "sg_preflight", "list-profiles", "--json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        payload = json.loads(result.stdout)
        profile_ids = {item["profile_id"] for item in payload}
        self.assertTrue({"G70", "G65", "G45"}.issubset(profile_ids))

    def test_list_actions_includes_operator_registry(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "sg_preflight", "list-actions", "--json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        payload = json.loads(result.stdout)
        action_ids = {item["action_id"] for item in payload}
        self.assertIn("daily_live_matrix", action_ids)
        self.assertIn("repo_checker_all", action_ids)
        self.assertIn("repo_checker_idcevo", action_ids)
        self.assertIn("qa_stack__g65", action_ids)
        self.assertIn("unused_resources__g65", action_ids)
        self.assertIn("delivery_checklist__g65", action_ids)
        self.assertIn("bmw_screenshot_smoke__g65", action_ids)

    def test_list_checkers_reports_checker_catalog(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "sg_preflight", "list-checkers", "--json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        payload = json.loads(result.stdout)
        checker_keys = {item["key"] for item in payload}
        self.assertIn("execute_checks", checker_keys)
        self.assertIn("checkall_bat", checker_keys)
        self.assertIn("delivery_checklist", checker_keys)
        self.assertIn("bmw_smoke", checker_keys)

    def test_delivery_checklist_read_cli_returns_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workbook_path = root / "repositories" / "trunk" / ".pdx" / "checkers" / "deliveryChecklist" / "Delivery Data - BMW.xlsx"
            _write_delivery_checklist_workbook(workbook_path)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = main(
                    [
                        "delivery-checklist",
                        "read",
                        "--workspace",
                        str(root),
                        "--profile",
                        "G65",
                        "--json",
                    ]
                )

            markdown_stdout = io.StringIO()
            with redirect_stdout(markdown_stdout):
                markdown_result = main(
                    [
                        "delivery-checklist",
                        "read",
                        "--workspace",
                        str(root),
                        "--profile",
                        "G65",
                        "--markdown",
                    ]
                )

        self.assertEqual(result, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["profile_id"], "G65")
        self.assertEqual(payload["matched_profile_id"], "G65_EVO")
        checks = {item["key"]: item for item in payload["checks"]}
        self.assertEqual(checks["export_size"]["status"], "passed")
        self.assertEqual(checks["screenshots"]["status"], "failed")
        self.assertFalse(payload["is_approval"])
        self.assertEqual(markdown_result, 0)
        self.assertIn("Delivery checklist data is read-only", markdown_stdout.getvalue())
        self.assertIn("SGFX does not run the delivery checklist or modify the workbook.", markdown_stdout.getvalue())

    def test_export_size_analysis_read_cli_returns_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workbook_path = root / "Cars" / "size_analysis" / "G65_20251002.xlsx"
            _write_export_size_analysis_workbook(workbook_path)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = main(
                    [
                        "export-size-analysis",
                        "read",
                        "--workspace",
                        str(root),
                        "--profile",
                        "G65",
                        "--latest",
                        "--json",
                    ]
                )

            markdown_stdout = io.StringIO()
            with redirect_stdout(markdown_stdout):
                markdown_result = main(
                    [
                        "export-size-analysis",
                        "read",
                        "--workspace",
                        str(root),
                        "--profile",
                        "G65",
                        "--date",
                        "20251002",
                        "--markdown",
                    ]
                )

        self.assertEqual(result, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["profile_id"], "G65")
        self.assertEqual(payload["matched_profile_id"], "G65")
        self.assertEqual(payload["workbook_date"], "2025-10-02")
        self.assertEqual(payload["variant_count"], 2)
        self.assertFalse(payload["is_approval"])
        self.assertEqual(markdown_result, 0)
        self.assertIn("Export-size analysis data is read-only", markdown_stdout.getvalue())
        self.assertIn("SGFX does not run the export size workflow or modify the workbook.", markdown_stdout.getvalue())
        self.assertIn("BEV-Basis", markdown_stdout.getvalue())

    def test_screenshot_test_state_read_cli_returns_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_screenshot_test_state(root)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = main(
                    [
                        "screenshot-test-state",
                        "read",
                        "--workspace",
                        str(root),
                        "--profile",
                        "G65",
                        "--json",
                    ]
                )

            markdown_stdout = io.StringIO()
            with redirect_stdout(markdown_stdout):
                markdown_result = main(
                    [
                        "screenshot-test-state",
                        "read",
                        "--workspace",
                        str(root),
                        "--profile",
                        "G65",
                        "--markdown",
                    ]
                )

        self.assertEqual(result, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["matched_profile_id"], "G65_EVO")
        self.assertEqual(payload["expected_count"], 2)
        self.assertEqual(payload["actual_count"], 1)
        self.assertEqual(payload["diff_count"], 1)
        self.assertEqual(payload["disabled_test_count"], 1)
        self.assertFalse(payload["is_approval"])
        self.assertEqual(markdown_result, 0)
        self.assertIn("Screenshot test state is read-only", markdown_stdout.getvalue())
        self.assertIn("SGFX does not run screenshot tests or approve screenshots.", markdown_stdout.getvalue())
        self.assertNotIn("approved", markdown_stdout.getvalue().lower())

    def test_bmw_git_readiness_read_cli_returns_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_bmw_git_readiness_state(root)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = main(
                    [
                        "bmw-git-readiness",
                        "read",
                        "--workspace",
                        str(root),
                        "--profile",
                        "G65",
                        "--json",
                    ]
                )

            markdown_stdout = io.StringIO()
            with redirect_stdout(markdown_stdout):
                markdown_result = main(
                    [
                        "bmw-git-readiness",
                        "read",
                        "--workspace",
                        str(root),
                        "--profile",
                        "G65",
                        "--markdown",
                    ]
                )

        self.assertEqual(result, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["matched_profile_id"], "G65_EVO")
        self.assertTrue(payload["main_scene_present"])
        self.assertTrue(payload["latest_commit"]["sha"])
        self.assertFalse(payload["is_approval"])
        self.assertEqual(markdown_result, 0)
        self.assertIn("BMW Git per-profile readiness is read-only", markdown_stdout.getvalue())
        self.assertIn("SGFX does not write to BMW Git or fetch from the remote.", markdown_stdout.getvalue())
        self.assertNotIn("approved", markdown_stdout.getvalue().lower())

    def test_workflow_status_reports_repo_scene_stage(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "sg_preflight", "workflow-status", "--json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        payload = json.loads(result.stdout)
        workflow_keys = {item["key"] for item in payload}
        self.assertIn("repo_scene_checks", workflow_keys)
        self.assertIn("bmw_screenshot_smoke", workflow_keys)

    def test_desktop_help_is_available(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "sg_preflight", "desktop", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        self.assertIn("experimental desktop operator shell", result.stdout.lower())

    def test_retro_extract_help_uses_neutral_team_retro_wording(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "sg_preflight", "retro-extract", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        self.assertIn("team retrospective export", result.stdout)
        self.assertNotIn("White" "board retro export", result.stdout)

    def test_desktop_command_dispatches_to_runner(self) -> None:
        with mock.patch("sg_preflight.desktop.app.run_desktop_app", return_value=7) as runner:
            result = main(["desktop", "--profile", "G65"])
        self.assertEqual(result, 7)
        runner.assert_called_once_with(initial_profile_id="G65")

    def test_launch_action_spawns_worker_and_returns_queued_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_temp_g65_profile(root)
            _create_checker_files(root)
            (root / "config").mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / "config" / "sg_rules_live_g65.json", root / "config" / "sg_rules_live_g65.json")

            stdout = io.StringIO()
            with mock.patch("sg_preflight.cli.subprocess.Popen") as popen:
                with mock.patch("sg_preflight.qa_actions.prerequisite_status", return_value=[]):
                    with redirect_stdout(stdout):
                        result = main(
                            [
                                "launch-action",
                                "qa_stack__g65",
                                "--workspace",
                                str(root),
                                "--json",
                            ]
                        )

        self.assertEqual(result, 0)
        popen.assert_called_once()
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["action_id"], "qa_stack__g65")
        self.assertEqual(payload["status"], "queued")
        self.assertTrue(payload["run_id"])

    def test_desktop_state_recent_actions_runs_and_snapshots_use_workspace_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = create_temp_g65_profile(root)
            _create_checker_files(root)
            (root / "config").mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / "config" / "sg_rules_live_g65.json", root / "config" / "sg_rules_live_g65.json")

            action = get_operator_action("repo_checker_profile__g65", root)
            record = build_action_record(action, root)
            record.status = "completed"
            record.summary = {
                "title": "Repo checker result",
                "lines": [
                    "Style checker: 1 style-guide issue(s) across 8 checked file(s).",
                    "Open first: C:\\repo\\repositories\\trunk\\Cars_IDCevo\\BMW\\G65\\logic\\car_logic.lua (style_checker) - style issue",
                ],
            }
            write_text(Path(record.paths["log"]), "synthetic log\n")
            save_action_record(record)
            run_record = execute_profile_run(
                profile,
                RunRequest(
                    profile_id="G65",
                    packs=["anchors", "constants", "carpaints", "project_sanity"],
                    fail_on="never",
                ),
                root,
            )

            recent_stdout = io.StringIO()
            with redirect_stdout(recent_stdout):
                recent_result = main(
                    [
                        "desktop-state",
                        "recent-actions",
                        "--workspace",
                        str(root),
                        "--profile-id",
                        "G65",
                        "--json",
                    ]
                )

            recent_runs_stdout = io.StringIO()
            with redirect_stdout(recent_runs_stdout):
                recent_runs_result = main(
                    [
                        "desktop-state",
                        "recent-runs",
                        "--workspace",
                        str(root),
                        "--profile-id",
                        "G65",
                        "--json",
                    ]
                )

            snapshot_stdout = io.StringIO()
            with redirect_stdout(snapshot_stdout):
                snapshot_result = main(
                    [
                        "desktop-state",
                        "snapshot",
                        record.run_id,
                        "--workspace",
                        str(root),
                        "--json",
                    ]
                )

            run_snapshot_stdout = io.StringIO()
            with redirect_stdout(run_snapshot_stdout):
                run_snapshot_result = main(
                    [
                        "desktop-state",
                        "run-snapshot",
                        run_record.run_id,
                        "--workspace",
                        str(root),
                        "--json",
                    ]
                )

        self.assertEqual(recent_result, 0)
        recent_payload = json.loads(recent_stdout.getvalue())
        self.assertEqual(recent_payload[0]["run_id"], record.run_id)
        self.assertEqual(recent_payload[0]["profile_id"], "G65")
        self.assertEqual(recent_runs_result, 0)
        recent_runs_payload = json.loads(recent_runs_stdout.getvalue())
        self.assertEqual(recent_runs_payload[0]["run_id"], run_record.run_id)
        self.assertEqual(recent_runs_payload[0]["profile_id"], "G65")
        self.assertEqual(snapshot_result, 0)
        snapshot_payload = json.loads(snapshot_stdout.getvalue())
        self.assertEqual(snapshot_payload["run_id"], record.run_id)
        self.assertIn("Style checker:", snapshot_payload["summary_lines"][0])
        self.assertEqual(run_snapshot_result, 0)
        run_snapshot_payload = json.loads(run_snapshot_stdout.getvalue())
        self.assertEqual(run_snapshot_payload["run_id"], run_record.run_id)
        self.assertIn("Counts:", run_snapshot_payload["summary_lines"][1])

    def test_desktop_state_overview_returns_native_startup_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_temp_g65_profile(root)
            _create_checker_files(root)
            (root / "config").mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / "config" / "sg_rules_live_g65.json", root / "config" / "sg_rules_live_g65.json")

            overview_stdout = io.StringIO()
            with redirect_stdout(overview_stdout):
                result = main(
                    [
                        "desktop-state",
                        "overview",
                        "--workspace",
                        str(root),
                        "--profile-id",
                        "G65",
                        "--json",
                    ]
                )

        self.assertEqual(result, 0)
        payload = json.loads(overview_stdout.getvalue())
        self.assertEqual(payload["recommended_profile_id"], "G65")
        self.assertEqual(payload["recommended_action_id"], "qa_stack__g65")
        self.assertGreaterEqual(payload["action_count"], 5)
        self.assertGreaterEqual(payload["blocker_count"], 1)
        self.assertIn("summary_line", payload)

    def test_ticket_review_cli_forwards_candidate_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidate_root = root / "manual-candidates"
            candidate_root.mkdir(parents=True, exist_ok=True)
            fake_result = mock.Mock()
            fake_result.bundle = mock.Mock()

            with mock.patch("sg_preflight.cli.materialize_ticket_review_bundle", return_value=fake_result) as materialize:
                with mock.patch("sg_preflight.cli._console_ticket_review") as console:
                    result = main(
                        [
                            "ticket-review",
                            "IDCEVODEV-960073",
                            "--workspace",
                            str(root),
                            "--profile",
                            "G65",
                            "--candidate-root",
                            str(candidate_root),
                        ]
                    )

        self.assertEqual(result, 0)
        console.assert_called_once()
        self.assertEqual(
            materialize.call_args.kwargs["candidate_roots"],
            (candidate_root.resolve(),),
        )

    def test_review_board_related_commands_return_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = create_review_package_fixture(root)

            review_board_stdout = io.StringIO()
            with redirect_stdout(review_board_stdout):
                review_board_result = main(
                    [
                        "review-board",
                        "latest",
                        "--workspace",
                        str(root),
                        "--ticket-id",
                        "IDCEVODEV-960073",
                        "--json",
                    ]
                )

            copy_update_stdout = io.StringIO()
            with redirect_stdout(copy_update_stdout):
                copy_update_result = main(
                    [
                        "review-board",
                        "copy-update",
                        "--workspace",
                        str(root),
                        "--ticket-id",
                        "IDCEVODEV-960073",
                    ]
                )

            copy_update_json_stdout = io.StringIO()
            with redirect_stdout(copy_update_json_stdout):
                copy_update_json_result = main(
                    [
                        "review-board",
                        "copy-update",
                        "--workspace",
                        str(root),
                        "--ticket-id",
                        "IDCEVODEV-960073",
                        "--json",
                    ]
                )

            verify_stdout = io.StringIO()
            with redirect_stdout(verify_stdout):
                verify_result = main(
                    [
                        "review-board",
                        "verify",
                        "--workspace",
                        str(root),
                        "--path",
                        str(fixture["zip_path"]),
                        "--json",
                    ]
                )

            priority_stdout = io.StringIO()
            with redirect_stdout(priority_stdout):
                priority_result = main(
                    [
                        "review-priority",
                        "latest",
                        "--workspace",
                        str(root),
                        "--ticket-id",
                        "IDCEVODEV-960073",
                        "--json",
                    ]
                )

            delta_stdout = io.StringIO()
            with redirect_stdout(delta_stdout):
                delta_result = main(
                    [
                        "daily-delta",
                        "latest",
                        "--workspace",
                        str(root),
                        "--ticket-id",
                        "IDCEVODEV-960073",
                        "--json",
                    ]
                )

            digest_stdout = io.StringIO()
            with redirect_stdout(digest_stdout):
                digest_result = main(
                    [
                        "daily-digest",
                        "latest",
                        "--workspace",
                        str(root),
                        "--ticket-id",
                        "IDCEVODEV-960073",
                    ]
                )

            digest_json_stdout = io.StringIO()
            with redirect_stdout(digest_json_stdout):
                digest_json_result = main(
                    [
                        "daily-digest",
                        "latest",
                        "--workspace",
                        str(root),
                        "--ticket-id",
                        "IDCEVODEV-960073",
                        "--json",
                    ]
                )

            digest_markdown_stdout = io.StringIO()
            with redirect_stdout(digest_markdown_stdout):
                digest_markdown_result = main(
                    [
                        "daily-digest",
                        "latest",
                        "--workspace",
                        str(root),
                        "--ticket-id",
                        "IDCEVODEV-960073",
                        "--markdown",
                    ]
                )

            desktop_stdout = io.StringIO()
            with redirect_stdout(desktop_stdout):
                desktop_result = main(
                    [
                        "desktop-state",
                        "review-board",
                        "--workspace",
                        str(root),
                        "--ticket-id",
                        "IDCEVODEV-960073",
                        "--json",
                    ]
                )

            decisions_stdout = io.StringIO()
            with redirect_stdout(decisions_stdout):
                decisions_result = main(
                    [
                        "review-decisions",
                        "set",
                        "IDCEVODEV-960073",
                        "lights_OnlyCones",
                        "--workspace",
                        str(root),
                        "--status",
                        "follow_up",
                        "--owner",
                        "Adrian",
                        "--note",
                        "Treat as follow-up.",
                        "--json",
                    ]
                )

            findings_stdout = io.StringIO()
            with redirect_stdout(findings_stdout):
                findings_result = main(
                    [
                        "external-findings",
                        "add",
                        "IDCEVODEV-960073",
                        "--workspace",
                        str(root),
                        "--source",
                        "Teams / 3D Car - Bug Reports / Jana",
                        "--reported-by",
                        "Jana",
                        "--category",
                        "changelog",
                        "--type",
                        "changelog finding",
                        "--scope",
                        "G50,NA8",
                        "--finding",
                        "Missing changelog entry for light cones position change",
                        "--owner",
                        "Ana-Karina Nazare",
                        "--status",
                        "reported",
                        "--related-surface",
                        "lights_OnlyCones",
                        "--json",
                    ]
                )

        self.assertEqual(review_board_result, 0)
        self.assertEqual(copy_update_result, 0)
        self.assertEqual(copy_update_json_result, 0)
        self.assertEqual(verify_result, 0)
        self.assertEqual(priority_result, 0)
        self.assertEqual(delta_result, 0)
        self.assertEqual(digest_result, 0)
        self.assertEqual(digest_json_result, 0)
        self.assertEqual(digest_markdown_result, 0)
        self.assertEqual(desktop_result, 0)
        self.assertEqual(decisions_result, 0)
        self.assertEqual(findings_result, 0)
        self.assertEqual(json.loads(review_board_stdout.getvalue())["ticket_id"], "IDCEVODEV-960073")
        self.assertIn("IDCEVODEV-960073 QA status", copy_update_stdout.getvalue())
        self.assertEqual(json.loads(copy_update_json_stdout.getvalue())["ticket_id"], "IDCEVODEV-960073")
        self.assertEqual(json.loads(verify_stdout.getvalue())["status"], "warning")
        self.assertEqual(json.loads(priority_stdout.getvalue())["source"], "daily_snapshot")
        self.assertIn("current_created_at", json.loads(delta_stdout.getvalue()))
        self.assertIn("Daily 3D Car QA Digest", digest_stdout.getvalue())
        digest_payload = json.loads(digest_json_stdout.getvalue())
        self.assertEqual(digest_payload["ticket_id"], "IDCEVODEV-960073")
        self.assertIn("evidence_prepared", digest_payload["sections"])
        self.assertIn("what_landed_today", digest_payload["sections"])
        self.assertIn("workflow_status", digest_payload["sections"])
        self.assertIn("manual_review_pending", digest_payload["sections"])
        self.assertIn("waiting_for_owner", digest_payload["sections"])
        self.assertIn("suggested_review_order", digest_payload["sections"])
        self.assertIn("# Daily 3D Car QA Digest", digest_markdown_stdout.getvalue())
        self.assertIn("Workflow status", digest_markdown_stdout.getvalue())
        self.assertIn("Suggested review order", digest_markdown_stdout.getvalue())
        self.assertEqual(json.loads(desktop_stdout.getvalue())["ticket_id"], "IDCEVODEV-960073")
        self.assertEqual(json.loads(decisions_stdout.getvalue())["decisions"][0]["status"], "follow_up")
        self.assertEqual(json.loads(findings_stdout.getvalue())["findings"][0]["category"], "changelog")

    def test_daily_digest_latest_handles_fresh_workspace_without_review_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            markdown_stdout = io.StringIO()
            markdown_stderr = io.StringIO()
            with redirect_stdout(markdown_stdout), redirect_stderr(markdown_stderr):
                markdown_result = main(
                    [
                        "daily-digest",
                        "latest",
                        "--workspace",
                        str(root),
                        "--markdown",
                    ]
                )

            json_stdout = io.StringIO()
            json_stderr = io.StringIO()
            with redirect_stdout(json_stdout), redirect_stderr(json_stderr):
                json_result = main(
                    [
                        "daily-digest",
                        "latest",
                        "--workspace",
                        str(root),
                        "--json",
                    ]
                )

        self.assertEqual(markdown_result, 0)
        self.assertEqual(markdown_stderr.getvalue(), "")
        self.assertIn("No review package found", markdown_stdout.getvalue())
        self.assertIn("ticket-review", markdown_stdout.getvalue())
        self.assertIn("Manual review remains required", markdown_stdout.getvalue())
        self.assertEqual(json_result, 0)
        self.assertEqual(json_stderr.getvalue(), "")
        payload = json.loads(json_stdout.getvalue())
        self.assertFalse(payload["data_available"])
        self.assertEqual(payload["status"], "no_review_package")
        self.assertIn("ticket-review", payload["setup_hint"])
        self.assertIn("what_landed_today", payload["sections"])
        self.assertIn("workflow_status", payload["sections"])

    def test_ticket_review_cli_sendable_disables_action_bundles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fake_result = mock.Mock()
            fake_result.bundle = mock.Mock()

            with mock.patch("sg_preflight.cli.materialize_ticket_review_bundle", return_value=fake_result) as materialize:
                with mock.patch("sg_preflight.cli._console_ticket_review"):
                    result = main(
                        [
                            "ticket-review",
                            "IDCEVODEV-960073",
                            "--workspace",
                            str(root),
                            "--sendable",
                        ]
                    )

        self.assertEqual(result, 0)
        self.assertFalse(materialize.call_args.kwargs["include_action_bundles"])

    def test_daily_snapshot_cli_forwards_battery_filters(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fake_result = mock.Mock()
            fake_result.snapshot = mock.Mock()
            fake_result.markdown_path = root / "snapshot.md"
            fake_result.json_path = root / "snapshot.json"

            with mock.patch("sg_preflight.cli.materialize_daily_qa_snapshot", return_value=fake_result) as materialize:
                with mock.patch("sg_preflight.cli._console_daily_snapshot") as console:
                    result = main(
                        [
                            "daily-qa-snapshot",
                            "--workspace",
                            str(root),
                            "--profile",
                            "NA8",
                            "--battery-defaults",
                            "--battery-filter",
                            "lights_drl_front",
                        ]
                    )

        self.assertEqual(result, 0)
        console.assert_called_once()
        self.assertEqual(
            materialize.call_args.kwargs["battery_filters"],
            (
                "default",
                "openAllDoors_",
                "lights_drl_front",
                "lights_LowBeam",
                "lights_HighBeam",
                "lights_OnlyCones",
                "welcome_animation_",
                "automatic_Doors_",
                "highlighting_Doors",
            ),
        )

    def test_screenshot_triage_cli_forwards_candidate_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "Cars_IDCevo" / "BMW" / "G70"
            project_root.mkdir(parents=True, exist_ok=True)
            candidate_root = root / "manual-candidates"
            candidate_root.mkdir(parents=True, exist_ok=True)
            fake_bundle = mock.Mock()
            fake_bundle.report = mock.Mock()

            with mock.patch("sg_preflight.cli.build_visual_review_prep", return_value=mock.Mock(priority_screenshots=("focus.png",))):
                with mock.patch("sg_preflight.cli.materialize_screenshot_triage", return_value=fake_bundle) as materialize:
                    with mock.patch("sg_preflight.cli._console_screenshot_triage") as console:
                        result = main(
                            [
                                "screenshot-triage",
                                "--project-root",
                                str(project_root),
                                "--workspace",
                                str(root),
                                "--candidate-root",
                                str(candidate_root),
                            ]
                        )

        self.assertEqual(result, 0)
        console.assert_called_once()
        self.assertEqual(
            materialize.call_args.kwargs["candidate_roots"],
            (candidate_root.resolve(),),
        )

    def test_daily_qa_snapshot_cli_forwards_profiles_and_smoke_options(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fake_result = mock.Mock()
            fake_result.snapshot = mock.Mock()

            with mock.patch("sg_preflight.cli.materialize_daily_qa_snapshot", return_value=fake_result) as materialize:
                with mock.patch("sg_preflight.cli._console_daily_snapshot") as console:
                    result = main(
                        [
                            "daily-qa-snapshot",
                            "--workspace",
                            str(root),
                            "--profile",
                            "NA8",
                            "--profile",
                            "G78",
                            "--smoke-test",
                            "openAllDoors_rightView",
                            "--no-smoke",
                        ]
                    )

        self.assertEqual(result, 0)
        console.assert_called_once()
        self.assertEqual(
            materialize.call_args.kwargs["profile_ids"],
            ("NA8", "G78"),
        )
        self.assertEqual(materialize.call_args.kwargs["smoke_test"], "openAllDoors_rightView")
        self.assertFalse(materialize.call_args.kwargs["run_smoke"])

    def test_good_demo_passes(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "sg_preflight", "demo-good"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        report_path = ROOT / "out" / "demo-good.json"
        self.assertTrue(report_path.exists())
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["summary"]["errors"], 0)

    def test_broken_demo_fails(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "sg_preflight", "demo-broken"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2, msg=result.stdout + "\n" + result.stderr)
        report_path = ROOT / "out" / "demo-broken.json"
        self.assertTrue(report_path.exists())
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertGreater(report["summary"]["errors"], 0)


if __name__ == "__main__":
    unittest.main()
