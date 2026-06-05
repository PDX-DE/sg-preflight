from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from typing import Any

from sg_preflight.subprocess_utils import hidden_subprocess_kwargs, sgfx_cli_command


DASHBOARD_TITLE = "Seriengrafik: Project Quality-Hero"
STARTUP_LOG_NAME = "sgfx-preflight-startup.log"
WEBVIEW2_RUNTIME_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
NATIVE_RETURN_FALLBACK_SECONDS = 5.0
BROWSER_FALLBACK_ENV = "SGFX_PREFLIGHT_BROWSER_FALLBACK"
FORCE_FROZEN_NATIVE_ENV = "SGFX_PREFLIGHT_FORCE_FROZEN_NATIVE"


def startup_log_path() -> Path:
    return Path(tempfile.gettempdir()) / STARTUP_LOG_NAME


def append_startup_log(message: str) -> None:
    try:
        with startup_log_path().open("a", encoding="utf-8") as handle:
            handle.write(f"{datetime.now().isoformat(timespec='seconds')}: {message}\n")
    except OSError:
        return


def webview2_runtime_available() -> bool:
    if sys.platform != "win32":
        return True
    try:
        import winreg
    except ImportError:
        return False
    subkeys = (
        rf"SOFTWARE\Microsoft\EdgeUpdate\ClientState\{WEBVIEW2_RUNTIME_GUID}",
        rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\ClientState\{WEBVIEW2_RUNTIME_GUID}",
        rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_RUNTIME_GUID}",
        rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_RUNTIME_GUID}",
    )
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for subkey in subkeys:
            try:
                with winreg.OpenKey(hive, subkey):
                    return True
            except OSError:
                continue
    return False


def _find_open_dashboard_port(start_port: int = 8000, end_port: int = 8999) -> int:
    for port in range(start_port, end_port + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise OSError("No open SGFX dashboard port found between 8000 and 8999")


def _run_nicegui(
    ui: Any,
    *,
    host: str,
    port: int,
    native: bool,
    reload: bool,
    show: bool,
    favicon_path: Path,
) -> None:
    kwargs: dict[str, Any] = {
        "host": host,
        "port": port,
        "native": native,
        "reload": reload,
        "title": DASHBOARD_TITLE,
        "show": show,
        # NiceGUI reconnect timeout: 30s for graceful stall tolerance, so sub-30s
        # slow page handlers / jitter don't trigger reconnect storms. The 30s server-side
        # Full QA dedup window is the safety net for cached ?full_qa_run=1 re-fires,
        # not the primary defense.
        "reconnect_timeout": 30.0,
    }
    if favicon_path.is_file():
        kwargs["favicon"] = str(favicon_path)
    ui.run(**kwargs)


def _browser_fallback_show_requested() -> bool:
    return os.environ.get(BROWSER_FALLBACK_ENV) == "1"


def _frozen_native_window_allowed() -> bool:
    return not getattr(sys, "frozen", False) or os.environ.get(FORCE_FROZEN_NATIVE_ENV) == "1"


def _packaged_native_unavailable() -> RuntimeError:
    return RuntimeError(
        "Packaged native mode is hosted by the embedded desktop shell. "
        "Use the executable default mode, or pass --no-native only for local server diagnostics."
    )


def _clean_fallback_theme(ui_mode: str | None) -> str:
    value = str(ui_mode or "clean").strip().casefold()
    return value if value in ("clean",) else "clean"


def _launch_browser_fallback_process(
    *,
    profile_id: str,
    workspace: Path,
    bmw_root: Path | str | None,
    ui_mode: str | None,
    host: str,
    fallback_port: int,
) -> int:
    command = sgfx_cli_command("dashboard", "run")
    if profile_id:
        command.extend(["--profile", profile_id])
    command.extend(
        [
            "--workspace",
            str(workspace),
            "--ui-mode",
            _clean_fallback_theme(ui_mode),
            "--host",
            host,
            "--port",
            str(fallback_port),
            "--no-native",
        ]
    )
    if bmw_root is not None:
        command.extend(["--bmw-root", str(bmw_root)])
    env = os.environ.copy()
    env[BROWSER_FALLBACK_ENV] = "1"
    append_startup_log(f"launching browser fallback process on {host}:{fallback_port}")
    child = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        **hidden_subprocess_kwargs(),
    )
    try:
        exit_code = child.wait(timeout=3)
    except subprocess.TimeoutExpired:
        return 0
    raise RuntimeError(f"Browser fallback process exited early with code {exit_code}")
