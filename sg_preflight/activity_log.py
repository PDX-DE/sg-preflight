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
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_ts(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


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
    return None
