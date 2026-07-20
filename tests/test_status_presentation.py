from __future__ import annotations

import unittest

from sg_preflight.status_presentation import status_label, status_tone


class TestStatusPresentation(unittest.TestCase):
    def test_operator_states_have_exact_labels_and_semantic_tones(self) -> None:
        expected = {
            "failed": ("Failed", "bad"),
            "findings": ("Findings", "warn"),
            "queued": ("Queued", "active"),
            "running": ("Running", "active"),
            "completed": ("Completed", "active"),
            "available": ("Available", "evidence"),
            "recorded": ("Evidence recorded", "evidence"),
            "not_recorded": ("Not recorded", "neutral"),
            "external": ("External evidence", "neutral"),
            "human_review": ("Human review", "warn"),
            "passed": ("Passed", "good"),
        }

        self.assertEqual(
            {status: (status_label(status), status_tone(status)) for status in expected},
            expected,
        )

    def test_exact_matching_keeps_negated_and_unknown_states_neutral_or_negative(self) -> None:
        self.assertEqual(status_label("not_available"), "Not available")
        self.assertEqual(status_tone("not_available"), "bad")
        self.assertEqual(status_label("almost_available"), "Almost available")
        self.assertEqual(status_tone("almost_available"), "neutral")
        self.assertEqual(status_label("  custom<script> state  "), "Custom script state")
        self.assertEqual(status_tone("  custom<script> state  "), "neutral")
        self.assertEqual(status_label(""), "Unknown")
        self.assertEqual(status_tone(""), "neutral")

    def test_execution_evidence_and_outcome_states_are_visually_distinct(self) -> None:
        self.assertEqual(
            {status_tone("completed"), status_tone("available"), status_tone("passed")},
            {"active", "evidence", "good"},
        )


if __name__ == "__main__":
    unittest.main()
