"""Desktop completion notifications: the background-safe notifier and the
Full QA Pass completion title/message builder.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sg_preflight.dashboard_workflows.state_bridge import _with_main_globals


def _notify_completion_safe(
    *,
    title: str,
    message: str,
    workspace: Path,
    action_id: str,
    profile_id: str,
    evidence_path: str = "",
    enabled: bool | None = None,
    elapsed_seconds: Any | None = None,
    minimum_elapsed_seconds: int = 0,
) -> None:
    if enabled is False or (enabled is None and not _dashboard_notifications_enabled(workspace)):
        return
    if minimum_elapsed_seconds > 0:
        try:
            elapsed = int(float(elapsed_seconds or 0))
        except (TypeError, ValueError):
            elapsed = 0
        if elapsed < minimum_elapsed_seconds:
            return
    from nicegui import background_tasks, run as nicegui_run

    notification_task = nicegui_run.io_bound(
        notify_desktop_completion,
        title=title,
        message=message,
        workspace=workspace,
        action_id=action_id,
        profile_id=profile_id,
        evidence_path=evidence_path,
    )
    try:
        background_tasks.create(
            notification_task,
            name=f"sgfx-desktop-notification-{action_id or 'completion'}",
        )
    except Exception:
        close = getattr(notification_task, "close", None)
        if callable(close):
            close()
        return


def _full_qa_completion_notification(profile_id: str, payload: dict[str, Any]) -> dict[str, str]:
    status = str(payload.get("status", payload.get("run_status", "unknown"))).strip().casefold()
    counts = payload.get("counts", {}) if isinstance(payload.get("counts"), dict) else {}

    def _count(key: str) -> int:
        try:
            return int(counts.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0

    failed_count = _count("failed") + _count("unavailable")
    if status in {"failed", "unavailable"} or failed_count > 0:
        return {
            "title": "Full QA Pass needs attention",
            "message": f"Full QA Pass for {profile_id} did not complete. See dashboard.",
        }
    review_count = _count("incomplete") + _count("confirmation_pending") + len(
        payload.get("confirmation_items", []) if isinstance(payload.get("confirmation_items"), list) else []
    )
    return {
        "title": "Full QA Pass finished",
        "message": f"Full QA Pass for {profile_id} completed. {review_count} items ready for your review.",
    }


_notify_completion_safe = _with_main_globals(_notify_completion_safe)
_full_qa_completion_notification = _with_main_globals(_full_qa_completion_notification)
