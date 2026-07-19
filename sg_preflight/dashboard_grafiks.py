"""Locates and launches the Grafiks native shell (cinematic or operator console) from the dashboard."""

from __future__ import annotations

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
GRAFIKS_BUNDLED_SHELL_DIR = Path("grafiks_shell")
GRAFIKS_SPAWN_FAILURE_EXIT_CODE = 126
CINEMATIC_RUNTIME_COMPANIONS = (
    "ramses-shared-lib-headless.dll",
    "ramses-shared-lib-renderer.dll",
    "ramses-shared-lib.dll",
    "SDL3.dll",
)
GRAFIKS_CXX_BUILD_DIR = Path("cpp") / "build" / "vs2022-ramses-28.16" / "Release"
GRAFIKS_DEFAULT_BMW_CARS_ROOT = Path(r"C:\3D Car git\digital-3d-car-models\cars\BMW")
GRAFIKS_MODE_WIP_HINT = (
    "Grafiks mode is WIP - use Clean for now unless the operator console or cinematic fallback is installed."
)


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
    preference_candidates: list[Path] = []
    configured_preference = _dashboard_grafiks_shell_exe_preference(workspace)
    if configured_preference:
        preferred = Path(configured_preference)
        if preferred.is_dir():
            preference_candidates.extend(
                [preferred / OPERATOR_CONSOLE_SHELL_EXE_NAME, preferred / GRAFIKS_SHELL_EXE_NAME]
            )
        else:
            preference_candidates.append(preferred)

    environment_files: list[Path] = []
    environment_directories: list[Path] = []
    for key in GRAFIKS_SHELL_EXE_ENV_KEYS:
        raw = os.environ.get(key, "").strip()
        if not raw:
            continue
        configured = Path(raw)
        if configured.is_dir():
            environment_directories.append(configured)
        else:
            environment_files.append(configured)

    environment_directories = _unique_existing_order(environment_directories)
    environment_candidates = [
        *environment_files,
        *(directory / OPERATOR_CONSOLE_SHELL_EXE_NAME for directory in environment_directories),
        *(directory / GRAFIKS_SHELL_EXE_NAME for directory in environment_directories),
    ]

    source_root = _dashboard_source_root()
    roots = [source_root, Path.cwd()]
    if workspace is not None:
        roots.append(Path(workspace))
    if source_root.parent != source_root:
        roots.append(source_root.parent / "sg-preflight")

    discovered_directories: list[Path] = []
    for root in _unique_existing_order(roots):
        discovered_directories.extend(
            [
                root / GRAFIKS_BUNDLED_SHELL_DIR,
                root / GRAFIKS_CXX_BUILD_DIR,
                root / "build" / "vs2022-ramses-28.16" / "Release",
                root,
            ]
        )
    discovered_directories = _unique_existing_order(discovered_directories)
    discovery_candidates = [
        *(directory / OPERATOR_CONSOLE_SHELL_EXE_NAME for directory in discovered_directories),
        *(directory / GRAFIKS_SHELL_EXE_NAME for directory in discovered_directories),
    ]
    return _unique_existing_order(preference_candidates + environment_candidates + discovery_candidates)


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
    if _is_operator_console_shell(exe_path):
        return [str(exe_path)]
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


def _grafiks_shell_kind(exe_path: Path) -> str:
    if _is_operator_console_shell(exe_path):
        return "operator"
    return "cinematic"


def _grafiks_runtime_issue(exe_path: Path) -> str:
    try:
        if not exe_path.parent.is_dir():
            return "working_directory"
        if not exe_path.is_file():
            return "executable"
        if _grafiks_shell_kind(exe_path) == "cinematic":
            missing_count = sum(
                not (exe_path.parent / companion).is_file() for companion in CINEMATIC_RUNTIME_COMPANIONS
            )
            if missing_count:
                return f"companions_{missing_count}"
    except OSError:
        return "filesystem"
    return ""


def _grafiks_not_installed_message(workspace: Path | str | None = None) -> str:
    return (
        f"{GRAFIKS_MODE_WIP_HINT}\n"
        f"C++ shell not installed: {OPERATOR_CONSOLE_SHELL_EXE_NAME} and {GRAFIKS_SHELL_EXE_NAME} were not found.\n"
        f"Build either shell or set {GRAFIKS_SHELL_EXE_ENV_KEYS[0]} to its executable to enable Grafiks mode."
    )


def run_grafiks_mode(
    *,
    profile_id: str = "",
    workspace: Path | str,
    bmw_root: Path | str | None = None,
    shell_path: Path | str | None = None,
    resolve_shell_exe: Callable[[Path | str | None], Path | None] | None = None,
    not_installed_message: Callable[[Path | str | None], str] | None = None,
) -> int:
    root = Path(workspace).resolve()
    resolve = resolve_shell_exe or _resolve_grafiks_shell_exe
    message_for = not_installed_message or _grafiks_not_installed_message
    exe_path = Path(shell_path) if shell_path is not None else resolve(root)
    if exe_path is None:
        message = message_for(root)
        append_startup_log("Grafiks fallback=clean category=missing_executable")
        print(message)
        return GRAFIKS_SPAWN_FAILURE_EXIT_CODE

    try:
        exe_path = Path(exe_path).resolve()
    except OSError:
        append_startup_log("Grafiks fallback=clean category=missing_runtime shell=unknown reason=filesystem")
        print("Grafiks runtime is unavailable. Clean mode remains active.", file=sys.stderr)
        return GRAFIKS_SPAWN_FAILURE_EXIT_CODE

    shell_kind = _grafiks_shell_kind(exe_path)
    runtime_issue = _grafiks_runtime_issue(exe_path)
    if runtime_issue:
        append_startup_log(
            f"Grafiks fallback=clean category=missing_runtime shell={shell_kind} reason={runtime_issue}"
        )
        print("Grafiks runtime is unavailable. Clean mode remains active.", file=sys.stderr)
        return GRAFIKS_SPAWN_FAILURE_EXIT_CODE

    command = _grafiks_shell_command(exe_path, profile_id=profile_id, bmw_root=bmw_root)
    append_startup_log(f"Grafiks launch category=starting shell={shell_kind}")
    print(GRAFIKS_MODE_WIP_HINT)
    print(f"Launching Grafiks {shell_kind} shell.")
    try:
        process = subprocess.Popen(command, cwd=exe_path.parent)
    except OSError as exc:
        append_startup_log(f"Grafiks fallback=clean category=spawn_failed error={type(exc).__name__}")
        print("Grafiks could not start. Clean mode remains active.", file=sys.stderr)
        return GRAFIKS_SPAWN_FAILURE_EXIT_CODE
    try:
        exit_code = process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        return 0
    except OSError as exc:
        append_startup_log(f"Grafiks fallback=clean category=spawn_failed error={type(exc).__name__}")
        print("Grafiks could not start. Clean mode remains active.", file=sys.stderr)
        return GRAFIKS_SPAWN_FAILURE_EXIT_CODE
    # An exit inside the wait window is an early exit even with code 0 - the shell never stayed up.
    append_startup_log(f"Grafiks fallback=clean category=early_exit exit_code={int(exit_code)}")
    print(f"Grafiks exited early with code {exit_code}. Clean mode remains active.", file=sys.stderr)
    return int(exit_code) or GRAFIKS_SPAWN_FAILURE_EXIT_CODE
