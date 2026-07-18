"""Live-state snapshot publishing: the debounced live_state.json writer and
the full-qa-pass snapshot page merge helper.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sg_preflight.dashboard_workflows.state_bridge import _with_main_globals


def _publish_live_state(
    workspace: Path | str,
    *,
    dashboard_surface: str,
    profile_id: str = "",
    wizard_step_id: str = "",
    wizard_step_index: int = -1,
    wizard_step_total: int = 0,
    queued_acknowledgments: tuple[str, ...] = (),
    last_operator_action: tuple[str, str] | None = None,
    last_error: str | None = None,
) -> None:
    """Best-effort debounced write to live_state.json.

    All failures are swallowed — observability must never crash an operator
    surface. The debounced writer batches updates so a sub-250ms burst becomes
    one disk write.
    """
    try:
        from sg_preflight.live_state import (
            LastOperatorAction,
            LiveStateSnapshot,
            _utc_now_ms,
            write_live_state,
        )
        action = (
            LastOperatorAction(verb=last_operator_action[0], surface=last_operator_action[1], ts=_utc_now_ms())
            if last_operator_action
            else None
        )
        snapshot = LiveStateSnapshot(
            dashboard_surface=dashboard_surface,
            profile_id=profile_id,
            wizard_step_id=wizard_step_id,
            wizard_step_index=wizard_step_index,
            wizard_step_total=wizard_step_total,
            queued_acknowledgments=tuple(queued_acknowledgments),
            last_operator_action=action,
            last_error=last_error,
        )
        write_live_state(workspace, snapshot)
    except Exception:
        # Observability never blocks; failures are not surfaced to the operator.
        return


def _snapshot_with_full_qa_payload(snapshot: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    pages = list(snapshot.get("pages", []))
    for index, page in enumerate(pages):
        if not isinstance(page, dict) or str(page.get("id", "")) != "full-qa-pass":
            continue
        steps = [step for step in payload.get("steps", []) if isinstance(step, dict)]
        pages[index] = {
            **page,
            "status": str(payload.get("status", payload.get("run_status", "unknown"))),
            "summary": str(payload.get("summary", "")),
            "items": [
                {
                    "label": str(step.get("label", "")),
                    "status": str(step.get("status", "")),
                    "detail": str(step.get("summary", "")),
                }
                for step in steps
            ],
            "payload": payload,
            "confluence_anchors": list(payload.get("confluence_anchors", page.get("confluence_anchors", []))),
        }
        break
    return {**snapshot, "pages": pages}


_publish_live_state = _with_main_globals(_publish_live_state)
_snapshot_with_full_qa_payload = _with_main_globals(_snapshot_with_full_qa_payload)
