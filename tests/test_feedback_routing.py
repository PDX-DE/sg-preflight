"""H-33 tests for the operator-configurable feedback routing module."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class FeedbackRoutingDefaultsTests(unittest.TestCase):
    def test_default_email_recipient_is_work_email(self) -> None:
        from sg_preflight.feedback_routing import (
            DEFAULT_EMAIL_RECIPIENT,
            DEFAULT_TEAMS_RECIPIENT,
        )

        # H-33: switched from personal gmail to work email so feedback lands in
        # the PDX inbox by default.
        self.assertEqual(DEFAULT_EMAIL_RECIPIENT, "david-erik.garcia-arenas@paradoxcat.com")
        self.assertEqual(DEFAULT_TEAMS_RECIPIENT, "david-erik.garcia-arenas@paradoxcat.com")

    def test_load_returns_defaults_when_no_config_exists(self) -> None:
        from sg_preflight.feedback_routing import load_feedback_routing

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": str(tmp)}):
                routing = load_feedback_routing()
        self.assertFalse(routing.config_loaded)
        self.assertEqual(routing.email_recipient, "david-erik.garcia-arenas@paradoxcat.com")
        self.assertEqual(routing.teams_recipient, "david-erik.garcia-arenas@paradoxcat.com")
        self.assertEqual(routing.primary, "email")
        self.assertEqual(routing.subject_prefix, "SGFX feedback")
        self.assertIn("feedback_routing.json", routing.config_path)


class FeedbackRoutingOverrideTests(unittest.TestCase):
    def test_config_file_overrides_default_recipients(self) -> None:
        from sg_preflight.feedback_routing import load_feedback_routing

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "feedback_routing.json").write_text(
                json.dumps({
                    "schema_version": 1,
                    "primary": "teams",
                    "teams_recipient": "team-lead@paradoxcat.com",
                    "email_recipient": "qa-inbox@paradoxcat.com",
                    "subject_prefix": "QA escalation",
                }),
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": tmp}):
                routing = load_feedback_routing()
        self.assertTrue(routing.config_loaded)
        self.assertEqual(routing.primary, "teams")
        self.assertEqual(routing.teams_recipient, "team-lead@paradoxcat.com")
        self.assertEqual(routing.email_recipient, "qa-inbox@paradoxcat.com")
        self.assertEqual(routing.subject_prefix, "QA escalation")

    def test_malformed_config_falls_back_to_defaults_without_raising(self) -> None:
        from sg_preflight.feedback_routing import load_feedback_routing

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "feedback_routing.json").write_text("{not valid json", encoding="utf-8")
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": tmp}):
                routing = load_feedback_routing()
        # Malformed config is silently ignored so the dashboard feedback surface
        # remains functional; config_loaded stays False so the operator can be
        # told the override didn't take.
        self.assertFalse(routing.config_loaded)
        self.assertEqual(routing.email_recipient, "david-erik.garcia-arenas@paradoxcat.com")

    def test_config_rejects_unparseable_recipient_and_keeps_default(self) -> None:
        from sg_preflight.feedback_routing import load_feedback_routing

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "feedback_routing.json").write_text(
                json.dumps({
                    "schema_version": 1,
                    "email_recipient": "definitely\nnot an email",
                    "teams_recipient": "<script>alert(1)</script>",
                }),
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": tmp}):
                routing = load_feedback_routing()
        self.assertTrue(routing.config_loaded)
        # Bad recipients are rejected and the hardcoded defaults stand.
        self.assertEqual(routing.email_recipient, "david-erik.garcia-arenas@paradoxcat.com")
        self.assertEqual(routing.teams_recipient, "david-erik.garcia-arenas@paradoxcat.com")

    def test_config_primary_must_be_email_or_teams(self) -> None:
        from sg_preflight.feedback_routing import load_feedback_routing

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "feedback_routing.json").write_text(
                json.dumps({"schema_version": 1, "primary": "slack"}),
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": tmp}):
                routing = load_feedback_routing()
        self.assertEqual(routing.primary, "email")  # falls back to default

    def test_to_payload_surfaces_only_routing_and_config_metadata(self) -> None:
        from sg_preflight.feedback_routing import load_feedback_routing, to_payload

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"SGFX_OPERATOR_STATE_DIR": tmp}):
                routing = load_feedback_routing()
            payload = to_payload(routing)
        self.assertEqual(
            set(payload.keys()),
            {"primary", "email_recipient", "teams_recipient", "subject_prefix", "config_path", "config_loaded"},
        )


class FeedbackRoutingDashboardWiringTests(unittest.TestCase):
    """H-33 source guards on the dashboard wiring — the buttons must exist + the
    JS must read the routing context."""

    def test_dashboard_source_has_open_email_and_open_teams_buttons(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "sg_preflight" / "dashboard" / "main.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('data-sgfx-feedback-channel="email"', source)
        self.assertIn("Open email</button>", source)
        self.assertIn('data-sgfx-feedback-channel="teams"', source)
        self.assertIn("Open Teams</button>", source)
        self.assertIn("window.sgfxOpenFeedbackTeams", source)

    def test_dashboard_teams_deep_link_uses_msteams_protocol(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "sg_preflight" / "dashboard" / "main.py").read_text(
            encoding="utf-8"
        )
        # JS must build the msteams:// URL with the encoded recipient + message.
        self.assertIn("msteams://l/chat/0/0?users=", source)
        self.assertIn("encodeURIComponent(recipient)", source)
        self.assertIn("encodeURIComponent(messageBody)", source)

    def test_dashboard_default_feedback_email_is_work_email(self) -> None:
        from sg_preflight.dashboard import main as dashboard_main
        self.assertEqual(dashboard_main.DEFAULT_FEEDBACK_EMAIL, "david-erik.garcia-arenas@paradoxcat.com")


if __name__ == "__main__":
    unittest.main()
