"""Background job dataclasses for long-running dashboard actions, plus the
review-package build, Batch Full QA Pass, and Quality-Hero report process
orchestration that drives them.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from sg_preflight.dashboard_workflows.state_bridge import _with_main_globals


_BUILD_PACKAGE_TIMEOUT_SECONDS = 600
_BUILD_PACKAGE_STDOUT_TAIL_LINES = 20
_BUILD_PACKAGE_STDOUT_TAIL_BYTES = 2000
_BUILD_PACKAGE_FILE_ACTIVITY_LIMIT = 20
_BUILD_PACKAGE_TYPICAL_RANGE_LABEL = "typical 1-5 min"
_QUALITY_HERO_REPORT_TIMEOUT_SECONDS = 600
_BATCH_FULL_QA_TIMEOUT_SECONDS = 600
_BATCH_FULL_QA_TYPICAL_RANGE_LABEL = "Typical 1-3 min per profile"


# --- Background job dataclasses ---
@dataclass
class ReviewPackageBuildJob:
    ticket_id: str
    profile_id: str
    workspace: Path
    process: subprocess.Popen[bytes]
    command: list[str]
    stdout_path: Path
    stderr_path: Path
    started_monotonic: float
    started_wall_time: float
    timeout_seconds: int
    completed: bool = False
    result_payload: dict[str, Any] | None = None


@dataclass
class BatchFullQaPassJob:
    profile_ids: list[str]
    workspace: Path
    bmw_root: str
    log_root: Path
    timeout_seconds: int
    trusted_tool_mode: bool
    current_index: int = 0
    process: subprocess.Popen[bytes] | None = None
    command: list[str] = field(default_factory=list)
    stdout_path: Path | None = None
    stderr_path: Path | None = None
    current_started_monotonic: float = 0.0
    current_started_wall_time: float = 0.0
    batch_started_monotonic: float = 0.0
    batch_started_wall_time: float = 0.0
    results: list[dict[str, Any]] = field(default_factory=list)
    cancel_after_current: bool = False
    completed: bool = False
    result_payload: dict[str, Any] | None = None


# --- Review package build, Batch Full QA Pass, and Quality-Hero report process orchestration ---
def _validate_review_package_inputs(workspace: Path | str, profile_id: str, ticket_id: str) -> tuple[Path, str, str]:
    clean_ticket = ticket_id.strip()
    if not clean_ticket:
        raise ValueError("Ticket ID required to build a review package.")
    clean_profile = profile_id.strip()
    if not clean_profile:
        raise ValueError("Profile ID required to build a review package.")
    return Path(workspace).resolve(), clean_profile, clean_ticket


def _dashboard_review_package_command(*, workspace: Path, profile_id: str, ticket_id: str) -> list[str]:
    return sgfx_cli_command(
        "ticket-review",
        ticket_id,
        "--workspace",
        str(workspace),
        "--profile",
        profile_id,
        "--json",
    )


def _build_tail_text(path: Path, limit: int = _BUILD_PACKAGE_STDOUT_TAIL_BYTES) -> str:
    if not path.is_file():
        return ""
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    return data[-limit:].decode("utf-8", errors="replace")


def _build_tail_lines(path: Path, limit: int = _BUILD_PACKAGE_STDOUT_TAIL_LINES) -> list[str]:
    text = _build_tail_text(path)
    if not text:
        return []
    return text.splitlines()[-limit:]


def _build_combined_tail_lines(stdout_path: Path, stderr_path: Path) -> list[str]:
    lines = list(_build_tail_lines(stdout_path))
    lines.extend(f"stderr: {line}" for line in _build_tail_lines(stderr_path))
    return lines[-_BUILD_PACKAGE_STDOUT_TAIL_LINES:]


def _size_label(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    kib = size_bytes / 1024
    if kib < 1024:
        return f"{kib:.0f} KB"
    mib = kib / 1024
    return f"{mib:.1f} MB"


def _build_package_file_activity(
    workspace: Path,
    started_wall_time: float,
    limit: int = _BUILD_PACKAGE_FILE_ACTIVITY_LIMIT,
) -> list[dict[str, Any]]:
    roots = [workspace / "out", workspace / "operator_state" / "review_package_build"]
    entries: list[tuple[float, dict[str, Any]]] = []
    threshold = started_wall_time - 1.0
    seen: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        candidates = [root]
        if root.is_dir():
            try:
                candidates.extend(path for path in root.rglob("*") if path.is_file())
            except OSError:
                continue
        for path in candidates:
            normalized = str(path).casefold()
            if normalized in seen or not path.exists():
                continue
            seen.add(normalized)
            try:
                stat = path.stat()
            except OSError:
                continue
            last_activity = max(stat.st_mtime, stat.st_ctime)
            if last_activity < threshold:
                continue
            event = "created" if stat.st_ctime >= threshold else "modified"
            size_label = _size_label(int(stat.st_size)) if path.is_file() else "folder"
            try:
                relative = str(path.relative_to(workspace))
            except ValueError:
                relative = path.name
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


def _elapsed_label(elapsed_seconds: float) -> str:
    elapsed = max(0, int(elapsed_seconds))
    minutes, seconds = divmod(elapsed, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _dashboard_full_qa_pass_command(
    *,
    workspace: Path,
    profile_id: str,
    bmw_root: str = "",
    trusted_tool_mode: bool = True,
) -> list[str]:
    command = sgfx_cli_command(
        "full-qa-pass",
        "run",
        "--profile",
        profile_id,
        "--workspace",
        str(workspace),
        "--format",
        "json",
    )
    if bmw_root:
        command.extend(["--bmw-root", bmw_root])
    command.append("--automatic-mode" if trusted_tool_mode else "--manual-mode")
    return command


def _batch_profile_safe_name(profile_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", profile_id.strip().upper() or "PROFILE")


def _read_json_payload(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return {}
    if not text:
        return {}
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _batch_step_payload(payload: dict[str, Any], step_id: str) -> dict[str, Any]:
    for step in payload.get("steps", []):
        if isinstance(step, dict) and str(step.get("id", "")) == step_id:
            step_payload = step.get("payload", {})
            return step_payload if isinstance(step_payload, dict) else {}
    return {}


def _batch_profile_result(
    job: BatchFullQaPassJob,
    *,
    profile_id: str,
    exit_code: int,
    timed_out: bool = False,
) -> dict[str, Any]:
    elapsed_seconds = time.monotonic() - job.current_started_monotonic
    payload = _read_json_payload(job.stdout_path)
    status = str(payload.get("status", "failed" if exit_code else "unknown"))
    if exit_code != 0:
        outcome = "failed"
    elif timed_out:
        outcome = "failed"
    else:
        outcome = status if status in {"passed", "incomplete", "failed"} else "recorded"
    risk_payload = _batch_step_payload(payload, "risk-score")
    risk_score = risk_payload.get("risk_score", risk_payload.get("score", "unknown"))
    pending_review_count = len(
        [
            step
            for step in payload.get("steps", [])
            if isinstance(step, dict) and str(step.get("status", "")) not in {"passed", "skipped"}
        ]
    )
    progress = payload.get("progress", {}) if isinstance(payload.get("progress"), dict) else {}
    summary = str(payload.get("summary", "") or f"Full QA Pass exited {exit_code} for {profile_id}.")
    result = {
        "profile_id": profile_id,
        "outcome": outcome,
        "status": status,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "risk_score": str(risk_score),
        "pending_review_count": pending_review_count,
        "completed_steps": int(progress.get("completed_steps", 0) or 0),
        "total_steps": int(progress.get("total_steps", 0) or 0),
        "elapsed_seconds": int(max(0, elapsed_seconds)),
        "elapsed_label": _elapsed_label(elapsed_seconds),
        "summary": summary,
        "stdout_path": str(job.stdout_path or ""),
        "stderr_path": str(job.stderr_path or ""),
        "stdout_tail_lines": _build_combined_tail_lines(job.stdout_path or Path(), job.stderr_path or Path()),
        "profile_link": f"?profile={quote(profile_id)}&full_qa_run=1",
        "manual_review_required": True,
        "is_approval": False,
    }
    append_activity_entry(
        job.workspace,
        verb="ran",
        surface="batch-full-qa-pass",
        profile=profile_id,
        outcome="ok" if exit_code == 0 and not timed_out else "error",
        note=f"Batch Full QA Pass subprocess completed for {profile_id} with exit {exit_code}.",
    )
    return result


def _batch_progress_payload(job: BatchFullQaPassJob, *, summary: str = "") -> dict[str, Any]:
    total = len(job.profile_ids)
    current_profile = job.profile_ids[job.current_index] if job.current_index < total else ""
    elapsed = time.monotonic() - (job.current_started_monotonic or job.batch_started_monotonic)
    completed = len(job.results)
    return {
        "status": "running",
        "completed": False,
        "profiles": list(job.profile_ids),
        "current_profile": current_profile,
        "current_index": min(job.current_index + 1, total),
        "total_profiles": total,
        "completed_profiles": completed,
        "percent": int(round((completed / max(1, total)) * 100)),
        "elapsed_seconds": int(max(0, elapsed)),
        "elapsed_label": _elapsed_label(elapsed),
        "typical_range": _BATCH_FULL_QA_TYPICAL_RANGE_LABEL,
        "cancel_after_current": bool(job.cancel_after_current),
        "summary": summary or f"Running profile {min(job.current_index + 1, total)} of {total}: {current_profile}.",
        "results": list(job.results),
        "stdout_tail_lines": _build_combined_tail_lines(job.stdout_path or Path(), job.stderr_path or Path()),
        "stdout_path": str(job.stdout_path or ""),
        "stderr_path": str(job.stderr_path or ""),
        "manual_review_required": True,
        "is_approval": False,
    }


def _complete_batch_full_qa_pass(job: BatchFullQaPassJob, *, canceled: bool = False) -> dict[str, Any]:
    failed_count = len([item for item in job.results if str(item.get("exit_code", "")) != "0"])
    incomplete_count = len([item for item in job.results if str(item.get("outcome", "")) == "incomplete"])
    if canceled:
        status = "incomplete"
        summary = f"Batch stopped after {len(job.results)}/{len(job.profile_ids)} profile(s)."
    elif failed_count:
        status = "failed"
        summary = f"Batch completed with {failed_count} failed profile subprocess(es)."
    elif incomplete_count:
        status = "incomplete"
        summary = f"Batch completed; {incomplete_count} profile(s) still need operator review."
    else:
        status = "passed"
        summary = f"Batch completed for {len(job.results)} profile(s)."
    payload = {
        "status": status,
        "completed": True,
        "profiles": list(job.profile_ids),
        "current_profile": "",
        "current_index": len(job.profile_ids),
        "total_profiles": len(job.profile_ids),
        "completed_profiles": len(job.results),
        "percent": 100 if job.profile_ids else 0,
        "typical_range": _BATCH_FULL_QA_TYPICAL_RANGE_LABEL,
        "summary": summary,
        "results": list(job.results),
        "canceled": canceled,
        "manual_review_required": True,
        "is_approval": False,
    }
    job.completed = True
    job.result_payload = payload
    return payload


def _start_batch_profile_process(job: BatchFullQaPassJob) -> None:
    profile_id = job.profile_ids[job.current_index]
    profile_token = _batch_profile_safe_name(profile_id)
    stdout_path = job.log_root / f"{job.current_index + 1:02d}-{profile_token}.stdout.log"
    stderr_path = job.log_root / f"{job.current_index + 1:02d}-{profile_token}.stderr.log"
    ensure_parent(stdout_path)
    command = _dashboard_full_qa_pass_command(
        workspace=job.workspace,
        profile_id=profile_id,
        bmw_root=job.bmw_root,
        trusted_tool_mode=job.trusted_tool_mode,
    )
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault("PYTHONIOENCODING", "utf-8")
    if not getattr(sys, "frozen", False):
        repo_root = Path(__file__).resolve().parents[1]
        existing_pythonpath = str(env.get("PYTHONPATH", "") or "")
        env["PYTHONPATH"] = (
            f"{repo_root}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else str(repo_root)
        )
    job.command = command
    job.stdout_path = stdout_path
    job.stderr_path = stderr_path
    job.current_started_monotonic = time.monotonic()
    job.current_started_wall_time = time.time()
    with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
        job.process = subprocess.Popen(
            command,
            cwd=job.workspace,
            stdin=subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=stderr_handle,
            env=env,
            **hidden_subprocess_kwargs(),
        )


def start_dashboard_batch_full_qa_pass(
    *,
    workspace: Path | str,
    profile_ids: list[str],
    bmw_root: Path | str | None = None,
    trusted_tool_mode: bool = True,
    timeout_seconds: int = _BATCH_FULL_QA_TIMEOUT_SECONDS,
) -> BatchFullQaPassJob:
    workspace_path = Path(workspace).resolve()
    clean_profiles: list[str] = []
    for profile in profile_ids:
        clean = str(profile or "").strip().upper()
        if clean and clean not in clean_profiles:
            clean_profiles.append(clean)
    if not clean_profiles:
        raise ValueError("Select at least one profile before starting the batch.")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_root = workspace_path / "operator_state" / "batch_full_qa_pass" / stamp
    job = BatchFullQaPassJob(
        profile_ids=clean_profiles,
        workspace=workspace_path,
        bmw_root=str(Path(bmw_root).resolve()) if bmw_root else "",
        log_root=log_root,
        timeout_seconds=timeout_seconds,
        trusted_tool_mode=trusted_tool_mode,
        batch_started_monotonic=time.monotonic(),
        batch_started_wall_time=time.time(),
    )
    _start_batch_profile_process(job)
    append_activity_entry(
        workspace_path,
        verb="ran",
        surface="batch-full-qa-pass",
        profile=",".join(clean_profiles),
        outcome="ok",
        note=f"Batch Full QA Pass started for {len(clean_profiles)} profile(s).",
    )
    return job


def request_cancel_dashboard_batch_full_qa_pass(job: BatchFullQaPassJob) -> dict[str, Any]:
    job.cancel_after_current = True
    return _batch_progress_payload(job, summary="Cancel requested; current profile will finish first.")


def poll_dashboard_batch_full_qa_pass(job: BatchFullQaPassJob) -> dict[str, Any] | None:
    if job.completed:
        return job.result_payload or _complete_batch_full_qa_pass(job)
    if job.process is None:
        if job.current_index >= len(job.profile_ids):
            return _complete_batch_full_qa_pass(job)
        _start_batch_profile_process(job)
        return _batch_progress_payload(job)
    exit_code = job.process.poll()
    elapsed = time.monotonic() - job.current_started_monotonic
    if exit_code is None and elapsed < job.timeout_seconds:
        return _batch_progress_payload(job)
    timed_out = False
    if exit_code is None:
        timed_out = True
        job.process.terminate()
        try:
            job.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            job.process.kill()
            job.process.wait(timeout=5)
        exit_code = job.process.returncode if job.process.returncode is not None else -1
    current_profile = job.profile_ids[job.current_index]
    job.results.append(_batch_profile_result(job, profile_id=current_profile, exit_code=exit_code, timed_out=timed_out))
    job.current_index += 1
    job.process = None
    if job.cancel_after_current or job.current_index >= len(job.profile_ids):
        return _complete_batch_full_qa_pass(job, canceled=job.cancel_after_current and job.current_index < len(job.profile_ids))
    _start_batch_profile_process(job)
    return _batch_progress_payload(
        job,
        summary=f"Started next profile {job.current_index + 1} of {len(job.profile_ids)}: {job.profile_ids[job.current_index]}.",
    )


def _review_build_progress_payload(job: ReviewPackageBuildJob, *, elapsed_seconds: float) -> dict[str, Any]:
    return {
        "ticket_id": job.ticket_id,
        "profile_id": job.profile_id,
        "workspace": str(job.workspace),
        "status": "running",
        "outcome": "running",
        "completed": False,
        "exit_code": None,
        "command": list(job.command),
        "timeout_seconds": job.timeout_seconds,
        "elapsed_seconds": int(max(0, elapsed_seconds)),
        "elapsed_label": _elapsed_label(elapsed_seconds),
        "typical_range": _BUILD_PACKAGE_TYPICAL_RANGE_LABEL,
        "timed_out": False,
        "canceled": False,
        "summary": "Build review package running.",
        "stdout_tail": _build_tail_text(job.stdout_path),
        "stdout_tail_lines": _build_combined_tail_lines(job.stdout_path, job.stderr_path),
        "stderr_tail": _build_tail_text(job.stderr_path),
        "stdout_path": str(job.stdout_path),
        "stderr_path": str(job.stderr_path),
        "file_activity": _build_package_file_activity(job.workspace, job.started_wall_time),
        "recorded_by_tool": True,
        "is_approval": False,
    }


def _complete_review_package_build(
    job: ReviewPackageBuildJob,
    *,
    exit_code: int,
    timed_out: bool = False,
    canceled: bool = False,
) -> dict[str, Any]:
    elapsed_seconds = time.monotonic() - job.started_monotonic
    outcome = "recorded" if exit_code == 0 and not timed_out and not canceled else "failed"
    if exit_code == 0 and not timed_out and not canceled:
        _write_active_ticket_state(job.workspace, job.ticket_id, source="build-review-package")
    append_activity_entry(
        job.workspace,
        verb="ran",
        surface="daily-digest",
        profile=job.profile_id,
        outcome="ok" if outcome == "recorded" else "error",
        note=f"Build review package for {job.ticket_id}",
    )
    if timed_out:
        summary = f"Build review package timed out after {job.timeout_seconds} seconds."
    elif canceled:
        summary = "Build review package canceled by operator."
    elif exit_code == 0:
        summary = "Build review package completed. Refresh to reload digest evidence."
    else:
        summary = f"Build review package failed with exit code {exit_code}."
    payload = {
        "ticket_id": job.ticket_id,
        "profile_id": job.profile_id,
        "workspace": str(job.workspace),
        "status": outcome,
        "outcome": outcome,
        "completed": True,
        "exit_code": exit_code,
        "command": list(job.command),
        "timeout_seconds": job.timeout_seconds,
        "elapsed_seconds": int(max(0, elapsed_seconds)),
        "elapsed_label": _elapsed_label(elapsed_seconds),
        "typical_range": _BUILD_PACKAGE_TYPICAL_RANGE_LABEL,
        "timed_out": timed_out,
        "canceled": canceled,
        "summary": summary,
        "stdout_tail": _build_tail_text(job.stdout_path),
        "stdout_tail_lines": _build_combined_tail_lines(job.stdout_path, job.stderr_path),
        "stderr_tail": _build_tail_text(job.stderr_path),
        "stdout_path": str(job.stdout_path),
        "stderr_path": str(job.stderr_path),
        "file_activity": _build_package_file_activity(job.workspace, job.started_wall_time),
        "recorded_by_tool": True,
        "is_approval": False,
    }
    job.completed = True
    job.result_payload = payload
    return payload


def start_dashboard_review_package_build(
    *,
    workspace: Path | str,
    profile_id: str,
    ticket_id: str,
    operator_confirmed: bool,
    timeout_seconds: int = _BUILD_PACKAGE_TIMEOUT_SECONDS,
) -> ReviewPackageBuildJob:
    if not operator_confirmed:
        raise ValueError("Operator confirmation is required before building a review package.")
    workspace_path, clean_profile, clean_ticket = _validate_review_package_inputs(workspace, profile_id, ticket_id)
    command = _dashboard_review_package_command(
        workspace=workspace_path,
        profile_id=clean_profile,
        ticket_id=clean_ticket,
    )
    log_root = workspace_path / "operator_state" / "review_package_build"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stdout_path = log_root / f"{clean_ticket}-{clean_profile}-{stamp}.stdout.log"
    stderr_path = log_root / f"{clean_ticket}-{clean_profile}-{stamp}.stderr.log"
    ensure_parent(stdout_path)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault("PYTHONIOENCODING", "utf-8")
    started_wall_time = time.time()
    started_monotonic = time.monotonic()
    with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
        process = subprocess.Popen(
            command,
            cwd=workspace_path,
            stdin=subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=stderr_handle,
            env=env,
            **hidden_subprocess_kwargs(),
        )
    return ReviewPackageBuildJob(
        ticket_id=clean_ticket,
        profile_id=clean_profile,
        workspace=workspace_path,
        process=process,
        command=command,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        started_monotonic=started_monotonic,
        started_wall_time=started_wall_time,
        timeout_seconds=timeout_seconds,
    )


def poll_dashboard_review_package_build(job: ReviewPackageBuildJob) -> dict[str, Any] | None:
    if job.completed:
        return job.result_payload or _complete_review_package_build(
            job,
            exit_code=job.process.returncode or 0,
        )
    exit_code = job.process.poll()
    elapsed = time.monotonic() - job.started_monotonic
    if exit_code is None and elapsed < job.timeout_seconds:
        return _review_build_progress_payload(job, elapsed_seconds=elapsed)
    if exit_code is None:
        job.process.terminate()
        try:
            job.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            job.process.kill()
            job.process.wait(timeout=5)
        return _complete_review_package_build(
            job,
            exit_code=job.process.returncode if job.process.returncode is not None else -1,
            timed_out=True,
        )
    return _complete_review_package_build(job, exit_code=exit_code)


def cancel_dashboard_review_package_build(job: ReviewPackageBuildJob) -> dict[str, Any]:
    if job.process.poll() is None:
        job.process.terminate()
        try:
            job.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            job.process.kill()
            job.process.wait(timeout=5)
    return _complete_review_package_build(
        job,
        exit_code=job.process.returncode if job.process.returncode is not None else -1,
        canceled=True,
    )


def build_dashboard_review_package(
    *,
    workspace: Path | str,
    profile_id: str,
    ticket_id: str,
    timeout_seconds: int = _BUILD_PACKAGE_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    clean_ticket = ticket_id.strip()
    if not clean_ticket:
        raise ValueError("Ticket ID required to build a review package.")
    clean_profile = profile_id.strip()
    if not clean_profile:
        raise ValueError("Profile ID required to build a review package.")
    workspace_path = Path(workspace).resolve()
    command = _dashboard_review_package_command(
        workspace=workspace_path,
        profile_id=clean_profile,
        ticket_id=clean_ticket,
    )
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
        **hidden_subprocess_kwargs(),
    )
    outcome = "recorded" if completed.returncode == 0 else "failed"
    if completed.returncode == 0:
        _write_active_ticket_state(workspace_path, clean_ticket, source="build-review-package")
    append_activity_entry(
        workspace_path,
        verb="ran",
        surface="daily-digest",
        profile=clean_profile,
        outcome="ok" if completed.returncode == 0 else "error",
        note=f"Build review package for {clean_ticket}",
    )
    return {
        "ticket_id": clean_ticket,
        "profile_id": clean_profile,
        "workspace": str(workspace_path),
        "exit_code": completed.returncode,
        "outcome": outcome,
        "stdout_tail": completed.stdout[-2000:] if completed.stdout else "",
        "stderr_tail": completed.stderr[-2000:] if completed.stderr else "",
        "recorded_by_tool": True,
    }


def _quality_hero_report_output_root(workspace: Path, profile_id: str) -> Path:
    safe_profile = re.sub(r"[^A-Za-z0-9_.-]+", "_", profile_id.strip().lower() or "profile")
    return operator_ui_root(workspace) / "quality-hero-report" / safe_profile


def _dashboard_quality_hero_report_command(
    *,
    workspace: Path,
    profile_id: str,
    ticket_id: str,
    output_root: Path,
) -> list[str]:
    command = sgfx_cli_command(
        "quality-hero-report",
        "generate",
        "--profile",
        profile_id,
        "--workspace",
        str(workspace),
        "--output-root",
        str(output_root),
        "--format",
        "json",
    )
    if ticket_id:
        command.extend(["--ticket", ticket_id])
    return command


def build_dashboard_quality_hero_report(
    *,
    workspace: Path | str,
    profile_id: str,
    ticket_id: str = "",
    output_root: Path | str | None = None,
    timeout_seconds: int = _QUALITY_HERO_REPORT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    clean_profile = profile_id.strip()
    if not clean_profile:
        raise ValueError("Profile ID required to build a Quality-Hero report.")
    clean_ticket = ticket_id.strip().upper()
    workspace_path = Path(workspace).resolve()
    output_path = Path(output_root).resolve() if output_root else _quality_hero_report_output_root(workspace_path, clean_profile)
    command = _dashboard_quality_hero_report_command(
        workspace=workspace_path,
        profile_id=clean_profile,
        ticket_id=clean_ticket,
        output_root=output_path,
    )
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
        **hidden_subprocess_kwargs(),
    )
    payload: dict[str, Any] = {}
    if completed.stdout.strip():
        try:
            loaded = json.loads(completed.stdout)
            payload = loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            payload = {}
    outcome = "recorded" if completed.returncode == 0 else "failed"
    if completed.returncode == 0 and clean_ticket:
        _write_active_ticket_state(workspace_path, clean_ticket, source="quality-hero-report")
    append_activity_entry(
        workspace_path,
        verb="ran",
        surface="daily-digest",
        profile=clean_profile,
        outcome="ok" if completed.returncode == 0 else "error",
        note=f"Build Quality-Hero report for {clean_ticket or 'no ticket'}",
    )
    markdown_path = str(payload.get("markdown_path", "") or "")
    html_path = str(payload.get("html_path", "") or "")
    json_path = str(payload.get("json_path", "") or "")
    return {
        "ticket_id": clean_ticket,
        "profile_id": clean_profile,
        "workspace": str(workspace_path),
        "output_root": str(output_path),
        "exit_code": completed.returncode,
        "outcome": outcome,
        "status": outcome,
        "command": command,
        "markdown_path": markdown_path,
        "html_path": html_path,
        "json_path": json_path,
        "markdown_size_bytes": Path(markdown_path).stat().st_size if markdown_path and Path(markdown_path).is_file() else 0,
        "html_size_bytes": Path(html_path).stat().st_size if html_path and Path(html_path).is_file() else 0,
        "json_size_bytes": Path(json_path).stat().st_size if json_path and Path(json_path).is_file() else 0,
        "stdout_tail": completed.stdout[-2000:] if completed.stdout else "",
        "stderr_tail": completed.stderr[-2000:] if completed.stderr else "",
        "recorded_by_tool": True,
        "is_approval": False,
    }


_validate_review_package_inputs = _with_main_globals(_validate_review_package_inputs)
_dashboard_review_package_command = _with_main_globals(_dashboard_review_package_command)
_build_tail_text = _with_main_globals(_build_tail_text)
_build_tail_lines = _with_main_globals(_build_tail_lines)
_build_combined_tail_lines = _with_main_globals(_build_combined_tail_lines)
_size_label = _with_main_globals(_size_label)
_build_package_file_activity = _with_main_globals(_build_package_file_activity)
_elapsed_label = _with_main_globals(_elapsed_label)
_dashboard_full_qa_pass_command = _with_main_globals(_dashboard_full_qa_pass_command)
_batch_profile_safe_name = _with_main_globals(_batch_profile_safe_name)
_read_json_payload = _with_main_globals(_read_json_payload)
_batch_step_payload = _with_main_globals(_batch_step_payload)
_batch_profile_result = _with_main_globals(_batch_profile_result)
_batch_progress_payload = _with_main_globals(_batch_progress_payload)
_complete_batch_full_qa_pass = _with_main_globals(_complete_batch_full_qa_pass)
_start_batch_profile_process = _with_main_globals(_start_batch_profile_process)
start_dashboard_batch_full_qa_pass = _with_main_globals(start_dashboard_batch_full_qa_pass)
request_cancel_dashboard_batch_full_qa_pass = _with_main_globals(request_cancel_dashboard_batch_full_qa_pass)
poll_dashboard_batch_full_qa_pass = _with_main_globals(poll_dashboard_batch_full_qa_pass)
_review_build_progress_payload = _with_main_globals(_review_build_progress_payload)
_complete_review_package_build = _with_main_globals(_complete_review_package_build)
start_dashboard_review_package_build = _with_main_globals(start_dashboard_review_package_build)
poll_dashboard_review_package_build = _with_main_globals(poll_dashboard_review_package_build)
cancel_dashboard_review_package_build = _with_main_globals(cancel_dashboard_review_package_build)
build_dashboard_review_package = _with_main_globals(build_dashboard_review_package)
_quality_hero_report_output_root = _with_main_globals(_quality_hero_report_output_root)
_dashboard_quality_hero_report_command = _with_main_globals(_dashboard_quality_hero_report_command)
build_dashboard_quality_hero_report = _with_main_globals(build_dashboard_quality_hero_report)
