"""Screenshot Test State page panel: evidence rows, the inline side-by-side
review viewer, and the confirmation-gated screenshot-capture action with its
live-output/poll-timer wiring.
"""

from __future__ import annotations

from html import escape as html_escape
from pathlib import Path
from typing import Any

from sg_preflight.dashboard.load_tokens import (
    _cancel_background_poll_timer,
    _parent_slot_deleted,
    _start_io_bound_poll_timer,
)
from sg_preflight.dashboard.panels_common import (
    LONG_RUNNING_NOTIFICATION_SECONDS,
    _attach_tooltip,
    _render_empty_state_note,
    _render_page_confluence_anchors,
    _render_status_chip,
)
from sg_preflight.dashboard_pages_workflows import (
    _materialize_screenshot_review_viewer_for_dashboard,
    _notify_completion_safe,
    _screenshot_review_viewer_url,
)
from sg_preflight.screenshot_capture import (
    SCREENSHOT_CAPTURE_ACTION_ID,
    SCREENSHOT_CAPTURE_ACTION_LABEL,
    cancel_screenshot_capture_with_export_check,
    poll_screenshot_capture_with_export_check,
    start_screenshot_capture_with_export_check,
)


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

        async def _build_and_open_viewer() -> None:
            build_viewer_button.disable()
            viewer_status.text = "Building screenshot review viewer..."
            try:
                from nicegui import run as nicegui_run

                bundle = await nicegui_run.io_bound(
                    _materialize_screenshot_review_viewer_for_dashboard,
                    str(snapshot["profile_id"]),
                    workspace,
                    bmw_root=bmw_root,
                )
            except Exception as exc:  # noqa: BLE001
                viewer_status.text = f"Viewer generation failed: {exc}"
                ui.notify("Screenshot review viewer generation failed.")
                return
            finally:
                build_viewer_button.enable()
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

        build_viewer_button = _attach_tooltip(
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

            async def _cancel() -> None:
                from nicegui import run as nicegui_run

                job = job_state.get("job")
                if job is None:
                    return
                cancel_button.disable()
                status_label.text = "Stopping screenshot capture..."
                result = await nicegui_run.io_bound(cancel_screenshot_capture_with_export_check, job)
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

            def _poll_screenshot_io() -> dict[str, Any] | None:
                job = job_state.get("job")
                if job is None:
                    return {"_sgfx_stop_poll": True}
                return poll_screenshot_capture_with_export_check(job)

            def _apply_screenshot_poll(result: dict[str, Any] | None) -> None:
                try:
                    if isinstance(result, dict) and result.get("_sgfx_stop_poll"):
                        _stop_screenshot_poll_timer()
                        return
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
                poll_timer_ref["timer"] = _start_io_bound_poll_timer(1.0, _poll_screenshot_io, _apply_screenshot_poll)

            with ui.dialog() as confirm_dialog, ui.card():
                ui.label(str(action.get("confirmation_message", ""))).classes("sgfx-summary")
                ui.label("Manual review remains required. Decision: not approval — evidence only.").classes(
                    "sgfx-muted"
                )

                async def _start() -> None:
                    from nicegui import run as nicegui_run

                    try:
                        job_state["job"] = await nicegui_run.io_bound(
                            start_screenshot_capture_with_export_check,
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
