from __future__ import annotations

import os
import tempfile
from pathlib import Path
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from sg_preflight.models import Finding, PackResult, Report
from sg_preflight.profiles import RunProfile
from sg_preflight.qa_actions import (
    ACTION_PROGRESS_PLANS,
    build_action_record,
    get_operator_action,
    save_action_record as save_action_task_record,
)
from sg_preflight.reporting import write_html_report
from sg_preflight.services import (
    RUN_PROGRESS_PLAN,
    RunRequest,
    build_progress_payload,
    build_run_record,
    save_run_record,
)
from sg_preflight.ui import create_app
from tests.operator_helpers import create_temp_g65_profile, write_text

ROOT = Path(__file__).resolve().parents[1]


class TestOperatorUI(unittest.TestCase):
    def test_home_and_run_pages_render_profile_information(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = create_temp_g65_profile(root)
            sibling_profiles = [
                RunProfile(
                    profile_id="G70",
                    label="BMW G70 test slice",
                    repo_root=profile.repo_root,
                    project_root=profile.project_root,
                    config_path=profile.config_path,
                    default_context=profile.default_context,
                    description=profile.description,
                    operator_goal=profile.operator_goal,
                    workflow_value=profile.workflow_value,
                    friendly_task="Find obvious delivery issues",
                    friendly_summary="Synthetic G70 fixture for guided operator tests.",
                    focus_points=profile.focus_points,
                    mirror_audit_targets=profile.mirror_audit_targets,
                    reference_repo_root=profile.reference_repo_root,
                ),
                RunProfile(
                    profile_id="G45",
                    label="BMW G45 test slice",
                    repo_root=profile.repo_root,
                    project_root=profile.project_root,
                    config_path=profile.config_path,
                    default_context=profile.default_context,
                    description=profile.description,
                    operator_goal=profile.operator_goal,
                    workflow_value=profile.workflow_value,
                    friendly_task="Check anchor setup",
                    friendly_summary="Synthetic G45 fixture for guided operator tests.",
                    focus_points=profile.focus_points,
                    mirror_audit_targets=profile.mirror_audit_targets,
                    reference_repo_root=profile.reference_repo_root,
                ),
            ]
            with mock.patch.dict(
                os.environ,
                {"SG_CARMODELS_REPO": str(root / "missing" / "digital-3d-car-models")},
                clear=False,
            ):
                with mock.patch("sg_preflight.services.shutil.which", return_value=None):
                    client = TestClient(create_app(root=root, profiles=[profile, *sibling_profiles]))

                    home = client.get("/ui")
                    stage_view = client.get("/ui/stages/pre_delivery")
                    guided = client.get("/ui/start/constants")
                    stage_guided = client.get("/ui/start/constants?stage=before_commit")
                    run_view = client.get("/ui/profiles/G65")
                    guided_run_view = client.get("/ui/profiles/G65?job=constants")
                    staged_run_view = client.get("/ui/profiles/G65?job=constants&stage=before_commit")

        self.assertEqual(home.status_code, 200)
        self.assertIn("Start here: what changed?", home.text)
        self.assertIn("I changed constants", home.text)
        self.assertIn("If the workflow stage matters", home.text)
        self.assertIn("Before commit", home.text)
        self.assertIn("Check one car, open the right file, and copy the proof.", home.text)
        self.assertIn('href="#change-type-start"', home.text)
        self.assertIn("Pick the change type first.", home.text)
        self.assertIn("Best current start: G65", home.text)
        self.assertIn("Show more tools, direct car picks, and recent checks", home.text)
        self.assertIn("Pick a car directly", home.text)
        self.assertIn("Check all live cars", home.text)
        self.assertIn("BMW G65 test slice", home.text)
        self.assertIn("If you need more detail", home.text)
        self.assertIn("Show workflow fit and blockers", home.text)
        self.assertIn("What is this for?", home.text)
        self.assertIn("Light mode", home.text)
        self.assertIn("Hide guide", home.text)
        self.assertEqual(stage_view.status_code, 200)
        self.assertIn("What this stage needs", stage_view.text)
        self.assertIn("Performance tests and delivery documentation", stage_view.text)
        self.assertIn("Start from the kind of change", stage_view.text)
        self.assertEqual(guided.status_code, 200)
        self.assertIn("Use this car first", guided.text)
        self.assertIn("Run constants check for G65", guided.text)
        self.assertIn("Other cars", guided.text)
        self.assertIn("Recommended", guided.text)
        self.assertEqual(stage_guided.status_code, 200)
        self.assertIn("Use this after implementation and before any commit", stage_guided.text)
        self.assertEqual(run_view.status_code, 200)
        self.assertIn('href="#run-now"', run_view.text)
        self.assertIn('id="run-now"', run_view.text)
        self.assertIn("Run full check for this car", run_view.text)
        self.assertIn("Files this check will use", run_view.text)
        self.assertIn("Show a smaller quick check", run_view.text)
        self.assertIn("Show other actions", run_view.text)
        self.assertIn("Run BMW screenshot smoke for G65", run_view.text)
        self.assertEqual(guided_run_view.status_code, 200)
        self.assertIn("Constants check", guided_run_view.text)
        self.assertIn("Run constants check for this car", guided_run_view.text)
        self.assertNotIn("Run full check instead", guided_run_view.text)
        self.assertEqual(staged_run_view.status_code, 200)
        self.assertIn("Use this after implementation and before any commit", staged_run_view.text)

    def test_run_result_and_evidence_pages_render_grouped_findings_and_links(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = create_temp_g65_profile(root)
            (profile.repo_root / "Cars_IDCevo" / "BMW" / "G70").mkdir(parents=True, exist_ok=True)
            main_rca = profile.project_root / "main.rca"
            main_rca.write_text(
                main_rca.read_text(encoding="utf-8")
                + "shared=/../../G70/_Common/interfaces/Link_Common_Variants.lua\n",
                encoding="utf-8",
            )
            (profile.project_root / "logic" / "unused_debug.lua").write_text(
                "-- intentionally unused\n",
                encoding="utf-8",
            )
            client = TestClient(create_app(root=root, profiles=[profile]))

            create_response = client.post(
                "/ui/api/runs",
                json={
                    "profile_id": "G65",
                    "packs": ["anchors", "constants", "carpaints", "project_sanity"],
                    "fail_on": "never",
                    "context": {
                        **profile.default_context,
                        "workflow_stage": "pre_delivery",
                        "workflow_stage_label": "Pre-delivery",
                    },
                },
            )
            self.assertEqual(create_response.status_code, 202)
            payload = create_response.json()

            result_page = client.get(payload["result_url"])
            evidence_page = client.get(payload["result_url"] + "/evidence")

        self.assertEqual(result_page.status_code, 200)
        self.assertIn('href="#first-thing-to-do"', result_page.text)
        self.assertIn('id="copy-ready-notes"', result_page.text)
        self.assertIn("First thing to do", result_page.text)
        self.assertIn("Copy handoff for this problem", result_page.text)
        self.assertIn("Copy finding", result_page.text)
        self.assertIn("Show all grouped problems", result_page.text)
        self.assertIn("TA / pipeline / integration owner", result_page.text)
        self.assertIn("Confirm whether the Lua file is intentionally unused", result_page.text)
        self.assertIn("Source file", result_page.text)
        self.assertIn("Lua source", result_page.text)
        self.assertIn("Stage readiness", result_page.text)
        self.assertIn("Evidence completeness", result_page.text)
        self.assertIn("Stage-specific exports", result_page.text)
        self.assertIn("Manual review companion", result_page.text)
        self.assertIn("Copy pre-delivery summary", result_page.text)
        self.assertIn("Copy delivery handoff", result_page.text)
        self.assertIn("Copy Jira implementation update", result_page.text)
        self.assertIn("Copy delivery-doc snippet", result_page.text)
        self.assertIn("Copy manual review record", result_page.text)
        self.assertIn("Performance tests and delivery documentation", result_page.text)
        self.assertEqual(evidence_page.status_code, 200)
        self.assertIn('href="#stage-exports"', evidence_page.text)
        self.assertIn('id="files-proof"', evidence_page.text)
        self.assertIn("Pinned first file", evidence_page.text)
        self.assertIn("Reports", evidence_page.text)
        self.assertIn("Source-of-truth files", evidence_page.text)
        self.assertIn("Run metadata", evidence_page.text)
        self.assertIn("Stage readiness", evidence_page.text)
        self.assertIn("Evidence completeness", evidence_page.text)
        self.assertIn("Stage-specific exports", evidence_page.text)
        self.assertIn("Manual review companion", evidence_page.text)
        self.assertIn("Copy screenshot evidence slots", evidence_page.text)

    def test_guided_run_carries_plain_language_job_label_into_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = create_temp_g65_profile(root)
            client = TestClient(create_app(root=root, profiles=[profile]))

            create_response = client.post(
                "/ui/api/runs",
                json={
                    "profile_id": "G65",
                    "packs": ["constants"],
                    "fail_on": "never",
                    "context": {
                        "operator_job": "constants",
                        "operator_job_label": "Constants check",
                        "workflow_stage": "evidence_update",
                        "workflow_stage_label": "Evidence update",
                    },
                },
            )
            self.assertEqual(create_response.status_code, 202)
            payload = create_response.json()
            result_page = client.get(payload["result_url"])
            evidence_page = client.get(payload["result_url"] + "/evidence")

        self.assertEqual(result_page.status_code, 200)
        self.assertIn("Evidence update - Constants check on G65", result_page.text)
        self.assertIn("Copy positive test note", result_page.text)
        self.assertIn("Copy Jira update", result_page.text)
        self.assertIn("Copy QA Hero note", result_page.text)
        self.assertIn("Copy Jira implementation update", result_page.text)
        self.assertIn("Copy Jira negative test note", result_page.text)
        self.assertIn("Stage readiness", result_page.text)
        self.assertIn("You are done when...", result_page.text)
        self.assertEqual(evidence_page.status_code, 200)
        self.assertIn("Attach the result in the real ticket", evidence_page.text)

    def test_result_page_shows_diff_against_previous_completed_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = create_temp_g65_profile(root)
            client = TestClient(create_app(root=root, profiles=[profile]))

            first_response = client.post(
                "/ui/api/runs",
                json={
                    "profile_id": "G65",
                    "packs": ["anchors", "constants", "carpaints", "project_sanity"],
                    "fail_on": "never",
                    "context": profile.default_context,
                },
            )
            self.assertEqual(first_response.status_code, 202)

            (profile.project_root / "logic" / "unused_debug.lua").write_text(
                "-- intentionally unused\n",
                encoding="utf-8",
            )

            second_response = client.post(
                "/ui/api/runs",
                json={
                    "profile_id": "G65",
                    "packs": ["anchors", "constants", "carpaints", "project_sanity"],
                    "fail_on": "never",
                    "context": profile.default_context,
                },
            )
            self.assertEqual(second_response.status_code, 202)
            second_page = client.get(second_response.json()["result_url"])

        self.assertEqual(second_page.status_code, 200)
        self.assertIn("Changed since last check", second_page.text)
        self.assertIn("New findings", second_page.text)
        self.assertIn("Copy diff update", second_page.text)

    def test_running_result_page_renders_live_progress_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = create_temp_g65_profile(root)
            client = TestClient(create_app(root=root, profiles=[profile]))

            record = build_run_record(
                profile,
                RunRequest(profile_id="G65"),
                root,
            )
            record.status = "running"
            record.started_at_utc = "2026-04-16T08:00:00+00:00"
            record.progress = build_progress_payload(
                RUN_PROGRESS_PLAN,
                step_key="manifest_paths",
                percent=62,
                label="Scanning path references",
                detail="Reading SG files for absolute, relative, and cross-car references.",
            )
            save_run_record(record)

            page = client.get(f"/ui/runs/{record.run_id}")

        self.assertEqual(page.status_code, 200)
        self.assertIn("Scanning path references", page.text)
        self.assertIn("NOW LOADING...", page.text)

    def test_status_apis_surface_progress_events_and_action_log_tail(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = create_temp_g65_profile(root)
            client = TestClient(create_app(root=root, profiles=[profile]))

            run_record = build_run_record(
                profile,
                RunRequest(profile_id="G65"),
                root,
            )
            run_record.status = "running"
            run_record.started_at_utc = "2026-04-16T08:00:00+00:00"
            run_record.progress = build_progress_payload(
                RUN_PROGRESS_PLAN,
                step_key="validate_constants",
                percent=79,
                label="Validating constants",
                detail="Running the `constants` validator against the materialized SG bundle.",
                events=[
                    {
                        "timestamp_utc": "2026-04-16T08:00:01+00:00",
                        "step_key": "constants_expected",
                        "label": "Reading expected constants",
                        "detail": "Normalizing G65_Pivot_Master.json.",
                    },
                    {
                        "timestamp_utc": "2026-04-16T08:00:02+00:00",
                        "step_key": "validate_constants",
                        "label": "Validating constants",
                        "detail": "Running the `constants` validator against the materialized SG bundle.",
                    },
                ],
            )
            save_run_record(run_record)

            action = get_operator_action("daily_live_matrix", root, profiles=[profile])
            action_record = build_action_record(action, root)
            action_record.status = "running"
            action_record.started_at_utc = "2026-04-16T08:00:00+00:00"
            action_record.progress = build_progress_payload(
                ACTION_PROGRESS_PLANS[action.kind],
                step_key="profiles",
                percent=40,
                label="Running G65",
                detail="Live matrix 1/1: materializing and validating G65.",
                events=[
                    {
                        "timestamp_utc": "2026-04-16T08:00:01+00:00",
                        "step_key": "profiles",
                        "label": "Running live profile matrix",
                        "detail": "Preparing 1 live profile run(s).",
                    }
                ],
            )
            write_text(Path(action_record.paths["log"]), "line 1\nline 2\nline 3\n")
            save_action_task_record(action_record)

            run_status = client.get(f"/ui/api/runs/{run_record.run_id}")
            action_status = client.get(f"/ui/api/actions/{action_record.run_id}")

        self.assertEqual(run_status.status_code, 200)
        run_payload = run_status.json()
        self.assertIn("progress", run_payload)
        self.assertEqual(run_payload["progress"]["label"], "Validating constants")
        self.assertEqual(len(run_payload["progress"]["events"]), 2)
        self.assertEqual(run_payload["progress"]["events"][0]["step_key"], "constants_expected")
        self.assertEqual(run_payload["progress"]["step_details"][0]["key"], "queued")
        self.assertEqual(run_payload["live_log_tail"], [])

        self.assertEqual(action_status.status_code, 200)
        action_payload = action_status.json()
        self.assertEqual(action_payload["progress"]["label"], "Running G65")
        self.assertEqual(action_payload["progress"]["events"][0]["step_key"], "profiles")
        self.assertEqual(action_payload["live_log_tail"], ["line 1", "line 2", "line 3"])

    def test_blocked_action_can_be_started_and_rendered(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = create_temp_g65_profile(root)
            client = TestClient(create_app(root=root, profiles=[profile]))

            response = client.post("/ui/api/actions", json={"action_id": "scene_check__g65"})
            self.assertEqual(response.status_code, 202)
            payload = response.json()
            result_page = client.get(payload["result_url"])

        self.assertEqual(result_page.status_code, 200)
        self.assertIn("This automation is blocked here", result_page.text)
        self.assertIn("Scene check needs both the mirrored", result_page.text)
        self.assertIn("Do this next", result_page.text)
        self.assertNotIn("Raw log", result_page.text)

    def test_completed_and_failed_action_pages_render_plain_language_states(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = create_temp_g65_profile(root)
            client = TestClient(create_app(root=root, profiles=[profile]))

            completed_action = get_operator_action("daily_live_matrix", root, profiles=[profile])
            completed_record = build_action_record(completed_action, root)
            completed_record.status = "completed"
            completed_record.summary = {
                "title": "Daily SG Check",
                "lines": [
                    "G65: 0 errors, 1 warnings, 0 info",
                    "Open the summary markdown if you need to hand this off.",
                ],
            }
            write_text(Path(completed_record.paths["log"]), "completed\n")
            save_action_task_record(completed_record)

            failed_action = get_operator_action("daily_live_matrix", root, profiles=[profile])
            failed_record = build_action_record(failed_action, root)
            failed_record.status = "failed"
            failed_record.error_message = "synthetic failure"
            write_text(Path(failed_record.paths["log"]), "failed\n")
            save_action_task_record(failed_record)

            completed_page = client.get(f"/ui/actions/{completed_record.run_id}")
            failed_page = client.get(f"/ui/actions/{failed_record.run_id}")

        self.assertEqual(completed_page.status_code, 200)
        self.assertIn("This automation finished", completed_page.text)
        self.assertIn("Open this now", completed_page.text)
        self.assertIn("Show all generated files", completed_page.text)
        self.assertIn("Raw log", completed_page.text)
        self.assertEqual(failed_page.status_code, 200)
        self.assertIn("This automation failed before completion", failed_page.text)
        self.assertIn("synthetic failure", failed_page.text)
        self.assertIn("Open the action log first.", failed_page.text)

    def test_running_action_page_renders_live_progress_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = create_temp_g65_profile(root)
            client = TestClient(create_app(root=root, profiles=[profile]))

            action = get_operator_action("daily_live_matrix", root, profiles=[profile])
            record = build_action_record(action, root)
            record.status = "running"
            record.started_at_utc = "2026-04-16T08:00:00+00:00"
            record.progress = build_progress_payload(
                ACTION_PROGRESS_PLANS[action.kind],
                step_key="profiles",
                percent=40,
                label="Running G65",
                detail="Live matrix 1/1: materializing and validating G65.",
            )
            save_action_task_record(record)

            page = client.get(f"/ui/actions/{record.run_id}")

        self.assertEqual(page.status_code, 200)
        self.assertIn("Running G65", page.text)
        self.assertIn("NOW LOADING...", page.text)

    def test_file_route_rethemes_generated_html_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = create_temp_g65_profile(root)
            client = TestClient(create_app(root=root, profiles=[profile]))

            report = Report(
                bundle="demo://bundle",
                context={"car_model": "G65", "delivery_phase": "preview"},
                packs=[
                    PackResult(
                        pack="project_sanity",
                        findings=[
                            Finding(
                                pack="project_sanity",
                                code="project_sanity.unused_lua",
                                severity="warning",
                                message="Lua file is present but not referenced",
                                location="Lua/test.lua",
                            )
                        ],
                    )
                ],
            )
            report_path = root / "out" / "operator-ui" / "runs" / "demo" / "report.html"
            write_html_report(report, report_path)

            page = client.get(f"/ui/files?path={report_path}")

        self.assertEqual(page.status_code, 200)
        self.assertIn("Operator report", page.text)
        self.assertIn("report-route", page.text)
        self.assertIn("This report is the printable operator summary for one SG check", page.text)
        self.assertIn("--bg: #040811", page.text)

    def test_operator_css_keeps_loading_overlay_hidden_by_default(self) -> None:
        css = (ROOT / "sg_preflight" / "static" / "operator.css").read_text(encoding="utf-8")
        self.assertIn(".loading-overlay[hidden]", css)
        self.assertIn('body[data-loading-active="true"] .loading-overlay[hidden]', css)
        self.assertIn(".loading-overlay--expanded", css)
        self.assertIn("overflow-y: auto", css)
        self.assertIn(".loading-native-screen", css)
        js = (ROOT / "sg_preflight" / "static" / "operator.js").read_text(encoding="utf-8")
        self.assertIn("const syncOverlayExpandedState = function (resetScroll)", js)
        self.assertIn("if (resetScroll && expanded)", js)
        self.assertIn("Show exactly what the tool is doing", js)
        base = (ROOT / "sg_preflight" / "templates" / "base.html").read_text(encoding="utf-8")
        self.assertIn("loading-native-screen", base)
        self.assertIn("Show exactly what the tool is doing", base)

    def test_deep_audit_route_persists_and_renders_playground_note(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            mirror_root = root / "repositories" / "trunk"
            reference_root = root / "reference" / "trunk"

            (mirror_root / "Cars_IDCevo" / "BMW" / "G65").mkdir(parents=True, exist_ok=True)
            (reference_root / "Cars_IDCevo" / "BMW" / "G65").mkdir(parents=True, exist_ok=True)
            (mirror_root / "Cars" / "BMW").mkdir(parents=True, exist_ok=True)
            (reference_root / "Cars" / "BMW").mkdir(parents=True, exist_ok=True)
            (reference_root / "Playground" / "RaCoSceneMerging_PoC").mkdir(parents=True, exist_ok=True)

            (mirror_root / "Cars_IDCevo" / "BMW" / "G65" / "main.rca").write_text("same\n", encoding="utf-8")
            (reference_root / "Cars_IDCevo" / "BMW" / "G65" / "main.rca").write_text("same\n", encoding="utf-8")
            (mirror_root / "Cars" / "BMW" / "CarPaint.json").write_text("{ }\n", encoding="utf-8")
            (reference_root / "Cars" / "BMW" / "CarPaint.json").write_text("{ }\n", encoding="utf-8")
            (
                reference_root / "Playground" / "RaCoSceneMerging_PoC" / "only-on-reference.txt"
            ).write_text("drift\n", encoding="utf-8")

            profile = RunProfile(
                profile_id="G65",
                label="BMW G65 test slice",
                repo_root=mirror_root,
                project_root=mirror_root / "Cars_IDCevo" / "BMW" / "G65",
                config_path=root / "config" / "sg_rules_live_g65.json",
                mirror_audit_targets=("Cars_IDCevo/BMW/G65", "Cars/BMW/CarPaint.json"),
                reference_repo_root=reference_root,
            )

            client = TestClient(create_app(root=root, profiles=[profile]))

            response = client.get("/ui/audits/mirror/deep", follow_redirects=False)
            self.assertEqual(response.status_code, 302)
            home = client.get("/ui")

        self.assertEqual(home.status_code, 200)
        self.assertIn("Refresh deep mirror audit", home.text)
        self.assertIn("Show mirror health", home.text)
        self.assertIn("Playground/RaCoSceneMerging_PoC", home.text)


if __name__ == "__main__":
    unittest.main()
