from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from sg_preflight.bmw_pipeline_auto_fix import MISSING_ACTUAL_DIAGNOSTIC_ACTION_ID
from sg_preflight.full_qa_pass import (
    build_full_qa_pass,
    render_full_qa_pass_markdown,
    render_full_qa_pass_text,
)


def _payload(status: str = "available", **extra: object) -> dict[str, object]:
    return {
        "status": status,
        "summary": f"{status} summary",
        "manual_review_required": True,
        "is_approval": False,
        **extra,
    }


class _Board:
    def to_dict(self) -> dict[str, object]:
        return {"source_state": "ready"}


def _gate(payload: dict[str, object], gate_id: str) -> dict[str, object]:
    return next(step for step in payload["steps"] if step["id"] == gate_id)


def _source(payload: dict[str, object], source_id: str) -> dict[str, object]:
    return next(step for step in payload["source_evidence"] if step["id"] == source_id)


class TestFullQaPass(unittest.TestCase):
    def setUp(self) -> None:
        for name in (
            "build_api_version_coverage_board",
            "build_country_variant_coverage_board",
            "build_disabled_tests_board",
            "build_export_size_trend_board",
        ):
            patcher = mock.patch(f"sg_preflight.full_qa_pass.{name}", return_value=_Board())
            patcher.start()
            self.addCleanup(patcher.stop)
        action_records_patcher = mock.patch(
            "sg_preflight.full_qa_pass.list_recent_action_records",
            return_value=[],
        )
        self.action_records_reader = action_records_patcher.start()
        self.addCleanup(action_records_patcher.stop)
        run_records_patcher = mock.patch(
            "sg_preflight.full_qa_pass.list_recent_run_records",
            return_value=[],
        )
        self.run_records_reader = run_records_patcher.start()
        self.addCleanup(run_records_patcher.stop)

    def test_full_qa_steps_are_exactly_the_seven_control_center_gates(self) -> None:
        from sg_preflight.full_qa_pass import build_full_qa_pass

        self.action_records_reader.return_value = [
            {
                "run_id": "action-001",
                "action_id": "sgfx_preflight__g45",
                "kind": "sgfx_preflight",
                "profile_id": "G45",
                "status": "completed",
                "created_at_utc": "2026-07-12T20:00:00+00:00",
                "completed_at_utc": "2026-07-12T20:01:00+00:00",
                "summary": {
                    "errors": 0,
                    "warnings": 2,
                    "info": 3,
                    "child_run_id": "action-001-preflight",
                },
                "paths": {"summary": r"C:\private\operator\summary.json"},
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with (
                mock.patch("sg_preflight.full_qa_pass.build_onboarding_guide", return_value=_payload("available", onboarding_status="available", operator_focus_steps=[])),
                mock.patch("sg_preflight.full_qa_pass.read_delivery_checklist", return_value=_payload("available")),
                mock.patch("sg_preflight.full_qa_pass.build_delivery_workbook_trigger", return_value=_payload("available", trigger_status="available", can_start=False, blockers=[])),
                mock.patch("sg_preflight.full_qa_pass.read_bmw_screenshot_state", return_value=_payload("available")),
                mock.patch("sg_preflight.full_qa_pass.read_per_car_risk_score", return_value=_payload("available", signals=[])),
                mock.patch("sg_preflight.full_qa_pass.build_manual_review_assist", return_value=_payload("available", operator_focus_steps=[])),
                mock.patch("sg_preflight.full_qa_pass.build_operator_handoff_snapshot", return_value=_payload("recorded")),
            ):
                payload = build_full_qa_pass("G45", workspace=root)

        self.assertEqual(
            [step["id"] for step in payload["steps"]],
            ["context", "asset", "interface", "variants", "visual", "review", "delivery"],
        )
        rendered_steps = repr(payload["steps"]).casefold()
        self.assertNotIn("onboarding", rendered_steps)
        self.assertNotIn("comparison", rendered_steps)
        self.assertNotIn("digest", rendered_steps)
        self.assertIn("country-variant-coverage", rendered_steps)
        self.assertIn("evidence_summary", payload)
        self.assertIn("Profile: G45", payload["evidence_summary"])
        self.assertIn("Local checks: 0 errors, 2 warnings, 3 info", payload["evidence_summary"])
        self.assertIn("Provenance: Local SGFX action sgfx_preflight__g45", payload["evidence_summary"])
        self.assertIn("Retest hash: action-001-preflight", payload["evidence_summary"])
        self.assertNotIn(r"C:\private", payload["evidence_summary"])
        self.assertNotIn("://", payload["evidence_summary"])
        self.assertFalse(payload["is_approval"])

    def test_full_pass_does_not_invent_a_comparison_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch("sg_preflight.full_qa_pass._step_defs", return_value=[]):
                payload = build_full_qa_pass("G70", workspace=Path(temp_dir))

        self.assertEqual(payload["profile_id"], "G70")
        self.assertEqual(payload["comparison_profile"], "")

    def test_full_pass_chains_components_and_surfaces_confirmations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            patches = [
                mock.patch("sg_preflight.full_qa_pass.build_onboarding_guide", return_value=_payload("available", onboarding_status="available", operator_focus_steps=[])),
                mock.patch("sg_preflight.full_qa_pass.read_delivery_checklist", return_value=_payload("available")),
                mock.patch(
                    "sg_preflight.full_qa_pass.build_delivery_workbook_trigger",
                    return_value=_payload(
                        "available",
                        trigger_status="available",
                        can_start=True,
                        action_id="generate-delivery-workbook",
                        label="Generate delivery workbook",
                        operator_confirmation_required=True,
                        confirmation_message="Confirm before starting local generation.",
                        blockers=[],
                    ),
                ),
                mock.patch("sg_preflight.full_qa_pass.read_bmw_screenshot_state", return_value=_payload("available")),
                mock.patch("sg_preflight.full_qa_pass.read_per_car_risk_score", return_value=_payload("available", signals=[])),
                mock.patch("sg_preflight.full_qa_pass.build_manual_review_assist", return_value=_payload("available", operator_focus_steps=[])),
                mock.patch("sg_preflight.full_qa_pass.build_operator_handoff_snapshot", return_value=_payload("recorded")),
            ]
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
                payload = build_full_qa_pass("G70", workspace=root, trusted_tool_mode=False)

        self.assertEqual(payload["status"], "incomplete")
        self.assertFalse(payload["halted"])
        self.assertEqual(payload["progress"]["completed_steps"], 5)
        self.assertEqual(len(payload["steps"]), 7)
        self.assertTrue(payload["operator_confirmation_required"])
        self.assertEqual(payload["confirmation_items"][0]["action_id"], "generate-delivery-workbook")
        delivery = _gate(payload, "delivery")
        self.assertEqual(delivery["status"], "confirmation_pending")
        self.assertEqual(delivery["inline_actions"][0]["id"], "generate-delivery-workbook")
        self.assertEqual(delivery["inline_actions"][0]["typical_range"], "typical 1-10 min")
        self.assertFalse(payload["records_operator_verdict"])
        self.assertFalse(payload["is_approval"])
        self.assertIn("Manual review remains required.", payload["guardrails"])

    def test_trusted_tool_mode_removes_confirmation_requirement_without_recording_verdicts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            patches = [
                mock.patch("sg_preflight.full_qa_pass.build_onboarding_guide", return_value=_payload("available", onboarding_status="available", operator_focus_steps=[])),
                mock.patch("sg_preflight.full_qa_pass.read_delivery_checklist", return_value=_payload("available")),
                mock.patch(
                    "sg_preflight.full_qa_pass.build_delivery_workbook_trigger",
                    return_value=_payload(
                        "available",
                        trigger_status="available",
                        can_start=True,
                        operator_confirmation_required=False,
                        blockers=[],
                    ),
                ),
                mock.patch("sg_preflight.full_qa_pass.read_bmw_screenshot_state", return_value=_payload("available")),
                mock.patch("sg_preflight.full_qa_pass.read_per_car_risk_score", return_value=_payload("available", signals=[])),
                mock.patch("sg_preflight.full_qa_pass.build_manual_review_assist", return_value=_payload("available", operator_focus_steps=[])),
                mock.patch("sg_preflight.full_qa_pass.build_operator_handoff_snapshot", return_value=_payload("recorded")),
            ]
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
                payload = build_full_qa_pass("G70", workspace=root, trusted_tool_mode=True)

        self.assertEqual(payload["status"], "incomplete")
        self.assertTrue(payload["trusted_tool_mode"])
        self.assertFalse(payload["operator_confirmation_required"])
        self.assertEqual(payload["confirmation_items"], [])
        self.assertEqual(payload["trusted_auto_actions"][0]["id"], "generate-delivery-workbook")
        self.assertIn("Jira REST and SVN gates still always prompt", payload["trusted_tool_mode_note"])
        self.assertTrue(_gate(payload, "delivery")["confluence_anchors"])
        self.assertFalse(payload["records_operator_verdict"])

    def test_screenshot_zero_actuals_is_incomplete_with_capture_action(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            patches = [
                mock.patch("sg_preflight.full_qa_pass.build_onboarding_guide", return_value=_payload("available", onboarding_status="available", operator_focus_steps=[])),
                mock.patch("sg_preflight.full_qa_pass.read_delivery_checklist", return_value=_payload("available")),
                mock.patch("sg_preflight.full_qa_pass.build_delivery_workbook_trigger", return_value=_payload("available", trigger_status="available", can_start=False, blockers=[])),
                mock.patch(
                    "sg_preflight.full_qa_pass.read_bmw_screenshot_state",
                    return_value=_payload(
                        "incomplete",
                        expected_count=48,
                        actual_count=0,
                        diff_count=0,
                        car_root=str(root / "Cars_IDCevo" / "BMW" / "F70"),
                        expected_root=str(root / "Cars_IDCevo" / "BMW" / "F70" / "export" / "tests" / "expected"),
                        actuals_root=str(root / "Cars_IDCevo" / "BMW" / "F70" / "export" / "tests" / "actuals"),
                        diff_root=str(root / "Cars_IDCevo" / "BMW" / "F70" / "export" / "tests" / "diff"),
                    ),
                ),
                mock.patch(
                    "sg_preflight.full_qa_pass.check_screenshot_capture_environment",
                    return_value={
                        "can_run": True,
                        "confirmation_message": "Run BMW screenshot capture for F70.",
                        "target_write_path": str(root / "actuals"),
                        "native_output_path": str(root / "out"),
                    },
                ),
                mock.patch("sg_preflight.full_qa_pass.read_per_car_risk_score", return_value=_payload("available", signals=[])),
                mock.patch("sg_preflight.full_qa_pass.build_manual_review_assist", return_value=_payload("available", operator_focus_steps=[])),
                mock.patch("sg_preflight.full_qa_pass.build_operator_handoff_snapshot", return_value=_payload("recorded")),
            ]
            with (
                patches[0],
                patches[1],
                patches[2],
                patches[3],
                patches[4],
                patches[5],
                patches[6],
                patches[7],
            ):
                payload = build_full_qa_pass("F70", workspace=root, trusted_tool_mode=False)

        screenshot_step = _source(payload, "screenshot-test-state")
        self.assertEqual(screenshot_step["status"], "confirmation_pending")
        self.assertEqual(screenshot_step["inline_actions"][0]["id"], "capture-screenshots")
        self.assertEqual(screenshot_step["inline_actions"][0]["typical_range"], "typical 2-10 min")
        self.assertIn("Run BMW screenshot capture for F70", screenshot_step["inline_actions"][0]["confirmation_message"])
        self.assertIn("black offscreen-rendering window", screenshot_step["inline_actions"][0]["confirmation_message"])
        self.assertEqual(screenshot_step["inline_actions"][1]["id"], MISSING_ACTUAL_DIAGNOSTIC_ACTION_ID)
        self.assertEqual(screenshot_step["inline_actions"][1]["kind"], "diagnostic_chain")
        self.assertTrue(screenshot_step["inline_actions"][1]["enabled"])
        self.assertTrue(payload["operator_confirmation_required"])

    def test_screenshot_action_surfaces_export_first_when_exported_ramses_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            patches = [
                mock.patch("sg_preflight.full_qa_pass.build_onboarding_guide", return_value=_payload("available", onboarding_status="available", operator_focus_steps=[])),
                mock.patch("sg_preflight.full_qa_pass.read_delivery_checklist", return_value=_payload("available")),
                mock.patch("sg_preflight.full_qa_pass.build_delivery_workbook_trigger", return_value=_payload("available", trigger_status="available", can_start=False, blockers=[])),
                mock.patch(
                    "sg_preflight.full_qa_pass.read_bmw_screenshot_state",
                    return_value=_payload(
                        "incomplete",
                        expected_count=4,
                        actual_count=0,
                        diff_count=0,
                        car_root=str(root / "cars" / "BMW" / "G70_EVO"),
                        expected_root=str(root / "cars" / "BMW" / "G70_EVO" / "export" / "tests" / "expected"),
                    ),
                ),
                mock.patch(
                    "sg_preflight.full_qa_pass.check_screenshot_capture_environment",
                    return_value={
                        "can_run": True,
                        "confirmation_message": "Run BMW screenshot capture for G70.",
                        "target_write_path": str(root / "sgfx_outputs" / "g70" / "screenshot-capture"),
                        "native_output_path": str(root / "cars" / "BMW" / "G70_EVO" / "export" / "tests"),
                    },
                ),
                mock.patch(
                    "sg_preflight.full_qa_pass.check_screenshot_export_artifact",
                    return_value={
                        "status": "missing",
                        "export_required": True,
                        "exported_ramses_path": str(root / "cars" / "BMW" / "G70_EVO" / "export" / "exported.ramses"),
                    },
                ),
                mock.patch("sg_preflight.full_qa_pass.read_per_car_risk_score", return_value=_payload("available", signals=[])),
                mock.patch("sg_preflight.full_qa_pass.build_manual_review_assist", return_value=_payload("available", operator_focus_steps=[])),
                mock.patch("sg_preflight.full_qa_pass.build_operator_handoff_snapshot", return_value=_payload("recorded")),
            ]
            with (
                patches[0],
                patches[1],
                patches[2],
                patches[3],
                patches[4],
                patches[5],
                patches[6],
                patches[7],
                patches[8],
            ):
                payload = build_full_qa_pass("G70", workspace=root, trusted_tool_mode=False)

        screenshot_step = _source(payload, "screenshot-test-state")
        action = screenshot_step["inline_actions"][0]
        self.assertEqual(action["id"], "capture-screenshots")
        self.assertEqual(action["label"], "Export then capture screenshots")
        self.assertTrue(action["requires_export_first"])
        self.assertEqual(action["typical_range"], "typical 3-20 min")
        self.assertIn("will run the BMW export first", action["confirmation_message"])
        self.assertIn("exported.ramses", action["confirmation_message"])

    def test_missing_workbook_with_available_generator_does_not_halt_in_automatic_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            patches = [
                mock.patch("sg_preflight.full_qa_pass.build_onboarding_guide", return_value=_payload("available", onboarding_status="available", operator_focus_steps=[])),
                mock.patch("sg_preflight.full_qa_pass.read_delivery_checklist", return_value=_payload("missing")),
                mock.patch(
                    "sg_preflight.full_qa_pass.build_delivery_workbook_trigger",
                    return_value=_payload(
                        "available",
                        trigger_status="available",
                        can_start=True,
                        action_id="generate-delivery-workbook",
                        label="Generate delivery workbook",
                        confirmation_message="No workbook for NA0 - run the BMW export to generate one?",
                        blockers=[],
                    ),
                ),
                mock.patch("sg_preflight.full_qa_pass.read_bmw_screenshot_state", return_value=_payload("available")),
                mock.patch("sg_preflight.full_qa_pass.read_per_car_risk_score", return_value=_payload("available", signals=[])),
                mock.patch("sg_preflight.full_qa_pass.build_manual_review_assist", return_value=_payload("available", operator_focus_steps=[])),
                mock.patch("sg_preflight.full_qa_pass.build_operator_handoff_snapshot", return_value=_payload("recorded")),
            ]
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
                payload = build_full_qa_pass("NA0", workspace=root, trusted_tool_mode=True)

        steps = {step["id"]: step for step in payload["source_evidence"]}
        checklist_action = steps["delivery-checklist"]["inline_actions"][0]
        self.assertEqual(steps["delivery-checklist"]["id"], "delivery-checklist")
        self.assertEqual(steps["delivery-checklist"]["label"], "Delivery documentation")
        self.assertFalse(payload["halted"])
        self.assertEqual(steps["delivery-checklist"]["status"], "incomplete")
        self.assertEqual(checklist_action["id"], "generate-delivery-workbook")
        self.assertEqual(checklist_action["step_id"], "delivery-checklist")
        self.assertTrue(checklist_action["trusted_auto_confirm"])
        self.assertFalse(checklist_action["requires_confirmation"])
        self.assertEqual(checklist_action["resolves_step_ids"], ["delivery-checklist", "delivery-workbook-trigger"])
        self.assertEqual(steps["delivery-workbook-trigger"]["status"], "passed")
        self.assertEqual(steps["delivery-workbook-trigger"]["inline_actions"], [])
        self.assertFalse(any(step["status"] == "skipped" for step in payload["steps"]))
        self.assertEqual(payload["trusted_auto_actions"], [checklist_action])

    def test_missing_workbook_with_available_generator_prompts_in_manual_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            patches = [
                mock.patch("sg_preflight.full_qa_pass.build_onboarding_guide", return_value=_payload("available", onboarding_status="available", operator_focus_steps=[])),
                mock.patch("sg_preflight.full_qa_pass.read_delivery_checklist", return_value=_payload("missing")),
                mock.patch(
                    "sg_preflight.full_qa_pass.build_delivery_workbook_trigger",
                    return_value=_payload(
                        "available",
                        trigger_status="available",
                        can_start=True,
                        action_id="generate-delivery-workbook",
                        label="Generate delivery workbook",
                        confirmation_message="No workbook for NA0 - run the BMW export to generate one?",
                        blockers=[],
                    ),
                ),
                mock.patch("sg_preflight.full_qa_pass.read_bmw_screenshot_state", return_value=_payload("available")),
                mock.patch("sg_preflight.full_qa_pass.read_per_car_risk_score", return_value=_payload("available", signals=[])),
                mock.patch("sg_preflight.full_qa_pass.build_manual_review_assist", return_value=_payload("available", operator_focus_steps=[])),
                mock.patch("sg_preflight.full_qa_pass.build_operator_handoff_snapshot", return_value=_payload("recorded")),
            ]
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
                payload = build_full_qa_pass("NA0", workspace=root, trusted_tool_mode=False)

        steps = {step["id"]: step for step in payload["source_evidence"]}
        checklist_action = steps["delivery-checklist"]["inline_actions"][0]
        self.assertFalse(payload["halted"])
        self.assertEqual(steps["delivery-checklist"]["status"], "confirmation_pending")
        self.assertTrue(checklist_action["requires_confirmation"])
        self.assertFalse(checklist_action["trusted_auto_confirm"])
        self.assertTrue(payload["operator_confirmation_required"])
        self.assertEqual(payload["confirmation_items"][0]["action_id"], "generate-delivery-workbook")
        self.assertIn("No workbook for NA0", payload["confirmation_items"][0]["detail"])

    def test_full_pass_halts_and_skips_later_steps_on_blocking_issue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with mock.patch("sg_preflight.full_qa_pass.build_onboarding_guide", return_value=_payload("available", onboarding_status="available", operator_focus_steps=[])):
                with mock.patch("sg_preflight.full_qa_pass.read_delivery_checklist", return_value=_payload("missing")):
                    with mock.patch("sg_preflight.full_qa_pass.build_delivery_workbook_trigger", return_value=_payload("unavailable", trigger_status="unavailable", can_start=False, blockers=[{"key": "repo"}])):
                        payload = build_full_qa_pass("G70", workspace=root)

        self.assertEqual(payload["status"], "incomplete")
        self.assertTrue(payload["halted"])
        self.assertEqual(payload["halted_step"], "Delivery documentation")
        self.assertIn("Halted at Delivery documentation", payload["summary"])
        skipped = [step for step in payload["source_evidence"] if step["status"] == "skipped"]
        self.assertGreaterEqual(len(skipped), 1)
        self.assertIn("Delivery documentation", skipped[0]["summary"])

    def test_renderers_keep_guardrails_and_no_approval_claim(self) -> None:
        payload = {
            "profile_id": "G70",
            "status": "incomplete",
            "summary": "Full QA pass prepared local evidence.",
            "trusted_tool_mode": True,
            "operator_confirmation_required": True,
            "progress": {"completed_steps": 1, "total_steps": 2},
            "guardrails": ["Manual review remains required.", "Decision: not approval — evidence only."],
            "steps": [{"status": "passed", "label": "Risk score", "summary": "Risk score read locally."}],
            "confirmation_items": [{"status": "incomplete", "label": "Generate delivery workbook", "detail": "Confirm first."}],
            "evidence_summary": "Profile: G70\nRetest hash: action-001-preflight",
        }

        text = render_full_qa_pass_text(payload)
        markdown = render_full_qa_pass_markdown(payload)

        self.assertIn("Run full QA pass - G70", text)
        self.assertIn("Automatic mode: True", text)
        self.assertIn("Manual review remains required.", text)
        self.assertIn("Copy-ready evidence:\nProfile: G70", text)
        self.assertIn("Automatic mode: `True`", markdown)
        self.assertIn("Manual review required: yes", markdown)
        self.assertIn("Decision: not approval", markdown)
        self.assertIn("## Copy-ready Evidence\n\nProfile: G70", markdown)
        self.assertNotIn("records operator verdict", markdown.casefold())


if __name__ == "__main__":
    unittest.main()
