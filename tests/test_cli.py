from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
import unittest
from unittest import mock

from sg_preflight.cli import main
from sg_preflight.qa_actions import build_action_record, get_operator_action, save_action_record
from sg_preflight.services import RunRequest, execute_profile_run
from tests.operator_helpers import create_temp_g65_profile, write_text
from tests.test_qa_actions import _create_checker_files


ROOT = Path(__file__).resolve().parents[1]


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
