from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from sg_preflight.review_tracking import (
    add_external_finding,
    load_external_findings,
    load_review_decisions,
    set_review_decision,
)
from tests.operator_helpers import create_review_package_fixture


class TestReviewTracking(unittest.TestCase):
    def test_review_decision_tracking_uses_json_source_of_truth(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = create_review_package_fixture(root)

            initial = load_review_decisions(
                "IDCEVODEV-960073",
                root,
                fallback_markdown_path=fixture["package_root"] / "review-owner-decisions.md",
            )
            updated = set_review_decision(
                "IDCEVODEV-960073",
                "lights_OnlyCones",
                status="follow_up",
                owner="Adrian",
                note="Treat as follow-up unless delivery blocks.",
                workspace=root,
                fallback_markdown_path=fixture["package_root"] / "review-owner-decisions.md",
            )

            self.assertTrue(Path(updated["json_path"]).exists())
            self.assertTrue(Path(updated["markdown_path"]).exists())

        self.assertEqual(initial["pending_count"], 2)
        self.assertEqual(updated["pending_count"], 1)
        self.assertEqual(updated["decisions"][0]["status"], "follow_up")

    def test_external_findings_tracking_captures_teams_bug_report_signals(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            payload = add_external_finding(
                "IDCEVODEV-960073",
                source="Teams / 3D Car - Bug Reports / Jana",
                reported_by="Jana",
                category="changelog",
                scope=["G78", "G50"],
                finding="Missing changelog entry for light cones position change",
                owner="Ana-Karina Nazare",
                status="reported",
                note="Track separately from screenshot/export evidence.",
                finding_type="changelog finding",
                related_investigation_surfaces=["lights_OnlyCones", "Pivot Master", "parking_asset_info.json"],
                workspace=root,
            )
            latest = load_external_findings("IDCEVODEV-960073", root)

            self.assertTrue(Path(latest["json_path"]).exists())
            self.assertTrue(Path(latest["markdown_path"]).exists())

        self.assertEqual(payload["count"], 1)
        self.assertEqual(latest["count"], 1)
        self.assertEqual(latest["findings"][0]["category"], "changelog")
        self.assertIn("lights_OnlyCones", latest["related_investigation_surfaces"])


if __name__ == "__main__":
    unittest.main()
