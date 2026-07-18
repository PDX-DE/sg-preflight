"""NiceGUI operator dashboard: assembles the page snapshot and serves it.

Owns the `ui.page` / `app.get` routes (the `/` index and the
`/sgfx-dashboard-api/full-qa-pass` JSON endpoint), the app-shell renderer
(`_render_dashboard`, `_render_selected_page`), and the native-window/browser
launch entry point `run_dashboard`. Everything this module used to define
directly now lives in cohesive siblings and is re-exported here explicitly so
`sg_preflight.dashboard.main` keeps resolving every name (and every mock.patch
target) it always has.

`dashboard/load_tokens.py` owns `DashboardLoadToken` and the poll-timer /
NiceGUI-runtime-error plumbing used while a page or snapshot is loading.

`dashboard/manual_review_state.py` owns the manual-review dashboard state
file path plus the save/record helpers.

`dashboard/snapshot.py` owns `build_dashboard_snapshot`, `build_dashboard_page`,
the navigation/page-builder registry, and the ticket-context helpers that feed
the snapshot's welcome/guardrail payload.

`dashboard/panels_common.py` owns the shared page-panel rendering helpers
(status tone/chip, Confluence anchor rendering, tooltip attachment, the
generic reader-row/page-panel renderer, the source-root reader panel,
first-run/about/changed-profiles cards, and the clipboard-copy JS builders).

`dashboard/panels_setup_delivery.py`, `dashboard/panels_screenshots.py`, and
`dashboard/panels_scoring.py` own the dependency-setup, delivery-checklist,
screenshot-test-state, risk-score, cross-car-comparison, and team-digest-board
page panels.

`dashboard_pages_config.py` owns the payload builders for the read-only report
pages: delivery checklist, disabled tests, API/country-variant coverage,
export-size trend, setup doctor, QA workflows, BMW process, home/onboarding,
screenshot test state, risk score, cross-car comparison, daily digest, team
digest board, and operator handoff.

`dashboard_pages_workflows.py` owns the stateful, operator-triggered
workflows — Full QA Pass, Batch Full QA Pass, the manual review wizard,
review-package build, and Quality-Hero report generation — including their
dedup/background-job machinery and the panel renderers for those workflow
pages. The daily digest and operator handoff panels also render from there,
since those panels host workflow actions rather than just displaying data.
"""

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
from sg_preflight.qa_pass_report import (
    build_qa_pass_report_summary,
    default_qa_pass_report_zip_path,
    export_qa_pass_report_zip,
    write_qa_pass_report_html,
)
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
    cancel_screenshot_capture_with_export_check,
    check_screenshot_capture_environment,
    check_screenshot_export_artifact,
    poll_screenshot_capture,
    poll_screenshot_capture_with_export_check,
    start_screenshot_capture,
    start_screenshot_capture_with_export_check,
)
from sg_preflight.services import operator_ui_root
from sg_preflight.shell_registry import (
    HOME_HUB_TILES as REGISTERED_HOME_HUB_TILES,
    HOME_ROUTE_ID,
    HOME_SUBTITLE,
    HOME_TITLE,
    NAVIGATION_GROUP_ORDER,
    SHORTCUT_ACTIONS,
)
from sg_preflight.setup_doctor import build_setup_doctor_report
from sg_preflight.subprocess_utils import hidden_subprocess_kwargs, sgfx_cli_command
from sg_preflight.surface_registry import SURFACE_DESCRIPTORS, get_surface_descriptor, is_registered_surface
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
    _run_nicegui,
    append_startup_log,
    startup_log_path,
    webview2_runtime_available,
)
from sg_preflight.dashboard_preferences import (
    _abbreviate_workspace_text,
    _candidate_git_roots,
    _clean_theme,
    _dashboard_active_ticket_id as _dashboard_active_ticket_id_impl,
    _dashboard_build_sha,
    _dashboard_exe_sha256,
    _dashboard_feedback_context,
    _dashboard_feedback_recipient,
    _dashboard_default_ticket_id,
    _dashboard_notifications_enabled,
    _dashboard_preferred_profile_id,
    _dashboard_profile_known,
    _dashboard_run_mode,
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
    CINEMATIC_RUNTIME_COMPANIONS,
    GRAFIKS_CXX_BUILD_DIR,
    GRAFIKS_DEFAULT_BMW_CARS_ROOT,
    GRAFIKS_MODE_WARNING_BODY,
    GRAFIKS_MODE_WARNING_TITLE,
    GRAFIKS_MODE_WIP_HINT,
    GRAFIKS_SHELL_EXE_ENV_KEYS,
    GRAFIKS_SHELL_EXE_NAME,
    GRAFIKS_SPAWN_FAILURE_EXIT_CODE,
    OPERATOR_CONSOLE_SHELL_EXE_NAME,
    _dashboard_source_root,
    _grafiks_bmw_cars_root,
    _grafiks_not_installed_message,
    _grafiks_profile_registry_file,
    _grafiks_shell_command,
    _grafiks_shell_exe_candidates,
    _grafiks_shell_label,
    _resolve_grafiks_shell_exe,
    _unique_existing_order,
)
from sg_preflight.dashboard_pages_config import (
    _int_payload_value,
    _screenshot_empty_note,
    _reader_page,
    _delivery_checklist_page as _build_delivery_checklist_page,
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
    _home_page,
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
    _qa_pass_report_output_root,
    _qa_pass_report_url,
    build_dashboard_qa_pass_report,
    export_dashboard_qa_pass_report,
    _screenshot_review_viewer_url,
    _materialize_screenshot_review_viewer_for_dashboard,
    _notify_completion_safe,
    _full_qa_completion_notification,
    DAILY_DIGEST_BUILD_PACKAGE_ACTION_ID,
    DAILY_DIGEST_BUILD_PACKAGE_ACTION_LABEL,
    QUALITY_HERO_REPORT_ACTION_ID,
    QUALITY_HERO_REPORT_ACTION_LABEL,
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
    _render_batch_full_qa_pass_panel,
    _render_full_qa_pass_panel,
)
from sg_preflight.dashboard.load_tokens import (
    DashboardLoadToken,
    _cancel_background_poll_timer,
    _complete_dashboard_page_load,
    _complete_dashboard_snapshot_refresh,
    _dashboard_load_token_is_current,
    _dashboard_load_token_matches,
    _ignorable_nicegui_runtime_error,
    _next_dashboard_load_token,
    _nicegui_client_deleted,
    _parent_slot_deleted,
    _run_javascript_if_client_alive,
    _start_background_poll_timer,
    _start_io_bound_poll_timer,
)
from sg_preflight.dashboard.manual_review_state import (
    MANUAL_REVIEW_RECORD_VERDICTS,
    MANUAL_REVIEW_STATUSES,
    _BLOCKED_MANUAL_STATUSES,
    _MANUAL_REVIEW_PENDING_VERDICT,
    _manual_review_state_path,
    record_manual_review_dashboard_step,
    save_manual_review_state,
)
from sg_preflight.dashboard.snapshot import (
    DASHBOARD_GUARDRAILS,
    DASHBOARD_NAVIGATION,
    DASHBOARD_NAV_GROUPS,
    DASHBOARD_SHORTCUT_ACTIONS,
    DASHBOARD_SHORTCUTS,
    DASHBOARD_TITLE,
    SETUP_COMPLETE_NOTE,
    _EAGER_PAGE_IDS,
    _apply_shell_metadata,
    _build_dashboard_pages,
    _build_navigation_groups,
    _daily_digest_ticket_context,
    _dashboard_active_ticket_id,
    _dashboard_changed_profiles,
    _delivery_checklist_page,
    _deferred_page_stub,
    build_dashboard_page,
    build_dashboard_snapshot,
)
from sg_preflight.dashboard.panels_common import (
    CONFLUENCE_DUMP_PREFIX,
    CONFLUENCE_DUMP_SPACE_KEY,
    DASHBOARD_BRAND_LOGO_ASSET,
    LONG_RUNNING_NOTIFICATION_SECONDS,
    VERBOSE_TOOLTIP_ENV,
    _STANDING_DISCLAIMER_RE,
    _STANDING_PANEL_NOTE,
    _STATUS_TONE_BAD_TOKENS,
    _STATUS_TONE_GOOD_TOKENS,
    _STATUS_TONE_WARN_TOKENS,
    _attach_tooltip,
    _confluence_anchor_path,
    _confluence_anchor_relative_path,
    _confluence_anchor_url,
    _confluence_dump_root,
    _copy_dashboard_link_to_clipboard,
    _copy_dashboard_text_to_clipboard,
    _dashboard_data_uri,
    _dashboard_verbose_tooltips_enabled,
    _file_activity_visual_items,
    _image_mime,
    _page_confluence_anchors,
    _pipeline_traceback,
    _reader_rows_from_payload,
    _render_about_panel,
    _render_changed_profiles_card,
    _render_confluence_anchor,
    _render_empty_state_note,
    _render_first_run_welcome,
    _render_page_confluence_anchors,
    _render_page_panel,
    _render_reader_rows,
    _render_source_root_reader_panel,
    _render_status_chip,
    _screenshot_review_visual_rows,
    _status_tone,
    _strip_standing_disclaimers,
)
from sg_preflight.dashboard.panels_setup_delivery import (
    _render_delivery_checklist_panel,
    _render_setup_status_panel,
)
from sg_preflight.dashboard.panels_screenshots import _render_screenshot_test_state_panel
from sg_preflight.dashboard.panels_scoring import (
    _render_cross_car_comparison_panel,
    _render_risk_score_panel,
    _render_team_digest_board_panel,
)


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
    "Build Quality-Hero report", "HTML report", "sgfx-wizard-card", "sgfx-wizard-overlay",
    "Confirm local tool action", "Skip current", "Full QA Pass summary", "full_qa_run", "automatic_mode",
    "Open report", "Export ZIP", "build_dashboard_qa_pass_report", "export_dashboard_qa_pass_report",
    "QA Pass report ready", "sgfx-qa-pass-verdict",
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
    "lambda _event=None, current=action: _confirm_start(current)", "Run selected profiles",
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
FIRST_LAUNCH_DISMISS_STORAGE_KEY = "sgfx.firstLaunch.dismissed"
FEEDBACK_EMAIL_ENV = "SGFX_FEEDBACK_EMAIL"
DEFAULT_FEEDBACK_EMAIL = "david-erik.garcia-arenas@paradoxcat.com"
DESKTOP_NOTIFICATIONS_ENV = "SGFX_DESKTOP_NOTIFICATIONS"
CANONICAL_SOURCE_REPO_ROOT = Path(r"C:\repositories\trunk")


PRIMARY_SURFACE_SUBTITLES = {item.surface_id: item.subtitle for item in SURFACE_DESCRIPTORS}
HOME_HUB_TILES = tuple(
    (item.surface_id, item.title, item.icon_key, item.subtitle)
    for item in REGISTERED_HOME_HUB_TILES
)
THEME_CHOICES = ["clean"]
QUALITY_HERO_CONFLUENCE_ANCHOR = (
    f"{CONFLUENCE_DUMP_PREFIX}139_3D-Car/298_Quality-Hero-How-to-review-the-3D-car/page.txt"
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
    f"{CONFLUENCE_DUMP_PREFIX}"
    "016_Project-Management/024_How-to...-Seriesgraphics/029_Regular-Meetings/030_SG-Daily/page.txt"
)

ABOUT_CONTENT: dict[str, Any] = {
    "heading": "About",
    "description": (
        "Local-only QA preflight tool for the SGFX Seriengrafik delivery workflow. "
        "Reads operator-local evidence (delivery documentation, screenshot test state, BMW pipeline "
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
        "This tool reads operator-local files (delivery documentation, BMW pipeline outputs, screenshot test state, manual-review records) and renders them for the morning Quality-Hero standup. No telemetry, no external service calls.",
        "Suggested evidence comes from a deterministic local filesystem probe — does this file exist, does this directory contain these files, does this workbook have these rows. The operator records every verdict; the tool does not pre-decide.",
        "The Jira post flow is the one explicit network boundary, and it stays default-off behind a --confirm flag. Default mode is dry-run.",
    ),
}
ABOUT_CONTENT["tagline"] = PRIMARY_SURFACE_SUBTITLES["about"]

# Logo placement spec:
#   sidebar header (Clean):        sgfx_icon.png        ~200 x auto px
#   main header (Clean):           logo_sgfx.png        ~96 x auto px
#   Grafiks shell HeaderBanner:    logo_sgfx.png        ~100 x auto px
#   About panel hero (Clean):      logo_sgfx.png        ~240 x auto px
#   Window taskbar (.ico):         exe_ico.ico              setWindowIcon(QIcon(exe_ico.ico))
#   Hotkey popup (Clean + Grafiks): debug_icon.png          ~96 x 96 px animated overlay
_DASHBOARD_TICKET_FALLBACK = "IDCEVODEV-977874"
_TICKET_ID_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
_MISSING_STATUSES = {
    "missing",
    "no_review_package",
    "no_overview_sheet",
    "not_found",
}
_UNKNOWN_STATUSES = {"error", "failed", "unreadable", "unknown"}
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
    "No cross-car comparison rows were generated yet. Choose two profiles with local evidence, then refresh this page."
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


def _dashboard_run_port(*, native: bool, port: int) -> int:
    if native or port:
        return port
    return _find_open_dashboard_port()


def run_grafiks_mode(
    *,
    profile_id: str = "",
    workspace: Path | str,
    bmw_root: Path | str | None = None,
    shell_path: Path | str | None = None,
) -> int:
    return _dashboard_grafiks.run_grafiks_mode(
        profile_id=profile_id,
        workspace=workspace,
        bmw_root=bmw_root,
        shell_path=shell_path,
        resolve_shell_exe=_resolve_grafiks_shell_exe,
        not_installed_message=_grafiks_not_installed_message,
    )


SCREENSHOT_TEST_STATE_OWNERSHIP_NOTE = (
    "Screenshot capture runs from the lane-correct BMW Git pipeline script after confirmation; SGFX reads the output as evidence."
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
        if page_id == "full-qa-pass":
            _render_full_qa_pass_panel(ui, snapshot, workspace)
        elif page_id == "delivery-checklist":
            _render_delivery_checklist_panel(ui, snapshot, workspace)
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
        materialize_page_ids: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        return await _io_bound(
            build_dashboard_snapshot,
            profile_id,
            workspace,
            bmw_root=bmw_root,
            ui_mode=ui_mode_override if ui_mode_override is not None else ui_mode,
            defer_daily_digest=defer_daily_digest,
            defer_team_digest_board=defer_team_digest_board,
            lazy_pages=True,
            materialize_page_ids=materialize_page_ids,
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
        lazy_pages=True,
    )

    @app.get("/sgfx-dashboard-api/full-qa-pass")
    async def _full_qa_pass_api(profile: str = "", trusted_tool_mode: str = "1") -> dict[str, Any]:
        requested_profile = str(profile or base_snapshot.get("profile_id") or initial_profile_id).strip()
        trusted = str(trusted_tool_mode).strip().casefold() in {"1", "true", "yes", "on"}
        # Same per-profile 30s dedup as the `_index` page handler. Pre-fix, this
        # JSON API was an unguarded second entry point for the same
        # build_full_qa_pass invocation; NiceGUI's WebSocket reconnect or any
        # client polling against this URL would re-fire the side effect even
        # when the dashboard gate was holding.
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
            # Dedup BEFORE firing so a NiceGUI WebSocket reconnect storm cannot
            # re-execute build_full_qa_pass with the cached trigger URL.
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
            .sgfx-dashboard { background: var(--sgfx-bg); color: var(--sgfx-fg); font-family: 'Segoe UI', 'Cascadia Code', Arial, sans-serif; line-height: 1.5; }
            .sgfx-theme-grafiks { background: var(--sgfx-bg); }
            .sgfx-shell { min-height: 100vh; gap: 0; }
            .sgfx-sidebar { position: fixed; inset: 0 auto 0 0; z-index: 9100; width: min(292px, calc(100vw - 56px)); min-height: 100vh; padding: 22px 16px; background: var(--sgfx-bg-elev); border-right: 1px solid var(--sgfx-border); gap: 10px; overflow-y: auto; transform: translateX(calc(-100% - 1px)); transition: transform 180ms ease-out, box-shadow 180ms ease-out; }
            body.sgfx-sidebar-open .sgfx-sidebar { transform: translateX(0); box-shadow: 18px 0 42px rgba(0, 0, 0, 0.38); }
            .sgfx-sidebar-backdrop { position: fixed; inset: 0; z-index: 9090; background: rgba(0, 0, 0, 0.46); opacity: 0; pointer-events: none; transition: opacity 160ms ease-out; }
            body.sgfx-sidebar-open .sgfx-sidebar-backdrop { opacity: 1; pointer-events: auto; }
            .sgfx-sidebar-logo { width: 200px; max-width: 100%; height: auto; object-fit: contain; margin: 4px 0 14px 0; }
            .sgfx-nav-button { justify-content: flex-start; border-radius: 6px; color: var(--sgfx-fg) !important; min-height: 34px; }
            .sgfx-nav-button:hover { background: var(--sgfx-accent-soft) !important; }
            .sgfx-nav-button[data-sgfx-nav-active="true"] { background: var(--sgfx-accent-soft) !important; color: var(--sgfx-accent) !important; font-weight: 600; }
            .sgfx-nav-home, .sgfx-nav-jump { border: 1px solid var(--sgfx-border) !important; }
            .sgfx-nav-jump { color: var(--sgfx-fg-muted) !important; }
            .sgfx-nav-group-title { margin: 12px 4px 2px 4px; color: var(--sgfx-fg-muted); font-size: 11px; letter-spacing: 0.02em; font-weight: 600; }
            .sgfx-jump-option { justify-content: flex-start; border-radius: 6px; color: var(--sgfx-fg) !important; min-height: 34px; }
            .sgfx-jump-option:hover, .sgfx-jump-option[data-sgfx-jump-active="true"] { background: var(--sgfx-accent-soft) !important; }
            .sgfx-jump-group { margin: 8px 2px 0 2px; color: var(--sgfx-fg-muted); font-size: 11px; letter-spacing: 0.02em; font-weight: 600; }
            .sgfx-jump-card { width: min(520px, 92vw); max-height: 78vh; gap: 8px; padding: 14px; background: var(--sgfx-bg-elev); border: 1px solid var(--sgfx-border); }
            .sgfx-jump-list { gap: 2px; overflow-y: auto; max-height: 58vh; }
            .sgfx-jump-input { margin-bottom: 4px; }
            .sgfx-hub-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; margin: 4px 0 8px 0; }
            .sgfx-hub-tile { display: flex; flex-direction: column; align-items: flex-start; gap: 6px; text-align: left; padding: 16px; border-radius: 10px; border: 1px solid var(--sgfx-border); background: var(--sgfx-bg-panel); color: var(--sgfx-fg); cursor: pointer; transition: border-color 120ms ease-out, transform 120ms ease-out; }
            .sgfx-hub-tile:hover { border-color: var(--sgfx-accent); transform: translateY(-1px); }
            .sgfx-hub-tile-icon { font-size: 26px; color: var(--sgfx-accent); }
            .sgfx-hub-tile-title { font-size: 15px; font-weight: 650; color: var(--sgfx-fg-strong); }
            .sgfx-hub-tile-desc { font-size: 12px; color: var(--sgfx-fg-muted); line-height: 1.4; }
            .sgfx-shortcut { color: var(--sgfx-fg-muted); font-size: 12px; line-height: 1.5; }
            .sgfx-menu-button { position: fixed; top: 18px; left: 18px; z-index: 9080; width: 36px; height: 36px; border: 1px solid var(--sgfx-border) !important; border-radius: 999px; background: var(--sgfx-bg-elev) !important; color: var(--sgfx-fg) !important; font-size: 20px; line-height: 1; cursor: pointer; box-shadow: 0 10px 24px rgba(0, 0, 0, 0.22); }
            body.sgfx-sidebar-open .sgfx-menu-button { border-color: var(--sgfx-accent) !important; color: var(--sgfx-accent) !important; }
            .sgfx-floating-shortcuts { position: fixed; left: 18px; bottom: 18px; z-index: 9070; display: flex; flex-direction: column; gap: 4px; padding: 8px 10px; border: 1px solid var(--sgfx-border); border-radius: 8px; background: rgba(37, 37, 38, 0.94); box-shadow: 0 10px 24px rgba(0, 0, 0, 0.22); transition: opacity 160ms ease-out, transform 160ms ease-out; }
            .sgfx-floating-shortcuts span { color: var(--sgfx-fg-muted); font-size: 12px; line-height: 1.35; }
            body.sgfx-sidebar-open .sgfx-floating-shortcuts { opacity: 0.36; transform: translateX(-4px); pointer-events: none; }
            .sgfx-main { flex: 1; min-width: 0; padding: 26px 34px 28px 78px; gap: 22px; background: var(--sgfx-bg); }
            .sgfx-header { border-bottom: 1px solid var(--sgfx-border-soft); padding-bottom: 16px; }
            .sgfx-subtitle { color: var(--sgfx-fg-muted); font-size: 13px; }
            .sgfx-registry-note { font-size: 12px; opacity: 0.75; }
            .sgfx-brand-lockup { gap: 14px; }
            .sgfx-brand-logo { height: 96px; max-width: 360px; width: auto; object-fit: contain; flex: 0 0 auto; }
            .sgfx-about-logo { width: 240px; max-width: 42vw; height: auto; object-fit: contain; flex: 0 0 auto; }
            .sgfx-content { width: 100%; }
            .sgfx-footer { border-top: 1px solid var(--sgfx-border); padding-top: 12px; margin-top: 12px; }
            .sgfx-footer-actions { gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
            .sgfx-feedback-button { border: 1px solid var(--sgfx-border) !important; border-radius: 6px; background: var(--sgfx-bg-elev) !important; color: var(--sgfx-fg) !important; min-height: 32px; padding: 0 12px; cursor: pointer; }
            .sgfx-feedback-button:hover { border-color: var(--sgfx-accent) !important; color: var(--sgfx-accent) !important; }
            .sgfx-guardrail { color: var(--sgfx-fg-muted); font-size: 13px; line-height: 1.55; }
            .sgfx-page-panel { border-radius: 10px; box-shadow: none; border: 1px solid var(--sgfx-border-soft); width: 100%; padding: 22px 24px; background: var(--sgfx-bg-panel); color: var(--sgfx-fg); margin-bottom: 16px; line-height: 1.55; }
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
            .sgfx-panel-title { font-size: 17px; font-weight: 650; color: var(--sgfx-fg-strong); letter-spacing: 0.01em; margin-bottom: 4px; }
            .sgfx-panel-tagline, .sgfx-muted { color: var(--sgfx-fg-muted); font-size: 13px; }
            .sgfx-standing-note { font-size: 11px; letter-spacing: 0.04em; opacity: 0.75; }
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
            .sgfx-status.sgfx-tone-bad { background: rgba(241, 76, 76, 0.18); color: #f14c4c; }
            .sgfx-status.sgfx-tone-warn { background: rgba(204, 167, 0, 0.16); color: #cca700; }
            .sgfx-status.sgfx-tone-good { background: rgba(137, 209, 133, 0.15); color: #89d185; }
            .sgfx-status.sgfx-tone-neutral { background: rgba(128, 128, 128, 0.15); color: var(--sgfx-fg-muted); }
            .sgfx-status-cell { font-weight: 600; }
            .sgfx-status-cell.sgfx-tone-bad { color: #f14c4c; }
            .sgfx-status-cell.sgfx-tone-warn { color: #cca700; }
            .sgfx-status-cell.sgfx-tone-good { color: #89d185; }
            .sgfx-status-cell.sgfx-tone-neutral { color: var(--sgfx-fg-muted); font-weight: 400; }
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
            "requested_profile_id": str(snapshot.get("profile_id", "")),
            "load_generation": 0,
            "dashboard_mode": "clean",
        }
        content_holder: dict[str, Any] = {}
        controls: dict[str, Any] = {}
        feedback_context = await _io_bound(_dashboard_feedback_context, workspace)

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

        async def _confirm_grafiks_launch() -> None:
            shell_path = await _io_bound(_resolve_grafiks_shell_exe, workspace)
            if shell_path is None:
                _set_mode_button_state("clean")
                _show_grafiks_confirm_dialog(_grafiks_not_installed_message(workspace), allow_continue=False)
                return
            _set_mode_button_state("grafiks")
            grafiks_confirm_dialog.close()
            exit_code = await _io_bound(
                run_grafiks_mode,
                profile_id=str(state["snapshot"].get("profile_id", "")),
                workspace=workspace,
                bmw_root=bmw_root,
                shell_path=shell_path,
            )
            if exit_code:
                _set_mode_button_state("clean")
                _show_grafiks_confirm_dialog(
                    f"Grafiks could not launch (code {exit_code}). Clean mode remains active.",
                    allow_continue=True,
                )

        async def _select_grafiks_mode() -> None:
            shell_path = await _io_bound(_resolve_grafiks_shell_exe, workspace)
            if shell_path is None:
                _set_mode_button_state("clean")
                _show_grafiks_confirm_dialog(_grafiks_not_installed_message(workspace), allow_continue=False)
                return
            _show_grafiks_confirm_dialog(
                "Grafiks is ready to launch.",
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
                if active_page_id == "home":
                    _render_changed_profiles_card(
                        ui,
                        state["snapshot"],
                        open_batch=_open_changed_profiles_batch,
                    )
                    with ui.element("div").classes("sgfx-hub-grid full-width"):
                        for surface_id, title, icon_key, subtitle in HOME_HUB_TILES:
                            with ui.element("button").classes("sgfx-hub-tile").on(
                                "click", lambda page_id=surface_id: _open_page(page_id)
                            ):
                                ui.icon(icon_key).classes("sgfx-hub-tile-icon")
                                ui.label(title).classes("sgfx-hub-tile-title")
                                ui.label(subtitle).classes("sgfx-hub-tile-desc")
                    home_page = _pages_by_id().get("home", {})
                    _render_page_panel(ui, home_page)
                elif active_page_id == "delivery-checklist":
                    _render_delivery_checklist_panel(
                        ui,
                        state["snapshot"],
                        workspace,
                        on_setup_completed=_refresh_snapshot,
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

        def _finish_page_transition(page_id: str) -> None:
            if not page_id:
                return
            _run_javascript_if_client_alive(
                ui,
                f"window.sgfxFinishTransition && window.sgfxFinishTransition('tab', {json.dumps(page_id)});",
            )

        async def _finish_snapshot_refresh(
            token: DashboardLoadToken,
            *,
            defer_daily_digest: bool,
            defer_team_digest_board: bool,
            transition_page_id: str = "",
            notify_message: str = "",
        ) -> None:
            try:
                snapshot = await _build_snapshot_io(
                    token.profile_id,
                    ui_mode_override=_current_theme(),
                    defer_daily_digest=defer_daily_digest,
                    defer_team_digest_board=defer_team_digest_board,
                    materialize_page_ids=(token.page_id,),
                )
            except Exception as exc:  # noqa: BLE001
                _complete_dashboard_snapshot_refresh(
                    token,
                    state=state,
                    snapshot=None,
                    error=exc,
                    render_current_page=_render_current_page,
                    refresh_labels=_refresh_labels,
                    notify=ui.notify,
                    finish_transition=_finish_page_transition,
                    transition_page_id=transition_page_id,
                )
                return
            _complete_dashboard_snapshot_refresh(
                token,
                state=state,
                snapshot=snapshot,
                error=None,
                render_current_page=_render_current_page,
                refresh_labels=_refresh_labels,
                notify=ui.notify,
                finish_transition=_finish_page_transition,
                transition_page_id=transition_page_id,
                notify_message=notify_message,
            )

        def _start_snapshot_refresh(
            *,
            profile_id: str,
            active_page_id: str,
            defer_daily_digest: bool,
            defer_team_digest_board: bool,
            loading_message: str,
            reason: str,
            transition_page_id: str = "",
            notify_message: str = "",
        ) -> None:
            _dashboard_changed_profiles.cache_clear()
            token = _next_dashboard_load_token(
                state,
                profile_id=profile_id,
                page_id=active_page_id,
                reason=reason,
            )
            state["loading_message"] = loading_message
            _render_current_page()
            _schedule_background(
                _finish_snapshot_refresh(
                    token,
                    defer_daily_digest=defer_daily_digest,
                    defer_team_digest_board=defer_team_digest_board,
                    transition_page_id=transition_page_id,
                    notify_message=notify_message,
                ),
                name="sgfx-dashboard-snapshot-refresh",
            )

        async def _load_single_page(
            token: DashboardLoadToken,
            *,
            transition_page_id: str = "",
            notify_message: str = "",
        ) -> None:
            try:
                page = await _io_bound(
                    build_dashboard_page,
                    token.page_id,
                    token.profile_id,
                    workspace,
                    bmw_root=bmw_root,
                    ui_mode=_current_theme(),
                )
            except Exception as exc:  # noqa: BLE001
                _complete_dashboard_page_load(
                    token,
                    state=state,
                    page=None,
                    error=exc,
                    render_current_page=_render_current_page,
                    notify=ui.notify,
                    finish_transition=_finish_page_transition,
                    transition_page_id=transition_page_id,
                )
                return
            _complete_dashboard_page_load(
                token,
                state=state,
                page=page,
                error=None,
                render_current_page=_render_current_page,
                notify=ui.notify,
                finish_transition=_finish_page_transition,
                transition_page_id=transition_page_id,
                notify_message=notify_message,
            )

        def _start_single_page_load(
            page_id: str,
            *,
            profile_id: str,
            reason: str,
            transition_page_id: str = "",
            notify_message: str = "",
        ) -> None:
            token = _next_dashboard_load_token(
                state,
                profile_id=profile_id,
                page_id=page_id,
                reason=reason,
            )
            title = str(_pages_by_id().get(page_id, {}).get("title", page_id))
            state["loading_message"] = f"Loading {title}..."
            _render_current_page()
            _schedule_background(
                _load_single_page(
                    token,
                    transition_page_id=transition_page_id,
                    notify_message=notify_message,
                ),
                name=f"sgfx-dashboard-page-{page_id}",
            )

        def _open_page(page_id: str) -> None:
            state["active_page_id"] = page_id
            _run_javascript_if_client_alive(ui, f"document.body.dataset.sgfxActivePage = {json.dumps(page_id)};")
            _run_javascript_if_client_alive(ui, f"window.sgfxHighlightNav && window.sgfxHighlightNav({json.dumps(page_id)});")
            _run_javascript_if_client_alive(ui, "window.sgfxSetSidebarOpen && window.sgfxSetSidebarOpen(false);")
            requested_profile = str(
                state.get("requested_profile_id") or state["snapshot"].get("profile_id", "")
            )
            if page_id == "about":
                _next_dashboard_load_token(
                    state,
                    profile_id=requested_profile,
                    page_id=page_id,
                    reason="navigation",
                )
                state["loading_message"] = ""
                _render_current_page()
                _finish_page_transition(page_id)
                return
            if requested_profile != str(state["snapshot"].get("profile_id", "")):
                _start_snapshot_refresh(
                    profile_id=requested_profile,
                    active_page_id=page_id,
                    defer_daily_digest=page_id != "daily-digest",
                    defer_team_digest_board=page_id != "team-digest-board",
                    loading_message=f"Loading {str(_pages_by_id().get(page_id, {}).get('title', page_id))}...",
                    reason="navigation",
                    transition_page_id=page_id,
                )
                return
            if page_id in {"daily-digest", "team-digest-board"} and _pages_by_id().get(page_id, {}).get("deferred"):
                _start_snapshot_refresh(
                    profile_id=requested_profile,
                    active_page_id=page_id,
                    defer_daily_digest=page_id != "daily-digest",
                    defer_team_digest_board=page_id != "team-digest-board",
                    loading_message=f"Loading {str(_pages_by_id().get(page_id, {}).get('title', page_id))}...",
                    reason="navigation",
                    transition_page_id=page_id,
                )
                return
            if _pages_by_id().get(page_id, {}).get("deferred"):
                _start_single_page_load(
                    page_id,
                    profile_id=requested_profile,
                    reason="navigation",
                    transition_page_id=page_id,
                )
                return
            _next_dashboard_load_token(
                state,
                profile_id=requested_profile,
                page_id=page_id,
                reason="navigation",
            )
            state["loading_message"] = ""
            _render_current_page()
            _finish_page_transition(page_id)

        def _refresh_snapshot(
            profile_id: str | None = None,
            *,
            notify_message: str = "",
            reason: str = "refresh",
        ) -> None:
            current_profile = (
                profile_id
                if profile_id is not None
                else str(state.get("requested_profile_id") or state["snapshot"].get("profile_id", ""))
            )
            active_page_id = str(state.get("active_page_id", "delivery-checklist"))
            _start_snapshot_refresh(
                profile_id=current_profile,
                active_page_id=active_page_id,
                defer_daily_digest=active_page_id != "daily-digest",
                defer_team_digest_board=active_page_id != "team-digest-board",
                loading_message="Refreshing dashboard data...",
                reason=reason,
                notify_message=notify_message,
            )

        def _refresh_current_page() -> None:
            _refresh_snapshot(notify_message="Current page refreshed from read-only sources.")

        def _set_profile(value: str) -> None:
            profile_id = _profile_id_from_select_value(value)
            if profile_id:
                _write_dashboard_profile_preference(workspace, profile_id)
            _refresh_snapshot(
                profile_id,
                notify_message=f"Profile switched to {profile_id or state['snapshot']['profile_id']}.",
                reason="profile_change",
            )

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
                        // Microsoft Teams native deep-link. Opens a 1:1 chat with
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
                        // Clipboard fallback so the operator's prefilled message is
                        // never lost even if Teams doesn't open (msteams:// protocol
                        // handler unregistered, browser blocking schemes, packaged
                        // exe restrictions, etc.).
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
                    window.sgfxHighlightNav = (pageId) => {{
                        document.querySelectorAll('[data-sgfx-nav-item]').forEach((el) => {{
                            el.dataset.sgfxNavActive = (el.dataset.sgfxNavItem === pageId) ? 'true' : 'false';
                        }});
                    }};
                    window.sgfxHighlightNav(document.body.dataset.sgfxActivePage || {json.dumps(state["active_page_id"])});
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

        jump_state: dict[str, Any] = {"filtered": []}

        def _jump_to(page_id: str) -> None:
            jump_dialog.close()
            _open_page(page_id)

        def _render_jump_options(query: str = "") -> None:
            jump_list.clear()
            needle = str(query or "").strip().lower()
            ordered: list[str] = []
            snapshot = state["snapshot"]
            nav_labels = {str(item["id"]): str(item["label"]) for item in snapshot["navigation"]}
            with jump_list:
                home_label = nav_labels.get("home", "Home")
                if not needle or needle in home_label.lower() or needle in "home":
                    ordered.append("home")
                    ui.button(
                        home_label,
                        icon="home",
                        on_click=lambda: _jump_to("home"),
                    ).props("flat no-caps align=left").classes("sgfx-jump-option full-width")
                for group in snapshot.get("navigation_groups", []):
                    matches = [
                        item
                        for item in group["items"]
                        if not needle
                        or needle in str(item["label"]).lower()
                        or needle in str(item["id"]).lower()
                    ]
                    if not matches:
                        continue
                    ui.label(str(group["title"])).classes("sgfx-jump-group")
                    for item in matches:
                        page_id = str(item["id"])
                        ordered.append(page_id)
                        ui.button(
                            str(item["label"]),
                            on_click=lambda pid=page_id: _jump_to(pid),
                        ).props("flat no-caps align=left").classes("sgfx-jump-option full-width")
                if not ordered:
                    ui.label("No page matches.").classes("sgfx-muted")
            jump_state["filtered"] = ordered

        def _jump_first() -> None:
            if jump_state["filtered"]:
                _jump_to(jump_state["filtered"][0])

        def _open_jump_palette() -> None:
            jump_input.value = ""
            _render_jump_options("")
            jump_dialog.open()

        def _handle_global_key(event: Any) -> None:
            try:
                if not getattr(event.action, "keydown", False):
                    return
                if event.key == "/":
                    _open_jump_palette()
            except Exception:  # pragma: no cover - defensive UI guard
                pass

        with ui.dialog() as jump_dialog:
            with ui.card().classes("sgfx-jump-card"):
                jump_input = (
                    ui.input(placeholder="Jump to page — type to filter, Enter opens the first match")
                    .props("autofocus outlined dense clearable")
                    .classes("sgfx-jump-input full-width")
                )
                jump_input.on_value_change(lambda: _render_jump_options(str(jump_input.value or "")))
                jump_input.on("keydown.enter", lambda: _jump_first())
                jump_list = ui.column().classes("sgfx-jump-list full-width")

        ui.keyboard(on_key=_handle_global_key)

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
              <span>/ Jump to page</span>
              <span>F1 Help</span>
              <span>Esc Close sidebar</span>
            </div>
            """,
            sanitize=False,
        )

        with ui.row().classes("sgfx-shell full-width no-wrap"):
            with ui.column().classes("sgfx-sidebar"):
                ui.image(f"/sgfx-dashboard-assets/{DASHBOARD_BRAND_ICON_ASSET}").classes("sgfx-sidebar-logo")
                nav_titles = {
                    str(item["id"]): str(item["label"])
                    for item in state["snapshot"]["navigation"]
                }
                _attach_tooltip(
                    ui,
                    ui.button(
                        nav_titles.get("home", "Home"),
                        icon="home",
                        on_click=lambda: _open_page("home"),
                    ).props("flat no-caps align=left data-sgfx-nav-item=home").classes(
                        "sgfx-nav-button sgfx-nav-home full-width"
                    ),
                    "Open the operator hub for the selected local profile.",
                )
                _attach_tooltip(
                    ui,
                    ui.button(
                        "Jump to page",
                        icon="search",
                        on_click=lambda: _open_jump_palette(),
                    ).props("flat no-caps align=left").classes("sgfx-nav-button sgfx-nav-jump full-width"),
                    "Jump to any page — press / anywhere.",
                )
                for group in state["snapshot"].get("navigation_groups", []):
                    ui.label(str(group["title"])).classes("sgfx-nav-group-title")
                    for nav_item in group["items"]:
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
                                '<div id="sgfx-shortcut-feedback" class="sgfx-shortcut-feedback"></div>'
                            )
                            registry = state["snapshot"].get("profile_registry", {})
                            controls["profile_registry_label"] = _attach_tooltip(
                                ui,
                                ui.label(
                                    str(registry.get("summary", "")) if isinstance(registry, dict) else ""
                                ).classes("sgfx-subtitle sgfx-registry-note"),
                                "Number of build profiles available in this workspace.",
                            )
                    with ui.row().classes("items-center"):
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
                        # Teams direct-message option. msteams:// deep-link opens
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

    def _register_session_hook(name: str, handler: object) -> None:
        callback = getattr(app, name, None)
        if not callable(callback):
            return
        try:
            callback(handler)
        except Exception:
            return

    def _session_startup() -> None:
        try:
            from sg_preflight import session_log

            session_log.start_session_log(
                root,
                source="ui",
                surface="dashboard",
                detail={"profile": profile_id, "ui_mode": ui_mode or "", "workspace": str(root)},
            )
            session_log.event(
                source="ui",
                surface="dashboard",
                profile=profile_id,
                message="Dashboard session started",
                detail={"ui_mode": ui_mode or "", "workspace": str(root), "native": native},
            )
        except Exception:
            return

    def _session_exception(*args: object, **kwargs: object) -> None:
        try:
            import traceback
            from sg_preflight import session_log

            exc = next((item for item in [*args, *kwargs.values()] if isinstance(item, BaseException)), None)
            if exc is not None:
                detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            else:
                detail = {"args": [str(item) for item in args], "kwargs": {key: str(value) for key, value in kwargs.items()}}
            session_log.event(
                source="exception",
                surface="dashboard",
                profile=profile_id,
                message="NiceGUI exception",
                detail=detail,
                level="error",
            )
        except Exception:
            return

    def _session_shutdown() -> None:
        try:
            from sg_preflight import session_log

            current = session_log.current_session_log()
            if current is None:
                return
            current.close_summary(surface="dashboard", profile=profile_id, message="Dashboard session ended")
        except Exception:
            return

    _register_session_hook("on_startup", _session_startup)
    _register_session_hook("on_exception", _session_exception)
    _register_session_hook("on_shutdown", _session_shutdown)

    try:
        _render_dashboard(ui, app, initial_profile_id=profile_id, workspace=root, bmw_root=bmw_root, ui_mode=ui_mode)
    except Exception as exc:
        try:
            from sg_preflight.session_log import exception_event

            exception_event(surface="dashboard render", exc=exc, profile=profile_id, message="Dashboard render failed")
        except Exception:
            pass
        append_startup_log(f"dashboard render failed: {type(exc).__name__}: {exc!r}")
        raise
    favicon_path = runtime_asset_path("sgfx_icon.png")
    run_port = _dashboard_run_port(native=native, port=port)
    if native:
        append_startup_log(f"attempting NiceGUI native mode on {host}:{run_port or 'auto'}")
        if not _frozen_native_window_allowed():
            append_startup_log("packaged native window is hosted by the desktop shell; opening the browser fallback")
            fallback_port = _dashboard_run_port(native=False, port=port)
            return _launch_browser_fallback_process(
                profile_id=profile_id,
                workspace=root,
                bmw_root=bmw_root,
                ui_mode=ui_mode,
                host=host,
                fallback_port=fallback_port,
            )
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
