from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

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


class TestFullQaPass(unittest.TestCase):
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
                mock.patch("sg_preflight.full_qa_pass.build_cross_car_comparison", return_value=_payload("available")),
                mock.patch("sg_preflight.full_qa_pass.build_team_daily_digest_board", return_value=_payload("available")),
                mock.patch("sg_preflight.full_qa_pass.build_manual_review_assist", return_value=_payload("available", operator_focus_steps=[])),
                mock.patch("sg_preflight.full_qa_pass.build_operator_handoff_snapshot", return_value=_payload("recorded")),
            ]
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8]:
                payload = build_full_qa_pass("G70", workspace=root, trusted_tool_mode=False)

        self.assertEqual(payload["status"], "incomplete")
        self.assertFalse(payload["halted"])
        self.assertEqual(payload["progress"]["completed_steps"], 8)
        self.assertEqual(len(payload["steps"]), 9)
        self.assertTrue(payload["operator_confirmation_required"])
        self.assertEqual(payload["confirmation_items"][0]["action_id"], "generate-delivery-workbook")
        self.assertEqual(payload["steps"][2]["status"], "confirmation_pending")
        self.assertEqual(payload["steps"][2]["inline_actions"][0]["id"], "generate-delivery-workbook")
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
                mock.patch("sg_preflight.full_qa_pass.build_cross_car_comparison", return_value=_payload("available")),
                mock.patch("sg_preflight.full_qa_pass.build_team_daily_digest_board", return_value=_payload("available")),
                mock.patch("sg_preflight.full_qa_pass.build_manual_review_assist", return_value=_payload("available", operator_focus_steps=[])),
                mock.patch("sg_preflight.full_qa_pass.build_operator_handoff_snapshot", return_value=_payload("recorded")),
            ]
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8]:
                payload = build_full_qa_pass("G70", workspace=root, trusted_tool_mode=True)

        self.assertEqual(payload["status"], "passed")
        self.assertTrue(payload["trusted_tool_mode"])
        self.assertFalse(payload["operator_confirmation_required"])
        self.assertEqual(payload["confirmation_items"], [])
        self.assertEqual(payload["trusted_auto_actions"][0]["id"], "generate-delivery-workbook")
        self.assertIn("Jira REST and SVN gates still always prompt", payload["trusted_tool_mode_note"])
        self.assertTrue(payload["steps"][2]["confluence_anchors"])
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
                    return_value=_payload("incomplete", expected_count=48, actual_count=0, diff_count=0),
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
                mock.patch("sg_preflight.full_qa_pass.build_cross_car_comparison", return_value=_payload("available")),
                mock.patch("sg_preflight.full_qa_pass.build_team_daily_digest_board", return_value=_payload("available")),
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
                patches[9],
            ):
                payload = build_full_qa_pass("F70", workspace=root, trusted_tool_mode=False)

        screenshot_step = next(step for step in payload["steps"] if step["id"] == "screenshot-test-state")
        self.assertEqual(screenshot_step["status"], "confirmation_pending")
        self.assertEqual(screenshot_step["inline_actions"][0]["id"], "capture-screenshots")
        self.assertIn("Run BMW screenshot capture for F70", screenshot_step["inline_actions"][0]["confirmation_message"])
        self.assertIn("black offscreen-rendering window", screenshot_step["inline_actions"][0]["confirmation_message"])
        self.assertTrue(payload["operator_confirmation_required"])

    def test_full_pass_halts_and_skips_later_steps_on_blocking_issue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with mock.patch("sg_preflight.full_qa_pass.build_onboarding_guide", return_value=_payload("available", onboarding_status="available", operator_focus_steps=[])):
                with mock.patch("sg_preflight.full_qa_pass.read_delivery_checklist", return_value=_payload("missing")):
                    payload = build_full_qa_pass("G70", workspace=root)

        self.assertEqual(payload["status"], "incomplete")
        self.assertTrue(payload["halted"])
        self.assertEqual(payload["halted_step"], "Delivery checklist")
        self.assertIn("Halted at Delivery checklist", payload["summary"])
        skipped = [step for step in payload["steps"] if step["status"] == "skipped"]
        self.assertGreaterEqual(len(skipped), 1)
        self.assertIn("Delivery checklist", skipped[0]["summary"])

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
        }

        text = render_full_qa_pass_text(payload)
        markdown = render_full_qa_pass_markdown(payload)

        self.assertIn("Run full QA pass - G70", text)
        self.assertIn("Automatic mode: True", text)
        self.assertIn("Manual review remains required.", text)
        self.assertIn("Automatic mode: `True`", markdown)
        self.assertIn("Manual review required: yes", markdown)
        self.assertIn("Decision: not approval", markdown)
        self.assertNotIn("records operator verdict", markdown.casefold())


if __name__ == "__main__":
    unittest.main()
