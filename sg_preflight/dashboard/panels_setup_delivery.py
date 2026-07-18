"""Dependency-setup and delivery-checklist page panels: the consent-gated
setup-action runner and the delivery workbook generation trigger, both with
their live-output/poll-timer wiring.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from sg_preflight.dashboard.load_tokens import (
    _cancel_background_poll_timer,
    _ignorable_nicegui_runtime_error,
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
from sg_preflight.dashboard_pages_workflows import _notify_completion_safe
from sg_preflight.delivery_workbook_generation import (
    GENERATE_WORKBOOK_ACTION_ID,
    GENERATE_WORKBOOK_ACTION_LABEL,
    cancel_delivery_workbook_generation,
    poll_delivery_workbook_generation,
    start_delivery_workbook_generation,
)
from sg_preflight.dependency_onboarding import (
    cancel_dependency_setup_action,
    poll_dependency_setup_action,
    start_dependency_setup_action,
)


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

        async def _cancel_setup() -> None:
            from nicegui import run as nicegui_run

            job = job_state.get("job")
            if job is None:
                return
            cancel_button.disable()
            status_label.text = "Stopping dependency setup..."
            result = await nicegui_run.io_bound(cancel_dependency_setup_action, job)
            progress.visible = False
            _show_setup_progress()
            _update_setup_progress(result)
            status_label.text = str(result.get("summary", "Dependency setup canceled."))
            _stop_setup_poll_timer()
            ui.notify("Dependency setup canceled.")

        cancel_button = _attach_tooltip(
            ui,
            ui.button("Cancel setup", on_click=_cancel_setup),
            "Stop the currently running local setup worker.",
        )
        cancel_button.disable()

        def _poll_setup_io() -> dict[str, Any] | None:
            job = job_state.get("job")
            if job is None:
                return {"_sgfx_stop_poll": True}
            return poll_dependency_setup_action(job)

        def _apply_setup_poll(result: dict[str, Any] | None) -> None:
            try:
                if isinstance(result, dict) and result.get("_sgfx_stop_poll"):
                    _stop_setup_poll_timer()
                    return
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
            poll_timer_ref["timer"] = _start_io_bound_poll_timer(1.0, _poll_setup_io, _apply_setup_poll)

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

                    async def _run(
                        action_payload: dict[str, Any] = action,
                        dialog: Any = confirm_dialog,
                        source_widget: Any = source_input,
                        target_widget: Any = target_input,
                    ) -> None:
                        from nicegui import run as nicegui_run

                        selected_source = _input_value(source_widget, str(action_payload.get("source_path", "")))
                        selected_target = _input_value(target_widget, str(action_payload.get("target_path", "")))
                        try:
                            job_state["job"] = await nicegui_run.io_bound(
                                start_dependency_setup_action,
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

            async def _cancel() -> None:
                from nicegui import run as nicegui_run

                job = job_state.get("job")
                if job is None:
                    return
                cancel_button.disable()
                status_label.text = "Stopping delivery workbook generation..."
                result = await nicegui_run.io_bound(cancel_delivery_workbook_generation, job)
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

            def _poll_delivery_io() -> dict[str, Any] | None:
                job = job_state.get("job")
                if job is None:
                    return {"_sgfx_stop_poll": True}
                return poll_delivery_workbook_generation(job)

            def _apply_delivery_poll(result: dict[str, Any] | None) -> None:
                try:
                    if isinstance(result, dict) and result.get("_sgfx_stop_poll"):
                        _stop_delivery_poll_timer()
                        return
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
                poll_timer_ref["timer"] = _start_io_bound_poll_timer(1.0, _poll_delivery_io, _apply_delivery_poll)

            with ui.dialog() as confirm_dialog, ui.card():
                ui.label(str(action.get("confirmation_message", ""))).classes("sgfx-summary")
                ui.label("Manual review remains required. Decision: not approval — evidence only.").classes(
                    "sgfx-muted"
                )

                async def _start() -> None:
                    from nicegui import run as nicegui_run

                    try:
                        job_state["job"] = await nicegui_run.io_bound(
                            start_delivery_workbook_generation,
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
