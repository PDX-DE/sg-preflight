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
FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "checkers"


def _checker_fixture(name: str) -> str:
    return (FIXTURE_ROOT / name).read_text(encoding="utf-8")


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
            sample_style_output = _checker_fixture("style_checker_issue.log")
            sample_execute_output = _checker_fixture("execute_checks_issue.log")

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
                self.assertIn("Style checker: 1 style-guide issue(s)", joined)
                self.assertIn("executeChecks: 2 error batch(es)", joined)
                self.assertIn("luacheck: 124 file(s)", joined)
                self.assertIn("Open first:", joined)
                checker_evidence = record.summary.get("checker_evidence", {})
                self.assertFalse(checker_evidence.get("summary_only", True))
                self.assertEqual(
                    checker_evidence.get("top_paths", [{}])[0].get("path"),
                    r"C:\repo\repositories\trunk\Cars_IDCevo\RollsRoyce\PINT_RR\_Placeholders\scripts\Logic_Placeholder_Hood.lua",
                )
                self.assertIn("tabbingcheck", checker_evidence.get("top_paths", [{}])[0].get("checkers", []))
                self.assertIn("luacheck", checker_evidence.get("top_paths", [{}])[0].get("checkers", []))

    def test_execute_scene_check_action_persists_file_backed_scene_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = create_temp_g65_profile(root)
            _create_checker_files(root)
            raco_exe = root / "tools" / "RaCoHeadless.exe"
            write_text(raco_exe, "fixture exe\n")

            scene_error_output = "\n".join(_checker_fixture("scene_check_error.log").splitlines()[1:]).strip()
            scene_clean_output = "\n".join(_checker_fixture("scene_check_clean.log").splitlines()[1:]).strip()

            with mock.patch.dict(
                os.environ,
                {
                    "SG_RACO_HEADLESS": str(raco_exe),
                    "SG_CARMODELS_REPO": str(root / "missing" / "digital-3d-car-models"),
                },
                clear=False,
            ):
                action = get_operator_action("scene_check__g65", root, profiles=[profile])
                with mock.patch(
                    "sg_preflight.qa_actions.subprocess.run",
                    side_effect=[
                        subprocess.CompletedProcess(
                            args=[str(raco_exe)],
                            returncode=1,
                            stdout=scene_error_output,
                            stderr="",
                        ),
                        subprocess.CompletedProcess(
                            args=[str(raco_exe)],
                            returncode=0,
                            stdout=scene_clean_output,
                            stderr="",
                        ),
                    ],
                ):
                    record = execute_operator_action(action, root)

            self.assertEqual(record.status, "completed")
            self.assertTrue(Path(record.paths["log"]).exists())
            self.assertTrue(Path(record.paths["xlsx_report"]).exists())
            self.assertIn("Scenes with errors: 1", " ".join(record.summary.get("lines", [])))
            self.assertIn("Open first:", " ".join(record.summary.get("lines", [])))
            checker_evidence = record.summary.get("checker_evidence", {})
            self.assertFalse(checker_evidence.get("summary_only", True))
            self.assertEqual(checker_evidence.get("checked_scenes"), 2)
            self.assertEqual(checker_evidence.get("scenes_with_errors"), 1)
            self.assertEqual(
                checker_evidence.get("top_paths", [{}])[0].get("path"),
                str(profile.project_root / "main.rca"),
            )
            affected = checker_evidence.get("affected_files", [{}])[0]
            self.assertIn("File Load Error", affected.get("message", ""))
            self.assertTrue(affected.get("workbook_sheet"))
            self.assertEqual(affected.get("workbook_row"), 2)

    def test_execute_unused_resource_action_persists_log_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = create_temp_g65_profile(root)
            _create_checker_files(root)
            action = get_operator_action("unused_resources__g65", root, profiles=[profile])

            sample_output = _checker_fixture("unused_resources_issue.log")

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
            self.assertEqual(record.summary.get("unused_count"), 2)
            self.assertIn("unused_diffuse.png", " ".join(record.summary.get("lines", [])))
            self.assertIn("Open first:", " ".join(record.summary.get("lines", [])))
            checker_evidence = record.summary.get("checker_evidence", {})
            self.assertFalse(checker_evidence.get("summary_only", True))
            self.assertEqual(
                checker_evidence.get("top_paths", [{}])[0].get("path"),
                r"C:\repo\repositories\trunk\Cars_IDCevo\BMW\G65\resources\shaders\orphan_shader.vert",
            )
            self.assertEqual(checker_evidence.get("checkers", [{}])[0].get("name"), "unused_resources")
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
            self.assertIn("Open first:", " ".join(record.summary.get("lines", [])))
            checker_evidence = record.summary.get("checker_evidence", {})
            self.assertFalse(checker_evidence.get("summary_only", True))
            self.assertTrue(
                str(checker_evidence.get("top_paths", [{}])[0].get("path", "")).endswith(
                    r"repositories\trunk\.pdx\checkers\deliveryChecklist\README.md"
                )
            )
            self.assertTrue(any("digital-3d-car-models" in item for item in checker_evidence.get("manual_followups", [])))
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
            checker_evidence = record.summary.get("checker_evidence", {})
            self.assertFalse(checker_evidence.get("summary_only", True))
            self.assertEqual(
                checker_evidence.get("top_paths", [{}])[0].get("path"),
                str(profile.project_root / "resources" / "textures" / "unused_diffuse.png"),
            )
            self.assertIn(
                "unused_resources",
                checker_evidence.get("top_paths", [{}])[0].get("checkers", []),
            )


if __name__ == "__main__":
    unittest.main()
