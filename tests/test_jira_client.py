from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from urllib import error as urllib_error

from sg_preflight.jira_client import (
    ConfigError,
    JIRA_KEYRING_SERVICE,
    JIRA_POSTING_BANNER,
    JIRA_TICKETS_UNAVAILABLE_SUMMARY,
    JiraPostError,
    build_my_weekly_ticket_jql,
    attach_jira_file_action,
    build_my_unresolved_ticket_jql,
    build_profile_ticket_jql,
    clear_jira_my_tickets_cache,
    clear_jira_profile_ticket_cache,
    extract_numbered_section_text,
    jira_status,
    load_jira_credentials,
    post_jira_comment,
    post_jira_comment_action,
    search_jira_profile_tickets,
    search_my_weekly_tickets,
    search_my_unresolved_tickets,
    update_jira_issue_action,
    write_jira_credentials,
)


class _FakeResponse:
    def __init__(self, status: int = 201, body: bytes = b'{"id":"10001"}') -> None:
        self.status = status
        self._body = body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class _FakeKeyring:
    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, account: str, password: str) -> None:
        self.store[(service, account)] = password

    def get_password(self, service: str, account: str) -> str | None:
        return self.store.get((service, account))

    def delete_password(self, service: str, account: str) -> None:
        self.store.pop((service, account), None)


def _write_keychain_credentials(
    state_dir: Path,
    fake_keyring: _FakeKeyring,
    *,
    jira_url: str = "https://jira.example",
    pat: str = "test-pat-placeholder-not-real",
) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "jira_pat.json").write_text(json.dumps({"jira_url": jira_url}), encoding="utf-8")
    fake_keyring.store[(JIRA_KEYRING_SERVICE, jira_url)] = pat


class TestJiraClient(unittest.TestCase):
    def test_extract_numbered_section_prefers_text_fence_body(self) -> None:
        markdown = """# Drafts

## 6. First Jira update

Intro that should stay outside the comment.

```text
Status update

Manual review remains required.
```

## 7. Second Jira update

```text
Other text
```
"""

        body = extract_numbered_section_text(markdown, "6")

        self.assertEqual(body, "Status update\n\nManual review remains required.")

    def test_dry_run_never_calls_transport_and_keeps_confirmation_gate(self) -> None:
        calls: list[object] = []

        result = post_jira_comment(
            "IDCEVODEV-977874",
            "Status update",
            base_url="https://jira.example",
            token="test-pat-placeholder-not-real",
            confirm=False,
            transport=lambda request, timeout=30: calls.append(request),
        )

        self.assertEqual(result["status"], "dry_run")
        self.assertFalse(result["posted"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(calls, [])
        self.assertEqual(result["note"], JIRA_POSTING_BANNER)
        self.assertIn("--confirm", result["guard"])

    def test_default_jira_action_preview_loads_no_credentials_and_calls_no_transport(self) -> None:
        transport = mock.Mock(side_effect=AssertionError("transport must stay unused"))
        with mock.patch(
            "sg_preflight.jira_client.load_jira_credentials",
            side_effect=AssertionError("credentials must stay unused"),
        ):
            payload = post_jira_comment_action(
                "IDCEVODEV-1000001",
                "Preview body",
                transport=transport,
            )

        self.assertTrue(payload["dry_run"])
        self.assertTrue(payload["confirm_network_required"])
        transport.assert_not_called()

    def test_jira_write_requires_network_and_write_confirmation(self) -> None:
        with self.assertRaises(JiraPostError):
            post_jira_comment_action(
                "IDCEVODEV-1000001",
                "Body",
                auto_confirm=True,
                confirm_network=False,
            )

    def test_legacy_jira_post_requires_network_confirmation_before_write(self) -> None:
        transport = mock.Mock(side_effect=AssertionError("transport must stay unused"))
        with self.assertRaises(JiraPostError):
            post_jira_comment(
                "IDCEVODEV-977874",
                "Status update",
                base_url="https://jira.example",
                token="test-pat-placeholder-not-real",
                confirm=True,
                confirm_network=False,
                transport=transport,
            )
        transport.assert_not_called()

    def test_jira_base_url_must_be_https_after_network_confirmation(self) -> None:
        with self.assertRaises(ConfigError):
            post_jira_comment(
                "IDCEVODEV-977874",
                "Status update",
                base_url="http://jira.example",
                token="test-pat-placeholder-not-real",
                confirm=False,
                confirm_network=True,
            )

    def test_confirm_requires_base_url_and_pat(self) -> None:
        with self.assertRaises(JiraPostError) as missing_base:
            post_jira_comment(
                "IDCEVODEV-977874",
                "Status update",
                token="test-pat-placeholder-not-real",
                confirm=True,
                confirm_network=True,
            )

        with self.assertRaises(JiraPostError) as missing_token:
            post_jira_comment(
                "IDCEVODEV-977874",
                "Status update",
                base_url="https://jira.example",
                confirm=True,
                confirm_network=True,
            )

        self.assertIn("base URL", str(missing_base.exception))
        self.assertIn("PAT", str(missing_token.exception))

    def test_confirm_posts_one_comment_to_jira_rest_endpoint(self) -> None:
        captured: dict[str, object] = {}

        def transport(request, timeout=30):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            captured["headers"] = dict(request.header_items())
            captured["payload"] = json.loads(request.data.decode("utf-8")) if request.data else None
            captured["timeout"] = timeout
            return _FakeResponse()

        result = post_jira_comment(
            "IDCEVODEV-977874",
            "Status update",
            base_url="https://jira.example/",
            token="test-pat-placeholder-not-real",
            confirm=True,
            confirm_network=True,
            transport=transport,
        )

        self.assertEqual(result["status"], "posted")
        self.assertTrue(result["posted"])
        self.assertFalse(result["dry_run"])
        self.assertEqual(captured["url"], "https://jira.example/rest/api/2/issue/IDCEVODEV-977874/comment")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["payload"], {"body": "Status update"})
        self.assertEqual(captured["headers"]["Authorization"], "Bearer test-pat-placeholder-not-real")
        self.assertEqual(result["http_status"], 201)

    def test_section_file_roundtrip_uses_numbered_heading(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "HANDOVER_WORDING.md"
            path.write_text(
                "## 19. Jira posting dry run\n\n```text\nReady for operator-confirmed posting.\n```\n",
                encoding="utf-8",
            )

            body = extract_numbered_section_text(path.read_text(encoding="utf-8"), "19")

        self.assertEqual(body, "Ready for operator-confirmed posting.")

    def test_load_jira_credentials_prefers_operator_state_env_without_mutating_legacy_config(self) -> None:
        fake_keyring = _FakeKeyring()
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir) / "state"
            path = state_dir / "jira_pat.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps({"jira_url": "https://jira.example", "pat": "test-pat-placeholder-not-real"}),
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": str(state_dir)}):
                with mock.patch.dict(sys.modules, {"keyring": fake_keyring}):
                    credentials = load_jira_credentials()
            saved = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(credentials["jira_url"], "https://jira.example")
        self.assertEqual(credentials["pat"], "test-pat-placeholder-not-real")
        self.assertTrue(credentials["path"].endswith("jira_pat.json"))
        self.assertEqual(
            saved,
            {"jira_url": "https://jira.example", "pat": "test-pat-placeholder-not-real"},
        )
        self.assertEqual(fake_keyring.store, {})

    def test_load_jira_credentials_reads_pat_from_keychain(self) -> None:
        fake_keyring = _FakeKeyring()
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir) / "state"
            _write_keychain_credentials(state_dir, fake_keyring)
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": str(state_dir)}):
                with mock.patch.dict(sys.modules, {"keyring": fake_keyring}):
                    credentials = load_jira_credentials()

        self.assertEqual(credentials["jira_url"], "https://jira.example")
        self.assertEqual(credentials["pat"], "test-pat-placeholder-not-real")

    def test_load_jira_credentials_accepts_legacy_token_key_without_mutation(self) -> None:
        fake_keyring = _FakeKeyring()
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir) / "state"
            path = state_dir / "jira_pat.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps({"jira_url": "https://jira.example", "pat_api_id": "test-pat-placeholder-not-real"}),
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": str(state_dir)}):
                with mock.patch.dict(sys.modules, {"keyring": fake_keyring}):
                    credentials = load_jira_credentials()
            saved = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(credentials["pat"], "test-pat-placeholder-not-real")
        self.assertEqual(
            saved,
            {"jira_url": "https://jira.example", "pat_api_id": "test-pat-placeholder-not-real"},
        )
        self.assertEqual(fake_keyring.store, {})

    def test_load_jira_credentials_reports_missing_with_remediation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": str(Path(temp_dir) / "missing")}):
                with mock.patch("pathlib.Path.home", return_value=Path(temp_dir) / "home"):
                    with mock.patch("pathlib.Path.cwd", return_value=Path(temp_dir) / "cwd"):
                        with self.assertRaises(ConfigError) as caught:
                            load_jira_credentials()

        self.assertIn("Jira PAT is missing", str(caught.exception))

    def test_load_jira_credentials_fails_closed_when_keychain_backend_errors(self) -> None:
        class BrokenKeyring:
            def get_password(self, service: str, account: str) -> str | None:
                raise RuntimeError("backend unavailable")

        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir) / "state"
            state_dir.mkdir()
            path = state_dir / "jira_pat.json"
            path.write_text(json.dumps({"jira_url": "https://jira.example"}), encoding="utf-8")
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": str(state_dir)}):
                with mock.patch.dict(sys.modules, {"keyring": BrokenKeyring()}):
                    with self.assertRaises(ConfigError) as caught:
                        load_jira_credentials()
            saved_after = json.loads(path.read_text(encoding="utf-8"))

        self.assertIn("keychain", str(caught.exception))
        self.assertNotIn("pat", json.dumps(saved_after).lower())

    def test_load_jira_credentials_does_not_touch_keychain_for_legacy_pat(self) -> None:
        class BrokenKeyring:
            def set_password(self, service: str, account: str, password: str) -> None:
                raise RuntimeError("backend unavailable")

            def get_password(self, service: str, account: str) -> str | None:
                raise RuntimeError("backend unavailable")

        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir) / "state"
            state_dir.mkdir()
            path = state_dir / "jira_pat.json"
            path.write_text(
                json.dumps({"jira_url": "https://jira.example", "pat": "test-pat-placeholder-not-real"}),
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": str(state_dir)}):
                with mock.patch.dict(sys.modules, {"keyring": BrokenKeyring()}):
                    credentials = load_jira_credentials()
            saved_after = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(credentials["pat"], "test-pat-placeholder-not-real")
        self.assertEqual(
            saved_after,
            {"jira_url": "https://jira.example", "pat": "test-pat-placeholder-not-real"},
        )

    def test_write_jira_credentials_records_operator_local_file_with_redacted_payload(self) -> None:
        fake_keyring = _FakeKeyring()
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.dict(sys.modules, {"keyring": fake_keyring}):
                result = write_jira_credentials(
                    jira_url="https://jira.example/",
                    pat="test-pat-placeholder-not-real",
                    state_dir=temp_dir,
                )
            path = Path(temp_dir) / "jira_pat.json"
            saved = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "recorded")
        self.assertEqual(saved["jira_url"], "https://jira.example")
        self.assertNotIn("pat", saved)
        self.assertEqual(fake_keyring.store[(JIRA_KEYRING_SERVICE, "https://jira.example")], "test-pat-placeholder-not-real")
        self.assertNotIn("test-pat-placeholder-not-real", json.dumps(result))
        self.assertEqual(result["credential"]["pat_fingerprint"], "****real")

    def test_jira_status_runs_read_only_connection_and_ticket_gets(self) -> None:
        calls: list[tuple[str, str]] = []
        fake_keyring = _FakeKeyring()

        def transport(request, timeout=30):
            calls.append((request.get_method(), request.full_url))
            return _FakeResponse(200, b'{"name":"operator"}')

        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            _write_keychain_credentials(state_dir, fake_keyring)
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": str(state_dir)}):
                with mock.patch.dict(sys.modules, {"keyring": fake_keyring}):
                    result = jira_status(
                        ticket="IDCEVODEV-1009244",
                        confirm_network=True,
                        transport=transport,
                    )

        self.assertEqual(result["status"], "available")
        self.assertEqual(result["connection_status"], "available")
        self.assertEqual(result["ticket_status"], "available")
        self.assertEqual([method for method, _url in calls], ["GET", "GET"])
        self.assertNotIn("test-pat-placeholder-not-real", json.dumps(result))

    def test_jira_status_reads_legacy_pat_without_migration_or_config_rewrite(self) -> None:
        calls: list[tuple[str, str]] = []
        keyring_calls: list[str] = []

        class RecordingKeyring:
            def set_password(self, service: str, account: str, password: str) -> None:
                keyring_calls.append("set")

            def get_password(self, service: str, account: str) -> str | None:
                keyring_calls.append("get")
                return None

            def delete_password(self, service: str, account: str) -> None:
                keyring_calls.append("delete")

        def transport(request, timeout=30):
            calls.append((request.get_method(), request.full_url))
            return _FakeResponse(200, b'{"name":"operator"}')

        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            path = state_dir / "jira_pat.json"
            original = json.dumps(
                {
                    "jira_url": "https://jira.example",
                    "pat": "test-pat-placeholder-not-real",
                },
                indent=2,
            ).encode("utf-8")
            path.write_bytes(original)
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": str(state_dir)}):
                with mock.patch.dict(sys.modules, {"keyring": RecordingKeyring()}):
                    result = jira_status(
                        ticket="IDCEVODEV-1009244",
                        confirm_network=True,
                        transport=transport,
                    )
            saved = path.read_bytes()

        self.assertEqual(result["status"], "available")
        self.assertEqual([method for method, _url in calls], ["GET", "GET"])
        self.assertEqual(saved, original)
        self.assertEqual(keyring_calls, [])
        self.assertNotIn("test-pat-placeholder-not-real", json.dumps(result))

    def test_profile_ticket_search_builds_read_only_jql_and_sanitizes_rows(self) -> None:
        calls: list[tuple[str, str]] = []
        fake_keyring = _FakeKeyring()

        def transport(request, timeout=30):
            calls.append((request.get_method(), request.full_url))
            return _FakeResponse(
                200,
                json.dumps(
                    {
                        "issues": [
                            {
                                "key": "IDCEVODEV-1000001",
                                "fields": {
                                    "summary": "G65 screenshot review follow-up",
                                    "status": {"name": "In Progress"},
                                    "labels": ["G65"],
                                    "updated": "2026-05-28T10:00:00.000+0200",
                                },
                            }
                        ]
                    }
                ).encode("utf-8"),
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            _write_keychain_credentials(state_dir, fake_keyring)
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": str(state_dir)}):
                with mock.patch.dict(sys.modules, {"keyring": fake_keyring}):
                    result = search_jira_profile_tickets("G65", transport=transport)

        self.assertEqual(result["status"], "available")
        self.assertEqual(result["ticket_count"], 1)
        self.assertEqual(result["tickets"][0]["key"], "IDCEVODEV-1000001")
        self.assertEqual(result["tickets"][0]["status"], "In Progress")
        self.assertEqual(result["tickets"][0]["url"], "https://jira.example/browse/IDCEVODEV-1000001")
        self.assertEqual(calls[0][0], "GET")
        self.assertIn("statusCategory+%21%3D+Done", calls[0][1])
        self.assertIn("summary+~+%22G65%22", calls[0][1])
        self.assertNotIn("test-pat-placeholder-not-real", json.dumps(result))

    def test_profile_ticket_rows_carry_browse_url_for_click_through(self) -> None:
        """Every ticket row must include a fully-qualified `url` field that
        points at the operator-configured Jira base URL so the dashboard inline
        panel can render a working browser link. Regression after 2026-05-29 07:17
        operator walkthrough where ticket clicks did nothing."""
        from sg_preflight.jira_client import _profile_ticket_rows

        response = {
            "issues": [
                {
                    "key": "IDCEVODEV-1009244",
                    "fields": {
                        "summary": "Quality-Hero CW20 review for F70",
                        "status": {"name": "In Review"},
                        "labels": ["seriengrafik"],
                    },
                },
                {
                    "key": "IDCEVODEV-1009239",
                    "fields": {"summary": "G70 delivery checklist", "status": {"name": "Open"}},
                },
            ]
        }
        rows = _profile_ticket_rows(response, "https://jira.cc.bmwgroup.net")
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertIn("url", row)
            self.assertTrue(row["url"].startswith("https://jira.cc.bmwgroup.net/browse/"))
            self.assertIn(row["key"], row["url"])
        # First row URL is fully formed and click-ready.
        self.assertEqual(
            rows[0]["url"],
            "https://jira.cc.bmwgroup.net/browse/IDCEVODEV-1009244",
        )

    def test_profile_ticket_search_reports_missing_credentials_without_transport(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": str(Path(temp_dir) / "missing")}):
                with mock.patch("pathlib.Path.home", return_value=Path(temp_dir) / "home"):
                    with mock.patch("pathlib.Path.cwd", return_value=Path(temp_dir) / "cwd"):
                        result = search_jira_profile_tickets("F70")

        self.assertEqual(result["status"], "missing")
        self.assertEqual(result["ticket_count"], 0)
        self.assertTrue(result["read_only"])
        self.assertIn("Jira tickets unavailable", result["summary"])

    def test_profile_ticket_search_failure_hides_raw_exception_in_visible_summary(self) -> None:
        clear_jira_profile_ticket_cache()
        fake_keyring = _FakeKeyring()

        def transport(request, timeout=30):
            raise JiraPostError("forced transport failure with local detail")

        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            _write_keychain_credentials(state_dir, fake_keyring)
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": str(state_dir)}):
                with mock.patch.dict(sys.modules, {"keyring": fake_keyring}):
                    result = search_jira_profile_tickets("G65", transport=transport)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["summary"], JIRA_TICKETS_UNAVAILABLE_SUMMARY)
        self.assertNotIn("forced transport failure", result["summary"])
        self.assertIn("forced transport failure", result["diagnostic_detail"])

    def test_profile_ticket_search_uses_sixty_second_cache_for_real_transport(self) -> None:
        clear_jira_profile_ticket_cache()
        calls: list[str] = []
        fake_keyring = _FakeKeyring()

        def transport(request, timeout=30):
            calls.append(request.full_url)
            return _FakeResponse(200, b'{"issues":[]}')

        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            _write_keychain_credentials(state_dir, fake_keyring)
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": str(state_dir)}):
                with mock.patch.dict(sys.modules, {"keyring": fake_keyring}):
                    with mock.patch("sg_preflight.jira_client.urllib_request.urlopen", side_effect=transport):
                        clear_jira_profile_ticket_cache()
                        first = search_jira_profile_tickets("NA5")
                        second = search_jira_profile_tickets("NA5")

        self.assertEqual(first["cache_status"], "miss")
        self.assertEqual(second["cache_status"], "hit")
        self.assertEqual(len(calls), 1)

    def test_profile_ticket_jql_matches_h17_scope(self) -> None:
        jql = build_profile_ticket_jql("G65")

        self.assertIn("project = IDCEVODEV", jql)
        self.assertIn("statusCategory != Done", jql)
        self.assertIn('summary ~ "G65"', jql)
        self.assertIn('description ~ "G65"', jql)
        self.assertIn('labels in ("G65", "g65")', jql)

    def test_my_unresolved_ticket_jql_matches_assignment_scope(self) -> None:
        self.assertEqual(
            build_my_unresolved_ticket_jql(),
            "assignee = currentUser() AND resolution = Unresolved ORDER BY updated DESC",
        )

    def test_my_weekly_ticket_jql_includes_resolved_this_week_scope(self) -> None:
        self.assertEqual(
            build_my_weekly_ticket_jql(),
            "assignee = currentUser() AND updated >= startOfWeek() ORDER BY updated DESC",
        )
        self.assertEqual(
            build_my_weekly_ticket_jql("-7d"),
            "assignee = currentUser() AND updated >= -7d ORDER BY updated DESC",
        )
        with self.assertRaises(ValueError):
            build_my_weekly_ticket_jql("project = IDCEVODEV")

    def test_my_unresolved_ticket_search_is_read_only_and_redacts_pat(self) -> None:
        clear_jira_my_tickets_cache()
        calls: list[tuple[str, str]] = []
        fake_keyring = _FakeKeyring()

        def transport(request, timeout=30):
            calls.append((request.get_method(), request.full_url))
            return _FakeResponse(
                200,
                json.dumps(
                    {
                        "issues": [
                            {
                                "key": "IDCEVODEV-1000002",
                                "fields": {
                                    "summary": "G70 evidence package follow-up",
                                    "status": {"name": "In Progress"},
                                    "priority": {"name": "High"},
                                    "project": {"key": "IDCEVODEV"},
                                    "assignee": {"displayName": "Operator"},
                                    "updated": "2026-06-03T10:00:00.000+0200",
                                },
                            }
                        ]
                    }
                ).encode("utf-8"),
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            _write_keychain_credentials(state_dir, fake_keyring)
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": str(state_dir)}):
                with mock.patch.dict(sys.modules, {"keyring": fake_keyring}):
                    result = search_my_unresolved_tickets(max_results=3, transport=transport)

        self.assertEqual(result["status"], "available")
        self.assertEqual(result["ticket_count"], 1)
        self.assertTrue(result["read_only"])
        self.assertFalse(result["is_approval"])
        self.assertEqual(result["tickets"][0]["key"], "IDCEVODEV-1000002")
        self.assertEqual(result["tickets"][0]["priority"], "High")
        self.assertEqual(result["tickets"][0]["project"], "IDCEVODEV")
        self.assertEqual(result["tickets"][0]["assignee"], "Operator")
        self.assertEqual(result["tickets"][0]["url"], "https://jira.example/browse/IDCEVODEV-1000002")
        self.assertEqual(calls[0][0], "GET")
        self.assertIn("assignee+%3D+currentUser%28%29", calls[0][1])
        self.assertIn("resolution+%3D+Unresolved", calls[0][1])
        self.assertIn("fields=summary%2Cstatus%2Cpriority%2Cupdated%2Cproject%2Cassignee", calls[0][1])
        self.assertNotIn("test-pat-placeholder-not-real", json.dumps(result))

    def test_my_unresolved_ticket_search_failed_transport_hides_raw_error_from_summary(self) -> None:
        clear_jira_my_tickets_cache()
        fake_keyring = _FakeKeyring()

        def transport(request, timeout=30):
            raise urllib_error.URLError("offline raw detail")

        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            _write_keychain_credentials(state_dir, fake_keyring)
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": str(state_dir)}):
                with mock.patch.dict(sys.modules, {"keyring": fake_keyring}):
                    result = search_my_unresolved_tickets(transport=transport)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["summary"], "My Tickets unavailable. Check local Jira setup before retrying.")
        self.assertNotIn("offline raw detail", result["summary"])
        self.assertIn("offline raw detail", result["diagnostic_detail"])
        self.assertNotIn("test-pat-placeholder-not-real", json.dumps(result))

    def test_weekly_ticket_search_preview_loads_nothing(self) -> None:
        transport = mock.Mock(side_effect=AssertionError("transport must stay unused"))
        with mock.patch(
            "sg_preflight.jira_client.load_jira_credentials",
            side_effect=AssertionError("credentials must stay unused"),
        ):
            payload = search_my_weekly_tickets(
                since="-7d",
                confirm_network=False,
                transport=transport,
            )

        self.assertEqual(payload["status"], "not_run")
        self.assertEqual(payload["connection_status"], "not_run")
        self.assertEqual(payload["credential"]["status"], "not_loaded")
        self.assertEqual(payload["verification"]["status"], "not_run")
        self.assertFalse(payload["network_confirmed"])
        self.assertTrue(payload["confirm_network_required"])
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["ticket_count"], 0)
        self.assertEqual(payload["cache_status"], "skipped")
        self.assertEqual(payload["tickets"], [])
        self.assertEqual(payload["total_available"], None)
        self.assertEqual(payload["result_limit"], 50)
        self.assertTrue(payload["read_only"])
        self.assertFalse(payload["is_approval"])
        self.assertEqual(
            payload["summary"],
            "Jira lookup not run. Add --confirm-network to include assigned tickets.",
        )
        transport.assert_not_called()

    def test_weekly_ticket_search_preview_leaves_cache_unchanged(self) -> None:
        from sg_preflight import jira_client as jira_client_module

        sentinel_key = ("https://jira.example", "2", "-7d", 50)
        sentinel_payload = {
            "status": "available",
            "ticket_count": 1,
            "tickets": [{"key": "IDCEVODEV-1000003"}],
        }
        with mock.patch.dict(
            jira_client_module._JIRA_MY_WEEKLY_TICKETS_CACHE,
            {sentinel_key: (123456789.0, sentinel_payload)},
            clear=True,
        ):
            before = dict(jira_client_module._JIRA_MY_WEEKLY_TICKETS_CACHE)
            search_my_weekly_tickets(confirm_network=False)
            after = dict(jira_client_module._JIRA_MY_WEEKLY_TICKETS_CACHE)

        self.assertEqual(after, before)

    def test_weekly_ticket_search_preview_clamps_result_limit(self) -> None:
        preview = search_my_weekly_tickets(max_results=0, confirm_network=False)

        self.assertEqual(preview["result_limit"], 1)

    def test_weekly_ticket_confirmed_legacy_credentials_use_get_without_mutation(self) -> None:
        calls: list[tuple[str, str]] = []
        keyring_calls: list[str] = []

        class RecordingKeyring:
            def set_password(self, service: str, account: str, password: str) -> None:
                keyring_calls.append("set")

            def get_password(self, service: str, account: str) -> str | None:
                keyring_calls.append("get")
                return None

            def delete_password(self, service: str, account: str) -> None:
                keyring_calls.append("delete")

        def transport(request, timeout=30):
            calls.append((request.get_method(), request.full_url))
            return _FakeResponse(200, b'{"total":0,"issues":[]}')

        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            path = state_dir / "jira_pat.json"
            original = (
                '{\n  "jira_url": "https://jira.example",\n'
                '  "pat": "test-pat-placeholder-not-real"\n}\n'
            ).encode("utf-8")
            path.write_bytes(original)
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": str(state_dir)}):
                with mock.patch.dict(sys.modules, {"keyring": RecordingKeyring()}):
                    payload = search_my_weekly_tickets(
                        confirm_network=True,
                        transport=transport,
                    )
            saved = path.read_bytes()

        self.assertEqual(payload["status"], "available")
        self.assertEqual([method for method, _url in calls], ["GET"])
        self.assertEqual(saved, original)
        self.assertEqual(keyring_calls, [])
        self.assertNotIn("test-pat-placeholder-not-real", json.dumps(payload))

    def test_my_weekly_ticket_search_is_read_only_and_allows_done_items(self) -> None:
        clear_jira_my_tickets_cache()
        calls: list[tuple[str, str]] = []
        fake_keyring = _FakeKeyring()

        def transport(request, timeout=30):
            calls.append((request.get_method(), request.full_url))
            return _FakeResponse(
                200,
                json.dumps(
                    {
                        "total": 74,
                        "issues": [
                            {
                                "key": "IDCEVODEV-1000003",
                                "fields": {
                                    "summary": "G65 weekly ticket draft",
                                    "status": {"name": "Done", "statusCategory": {"name": "Done"}},
                                    "priority": {"name": "Medium"},
                                    "project": {"key": "IDCEVODEV"},
                                    "assignee": {"displayName": "Operator"},
                                    "updated": "2026-06-17T10:00:00.000+0200",
                                },
                            }
                        ]
                    }
                ).encode("utf-8"),
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            _write_keychain_credentials(state_dir, fake_keyring)
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": str(state_dir)}):
                with mock.patch.dict(sys.modules, {"keyring": fake_keyring}):
                    result = search_my_weekly_tickets(
                        since="-7d",
                        max_results=50,
                        confirm_network=True,
                        transport=transport,
                    )

        self.assertEqual(result["status"], "available")
        self.assertEqual(result["ticket_count"], 1)
        self.assertEqual(result["total_available"], 74)
        self.assertTrue(result["read_only"])
        self.assertFalse(result["is_approval"])
        self.assertEqual(result["tickets"][0]["key"], "IDCEVODEV-1000003")
        self.assertEqual(result["tickets"][0]["status"], "Done")
        self.assertEqual(result["tickets"][0]["status_category"], "Done")
        self.assertEqual(calls[0][0], "GET")
        self.assertIn("assignee+%3D+currentUser%28%29", calls[0][1])
        self.assertIn("updated+%3E%3D+-7d", calls[0][1])
        self.assertNotIn("resolution+%3D+Unresolved", calls[0][1])
        self.assertIn("fields=summary%2Cstatus%2Cpriority%2Cupdated%2Cproject%2Cassignee", calls[0][1])
        self.assertNotIn("test-pat-placeholder-not-real", json.dumps(result))

    def test_my_weekly_ticket_search_reports_missing_credentials_without_transport(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": str(Path(temp_dir) / "missing")}):
                with mock.patch("pathlib.Path.home", return_value=Path(temp_dir) / "home"):
                    with mock.patch("pathlib.Path.cwd", return_value=Path(temp_dir) / "cwd"):
                        result = search_my_weekly_tickets(confirm_network=True)

        self.assertEqual(result["status"], "missing")
        self.assertEqual(result["ticket_count"], 0)
        self.assertTrue(result["read_only"])
        self.assertIn("Weekly Tickets unavailable", result["summary"])

    def test_my_weekly_ticket_search_reports_failed_transport_without_raising(self) -> None:
        fake_keyring = _FakeKeyring()

        def transport(request, timeout=30):
            raise urllib_error.URLError("offline")

        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            _write_keychain_credentials(state_dir, fake_keyring)
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": str(state_dir)}):
                with mock.patch.dict(sys.modules, {"keyring": fake_keyring}):
                    result = search_my_weekly_tickets(confirm_network=True, transport=transport)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["ticket_count"], 0)
        self.assertIn("Weekly Tickets unavailable", result["summary"])
        self.assertNotIn("test-pat-placeholder-not-real", json.dumps(result))

    def test_weekly_ticket_confirmed_missing_and_offline_stay_distinct_from_preview(self) -> None:
        preview = search_my_weekly_tickets(confirm_network=False)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": str(root / "missing")}):
                with mock.patch("pathlib.Path.home", return_value=root / "home"):
                    with mock.patch("pathlib.Path.cwd", return_value=root / "cwd"):
                        missing = search_my_weekly_tickets(confirm_network=True)

            state_dir = root / "state"
            fake_keyring = _FakeKeyring()
            _write_keychain_credentials(state_dir, fake_keyring)
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": str(state_dir)}):
                with mock.patch.dict(sys.modules, {"keyring": fake_keyring}):
                    failed = search_my_weekly_tickets(
                        confirm_network=True,
                        transport=mock.Mock(side_effect=urllib_error.URLError("offline")),
                    )

        self.assertEqual(preview["status"], "not_run")
        self.assertEqual(missing["status"], "missing")
        self.assertEqual(failed["status"], "failed")
        self.assertFalse(preview["network_confirmed"])
        self.assertTrue(missing["network_confirmed"])
        self.assertTrue(failed["network_confirmed"])

    def test_post_comment_action_previews_with_gets_before_auto_confirm_posts(self) -> None:
        calls: list[tuple[str, str, object]] = []
        fake_keyring = _FakeKeyring()

        def transport(request, timeout=30):
            payload = json.loads(request.data.decode("utf-8")) if request.data else None
            calls.append((request.get_method(), request.full_url, payload))
            if request.get_method() == "POST":
                return _FakeResponse(
                    201,
                    b'{"id":"10001","self":"https://jira.example/rest/api/2/issue/IDCEVODEV-1009244/comment/10001"}',
                )
            return _FakeResponse(200, b'{"key":"IDCEVODEV-1009244"}')

        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            _write_keychain_credentials(state_dir, fake_keyring)
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": str(state_dir)}):
                with mock.patch.dict(sys.modules, {"keyring": fake_keyring}):
                    preview = post_jira_comment_action(
                        "IDCEVODEV-1009244",
                        "Integration test comment.",
                        confirm_network=True,
                        transport=transport,
                    )
                    posted = post_jira_comment_action(
                        "IDCEVODEV-1009244",
                        "Integration test comment.",
                        auto_confirm=True,
                        confirm_network=True,
                        transport=transport,
                    )

        self.assertEqual(preview["status"], "skipped")
        self.assertTrue(preview["confirm_required"])
        self.assertEqual([method for method, _url, _payload in calls[:2]], ["GET", "GET"])
        self.assertEqual(posted["status"], "recorded")
        self.assertEqual(calls[-1][0], "POST")
        self.assertEqual(calls[-1][2], {"body": "Integration test comment."})

    def test_update_issue_and_attach_file_actions_are_confirmation_gated(self) -> None:
        calls: list[tuple[str, str]] = []
        fake_keyring = _FakeKeyring()

        def transport(request, timeout=30):
            calls.append((request.get_method(), request.full_url))
            return _FakeResponse(200 if request.get_method() == "GET" else 204, b"{}")

        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir) / "state"
            state_dir.mkdir()
            _write_keychain_credentials(state_dir, fake_keyring)
            attachment = Path(temp_dir) / "evidence.txt"
            attachment.write_text("fixture\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": str(state_dir)}):
                with mock.patch.dict(sys.modules, {"keyring": fake_keyring}):
                    update_preview = update_jira_issue_action(
                        "IDCEVODEV-1009244",
                        {"summary": "Updated summary"},
                        confirm_network=True,
                        transport=transport,
                    )
                    attach_preview = attach_jira_file_action(
                        "IDCEVODEV-1009244",
                        attachment,
                        confirm_network=True,
                        transport=transport,
                    )

        self.assertEqual(update_preview["status"], "skipped")
        self.assertEqual(update_preview["fields"]["fields"]["summary"], "Updated summary")
        self.assertEqual(attach_preview["status"], "skipped")
        self.assertEqual(attach_preview["attachments"][0]["name"], "evidence.txt")
        self.assertEqual([method for method, _url in calls], ["GET", "GET", "GET", "GET"])


class TestFacadePatchTargets(unittest.TestCase):
    def test_facade_level_credential_patch_intercepts_sibling_calls(self) -> None:
        from sg_preflight import jira_client, jira_client_search

        calls: list[bool] = []

        def fake_load(*args: object, **kwargs: object) -> object:
            calls.append(True)
            raise jira_client.ConfigError("patched out for the facade contract test")

        def no_network(*args: object, **kwargs: object) -> object:
            raise AssertionError("the network path must not be reached")

        with mock.patch.object(jira_client_search, "_JIRA_MY_TICKETS_CACHE", {}):
            with mock.patch.object(jira_client, "load_jira_credentials", fake_load):
                result = jira_client.search_my_unresolved_tickets(transport=no_network)

        self.assertTrue(calls, "the facade-level patch was not honored by the search sibling")
        self.assertEqual(result["status"], "missing")
