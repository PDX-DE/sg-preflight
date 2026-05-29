"""H-35 source guards + light behavioural tests for the Jira external-browser
handoff and the Teams clipboard fallback."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock


class JiraExternalBrowserHandoffTests(unittest.TestCase):
    def test_helper_invokes_webbrowser_open_with_new_external_window(self) -> None:
        """`_open_jira_ticket_in_browser` must call `webbrowser.open(url, new=2,
        autoraise=True)` so the operator's default external browser handles the
        Jira redirect via their existing SSO session (no in-app re-login)."""
        from sg_preflight.dashboard import main as dashboard_main

        opens: list[tuple[str, int, bool]] = []
        notifies: list[str] = []
        js_calls: list[str] = []

        class FakeUi:
            def notify(self, message: str, *args, **kwargs) -> None:
                notifies.append(str(message))

            def run_javascript(self, payload: str) -> None:
                js_calls.append(payload)

        def fake_open(url: str, new: int = 0, autoraise: bool = True) -> bool:
            opens.append((url, new, autoraise))
            return True

        with mock.patch.object(dashboard_main.webbrowser, "open", side_effect=fake_open):
            dashboard_main._open_jira_ticket_in_browser(
                FakeUi(),
                "https://jira.cc.bmwgroup.net/browse/IDCEVODEV-1009244",
                "IDCEVODEV-1009244",
            )

        self.assertEqual(len(opens), 1, opens)
        url, new, _autoraise = opens[0]
        self.assertEqual(url, "https://jira.cc.bmwgroup.net/browse/IDCEVODEV-1009244")
        self.assertEqual(new, 2, "webbrowser.open must use new=2 so a new browser window opens")
        # Clipboard fallback fired.
        self.assertEqual(len(js_calls), 1)
        self.assertIn("navigator.clipboard.writeText", js_calls[0])
        self.assertIn("IDCEVODEV-1009244", js_calls[0])
        # Notify shown with the success wording.
        self.assertEqual(len(notifies), 1)
        self.assertIn("Opened IDCEVODEV-1009244", notifies[0])
        self.assertIn("URL copied to clipboard", notifies[0])

    def test_helper_falls_back_gracefully_when_webbrowser_open_fails(self) -> None:
        """If `webbrowser.open` raises or returns False, the notify must say
        the operator can paste from the clipboard manually."""
        from sg_preflight.dashboard import main as dashboard_main

        notifies: list[str] = []

        class FakeUi:
            def notify(self, message: str, *args, **kwargs) -> None:
                notifies.append(str(message))

            def run_javascript(self, payload: str) -> None:
                pass

        # Case 1: open() returns False.
        with mock.patch.object(dashboard_main.webbrowser, "open", return_value=False):
            dashboard_main._open_jira_ticket_in_browser(FakeUi(), "https://example/browse/X-1", "X-1")
        self.assertEqual(len(notifies), 1)
        self.assertIn("Could not launch a browser", notifies[0])
        self.assertIn("URL copied to clipboard", notifies[0])

        # Case 2: open() raises.
        notifies.clear()
        with mock.patch.object(dashboard_main.webbrowser, "open", side_effect=RuntimeError("boom")):
            dashboard_main._open_jira_ticket_in_browser(FakeUi(), "https://example/browse/X-2", "X-2")
        self.assertEqual(len(notifies), 1)
        self.assertIn("Could not launch a browser", notifies[0])


class TeamsClipboardFallbackTests(unittest.TestCase):
    def test_teams_open_handler_also_copies_message_to_clipboard(self) -> None:
        """H-35 Part B source guard: the `sgfxOpenFeedbackTeams` JS handler must
        ALSO write the prefilled message to the clipboard so the action is never
        lost if Teams doesn't open."""
        source = (
            Path(__file__).resolve().parents[1] / "sg_preflight" / "dashboard" / "main.py"
        ).read_text(encoding="utf-8")
        idx = source.find("window.sgfxOpenFeedbackTeams")
        self.assertNotEqual(idx, -1, "sgfxOpenFeedbackTeams handler not found")
        block = source[idx:idx + 2500]
        # msteams:// deep-link still fires (H-33 behaviour preserved).
        self.assertIn("window.sgfxBuildFeedbackTeams()", block)
        self.assertIn("document.createElement('a')", block)
        self.assertIn("link.click()", block)
        # H-35 Part B: clipboard fallback.
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
