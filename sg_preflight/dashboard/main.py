from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from time import monotonic
from typing import Any, Callable

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
    load_manual_review_session,
    record_manual_review_step,
)
from sg_preflight.profiles import list_run_profiles
from sg_preflight.utils import ensure_parent


DASHBOARD_TITLE = "SGFX"
DASHBOARD_BRAND_LOGO_ASSET = "framework_sgfx_logo.png"
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
        ("framework_sgfx_logo.png", "primary brand lockup, header surface"),
        ("logo_sgfx.png", "compact brand mark, alternate panels"),
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
#   sidebar header (Clean):        sgfx_icon.png        ~132 x auto  px
#   main header (Clean):           framework_sgfx_logo.png  ~72 x 72 px (currently 52 px — too small)
#   Grafiks shell HeaderBanner:    framework_sgfx_logo.png  62 x 62 px (existing)
#   About panel hero (Clean):      framework_sgfx_logo.png  ~160 x auto px
#   Window taskbar (.ico):         exe_ico.ico              setWindowIcon(QIcon(exe_ico.ico))
#   Hotkey popup (Clean + Grafiks): debug_icon.png          ~96 x 96 px animated overlay
MANUAL_REVIEW_STATUSES = ["not_run", "recorded", "incomplete"]
MANUAL_REVIEW_RECORD_VERDICTS = ["passed", "failed", "skipped", "incomplete"]
MANUAL_REVIEW_DASHBOARD_TICKET_ID = "IDCEVODEV-977874"
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


def _resolve_dashboard_profile_id(profile_id: str | None, options: list[dict[str, str]]) -> str:
    requested = str(profile_id or "").strip()
    if not requested:
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


def load_dashboard_preference(workspace: Path | str) -> str:
    path = _operator_state_path(workspace, "dashboard_preferences.json")
    if not path.is_file():
        return "clean"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return "clean"
    if not isinstance(payload, dict):
        return "clean"
    return _clean_theme(str(payload.get("theme", "clean")))


def save_dashboard_preference(workspace: Path | str, theme: str) -> dict[str, str]:
    payload = {"theme": _clean_theme(theme), "updated_at_utc": _utc_now()}
    path = _operator_state_path(workspace, "dashboard_preferences.json")
    ensure_parent(path)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


SCREENSHOT_TEST_STATE_OWNERSHIP_NOTE = (
    "Screenshot capture runs from the BMW Git pipeline (`ci/scripts/car_manager.py screenshots`); "
    "SGFX reads the output."
)


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
    return {
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
    preflight = check_delivery_workbook_generation_environment(profile_id=profile_id, workspace=workspace)
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
) -> dict[str, Any]:
    actions = [
        {
            "id": DAILY_DIGEST_BUILD_PACKAGE_ACTION_ID,
            "label": DAILY_DIGEST_BUILD_PACKAGE_ACTION_LABEL,
            "requires_ticket_id": True,
            "ticket_id_hint": active_ticket_id.strip() or DAILY_DIGEST_TICKET_ID_PLACEHOLDER,
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
            "payload": {"profile_id": profile_id, "active_ticket_id": active_ticket_id.strip()},
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
    return {
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
            "active_ticket_id": active_ticket_id.strip(),
        },
    }


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
) -> dict[str, Any]:
    session = _load_manual_review_dashboard_session(profile_id=profile_id, workspace=workspace)
    if session is not None:
        return session
    return create_manual_review_session(
        profile_id=profile_id,
        ticket_id=MANUAL_REVIEW_DASHBOARD_TICKET_ID,
        workspace=workspace,
        session_id=_manual_review_dashboard_session_id(profile_id),
    )


def _manual_review_step_recorded(step: dict[str, Any]) -> bool:
    return str(step.get("verdict", _MANUAL_REVIEW_PENDING_VERDICT)).strip() != _MANUAL_REVIEW_PENDING_VERDICT


def _manual_review_step_detail(step: dict[str, Any]) -> str:
    if not _manual_review_step_recorded(step):
        return str(step.get("evidence_prompt", ""))
    verdict = str(step.get("verdict", "")).strip()
    recorded_at = str(step.get("recorded_at_utc", "")).strip()
    note = str(step.get("note", "")).strip()
    pieces = [item for item in (verdict, recorded_at, note) if item]
    return " | ".join(pieces)


def _manual_review_page(profile_id: str, workspace: Path | str) -> dict[str, Any]:
    session = _load_manual_review_dashboard_session(profile_id=profile_id, workspace=workspace)
    steps = (
        list(session.get("steps", []))
        if isinstance(session, dict)
        else [step.to_session_step() for step in QUALITY_HERO_STEPS]
    )
    recorded_count = sum(1 for step in steps if isinstance(step, dict) and _manual_review_step_recorded(step))
    status = "recorded" if recorded_count else _MANUAL_REVIEW_PENDING_VERDICT
    session_payload = session if isinstance(session, dict) else {}
    return {
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
            "ticket_id": str(session_payload.get("ticket_id", MANUAL_REVIEW_DASHBOARD_TICKET_ID)),
            "session_path": str(session_payload.get("session_path", "")),
            "markdown_path": str(session_payload.get("markdown_path", "")),
            "steps": steps,
        },
    }


def build_dashboard_snapshot(
    profile_id: str,
    workspace: Path | str,
    *,
    bmw_root: Path | str | None = None,
    ui_mode: str | None = None,
) -> dict[str, Any]:
    root = _workspace(workspace)
    profile_options = dashboard_profile_options()
    resolved_profile_id = _resolve_dashboard_profile_id(profile_id, profile_options)
    profile_known = _dashboard_profile_known(resolved_profile_id, profile_options)
    theme = _clean_theme(ui_mode or load_dashboard_preference(root))
    setup_status = build_dependency_onboarding_status(workspace=root, bmw_root=bmw_root)
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
            "guardrails": list(DASHBOARD_GUARDRAILS),
        },
        "pages": [
            _delivery_checklist_page(resolved_profile_id, root, bmw_root=bmw_root, setup_status=setup_status),
            _reader_page(
                page_id="screenshot-test-state",
                title="Screenshot Test State",
                tagline="BMW + MINI baseline / actual / diff counts per brand.",
                reader=lambda: read_bmw_screenshot_state(
                    resolved_profile_id,
                    workspace=Path(bmw_root).resolve() if bmw_root else root,
                    sg_project_root=root,
                ),
                workspace=root,
                ownership_note=SCREENSHOT_TEST_STATE_OWNERSHIP_NOTE,
            ),
            _daily_digest_page(root, resolved_profile_id),
            _manual_review_page(resolved_profile_id, root),
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
    )


_BUILD_PACKAGE_TIMEOUT_SECONDS = 600


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
    from sg_preflight.subprocess_utils import hidden_subprocess_kwargs

    command = [
        sys.executable,
        "-B",
        "-m",
        "sg_preflight",
        "ticket-review",
        clean_ticket,
        "--workspace",
        str(workspace_path),
        "--profile-ids",
        clean_profile,
        "--json",
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
        **hidden_subprocess_kwargs(),
    )
    outcome = "recorded" if completed.returncode == 0 else "failed"
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
        if open_setup is not None:
            _attach_tooltip(
                ui,
                ui.button("Run setup", on_click=open_setup).props("color=primary"),
                "Open the dependency setup card; no system changes run without confirmation.",
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
                    source_required = action_id in {"setup-raco-from-shared-tools", "setup-blender-411"}
                    target_required = action_id in {
                        "setup-raco-from-shared-tools",
                        "clone-digital-3d-car-repo",
                        "setup-digital-3d-car-repo",
                    }
                    source_input = None
                    target_input = None
                    if source_required:
                        source_input = _attach_tooltip(
                            ui,
                            ui.input(
                                "Source path",
                                value=str(action.get("source_path", "")),
                            ).classes("full-width"),
                            "Select the operator-approved local source for this setup action.",
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


def _render_daily_digest_panel(ui: Any, snapshot: dict[str, Any], workspace: Path) -> None:
    page = next(page for page in snapshot["pages"] if page["id"] == "daily-digest")
    with ui.column().classes("sgfx-page-panel"):
        with ui.row().classes("items-center justify-between full-width"):
            ui.label(str(page["title"])).classes("sgfx-panel-title")
            _render_status_chip(ui, str(page.get("status", "unknown")))
        ui.label(str(page["tagline"])).classes("sgfx-panel-tagline")
        ui.label(str(page.get("summary", ""))).classes("sgfx-summary")
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
            ticket_input = ui.input(label="Ticket ID", placeholder=hint).classes("full-width")
            status_label = ui.label("Local-only: this runs the read-only `ticket-review` CLI in the background.").classes(
                "sgfx-muted"
            )

            def _build(ticket_input=ticket_input, status_label=status_label) -> None:
                ticket_value = str(ticket_input.value or "").strip()
                if not ticket_value:
                    ui.notify("Enter a ticket ID before building a review package.")
                    return
                status_label.text = f"Building review package for {ticket_value}..."
                try:
                    result = build_dashboard_review_package(
                        workspace=workspace,
                        profile_id=str(snapshot["profile_id"]),
                        ticket_id=ticket_value,
                    )
                except Exception as exc:  # noqa: BLE001
                    status_label.text = f"Build failed: {exc}"
                    ui.notify("Build review package failed.")
                    return
                outcome = result.get("outcome", "unknown")
                exit_code = result.get("exit_code", "?")
                status_label.text = (
                    f"Build {outcome} (exit {exit_code}) for {ticket_value}. Refresh to reload digest evidence."
                )
                ui.notify(f"Build review package {outcome}.")

            _attach_tooltip(
                ui,
                ui.button(str(action.get("label", DAILY_DIGEST_BUILD_PACKAGE_ACTION_LABEL)), on_click=_build).props(
                    "color=primary"
                ),
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
        for step in page["payload"]["steps"]:
            slug = str(step.get("slug", ""))
            with ui.expansion(str(step.get("title", slug)), icon="fact_check").classes("sgfx-step"):
                focus = ", ".join(str(item) for item in step.get("review_focus", []) if str(item).strip())
                if focus:
                    ui.label(f"Review focus: {focus}").classes("sgfx-summary")
                ui.label(str(step.get("evidence_prompt", ""))).classes("sgfx-muted")
                current_verdict = str(step.get("verdict", "")).strip()
                verdict_value = current_verdict if current_verdict in MANUAL_REVIEW_RECORD_VERDICTS else None
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

                def _record(slug: str = slug, verdict=verdict, note=note) -> None:
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
    def _index() -> None:
        snapshot = dict(base_snapshot)
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
            .sgfx-sidebar { width: 268px; min-height: 100vh; padding: 22px 16px; background: var(--sgfx-bg-elev); border-right: 1px solid var(--sgfx-border); gap: 10px; }
            .sgfx-sidebar-logo { width: 132px; height: auto; object-fit: contain; margin: 4px 0 14px 0; }
            .sgfx-nav-button { justify-content: flex-start; border-radius: 6px; color: var(--sgfx-fg) !important; }
            .sgfx-nav-button:hover { background: var(--sgfx-accent-soft) !important; }
            .sgfx-shortcut { color: var(--sgfx-fg-muted); font-size: 12px; line-height: 1.5; }
            .sgfx-main { flex: 1; min-width: 0; padding: 24px 28px; gap: 18px; background: var(--sgfx-bg); }
            .sgfx-header { border-bottom: 1px solid var(--sgfx-border); padding-bottom: 14px; }
            .sgfx-subtitle { color: var(--sgfx-fg-muted); font-size: 13px; }
            .sgfx-brand-lockup { gap: 14px; }
            .sgfx-brand-logo { width: 72px; height: 72px; object-fit: contain; flex: 0 0 auto; }
            .sgfx-about-logo { width: 160px; max-width: 34vw; height: auto; object-fit: contain; flex: 0 0 auto; }
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
