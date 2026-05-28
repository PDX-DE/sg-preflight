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

        self.assertIn("PDX_SGFX/139_3D-Car/225_3D-Car---RaCo-Implementation/226_How-to-screenshottest", anchors)
        self.assertIn("PDX_SGFX/366_Ambient-Layer/376_How-to-screenshot-test-AL", anchors)
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


if __name__ == "__main__":
    unittest.main()
