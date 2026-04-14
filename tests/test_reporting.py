from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from sg_preflight.models import Finding, PackResult, Report
from sg_preflight.reporting import write_html_report, write_markdown_report


class TestReporting(unittest.TestCase):
    def test_reports_group_findings_and_include_handoff_context(self) -> None:
        report = Report(
            bundle="demo://bundle",
            context={
                "car_model": "G70",
                "trim_line": "Sport",
                "delivery_phase": "preview",
                "review_target": "internal_rack",
                "evidence_source": "unit-test bundle",
            },
        )
        project_sanity = PackResult(pack="project_sanity")
        project_sanity.add(
            Finding(
                pack="project_sanity",
                code="project_sanity.unused_lua",
                severity="warning",
                message="Lua file is present but not referenced",
                location="Lua/a.lua",
            )
        )
        project_sanity.add(
            Finding(
                pack="project_sanity",
                code="project_sanity.unused_lua",
                severity="warning",
                message="Lua file is present but not referenced",
                location="Lua/b.lua",
            )
        )
        project_sanity.add(
            Finding(
                pack="project_sanity",
                code="project_sanity.onedrive_root",
                severity="error",
                message="Project root points into OneDrive, which is unsafe for this workflow",
                location="C:\\Users\\Demo\\OneDrive\\Project",
            )
        )
        report.packs.append(project_sanity)
        config = {
            "reporting": {
                "context_labels": {"car_model": "Car Model"},
                "context_field_order": [
                    "car_model",
                    "trim_line",
                    "delivery_phase",
                    "review_target",
                    "evidence_source",
                ],
                "pack_owner_hints": {"project_sanity": "TA / pipeline / integration owner"},
                "code_hints": {
                    "project_sanity.onedrive_root": {
                        "action": "Move the project out of OneDrive before further integration work."
                    }
                },
            }
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            html_output = Path(temp_dir) / "report.html"
            md_output = Path(temp_dir) / "report.md"
            write_html_report(report, html_output, config)
            write_markdown_report(report, md_output, config)
            html = html_output.read_text(encoding="utf-8")
            markdown = md_output.read_text(encoding="utf-8")

        self.assertIn("Grouped Findings", html)
        self.assertIn("Pack Highlights", html)
        self.assertIn("Workflow Context", html)
        self.assertIn("Suggested Next Actions", html)
        self.assertIn("Owner Hint", html)
        self.assertIn("2 occurrences", html)
        self.assertIn("Full Findings", html)
        self.assertIn("<details class='pack-details'>", html)
        self.assertIn("project_sanity.unused_lua", html)
        self.assertIn("Car Model", html)
        self.assertIn("Move the project out of OneDrive", html)

        self.assertIn("# SG Preflight QA Handoff", markdown)
        self.assertIn("## Workflow Context", markdown)
        self.assertIn("## Suggested Next Actions", markdown)
        self.assertIn("Car Model: G70", markdown)
        self.assertIn("Owner: TA / pipeline / integration owner", markdown)


if __name__ == "__main__":
    unittest.main()
