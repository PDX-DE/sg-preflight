"""Risk Score, Cross-Car Comparison, and Team Digest Board page panels —
the three read-only scoring/comparison surfaces that share the same
standing-disclaimer and empty-state rendering conventions.
"""

from __future__ import annotations

from typing import Any

from sg_preflight.dashboard.panels_common import (
    _STANDING_PANEL_NOTE,
    _attach_tooltip,
    _render_empty_state_note,
    _render_page_confluence_anchors,
    _render_status_chip,
    _strip_standing_disclaimers,
)


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
        summary = _strip_standing_disclaimers(str(page.get("summary", "")))
        if summary:
            ui.label(summary).classes("sgfx-summary")
        standing_note = ui.label(_STANDING_PANEL_NOTE).classes("sgfx-muted sgfx-standing-note")
        ownership_note = str(page.get("ownership_note", "")).strip()
        if ownership_note:
            _attach_tooltip(ui, standing_note, ownership_note)
        _render_empty_state_note(ui, page)
        # Risk-score sparkline wiring: renders the trend sparkline next to the risk-score
        # numbers so the dashboard live UI surfaces the same trend signal that lands in
        # the profile summary HTML output and the risk-score CLI text output.
        sparkline = page.get("risk_sparkline") if isinstance(page.get("risk_sparkline"), dict) else {}
        if sparkline:
            with ui.row().classes("items-center sgfx-risk-sparkline"):
                ui.label("Risk trend (last N runs):").classes("sgfx-panel-tagline")
                if sparkline.get("svg"):
                    ui.html(str(sparkline.get("svg")), sanitize=False)
                elif sparkline.get("fallback"):
                    ui.label(str(sparkline.get("fallback"))).classes("sgfx-muted")
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
    left_profile = str(payload.get("left_profile", ""))
    right_profile = str(payload.get("right_profile", ""))
    with ui.column().classes("sgfx-page-panel"):
        with ui.row().classes("items-center justify-between full-width"):
            ui.label(str(page["title"])).classes("sgfx-panel-title")
            _render_status_chip(ui, str(page.get("status", "unknown")))
        ui.label(str(page["tagline"])).classes("sgfx-panel-tagline")
        _render_page_confluence_anchors(ui, page)
        summary = _strip_standing_disclaimers(str(page.get("summary", "")))
        if summary:
            ui.label(summary).classes("sgfx-summary")
        standing_note = ui.label(_STANDING_PANEL_NOTE).classes("sgfx-muted sgfx-standing-note")
        ownership_note = str(page.get("ownership_note", "")).strip()
        if ownership_note:
            _attach_tooltip(ui, standing_note, ownership_note)
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
        summary = _strip_standing_disclaimers(str(page.get("summary", "")))
        if summary:
            ui.label(summary).classes("sgfx-summary")
        standing_note = ui.label(_STANDING_PANEL_NOTE).classes("sgfx-muted sgfx-standing-note")
        ownership_note = str(page.get("ownership_note", "")).strip()
        if ownership_note:
            _attach_tooltip(ui, standing_note, ownership_note)
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
