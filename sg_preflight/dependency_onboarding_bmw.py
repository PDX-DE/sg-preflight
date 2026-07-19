"""BMW digital-3d-car-models Git checkout / IDC_23 worktree discovery and
setup, plus the isolated BMW CI venv (yaml/PIL) resolution and setup.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from sg_preflight.dependency_onboarding_jobs import (
    DEPENDENCY_SETUP_TIMEOUT_SECONDS,
    _auto_register_dependency_path,
    _env_path,
    _existing_dir,
    _find_executable,
    _registered_path,
    _setup_action,
    _setup_result,
    _status_item,
    _with_onboarding_globals,
    load_dependency_onboarding_state,
    record_dependency_path,
)
from sg_preflight.subprocess_utils import hidden_subprocess_kwargs


DIGITAL_3D_CAR_REPO_ENV = "Digital-3D-Car-Repo"


DIGITAL_3D_CAR_REPO_IDC23_ENV = "Digital-3D-Car-Repo-IDC23"


BMW_MODELS_REPO_URL = "https://cc-github.bmwgroup.net/apinext/digital-3d-car-models.git"


BMW_PIPELINE_PYTHON_ENV = "SG_BMW_PYTHON_EXE"


BMW_CI_VENV_DIRNAME = ".venv_bmw_ci"


BMW_CI_REQUIREMENTS_RELATIVE_PATH = Path("ci") / "scripts" / "requirements.txt"


BMW_CI_IMPORT_PROBE = "import yaml, PIL"


BMW_GIT_CONFLUENCE_ANCHOR = "003_Onboarding/013_How-to-access-BMW-GIT:20-126"


BMW_ENV_CONFLUENCE_ANCHOR = (
    "311_Delivery-process/312_3D-Car---Delivery-and-Integration/"
    "315_How-to-3D-Cars-Delivery-Checklist----v0:50-54"
)


IDC23_WORKTREE_CONFLUENCE_ANCHOR = (
    "003_Onboarding/004_Onboarding-for-new-team-members:143-145; "
    "003_Onboarding/013_How-to-access-BMW-GIT:20-126; "
    "311_Delivery-process/312_3D-Car---Delivery-and-Integration/"
    "315_How-to-3D-Cars-Delivery-Checklist----v0:81-82"
)


def _candidate_bmw_repo_paths(workspace: Path, state: dict[str, Any], bmw_root: Path | str | None) -> list[Path | None]:
    candidates: list[Path | None] = [
        Path(bmw_root).expanduser() if bmw_root else None,
        _env_path((DIGITAL_3D_CAR_REPO_ENV, "SG_BMW_CAR_MODELS_ROOT", "SG_CARMODELS_REPO", "SG-CarModels-Repo")),
        workspace / "digital-3d-car-models",
        workspace / "external" / "digital-3d-car-models",
        workspace.parent / "digital-3d-car-models",
        Path(r"C:\3D Car git\digital-3d-car-models"),
        Path(r"C:\repos\digital-3d-car-models"),
        _registered_path(state, "digital_3d_car_repo"),
    ]
    return candidates


def _valid_bmw_repo_root(root: Path | None) -> bool:
    return root is not None and (root / "cars" / "BMW").is_dir()


def _candidate_idc23_repo_paths(
    workspace: Path,
    state: dict[str, Any],
    bmw_root: Path | str | None,
) -> list[Path | None]:
    main_root = _existing_dir(_candidate_bmw_repo_paths(workspace, state, bmw_root))
    candidates: list[Path | None] = [
        _env_path((DIGITAL_3D_CAR_REPO_IDC23_ENV, "SG_BMW_CAR_MODELS_ROOT_IDC23")),
        workspace / "external" / "digital-3d-car-models-idc23",
        workspace.parent / "digital-3d-car-models-idc23",
        Path(r"C:\3D Car git\worktrees\assets-idc23"),
        Path(r"C:\3D Car git\digital-3d-car-models-idc23"),
    ]
    if main_root is not None:
        candidates.extend(
            [
                main_root.parent / "worktrees" / "assets-idc23",
                main_root.parent / "digital-3d-car-models-idc23",
                main_root / "assets" / "idc23",
            ]
        )
    candidates.extend(
        [
            _registered_path(state, "digital_3d_car_repo_idc23"),
            _registered_path(state, "digital_3d_car_repo_assets_idc23"),
        ]
    )
    return candidates


def _default_idc23_worktree_target(main_root: Path | None, workspace: Path) -> Path:
    if main_root is not None:
        worktrees_root = main_root.parent / "worktrees"
        if worktrees_root.is_dir() or main_root.parent.name.casefold() == "3d car git":
            return worktrees_root / "assets-idc23"
        return main_root.parent / "digital-3d-car-models-idc23"
    return workspace / "external" / "digital-3d-car-models-idc23"


def _idc23_worktree_check(root: Path | None) -> tuple[str, str]:
    if root is None:
        return "missing", f"{DIGITAL_3D_CAR_REPO_IDC23_ENV} is not set."
    script = root / "ci" / "scripts" / "test" / "main.py"
    shared = root / "cars" / "BMW" / "_Shared"
    if not script.is_file():
        return "incomplete", "The IDC_23 worktree does not expose ci/scripts/test/main.py."
    if not shared.is_dir():
        return "incomplete", "The IDC_23 worktree is missing cars/BMW/_Shared."
    return "available", "IDC_23 assets/idc23 worktree is available for read-only script invocation."


def _record_idc23_repo_path(*, workspace: Path | str, path: Path | str) -> None:
    record_dependency_path(workspace=workspace, key="digital_3d_car_repo_idc23", path=path)
    record_dependency_path(workspace=workspace, key="digital_3d_car_repo_assets_idc23", path=path)


def _bmw_ci_venv_python(repo_root: Path) -> Path:
    scripts_dir = "Scripts" if os.name == "nt" else "bin"
    executable = "python.exe" if os.name == "nt" else "python"
    return repo_root / BMW_CI_VENV_DIRNAME / scripts_dir / executable


def _unique_existing_bmw_repo_roots(
    *,
    workspace: Path,
    state: dict[str, Any],
    bmw_root: Path | str | None,
) -> list[Path]:
    candidates: list[Path | None] = [
        _existing_dir(_candidate_bmw_repo_paths(workspace, state, bmw_root)),
        _existing_dir(_candidate_idc23_repo_paths(workspace, state, bmw_root)),
    ]
    roots: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate is None:
            continue
        normalized = os.path.normcase(str(candidate.resolve()))
        if normalized in seen:
            continue
        seen.add(normalized)
        roots.append(candidate.resolve())
    return roots


def _resolve_bmw_ci_python(
    state: dict[str, Any],
    *,
    workspace: Path,
    bmw_root: Path | str | None = None,
) -> tuple[Path | None, str, str]:
    override = os.environ.get(BMW_PIPELINE_PYTHON_ENV, "").strip()
    if override:
        override_path = Path(override).expanduser()
        if override_path.is_file():
            return override_path.resolve(), "env", f"{BMW_PIPELINE_PYTHON_ENV} points to a Python executable."
        return (
            None,
            "env_missing",
            f"{BMW_PIPELINE_PYTHON_ENV} is set, but the file does not exist: {override_path}",
        )
    registered = _registered_path(state, "bmw_pipeline_python")
    if registered is not None and registered.is_file():
        return registered.resolve(), "registered", "BMW pipeline Python is registered in dependency onboarding."
    for repo_root in _unique_existing_bmw_repo_roots(workspace=workspace, state=state, bmw_root=bmw_root):
        candidate = _bmw_ci_venv_python(repo_root)
        if candidate.is_file():
            return candidate.resolve(), "venv", f"BMW-CI venv Python was found at {candidate}."
    return (
        None,
        "missing",
        f"No BMW-CI Python was found. Set {BMW_PIPELINE_PYTHON_ENV}, register bmw_pipeline_python, or run setup.",
    )


def _probe_bmw_ci_python(python_path: Path) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            [str(python_path), "-c", BMW_CI_IMPORT_PROBE],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            check=False,
            **hidden_subprocess_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    output = (completed.stderr or completed.stdout or "").strip()
    if completed.returncode == 0:
        return True, output
    return False, output or f"Import probe exited with {completed.returncode}."


def _bmw_ci_requirements_paths(repo_roots: list[Path]) -> list[Path]:
    paths: list[Path] = []
    seen: set[str] = set()
    for root in repo_roots:
        path = root / BMW_CI_REQUIREMENTS_RELATIVE_PATH
        normalized = os.path.normcase(str(path))
        if normalized in seen:
            continue
        seen.add(normalized)
        if path.is_file():
            paths.append(path)
    return paths


def _bmw_ci_requirements_status(state: dict[str, Any], workspace: Path) -> dict[str, Any]:
    repo_roots = _unique_existing_bmw_repo_roots(workspace=workspace, state=state, bmw_root=None)
    requirements_paths = _bmw_ci_requirements_paths(repo_roots)
    target_repo = repo_roots[0] if repo_roots else workspace
    target_venv_python = _bmw_ci_venv_python(target_repo)
    command_lines = [
        f'"<base-python>" -m venv --clear "{target_venv_python.parent.parent}"',
        *[
            f'"{target_venv_python}" -m pip install -r "{path}"'
            for path in requirements_paths
        ],
    ]
    action = _setup_action(
        action_id="setup-bmw-ci-requirements",
        label="Install BMW pipeline requirements",
        dependency_key="bmw_ci_requirements",
        status="available" if repo_roots else "incomplete",
        confirmation_message=(
            "Create an isolated .venv_bmw_ci, install BMW CI requirements into it, "
            "and register it as the BMW pipeline Python."
        ),
        effects=[
            "Creates or refreshes an isolated .venv_bmw_ci folder under the local BMW Git worktree.",
            "Installs ci/scripts/requirements.txt into that venv for each available BMW worktree.",
            "Records the venv python.exe in operator_state/dependency_onboarding.json.",
        ],
        confluence_anchor=BMW_ENV_CONFLUENCE_ANCHOR,
        can_run_now=bool(repo_roots),
        command_preview="\n".join(command_lines),
        target_path=target_repo,
        operator_inputs=[
            "Confirm before installing Python packages into the isolated BMW-CI venv.",
            "Optional: set SG_BMW_PYTHON_EXE to an existing BMW pipeline Python instead.",
        ],
    )
    python_path, source, detail = _resolve_bmw_ci_python(state, workspace=workspace)
    if python_path is None:
        if not repo_roots:
            detail += " No BMW Git worktree was found for the venv target."
        return _status_item(
            key="bmw_ci_requirements",
            label="BMW CI Python requirements",
            status="missing",
            detail=detail,
            path=target_venv_python,
            confluence_anchor=BMW_ENV_CONFLUENCE_ANCHOR,
            setup_action=action,
        )
    imports_ok, probe_detail = _probe_bmw_ci_python(python_path)
    if not imports_ok:
        return _status_item(
            key="bmw_ci_requirements",
            label="BMW CI Python requirements",
            status="incomplete",
            detail=f"{python_path} cannot import yaml and PIL yet. {probe_detail}",
            path=python_path,
            confluence_anchor=BMW_ENV_CONFLUENCE_ANCHOR,
            setup_action=action,
        )
    if source == "venv":
        _auto_register_dependency_path(state, workspace=workspace, key="bmw_pipeline_python", path=python_path)
    return _status_item(
        key="bmw_ci_requirements",
        label="BMW CI Python requirements",
        status="available",
        detail=f"{python_path} can import yaml and PIL.",
        path=python_path,
        confluence_anchor=BMW_ENV_CONFLUENCE_ANCHOR,
        setup_action={},
    )


def _bmw_repo_status(state: dict[str, Any], workspace: Path, bmw_root: Path | str | None) -> dict[str, Any]:
    explicit_env = os.environ.get(DIGITAL_3D_CAR_REPO_ENV, "").strip()
    candidate = _existing_dir(_candidate_bmw_repo_paths(workspace, state, bmw_root))
    git_path = _find_executable("git.exe") or _find_executable("git")
    lfs_path = _find_executable("git-lfs.exe") or _find_executable("git-lfs")
    effects = [
        "Clones the BMW models repository into an operator-chosen local folder when no checkout exists.",
        f"Sets the user environment variable {DIGITAL_3D_CAR_REPO_ENV} with setx after confirmation.",
        "Does not write into the BMW repository contents.",
    ]
    action_id = "setup-digital-3d-car-repo" if candidate is not None else "clone-digital-3d-car-repo"
    action_label = "Set up BMW Git env" if candidate is not None else "Clone BMW Git checkout"
    clone_can_run = candidate is None and git_path is not None and lfs_path is not None
    command_preview = (
        f'setx {DIGITAL_3D_CAR_REPO_ENV} "{candidate}"'
        if candidate is not None
        else f'git clone {BMW_MODELS_REPO_URL} "<target>\\digital-3d-car-models"'
    )
    default_target = candidate if candidate is not None else Path(r"C:\3D Car git\digital-3d-car-models")
    action = _setup_action(
        action_id=action_id,
        label=action_label,
        dependency_key="digital_3d_car_repo",
        status="available" if (candidate is not None or clone_can_run) else "incomplete",
        confirmation_message=(
            f"Configure {DIGITAL_3D_CAR_REPO_ENV} for the local digital-3d-car-models checkout. "
            "If the checkout is missing, clone only after BMW Git access and credentials are available."
        ),
        effects=effects,
        confluence_anchor=BMW_ENV_CONFLUENCE_ANCHOR,
        can_run_now=(candidate is not None and sys.platform == "win32") or clone_can_run,
        command_preview=command_preview,
        target_path=default_target,
        operator_inputs=["Choose the local clone folder if no checkout is detected."],
    )
    if candidate is None:
        detail = "digital-3d-car-models checkout was not found locally."
        if git_path is None:
            detail += " Git was not found; install Git and Git LFS before cloning."
        elif lfs_path is None:
            detail += " Git LFS was not found; install Git LFS before cloning."
        return _status_item(
            key="digital_3d_car_repo",
            label=f"{DIGITAL_3D_CAR_REPO_ENV}",
            status="missing",
            detail=detail,
            confluence_anchor=BMW_GIT_CONFLUENCE_ANCHOR,
            setup_action=action,
        )
    if not (candidate / "cars" / "BMW").is_dir():
        return _status_item(
            key="digital_3d_car_repo",
            label=f"{DIGITAL_3D_CAR_REPO_ENV}",
            status="incomplete",
            detail="The detected checkout does not expose cars/BMW.",
            path=candidate,
            confluence_anchor=BMW_ENV_CONFLUENCE_ANCHOR,
            setup_action=action,
        )
    _auto_register_dependency_path(state, workspace=workspace, key="digital_3d_car_repo", path=candidate)
    detail = "BMW Git models checkout is available for read-only local evidence."
    if not explicit_env:
        detail += f" Existing checkout detected; {DIGITAL_3D_CAR_REPO_ENV} setup is optional for future shells."
    return _status_item(
        key="digital_3d_car_repo",
        label=f"{DIGITAL_3D_CAR_REPO_ENV}",
        status="available",
        detail=detail,
        path=candidate,
        confluence_anchor=BMW_ENV_CONFLUENCE_ANCHOR,
        setup_action={},
    )


def _idc23_repo_status(state: dict[str, Any], workspace: Path, bmw_root: Path | str | None) -> dict[str, Any]:
    main_root = _existing_dir(_candidate_bmw_repo_paths(workspace, state, bmw_root))
    candidate = _existing_dir(_candidate_idc23_repo_paths(workspace, state, bmw_root))
    candidate_status, candidate_detail = _idc23_worktree_check(candidate)
    target_path = candidate if candidate is not None else _default_idc23_worktree_target(main_root, workspace)
    git_path = _find_executable("git.exe") or _find_executable("git")
    effects = [
        "Runs git worktree add for the assets/idc23 branch only after operator confirmation.",
        f"Sets the user environment variable {DIGITAL_3D_CAR_REPO_IDC23_ENV} with setx on Windows.",
        "Verifies ci/scripts/test/main.py and cars/BMW/_Shared before recording the path.",
        "Records the IDC_23 worktree path in operator_state/dependency_onboarding.json.",
        "Does not modify BMW source files, SVN, or Jira.",
    ]
    command_preview = f'git -C "<{DIGITAL_3D_CAR_REPO_ENV}>" worktree add "{target_path}" assets/idc23'
    if sys.platform == "win32":
        command_preview += f' && setx {DIGITAL_3D_CAR_REPO_IDC23_ENV} "{target_path}"'
    action = _setup_action(
        action_id="setup-digital-3d-car-repo-idc23",
        label="Set up IDC_23 worktree",
        dependency_key="digital_3d_car_repo_idc23",
        status="available" if (_valid_bmw_repo_root(main_root) and git_path is not None) else "incomplete",
        confirmation_message=(
            "Create or register the separate assets/idc23 BMW Git worktree for IDC_23 pipeline commands. "
            "This setup records local paths only after the worktree structure is verified."
        ),
        effects=effects,
        confluence_anchor=IDC23_WORKTREE_CONFLUENCE_ANCHOR,
        can_run_now=_valid_bmw_repo_root(main_root) and git_path is not None,
        command_preview=command_preview,
        target_path=target_path,
        source_path=main_root,
        operator_inputs=[
            "Choose the local target folder for the assets/idc23 worktree.",
            f"Confirm {DIGITAL_3D_CAR_REPO_ENV} points at the master BMW Git checkout before running.",
        ],
    )
    if candidate_status == "available" and candidate is not None:
        _auto_register_dependency_path(
            state,
            workspace=workspace,
            key="digital_3d_car_repo_idc23",
            path=candidate,
        )
        _auto_register_dependency_path(
            state,
            workspace=workspace,
            key="digital_3d_car_repo_assets_idc23",
            path=candidate,
        )
        return _status_item(
            key="digital_3d_car_repo_idc23",
            label=f"{DIGITAL_3D_CAR_REPO_IDC23_ENV}",
            status="available",
            detail=candidate_detail,
            path=candidate,
            confluence_anchor=IDC23_WORKTREE_CONFLUENCE_ANCHOR,
            setup_action={},
        )
    if main_root is None:
        candidate_detail += f" Configure {DIGITAL_3D_CAR_REPO_ENV} before creating the IDC_23 worktree."
    elif git_path is None:
        candidate_detail += " Git was not found; install Git before creating the IDC_23 worktree."
    return _status_item(
        key="digital_3d_car_repo_idc23",
        label=f"{DIGITAL_3D_CAR_REPO_IDC23_ENV}",
        status=candidate_status,
        detail=candidate_detail,
        path=candidate,
        confluence_anchor=IDC23_WORKTREE_CONFLUENCE_ANCHOR,
        setup_action=action,
    )


def _run_bmw_env_setup(
    *,
    action_id: str,
    workspace: Path,
    action: dict[str, Any],
    target_path: Path | str | None,
    source_path: Path | str | None,
    stream_output: bool,
) -> dict[str, Any]:
    del source_path, stream_output
    raw_target = str(target_path or action.get("target_path", "")).strip()
    if not raw_target:
        return _setup_result(
            status="missing",
            action_id=action_id,
            summary="No local digital-3d-car-models checkout path was selected.",
        )
    repo_root = Path(raw_target).expanduser().resolve()
    if not (repo_root / "cars" / "BMW").is_dir():
        return _setup_result(
            status="incomplete",
            action_id=action_id,
            summary="Selected checkout does not expose cars/BMW.",
            path=repo_root,
        )
    if sys.platform != "win32":
        record_dependency_path(workspace=workspace, key="digital_3d_car_repo", path=repo_root)
        return _setup_result(
            status="recorded",
            action_id=action_id,
            summary=f"Recorded {DIGITAL_3D_CAR_REPO_ENV}; setx is available only on Windows.",
            path=repo_root,
        )
    try:
        completed = subprocess.run(
            ["setx", DIGITAL_3D_CAR_REPO_ENV, str(repo_root)],
            cwd=workspace,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
            **hidden_subprocess_kwargs(),
        )
    except subprocess.TimeoutExpired:
        return _setup_result(
            status="failed",
            action_id=action_id,
            summary="setx timed out while setting the BMW Git environment variable.",
            path=repo_root,
        )
    if completed.returncode != 0:
        return _setup_result(
            status="failed",
            action_id=action_id,
            summary=(completed.stderr or completed.stdout or "setx failed.").strip(),
            path=repo_root,
            exit_code=completed.returncode,
        )
    record_dependency_path(workspace=workspace, key="digital_3d_car_repo", path=repo_root)
    return _setup_result(
        status="recorded",
        action_id=action_id,
        summary=f"Recorded {DIGITAL_3D_CAR_REPO_ENV} for future shells.",
        path=repo_root,
        exit_code=completed.returncode,
    )


def _repo_root_from_target(target_path: Path | str | None) -> Path | None:
    raw_target = str(target_path or "").strip()
    if not raw_target:
        return None
    selected = Path(raw_target).expanduser().resolve()
    if selected.name.casefold() == "digital-3d-car-models":
        return selected
    return selected / "digital-3d-car-models"


def _run_bmw_clone_setup(
    *,
    action_id: str,
    workspace: Path,
    action: dict[str, Any],
    target_path: Path | str | None,
    source_path: Path | str | None,
    stream_output: bool,
) -> dict[str, Any]:
    del source_path
    repo_root = _repo_root_from_target(target_path or action.get("target_path", ""))
    if repo_root is None:
        return _setup_result(
            status="incomplete",
            action_id=action_id,
            summary="Choose a local target folder for the BMW Git clone before running setup.",
        )
    if repo_root.exists():
        if (repo_root / "cars" / "BMW").is_dir():
            return _run_bmw_env_setup(
                action_id="setup-digital-3d-car-repo",
                workspace=workspace,
                action={"target_path": str(repo_root)},
                target_path=repo_root,
                source_path=None,
                stream_output=stream_output,
            )
        return _setup_result(
            status="incomplete",
            action_id=action_id,
            summary="Target path already exists but does not expose cars/BMW.",
            path=repo_root,
        )
    git_path = _find_executable("git.exe") or _find_executable("git")
    lfs_path = _find_executable("git-lfs.exe") or _find_executable("git-lfs")
    if git_path is None:
        return _setup_result(
            status="missing",
            action_id=action_id,
            summary="Git was not found; install Git before cloning the BMW models repository.",
            path=repo_root,
        )
    if lfs_path is None:
        return _setup_result(
            status="missing",
            action_id=action_id,
            summary="Git LFS was not found; install Git LFS before cloning the BMW models repository.",
            path=repo_root,
        )
    try:
        repo_root.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return _setup_result(
            status="failed",
            action_id=action_id,
            summary=f"Could not create clone parent folder: {exc}",
            path=repo_root,
        )
    clone_command = [str(git_path), "clone", BMW_MODELS_REPO_URL, str(repo_root)]
    lfs_command = [str(git_path), "-C", str(repo_root), "lfs", "pull"]
    if stream_output:
        print(f"Running {' '.join(clone_command)}", flush=True)
        clone_result = subprocess.run(
            clone_command,
            cwd=repo_root.parent,
            stdin=subprocess.DEVNULL,
            text=True,
            timeout=DEPENDENCY_SETUP_TIMEOUT_SECONDS,
            **hidden_subprocess_kwargs(),
        )
        clone_output = ""
    else:
        clone_result = subprocess.run(
            clone_command,
            cwd=repo_root.parent,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=DEPENDENCY_SETUP_TIMEOUT_SECONDS,
            **hidden_subprocess_kwargs(),
        )
        clone_output = (clone_result.stderr or clone_result.stdout or "").strip()
    if clone_result.returncode != 0:
        return _setup_result(
            status="failed",
            action_id=action_id,
            summary=clone_output or f"BMW Git clone failed with exit code {clone_result.returncode}.",
            path=repo_root,
            exit_code=clone_result.returncode,
        )
    if stream_output:
        print(f"Running {' '.join(lfs_command)}", flush=True)
        lfs_result = subprocess.run(
            lfs_command,
            cwd=repo_root,
            stdin=subprocess.DEVNULL,
            text=True,
            timeout=DEPENDENCY_SETUP_TIMEOUT_SECONDS,
            **hidden_subprocess_kwargs(),
        )
        lfs_output = ""
    else:
        lfs_result = subprocess.run(
            lfs_command,
            cwd=repo_root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=DEPENDENCY_SETUP_TIMEOUT_SECONDS,
            **hidden_subprocess_kwargs(),
        )
        lfs_output = (lfs_result.stderr or lfs_result.stdout or "").strip()
    if lfs_result.returncode != 0:
        return _setup_result(
            status="failed",
            action_id=action_id,
            summary=lfs_output or f"Git LFS pull failed with exit code {lfs_result.returncode}.",
            path=repo_root,
            exit_code=lfs_result.returncode,
        )
    if not (repo_root / "cars" / "BMW").is_dir():
        return _setup_result(
            status="incomplete",
            action_id=action_id,
            summary="Clone completed, but cars/BMW was not found in the checkout.",
            path=repo_root,
        )
    return _run_bmw_env_setup(
        action_id="setup-digital-3d-car-repo",
        workspace=workspace,
        action={"target_path": str(repo_root)},
        target_path=repo_root,
        source_path=None,
        stream_output=stream_output,
    )


def _run_setx_for_idc23(workspace: Path, repo_root: Path, action_id: str) -> dict[str, Any]:
    if sys.platform != "win32":
        _record_idc23_repo_path(workspace=workspace, path=repo_root)
        return _setup_result(
            status="recorded",
            action_id=action_id,
            summary=f"Recorded {DIGITAL_3D_CAR_REPO_IDC23_ENV}; setx is available only on Windows.",
            path=repo_root,
            git_worktree_add_invoked=False,
            setx_invoked=False,
            shared_root_status="available",
        )
    try:
        completed = subprocess.run(
            ["setx", DIGITAL_3D_CAR_REPO_IDC23_ENV, str(repo_root)],
            cwd=workspace,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
            **hidden_subprocess_kwargs(),
        )
    except subprocess.TimeoutExpired:
        return _setup_result(
            status="failed",
            action_id=action_id,
            summary="setx timed out while setting the IDC_23 BMW Git environment variable.",
            path=repo_root,
            git_worktree_add_invoked=False,
            setx_invoked=True,
            shared_root_status="available",
        )
    if completed.returncode != 0:
        return _setup_result(
            status="failed",
            action_id=action_id,
            summary=(completed.stderr or completed.stdout or "setx failed.").strip(),
            path=repo_root,
            exit_code=completed.returncode,
            git_worktree_add_invoked=False,
            setx_invoked=True,
            shared_root_status="available",
        )
    _record_idc23_repo_path(workspace=workspace, path=repo_root)
    return _setup_result(
        status="recorded",
        action_id=action_id,
        summary=f"Recorded {DIGITAL_3D_CAR_REPO_IDC23_ENV} for future shells.",
        path=repo_root,
        exit_code=completed.returncode,
        git_worktree_add_invoked=False,
        setx_invoked=True,
        shared_root_status="available",
    )


def _run_bmw_idc23_setup(
    *,
    action_id: str,
    workspace: Path,
    action: dict[str, Any],
    target_path: Path | str | None,
    source_path: Path | str | None,
    stream_output: bool,
) -> dict[str, Any]:
    raw_target = str(target_path or action.get("target_path", "")).strip()
    if not raw_target:
        return _setup_result(
            status="incomplete",
            action_id=action_id,
            summary="Choose the local target folder for the IDC_23 assets/idc23 worktree before running setup.",
        )
    target = Path(raw_target).expanduser().resolve()
    state = load_dependency_onboarding_state(workspace)
    raw_base = str(source_path or action.get("source_path", "")).strip()
    base_repo = Path(raw_base).expanduser().resolve() if raw_base else _existing_dir(
        _candidate_bmw_repo_paths(workspace, state, None)
    )
    if not _valid_bmw_repo_root(base_repo):
        return _setup_result(
            status="incomplete",
            action_id=action_id,
            summary=f"Configure {DIGITAL_3D_CAR_REPO_ENV} before creating the IDC_23 worktree.",
            path=target,
            git_worktree_add_invoked=False,
            setx_invoked=False,
            shared_root_status="unknown",
        )
    current_status, current_detail = _idc23_worktree_check(target if target.exists() else None)
    if current_status == "available":
        result = _run_setx_for_idc23(workspace, target, action_id)
        result["summary"] = f"Existing IDC_23 worktree verified. {result['summary']}"
        return result
    if target.exists():
        return _setup_result(
            status="incomplete",
            action_id=action_id,
            summary=current_detail,
            path=target,
            git_worktree_add_invoked=False,
            setx_invoked=False,
            shared_root_status="missing" if not (target / "cars" / "BMW" / "_Shared").is_dir() else "available",
        )
    git_path = _find_executable("git.exe") or _find_executable("git")
    if git_path is None:
        return _setup_result(
            status="missing",
            action_id=action_id,
            summary="Git was not found; install Git before creating the IDC_23 worktree.",
            path=target,
            git_worktree_add_invoked=False,
            setx_invoked=False,
            shared_root_status="unknown",
        )
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return _setup_result(
            status="failed",
            action_id=action_id,
            summary=f"Could not create IDC_23 worktree parent folder: {exc}",
            path=target,
            git_worktree_add_invoked=False,
            setx_invoked=False,
            shared_root_status="unknown",
        )
    command = [str(git_path), "-C", str(base_repo), "worktree", "add", str(target), "assets/idc23"]
    if stream_output:
        print(f"Running {' '.join(command)}", flush=True)
        completed = subprocess.run(
            command,
            cwd=base_repo,
            stdin=subprocess.DEVNULL,
            text=True,
            timeout=DEPENDENCY_SETUP_TIMEOUT_SECONDS,
            **hidden_subprocess_kwargs(),
        )
        output = ""
    else:
        completed = subprocess.run(
            command,
            cwd=base_repo,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=DEPENDENCY_SETUP_TIMEOUT_SECONDS,
            **hidden_subprocess_kwargs(),
        )
        output = (completed.stderr or completed.stdout or "").strip()
    if completed.returncode != 0:
        return _setup_result(
            status="failed",
            action_id=action_id,
            summary=output or f"IDC_23 git worktree add failed with exit code {completed.returncode}.",
            path=target,
            exit_code=completed.returncode,
            git_worktree_add_invoked=True,
            setx_invoked=False,
            shared_root_status="unknown",
        )
    status, detail = _idc23_worktree_check(target)
    if status != "available":
        return _setup_result(
            status="incomplete",
            action_id=action_id,
            summary=detail,
            path=target,
            exit_code=completed.returncode,
            git_worktree_add_invoked=True,
            setx_invoked=False,
            shared_root_status="missing" if not (target / "cars" / "BMW" / "_Shared").is_dir() else "available",
        )
    result = _run_setx_for_idc23(workspace, target, action_id)
    result["git_worktree_add_invoked"] = True
    result["summary"] = f"IDC_23 worktree created and verified. {result['summary']}"
    return result


def _base_python_for_bmw_ci_venv() -> Path | None:
    if not getattr(sys, "frozen", False):
        candidate = Path(sys.executable).expanduser()
        if candidate.is_file():
            return candidate.resolve()
    override = os.environ.get(BMW_PIPELINE_PYTHON_ENV, "").strip()
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_file():
            return candidate.resolve()
    for launcher_name in ("py.exe", "py"):
        launcher = _find_executable(launcher_name)
        if launcher is None or not launcher.is_file():
            continue
        try:
            completed = subprocess.run(
                [str(launcher), "-3.13", "-c", "import sys; print(sys.executable)"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30,
                check=False,
                **hidden_subprocess_kwargs(),
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if completed.returncode != 0:
            continue
        output_lines = (completed.stdout or "").strip().splitlines()
        if not output_lines:
            continue
        candidate = Path(output_lines[-1]).expanduser()
        if candidate.is_file():
            return candidate.resolve()
    for executable_name in ("python.exe", "python", "py.exe", "py", "python3.exe", "python3"):
        candidate = _find_executable(executable_name)
        if candidate is not None and candidate.is_file():
            return candidate.resolve()
    return None


def _run_dependency_setup_command(
    command: list[str],
    *,
    cwd: Path,
    stream_output: bool,
    timeout_seconds: int = DEPENDENCY_SETUP_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    if stream_output:
        print(f"Running {' '.join(command)}", flush=True)
        return subprocess.run(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            text=True,
            timeout=timeout_seconds,
            check=False,
            **hidden_subprocess_kwargs(),
        )
    return subprocess.run(
        command,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout_seconds,
        check=False,
        **hidden_subprocess_kwargs(),
    )


def _command_output_tail(completed: subprocess.CompletedProcess[str], limit: int = 1600) -> str:
    output = "\n".join(part for part in (completed.stderr, completed.stdout) if part)
    output = output.strip()
    return output[-limit:] if len(output) > limit else output


def _run_bmw_ci_requirements_setup(
    *,
    action_id: str,
    workspace: Path,
    action: dict[str, Any],
    target_path: Path | str | None,
    source_path: Path | str | None,
    stream_output: bool,
) -> dict[str, Any]:
    del source_path
    base_python = _base_python_for_bmw_ci_venv()
    if base_python is None:
        return _setup_result(
            status="missing",
            action_id=action_id,
            summary=(
                "No real Python found to build the BMW CI venv; "
                f"set {BMW_PIPELINE_PYTHON_ENV} or install Python."
            ),
        )
    state = load_dependency_onboarding_state(workspace)
    selected_target = Path(str(target_path or action.get("target_path", ""))).expanduser().resolve() if (
        target_path or action.get("target_path")
    ) else None
    repo_roots = _unique_existing_bmw_repo_roots(workspace=workspace, state=state, bmw_root=selected_target)
    if selected_target is not None and selected_target.is_dir():
        normalized = {os.path.normcase(str(root)) for root in repo_roots}
        if os.path.normcase(str(selected_target)) not in normalized:
            repo_roots.insert(0, selected_target)
    if not repo_roots:
        return _setup_result(
            status="missing",
            action_id=action_id,
            summary="No BMW Git worktree was found for BMW CI requirements setup.",
        )
    requirements_paths = _bmw_ci_requirements_paths(repo_roots)
    missing_requirements = [
        str(root / BMW_CI_REQUIREMENTS_RELATIVE_PATH)
        for root in repo_roots
        if not (root / BMW_CI_REQUIREMENTS_RELATIVE_PATH).is_file()
    ]
    if not requirements_paths:
        return _setup_result(
            status="incomplete",
            action_id=action_id,
            summary="No ci/scripts/requirements.txt file was found in the available BMW worktrees.",
            path=repo_roots[0],
            missing_requirements=missing_requirements,
        )
    target_repo = requirements_paths[0].parents[2]
    venv_root = target_repo / BMW_CI_VENV_DIRNAME
    venv_python = _bmw_ci_venv_python(target_repo)
    try:
        venv_root.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return _setup_result(
            status="failed",
            action_id=action_id,
            summary=f"Could not create BMW CI venv parent folder: {exc}",
            path=venv_root,
        )
    venv_command = [str(base_python), "-m", "venv", "--clear", str(venv_root)]
    try:
        venv_result = _run_dependency_setup_command(venv_command, cwd=target_repo, stream_output=stream_output)
    except subprocess.TimeoutExpired:
        return _setup_result(
            status="failed",
            action_id=action_id,
            summary="Creating the BMW CI venv timed out.",
            path=venv_root,
        )
    if venv_result.returncode != 0:
        return _setup_result(
            status="failed",
            action_id=action_id,
            summary=_command_output_tail(venv_result) or f"venv creation failed with exit code {venv_result.returncode}.",
            path=venv_root,
            exit_code=venv_result.returncode,
        )
    if not venv_python.is_file():
        return _setup_result(
            status="incomplete",
            action_id=action_id,
            summary="BMW CI venv creation completed, but the venv Python was not found.",
            path=venv_python,
            missing_requirements=missing_requirements,
        )
    installed_requirements: list[str] = []
    for requirements_path in requirements_paths:
        pip_command = [str(venv_python), "-m", "pip", "install", "-r", str(requirements_path)]
        try:
            pip_result = _run_dependency_setup_command(
                pip_command,
                cwd=requirements_path.parent,
                stream_output=stream_output,
            )
        except subprocess.TimeoutExpired:
            return _setup_result(
                status="failed",
                action_id=action_id,
                summary=f"pip install timed out for {requirements_path}.",
                path=venv_python,
                installed_requirements=installed_requirements,
                missing_requirements=missing_requirements,
            )
        if pip_result.returncode != 0:
            return _setup_result(
                status="failed",
                action_id=action_id,
                summary=_command_output_tail(pip_result) or f"pip install failed for {requirements_path}.",
                path=venv_python,
                exit_code=pip_result.returncode,
                failed_requirements=str(requirements_path),
                installed_requirements=installed_requirements,
                missing_requirements=missing_requirements,
            )
        installed_requirements.append(str(requirements_path))
    imports_ok, probe_detail = _probe_bmw_ci_python(venv_python)
    if not imports_ok:
        return _setup_result(
            status="incomplete",
            action_id=action_id,
            summary=f"Installed BMW CI requirements, but yaml/PIL import probe still fails. {probe_detail}",
            path=venv_python,
            installed_requirements=installed_requirements,
            missing_requirements=missing_requirements,
        )
    record_dependency_path(workspace=workspace, key="bmw_pipeline_python", path=venv_python)
    missing_note = f" Missing requirements files were skipped: {len(missing_requirements)}." if missing_requirements else ""
    return _setup_result(
        status="recorded",
        action_id=action_id,
        summary=f"Recorded BMW CI Python with yaml/PIL available.{missing_note}",
        path=venv_python,
        installed_requirements=installed_requirements,
        missing_requirements=missing_requirements,
    )


# Re-resolve collaborators through the live `dependency_onboarding` facade on
# every call, so `mock.patch.object(dependency_onboarding, "_name", ...)`
# keeps intercepting now that callers and callees can live in different files.
_candidate_bmw_repo_paths = _with_onboarding_globals(_candidate_bmw_repo_paths)
_valid_bmw_repo_root = _with_onboarding_globals(_valid_bmw_repo_root)
_candidate_idc23_repo_paths = _with_onboarding_globals(_candidate_idc23_repo_paths)
_default_idc23_worktree_target = _with_onboarding_globals(_default_idc23_worktree_target)
_idc23_worktree_check = _with_onboarding_globals(_idc23_worktree_check)
_record_idc23_repo_path = _with_onboarding_globals(_record_idc23_repo_path)
_bmw_ci_venv_python = _with_onboarding_globals(_bmw_ci_venv_python)
_unique_existing_bmw_repo_roots = _with_onboarding_globals(_unique_existing_bmw_repo_roots)
_resolve_bmw_ci_python = _with_onboarding_globals(_resolve_bmw_ci_python)
_probe_bmw_ci_python = _with_onboarding_globals(_probe_bmw_ci_python)
_bmw_ci_requirements_paths = _with_onboarding_globals(_bmw_ci_requirements_paths)
_bmw_ci_requirements_status = _with_onboarding_globals(_bmw_ci_requirements_status)
_bmw_repo_status = _with_onboarding_globals(_bmw_repo_status)
_idc23_repo_status = _with_onboarding_globals(_idc23_repo_status)
_run_bmw_env_setup = _with_onboarding_globals(_run_bmw_env_setup)
_repo_root_from_target = _with_onboarding_globals(_repo_root_from_target)
_run_bmw_clone_setup = _with_onboarding_globals(_run_bmw_clone_setup)
_run_setx_for_idc23 = _with_onboarding_globals(_run_setx_for_idc23)
_run_bmw_idc23_setup = _with_onboarding_globals(_run_bmw_idc23_setup)
_base_python_for_bmw_ci_venv = _with_onboarding_globals(_base_python_for_bmw_ci_venv)
_run_dependency_setup_command = _with_onboarding_globals(_run_dependency_setup_command)
_command_output_tail = _with_onboarding_globals(_command_output_tail)
_run_bmw_ci_requirements_setup = _with_onboarding_globals(_run_bmw_ci_requirements_setup)
