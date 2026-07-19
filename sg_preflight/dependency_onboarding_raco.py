"""RaCo GUI and RaCoHeadless discovery (Confluence-documented OneDrive Tools
fallback) and the copy/extract-then-register RaCo setup action.
"""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any
import zipfile

from sg_preflight.dependency_onboarding_jobs import (
    _auto_register_dependency_path,
    _env_path,
    _existing_dir,
    _existing_file,
    _find_executable,
    _glob_dirs,
    _registered_path,
    _setup_action,
    _setup_result,
    _status_item,
    _with_onboarding_globals,
    record_dependency_path,
)


RACO_BASELINE_VERSION = "2.3.1"


RACO_CONFLUENCE_ANCHOR = "003_Onboarding/005_How-to-set-up-your-Laptop:190-204"


RACO_HEADLESS_CONFLUENCE_ANCHOR = (
    "139_3D-Car/225_3D-Car---RaCo-Implementation/"
    "249_How-to-use-the-various-python-scripts-fo:170-190"
)


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


# Re-resolve collaborators through the live `dependency_onboarding` facade on
# every call, so `mock.patch.object(dependency_onboarding, "_name", ...)`
# keeps intercepting now that callers and callees can live in different files.
_raco_install_roots = _with_onboarding_globals(_raco_install_roots)
_raco_executable_candidates = _with_onboarding_globals(_raco_executable_candidates)
_onedrive_raco_sources = _with_onboarding_globals(_onedrive_raco_sources)
_raco_source_detail = _with_onboarding_globals(_raco_source_detail)
_raco_status = _with_onboarding_globals(_raco_status)
_find_executable_under = _with_onboarding_globals(_find_executable_under)
_safe_extract_zip = _with_onboarding_globals(_safe_extract_zip)
_resolve_raco_install_root = _with_onboarding_globals(_resolve_raco_install_root)
_run_raco_setup = _with_onboarding_globals(_run_raco_setup)
