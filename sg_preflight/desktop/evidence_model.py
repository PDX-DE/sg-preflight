from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sg_preflight.profiles import RunProfile, list_run_profiles
from sg_preflight.qa_actions import ActionRecord, list_operator_actions, list_recent_action_records, load_action_record
from sg_preflight.reporting import build_report_presentation
from sg_preflight.services import (
    RunRecord,
    list_recent_run_records,
    load_run_config,
    load_run_record,
    load_run_report,
    prerequisite_status,
    qa_workflow_status,
    workspace_root,
)


PRIMARY_ACTION_TEMPLATE = (
    "qa_stack__{profile}",
    "repo_checker_profile__{profile}",
    "scene_check__{profile}",
    "unused_resources__{profile}",
    "delivery_checklist__{profile}",
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
    created_at_utc: str
    workflow_stage_label: str
    summary_title: str
    summary_lines: tuple[str, ...]
    grouped_lines: tuple[str, ...]
    notes: tuple[str, ...]
    packs: tuple[str, ...]
    artifacts: tuple[DesktopArtifactItem, ...]
    source_files: tuple[DesktopArtifactItem, ...]
    copy_items: tuple[DesktopCopyItem, ...]


def _ready_profiles(root: Path, profiles: list[RunProfile] | None = None) -> list[RunProfile]:
    live_profiles = profiles if profiles is not None else list_run_profiles(root)
    return [
        profile
        for profile in live_profiles
        if profile.project_root.exists() and profile.config_path.exists()
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
        state = "ready" if item.get("status") == "available" else "blocked"
        blocker = () if state == "ready" else (f"{label} is not available locally: {item.get('path', '')}",)
        return DesktopBlockerItem(
            key=key,
            label=label,
            state=state,
            summary=summary if state == "ready" else f"{summary} Missing on this machine.",
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
    readiness = {item["key"]: item for item in prerequisite_status(root)}
    workflow = {item["key"]: item for item in qa_workflow_status(root, live_profiles)}
    raco_ready = readiness.get("raco_headless", {}).get("status") == "available"
    delivery = workflow.get("delivery_checklist", {})
    bmw = workflow.get("bmw_screenshot_smoke", {})

    return [
        DesktopManualCard(
            key="blender_raco_compare",
            label="Blender vs RaCo review",
            state="manual" if raco_ready else "blocked",
            summary=(
                "Compare the changed area in Blender and RaCo before treating the slice as visually safe."
                if raco_ready
                else "RaCoHeadless is missing locally, so only the manual Blender side is currently available."
            ),
            note="Keep the deterministic evidence open while doing the visual compare.",
        ),
        DesktopManualCard(
            key="screenshot_slots",
            label="Screenshot evidence slot",
            state="manual",
            summary="Capture the important proof shots early instead of waiting for delivery pressure.",
            note=f"Attach the screenshot path next to the {profile_id} evidence bundle once you have it.",
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
                else "BMW-side follow-up is still blocked locally, so keep the SG-side post-integration note ready without pretending the BMW stage ran."
            ),
            note="Use the SG-side report links first, then append the BMW-side outcome once access exists.",
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
        "Evidence ready:",
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


def _copy_items(
    record: ActionRecord,
    items: tuple[DesktopEvidenceItem, ...],
    run_record: RunRecord | None,
) -> tuple[DesktopCopyItem, ...]:
    title = str(record.summary.get("title", record.label)) if isinstance(record.summary, dict) else record.label
    primary_line = _primary_evidence_line(items)
    if run_record is not None:
        grouped_items = _report_grouped_items(run_record)
        grouped_lines = _grouped_finding_lines(grouped_items)
        return _export_copy_items(
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
        )

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
    )
    return tuple(
        item
        for item in (
            DesktopCopyItem(key="jira", label="Copy Jira note", text=quick_update),
            DesktopCopyItem(key="qa_hero", label="Copy QA Hero note", text=quick_update),
            DesktopCopyItem(key="quick_update", label="Copy quick update", text=quick_update),
            DesktopCopyItem(key="handoff", label="Copy full handoff", text=quick_update),
        )
        if item.text.strip()
    )


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
        created_at_utc=record.created_at_utc,
        workflow_stage_label=progress_label,
        summary_title=summary_title,
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
        created_at_utc=run_record.created_at_utc,
        workflow_stage_label=stage_label,
        summary_title=summary_title,
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
        current_command=str(current_meta.get("command", "")).strip(),
        child_run_id=str(current_meta.get("child_run_id", "")).strip(),
        linked_run_id=(str(current_meta.get("child_run_id", "")).strip() or (run_record.run_id if run_record is not None else "")),
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
