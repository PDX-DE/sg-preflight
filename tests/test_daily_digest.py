from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sg_preflight.daily_digest import build_daily_digest, render_daily_digest_markdown
from sg_preflight.review_state import build_review_board_state
from sg_preflight.review_tracking import set_review_decision
from tests.operator_helpers import create_review_package_fixture


class TestDailyDigest(unittest.TestCase):
    def test_daily_digest_json_separates_review_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = create_review_package_fixture(root)
            set_review_decision(
                "IDCEVODEV-960073",
                "lights_OnlyCones",
                status="pending",
                owner="Adrian",
                note="Awaiting owner follow-up before reviewer decision.",
                workspace=root,
                fallback_markdown_path=fixture["package_root"] / "review-owner-decisions.md",
            )
            state = build_review_board_state("IDCEVODEV-960073", root)

        digest = build_daily_digest(state)
        sections = digest["sections"]

        self.assertEqual(digest["ticket_id"], "IDCEVODEV-960073")
        self.assertEqual(digest["delivery_mode"], "opt_in_manual")
        self.assertIn("not a visual approval", digest["guardrails"])
        self.assertTrue(sections["evidence_prepared"]["items"])
        self.assertTrue(sections["blockers"]["items"])
        self.assertTrue(sections["manual_review_pending"]["items"])
        self.assertTrue(sections["waiting_for_owner"]["items"])
        owned_waiting_items = [
            item for item in sections["waiting_for_owner"]["items"] if item.get("owner") == "Adrian"
        ]
        self.assertTrue(owned_waiting_items)
        self.assertTrue(sections["suggested_review_order"]["items"])
        self.assertIn(
            "Suggested review order only",
            sections["suggested_review_order"]["items"][0]["guidance"],
        )
        self.assertNotIn("approved", sections["suggested_review_order"]["items"][0]["guidance"].lower())
        self.assertNotIn("validated", sections["suggested_review_order"]["items"][0]["guidance"].lower())
        self.assertIn("[waiting_for_adrian]", digest["markdown"])
        self.assertNotIn("approved", digest["markdown"].lower())
        self.assertNotIn("validated", digest["markdown"].lower())

    def test_daily_digest_markdown_renders_clean_empty_state(self) -> None:
        digest = build_daily_digest(
            {
                "ticket_id": "IDCEVODEV-EMPTY",
                "scope": ["G70"],
                "daily_snapshot_created_at": "2026-05-14T06:30:00",
                "daily_snapshot_summary": {"smoke_completed": 0, "smoke_total": 0},
                "screenshot_battery_counts": {"total": 0},
                "daily_delta_summary": {
                    "new_failures_count": 0,
                    "resolved_failures_count": 0,
                    "new_screenshot_diffs_count": 0,
                    "unchanged_blockers_count": 0,
                    "operator_signal": "",
                },
                "daily_delta": {
                    "new_failures": [],
                    "new_screenshot_diffs": [],
                    "unchanged_blockers": [],
                    "resolved_failures": [],
                    "top_five_to_review": [],
                },
                "review_owner_decisions": {"sections": [], "pending_titles": []},
                "manual_review_profiles": [],
                "artifact_references": {},
                "top_review_priority_items": [],
                "open_items": [],
            }
        )

        markdown = render_daily_digest_markdown(digest)

        self.assertIn("# Daily 3D Car QA Digest - IDCEVODEV-EMPTY", markdown)
        self.assertIn("Opt-in local summary", markdown)
        self.assertIn("No evidence artifacts recorded in the current state.", markdown)
        self.assertIn("No blockers recorded in the current state.", markdown)
        self.assertIn("No manual review items recorded in the current state.", markdown)
        self.assertIn("No waiting-for-owner items recorded in the current state.", markdown)
        self.assertIn("No suggested review-order items recorded in the current state.", markdown)
        self.assertIn("Manual review remains required", markdown)
        self.assertNotIn("approved", markdown.lower())
        self.assertNotIn("validated", markdown.lower())

    def test_daily_digest_surfaces_what_landed_today_without_release_claim(self) -> None:
        digest = build_daily_digest(
            {
                "ticket_id": "IDCEVODEV-LANDED",
                "scope": ["G65"],
                "daily_snapshot_summary": {"smoke_completed": 0, "smoke_total": 0},
                "screenshot_battery_counts": {"total": 0},
                "daily_delta_summary": {
                    "new_failures_count": 0,
                    "resolved_failures_count": 0,
                    "new_screenshot_diffs_count": 0,
                    "unchanged_blockers_count": 0,
                    "operator_signal": "",
                },
                "daily_delta": {
                    "new_failures": [],
                    "new_screenshot_diffs": [],
                    "unchanged_blockers": [],
                    "resolved_failures": [],
                    "top_five_to_review": [],
                },
                "review_owner_decisions": {"sections": [], "pending_titles": []},
                "manual_review_profiles": [],
                "artifact_references": {},
                "top_review_priority_items": [],
                "open_items": [],
                "what_landed_today": [
                    {
                        "short_sha": "0fe84c3",
                        "subject": "feat(checkers): surface BMW Git readiness",
                        "committed_at": "2026-05-15 10:15:00 +0200",
                    }
                ],
            }
        )

        items = digest["sections"]["what_landed_today"]["items"]

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["status"], "local_commit")
        self.assertIn("0fe84c3", items[0]["detail"])
        self.assertIn("local change log", items[0]["guidance"].lower())
        self.assertIn("What landed today", digest["markdown"])
        self.assertNotIn("approved", digest["markdown"].lower())
        self.assertNotIn("validated", digest["markdown"].lower())
        self.assertNotIn("deployed", digest["markdown"].lower())

    def test_daily_digest_surfaces_workflow_status_without_verdict_claim(self) -> None:
        digest = build_daily_digest(
            {
                "ticket_id": "IDCEVODEV-WORKFLOW",
                "scope": ["G65"],
                "daily_snapshot_summary": {"smoke_completed": 0, "smoke_total": 0},
                "screenshot_battery_counts": {"total": 0},
                "daily_delta_summary": {
                    "new_failures_count": 0,
                    "resolved_failures_count": 0,
                    "new_screenshot_diffs_count": 0,
                    "unchanged_blockers_count": 0,
                    "operator_signal": "",
                },
                "daily_delta": {
                    "new_failures": [],
                    "new_screenshot_diffs": [],
                    "unchanged_blockers": [],
                    "resolved_failures": [],
                    "top_five_to_review": [],
                },
                "review_owner_decisions": {"sections": [], "pending_titles": []},
                "manual_review_profiles": [],
                "artifact_references": {},
                "top_review_priority_items": [],
                "open_items": [],
                "qa_workflow_status": [
                    {
                        "key": "delivery_checklist",
                        "label": "BMW delivery checklist bridge",
                        "state": "blocked",
                        "summary": "The mirrored delivery assets are not complete on this machine.",
                        "blockers": ["Missing deliveryChecklist helper."],
                    },
                    {
                        "key": "handoff_evidence",
                        "label": "Triage and delivery handoff evidence",
                        "state": "covered",
                        "summary": "Run records and reports are available.",
                        "blockers": [],
                    },
                ],
            }
        )

        items = digest["sections"]["workflow_status"]["items"]
        blocked_items = [item for item in items if item["status"] == "blocked"]

        self.assertEqual(len(items), 2)
        self.assertTrue(blocked_items)
        self.assertIn("Missing deliveryChecklist helper.", blocked_items[0]["detail"])
        self.assertIn("status snapshot only", blocked_items[0]["guidance"])
        self.assertIn("Workflow status", digest["markdown"])
        self.assertIn("Manual review remains required", digest["markdown"])
        self.assertNotIn("approval", digest["sections"]["workflow_status"]["heading"].lower())
        self.assertNotIn("validated", digest["markdown"].lower())

    def test_daily_digest_surfaces_screenshot_test_state_as_guidance_not_verdict(self) -> None:
        digest = build_daily_digest(
            {
                "ticket_id": "IDCEVODEV-SCREEN",
                "scope": ["G65"],
                "daily_snapshot_summary": {"smoke_completed": 0, "smoke_total": 0},
                "screenshot_battery_counts": {"total": 0},
                "daily_delta_summary": {
                    "new_failures_count": 0,
                    "resolved_failures_count": 0,
                    "new_screenshot_diffs_count": 0,
                    "unchanged_blockers_count": 0,
                    "operator_signal": "",
                },
                "daily_delta": {
                    "new_failures": [],
                    "new_screenshot_diffs": [],
                    "unchanged_blockers": [],
                    "resolved_failures": [],
                    "top_five_to_review": [],
                },
                "review_owner_decisions": {"sections": [], "pending_titles": []},
                "manual_review_profiles": [],
                "artifact_references": {},
                "top_review_priority_items": [],
                "open_items": [],
                "bmw_screenshot_state": [
                    {
                        "profile_id": "G65",
                        "matched_profile_id": "G65_EVO",
                        "status": "available",
                        "expected_count": 85,
                        "actual_count": 34,
                        "diff_count": 0,
                        "disabled_test_count": 2,
                        "expected_root": r"C:\3D Car git\digital-3d-car-models\cars\BMW\G65_EVO\export\tests\expected",
                        "note": "Read-only screenshot test state; manual review remains required.",
                        "is_approval": False,
                    }
                ],
            }
        )

        items = digest["sections"]["evidence_prepared"]["items"]
        screenshot_items = [item for item in items if item.get("source") == "bmw_screenshot_state"]

        self.assertEqual(len(screenshot_items), 1)
        self.assertIn("85 expected / 34 actual / 0 diff", screenshot_items[0]["detail"])
        self.assertIn("Suggested screenshot review input only", screenshot_items[0]["guidance"])
        self.assertFalse(screenshot_items[0]["is_approval"])
        self.assertIn("Screenshot test state", digest["markdown"])
        self.assertNotIn("approved", digest["markdown"].lower())
        self.assertNotIn("validated", digest["markdown"].lower())


if __name__ == "__main__":
    unittest.main()
