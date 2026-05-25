from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
import unittest

from sg_preflight.manual_review import (
    QUALITY_HERO_STEPS,
    create_manual_review_session_from_template,
    record_manual_review_step,
)
from sg_preflight.risk_scoring import (
    RISK_SCORE_GUARDRAILS,
    read_per_car_risk_score,
    render_risk_score_markdown,
    render_risk_score_text,
)
from tests.operator_helpers import write_text


def _write_image(path: Path, *, mtime: int) -> None:
    write_text(path, "fake\n")
    os.utime(path, (mtime, mtime))


def _write_screenshot_fixture(root: Path) -> None:
    tests_root = root / "digital-3d-car-models" / "cars" / "BMW" / "G65_EVO" / "export" / "tests"
    write_text(root / "digital-3d-car-models" / "ci" / "scripts" / "README.md", "fixture\n")
    _write_image(tests_root / "expected" / "front.png", mtime=946684740)
    _write_image(tests_root / "expected" / "rear.png", mtime=946684740)
    _write_image(tests_root / "actuals" / "front.png", mtime=946684920)
    _write_image(tests_root / "diff" / "rear.png", mtime=946684920)
    write_text(tests_root / "test_config.lua", 'disableTest("country_variant_extra")\n')


def _write_review_session(root: Path) -> None:
    session = create_manual_review_session_from_template(
        profile_id="G65",
        ticket_id="IDCEVODEV-977874",
        workspace=root,
        session_id="risk-review-g65",
    )
    session = record_manual_review_step(
        session["session_path"],
        QUALITY_HERO_STEPS[0].slug,
        "passed",
        workspace=root,
        note="Checked in fixture.",
    )
    path = Path(session["session_path"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["updated_at_utc"] = "2000-01-01T00:00:00Z"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class RiskScoringTests(unittest.TestCase):
    def test_risk_score_uses_current_counts_manual_review_and_delta(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_screenshot_fixture(root)
            _write_review_session(root)

            payload = read_per_car_risk_score("G65", workspace=root)

        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["current_snapshot"]["expected_count"], 2)
        self.assertEqual(payload["current_snapshot"]["actual_count"], 1)
        self.assertEqual(payload["current_snapshot"]["diff_count"], 1)
        self.assertEqual(payload["latest_review"]["recorded_steps"], 1)
        self.assertEqual(payload["latest_review"]["pending_steps"], len(QUALITY_HERO_STEPS) - 1)
        self.assertEqual(payload["delta_since_last_review"]["changed_file_count"], 2)
        self.assertGreater(payload["risk_score"], 0)
        self.assertEqual(tuple(payload["guardrails"]), RISK_SCORE_GUARDRAILS)
        self.assertFalse(payload["is_approval"])
        signal_ids = {signal["id"] for signal in payload["signals"]}
        self.assertIn("diff_screenshots_present", signal_ids)
        self.assertIn("manual_review_pending_steps", signal_ids)
        self.assertIn("screenshot_delta_since_review", signal_ids)

    def test_risk_score_without_manual_session_marks_delta_not_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_screenshot_fixture(root)

            payload = read_per_car_risk_score("G65", workspace=root)

        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["latest_review"]["status"], "not_run")
        self.assertEqual(payload["delta_since_last_review"]["status"], "not_run")
        self.assertIn("manual_review_not_started", {signal["id"] for signal in payload["signals"]})

    def test_risk_score_renderers_keep_manual_review_guardrail(self) -> None:
        payload = {
            "profile_id": "G65",
            "status": "available",
            "risk_score": 42,
            "risk_level": "medium",
            "current_snapshot": {"expected_count": 2, "actual_count": 1, "diff_count": 1, "disabled_test_count": 0},
            "latest_review": {"session_id": "risk-review-g65", "recorded_steps": 1, "pending_steps": 6},
            "delta_since_last_review": {"changed_file_count": 2},
            "signals": [{"id": "diff_screenshots_present", "status": "available", "weight": 13, "detail": "1 diff"}],
            "guardrails": list(RISK_SCORE_GUARDRAILS),
            "is_approval": False,
        }

        text = render_risk_score_text(payload)
        markdown = render_risk_score_markdown(payload)

        self.assertIn("Manual review remains required", text)
        self.assertIn("Manual review remains required", markdown)
        self.assertIn("Decision: not approval — evidence only.", text)
        self.assertIn("Decision: not approval — evidence only.", markdown)
        self.assertIn("42/100", markdown)
        self.assertNotIn("approved", text.casefold())
        self.assertNotIn("production-" "ready", markdown.casefold())


if __name__ == "__main__":
    unittest.main()
