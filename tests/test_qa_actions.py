from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest import mock

from sg_preflight.qa_actions import execute_operator_action, get_operator_action, list_operator_actions
from tests.operator_helpers import create_temp_g65_profile, write_text


ROOT = Path(__file__).resolve().parents[1]


def _create_checker_files(root: Path) -> None:
    mirror_root = root / "repositories" / "trunk"
    write_text(mirror_root / ".pdx" / "checkers" / "executeChecks.py", "print('checker stub')\n")
    write_text(mirror_root / ".pdx" / "checkers" / "checkall.bat", "@echo off\n")
    write_text(mirror_root / ".pdx" / "checkers" / "checkcars.bat", "@echo off\n")
    write_text(mirror_root / ".pdx" / "checkers" / "checkcars_IDCevo.bat", "@echo off\n")
    write_text(
        mirror_root / ".pdx" / "checkers" / "code_style_checker" / "check_all_styles.py",
        "print('style stub')\n",
    )
    write_text(
        mirror_root / ".pdx" / "checkers" / "printNotUsedResources.py",
        "print('unused stub')\n",
    )
    write_text(mirror_root / "check_scenes.py", "print('scene stub')\n")
    (mirror_root / "Cars").mkdir(parents=True, exist_ok=True)


class TestQaActions(unittest.TestCase):
    def test_action_registry_marks_repo_checker_ready_and_scene_check_blocked_without_raco(self) -> None:
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
                    actions = list_operator_actions(root, profiles=[profile])

        action_map = {action.action_id: action for action in actions}
        self.assertTrue(action_map["daily_live_matrix"].ready)
        self.assertTrue(action_map["repo_checker_all"].ready)
        self.assertTrue(action_map["qa_stack__g65"].ready)
        self.assertTrue(action_map["repo_checker_profile__g65"].ready)
        self.assertTrue(action_map["unused_resources__g65"].ready)
        self.assertTrue(action_map["delivery_checklist__g65"].ready)
        self.assertFalse(action_map["scene_check__g65"].ready)
        self.assertFalse(action_map["bmw_screenshot_smoke__g65"].ready)
        self.assertIn("RaCoHeadless.exe", action_map["scene_check__g65"].blocker_message)
        self.assertIn("digital-3d-car-models", action_map["bmw_screenshot_smoke__g65"].blocker_message)

    def test_execute_repo_checker_action_persists_log_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = create_temp_g65_profile(root)
            _create_checker_files(root)
            action = get_operator_action("repo_checker_profile__g65", root, profiles=[profile])

            sample_style_output = """
Checking C:\\temp\\Cars\\BMW\\G65
checked 8 files (src: 3; fmt: 7; license: 7)
detected 2 style guide issues
""".strip()

            sample_execute_output = """
############################################
starting  luacheck on  12  files
############################################
0  errors found
############################################
""".strip()

            with mock.patch(
                "sg_preflight.qa_actions.subprocess.run",
                side_effect=[
                    subprocess.CompletedProcess(
                        args=["python"],
                        returncode=1,
                        stdout=sample_style_output,
                        stderr="",
                    ),
                    subprocess.CompletedProcess(
                        args=["python"],
                        returncode=0,
                        stdout=sample_execute_output,
                        stderr="",
                    ),
                ],
            ):
                record = execute_operator_action(action, root)
                self.assertEqual(record.status, "completed")
                self.assertTrue(Path(record.paths["log"]).exists())
                self.assertTrue(Path(record.paths["summary_json"]).exists())
                joined = " ".join(record.summary.get("lines", []))
                self.assertIn("Style checker: 2 style-guide issue(s)", joined)
                self.assertIn("executeChecks: 0 error batch(es)", joined)
                self.assertIn("luacheck: 12 file(s)", joined)

    def test_execute_unused_resource_action_persists_log_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = create_temp_g65_profile(root)
            _create_checker_files(root)
            action = get_operator_action("unused_resources__g65", root, profiles=[profile])

            sample_output = str(profile.project_root / "resources" / "textures" / "unused_diffuse.png")

            with mock.patch(
                "sg_preflight.qa_actions.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=["python"],
                    returncode=0,
                    stdout=sample_output,
                    stderr="",
                ),
            ):
                record = execute_operator_action(action, root)

            self.assertEqual(record.status, "completed")
            self.assertEqual(record.summary.get("unused_count"), 1)
            self.assertIn("unused_diffuse.png", " ".join(record.summary.get("lines", [])))
            self.assertTrue(Path(record.paths["log"]).exists())

    def test_execute_delivery_checklist_action_reports_missing_bmw_prerequisites(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = create_temp_g65_profile(root)
            action = get_operator_action("delivery_checklist__g65", root, profiles=[profile])

            with mock.patch.dict(
                os.environ,
                {"SG_CARMODELS_REPO": str(root / "missing" / "digital-3d-car-models")},
                clear=False,
            ):
                record = execute_operator_action(action, root)

            self.assertEqual(record.status, "completed")
            self.assertEqual(record.summary.get("local_assets_found"), 4)
            self.assertFalse(record.summary.get("bmw_repo_ready"))
            self.assertIn(
                "blocked on local `digital-3d-car-models` access",
                " ".join(record.summary.get("lines", [])),
            )
            self.assertTrue(Path(record.paths["log"]).exists())

    def test_execute_profile_stack_runs_preflight_and_available_sg_steps(self) -> None:
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

                sample_style_output = """
Checking C:\\temp\\Cars\\BMW\\G65
checked 8 files (src: 3; fmt: 7; license: 7)
detected 2 style guide issues
""".strip()

                sample_execute_output = """
############################################
starting  luacheck on  12  files
############################################
0  errors found
############################################
""".strip()

                sample_unused_output = str(profile.project_root / "resources" / "textures" / "unused_diffuse.png")

                with mock.patch(
                    "sg_preflight.qa_actions.subprocess.run",
                    side_effect=[
                        subprocess.CompletedProcess(
                            args=["python"],
                            returncode=1,
                            stdout=sample_style_output,
                            stderr="",
                        ),
                        subprocess.CompletedProcess(
                            args=["python"],
                            returncode=0,
                            stdout=sample_execute_output,
                            stderr="",
                        ),
                        subprocess.CompletedProcess(
                            args=["python"],
                            returncode=0,
                            stdout=sample_unused_output,
                            stderr="",
                        ),
                    ],
                ):
                    record = execute_operator_action(action, root)

            lines = record.summary.get("lines", []) if record.summary else []
            self.assertEqual(record.status, "completed")
            self.assertTrue(any(line.startswith("Standard preflight:") for line in lines))
            self.assertTrue(any(line.startswith("Repo checker:") for line in lines))
            self.assertTrue(any(line.startswith("Unused resources:") for line in lines))
            self.assertTrue(any(line.startswith("Delivery checklist:") for line in lines))
            self.assertTrue(any("2 style issue(s)" in line for line in lines))
            self.assertTrue(any("Scene check: blocked" in line for line in lines))
            self.assertTrue(any("BMW screenshot smoke: blocked" in line for line in lines))


if __name__ == "__main__":
    unittest.main()
