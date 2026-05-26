from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any

from sg_preflight.bmw_delivery import (
    LANE_IDC23,
    LANE_IDCEVO,
    LANE_UNKNOWN,
    candidate_bmw_profile_ids,
    detect_lane,
    find_bmw_registry_entry,
    read_bmw_screenshot_state,
    resolve_bmw_profile_id,
)
from sg_preflight.delivery_workbook_generation import (
    DIGITAL_3D_CAR_REPO_ENV,
    DIGITAL_3D_CAR_REPO_IDC23_ENV,
    _check,
    _clean_profile,
    _digital_repo_check,
    _elapsed_label,
    _idc23_repo_check,
    _existing_parent,
    _missing_car_payload,
    _overall_preflight_status,
    _registered_car_root,
    _requires_registered_car_folder,
    _sgfx_pipeline_output_root,
    _unavailable_model_summary,
    _python_check,
    _python_command_payload,
    _size_label,
    _tail_lines,
    _tail_text,
    _tool_check,
)
from sg_preflight.subprocess_utils import hidden_subprocess_kwargs
from sg_preflight.utils import ensure_parent


SCREENSHOT_CAPTURE_ACTION_ID = "capture-screenshots"
SCREENSHOT_CAPTURE_ACTION_LABEL = "Capture screenshots"
SCREENSHOT_CAPTURE_TIMEOUT_SECONDS = 900
SCREENSHOT_CAPTURE_MIN_FREE_BYTES = 100 * 1024 * 1024
SCREENSHOT_CAPTURE_TYPICAL_RANGE_LABEL = "typical 2-10 min"
SCREENSHOT_CAPTURE_FILE_ACTIVITY_LIMIT = 24
SCREENSHOT_CAPTURE_COPIED_EVIDENCE_LIMIT = 80
_SCREENSHOT_BRANDS = ("BMW", "MINI", "Alpina", "MGmbH", "RollsRoyce")


def _capture_tests_root(bmw_root: Path, profile_id: str) -> Path:
    candidates = candidate_bmw_profile_ids(profile_id)
    for brand in _SCREENSHOT_BRANDS:
        brand_root = bmw_root / "cars" / brand
        for candidate in candidates:
            car_root = brand_root / candidate
            if car_root.exists():
                return car_root / "export" / "tests"
    entry = find_bmw_registry_entry(profile_id, bmw_root)
    if entry is not None and entry.model_type == "retarget" and entry.target:
        for brand in _SCREENSHOT_BRANDS:
            target_root = bmw_root / "cars" / brand / entry.target
            if target_root.exists():
                return target_root / "export" / "tests"
    fallback_profile = candidates[0] if candidates else _clean_profile(profile_id)
    return bmw_root / "cars" / "BMW" / fallback_profile / "export" / "tests"


def _capture_activity_roots(bmw_root: Path, profile_id: str) -> list[Path]:
    tests_root = _capture_tests_root(bmw_root, profile_id)
    return [tests_root / "actuals", tests_root / "diff"]


def _screenshot_sgfx_output_dir(workspace: Path, profile_id: str) -> Path:
    return _sgfx_pipeline_output_root(workspace, profile_id, "screenshot-capture")


def _screenshot_disk_space_check(bmw_root: Path | None, profile_id: str, min_free_bytes: int) -> dict[str, str]:
    target = _capture_tests_root(bmw_root, profile_id) if bmw_root is not None else Path()
    probe_root = _existing_parent(target if target != Path() else Path.cwd())
    try:
        usage = shutil.disk_usage(probe_root)
    except OSError as exc:
        return _check(
            key="screenshot_disk_space",
            label="screenshot output disk headroom",
            status="failed",
            detail=f"Could not read disk space for {probe_root}: {exc}",
            path=target,
            remediation="Verify the local BMW Git checkout path is accessible.",
        )
    free_bytes = int(usage.free)
    if free_bytes < min_free_bytes:
        return _check(
            key="screenshot_disk_space",
            label="screenshot output disk headroom",
            status="missing",
            detail=f"{free_bytes} bytes free; {min_free_bytes} bytes required.",
            path=target,
            remediation="Free local disk space before running screenshot capture.",
        )
    return _check(
        key="screenshot_disk_space",
        label="screenshot output disk headroom",
        status="available",
        detail=f"{free_bytes} bytes free; {min_free_bytes} bytes required.",
        path=target,
    )


def resolve_screenshot_capture_command(
    *,
    profile_id: str,
    bmw_root: Path | str,
    workspace: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(bmw_root).resolve()
    clean_profile = _clean_profile(profile_id)
    lane = detect_lane(clean_profile, bmw_root=root)
    python_payload = _python_command_payload(workspace)
    if python_payload["status"] != "available":
        return {
            "status": "unavailable",
            "strategy": "none",
            "command": [],
            "cwd": str(root),
            "script_path": "",
            "lane": lane,
            "summary": str(python_payload.get("detail", "No Python launcher was found.")),
        }
    python_command = list(python_payload["command"])
    if lane == LANE_UNKNOWN:
        return {
            "status": "unavailable",
            "strategy": "none",
            "command": [],
            "cwd": str(root),
            "script_path": "",
            "profile_id": clean_profile,
            "bmw_profile_id": "",
            "lane": LANE_UNKNOWN,
            "summary": _unavailable_model_summary(clean_profile, root),
            "remediation": "Use the BMW Git source-of-truth checkout for lane detection before running screenshot capture.",
        }
    if lane == LANE_IDC23:
        idc23_check, idc23_root = _idc23_repo_check(workspace)
        if idc23_root is None or idc23_check["status"] != "available":
            return {
                "status": "unavailable",
                "strategy": "none",
                "command": [],
                "cwd": str(root),
                "script_path": "",
                "profile_id": clean_profile,
                "bmw_profile_id": "",
                "lane": lane,
                "summary": idc23_check["detail"],
                "remediation": idc23_check.get("remediation", ""),
            }
        legacy = idc23_root / "ci" / "scripts" / "test" / "main.py"
        bmw_profile = resolve_bmw_profile_id(clean_profile, idc23_root)
        bmw_profile, car_root = _registered_car_root(
            profile_id=clean_profile,
            source_root=root,
            execution_root=idc23_root,
            resolved_bmw_profile_id=bmw_profile,
        )
        if _requires_registered_car_folder(clean_profile, root) and not car_root.is_dir():
            return _missing_car_payload(
                clean_profile=clean_profile,
                lane=lane,
                root=root,
                execution_root=idc23_root,
                bmw_profile=bmw_profile,
                car_root=car_root,
                action="screenshot capture",
            )
        return {
            "status": "available",
            "strategy": "idc23_test_main_screenshots",
            "command": [*python_command, str(legacy), "screenshots", "--diff", bmw_profile],
            "cwd": str(idc23_root),
            "script_path": str(legacy),
            "profile_id": clean_profile,
            "bmw_profile_id": bmw_profile,
            "lane": lane,
            "source_bmw_root": str(root),
            "execution_bmw_root": str(idc23_root),
        }
    car_manager = root / "ci" / "scripts" / "car_manager.py"
    if lane == LANE_IDCEVO and car_manager.is_file():
        bmw_profile = resolve_bmw_profile_id(clean_profile, root)
        bmw_profile, car_root = _registered_car_root(
            profile_id=clean_profile,
            source_root=root,
            execution_root=root,
            resolved_bmw_profile_id=bmw_profile,
        )
        if _requires_registered_car_folder(clean_profile, root) and not car_root.is_dir():
            return _missing_car_payload(
                clean_profile=clean_profile,
                lane=lane,
                root=root,
                execution_root=root,
                bmw_profile=bmw_profile,
                car_root=car_root,
                action="screenshot capture",
            )
        return {
            "status": "available",
            "strategy": "car_manager_screenshots",
            "command": [*python_command, str(car_manager), "screenshots", "--diff", bmw_profile],
            "cwd": str(root),
            "script_path": str(car_manager),
            "profile_id": clean_profile,
            "bmw_profile_id": bmw_profile,
            "lane": lane,
            "source_bmw_root": str(root),
            "execution_bmw_root": str(root),
        }
    return {
        "status": "unavailable",
        "strategy": "none",
        "command": [],
        "cwd": str(root),
        "script_path": "",
        "profile_id": clean_profile,
        "bmw_profile_id": "",
        "lane": lane,
        "summary": "No supported BMW pipeline screenshot script was found for the detected lane.",
        "remediation": "IDC_EVO requires ci/scripts/car_manager.py on master; IDC_23 requires ci/scripts/test/main.py on an assets/idc23 worktree.",
    }


def check_screenshot_capture_environment(
    *,
    profile_id: str,
    workspace: Path | str,
    bmw_root: Path | str | None = None,
    min_free_bytes: int = SCREENSHOT_CAPTURE_MIN_FREE_BYTES,
) -> dict[str, Any]:
    workspace_path = Path(workspace).resolve()
    clean_profile = _clean_profile(profile_id)
    repo_check, repo_root = _digital_repo_check(bmw_root, workspace=workspace_path)
    lane = detect_lane(clean_profile, bmw_root=repo_root) if repo_root is not None else LANE_UNKNOWN
    checks = [
        repo_check,
        _python_check(workspace_path),
        _tool_check("RaCoHeadless.exe", "RaCoHeadless", workspace=workspace_path),
        _tool_check("blender.exe", "Blender", workspace=workspace_path),
    ]
    if repo_root is not None:
        if lane == LANE_IDC23 and repo_check["status"] == "available":
            idc23_check, _idc23_root = _idc23_repo_check(workspace_path)
            checks.append(idc23_check)
        command_payload = resolve_screenshot_capture_command(
            profile_id=clean_profile,
            bmw_root=repo_root,
            workspace=workspace_path,
        )
        if command_payload["status"] == "available":
            checks.append(
                _check(
                    key="bmw_screenshot_script",
                    label="BMW screenshot script",
                    status="available",
                    detail=f"Using {command_payload['strategy']} for {command_payload.get('lane', lane)}.",
                    path=str(command_payload.get("script_path", "")),
                )
            )
        else:
            checks.append(
                _check(
                    key="bmw_screenshot_script",
                    label="BMW screenshot script",
                    status=str(command_payload.get("status", "unavailable")),
                    detail=str(command_payload.get("summary", "No supported screenshot script was found.")),
                    remediation=str(
                        command_payload.get(
                            "remediation",
                            "Use the lane-correct BMW Git checkout: master for IDC_EVO or assets/idc23 for IDC_23.",
                        )
                    ),
                )
            )
    else:
        checks.append(
            _check(
                key="bmw_screenshot_script",
                label="BMW screenshot script",
                status="unavailable",
                detail="BMW Git checkout was not resolved, so screenshot script discovery did not run.",
            )
        )
    execution_root = (
        Path(str(command_payload.get("execution_bmw_root"))).resolve()
        if repo_root is not None and command_payload.get("status") == "available"
        else repo_root
    )
    checks.append(_screenshot_disk_space_check(execution_root, clean_profile, min_free_bytes))
    can_run = all(check["status"] == "available" for check in checks)
    status = _overall_preflight_status(checks)
    native_target_path = _capture_tests_root(execution_root, clean_profile) if execution_root is not None else Path()
    target_path = _screenshot_sgfx_output_dir(workspace_path, clean_profile)
    return {
        "profile_id": clean_profile,
        "workspace": str(workspace_path),
        "bmw_root": str(repo_root or ""),
        "execution_bmw_root": str(execution_root or ""),
        "lane": lane,
        "target_write_path": str(target_path),
        "native_output_path": str(native_target_path),
        "sgfx_output_root": str(target_path),
        "estimated_size_bytes": min_free_bytes,
        "status": status,
        "can_run": can_run,
        "checks": checks,
        "confirmation_message": (
            f"This will run BMW pipeline screenshot capture for {clean_profile}. It may write native actual/diff "
            f"output under `{native_target_path}`; SGFX copies review evidence to `{target_path}`. Continue?"
        ),
        "disabled_reason": "" if can_run else "One or more environment pre-flight checks failed.",
    }


@dataclass
class ScreenshotCaptureJob:
    profile_id: str
    workspace: Path
    bmw_root: Path
    process: subprocess.Popen[bytes]
    command: list[str]
    strategy: str
    stdout_path: Path
    stderr_path: Path
    started_monotonic: float
    started_wall_time: float
    timeout_seconds: int
    preflight: dict[str, Any]
    completed: bool = False


def _capture_file_activity(
    bmw_root: Path,
    profile_id: str,
    started_wall_time: float,
    limit: int = SCREENSHOT_CAPTURE_FILE_ACTIVITY_LIMIT,
) -> list[dict[str, Any]]:
    entries: list[tuple[float, dict[str, Any]]] = []
    threshold = started_wall_time - 1.0
    seen_roots: set[Path] = set()
    for root in _capture_activity_roots(bmw_root, profile_id):
        scan_root = root if root.is_dir() else root.parent
        if not scan_root.is_dir():
            continue
        resolved_scan_root = scan_root.resolve()
        if resolved_scan_root in seen_roots:
            continue
        seen_roots.add(resolved_scan_root)
        for path in scan_root.rglob("*"):
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            last_activity = max(stat.st_mtime, stat.st_ctime)
            if last_activity < threshold:
                continue
            event = "created" if stat.st_ctime >= threshold else "modified"
            try:
                relative = str(path.relative_to(scan_root))
            except ValueError:
                relative = path.name
            size_label = _size_label(int(stat.st_size))
            summary_path = f"{scan_root.name}/{relative}" if scan_root.name else relative
            entries.append(
                (
                    last_activity,
                    {
                        "event": event,
                        "path": str(path),
                        "relative_path": summary_path,
                        "size_bytes": int(stat.st_size),
                        "size_label": size_label,
                        "summary": f"{event.title()} `{summary_path}` ({size_label})",
                    },
                )
            )
    return [item for _timestamp, item in sorted(entries, key=lambda pair: pair[0], reverse=True)[:limit]]


def _copy_screenshot_capture_evidence(job: ScreenshotCaptureJob) -> dict[str, Any]:
    output_root = _screenshot_sgfx_output_dir(job.workspace, job.profile_id)
    copied_files: list[dict[str, Any]] = []
    for root in _capture_activity_roots(job.bmw_root, job.profile_id):
        if not root.is_dir():
            continue
        group = root.name or "screenshots"
        for source in root.rglob("*"):
            if not source.is_file():
                continue
            try:
                relative = source.relative_to(root)
            except ValueError:
                relative = Path(source.name)
            destination = output_root / group / relative
            ensure_parent(destination)
            shutil.copy2(source, destination)
            try:
                stat = destination.stat()
            except OSError:
                size_bytes = 0
            else:
                size_bytes = int(stat.st_size)
            copied_files.append(
                {
                    "source_path": str(source),
                    "path": str(destination),
                    "relative_path": str(Path(group) / relative).replace("\\", "/"),
                    "size_bytes": size_bytes,
                    "size_label": _size_label(size_bytes),
                }
            )
    for source, name in ((job.stdout_path, "stdout.log"), (job.stderr_path, "stderr.log")):
        if not source.is_file():
            continue
        destination = output_root / "logs" / name
        ensure_parent(destination)
        shutil.copy2(source, destination)
        try:
            stat = destination.stat()
        except OSError:
            size_bytes = 0
        else:
            size_bytes = int(stat.st_size)
        copied_files.append(
            {
                "source_path": str(source),
                "path": str(destination),
                "relative_path": str(Path("logs") / name).replace("\\", "/"),
                "size_bytes": size_bytes,
                "size_label": _size_label(size_bytes),
            }
        )
    return {
        "status": "recorded" if copied_files else "missing",
        "output_root": str(output_root),
        "files": copied_files[:SCREENSHOT_CAPTURE_COPIED_EVIDENCE_LIMIT],
        "file_count": len(copied_files),
    }


def _capture_combined_tail_lines(stdout_path: Path, stderr_path: Path) -> list[str]:
    lines = list(_tail_lines(stdout_path))
    lines.extend(f"stderr: {line}" for line in _tail_lines(stderr_path))
    return lines[-SCREENSHOT_CAPTURE_FILE_ACTIVITY_LIMIT:]


def _capture_progress_payload(job: ScreenshotCaptureJob, *, elapsed_seconds: float) -> dict[str, Any]:
    return {
        "profile_id": job.profile_id,
        "workspace": str(job.workspace),
        "bmw_root": str(job.bmw_root),
        "status": "running",
        "completed": False,
        "data_available": False,
        "exit_code": None,
        "strategy": job.strategy,
        "command": list(job.command),
        "timeout_seconds": job.timeout_seconds,
        "elapsed_seconds": int(max(0, elapsed_seconds)),
        "elapsed_label": _elapsed_label(elapsed_seconds),
        "typical_range": SCREENSHOT_CAPTURE_TYPICAL_RANGE_LABEL,
        "timed_out": False,
        "canceled": False,
        "summary": "BMW screenshot capture running.",
        "stdout_tail": _tail_text(job.stdout_path),
        "stdout_tail_lines": _capture_combined_tail_lines(job.stdout_path, job.stderr_path),
        "stderr_tail": _tail_text(job.stderr_path),
        "stdout_path": str(job.stdout_path),
        "stderr_path": str(job.stderr_path),
        "file_activity": _capture_file_activity(job.bmw_root, job.profile_id, job.started_wall_time),
        "sgfx_output_root": str(_screenshot_sgfx_output_dir(job.workspace, job.profile_id)),
        "native_output_path": str(_capture_tests_root(job.bmw_root, job.profile_id)),
        "preflight": job.preflight,
        "recorded_by_tool": True,
        "is_approval": False,
    }


def _capture_result(
    job: ScreenshotCaptureJob,
    *,
    exit_code: int,
    status: str,
    summary: str,
    timed_out: bool = False,
    canceled: bool = False,
) -> dict[str, Any]:
    screenshot_payload: dict[str, Any] = {}
    if not timed_out and not canceled:
        try:
            screenshot_payload = read_bmw_screenshot_state(
                profile_id=job.profile_id,
                workspace=job.workspace,
                bmw_root=job.bmw_root,
                sg_project_root=job.workspace,
            )
        except Exception as exc:  # noqa: BLE001
            screenshot_payload = {"status": "failed", "summary": f"screenshot state could not be re-read: {exc}"}
        actual_count = int(screenshot_payload.get("actual_count", 0) or 0)
        diff_count = int(screenshot_payload.get("diff_count", 0) or 0)
        if actual_count or diff_count:
            status = "available"
            summary = (
                str(screenshot_payload.get("summary", "Screenshot capture output is available."))
                if exit_code == 0
                else (
                    f"BMW screenshot capture produced actual/diff evidence with exit code {exit_code}. "
                    "Manual review remains required."
                )
            )
        elif status == "available":
            status = "incomplete"
            summary = (
                "BMW screenshot capture exited 0, but no actual or diff screenshot files were detected. "
                f"{screenshot_payload.get('summary', '')}".strip()
            )
    copied_evidence = _copy_screenshot_capture_evidence(job)
    elapsed_seconds = time.monotonic() - job.started_monotonic
    return {
        "profile_id": job.profile_id,
        "workspace": str(job.workspace),
        "bmw_root": str(job.bmw_root),
        "status": status,
        "completed": True,
        "data_available": status == "available",
        "exit_code": exit_code,
        "strategy": job.strategy,
        "command": list(job.command),
        "timeout_seconds": job.timeout_seconds,
        "elapsed_seconds": int(max(0, elapsed_seconds)),
        "elapsed_label": _elapsed_label(elapsed_seconds),
        "typical_range": SCREENSHOT_CAPTURE_TYPICAL_RANGE_LABEL,
        "timed_out": timed_out,
        "canceled": canceled,
        "summary": summary,
        "stdout_tail": _tail_text(job.stdout_path),
        "stdout_tail_lines": _capture_combined_tail_lines(job.stdout_path, job.stderr_path),
        "stderr_tail": _tail_text(job.stderr_path),
        "stdout_path": str(job.stdout_path),
        "stderr_path": str(job.stderr_path),
        "file_activity": _capture_file_activity(job.bmw_root, job.profile_id, job.started_wall_time),
        "copied_evidence": copied_evidence,
        "sgfx_output_root": copied_evidence["output_root"],
        "native_output_path": str(_capture_tests_root(job.bmw_root, job.profile_id)),
        "preflight": job.preflight,
        "screenshot_state_status": str(screenshot_payload.get("status", "")),
        "actual_count": int(screenshot_payload.get("actual_count", 0) or 0),
        "diff_count": int(screenshot_payload.get("diff_count", 0) or 0),
        "recorded_by_tool": True,
        "is_approval": False,
    }


def start_screenshot_capture(
    *,
    profile_id: str,
    workspace: Path | str,
    operator_confirmed: bool,
    bmw_root: Path | str | None = None,
    timeout_seconds: int = SCREENSHOT_CAPTURE_TIMEOUT_SECONDS,
) -> ScreenshotCaptureJob:
    if not operator_confirmed:
        raise ValueError("Operator confirmation is required before running BMW screenshot capture.")
    workspace_path = Path(workspace).resolve()
    clean_profile = _clean_profile(profile_id)
    preflight = check_screenshot_capture_environment(
        profile_id=clean_profile,
        workspace=workspace_path,
        bmw_root=bmw_root,
    )
    if not preflight["can_run"]:
        raise RuntimeError("Environment pre-flight checks must pass before running BMW screenshot capture.")
    repo_root = Path(str(preflight["bmw_root"])).resolve()
    command_payload = resolve_screenshot_capture_command(
        profile_id=clean_profile,
        bmw_root=repo_root,
        workspace=workspace_path,
    )
    if command_payload["status"] != "available":
        raise FileNotFoundError(str(command_payload.get("summary", "No supported BMW screenshot script was found.")))
    execution_root = Path(str(command_payload.get("execution_bmw_root") or command_payload["cwd"])).resolve()
    log_root = workspace_path / "operator_state" / "screenshot_capture"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stdout_path = log_root / f"{clean_profile}-{stamp}.stdout.log"
    stderr_path = log_root / f"{clean_profile}-{stamp}.stderr.log"
    ensure_parent(stdout_path)
    env = os.environ.copy()
    env[DIGITAL_3D_CAR_REPO_ENV] = str(execution_root)
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault("PYTHONIOENCODING", "utf-8")
    if command_payload.get("lane") == LANE_IDC23:
        env[DIGITAL_3D_CAR_REPO_IDC23_ENV] = str(execution_root)
    started_wall_time = time.time()
    started_monotonic = time.monotonic()
    with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
        process = subprocess.Popen(
            list(command_payload["command"]),
            cwd=str(command_payload["cwd"]),
            stdin=subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=stderr_handle,
            env=env,
            **hidden_subprocess_kwargs(),
        )
    return ScreenshotCaptureJob(
        profile_id=clean_profile,
        workspace=workspace_path,
        bmw_root=execution_root,
        process=process,
        command=list(command_payload["command"]),
        strategy=str(command_payload["strategy"]),
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        started_monotonic=started_monotonic,
        started_wall_time=started_wall_time,
        timeout_seconds=timeout_seconds,
        preflight=preflight,
    )


def poll_screenshot_capture(job: ScreenshotCaptureJob) -> dict[str, Any] | None:
    if job.completed:
        return _capture_result(job, exit_code=job.process.returncode or 0, status="unknown", summary="Job already completed.")
    exit_code = job.process.poll()
    elapsed = time.monotonic() - job.started_monotonic
    if exit_code is None and elapsed < job.timeout_seconds:
        return _capture_progress_payload(job, elapsed_seconds=elapsed)
    if exit_code is None:
        job.process.terminate()
        try:
            job.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            job.process.kill()
            job.process.wait(timeout=5)
        job.completed = True
        return _capture_result(
            job,
            exit_code=job.process.returncode if job.process.returncode is not None else -1,
            status="failed",
            summary=f"BMW screenshot capture timed out after {job.timeout_seconds} seconds.",
            timed_out=True,
        )
    job.completed = True
    return _capture_result(
        job,
        exit_code=exit_code,
        status="available" if exit_code == 0 else "failed",
        summary=(
            "BMW screenshot capture completed. Re-reading screenshot evidence."
            if exit_code == 0
            else f"BMW screenshot capture failed with exit code {exit_code}."
        ),
    )


def cancel_screenshot_capture(job: ScreenshotCaptureJob) -> dict[str, Any]:
    if job.process.poll() is None:
        job.process.terminate()
        try:
            job.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            job.process.kill()
            job.process.wait(timeout=5)
    job.completed = True
    return _capture_result(
        job,
        exit_code=job.process.returncode if job.process.returncode is not None else -1,
        status="failed",
        summary="BMW screenshot capture canceled by operator.",
        canceled=True,
    )
