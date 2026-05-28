from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest import mock

from sg_preflight.cli import main
from sg_preflight.desktop_notifications import notify_desktop_completion


class TestDesktopNotifications(unittest.TestCase):
    def test_notify_desktop_completion_dry_run_records_local_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            payload = notify_desktop_completion(
                title="Done",
                message="Action completed.",
                workspace=Path(temp_dir),
                action_id="test-action",
                profile_id="G70",
                dry_run=True,
            )

            self.assertEqual(payload["status"], "recorded")
            self.assertEqual(payload["delivery_status"], "skipped")
            self.assertFalse(payload["shown"])
            self.assertTrue(Path(payload["record_path"]).is_file())
            self.assertFalse(payload["is_approval"])

    def test_notify_desktop_completion_uses_windows_shell_notification_runner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runner = mock.Mock(
                return_value=subprocess.CompletedProcess(
                    args=["powershell.exe"],
                    returncode=0,
                    stdout="",
                    stderr="",
                )
            )
            with mock.patch("sg_preflight.desktop_notifications.platform.system", return_value="Windows"):
                payload = notify_desktop_completion(
                    title="Done",
                    message="Action completed.",
                    workspace=Path(temp_dir),
                    action_id="test-action",
                    profile_id="G70",
                    runner=runner,
                )

            self.assertEqual(payload["delivery_status"], "available")
            self.assertTrue(payload["shown"])
            self.assertEqual(payload["method"], "windows_shell_notification")
            runner.assert_called_once()
            command = runner.call_args.args[0]
            self.assertIn("powershell.exe", command[0])
            script = command[-1]
            self.assertIn("NotifyIcon", script)
            self.assertIn("ShowBalloonTip", script)
            self.assertNotIn("TopMost", script)

    def test_cli_desktop_notification_dry_run_outputs_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = main(
                    [
                        "desktop-notification",
                        "send",
                        "--workspace",
                        temp_dir,
                        "--title",
                        "Done",
                        "--message",
                        "Action completed.",
                        "--action-id",
                        "test-action",
                        "--profile",
                        "G70",
                        "--dry-run",
                        "--format",
                        "json",
                    ]
                )

            self.assertEqual(result, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["delivery_status"], "skipped")
            self.assertTrue(Path(payload["record_path"]).is_file())


if __name__ == "__main__":
    unittest.main()
