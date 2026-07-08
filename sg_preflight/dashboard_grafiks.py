from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Callable

from sg_preflight.dashboard_preferences import _dashboard_grafiks_shell_exe_preference
from sg_preflight.dashboard_webserver import append_startup_log


GRAFIKS_SHELL_EXE_ENV_KEYS = ("SGFX_GRAFIKS_SHELL_EXE", "SGFX_CINEMATIC_SHELL_EXE")
GRAFIKS_SHELL_EXE_NAME = "sgfx_cine_cinematic_shell.exe"
OPERATOR_CONSOLE_SHELL_EXE_NAME = "sgfx_screens.exe"
# Subdirectory the packaged exe carries the operator-console dist under (_internal/grafiks_shell/).
GRAFIKS_BUNDLED_SHELL_DIR = Path("grafiks_shell")
GRAFIKS_STATUS_HANDOFF_NAME = "sgfx_status.json"
GRAFIKS_CXX_BUILD_DIR = Path("cpp") / "build" / "vs2022-ramses-28.16" / "Release"
GRAFIKS_DEFAULT_BMW_CARS_ROOT = Path(r"C:\3D Car git\digital-3d-car-models\cars\BMW")
GRAFIKS_MODE_WIP_HINT = "Grafiks mode is WIP - use Clean for now unless the C++ Grafiks shell is installed."


def _grafiks_shell_label(exe_path: Path | None = None) -> str:
    if exe_path is not None and not _is_operator_console_shell(exe_path):
        return "Grafiks cinematic shell"
    return "Grafiks operator console"
GRAFIKS_MODE_WARNING_TITLE = "WARNING - Grafiks mode is still a work in progress."
GRAFIKS_MODE_WARNING_BODY = "Expect instability and bugs. Thanks for your patience!"


def _dashboard_source_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _unique_existing_order(paths: list[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        key = str(resolved).casefold()
        if key not in seen:
            seen.add(key)
            unique.append(resolved)
    return unique


def _grafiks_shell_exe_candidates(workspace: Path | str | None = None) -> list[Path]:
    candidates: list[Path] = []
    configured_preference = _dashboard_grafiks_shell_exe_preference(workspace)
    if configured_preference:
        preferred = Path(configured_preference)
        if preferred.is_dir():
            candidates.extend(
                [preferred / OPERATOR_CONSOLE_SHELL_EXE_NAME, preferred / GRAFIKS_SHELL_EXE_NAME]
            )
        else:
            candidates.append(preferred)

    for key in GRAFIKS_SHELL_EXE_ENV_KEYS:
        raw = os.environ.get(key, "").strip()
        if not raw:
            continue
        configured = Path(raw)
        if configured.is_dir():
            candidates.extend(
                [configured / OPERATOR_CONSOLE_SHELL_EXE_NAME, configured / GRAFIKS_SHELL_EXE_NAME]
            )
        else:
            candidates.append(configured)

    source_root = _dashboard_source_root()
    roots = [source_root, Path.cwd()]
    if workspace is not None:
        roots.append(Path(workspace))
    if source_root.parent != source_root:
        roots.append(source_root.parent / "sg-preflight")

    for root in _unique_existing_order(roots):
        candidates.extend(
            [
                # Grafiks mode is the operator console; prefer it everywhere. The packaged
                # exe carries it under _internal/grafiks_shell/ (see build_sgfx_exe.py).
                root / GRAFIKS_BUNDLED_SHELL_DIR / OPERATOR_CONSOLE_SHELL_EXE_NAME,
                root / OPERATOR_CONSOLE_SHELL_EXE_NAME,
                # The Ramses cinematic shell is a separate R&D track, only a last resort.
                root / GRAFIKS_BUNDLED_SHELL_DIR / GRAFIKS_SHELL_EXE_NAME,
                root / GRAFIKS_CXX_BUILD_DIR / GRAFIKS_SHELL_EXE_NAME,
                root / "build" / "vs2022-ramses-28.16" / "Release" / GRAFIKS_SHELL_EXE_NAME,
                root / GRAFIKS_SHELL_EXE_NAME,
            ]
        )
    return _unique_existing_order(candidates)


def _resolve_grafiks_shell_exe(workspace: Path | str | None = None) -> Path | None:
    for candidate in _grafiks_shell_exe_candidates(workspace):
        if candidate.is_file():
            return candidate
    return None


def _grafiks_bmw_cars_root(bmw_root: Path | str | None = None) -> Path:
    candidates: list[Path] = []
    if bmw_root is not None:
        root = Path(bmw_root)
        candidates.extend([root / "cars" / "BMW", root])
    raw = os.environ.get("SGFX_BMW_CARS_ROOT", "").strip()
    if raw:
        candidates.append(Path(raw))
    candidates.append(GRAFIKS_DEFAULT_BMW_CARS_ROOT)
    for candidate in _unique_existing_order(candidates):
        if candidate.is_dir():
            return candidate
    return GRAFIKS_DEFAULT_BMW_CARS_ROOT


def _grafiks_profile_registry_file() -> Path:
    return _dashboard_source_root() / "sg_preflight" / "profiles.py"


def _grafiks_shell_command(
    exe_path: Path,
    *,
    profile_id: str = "",
    bmw_root: Path | str | None = None,
) -> list[str]:
    command = [
        str(exe_path),
        "--interactive",
        "--hub-planet",
        "--hub-nodes",
        "--fusion-cars-root",
        str(_grafiks_bmw_cars_root(bmw_root)),
        "--asset-root",
        "assets",
        "--font-root",
        str(Path("assets") / "fonts"),
    ]
    registry_file = _grafiks_profile_registry_file()
    if registry_file.is_file():
        command.extend(["--profile-registry-file", str(registry_file)])
    normalized_profile = str(profile_id or "").strip()
    if normalized_profile:
        command.extend(["--fusion-profile-id", normalized_profile])
    return command


def _is_operator_console_shell(exe_path: Path) -> bool:
    return exe_path.name.casefold() == OPERATOR_CONSOLE_SHELL_EXE_NAME.casefold()


def _write_grafiks_status_handoff(exe_path: Path, profile_id: str) -> bool:
    normalized = str(profile_id or "").strip()
    if normalized.upper().endswith("_EVO"):
        normalized = normalized[: -len("_EVO")]
    if not normalized:
        return False
    status_path = exe_path.parent / GRAFIKS_STATUS_HANDOFF_NAME
    payload: dict = {}
    try:
        if status_path.is_file():
            existing = json.loads(status_path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                payload = existing
    except (OSError, ValueError):
        payload = {}
    run_section = payload.get("run")
    if not isinstance(run_section, dict):
        run_section = {}
    run_section["activeProfile"] = normalized
    payload["run"] = run_section
    try:
        status_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        append_startup_log(
            f"Grafiks car-preselect handoff skipped ({exc}); launching without preselect"
        )
        return False
    return True


def _grafiks_not_installed_message(workspace: Path | str | None = None) -> str:
    expected = _grafiks_shell_exe_candidates(workspace)
    first_expected = str(expected[0]) if expected else OPERATOR_CONSOLE_SHELL_EXE_NAME
    return (
        f"{GRAFIKS_MODE_WIP_HINT}\n"
        f"C++ shell not installed: Grafiks operator console not found. Expected first: {first_expected}\n"
        f"Set the Grafiks shell path on the Settings page (or {GRAFIKS_SHELL_EXE_ENV_KEYS[0]}) to the "
        f"built operator console ({OPERATOR_CONSOLE_SHELL_EXE_NAME}) to enable Grafiks mode."
    )


def run_grafiks_mode(
    *,
    profile_id: str = "",
    workspace: Path | str,
    bmw_root: Path | str | None = None,
    resolve_shell_exe: Callable[[Path | str | None], Path | None] | None = None,
    not_installed_message: Callable[[Path | str | None], str] | None = None,
) -> int:
    root = Path(workspace).resolve()
    resolve = resolve_shell_exe or _resolve_grafiks_shell_exe
    message_for = not_installed_message or _grafiks_not_installed_message
    exe_path = resolve(root)
    if exe_path is None:
        message = message_for(root)
        append_startup_log(f"Grafiks mode unavailable: {message.replace(chr(10), ' | ')}")
        print(message)
        return 0

    if _is_operator_console_shell(exe_path):
        _write_grafiks_status_handoff(exe_path, profile_id)
        command = [str(exe_path)]
    else:
        command = _grafiks_shell_command(exe_path, profile_id=profile_id, bmw_root=bmw_root)
    shell_label = _grafiks_shell_label(exe_path)
    append_startup_log(f"launching {shell_label}: {exe_path}")
    print(GRAFIKS_MODE_WIP_HINT)
    print(f"Launching {shell_label}: {exe_path}")
    process = subprocess.Popen(command, cwd=exe_path.parent)
    try:
        exit_code = process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        return 0
    if exit_code == 0:
        return 0
    print(f"Grafiks C++ shell exited early with code {exit_code}.", file=sys.stderr)
    return int(exit_code)
