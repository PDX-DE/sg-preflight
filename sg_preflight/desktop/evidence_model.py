from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sg_preflight.profiles import RunProfile, list_run_profiles
from sg_preflight.qa_actions import ActionRecord, list_operator_actions, list_recent_action_records, load_action_record
from sg_preflight.services import RunRecord, list_recent_run_records, prerequisite_status, qa_workflow_status, workspace_root


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
    summary_lines: tuple[str, ...]
    top_paths: tuple[DesktopEvidenceItem, ...]
    manual_followups: tuple[str, ...]
    artifacts: tuple[DesktopArtifactItem, ...]
    log_path: str
    log_tail: str
    latest_run_links: DesktopLinks
    copy_items: tuple[DesktopCopyItem, ...]
    summary_only: bool


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
    return tuple(items)


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


def _copy_items(
    record: ActionRecord,
    items: tuple[DesktopEvidenceItem, ...],
    run_record: RunRecord | None,
) -> tuple[DesktopCopyItem, ...]:
    title = str(record.summary.get("title", record.label)) if isinstance(record.summary, dict) else record.label
    summary_lines = _summary_lines(record.summary)
    primary_line = _primary_evidence_line(items)
    latest_html = run_record.paths.get("html_report", "") if run_record is not None else ""
    latest_markdown = _latest_markdown_text(run_record)

    jira_lines = [
        f"Jira update - {record.profile_id or record.action_id}",
        f"Action: {title}",
        f"Status: {record.status}",
    ]
    if summary_lines:
        jira_lines.append(f"Summary: {summary_lines[0]}")
    if primary_line:
        jira_lines.append(f"Open first: {primary_line}")
    if latest_html:
        jira_lines.append(f"HTML report: {latest_html}")
    elif record.paths.get("log"):
        jira_lines.append(f"Action log: {record.paths['log']}")

    qa_hero_lines = [
        f"QA Hero note - {record.profile_id or record.action_id}",
        f"Action: {title}",
        f"Status: {record.status}",
    ]
    if primary_line:
        qa_hero_lines.append(f"Primary evidence: {primary_line}")
    qa_hero_lines.extend(summary_lines[:3])
    if latest_html:
        qa_hero_lines.append(f"Evidence: {latest_html}")

    handoff_text = latest_markdown or "\n".join(qa_hero_lines).strip()

    return (
        DesktopCopyItem(key="jira", label="Copy Jira note", text="\n".join(jira_lines).strip()),
        DesktopCopyItem(key="qa_hero", label="Copy QA Hero note", text="\n".join(qa_hero_lines).strip()),
        DesktopCopyItem(key="handoff", label="Copy handoff", text=handoff_text),
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
