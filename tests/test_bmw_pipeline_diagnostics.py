from __future__ import annotations

from pathlib import Path
import unittest

from sg_preflight.bmw_pipeline_diagnostics import (
    bmw_pipeline_diagnostic_pattern,
    bmw_pipeline_diagnostic_patterns,
    diagnostic_pattern_anchors,
    load_bmw_pipeline_diagnostics,
)


ROOT = Path(__file__).resolve().parents[1]


class BmwPipelineDiagnosticsTests(unittest.TestCase):
    def test_packaged_pattern_data_loads_magenta_and_missing_actuals(self) -> None:
        payload = load_bmw_pipeline_diagnostics()
        patterns = bmw_pipeline_diagnostic_patterns()

        self.assertEqual(payload["schema_version"], "1.0")
        self.assertGreaterEqual(len(patterns), 2)
        self.assertIsNotNone(bmw_pipeline_diagnostic_pattern("magenta_tint_in_actual_image"))
        self.assertIsNotNone(bmw_pipeline_diagnostic_pattern("actual_image_not_rendered_diff_missing"))
        magenta = bmw_pipeline_diagnostic_pattern("magenta_tint_in_actual_image") or {}
        self.assertIn("bmw_git_source_citations", magenta)
        self.assertIn(
            "ci/scripts/common/config.json: screenshots_clear_color",
            " | ".join(str(item) for item in magenta.get("bmw_git_source_citations", [])),
        )

    def test_pattern_anchors_are_available_without_local_personal_paths(self) -> None:
        anchors = diagnostic_pattern_anchors(
            "actual_image_not_rendered_diff_missing",
            "magenta_tint_in_actual_image",
        )
        data_text = (ROOT / "sg_preflight" / "data" / "bmw_pipeline_diagnostics.json").read_text(
            encoding="utf-8"
        )

        self.assertIn("PDX_SERIESGRAPHICS/139_3D-Car/225_3D-Car---RaCo-Implementation/226_How-to-screenshottest", anchors)
        self.assertIn("PDX_SERIESGRAPHICS/366_Ambient-Layer/376_How-to-screenshot-test-AL", anchors)
        self.assertNotIn("C:" + "/Users", data_text)
        self.assertNotIn("C:" + "\\Users", data_text)
        for token in (
            "Mer" + "cedes",
            "Clau" + "de",
            "As" + "ton",
            "Yon" + "daime",
            "Co" + "dex",
            "A" + "I " + "agent",
        ):
            self.assertNotIn(token, data_text)

class TestFailureDigest(unittest.TestCase):
    def test_extracts_first_failure_line_with_context(self) -> None:
        from sg_preflight.bmw_pipeline_diagnostics import extract_failure_digest

        log = "\n".join(f"line {i}" for i in range(1, 20))
        log = log.replace("line 9", "FAILURE: Build failed with an exception.")
        digest = extract_failure_digest(log, context_lines=2)

        self.assertTrue(digest["found"])
        self.assertEqual(digest["line_number"], 9)
        self.assertIn("FAILURE: Build failed", digest["marker_line"])
        self.assertEqual(
            digest["excerpt"].splitlines(),
            ["line 7", "line 8", "FAILURE: Build failed with an exception.", "line 10", "line 11"],
        )

    def test_falls_back_to_tail_when_no_marker_matches(self) -> None:
        from sg_preflight.bmw_pipeline_diagnostics import extract_failure_digest

        digest = extract_failure_digest("all good\nstill good\ndone", context_lines=2)

        self.assertFalse(digest["found"])
        self.assertEqual(digest["marker_line"], "done")
        self.assertIn("all good", digest["excerpt"])

    def test_empty_log_reports_nothing_found(self) -> None:
        from sg_preflight.bmw_pipeline_diagnostics import extract_failure_digest

        digest = extract_failure_digest("")

        self.assertFalse(digest["found"])
        self.assertEqual(digest["excerpt"], "")


if __name__ == "__main__":
    unittest.main()
