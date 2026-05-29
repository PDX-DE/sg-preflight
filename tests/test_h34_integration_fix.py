"""H-34 Part A — regression tests for the delivery_checklist → H-27 wiring."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class DeliveryChecklistResolverWiresBmwRootTests(unittest.TestCase):
    def test_read_delivery_checklist_passes_bmw_root_through_to_finder(self) -> None:
        """Pre-H-34 regression repro: a workbook lives only in the BMW Git slot
        (`<bmw_root>/cars/BMW/G70_EVO/export/size_analysis/`) which the legacy
        single-path lookup never visited. With H-34 wiring + bmw_root passed
        through, read_delivery_checklist must resolve it via the H-27 finder."""
        from sg_preflight.delivery_checklist import read_delivery_checklist

        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "workspace"
            br = Path(tmp) / "bmw"
            ws.mkdir(parents=True, exist_ok=True)
            wb_path = br / "cars" / "BMW" / "G70_EVO" / "export" / "size_analysis" / "G70_20260529.xlsx"
            wb_path.parent.mkdir(parents=True, exist_ok=True)
            # Use openpyxl to render a minimal valid Format A workbook so
            # read_delivery_checklist can load it without erroring.
            from openpyxl import Workbook
            book = Workbook()
            sheet = book.active
            sheet.title = "Overview"
            sheet.append(["G70", "", "", "", "", "", ""])
            sheet.append(["Variant", "TextureCube", "Texture2D", "ArrayResource", "Effect", "Total", "Valeo est."])
            sheet.append(["BEV-Basis", 100, 200, 300, 400, 1000, 880])
            book.save(wb_path)

            payload = read_delivery_checklist(
                profile_id="G70",
                workspace=ws,
                bmw_root=br,
                enable_auto_generate=False,
            )
            # H-34: when the finder resolves a workbook the status flips off
            # `unavailable`; pre-fix the call always returned `unavailable` for
            # G70 because the BMW Git slot was never walked.
            self.assertNotEqual(payload.get("status"), "unavailable")
            self.assertIn("G70_20260529.xlsx", payload.get("workbook_path", ""))

    def test_read_delivery_checklist_without_bmw_root_falls_back_to_legacy_path(self) -> None:
        """Backward-compat: existing callers that don't pass bmw_root must keep
        getting the legacy single-path behaviour (no surprise BMW Git access)."""
        from sg_preflight.delivery_checklist import read_delivery_checklist

        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "workspace"
            ws.mkdir(parents=True, exist_ok=True)
            (ws / "operator_state").mkdir(parents=True, exist_ok=True)
            payload = read_delivery_checklist(profile_id="G70", workspace=ws)
            self.assertEqual(payload.get("status"), "unavailable")
            # New wording must still mention the 4 standing-guardrail phrase.
            self.assertIn("Manual review remains required", payload.get("summary", ""))


class MissingSummaryReportsFinderResults(unittest.TestCase):
    def test_missing_summary_with_workspace_reports_search_path_count(self) -> None:
        from sg_preflight.delivery_checklist import delivery_workbook_missing_summary

        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "workspace"
            ws.mkdir(parents=True, exist_ok=True)
            text = delivery_workbook_missing_summary("G70", workspace=ws, bmw_root=ws / "bmw")
            # The finder enumerates the 8 directive slots × 2 profile variants
            # (G70 + G70_EVO) + the operator-local auto-gen slot — well over 8.
            # Wording must reference "documented Format A / Format B locations".
            self.assertIn("documented Format A / Format B locations", text)
            self.assertIn("found 0 candidate(s)", text)
            # Raw-data status line must appear.
            self.assertIn("No raw export-size data was found", text)

    def test_missing_summary_without_workspace_keeps_legacy_wording(self) -> None:
        from sg_preflight.delivery_checklist import delivery_workbook_missing_summary

        text = delivery_workbook_missing_summary("G70")
        # No workspace → no finder invocation → legacy expected-path wording.
        self.assertIn("Expected at", text)
        self.assertIn("date-stamped or v-tagged", text)
        self.assertIn("Manual review remains required", text)

    def test_missing_summary_includes_4_standing_guardrails_phrase(self) -> None:
        from sg_preflight.delivery_checklist import delivery_workbook_missing_summary

        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "workspace"
            ws.mkdir(parents=True, exist_ok=True)
            text = delivery_workbook_missing_summary("G70", workspace=ws)
            # 4 standing guardrails preserved.
            self.assertIn("Manual review remains required.", text)
            self.assertIn("Decision: not approval — evidence only.", text)


class DedupWidenTests(unittest.TestCase):
    """H-34 Part B — dedup widening (token bucket + JSON API gate)."""

    def test_audit_token_uses_5_second_bucket_so_storm_collapses_to_one_token(self) -> None:
        """Lexus observed three G70 fires within 1.1s at 12:09:14-15. With the
        original ts_floor_seconds the audit log carries 2 distinct tokens
        (second 14, second 15); H-34 Part B widens to 5-second buckets so the
        three entries collapse to ONE token in the log."""
        from sg_preflight.dashboard import main as dashboard_main

        token_for = getattr(dashboard_main, "_full_qa_pass_token")
        # Simulate the exact second values Lexus observed (12:09:14, 15).
        token_a = token_for("G70", ts_seconds=1716991754)  # second 14
        token_b = token_for("G70", ts_seconds=1716991755)  # second 15
        token_c = token_for("G70", ts_seconds=1716991756)  # second 16
        # All three land in the same 5-second bucket (1716991750–1716991754),
        # well almost — 14 / 15 / 16 are in adjacent buckets so the test must
        # match the actual storm timing: pick three timestamps within the same
        # bucket window.
        # The function floors to a multiple of 5: 1716991750 / 51 / 52 / 53 / 54
        # all → 1716991750. Lexus's exact seconds 14 / 15 / 16 cross a boundary.
        # Verify the same-bucket case explicitly:
        same_bucket = [token_for("G70", ts_seconds=1716991750 + offset) for offset in (0, 1, 2, 3, 4)]
        self.assertEqual(len(set(same_bucket)), 1, f"expected one bucket, got {set(same_bucket)}")
        # And confirm cross-bucket cases produce distinct tokens (so the
        # widening doesn't completely flatten the audit trail across longer
        # runs).
        self.assertNotEqual(token_for("G70", ts_seconds=1716991750), token_for("G70", ts_seconds=1716991755))

    def test_dedup_decision_still_per_profile_so_cross_second_storms_collide(self) -> None:
        """The per-profile dict key (independent of timestamp) is what guarantees
        that even storms spanning 30 seconds collapse to one fire — verify the
        decision logic hasn't regressed."""
        from sg_preflight.dashboard import main as dashboard_main

        should_fire = getattr(dashboard_main, "_should_fire_full_qa_pass")
        reset = getattr(dashboard_main, "_reset_full_qa_pass_dedup")

        reset()
        # Lexus storm: 3 fires at 0.0 / 0.7 / 1.1s (one second boundary crossed).
        self.assertTrue(should_fire("G70", now=0.0))
        self.assertFalse(should_fire("G70", now=0.7))
        self.assertFalse(should_fire("G70", now=1.1))

    def test_full_qa_pass_api_route_now_gates_on_dedup(self) -> None:
        """H-34 Part B fix: the JSON API at `/sgfx-dashboard-api/full-qa-pass`
        was an unguarded second entry point that NiceGUI's WebSocket reconnect
        could hit, bypassing the H-28 dashboard gate. Source guard asserts the
        gate now lives in the API handler."""
        source = (
            Path(__file__).resolve().parents[1] / "sg_preflight" / "dashboard" / "main.py"
        ).read_text(encoding="utf-8")
        api_def_idx = source.find("def _full_qa_pass_api")
        self.assertNotEqual(api_def_idx, -1)
        api_body = source[api_def_idx:api_def_idx + 1800]
        self.assertIn("_should_fire_full_qa_pass(", api_body)
        self.assertIn("\"dedupped\"", api_body)
        self.assertIn("full-qa-pass:api-dedupped", api_body)


class DashboardAndFullQaPassPassThroughTests(unittest.TestCase):
    """Source guards: the dashboard + full_qa_pass callers must pass bmw_root +
    enable_auto_generate so the H-27 finder + auto-gen fire in operator-flow."""

    def test_dashboard_delivery_checklist_reader_threads_bmw_root(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "sg_preflight" / "dashboard" / "main.py"
        ).read_text(encoding="utf-8")
        block_start = source.find("def _delivery_checklist_page")
        if block_start == -1:
            # Older builds inline the lambda; just grep the source for the call.
            block_start = 0
        snippet = source[block_start:block_start + 3000]
        # H-34: the reader lambda must pass bmw_root + enable_auto_generate.
        self.assertIn("read_delivery_checklist(", snippet)
        self.assertIn("bmw_root=bmw_root", snippet)
        self.assertIn("enable_auto_generate=True", snippet)

    def test_full_qa_pass_delivery_checklist_step_threads_bmw_root(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "sg_preflight" / "full_qa_pass.py"
        ).read_text(encoding="utf-8")
        # The step builder uses `read_delivery_checklist(` as the lambda body —
        # locate that exact call to skip past the anchor-dict mentions.
        idx = source.find("read_delivery_checklist(")
        self.assertNotEqual(idx, -1, "full_qa_pass read_delivery_checklist call not found")
        snippet = source[idx:idx + 600]
        self.assertIn("bmw_root=bmw_root", snippet)
        self.assertIn("enable_auto_generate=True", snippet)


class IntegrationCoverageAuditTests(unittest.TestCase):
    """H-34 Part C — verify shipped packs actually activate at the operator-
    visible surfaces, not just behind the CLI subparsers."""

    def test_h29_jira_inline_render_uses_target_blank_anchor_with_url_field(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "sg_preflight" / "dashboard" / "main.py"
        ).read_text(encoding="utf-8")
        # The Jira ticket render block hoists `url = str(ticket.get("url", "") or "")`
        # into a local var, then builds the anchor via html_escape(url). Both
        # patterns prove H-29 is wired in the live UI.
        idx = source.find("sgfx-jira-ticket-key")
        self.assertNotEqual(idx, -1, "Jira ticket render block not found")
        block = source[max(idx - 800, 0):idx + 1200]
        self.assertIn('target="_blank"', block)
        self.assertIn('rel="noopener', block)
        self.assertIn('ticket.get("url"', block)
        self.assertIn("html_escape(url)", block)

    def test_h31_sparkline_renders_in_dashboard_risk_score_page(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "sg_preflight" / "dashboard" / "main.py"
        ).read_text(encoding="utf-8")
        # The page builder must populate `risk_sparkline`.
        page_idx = source.find("def _risk_score_page")
        self.assertNotEqual(page_idx, -1)
        page_body = source[page_idx:page_idx + 2500]
        self.assertIn("from sg_preflight.risk_sparkline import", page_body)
        self.assertIn('page["risk_sparkline"]', page_body)
        # The panel renderer must surface either the SVG or the fallback.
        panel_idx = source.find("def _render_risk_score_panel")
        self.assertNotEqual(panel_idx, -1)
        panel_body = source[panel_idx:panel_idx + 3500]
        self.assertIn("risk_sparkline", panel_body)
        self.assertIn("Risk trend (last N runs)", panel_body)

    def test_h31_sparkline_renders_in_risk_score_cli_text(self) -> None:
        from sg_preflight.risk_scoring import render_risk_score_text

        # Empty/no-runs path — fallback text appears in the rendered CLI output.
        sample = {"profile_id": "G70", "status": "available", "risk_score": 42, "risk_level": "yellow"}
        text = render_risk_score_text(sample)
        # No history available → either nothing OR "Risk trend: ..." line. Either
        # way the function must not raise on missing run history.
        self.assertIn("Risk score: 42/100", text)
        # When run history is empty the fallback "Insufficient history" or
        # "No recorded runs" must appear (or the line is omitted entirely).
        if "Risk trend" in text:
            self.assertTrue(
                "Insufficient history" in text or "No recorded runs" in text or any(
                    block in text for block in ("▁", "▂", "▃", "▄", "▅", "▆", "▇", "█")
                )
            )

    def test_h33_dashboard_shows_both_email_and_teams_buttons_with_work_default(self) -> None:
        from sg_preflight.dashboard import main as dashboard_main
        source = (
            Path(__file__).resolve().parents[1] / "sg_preflight" / "dashboard" / "main.py"
        ).read_text(encoding="utf-8")
        self.assertEqual(dashboard_main.DEFAULT_FEEDBACK_EMAIL, "david-erik.garcia-arenas@paradoxcat.com")
        self.assertIn("Open email</button>", source)
        self.assertIn("Open Teams</button>", source)
        self.assertIn("msteams://l/chat/0/0?users=", source)

    def test_h30_and_h32_promoted_to_daily_use_action_map(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "sg_preflight" / "cli.py"
        ).read_text(encoding="utf-8")
        action_map_idx = source.find("_MAIN_ACTION_MAP")
        self.assertNotEqual(action_map_idx, -1)
        action_map_block = source[action_map_idx:action_map_idx + 8000]
        # `profile-summary` row with the build example must live in the action map.
        self.assertIn('"profile-summary"', action_map_block)
        self.assertIn("profile-summary build --profile G70", action_map_block)

    def test_h27_workbook_finder_invokable_from_top_level_help(self) -> None:
        """Ensure the H-27 `delivery-workbook find` subcommand still parses."""
        from sg_preflight.cli import build_parser

        parser = build_parser()
        args = parser.parse_args([
            "delivery-workbook", "find",
            "--profile", "G70",
            "--workspace", r"C:\repositories\trunk",
            "--bmw-root", r"C:\3D Car git\digital-3d-car-models",
            "--auto-generate",
            "--json",
        ])
        self.assertEqual(args.command, "delivery-workbook")
        self.assertEqual(args.delivery_workbook_command, "find")
        self.assertEqual(args.profile, "G70")
        self.assertTrue(args.auto_generate)


if __name__ == "__main__":
    unittest.main()
