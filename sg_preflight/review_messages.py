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


def _digest_blockers(state: dict[str, Any]) -> list[str]:
    blockers = _open_blockers(state)
    condensed: list[str] = []
    lowered = [item.casefold() for item in blockers]
    if any("jira" in item for item in lowered) or any("codecraft" in item for item in lowered) or any("qx" in item for item in lowered):
        condensed.append("Jira / CodeCraft / QX access")
    if _pending_decisions(state):
        condensed.append("review-owner decisions")
    if not condensed and blockers:
        condensed.append(blockers[0])
    return condensed


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
    delta_summary = state.get("daily_delta_summary", {})

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
        "delta_summary": {
            "new_failures_count": int(delta_summary.get("new_failures_count", 0) or 0),
            "resolved_failures_count": int(delta_summary.get("resolved_failures_count", 0) or 0),
            "new_screenshot_diffs_count": int(delta_summary.get("new_screenshot_diffs_count", 0) or 0),
            "unchanged_blockers_count": int(delta_summary.get("unchanged_blockers_count", 0) or 0),
        },
    }


def build_morning_digest(state: dict[str, Any], previous_state: dict[str, Any] | None = None) -> str:
    digest = build_digest_json(state, previous_state=previous_state)
    scope = " / ".join(digest["scope"]) if digest["scope"] else "n/a"
    verification = digest["package_verification_status"] or "unknown"
    smoke = digest["representative_smoke"]
    battery = digest["screenshot_battery"]
    unresolved = ", ".join(digest["unresolved_families"]) if digest["unresolved_families"] else "none"
    pending_decisions = _pending_decisions(state)
    blockers = _digest_blockers(state)
    review_first = digest["review_first"]
    delta_summary = digest["delta_summary"]

    title = "Daily 3D Car QA Digest"
    if digest["ticket_id"]:
        title += f" - {digest['ticket_id']}"
    if digest["date"]:
        title += f" ({digest['date']})"
    lines = [title]
    lines.append(f"Scope: {scope}")
    lines.append(f"Package verification: {verification}")
    lines.append(f"Smoke: {smoke['completed']}/{smoke['total']} passed")
    lines.append(
        "Battery: "
        f"{battery['covered']}/{battery['total']} covered "
        f"({battery['exact_candidate_ready']} exact, {battery['proxy_candidate_ready']} proxy, {battery['runtime_crash']} crash)"
    )
    lines.append(
        "Delta: "
        f"+{delta_summary['new_failures_count']} failures, "
        f"{delta_summary['resolved_failures_count']} resolved, "
        f"{delta_summary['new_screenshot_diffs_count']} new diffs, "
        f"{delta_summary['unchanged_blockers_count']} unchanged blockers"
    )
    lines.append(f"Unresolved exact: {unresolved}")
    if pending_decisions:
        lines.append("Needs decision: " + "; ".join(pending_decisions[:2]) + ("; ..." if len(pending_decisions) > 2 else ""))
    elif review_first:
        lines.append("Review first: " + review_first[0])
    if blockers:
        lines.append("Open blockers: " + "; ".join(blockers))
    return "\n".join(lines)
