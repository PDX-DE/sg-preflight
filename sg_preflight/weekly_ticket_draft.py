"""Builds the draft weekly "tickets I worked on" summary by combining Jira's assigned/updated tickets with the local SGFX activity log."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from typing import Any

from sg_preflight.activity_log import read_activity_entries
from sg_preflight.jira_client import search_my_weekly_tickets


WEEKLY_TICKET_DRAFT_TITLE = "Tickets I worked on"
PART_A_HEADING = "Tickets you worked on this week"
PART_B_HEADING = "Your SGFX activity this week"
PART_B_NOTE = "For your reference - to help you complete the list above, not part of it."
DRAFT_FOOTER = "Draft only - review and edit before sending. SGFX doesn't send anything."
JIRA_CAVEAT = (
    "Starting point from Jira: tickets assigned to you and updated this week. "
    "Add tickets you worked on but are not currently assigned, and remove any that were only touched by someone else."
)
JIRA_NOT_RUN_BANNER = "Jira lookup not run. Add --confirm-network to include assigned tickets."
OFFLINE_BANNER = (
    "Jira not connected - run `integration jira register --confirm-local-write` to auto-pull tickets; "
    "meanwhile use the SGFX activity below."
)
JIRA_UNAVAILABLE_BANNER = (
    "Couldn't reach Jira just now - use the activity below as a starting point and try again once you're back online."
)
_GROUP_ORDER = ("In progress", "In review", "Completed this week", "To do", "Other")
_PART_B_EXCLUDED_SURFACES = frozenset({"digest weekly-tickets"})


def _part_a_banner(jira_status: str) -> str:
    status = str(jira_status or "").strip().lower()
    if status == "not_run":
        return JIRA_NOT_RUN_BANNER
    if status == "missing":
        return OFFLINE_BANNER
    if status not in {"available", ""}:
        return JIRA_UNAVAILABLE_BANNER
    return ""


def build_weekly_ticket_draft(
    *,
    since: str = "startOfWeek",
    workspace: Path | str | None = None,
    confirm_network: bool = False,
    transport: Any | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = _coerce_now(now)
    root = Path(workspace).resolve() if workspace is not None else Path.cwd().resolve()
    jira_payload = search_my_weekly_tickets(
        since=since,
        max_results=50,
        confirm_network=confirm_network,
        transport=transport,
    )
    tickets = [dict(item) for item in jira_payload.get("tickets", []) if isinstance(item, dict)]
    total_available = _total_available(jira_payload.get("total_available"))
    result_limit = _total_available(jira_payload.get("result_limit")) or 50
    truncated = _is_truncated(ticket_count=len(tickets), total_available=total_available, result_limit=result_limit)
    truncation_note = _truncation_note(ticket_count=len(tickets), total_available=total_available) if truncated else ""
    activity_payload = read_activity_entries(root, since="this-week", now=current, limit=200)
    payload = {
        "title": WEEKLY_TICKET_DRAFT_TITLE,
        "status": "available",
        "since": since,
        "range_label": _range_label(since, current),
        "workspace": str(root),
        "operator": _operator_from_tickets(tickets),
        "jira_status": str(jira_payload.get("status", "unknown")),
        "jira_summary": str(jira_payload.get("summary", "")),
        "jira_jql": str(jira_payload.get("jql", "")),
        "connection_status": str(jira_payload.get("connection_status", "not_run")),
        "verification": jira_payload.get("verification", {}),
        "network_confirmed": bool(jira_payload.get("network_confirmed", False)),
        "confirm_network_required": bool(jira_payload.get("confirm_network_required", False)),
        "dry_run": bool(jira_payload.get("dry_run", True)),
        "ticket_count": int(jira_payload.get("ticket_count", len(tickets)) or 0),
        "tickets": tickets,
        "cache_status": str(jira_payload.get("cache_status", "skipped")),
        "total_available": total_available,
        "truncated": truncated,
        "truncation_note": truncation_note,
        "credential": jira_payload.get("credential", {}),
        "part_a": _part_a(tickets, truncation_note=truncation_note),
        "part_b": _part_b(activity_payload),
        "guardrails": [DRAFT_FOOTER, JIRA_CAVEAT, PART_B_NOTE],
        "read_only": True,
        "is_approval": False,
    }
    payload["text"] = render_weekly_ticket_draft_text(payload)
    payload["markdown"] = render_weekly_ticket_draft_markdown(payload)
    return payload


def render_weekly_ticket_draft_text(payload: dict[str, Any]) -> str:
    lines = [
        f"{payload.get('title', WEEKLY_TICKET_DRAFT_TITLE)} - week of {payload.get('range_label', '')}",
        DRAFT_FOOTER,
    ]
    operator = str(payload.get("operator", "")).strip()
    if operator:
        lines.insert(1, f"From: {operator}")

    part_a = payload.get("part_a", {}) if isinstance(payload.get("part_a"), dict) else {}
    lines.extend(["", f"Part A - {PART_A_HEADING}"])
    jira_status = str(payload.get("jira_status", ""))
    banner = _part_a_banner(jira_status)
    if banner:
        lines.append(banner)
    truncation_note = str(payload.get("truncation_note", "") or part_a.get("truncation_note", "")).strip()
    if truncation_note:
        lines.append(truncation_note)
    groups = part_a.get("groups", []) if isinstance(part_a, dict) else []
    if isinstance(groups, list) and groups:
        for group in groups:
            if not isinstance(group, dict):
                continue
            lines.append(f"{group.get('heading', 'Other')}:")
            for ticket in group.get("tickets", []):
                if isinstance(ticket, dict):
                    lines.append(f"- {_ticket_line(ticket)}")
    elif jira_status in {"available", ""}:
        lines.append(str(part_a.get("empty_message", "No tickets updated this week.")))

    part_b = payload.get("part_b", {}) if isinstance(payload.get("part_b"), dict) else {}
    lines.extend(["", f"Part B - {PART_B_HEADING}", PART_B_NOTE])
    activity_groups = part_b.get("groups", []) if isinstance(part_b, dict) else []
    if isinstance(activity_groups, list) and activity_groups:
        for group in activity_groups:
            if not isinstance(group, dict):
                continue
            lines.append(f"{group.get('profile', 'General')}:")
            for item in group.get("items", []):
                if isinstance(item, dict):
                    lines.append(f"- {item.get('label', '')}")
    else:
        lines.append(str(part_b.get("empty_message", "No SGFX activity entries recorded this week.")))

    lines.extend(["", JIRA_CAVEAT, DRAFT_FOOTER])
    return "\n".join(line for line in lines if line is not None)


def render_weekly_ticket_draft_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# {payload.get('title', WEEKLY_TICKET_DRAFT_TITLE)} - week of {payload.get('range_label', '')}",
        "",
        f"> {DRAFT_FOOTER}",
        "",
    ]
    operator = str(payload.get("operator", "")).strip()
    if operator:
        lines.append(f"- Operator: `{operator}`")
    lines.append(f"- Window: `{payload.get('since', 'startOfWeek')}`")
    lines.append("")

    part_a = payload.get("part_a", {}) if isinstance(payload.get("part_a"), dict) else {}
    lines.append(f"## Part A - {PART_A_HEADING}")
    jira_status = str(payload.get("jira_status", ""))
    banner = _part_a_banner(jira_status)
    if banner:
        lines.append(f"> {banner}")
        lines.append("")
    truncation_note = str(payload.get("truncation_note", "") or part_a.get("truncation_note", "")).strip()
    if truncation_note:
        lines.append(f"> {truncation_note}")
        lines.append("")
    groups = part_a.get("groups", []) if isinstance(part_a, dict) else []
    if isinstance(groups, list) and groups:
        for group in groups:
            if not isinstance(group, dict):
                continue
            lines.append(f"### {group.get('heading', 'Other')}")
            for ticket in group.get("tickets", []):
                if isinstance(ticket, dict):
                    lines.append(f"- {_ticket_line(ticket)}")
            lines.append("")
    elif jira_status in {"available", ""}:
        lines.append(f"- {part_a.get('empty_message', 'No tickets updated this week.')}")
        lines.append("")

    part_b = payload.get("part_b", {}) if isinstance(payload.get("part_b"), dict) else {}
    lines.append(f"## Part B - {PART_B_HEADING}")
    lines.append(f"> {PART_B_NOTE}")
    lines.append("")
    activity_groups = part_b.get("groups", []) if isinstance(part_b, dict) else []
    if isinstance(activity_groups, list) and activity_groups:
        for group in activity_groups:
            if not isinstance(group, dict):
                continue
            lines.append(f"### {group.get('profile', 'General')}")
            for item in group.get("items", []):
                if isinstance(item, dict):
                    lines.append(f"- {item.get('label', '')}")
            lines.append("")
    else:
        lines.append(f"- {part_b.get('empty_message', 'No SGFX activity entries recorded this week.')}")
        lines.append("")

    lines.extend([f"> {JIRA_CAVEAT}", "", f"> {DRAFT_FOOTER}"])
    return "\n".join(lines).rstrip() + "\n"


def _coerce_now(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _range_label(since: str, now: datetime) -> str:
    normalized = str(since or "startOfWeek").strip()
    today = now.date()
    if normalized.lower() == "startofweek":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        return f"{start.isoformat()} to {end.isoformat()}"
    match = re.fullmatch(r"-([1-9][0-9]*)[dD]", normalized)
    if match:
        start = today - timedelta(days=int(match.group(1)))
        return f"{start.isoformat()} to {today.isoformat()}"
    return normalized


def _operator_from_tickets(tickets: list[dict[str, Any]]) -> str:
    for ticket in tickets:
        assignee = str(ticket.get("assignee", "")).strip()
        if assignee:
            return assignee
    return ""


def _part_a(tickets: list[dict[str, Any]], *, truncation_note: str = "") -> dict[str, Any]:
    buckets: dict[str, list[dict[str, Any]]] = {heading: [] for heading in _GROUP_ORDER}
    for ticket in tickets:
        buckets[_ticket_group(ticket)].append(ticket)
    groups = [
        {"heading": heading, "count": len(items), "tickets": items}
        for heading in _GROUP_ORDER
        if (items := buckets[heading])
    ]
    return {
        "heading": PART_A_HEADING,
        "tickets": tickets,
        "ticket_count": len(tickets),
        "groups": groups,
        "truncated": bool(truncation_note),
        "truncation_note": truncation_note,
        "empty_message": "No tickets updated this week.",
        "source": "jira",
    }


def _ticket_group(ticket: dict[str, Any]) -> str:
    status = str(ticket.get("status", "")).strip().lower()
    category = str(ticket.get("status_category", "")).strip().lower()
    if "review" in status:
        return "In review"
    if category == "done" or status in {"done", "closed", "resolved", "complete", "completed"}:
        return "Completed this week"
    if category in {"to do", "new"} or status in {"to do", "todo", "open", "backlog"}:
        return "To do"
    if category == "in progress" or status in {"in progress", "in-progress", "started"}:
        return "In progress"
    return "Other"


def _ticket_line(ticket: dict[str, Any]) -> str:
    key = str(ticket.get("key", "")).strip() or "ticket"
    summary = str(ticket.get("summary", "")).strip() or "No summary"
    status = str(ticket.get("status", "")).strip() or "unknown"
    return f"{key} - {summary} - {status}"


def _part_b(activity_payload: dict[str, Any]) -> dict[str, Any]:
    entries = activity_payload.get("entries", []) if isinstance(activity_payload, dict) else []
    counters: dict[str, Counter[tuple[str, str]]] = defaultdict(Counter)
    iterable = entries if isinstance(entries, list) else []
    for entry in iterable:
        if not isinstance(entry, dict):
            continue
        profile = str(entry.get("profile", "") or "").strip().upper() or "General"
        verb = str(entry.get("verb", "") or "read").strip().lower() or "read"
        surface = str(entry.get("surface", "") or "sgfx").strip()
        if surface.casefold() in _PART_B_EXCLUDED_SURFACES:
            continue
        counters[profile][(verb, surface)] += 1
    groups = []
    for profile in sorted(counters):
        items = []
        for (verb, surface), count in counters[profile].most_common():
            label = f"{verb} {surface} x{count}"
            items.append({"verb": verb, "surface": surface, "count": count, "label": label})
        groups.append({"profile": profile, "count": sum(item["count"] for item in items), "items": items})
    return {
        "heading": PART_B_HEADING,
        "note": PART_B_NOTE,
        "groups": groups,
        "entry_count": sum(group["count"] for group in groups),
        "empty_message": "No SGFX activity entries recorded this week.",
        "source": "activity_log",
    }


def _total_available(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _is_truncated(*, ticket_count: int, total_available: int | None, result_limit: int = 50) -> bool:
    if total_available is not None:
        return total_available > ticket_count
    return ticket_count >= result_limit


def _truncation_note(*, ticket_count: int, total_available: int | None) -> str:
    if total_available is not None:
        return (
            f"Showing the {ticket_count} most recently updated - {total_available} tickets matched this week. "
            "Narrow the window with --since to see the rest."
        )
    return (
        f"Showing the {ticket_count} most recently updated; there may be more - "
        "narrow the window with --since."
    )
