from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def _load_script():
    path = ROOT / "scripts" / "benchmark_qt_quick.py"
    spec = importlib.util.spec_from_file_location("benchmark_qt_quick_for_test", path)
    if spec is None or spec.loader is None:
        raise AssertionError("benchmark_qt_quick.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestQtQuickBenchmarkStatistics(unittest.TestCase):
    def test_navigation_routes_are_loaded_and_primed_before_measurement(self) -> None:
        from sg_preflight.desktop import qt_quick_benchmark_probe as probe

        runtime = mock.Mock()
        root = mock.Mock()
        frames = [7]
        runtime.controller.navigate.return_value = True

        with mock.patch.object(probe, "_wait_for_page", return_value=True) as waiter:
            probe._prepare_cached_routes(runtime, root, frames)

        expected_routes = list(probe._ROUTES.values()) * 2
        self.assertEqual(
            [call.args[0] for call in runtime.controller.navigate.call_args_list],
            expected_routes,
        )
        self.assertEqual(root.requestUpdate.call_count, len(expected_routes))
        self.assertEqual(waiter.call_count, len(expected_routes))
        source = (ROOT / "sg_preflight" / "desktop" / "qt_quick_benchmark_probe.py").read_text(
            encoding="utf-8"
        )
        stress_source = source[
            source.index("def _run_reader_stress") : source.index("def run_benchmark_request")
        ]
        self.assertLess(
            stress_source.index("_prepare_cached_routes(runtime, root, frames)"),
            stress_source.index('request["ready_path"].touch(exist_ok=False)'),
        )
        self.assertLess(
            stress_source.index('request["ready_path"].touch(exist_ok=False)'),
            stress_source.index("sys.setprofile(profiler)"),
        )

    def test_gui_profiler_records_desktop_callbacks_without_path_output(self) -> None:
        from sg_preflight.desktop.qt_quick_benchmark_probe import _GuiCallbackProfiler

        profiler = _GuiCallbackProfiler()
        frame = mock.Mock()
        frame.f_code.co_filename = r"C:\private\sg_preflight\desktop\qt_quick_controller.py"
        profiler(frame, "call", None)
        profiler(frame, "return", None)

        self.assertEqual(len(profiler.samples_ms), 1)
        self.assertGreaterEqual(profiler.samples_ms[0], 0)
        self.assertNotIn("private", json.dumps(profiler.samples_ms))

    def test_worker_request_rejects_output_outside_its_temp_directory(self) -> None:
        from sg_preflight.desktop.qt_quick_benchmark_probe import BenchmarkProbeError, _read_request

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            request = root / "request.json"
            request.write_text(
                json.dumps(
                    {
                        "scenario": "startup",
                        "output_path": str(root.parent / "outside.json"),
                        "workspace": str(workspace),
                        "start_ns": 1,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(BenchmarkProbeError):
                _read_request(request)

    def test_reader_stress_ready_signal_stays_inside_the_request_boundary(self) -> None:
        from sg_preflight.desktop.qt_quick_benchmark_probe import BenchmarkProbeError, _read_request

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            request = root / "request.json"
            payload = {
                "scenario": "reader-stress",
                "output_path": str(root / "result.json"),
                "workspace": str(workspace),
                "start_ns": 1,
                "ready_path": str(root / "stress-ready"),
            }
            request.write_text(json.dumps(payload), encoding="utf-8")

            parsed = _read_request(request)

            self.assertEqual(parsed["ready_path"], (root / "stress-ready").resolve())
            payload["ready_path"] = str(root.parent / "outside-ready")
            request.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(BenchmarkProbeError):
                _read_request(request)

    def test_nearest_rank_percentiles_are_deterministic(self) -> None:
        module = _load_script()
        samples = list(range(1, 21))

        self.assertEqual(module.nearest_rank_percentile(samples, 50), 10.0)
        self.assertEqual(module.nearest_rank_percentile(samples, 95), 19.0)
        with self.assertRaises(ValueError):
            module.nearest_rank_percentile([], 95)
        with self.assertRaises(ValueError):
            module.nearest_rank_percentile(samples, 0)

    def test_warm_start_requires_one_priming_and_twenty_measured_launches(self) -> None:
        module = _load_script()
        raw = {"priming_ms": 2200.0, "launch_ms": [1000.0 + index for index in range(20)]}

        evidence = module.evaluate_scenario("warm-start", raw, self._fingerprint())

        self.assertTrue(evidence["passed"])
        self.assertEqual(evidence["sample_count"], 20)
        self.assertEqual(evidence["metrics"]["p95_ms"], 1018.0)
        self.assertEqual(evidence["percentile_method"], "nearest-rank")
        self.assertEqual(evidence["failures"], [])

        for invalid in (
            {"priming_ms": None, "launch_ms": raw["launch_ms"]},
            {"priming_ms": 1.0, "launch_ms": raw["launch_ms"][:-1]},
            {"priming_ms": 1.0, "launch_ms": [3000.0] * 20},
        ):
            with self.subTest(invalid=invalid):
                self.assertFalse(module.evaluate_scenario("warm-start", invalid, self._fingerprint())["passed"])

    def test_first_run_requires_five_unique_stages_and_reports_median_maximum(self) -> None:
        module = _load_script()
        raw = {
            "launches": [
                {"stage_id": f"stage-{index}", "duration_ms": duration}
                for index, duration in enumerate((2000.0, 2500.0, 3000.0, 3500.0, 4000.0), 1)
            ]
        }

        evidence = module.evaluate_scenario("first-run", raw, self._fingerprint())

        self.assertTrue(evidence["passed"])
        self.assertEqual(evidence["metrics"]["median_ms"], 3000.0)
        self.assertEqual(evidence["metrics"]["maximum_ms"], 4000.0)
        duplicate = {"launches": [dict(item, stage_id="same") for item in raw["launches"]]}
        self.assertFalse(module.evaluate_scenario("first-run", duplicate, self._fingerprint())["passed"])

    def test_navigation_requires_twenty_acknowledged_samples_per_renderer(self) -> None:
        module = _load_script()
        renderers = {
            renderer: [
                {"feedback_ms": 50.0, "settle_ms": 200.0, "acknowledged": True}
                for _index in range(20)
            ]
            for renderer in module.RENDERER_KINDS
        }

        evidence = module.evaluate_scenario("navigation", {"renderers": renderers}, self._fingerprint())

        self.assertTrue(evidence["passed"])
        self.assertEqual(evidence["sample_count"], 120)
        self.assertTrue(all(item["feedback_p95_ms"] == 50.0 for item in evidence["metrics"].values()))
        renderers["overview"][0]["acknowledged"] = False
        failed = module.evaluate_scenario("navigation", {"renderers": renderers}, self._fingerprint())
        self.assertFalse(failed["passed"])
        self.assertTrue(any("acknowledgement" in item for item in failed["failures"]))

    def test_reader_stress_requires_exact_readers_inputs_resizes_and_callback_budget(self) -> None:
        module = _load_script()
        raw = {
            "duration_s": 60,
            "reader_count": 2,
            "cpu_target_percent": 75,
            "navigation_ack_ms": [100.0] * 30,
            "resize_ack_ms": [120.0] * 6,
            "gui_callback_ms": [1.0] * 60,
            "missing_navigation_acknowledgements": 0,
            "missing_resize_acknowledgements": 0,
        }

        evidence = module.evaluate_scenario("reader-stress", raw, self._fingerprint())

        self.assertTrue(evidence["passed"])
        self.assertEqual(evidence["metrics"]["navigation_p95_ms"], 100.0)
        self.assertEqual(evidence["metrics"]["resize_maximum_ms"], 120.0)
        self.assertEqual(evidence["metrics"]["gui_callback_p95_ms"], 1.0)
        for key, value in (
            ("reader_count", 1),
            ("cpu_target_percent", 90),
            ("navigation_ack_ms", [100.0] * 29),
            ("resize_ack_ms", [120.0] * 5),
            ("missing_navigation_acknowledgements", 1),
            ("gui_callback_ms", [5.0] * 60),
        ):
            with self.subTest(key=key):
                failed = module.evaluate_scenario("reader-stress", {**raw, key: value}, self._fingerprint())
                self.assertFalse(failed["passed"])

    def test_fingerprint_and_evidence_reject_identity_and_path_data(self) -> None:
        module = _load_script()
        clean = module.sanitize_environment_fingerprint(self._fingerprint())
        self.assertEqual(clean["bundle_commit"], "1" * 40)
        for fingerprint in (
            {**self._fingerprint(), "username": "private-user"},
            {**self._fingerprint(), "bundle_commit": r"C:\private\checkout"},
            {**self._fingerprint(), "cpu": r"Example CPU from C:\private\checkout"},
            {**self._fingerprint(), "host": "workstation-name"},
        ):
            with self.subTest(fingerprint=fingerprint):
                with self.assertRaises(ValueError):
                    module.sanitize_environment_fingerprint(fingerprint)
        with self.assertRaises(ValueError):
            module.evaluate_scenario(
                "warm-start",
                {
                    "priming_ms": 1.0,
                    "launch_ms": [1.0] * 20,
                    "operator_path": r"C:\private\operator",
                },
                self._fingerprint(),
            )

    def test_malformed_nested_samples_cannot_flow_into_failure_evidence(self) -> None:
        module = _load_script()
        unsafe = r"C:\private\operator"
        cases = (
            ("warm-start", {"priming_ms": unsafe, "launch_ms": [1.0] * 20}),
            (
                "first-run",
                {
                    "launches": [
                        {"stage_id": unsafe, "duration_ms": 1.0}
                        for _index in range(5)
                    ]
                },
            ),
            ("navigation", {"renderers": {unsafe: []}}),
            (
                "reader-stress",
                {
                    "duration_s": 60,
                    "reader_count": 2,
                    "cpu_target_percent": 75,
                    "navigation_ack_ms": [unsafe],
                    "resize_ack_ms": [1.0] * 6,
                    "gui_callback_ms": [1.0],
                    "missing_navigation_acknowledgements": 0,
                    "missing_resize_acknowledgements": 0,
                },
            ),
        )
        for scenario, raw in cases:
            with self.subTest(scenario=scenario):
                with self.assertRaises(ValueError) as captured:
                    module.evaluate_scenario(scenario, raw, self._fingerprint())
                self.assertNotIn(unsafe, str(captured.exception))

    def test_bundle_fingerprint_uses_the_measured_manifest_versions(self) -> None:
        module = _load_script()
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle = Path(temp_dir) / "bundle"
            bundle.mkdir()
            manifest = {
                "schema_version": 1,
                "source_commit": "a" * 40,
                "python_version": "3.13.12",
                "pyside6_version": "6.9.0",
                "qt_version": "6.9.0",
                "qml_contract_version": 1,
                "presentation_modes": ["clean", "qt-quick"],
                "qml_imports": [{"module": "QtQuick", "plugin": "qtquick2plugin"}],
            }
            (bundle / "bundle-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            target = module.BenchmarkTarget((str(bundle / "sgfx-preflight.exe"),), bundle, bundle)

            fingerprint = module.environment_fingerprint(target=target)

        self.assertEqual(fingerprint["bundle_commit"], "a" * 40)
        self.assertEqual(fingerprint["python_version"], "3.13.12")
        self.assertEqual(fingerprint["pyside6_version"], "6.9.0")
        self.assertEqual(fingerprint["qt_version"], "6.9.0")

    def test_default_target_rejects_an_incomplete_or_invalid_bundle(self) -> None:
        module = _load_script()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle = root / "dist" / "sgfx-preflight"
            bundle.mkdir(parents=True)
            executable = bundle / "sgfx-preflight.exe"
            executable.write_bytes(b"fixture")
            with mock.patch.object(module, "ROOT", root):
                with self.assertRaises(RuntimeError):
                    module.benchmark_target()
                (bundle / "bundle-manifest.json").write_text("{}", encoding="utf-8")
                with self.assertRaises(RuntimeError):
                    module.benchmark_target()

    def test_json_cli_uses_supplied_samples_without_dropping_failures(self) -> None:
        module = _load_script()
        raw = {"priming_ms": 1.0, "launch_ms": [3000.0] * 20}
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "samples.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            stdout = io.StringIO()
            with mock.patch.object(module, "environment_fingerprint", return_value=self._fingerprint()):
                with mock.patch("sys.stdout", stdout):
                    exit_code = module.main(
                        ["--scenario", "warm-start", "--format", "json", "--samples", str(path)]
                    )

        evidence = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertFalse(evidence["passed"])
        self.assertEqual(evidence["raw_samples"]["launch_ms"], raw["launch_ms"])
        self.assertGreater(evidence["failure_count"], 0)

    def test_live_warm_collection_runs_one_priming_plus_twenty_measured_workers(self) -> None:
        module = _load_script()
        target = module.BenchmarkTarget(("bundle.exe",), Path("bundle"), Path("bundle"))
        calls: list[dict[str, object]] = []

        def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            request_path = Path(kwargs["env"][module.BENCHMARK_REQUEST_ENV])
            request = json.loads(request_path.read_text(encoding="utf-8"))
            output_path = Path(request["output_path"])
            output_path.write_text(
                json.dumps({"duration_ms": 1000.0 + len(calls), "acknowledged": True}),
                encoding="utf-8",
            )
            calls.append({"command": command, "kwargs": kwargs, "request": request})
            return subprocess.CompletedProcess(command, 0)

        raw = module.collect_scenario("warm-start", target=target, runner=run)

        self.assertEqual(raw["priming_ms"], 1000.0)
        self.assertEqual(len(raw["launch_ms"]), 20)
        self.assertEqual(len(calls), 21)
        self.assertTrue(all(item["command"] == ["bundle.exe"] for item in calls))
        for item in calls:
            environment = item["kwargs"]["env"]
            for key in ("QML2_IMPORT_PATH", "QML_IMPORT_PATH", "QT_PLUGIN_PATH", "PYTHONPATH"):
                self.assertNotIn(key, environment)
            self.assertEqual(item["request"]["scenario"], "startup")

    def test_reader_stress_envelope_covers_preparation_and_sixty_second_run(self) -> None:
        module = _load_script()
        target = module.BenchmarkTarget(("bundle.exe",), Path("bundle"), Path("bundle"))
        timeouts: list[int] = []
        requests: list[dict[str, object]] = []

        def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            request_path = Path(kwargs["env"][module.BENCHMARK_REQUEST_ENV])
            request = json.loads(request_path.read_text(encoding="utf-8"))
            Path(request["output_path"]).write_text(
                json.dumps({"acknowledged": True, "raw_samples": {}}),
                encoding="utf-8",
            )
            timeouts.append(kwargs["timeout"])
            requests.append(request)
            return subprocess.CompletedProcess(command, 0)

        process = mock.Mock()
        with mock.patch.object(module, "_start_cpu_load", return_value=[process]) as start_load:
            with mock.patch.object(module, "_stop_cpu_load") as stop_load:
                result = module._run_benchmark_worker("reader-stress", target=target, runner=run)

        self.assertTrue(result["acknowledged"])
        self.assertEqual(timeouts, [150])
        ready_path = Path(requests[0]["ready_path"])
        start_load.assert_called_once_with(ready_path)
        stop_load.assert_called_once_with([process])
        with tempfile.TemporaryDirectory() as temp_dir:
            ready_path = Path(temp_dir) / "stress-ready"
            with mock.patch.object(module.os, "cpu_count", return_value=1):
                with mock.patch.object(module.subprocess, "Popen", return_value=process) as popen:
                    workers = module._start_cpu_load(ready_path)
        self.assertEqual(workers, [process])
        workload = popen.call_args.args[0][3]
        self.assertIn("while not ready.is_file()", workload)
        self.assertIn("deadline=time.perf_counter()+75", workload)
        self.assertEqual(
            popen.call_args.kwargs["env"][module.READER_STRESS_READY_ENV],
            str(ready_path.resolve()),
        )

    def test_live_first_run_uses_five_unique_staged_bundle_directories(self) -> None:
        module = _load_script()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle = root / "bundle"
            executable = bundle / "sgfx-preflight.exe"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"fixture")
            target = module.BenchmarkTarget((str(executable),), bundle, bundle)
            commands: list[list[str]] = []

            def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                request_path = Path(kwargs["env"][module.BENCHMARK_REQUEST_ENV])
                request = json.loads(request_path.read_text(encoding="utf-8"))
                Path(request["output_path"]).write_text(
                    json.dumps({"duration_ms": 2000.0, "acknowledged": True}),
                    encoding="utf-8",
                )
                commands.append(command)
                return subprocess.CompletedProcess(command, 0)

            raw = module.collect_scenario("first-run", target=target, runner=run)

        self.assertEqual(len(raw["launches"]), 5)
        self.assertEqual(len({item["stage_id"] for item in raw["launches"]}), 5)
        self.assertEqual(len(commands), 5)
        self.assertEqual(len({str(Path(command[0]).parent) for command in commands}), 5)

    def test_real_source_worker_acknowledges_first_frame_without_workspace_writes(self) -> None:
        module = _load_script()
        target = module.BenchmarkTarget(
            (sys.executable, "-B", "-m", "sg_preflight.exe_entry"),
            ROOT,
            None,
        )
        with mock.patch.dict(
            os.environ,
            {"QT_QPA_PLATFORM": "offscreen", "QSG_RHI_BACKEND": "software"},
        ):
            result = module._run_benchmark_worker("startup", target=target)

        self.assertTrue(result["acknowledged"])
        self.assertGreater(result["duration_ms"], 0)

    @staticmethod
    def _fingerprint() -> dict[str, object]:
        return {
            "os": "Windows 11 10.0.26100",
            "cpu": "Example CPU",
            "logical_cores": 16,
            "ram_bytes": 32 * 1024**3,
            "power_mode": "best-performance",
            "display": "1920x1080@100%",
            "python_version": "3.13.13",
            "pyside6_version": "6.9.1",
            "qt_version": "6.9.1",
            "bundle_commit": "1" * 40,
            "stress": "none",
        }


if __name__ == "__main__":
    unittest.main()
