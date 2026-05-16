from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from sg_preflight.jira_client import (
    JIRA_POSTING_BANNER,
    JiraPostError,
    extract_numbered_section_text,
    post_jira_comment,
)


class _FakeResponse:
    status = 201

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return b'{"id":"10001","self":"https://jira.example/rest/api/2/issue/IDCEVODEV-977874/comment/10001"}'


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
            token="secret",
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
            post_jira_comment("IDCEVODEV-977874", "Status update", token="secret", confirm=True)

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
            token="secret",
            confirm=True,
            transport=transport,
        )

        self.assertEqual(result["status"], "posted")
        self.assertTrue(result["posted"])
        self.assertFalse(result["dry_run"])
        self.assertEqual(captured["url"], "https://jira.example/rest/api/2/issue/IDCEVODEV-977874/comment")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["payload"], {"body": "Status update"})
        self.assertEqual(captured["headers"]["Authorization"], "Bearer secret")
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
