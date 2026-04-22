from __future__ import annotations

from datetime import datetime
from typing import Any


def _scope_text(state: dict[str, Any]) -> str:
    scope = [str(item).strip() for item in state.get("scope", []) if str(item).strip()]
    return " / ".join(scope) if scope else "n/a"


def _battery_counts(state: dict[str, Any]) -> tuple[int, int, int, int, int]:
    counts = state.get("screenshot_battery_counts", {})
    total = int(counts.get("total", 0) or 0)
    exact = int(counts.get("exact_candidate_ready", 0) or 0)
    proxy = int(counts.get("proxy_candidate_ready", 0) or 0)
    crash = int(counts.get("runtime_crash", 0) or 0)
    covered = exact + proxy
    return total, covered, exact, proxy, crash


def _pending_decisions(state: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    items: list[str] = []
    decisions = state.get("review_owner_decisions", {}).get("sections", [])
    for section in decisions:
        if not section.get("pending", False):
            continue
        title = str(section.get("title", "")).strip()
        if not title:
            continue
        key = title.casefold()
        if key in seen:
            continue
        seen.add(key)
        items.append(title)
    return items


def _open_blockers(state: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    blockers: list[str] = []
    for item in state.get("open_items", []):
        text = str(item).strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        blockers.append(text)
    return blockers


def _review_first_items(state: dict[str, Any]) -> list[str]:
    delta_items = [
        str(item).strip()
        for item in state.get("daily_delta", {}).get("top_five_to_review", [])
        if str(item).strip()
    ]
    if delta_items:
        return delta_items[:5]

    ranked_items = []
    for item in state.get("top_review_priority_items", []):
        profile_id = str(item.get("profile_id", "")).strip()
        filter_name = str(item.get("filter_name", "")).strip()
        verdict = str(item.get("verdict", "")).strip()
        reason = str(item.get("reason", "")).strip()
        label = " / ".join(part for part in (profile_id, filter_name) if part)
        if verdict:
            label = f"{label}: {verdict}" if label else verdict
        if reason:
            label = f"{label} - {reason}" if label else reason
        if label:
            ranked_items.append(label)
    return ranked_items[:5]


def _digest_date(state: dict[str, Any]) -> str:
    candidates = (
        str(state.get("daily_delta", {}).get("current_created_at", "")).strip(),
        str(state.get("daily_snapshot_created_at", "")).strip(),
        str(state.get("generated_at", "")).strip(),
    )
    for candidate in candidates:
        if not candidate:
            continue
        normalized = candidate.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized).date().isoformat()
        except ValueError:
            if "T" in candidate:
                return candidate.split("T", 1)[0]
            return candidate
    return ""


def build_review_owner_update(state: dict[str, Any]) -> str:
    ticket_id = str(state.get("ticket_id", "")).strip() or "QA status"
    scope = _scope_text(state)
    smoke_summary = state.get("daily_snapshot_summary", {})
    smoke_completed = int(smoke_summary.get("smoke_completed", 0) or 0)
    smoke_total = int(smoke_summary.get("smoke_total", 0) or 0)
    total, covered, exact, proxy, crash = _battery_counts(state)
    unresolved_families = [str(item).strip() for item in state.get("unresolved_families", []) if str(item).strip()]
    pending_decisions = _pending_decisions(state)
    blockers = _open_blockers(state)

    lines = [
        f"{ticket_id} QA status",
        f"Scope: {scope}",
        "",
        f"Representative smoke: {smoke_completed}/{smoke_total} passed",
        f"Screenshot battery: {covered}/{total} covered",
        f"- {exact} exact candidate-ready",
        f"- {proxy} proxy candidate-ready",
        f"- {crash} exact unresolved",
    ]

    if unresolved_families:
        heading = "Only unresolved exact family:" if len(unresolved_families) == 1 else "Unresolved exact families:"
        lines.extend(["", heading, *[f"- {item}" for item in unresolved_families]])

    if pending_decisions:
        lines.extend(["", "Needs review-owner decision:", *[f"- {item}" for item in pending_decisions]])

    jira_blocked = any("jira" in item.casefold() for item in blockers)
    if jira_blocked:
        lines.extend(["", "Jira writeback remains blocked on my side."])

    return "\n".join(lines)


def build_digest_json(state: dict[str, Any], previous_state: dict[str, Any] | None = None) -> dict[str, Any]:
    del previous_state  # Reserved for future cross-run comparison when needed explicitly.

    smoke_summary = state.get("daily_snapshot_summary", {})
    total, covered, exact, proxy, crash = _battery_counts(state)
    delta = state.get("daily_delta", {})
    unresolved_families = [str(item).strip() for item in state.get("unresolved_families", []) if str(item).strip()]
    blockers = _open_blockers(state)

    return {
        "title": "Daily 3D Car QA Digest",
        "ticket_id": str(state.get("ticket_id", "")).strip(),
        "date": _digest_date(state),
        "scope": [str(item).strip() for item in state.get("scope", []) if str(item).strip()],
        "package_verification_status": str(state.get("package_verification", {}).get("status", "")).strip(),
        "representative_smoke": {
            "completed": int(smoke_summary.get("smoke_completed", 0) or 0),
            "total": int(smoke_summary.get("smoke_total", 0) or 0),
        },
        "screenshot_battery": {
            "covered": covered,
            "total": total,
            "exact_candidate_ready": exact,
            "proxy_candidate_ready": proxy,
            "runtime_crash": crash,
        },
        "unresolved_families": unresolved_families,
        "new_since_previous_run": {
            "new_failures": list(delta.get("new_failures", [])),
            "new_screenshot_diffs": list(delta.get("new_screenshot_diffs", [])),
        },
        "still_unresolved": list(delta.get("unchanged_blockers", [])),
        "resolved": list(delta.get("resolved_failures", [])),
        "review_first": _review_first_items(state),
        "open_blockers": blockers,
    }


def build_morning_digest(state: dict[str, Any], previous_state: dict[str, Any] | None = None) -> str:
    digest = build_digest_json(state, previous_state=previous_state)
    scope = " / ".join(digest["scope"]) if digest["scope"] else "n/a"
    verification = digest["package_verification_status"] or "unknown"
    smoke = digest["representative_smoke"]
    battery = digest["screenshot_battery"]

    def _emit_list(title: str, items: list[str], *, numbered: bool = False) -> list[str]:
        if not items:
            return [title, "- none"]
        if numbered:
            return [title, *[f"{index}. {item}" for index, item in enumerate(items, start=1)]]
        return [title, *[f"- {item}" for item in items]]

    lines = ["Daily 3D Car QA Digest"]
    if digest["date"]:
        lines.append(f"Date: {digest['date']}")
    if digest["ticket_id"]:
        lines.append(f"Ticket: {digest['ticket_id']}")
    lines.append(f"Scope: {scope}")
    lines.extend(
        [
            "",
            f"Package verification: {verification}",
            f"Representative smoke: {smoke['completed']}/{smoke['total']} passed",
            f"Screenshot battery: {battery['covered']}/{battery['total']} covered",
            f"- {battery['exact_candidate_ready']} exact candidate-ready",
            f"- {battery['proxy_candidate_ready']} proxy candidate-ready",
            f"- {battery['runtime_crash']} exact unresolved",
        ]
    )

    if digest["unresolved_families"]:
        lines.extend(["", "Only unresolved exact family:", *[f"- {item}" for item in digest["unresolved_families"]]])

    lines.extend(
        [
            "",
            *_emit_list("New since previous run:", digest["new_since_previous_run"]["new_failures"] + digest["new_since_previous_run"]["new_screenshot_diffs"]),
            "",
            *_emit_list("Still unresolved:", digest["still_unresolved"]),
            "",
            *_emit_list("Resolved:", digest["resolved"]),
            "",
            *_emit_list("Review first:", digest["review_first"], numbered=True),
            "",
            *_emit_list("Open blockers:", digest["open_blockers"]),
        ]
    )
    return "\n".join(lines)
