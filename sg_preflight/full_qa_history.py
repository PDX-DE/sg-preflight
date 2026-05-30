from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def profile_output_token(profile_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(profile_id or "").strip().lower() or "profile")


def full_qa_history_root(*, home: Path | None = None) -> Path:
    raw = os.environ.get("SGFX_FULL_QA_HISTORY_ROOT", "").strip()
    if raw:
        return Path(raw)
    root = Path(home).resolve() if home is not None else Path.home().resolve()
    return root / "sgfx_outputs"


def full_qa_profile_output_root(profile_id: str, *, home: Path | None = None) -> Path:
    return full_qa_history_root(home=home) / profile_output_token(profile_id)


def full_qa_run_history_path(profile_id: str, *, home: Path | None = None) -> Path:
    return full_qa_profile_output_root(profile_id, home=home) / "run_history.json"


def read_full_qa_run_history(profile_id: str, *, home: Path | None = None) -> dict[str, Any]:
    path = full_qa_run_history_path(profile_id, home=home)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def record_full_qa_run_history(
    profile_id: str,
    payload: dict[str, Any],
    *,
    home: Path | None = None,
    completed_at_utc: str | None = None,
    runs_retained: int = 10,
) -> Path:
    completed_at = completed_at_utc or utc_now()
    steps = payload.get("steps", [])
    passed_count = 0
    incomplete_count = 0
    failed_count = 0
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            status = str(step.get("status", "")).strip().casefold()
            if status == "passed":
                passed_count += 1
            elif status == "failed":
                failed_count += 1
            elif status:
                incomplete_count += 1
    last_status = str(payload.get("status", "") or payload.get("run_status", "") or "recorded")
    last_summary = str(payload.get("summary", "") or "")
    run_record = {
        "completed_at_utc": completed_at,
        "status": last_status,
        "summary": last_summary,
        "passed_steps": passed_count,
        "incomplete_steps": incomplete_count,
        "failed_steps": failed_count,
        "risk_score": payload.get("risk_score") if isinstance(payload.get("risk_score"), (int, float)) else None,
        "risk_level": str(payload.get("risk_level", "") or ""),
    }
    # H-30/H-31: keep a bounded list of historical runs so the sparkline +
    # profile summary HTML can render trends. Preserves the legacy single-
    # record top-level fields for backward compatibility with H-22 readers.
    existing = read_full_qa_run_history(profile_id, home=home)
    existing_runs = existing.get("runs") if isinstance(existing, dict) else None
    runs: list[dict[str, Any]] = list(existing_runs) if isinstance(existing_runs, list) else []
    runs.append(run_record)
    if runs_retained > 0 and len(runs) > runs_retained:
        runs = runs[-runs_retained:]
    history = {
        "schema_version": 2,
        "profile_id": str(profile_id or "").strip().upper(),
        "last_successful_run_at": completed_at,
        "last_status": last_status,
        "last_summary": last_summary,
        "passed_steps": passed_count,
        "incomplete_steps": incomplete_count,
        "failed_steps": failed_count,
        "manual_review_required": bool(payload.get("manual_review_required", True)),
        "is_approval": False,
        "runs": runs,
    }
    path = full_qa_run_history_path(profile_id, home=home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def read_full_qa_run_list(
    profile_id: str,
    *,
    home: Path | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return the last `limit` recorded runs newest-first.

    Backward-compat: when the history file uses the legacy schema (no `runs`
    list), synthesise a single-element list from the top-level fields so older
    persisted histories still surface in the sparkline + profile summary.
    """
    history = read_full_qa_run_history(profile_id, home=home)
    if not isinstance(history, dict):
        return []
    runs_value = history.get("runs")
    runs: list[dict[str, Any]]
    if isinstance(runs_value, list) and runs_value:
        runs = [item for item in runs_value if isinstance(item, dict)]
    elif history.get("last_successful_run_at"):
        # Legacy single-record fallback.
        runs = [
            {
                "completed_at_utc": history.get("last_successful_run_at", ""),
                "status": history.get("last_status", ""),
                "summary": history.get("last_summary", ""),
                "passed_steps": history.get("passed_steps", 0),
                "incomplete_steps": history.get("incomplete_steps", 0),
                "failed_steps": history.get("failed_steps", 0),
                "risk_score": None,
                "risk_level": "",
            }
        ]
    else:
        return []
    # Newest first (history list is appended at the end).
    runs = list(reversed(runs))
    if limit > 0:
        runs = runs[:limit]
    return runs
