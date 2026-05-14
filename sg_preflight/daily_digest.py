from __future__ import annotations

from pathlib import Path
from typing import Any

from sg_preflight.delivery_checklist import (
    delivery_checklist_digest_items,
    read_delivery_checklists_for_profiles,
)
from sg_preflight.export_size_analysis import (
    export_size_analysis_digest_items,
    read_export_size_analyses_for_profiles,
)
from sg_preflight.manual_review import manual_review_digest_items
from sg_preflight.review_messages import build_digest_json, build_morning_digest
from sg_preflight.review_state import build_review_board_state


_GUARDRAILS = [
    "opt-in local summary",
    "no Jira or Teams auto-posting",
    "not production-ready",
    "not a visual approval",
    "manual review remains required",
    "suggested review order is guidance, not a verdict",
]


def _review_package_setup_hint(ticket_id: str | None = None) -> str:
    ticket = ticket_id.strip() if ticket_id else "<ticket-id>"
    return f"Run python -m sg_preflight ticket-review {ticket} --profile <profile-id> --sendable first."


def _workspace_text(workspace: Path | str | None) -> str:
    if workspace is None:
        return str(Path.cwd())
    return str(Path(workspace).resolve())


def _string_items(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(item).strip() for item in values if str(item).strip()]


def _section(heading: str, items: list[dict[str, Any]], empty_message: str) -> dict[str, Any]:
    return {
        "heading": heading,
        "items": items,
        "count": len(items),
        "empty_message": empty_message,
    }


def _artifact_evidence_items(state: dict[str, Any]) -> list[dict[str, Any]]:
    references = state.get("artifact_references", {})
    if not isinstance(references, dict):
        return []
    preferred_keys = (
        "latest_daily_snapshot_markdown",
        "review_priority_markdown",
        "daily_delta_markdown",
        "candidate_gallery",
        "dod_matrix",
        "review_owner_decisions",
        "package_zip",
    )
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in preferred_keys:
        ref = references.get(key, {})
        if not isinstance(ref, dict) or not ref.get("exists"):
            continue
        label = str(ref.get("label", key)).strip() or key
        path = str(ref.get("absolute_path", "")).strip()
        dedupe_key = f"{label}\0{path}".casefold()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        items.append(
            {
                "label": label,
                "status": "prepared",
                "path": path,
            }
        )
    return items


def _summary_evidence_items(state: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    smoke = state.get("daily_snapshot_summary", {})
    if isinstance(smoke, dict):
        smoke_total = int(smoke.get("smoke_total", 0) or 0)
        smoke_completed = int(smoke.get("smoke_completed", 0) or 0)
        if smoke_total or smoke_completed:
            items.append(
                {
                    "label": "Representative smoke",
                    "status": "prepared",
                    "detail": f"{smoke_completed}/{smoke_total} completed",
                }
            )
    battery = state.get("screenshot_battery_counts", {})
    if isinstance(battery, dict):
        total = int(battery.get("total", 0) or 0)
        exact = int(battery.get("exact_candidate_ready", 0) or 0)
        proxy = int(battery.get("proxy_candidate_ready", 0) or 0)
        crash = int(battery.get("runtime_crash", 0) or 0)
        if total or exact or proxy or crash:
            items.append(
                {
                    "label": "Screenshot battery summary",
                    "status": "prepared",
                    "detail": f"{exact} exact / {proxy} proxy / {crash} crash / {total} total",
                }
            )
    return items


def _blocker_items(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "label": text,
            "status": "blocked",
        }
        for text in _string_items(state.get("open_items", []))
    ]


def _manual_review_items(state: dict[str, Any]) -> list[dict[str, Any]]:
    profiles = state.get("manual_review_profiles", [])
    session_items = state.get("manual_review_sessions", [])
    if not isinstance(profiles, list):
        profiles = []
    items: list[dict[str, Any]] = []
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        status = str(profile.get("status", "pending")).strip() or "pending"
        if status == "passed":
            continue
        profile_id = str(profile.get("profile_id", "")).strip() or "unknown profile"
        items.append(
            {
                "label": profile_id,
                "status": status,
                "detail": str(profile.get("summary", "")).strip(),
                "note": str(profile.get("note", "")).strip(),
            }
        )
    if isinstance(session_items, list):
        for item in session_items:
            if isinstance(item, dict):
                items.append(dict(item))
    return items


def _waiting_owner_items(state: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    decisions = state.get("review_owner_decisions", {})
    sections = decisions.get("sections", []) if isinstance(decisions, dict) else []
    if isinstance(sections, list):
        for section in sections:
            if not isinstance(section, dict) or not section.get("pending", False):
                continue
            title = str(section.get("title", "")).strip()
            if not title:
                continue
            items.append(
                {
                    "label": title,
                    "status": "waiting_for_owner",
                    "owner": str(section.get("owner", "")).strip(),
                    "detail": str(section.get("note", "")).strip(),
                }
            )
    findings = state.get("external_findings", {})
    finding_items = findings.get("items", []) if isinstance(findings, dict) else []
    if isinstance(finding_items, list):
        for finding in finding_items:
            if not isinstance(finding, dict):
                continue
            status = str(finding.get("status", "")).strip().lower()
            if status in {"resolved", "closed", "done"}:
                continue
            label = str(finding.get("finding", "")).strip()
            owner = str(finding.get("owner", "")).strip()
            if not label and not owner:
                continue
            items.append(
                {
                    "label": label or "External finding",
                    "status": status or "reported",
                    "owner": owner,
                    "detail": str(finding.get("source", "")).strip(),
                }
            )
    return items


def _suggested_review_items(state: dict[str, Any]) -> list[dict[str, Any]]:
    ranked = state.get("top_review_priority_items", [])
    if not isinstance(ranked, list):
        return []
    items: list[dict[str, Any]] = []
    for index, item in enumerate(ranked, start=1):
        if not isinstance(item, dict):
            continue
        profile_id = str(item.get("profile_id", "")).strip()
        filter_name = str(item.get("filter_name", "")).strip()
        if not profile_id and not filter_name:
            continue
        items.append(
            {
                "order": index,
                "profile_id": profile_id,
                "filter_name": filter_name,
                "priority_level": str(item.get("priority_level", "")).strip(),
                "attention_category": str(item.get("attention_category", "")).strip(),
                "verdict": str(item.get("verdict", "")).strip(),
                "reason": str(item.get("reason", "")).strip(),
                "recommendation": _safe_recommendation(str(item.get("recommendation", "")).strip()),
                "signals": _string_items(item.get("signals", [])),
                "guidance": "Suggested review order only; reviewer verdict required; not a QA verdict.",
            }
        )
    return items


def _safe_recommendation(value: str) -> str:
    if "not human review" in value.casefold():
        return "Treat as a technical blocker before manual visual review."
    return value


def build_daily_digest(state: dict[str, Any]) -> dict[str, Any]:
    compact = build_digest_json(state)
    digest = {
        "title": "Daily 3D Car QA Digest",
        "ticket_id": str(state.get("ticket_id", "")).strip(),
        "status": str(state.get("status", "ready")).strip() or "ready",
        "data_available": bool(state.get("data_available", True)),
        "date": compact.get("date", ""),
        "scope": list(compact.get("scope", [])),
        "delivery_mode": "opt_in_manual",
        "guardrails": list(_GUARDRAILS),
        "summary": compact,
        "sections": {
            "evidence_prepared": _section(
                "Evidence prepared",
                _summary_evidence_items(state)
                + delivery_checklist_digest_items(state)
                + export_size_analysis_digest_items(state)
                + _artifact_evidence_items(state),
                "No evidence artifacts recorded in the current state.",
            ),
            "blockers": _section(
                "Blockers",
                _blocker_items(state),
                "No blockers recorded in the current state.",
            ),
            "manual_review_pending": _section(
                "Manual review pending",
                _manual_review_items(state),
                "No manual review items recorded in the current state.",
            ),
            "waiting_for_owner": _section(
                "Waiting for owner",
                _waiting_owner_items(state),
                "No waiting-for-owner items recorded in the current state.",
            ),
            "suggested_review_order": _section(
                "Suggested review order",
                _suggested_review_items(state),
                "No suggested review-order items recorded in the current state.",
            ),
        },
    }
    digest["text"] = render_daily_digest_text(digest)
    digest["markdown"] = render_daily_digest_markdown(digest)
    return digest


def build_latest_daily_digest(
    ticket_id: str | None = None,
    workspace: Path | str | None = None,
) -> dict[str, Any]:
    try:
        state = build_review_board_state(ticket_id, workspace)
    except FileNotFoundError as exc:
        if "No matching review package" not in str(exc):
            raise
        return build_no_data_daily_digest(ticket_id, workspace)
    state["manual_review_sessions"] = manual_review_digest_items(workspace=workspace, ticket_id=ticket_id)
    state["delivery_checklist"] = read_delivery_checklists_for_profiles(
        tuple(str(item) for item in state.get("scope", []) if str(item).strip()),
        workspace=workspace,
    )
    state["export_size_analysis"] = read_export_size_analyses_for_profiles(
        tuple(str(item) for item in state.get("scope", []) if str(item).strip()),
        workspace=workspace,
    )
    return build_daily_digest(state)


def build_no_data_daily_digest(
    ticket_id: str | None = None,
    workspace: Path | str | None = None,
) -> dict[str, Any]:
    state = {
        "ticket_id": ticket_id or "",
        "status": "no_review_package",
        "data_available": False,
        "scope": [],
        "daily_snapshot_summary": {"smoke_completed": 0, "smoke_total": 0},
        "screenshot_battery_counts": {"total": 0},
        "daily_delta_summary": {
            "new_failures_count": 0,
            "resolved_failures_count": 0,
            "new_screenshot_diffs_count": 0,
            "unchanged_blockers_count": 0,
            "operator_signal": "",
        },
        "daily_delta": {
            "new_failures": [],
            "new_screenshot_diffs": [],
            "unchanged_blockers": [],
            "resolved_failures": [],
            "top_five_to_review": [],
        },
        "review_owner_decisions": {"sections": [], "pending_titles": []},
        "manual_review_profiles": [],
        "manual_review_sessions": manual_review_digest_items(workspace=workspace, ticket_id=ticket_id),
        "artifact_references": {},
        "top_review_priority_items": [],
        "open_items": [],
    }
    digest = build_daily_digest(state)
    digest["workspace"] = _workspace_text(workspace)
    digest["no_data_message"] = "No review package found in this workspace."
    digest["setup_hint"] = _review_package_setup_hint(ticket_id)
    digest["text"] = render_daily_digest_text(digest)
    digest["markdown"] = render_daily_digest_markdown(digest)
    return digest


def _format_digest_title(digest: dict[str, Any]) -> str:
    title = str(digest.get("title", "Daily 3D Car QA Digest")).strip() or "Daily 3D Car QA Digest"
    ticket_id = str(digest.get("ticket_id", "")).strip()
    return f"{title} - {ticket_id}" if ticket_id else title


def _owner_slug(owner: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in owner.strip())
    return "_".join(part for part in slug.split("_") if part)


def _status_with_owner(status: str, owner: str) -> str:
    if not owner:
        return status
    if status == "waiting_for_owner":
        owner_token = _owner_slug(owner)
        return f"waiting_for_{owner_token}" if owner_token else status
    return f"{status}: {owner}" if status else f"owner: {owner}"


def _item_text(item: dict[str, Any]) -> str:
    label = str(item.get("label", "")).strip()
    if not label:
        profile = str(item.get("profile_id", "")).strip()
        filter_name = str(item.get("filter_name", "")).strip()
        label = " / ".join(part for part in (profile, filter_name) if part)
    status = str(item.get("status", "") or item.get("priority_level", "")).strip()
    owner = str(item.get("owner", "")).strip()
    status = _status_with_owner(status, owner)
    detail = str(item.get("detail", "") or item.get("reason", "")).strip()
    parts = [label or "item"]
    if status:
        parts.append(f"[{status}]")
    if detail:
        parts.append(f"- {detail}")
    return " ".join(parts)


def render_daily_digest_text(digest: dict[str, Any]) -> str:
    lines = [_format_digest_title(digest)]
    scope = " / ".join(str(item) for item in digest.get("scope", []) if str(item)) or "n/a"
    if digest.get("date"):
        lines.append(f"Date: {digest['date']} | Scope: {scope}")
    else:
        lines.append(f"Scope: {scope}")
    lines.append("Opt-in local summary. Manual review remains required; not a visual approval.")
    if digest.get("data_available") is False:
        lines.append(str(digest.get("no_data_message", "No review package found in this workspace.")))
        setup_hint = str(digest.get("setup_hint", "")).strip()
        if setup_hint:
            lines.append(f"Next step: {setup_hint}")
    sections = digest.get("sections", {})
    if isinstance(sections, dict):
        for section in sections.values():
            if not isinstance(section, dict):
                continue
            heading = str(section.get("heading", "Section")).strip()
            lines.append("")
            lines.append(f"{heading}:")
            items = section.get("items", [])
            if not isinstance(items, list) or not items:
                lines.append(f"- {section.get('empty_message', 'No recorded items.')}")
                continue
            for item in items:
                if isinstance(item, dict):
                    lines.append(f"- {_item_text(item)}")
    return "\n".join(lines)


def render_daily_digest_markdown(digest: dict[str, Any]) -> str:
    lines = [
        f"# {_format_digest_title(digest)}",
        "",
        "> Opt-in local summary. No Jira or Teams post is performed. Manual review remains required; this is not a visual approval.",
        "",
    ]
    if digest.get("data_available") is False:
        lines.append(f"> {digest.get('no_data_message', 'No review package found in this workspace.')}")
        setup_hint = str(digest.get("setup_hint", "")).strip()
        if setup_hint:
            lines.append(f"> Next step: `{setup_hint}`")
        lines.append("")
    if digest.get("date"):
        lines.append(f"- Date: `{digest['date']}`")
    scope = " / ".join(str(item) for item in digest.get("scope", []) if str(item)) or "n/a"
    lines.append(f"- Scope: `{scope}`")
    lines.append("- Suggested review order is guidance only, not a QA verdict.")
    lines.append("")

    sections = digest.get("sections", {})
    if isinstance(sections, dict):
        for section in sections.values():
            if not isinstance(section, dict):
                continue
            lines.append(f"## {section.get('heading', 'Section')}")
            items = section.get("items", [])
            if not isinstance(items, list) or not items:
                lines.append(f"- {section.get('empty_message', 'No recorded items.')}")
                lines.append("")
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                lines.append(f"- {_item_text(item)}")
                recommendation = str(item.get("recommendation", "")).strip()
                guidance = str(item.get("guidance", "")).strip()
                if recommendation:
                    lines.append(f"  - Reviewer suggestion: {recommendation}")
                if guidance:
                    lines.append(f"  - {guidance}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
