from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from sg_preflight.cli import main
from sg_preflight.daily_digest import build_latest_daily_digest
from sg_preflight.manual_review import (
    QUALITY_HERO_STEP_TITLES,
    VALID_VERDICTS,
    create_manual_review_session,
    load_manual_review_session,
    record_manual_review_step,
    render_manual_review_markdown,
)


class TestManualReviewCompanion(unittest.TestCase):
    def test_create_session_populates_quality_hero_steps_without_verdicts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            session = create_manual_review_session(
                profile_id="G65",
                ticket_id="IDCEVODEV-977874",
                workspace=root,
                session_id="manual-001",
            )

            session_path = Path(session["session_path"])
            self.assertTrue(session_path.exists())
            self.assertEqual(session["profile_id"], "G65")
            self.assertEqual(session["ticket_id"], "IDCEVODEV-977874")
            self.assertEqual([step["title"] for step in session["steps"]], list(QUALITY_HERO_STEP_TITLES))
            self.assertTrue(all(step["verdict"] == "pending" for step in session["steps"]))
            self.assertTrue(all(step["recorded_by_tool"] is False for step in session["steps"]))

            markdown = render_manual_review_markdown(session)
            self.assertIn(
                "Manual review companion. Operator records the verdict per step. Not a tool-generated review or approval.",
                markdown,
            )
            self.assertIn("Blender Visual Check", markdown)
            self.assertIn("CarPaints Test RaCo", markdown)
            self.assertNotIn("automated visual approval", markdown.lower())

    def test_record_step_captures_explicit_reviewer_verdict_note_and_screenshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            screenshot = root / "evidence" / "blender-front.png"
            screenshot.parent.mkdir(parents=True)
            screenshot.write_bytes(b"fake png bytes")
            create_manual_review_session(
                profile_id="G65",
                ticket_id="IDCEVODEV-977874",
                workspace=root,
                session_id="manual-001",
            )

            updated = record_manual_review_step(
                "manual-001",
                "blender_visual_check",
                "pass",
                workspace=root,
                note="Reviewer checked logos, lights, side mirrors, rims and flaps.",
                screenshot=screenshot,
            )

            step = next(item for item in updated["steps"] if item["slug"] == "blender_visual_check")
            self.assertEqual(step["verdict"], "pass")
            self.assertEqual(step["note"], "Reviewer checked logos, lights, side mirrors, rims and flaps.")
            self.assertEqual(step["screenshot_path"], str(screenshot.resolve()))
            self.assertFalse(step["recorded_by_tool"])
            self.assertEqual(updated["summary"]["recorded_steps"], 1)
            self.assertGreaterEqual(updated["summary"]["pending_steps"], 6)

            reloaded = load_manual_review_session("manual-001", workspace=root)
            self.assertEqual(reloaded["steps"][0]["verdict"], "pass")
            self.assertIn("[pass]", render_manual_review_markdown(reloaded))

    def test_all_verdict_values_are_operator_recorded_and_bad_screenshot_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_manual_review_session(
                profile_id="G65",
                ticket_id="IDCEVODEV-977874",
                workspace=root,
                session_id="manual-001",
            )

            step_slugs = (
                "blender_visual_check",
                "constants_info_verification",
                "functionality_test_raco",
                "documentation_review",
            )
            for step_slug, verdict in zip(step_slugs, VALID_VERDICTS):
                record_manual_review_step(
                    "manual-001",
                    step_slug,
                    verdict,
                    workspace=root,
                    note=f"Reviewer recorded {verdict}.",
                )

            updated = load_manual_review_session("manual-001", workspace=root)
            verdicts = {step["slug"]: step["verdict"] for step in updated["steps"]}
            for step_slug, verdict in zip(step_slugs, VALID_VERDICTS):
                self.assertEqual(verdicts[step_slug], verdict)
            self.assertEqual(updated["summary"]["recorded_steps"], len(VALID_VERDICTS))
            self.assertFalse(any(step["recorded_by_tool"] for step in updated["steps"]))

            with self.assertRaises(FileNotFoundError):
                record_manual_review_step(
                    "manual-001",
                    "anchor_points_test_raco",
                    "blocked",
                    workspace=root,
                    screenshot=root / "missing.png",
                )

    def test_cli_creates_records_and_renders_markdown_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            session_stdout = io.StringIO()
            with redirect_stdout(session_stdout):
                create_result = main(
                    [
                        "manual-review",
                        "session",
                        "--workspace",
                        str(root),
                        "--profile",
                        "G65",
                        "--ticket",
                        "IDCEVODEV-977874",
                        "--session-id",
                        "manual-001",
                        "--json",
                    ]
                )

            record_stdout = io.StringIO()
            with redirect_stdout(record_stdout):
                record_result = main(
                    [
                        "manual-review",
                        "record-step",
                        "manual-001",
                        "--workspace",
                        str(root),
                        "--step",
                        "constants_info_verification",
                        "--verdict",
                        "blocked",
                        "--note",
                        "Waiting for epic constants.",
                        "--json",
                    ]
                )

            summary_stdout = io.StringIO()
            with redirect_stdout(summary_stdout):
                summary_result = main(
                    [
                        "manual-review",
                        "summary",
                        "manual-001",
                        "--workspace",
                        str(root),
                        "--markdown",
                    ]
                )

        self.assertEqual(create_result, 0)
        self.assertEqual(record_result, 0)
        self.assertEqual(summary_result, 0)
        payload = json.loads(session_stdout.getvalue())
        self.assertEqual(payload["session_id"], "manual-001")
        self.assertIn("Constants Info Verification", summary_stdout.getvalue())
        self.assertIn("[blocked]", summary_stdout.getvalue())
        self.assertIn("Operator records the verdict per step", summary_stdout.getvalue())

    def test_open_tool_commands_fail_clean_when_external_tool_is_not_configured(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_manual_review_session(
                profile_id="G65",
                ticket_id="IDCEVODEV-977874",
                workspace=root,
                session_id="manual-001",
            )

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                result = main(
                    [
                        "manual-review",
                        "open-raco",
                        "manual-001",
                        "--workspace",
                        str(root),
                        "--step",
                        "functionality_test_raco",
                    ]
                )

        self.assertEqual(result, 1)
        self.assertIn("Ramses Composer / RaCo is not configured", stderr.getvalue())

    def test_daily_digest_surfaces_pending_manual_review_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_manual_review_session(
                profile_id="G65",
                ticket_id="IDCEVODEV-977874",
                workspace=root,
                session_id="manual-001",
            )

            digest = build_latest_daily_digest("IDCEVODEV-977874", root)

        items = digest["sections"]["manual_review_pending"]["items"]
        labels = [item["label"] for item in items]
        self.assertTrue(any("manual-001" in label for label in labels))
        self.assertTrue(any(item.get("session_id") == "manual-001" for item in items))
        self.assertIn("blender_visual_check", digest["markdown"])
        self.assertIn("Operator verdict required", digest["markdown"])


if __name__ == "__main__":
    unittest.main()
