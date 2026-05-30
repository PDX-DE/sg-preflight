from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from sg_preflight.team_digest_board import (
    build_team_daily_digest_board,
    render_team_digest_board_markdown,
)
from tests.operator_helpers import write_text


def _write_screenshot_fixture(root: Path, profile_id: str) -> None:
    tests_root = root / "digital-3d-car-models" / "cars" / "BMW" / f"{profile_id}_EVO" / "export" / "tests"
    write_text(root / "digital-3d-car-models" / "ci" / "scripts" / "README.md", "fixture\n")
    write_text(tests_root / "expected" / "front.png", "fake\n")
    write_text(tests_root / "actuals" / "front.png", "fake\n")
    write_text(tests_root / "diff" / "front.png", "fake\n")


class TeamDigestBoardTests(unittest.TestCase):
    def test_board_chooses_local_snapshot_and_surfaces_tradeoffs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_screenshot_fixture(root, "G70")
            _write_screenshot_fixture(root, "G65")

            board = build_team_daily_digest_board(workspace=root, profiles=("G70", "G65"))

        self.assertEqual(board["status"], "available")
        self.assertEqual(board["share_decision"]["selected_model"], "local_snapshot")
        self.assertEqual(board["share_decision"]["status"], "available")
        option_models = {option["model"]: option["status"] for option in board["share_decision"]["options"]}
        self.assertEqual(option_models["local_snapshot"], "available")
        self.assertEqual(option_models["svn_shared"], "skipped")
        self.assertEqual(option_models["confluence_page"], "skipped")
        risk_items = board["sections"]["risk_by_profile"]["items"]
        self.assertEqual([item["profile_id"] for item in risk_items], ["G70", "G65"])
        self.assertTrue(all(item["manual_review_required"] for item in risk_items))
        self.assertTrue(all(item["is_approval"] is False for item in risk_items))
        self.assertFalse(board["is_approval"])

    def test_board_markdown_keeps_share_model_and_guardrails_visible(self) -> None:
        board = {
            "title": "Team Daily Digest Board",
            "status": "available",
            "profiles": ["G70"],
            "manual_review_required": True,
            "is_approval": False,
            "guardrails": [
                "Manual review remains required.",
                "Decision: not approval — evidence only.",
            ],
            "share_decision": {
                "selected_model": "local_snapshot",
                "status": "available",
                "rationale": "Local snapshot writes only operator-local output.",
                "options": [
                    {"model": "local_snapshot", "status": "available", "tradeoff": "Local and regenerable."},
                    {"model": "svn_shared", "status": "skipped", "tradeoff": "Requires a separate gate."},
                ],
            },
            "sections": {
                "risk_by_profile": {
                    "heading": "Risk by profile",
                    "items": [{"label": "G70", "status": "available", "risk_score": 42, "detail": "Local signal."}],
                    "empty_message": "",
                },
                "what_landed_today": {
                    "heading": "What landed today",
                    "items": [{"label": "docs(ui): wire " + "A" + "I" + " wording", "status": "local_commit"}],
                    "empty_message": "",
                }
            },
        }

        markdown = render_team_digest_board_markdown(board)

        self.assertIn("Sharing Model Trade-Offs", markdown)
        self.assertIn("local_snapshot", markdown)
        self.assertIn("Manual review remains required", markdown)
        self.assertIn("Decision: not approval", markdown)
        self.assertNotIn("A" + "I", markdown)
        self.assertNotIn("approved", markdown.casefold())
        self.assertNotIn("validated", markdown.casefold())


if __name__ == "__main__":
    unittest.main()
