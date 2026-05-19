from __future__ import annotations

from typing import Any


SGFX_AVAILABLE = "available"
SGFX_MISSING = "missing"
SGFX_UNKNOWN = "unknown"
SGFX_NOT_RUN = "not_run"

_AVAILABLE_STATUSES = {
    "available",
    "present",
    "recorded",
}
_MISSING_STATUSES = {
    "missing",
    "no_bmw_root",
    "no_expected_baselines",
    "no_export_tests",
    "no_overview_sheet",
    "no_profile_folder",
    "no_review_package",
    "no_workbook",
    "not_available",
    "profile_not_found",
    "unavailable",
}
_UNKNOWN_STATUSES = {
    "error",
    "git_unreadable",
    "unknown",
    "unreadable",
}
_NOT_RUN_STATUSES = {
    "not_run",
    "pending",
    "skipped",
}


def sgfx_status_from_payload(payload: dict[str, Any] | None) -> str:
    if not payload:
        return SGFX_UNKNOWN
    raw_status = str(payload.get("status", "")).strip().lower()
    if raw_status in _AVAILABLE_STATUSES:
        return SGFX_AVAILABLE
    if raw_status in _MISSING_STATUSES:
        return SGFX_MISSING
    if raw_status in _UNKNOWN_STATUSES:
        return SGFX_UNKNOWN
    if raw_status in _NOT_RUN_STATUSES:
        return SGFX_NOT_RUN
    if payload.get("data_available") is True:
        return SGFX_AVAILABLE
    if payload.get("data_available") is False:
        return SGFX_MISSING
    return SGFX_UNKNOWN


def phase_payload(
    *,
    phase_id: str,
    source: str,
    sgfx_status: str,
    summary: str,
    raw_payload: dict[str, Any],
    confluence_anchor: str = "",
) -> dict[str, Any]:
    return {
        "phase_id": phase_id,
        "source": source,
        "sgfx_status": sgfx_status,
        "summary": summary,
        "payload": raw_payload,
        "confluence_anchor": confluence_anchor,
        "is_approval": False,
    }


def openhtf_phase_result(sgfx_status: str, htf: Any) -> Any:
    if sgfx_status == SGFX_NOT_RUN:
        return htf.PhaseResult.SKIP
    if sgfx_status in {SGFX_MISSING, SGFX_UNKNOWN}:
        return htf.PhaseResult.FAIL_AND_CONTINUE
    return htf.PhaseResult.CONTINUE
