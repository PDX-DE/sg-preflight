from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sg_preflight.bmw_delivery import read_bmw_screenshot_state
from sg_preflight.manual_review import list_manual_review_sessions


RISK_SCORE_GUARDRAILS = (
    "Manual review remains required.",
    "Decision: not approval — evidence only.",
)
RISK_SCORE_BANNER = (
    "Per-car risk score is an evidence triage signal from local files. "
    f"{RISK_SCORE_GUARDRAILS[0]} {RISK_SCORE_GUARDRAILS[1]}"
)
RISK_SCORE_NOTE = (
    "Risk score is based on current screenshot counts, latest manual-review state, "
    "and screenshot files changed after the latest manual-review timestamp."
)
RISK_SCORE_CONFLUENCE_ANCHORS = (
    "PDX_" + "SER" + "GFX/139_3D-Car/298_Quality-Hero-How-to-review-the-3D-car/page.txt",
    "PDX_" + "SER" + "GFX/139_3D-Car/225_3D-Car---RaCo-Implementation/226_How-to-screenshottest/page.txt",
    "PDX_"
    + "SER"
    + "GFX/016_Project-Management/024_How-to...-Seriesgraphics/043_Project-Setup-122025/044_Topic-Owner-TO/page.txt",
)
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
_PENDING_VERDICT = "not_run"


def _int_value(payload: dict[str, Any], key: str) -> int:
    try:
        return int(payload.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _parse_utc(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _session_sort_timestamp(session: dict[str, Any]) -> datetime:
    parsed = _parse_utc(session.get("updated_at_utc") or session.get("created_at_utc"))
    return parsed or datetime.min.replace(tzinfo=timezone.utc)


def _latest_manual_review_session(
    profile_id: str,
    *,
    workspace: Path | str | None,
) -> dict[str, Any] | None:
    requested = profile_id.strip().casefold()
    matches = [
        session
        for session in list_manual_review_sessions(workspace=workspace)
        if str(session.get("profile_id", "")).strip().casefold() == requested
    ]
    if not matches:
        return None
    return sorted(matches, key=_session_sort_timestamp)[-1]


def _manual_summary(session: dict[str, Any] | None) -> dict[str, int]:
    counts = {
        "total_steps": 0,
        "recorded_steps": 0,
        "pending_steps": 0,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "incomplete": 0,
    }
    if not isinstance(session, dict):
        return counts
    steps = [step for step in session.get("steps", []) if isinstance(step, dict)]
    counts["total_steps"] = len(steps)
    for step in steps:
        verdict = str(step.get("verdict", _PENDING_VERDICT) or _PENDING_VERDICT).strip().casefold()
        if verdict == _PENDING_VERDICT:
            counts["pending_steps"] += 1
            continue
        counts["recorded_steps"] += 1
        if verdict in counts:
            counts[verdict] += 1
    return counts


def _image_paths(root_value: object) -> list[Path]:
    root = Path(str(root_value or ""))
    if not root.is_dir():
        return []
    return [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES
    ]


def _changed_since(root_value: object, timestamp: datetime | None) -> int:
    if timestamp is None:
        return 0
    changed = 0
    for path in _image_paths(root_value):
        try:
            modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if modified > timestamp:
            changed += 1
    return changed


def _delta_since_review(screenshot_state: dict[str, Any], latest_session: dict[str, Any] | None) -> dict[str, Any]:
    if latest_session is None:
        return {
            "status": "not_run",
            "changed_file_count": 0,
            "expected_changed_count": 0,
            "actual_changed_count": 0,
            "diff_changed_count": 0,
            "last_review_at_utc": "",
            "summary": "No manual-review session found for this profile.",
        }
    review_timestamp = _parse_utc(latest_session.get("updated_at_utc") or latest_session.get("created_at_utc"))
    review_at = str(latest_session.get("updated_at_utc") or latest_session.get("created_at_utc") or "")
    if review_timestamp is None:
        return {
            "status": "unknown",
            "changed_file_count": 0,
            "expected_changed_count": 0,
            "actual_changed_count": 0,
            "diff_changed_count": 0,
            "last_review_at_utc": review_at,
            "summary": "Latest manual-review timestamp could not be parsed.",
        }
    expected = _changed_since(screenshot_state.get("expected_root", ""), review_timestamp)
    actual = _changed_since(screenshot_state.get("actuals_root", ""), review_timestamp)
    diff = _changed_since(screenshot_state.get("diff_root", ""), review_timestamp)
    total = expected + actual + diff
    return {
        "status": "available",
        "changed_file_count": total,
        "expected_changed_count": expected,
        "actual_changed_count": actual,
        "diff_changed_count": diff,
        "last_review_at_utc": review_at,
        "summary": f"{total} screenshot file(s) changed after the latest manual-review update.",
    }


def _risk_level(score: int) -> str:
    if score >= 70:
        return "high"
    if score >= 35:
        return "medium"
    return "low"


def _score_and_signals(
    *,
    screenshot_state: dict[str, Any],
    manual_counts: dict[str, int],
    latest_session: dict[str, Any] | None,
    delta: dict[str, Any],
) -> tuple[int, list[dict[str, Any]]]:
    score = 0
    signals: list[dict[str, Any]] = []
    expected_count = _int_value(screenshot_state, "expected_count")
    actual_count = _int_value(screenshot_state, "actual_count")
    diff_count = _int_value(screenshot_state, "diff_count")
    disabled_count = _int_value(screenshot_state, "disabled_test_count")

    def add_signal(signal_id: str, weight: int, status: str, detail: str) -> None:
        nonlocal score
        score += weight
        signals.append({"id": signal_id, "weight": weight, "status": status, "detail": detail})

    if not bool(screenshot_state.get("data_available", False)):
        add_signal("screenshot_state_unavailable", 25, "unavailable", "Screenshot state is not available locally.")
    if expected_count > 0 and actual_count == 0:
        add_signal("no_actual_screenshots", 20, "missing", "Expected baselines exist but no actual screenshots are present.")
    if diff_count > 0:
        add_signal("diff_screenshots_present", min(30, 12 + diff_count), "available", f"{diff_count} diff screenshot file(s) are present.")
    if disabled_count > 0:
        add_signal("disabled_screenshot_tests", min(15, disabled_count * 2), "available", f"{disabled_count} screenshot test(s) are disabled in config.")

    if latest_session is None:
        add_signal("manual_review_not_started", 25, "not_run", "No manual-review session found for this profile.")
    else:
        pending_steps = int(manual_counts.get("pending_steps", 0))
        failed_steps = int(manual_counts.get("failed", 0))
        incomplete_steps = int(manual_counts.get("incomplete", 0))
        if pending_steps:
            add_signal("manual_review_pending_steps", min(25, pending_steps * 4), "not_run", f"{pending_steps} manual-review step(s) are not recorded yet.")
        if failed_steps:
            add_signal("manual_review_failed_steps", min(25, failed_steps * 12), "failed", f"{failed_steps} manual-review step(s) are recorded as failed.")
        if incomplete_steps:
            add_signal("manual_review_incomplete_steps", min(15, incomplete_steps * 8), "incomplete", f"{incomplete_steps} manual-review step(s) are recorded as incomplete.")

    changed_count = _int_value(delta, "changed_file_count")
    if changed_count:
        actual_changed = _int_value(delta, "actual_changed_count")
        diff_changed = _int_value(delta, "diff_changed_count")
        weight = min(25, changed_count * 2 + diff_changed * 2 + actual_changed)
        add_signal(
            "screenshot_delta_since_review",
            weight,
            "available",
            f"{changed_count} screenshot file(s) changed after the latest manual-review update.",
        )
    if not signals:
        signals.append(
            {
                "id": "no_active_risk_signals",
                "weight": 0,
                "status": "passed",
                "detail": "No local risk signal crossed the scoring thresholds.",
            }
        )
    return min(100, score), signals


def read_per_car_risk_score(
    profile_id: str,
    *,
    workspace: Path | str | None = None,
    bmw_root: Path | str | None = None,
) -> dict[str, Any]:
    workspace_path = Path(workspace).resolve() if workspace is not None else Path.cwd()
    clean_profile = profile_id.strip() or "profile"
    screenshot_state = read_bmw_screenshot_state(
        clean_profile,
        workspace=workspace_path,
        bmw_root=bmw_root,
        sg_project_root=workspace_path,
    )
    latest_session = _latest_manual_review_session(clean_profile, workspace=workspace_path)
    manual_counts = _manual_summary(latest_session)
    delta = _delta_since_review(screenshot_state, latest_session)
    risk_score, signals = _score_and_signals(
        screenshot_state=screenshot_state,
        manual_counts=manual_counts,
        latest_session=latest_session,
        delta=delta,
    )
    latest_review = {
        "status": "not_run",
        "session_id": "",
        "ticket_id": "",
        "updated_at_utc": "",
        "session_path": "",
        "recorded_steps": 0,
        "pending_steps": 0,
    }
    if latest_session is not None:
        latest_review = {
            "status": str(latest_session.get("status", "unknown") or "unknown"),
            "session_id": str(latest_session.get("session_id", "")),
            "ticket_id": str(latest_session.get("ticket_id", "")),
            "updated_at_utc": str(latest_session.get("updated_at_utc", "")),
            "session_path": str(latest_session.get("session_path", "")),
            "recorded_steps": int(manual_counts.get("recorded_steps", 0)),
            "pending_steps": int(manual_counts.get("pending_steps", 0)),
        }
    status = "available" if bool(screenshot_state.get("data_available", False)) or latest_session is not None else "not_run"
    level = _risk_level(risk_score)
    summary = (
        f"Risk score {risk_score}/100 ({level}) for {clean_profile}; "
        f"{len([signal for signal in signals if int(signal.get('weight', 0) or 0) > 0])} active local signal(s)."
    )
    return {
        "profile_id": clean_profile,
        "matched_profile_id": str(screenshot_state.get("matched_profile_id", "")),
        "brand": str(screenshot_state.get("brand", "")),
        "status": status,
        "data_available": status == "available",
        "risk_score": risk_score,
        "risk_level": level,
        "summary": summary,
        "current_snapshot": {
            "status": str(screenshot_state.get("status", "unknown")),
            "expected_count": _int_value(screenshot_state, "expected_count"),
            "actual_count": _int_value(screenshot_state, "actual_count"),
            "diff_count": _int_value(screenshot_state, "diff_count"),
            "disabled_test_count": _int_value(screenshot_state, "disabled_test_count"),
            "expected_root": str(screenshot_state.get("expected_root", "")),
            "actuals_root": str(screenshot_state.get("actuals_root", "")),
            "diff_root": str(screenshot_state.get("diff_root", "")),
        },
        "latest_review": latest_review,
        "delta_since_last_review": delta,
        "signals": signals,
        "confluence_anchors": list(RISK_SCORE_CONFLUENCE_ANCHORS),
        "guardrails": list(RISK_SCORE_GUARDRAILS),
        "manual_review_required": True,
        "is_approval": False,
        "note": RISK_SCORE_NOTE,
        "guidance": "Use this score to focus review order only; the operator records the review outcome.",
    }


def render_risk_score_text(payload: dict[str, Any]) -> str:
    current = payload.get("current_snapshot", {}) if isinstance(payload.get("current_snapshot"), dict) else {}
    latest = payload.get("latest_review", {}) if isinstance(payload.get("latest_review"), dict) else {}
    delta = payload.get("delta_since_last_review", {}) if isinstance(payload.get("delta_since_last_review"), dict) else {}
    lines = [
        RISK_SCORE_BANNER,
        *[
            str(item)
            for item in payload.get("guardrails", RISK_SCORE_GUARDRAILS)
            if str(item).strip()
        ],
        f"Profile: {payload.get('profile_id', '')}",
        f"Status: {payload.get('status', '')}",
        f"Risk score: {payload.get('risk_score', 0)}/100 ({payload.get('risk_level', 'unknown')})",
        f"Counts: {current.get('expected_count', 0)} expected / {current.get('actual_count', 0)} actual / {current.get('diff_count', 0)} diff",
        f"Manual-review session: {latest.get('session_id', '') or 'not found'}",
        f"Manual-review steps: {latest.get('recorded_steps', 0)} recorded / {latest.get('pending_steps', 0)} not_run",
        f"Delta since latest review: {delta.get('changed_file_count', 0)} changed screenshot file(s)",
        str(payload.get("note", RISK_SCORE_NOTE)),
    ]
    return "\n".join(lines)


def render_risk_score_markdown(payload: dict[str, Any]) -> str:
    current = payload.get("current_snapshot", {}) if isinstance(payload.get("current_snapshot"), dict) else {}
    latest = payload.get("latest_review", {}) if isinstance(payload.get("latest_review"), dict) else {}
    delta = payload.get("delta_since_last_review", {}) if isinstance(payload.get("delta_since_last_review"), dict) else {}
    lines = [
        f"# Per-Car Risk Score - {payload.get('profile_id', '') or 'profile'}",
        "",
        f"> {RISK_SCORE_BANNER}",
        "",
        f"- Status: `{payload.get('status', '')}`",
        f"- Risk score: `{payload.get('risk_score', 0)}/100`",
        f"- Risk level: `{payload.get('risk_level', 'unknown')}`",
        f"- Expected / actual / diff: `{current.get('expected_count', 0)} / {current.get('actual_count', 0)} / {current.get('diff_count', 0)}`",
        f"- Disabled tests in config: `{current.get('disabled_test_count', 0)}`",
        f"- Latest manual-review session: `{latest.get('session_id', '') or 'not found'}`",
        f"- Manual-review steps: `{latest.get('recorded_steps', 0)} recorded / {latest.get('pending_steps', 0)} not_run`",
        f"- Changed screenshot files after latest review: `{delta.get('changed_file_count', 0)}`",
        "",
        "## Guardrails",
    ]
    for guardrail in payload.get("guardrails", RISK_SCORE_GUARDRAILS):
        if str(guardrail).strip():
            lines.append(f"- {guardrail}")
    lines.extend([
        "",
        "## Signals",
    ])
    for signal in payload.get("signals", []):
        if isinstance(signal, dict):
            lines.append(
                f"- `{signal.get('status', 'unknown')}` `{signal.get('id', '')}` "
                f"(+{signal.get('weight', 0)}): {signal.get('detail', '')}"
            )
    lines.extend(["", f"> {payload.get('note', RISK_SCORE_NOTE)}", f"> {payload.get('guidance', '')}"])
    return "\n".join(lines).rstrip() + "\n"
