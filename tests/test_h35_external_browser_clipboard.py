"""internal milestone source guards + light behavioural tests for dashboard clipboard flows."""
from __future__ import annotations

import unittest
from pathlib import Path


class JiraClipboardOnlyTests(unittest.TestCase):
    def test_helper_copies_ticket_url_without_browser_open(self) -> None:
        """Jira ticket clicks are copy-only; the browser reports copy success."""
        from sg_preflight.dashboard import main as dashboard_main

        notifies: list[str] = []
        js_calls: list[str] = []

        class FakeUi:
            def notify(self, message: str, *args, **kwargs) -> None:
                notifies.append(str(message))

            def run_javascript(self, payload: str) -> None:
                js_calls.append(payload)

        dashboard_main._copy_dashboard_link_to_clipboard(
            FakeUi(),
            "https://jira.cc.bmwgroup.net/browse/IDCEVODEV-1009244",
            "IDCEVODEV-1009244",
        )

        self.assertEqual(len(js_calls), 1)
        self.assertIn("navigator.clipboard.writeText", js_calls[0])
        self.assertIn("document.execCommand('copy')", js_calls[0])
        self.assertIn("https://jira.cc.bmwgroup.net/browse/IDCEVODEV-1009244", js_calls[0])
        self.assertIn("IDCEVODEV-1009244", js_calls[0])
        self.assertIn("Copied to clipboard: ${label}", js_calls[0])
        self.assertIn("Couldn't copy automatically. Link:", js_calls[0])
        self.assertEqual(notifies, [])

    def test_helper_still_notifies_if_clipboard_javascript_fails(self) -> None:
        from sg_preflight.dashboard import main as dashboard_main

        notifies: list[str] = []

        class FakeUi:
            def notify(self, message: str, *args, **kwargs) -> None:
                notifies.append(str(message))

            def run_javascript(self, payload: str) -> None:
                raise RuntimeError("clipboard unavailable")

        dashboard_main._copy_dashboard_link_to_clipboard(FakeUi(), "https://example/browse/X-1", "X-1")
        self.assertEqual(len(notifies), 1)
        self.assertEqual(notifies[0], "Couldn't start clipboard copy. Link: https://example/browse/X-1")

    def test_dashboard_source_has_no_jira_webbrowser_open_path(self) -> None:
        base = Path(__file__).resolve().parents[1] / "sg_preflight" / "dashboard"
        helper_source = (base / "panels_common.py").read_text(encoding="utf-8")
        source = (base / "main.py").read_text(encoding="utf-8") + helper_source
        self.assertNotIn("import webbrowser", source)
        jira_helper_idx = helper_source.find("def _copy_dashboard_link_to_clipboard")
        self.assertNotEqual(jira_helper_idx, -1, "clipboard helper not found")
        helper_end = helper_source.find("\n\ndef ", jira_helper_idx)
        if helper_end == -1:
            helper_end = len(helper_source)
        helper_body = helper_source[jira_helper_idx:helper_end]
        self.assertNotIn("webbrowser.open", helper_body)
        self.assertIn("navigator.clipboard.writeText", helper_body)
        self.assertIn("document.execCommand('copy')", helper_body)
        self.assertIn("Copied to clipboard:", helper_body)
        self.assertIn("Couldn't copy automatically. Link:", helper_body)


class TeamsClipboardFallbackTests(unittest.TestCase):
    def test_teams_open_handler_also_copies_message_to_clipboard(self) -> None:
        """internal milestone Part B source guard: the `sgfxOpenFeedbackTeams` JS handler must
        ALSO write the prefilled message to the clipboard so the action is never
        lost if Teams doesn't open."""
        source = (
            Path(__file__).resolve().parents[1] / "sg_preflight" / "dashboard" / "main.py"
        ).read_text(encoding="utf-8")
        idx = source.find("window.sgfxOpenFeedbackTeams")
        self.assertNotEqual(idx, -1, "sgfxOpenFeedbackTeams handler not found")
        block = source[idx:idx + 2500]
        # msteams:// deep-link still fires (internal milestone behaviour preserved).
        self.assertIn("window.sgfxBuildFeedbackTeams()", block)
        self.assertIn("document.createElement('a')", block)
        self.assertIn("link.click()", block)
        # internal milestone Part B: clipboard fallback.
        self.assertIn("navigator.clipboard.writeText(fullMessage)", block)
        # Inline toast notifying the operator the message was also copied.
        self.assertIn("Teams should open; message also copied to clipboard.", block)

    def test_feedback_toast_helper_renders_via_inline_dom_not_nicegui_socket(self) -> None:
        """The toast must NOT require an active NiceGUI WebSocket connection so
        the message-copied notice fires even when the operator is on a stale
        tab. Source guard for `sgfxNotifyFeedbackToast`."""
        source = (
            Path(__file__).resolve().parents[1] / "sg_preflight" / "dashboard" / "main.py"
        ).read_text(encoding="utf-8")
        # Find the toast assignment (skip the earlier reference inside
        # sgfxOpenFeedbackTeams) by anchoring on the function definition.
        marker = "window.sgfxNotifyFeedbackToast = (message)"
        idx = source.find(marker)
        self.assertNotEqual(idx, -1, "sgfxNotifyFeedbackToast helper definition not found")
        block = source[idx:idx + 2200]
        self.assertIn("document.createElement('div')", block)
        self.assertIn("sgfxFeedbackToast", block)
        self.assertIn("setTimeout(() => toast.remove(), 3500)", block, "toast should auto-dismiss after a few seconds")


if __name__ == "__main__":
    unittest.main()
