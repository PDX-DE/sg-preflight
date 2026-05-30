"""H-31 tests for the risk score sparkline (SVG + ASCII + honest fallback)."""
from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from sg_preflight.risk_sparkline import (
    MIN_RUNS_FOR_TREND,
    SparklineData,
    build_sparkline_data,
    render_sparkline_ascii,
    render_sparkline_svg,
    sparkline_fallback_text,
)


class SparklineBuildTests(unittest.TestCase):
    def test_zero_runs_returns_no_trend_with_honest_reason(self) -> None:
        data = build_sparkline_data([])
        self.assertFalse(data.has_trend)
        self.assertEqual(data.risk_scores, ())
        self.assertIn("No recorded runs", data.fallback_reason)

    def test_one_or_two_runs_marks_insufficient_history(self) -> None:
        runs = [
            {"completed_at_utc": "2026-05-29T08:00:00Z", "risk_score": 40},
            {"completed_at_utc": "2026-05-29T09:00:00Z", "risk_score": 50},
        ]
        data = build_sparkline_data(runs)
        self.assertFalse(data.has_trend)
        self.assertEqual(len(data.risk_scores), 2)
        self.assertIn("Insufficient history", data.fallback_reason)

    def test_three_or_more_runs_with_scores_unlocks_trend(self) -> None:
        runs = [
            # Reader returns newest-first; build_sparkline_data reverses to chronological.
            {"completed_at_utc": "2026-05-29T10:00:00Z", "risk_score": 60},
            {"completed_at_utc": "2026-05-29T09:00:00Z", "risk_score": 40},
            {"completed_at_utc": "2026-05-29T08:00:00Z", "risk_score": 20},
        ]
        data = build_sparkline_data(runs, profile_id="G70")
        self.assertTrue(data.has_trend)
        self.assertEqual(data.risk_scores, (20, 40, 60))  # chronological
        self.assertEqual(data.profile_id, "G70")
        self.assertEqual(data.fallback_reason, "")

    def test_runs_without_parseable_risk_score_are_skipped(self) -> None:
        runs = [
            {"completed_at_utc": "2026-05-29T10:00:00Z", "risk_score": None},
            {"completed_at_utc": "2026-05-29T09:00:00Z"},  # missing field entirely
            {"completed_at_utc": "2026-05-29T08:00:00Z", "risk_score": "not a number"},
            {"completed_at_utc": "2026-05-29T07:00:00Z", "risk_score": 25},
            {"completed_at_utc": "2026-05-29T06:00:00Z", "risk_score": 30},
            {"completed_at_utc": "2026-05-29T05:00:00Z", "risk_score": 45},
        ]
        data = build_sparkline_data(runs)
        self.assertTrue(data.has_trend)
        self.assertEqual(data.risk_scores, (45, 30, 25))

    def test_min_runs_constant_is_three(self) -> None:
        self.assertEqual(MIN_RUNS_FOR_TREND, 3)


class SparklineRenderTests(unittest.TestCase):
    def test_svg_emits_one_rect_per_score_with_data_score_attr(self) -> None:
        data = build_sparkline_data([
            {"completed_at_utc": "2026-05-29T10:00:00Z", "risk_score": 60},
            {"completed_at_utc": "2026-05-29T09:00:00Z", "risk_score": 40},
            {"completed_at_utc": "2026-05-29T08:00:00Z", "risk_score": 20},
        ])
        svg = render_sparkline_svg(data)
        self.assertTrue(svg.startswith("<svg "))
        self.assertIn("xmlns=\"http://www.w3.org/2000/svg\"", svg)
        self.assertIn('role="img"', svg)
        rects = re.findall(r'<rect[^>]+data-score="(\d+)"', svg)
        self.assertEqual(rects, ["20", "40", "60"])
        # Per-score colour bands.
        self.assertIn('fill="#57d68d"', svg)  # green for 20
        self.assertIn('fill="#e8c07d"', svg)  # yellow for 40
        self.assertIn('fill="#f07f72"', svg)  # red for 60

    def test_svg_empty_when_no_trend(self) -> None:
        data = SparklineData(has_trend=False)
        self.assertEqual(render_sparkline_svg(data), "")

    def test_ascii_unicode_blocks_emitted_in_order(self) -> None:
        data = build_sparkline_data([
            {"completed_at_utc": "t3", "risk_score": 100},
            {"completed_at_utc": "t2", "risk_score": 50},
            {"completed_at_utc": "t1", "risk_score": 0},
        ])
        ascii_chart = render_sparkline_ascii(data)
        self.assertEqual(len(ascii_chart), 3)
        # Lowest bar uses the lowest block; highest uses the highest.
        from sg_preflight.risk_sparkline import _ASCII_BLOCKS
        self.assertEqual(ascii_chart[0], _ASCII_BLOCKS[0])
        self.assertEqual(ascii_chart[-1], _ASCII_BLOCKS[-1])

    def test_ascii_empty_when_no_trend(self) -> None:
        data = SparklineData(has_trend=False, fallback_reason="Insufficient history")
        self.assertEqual(render_sparkline_ascii(data), "")

    def test_fallback_text_when_trend_unavailable(self) -> None:
        data = SparklineData(has_trend=False, fallback_reason="Insufficient history (1 run)")
        self.assertEqual(sparkline_fallback_text(data), "Insufficient history (1 run)")
        # Fallback returns empty when trend is available — the caller renders the SVG instead.
        ok = SparklineData(has_trend=True, risk_scores=(10, 20, 30))
        self.assertEqual(sparkline_fallback_text(ok), "")


class SparklineIntegrationWithFullQaHistoryTests(unittest.TestCase):
    def test_sparkline_consumes_read_full_qa_run_list_directly(self) -> None:
        """End-to-end H-30 + H-31 wiring: history list → sparkline data → SVG."""
        from sg_preflight.full_qa_history import (
            read_full_qa_run_list,
            record_full_qa_run_history,
        )

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            for index, score in enumerate((10, 25, 40, 55), start=1):
                record_full_qa_run_history(
                    "G70",
                    {
                        "status": "incomplete",
                        "summary": f"run {index}",
                        "steps": [{"status": "passed"}, {"status": "incomplete"}],
                        "risk_score": score,
                        "risk_level": "yellow" if score >= 30 else "green",
                    },
                    home=home,
                    completed_at_utc=f"2026-05-29T0{index}:00:00Z",
                )
            runs = read_full_qa_run_list("G70", home=home, limit=10)
            data = build_sparkline_data(runs, profile_id="G70")
            self.assertTrue(data.has_trend)
            # Chronological order matches insertion order.
            self.assertEqual(data.risk_scores, (10, 25, 40, 55))
            svg = render_sparkline_svg(data)
            self.assertIn('data-score="10"', svg)
            self.assertIn('data-score="55"', svg)


if __name__ == "__main__":
    unittest.main()
