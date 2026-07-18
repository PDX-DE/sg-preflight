"""Manual-review dashboard state: the per-profile state file path plus the
save/record helpers the manual-review panel and workflow actions write through.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sg_preflight.dashboard_pages_workflows import _ensure_manual_review_dashboard_session
from sg_preflight.dashboard_preferences import _operator_state_path, _utc_now
from sg_preflight.manual_review import QUALITY_HERO_STEPS, record_manual_review_step
from sg_preflight.utils import ensure_parent

MANUAL_REVIEW_STATUSES = ["not_run", "recorded", "incomplete"]
MANUAL_REVIEW_RECORD_VERDICTS = ["passed", "failed", "skipped", "incomplete"]
_BLOCKED_MANUAL_STATUSES = {
    "approve",
    "approved",
    "approval",
    "clear",
    "cleared",
    "signoff",
    "sign-off",
    "signed-off",
    "validated",
    "verified",
    "pass",
    "passed",
}
_MANUAL_REVIEW_PENDING_VERDICT = "not_run"


def _manual_review_state_path(workspace: Path | str, profile_id: str) -> Path:
    safe_profile = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in profile_id.strip()) or "profile"
    return _operator_state_path(workspace, f"manual_review_{safe_profile}.json")


def save_manual_review_state(
    *,
    profile_id: str,
    workspace: Path | str,
    step_slug: str,
    status: str,
    note: str = "",
) -> dict[str, Any]:
    clean_status = status.strip().casefold()
    if clean_status in _BLOCKED_MANUAL_STATUSES or clean_status not in MANUAL_REVIEW_STATUSES:
        raise ValueError(f"Unsupported manual-review dashboard status: {status}")
    known_slugs = {step.slug for step in QUALITY_HERO_STEPS}
    if step_slug not in known_slugs:
        raise KeyError(f"Unknown manual-review step: {step_slug}")
    path = _manual_review_state_path(workspace, profile_id)
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            payload = {}
    else:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("profile_id", profile_id.strip())
    payload["updated_at_utc"] = _utc_now()
    payload["source"] = "NiceGUI dashboard manual-review companion"
    payload["recorded_by_tool"] = False
    steps = payload.setdefault("steps", {})
    if not isinstance(steps, dict):
        steps = {}
        payload["steps"] = steps
    steps[step_slug] = {
        "status": clean_status,
        "note": note.strip(),
        "recorded_at_utc": _utc_now(),
        "recorded_by_tool": False,
    }
    ensure_parent(path)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def record_manual_review_dashboard_step(
    *,
    profile_id: str,
    workspace: Path | str,
    step_slug: str,
    verdict: str,
    note: str = "",
    suggested_verdict: str = "",
) -> dict[str, Any]:
    if verdict.strip().casefold() not in MANUAL_REVIEW_RECORD_VERDICTS:
        raise ValueError(f"Unsupported manual-review dashboard verdict: {verdict}")
    session = _ensure_manual_review_dashboard_session(profile_id=profile_id.strip(), workspace=workspace)
    return record_manual_review_step(
        session["session_path"],
        step_slug,
        verdict,
        workspace=workspace,
        note=note,
        suggested_verdict=suggested_verdict,
    )
