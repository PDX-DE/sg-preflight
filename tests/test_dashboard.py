from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


class NiceGuiDashboardLazyImportTests(unittest.TestCase):
    def test_cli_import_and_parser_do_not_import_nicegui(self) -> None:
        sys.modules.pop("nicegui", None)
        sys.modules.pop("sg_preflight.dashboard.main", None)

        from sg_preflight.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "dashboard",
                "run",
                "--profile",
                "G65",
                "--workspace",
                r"C:\repositories\trunk",
                "--no-native",
                "--port",
                "0",
            ]
        )

        self.assertEqual(args.command, "dashboard")
        self.assertEqual(args.dashboard_command, "run")
        self.assertEqual(args.profile, "G65")
        self.assertNotIn("nicegui", sys.modules)
        self.assertNotIn("sg_preflight.dashboard.main", sys.modules)


class NiceGuiDashboardModelTests(unittest.TestCase):
    def test_choice_options_are_nicegui_compatible_lists(self) -> None:
        from sg_preflight.dashboard.main import MANUAL_REVIEW_STATUSES, THEME_CHOICES

        self.assertIsInstance(THEME_CHOICES, list)
        self.assertIsInstance(MANUAL_REVIEW_STATUSES, list)

    def test_dashboard_snapshot_contains_four_operator_pages_and_guardrails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from sg_preflight.dashboard.main import build_dashboard_snapshot

            snapshot = build_dashboard_snapshot("G65", tmp)

        page_ids = [page["id"] for page in snapshot["pages"]]
        self.assertEqual(
            page_ids,
            [
                "delivery-checklist",
                "screenshot-test-state",
                "daily-digest",
                "manual-review",
            ],
        )
        self.assertEqual(snapshot["profile_id"], "G65")
        self.assertEqual(snapshot["theme"], "clean")
        self.assertEqual(snapshot["workspace_label"], Path(tmp).name)
        self.assertEqual(
            snapshot["navigation"],
            [
                {"id": "delivery-checklist", "label": "Delivery Checklist"},
                {"id": "screenshot-test-state", "label": "Screenshot Test State"},
                {"id": "daily-digest", "label": "Daily Digest"},
                {"id": "manual-review", "label": "Manual Review Companion"},
            ],
        )
        self.assertEqual(
            snapshot["shortcuts"],
            ["F1 Help", "F2 Profile switch", "F5 Refresh page", "F12 Diagnostic", "Esc Quit"],
        )
        self.assertEqual(snapshot["pages"][0]["tagline"], "Workbook evidence per delivery profile (read-only).")
        self.assertEqual(snapshot["pages"][1]["tagline"], "BMW + MINI baseline / actual / diff counts per brand.")
        self.assertEqual(snapshot["pages"][2]["tagline"], "Morning status snapshot for the SG Daily standup.")
        self.assertEqual(
            snapshot["pages"][3]["tagline"],
            "Step through the 7 Quality-Hero review steps. Operator verdict per step.",
        )
        self.assertIn("Manual review remains required.", snapshot["guardrails"])
        self.assertIn("Decision: not approval - evidence only.", snapshot["guardrails"])
        self.assertIn("BMW Git access is read-only. SGFX never modifies BMW source.", snapshot["guardrails"])
        self.assertIn("Activity log is local-only - never posted to Jira, SVN, or BMW Git.", snapshot["guardrails"])
        for forbidden in ("approved", "cleared", "signed-off", "production-ready"):
            self.assertNotIn(forbidden, json.dumps(snapshot, ensure_ascii=False).casefold())

    def test_manual_review_state_save_is_operator_local_and_rejects_approval_words(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from sg_preflight.dashboard.main import save_manual_review_state

            payload = save_manual_review_state(
                profile_id="G65",
                workspace=tmp,
                step_slug="blender_visual_check",
                status="captured",
                note="Checked Blender and RaCo side by side.",
            )
            path = Path(tmp) / "operator_state" / "manual_review_G65.json"

            self.assertTrue(path.is_file())
            self.assertEqual(payload["profile_id"], "G65")
            self.assertEqual(payload["steps"]["blender_visual_check"]["status"], "captured")
            self.assertEqual(payload["steps"]["blender_visual_check"]["recorded_by_tool"], False)

            with self.assertRaises(ValueError):
                save_manual_review_state(
                    profile_id="G65",
                    workspace=tmp,
                    step_slug="blender_visual_check",
                    status="approved",
                    note="bad",
                )
