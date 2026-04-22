from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest import mock

from sg_preflight.profiles import RunProfile
from sg_preflight.qa_actions import (
    attach_manual_evidence,
    build_action_record,
    execute_operator_action,
    get_operator_action,
    save_action_record,
)
from sg_preflight.ticket_review import materialize_ticket_review_bundle
from tests.operator_helpers import write_text


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "checkers"
_PNG_FIXTURE = bytes.fromhex(
    "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C489"
    "0000000D49444154789C6360606060000000050001A5F645400000000049454E44AE426082"
)


def _checker_fixture(name: str) -> str:
    return (FIXTURE_ROOT / name).read_text(encoding="utf-8")


def _create_checker_files(root: Path) -> None:
    mirror_root = root / "repositories" / "trunk"
    repositories_root = root / "repositories"
    delivery_root = mirror_root / ".pdx" / "checkers" / "deliveryChecklist"
    testing_root = mirror_root / ".pdx" / "raco" / "scripts" / "testing"
    structure_root = mirror_root / ".pdx" / "raco" / "scripts" / "structure" / "scene_creation"
    res_root = mirror_root / ".pdx" / "raco" / "scripts" / "RES"
    log_root = mirror_root / ".pdx" / "raco" / "scripts" / "LOG"
    python_root = mirror_root / ".pdx" / "python"
    write_text(mirror_root / ".pdx" / "checkers" / "executeChecks.py", "print('checker stub')\n")
    write_text(mirror_root / ".pdx" / "checkers" / "checkall.bat", "@echo off\n")
    write_text(mirror_root / ".pdx" / "checkers" / "checkcars.bat", "@echo off\n")
    write_text(mirror_root / ".pdx" / "checkers" / "checkcars_IDCevo.bat", "@echo off\n")
    write_text(
        mirror_root / ".pdx" / "checkers" / "code_style_checker" / "check_all_styles.py",
        "print('style stub')\n",
    )
    write_text(mirror_root / ".pdx" / "checkers" / "printNotUsedResources.py", "print('unused stub')\n")
    write_text(mirror_root / "check_scenes.py", "print('scene stub')\n")
    write_text(delivery_root / "README.md", "delivery checklist fixture\n")
    write_text(delivery_root / "deliveryChecklist.py", "print('delivery checklist fixture')\n")
    write_text(delivery_root / "deliveryChecklist.exe", "fixture exe placeholder\n")
    write_text(delivery_root / "cameraCrane.lua", "-- fixture camera crane\n")
    write_text(python_root / "carmodel_data.json", "{\n  \"G65\": {}\n}\n")
    write_text(testing_root / "test_absolute_path.py", "print('absolute path stub')\n")
    write_text(testing_root / "test_ucap_ignore.py", "print('ucap ignore stub')\n")
    write_text(testing_root / "test_unused_lua_files.py", "print('unused lua stub')\n")
    write_text(testing_root / "resources_size_report.py", "print('resources size stub')\n")
    write_text(testing_root / "setup_perspective.py", "print('setup perspective stub')\n")
    write_text(testing_root / "read_json_carpaints.py", "print('carpaints stub')\n")
    write_text(testing_root / "variants_export.py", "print('variants export stub')\n")
    write_text(structure_root / "create_BMW_IDCevo_folderStructure.py", "print('create idcevo structure stub')\n")
    write_text(structure_root / "write_prefab_structure.py", "print('write prefab stub')\n")
    write_text(structure_root / "read_prefab_structure_IDCevo.py", "print('read prefab idcevo stub')\n")
    write_text(res_root / "update_RES.py", "print('update res stub')\n")
    write_text(log_root / "get_transforms.py", "print('get transforms stub')\n")
    write_text(mirror_root / ".pdx" / "raco" / "TestCarPaint" / "README.md", "test car paint fixture\n")
    write_text(
        mirror_root / ".pdx" / "raco" / "archive" / "PerspectiveTracePlayer" / "README.md",
        "trace player archive fixture\n",
    )
    write_text(repositories_root / "branches" / "G05_legacy" / "README.md", "legacy branch fixture\n")
    write_text(repositories_root / "delivery" / "README.md", "delivery root fixture\n")
    write_text(mirror_root / "Cars" / "BMW" / "_Shared" / "MatLib" / "README.md", "classic shared fixture\n")
    (mirror_root / "Cars").mkdir(parents=True, exist_ok=True)


def _create_profile(root: Path) -> RunProfile:
    repo_root = root / "repositories" / "trunk"
    project_relative = Path("Cars_IDCevo/BMW/G65")
    project_root = repo_root / project_relative
    write_text(root / "config" / "sg_rules_live_g65.json", "{\n  \"packs\": []\n}\n")
    write_text(project_root / "main" / "Main_G65.rca", "fixture rca\n")
    write_text(project_root / "_Workfiles" / "blender" / "G65_WheelFX.blend", "fixture blend\n")
    return RunProfile(
        profile_id="G65",
        label="BMW G65 test slice",
        repo_root=repo_root,
        project_root=project_root,
        project_relative=project_relative,
        config_path=root / "config" / "sg_rules_live_g65.json",
        default_context={"car_model": "G65"},
        reference_repo_root=repo_root,
    )


def _write_png_fixture(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_PNG_FIXTURE)


def _create_visual_review_files(root: Path, project_root: Path) -> None:
    write_text(
        project_root / "CHANGELOG.md",
        "\n".join(
            [
                "# Changelog",
                "",
                "## [1.0.1] - NOT YET DELIVERED",
                "- Updated welcome light animation timing",
                "- Adjusted front light mapping",
            ]
        )
        + "\n",
    )
    write_text(project_root / "_Common" / "constants" / "README_constants_G65.md", "constants review note\n")
    write_text(project_root / "export" / "tests" / "test_config.lua", "-- screenshot config\n")
    _write_png_fixture(project_root / "export" / "tests" / "expected" / "lights_drl_front.png")
    _write_png_fixture(project_root / "export" / "tests" / "expected" / "default.png")
    _write_png_fixture(project_root / "export" / "tests" / "results" / "lights_drl_front.png")
    shared_root = root / "repositories" / "trunk" / "Cars_IDCevo" / "BMW" / "_Shared_IDCevo"
    write_text(shared_root / "LightCones" / "README.md", "shared lightcones readme\n")
    write_text(shared_root / "LightCones" / "CHANGELOG.md", "## [1.0.0]\n- shared light change\n")
    write_text(shared_root / "RES_Common_LightCarpet" / "README.md", "shared carpet readme\n")


def _create_native_verification(root: Path) -> None:
    verification_root = root / "build" / "native-installer-fullscreen" / "verification" / "auto-fixture"
    write_text(verification_root / "verification.log", "verification fixture\n")
    write_text(verification_root / "backend-trace.log", "backend trace fixture\n")
    write_text(verification_root / "environment.png", "png fixture\n")


def _create_daily_snapshot_fixture(root: Path, profile_id: str) -> None:
    output_root = root / "out" / "daily-3d-car-qa-summary-fixture"
    output_root.mkdir(parents=True, exist_ok=True)
    fixture_root = root / "fixture" / "daily-snapshot"
    write_text(fixture_root / "config.log", "config fixture\n")
    write_text(fixture_root / f"{profile_id.lower()}-smoke.log", "Export finished\nFile sizes: Ramses=123456b RLogic=0b\n")
    write_text(fixture_root / f"{profile_id.lower()}-battery-default.log", "default battery fixture\n")
    write_text(fixture_root / f"{profile_id.lower()}-battery-lowbeam.log", "lowbeam proxy battery fixture\n")
    _write_png_fixture(fixture_root / profile_id.lower() / "default" / "tests" / "actuals" / "default.png")
    _write_png_fixture(
        fixture_root / profile_id.lower() / "lights_lowbeam" / "tests" / "proxy_actuals" / "lights_LowBeam_proxy.png"
    )
    write_text(output_root / "daily-3d-car-qa-summary.md", "# fixture snapshot\n")
    write_text(
        output_root / "review-priority-ranking.md",
        "# Screenshot Review Priority Ranking\n\n- G65: `default` -> `baseline_candidate_ready`\n",
    )
    write_text(
        output_root / "review-priority-ranking.json",
        '{\n  "ranked_items": [\n    {\n      "profile_id": "G65",\n      "filter_name": "default",\n      "verdict": "baseline_candidate_ready",\n      "priority_score": 70\n    }\n  ],\n  "top_five": []\n}\n',
    )
    write_text(
        output_root / "daily-qa-delta-summary.md",
        "# Daily QA Delta Summary\n\n- Current run: `2026-04-21T17:57:55`\n- Previous run: `none`\n",
    )
    write_text(
        output_root / "daily-qa-delta-summary.json",
        '{\n  "current_created_at": "2026-04-21T17:57:55",\n  "previous_created_at": "",\n  "new_failures": [],\n  "resolved_failures": [],\n  "new_screenshot_diffs": [],\n  "unchanged_blockers": [],\n  "changed_counts": {\n    "current": {\n      "baseline_candidate_ready": 1,\n      "proxy_candidate_ready": 1,\n      "smoke_completed": 1\n    },\n    "previous": {}\n  },\n  "top_five_to_review": []\n}\n',
    )
    write_text(
        output_root / "daily-3d-car-qa-summary.json",
        """
{
  "created_at": "2026-04-21T17:57:55",
  "scope_profiles": ["G65"],
  "bmw_repo_root": "C:/fixture/digital-3d-car-models",
  "config_check": {
    "status": "ready",
    "python_exe": "C:/fixture/python.exe",
    "repo_root": "C:/fixture/digital-3d-car-models",
    "log_path": "__CONFIG_LOG__",
    "output_excerpt": "",
    "error": ""
  },
  "smoke_results": [
    {
      "profile_id": "G65",
      "bmw_profile_id": "G65_EVO",
      "status": "completed",
      "smoke_test": "openAllDoors_rightView",
      "python_exe": "C:/fixture/python.exe",
      "sg_project_root": "C:/repositories/trunk/Cars_IDCevo/BMW/G65",
      "bmw_test_config_path": "C:/fixture/test_config_tmp.lua",
      "log_path": "__SMOKE_LOG__",
      "exported_ramses_size": 123456,
      "exported_rlogic_size": 0,
      "expected_count": 2,
      "actual_count": 2,
      "diff_count": 0,
      "compare_ok": true,
      "error": "",
      "notes": ["fixture smoke"]
    }
  ],
  "battery_results": [
    {
      "profile_id": "G65",
      "bmw_profile_id": "G65_EVO",
      "filter_name": "default",
      "verdict": "baseline_candidate_ready",
      "status": "completed",
      "results_root": "__DEFAULT_ROOT__",
      "log_path": "__DEFAULT_LOG__",
      "expected_count": 1,
      "actual_count": 1,
      "diff_count": 0,
      "compare_ok": true,
      "error": "",
      "missing_expected_baseline": "",
      "actual_files": ["default.png"],
      "expected_files": ["default.png"],
      "diff_files": [],
      "proxy_files": [],
      "target_output_present": true,
      "notes": ["fixture candidate"]
    },
    {
      "profile_id": "G65",
      "bmw_profile_id": "G65_EVO",
      "filter_name": "lights_LowBeam",
      "verdict": "proxy_candidate_ready",
      "status": "completed",
      "results_root": "__LOWBEAM_ROOT__",
      "log_path": "__LOWBEAM_LOG__",
      "expected_count": 0,
      "actual_count": 0,
      "diff_count": 0,
      "compare_ok": false,
      "error": "",
      "missing_expected_baseline": "lights_LowBeam.png",
      "actual_files": [],
      "expected_files": [],
      "diff_files": [],
      "proxy_files": ["lights_LowBeam_proxy.png"],
      "target_output_present": false,
      "notes": ["fixture proxy"]
    }
  ],
  "diagnostics": ["G65: exact cone rendering unresolved; low/high beam proxy coverage exists."],
  "blocked_steps": [],
  "top_review_items": ["G65: openAllDoors_rightView passed locally with no visible diff."],
  "notes": []
}
""".strip()
        .replace("__CONFIG_LOG__", str((fixture_root / "config.log").resolve()).replace("\\", "/"))
        .replace("__SMOKE_LOG__", str((fixture_root / f"{profile_id.lower()}-smoke.log").resolve()).replace("\\", "/"))
        .replace(
            "__DEFAULT_ROOT__",
            str((fixture_root / profile_id.lower() / "default").resolve()).replace("\\", "/"),
        )
        .replace(
            "__DEFAULT_LOG__",
            str((fixture_root / f"{profile_id.lower()}-battery-default.log").resolve()).replace("\\", "/"),
        )
        .replace(
            "__LOWBEAM_ROOT__",
            str((fixture_root / profile_id.lower() / "lights_lowbeam").resolve()).replace("\\", "/"),
        )
        .replace(
            "__LOWBEAM_LOG__",
            str((fixture_root / f"{profile_id.lower()}-battery-lowbeam.log").resolve()).replace("\\", "/"),
        )
        + "\n",
    )


class TestTicketReview(unittest.TestCase):
    def test_materialize_ticket_review_bundle_can_stay_scope_first_without_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _create_checker_files(root)
            result = materialize_ticket_review_bundle(
                "IDCEVODEV-977874",
                workspace=root,
                output_root=root / "out" / "IDCEVODEV-977874-review-package",
            )

            self.assertEqual(result.bundle.profile_ids, ())
            self.assertIn("No car/slice is confirmed locally yet", result.bundle.scope_note)
            review_text = result.review_status_path.read_text(encoding="utf-8")
            matrix_text = result.dod_matrix_path.read_text(encoding="utf-8")
            playbook_text = result.three_d_qa_playbook_path.read_text(encoding="utf-8")
            topology_text = result.repo_topology_reference_path.read_text(encoding="utf-8")
            surface_text = result.delivery_surface_map_path.read_text(encoding="utf-8")
            catalog_text = result.raco_script_catalog_path.read_text(encoding="utf-8")
            target_text = result.delivery_target_catalog_path.read_text(encoding="utf-8")
            self.assertIn("Profiles grounded locally: none confirmed", review_text)
            self.assertIn("No confirmed local slice is grounded yet", matrix_text)
            self.assertIn("No confirmed local slice is grounded yet", playbook_text)
            self.assertIn("Repo Topology Reference", topology_text)
            self.assertIn("Delivery Surface Map", surface_text)
            self.assertIn("RaCo Script Catalog", catalog_text)
            self.assertIn("Delivery Target Catalog", target_text)

    def test_materialize_ticket_review_bundle_generates_dod_matrix_and_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = _create_profile(root)
            _create_checker_files(root)
            _create_visual_review_files(root, profile.project_root)
            _create_native_verification(root)
            _create_daily_snapshot_fixture(root, "G65")

            delivery_action = get_operator_action("delivery_checklist__g65", root, profiles=[profile])
            repo_action = get_operator_action("repo_checker_profile__g65", root, profiles=[profile])

            with mock.patch.dict(
                os.environ,
                {"SG_CARMODELS_REPO": str(root / "missing" / "digital-3d-car-models")},
                clear=False,
            ):
                with mock.patch("sg_preflight.visual_review._run_svn", return_value=""):
                    execute_operator_action(delivery_action, root)

            with mock.patch("sg_preflight.visual_review._run_svn", return_value=""):
                with mock.patch(
                    "sg_preflight.qa_actions.subprocess.run",
                    side_effect=[
                        subprocess.CompletedProcess(
                            args=["python"],
                            returncode=1,
                            stdout=_checker_fixture("style_checker_issue.log"),
                            stderr="",
                        ),
                        subprocess.CompletedProcess(
                            args=["python"],
                            returncode=0,
                            stdout=_checker_fixture("execute_checks_issue.log"),
                            stderr="",
                        ),
                    ],
                ):
                    execute_operator_action(repo_action, root)

            result = materialize_ticket_review_bundle(
                "IDCEVODEV-960073",
                title="Quality-Hero: How to review the 3D car",
                profile_ids=("G65",),
                workspace=root,
                output_root=root / "out" / "IDCEVODEV-960073-review-package",
                scope_note="G65 is only the first concrete live-SVN slice, not confirmed final scope.",
                include_action_bundles=False,
            )

            self.assertTrue(result.review_status_path.exists())
            self.assertTrue(result.dod_matrix_path.exists())
            self.assertTrue(result.dod_update_draft_path.exists())
            self.assertTrue(result.teams_update_path.exists())
            self.assertTrue(result.stakeholder_sync_path.exists())
            self.assertTrue(result.review_protocol_path.exists())
            self.assertTrue(result.owner_matrix_path.exists())
            self.assertTrue(result.qa_capability_matrix_path.exists())
            self.assertTrue(result.three_d_qa_playbook_path.exists())
            self.assertTrue(result.repo_topology_reference_path.exists())
            self.assertTrue(result.delivery_surface_map_path.exists())
            self.assertTrue(result.raco_script_catalog_path.exists())
            self.assertTrue(result.delivery_target_catalog_path.exists())
            self.assertTrue(result.manual_review_companion_path.exists())
            self.assertTrue(result.manual_evidence_index_path.exists())
            self.assertTrue(result.manual_evidence_json_path.exists())
            self.assertTrue(result.review_owner_decisions_path.exists())
            self.assertTrue(result.sent_package_manifest_path.exists())
            self.assertTrue(result.zip_sha256_path.exists())
            self.assertTrue(result.zip_path.exists())

            item_map = {item.key: item for item in result.bundle.dod_items}
            self.assertEqual(item_map["format_checker_svn"].status, "covered_with_findings")
            self.assertEqual(item_map["screenshot_tests_bmws"].status, "partial")
            self.assertEqual(item_map["headless_export_check_bmw"].status, "covered")
            self.assertEqual(item_map["asset_review_in_raco_bmws"].status, "manual_ready")
            self.assertEqual(item_map["support"].status, "needs_scope")
            self.assertFalse(result.bundle.manual_evidence)

            self.assertTrue(any("process-definition task" in note for note in result.bundle.notes))
            self.assertTrue(result.bundle.findings)

            review_text = result.review_status_path.read_text(encoding="utf-8")
            matrix_text = result.dod_matrix_path.read_text(encoding="utf-8")
            dod_update_text = result.dod_update_draft_path.read_text(encoding="utf-8")
            teams_text = result.teams_update_path.read_text(encoding="utf-8")
            stakeholder_text = result.stakeholder_sync_path.read_text(encoding="utf-8")
            protocol_text = result.review_protocol_path.read_text(encoding="utf-8")
            owner_text = result.owner_matrix_path.read_text(encoding="utf-8")
            capability_text = result.qa_capability_matrix_path.read_text(encoding="utf-8")
            playbook_text = result.three_d_qa_playbook_path.read_text(encoding="utf-8")
            topology_text = result.repo_topology_reference_path.read_text(encoding="utf-8")
            surface_text = result.delivery_surface_map_path.read_text(encoding="utf-8")
            catalog_text = result.raco_script_catalog_path.read_text(encoding="utf-8")
            target_text = result.delivery_target_catalog_path.read_text(encoding="utf-8")
            manual_companion_text = result.manual_review_companion_path.read_text(encoding="utf-8")
            manual_index_text = result.manual_evidence_index_path.read_text(encoding="utf-8")
            decisions_text = result.review_owner_decisions_path.read_text(encoding="utf-8")
            manifest_text = result.sent_package_manifest_path.read_text(encoding="utf-8")
            sha256_text = result.zip_sha256_path.read_text(encoding="utf-8")

            self.assertIn("Concrete Findings", review_text)
            self.assertIn("Manual Evidence Rollup", review_text)
            self.assertIn("screenshot tests bmws", matrix_text)
            self.assertIn("Representative local BMW export proof is attached", matrix_text)
            self.assertIn("smoke `openAllDoors_rightView` -> passed locally with no visible diff", matrix_text)
            self.assertIn("Proposed clarified wording", dod_update_text)
            self.assertIn("What I still need from Adrian / Hristofor / Stefan", teams_text)
            self.assertIn("## Message For Jana", stakeholder_text)
            self.assertIn("Workflow steps", protocol_text)
            self.assertIn("Possible test cases from current local slices", protocol_text)
            self.assertIn("Packaged QA capability matrix", protocol_text)
            self.assertIn("Packaged repo topology reference", protocol_text)
            self.assertIn("Packaged delivery surface map", protocol_text)
            self.assertIn("Packaged RaCo script catalog", protocol_text)
            self.assertIn("Packaged delivery target catalog", protocol_text)
            self.assertIn("Owner hint", owner_text)
            self.assertIn("SG repo scenes checker", capability_text)
            self.assertIn("resources_size_report.py", capability_text)
            self.assertIn("archive\\PerspectiveTracePlayer", capability_text)
            self.assertIn("blocked by BMW access", capability_text)
            self.assertIn("Confluence-derived 3D test catalog", playbook_text)
            self.assertIn("Blender visual check", playbook_text)
            self.assertIn("What still stays BMW-side", playbook_text)
            self.assertIn("C:\\", topology_text)
            self.assertIn("branches", topology_text)
            self.assertIn("delivery", topology_text)
            self.assertIn("Cars\\BMW\\_Shared", topology_text)
            self.assertIn("Cars_IDCevo\\BMW\\_Shared_IDCevo", topology_text)
            self.assertIn("G05_legacy", topology_text)
            self.assertIn("blocked", surface_text)
            self.assertIn("digital-3d-car-models", surface_text)
            self.assertIn("headless", surface_text)
            self.assertIn("screenshot", surface_text)
            self.assertIn(".pdx\\python\\carmodel_data.json", catalog_text)
            self.assertIn("create_BMW_IDCevo_folderStructure.py", catalog_text)
            self.assertIn("read_prefab_structure_IDCevo.py", catalog_text)
            self.assertIn("update_RES.py", catalog_text)
            self.assertIn("get_transforms.py", catalog_text)
            self.assertIn("PerspectiveTracePlayer", catalog_text)
            self.assertIn("variant_export.py", catalog_text)
            self.assertIn("variants_export.py", catalog_text)
            self.assertIn("climate-app", target_text)
            self.assertIn("perso-app", target_text)
            self.assertIn("ambient-layer-assets", target_text)
            self.assertIn("CCP MINI / CCP BMW / CCP CN LLN", target_text)
            self.assertIn("Krister - 3D_Assets_Sizes.xlsm", target_text)
            self.assertIn("Manual review record", manual_companion_text)
            self.assertIn("Total attached evidence items: 0", manual_index_text)
            self.assertIn("# Review-owner decisions", decisions_text)
            self.assertIn("## lights_OnlyCones", decisions_text)
            self.assertIn("# SENT PACKAGE MANIFEST", manifest_text)
            self.assertIn("IDCEVODEV-960073", manifest_text)
            self.assertIn(result.zip_path.name, manifest_text)
            self.assertIn(result.zip_path.name, sha256_text)

            self.assertTrue(any("screenshot triage" in evidence.label.lower() for evidence in item_map["screenshot_tests_bmws"].evidence))
            self.assertTrue(any("screenshot test config" in evidence.label.lower() for evidence in item_map["screenshot_tests_bmws"].evidence))
            self.assertTrue(any("screenshot evidence slots" in evidence.label.lower() for evidence in item_map["screenshot_tests_bmws"].evidence))
            self.assertTrue(any("manual review record" in evidence.label.lower() for evidence in item_map["asset_review_in_raco_bmws"].evidence))
            self.assertTrue(any("qa capability matrix" in evidence.label.lower() for evidence in item_map["support"].evidence))
            self.assertTrue(any("3d qa playbook" in evidence.label.lower() for evidence in item_map["support"].evidence))
            self.assertTrue(any("repo topology reference" in evidence.label.lower() for evidence in item_map["support"].evidence))
            self.assertTrue(any("delivery surface map" in evidence.label.lower() for evidence in item_map["support"].evidence))
            self.assertTrue(any("raco script catalog" in evidence.label.lower() for evidence in item_map["support"].evidence))
            self.assertTrue(any("delivery target catalog" in evidence.label.lower() for evidence in item_map["support"].evidence))
            self.assertFalse(any("delivery blocker" in evidence.label.lower() for evidence in item_map["support"].evidence))
            self.assertFalse(any("repo checker summary" in evidence.label.lower() for evidence in item_map["format_checker_svn"].evidence))
            self.assertTrue(any(evidence.label == "CHANGELOG.md" for evidence in result.bundle.evidence_index))
            self.assertTrue(
                (result.package_root / "artifacts" / "manual-review" / "g65" / "manual-review-record.md").exists()
            )
            self.assertFalse((result.package_root / "artifacts" / "verification").exists())

            packaged_snapshot_root = result.package_root / "artifacts" / "daily-snapshot"
            packaged_gallery = packaged_snapshot_root / "candidate-review-gallery.html"
            packaged_gallery_text = packaged_gallery.read_text(encoding="utf-8")
            self.assertTrue(packaged_gallery.exists())
            self.assertNotIn("file:///", packaged_gallery_text)
            self.assertIn('src="images/g65/default/tests/actuals/default.png"', packaged_gallery_text)
            self.assertIn(
                'src="images/g65/lights_lowbeam/tests/proxy_actuals/lights_LowBeam_proxy.png"',
                packaged_gallery_text,
            )
            self.assertTrue((packaged_snapshot_root / "logs" / "config.log").exists())
            self.assertTrue((packaged_snapshot_root / "logs" / "g65-smoke.log").exists())
            self.assertTrue((packaged_snapshot_root / "logs" / "g65-battery-default.log").exists())
            self.assertTrue((packaged_snapshot_root / "logs" / "g65-battery-lowbeam.log").exists())
            self.assertTrue((packaged_snapshot_root / "review-priority-ranking.md").exists())
            self.assertTrue((packaged_snapshot_root / "review-priority-ranking.json").exists())
            self.assertTrue((packaged_snapshot_root / "daily-qa-delta-summary.md").exists())
            self.assertTrue((packaged_snapshot_root / "daily-qa-delta-summary.json").exists())
            self.assertTrue((packaged_snapshot_root / "images" / "g65" / "default" / "tests" / "actuals" / "default.png").exists())
            self.assertTrue(
                (
                    packaged_snapshot_root
                    / "images"
                    / "g65"
                    / "lights_lowbeam"
                    / "tests"
                    / "proxy_actuals"
                    / "lights_LowBeam_proxy.png"
                ).exists()
            )
            self.assertFalse((result.package_root / "artifacts" / "actions").exists())
            self.assertFalse(
                (result.package_root / "artifacts" / "screenshot-triage" / "g65" / "screenshot-triage.html").exists()
            )
            self.assertIn("artifacts/daily-snapshot/logs/g65-smoke.log", matrix_text)
            self.assertIn("artifacts/daily-snapshot/logs/g65-battery-default.log", matrix_text)
            self.assertIn("artifacts/daily-snapshot/logs/g65-battery-lowbeam.log", matrix_text)
            self.assertIn("review-priority-ranking.md", matrix_text)
            self.assertIn("daily-qa-delta-summary.md", matrix_text)
            self.assertNotIn("digital-3d-car-models/ci/scripts/car_manager.py", matrix_text)

    def test_materialize_ticket_review_bundle_harvests_manual_evidence_from_blocked_scene_check(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = _create_profile(root)
            _create_checker_files(root)
            _create_visual_review_files(root, profile.project_root)

            scene_action = get_operator_action("scene_check__g65", root, profiles=[profile])
            scene_record = execute_operator_action(scene_action, root)
            self.assertEqual(scene_record.status, "blocked")

            screenshot_source = root / "notes" / "g65-manual-shot.png"
            _write_png_fixture(screenshot_source)
            attach_manual_evidence(
                scene_record.run_id,
                root,
                kind="screenshot",
                label="G65 manual screenshot",
                source_path=str(screenshot_source),
            )
            attach_manual_evidence(
                scene_record.run_id,
                root,
                kind="raco_note",
                label="G65 RaCo note",
                note="Scene checked: welcome light carpet",
            )
            attach_manual_evidence(
                scene_record.run_id,
                root,
                kind="visual_review_checklist",
                label="G65 visual checklist",
                note="Project changelog reviewed: [x]",
            )

            result = materialize_ticket_review_bundle(
                "IDCEVODEV-960073",
                title="Quality-Hero: How to review the 3D car",
                profile_ids=("G65",),
                workspace=root,
                output_root=root / "out" / "IDCEVODEV-960073-review-package",
                scope_note="G65 is only the first concrete live-SVN slice, not confirmed final scope.",
            )

            item_map = {item.key: item for item in result.bundle.dod_items}
            self.assertEqual(item_map["screenshot_tests_bmws"].status, "partial")
            self.assertEqual(item_map["asset_review_in_raco_bmws"].status, "partial")
            self.assertEqual(len(result.bundle.manual_evidence), 3)
            self.assertTrue(any(item.source_action_id == "scene_check__g65" for item in result.bundle.manual_evidence))

            review_text = result.review_status_path.read_text(encoding="utf-8")
            protocol_text = result.review_protocol_path.read_text(encoding="utf-8")
            teams_text = result.teams_update_path.read_text(encoding="utf-8")
            manual_index_payload = result.manual_evidence_json_path.read_text(encoding="utf-8")

            self.assertIn("screenshot=1", review_text)
            self.assertIn("raco_note=1", review_text)
            self.assertIn("desktop-state attach-manual-evidence", protocol_text)
            self.assertIn(scene_record.run_id, protocol_text)
            self.assertIn("counts by kind: raco_note=1, screenshot=1, visual_review_checklist=1", teams_text)
            self.assertIn('"source_action_id": "scene_check__g65"', manual_index_payload)
            self.assertTrue(
                any("Ticket manual evidence index" in evidence.label for evidence in item_map["support"].evidence)
            )
            self.assertTrue(
                any("raco_note" in evidence.label for evidence in item_map["asset_review_in_raco_bmws"].evidence)
            )
            self.assertTrue(
                (result.package_root / "artifacts" / "manual-evidence" / "g65" / scene_record.run_id).exists()
            )

    def test_materialize_ticket_review_bundle_dedupes_shared_manual_evidence_across_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = _create_profile(root)
            _create_checker_files(root)
            _create_visual_review_files(root, profile.project_root)

            shared_evidence = root / "shared" / "manual-proof.png"
            _write_png_fixture(shared_evidence)

            scene_action = get_operator_action("scene_check__g65", root, profiles=[profile])
            scene_record = build_action_record(scene_action, root)
            scene_record.status = "blocked"
            scene_record.manual_evidence = [
                {
                    "id": "scene-manual-proof",
                    "kind": "screenshot",
                    "label": "Shared screenshot proof",
                    "path": str(shared_evidence),
                    "note": "",
                    "created_at_utc": "2026-04-21T00:00:00+00:00",
                }
            ]
            save_action_record(scene_record)

            stack_action = get_operator_action("qa_stack__g65", root, profiles=[profile])
            stack_record = build_action_record(stack_action, root)
            stack_record.status = "completed"
            stack_record.manual_evidence = [
                {
                    "id": "stack-manual-proof",
                    "kind": "screenshot",
                    "label": "Shared screenshot proof",
                    "path": str(shared_evidence),
                    "note": "",
                    "created_at_utc": "2026-04-21T00:01:00+00:00",
                }
            ]
            save_action_record(stack_record)

            result = materialize_ticket_review_bundle(
                "IDCEVODEV-960073",
                title="Quality-Hero: How to review the 3D car",
                profile_ids=("G65",),
                workspace=root,
                output_root=root / "out" / "IDCEVODEV-960073-review-package",
            )

            self.assertEqual(len(result.bundle.manual_evidence), 1)
            json_payload = result.manual_evidence_json_path.read_text(encoding="utf-8")
            self.assertEqual(json_payload.count("Shared screenshot proof"), 1)
            copied_files = list((result.package_root / "artifacts" / "manual-evidence" / "g65").rglob("manual-proof.png"))
            self.assertEqual(len(copied_files), 1)


if __name__ == "__main__":
    unittest.main()
