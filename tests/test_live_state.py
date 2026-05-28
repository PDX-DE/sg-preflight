"""H-26 tests for the live observability surface."""
from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sg_preflight.activity_log import (
    _cutoff_for_since,
    _utc_now,
    append_activity_entry,
    read_activity_entries,
)
from sg_preflight.live_state import (
    DEFAULT_DEBOUNCE_MS,
    DebouncedLiveStateWriter,
    LastOperatorAction,
    LIVE_STATE_SCHEMA_VERSION,
    LiveStateSnapshot,
    RunningSubprocess,
    live_state_path,
    read_live_state,
    sanitize_payload,
    write_live_state,
)


class LiveStateSnapshotTests(unittest.TestCase):
    def test_snapshot_to_payload_carries_canonical_schema(self) -> None:
        snap = LiveStateSnapshot(
            dashboard_surface="full-qa-pass",
            profile_id="F70",
            wizard_step_id="screenshot-test-state",
            wizard_step_index=3,
            wizard_step_total=9,
            queued_acknowledgments=("risk-score", "manual-review-assist"),
            running_subprocess=RunningSubprocess(
                name="build_full_qa_pass",
                started_at="2026-05-29T01:30:00.000Z",
                pid_present=True,
            ),
            last_operator_action=LastOperatorAction(
                verb="ran",
                surface="full-qa-pass:run",
                ts="2026-05-29T01:30:00.000Z",
            ),
            last_error=None,
        )

        payload = snap.to_payload(ts="2026-05-29T01:30:00.123Z")

        self.assertEqual(payload["schema_version"], LIVE_STATE_SCHEMA_VERSION)
        self.assertEqual(payload["ts"], "2026-05-29T01:30:00.123Z")
        self.assertEqual(payload["dashboard_surface"], "full-qa-pass")
        self.assertEqual(payload["profile_id"], "F70")
        self.assertEqual(payload["wizard_step_id"], "screenshot-test-state")
        self.assertEqual(payload["wizard_step_index"], 3)
        self.assertEqual(payload["wizard_step_total"], 9)
        self.assertEqual(payload["queued_acknowledgments"], ["risk-score", "manual-review-assist"])
        self.assertEqual(payload["running_subprocess"]["name"], "build_full_qa_pass")
        self.assertTrue(payload["running_subprocess"]["pid_present"])
        self.assertEqual(payload["last_operator_action"]["verb"], "ran")
        self.assertIsNone(payload["last_error"])

    def test_sanitize_payload_masks_pat_like_tokens(self) -> None:
        scrubbed = sanitize_payload({
            "pat": "abcdef1234567890abcdef1234567890XYZW",
            "note": "Authorization: Bearer SECRETTOKENVALUE here",
            "json_blob": '{"token": "0123456789abcdef0123456789abcdef"}',
        })

        # 32+ char tokens are masked to ****<last4>
        self.assertIn("****XYZW", scrubbed["pat"])
        self.assertNotIn("abcdef1234567890abcdef1234567890XYZW", scrubbed["pat"])
        # Bearer suffix scrubbed
        self.assertIn("Bearer ****", scrubbed["note"])
        self.assertNotIn("SECRETTOKENVALUE", scrubbed["note"])
        # Nested string token also scrubbed
        self.assertNotIn("0123456789abcdef0123456789abcdef", scrubbed["json_blob"])


class DebouncedLiveStateWriterTests(unittest.TestCase):
    def test_debounce_coalesces_bursts_into_single_disk_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            writer = DebouncedLiveStateWriter(workspace, debounce_ms=120)

            # Three rapid updates within the debounce window — should produce one
            # write after the timer fires.
            for index in range(3):
                writer.update(LiveStateSnapshot(dashboard_surface=f"surface-{index}", profile_id="F70"))

            # Wait long enough for the debounced timer to fire.
            time.sleep(0.3)

            path = live_state_path(workspace)
            self.assertTrue(path.is_file(), "live_state.json should exist after debounce drain")
            payload = json.loads(path.read_text(encoding="utf-8"))
            # The LAST update wins.
            self.assertEqual(payload["dashboard_surface"], "surface-2")
            writer.close()

    def test_write_through_top_level_helper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            snapshot = LiveStateSnapshot(
                dashboard_surface="dashboard:index",
                profile_id="G65",
                wizard_step_id="onboarding",
                wizard_step_index=0,
                wizard_step_total=9,
            )
            write_live_state(workspace, snapshot)
            time.sleep(0.4)  # let the debounce window elapse
            out = read_live_state(workspace)
            self.assertEqual(out.get("status"), "available")
            self.assertEqual(out["profile_id"], "G65")

    def test_read_live_state_unavailable_when_no_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = read_live_state(Path(tmp))
            self.assertEqual(out["status"], "unavailable")
            self.assertIn("live_state.json", out["path"])


class ActivityLogH26EnrichmentTests(unittest.TestCase):
    def test_timestamp_has_millisecond_precision(self) -> None:
        ts = _utc_now(datetime(2026, 5, 29, 1, 30, 0, 123456, tzinfo=timezone.utc))
        # ISO with ms precision ends with .NNNZ
        self.assertRegex(ts, r"^2026-05-29T01:30:00\.\d{3}Z$")

    def test_append_supports_new_lifecycle_verbs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "operator_state").mkdir(parents=True, exist_ok=True)
            for verb, surface in (
                ("started", "subprocess:build_full_qa_pass"),
                ("exited", "subprocess:build_full_qa_pass"),
                ("entered", "wizard:screenshot-test-state"),
                ("completed", "wizard:screenshot-test-state"),
                ("clicked", "button:run-full-qa-pass"),
                ("dismissed", "modal:high-risk-confirm"),
                ("errored", "subprocess:capture_screenshots"),
                ("cancelled", "wizard:full-qa-pass"),
            ):
                entry = append_activity_entry(
                    workspace, verb=verb, surface=surface, profile="F70", outcome="ok"
                )
                self.assertEqual(entry["verb"], verb)
                self.assertEqual(entry["surface"], surface)

    def test_since_accepts_free_form_durations(self) -> None:
        now = datetime(2026, 5, 29, 1, 30, 0, tzinfo=timezone.utc)
        for spec, expected_delta in (
            ("30s", timedelta(seconds=30)),
            ("5 min", timedelta(minutes=5)),
            ("5 min ago", timedelta(minutes=5)),
            ("1h", timedelta(hours=1)),
            ("2 hours", timedelta(hours=2)),
            ("3 days ago", timedelta(days=3)),
        ):
            cutoff = _cutoff_for_since(spec, now)
            self.assertIsNotNone(cutoff, f"Free-form '{spec}' should parse")
            self.assertEqual(cutoff, now - expected_delta, f"Failed for spec {spec!r}")

    def test_since_keyword_filters_still_work_after_h26(self) -> None:
        now = datetime(2026, 5, 29, 12, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(_cutoff_for_since("today", now), datetime(2026, 5, 29, tzinfo=timezone.utc))
        self.assertEqual(_cutoff_for_since("yesterday", now), datetime(2026, 5, 28, tzinfo=timezone.utc))
        self.assertIsNone(_cutoff_for_since("all", now))

    def test_full_qa_pass_run_writes_one_entry_per_simulated_click(self) -> None:
        """Carry-forward from H-25: ensure the lifecycle verbs do not regress the
        H-25 idempotency guarantee — one click stays one entry."""
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "operator_state").mkdir(parents=True, exist_ok=True)

            append_activity_entry(
                workspace, verb="ran", surface="full-qa-pass:run", profile="F70", outcome="ok"
            )

            payload = read_activity_entries(workspace, profile="F70", since="all")
            run_entries = [
                entry for entry in payload["entries"]
                if entry.get("surface") == "full-qa-pass:run"
            ]
            self.assertEqual(len(run_entries), 1)


if __name__ == "__main__":
    unittest.main()
