"""Builds the desktop shell's operator profile, action, blocker, manual-review, surface, and recent-run listings from backend state."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sg_preflight.bmw_delivery import read_bmw_screenshot_state
from sg_preflight.daily_digest import build_latest_daily_digest
from sg_preflight.delivery_checklist import read_delivery_checklist
from sg_preflight.operator_handoff import build_operator_handoff_snapshot
from sg_preflight.profiles import RunProfile, list_run_profiles
from sg_preflight.qa_actions import ActionRecord, list_operator_actions, list_recent_action_records
from sg_preflight.risk_scoring import read_per_car_risk_score
from sg_preflight.services import (
    RunRecord,
    list_recent_run_records,
    prerequisite_status,
    qa_workflow_status,
    workspace_root,
)
from sg_preflight.visual_review import build_visual_review_prep

from sg_preflight.desktop.evidence_formatting import _counts_line, _decision_title, _summary_lines


PRIMARY_ACTION_TEMPLATE = (
    "qa_stack__{profile}",
    "repo_checker_profile__{profile}",
    "scene_check__{profile}",
    "unused_resources__{profile}",
    "delivery_checklist__{profile}",
)


DELIVERY_CHECKLIST_EMPTY_NOTE = (
    "No size-analysis workbook yet for this profile. Click Generate to invoke the BMW pipeline export step."
)


SCREENSHOT_TEST_STATE_EMPTY_NOTE = (
    "No captured screenshots yet — run the lane-correct BMW Git screenshot command for this profile to generate."
)


DAILY_DIGEST_EMPTY_NOTE = (
    "No review package on this workspace yet. Click Build to generate one for the active ticket."
)


MANUAL_REVIEW_EMPTY_NOTE = (
    "Manual review session not started. Click Start Session below to begin, then Record evidence on each Quality-Hero step as you complete it."
)


@dataclass(frozen=True)
class DesktopProfileChoice:
    profile_id: str
    label: str
    summary: str
    recommended_action_id: str


@dataclass(frozen=True)
class DesktopActionChoice:
    action_id: str
    label: str
    description: str
    ready: bool
    blocker_message: str
    command_preview: str


@dataclass(frozen=True)
class DesktopBlockerItem:
    key: str
    label: str
    state: str
    summary: str
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class DesktopManualCard:
    key: str
    label: str
    state: str
    summary: str
    note: str


@dataclass(frozen=True)
class DesktopSurfaceItem:
    key: str
    label: str
    state: str
    summary: str


@dataclass(frozen=True)
class DesktopRecentActionItem:
    run_id: str
    action_id: str
    title: str
    status: str
    profile_id: str
    created_at_utc: str
    progress_label: str
    summary: str


@dataclass(frozen=True)
class DesktopRecentRunItem:
    run_id: str
    profile_id: str
    profile_label: str
    title: str
    status: str
    created_at_utc: str
    summary: str
    html_report: str


def _ready_profiles(root: Path, profiles: list[RunProfile] | None = None) -> list[RunProfile]:
    live_profiles = profiles if profiles is not None else list_run_profiles(root)
    return [
        profile
        for profile in live_profiles
        if profile.source_project_root().exists()
    ]


def _recent_actions(root: Path) -> list[ActionRecord]:
    return list_recent_action_records(root, limit=200)


def _recent_runs(root: Path) -> list[RunRecord]:
    return list_recent_run_records(root, limit=200)


def _latest_action_record(
    profile_id: str,
    root: Path,
    *,
    preferred_action_id: str = "",
) -> ActionRecord | None:
    normalized_profile = profile_id.strip().lower()
    normalized_action = preferred_action_id.strip().lower()
    for record in _recent_actions(root):
        if record.profile_id.strip().lower() != normalized_profile:
            continue
        if normalized_action and record.action_id.strip().lower() != normalized_action:
            continue
        return record
    return None


def _latest_run_record(profile_id: str, root: Path) -> RunRecord | None:
    normalized_profile = profile_id.strip().lower()
    for record in _recent_runs(root):
        if record.profile_id.strip().lower() == normalized_profile:
            return record
    return None


def desktop_profiles(
    workspace: Path | None = None,
    *,
    profiles: list[RunProfile] | None = None,
) -> list[DesktopProfileChoice]:
    root = workspace_root(workspace)
    items: list[DesktopProfileChoice] = []
    for profile in _ready_profiles(root, profiles):
        latest = _latest_action_record(profile.profile_id, root, preferred_action_id=f"qa_stack__{profile.profile_id.lower()}")
        if latest is not None and isinstance(latest.summary, dict):
            lines = [str(line).strip() for line in latest.summary.get("lines", []) if str(line).strip()]
            summary = lines[0] if lines else profile.friendly_summary or profile.operator_goal or profile.description
        else:
            summary = profile.friendly_summary or profile.operator_goal or profile.description
        items.append(
            DesktopProfileChoice(
                profile_id=profile.profile_id,
                label=profile.label,
                summary=summary,
                recommended_action_id=f"qa_stack__{profile.profile_id.lower()}",
            )
        )
    return items


def desktop_actions_for_profile(
    profile_id: str,
    workspace: Path | None = None,
    *,
    profiles: list[RunProfile] | None = None,
) -> list[DesktopActionChoice]:
    root = workspace_root(workspace)
    live_profiles = _ready_profiles(root, profiles)
    action_map = {
        action.action_id: action
        for action in list_operator_actions(root, profiles=live_profiles)
    }
    action_ids = [
        template.format(profile=profile_id.strip().lower())
        for template in PRIMARY_ACTION_TEMPLATE
    ]
    items: list[DesktopActionChoice] = []
    for action_id in action_ids:
        action = action_map.get(action_id)
        if action is None:
            continue
        items.append(
            DesktopActionChoice(
                action_id=action.action_id,
                label=action.label,
                description=action.description,
                ready=action.ready,
                blocker_message=action.blocker_message,
                command_preview=action.command_preview,
            )
        )
    return items


def desktop_blocker_items(
    profile_id: str,
    workspace: Path | None = None,
    *,
    profiles: list[RunProfile] | None = None,
) -> list[DesktopBlockerItem]:
    root = workspace_root(workspace)
    live_profiles = _ready_profiles(root, profiles)
    readiness = {item["key"]: item for item in prerequisite_status(root)}
    workflow = {item["key"]: item for item in qa_workflow_status(root, live_profiles)}

    def _machine_item(key: str, label: str, summary: str) -> DesktopBlockerItem:
        item = readiness.get(key, {})
        state = "available" if item.get("status") == "available" else "blocked"
        blocker = () if state == "available" else (f"{label} is not available locally: {item.get('path', '')}",)
        return DesktopBlockerItem(
            key=key,
            label=label,
            state=state,
            summary=summary if state == "available" else f"{summary} Missing on this machine.",
            blockers=blocker,
        )

    workflow_items = []
    for key in ("repo_scene_checks", "delivery_checklist", "bmw_screenshot_smoke"):
        item = workflow.get(key, {})
        workflow_items.append(
            DesktopBlockerItem(
                key=key,
                label=str(item.get("label", key.replace("_", " ").title())),
                state=str(item.get("state", "blocked")),
                summary=str(item.get("summary", "")),
                blockers=tuple(str(blocker) for blocker in item.get("blockers", []) if str(blocker).strip()),
            )
        )

    return [
        _machine_item(
            "raco_headless",
            "RaCo / RaCoHeadless",
            "Desktop scene-check execution depends on the local RaCoHeadless tool.",
        ),
        workflow_items[0],
        workflow_items[1],
        _machine_item(
            "bmw_models_repo",
            "BMW Repo Access",
            "BMW-owned delivery and smoke helpers still depend on a local `digital-3d-car-models` clone.",
        ),
        workflow_items[2],
    ]


def desktop_manual_cards(
    profile_id: str,
    workspace: Path | None = None,
    *,
    profiles: list[RunProfile] | None = None,
) -> list[DesktopManualCard]:
    root = workspace_root(workspace)
    live_profiles = _ready_profiles(root, profiles)
    normalized_profile = profile_id.strip().lower()
    selected_profile = next(
        (profile for profile in live_profiles if profile.profile_id.strip().lower() == normalized_profile),
        None,
    )
    readiness = {item["key"]: item for item in prerequisite_status(root)}
    workflow = {item["key"]: item for item in qa_workflow_status(root, live_profiles)}
    raco_status = str(readiness.get("raco_gui", {}).get("status", "missing"))
    raco_ready = raco_status == "available"
    blender_ready = str(readiness.get("blender_executable", {}).get("status", "missing")) == "available"
    delivery = workflow.get("delivery_checklist", {})
    bmw = workflow.get("bmw_screenshot_smoke", {})
    bmw_checklist_path = root / "docs" / "bmw-access-integration-checklist.md"
    bmw_checklist_note = (
        f"Keep the intake steps in {bmw_checklist_path} so BMW access, repo setup, helper discovery, and first dry run are available the moment access lands."
        if bmw_checklist_path.exists()
        else "Add docs/bmw-access-integration-checklist.md so BMW access and smoke setup can be tracked inside the shell flow."
    )
    review_prep = (
        build_visual_review_prep(
            selected_profile.profile_id,
            selected_profile.source_project_root(),
            repo_root=selected_profile.source_repo_root(),
        )
        if selected_profile is not None and selected_profile.source_project_root().exists()
        else None
    )

    visual_review_summary = (
        "Open the changed area in Blender and RaCo, compare both views, then record the result as first-class manual evidence."
        if blender_ready and raco_ready
        else "At least one visual-review tool is still missing or incompatible locally, so keep the checklist explicit instead of assuming the visual pass happened."
    )
    if review_prep is not None and review_prep.screenshot_count:
        visual_review_summary = (
            f"Compare the changed area in Blender and RaCo, then cross-check it against "
            f"{review_prep.screenshot_count} live screenshot baselines."
        )

    visual_review_note = (
        "Use ATTACH VISUAL REVIEW CHECKLIST to save: project changelog reviewed, screenshot baseline reviewed, Blender scene opened, "
        "RaCo scene opened, Blender vs RaCo compared, key camera checked, screenshot captured, and finding documented."
    )
    if review_prep is not None and review_prep.priority_screenshots:
        visual_review_note += " After running a profile action, open the generated Visual review gallery from Files and start with: " + ", ".join(review_prep.priority_screenshots[:6]) + "."

    cards = [
        DesktopManualCard(
            key="visual_review_session",
            label="Visual review session",
            state="manual" if (blender_ready or raco_ready) else "blocked",
            summary=visual_review_summary,
            note=visual_review_note,
        ),
    ]

    if review_prep is not None:
        cards.append(
            DesktopManualCard(
                key="project_changelog_review",
                label="Project changelog review",
                state="manual" if review_prep.changelog_path else "blocked",
                summary=review_prep.changelog_heading or "Project changelog is not available locally.",
                note=(
                    "Focus lines: " + " | ".join(review_prep.changelog_focus_lines[:4])
                    if review_prep.changelog_focus_lines
                    else "Review the latest car changelog before trusting the visual baseline."
                ),
            )
        )
        cards.append(
            DesktopManualCard(
                key="screenshot_baseline_review",
                label="Screenshot baseline review",
                state="manual" if review_prep.screenshot_count else "blocked",
                summary=(
                    f"{review_prep.screenshot_count} live screenshot baselines are available for local reference."
                    if review_prep.screenshot_count
                    else "No live screenshot baselines were detected under export/tests/expected."
                ),
                note=(
                    "Priority shortlist: " + ", ".join(review_prep.priority_screenshots[:6])
                    if review_prep.priority_screenshots
                    else "Run a profile action first, then open the generated Visual review gallery from Files."
                ),
            )
        )
        cards.append(
            DesktopManualCard(
                key="tool_entrypoints",
                label="Tool entry points",
                state="manual" if (review_prep.raco_scene_path or review_prep.blender_workfile_path) else "blocked",
                summary="Representative local files are available for first-pass open-in-RaCo / open-in-Blender checks.",
                note=" | ".join(
                    part
                    for part in (
                        f"RaCo: {Path(review_prep.raco_scene_path).name}" if review_prep.raco_scene_path else "",
                        f"Blender: {Path(review_prep.blender_workfile_path).name}" if review_prep.blender_workfile_path else "",
                        f"Constants README: {Path(review_prep.constants_readme_path).name}" if review_prep.constants_readme_path else "",
                    )
                    if part
                ) or "Representative RaCo or Blender files were not detected for this profile.",
            )
        )
        cards.append(
            DesktopManualCard(
                key="shared_bmw_docs_review",
                label="Shared BMW docs review",
                state="manual" if (review_prep.shared_doc_paths or review_prep.shared_svn_log_lines) else "blocked",
                summary=(
                    f"{len(review_prep.shared_doc_paths)} shared BMW README / CHANGELOG file(s) were prioritized from the latest shared SVN log."
                    if review_prep.shared_doc_paths
                    else "No shared BMW README / CHANGELOG shortlist was generated."
                ),
                note=(
                    "Shared SVN: " + " | ".join(review_prep.shared_svn_log_lines[:2])
                    if review_prep.shared_svn_log_lines
                    else "Open the generated Visual review prep from Files to inspect shared BMW SVN and README / CHANGELOG context."
                ),
            )
        )

    cards.extend([
        DesktopManualCard(
            key="screenshot_slots",
            label="Screenshot evidence slot",
            state="manual",
            summary="Capture the important proof shots early instead of waiting for delivery pressure.",
            note=f"Attach the screenshot path next to the {profile_id} evidence bundle once you have it.",
        ),
        DesktopManualCard(
            key="bmw_access_intake",
            label="BMW access intake checklist",
            state="blocked" if str(bmw.get("state", "blocked")) == "blocked" else "manual",
            summary=(
                "BMW-side smoke is still blocked locally, so the intake checklist has to stay visible in the shell instead of living in chat memory."
            ),
            note=bmw_checklist_note,
        ),
        DesktopManualCard(
            key="delivery_note",
            label="Delivery documentation note",
            state=str(delivery.get("state", "blocked")),
            summary=str(delivery.get("summary", "The delivery documentation state is not available.")),
            note="Call out BMW blockers explicitly instead of hiding them in a vague note.",
        ),
        DesktopManualCard(
            key="post_integration_note",
            label="Post-integration note",
            state="manual" if str(bmw.get("state", "blocked")) != "blocked" else "blocked",
            summary=(
                "After integration, record positive and negative outcomes in Jira or QA Hero with the same evidence links."
                if str(bmw.get("state", "blocked")) != "blocked"
                else "BMW-side follow-up is still blocked locally, so keep the SG-side post-integration note visible without pretending the BMW stage ran."
            ),
            note="Use the SG-side report links first, then append the BMW-side outcome once access exists.",
        ),
    ])
    return cards


def _surface_state(payload: dict[str, Any]) -> str:
    raw_status = str(payload.get("status", "unknown") or "unknown").strip()
    if bool(payload.get("data_available", False)):
        return "available"
    if raw_status == "no_review_package":
        return "incomplete"
    if raw_status in {"no_workbook", "unavailable", "profile_not_found"}:
        return "unavailable"
    if raw_status in {"missing", "not_found", "no_overview_sheet"}:
        return "missing"
    if raw_status in {"error", "failed", "unreadable"}:
        return "unknown"
    return raw_status or "unknown"


def _abbreviate_workspace_text(text: str, root: Path) -> str:
    root_text = str(root.resolve())
    if root_text not in text:
        return text
    return text.replace(root_text, root.name or str(root))


def _surface_empty_note(key: str, payload: dict[str, Any]) -> str:
    if key == "delivery-checklist" and _surface_state(payload) == "unavailable":
        return DELIVERY_CHECKLIST_EMPTY_NOTE
    if key == "daily-digest" and str(payload.get("status", "")) == "no_review_package":
        return DAILY_DIGEST_EMPTY_NOTE
    if key == "screenshot-test-state":
        try:
            actual_count = int(payload.get("actual_count", 0) or 0)
            diff_count = int(payload.get("diff_count", 0) or 0)
        except (TypeError, ValueError):
            actual_count = 0
            diff_count = 0
        if actual_count == 0 and diff_count == 0:
            return SCREENSHOT_TEST_STATE_EMPTY_NOTE
    return ""


def _surface_summary(key: str, payload: dict[str, Any], fallback: str, root: Path) -> str:
    raw = payload.get("summary", "")
    if isinstance(raw, dict):
        raw = ""
    text = str(raw or payload.get("no_data_message", "") or payload.get("note", "") or fallback)
    note = _surface_empty_note(key, payload)
    if note and note not in text:
        text = f"{text} {note}"
    return _abbreviate_workspace_text(text, root)


def desktop_surface_items(profile_id: str, workspace: Path | None = None) -> list[DesktopSurfaceItem]:
    from sg_preflight.desktop import evidence_model as _facade

    root = workspace_root(workspace)
    normalized_profile = profile_id.strip() or "profile"

    def _from_payload(key: str, label: str, payload: dict[str, Any]) -> DesktopSurfaceItem:
        return DesktopSurfaceItem(
            key=key,
            label=label,
            state=_surface_state(payload),
            summary=_surface_summary(key, payload, "No summary available.", root),
        )

    def _safe_item(key: str, label: str, reader) -> DesktopSurfaceItem:
        try:
            payload = reader()
        except Exception as exc:
            return DesktopSurfaceItem(
                key=key,
                label=label,
                state="unknown",
                summary=f"{label} could not be read: {exc}",
            )
        return _from_payload(key, label, payload)

    return [
        _safe_item(
            "delivery-checklist",
            "Delivery documentation",
            lambda: read_delivery_checklist(profile_id=normalized_profile, workspace=root),
        ),
        _safe_item(
            "screenshot-test-state",
            "Screenshot Test State",
            lambda: read_bmw_screenshot_state(normalized_profile, workspace=root, sg_project_root=root),
        ),
        _safe_item(
            "risk-score",
            "Risk Score",
            lambda: read_per_car_risk_score(normalized_profile, workspace=root),
        ),
        _safe_item(
            "cross-car-comparison",
            "Cross-Car Comparison",
            lambda: _facade.build_cross_car_comparison(workspace=root, left_profile="", right_profile=""),
        ),
        _safe_item(
            "daily-digest",
            "Daily Digest",
            lambda: build_latest_daily_digest(workspace=root),
        ),
        _safe_item(
            "team-digest-board",
            "Team Digest Board",
            lambda: _facade.build_team_daily_digest_board(workspace=root, profiles=(normalized_profile,)),
        ),
        _safe_item(
            "operator-handoff",
            "Operator Handoff",
            lambda: build_operator_handoff_snapshot(workspace=root, profile_id=normalized_profile),
        ),
        DesktopSurfaceItem(
            key="manual-review",
            label="Manual Review Companion",
            state="not_run",
            summary=MANUAL_REVIEW_EMPTY_NOTE,
        ),
    ]


def desktop_recent_actions(
    workspace: Path | None = None,
    *,
    profile_id: str = "",
    limit: int = 12,
) -> list[DesktopRecentActionItem]:
    root = workspace_root(workspace)
    normalized_profile = profile_id.strip().lower()
    items: list[DesktopRecentActionItem] = []
    for record in list_recent_action_records(root, limit=max(limit * 4, limit)):
        if normalized_profile and record.profile_id.strip().lower() != normalized_profile:
            continue
        summary = record.summary if isinstance(record.summary, dict) else {}
        summary_lines = _summary_lines(summary)
        progress = record.progress if isinstance(record.progress, dict) else {}
        items.append(
            DesktopRecentActionItem(
                run_id=record.run_id,
                action_id=record.action_id,
                title=str(summary.get("title", record.label)).strip() or record.label,
                status=record.status,
                profile_id=record.profile_id,
                created_at_utc=record.created_at_utc,
                progress_label=str(progress.get("label", "")).strip(),
                summary=summary_lines[0] if summary_lines else record.label,
            )
        )
        if len(items) >= limit:
            break
    return items


def desktop_recent_runs(
    workspace: Path | None = None,
    *,
    profile_id: str = "",
    limit: int = 12,
) -> list[DesktopRecentRunItem]:
    root = workspace_root(workspace)
    normalized_profile = profile_id.strip().lower()
    items: list[DesktopRecentRunItem] = []
    for record in _recent_runs(root):
        if normalized_profile and record.profile_id.strip().lower() != normalized_profile:
            continue
        counts = record.summary or {}
        title = _decision_title(counts)
        items.append(
            DesktopRecentRunItem(
                run_id=record.run_id,
                profile_id=record.profile_id,
                profile_label=record.profile_label,
                title=title,
                status=record.status,
                created_at_utc=record.created_at_utc,
                summary=_counts_line(counts),
                html_report=str(record.paths.get("html_report", "")).strip(),
            )
        )
        if len(items) >= limit:
            break
    return items
