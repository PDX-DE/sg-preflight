"""Facade re-exporting the desktop shell's evidence-model siblings — environment doctor, action listing,
formatting, and snapshot building — so every previous call site and mock-patch target still resolves here."""

from __future__ import annotations

from sg_preflight.desktop.evidence_environment_doctor import (
    DesktopEnvironmentItem,
    _state_counts,
    desktop_environment_doctor,
)

from sg_preflight.desktop.evidence_action_listing import (
    DAILY_DIGEST_EMPTY_NOTE,
    DELIVERY_CHECKLIST_EMPTY_NOTE,
    DesktopActionChoice,
    DesktopBlockerItem,
    DesktopManualCard,
    DesktopProfileChoice,
    DesktopRecentActionItem,
    DesktopRecentRunItem,
    DesktopSurfaceItem,
    MANUAL_REVIEW_EMPTY_NOTE,
    PRIMARY_ACTION_TEMPLATE,
    SCREENSHOT_TEST_STATE_EMPTY_NOTE,
    _abbreviate_workspace_text,
    _latest_action_record,
    _latest_run_record,
    _ready_profiles,
    _recent_actions,
    _recent_runs,
    _surface_empty_note,
    _surface_state,
    _surface_summary,
    desktop_actions_for_profile,
    desktop_blocker_items,
    desktop_manual_cards,
    desktop_profiles,
    desktop_recent_actions,
    desktop_recent_runs,
    desktop_surface_items,
)

from sg_preflight.desktop.evidence_formatting import (
    DesktopArtifactItem,
    DesktopCopyItem,
    DesktopEvidenceItem,
    _action_grouped_lines,
    _action_source_items,
    _artifact_items,
    _checker_evidence,
    _coerce_line_number,
    _copy_items,
    _counts_line,
    _decision_title,
    _dedupe_artifact_items,
    _desktop_evidence_items,
    _export_copy_items,
    _grouped_finding_lines,
    _latest_markdown_text,
    _load_text_path,
    _load_visual_review_payload,
    _manual_evidence_copy_lines,
    _primary_evidence_line,
    _quick_update_text,
    _report_grouped_items,
    _run_artifact_items,
    _run_source_items,
    _summary_lines,
    _tail_text,
    _visual_review_copy_item,
    _workflow_stage_label,
)

from sg_preflight.desktop.evidence_snapshot_builder import (
    DesktopActionSnapshot,
    DesktopLinks,
    DesktopOperatorOverview,
    DesktopRunSnapshot,
    _desktop_run_snapshot_from_action_record,
    _initializing_run_snapshot,
    _looks_like_transient_run_reference,
    desktop_action_snapshot,
    desktop_operator_overview,
    desktop_run_snapshot,
    latest_action_snapshot_for_profile,
    latest_run_links,
)

# also used by desktop_surface_items() in evidence_action_listing.py, resolved through this
# module's namespace at call time so mock.patch("sg_preflight.desktop.evidence_model.*") still intercepts
from sg_preflight.cross_car_comparison import build_cross_car_comparison
from sg_preflight.team_digest_board import build_team_daily_digest_board
