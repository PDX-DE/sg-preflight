from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from sg_preflight.review_state import (
    build_review_board_state,
    list_review_packages,
    load_daily_delta,
    load_external_review_findings,
    load_latest_daily_snapshot,
    load_latest_review_package,
    load_review_owner_decisions,
    load_review_priority,
    verify_sendable_package,
)
from sg_preflight.review_tracking import add_external_finding, set_review_decision
from tests.operator_helpers import create_review_package_fixture, write_json


class TestReviewState(unittest.TestCase):
    def test_load_latest_review_package_prefers_top_level_package_over_nested_ref(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = create_review_package_fixture(root)
            nested_root = root / "out" / "delivery-support-package-2026-04-22" / "refs" / "IDCEVODEV-960073"
            nested_root.mkdir(parents=True, exist_ok=True)
            write_json(
                nested_root / "IDCEVODEV-960073-review-bundle.json",
                {
                    "ticket_id": "IDCEVODEV-960073",
                    "title": "IDCEVODEV-960073",
                    "generated_at_utc": "2026-04-22T18:00:00+00:00",
                    "overall_status": "partial",
                    "profile_ids": ["NA8", "G78", "G50"],
                    "blockers": [],
                    "next_questions": [],
                },
            )

            latest = load_latest_review_package("IDCEVODEV-960073", root)
            expected_package_root = fixture["package_root"].resolve()

        self.assertEqual(Path(latest["package_root"]).resolve(), expected_package_root)
        self.assertFalse(latest["nested_reference"])

    def test_build_review_board_state_merges_package_and_latest_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = create_review_package_fixture(root)
            set_review_decision(
                "IDCEVODEV-960073",
                "lights_OnlyCones",
                status="follow_up",
                owner="Adrian",
                note="Treat as follow-up unless delivery is blocked.",
                workspace=root,
                fallback_markdown_path=fixture["package_root"] / "review-owner-decisions.md",
            )
            add_external_finding(
                "IDCEVODEV-960073",
                source="Teams / 3D Car - Bug Reports / Jana",
                reported_by="Jana",
                category="changelog",
                scope=["G50", "NA8"],
                finding="Missing changelog entry for light cones position change",
                owner="Ana-Karina Nazare",
                status="reported",
                note="Potentially related to light-cone positioning work.",
                finding_type="changelog finding",
                related_investigation_surfaces=["lights_OnlyCones", "Pivot Master", "parking_asset_info.json"],
                workspace=root,
            )

            state = build_review_board_state("IDCEVODEV-960073", root)
            expected_package_root = fixture["package_root"].resolve()

        self.assertEqual(state["ticket_id"], "IDCEVODEV-960073")
        self.assertEqual(state["scope"], ["NA8", "G78", "G50"])
        self.assertEqual(state["screenshot_battery_counts"]["exact_candidate_ready"], 1)
        self.assertEqual(state["screenshot_battery_counts"]["proxy_candidate_ready"], 1)
        self.assertEqual(state["screenshot_battery_counts"]["runtime_crash"], 1)
        self.assertEqual(state["unresolved_families"], ["lights_OnlyCones"])
        self.assertEqual(state["review_priority"]["source"], "daily_snapshot")
        self.assertEqual(state["daily_delta"]["source"], "daily_snapshot")
        self.assertTrue(state["daily_delta_summary"]["has_previous_run"])
        self.assertEqual(state["daily_delta_summary"]["unchanged_blockers_count"], 1)
        self.assertEqual(Path(state["package_path"]).resolve(), expected_package_root)
        self.assertTrue(state["artifact_references"]["candidate_gallery"]["exists"])
        self.assertIn("IDCEVODEV-960073 QA status", state["review_owner_update_text"])
        self.assertIn("Daily 3D Car QA Digest", state["morning_digest_text"])
        self.assertEqual(state["morning_digest"]["ticket_id"], "IDCEVODEV-960073")
        self.assertEqual(state["review_owner_decisions"]["pending_count"], 1)
        self.assertEqual(state["review_owner_decisions"]["sections"][0]["status"], "follow_up")
        self.assertEqual(state["external_findings"]["count"], 1)
        self.assertIn("lights_OnlyCones", state["external_findings"]["related_investigation_surfaces"])
        self.assertEqual(state["top_review_priority_items"][0]["priority_level"], "P0")
        self.assertEqual(len(state["manual_review_profiles"]), 3)
        self.assertEqual(state["manual_review_profiles"][0]["profile_id"], "NA8")
        self.assertEqual(state["manual_review_profiles"][0]["status"], "pending")
        self.assertTrue(state["manual_review_profiles"][0]["raco_scene"]["exists"])
        self.assertTrue(state["manual_review_profiles"][0]["blender_workfile"]["exists"])
        self.assertIn("manual review", state["manual_review_profiles"][0]["copy_review_note_text"].lower())

    def test_verify_sendable_package_reports_warning_when_optional_package_json_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = create_review_package_fixture(root)

            verification = verify_sendable_package(fixture["zip_path"], root)

        self.assertEqual(verification["status"], "warning")
        self.assertTrue(verification["sha256_match"])
        self.assertEqual(verification["errors"], [])
        self.assertIn("review_priority_json", verification["optional_files"])

    def test_load_helpers_return_structured_json_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_review_package_fixture(root)

            packages = list_review_packages(root)
            snapshot = load_latest_daily_snapshot(root)
            priority = load_review_priority("IDCEVODEV-960073", root)
            delta = load_daily_delta("IDCEVODEV-960073", root)
            decisions = load_review_owner_decisions("IDCEVODEV-960073", root)
            external = load_external_review_findings("IDCEVODEV-960073", root)

        self.assertEqual(len(packages), 1)
        self.assertEqual(snapshot["summary"]["smoke_completed"], 3)
        self.assertEqual(priority["top_items"][0]["filter_name"], "lights_OnlyCones")
        self.assertEqual(priority["top_items"][0]["priority_level"], "P0")
        self.assertEqual(delta["top_five_to_review"][0], "NA8: `default` generated a candidate output; baseline approval can be done quickly.")
        self.assertGreaterEqual(decisions["pending_count"], 1)
        self.assertEqual(external["count"], 0)
