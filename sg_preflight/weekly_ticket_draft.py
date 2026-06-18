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
OFFLINE_BANNER = "Jira not connected - run `jira register` to auto-pull tickets; meanwhile use the SGFX activity below."
_GROUP_ORDER = ("In progress", "In review", "Completed this week", "To do", "Other")


def build_weekly_ticket_draft(
    *,
    since: str = "startOfWeek",
    workspace: Path | str | None = None,
    transport: Any | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = _coerce_now(now)
    root = Path(workspace).resolve() if workspace is not None else Path.cwd().resolve()
    jira_payload = search_my_weekly_tickets(since=since, max_results=50, transport=transport)
    tickets = [dict(item) for item in jira_payload.get("tickets", []) if isinstance(item, dict)]
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
        "credential": jira_payload.get("credential", {}),
        "part_a": _part_a(tickets),
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
        lines.insert(1, f"Operator: {operator}")

    part_a = payload.get("part_a", {}) if isinstance(payload.get("part_a"), dict) else {}
    lines.extend(["", f"Part A - {PART_A_HEADING}"])
    jira_status = str(payload.get("jira_status", ""))
    if jira_status == "missing":
        lines.append(OFFLINE_BANNER)
    groups = part_a.get("groups", []) if isinstance(part_a, dict) else []
    if isinstance(groups, list) and groups:
        for group in groups:
            if not isinstance(group, dict):
                continue
            lines.append(f"{group.get('heading', 'Other')}:")
            for ticket in group.get("tickets", []):
                if isinstance(ticket, dict):
                    lines.append(f"- {_ticket_line(ticket)}")
    elif jira_status not in {"available", ""}:
        lines.append(str(payload.get("jira_summary", "Jira tickets unavailable for this draft.")))
    else:
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
    if jira_status == "missing":
        lines.append(f"> {OFFLINE_BANNER}")
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
    elif jira_status not in {"available", ""}:
        lines.append(f"- {payload.get('jira_summary', 'Jira tickets unavailable for this draft.')}")
        lines.append("")
    else:
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


def _part_a(tickets: list[dict[str, Any]]) -> dict[str, Any]:
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
