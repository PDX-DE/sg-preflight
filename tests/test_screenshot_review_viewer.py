from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import struct
import tempfile
from pathlib import Path
import unittest

from sg_preflight.cli import main
from sg_preflight.screenshot_review_viewer import _script_json_payload, build_screenshot_review_viewer


class TestScreenshotReviewViewer(unittest.TestCase):
    def _write_bmp(self, path: Path, color: tuple[int, int, int]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        width = 2
        height = 2
        row_size = ((24 * width + 31) // 32) * 4
        image_size = row_size * height
        file_size = 54 + image_size
        red, green, blue = color
        pixel = bytes((blue, green, red))
        row = (pixel * width).ljust(row_size, b"\x00")
        header = (
            b"BM"
            + struct.pack("<IHHI", file_size, 0, 0, 54)
            + struct.pack("<IIIHHIIIIII", 40, width, height, 1, 24, 0, image_size, 2835, 2835, 0, 0)
        )
        path.write_bytes(header + (row * height))

    def test_build_screenshot_review_viewer_writes_sync_zoom_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "Cars_IDCevo" / "BMW" / "G70"
            expected_root = project_root / "export" / "tests" / "expected"
            actual_root = project_root / "export" / "tests" / "actuals"
            diff_root = project_root / "export" / "tests" / "diff"

            self._write_bmp(expected_root / "front.bmp", (10, 20, 30))
            self._write_bmp(actual_root / "front.bmp", (90, 20, 30))
            self._write_bmp(diff_root / "front.bmp", (255, 0, 0))

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
            self.assertTrue(item.expected_uri.startswith("file:///"))
            self.assertTrue(item.actual_uri.startswith("file:///"))
            self.assertTrue(item.diff_uri.startswith("file:///"))

            html = bundle.html_path.read_text(encoding="utf-8")
            self.assertIn('data-sgfx-screenshot-viewer="true"', html)
            self.assertIn("Sync zoom", html)
            self.assertIn('data-pane="expected"', html)
            self.assertIn('data-pane="actual"', html)
            self.assertIn('data-pane="diff"', html)
            self.assertIn("pointerdown", html)
            self.assertIn("Manual review remains required.", html)
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
            self.assertTrue(payload["items"][0]["actual_uri"].startswith("file:///"))


if __name__ == "__main__":
    unittest.main()
