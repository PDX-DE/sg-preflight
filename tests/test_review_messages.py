from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from sg_preflight.review_messages import build_digest_json, build_morning_digest, build_review_owner_update
from sg_preflight.review_state import build_review_board_state
from tests.operator_helpers import create_review_package_fixture


class TestReviewMessages(unittest.TestCase):
    def test_review_owner_update_and_digest_summarize_review_board_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_review_package_fixture(root)
            state = build_review_board_state("IDCEVODEV-960073", root)

        update = build_review_owner_update(state)
        digest = build_morning_digest(state)
        digest_json = build_digest_json(state)

        self.assertIn("IDCEVODEV-960073 QA status", update)
        self.assertIn("Scope: NA8 / G78 / G50", update)
        self.assertIn("Representative smoke: 3/3 passed", update)
        self.assertIn("lights_OnlyCones", update)

        self.assertIn("Daily 3D Car QA Digest", digest)
        self.assertIn("(2026-04-22)", digest)
        self.assertIn("Battery: 2/3 covered", digest)
        self.assertIn("Delta: +0 failures, 0 resolved, 0 new diffs, 1 unchanged blockers", digest)
        self.assertIn("Unresolved exact: lights_OnlyCones", digest)
        self.assertLessEqual(len([line for line in digest.splitlines() if line.strip()]), 9)

        self.assertEqual(digest_json["ticket_id"], "IDCEVODEV-960073")
        self.assertEqual(digest_json["screenshot_battery"]["covered"], 2)
        self.assertEqual(digest_json["unresolved_families"], ["lights_OnlyCones"])
        self.assertEqual(digest_json["delta_summary"]["unchanged_blockers_count"], 1)
