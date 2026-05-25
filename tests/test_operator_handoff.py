from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from sg_preflight.operator_handoff import (
    build_operator_handoff_snapshot,
    record_operator_handoff,
    render_operator_handoff_markdown,
)


class OperatorHandoffTests(unittest.TestCase):
    def test_record_and_read_latest_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            record = record_operator_handoff(
                workspace=root,
                profile_id="G65",
                ticket_id="IDCEVODEV-977874",
                stopping_point="Exterior diffs reviewed through right-front view.",
                next_step="Continue with interior lighting screenshots.",
                note="Check mirror angle before recording manual verdict.",
            )

            snapshot = build_operator_handoff_snapshot(workspace=root, profile_id="G65")

        self.assertEqual(record["status"], "recorded")
        self.assertEqual(snapshot["status"], "recorded")
        self.assertTrue(snapshot["data_available"])
        self.assertEqual(snapshot["profile_id"], "G65")
        self.assertEqual(snapshot["latest_handoff"]["stopping_point"], record["stopping_point"])
        self.assertEqual(snapshot["handoff_count"], 1)
        self.assertTrue(snapshot["manual_review_required"])
        self.assertFalse(snapshot["is_approval"])
        self.assertTrue(all(item["status"] in {"recorded", "not_run"} for item in snapshot["handoff_items"]))

    def test_empty_snapshot_is_not_run_and_guardrailed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot = build_operator_handoff_snapshot(workspace=Path(temp_dir), profile_id="G70")

        self.assertEqual(snapshot["status"], "not_run")
        self.assertFalse(snapshot["data_available"])
        self.assertEqual(snapshot["latest_handoff"], {})
        self.assertTrue(snapshot["manual_review_required"])
        self.assertFalse(snapshot["is_approval"])

    def test_handoff_rejects_approval_wording(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ValueError):
                record_operator_handoff(
                    workspace=Path(temp_dir),
                    profile_id="G65",
                    stopping_point="Screenshots approved for handoff.",
                )

    def test_markdown_keeps_stopping_point_and_guardrails_visible(self) -> None:
        payload = {
            "title": "Operator Handoff",
            "status": "recorded",
            "profile_id": "G65",
            "handoff_count": 1,
            "summary": "Latest handoff for G65: Exterior diffs reviewed.",
            "latest_handoff": {
                "stopping_point": "Exterior diffs reviewed.",
                "next_step": "Continue with interior lighting screenshots.",
                "note": "Local note.",
            },
            "guardrails": [
                "Manual review remains required.",
                "Decision: not approval — evidence only.",
            ],
        }

        markdown = render_operator_handoff_markdown(payload)

        self.assertIn("Operator Handoff", markdown)
        self.assertIn("Stopping point", markdown)
        self.assertIn("Manual review remains required", markdown)
        self.assertIn("Decision: not approval", markdown)
        self.assertNotIn("approved", markdown.casefold())
        self.assertNotIn("validated", markdown.casefold())


if __name__ == "__main__":
    unittest.main()
