from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sg_preflight.daily_snapshot import (
    BmwBatteryResult,
    BmwConfigCheckResult,
    BmwSmokeResult,
    _battery_verdict,
    _beam_family_diagnostics,
    _review_priority_level,
    _review_priority_payload,
    _review_priority_score,
    _render_local_battery_override_lua,
    _render_local_call_screenshot_override_lua,
    _snapshot_result_from_dict,
    _write_battery_script,
    ensure_idcevo_bmw_support_files,
    materialize_daily_qa_snapshot,
)
from tests.operator_helpers import write_text


class TestDailySnapshot(unittest.TestCase):
    def test_review_priority_scoring_weights_cone_runtime_above_exact_candidate(self) -> None:
        cone_crash = BmwBatteryResult(
            profile_id="NA8",
            bmw_profile_id="NA8_EVO",
            filter_name="lights_OnlyCones",
            verdict="runtime_crash",
            status="failed",
            results_root="out/cones",
            log_path="out/cones.log",
            actual_count=1,
            target_output_present=True,
        )
        default_candidate = BmwBatteryResult(
            profile_id="NA8",
            bmw_profile_id="NA8_EVO",
            filter_name="default",
            verdict="baseline_candidate_ready",
            status="completed",
            results_root="out/default",
            log_path="out/default.log",
            actual_count=1,
            target_output_present=True,
        )

        self.assertGreater(_review_priority_score(cone_crash), _review_priority_score(default_candidate))
        self.assertEqual(_review_priority_level(cone_crash), "P0")

        payload = _review_priority_payload(
            _snapshot_result_from_dict(
                {
                    "created_at": "2026-04-23T08:00:00",
                    "scope_profiles": ["NA8"],
                    "bmw_repo_root": "C:/repo/digital-3d-car-models",
                    "config_check": {
                        "status": "ready",
                        "python_exe": "python.exe",
                        "repo_root": "C:/repo/digital-3d-car-models",
                        "log_path": "out/config.log",
                    },
                    "smoke_results": [],
                    "battery_results": [default_candidate.to_dict(), cone_crash.to_dict()],
                    "blocked_steps": [],
                    "top_review_items": [],
                    "notes": [],
                }
            )
        )

        self.assertEqual(payload["ranked_items"][0]["filter_name"], "lights_OnlyCones")
        self.assertIn("runtime crash", payload["ranked_items"][0]["signals"])
        self.assertIn("cone family", payload["ranked_items"][0]["signals"])

    def test_ensure_idcevo_bmw_support_files_copies_generic_bmw_support_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            trunk_root = root / "repositories" / "trunk"
            source_root = root / "repositories" / "trunk" / "Cars" / "BMW"
            target_root = root / "repositories" / "trunk" / "Cars_IDCevo" / "BMW"

            write_text(source_root / "CarPaint.json", "{}\n")
            write_text(source_root / "perspectives_CID_2to1.json", "{}\n")
            write_text(source_root / "perspectives_CID_3to1.json", "{}\n")
            write_text(source_root / "perspectives_IC_mid.json", "{}\n")
            write_text(source_root / "perspectives_IC_high.json", "{}\n")

            with mock.patch("sg_preflight.daily_snapshot._resolve_svn_trunk_root", return_value=trunk_root):
                copied, notes = ensure_idcevo_bmw_support_files(root)

            self.assertEqual(len(copied), 5)
            self.assertTrue((target_root / "CarPaint.json").exists())
            self.assertTrue(any("Prepared local BMW support file" in note for note in notes))

    def test_materialize_daily_qa_snapshot_writes_markdown_and_json_without_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            trunk_root = root / "repositories" / "trunk"
            repo_root = root / "digital-3d-car-models"
            output_root = root / "out" / "daily-snapshot"
            source_root = root / "repositories" / "trunk" / "Cars" / "BMW"

            write_text(repo_root / "ci" / "scripts" / "README.md", "fixture\n")
            write_text(repo_root / "ci" / "scripts" / "car_manager.py", "print('fixture')\n")
            write_text(source_root / "CarPaint.json", "{}\n")
            write_text(source_root / "perspectives_CID_2to1.json", "{}\n")
            write_text(source_root / "perspectives_CID_3to1.json", "{}\n")
            write_text(source_root / "perspectives_IC_mid.json", "{}\n")
            write_text(source_root / "perspectives_IC_high.json", "{}\n")

            fake_config = BmwConfigCheckResult(
                status="ready",
                python_exe="python.exe",
                repo_root=str(repo_root),
                log_path=str(output_root / "bmw-configurations.log"),
                output_excerpt="fixture configuration output",
                error="",
            )

            with mock.patch("sg_preflight.daily_snapshot._resolve_svn_trunk_root", return_value=trunk_root):
                with mock.patch("sg_preflight.daily_snapshot._run_bmw_configuration_check", return_value=fake_config):
                    result = materialize_daily_qa_snapshot(
                        workspace_root=root,
                        output_root=output_root,
                        profile_ids=("NA8", "G78", "G50"),
                        run_smoke=False,
                    )

            self.assertTrue(result.markdown_path.exists())
            self.assertTrue(result.json_path.exists())
            self.assertTrue(result.delta_summary_markdown_path is not None)
            self.assertTrue(result.delta_summary_json_path is not None)
            self.assertTrue(result.delta_summary_markdown_path.exists())
            self.assertTrue(result.delta_summary_json_path.exists())
            self.assertIsNone(result.review_priority_markdown_path)
            self.assertIsNone(result.review_priority_json_path)
            self.assertEqual(result.snapshot.config_check.status, "ready")
            self.assertEqual(result.snapshot.scope_profiles, ("NA8", "G78", "G50"))

            markdown = result.markdown_path.read_text(encoding="utf-8")
            delta_markdown = result.delta_summary_markdown_path.read_text(encoding="utf-8")
            self.assertIn("Daily 3D Car QA Summary", markdown)
            self.assertIn("Scope: `NA8, G78, G50`", markdown)
            self.assertIn("fixture configuration output", markdown)
            self.assertIn("Daily QA Delta Summary", delta_markdown)
            self.assertIn("Previous run: `none`", delta_markdown)

    def test_materialize_daily_qa_snapshot_writes_battery_baseline_gap_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            trunk_root = root / "repositories" / "trunk"
            repo_root = root / "digital-3d-car-models"
            output_root = root / "out" / "daily-snapshot"
            source_root = root / "repositories" / "trunk" / "Cars" / "BMW"

            write_text(repo_root / "ci" / "scripts" / "README.md", "fixture\n")
            write_text(repo_root / "ci" / "scripts" / "car_manager.py", "print('fixture')\n")
            write_text(source_root / "CarPaint.json", "{}\n")
            write_text(source_root / "perspectives_CID_2to1.json", "{}\n")
            write_text(source_root / "perspectives_CID_3to1.json", "{}\n")
            write_text(source_root / "perspectives_IC_mid.json", "{}\n")
            write_text(source_root / "perspectives_IC_high.json", "{}\n")

            fake_config = BmwConfigCheckResult(
                status="ready",
                python_exe="python.exe",
                repo_root=str(repo_root),
                log_path=str(output_root / "bmw-configurations.log"),
                output_excerpt="fixture configuration output",
                error="",
            )
            fake_smoke = BmwSmokeResult(
                profile_id="NA8",
                bmw_profile_id="NA8_EVO",
                status="completed",
                smoke_test="openAllDoors_rightView",
                python_exe="python.exe",
                sg_project_root=str(trunk_root / "Cars_IDCevo" / "BMW" / "NA8"),
                bmw_test_config_path=str(repo_root / "cars" / "BMW" / "NA8_EVO" / "export" / "tests" / "test_config_tmp.lua"),
                log_path=str(output_root / "na8-bmw-smoke.log"),
                exported_ramses_size=123,
                exported_rlogic_size=0,
                expected_count=1,
                actual_count=1,
                diff_count=0,
                compare_ok=True,
                notes=("fixture smoke",),
            )
            fake_battery = (
                BmwBatteryResult(
                    profile_id="NA8",
                    bmw_profile_id="NA8_EVO",
                    filter_name="highlighting_Doors",
                    verdict="scenario_output_missing",
                    status="completed",
                    results_root=str(output_root / "na8" / "battery" / "highlighting_doors"),
                    log_path=str(output_root / "na8-bmw-battery.log"),
                    expected_count=0,
                    actual_count=2,
                    diff_count=0,
                    compare_ok=False,
                    error="Expected screenshot missing: C:/repositories/trunk/Cars_IDCevo/BMW/NA8/export/tests/expected/highlighting_Doors.png",
                    missing_expected_baseline="highlighting_Doors.png",
                    actual_files=("openAllDoors_rightView.png", "trunk_PreciseAngle_TrunkClosed.png"),
                    target_output_present=False,
                    notes=("fixture battery",),
                ),
            )

            with mock.patch("sg_preflight.daily_snapshot._resolve_svn_trunk_root", return_value=trunk_root):
                with mock.patch("sg_preflight.daily_snapshot._run_bmw_configuration_check", return_value=fake_config):
                    with mock.patch("sg_preflight.daily_snapshot._run_profile_smoke", return_value=fake_smoke):
                        with mock.patch("sg_preflight.daily_snapshot._run_profile_battery", return_value=fake_battery):
                            result = materialize_daily_qa_snapshot(
                                workspace_root=root,
                                output_root=output_root,
                                profile_ids=("NA8",),
                                run_smoke=True,
                                battery_filters=("highlighting_Doors",),
                            )

            self.assertIsNotNone(result.battery_baseline_gaps_markdown_path)
            self.assertIsNotNone(result.battery_baseline_gaps_json_path)
            self.assertIsNotNone(result.review_priority_markdown_path)
            self.assertIsNotNone(result.review_priority_json_path)
            self.assertIsNotNone(result.delta_summary_markdown_path)
            self.assertIsNotNone(result.delta_summary_json_path)
            self.assertTrue(result.battery_baseline_gaps_markdown_path.exists())
            self.assertTrue(result.battery_baseline_gaps_json_path.exists())
            self.assertTrue(result.review_priority_markdown_path.exists())
            self.assertTrue(result.review_priority_json_path.exists())
            self.assertTrue(result.delta_summary_markdown_path.exists())
            self.assertTrue(result.delta_summary_json_path.exists())

            markdown = result.battery_baseline_gaps_markdown_path.read_text(encoding="utf-8")
            payload = result.battery_baseline_gaps_json_path.read_text(encoding="utf-8")
            priority_markdown = result.review_priority_markdown_path.read_text(encoding="utf-8")
            delta_markdown = result.delta_summary_markdown_path.read_text(encoding="utf-8")

            self.assertIn("highlighting_Doors", markdown)
            self.assertIn("highlighting_Doors.png", markdown)
            self.assertIn("config/output mismatch", markdown)
            self.assertIn("openAllDoors_rightView.png", markdown)
            self.assertIn("highlighting_Doors.png", payload)
            self.assertIn("scenario_output_missing", payload)
            self.assertIn("Screenshot Review Priority Ranking", priority_markdown)
            self.assertIn("`highlighting_Doors`", priority_markdown)
            self.assertIn("Daily QA Delta Summary", delta_markdown)
            self.assertIn("NA8: `highlighting_Doors` did not generate the requested scenario output", delta_markdown)

    def test_snapshot_result_from_dict_roundtrips_battery_results(self) -> None:
        payload = {
            "created_at": "2026-04-21T18:00:00",
            "scope_profiles": ["NA8"],
            "bmw_repo_root": "C:/repo/digital-3d-car-models",
            "config_check": {
                "status": "ready",
                "python_exe": "python.exe",
                "repo_root": "C:/repo/digital-3d-car-models",
                "log_path": "out/config.log",
            },
            "smoke_results": [],
            "battery_results": [
                {
                    "profile_id": "NA8",
                    "bmw_profile_id": "NA8_EVO",
                    "filter_name": "lights_LowBeam",
                    "verdict": "baseline_candidate_ready",
                    "status": "completed",
                    "results_root": "out/na8/battery/lights_lowbeam",
                    "log_path": "out/na8.log",
                    "expected_count": 2,
                    "actual_count": 2,
                    "diff_count": 0,
                    "compare_ok": True,
                    "missing_expected_baseline": "lights_LowBeam.png",
                    "actual_files": ["lights_LowBeam.png", "openAllDoors_rightView.png"],
                    "expected_files": [],
                    "diff_files": [],
                    "target_output_present": True,
                    "notes": ["fixture"],
                }
            ],
            "blocked_steps": [],
            "top_review_items": [],
            "notes": [],
        }

        snapshot = _snapshot_result_from_dict(payload)

        self.assertEqual(snapshot.scope_profiles, ("NA8",))
        self.assertEqual(len(snapshot.battery_results), 1)
        self.assertEqual(snapshot.battery_results[0].filter_name, "lights_LowBeam")
        self.assertEqual(snapshot.battery_results[0].verdict, "baseline_candidate_ready")
        self.assertTrue(snapshot.battery_results[0].target_output_present)
        self.assertIn("lights_LowBeam.png", snapshot.battery_results[0].actual_files)

    def test_battery_verdict_distinguishes_output_mismatch_from_baseline_candidate(self) -> None:
        mismatch = _battery_verdict(
            expected_count=2,
            actual_count=2,
            diff_count=0,
            compare_ok=False,
            status="failed",
            missing_expected_baseline="highlighting_Doors.png",
            target_output_present=False,
            error="missing expected",
        )
        ready = _battery_verdict(
            expected_count=2,
            actual_count=2,
            diff_count=0,
            compare_ok=False,
            status="failed",
            missing_expected_baseline="lights_LowBeam.png",
            target_output_present=True,
            error="missing expected",
        )

        self.assertEqual(mismatch, "scenario_output_missing")
        self.assertEqual(ready, "baseline_candidate_ready")

    def test_battery_verdict_marks_proxy_candidate_ready(self) -> None:
        proxy = _battery_verdict(
            expected_count=2,
            actual_count=0,
            diff_count=0,
            compare_ok=False,
            status="proxy_completed",
            missing_expected_baseline="",
            target_output_present=False,
            error="Viewer exited with code 3221226356 while executing lights_LowBeam",
            proxy_files=("lights_LowBeam.png",),
        )

        self.assertEqual(proxy, "proxy_candidate_ready")

    def test_render_local_battery_override_lua_adds_beam_wait_workaround(self) -> None:
        rendered = _render_local_battery_override_lua(("lights_LowBeam", "lights_HighBeam", "lights_OnlyCones"))

        self.assertIn('testViews["lights_LowBeam"].update', rendered)
        self.assertIn('testViews["lights_HighBeam"].update', rendered)
        self.assertIn('testViews["lights_OnlyCones"].update', rendered)
        self.assertIn("waitOnRendering(1000)", rendered)

    def test_render_local_call_screenshot_override_lua_instruments_viewer_execution(self) -> None:
        rendered = _render_local_call_screenshot_override_lua(("lights_LowBeam",))

        self.assertIn("function callSingleScreenshotTest(name, path)", rendered)
        self.assertIn("function callScreenshotTests(path)", rendered)
        self.assertIn("SGPREFLIGHT_LUA_TEST_STATUS=", rendered)
        self.assertIn("SGPREFLIGHT_LUA_SCREENSHOT_STATUS=", rendered)
        self.assertIn("waitOnRendering(1000)", rendered)
        self.assertIn("R.screenshot(screenshotPath)", rendered)

    def test_write_battery_script_injects_local_screenshot_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            script_path = root / "battery.py"

            _write_battery_script(
                script_path,
                profile_id="NA8",
                sg_project_root=root / "Cars_IDCevo" / "BMW" / "NA8",
                bmw_test_config_path=root / "digital-3d-car-models" / "cars" / "BMW" / "NA8_EVO" / "export" / "tests" / "test_config_tmp.lua",
                filters=("lights_LowBeam", "lights_HighBeam"),
                results_root=root / "out" / "battery",
            )

            rendered = script_path.read_text(encoding="utf-8")

            self.assertIn("LOCAL_TEST_OVERRIDE_LUA", rendered)
            self.assertIn("LOCAL_SCREENSHOT_OVERRIDE_LUA", rendered)
            self.assertIn("PROXY_SCREENSHOT_TEMPLATES", rendered)
            self.assertIn("SGPREFLIGHT_LUA_TEST_STATUS=", rendered)
            self.assertIn("SGPREFLIGHT_LUA_SCREENSHOT_STATUS=", rendered)
            self.assertIn('.enabled = true', rendered)
            self.assertIn("callSingleScreenshotTest(", rendered)
            self.assertIn("proxy_direct_exec_lua", rendered)

    def test_beam_family_diagnostics_detect_control_ok_but_beams_missing(self) -> None:
        items = (
            BmwBatteryResult(
                profile_id="NA8",
                bmw_profile_id="NA8_EVO",
                filter_name="lights_drl_front",
                verdict="baseline_candidate_ready",
                status="completed",
                results_root="out/na8/battery/lights_drl_front",
                log_path="out/na8.log",
                actual_count=1,
                target_output_present=True,
            ),
            BmwBatteryResult(
                profile_id="NA8",
                bmw_profile_id="NA8_EVO",
                filter_name="lights_LowBeam",
                verdict="blocked",
                status="completed",
                results_root="out/na8/battery/lights_lowbeam",
                log_path="out/na8.log",
                missing_expected_baseline="lights_LowBeam.png",
            ),
            BmwBatteryResult(
                profile_id="NA8",
                bmw_profile_id="NA8_EVO",
                filter_name="lights_HighBeam",
                verdict="blocked",
                status="completed",
                results_root="out/na8/battery/lights_highbeam",
                log_path="out/na8.log",
                missing_expected_baseline="lights_HighBeam.png",
            ),
        )

        diagnostics = _beam_family_diagnostics(items)

        self.assertEqual(len(diagnostics), 1)
        self.assertIn("control `lights_drl_front` generated screenshot payload", diagnostics[0])
        self.assertIn("`lights_LowBeam`", diagnostics[0])
        self.assertIn("`lights_HighBeam`", diagnostics[0])


if __name__ == "__main__":
    unittest.main()
