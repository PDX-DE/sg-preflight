from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import struct
import tempfile
from pathlib import Path
import unittest

from sg_preflight.cli import main
from sg_preflight.screenshot_review_viewer import (
    DiffDeltaThresholds,
    _script_json_payload,
    build_screenshot_review_viewer,
    compute_diff_delta_badge,
    compute_diff_delta_histogram,
)


class TestScreenshotReviewViewer(unittest.TestCase):
    def _write_bmp(self, path: Path, color: tuple[int, int, int]) -> None:
        self._write_bmp_pixels(path, [[color, color], [color, color]])

    def _write_bmp_pixels(self, path: Path, pixels: list[list[tuple[int, int, int]]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        height = len(pixels)
        width = len(pixels[0]) if pixels else 0
        row_size = ((24 * width + 31) // 32) * 4
        image_size = row_size * height
        file_size = 54 + image_size
        header = (
            b"BM"
            + struct.pack("<IHHI", file_size, 0, 0, 54)
            + struct.pack("<IIIHHIIIIII", 40, width, height, 1, 24, 0, image_size, 2835, 2835, 0, 0)
        )
        rows: list[bytes] = []
        for row_pixels in reversed(pixels):
            row = b"".join(bytes((blue, green, red)) for red, green, blue in row_pixels)
            rows.append(row.ljust(row_size, b"\x00"))
        path.write_bytes(header + b"".join(rows))

    def test_compute_diff_delta_badge_classifies_threshold_bands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            thresholds = DiffDeltaThresholds(green_max_percent=0.5, yellow_max_percent=2.0)
            cases = (
                ("green.bmp", 1, "green", "max-\u0394: 0.4% (x=2, y=1)"),
                ("yellow.bmp", 3, "yellow", "max-\u0394: 1.2% (x=2, y=1)"),
                ("red.bmp", 8, "red", "max-\u0394: 3.1% (x=2, y=1)"),
            )
            for name, value, level, label in cases:
                path = root / name
                self._write_bmp_pixels(
                    path,
                    [
                        [(0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0)],
                        [(0, 0, 0), (0, 0, 0), (value, 0, 0), (0, 0, 0)],
                        [(0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0)],
                    ],
                )

                badge = compute_diff_delta_badge(path, thresholds=thresholds)

                self.assertEqual(badge.status, "available")
                self.assertEqual(badge.level, level)
                self.assertEqual(badge.label, label)
                self.assertEqual(badge.max_x, 2)
                self.assertEqual(badge.max_y, 1)

    def test_compute_diff_delta_histogram_bins_changed_pixels_by_axis(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "cluster.bmp"
            self._write_bmp_pixels(
                path,
                [
                    [(0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0)],
                    [(0, 0, 0), (8, 0, 0), (8, 0, 0), (0, 0, 0)],
                    [(0, 0, 0), (0, 0, 0), (8, 0, 0), (0, 0, 0)],
                ],
            )

            histogram = compute_diff_delta_histogram(path, max_bins=4)

            self.assertEqual(histogram.status, "available")
            self.assertEqual(histogram.changed_pixel_count, 3)
            self.assertEqual(histogram.total_pixel_count, 12)
            self.assertEqual(histogram.x_axis.bins, (0, 1, 2, 0))
            self.assertEqual(histogram.y_axis.bins, (0, 2, 1))
            self.assertEqual(histogram.x_axis.peak_label, "x=2")
            self.assertEqual(histogram.y_axis.peak_label, "y=1")

    def test_build_screenshot_review_viewer_writes_sync_zoom_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "Cars_IDCevo" / "BMW" / "G70"
            expected_root = project_root / "export" / "tests" / "expected"
            actual_root = project_root / "export" / "tests" / "actuals"
            diff_root = project_root / "export" / "tests" / "diff"

            self._write_bmp(expected_root / "front.bmp", (0, 20, 30))
            self._write_bmp(actual_root / "front.bmp", (255, 20, 30))
            self._write_bmp(diff_root / "front_color.bmp", (255, 0, 0))

            bundle = build_screenshot_review_viewer(
                "G70",
                project_root,
                root / "out" / "viewer",
                candidate_roots=(actual_root,),
                diff_reference_roots=(diff_root,),
            )

            self.assertEqual(bundle.viewer.profile_id, "G70")
            self.assertEqual(bundle.viewer.item_count, 1)
            self.assertTrue(bundle.json_path.exists())
            self.assertTrue(bundle.html_path.exists())
            item = bundle.viewer.items[0]
            self.assertEqual(item.key, "front")
            self.assertEqual(item.expected_uri, "assets/expected/front.bmp")
            self.assertEqual(item.actual_uri, "assets/actual/front.bmp")
            self.assertEqual(item.diff_delta_level, "red")
            self.assertEqual(item.diff_delta_label, "max-\u0394: 100.0% (x=0, y=0)")
            expected_diff_uri = (
                "assets/diff/front.png"
                if (bundle.html_path.parent / "assets/diff/front.png").is_file()
                else "assets/diff/front.bmp"
            )
            self.assertEqual(item.diff_uri, expected_diff_uri)
            self.assertEqual(item.diff_histogram_status, "available")
            self.assertEqual(item.diff_histogram_changed_pixel_count, 4)
            self.assertEqual(item.diff_histogram_total_pixel_count, 4)
            self.assertEqual(item.diff_histogram_x_bins, (2, 2))
            self.assertEqual(item.diff_histogram_y_bins, (2, 2))
            self.assertEqual(item.diff_histogram_x_peak_label, "x=0")
            self.assertEqual(item.diff_histogram_y_peak_label, "y=0")
            self.assertTrue((bundle.html_path.parent / item.expected_uri).is_file())
            self.assertTrue((bundle.html_path.parent / item.actual_uri).is_file())
            self.assertTrue((bundle.html_path.parent / item.diff_uri).is_file())

            html = bundle.html_path.read_text(encoding="utf-8")
            self.assertIn('data-sgfx-screenshot-viewer="true"', html)
            self.assertIn("Sync zoom", html)
            self.assertIn('data-pane="expected"', html)
            self.assertIn('data-pane="actual"', html)
            self.assertIn('data-pane="diff"', html)
            self.assertIn("pointerdown", html)
            self.assertIn("Manual review remains required.", html)
            self.assertIn("delta-badge delta-red", html)
            self.assertIn("max-\u0394: 100.0%", html)
            self.assertIn('class="delta-histogram sgfx-delta-histogram"', html)
            self.assertIn("Show positional histogram", html)
            self.assertIn("x-axis peak: x=0", html)
            self.assertIn("y-axis peak: y=0", html)
            self.assertIn("data-histogram-x", html)
            self.assertIn("data-histogram-y", html)
            self.assertNotIn("<details open", html)
            script_body = html.split('<script id="sgfx-viewer-data" type="application/json">', 1)[1].split(
                "</script>",
                1,
            )[0]
            self.assertTrue(script_body.startswith('{"profile_id"'))
            self.assertNotIn("&quot;", script_body)

    def test_viewer_json_script_payload_keeps_json_quotes_for_row_buttons(self) -> None:
        payload = _script_json_payload('{"summary":"</script><b>check</b>","quote":"ok"}')

        self.assertIn('"summary"', payload)
        self.assertNotIn("&quot;", payload)
        self.assertNotIn("</script>", payload)
        self.assertIn("\\u003c/script\\u003e", payload)

    def test_viewer_surfaces_missing_candidate_escalation_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "Cars_IDCevo" / "BMW" / "G70"
            expected_root = project_root / "export" / "tests" / "expected"

            self._write_bmp(expected_root / "highlighting.bmp", (10, 20, 30))

            bundle = build_screenshot_review_viewer(
                "G70",
                project_root,
                root / "out" / "viewer",
            )

            item = bundle.viewer.items[0]
            self.assertEqual(item.classification, "missing_candidate")
            self.assertEqual(item.escalation_path, "data_prep_or_ci_team")
            self.assertIn("BMW pipeline did not render an actual image", item.summary)
            html = bundle.html_path.read_text(encoding="utf-8")
            self.assertIn("data-escalation", html)
            self.assertIn("Escalation path:", html)

    def test_cli_build_screenshot_review_viewer_outputs_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "Cars_IDCevo" / "BMW" / "G70"
            expected_root = project_root / "export" / "tests" / "expected"
            actual_root = project_root / "export" / "tests" / "actuals"

            self._write_bmp(expected_root / "rear.bmp", (10, 20, 30))
            self._write_bmp(actual_root / "rear.bmp", (10, 20, 30))

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = main(
                    [
                        "screenshot-review-viewer",
                        "build",
                        "--project-root",
                        str(project_root),
                        "--candidate-root",
                        str(actual_root),
                        "--output-root",
                        str(root / "out" / "viewer"),
                        "--json",
                    ]
                )

            self.assertEqual(result, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["profile_id"], "G70")
            self.assertEqual(payload["item_count"], 1)
            self.assertEqual(payload["items"][0]["actual_uri"], "assets/actual/rear.bmp")


if __name__ == "__main__":
    unittest.main()
