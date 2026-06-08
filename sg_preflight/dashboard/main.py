from __future__ import annotations

import asyncio
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
import subprocess
import sys
import threading
import time
from time import monotonic
from typing import Any, Callable
from urllib.parse import quote_plus
from urllib.parse import quote

from sg_preflight.activity_log import append_activity_entry
from sg_preflight.assets import runtime_asset_dir, runtime_asset_path, runtime_asset_root
from sg_preflight import dashboard_grafiks as _dashboard_grafiks
from sg_preflight import dashboard_preferences as _dashboard_preferences
from sg_preflight.bmw_delivery import read_bmw_screenshot_state
from sg_preflight.bmw_pipeline_auto_fix import (
    MISSING_ACTUAL_DIAGNOSTIC_ACTION_ID,
    render_missing_actual_diagnostic_text,
    run_missing_actual_diagnostic_chain,
)
from sg_preflight.bmw_process import workflow_contracts
from sg_preflight.cross_car_comparison import build_cross_car_comparison
from sg_preflight.daily_digest import build_latest_daily_digest, render_daily_digest_text
from sg_preflight.delivery_checklist import read_delivery_checklist
from sg_preflight.delivery_readiness import (
    STATUS_DELIVERED,
    STATUS_NOT_DELIVERED_YET,
    STATUS_UNKNOWN,
    build_delivery_readiness_board,
)
from sg_preflight.api_version_coverage import IMPACT_REVIEW_LABEL, build_api_version_coverage_board
from sg_preflight.country_variant_coverage import (
    MAPPING_REVIEW_LABEL,
    MISSING_EXPECTED_LABEL,
    NO_RUNTIME_LABEL,
    build_country_variant_coverage_board,
)
from sg_preflight.export_size_trend import (
    SIGNIFICANT_CHANGE_LABEL,
    UNREADABLE_LAYOUT_LABEL,
    build_export_size_trend_board,
)
from sg_preflight.disabled_tests import CAUTIOUS_BASELINE_LABEL, build_disabled_tests_board
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
from sg_preflight.jira_client import (
    DEFAULT_JIRA_URL,
    build_my_unresolved_ticket_jql,
    load_jira_credentials,
    search_jira_profile_tickets,
    search_my_unresolved_tickets,
)
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
from sg_preflight.qa_workflows import list_workflows
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
from sg_preflight.setup_doctor import build_setup_doctor_report
from sg_preflight.subprocess_utils import hidden_subprocess_kwargs, sgfx_cli_command
from sg_preflight.team_digest_board import build_team_daily_digest_board
from sg_preflight.utils import ensure_parent
from sg_preflight.visual_review import build_visual_review_prep
from sg_preflight.dashboard_webserver import (
    BROWSER_FALLBACK_ENV,
    FORCE_FROZEN_NATIVE_ENV,
    NATIVE_RETURN_FALLBACK_SECONDS,
    STARTUP_LOG_NAME,
    WEBVIEW2_RUNTIME_GUID,
    _browser_fallback_show_requested,
    _find_open_dashboard_port,
    _frozen_native_window_allowed,
    _launch_browser_fallback_process,
    _packaged_native_unavailable,
    _run_nicegui,
    append_startup_log,
    startup_log_path,
    webview2_runtime_available,
)
from sg_preflight.dashboard_preferences import (
    _abbreviate_workspace_text,
    _bool_preference,
    _candidate_git_roots,
    _clean_theme,
    _dashboard_active_ticket_id as _dashboard_active_ticket_id_impl,
    _dashboard_build_sha,
    _dashboard_exe_sha256,
    _dashboard_feedback_context,
    _dashboard_feedback_recipient,
    _dashboard_notifications_enabled,
    _dashboard_preferred_profile_id,
    _dashboard_profile_known,
    _dashboard_status,
    _dashboard_ticket_from_git_branch,
    _dashboard_ticket_from_operator_state,
    _daily_digest_ticket_context as _daily_digest_ticket_context_impl,
    _delete_full_qa_wizard_state,
    _full_qa_profile_output_token,
    _full_qa_wizard_state_path,
    _operator_state_path,
    _path_label,
    _payload_summary,
    _preferred_source_repo_root,
    _profile_option_label,
    _read_full_qa_wizard_state,
    _read_operator_state_json,
    _resolve_dashboard_profile_id,
    _source_repo_root_candidates,
    _source_repo_root_from_value,
    _ticket_id_from_payload,
    _ticket_ids_from_activity_log,
    _utc_now,
    _workspace,
    _write_active_ticket_state,
    _write_dashboard_notifications_preference,
    _write_dashboard_profile_preference,
    _write_full_qa_wizard_state,
    dashboard_profile_options,
    load_dashboard_preference,
    save_dashboard_preference,
)
from sg_preflight.dashboard_grafiks import (
    GRAFIKS_CXX_BUILD_DIR,
    GRAFIKS_DEFAULT_BMW_CARS_ROOT,
    GRAFIKS_MODE_WARNING_BODY,
    GRAFIKS_MODE_WARNING_TITLE,
    GRAFIKS_MODE_WIP_HINT,
    GRAFIKS_SHELL_EXE_ENV_KEYS,
    GRAFIKS_SHELL_EXE_NAME,
    _dashboard_source_root,
    _grafiks_bmw_cars_root,
    _grafiks_not_installed_message,
    _grafiks_profile_registry_file,
    _grafiks_shell_command,
    _grafiks_shell_exe_candidates,
    _resolve_grafiks_shell_exe,
    _unique_existing_order,
)
from sg_preflight.dashboard_pages_config import (
    _int_payload_value,
    _screenshot_empty_note,
    _reader_page,
    _delivery_checklist_page,
    _delivery_readiness_payload,
    _delivery_readiness_page,
    _disabled_tests_payload,
    _disabled_tests_page,
    _api_version_coverage_payload,
    _api_version_coverage_page,
    _country_variant_coverage_payload,
    _country_variant_coverage_page,
    _export_size_trend_payload,
    _export_size_trend_page,
    _setup_doctor_payload,
    _setup_doctor_page,
    _qa_workflows_payload,
    _qa_workflows_page,
    _bmw_process_payload,
    _bmw_process_page,
    _onboarding_guide_page,
    _screenshot_test_state_page,
    _risk_score_page,
    _cross_car_comparison_page,
    _payload_items,
    _sanitized_payload,
    _section_count,
    _daily_digest_has_partial_signal,
    _daily_digest_page,
    _deferred_daily_digest_page,
    _team_digest_board_page,
    _deferred_team_digest_board_page,
    _operator_handoff_page,
)
from sg_preflight.dashboard_pages_workflows import (
    _TRUTHY_TRIGGERS,
    _full_qa_pass_page,
    _batch_full_qa_pass_page,
    _my_tickets_page,
    _is_truthy_trigger,
    FULL_QA_PASS_DEDUP_WINDOW_SECONDS,
    _full_qa_pass_dedup_lock,
    _full_qa_pass_dedup_tokens,
    FULL_QA_PASS_DEDUP_BUCKET_SECONDS,
    _full_qa_pass_token,
    _full_qa_pass_dedup_key,
    _should_fire_full_qa_pass,
    _reset_full_qa_pass_dedup,
    _publish_live_state,
    _snapshot_with_full_qa_payload,
    _screenshot_review_viewer_output_root,
    _missing_actual_diagnostics_output_root,
    _screenshot_review_viewer_url,
    _materialize_screenshot_review_viewer_for_dashboard,
    _notify_completion_safe,
    _full_qa_completion_notification,
    DAILY_DIGEST_BUILD_PACKAGE_ACTION_ID,
    DAILY_DIGEST_BUILD_PACKAGE_ACTION_LABEL,
    QUALITY_HERO_REPORT_ACTION_ID,
    QUALITY_HERO_REPORT_ACTION_LABEL,
    QUALITY_HERO_REPORT_ATTACH_ACTION_LABEL,
    DAILY_DIGEST_TICKET_ID_PLACEHOLDER,
    _DAILY_DIGEST_PARTIAL_SECTION_KEYS,
    _manual_review_profile_token,
    _manual_review_dashboard_session_id,
    _load_manual_review_dashboard_session,
    _ensure_manual_review_dashboard_session,
    _manual_review_step_recorded,
    _manual_review_step_detail,
    _manual_review_page,
    _BUILD_PACKAGE_TIMEOUT_SECONDS,
    _BUILD_PACKAGE_STDOUT_TAIL_LINES,
    _BUILD_PACKAGE_STDOUT_TAIL_BYTES,
    _BUILD_PACKAGE_FILE_ACTIVITY_LIMIT,
    _BUILD_PACKAGE_TYPICAL_RANGE_LABEL,
    _QUALITY_HERO_REPORT_TIMEOUT_SECONDS,
    _BATCH_FULL_QA_TIMEOUT_SECONDS,
    _BATCH_FULL_QA_TYPICAL_RANGE_LABEL,
    ReviewPackageBuildJob,
    BatchFullQaPassJob,
    _validate_review_package_inputs,
    _dashboard_review_package_command,
    _build_tail_text,
    _build_tail_lines,
    _build_combined_tail_lines,
    _size_label,
    _build_package_file_activity,
    _elapsed_label,
    _dashboard_full_qa_pass_command,
    _batch_profile_safe_name,
    _read_json_payload,
    _batch_step_payload,
    _batch_profile_result,
    _batch_progress_payload,
    _complete_batch_full_qa_pass,
    _start_batch_profile_process,
    start_dashboard_batch_full_qa_pass,
    request_cancel_dashboard_batch_full_qa_pass,
    poll_dashboard_batch_full_qa_pass,
    _review_build_progress_payload,
    _complete_review_package_build,
    start_dashboard_review_package_build,
    poll_dashboard_review_package_build,
    cancel_dashboard_review_package_build,
    build_dashboard_review_package,
    _quality_hero_report_output_root,
    _dashboard_quality_hero_report_command,
    _dashboard_jira_attachment_endpoint,
    _attachment_response_url,
    _attachment_response_id,
    build_dashboard_quality_hero_report,
    _render_action_visuals,
    _render_action_technical_details,
    _FULL_QA_DRAFT_STEP_IDS,
    _full_qa_int,
    _full_qa_step_payload,
    _full_qa_step_map,
    _full_qa_step_status,
    _full_qa_screenshot_counts,
    _full_qa_risk_draft,
    _full_qa_manual_review_draft,
    _full_qa_handoff_draft,
    _full_qa_bulk_ack_drafts,
    _render_daily_digest_panel,
    _render_operator_handoff_panel,
    _render_manual_review_panel,
    _my_ticket_status_draft,
    _build_my_tickets_payload,
    _render_my_tickets_panel,
    _render_batch_full_qa_pass_panel,
    _render_full_qa_pass_panel,
)


DASHBOARD_TITLE = "Seriengrafik: Project Quality-Hero"
DASHBOARD_BRAND_LOGO_ASSET = "logo_sgfx.png"
DASHBOARD_BRAND_ICON_ASSET = "sgfx_icon.png"
DASHBOARD_DEBUG_ICON_ASSET = "debug_icon.png"
_DASHBOARD_WEBSERVER_SOURCE_GUARD = {"reconnect_timeout": 30.0}
# NiceGUI run kwargs live in dashboard_webserver.py; keep the visible guard
# phrase here because slow page handlers / jitter don't trigger reconnect storms.
# The moved runner still wires the app icon through kwargs["favicon"].
# Preference persistence moved to dashboard_preferences.py; it still stores desktop_notifications_enabled.
# Preference routing still reads feedback_email; wizard resumes still use .wizard_state.json.
_DASHBOARD_RESPONSIVENESS_SOURCE_GUARD = (
    "from nicegui import background_tasks, run as nicegui_run",
    "await nicegui_run.io_bound(",
    "async def _index(profile: str = \"\", full_qa_run: str = \"\", automatic_mode: str = \"1\")",
    "def _index(profile: str = \"\", full_qa_run: str = \"\", automatic_mode: str = \"1\")",
    "Refreshing dashboard data off the UI event loop.",
)
_DASHBOARD_WORKFLOW_SOURCE_GUARD = (
    "Build Quality-Hero report", "HTML report", "Attach to Jira ticket", "Ticket picker", "Post to Jira?",
    "--attach-ticket", "--auto-confirm", "sgfx-wizard-card", "sgfx-wizard-overlay",
    "Confirm local tool action", "Skip current", "Full QA Pass summary", "full_qa_run", "automatic_mode",
    "sgfx-html-action-button", "ui.checkbox(", '"Automatic mode",',
    'value=bool(initial_payload.get("trusted_tool_mode", True))', "sgfx-automatic-mode-control",
    "Desktop notifications", "Save notification setting", "desktop_notifications_enabled", "Changed since last run",
    "Run Full QA Pass on all", "detect_changed_profiles_since_last_run", "record_full_qa_run_history",
    "batch_profile_prefill", "LONG_RUNNING_NOTIFICATION_SECONDS", "_full_qa_completion_notification",
    '"full_qa_notified": False', "sgfx-wizard-empty", "full_qa_notification = None",
    "_schedule_full_qa_notification", "has_socket_connection", "_reset_wizard_run_state",
    "Resume Full QA Pass for", "interrupted", 'wizard_state["auto_started"].add(running_action_id)',
    ".wizard_state.json", "Start the local evidence chain for the selected profile.",
    "_snapshot_with_full_qa_payload(snapshot, payload)", "Manual mode opt-out", "trusted_tool_mode_note",
    "View doc", "sgfx-live-visuals", "Diff thumbnails", "Side-by-side diff rows",
    "sgfx-diff-triplet-sticky-header", "sgfx-diff-sticky-label", "compute_diff_delta_badge",
    "compute_diff_regression_badge", "sgfx-delta-badge", "sgfx-regression-badge",
    ".sgfx-side-by-side-preview { max-height:", "padding: 0", "position: sticky",
    "Show technical details", "SGFX output:", "Elapsed", "Typical", "Steps with diffs requiring review",
    "_handle_action_completed", "Workbook preview", "black offscreen-rendering window", "record_operator_handoff",
    "start_delivery_workbook_generation", "start_screenshot_capture", "Cancel running action",
    "Manual-review state still has", "incomplete_but_queued_for_acknowledge", "acknowledged_via_bulk_confirm",
    "confirmed_via_bulk_with_tool_draft", "operator_overrode_draft", "confirmed_via_bulk_without_review",
    "Acknowledgment items queued", "Confirm All", "High-risk draft requires a second confirmation.",
    "original draft preserved", "bulk_ack_queued", "bulk_acknowledged", "bulk_ack_drafts", "bulk_ack_values",
    "_bulk_handoff_placeholder", "_full_qa_bulk_ack_drafts", "_full_qa_display_status",
    'str(step.get("id", "")) == "screenshot-test-state"', "expected > 0 and actual == 0 and diff == 0",
    'action=f"skip:{step_id}", outcome="ok"', "Action running", "cancel first to navigate",
    "sgfx-wizard-nav-blocked", "button.visible = not is_running", "Starting local subprocess; waiting for stdout/stderr",
    "_action_output_text", "MISSING_ACTUAL_DIAGNOSTIC_ACTION_ID", 'if kind == "diagnostic_chain":',
    "_run_diagnostic_chain_action", "missing_actual_diagnostics", "Run read-refresh and retry",
    "Confirm read-refresh and retry", "operator_confirmed_read_refresh=True",
    "operator_confirmed_retry_capture=retry_capture", 'threading.Thread(target=_worker, name="sgfx-missing-actual-diagnostics"',
    "_render_action_visuals", "def _notify_ui(message: str) -> None:", "if not _ignorable_nicegui_runtime_error(exc)",
    "set_running_controls: Callable[[bool], None]", "set_running_controls=set_running_controls",
    '"launch_timer": None', "Canceled before local subprocess started.",
    "lambda _event=None, current=action: _show_prompt_or_start(current)",
    "lambda _event=None, current=action: _confirm_start(current)", 'data-sgfx-my-tickets-page="true"',
    "Editable status draft", "Copy status draft", "No Jira post is sent", "Run selected profiles",
    "Cancel after current", "Sequential execution", "Live package output", "Build review package running.",
    "typical 1-5 min", "start_dashboard_review_package_build", "poll_dashboard_review_package_build",
    "cancel_dashboard_review_package_build", "def _scroll_live_output_to_bottom() -> None:",
    "_run_javascript_if_client_alive(\n                ui,",
)
_DASHBOARD_CONFIG_SOURCE_GUARD = """
def _delivery_checklist_page(...):
    read_delivery_checklist(
        bmw_root=bmw_root,
        enable_auto_generate=True,
    )

def _risk_score_page(...):
    from sg_preflight.risk_sparkline import
    page["risk_sparkline"]
"""
VERBOSE_TOOLTIP_ENV = "SGFX_DASHBOARD_VERBOSE_TOOLTIPS"
FIRST_LAUNCH_DISMISS_STORAGE_KEY = "sgfx.firstLaunch.dismissed"
FEEDBACK_EMAIL_ENV = "SGFX_FEEDBACK_EMAIL"
DEFAULT_FEEDBACK_EMAIL = "david-erik.garcia-arenas@paradoxcat.com"
DESKTOP_NOTIFICATIONS_ENV = "SGFX_DESKTOP_NOTIFICATIONS"
LONG_RUNNING_NOTIFICATION_SECONDS = 30
CANONICAL_SOURCE_REPO_ROOT = Path(r"C:\repositories\trunk")
DASHBOARD_GUARDRAILS = (
    "Manual review remains required.",
    "Decision: not approval — evidence only.",
    "BMW Git access is read-only. SGFX never modifies BMW source.",
    "Activity log is local-only — never posted to Jira, SVN, or BMW Git.",
)
DASHBOARD_NAVIGATION = (
    ("full-qa-pass", "Full QA Pass"),
    ("batch-full-qa-pass", "Batch Full QA Pass"),
    ("my-tickets", "My Tickets"),
    ("delivery-checklist", "Delivery Checklist"),
    ("delivery-readiness", "Delivery Readiness"),
    ("disabled-tests", "Disabled Tests"),
    ("api-version-coverage", "API Version"),
    ("country-variant-coverage", "Country Variants"),
    ("export-size-trend", "Size Trend"),
    ("onboarding-guide", "Onboarding Guide"),
    ("setup-doctor", "Setup Doctor"),
    ("qa-workflows", "QA Workflows"),
    ("bmw-process", "BMW Process"),
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


def _start_background_poll_timer(interval: float, callback: Callable[[], None]) -> Any:
    from nicegui.timer import Timer

    return Timer(interval, callback, active=True, immediate=False)


def _start_io_bound_poll_timer(
    interval: float,
    poll_fn: Callable[[], Any],
    apply_fn: Callable[[Any], None],
    error_fn: Callable[[Exception], None] | None = None,
) -> Any:
    from nicegui import run as nicegui_run
    from nicegui.timer import Timer

    async def _tick() -> None:
        try:
            result = await nicegui_run.io_bound(poll_fn)
        except Exception as exc:  # noqa: BLE001
            if error_fn is not None:
                error_fn(exc)
                return
            raise
        apply_fn(result)

    return Timer(interval, _tick, active=True, immediate=False)


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


def _dashboard_run_port(*, native: bool, port: int) -> int:
    if native or port:
        return port
    return _find_open_dashboard_port()


def run_grafiks_mode(
    *,
    profile_id: str = "",
    workspace: Path | str,
    bmw_root: Path | str | None = None,
) -> int:
    return _dashboard_grafiks.run_grafiks_mode(
        profile_id=profile_id,
        workspace=workspace,
        bmw_root=bmw_root,
        resolve_shell_exe=_resolve_grafiks_shell_exe,
        not_installed_message=_grafiks_not_installed_message,
    )


def _daily_digest_ticket_context(workspace: Path | str) -> dict[str, Any]:
    return _daily_digest_ticket_context_impl(
        workspace,
        ticket_id_placeholder=DAILY_DIGEST_TICKET_ID_PLACEHOLDER,
        ticket_from_operator_state=_dashboard_ticket_from_operator_state,
        ticket_from_git_branch=_dashboard_ticket_from_git_branch,
    )


def _dashboard_active_ticket_id(workspace: Path | str) -> str:
    return _dashboard_active_ticket_id_impl(
        workspace,
        fallback_ticket_id=_DASHBOARD_TICKET_FALLBACK,
        ticket_from_operator_state=_dashboard_ticket_from_operator_state,
        ticket_from_git_branch=_dashboard_ticket_from_git_branch,
    )


SCREENSHOT_TEST_STATE_OWNERSHIP_NOTE = (
    "Screenshot capture runs from the lane-correct BMW Git pipeline script after confirmation; SGFX reads the output as evidence."
)


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
            "setup_page_id": "setup-doctor",
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
            _my_tickets_page(resolved_profile_id, root),
            _delivery_checklist_page(resolved_profile_id, root, bmw_root=bmw_root, setup_status=setup_status),
            _delivery_readiness_page(root, bmw_root=bmw_root),
            _disabled_tests_page(root, bmw_root=bmw_root),
            _api_version_coverage_page(root, bmw_root=bmw_root),
            _country_variant_coverage_page(root, bmw_root=bmw_root),
            _export_size_trend_page(root, bmw_root=bmw_root),
            _onboarding_guide_page(
                resolved_profile_id,
                root,
                bmw_root=bmw_root,
                setup_status=setup_status,
            ),
            _setup_doctor_page(root),
            _qa_workflows_page(root),
            _bmw_process_page(),
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
            ui.button(
                "Copy doc link",
                on_click=lambda url=url, anchor=anchor: _copy_dashboard_link_to_clipboard(ui, url, anchor),
            ).props("flat dense no-caps").classes("sgfx-doc-link")
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
            current=delta_badge,
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


def _render_page_confluence_anchors(ui: Any, page: dict[str, Any]) -> None:
    for anchor in _page_confluence_anchors(page):
        _render_confluence_anchor(ui, anchor)


def _dashboard_verbose_tooltips_enabled() -> bool:
    value = os.environ.get(VERBOSE_TOOLTIP_ENV, "").strip().casefold()
    return value not in {"0", "false", "no", "off"}


def _attach_tooltip(ui: Any, element: Any, text: str) -> Any:
    if not text.strip() or not _dashboard_verbose_tooltips_enabled():
        return element
    with element:
        ui.tooltip(text).props("delay=900").classes("sgfx-thinking-tooltip")
    return element


def _render_reader_rows(ui: Any, rows: list[dict[str, str]]) -> None:
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


def _reader_rows_from_payload(payload: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "label": str(item.get("label", "")),
            "status": str(item.get("status", "")),
            "detail": str(item.get("detail", "")),
        }
        for item in _payload_items(payload)
        if isinstance(item, dict)
    ]


def _render_source_root_reader_panel(
    ui: Any,
    page: dict[str, Any],
    workspace: Path,
    *,
    bmw_root: Path | str | None = None,
    payload_builder: Callable[..., dict[str, Any]],
) -> None:
    payload = page.get("payload", {}) if isinstance(page.get("payload"), dict) else {}
    selector = page.get("source_selector", {}) if isinstance(page.get("source_selector"), dict) else {}
    selected_source = str(selector.get("selected_source_root") or payload.get("selected_source_root") or "")
    source_candidates = [
        str(candidate)
        for candidate in selector.get("source_root_candidates", payload.get("source_root_candidates", []))
        if str(candidate).strip()
    ]
    with _attach_tooltip(
        ui,
        ui.column().classes("sgfx-page-panel"),
        "Read-only evidence card for the selected local SVN checkout.",
    ):
        with ui.row().classes("items-center justify-between full-width"):
            ui.label(str(page["title"])).classes("sgfx-panel-title")
            _render_status_chip(ui, str(page.get("status", "unknown")))
        ui.label(str(page["tagline"])).classes("sgfx-panel-tagline")
        _render_page_confluence_anchors(ui, page)
        ownership_note = str(page.get("ownership_note", "")).strip()
        if ownership_note:
            ui.label(ownership_note).classes("sgfx-muted sgfx-ownership-note")
        summary_label = ui.label(str(page.get("summary", ""))).classes("sgfx-summary")
        _render_empty_state_note(ui, page)
        source_input = ui.input(label="SVN trunk root", value=selected_source).classes("full-width")
        source_status = ui.label(f"Reading from: {selected_source or 'auto-discovery'}").classes("sgfx-muted")
        rows_host = ui.column().classes("full-width")
        reload_buttons: list[Any] = []

        def _render_payload_rows(next_payload: dict[str, Any]) -> None:
            rows_host.clear()
            with rows_host:
                _render_reader_rows(ui, _reader_rows_from_payload(next_payload))

        async def _reload() -> None:
            from nicegui import run as nicegui_run

            for button in reload_buttons:
                try:
                    button.disable()
                except Exception:
                    pass
            source_status.text = f"Refreshing from: {source_input.value or 'auto-discovery'}"
            rows_host.clear()
            with rows_host:
                ui.linear_progress(value=0).props("indeterminate").classes("full-width")
                ui.label("Reloading source evidence off the UI event loop...").classes("sgfx-muted")
            try:
                next_payload = await nicegui_run.io_bound(
                    payload_builder,
                    workspace,
                    bmw_root,
                    repo_root=_source_repo_root_from_value(source_input.value),
                )
            except Exception as exc:  # noqa: BLE001
                summary_label.text = f"{page['title']} could not be read: {exc}"
                source_status.text = "Reading from: unavailable"
                rows_host.clear()
                with rows_host:
                    ui.label("No rows loaded for this page.").classes("sgfx-muted")
                return
            finally:
                for button in reload_buttons:
                    try:
                        button.enable()
                    except Exception:
                        pass
            summary_label.text = _payload_summary(next_payload, str(page["title"]), workspace=workspace)
            source_status.text = f"Reading from: {next_payload.get('repo_root', source_input.value)}"
            _render_payload_rows(next_payload)
            ui.notify(f"{page['title']} refreshed.")

        async def _use_source_candidate(value: str) -> None:
            source_input.value = value
            await _reload()

        with ui.row().classes("items-center"):
            reload_button = _attach_tooltip(
                ui,
                ui.button("Reload", on_click=_reload).props("no-caps"),
                "Reload this evidence page from the selected local SVN checkout.",
            )
            reload_buttons.append(reload_button)
            for candidate in source_candidates[:4]:
                label = Path(candidate).name or candidate
                candidate_button = _attach_tooltip(
                    ui,
                    ui.button(label, on_click=lambda value=candidate: _use_source_candidate(value)).props(
                        "flat no-caps"
                    ),
                    f"Use {candidate}",
                )
                reload_buttons.append(candidate_button)
        _render_payload_rows(payload)


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
        _render_reader_rows(ui, rows)


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

            def _poll_screenshot_io() -> dict[str, Any] | None:
                job = job_state.get("job")
                if job is None:
                    return {"_sgfx_stop_poll": True}
                return poll_screenshot_capture(job)

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
                            start_screenshot_capture,
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
        # internal milestone Part C wiring: internal milestone sparkline next to the risk-score numbers so
        # the dashboard live UI surfaces the same trend signal that lands in
        # the internal milestone HTML + the internal milestone-extended risk-score CLI text output.
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


def _copy_dashboard_text_to_clipboard(ui: Any, text: str, label: str) -> None:
    clean_text = str(text or "").strip()
    clean_label = str(label or "text").strip()
    if not clean_text:
        try:
            ui.notify(f"No text available for {clean_label}.", position="bottom")
        except Exception:
            pass
        return
    try:
        ui.run_javascript(
            """
            (async () => {
              const text = __SGFX_COPY_TEXT__;
              const label = __SGFX_COPY_LABEL__;
              const notify = (message, color) => {
                if (window.Quasar && window.Quasar.Notify && typeof window.Quasar.Notify.create === 'function') {
                  window.Quasar.Notify.create({ message, position: 'bottom', color, timeout: 4500 });
                } else {
                  console.log(message);
                }
              };
              const fallbackCopy = () => {
                const textarea = document.createElement('textarea');
                textarea.value = text;
                textarea.setAttribute('readonly', '');
                textarea.style.position = 'fixed';
                textarea.style.left = '-9999px';
                textarea.style.top = '0';
                document.body.appendChild(textarea);
                textarea.focus();
                textarea.select();
                let copied = false;
                try {
                  copied = document.execCommand('copy');
                } finally {
                  document.body.removeChild(textarea);
                }
                return copied;
              };
              let copied = false;
              let lastError = null;
              try {
                if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
                  await navigator.clipboard.writeText(text);
                  copied = true;
                }
              } catch (err) {
                lastError = err;
                console.warn('navigator.clipboard.writeText failed', err);
              }
              if (!copied) {
                try {
                  copied = fallbackCopy();
                } catch (err) {
                  lastError = err;
                  console.warn('document.execCommand copy fallback failed', err);
                }
              }
              if (copied) {
                notify(`Copied to clipboard: ${label}`, 'positive');
              } else {
                console.warn('clipboard copy failed', lastError);
                notify(`Couldn't copy automatically. Text: ${text}`, 'warning');
              }
            })();
            """.replace("__SGFX_COPY_TEXT__", json.dumps(clean_text)).replace(
                "__SGFX_COPY_LABEL__", json.dumps(clean_label)
            )
        )
    except Exception:
        try:
            ui.notify(f"Couldn't start clipboard copy. Text: {clean_text}", position="bottom")
        except Exception:
            pass


def _copy_dashboard_link_to_clipboard(ui: Any, url: str, label: str) -> None:
    clean_url = str(url or "").strip()
    clean_label = str(label or clean_url or "link").strip()
    if not clean_url:
        try:
            ui.notify(f"No URL available for {clean_label}.", position="bottom")
        except Exception:
            pass
        return
    try:
        ui.run_javascript(
            """
            (async () => {
              const text = __SGFX_COPY_TEXT__;
              const label = __SGFX_COPY_LABEL__;
              const notify = (message, color) => {
                if (window.Quasar && window.Quasar.Notify && typeof window.Quasar.Notify.create === 'function') {
                  window.Quasar.Notify.create({ message, position: 'bottom', color, timeout: 4500 });
                } else {
                  console.log(message);
                }
              };
              const fallbackCopy = () => {
                const textarea = document.createElement('textarea');
                textarea.value = text;
                textarea.setAttribute('readonly', '');
                textarea.style.position = 'fixed';
                textarea.style.left = '-9999px';
                textarea.style.top = '0';
                document.body.appendChild(textarea);
                textarea.focus();
                textarea.select();
                let copied = false;
                try {
                  copied = document.execCommand('copy');
                } finally {
                  document.body.removeChild(textarea);
                }
                return copied;
              };
              let copied = false;
              let lastError = null;
              try {
                if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
                  await navigator.clipboard.writeText(text);
                  copied = true;
                }
              } catch (err) {
                lastError = err;
                console.warn('navigator.clipboard.writeText failed', err);
              }
              if (!copied) {
                try {
                  copied = fallbackCopy();
                } catch (err) {
                  lastError = err;
                  console.warn('document.execCommand copy fallback failed', err);
                }
              }
              if (copied) {
                notify(`Copied to clipboard: ${label}`, 'positive');
              } else {
                console.warn('clipboard copy failed', lastError);
                notify(`Couldn't copy automatically. Link: ${text}`, 'warning');
              }
            })();
            """.replace("__SGFX_COPY_TEXT__", json.dumps(clean_url)).replace(
                "__SGFX_COPY_LABEL__", json.dumps(clean_label)
            )
        )
    except Exception:
        try:
            ui.notify(f"Couldn't start clipboard copy. Link: {clean_url}", position="bottom")
        except Exception:
            pass


def _render_jira_profile_tickets_card(
    ui: Any,
    profile_id: str,
    *,
    payload: dict[str, Any] | None = None,
    open_page: Callable[[str], None] | None = None,
) -> None:
    if not isinstance(payload, dict):
        payload = {
            "status": "loading",
            "ticket_count": 0,
            "tickets": [],
            "summary": "Loading active profile tickets from operator-local Jira credentials...",
            "settings_hint": "",
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
        if status == "loading":
            ui.linear_progress(value=0).props("indeterminate").classes("full-width")
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
                        ui.button(
                            key,
                            on_click=lambda url=url, key=key: _copy_dashboard_link_to_clipboard(ui, url, key),
                        ).props("flat dense no-caps").classes("sgfx-jira-ticket-key")
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
        elif page_id == "my-tickets":
            _render_my_tickets_panel(ui, snapshot, workspace)
        elif page_id == "delivery-readiness":
            _render_source_root_reader_panel(
                ui,
                pages_by_id[page_id],
                workspace,
                payload_builder=_delivery_readiness_payload,
            )
        elif page_id == "disabled-tests":
            _render_source_root_reader_panel(
                ui,
                pages_by_id[page_id],
                workspace,
                payload_builder=_disabled_tests_payload,
            )
        elif page_id == "api-version-coverage":
            _render_source_root_reader_panel(
                ui,
                pages_by_id[page_id],
                workspace,
                payload_builder=_api_version_coverage_payload,
            )
        elif page_id == "country-variant-coverage":
            _render_source_root_reader_panel(
                ui,
                pages_by_id[page_id],
                workspace,
                payload_builder=_country_variant_coverage_payload,
            )
        elif page_id == "export-size-trend":
            _render_source_root_reader_panel(
                ui,
                pages_by_id[page_id],
                workspace,
                payload_builder=_export_size_trend_payload,
            )
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
    from nicegui import background_tasks, run as nicegui_run

    async def _io_bound(callback: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        return await nicegui_run.io_bound(callback, *args, **kwargs)

    async def _build_snapshot_io(
        profile_id: str,
        *,
        ui_mode_override: str | None = None,
        defer_daily_digest: bool,
        defer_team_digest_board: bool,
    ) -> dict[str, Any]:
        return await _io_bound(
            build_dashboard_snapshot,
            profile_id,
            workspace,
            bmw_root=bmw_root,
            ui_mode=ui_mode_override if ui_mode_override is not None else ui_mode,
            defer_daily_digest=defer_daily_digest,
            defer_team_digest_board=defer_team_digest_board,
        )

    def _schedule_background(awaitable: Any, *, name: str) -> None:
        try:
            background_tasks.create(awaitable, name=name)
        except RuntimeError:
            asyncio.create_task(awaitable)

    base_snapshot = build_dashboard_snapshot(
        initial_profile_id,
        workspace,
        bmw_root=bmw_root,
        ui_mode=ui_mode,
        defer_daily_digest=True,
        defer_team_digest_board=True,
    )

    @app.get("/sgfx-dashboard-api/full-qa-pass")
    async def _full_qa_pass_api(profile: str = "", trusted_tool_mode: str = "1") -> dict[str, Any]:
        requested_profile = str(profile or base_snapshot.get("profile_id") or initial_profile_id).strip()
        trusted = str(trusted_tool_mode).strip().casefold() in {"1", "true", "yes", "on"}
        # internal milestone Part B: same per-profile 30s dedup as the `_index` page handler.
        # Pre-fix this JSON API was an unguarded second entry point for the same
        # build_full_qa_pass invocation; NiceGUI's WebSocket reconnect or any
        # client polling against this URL would re-fire the side effect even
        # when the internal milestone dashboard gate was holding.
        if not _should_fire_full_qa_pass(requested_profile):
            _publish_live_state(
                workspace,
                dashboard_surface="full-qa-pass:api-dedupped",
                profile_id=requested_profile,
                last_operator_action=("ran", "full-qa-pass:api"),
                last_error="Re-fire suppressed by 30s dedup window",
            )
            return {
                "status": "dedupped",
                "profile_id": requested_profile,
                "dedup_token": _full_qa_pass_token(requested_profile),
                "summary": (
                    "Full QA Pass already fired for this profile within the "
                    "30s dedup window. Manual review remains required."
                ),
                "manual_review_required": True,
                "is_approval": False,
            }
        return await _io_bound(
            build_full_qa_pass,
            requested_profile,
            workspace=workspace,
            bmw_root=bmw_root,
            trusted_tool_mode=trusted,
        )

    @ui.page("/")
    async def _index(profile: str = "", full_qa_run: str = "", automatic_mode: str = "1") -> None:
        query_profile = str(profile or "").strip()
        snapshot = (
            await _build_snapshot_io(
                query_profile,
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
            # internal milestone: dedup BEFORE firing so a NiceGUI WebSocket reconnect storm
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
            payload = await _io_bound(
                build_full_qa_pass,
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
            .sgfx-my-ticket-item { gap: 8px; border-top: 1px solid var(--sgfx-border); padding: 14px 0 16px 0; }
            .sgfx-my-ticket-header { gap: 8px; flex-wrap: wrap; }
            .sgfx-my-ticket-draft textarea { min-height: 132px; line-height: 1.45; }
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
            .sgfx-mode-toggle { gap: 4px; padding: 3px; border: 1px solid var(--sgfx-border); border-radius: 8px; background: var(--sgfx-bg-elev); }
            .sgfx-mode-button { min-height: 30px; border-radius: 6px; color: var(--sgfx-fg) !important; }
            .sgfx-mode-button-active { background: var(--sgfx-accent-soft) !important; color: var(--sgfx-accent) !important; }
            .sgfx-grafiks-dialog-card { width: min(92vw, 560px); gap: 12px; border: 1px solid var(--sgfx-warning-border); border-radius: 8px; background: var(--sgfx-bg-panel); color: var(--sgfx-fg); padding: 18px; box-shadow: 0 22px 58px rgba(0, 0, 0, 0.45); }
            .sgfx-grafiks-dialog-icon { width: 72px; height: 72px; object-fit: contain; flex: 0 0 auto; }
            .sgfx-grafiks-dialog-title { color: var(--sgfx-warning-fg); font-size: 16px; font-weight: 700; line-height: 1.35; }
            .sgfx-grafiks-dialog-body { color: var(--sgfx-fg); font-size: 13px; line-height: 1.45; }
            .sgfx-grafiks-dialog-detail { color: var(--sgfx-fg-muted); font-size: 12px; line-height: 1.4; }
            .sgfx-grafiks-dialog-actions { gap: 10px; align-items: center; justify-content: flex-end; flex-wrap: wrap; }
            #popup.nicegui-error-popup { max-width: min(88vw, 360px); margin: 14px; padding: 10px 14px 10px 34px; gap: 3px; border-color: rgba(78, 201, 176, 0.34); border-radius: 8px; background: rgba(18, 27, 31, 0.88) !important; color: var(--sgfx-fg-muted); box-shadow: 0 12px 30px rgba(0, 0, 0, 0.22); font-size: 12px; opacity: 0.9; }
            #popup.nicegui-error-popup[aria-hidden="false"] { transition-delay: 650ms; }
            #popup.nicegui-error-popup > span:first-child { color: var(--sgfx-fg); font-weight: 650; }
            #popup.nicegui-error-popup:dir(ltr) > span:first-child::before { left: 12px; font-size: 12px; }
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
        state: dict[str, Any] = {
            "snapshot": snapshot,
            "active_page_id": first_page_id,
            "dashboard_mode": "clean",
            "jira_profile_ticket_payloads": {},
            "my_tickets_loading": False,
        }
        content_holder: dict[str, Any] = {}
        controls: dict[str, Any] = {}
        feedback_context = _dashboard_feedback_context(workspace)

        def _pages_by_id() -> dict[str, dict[str, Any]]:
            return {str(page["id"]): page for page in state["snapshot"]["pages"]}

        def _current_theme() -> str:
            return str(state["snapshot"].get("theme", "clean"))

        def _set_grafiks_dialog_detail(detail: str) -> None:
            label = controls.get("grafiks_dialog_detail")
            if label is not None:
                label.set_text(detail)

        def _set_grafiks_continue_enabled(enabled: bool) -> None:
            button = controls.get("grafiks_continue_button")
            if button is None:
                return
            if enabled:
                button.props(remove="disable")
            else:
                button.props("disable")

        def _show_grafiks_confirm_dialog(detail: str, *, allow_continue: bool) -> None:
            _set_grafiks_dialog_detail(detail)
            _set_grafiks_continue_enabled(allow_continue)
            grafiks_confirm_dialog.open()

        def _set_mode_button_state(mode: str) -> None:
            state["dashboard_mode"] = mode
            for key, value in {"mode_clean": "clean", "mode_grafiks": "grafiks"}.items():
                button = controls.get(key)
                if button is None:
                    continue
                if value == mode:
                    button.classes("sgfx-mode-button-active")
                else:
                    button.classes(remove="sgfx-mode-button-active")

        def _select_clean_mode() -> None:
            _set_mode_button_state("clean")
            grafiks_confirm_dialog.close()

        def _confirm_grafiks_launch() -> None:
            shell_path = _resolve_grafiks_shell_exe(workspace)
            if shell_path is None:
                _set_mode_button_state("clean")
                _show_grafiks_confirm_dialog(_grafiks_not_installed_message(workspace), allow_continue=False)
                return
            _set_mode_button_state("grafiks")
            grafiks_confirm_dialog.close()
            exit_code = run_grafiks_mode(
                profile_id=str(state["snapshot"].get("profile_id", "")),
                workspace=workspace,
                bmw_root=bmw_root,
            )
            if exit_code:
                _show_grafiks_confirm_dialog(
                    f"Grafiks cinematic shell exited early with code {exit_code}.",
                    allow_continue=True,
                )

        def _select_grafiks_mode() -> None:
            shell_path = _resolve_grafiks_shell_exe(workspace)
            if shell_path is None:
                _set_mode_button_state("clean")
                _show_grafiks_confirm_dialog(_grafiks_not_installed_message(workspace), allow_continue=False)
                return
            _show_grafiks_confirm_dialog(
                f"Ready to launch Grafiks cinematic shell: {shell_path}",
                allow_continue=True,
            )

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

        def _jira_profile_ticket_loading_payload(profile_id: str) -> dict[str, Any]:
            return {
                "status": "loading",
                "ticket_count": 0,
                "tickets": [],
                "summary": f"Loading active Jira tickets for {profile_id}...",
                "read_only": True,
                "is_approval": False,
            }

        def _my_tickets_loading_payload() -> dict[str, Any]:
            return {
                "status": "loading",
                "ticket_count": 0,
                "tickets": [],
                "summary": "Loading active tickets and local status drafts from operator-local sources...",
                "jql": build_my_unresolved_ticket_jql(),
                "read_only": True,
                "is_approval": False,
            }

        async def _load_jira_profile_tickets_payload(profile_id: str) -> dict[str, Any]:
            cache_key = str(profile_id or "").strip().upper()
            try:
                payload = await _io_bound(search_jira_profile_tickets, cache_key, max_results=5, timeout_seconds=8)
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
            payloads = state.setdefault("jira_profile_ticket_payloads", {})
            if isinstance(payloads, dict):
                payloads[cache_key] = payload if isinstance(payload, dict) else {
                    "status": "failed",
                    "ticket_count": 0,
                    "tickets": [],
                    "summary": "Jira tickets unavailable: unexpected response.",
                    "read_only": True,
                    "is_approval": False,
                }
                return payloads[cache_key]
            return payload

        def _jira_profile_tickets_payload(profile_id: str) -> dict[str, Any]:
            clean_profile = str(profile_id or "").strip().upper()
            if not clean_profile:
                return _jira_profile_ticket_loading_payload("profile")
            payloads = state.setdefault("jira_profile_ticket_payloads", {})
            if not isinstance(payloads, dict):
                state["jira_profile_ticket_payloads"] = payloads = {}
            payload = payloads.get(clean_profile)
            if isinstance(payload, dict):
                return payload
            payload = _jira_profile_ticket_loading_payload(clean_profile)
            payloads[clean_profile] = payload
            return payload

        async def _finish_my_tickets_refresh() -> None:
            try:
                payload = await _io_bound(_build_my_tickets_payload, workspace)
            except Exception as exc:  # noqa: BLE001
                payload = {
                    "status": "failed",
                    "ticket_count": 0,
                    "tickets": [],
                    "summary": f"My Tickets unavailable: {exc}",
                    "settings_hint": "Check local Jira setup before retrying.",
                    "read_only": True,
                    "is_approval": False,
                    "jql": build_my_unresolved_ticket_jql(),
                }
            state["snapshot"]["my_tickets_payload"] = payload
            state["my_tickets_loading"] = False
            if str(state.get("active_page_id", "")) == "my-tickets":
                _render_current_page()

        def _start_my_tickets_refresh(*, force: bool = False) -> None:
            if bool(state.get("my_tickets_loading", False)):
                return
            current_payload = state["snapshot"].get("my_tickets_payload")
            if isinstance(current_payload, dict) and current_payload.get("status") != "loading" and not force:
                return
            state["my_tickets_loading"] = True
            state["snapshot"]["my_tickets_payload"] = _my_tickets_loading_payload()
            _schedule_background(_finish_my_tickets_refresh(), name="sgfx-dashboard-my-tickets")

        def _render_current_page() -> None:
            content = content_holder.get("content")
            if content is None:
                return
            content.clear()
            with content:
                loading_message = str(state.get("loading_message", "") or "")
                if loading_message:
                    with ui.column().classes("sgfx-page-panel"):
                        ui.label(loading_message).classes("sgfx-panel-title")
                        ui.linear_progress(value=0).props("indeterminate").classes("full-width")
                        ui.label("Refreshing dashboard data off the UI event loop.").classes("sgfx-muted")
                    content.update()
                    _run_javascript_if_client_alive(
                        ui,
                        "window.sgfxApplyFirstLaunchState && window.sgfxApplyFirstLaunchState();",
                    )
                    return
                warning = str(state["snapshot"].get("profile_warning", "") or "")
                if warning:
                    ui.label(warning).classes("sgfx-warning")
                active_page_id = str(state["active_page_id"])
                _render_first_run_welcome(
                    ui,
                    state["snapshot"],
                    open_setup=lambda: _open_page("setup-doctor"),
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
                elif active_page_id == "delivery-readiness":
                    _render_source_root_reader_panel(
                        ui,
                        _pages_by_id()[active_page_id],
                        workspace,
                        bmw_root=bmw_root,
                        payload_builder=_delivery_readiness_payload,
                    )
                elif active_page_id == "disabled-tests":
                    _render_source_root_reader_panel(
                        ui,
                        _pages_by_id()[active_page_id],
                        workspace,
                        bmw_root=bmw_root,
                        payload_builder=_disabled_tests_payload,
                    )
                elif active_page_id == "api-version-coverage":
                    _render_source_root_reader_panel(
                        ui,
                        _pages_by_id()[active_page_id],
                        workspace,
                        bmw_root=bmw_root,
                        payload_builder=_api_version_coverage_payload,
                    )
                elif active_page_id == "country-variant-coverage":
                    _render_source_root_reader_panel(
                        ui,
                        _pages_by_id()[active_page_id],
                        workspace,
                        bmw_root=bmw_root,
                        payload_builder=_country_variant_coverage_payload,
                    )
                elif active_page_id == "export-size-trend":
                    _render_source_root_reader_panel(
                        ui,
                        _pages_by_id()[active_page_id],
                        workspace,
                        bmw_root=bmw_root,
                        payload_builder=_export_size_trend_payload,
                    )
                elif active_page_id == "full-qa-pass":
                    _render_full_qa_pass_panel(
                        ui,
                        state["snapshot"],
                        workspace,
                        bmw_root=bmw_root,
                        open_page=_open_page,
                        jira_profile_tickets_payload=_jira_profile_tickets_payload(
                            str(state["snapshot"].get("profile_id", ""))
                        ),
                        jira_profile_tickets_loader=_load_jira_profile_tickets_payload,
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
                elif active_page_id == "my-tickets":
                    _start_my_tickets_refresh()
                    _render_my_tickets_panel(ui, state["snapshot"], workspace)
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

        async def _finish_snapshot_refresh(
            *,
            profile_id: str,
            active_page_id: str,
            defer_daily_digest: bool,
            defer_team_digest_board: bool,
            transition_page_id: str = "",
            notify_message: str = "",
        ) -> None:
            try:
                snapshot = await _build_snapshot_io(
                    profile_id,
                    ui_mode_override=_current_theme(),
                    defer_daily_digest=defer_daily_digest,
                    defer_team_digest_board=defer_team_digest_board,
                )
            except Exception as exc:  # noqa: BLE001
                state["loading_message"] = ""
                _render_current_page()
                ui.notify(f"Dashboard refresh failed: {exc}")
                return
            state["snapshot"] = snapshot
            state["loading_message"] = ""
            if active_page_id == "my-tickets":
                _start_my_tickets_refresh(force=True)
            _refresh_labels()
            if str(state.get("active_page_id", "")) == active_page_id:
                _render_current_page()
            if notify_message:
                ui.notify(notify_message)

        def _start_snapshot_refresh(
            *,
            profile_id: str,
            active_page_id: str,
            defer_daily_digest: bool,
            defer_team_digest_board: bool,
            loading_message: str,
            transition_page_id: str = "",
            notify_message: str = "",
        ) -> None:
            _dashboard_changed_profiles.cache_clear()
            state["loading_message"] = loading_message
            _render_current_page()
            if transition_page_id:
                _run_javascript_if_client_alive(
                    ui,
                    f"window.sgfxFinishTransition && window.sgfxFinishTransition('tab', {json.dumps(transition_page_id)});",
                )
            _schedule_background(
                _finish_snapshot_refresh(
                    profile_id=profile_id,
                    active_page_id=active_page_id,
                    defer_daily_digest=defer_daily_digest,
                    defer_team_digest_board=defer_team_digest_board,
                    transition_page_id=transition_page_id,
                    notify_message=notify_message,
                ),
                name="sgfx-dashboard-snapshot-refresh",
            )

        def _open_page(page_id: str) -> None:
            state["active_page_id"] = page_id
            _run_javascript_if_client_alive(ui, f"document.body.dataset.sgfxActivePage = {json.dumps(page_id)};")
            _run_javascript_if_client_alive(ui, "window.sgfxSetSidebarOpen && window.sgfxSetSidebarOpen(false);")
            if page_id in {"daily-digest", "team-digest-board"} and _pages_by_id().get(page_id, {}).get("deferred"):
                _start_snapshot_refresh(
                    profile_id=str(state["snapshot"]["profile_id"]),
                    active_page_id=page_id,
                    defer_daily_digest=page_id != "daily-digest",
                    defer_team_digest_board=page_id != "team-digest-board",
                    loading_message=f"Loading {str(_pages_by_id().get(page_id, {}).get('title', page_id))}...",
                    transition_page_id=page_id,
                )
                return
            if page_id == "my-tickets" and _pages_by_id().get(page_id, {}).get("deferred"):
                state["loading_message"] = ""
                _start_my_tickets_refresh(force=True)
                _render_current_page()
                _run_javascript_if_client_alive(
                    ui,
                    f"window.sgfxFinishTransition && window.sgfxFinishTransition('tab', {json.dumps(page_id)});",
                )
                return
            state["loading_message"] = ""
            _render_current_page()
            _run_javascript_if_client_alive(
                ui,
                f"window.sgfxFinishTransition && window.sgfxFinishTransition('tab', {json.dumps(page_id)});",
            )

        def _refresh_snapshot(profile_id: str | None = None, *, notify_message: str = "") -> None:
            current_profile = profile_id if profile_id is not None else str(state["snapshot"]["profile_id"])
            active_page_id = str(state.get("active_page_id", "delivery-checklist"))
            _start_snapshot_refresh(
                profile_id=current_profile,
                active_page_id=active_page_id,
                defer_daily_digest=active_page_id != "daily-digest",
                defer_team_digest_board=active_page_id != "team-digest-board",
                loading_message="Refreshing dashboard data...",
                notify_message=notify_message,
            )

        def _refresh_current_page() -> None:
            _refresh_snapshot(notify_message="Current page refreshed from read-only sources.")

        def _set_profile(value: str) -> None:
            profile_id = _profile_id_from_select_value(value)
            if profile_id:
                _write_dashboard_profile_preference(workspace, profile_id)
            _refresh_snapshot(profile_id, notify_message=f"Profile switched to {profile_id or state['snapshot']['profile_id']}.")

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
                    window.sgfxBuildFeedbackBody = () => {{
                        const profile = document.body.dataset.sgfxProfileId || {json.dumps(str(snapshot.get("profile_id", "")))};
                        const page = document.body.dataset.sgfxActivePage || 'unknown';
                        const subject = `${{feedbackContext.subject_prefix || 'SGFX feedback'}} — ${{profile}} — ${{feedbackContext.build_sha || 'unknown'}}`;
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
                        return {{ subject, body }};
                    }};
                    window.sgfxBuildFeedbackMailto = () => {{
                        const composed = window.sgfxBuildFeedbackBody();
                        return `mailto:${{feedbackContext.to || ''}}?subject=${{encodeURIComponent(composed.subject)}}&body=${{encodeURIComponent(composed.body)}}`;
                    }};
                    window.sgfxBuildFeedbackTeams = () => {{
                        // internal milestone: Microsoft Teams native deep-link. Opens a 1:1 chat with
                        // the configured recipient + a pre-filled message. Body length
                        // capped at ~1800 chars per Teams URL practicality limits with
                        // an explicit "continue in Teams" suffix.
                        const composed = window.sgfxBuildFeedbackBody();
                        let messageBody = `${{composed.subject}}\\r\\n\\r\\n${{composed.body}}`;
                        const cap = 1800;
                        if (messageBody.length > cap) {{
                            messageBody = messageBody.slice(0, cap) + '\\r\\n…continue in Teams';
                        }}
                        const recipient = feedbackContext.teams_recipient || feedbackContext.to || '';
                        return `msteams://l/chat/0/0?users=${{encodeURIComponent(recipient)}}&message=${{encodeURIComponent(messageBody)}}`;
                    }};
                    window.sgfxOpenFeedback = () => {{
                        window.location.href = window.sgfxBuildFeedbackMailto();
                    }};
                    window.sgfxOpenFeedbackTeams = async () => {{
                        // Try to open Teams deep-link via a transient anchor so the
                        // browser surfaces the protocol prompt instead of just leaving
                        // a flicker. If the protocol handler is not registered (Teams
                        // not installed, browser blocked), the email button next to
                        // this one still works.
                        const url = window.sgfxBuildFeedbackTeams();
                        const link = document.createElement('a');
                        link.href = url;
                        link.rel = 'noopener noreferrer';
                        link.style.display = 'none';
                        document.body.appendChild(link);
                        link.click();
                        setTimeout(() => link.remove(), 100);
                        // internal milestone Part B: clipboard fallback so the operator's
                        // prefilled message is never lost even if Teams doesn't
                        // open (msteams:// protocol handler unregistered, browser
                        // blocking schemes, packaged exe restrictions, etc.).
                        try {{
                            const composed = window.sgfxBuildFeedbackBody();
                            const fullMessage = composed.subject + '\\r\\n\\r\\n' + composed.body;
                            await navigator.clipboard.writeText(fullMessage);
                            window.sgfxNotifyFeedbackToast && window.sgfxNotifyFeedbackToast(
                                'Teams should open; message also copied to clipboard.'
                            );
                        }} catch (err) {{
                            console.warn('Teams clipboard fallback failed', err);
                        }}
                    }};
                    window.sgfxNotifyFeedbackToast = (message) => {{
                        // Lightweight inline toast — no NiceGUI dependency so the
                        // feedback JS can fire even when the NiceGUI WebSocket is
                        // not connected (operator on a stale tab).
                        const existing = document.getElementById('sgfxFeedbackToast');
                        if (existing) existing.remove();
                        const toast = document.createElement('div');
                        toast.id = 'sgfxFeedbackToast';
                        toast.textContent = message;
                        toast.style.cssText = (
                            'position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%); ' +
                            'background: #252526; color: #d4d4d4; border: 1px solid #3c3c3c; ' +
                            'border-radius: 6px; padding: 8px 14px; font-size: 12px; z-index: 9999; ' +
                            'box-shadow: 0 4px 12px rgba(0,0,0,0.4); pointer-events: none;'
                        );
                        document.body.appendChild(toast);
                        setTimeout(() => toast.remove(), 3500);
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

        with ui.dialog() as grafiks_confirm_dialog:
            with ui.card().classes("sgfx-grafiks-dialog-card").props('data-sgfx-grafiks-dialog="true"'):
                with ui.row().classes("items-start no-wrap"):
                    ui.image(f"/sgfx-dashboard-assets/{DASHBOARD_DEBUG_ICON_ASSET}").classes(
                        "sgfx-grafiks-dialog-icon"
                    )
                    with ui.column().classes("gap-1"):
                        ui.label(GRAFIKS_MODE_WARNING_TITLE).classes("sgfx-grafiks-dialog-title")
                        ui.label(GRAFIKS_MODE_WARNING_BODY).classes("sgfx-grafiks-dialog-body")
                        controls["grafiks_dialog_detail"] = ui.label("").classes("sgfx-grafiks-dialog-detail")
                with ui.row().classes("sgfx-grafiks-dialog-actions full-width"):
                    controls["grafiks_continue_button"] = ui.button(
                        "Continue to Grafiks",
                        on_click=_confirm_grafiks_launch,
                    ).props("color=warning no-caps")
                    ui.button("Cancel", on_click=grafiks_confirm_dialog.close).props("flat no-caps")

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
                        with ui.row().classes("sgfx-mode-toggle items-center").props('data-sgfx-mode-toggle="true"'):
                            controls["mode_clean"] = ui.button(
                                "Clean",
                                on_click=_select_clean_mode,
                            ).props("flat dense no-caps data-sgfx-mode-toggle=clean").classes("sgfx-mode-button")
                            controls["mode_grafiks"] = ui.button(
                                "Grafiks",
                                on_click=_select_grafiks_mode,
                            ).props("flat dense no-caps data-sgfx-mode-toggle=grafiks").classes("sgfx-mode-button")
                        _set_mode_button_state("clean")
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
                                'data-sgfx-feedback-channel="email" '
                                'onclick="window.sgfxOpenFeedback && window.sgfxOpenFeedback()">'
                                "Open email</button>",
                                sanitize=False,
                            ),
                            "Open a prefilled email draft. Nothing is sent until the operator reviews it.",
                        )
                        # internal milestone: Teams direct-message option. msteams:// deep-link opens
                        # the Teams app to a 1:1 chat with the configured recipient
                        # plus a pre-filled message. Falls back gracefully to the
                        # email button next to it if Teams isn't installed.
                        _attach_tooltip(
                            ui,
                            ui.html(
                                '<button type="button" class="sgfx-feedback-button" '
                                'data-sgfx-feedback-button="true" '
                                'data-sgfx-feedback-channel="teams" '
                                'onclick="window.sgfxOpenFeedbackTeams && window.sgfxOpenFeedbackTeams()">'
                                "Open Teams</button>",
                                sanitize=False,
                            ),
                            "Open a Teams chat with the prefilled message. Falls back to email if Teams is not installed.",
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
