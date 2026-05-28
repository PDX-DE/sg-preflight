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
    history = {
        "schema_version": 1,
        "profile_id": str(profile_id or "").strip().upper(),
        "last_successful_run_at": completed_at,
        "last_status": str(payload.get("status", "") or payload.get("run_status", "") or "recorded"),
        "last_summary": str(payload.get("summary", "") or ""),
        "passed_steps": passed_count,
        "incomplete_steps": incomplete_count,
        "failed_steps": failed_count,
        "manual_review_required": bool(payload.get("manual_review_required", True)),
        "is_approval": False,
    }
    path = full_qa_run_history_path(profile_id, home=home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
