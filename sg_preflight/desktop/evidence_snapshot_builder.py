"""Assembles the desktop shell's operator-overview, run, and action snapshot payloads for the Qt Quick shell."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sg_preflight.export_size_analysis import read_export_size_analysis
from sg_preflight.profiles import RunProfile
from sg_preflight.qa_actions import ActionRecord, load_action_record
from sg_preflight.services import load_run_record, utc_now, workspace_root

from sg_preflight.desktop.evidence_action_listing import (
    _latest_action_record,
    _latest_run_record,
    _ready_profiles,
    desktop_actions_for_profile,
    desktop_blocker_items,
    desktop_manual_cards,
    desktop_recent_actions,
    desktop_recent_runs,
)
from sg_preflight.desktop.evidence_environment_doctor import _state_counts, desktop_environment_doctor
from sg_preflight.desktop.evidence_formatting import (
    DesktopArtifactItem,
    DesktopCopyItem,
    DesktopEvidenceItem,
    _action_grouped_lines,
    _action_source_items,
    _artifact_items,
    _checker_evidence,
    _copy_items,
    _counts_line,
    _decision_title,
    _desktop_evidence_items,
    _export_copy_items,
    _grouped_finding_lines,
    _manual_evidence_copy_lines,
    _report_grouped_items,
    _run_artifact_items,
    _run_source_items,
    _summary_lines,
    _tail_text,
    _workflow_stage_label,
)


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
