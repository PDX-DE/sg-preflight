"""Full QA Pass & Batch Full QA Pass page payloads, plus the reconnect-storm
trigger-flag parsing and process-local dedup for the Full QA Pass trigger.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from sg_preflight.dashboard_workflows.state_bridge import _with_main_globals


def _full_qa_pass_page(
    profile_id: str,
    workspace: Path,
    *,
    bmw_root: Path | str | None = None,
    trusted_tool_mode: bool = False,
) -> dict[str, Any]:
    del bmw_root
    payload = {
        "schema_version": 1,
        "profile_id": profile_id,
        "workspace": str(workspace),
        "status": "not_run",
        "run_status": "not_run",
        "summary": "Full QA pass has not run in this dashboard session.",
        "progress": {"completed_steps": 0, "total_steps": 9, "percent": 0},
        "steps": [],
        "confirmation_items": [],
        "operator_confirmation_required": False,
        "trusted_tool_mode": bool(trusted_tool_mode),
        "read_only": True,
        "manual_review_required": True,
        "records_operator_verdict": False,
        "is_approval": False,
        "guardrails": list(DASHBOARD_GUARDRAILS),
        "confluence_anchors": [QUALITY_HERO_CONFLUENCE_ANCHOR, DELIVERY_CHECKLIST_CONFLUENCE_ANCHOR],
    }
    return {
        "id": "full-qa-pass",
        "title": "Full QA Pass",
        "tagline": "One local pass through setup, evidence, review assist, and handoff status.",
        "status": str(payload.get("status", "unknown")),
        "data_available": True,
        "summary": str(payload.get("summary", "")),
        "items": [
            {
                "label": str(step.get("label", "")),
                "status": str(step.get("status", "")),
                "detail": str(step.get("summary", "")),
            }
            for step in payload.get("steps", [])
            if isinstance(step, dict)
        ],
        "payload": payload,
        "confluence_anchors": list(payload.get("confluence_anchors", [])),
    }


def _batch_full_qa_pass_page(profile_id: str, workspace: Path) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "profile_id": profile_id,
        "workspace": str(workspace),
        "status": "not_run",
        "summary": "Select multiple profiles and run their Full QA Pass snapshots one at a time.",
        "progress": {"completed_profiles": 0, "total_profiles": 0, "percent": 0},
        "results": [],
        "read_only": True,
        "manual_review_required": True,
        "records_operator_verdict": False,
        "is_approval": False,
        "guardrails": list(DASHBOARD_GUARDRAILS),
        "confluence_anchors": [QUALITY_HERO_CONFLUENCE_ANCHOR],
    }
    return {
        "id": "batch-full-qa-pass",
        "title": "Batch Full QA Pass",
        "tagline": "Run selected profiles sequentially; one profile finishes before the next starts.",
        "status": "not_run",
        "data_available": True,
        "summary": str(payload.get("summary", "")),
        "items": [],
        "payload": payload,
        "confluence_anchors": list(payload.get("confluence_anchors", [])),
    }


_TRUTHY_TRIGGERS = frozenset({"1", "true", "yes", "on"})


def _is_truthy_trigger(value: str | None, *, default: str = "") -> bool:
    raw = str(value if value is not None else default or "").strip().casefold()
    return raw in _TRUTHY_TRIGGERS


# Process-local dedup for the Full QA Pass trigger so a NiceGUI WebSocket
# reconnect storm cannot re-fire `build_full_qa_pass` after the ui.navigate.to
# redirect below (the storm re-hits the page handler with the cached
# `?full_qa_run=1` URL before the redirect lands client-side, observed
# 2026-05-29 07:17:28-31: 5 fires for G70 within 2.4s).
#
# The dedup key is per-profile (not per-second) so even storms that span
# multiple wall-clock seconds collide on the same recorded token. The 30s
# expiry releases the lock once any reasonable operator re-click cadence has
# passed. The redirect + early-return path stays as belt+suspenders.
FULL_QA_PASS_DEDUP_WINDOW_SECONDS = 30.0
_full_qa_pass_dedup_lock = threading.Lock()
_full_qa_pass_dedup_tokens: dict[str, float] = {}


FULL_QA_PASS_DEDUP_BUCKET_SECONDS = 5


def _full_qa_pass_token(profile_id: str, ts_seconds: int | None = None) -> str:
    """Audit-trail token. Widens the timestamp suffix from per-second
    to per-5-second buckets so back-to-back fires that cross a second boundary
    (observed in testing: a 12:09:14.x / 12:09:15.x burst on one profile — three log entries
    inside 1.1s) collapse to the same token rather than three distinct ones.

    The dedup DECISION still keys on `profile_id` only via
    `_full_qa_pass_dedup_key`; the bucketed timestamp is for log readability.
    """
    if ts_seconds is None:
        ts_seconds = int(time.time())
    bucket = (int(ts_seconds) // FULL_QA_PASS_DEDUP_BUCKET_SECONDS) * FULL_QA_PASS_DEDUP_BUCKET_SECONDS
    return f"full-qa-pass:{profile_id}:{bucket}"


def _full_qa_pass_dedup_key(profile_id: str) -> str:
    """The dict key — per-profile so multi-second reconnect storms still dedup."""
    return f"full-qa-pass:{str(profile_id or '').strip().upper() or 'UNKNOWN'}"


def _should_fire_full_qa_pass(profile_id: str, *, now: float | None = None) -> bool:
    """Return True iff this profile has NOT been fired within the dedup window.

    Side effect on a True return: records the new fire so any subsequent call
    within `FULL_QA_PASS_DEDUP_WINDOW_SECONDS` returns False. Side effect on a
    False return: none. Prunes expired tokens on every call.
    """
    key = _full_qa_pass_dedup_key(profile_id)
    current = now if now is not None else time.monotonic()
    with _full_qa_pass_dedup_lock:
        expired = [k for k, exp in _full_qa_pass_dedup_tokens.items() if exp <= current]
        for k in expired:
            _full_qa_pass_dedup_tokens.pop(k, None)
        if key in _full_qa_pass_dedup_tokens:
            return False
        _full_qa_pass_dedup_tokens[key] = current + FULL_QA_PASS_DEDUP_WINDOW_SECONDS
        return True


def _reset_full_qa_pass_dedup() -> None:
    """Test helper: clear the dedup cache so each unit test starts clean."""
    with _full_qa_pass_dedup_lock:
        _full_qa_pass_dedup_tokens.clear()


_full_qa_pass_page = _with_main_globals(_full_qa_pass_page)
_batch_full_qa_pass_page = _with_main_globals(_batch_full_qa_pass_page)
_is_truthy_trigger = _with_main_globals(_is_truthy_trigger)
_full_qa_pass_token = _with_main_globals(_full_qa_pass_token)
_full_qa_pass_dedup_key = _with_main_globals(_full_qa_pass_dedup_key)
_should_fire_full_qa_pass = _with_main_globals(_should_fire_full_qa_pass)
_reset_full_qa_pass_dedup = _with_main_globals(_reset_full_qa_pass_dedup)
