from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import socket
from typing import Any, Callable

from sg_preflight.assets import runtime_asset_dir, runtime_asset_path, runtime_asset_root
from sg_preflight.bmw_delivery import read_bmw_screenshot_state
from sg_preflight.daily_digest import build_latest_daily_digest
from sg_preflight.delivery_checklist import read_delivery_checklist
from sg_preflight.manual_review import QUALITY_HERO_STEPS
from sg_preflight.profiles import list_run_profiles
from sg_preflight.utils import ensure_parent


DASHBOARD_TITLE = "SGFX QA Preflight"
DASHBOARD_HEADER = "SGFX: Project Quality-Hero"
DASHBOARD_GUARDRAILS = (
    "Manual review remains required.",
    "Decision: not approval - evidence only.",
    "BMW Git access is read-only. SGFX never modifies BMW source.",
    "Activity log is local-only - never posted to Jira, SVN, or BMW Git.",
)
DASHBOARD_NAVIGATION = (
    ("delivery-checklist", "Delivery Checklist"),
    ("screenshot-test-state", "Screenshot Test State"),
    ("daily-digest", "Daily Digest"),
    ("manual-review", "Manual Review Companion"),
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
MANUAL_REVIEW_STATUSES = ["pending", "captured", "blocked"]
_MISSING_STATUSES = {
    "missing",
    "no_workbook",
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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


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
    if status in {"not_available", "unavailable"}:
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


def _reader_page(
    *,
    page_id: str,
    title: str,
    tagline: str,
    reader: Callable[[], dict[str, Any]],
    workspace: Path | str | None = None,
) -> dict[str, Any]:
    try:
        payload = reader()
    except Exception as exc:
        return {
            "id": page_id,
            "title": title,
            "tagline": tagline,
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
        "status": _dashboard_status(raw_status, data_available),
        "raw_status": raw_status,
        "data_available": data_available,
        "summary": _payload_summary(payload, title, workspace=workspace),
        "items": _payload_items(payload),
        "payload": _sanitized_payload(payload),
    }


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
    )
    return {key: payload[key] for key in allowed if key in payload}


def _daily_digest_page(workspace: Path, profile_id: str) -> dict[str, Any]:
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
            "payload": {"profile_id": profile_id},
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
    return {
        "id": "daily-digest",
        "title": "Daily Digest",
        "tagline": "Morning status snapshot for the SG Daily standup.",
        "status": _dashboard_status(str(digest.get("status", "unknown")), bool(digest.get("data_available", False))),
        "raw_status": str(digest.get("status", "unknown")),
        "data_available": bool(digest.get("data_available", False)),
        "summary": str(digest.get("no_data_message", "Daily digest snapshot loaded.")),
        "items": items,
        "payload": {
            "status": digest.get("status", "unknown"),
            "scope": digest.get("scope", []),
            "date": digest.get("date", ""),
        },
    }


def _manual_review_page() -> dict[str, Any]:
    steps = [step.to_session_step() for step in QUALITY_HERO_STEPS]
    return {
        "id": "manual-review",
        "title": "Manual Review Companion",
        "tagline": "Step through the 7 Quality-Hero review steps. Operator verdict per step.",
        "status": "pending",
        "data_available": True,
        "summary": f"{len(steps)} manual-review steps available for operator notes.",
        "items": [
            {
                "label": str(step.get("title", "")),
                "status": str(step.get("verdict", "pending")),
                "detail": str(step.get("evidence_prompt", "")),
            }
            for step in steps
        ],
        "payload": {"steps": steps},
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
    return {
        "title": DASHBOARD_TITLE,
        "header": DASHBOARD_HEADER,
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
        "pages": [
            _reader_page(
                page_id="delivery-checklist",
                title="Delivery Checklist",
                tagline="Workbook evidence per delivery profile (read-only).",
                reader=lambda: read_delivery_checklist(profile_id=resolved_profile_id, workspace=root),
                workspace=root,
            ),
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
            ),
            _daily_digest_page(root, resolved_profile_id),
            _manual_review_page(),
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


def _render_status_chip(ui: Any, status: str) -> None:
    ui.badge(status or "unknown").classes("sgfx-status")


def _render_page_panel(ui: Any, page: dict[str, Any]) -> None:
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
            ui.table(
                columns=[
                    {"name": "label", "label": "Item", "field": "label", "align": "left"},
                    {"name": "status", "label": "Status", "field": "status", "align": "left"},
                    {"name": "detail", "label": "Detail", "field": "detail", "align": "left"},
                ],
                rows=rows,
                row_key="label",
            ).classes("sgfx-table")
        else:
            ui.label("No rows loaded for this page.").classes("sgfx-muted")


def _render_manual_review_panel(ui: Any, snapshot: dict[str, Any], workspace: Path) -> None:
    page = next(page for page in snapshot["pages"] if page["id"] == "manual-review")
    with ui.column().classes("sgfx-page-panel"):
        ui.label(str(page["title"])).classes("sgfx-panel-title")
        ui.label(str(page["tagline"])).classes("sgfx-panel-tagline")
        ui.label("Manual review remains required. Decision: not approval - evidence only.").classes("sgfx-summary")
        for step in page["payload"]["steps"]:
            slug = str(step.get("slug", ""))
            with ui.expansion(str(step.get("title", slug)), icon="fact_check").classes("sgfx-step"):
                focus = ", ".join(str(item) for item in step.get("review_focus", []) if str(item).strip())
                if focus:
                    ui.label(f"Review focus: {focus}").classes("sgfx-summary")
                ui.label(str(step.get("evidence_prompt", ""))).classes("sgfx-muted")
                status = ui.radio(MANUAL_REVIEW_STATUSES, value="pending").props("inline")
                note = ui.textarea(label="Operator note").classes("full-width")

                def _save(slug: str = slug, status=status, note=note) -> None:
                    save_manual_review_state(
                        profile_id=str(snapshot["profile_id"]),
                        workspace=workspace,
                        step_slug=slug,
                        status=str(status.value),
                        note=str(note.value or ""),
                    )
                    ui.notify("Manual-review note saved locally.")

                ui.button("Save local note", on_click=_save).props("color=primary")


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
        if page_id == "manual-review":
            _render_manual_review_panel(ui, snapshot, workspace)
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
        ui.query("body").classes(f"sgfx-dashboard sgfx-theme-{theme}")
        ui.add_head_html(
            """
            <style>
            .sgfx-dashboard { background: #f7f8fa; color: #17202a; font-family: Segoe UI, Arial, sans-serif; }
            .sgfx-theme-grafiks { background: #eef2f5; }
            .sgfx-shell { min-height: 100vh; gap: 0; }
            .sgfx-sidebar { width: 268px; min-height: 100vh; padding: 18px 14px; background: #ffffff; border-right: 1px solid #d8dde6; }
            .sgfx-sidebar-title { font-size: 18px; font-weight: 700; letter-spacing: 0; }
            .sgfx-sidebar-theme { color: #5e6b7a; font-size: 13px; margin-bottom: 8px; }
            .sgfx-nav-button { justify-content: flex-start; border-radius: 6px; }
            .sgfx-shortcut { color: #657386; font-size: 12px; line-height: 1.4; }
            .sgfx-main { flex: 1; min-width: 0; padding: 20px 24px; gap: 16px; }
            .sgfx-header { border-bottom: 1px solid #d8dde6; padding-bottom: 12px; }
            .sgfx-title { font-size: 24px; font-weight: 700; letter-spacing: 0; }
            .sgfx-subtitle { color: #5e6b7a; font-size: 14px; }
            .sgfx-brand-lockup { gap: 12px; }
            .sgfx-brand-logo { width: 52px; height: 52px; object-fit: contain; flex: 0 0 auto; }
            .sgfx-content { width: 100%; }
            .sgfx-footer { border-top: 1px solid #d8dde6; padding-top: 10px; }
            .sgfx-guardrail { color: #394654; font-size: 13px; }
            .sgfx-page-panel { border-radius: 8px; box-shadow: none; border: 1px solid #dbe1ea; width: 100%; padding: 16px; background: #ffffff; }
            .sgfx-panel-title { font-size: 18px; font-weight: 650; }
            .sgfx-panel-tagline, .sgfx-muted { color: #657386; font-size: 13px; }
            .sgfx-summary { color: #2f3b48; font-size: 14px; }
            .sgfx-warning { border: 1px solid #d7a23b; background: #fff8e8; color: #694b12; border-radius: 6px; padding: 8px 10px; }
            .sgfx-shortcut-feedback { min-height: 22px; color: #2f3b48; font-size: 13px; padding: 2px 0; }
            .sgfx-profile-select { min-width: 132px; }
            .sgfx-status { text-transform: none; }
            .sgfx-table { width: 100%; }
            .sgfx-step { border: 1px solid #dde3ec; border-radius: 8px; margin: 8px 0; }
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
            theme_label = controls.get("theme_label")
            if theme_label is not None:
                theme_label.set_text(f"[{_current_theme().title()}]")

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
                if active_page_id == "manual-review":
                    _render_manual_review_panel(ui, state["snapshot"], workspace)
                else:
                    _render_page_panel(ui, _pages_by_id()[active_page_id])

        def _open_page(page_id: str) -> None:
            state["active_page_id"] = page_id
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
                    const show = (message) => {{
                        const target = document.getElementById('sgfx-shortcut-feedback');
                        if (target) target.textContent = message;
                    }};
                    if (window.__sgfxDashboardShortcutsInstalled) return;
                    window.__sgfxDashboardShortcutsInstalled = true;
                    document.addEventListener('keydown', (event) => {{
                        if (!['F1', 'F2', 'F5', 'F12', 'Escape'].includes(event.key)) return;
                        event.preventDefault();
                        if (event.key === 'F1') show(messages.F1);
                        if (event.key === 'F2') {{
                            show(messages.F2);
                            const input = document.querySelector('.sgfx-profile-select input');
                            if (input) input.focus();
                        }}
                        if (event.key === 'F5') {{
                            show(messages.F5);
                            const refresh = document.querySelector('.sgfx-refresh-button');
                            if (refresh) refresh.click();
                        }}
                        if (event.key === 'F12') show(`${{messages.F12}} Current page: {state["active_page_id"]}.`);
                        if (event.key === 'Escape') show(messages.Esc);
                    }});
                }})();
                """
            )

        with ui.row().classes("sgfx-shell full-width no-wrap"):
            with ui.column().classes("sgfx-sidebar"):
                ui.label(DASHBOARD_TITLE).classes("sgfx-sidebar-title")
                controls["theme_label"] = ui.label(f"[{theme.title()}]").classes("sgfx-sidebar-theme")
                ui.separator()
                for nav_item in state["snapshot"]["navigation"]:
                    ui.button(
                        str(nav_item["label"]),
                        on_click=lambda page_id=str(nav_item["id"]): _open_page(page_id),
                    ).props("flat no-caps align=left").classes("sgfx-nav-button full-width")
                ui.separator()
                for shortcut in state["snapshot"]["shortcuts"]:
                    ui.label(str(shortcut)).classes("sgfx-shortcut")
                ui.label("About").classes("sgfx-shortcut")
            with ui.column().classes("sgfx-main"):
                with ui.row().classes("sgfx-header items-center justify-between full-width"):
                    with ui.row().classes("sgfx-brand-lockup items-center"):
                        ui.image("/sgfx-dashboard-assets/framework_sgfx_logo.png").classes("sgfx-brand-logo")
                        with ui.column():
                            ui.label(DASHBOARD_HEADER).classes("sgfx-title")
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
                        controls["profile_select"] = ui.select(
                            [str(option["id"]) for option in state["snapshot"]["profile_options"]],
                            value=str(state["snapshot"]["profile_id"]) if state["snapshot"]["profile_known"] else None,
                            label="Profile",
                            on_change=lambda event: _set_profile(str(event.value or "")),
                        ).props("dense outlined").classes("sgfx-profile-select")
                        ui.button("Refresh", on_click=_refresh_current_page).props("flat dense no-caps").classes(
                            "sgfx-refresh-button"
                        )
                        ui.label("Mode: Clean").classes("sgfx-shortcut")
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

    ui, app = require_nicegui()
    root = _workspace(workspace)
    _render_dashboard(ui, app, initial_profile_id=profile_id, workspace=root, bmw_root=bmw_root, ui_mode=ui_mode)
    favicon_path = runtime_asset_path("sgfx_icon.png")
    run_port = _dashboard_run_port(native=native, port=port)
    show_browser = False if not native else True
    if favicon_path.is_file():
        ui.run(
            host=host,
            port=run_port,
            native=native,
            reload=reload,
            title=DASHBOARD_TITLE,
            favicon=str(favicon_path),
            show=show_browser,
        )
    else:
        ui.run(host=host, port=run_port, native=native, reload=reload, title=DASHBOARD_TITLE, show=show_browser)
    return 0
