from __future__ import annotations

from pathlib import Path
import re
import subprocess
import time
from typing import Any, Callable

from sg_preflight.bmw_pipeline_diagnostics import bmw_pipeline_diagnostic_pattern
from sg_preflight.delivery_workbook_generation import _clean_profile
from sg_preflight.screenshot_capture import (
    SCREENSHOT_CAPTURE_TIMEOUT_SECONDS,
    check_screenshot_capture_environment,
    poll_screenshot_capture,
    start_screenshot_capture,
)
from sg_preflight.screenshot_triage import materialize_screenshot_triage
from sg_preflight.subprocess_utils import hidden_subprocess_kwargs


MISSING_ACTUAL_DIAGNOSTIC_ACTION_ID = "missing-actual-diagnostic-chain"
READ_REFRESH_ACTION_ID = "read-refresh-bmw-svn"
RETRY_SCREENSHOT_CAPTURE_ACTION_ID = "retry-screenshot-capture"
ASSET_DOCTOR_ACTION_ID = "asset-doctor"
_ASSET_LITERAL_RE = re.compile(r"""["']([^"']+\.(?:ramses|lua|png|jpg|jpeg|bmp|dds|ktx|ktx2|hdr|exr|glb|gltf|bin|json|yaml|yml))["']""", re.IGNORECASE)


CommandRunner = Callable[[list[str], Path, int], subprocess.CompletedProcess[str]]


def _run_command(command: list[str], cwd: Path, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        **hidden_subprocess_kwargs(),
    )


def _step(step_id: str, label: str, status: str, detail: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": step_id,
        "label": label,
        "status": status,
        "detail": detail,
        "manual_review_required": True,
        "is_approval": False,
        **extra,
    }


def _tail(text: str, limit: int = 4000) -> str:
    clean = str(text or "")
    return clean[-limit:] if len(clean) > limit else clean


def _candidate_reference_paths(reference: str, *, project_root: Path, config_path: Path) -> tuple[Path, ...]:
    raw = Path(reference.replace("/", "\\"))
    if raw.is_absolute():
        return (raw,)
    candidates = [
        config_path.parent / raw,
        project_root / raw,
        project_root / "export" / "tests" / raw,
        project_root.parent / raw,
    ]
    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in unique:
            unique.append(resolved)
    return tuple(unique)


def _asset_doctor(profile_id: str, project_root: Path, missing_keys: tuple[str, ...]) -> dict[str, Any]:
    clean_profile = _clean_profile(profile_id)
    config_path = project_root / "export" / "tests" / "test_config.lua"
    if not config_path.is_file():
        return {
            "status": "missing",
            "summary": "BMW Git test_config.lua was not found; asset references could not be scanned.",
            "config_path": str(config_path),
            "references_checked": [],
            "missing_references": [],
            "manual_review_required": True,
            "is_approval": False,
        }
    try:
        config_text = config_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {
            "status": "unavailable",
            "summary": f"BMW Git test_config.lua could not be read: {exc}",
            "config_path": str(config_path),
            "references_checked": [],
            "missing_references": [],
            "manual_review_required": True,
            "is_approval": False,
        }
    references = tuple(dict.fromkeys(match.group(1).strip() for match in _ASSET_LITERAL_RE.finditer(config_text)))
    checked: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for reference in references:
        candidates = _candidate_reference_paths(reference, project_root=project_root, config_path=config_path)
        found_path = next((path for path in candidates if path.exists()), None)
        record = {
            "reference": reference,
            "status": "available" if found_path is not None else "missing",
            "resolved_path": str(found_path or ""),
            "candidate_paths": [str(path) for path in candidates],
        }
        checked.append(record)
        if found_path is None:
            missing.append(record)
    if missing:
        status = "incomplete"
        summary = f"{len(missing)} referenced asset path(s) were not found for {clean_profile}."
    elif checked:
        status = "available"
        summary = f"{len(checked)} referenced asset path(s) resolved for {clean_profile}."
    else:
        status = "available"
        summary = (
            f"No explicit asset file literals were found in test_config.lua for {clean_profile}; "
            "continue with read-refresh and retry if actuals remain missing."
        )
    return {
        "status": status,
        "summary": summary,
        "config_path": str(config_path),
        "missing_test_keys": list(missing_keys),
        "references_checked": checked,
        "missing_references": missing,
        "manual_review_required": True,
        "is_approval": False,
    }


def _known_pattern_payload(pattern_ids: tuple[str, ...]) -> dict[str, Any]:
    patterns: list[dict[str, Any]] = []
    for pattern_id in pattern_ids:
        pattern = bmw_pipeline_diagnostic_pattern(pattern_id)
        if not pattern:
            continue
        patterns.append(
            {
                "pattern_id": str(pattern.get("pattern_id", pattern_id)),
                "title": str(pattern.get("title", "")),
                "trigger": str(pattern.get("trigger_description", "")),
                "confluence_anchor": str(pattern.get("confluence_anchor", "")),
                "recommended_actions": pattern.get("recommended_actions", []),
            }
        )
    return {
        "status": "available" if patterns else "missing",
        "patterns": patterns,
        "summary": f"{len(patterns)} known diagnostic pattern(s) matched the missing-actual state.",
    }


def _read_refresh_commands(workspace: Path, bmw_root: Path | None) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    if bmw_root and (bmw_root / ".git").exists():
        commands.append(
            {
                "id": "bmw-git-pull",
                "label": "BMW Git read-refresh",
                "command": ["git", "-C", str(bmw_root), "pull", "--ff-only"],
                "cwd": str(bmw_root),
            }
        )
    if (workspace / ".svn").exists():
        commands.append(
            {
                "id": "svn-update",
                "label": "SVN read-refresh",
                "command": ["svn", "update", str(workspace)],
                "cwd": str(workspace),
            }
        )
    return commands


def _run_read_refresh(
    *,
    workspace: Path,
    bmw_root: Path | None,
    command_runner: CommandRunner,
    timeout_seconds: int,
) -> dict[str, Any]:
    commands = _read_refresh_commands(workspace, bmw_root)
    if not commands:
        return {
            "status": "unavailable",
            "summary": "No BMW Git .git directory or SVN .svn directory was found for read-refresh.",
            "commands": [],
            "manual_review_required": True,
            "is_approval": False,
        }
    results: list[dict[str, Any]] = []
    for item in commands:
        command = [str(part) for part in item["command"]]
        cwd = Path(str(item["cwd"]))
        try:
            completed = command_runner(command, cwd, timeout_seconds)
        except (OSError, subprocess.TimeoutExpired) as exc:
            results.append(
                {
                    **item,
                    "status": "failed",
                    "exit_code": -1,
                    "stdout_tail": "",
                    "stderr_tail": str(exc),
                }
            )
            continue
        results.append(
            {
                **item,
                "status": "available" if completed.returncode == 0 else "failed",
                "exit_code": int(completed.returncode),
                "stdout_tail": _tail(completed.stdout),
                "stderr_tail": _tail(completed.stderr),
            }
        )
    failed = [item for item in results if item["status"] != "available"]
    return {
        "status": "failed" if failed else "available",
        "summary": (
            f"{len(results) - len(failed)}/{len(results)} read-refresh command(s) completed."
            if results
            else "No read-refresh command ran."
        ),
        "commands": results,
        "manual_review_required": True,
        "is_approval": False,
    }


def _run_retry_capture(
    *,
    profile_id: str,
    workspace: Path,
    bmw_root: Path | None,
    operator_confirmed_retry_capture: bool,
    timeout_seconds: int,
) -> dict[str, Any]:
    if not operator_confirmed_retry_capture:
        return {
            "status": "confirmation_pending",
            "summary": "Operator confirmation is required before retrying BMW screenshot capture.",
            "manual_review_required": True,
            "is_approval": False,
        }
    job = start_screenshot_capture(
        profile_id=profile_id,
        workspace=workspace,
        bmw_root=bmw_root,
        operator_confirmed=True,
        timeout_seconds=timeout_seconds,
    )
    while True:
        result = poll_screenshot_capture(job)
        if result is not None:
            return result
        time.sleep(1.0)


def run_missing_actual_diagnostic_chain(
    *,
    profile_id: str,
    workspace: Path | str,
    project_root: Path | str,
    output_root: Path | str,
    bmw_root: Path | str | None = None,
    expected_root: Path | str | None = None,
    candidate_roots: tuple[Path | str, ...] = (),
    diff_reference_roots: tuple[Path | str, ...] = (),
    operator_confirmed_read_refresh: bool = False,
    retry_capture: bool = False,
    operator_confirmed_retry_capture: bool = False,
    command_runner: CommandRunner = _run_command,
    read_refresh_timeout_seconds: int = 120,
    retry_timeout_seconds: int = SCREENSHOT_CAPTURE_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    clean_profile = _clean_profile(profile_id)
    workspace_path = Path(workspace).resolve()
    project_path = Path(project_root).resolve()
    output_path = Path(output_root).resolve()
    bmw_path = Path(bmw_root).resolve() if bmw_root else None
    triage_bundle = materialize_screenshot_triage(
        clean_profile,
        project_path,
        output_path / "triage",
        expected_root=Path(expected_root).resolve() if expected_root else None,
        candidate_roots=tuple(Path(item).resolve() for item in candidate_roots),
        diff_reference_roots=tuple(Path(item).resolve() for item in diff_reference_roots),
    )
    missing_pairs = tuple(pair for pair in triage_bundle.report.pairs if pair.classification == "missing_candidate")
    missing_keys = tuple(pair.key for pair in missing_pairs)
    pattern_ids = tuple(
        dict.fromkeys(
            pattern_id
            for pair in missing_pairs
            for pattern_id in getattr(pair, "diagnostic_pattern_ids", ())
            if str(pattern_id).strip()
        )
    )
    preflight = check_screenshot_capture_environment(
        profile_id=clean_profile,
        workspace=workspace_path,
        bmw_root=bmw_path,
    )
    known_patterns = _known_pattern_payload(pattern_ids)
    asset_doctor = _asset_doctor(clean_profile, project_path, missing_keys)
    read_refresh_payload: dict[str, Any]
    if not missing_pairs:
        read_refresh_payload = {
            "status": "skipped",
            "summary": "No missing actual rows were found.",
            "commands": [],
            "manual_review_required": True,
            "is_approval": False,
        }
    elif operator_confirmed_read_refresh:
        read_refresh_payload = _run_read_refresh(
            workspace=workspace_path,
            bmw_root=bmw_path,
            command_runner=command_runner,
            timeout_seconds=read_refresh_timeout_seconds,
        )
    else:
        read_refresh_payload = {
            "status": "confirmation_pending",
            "summary": "Operator confirmation is required before git pull or svn update.",
            "commands": _read_refresh_commands(workspace_path, bmw_path),
            "manual_review_required": True,
            "is_approval": False,
        }
    retry_payload: dict[str, Any]
    if not missing_pairs:
        retry_payload = {
            "status": "skipped",
            "summary": "No missing actual rows were found.",
            "manual_review_required": True,
            "is_approval": False,
        }
    elif retry_capture:
        retry_payload = _run_retry_capture(
            profile_id=clean_profile,
            workspace=workspace_path,
            bmw_root=bmw_path,
            operator_confirmed_retry_capture=operator_confirmed_retry_capture,
            timeout_seconds=retry_timeout_seconds,
        )
    else:
        retry_payload = {
            "status": "not_run",
            "summary": "Retry screenshot capture was not requested.",
            "manual_review_required": True,
            "is_approval": False,
        }
    if not missing_pairs:
        status = "auto_fix_resolved"
        summary = "No missing actual rows remain in screenshot evidence."
        operator_confirmation_required = False
    elif read_refresh_payload["status"] == "confirmation_pending" or retry_payload["status"] == "confirmation_pending":
        status = "confirmation_pending"
        summary = "Missing actual rows found; read-refresh and retry remain gated by operator confirmation."
        operator_confirmation_required = True
    elif retry_capture and retry_payload.get("actual_count", 0):
        status = "auto_fix_resolved"
        summary = "Retry screenshot capture produced actual screenshot evidence."
        operator_confirmation_required = False
    else:
        status = "auto_fix_exhausted_escalation_required" if operator_confirmed_read_refresh or retry_capture else "incomplete"
        summary = "Missing actual rows still require diagnostic follow-up and operator review."
        operator_confirmation_required = False
    steps = [
        _step(
            "pre-flight",
            "Screenshot capture pre-flight",
            str(preflight.get("status", "unknown")),
            str(preflight.get("disabled_reason", "") or preflight.get("summary", "") or "Pre-flight checks recorded."),
            payload=preflight,
        ),
        _step(
            "known-patterns",
            "Known diagnostic patterns",
            known_patterns["status"],
            known_patterns["summary"],
            payload=known_patterns,
        ),
        _step(
            "read-refresh",
            "BMW Git/SVN read-refresh",
            str(read_refresh_payload.get("status", "unknown")),
            str(read_refresh_payload.get("summary", "")),
            payload=read_refresh_payload,
        ),
        _step(
            "retry-capture",
            "Retry screenshot capture",
            str(retry_payload.get("status", "unknown")),
            str(retry_payload.get("summary", "")),
            payload=retry_payload,
        ),
        _step(
            "asset-doctor",
            "Asset doctor",
            str(asset_doctor.get("status", "unknown")),
            str(asset_doctor.get("summary", "")),
            payload=asset_doctor,
        ),
    ]
    return {
        "schema_version": 1,
        "action_id": MISSING_ACTUAL_DIAGNOSTIC_ACTION_ID,
        "profile_id": clean_profile,
        "workspace": str(workspace_path),
        "project_root": str(project_path),
        "bmw_root": str(bmw_path or ""),
        "status": status,
        "summary": summary,
        "operator_confirmation_required": operator_confirmation_required,
        "confirmation_message": (
            f"This can run BMW Git `git pull --ff-only` and SVN `svn update` read-refresh for {clean_profile}. "
            "SVN writes remain locked. Continue only after operator confirmation."
        ),
        "missing_actual_count": len(missing_pairs),
        "missing_actuals": [
            {
                "key": pair.key,
                "summary": pair.summary,
                "diagnostic_chain_status": pair.diagnostic_chain_status,
                "diagnostic_pattern_ids": list(pair.diagnostic_pattern_ids),
                "escalation_message": pair.escalation_message,
            }
            for pair in missing_pairs
        ],
        "steps": steps,
        "triage_json_path": str(triage_bundle.json_path),
        "triage_html_path": str(triage_bundle.html_path),
        "manual_review_required": True,
        "is_approval": False,
    }


def render_missing_actual_diagnostic_text(payload: dict[str, Any]) -> str:
    lines = [
        f"BMW pipeline diagnostic chain: {payload.get('profile_id', '')}",
        f"Status: {payload.get('status', 'unknown')}",
        f"Summary: {payload.get('summary', '')}",
        f"Missing actuals: {payload.get('missing_actual_count', 0)}",
        f"Operator confirmation required: {payload.get('operator_confirmation_required', False)}",
    ]
    for step in payload.get("steps", []):
        if isinstance(step, dict):
            lines.append(f"- {step.get('label', step.get('id', 'step'))}: {step.get('status', 'unknown')} - {step.get('detail', '')}")
    return "\n".join(lines)


def render_missing_actual_diagnostic_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# BMW pipeline diagnostic chain - {payload.get('profile_id', '')}",
        "",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- Summary: {payload.get('summary', '')}",
        f"- Missing actuals: `{payload.get('missing_actual_count', 0)}`",
        f"- Operator confirmation required: `{payload.get('operator_confirmation_required', False)}`",
        "",
        "## Steps",
    ]
    for step in payload.get("steps", []):
        if isinstance(step, dict):
            lines.append(f"- **{step.get('label', step.get('id', 'step'))}**: `{step.get('status', 'unknown')}` - {step.get('detail', '')}")
    lines.extend(
        [
            "",
            "Manual review remains required.",
            "Decision: not approval - evidence only.",
        ]
    )
    return "\n".join(lines)
