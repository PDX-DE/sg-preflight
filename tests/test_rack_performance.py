from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sg_preflight.rack_performance import (
    build_rack_performance_report,
    evaluate_against_budget,
    parse_ramses_log,
    rack_performance_markdown,
    write_rack_performance_report,
)

CAPTURE = """\
07-08 22:10:01.123 1234 1250 I ramses.Periodic: Avg framerate: 28.50 FPS [minFrameTime 2370us, maxFrameTime 41000us], drawCalls (0/0/0), numFrames 17
07-08 22:10:01.124 1234 1250 I ramses.Periodic: Avg frame delta 35.10ms min=33.07ms max=48.30ms
07-08 22:10:01.125 1234 1250 I ramses.Periodic: staticRes VRAM usage/cache (20746/0 KB)
07-08 22:10:01.126 1234 1250 I ramses.Periodic: DR VRAM usage 43597 KB
07-08 22:10:01.127 1234 1250 I ramses.Periodic: Total VRAM usage 64343 KB
07-08 22:10:01.128 1234 1250 I App: CPU usage: 42%
07-08 22:10:03.223 1234 1250 I ramses.Periodic: Avg framerate: 31.20 FPS [minFrameTime 2100us, maxFrameTime 39000us], drawCalls (0/0/0), numFrames 31
07-08 22:10:03.224 1234 1250 I ramses.Periodic: Total VRAM usage 65900 KB
07-08 22:10:03.225 1234 1250 I App: CPU usage: 55%
"""


class RamsesLogParseTests(unittest.TestCase):
    def test_extracts_all_metric_families(self) -> None:
        parsed = parse_ramses_log(CAPTURE)
        summary = parsed["summary"]
        self.assertEqual(summary["fps"], {"count": 2, "min": 28.5, "max": 31.2, "avg": 29.85})
        self.assertEqual(summary["vram_total_kb"]["max"], 65900)
        self.assertEqual(summary["vram_static_kb"]["min"], 20746)
        self.assertEqual(summary["vram_dr_kb"]["max"], 43597)
        self.assertEqual(summary["cpu_percent"], {"count": 2, "min": 42, "max": 55, "avg": 48.5})
        self.assertEqual(summary["frame_delta_ms"]["min"], 35.1)

    def test_empty_capture_yields_no_summary(self) -> None:
        parsed = parse_ramses_log("nothing to see here\nanother line")
        self.assertEqual(parsed["summary"], {})
        self.assertEqual(parsed["matched_lines"], 0)


class BudgetEvaluationTests(unittest.TestCase):
    def test_flags_under_fps_and_over_vram(self) -> None:
        summary = parse_ramses_log(CAPTURE)["summary"]
        result = evaluate_against_budget(
            summary,
            {"min_fps": 30, "max_vram_total_kb": 65536, "max_cpu_percent": 80},
        )
        self.assertEqual(result["state"], "over_budget")
        self.assertEqual(result["over_budget"], 2)
        by_metric = {c["metric"]: c["status"] for c in result["checks"]}
        self.assertEqual(by_metric["fps"], "over_budget")
        self.assertEqual(by_metric["vram_total_kb"], "over_budget")
        self.assertEqual(by_metric["cpu_percent"], "within_budget")

    def test_within_budget_when_limits_are_generous(self) -> None:
        summary = parse_ramses_log(CAPTURE)["summary"]
        result = evaluate_against_budget(summary, {"min_fps": 20, "max_vram_total_kb": 999999})
        self.assertEqual(result["state"], "within_budget")
        self.assertEqual(result["over_budget"], 0)

    def test_no_budget_is_measured_only(self) -> None:
        summary = parse_ramses_log(CAPTURE)["summary"]
        result = evaluate_against_budget(summary, None)
        self.assertEqual(result["state"], "measured_only")

    def test_budget_for_missing_metric_reports_no_data(self) -> None:
        result = evaluate_against_budget({"cpu_percent": {"count": 1, "min": 1, "max": 1, "avg": 1}}, {"min_fps": 30})
        self.assertEqual(result["checks"][0]["status"], "no_data")


class ReportTests(unittest.TestCase):
    def test_report_and_markdown_and_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = root / "capture.log"
            capture.write_text(CAPTURE, encoding="utf-8")
            report = build_rack_performance_report(capture, budget={"min_fps": 30, "max_vram_total_kb": 65536})
            self.assertEqual(report["state"], "over_budget")
            text = rack_performance_markdown(report)
            self.assertIn("over the operator budget", text)
            self.assertIn("not a standalone visual-QA pass", text)
            out = write_rack_performance_report(report, root / "out" / "rack.md")
            self.assertTrue(out.is_file())

    def test_missing_capture(self) -> None:
        report = build_rack_performance_report(Path("does-not-exist.log"))
        self.assertEqual(report["state"], "no_capture")
        self.assertIn("No logcat capture", rack_performance_markdown(report))

    def test_capture_without_samples(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            capture = Path(tmp) / "empty.log"
            capture.write_text("just some unrelated log lines\n", encoding="utf-8")
            report = build_rack_performance_report(capture)
            self.assertEqual(report["state"], "no_samples")


if __name__ == "__main__":
    unittest.main()
