from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from sg_preflight.cross_car_comparison import (
    build_cross_car_comparison,
    render_cross_car_comparison_markdown,
)
from tests.operator_helpers import write_text


def _write_screenshot_fixture(root: Path, profile_id: str, *, expected: int, actual: int, diff: int) -> None:
    tests_root = root / "digital-3d-car-models" / "cars" / "BMW" / f"{profile_id}_EVO" / "export" / "tests"
    write_text(root / "digital-3d-car-models" / "ci" / "scripts" / "README.md", "fixture\n")
    for index in range(expected):
        write_text(tests_root / "expected" / f"view_{index}.png", "fake\n")
    for index in range(actual):
        write_text(tests_root / "actuals" / f"view_{index}.png", "fake\n")
    for index in range(diff):
        write_text(tests_root / "diff" / f"view_{index}.png", "fake\n")


class CrossCarComparisonTests(unittest.TestCase):
    def test_comparison_puts_g70_and_g65_risk_widget_side_by_side(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_screenshot_fixture(root, "G70", expected=3, actual=2, diff=1)
            _write_screenshot_fixture(root, "G65", expected=2, actual=1, diff=0)

            payload = build_cross_car_comparison(
                workspace=root,
                left_profile="G70",
                right_profile="G65",
            )

        self.assertEqual(payload["comparison_axis"], "risk-score")
        self.assertEqual(payload["left_profile"], "G70")
        self.assertEqual(payload["right_profile"], "G65")
        self.assertEqual(payload["profiles"], ["G70", "G65"])
        self.assertTrue(payload["manual_review_required"])
        self.assertFalse(payload["is_approval"])
        rows = {row["id"]: row for row in payload["comparison_rows"]}
        self.assertIn("risk_score", rows)
        self.assertIn("actual_screenshots", rows)
        self.assertEqual(rows["actual_screenshots"]["left_raw"], 2)
        self.assertEqual(rows["actual_screenshots"]["right_raw"], 1)
        self.assertEqual(rows["actual_screenshots"]["delta"], 1)
        self.assertTrue(all(row["is_approval"] is False for row in payload["comparison_rows"]))

    def test_comparison_markdown_keeps_guardrails_visible(self) -> None:
        payload = {
            "title": "Cross-Car Comparison",
            "status": "available",
            "widget_label": "Risk Score",
            "left_profile": "G70",
            "right_profile": "G65",
            "summary": "Cross-car comparison for G70 vs G65.",
            "comparison_rows": [
                {
                    "label": "Risk score",
                    "left_value": "42/100 (medium)",
                    "right_value": "21/100 (low)",
                    "delta_label": "+21 point(s)",
                    "status": "available",
                }
            ],
            "guardrails": [
                "Manual review remains required.",
                "Decision: not approval — evidence only.",
            ],
        }

        markdown = render_cross_car_comparison_markdown(payload)

        self.assertIn("Cross-Car Comparison", markdown)
        self.assertIn("G70", markdown)
        self.assertIn("G65", markdown)
        self.assertIn("Manual review remains required", markdown)
        self.assertIn("Decision: not approval", markdown)
        self.assertNotIn("approved", markdown.casefold())
        self.assertNotIn("validated", markdown.casefold())


if __name__ == "__main__":
    unittest.main()
