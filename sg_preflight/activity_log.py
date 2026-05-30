from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any


ACTIVITY_LOG_BANNER = (
    "Activity log is operator-local. SGFX does not post activity entries to Jira, SVN, or BMW Git."
)

VALID_VERBS = {
    "opened",
    "ran",
    "read",
    "exported",
    "refreshed",
    "switched-profile",
    "switched-mode",
    # H-26 lifecycle event verbs (granular observability per [[feedback-real-bmw-pipeline-must-be-run]]).
    # Each pairs with a surface like `subprocess:start` / `modal:open` / `wizard:step-enter`
    # / `button:click` and operator-readable payload context.
    "started",
    "exited",
    "entered",
    "completed",
    "cancelled",
    "clicked",
    "dismissed",
    "errored",
}

FORBIDDEN_VERBS = {"approved", "cleared", "signed off", "marked done", "verified"}

VALID_OUTCOMES = {"ok", "error", "empty", "unavailable"}


def activity_log_path(workspace: Path | str) -> Path:
    return Path(workspace).resolve() / "operator_state" / "activity_log.jsonl"


def append_activity_entry(
    workspace: Path | str,
    *,
    verb: str,
    surface: str,
    profile: str = "",
    outcome: str = "ok",
    note: str = "",
    now: datetime | None = None,
) -> dict[str, str]:
    safe_verb = _validate_verb(verb)
    safe_outcome = _validate_outcome(outcome)
    timestamp = _utc_now(now)
    entry = {
        "ts": timestamp,
        "verb": safe_verb,
        "surface": _clean_token(surface, default="unknown"),
        "profile": _clean_token(profile, default=""),
        "outcome": safe_outcome,
        "note": str(note or "").strip(),
    }
    path = activity_log_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    return entry


def read_activity_entries(
    workspace: Path | str,
    *,
    profile: str = "",
    since: str = "all",
    now: datetime | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    entries = _read_jsonl(activity_log_path(workspace))
    cutoff = _cutoff_for_since(since, now or datetime.now(timezone.utc))
    safe_profile = str(profile or "").strip().upper()
    filtered = []
    for entry in entries:
        if safe_profile and str(entry.get("profile") or "").upper() != safe_profile:
            continue
        if cutoff is not None and _parse_ts(str(entry.get("ts") or "")) < cutoff:
            continue
        filtered.append(entry)
    filtered.sort(key=lambda item: str(item.get("ts") or ""), reverse=True)
    if limit > 0:
        filtered = filtered[:limit]
    return {
        "note": ACTIVITY_LOG_BANNER,
        "path": str(activity_log_path(workspace)),
        "filter": {"profile": safe_profile or "all", "since": since or "all", "limit": limit},
        "count": len(filtered),
        "entries": filtered,
    }


def render_activity_log_text(payload: dict[str, Any]) -> str:
    lines = [str(payload.get("note") or ACTIVITY_LOG_BANNER)]
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        lines.append("No activity entries for this filter.")
        return "\n".join(lines)
    for entry in entries:
        lines.append(
            f"- {entry.get('ts', '')} {entry.get('verb', '')} "
            f"{entry.get('surface', '')} {entry.get('profile', '')} "
            f"{entry.get('outcome', '')} {entry.get('note', '')}".rstrip()
        )
    return "\n".join(lines)


def _read_jsonl(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    entries: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, dict):
            entries.append({str(key): str(value) for key, value in raw.items()})
    return entries


def _validate_verb(value: str) -> str:
    safe = str(value or "").strip().lower()
    if safe in FORBIDDEN_VERBS or safe not in VALID_VERBS:
        raise ValueError("Activity verb must be factual and operator-local")
    return safe


def _validate_outcome(value: str) -> str:
    safe = str(value or "").strip().lower() or "ok"
    if safe not in VALID_OUTCOMES:
        raise ValueError(f"Activity outcome must be one of: {', '.join(sorted(VALID_OUTCOMES))}")
    return safe


def _clean_token(value: str, *, default: str) -> str:
    text = str(value or "").strip()
    return text or default


def _utc_now(value: datetime | None = None) -> str:
    """Return an ISO-8601 UTC timestamp with millisecond precision (Z suffix).

    H-26 upgrade: pre-H-26 entries used second precision; the reader continues to
    parse both forms (see `_parse_ts`). New entries are written at ms precision so
    operators and tooling can correlate activity log + live_state.json updates
    without ambiguity when events land within the same second.
    """
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    iso = current.astimezone(timezone.utc).isoformat(timespec="milliseconds")
    return iso.replace("+00:00", "Z")


def _parse_ts(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


_DURATION_PATTERN = __import__("re").compile(
    r"^\s*(\d+)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)\s*(?:ago)?\s*$",
    __import__("re").IGNORECASE,
)
_DURATION_UNIT_SECONDS = {
    "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
    "d": 86400, "day": 86400, "days": 86400,
}


def _cutoff_for_since(since: str, now: datetime) -> datetime | None:
    normalized = str(since or "all").strip().lower().replace("_", "-")
    current = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    if normalized == "today":
        return current.replace(hour=0, minute=0, second=0, microsecond=0)
    if normalized == "yesterday":
        today = current.replace(hour=0, minute=0, second=0, microsecond=0)
        return today - timedelta(days=1)
    if normalized in {"this-week", "week"}:
        start = current.replace(hour=0, minute=0, second=0, microsecond=0)
        return start - timedelta(days=start.weekday())
    # H-26: free-form duration strings such as "5m", "5 min ago", "30s", "1h", "2 hours".
    match = _DURATION_PATTERN.match(normalized)
    if match:
        amount = int(match.group(1))
        unit_seconds = _DURATION_UNIT_SECONDS.get(match.group(2).lower(), 0)
        if amount > 0 and unit_seconds > 0:
            return current - timedelta(seconds=amount * unit_seconds)
    return None
