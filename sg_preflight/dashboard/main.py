from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable

from sg_preflight.bmw_delivery import read_bmw_screenshot_state
from sg_preflight.daily_digest import build_latest_daily_digest
from sg_preflight.delivery_checklist import read_delivery_checklist
from sg_preflight.manual_review import QUALITY_HERO_STEPS
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
THEME_CHOICES = ["clean", "grafiks"]
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


def _clean_theme(ui_mode: str | None) -> str:
    value = str(ui_mode or "clean").strip().casefold()
    return value if value in THEME_CHOICES else "clean"


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
        "summary": str(payload.get("summary", "") or payload.get("note", "") or title),
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
    theme = _clean_theme(ui_mode or load_dashboard_preference(root))
    return {
        "title": DASHBOARD_TITLE,
        "header": DASHBOARD_HEADER,
        "profile_id": profile_id.strip(),
        "workspace": str(root),
        "workspace_label": _path_label(root),
        "theme": theme,
        "navigation": [{"id": page_id, "label": label} for page_id, label in DASHBOARD_NAVIGATION],
        "shortcuts": list(DASHBOARD_SHORTCUTS),
        "guardrails": list(DASHBOARD_GUARDRAILS),
        "pages": [
            _reader_page(
                page_id="delivery-checklist",
                title="Delivery Checklist",
                tagline="Workbook evidence per delivery profile (read-only).",
                reader=lambda: read_delivery_checklist(profile_id=profile_id, workspace=root),
            ),
            _reader_page(
                page_id="screenshot-test-state",
                title="Screenshot Test State",
                tagline="BMW + MINI baseline / actual / diff counts per brand.",
                reader=lambda: read_bmw_screenshot_state(
                    profile_id,
                    workspace=Path(bmw_root).resolve() if bmw_root else root,
                    sg_project_root=root,
                ),
            ),
            _daily_digest_page(root, profile_id),
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


def _render_dashboard(ui: Any, app: Any, snapshot: dict[str, Any], *, workspace: Path) -> None:
    theme = str(snapshot.get("theme", "clean"))
    app.add_static_files("/sgfx-dashboard-static", str(Path(__file__).resolve().parent))

    @ui.page("/")
    def _index() -> None:
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
            .sgfx-content { width: 100%; }
            .sgfx-footer { border-top: 1px solid #d8dde6; padding-top: 10px; }
            .sgfx-guardrail { color: #394654; font-size: 13px; }
            .sgfx-page-panel { border-radius: 8px; box-shadow: none; border: 1px solid #dbe1ea; width: 100%; padding: 16px; background: #ffffff; }
            .sgfx-panel-title { font-size: 18px; font-weight: 650; }
            .sgfx-panel-tagline, .sgfx-muted { color: #657386; font-size: 13px; }
            .sgfx-summary { color: #2f3b48; font-size: 14px; }
            .sgfx-status { text-transform: none; }
            .sgfx-table { width: 100%; }
            .sgfx-step { border: 1px solid #dde3ec; border-radius: 8px; margin: 8px 0; }
            </style>
            """
        )
        pages_by_id = {str(page["id"]): page for page in snapshot["pages"]}
        first_page_id = str(snapshot["navigation"][0]["id"])
        content_holder: dict[str, Any] = {}

        def _open_page(page_id: str) -> None:
            content = content_holder.get("content")
            if content is not None:
                _render_selected_page(ui, content, pages_by_id, page_id, snapshot, workspace)

        with ui.row().classes("sgfx-shell full-width no-wrap"):
            with ui.column().classes("sgfx-sidebar"):
                ui.label(DASHBOARD_TITLE).classes("sgfx-sidebar-title")
                ui.label(f"[{theme.title()}]").classes("sgfx-sidebar-theme")
                ui.separator()
                for nav_item in snapshot["navigation"]:
                    ui.button(
                        str(nav_item["label"]),
                        on_click=lambda page_id=str(nav_item["id"]): _open_page(page_id),
                    ).props("flat no-caps align=left").classes("sgfx-nav-button full-width")
                ui.separator()
                for shortcut in snapshot["shortcuts"]:
                    ui.label(str(shortcut)).classes("sgfx-shortcut")
                ui.label("About").classes("sgfx-shortcut")
            with ui.column().classes("sgfx-main"):
                with ui.row().classes("sgfx-header items-center justify-between full-width"):
                    with ui.column():
                        ui.label(DASHBOARD_HEADER).classes("sgfx-title")
                        ui.label(
                            f"Profile: {snapshot['profile_id']} | Workspace: {snapshot['workspace_label']}"
                        ).classes("sgfx-subtitle")
                    with ui.row().classes("items-center"):
                        ui.label("F1 Help").classes("sgfx-shortcut")
                        ui.label("F12 Diagnostic").classes("sgfx-shortcut")
                        ui.label("Esc Quit").classes("sgfx-shortcut")
                        theme_toggle = ui.toggle(THEME_CHOICES, value=theme).props("dense")

                def _set_theme() -> None:
                    selected = _clean_theme(str(theme_toggle.value))
                    save_dashboard_preference(workspace, selected)
                    ui.run_javascript(
                        "document.body.classList.remove('sgfx-theme-clean', 'sgfx-theme-grafiks');"
                        f"document.body.classList.add('sgfx-theme-{selected}');"
                    )
                    ui.notify("Dashboard theme preference saved locally.")

                theme_toggle.on_value_change(lambda _: _set_theme())
                content = ui.column().classes("sgfx-content")
                content_holder["content"] = content
                _render_selected_page(ui, content, pages_by_id, first_page_id, snapshot, workspace)
                with ui.column().classes("sgfx-footer full-width"):
                    for guardrail in snapshot["guardrails"]:
                        ui.label(str(guardrail)).classes("sgfx-guardrail")


def run_dashboard(
    *,
    profile_id: str,
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
    snapshot = build_dashboard_snapshot(profile_id, root, bmw_root=bmw_root, ui_mode=ui_mode)
    _render_dashboard(ui, app, snapshot, workspace=root)
    ui.run(host=host, port=port, native=native, reload=reload, title=DASHBOARD_TITLE)
    return 0
