from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sg_preflight.activity_log import read_activity_entries


HOME_EMPTY_MESSAGE = "No local activity recorded yet."


def build_home_context(
    workspace: Path | str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone()
    stamp = f"{current:%Y-%m-%d %H:%M}"
    try:
        payload = read_activity_entries(
            Path(workspace),
            since="all",
            now=current,
            limit=5,
        )
    except Exception:
        payload = {}
    raw_entries = payload.get("entries", []) if isinstance(payload, dict) else []
    activity: list[dict[str, str]] = []
    for entry in raw_entries[:5]:
        if not isinstance(entry, dict):
            continue
        detail = " ".join(
            part
            for part in (
                str(entry.get("verb", "") or ""),
                str(entry.get("surface", "") or ""),
                str(entry.get("profile", "") or ""),
                str(entry.get("note", "") or ""),
            )
            if part
        ).strip()
        activity.append(
            {
                "label": str(entry.get("ts", "") or "recent"),
                "status": str(entry.get("outcome", "") or "recorded"),
                "detail": detail or "Local activity entry.",
            }
        )
    freshness_label = f"Data as of {stamp}"
    if activity:
        summary = f"{freshness_label}. Your last {len(activity)} local action(s) are below."
    else:
        summary = f"{freshness_label}. {HOME_EMPTY_MESSAGE} Run a check or open a board to get started."
    return {
        "status": "available" if activity else "not_run",
        "data_available": bool(activity),
        "summary": summary,
        "freshness_label": freshness_label,
        "data_as_of": stamp,
        "activity": [dict(item) for item in activity],
        "board_rows": [dict(item) for item in activity],
        "empty_message": HOME_EMPTY_MESSAGE,
        "read_only": True,
        "is_approval": False,
    }
