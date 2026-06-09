from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from sg_preflight.cli import main
from sg_preflight.session_log import (
    _reset_session_log_for_tests,
    event,
    exception_event,
    export_session_log,
    latest_session_payload,
    read_session_records,
    start_session_log,
)


RAW_TOKEN = "abcdef1234567890abcdef1234567890XYZW"


class SessionLogTests(unittest.TestCase):
    def tearDown(self) -> None:
        _reset_session_log_for_tests()

    def test_session_log_writes_scrubbed_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            session = start_session_log(workspace)
            event(
                source="cli",
                surface="doctor",
                profile="G65",
                message="Diagnostic command completed",
                detail={"token": RAW_TOKEN, "authorization": f"Bearer {RAW_TOKEN}"},
            )

            self.assertEqual(session.path.parent, workspace.resolve() / "operator_state" / "sessions")
            records = read_session_records(session.path)
            raw_text = session.path.read_text(encoding="utf-8")

            self.assertGreaterEqual(len(records), 2)
            self.assertEqual(records[-1]["source"], "cli")
            self.assertEqual(records[-1]["surface"], "doctor")
            self.assertNotIn(RAW_TOKEN, raw_text)
            self.assertIn("****XYZW", raw_text)
            self.assertIn("Bearer ****", raw_text)

    def test_planted_exception_lands_in_session_log_scrubbed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            session = start_session_log(workspace)

            try:
                raise RuntimeError(f"forced crash with token {RAW_TOKEN}")
            except RuntimeError as exc:
                exception_event(surface="forced-exception-smoke", exc=exc)

            raw_text = session.path.read_text(encoding="utf-8")
            records = read_session_records(session.path)
            self.assertEqual(records[-1]["source"], "exception")
            self.assertEqual(records[-1]["level"], "error")
            self.assertIn("forced-exception-smoke", records[-1]["surface"])
            self.assertNotIn(RAW_TOKEN, raw_text)
            self.assertIn("****XYZW", raw_text)

    def test_export_bundles_session_and_scrubbed_referenced_logs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / ("a" * 32)
            workspace.mkdir()
            session = start_session_log(workspace)
            stderr_path = workspace / "operator_state" / "screenshot_capture" / "G65.stderr.log"
            stderr_path.parent.mkdir(parents=True, exist_ok=True)
            stderr_path.write_text(f"failed with Bearer {RAW_TOKEN}\n", encoding="utf-8")
            event(
                source="subprocess",
                surface="screenshot_capture",
                profile="G65",
                level="error",
                message="BMW screenshot capture completed",
                detail={"exit_code": 7, "stderr_path": str(stderr_path), "stderr_tail": f"Bearer {RAW_TOKEN}"},
            )

            zip_path = workspace / "operator_state" / "session-export.zip"
            payload = export_session_log(workspace, zip_output=zip_path)

            self.assertEqual(payload["referenced_log_count"], 1)
            self.assertTrue(zip_path.is_file())
            with zipfile.ZipFile(zip_path) as archive:
                names = archive.namelist()
                self.assertIn("session-log.jsonl", names)
                referenced = [name for name in names if name.startswith("referenced/")]
                self.assertEqual(len(referenced), 1)
                session_text = archive.read("session-log.jsonl").decode("utf-8")
                stderr_text = archive.read(referenced[0]).decode("utf-8")
            self.assertNotIn(RAW_TOKEN, session_text)
            self.assertNotIn(RAW_TOKEN, stderr_text)
            self.assertIn("Bearer ****", stderr_text)
            self.assertIn(str(session.path), payload["session_log_path"])

    def test_cli_latest_and_export_use_latest_session_log(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            start_session_log(workspace)
            event(source="ui", surface="dashboard", message="Dashboard session started", detail={"workspace": str(workspace)})

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = main(["session-log", "latest", "--workspace", str(workspace), "--tail", "5"])
            latest_output = out.getvalue()
            self.assertEqual(exit_code, 0)
            self.assertIn("Session log:", latest_output)
            self.assertIn("Dashboard session started", latest_output)

            zip_path = workspace / "diag.zip"
            out = io.StringIO()
            with redirect_stdout(out):
                export_code = main(["session-log", "export", "--workspace", str(workspace), "--zip-output", str(zip_path), "--json"])
            payload = json.loads(out.getvalue())
            self.assertEqual(export_code, 0)
            self.assertEqual(payload["zip_path"], str(zip_path.resolve()))
            self.assertTrue(zip_path.is_file())

            out = io.StringIO()
            with mock.patch.dict("os.environ", {"SGFX_PREFLIGHT_WORKSPACE": str(workspace)}, clear=False):
                with redirect_stdout(out):
                    env_code = main(["session-log", "latest", "--tail", "5"])
            self.assertEqual(env_code, 0)
            self.assertIn("Dashboard session started", out.getvalue())

    def test_latest_payload_reports_missing_log(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            payload = latest_session_payload(Path(temp_dir))

            self.assertEqual(payload["path"], "")
            self.assertEqual(payload["records"], [])
            self.assertIn("No session logs", payload["note"])


if __name__ == "__main__":
    unittest.main()
