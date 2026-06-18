from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from sg_preflight.activity_log import append_activity_entry
from sg_preflight.jira_client import JIRA_KEYRING_SERVICE, clear_jira_my_tickets_cache
from sg_preflight.weekly_ticket_draft import (
    build_weekly_ticket_draft,
    render_weekly_ticket_draft_markdown,
    render_weekly_ticket_draft_text,
)


class _FakeKeyring:
    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, account: str, password: str) -> None:
        self.store[(service, account)] = password

    def get_password(self, service: str, account: str) -> str | None:
        return self.store.get((service, account))

    def delete_password(self, service: str, account: str) -> None:
        self.store.pop((service, account), None)


class _FakeResponse:
    def __init__(self, status: int = 200, body: bytes = b'{"issues":[]}') -> None:
        self.status = status
        self._body = body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _write_keychain_credentials(state_dir: Path, fake_keyring: _FakeKeyring) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "jira_pat.json").write_text(json.dumps({"jira_url": "https://jira.example"}), encoding="utf-8")
    fake_keyring.store[(JIRA_KEYRING_SERVICE, "https://jira.example")] = "test-pat-placeholder-not-real"


def _transport_with_issues(issues: list[dict[str, object]]):
    def transport(request, timeout=30):
        return _FakeResponse(200, json.dumps({"issues": issues}).encode("utf-8"))

    return transport


class TestWeeklyTicketDraft(unittest.TestCase):
    def setUp(self) -> None:
        clear_jira_my_tickets_cache()

    def test_weekly_ticket_draft_groups_jira_tickets_and_local_activity(self) -> None:
        fixed_now = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)
        fake_keyring = _FakeKeyring()
        issues = [
            {
                "key": "IDCEVODEV-1000001",
                "fields": {
                    "summary": "G65 screenshot review follow-up",
                    "status": {"name": "In Progress", "statusCategory": {"name": "In Progress"}},
                    "priority": {"name": "High"},
                    "project": {"key": "IDCEVODEV"},
                    "assignee": {"displayName": "Operator"},
                    "updated": "2026-06-17T10:00:00.000+0200",
                },
            },
            {
                "key": "IDCEVODEV-1000002",
                "fields": {
                    "summary": "Close delivered workbook task",
                    "status": {"name": "Done", "statusCategory": {"name": "Done"}},
                    "priority": {"name": "Medium"},
                    "project": {"key": "IDCEVODEV"},
                    "assignee": {"displayName": "Operator"},
                    "updated": "2026-06-16T08:00:00.000+0200",
                },
            },
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_dir = root / "state"
            _write_keychain_credentials(state_dir, fake_keyring)
            append_activity_entry(root, verb="ran", surface="screenshot capture", profile="G65", now=fixed_now)
            append_activity_entry(root, verb="ran", surface="screenshot capture", profile="G65", now=fixed_now)
            append_activity_entry(root, verb="exported", surface="workbook", profile="NA0", now=fixed_now)
            append_activity_entry(
                root,
                verb="read",
                surface="old board",
                profile="G65",
                now=datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc),
            )
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": str(state_dir)}):
                with mock.patch.dict(sys.modules, {"keyring": fake_keyring}):
                    payload = build_weekly_ticket_draft(
                        workspace=root,
                        transport=_transport_with_issues(issues),
                        now=fixed_now,
                    )

        self.assertEqual(payload["jira_status"], "available")
        self.assertEqual(payload["range_label"], "2026-06-15 to 2026-06-21")
        self.assertEqual(payload["operator"], "Operator")
        self.assertTrue(payload["read_only"])
        self.assertFalse(payload["is_approval"])
        group_headings = [group["heading"] for group in payload["part_a"]["groups"]]
        self.assertIn("In progress", group_headings)
        self.assertIn("Completed this week", group_headings)
        activity_profiles = {group["profile"]: group for group in payload["part_b"]["groups"]}
        self.assertIn("G65", activity_profiles)
        self.assertIn("NA0", activity_profiles)
        self.assertEqual(activity_profiles["G65"]["items"][0]["count"], 2)
        self.assertIn("for your reference", payload["part_b"]["note"].lower())

    def test_weekly_ticket_draft_degrades_when_jira_is_not_connected(self) -> None:
        fixed_now = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            append_activity_entry(root, verb="refreshed", surface="delivery board", profile="G65", now=fixed_now)
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": str(root / "missing")}):
                with mock.patch("pathlib.Path.home", return_value=root / "home"):
                    with mock.patch("pathlib.Path.cwd", return_value=root / "cwd"):
                        payload = build_weekly_ticket_draft(workspace=root, now=fixed_now)

        text = render_weekly_ticket_draft_text(payload)

        self.assertEqual(payload["jira_status"], "missing")
        self.assertIn("Jira not connected", text)
        self.assertNotIn("No tickets updated this week", text)
        self.assertIn("delivery board", text)
        self.assertIn("Draft only", text)

    def test_weekly_ticket_draft_renders_empty_week_without_claims(self) -> None:
        fixed_now = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)
        fake_keyring = _FakeKeyring()

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_dir = root / "state"
            _write_keychain_credentials(state_dir, fake_keyring)
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": str(state_dir)}):
                with mock.patch.dict(sys.modules, {"keyring": fake_keyring}):
                    payload = build_weekly_ticket_draft(
                        workspace=root,
                        transport=_transport_with_issues([]),
                        now=fixed_now,
                    )

        text = render_weekly_ticket_draft_text(payload)
        markdown = render_weekly_ticket_draft_markdown(payload)

        self.assertIn("No tickets updated this week", text)
        self.assertIn("No SGFX activity entries recorded this week", text)
        self.assertIn("# Tickets I worked on", markdown)
        self.assertIn("Draft only", markdown)
        lowered = f"{text}\n{markdown}".lower()
        self.assertNotIn("lexus", lowered)
        self.assertNotIn("mercedes", lowered)
        self.assertNotIn("aston", lowered)
        self.assertNotIn("claude", lowered)
        self.assertNotIn("codex", lowered)
        self.assertNotIn("chatgpt", lowered)
        self.assertNotIn("clockodo", lowered)


if __name__ == "__main__":
    unittest.main()
