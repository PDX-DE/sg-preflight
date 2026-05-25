from __future__ import annotations

import importlib.util
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
from typing import Any
import uuid

from sg_preflight.bmw_delivery import read_bmw_screenshot_state
from sg_preflight.cross_car_comparison import build_cross_car_comparison
from sg_preflight.daily_digest import build_latest_daily_digest
from sg_preflight.delivery_checklist import read_delivery_checklist
from sg_preflight.manual_review import QUALITY_HERO_STEPS
from sg_preflight.profiles import RunProfile, list_run_profiles
from sg_preflight.qa_actions import ActionRecord, list_operator_actions, list_recent_action_records, load_action_record
from sg_preflight.export_size_analysis import read_export_size_analysis
from sg_preflight.reporting import build_report_presentation
from sg_preflight.risk_scoring import read_per_car_risk_score
from sg_preflight.team_digest_board import build_team_daily_digest_board
from sg_preflight.services import (
    RunRecord,
    list_recent_run_records,
    load_run_config,
    load_run_record,
    load_run_report,
    prerequisite_status,
    qa_workflow_status,
    utc_now,
    workspace_root,
)
from sg_preflight.visual_review import build_visual_review_prep


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
class DesktopEvidenceItem:
    path: str
    checker: str
    message: str
    severity: str
    line: int | None = None
    source_kind: str = ""


@dataclass(frozen=True)
class DesktopArtifactItem:
    label: str
    path: str


@dataclass(frozen=True)
class DesktopCopyItem:
    key: str
    label: str
    text: str


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


@dataclass(frozen=True)
class DesktopLinks:
    output_root: str = ""
    html_report: str = ""
    markdown_report: str = ""
    json_report: str = ""


@dataclass(frozen=True)
class DesktopActionSnapshot:
    run_id: str
    action_id: str
    title: str
    status: str
    profile_id: str
    progress_percent: int
    progress_label: str
    progress_detail: str
    current_command: str
    child_run_id: str
    linked_run_id: str
    workspace_root: str
    project_root: str
    output_root: str
    error_message: str
    exit_code: int
    summary_lines: tuple[str, ...]
    top_paths: tuple[DesktopEvidenceItem, ...]
    manual_followups: tuple[str, ...]
    artifacts: tuple[DesktopArtifactItem, ...]
    log_path: str
    log_tail: str
    latest_run_links: DesktopLinks
    copy_items: tuple[DesktopCopyItem, ...]
    summary_only: bool


@dataclass(frozen=True)
class DesktopRunSnapshot:
    run_id: str
    profile_id: str
    profile_label: str
    status: str
    initializing: bool
    created_at_utc: str
    workflow_stage_label: str
    summary_title: str
    current_command: str
    log_path: str
    log_tail: str
    output_root: str
    project_root: str
    error_message: str
    exit_code: int
    summary_lines: tuple[str, ...]
    grouped_lines: tuple[str, ...]
    notes: tuple[str, ...]
    packs: tuple[str, ...]
    artifacts: tuple[DesktopArtifactItem, ...]
    source_files: tuple[DesktopArtifactItem, ...]
    copy_items: tuple[DesktopCopyItem, ...]


@dataclass(frozen=True)
class DesktopEnvironmentItem:
    key: str
    category: str
    label: str
    state: str
    summary: str
    path: str
    next_action: str


@dataclass(frozen=True)
class DesktopOperatorOverview:
    workspace_root: str
    generated_at_utc: str
    recommended_profile_id: str
    recommended_action_id: str
    ready_profile_count: int
    action_count: int
    ready_action_count: int
    blocked_action_count: int
    blocker_count: int
    manual_card_count: int
    environment_state_counts: dict[str, int]
    latest_action_run_id: str
    latest_action_status: str
    latest_run_id: str
    latest_run_status: str
    summary_line: str
    export_size_analysis_status: str = "no_profile"
    export_size_analysis_variant_count: int = 0
    export_size_analysis_workbook_date: str = ""
    export_size_analysis_summary: str = ""
    export_size_analysis_workbook_path: str = ""


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


def latest_run_links(profile_id: str, workspace: Path | None = None) -> DesktopLinks:
    root = workspace_root(workspace)
    record = _latest_run_record(profile_id, root)
    if record is None:
        return DesktopLinks()
    return DesktopLinks(
        output_root=str(record.paths.get("output_root", "")),
        html_report=str(record.paths.get("html_report", "")),
        markdown_report=str(record.paths.get("markdown_report", "")),
        json_report=str(record.paths.get("json_report", "")),
    )


def desktop_environment_doctor(workspace: Path | None = None) -> list[DesktopEnvironmentItem]:
    root = workspace_root(workspace)
    readiness = {item["key"]: item for item in prerequisite_status(root)}

    def _ready_from_prereq(key: str) -> bool:
        return str(readiness.get(key, {}).get("status", "")).strip().lower() == "available"

    def _status_from_prereq(key: str) -> str:
        return str(readiness.get(key, {}).get("status", "")).strip().lower()

    def _detail_from_prereq(key: str) -> str:
        return str(readiness.get(key, {}).get("detail", "")).strip()

    def _probe_path_from_prereq(key: str) -> str:
        return str(readiness.get(key, {}).get("probe_path", "")).strip()

    def _item(
        *,
        key: str,
        category: str,
        label: str,
        state: str,
        summary: str,
        path: str,
        next_action: str,
    ) -> DesktopEnvironmentItem:
        return DesktopEnvironmentItem(
            key=key,
            category=category,
            label=label,
            state=state,
            summary=summary,
            path=path,
            next_action=next_action,
        )

    sg_module_spec = importlib.util.find_spec("sg_preflight")
    sg_module_path = ""
    if sg_module_spec is not None:
        if sg_module_spec.origin:
            sg_module_path = str(Path(sg_module_spec.origin))
        elif sg_module_spec.submodule_search_locations:
            sg_module_path = str(next(iter(sg_module_spec.submodule_search_locations), ""))

    delivery_keys = (
        "delivery_checklist_tool",
        "delivery_checklist_helper",
        "delivery_checklist_readme",
        "delivery_checklist_camera_crane",
    )
    delivery_ready = sum(1 for key in delivery_keys if _ready_from_prereq(key))
    if delivery_ready == len(delivery_keys):
        delivery_state = "available"
        delivery_summary = "The mirrored delivery-checklist bridge assets are present locally. This remains SG-side readiness, not BMW execution."
    elif delivery_ready > 0:
        delivery_state = "partial"
        delivery_summary = "Some delivery-checklist bridge assets exist locally, but the mirrored set is incomplete."
    else:
        delivery_state = "blocked"
        delivery_summary = "The mirrored delivery-checklist bridge assets are not available locally yet."

    bmw_script_keys = (
        "bmw_screenshot_scripts",
        "bmw_car_manager_script",
        "bmw_test_main_script",
    )
    bmw_script_ready = sum(1 for key in bmw_script_keys if _ready_from_prereq(key))
    if bmw_script_ready == len(bmw_script_keys):
        bmw_scripts_state = "available"
        bmw_scripts_summary = "The BMW smoke helper script surface is present locally."
    elif bmw_script_ready > 0:
        bmw_scripts_state = "partial"
        bmw_scripts_summary = "Some BMW smoke helper files were found locally, but the full helper surface is incomplete."
    else:
        bmw_scripts_state = "blocked"
        bmw_scripts_summary = "BMW smoke helper scripts are still blocked on repo access and local checkout."

    output_root = root / "out" / "operator-ui"
    output_state = "not_run"
    output_summary = "Operator output write access is not probed during this read-only desktop overview."
    output_path = str(output_root)

    python_path = str(Path(sys.executable).resolve())
    python_ready = Path(python_path).exists()
    raco_headless_status = _status_from_prereq("raco_headless")
    raco_headless_detail = _detail_from_prereq("raco_headless")
    raco_headless_probe = _probe_path_from_prereq("raco_headless")
    raco_gui_status = _status_from_prereq("raco_gui")
    raco_gui_detail = _detail_from_prereq("raco_gui")
    raco_gui_probe = _probe_path_from_prereq("raco_gui")

    items = [
        _item(
            key="python_backend",
            category="Python backend",
            label="Python backend",
            state="available" if python_ready else "missing",
            summary=(
                "The shell has a concrete Python executable available for backend commands."
                if python_ready
                else "The shell does not have a working Python executable path for backend commands."
            ),
            path=python_path,
            next_action="Use the bundled environment or launch the shell with --python pointing at a working interpreter.",
        ),
        _item(
            key="sg_preflight_import",
            category="Python backend",
            label="sg_preflight import",
            state="available" if sg_module_spec is not None else "blocked",
            summary=(
                "The shared SG Preflight backend module can be imported by the active interpreter."
                if sg_module_spec is not None
                else "The active interpreter cannot import the shared SG Preflight backend module."
            ),
            path=sg_module_path or "sg_preflight",
            next_action="Install the workspace package into the active interpreter or switch the shell to the bundled environment.",
        ),
        _item(
            key="mirror_root",
            category="SG mirror",
            label="repositories/trunk mirror",
            state="available" if _ready_from_prereq("mirror_root") else "missing",
            summary=(
                "The mirrored Seriengrafik working tree is available locally."
                if _ready_from_prereq("mirror_root")
                else "The mirrored Seriengrafik working tree is missing locally."
            ),
            path=str(readiness.get("mirror_root", {}).get("path", "")),
            next_action="Sync the working mirror into repositories\\trunk before relying on SG-side checker coverage.",
        ),
        _item(
            key="checker_root",
            category="SG mirror",
            label=".pdx/checkers",
            state="available" if _ready_from_prereq("checker_root") else "missing",
            summary=(
                "The mirrored SG checker root is available."
                if _ready_from_prereq("checker_root")
                else "The mirrored SG checker root is missing."
            ),
            path=str(readiness.get("checker_root", {}).get("path", "")),
            next_action="Mirror the .pdx/checkers folder from Seriengrafik into the local workspace.",
        ),
        _item(
            key="execute_checks",
            category="SG mirror",
            label="executeChecks.py",
            state="available" if _ready_from_prereq("execute_checks") else "missing",
            summary=(
                "The main SG checker dispatcher is available locally."
                if _ready_from_prereq("execute_checks")
                else "The main SG checker dispatcher is missing locally."
            ),
            path=str(readiness.get("execute_checks", {}).get("path", "")),
            next_action="Mirror executeChecks.py into .pdx/checkers so repo and stack actions can stay truthful.",
        ),
        _item(
            key="unused_resource_checker",
            category="SG mirror",
            label="printNotUsedResources.py",
            state="available" if _ready_from_prereq("unused_resource_checker") else "missing",
            summary=(
                "The SG unused-resource checker is available locally."
                if _ready_from_prereq("unused_resource_checker")
                else "The SG unused-resource checker is missing locally."
            ),
            path=str(readiness.get("unused_resource_checker", {}).get("path", "")),
            next_action="Mirror printNotUsedResources.py into .pdx/checkers so unused-resource scans stay wired.",
        ),
        _item(
            key="delivery_checklist_assets",
            category="SG mirror",
            label="deliveryChecklist assets",
            state=delivery_state,
            summary=delivery_summary,
            path=str(readiness.get("delivery_checklist_tool", {}).get("path", "")),
            next_action="Keep this surface as a readiness bridge until the BMW-owned delivery execution path is actually available.",
        ),
        _item(
            key="raco_headless",
            category="Local tools",
            label="RaCoHeadless",
            state=(
                "available"
                if raco_headless_status == "available"
                else "partial"
                if raco_headless_status == "incompatible"
                else "missing"
            ),
            summary=(
                "RaCoHeadless is available for local scene-side readiness checks."
                if raco_headless_status == "available"
                else (
                    "RaCoHeadless exists locally, but the configured build cannot open the representative SG scene here."
                    + (f" {raco_headless_detail}" if raco_headless_detail else "")
                )
                if raco_headless_status == "incompatible"
                else "RaCoHeadless is not configured on this machine yet."
            ),
            path=str(readiness.get("raco_headless", {}).get("path", "")),
            next_action=(
                "Point SG_RACO_HEADLESS at a Ramses Composer build that can open the current SG scene feature level."
                + (f" Probe scene: {raco_headless_probe}" if raco_headless_probe else "")
            )
            if raco_headless_status == "incompatible"
            else "Set SG_RACO_HEADLESS or install the standard Ramses Composer build on this machine.",
        ),
        _item(
            key="raco_gui",
            category="Local tools",
            label="Ramses Composer / RaCo GUI",
            state=(
                "available"
                if raco_gui_status == "available" and raco_headless_status != "incompatible"
                else "partial"
                if raco_gui_status == "available"
                else "missing"
            ),
            summary=(
                "A Ramses Composer GUI executable is available for first-pass open-in-RaCo adapters."
                if raco_gui_status == "available" and raco_headless_status != "incompatible"
                else (
                    "A Ramses Composer GUI executable is available for manual open-in-RaCo adapters, but representative scene compatibility is still only partial because RaCoHeadless is not green yet."
                    + (f" {raco_headless_detail}" if raco_headless_detail else "")
                )
                if raco_gui_status == "available"
                else "No Ramses Composer GUI executable is configured locally yet."
            ),
            path=str(readiness.get("raco_gui", {}).get("path", "")),
            next_action=(
                "Point SG_RACO_HEADLESS at a Ramses Composer build that can open the current SG scene feature level, then keep the GUI adapter for manual review."
                + (f" Probe scene: {raco_headless_probe or raco_gui_probe}" if (raco_headless_probe or raco_gui_probe) else "")
            )
            if raco_gui_status == "available" and raco_headless_status == "incompatible"
            else "Set SG_RACO_GUI or install the standard Ramses Composer GUI build before exposing open-in-RaCo adapters.",
        ),
        _item(
            key="blender_executable",
            category="Local tools",
            label="Blender executable",
            state="available" if _ready_from_prereq("blender_executable") else "missing",
            summary=(
                "A Blender executable path is available for local opening/adapter flows."
                if _ready_from_prereq("blender_executable")
                else "No Blender executable path is configured locally yet."
            ),
            path=str(readiness.get("blender_executable", {}).get("path", "")),
            next_action="Set SG_BLENDER_EXE or install the standard Blender build before adding Blender-open adapters.",
        ),
        _item(
            key="bmw_models_repo",
            category="BMW / External",
            label="BMW digital-3d-car repo",
            state="available" if _ready_from_prereq("bmw_models_repo") else "blocked",
            summary=(
                "The BMW models repository is available locally."
                if _ready_from_prereq("bmw_models_repo")
                else "The BMW models repository is still blocked on access or local checkout."
            ),
            path=str(readiness.get("bmw_models_repo", {}).get("path", "")),
            next_action="Set SG_CARMODELS_REPO once access exists and the BMW repository is cloned locally.",
        ),
        _item(
            key="bmw_helper_scripts",
            category="BMW / External",
            label="BMW helper scripts",
            state=bmw_scripts_state,
            summary=bmw_scripts_summary,
            path=str(readiness.get("bmw_test_main_script", {}).get("path", "")),
            next_action="Treat BMW smoke as blocked until the repo, helper scripts, and target mapping are all present locally.",
        ),
        _item(
            key="jira_qa_hero",
            category="BMW / External",
            label="Jira / QA Hero",
            state="blocked",
            summary="Direct Jira or QA Hero integration is not connected here yet. The current product surface is copy export, not API automation.",
            path="copy exports only",
            next_action="Keep using the SG-side copy exports until the real ticket integration path is agreed and available.",
        ),
        _item(
            key="output_write_access",
            category="Operator output",
            label="out/operator-ui write access",
            state=output_state,
            summary=output_summary,
            path=output_path,
            next_action="Ensure the workspace output folder stays writable so evidence, screenshots, and action records can be persisted.",
        ),
    ]
    return items


def _state_counts(items: list[DesktopEnvironmentItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        state = item.state.strip().lower() or "unknown"
        counts[state] = counts.get(state, 0) + 1
    return counts


def desktop_operator_overview(
    workspace: Path | None = None,
    *,
    profile_id: str = "",
    profiles: list[RunProfile] | None = None,
) -> DesktopOperatorOverview:
    root = workspace_root(workspace)
    ready_profiles = _ready_profiles(root, profiles)
    normalized_profile = profile_id.strip().lower()
    selected_profile = next(
        (
            profile
            for profile in ready_profiles
            if profile.profile_id.strip().lower() == normalized_profile
        ),
        ready_profiles[0] if ready_profiles else None,
    )
    selected_profile_id = selected_profile.profile_id if selected_profile is not None else ""
    recommended_action_id = (
        f"qa_stack__{selected_profile_id.lower()}" if selected_profile_id else ""
    )

    actions = (
        desktop_actions_for_profile(selected_profile_id, root, profiles=ready_profiles)
        if selected_profile_id
        else []
    )
    blockers = (
        desktop_blocker_items(selected_profile_id, root, profiles=ready_profiles)
        if selected_profile_id
        else []
    )
    manual_cards = (
        desktop_manual_cards(selected_profile_id, root, profiles=ready_profiles)
        if selected_profile_id
        else []
    )
    environment_items = desktop_environment_doctor(root)
    recent_action_items = (
        desktop_recent_actions(root, profile_id=selected_profile_id, limit=1)
        if selected_profile_id
        else []
    )
    recent_run_items = (
        desktop_recent_runs(root, profile_id=selected_profile_id, limit=1)
        if selected_profile_id
        else []
    )

    ready_action_count = sum(1 for action in actions if action.ready)
    blocked_action_count = len(actions) - ready_action_count
    blocker_count = sum(
        1
        for item in blockers
        if item.state.strip().lower() not in {"available", "covered"}
    )
    latest_action = recent_action_items[0] if recent_action_items else None
    latest_run = recent_run_items[0] if recent_run_items else None

    if selected_profile_id:
        summary_line = (
            f"{selected_profile_id}: {ready_action_count}/{len(actions)} native actions available; "
            f"{blocker_count} blocker card(s); {len(manual_cards)} manual card(s)."
        )
        if latest_action is not None:
            summary_line += f" Latest action: {latest_action.status}."
        export_size_analysis = read_export_size_analysis(
            profile_id=selected_profile_id,
            workspace=root,
            latest=True,
        )
    else:
        summary_line = "No available SG profile is available for the native operator overview."
        export_size_analysis = {}

    export_size_analysis_summary = str(export_size_analysis.get("note", "")).strip()
    if not export_size_analysis_summary:
        export_size_analysis_summary = str(export_size_analysis.get("summary", "")).strip()

    return DesktopOperatorOverview(
        workspace_root=str(root),
        generated_at_utc=utc_now(),
        recommended_profile_id=selected_profile_id,
        recommended_action_id=recommended_action_id,
        ready_profile_count=len(ready_profiles),
        action_count=len(actions),
        ready_action_count=ready_action_count,
        blocked_action_count=blocked_action_count,
        blocker_count=blocker_count,
        manual_card_count=len(manual_cards),
        environment_state_counts=_state_counts(environment_items),
        latest_action_run_id=latest_action.run_id if latest_action is not None else "",
        latest_action_status=latest_action.status if latest_action is not None else "",
        latest_run_id=latest_run.run_id if latest_run is not None else "",
        latest_run_status=latest_run.status if latest_run is not None else "",
        summary_line=summary_line,
        export_size_analysis_status=str(export_size_analysis.get("status", "no_profile")).strip(),
        export_size_analysis_variant_count=int(export_size_analysis.get("variant_count", 0) or 0),
        export_size_analysis_workbook_date=str(export_size_analysis.get("workbook_date", "")).strip(),
        export_size_analysis_summary=export_size_analysis_summary,
        export_size_analysis_workbook_path=str(export_size_analysis.get("workbook_path", "")).strip(),
    )


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
            label="Delivery checklist note",
            state=str(delivery.get("state", "blocked")),
            summary=str(delivery.get("summary", "The delivery-checklist bridge state is not available.")),
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
            "Delivery Checklist",
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
            lambda: build_cross_car_comparison(workspace=root, left_profile="G70", right_profile="G65"),
        ),
        _safe_item(
            "daily-digest",
            "Daily Digest",
            lambda: build_latest_daily_digest(workspace=root),
        ),
        _safe_item(
            "team-digest-board",
            "Team Digest Board",
            lambda: build_team_daily_digest_board(workspace=root, profiles=(normalized_profile, "G70", "G65")),
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


def _summary_lines(summary: dict[str, Any] | None) -> tuple[str, ...]:
    if not isinstance(summary, dict):
        return ()
    return tuple(str(line).strip() for line in summary.get("lines", []) if str(line).strip())


def _checker_evidence(summary: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(summary, dict):
        return {}
    evidence = summary.get("checker_evidence")
    return evidence if isinstance(evidence, dict) else {}


def _coerce_line_number(raw: Any) -> int | None:
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _desktop_evidence_items(evidence: dict[str, Any]) -> tuple[DesktopEvidenceItem, ...]:
    raw_items = evidence.get("top_paths", []) or evidence.get("affected_files", [])
    items: list[DesktopEvidenceItem] = []
    for raw in raw_items[:5]:
        if not isinstance(raw, dict):
            continue
        path = str(raw.get("path", "")).strip()
        if not path:
            continue
        items.append(
            DesktopEvidenceItem(
                path=path,
                checker=str(raw.get("checker", "")).strip(),
                message=str(raw.get("message", "")).strip(),
                severity=str(raw.get("severity", "warning")).strip(),
                line=_coerce_line_number(raw.get("line")),
                source_kind=str(raw.get("source_kind", "")).strip(),
            )
        )
    return tuple(items)


def _artifact_items(record: ActionRecord) -> tuple[DesktopArtifactItem, ...]:
    items: list[DesktopArtifactItem] = []
    built_in = (
        ("Action log", str(record.paths.get("log", "")).strip()),
        ("Action summary JSON", str(record.paths.get("summary_json", "")).strip()),
        ("Action summary Markdown", str(record.paths.get("summary_md", "")).strip()),
        ("Action record", str(record.paths.get("action_record", "")).strip()),
    )
    for label, path in built_in:
        if path:
            items.append(DesktopArtifactItem(label=label, path=path))
    for raw in record.artifacts:
        if not isinstance(raw, dict):
            continue
        path = str(raw.get("path", "")).strip()
        if not path:
            continue
        items.append(
            DesktopArtifactItem(
                label=str(raw.get("label", "Artifact")).strip() or "Artifact",
                path=path,
            )
        )
    return _dedupe_artifact_items(items)


def _manual_evidence_copy_lines(record: ActionRecord) -> tuple[str, ...]:
    lines: list[str] = []
    for raw in record.manual_evidence[:6]:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label", "Manual evidence")).strip() or "Manual evidence"
        path = str(raw.get("path", "")).strip()
        if not path:
            continue
        lines.append(f"- {label}: {path}")
    return tuple(lines)


def _tail_text(path: str, limit: int = 30) -> str:
    if not path:
        return ""
    candidate = Path(path)
    if not candidate.exists():
        return ""
    lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-limit:]).strip()


def _latest_markdown_text(run_record: RunRecord | None) -> str:
    if run_record is None:
        return ""
    candidate = Path(run_record.paths.get("markdown_report", ""))
    if not candidate.exists():
        return ""
    return candidate.read_text(encoding="utf-8", errors="replace").strip()


def _primary_evidence_line(items: tuple[DesktopEvidenceItem, ...]) -> str:
    if not items:
        return ""
    first = items[0]
    line = f" line {first.line}" if first.line is not None else ""
    checker = f" [{first.checker}]" if first.checker else ""
    message = f" - {first.message}" if first.message else ""
    return f"{first.path}{line}{checker}{message}"


def _workflow_stage_label(context: dict[str, Any] | None) -> str:
    if not isinstance(context, dict):
        return ""
    return str(context.get("workflow_stage_label", "")).strip()


def _decision_title(summary: dict[str, Any] | None) -> str:
    counts = summary if isinstance(summary, dict) else {}
    errors = int(counts.get("errors", 0) or 0)
    warnings = int(counts.get("warnings", 0) or 0)
    if errors > 0:
        return "Needs action before this can be treated as healthy."
    if warnings > 0:
        return "Usable signal, but still needs triage."
    return "Clean run with no findings."


def _counts_line(summary: dict[str, Any] | None) -> str:
    counts = summary if isinstance(summary, dict) else {}
    return (
        f"Counts: {int(counts.get('errors', 0) or 0)} errors, "
        f"{int(counts.get('warnings', 0) or 0)} warnings, "
        f"{int(counts.get('info', 0) or 0)} info, "
        f"{int(counts.get('total', 0) or 0)} total"
    )


def _report_grouped_items(run_record: RunRecord | None) -> list[dict[str, Any]]:
    if run_record is None:
        return []
    report = load_run_report(run_record)
    if report is None:
        return []
    config = load_run_config(run_record)
    presentation = build_report_presentation(report, config)
    raw_grouped = presentation.get("grouped_findings", [])
    return [dict(item) for item in raw_grouped if isinstance(item, dict)]


def _grouped_finding_lines(grouped_items: list[dict[str, Any]], limit: int = 3) -> tuple[str, ...]:
    lines: list[str] = []
    for item in grouped_items[:limit]:
        lines.append(
            f"[{str(item.get('severity', '')).upper()}] "
            f"{item.get('pack', '')} / {item.get('code', '')} x{item.get('count', 0)}: "
            f"{item.get('message', '')}"
        )
        owner = str(item.get("owner", "")).strip()
        action = str(item.get("action", "")).strip()
        locations = item.get("locations", [])
        if owner:
            lines.append(f"Owner: {owner}")
        if action:
            lines.append(f"Action: {action}")
        if isinstance(locations, list) and locations:
            lines.append(
                "Examples: " + ", ".join(str(location).strip() for location in locations[:3] if str(location).strip())
            )
    return tuple(line for line in lines if line.strip())


def _dedupe_artifact_items(items: list[DesktopArtifactItem]) -> tuple[DesktopArtifactItem, ...]:
    seen: set[tuple[str, str]] = set()
    unique: list[DesktopArtifactItem] = []
    for item in items:
        label = str(item.label).strip()
        path = str(item.path).strip()
        if not path:
            continue
        key = (label, path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return tuple(unique)


def _run_artifact_items(run_record: RunRecord) -> tuple[DesktopArtifactItem, ...]:
    labels = (
        ("Output root", str(run_record.paths.get("output_root", "")).strip()),
        ("HTML report", str(run_record.paths.get("html_report", "")).strip()),
        ("Markdown report", str(run_record.paths.get("markdown_report", "")).strip()),
        ("JSON report", str(run_record.paths.get("json_report", "")).strip()),
        ("Bundle root", str(run_record.paths.get("bundle", "")).strip()),
        ("Bundle metadata", str(run_record.paths.get("bundle_metadata", "")).strip()),
        ("Project manifest", str(run_record.paths.get("project_manifest", "")).strip()),
        ("Run record", str(run_record.paths.get("run_record", "")).strip()),
        ("Config", str(run_record.config_path).strip()),
        ("Project root", str(run_record.project_root).strip()),
    )
    items = [DesktopArtifactItem(label=label, path=path) for label, path in labels if path]
    return _dedupe_artifact_items(items)


def _run_source_items(run_record: RunRecord) -> tuple[DesktopArtifactItem, ...]:
    items: list[DesktopArtifactItem] = []
    for key, path in sorted(run_record.source_paths.items()):
        cleaned_path = str(path).strip()
        if not cleaned_path:
            continue
        label = str(key).replace("_", " ").strip().title() or "Source file"
        items.append(DesktopArtifactItem(label=label, path=cleaned_path))
    return _dedupe_artifact_items(items)


def _quick_update_text(
    *,
    heading: str,
    profile_id: str,
    workflow_stage_label: str,
    title: str,
    counts_line: str,
    grouped_lines: tuple[str, ...],
    primary_line: str,
    html_report: str,
    project_root: str,
    manual_evidence_lines: tuple[str, ...] = (),
) -> str:
    lines = [
        f"{heading} - {profile_id}",
        f"Result: {title}",
        counts_line,
    ]
    if workflow_stage_label:
        lines.insert(1, f"Workflow stage: {workflow_stage_label}")
    if primary_line:
        lines.extend(["", f"Open first: {primary_line}"])
    if grouped_lines:
        lines.extend(["", "Top findings:", *grouped_lines[:4]])
    if manual_evidence_lines:
        lines.extend(["", "Manual evidence attached:", *manual_evidence_lines[:4]])
    lines.extend(["", "Open if needed:"])
    if html_report:
        lines.append(f"HTML report: {html_report}")
    if project_root:
        lines.append(f"Project root: {project_root}")
    return "\n".join(line for line in lines if str(line).strip()).strip()


def _export_copy_items(
    *,
    profile_id: str,
    workflow_stage_label: str,
    title: str,
    counts_line: str,
    grouped_lines: tuple[str, ...],
    primary_line: str,
    html_report: str,
    markdown_report: str,
    project_root: str,
    output_root: str,
    manual_evidence_lines: tuple[str, ...] = (),
) -> tuple[DesktopCopyItem, ...]:
    primary_problem = primary_line or (grouped_lines[0] if grouped_lines else "No deterministic finding is currently blocking the run.")
    quick_update = _quick_update_text(
        heading="SG Preflight update",
        profile_id=profile_id,
        workflow_stage_label=workflow_stage_label,
        title=title,
        counts_line=counts_line,
        grouped_lines=grouped_lines,
        primary_line=primary_line,
        html_report=html_report,
        project_root=project_root,
        manual_evidence_lines=manual_evidence_lines,
    )
    implementation_lines = [
        f"Jira implementation update - {profile_id}",
        f"Result: {title}",
        counts_line,
        "",
        "Top findings:",
        *(grouped_lines[:4] or ("No grouped findings were raised in this run.",)),
        "",
        "Evidence:",
        f"- HTML report: {html_report}",
        f"- Output root: {output_root}",
    ]
    positive_lines = [
        f"Jira positive test note - {profile_id}",
        f"Status: {'clean deterministic SG-side run.' if 'Clean run' in title else 'run completed but is not clean; use the negative note for current issues.'}",
        counts_line,
        "",
        "Evidence attached:",
        f"- HTML report: {html_report}",
        f"- Output root: {output_root}",
    ]
    negative_lines = [
        f"Jira negative test note - {profile_id}",
        f"Primary issue: {primary_problem}",
        counts_line,
        "",
        "Top findings:",
        *(grouped_lines[:4] or ("No grouped findings were raised in this run.",)),
        "",
        "Evidence attached:",
        f"- HTML report: {html_report}",
        f"- Output root: {output_root}",
    ]
    qa_hero_lines = [
        f"QA Hero note - {profile_id}",
        f"Result: {title}",
        f"Primary issue: {primary_problem}",
        "",
        "Evidence:",
        f"- HTML report: {html_report}",
        f"- Markdown report: {markdown_report}",
    ]
    pre_delivery_lines = [
        f"Pre-delivery summary - {profile_id}",
        f"Result: {title}",
        counts_line,
        f"Primary issue: {primary_problem}",
        "",
        "Evidence available:",
        f"- HTML report: {html_report}",
        f"- Markdown report: {markdown_report}",
        f"- Output root: {output_root}",
    ]
    delivery_doc_lines = [
        f"Delivery-doc snippet - {profile_id}",
        f"- Result: {title}",
        f"- {counts_line}",
        f"- Primary issue: {primary_problem}",
        f"- Evidence: {html_report}",
    ]
    if manual_evidence_lines:
        implementation_lines.extend(["", "Manual evidence attached:", *manual_evidence_lines[:4]])
        positive_lines.extend(["", "Manual evidence attached:", *manual_evidence_lines[:4]])
        negative_lines.extend(["", "Manual evidence attached:", *manual_evidence_lines[:4]])
        qa_hero_lines.extend(["", "Manual evidence attached:", *manual_evidence_lines[:4]])
        pre_delivery_lines.extend(["", "Manual evidence attached:", *manual_evidence_lines[:4]])
        delivery_doc_lines.extend(["- Manual evidence:", *manual_evidence_lines[:4]])
    if workflow_stage_label:
        implementation_lines.insert(1, f"Workflow stage: {workflow_stage_label}")
        positive_lines.insert(1, f"Workflow stage: {workflow_stage_label}")
        negative_lines.insert(1, f"Workflow stage: {workflow_stage_label}")
        qa_hero_lines.insert(1, f"Workflow stage: {workflow_stage_label}")
        pre_delivery_lines.insert(1, f"Workflow stage: {workflow_stage_label}")
        delivery_doc_lines.insert(1, f"- Workflow stage: {workflow_stage_label}")

    handoff = _load_text_path(markdown_report) or quick_update
    items = (
        DesktopCopyItem(key="jira", label="Copy Jira note", text="\n".join(implementation_lines).strip()),
        DesktopCopyItem(key="jira_positive", label="Copy Jira positive test note", text="\n".join(positive_lines).strip()),
        DesktopCopyItem(key="jira_negative", label="Copy Jira negative test note", text="\n".join(negative_lines).strip()),
        DesktopCopyItem(key="qa_hero", label="Copy QA Hero note", text="\n".join(qa_hero_lines).strip()),
        DesktopCopyItem(key="pre_delivery", label="Copy pre-delivery summary", text="\n".join(pre_delivery_lines).strip()),
        DesktopCopyItem(key="delivery_doc", label="Copy delivery-doc snippet", text="\n".join(delivery_doc_lines).strip()),
        DesktopCopyItem(key="quick_update", label="Copy quick update", text=quick_update),
        DesktopCopyItem(key="handoff", label="Copy full handoff", text=handoff),
    )
    return tuple(item for item in items if item.text.strip())


def _load_text_path(path_value: str) -> str:
    if not path_value:
        return ""
    candidate = Path(path_value)
    if not candidate.exists() or not candidate.is_file():
        return ""
    return candidate.read_text(encoding="utf-8", errors="replace").strip()


def _load_visual_review_payload(record: ActionRecord) -> dict[str, Any]:
    candidate = Path(str(record.paths.get("visual_review_prep_json", "")).strip())
    if not candidate.exists() or not candidate.is_file():
        return {}
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _visual_review_copy_item(record: ActionRecord) -> DesktopCopyItem | None:
    payload = _load_visual_review_payload(record)
    if not payload:
        return None

    profile_id = str(payload.get("profile_id", record.profile_id or record.action_id)).strip()
    changelog_heading = str(payload.get("changelog_heading", "")).strip()
    changelog_focus = [str(item).strip() for item in payload.get("changelog_focus_lines", []) if str(item).strip()]
    priority_screenshots = [str(item).strip() for item in payload.get("priority_screenshots", []) if str(item).strip()]
    raco_scene_path = str(payload.get("raco_scene_path", "")).strip()
    blender_workfile_path = str(payload.get("blender_workfile_path", "")).strip()
    screenshot_root = str(payload.get("screenshot_root", "")).strip()

    lines = [f"Visual review note - {profile_id}"]
    if changelog_heading:
        lines.append(f"Changelog focus: {changelog_heading}")
    lines.append("")
    lines.append("Manual review prep:")
    if changelog_focus:
        lines.extend(f"- {line}" for line in changelog_focus[:6])
    else:
        lines.append("- No changelog focus lines were detected.")
    if priority_screenshots:
        lines.append("")
        lines.append("Priority screenshot baselines:")
        lines.extend(f"- {name}" for name in priority_screenshots[:8])
    if screenshot_root:
        lines.append(f"- Screenshot baseline root: {screenshot_root}")
    if raco_scene_path or blender_workfile_path:
        lines.append("")
        lines.append("Tool entry points:")
        if raco_scene_path:
            lines.append(f"- RaCo scene: {raco_scene_path}")
        if blender_workfile_path:
            lines.append(f"- Blender workfile: {blender_workfile_path}")
    lines.extend(
        [
            "",
            "Checklist:",
            "- Project changelog reviewed: [ ]",
            "- Screenshot baseline set reviewed: [ ]",
            "- Representative RaCo scene opened: [ ]",
            "- Representative Blender workfile opened: [ ]",
            "- Findings documented with evidence: [ ]",
            "- Notes:",
            "- ",
        ]
    )
    return DesktopCopyItem(
        key="visual_review",
        label="Copy visual review note",
        text="\n".join(lines).strip(),
    )


def _copy_items(
    record: ActionRecord,
    items: tuple[DesktopEvidenceItem, ...],
    run_record: RunRecord | None,
) -> tuple[DesktopCopyItem, ...]:
    title = str(record.summary.get("title", record.label)) if isinstance(record.summary, dict) else record.label
    primary_line = _primary_evidence_line(items)
    manual_evidence_lines = _manual_evidence_copy_lines(record)
    if run_record is not None:
        grouped_items = _report_grouped_items(run_record)
        grouped_lines = _grouped_finding_lines(grouped_items)
        export_items = list(_export_copy_items(
            profile_id=record.profile_id or record.action_id,
            workflow_stage_label=_workflow_stage_label(run_record.context),
            title=title,
            counts_line=_counts_line(run_record.summary),
            grouped_lines=grouped_lines,
            primary_line=primary_line,
            html_report=str(run_record.paths.get("html_report", "")).strip(),
            markdown_report=str(run_record.paths.get("markdown_report", "")).strip(),
            project_root=str(run_record.project_root).strip(),
            output_root=str(run_record.paths.get("output_root", "")).strip(),
            manual_evidence_lines=manual_evidence_lines,
        ))
        visual_review_item = _visual_review_copy_item(record)
        if visual_review_item is not None:
            export_items.append(visual_review_item)
        return tuple(item for item in export_items if item.text.strip())

    summary_lines = _summary_lines(record.summary)
    quick_update = _quick_update_text(
        heading="SG action update",
        profile_id=record.profile_id or record.action_id,
        workflow_stage_label="",
        title=title,
        counts_line=summary_lines[0] if summary_lines else f"Status: {record.status}",
        grouped_lines=summary_lines[1:4],
        primary_line=primary_line,
        html_report="",
        project_root=record.project_root,
        manual_evidence_lines=manual_evidence_lines,
    )
    fallback_items = [
        item
        for item in (
            DesktopCopyItem(key="jira", label="Copy Jira note", text=quick_update),
            DesktopCopyItem(key="qa_hero", label="Copy QA Hero note", text=quick_update),
            DesktopCopyItem(key="quick_update", label="Copy quick update", text=quick_update),
            DesktopCopyItem(key="handoff", label="Copy full handoff", text=quick_update),
        )
        if item.text.strip()
    ]
    visual_review_item = _visual_review_copy_item(record)
    if visual_review_item is not None:
        fallback_items.append(visual_review_item)
    return tuple(fallback_items)


def _action_grouped_lines(
    record: ActionRecord,
    summary: dict[str, Any],
    evidence_items: tuple[DesktopEvidenceItem, ...],
) -> tuple[str, ...]:
    lines: list[str] = []
    for item in evidence_items[:4]:
        checker = f" [{item.checker}]" if item.checker else ""
        message = f": {item.message}" if item.message else ""
        lines.append(f"[{item.severity.upper()}]{checker} {item.path}{message}".strip())

    for line in _summary_lines(summary):
        cleaned = str(line).strip()
        if not cleaned:
            continue
        if cleaned in lines:
            continue
        lines.append(cleaned)
        if len(lines) >= 6:
            break

    if record.error_message.strip():
        lines.append(record.error_message.strip())
    return tuple(lines[:6])


def _action_source_items(items: tuple[DesktopEvidenceItem, ...]) -> tuple[DesktopArtifactItem, ...]:
    artifacts = [
        DesktopArtifactItem(
            label=item.checker or f"Source {index + 1}",
            path=item.path,
        )
        for index, item in enumerate(items)
        if item.path.strip()
    ]
    return _dedupe_artifact_items(artifacts)


def _desktop_run_snapshot_from_action_record(
    record: ActionRecord,
    root: Path,
) -> DesktopRunSnapshot:
    summary = record.summary if isinstance(record.summary, dict) else {}
    evidence = _checker_evidence(summary)
    evidence_items = _desktop_evidence_items(evidence)
    latest_run = _latest_run_record(record.profile_id, root) if record.profile_id else None
    progress = record.progress if isinstance(record.progress, dict) else {}
    progress_label = str(progress.get("label", "")).strip()
    progress_detail = str(progress.get("detail", "")).strip()
    current_step = str(progress.get("step_key", "")).strip()
    step_details = progress.get("step_details", []) if isinstance(progress.get("step_details"), list) else []
    current_meta: dict[str, Any] = {}
    for item in step_details:
        if isinstance(item, dict) and str(item.get("key", "")).strip() == current_step:
            current_meta = dict(item.get("meta", {})) if isinstance(item.get("meta"), dict) else {}
            break

    summary_title = str(summary.get("title", record.label)).strip() or record.label
    summary_lines: list[str] = []
    if progress_label:
        summary_lines.append(progress_label)
    if progress_detail:
        summary_lines.append(progress_detail)
    if not summary_lines:
        summary_lines.append(f"Status: {record.status}")
    for line in _summary_lines(summary):
        cleaned = str(line).strip()
        if cleaned and cleaned not in summary_lines:
            summary_lines.append(cleaned)
        if len(summary_lines) >= 6:
            break

    notes = [str(note).strip() for note in record.notes if str(note).strip()]
    notes.extend(_manual_evidence_copy_lines(record))
    if record.error_message.strip():
        notes.append(record.error_message.strip())

    profile_label = record.profile_id or summary_title
    if latest_run is not None and latest_run.profile_label.strip():
        profile_label = latest_run.profile_label

    return DesktopRunSnapshot(
        run_id=record.run_id,
        profile_id=record.profile_id,
        profile_label=profile_label,
        status=record.status,
        initializing=False,
        created_at_utc=record.created_at_utc,
        workflow_stage_label=progress_label,
        summary_title=summary_title,
        current_command=str(current_meta.get("command", record.command_preview)).strip(),
        log_path=str(record.paths.get("log", "")).strip(),
        log_tail=_tail_text(str(record.paths.get("log", "")).strip()),
        output_root=str(record.paths.get("output_root", "")).strip(),
        project_root=str(record.project_root).strip(),
        error_message=str(record.error_message).strip(),
        exit_code=int(record.exit_code or 0),
        summary_lines=tuple(summary_lines[:6]),
        grouped_lines=_action_grouped_lines(record, summary, evidence_items),
        notes=tuple(notes[:8]),
        packs=tuple(str(item).strip() for item in summary.get("packs", []) if str(item).strip()),
        artifacts=_artifact_items(record),
        source_files=_action_source_items(evidence_items),
        copy_items=_copy_items(record, evidence_items, None),
    )


def desktop_run_snapshot(
    run_id_or_path: str | Path,
    workspace: Path | None = None,
) -> DesktopRunSnapshot:
    root = workspace_root(workspace)
    try:
        run_record = load_run_record(run_id_or_path, root)
    except (FileNotFoundError, OSError, ValueError) as run_error:
        try:
            action_record = load_action_record(run_id_or_path, root)
        except (FileNotFoundError, OSError, ValueError):
            reference = str(run_id_or_path).strip()
            if _looks_like_transient_run_reference(reference):
                return _initializing_run_snapshot(reference)
            raise run_error
        return _desktop_run_snapshot_from_action_record(action_record, root)

    grouped_items = _report_grouped_items(run_record)
    grouped_lines = _grouped_finding_lines(grouped_items, limit=4)
    summary_title = _decision_title(run_record.summary)
    summary_lines = [
        f"Result: {summary_title}",
        _counts_line(run_record.summary),
    ]
    stage_label = _workflow_stage_label(run_record.context)
    if stage_label:
        summary_lines.insert(1, f"Workflow stage: {stage_label}")
    if run_record.packs:
        summary_lines.append("Packs: " + ", ".join(run_record.packs))

    return DesktopRunSnapshot(
        run_id=run_record.run_id,
        profile_id=run_record.profile_id,
        profile_label=run_record.profile_label,
        status=run_record.status,
        initializing=False,
        created_at_utc=run_record.created_at_utc,
        workflow_stage_label=stage_label,
        summary_title=summary_title,
        current_command="",
        log_path="",
        log_tail="",
        output_root=str(run_record.paths.get("output_root", "")).strip(),
        project_root=str(run_record.project_root).strip(),
        error_message="",
        exit_code=0,
        summary_lines=tuple(summary_lines),
        grouped_lines=grouped_lines,
        notes=tuple(str(note).strip() for note in run_record.notes if str(note).strip()),
        packs=tuple(run_record.packs),
        artifacts=_run_artifact_items(run_record),
        source_files=_run_source_items(run_record),
        copy_items=_export_copy_items(
            profile_id=run_record.profile_id,
            workflow_stage_label=stage_label,
            title=summary_title,
            counts_line=_counts_line(run_record.summary),
            grouped_lines=grouped_lines,
            primary_line="",
            html_report=str(run_record.paths.get("html_report", "")).strip(),
            markdown_report=str(run_record.paths.get("markdown_report", "")).strip(),
            project_root=str(run_record.project_root).strip(),
            output_root=str(run_record.paths.get("output_root", "")).strip(),
        ),
    )


def _looks_like_transient_run_reference(reference: str) -> bool:
    normalized = reference.strip().replace("/", "\\").lower()
    if not normalized:
        return False
    if "\\out\\operator-ui\\" in normalized:
        return True
    try:
        uuid.UUID(reference.strip())
        return True
    except (ValueError, AttributeError):
        return False


def _initializing_run_snapshot(reference: str) -> DesktopRunSnapshot:
    summary_lines = (
        "Action record is initializing.",
        "The native shell is waiting for the nested action bundle to be written.",
    )
    notes = (
        "This is a transient operator-state refresh while a long-running action is still materializing its nested run bundle.",
        "Refresh again in a moment; the structured run snapshot should replace this placeholder automatically.",
    )
    return DesktopRunSnapshot(
        run_id=reference,
        profile_id="",
        profile_label="Initializing action record",
        status="queued",
        initializing=True,
        created_at_utc="",
        workflow_stage_label="Initializing action record",
        summary_title="Action record is initializing",
        current_command="",
        log_path="",
        log_tail="",
        output_root="",
        project_root="",
        error_message="",
        exit_code=0,
        summary_lines=summary_lines,
        grouped_lines=(),
        notes=notes,
        packs=(),
        artifacts=(),
        source_files=(),
        copy_items=(),
    )


def desktop_action_snapshot(
    run_id_or_path: str | Path,
    workspace: Path | None = None,
) -> DesktopActionSnapshot:
    root = workspace_root(workspace)
    record = load_action_record(run_id_or_path, root)
    summary = record.summary if isinstance(record.summary, dict) else {}
    evidence = _checker_evidence(summary)
    progress = record.progress if isinstance(record.progress, dict) else {}
    current_step = str(progress.get("step_key", "")).strip()
    current_detail = str(progress.get("detail", "")).strip()
    step_details = progress.get("step_details", []) if isinstance(progress.get("step_details"), list) else []
    current_meta: dict[str, Any] = {}
    for item in step_details:
        if isinstance(item, dict) and str(item.get("key", "")).strip() == current_step:
            current_meta = dict(item.get("meta", {})) if isinstance(item.get("meta"), dict) else {}
            break

    run_record = _latest_run_record(record.profile_id, root) if record.profile_id else None
    evidence_items = _desktop_evidence_items(evidence)
    return DesktopActionSnapshot(
        run_id=record.run_id,
        action_id=record.action_id,
        title=str(summary.get("title", record.label)).strip() or record.label,
        status=record.status,
        profile_id=record.profile_id,
        progress_percent=int(progress.get("percent", 0) or 0),
        progress_label=str(progress.get("label", record.status.title())).strip(),
        progress_detail=current_detail,
        current_command=str(current_meta.get("command", record.command_preview)).strip(),
        child_run_id=str(current_meta.get("child_run_id", "")).strip(),
        linked_run_id=(str(current_meta.get("child_run_id", "")).strip() or (run_record.run_id if run_record is not None else "")),
        workspace_root=str(record.workspace_root).strip(),
        project_root=str(record.project_root).strip(),
        output_root=str(record.paths.get("output_root", "")).strip(),
        error_message=str(record.error_message).strip(),
        exit_code=int(record.exit_code or 0),
        summary_lines=_summary_lines(summary),
        top_paths=evidence_items,
        manual_followups=tuple(str(item).strip() for item in evidence.get("manual_followups", []) if str(item).strip()),
        artifacts=_artifact_items(record),
        log_path=str(record.paths.get("log", "")).strip(),
        log_tail=_tail_text(str(record.paths.get("log", "")).strip()),
        latest_run_links=latest_run_links(record.profile_id, root) if record.profile_id else DesktopLinks(),
        copy_items=_copy_items(record, evidence_items, run_record),
        summary_only=bool(evidence.get("summary_only", not bool(evidence))),
    )


def latest_action_snapshot_for_profile(
    profile_id: str,
    workspace: Path | None = None,
    *,
    preferred_action_id: str = "",
) -> DesktopActionSnapshot | None:
    root = workspace_root(workspace)
    record = _latest_action_record(profile_id, root, preferred_action_id=preferred_action_id)
    if record is None and preferred_action_id:
        record = _latest_action_record(profile_id, root)
    if record is None:
        return None
    return desktop_action_snapshot(record.run_id, root)
