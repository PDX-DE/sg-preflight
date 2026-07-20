"""Detects and, where possible, installs the external tools the BMW 3D Car
pipeline needs: the RaCo GUI and RaCoHeadless installs, Blender 4.1 + SG
Toolkit, the digital-3d-car-repo BMW Git clone (main checkout plus the
optional IDC23 worktree), and the BMW CI Python venv/requirements.

Detected or operator-registered paths persist to
`<workspace>/operator_state/dependency_onboarding.json`, guarded by a file
lock at `dependency_onboarding.lock` so the dashboard and CLI don't race each
other reading or writing the same state file.

"Detect" (`build_dependency_onboarding_status` and the `_*_status` helpers)
only inspects the filesystem, PATH, and Windows registry to report what is
already present — it never changes anything. "Install" (the `_run_*_setup`
functions launched through `run_dependency_setup_action` /
`start_dependency_setup_action`) is the only path that downloads, clones, or
builds a dependency and then records its resulting path via
`record_dependency_path`.

The implementation lives in cohesive siblings and is re-exported here
explicitly so every previous name (and every mock.patch target) still
resolves through `sg_preflight.dependency_onboarding`:

- `dependency_onboarding_jobs.py` is the shared tier: operator-state
  persistence, generic path-probe helpers, the status/action/result dict
  builders, and the `DependencySetupJob` job-runner.
- `dependency_onboarding_raco.py`, `dependency_onboarding_blender.py`, and
  `dependency_onboarding_bmw.py` own RaCo, Blender, and BMW Git/IDC23/BMW-CI
  discovery and setup respectively; they only import from the shared tier,
  never from each other.

This module keeps `build_dependency_onboarding_status` (aggregates all three
domains), the setup-action dispatch table, and `run_/start_dependency_setup_
action`, since those necessarily cross all three domain modules.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
import urllib.request

from sg_preflight.subprocess_utils import hidden_subprocess_kwargs
from sg_preflight.utils import ensure_parent

from sg_preflight.dependency_onboarding_jobs import (
    DEPENDENCY_SETUP_FILE_ACTIVITY_LIMIT,
    DEPENDENCY_SETUP_STDOUT_TAIL_BYTES,
    DEPENDENCY_SETUP_STDOUT_TAIL_LINES,
    DEPENDENCY_SETUP_TIMEOUT_SECONDS,
    DEPENDENCY_STATE_REPLACE_ATTEMPTS,
    DEPENDENCY_STATE_REPLACE_RETRY_ATTEMPTS,
    DEPENDENCY_STATE_REPLACE_RETRY_SECONDS,
    DependencySetupJob,
    ONBOARDING_STATE_FILENAME,
    ONBOARDING_STATE_LOCK_FILENAME,
    _DEPENDENCY_STATE_LOCK,
    _DEPENDENCY_STATE_TRANSACTIONS,
    _KNOWN_REGISTERED_PATHS,
    _acquire_dependency_state_file_lock,
    _auto_register_dependency_path,
    _combined_tail_lines,
    _dependency_setup_progress_payload,
    _dependency_setup_result,
    _dependency_setup_worker_command,
    _dependency_state_transaction,
    _elapsed_label,
    _env_path,
    _existing_dir,
    _existing_file,
    _file_activity_from_roots,
    _find_executable,
    _glob_dirs,
    _held_dependency_state_transactions,
    _last_json_payload,
    _persist_auto_detected_dependency_paths,
    _registered_path,
    _registered_paths_snapshot,
    _release_dependency_state_file_lock,
    _same_registered_path,
    _setup_action,
    _setup_result,
    _size_label,
    _status_item,
    _tail_lines,
    _tail_text,
    _utc_now,
    _workspace,
    _write_dependency_onboarding_state,
    cancel_dependency_setup_action,
    dependency_onboarding_state_lock_path,
    dependency_onboarding_state_path,
    finish_first_run_guidance,
    first_run_guidance_eligible,
    has_operator_state,
    load_dependency_onboarding_state,
    operator_state_root,
    poll_dependency_setup_action,
    record_dependency_path,
)
from sg_preflight.dependency_onboarding_raco import (
    RACO_BASELINE_VERSION,
    RACO_CONFLUENCE_ANCHOR,
    RACO_HEADLESS_CONFLUENCE_ANCHOR,
    _find_executable_under,
    _onedrive_raco_sources,
    _raco_executable_candidates,
    _raco_install_roots,
    _raco_source_detail,
    _raco_status,
    _resolve_raco_install_root,
    _run_raco_setup,
    _safe_extract_zip,
)
from sg_preflight.dependency_onboarding_blender import (
    BLENDER_BASELINE_VERSION,
    BLENDER_CONFLUENCE_ANCHOR,
    BLENDER_INSTALLER_FILENAME,
    BLENDER_INSTALLER_URL,
    _blender_disallowed,
    _blender_path_candidates,
    _blender_status,
    _download_blender_installer,
    _run_blender_setup,
    _windows_admin_status,
)
from sg_preflight.dependency_onboarding_bmw import (
    BMW_CI_IMPORT_PROBE,
    BMW_CI_REQUIREMENTS_RELATIVE_PATH,
    BMW_CI_VENV_DIRNAME,
    BMW_ENV_CONFLUENCE_ANCHOR,
    BMW_GIT_CONFLUENCE_ANCHOR,
    BMW_MODELS_REPO_URL,
    BMW_PIPELINE_PYTHON_ENV,
    DIGITAL_3D_CAR_REPO_ENV,
    DIGITAL_3D_CAR_REPO_IDC23_ENV,
    IDC23_WORKTREE_CONFLUENCE_ANCHOR,
    _base_python_for_bmw_ci_venv,
    _bmw_ci_requirements_paths,
    _bmw_ci_requirements_status,
    _bmw_ci_venv_python,
    _bmw_repo_status,
    _candidate_bmw_repo_paths,
    _candidate_idc23_repo_paths,
    _command_output_tail,
    _default_idc23_worktree_target,
    _idc23_repo_status,
    _idc23_worktree_check,
    _probe_bmw_ci_python,
    _record_idc23_repo_path,
    _repo_root_from_target,
    _resolve_bmw_ci_python,
    _run_bmw_ci_requirements_setup,
    _run_bmw_clone_setup,
    _run_bmw_env_setup,
    _run_bmw_idc23_setup,
    _run_dependency_setup_command,
    _run_setx_for_idc23,
    _unique_existing_bmw_repo_roots,
    _valid_bmw_repo_root,
)


_DEPENDENCY_ORDER = (
    "raco_gui",
    "raco_headless",
    "blender",
    "digital_3d_car_repo",
    "digital_3d_car_repo_idc23",
    "bmw_ci_requirements",
)


_BASELINE_SOURCE_NOTE = (
    "Re-read the Confluence dump before changing dependency baselines; versions can move during daily sync."
)


RACO_SETUP_TYPICAL_RANGE_LABEL = "typical ~30 sec"


BLENDER_SETUP_TYPICAL_RANGE_LABEL = "typical ~2 min"


BMW_GIT_SETUP_TYPICAL_RANGE_LABEL = "typical ~2-10 min"


BMW_GIT_IDC23_SETUP_TYPICAL_RANGE_LABEL = "typical ~1-5 min"


BMW_CI_SETUP_TYPICAL_RANGE_LABEL = "typical 1-3 min"


ENV_SETUP_TYPICAL_RANGE_LABEL = "typical <30 sec"


_SETUP_ACTION_TYPICAL_RANGES = {
    "setup-raco-from-shared-tools": RACO_SETUP_TYPICAL_RANGE_LABEL,
    "setup-blender-411": BLENDER_SETUP_TYPICAL_RANGE_LABEL,
    "clone-digital-3d-car-repo": BMW_GIT_SETUP_TYPICAL_RANGE_LABEL,
    "setup-digital-3d-car-repo": ENV_SETUP_TYPICAL_RANGE_LABEL,
    "setup-digital-3d-car-repo-idc23": BMW_GIT_IDC23_SETUP_TYPICAL_RANGE_LABEL,
    "setup-bmw-ci-requirements": BMW_CI_SETUP_TYPICAL_RANGE_LABEL,
}


def build_dependency_onboarding_status(
    *,
    workspace: Path | str,
    bmw_root: Path | str | None = None,
    persist_auto_detected_paths: bool = True,
) -> dict[str, Any]:
    root = _workspace(workspace)
    first_run = first_run_guidance_eligible(root)
    state = load_dependency_onboarding_state(root)
    registered_paths_before_detection = _registered_paths_snapshot(state)
    raco_gui, raco_headless = _raco_status(state, root)
    dependencies = {
        "raco_gui": raco_gui,
        "raco_headless": raco_headless,
        "blender": _blender_status(state, root),
        "digital_3d_car_repo": _bmw_repo_status(state, root, bmw_root),
        "digital_3d_car_repo_idc23": _idc23_repo_status(state, root, bmw_root),
        "bmw_ci_requirements": _bmw_ci_requirements_status(state, root),
    }
    items = [dependencies[key] for key in _DEPENDENCY_ORDER]
    actions = []
    seen_action_ids: set[str] = set()
    for item in items:
        action = item.get("setup_action")
        if not isinstance(action, dict):
            continue
        action_id = str(action.get("id", "")).strip()
        if not action_id or action_id in seen_action_ids:
            continue
        seen_action_ids.add(action_id)
        actions.append(action)
    available_count = sum(1 for item in items if item["status"] == "available")
    missing_count = sum(1 for item in items if item["status"] == "missing")
    incomplete_count = sum(1 for item in items if item["status"] == "incomplete")
    status = "available" if available_count == len(items) else "incomplete"
    if persist_auto_detected_paths:
        _persist_auto_detected_dependency_paths(
            root,
            original_paths=registered_paths_before_detection,
            detected_state=state,
        )
    return {
        "status": status,
        "summary": (
            f"{available_count}/{len(items)} dependency item(s) available; "
            "setup actions require operator confirmation."
        ),
        "workspace": str(root),
        "state_path": str(dependency_onboarding_state_path(root)),
        "first_run": first_run,
        "baseline_source_note": _BASELINE_SOURCE_NOTE,
        "items": items,
        "actions": actions,
        "counts": {
            "available": available_count,
            "missing": missing_count,
            "incomplete": incomplete_count,
        },
        "confluence_anchors": [
            RACO_CONFLUENCE_ANCHOR,
            RACO_HEADLESS_CONFLUENCE_ANCHOR,
            BLENDER_CONFLUENCE_ANCHOR,
            BMW_GIT_CONFLUENCE_ANCHOR,
            BMW_ENV_CONFLUENCE_ANCHOR,
            IDC23_WORKTREE_CONFLUENCE_ANCHOR,
        ],
        "guardrails": [
            "Manual review remains required.",
            "Decision: not approval — evidence only.",
            "BMW Git access is read-only. SGFX never modifies BMW source.",
            "Activity log is local-only — never posted to Jira, SVN, or BMW Git.",
        ],
    }


_SETUP_ACTION_HANDLERS = {
    "setup-raco-from-shared-tools": _run_raco_setup,
    "setup-blender-411": _run_blender_setup,
    "clone-digital-3d-car-repo": _run_bmw_clone_setup,
    "setup-digital-3d-car-repo": _run_bmw_env_setup,
    "setup-digital-3d-car-repo-idc23": _run_bmw_idc23_setup,
    "setup-bmw-ci-requirements": _run_bmw_ci_requirements_setup,
}


def _setup_actions_by_id(root: Path) -> dict[str, dict[str, Any]]:
    status = build_dependency_onboarding_status(workspace=root)
    return {str(action.get("id", "")): action for action in status.get("actions", []) if isinstance(action, dict)}


def run_dependency_setup_action(
    *,
    action_id: str,
    workspace: Path | str,
    operator_confirmed: bool,
    target_path: Path | str | None = None,
    source_path: Path | str | None = None,
    stream_output: bool = False,
) -> dict[str, Any]:
    if not operator_confirmed:
        raise ValueError("Operator confirmation is required before setup changes.")
    root = _workspace(workspace)
    action = _setup_actions_by_id(root).get(action_id)
    handler = _SETUP_ACTION_HANDLERS.get(action_id)
    if handler is None:
        raise KeyError(f"Unknown dependency setup action: {action_id}")
    if action is None:
        action = {
            "id": action_id,
            "target_path": str(target_path or ""),
            "source_path": str(source_path or ""),
        }
    return handler(
        action_id=action_id,
        workspace=root,
        action=action,
        target_path=target_path,
        source_path=source_path,
        stream_output=stream_output,
    )


def start_dependency_setup_action(
    *,
    action_id: str,
    workspace: Path | str,
    operator_confirmed: bool,
    target_path: Path | str | None = None,
    source_path: Path | str | None = None,
    timeout_seconds: int = DEPENDENCY_SETUP_TIMEOUT_SECONDS,
) -> DependencySetupJob:
    if not operator_confirmed:
        raise ValueError("Operator confirmation is required before setup changes.")
    root = _workspace(workspace)
    action = _setup_actions_by_id(root).get(action_id)
    if action is None and action_id not in _SETUP_ACTION_HANDLERS:
        raise KeyError(f"Unknown dependency setup action: {action_id}")
    if action is None:
        action = {
            "id": action_id,
            "target_path": str(target_path or ""),
            "source_path": str(source_path or ""),
        }
    resolved_target = Path(str(target_path or action.get("target_path", ""))).expanduser() if (target_path or action.get("target_path")) else None
    resolved_source = Path(str(source_path or action.get("source_path", ""))).expanduser() if (source_path or action.get("source_path")) else None
    log_root = operator_state_root(root) / "dependency_setup"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stdout_path = log_root / f"{action_id}-{stamp}.stdout.log"
    stderr_path = log_root / f"{action_id}-{stamp}.stderr.log"
    ensure_parent(stdout_path)
    command = _dependency_setup_worker_command(
        action_id=action_id,
        workspace=root,
        target_path=resolved_target,
        source_path=resolved_source,
    )
    started_wall_time = time.time()
    started_monotonic = time.monotonic()
    with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
        process = subprocess.Popen(
            command,
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=stderr_handle,
            **hidden_subprocess_kwargs(),
        )
    return DependencySetupJob(
        action_id=action_id,
        workspace=root,
        process=process,
        command=command,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        started_monotonic=started_monotonic,
        started_wall_time=started_wall_time,
        timeout_seconds=timeout_seconds,
        typical_range=_SETUP_ACTION_TYPICAL_RANGES.get(action_id, "typical setup range unknown"),
        target_path=resolved_target.resolve() if resolved_target is not None else None,
        source_path=resolved_source.resolve() if resolved_source is not None else None,
    )
