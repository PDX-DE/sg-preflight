from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path
import unittest

from sg_preflight.screenshot_triage import VisualDiffThresholds, materialize_screenshot_triage
from tests.operator_helpers import write_text


PILLOW_AVAILABLE = bool(importlib.util.find_spec("PIL"))
if PILLOW_AVAILABLE:
    from PIL import Image


@unittest.skipUnless(PILLOW_AVAILABLE, "Pillow is required for screenshot-triage image fixtures")
class TestScreenshotTriage(unittest.TestCase):
    def _write_png(self, path: Path, size: tuple[int, int], color: tuple[int, int, int, int]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGBA", size, color)
        image.save(path)

    def test_materialize_screenshot_triage_classifies_pairs_conservatively(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "Cars_IDCevo" / "BMW" / "G70"
            expected_root = project_root / "export" / "tests" / "expected"
            candidate_root = project_root / "export" / "tests" / "results"

            self._write_png(expected_root / "same.png", (64, 64), (10, 20, 30, 255))
            self._write_png(expected_root / "tiny_drift.png", (100, 100), (20, 30, 40, 255))
            self._write_png(expected_root / "changed.png", (64, 64), (30, 40, 50, 255))
            self._write_png(expected_root / "mismatch.png", (64, 64), (40, 50, 60, 255))
            self._write_png(expected_root / "missing_candidate.png", (64, 64), (50, 60, 70, 255))

            self._write_png(candidate_root / "same.png", (64, 64), (10, 20, 30, 255))
            self._write_png(candidate_root / "tiny_drift.png", (100, 100), (20, 30, 40, 255))
            with Image.open(candidate_root / "tiny_drift.png") as image:
                image.putpixel((0, 0), (21, 30, 40, 255))
                image.save(candidate_root / "tiny_drift.png")
            self._write_png(candidate_root / "changed.png", (64, 64), (200, 40, 50, 255))
            self._write_png(candidate_root / "mismatch.png", (80, 64), (40, 50, 60, 255))
            self._write_png(candidate_root / "extra_candidate.png", (64, 64), (90, 100, 110, 255))
            write_text(project_root / "export" / "tests" / "test_config.lua", "-- fixture\n")

            bundle = materialize_screenshot_triage(
                "G70",
                project_root,
                root / "out" / "triage",
                priority_names=("changed.png", "tiny_drift.png"),
            )

            report = bundle.report
            self.assertEqual(report.pair_count, 6)
            self.assertEqual(report.unchanged_count, 1)
            self.assertEqual(report.near_identical_count, 1)
            self.assertEqual(report.needs_review_count, 1)
            self.assertEqual(report.dimension_mismatch_count, 1)
            self.assertEqual(report.missing_candidate_count, 1)
            self.assertEqual(report.missing_baseline_count, 1)
            self.assertEqual(report.cosmetic_likely_pass_count, 2)
            self.assertEqual(report.structural_likely_review_count, 2)
            self.assertEqual(report.unclear_manual_review_count, 2)
            self.assertEqual(report.external_classifier_status, "disabled")
            self.assertEqual(report.candidate_roots[0].kind, "auto-detected")
            self.assertTrue(bundle.json_path.exists())
            self.assertTrue(bundle.markdown_path.exists())
            self.assertTrue(bundle.html_path.exists())

            pair_map = {pair.key: pair for pair in report.pairs}
            self.assertEqual(pair_map["same"].classification, "unchanged")
            self.assertEqual(pair_map["tiny_drift"].classification, "near_identical")
            self.assertEqual(pair_map["changed"].classification, "needs_review")
            self.assertEqual(pair_map["changed"].visual_classification, "structural_likely_review")
            self.assertEqual(pair_map["mismatch"].classification, "dimension_mismatch")
            self.assertEqual(pair_map["tiny_drift"].visual_classification, "cosmetic_likely_pass")
            self.assertEqual(pair_map["missing_candidate"].visual_classification, "unclear_manual_review")
            self.assertEqual(pair_map["missing_candidate"].classification, "missing_candidate")
            self.assertIn(
                "BMW pipeline did not render an actual image for this test.",
                pair_map["missing_candidate"].summary,
            )
            self.assertIn(
                "cars/BMW/G70/export/tests/diff/missing_candidate_*.png absent",
                pair_map["missing_candidate"].summary,
            )
            self.assertIn("Pink/magenta content is context-dependent", pair_map["missing_candidate"].summary)
            self.assertIn("Color alone is not used as the verdict.", pair_map["missing_candidate"].summary)
            self.assertIn("Diagnostic anchors:", pair_map["missing_candidate"].summary)
            self.assertNotIn("textures/shaders fail to load", pair_map["missing_candidate"].summary)
            self.assertEqual(pair_map["missing_candidate"].escalation_path, "data_prep_or_ci_team")
            self.assertEqual(pair_map["extra_candidate"].classification, "missing_baseline")
            self.assertIsNotNone(pair_map["changed"].review_score)
            self.assertGreater(pair_map["changed"].review_score or 0.0, 0.0)
            self.assertTrue(pair_map["changed"].anomaly_hints)
            self.assertTrue(Path(pair_map["tiny_drift"].diff_image_path).exists())
            self.assertTrue(Path(pair_map["changed"].diff_image_path).exists())

    def test_materialize_screenshot_triage_accepts_visual_threshold_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "Cars_IDCevo" / "BMW" / "G70"
            expected_root = project_root / "export" / "tests" / "expected"
            candidate_root = project_root / "export" / "tests" / "results"

            self._write_png(expected_root / "changed.png", (32, 32), (30, 40, 50, 255))
            self._write_png(candidate_root / "changed.png", (32, 32), (30, 40, 50, 255))
            with Image.open(candidate_root / "changed.png") as image:
                for x in range(3):
                    image.putpixel((x, 0), (90, 40, 50, 255))
                image.save(candidate_root / "changed.png")

            bundle = materialize_screenshot_triage(
                "G70",
                project_root,
                root / "out" / "triage",
                visual_thresholds=VisualDiffThresholds(
                    cosmetic_max_changed_ratio=0.0,
                    cosmetic_max_mean_abs_diff=0.0,
                    structural_min_changed_ratio=2.0,
                    structural_min_mean_abs_diff=255.0,
                    structural_min_review_score=999.0,
                ),
                external_classifier_requested=True,
            )

            pair = bundle.report.pairs[0]
            self.assertEqual(pair.classification, "needs_review")
            self.assertEqual(pair.visual_classification, "unclear_manual_review")
            self.assertEqual(bundle.report.unclear_manual_review_count, 1)
            self.assertEqual(bundle.report.external_classifier_status, "unavailable")
            self.assertTrue(any("no external service call" in note for note in bundle.report.notes))

    def test_materialize_screenshot_triage_reports_missing_candidate_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "Cars_IDCevo" / "BMW" / "G70"
            expected_root = project_root / "export" / "tests" / "expected"
            self._write_png(expected_root / "only_baseline.png", (32, 32), (1, 2, 3, 255))

            bundle = materialize_screenshot_triage(
                "G70",
                project_root,
                root / "out" / "triage",
            )

            self.assertEqual(bundle.report.missing_candidate_count, 1)
            self.assertFalse(bundle.report.candidate_roots)
            self.assertTrue(any("No candidate screenshot root was detected locally" in note for note in bundle.report.notes))

    def test_materialize_screenshot_triage_marks_operator_supplied_candidate_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "Cars_IDCevo" / "BMW" / "G70"
            expected_root = project_root / "export" / "tests" / "expected"
            external_candidate_root = root / "manual-candidates"

            self._write_png(expected_root / "manual.png", (32, 32), (1, 2, 3, 255))
            self._write_png(external_candidate_root / "manual.png", (32, 32), (1, 2, 3, 255))

            bundle = materialize_screenshot_triage(
                "G70",
                project_root,
                root / "out" / "triage",
                candidate_roots=(external_candidate_root,),
            )

            self.assertEqual(bundle.report.unchanged_count, 1)
            self.assertEqual(bundle.report.candidate_roots[0].kind, "operator-supplied")

    def test_materialize_screenshot_triage_keeps_missing_expected_root_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "Cars_IDCevo" / "BMW" / "NA8"

            bundle = materialize_screenshot_triage(
                "NA8",
                project_root,
                root / "out" / "triage",
            )

            self.assertEqual(bundle.report.expected_root, "")
            self.assertEqual(bundle.report.pair_count, 0)
            self.assertFalse(bundle.report.pairs)
            self.assertTrue(any("No `export/tests/expected` baseline root was detected" in note for note in bundle.report.notes))


if __name__ == "__main__":
    unittest.main()
