from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from sg_preflight.daily_digest import build_daily_digest
from sg_preflight.delivery_checklist import delivery_checklist_digest_items
from sg_preflight.export_size_analysis import (
    READ_ONLY_BANNER,
    export_size_analysis_digest_items,
    read_export_size_analysis,
    render_export_size_analysis_markdown,
    resolve_export_size_analysis_workbook,
)


def _write_export_size_analysis_workbook(path: Path, *, profile: str = "G65", total: float = 28665.10999999998) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Overview"
    worksheet.append([profile, None, None, None, None, None, None])
    worksheet.append(["Variant", "TextureCube", "Texture2D", "ArrayResource", "Effect", "Total", "Valeo est."])
    worksheet.append(["BEV-Basis", 5616, 11935.61, 10677.93999999998, 435.5600000000003, total, 25225.30])
    worksheet.append(["ICE-MPP", 5616, 11935.61, 10677.93999999998, 435.5600000000003, total + 1, 25226.30])
    workbook.save(path)


class TestExportSizeAnalysis(unittest.TestCase):
    def test_read_export_size_analysis_parses_overview_sheet_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workbook_path = Path(temp_dir) / "Cars" / "size_analysis" / "G65_20251002.xlsx"
            _write_export_size_analysis_workbook(workbook_path)
            before_mtime = workbook_path.stat().st_mtime_ns

            payload = read_export_size_analysis(
                profile_id="G65",
                workspace=Path(temp_dir),
                latest=True,
            )

            after_mtime = workbook_path.stat().st_mtime_ns

        self.assertEqual(payload["status"], "available")
        self.assertTrue(payload["data_available"])
        self.assertEqual(payload["profile_id"], "G65")
        self.assertEqual(payload["matched_profile_id"], "G65")
        self.assertEqual(payload["worksheet"], "Overview")
        self.assertEqual(payload["workbook_date"], "2025-10-02")
        self.assertEqual(payload["variant_count"], 2)
        self.assertEqual(payload["workbook_metadata"]["row_count"], 4)
        self.assertGreater(payload["workbook_metadata"]["file_size"], 0)
        self.assertTrue(payload["workbook_metadata"]["modified_at"])
        self.assertFalse(payload["is_approval"])
        self.assertEqual(before_mtime, after_mtime)
        self.assertEqual(payload["variants"][0]["name"], "BEV-Basis")
        self.assertEqual(payload["variants"][0]["totals"]["Total"], "28665.11")
        self.assertEqual(payload["variants"][0]["totals"]["ArrayResource"], "10677.94")
        self.assertEqual(payload["variants"][0]["totals"]["Effect"], "435.56")
        self.assertEqual(payload["variants"][0]["totals"]["Valeo est."], "25225.3")
        self.assertIn("2 variant", payload["summary"])
        self.assertIn("read-only", payload["note"].lower())

    def test_read_export_size_analysis_returns_unavailable_when_workbook_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            payload = read_export_size_analysis(profile_id="G65", workspace=root, latest=True)

        self.assertEqual(payload["status"], "unavailable")
        self.assertFalse(payload["data_available"])
        self.assertEqual(payload["profile_id"], "G65")
        self.assertIn("Cars", payload["workbook_path"])
        self.assertIn("size_analysis", payload["workbook_path"])
        self.assertIn("workbook not found", payload["summary"].lower())
        self.assertIn("CI team operation", payload["summary"])
        self.assertEqual(payload["variants"], [])

    def test_read_export_size_analysis_returns_no_overview_sheet_when_overview_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workbook_path = Path(temp_dir) / "Cars" / "size_analysis" / "G65_20251002.xlsx"
            workbook_path.parent.mkdir(parents=True, exist_ok=True)
            workbook = Workbook()
            workbook.active.title = "Details"
            workbook.save(workbook_path)

            payload = read_export_size_analysis(profile_id="G65", workspace=Path(temp_dir), latest=True)

        self.assertEqual(payload["status"], "no_overview_sheet")
        self.assertFalse(payload["data_available"])
        self.assertEqual(payload["workbook_path"], str(workbook_path.resolve()))
        self.assertIn("Overview", payload["summary"])

    def test_resolve_export_size_analysis_workbook_picks_latest_by_glob(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            older = root / "Cars" / "size_analysis" / "G65_20250930.xlsx"
            newer = root / "Cars" / "size_analysis" / "G65_20251002.xlsx"
            _write_export_size_analysis_workbook(older, total=28515.26)
            _write_export_size_analysis_workbook(newer, total=28665.11)

            resolved = resolve_export_size_analysis_workbook(profile_id="G65_EVO", workspace=root, latest=True)
            payload = read_export_size_analysis(profile_id="G65_EVO", workspace=root, latest=True)

        self.assertEqual(resolved, newer.resolve())
        self.assertEqual(payload["workbook_date"], "2025-10-02")
        self.assertEqual(payload["matched_profile_id"], "G65")

    def test_read_export_size_analysis_picks_explicit_date(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            older = root / "Cars" / "size_analysis" / "G65_20250930.xlsx"
            newer = root / "Cars" / "size_analysis" / "G65_20251002.xlsx"
            _write_export_size_analysis_workbook(older, total=28515.26)
            _write_export_size_analysis_workbook(newer, total=28665.11)

            payload = read_export_size_analysis(profile_id="G65", workspace=root, date="20250930")

        self.assertEqual(payload["workbook_path"], str(older.resolve()))
        self.assertEqual(payload["workbook_date"], "2025-09-30")
        self.assertEqual(payload["variants"][0]["totals"]["Total"], "28515.26")

    def test_export_size_analysis_markdown_starts_with_read_only_banner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workbook_path = Path(temp_dir) / "Cars" / "size_analysis" / "G65_20251002.xlsx"
            _write_export_size_analysis_workbook(workbook_path)
            payload = read_export_size_analysis(profile_id="G65", workbook_path=workbook_path)

        markdown = render_export_size_analysis_markdown(payload)

        self.assertTrue(markdown.startswith(READ_ONLY_BANNER))
        self.assertIn("SGFX does not run the export size workflow or modify the workbook.", markdown)
        self.assertIn("BEV-Basis", markdown)
        self.assertIn("Manual delivery review remains required.", markdown)
        self.assertNotIn("approved", markdown.lower())

    def test_daily_digest_surfaces_export_size_analysis_distinct_from_delivery_checklist(self) -> None:
        export_payload = {
            "profile_id": "G65",
            "matched_profile_id": "G65",
            "status": "available",
            "data_available": True,
            "workbook_date": "2025-10-02",
            "workbook_path": "C:/repositories/trunk/Cars/size_analysis/G65_20251002.xlsx",
            "variant_count": 2,
            "variants": [
                {"name": "BEV-Basis", "totals": {"Total": "28665.11"}},
                {"name": "ICE-MPP", "totals": {"Total": "28666.11"}},
            ],
            "summary": "Export-size analysis G65 2025-10-02: 2 variants recorded from Overview sheet.",
        }
        checklist_payload = {
            "profile_id": "G65",
            "status": "available",
            "data_available": True,
            "summary": "Delivery checklist G65: Ramses Size recorded; Logic Size recorded.",
        }

        digest = build_daily_digest(
            {
                "ticket_id": "IDCEVODEV-977874",
                "scope": ["G65"],
                "daily_snapshot_summary": {"smoke_completed": 0, "smoke_total": 0},
                "screenshot_battery_counts": {"total": 0},
                "daily_delta_summary": {},
                "daily_delta": {},
                "review_owner_decisions": {"sections": []},
                "manual_review_profiles": [],
                "delivery_checklist": [checklist_payload],
                "export_size_analysis": [export_payload],
                "artifact_references": {},
                "top_review_priority_items": [],
                "open_items": [],
            }
        )

        evidence_items = digest["sections"]["evidence_prepared"]["items"]
        sources = {item["source"] for item in evidence_items if "source" in item}

        self.assertIn("delivery_checklist", sources)
        self.assertIn("export_size_analysis", sources)
        self.assertNotEqual(
            delivery_checklist_digest_items({"delivery_checklist": [checklist_payload]})[0]["source"],
            export_size_analysis_digest_items({"export_size_analysis": [export_payload]})[0]["source"],
        )
        export_items = [item for item in evidence_items if item.get("source") == "export_size_analysis"]
        self.assertEqual(export_items[0]["label"], "Export-size analysis G65 (2025-10-02)")
        self.assertIn("2 variant", export_items[0]["detail"])
        self.assertIn("BEV-Basis", export_items[0]["detail"])
        self.assertIn("Export-size analysis G65", digest["markdown"])
        self.assertNotIn("approved", export_items[0]["note"].lower())


if __name__ == "__main__":
    unittest.main()
