from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps
from html import escape as html_escape
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from typing import Any, Callable
from urllib.parse import quote, quote_plus

from sg_preflight.qa_pass_report import (
    build_qa_pass_report_summary,
    default_qa_pass_report_zip_path,
    export_qa_pass_report_zip,
    write_qa_pass_report_html,
)
from sg_preflight.weekly_ticket_draft import build_weekly_ticket_draft, render_weekly_ticket_draft_text


MY_TICKETS_UNAVAILABLE_SUMMARY = "My Tickets unavailable. Check local Jira setup before retrying."
WEEKLY_TICKET_DRAFT_UNAVAILABLE_SUMMARY = "Weekly Ticket Draft unavailable. Check local Jira setup before retrying."


_MAIN_GLOBAL_NAMES = (
    "Any",
    "Callable",
    "Path",
    "json",
    "os",
    "re",
    "subprocess",
    "sys",
    "threading",
    "time",
    "datetime",
    "timezone",
    "html_escape",
    "quote",
    "quote_plus",
    "DASHBOARD_GUARDRAILS",
    "QUALITY_HERO_CONFLUENCE_ANCHOR",
    "DELIVERY_CHECKLIST_CONFLUENCE_ANCHOR",
    "BMW_PIPELINE_PYTHON_CONFLUENCE_ANCHOR",
    "SG_DAILY_CONFLUENCE_ANCHOR",
    "MANUAL_REVIEW_STATUSES",
    "MANUAL_REVIEW_RECORD_VERDICTS",
    "MANUAL_REVIEW_EMPTY_NOTE",
    "_MANUAL_REVIEW_PENDING_VERDICT",
    "_TICKET_ID_PATTERN",
    "SETUP_COMPLETE_NOTE",
    "SCREENSHOT_TEST_STATE_OWNERSHIP_NOTE",
    "DAILY_DIGEST_BUILD_PACKAGE_ACTION_ID",
    "DAILY_DIGEST_BUILD_PACKAGE_ACTION_LABEL",
    "QUALITY_HERO_REPORT_ACTION_ID",
    "QUALITY_HERO_REPORT_ACTION_LABEL",
    "QUALITY_HERO_REPORT_ATTACH_ACTION_LABEL",
    "DAILY_DIGEST_TICKET_ID_PLACEHOLDER",
    "_DAILY_DIGEST_PARTIAL_SECTION_KEYS",
    "_BUILD_PACKAGE_TIMEOUT_SECONDS",
    "_BUILD_PACKAGE_STDOUT_TAIL_LINES",
    "_BUILD_PACKAGE_STDOUT_TAIL_BYTES",
    "_BUILD_PACKAGE_FILE_ACTIVITY_LIMIT",
    "_BUILD_PACKAGE_TYPICAL_RANGE_LABEL",
    "_QUALITY_HERO_REPORT_TIMEOUT_SECONDS",
    "_BATCH_FULL_QA_TIMEOUT_SECONDS",
    "_BATCH_FULL_QA_TYPICAL_RANGE_LABEL",
    "LONG_RUNNING_NOTIFICATION_SECONDS",
    "VERBOSE_TOOLTIP_ENV",
    "_workspace",
    "_utc_now",
    "_operator_state_path",
    "_read_operator_state_json",
    "_write_active_ticket_state",
    "_dashboard_active_ticket_id",
    "_daily_digest_ticket_context",
    "_dashboard_notifications_enabled",
    "_write_dashboard_notifications_preference",
    "_full_qa_wizard_state_path",
    "_read_full_qa_wizard_state",
    "_write_full_qa_wizard_state",
    "_delete_full_qa_wizard_state",
    "_payload_items",
    "_sanitized_payload",
    "_payload_summary",
    "_dashboard_changed_profiles",
    "_dashboard_data_uri",
    "_pipeline_traceback",
    "_screenshot_review_visual_rows",
    "_file_activity_visual_items",
    "_render_status_chip",
    "_render_page_panel",
    "_render_confluence_anchor",
    "_render_page_confluence_anchors",
    "_render_empty_state_note",
    "_render_action_visuals",
    "_render_action_technical_details",
    "_attach_tooltip",
    "_copy_dashboard_text_to_clipboard",
    "_copy_dashboard_link_to_clipboard",
    "_render_jira_profile_tickets_card",
    "_start_background_poll_timer",
    "_start_io_bound_poll_timer",
    "_cancel_background_poll_timer",
    "_parent_slot_deleted",
    "_ignorable_nicegui_runtime_error",
    "_run_javascript_if_client_alive",
    "build_my_unresolved_ticket_jql",
    "search_my_unresolved_tickets",
    "search_jira_profile_tickets",
    "load_jira_credentials",
    "DEFAULT_JIRA_URL",
    "operator_ui_root",
    "sgfx_cli_command",
    "hidden_subprocess_kwargs",
    "ensure_parent",
    "append_activity_entry",
    "notify_desktop_completion",
    "record_full_qa_run_history",
    "build_qa_pass_report_summary",
    "default_qa_pass_report_zip_path",
    "export_qa_pass_report_zip",
    "write_qa_pass_report_html",
    "build_full_qa_pass",
    "get_run_profile",
    "build_latest_daily_digest",
    "render_daily_digest_text",
    "build_screenshot_review_viewer",
    "compute_diff_delta_badge",
    "compute_diff_regression_badge",
    "run_missing_actual_diagnostic_chain",
    "render_missing_actual_diagnostic_text",
    "MISSING_ACTUAL_DIAGNOSTIC_ACTION_ID",
    "build_visual_review_prep",
    "read_bmw_screenshot_state",
    "check_screenshot_capture_environment",
    "check_screenshot_export_artifact",
    "record_operator_handoff",
    "start_delivery_workbook_generation",
    "poll_delivery_workbook_generation",
    "cancel_delivery_workbook_generation",
    "build_delivery_workbook_trigger",
    "GENERATE_WORKBOOK_ACTION_ID",
    "GENERATE_WORKBOOK_ACTION_LABEL",
    "GENERATE_WORKBOOK_TIMEOUT_SECONDS",
    "start_screenshot_capture",
    "poll_screenshot_capture",
    "cancel_screenshot_capture",
    "start_screenshot_capture_with_export_check",
    "poll_screenshot_capture_with_export_check",
    "cancel_screenshot_capture_with_export_check",
    "SCREENSHOT_CAPTURE_ACTION_ID",
    "SCREENSHOT_CAPTURE_ACTION_LABEL",
    "SCREENSHOT_CAPTURE_TIMEOUT_SECONDS",
    "start_dependency_setup_action",
    "poll_dependency_setup_action",
    "cancel_dependency_setup_action",
    "build_dependency_onboarding_status",
    "QUALITY_HERO_STEPS",
    "review_template_for_profile",
    "list_car_review_templates",
    "load_manual_review_session",
    "create_manual_review_session_from_template",
    "record_manual_review_step",
    "record_manual_review_dashboard_step",
    "build_manual_review_assist",
    "build_manual_review_assist_from_auto_checks",
    "apply_manual_review_suggestions",
    "run_manual_review_auto_checks",
    "build_weekly_ticket_draft",
    "render_weekly_ticket_draft_text",
    "_full_qa_pass_page",
    "_batch_full_qa_pass_page",
    "_my_tickets_page",
    "_weekly_ticket_draft_page",
    "_is_truthy_trigger",
    "_full_qa_pass_token",
    "_full_qa_pass_dedup_key",
    "_should_fire_full_qa_pass",
    "_reset_full_qa_pass_dedup",
    "_publish_live_state",
    "_snapshot_with_full_qa_payload",
    "_screenshot_review_viewer_output_root",
    "_missing_actual_diagnostics_output_root",
    "_qa_pass_report_output_root",
    "_qa_pass_report_url",
    "build_dashboard_qa_pass_report",
    "export_dashboard_qa_pass_report",
    "_screenshot_review_viewer_url",
    "_materialize_screenshot_review_viewer_for_dashboard",
    "_notify_completion_safe",
    "_full_qa_completion_notification",
    "_manual_review_profile_token",
    "_manual_review_dashboard_session_id",
    "_load_manual_review_dashboard_session",
    "_ensure_manual_review_dashboard_session",
    "_manual_review_step_recorded",
    "_manual_review_step_detail",
    "_manual_review_page",
    "_dashboard_review_package_command",
    "_dashboard_full_qa_pass_command",
    "_batch_profile_safe_name",
    "_read_json_payload",
    "_batch_step_payload",
    "_batch_profile_result",
    "_batch_progress_payload",
    "_complete_batch_full_qa_pass",
    "_start_batch_profile_process",
    "start_dashboard_batch_full_qa_pass",
    "request_cancel_dashboard_batch_full_qa_pass",
    "poll_dashboard_batch_full_qa_pass",
    "_review_build_progress_payload",
    "_complete_review_package_build",
    "start_dashboard_review_package_build",
    "poll_dashboard_review_package_build",
    "cancel_dashboard_review_package_build",
    "build_dashboard_review_package",
    "_quality_hero_report_output_root",
    "_dashboard_quality_hero_report_command",
    "_dashboard_jira_attachment_endpoint",
    "_attachment_response_url",
    "_attachment_response_id",
    "build_dashboard_quality_hero_report",
    "_build_action_visual_payload",
    "_full_qa_int",
    "_full_qa_step_payload",
    "_full_qa_step_map",
    "_full_qa_step_status",
    "_full_qa_screenshot_counts",
    "_full_qa_risk_draft",
    "_full_qa_manual_review_draft",
    "_full_qa_handoff_draft",
    "_full_qa_bulk_ack_drafts",
    "_render_daily_digest_panel",
    "_render_operator_handoff_panel",
    "_render_manual_review_panel",
    "_my_ticket_status_draft",
    "_build_my_tickets_payload",
    "_build_weekly_ticket_draft_payload",
    "_render_my_tickets_panel",
    "_render_weekly_ticket_draft_panel",
    "_render_batch_full_qa_pass_panel",
    "_render_full_qa_pass_panel",
)


def _sync_main_globals() -> None:
    from sg_preflight.dashboard import main as dashboard_main

    for name in _MAIN_GLOBAL_NAMES:
        if hasattr(dashboard_main, name):
            globals()[name] = getattr(dashboard_main, name)


def _with_main_globals(func: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        _sync_main_globals()
        return func(*args, **kwargs)

    return wrapper


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


def _my_tickets_page(profile_id: str, workspace: Path) -> dict[str, Any]:
    jql = build_my_unresolved_ticket_jql()
    payload = {
        "schema_version": 1,
        "profile_id": profile_id,
        "workspace": str(workspace),
        "status": "read_only",
        "summary": "Open this page to load your assigned unresolved Jira tickets from operator-local credentials.",
        "jql": jql,
        "draft_source": "local SGFX review evidence; no Jira post is sent",
        "read_only": True,
        "is_approval": False,
    }
    return {
        "id": "my-tickets",
        "title": "My Tickets",
        "tagline": "Read your assigned unresolved Jira tickets and prepare review-only status drafts.",
        "status": "read_only",
        "data_available": False,
        "summary": str(payload["summary"]),
        "items": [],
        "payload": payload,
        "deferred": True,
    }


def _weekly_ticket_draft_page(profile_id: str, workspace: Path) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "profile_id": profile_id,
        "workspace": str(workspace),
        "status": "read_only",
        "summary": "Open this page to draft your weekly ticket list, ready to review and send.",
        "read_only": True,
        "is_approval": False,
    }
    return {
        "id": "weekly-ticket-draft",
        "title": "Weekly Ticket Draft",
        "tagline": "Draft your end-of-week ticket list from Jira updates and local SGFX activity.",
        "status": "read_only",
        "data_available": False,
        "summary": str(payload["summary"]),
        "items": [],
        "payload": payload,
        "deferred": True,
    }


_TRUTHY_TRIGGERS = frozenset({"1", "true", "yes", "on"})


def _is_truthy_trigger(value: str | None, *, default: str = "") -> bool:
    raw = str(value if value is not None else default or "").strip().casefold()
    return raw in _TRUTHY_TRIGGERS


# internal milestone: process-local dedup for the Full QA Pass trigger so a NiceGUI WebSocket
# reconnect storm cannot re-fire `build_full_qa_pass` after the internal milestone ui.navigate.to
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


FULL_QA_PASS_DEDUP_BUCKET_SECONDS = 5


def _full_qa_pass_token(profile_id: str, ts_seconds: int | None = None) -> str:
    """Audit-trail token. internal milestone Part B widens the timestamp suffix from per-second
    to per-5-second buckets so back-to-back fires that cross a second boundary
    (observed in testing: a 12:09:14.x / 12:09:15.x burst on one profile — three log entries
    inside 1.1s) collapse to the same token rather than three distinct ones.

    The dedup DECISION still keys on `profile_id` only via
    `_full_qa_pass_dedup_key`; the bucketed timestamp is for log readability.
    """
    if ts_seconds is None:
        ts_seconds = int(time.time())
    bucket = (int(ts_seconds) // FULL_QA_PASS_DEDUP_BUCKET_SECONDS) * FULL_QA_PASS_DEDUP_BUCKET_SECONDS
    return f"full-qa-pass:{profile_id}:{bucket}"


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
    """internal milestone hookpoint: best-effort debounced write to live_state.json.

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


def _qa_pass_report_output_root(workspace: Path, profile_id: str) -> Path:
    safe_profile = re.sub(r"[^A-Za-z0-9_.-]+", "_", profile_id.strip().lower() or "profile")
    return operator_ui_root(workspace) / "qa-pass-report" / safe_profile


def _qa_pass_report_url(profile_id: str) -> str:
    safe_profile = re.sub(r"[^A-Za-z0-9_.-]+", "_", profile_id.strip().lower() or "profile")
    return f"/sgfx-operator-ui/qa-pass-report/{safe_profile}/qa-pass-report.html"


def build_dashboard_qa_pass_report(
    *,
    workspace: Path | str,
    profile_id: str,
    payload: dict[str, Any],
    output_root: Path | str | None = None,
) -> dict[str, Any]:
    workspace_path = Path(workspace).resolve()
    clean_profile = profile_id.strip().upper()
    if not clean_profile:
        raise ValueError("Profile ID required to build the QA Pass report.")
    report_root = Path(output_root).resolve() if output_root else _qa_pass_report_output_root(workspace_path, clean_profile)
    bundle = write_qa_pass_report_html(
        profile_id=clean_profile,
        payload=payload,
        output_root=report_root,
        mode="dashboard",
    )
    result = bundle.to_payload()
    result["url"] = _qa_pass_report_url(clean_profile)
    return result


def export_dashboard_qa_pass_report(
    *,
    workspace: Path | str,
    profile_id: str,
    payload: dict[str, Any],
    bmw_root: Path | str | None = None,
    output_root: Path | str | None = None,
) -> dict[str, Any]:
    workspace_path = Path(workspace).resolve()
    clean_profile = profile_id.strip().upper()
    if not clean_profile:
        raise ValueError("Profile ID required to export the QA Pass report.")
    report_root = Path(output_root).resolve() if output_root else _qa_pass_report_output_root(workspace_path, clean_profile)
    zip_path = default_qa_pass_report_zip_path(report_root, clean_profile)
    result = export_qa_pass_report_zip(
        profile_id=clean_profile,
        workspace=workspace_path,
        bmw_root=bmw_root,
        payload=payload,
        output_path=zip_path,
    )
    payload_result = result.to_payload()
    payload_result["zip_size_bytes"] = zip_path.stat().st_size if zip_path.is_file() else 0
    return payload_result


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
    from nicegui import background_tasks, run as nicegui_run

    notification_task = nicegui_run.io_bound(
        notify_desktop_completion,
        title=title,
        message=message,
        workspace=workspace,
        action_id=action_id,
        profile_id=profile_id,
        evidence_path=evidence_path,
    )
    try:
        background_tasks.create(
            notification_task,
            name=f"sgfx-desktop-notification-{action_id or 'completion'}",
        )
    except Exception:
        close = getattr(notification_task, "close", None)
        if callable(close):
            close()
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
        repo_root = Path(__file__).resolve().parents[1]
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

def _build_action_visual_payload(result: dict[str, Any]) -> dict[str, Any]:
    workbook_preview = result.get("workbook_preview", {})
    if not isinstance(workbook_preview, dict):
        workbook_preview = {}
    return {
        "review_rows": _screenshot_review_visual_rows(result),
        "image_items": _file_activity_visual_items(result),
        "workbook_preview": workbook_preview,
    }


def _empty_action_visual_payload(result: dict[str, Any]) -> dict[str, Any]:
    workbook_preview = result.get("workbook_preview", {})
    if not isinstance(workbook_preview, dict):
        workbook_preview = {}
    return {"review_rows": [], "image_items": [], "workbook_preview": workbook_preview}


def _render_action_visuals(
    ui: Any,
    result: dict[str, Any],
    *,
    visual_label: Any,
    visual_host: Any,
    open_screenshot_viewer: Callable[[str, str], None] | None = None,
    visual_payload: dict[str, Any] | None = None,
) -> None:
    visual_host.clear()
    payload = visual_payload if isinstance(visual_payload, dict) else _empty_action_visual_payload(result)
    review_rows = [row for row in payload.get("review_rows", []) if isinstance(row, dict)]
    image_items = [item for item in payload.get("image_items", []) if isinstance(item, dict)]
    workbook_preview = payload.get("workbook_preview", {})
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

                    async def _open(current: dict[str, str] = row) -> None:
                        if open_screenshot_viewer is not None:
                            result = open_screenshot_viewer(current["key"], current["label"])
                            if asyncio.iscoroutine(result):
                                await result

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

            async def _cancel_build() -> None:
                from nicegui import run as nicegui_run

                job = job_state.get("job")
                if job is None:
                    return
                cancel_button.disable()
                status_label.text = "Stopping build review package..."
                result = await nicegui_run.io_bound(cancel_dashboard_review_package_build, job)
                progress.visible = False
                _show_build_progress()
                _update_build_progress(result)
                status_label.text = str(result.get("summary", "Build review package canceled."))
                _stop_build_poll_timer()
                ui.notify("Build review package canceled.")

            cancel_button = _attach_tooltip(
                ui,
                ui.button("Cancel build", on_click=_cancel_build),
                "Stop the local review-package build worker.",
            )
            cancel_button.disable()

            def _poll_build_io() -> dict[str, Any] | None:
                job = job_state.get("job")
                if job is None:
                    return {"_sgfx_stop_poll": True}
                return poll_dashboard_review_package_build(job)

            def _apply_build_poll(result: dict[str, Any] | None) -> None:
                try:
                    if isinstance(result, dict) and result.get("_sgfx_stop_poll"):
                        _stop_build_poll_timer()
                        return
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
                poll_timer_ref["timer"] = _start_io_bound_poll_timer(1.0, _poll_build_io, _apply_build_poll)

            with ui.dialog() as confirm_dialog, ui.card():
                ui.label("Build review package").classes("sgfx-panel-title")
                ui.label(
                    "This builds a local evidence package from current workspace data; nothing is posted externally."
                ).classes("sgfx-summary")
                ui.label("Manual review remains required. Decision: not approval — evidence only.").classes(
                    "sgfx-muted"
                )

                async def _build(ticket_input=ticket_input, status_label=status_label) -> None:
                    from nicegui import run as nicegui_run

                    ticket_value = str(ticket_input.value or "").strip()
                    if not ticket_value:
                        ui.notify("Enter a ticket ID before building a review package.")
                        return
                    try:
                        job_state["job"] = await nicegui_run.io_bound(
                            start_dashboard_review_package_build,
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
            report_html_actions_host = ui.row().classes("sgfx-confirm-actions")
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

            def _report_html_url() -> str:
                path = _report_html_path()
                if path is None:
                    return ""
                try:
                    relative = path.resolve().relative_to(operator_ui_root(workspace).resolve())
                except ValueError:
                    return ""
                return "/sgfx-operator-ui/" + quote(str(relative).replace("\\", "/"), safe="/")

            async def _build_quality_report() -> None:
                ticket_value = _selected_report_ticket()
                if not ticket_value:
                    ui.notify("Choose or enter a Jira ticket before building the report.")
                    return
                build_report_button.disable()
                report_status.text = "Building Quality-Hero report..."
                try:
                    from nicegui import run as nicegui_run

                    result = await nicegui_run.io_bound(
                        build_dashboard_quality_hero_report,
                        workspace=workspace,
                        profile_id=str(snapshot["profile_id"]),
                        ticket_id=ticket_value,
                    )
                except Exception as exc:  # noqa: BLE001
                    report_status.text = f"Quality-Hero report failed: {exc}"
                    ui.notify("Quality-Hero report failed.")
                    return
                finally:
                    build_report_button.enable()
                report_state.clear()
                report_state.update(result)
                markdown_path = _report_markdown_path()
                report_status.text = (
                    f"Quality-Hero report {result.get('outcome', 'unknown')} "
                    f"(exit {result.get('exit_code', '?')}) for {ticket_value}."
                )
                report_path_label.text = f"Report: {markdown_path}" if markdown_path else "Report path unavailable."
                html_path = _report_html_path()
                report_html_label.text = "HTML report ready." if html_path else "HTML report path unavailable."
                report_html_actions_host.clear()
                if html_path:
                    with report_html_actions_host:
                        html_url = _report_html_url()
                        if html_url:
                            ui.button(
                                "Copy HTML report link",
                                on_click=lambda url=html_url: _copy_dashboard_link_to_clipboard(
                                    ui,
                                    url,
                                    "Quality-Hero HTML report",
                                ),
                            ).props("flat dense no-caps")
                        ui.button(
                            "Copy HTML report path",
                            on_click=lambda path=str(html_path): _copy_dashboard_text_to_clipboard(
                                ui,
                                path,
                                "Quality-Hero HTML report path",
                            ),
                        ).props("flat dense no-caps")
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

                async def _post_report_attachment() -> None:
                    ticket_value = _selected_report_ticket()
                    markdown_path = _report_markdown_path()
                    if not ticket_value or markdown_path is None:
                        ui.notify("Generate a report and choose a ticket before posting.")
                        return
                    post_button.disable()
                    attach_status.text = "Attaching Quality-Hero report to Jira..."
                    try:
                        from nicegui import run as nicegui_run

                        result = await nicegui_run.io_bound(
                            build_dashboard_quality_hero_report,
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
                    finally:
                        post_button.enable()
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
                            ui.button(
                                "Copy Jira attachment URL",
                                on_click=lambda jira_url=jira_url: _copy_dashboard_link_to_clipboard(
                                    ui,
                                    jira_url,
                                    "Jira attachment URL",
                                ),
                            ).props("flat dense no-caps").classes("sgfx-muted")
                        else:
                            ui.label("Jira attachment URL unavailable in response.").classes("sgfx-muted")
                    ui.notify("Quality-Hero report attached to Jira.")
                    attach_dialog.close()

                post_button = _attach_tooltip(
                    ui,
                    ui.button("Post", on_click=_post_report_attachment).props("color=primary"),
                    "Attach this local Markdown report to the selected Jira ticket.",
                )
                ui.button("Cancel", on_click=attach_dialog.close)

            build_report_button = _attach_tooltip(
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

def _render_operator_handoff_panel(ui: Any, snapshot: dict[str, Any], workspace: Path) -> None:
    page = next(page for page in snapshot["pages"] if page["id"] == "operator-handoff")
    payload = page.get("payload", {}) if isinstance(page.get("payload"), dict) else {}
    latest = payload.get("latest_handoff", {}) if isinstance(payload.get("latest_handoff"), dict) else {}
    active_ticket_id = str(snapshot.get("active_ticket_id", "") or "").strip()
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
            value=str(latest.get("ticket_id", "") or active_ticket_id),
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

            async def _start_session() -> None:
                from nicegui import run as nicegui_run

                await nicegui_run.io_bound(
                    _ensure_manual_review_dashboard_session,
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

                async def _record(
                    slug: str = slug,
                    verdict=verdict,
                    note=note,
                ) -> None:
                    selected = str(verdict.value or "").strip()
                    if not selected:
                        ui.notify("Select a manual-review verdict before recording.")
                        return
                    from nicegui import run as nicegui_run

                    await nicegui_run.io_bound(
                        record_manual_review_dashboard_step,
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

def _my_ticket_status_draft(ticket: dict[str, Any], workspace: Path) -> str:
    key = str(ticket.get("key", "") or "").strip().upper()
    summary = str(ticket.get("summary", "") or "").strip()
    status = str(ticket.get("status", "") or "unknown").strip()
    priority = str(ticket.get("priority", "") or "").strip()
    headline = f"Status update draft for {key}"
    if summary:
        headline += f" - {summary}"
    meta = [f"Current Jira status: {status}"]
    if priority:
        meta.append(f"Priority: {priority}")
    try:
        digest = build_latest_daily_digest(ticket_id=key, workspace=workspace)
    except Exception as exc:  # noqa: BLE001
        return (
            f"{headline}\n\n"
            f"{'; '.join(meta)}.\n\n"
            "SGFX could not read the local review evidence for this ticket yet. "
            f"Local evidence read failed with: {exc}\n\n"
            "Next step: build or refresh the local review package, then review the evidence before posting. "
            "Manual review remains required."
        )
    if bool(digest.get("data_available", False)):
        digest_text = render_daily_digest_text(digest).strip()
        return (
            f"{headline}\n\n"
            f"{'; '.join(meta)}.\n\n"
            f"{digest_text}\n\n"
            "Operator note: review and edit this draft before copying it to Jira. "
            "Manual review remains required; this is not an approval."
        )
    setup_hint = str(digest.get("setup_hint", "") or "").strip()
    if not setup_hint:
        setup_hint = f"sgfx-preflight.exe ticket-review {key} --profile <profile> --workspace {workspace} --json"
    return (
        f"{headline}\n\n"
        f"{'; '.join(meta)}.\n\n"
        "SGFX checked the local review evidence for this ticket and no review package is available in this workspace yet. "
        "No Jira post is sent.\n\n"
        f"Next step: {setup_hint}\n\n"
        "After the package is built, refresh My Tickets and edit this draft from the loaded evidence before copying it."
    )


def _genericize_failed_summary(payload: dict[str, Any], *, raw_prefix: str, generic_summary: str) -> None:
    summary = str(payload.get("summary", "") or "").strip()
    if summary.startswith(f"{raw_prefix}:"):
        payload.setdefault("diagnostic_detail", summary)
        payload["summary"] = generic_summary


def _build_my_tickets_payload(workspace: Path) -> dict[str, Any]:
    try:
        payload = search_my_unresolved_tickets(max_results=12, timeout_seconds=8)
    except Exception as exc:  # noqa: BLE001
        payload = {
            "status": "failed",
            "ticket_count": 0,
            "tickets": [],
            "summary": MY_TICKETS_UNAVAILABLE_SUMMARY,
            "diagnostic_detail": f"My Tickets unavailable: {exc}",
            "settings_hint": "Check local Jira setup before retrying.",
            "read_only": True,
            "is_approval": False,
            "jql": build_my_unresolved_ticket_jql(),
        }
    if not isinstance(payload, dict):
        payload = {
            "status": "failed",
            "ticket_count": 0,
            "tickets": [],
            "summary": "My Tickets unavailable: Jira returned an unexpected response.",
            "settings_hint": "Check local Jira setup before retrying.",
            "read_only": True,
            "is_approval": False,
            "jql": build_my_unresolved_ticket_jql(),
        }
    _genericize_failed_summary(
        payload,
        raw_prefix="My Tickets unavailable",
        generic_summary=MY_TICKETS_UNAVAILABLE_SUMMARY,
    )
    tickets = [ticket for ticket in payload.get("tickets", []) if isinstance(ticket, dict)]
    enriched_tickets: list[dict[str, Any]] = []
    for ticket in tickets:
        enriched = dict(ticket)
        enriched["status_draft"] = _my_ticket_status_draft(enriched, workspace)
        enriched_tickets.append(enriched)
    payload["tickets"] = enriched_tickets
    payload["ticket_count"] = len(enriched_tickets)
    payload.setdefault("jql", build_my_unresolved_ticket_jql())
    payload.setdefault("read_only", True)
    payload.setdefault("is_approval", False)
    return payload


def _build_weekly_ticket_draft_payload(workspace: Path) -> dict[str, Any]:
    try:
        payload = build_weekly_ticket_draft(workspace=workspace)
    except Exception as exc:  # noqa: BLE001
        payload = {
            "status": "failed",
            "jira_status": "failed",
            "summary": WEEKLY_TICKET_DRAFT_UNAVAILABLE_SUMMARY,
            "diagnostic_detail": f"Weekly Ticket Draft unavailable: {exc}",
            "text": "",
            "read_only": True,
            "is_approval": False,
        }
    if not isinstance(payload, dict):
        payload = {
            "status": "failed",
            "jira_status": "failed",
            "summary": "Weekly Ticket Draft unavailable: unexpected response.",
            "text": "",
            "read_only": True,
            "is_approval": False,
        }
    _genericize_failed_summary(
        payload,
        raw_prefix="Weekly Ticket Draft unavailable",
        generic_summary=WEEKLY_TICKET_DRAFT_UNAVAILABLE_SUMMARY,
    )
    payload.setdefault("read_only", True)
    payload.setdefault("is_approval", False)
    payload["text"] = render_weekly_ticket_draft_text(payload)
    return payload


def _render_my_tickets_panel(ui: Any, snapshot: dict[str, Any], workspace: Path) -> None:
    page = next(page for page in snapshot["pages"] if page["id"] == "my-tickets")
    payload = snapshot.get("my_tickets_payload", {}) if isinstance(snapshot.get("my_tickets_payload"), dict) else {}
    if not payload:
        payload = page.get("payload", {}) if isinstance(page.get("payload"), dict) else {}
    status = str(payload.get("status", "unknown"))
    tickets = [ticket for ticket in payload.get("tickets", []) if isinstance(ticket, dict)]
    with ui.column().classes("sgfx-page-panel").props('data-sgfx-my-tickets-page="true"'):
        with ui.row().classes("items-center justify-between full-width"):
            ui.label(str(page["title"])).classes("sgfx-panel-title")
            _render_status_chip(ui, status)
        ui.label(str(page["tagline"])).classes("sgfx-panel-tagline")
        ui.label(str(payload.get("summary", page.get("summary", "My Tickets unavailable.")))).classes("sgfx-summary")
        ui.label("Read-only Jira REST query. No Jira post is sent from this page.").classes("sgfx-muted")
        jql = str(payload.get("jql", build_my_unresolved_ticket_jql()) or "")
        if jql:
            ui.label(f"JQL: {jql}").classes("sgfx-muted")
        cache_status = str(payload.get("cache_status", "") or "").strip()
        if cache_status:
            ui.label(f"Cache: {cache_status}.").classes("sgfx-muted")
        if status == "loading":
            ui.linear_progress(value=0).props("indeterminate").classes("full-width")
            ui.label("Loading active tickets and local status drafts off the UI event loop.").classes("sgfx-muted")
            return
        if not tickets:
            settings_hint = str(payload.get("settings_hint", "") or "")
            if settings_hint:
                ui.label(settings_hint).classes("sgfx-muted")
            elif status == "available":
                ui.label("No assigned unresolved tickets were returned.").classes("sgfx-muted")
            return
        for ticket in tickets:
            key = str(ticket.get("key", "") or "").strip().upper()
            url = str(ticket.get("url", "") or "").strip()
            draft = str(ticket.get("status_draft", "") or "").strip()
            if not draft:
                draft = (
                    f"Status update draft for {key}\n\n"
                    "SGFX is still preparing the local evidence draft. Refresh My Tickets after the loader finishes."
                )
            with ui.column().classes("sgfx-my-ticket-item full-width").props('data-sgfx-my-ticket-row="true"'):
                with ui.row().classes("items-center full-width sgfx-my-ticket-header"):
                    if url:
                        ui.button(
                            key,
                            on_click=lambda url=url, key=key: _copy_dashboard_link_to_clipboard(ui, url, key),
                        ).props("flat dense no-caps").classes("sgfx-jira-ticket-key")
                    else:
                        ui.label(key).classes("sgfx-jira-ticket-key")
                    ui.label(str(ticket.get("status", "unknown"))).classes("sgfx-jira-status-pill")
                    priority = str(ticket.get("priority", "") or "").strip()
                    if priority:
                        ui.label(priority).classes("sgfx-jira-status-pill")
                ui.label(str(ticket.get("summary", ""))).classes("sgfx-summary")
                updated = str(ticket.get("updated", "") or "").strip()
                if updated:
                    ui.label(f"Updated: {updated}").classes("sgfx-muted")
                draft_input = (
                    ui.textarea(label=f"Editable status draft for {key}", value=draft)
                    .props("outlined")
                    .classes("full-width sgfx-my-ticket-draft")
                )
                with ui.row().classes("sgfx-confirm-actions"):
                    _attach_tooltip(
                        ui,
                        ui.button(
                            "Copy status draft",
                            on_click=lambda draft_input=draft_input, key=key: _copy_dashboard_text_to_clipboard(
                                ui,
                                str(draft_input.value or ""),
                                f"{key} status draft",
                            ),
                        ).props("color=primary no-caps"),
                        "Copy the edited local draft. SGFX does not post it to Jira.",
                    )
                    if url:
                        _attach_tooltip(
                            ui,
                            ui.button(
                                "Copy ticket link",
                                on_click=lambda url=url, key=key: _copy_dashboard_link_to_clipboard(ui, url, key),
                            ).props("flat dense no-caps"),
                            "Copy the Jira ticket link only.",
                        )


def _render_weekly_ticket_draft_panel(ui: Any, snapshot: dict[str, Any], workspace: Path) -> None:
    page = next(page for page in snapshot["pages"] if page["id"] == "weekly-ticket-draft")
    payload = (
        snapshot.get("weekly_ticket_draft_payload", {})
        if isinstance(snapshot.get("weekly_ticket_draft_payload"), dict)
        else {}
    )
    if not payload:
        payload = page.get("payload", {}) if isinstance(page.get("payload"), dict) else {}
    status = str(payload.get("status", payload.get("jira_status", "unknown")) or "unknown")
    draft_text = str(payload.get("text", "") or "").strip()
    if not draft_text:
        draft_text = render_weekly_ticket_draft_text(payload)
    with ui.column().classes("sgfx-page-panel").props('data-sgfx-weekly-ticket-draft-page="true"'):
        with ui.row().classes("items-center justify-between full-width"):
            ui.label(str(page["title"])).classes("sgfx-panel-title")
            _render_status_chip(ui, status)
        ui.label(str(page["tagline"])).classes("sgfx-panel-tagline")
        ui.label(str(payload.get("summary", page.get("summary", "Weekly Ticket Draft unavailable.")))).classes(
            "sgfx-summary"
        )
        ui.label("Draft only - review and edit before sending. SGFX doesn't send anything.").classes("sgfx-muted")
        if status == "loading":
            ui.linear_progress(value=0).props("indeterminate").classes("full-width")
            ui.label("Loading the weekly ticket draft off the UI event loop.").classes("sgfx-muted")
            return
        draft_input = (
            ui.textarea(label="Editable weekly ticket draft", value=draft_text)
            .props("outlined")
            .classes("full-width sgfx-weekly-ticket-draft")
        )
        with ui.row().classes("sgfx-confirm-actions"):
            _attach_tooltip(
                ui,
                ui.button(
                    "Copy draft",
                    on_click=lambda draft_input=draft_input: _copy_dashboard_text_to_clipboard(
                        ui,
                        str(draft_input.value or ""),
                        "weekly ticket draft",
                    ),
                ).props("color=primary no-caps"),
                "Copy the edited weekly draft. SGFX does not send it.",
            )


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

        def _poll_batch_io() -> dict[str, Any] | None:
            job = job_ref.get("job")
            if job is None:
                return {"_sgfx_stop_poll": True}
            return poll_dashboard_batch_full_qa_pass(job)

        def _apply_batch_poll(result: dict[str, Any] | None) -> None:
            try:
                if isinstance(result, dict) and result.get("_sgfx_stop_poll"):
                    _stop_timer()
                    return
                if result is not None:
                    _apply_result(result)
            except RuntimeError as exc:
                if not _parent_slot_deleted(exc):
                    raise
                _stop_timer()

        def _start_timer() -> None:
            _stop_timer()
            timer_ref["timer"] = _start_io_bound_poll_timer(1.0, _poll_batch_io, _apply_batch_poll)

        async def _start_batch() -> None:
            from nicegui import run as nicegui_run

            raw_profiles = profiles_select.value
            selected = raw_profiles if isinstance(raw_profiles, list) else [raw_profiles]
            profiles = [str(profile).strip() for profile in selected if str(profile).strip()]
            if not profiles:
                ui.notify("Select at least one profile before starting the batch.")
                return
            try:
                job_ref["job"] = await nicegui_run.io_bound(
                    start_dashboard_batch_full_qa_pass,
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
            first_result = await nicegui_run.io_bound(poll_dashboard_batch_full_qa_pass, job_ref["job"])
            if first_result is not None:
                _apply_result(first_result)

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
    jira_profile_tickets_payload: dict[str, Any] | None = None,
    jira_profile_tickets_loader: Callable[[str], Any] | None = None,
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
        "visual_payloads": {},
        "visual_payloads_loading": set(),
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
        jira_card_host = ui.column().classes("full-width")

        def _paint_jira_profile_tickets(payload: dict[str, Any] | None) -> None:
            jira_card_host.clear()
            with jira_card_host:
                _render_jira_profile_tickets_card(
                    ui,
                    profile_id,
                    payload=payload,
                    open_page=open_page,
                )

        _paint_jira_profile_tickets(jira_profile_tickets_payload)
        if (
            jira_profile_tickets_loader is not None
            and str((jira_profile_tickets_payload or {}).get("status", "")).casefold() == "loading"
        ):
            async def _load_jira_profile_tickets_card() -> None:
                try:
                    payload = await jira_profile_tickets_loader(profile_id)
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
                _paint_jira_profile_tickets(payload if isinstance(payload, dict) else None)

            try:
                from nicegui import background_tasks

                background_tasks.create(_load_jira_profile_tickets_card(), name="sgfx-jira-profile-card")
            except RuntimeError:
                asyncio.create_task(_load_jira_profile_tickets_card())

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

        with ui.dialog() as qa_pass_report_dialog:
            with ui.card().classes("sgfx-viewer-dialog-card sgfx-qa-pass-report-dialog"):
                with ui.row().classes("items-center justify-between full-width"):
                    qa_pass_report_title = ui.label("QA Pass Report").classes("sgfx-panel-title")
                    ui.button("Close", on_click=qa_pass_report_dialog.close).props("flat dense no-caps")
                ui.label(
                    "Full QA Pass evidence is rendered below. Manual review remains required."
                ).classes("sgfx-muted")
                qa_pass_report_frame_host = ui.column().classes("sgfx-viewer-frame-host")

        async def _open_wizard_screenshot_viewer(item_key: str, label: str = "") -> None:
            from nicegui import run as nicegui_run

            try:
                await nicegui_run.io_bound(
                    _materialize_screenshot_review_viewer_for_dashboard,
                    profile_id,
                    workspace,
                    bmw_root=bmw_root,
                )
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

        def _open_qa_pass_report_dialog(url: str, title: str) -> None:
            safe_url = html_escape(url, quote=True)
            qa_pass_report_title.text = title or "QA Pass Report"
            qa_pass_report_frame_host.clear()
            with qa_pass_report_frame_host:
                ui.html(
                    f'<iframe data-sgfx-inline-viewer="true" class="sgfx-viewer-iframe" '
                    f'src="{safe_url}" title="QA Pass Report"></iframe>',
                    sanitize=False,
                ).classes("full-width")
            qa_pass_report_dialog.open()

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

        def _result_may_have_visuals(result: dict[str, Any]) -> bool:
            workbook_preview = result.get("workbook_preview", {})
            return bool(
                result.get("screenshot_review_rows")
                or result.get("file_activity")
                or (isinstance(workbook_preview, dict) and workbook_preview.get("workbook_path"))
            )

        def _action_visual_cache_key(result: dict[str, Any]) -> str:
            row_parts: list[str] = []
            rows = result.get("screenshot_review_rows", [])
            if isinstance(rows, list):
                for row in rows[:4]:
                    if not isinstance(row, dict):
                        continue
                    row_parts.extend(
                        str(row.get(key, "") or "")
                        for key in ("key", "label", "expected_path", "actual_path", "diff_path")
                    )
            workbook_preview = result.get("workbook_preview", {})
            workbook_path = (
                str(workbook_preview.get("workbook_path", "") or "")
                if isinstance(workbook_preview, dict)
                else ""
            )
            return json.dumps(
                {
                    "action": str(result.get("action_id", "")),
                    "status": str(result.get("status", "")),
                    "summary": str(result.get("summary", "")),
                    "rows": row_parts,
                    "file_activity": [
                        str(item.get("path", "") or "")
                        for item in result.get("file_activity", [])
                        if isinstance(item, dict)
                    ][:4],
                    "workbook_path": workbook_path,
                },
                sort_keys=True,
            )

        def _render_action_visuals_loading(visual_label: Any, visual_host: Any) -> None:
            visual_host.clear()
            visual_label.visible = True
            visual_host.visible = True
            with visual_host:
                ui.linear_progress(value=0).props("indeterminate").classes("full-width")
                ui.label("Preparing visual evidence off the UI event loop...").classes("sgfx-muted")

        def _action_visual_payload_for(result: dict[str, Any]) -> dict[str, Any] | None:
            payloads = wizard_state.get("visual_payloads", {})
            if not isinstance(payloads, dict):
                wizard_state["visual_payloads"] = payloads = {}
            payload = payloads.get(_action_visual_cache_key(result))
            return payload if isinstance(payload, dict) else None

        def _schedule_action_visual_payload(
            result: dict[str, Any],
            *,
            on_ready: Callable[[dict[str, Any]], None],
        ) -> None:
            if not _result_may_have_visuals(result):
                on_ready(_empty_action_visual_payload(result))
                return
            cache_key = _action_visual_cache_key(result)
            payloads = wizard_state.get("visual_payloads", {})
            if isinstance(payloads, dict) and isinstance(payloads.get(cache_key), dict):
                on_ready(payloads[cache_key])
                return
            loading = wizard_state.get("visual_payloads_loading", set())
            if not isinstance(loading, set):
                wizard_state["visual_payloads_loading"] = loading = set()
            if cache_key in loading:
                return
            loading.add(cache_key)

            async def _build_and_apply() -> None:
                try:
                    from nicegui import run as nicegui_run

                    payload = await nicegui_run.io_bound(_build_action_visual_payload, result)
                except Exception:  # noqa: BLE001
                    payload = _empty_action_visual_payload(result)
                finally:
                    loading.discard(cache_key)
                payloads = wizard_state.get("visual_payloads", {})
                if not isinstance(payloads, dict):
                    wizard_state["visual_payloads"] = payloads = {}
                payloads[cache_key] = payload
                on_ready(payload)

            try:
                from nicegui import background_tasks

                background_tasks.create(_build_and_apply(), name="sgfx-action-visuals")
            except RuntimeError:
                asyncio.create_task(_build_and_apply())

        def _schedule_action_visual_render(
            result: dict[str, Any],
            *,
            visual_label: Any,
            visual_host: Any,
            open_screenshot_viewer: Callable[[str, str], None] | None = None,
        ) -> None:
            cached = _action_visual_payload_for(result)
            if cached is not None:
                _render_action_visuals(
                    ui,
                    result,
                    visual_label=visual_label,
                    visual_host=visual_host,
                    open_screenshot_viewer=open_screenshot_viewer,
                    visual_payload=cached,
                )
                return
            if _result_may_have_visuals(result):
                _render_action_visuals_loading(visual_label, visual_host)
            else:
                _render_action_visuals(
                    ui,
                    result,
                    visual_label=visual_label,
                    visual_host=visual_host,
                    open_screenshot_viewer=open_screenshot_viewer,
                    visual_payload=_empty_action_visual_payload(result),
                )
                return

            def _paint(payload: dict[str, Any]) -> None:
                _render_action_visuals(
                    ui,
                    result,
                    visual_label=visual_label,
                    visual_host=visual_host,
                    open_screenshot_viewer=open_screenshot_viewer,
                    visual_payload=payload,
                )

            _schedule_action_visual_payload(result, on_ready=_paint)

        def _typical_range_for_step(step: dict[str, Any]) -> str:
            step_id = str(step.get("id", ""))
            actions = [action for action in step.get("inline_actions", []) if isinstance(action, dict)]
            for action in actions:
                action_id = str(action.get("id", ""))
                if action_id == GENERATE_WORKBOOK_ACTION_ID:
                    return "typical 1-10 min"
                if action_id == SCREENSHOT_CAPTURE_ACTION_ID:
                    return str(action.get("typical_range", "typical 2-10 min"))
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

            def _poll_action_io() -> dict[str, Any] | None:
                job = job_state.get("job")
                if job is None:
                    return {"_sgfx_stop_poll": True}
                poller = job_state.get("poller")
                if poller is None:
                    return None
                return poller(job)

            def _apply_action_poll(result: dict[str, Any] | None) -> None:
                try:
                    if isinstance(result, dict) and result.get("_sgfx_stop_poll"):
                        _stop_timer()
                        return
                    label = str(job_state.get("label", "local action"))
                    if result is None:
                        return
                    live_output.value = _action_output_text(result)
                    eta_label.text = _eta_text(
                        elapsed=str(result.get("elapsed_label", "00:00")),
                        typical=str(result.get("typical_range", action.get("typical_range", "typical <1 min"))),
                    )
                    _render_action_technical_details(ui, result, details_host=details_host)
                    _schedule_action_visual_render(
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

            def _launch_job_io() -> dict[str, Any]:
                try:
                    if action_id == GENERATE_WORKBOOK_ACTION_ID:
                        return {
                            "job": start_delivery_workbook_generation(
                                profile_id=profile_id,
                                workspace=workspace,
                                bmw_root=bmw_root,
                                operator_confirmed=True,
                            ),
                            "poller": poll_delivery_workbook_generation,
                            "label": "delivery workbook generation",
                        }
                    if action_id == SCREENSHOT_CAPTURE_ACTION_ID:
                        return {
                            "job": start_screenshot_capture_with_export_check(
                                profile_id=profile_id,
                                workspace=workspace,
                                bmw_root=bmw_root,
                                operator_confirmed=True,
                            ),
                            "poller": poll_screenshot_capture_with_export_check,
                            "label": "screenshot capture",
                        }
                    raise ValueError(f"Unsupported Full QA Pass action: {action_id}")
                except Exception as exc:  # noqa: BLE001
                    return {"error": exc}

            def _apply_launch_job(result: dict[str, Any]) -> None:
                _stop_launch_timer()
                error = result.get("error") if isinstance(result, dict) else None
                if isinstance(error, Exception):
                    _finish_start_failure(error)
                    return
                job_state["job"] = result.get("job")
                job_state["poller"] = result.get("poller")
                job_state["label"] = str(result.get("label", "local action"))
                _append_activity(action=action_id, note=f"Started {job_state['label']} from Full QA Pass.")
                job_state["timer"] = _start_io_bound_poll_timer(1.0, _poll_action_io, _apply_action_poll)

            job_state["launch_timer"] = _start_io_bound_poll_timer(0.1, _launch_job_io, _apply_launch_job)

        async def _cancel_subprocess_action(
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
                from nicegui import run as nicegui_run

                cancel_button.disable()
                completion_label.text = "Stopping local subprocess..."
                if action_id == GENERATE_WORKBOOK_ACTION_ID:
                    result = await nicegui_run.io_bound(cancel_delivery_workbook_generation, job_state["job"])
                elif action_id == SCREENSHOT_CAPTURE_ACTION_ID:
                    result = await nicegui_run.io_bound(cancel_screenshot_capture_with_export_check, job_state["job"])
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
                _schedule_action_visual_render(
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

        async def _invoke_operator_action(
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
                    from nicegui import run as nicegui_run

                    completion_label.text = "Checking manual-review evidence..."
                    assist = await nicegui_run.io_bound(build_manual_review_assist, profile_id, workspace=workspace)
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

            def _notification_tick_io() -> bool:
                return True

            def _send_notification(_ready: bool) -> None:
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

            timer_ref["timer"] = _start_io_bound_poll_timer(2.0, _notification_tick_io, _send_notification)

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

        def _refresh_full_qa_after_local_action(
            action_id: str,
            *,
            completed_step_ids: set[str],
            result: dict[str, Any],
        ) -> None:
            async def _refresh() -> None:
                trusted = bool(trusted_control.value)
                notice.text = "Refreshing Full QA Pass evidence after local action..."
                try:
                    from nicegui import run as nicegui_run

                    refreshed_payload = await nicegui_run.io_bound(
                        build_full_qa_pass,
                        profile_id,
                        workspace=workspace,
                        bmw_root=bmw_root,
                        trusted_tool_mode=trusted,
                    )
                except Exception as exc:  # noqa: BLE001
                    current_payload = wizard_state["payload"] if isinstance(wizard_state.get("payload"), dict) else {}
                    _persist_wizard_state(current_payload, reason=f"{action_id}_refresh_failed", status="in_progress")
                    notice.text = f"Full QA Pass refresh failed after local action: {exc}"
                    _notify_ui("Full QA Pass refresh failed after local action.")
                    return
                wizard_state["completed"].update(step_id for step_id in completed_step_ids if step_id)
                notice.text = str(
                    refreshed_payload.get(
                        "summary",
                        result.get("summary", "Full QA Pass evidence refreshed after local action."),
                    )
                )
                _persist_wizard_state(refreshed_payload, reason=f"{action_id}_refresh", status="in_progress")
                _render_payload(refreshed_payload)

            try:
                from nicegui import background_tasks

                background_tasks.create(_refresh(), name="sgfx-full-qa-refresh-after-action")
            except RuntimeError:
                asyncio.create_task(_refresh())

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

        def _handle_action_completed(step_id: str, result: dict[str, Any], *, action_id: str = "") -> None:
            if step_id:
                wizard_state["action_results"][step_id] = result
                _replace_step_payload(step_id, result)
            if action_id == GENERATE_WORKBOOK_ACTION_ID:
                completed_step_ids = {step_id, "delivery-checklist", "delivery-workbook-trigger"}
                wizard_state["completed"].update(item for item in completed_step_ids if item)
                _refresh_full_qa_after_local_action(
                    action_id,
                    completed_step_ids=completed_step_ids,
                    result=result,
                )
                return
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

        async def _run_diagnostic_chain_action(
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
                    async def _confirm_followup(_event: Any = None, current: dict[str, Any] = action) -> None:
                        _hide_prompt_overlay(prompt_overlay)
                        await _run_diagnostic_chain_action(
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
                                    ui.button("Yes", on_click=_confirm_followup).props(
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

                def _poll_worker_io() -> dict[str, Any]:
                    return {
                        "completed": bool(worker_state.get("completed", False)),
                        "result": worker_state.get("result"),
                    }

                def _apply_poll_worker(state_payload: dict[str, Any]) -> None:
                    if not bool(state_payload.get("completed", False)):
                        return
                    _cancel_background_poll_timer(worker_state.get("timer"))
                    worker_state["timer"] = None
                    _clear_diagnostic_running_state()
                    result = state_payload.get("result")
                    if isinstance(result, dict):
                        _apply_diagnostic_result(result)

                threading.Thread(target=_worker, name="sgfx-missing-actual-diagnostics", daemon=True).start()
                worker_state["timer"] = _start_io_bound_poll_timer(0.5, _poll_worker_io, _apply_poll_worker)
                return

            from nicegui import run as nicegui_run

            result = await nicegui_run.io_bound(_execute_diagnostic_chain)
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
                        action_id=str(current.get("id", "")),
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
                        ui.button("Run", on_click=lambda _event=None, current=action: _confirm_start(current)).props(
                            "color=primary"
                        )
                        ui.button("Skip", on_click=lambda: _hide_prompt_overlay(prompt_overlay))

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

            async def _cancel_current_action(
                _event: Any = None,
                current: dict[str, Any] = action,
            ) -> None:
                await _cancel_subprocess_action(
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

            cancel_button = ui.button(
                "Cancel running action",
                on_click=_cancel_current_action,
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

                async def _save_handoff() -> None:
                    await _invoke_operator_action(
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
                async def _run_operator_action(_event: Any = None, current: dict[str, Any] = action) -> None:
                    await _invoke_operator_action(
                        current,
                        status_label=status_label,
                        completion_label=completion_label,
                    )
                    if str(status_label.text) == "passed":
                        _mark_step_completed(str(current.get("step_id", "")))

                _attach_tooltip(
                    ui,
                    ui.button(label, on_click=_run_operator_action),
                    str(action.get("summary", "")),
                )
                return
            if kind == "diagnostic_chain":
                async def _run_diagnostic_action(_event: Any = None, current: dict[str, Any] = action) -> None:
                    await _run_diagnostic_chain_action(
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
                    ui.button(label, on_click=_run_diagnostic_action),
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
                                action_id=str(current.get("id", "")),
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
                        qa_report_summary = build_qa_pass_report_summary(payload)
                        with ui.column().classes("sgfx-qa-pass-verdict"):
                            ui.label(str(qa_report_summary.get("hero_text", ""))).classes("sgfx-panel-title")
                            ui.label(
                                "Evidence prepared locally. Manual review remains required before any delivery decision."
                            ).classes("sgfx-muted")
                            with ui.row().classes("sgfx-hero-stats"):
                                ui.label(
                                    f"{qa_report_summary.get('passed_count', 0)} passed"
                                ).classes("sgfx-status-pill")
                                ui.label(
                                    f"{qa_report_summary.get('screenshot_diff_count', 0)} screenshot diffs"
                                ).classes("sgfx-status-pill")
                                ui.label(
                                    f"{qa_report_summary.get('manual_review_item_count', 0)} manual items"
                                ).classes("sgfx-status-pill")
                                risk_score = qa_report_summary.get("risk_score")
                                risk_level = str(qa_report_summary.get("risk_level", "unknown"))
                                risk_text = (
                                    f"risk {risk_score}/100 {risk_level}"
                                    if risk_score is not None
                                    else f"risk {risk_level}"
                                )
                                ui.label(risk_text).classes("sgfx-status-pill")
                            report_status_label = ui.label("Build an interactive report or export a shareable ZIP.").classes(
                                "sgfx-muted"
                            )
                            report_export_host = ui.column().classes("full-width")
                            report_controls: dict[str, Any] = {}

                            async def _open_qa_pass_report() -> None:
                                from nicegui import run as nicegui_run

                                button = report_controls.get("open")
                                if button is not None:
                                    button.disable()
                                report_status_label.text = "Building interactive QA Pass report..."
                                try:
                                    result = await nicegui_run.io_bound(
                                        build_dashboard_qa_pass_report,
                                        workspace=workspace,
                                        profile_id=profile_id,
                                        payload=payload,
                                    )
                                except Exception as exc:  # noqa: BLE001
                                    report_status_label.text = f"QA Pass report failed: {exc}"
                                    _notify_ui("QA Pass report failed.")
                                    return
                                finally:
                                    if button is not None:
                                        button.enable()
                                url = str(result.get("url", "") or _qa_pass_report_url(profile_id))
                                separator = "&" if "?" in url else "?"
                                _open_qa_pass_report_dialog(
                                    f"{url}{separator}t={int(time.time())}",
                                    f"QA Pass Report - {profile_id}",
                                )
                                report_status_label.text = f"QA Pass report ready: {result.get('html_path', '')}"
                                _notify_ui("QA Pass report ready.")

                            async def _export_qa_pass_report() -> None:
                                from nicegui import run as nicegui_run

                                button = report_controls.get("export")
                                if button is not None:
                                    button.disable()
                                report_status_label.text = "Exporting QA Pass report ZIP..."
                                try:
                                    result = await nicegui_run.io_bound(
                                        export_dashboard_qa_pass_report,
                                        workspace=workspace,
                                        profile_id=profile_id,
                                        bmw_root=bmw_root,
                                        payload=payload,
                                    )
                                except Exception as exc:  # noqa: BLE001
                                    report_status_label.text = f"QA Pass ZIP export failed: {exc}"
                                    _notify_ui("QA Pass ZIP export failed.")
                                    return
                                finally:
                                    if button is not None:
                                        button.enable()
                                zip_path = str(result.get("zip_path", "") or "")
                                zip_size = _size_label(_full_qa_int(result.get("zip_size_bytes")))
                                report_status_label.text = f"Export ZIP saved: {zip_path} ({zip_size})."
                                report_export_host.clear()
                                with report_export_host:
                                    ui.label(f"Export ZIP: {zip_path}").classes("sgfx-muted")
                                    ui.button(
                                        "Copy ZIP path",
                                        on_click=lambda path=zip_path: _copy_dashboard_text_to_clipboard(
                                            ui,
                                            path,
                                            "QA Pass ZIP path",
                                        ),
                                    ).props("flat dense no-caps")
                                _notify_ui("QA Pass ZIP exported.")

                            with ui.row().classes("sgfx-confirm-actions"):
                                report_controls["open"] = _attach_tooltip(
                                    ui,
                                    ui.button("Open report", on_click=_open_qa_pass_report).props("color=primary"),
                                    "Build the interactive Full QA Pass report off the UI event loop.",
                                )
                                report_controls["export"] = _attach_tooltip(
                                    ui,
                                    ui.button("Export ZIP", on_click=_export_qa_pass_report),
                                    "Export a standalone report HTML plus evidence into one local ZIP.",
                                )
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
                                cached_visual_payload = _action_visual_payload_for(step_payload)
                                if cached_visual_payload is not None:
                                    _render_action_visuals(
                                        ui,
                                        step_payload,
                                        visual_label=done_visual_label,
                                        visual_host=done_visual_host,
                                        open_screenshot_viewer=_open_wizard_screenshot_viewer,
                                        visual_payload=cached_visual_payload,
                                    )
                                elif _result_may_have_visuals(step_payload):
                                    _render_action_visuals_loading(done_visual_label, done_visual_host)

                                    def _rerender_payload(_payload: dict[str, Any]) -> None:
                                        _render_payload(payload, preserve_index=True)

                                    _schedule_action_visual_payload(step_payload, on_ready=_rerender_payload)
                                else:
                                    _render_action_visuals(
                                        ui,
                                        step_payload,
                                        visual_label=done_visual_label,
                                        visual_host=done_visual_host,
                                        open_screenshot_viewer=_open_wizard_screenshot_viewer,
                                        visual_payload=_empty_action_visual_payload(step_payload),
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

        async def _run_full_pass_async() -> None:
            trusted = bool(trusted_control.value)
            run_full_pass_button.disable()
            notice.text = "Full QA Pass running off the UI event loop..."
            try:
                from nicegui import run as nicegui_run

                payload = await nicegui_run.io_bound(
                    build_full_qa_pass,
                    profile_id,
                    workspace=workspace,
                    bmw_root=bmw_root,
                    trusted_tool_mode=trusted,
                )
            except Exception as exc:  # noqa: BLE001
                notice.text = f"Full QA Pass failed: {exc}"
                _notify_ui("Full QA Pass failed.")
                return
            finally:
                run_full_pass_button.enable()
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

        def _run_full_pass() -> None:
            from nicegui import background_tasks

            background_tasks.create(_run_full_pass_async(), name="sgfx-full-qa-pass")

        run_full_pass_button = _attach_tooltip(
            ui,
            ui.button("Run full QA pass", on_click=_run_full_pass).classes("sgfx-html-action-button"),
            "Start the local evidence chain for the selected profile.",
        )
        _render_resume_prompt()
        _render_payload(initial_payload)

_full_qa_pass_page = _with_main_globals(_full_qa_pass_page)
_batch_full_qa_pass_page = _with_main_globals(_batch_full_qa_pass_page)
_my_tickets_page = _with_main_globals(_my_tickets_page)
_weekly_ticket_draft_page = _with_main_globals(_weekly_ticket_draft_page)
_is_truthy_trigger = _with_main_globals(_is_truthy_trigger)
_full_qa_pass_token = _with_main_globals(_full_qa_pass_token)
_full_qa_pass_dedup_key = _with_main_globals(_full_qa_pass_dedup_key)
_should_fire_full_qa_pass = _with_main_globals(_should_fire_full_qa_pass)
_reset_full_qa_pass_dedup = _with_main_globals(_reset_full_qa_pass_dedup)
_publish_live_state = _with_main_globals(_publish_live_state)
_snapshot_with_full_qa_payload = _with_main_globals(_snapshot_with_full_qa_payload)
_screenshot_review_viewer_output_root = _with_main_globals(_screenshot_review_viewer_output_root)
_missing_actual_diagnostics_output_root = _with_main_globals(_missing_actual_diagnostics_output_root)
_qa_pass_report_output_root = _with_main_globals(_qa_pass_report_output_root)
_qa_pass_report_url = _with_main_globals(_qa_pass_report_url)
build_dashboard_qa_pass_report = _with_main_globals(build_dashboard_qa_pass_report)
export_dashboard_qa_pass_report = _with_main_globals(export_dashboard_qa_pass_report)
_screenshot_review_viewer_url = _with_main_globals(_screenshot_review_viewer_url)
_materialize_screenshot_review_viewer_for_dashboard = _with_main_globals(_materialize_screenshot_review_viewer_for_dashboard)
_notify_completion_safe = _with_main_globals(_notify_completion_safe)
_full_qa_completion_notification = _with_main_globals(_full_qa_completion_notification)
_manual_review_profile_token = _with_main_globals(_manual_review_profile_token)
_manual_review_dashboard_session_id = _with_main_globals(_manual_review_dashboard_session_id)
_load_manual_review_dashboard_session = _with_main_globals(_load_manual_review_dashboard_session)
_ensure_manual_review_dashboard_session = _with_main_globals(_ensure_manual_review_dashboard_session)
_manual_review_step_recorded = _with_main_globals(_manual_review_step_recorded)
_manual_review_step_detail = _with_main_globals(_manual_review_step_detail)
_manual_review_page = _with_main_globals(_manual_review_page)
_validate_review_package_inputs = _with_main_globals(_validate_review_package_inputs)
_dashboard_review_package_command = _with_main_globals(_dashboard_review_package_command)
_build_tail_text = _with_main_globals(_build_tail_text)
_build_tail_lines = _with_main_globals(_build_tail_lines)
_build_combined_tail_lines = _with_main_globals(_build_combined_tail_lines)
_size_label = _with_main_globals(_size_label)
_build_package_file_activity = _with_main_globals(_build_package_file_activity)
_elapsed_label = _with_main_globals(_elapsed_label)
_dashboard_full_qa_pass_command = _with_main_globals(_dashboard_full_qa_pass_command)
_batch_profile_safe_name = _with_main_globals(_batch_profile_safe_name)
_read_json_payload = _with_main_globals(_read_json_payload)
_batch_step_payload = _with_main_globals(_batch_step_payload)
_batch_profile_result = _with_main_globals(_batch_profile_result)
_batch_progress_payload = _with_main_globals(_batch_progress_payload)
_complete_batch_full_qa_pass = _with_main_globals(_complete_batch_full_qa_pass)
_start_batch_profile_process = _with_main_globals(_start_batch_profile_process)
start_dashboard_batch_full_qa_pass = _with_main_globals(start_dashboard_batch_full_qa_pass)
request_cancel_dashboard_batch_full_qa_pass = _with_main_globals(request_cancel_dashboard_batch_full_qa_pass)
poll_dashboard_batch_full_qa_pass = _with_main_globals(poll_dashboard_batch_full_qa_pass)
_review_build_progress_payload = _with_main_globals(_review_build_progress_payload)
_complete_review_package_build = _with_main_globals(_complete_review_package_build)
start_dashboard_review_package_build = _with_main_globals(start_dashboard_review_package_build)
poll_dashboard_review_package_build = _with_main_globals(poll_dashboard_review_package_build)
cancel_dashboard_review_package_build = _with_main_globals(cancel_dashboard_review_package_build)
build_dashboard_review_package = _with_main_globals(build_dashboard_review_package)
_quality_hero_report_output_root = _with_main_globals(_quality_hero_report_output_root)
_dashboard_quality_hero_report_command = _with_main_globals(_dashboard_quality_hero_report_command)
_dashboard_jira_attachment_endpoint = _with_main_globals(_dashboard_jira_attachment_endpoint)
_attachment_response_url = _with_main_globals(_attachment_response_url)
_attachment_response_id = _with_main_globals(_attachment_response_id)
build_dashboard_quality_hero_report = _with_main_globals(build_dashboard_quality_hero_report)
_build_action_visual_payload = _with_main_globals(_build_action_visual_payload)
_render_action_visuals = _with_main_globals(_render_action_visuals)
_render_action_technical_details = _with_main_globals(_render_action_technical_details)
_full_qa_int = _with_main_globals(_full_qa_int)
_full_qa_step_payload = _with_main_globals(_full_qa_step_payload)
_full_qa_step_map = _with_main_globals(_full_qa_step_map)
_full_qa_step_status = _with_main_globals(_full_qa_step_status)
_full_qa_screenshot_counts = _with_main_globals(_full_qa_screenshot_counts)
_full_qa_risk_draft = _with_main_globals(_full_qa_risk_draft)
_full_qa_manual_review_draft = _with_main_globals(_full_qa_manual_review_draft)
_full_qa_handoff_draft = _with_main_globals(_full_qa_handoff_draft)
_full_qa_bulk_ack_drafts = _with_main_globals(_full_qa_bulk_ack_drafts)
_render_daily_digest_panel = _with_main_globals(_render_daily_digest_panel)
_render_operator_handoff_panel = _with_main_globals(_render_operator_handoff_panel)
_render_manual_review_panel = _with_main_globals(_render_manual_review_panel)
_my_ticket_status_draft = _with_main_globals(_my_ticket_status_draft)
_build_my_tickets_payload = _with_main_globals(_build_my_tickets_payload)
_build_weekly_ticket_draft_payload = _with_main_globals(_build_weekly_ticket_draft_payload)
_render_my_tickets_panel = _with_main_globals(_render_my_tickets_panel)
_render_weekly_ticket_draft_panel = _with_main_globals(_render_weekly_ticket_draft_panel)
_render_batch_full_qa_pass_panel = _with_main_globals(_render_batch_full_qa_pass_panel)
_render_full_qa_pass_panel = _with_main_globals(_render_full_qa_pass_panel)
