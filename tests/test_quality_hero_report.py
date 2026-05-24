from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import struct
import tempfile
from pathlib import Path
import unittest
from unittest import mock

from openpyxl import Workbook

from sg_preflight.cli import main
from sg_preflight.quality_hero_report import build_quality_hero_report
from tests.operator_helpers import create_temp_g65_profile


def _write_bmp(path: Path, color: tuple[int, int, int]) -> None:
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


def _write_delivery_workbook(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Delivery"
    sheet.append(["Car", "Last Tested", "SVN Revision", "Changelog Revision", "Export Size", "Screenshots"])
    sheet.append(["G65", "2026-05-25", "r123", "r122", "OK", "OK"])
    workbook.save(path)


def _write_export_workbook(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Overview"
    sheet.append(["G65"])
    sheet.append(["Variant", "TextureCube", "Total"])
    sheet.append(["BEV-Basis", 1, 2])
    workbook.save(path)


class TestQualityHeroReport(unittest.TestCase):
    def test_build_quality_hero_report_collects_workbook_screenshot_and_manual_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = create_temp_g65_profile(root)
            project_root = profile.project_root
            _write_delivery_workbook(
                root / "repositories" / "trunk" / ".pdx" / "checkers" / "deliveryChecklist" / "Delivery Data - BMW.xlsx"
            )
            _write_export_workbook(root / "repositories" / "trunk" / "Cars" / "size_analysis" / "G65_20260525.xlsx")
            expected = project_root / "export" / "tests" / "expected" / "front.bmp"
            actual = project_root / "export" / "tests" / "actuals" / "front.bmp"
            _write_bmp(expected, (10, 20, 30))
            _write_bmp(actual, (90, 20, 30))
            viewer_json = root / "viewer.json"
            viewer_json.write_text(
                json.dumps(
                    {
                        "profile_id": profile.profile_id,
                        "project_root": str(project_root),
                        "expected_root": str(expected.parent),
                        "item_count": 1,
                        "html_path": str(root / "viewer.html"),
                        "items": [
                            {
                                "key": "front",
                                "classification": "needs_review",
                                "visual_classification": "structural_likely_review",
                                "summary": "Visual change detected.",
                                "expected_path": str(expected),
                                "actual_path": str(actual),
                                "diff_path": "",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            bundle = build_quality_hero_report(
                profile_id=profile.profile_id,
                workspace=root,
                output_root=root / "out" / "report",
                ticket_id="IDCEVODEV-1009244",
                bmw_root=root / "missing-digital-3d-car-models",
                screenshot_viewer_json=viewer_json,
                thumbnail_limit=1,
            )

            self.assertTrue(bundle.markdown_path.exists())
            self.assertTrue(bundle.json_path.exists())
            self.assertEqual(bundle.payload["profile_id"], "G65")
            self.assertEqual(bundle.payload["delivery_checklist"]["status"], "available")
            self.assertEqual(bundle.payload["export_size_analysis"]["status"], "available")
            self.assertEqual(bundle.payload["screenshot_counts"]["items"], 1)
            self.assertFalse(bundle.payload["is_approval"])

            markdown = bundle.markdown_path.read_text(encoding="utf-8")
            self.assertIn("# Quality-Hero Review Report - G65", markdown)
            self.assertIn("## Workbook Stats", markdown)
            self.assertIn("## Screenshot Review", markdown)
            self.assertIn("## Screenshot Thumbnails", markdown)
            self.assertIn("<img", markdown)
            self.assertIn("Manual review remains required.", markdown)

    def test_cli_quality_hero_report_can_prepare_jira_attachment_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = create_temp_g65_profile(root)
            viewer_json = root / "viewer.json"
            viewer_json.write_text(
                json.dumps(
                    {
                        "profile_id": profile.profile_id,
                        "project_root": str(profile.project_root),
                        "expected_root": "",
                        "item_count": 0,
                        "items": [],
                    }
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with mock.patch(
                "sg_preflight.cli.attach_jira_file_action",
                return_value={"status": "recorded", "ticket": "IDCEVODEV-1009244", "posted": True},
            ) as attach:
                with redirect_stdout(stdout):
                    result = main(
                        [
                            "quality-hero-report",
                            "generate",
                            "--profile",
                            profile.profile_id,
                            "--workspace",
                            str(root),
                            "--bmw-root",
                            str(root / "missing-digital-3d-car-models"),
                            "--screenshot-viewer-json",
                            str(viewer_json),
                            "--output-root",
                            str(root / "out" / "report"),
                            "--attach-ticket",
                            "IDCEVODEV-1009244",
                            "--auto-confirm",
                            "--format",
                            "json",
                        ]
                    )

            self.assertEqual(result, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["jira_attachment"]["status"], "recorded")
            attach.assert_called_once()
            self.assertTrue(attach.call_args.kwargs["auto_confirm"])


if __name__ == "__main__":
    unittest.main()
