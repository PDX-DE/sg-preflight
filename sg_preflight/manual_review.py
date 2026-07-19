"""Assembles the manual-review assist board and markdown from the review
templates, suggestions, and session modules."""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any

from sg_preflight.services import prerequisite_status
from sg_preflight.subprocess_utils import hidden_subprocess_kwargs

from sg_preflight.manual_review_templates import (
    AUTO_CHECK_NOTE,
    MANUAL_REVIEW_HEADER,
    REVIEW_ASSIST_NOTE,
    REVIEW_FOCUS_NOTE,
    VALID_VERDICTS,
    _BMW_SCRIPT_CONFLUENCE_SOURCE,
    _CONFLUENCE_SOURCE,
    _DELIVERY_CONFLUENCE_SOURCE,
    _EVIDENCE_AVAILABLE,
    _EVIDENCE_MISSING,
    _PENDING_VERDICT,
    _workspace,
    list_car_review_templates,
    get_car_review_template,
    review_template_for_profile,
    CarReviewTemplate,
    ManualReviewStepTemplate,
    CAR_REVIEW_TEMPLATES,
    QUALITY_HERO_STEPS,
    QUALITY_HERO_STEP_TITLES,
)
from sg_preflight.manual_review_suggestions import (
    apply_manual_review_suggestions,
    build_manual_review_assist_from_auto_checks,
    run_manual_review_auto_checks,
    suggest_manual_review_verdicts,
)
from sg_preflight.manual_review_session import (
    create_manual_review_session,
    create_manual_review_session_from_template,
    list_manual_review_sessions,
    load_manual_review_session,
    manual_review_digest_items,
    record_manual_review_step,
    _find_step,
    _normalize_verdict,
    _string_list,
)


def build_manual_review_assist(
    profile_id: str,
    *,
    workspace: Path | str | None = None,
) -> dict[str, Any]:
    return build_manual_review_assist_from_auto_checks(
        run_manual_review_auto_checks(profile_id, workspace=workspace)
    )


def _step_markdown(step: dict[str, Any]) -> list[str]:
    title = str(step.get("title", "")).strip()
    slug = str(step.get("slug", "")).strip()
    verdict = _normalize_verdict(step.get("verdict", _PENDING_VERDICT)) or _PENDING_VERDICT
    lines = [f"### {title}", f"- Step: `{slug}`", f"- Verdict: [{verdict}]"]
    review_focus = _string_list(step.get("review_focus", []))
    if review_focus:
        lines.append("- Review focus: " + ", ".join(review_focus))
    evidence_prompt = str(step.get("evidence_prompt", "")).strip()
    if evidence_prompt:
        lines.append(f"- Evidence prompt: {evidence_prompt}")
    review_focus_note = str(step.get("review_focus_note", "")).strip()
    if review_focus_note:
        lines.append(f"- Review focus note: {review_focus_note}")
    suggested = _normalize_verdict(step.get("suggested_verdict", ""))
    if suggested in VALID_VERDICTS:
        lines.append(f"- Suggested verdict: [{suggested}]")
        reason = str(step.get("suggestion_reason", "")).strip()
        if reason:
            lines.append(f"- Suggestion reason: {reason}")
    evidence_status = str(step.get("evidence_status", "")).strip()
    if evidence_status in {_EVIDENCE_AVAILABLE, _EVIDENCE_MISSING}:
        lines.append(f"- Evidence status: `{evidence_status}`")
        reason = str(step.get("suggestion_reason", "")).strip()
        if reason:
            lines.append(f"- Evidence note: {reason}")
        lines.append("- Manual review required: yes")
    auto_check_status = str(step.get("auto_check_status", "")).strip()
    if auto_check_status and auto_check_status != "not_run":
        lines.append(f"- Auto-check status: `{auto_check_status}`")
        auto_check_kind = str(step.get("auto_check_kind", "")).strip()
        if auto_check_kind:
            lines.append(f"- Auto-check kind: `{auto_check_kind}`")
        auto_check_summary = str(step.get("auto_check_summary", "")).strip()
        if auto_check_summary:
            lines.append(f"- Auto-check note: {auto_check_summary}")
        operator_focus_reason = str(step.get("operator_focus_reason", "")).strip()
        if operator_focus_reason:
            lines.append(f"- Operator focus: {operator_focus_reason}")
    operator_verdict = _normalize_verdict(step.get("operator_verdict", ""))
    if operator_verdict in VALID_VERDICTS:
        lines.append(f"- Operator verdict: [{operator_verdict}]")
    if step.get("note"):
        lines.append(f"- Reviewer note: {step['note']}")
    if step.get("screenshot_path"):
        lines.append(f"- Screenshot: `{step['screenshot_path']}`")
    guidance = step.get("guidance", [])
    if isinstance(guidance, list) and guidance:
        lines.append("- Guidance:")
        lines.extend(f"  - {item}" for item in guidance if str(item).strip())
    return lines


def render_manual_review_markdown(session: dict[str, Any]) -> str:
    template = session.get("car_family_template", {})
    checklist = session.get("evidence_checklist", [])
    anchors = session.get("confluence_anchors", [session.get("source", _CONFLUENCE_SOURCE)])
    lines = [
        f"# Manual review session - {session.get('ticket_id', '')} / {session.get('profile_id', '')}",
        "",
        MANUAL_REVIEW_HEADER,
        "",
        f"- Session: `{session.get('session_id', '')}`",
        f"- Status: `{session.get('status', 'in_progress')}`",
        f"- Source: `{session.get('source', _CONFLUENCE_SOURCE)}`",
        "- Manual RaCo / Blender / screenshot review remains required.",
        "",
        "## Summary",
    ]
    summary = session.get("summary", {}) if isinstance(session.get("summary", {}), dict) else {}
    lines.extend(
        [
            f"- Recorded steps: {summary.get('recorded_steps', 0)}/{summary.get('total_steps', 0)}",
            f"- Not-run steps: {summary.get('pending_steps', 0)}",
            "",
        ]
    )
    if isinstance(template, dict) and template:
        lines.extend(
            [
                "",
                "## Review Template",
                f"- Family: `{template.get('family_id', '')}`",
                f"- Title: {template.get('title', '')}",
                f"- Brand / lane: {template.get('brand', '')} / {template.get('lane', '')}",
                f"- Description: {template.get('description', '')}",
            ]
        )
    if isinstance(checklist, list) and checklist:
        lines.extend(["", "## Evidence Checklist"])
        for item in checklist:
            if isinstance(item, dict):
                lines.append(
                    f"- [{item.get('status', 'not_run')}] {item.get('label', '')} "
                    f"(manual review required: {item.get('manual_review_required', True)})"
                )
    if isinstance(anchors, list) and anchors:
        lines.extend(["", "## Confluence Anchors"])
        lines.extend(f"- `{anchor}`" for anchor in anchors if str(anchor).strip())
    lines.extend(["", "## Steps"])
    for step in session.get("steps", []):
        if isinstance(step, dict):
            lines.extend(_step_markdown(step))
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_manual_review_auto_checks_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# Manual review auto-checks - {payload.get('profile_id', '')}",
        "",
        AUTO_CHECK_NOTE,
        "",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- Auto-check status: `{payload.get('auto_execution_status', 'unknown')}`",
        "- Manual review required: yes",
        "- Decision: not approval; evidence only.",
    ]
    summary = str(payload.get("summary", "")).strip()
    if summary:
        lines.extend(["", summary])
    roots = payload.get("project_roots", [])
    if isinstance(roots, list) and roots:
        lines.extend(["", "## Project Roots"])
        lines.extend(f"- `{root}`" for root in roots if str(root).strip())
    anchors = payload.get("confluence_anchors", [])
    if isinstance(anchors, list) and anchors:
        lines.extend(["", "## Confluence Anchors"])
        lines.extend(f"- `{anchor}`" for anchor in anchors if str(anchor).strip())
    lines.extend(["", "## Steps"])
    for step in payload.get("steps", []):
        if not isinstance(step, dict):
            continue
        lines.append(f"### {step.get('title', step.get('slug', 'Manual review step'))}")
        lines.append(f"- Step: `{step.get('slug', '')}`")
        lines.append(f"- Evidence status: `{step.get('evidence_status', 'unknown')}`")
        lines.append(f"- Auto-check status: `{step.get('auto_check_status', 'unknown')}`")
        kind = str(step.get("auto_check_kind", "")).strip()
        if kind:
            lines.append(f"- Auto-check kind: `{kind}`")
        summary_text = str(step.get("auto_check_summary", step.get("suggestion_reason", ""))).strip()
        if summary_text:
            lines.append(f"- Auto-check note: {summary_text}")
        focus = str(step.get("operator_focus_reason", "")).strip()
        if focus:
            lines.append(f"- Operator focus: {focus}")
        lines.append("- Suggested verdict: []")
        lines.append("- Manual review required: yes")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_manual_review_assist_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# Manual review assist - {payload.get('profile_id', '')}",
        "",
        REVIEW_ASSIST_NOTE,
        "",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- Assist status: `{payload.get('assist_status', 'unknown')}`",
        "- Manual review required: yes",
        "- Operator confirmation required: yes",
        "- Decision: not approval; evidence only.",
    ]
    summary = str(payload.get("summary", "")).strip()
    if summary:
        lines.extend(["", summary])
    anchors = payload.get("confluence_anchors", [])
    if isinstance(anchors, list) and anchors:
        lines.extend(["", "## Confluence Anchors"])
        lines.extend(f"- `{anchor}`" for anchor in anchors if str(anchor).strip())
    lines.extend(["", "## Suggested Starting Points"])
    for step in payload.get("steps", []):
        if not isinstance(step, dict):
            continue
        lines.append(f"### {step.get('title', step.get('slug', 'Manual review step'))}")
        lines.append(f"- Step: `{step.get('slug', '')}`")
        lines.append(f"- Suggested starting verdict: [{step.get('suggested_verdict', '')}]")
        reason = str(step.get("suggestion_reason", "")).strip()
        if reason:
            lines.append(f"- Reason: {reason}")
        auto_check_status = str(step.get("auto_check_status", "")).strip()
        if auto_check_status:
            lines.append(f"- Auto-check status: `{auto_check_status}`")
        auto_check_kind = str(step.get("auto_check_kind", "")).strip()
        if auto_check_kind:
            lines.append(f"- Auto-check kind: `{auto_check_kind}`")
        lines.append("- Operator records final verdict: yes")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _status_item(key: str, workspace: Path | str | None) -> dict[str, str]:
    statuses = prerequisite_status(_workspace(workspace))
    for item in statuses:
        if item.get("key") == key:
            return item
    return {"status": "missing", "path": "", "detail": ""}


def open_manual_review_tool(
    session_id_or_path: str | Path,
    step_slug: str,
    *,
    tool: str,
    workspace: Path | str | None = None,
    launch: bool = True,
) -> dict[str, Any]:
    session = load_manual_review_session(session_id_or_path, workspace=workspace)
    step = _find_step(session, step_slug)
    normalized_tool = tool.strip().lower()
    if normalized_tool not in {"raco", "blender"}:
        raise ValueError(f"Unsupported manual review tool: {tool}")
    status_key = "raco_gui" if normalized_tool == "raco" else "blender_executable"
    status = _status_item(status_key, workspace)
    if str(status.get("status", "")).strip().lower() != "available":
        label = "Ramses Composer / RaCo" if normalized_tool == "raco" else "Blender"
        raise RuntimeError(f"{label} is not configured for manual review launching.")
    executable = Path(str(status.get("path", ""))).resolve()
    command = [str(executable)]
    if launch:
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **hidden_subprocess_kwargs())
    return {
        "session_id": session["session_id"],
        "step": {
            "slug": str(step.get("slug", "")),
            "title": str(step.get("title", "")),
            "verdict": str(step.get("verdict", _PENDING_VERDICT)),
        },
        "tool": normalized_tool,
        "status": "launched" if launch else "ready",
        "command": command,
    }
