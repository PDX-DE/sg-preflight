from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from sg_preflight.jira_client import (
    ConfigError,
    JIRA_POSTING_BANNER,
    JiraPostError,
    attach_jira_file_action,
    extract_numbered_section_text,
    jira_status,
    load_jira_credentials,
    post_jira_comment,
    post_jira_comment_action,
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

    def test_confirm_requires_base_url_and_pat(self) -> None:
        with self.assertRaises(JiraPostError) as missing_base:
            post_jira_comment("IDCEVODEV-977874", "Status update", token="test-pat-placeholder-not-real", confirm=True)

        with self.assertRaises(JiraPostError) as missing_token:
            post_jira_comment("IDCEVODEV-977874", "Status update", base_url="https://jira.example", confirm=True)

        self.assertIn("base URL", str(missing_base.exception))
        self.assertIn("PAT", str(missing_token.exception))

    def test_confirm_posts_one_comment_to_jira_rest_endpoint(self) -> None:
        captured: dict[str, object] = {}

        def transport(request, timeout=30):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            captured["headers"] = dict(request.header_items())
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return _FakeResponse()

        result = post_jira_comment(
            "IDCEVODEV-977874",
            "Status update",
            base_url="https://jira.example/",
            token="test-pat-placeholder-not-real",
            confirm=True,
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

    def test_load_jira_credentials_prefers_operator_state_env_without_echoing_pat(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir) / "state"
            path = state_dir / "jira_pat.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps({"jira_url": "https://jira.example", "pat": "test-pat-placeholder-not-real"}),
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": str(state_dir)}):
                credentials = load_jira_credentials()

        self.assertEqual(credentials["jira_url"], "https://jira.example")
        self.assertEqual(credentials["pat"], "test-pat-placeholder-not-real")
        self.assertTrue(credentials["path"].endswith("jira_pat.json"))

    def test_load_jira_credentials_accepts_legacy_token_key_without_echoing_pat(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir) / "state"
            path = state_dir / "jira_pat.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps({"jira_url": "https://jira.example", "pat_api_id": "test-pat-placeholder-not-real"}),
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": str(state_dir)}):
                credentials = load_jira_credentials()

        self.assertEqual(credentials["pat"], "test-pat-placeholder-not-real")

    def test_load_jira_credentials_reports_missing_with_remediation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": str(Path(temp_dir) / "missing")}):
                with mock.patch("pathlib.Path.home", return_value=Path(temp_dir) / "home"):
                    with mock.patch("pathlib.Path.cwd", return_value=Path(temp_dir) / "cwd"):
                        with self.assertRaises(ConfigError) as caught:
                            load_jira_credentials()

        self.assertIn("Jira PAT is missing", str(caught.exception))

    def test_write_jira_credentials_records_operator_local_file_with_redacted_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = write_jira_credentials(
                jira_url="https://jira.example/",
                pat="test-pat-placeholder-not-real",
                state_dir=temp_dir,
            )
            path = Path(temp_dir) / "jira_pat.json"
            saved = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "recorded")
        self.assertEqual(saved["jira_url"], "https://jira.example")
        self.assertEqual(saved["pat"], "test-pat-placeholder-not-real")
        self.assertNotIn("test-pat-placeholder-not-real", json.dumps(result))
        self.assertEqual(result["credential"]["pat_fingerprint"], "****real")

    def test_jira_status_runs_read_only_connection_and_ticket_gets(self) -> None:
        calls: list[tuple[str, str]] = []

        def transport(request, timeout=30):
            calls.append((request.get_method(), request.full_url))
            return _FakeResponse(200, b'{"name":"operator"}')

        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            (state_dir / "jira_pat.json").write_text(
                json.dumps({"jira_url": "https://jira.example", "pat": "test-pat-placeholder-not-real"}),
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": str(state_dir)}):
                result = jira_status(ticket="IDCEVODEV-1009244", transport=transport)

        self.assertEqual(result["status"], "available")
        self.assertEqual(result["connection_status"], "available")
        self.assertEqual(result["ticket_status"], "available")
        self.assertEqual([method for method, _url in calls], ["GET", "GET"])
        self.assertNotIn("test-pat-placeholder-not-real", json.dumps(result))

    def test_post_comment_action_previews_with_gets_before_auto_confirm_posts(self) -> None:
        calls: list[tuple[str, str, object]] = []

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
            (state_dir / "jira_pat.json").write_text(
                json.dumps({"jira_url": "https://jira.example", "pat": "test-pat-placeholder-not-real"}),
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": str(state_dir)}):
                preview = post_jira_comment_action(
                    "IDCEVODEV-1009244",
                    "Integration test comment.",
                    transport=transport,
                )
                posted = post_jira_comment_action(
                    "IDCEVODEV-1009244",
                    "Integration test comment.",
                    auto_confirm=True,
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

        def transport(request, timeout=30):
            calls.append((request.get_method(), request.full_url))
            return _FakeResponse(200 if request.get_method() == "GET" else 204, b"{}")

        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir) / "state"
            state_dir.mkdir()
            (state_dir / "jira_pat.json").write_text(
                json.dumps({"jira_url": "https://jira.example", "pat": "test-pat-placeholder-not-real"}),
                encoding="utf-8",
            )
            attachment = Path(temp_dir) / "evidence.txt"
            attachment.write_text("fixture\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": str(state_dir)}):
                update_preview = update_jira_issue_action(
                    "IDCEVODEV-1009244",
                    {"summary": "Updated summary"},
                    transport=transport,
                )
                attach_preview = attach_jira_file_action(
                    "IDCEVODEV-1009244",
                    attachment,
                    transport=transport,
                )

        self.assertEqual(update_preview["status"], "skipped")
        self.assertEqual(update_preview["fields"]["fields"]["summary"], "Updated summary")
        self.assertEqual(attach_preview["status"], "skipped")
        self.assertEqual(attach_preview["attachments"][0]["name"], "evidence.txt")
        self.assertEqual([method for method, _url in calls], ["GET", "GET", "GET", "GET"])
