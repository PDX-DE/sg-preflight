from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any

EVIDENCE_ONLY_BANNER = (
    "Evidence only - the Ramses probe records metadata, validation, inventory, logic, lifecycle, "
    "and frame evidence; manual review remains required."
)

NATIVE_REPORT_NAME = "ramses-probe-native.json"
EVIDENCE_FILE_NAME = "ramses-r0-evidence.json"

_EVIDENCE_MAX_BYTES = 4 * 1024 * 1024
_CONSOLE_STREAM_MAX_BYTES = 256 * 1024
_REPORT_TOP_LEVEL_KEYS = {
    "schemaVersion", "probeVersion", "profile", "backend", "scenePath", "metadata", "phases",
    "failure", "findings", "inventory", "logic", "lifecycle", "frame",
}
_PHASE_NAMES = ("arguments", "metadata", "scene_load", "validation", "inventory", "logic",
                "perspective", "frame")
_PHASE_STATUSES = {"completed", "failed", "not_run", "not_requested"}


@dataclass(frozen=True)
class ProbeRunRequest:
    profile: str
    scene_path: Path
    output_root: Path
    helper_path: Path
    helper_sha256: str
    perspective_path: Path | None = None
    perspective_id: str | None = None
    backend: str = "opengl"
    timeout_seconds: int = 120


@dataclass(frozen=True)
class ProbeRunResult:
    outcome: str
    exit_code: int
    rejections: tuple[str, ...]
    evidence_path: Path | None
    native_report: dict[str, Any] | None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _worktree_status(anchor: Path) -> str | None:
    git = shutil.which("git")
    if git is None:
        return None
    try:
        toplevel = subprocess.run(
            [git, "-C", str(anchor), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=30, check=False)
        if toplevel.returncode != 0:
            return None
        status = subprocess.run(
            [git, "-C", str(anchor), "status", "--porcelain"],
            capture_output=True, text=True, timeout=60, check=False)
        if status.returncode != 0:
            return None
        return status.stdout
    except (OSError, subprocess.TimeoutExpired):
        return None


def build_helper_arguments(request: ProbeRunRequest) -> list[str]:
    arguments = [
        "--scene", str(request.scene_path),
        "--output-root", str(request.output_root),
        "--profile", request.profile,
        "--backend", request.backend,
    ]
    if request.perspective_path is not None and request.perspective_id is not None:
        arguments += ["--perspective", str(request.perspective_path),
                      "--perspective-id", request.perspective_id]
    return arguments


def validate_native_report(report: object, *, expected_profile: str,
                           expected_scene_path: str) -> list[str]:
    if not isinstance(report, dict) or set(report.keys()) != _REPORT_TOP_LEVEL_KEYS:
        return ["malformed_report"]
    if report["schemaVersion"] != 1 or report["probeVersion"] != "0.1.0":
        return ["malformed_report"]
    if not isinstance(report["profile"], str) or not isinstance(report["scenePath"], str):
        return ["malformed_report"]
    if not isinstance(report["phases"], list) or not isinstance(report["findings"], list) or \
            not isinstance(report["inventory"], list) or not isinstance(report["logic"], list):
        return ["malformed_report"]

    rejections: list[str] = []

    phases = report["phases"]
    phase_shape_valid = len(phases) == len(_PHASE_NAMES) and all(
        isinstance(record, dict) and set(record.keys()) == {"phase", "status"}
        and record["phase"] == name and record["status"] in _PHASE_STATUSES
        for record, name in zip(phases, _PHASE_NAMES)
    )
    if not phase_shape_valid:
        rejections.append("partial_report")
    else:
        has_failed_phase = any(record["status"] == "failed" for record in phases)
        failure = report["failure"]
        failure_valid = failure is None or (
            isinstance(failure, dict) and set(failure.keys()) == {"phase", "reason"})
        if not failure_valid or has_failed_phase != (failure is not None):
            rejections.append("partial_report")

    if report["profile"] != expected_profile:
        rejections.append("mismatched_profile")
    if report["scenePath"] != expected_scene_path:
        rejections.append("mismatched_source")

    frame = report["frame"]
    if isinstance(frame, dict):
        frame_file = frame.get("file")
        if frame_file is not None and frame_file != "first-frame.png":
            rejections.append("escaped_path")

    return rejections


def _write_evidence_atomically(output_root: Path, payload: dict[str, Any]) -> Path | None:
    text = json.dumps(payload, indent=2, sort_keys=True)
    if len(text.encode("utf-8")) > _EVIDENCE_MAX_BYTES:
        return None
    target = output_root / EVIDENCE_FILE_NAME
    temporary = output_root / (EVIDENCE_FILE_NAME + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, target)
    return target


def run_probe(request: ProbeRunRequest) -> ProbeRunResult:
    rejections: list[str] = []
    native_report: dict[str, Any] | None = None
    exit_code = -1
    helper_digest_actual = ""
    scene_before = ""
    scene_after = ""
    perspective_digest = ""
    worktree_before: str | None = None
    worktree_after: str | None = None

    def finish(outcome: str) -> ProbeRunResult:
        evidence = {
            "schemaVersion": 1,
            "banner": EVIDENCE_ONLY_BANNER,
            "request": {
                "profile": request.profile,
                "backend": request.backend,
                "scenePath": str(request.scene_path),
                "outputRoot": str(request.output_root),
                "perspectivePath": str(request.perspective_path) if request.perspective_path else None,
                "perspectiveId": request.perspective_id,
            },
            "helper": {
                "path": str(request.helper_path),
                "sha256Expected": request.helper_sha256,
                "sha256Actual": helper_digest_actual,
            },
            "digests": {
                "sceneBefore": scene_before,
                "sceneAfter": scene_after,
                "perspective": perspective_digest or None,
                "worktreeStatusBefore": worktree_before,
                "worktreeStatusAfter": worktree_after,
            },
            "helperExitCode": exit_code,
            "outcome": outcome,
            "rejections": list(rejections),
            "nativeReport": native_report,
        }
        evidence_path = None
        if request.output_root.is_dir():
            evidence_path = _write_evidence_atomically(request.output_root, evidence)
        return ProbeRunResult(
            outcome=outcome,
            exit_code=exit_code,
            rejections=tuple(rejections),
            evidence_path=evidence_path,
            native_report=native_report,
        )

    if not request.helper_path.is_file():
        rejections.append("untrusted_helper")
        return finish("untrusted_helper")
    helper_digest_actual = sha256_file(request.helper_path)
    if helper_digest_actual.lower() != request.helper_sha256.lower():
        rejections.append("untrusted_helper")
        return finish("untrusted_helper")

    if not request.scene_path.is_file():
        rejections.append("scene_unavailable")
        return finish("scene_unavailable")
    if not request.output_root.is_dir():
        rejections.append("output_unavailable")
        return finish("output_unavailable")
    output_root = request.output_root.resolve()
    source_root = request.scene_path.resolve().parent
    if output_root.is_relative_to(source_root) or source_root.is_relative_to(output_root):
        rejections.append("roots_not_disjoint")
        return finish("roots_not_disjoint")
    report_path = request.output_root / NATIVE_REPORT_NAME
    if report_path.exists():
        rejections.append("stale_report")
        return finish("stale_report")

    scene_before = sha256_file(request.scene_path)
    if request.perspective_path is not None and request.perspective_path.is_file():
        perspective_digest = sha256_file(request.perspective_path)
    worktree_before = _worktree_status(request.scene_path.parent)

    def persist_console(stream_name: str, payload: bytes | None) -> None:
        target = request.output_root / stream_name
        target.write_bytes((payload or b"")[:_CONSOLE_STREAM_MAX_BYTES])

    try:
        completed = subprocess.run(
            [str(request.helper_path), *build_helper_arguments(request)],
            capture_output=True,
            timeout=request.timeout_seconds,
            check=False,
        )
        exit_code = completed.returncode
        persist_console("stdout.log", completed.stdout)
        persist_console("stderr.log", completed.stderr)
    except subprocess.TimeoutExpired as expired:
        persist_console("stdout.log", expired.stdout)
        persist_console("stderr.log", expired.stderr)
        rejections.append("helper_timeout")
        return finish("helper_timeout")

    if not report_path.is_file():
        return finish("helper_crash")
    try:
        parsed = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rejections.append("malformed_report")
        return finish("malformed_report")

    report_rejections = validate_native_report(
        parsed, expected_profile=request.profile, expected_scene_path=str(request.scene_path))
    if report_rejections:
        rejections.extend(report_rejections)
        return finish(report_rejections[0])
    native_report = parsed

    scene_after = sha256_file(request.scene_path)
    if scene_after != scene_before:
        rejections.append("source_mutated")
        return finish("source_mutated")
    if request.perspective_path is not None and perspective_digest and \
            sha256_file(request.perspective_path) != perspective_digest:
        rejections.append("source_mutated")
        return finish("source_mutated")
    if worktree_before is not None:
        worktree_after = _worktree_status(request.scene_path.parent)
        if worktree_after != worktree_before:
            rejections.append("worktree_status_changed")
            return finish("worktree_status_changed")

    if exit_code == 0:
        return finish("completed")
    if exit_code == 65:
        failure = native_report["failure"]
        if isinstance(failure, dict):
            return finish(str(failure["reason"]))
        rejections.append("partial_report")
        return finish("partial_report")
    return finish("helper_crash")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sg_preflight.ramses_probe_runner",
        description="Run the Ramses R0 probe helper and publish validated local evidence.",
    )
    parser.add_argument("--profile", required=True)
    parser.add_argument("--scene", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--helper", required=True, type=Path)
    parser.add_argument("--helper-sha256", required=True)
    parser.add_argument("--perspective", type=Path)
    parser.add_argument("--perspective-id")
    parser.add_argument("--timeout-seconds", type=int, default=120)
    options = parser.parse_args(argv)
    if (options.perspective is None) != (options.perspective_id is None):
        parser.error("--perspective and --perspective-id must be supplied together")

    result = run_probe(ProbeRunRequest(
        profile=options.profile,
        scene_path=options.scene,
        output_root=options.output_root,
        helper_path=options.helper,
        helper_sha256=options.helper_sha256,
        perspective_path=options.perspective,
        perspective_id=options.perspective_id,
        timeout_seconds=options.timeout_seconds,
    ))
    print(f"ramses-probe outcome={result.outcome} exit={result.exit_code} "
          f"evidence={result.evidence_path}")
    if result.outcome == "completed":
        return 0
    if result.outcome in {"helper_crash", "helper_timeout"}:
        return 70
    return 65


if __name__ == "__main__":
    raise SystemExit(main())
