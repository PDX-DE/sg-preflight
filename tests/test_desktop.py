from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest import mock

from sg_preflight.desktop.evidence_model import (
    desktop_action_snapshot,
    desktop_actions_for_profile,
    desktop_blocker_items,
    desktop_recent_actions,
    desktop_recent_runs,
    desktop_run_snapshot,
    latest_action_snapshot_for_profile,
)
from sg_preflight.desktop.file_ops import build_open_command, build_reveal_command, normalize_local_path
from sg_preflight.qa_actions import execute_operator_action, get_operator_action
from tests.operator_helpers import create_temp_g65_profile, write_text
from tests.test_qa_actions import ROOT, _create_checker_files


class TestDesktopEvidenceModel(unittest.TestCase):
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
            self.assertTrue(any(item.label == "Copy Jira note" for item in snapshot.copy_items))
            self.assertTrue(any(item.key == "pre_delivery" for item in snapshot.copy_items))
            self.assertTrue(snapshot.latest_run_links.html_report.endswith(".html"))
            self.assertTrue(snapshot.linked_run_id)
            self.assertEqual(run_snapshot.profile_id, "G65")
            self.assertTrue(any(item.label == "HTML report" for item in run_snapshot.artifacts))
            self.assertTrue(any(item.label == "Scene Hierarchy" for item in run_snapshot.source_files))
            self.assertIsNotNone(latest)
            self.assertEqual(latest.run_id, record.run_id)
            self.assertEqual(recent[0].run_id, record.run_id)
            self.assertIn("Standard preflight:", recent[0].summary)
            self.assertEqual(recent_runs[0].profile_id, "G65")
            self.assertTrue(recent_runs[0].summary.startswith("Counts:"))
            self.assertTrue(any(item.key == "bmw_screenshot_smoke" for item in blockers))

    def test_run_snapshot_returns_initializing_placeholder_for_transient_missing_nested_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transient_run_id = "123e4567-e89b-12d3-a456-426614174000"

            snapshot = desktop_run_snapshot(transient_run_id, root)

        self.assertEqual(snapshot.run_id, transient_run_id)
        self.assertEqual(snapshot.status, "queued")
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
