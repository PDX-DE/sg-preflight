from __future__ import annotations

import json
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

from sg_preflight.qa_pass_report import (
    build_qa_pass_report_summary,
    export_qa_pass_report_zip,
    render_qa_pass_report_html,
    write_qa_pass_report_html,
)


RAW_TOKEN = "abcdef1234567890abcdef1234567890XYZW"


def _write_bmp(path: Path, *, value: int = 0) -> None:
    width = 4
    height = 4
    row_size = ((24 * width + 31) // 32) * 4
    pixel_bytes = bytearray()
    for _y in range(height):
        row = bytearray()
        for x in range(width):
            channel = (value + x * 20) % 255
            row.extend(bytes((channel, channel, channel)))
        row.extend(b"\x00" * (row_size - width * 3))
        pixel_bytes.extend(row)
    file_size = 14 + 40 + len(pixel_bytes)
    header = b"BM" + struct.pack("<IHHI", file_size, 0, 0, 54)
    dib = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, 0, len(pixel_bytes), 0, 0, 0, 0)
    path.write_bytes(header + dib + pixel_bytes)


def _fixture_payload(root: Path) -> dict:
    rows = []
    for index in range(2):
        expected = root / f"expected-{index}.bmp"
        actual = root / f"actual-{index}.bmp"
        diff = root / f"diff-{index}.bmp"
        _write_bmp(expected, value=10 + index)
        _write_bmp(actual, value=12 + index)
        _write_bmp(diff, value=40 + index)
        rows.append(
            {
                "key": f"camera_{index}",
                "label": f"Camera {index}",
                "expected_path": str(expected),
                "actual_path": str(actual),
                "diff_path": str(diff),
            }
        )
    return {
        "profile_id": "NA5",
        "status": "incomplete",
        "counts": {"passed": 5, "incomplete": 2},
        "summary": rf"Prepared evidence. Token={RAW_TOKEN}. Path=C:\Users\someuser\sgfx_outputs\na5",
        "manual_review_required": True,
        "steps": [
            {
                "id": "screenshot-test-state",
                "label": "Screenshot test state",
                "status": "incomplete",
                "summary": "Visual diffs are present.",
                "payload": {
                    "status": "available",
                    "diff_count": 2,
                    "copied_evidence": {"screenshot_review_rows": rows},
                },
            },
            {
                "id": "risk-score",
                "label": "Risk score",
                "status": "passed",
                "summary": "Risk score read locally.",
                "payload": {
                    "status": "available",
                    "risk_score": 64,
                    "risk_level": "high",
                    "signals": [{"id": "visual_diffs", "status": "available", "detail": "2 diff rows"}],
                },
            },
            {
                "id": "delivery-checklist",
                "label": "Delivery checklist",
                "status": "passed",
                "summary": "Checklist available.",
                "payload": {"checks": [{"label": "Workbook", "status": "available", "detail": "Found"}]},
            },
            {
                "id": "disabled-tests",
                "label": "Disabled tests",
                "status": "incomplete",
                "summary": "Disabled tests need review.",
                "payload": {"disabled_call_total": 3},
            },
            {
                "id": "my-tickets",
                "label": "My tickets",
                "status": "passed",
                "summary": "Ticket read-only query complete.",
                "payload": {"tickets": [{"key": "IDCEVODEV-1", "status": "Open", "summary": "Review NA5"}]},
            },
            {
                "id": "manual-review-assist",
                "label": "Manual review assist",
                "status": "incomplete",
                "summary": "Manual review remains.",
                "payload": {
                    "steps": [
                        {
                            "slug": "blender_visual_check",
                            "title": "Blender visual check",
                            "suggested_verdict": "incomplete",
                            "suggestion_reason": "Operator focus is required.",
                        },
                        {
                            "slug": "documentation_review",
                            "title": "Documentation review",
                            "suggested_verdict": "passed",
                            "suggestion_reason": "Evidence exists.",
                        },
                    ],
                    "operator_focus_steps": ["blender_visual_check"],
                },
            },
        ],
        "guardrails": ["Manual review remains required.", "Decision: not approval - evidence only."],
    }


class QaPassReportRenderTests(unittest.TestCase):
    def test_report_renders_all_diff_rows_and_has_no_external_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = _fixture_payload(Path(tmp))
            html = render_qa_pass_report_html(
                payload,
                mode="export",
                run_history=[
                    {"completed_at_utc": "t3", "risk_score": 70},
                    {"completed_at_utc": "t2", "risk_score": 50},
                    {"completed_at_utc": "t1", "risk_score": 25},
                ],
            )
        self.assertEqual(html.count('data-sgfx-diff-row="true"'), 2)
        self.assertIn('id="sgfx-zoom"', html)
        self.assertIn("Expected", html)
        self.assertIn("Actual", html)
        self.assertIn("Diff", html)
        self.assertIn("data:image/bmp;base64", html)
        self.assertIn("Manual review remains required", html)
        self.assertNotIn("<script src", html)
        self.assertNotIn("<link", html)
        self.assertNotIn('src="assets/', html)
        self.assertNotIn(RAW_TOKEN, html)
        self.assertIn("****XYZW", html)
        self.assertNotIn("someuser", html)

    def test_summary_counts_use_rows_and_manual_focus(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = build_qa_pass_report_summary(_fixture_payload(Path(tmp)))
        self.assertEqual(summary["profile_id"], "NA5")
        self.assertEqual(summary["passed_count"], 5)
        self.assertEqual(summary["screenshot_diff_count"], 2)
        self.assertEqual(summary["manual_review_item_count"], 1)
        self.assertEqual(summary["risk_score"], 64)

    def test_dashboard_mode_writes_referenced_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _fixture_payload(root)
            bundle = write_qa_pass_report_html(
                profile_id="NA5",
                payload=payload,
                output_root=root / "report",
                mode="dashboard",
            )
            html = bundle.html_path.read_text(encoding="utf-8")
            self.assertIn('src="assets/screenshot-diffs/', html)
            self.assertFalse("data:image/" in html)
            self.assertEqual(len(list((bundle.output_root / "assets" / "screenshot-diffs").glob("*.bmp"))), 6)


class QaPassReportZipTests(unittest.TestCase):
    def test_zip_bundles_report_payload_images_and_masks_text_members(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            payload = _fixture_payload(root)
            zip_path = root / "na5-report.zip"
            result = export_qa_pass_report_zip(
                profile_id="NA5",
                workspace=workspace,
                payload=payload,
                output_path=zip_path,
                run_history=[
                    {"completed_at_utc": "t3", "risk_score": 70},
                    {"completed_at_utc": "t2", "risk_score": 50},
                    {"completed_at_utc": "t1", "risk_score": 25},
                ],
            )
            self.assertTrue(result.zip_path.is_file())
            with zipfile.ZipFile(zip_path, "r") as zf:
                names = set(zf.namelist())
                self.assertIn("summary.html", names)
                self.assertIn("qa-pass-report.html", names)
                self.assertIn("full_qa_payload.json", names)
                self.assertIn("manifest.json", names)
                self.assertIn("qa_pass_report_manifest.json", names)
                self.assertEqual(len([name for name in names if name.startswith("screenshots/expected/")]), 2)
                self.assertEqual(len([name for name in names if name.startswith("screenshots/actual/")]), 2)
                self.assertEqual(len([name for name in names if name.startswith("screenshots/diff/")]), 2)
                for name in (
                    "summary.html",
                    "qa-pass-report.html",
                    "full_qa_payload.json",
                    "manifest.json",
                    "qa_pass_report_manifest.json",
                ):
                    text = zf.read(name).decode("utf-8")
                    self.assertNotIn(RAW_TOKEN, text, name)
                    self.assertNotIn("someuser", text, name)
                payload_json = json.loads(zf.read("full_qa_payload.json").decode("utf-8"))
                self.assertEqual(payload_json["profile_id"], "NA5")


if __name__ == "__main__":
    unittest.main()
