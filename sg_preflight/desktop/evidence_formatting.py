"""Formats desktop shell evidence, run/action summaries, and Jira / QA-Hero copy text from backend records."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sg_preflight.qa_actions import ActionRecord
from sg_preflight.reporting import build_report_presentation
from sg_preflight.services import RunRecord, load_run_config, load_run_report


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
