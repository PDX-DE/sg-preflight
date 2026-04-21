from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path
import unittest

from sg_preflight.screenshot_triage import materialize_screenshot_triage
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
            self.assertEqual(report.candidate_roots[0].kind, "auto-detected")
            self.assertTrue(bundle.json_path.exists())
            self.assertTrue(bundle.markdown_path.exists())
            self.assertTrue(bundle.html_path.exists())

            pair_map = {pair.key: pair for pair in report.pairs}
            self.assertEqual(pair_map["same"].classification, "unchanged")
            self.assertEqual(pair_map["tiny_drift"].classification, "near_identical")
            self.assertEqual(pair_map["changed"].classification, "needs_review")
            self.assertEqual(pair_map["mismatch"].classification, "dimension_mismatch")
            self.assertEqual(pair_map["missing_candidate"].classification, "missing_candidate")
            self.assertEqual(pair_map["extra_candidate"].classification, "missing_baseline")
            self.assertTrue(Path(pair_map["tiny_drift"].diff_image_path).exists())
            self.assertTrue(Path(pair_map["changed"].diff_image_path).exists())

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


if __name__ == "__main__":
    unittest.main()
