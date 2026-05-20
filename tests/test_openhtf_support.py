from __future__ import annotations

import importlib.util
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock


class OpenHtfSupportLazyImportTests(unittest.TestCase):
    def test_cli_import_does_not_import_openhtf_support(self) -> None:
        import sg_preflight.cli as cli

        self.assertTrue(callable(cli.main))

    def test_missing_openhtf_error_has_setup_guidance(self) -> None:
        from sg_preflight.openhtf_support.dependency import OpenHtfUnavailable, require_openhtf

        with mock.patch("importlib.import_module", side_effect=ImportError("no openhtf here")):
            with self.assertRaises(OpenHtfUnavailable) as caught:
                require_openhtf()

        self.assertIn("OpenHTF", str(caught.exception))
        self.assertIn("pip install", str(caught.exception))

    def test_station_command_is_registered_without_importing_openhtf(self) -> None:
        from sg_preflight.cli import build_parser

        args = build_parser().parse_args(
            [
                "station",
                "run",
                "--profile",
                "G65",
                "--workspace",
                "C:/workspace",
                "--port",
                "0",
                "--history",
                "out/openhtf-history",
                "--no-browser",
                "--once",
            ]
        )

        self.assertEqual(args.command, "station")
        self.assertEqual(args.station_command, "run")
        self.assertEqual(args.profile, "G65")


class OpenHtfOutcomeTests(unittest.TestCase):
    def test_payload_status_maps_to_sgfx_vocab(self) -> None:
        from sg_preflight.openhtf_support.outcomes import sgfx_status_from_payload

        cases = {
            "available": "available",
            "present": "available",
            "no_workbook": "missing",
            "no_review_package": "missing",
            "unreadable": "unknown",
            "error": "unknown",
            "not_run": "not_run",
        }

        for raw_status, expected in cases.items():
            with self.subTest(raw_status=raw_status):
                self.assertEqual(sgfx_status_from_payload({"status": raw_status}), expected)

    def test_phase_result_status_never_uses_approval_words(self) -> None:
        from sg_preflight.openhtf_support.outcomes import phase_payload

        payload = phase_payload(
            phase_id="delivery_checklist_phase",
            source="delivery_checklist",
            sgfx_status="available",
            summary="Delivery checklist data was read.",
            raw_payload={"status": "available"},
        )

        rendered = str(payload).lower()
        self.assertNotIn("approved", rendered)
        self.assertNotIn("cleared", rendered)
        self.assertNotIn("signed-off", rendered)


class _FakeContext:
    profile_id = "G65"
    workspace = Path("C:/workspace")
    bmw_root = None
    ui_mode = "clean"


class _FakeWorkbookPlug:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def read_delivery_checklist(self) -> dict[str, object]:
        return dict(self.payload)


class _FakeMirrorPlug:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def read_screenshot_test_state(self) -> dict[str, object]:
        return dict(self.payload)


class _FakeDailyPlug:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def read_daily_digest(self) -> dict[str, object]:
        return dict(self.payload)


class _FakeManualPlug:
    def manual_review_companion(self) -> dict[str, object]:
        return {
            "status": "not_run",
            "data_available": False,
            "summary": "Manual review companion is pending operator input.",
            "step_count": 7,
            "is_approval": False,
        }


class OpenHtfPhaseObservationTests(unittest.TestCase):
    def test_delivery_checklist_observation_maps_available_payload(self) -> None:
        from sg_preflight.openhtf_support.phases import build_delivery_checklist_observation

        observation = build_delivery_checklist_observation(
            _FakeContext(),
            _FakeWorkbookPlug(
                {
                    "status": "available",
                    "data_available": True,
                    "summary": "Delivery checklist data was read.",
                    "is_approval": False,
                }
            ),
        )

        self.assertEqual(observation["sgfx_status"], "available")
        self.assertEqual(observation["source"], "delivery_checklist")

    def test_screenshot_state_observation_maps_missing_payload(self) -> None:
        from sg_preflight.openhtf_support.phases import build_screenshot_test_state_observation

        observation = build_screenshot_test_state_observation(
            _FakeContext(),
            _FakeMirrorPlug(
                {
                    "status": "no_expected_baselines",
                    "data_available": False,
                    "summary": "No expected baselines were found.",
                    "is_approval": False,
                }
            ),
        )

        self.assertEqual(observation["sgfx_status"], "missing")
        self.assertEqual(observation["source"], "screenshot_test_state")

    def test_daily_digest_observation_maps_no_review_package_as_missing(self) -> None:
        from sg_preflight.openhtf_support.phases import build_daily_digest_observation

        observation = build_daily_digest_observation(
            _FakeContext(),
            _FakeDailyPlug(
                {
                    "status": "no_review_package",
                    "data_available": False,
                    "summary": "No review package found.",
                    "is_approval": False,
                }
            ),
        )

        self.assertEqual(observation["sgfx_status"], "missing")
        self.assertEqual(observation["source"], "daily_digest")

    def test_manual_review_observation_stays_not_run(self) -> None:
        from sg_preflight.openhtf_support.phases import build_manual_review_companion_observation

        observation = build_manual_review_companion_observation(_FakeContext(), _FakeManualPlug())

        self.assertEqual(observation["sgfx_status"], "not_run")
        self.assertEqual(observation["source"], "manual_review_companion")
        self.assertFalse(observation["payload"]["is_approval"])


@unittest.skipUnless(importlib.util.find_spec("openhtf"), "OpenHTF is not installed")
class OpenHtfStationSmokeTests(unittest.TestCase):
    def test_make_sgfx_test_contains_four_mvp_phases(self) -> None:
        from sg_preflight.openhtf_support.station import make_sgfx_test

        test = make_sgfx_test(profile_id="G65", workspace=Path("C:/workspace"))
        phase_names = [
            phase.name
            for phase in test.descriptor.phase_sequence.all_phases()
        ]

        self.assertEqual(
            phase_names,
            [
                "delivery_checklist_phase",
                "screenshot_test_state_phase",
                "daily_digest_phase",
                "manual_review_companion_phase",
            ],
        )

    def test_station_server_serves_sgfx_title_override(self) -> None:
        from sg_preflight.openhtf_support.station import start_sgfx_station_server

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with start_sgfx_station_server(
                profile_id="G65",
                workspace=root,
                history_path=root / "history",
                port=0,
            ) as started:
                with urllib.request.urlopen(started.sgfx_url, timeout=5) as response:
                    html = response.read().decode("utf-8")

        self.assertIn("<title>SGFX QA Preflight</title>", html)
        self.assertIn("SGFX: Project Quality-Hero", html)
        self.assertIn("Manual review remains required.", html)
        self.assertIn("Decision: not approval — evidence only.", html)
