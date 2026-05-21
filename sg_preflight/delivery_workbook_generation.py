from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any

from sg_preflight.delivery_checklist import read_delivery_checklist
from sg_preflight.subprocess_utils import hidden_subprocess_kwargs
from sg_preflight.utils import ensure_parent


DIGITAL_3D_CAR_REPO_ENV = "Digital-3D-Car-Repo"
BMW_PIPELINE_PYTHON_ENV = "SG_BMW_PYTHON_EXE"
GENERATE_WORKBOOK_ACTION_ID = "generate-delivery-workbook"
GENERATE_WORKBOOK_ACTION_LABEL = "Generate delivery workbook"
GENERATE_WORKBOOK_TIMEOUT_SECONDS = 600
GENERATE_WORKBOOK_MIN_FREE_BYTES = 100 * 1024 * 1024
GENERATION_STDOUT_TAIL_BYTES = 2000
GENERATION_STDOUT_TAIL_LINES = 20
GENERATION_FILE_ACTIVITY_LIMIT = 20
GENERATION_TYPICAL_RANGE_LABEL = "typical 1-10 min"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _clean_profile(profile_id: str) -> str:
    return profile_id.strip().upper()


def _existing_parent(path: Path) -> Path:
    current = path.resolve()
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


def _find_executable(executable_name: str) -> str:
    found = shutil.which(executable_name)
    if found:
        return found
    if sys.platform != "win32":
        return ""
    try:
        import winreg
    except ImportError:
        return ""
    subkey = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{executable_name}"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, subkey) as key:
                value, _kind = winreg.QueryValueEx(key, "")
        except OSError:
            continue
        candidate = Path(str(value).strip('"'))
        if candidate.is_file():
            return str(candidate)
    return ""


def _check(
    *,
    key: str,
    label: str,
    status: str,
    detail: str,
    path: Path | str | None = None,
    remediation: str = "",
) -> dict[str, str]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "detail": detail,
        "path": str(path or ""),
        "remediation": remediation,
    }


def _digital_repo_check(bmw_root: Path | str | None = None) -> tuple[dict[str, str], Path | None]:
    raw = str(bmw_root or os.environ.get(DIGITAL_3D_CAR_REPO_ENV, "")).strip()
    if not raw:
        return (
            _check(
                key="digital_3d_car_repo",
                label=f"{DIGITAL_3D_CAR_REPO_ENV} environment variable",
                status="missing",
                detail=f"{DIGITAL_3D_CAR_REPO_ENV} is not set.",
                remediation=(
                    f"Set {DIGITAL_3D_CAR_REPO_ENV} to the local digital-3d-car-models checkout before running export."
                ),
            ),
            None,
        )
    root = Path(raw).expanduser().resolve()
    cars_bmw = root / "cars" / "BMW"
    if not cars_bmw.is_dir():
        return (
            _check(
                key="digital_3d_car_repo",
                label=f"{DIGITAL_3D_CAR_REPO_ENV} environment variable",
                status="missing",
                detail="The configured BMW Git checkout does not expose cars/BMW.",
                path=root,
                remediation=f"Point {DIGITAL_3D_CAR_REPO_ENV} at the digital-3d-car-models repository root.",
            ),
            root,
        )
    return (
        _check(
            key="digital_3d_car_repo",
            label=f"{DIGITAL_3D_CAR_REPO_ENV} environment variable",
            status="available",
            detail="BMW Git checkout is available for read-only script invocation.",
            path=root,
        ),
        root,
    )


def _tool_check(executable_name: str, label: str) -> dict[str, str]:
    found = _find_executable(executable_name)
    key = executable_name.replace(".exe", "").replace("-", "_").casefold()
    if key == "racoheadless":
        key = "raco_headless"
    if found:
        return _check(
            key=key,
            label=label,
            status="available",
            detail=f"{label} executable is available.",
            path=found,
        )
    return _check(
        key=key,
        label=label,
        status="missing",
        detail=f"{label} executable was not found on PATH or App Paths.",
        remediation=f"Install {label} or add {executable_name} to PATH before running export.",
    )


def _python_command_payload() -> dict[str, Any]:
    override = os.environ.get(BMW_PIPELINE_PYTHON_ENV, "").strip()
    if override:
        override_path = Path(override).expanduser()
        if override_path.is_file():
            return {
                "status": "available",
                "command": [str(override_path.resolve())],
                "path": str(override_path.resolve()),
                "detail": f"{BMW_PIPELINE_PYTHON_ENV} points to a Python executable.",
            }
        return {
            "status": "missing",
            "command": [],
            "path": str(override_path),
            "detail": f"{BMW_PIPELINE_PYTHON_ENV} is set, but the file does not exist.",
        }

    candidates: list[str] = []
    if not getattr(sys, "frozen", False):
        candidates.append(str(Path(sys.executable).resolve()))
    for executable_name in ("py.exe", "python.exe", "python3.exe", "py", "python", "python3"):
        found = shutil.which(executable_name)
        if found:
            candidates.append(found)
    seen: set[str] = set()
    for candidate in candidates:
        normalized = candidate.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        return {
            "status": "available",
            "command": [candidate],
            "path": candidate,
            "detail": "Python is available for BMW pipeline script invocation.",
        }
    return {
        "status": "missing",
        "command": [],
        "path": "",
        "detail": "No Python launcher was found for BMW pipeline script invocation.",
    }


def _python_check() -> dict[str, str]:
    payload = _python_command_payload()
    if payload["status"] == "available":
        return _check(
            key="bmw_pipeline_python",
            label="BMW pipeline Python",
            status="available",
            detail=str(payload.get("detail", "")),
            path=str(payload.get("path", "")),
        )
    return _check(
        key="bmw_pipeline_python",
        label="BMW pipeline Python",
        status="missing",
        detail=str(payload.get("detail", "")),
        path=str(payload.get("path", "")),
        remediation=f"Install Python launcher support or set {BMW_PIPELINE_PYTHON_ENV} to the BMW pipeline Python.",
    )


def _disk_space_check(workspace: Path, min_free_bytes: int) -> dict[str, str]:
    target = workspace / "Cars" / "size_analysis"
    probe_root = _existing_parent(target)
    try:
        usage = shutil.disk_usage(probe_root)
    except OSError as exc:
        return _check(
            key="disk_space",
            label="size_analysis disk headroom",
            status="failed",
            detail=f"Could not read disk space for {probe_root}: {exc}",
            path=target,
            remediation="Verify the local SVN workspace path is accessible.",
        )
    free_bytes = int(usage.free)
    if free_bytes < min_free_bytes:
        return _check(
            key="disk_space",
            label="size_analysis disk headroom",
            status="missing",
            detail=f"{free_bytes} bytes free; {min_free_bytes} bytes required.",
            path=target,
            remediation="Free local disk space before running export.",
        )
    return _check(
        key="disk_space",
        label="size_analysis disk headroom",
        status="available",
        detail=f"{free_bytes} bytes free; {min_free_bytes} bytes required.",
        path=target,
    )


def check_delivery_workbook_generation_environment(
    *,
    profile_id: str,
    workspace: Path | str,
    bmw_root: Path | str | None = None,
    min_free_bytes: int = GENERATE_WORKBOOK_MIN_FREE_BYTES,
) -> dict[str, Any]:
    workspace_path = Path(workspace).resolve()
    clean_profile = _clean_profile(profile_id)
    repo_check, repo_root = _digital_repo_check(bmw_root)
    checks = [
        repo_check,
        _python_check(),
        _tool_check("raco.exe", "RaCo"),
        _tool_check("RaCoHeadless.exe", "RaCoHeadless"),
        _tool_check("blender.exe", "Blender"),
        _disk_space_check(workspace_path, min_free_bytes),
    ]
    can_run = all(check["status"] == "available" for check in checks)
    target_path = workspace_path / "Cars" / "size_analysis"
    return {
        "profile_id": clean_profile,
        "workspace": str(workspace_path),
        "bmw_root": str(repo_root or ""),
        "target_write_path": str(target_path),
        "estimated_size_bytes": min_free_bytes,
        "status": "available" if can_run else "failed",
        "can_run": can_run,
        "checks": checks,
        "confirmation_message": (
            f"This will run the BMW pipeline for {clean_profile}. May take several minutes and writes to your "
            f"local SVN working copy at `{target_path}`. Continue?"
        ),
        "disabled_reason": "" if can_run else "One or more environment pre-flight checks failed.",
    }


def resolve_delivery_workbook_generation_command(
    *,
    profile_id: str,
    bmw_root: Path | str,
) -> dict[str, Any]:
    root = Path(bmw_root).resolve()
    clean_profile = _clean_profile(profile_id)
    python_payload = _python_command_payload()
    if python_payload["status"] != "available":
        return {
            "status": "missing",
            "strategy": "none",
            "command": [],
            "cwd": str(root),
            "script_path": "",
            "summary": str(python_payload.get("detail", "No Python launcher was found.")),
        }
    python_command = list(python_payload["command"])
    car_manager = root / "ci" / "scripts" / "car_manager.py"
    if car_manager.is_file():
        return {
            "status": "available",
            "strategy": "car_manager_export",
            "command": [*python_command, str(car_manager), "export", clean_profile],
            "cwd": str(root),
            "script_path": str(car_manager),
        }
    legacy = root / "ci" / "scripts" / "test" / "main.py"
    if legacy.is_file():
        return {
            "status": "available",
            "strategy": "legacy_test_main_export",
            "command": [*python_command, str(legacy), "export", clean_profile],
            "cwd": str(root),
            "script_path": str(legacy),
        }
    return {
        "status": "missing",
        "strategy": "none",
        "command": [],
        "cwd": str(root),
        "script_path": "",
        "summary": "No supported BMW pipeline export script was found.",
    }


@dataclass
class DeliveryWorkbookGenerationJob:
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


def _elapsed_label(elapsed_seconds: float) -> str:
    elapsed = max(0, int(elapsed_seconds))
    minutes, seconds = divmod(elapsed, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _tail_lines(path: Path, limit: int = GENERATION_STDOUT_TAIL_LINES) -> list[str]:
    text = _tail_text(path)
    if not text:
        return []
    return text.splitlines()[-limit:]


def _tail_text(path: Path, limit: int = GENERATION_STDOUT_TAIL_BYTES) -> str:
    if not path.is_file():
        return ""
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    return data[-limit:].decode("utf-8", errors="replace")


def _size_label(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    kib = size_bytes / 1024
    if kib < 1024:
        return f"{kib:.0f} KB"
    mib = kib / 1024
    return f"{mib:.1f} MB"


def _delivery_workbook_output_dir(workspace: Path) -> Path:
    return workspace / "Cars" / "size_analysis"


def _file_activity(workspace: Path, started_wall_time: float, limit: int = GENERATION_FILE_ACTIVITY_LIMIT) -> list[dict[str, Any]]:
    output_dir = _delivery_workbook_output_dir(workspace)
    if not output_dir.is_dir():
        return []
    entries: list[tuple[float, dict[str, Any]]] = []
    threshold = started_wall_time - 1.0
    for path in output_dir.rglob("*"):
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
        relative = str(path.relative_to(output_dir))
        size_label = _size_label(int(stat.st_size))
        entries.append(
            (
                last_activity,
                {
                    "event": event,
                    "path": str(path),
                    "relative_path": relative,
                    "size_bytes": int(stat.st_size),
                    "size_label": size_label,
                    "summary": f"{event.title()} `{relative}` ({size_label})",
                },
            )
        )
    return [item for _timestamp, item in sorted(entries, key=lambda pair: pair[0], reverse=True)[:limit]]


def _generation_progress_payload(job: DeliveryWorkbookGenerationJob, *, elapsed_seconds: float) -> dict[str, Any]:
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
        "typical_range": GENERATION_TYPICAL_RANGE_LABEL,
        "timed_out": False,
        "canceled": False,
        "summary": "BMW pipeline export running.",
        "stdout_tail": _tail_text(job.stdout_path),
        "stdout_tail_lines": _tail_lines(job.stdout_path),
        "stderr_tail": _tail_text(job.stderr_path),
        "stdout_path": str(job.stdout_path),
        "stderr_path": str(job.stderr_path),
        "file_activity": _file_activity(job.workspace, job.started_wall_time),
        "preflight": job.preflight,
        "recorded_by_tool": True,
        "is_approval": False,
    }


def _generation_result(
    job: DeliveryWorkbookGenerationJob,
    *,
    exit_code: int,
    status: str,
    summary: str,
    timed_out: bool = False,
    canceled: bool = False,
) -> dict[str, Any]:
    checklist_payload: dict[str, Any] = {}
    if exit_code == 0 and not timed_out and not canceled:
        try:
            checklist_payload = read_delivery_checklist(profile_id=job.profile_id, workspace=job.workspace)
        except Exception as exc:  # noqa: BLE001
            checklist_payload = {"status": "failed", "summary": f"delivery checklist could not be re-read: {exc}"}
        if checklist_payload.get("status") == "available":
            status = "available"
            summary = str(checklist_payload.get("summary", "Delivery workbook generated and available."))
        elif status == "available":
            status = "incomplete"
            summary = (
                "BMW pipeline exited 0, but the delivery workbook is still unavailable. "
                f"{checklist_payload.get('summary', '')}".strip()
            )
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
        "typical_range": GENERATION_TYPICAL_RANGE_LABEL,
        "timed_out": timed_out,
        "canceled": canceled,
        "summary": summary,
        "stdout_tail": _tail_text(job.stdout_path),
        "stdout_tail_lines": _tail_lines(job.stdout_path),
        "stderr_tail": _tail_text(job.stderr_path),
        "stdout_path": str(job.stdout_path),
        "stderr_path": str(job.stderr_path),
        "file_activity": _file_activity(job.workspace, job.started_wall_time),
        "preflight": job.preflight,
        "checklist_status": str(checklist_payload.get("status", "")),
        "checklist_summary": str(checklist_payload.get("summary", "")),
        "recorded_by_tool": True,
        "is_approval": False,
    }


def start_delivery_workbook_generation(
    *,
    profile_id: str,
    workspace: Path | str,
    operator_confirmed: bool,
    bmw_root: Path | str | None = None,
    timeout_seconds: int = GENERATE_WORKBOOK_TIMEOUT_SECONDS,
) -> DeliveryWorkbookGenerationJob:
    if not operator_confirmed:
        raise ValueError("Operator confirmation is required before running BMW pipeline export.")
    workspace_path = Path(workspace).resolve()
    clean_profile = _clean_profile(profile_id)
    preflight = check_delivery_workbook_generation_environment(
        profile_id=clean_profile,
        workspace=workspace_path,
        bmw_root=bmw_root,
    )
    if not preflight["can_run"]:
        raise RuntimeError("Environment pre-flight checks must pass before running BMW pipeline export.")
    repo_root = Path(str(preflight["bmw_root"])).resolve()
    command_payload = resolve_delivery_workbook_generation_command(profile_id=clean_profile, bmw_root=repo_root)
    if command_payload["status"] != "available":
        raise FileNotFoundError(str(command_payload.get("summary", "No supported BMW pipeline export script was found.")))
    log_root = workspace_path / "operator_state" / "delivery_workbook_generation"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stdout_path = log_root / f"{clean_profile}-{stamp}.stdout.log"
    stderr_path = log_root / f"{clean_profile}-{stamp}.stderr.log"
    ensure_parent(stdout_path)
    env = os.environ.copy()
    env[DIGITAL_3D_CAR_REPO_ENV] = str(repo_root)
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
    return DeliveryWorkbookGenerationJob(
        profile_id=clean_profile,
        workspace=workspace_path,
        bmw_root=repo_root,
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


def poll_delivery_workbook_generation(job: DeliveryWorkbookGenerationJob) -> dict[str, Any] | None:
    if job.completed:
        return _generation_result(job, exit_code=job.process.returncode or 0, status="unknown", summary="Job already completed.")
    exit_code = job.process.poll()
    elapsed = time.monotonic() - job.started_monotonic
    if exit_code is None and elapsed < job.timeout_seconds:
        return _generation_progress_payload(job, elapsed_seconds=elapsed)
    if exit_code is None:
        job.process.terminate()
        try:
            job.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            job.process.kill()
            job.process.wait(timeout=5)
        job.completed = True
        return _generation_result(
            job,
            exit_code=job.process.returncode if job.process.returncode is not None else -1,
            status="failed",
            summary=f"BMW pipeline export timed out after {job.timeout_seconds} seconds.",
            timed_out=True,
        )
    job.completed = True
    return _generation_result(
        job,
        exit_code=exit_code,
        status="available" if exit_code == 0 else "failed",
        summary=(
            "BMW pipeline export completed. Re-reading delivery workbook evidence."
            if exit_code == 0
            else f"BMW pipeline export failed with exit code {exit_code}."
        ),
    )


def cancel_delivery_workbook_generation(job: DeliveryWorkbookGenerationJob) -> dict[str, Any]:
    if job.process.poll() is None:
        job.process.terminate()
        try:
            job.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            job.process.kill()
            job.process.wait(timeout=5)
    job.completed = True
    return _generation_result(
        job,
        exit_code=job.process.returncode if job.process.returncode is not None else -1,
        status="failed",
        summary="BMW pipeline export canceled by operator.",
        canceled=True,
    )
