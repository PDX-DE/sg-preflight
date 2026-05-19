from __future__ import annotations

from datetime import datetime, timezone
import tempfile
from pathlib import Path
import unittest

from sg_preflight.activity_log import (
    ACTIVITY_LOG_BANNER,
    append_activity_entry,
    activity_log_path,
    read_activity_entries,
)


class TestActivityLog(unittest.TestCase):
    def test_append_and_read_activity_entries_are_operator_local(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            first = append_activity_entry(
                workspace,
                verb="read",
                surface="daily-digest",
                profile="G65",
                outcome="ok",
                note="status summary opened",
                now=datetime(2026, 5, 19, 7, 30, tzinfo=timezone.utc),
            )
            second = append_activity_entry(
                workspace,
                verb="refreshed",
                surface="screenshot-test-state",
                profile="G65",
                outcome="empty",
                now=datetime(2026, 5, 19, 7, 45, tzinfo=timezone.utc),
            )

            self.assertEqual(first["verb"], "read")
            self.assertEqual(second["outcome"], "empty")
            self.assertEqual(activity_log_path(workspace).parent.name, "operator_state")
            self.assertTrue(activity_log_path(workspace).exists())

            payload = read_activity_entries(
                workspace,
                profile="G65",
                since="today",
                now=datetime(2026, 5, 19, 8, 0, tzinfo=timezone.utc),
            )

            self.assertEqual(payload["note"], ACTIVITY_LOG_BANNER)
            self.assertEqual([entry["surface"] for entry in payload["entries"]], ["screenshot-test-state", "daily-digest"])
            self.assertEqual(payload["count"], 2)

    def test_activity_log_rejects_verdict_like_verbs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "Activity verb"):
                append_activity_entry(
                    Path(temp_dir),
                    verb="approved",
                    surface="screenshots",
                    profile="G65",
                    outcome="ok",
                )


if __name__ == "__main__":
    unittest.main()
