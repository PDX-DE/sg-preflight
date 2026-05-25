from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from sg_preflight.cli import main
from sg_preflight.daily_digest import build_latest_daily_digest
from sg_preflight.manual_review import (
    QUALITY_HERO_STEP_TITLES,
    VALID_VERDICTS,
    apply_manual_review_suggestions,
    create_manual_review_session,
    create_manual_review_session_from_template,
    list_car_review_templates,
    load_manual_review_session,
    record_manual_review_step,
    render_manual_review_auto_checks_markdown,
    render_manual_review_markdown,
    review_template_for_profile,
    run_manual_review_auto_checks,
    suggest_manual_review_verdicts,
)
from tests.operator_helpers import write_text


class TestManualReviewCompanion(unittest.TestCase):
    def test_create_session_populates_quality_hero_steps_without_verdicts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            session = create_manual_review_session(
                profile_id="G65",
                ticket_id="IDCEVODEV-977874",
                workspace=root,
                session_id="manual-001",
            )

            session_path = Path(session["session_path"])
            self.assertTrue(session_path.exists())
            self.assertEqual(session["profile_id"], "G65")
            self.assertEqual(session["ticket_id"], "IDCEVODEV-977874")
            self.assertEqual([step["title"] for step in session["steps"]], list(QUALITY_HERO_STEP_TITLES))
            self.assertTrue(all(step["verdict"] == "not_run" for step in session["steps"]))
            self.assertTrue(all(step["recorded_by_tool"] is False for step in session["steps"]))

            markdown = render_manual_review_markdown(session)
            self.assertIn(
                "Manual review companion. Operator records the verdict per step. Not a tool-generated review or approval.",
                markdown,
            )
            self.assertIn("Blender Visual Check", markdown)
            self.assertIn("CarPaints Test RaCo", markdown)
            self.assertNotIn("automated visual approval", markdown.lower())

    def test_quality_hero_steps_include_structured_review_focus_without_verdicts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            session = create_manual_review_session(
                profile_id="G65",
                ticket_id="IDCEVODEV-977874",
                workspace=root,
                session_id="manual-001",
            )

        by_slug = {step["slug"]: step for step in session["steps"]}
        blender = by_slug["blender_visual_check"]
        functionality = by_slug["functionality_test_raco"]
        carpaints = by_slug["carpaints_test_raco"]
        anchors = by_slug["anchor_points_test_raco"]

        self.assertIn("LightFX", blender["review_focus"])
        self.assertIn("Selective Yellow", blender["review_focus"])
        self.assertIn("WelcomeFX", functionality["review_focus"])
        self.assertIn("Country variants", functionality["review_focus"])
        self.assertIn("CarPaint / Lackcode", carpaints["review_focus"])
        self.assertIn("Anchor points", anchors["review_focus"])
        self.assertTrue(all(step["recorded_by_tool"] is False for step in session["steps"]))
        self.assertTrue(all(step["verdict"] == "not_run" for step in session["steps"]))
        self.assertTrue(all(step["review_focus_note"].startswith("Review guidance only") for step in session["steps"]))

        markdown = render_manual_review_markdown(session)
        self.assertIn("Review focus:", markdown)
        self.assertIn("LightFX", markdown)
        self.assertIn("WelcomeFX", markdown)
        self.assertIn("CarPaint / Lackcode", markdown)
        self.assertIn("Review guidance only", markdown)
        self.assertNotIn("approved", markdown.lower())

    def test_family_templates_bootstrap_evidence_checklist_without_verdicts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            session = create_manual_review_session_from_template(
                profile_id="F66",
                ticket_id="IDCEVODEV-1009244",
                family_id="mini",
                workspace=root,
                session_id="manual-mini",
            )

        self.assertEqual(session["family_id"], "mini")
        self.assertEqual(session["car_family_template"]["brand"], "MINI")
        self.assertTrue(session["evidence_checklist"])
        self.assertTrue(all(item["status"] == "not_run" for item in session["evidence_checklist"]))
        self.assertTrue(all(item["manual_review_required"] for item in session["evidence_checklist"]))
        self.assertTrue(all(step["verdict"] == "not_run" for step in session["steps"]))
        self.assertTrue(session["manual_review_required"])
        self.assertFalse(session["is_approval"])
        markdown = render_manual_review_markdown(session)
        self.assertIn("## Evidence Checklist", markdown)
        self.assertIn("MINI Quality-Hero review", markdown)
        self.assertIn("Confluence Anchors", markdown)

    def test_family_template_selection_uses_profile_metadata_and_aliases(self) -> None:
        templates = {item["family_id"]: item for item in list_car_review_templates()}

        self.assertEqual(set(templates), {"bmw_idcevo", "bmw_idc23", "mini"})
        self.assertEqual(review_template_for_profile("MINI_U25")["family_id"], "mini")

    def test_manual_review_suggestions_are_profile_agnostic_guidance_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "repositories" / "trunk" / "Cars_IDCevo" / "BMW" / "G70"
            write_text(project / "_WorkFiles" / "scene.blend", "blend fixture\n")
            write_text(project / "_WorkFiles" / "json" / "G70_Pivot_Master.json", "{}\n")
            write_text(project / "_Common" / "constants" / "scripts" / "Module_constants_G70.lua", "return {}\n")
            write_text(project / "export" / "tests" / "expected" / "front.png", "fake\n")
            write_text(project / "README.md", "# G70\n")
            write_text(project / "CHANGELOG.md", "# Changes\n")
            write_text(
                root
                / "operator_state"
                / "manual_review_suggestions"
                / "g70"
                / "functionality_test_raco.passed",
                "ok\n",
            )

            payload = suggest_manual_review_verdicts("G70", workspace=root)

        suggestions = payload["suggestions"]
        self.assertEqual(suggestions["blender_visual_check"]["suggested_verdict"], "")
        self.assertEqual(suggestions["blender_visual_check"]["evidence_status"], "available")
        self.assertEqual(suggestions["constants_info_verification"]["suggested_verdict"], "")
        self.assertEqual(suggestions["constants_info_verification"]["evidence_status"], "available")
        self.assertEqual(suggestions["final_look_comparison_raco_blender_epic"]["suggested_verdict"], "")
        self.assertEqual(suggestions["final_look_comparison_raco_blender_epic"]["evidence_status"], "available")
        self.assertEqual(suggestions["functionality_test_raco"]["suggested_verdict"], "")
        self.assertEqual(suggestions["functionality_test_raco"]["evidence_status"], "available")
        self.assertEqual(suggestions["anchor_points_test_raco"]["suggested_verdict"], "")
        self.assertEqual(suggestions["anchor_points_test_raco"]["evidence_status"], "missing")
        self.assertEqual(suggestions["documentation_review"]["suggested_verdict"], "")
        self.assertEqual(suggestions["documentation_review"]["evidence_status"], "available")
        self.assertTrue(suggestions["blender_visual_check"]["manual_review_required"])
        self.assertFalse(payload["is_approval"])
        self.assertIn("Evidence hints never select", payload["note"])

    def test_manual_review_auto_checks_surface_evidence_without_verdicts(self) -> None:
        from openpyxl import Workbook

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "repositories" / "trunk" / "Cars_IDCevo" / "BMW" / "G70"
            write_text(project / "_WorkFiles" / "scene.blend", "blend fixture\n")
            write_text(project / "_WorkFiles" / "json" / "G70_Pivot_Master.json", "{}\n")
            write_text(project / "_Common" / "constants" / "scripts" / "Module_constants_G70.lua", "return {}\n")
            write_text(project / "export" / "tests" / "expected" / "front.png", "fake baseline\n")
            write_text(project / "resources" / "RES_G70_AnchorPoints" / "anchors.json", "{}\n")
            write_text(project.parent / "CarPaint.json", "{}\n")
            write_text(project / "README.md", "# G70\n")
            write_text(project / "CHANGELOG.md", "# Changes\n")
            workbook_path = root / "Cars" / "size_analysis" / "G70_20260525.xlsx"
            workbook_path.parent.mkdir(parents=True, exist_ok=True)
            workbook = Workbook()
            overview = workbook.active
            overview.title = "Overview"
            overview.append(["G70"])
            overview.append([])
            overview.append(["Variant", "Total", "Logic"])
            overview.append(["Base", 100, 20])
            overview.append(["M Sport", 110, 21])
            workbook.save(workbook_path)

            payload = run_manual_review_auto_checks("G70", workspace=root)

        by_slug = {step["slug"]: step for step in payload["steps"]}
        self.assertEqual(payload["status"], "available")
        self.assertTrue(payload["manual_review_required"])
        self.assertFalse(payload["is_approval"])
        self.assertEqual(by_slug["blender_visual_check"]["suggested_verdict"], "")
        self.assertEqual(by_slug["blender_visual_check"]["auto_check_kind"], "file_presence")
        self.assertEqual(by_slug["final_look_comparison_raco_blender_epic"]["auto_check_kind"], "visual_diff")
        self.assertEqual(
            by_slug["final_look_comparison_raco_blender_epic"]["auto_check_metrics"]["visual_diff"]["pair_count"],
            1,
        )
        self.assertEqual(by_slug["functionality_test_raco"]["auto_check_kind"], "workbook_variance")
        self.assertEqual(
            by_slug["functionality_test_raco"]["auto_check_metrics"]["workbook_variance"]["variant_count"],
            2,
        )
        self.assertEqual(by_slug["anchor_points_test_raco"]["evidence_status"], "available")
        self.assertEqual(by_slug["carpaints_test_raco"]["evidence_status"], "available")
        self.assertTrue(all(step["suggested_verdict"] == "" for step in payload["steps"]))
        markdown = render_manual_review_auto_checks_markdown(payload)
        self.assertIn("Auto-check status", markdown)
        self.assertIn("Manual review required: yes", markdown)
        self.assertNotIn("approved", markdown.lower())

    def test_apply_manual_review_suggestions_does_not_overwrite_recorded_verdicts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "repositories" / "trunk" / "Cars_IDCevo" / "BMW" / "G70"
            write_text(project / "_WorkFiles" / "scene.blend", "blend fixture\n")
            session = create_manual_review_session(
                profile_id="G70",
                ticket_id="IDCEVODEV-977874",
                workspace=root,
                session_id="manual-001",
            )
            session["steps"][0]["verdict"] = "failed"

            decorated = apply_manual_review_suggestions(session["steps"], profile_id="G70", workspace=root)

        self.assertEqual(decorated[0]["verdict"], "failed")
        self.assertEqual(decorated[0]["suggested_verdict"], "")
        constants = next(item for item in decorated if item["slug"] == "constants_info_verification")
        self.assertEqual(constants["suggested_verdict"], "")
        self.assertEqual(constants["evidence_status"], "missing")
        self.assertTrue(constants["manual_review_required"])
        self.assertFalse(constants["suggestion_is_approval"])
        self.assertEqual(constants["auto_check_status"], "missing")
        self.assertEqual(constants["operator_focus_status"], "incomplete")

    def test_record_step_captures_explicit_reviewer_verdict_note_and_screenshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            screenshot = root / "evidence" / "blender-front.png"
            screenshot.parent.mkdir(parents=True)
            screenshot.write_bytes(b"fake png bytes")
            create_manual_review_session(
                profile_id="G65",
                ticket_id="IDCEVODEV-977874",
                workspace=root,
                session_id="manual-001",
            )

            updated = record_manual_review_step(
                "manual-001",
                "blender_visual_check",
                "passed",
                workspace=root,
                note="Reviewer checked logos, lights, side mirrors, rims and flaps.",
                screenshot=screenshot,
                suggested_verdict="passed",
            )

            step = next(item for item in updated["steps"] if item["slug"] == "blender_visual_check")
            self.assertEqual(step["verdict"], "passed")
            self.assertEqual(step["operator_verdict"], "passed")
            self.assertEqual(step["suggested_verdict"], "passed")
            self.assertEqual(step["note"], "Reviewer checked logos, lights, side mirrors, rims and flaps.")
            self.assertEqual(step["screenshot_path"], str(screenshot.resolve()))
            self.assertFalse(step["recorded_by_tool"])
            self.assertEqual(updated["summary"]["recorded_steps"], 1)
            self.assertGreaterEqual(updated["summary"]["pending_steps"], 6)

            reloaded = load_manual_review_session("manual-001", workspace=root)
            self.assertEqual(reloaded["steps"][0]["verdict"], "passed")
            self.assertIn("[passed]", render_manual_review_markdown(reloaded))

    def test_record_step_accepts_legacy_direct_api_aliases_as_canonical_verdicts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_manual_review_session(
                profile_id="G65",
                ticket_id="IDCEVODEV-977874",
                workspace=root,
                session_id="manual-001",
            )

            updated = record_manual_review_step(
                "manual-001",
                "blender_visual_check",
                "pass",
                workspace=root,
                note="Legacy caller alias.",
            )

        step = next(item for item in updated["steps"] if item["slug"] == "blender_visual_check")
        self.assertEqual(step["verdict"], "passed")
        self.assertEqual(updated["summary"]["passed"], 1)

    def test_all_verdict_values_are_operator_recorded_and_bad_screenshot_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_manual_review_session(
                profile_id="G65",
                ticket_id="IDCEVODEV-977874",
                workspace=root,
                session_id="manual-001",
            )

            step_slugs = (
                "blender_visual_check",
                "constants_info_verification",
                "functionality_test_raco",
                "documentation_review",
            )
            for step_slug, verdict in zip(step_slugs, VALID_VERDICTS):
                record_manual_review_step(
                    "manual-001",
                    step_slug,
                    verdict,
                    workspace=root,
                    note=f"Reviewer recorded {verdict}.",
                )

            updated = load_manual_review_session("manual-001", workspace=root)
            verdicts = {step["slug"]: step["verdict"] for step in updated["steps"]}
            for step_slug, verdict in zip(step_slugs, VALID_VERDICTS):
                self.assertEqual(verdicts[step_slug], verdict)
            self.assertEqual(updated["summary"]["recorded_steps"], len(VALID_VERDICTS))
            self.assertFalse(any(step["recorded_by_tool"] for step in updated["steps"]))

            with self.assertRaises(FileNotFoundError):
                record_manual_review_step(
                    "manual-001",
                    "anchor_points_test_raco",
                    "incomplete",
                    workspace=root,
                    screenshot=root / "missing.png",
                )

    def test_cli_creates_records_and_renders_markdown_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            session_stdout = io.StringIO()
            with redirect_stdout(session_stdout):
                create_result = main(
                    [
                        "manual-review",
                        "session",
                        "--workspace",
                        str(root),
                        "--profile",
                        "G65",
                        "--ticket",
                        "IDCEVODEV-977874",
                        "--session-id",
                        "manual-001",
                        "--json",
                    ]
                )

            record_stdout = io.StringIO()
            with redirect_stdout(record_stdout):
                record_result = main(
                    [
                        "manual-review",
                        "record-step",
                        "manual-001",
                        "--workspace",
                        str(root),
                        "--step",
                        "constants_info_verification",
                        "--verdict",
                        "incomplete",
                        "--note",
                        "Waiting for epic constants.",
                        "--json",
                    ]
                )

            summary_stdout = io.StringIO()
            with redirect_stdout(summary_stdout):
                summary_result = main(
                    [
                        "manual-review",
                        "summary",
                        "manual-001",
                        "--workspace",
                        str(root),
                        "--markdown",
                    ]
                )

        self.assertEqual(create_result, 0)
        self.assertEqual(record_result, 0)
        self.assertEqual(summary_result, 0)
        payload = json.loads(session_stdout.getvalue())
        self.assertEqual(payload["session_id"], "manual-001")
        self.assertIn("Constants Info Verification", summary_stdout.getvalue())
        self.assertIn("[incomplete]", summary_stdout.getvalue())
        self.assertIn("Operator records the verdict per step", summary_stdout.getvalue())

    def test_open_tool_commands_fail_clean_when_external_tool_is_not_configured(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_manual_review_session(
                profile_id="G65",
                ticket_id="IDCEVODEV-977874",
                workspace=root,
                session_id="manual-001",
            )

            stderr = io.StringIO()
            with mock.patch(
                "sg_preflight.manual_review.prerequisite_status",
                return_value=[{"key": "raco_gui", "status": "missing", "path": "", "detail": ""}],
            ):
                with redirect_stderr(stderr):
                    result = main(
                        [
                            "manual-review",
                            "open-raco",
                            "manual-001",
                            "--workspace",
                            str(root),
                            "--step",
                            "functionality_test_raco",
                        ]
                    )

        self.assertEqual(result, 1)
        self.assertIn("Ramses Composer / RaCo is not configured", stderr.getvalue())

    def test_daily_digest_surfaces_pending_manual_review_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_manual_review_session(
                profile_id="G65",
                ticket_id="IDCEVODEV-977874",
                workspace=root,
                session_id="manual-001",
            )

            digest = build_latest_daily_digest("IDCEVODEV-977874", root)

        items = digest["sections"]["manual_review_pending"]["items"]
        labels = [item["label"] for item in items]
        self.assertTrue(any("manual-001" in label for label in labels))
        self.assertTrue(any(item.get("session_id") == "manual-001" for item in items))
        self.assertIn("blender_visual_check", digest["markdown"])
        self.assertIn("Operator verdict required", digest["markdown"])
        blender_item = next(item for item in items if item.get("step_slug") == "blender_visual_check")
        self.assertEqual(blender_item["status"], "not_run")
        self.assertIn("LightFX", blender_item["review_focus"])
        self.assertIn("Review guidance only", blender_item["note"])


if __name__ == "__main__":
    unittest.main()
