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
_FRAME_OUTCOMES = {"readback_complete", "missing_contract", "renderer_unavailable",
                   "scene_incompatible", "logic_update_failed", "lifecycle_rejected",
                   "lifecycle_timeout", "readback_failed", "frame_write_failed", "frame_too_large"}
_FRAME_CLASSIFICATIONS = {"content", "black", "undetermined"}
_FRAME_KEYS = {"outcome", "classification", "file", "drivenInputs"}
# Exactly the classified reasons the native probe emits per phase; every phase can additionally
# carry the probe's unexpected_exception catch-all. Anything else (including reserved outcome
# words like "completed") fails closed.
_FAILURE_REASONS_BY_PHASE = {
    "scene_load": {"scene_unavailable", "scene_incompatible", "framework_unavailable"},
    "perspective": {"perspective_unreadable", "perspective_too_large", "perspective_malformed",
                    "perspective_id_missing", "perspective_values_invalid"},
    "frame": _FRAME_OUTCOMES - {"readback_complete", "missing_contract"},
}


def _failure_record_valid(failure: dict[str, Any]) -> bool:
    phase = failure["phase"]
    reason = failure["reason"]
    if phase not in _PHASE_NAMES:
        return False
    if reason == "unexpected_exception":
        return True
    return reason in _FAILURE_REASONS_BY_PHASE.get(phase, set())


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


_PROBE_HELPER_BUNDLE_RELATIVE = Path("_internal") / "cpp" / "bin" / "sgfx_cine_ramses_probe.exe"
_BUNDLE_MANIFEST_NAME = "bundle-manifest.json"
_SHA256_HEX = 64


@dataclass(frozen=True)
class ProbeHelperReadiness:
    ready: bool
    reason: str
    helper_path: Path | None
    helper_sha256: str


def resolve_packaged_probe_helper(bundle_root: Path) -> ProbeHelperReadiness:
    # Fail closed with the exact missing prerequisite: a missing helper must surface as
    # unavailable to the caller, never as a preflight failure (design section 13).
    def unavailable(reason: str) -> ProbeHelperReadiness:
        return ProbeHelperReadiness(ready=False, reason=reason, helper_path=None,
                                    helper_sha256="")

    manifest_path = Path(bundle_root) / _BUNDLE_MANIFEST_NAME
    if not manifest_path.is_file():
        return unavailable("manifest_unavailable")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return unavailable("manifest_malformed")
    if not isinstance(manifest, dict):
        return unavailable("manifest_malformed")
    state = manifest.get("ramses_probe_helper")
    digest = manifest.get("ramses_probe_helper_sha256")
    if state not in {"included", "unavailable"} or not isinstance(digest, str):
        return unavailable("manifest_malformed")
    if state == "unavailable":
        return unavailable("helper_not_packaged")
    if len(digest) != _SHA256_HEX or any(c not in "0123456789abcdef" for c in digest):
        return unavailable("manifest_malformed")
    helper_path = Path(bundle_root) / _PROBE_HELPER_BUNDLE_RELATIVE
    if not helper_path.is_file():
        return unavailable("helper_missing")
    if sha256_file(helper_path) != digest:
        return unavailable("helper_digest_mismatch")
    return ProbeHelperReadiness(ready=True, reason="", helper_path=helper_path,
                                helper_sha256=digest)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _porcelain_paths(line: str) -> list[str]:
    # A porcelain status line references one path, or two for a rename/copy ("old -> new").
    body = line[3:]
    if " -> " in body:
        old, new = body.split(" -> ", 1)
        return [old.strip().strip('"'), new.strip().strip('"')]
    return [body.strip().strip('"')]


def _worktree_status(anchor: Path, exclude: Path | None = None) -> str | None:
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
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = status.stdout.splitlines()
    if exclude is not None:
        # The probe's own sanctioned writes must not count as a source-worktree mutation.
        try:
            prefix = exclude.resolve().relative_to(Path(toplevel.stdout.strip()).resolve()).as_posix()
        except (OSError, ValueError):
            prefix = ""
        if prefix and prefix != ".":
            def _under_output(path: str) -> bool:
                return path.startswith(prefix + "/") or path.rstrip("/") == prefix

            # Drop a line only when every path it names lives under the probe's own output root.
            # A rename that moves a tracked source file OUT of the tree into the output root keeps
            # the line (its source side is outside the prefix), so the mutation is still caught.
            lines = [
                line for line in lines
                if not all(_under_output(path) for path in _porcelain_paths(line))
            ]
    return "\n".join(lines)


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
            isinstance(failure, dict) and set(failure.keys()) == {"phase", "reason"}
            and _failure_record_valid(failure))
        if not failure_valid or has_failed_phase != (failure is not None):
            rejections.append("partial_report")

    if report["profile"] != expected_profile:
        rejections.append("mismatched_profile")
    if report["scenePath"] != expected_scene_path:
        rejections.append("mismatched_source")

    frame = report["frame"]
    if isinstance(frame, dict):
        if set(frame.keys()) - _FRAME_KEYS:
            rejections.append("malformed_report")
        if frame.get("outcome") not in _FRAME_OUTCOMES:
            rejections.append("malformed_report")
        classification = frame.get("classification")
        if classification is not None and classification not in _FRAME_CLASSIFICATIONS:
            rejections.append("malformed_report")
        frame_file = frame.get("file")
        if frame_file is not None and frame_file != "first-frame.png":
            rejections.append("escaped_path")
    elif frame is not None:
        rejections.append("malformed_report")

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
    worktree_before = _worktree_status(request.scene_path.parent, exclude=request.output_root)

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

    # Re-verify the helper against its pin after execution: a same-machine writer could have
    # swapped the binary (or a symlink/junction in its path) in the window between the pre-launch
    # hash and the exec, so the digest that ran must still match what was vetted.
    if not request.helper_path.is_file() or \
            sha256_file(request.helper_path).lower() != request.helper_sha256.lower():
        rejections.append("untrusted_helper")
        return finish("untrusted_helper")

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
        worktree_after = _worktree_status(request.scene_path.parent, exclude=request.output_root)
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
