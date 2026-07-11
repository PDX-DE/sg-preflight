from __future__ import annotations

import argparse
import ctypes
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_REQUEST_ENV = "SGFX_QT_BENCHMARK_REQUEST"
RENDERER_KINDS = ("overview", "matrix", "evidence", "workflow", "review", "about")
SCENARIOS = ("warm-start", "first-run", "navigation", "reader-stress")
_FINGERPRINT_KEYS = frozenset(
    {
        "os",
        "cpu",
        "logical_cores",
        "ram_bytes",
        "power_mode",
        "display",
        "python_version",
        "pyside6_version",
        "qt_version",
        "bundle_commit",
        "stress",
    }
)
_FORBIDDEN_FINGERPRINT_KEY_PARTS = ("user", "host", "path", "credential", "telemetry")
_COMMIT_PATTERN = re.compile(r"^[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?$")
_STAGE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+_-]{0,63}$")


@dataclass(frozen=True, slots=True)
class BenchmarkTarget:
    command: tuple[str, ...]
    working_directory: Path
    bundle_directory: Path | None


def nearest_rank_percentile(samples: Sequence[float], percentile: float) -> float:
    if not samples:
        raise ValueError("At least one sample is required.")
    if not 0 < percentile <= 100:
        raise ValueError("Percentile must be in the range (0, 100].")
    ordered = sorted(float(value) for value in samples)
    rank = math.ceil((percentile / 100) * len(ordered))
    return ordered[rank - 1]


def _duration_samples(value: object, *, required_count: int | None = None) -> list[float] | None:
    if not isinstance(value, list):
        return None
    samples: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return None
        sample = float(item)
        if not math.isfinite(sample) or sample < 0:
            return None
        samples.append(sample)
    if required_count is not None and len(samples) != required_count:
        return None
    return samples


def _safe_fingerprint_string(value: str) -> bool:
    if not value or any(character in value for character in ("\r", "\n", "\x00")):
        return False
    if "/" in value or "\\" in value or re.search(r"[A-Za-z]:[\\/]", value):
        return False
    return len(value) <= 256


def sanitize_environment_fingerprint(fingerprint: Mapping[str, object]) -> dict[str, object]:
    if set(fingerprint) != _FINGERPRINT_KEYS:
        raise ValueError("The environment fingerprint fields are invalid.")
    for key in fingerprint:
        folded = key.casefold()
        if any(part in folded for part in _FORBIDDEN_FINGERPRINT_KEY_PARTS):
            raise ValueError("The environment fingerprint contains identity data.")
    normalized: dict[str, object] = {}
    for key in sorted(_FINGERPRINT_KEYS):
        value = fingerprint[key]
        if isinstance(value, str):
            if not _safe_fingerprint_string(value):
                raise ValueError("The environment fingerprint contains path or control data.")
            normalized[key] = value
        elif type(value) is int and value >= 0:
            normalized[key] = value
        else:
            raise ValueError("The environment fingerprint value is invalid.")
    commit = normalized["bundle_commit"]
    if not isinstance(commit, str) or _COMMIT_PATTERN.fullmatch(commit) is None:
        raise ValueError("The bundle commit is invalid.")
    return normalized


def _base_evidence(
    scenario: str,
    raw_samples: Mapping[str, object],
    fingerprint: Mapping[str, object],
) -> dict[str, Any]:
    return {
        "scenario": scenario,
        "percentile_method": "nearest-rank",
        "environment": sanitize_environment_fingerprint(fingerprint),
        "raw_samples": json.loads(json.dumps(raw_samples, allow_nan=False)),
        "sample_count": 0,
        "metrics": {},
        "failures": [],
        "failure_count": 0,
        "passed": False,
    }


def _safe_timing_scalar(value: object) -> bool:
    if value is None or isinstance(value, bool):
        return True
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def _safe_timing_sequence(value: object) -> bool:
    return value is None or (
        isinstance(value, list)
        and all(_safe_timing_scalar(item) for item in value)
    )


def _validate_raw_schema(scenario: str, raw: Mapping[str, object]) -> None:
    if scenario == "warm-start":
        if set(raw) != {"priming_ms", "launch_ms"}:
            raise ValueError("Warm-start sample fields are invalid.")
        if not _safe_timing_scalar(raw.get("priming_ms")) or not _safe_timing_sequence(
            raw.get("launch_ms")
        ):
            raise ValueError("Warm-start sample fields are invalid.")
        return
    if scenario == "first-run":
        if set(raw) != {"launches"} or not isinstance(raw.get("launches"), list):
            raise ValueError("First-run sample fields are invalid.")
        for item in raw["launches"]:
            if not isinstance(item, Mapping) or set(item) != {"stage_id", "duration_ms"}:
                raise ValueError("First-run sample fields are invalid.")
            stage_id = item.get("stage_id")
            if (
                not isinstance(stage_id, str)
                or _STAGE_PATTERN.fullmatch(stage_id) is None
                or not _safe_timing_scalar(item.get("duration_ms"))
            ):
                raise ValueError("First-run sample fields are invalid.")
        return
    if scenario == "navigation":
        if set(raw) != {"renderers"} or not isinstance(raw.get("renderers"), Mapping):
            raise ValueError("Navigation sample fields are invalid.")
        if not set(raw["renderers"]).issubset(RENDERER_KINDS):
            raise ValueError("Navigation sample fields are invalid.")
        for samples in raw["renderers"].values():
            if not isinstance(samples, list):
                raise ValueError("Navigation sample fields are invalid.")
            for item in samples:
                acknowledged = item.get("acknowledged") if isinstance(item, Mapping) else None
                if (
                    not isinstance(item, Mapping)
                    or set(item) != {"feedback_ms", "settle_ms", "acknowledged"}
                    or not _safe_timing_scalar(item.get("feedback_ms"))
                    or not _safe_timing_scalar(item.get("settle_ms"))
                    or (
                        acknowledged is not True
                        and acknowledged is not False
                        and acknowledged is not None
                    )
                ):
                    raise ValueError("Navigation sample fields are invalid.")
        return
    expected = {
        "duration_s",
        "reader_count",
        "cpu_target_percent",
        "navigation_ack_ms",
        "resize_ack_ms",
        "gui_callback_ms",
        "missing_navigation_acknowledgements",
        "missing_resize_acknowledgements",
    }
    if set(raw) != expected:
        raise ValueError("Reader-stress sample fields are invalid.")
    scalar_fields = (
        "duration_s",
        "reader_count",
        "cpu_target_percent",
        "missing_navigation_acknowledgements",
        "missing_resize_acknowledgements",
    )
    sequence_fields = ("navigation_ack_ms", "resize_ack_ms", "gui_callback_ms")
    if any(not _safe_timing_scalar(raw.get(key)) for key in scalar_fields) or any(
        not _safe_timing_sequence(raw.get(key)) for key in sequence_fields
    ):
        raise ValueError("Reader-stress sample fields are invalid.")


def _evaluate_warm_start(evidence: dict[str, Any], raw: Mapping[str, object]) -> None:
    failures: list[str] = evidence["failures"]
    priming = raw.get("priming_ms")
    if isinstance(priming, bool) or not isinstance(priming, (int, float)) or float(priming) < 0:
        failures.append("Exactly one successful priming launch is required.")
    samples = _duration_samples(raw.get("launch_ms"), required_count=20)
    if samples is None:
        failures.append("Exactly 20 measured warm launches are required.")
        return
    evidence["sample_count"] = len(samples)
    evidence["metrics"] = {
        "p50_ms": nearest_rank_percentile(samples, 50),
        "p95_ms": nearest_rank_percentile(samples, 95),
        "maximum_ms": max(samples),
    }
    if evidence["metrics"]["p95_ms"] > 2500:
        failures.append("Warm-start p95 exceeds 2500 ms.")


def _evaluate_first_run(evidence: dict[str, Any], raw: Mapping[str, object]) -> None:
    failures: list[str] = evidence["failures"]
    launches = raw.get("launches")
    if not isinstance(launches, list) or len(launches) != 5:
        failures.append("Exactly five first-run launches are required.")
        return
    stage_ids: set[str] = set()
    samples: list[float] = []
    for launch in launches:
        if not isinstance(launch, Mapping):
            failures.append("First-run launch data is invalid.")
            return
        stage_id = launch.get("stage_id")
        duration = launch.get("duration_ms")
        if not isinstance(stage_id, str) or _STAGE_PATTERN.fullmatch(stage_id) is None:
            failures.append("First-run stage identifiers are invalid.")
            return
        parsed = _duration_samples([duration], required_count=1)
        if parsed is None:
            failures.append("First-run durations are invalid.")
            return
        stage_ids.add(stage_id)
        samples.extend(parsed)
    if len(stage_ids) != 5:
        failures.append("Five unique staged directories are required.")
    evidence["sample_count"] = len(samples)
    evidence["metrics"] = {
        "median_ms": float(statistics.median(samples)),
        "maximum_ms": max(samples),
    }
    if evidence["metrics"]["median_ms"] > 4000:
        failures.append("First-run median exceeds 4000 ms.")
    if evidence["metrics"]["maximum_ms"] > 5000:
        failures.append("First-run maximum exceeds 5000 ms.")


def _evaluate_navigation(evidence: dict[str, Any], raw: Mapping[str, object]) -> None:
    failures: list[str] = evidence["failures"]
    renderers = raw.get("renderers")
    if not isinstance(renderers, Mapping) or set(renderers) != set(RENDERER_KINDS):
        failures.append("All six renderer kinds are required.")
        return
    metrics: dict[str, dict[str, float]] = {}
    sample_count = 0
    for renderer in RENDERER_KINDS:
        samples = renderers.get(renderer)
        if not isinstance(samples, list) or len(samples) < 20:
            failures.append(f"Renderer {renderer} requires at least 20 samples.")
            continue
        feedback: list[float] = []
        settle: list[float] = []
        for sample in samples:
            if not isinstance(sample, Mapping) or sample.get("acknowledged") is not True:
                failures.append(f"Renderer {renderer} has a missing acknowledgement.")
                continue
            parsed_feedback = _duration_samples([sample.get("feedback_ms")], required_count=1)
            parsed_settle = _duration_samples([sample.get("settle_ms")], required_count=1)
            if parsed_feedback is None or parsed_settle is None:
                failures.append(f"Renderer {renderer} has invalid timing data.")
                continue
            feedback.extend(parsed_feedback)
            settle.extend(parsed_settle)
        sample_count += len(samples)
        if len(feedback) != len(samples) or len(settle) != len(samples):
            continue
        metrics[renderer] = {
            "feedback_p95_ms": nearest_rank_percentile(feedback, 95),
            "settle_p95_ms": nearest_rank_percentile(settle, 95),
        }
        if metrics[renderer]["feedback_p95_ms"] > 100:
            failures.append(f"Renderer {renderer} feedback p95 exceeds 100 ms.")
        if metrics[renderer]["settle_p95_ms"] > 333:
            failures.append(f"Renderer {renderer} settle p95 exceeds 333 ms.")
    evidence["sample_count"] = sample_count
    evidence["metrics"] = metrics


def _evaluate_reader_stress(evidence: dict[str, Any], raw: Mapping[str, object]) -> None:
    failures: list[str] = evidence["failures"]
    if raw.get("duration_s") != 60:
        failures.append("Reader stress must run for 60 seconds.")
    if raw.get("reader_count") != 2:
        failures.append("Reader stress requires two delayed readers.")
    cpu_target = raw.get("cpu_target_percent")
    if isinstance(cpu_target, bool) or not isinstance(cpu_target, (int, float)) or not 70 <= cpu_target <= 80:
        failures.append("Reader stress CPU target must stay between 70 and 80 percent.")
    navigation = _duration_samples(raw.get("navigation_ack_ms"), required_count=30)
    resize = _duration_samples(raw.get("resize_ack_ms"), required_count=6)
    callbacks = _duration_samples(raw.get("gui_callback_ms"))
    if navigation is None:
        failures.append("Reader stress requires 30 navigation acknowledgements.")
    if resize is None:
        failures.append("Reader stress requires six resize acknowledgements.")
    if callbacks is None or not callbacks:
        failures.append("Reader stress requires GUI callback timing samples.")
    if raw.get("missing_navigation_acknowledgements") != 0:
        failures.append("Reader stress has missing navigation acknowledgements.")
    if raw.get("missing_resize_acknowledgements") != 0:
        failures.append("Reader stress has missing resize acknowledgements.")
    if navigation is None or resize is None or callbacks is None or not callbacks:
        return
    evidence["sample_count"] = len(navigation)
    evidence["metrics"] = {
        "navigation_p95_ms": nearest_rank_percentile(navigation, 95),
        "resize_maximum_ms": max(resize),
        "gui_callback_p95_ms": nearest_rank_percentile(callbacks, 95),
    }
    if evidence["metrics"]["navigation_p95_ms"] > 250:
        failures.append("Reader-stress navigation p95 exceeds 250 ms.")
    if evidence["metrics"]["resize_maximum_ms"] > 250:
        failures.append("Reader-stress resize acknowledgement exceeds 250 ms.")
    if evidence["metrics"]["gui_callback_p95_ms"] >= 4:
        failures.append("GUI callback p95 must remain below 4 ms.")


def evaluate_scenario(
    scenario: str,
    raw_samples: Mapping[str, object],
    fingerprint: Mapping[str, object],
) -> dict[str, Any]:
    if scenario not in SCENARIOS:
        raise ValueError("Unknown benchmark scenario.")
    if not isinstance(raw_samples, Mapping):
        raise ValueError("Benchmark samples must be a mapping.")
    _validate_raw_schema(scenario, raw_samples)
    evidence = _base_evidence(scenario, raw_samples, fingerprint)
    evaluators = {
        "warm-start": _evaluate_warm_start,
        "first-run": _evaluate_first_run,
        "navigation": _evaluate_navigation,
        "reader-stress": _evaluate_reader_stress,
    }
    evaluators[scenario](evidence, raw_samples)
    evidence["failure_count"] = len(evidence["failures"])
    evidence["passed"] = evidence["failure_count"] == 0
    return evidence


def _ram_bytes() -> int:
    if sys.platform == "win32":
        class MemoryStatus(ctypes.Structure):
            _fields_ = (
                ("length", ctypes.c_ulong),
                ("memory_load", ctypes.c_ulong),
                ("total_physical", ctypes.c_ulonglong),
                ("available_physical", ctypes.c_ulonglong),
                ("total_page_file", ctypes.c_ulonglong),
                ("available_page_file", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong),
                ("available_virtual", ctypes.c_ulonglong),
                ("available_extended_virtual", ctypes.c_ulonglong),
            )

        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.total_physical)
    if hasattr(os, "sysconf"):
        try:
            return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
        except (OSError, ValueError):
            pass
    return 0


def _bundle_runtime_metadata(bundle: Path) -> dict[str, str]:
    manifest_path = Path(bundle) / "bundle-manifest.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("The benchmark bundle manifest is invalid.") from exc
    if not isinstance(payload, Mapping):
        raise RuntimeError("The benchmark bundle manifest is invalid.")
    commit = payload.get("source_commit")
    versions = {
        "python_version": payload.get("python_version"),
        "pyside6_version": payload.get("pyside6_version"),
        "qt_version": payload.get("qt_version"),
    }
    modes = payload.get("presentation_modes")
    imports = payload.get("qml_imports")
    if (
        payload.get("schema_version") != 1
        or payload.get("qml_contract_version") != 1
        or not isinstance(commit, str)
        or _COMMIT_PATTERN.fullmatch(commit) is None
        or not isinstance(modes, list)
        or not all(isinstance(mode, str) for mode in modes)
        or not {"clean", "qt-quick"}.issubset(modes)
        or not isinstance(imports, list)
        or not imports
        or any(
            not isinstance(value, str) or _VERSION_PATTERN.fullmatch(value) is None
            for value in versions.values()
        )
    ):
        raise RuntimeError("The benchmark bundle manifest is invalid.")
    return {
        "bundle_commit": commit.casefold(),
        **versions,
    }


def _source_commit() -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        completed = None
    fallback = completed.stdout.strip() if completed is not None and completed.returncode == 0 else ""
    if _COMMIT_PATTERN.fullmatch(fallback) is None:
        raise RuntimeError("The benchmark bundle commit is unavailable.")
    return fallback.casefold()


def environment_fingerprint(
    *,
    stress: str = "none",
    target: BenchmarkTarget | None = None,
) -> dict[str, object]:
    if target is not None and target.bundle_directory is not None:
        runtime = _bundle_runtime_metadata(target.bundle_directory)
    else:
        try:
            import PySide6
            from PySide6.QtCore import qVersion

            pyside6_version = PySide6.__version__
            qt_version = qVersion()
        except ImportError:
            pyside6_version = "unavailable"
            qt_version = "unavailable"
        runtime = {
            "bundle_commit": _source_commit(),
            "python_version": platform.python_version(),
            "pyside6_version": pyside6_version,
            "qt_version": qt_version,
        }
    fingerprint = {
        "os": f"{platform.system()} {platform.release()} {platform.version()}".strip(),
        "cpu": (platform.processor() or platform.machine() or "unreported").strip(),
        "logical_cores": os.cpu_count() or 0,
        "ram_bytes": _ram_bytes(),
        "power_mode": os.environ.get("SGFX_BENCHMARK_POWER_MODE", "unreported").strip() or "unreported",
        "display": os.environ.get("SGFX_BENCHMARK_DISPLAY", "unreported").strip() or "unreported",
        "python_version": runtime["python_version"],
        "pyside6_version": runtime["pyside6_version"],
        "qt_version": runtime["qt_version"],
        "bundle_commit": runtime["bundle_commit"],
        "stress": stress,
    }
    return sanitize_environment_fingerprint(fingerprint)


def benchmark_target() -> BenchmarkTarget:
    bundle = ROOT / "dist" / "sgfx-preflight"
    executable = bundle / "sgfx-preflight.exe"
    manifest = bundle / "bundle-manifest.json"
    if executable.exists() or manifest.exists():
        if not executable.is_file() or not manifest.is_file():
            raise RuntimeError("The benchmark bundle is incomplete.")
        _bundle_runtime_metadata(bundle)
        return BenchmarkTarget((str(executable),), bundle, bundle)
    return BenchmarkTarget(
        (sys.executable, "-B", "-m", "sg_preflight.exe_entry"),
        ROOT,
        None,
    )


def _run_benchmark_worker(
    scenario: str,
    *,
    target: BenchmarkTarget,
    runner: Any = subprocess.run,
) -> Mapping[str, object]:
    with tempfile.TemporaryDirectory(prefix="sgfx-qt-benchmark-") as temp_dir:
        root = Path(temp_dir)
        output_path = root / "result.json"
        workspace = root / "workspace"
        workspace.mkdir()
        request_path = root / "request.json"
        start_ns = time.perf_counter_ns()
        request = {
            "scenario": scenario,
            "output_path": str(output_path),
            "workspace": str(workspace),
            "start_ns": start_ns,
        }
        request_path.write_text(json.dumps(request, sort_keys=True), encoding="utf-8")
        environment = os.environ.copy()
        environment[BENCHMARK_REQUEST_ENV] = str(request_path)
        for key in ("QML2_IMPORT_PATH", "QML_IMPORT_PATH", "QT_PLUGIN_PATH", "PYTHONPATH"):
            environment.pop(key, None)
        try:
            completed = runner(
                list(target.command),
                cwd=target.working_directory,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=90,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError("The Qt Quick benchmark worker could not be completed.") from exc
        if completed.returncode != 0 or not output_path.is_file():
            raise RuntimeError("The Qt Quick benchmark worker failed.")
        try:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("The Qt Quick benchmark worker returned invalid data.") from exc
        if not isinstance(payload, Mapping) or payload.get("acknowledged") is not True:
            raise RuntimeError("The Qt Quick benchmark worker missed an acknowledgement.")
        return payload


def _start_cpu_load(duration_s: int = 90) -> list[subprocess.Popen[bytes]]:
    worker_count = max(1, os.cpu_count() or 1)
    workload = (
        "import time\n"
        f"deadline=time.perf_counter()+{int(duration_s)}\n"
        "value=1\n"
        "while time.perf_counter()<deadline:\n"
        " cycle=time.perf_counter()\n"
        " while time.perf_counter()-cycle<0.075:\n"
        "  value=(value*1103515245+12345)&0x7fffffff\n"
        " remaining=0.1-(time.perf_counter()-cycle)\n"
        " if remaining>0:\n"
        "  time.sleep(remaining)\n"
    )
    processes: list[subprocess.Popen[bytes]] = []
    try:
        for _index in range(worker_count):
            processes.append(
                subprocess.Popen(
                    [sys.executable, "-B", "-c", workload],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            )
    except OSError:
        _stop_cpu_load(processes)
        raise
    return processes


def _stop_cpu_load(processes: Sequence[subprocess.Popen[bytes]]) -> None:
    for process in processes:
        if process.poll() is None:
            process.terminate()
    for process in processes:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def collect_scenario(
    scenario: str,
    *,
    target: BenchmarkTarget | None = None,
    runner: Any = subprocess.run,
) -> Mapping[str, object]:
    selected = target or benchmark_target()
    if scenario == "warm-start":
        priming = _run_benchmark_worker("startup", target=selected, runner=runner)
        measured = [
            _run_benchmark_worker("startup", target=selected, runner=runner)
            for _index in range(20)
        ]
        return {
            "priming_ms": priming.get("duration_ms"),
            "launch_ms": [item.get("duration_ms") for item in measured],
        }
    if scenario == "first-run":
        if selected.bundle_directory is None or not selected.bundle_directory.is_dir():
            raise RuntimeError("First-run measurement requires a staged bundle.")
        executable_name = Path(selected.command[0]).name
        launches: list[dict[str, object]] = []
        with tempfile.TemporaryDirectory(prefix="sgfx-first-run-") as temp_dir:
            staging_root = Path(temp_dir)
            for index in range(1, 6):
                stage_id = f"stage-{index}"
                staged_bundle = staging_root / stage_id
                shutil.copytree(selected.bundle_directory, staged_bundle)
                staged_target = BenchmarkTarget(
                    (str(staged_bundle / executable_name),),
                    staged_bundle,
                    staged_bundle,
                )
                result = _run_benchmark_worker("startup", target=staged_target, runner=runner)
                launches.append({"stage_id": stage_id, "duration_ms": result.get("duration_ms")})
                shutil.rmtree(staged_bundle)
        return {"launches": launches}
    if scenario in {"navigation", "reader-stress"}:
        cpu_load: list[subprocess.Popen[bytes]] = []
        try:
            if scenario == "reader-stress":
                cpu_load = _start_cpu_load()
            result = _run_benchmark_worker(scenario, target=selected, runner=runner)
        finally:
            _stop_cpu_load(cpu_load)
        samples = result.get("raw_samples")
        if not isinstance(samples, Mapping):
            raise RuntimeError("The Qt Quick benchmark worker returned invalid samples.")
        return samples
    raise ValueError("Unknown benchmark scenario.")


def _load_samples(path: Path) -> Mapping[str, object]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("The benchmark sample input is invalid.") from exc
    if not isinstance(payload, Mapping):
        raise RuntimeError("The benchmark sample input is invalid.")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate repeatable Qt Quick performance evidence.")
    parser.add_argument("--scenario", choices=SCENARIOS, required=True)
    parser.add_argument("--format", choices=("json",), default="json")
    parser.add_argument("--samples", type=Path)
    args = parser.parse_args(argv)
    try:
        target = None if args.samples is not None else benchmark_target()
        raw_samples = (
            _load_samples(args.samples)
            if args.samples is not None
            else collect_scenario(args.scenario, target=target)
        )
        fingerprint = environment_fingerprint(
            stress=args.scenario if args.scenario == "reader-stress" else "none",
            target=target,
        )
        evidence = evaluate_scenario(args.scenario, raw_samples, fingerprint)
    except (RuntimeError, ValueError) as exc:
        print(json.dumps({"scenario": args.scenario, "passed": False, "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
