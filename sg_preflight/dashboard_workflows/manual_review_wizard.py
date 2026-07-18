"""Manual review wizard session state and the Manual Review Companion page."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sg_preflight.dashboard_workflows.state_bridge import _with_main_globals


def _manual_review_profile_token(profile_id: str) -> str:
    token = "".join(ch.lower() if ch.isalnum() else "_" for ch in profile_id.strip())
    token = "_".join(part for part in token.split("_") if part)
    return token or "profile"


def _manual_review_dashboard_session_id(profile_id: str) -> str:
    return f"dashboard-{_manual_review_profile_token(profile_id)}"


def _load_manual_review_dashboard_session(
    *,
    profile_id: str,
    workspace: Path | str,
) -> dict[str, Any] | None:
    session_id = _manual_review_dashboard_session_id(profile_id)
    try:
        return load_manual_review_session(session_id, workspace=workspace)
    except (FileNotFoundError, ValueError):
        return None


def _ensure_manual_review_dashboard_session(
    *,
    profile_id: str,
    workspace: Path | str,
    ticket_id: str | None = None,
    family_id: str = "",
) -> dict[str, Any]:
    session = _load_manual_review_dashboard_session(profile_id=profile_id, workspace=workspace)
    if session is not None:
        return session
    return create_manual_review_session_from_template(
        profile_id=profile_id,
        ticket_id=(ticket_id or _dashboard_active_ticket_id(workspace)),
        family_id=family_id,
        workspace=workspace,
        session_id=_manual_review_dashboard_session_id(profile_id),
    )


def _manual_review_step_recorded(step: dict[str, Any]) -> bool:
    return str(step.get("verdict", _MANUAL_REVIEW_PENDING_VERDICT)).strip() != _MANUAL_REVIEW_PENDING_VERDICT


def _manual_review_step_detail(step: dict[str, Any]) -> str:
    if not _manual_review_step_recorded(step):
        auto_status = str(step.get("auto_check_status", "")).strip()
        auto_summary = str(step.get("auto_check_summary", "")).strip()
        if auto_status and auto_status != "not_run" and auto_summary:
            return f"Auto-check {auto_status}. Manual review remains required. {auto_summary}".strip()
        evidence_status = str(step.get("evidence_status", step.get("suggestion_status", ""))).strip()
        reason = str(step.get("suggestion_reason", "")).strip()
        if evidence_status in {"available", "missing"}:
            label = "Evidence available" if evidence_status == "available" else "Evidence missing"
            return f"{label}. Manual review remains required. {reason}".strip()
        return str(step.get("evidence_prompt", ""))
    verdict = str(step.get("verdict", "")).strip()
    recorded_at = str(step.get("recorded_at_utc", "")).strip()
    note = str(step.get("note", "")).strip()
    pieces = [item for item in (verdict, recorded_at, note) if item]
    return " | ".join(pieces)


def _manual_review_page(
    profile_id: str,
    workspace: Path | str,
    *,
    active_ticket_id: str = "",
) -> dict[str, Any]:
    session = _load_manual_review_dashboard_session(profile_id=profile_id, workspace=workspace)
    steps = (
        list(session.get("steps", []))
        if isinstance(session, dict)
        else [step.to_session_step() for step in QUALITY_HERO_STEPS]
    )
    auto_check_payload = run_manual_review_auto_checks(profile_id, workspace=workspace)
    steps = apply_manual_review_suggestions(
        steps,
        profile_id=profile_id,
        workspace=workspace,
        auto_check_payload=auto_check_payload,
    )
    review_assist = build_manual_review_assist_from_auto_checks(auto_check_payload)
    recorded_count = sum(1 for step in steps if isinstance(step, dict) and _manual_review_step_recorded(step))
    status = "recorded" if recorded_count else _MANUAL_REVIEW_PENDING_VERDICT
    session_payload = session if isinstance(session, dict) else {}
    ticket_id = active_ticket_id.strip() or _dashboard_active_ticket_id(workspace)
    default_template = review_template_for_profile(profile_id, workspace=workspace)
    review_templates = list(list_car_review_templates())
    template_anchors = list(session_payload.get("confluence_anchors", default_template.get("confluence_anchors", [])))
    page = {
        "id": "manual-review",
        "title": "Manual Review Companion",
        "tagline": "Step through the 7 Quality-Hero review steps. Operator verdict per step.",
        "status": status,
        "data_available": True,
        "summary": f"{recorded_count}/{len(steps)} manual-review steps recorded locally.",
        "items": [
            {
                "label": str(step.get("title", "")),
                "status": "recorded" if _manual_review_step_recorded(step) else _MANUAL_REVIEW_PENDING_VERDICT,
                "detail": _manual_review_step_detail(step),
            }
            for step in steps
            if isinstance(step, dict)
        ],
        "payload": {
            "status": status,
            "data_available": True,
            "summary": f"{recorded_count}/{len(steps)} manual-review steps recorded locally.",
            "read_only": True,
            "is_approval": False,
            "manual_review_required": True,
            "records_operator_verdict": True,
            "session_id": str(session_payload.get("session_id", _manual_review_dashboard_session_id(profile_id))),
            "ticket_id": str(session_payload.get("ticket_id", ticket_id)),
            "session_path": str(session_payload.get("session_path", "")),
            "markdown_path": str(session_payload.get("markdown_path", "")),
            "steps": steps,
            "review_templates": review_templates,
            "default_family_id": str(default_template.get("family_id", "")),
            "family_id": str(session_payload.get("family_id", default_template.get("family_id", ""))),
            "evidence_checklist": list(session_payload.get("evidence_checklist", default_template.get("evidence_checklist", []))),
            "confluence_anchors": template_anchors or [QUALITY_HERO_CONFLUENCE_ANCHOR],
            "review_assist": review_assist,
        },
        "confluence_anchors": template_anchors or [QUALITY_HERO_CONFLUENCE_ANCHOR],
    }
    if status == _MANUAL_REVIEW_PENDING_VERDICT:
        page["empty_state_note"] = MANUAL_REVIEW_EMPTY_NOTE
    return page


_manual_review_profile_token = _with_main_globals(_manual_review_profile_token)
_manual_review_dashboard_session_id = _with_main_globals(_manual_review_dashboard_session_id)
_load_manual_review_dashboard_session = _with_main_globals(_load_manual_review_dashboard_session)
_ensure_manual_review_dashboard_session = _with_main_globals(_ensure_manual_review_dashboard_session)
_manual_review_step_recorded = _with_main_globals(_manual_review_step_recorded)
_manual_review_step_detail = _with_main_globals(_manual_review_step_detail)
_manual_review_page = _with_main_globals(_manual_review_page)
