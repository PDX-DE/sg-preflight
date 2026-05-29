from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
from html import escape as html_escape
import json
import os
import platform
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
from time import monotonic
from typing import Any, Callable
from urllib.parse import quote_plus
from urllib.parse import quote

from sg_preflight.activity_log import append_activity_entry
from sg_preflight.assets import runtime_asset_dir, runtime_asset_path, runtime_asset_root
from sg_preflight.bmw_delivery import read_bmw_screenshot_state
from sg_preflight.bmw_pipeline_auto_fix import (
    MISSING_ACTUAL_DIAGNOSTIC_ACTION_ID,
    render_missing_actual_diagnostic_text,
    run_missing_actual_diagnostic_chain,
)
from sg_preflight.cross_car_comparison import build_cross_car_comparison
from sg_preflight.daily_digest import build_latest_daily_digest
from sg_preflight.delivery_checklist import read_delivery_checklist
from sg_preflight.delivery_workbook_generation import (
    GENERATE_WORKBOOK_ACTION_ID,
    GENERATE_WORKBOOK_ACTION_LABEL,
    GENERATE_WORKBOOK_TIMEOUT_SECONDS,
    build_delivery_workbook_trigger,
    cancel_delivery_workbook_generation,
    poll_delivery_workbook_generation,
    start_delivery_workbook_generation,
)
from sg_preflight.desktop_notifications import notify_desktop_completion
from sg_preflight.dependency_onboarding import (
    build_dependency_onboarding_status,
    cancel_dependency_setup_action,
    poll_dependency_setup_action,
    start_dependency_setup_action,
)
from sg_preflight.full_qa_pass import build_full_qa_pass
from sg_preflight.full_qa_history import record_full_qa_run_history
from sg_preflight.jira_client import DEFAULT_JIRA_URL, load_jira_credentials, search_jira_profile_tickets
from sg_preflight.manual_review import (
    QUALITY_HERO_STEPS,
    apply_manual_review_suggestions,
    build_manual_review_assist,
    build_manual_review_assist_from_auto_checks,
    create_manual_review_session_from_template,
    list_car_review_templates,
    load_manual_review_session,
    record_manual_review_step,
    review_template_for_profile,
    run_manual_review_auto_checks,
)
from sg_preflight.operator_handoff import (
    build_operator_handoff_snapshot,
    record_operator_handoff,
)
from sg_preflight.onboarding_assistant import build_onboarding_guide
from sg_preflight.profiles import (
    PROFILE_REGISTRY_DYNAMIC_SOURCE,
    PROFILE_SCOPE_DEFAULT,
    get_run_profile,
    list_run_profiles,
)
from sg_preflight.profile_change_detection import detect_changed_profiles_since_last_run
from sg_preflight.risk_scoring import read_per_car_risk_score
from sg_preflight.screenshot_review_viewer import (
    build_screenshot_review_viewer,
    compute_diff_delta_badge,
    compute_diff_regression_badge,
)
from sg_preflight.screenshot_capture import (
    SCREENSHOT_CAPTURE_ACTION_ID,
    SCREENSHOT_CAPTURE_ACTION_LABEL,
    SCREENSHOT_CAPTURE_TIMEOUT_SECONDS,
    cancel_screenshot_capture,
    check_screenshot_capture_environment,
    poll_screenshot_capture,
    start_screenshot_capture,
)
from sg_preflight.services import operator_ui_root
from sg_preflight.subprocess_utils import hidden_subprocess_kwargs, sgfx_cli_command
from sg_preflight.team_digest_board import build_team_daily_digest_board
from sg_preflight.utils import ensure_parent
from sg_preflight.visual_review import build_visual_review_prep


DASHBOARD_TITLE = "Seriengrafik: Project Quality-Hero"
DASHBOARD_BRAND_LOGO_ASSET = "logo_sgfx.png"
DASHBOARD_BRAND_ICON_ASSET = "sgfx_icon.png"
DASHBOARD_DEBUG_ICON_ASSET = "debug_icon.png"
STARTUP_LOG_NAME = "sgfx-preflight-startup.log"
WEBVIEW2_RUNTIME_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
NATIVE_RETURN_FALLBACK_SECONDS = 5.0
BROWSER_FALLBACK_ENV = "SGFX_PREFLIGHT_BROWSER_FALLBACK"
FORCE_FROZEN_NATIVE_ENV = "SGFX_PREFLIGHT_FORCE_FROZEN_NATIVE"
VERBOSE_TOOLTIP_ENV = "SGFX_DASHBOARD_VERBOSE_TOOLTIPS"
FIRST_LAUNCH_DISMISS_STORAGE_KEY = "sgfx.firstLaunch.dismissed"
FEEDBACK_EMAIL_ENV = "SGFX_FEEDBACK_EMAIL"
DEFAULT_FEEDBACK_EMAIL = "daviderikgarciaarenas@gmail.com"
DESKTOP_NOTIFICATIONS_ENV = "SGFX_DESKTOP_NOTIFICATIONS"
LONG_RUNNING_NOTIFICATION_SECONDS = 30
DASHBOARD_GUARDRAILS = (
    "Manual review remains required.",
    "Decision: not approval — evidence only.",
    "BMW Git access is read-only. SGFX never modifies BMW source.",
    "Activity log is local-only — never posted to Jira, SVN, or BMW Git.",
)
DASHBOARD_NAVIGATION = (
    ("full-qa-pass", "Full QA Pass"),
    ("batch-full-qa-pass", "Batch Full QA Pass"),
    ("delivery-checklist", "Delivery Checklist"),
    ("onboarding-guide", "Onboarding Guide"),
    ("screenshot-test-state", "Screenshot Test State"),
    ("risk-score", "Risk Score"),
    ("cross-car-comparison", "Cross-Car Comparison"),
    ("daily-digest", "Daily Digest"),
    ("team-digest-board", "Team Digest Board"),
    ("operator-handoff", "Operator Handoff"),
    ("manual-review", "Manual Review Companion"),
    ("about", "About"),
)
DASHBOARD_SHORTCUTS = ("F1-F12 Help", "F2 Profile switch", "F5 Refresh page", "F12 Diagnostic", "Esc Quit")
DASHBOARD_SHORTCUT_ACTIONS = (
    ("F1", "Help: use the sidebar pages to inspect read-only SGFX evidence."),
    ("F2", "Profile switch: use the Profile selector in the header."),
    ("F3", "Reference: no action is assigned to F3 in this release."),
    ("F4", "Reference: no action is assigned to F4 in this release."),
    ("F5", "Refresh page: re-read the current profile evidence."),
    ("F6", "Reference: no action is assigned to F6 in this release."),
    ("F7", "Reference: no action is assigned to F7 in this release."),
    ("F8", "Reference: no action is assigned to F8 in this release."),
    ("F9", "Reference: no action is assigned to F9 in this release."),
    ("F10", "Reference: no action is assigned to F10 in this release."),
    ("F11", "Reference: no action is assigned to F11 in this release."),
    ("F12", "Diagnostic: profile, workspace, and current page are shown in the header."),
    ("Esc", "Quit: close the native window or browser tab when the local review is done."),
)
THEME_CHOICES = ["clean"]
QUALITY_HERO_CONFLUENCE_ANCHOR = (
    "PDX_" + "SER" + "GFX/139_3D-Car/298_Quality-Hero-How-to-review-the-3D-car/page.txt"
)
DELIVERY_CHECKLIST_CONFLUENCE_ANCHOR = (
    "311_Delivery-process/312_3D-Car---Delivery-and-Integration/"
    "315_How-to-3D-Cars-Delivery-Checklist----v0:50-54,67-69,81-82,100-102"
)
BMW_PIPELINE_PYTHON_CONFLUENCE_ANCHOR = (
    "139_3D-Car/225_3D-Car---RaCo-Implementation/"
    "249_How-to-use-the-various-python-scripts-fo:170-190"
)
SG_DAILY_CONFLUENCE_ANCHOR = (
    "PDX_"
    + "SER"
    + "GFX/016_Project-Management/024_How-to...-Seriesgraphics/029_Regular-Meetings/030_SG-Daily/page.txt"
)

ABOUT_CONTENT: dict[str, Any] = {
    "heading": "About",
    "description": (
        "Local-only QA preflight tool for the SGFX Seriengrafik delivery workflow. "
        "Reads operator-local evidence (delivery checklists, screenshot test state, BMW pipeline "
        "outputs, manual-review verdicts) and surfaces it for the morning Quality-Hero standup. "
        "Never modifies BMW source; never posts to Jira, SVN, or BMW Git."
    ),
    "version_placeholder": "version: alpha (local handover bundle)",
    "logo_assets": (
        ("logo_sgfx.png", "primary brand lockup, header and About surfaces"),
        ("framework_sgfx_logo.png", "alternate compact mark"),
        ("sgfx_icon.png", "square icon, sidebar header"),
    ),
    "confluence_anchors": (
        ("Quality-Hero manual review workflow", QUALITY_HERO_CONFLUENCE_ANCHOR),
        ("PDX Seriengrafik onboarding (laptop setup)", "003_Onboarding/005_How-to-set-up-your-Laptop"),
        ("BMW Git access", "003_Onboarding/013_How-to-access-BMW-GIT"),
        ("Git workflow", "003_Onboarding/015_How-to-Git"),
        ("Blender 4 + SGToolkit setup", "139_3D-Car/.../266_How-to-Setup-Blender-4-and-SGToolkit-1.0"),
        ("Delivery checklist (env var)", "311_Delivery-process/.../315_How-to-3D-Cars-Delivery-Checklist----v0"),
        ("BMW pipeline Python scripts", BMW_PIPELINE_PYTHON_CONFLUENCE_ANCHOR),
        ("SG Daily", SG_DAILY_CONFLUENCE_ANCHOR),
    ),
    "data_handling_disclosure": (
        "Data handling",
        "This tool reads operator-local files (delivery checklists, BMW pipeline outputs, screenshot test state, manual-review records) and renders them for the morning Quality-Hero standup. No telemetry, no external service calls.",
        "Suggested evidence comes from a deterministic local filesystem probe — does this file exist, does this directory contain these files, does this workbook have these rows. The operator records every verdict; the tool does not pre-decide.",
        "The Jira post flow is the one explicit network boundary, and it stays default-off behind a --confirm flag. Default mode is dry-run.",
    ),
}

# Logo placement spec:
#   sidebar header (Clean):        sgfx_icon.png        ~200 x auto px
#   main header (Clean):           logo_sgfx.png        ~96 x auto px
#   Grafiks shell HeaderBanner:    logo_sgfx.png        ~100 x auto px
#   About panel hero (Clean):      logo_sgfx.png        ~240 x auto px
#   Window taskbar (.ico):         exe_ico.ico              setWindowIcon(QIcon(exe_ico.ico))
#   Hotkey popup (Clean + Grafiks): debug_icon.png          ~96 x 96 px animated overlay
MANUAL_REVIEW_STATUSES = ["not_run", "recorded", "incomplete"]
MANUAL_REVIEW_RECORD_VERDICTS = ["passed", "failed", "skipped", "incomplete"]
_DASHBOARD_TICKET_FALLBACK = "IDCEVODEV-977874"
_TICKET_ID_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
_MISSING_STATUSES = {
    "missing",
    "no_review_package",
    "no_overview_sheet",
    "not_found",
}
_UNKNOWN_STATUSES = {"error", "failed", "unreadable", "unknown"}
_BLOCKED_MANUAL_STATUSES = {
    "approve",
    "approved",
    "approval",
    "clear",
    "cleared",
    "signoff",
    "sign-off",
    "signed-off",
    "validated",
    "verified",
    "pass",
    "passed",
}
_MANUAL_REVIEW_PENDING_VERDICT = "not_run"
DELIVERY_CHECKLIST_EMPTY_NOTE = (
    "No size-analysis workbook yet for this profile. Click Generate to invoke the BMW pipeline export step."
)
SCREENSHOT_TEST_STATE_EMPTY_NOTE = (
    "No captured screenshots yet. Click Capture to invoke the BMW pipeline screenshot step after pre-flight passes."
)
RISK_SCORE_EMPTY_NOTE = (
    "No prior manual-review session or screenshot evidence was found for this profile. Start with evidence capture and review recording."
)
CROSS_CAR_COMPARISON_EMPTY_NOTE = (
    "No cross-car comparison rows were generated yet. Build local evidence for G70 and G65, then refresh this page."
)
DAILY_DIGEST_EMPTY_NOTE = (
    "No review package on this workspace yet. Click Build to generate one for the active ticket."
)
TEAM_DIGEST_BOARD_EMPTY_NOTE = (
    "No team-board rows were generated yet. Build local evidence first, then refresh this board."
)
OPERATOR_HANDOFF_EMPTY_NOTE = (
    "No shift handoff recorded yet. Add a stopping point before pausing or handing over."
)
MANUAL_REVIEW_EMPTY_NOTE = (
    "Manual review session not started. Click Start Session below to begin, then Record evidence on each Quality-Hero step as you complete it."
)
SETUP_COMPLETE_NOTE = "Setup complete — go to evidence pages to start your QA Hero workflow."


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


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


def _workspace(workspace: Path | str) -> Path:
    return Path(workspace).resolve()


def _path_label(path: Path | str) -> str:
    value = Path(path)
    return value.name or str(value)


def _abbreviate_workspace_text(text: str, workspace: Path | str | None) -> str:
    if workspace is None:
        return text
    root = Path(workspace).resolve()
    root_text = str(root)
    if root_text not in text:
        return text
    return text.replace(root_text, _path_label(root))


def _payload_summary(payload: dict[str, Any], fallback: str, *, workspace: Path | str | None = None) -> str:
    raw = payload.get("summary", "")
    if isinstance(raw, dict):
        raw = ""
    text = str(raw or payload.get("no_data_message", "") or payload.get("note", "") or fallback)
    return _abbreviate_workspace_text(text, workspace)


def _clean_theme(ui_mode: str | None) -> str:
    value = str(ui_mode or "clean").strip().casefold()
    return value if value in THEME_CHOICES else "clean"


def _start_background_poll_timer(interval: float, callback: Callable[[], None]) -> Any:
    from nicegui.timer import Timer

    return Timer(interval, callback, active=True, immediate=False)


def _cancel_background_poll_timer(timer: Any) -> None:
    if timer is None:
        return
    try:
        timer.cancel(with_current_invocation=True)
    except TypeError:
        timer.cancel()
    except RuntimeError:
        return


def _parent_slot_deleted(error: RuntimeError) -> bool:
    message = str(error).casefold()
    return ("parent slot" in message or ("parent element" in message and "slot" in message)) and "deleted" in message


def _nicegui_client_deleted(error: RuntimeError) -> bool:
    message = str(error).casefold()
    return "client this element belongs to has been deleted" in message


def _ignorable_nicegui_runtime_error(error: RuntimeError) -> bool:
    message = str(error).casefold()
    return _parent_slot_deleted(error) or _nicegui_client_deleted(error) or (
        "current slot cannot be determined" in message and "slot stack" in message
    )


def _run_javascript_if_client_alive(ui: Any, code: str) -> None:
    try:
        ui.run_javascript(code)
    except RuntimeError as exc:
        if not _ignorable_nicegui_runtime_error(exc):
            raise


def _find_open_dashboard_port(start_port: int = 8000, end_port: int = 8999) -> int:
    for port in range(start_port, end_port + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise OSError("No open SGFX dashboard port found between 8000 and 8999")


def _dashboard_run_port(*, native: bool, port: int) -> int:
    if native or port:
        return port
    return _find_open_dashboard_port()


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


def _launch_browser_fallback_process(
    *,
    profile_id: str,
    workspace: Path,
    bmw_root: Path | str | None,
    ui_mode: str | None,
    host: str,
    fallback_port: int,
) -> int:
    from sg_preflight.subprocess_utils import hidden_subprocess_kwargs

    command = sgfx_cli_command("dashboard", "run")
    if profile_id:
        command.extend(["--profile", profile_id])
    command.extend(
        [
            "--workspace",
            str(workspace),
            "--ui-mode",
            _clean_theme(ui_mode),
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


def _profile_option_label(option: dict[str, Any]) -> str:
    brand = str(option.get("brand", "BMW") or "BMW")
    lane = str(option.get("lane", "unknown") or "unknown")
    model_type = str(option.get("type", "build") or "build")
    label = f"{brand} / {lane} / {option['id']}"
    target = str(option.get("retarget_target", "") or "")
    if model_type == "retarget" and target:
        label = f"{label} -> {target}"
    elif model_type and model_type != "build":
        label = f"{label} ({model_type})"
    return label


def dashboard_profile_options(
    *,
    bmw_root: Path | str | None = None,
    profile_scope: str = PROFILE_SCOPE_DEFAULT,
) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    for profile in list_run_profiles(bmw_root=bmw_root, profile_scope=profile_scope):
        option: dict[str, Any] = {
            "id": profile.profile_id,
            "label": profile.label,
            "bmw_profile_id": profile.bmw_profile_id,
            "lane": profile.lane,
            "brand": profile.brand,
            "type": profile.model_type,
            "interface_version": profile.interface_version,
            "retarget_target": profile.retarget_target,
            "active_build": profile.active_build,
            "registry_source": profile.registry_source,
        }
        option["select_label"] = _profile_option_label(option)
        options.append(option)
    return options


def _resolve_dashboard_profile_id(
    profile_id: str | None,
    options: list[dict[str, str]],
    *,
    workspace: Path | str | None = None,
    fallback_options: list[dict[str, str]] | None = None,
) -> str:
    requested = str(profile_id or "").strip()
    if not requested:
        preferred = _dashboard_preferred_profile_id(workspace, options) if workspace is not None else ""
        if preferred:
            return preferred
        fallbacks = fallback_options or options
        return fallbacks[0]["id"] if fallbacks else options[0]["id"] if options else ""
    for option in options:
        if option["id"].casefold() == requested.casefold():
            return option["id"]
    return requested.upper()


def _dashboard_profile_known(profile_id: str, options: list[dict[str, str]]) -> bool:
    return any(option["id"].casefold() == profile_id.casefold() for option in options)


def _dashboard_status(raw_status: str, data_available: bool = False) -> str:
    status = raw_status.strip().casefold()
    if data_available and status in {"available", "recorded", "ok"}:
        return "available"
    if status in _MISSING_STATUSES:
        return "missing"
    if status in _UNKNOWN_STATUSES:
        return "unknown"
    if status in {"not_run", "not-run", "not run", "pending"}:
        return "not_run"
    if status in {"not_available", "unavailable", "no_workbook", "profile_not_found"}:
        return "unavailable"
    return status or "unknown"


def _operator_state_path(workspace: Path | str, filename: str) -> Path:
    return _workspace(workspace) / "operator_state" / filename


def _read_operator_state_json(workspace: Path | str, filename: str) -> dict[str, Any]:
    path = _operator_state_path(workspace, filename)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _dashboard_feedback_recipient(workspace: Path | str) -> str:
    payload = _read_operator_state_json(workspace, "dashboard_preferences.json")
    for raw in (payload.get("feedback_email"), os.environ.get(FEEDBACK_EMAIL_ENV, ""), DEFAULT_FEEDBACK_EMAIL):
        configured = str(raw or "").strip()
        if configured and re.fullmatch(r"[A-Za-z0-9._%+\-@,;]+", configured):
            return configured
    return DEFAULT_FEEDBACK_EMAIL


def _candidate_git_roots() -> list[Path]:
    roots: list[Path] = []
    for start in (Path(__file__).resolve(), Path.cwd().resolve(), Path(sys.executable).resolve()):
        roots.extend([start, *start.parents])
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root).casefold()
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


@lru_cache(maxsize=1)
def _dashboard_build_sha() -> str:
    for root in _candidate_git_roots():
        if not (root / ".git").exists():
            continue
        try:
            completed = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=root,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                text=True,
                timeout=3,
                check=False,
                **hidden_subprocess_kwargs(),
            )
        except Exception:
            continue
        value = completed.stdout.strip()
        if completed.returncode == 0 and value:
            try:
                dirty = subprocess.run(
                    ["git", "status", "--short", "--untracked-files=no"],
                    cwd=root,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    text=True,
                    timeout=3,
                    check=False,
                    **hidden_subprocess_kwargs(),
                )
            except Exception:
                return value
            suffix = "-dirty" if dirty.returncode == 0 and dirty.stdout.strip() else ""
            return f"{value}{suffix}"
    return "unknown"


@lru_cache(maxsize=1)
def _dashboard_exe_sha256() -> str:
    if not getattr(sys, "frozen", False):
        return "source-run"
    executable = Path(sys.executable)
    if not executable.is_file():
        return "unavailable"
    digest = hashlib.sha256()
    try:
        with executable.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return "unavailable"
    return digest.hexdigest().upper()


def _dashboard_feedback_context(workspace: Path | str) -> dict[str, str]:
    return {
        "to": _dashboard_feedback_recipient(workspace),
        "build_sha": _dashboard_build_sha(),
        "exe_sha": _dashboard_exe_sha256(),
        "os_version": platform.platform(),
    }


def _dashboard_preferred_profile_id(workspace: Path | str | None, options: list[dict[str, str]]) -> str:
    if workspace is None:
        return ""
    option_ids = {str(option["id"]).casefold(): str(option["id"]) for option in options}
    for filename in ("dashboard_preferences.json", "dashboard_context.json", "operator_context.json"):
        payload = _read_operator_state_json(workspace, filename)
        for key in ("profile_id", "active_profile_id", "selected_profile_id", "last_profile_id"):
            raw = str(payload.get(key, "")).strip()
            if raw and raw.casefold() in option_ids:
                return option_ids[raw.casefold()]
    return ""


def _write_dashboard_profile_preference(workspace: Path | str, profile_id: str) -> dict[str, Any]:
    clean_profile = profile_id.strip()
    payload = _read_operator_state_json(workspace, "dashboard_preferences.json")
    payload["profile_id"] = clean_profile
    payload["last_profile_id"] = clean_profile
    payload["updated_at_utc"] = _utc_now()
    path = _operator_state_path(workspace, "dashboard_preferences.json")
    ensure_parent(path)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def _bool_preference(value: Any, *, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().casefold()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _dashboard_notifications_enabled(workspace: Path | str) -> bool:
    env_value = os.environ.get(DESKTOP_NOTIFICATIONS_ENV)
    if env_value is not None:
        return _bool_preference(env_value, default=True)
    payload = _read_operator_state_json(workspace, "dashboard_preferences.json")
    return _bool_preference(payload.get("desktop_notifications_enabled"), default=True)


def _write_dashboard_notifications_preference(workspace: Path | str, enabled: bool) -> dict[str, Any]:
    payload = _read_operator_state_json(workspace, "dashboard_preferences.json")
    payload["desktop_notifications_enabled"] = bool(enabled)
    payload["updated_at_utc"] = _utc_now()
    path = _operator_state_path(workspace, "dashboard_preferences.json")
    ensure_parent(path)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def _full_qa_profile_output_token(profile_id: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(profile_id or "unknown").strip()).strip("._-")
    return (token or "unknown").lower()


def _full_qa_wizard_state_path(profile_id: str, *, home: Path | None = None) -> Path:
    root = Path(home).resolve() if home is not None else Path.home().resolve()
    return root / "sgfx_outputs" / _full_qa_profile_output_token(profile_id) / ".wizard_state.json"


def _read_full_qa_wizard_state(profile_id: str, *, home: Path | None = None) -> dict[str, Any]:
    path = _full_qa_wizard_state_path(profile_id, home=home)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_full_qa_wizard_state(profile_id: str, payload: dict[str, Any], *, home: Path | None = None) -> Path:
    path = _full_qa_wizard_state_path(profile_id, home=home)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    temp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    temp_path.replace(path)
    return path


def _delete_full_qa_wizard_state(profile_id: str, *, home: Path | None = None) -> None:
    try:
        _full_qa_wizard_state_path(profile_id, home=home).unlink()
    except FileNotFoundError:
        return


def _ticket_id_from_payload(payload: dict[str, Any]) -> str:
    for key in ("active_ticket_id", "ticket_id", "jira_ticket", "jira_ticket_id", "ticket"):
        raw = str(payload.get(key, "")).strip().upper()
        if raw and _TICKET_ID_PATTERN.fullmatch(raw):
            return raw
    return ""


def _dashboard_ticket_from_operator_state(workspace: Path | str) -> str:
    for filename in ("dashboard_context.json", "operator_context.json", "active_ticket.json"):
        ticket_id = _ticket_id_from_payload(_read_operator_state_json(workspace, filename))
        if ticket_id:
            return ticket_id
    return ""


def _dashboard_ticket_from_git_branch(workspace: Path | str) -> str:
    from sg_preflight.subprocess_utils import hidden_subprocess_kwargs

    try:
        completed = subprocess.run(
            ["git", "-C", str(_workspace(workspace)), "rev-parse", "--abbrev-ref", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            text=True,
            timeout=2,
            **hidden_subprocess_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if completed.returncode != 0:
        return ""
    match = _TICKET_ID_PATTERN.search(str(completed.stdout or "").upper())
    return match.group(0) if match else ""


def _ticket_ids_from_activity_log(workspace: Path | str, *, limit: int = 6) -> list[str]:
    path = _workspace(workspace) / "operator_state" / "activity_log.jsonl"
    if not path.is_file():
        return []
    tickets: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in reversed(lines):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            payload = {"note": line}
        haystack = json.dumps(payload, ensure_ascii=False) if isinstance(payload, dict) else str(payload)
        for match in _TICKET_ID_PATTERN.finditer(haystack.upper()):
            ticket_id = match.group(0)
            if ticket_id not in tickets:
                tickets.append(ticket_id)
                if len(tickets) >= limit:
                    return tickets
    return tickets


def _write_active_ticket_state(workspace: Path | str, ticket_id: str, *, source: str) -> dict[str, Any]:
    clean_ticket = ticket_id.strip().upper()
    if not _TICKET_ID_PATTERN.fullmatch(clean_ticket):
        raise ValueError(f"Unsupported ticket ID: {ticket_id}")
    path = _operator_state_path(workspace, "active_ticket.json")
    payload = _read_operator_state_json(workspace, "active_ticket.json")
    payload.update(
        {
            "active_ticket_id": clean_ticket,
            "ticket_id": clean_ticket,
            "source": source.strip() or "operator",
            "updated_at_utc": _utc_now(),
        }
    )
    ensure_parent(path)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    temp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(path)
    return payload


def _daily_digest_ticket_context(workspace: Path | str) -> dict[str, Any]:
    active_ticket = _ticket_id_from_payload(_read_operator_state_json(workspace, "active_ticket.json"))
    recent_ticket_ids = _ticket_ids_from_activity_log(workspace)
    if active_ticket:
        return {
            "active_ticket_id": active_ticket,
            "ticket_id_hint": active_ticket,
            "ticket_id_source": "active_ticket_file",
            "recent_ticket_ids": recent_ticket_ids,
        }
    operator_ticket = _dashboard_ticket_from_operator_state(workspace)
    if operator_ticket:
        return {
            "active_ticket_id": operator_ticket,
            "ticket_id_hint": operator_ticket,
            "ticket_id_source": "operator_state",
            "recent_ticket_ids": recent_ticket_ids,
        }
    branch_ticket = _dashboard_ticket_from_git_branch(workspace)
    if branch_ticket:
        return {
            "active_ticket_id": branch_ticket,
            "ticket_id_hint": branch_ticket,
            "ticket_id_source": "git_branch",
            "recent_ticket_ids": recent_ticket_ids,
        }
    if recent_ticket_ids:
        return {
            "active_ticket_id": recent_ticket_ids[0],
            "ticket_id_hint": recent_ticket_ids[0],
            "ticket_id_source": "activity_log",
            "recent_ticket_ids": recent_ticket_ids,
        }
    return {
        "active_ticket_id": "",
        "ticket_id_hint": DAILY_DIGEST_TICKET_ID_PLACEHOLDER,
        "ticket_id_source": "manual_entry",
        "recent_ticket_ids": [],
    }


def _dashboard_active_ticket_id(workspace: Path | str) -> str:
    state_ticket = _dashboard_ticket_from_operator_state(workspace)
    if state_ticket:
        return state_ticket
    for key in ("SGFX_ACTIVE_TICKET_ID", "SGFX_DASHBOARD_TICKET_ID"):
        raw = os.environ.get(key, "").strip().upper()
        if raw and _TICKET_ID_PATTERN.fullmatch(raw):
            return raw
    branch_ticket = _dashboard_ticket_from_git_branch(workspace)
    if branch_ticket:
        return branch_ticket
    return _DASHBOARD_TICKET_FALLBACK


def load_dashboard_preference(workspace: Path | str) -> str:
    payload = _read_operator_state_json(workspace, "dashboard_preferences.json")
    return _clean_theme(str(payload.get("theme", "clean")))


def save_dashboard_preference(workspace: Path | str, theme: str) -> dict[str, Any]:
    payload = _read_operator_state_json(workspace, "dashboard_preferences.json")
    payload["theme"] = _clean_theme(theme)
    payload["updated_at_utc"] = _utc_now()
    path = _operator_state_path(workspace, "dashboard_preferences.json")
    ensure_parent(path)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


SCREENSHOT_TEST_STATE_OWNERSHIP_NOTE = (
    "Screenshot capture runs from the lane-correct BMW Git pipeline script after confirmation; SGFX reads the output as evidence."
)


def _int_payload_value(payload: dict[str, Any], key: str) -> int:
    try:
        return int(payload.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _screenshot_empty_note(payload: dict[str, Any]) -> str:
    if _int_payload_value(payload, "actual_count") == 0 and _int_payload_value(payload, "diff_count") == 0:
        return SCREENSHOT_TEST_STATE_EMPTY_NOTE
    return ""


def _reader_page(
    *,
    page_id: str,
    title: str,
    tagline: str,
    reader: Callable[[], dict[str, Any]],
    workspace: Path | str | None = None,
    ownership_note: str = "",
) -> dict[str, Any]:
    try:
        payload = reader()
    except Exception as exc:
        return {
            "id": page_id,
            "title": title,
            "tagline": tagline,
            "ownership_note": ownership_note,
            "status": "unknown",
            "data_available": False,
            "summary": f"{title} could not be read: {exc}",
            "items": [],
            "payload": {},
        }
    raw_status = str(payload.get("status", "unknown") or "unknown")
    data_available = bool(payload.get("data_available", False))
    page = {
        "id": page_id,
        "title": title,
        "tagline": tagline,
        "ownership_note": ownership_note,
        "status": _dashboard_status(raw_status, data_available),
        "raw_status": raw_status,
        "data_available": data_available,
        "summary": _payload_summary(payload, title, workspace=workspace),
        "items": _payload_items(payload),
        "payload": _sanitized_payload(payload),
    }
    if page_id == "screenshot-test-state":
        page["empty_state_note"] = _screenshot_empty_note(payload)
    return page


def _delivery_checklist_page(
    profile_id: str,
    workspace: Path,
    *,
    bmw_root: Path | str | None = None,
    setup_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    page = _reader_page(
        page_id="delivery-checklist",
        title="Delivery Checklist",
        tagline="Workbook evidence per delivery profile (read-only).",
        reader=lambda: read_delivery_checklist(profile_id=profile_id, workspace=workspace),
        workspace=workspace,
    )
    page["confluence_anchors"] = [DELIVERY_CHECKLIST_CONFLUENCE_ANCHOR]
    page["setup_status"] = setup_status or build_dependency_onboarding_status(workspace=workspace, bmw_root=bmw_root)
    page["workbook_trigger"] = build_delivery_workbook_trigger(
        profile_id=profile_id,
        workspace=workspace,
        bmw_root=bmw_root,
    )
    if page.get("status") != "unavailable":
        return page
    page["empty_state_note"] = DELIVERY_CHECKLIST_EMPTY_NOTE
    preflight = page["workbook_trigger"].get("preflight", {})
    page["actions"] = [
        {
            "id": GENERATE_WORKBOOK_ACTION_ID,
            "label": GENERATE_WORKBOOK_ACTION_LABEL,
            "requires_confirmation": True,
            "timeout_seconds": GENERATE_WORKBOOK_TIMEOUT_SECONDS,
            "preflight": preflight,
            "disabled": not bool(preflight.get("can_run", False)),
            "confirmation_message": str(preflight.get("confirmation_message", "")),
            "confluence_anchor": DELIVERY_CHECKLIST_CONFLUENCE_ANCHOR,
        }
    ]
    return page


def _full_qa_pass_page(
    profile_id: str,
    workspace: Path,
    *,
    bmw_root: Path | str | None = None,
    trusted_tool_mode: bool = False,
) -> dict[str, Any]:
    del bmw_root, trusted_tool_mode
    payload = {
        "schema_version": 1,
        "profile_id": profile_id,
        "workspace": str(workspace),
        "status": "not_run",
        "run_status": "not_run",
        "summary": "Full QA pass has not run in this dashboard session.",
        "progress": {"completed_steps": 0, "total_steps": 9, "percent": 0},
        "steps": [],
        "confirmation_items": [],
        "operator_confirmation_required": False,
        "manual_review_required": True,
        "records_operator_verdict": False,
        "is_approval": False,
        "guardrails": list(DASHBOARD_GUARDRAILS),
        "confluence_anchors": [QUALITY_HERO_CONFLUENCE_ANCHOR, DELIVERY_CHECKLIST_CONFLUENCE_ANCHOR],
    }
    return {
        "id": "full-qa-pass",
        "title": "Full QA Pass",
        "tagline": "One local pass through setup, evidence, review assist, and handoff status.",
        "status": str(payload.get("status", "unknown")),
        "data_available": True,
        "summary": str(payload.get("summary", "")),
        "items": [
            {
                "label": str(step.get("label", "")),
                "status": str(step.get("status", "")),
                "detail": str(step.get("summary", "")),
            }
            for step in payload.get("steps", [])
            if isinstance(step, dict)
        ],
        "payload": payload,
        "confluence_anchors": list(payload.get("confluence_anchors", [])),
    }


def _batch_full_qa_pass_page(profile_id: str, workspace: Path) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "profile_id": profile_id,
        "workspace": str(workspace),
        "status": "not_run",
        "summary": "Select multiple profiles and run their Full QA Pass snapshots one at a time.",
        "progress": {"completed_profiles": 0, "total_profiles": 0, "percent": 0},
        "results": [],
        "manual_review_required": True,
        "records_operator_verdict": False,
        "is_approval": False,
        "guardrails": list(DASHBOARD_GUARDRAILS),
        "confluence_anchors": [QUALITY_HERO_CONFLUENCE_ANCHOR],
    }
    return {
        "id": "batch-full-qa-pass",
        "title": "Batch Full QA Pass",
        "tagline": "Run selected profiles sequentially; one profile finishes before the next starts.",
        "status": "not_run",
        "data_available": True,
        "summary": str(payload.get("summary", "")),
        "items": [],
        "payload": payload,
        "confluence_anchors": list(payload.get("confluence_anchors", [])),
    }


_TRUTHY_TRIGGERS = frozenset({"1", "true", "yes", "on"})


def _is_truthy_trigger(value: str | None, *, default: str = "") -> bool:
    raw = str(value if value is not None else default or "").strip().casefold()
    return raw in _TRUTHY_TRIGGERS


# H-28: process-local dedup for the Full QA Pass trigger so a NiceGUI WebSocket
# reconnect storm cannot re-fire `build_full_qa_pass` after the H-25 ui.navigate.to
# redirect (the storm re-hits the page handler with the cached `?full_qa_run=1`
# URL before the redirect lands client-side, observed 2026-05-29 07:17:28-31:
# 5 fires for G70 within 2.4s).
#
# The dedup key is per-profile (not per-second) so even storms that span
# multiple wall-clock seconds collide on the same recorded token. The 30s
# expiry releases the lock once any reasonable operator re-click cadence has
# passed. The redirect + early-return path stays as belt+suspenders.
FULL_QA_PASS_DEDUP_WINDOW_SECONDS = 30.0
_full_qa_pass_dedup_lock = threading.Lock()
_full_qa_pass_dedup_tokens: dict[str, float] = {}


def _full_qa_pass_token(profile_id: str, ts_seconds: int | None = None) -> str:
    """Per-directive shape `full-qa-pass:<profile>:<ts_floor_seconds>` — the
    suffix preserves audit-trail readability; the dedup decision keys on the
    `profile_id` component (see `_should_fire_full_qa_pass`)."""
    if ts_seconds is None:
        ts_seconds = int(time.time())
    return f"full-qa-pass:{profile_id}:{int(ts_seconds)}"


def _full_qa_pass_dedup_key(profile_id: str) -> str:
    """The dict key — per-profile so multi-second reconnect storms still dedup."""
    return f"full-qa-pass:{str(profile_id or '').strip().upper() or 'UNKNOWN'}"


def _should_fire_full_qa_pass(profile_id: str, *, now: float | None = None) -> bool:
    """Return True iff this profile has NOT been fired within the dedup window.

    Side effect on a True return: records the new fire so any subsequent call
    within `FULL_QA_PASS_DEDUP_WINDOW_SECONDS` returns False. Side effect on a
    False return: none. Prunes expired tokens on every call.
    """
    key = _full_qa_pass_dedup_key(profile_id)
    current = now if now is not None else time.monotonic()
    with _full_qa_pass_dedup_lock:
        expired = [k for k, exp in _full_qa_pass_dedup_tokens.items() if exp <= current]
        for k in expired:
            _full_qa_pass_dedup_tokens.pop(k, None)
        if key in _full_qa_pass_dedup_tokens:
            return False
        _full_qa_pass_dedup_tokens[key] = current + FULL_QA_PASS_DEDUP_WINDOW_SECONDS
        return True


def _reset_full_qa_pass_dedup() -> None:
    """Test helper: clear the dedup cache so each unit test starts clean."""
    with _full_qa_pass_dedup_lock:
        _full_qa_pass_dedup_tokens.clear()


def _publish_live_state(
    workspace: Path | str,
    *,
    dashboard_surface: str,
    profile_id: str = "",
    wizard_step_id: str = "",
    wizard_step_index: int = -1,
    wizard_step_total: int = 0,
    queued_acknowledgments: tuple[str, ...] = (),
    last_operator_action: tuple[str, str] | None = None,
    last_error: str | None = None,
) -> None:
    """H-26 hookpoint: best-effort debounced write to live_state.json.

    All failures are swallowed — observability must never crash an operator
    surface. The debounced writer batches updates so a sub-250ms burst becomes
    one disk write.
    """
    try:
        from sg_preflight.live_state import (
            LastOperatorAction,
            LiveStateSnapshot,
            _utc_now_ms,
            write_live_state,
        )
        action = (
            LastOperatorAction(verb=last_operator_action[0], surface=last_operator_action[1], ts=_utc_now_ms())
            if last_operator_action
            else None
        )
        snapshot = LiveStateSnapshot(
            dashboard_surface=dashboard_surface,
            profile_id=profile_id,
            wizard_step_id=wizard_step_id,
            wizard_step_index=wizard_step_index,
            wizard_step_total=wizard_step_total,
            queued_acknowledgments=tuple(queued_acknowledgments),
            last_operator_action=action,
            last_error=last_error,
        )
        write_live_state(workspace, snapshot)
    except Exception:
        # Observability never blocks; failures are not surfaced to the operator.
        return


def _snapshot_with_full_qa_payload(snapshot: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    pages = list(snapshot.get("pages", []))
    for index, page in enumerate(pages):
        if not isinstance(page, dict) or str(page.get("id", "")) != "full-qa-pass":
            continue
        steps = [step for step in payload.get("steps", []) if isinstance(step, dict)]
        pages[index] = {
            **page,
            "status": str(payload.get("status", payload.get("run_status", "unknown"))),
            "summary": str(payload.get("summary", "")),
            "items": [
                {
                    "label": str(step.get("label", "")),
                    "status": str(step.get("status", "")),
                    "detail": str(step.get("summary", "")),
                }
                for step in steps
            ],
            "payload": payload,
            "confluence_anchors": list(payload.get("confluence_anchors", page.get("confluence_anchors", []))),
        }
        break
    return {**snapshot, "pages": pages}


def _onboarding_guide_page(
    profile_id: str,
    workspace: Path | str,
    *,
    setup_status: dict[str, Any],
    bmw_root: Path | str | None = None,
) -> dict[str, Any]:
    payload = build_onboarding_guide(
        profile_id,
        workspace=workspace,
        bmw_root=bmw_root,
        dependency_status=setup_status,
    )
    return {
        "id": "onboarding-guide",
        "title": "Onboarding Guide",
        "tagline": "New-operator path through setup, evidence pages, manual review, and handoff.",
        "status": str(payload.get("onboarding_status", "unknown")),
        "data_available": True,
        "summary": str(payload.get("summary", "")),
        "items": list(payload.get("items", [])),
        "payload": payload,
        "confluence_anchors": list(payload.get("confluence_anchors", [])),
    }


def _screenshot_test_state_page(
    profile_id: str,
    workspace: Path,
    *,
    bmw_root: Path | str | None = None,
) -> dict[str, Any]:
    page = _reader_page(
        page_id="screenshot-test-state",
        title="Screenshot Test State",
        tagline="BMW + MINI baseline / actual / diff counts per brand.",
        reader=lambda: read_bmw_screenshot_state(
            profile_id,
            workspace=workspace,
            bmw_root=bmw_root,
            sg_project_root=workspace,
        ),
        workspace=workspace,
        ownership_note=SCREENSHOT_TEST_STATE_OWNERSHIP_NOTE,
    )
    page["confluence_anchors"] = [QUALITY_HERO_CONFLUENCE_ANCHOR, BMW_PIPELINE_PYTHON_CONFLUENCE_ANCHOR]
    preflight = check_screenshot_capture_environment(
        profile_id=profile_id,
        workspace=workspace,
        bmw_root=bmw_root,
    )
    page["actions"] = [
        {
            "id": SCREENSHOT_CAPTURE_ACTION_ID,
            "label": SCREENSHOT_CAPTURE_ACTION_LABEL,
            "requires_confirmation": True,
            "timeout_seconds": SCREENSHOT_CAPTURE_TIMEOUT_SECONDS,
            "preflight": preflight,
            "disabled": not bool(preflight.get("can_run", False)),
            "confirmation_message": str(preflight.get("confirmation_message", "")),
            "confluence_anchor": BMW_PIPELINE_PYTHON_CONFLUENCE_ANCHOR,
        }
    ]
    return page


def _risk_score_page(
    profile_id: str,
    workspace: Path,
    *,
    bmw_root: Path | str | None = None,
) -> dict[str, Any]:
    page = _reader_page(
        page_id="risk-score",
        title="Risk Score",
        tagline="Per-car review focus signal with delta since latest local manual review.",
        reader=lambda: read_per_car_risk_score(
            profile_id,
            workspace=workspace,
            bmw_root=bmw_root,
        ),
        workspace=workspace,
        ownership_note="Risk score focuses review order only; operator verdicts remain manual.",
    )
    payload = page.get("payload", {}) if isinstance(page.get("payload"), dict) else {}
    page["confluence_anchors"] = list(payload.get("confluence_anchors", []))
    if page.get("status") == "not_run":
        page["empty_state_note"] = RISK_SCORE_EMPTY_NOTE
    return page


def _cross_car_comparison_page(
    workspace: Path,
    *,
    bmw_root: Path | str | None = None,
) -> dict[str, Any]:
    page = _reader_page(
        page_id="cross-car-comparison",
        title="Cross-Car Comparison",
        tagline="G70 vs G65 risk-score widget side by side.",
        reader=lambda: build_cross_car_comparison(
            workspace=workspace,
            bmw_root=bmw_root,
            left_profile="G70",
            right_profile="G65",
        ),
        workspace=workspace,
        ownership_note="Read-only comparison of local risk-score evidence; no BMW source or network writes.",
    )
    payload = page.get("payload", {}) if isinstance(page.get("payload"), dict) else {}
    page["confluence_anchors"] = list(payload.get("confluence_anchors", []))
    if not page.get("items"):
        page["empty_state_note"] = CROSS_CAR_COMPARISON_EMPTY_NOTE
    return page


def _screenshot_review_viewer_output_root(workspace: Path, profile_id: str) -> Path:
    safe_profile = re.sub(r"[^A-Za-z0-9_.-]+", "_", profile_id.strip().lower() or "profile")
    return operator_ui_root(workspace) / "screenshot-review-viewer" / safe_profile


def _missing_actual_diagnostics_output_root(workspace: Path, profile_id: str) -> Path:
    safe_profile = re.sub(r"[^A-Za-z0-9_.-]+", "_", profile_id.strip().lower() or "profile")
    return operator_ui_root(workspace) / "missing-actual-diagnostics" / safe_profile


def _screenshot_review_viewer_url(profile_id: str, item_key: str = "") -> str:
    safe_profile = re.sub(r"[^A-Za-z0-9_.-]+", "_", profile_id.strip().lower() or "profile")
    url = f"/sgfx-operator-ui/screenshot-review-viewer/{safe_profile}/screenshot-review-viewer.html"
    if item_key:
        url += f"#{quote(item_key, safe='')}"
    return url


def _materialize_screenshot_review_viewer_for_dashboard(
    profile_id: str,
    workspace: Path,
    *,
    bmw_root: Path | str | None = None,
) -> Any:
    profile = get_run_profile(profile_id, workspace, bmw_root=bmw_root)
    project_root = profile.source_project_root()
    prep = build_visual_review_prep(profile.profile_id, project_root)
    state = read_bmw_screenshot_state(
        profile.profile_id,
        workspace=workspace,
        bmw_root=bmw_root,
        sg_project_root=project_root,
    )
    candidate_roots = tuple(
        Path(value).resolve()
        for value in (str(state.get("actuals_root", "")).strip(),)
        if value and Path(value).is_dir()
    )
    diff_roots = tuple(
        Path(value).resolve()
        for value in (str(state.get("diff_root", "")).strip(),)
        if value and Path(value).is_dir()
    )
    expected_root_value = str(state.get("expected_root", "")).strip()
    return build_screenshot_review_viewer(
        profile.profile_id,
        project_root,
        _screenshot_review_viewer_output_root(workspace, profile.profile_id),
        expected_root=Path(expected_root_value).resolve() if expected_root_value else None,
        candidate_roots=candidate_roots,
        diff_reference_roots=diff_roots,
        priority_names=tuple(str(item) for item in prep.priority_screenshots),
    )


def _notify_completion_safe(
    *,
    title: str,
    message: str,
    workspace: Path,
    action_id: str,
    profile_id: str,
    evidence_path: str = "",
    enabled: bool | None = None,
    elapsed_seconds: Any | None = None,
    minimum_elapsed_seconds: int = 0,
) -> None:
    if enabled is False or (enabled is None and not _dashboard_notifications_enabled(workspace)):
        return
    if minimum_elapsed_seconds > 0:
        try:
            elapsed = int(float(elapsed_seconds or 0))
        except (TypeError, ValueError):
            elapsed = 0
        if elapsed < minimum_elapsed_seconds:
            return
    try:
        notify_desktop_completion(
            title=title,
            message=message,
            workspace=workspace,
            action_id=action_id,
            profile_id=profile_id,
            evidence_path=evidence_path,
        )
    except Exception:
        return


def _full_qa_completion_notification(profile_id: str, payload: dict[str, Any]) -> dict[str, str]:
    status = str(payload.get("status", payload.get("run_status", "unknown"))).strip().casefold()
    counts = payload.get("counts", {}) if isinstance(payload.get("counts"), dict) else {}

    def _count(key: str) -> int:
        try:
            return int(counts.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0

    failed_count = _count("failed") + _count("unavailable")
    if status in {"failed", "unavailable"} or failed_count > 0:
        return {
            "title": "Full QA Pass needs attention",
            "message": f"Full QA Pass for {profile_id} did not complete. See dashboard.",
        }
    review_count = _count("incomplete") + _count("confirmation_pending") + len(
        payload.get("confirmation_items", []) if isinstance(payload.get("confirmation_items"), list) else []
    )
    return {
        "title": "Full QA Pass finished",
        "message": f"Full QA Pass for {profile_id} completed. {review_count} items ready for your review.",
    }


def _payload_items(payload: dict[str, Any]) -> list[dict[str, str]]:
    handoff_items = payload.get("handoff_items", [])
    if isinstance(handoff_items, list) and handoff_items:
        return [
            {
                "label": str(item.get("label", "item")),
                "status": str(item.get("status", "unknown")),
                "detail": str(item.get("detail", "")),
            }
            for item in handoff_items
            if isinstance(item, dict)
        ]
    comparison_rows = payload.get("comparison_rows", [])
    if isinstance(comparison_rows, list) and comparison_rows:
        return [
            {
                "label": str(item.get("label", "row")),
                "status": str(item.get("status", "unknown")),
                "detail": f"{item.get('left_value', '')} vs {item.get('right_value', '')}; {item.get('delta_label', '')}",
            }
            for item in comparison_rows
            if isinstance(item, dict)
        ]
    board_rows = payload.get("board_rows", [])
    if isinstance(board_rows, list) and board_rows:
        return [
            {
                "label": str(item.get("label", "row")),
                "status": str(item.get("status", "unknown")),
                "detail": str(item.get("detail", "")),
            }
            for item in board_rows
            if isinstance(item, dict)
        ]
    signals = payload.get("signals", [])
    if isinstance(signals, list) and signals:
        return [
            {
                "label": str(signal.get("id", "signal")),
                "status": str(signal.get("status", "unknown")),
                "detail": str(signal.get("detail", "")),
            }
            for signal in signals
            if isinstance(signal, dict)
        ]
    checks = payload.get("checks", [])
    if isinstance(checks, list) and checks:
        items = []
        for check in checks:
            if not isinstance(check, dict):
                continue
            items.append(
                {
                    "label": str(check.get("label", check.get("key", "check"))),
                    "status": str(check.get("status", "unknown")),
                    "detail": str(check.get("raw_value", "")),
                }
            )
        return items
    counts = []
    for key, label in (
        ("expected_count", "Expected"),
        ("actual_count", "Actual"),
        ("diff_count", "Diff"),
        ("disabled_test_count", "Disabled"),
        ("sg_perspectives_screenshot_count", "SG Perspectives"),
        ("sg_perspectives_comparison_count", "SG Comparisons"),
    ):
        if key in payload:
            counts.append({"label": label, "status": str(payload.get(key, 0)), "detail": ""})
    return counts


def _sanitized_payload(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "profile_id",
        "matched_profile_id",
        "brand",
        "status",
        "data_available",
        "summary",
        "workbook_path",
        "expected_count",
        "actual_count",
        "diff_count",
        "disabled_test_count",
        "expected_root",
        "actuals_root",
        "diff_root",
        "sg_perspectives_root",
        "sg_perspectives_latest_folder",
        "sg_perspectives_screenshot_count",
        "sg_perspectives_comparison_count",
        "risk_score",
        "risk_level",
        "current_snapshot",
        "latest_review",
        "delta_since_last_review",
        "signals",
        "confluence_anchors",
        "manual_review_required",
        "is_approval",
        "note",
        "guidance",
        "share_decision",
        "sections",
        "profiles",
        "board_rows",
        "comparison_axis",
        "comparison_rows",
        "left_profile",
        "right_profile",
        "widget_label",
        "handoff_count",
        "latest_handoff",
        "handoff_items",
    )
    return {key: payload[key] for key in allowed if key in payload}


DAILY_DIGEST_BUILD_PACKAGE_ACTION_ID = "build-review-package"
DAILY_DIGEST_BUILD_PACKAGE_ACTION_LABEL = "Build review package for this workspace"
QUALITY_HERO_REPORT_ACTION_ID = "build-quality-hero-report"
QUALITY_HERO_REPORT_ACTION_LABEL = "Build Quality-Hero report"
QUALITY_HERO_REPORT_ATTACH_ACTION_LABEL = "Attach to Jira ticket"
DAILY_DIGEST_TICKET_ID_PLACEHOLDER = "e.g., IDCEVODEV-1005738"
_DAILY_DIGEST_PARTIAL_SECTION_KEYS = (
    "what_landed_today",
    "workflow_status",
    "evidence_prepared",
    "manual_review_pending",
)


def _section_count(section: object) -> int:
    if not isinstance(section, dict):
        return 0
    try:
        return int(section.get("count", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _daily_digest_has_partial_signal(sections: dict[str, Any]) -> bool:
    for key in _DAILY_DIGEST_PARTIAL_SECTION_KEYS:
        if _section_count(sections.get(key)) > 0:
            return True
    return False


def _daily_digest_page(
    workspace: Path,
    profile_id: str,
    *,
    active_ticket_id: str = "",
    ticket_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = dict(ticket_context or {})
    default_ticket = str(context.get("active_ticket_id", active_ticket_id)).strip()
    ticket_hint = str(context.get("ticket_id_hint", default_ticket or DAILY_DIGEST_TICKET_ID_PLACEHOLDER)).strip()
    base_action = {
        "requires_ticket_id": True,
        "ticket_id_hint": ticket_hint or DAILY_DIGEST_TICKET_ID_PLACEHOLDER,
        "ticket_id_default": default_ticket,
        "ticket_id_source": str(context.get("ticket_id_source", "manual_entry")),
        "recent_ticket_ids": list(context.get("recent_ticket_ids", [])),
        "confluence_anchor": SG_DAILY_CONFLUENCE_ANCHOR,
    }
    actions = [
        {
            "id": DAILY_DIGEST_BUILD_PACKAGE_ACTION_ID,
            "label": DAILY_DIGEST_BUILD_PACKAGE_ACTION_LABEL,
            **base_action,
        },
        {
            "id": QUALITY_HERO_REPORT_ACTION_ID,
            "label": QUALITY_HERO_REPORT_ACTION_LABEL,
            **base_action,
        },
    ]
    try:
        digest = build_latest_daily_digest(workspace=workspace)
    except Exception as exc:
        return {
            "id": "daily-digest",
            "title": "Daily Digest",
            "tagline": "Morning status snapshot for the SG Daily standup.",
            "status": "unknown",
            "data_available": False,
            "summary": f"Daily digest could not be read: {exc}",
            "items": [],
            "actions": actions,
            "confluence_anchors": [SG_DAILY_CONFLUENCE_ANCHOR],
            "payload": {
                "profile_id": profile_id,
                "active_ticket_id": default_ticket,
                "ticket_id_source": str(context.get("ticket_id_source", "manual_entry")),
                "recent_ticket_ids": list(context.get("recent_ticket_ids", [])),
            },
        }
    sections = digest.get("sections", {}) if isinstance(digest, dict) else {}
    items: list[dict[str, str]] = []
    if isinstance(sections, dict):
        for key in ("what_landed_today", "workflow_status", "evidence_prepared"):
            section = sections.get(key, {})
            if not isinstance(section, dict):
                continue
            items.append(
                {
                    "label": str(section.get("heading", key.replace("_", " ").title())),
                    "status": str(section.get("count", 0)),
                    "detail": str(section.get("empty_message", "")) if not section.get("count") else "items available",
                }
            )
    raw_status = str(digest.get("status", "unknown"))
    data_available = bool(digest.get("data_available", False))
    has_partial = isinstance(sections, dict) and _daily_digest_has_partial_signal(sections)
    status_value = _dashboard_status(raw_status, data_available)
    if raw_status == "no_review_package" and has_partial:
        status_value = "incomplete"
    page = {
        "id": "daily-digest",
        "title": "Daily Digest",
        "tagline": "Morning status snapshot for the SG Daily standup.",
        "status": status_value,
        "raw_status": raw_status,
        "data_available": data_available or has_partial,
        "summary": str(digest.get("no_data_message", "Daily digest snapshot loaded.")),
        "items": items,
        "actions": actions,
        "confluence_anchors": [SG_DAILY_CONFLUENCE_ANCHOR],
        "payload": {
            "status": digest.get("status", "unknown"),
            "scope": digest.get("scope", []),
            "date": digest.get("date", ""),
            "active_ticket_id": default_ticket,
            "ticket_id_source": str(context.get("ticket_id_source", "manual_entry")),
            "recent_ticket_ids": list(context.get("recent_ticket_ids", [])),
        },
    }
    if raw_status == "no_review_package" or status_value == "incomplete":
        page["empty_state_note"] = DAILY_DIGEST_EMPTY_NOTE
    return page


def _deferred_daily_digest_page(profile_id: str, ticket_context: dict[str, Any] | None = None) -> dict[str, Any]:
    context = dict(ticket_context or {})
    default_ticket = str(context.get("active_ticket_id", "")).strip()
    ticket_hint = str(context.get("ticket_id_hint", default_ticket or DAILY_DIGEST_TICKET_ID_PLACEHOLDER)).strip()
    base_action = {
        "requires_ticket_id": True,
        "ticket_id_hint": ticket_hint or DAILY_DIGEST_TICKET_ID_PLACEHOLDER,
        "ticket_id_default": default_ticket,
        "ticket_id_source": str(context.get("ticket_id_source", "manual_entry")),
        "recent_ticket_ids": list(context.get("recent_ticket_ids", [])),
        "confluence_anchor": SG_DAILY_CONFLUENCE_ANCHOR,
    }
    return {
        "id": "daily-digest",
        "title": "Daily Digest",
        "tagline": "Morning status snapshot for the SG Daily standup.",
        "status": "not_run",
        "raw_status": "not_run",
        "data_available": False,
        "summary": f"Daily Digest for {profile_id} refreshes when opened.",
        "items": [],
        "actions": [
            {
                "id": DAILY_DIGEST_BUILD_PACKAGE_ACTION_ID,
                "label": DAILY_DIGEST_BUILD_PACKAGE_ACTION_LABEL,
                **base_action,
            },
            {
                "id": QUALITY_HERO_REPORT_ACTION_ID,
                "label": QUALITY_HERO_REPORT_ACTION_LABEL,
                **base_action,
            },
        ],
        "confluence_anchors": [SG_DAILY_CONFLUENCE_ANCHOR],
        "payload": {
            "profile_id": profile_id,
            "status": "not_run",
            "scope": [],
            "date": "",
            "active_ticket_id": default_ticket,
            "ticket_id_source": str(context.get("ticket_id_source", "manual_entry")),
            "recent_ticket_ids": list(context.get("recent_ticket_ids", [])),
        },
        "empty_state_note": "Open Daily Digest to load the local standup snapshot.",
        "deferred": True,
    }


def _team_digest_board_page(
    workspace: Path,
    profile_id: str,
    *,
    bmw_root: Path | str | None = None,
) -> dict[str, Any]:
    def _reader() -> dict[str, Any]:
        board = build_team_daily_digest_board(
            workspace=workspace,
            bmw_root=bmw_root,
            profiles=(profile_id, "G70", "G65"),
            ticket_id=_dashboard_active_ticket_id(workspace),
        )
        sections = board.get("sections", {}) if isinstance(board.get("sections"), dict) else {}
        rows: list[dict[str, Any]] = []
        share = board.get("share_decision", {}) if isinstance(board.get("share_decision"), dict) else {}
        rows.append(
            {
                "label": "Sharing model",
                "status": str(share.get("status", "unknown")),
                "detail": f"Selected: {share.get('selected_model', 'unknown')}",
            }
        )
        for section_key in ("risk_by_profile", "what_landed_today", "workflow_status"):
            section = sections.get(section_key, {}) if isinstance(sections, dict) else {}
            if not isinstance(section, dict):
                continue
            for item in section.get("items", [])[:4]:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label", item.get("profile_id", section.get("heading", section_key))))
                status = str(item.get("status", "unknown"))
                detail = str(item.get("detail", ""))
                if "risk_score" in item:
                    detail = f"risk {item.get('risk_score', 0)}/100; {detail}".strip()
                rows.append({"label": label, "status": status, "detail": detail})
        board["board_rows"] = rows
        return board

    page = _reader_page(
        page_id="team-digest-board",
        title="Team Digest Board",
        tagline="Local snapshot for standup review across selected car profiles.",
        reader=_reader,
        workspace=workspace,
        ownership_note="Default sharing model is local snapshot; SVN and Confluence sharing remain explicit gates.",
    )
    payload = page.get("payload", {}) if isinstance(page.get("payload"), dict) else {}
    page["confluence_anchors"] = list(payload.get("confluence_anchors", []))
    if not page.get("items"):
        page["empty_state_note"] = TEAM_DIGEST_BOARD_EMPTY_NOTE
    return page


def _deferred_team_digest_board_page(profile_id: str) -> dict[str, Any]:
    return {
        "id": "team-digest-board",
        "title": "Team Digest Board",
        "tagline": "Local snapshot for standup review across selected car profiles.",
        "ownership_note": "Default sharing model is local snapshot; SVN and Confluence sharing remain explicit gates.",
        "status": "not_run",
        "raw_status": "not_run",
        "data_available": False,
        "summary": f"Team Digest Board for {profile_id} refreshes when opened.",
        "items": [],
        "payload": {
            "profile_id": profile_id,
            "status": "not_run",
            "data_available": False,
            "share_decision": {
                "rationale": "Open this page to load the local team digest snapshot.",
                "options": [],
            },
            "board_rows": [],
        },
        "confluence_anchors": [],
        "empty_state_note": "Open Team Digest Board to load the local standup snapshot.",
        "deferred": True,
    }


def _operator_handoff_page(profile_id: str, workspace: Path) -> dict[str, Any]:
    page = _reader_page(
        page_id="operator-handoff",
        title="Operator Handoff",
        tagline="Record the stopping point before a shift handoff.",
        reader=lambda: build_operator_handoff_snapshot(workspace=workspace, profile_id=profile_id),
        workspace=workspace,
        ownership_note="Handoff records stay operator-local and are not posted to Jira, SVN, or BMW Git.",
    )
    payload = page.get("payload", {}) if isinstance(page.get("payload"), dict) else {}
    page["confluence_anchors"] = [SG_DAILY_CONFLUENCE_ANCHOR, QUALITY_HERO_CONFLUENCE_ANCHOR]
    if not payload.get("latest_handoff"):
        page["empty_state_note"] = OPERATOR_HANDOFF_EMPTY_NOTE
    return page


def _manual_review_profile_token(profile_id: str) -> str:
    token = "".join(ch.lower() if ch.isalnum() else "_" for ch in profile_id.strip())
    token = "_".join(part for part in token.split("_") if part)
    return token or "profile"


def _manual_review_dashboard_session_id(profile_id: str) -> str:
    return f"dashboard-{_manual_review_profile_token(profile_id)}"


def _load_manual_review_dashboard_session(
    *,
    profile_id: str,
    workspace: Path | str,
) -> dict[str, Any] | None:
    session_id = _manual_review_dashboard_session_id(profile_id)
    try:
        return load_manual_review_session(session_id, workspace=workspace)
    except (FileNotFoundError, ValueError):
        return None


def _ensure_manual_review_dashboard_session(
    *,
    profile_id: str,
    workspace: Path | str,
    ticket_id: str | None = None,
    family_id: str = "",
) -> dict[str, Any]:
    session = _load_manual_review_dashboard_session(profile_id=profile_id, workspace=workspace)
    if session is not None:
        return session
    return create_manual_review_session_from_template(
        profile_id=profile_id,
        ticket_id=(ticket_id or _dashboard_active_ticket_id(workspace)),
        family_id=family_id,
        workspace=workspace,
        session_id=_manual_review_dashboard_session_id(profile_id),
    )


def _manual_review_step_recorded(step: dict[str, Any]) -> bool:
    return str(step.get("verdict", _MANUAL_REVIEW_PENDING_VERDICT)).strip() != _MANUAL_REVIEW_PENDING_VERDICT


def _manual_review_step_detail(step: dict[str, Any]) -> str:
    if not _manual_review_step_recorded(step):
        auto_status = str(step.get("auto_check_status", "")).strip()
        auto_summary = str(step.get("auto_check_summary", "")).strip()
        if auto_status and auto_status != "not_run" and auto_summary:
            return f"Auto-check {auto_status}. Manual review remains required. {auto_summary}".strip()
        evidence_status = str(step.get("evidence_status", step.get("suggestion_status", ""))).strip()
        reason = str(step.get("suggestion_reason", "")).strip()
        if evidence_status in {"available", "missing"}:
            label = "Evidence available" if evidence_status == "available" else "Evidence missing"
            return f"{label}. Manual review remains required. {reason}".strip()
        return str(step.get("evidence_prompt", ""))
    verdict = str(step.get("verdict", "")).strip()
    recorded_at = str(step.get("recorded_at_utc", "")).strip()
    note = str(step.get("note", "")).strip()
    pieces = [item for item in (verdict, recorded_at, note) if item]
    return " | ".join(pieces)


def _manual_review_page(
    profile_id: str,
    workspace: Path | str,
    *,
    active_ticket_id: str = "",
) -> dict[str, Any]:
    session = _load_manual_review_dashboard_session(profile_id=profile_id, workspace=workspace)
    steps = (
        list(session.get("steps", []))
        if isinstance(session, dict)
        else [step.to_session_step() for step in QUALITY_HERO_STEPS]
    )
    auto_check_payload = run_manual_review_auto_checks(profile_id, workspace=workspace)
    steps = apply_manual_review_suggestions(
        steps,
        profile_id=profile_id,
        workspace=workspace,
        auto_check_payload=auto_check_payload,
    )
    review_assist = build_manual_review_assist_from_auto_checks(auto_check_payload)
    recorded_count = sum(1 for step in steps if isinstance(step, dict) and _manual_review_step_recorded(step))
    status = "recorded" if recorded_count else _MANUAL_REVIEW_PENDING_VERDICT
    session_payload = session if isinstance(session, dict) else {}
    ticket_id = active_ticket_id.strip() or _dashboard_active_ticket_id(workspace)
    default_template = review_template_for_profile(profile_id, workspace=workspace)
    review_templates = list(list_car_review_templates())
    template_anchors = list(session_payload.get("confluence_anchors", default_template.get("confluence_anchors", [])))
    page = {
        "id": "manual-review",
        "title": "Manual Review Companion",
        "tagline": "Step through the 7 Quality-Hero review steps. Operator verdict per step.",
        "status": status,
        "data_available": True,
        "summary": f"{recorded_count}/{len(steps)} manual-review steps recorded locally.",
        "items": [
            {
                "label": str(step.get("title", "")),
                "status": "recorded" if _manual_review_step_recorded(step) else _MANUAL_REVIEW_PENDING_VERDICT,
                "detail": _manual_review_step_detail(step),
            }
            for step in steps
            if isinstance(step, dict)
        ],
        "payload": {
            "session_id": str(session_payload.get("session_id", _manual_review_dashboard_session_id(profile_id))),
            "ticket_id": str(session_payload.get("ticket_id", ticket_id)),
            "session_path": str(session_payload.get("session_path", "")),
            "markdown_path": str(session_payload.get("markdown_path", "")),
            "steps": steps,
            "review_templates": review_templates,
            "default_family_id": str(default_template.get("family_id", "")),
            "family_id": str(session_payload.get("family_id", default_template.get("family_id", ""))),
            "evidence_checklist": list(session_payload.get("evidence_checklist", default_template.get("evidence_checklist", []))),
            "confluence_anchors": template_anchors or [QUALITY_HERO_CONFLUENCE_ANCHOR],
            "review_assist": review_assist,
        },
        "confluence_anchors": template_anchors or [QUALITY_HERO_CONFLUENCE_ANCHOR],
    }
    if status == _MANUAL_REVIEW_PENDING_VERDICT:
        page["empty_state_note"] = MANUAL_REVIEW_EMPTY_NOTE
    return page


@lru_cache(maxsize=8)
def _dashboard_changed_profiles(workspace_text: str, bmw_root_text: str) -> dict[str, Any]:
    return detect_changed_profiles_since_last_run(
        workspace=Path(workspace_text),
        bmw_root=Path(bmw_root_text) if bmw_root_text else None,
    )


def build_dashboard_snapshot(
    profile_id: str,
    workspace: Path | str,
    *,
    bmw_root: Path | str | None = None,
    ui_mode: str | None = None,
    defer_daily_digest: bool = False,
    defer_team_digest_board: bool = False,
) -> dict[str, Any]:
    root = _workspace(workspace)
    profile_options = dashboard_profile_options(bmw_root=bmw_root, profile_scope=PROFILE_SCOPE_DEFAULT)
    profile_options_all = dashboard_profile_options(bmw_root=bmw_root, profile_scope="all")
    profile_registry_status = (
        "available"
        if any(option.get("registry_source") == PROFILE_REGISTRY_DYNAMIC_SOURCE for option in profile_options_all)
        else "unavailable"
    )
    resolved_profile_id = _resolve_dashboard_profile_id(
        profile_id,
        profile_options_all,
        workspace=root,
        fallback_options=profile_options,
    )
    profile_known = _dashboard_profile_known(resolved_profile_id, profile_options_all)
    profile_in_default_view = _dashboard_profile_known(resolved_profile_id, profile_options)
    theme = _clean_theme(ui_mode or load_dashboard_preference(root))
    setup_status = build_dependency_onboarding_status(workspace=root, bmw_root=bmw_root)
    active_ticket_id = _dashboard_active_ticket_id(root)
    daily_ticket_context = _daily_digest_ticket_context(root)
    output_root = operator_ui_root(root)
    daily_digest_page = (
        _deferred_daily_digest_page(resolved_profile_id, daily_ticket_context)
        if defer_daily_digest
        else _daily_digest_page(
            root,
            resolved_profile_id,
            active_ticket_id=active_ticket_id,
            ticket_context=daily_ticket_context,
        )
    )
    team_digest_page = (
        _deferred_team_digest_board_page(resolved_profile_id)
        if defer_team_digest_board
        else _team_digest_board_page(root, resolved_profile_id, bmw_root=bmw_root)
    )
    changed_profiles = _dashboard_changed_profiles(
        str(root),
        str(Path(bmw_root).resolve()) if bmw_root is not None else "",
    )
    return {
        "title": DASHBOARD_TITLE,
        "profile_id": resolved_profile_id,
        "profile_known": profile_known,
        "profile_warning": ""
        if profile_known
        else f"Profile {resolved_profile_id} is not in the current profile registry. Select a registered profile or check config.",
        "profile_options": profile_options,
        "profile_options_all": profile_options_all,
        "profile_show_all": bool(profile_known and not profile_in_default_view),
        "profile_registry": {
            "status": profile_registry_status,
            "source": PROFILE_REGISTRY_DYNAMIC_SOURCE if profile_registry_status == "available" else "fallback_static_23",
            "default_count": len(profile_options),
            "total_count": len(profile_options_all),
            "summary": (
                f"{len(profile_options)} active build profile(s) shown by default; "
                f"{len(profile_options_all)} registered profile(s) available."
                if profile_registry_status == "available"
                else "BMW registry source unavailable; using the static fallback profile list."
            ),
        },
        "workspace": str(root),
        "workspace_label": _path_label(root),
        "output_root": str(output_root),
        "output_root_label": _path_label(output_root),
        "theme": theme,
        "navigation": [{"id": page_id, "label": label} for page_id, label in DASHBOARD_NAVIGATION],
        "shortcuts": list(DASHBOARD_SHORTCUTS),
        "shortcut_actions": [{"key": key, "message": message} for key, message in DASHBOARD_SHORTCUT_ACTIONS],
        "guardrails": list(DASHBOARD_GUARDRAILS),
        "welcome": {
            "show": bool(setup_status.get("first_run")),
            "title": "Pick a profile",
            "summary": (
                "Local-only preflight for collecting delivery evidence. "
                "Choose the car profile first, then start Full QA Pass from the visible entry point."
            ),
            "setup_page_id": "delivery-checklist",
            "setup_action_count": len(
                [action for action in setup_status.get("actions", []) if isinstance(action, dict)]
            ),
            "setup_complete_note": SETUP_COMPLETE_NOTE,
            "guardrails": list(DASHBOARD_GUARDRAILS),
        },
        "changed_profiles": changed_profiles,
        "pages": [
            _full_qa_pass_page(resolved_profile_id, root, bmw_root=bmw_root),
            _batch_full_qa_pass_page(resolved_profile_id, root),
            _delivery_checklist_page(resolved_profile_id, root, bmw_root=bmw_root, setup_status=setup_status),
            _onboarding_guide_page(
                resolved_profile_id,
                root,
                bmw_root=bmw_root,
                setup_status=setup_status,
            ),
            _screenshot_test_state_page(resolved_profile_id, root, bmw_root=bmw_root),
            _risk_score_page(resolved_profile_id, root, bmw_root=bmw_root),
            _cross_car_comparison_page(root, bmw_root=bmw_root),
            daily_digest_page,
            team_digest_page,
            _operator_handoff_page(resolved_profile_id, root),
            _manual_review_page(resolved_profile_id, root, active_ticket_id=active_ticket_id),
        ],
    }


def _manual_review_state_path(workspace: Path | str, profile_id: str) -> Path:
    safe_profile = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in profile_id.strip()) or "profile"
    return _operator_state_path(workspace, f"manual_review_{safe_profile}.json")


def save_manual_review_state(
    *,
    profile_id: str,
    workspace: Path | str,
    step_slug: str,
    status: str,
    note: str = "",
) -> dict[str, Any]:
    clean_status = status.strip().casefold()
    if clean_status in _BLOCKED_MANUAL_STATUSES or clean_status not in MANUAL_REVIEW_STATUSES:
        raise ValueError(f"Unsupported manual-review dashboard status: {status}")
    known_slugs = {step.slug for step in QUALITY_HERO_STEPS}
    if step_slug not in known_slugs:
        raise KeyError(f"Unknown manual-review step: {step_slug}")
    path = _manual_review_state_path(workspace, profile_id)
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            payload = {}
    else:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("profile_id", profile_id.strip())
    payload["updated_at_utc"] = _utc_now()
    payload["source"] = "NiceGUI dashboard manual-review companion"
    payload["recorded_by_tool"] = False
    steps = payload.setdefault("steps", {})
    if not isinstance(steps, dict):
        steps = {}
        payload["steps"] = steps
    steps[step_slug] = {
        "status": clean_status,
        "note": note.strip(),
        "recorded_at_utc": _utc_now(),
        "recorded_by_tool": False,
    }
    ensure_parent(path)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def record_manual_review_dashboard_step(
    *,
    profile_id: str,
    workspace: Path | str,
    step_slug: str,
    verdict: str,
    note: str = "",
    suggested_verdict: str = "",
) -> dict[str, Any]:
    if verdict.strip().casefold() not in MANUAL_REVIEW_RECORD_VERDICTS:
        raise ValueError(f"Unsupported manual-review dashboard verdict: {verdict}")
    session = _ensure_manual_review_dashboard_session(profile_id=profile_id.strip(), workspace=workspace)
    return record_manual_review_step(
        session["session_path"],
        step_slug,
        verdict,
        workspace=workspace,
        note=note,
        suggested_verdict=suggested_verdict,
    )


_BUILD_PACKAGE_TIMEOUT_SECONDS = 600
_BUILD_PACKAGE_STDOUT_TAIL_LINES = 20
_BUILD_PACKAGE_STDOUT_TAIL_BYTES = 2000
_BUILD_PACKAGE_FILE_ACTIVITY_LIMIT = 20
_BUILD_PACKAGE_TYPICAL_RANGE_LABEL = "typical 1-5 min"
_QUALITY_HERO_REPORT_TIMEOUT_SECONDS = 600
_BATCH_FULL_QA_TIMEOUT_SECONDS = 600
_BATCH_FULL_QA_TYPICAL_RANGE_LABEL = "Typical 1-3 min per profile"


@dataclass
class ReviewPackageBuildJob:
    ticket_id: str
    profile_id: str
    workspace: Path
    process: subprocess.Popen[bytes]
    command: list[str]
    stdout_path: Path
    stderr_path: Path
    started_monotonic: float
    started_wall_time: float
    timeout_seconds: int
    completed: bool = False
    result_payload: dict[str, Any] | None = None


@dataclass
class BatchFullQaPassJob:
    profile_ids: list[str]
    workspace: Path
    bmw_root: str
    log_root: Path
    timeout_seconds: int
    trusted_tool_mode: bool
    current_index: int = 0
    process: subprocess.Popen[bytes] | None = None
    command: list[str] = field(default_factory=list)
    stdout_path: Path | None = None
    stderr_path: Path | None = None
    current_started_monotonic: float = 0.0
    current_started_wall_time: float = 0.0
    batch_started_monotonic: float = 0.0
    batch_started_wall_time: float = 0.0
    results: list[dict[str, Any]] = field(default_factory=list)
    cancel_after_current: bool = False
    completed: bool = False
    result_payload: dict[str, Any] | None = None


def _validate_review_package_inputs(workspace: Path | str, profile_id: str, ticket_id: str) -> tuple[Path, str, str]:
    clean_ticket = ticket_id.strip()
    if not clean_ticket:
        raise ValueError("Ticket ID required to build a review package.")
    clean_profile = profile_id.strip()
    if not clean_profile:
        raise ValueError("Profile ID required to build a review package.")
    return Path(workspace).resolve(), clean_profile, clean_ticket


def _dashboard_review_package_command(*, workspace: Path, profile_id: str, ticket_id: str) -> list[str]:
    return sgfx_cli_command(
        "ticket-review",
        ticket_id,
        "--workspace",
        str(workspace),
        "--profile",
        profile_id,
        "--json",
    )


def _build_tail_text(path: Path, limit: int = _BUILD_PACKAGE_STDOUT_TAIL_BYTES) -> str:
    if not path.is_file():
        return ""
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    return data[-limit:].decode("utf-8", errors="replace")


def _build_tail_lines(path: Path, limit: int = _BUILD_PACKAGE_STDOUT_TAIL_LINES) -> list[str]:
    text = _build_tail_text(path)
    if not text:
        return []
    return text.splitlines()[-limit:]


def _build_combined_tail_lines(stdout_path: Path, stderr_path: Path) -> list[str]:
    lines = list(_build_tail_lines(stdout_path))
    lines.extend(f"stderr: {line}" for line in _build_tail_lines(stderr_path))
    return lines[-_BUILD_PACKAGE_STDOUT_TAIL_LINES:]


def _size_label(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    kib = size_bytes / 1024
    if kib < 1024:
        return f"{kib:.0f} KB"
    mib = kib / 1024
    return f"{mib:.1f} MB"


def _build_package_file_activity(
    workspace: Path,
    started_wall_time: float,
    limit: int = _BUILD_PACKAGE_FILE_ACTIVITY_LIMIT,
) -> list[dict[str, Any]]:
    roots = [workspace / "out", workspace / "operator_state" / "review_package_build"]
    entries: list[tuple[float, dict[str, Any]]] = []
    threshold = started_wall_time - 1.0
    seen: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        candidates = [root]
        if root.is_dir():
            try:
                candidates.extend(path for path in root.rglob("*") if path.is_file())
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
                relative = str(path.relative_to(workspace))
            except ValueError:
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


def _elapsed_label(elapsed_seconds: float) -> str:
    elapsed = max(0, int(elapsed_seconds))
    minutes, seconds = divmod(elapsed, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _dashboard_full_qa_pass_command(
    *,
    workspace: Path,
    profile_id: str,
    bmw_root: str = "",
    trusted_tool_mode: bool = True,
) -> list[str]:
    command = sgfx_cli_command(
        "full-qa-pass",
        "run",
        "--profile",
        profile_id,
        "--workspace",
        str(workspace),
        "--format",
        "json",
    )
    if bmw_root:
        command.extend(["--bmw-root", bmw_root])
    command.append("--automatic-mode" if trusted_tool_mode else "--manual-mode")
    return command


def _batch_profile_safe_name(profile_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", profile_id.strip().upper() or "PROFILE")


def _read_json_payload(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return {}
    if not text:
        return {}
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _batch_step_payload(payload: dict[str, Any], step_id: str) -> dict[str, Any]:
    for step in payload.get("steps", []):
        if isinstance(step, dict) and str(step.get("id", "")) == step_id:
            step_payload = step.get("payload", {})
            return step_payload if isinstance(step_payload, dict) else {}
    return {}


def _batch_profile_result(
    job: BatchFullQaPassJob,
    *,
    profile_id: str,
    exit_code: int,
    timed_out: bool = False,
) -> dict[str, Any]:
    elapsed_seconds = time.monotonic() - job.current_started_monotonic
    payload = _read_json_payload(job.stdout_path)
    status = str(payload.get("status", "failed" if exit_code else "unknown"))
    if exit_code != 0:
        outcome = "failed"
    elif timed_out:
        outcome = "failed"
    else:
        outcome = status if status in {"passed", "incomplete", "failed"} else "recorded"
    risk_payload = _batch_step_payload(payload, "risk-score")
    risk_score = risk_payload.get("risk_score", risk_payload.get("score", "unknown"))
    pending_review_count = len(
        [
            step
            for step in payload.get("steps", [])
            if isinstance(step, dict) and str(step.get("status", "")) not in {"passed", "skipped"}
        ]
    )
    progress = payload.get("progress", {}) if isinstance(payload.get("progress"), dict) else {}
    summary = str(payload.get("summary", "") or f"Full QA Pass exited {exit_code} for {profile_id}.")
    result = {
        "profile_id": profile_id,
        "outcome": outcome,
        "status": status,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "risk_score": str(risk_score),
        "pending_review_count": pending_review_count,
        "completed_steps": int(progress.get("completed_steps", 0) or 0),
        "total_steps": int(progress.get("total_steps", 0) or 0),
        "elapsed_seconds": int(max(0, elapsed_seconds)),
        "elapsed_label": _elapsed_label(elapsed_seconds),
        "summary": summary,
        "stdout_path": str(job.stdout_path or ""),
        "stderr_path": str(job.stderr_path or ""),
        "stdout_tail_lines": _build_combined_tail_lines(job.stdout_path or Path(), job.stderr_path or Path()),
        "profile_link": f"?profile={quote(profile_id)}&full_qa_run=1",
        "manual_review_required": True,
        "is_approval": False,
    }
    append_activity_entry(
        job.workspace,
        verb="ran",
        surface="batch-full-qa-pass",
        profile=profile_id,
        outcome="ok" if exit_code == 0 and not timed_out else "error",
        note=f"Batch Full QA Pass subprocess completed for {profile_id} with exit {exit_code}.",
    )
    return result


def _batch_progress_payload(job: BatchFullQaPassJob, *, summary: str = "") -> dict[str, Any]:
    total = len(job.profile_ids)
    current_profile = job.profile_ids[job.current_index] if job.current_index < total else ""
    elapsed = time.monotonic() - (job.current_started_monotonic or job.batch_started_monotonic)
    completed = len(job.results)
    return {
        "status": "running",
        "completed": False,
        "profiles": list(job.profile_ids),
        "current_profile": current_profile,
        "current_index": min(job.current_index + 1, total),
        "total_profiles": total,
        "completed_profiles": completed,
        "percent": int(round((completed / max(1, total)) * 100)),
        "elapsed_seconds": int(max(0, elapsed)),
        "elapsed_label": _elapsed_label(elapsed),
        "typical_range": _BATCH_FULL_QA_TYPICAL_RANGE_LABEL,
        "cancel_after_current": bool(job.cancel_after_current),
        "summary": summary or f"Running profile {min(job.current_index + 1, total)} of {total}: {current_profile}.",
        "results": list(job.results),
        "stdout_tail_lines": _build_combined_tail_lines(job.stdout_path or Path(), job.stderr_path or Path()),
        "stdout_path": str(job.stdout_path or ""),
        "stderr_path": str(job.stderr_path or ""),
        "manual_review_required": True,
        "is_approval": False,
    }


def _complete_batch_full_qa_pass(job: BatchFullQaPassJob, *, canceled: bool = False) -> dict[str, Any]:
    failed_count = len([item for item in job.results if str(item.get("exit_code", "")) != "0"])
    incomplete_count = len([item for item in job.results if str(item.get("outcome", "")) == "incomplete"])
    if canceled:
        status = "incomplete"
        summary = f"Batch stopped after {len(job.results)}/{len(job.profile_ids)} profile(s)."
    elif failed_count:
        status = "failed"
        summary = f"Batch completed with {failed_count} failed profile subprocess(es)."
    elif incomplete_count:
        status = "incomplete"
        summary = f"Batch completed; {incomplete_count} profile(s) still need operator review."
    else:
        status = "passed"
        summary = f"Batch completed for {len(job.results)} profile(s)."
    payload = {
        "status": status,
        "completed": True,
        "profiles": list(job.profile_ids),
        "current_profile": "",
        "current_index": len(job.profile_ids),
        "total_profiles": len(job.profile_ids),
        "completed_profiles": len(job.results),
        "percent": 100 if job.profile_ids else 0,
        "typical_range": _BATCH_FULL_QA_TYPICAL_RANGE_LABEL,
        "summary": summary,
        "results": list(job.results),
        "canceled": canceled,
        "manual_review_required": True,
        "is_approval": False,
    }
    job.completed = True
    job.result_payload = payload
    return payload


def _start_batch_profile_process(job: BatchFullQaPassJob) -> None:
    profile_id = job.profile_ids[job.current_index]
    profile_token = _batch_profile_safe_name(profile_id)
    stdout_path = job.log_root / f"{job.current_index + 1:02d}-{profile_token}.stdout.log"
    stderr_path = job.log_root / f"{job.current_index + 1:02d}-{profile_token}.stderr.log"
    ensure_parent(stdout_path)
    command = _dashboard_full_qa_pass_command(
        workspace=job.workspace,
        profile_id=profile_id,
        bmw_root=job.bmw_root,
        trusted_tool_mode=job.trusted_tool_mode,
    )
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault("PYTHONIOENCODING", "utf-8")
    if not getattr(sys, "frozen", False):
        repo_root = Path(__file__).resolve().parents[2]
        existing_pythonpath = str(env.get("PYTHONPATH", "") or "")
        env["PYTHONPATH"] = (
            f"{repo_root}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else str(repo_root)
        )
    job.command = command
    job.stdout_path = stdout_path
    job.stderr_path = stderr_path
    job.current_started_monotonic = time.monotonic()
    job.current_started_wall_time = time.time()
    with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
        job.process = subprocess.Popen(
            command,
            cwd=job.workspace,
            stdin=subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=stderr_handle,
            env=env,
            **hidden_subprocess_kwargs(),
        )


def start_dashboard_batch_full_qa_pass(
    *,
    workspace: Path | str,
    profile_ids: list[str],
    bmw_root: Path | str | None = None,
    trusted_tool_mode: bool = True,
    timeout_seconds: int = _BATCH_FULL_QA_TIMEOUT_SECONDS,
) -> BatchFullQaPassJob:
    workspace_path = Path(workspace).resolve()
    clean_profiles: list[str] = []
    for profile in profile_ids:
        clean = str(profile or "").strip().upper()
        if clean and clean not in clean_profiles:
            clean_profiles.append(clean)
    if not clean_profiles:
        raise ValueError("Select at least one profile before starting the batch.")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_root = workspace_path / "operator_state" / "batch_full_qa_pass" / stamp
    job = BatchFullQaPassJob(
        profile_ids=clean_profiles,
        workspace=workspace_path,
        bmw_root=str(Path(bmw_root).resolve()) if bmw_root else "",
        log_root=log_root,
        timeout_seconds=timeout_seconds,
        trusted_tool_mode=trusted_tool_mode,
        batch_started_monotonic=time.monotonic(),
        batch_started_wall_time=time.time(),
    )
    _start_batch_profile_process(job)
    append_activity_entry(
        workspace_path,
        verb="ran",
        surface="batch-full-qa-pass",
        profile=",".join(clean_profiles),
        outcome="ok",
        note=f"Batch Full QA Pass started for {len(clean_profiles)} profile(s).",
    )
    return job


def request_cancel_dashboard_batch_full_qa_pass(job: BatchFullQaPassJob) -> dict[str, Any]:
    job.cancel_after_current = True
    return _batch_progress_payload(job, summary="Cancel requested; current profile will finish first.")


def poll_dashboard_batch_full_qa_pass(job: BatchFullQaPassJob) -> dict[str, Any] | None:
    if job.completed:
        return job.result_payload or _complete_batch_full_qa_pass(job)
    if job.process is None:
        if job.current_index >= len(job.profile_ids):
            return _complete_batch_full_qa_pass(job)
        _start_batch_profile_process(job)
        return _batch_progress_payload(job)
    exit_code = job.process.poll()
    elapsed = time.monotonic() - job.current_started_monotonic
    if exit_code is None and elapsed < job.timeout_seconds:
        return _batch_progress_payload(job)
    timed_out = False
    if exit_code is None:
        timed_out = True
        job.process.terminate()
        try:
            job.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            job.process.kill()
            job.process.wait(timeout=5)
        exit_code = job.process.returncode if job.process.returncode is not None else -1
    current_profile = job.profile_ids[job.current_index]
    job.results.append(_batch_profile_result(job, profile_id=current_profile, exit_code=exit_code, timed_out=timed_out))
    job.current_index += 1
    job.process = None
    if job.cancel_after_current or job.current_index >= len(job.profile_ids):
        return _complete_batch_full_qa_pass(job, canceled=job.cancel_after_current and job.current_index < len(job.profile_ids))
    _start_batch_profile_process(job)
    return _batch_progress_payload(
        job,
        summary=f"Started next profile {job.current_index + 1} of {len(job.profile_ids)}: {job.profile_ids[job.current_index]}.",
    )


def _review_build_progress_payload(job: ReviewPackageBuildJob, *, elapsed_seconds: float) -> dict[str, Any]:
    return {
        "ticket_id": job.ticket_id,
        "profile_id": job.profile_id,
        "workspace": str(job.workspace),
        "status": "running",
        "outcome": "running",
        "completed": False,
        "exit_code": None,
        "command": list(job.command),
        "timeout_seconds": job.timeout_seconds,
        "elapsed_seconds": int(max(0, elapsed_seconds)),
        "elapsed_label": _elapsed_label(elapsed_seconds),
        "typical_range": _BUILD_PACKAGE_TYPICAL_RANGE_LABEL,
        "timed_out": False,
        "canceled": False,
        "summary": "Build review package running.",
        "stdout_tail": _build_tail_text(job.stdout_path),
        "stdout_tail_lines": _build_combined_tail_lines(job.stdout_path, job.stderr_path),
        "stderr_tail": _build_tail_text(job.stderr_path),
        "stdout_path": str(job.stdout_path),
        "stderr_path": str(job.stderr_path),
        "file_activity": _build_package_file_activity(job.workspace, job.started_wall_time),
        "recorded_by_tool": True,
        "is_approval": False,
    }


def _complete_review_package_build(
    job: ReviewPackageBuildJob,
    *,
    exit_code: int,
    timed_out: bool = False,
    canceled: bool = False,
) -> dict[str, Any]:
    elapsed_seconds = time.monotonic() - job.started_monotonic
    outcome = "recorded" if exit_code == 0 and not timed_out and not canceled else "failed"
    if exit_code == 0 and not timed_out and not canceled:
        _write_active_ticket_state(job.workspace, job.ticket_id, source="build-review-package")
    append_activity_entry(
        job.workspace,
        verb="ran",
        surface="daily-digest",
        profile=job.profile_id,
        outcome="ok" if outcome == "recorded" else "error",
        note=f"Build review package for {job.ticket_id}",
    )
    if timed_out:
        summary = f"Build review package timed out after {job.timeout_seconds} seconds."
    elif canceled:
        summary = "Build review package canceled by operator."
    elif exit_code == 0:
        summary = "Build review package completed. Refresh to reload digest evidence."
    else:
        summary = f"Build review package failed with exit code {exit_code}."
    payload = {
        "ticket_id": job.ticket_id,
        "profile_id": job.profile_id,
        "workspace": str(job.workspace),
        "status": outcome,
        "outcome": outcome,
        "completed": True,
        "exit_code": exit_code,
        "command": list(job.command),
        "timeout_seconds": job.timeout_seconds,
        "elapsed_seconds": int(max(0, elapsed_seconds)),
        "elapsed_label": _elapsed_label(elapsed_seconds),
        "typical_range": _BUILD_PACKAGE_TYPICAL_RANGE_LABEL,
        "timed_out": timed_out,
        "canceled": canceled,
        "summary": summary,
        "stdout_tail": _build_tail_text(job.stdout_path),
        "stdout_tail_lines": _build_combined_tail_lines(job.stdout_path, job.stderr_path),
        "stderr_tail": _build_tail_text(job.stderr_path),
        "stdout_path": str(job.stdout_path),
        "stderr_path": str(job.stderr_path),
        "file_activity": _build_package_file_activity(job.workspace, job.started_wall_time),
        "recorded_by_tool": True,
        "is_approval": False,
    }
    job.completed = True
    job.result_payload = payload
    return payload


def start_dashboard_review_package_build(
    *,
    workspace: Path | str,
    profile_id: str,
    ticket_id: str,
    operator_confirmed: bool,
    timeout_seconds: int = _BUILD_PACKAGE_TIMEOUT_SECONDS,
) -> ReviewPackageBuildJob:
    if not operator_confirmed:
        raise ValueError("Operator confirmation is required before building a review package.")
    workspace_path, clean_profile, clean_ticket = _validate_review_package_inputs(workspace, profile_id, ticket_id)
    command = _dashboard_review_package_command(
        workspace=workspace_path,
        profile_id=clean_profile,
        ticket_id=clean_ticket,
    )
    log_root = workspace_path / "operator_state" / "review_package_build"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stdout_path = log_root / f"{clean_ticket}-{clean_profile}-{stamp}.stdout.log"
    stderr_path = log_root / f"{clean_ticket}-{clean_profile}-{stamp}.stderr.log"
    ensure_parent(stdout_path)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault("PYTHONIOENCODING", "utf-8")
    started_wall_time = time.time()
    started_monotonic = time.monotonic()
    with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
        process = subprocess.Popen(
            command,
            cwd=workspace_path,
            stdin=subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=stderr_handle,
            env=env,
            **hidden_subprocess_kwargs(),
        )
    return ReviewPackageBuildJob(
        ticket_id=clean_ticket,
        profile_id=clean_profile,
        workspace=workspace_path,
        process=process,
        command=command,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        started_monotonic=started_monotonic,
        started_wall_time=started_wall_time,
        timeout_seconds=timeout_seconds,
    )


def poll_dashboard_review_package_build(job: ReviewPackageBuildJob) -> dict[str, Any] | None:
    if job.completed:
        return job.result_payload or _complete_review_package_build(
            job,
            exit_code=job.process.returncode or 0,
        )
    exit_code = job.process.poll()
    elapsed = time.monotonic() - job.started_monotonic
    if exit_code is None and elapsed < job.timeout_seconds:
        return _review_build_progress_payload(job, elapsed_seconds=elapsed)
    if exit_code is None:
        job.process.terminate()
        try:
            job.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            job.process.kill()
            job.process.wait(timeout=5)
        return _complete_review_package_build(
            job,
            exit_code=job.process.returncode if job.process.returncode is not None else -1,
            timed_out=True,
        )
    return _complete_review_package_build(job, exit_code=exit_code)


def cancel_dashboard_review_package_build(job: ReviewPackageBuildJob) -> dict[str, Any]:
    if job.process.poll() is None:
        job.process.terminate()
        try:
            job.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            job.process.kill()
            job.process.wait(timeout=5)
    return _complete_review_package_build(
        job,
        exit_code=job.process.returncode if job.process.returncode is not None else -1,
        canceled=True,
    )


def build_dashboard_review_package(
    *,
    workspace: Path | str,
    profile_id: str,
    ticket_id: str,
    timeout_seconds: int = _BUILD_PACKAGE_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    clean_ticket = ticket_id.strip()
    if not clean_ticket:
        raise ValueError("Ticket ID required to build a review package.")
    clean_profile = profile_id.strip()
    if not clean_profile:
        raise ValueError("Profile ID required to build a review package.")
    workspace_path = Path(workspace).resolve()
    command = _dashboard_review_package_command(
        workspace=workspace_path,
        profile_id=clean_profile,
        ticket_id=clean_ticket,
    )
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
        **hidden_subprocess_kwargs(),
    )
    outcome = "recorded" if completed.returncode == 0 else "failed"
    if completed.returncode == 0:
        _write_active_ticket_state(workspace_path, clean_ticket, source="build-review-package")
    append_activity_entry(
        workspace_path,
        verb="ran",
        surface="daily-digest",
        profile=clean_profile,
        outcome="ok" if completed.returncode == 0 else "error",
        note=f"Build review package for {clean_ticket}",
    )
    return {
        "ticket_id": clean_ticket,
        "profile_id": clean_profile,
        "workspace": str(workspace_path),
        "exit_code": completed.returncode,
        "outcome": outcome,
        "stdout_tail": completed.stdout[-2000:] if completed.stdout else "",
        "stderr_tail": completed.stderr[-2000:] if completed.stderr else "",
        "recorded_by_tool": True,
    }


def _quality_hero_report_output_root(workspace: Path, profile_id: str) -> Path:
    safe_profile = re.sub(r"[^A-Za-z0-9_.-]+", "_", profile_id.strip().lower() or "profile")
    return operator_ui_root(workspace) / "quality-hero-report" / safe_profile


def _dashboard_quality_hero_report_command(
    *,
    workspace: Path,
    profile_id: str,
    ticket_id: str,
    output_root: Path,
    attach_ticket: str = "",
) -> list[str]:
    command = sgfx_cli_command(
        "quality-hero-report",
        "generate",
        "--profile",
        profile_id,
        "--workspace",
        str(workspace),
        "--output-root",
        str(output_root),
        "--format",
        "json",
    )
    if ticket_id:
        command.extend(["--ticket", ticket_id])
    if attach_ticket:
        command.extend(["--attach-ticket", attach_ticket, "--auto-confirm"])
    return command


def _dashboard_jira_attachment_endpoint(ticket_id: str) -> str:
    ticket = ticket_id.strip().upper()
    try:
        base_url = str(load_jira_credentials().get("jira_url", "") or DEFAULT_JIRA_URL)
    except Exception:  # noqa: BLE001
        base_url = DEFAULT_JIRA_URL
    return f"{base_url.rstrip('/')}/rest/api/2/issue/{ticket}/attachments"


def _attachment_response_url(attachment: dict[str, Any]) -> str:
    response = attachment.get("response")
    if isinstance(response, list) and response:
        first = response[0]
        if isinstance(first, dict):
            return str(first.get("self", "") or "")
    if isinstance(response, dict):
        return str(response.get("self", "") or "")
    return ""


def _attachment_response_id(attachment: dict[str, Any]) -> str:
    response = attachment.get("response")
    if isinstance(response, list) and response:
        first = response[0]
        if isinstance(first, dict):
            return str(first.get("id", "") or first.get("key", "") or "")
    if isinstance(response, dict):
        return str(response.get("id", "") or response.get("key", "") or "")
    return ""


def build_dashboard_quality_hero_report(
    *,
    workspace: Path | str,
    profile_id: str,
    ticket_id: str = "",
    output_root: Path | str | None = None,
    attach_ticket: str = "",
    operator_confirmed: bool = False,
    timeout_seconds: int = _QUALITY_HERO_REPORT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    clean_profile = profile_id.strip()
    if not clean_profile:
        raise ValueError("Profile ID required to build a Quality-Hero report.")
    clean_ticket = ticket_id.strip().upper()
    clean_attach_ticket = attach_ticket.strip().upper()
    if clean_attach_ticket and not operator_confirmed:
        raise ValueError("Operator confirmation is required before attaching a Quality-Hero report to Jira.")
    workspace_path = Path(workspace).resolve()
    output_path = Path(output_root).resolve() if output_root else _quality_hero_report_output_root(workspace_path, clean_profile)
    command = _dashboard_quality_hero_report_command(
        workspace=workspace_path,
        profile_id=clean_profile,
        ticket_id=clean_ticket,
        output_root=output_path,
        attach_ticket=clean_attach_ticket,
    )
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
        **hidden_subprocess_kwargs(),
    )
    payload: dict[str, Any] = {}
    if completed.stdout.strip():
        try:
            loaded = json.loads(completed.stdout)
            payload = loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            payload = {}
    outcome = "recorded" if completed.returncode == 0 else "failed"
    ticket_for_state = clean_attach_ticket or clean_ticket
    if completed.returncode == 0 and ticket_for_state:
        _write_active_ticket_state(workspace_path, ticket_for_state, source="quality-hero-report")
    append_activity_entry(
        workspace_path,
        verb="ran",
        surface="daily-digest",
        profile=clean_profile,
        outcome="ok" if completed.returncode == 0 else "error",
        note=(
            f"Attach Quality-Hero report to {clean_attach_ticket}"
            if clean_attach_ticket
            else f"Build Quality-Hero report for {clean_ticket or 'no ticket'}"
        ),
    )
    markdown_path = str(payload.get("markdown_path", "") or "")
    html_path = str(payload.get("html_path", "") or "")
    json_path = str(payload.get("json_path", "") or "")
    attachment = payload.get("jira_attachment", {}) if isinstance(payload.get("jira_attachment"), dict) else {}
    return {
        "ticket_id": clean_ticket,
        "attach_ticket": clean_attach_ticket,
        "profile_id": clean_profile,
        "workspace": str(workspace_path),
        "output_root": str(output_path),
        "exit_code": completed.returncode,
        "outcome": outcome,
        "status": outcome,
        "command": command,
        "markdown_path": markdown_path,
        "html_path": html_path,
        "json_path": json_path,
        "markdown_size_bytes": Path(markdown_path).stat().st_size if markdown_path and Path(markdown_path).is_file() else 0,
        "html_size_bytes": Path(html_path).stat().st_size if html_path and Path(html_path).is_file() else 0,
        "json_size_bytes": Path(json_path).stat().st_size if json_path and Path(json_path).is_file() else 0,
        "jira_attachment": attachment,
        "attachment_id": _attachment_response_id(attachment),
        "jira_url": _attachment_response_url(attachment),
        "stdout_tail": completed.stdout[-2000:] if completed.stdout else "",
        "stderr_tail": completed.stderr[-2000:] if completed.stderr else "",
        "recorded_by_tool": True,
        "is_approval": False,
    }


def _render_status_chip(ui: Any, status: str) -> None:
    ui.badge(status or "unknown").classes("sgfx-status")


def _page_confluence_anchors(page: dict[str, Any]) -> list[str]:
    anchors = page.get("confluence_anchors", [])
    if isinstance(anchors, str):
        anchors = [anchors]
    if not isinstance(anchors, list):
        return []
    return [str(anchor).strip() for anchor in anchors if str(anchor).strip()]


def _confluence_dump_root() -> Path:
    return Path(os.environ.get("SGFX_CONFLUENCE_DUMP_ROOT", Path.home() / "Downloads" / "confluence-readable-dumps"))


def _confluence_anchor_relative_path(anchor: str) -> str:
    clean = anchor.strip()
    if ".txt" in clean:
        clean = clean[: clean.index(".txt") + 4]
    elif ":" in clean:
        clean = clean.split(":", 1)[0]
    clean = clean.strip().replace("\\", "/").lstrip("/")
    prefix = "PDX_" + "SER" + "GFX/"
    if clean and not clean.startswith((prefix, "BMW_3DCar/")):
        clean = prefix + clean
    return clean


def _confluence_anchor_path(anchor: str) -> Path | None:
    relative = _confluence_anchor_relative_path(anchor)
    if not relative:
        return None
    path = (_confluence_dump_root() / relative).resolve()
    return path if path.is_file() else None


def _confluence_anchor_url(anchor: str) -> str:
    path = _confluence_anchor_path(anchor)
    if path is None:
        return ""
    try:
        relative = path.relative_to(_confluence_dump_root().resolve())
    except ValueError:
        return ""
    return "/sgfx-confluence/" + quote(str(relative).replace("\\", "/"), safe="/")


def _render_confluence_anchor(ui: Any, anchor: str) -> None:
    with ui.row().classes("sgfx-doc-link-row"):
        ui.label(f"Confluence anchor: {anchor}").classes("sgfx-muted")
        url = _confluence_anchor_url(anchor)
        if url:
            ui.link("View doc", url, new_tab=True).classes("sgfx-doc-link")
        else:
            ui.label("View doc unavailable").classes("sgfx-muted")


def _image_mime(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".bmp":
        return "image/bmp"
    return "image/png"


def _dashboard_data_uri(path_value: str, *, max_bytes: int = 3_000_000) -> str:
    path = Path(str(path_value or ""))
    if path.suffix.casefold() not in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
        return ""
    if not path.is_file():
        return ""
    try:
        if path.stat().st_size > max_bytes:
            return ""
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return ""
    return f"data:{_image_mime(path)};base64,{encoded}"


def _pipeline_traceback(result: dict[str, Any]) -> dict[str, str]:
    payload = result.get("pipeline_traceback", {})
    if not isinstance(payload, dict) or not bool(payload.get("detected", False)):
        return {}
    summary = str(payload.get("summary", "")).strip()
    details = str(payload.get("technical_details", "")).strip()
    if not summary and not details:
        return {}
    return {"summary": summary, "technical_details": details}


def _screenshot_review_visual_rows(result: dict[str, Any], *, limit: int = 4) -> list[dict[str, str]]:
    rows = result.get("screenshot_review_rows", [])
    if not isinstance(rows, list):
        return []
    profile_id = str(result.get("profile_id", "")).strip()
    visual_rows: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        expected_src = _dashboard_data_uri(str(row.get("expected_path", "")))
        actual_src = _dashboard_data_uri(str(row.get("actual_path", "")))
        diff_path = str(row.get("diff_path", "")).strip()
        diff_src = _dashboard_data_uri(diff_path)
        delta_badge = compute_diff_delta_badge(diff_path)
        regression_badge = compute_diff_regression_badge(
            profile_id,
            diff_path,
            key=str(row.get("key", "") or row.get("label", "")).strip(),
        )
        if not any((expected_src, actual_src, diff_src)):
            continue
        visual_rows.append(
            {
                "key": str(row.get("key", "") or row.get("label", "")).strip(),
                "label": str(row.get("label", "") or row.get("key", "")).strip(),
                "expected_src": expected_src,
                "actual_src": actual_src,
                "diff_src": diff_src,
                "expected_path": str(row.get("expected_path", "")).strip(),
                "actual_path": str(row.get("actual_path", "")).strip(),
                "diff_path": diff_path,
                "diff_delta_label": delta_badge.label,
                "diff_delta_level": delta_badge.level,
                "diff_regression_label": regression_badge.label,
                "diff_regression_level": regression_badge.level,
            }
        )
        if len(visual_rows) >= limit:
            break
    return visual_rows


def _file_activity_visual_items(result: dict[str, Any], *, limit: int = 4) -> list[dict[str, str]]:
    activity = result.get("file_activity", [])
    if not isinstance(activity, list):
        return []
    items: list[dict[str, str]] = []
    for entry in activity:
        if not isinstance(entry, dict):
            continue
        path = str(entry.get("path", "")).strip()
        data_uri = _dashboard_data_uri(path)
        if not data_uri:
            continue
        relative = str(entry.get("relative_path", Path(path).name)).strip()
        items.append(
            {
                "label": relative or Path(path).name,
                "detail": str(entry.get("summary", "") or entry.get("size_label", "")),
                "src": data_uri,
            }
        )
        if len(items) >= limit:
            break
    return items


def _render_action_visuals(
    ui: Any,
    result: dict[str, Any],
    *,
    visual_label: Any,
    visual_host: Any,
    open_screenshot_viewer: Callable[[str, str], None] | None = None,
) -> None:
    visual_host.clear()
    review_rows = _screenshot_review_visual_rows(result)
    image_items = _file_activity_visual_items(result)
    workbook_preview = result.get("workbook_preview", {})
    if not isinstance(workbook_preview, dict):
        workbook_preview = {}
    has_workbook_preview = bool(workbook_preview.get("workbook_path"))
    if not review_rows and not image_items and not has_workbook_preview:
        visual_label.visible = False
        visual_host.visible = False
        return
    visual_label.visible = True
    visual_host.visible = True
    with visual_host:
        if has_workbook_preview:
            with ui.column().classes("sgfx-workbook-preview"):
                ui.label("Workbook preview").classes("sgfx-panel-tagline")
                ui.label(Path(str(workbook_preview.get("workbook_path", ""))).name).classes("sgfx-summary")
                variant_count = str(workbook_preview.get("variant_count", "") or "").strip()
                if variant_count:
                    ui.label(f"{variant_count} variant(s) detected").classes("sgfx-status-pill")
                totals = workbook_preview.get("variant_totals", [])
                if isinstance(totals, list) and totals:
                    for item in totals[:6]:
                        ui.label(str(item)).classes("sgfx-muted")
                summary = str(workbook_preview.get("summary", "") or "").strip()
                if summary:
                    ui.label(summary).classes("sgfx-muted")
        if review_rows:
            with ui.column().classes("sgfx-diff-preview sgfx-side-by-side-preview"):
                ui.label("Side-by-side diff rows").classes("sgfx-panel-tagline")
                with ui.row().classes("sgfx-diff-triplet-sticky-header"):
                    for slot_label in ("Expected", "Actual", "Diff"):
                        ui.label(slot_label).classes("sgfx-diff-sticky-label")
                for row in review_rows:
                    label = row["label"] or row["key"] or "screenshot diff"

                    def _open(current: dict[str, str] = row) -> None:
                        if open_screenshot_viewer is not None:
                            open_screenshot_viewer(current["key"], current["label"])

                    with ui.column().classes("sgfx-diff-row-card"):
                        with ui.button(on_click=_open).props("flat no-caps").classes("sgfx-diff-triplet-button"):
                            with ui.row().classes("sgfx-diff-triplet"):
                                for slot in ("expected", "actual", "diff"):
                                    src = row.get(f"{slot}_src", "")
                                    with ui.column().classes("sgfx-diff-triplet-pane"):
                                        if src:
                                            ui.image(src).classes("sgfx-diff-thumb")
                                        else:
                                            ui.label("missing").classes("sgfx-muted")
                        with ui.row().classes("sgfx-diff-row-meta"):
                            ui.label(label).classes("sgfx-muted")
                            if row.get("diff_delta_label"):
                                ui.label(str(row["diff_delta_label"])).classes(
                                    f"sgfx-delta-badge sgfx-delta-{row['diff_delta_level']}"
                                )
                            if row.get("diff_regression_label"):
                                ui.label(str(row["diff_regression_label"])).classes(
                                    f"sgfx-regression-badge sgfx-regression-{row['diff_regression_level']}"
                                )
        elif image_items:
            with ui.column().classes("sgfx-diff-preview"):
                ui.label("Diff thumbnails").classes("sgfx-panel-tagline")
                with ui.row().classes("sgfx-diff-thumbnails"):
                    for item in image_items:
                        with ui.column().classes("sgfx-diff-thumb-card"):
                            ui.image(str(item["src"])).classes("sgfx-diff-thumb")
                            ui.label(str(item["label"])).classes("sgfx-muted")


def _render_action_technical_details(ui: Any, result: dict[str, Any], *, details_host: Any) -> None:
    details_host.clear()
    traceback_payload = _pipeline_traceback(result)
    if not traceback_payload:
        details_host.visible = False
        return
    details_host.visible = True
    with details_host:
        ui.label(traceback_payload["summary"]).classes("sgfx-warning")
        with ui.expansion("Show technical details", value=False).classes("full-width sgfx-technical-details"):
            ui.textarea(value=traceback_payload["technical_details"]).props("readonly outlined").classes(
                "full-width sgfx-technical-details-text"
            )


def _render_page_confluence_anchors(ui: Any, page: dict[str, Any]) -> None:
    for anchor in _page_confluence_anchors(page):
        _render_confluence_anchor(ui, anchor)


_FULL_QA_DRAFT_STEP_IDS = ("risk-score", "manual-review-assist", "operator-handoff")


def _full_qa_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _full_qa_step_payload(step: dict[str, Any]) -> dict[str, Any]:
    payload = step.get("payload", {})
    return payload if isinstance(payload, dict) else {}


def _full_qa_step_map(steps: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(step.get("id", "")): step for step in steps if isinstance(step, dict)}


def _full_qa_step_status(step: dict[str, Any]) -> str:
    return str(step.get("status", "unknown") or "unknown")


def _full_qa_screenshot_counts(step: dict[str, Any] | None) -> dict[str, int]:
    if not isinstance(step, dict):
        return {
            "expected_count": 0,
            "actual_count": 0,
            "diff_count": 0,
            "missing_candidate_count": 0,
            "review_row_count": 0,
            "evidence_file_count": 0,
            "pipeline_traceback_detected": 0,
        }
    payload = _full_qa_step_payload(step)
    rows = payload.get("screenshot_review_rows", [])
    copied_evidence = payload.get("copied_evidence", {})
    if not isinstance(rows, list) or not rows:
        if isinstance(copied_evidence, dict):
            rows = copied_evidence.get("screenshot_review_rows", [])
    pipeline_traceback = payload.get("pipeline_traceback", {})
    pipeline_detected = bool(pipeline_traceback.get("detected")) if isinstance(pipeline_traceback, dict) else False
    return {
        "expected_count": _full_qa_int(payload.get("expected_count")),
        "actual_count": _full_qa_int(payload.get("actual_count")),
        "diff_count": _full_qa_int(payload.get("diff_count")),
        "missing_candidate_count": _full_qa_int(payload.get("missing_candidate_count")),
        "review_row_count": len(rows) if isinstance(rows, list) else 0,
        "evidence_file_count": (
            _full_qa_int(copied_evidence.get("file_count")) if isinstance(copied_evidence, dict) else 0
        ),
        "pipeline_traceback_detected": 1 if pipeline_detected else 0,
    }


def _full_qa_risk_draft(profile_id: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    step_by_id = _full_qa_step_map(steps)
    screenshot_counts = _full_qa_screenshot_counts(step_by_id.get("screenshot-test-state"))
    risk_payload = _full_qa_step_payload(step_by_id.get("risk-score", {}))
    workbook_status = _full_qa_step_status(step_by_id.get("delivery-checklist", {}))
    workbook_trigger_status = _full_qa_step_status(step_by_id.get("delivery-workbook-trigger", {}))
    missing_candidate_count = screenshot_counts["missing_candidate_count"]
    diff_count = screenshot_counts["diff_count"]
    review_row_count = screenshot_counts["review_row_count"]
    evidence_file_count = screenshot_counts["evidence_file_count"]
    pipeline_traceback_detected = bool(screenshot_counts["pipeline_traceback_detected"])
    risk_score = _full_qa_int(risk_payload.get("risk_score"))
    risk_level = str(risk_payload.get("risk_level", "")).strip().casefold()
    expected = screenshot_counts["expected_count"]
    actual = screenshot_counts["actual_count"]

    level = "low"
    reasons: list[str] = []
    if missing_candidate_count:
        level = "high"
        reasons.append(f"{missing_candidate_count} screenshot candidate(s) are missing")
    elif (
        expected > 0
        and actual == 0
        and diff_count == 0
        and review_row_count == 0
        and evidence_file_count == 0
        and not pipeline_traceback_detected
    ):
        level = "high"
        reasons.append("expected screenshots exist but no actual or diff screenshots are present")
    elif risk_level == "high" or risk_score >= 70:
        level = "high"
        reasons.append(f"risk score is {risk_score}/100")
    elif (
        diff_count
        or review_row_count
        or evidence_file_count
        or pipeline_traceback_detected
        or risk_level == "medium"
        or risk_score >= 35
    ):
        level = "medium"
        count = diff_count or review_row_count
        if diff_count or review_row_count:
            reasons.append(f"{count} visual diff row(s) need operator review")
        elif evidence_file_count or pipeline_traceback_detected:
            reasons.append("screenshot capture output needs operator review")
        else:
            reasons.append(f"risk score is {risk_score}/100")
    else:
        reasons.append("local evidence has no high-risk signal")

    if workbook_status in {"failed", "incomplete", "unavailable"} or workbook_trigger_status in {
        "failed",
        "incomplete",
        "unavailable",
    }:
        if level == "low":
            level = "medium"
        reasons.append("workbook readiness is not passed")

    reason = "; ".join(reasons[:3])
    text = (
        f"Risk draft: {level} for {profile_id}. {reason}. "
        "Manual review remains required before any verdict is recorded."
    )
    return {
        "step_id": "risk-score",
        "label": "Risk Score draft",
        "level": level,
        "reason": reason,
        "text": text,
        "draft_available": True,
    }


def _full_qa_manual_review_draft(profile_id: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    step_by_id = _full_qa_step_map(steps)
    manual_step = step_by_id.get("manual-review-assist", {})
    payload = _full_qa_step_payload(manual_step)
    focus_steps = payload.get("operator_focus_steps", [])
    focus_count = (
        len(focus_steps) if isinstance(focus_steps, list) else _full_qa_int(manual_step.get("operator_focus_count"))
    )
    suggestions = payload.get("suggestions", [])
    suggestion_count = len(suggestions) if isinstance(suggestions, list) else 0
    session = payload.get("session", {}) if isinstance(payload.get("session"), dict) else {}
    recorded_count = _full_qa_int(session.get("recorded_steps") or payload.get("recorded_steps"))
    pending_count = _full_qa_int(session.get("pending_steps") or payload.get("pending_steps"))
    if not recorded_count and not pending_count:
        recorded_count = _full_qa_int(payload.get("recorded_verdict_count"))
        pending_count = _full_qa_int(payload.get("pending_verdict_count"))
    if focus_count:
        text = (
            f"Manual Review draft for {profile_id}: {focus_count} item(s) still need operator focus. "
            f"{suggestion_count} local suggestion(s) are captured for review; record verdicts only after inspection."
        )
    elif recorded_count or pending_count:
        text = (
            f"Manual Review draft for {profile_id}: {recorded_count} decision(s) recorded locally and "
            f"{pending_count} decision(s) still pending. Confirm the board before final handoff."
        )
    else:
        text = (
            f"Manual Review draft for {profile_id}: no recorded decision summary was found in this run. "
            "Open the Manual Review Companion if a verdict still needs to be entered."
        )
    return {
        "step_id": "manual-review-assist",
        "label": "Manual Review draft",
        "level": "manual_review_required",
        "reason": f"{focus_count} focus item(s), {recorded_count} recorded, {pending_count} pending",
        "text": text,
        "draft_available": True,
    }


def _full_qa_handoff_draft(profile_id: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    passed_count = len([step for step in steps if _full_qa_step_status(step) == "passed"])
    flagged_steps = [
        step
        for step in steps
        if _full_qa_step_status(step) in {"incomplete", "failed", "unavailable", "confirmation_pending"}
        or _full_qa_int(step.get("operator_focus_count")) > 0
    ]
    risk_draft = _full_qa_risk_draft(profile_id, steps)
    escalation = ""
    if str(risk_draft.get("level", "")) == "high":
        escalation = f" Escalation reason: {risk_draft.get('reason', '')}."
    elif flagged_steps:
        escalation = " Review the queued acknowledgment cards before shift handoff."
    text = (
        f"Full QA Pass for {profile_id} completed. {passed_count} automated steps passed; "
        f"{len(flagged_steps)} item(s) flagged for review.{escalation}"
    )
    return {
        "step_id": "operator-handoff",
        "label": "Operator Handoff draft",
        "level": "handoff",
        "reason": f"{passed_count} passed, {len(flagged_steps)} flagged",
        "text": text,
        "draft_available": True,
    }


def _full_qa_bulk_ack_drafts(profile_id: str, steps: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        "risk-score": _full_qa_risk_draft(profile_id, steps),
        "manual-review-assist": _full_qa_manual_review_draft(profile_id, steps),
        "operator-handoff": _full_qa_handoff_draft(profile_id, steps),
    }


def _dashboard_verbose_tooltips_enabled() -> bool:
    value = os.environ.get(VERBOSE_TOOLTIP_ENV, "").strip().casefold()
    return value not in {"0", "false", "no", "off"}


def _attach_tooltip(ui: Any, element: Any, text: str) -> Any:
    if not text.strip() or not _dashboard_verbose_tooltips_enabled():
        return element
    with element:
        ui.tooltip(text).props("delay=900").classes("sgfx-thinking-tooltip")
    return element


def _render_page_panel(ui: Any, page: dict[str, Any]) -> None:
    with _attach_tooltip(
        ui,
        ui.column().classes("sgfx-page-panel"),
        "Read-only evidence card for the selected local workspace and profile.",
    ):
        with ui.row().classes("items-center justify-between full-width"):
            ui.label(str(page["title"])).classes("sgfx-panel-title")
            _render_status_chip(ui, str(page.get("status", "unknown")))
        ui.label(str(page["tagline"])).classes("sgfx-panel-tagline")
        _render_page_confluence_anchors(ui, page)
        ownership_note = str(page.get("ownership_note", "")).strip()
        if ownership_note:
            ui.label(ownership_note).classes("sgfx-muted sgfx-ownership-note")
        ui.label(str(page.get("summary", ""))).classes("sgfx-summary")
        _render_empty_state_note(ui, page)
        rows = [
            {
                "label": str(item.get("label", "")),
                "status": str(item.get("status", "")),
                "detail": str(item.get("detail", "")),
            }
            for item in page.get("items", [])
            if isinstance(item, dict)
        ]
        if rows:
            _attach_tooltip(
                ui,
                ui.table(
                    columns=[
                        {"name": "label", "label": "Item", "field": "label", "align": "left"},
                        {"name": "status", "label": "Status", "field": "status", "align": "left"},
                        {"name": "detail", "label": "Detail", "field": "detail", "align": "left"},
                    ],
                    rows=rows,
                    row_key="label",
                ).classes("sgfx-table"),
                "Evidence rows are read from local files only.",
            )
        else:
            ui.label("No rows loaded for this page.").classes("sgfx-muted")


def _render_empty_state_note(ui: Any, page: dict[str, Any]) -> None:
    note = str(page.get("empty_state_note", "")).strip()
    if note:
        ui.label(note).classes("sgfx-warning")


def _render_first_run_welcome(
    ui: Any,
    snapshot: dict[str, Any],
    open_setup: Callable[[], None] | None = None,
    open_full_qa: Callable[[], None] | None = None,
) -> None:
    welcome = snapshot.get("welcome", {})
    if not isinstance(welcome, dict) or not welcome.get("show"):
        return
    with ui.column().classes("sgfx-page-panel sgfx-first-launch-card").props("data-sgfx-first-launch-card=true"):
        with ui.row().classes("items-center justify-between full-width"):
            ui.label(str(welcome.get("title", "Welcome"))).classes("sgfx-panel-title")
            with ui.row().classes("items-center sgfx-first-launch-actions"):
                _render_status_chip(ui, "incomplete")
                ui.html(
                    '<button type="button" class="sgfx-link-button" '
                    'data-sgfx-dismiss-onboarding="true" '
                    'onclick="window.sgfxDismissFirstLaunch && window.sgfxDismissFirstLaunch()">'
                    "Don't show again</button>",
                    sanitize=False,
                )
        ui.label(str(welcome.get("summary", ""))).classes("sgfx-summary")
        with ui.row().classes("sgfx-first-launch-actions"):
            if open_full_qa is not None:
                _attach_tooltip(
                    ui,
                    ui.button("Full QA Pass", on_click=open_full_qa).props("color=primary no-caps dense"),
                    "Open the one-pass wizard for the selected profile.",
                )
            setup_action_count = int(welcome.get("setup_action_count", 0) or 0)
            if open_setup is not None and setup_action_count > 0:
                _attach_tooltip(
                    ui,
                    ui.button("Run setup", on_click=open_setup).props("flat no-caps dense"),
                    "Open dependency setup; no system changes run without confirmation.",
                )
            elif setup_action_count == 0:
                ui.label(str(welcome.get("setup_complete_note", SETUP_COMPLETE_NOTE))).classes("sgfx-muted")


def _render_changed_profiles_card(
    ui: Any,
    snapshot: dict[str, Any],
    *,
    open_batch: Callable[[list[str]], None] | None = None,
) -> None:
    payload = snapshot.get("changed_profiles", {})
    if not isinstance(payload, dict):
        return
    status = str(payload.get("status", "unknown"))
    changed_profiles = [item for item in payload.get("changed_profiles", []) if isinstance(item, dict)]
    changed_ids = [str(item.get("profile_id", "")).strip() for item in changed_profiles if str(item.get("profile_id", "")).strip()]
    with ui.column().classes("sgfx-page-panel sgfx-changed-profiles-card"):
        with ui.row().classes("items-center justify-between full-width"):
            ui.label("Changed since last run").classes("sgfx-panel-title")
            _render_status_chip(ui, "incomplete" if changed_profiles else status)
        if status == "unavailable":
            ui.label("Change-detection unavailable; refresh manually.").classes("sgfx-warning")
            ui.label("Check BMW Git and SVN paths in setup if this persists.").classes("sgfx-muted")
            return
        ui.label(str(payload.get("summary", ""))).classes("sgfx-summary")
        if not changed_profiles:
            ui.label("No profiles changed since the last successful local run.").classes("sgfx-muted")
            return
        rows = [
            {
                "profile": str(item.get("profile_id", "")),
                "last_run": str(item.get("last_qa_pass_at", "")) or "not_run",
                "newest_config": str(item.get("newest_config_mtime", "")) or "unknown",
                "path": str(item.get("newest_config_path", "")),
            }
            for item in changed_profiles[:12]
        ]
        ui.table(
            columns=[
                {"name": "profile", "label": "Profile", "field": "profile", "align": "left"},
                {"name": "last_run", "label": "Last run", "field": "last_run", "align": "left"},
                {"name": "newest_config", "label": "Newest config", "field": "newest_config", "align": "left"},
                {"name": "path", "label": "Path", "field": "path", "align": "left"},
            ],
            rows=rows,
            row_key="profile",
        ).classes("sgfx-table")
        if open_batch is not None and changed_ids:
            _attach_tooltip(
                ui,
                ui.button("Run Full QA Pass on all", on_click=lambda: open_batch(changed_ids)).props("color=primary"),
                "Open the batch Full QA Pass runner with these changed profiles selected.",
            )


def _render_about_panel(ui: Any, content: dict[str, Any] | None = None) -> None:
    payload = content if isinstance(content, dict) else ABOUT_CONTENT
    with _attach_tooltip(
        ui,
        ui.column().classes("sgfx-page-panel"),
        "About this local-only preflight surface and its documented evidence anchors.",
    ):
        with ui.row().classes("items-center sgfx-brand-lockup"):
            ui.image(f"/sgfx-dashboard-assets/{DASHBOARD_BRAND_LOGO_ASSET}").classes("sgfx-about-logo")
            ui.label(str(payload.get("heading", "About"))).classes("sgfx-panel-title")
        ui.label(str(payload.get("description", ""))).classes("sgfx-summary")
        ui.label(str(payload.get("version_placeholder", ""))).classes("sgfx-muted")
        anchors = payload.get("confluence_anchors", ())
        if anchors:
            ui.label("Confluence anchors").classes("sgfx-panel-title")
            for label, anchor in anchors:
                ui.label(f"{label} — {anchor}").classes("sgfx-shortcut")
        disclosure_lines = tuple(payload.get("data_handling_disclosure", ()))
        if disclosure_lines:
            ui.label(str(disclosure_lines[0])).classes("sgfx-panel-title")
            for line in disclosure_lines[1:]:
                ui.label(str(line)).classes("sgfx-summary")
        for guardrail in DASHBOARD_GUARDRAILS:
            ui.label(str(guardrail)).classes("sgfx-guardrail")


def _render_setup_status_panel(
    ui: Any,
    setup_status: dict[str, Any],
    workspace: Path,
    *,
    on_setup_completed: Callable[[], None] | None = None,
) -> None:
    items = [item for item in setup_status.get("items", []) if isinstance(item, dict)]
    actions = [action for action in setup_status.get("actions", []) if isinstance(action, dict)]
    if not items:
        return
    ui.separator()
    with ui.column().classes("sgfx-page-panel"):
        with ui.row().classes("items-center justify-between full-width"):
            ui.label("Dependency setup").classes("sgfx-panel-title")
            _render_status_chip(ui, str(setup_status.get("status", "unknown")))
        ui.label(str(setup_status.get("summary", ""))).classes("sgfx-summary")
        ui.label("Setup actions disclose system changes and require operator confirmation.").classes("sgfx-muted")
        rows = [
            {
                "label": str(item.get("label", "")),
                "status": str(item.get("status", "")),
                "detail": str(item.get("detail", "")),
            }
            for item in items
        ]
        _attach_tooltip(
            ui,
            ui.table(
                columns=[
                    {"name": "label", "label": "Dependency", "field": "label", "align": "left"},
                    {"name": "status", "label": "Status", "field": "status", "align": "left"},
                    {"name": "detail", "label": "Detail", "field": "detail", "align": "left"},
                ],
                rows=rows,
                row_key="label",
            ).classes("sgfx-table"),
            "Detected installs are preferred; OneDrive setup is a fallback for missing tools.",
        )
        if not actions:
            ui.label("All setup dependencies are available.").classes("sgfx-muted")
            return
        status_label = ui.label("Local-only setup: no changes run until a confirmation dialog is accepted.").classes(
            "sgfx-muted"
        )
        progress = ui.linear_progress(value=0).props("indeterminate").classes("full-width")
        progress.visible = False
        elapsed_label = ui.label("Running 00:00 / typical setup range unknown").classes("sgfx-muted")
        elapsed_label.visible = False
        live_output = (
            ui.textarea(label="Live setup output", value="No output recorded yet.")
            .props("readonly outlined")
            .classes("full-width sgfx-live-output")
        )
        live_output.visible = False
        file_activity_label = ui.label("File activity").classes("sgfx-panel-tagline")
        file_activity_label.visible = False
        file_activity_host = ui.column().classes("sgfx-file-activity full-width")
        file_activity_host.visible = False
        job_state: dict[str, Any] = {"job": None}
        poll_timer_ref: dict[str, Any] = {"timer": None}

        def _stop_setup_poll_timer() -> None:
            _cancel_background_poll_timer(poll_timer_ref.get("timer"))
            poll_timer_ref["timer"] = None

        def _show_setup_progress() -> None:
            elapsed_label.visible = True
            live_output.visible = True
            file_activity_label.visible = True
            file_activity_host.visible = True

        def _reset_setup_progress() -> None:
            elapsed_label.text = "Running 00:00 / typical setup range unknown"
            live_output.value = "No output recorded yet."
            file_activity_host.clear()
            with file_activity_host:
                ui.label("No file changes recorded yet.").classes("sgfx-muted")

        def _update_setup_progress(result: dict[str, Any]) -> None:
            elapsed = str(result.get("elapsed_label", "00:00"))
            typical = str(result.get("typical_range", "typical setup range unknown"))
            elapsed_label.text = f"Running {elapsed} / {typical}"
            stdout_lines = [str(line) for line in result.get("stdout_tail_lines", []) if str(line).strip()]
            live_output.value = "\n".join(stdout_lines) if stdout_lines else "No output recorded yet."
            file_activity_host.clear()
            file_activity = [item for item in result.get("file_activity", []) if isinstance(item, dict)]
            with file_activity_host:
                if file_activity:
                    for item in file_activity:
                        ui.label(str(item.get("summary", ""))).classes("sgfx-summary")
                else:
                    ui.label("No file changes recorded yet.").classes("sgfx-muted")

        def _cancel_setup() -> None:
            job = job_state.get("job")
            if job is None:
                return
            result = cancel_dependency_setup_action(job)
            progress.visible = False
            _show_setup_progress()
            _update_setup_progress(result)
            status_label.text = str(result.get("summary", "Dependency setup canceled."))
            _stop_setup_poll_timer()
            cancel_button.disable()
            ui.notify("Dependency setup canceled.")

        cancel_button = _attach_tooltip(
            ui,
            ui.button("Cancel setup", on_click=_cancel_setup),
            "Stop the currently running local setup worker.",
        )
        cancel_button.disable()

        def _poll_setup() -> None:
            try:
                job = job_state.get("job")
                if job is None:
                    _stop_setup_poll_timer()
                    return
                result = poll_dependency_setup_action(job)
                if result is None:
                    return
                _show_setup_progress()
                _update_setup_progress(result)
                if not result.get("completed", True):
                    status_label.text = str(result.get("summary", "Dependency setup running."))
                    return
                _stop_setup_poll_timer()
                progress.visible = False
                cancel_button.disable()
                outcome = str(result.get("status", "unknown"))
                status_label.text = f"Setup {outcome}. {result.get('summary', '')} Re-reading dependency status."
                ui.notify(f"Dependency setup {outcome}.")
                if on_setup_completed is not None:
                    on_setup_completed()
            except RuntimeError as exc:
                if not _ignorable_nicegui_runtime_error(exc):
                    raise
                _stop_setup_poll_timer()

        def _start_setup_poll_timer() -> None:
            _stop_setup_poll_timer()
            poll_timer_ref["timer"] = _start_background_poll_timer(1.0, _poll_setup)

        with ui.row().classes("items-center"):
            for action in actions:
                with ui.dialog() as confirm_dialog, ui.card():
                    ui.label(str(action.get("label", "Set up"))).classes("sgfx-panel-title")
                    ui.label(str(action.get("confirmation_message", ""))).classes("sgfx-summary")
                    ui.label("System changes").classes("sgfx-panel-tagline")
                    for effect in action.get("effects", []):
                        ui.label(str(effect)).classes("sgfx-muted")
                    anchor = str(action.get("confluence_anchor", "")).strip()
                    if anchor:
                        ui.label(f"Confluence anchor: {anchor}").classes("sgfx-muted")
                    command_preview = str(action.get("command_preview", "")).strip()
                    if command_preview:
                        ui.label(command_preview).classes("sgfx-muted")
                    if not action.get("can_run_now"):
                        ui.label(
                            "This setup step needs operator-selected files, installer UI, or credentials before SGFX can run it."
                        ).classes("sgfx-muted")

                    action_id = str(action.get("id", ""))
                    source_supported = action_id in {
                        "setup-raco-from-shared-tools",
                        "setup-blender-411",
                        "setup-digital-3d-car-repo-idc23",
                    }
                    source_required = action_id in {
                        "setup-raco-from-shared-tools",
                        "setup-digital-3d-car-repo-idc23",
                    }
                    target_required = action_id in {
                        "setup-raco-from-shared-tools",
                        "clone-digital-3d-car-repo",
                        "setup-digital-3d-car-repo",
                        "setup-digital-3d-car-repo-idc23",
                    }
                    source_input = None
                    target_input = None
                    if source_supported:
                        source_input = _attach_tooltip(
                            ui,
                            ui.input(
                                "Source path",
                                value=str(action.get("source_path", "")),
                            ).classes("full-width"),
                            "Select an operator-approved local source, or leave optional installer sources blank.",
                        )
                    if target_required:
                        target_input = _attach_tooltip(
                            ui,
                            ui.input(
                                "Target path",
                                value=str(action.get("target_path", "")),
                            ).classes("full-width"),
                            "Select the local folder SGFX should use for setup output or registration.",
                        )

                    def _input_value(input_widget: Any, fallback: str = "") -> str:
                        if input_widget is None:
                            return fallback
                        return str(getattr(input_widget, "value", "") or "").strip()

                    def _inputs_ready(
                        source_widget: Any = source_input,
                        target_widget: Any = target_input,
                        source_needed: bool = source_required,
                        target_needed: bool = target_required,
                    ) -> bool:
                        if source_needed and not _input_value(source_widget):
                            return False
                        if target_needed and not _input_value(target_widget):
                            return False
                        return True

                    def _run(
                        action_payload: dict[str, Any] = action,
                        dialog: Any = confirm_dialog,
                        source_widget: Any = source_input,
                        target_widget: Any = target_input,
                    ) -> None:
                        selected_source = _input_value(source_widget, str(action_payload.get("source_path", "")))
                        selected_target = _input_value(target_widget, str(action_payload.get("target_path", "")))
                        try:
                            job_state["job"] = start_dependency_setup_action(
                                action_id=str(action_payload.get("id", "")),
                                workspace=workspace,
                                operator_confirmed=True,
                                target_path=selected_target or None,
                                source_path=selected_source or None,
                            )
                        except Exception as exc:  # noqa: BLE001
                            status_label.text = f"Setup failed: {exc}"
                            ui.notify("Dependency setup failed.")
                            dialog.close()
                            return
                        status_label.text = "Dependency setup running..."
                        progress.visible = True
                        _show_setup_progress()
                        _reset_setup_progress()
                        cancel_button.enable()
                        _start_setup_poll_timer()
                        dialog.close()

                    continue_button = _attach_tooltip(
                        ui,
                        ui.button("Continue", on_click=_run).props("color=primary"),
                        "Run this setup action after the confirmation dialog is accepted.",
                    )

                    def _refresh_continue_button(
                        _event: Any = None,
                        button: Any = continue_button,
                        ready: Callable[[], bool] = _inputs_ready,
                    ) -> None:
                        if ready():
                            button.enable()
                        else:
                            button.disable()

                    if source_input is not None:
                        source_input.on("update:model-value", _refresh_continue_button)
                    if target_input is not None:
                        target_input.on("update:model-value", _refresh_continue_button)
                    if not _inputs_ready():
                        continue_button.disable()
                    ui.button("Close", on_click=confirm_dialog.close)
                _attach_tooltip(
                    ui,
                    ui.button(str(action.get("label", "Set up")), on_click=confirm_dialog.open).props("no-caps"),
                    "Review required inputs and system changes before running this setup action.",
                )


def _render_delivery_checklist_panel(
    ui: Any,
    snapshot: dict[str, Any],
    workspace: Path,
    *,
    on_setup_completed: Callable[[], None] | None = None,
) -> None:
    page = next(page for page in snapshot["pages"] if page["id"] == "delivery-checklist")
    setup_status = page.get("setup_status", {})
    if isinstance(setup_status, dict):
        _render_setup_status_panel(ui, setup_status, workspace, on_setup_completed=on_setup_completed)
    with ui.column().classes("sgfx-page-panel"):
        with ui.row().classes("items-center justify-between full-width"):
            ui.label(str(page["title"])).classes("sgfx-panel-title")
            _render_status_chip(ui, str(page.get("status", "unknown")))
        ui.label(str(page["tagline"])).classes("sgfx-panel-tagline")
        _render_page_confluence_anchors(ui, page)
        ui.label(str(page.get("summary", ""))).classes("sgfx-summary")
        _render_empty_state_note(ui, page)
        rows = [
            {
                "label": str(item.get("label", "")),
                "status": str(item.get("status", "")),
                "detail": str(item.get("detail", "")),
            }
            for item in page.get("items", [])
            if isinstance(item, dict)
        ]
        if rows:
            _attach_tooltip(
                ui,
                ui.table(
                    columns=[
                        {"name": "label", "label": "Item", "field": "label", "align": "left"},
                        {"name": "status", "label": "Status", "field": "status", "align": "left"},
                        {"name": "detail", "label": "Detail", "field": "detail", "align": "left"},
                    ],
                    rows=rows,
                    row_key="label",
                ).classes("sgfx-table"),
                "Workbook evidence read from the selected local workspace.",
            )
        else:
            ui.label("No rows loaded for this page.").classes("sgfx-muted")
        trigger = page.get("workbook_trigger", {})
        if isinstance(trigger, dict):
            ui.separator()
            with ui.row().classes("items-center justify-between full-width"):
                ui.label("Workbook generation trigger").classes("sgfx-panel-tagline")
                _render_status_chip(ui, str(trigger.get("trigger_status", "unknown")))
            ui.label(str(trigger.get("summary", ""))).classes("sgfx-muted")
            ui.label("Local-only: generation starts only through the confirmation-gated action.").classes("sgfx-muted")

        actions = [
            action for action in page.get("actions", []) if isinstance(action, dict)
        ]
        for action in actions:
            if action.get("id") != GENERATE_WORKBOOK_ACTION_ID:
                continue
            preflight = action.get("preflight", {}) if isinstance(action.get("preflight"), dict) else {}
            checks = [
                {
                    "label": str(item.get("label", "")),
                    "status": str(item.get("status", "")),
                    "detail": str(item.get("detail", "")),
                }
                for item in preflight.get("checks", [])
                if isinstance(item, dict)
            ]
            ui.separator()
            ui.label("Generate delivery workbook").classes("sgfx-panel-tagline")
            ui.label("Environment pre-flight must pass before SGFX can invoke the BMW pipeline.").classes(
                "sgfx-muted"
            )
            anchor = str(action.get("confluence_anchor", "")).strip()
            if anchor:
                ui.label(f"Confluence anchor: {anchor}").classes("sgfx-muted")
            if checks:
                _attach_tooltip(
                    ui,
                    ui.table(
                        columns=[
                            {"name": "label", "label": "Check", "field": "label", "align": "left"},
                            {"name": "status", "label": "Status", "field": "status", "align": "left"},
                            {"name": "detail", "label": "Detail", "field": "detail", "align": "left"},
                        ],
                        rows=checks,
                        row_key="label",
                    ).classes("sgfx-table"),
                    "Pre-flight checks gate local workbook generation.",
                )
            disabled_reason = str(preflight.get("disabled_reason", "")).strip()
            if disabled_reason:
                ui.label(disabled_reason).classes("sgfx-muted")
            status_label = ui.label("Local-only: this action runs only after operator confirmation.").classes(
                "sgfx-muted"
            )
            progress = ui.linear_progress(value=0).props("indeterminate").classes("full-width")
            progress.visible = False
            elapsed_label = ui.label("Running 00:00 / typical 1-10 min").classes("sgfx-muted")
            elapsed_label.visible = False
            live_output = (
                ui.textarea(label="Live output", value="No output recorded yet.")
                .props("readonly outlined")
                .classes("full-width sgfx-live-output")
            )
            live_output.visible = False
            file_activity_label = ui.label("File activity").classes("sgfx-panel-tagline")
            file_activity_label.visible = False
            file_activity_host = ui.column().classes("sgfx-file-activity full-width")
            file_activity_host.visible = False
            job_state: dict[str, Any] = {"job": None}
            poll_timer_ref: dict[str, Any] = {"timer": None}

            def _stop_delivery_poll_timer() -> None:
                _cancel_background_poll_timer(poll_timer_ref.get("timer"))
                poll_timer_ref["timer"] = None

            def _show_live_progress() -> None:
                elapsed_label.visible = True
                live_output.visible = True
                file_activity_label.visible = True
                file_activity_host.visible = True

            def _reset_live_progress() -> None:
                elapsed_label.text = "Running 00:00 / typical 1-10 min"
                live_output.value = "No output recorded yet."
                file_activity_host.clear()
                with file_activity_host:
                    ui.label("No file changes recorded yet.").classes("sgfx-muted")

            def _update_live_progress(result: dict[str, Any]) -> None:
                elapsed = str(result.get("elapsed_label", "00:00"))
                typical = str(result.get("typical_range", "typical 1-10 min"))
                elapsed_label.text = f"Running {elapsed} / {typical}"
                stdout_lines = [str(line) for line in result.get("stdout_tail_lines", []) if str(line).strip()]
                live_output.value = "\n".join(stdout_lines) if stdout_lines else "No output recorded yet."
                file_activity_host.clear()
                file_activity = [item for item in result.get("file_activity", []) if isinstance(item, dict)]
                with file_activity_host:
                    if file_activity:
                        for item in file_activity:
                            ui.label(str(item.get("summary", ""))).classes("sgfx-summary")
                    else:
                        ui.label("No file changes recorded yet.").classes("sgfx-muted")

            def _cancel() -> None:
                job = job_state.get("job")
                if job is None:
                    return
                result = cancel_delivery_workbook_generation(job)
                progress.visible = False
                _show_live_progress()
                _update_live_progress(result)
                status_label.text = str(result.get("summary", "Generation canceled."))
                _stop_delivery_poll_timer()
                ui.notify("Delivery workbook generation canceled.")

            cancel_button = _attach_tooltip(
                ui,
                ui.button("Cancel", on_click=_cancel),
                "Stop the local workbook-generation worker.",
            )
            cancel_button.disable()

            def _poll() -> None:
                try:
                    job = job_state.get("job")
                    if job is None:
                        _stop_delivery_poll_timer()
                        return
                    result = poll_delivery_workbook_generation(job)
                    if result is None:
                        return
                    _show_live_progress()
                    _update_live_progress(result)
                    if not result.get("completed", True):
                        status_label.text = str(result.get("summary", "BMW pipeline export running."))
                        return
                    _stop_delivery_poll_timer()
                    progress.visible = False
                    cancel_button.disable()
                    outcome = str(result.get("status", "unknown"))
                    status_label.text = (
                        f"Generation {outcome}. {result.get('summary', '')} Refresh to re-read workbook evidence."
                    )
                    ui.notify(f"Delivery workbook generation {outcome}.")
                    _notify_completion_safe(
                        title="SGFX delivery workbook finished",
                        message=f"Delivery workbook generation {outcome}.",
                        workspace=workspace,
                        action_id=GENERATE_WORKBOOK_ACTION_ID,
                        profile_id=str(snapshot["profile_id"]),
                        evidence_path=str(result.get("output_root", "")),
                        elapsed_seconds=result.get("elapsed_seconds"),
                        minimum_elapsed_seconds=LONG_RUNNING_NOTIFICATION_SECONDS,
                    )
                except RuntimeError as exc:
                    if not _parent_slot_deleted(exc):
                        raise
                    _stop_delivery_poll_timer()

            def _start_delivery_poll_timer() -> None:
                _stop_delivery_poll_timer()
                poll_timer_ref["timer"] = _start_background_poll_timer(1.0, _poll)

            with ui.dialog() as confirm_dialog, ui.card():
                ui.label(str(action.get("confirmation_message", ""))).classes("sgfx-summary")
                ui.label("Manual review remains required. Decision: not approval — evidence only.").classes(
                    "sgfx-muted"
                )

                def _start() -> None:
                    try:
                        job_state["job"] = start_delivery_workbook_generation(
                            profile_id=str(snapshot["profile_id"]),
                            workspace=workspace,
                            operator_confirmed=True,
                        )
                    except Exception as exc:  # noqa: BLE001
                        status_label.text = f"Generation failed to start: {exc}"
                        ui.notify("Delivery workbook generation failed to start.")
                        confirm_dialog.close()
                        return
                    status_label.text = "BMW pipeline export running..."
                    progress.visible = True
                    _show_live_progress()
                    _reset_live_progress()
                    cancel_button.enable()
                    _start_delivery_poll_timer()
                    confirm_dialog.close()

                confirm_button = _attach_tooltip(
                    ui,
                    ui.button("Continue", on_click=_start).props("color=primary"),
                    "Start local workbook generation after this confirmation.",
                )
                if action.get("disabled"):
                    confirm_button.disable()
                ui.button("Close", on_click=confirm_dialog.close)
            run_button = _attach_tooltip(
                ui,
                ui.button(str(action.get("label", GENERATE_WORKBOOK_ACTION_LABEL)), on_click=confirm_dialog.open),
                "Generate workbook evidence locally after the environment pre-flight passes.",
            )
            if action.get("disabled"):
                run_button.disable()


def _render_screenshot_test_state_panel(
    ui: Any,
    snapshot: dict[str, Any],
    workspace: Path,
    *,
    bmw_root: Path | str | None = None,
) -> None:
    page = next(page for page in snapshot["pages"] if page["id"] == "screenshot-test-state")
    with ui.column().classes("sgfx-page-panel"):
        with ui.row().classes("items-center justify-between full-width"):
            ui.label(str(page["title"])).classes("sgfx-panel-title")
            _render_status_chip(ui, str(page.get("status", "unknown")))
        ui.label(str(page["tagline"])).classes("sgfx-panel-tagline")
        _render_page_confluence_anchors(ui, page)
        ui.label(str(page.get("summary", ""))).classes("sgfx-summary")
        _render_empty_state_note(ui, page)
        ownership_note = str(page.get("ownership_note", "")).strip()
        if ownership_note:
            ui.label(ownership_note).classes("sgfx-muted")
        rows = [
            {
                "label": str(item.get("label", "")),
                "status": str(item.get("status", "")),
                "detail": str(item.get("detail", "")),
            }
            for item in page.get("items", [])
            if isinstance(item, dict)
        ]
        if rows:
            _attach_tooltip(
                ui,
                ui.table(
                    columns=[
                        {"name": "label", "label": "Item", "field": "label", "align": "left"},
                        {"name": "status", "label": "Status", "field": "status", "align": "left"},
                        {"name": "detail", "label": "Detail", "field": "detail", "align": "left"},
                    ],
                    rows=rows,
                    row_key="label",
                ).classes("sgfx-table"),
                "Screenshot evidence counts are read from local BMW and SVN folders.",
            )
        else:
            ui.label("No rows loaded for this page.").classes("sgfx-muted")

        ui.separator()
        ui.label("Side-by-side screenshot review").classes("sgfx-panel-tagline")
        ui.label(
            "Build a local expected / actual / diff viewer with synchronized zoom and pan. "
            "Manual review remains required."
        ).classes("sgfx-muted")
        viewer_status = ui.label("Viewer not generated in this session.").classes("sgfx-muted")
        viewer_links = ui.column().classes("full-width")

        with ui.dialog() as viewer_dialog:
            with ui.card().classes("sgfx-viewer-dialog-card"):
                with ui.row().classes("items-center justify-between full-width"):
                    viewer_dialog_title = ui.label("Side-by-side screenshot review").classes("sgfx-panel-title")
                    _attach_tooltip(
                        ui,
                        ui.button("Close", on_click=viewer_dialog.close).props("flat dense no-caps"),
                        "Close the embedded screenshot review viewer.",
                    )
                ui.label(
                    "Expected / actual / diff panes render below with synchronized zoom and pan controls. "
                    "Manual review remains required."
                ).classes("sgfx-muted")
                viewer_frame_host = ui.column().classes("sgfx-viewer-frame-host")

        def _open_inline_viewer(url: str, label: str = "") -> None:
            viewer_dialog_title.text = label or "Side-by-side screenshot review"
            viewer_frame_host.clear()
            safe_url = html_escape(url, quote=True)
            with viewer_frame_host:
                ui.html(
                    f'<iframe data-sgfx-inline-viewer="true" class="sgfx-viewer-iframe" '
                    f'src="{safe_url}" title="Side-by-side screenshot review"></iframe>',
                    sanitize=False,
                ).classes("full-width")
            viewer_status.text = f"Viewer open inside SGFX: {label or 'all screenshot rows'}."
            viewer_dialog.open()

        def _render_viewer_links(bundle: Any) -> None:
            viewer_links.clear()
            with viewer_links:
                items = [item for item in bundle.viewer.items if item.diff_uri or item.actual_uri or item.expected_uri]
                if not items:
                    ui.label("No screenshot pairs were available for the viewer.").classes("sgfx-muted")
                    return
                ui.label("Open a diff row in the side-by-side viewer.").classes("sgfx-muted")
                for item in items[:12]:
                    target_url = _screenshot_review_viewer_url(str(snapshot["profile_id"]), item.key)
                    target_label = f"{item.key} [{item.classification} / {item.visual_classification}]"
                    button = _attach_tooltip(
                        ui,
                        ui.button(
                            target_label,
                            on_click=lambda url=target_url, label=target_label: _open_inline_viewer(url, label),
                        ),
                        "Open this screenshot in the synchronized expected / actual / diff viewer.",
                    )
                    button.classes("sgfx-nav-button")

        def _build_and_open_viewer() -> None:
            try:
                bundle = _materialize_screenshot_review_viewer_for_dashboard(
                    str(snapshot["profile_id"]),
                    workspace,
                    bmw_root=bmw_root,
                )
            except Exception as exc:  # noqa: BLE001
                viewer_status.text = f"Viewer generation failed: {exc}"
                ui.notify("Screenshot review viewer generation failed.")
                return
            viewer_status.text = (
                f"Viewer generated with {bundle.viewer.item_count} screenshot item(s). "
                f"JSON: {bundle.json_path.name}"
            )
            _render_viewer_links(bundle)
            _open_inline_viewer(
                _screenshot_review_viewer_url(str(snapshot["profile_id"])),
                f"Side-by-side screenshot review - {snapshot['profile_id']}",
            )
            ui.notify("Screenshot review viewer generated locally.")

        _attach_tooltip(
            ui,
            ui.button("Build viewer", on_click=_build_and_open_viewer),
            "Build and open the local side-by-side screenshot review viewer.",
        )

        actions = [action for action in page.get("actions", []) if isinstance(action, dict)]
        for action in actions:
            if action.get("id") != SCREENSHOT_CAPTURE_ACTION_ID:
                continue
            preflight = action.get("preflight", {}) if isinstance(action.get("preflight"), dict) else {}
            checks = [
                {
                    "label": str(item.get("label", "")),
                    "status": str(item.get("status", "")),
                    "detail": str(item.get("detail", "")),
                }
                for item in preflight.get("checks", [])
                if isinstance(item, dict)
            ]
            ui.separator()
            ui.label("Capture screenshots").classes("sgfx-panel-tagline")
            ui.label("Environment pre-flight must pass before SGFX can invoke the BMW screenshot helper.").classes(
                "sgfx-muted"
            )
            anchor = str(action.get("confluence_anchor", "")).strip()
            if anchor:
                ui.label(f"Confluence anchor: {anchor}").classes("sgfx-muted")
            if checks:
                _attach_tooltip(
                    ui,
                    ui.table(
                        columns=[
                            {"name": "label", "label": "Check", "field": "label", "align": "left"},
                            {"name": "status", "label": "Status", "field": "status", "align": "left"},
                            {"name": "detail", "label": "Detail", "field": "detail", "align": "left"},
                        ],
                        rows=checks,
                        row_key="label",
                    ).classes("sgfx-table"),
                    "Pre-flight checks gate local screenshot capture.",
                )
            disabled_reason = str(preflight.get("disabled_reason", "")).strip()
            if disabled_reason:
                ui.label(disabled_reason).classes("sgfx-muted")
            status_label = ui.label("Local-only: this action runs only after operator confirmation.").classes(
                "sgfx-muted"
            )
            progress = ui.linear_progress(value=0).props("indeterminate").classes("full-width")
            progress.visible = False
            elapsed_label = ui.label("Running 00:00 / typical 2-10 min").classes("sgfx-muted")
            elapsed_label.visible = False
            live_output = (
                ui.textarea(label="Live output", value="No output recorded yet.")
                .props("readonly outlined")
                .classes("full-width sgfx-live-output")
            )
            live_output.visible = False
            file_activity_label = ui.label("File activity").classes("sgfx-panel-tagline")
            file_activity_label.visible = False
            file_activity_host = ui.column().classes("sgfx-file-activity full-width")
            file_activity_host.visible = False
            job_state: dict[str, Any] = {"job": None}
            poll_timer_ref: dict[str, Any] = {"timer": None}

            def _stop_screenshot_poll_timer() -> None:
                _cancel_background_poll_timer(poll_timer_ref.get("timer"))
                poll_timer_ref["timer"] = None

            def _show_live_progress() -> None:
                elapsed_label.visible = True
                live_output.visible = True
                file_activity_label.visible = True
                file_activity_host.visible = True

            def _reset_live_progress() -> None:
                elapsed_label.text = "Running 00:00 / typical 2-10 min"
                live_output.value = "No output recorded yet."
                file_activity_host.clear()
                with file_activity_host:
                    ui.label("No file changes recorded yet.").classes("sgfx-muted")

            def _update_live_progress(result: dict[str, Any]) -> None:
                elapsed = str(result.get("elapsed_label", "00:00"))
                typical = str(result.get("typical_range", "typical 2-10 min"))
                elapsed_label.text = f"Running {elapsed} / {typical}"
                stdout_lines = [str(line) for line in result.get("stdout_tail_lines", []) if str(line).strip()]
                live_output.value = "\n".join(stdout_lines) if stdout_lines else "No output recorded yet."
                file_activity_host.clear()
                file_activity = [item for item in result.get("file_activity", []) if isinstance(item, dict)]
                with file_activity_host:
                    if file_activity:
                        for item in file_activity:
                            ui.label(str(item.get("summary", ""))).classes("sgfx-summary")
                    else:
                        ui.label("No file changes recorded yet.").classes("sgfx-muted")

            def _cancel() -> None:
                job = job_state.get("job")
                if job is None:
                    return
                result = cancel_screenshot_capture(job)
                progress.visible = False
                _show_live_progress()
                _update_live_progress(result)
                status_label.text = str(result.get("summary", "Screenshot capture canceled."))
                _stop_screenshot_poll_timer()
                ui.notify("Screenshot capture canceled.")

            cancel_button = _attach_tooltip(
                ui,
                ui.button("Cancel", on_click=_cancel),
                "Stop the local screenshot-capture worker.",
            )
            cancel_button.disable()

            def _poll() -> None:
                try:
                    job = job_state.get("job")
                    if job is None:
                        _stop_screenshot_poll_timer()
                        return
                    result = poll_screenshot_capture(job)
                    if result is None:
                        return
                    _show_live_progress()
                    _update_live_progress(result)
                    if not result.get("completed", True):
                        status_label.text = str(result.get("summary", "BMW screenshot capture running."))
                        return
                    _stop_screenshot_poll_timer()
                    progress.visible = False
                    cancel_button.disable()
                    outcome = str(result.get("status", "unknown"))
                    status_label.text = (
                        f"Screenshot capture {outcome}. {result.get('summary', '')} "
                        "Refresh to re-read screenshot evidence."
                    )
                    ui.notify(f"Screenshot capture {outcome}.")
                    _notify_completion_safe(
                        title="SGFX screenshot capture finished",
                        message=f"Screenshot capture {outcome}.",
                        workspace=workspace,
                        action_id=SCREENSHOT_CAPTURE_ACTION_ID,
                        profile_id=str(snapshot["profile_id"]),
                        evidence_path=str(result.get("output_root", "")),
                        elapsed_seconds=result.get("elapsed_seconds"),
                        minimum_elapsed_seconds=LONG_RUNNING_NOTIFICATION_SECONDS,
                    )
                except RuntimeError as exc:
                    if not _parent_slot_deleted(exc):
                        raise
                    _stop_screenshot_poll_timer()

            def _start_screenshot_poll_timer() -> None:
                _stop_screenshot_poll_timer()
                poll_timer_ref["timer"] = _start_background_poll_timer(1.0, _poll)

            with ui.dialog() as confirm_dialog, ui.card():
                ui.label(str(action.get("confirmation_message", ""))).classes("sgfx-summary")
                ui.label("Manual review remains required. Decision: not approval — evidence only.").classes(
                    "sgfx-muted"
                )

                def _start() -> None:
                    try:
                        job_state["job"] = start_screenshot_capture(
                            profile_id=str(snapshot["profile_id"]),
                            workspace=workspace,
                            bmw_root=bmw_root,
                            operator_confirmed=True,
                        )
                    except Exception as exc:  # noqa: BLE001
                        status_label.text = f"Screenshot capture failed to start: {exc}"
                        ui.notify("Screenshot capture failed to start.")
                        confirm_dialog.close()
                        return
                    status_label.text = "BMW screenshot capture running..."
                    progress.visible = True
                    _show_live_progress()
                    _reset_live_progress()
                    cancel_button.enable()
                    _start_screenshot_poll_timer()
                    confirm_dialog.close()

                confirm_button = _attach_tooltip(
                    ui,
                    ui.button("Continue", on_click=_start).props("color=primary"),
                    "Start local screenshot capture after this confirmation.",
                )
                if action.get("disabled"):
                    confirm_button.disable()
                ui.button("Close", on_click=confirm_dialog.close)
            run_button = _attach_tooltip(
                ui,
                ui.button(str(action.get("label", SCREENSHOT_CAPTURE_ACTION_LABEL)), on_click=confirm_dialog.open),
                "Capture screenshot evidence locally after the environment pre-flight passes.",
            )
            if action.get("disabled"):
                run_button.disable()


def _render_risk_score_panel(ui: Any, snapshot: dict[str, Any]) -> None:
    page = next(page for page in snapshot["pages"] if page["id"] == "risk-score")
    payload = page.get("payload", {}) if isinstance(page.get("payload"), dict) else {}
    current = payload.get("current_snapshot", {}) if isinstance(payload.get("current_snapshot"), dict) else {}
    latest = payload.get("latest_review", {}) if isinstance(payload.get("latest_review"), dict) else {}
    delta = (
        payload.get("delta_since_last_review", {})
        if isinstance(payload.get("delta_since_last_review"), dict)
        else {}
    )
    with ui.column().classes("sgfx-page-panel"):
        with ui.row().classes("items-center justify-between full-width"):
            ui.label(str(page["title"])).classes("sgfx-panel-title")
            _render_status_chip(ui, str(page.get("status", "unknown")))
        ui.label(str(page["tagline"])).classes("sgfx-panel-tagline")
        _render_page_confluence_anchors(ui, page)
        ownership_note = str(page.get("ownership_note", "")).strip()
        if ownership_note:
            ui.label(ownership_note).classes("sgfx-muted sgfx-ownership-note")
        ui.label(str(page.get("summary", ""))).classes("sgfx-summary")
        ui.label("Manual review remains required. Decision: not approval — evidence only.").classes("sgfx-muted")
        _render_empty_state_note(ui, page)
        with ui.row().classes("full-width"):
            with ui.column().classes("sgfx-risk-metric"):
                ui.label("Current evidence").classes("sgfx-panel-tagline")
                ui.label(
                    f"{current.get('expected_count', 0)} expected / "
                    f"{current.get('actual_count', 0)} actual / {current.get('diff_count', 0)} diff"
                ).classes("sgfx-summary")
                ui.label(f"Disabled tests: {current.get('disabled_test_count', 0)}").classes("sgfx-muted")
            with ui.column().classes("sgfx-risk-metric"):
                ui.label("Latest manual review").classes("sgfx-panel-tagline")
                ui.label(str(latest.get("session_id", "") or "not found")).classes("sgfx-summary")
                ui.label(
                    f"{latest.get('recorded_steps', 0)} recorded / {latest.get('pending_steps', 0)} not_run"
                ).classes("sgfx-muted")
            with ui.column().classes("sgfx-risk-metric"):
                ui.label("Delta since latest review").classes("sgfx-panel-tagline")
                ui.label(f"{delta.get('changed_file_count', 0)} changed screenshot file(s)").classes("sgfx-summary")
                ui.label(str(delta.get("summary", ""))).classes("sgfx-muted")
        rows = [
            {
                "label": str(item.get("label", "")),
                "status": str(item.get("status", "")),
                "detail": str(item.get("detail", "")),
            }
            for item in page.get("items", [])
            if isinstance(item, dict)
        ]
        if rows:
            _attach_tooltip(
                ui,
                ui.table(
                    columns=[
                        {"name": "label", "label": "Signal", "field": "label", "align": "left"},
                        {"name": "status", "label": "Status", "field": "status", "align": "left"},
                        {"name": "detail", "label": "Detail", "field": "detail", "align": "left"},
                    ],
                    rows=rows,
                    row_key="label",
                ).classes("sgfx-table"),
                "Risk signals are deterministic local-file observations.",
            )


def _render_cross_car_comparison_panel(ui: Any, snapshot: dict[str, Any]) -> None:
    page = next(page for page in snapshot["pages"] if page["id"] == "cross-car-comparison")
    payload = page.get("payload", {}) if isinstance(page.get("payload"), dict) else {}
    left_profile = str(payload.get("left_profile", "G70"))
    right_profile = str(payload.get("right_profile", "G65"))
    with ui.column().classes("sgfx-page-panel"):
        with ui.row().classes("items-center justify-between full-width"):
            ui.label(str(page["title"])).classes("sgfx-panel-title")
            _render_status_chip(ui, str(page.get("status", "unknown")))
        ui.label(str(page["tagline"])).classes("sgfx-panel-tagline")
        _render_page_confluence_anchors(ui, page)
        ownership_note = str(page.get("ownership_note", "")).strip()
        if ownership_note:
            ui.label(ownership_note).classes("sgfx-muted sgfx-ownership-note")
        ui.label(str(page.get("summary", ""))).classes("sgfx-summary")
        ui.label("Manual review remains required. Decision: not approval — evidence only.").classes("sgfx-muted")
        _render_empty_state_note(ui, page)
        rows = [
            {
                "label": str(item.get("label", "")),
                "left_value": str(item.get("left_value", "")),
                "right_value": str(item.get("right_value", "")),
                "delta": str(item.get("delta_label", "")),
                "status": str(item.get("status", "")),
            }
            for item in page.get("items", [])
            if isinstance(item, dict)
        ]
        if rows:
            _attach_tooltip(
                ui,
                ui.table(
                    columns=[
                        {"name": "label", "label": "Signal", "field": "label", "align": "left"},
                        {"name": "left_value", "label": left_profile, "field": "left_value", "align": "left"},
                        {"name": "right_value", "label": right_profile, "field": "right_value", "align": "left"},
                        {"name": "delta", "label": "Delta", "field": "delta", "align": "left"},
                        {"name": "status", "label": "Status", "field": "status", "align": "left"},
                    ],
                    rows=rows,
                    row_key="label",
                ).classes("sgfx-table"),
                "Compares the same local risk-score widget across two profiles.",
            )


def _render_daily_digest_panel(ui: Any, snapshot: dict[str, Any], workspace: Path) -> None:
    page = next(page for page in snapshot["pages"] if page["id"] == "daily-digest")
    with ui.column().classes("sgfx-page-panel"):
        with ui.row().classes("items-center justify-between full-width"):
            ui.label(str(page["title"])).classes("sgfx-panel-title")
            _render_status_chip(ui, str(page.get("status", "unknown")))
        ui.label(str(page["tagline"])).classes("sgfx-panel-tagline")
        _render_page_confluence_anchors(ui, page)
        ui.label(str(page.get("summary", ""))).classes("sgfx-summary")
        _render_empty_state_note(ui, page)
        rows = [
            {
                "label": str(item.get("label", "")),
                "status": str(item.get("status", "")),
                "detail": str(item.get("detail", "")),
            }
            for item in page.get("items", [])
            if isinstance(item, dict)
        ]
        if rows:
            _attach_tooltip(
                ui,
                ui.table(
                    columns=[
                        {"name": "label", "label": "Item", "field": "label", "align": "left"},
                        {"name": "status", "label": "Status", "field": "status", "align": "left"},
                        {"name": "detail", "label": "Detail", "field": "detail", "align": "left"},
                    ],
                    rows=rows,
                    row_key="label",
                ).classes("sgfx-table"),
                "Digest rows summarize local evidence prepared for review.",
            )
        else:
            ui.label("No rows loaded for this page.").classes("sgfx-muted")
        actions = [
            action for action in page.get("actions", []) if isinstance(action, dict)
        ]
        for action in actions:
            if action.get("id") != DAILY_DIGEST_BUILD_PACKAGE_ACTION_ID:
                continue
            ui.label("Build review package").classes("sgfx-panel-tagline")
            anchor = str(action.get("confluence_anchor", "")).strip()
            if anchor:
                ui.label(f"Confluence anchor: {anchor}").classes("sgfx-muted")
            hint = str(action.get("ticket_id_hint", "")).strip() or DAILY_DIGEST_TICKET_ID_PLACEHOLDER
            ticket_input = ui.input(
                label="Ticket ID",
                value=str(action.get("ticket_id_default", "")).strip(),
                placeholder=hint,
            ).classes("full-width")
            source = str(action.get("ticket_id_source", "")).strip()
            if source and source != "manual_entry":
                ui.label(f"Detected ticket source: {source}.").classes("sgfx-muted")
            recent_tickets = [str(item).strip() for item in action.get("recent_ticket_ids", []) if str(item).strip()]
            if recent_tickets:
                ui.label("Recent tickets: " + ", ".join(recent_tickets[:5])).classes("sgfx-muted")
            status_label = ui.label("Local-only: this runs the read-only `ticket-review` CLI in the background.").classes(
                "sgfx-muted"
            )
            progress = ui.linear_progress(value=0).props("indeterminate").classes("full-width")
            progress.visible = False
            elapsed_label = ui.label(f"Running 00:00 / {_BUILD_PACKAGE_TYPICAL_RANGE_LABEL}").classes("sgfx-muted")
            elapsed_label.visible = False
            live_output = (
                ui.textarea(label="Live package output", value="No output recorded yet.")
                .props("readonly outlined")
                .classes("full-width sgfx-live-output")
            )
            live_output.visible = False
            file_activity_label = ui.label("File activity").classes("sgfx-panel-tagline")
            file_activity_label.visible = False
            file_activity_host = ui.column().classes("sgfx-file-activity full-width")
            file_activity_host.visible = False
            job_state: dict[str, Any] = {"job": None}
            poll_timer_ref: dict[str, Any] = {"timer": None}

            def _stop_build_poll_timer() -> None:
                _cancel_background_poll_timer(poll_timer_ref.get("timer"))
                poll_timer_ref["timer"] = None

            def _show_build_progress() -> None:
                elapsed_label.visible = True
                live_output.visible = True
                file_activity_label.visible = True
                file_activity_host.visible = True

            def _reset_build_progress() -> None:
                elapsed_label.text = f"Running 00:00 / {_BUILD_PACKAGE_TYPICAL_RANGE_LABEL}"
                live_output.value = "No output recorded yet."
                file_activity_host.clear()
                with file_activity_host:
                    ui.label("No file changes recorded yet.").classes("sgfx-muted")

            def _update_build_progress(result: dict[str, Any]) -> None:
                elapsed = str(result.get("elapsed_label", "00:00"))
                typical = str(result.get("typical_range", _BUILD_PACKAGE_TYPICAL_RANGE_LABEL))
                elapsed_label.text = f"Running {elapsed} / {typical}"
                stdout_lines = [str(line) for line in result.get("stdout_tail_lines", []) if str(line).strip()]
                live_output.value = "\n".join(stdout_lines) if stdout_lines else "No output recorded yet."
                file_activity_host.clear()
                file_activity = [item for item in result.get("file_activity", []) if isinstance(item, dict)]
                with file_activity_host:
                    if file_activity:
                        for item in file_activity:
                            ui.label(str(item.get("summary", ""))).classes("sgfx-summary")
                    else:
                        ui.label("No file changes recorded yet.").classes("sgfx-muted")

            def _cancel_build() -> None:
                job = job_state.get("job")
                if job is None:
                    return
                result = cancel_dashboard_review_package_build(job)
                progress.visible = False
                _show_build_progress()
                _update_build_progress(result)
                status_label.text = str(result.get("summary", "Build review package canceled."))
                _stop_build_poll_timer()
                cancel_button.disable()
                ui.notify("Build review package canceled.")

            cancel_button = _attach_tooltip(
                ui,
                ui.button("Cancel build", on_click=_cancel_build),
                "Stop the local review-package build worker.",
            )
            cancel_button.disable()

            def _poll_build() -> None:
                try:
                    job = job_state.get("job")
                    if job is None:
                        _stop_build_poll_timer()
                        return
                    result = poll_dashboard_review_package_build(job)
                    if result is None:
                        return
                    _show_build_progress()
                    _update_build_progress(result)
                    if not result.get("completed", True):
                        status_label.text = str(result.get("summary", "Build review package running."))
                        return
                    _stop_build_poll_timer()
                    progress.visible = False
                    cancel_button.disable()
                    outcome = str(result.get("outcome", "unknown"))
                    exit_code = result.get("exit_code", "?")
                    status_label.text = (
                        f"Build {outcome} (exit {exit_code}) for {result.get('ticket_id', '')}. "
                        "Refresh to reload digest evidence."
                    )
                    ui.notify(f"Build review package {outcome}.")
                    _notify_completion_safe(
                        title="SGFX review package finished",
                        message=f"Build review package {outcome} for {result.get('ticket_id', '')}.",
                        workspace=workspace,
                        action_id=DAILY_DIGEST_BUILD_PACKAGE_ACTION_ID,
                        profile_id=str(snapshot["profile_id"]),
                        evidence_path=str(result.get("output_root", "")),
                        elapsed_seconds=result.get("elapsed_seconds"),
                        minimum_elapsed_seconds=LONG_RUNNING_NOTIFICATION_SECONDS,
                    )
                except RuntimeError as exc:
                    if not _parent_slot_deleted(exc):
                        raise
                    _stop_build_poll_timer()

            def _start_build_poll_timer() -> None:
                _stop_build_poll_timer()
                poll_timer_ref["timer"] = _start_background_poll_timer(1.0, _poll_build)

            with ui.dialog() as confirm_dialog, ui.card():
                ui.label("Build review package").classes("sgfx-panel-title")
                ui.label(
                    "This builds a local evidence package from current workspace data; nothing is posted externally."
                ).classes("sgfx-summary")
                ui.label("Manual review remains required. Decision: not approval — evidence only.").classes(
                    "sgfx-muted"
                )

                def _build(ticket_input=ticket_input, status_label=status_label) -> None:
                    ticket_value = str(ticket_input.value or "").strip()
                    if not ticket_value:
                        ui.notify("Enter a ticket ID before building a review package.")
                        return
                    try:
                        job_state["job"] = start_dashboard_review_package_build(
                            workspace=workspace,
                            profile_id=str(snapshot["profile_id"]),
                            ticket_id=ticket_value,
                            operator_confirmed=True,
                        )
                    except Exception as exc:  # noqa: BLE001
                        status_label.text = f"Build failed to start: {exc}"
                        ui.notify("Build review package failed to start.")
                        confirm_dialog.close()
                        return
                    status_label.text = f"Build review package running for {ticket_value}..."
                    progress.visible = True
                    _show_build_progress()
                    _reset_build_progress()
                    cancel_button.enable()
                    _start_build_poll_timer()
                    confirm_dialog.close()

                _attach_tooltip(
                    ui,
                    ui.button("Continue", on_click=_build).props("color=primary"),
                    "Start the local review-package build after this confirmation.",
                )
                ui.button("Close", on_click=confirm_dialog.close)

            def _open_build_dialog(ticket_input=ticket_input) -> None:
                ticket_value = str(ticket_input.value or "").strip()
                if not ticket_value:
                    ui.notify("Enter a ticket ID before building a review package.")
                    return
                confirm_dialog.open()

            _attach_tooltip(
                ui,
                ui.button(
                    str(action.get("label", DAILY_DIGEST_BUILD_PACKAGE_ACTION_LABEL)),
                    on_click=_open_build_dialog,
                ).props("color=primary"),
                "Build a local review package; nothing is posted externally.",
            )

        quality_action = next(
            (action for action in actions if action.get("id") == QUALITY_HERO_REPORT_ACTION_ID),
            None,
        )
        if quality_action:
            ui.separator()
            ui.label("Quality-Hero report").classes("sgfx-panel-tagline")
            ui.label(
                "Generate the local Markdown report first. Attaching to Jira stays confirmation-gated per post."
            ).classes("sgfx-muted")
            anchor = str(quality_action.get("confluence_anchor", "")).strip()
            if anchor:
                ui.label(f"Confluence anchor: {anchor}").classes("sgfx-muted")
            default_ticket = str(quality_action.get("ticket_id_default", "")).strip().upper()
            recent_tickets = [
                str(item).strip().upper()
                for item in quality_action.get("recent_ticket_ids", [])
                if str(item).strip()
            ]
            ticket_options = []
            for candidate in [default_ticket, *recent_tickets]:
                if candidate and candidate not in ticket_options:
                    ticket_options.append(candidate)
            ticket_select = ui.select(
                ticket_options or [DAILY_DIGEST_TICKET_ID_PLACEHOLDER],
                value=default_ticket if default_ticket in ticket_options else (ticket_options[0] if ticket_options else None),
                label="Ticket picker",
            ).classes("full-width")
            ticket_override = ui.input(
                label="Ticket override",
                placeholder=str(quality_action.get("ticket_id_hint", DAILY_DIGEST_TICKET_ID_PLACEHOLDER)),
            ).classes("full-width")
            report_status = ui.label("No Quality-Hero report generated in this session.").classes("sgfx-muted")
            report_path_label = ui.label("").classes("sgfx-muted")
            report_html_label = ui.label("").classes("sgfx-muted")
            attach_status = ui.label("").classes("sgfx-muted")
            jira_link_host = ui.column().classes("full-width")
            report_state: dict[str, Any] = {}
            attach_button_holder: dict[str, Any] = {}

            def _selected_report_ticket() -> str:
                raw = str(ticket_override.value or ticket_select.value or "").strip().upper()
                return raw if _TICKET_ID_PATTERN.fullmatch(raw) else ""

            def _report_markdown_path() -> Path | None:
                value = str(report_state.get("markdown_path", "") or "").strip()
                if not value:
                    return None
                path = Path(value)
                return path if path.is_file() else None

            def _report_html_path() -> Path | None:
                value = str(report_state.get("html_path", "") or "").strip()
                if not value:
                    return None
                path = Path(value)
                return path if path.is_file() else None

            def _build_quality_report() -> None:
                ticket_value = _selected_report_ticket()
                if not ticket_value:
                    ui.notify("Choose or enter a Jira ticket before building the report.")
                    return
                try:
                    result = build_dashboard_quality_hero_report(
                        workspace=workspace,
                        profile_id=str(snapshot["profile_id"]),
                        ticket_id=ticket_value,
                    )
                except Exception as exc:  # noqa: BLE001
                    report_status.text = f"Quality-Hero report failed: {exc}"
                    ui.notify("Quality-Hero report failed.")
                    return
                report_state.clear()
                report_state.update(result)
                markdown_path = _report_markdown_path()
                report_status.text = (
                    f"Quality-Hero report {result.get('outcome', 'unknown')} "
                    f"(exit {result.get('exit_code', '?')}) for {ticket_value}."
                )
                report_path_label.text = f"Report: {markdown_path}" if markdown_path else "Report path unavailable."
                html_path = _report_html_path()
                report_html_label.text = f"HTML report: {html_path}" if html_path else "HTML report path unavailable."
                attach_status.text = "Report can now be attached after confirmation." if markdown_path else ""
                jira_link_host.clear()
                if markdown_path:
                    attach_button_holder["button"].enable()
                ui.notify("Quality-Hero report generated locally.")

            def _open_attach_dialog() -> None:
                ticket_value = _selected_report_ticket()
                markdown_path = _report_markdown_path()
                if not ticket_value:
                    ui.notify("Choose or enter a Jira ticket before attaching.")
                    return
                if markdown_path is None:
                    ui.notify("Generate the Quality-Hero report before attaching to Jira.")
                    return
                confirm_ticket.text = f"Ticket: {ticket_value}"
                confirm_path.text = f"Report path: {markdown_path}"
                confirm_size.text = f"Attachment size: {_size_label(markdown_path.stat().st_size)}"
                confirm_endpoint.text = f"Endpoint: {_dashboard_jira_attachment_endpoint(ticket_value)}"
                attach_dialog.open()

            with ui.dialog() as attach_dialog, ui.card():
                ui.label("Attach to Jira ticket").classes("sgfx-panel-title")
                ui.label("Post to Jira?").classes("sgfx-summary")
                ui.label("This posts the generated Markdown report only after this confirmation. HTML stays local.").classes(
                    "sgfx-summary"
                )
                confirm_ticket = ui.label("Ticket:").classes("sgfx-muted")
                confirm_path = ui.label("Report path:").classes("sgfx-muted")
                confirm_size = ui.label("Attachment size:").classes("sgfx-muted")
                confirm_endpoint = ui.label("Endpoint:").classes("sgfx-muted")
                ui.label("Manual review remains required. Decision: not approval — evidence only.").classes(
                    "sgfx-muted"
                )

                def _post_report_attachment() -> None:
                    ticket_value = _selected_report_ticket()
                    markdown_path = _report_markdown_path()
                    if not ticket_value or markdown_path is None:
                        ui.notify("Generate a report and choose a ticket before posting.")
                        return
                    try:
                        result = build_dashboard_quality_hero_report(
                            workspace=workspace,
                            profile_id=str(snapshot["profile_id"]),
                            ticket_id=ticket_value,
                            output_root=Path(str(report_state.get("output_root", ""))),
                            attach_ticket=ticket_value,
                            operator_confirmed=True,
                        )
                    except Exception as exc:  # noqa: BLE001
                        attach_status.text = f"Jira attachment failed: {exc}"
                        ui.notify("Jira attachment failed.")
                        attach_dialog.close()
                        return
                    report_state.clear()
                    report_state.update(result)
                    attachment_id = str(result.get("attachment_id", "") or "")
                    jira_url = str(result.get("jira_url", "") or "")
                    attach_status.text = (
                        f"Jira attachment {attachment_id or result.get('outcome', 'unknown')} "
                        f"for {ticket_value}."
                    )
                    jira_link_host.clear()
                    with jira_link_host:
                        if jira_url:
                            ui.link("Open Jira attachment", jira_url, new_tab=True).classes("sgfx-muted")
                        else:
                            ui.label("Jira attachment URL unavailable in response.").classes("sgfx-muted")
                    ui.notify("Quality-Hero report attached to Jira.")
                    attach_dialog.close()

                _attach_tooltip(
                    ui,
                    ui.button("Post", on_click=_post_report_attachment).props("color=primary"),
                    "Attach this local Markdown report to the selected Jira ticket.",
                )
                ui.button("Cancel", on_click=attach_dialog.close)

            _attach_tooltip(
                ui,
                ui.button(str(quality_action.get("label", QUALITY_HERO_REPORT_ACTION_LABEL)), on_click=_build_quality_report)
                .props("color=primary"),
                "Generate a local Quality-Hero Markdown report.",
            )
            attach_button = _attach_tooltip(
                ui,
                ui.button(QUALITY_HERO_REPORT_ATTACH_ACTION_LABEL, on_click=_open_attach_dialog),
                "Review the Jira ticket, report path, size, and endpoint before attaching.",
            )
            attach_button.disable()
            attach_button_holder["button"] = attach_button


def _render_team_digest_board_panel(ui: Any, snapshot: dict[str, Any]) -> None:
    page = next(page for page in snapshot["pages"] if page["id"] == "team-digest-board")
    payload = page.get("payload", {}) if isinstance(page.get("payload"), dict) else {}
    share = payload.get("share_decision", {}) if isinstance(payload.get("share_decision"), dict) else {}
    with ui.column().classes("sgfx-page-panel"):
        with ui.row().classes("items-center justify-between full-width"):
            ui.label(str(page["title"])).classes("sgfx-panel-title")
            _render_status_chip(ui, str(page.get("status", "unknown")))
        ui.label(str(page["tagline"])).classes("sgfx-panel-tagline")
        _render_page_confluence_anchors(ui, page)
        ownership_note = str(page.get("ownership_note", "")).strip()
        if ownership_note:
            ui.label(ownership_note).classes("sgfx-muted sgfx-ownership-note")
        ui.label(str(page.get("summary", ""))).classes("sgfx-summary")
        ui.label("Manual review remains required. Decision: not approval — evidence only.").classes("sgfx-muted")
        _render_empty_state_note(ui, page)
        ui.label("Sharing model trade-offs").classes("sgfx-panel-tagline")
        ui.label(str(share.get("rationale", ""))).classes("sgfx-muted")
        share_rows = [
            {
                "model": str(option.get("model", "")),
                "status": str(option.get("status", "unknown")),
                "tradeoff": str(option.get("tradeoff", "")),
            }
            for option in share.get("options", [])
            if isinstance(option, dict)
        ]
        if share_rows:
            _attach_tooltip(
                ui,
                ui.table(
                    columns=[
                        {"name": "model", "label": "Model", "field": "model", "align": "left"},
                        {"name": "status", "label": "Status", "field": "status", "align": "left"},
                        {"name": "tradeoff", "label": "Trade-off", "field": "tradeoff", "align": "left"},
                    ],
                    rows=share_rows,
                    row_key="model",
                ).classes("sgfx-table"),
                "The board defaults to local snapshot until a separate share/write gate opens.",
            )
        rows = [
            {
                "label": str(item.get("label", "")),
                "status": str(item.get("status", "")),
                "detail": str(item.get("detail", "")),
            }
            for item in page.get("items", [])
            if isinstance(item, dict)
        ]
        if rows:
            _attach_tooltip(
                ui,
                ui.table(
                    columns=[
                        {"name": "label", "label": "Row", "field": "label", "align": "left"},
                        {"name": "status", "label": "Status", "field": "status", "align": "left"},
                        {"name": "detail", "label": "Detail", "field": "detail", "align": "left"},
                    ],
                    rows=rows,
                    row_key="label",
                ).classes("sgfx-table"),
                "Team board rows are read from local digest and risk-score data.",
            )


def _render_operator_handoff_panel(ui: Any, snapshot: dict[str, Any], workspace: Path) -> None:
    page = next(page for page in snapshot["pages"] if page["id"] == "operator-handoff")
    payload = page.get("payload", {}) if isinstance(page.get("payload"), dict) else {}
    latest = payload.get("latest_handoff", {}) if isinstance(payload.get("latest_handoff"), dict) else {}
    with ui.column().classes("sgfx-page-panel"):
        with ui.row().classes("items-center justify-between full-width"):
            ui.label(str(page["title"])).classes("sgfx-panel-title")
            _render_status_chip(ui, str(page.get("status", "unknown")))
        ui.label(str(page["tagline"])).classes("sgfx-panel-tagline")
        _render_page_confluence_anchors(ui, page)
        ownership_note = str(page.get("ownership_note", "")).strip()
        if ownership_note:
            ui.label(ownership_note).classes("sgfx-muted sgfx-ownership-note")
        latest_label = ui.label(str(page.get("summary", ""))).classes("sgfx-summary")
        ui.label("Manual review remains required. Decision: not approval — evidence only.").classes("sgfx-muted")
        _render_empty_state_note(ui, page)
        rows = [
            {
                "label": str(item.get("label", "")),
                "status": str(item.get("status", "")),
                "detail": str(item.get("detail", "")),
            }
            for item in page.get("items", [])
            if isinstance(item, dict)
        ]
        if rows:
            _attach_tooltip(
                ui,
                ui.table(
                    columns=[
                        {"name": "label", "label": "Item", "field": "label", "align": "left"},
                        {"name": "status", "label": "Status", "field": "status", "align": "left"},
                        {"name": "detail", "label": "Detail", "field": "detail", "align": "left"},
                    ],
                    rows=rows,
                    row_key="label",
                ).classes("sgfx-table"),
                "Latest handoff rows are read from the operator-local handoff log.",
            )
        ui.label("Mark stopping point").classes("sgfx-panel-tagline")
        stopping_input = ui.input(
            "Stopping point",
            value=str(latest.get("stopping_point", "")),
            placeholder="Example: reviewed exterior diffs through right-front view",
        ).classes("full-width")
        next_step_input = ui.input(
            "Next step",
            value=str(latest.get("next_step", "")),
            placeholder="Example: continue with interior lighting screenshots",
        ).classes("full-width")
        ticket_input = ui.input(
            "Ticket",
            value=str(latest.get("ticket_id", "") or _dashboard_active_ticket_id(workspace)),
            placeholder="Optional ticket id",
        ).classes("full-width")
        note_input = ui.textarea(
            "Note",
            value=str(latest.get("note", "")),
            placeholder="Optional local note for the next operator",
        ).classes("full-width")
        status_label = ui.label("").classes("sgfx-muted")

        def _record_handoff() -> None:
            try:
                record = record_operator_handoff(
                    workspace=workspace,
                    profile_id=str(snapshot.get("profile_id", "")),
                    ticket_id=str(ticket_input.value or ""),
                    stopping_point=str(stopping_input.value or ""),
                    next_step=str(next_step_input.value or ""),
                    note=str(note_input.value or ""),
                )
            except Exception as exc:  # noqa: BLE001
                status_label.text = f"Handoff record failed: {exc}"
                ui.notify("Handoff record failed.")
                return
            latest_label.text = f"Latest handoff for {record['profile_id']}: {record['stopping_point']}"
            status_label.text = f"Handoff recorded locally: {record['handoff_id']}"
            ui.notify("Handoff recorded locally.")

        _attach_tooltip(
            ui,
            ui.button("Record handoff", on_click=_record_handoff).props("color=primary"),
            "Record the stopping point in operator-local state.",
        )


def _render_manual_review_panel(ui: Any, snapshot: dict[str, Any], workspace: Path) -> None:
    page = next(page for page in snapshot["pages"] if page["id"] == "manual-review")
    with ui.column().classes("sgfx-page-panel"):
        with ui.row().classes("items-center justify-between full-width"):
            ui.label(str(page["title"])).classes("sgfx-panel-title")
            _render_status_chip(ui, str(page.get("status", "unknown")))
        ui.label(str(page["tagline"])).classes("sgfx-panel-tagline")
        _render_page_confluence_anchors(ui, page)
        ui.label("Manual review remains required. Decision: not approval — evidence only.").classes("sgfx-summary")
        _render_empty_state_note(ui, page)
        if page.get("status") == _MANUAL_REVIEW_PENDING_VERDICT:
            templates = [
                item for item in page.get("payload", {}).get("review_templates", [])
                if isinstance(item, dict) and str(item.get("family_id", "")).strip()
            ]
            template_options = [str(item.get("family_id", "")) for item in templates]
            family_select = ui.select(
                template_options,
                value=str(page.get("payload", {}).get("default_family_id", "")),
                label="Family",
            ).classes("full-width")
            selected_template = next(
                (
                    item for item in templates
                    if str(item.get("family_id", "")) == str(page.get("payload", {}).get("default_family_id", ""))
                ),
                {},
            )
            if selected_template:
                ui.label(str(selected_template.get("title", ""))).classes("sgfx-muted")

            def _start_session() -> None:
                _ensure_manual_review_dashboard_session(
                    profile_id=str(snapshot["profile_id"]),
                    workspace=workspace,
                    family_id=str(family_select.value or ""),
                )
                ui.notify("Car review session started locally.")

            _attach_tooltip(
                ui,
                ui.button("Start new car review", on_click=_start_session).props("flat no-caps"),
                "Create the local family-template review session before recording step evidence.",
            )
        review_assist = page.get("payload", {}).get("review_assist", {})
        if isinstance(review_assist, dict) and review_assist.get("steps"):
            with ui.expansion("Review Assist", icon="rule").classes("sgfx-step"):
                ui.label(str(review_assist.get("summary", ""))).classes("sgfx-summary")
                ui.label("Suggested starting points only; operator confirms or changes every verdict below.").classes(
                    "sgfx-muted"
                )
                assist_rows = [
                    {
                        "step": str(step.get("title", "")),
                        "suggested": str(step.get("suggested_verdict", "")),
                        "status": str(step.get("auto_check_status", "")),
                        "reason": str(step.get("suggestion_reason", "")),
                    }
                    for step in review_assist.get("steps", [])
                    if isinstance(step, dict)
                ]
                if assist_rows:
                    ui.table(
                        columns=[
                            {"name": "step", "label": "Step", "field": "step", "align": "left"},
                            {"name": "suggested", "label": "Starting Point", "field": "suggested", "align": "left"},
                            {"name": "status", "label": "Evidence", "field": "status", "align": "left"},
                            {"name": "reason", "label": "Reason", "field": "reason", "align": "left"},
                        ],
                        rows=assist_rows,
                        row_key="step",
                    ).classes("sgfx-table")
        checklist = page.get("payload", {}).get("evidence_checklist", [])
        if isinstance(checklist, list) and checklist:
            with ui.expansion("Evidence checklist", icon="checklist").classes("sgfx-step"):
                for item in checklist:
                    if isinstance(item, dict):
                        ui.label(f"{item.get('status', 'not_run')} · {item.get('label', '')}").classes("sgfx-muted")
        for step in page["payload"]["steps"]:
            slug = str(step.get("slug", ""))
            with ui.expansion(str(step.get("title", slug)), icon="fact_check").classes("sgfx-step"):
                focus = ", ".join(str(item) for item in step.get("review_focus", []) if str(item).strip())
                if focus:
                    ui.label(f"Review focus: {focus}").classes("sgfx-summary")
                ui.label(str(step.get("evidence_prompt", ""))).classes("sgfx-muted")
                current_verdict = str(step.get("verdict", "")).strip()
                evidence_status = str(step.get("evidence_status", step.get("suggestion_status", ""))).strip()
                suggestion_reason = str(step.get("suggestion_reason", "")).strip()
                if evidence_status in {"available", "missing"}:
                    evidence_label = "Evidence available" if evidence_status == "available" else "Evidence missing"
                    ui.label(
                        f"{evidence_label}. Manual review remains required. {suggestion_reason}".strip()
                    ).classes("sgfx-muted")
                auto_status = str(step.get("auto_check_status", "")).strip()
                auto_summary = str(step.get("auto_check_summary", "")).strip()
                auto_kind = str(step.get("auto_check_kind", "")).strip()
                if auto_status and auto_status != "not_run" and auto_summary:
                    prefix = f"Auto-check {auto_status}"
                    if auto_kind:
                        prefix = f"{prefix} · {auto_kind}"
                    ui.label(f"{prefix}: {auto_summary}").classes("sgfx-muted")
                    ui.label("Operator records the manual-review verdict; this evidence is not approval.").classes("sgfx-muted")
                verdict_value = (
                    current_verdict
                    if current_verdict in MANUAL_REVIEW_RECORD_VERDICTS
                    else None
                )
                verdict = ui.select(
                    MANUAL_REVIEW_RECORD_VERDICTS,
                    value=verdict_value,
                    label="Verdict",
                ).classes("full-width")
                note = ui.textarea(label="Operator note", value=str(step.get("note", ""))).classes("full-width")
                recorded_at = str(step.get("recorded_at_utc", "")).strip()
                if _manual_review_step_recorded(step):
                    recorded_by_tool = step.get("recorded_by_tool", False)
                    ui.label(
                        f"Recorded: {current_verdict} | {recorded_at} | recorded_by_tool: {recorded_by_tool}"
                    ).classes("sgfx-muted")

                def _record(
                    slug: str = slug,
                    verdict=verdict,
                    note=note,
                ) -> None:
                    selected = str(verdict.value or "").strip()
                    if not selected:
                        ui.notify("Select a manual-review verdict before recording.")
                        return
                    record_manual_review_dashboard_step(
                        profile_id=str(snapshot["profile_id"]),
                        workspace=workspace,
                        step_slug=slug,
                        verdict=selected,
                        note=str(note.value or ""),
                        suggested_verdict="",
                    )
                    ui.notify("Manual-review evidence recorded locally.")

                _attach_tooltip(
                    ui,
                    ui.button("Record", on_click=_record).props("color=primary"),
                    "Record the operator verdict locally for this manual-review step.",
                )


def _render_jira_profile_tickets_card(
    ui: Any,
    profile_id: str,
    *,
    open_page: Callable[[str], None] | None = None,
) -> None:
    try:
        payload = search_jira_profile_tickets(profile_id, max_results=5, timeout_seconds=8)
    except Exception as exc:  # noqa: BLE001
        payload = {
            "status": "failed",
            "ticket_count": 0,
            "tickets": [],
            "summary": f"Jira tickets unavailable: {exc}",
            "settings_hint": "Check local Jira setup before retrying.",
            "read_only": True,
            "is_approval": False,
        }
    status = str(payload.get("status", "unknown"))
    tickets = [ticket for ticket in payload.get("tickets", []) if isinstance(ticket, dict)]
    with ui.column().classes("sgfx-jira-profile-card full-width"):
        ui.html('<span data-sgfx-jira-profile-tickets="true"></span>', sanitize=False)
        with ui.row().classes("items-center justify-between full-width"):
            ui.label("Active tickets for this profile").classes("sgfx-panel-tagline")
            _render_status_chip(ui, status)
        ui.label(str(payload.get("summary", "Jira tickets unavailable."))).classes("sgfx-summary")
        cache_status = str(payload.get("cache_status", "")).strip()
        if cache_status:
            ui.label(f"Read-only Jira REST query. Cache: {cache_status}; no Jira update is sent.").classes(
                "sgfx-muted"
            )
        if tickets:
            for ticket in tickets:
                key = str(ticket.get("key", "") or "")
                url = str(ticket.get("url", "") or "")
                with ui.row().classes("sgfx-jira-ticket-row full-width items-center"):
                    if url:
                        # H-29: raw <a target="_blank" rel="noopener"> instead of
                        # ui.link to guarantee browser click-through across NiceGUI
                        # versions. ui.link with new_tab=True did not consistently
                        # open the URL in real-browser walkthroughs (observed
                        # 2026-05-29 07:17 on the H-26 exe — clicks did nothing).
                        ui.html(
                            f'<a class="sgfx-jira-ticket-key" href="{html_escape(url)}" '
                            f'target="_blank" rel="noopener noreferrer">{html_escape(key)}</a>'
                        )
                    else:
                        ui.label(key).classes("sgfx-jira-ticket-key")
                    ui.label(str(ticket.get("status", "unknown"))).classes("sgfx-jira-status-pill")
                    ui.label(str(ticket.get("summary", ""))).classes("sgfx-muted")
        elif status != "available":
            ui.label("Jira tickets unavailable").classes("sgfx-summary")
            settings_hint = str(payload.get("settings_hint", "") or "")
            if settings_hint:
                ui.label(settings_hint).classes("sgfx-muted")
            if open_page is not None:
                _attach_tooltip(
                    ui,
                    ui.button("Open setup guidance", on_click=lambda: open_page("onboarding-guide")).props(
                        "flat no-caps dense"
                    ),
                    "Open local setup guidance. Jira credentials remain operator-local.",
                )
        else:
            ui.label("No open profile-matched Jira tickets were returned.").classes("sgfx-muted")


def _render_batch_full_qa_pass_panel(
    ui: Any,
    snapshot: dict[str, Any],
    workspace: Path,
    *,
    bmw_root: Path | str | None = None,
    open_profile: Callable[[str], None] | None = None,
    default_profile_ids: list[str] | tuple[str, ...] | None = None,
) -> None:
    page = next(page for page in snapshot["pages"] if page["id"] == "batch-full-qa-pass")
    profile_ids = [str(option.get("id", "")) for option in snapshot.get("profile_options", []) if str(option.get("id", ""))]
    active_profile = str(snapshot.get("profile_id", "") or "")
    requested_defaults = [str(item).strip() for item in (default_profile_ids or []) if str(item).strip()]
    default_profiles = [profile for profile in requested_defaults if profile in profile_ids]
    if not default_profiles:
        default_profiles = [active_profile] if active_profile in profile_ids else profile_ids[:1]
        for preferred in ("F70", "G65"):
            if preferred in profile_ids and preferred not in default_profiles:
                default_profiles.append(preferred)
            if len(default_profiles) >= 2:
                break
        if len(default_profiles) < 2:
            for candidate in profile_ids:
                if candidate not in default_profiles:
                    default_profiles.append(candidate)
                if len(default_profiles) >= 2:
                    break
    with ui.column().classes("sgfx-page-panel"):
        with ui.row().classes("items-center justify-between full-width"):
            ui.label(str(page["title"])).classes("sgfx-panel-title")
            _render_status_chip(ui, str(page.get("status", "unknown")))
        ui.label(str(page["tagline"])).classes("sgfx-panel-tagline")
        _render_page_confluence_anchors(ui, page)
        ui.label("Sequential execution: profile N finishes before profile N+1 starts.").classes("sgfx-summary")
        ui.label("Manual review remains required. Decision: not approval — evidence only.").classes("sgfx-muted")
        profiles_select = ui.select(
            profile_ids,
            value=default_profiles,
            label="Profiles",
        ).props("multiple use-chips outlined").classes("full-width")
        status_label = ui.label("Batch has not run in this dashboard session.").classes("sgfx-muted")
        current_label = ui.label("").classes("sgfx-summary")
        progress = ui.linear_progress(value=0).classes("full-width")
        progress.visible = False
        live_output = (
            ui.textarea(label="Current profile subprocess output", value="No subprocess output yet.")
            .props("readonly outlined")
            .classes("full-width sgfx-live-output")
        )
        live_output.visible = False
        result_host = ui.column().classes("full-width")
        timer_ref: dict[str, Any] = {"timer": None}
        job_ref: dict[str, Any] = {"job": None}

        def _stop_timer() -> None:
            _cancel_background_poll_timer(timer_ref.get("timer"))
            timer_ref["timer"] = None

        def _render_results(result: dict[str, Any]) -> None:
            result_host.clear()
            rows = [
                {
                    "profile": str(item.get("profile_id", "")),
                    "outcome": str(item.get("outcome", "")),
                    "risk_score": str(item.get("risk_score", "")),
                    "pending_review_count": str(item.get("pending_review_count", 0)),
                    "elapsed": str(item.get("elapsed_label", "")),
                }
                for item in result.get("results", [])
                if isinstance(item, dict)
            ]
            with result_host:
                if not rows:
                    ui.label("No profile results recorded yet.").classes("sgfx-muted")
                    return
                ui.table(
                    columns=[
                        {"name": "profile", "label": "Profile", "field": "profile", "align": "left"},
                        {"name": "outcome", "label": "Outcome", "field": "outcome", "align": "left"},
                        {"name": "risk_score", "label": "Risk Score", "field": "risk_score", "align": "left"},
                        {
                            "name": "pending_review_count",
                            "label": "Pending Review",
                            "field": "pending_review_count",
                            "align": "left",
                        },
                        {"name": "elapsed", "label": "Elapsed", "field": "elapsed", "align": "left"},
                    ],
                    rows=rows,
                    row_key="profile",
                ).classes("sgfx-table")
                with ui.row().classes("sgfx-batch-profile-links"):
                    for row in rows:
                        profile = str(row.get("profile", ""))
                        ui.link(
                            f"Open {profile}",
                            f"/?profile={quote(profile)}&full_qa_run=1",
                            new_tab=False,
                        ).classes("sgfx-muted")

        def _apply_result(result: dict[str, Any]) -> None:
            progress.visible = True
            live_output.visible = True
            percent = max(0, min(100, int(result.get("percent", 0) or 0)))
            progress.value = percent / 100
            current = str(result.get("current_profile", ""))
            current_index = result.get("current_index", 0)
            total = result.get("total_profiles", 0)
            elapsed = str(result.get("elapsed_label", "00:00"))
            typical = str(result.get("typical_range", _BATCH_FULL_QA_TYPICAL_RANGE_LABEL))
            current_label.text = (
                f"Profile {current_index}/{total}: {current} · Elapsed {elapsed} / {typical}"
                if current
                else f"Completed {result.get('completed_profiles', 0)}/{total} profile(s)."
            )
            status_label.text = str(result.get("summary", "Batch Full QA Pass running."))
            lines = [str(line) for line in result.get("stdout_tail_lines", []) if str(line).strip()]
            live_output.value = "\n".join(lines[-20:]) if lines else "No subprocess output yet."
            _render_results(result)
            if bool(result.get("completed", False)):
                _stop_timer()
                progress.value = 1.0
                start_button.enable()
                cancel_button.disable()

        def _poll() -> None:
            try:
                job = job_ref.get("job")
                if job is None:
                    _stop_timer()
                    return
                result = poll_dashboard_batch_full_qa_pass(job)
                if result is not None:
                    _apply_result(result)
            except RuntimeError as exc:
                if not _parent_slot_deleted(exc):
                    raise
                _stop_timer()

        def _start_timer() -> None:
            _stop_timer()
            timer_ref["timer"] = _start_background_poll_timer(1.0, _poll)

        def _start_batch() -> None:
            raw_profiles = profiles_select.value
            selected = raw_profiles if isinstance(raw_profiles, list) else [raw_profiles]
            profiles = [str(profile).strip() for profile in selected if str(profile).strip()]
            if not profiles:
                ui.notify("Select at least one profile before starting the batch.")
                return
            try:
                job_ref["job"] = start_dashboard_batch_full_qa_pass(
                    workspace=workspace,
                    profile_ids=profiles,
                    bmw_root=bmw_root,
                    trusted_tool_mode=True,
                )
            except Exception as exc:  # noqa: BLE001
                status_label.text = f"Batch Full QA Pass failed to start: {exc}"
                ui.notify("Batch Full QA Pass failed to start.")
                return
            status_label.text = f"Batch Full QA Pass started for {len(profiles)} profile(s)."
            progress.visible = True
            live_output.visible = True
            start_button.disable()
            cancel_button.enable()
            _start_timer()
            _poll()

        def _cancel_after_current() -> None:
            job = job_ref.get("job")
            if job is None:
                return
            result = request_cancel_dashboard_batch_full_qa_pass(job)
            cancel_button.disable()
            _apply_result(result)
            ui.notify("Batch will stop after the current profile.")

        with ui.row().classes("sgfx-full-qa-controls"):
            start_button = _attach_tooltip(
                ui,
                ui.button("Run selected profiles", on_click=_start_batch).props("color=primary"),
                "Start one Full QA Pass subprocess per selected profile, sequentially.",
            )
            cancel_button = _attach_tooltip(
                ui,
                ui.button("Cancel after current", on_click=_cancel_after_current),
                "Finish the current profile, then stop before starting the next one.",
            )
            cancel_button.disable()
        _render_results({"results": []})


def _render_full_qa_pass_panel(
    ui: Any,
    snapshot: dict[str, Any],
    workspace: Path,
    *,
    bmw_root: Path | str | None = None,
    open_page: Callable[[str], None] | None = None,
) -> None:
    running_navigation_message = "Action running — cancel first to navigate"
    page = next(page for page in snapshot["pages"] if page["id"] == "full-qa-pass")
    initial_payload = page.get("payload", {}) if isinstance(page.get("payload"), dict) else {}
    profile_id = str(snapshot["profile_id"])
    running_actions: set[str] = set()
    active_jobs: dict[str, dict[str, Any]] = {}
    try:
        from nicegui import context as nicegui_context

        dashboard_client = nicegui_context.client
    except Exception:
        dashboard_client = None
    wizard_state: dict[str, Any] = {
        "payload": initial_payload,
        "index": 0,
        "skipped": set(),
        "completed": set(),
        "auto_started": set(),
        "bulk_ack_queued": set(),
        "bulk_acknowledged": {},
        "bulk_ack_outcomes": {},
        "bulk_ack_drafts": {},
        "bulk_ack_values": {},
        "bulk_ack_high_risk_prompt": False,
        "bulk_handoff_text": "",
        "action_results": {},
        "running_step_id": "",
        "running_action_id": "",
        "done": False,
        "full_qa_notified": False,
        "run_history_recorded": False,
    }

    def _save_notifications_preference() -> None:
        enabled = bool(notifications_control.value)
        _write_dashboard_notifications_preference(workspace, enabled)
        try:
            ui.notify(f"Desktop notifications {'enabled' if enabled else 'disabled'}.")
        except RuntimeError as exc:
            if not _ignorable_nicegui_runtime_error(exc):
                raise

    with ui.column().classes("sgfx-page-panel"):
        with ui.row().classes("items-center justify-between full-width"):
            ui.label(str(page["title"])).classes("sgfx-panel-title")
            _render_status_chip(ui, str(initial_payload.get("status", "unknown")))
        ui.label(str(page["tagline"])).classes("sgfx-panel-tagline")
        _render_page_confluence_anchors(ui, page)
        ui.label(
            "Runs local evidence readers in order and stops before blocking issues. "
            "Confirmation-gated actions remain explicit."
        ).classes("sgfx-muted")
        ui.label(str(initial_payload.get("trusted_tool_mode_note", ""))).classes("sgfx-muted")
        ui.label(
            "Ramses may show a black offscreen-rendering window during screenshot capture; "
            "live output appears in the action panel."
        ).classes("sgfx-muted")
        _render_jira_profile_tickets_card(ui, profile_id, open_page=open_page)

        with ui.row().classes("sgfx-full-qa-controls"):
            trusted_control = ui.checkbox(
                "Automatic mode",
                value=bool(initial_payload.get("trusted_tool_mode", True)),
            ).classes("sgfx-automatic-mode-control")
            ui.label("Manual mode opt-out: switch Automatic mode off to confirm local actions one by one.").classes(
                "sgfx-muted"
            )
            notifications_control = ui.checkbox(
                "Desktop notifications",
                value=_dashboard_notifications_enabled(workspace),
            ).classes("sgfx-desktop-notifications-control")
            _attach_tooltip(
                ui,
                ui.button("Save notification setting", on_click=_save_notifications_preference).props(
                    "flat dense no-caps"
                ),
                "Store whether SGFX shows Windows notifications when long local work finishes.",
            )
            notice = ui.label("Full QA pass has not run in this dashboard session.").classes("sgfx-muted")
            resume_prompt_host = ui.column().classes("full-width")
            result_host = ui.column().classes("full-width")

        with ui.dialog() as wizard_viewer_dialog:
            with ui.card().classes("sgfx-viewer-dialog-card"):
                with ui.row().classes("items-center justify-between full-width"):
                    wizard_viewer_title = ui.label("Side-by-side screenshot review").classes("sgfx-panel-title")
                    ui.button("Close", on_click=wizard_viewer_dialog.close).props("flat dense no-caps")
                ui.label(
                    "Expected / actual / diff panes render below with synchronized zoom and pan controls. "
                    "Manual review remains required."
                ).classes("sgfx-muted")
                wizard_viewer_frame_host = ui.column().classes("sgfx-viewer-frame-host")

        def _open_wizard_screenshot_viewer(item_key: str, label: str = "") -> None:
            try:
                _materialize_screenshot_review_viewer_for_dashboard(profile_id, workspace, bmw_root=bmw_root)
            except Exception as exc:  # noqa: BLE001
                _notify_ui(f"Screenshot viewer generation failed: {exc}")
                return
            safe_url = html_escape(_screenshot_review_viewer_url(profile_id, item_key), quote=True)
            wizard_viewer_title.text = label or "Side-by-side screenshot review"
            wizard_viewer_frame_host.clear()
            with wizard_viewer_frame_host:
                ui.html(
                    f'<iframe data-sgfx-inline-viewer="true" class="sgfx-viewer-iframe" '
                    f'src="{safe_url}" title="Side-by-side screenshot review"></iframe>',
                    sanitize=False,
                ).classes("full-width")
            wizard_viewer_dialog.open()

        def _notify_ui(message: str) -> None:
            try:
                ui.notify(message)
            except RuntimeError as exc:
                if not _ignorable_nicegui_runtime_error(exc):
                    raise

        def _client_has_socket_connection() -> bool:
            if dashboard_client is None:
                return True
            return bool(getattr(dashboard_client, "has_socket_connection", True))

        def _append_activity(*, action: str, outcome: str = "ok", note: str = "") -> None:
            append_activity_entry(
                workspace,
                verb="ran",
                surface=f"full-qa-pass:{action}",
                profile=profile_id,
                outcome=outcome,
                note=note,
            )

        def _ack_timestamp() -> str:
            return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

        def _bulk_handoff_placeholder(timestamp: str) -> str:
            return (
                f"Full QA Pass completed for {profile_id} - automated steps passed; "
                f"acknowledgment items batch-confirmed at {timestamp}."
            )

        def _action_output_text(result: dict[str, Any]) -> str:
            if str(result.get("action_id", "")) == MISSING_ACTUAL_DIAGNOSTIC_ACTION_ID:
                return render_missing_actual_diagnostic_text(result)
            copied_evidence = result.get("copied_evidence", {}) if isinstance(result.get("copied_evidence"), dict) else {}
            sgfx_output = str(result.get("sgfx_output_root") or copied_evidence.get("output_root") or "").strip()
            traceback_payload = _pipeline_traceback(result)
            if traceback_payload:
                lines = [traceback_payload["summary"]]
                if sgfx_output:
                    lines.append(f"SGFX output: {sgfx_output}")
                return "\n".join(lines)
            stdout_lines = [str(line) for line in result.get("stdout_tail_lines", []) if str(line).strip()]
            if sgfx_output:
                stdout_lines.append(f"SGFX output: {sgfx_output}")
            if stdout_lines:
                return "\n".join(stdout_lines)
            paths = [
                str(result.get("stdout_path", "")).strip(),
                str(result.get("stderr_path", "")).strip(),
            ]
            log_hint = "\n".join(f"log: {path}" for path in paths if path)
            if log_hint:
                return f"Waiting for subprocess stdout/stderr...\n{log_hint}"
            return "Waiting for subprocess stdout/stderr..."

        def _scroll_live_output_to_bottom() -> None:
            _run_javascript_if_client_alive(
                ui,
                "setTimeout(() => {"
                "document.querySelectorAll('.sgfx-live-output textarea')"
                ".forEach((el) => { el.scrollTop = el.scrollHeight; });"
                "}, 0);",
            )

        def _typical_range_for_step(step: dict[str, Any]) -> str:
            step_id = str(step.get("id", ""))
            actions = [action for action in step.get("inline_actions", []) if isinstance(action, dict)]
            for action in actions:
                action_id = str(action.get("id", ""))
                if action_id == GENERATE_WORKBOOK_ACTION_ID:
                    return "typical 1-10 min"
                if action_id == SCREENSHOT_CAPTURE_ACTION_ID:
                    return "typical 2-10 min"
                if action_id == DAILY_DIGEST_BUILD_PACKAGE_ACTION_ID:
                    return _BUILD_PACKAGE_TYPICAL_RANGE_LABEL
            ranges = {
                "delivery-workbook-trigger": "typical 1-10 min",
                "screenshot-test-state": "typical 2-10 min",
                "operator-handoff": "typical <1 min",
            }
            return ranges.get(step_id, "typical <1 min")

        def _eta_text(*, elapsed: str = "00:00", typical: str = "typical <1 min") -> str:
            clean_typical = str(typical or "typical <1 min").strip()
            if clean_typical.casefold().startswith("typical "):
                clean_typical = "Typical " + clean_typical[8:]
            elif clean_typical:
                clean_typical = clean_typical[:1].upper() + clean_typical[1:]
            return f"Elapsed {elapsed or '00:00'} / {clean_typical}"

        def _start_subprocess_action(
            action: dict[str, Any],
            *,
            status_label: Any,
            eta_label: Any,
            progress: Any,
            live_output: Any,
            details_host: Any,
            visual_label: Any,
            visual_host: Any,
            completion_label: Any,
            cancel_button: Any | None = None,
            set_running_controls: Callable[[bool], None] | None = None,
            on_complete: Callable[[dict[str, Any]], None] | None = None,
        ) -> None:
            action_id = str(action.get("id", ""))
            if action_id in running_actions:
                return
            running_actions.add(action_id)
            wizard_state["running_action_id"] = action_id
            wizard_state["running_step_id"] = str(action.get("step_id", ""))
            current_payload = wizard_state["payload"] if isinstance(wizard_state.get("payload"), dict) else {}
            _persist_wizard_state(current_payload, reason="action_started", status="running")
            status_label.text = "running"
            eta_label.text = _eta_text(typical=str(action.get("typical_range", _typical_range_for_step({"inline_actions": [action]}))))
            completion_label.text = f"{action.get('label', 'Action')} running..."
            progress.visible = True
            progress.props("indeterminate")
            live_output.visible = True
            live_output.value = "Starting local subprocess; waiting for stdout/stderr..."
            details_host.clear()
            details_host.visible = False
            visual_label.visible = False
            visual_host.clear()
            visual_host.visible = False
            _scroll_live_output_to_bottom()
            if cancel_button is not None:
                cancel_button.visible = True
                cancel_button.enable()
            if set_running_controls is not None:
                set_running_controls(True)
            job_state: dict[str, Any] = {"job": None, "timer": None, "launch_timer": None}
            active_jobs[action_id] = job_state

            def _stop_launch_timer() -> None:
                _cancel_background_poll_timer(job_state.get("launch_timer"))
                job_state["launch_timer"] = None

            def _finish_start_failure(exc: Exception) -> None:
                _stop_launch_timer()
                active_jobs.pop(action_id, None)
                status_label.text = "failed"
                eta_label.text = _eta_text(typical=str(action.get("typical_range", "typical <1 min")))
                completion_label.text = f"{action.get('label', 'Action')} failed to start: {exc}"
                live_output.value = str(exc)
                details_host.clear()
                details_host.visible = False
                visual_label.visible = False
                visual_host.visible = False
                progress.visible = False
                if cancel_button is not None:
                    cancel_button.visible = False
                running_actions.discard(action_id)
                wizard_state["running_action_id"] = ""
                wizard_state["running_step_id"] = ""
                _persist_wizard_state(current_payload, reason="action_start_failed", status="in_progress")
                if set_running_controls is not None:
                    set_running_controls(False)
                _append_activity(action=action_id, outcome="error", note=str(exc))
                _notify_ui(f"{action.get('label', 'Action')} failed to start.")

            def _stop_timer() -> None:
                _cancel_background_poll_timer(job_state.get("timer"))
                job_state["timer"] = None
                active_jobs.pop(action_id, None)

            def _poll() -> None:
                try:
                    job = job_state.get("job")
                    if job is None:
                        _stop_timer()
                        return
                    poller = job_state.get("poller")
                    if poller is None:
                        return
                    label = str(job_state.get("label", "local action"))
                    result = poller(job)
                    if result is None:
                        return
                    live_output.value = _action_output_text(result)
                    eta_label.text = _eta_text(
                        elapsed=str(result.get("elapsed_label", "00:00")),
                        typical=str(result.get("typical_range", action.get("typical_range", "typical <1 min"))),
                    )
                    _render_action_technical_details(ui, result, details_host=details_host)
                    _render_action_visuals(
                        ui,
                        result,
                        visual_label=visual_label,
                        visual_host=visual_host,
                        open_screenshot_viewer=_open_wizard_screenshot_viewer,
                    )
                    _scroll_live_output_to_bottom()
                    if not bool(result.get("completed", True)):
                        completion_label.text = str(result.get("summary", f"{label} running."))
                        return
                    _stop_timer()
                    running_actions.discard(action_id)
                    wizard_state["running_action_id"] = ""
                    wizard_state["running_step_id"] = ""
                    progress.visible = False
                    if cancel_button is not None:
                        cancel_button.visible = False
                    if set_running_controls is not None:
                        set_running_controls(False)
                    outcome = str(result.get("status", "unknown"))
                    status_label.text = "passed" if outcome == "available" else outcome
                    completion_label.text = f"{action.get('label', 'Action')} {outcome}. {result.get('summary', '')}"
                    _append_activity(
                        action=action_id,
                        outcome="ok" if outcome == "available" else "unavailable",
                        note=str(result.get("summary", "")),
                    )
                    _notify_ui(f"{action.get('label', 'Action')} {outcome}.")
                    _notify_completion_safe(
                        title="SGFX Full QA Pass action finished",
                        message=f"{action.get('label', 'Action')} {outcome}.",
                        workspace=workspace,
                        action_id=action_id,
                        profile_id=profile_id,
                        evidence_path=str(result.get("sgfx_output_root", "")),
                        enabled=bool(notifications_control.value),
                        elapsed_seconds=result.get("elapsed_seconds"),
                        minimum_elapsed_seconds=LONG_RUNNING_NOTIFICATION_SECONDS,
                    )
                    if outcome == "available" and on_complete is not None:
                        on_complete(result)
                    else:
                        current_payload = wizard_state["payload"] if isinstance(wizard_state.get("payload"), dict) else {}
                        _persist_wizard_state(current_payload, reason="action_completed", status="in_progress")
                except RuntimeError as exc:
                    if not _ignorable_nicegui_runtime_error(exc):
                        raise
                    _stop_timer()
                    if set_running_controls is not None:
                        set_running_controls(False)

            def _launch_job() -> None:
                _stop_launch_timer()
                try:
                    if action_id == GENERATE_WORKBOOK_ACTION_ID:
                        job_state["job"] = start_delivery_workbook_generation(
                            profile_id=profile_id,
                            workspace=workspace,
                            bmw_root=bmw_root,
                            operator_confirmed=True,
                        )
                        job_state["poller"] = poll_delivery_workbook_generation
                        job_state["label"] = "delivery workbook generation"
                    elif action_id == SCREENSHOT_CAPTURE_ACTION_ID:
                        job_state["job"] = start_screenshot_capture(
                            profile_id=profile_id,
                            workspace=workspace,
                            bmw_root=bmw_root,
                            operator_confirmed=True,
                        )
                        job_state["poller"] = poll_screenshot_capture
                        job_state["label"] = "screenshot capture"
                    else:
                        raise ValueError(f"Unsupported Full QA Pass action: {action_id}")
                except Exception as exc:  # noqa: BLE001
                    _finish_start_failure(exc)
                    return
                _append_activity(action=action_id, note=f"Started {job_state['label']} from Full QA Pass.")
                job_state["timer"] = _start_background_poll_timer(1.0, _poll)

            job_state["launch_timer"] = _start_background_poll_timer(0.1, _launch_job)

        def _cancel_subprocess_action(
            action: dict[str, Any],
            *,
            status_label: Any,
            eta_label: Any,
            progress: Any,
            live_output: Any,
            details_host: Any,
            visual_label: Any,
            visual_host: Any,
            completion_label: Any,
            cancel_button: Any,
            set_running_controls: Callable[[bool], None] | None = None,
        ) -> None:
            action_id = str(action.get("id", ""))
            job_state = active_jobs.get(action_id)
            if not job_state or job_state.get("job") is None:
                if job_state is not None:
                    _cancel_background_poll_timer(job_state.get("launch_timer"))
                    active_jobs.pop(action_id, None)
                    running_actions.discard(action_id)
                    wizard_state["running_action_id"] = ""
                    wizard_state["running_step_id"] = ""
                    progress.visible = False
                    status_label.text = "incomplete"
                    eta_label.text = _eta_text(typical=str(action.get("typical_range", "typical <1 min")))
                    live_output.visible = True
                    live_output.value = "Canceled before local subprocess started."
                    details_host.clear()
                    details_host.visible = False
                    visual_label.visible = False
                    visual_host.visible = False
                    if set_running_controls is not None:
                        set_running_controls(False)
                    _append_activity(action=action_id, outcome="unavailable", note="Action canceled before subprocess start.")
                    current_payload = wizard_state["payload"] if isinstance(wizard_state.get("payload"), dict) else {}
                    _persist_wizard_state(current_payload, reason="action_canceled", status="in_progress")
                    completion_label.text = "Action canceled before local subprocess started."
                else:
                    completion_label.text = "No running action is available to cancel."
                cancel_button.visible = False
                return
            try:
                if action_id == GENERATE_WORKBOOK_ACTION_ID:
                    result = cancel_delivery_workbook_generation(job_state["job"])
                elif action_id == SCREENSHOT_CAPTURE_ACTION_ID:
                    result = cancel_screenshot_capture(job_state["job"])
                else:
                    raise ValueError(f"Unsupported Full QA Pass action: {action_id}")
                _cancel_background_poll_timer(job_state.get("timer"))
                active_jobs.pop(action_id, None)
                running_actions.discard(action_id)
                wizard_state["running_action_id"] = ""
                wizard_state["running_step_id"] = ""
                progress.visible = False
                cancel_button.visible = False
                status_label.text = "incomplete"
                eta_label.text = _eta_text(
                    elapsed=str(result.get("elapsed_label", "00:00")),
                    typical=str(result.get("typical_range", action.get("typical_range", "typical <1 min"))),
                )
                completion_label.text = str(result.get("summary", "Action canceled."))
                live_output.value = _action_output_text(result)
                _render_action_technical_details(ui, result, details_host=details_host)
                _render_action_visuals(
                    ui,
                    result,
                    visual_label=visual_label,
                    visual_host=visual_host,
                    open_screenshot_viewer=_open_wizard_screenshot_viewer,
                )
                _scroll_live_output_to_bottom()
                if set_running_controls is not None:
                    set_running_controls(False)
                _append_activity(action=action_id, outcome="unavailable", note=completion_label.text)
                current_payload = wizard_state["payload"] if isinstance(wizard_state.get("payload"), dict) else {}
                _persist_wizard_state(current_payload, reason="action_canceled", status="in_progress")
                _notify_ui(completion_label.text)
            except Exception as exc:  # noqa: BLE001
                status_label.text = "failed"
                completion_label.text = f"Cancel failed: {exc}"
                if set_running_controls is not None:
                    set_running_controls(False)
                _append_activity(action=action_id, outcome="error", note=str(exc))

        def _invoke_operator_action(
            action: dict[str, Any],
            *,
            status_label: Any,
            completion_label: Any,
            stopping_point: str = "",
            next_step: str = "",
        ) -> None:
            action_id = str(action.get("id", ""))
            try:
                if action_id == "risk-reviewed":
                    _append_activity(action=action_id, note=str(action.get("summary", "")))
                    status_label.text = "passed"
                    completion_label.text = "Risk signals were marked reviewed for this local pass."
                elif action_id == "manual-review-recorded":
                    assist = build_manual_review_assist(profile_id, workspace=workspace)
                    focus_count = len(assist.get("operator_focus_steps", []))
                    status_label.text = "passed" if focus_count == 0 else "incomplete"
                    completion_label.text = (
                        "Manual-review state has recorded verdicts for this pass."
                        if focus_count == 0
                        else f"Manual-review state still has {focus_count} item(s) needing operator focus."
                    )
                    _append_activity(action=action_id, outcome="ok" if focus_count == 0 else "unavailable")
                elif action_id == "record-handoff":
                    record_operator_handoff(
                        workspace=workspace,
                        profile_id=profile_id,
                        ticket_id=str(snapshot.get("active_ticket_id", "")),
                        stopping_point=stopping_point or "Full QA Pass operator stopping point.",
                        next_step=next_step or "Continue the remaining Full QA Pass items.",
                    )
                    _append_activity(action=action_id, note="Recorded local stopping point from Full QA Pass.")
                    status_label.text = "passed"
                    completion_label.text = "Local operator handoff recorded."
                else:
                    raise ValueError(f"Unsupported operator action: {action_id}")
                _notify_ui(str(completion_label.text))
            except Exception as exc:  # noqa: BLE001
                status_label.text = "failed"
                completion_label.text = f"{action.get('label', 'Action')} failed: {exc}"
                _append_activity(action=action_id, outcome="error", note=str(exc))
                _notify_ui(f"{action.get('label', 'Action')} failed.")

        def _open_target_page(target_page: str) -> None:
            if open_page is not None:
                open_page(target_page)
                return
            _notify_ui(f"Open {target_page} from the sidebar.")

        def _safe_int(value: object) -> int:
            try:
                return int(value or 0)
            except (TypeError, ValueError):
                return 0

        def _full_qa_display_status(step: dict[str, Any]) -> str:
            status = str(step.get("status", "unknown"))
            step_payload = step.get("payload", {}) if isinstance(step.get("payload"), dict) else {}
            if str(step.get("id", "")) == "screenshot-test-state":
                expected = _safe_int(step_payload.get("expected_count"))
                actual = _safe_int(step_payload.get("actual_count"))
                diff = _safe_int(step_payload.get("diff_count"))
                sg_captured = _safe_int(step_payload.get("sg_perspectives_screenshot_count"))
                if expected > 0 and actual == 0 and diff == 0 and sg_captured == 0:
                    return "incomplete"
            return status

        def _full_qa_effective_status(step: dict[str, Any]) -> str:
            step_id = str(step.get("id", ""))
            if step_id in wizard_state["bulk_acknowledged"]:
                return str(wizard_state["bulk_ack_outcomes"].get(step_id, "acknowledged_via_bulk_confirm"))
            if step_id in wizard_state["skipped"]:
                return "skipped"
            if step_id in wizard_state["bulk_ack_queued"]:
                return "incomplete_but_queued_for_acknowledge"
            if step_id in wizard_state["completed"]:
                return "passed"
            return _full_qa_display_status(step)

        def _payload_steps(payload: dict[str, Any]) -> list[dict[str, Any]]:
            return [step for step in payload.get("steps", []) if isinstance(step, dict)]

        def _current_step_id(steps: list[dict[str, Any]]) -> str:
            index = _safe_int(wizard_state.get("index"))
            if 0 <= index < len(steps):
                return str(steps[index].get("id", ""))
            return ""

        def _serialize_wizard_state(payload: dict[str, Any], *, status: str, reason: str) -> dict[str, Any]:
            steps = _payload_steps(payload)
            return {
                "schema_version": 1,
                "profile_id": profile_id,
                "workspace": str(workspace),
                "status": status,
                "reason": reason,
                "saved_at_utc": _utc_now(),
                "current_step_index": _safe_int(wizard_state.get("index")),
                "current_step_id": _current_step_id(steps),
                "completed_step_ids": sorted(str(item) for item in wizard_state["completed"]),
                "skipped_step_ids": sorted(str(item) for item in wizard_state["skipped"]),
                "bulk_ack_queued_step_ids": sorted(str(item) for item in wizard_state["bulk_ack_queued"]),
                "bulk_acknowledged": dict(wizard_state["bulk_acknowledged"]),
                "bulk_ack_outcomes": dict(wizard_state["bulk_ack_outcomes"]),
                "bulk_ack_values": dict(wizard_state["bulk_ack_values"]),
                "running_step_id": str(wizard_state.get("running_step_id", "")),
                "running_action_id": str(wizard_state.get("running_action_id", "")),
                "full_qa_notified": bool(wizard_state.get("full_qa_notified")),
                "run_history_recorded": bool(wizard_state.get("run_history_recorded")),
                "step_outcomes": [
                    {
                        "step_id": str(step.get("id", "")),
                        "label": str(step.get("label", "")),
                        "status": _full_qa_effective_status(step),
                    }
                    for step in steps
                ],
                "payload": payload,
            }

        def _persist_wizard_state(payload: dict[str, Any], *, reason: str, status: str | None = None) -> None:
            if not _payload_steps(payload):
                return
            state_status = status or (
                "completed"
                if bool(wizard_state.get("done"))
                else "running"
                if running_actions
                else "in_progress"
            )
            _write_full_qa_wizard_state(
                profile_id,
                _serialize_wizard_state(payload, status=state_status, reason=reason),
            )

        def _mark_interrupted_step(payload: dict[str, Any], step_id: str, action_id: str) -> None:
            for step in _payload_steps(payload):
                if str(step.get("id", "")) != step_id:
                    continue
                step["status"] = "interrupted"
                step["source_status"] = "interrupted"
                step["summary"] = (
                    f"{step.get('label', 'Step')} was interrupted before the local action completed. "
                    "Re-run this step before treating it as evidence."
                )
                step_payload = step.get("payload", {}) if isinstance(step.get("payload"), dict) else {}
                step_payload["status"] = "interrupted"
                step_payload["summary"] = str(step["summary"])
                step_payload["interrupted_action_id"] = action_id
                step["payload"] = step_payload
                break

        def _should_queue_bulk_ack(step: dict[str, Any]) -> bool:
            step_id = str(step.get("id", ""))
            if step_id not in _FULL_QA_DRAFT_STEP_IDS:
                return False
            if step_id in wizard_state["skipped"] or step_id in wizard_state["completed"]:
                return False
            if step_id in wizard_state["bulk_acknowledged"]:
                return False
            status = _full_qa_display_status(step)
            if status in {"failed", "skipped", "unavailable"}:
                return False
            return True

        def _ensure_bulk_ack_drafts(payload: dict[str, Any]) -> None:
            steps = _payload_steps(payload)
            computed = _full_qa_bulk_ack_drafts(profile_id, steps)
            drafts = wizard_state["bulk_ack_drafts"]
            values = wizard_state["bulk_ack_values"]
            queued = set(wizard_state["bulk_ack_queued"])
            acknowledged = set(wizard_state["bulk_acknowledged"])
            for store_name in ("bulk_ack_drafts", "bulk_ack_values"):
                store = wizard_state[store_name]
                for step_id in list(store):
                    if step_id not in queued and step_id not in acknowledged:
                        store.pop(step_id, None)
            for step_id in queued:
                if step_id not in drafts:
                    draft = computed.get(step_id) or {
                        "step_id": step_id,
                        "label": f"{step_id} draft",
                        "level": "unknown",
                        "reason": "draft unavailable",
                        "text": "",
                        "draft_available": False,
                    }
                    drafts[step_id] = draft
                values.setdefault(step_id, str(drafts.get(step_id, {}).get("text", "")))

        def _bulk_ack_outcome(step_id: str, value: str) -> str:
            draft = wizard_state["bulk_ack_drafts"].get(step_id, {})
            draft_text = str(draft.get("text", "")).strip()
            if not bool(draft.get("draft_available", False)) or not draft_text:
                return "confirmed_via_bulk_without_review"
            if value.strip() != draft_text:
                return "operator_overrode_draft"
            return "confirmed_via_bulk_with_tool_draft"

        def _risk_draft_is_high() -> bool:
            draft = wizard_state["bulk_ack_drafts"].get("risk-score", {})
            return str(draft.get("level", "")).strip().casefold() == "high"

        def _sync_bulk_ack_queue(payload: dict[str, Any]) -> None:
            if not bool(payload.get("trusted_tool_mode", False)):
                wizard_state["bulk_ack_queued"].clear()
                wizard_state["bulk_ack_drafts"].clear()
                wizard_state["bulk_ack_values"].clear()
                wizard_state["bulk_ack_high_risk_prompt"] = False
                return
            queued: set[str] = set()
            for step in _payload_steps(payload):
                if _should_queue_bulk_ack(step):
                    queued.add(str(step.get("id", "")))
            wizard_state["bulk_ack_queued"] = queued
            if not queued:
                wizard_state["bulk_ack_high_risk_prompt"] = False

        def _bulk_ack_queued_steps(payload: dict[str, Any]) -> list[dict[str, Any]]:
            acknowledged = wizard_state["bulk_acknowledged"]
            return [
                step
                for step in _payload_steps(payload)
                if str(step.get("id", "")) in wizard_state["bulk_ack_queued"]
                and str(step.get("id", "")) not in acknowledged
            ]

        def _bulk_acknowledged_steps(payload: dict[str, Any]) -> list[dict[str, Any]]:
            acknowledged = wizard_state["bulk_acknowledged"]
            return [step for step in _payload_steps(payload) if str(step.get("id", "")) in acknowledged]

        def _schedule_full_qa_notification(notification: dict[str, str], payload: dict[str, Any]) -> None:
            timer_ref: dict[str, Any] = {"timer": None}

            def _send_notification() -> None:
                _cancel_background_poll_timer(timer_ref.get("timer"))
                timer_ref["timer"] = None
                if bool(wizard_state.get("full_qa_notified")):
                    return
                if running_actions or not bool(wizard_state.get("done")):
                    return
                if not _client_has_socket_connection():
                    return
                _notify_completion_safe(
                    title=notification["title"],
                    message=notification["message"],
                    workspace=workspace,
                    action_id="full-qa-pass",
                    profile_id=profile_id,
                    evidence_path=str(payload.get("workspace", "")),
                    enabled=bool(notifications_control.value),
                )
                wizard_state["full_qa_notified"] = True
                _persist_wizard_state(payload, reason="notification_sent", status="completed")

            timer_ref["timer"] = _start_background_poll_timer(2.0, _send_notification)

        def _record_run_history_once(payload: dict[str, Any]) -> None:
            if bool(wizard_state.get("run_history_recorded")):
                return
            try:
                record_full_qa_run_history(profile_id, payload)
            except OSError:
                return
            wizard_state["run_history_recorded"] = True
            _dashboard_changed_profiles.cache_clear()
            _persist_wizard_state(payload, reason="run_history_recorded", status="completed")

        def _reset_wizard_run_state(payload: dict[str, Any]) -> None:
            wizard_state["payload"] = payload
            wizard_state["index"] = 0
            wizard_state["skipped"].clear()
            wizard_state["completed"].clear()
            wizard_state["auto_started"].clear()
            wizard_state["bulk_ack_queued"].clear()
            wizard_state["bulk_acknowledged"].clear()
            wizard_state["bulk_ack_outcomes"].clear()
            wizard_state["bulk_ack_drafts"].clear()
            wizard_state["bulk_ack_values"].clear()
            wizard_state["bulk_ack_high_risk_prompt"] = False
            wizard_state["bulk_handoff_text"] = ""
            wizard_state["action_results"].clear()
            wizard_state["running_step_id"] = ""
            wizard_state["running_action_id"] = ""
            wizard_state["done"] = False
            wizard_state["full_qa_notified"] = False
            wizard_state["run_history_recorded"] = False

        def _restore_wizard_state(saved_state: dict[str, Any]) -> dict[str, Any]:
            payload = saved_state.get("payload", {}) if isinstance(saved_state.get("payload"), dict) else {}
            _reset_wizard_run_state(payload)
            wizard_state["index"] = _safe_int(saved_state.get("current_step_index"))
            wizard_state["completed"].update(str(item) for item in saved_state.get("completed_step_ids", []))
            wizard_state["skipped"].update(str(item) for item in saved_state.get("skipped_step_ids", []))
            wizard_state["bulk_ack_queued"].update(
                str(item) for item in saved_state.get("bulk_ack_queued_step_ids", [])
            )
            if isinstance(saved_state.get("bulk_acknowledged"), dict):
                wizard_state["bulk_acknowledged"].update(saved_state["bulk_acknowledged"])
            if isinstance(saved_state.get("bulk_ack_outcomes"), dict):
                wizard_state["bulk_ack_outcomes"].update(saved_state["bulk_ack_outcomes"])
            if isinstance(saved_state.get("bulk_ack_values"), dict):
                wizard_state["bulk_ack_values"].update(saved_state["bulk_ack_values"])
            wizard_state["full_qa_notified"] = bool(saved_state.get("full_qa_notified"))
            wizard_state["run_history_recorded"] = bool(saved_state.get("run_history_recorded"))
            status = str(saved_state.get("status", "")).strip().casefold()
            running_step_id = str(saved_state.get("running_step_id", "")).strip()
            running_action_id = str(saved_state.get("running_action_id", "")).strip()
            if status == "running" and running_step_id:
                _mark_interrupted_step(payload, running_step_id, running_action_id)
                if running_action_id:
                    wizard_state["auto_started"].add(running_action_id)
                steps = _payload_steps(payload)
                for index, step in enumerate(steps):
                    if str(step.get("id", "")) == running_step_id:
                        wizard_state["index"] = index
                        break
                wizard_state["done"] = False
            else:
                steps = _payload_steps(payload)
                wizard_state["done"] = bool(status == "completed" or wizard_state["index"] >= len(steps))
            return payload

        def _resume_saved_wizard_state() -> None:
            saved_state = _read_full_qa_wizard_state(profile_id)
            if not saved_state:
                _notify_ui("No saved Full QA Pass state is available.")
                return
            payload = _restore_wizard_state(saved_state)
            notice.text = f"Resumed Full QA Pass state saved at {saved_state.get('saved_at_utc', 'unknown time')}."
            _render_resume_prompt()
            _render_payload(payload, preserve_index=True)

        def _discard_saved_wizard_state() -> None:
            _delete_full_qa_wizard_state(profile_id)
            _render_resume_prompt()
            _reset_wizard_run_state(initial_payload)
            notice.text = "Saved Full QA Pass state discarded."
            _render_payload(initial_payload)

        def _render_resume_prompt() -> None:
            resume_prompt_host.clear()
            saved_state = _read_full_qa_wizard_state(profile_id)
            if not saved_state:
                return
            saved_at = str(saved_state.get("saved_at_utc", "unknown time"))
            status = str(saved_state.get("status", "unknown"))
            step_id = str(saved_state.get("current_step_id") or saved_state.get("running_step_id") or "unknown")
            with resume_prompt_host:
                with ui.column().classes("sgfx-resume-prompt"):
                    ui.label(f"Resume Full QA Pass for {profile_id}?").classes("sgfx-panel-tagline")
                    ui.label(f"Saved {saved_at}; status {status}; step {step_id}.").classes("sgfx-muted")
                    ui.label(
                        "Resume restores local progress. If a subprocess was active, that step is marked interrupted."
                    ).classes("sgfx-muted")
                    with ui.row().classes("sgfx-confirm-actions"):
                        ui.button("Resume", on_click=_resume_saved_wizard_state).props("color=primary")
                        ui.button("Discard", on_click=_discard_saved_wizard_state).props("flat")

        def _first_focus_index(steps: list[dict[str, Any]], *, start: int = 0) -> int:
            non_blocking = {
                "passed",
                "skipped",
                "incomplete_but_queued_for_acknowledge",
                "acknowledged_via_bulk_confirm",
                "confirmed_via_bulk_with_tool_draft",
                "operator_overrode_draft",
                "confirmed_via_bulk_without_review",
            }
            for index in range(max(0, start), len(steps)):
                if _full_qa_effective_status(steps[index]) not in non_blocking:
                    return index
            return len(steps)

        def _set_wizard_index(payload: dict[str, Any], *, start: int = 0) -> None:
            _sync_bulk_ack_queue(payload)
            steps = _payload_steps(payload)
            wizard_state["index"] = _first_focus_index(steps, start=start)
            wizard_state["done"] = wizard_state["index"] >= len(steps)

        def _replace_step_payload(step_id: str, result: dict[str, Any]) -> None:
            payload = wizard_state["payload"] if isinstance(wizard_state.get("payload"), dict) else {}
            steps = _payload_steps(payload)
            for step in steps:
                if str(step.get("id", "")) != step_id:
                    continue
                step_payload = step.get("payload", {}) if isinstance(step.get("payload"), dict) else {}
                merged = {**step_payload, **result}
                step["payload"] = merged
                step["source_status"] = str(result.get("status", step.get("source_status", "unknown")))
                if str(result.get("summary", "")).strip():
                    step["summary"] = str(result.get("summary", ""))
                if str(result.get("status", "")) == "available":
                    step["status"] = "available" if bool(result.get("manual_review_required", True)) else "passed"
                break

        def _step_has_diff_review(step: dict[str, Any]) -> bool:
            step_payload = step.get("payload", {}) if isinstance(step.get("payload"), dict) else {}
            return _safe_int(step_payload.get("diff_count")) > 0 or bool(step_payload.get("screenshot_review_rows"))

        def _handle_action_completed(step_id: str, result: dict[str, Any]) -> None:
            if step_id:
                wizard_state["action_results"][step_id] = result
                _replace_step_payload(step_id, result)
            trusted = bool((wizard_state.get("payload") or {}).get("trusted_tool_mode", False))
            diff_found = _safe_int(result.get("diff_count")) > 0 or bool(result.get("screenshot_review_rows"))
            if trusted or not diff_found:
                _mark_step_completed(step_id)
                return
            _render_payload(wizard_state["payload"], preserve_index=True)

        def _merge_missing_actual_diagnostic_result(step_id: str, result: dict[str, Any]) -> None:
            payload = wizard_state["payload"] if isinstance(wizard_state.get("payload"), dict) else {}
            steps = _payload_steps(payload)
            status = str(result.get("status", "unknown"))
            for step in steps:
                if str(step.get("id", "")) != step_id:
                    continue
                step_payload = step.get("payload", {}) if isinstance(step.get("payload"), dict) else {}
                step_payload["missing_actual_diagnostics"] = result
                step_payload["missing_candidate_count"] = max(
                    _safe_int(step_payload.get("missing_candidate_count")),
                    _safe_int(result.get("missing_actual_count")),
                )
                step["payload"] = step_payload
                step["source_status"] = status
                if str(result.get("summary", "")).strip():
                    step["summary"] = str(result.get("summary", ""))
                if status == "auto_fix_resolved":
                    step["status"] = "passed"
                elif bool(result.get("operator_confirmation_required", False)):
                    step["status"] = "confirmation_pending"
                else:
                    step["status"] = "incomplete"
                break
            wizard_state["action_results"][MISSING_ACTUAL_DIAGNOSTIC_ACTION_ID] = result
            _persist_wizard_state(payload, reason="diagnostic_chain_completed", status="in_progress")

        def _run_diagnostic_chain_action(
            action: dict[str, Any],
            *,
            prompt_overlay: Any,
            status_label: Any,
            eta_label: Any,
            progress: Any,
            live_output: Any,
            details_host: Any,
            visual_label: Any,
            visual_host: Any,
            completion_label: Any,
            set_running_controls: Callable[[bool], None] | None = None,
            operator_confirmed_read_refresh: bool = False,
            retry_capture: bool = False,
        ) -> None:
            if not bool(action.get("enabled", True)):
                completion_label.text = str(action.get("disabled_reason", "Diagnostic chain is not available."))
                return
            action_id = str(action.get("id", MISSING_ACTUAL_DIAGNOSTIC_ACTION_ID))
            running_actions.add(action_id)
            wizard_state["running_action_id"] = action_id
            wizard_state["running_step_id"] = str(action.get("step_id", ""))
            status_label.text = "running"
            eta_label.text = _eta_text(typical=str(action.get("typical_range", "typical <1 min")))
            completion_label.text = (
                "Running confirmed read-refresh and screenshot retry..."
                if operator_confirmed_read_refresh
                else "Building missing-actual diagnostic chain..."
            )
            progress.visible = True
            progress.props("indeterminate")
            live_output.visible = True
            live_output.value = (
                "Running operator-confirmed BMW Git/SVN read-refresh, then retrying screenshot capture..."
                if operator_confirmed_read_refresh
                else "Reading local screenshot state, diagnostic patterns, and test config..."
            )
            details_host.clear()
            details_host.visible = False
            visual_label.visible = False
            visual_host.clear()
            visual_host.visible = False
            if set_running_controls is not None:
                set_running_controls(True)

            def _execute_diagnostic_chain() -> dict[str, Any]:
                try:
                    project_root_text = str(action.get("project_root", "")).strip()
                    expected_root_text = str(action.get("expected_root", "")).strip()
                    if project_root_text:
                        project_root = Path(project_root_text).resolve()
                    else:
                        project = get_run_profile(profile_id, workspace, bmw_root=bmw_root)
                        project_root = project.source_project_root()
                    return run_missing_actual_diagnostic_chain(
                        profile_id=profile_id,
                        workspace=workspace,
                        bmw_root=bmw_root,
                        project_root=project_root,
                        expected_root=Path(expected_root_text).resolve() if expected_root_text else None,
                        candidate_roots=tuple(
                            Path(str(item)).resolve()
                            for item in action.get("candidate_roots", [])
                            if str(item).strip()
                        ),
                        diff_reference_roots=tuple(
                            Path(str(item)).resolve()
                            for item in action.get("diff_reference_roots", [])
                            if str(item).strip()
                        ),
                        output_root=_missing_actual_diagnostics_output_root(workspace, profile_id),
                        operator_confirmed_read_refresh=operator_confirmed_read_refresh,
                        retry_capture=retry_capture,
                        operator_confirmed_retry_capture=retry_capture,
                    )
                except Exception as exc:  # noqa: BLE001
                    return {
                        "action_id": MISSING_ACTUAL_DIAGNOSTIC_ACTION_ID,
                        "profile_id": profile_id,
                        "status": "failed",
                        "summary": f"Missing-actual diagnostic chain failed: {exc}",
                        "manual_review_required": True,
                        "is_approval": False,
                        "steps": [],
                    }

            def _clear_diagnostic_running_state() -> None:
                running_actions.discard(action_id)
                wizard_state["running_action_id"] = ""
                wizard_state["running_step_id"] = ""
                progress.visible = False
                if set_running_controls is not None:
                    set_running_controls(False)

            def _apply_diagnostic_result(result: dict[str, Any]) -> None:
                status = str(result.get("status", "unknown"))
                status_label.text = status
                completion_label.text = str(result.get("summary", "Missing-actual diagnostic chain recorded."))
                live_output.value = _action_output_text(result)
                _scroll_live_output_to_bottom()
                _merge_missing_actual_diagnostic_result(str(action.get("step_id", "")), result)
                if bool(result.get("operator_confirmation_required", False)) and not operator_confirmed_read_refresh:
                    def _confirm_followup(current: dict[str, Any] = action) -> None:
                        _hide_prompt_overlay(prompt_overlay)
                        _run_diagnostic_chain_action(
                            current,
                            prompt_overlay=prompt_overlay,
                            status_label=status_label,
                            eta_label=eta_label,
                            progress=progress,
                            live_output=live_output,
                            details_host=details_host,
                            visual_label=visual_label,
                            visual_host=visual_host,
                            completion_label=completion_label,
                            set_running_controls=set_running_controls,
                            operator_confirmed_read_refresh=True,
                            retry_capture=True,
                        )

                    def _show_followup_prompt() -> None:
                        prompt_overlay.clear()
                        prompt_overlay.visible = True
                        with prompt_overlay:
                            with ui.column().classes("sgfx-wizard-modal"):
                                ui.label("Confirm read-refresh and retry").classes("sgfx-panel-title")
                                ui.label(str(result.get("confirmation_message", ""))).classes("sgfx-summary")
                                ui.label(
                                    "This only runs read-refresh and screenshot retry. SVN writes stay locked."
                                ).classes("sgfx-muted")
                                paths = [str(path) for path in action.get("target_paths", []) if str(path).strip()]
                                if paths:
                                    ui.label("Target paths").classes("sgfx-panel-tagline")
                                    for path in paths:
                                        ui.label(path).classes("sgfx-muted")
                                with ui.row().classes("sgfx-wizard-modal-actions"):
                                    ui.button("Yes", on_click=lambda _event=None: _confirm_followup()).props(
                                        "color=primary"
                                    )
                                    ui.button("Cancel", on_click=lambda: _hide_prompt_overlay(prompt_overlay))

                    details_host.clear()
                    details_host.visible = True
                    with details_host:
                        ui.label("Read-refresh and retry are waiting for operator confirmation.").classes(
                            "sgfx-panel-tagline"
                        )
                        ui.label(str(result.get("confirmation_message", ""))).classes("sgfx-muted")
                        ui.button(
                            "Run read-refresh and retry",
                            on_click=lambda _event=None: _show_followup_prompt(),
                        ).props(
                            "color=primary"
                        )
                _append_activity(
                    action=action_id,
                    outcome="error" if status == "failed" else "ok",
                    note=str(result.get("summary", "")),
                )
                _notify_ui(f"Missing-actual diagnostic chain {status}.")

            if operator_confirmed_read_refresh:
                worker_state: dict[str, Any] = {"completed": False, "result": None, "timer": None}

                def _worker() -> None:
                    worker_state["result"] = _execute_diagnostic_chain()
                    worker_state["completed"] = True

                def _poll_worker() -> None:
                    if not bool(worker_state.get("completed", False)):
                        return
                    _cancel_background_poll_timer(worker_state.get("timer"))
                    worker_state["timer"] = None
                    _clear_diagnostic_running_state()
                    result = worker_state.get("result")
                    if isinstance(result, dict):
                        _apply_diagnostic_result(result)

                threading.Thread(target=_worker, name="sgfx-missing-actual-diagnostics", daemon=True).start()
                worker_state["timer"] = _start_background_poll_timer(0.5, _poll_worker)
                return

            result = _execute_diagnostic_chain()
            _clear_diagnostic_running_state()
            _apply_diagnostic_result(result)

        def _mark_step_completed(step_id: str) -> None:
            if step_id:
                wizard_state["completed"].add(step_id)
            payload = wizard_state["payload"] if isinstance(wizard_state.get("payload"), dict) else {}
            _sync_bulk_ack_queue(payload)
            steps = _payload_steps(payload)
            current_index = _safe_int(wizard_state.get("index"))
            wizard_state["index"] = _first_focus_index(steps, start=current_index + 1)
            wizard_state["done"] = wizard_state["index"] >= len(steps)
            _render_payload(payload, preserve_index=True)

        def _confirm_all_queued(draft_values: dict[str, str], *, require_high_risk_confirm: bool = True) -> None:
            payload = wizard_state["payload"] if isinstance(wizard_state.get("payload"), dict) else {}
            _sync_bulk_ack_queue(payload)
            queued_steps = _bulk_ack_queued_steps(payload)
            if not queued_steps:
                return
            _ensure_bulk_ack_drafts(payload)
            wizard_state["bulk_ack_values"].update({key: str(value or "") for key, value in draft_values.items()})
            if _risk_draft_is_high() and require_high_risk_confirm:
                wizard_state["bulk_ack_high_risk_prompt"] = True
                _render_payload(payload, preserve_index=True)
                return
            timestamp = _ack_timestamp()
            acknowledged = wizard_state["bulk_acknowledged"]
            outcomes = wizard_state["bulk_ack_outcomes"]
            final_values: dict[str, str] = {}
            for step in queued_steps:
                step_id = str(step.get("id", ""))
                value = str(wizard_state["bulk_ack_values"].get(step_id, "")).strip()
                draft = wizard_state["bulk_ack_drafts"].get(step_id, {})
                if not value:
                    value = str(draft.get("text", "") or _bulk_handoff_placeholder(timestamp)).strip()
                outcome = _bulk_ack_outcome(step_id, value)
                acknowledged[step_id] = timestamp
                outcomes[step_id] = outcome
                final_values[step_id] = value
                step["acknowledgment_status"] = outcome
                step["acknowledged_at_utc"] = timestamp
                step["acknowledgment_draft"] = str(draft.get("text", ""))
                step["acknowledgment_value"] = value
                if outcome == "operator_overrode_draft":
                    step["operator_override_text"] = value
                _append_activity(
                    action=f"bulk-acknowledge:{step_id}",
                    outcome="ok",
                    note=f"{outcome} at {timestamp}",
                )
            if any(str(step.get("id", "")) == "operator-handoff" for step in queued_steps):
                stopping_point = final_values.get("operator-handoff", "").strip() or _bulk_handoff_placeholder(timestamp)
                record_operator_handoff(
                    workspace=workspace,
                    profile_id=profile_id,
                    ticket_id=str(snapshot.get("active_ticket_id", "")),
                    stopping_point=stopping_point,
                    next_step="Review the Full QA Pass done summary and continue any listed follow-up.",
                    note="Batch acknowledgment recorded from Full QA Pass.",
                )
            wizard_state["bulk_ack_high_risk_prompt"] = False
            _sync_bulk_ack_queue(payload)
            _set_wizard_index(payload, start=len(_payload_steps(payload)))
            _render_payload(payload, preserve_index=True)

        def _skip_current_step() -> None:
            payload = wizard_state["payload"] if isinstance(wizard_state.get("payload"), dict) else {}
            steps = _payload_steps(payload)
            current_index = _safe_int(wizard_state.get("index"))
            if current_index >= len(steps):
                wizard_state["done"] = True
                _render_payload(payload, preserve_index=True)
                return
            step_id = str(steps[current_index].get("id", ""))
            wizard_state["skipped"].add(step_id)
            _append_activity(action=f"skip:{step_id}", outcome="ok", note="Operator skipped current wizard step.")
            wizard_state["index"] = _first_focus_index(steps, start=current_index + 1)
            wizard_state["done"] = wizard_state["index"] >= len(steps)
            _render_payload(payload, preserve_index=True)

        def _show_previous_step() -> None:
            payload = wizard_state["payload"] if isinstance(wizard_state.get("payload"), dict) else {}
            steps = _payload_steps(payload)
            current_index = _safe_int(wizard_state.get("index"))
            if not steps:
                return
            wizard_state["done"] = False
            wizard_state["index"] = max(0, min(current_index, len(steps)) - 1)
            _render_payload(payload, preserve_index=True)

        def _hide_prompt_overlay(prompt_overlay: Any) -> None:
            prompt_overlay.clear()
            prompt_overlay.visible = False

        def _show_prompt_overlay(
            prompt_overlay: Any,
            action: dict[str, Any],
            *,
            status_label: Any,
            eta_label: Any,
            progress: Any,
            live_output: Any,
            details_host: Any,
            visual_label: Any,
            visual_host: Any,
            completion_label: Any,
            cancel_button: Any,
            set_running_controls: Callable[[bool], None],
        ) -> None:
            def _confirm_start(current: dict[str, Any] = action) -> None:
                _hide_prompt_overlay(prompt_overlay)
                _start_subprocess_action(
                    current,
                    status_label=status_label,
                    eta_label=eta_label,
                    progress=progress,
                    live_output=live_output,
                    details_host=details_host,
                    visual_label=visual_label,
                    visual_host=visual_host,
                    completion_label=completion_label,
                    cancel_button=cancel_button,
                    set_running_controls=set_running_controls,
                    on_complete=lambda result, step_id=str(current.get("step_id", "")): _handle_action_completed(
                        step_id,
                        result,
                    ),
                )

            prompt_overlay.clear()
            prompt_overlay.visible = True
            with prompt_overlay:
                with ui.column().classes("sgfx-wizard-modal"):
                    ui.label("Confirm local tool action").classes("sgfx-panel-title")
                    ui.label(str(action.get("confirmation_message", ""))).classes("sgfx-summary")
                    paths = [str(path) for path in action.get("target_paths", []) if str(path).strip()]
                    if paths:
                        ui.label("Target paths").classes("sgfx-panel-tagline")
                        for path in paths:
                            ui.label(path).classes("sgfx-muted")
                    with ui.row().classes("sgfx-wizard-modal-actions"):
                        ui.button("Yes", on_click=lambda _event=None, current=action: _confirm_start(current)).props(
                            "color=primary"
                        )
                        ui.button("Cancel", on_click=lambda: _hide_prompt_overlay(prompt_overlay))

        def _render_action(
            action: dict[str, Any],
            *,
            status_label: Any,
            eta_label: Any,
            prompt_overlay: Any,
            auto_start_trusted: bool,
            action_buttons: list[Any],
            set_running_controls: Callable[[bool], None],
        ) -> None:
            label = str(action.get("label", "Action"))
            completion_label = ui.label(str(action.get("summary", ""))).classes("sgfx-muted")
            progress = ui.linear_progress(value=0).props("indeterminate").classes("full-width")
            progress.visible = False
            live_output = (
                ui.textarea(label="Live action output", value="No subprocess output yet.")
                .props("readonly outlined")
                .classes("full-width sgfx-live-output")
            )
            live_output.visible = False
            details_host = ui.column().classes("full-width sgfx-technical-details-host")
            details_host.visible = False
            visual_label = ui.label("Live visual output").classes("sgfx-panel-tagline")
            visual_label.visible = False
            visual_host = ui.row().classes("full-width sgfx-live-visuals")
            visual_host.visible = False
            cancel_button = ui.button(
                "Cancel running action",
                on_click=lambda _event=None, current=action: _cancel_subprocess_action(
                    current,
                    status_label=status_label,
                    eta_label=eta_label,
                    progress=progress,
                    live_output=live_output,
                    details_host=details_host,
                    visual_label=visual_label,
                    visual_host=visual_host,
                    completion_label=completion_label,
                    cancel_button=cancel_button,
                    set_running_controls=set_running_controls,
                ),
            )
            cancel_button.visible = False
            kind = str(action.get("kind", ""))
            if kind == "navigate":
                _attach_tooltip(
                    ui,
                    ui.button(
                        label,
                        on_click=lambda _event=None, target=str(action.get("target_page", "")): _open_target_page(
                            target
                        ),
                    ),
                    str(action.get("summary", "")),
                )
                return
            if kind == "handoff_form":
                form_host = ui.column().classes("full-width")
                form_host.visible = False

                def _show_form() -> None:
                    form_host.visible = True

                def _save_handoff() -> None:
                    _invoke_operator_action(
                        action,
                        status_label=status_label,
                        completion_label=completion_label,
                        stopping_point=str(stopping_input.value or ""),
                        next_step=str(next_input.value or ""),
                    )
                    if str(status_label.text) == "passed":
                        _mark_step_completed(str(action.get("step_id", "")))

                _attach_tooltip(ui, ui.button(label, on_click=_show_form), str(action.get("summary", "")))
                with form_host:
                    stopping_input = ui.textarea(
                        "Stopping point",
                        value=f"Stopped during Full QA Pass for {profile_id}.",
                    ).props("outlined").classes("full-width")
                    next_input = ui.input(
                        "Next step",
                        value="Continue remaining Full QA Pass items.",
                    ).props("outlined").classes("full-width")
                    ui.button("Save stopping point", on_click=_save_handoff).props("color=primary")
                return
            if kind in {"operator_ack", "verify_manual_review"}:
                def _run_operator_action(current: dict[str, Any] = action) -> None:
                    _invoke_operator_action(
                        current,
                        status_label=status_label,
                        completion_label=completion_label,
                    )
                    if str(status_label.text) == "passed":
                        _mark_step_completed(str(current.get("step_id", "")))

                _attach_tooltip(
                    ui,
                    ui.button(label, on_click=lambda _event=None, current=action: _run_operator_action(current)),
                    str(action.get("summary", "")),
                )
                return
            if kind == "diagnostic_chain":
                def _run_diagnostic_action(current: dict[str, Any] = action) -> None:
                    _run_diagnostic_chain_action(
                        current,
                        prompt_overlay=prompt_overlay,
                        status_label=status_label,
                        eta_label=eta_label,
                        progress=progress,
                        live_output=live_output,
                        details_host=details_host,
                        visual_label=visual_label,
                        visual_host=visual_host,
                        completion_label=completion_label,
                        set_running_controls=set_running_controls,
                    )

                button = _attach_tooltip(
                    ui,
                    ui.button(label, on_click=lambda _event=None, current=action: _run_diagnostic_action(current)),
                    str(action.get("summary", "")),
                )
                action_buttons.append(button)
                if not bool(action.get("enabled", True)):
                    button.disable()
                return
            if kind == "subprocess":
                def _show_prompt_or_start(current: dict[str, Any] = action) -> None:
                    if not bool(current.get("enabled", True)):
                        completion_label.text = str(current.get("disabled_reason", "Action is not available."))
                        return
                    if bool(current.get("requires_confirmation", False)):
                        _show_prompt_overlay(
                            prompt_overlay,
                            current,
                            status_label=status_label,
                            eta_label=eta_label,
                            progress=progress,
                            live_output=live_output,
                            details_host=details_host,
                            visual_label=visual_label,
                            visual_host=visual_host,
                            completion_label=completion_label,
                            cancel_button=cancel_button,
                            set_running_controls=set_running_controls,
                        )
                    else:
                        _start_subprocess_action(
                            current,
                            status_label=status_label,
                            eta_label=eta_label,
                            progress=progress,
                            live_output=live_output,
                            details_host=details_host,
                            visual_label=visual_label,
                            visual_host=visual_host,
                            completion_label=completion_label,
                            cancel_button=cancel_button,
                            set_running_controls=set_running_controls,
                            on_complete=lambda result, step_id=str(current.get("step_id", "")): _handle_action_completed(
                                step_id,
                                result,
                            ),
                        )

                button = _attach_tooltip(
                    ui,
                    ui.button(label, on_click=lambda _event=None, current=action: _show_prompt_or_start(current)),
                    str(action.get("confirmation_message", action.get("summary", ""))),
                )
                action_buttons.append(button)
                if not bool(action.get("enabled", True)):
                    button.disable()
                action_id = str(action.get("id", ""))
                if (
                    auto_start_trusted
                    and bool(action.get("trusted_auto_confirm", False))
                    and bool(action.get("enabled", True))
                    and action_id not in wizard_state["auto_started"]
                ):
                    wizard_state["auto_started"].add(action_id)
                    _show_prompt_or_start(action)
                return

        def _render_payload(payload: dict[str, Any], *, preserve_index: bool = False) -> None:
            wizard_state["payload"] = payload
            steps = _payload_steps(payload)
            _sync_bulk_ack_queue(payload)
            if not preserve_index:
                _set_wizard_index(payload)
            current_index = _safe_int(wizard_state.get("index"))
            if current_index > len(steps):
                current_index = len(steps)
                wizard_state["index"] = current_index
            wizard_state["done"] = bool(wizard_state.get("done")) or current_index >= len(steps)
            if steps:
                _persist_wizard_state(payload, reason="render")
            result_host.clear()
            with result_host:
                progress = payload.get("progress", {}) if isinstance(payload.get("progress"), dict) else {}
                total = len(steps) or _safe_int(progress.get("total_steps"))
                wizard_position = min(current_index, total)
                passed_count = sum(1 for step in steps if _full_qa_effective_status(step) == "passed")
                skipped_count = len(wizard_state["skipped"])
                percent = int((wizard_position / total) * 100) if total else 0
                ui.label(str(payload.get("summary", ""))).classes("sgfx-summary")
                with ui.column().classes("sgfx-wizard-shell"):
                    with ui.row().classes("sgfx-wizard-header"):
                        ui.label(
                            f"Full QA Pass / {profile_id} / Step {min(current_index + 1, total) if total else 0} of {total}"
                        ).classes("sgfx-wizard-breadcrumb")
                        ui.label(f"{passed_count} passed | {skipped_count} skipped").classes("sgfx-muted")
                    ui.linear_progress(value=max(0, min(100, percent)) / 100).classes(
                        "full-width sgfx-full-qa-progress"
                    )
                    ui.label(
                        f"Progress: {progress.get('completed_steps', 0)}/{progress.get('total_steps', 0)} "
                        f"evidence step(s); wizard position {wizard_position}/{total}."
                    ).classes("sgfx-muted")
                trusted_note = str(payload.get("trusted_tool_mode_note", "")).strip()
                if trusted_note:
                    ui.label(trusted_note).classes("sgfx-muted")
                halt_reason = str(payload.get("halt_reason", "")).strip()
                if halt_reason:
                    ui.label(f"Halted: {halt_reason}").classes("sgfx-warning")

                prompt_overlay = ui.column().classes("sgfx-wizard-overlay full-width")
                prompt_overlay.visible = False

                if steps and current_index > 0:
                    with ui.row().classes("sgfx-wizard-rail"):
                        for prior_index, prior_step in enumerate(steps[:current_index]):
                            prior_status = _full_qa_effective_status(prior_step)
                            icon = (
                                "✓"
                                if prior_status == "passed"
                                else "ack"
                                if prior_status
                                in {
                                    "incomplete_but_queued_for_acknowledge",
                                    "acknowledged_via_bulk_confirm",
                                    "confirmed_via_bulk_with_tool_draft",
                                    "operator_overrode_draft",
                                    "confirmed_via_bulk_without_review",
                                }
                                else "skip"
                                if prior_status == "skipped"
                                else "!"
                            )
                            ui.label(f"{icon} {prior_index + 1}. {prior_step.get('label', '')}").classes(
                                f"sgfx-wizard-rail-item sgfx-step-{prior_status}"
                            )

                if not steps:
                    with ui.column().classes("sgfx-wizard-card sgfx-wizard-empty"):
                        ui.label(str(payload.get("summary", "Full QA pass has not run yet."))).classes(
                            "sgfx-panel-title"
                        )
                        ui.label("Use Run full QA pass to start the local evidence chain.").classes("sgfx-muted")
                    result_host.update()
                    return

                if wizard_state["done"]:
                    full_qa_notification = None
                    if not bool(wizard_state.get("full_qa_notified")):
                        full_qa_notification = _full_qa_completion_notification(profile_id, payload)
                    _record_run_history_once(payload)
                    with ui.column().classes("sgfx-wizard-card sgfx-wizard-done"):
                        ui.label("Full QA Pass summary").classes("sgfx-panel-title")
                        ui.label(str(payload.get("summary", "Full QA Pass complete for this dashboard run."))).classes(
                            "sgfx-summary"
                        )
                        ui.label(
                            f"Wizard reviewed {min(current_index, len(steps))}/{len(steps)} step(s); "
                            f"{passed_count} passed and {skipped_count} skipped locally."
                        ).classes("sgfx-muted")
                        queued_ack_steps = _bulk_ack_queued_steps(payload)
                        if queued_ack_steps:
                            _ensure_bulk_ack_drafts(payload)
                            with ui.column().classes("sgfx-acknowledgment-queue"):
                                ui.label("Acknowledgment items queued").classes("sgfx-panel-tagline")
                                ui.label(
                                    f"{len(queued_ack_steps)} acknowledgment item(s) queued with local evidence drafts."
                                ).classes("sgfx-summary")
                                ui.label(
                                    "Review each draft below. Confirm All records unchanged drafts as "
                                    "confirmed_via_bulk_with_tool_draft; edited text is recorded as "
                                    "operator_overrode_draft with the original draft preserved."
                                ).classes("sgfx-muted")
                                draft_inputs: dict[str, Any] = {}
                                for ack_step in queued_ack_steps:
                                    step_id = str(ack_step.get("id", ""))
                                    draft = wizard_state["bulk_ack_drafts"].get(step_id, {})
                                    draft_value = str(
                                        wizard_state["bulk_ack_values"].get(step_id)
                                        or draft.get("text", "")
                                        or _bulk_handoff_placeholder(_ack_timestamp())
                                    )
                                    with ui.column().classes(
                                        f"sgfx-draft-confirm-card sgfx-draft-{draft.get('level', 'unknown')}"
                                    ):
                                        with ui.row().classes("items-center justify-between full-width"):
                                            ui.label(str(draft.get("label", ack_step.get("label", "")))).classes(
                                                "sgfx-panel-tagline"
                                            )
                                            ui.label("Draft - operator confirms or edits").classes("sgfx-muted")
                                        reason = str(draft.get("reason", "")).strip()
                                        if reason:
                                            ui.label(reason).classes("sgfx-muted")
                                        draft_input = ui.textarea(
                                            "Draft text",
                                            value=draft_value,
                                        ).props("outlined autogrow").classes("full-width sgfx-draft-text")
                                        draft_inputs[step_id] = draft_input
                                        ui.button(
                                            "Edit",
                                            on_click=lambda _event=None: _notify_ui(
                                                "Edit the draft text, then use Confirm All."
                                            ),
                                        ).props("flat dense no-caps")

                                def _collect_draft_values() -> dict[str, str]:
                                    values = {
                                        step_id: str(control.value or "")
                                        for step_id, control in draft_inputs.items()
                                    }
                                    wizard_state["bulk_ack_values"].update(values)
                                    return values

                                if bool(wizard_state.get("bulk_ack_high_risk_prompt")):
                                    with ui.column().classes("sgfx-high-risk-confirm"):
                                        ui.label("High-risk draft requires a second confirmation.").classes(
                                            "sgfx-warning"
                                        )
                                        ui.label(
                                            "Confirm All records the visible drafts; Cancel returns to draft review."
                                        ).classes("sgfx-muted")

                                        def _cancel_high_risk() -> None:
                                            wizard_state["bulk_ack_high_risk_prompt"] = False
                                            _render_payload(payload, preserve_index=True)

                                        with ui.row().classes("sgfx-confirm-actions"):
                                            ui.button(
                                                "Confirm All",
                                                on_click=lambda _event=None: _confirm_all_queued(
                                                    _collect_draft_values(),
                                                    require_high_risk_confirm=False,
                                                ),
                                            ).props("color=primary")
                                            ui.button("Cancel", on_click=_cancel_high_risk).props("flat")
                                else:
                                    ui.button(
                                        "Confirm All",
                                        on_click=lambda _event=None: _confirm_all_queued(_collect_draft_values()),
                                    ).props("color=primary")
                        acknowledged_steps = _bulk_acknowledged_steps(payload)
                        if acknowledged_steps:
                            ui.label("Confirmed queued items").classes("sgfx-panel-tagline")
                            for ack_step in acknowledged_steps:
                                step_id = str(ack_step.get("id", ""))
                                ack_timestamp = wizard_state["bulk_acknowledged"].get(step_id, "")
                                outcome = wizard_state["bulk_ack_outcomes"].get(
                                    step_id,
                                    "acknowledged_via_bulk_confirm",
                                )
                                ui.label(
                                    f"{ack_step.get('label', '')}: {outcome} at {ack_timestamp}"
                                ).classes("sgfx-muted")
                        diff_steps = [step for step in steps if _step_has_diff_review(step)]
                        if diff_steps:
                            ui.label("Steps with diffs requiring review").classes("sgfx-warning")
                            ui.label(
                                f"{len(diff_steps)} step(s) produced visual differences. "
                                "Review the rows below before recording any manual verdict."
                            ).classes("sgfx-muted")
                            for diff_step in diff_steps:
                                step_payload = diff_step.get("payload", {}) if isinstance(diff_step.get("payload"), dict) else {}
                                copied_evidence = (
                                    step_payload.get("copied_evidence", {})
                                    if isinstance(step_payload.get("copied_evidence"), dict)
                                    else {}
                                )
                                sgfx_output = str(
                                    step_payload.get("sgfx_output_root") or copied_evidence.get("output_root") or ""
                                ).strip()
                                diff_count = _safe_int(step_payload.get("diff_count"))
                                count_text = str(diff_count) if diff_count else "one or more"
                                ui.label(
                                    f"{diff_step.get('label', 'Screenshot step')}: BMW pipeline reports "
                                    f"{count_text} tests with visual differences - see thumbnails below for review."
                                ).classes("sgfx-summary")
                                if sgfx_output:
                                    ui.label(f"SGFX output: {sgfx_output}").classes("sgfx-muted")
                                done_details_host = ui.column().classes("full-width")
                                _render_action_technical_details(ui, step_payload, details_host=done_details_host)
                                done_visual_label = ui.label("Live visual output").classes("sgfx-panel-tagline")
                                done_visual_host = ui.row().classes("full-width sgfx-live-visuals")
                                _render_action_visuals(
                                    ui,
                                    step_payload,
                                    visual_label=done_visual_label,
                                    visual_host=done_visual_host,
                                    open_screenshot_viewer=_open_wizard_screenshot_viewer,
                                )
                        for guardrail in payload.get("guardrails", []):
                            if str(guardrail).strip():
                                ui.label(str(guardrail)).classes("sgfx-guardrail")
                        if steps:
                            ui.button("Back", on_click=_show_previous_step)
                    result_host.update()
                    if full_qa_notification is not None:
                        _schedule_full_qa_notification(full_qa_notification, payload)
                    return

                step = steps[current_index]
                step_status = _full_qa_effective_status(step)
                with ui.column().classes(f"sgfx-wizard-card sgfx-full-qa-step sgfx-step-{step_status}"):
                    action_buttons: list[Any] = []
                    nav_buttons: list[tuple[Any, bool]] = []

                    def _register_nav_button(button: Any, *, enabled: bool = True) -> Any:
                        nav_buttons.append((button, enabled))
                        if not enabled:
                            button.disable()
                        return button

                    def _set_running_controls(is_running: bool) -> None:
                        for button in action_buttons:
                            button.visible = not is_running
                        for button, default_enabled in nav_buttons:
                            if is_running:
                                button.disable()
                                button.classes(add="sgfx-wizard-nav-blocked")
                                button.props(f'title="{running_navigation_message}"')
                            else:
                                button.classes(remove="sgfx-wizard-nav-blocked")
                                button.props('title=""')
                                if default_enabled:
                                    button.enable()
                                else:
                                    button.disable()

                    with ui.row().classes("items-center justify-between full-width"):
                        ui.label(str(step.get("label", ""))).classes("sgfx-panel-title")
                        status_label = ui.label(step_status).classes("sgfx-status-pill")
                    eta_label = ui.label(
                        _eta_text(
                            elapsed=str((step.get("payload", {}) if isinstance(step.get("payload"), dict) else {}).get("elapsed_label", "00:00")),
                            typical=_typical_range_for_step(step),
                        )
                    ).classes("sgfx-muted sgfx-step-eta")
                    ui.label(str(step.get("summary", ""))).classes("sgfx-muted")
                    step_anchors = step.get("confluence_anchors", [])
                    if isinstance(step_anchors, str):
                        step_anchors = [step_anchors]
                    for anchor in [str(item).strip() for item in step_anchors if str(item).strip()][:1]:
                        _render_confluence_anchor(ui, anchor)
                    if str(step.get("id", "")) == "screenshot-test-state":
                        step_payload = step.get("payload", {}) if isinstance(step.get("payload"), dict) else {}
                        ui.label(
                            "Screenshot counts: "
                            f"{_safe_int(step_payload.get('expected_count'))} expected / "
                            f"{_safe_int(step_payload.get('actual_count'))} actual / "
                            f"{_safe_int(step_payload.get('diff_count'))} diff."
                        ).classes("sgfx-muted")
                    actions = [action for action in step.get("inline_actions", []) if isinstance(action, dict)]
                    if actions:
                        ui.label("Operator action").classes("sgfx-panel-tagline")
                        for action in actions:
                            _render_action(
                                action,
                                status_label=status_label,
                                eta_label=eta_label,
                                prompt_overlay=prompt_overlay,
                                auto_start_trusted=bool(payload.get("trusted_tool_mode", False)),
                                action_buttons=action_buttons,
                                set_running_controls=_set_running_controls,
                            )
                    with ui.row().classes("sgfx-wizard-nav"):
                        _register_nav_button(ui.button("Back", on_click=_show_previous_step), enabled=current_index > 0)
                        _register_nav_button(ui.button("Skip current", on_click=_skip_current_step))
                        _register_nav_button(ui.button("Run again", on_click=lambda: _run_full_pass()))
                    if any(str(action.get("id", "")) in running_actions for action in actions):
                        _set_running_controls(True)

                for guardrail in payload.get("guardrails", []):
                    if str(guardrail).strip():
                        ui.label(str(guardrail)).classes("sgfx-guardrail")
            result_host.update()

        def _run_full_pass() -> None:
            trusted = bool(trusted_control.value)
            payload = build_full_qa_pass(
                profile_id,
                workspace=workspace,
                bmw_root=bmw_root,
                trusted_tool_mode=trusted,
            )
            append_activity_entry(
                workspace,
                verb="ran",
                surface="full-qa-pass:run",
                profile=str(payload.get("profile_id", profile_id)),
                outcome="ok",
                note=f"Full QA Pass run with automatic_mode={trusted}.",
            )
            notice.text = str(payload.get("summary", "Full QA pass started."))
            _reset_wizard_run_state(payload)
            _render_payload(payload)

        _attach_tooltip(
            ui,
            ui.button("Run full QA pass", on_click=_run_full_pass).classes("sgfx-html-action-button"),
            "Start the local evidence chain for the selected profile.",
        )
        _render_resume_prompt()
        _render_payload(initial_payload)


def _render_selected_page(
    ui: Any,
    container: Any,
    pages_by_id: dict[str, dict[str, Any]],
    page_id: str,
    snapshot: dict[str, Any],
    workspace: Path,
) -> None:
    container.clear()
    with container:
        if page_id == "full-qa-pass":
            _render_full_qa_pass_panel(ui, snapshot, workspace)
        elif page_id == "delivery-checklist":
            _render_delivery_checklist_panel(ui, snapshot, workspace)
        elif page_id == "screenshot-test-state":
            _render_screenshot_test_state_panel(ui, snapshot, workspace)
        elif page_id == "risk-score":
            _render_risk_score_panel(ui, snapshot)
        elif page_id == "cross-car-comparison":
            _render_cross_car_comparison_panel(ui, snapshot)
        elif page_id == "manual-review":
            _render_manual_review_panel(ui, snapshot, workspace)
        elif page_id == "daily-digest":
            _render_daily_digest_panel(ui, snapshot, workspace)
        elif page_id == "team-digest-board":
            _render_team_digest_board_panel(ui, snapshot)
        elif page_id == "operator-handoff":
            _render_operator_handoff_panel(ui, snapshot, workspace)
        elif page_id == "about":
            _render_about_panel(ui, ABOUT_CONTENT)
        else:
            _render_page_panel(ui, pages_by_id[page_id])


def _render_dashboard(
    ui: Any,
    app: Any,
    *,
    initial_profile_id: str,
    workspace: Path,
    bmw_root: Path | str | None = None,
    ui_mode: str | None = None,
) -> None:
    app.add_static_files("/sgfx-dashboard-static", str(runtime_asset_dir("sg_preflight/dashboard")))
    app.add_static_files("/sgfx-dashboard-assets", str(runtime_asset_root()))
    confluence_root = _confluence_dump_root()
    if confluence_root.is_dir():
        app.add_static_files("/sgfx-confluence", str(confluence_root))
    operator_ui_static_root = operator_ui_root(workspace)
    operator_ui_static_root.mkdir(parents=True, exist_ok=True)
    app.add_static_files("/sgfx-operator-ui", str(operator_ui_static_root))
    base_snapshot = build_dashboard_snapshot(
        initial_profile_id,
        workspace,
        bmw_root=bmw_root,
        ui_mode=ui_mode,
        defer_daily_digest=True,
        defer_team_digest_board=True,
    )

    @app.get("/sgfx-dashboard-api/full-qa-pass")
    def _full_qa_pass_api(profile: str = "", trusted_tool_mode: str = "1") -> dict[str, Any]:
        requested_profile = str(profile or base_snapshot.get("profile_id") or initial_profile_id).strip()
        trusted = str(trusted_tool_mode).strip().casefold() in {"1", "true", "yes", "on"}
        return build_full_qa_pass(
            requested_profile,
            workspace=workspace,
            bmw_root=bmw_root,
            trusted_tool_mode=trusted,
        )

    @ui.page("/")
    def _index(profile: str = "", full_qa_run: str = "", automatic_mode: str = "1") -> None:
        query_profile = str(profile or "").strip()
        snapshot = (
            build_dashboard_snapshot(
                query_profile,
                workspace,
                bmw_root=bmw_root,
                ui_mode=ui_mode,
                defer_daily_digest=True,
                defer_team_digest_board=True,
            )
            if query_profile
            else dict(base_snapshot)
        )
        snapshot["theme"] = _clean_theme(ui_mode or load_dashboard_preference(workspace))
        if _is_truthy_trigger(full_qa_run):
            profile_for_trigger = str(
                snapshot.get("profile_id", query_profile or initial_profile_id)
            )
            # H-28: dedup BEFORE firing so a NiceGUI WebSocket reconnect storm
            # cannot re-execute build_full_qa_pass with the cached trigger URL.
            if not _should_fire_full_qa_pass(profile_for_trigger):
                _publish_live_state(
                    workspace,
                    dashboard_surface="full-qa-pass:run-dedupped",
                    profile_id=profile_for_trigger,
                    last_operator_action=("ran", "full-qa-pass:run"),
                    last_error="Re-fire suppressed by 30s dedup window",
                )
                ui.navigate.to(f"/?profile={quote_plus(profile_for_trigger)}")
                return
            trusted = _is_truthy_trigger(automatic_mode, default="1")
            payload = build_full_qa_pass(
                profile_for_trigger,
                workspace=workspace,
                bmw_root=bmw_root,
                trusted_tool_mode=trusted,
            )
            append_activity_entry(
                workspace,
                verb="ran",
                surface="full-qa-pass:run",
                profile=str(payload.get("profile_id", snapshot.get("profile_id", ""))),
                outcome="ok",
                note=f"Full QA Pass run with automatic_mode={trusted}; dedup_token={_full_qa_pass_token(profile_for_trigger)}.",
            )
            snapshot = _snapshot_with_full_qa_payload(snapshot, payload)
            profile_for_redirect = str(
                snapshot.get("profile_id", query_profile or initial_profile_id)
            )
            _publish_live_state(
                workspace,
                dashboard_surface="full-qa-pass:run-fired",
                profile_id=profile_for_redirect,
                last_operator_action=("ran", "full-qa-pass:run"),
            )
            ui.navigate.to(f"/?profile={quote_plus(profile_for_redirect)}")
            return
        _publish_live_state(
            workspace,
            dashboard_surface="dashboard:index",
            profile_id=str(snapshot.get("profile_id", query_profile or initial_profile_id)),
            last_operator_action=("opened", "dashboard:index"),
        )
        theme = str(snapshot.get("theme", "clean"))
        ui.dark_mode().enable()
        ui.query("body").classes(f"sgfx-dashboard sgfx-theme-{theme}")
        ui.add_head_html(
            """
            <style>
            :root {
              --sgfx-bg: #1e1e1e;
              --sgfx-bg-elev: #252526;
              --sgfx-bg-panel: #2b2b2b;
              --sgfx-border: #3c3c3c;
              --sgfx-border-soft: #333333;
              --sgfx-fg: #d4d4d4;
              --sgfx-fg-muted: #9da3a8;
              --sgfx-fg-strong: #ececec;
              --sgfx-accent: #4ec9b0;
              --sgfx-accent-soft: #264f44;
              --sgfx-warning-fg: #e8c07d;
              --sgfx-warning-bg: #3a2f18;
              --sgfx-warning-border: #6b5024;
            }
            html, body { background: var(--sgfx-bg); color: var(--sgfx-fg); }
            .sgfx-dashboard { background: var(--sgfx-bg); color: var(--sgfx-fg); font-family: 'Segoe UI', 'Cascadia Code', Arial, sans-serif; }
            .sgfx-theme-grafiks { background: var(--sgfx-bg); }
            .sgfx-shell { min-height: 100vh; gap: 0; }
            .sgfx-sidebar { position: fixed; inset: 0 auto 0 0; z-index: 9100; width: min(292px, calc(100vw - 56px)); min-height: 100vh; padding: 22px 16px; background: var(--sgfx-bg-elev); border-right: 1px solid var(--sgfx-border); gap: 10px; overflow-y: auto; transform: translateX(calc(-100% - 1px)); transition: transform 180ms ease-out, box-shadow 180ms ease-out; }
            body.sgfx-sidebar-open .sgfx-sidebar { transform: translateX(0); box-shadow: 18px 0 42px rgba(0, 0, 0, 0.38); }
            .sgfx-sidebar-backdrop { position: fixed; inset: 0; z-index: 9090; background: rgba(0, 0, 0, 0.46); opacity: 0; pointer-events: none; transition: opacity 160ms ease-out; }
            body.sgfx-sidebar-open .sgfx-sidebar-backdrop { opacity: 1; pointer-events: auto; }
            .sgfx-sidebar-logo { width: 200px; max-width: 100%; height: auto; object-fit: contain; margin: 4px 0 14px 0; }
            .sgfx-nav-button { justify-content: flex-start; border-radius: 6px; color: var(--sgfx-fg) !important; }
            .sgfx-nav-button:hover { background: var(--sgfx-accent-soft) !important; }
            .sgfx-shortcut { color: var(--sgfx-fg-muted); font-size: 12px; line-height: 1.5; }
            .sgfx-menu-button { position: fixed; top: 18px; left: 18px; z-index: 9080; width: 36px; height: 36px; border: 1px solid var(--sgfx-border) !important; border-radius: 999px; background: var(--sgfx-bg-elev) !important; color: var(--sgfx-fg) !important; font-size: 20px; line-height: 1; cursor: pointer; box-shadow: 0 10px 24px rgba(0, 0, 0, 0.22); }
            body.sgfx-sidebar-open .sgfx-menu-button { border-color: var(--sgfx-accent) !important; color: var(--sgfx-accent) !important; }
            .sgfx-floating-shortcuts { position: fixed; left: 18px; bottom: 18px; z-index: 9070; display: flex; flex-direction: column; gap: 4px; padding: 8px 10px; border: 1px solid var(--sgfx-border); border-radius: 8px; background: rgba(37, 37, 38, 0.94); box-shadow: 0 10px 24px rgba(0, 0, 0, 0.22); transition: opacity 160ms ease-out, transform 160ms ease-out; }
            .sgfx-floating-shortcuts span { color: var(--sgfx-fg-muted); font-size: 12px; line-height: 1.35; }
            body.sgfx-sidebar-open .sgfx-floating-shortcuts { opacity: 0.36; transform: translateX(-4px); pointer-events: none; }
            .sgfx-main { flex: 1; min-width: 0; padding: 24px 28px 24px 76px; gap: 18px; background: var(--sgfx-bg); }
            .sgfx-header { border-bottom: 1px solid var(--sgfx-border); padding-bottom: 14px; }
            .sgfx-subtitle { color: var(--sgfx-fg-muted); font-size: 13px; }
            .sgfx-brand-lockup { gap: 14px; }
            .sgfx-brand-logo { height: 96px; max-width: 360px; width: auto; object-fit: contain; flex: 0 0 auto; }
            .sgfx-about-logo { width: 240px; max-width: 42vw; height: auto; object-fit: contain; flex: 0 0 auto; }
            .sgfx-content { width: 100%; }
            .sgfx-footer { border-top: 1px solid var(--sgfx-border); padding-top: 12px; margin-top: 12px; }
            .sgfx-footer-actions { gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
            .sgfx-feedback-button { border: 1px solid var(--sgfx-border) !important; border-radius: 6px; background: var(--sgfx-bg-elev) !important; color: var(--sgfx-fg) !important; min-height: 32px; padding: 0 12px; cursor: pointer; }
            .sgfx-feedback-button:hover { border-color: var(--sgfx-accent) !important; color: var(--sgfx-accent) !important; }
            .sgfx-guardrail { color: var(--sgfx-fg-muted); font-size: 13px; line-height: 1.55; }
            .sgfx-page-panel { border-radius: 8px; box-shadow: none; border: 1px solid var(--sgfx-border); width: 100%; padding: 18px; background: var(--sgfx-bg-panel); color: var(--sgfx-fg); margin-bottom: 14px; }
            .sgfx-jira-profile-card { border: 1px solid var(--sgfx-border); border-radius: 8px; padding: 12px 14px; margin: 10px 0 14px; background: var(--sgfx-bg-elev); gap: 8px; }
            .sgfx-jira-ticket-row { border-top: 1px solid var(--sgfx-border); padding-top: 8px; gap: 8px; }
            .sgfx-jira-ticket-key { font-weight: 700; color: var(--sgfx-accent); text-decoration: none; }
            .sgfx-jira-status-pill { border: 1px solid var(--sgfx-border); border-radius: 999px; padding: 2px 8px; color: var(--sgfx-fg-muted); font-size: 12px; white-space: nowrap; }
            .sgfx-batch-profile-links { gap: 8px; flex-wrap: wrap; margin-top: 8px; }
            .sgfx-first-launch-card { gap: 8px; padding: 14px 16px; border-color: rgba(78, 201, 176, 0.42); background: #22302d; }
            .sgfx-first-launch-card[data-sgfx-dismissed="true"] { display: none; }
            .sgfx-first-launch-actions { gap: 10px; align-items: center; flex-wrap: wrap; }
            .sgfx-link-button { border: 0; background: transparent; color: var(--sgfx-accent); cursor: pointer; font-size: 12px; padding: 4px 0; }
            .sgfx-link-button:hover { text-decoration: underline; }
            .sgfx-panel-title { font-size: 18px; font-weight: 650; color: var(--sgfx-fg-strong); }
            .sgfx-panel-tagline, .sgfx-muted { color: var(--sgfx-fg-muted); font-size: 13px; }
            .sgfx-doc-link-row { gap: 10px; align-items: center; flex-wrap: wrap; }
            .sgfx-doc-link { color: var(--sgfx-accent) !important; font-size: 13px; text-decoration: none; border-bottom: 1px solid rgba(78, 201, 176, 0.45); }
            .sgfx-summary { color: var(--sgfx-fg); font-size: 14px; line-height: 1.55; }
            .sgfx-warning { border: 1px solid var(--sgfx-warning-border); background: var(--sgfx-warning-bg); color: var(--sgfx-warning-fg); border-radius: 6px; padding: 9px 12px; }
            .sgfx-shortcut-feedback { min-height: 22px; color: var(--sgfx-fg-muted); font-size: 13px; padding: 2px 0; }
            .sgfx-profile-select { min-width: 144px; }
            .sgfx-status { text-transform: none; }
            .sgfx-table { width: 100%; color: var(--sgfx-fg); }
            .sgfx-full-qa-controls { display: flex; flex-wrap: wrap; gap: 14px; align-items: center; margin: 10px 0 14px 0; }
            .sgfx-html-action-button { min-height: 36px; border: 0; border-radius: 6px; padding: 0 16px; background: var(--sgfx-accent); color: #071d18; font-weight: 600; cursor: pointer; }
            .sgfx-html-action-button:disabled { cursor: progress; opacity: 0.68; }
            .sgfx-inline-check { display: inline-flex; align-items: center; gap: 8px; color: var(--sgfx-fg); font-size: 13px; }
            .sgfx-full-qa-progress { width: 100%; height: 10px; margin: 10px 0 6px 0; accent-color: var(--sgfx-accent); transition: opacity 180ms ease, filter 180ms ease; }
            .sgfx-full-qa-table { width: 100%; border-collapse: collapse; margin-top: 14px; font-size: 13px; }
            .sgfx-full-qa-table th, .sgfx-full-qa-table td { border-bottom: 1px solid var(--sgfx-border-soft); padding: 9px 10px; text-align: left; vertical-align: top; }
            .sgfx-full-qa-table th { color: var(--sgfx-fg-strong); background: var(--sgfx-bg-elev); }
            .sgfx-status-pill { display: inline-block; min-width: 72px; border-radius: 999px; padding: 2px 8px; background: var(--sgfx-bg-elev); border: 1px solid var(--sgfx-border); font-size: 12px; transition: background-color 180ms ease, border-color 180ms ease, color 180ms ease; }
            .sgfx-step { border: 1px solid var(--sgfx-border); border-radius: 8px; margin: 8px 0; background: var(--sgfx-bg-elev); }
            .sgfx-full-qa-step { width: 100%; gap: 8px; border: 1px solid var(--sgfx-border); border-radius: 8px; margin: 8px 0; padding: 12px; background: var(--sgfx-bg-elev); transition: border-color 180ms ease-out, background-color 180ms ease-out, transform 180ms ease-out; }
            .sgfx-wizard-shell { width: 100%; gap: 8px; margin-top: 10px; }
            .sgfx-wizard-header { width: 100%; align-items: center; justify-content: space-between; gap: 12px; }
            .sgfx-wizard-breadcrumb { color: var(--sgfx-fg-strong); font-size: 14px; font-weight: 650; }
            .sgfx-wizard-rail { width: 100%; gap: 6px; flex-wrap: wrap; margin: 12px 0 8px 0; }
            .sgfx-wizard-rail-item { border: 1px solid var(--sgfx-border); border-radius: 999px; padding: 4px 10px; background: var(--sgfx-bg-elev); color: var(--sgfx-fg-muted); font-size: 12px; }
            .sgfx-wizard-card { width: min(100%, 860px); align-self: center; gap: 10px; border-radius: 8px; padding: 18px; margin: 14px auto; animation: sgfx-wizard-card-in 160ms ease-out; transition: border-color 180ms ease, background-color 180ms ease, transform 180ms ease; }
            .sgfx-wizard-nav, .sgfx-wizard-modal-actions { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
            .sgfx-wizard-nav .q-btn { transition: opacity 160ms ease, filter 160ms ease, transform 160ms ease; }
            .sgfx-wizard-nav-blocked { opacity: 0.52; filter: saturate(0.68); }
            .sgfx-wizard-overlay { position: fixed; inset: 0; z-index: 9200; display: flex; align-items: center; justify-content: center; background: rgba(4, 8, 10, 0.72); padding: 20px; animation: sgfx-overlay-in 120ms ease-out; }
            .sgfx-wizard-modal { width: min(92vw, 640px); gap: 10px; border: 1px solid var(--sgfx-warning-border); border-radius: 8px; background: var(--sgfx-bg-panel); color: var(--sgfx-fg); padding: 18px; box-shadow: 0 22px 58px rgba(0, 0, 0, 0.45); animation: sgfx-wizard-card-in 160ms ease-out; }
            .sgfx-wizard-done { border: 1px solid #3b6f55; background: #223027; }
            .sgfx-resume-prompt { width: min(100%, 860px); align-self: center; gap: 8px; border: 1px solid var(--sgfx-warning-border); border-radius: 8px; background: var(--sgfx-warning-bg); padding: 14px 16px; margin: 12px auto; }
            .sgfx-step-running { border-color: var(--sgfx-accent); background: #203530; }
            .sgfx-step-passed { border-color: #3b6f55; background: #223027; }
            .sgfx-step-failed { border-color: #8f4d4d; background: #332425; }
            .sgfx-step-skipped { border-color: var(--sgfx-border); background: var(--sgfx-bg-elev); }
            .sgfx-step-incomplete_but_queued_for_acknowledge { border-color: #94764c; background: #302b20; }
            .sgfx-step-acknowledged_via_bulk_confirm { border-color: #4f766f; background: #20302d; }
            .sgfx-step-confirmed_via_bulk_with_tool_draft { border-color: #4f766f; background: #20302d; }
            .sgfx-step-operator_overrode_draft { border-color: #6d7590; background: #252a38; }
            .sgfx-step-confirmed_via_bulk_without_review { border-color: #94764c; background: #302b20; }
            .sgfx-step-incomplete, .sgfx-step-confirmation_pending { border-color: var(--sgfx-warning-border); background: var(--sgfx-warning-bg); }
            .sgfx-acknowledgment-queue { gap: 8px; border: 1px solid #94764c; border-radius: 8px; background: #29251d; padding: 12px; }
            .sgfx-draft-confirm-card { gap: 8px; border: 1px solid var(--sgfx-border); border-radius: 8px; background: var(--sgfx-bg-panel); padding: 12px; }
            .sgfx-draft-high { border-color: #a45a55; background: #352323; }
            .sgfx-draft-medium { border-color: #94764c; background: #302b20; }
            .sgfx-draft-low, .sgfx-draft-handoff, .sgfx-draft-manual_review_required { border-color: #4f766f; background: #20302d; }
            .sgfx-draft-text textarea { min-height: 96px; line-height: 1.45; }
            .sgfx-high-risk-confirm { gap: 8px; border: 1px solid #a45a55; border-radius: 8px; background: #352323; padding: 12px; }
            .sgfx-changed-profiles-card { gap: 10px; }
            .sgfx-confirm-actions { gap: 10px; align-items: center; }
            .sgfx-live-output textarea { min-height: 160px; font-family: 'Cascadia Mono', Consolas, 'Courier New', monospace; font-size: 12px; line-height: 1.45; background: var(--sgfx-bg) !important; color: var(--sgfx-fg) !important; }
            .sgfx-live-visuals { gap: 12px; align-items: stretch; animation: sgfx-visual-in 160ms ease-out; }
            .sgfx-workbook-preview, .sgfx-diff-preview { flex: 1 1 280px; min-width: 260px; border: 1px solid var(--sgfx-border); border-radius: 8px; background: var(--sgfx-bg); padding: 10px; gap: 6px; }
            .sgfx-side-by-side-preview { max-height: min(68vh, 760px); overflow-y: auto; position: relative; padding: 0; }
            .sgfx-side-by-side-preview > .sgfx-panel-tagline { padding: 10px 10px 0 10px; }
            .sgfx-side-by-side-preview .sgfx-diff-row-card { margin: 0 10px 8px 10px; }
            .sgfx-side-by-side-preview .sgfx-diff-row-card:last-child { margin-bottom: 10px; }
            .sgfx-diff-thumbnails { gap: 10px; flex-wrap: wrap; }
            .sgfx-diff-thumb-card { width: 176px; border: 1px solid var(--sgfx-border-soft); border-radius: 6px; background: var(--sgfx-bg-elev); padding: 8px; gap: 6px; }
            .sgfx-diff-thumb { width: 160px; height: 100px; object-fit: contain; background: #111; border-radius: 4px; }
            .sgfx-diff-row-card { border: 1px solid var(--sgfx-border); border-radius: 8px; padding: 8px; background: var(--sgfx-bg-panel); gap: 6px; }
            .sgfx-diff-triplet-button { width: 100%; padding: 0 !important; text-align: left; }
            .sgfx-diff-triplet { display: grid; grid-template-columns: repeat(3, minmax(112px, 1fr)); gap: 8px; width: 100%; }
            .sgfx-diff-triplet-sticky-header { position: sticky; top: 0; z-index: 2; display: grid; grid-template-columns: repeat(3, minmax(112px, 1fr)); gap: 8px; width: 100%; padding: 8px 8px 7px 8px; border-bottom: 1px solid var(--sgfx-border); background: var(--sgfx-bg); box-shadow: 0 8px 16px rgba(0, 0, 0, 0.18); }
            .sgfx-diff-sticky-label { color: var(--sgfx-fg-strong); font-size: 12px; font-weight: 650; text-align: center; }
            .sgfx-diff-triplet-pane { min-width: 0; gap: 4px; align-items: center; }
            .sgfx-diff-row-meta { align-items: center; justify-content: space-between; gap: 8px; width: 100%; }
            .sgfx-delta-badge { display: inline-flex; align-items: center; flex: 0 0 auto; padding: 2px 7px; border: 1px solid var(--sgfx-border); border-radius: 999px; font-size: 11px; line-height: 1.35; }
            .sgfx-delta-green { color: #7ee2a8; border-color: rgba(126, 226, 168, 0.55); background: rgba(126, 226, 168, 0.11); }
            .sgfx-delta-yellow { color: #e8c07d; border-color: rgba(232, 192, 125, 0.55); background: rgba(232, 192, 125, 0.12); }
            .sgfx-delta-red { color: #f08a7d; border-color: rgba(240, 138, 125, 0.55); background: rgba(240, 138, 125, 0.13); }
            .sgfx-regression-badge { display: inline-flex; align-items: center; flex: 0 0 auto; padding: 2px 7px; border: 1px solid var(--sgfx-border); border-radius: 999px; font-size: 11px; line-height: 1.35; }
            .sgfx-regression-regression { color: #f08a7d; border-color: rgba(240, 138, 125, 0.55); background: rgba(240, 138, 125, 0.13); }
            .sgfx-regression-improved { color: #7ee2a8; border-color: rgba(126, 226, 168, 0.55); background: rgba(126, 226, 168, 0.11); }
            .sgfx-regression-stable { color: #e8c07d; border-color: rgba(232, 192, 125, 0.55); background: rgba(232, 192, 125, 0.1); }
            .sgfx-regression-neutral { color: var(--sgfx-fg-muted); border-color: var(--sgfx-border); background: rgba(255, 255, 255, 0.035); }
            .sgfx-technical-details-text textarea { font-family: Consolas, 'Courier New', monospace; font-size: 12px; min-height: 180px; }
            .sgfx-step-eta { font-variant-numeric: tabular-nums; }
            .sgfx-risk-metric { flex: 1 1 220px; min-width: 220px; border: 1px solid var(--sgfx-border); border-radius: 8px; padding: 12px; background: var(--sgfx-bg-elev); }
            .sgfx-file-activity { max-height: 160px; overflow-y: auto; border: 1px solid var(--sgfx-border); border-radius: 6px; padding: 8px; background: var(--sgfx-bg-elev); }
            .sgfx-viewer-dialog-card { width: min(96vw, 1680px); height: min(92vh, 980px); max-width: none !important; display: flex; flex-direction: column; gap: 10px; background: var(--sgfx-bg-panel); color: var(--sgfx-fg); border: 1px solid var(--sgfx-border); border-radius: 8px; }
            .sgfx-viewer-frame-host { flex: 1 1 auto; min-height: 0; width: 100%; }
            .sgfx-viewer-iframe { width: 100%; height: 100%; min-height: 620px; border: 1px solid var(--sgfx-border); border-radius: 6px; background: #ffffff; }
            .sgfx-thinking-tooltip { background: #121b1f !important; color: #f4fbf7 !important; border: 1px solid var(--sgfx-accent) !important; border-radius: 8px !important; padding: 8px 10px !important; box-shadow: 0 10px 28px rgba(0, 0, 0, 0.32); animation: sgfx-tooltip-pop 150ms ease-out; }
            .sgfx-thinking-tooltip::before { content: ""; display: inline-block; width: 8px; height: 8px; margin-right: 7px; border-radius: 50%; background: var(--sgfx-accent); animation: sgfx-tooltip-pulse 900ms ease-in-out infinite; vertical-align: middle; }
            .sgfx-hotkey-popup { position: fixed; top: 82px; right: 36px; z-index: 9000; min-width: 280px; max-width: 380px; display: flex; align-items: center; gap: 14px; padding: 14px 16px; border: 1px solid var(--sgfx-accent); border-radius: 8px; background: rgba(18, 27, 31, 0.96); color: var(--sgfx-fg); opacity: 0; transform: translateY(-8px) scale(0.98); pointer-events: none; transition: opacity 150ms ease-out, transform 150ms ease-out; box-shadow: 0 16px 42px rgba(0, 0, 0, 0.38); }
            .sgfx-hotkey-popup.show { opacity: 1; transform: translateY(0) scale(1); }
            .sgfx-hotkey-popup img { width: 96px; height: 96px; object-fit: contain; animation: sgfx-hotkey-pulse 900ms ease-in-out infinite; flex: 0 0 auto; }
            .sgfx-hotkey-key { color: var(--sgfx-fg-strong); font-size: 14px; font-weight: 650; }
            .sgfx-hotkey-message { color: var(--sgfx-fg-muted); font-size: 13px; line-height: 1.45; }
            @keyframes sgfx-wizard-card-in { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
            @keyframes sgfx-overlay-in { from { opacity: 0; } to { opacity: 1; } }
            @keyframes sgfx-visual-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
            @keyframes sgfx-tooltip-pop { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
            @keyframes sgfx-tooltip-pulse { 0%, 100% { transform: scale(0.78); opacity: 0.58; } 50% { transform: scale(1.22); opacity: 1; } }
            @keyframes sgfx-hotkey-pulse { 0%, 100% { transform: scale(0.96) rotate(0deg); opacity: 0.82; } 50% { transform: scale(1.04) rotate(3deg); opacity: 1; } }
            </style>
            """
        )
        first_page_id = str(snapshot["navigation"][0]["id"])
        state: dict[str, Any] = {"snapshot": snapshot, "active_page_id": first_page_id}
        content_holder: dict[str, Any] = {}
        controls: dict[str, Any] = {}
        feedback_context = _dashboard_feedback_context(workspace)

        def _pages_by_id() -> dict[str, dict[str, Any]]:
            return {str(page["id"]): page for page in state["snapshot"]["pages"]}

        def _current_theme() -> str:
            return str(state["snapshot"].get("theme", "clean"))

        def _header_text() -> str:
            active = state["snapshot"]
            return (
                f"Profile: {active['profile_id']} | Workspace: {active['workspace_label']} "
                f"| Output: {active.get('output_root_label', '')}"
            )

        def _all_profile_options() -> list[dict[str, Any]]:
            return [option for option in state["snapshot"].get("profile_options_all", []) if isinstance(option, dict)]

        def _default_profile_options() -> list[dict[str, Any]]:
            return [option for option in state["snapshot"].get("profile_options", []) if isinstance(option, dict)]

        def _profile_option_for_id(profile_id: str) -> dict[str, Any] | None:
            requested = profile_id.strip().casefold()
            for option in _all_profile_options():
                if str(option.get("id", "")).casefold() == requested:
                    return option
            return None

        def _select_label_for_profile(profile_id: str) -> str:
            option = _profile_option_for_id(profile_id)
            return str(option.get("select_label", profile_id)) if option else profile_id

        def _profile_id_from_select_value(value: str) -> str:
            selected = value.strip()
            for option in _all_profile_options():
                if selected in {str(option.get("id", "")), str(option.get("select_label", ""))}:
                    return str(option.get("id", selected))
            return selected

        def _filtered_profile_options() -> list[dict[str, Any]]:
            show_all_control = controls.get("profile_show_all")
            search_control = controls.get("profile_search")
            show_all = bool(getattr(show_all_control, "value", state["snapshot"].get("profile_show_all", False)))
            query = str(getattr(search_control, "value", "") or "").strip().casefold()
            options = _all_profile_options() if show_all else _default_profile_options()
            if not query:
                return options
            filtered = []
            for option in options:
                haystack = " ".join(
                    str(option.get(key, ""))
                    for key in ("id", "label", "select_label", "bmw_profile_id", "brand", "lane", "type", "retarget_target")
                ).casefold()
                if query in haystack:
                    filtered.append(option)
            return filtered

        def _sync_profile_select() -> None:
            profile_select = controls.get("profile_select")
            if profile_select is None:
                return
            options = _filtered_profile_options()
            labels = [str(option.get("select_label", option.get("id", ""))) for option in options]
            profile_select.options = labels
            current_id = str(state["snapshot"].get("profile_id", ""))
            current_label = _select_label_for_profile(current_id)
            profile_select.value = current_label if current_label in labels else None
            profile_select.update()

        def _refresh_labels() -> None:
            profile_label = controls.get("profile_label")
            if profile_label is not None:
                profile_label.set_text(_header_text())
            registry_label = controls.get("profile_registry_label")
            if registry_label is not None:
                registry = state["snapshot"].get("profile_registry", {})
                registry_label.set_text(str(registry.get("summary", "")) if isinstance(registry, dict) else "")
            show_all_control = controls.get("profile_show_all")
            if show_all_control is not None and bool(state["snapshot"].get("profile_show_all", False)):
                show_all_control.value = True
            _sync_profile_select()
            _sync_body_context()

        def _sync_body_context() -> None:
            payload = {
                "profileId": str(state["snapshot"].get("profile_id", "")),
                "activePage": str(state.get("active_page_id", "")),
            }
            _run_javascript_if_client_alive(
                ui,
                f"""
                (() => {{
                    const payload = {json.dumps(payload)};
                    document.body.dataset.sgfxProfileId = payload.profileId || '';
                document.body.dataset.sgfxActivePage = payload.activePage || 'unknown';
                }})();
                """
            )

        def _open_changed_profiles_batch(profile_ids: list[str]) -> None:
            state["batch_profile_prefill"] = [str(profile).strip() for profile in profile_ids if str(profile).strip()]
            _open_page("batch-full-qa-pass")

        def _render_current_page() -> None:
            content = content_holder.get("content")
            if content is None:
                return
            content.clear()
            with content:
                warning = str(state["snapshot"].get("profile_warning", "") or "")
                if warning:
                    ui.label(warning).classes("sgfx-warning")
                active_page_id = str(state["active_page_id"])
                _render_first_run_welcome(
                    ui,
                    state["snapshot"],
                    open_setup=lambda: _open_page("delivery-checklist"),
                    open_full_qa=lambda: _open_page("full-qa-pass"),
                )
                _render_changed_profiles_card(
                    ui,
                    state["snapshot"],
                    open_batch=_open_changed_profiles_batch,
                )
                if active_page_id == "delivery-checklist":
                    _render_delivery_checklist_panel(
                        ui,
                        state["snapshot"],
                        workspace,
                        on_setup_completed=_refresh_snapshot,
                    )
                elif active_page_id == "full-qa-pass":
                    _render_full_qa_pass_panel(
                        ui,
                        state["snapshot"],
                        workspace,
                        bmw_root=bmw_root,
                        open_page=_open_page,
                    )
                elif active_page_id == "batch-full-qa-pass":
                    _render_batch_full_qa_pass_panel(
                        ui,
                        state["snapshot"],
                        workspace,
                        bmw_root=bmw_root,
                        open_profile=lambda profile_id: (_set_profile(profile_id), _open_page("full-qa-pass")),
                        default_profile_ids=state.get("batch_profile_prefill", []),
                    )
                elif active_page_id == "screenshot-test-state":
                    _render_screenshot_test_state_panel(ui, state["snapshot"], workspace, bmw_root=bmw_root)
                elif active_page_id == "risk-score":
                    _render_risk_score_panel(ui, state["snapshot"])
                elif active_page_id == "cross-car-comparison":
                    _render_cross_car_comparison_panel(ui, state["snapshot"])
                elif active_page_id == "daily-digest":
                    _render_daily_digest_panel(ui, state["snapshot"], workspace)
                elif active_page_id == "team-digest-board":
                    _render_team_digest_board_panel(ui, state["snapshot"])
                elif active_page_id == "operator-handoff":
                    _render_operator_handoff_panel(ui, state["snapshot"], workspace)
                elif active_page_id == "manual-review":
                    _render_manual_review_panel(ui, state["snapshot"], workspace)
                elif active_page_id == "about":
                    _render_about_panel(ui, ABOUT_CONTENT)
                else:
                    _render_page_panel(ui, _pages_by_id()[active_page_id])
            content.update()
            _run_javascript_if_client_alive(
                ui,
                "window.sgfxApplyFirstLaunchState && window.sgfxApplyFirstLaunchState();",
            )

        def _open_page(page_id: str) -> None:
            state["active_page_id"] = page_id
            _run_javascript_if_client_alive(ui, f"document.body.dataset.sgfxActivePage = {json.dumps(page_id)};")
            _run_javascript_if_client_alive(ui, "window.sgfxSetSidebarOpen && window.sgfxSetSidebarOpen(false);")
            if page_id in {"daily-digest", "team-digest-board"} and _pages_by_id().get(page_id, {}).get("deferred"):
                state["snapshot"] = build_dashboard_snapshot(
                    str(state["snapshot"]["profile_id"]),
                    workspace,
                    bmw_root=bmw_root,
                    ui_mode=_current_theme(),
                    defer_daily_digest=page_id != "daily-digest",
                    defer_team_digest_board=page_id != "team-digest-board",
                )
                _refresh_labels()
            _render_current_page()
            _run_javascript_if_client_alive(
                ui,
                f"window.sgfxFinishTransition && window.sgfxFinishTransition('tab', {json.dumps(page_id)});",
            )

        def _refresh_snapshot(profile_id: str | None = None) -> None:
            current_profile = profile_id if profile_id is not None else str(state["snapshot"]["profile_id"])
            active_page_id = str(state.get("active_page_id", "delivery-checklist"))
            _dashboard_changed_profiles.cache_clear()
            state["snapshot"] = build_dashboard_snapshot(
                current_profile,
                workspace,
                bmw_root=bmw_root,
                ui_mode=_current_theme(),
                defer_daily_digest=active_page_id != "daily-digest",
                defer_team_digest_board=active_page_id != "team-digest-board",
            )
            _refresh_labels()
            _render_current_page()

        def _refresh_current_page() -> None:
            _refresh_snapshot()
            ui.notify("Current page refreshed from read-only sources.")

        def _set_profile(value: str) -> None:
            profile_id = _profile_id_from_select_value(value)
            if profile_id:
                _write_dashboard_profile_preference(workspace, profile_id)
            _refresh_snapshot(profile_id)
            ui.notify(f"Profile switched to {state['snapshot']['profile_id']}.")

        def _install_shortcut_script() -> None:
            messages = {str(item["key"]): str(item["message"]) for item in state["snapshot"]["shortcut_actions"]}
            _run_javascript_if_client_alive(
                ui,
                f"""
                (() => {{
                    const messages = {json.dumps(messages)};
                    const feedbackContext = {json.dumps(feedback_context)};
                    const firstLaunchStorageKey = {json.dumps(FIRST_LAUNCH_DISMISS_STORAGE_KEY)};
                    const functionKeys = Array.from({{ length: 12 }}, (_, index) => `F${{index + 1}}`);
                    let hideTimer = null;
                    document.body.dataset.sgfxActivePage = {json.dumps(state["active_page_id"])};
                    const show = (key, message) => {{
                        const target = document.getElementById('sgfx-shortcut-feedback');
                        if (target) target.textContent = message;
                        const popup = document.getElementById('sgfx-hotkey-popup');
                        if (!popup) return;
                        const keyTarget = popup.querySelector('[data-sgfx-hotkey-key]');
                        const messageTarget = popup.querySelector('[data-sgfx-hotkey-message]');
                        if (keyTarget) keyTarget.textContent = key;
                        if (messageTarget) messageTarget.textContent = message;
                        popup.classList.add('show');
                        if (hideTimer) window.clearTimeout(hideTimer);
                        hideTimer = window.setTimeout(() => popup.classList.remove('show'), 1250);
                    }};
                    window.__sgfxPerformanceTrace = window.__sgfxPerformanceTrace || [];
                    window.sgfxBeginTransition = (kind, label) => {{
                        window.__sgfxTransitionStart = {{
                            kind,
                            label,
                            startedAt: window.performance ? performance.now() : Date.now(),
                        }};
                    }};
                    window.sgfxFinishTransition = (kind, label) => {{
                        const now = window.performance ? performance.now() : Date.now();
                        const start = window.__sgfxTransitionStart || {{ kind, label, startedAt: now }};
                        const duration = Math.max(0, now - Number(start.startedAt || now));
                        const entry = {{
                            kind,
                            label,
                            duration_ms: Number(duration.toFixed(1)),
                            threshold_ms: 200,
                            status: duration > 200 ? 'hitch' : 'ok',
                        }};
                        window.__sgfxPerformanceTrace.push(entry);
                        document.body.dataset.sgfxLastTransitionMs = String(Math.round(duration));
                        document.body.dataset.sgfxLastTransitionStatus = entry.status;
                        if (duration > 200) console.warn('SGFX transition over 200ms', entry);
                        window.__sgfxTransitionStart = null;
                    }};
                    window.sgfxApplyFirstLaunchState = () => {{
                        const dismissed = window.localStorage.getItem(firstLaunchStorageKey) === '1';
                        document.querySelectorAll('[data-sgfx-first-launch-card]').forEach((card) => {{
                            card.dataset.sgfxDismissed = dismissed ? 'true' : 'false';
                        }});
                    }};
                    window.sgfxDismissFirstLaunch = () => {{
                        window.localStorage.setItem(firstLaunchStorageKey, '1');
                        window.sgfxApplyFirstLaunchState();
                    }};
                    window.sgfxBuildFeedbackMailto = () => {{
                        const profile = document.body.dataset.sgfxProfileId || {json.dumps(str(snapshot.get("profile_id", "")))};
                        const page = document.body.dataset.sgfxActivePage || 'unknown';
                        const subject = `SGFX feedback — ${{profile}} — ${{feedbackContext.build_sha || 'unknown'}}`;
                        const body = [
                            'Please describe what happened:',
                            '',
                            'Context:',
                            `Profile: ${{profile}}`,
                            `Dashboard surface: ${{page}}`,
                            `Build SHA: ${{feedbackContext.build_sha || 'unknown'}}`,
                            `.exe SHA: ${{feedbackContext.exe_sha || 'unavailable'}}`,
                            `OS version: ${{feedbackContext.os_version || 'unknown'}}`,
                            '',
                            'No telemetry was sent automatically. Review this message before sending.',
                        ].join('\\r\\n');
                        return `mailto:${{feedbackContext.to || ''}}?subject=${{encodeURIComponent(subject)}}&body=${{encodeURIComponent(body)}}`;
                    }};
                    window.sgfxOpenFeedback = () => {{
                        window.location.href = window.sgfxBuildFeedbackMailto();
                    }};
                    window.sgfxSetSidebarOpen = (open) => {{
                        const isOpen = Boolean(open);
                        document.body.classList.toggle('sgfx-sidebar-open', isOpen);
                        document.body.dataset.sgfxSidebar = isOpen ? 'open' : 'closed';
                    }};
                    window.sgfxToggleSidebar = () => {{
                        window.sgfxSetSidebarOpen(!document.body.classList.contains('sgfx-sidebar-open'));
                    }};
                    window.sgfxSetSidebarOpen(false);
                    if (window.__sgfxDashboardShortcutsInstalled) return;
                    window.__sgfxDashboardShortcutsInstalled = true;
                    window.sgfxApplyFirstLaunchState();
                    document.addEventListener('click', (event) => {{
                        const clickTarget = event.target instanceof Element ? event.target : event.target.parentElement;
                        if (!clickTarget) return;
                        const nav = clickTarget.closest('[data-sgfx-nav-item]');
                        if (nav) window.sgfxBeginTransition('tab', nav.dataset.sgfxNavItem || 'unknown');
                        const wizard = clickTarget.closest('.sgfx-wizard-nav button, .sgfx-html-action-button');
                        if (wizard) window.sgfxBeginTransition('wizard', (wizard.textContent || '').trim() || 'wizard');
                    }}, true);
                    const wizardObserver = new MutationObserver(() => {{
                        const card = document.querySelector('.sgfx-wizard-card');
                        if (card && window.__sgfxTransitionStart && window.__sgfxTransitionStart.kind === 'wizard') {{
                            window.sgfxFinishTransition('wizard', (card.textContent || '').trim().slice(0, 80) || 'wizard');
                        }}
                    }});
                    wizardObserver.observe(document.body, {{ childList: true, subtree: true }});
                    document.addEventListener('keydown', (event) => {{
                        if (!functionKeys.includes(event.key) && event.key !== 'Escape') return;
                        event.preventDefault();
                        if (event.key === 'F1') show('F1', messages.F1);
                        if (event.key === 'F2') {{
                            show('F2', messages.F2);
                            const input = document.querySelector('.sgfx-profile-select input');
                            if (input) input.focus();
                        }}
                        if (event.key === 'F5') {{
                            show('F5', messages.F5);
                            const refresh = document.querySelector('.sgfx-refresh-button');
                            if (refresh) refresh.click();
                        }}
                        if (event.key === 'F12') {{
                            const currentPage = document.body.dataset.sgfxActivePage || 'unknown';
                            show('F12', `${{messages.F12}} Current page: ${{currentPage}}.`);
                        }}
                        if (event.key === 'Escape') {{
                            window.sgfxSetSidebarOpen(false);
                            show('Esc', messages.Esc);
                        }}
                        if (!['F1', 'F2', 'F5', 'F12', 'Escape'].includes(event.key)) {{
                            show(event.key, messages[event.key] || 'No action is assigned to this function key.');
                        }}
                    }});
                }})();
                """
            )

        ui.html(
            f"""
            <button type="button" class="sgfx-menu-button" aria-label="Open navigation" onclick="window.sgfxToggleSidebar && window.sgfxToggleSidebar()">
              &#9776;
            </button>
            <div id="sgfx-hotkey-popup" class="sgfx-hotkey-popup" aria-live="polite">
              <img src="/sgfx-dashboard-assets/{DASHBOARD_DEBUG_ICON_ASSET}" alt="">
              <div>
                <div class="sgfx-hotkey-key" data-sgfx-hotkey-key>F1</div>
                <div class="sgfx-hotkey-message" data-sgfx-hotkey-message>Shortcuts available.</div>
              </div>
            </div>
            <div class="sgfx-sidebar-backdrop" data-sgfx-sidebar-backdrop onclick="window.sgfxSetSidebarOpen && window.sgfxSetSidebarOpen(false)" aria-hidden="true"></div>
            <div class="sgfx-floating-shortcuts" aria-label="Keyboard shortcuts">
              <span>F1 Help</span>
              <span>F12 Diagnostic</span>
              <span>Esc Quit</span>
            </div>
            """,
            sanitize=False,
        )

        with ui.row().classes("sgfx-shell full-width no-wrap"):
            with ui.column().classes("sgfx-sidebar"):
                ui.image(f"/sgfx-dashboard-assets/{DASHBOARD_BRAND_ICON_ASSET}").classes("sgfx-sidebar-logo")
                ui.separator()
                for nav_item in state["snapshot"]["navigation"]:
                    nav_id = str(nav_item["id"])
                    _attach_tooltip(
                        ui,
                        ui.button(
                            str(nav_item["label"]),
                            on_click=lambda page_id=nav_id: _open_page(page_id),
                        ).props(f"flat no-caps align=left data-sgfx-nav-item={nav_id}").classes(
                            "sgfx-nav-button full-width"
                        ),
                        f"Open {nav_item['label']} for the selected local profile.",
                    )
                ui.separator()
                for shortcut in state["snapshot"]["shortcuts"]:
                    ui.label(str(shortcut)).classes("sgfx-shortcut")
            with ui.column().classes("sgfx-main"):
                with ui.row().classes("sgfx-header items-center justify-between full-width"):
                    with ui.row().classes("sgfx-brand-lockup items-center"):
                        ui.image(f"/sgfx-dashboard-assets/{DASHBOARD_BRAND_LOGO_ASSET}").classes("sgfx-brand-logo")
                        with ui.column():
                            controls["profile_label"] = ui.label(_header_text()).classes("sgfx-subtitle")
                            ui.html(
                                '<div id="sgfx-shortcut-feedback" class="sgfx-shortcut-feedback">'
                                "Shortcuts available: F1 help, F2 profile, F5 refresh, F12 diagnostic, Esc quit guidance."
                                "</div>"
                            )
                            registry = state["snapshot"].get("profile_registry", {})
                            controls["profile_registry_label"] = ui.label(
                                str(registry.get("summary", "")) if isinstance(registry, dict) else ""
                            ).classes("sgfx-subtitle")
                    with ui.row().classes("items-center"):
                        ui.label("F1 Help").classes("sgfx-shortcut")
                        ui.label("F12 Diagnostic").classes("sgfx-shortcut")
                        ui.label("Esc Quit").classes("sgfx-shortcut")
                        controls["profile_show_all"] = ui.switch(
                            "Show all profiles",
                            value=bool(state["snapshot"].get("profile_show_all", False)),
                            on_change=lambda _event: _sync_profile_select(),
                        ).props("dense")
                        controls["profile_search"] = ui.input(
                            "Profile search",
                            on_change=lambda _event: _sync_profile_select(),
                        ).props("dense outlined clearable")
                        controls["profile_select"] = _attach_tooltip(
                            ui,
                            ui.select(
                                [
                                    str(option.get("select_label", option.get("id", "")))
                                    for option in (
                                        state["snapshot"]["profile_options_all"]
                                        if state["snapshot"].get("profile_show_all", False)
                                        else state["snapshot"]["profile_options"]
                                    )
                                ],
                                value=(
                                    _select_label_for_profile(str(state["snapshot"]["profile_id"]))
                                    if state["snapshot"]["profile_known"]
                                    else None
                                ),
                                label="Profile",
                                on_change=lambda event: _set_profile(str(event.value or "")),
                            ).props("dense outlined").classes("sgfx-profile-select"),
                            "Switch the local delivery profile without changing source files.",
                        )
                        _attach_tooltip(
                            ui,
                            ui.button("Refresh", on_click=_refresh_current_page).props("flat dense no-caps").classes(
                                "sgfx-refresh-button"
                            ),
                            "Re-read local evidence for the current profile and page.",
                        )
                content = ui.column().classes("sgfx-content")
                content_holder["content"] = content
                _render_current_page()
                with ui.column().classes("sgfx-footer full-width"):
                    with ui.row().classes("sgfx-footer-actions"):
                        _attach_tooltip(
                            ui,
                            ui.html(
                                '<button type="button" class="sgfx-feedback-button" '
                                'data-sgfx-feedback-button="true" '
                                'onclick="window.sgfxOpenFeedback && window.sgfxOpenFeedback()">'
                                "Send feedback</button>",
                                sanitize=False,
                            ),
                            "Open a prefilled email draft. Nothing is sent until the operator reviews it.",
                        )
                    for guardrail in state["snapshot"]["guardrails"]:
                        ui.label(str(guardrail)).classes("sgfx-guardrail")
        _install_shortcut_script()
        _sync_body_context()


def run_dashboard(
    *,
    profile_id: str = "",
    workspace: Path | str,
    bmw_root: Path | str | None = None,
    ui_mode: str | None = None,
    host: str = "127.0.0.1",
    port: int = 0,
    native: bool = True,
    reload: bool = False,
) -> int:
    from sg_preflight.dashboard.dependency import require_nicegui

    try:
        ui, app = require_nicegui()
    except Exception as exc:
        append_startup_log(f"NiceGUI import failed: {type(exc).__name__}: {exc!r}")
        raise
    root = _workspace(workspace)
    try:
        _render_dashboard(ui, app, initial_profile_id=profile_id, workspace=root, bmw_root=bmw_root, ui_mode=ui_mode)
    except Exception as exc:
        append_startup_log(f"dashboard render failed: {type(exc).__name__}: {exc!r}")
        raise
    favicon_path = runtime_asset_path("sgfx_icon.png")
    run_port = _dashboard_run_port(native=native, port=port)
    if native:
        append_startup_log(f"attempting NiceGUI native mode on {host}:{run_port or 'auto'}")
        if not _frozen_native_window_allowed():
            append_startup_log("packaged native window is disabled; browser fallback suppressed for desktop builds")
            raise _packaged_native_unavailable()
        if webview2_runtime_available():
            try:
                native_started_at = monotonic()
                _run_nicegui(
                    ui,
                    host=host,
                    port=run_port,
                    native=True,
                    reload=reload,
                    show=True,
                    favicon_path=favicon_path,
                )
                native_elapsed = monotonic() - native_started_at
                if native_elapsed >= NATIVE_RETURN_FALLBACK_SECONDS:
                    return 0
                append_startup_log(
                    f"native returned after {native_elapsed:.1f}s without a durable window; "
                    "falling back to browser mode"
                )
                if getattr(sys, "frozen", False):
                    append_startup_log("browser fallback suppressed for packaged desktop build")
                    raise _packaged_native_unavailable()
                fallback_port = _dashboard_run_port(native=False, port=port)
                return _launch_browser_fallback_process(
                    profile_id=profile_id,
                    workspace=root,
                    bmw_root=bmw_root,
                    ui_mode=ui_mode,
                    host=host,
                    fallback_port=fallback_port,
                )
            except Exception as exc:
                append_startup_log(f"native failed: {type(exc).__name__}: {exc!r}")
                if getattr(sys, "frozen", False):
                    append_startup_log("browser fallback suppressed for packaged desktop build")
                    raise _packaged_native_unavailable() from exc
                fallback_port = _dashboard_run_port(native=False, port=port)
                return _launch_browser_fallback_process(
                    profile_id=profile_id,
                    workspace=root,
                    bmw_root=bmw_root,
                    ui_mode=ui_mode,
                    host=host,
                    fallback_port=fallback_port,
                )
        else:
            append_startup_log("WebView2 runtime not found; falling back to browser mode")
        if getattr(sys, "frozen", False):
            append_startup_log("browser fallback suppressed for packaged desktop build")
            raise _packaged_native_unavailable()
        fallback_port = _dashboard_run_port(native=False, port=port)
        append_startup_log(f"falling back to browser mode on {host}:{fallback_port}")
        _run_nicegui(
            ui,
            host=host,
            port=fallback_port,
            native=False,
            reload=reload,
            show=True,
            favicon_path=favicon_path,
        )
        return 0

    append_startup_log(f"starting dashboard server mode on {host}:{run_port}")
    _run_nicegui(
        ui,
        host=host,
        port=run_port,
        native=False,
        reload=reload,
        show=_browser_fallback_show_requested(),
        favicon_path=favicon_path,
    )
    return 0
