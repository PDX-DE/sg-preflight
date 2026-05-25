from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from sg_preflight.onboarding_assistant import (
    build_onboarding_guide,
    render_onboarding_guide_markdown,
    render_onboarding_guide_text,
)


class TestOnboardingAssistant(unittest.TestCase):
    def test_onboarding_guide_wraps_dependency_status_without_recording_verdicts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dependency_status = {
                "status": "incomplete",
                "summary": "2/5 dependency item(s) available; setup actions require operator confirmation.",
                "items": [],
                "actions": [{"id": "setup-raco-from-shared-tools", "label": "Set up RaCo"}],
                "counts": {"available": 2, "missing": 3, "incomplete": 0},
                "confluence_anchors": ["003_Onboarding/005_How-to-set-up-your-Laptop:190-204"],
            }

            payload = build_onboarding_guide(
                "G70",
                workspace=root,
                dependency_status=dependency_status,
            )

        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["onboarding_status"], "incomplete")
        self.assertEqual(payload["setup_action_count"], 1)
        self.assertTrue(payload["operator_confirmation_required"])
        self.assertTrue(payload["manual_review_required"])
        self.assertFalse(payload["records_operator_verdict"])
        self.assertFalse(payload["is_approval"])
        self.assertIn("Manual review remains required.", payload["guardrails"])
        steps = {step["key"]: step for step in payload["steps"]}
        self.assertEqual(steps["dependency-setup"]["status"], "incomplete")
        self.assertEqual(steps["profile-template"]["status"], "available")
        self.assertEqual(steps["manual-review"]["status"], "not_run")
        self.assertIn("Dependency setup", {item["label"] for item in payload["items"]})

    def test_onboarding_guide_renderers_keep_guardrails_visible(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            payload = build_onboarding_guide(
                "G70",
                workspace=root,
                dependency_status={
                    "status": "available",
                    "summary": "5/5 dependency item(s) available; setup actions require operator confirmation.",
                    "items": [],
                    "actions": [],
                    "counts": {"available": 5, "missing": 0, "incomplete": 0},
                    "confluence_anchors": [],
                },
            )

        text = render_onboarding_guide_text(payload)
        markdown = render_onboarding_guide_markdown(payload)
        self.assertIn("Onboarding Guide - G70", text)
        self.assertIn("Manual review remains required.", text)
        self.assertIn("Manual review required: yes", markdown)
        self.assertIn("Decision: not approval", markdown)
        self.assertNotIn("records operator verdict", markdown.casefold())


if __name__ == "__main__":
    unittest.main()
