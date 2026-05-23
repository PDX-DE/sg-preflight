from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
from time import monotonic
from typing import Any, Callable

from sg_preflight.activity_log import append_activity_entry
from sg_preflight.assets import runtime_asset_dir, runtime_asset_path, runtime_asset_root
from sg_preflight.bmw_delivery import read_bmw_screenshot_state
from sg_preflight.daily_digest import build_latest_daily_digest
from sg_preflight.delivery_checklist import read_delivery_checklist
from sg_preflight.delivery_workbook_generation import (
    GENERATE_WORKBOOK_ACTION_ID,
    GENERATE_WORKBOOK_ACTION_LABEL,
    GENERATE_WORKBOOK_TIMEOUT_SECONDS,
    cancel_delivery_workbook_generation,
    check_delivery_workbook_generation_environment,
    poll_delivery_workbook_generation,
    start_delivery_workbook_generation,
)
from sg_preflight.dependency_onboarding import (
    build_dependency_onboarding_status,
    cancel_dependency_setup_action,
    poll_dependency_setup_action,
    start_dependency_setup_action,
)
from sg_preflight.manual_review import (
    QUALITY_HERO_STEPS,
    create_manual_review_session,
    apply_manual_review_suggestions,
    load_manual_review_session,
    record_manual_review_step,
)
from sg_preflight.profiles import list_run_profiles
from sg_preflight.screenshot_capture import (
    SCREENSHOT_CAPTURE_ACTION_ID,
    SCREENSHOT_CAPTURE_ACTION_LABEL,
    SCREENSHOT_CAPTURE_TIMEOUT_SECONDS,
    cancel_screenshot_capture,
    check_screenshot_capture_environment,
    poll_screenshot_capture,
    start_screenshot_capture,
)
from sg_preflight.subprocess_utils import hidden_subprocess_kwargs
from sg_preflight.utils import ensure_parent


DASHBOARD_TITLE = "SGFX"
DASHBOARD_BRAND_LOGO_ASSET = "logo_sgfx.png"
DASHBOARD_BRAND_ICON_ASSET = "sgfx_icon.png"
DASHBOARD_DEBUG_ICON_ASSET = "debug_icon.png"
STARTUP_LOG_NAME = "sgfx-preflight-startup.log"
WEBVIEW2_RUNTIME_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
NATIVE_RETURN_FALLBACK_SECONDS = 5.0
BROWSER_FALLBACK_ENV = "SGFX_PREFLIGHT_BROWSER_FALLBACK"
FORCE_FROZEN_NATIVE_ENV = "SGFX_PREFLIGHT_FORCE_FROZEN_NATIVE"
DASHBOARD_GUARDRAILS = (
    "Manual review remains required.",
    "Decision: not approval — evidence only.",
    "BMW Git access is read-only. SGFX never modifies BMW source.",
    "Activity log is local-only — never posted to Jira, SVN, or BMW Git.",
)
DASHBOARD_NAVIGATION = (
    ("delivery-checklist", "Delivery Checklist"),
    ("screenshot-test-state", "Screenshot Test State"),
    ("daily-digest", "Daily Digest"),
    ("manual-review", "Manual Review Companion"),
    ("about", "About"),
)
DASHBOARD_SHORTCUTS = ("F1 Help", "F2 Profile switch", "F5 Refresh page", "F12 Diagnostic", "Esc Quit")
DASHBOARD_SHORTCUT_ACTIONS = (
    ("F1", "Help: use the sidebar pages to inspect read-only SGFX evidence."),
    ("F2", "Profile switch: use the Profile selector in the header."),
    ("F5", "Refresh page: re-read the current profile evidence."),
    ("F12", "Diagnostic: profile, workspace, and current page are shown in the header."),
    ("Esc", "Quit: close the native window or browser tab when the local review is done."),
)
THEME_CHOICES = ["clean"]

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
        ("PDX Seriengrafik onboarding (laptop setup)", "003_Onboarding/005_How-to-set-up-your-Laptop"),
        ("BMW Git access", "003_Onboarding/013_How-to-access-BMW-GIT"),
        ("Git workflow", "003_Onboarding/015_How-to-Git"),
        ("Blender 4 + SGToolkit setup", "139_3D-Car/.../266_How-to-Setup-Blender-4-and-SGToolkit-1.0"),
        ("Delivery checklist (env var)", "311_Delivery-process/.../315_How-to-3D-Cars-Delivery-Checklist----v0"),
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
DAILY_DIGEST_EMPTY_NOTE = (
    "No review package on this workspace yet. Click Build to generate one for the active ticket."
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
    return "parent slot" in message and "deleted" in message


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

    if getattr(sys, "frozen", False):
        command = [sys.executable, "dashboard", "run"]
    else:
        command = [sys.executable, "-B", "-m", "sg_preflight", "dashboard", "run"]
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


def dashboard_profile_options() -> list[dict[str, str]]:
    return [{"id": profile.profile_id, "label": profile.label} for profile in list_run_profiles()]


def _resolve_dashboard_profile_id(
    profile_id: str | None,
    options: list[dict[str, str]],
    *,
    workspace: Path | str | None = None,
) -> str:
    requested = str(profile_id or "").strip()
    if not requested:
        preferred = _dashboard_preferred_profile_id(workspace, options) if workspace is not None else ""
        if preferred:
            return preferred
        return options[0]["id"] if options else ""
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
    page["setup_status"] = setup_status or build_dependency_onboarding_status(workspace=workspace, bmw_root=bmw_root)
    if page.get("status") != "unavailable":
        return page
    page["empty_state_note"] = DELIVERY_CHECKLIST_EMPTY_NOTE
    preflight = check_delivery_workbook_generation_environment(
        profile_id=profile_id,
        workspace=workspace,
        bmw_root=bmw_root,
    )
    page["actions"] = [
        {
            "id": GENERATE_WORKBOOK_ACTION_ID,
            "label": GENERATE_WORKBOOK_ACTION_LABEL,
            "requires_confirmation": True,
            "timeout_seconds": GENERATE_WORKBOOK_TIMEOUT_SECONDS,
            "preflight": preflight,
            "disabled": not bool(preflight.get("can_run", False)),
            "confirmation_message": str(preflight.get("confirmation_message", "")),
        }
    ]
    return page


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
        }
    ]
    return page


def _payload_items(payload: dict[str, Any]) -> list[dict[str, str]]:
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
    )
    return {key: payload[key] for key in allowed if key in payload}


DAILY_DIGEST_BUILD_PACKAGE_ACTION_ID = "build-review-package"
DAILY_DIGEST_BUILD_PACKAGE_ACTION_LABEL = "Build review package for this workspace"
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
    actions = [
        {
            "id": DAILY_DIGEST_BUILD_PACKAGE_ACTION_ID,
            "label": DAILY_DIGEST_BUILD_PACKAGE_ACTION_LABEL,
            "requires_ticket_id": True,
            "ticket_id_hint": ticket_hint or DAILY_DIGEST_TICKET_ID_PLACEHOLDER,
            "ticket_id_default": default_ticket,
            "ticket_id_source": str(context.get("ticket_id_source", "manual_entry")),
            "recent_ticket_ids": list(context.get("recent_ticket_ids", [])),
        }
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
) -> dict[str, Any]:
    session = _load_manual_review_dashboard_session(profile_id=profile_id, workspace=workspace)
    if session is not None:
        return session
    return create_manual_review_session(
        profile_id=profile_id,
        ticket_id=(ticket_id or _dashboard_active_ticket_id(workspace)),
        workspace=workspace,
        session_id=_manual_review_dashboard_session_id(profile_id),
    )


def _manual_review_step_recorded(step: dict[str, Any]) -> bool:
    return str(step.get("verdict", _MANUAL_REVIEW_PENDING_VERDICT)).strip() != _MANUAL_REVIEW_PENDING_VERDICT


def _manual_review_step_detail(step: dict[str, Any]) -> str:
    if not _manual_review_step_recorded(step):
        suggested = str(step.get("suggested_verdict", "")).strip()
        reason = str(step.get("suggestion_reason", "")).strip()
        if suggested:
            return f"Suggested: {suggested}. {reason}".strip()
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
    steps = apply_manual_review_suggestions(steps, profile_id=profile_id, workspace=workspace)
    recorded_count = sum(1 for step in steps if isinstance(step, dict) and _manual_review_step_recorded(step))
    status = "recorded" if recorded_count else _MANUAL_REVIEW_PENDING_VERDICT
    session_payload = session if isinstance(session, dict) else {}
    ticket_id = active_ticket_id.strip() or _dashboard_active_ticket_id(workspace)
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
        },
    }
    if status == _MANUAL_REVIEW_PENDING_VERDICT:
        page["empty_state_note"] = MANUAL_REVIEW_EMPTY_NOTE
    return page


def build_dashboard_snapshot(
    profile_id: str,
    workspace: Path | str,
    *,
    bmw_root: Path | str | None = None,
    ui_mode: str | None = None,
) -> dict[str, Any]:
    root = _workspace(workspace)
    profile_options = dashboard_profile_options()
    resolved_profile_id = _resolve_dashboard_profile_id(profile_id, profile_options, workspace=root)
    profile_known = _dashboard_profile_known(resolved_profile_id, profile_options)
    theme = _clean_theme(ui_mode or load_dashboard_preference(root))
    setup_status = build_dependency_onboarding_status(workspace=root, bmw_root=bmw_root)
    active_ticket_id = _dashboard_active_ticket_id(root)
    daily_ticket_context = _daily_digest_ticket_context(root)
    return {
        "title": DASHBOARD_TITLE,
        "profile_id": resolved_profile_id,
        "profile_known": profile_known,
        "profile_warning": ""
        if profile_known
        else f"Profile {resolved_profile_id} is not in the current profile registry. Select a registered profile or check config.",
        "profile_options": profile_options,
        "workspace": str(root),
        "workspace_label": _path_label(root),
        "theme": theme,
        "navigation": [{"id": page_id, "label": label} for page_id, label in DASHBOARD_NAVIGATION],
        "shortcuts": list(DASHBOARD_SHORTCUTS),
        "shortcut_actions": [{"key": key, "message": message} for key, message in DASHBOARD_SHORTCUT_ACTIONS],
        "guardrails": list(DASHBOARD_GUARDRAILS),
        "welcome": {
            "show": bool(setup_status.get("first_run")),
            "title": "Welcome",
            "summary": (
                "Local-only tool for collecting SGFX delivery evidence. "
                "Run setup before invoking local BMW pipeline helpers."
            ),
            "setup_page_id": "delivery-checklist",
            "setup_action_count": len(
                [action for action in setup_status.get("actions", []) if isinstance(action, dict)]
            ),
            "setup_complete_note": SETUP_COMPLETE_NOTE,
            "guardrails": list(DASHBOARD_GUARDRAILS),
        },
        "pages": [
            _delivery_checklist_page(resolved_profile_id, root, bmw_root=bmw_root, setup_status=setup_status),
            _screenshot_test_state_page(resolved_profile_id, root, bmw_root=bmw_root),
            _daily_digest_page(
                root,
                resolved_profile_id,
                active_ticket_id=active_ticket_id,
                ticket_context=daily_ticket_context,
            ),
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


def _validate_review_package_inputs(workspace: Path | str, profile_id: str, ticket_id: str) -> tuple[Path, str, str]:
    clean_ticket = ticket_id.strip()
    if not clean_ticket:
        raise ValueError("Ticket ID required to build a review package.")
    clean_profile = profile_id.strip()
    if not clean_profile:
        raise ValueError("Profile ID required to build a review package.")
    return Path(workspace).resolve(), clean_profile, clean_ticket


def _dashboard_review_package_command(*, workspace: Path, profile_id: str, ticket_id: str) -> list[str]:
    return [
        sys.executable,
        "-B",
        "-m",
        "sg_preflight",
        "ticket-review",
        ticket_id,
        "--workspace",
        str(workspace),
        "--profile-ids",
        profile_id,
        "--json",
    ]


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
    started_wall_time = time.time()
    started_monotonic = time.monotonic()
    with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
        process = subprocess.Popen(
            command,
            cwd=workspace_path,
            stdin=subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=stderr_handle,
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


def _render_status_chip(ui: Any, status: str) -> None:
    ui.badge(status or "unknown").classes("sgfx-status")


def _attach_tooltip(ui: Any, element: Any, text: str) -> Any:
    with element:
        ui.tooltip(text).classes("sgfx-thinking-tooltip")
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


def _render_first_run_welcome(ui: Any, snapshot: dict[str, Any], open_setup: Callable[[], None] | None = None) -> None:
    welcome = snapshot.get("welcome", {})
    if not isinstance(welcome, dict) or not welcome.get("show"):
        return
    with ui.column().classes("sgfx-page-panel"):
        with ui.row().classes("items-center justify-between full-width"):
            ui.label(str(welcome.get("title", "Welcome"))).classes("sgfx-panel-title")
            _render_status_chip(ui, "incomplete")
        ui.label(str(welcome.get("summary", ""))).classes("sgfx-summary")
        for guardrail in welcome.get("guardrails", []):
            ui.label(str(guardrail)).classes("sgfx-guardrail")
        setup_action_count = int(welcome.get("setup_action_count", 0) or 0)
        if open_setup is not None and setup_action_count > 0:
            _attach_tooltip(
                ui,
                ui.button("Run setup", on_click=open_setup).props("color=primary"),
                "Open the dependency setup card; no system changes run without confirmation.",
            )
        elif setup_action_count == 0:
            ui.label(str(welcome.get("setup_complete_note", SETUP_COMPLETE_NOTE))).classes("sgfx-muted")


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
        for guardrail in DASHBOARD_GUARDRAILS:
            ui.label(str(guardrail)).classes("sgfx-guardrail")


def _render_setup_status_panel(ui: Any, setup_status: dict[str, Any], workspace: Path) -> None:
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
                status_label.text = f"Setup {outcome}. {result.get('summary', '')} Refresh to re-read dependency status."
                ui.notify(f"Dependency setup {outcome}.")
            except RuntimeError as exc:
                if not _parent_slot_deleted(exc):
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
                    source_supported = action_id in {"setup-raco-from-shared-tools", "setup-blender-411"}
                    source_required = action_id == "setup-raco-from-shared-tools"
                    target_required = action_id in {
                        "setup-raco-from-shared-tools",
                        "clone-digital-3d-car-repo",
                        "setup-digital-3d-car-repo",
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


def _render_delivery_checklist_panel(ui: Any, snapshot: dict[str, Any], workspace: Path) -> None:
    page = next(page for page in snapshot["pages"] if page["id"] == "delivery-checklist")
    setup_status = page.get("setup_status", {})
    if isinstance(setup_status, dict):
        _render_setup_status_panel(ui, setup_status, workspace)
    with ui.column().classes("sgfx-page-panel"):
        with ui.row().classes("items-center justify-between full-width"):
            ui.label(str(page["title"])).classes("sgfx-panel-title")
            _render_status_chip(ui, str(page.get("status", "unknown")))
        ui.label(str(page["tagline"])).classes("sgfx-panel-tagline")
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


def _render_daily_digest_panel(ui: Any, snapshot: dict[str, Any], workspace: Path) -> None:
    page = next(page for page in snapshot["pages"] if page["id"] == "daily-digest")
    with ui.column().classes("sgfx-page-panel"):
        with ui.row().classes("items-center justify-between full-width"):
            ui.label(str(page["title"])).classes("sgfx-panel-title")
            _render_status_chip(ui, str(page.get("status", "unknown")))
        ui.label(str(page["tagline"])).classes("sgfx-panel-tagline")
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


def _render_manual_review_panel(ui: Any, snapshot: dict[str, Any], workspace: Path) -> None:
    page = next(page for page in snapshot["pages"] if page["id"] == "manual-review")
    with ui.column().classes("sgfx-page-panel"):
        with ui.row().classes("items-center justify-between full-width"):
            ui.label(str(page["title"])).classes("sgfx-panel-title")
            _render_status_chip(ui, str(page.get("status", "unknown")))
        ui.label(str(page["tagline"])).classes("sgfx-panel-tagline")
        ui.label("Manual review remains required. Decision: not approval — evidence only.").classes("sgfx-summary")
        _render_empty_state_note(ui, page)
        if page.get("status") == _MANUAL_REVIEW_PENDING_VERDICT:
            def _start_session() -> None:
                _ensure_manual_review_dashboard_session(
                    profile_id=str(snapshot["profile_id"]),
                    workspace=workspace,
                )
                ui.notify("Manual-review session started locally.")

            _attach_tooltip(
                ui,
                ui.button("Start Session", on_click=_start_session).props("flat no-caps"),
                "Create the local manual-review session before recording step evidence.",
            )
        for step in page["payload"]["steps"]:
            slug = str(step.get("slug", ""))
            with ui.expansion(str(step.get("title", slug)), icon="fact_check").classes("sgfx-step"):
                focus = ", ".join(str(item) for item in step.get("review_focus", []) if str(item).strip())
                if focus:
                    ui.label(f"Review focus: {focus}").classes("sgfx-summary")
                ui.label(str(step.get("evidence_prompt", ""))).classes("sgfx-muted")
                current_verdict = str(step.get("verdict", "")).strip()
                suggested_verdict = str(step.get("suggested_verdict", "")).strip()
                suggestion_reason = str(step.get("suggestion_reason", "")).strip()
                if suggested_verdict:
                    ui.label(
                        f"Suggested: {suggested_verdict}. Operator confirms or overrides. {suggestion_reason}".strip()
                    ).classes("sgfx-muted")
                verdict_value = (
                    current_verdict
                    if current_verdict in MANUAL_REVIEW_RECORD_VERDICTS
                    else suggested_verdict if suggested_verdict in MANUAL_REVIEW_RECORD_VERDICTS else None
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
                    suggested_verdict: str = suggested_verdict,
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
                        suggested_verdict=suggested_verdict,
                    )
                    ui.notify("Manual-review evidence recorded locally.")

                _attach_tooltip(
                    ui,
                    ui.button("Record", on_click=_record).props("color=primary"),
                    "Record the operator verdict locally for this manual-review step.",
                )


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
        if page_id == "delivery-checklist":
            _render_delivery_checklist_panel(ui, snapshot, workspace)
        elif page_id == "screenshot-test-state":
            _render_screenshot_test_state_panel(ui, snapshot, workspace)
        elif page_id == "manual-review":
            _render_manual_review_panel(ui, snapshot, workspace)
        elif page_id == "daily-digest":
            _render_daily_digest_panel(ui, snapshot, workspace)
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
    base_snapshot = build_dashboard_snapshot(initial_profile_id, workspace, bmw_root=bmw_root, ui_mode=ui_mode)

    @ui.page("/")
    def _index(profile: str = "") -> None:
        query_profile = str(profile or "").strip()
        snapshot = (
            build_dashboard_snapshot(query_profile, workspace, bmw_root=bmw_root, ui_mode=ui_mode)
            if query_profile
            else dict(base_snapshot)
        )
        snapshot["theme"] = _clean_theme(ui_mode or load_dashboard_preference(workspace))
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
            .sgfx-sidebar { width: 292px; min-height: 100vh; padding: 22px 16px; background: var(--sgfx-bg-elev); border-right: 1px solid var(--sgfx-border); gap: 10px; }
            .sgfx-sidebar-logo { width: 200px; max-width: 100%; height: auto; object-fit: contain; margin: 4px 0 14px 0; }
            .sgfx-nav-button { justify-content: flex-start; border-radius: 6px; color: var(--sgfx-fg) !important; }
            .sgfx-nav-button:hover { background: var(--sgfx-accent-soft) !important; }
            .sgfx-shortcut { color: var(--sgfx-fg-muted); font-size: 12px; line-height: 1.5; }
            .sgfx-main { flex: 1; min-width: 0; padding: 24px 28px; gap: 18px; background: var(--sgfx-bg); }
            .sgfx-header { border-bottom: 1px solid var(--sgfx-border); padding-bottom: 14px; }
            .sgfx-subtitle { color: var(--sgfx-fg-muted); font-size: 13px; }
            .sgfx-brand-lockup { gap: 14px; }
            .sgfx-brand-logo { height: 96px; max-width: 360px; width: auto; object-fit: contain; flex: 0 0 auto; }
            .sgfx-about-logo { width: 240px; max-width: 42vw; height: auto; object-fit: contain; flex: 0 0 auto; }
            .sgfx-content { width: 100%; }
            .sgfx-footer { border-top: 1px solid var(--sgfx-border); padding-top: 12px; margin-top: 12px; }
            .sgfx-guardrail { color: var(--sgfx-fg-muted); font-size: 13px; line-height: 1.55; }
            .sgfx-page-panel { border-radius: 8px; box-shadow: none; border: 1px solid var(--sgfx-border); width: 100%; padding: 18px; background: var(--sgfx-bg-panel); color: var(--sgfx-fg); margin-bottom: 14px; }
            .sgfx-panel-title { font-size: 18px; font-weight: 650; color: var(--sgfx-fg-strong); }
            .sgfx-panel-tagline, .sgfx-muted { color: var(--sgfx-fg-muted); font-size: 13px; }
            .sgfx-summary { color: var(--sgfx-fg); font-size: 14px; line-height: 1.55; }
            .sgfx-warning { border: 1px solid var(--sgfx-warning-border); background: var(--sgfx-warning-bg); color: var(--sgfx-warning-fg); border-radius: 6px; padding: 9px 12px; }
            .sgfx-shortcut-feedback { min-height: 22px; color: var(--sgfx-fg-muted); font-size: 13px; padding: 2px 0; }
            .sgfx-profile-select { min-width: 144px; }
            .sgfx-status { text-transform: none; }
            .sgfx-table { width: 100%; color: var(--sgfx-fg); }
            .sgfx-step { border: 1px solid var(--sgfx-border); border-radius: 8px; margin: 8px 0; background: var(--sgfx-bg-elev); }
            .sgfx-live-output textarea { min-height: 160px; font-family: 'Cascadia Mono', Consolas, 'Courier New', monospace; font-size: 12px; line-height: 1.45; background: var(--sgfx-bg) !important; color: var(--sgfx-fg) !important; }
            .sgfx-file-activity { max-height: 160px; overflow-y: auto; border: 1px solid var(--sgfx-border); border-radius: 6px; padding: 8px; background: var(--sgfx-bg-elev); }
            .sgfx-thinking-tooltip { background: #121b1f !important; color: #f4fbf7 !important; border: 1px solid var(--sgfx-accent) !important; border-radius: 8px !important; padding: 8px 10px !important; box-shadow: 0 10px 28px rgba(0, 0, 0, 0.32); animation: sgfx-tooltip-pop 150ms ease-out; }
            .sgfx-thinking-tooltip::before { content: ""; display: inline-block; width: 8px; height: 8px; margin-right: 7px; border-radius: 50%; background: var(--sgfx-accent); animation: sgfx-tooltip-pulse 900ms ease-in-out infinite; vertical-align: middle; }
            .sgfx-hotkey-popup { position: fixed; top: 82px; right: 36px; z-index: 9000; min-width: 280px; max-width: 380px; display: flex; align-items: center; gap: 14px; padding: 14px 16px; border: 1px solid var(--sgfx-accent); border-radius: 8px; background: rgba(18, 27, 31, 0.96); color: var(--sgfx-fg); opacity: 0; transform: translateY(-8px) scale(0.98); pointer-events: none; transition: opacity 150ms ease-out, transform 150ms ease-out; box-shadow: 0 16px 42px rgba(0, 0, 0, 0.38); }
            .sgfx-hotkey-popup.show { opacity: 1; transform: translateY(0) scale(1); }
            .sgfx-hotkey-popup img { width: 96px; height: 96px; object-fit: contain; animation: sgfx-hotkey-pulse 900ms ease-in-out infinite; flex: 0 0 auto; }
            .sgfx-hotkey-key { color: var(--sgfx-fg-strong); font-size: 14px; font-weight: 650; }
            .sgfx-hotkey-message { color: var(--sgfx-fg-muted); font-size: 13px; line-height: 1.45; }
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

        def _pages_by_id() -> dict[str, dict[str, Any]]:
            return {str(page["id"]): page for page in state["snapshot"]["pages"]}

        def _current_theme() -> str:
            return str(state["snapshot"].get("theme", "clean"))

        def _header_text() -> str:
            active = state["snapshot"]
            return f"Profile: {active['profile_id']} | Workspace: {active['workspace_label']}"

        def _refresh_labels() -> None:
            profile_label = controls.get("profile_label")
            if profile_label is not None:
                profile_label.set_text(_header_text())

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
                )
                if active_page_id == "delivery-checklist":
                    _render_delivery_checklist_panel(ui, state["snapshot"], workspace)
                elif active_page_id == "screenshot-test-state":
                    _render_screenshot_test_state_panel(ui, state["snapshot"], workspace, bmw_root=bmw_root)
                elif active_page_id == "daily-digest":
                    _render_daily_digest_panel(ui, state["snapshot"], workspace)
                elif active_page_id == "manual-review":
                    _render_manual_review_panel(ui, state["snapshot"], workspace)
                elif active_page_id == "about":
                    _render_about_panel(ui, ABOUT_CONTENT)
                else:
                    _render_page_panel(ui, _pages_by_id()[active_page_id])

        def _open_page(page_id: str) -> None:
            state["active_page_id"] = page_id
            ui.run_javascript(f"document.body.dataset.sgfxActivePage = {json.dumps(page_id)};")
            _render_current_page()

        def _refresh_snapshot(profile_id: str | None = None) -> None:
            current_profile = profile_id if profile_id is not None else str(state["snapshot"]["profile_id"])
            state["snapshot"] = build_dashboard_snapshot(
                current_profile,
                workspace,
                bmw_root=bmw_root,
                ui_mode=_current_theme(),
            )
            _refresh_labels()
            _render_current_page()

        def _refresh_current_page() -> None:
            _refresh_snapshot()
            ui.notify("Current page refreshed from read-only sources.")

        def _set_profile(value: str) -> None:
            _refresh_snapshot(value)
            ui.notify(f"Profile switched to {state['snapshot']['profile_id']}.")

        def _install_shortcut_script() -> None:
            messages = {str(item["key"]): str(item["message"]) for item in state["snapshot"]["shortcut_actions"]}
            ui.run_javascript(
                f"""
                (() => {{
                    const messages = {json.dumps(messages)};
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
                    if (window.__sgfxDashboardShortcutsInstalled) return;
                    window.__sgfxDashboardShortcutsInstalled = true;
                    document.addEventListener('keydown', (event) => {{
                        if (!['F1', 'F2', 'F5', 'F12', 'Escape'].includes(event.key)) return;
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
                        if (event.key === 'Escape') show('Esc', messages.Esc);
                    }});
                }})();
                """
            )

        ui.html(
            f"""
            <div id="sgfx-hotkey-popup" class="sgfx-hotkey-popup" aria-live="polite">
              <img src="/sgfx-dashboard-assets/{DASHBOARD_DEBUG_ICON_ASSET}" alt="">
              <div>
                <div class="sgfx-hotkey-key" data-sgfx-hotkey-key>F1</div>
                <div class="sgfx-hotkey-message" data-sgfx-hotkey-message>Shortcuts available.</div>
              </div>
            </div>
            """
        )

        with ui.row().classes("sgfx-shell full-width no-wrap"):
            with ui.column().classes("sgfx-sidebar"):
                ui.image(f"/sgfx-dashboard-assets/{DASHBOARD_BRAND_ICON_ASSET}").classes("sgfx-sidebar-logo")
                ui.separator()
                for nav_item in state["snapshot"]["navigation"]:
                    _attach_tooltip(
                        ui,
                        ui.button(
                            str(nav_item["label"]),
                            on_click=lambda page_id=str(nav_item["id"]): _open_page(page_id),
                        ).props("flat no-caps align=left").classes("sgfx-nav-button full-width"),
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
                    with ui.row().classes("items-center"):
                        ui.label("F1 Help").classes("sgfx-shortcut")
                        ui.label("F12 Diagnostic").classes("sgfx-shortcut")
                        ui.label("Esc Quit").classes("sgfx-shortcut")
                        controls["profile_select"] = _attach_tooltip(
                            ui,
                            ui.select(
                                [str(option["id"]) for option in state["snapshot"]["profile_options"]],
                                value=str(state["snapshot"]["profile_id"]) if state["snapshot"]["profile_known"] else None,
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
                    for guardrail in state["snapshot"]["guardrails"]:
                        ui.label(str(guardrail)).classes("sgfx-guardrail")
        _install_shortcut_script()


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
