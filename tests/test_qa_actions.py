from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
import unittest
from unittest import mock

from sg_preflight.qa_actions import (
    BMW_SCREENSHOT_SMOKE_TIMEOUT_SECONDS,
    build_action_record,
    execute_operator_action,
    get_operator_action,
    list_operator_actions,
    load_action_record,
)
from tests.operator_helpers import create_temp_g65_profile, isolated_missing_external_dependencies, write_text


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


def _missing_bmw_repo_env(root: Path) -> dict[str, str]:
    missing = str(root / "missing" / "digital-3d-car-models")
    return {
        "SG_BMW_CAR_MODELS_ROOT": missing,
        "SG_CARMODELS_REPO": missing,
        "SG-CarModels-Repo": missing,
    }


class TestQaActions(unittest.TestCase):
    def test_sgfx_preflight_action_is_exact_profile_scoped_and_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = create_temp_g65_profile(root)
            actions = {item.action_id: item for item in list_operator_actions(root, profiles=[profile])}
            self.assertIn("sgfx_preflight__g65", actions)
            action = actions["sgfx_preflight__g65"]

        self.assertEqual(action.action_id, "sgfx_preflight__g65")
        self.assertEqual(action.label, "Run local QA checks")
        self.assertEqual(action.kind, "sgfx_preflight")
        self.assertEqual(action.scope, "profile")
        self.assertEqual(action.profile_id, "G65")
        self.assertTrue(action.ready)
        self.assertEqual(action.command_preview, "internal: run four deterministic SGFX packs")

    def test_execute_sgfx_preflight_calls_only_the_four_pack_service(self) -> None:
        from sg_preflight.services import RunRequest, build_run_record

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = create_temp_g65_profile(root)
            actions = {item.action_id: item for item in list_operator_actions(root, profiles=[profile])}
            self.assertIn("sgfx_preflight__g65", actions)
            action = actions["sgfx_preflight__g65"]
            parent = build_action_record(action, root)
            child_output = Path(parent.paths["output_root"]) / "preflight"
            child = build_run_record(
                profile,
                RunRequest(
                    profile_id=profile.profile_id,
                    packs=["anchors", "constants", "carpaints", "project_sanity"],
                    fail_on="never",
                    output_root=child_output,
                    run_id=f"{parent.run_id}-preflight",
                ),
                root,
            )
            child.status = "completed"
            child.exit_code = 0
            child.summary = {"errors": 0, "warnings": 1, "info": 2}
            for key in ("html_report", "markdown_report", "json_report", "run_record"):
                write_text(Path(child.paths[key]), f"fixture {key}\n")

            forbidden = (
                "_execute_profile_stack",
                "_execute_repo_checker",
                "_execute_unused_resources",
                "_execute_scene_check",
                "_execute_delivery_checklist",
                "_execute_bmw_screenshot_smoke",
                "_visual_review_prep_entries",
            )
            patches = [
                mock.patch(
                    f"sg_preflight.qa_actions.{name}",
                    side_effect=AssertionError(f"{name} must not run"),
                )
                for name in forbidden
            ]
            with ExitStack() as stack:
                execute = stack.enter_context(
                    mock.patch(
                        "sg_preflight.qa_actions.execute_profile_run",
                        return_value=child,
                    )
                )
                for patcher in patches:
                    stack.enter_context(patcher)
                record = execute_operator_action(action, root, record=parent)

        request = execute.call_args.args[1]
        self.assertEqual(request.packs, ["anchors", "constants", "carpaints", "project_sanity"])
        self.assertEqual(Path(request.output_root), child_output)
        self.assertEqual(record.status, "completed")
        self.assertEqual(record.summary["errors"], 0)
        self.assertEqual(record.summary["warnings"], 1)
        self.assertEqual(record.summary["info"], 2)
        self.assertEqual(record.summary["packs"], request.packs)
        self.assertTrue(
            all(
                Path(value).resolve().is_relative_to(Path(record.paths["output_root"]).resolve())
                for value in record.paths.values()
                if str(value).strip()
            )
        )

    def _two_stage_fixture(self, root: Path):
        from sg_preflight.services import RunRequest, build_run_record

        profile = create_temp_g65_profile(root)
        # Keep every path inside the temp root: the machine-wide reference checkout must never
        # be read from or written to by these tests.
        scene = profile.project_root / "export" / "exported.ramses"
        write_text(scene, "synthetic scene bytes")
        actions = {item.action_id: item for item in list_operator_actions(root, profiles=[profile])}
        action = actions["sgfx_preflight__g65"]
        parent = build_action_record(action, root)
        child = build_run_record(
            profile,
            RunRequest(
                profile_id=profile.profile_id,
                packs=["anchors", "constants", "carpaints", "project_sanity"],
                fail_on="never",
                output_root=Path(parent.paths["output_root"]) / "preflight",
                run_id=f"{parent.run_id}-preflight",
            ),
            root,
        )
        child.status = "completed"
        child.exit_code = 0
        child.summary = {"errors": 0, "warnings": 1, "info": 2}
        for key in ("html_report", "markdown_report", "json_report", "run_record"):
            write_text(Path(child.paths[key]), f"fixture {key}\n")
        return profile, scene, action, parent, child

    def test_preflight_reports_r0_unavailable_without_breaking_core(self) -> None:
        from sg_preflight.ramses_probe_runner import ProbeHelperReadiness

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile, scene, action, parent, child = self._two_stage_fixture(root)
            with ExitStack() as stack:
                stack.enter_context(mock.patch(
                    "sg_preflight.qa_actions.execute_profile_run", return_value=child))
                stack.enter_context(mock.patch(
                    "sg_preflight.profiles.configured_reference_repo_root",
                    return_value=root / "repositories" / "trunk"))
                stack.enter_context(mock.patch(
                    "sg_preflight.qa_actions.resolve_packaged_probe_helper",
                    return_value=ProbeHelperReadiness(
                        ready=False, reason="helper_not_packaged",
                        helper_path=None, helper_sha256="")))
                probe = stack.enter_context(mock.patch("sg_preflight.qa_actions.run_probe"))
                record = execute_operator_action(action, root, record=parent)
            probe.assert_not_called()
            self.assertEqual(record.status, "completed")
            self.assertEqual(record.summary["errors"], 0)
            self.assertEqual(record.summary["warnings"], 1)
            stage = record.summary["ramses_r0"]
            self.assertEqual(stage["family"], "unavailable")
            self.assertEqual(stage["reason"], "helper_not_packaged")

    def test_preflight_runs_the_packaged_probe_when_ready(self) -> None:
        from sg_preflight.ramses_probe_runner import ProbeHelperReadiness, ProbeRunResult

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile, scene, action, parent, child = self._two_stage_fixture(root)
            helper = root / "bundle" / "_internal" / "cpp" / "bin" / "sgfx_cine_ramses_probe.exe"
            write_text(helper, "helper bytes")

            def fake_run_probe(request):
                evidence = Path(request.output_root) / "ramses-r0-evidence.json"
                write_text(evidence, "{}")
                return ProbeRunResult(
                    outcome="completed", exit_code=0, rejections=(),
                    evidence_path=evidence,
                    native_report={"findings": [{"severity": "error"}, {"severity": "warning"}]},
                )

            with ExitStack() as stack:
                stack.enter_context(mock.patch(
                    "sg_preflight.qa_actions.execute_profile_run", return_value=child))
                stack.enter_context(mock.patch(
                    "sg_preflight.profiles.configured_reference_repo_root",
                    return_value=root / "repositories" / "trunk"))
                stack.enter_context(mock.patch(
                    "sg_preflight.qa_actions.resolve_packaged_probe_helper",
                    return_value=ProbeHelperReadiness(
                        ready=True, reason="", helper_path=helper, helper_sha256="a" * 64)))
                probe = stack.enter_context(mock.patch(
                    "sg_preflight.qa_actions.run_probe", side_effect=fake_run_probe))
                record = execute_operator_action(action, root, record=parent)

            request = probe.call_args.args[0]
            self.assertEqual(Path(request.scene_path).resolve(), scene.resolve())
            self.assertEqual(request.profile, "G65")
            self.assertEqual(request.helper_path, helper)
            run_dir = Path(request.output_root)
            self.assertTrue(run_dir.resolve().is_relative_to(
                Path(record.paths["output_root"]).resolve()))
            self.assertEqual(record.status, "completed")
            self.assertEqual(record.summary["errors"], 0)
            stage = record.summary["ramses_r0"]
            self.assertEqual(stage["family"], "evidence")
            self.assertEqual(stage["outcome"], "completed")
            self.assertEqual(stage["finding_errors"], 1)
            self.assertEqual(stage["finding_warnings"], 1)
            labels = [item.get("label", "") for item in record.artifacts]
            self.assertIn("Ramses probe evidence", labels)

    def test_probe_failure_never_fails_the_core_preflight(self) -> None:
        from sg_preflight.ramses_probe_runner import ProbeHelperReadiness, ProbeRunResult

        cases = (
            ("helper_crash", 3, "execution_failure"),
            ("worktree_status_changed", 0, "execution_failure"),
            ("scene_incompatible", 65, "evidence"),
            ("scene_unavailable", 65, "unavailable"),
        )
        for outcome, exit_code, family in cases:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                profile, scene, action, parent, child = self._two_stage_fixture(root)
                helper = root / "bundle" / "_internal" / "cpp" / "bin" / "probe.exe"
                write_text(helper, "helper bytes")
                result = ProbeRunResult(
                    outcome=outcome, exit_code=exit_code,
                    rejections=(outcome,) if family == "execution_failure" else (),
                    evidence_path=None, native_report=None)
                with ExitStack() as stack:
                    stack.enter_context(mock.patch(
                        "sg_preflight.qa_actions.execute_profile_run", return_value=child))
                    stack.enter_context(mock.patch(
                        "sg_preflight.qa_actions.resolve_packaged_probe_helper",
                        return_value=ProbeHelperReadiness(
                            ready=True, reason="", helper_path=helper, helper_sha256="a" * 64)))
                    stack.enter_context(mock.patch(
                        "sg_preflight.qa_actions.run_probe", return_value=result))
                    record = execute_operator_action(action, root, record=parent)
                self.assertEqual(record.status, "completed", outcome)
                self.assertEqual(record.summary["errors"], 0, outcome)
                self.assertEqual(record.summary["ramses_r0"]["family"], family, outcome)
                self.assertEqual(record.summary["ramses_r0"]["outcome"], outcome, outcome)

    def test_missing_scene_is_unavailable_and_probe_never_launches(self) -> None:
        from sg_preflight.ramses_probe_runner import ProbeHelperReadiness

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile, scene, action, parent, child = self._two_stage_fixture(root)
            scene.unlink()
            helper = root / "bundle" / "_internal" / "cpp" / "bin" / "probe.exe"
            write_text(helper, "helper bytes")
            with ExitStack() as stack:
                stack.enter_context(mock.patch(
                    "sg_preflight.qa_actions.execute_profile_run", return_value=child))
                stack.enter_context(mock.patch(
                    "sg_preflight.profiles.configured_reference_repo_root",
                    return_value=root / "repositories" / "trunk"))
                stack.enter_context(mock.patch(
                    "sg_preflight.qa_actions.resolve_packaged_probe_helper",
                    return_value=ProbeHelperReadiness(
                        ready=True, reason="", helper_path=helper, helper_sha256="a" * 64)))
                probe = stack.enter_context(mock.patch("sg_preflight.qa_actions.run_probe"))
                record = execute_operator_action(action, root, record=parent)
            probe.assert_not_called()
            self.assertEqual(record.status, "completed")
            stage = record.summary["ramses_r0"]
            self.assertEqual(stage["family"], "unavailable")
            self.assertEqual(stage["reason"], "scene_unavailable")

    def test_action_registry_marks_repo_checker_ready_and_scene_check_blocked_without_raco(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = create_temp_g65_profile(root)
            _create_checker_files(root)

            with isolated_missing_external_dependencies(root):
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
                    **_missing_bmw_repo_env(root),
                },
                clear=False,
            ):
                with mock.patch(
                    "sg_preflight.services.probe_raco_runtime",
                    return_value={
                        "status": "available",
                        "detail": "Synthetic runtime accepted for test execution.",
                        "probe_path": str(profile.project_root / "main.rca"),
                    },
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
                Path(checker_evidence.get("top_paths", [{}])[0].get("path", "")).resolve(),
                (profile.project_root / "main.rca").resolve(),
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

            with isolated_missing_external_dependencies(root):
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
                    **_missing_bmw_repo_env(root),
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

    def test_execute_daily_live_matrix_aggregates_child_checker_evidence(self) -> None:
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
                    **_missing_bmw_repo_env(root),
                },
                clear=False,
            ):
                action = get_operator_action("daily_live_matrix", root, profiles=[profile])

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

            self.assertEqual(record.status, "completed")
            lines = record.summary.get("lines", []) if record.summary else []
            self.assertTrue(any(line.startswith("G65: preflight") for line in lines))
            self.assertTrue(any(line.startswith("Open first:") for line in lines))
            checker_evidence = record.summary.get("checker_evidence", {})
            self.assertFalse(checker_evidence.get("summary_only", True))
            self.assertEqual(
                checker_evidence.get("top_paths", [{}])[0].get("path"),
                str(profile.project_root / "resources" / "textures" / "unused_diffuse.png"),
            )
            self.assertEqual(checker_evidence.get("source_kind"), "daily_live_matrix")

    def test_bmw_screenshot_smoke_timeout_persists_failed_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = replace(create_temp_g65_profile(root), bmw_smoke_target="G65_EVO")
            bmw_repo = root / "digital-3d-car-models"
            write_text(bmw_repo / "ci" / "scripts" / "car_manager.py", "print('fixture')\n")
            with mock.patch.dict(
                os.environ,
                {
                    "SG_BMW_CAR_MODELS_ROOT": str(bmw_repo),
                    "SG_CARMODELS_REPO": str(bmw_repo),
                    "SG-CarModels-Repo": str(bmw_repo),
                },
                clear=False,
            ):
                action = get_operator_action("bmw_screenshot_smoke__g65", root, profiles=[profile])
                record = build_action_record(action, root)
                log_path = Path(record.paths["log"])
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_path.write_text(
                    "step: prepare\nFAILURE: Build failed with an exception.\nstep: abort\n",
                    encoding="utf-8",
                )
                with mock.patch(
                    "sg_preflight.qa_actions.subprocess.run",
                    side_effect=subprocess.TimeoutExpired(cmd=["python"], timeout=BMW_SCREENSHOT_SMOKE_TIMEOUT_SECONDS),
                ) as run:
                    with self.assertRaisesRegex(RuntimeError, "timed out"):
                        execute_operator_action(action, root, record=record)

            saved = load_action_record(record.run_id, root)
            self.assertEqual(saved.status, "failed")
            self.assertEqual(saved.exit_code, 1)
            self.assertIn("timed out", saved.error_message)
            digest_notes = [note for note in saved.notes if note.startswith("Failure digest")]
            self.assertEqual(len(digest_notes), 1)
            self.assertIn("FAILURE: Build failed with an exception.", digest_notes[0])
            self.assertIn("line 2", digest_notes[0])
            self.assertEqual(run.call_args.kwargs["timeout"], BMW_SCREENSHOT_SMOKE_TIMEOUT_SECONDS)


if __name__ == "__main__":
    unittest.main()
