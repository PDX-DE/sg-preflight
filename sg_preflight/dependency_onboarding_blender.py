"""Blender 4.1 + SG Toolkit discovery and the download/install-then-register
Blender setup action.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
import urllib.request

from sg_preflight.dependency_onboarding_jobs import (
    DEPENDENCY_SETUP_TIMEOUT_SECONDS,
    _auto_register_dependency_path,
    _env_path,
    _existing_file,
    _find_executable,
    _glob_dirs,
    _registered_path,
    _setup_action,
    _setup_result,
    _status_item,
    _with_onboarding_globals,
    load_dependency_onboarding_state,
    operator_state_root,
    record_dependency_path,
)
from sg_preflight.subprocess_utils import hidden_subprocess_kwargs
from sg_preflight.utils import ensure_parent


BLENDER_BASELINE_VERSION = "4.1.1"


BLENDER_INSTALLER_URL = "https://download.blender.org/release/Blender4.1/blender-4.1.1-windows-x64.msi"


BLENDER_INSTALLER_FILENAME = "blender-4.1.1-windows-x64.msi"


BLENDER_CONFLUENCE_ANCHOR = (
    "139_3D-Car/252_3D-car---3D-Crew/253_How-to-3D/"
    "266_How-to-Setup-Blender-4-and-SGToolkit-1.0:1-18"
)


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


def _windows_admin_status() -> str:
    if sys.platform != "win32":
        return "unknown"
    try:
        import ctypes

        return "available" if bool(ctypes.windll.shell32.IsUserAnAdmin()) else "missing"
    except Exception:  # noqa: BLE001
        return "unknown"


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


# Re-resolve collaborators through the live `dependency_onboarding` facade on
# every call, so `mock.patch.object(dependency_onboarding, "_name", ...)`
# keeps intercepting now that callers and callees can live in different files.
_blender_path_candidates = _with_onboarding_globals(_blender_path_candidates)
_blender_disallowed = _with_onboarding_globals(_blender_disallowed)
_windows_admin_status = _with_onboarding_globals(_windows_admin_status)
_blender_status = _with_onboarding_globals(_blender_status)
_download_blender_installer = _with_onboarding_globals(_download_blender_installer)
_run_blender_setup = _with_onboarding_globals(_run_blender_setup)
