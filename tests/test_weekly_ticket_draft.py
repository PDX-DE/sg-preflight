from __future__ import annotations

from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from urllib import error as urllib_error

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


def _transport_with_issues(issues: list[dict[str, object]], *, total: int | None = None):
    def transport(request, timeout=30):
        payload: dict[str, object] = {"issues": issues}
        if total is not None:
            payload["total"] = total
        return _FakeResponse(200, json.dumps(payload).encode("utf-8"))

    return transport


def _weekly_issue(index: int) -> dict[str, object]:
    return {
        "key": f"IDCEVODEV-{1000000 + index}",
        "fields": {
            "summary": f"Weekly ticket {index}",
            "status": {"name": "In Progress", "statusCategory": {"name": "In Progress"}},
            "priority": {"name": "Medium"},
            "project": {"key": "IDCEVODEV"},
            "assignee": {"displayName": "Operator"},
            "updated": "2026-06-17T10:00:00.000+0200",
        },
    }


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

    def test_weekly_ticket_draft_filters_only_its_own_activity_surface(self) -> None:
        fixed_now = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)
        fake_keyring = _FakeKeyring()

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_dir = root / "state"
            _write_keychain_credentials(state_dir, fake_keyring)
            append_activity_entry(root, verb="read", surface="digest weekly-tickets", profile="G65", now=fixed_now)
            append_activity_entry(root, verb="read", surface="daily-digest latest", profile="G65", now=fixed_now)
            append_activity_entry(root, verb="ran", surface="screenshot capture", profile="G65", now=fixed_now)
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": str(state_dir)}):
                with mock.patch.dict(sys.modules, {"keyring": fake_keyring}):
                    payload = build_weekly_ticket_draft(
                        workspace=root,
                        transport=_transport_with_issues([]),
                        now=fixed_now,
                    )

        text = render_weekly_ticket_draft_text(payload)

        self.assertNotIn("digest weekly-tickets", text)
        self.assertIn("daily-digest latest", text)
        self.assertIn("screenshot capture", text)

    def test_weekly_ticket_draft_shows_known_total_truncation_marker(self) -> None:
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
                        transport=_transport_with_issues([_weekly_issue(index) for index in range(50)], total=74),
                        now=fixed_now,
                    )

        text = render_weekly_ticket_draft_text(payload)
        markdown = render_weekly_ticket_draft_markdown(payload)

        self.assertTrue(payload["truncated"])
        self.assertEqual(payload["total_available"], 74)
        self.assertIn("Showing the 50 most recently updated - 74 tickets matched this week.", text)
        self.assertIn("Narrow the window with --since", markdown)

    def test_weekly_ticket_draft_shows_possible_truncation_when_total_is_unknown(self) -> None:
        fixed_now = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)
        fake_keyring = _FakeKeyring()

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_dir = root / "state"
            _write_keychain_credentials(state_dir, fake_keyring)
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": str(state_dir)}):
                with mock.patch.dict(sys.modules, {"keyring": fake_keyring}):
                    capped_payload = build_weekly_ticket_draft(
                        workspace=root,
                        transport=_transport_with_issues([_weekly_issue(index) for index in range(50)]),
                        now=fixed_now,
                    )
                    uncapped_payload = build_weekly_ticket_draft(
                        workspace=root,
                        transport=_transport_with_issues([_weekly_issue(1)]),
                        now=fixed_now,
                    )

        text = render_weekly_ticket_draft_text(capped_payload)
        uncapped_text = render_weekly_ticket_draft_text(uncapped_payload)

        self.assertTrue(capped_payload["truncated"])
        self.assertIsNone(capped_payload["total_available"])
        self.assertIn("Showing the 50 most recently updated; there may be more", text)
        self.assertFalse(uncapped_payload["truncated"])
        self.assertNotIn("Showing the 50 most recently updated", uncapped_text)

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
        self.assertNotIn("Weekly Tickets unavailable", text)
        self.assertIn("delivery board", text)
        self.assertIn("Draft only", text)

    def test_weekly_ticket_draft_failed_jira_keeps_raw_error_out_of_draft(self) -> None:
        fixed_now = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)
        fake_keyring = _FakeKeyring()
        leak_body = (
            b'{"errorMessages":["Endpoint https://jira.cc.bmwgroup.net/rest/api/2/search'
            b'?jql=assignee+%3D+currentUser() rejected by proxy 10.20.30.40"]}'
        )

        def transport(request, timeout=30):
            raise urllib_error.HTTPError(
                "https://jira.cc.bmwgroup.net/rest/api/2/search",
                400,
                "Bad Request",
                {},
                io.BytesIO(leak_body),
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_dir = root / "state"
            _write_keychain_credentials(state_dir, fake_keyring)
            append_activity_entry(root, verb="ran", surface="screenshot capture", profile="G65", now=fixed_now)
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": str(state_dir)}):
                with mock.patch.dict(sys.modules, {"keyring": fake_keyring}):
                    payload = build_weekly_ticket_draft(workspace=root, transport=transport, now=fixed_now)

        text = render_weekly_ticket_draft_text(payload)
        markdown = render_weekly_ticket_draft_markdown(payload)

        self.assertEqual(payload["jira_status"], "failed")
        for rendered in (text, markdown):
            self.assertIn("Couldn't reach Jira", rendered)
            self.assertIn("screenshot capture", rendered)
            self.assertNotIn("jira.cc.bmwgroup.net", rendered)
            self.assertNotIn("10.20.30.40", rendered)
            self.assertNotIn("HTTP 400", rendered)
            self.assertNotIn("errorMessages", rendered)
            self.assertNotIn("GET failed", rendered)
            self.assertNotIn("No tickets updated this week", rendered)

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
