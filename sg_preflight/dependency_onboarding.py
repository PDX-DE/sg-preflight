from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any
import urllib.request
import zipfile

from sg_preflight.subprocess_utils import hidden_subprocess_kwargs
from sg_preflight.utils import ensure_parent


DIGITAL_3D_CAR_REPO_ENV = "Digital-3D-Car-Repo"
ONBOARDING_STATE_FILENAME = "dependency_onboarding.json"
RACO_BASELINE_VERSION = "2.3.1"
BLENDER_BASELINE_VERSION = "4.1.1"
BLENDER_INSTALLER_URL = "https://download.blender.org/release/Blender4.1/blender-4.1.1-windows-x64.msi"
BLENDER_INSTALLER_FILENAME = "blender-4.1.1-windows-x64.msi"
BMW_MODELS_REPO_URL = "https://cc-github.bmwgroup.net/apinext/digital-3d-car-models.git"
DEPENDENCY_SETUP_TIMEOUT_SECONDS = 900
DEPENDENCY_SETUP_STDOUT_TAIL_LINES = 20
DEPENDENCY_SETUP_STDOUT_TAIL_BYTES = 2000
DEPENDENCY_SETUP_FILE_ACTIVITY_LIMIT = 20
RACO_SETUP_TYPICAL_RANGE_LABEL = "typical ~30 sec"
BLENDER_SETUP_TYPICAL_RANGE_LABEL = "typical ~2 min"
BMW_GIT_SETUP_TYPICAL_RANGE_LABEL = "typical ~2-10 min"
ENV_SETUP_TYPICAL_RANGE_LABEL = "typical <30 sec"

RACO_CONFLUENCE_ANCHOR = "003_Onboarding/005_How-to-set-up-your-Laptop:190-204"
BLENDER_CONFLUENCE_ANCHOR = (
    "139_3D-Car/252_3D-car---3D-Crew/253_How-to-3D/"
    "266_How-to-Setup-Blender-4-and-SGToolkit-1.0:1-18"
)
BMW_GIT_CONFLUENCE_ANCHOR = "003_Onboarding/013_How-to-access-BMW-GIT:20-126"
BMW_ENV_CONFLUENCE_ANCHOR = (
    "311_Delivery-process/312_3D-Car---Delivery-and-Integration/"
    "315_How-to-3D-Cars-Delivery-Checklist----v0:50-54"
)
RACO_HEADLESS_CONFLUENCE_ANCHOR = (
    "139_3D-Car/225_3D-Car---RaCo-Implementation/"
    "249_How-to-use-the-various-python-scripts-fo:170-190"
)

_DEPENDENCY_ORDER = ("raco_gui", "raco_headless", "blender", "digital_3d_car_repo")
_KNOWN_REGISTERED_PATHS = {
    "raco_gui",
    "raco_headless",
    "blender",
    "digital_3d_car_repo",
    "digital_3d_car_repo_idc23",
    "digital_3d_car_repo_assets_idc23",
}
_BASELINE_SOURCE_NOTE = (
    "Re-read the Confluence dump before changing dependency baselines; versions can move during daily sync."
)
_SETUP_ACTION_TYPICAL_RANGES = {
    "setup-raco-from-shared-tools": RACO_SETUP_TYPICAL_RANGE_LABEL,
    "setup-blender-411": BLENDER_SETUP_TYPICAL_RANGE_LABEL,
    "clone-digital-3d-car-repo": BMW_GIT_SETUP_TYPICAL_RANGE_LABEL,
    "setup-digital-3d-car-repo": ENV_SETUP_TYPICAL_RANGE_LABEL,
}


@dataclass
class DependencySetupJob:
    action_id: str
    workspace: Path
    process: subprocess.Popen[bytes]
    command: list[str]
    stdout_path: Path
    stderr_path: Path
    started_monotonic: float
    started_wall_time: float
    timeout_seconds: int
    typical_range: str
    target_path: Path | None = None
    source_path: Path | None = None
    completed: bool = False


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _workspace(workspace: Path | str) -> Path:
    return Path(workspace).resolve()


def operator_state_root(workspace: Path | str) -> Path:
    return _workspace(workspace) / "operator_state"


def dependency_onboarding_state_path(workspace: Path | str) -> Path:
    return operator_state_root(workspace) / ONBOARDING_STATE_FILENAME


def has_operator_state(workspace: Path | str) -> bool:
    root = operator_state_root(workspace)
    if not root.exists():
        return False
    try:
        return any(root.iterdir())
    except OSError:
        return False


def load_dependency_onboarding_state(workspace: Path | str) -> dict[str, Any]:
    path = dependency_onboarding_state_path(workspace)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_dependency_onboarding_state(workspace: Path | str, state: dict[str, Any]) -> dict[str, Any]:
    state["updated_at_utc"] = _utc_now()
    output_path = dependency_onboarding_state_path(workspace)
    ensure_parent(output_path)
    temp_path = output_path.with_name(f".{output_path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    temp_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(output_path)
    return state


def record_dependency_path(*, workspace: Path | str, key: str, path: Path | str) -> dict[str, Any]:
    clean_key = key.strip()
    if clean_key not in _KNOWN_REGISTERED_PATHS:
        raise KeyError(f"Unsupported dependency key: {key}")
    target = Path(path).expanduser().resolve()
    state = load_dependency_onboarding_state(workspace)
    registered_paths = state.setdefault("registered_paths", {})
    if not isinstance(registered_paths, dict):
        registered_paths = {}
        state["registered_paths"] = registered_paths
    registered_paths[clean_key] = str(target)
    state["source"] = "dependency onboarding"
    return _write_dependency_onboarding_state(workspace, state)


def _same_registered_path(current: Path | None, target: Path) -> bool:
    if current is None:
        return False
    try:
        return os.path.normcase(str(current.expanduser().resolve())) == os.path.normcase(str(target.resolve()))
    except (OSError, RuntimeError):
        try:
            current_text = str(current.expanduser())
        except RuntimeError:
            current_text = str(current)
        return os.path.normcase(current_text) == os.path.normcase(str(target))


def _auto_register_dependency_path(
    state: dict[str, Any],
    *,
    workspace: Path | str,
    key: str,
    path: Path | str | None,
) -> bool:
    clean_key = key.strip()
    if clean_key not in _KNOWN_REGISTERED_PATHS or path is None:
        return False
    target = Path(path).expanduser().resolve()
    if _same_registered_path(_registered_path(state, clean_key), target):
        return False
    registered_paths = state.setdefault("registered_paths", {})
    if not isinstance(registered_paths, dict):
        registered_paths = {}
        state["registered_paths"] = registered_paths
    registered_paths[clean_key] = str(target)
    state["source"] = str(state.get("source") or "dependency onboarding fast-path")
    state["last_auto_registered_key"] = clean_key
    _write_dependency_onboarding_state(workspace, state)
    return True


def _registered_path(state: dict[str, Any], key: str) -> Path | None:
    registered_paths = state.get("registered_paths", {})
    if not isinstance(registered_paths, dict):
        return None
    raw = str(registered_paths.get(key, "")).strip()
    return Path(raw).expanduser() if raw else None


def _existing_file(candidates: list[Path | None]) -> Path | None:
    seen: set[str] = set()
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            path = candidate.expanduser()
        except RuntimeError:
            continue
        normalized = str(path).casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        if path.is_file():
            return path.resolve()
    return None


def _existing_dir(candidates: list[Path | None]) -> Path | None:
    seen: set[str] = set()
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            path = candidate.expanduser()
        except RuntimeError:
            continue
        normalized = str(path).casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        if path.is_dir():
            return path.resolve()
    return None


def _env_path(keys: tuple[str, ...]) -> Path | None:
    for key in keys:
        raw = os.environ.get(key, "").strip()
        if raw:
            return Path(raw).expanduser()
    return None


def _find_executable(executable_name: str) -> Path | None:
    found = shutil.which(executable_name)
    if found:
        return Path(found).resolve()
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:
        return None
    subkey = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{executable_name}"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, subkey) as key:
                value, _kind = winreg.QueryValueEx(key, "")
        except OSError:
            continue
        candidate = Path(str(value).strip('"'))
        if candidate.is_file():
            return candidate.resolve()
    return None


def _glob_dirs(parent: Path, pattern: str, limit: int = 12) -> list[Path]:
    if not parent.is_dir():
        return []
    try:
        return [path for path in sorted(parent.glob(pattern)) if path.is_dir()][:limit]
    except OSError:
        return []


def _raco_install_roots(workspace: Path) -> list[Path]:
    roots: list[Path] = [
        workspace / "external" / "ramses",
        workspace.parent / "RamsesComposerWindows",
        Path(r"C:\dev\software\RamsesComposerWindows_v2.3.1"),
        Path(r"C:\dev\software\RamsesComposerWindows"),
        Path(r"C:\RamsesComposerWindows"),
    ]
    roots.extend(_glob_dirs(Path(r"C:\dev\software"), "RamsesComposer*"))
    return roots


def _raco_executable_candidates(
    workspace: Path,
    executable_name: str,
    preferred: Path | None,
    registered: Path | None = None,
) -> list[Path | None]:
    roots = _raco_install_roots(workspace)
    candidates: list[Path | None] = [preferred, _find_executable(executable_name)]
    for root in roots:
        candidates.extend(
            [
                root / "bin" / "RelWithDebInfo" / executable_name,
                root / executable_name,
            ]
        )
    candidates.append(registered)
    return candidates


def _onedrive_raco_sources() -> list[Path]:
    env_source = _env_path(("SG_RACO_ONEDRIVE_TOOLS", "SG_RACO_SOURCE_DIR"))
    try:
        home = Path.home()
    except RuntimeError:
        return [env_source] if env_source is not None else []
    candidates: list[Path | None] = [
        env_source,
        home / "Documents" / "Tools" / "Ramses_Composer_Current",
        home / "OneDrive" / "Tools" / "Ramses_Composer_Current",
        home / "OneDrive" / "Documents" / "Tools" / "Ramses_Composer_Current",
    ]
    for parent in _glob_dirs(home, "OneDrive*"):
        candidates.extend(
            [
                parent / "Tools" / "Ramses_Composer_Current",
                parent / "Documents" / "Tools" / "Ramses_Composer_Current",
            ]
        )
    return [candidate for candidate in candidates if candidate is not None]


def _raco_source_detail() -> tuple[str, Path | None]:
    source = _existing_dir(_onedrive_raco_sources())
    if source is None:
        return (
            "Team shared Ramses_Composer_Current folder was not found locally; use the documented OneDrive Tools folder.",
            None,
        )
    return f"Team shared Ramses_Composer_Current folder is available at {source}.", source


def _status_item(
    *,
    key: str,
    label: str,
    status: str,
    detail: str,
    path: Path | str | None = None,
    confluence_anchor: str,
    setup_action: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "detail": detail,
        "path": str(path or ""),
        "confluence_anchor": confluence_anchor,
        "setup_action": setup_action or {},
    }


def _setup_action(
    *,
    action_id: str,
    label: str,
    dependency_key: str,
    status: str,
    confirmation_message: str,
    effects: list[str],
    confluence_anchor: str,
    can_run_now: bool = False,
    command_preview: str = "",
    target_path: Path | str | None = None,
    source_path: Path | str | None = None,
    requires_admin: bool = False,
    operator_inputs: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": action_id,
        "label": label,
        "dependency_key": dependency_key,
        "status": status,
        "requires_confirmation": True,
        "confirmation_message": confirmation_message,
        "effects": effects,
        "confluence_anchor": confluence_anchor,
        "can_run_now": can_run_now,
        "command_preview": command_preview,
        "target_path": str(target_path or ""),
        "source_path": str(source_path or ""),
        "requires_admin": requires_admin,
        "operator_inputs": operator_inputs or [],
    }


def _windows_admin_status() -> str:
    if sys.platform != "win32":
        return "unknown"
    try:
        import ctypes

        return "available" if bool(ctypes.windll.shell32.IsUserAnAdmin()) else "missing"
    except Exception:  # noqa: BLE001
        return "unknown"


def _raco_status(state: dict[str, Any], workspace: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    gui = _existing_file(
        _raco_executable_candidates(
            workspace,
            "RamsesComposer.exe",
            _env_path(("SG_RACO_GUI", "SG_RACO_EDITOR", "RACO_GUI_EXE")),
            _registered_path(state, "raco_gui"),
        )
    )
    headless = _existing_file(
        _raco_executable_candidates(
            workspace,
            "RaCoHeadless.exe",
            _env_path(("SG_RACO_HEADLESS", "RACO_HEADLESS_EXE")),
            _registered_path(state, "raco_headless"),
        )
    )
    source_detail, source_path = _raco_source_detail()
    _auto_register_dependency_path(state, workspace=workspace, key="raco_gui", path=gui)
    _auto_register_dependency_path(state, workspace=workspace, key="raco_headless", path=headless)
    action_status = "available" if source_path is not None else "incomplete"
    action = _setup_action(
        action_id="setup-raco-from-shared-tools",
        label="Set up RaCo",
        dependency_key="raco_gui",
        status=action_status,
        confirmation_message=(
            f"Copy or extract Ramses Composer {RACO_BASELINE_VERSION} from the documented shared Tools folder "
            "to C:\\dev\\software, then register the GUI and headless executables in operator state."
        ),
        effects=[
            r"Copies or extracts files under C:\dev\software.",
            "Records RamsesComposer.exe and RaCoHeadless.exe paths in operator_state/dependency_onboarding.json.",
            "Does not modify BMW Git, SVN, or Jira.",
        ],
        confluence_anchor=RACO_CONFLUENCE_ANCHOR,
        can_run_now=source_path is not None,
        command_preview=(
            f'copy/extract "{source_path}" "C:\\dev\\software"'
            if source_path is not None
            else 'copy/extract "<Ramses_Composer_Current>" "C:\\dev\\software"'
        ),
        target_path=Path(r"C:\dev\software"),
        source_path=source_path,
        operator_inputs=["Select the shared zip/folder if the OneDrive probe is missing."],
    )
    gui_item = _status_item(
        key="raco_gui",
        label="Ramses Composer GUI",
        status="available" if gui is not None else "missing",
        detail=(
            "RamsesComposer.exe is available from an existing local install; "
            "the documented OneDrive Tools folder is only a fallback for missing installs."
        )
        if gui is not None
        else source_detail,
        path=gui,
        confluence_anchor=RACO_CONFLUENCE_ANCHOR,
        setup_action={} if gui is not None else action,
    )
    headless_action = dict(action)
    headless_action["dependency_key"] = "raco_headless"
    headless_action["confluence_anchor"] = RACO_HEADLESS_CONFLUENCE_ANCHOR
    headless_item = _status_item(
        key="raco_headless",
        label="RaCoHeadless",
        status="available" if headless is not None else "missing",
        detail=(
            "RaCoHeadless.exe is available from an existing local install; "
            "the documented OneDrive Tools folder is only a fallback for missing installs."
        )
        if headless is not None
        else source_detail,
        path=headless,
        confluence_anchor=RACO_HEADLESS_CONFLUENCE_ANCHOR,
        setup_action={} if headless is not None else headless_action,
    )
    return gui_item, headless_item


def _blender_path_candidates(state: dict[str, Any], workspace: Path) -> list[Path | None]:
    registered = _registered_path(state, "blender")
    candidates: list[Path | None] = [
        _env_path(("SG_BLENDER_EXE", "BLENDER_EXE")),
        _find_executable("blender.exe"),
        workspace / "external" / "blender" / "blender.exe",
        workspace.parent / "Blender" / "blender.exe",
        Path(r"C:\Program Files\Blender Foundation\Blender 4.1\blender.exe"),
    ]
    foundation = Path(r"C:\Program Files\Blender Foundation")
    for child in _glob_dirs(foundation, "Blender 4.*"):
        candidates.append(child / "blender.exe")
    candidates.append(registered)
    return candidates


def _blender_disallowed(path: Path) -> bool:
    value = str(path).casefold()
    return any(token in value for token in ("blender 4.2", "blender 4.3", "blender 4.4", "blender 4.5"))


def _blender_status(state: dict[str, Any], workspace: Path) -> dict[str, Any]:
    candidate = _existing_file(_blender_path_candidates(state, workspace))
    admin_status = _windows_admin_status()
    action = _setup_action(
        action_id="setup-blender-411",
        label="Set up Blender",
        dependency_key="blender",
        status="incomplete" if admin_status == "missing" else "available",
        confirmation_message=(
            f"Install Blender {BLENDER_BASELINE_VERSION} with a visible installer and register blender.exe in operator state. "
            "Corporate IT approval may be required."
        ),
        effects=[
            "Downloads or opens the official Blender installer source after operator confirmation.",
            r"Installs under Program Files or another operator-approved folder.",
            "Records blender.exe in operator_state/dependency_onboarding.json.",
        ],
        confluence_anchor=BLENDER_CONFLUENCE_ANCHOR,
        command_preview=f'download {BLENDER_INSTALLER_URL}, run visible installer, then register "blender.exe"',
        requires_admin=admin_status == "missing",
        operator_inputs=[
            "Optional: select a local installer or blender.exe; leave blank to download the pinned official installer.",
            "Confirm IT/admin approval when the installer requests it.",
        ],
    )
    if candidate is None:
        return _status_item(
            key="blender",
            label="Blender",
            status="missing",
            detail=f"Blender {BLENDER_BASELINE_VERSION} was not found.",
            confluence_anchor=BLENDER_CONFLUENCE_ANCHOR,
            setup_action=action,
        )
    if _blender_disallowed(candidate):
        return _status_item(
            key="blender",
            label="Blender",
            status="incomplete",
            detail=f"{candidate} exists, but the Confluence page says not to use Blender 4.2 or greater.",
            path=candidate,
            confluence_anchor=BLENDER_CONFLUENCE_ANCHOR,
            setup_action=action,
        )
    _auto_register_dependency_path(state, workspace=workspace, key="blender", path=candidate)
    return _status_item(
        key="blender",
        label="Blender",
        status="available",
        detail=f"Blender executable is available; Confluence baseline is {BLENDER_BASELINE_VERSION}.",
        path=candidate,
        confluence_anchor=BLENDER_CONFLUENCE_ANCHOR,
        setup_action={},
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


def build_dependency_onboarding_status(
    *,
    workspace: Path | str,
    bmw_root: Path | str | None = None,
) -> dict[str, Any]:
    root = _workspace(workspace)
    first_run = not has_operator_state(root)
    state = load_dependency_onboarding_state(root)
    raco_gui, raco_headless = _raco_status(state, root)
    dependencies = {
        "raco_gui": raco_gui,
        "raco_headless": raco_headless,
        "blender": _blender_status(state, root),
        "digital_3d_car_repo": _bmw_repo_status(state, root, bmw_root),
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
        ],
        "guardrails": [
            "Manual review remains required.",
            "Decision: not approval — evidence only.",
            "BMW Git access is read-only. SGFX never modifies BMW source.",
            "Activity log is local-only — never posted to Jira, SVN, or BMW Git.",
        ],
    }


def _setup_result(
    *,
    status: str,
    action_id: str,
    summary: str,
    path: Path | str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": status,
        "action_id": action_id,
        "summary": summary,
        "recorded_by_tool": True,
        "is_approval": False,
    }
    if path is not None:
        payload["path"] = str(path)
    payload.update(extra)
    return payload


def _find_executable_under(root: Path, executable_name: str) -> Path | None:
    if not root.is_dir():
        return None
    matches: list[Path] = []
    try:
        for path in root.rglob(executable_name):
            if path.is_file():
                matches.append(path)
    except OSError:
        return None
    if not matches:
        return None
    matches.sort(key=lambda path: ("relwithdebinfo" not in str(path).casefold(), len(path.parts), str(path)))
    return matches[0].resolve()


def _safe_extract_zip(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    base = destination.resolve()
    with zipfile.ZipFile(source) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            try:
                target.relative_to(base)
            except ValueError as exc:
                raise ValueError(f"Refusing to extract zip entry outside target folder: {member.filename}") from exc
        archive.extractall(destination)


def _download_blender_installer(workspace: Path, *, stream_output: bool) -> Path:
    download_root = operator_state_root(workspace) / "dependency_setup" / "downloads"
    destination = download_root / BLENDER_INSTALLER_FILENAME
    if destination.is_file():
        if stream_output:
            print(f"Using cached Blender installer: {destination}", flush=True)
        return destination.resolve()
    ensure_parent(destination)
    temp_path = destination.with_name(f".{destination.name}.{os.getpid()}.{time.time_ns()}.tmp")
    if stream_output:
        print(f"Downloading Blender installer from {BLENDER_INSTALLER_URL}", flush=True)
    try:
        urllib.request.urlretrieve(BLENDER_INSTALLER_URL, str(temp_path))
        temp_path.replace(destination)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
    return destination.resolve()


def _resolve_raco_install_root(source: Path, target_root: Path) -> Path:
    if source.is_file():
        return target_root / source.stem
    try:
        source_resolved = source.resolve()
        target_resolved = target_root.resolve()
        source_resolved.relative_to(target_resolved)
        return source_resolved
    except (OSError, ValueError):
        return target_root / source.name


def _run_raco_setup(
    *,
    action_id: str,
    workspace: Path,
    action: dict[str, Any],
    target_path: Path | str | None,
    source_path: Path | str | None,
    stream_output: bool,
) -> dict[str, Any]:
    raw_source = str(source_path or action.get("source_path", "")).strip()
    if not raw_source:
        return _setup_result(
            status="incomplete",
            action_id=action_id,
            summary="Select the documented Ramses_Composer_Current zip or folder before running RaCo setup.",
        )
    source = Path(raw_source).expanduser().resolve()
    if not source.exists():
        return _setup_result(
            status="missing",
            action_id=action_id,
            summary="Selected Ramses Composer source path does not exist.",
            path=source,
        )
    raw_target = str(target_path or action.get("target_path", "") or r"C:\dev\software").strip()
    target_root = Path(raw_target).expanduser().resolve()
    install_root = _resolve_raco_install_root(source, target_root)
    try:
        if source.is_file():
            if source.suffix.casefold() != ".zip":
                return _setup_result(
                    status="incomplete",
                    action_id=action_id,
                    summary="Selected Ramses Composer source must be a zip archive or extracted folder.",
                    path=source,
                )
            if stream_output:
                print(f"Extracting RaCo archive to {install_root}", flush=True)
            if not install_root.exists():
                _safe_extract_zip(source, install_root)
        elif install_root.resolve() != source.resolve():
            if stream_output:
                print(f"Copying RaCo folder to {install_root}", flush=True)
            if not install_root.exists():
                shutil.copytree(source, install_root)
        elif stream_output:
            print(f"Using existing RaCo folder at {install_root}", flush=True)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        return _setup_result(
            status="failed",
            action_id=action_id,
            summary=f"RaCo setup failed while copying or extracting files: {exc}",
            path=install_root,
        )
    gui = _find_executable_under(install_root, "RamsesComposer.exe")
    headless = _find_executable_under(install_root, "RaCoHeadless.exe")
    if gui is None or headless is None:
        return _setup_result(
            status="incomplete",
            action_id=action_id,
            summary="Copied RaCo files, but RamsesComposer.exe or RaCoHeadless.exe was not found.",
            path=install_root,
        )
    record_dependency_path(workspace=workspace, key="raco_gui", path=gui)
    record_dependency_path(workspace=workspace, key="raco_headless", path=headless)
    return _setup_result(
        status="recorded",
        action_id=action_id,
        summary="Recorded RamsesComposer.exe and RaCoHeadless.exe for future pre-flight checks.",
        path=install_root,
        raco_gui=str(gui),
        raco_headless=str(headless),
    )


def _run_blender_setup(
    *,
    action_id: str,
    workspace: Path,
    action: dict[str, Any],
    target_path: Path | str | None,
    source_path: Path | str | None,
    stream_output: bool,
) -> dict[str, Any]:
    del action, target_path
    raw_source = str(source_path or "").strip()
    if raw_source:
        source = Path(raw_source).expanduser().resolve()
    else:
        try:
            source = _download_blender_installer(workspace, stream_output=stream_output)
        except Exception as exc:  # noqa: BLE001
            return _setup_result(
                status="failed",
                action_id=action_id,
                summary=f"Blender installer download failed: {exc}",
                path=operator_state_root(workspace) / "dependency_setup" / "downloads" / BLENDER_INSTALLER_FILENAME,
                download_url=BLENDER_INSTALLER_URL,
            )
    if not source.is_file():
        return _setup_result(
            status="missing",
            action_id=action_id,
            summary="Selected Blender installer or blender.exe path does not exist.",
            path=source,
        )
    if source.name.casefold() == "blender.exe":
        if _blender_disallowed(source):
            return _setup_result(
                status="incomplete",
                action_id=action_id,
                summary="Selected blender.exe is from a disallowed Blender 4.2 or greater install.",
                path=source,
            )
        record_dependency_path(workspace=workspace, key="blender", path=source)
        return _setup_result(
            status="recorded",
            action_id=action_id,
            summary="Recorded existing blender.exe for future pre-flight checks.",
            path=source,
        )
    if sys.platform != "win32":
        return _setup_result(
            status="incomplete",
            action_id=action_id,
            summary="Blender installer execution is available only on Windows; select an installed blender.exe here.",
            path=source,
        )
    suffix = source.suffix.casefold()
    if suffix == ".msi":
        command = ["msiexec", "/i", str(source)]
    elif suffix == ".exe":
        command = [str(source)]
    else:
        return _setup_result(
            status="incomplete",
            action_id=action_id,
            summary="Selected Blender installer must be an .msi or .exe file.",
            path=source,
        )
    if stream_output:
        print(f"Running visible Blender installer: {' '.join(command)}", flush=True)
        completed = subprocess.run(
            command,
            cwd=workspace,
            stdin=subprocess.DEVNULL,
            text=True,
            timeout=DEPENDENCY_SETUP_TIMEOUT_SECONDS,
            **hidden_subprocess_kwargs(),
        )
        output = ""
    else:
        completed = subprocess.run(
            command,
            cwd=workspace,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=DEPENDENCY_SETUP_TIMEOUT_SECONDS,
            **hidden_subprocess_kwargs(),
        )
        output = (completed.stderr or completed.stdout or "").strip()
    if completed.returncode not in {0, 3010}:
        return _setup_result(
            status="failed",
            action_id=action_id,
            summary=output or f"Blender installer failed with exit code {completed.returncode}.",
            path=source,
            exit_code=completed.returncode,
        )
    state = load_dependency_onboarding_state(workspace)
    blender = _existing_file(_blender_path_candidates(state, workspace))
    if blender is None:
        return _setup_result(
            status="incomplete",
            action_id=action_id,
            summary="Blender installer completed, but blender.exe was not found yet.",
            path=source,
            exit_code=completed.returncode,
        )
    record_dependency_path(workspace=workspace, key="blender", path=blender)
    return _setup_result(
        status="recorded",
        action_id=action_id,
        summary="Recorded blender.exe for future pre-flight checks.",
        path=blender,
        exit_code=completed.returncode,
        download_url=BLENDER_INSTALLER_URL if not raw_source else "",
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


_SETUP_ACTION_HANDLERS = {
    "setup-raco-from-shared-tools": _run_raco_setup,
    "setup-blender-411": _run_blender_setup,
    "clone-digital-3d-car-repo": _run_bmw_clone_setup,
    "setup-digital-3d-car-repo": _run_bmw_env_setup,
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


def _elapsed_label(elapsed_seconds: float) -> str:
    elapsed = max(0, int(elapsed_seconds))
    minutes, seconds = divmod(elapsed, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _tail_text(path: Path, limit: int = DEPENDENCY_SETUP_STDOUT_TAIL_BYTES) -> str:
    if not path.is_file():
        return ""
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    return data[-limit:].decode("utf-8", errors="replace")


def _tail_lines(path: Path, limit: int = DEPENDENCY_SETUP_STDOUT_TAIL_LINES) -> list[str]:
    text = _tail_text(path)
    if not text:
        return []
    return text.splitlines()[-limit:]


def _combined_tail_lines(stdout_path: Path, stderr_path: Path) -> list[str]:
    lines = list(_tail_lines(stdout_path))
    lines.extend(f"stderr: {line}" for line in _tail_lines(stderr_path))
    return lines[-DEPENDENCY_SETUP_STDOUT_TAIL_LINES:]


def _size_label(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    kib = size_bytes / 1024
    if kib < 1024:
        return f"{kib:.0f} KB"
    mib = kib / 1024
    return f"{mib:.1f} MB"


def _file_activity_from_roots(
    roots: list[Path | None],
    started_wall_time: float,
    limit: int = DEPENDENCY_SETUP_FILE_ACTIVITY_LIMIT,
) -> list[dict[str, Any]]:
    entries: list[tuple[float, dict[str, Any]]] = []
    threshold = started_wall_time - 1.0
    seen: set[str] = set()
    for root in roots:
        if root is None:
            continue
        try:
            base = root.expanduser().resolve()
        except OSError:
            continue
        candidates = [base]
        if base.is_dir():
            try:
                candidates.extend(path for path in base.iterdir())
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
                relative = str(path.relative_to(base))
            except ValueError:
                relative = path.name
            if relative == ".":
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


def _dependency_setup_worker_command(
    *,
    action_id: str,
    workspace: Path,
    target_path: Path | str | None,
    source_path: Path | str | None,
) -> list[str]:
    if getattr(sys, "frozen", False):
        command = [sys.executable, "dependency-setup-worker", action_id, "--workspace", str(workspace)]
    else:
        command = [sys.executable, "-B", "-m", "sg_preflight", "dependency-setup-worker", action_id, "--workspace", str(workspace)]
    if target_path:
        command.extend(["--target-path", str(target_path)])
    if source_path:
        command.extend(["--source-path", str(source_path)])
    return command


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


def _last_json_payload(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    for line in reversed(lines):
        raw = line.strip()
        if not raw.startswith("{") or not raw.endswith("}"):
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        return payload if isinstance(payload, dict) else {}
    return {}


def _dependency_setup_progress_payload(job: DependencySetupJob, *, elapsed_seconds: float) -> dict[str, Any]:
    return {
        "action_id": job.action_id,
        "workspace": str(job.workspace),
        "status": "incomplete",
        "phase": "running",
        "completed": False,
        "exit_code": None,
        "command": list(job.command),
        "timeout_seconds": job.timeout_seconds,
        "elapsed_seconds": int(max(0, elapsed_seconds)),
        "elapsed_label": _elapsed_label(elapsed_seconds),
        "typical_range": job.typical_range,
        "timed_out": False,
        "canceled": False,
        "summary": "Dependency setup running.",
        "stdout_tail": _tail_text(job.stdout_path),
        "stdout_tail_lines": _combined_tail_lines(job.stdout_path, job.stderr_path),
        "stderr_tail": _tail_text(job.stderr_path),
        "stdout_path": str(job.stdout_path),
        "stderr_path": str(job.stderr_path),
        "file_activity": _file_activity_from_roots(
            [job.stdout_path.parent, job.target_path],
            job.started_wall_time,
        ),
        "recorded_by_tool": True,
        "is_approval": False,
    }


def _dependency_setup_result(
    job: DependencySetupJob,
    *,
    exit_code: int,
    status: str,
    summary: str,
    timed_out: bool = False,
    canceled: bool = False,
) -> dict[str, Any]:
    elapsed_seconds = time.monotonic() - job.started_monotonic
    payload = _last_json_payload(job.stdout_path)
    if not payload:
        payload = {
            "status": status,
            "action_id": job.action_id,
            "summary": summary,
            "recorded_by_tool": True,
            "is_approval": False,
        }
    payload.update(
        {
            "action_id": job.action_id,
            "workspace": str(job.workspace),
            "completed": True,
            "exit_code": exit_code,
            "command": list(job.command),
            "timeout_seconds": job.timeout_seconds,
            "elapsed_seconds": int(max(0, elapsed_seconds)),
            "elapsed_label": _elapsed_label(elapsed_seconds),
            "typical_range": job.typical_range,
            "timed_out": timed_out,
            "canceled": canceled,
            "stdout_tail": _tail_text(job.stdout_path),
            "stdout_tail_lines": _combined_tail_lines(job.stdout_path, job.stderr_path),
            "stderr_tail": _tail_text(job.stderr_path),
            "stdout_path": str(job.stdout_path),
            "stderr_path": str(job.stderr_path),
            "file_activity": _file_activity_from_roots(
                [job.stdout_path.parent, job.target_path],
                job.started_wall_time,
            ),
            "recorded_by_tool": True,
            "is_approval": False,
        }
    )
    payload.setdefault("status", status)
    payload.setdefault("summary", summary)
    return payload


def poll_dependency_setup_action(job: DependencySetupJob) -> dict[str, Any] | None:
    if job.completed:
        return _dependency_setup_result(
            job,
            exit_code=job.process.returncode or 0,
            status="unknown",
            summary="Dependency setup job already completed.",
        )
    exit_code = job.process.poll()
    elapsed = time.monotonic() - job.started_monotonic
    if exit_code is None and elapsed < job.timeout_seconds:
        return _dependency_setup_progress_payload(job, elapsed_seconds=elapsed)
    if exit_code is None:
        job.process.terminate()
        try:
            job.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            job.process.kill()
            job.process.wait(timeout=5)
        job.completed = True
        return _dependency_setup_result(
            job,
            exit_code=job.process.returncode if job.process.returncode is not None else -1,
            status="failed",
            summary=f"Dependency setup timed out after {job.timeout_seconds} seconds.",
            timed_out=True,
        )
    job.completed = True
    return _dependency_setup_result(
        job,
        exit_code=exit_code,
        status="recorded" if exit_code == 0 else "failed",
        summary=(
            "Dependency setup completed."
            if exit_code == 0
            else f"Dependency setup failed with exit code {exit_code}."
        ),
    )


def cancel_dependency_setup_action(job: DependencySetupJob) -> dict[str, Any]:
    if job.process.poll() is None:
        job.process.terminate()
        try:
            job.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            job.process.kill()
            job.process.wait(timeout=5)
    job.completed = True
    return _dependency_setup_result(
        job,
        exit_code=job.process.returncode if job.process.returncode is not None else -1,
        status="failed",
        summary="Dependency setup canceled by operator.",
        canceled=True,
    )
