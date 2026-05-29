"""H-30 tests for the consolidated profile dashboard HTML composer."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sg_preflight.profile_summary import (
    PROFILE_SUMMARY_SCHEMA_VERSION,
    ProfileSummary,
    build_profile_summary,
    redact_personal_paths,
    render_profile_summary_html,
    sanitize_text,
    write_profile_summary_html,
)


class RedactionTests(unittest.TestCase):
    def test_redact_personal_paths_replaces_user_segment(self) -> None:
        self.assertEqual(
            redact_personal_paths(r"C:\Users\someoperator\repos\foo.txt"),
            r"C:\Users\<operator>\repos\foo.txt",
        )
        # Drive-letter case-insensitivity.
        self.assertEqual(
            redact_personal_paths(r"d:\Users\AliceB\Documents"),
            r"d:\Users\<operator>\Documents",
        )
        # Already-redacted path is untouched (idempotent).
        self.assertEqual(
            redact_personal_paths(r"C:\Users\<operator>\repos"),
            r"C:\Users\<operator>\repos",
        )

    def test_sanitize_text_masks_pat_like_tokens(self) -> None:
        result = sanitize_text("token=abcdef1234567890abcdef1234567890XYZW")
        self.assertNotIn("abcdef1234567890abcdef1234567890XYZW", result)
        self.assertIn("****XYZW", result)

    def test_sanitize_text_preserves_git_sha_and_exe_sha(self) -> None:
        # 40-char hex git SHA stays intact.
        git_sha = "0123456789abcdef0123456789abcdef01234567"
        self.assertEqual(sanitize_text(git_sha), git_sha)
        # 64-char hex .exe SHA stays intact.
        exe_sha = "0123456789abcdef" * 4
        self.assertEqual(sanitize_text(exe_sha), exe_sha)


class RenderTests(unittest.TestCase):
    def _minimal_summary(self, **overrides) -> ProfileSummary:
        defaults = {
            "profile_id": "G70",
            "generated_at_utc": "2026-05-29T11:30:00Z",
            "build_commit": "abc1234",
            "exe_sha256": "deadbeef",
            "workbook": {"status": "unavailable", "candidate_count": 0},
            "risk_score": {"status": "unavailable"},
            "jira_tickets": {"status": "unavailable", "summary": "No tickets", "tickets": []},
            "full_qa_runs": [],
            "manual_review": {},
            "notes": [],
        }
        defaults.update(overrides)
        return ProfileSummary(**defaults)

    def test_render_emits_self_contained_dark_theme_html(self) -> None:
        summary = self._minimal_summary()
        html = render_profile_summary_html(summary)
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("--sgfx-bg: #1e1e1e", html)
        self.assertIn("Manual review remains required.", html)
        self.assertIn("Decision: not approval — evidence only.", html)
        self.assertIn("PDX_SERGFX/139_3D-Car/298_Quality-Hero-How-to-review-the-3D-car", html)
        # Sparkline placeholder slot stays empty when not provided.
        self.assertNotIn("sgfx-sparkline\">", html)

    def test_render_honest_classification_for_auto_generated_workbook(self) -> None:
        summary = self._minimal_summary(workbook={
            "status": "available",
            "selected": {
                "path": r"C:\Users\someone\sgfx_outputs\g70\delivery-workbook\G70_auto_20260529.xlsx",
                "source_classification": "auto_generated_locally",
                "workbook_format": "format_a_date_stamped",
                "mtime_iso": "2026-05-29T11:00:00Z",
                "size_bytes": 6128,
            },
            "candidate_count": 1,
        })
        html = render_profile_summary_html(summary)
        # Personal Windows path was redacted before render.
        self.assertNotIn(r"C:\Users\someone", html)
        # `<operator>` is HTML-escaped to `&lt;operator&gt;` when rendered.
        self.assertIn(r"C:\Users\&lt;operator&gt;", html)
        # Classification visible verbatim.
        self.assertIn("Auto-generated locally", html)
        self.assertIn("sgfx-classification-auto_generated_locally", html)

    def test_render_jira_tickets_with_url_renders_clickable_anchor(self) -> None:
        summary = self._minimal_summary(jira_tickets={
            "status": "available",
            "tickets": [
                {
                    "key": "IDCEVODEV-1009244",
                    "status": "In Review",
                    "summary": "F70 delivery checklist",
                    "url": "https://jira.cc.bmwgroup.net/browse/IDCEVODEV-1009244",
                }
            ],
        })
        html = render_profile_summary_html(summary)
        self.assertIn('target="_blank"', html)
        self.assertIn('rel="noopener noreferrer"', html)
        self.assertIn("IDCEVODEV-1009244", html)
        self.assertIn("https://jira.cc.bmwgroup.net/browse/IDCEVODEV-1009244", html)

    def test_render_includes_recent_runs_when_history_provided(self) -> None:
        runs = [
            {"completed_at_utc": "2026-05-28T20:00:00Z", "status": "incomplete", "summary": "manual review pending", "passed_steps": 5, "incomplete_steps": 4, "failed_steps": 0, "risk_score": 42, "risk_level": "yellow"},
            {"completed_at_utc": "2026-05-29T08:00:00Z", "status": "incomplete", "summary": "rerun", "passed_steps": 7, "incomplete_steps": 2, "failed_steps": 0, "risk_score": 35, "risk_level": "yellow"},
        ]
        summary = self._minimal_summary(full_qa_runs=runs)
        html = render_profile_summary_html(summary)
        self.assertIn("Recent Full QA Pass runs", html)
        self.assertIn("2026-05-28T20:00:00Z", html)
        self.assertIn("risk 42", html)
        self.assertIn("passed 5 · incomplete 4 · failed 0", html)

    def test_render_with_sparkline_inserts_svg_inline(self) -> None:
        summary = self._minimal_summary()
        spark = '<svg xmlns="http://www.w3.org/2000/svg" width="60" height="14"></svg>'
        html = render_profile_summary_html(summary, sparkline_svg=spark)
        self.assertIn("sgfx-sparkline", html)
        self.assertIn(spark, html)

    def test_render_with_sparkline_fallback_uses_honest_text(self) -> None:
        summary = self._minimal_summary()
        html = render_profile_summary_html(summary, sparkline_fallback_text="Insufficient history (2 runs)")
        self.assertIn("Insufficient history", html)
        self.assertIn("sgfx-sparkline-fallback", html)


class BuildTests(unittest.TestCase):
    def test_build_against_empty_workspace_returns_unavailable_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "workspace"
            ws.mkdir()
            (ws / "operator_state").mkdir()
            summary = build_profile_summary(
                "F70",
                workspace=ws,
                home=Path(tmp) / "home",
                history_limit=5,
                build_commit="abc",
                exe_sha256="xyz",
            )
            payload = summary.to_payload()
            self.assertEqual(payload["schema_version"], PROFILE_SUMMARY_SCHEMA_VERSION)
            self.assertEqual(payload["profile_id"], "F70")
            self.assertEqual(payload["workbook"].get("status"), "unavailable")
            self.assertEqual(payload["full_qa_runs"], [])

    def test_build_pulls_in_run_history_when_present(self) -> None:
        from sg_preflight.full_qa_history import record_full_qa_run_history

        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "workspace"
            home = Path(tmp) / "home"
            ws.mkdir()
            (ws / "operator_state").mkdir()
            home.mkdir()
            # Two synthetic runs so the list-based history surfaces in the summary.
            for index, status in enumerate(("incomplete", "incomplete"), start=1):
                record_full_qa_run_history(
                    "F70",
                    {"status": status, "summary": f"run {index}", "steps": [{"status": "passed"}, {"status": "incomplete"}]},
                    home=home,
                    completed_at_utc=f"2026-05-29T0{index}:00:00Z",
                )
            summary = build_profile_summary(
                "F70",
                workspace=ws,
                home=home,
                history_limit=5,
                build_commit="abc",
                exe_sha256="xyz",
            )
            self.assertEqual(len(summary.full_qa_runs), 2)
            # Newest-first ordering.
            self.assertEqual(summary.full_qa_runs[0]["completed_at_utc"], "2026-05-29T02:00:00Z")
            self.assertEqual(summary.full_qa_runs[1]["completed_at_utc"], "2026-05-29T01:00:00Z")

    def test_write_profile_summary_html_persists_self_contained_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "summary.html"
            summary = ProfileSummary(
                profile_id="G70",
                generated_at_utc="2026-05-29T11:30:00Z",
                build_commit="abc1234",
                exe_sha256="deadbeef",
            )
            write_profile_summary_html(summary, output)
            self.assertTrue(output.is_file())
            text = output.read_text(encoding="utf-8")
            self.assertIn("<!DOCTYPE html>", text)
            self.assertIn("--sgfx-bg: #1e1e1e", text)
            self.assertIn("Manual review remains required.", text)


class FullQaHistoryListTests(unittest.TestCase):
    """H-30 needs an append-only run list rather than the H-22 single-record shape."""

    def test_record_appends_to_runs_list_and_keeps_legacy_top_level_fields(self) -> None:
        from sg_preflight.full_qa_history import read_full_qa_run_list, record_full_qa_run_history

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            for index in range(3):
                record_full_qa_run_history(
                    "G70",
                    {"status": "incomplete", "summary": f"run {index}", "steps": []},
                    home=home,
                    completed_at_utc=f"2026-05-29T0{index}:00:00Z",
                )
            runs = read_full_qa_run_list("G70", home=home, limit=10)
            self.assertEqual(len(runs), 3)
            # Newest-first.
            self.assertEqual(runs[0]["completed_at_utc"], "2026-05-29T02:00:00Z")
            self.assertEqual(runs[2]["completed_at_utc"], "2026-05-29T00:00:00Z")

    def test_run_list_enforces_retention_bound(self) -> None:
        from sg_preflight.full_qa_history import read_full_qa_run_list, record_full_qa_run_history

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            for index in range(15):
                record_full_qa_run_history(
                    "G70",
                    {"status": "incomplete", "summary": f"r{index}", "steps": []},
                    home=home,
                    completed_at_utc=f"2026-05-29T{index:02d}:00:00Z",
                    runs_retained=10,
                )
            runs = read_full_qa_run_list("G70", home=home, limit=20)
            self.assertEqual(len(runs), 10)
            # Oldest five were dropped; newest is run 14.
            self.assertEqual(runs[0]["completed_at_utc"], "2026-05-29T14:00:00Z")

    def test_legacy_single_record_history_falls_back_to_synthetic_list(self) -> None:
        """Pre-H-30 history files have no `runs` key; the reader must still
        surface their single record so the sparkline/profile summary work
        out-of-the-box on existing operator state."""
        from sg_preflight.full_qa_history import full_qa_run_history_path, read_full_qa_run_list

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            target = full_qa_run_history_path("G70", home=home)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps({
                    "schema_version": 1,
                    "profile_id": "G70",
                    "last_successful_run_at": "2026-05-20T08:00:00Z",
                    "last_status": "incomplete",
                    "last_summary": "legacy",
                    "passed_steps": 4,
                    "incomplete_steps": 5,
                    "failed_steps": 0,
                }),
                encoding="utf-8",
            )
            runs = read_full_qa_run_list("G70", home=home, limit=5)
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]["completed_at_utc"], "2026-05-20T08:00:00Z")
            self.assertEqual(runs[0]["status"], "incomplete")


if __name__ == "__main__":
    unittest.main()
