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

from sg_preflight.bmw_delivery import (
    BMW_MODEL_CONFIG_RELATIVE,
    DIGITAL_3D_CAR_REPO_ENV,
    DIGITAL_3D_CAR_REPO_IDC23_ENV,
    LANE_IDC23,
    LANE_IDCEVO,
    LANE_UNKNOWN,
    detect_lane,
    find_bmw_registry_entry,
    load_bmw_model_config_records,
    resolve_bmw_profile_id,
)
from sg_preflight.delivery_checklist import (
    delivery_workbook_missing_escalation,
    delivery_workbook_missing_summary,
    read_delivery_checklist,
)
from sg_preflight.dependency_onboarding import load_dependency_onboarding_state
from sg_preflight.subprocess_utils import hidden_subprocess_kwargs
from sg_preflight.utils import ensure_parent


BMW_PIPELINE_PYTHON_ENV = "SG_BMW_PYTHON_EXE"
GENERATE_WORKBOOK_ACTION_ID = "generate-delivery-workbook"
GENERATE_WORKBOOK_ACTION_LABEL = "Generate delivery workbook"
GENERATE_WORKBOOK_TIMEOUT_SECONDS = 600
GENERATE_WORKBOOK_MIN_FREE_BYTES = 100 * 1024 * 1024
WORKBOOK_TRIGGER_GUARDRAILS = (
    "Manual review remains required.",
    "Decision: not approval — evidence only.",
    "BMW Git access is read-only. SGFX never modifies BMW source.",
    "Activity log is local-only — never posted to Jira, SVN, or BMW Git.",
)
GENERATION_STDOUT_TAIL_BYTES = 2000
GENERATION_STDOUT_TAIL_LINES = 20
GENERATION_FILE_ACTIVITY_LIMIT = 20
GENERATION_TYPICAL_RANGE_LABEL = "typical 1-10 min"
GENERATION_COPIED_EVIDENCE_LIMIT = 40
_TOOL_REGISTRATION_KEYS = {
    "raco": "raco_gui",
    "racoheadless": "raco_headless",
    "raco_headless": "raco_headless",
    "blender": "blender",
}
_PYTHON_REGISTRATION_KEYS = ("bmw_pipeline_python", "python", "python_executable")
_DIGITAL_REPO_REGISTRATION_KEYS = ("digital_3d_car_repo",)
_DIGITAL_REPO_IDC23_REGISTRATION_KEYS = ("digital_3d_car_repo_idc23", "digital_3d_car_repo_assets_idc23")
_MODEL_ONBOARDING_CONTACT = "Confluence anchor: Adding a new model derivative to system assembly process."
_IDC23_CONTACT = "Confluence anchor: 3D Cars Delivery Checklist, lines 81-82."
_BRAND_FOLDERS = {
    "BMW": "BMW",
    "MINI": "MINI",
    "Alpina": "Alpina",
    "MGmbH": "MGmbH",
    "RollsRoyce": "RollsRoyce",
}


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


def _registered_path_candidates(workspace: Path | str | None, keys: tuple[str, ...]) -> list[Path]:
    if workspace is None:
        return []
    state = load_dependency_onboarding_state(workspace)
    registered_paths = state.get("registered_paths", {})
    if not isinstance(registered_paths, dict):
        return []
    candidates: list[Path] = []
    for key in keys:
        raw = str(registered_paths.get(key, "")).strip()
        if not raw:
            continue
        try:
            candidate = Path(raw).expanduser()
        except RuntimeError:
            continue
        candidates.append(candidate)
    return candidates


def _registered_file(workspace: Path | str | None, keys: tuple[str, ...]) -> Path | None:
    for candidate in _registered_path_candidates(workspace, keys):
        if candidate.is_file():
            return candidate.resolve()
    return None


def _registered_dir(workspace: Path | str | None, keys: tuple[str, ...]) -> Path | None:
    for candidate in _registered_path_candidates(workspace, keys):
        if candidate.is_dir():
            return candidate.resolve()
    return None


def _digital_repo_check(
    bmw_root: Path | str | None = None,
    *,
    workspace: Path | str | None = None,
) -> tuple[dict[str, str], Path | None]:
    raw = str(bmw_root or os.environ.get(DIGITAL_3D_CAR_REPO_ENV, "")).strip()
    if not raw:
        registered = _registered_dir(workspace, _DIGITAL_REPO_REGISTRATION_KEYS)
        if registered is not None:
            raw = str(registered)
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


def _configured_idc23_repo_root(workspace: Path | str | None = None) -> Path | None:
    raw = os.environ.get(DIGITAL_3D_CAR_REPO_IDC23_ENV, "").strip()
    if not raw:
        registered = _registered_dir(workspace, _DIGITAL_REPO_IDC23_REGISTRATION_KEYS)
        if registered is not None:
            raw = str(registered)
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _idc23_repo_check(workspace: Path | str | None = None) -> tuple[dict[str, str], Path | None]:
    root = _configured_idc23_repo_root(workspace)
    if root is None:
        return (
            _check(
                key="digital_3d_car_repo_idc23",
                label=f"{DIGITAL_3D_CAR_REPO_IDC23_ENV} environment variable",
                status="unavailable",
                detail=f"{DIGITAL_3D_CAR_REPO_IDC23_ENV} is not set.",
                remediation=(
                    "IDC_23 execution requires a separate assets/idc23 worktree. "
                    f"Run `git worktree add <path> assets/idc23` from BMW Git root, then set {DIGITAL_3D_CAR_REPO_IDC23_ENV} to that path. "
                    + _IDC23_CONTACT
                ),
            ),
            None,
        )
    script = root / "ci" / "scripts" / "test" / "main.py"
    shared = root / "cars" / "BMW" / "_Shared"
    if not script.is_file():
        return (
            _check(
                key="digital_3d_car_repo_idc23",
                label=f"{DIGITAL_3D_CAR_REPO_IDC23_ENV} worktree",
                status="unavailable",
                detail="The configured IDC_23 worktree does not expose ci/scripts/test/main.py.",
                path=root,
                remediation=f"Point the IDC_23 path at a digital-3d-car-models worktree checked out on assets/idc23. {_IDC23_CONTACT}",
            ),
            root,
        )
    if not shared.is_dir():
        return (
            _check(
                key="digital_3d_car_repo_idc23",
                label=f"{DIGITAL_3D_CAR_REPO_IDC23_ENV} worktree",
                status="unavailable",
                detail="The configured IDC_23 worktree is missing cars/BMW/_Shared.",
                path=shared,
                remediation=f"Ensure cars/BMW/_Shared is checked out in the assets/idc23 worktree before running IDC_23 pipeline commands. {_IDC23_CONTACT}",
            ),
            root,
        )
    return (
        _check(
            key="digital_3d_car_repo_idc23",
            label=f"{DIGITAL_3D_CAR_REPO_IDC23_ENV} worktree",
            status="available",
            detail="IDC_23 assets/idc23 worktree is available for read-only script invocation.",
            path=root,
        ),
        root,
    )


def _tool_key(executable_name: str) -> str:
    key = executable_name.strip()
    if key.casefold().endswith(".exe"):
        key = key[:-4]
    key = key.replace("-", "_").casefold()
    if key == "racoheadless":
        key = "raco_headless"
    return key


def _tool_check(executable_name: str, label: str, *, workspace: Path | str | None = None) -> dict[str, str]:
    key = _tool_key(executable_name)
    registered_key = _TOOL_REGISTRATION_KEYS.get(key)
    registered = _registered_file(workspace, (registered_key,)) if registered_key else None
    if registered is not None:
        return _check(
            key=key,
            label=label,
            status="available",
            detail=f"{label} executable is available from dependency setup registration.",
            path=registered,
        )
    found = _find_executable(executable_name)
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
        detail=f"{label} executable was not found in dependency setup registration, PATH, or App Paths.",
        remediation=f"Install {label}, register it in Dependency Setup, or add {executable_name} to PATH before running export.",
    )


def _python_command_payload(workspace: Path | str | None = None) -> dict[str, Any]:
    registered = _registered_file(workspace, _PYTHON_REGISTRATION_KEYS)
    if registered is not None:
        return {
            "status": "available",
            "command": [str(registered)],
            "path": str(registered),
            "detail": "BMW pipeline Python is available from dependency setup registration.",
        }
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
    for executable_name in ("py.exe", "python.exe", "python3.exe", "py", "python", "python3"):
        found = shutil.which(executable_name)
        if found:
            candidates.append(found)
    if not getattr(sys, "frozen", False):
        candidates.append(str(Path(sys.executable).resolve()))
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


def _python_check(workspace: Path | str | None = None) -> dict[str, str]:
    payload = _python_command_payload(workspace)
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


def _overall_preflight_status(checks: list[dict[str, str]]) -> str:
    if all(check["status"] == "available" for check in checks):
        return "available"
    if any(check["status"] == "failed" for check in checks):
        return "failed"
    return "unavailable"


def _unavailable_model_summary(profile_id: str, root: Path) -> str:
    config_path = root / BMW_MODEL_CONFIG_RELATIVE
    if not load_bmw_model_config_records(root):
        return (
            f"BMW registry source unavailable for {profile_id}: {config_path} could not be read. "
            "Use the BMW Git source-of-truth checkout before running pipeline actions."
        )
    if find_bmw_registry_entry(profile_id, root) is None:
        return (
            f"Car {profile_id} is not onboarded in BMW Git models_build_config.yaml. "
            f"Data-prep team operation. {_MODEL_ONBOARDING_CONTACT}"
        )
    return f"Lane could not be determined for profile {profile_id} from BMW models_build_config.yaml."


def _registered_car_root(
    *,
    profile_id: str,
    source_root: Path,
    execution_root: Path,
    resolved_bmw_profile_id: str,
) -> tuple[str, Path]:
    entry = find_bmw_registry_entry(profile_id, source_root)
    brand = entry.brand if entry is not None else "BMW"
    bmw_profile = entry.bmw_profile_id if entry is not None else resolved_bmw_profile_id
    brand_folder = _BRAND_FOLDERS.get(brand, brand or "BMW")
    return bmw_profile, execution_root / "cars" / brand_folder / bmw_profile


def _requires_registered_car_folder(profile_id: str, source_root: Path) -> bool:
    entry = find_bmw_registry_entry(profile_id, source_root)
    return entry is None or entry.model_type != "retarget"


def _missing_car_payload(
    *,
    clean_profile: str,
    lane: str,
    root: Path,
    execution_root: Path,
    bmw_profile: str,
    car_root: Path,
    action: str,
) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "strategy": "none",
        "command": [],
        "cwd": str(execution_root),
        "script_path": "",
        "profile_id": clean_profile,
        "bmw_profile_id": bmw_profile,
        "lane": lane,
        "source_bmw_root": str(root),
        "execution_bmw_root": str(execution_root),
        "summary": (
            f"BMW Git car data for {clean_profile} is unavailable in the lane-correct checkout: {car_root}. "
            f"Data-prep team operation before {action} can run. {_MODEL_ONBOARDING_CONTACT}"
        ),
        "remediation": "Use a BMW Git checkout/worktree that contains the registered car folder for this lane.",
    }


def check_delivery_workbook_generation_environment(
    *,
    profile_id: str,
    workspace: Path | str,
    bmw_root: Path | str | None = None,
    min_free_bytes: int = GENERATE_WORKBOOK_MIN_FREE_BYTES,
) -> dict[str, Any]:
    workspace_path = Path(workspace).resolve()
    clean_profile = _clean_profile(profile_id)
    repo_check, repo_root = _digital_repo_check(bmw_root, workspace=workspace_path)
    lane = detect_lane(clean_profile, bmw_root=repo_root) if repo_root is not None else LANE_UNKNOWN
    checks = [
        repo_check,
        _python_check(workspace_path),
        _tool_check("raco.exe", "RaCo", workspace=workspace_path),
        _tool_check("RaCoHeadless.exe", "RaCoHeadless", workspace=workspace_path),
        _tool_check("blender.exe", "Blender", workspace=workspace_path),
        _disk_space_check(workspace_path, min_free_bytes),
    ]
    if repo_root is not None and repo_check["status"] == "available":
        if lane == LANE_IDC23:
            idc23_check, _idc23_root = _idc23_repo_check(workspace_path)
            checks.append(idc23_check)
        command_payload = resolve_delivery_workbook_generation_command(
            profile_id=clean_profile,
            bmw_root=repo_root,
            workspace=workspace_path,
        )
        checks.append(
            _check(
                key="bmw_export_script",
                label="BMW export script",
                status=str(command_payload.get("status", "unavailable"))
                if command_payload["status"] != "available"
                else "available",
                detail=(
                    f"Using {command_payload['strategy']} for {command_payload.get('lane', lane)}."
                    if command_payload["status"] == "available"
                    else str(command_payload.get("summary", "No supported BMW pipeline export script was found."))
                ),
                path=str(command_payload.get("script_path", "")),
                remediation=str(command_payload.get("remediation", "")),
            )
        )
    can_run = all(check["status"] == "available" for check in checks)
    native_target_path = workspace_path / "Cars" / "size_analysis"
    target_path = _delivery_workbook_sgfx_output_dir(workspace_path, clean_profile)
    status = _overall_preflight_status(checks)
    return {
        "profile_id": clean_profile,
        "workspace": str(workspace_path),
        "bmw_root": str(repo_root or ""),
        "lane": lane,
        "target_write_path": str(target_path),
        "native_output_path": str(native_target_path),
        "sgfx_output_root": str(target_path),
        "estimated_size_bytes": min_free_bytes,
        "status": status,
        "can_run": can_run,
        "checks": checks,
        "confirmation_message": (
            f"This will run the BMW pipeline for {clean_profile}. It may write native pipeline output under "
            f"`{native_target_path}`; SGFX copies the generated workbook evidence to `{target_path}`. Continue?"
        ),
        "disabled_reason": "" if can_run else "One or more environment pre-flight checks failed.",
    }


def _delivery_workbook_trigger_blockers(preflight: dict[str, Any]) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    for check in preflight.get("checks", []):
        if not isinstance(check, dict):
            continue
        status = str(check.get("status", "")).strip()
        if status == "available":
            continue
        blockers.append(
            {
                "key": str(check.get("key", "")).strip(),
                "label": str(check.get("label", "")).strip(),
                "status": status or "unknown",
                "detail": str(check.get("detail", "")).strip(),
                "remediation": str(check.get("remediation", "")).strip(),
            }
        )
    return blockers


def build_delivery_workbook_trigger(
    *,
    profile_id: str,
    workspace: Path | str,
    bmw_root: Path | str | None = None,
    trusted_tool_mode: bool = False,
) -> dict[str, Any]:
    preflight = check_delivery_workbook_generation_environment(
        profile_id=profile_id,
        workspace=workspace,
        bmw_root=bmw_root,
    )
    blockers = _delivery_workbook_trigger_blockers(preflight)
    can_start = bool(preflight.get("can_run", False))
    confirmation_required = can_start and not trusted_tool_mode
    trigger_status = "available" if can_start else str(preflight.get("status", "incomplete") or "incomplete")
    return {
        "schema_version": 1,
        "action_id": GENERATE_WORKBOOK_ACTION_ID,
        "label": GENERATE_WORKBOOK_ACTION_LABEL,
        "profile_id": str(preflight.get("profile_id", profile_id)).strip(),
        "workspace": str(Path(workspace).resolve()),
        "status": "available",
        "trigger_status": trigger_status,
        "can_start": can_start,
        "started": False,
        "trusted_tool_mode": bool(trusted_tool_mode),
        "operator_confirmation_required": confirmation_required,
        "confirmation_message": str(preflight.get("confirmation_message", "")),
        "timeout_seconds": GENERATE_WORKBOOK_TIMEOUT_SECONDS,
        "preflight": preflight,
        "blockers": blockers,
        "manual_review_required": True,
        "records_operator_verdict": False,
        "is_approval": False,
        "summary": (
            "Delivery workbook generation can be started after operator confirmation."
            if can_start
            else f"Delivery workbook generation is not available yet: {preflight.get('disabled_reason', '')}"
        ),
        "next_action": (
            "Confirm the generation action in the dashboard or trusted orchestrator."
            if can_start
            else "Resolve the listed pre-flight blockers before starting generation."
        ),
        "guardrails": list(WORKBOOK_TRIGGER_GUARDRAILS),
    }


def render_delivery_workbook_trigger_text(payload: dict[str, Any]) -> str:
    lines = [
        f"Delivery workbook trigger - {payload.get('profile_id', '')}",
        str(payload.get("summary", "")),
        f"Trigger status: {payload.get('trigger_status', 'unknown')}",
        f"Can start: {payload.get('can_start', False)}",
        f"Operator confirmation required: {payload.get('operator_confirmation_required', False)}",
        "",
        "Guardrails:",
    ]
    lines.extend(f"- {guardrail}" for guardrail in payload.get("guardrails", []) if str(guardrail).strip())
    blockers = [item for item in payload.get("blockers", []) if isinstance(item, dict)]
    if blockers:
        lines.extend(["", "Blockers:"])
        lines.extend(
            f"- [{item.get('status', 'unknown')}] {item.get('label', '')}: {item.get('detail', '')}"
            for item in blockers
        )
    return "\n".join(lines).rstrip() + "\n"


def render_delivery_workbook_trigger_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# Delivery workbook trigger - {payload.get('profile_id', '')}",
        "",
        str(payload.get("summary", "")),
        "",
        f"- Trigger status: `{payload.get('trigger_status', 'unknown')}`",
        f"- Can start: `{payload.get('can_start', False)}`",
        f"- Operator confirmation required: `{payload.get('operator_confirmation_required', False)}`",
        "- Manual review required: yes",
        "- Decision: not approval; evidence only.",
        "",
        "## Guardrails",
    ]
    lines.extend(f"- {guardrail}" for guardrail in payload.get("guardrails", []) if str(guardrail).strip())
    blockers = [item for item in payload.get("blockers", []) if isinstance(item, dict)]
    if blockers:
        lines.extend(["", "## Blockers"])
        lines.extend(
            f"- `{item.get('status', 'unknown')}` {item.get('label', '')}: {item.get('detail', '')}"
            for item in blockers
        )
    return "\n".join(lines).rstrip() + "\n"


def resolve_delivery_workbook_generation_command(
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
            "remediation": "Use the BMW Git source-of-truth checkout for lane detection before running export.",
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
                action="export",
            )
        return {
            "status": "available",
            "strategy": "idc23_test_main_export",
            "command": [*python_command, str(legacy), "export", bmw_profile],
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
                action="export",
            )
        return {
            "status": "available",
            "strategy": "car_manager_export",
            "command": [*python_command, str(car_manager), "export", bmw_profile],
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
        "summary": "No supported BMW pipeline export script was found for the detected lane.",
        "remediation": "IDC_EVO requires ci/scripts/car_manager.py on master; IDC_23 requires ci/scripts/test/main.py on an assets/idc23 worktree.",
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


def _profile_output_token(profile_id: str) -> str:
    token = "".join(ch.lower() if ch.isalnum() else "-" for ch in _clean_profile(profile_id))
    return "-".join(part for part in token.split("-") if part) or "profile"


def _sgfx_profile_output_root(workspace: Path, profile_id: str) -> Path:
    return workspace / "out" / _profile_output_token(profile_id)


def _sgfx_pipeline_output_root(workspace: Path, profile_id: str, action: str) -> Path:
    return _sgfx_profile_output_root(workspace, profile_id) / action


def _copy_file_evidence(source: Path, destination: Path) -> dict[str, Any] | None:
    if not source.is_file():
        return None
    ensure_parent(destination)
    shutil.copy2(source, destination)
    try:
        stat = destination.stat()
    except OSError:
        size_bytes = 0
    else:
        size_bytes = int(stat.st_size)
    return {
        "source_path": str(source),
        "path": str(destination),
        "relative_path": destination.name,
        "size_bytes": size_bytes,
        "size_label": _size_label(size_bytes),
    }


def _delivery_workbook_output_dir(workspace: Path) -> Path:
    return workspace / "Cars" / "size_analysis"


def _delivery_workbook_sgfx_output_dir(workspace: Path, profile_id: str) -> Path:
    return _sgfx_pipeline_output_root(workspace, profile_id, "delivery-workbook")


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


def _copy_delivery_workbook_evidence(
    job: DeliveryWorkbookGenerationJob,
    checklist_payload: dict[str, Any],
) -> dict[str, Any]:
    output_root = _delivery_workbook_sgfx_output_dir(job.workspace, job.profile_id)
    copied_files: list[dict[str, Any]] = []
    workbook_path = Path(str(checklist_payload.get("workbook_path", "")).strip())
    if workbook_path.is_file():
        copied = _copy_file_evidence(workbook_path, output_root / workbook_path.name)
        if copied is not None:
            copied_files.append(copied)
    for source, name in ((job.stdout_path, "stdout.log"), (job.stderr_path, "stderr.log")):
        copied = _copy_file_evidence(source, output_root / "logs" / name)
        if copied is not None:
            copied_files.append(copied)
    return {
        "status": "recorded" if copied_files else "missing",
        "output_root": str(output_root),
        "files": copied_files[:GENERATION_COPIED_EVIDENCE_LIMIT],
        "file_count": len(copied_files),
    }


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
        "sgfx_output_root": str(_delivery_workbook_sgfx_output_dir(job.workspace, job.profile_id)),
        "native_output_path": str(_delivery_workbook_output_dir(job.workspace)),
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
    escalation: dict[str, str] = {}
    if exit_code == 0 and not timed_out and not canceled:
        try:
            checklist_payload = read_delivery_checklist(profile_id=job.profile_id, workspace=job.workspace)
        except Exception as exc:  # noqa: BLE001
            checklist_payload = {"status": "failed", "summary": f"delivery checklist could not be re-read: {exc}"}
        if checklist_payload.get("status") == "available":
            status = "available"
            summary = str(checklist_payload.get("summary", "Delivery workbook generated and available."))
        elif status == "available":
            status = "unavailable"
            checklist_summary = str(checklist_payload.get("summary", "")).strip()
            escalation = delivery_workbook_missing_escalation(job.profile_id)
            summary = (
                "BMW export completed, but the delivery workbook is not available yet. "
                f"{delivery_workbook_missing_summary(job.profile_id)}"
            )
            if checklist_summary:
                summary = f"{summary} {checklist_summary}"
    copied_evidence = _copy_delivery_workbook_evidence(job, checklist_payload)
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
        "copied_evidence": copied_evidence,
        "sgfx_output_root": copied_evidence["output_root"],
        "native_output_path": str(_delivery_workbook_output_dir(job.workspace)),
        "preflight": job.preflight,
        "checklist_status": str(checklist_payload.get("status", "")),
        "checklist_summary": str(checklist_payload.get("summary", "")),
        "escalation": escalation,
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
    command_payload = resolve_delivery_workbook_generation_command(
        profile_id=clean_profile,
        bmw_root=repo_root,
        workspace=workspace_path,
    )
    if command_payload["status"] != "available":
        raise FileNotFoundError(str(command_payload.get("summary", "No supported BMW pipeline export script was found.")))
    execution_root = Path(str(command_payload.get("execution_bmw_root") or command_payload["cwd"])).resolve()
    log_root = workspace_path / "operator_state" / "delivery_workbook_generation"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stdout_path = log_root / f"{clean_profile}-{stamp}.stdout.log"
    stderr_path = log_root / f"{clean_profile}-{stamp}.stderr.log"
    ensure_parent(stdout_path)
    env = os.environ.copy()
    env[DIGITAL_3D_CAR_REPO_ENV] = str(execution_root)
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
    return DeliveryWorkbookGenerationJob(
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
