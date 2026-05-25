from __future__ import annotations

from pathlib import Path
from typing import Any

from sg_preflight.risk_scoring import RISK_SCORE_CONFLUENCE_ANCHORS, read_per_car_risk_score


CROSS_CAR_COMPARISON_TITLE = "Cross-Car Comparison"
CROSS_CAR_COMPARISON_NOTE = (
    "Side-by-side risk-score evidence for two car profiles. Manual review remains required."
)
CROSS_CAR_COMPARISON_GUARDRAILS = (
    "Manual review remains required.",
    "Decision: not approval — evidence only.",
    "BMW Git access is read-only. SGFX never modifies BMW source.",
    "Activity log is local-only — never posted to Jira, SVN, or BMW Git.",
)
DEFAULT_LEFT_PROFILE = "G70"
DEFAULT_RIGHT_PROFILE = "G65"


def _clean_profile(value: str | None, fallback: str) -> str:
    profile = str(value or "").strip().upper()
    return profile or fallback


def _profile_pair(left_profile: str | None, right_profile: str | None) -> tuple[str, str]:
    left = _clean_profile(left_profile, DEFAULT_LEFT_PROFILE)
    right = _clean_profile(right_profile, DEFAULT_RIGHT_PROFILE)
    if left.casefold() == right.casefold():
        right = DEFAULT_RIGHT_PROFILE if left.casefold() != DEFAULT_RIGHT_PROFILE.casefold() else DEFAULT_LEFT_PROFILE
    return left, right


def _safe_risk_score(profile_id: str, workspace: Path, bmw_root: Path | str | None) -> dict[str, Any]:
    try:
        return read_per_car_risk_score(profile_id, workspace=workspace, bmw_root=bmw_root)
    except Exception as exc:  # noqa: BLE001
        return {
            "profile_id": profile_id,
            "status": "unknown",
            "data_available": False,
            "risk_score": 0,
            "risk_level": "unknown",
            "summary": f"Risk score could not be read: {exc}",
            "current_snapshot": {
                "expected_count": 0,
                "actual_count": 0,
                "diff_count": 0,
                "disabled_test_count": 0,
            },
            "latest_review": {
                "recorded_steps": 0,
                "pending_steps": 0,
                "session_id": "",
                "status": "unknown",
            },
            "delta_since_last_review": {"changed_file_count": 0, "status": "unknown"},
            "signals": [],
            "manual_review_required": True,
            "is_approval": False,
        }


def _int_value(payload: dict[str, Any], key: str) -> int:
    try:
        return int(payload.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _nested_int(payload: dict[str, Any], section: str, key: str) -> int:
    nested = payload.get(section, {}) if isinstance(payload.get(section), dict) else {}
    return _int_value(nested, key)


def _row_status(left: dict[str, Any], right: dict[str, Any]) -> str:
    statuses = {str(left.get("status", "unknown")), str(right.get("status", "unknown"))}
    if statuses == {"available"}:
        return "available"
    if "unknown" in statuses:
        return "unknown"
    if "available" in statuses:
        return "incomplete"
    return "not_run"


def _numeric_row(
    *,
    row_id: str,
    label: str,
    left_profile: str,
    right_profile: str,
    left_payload: dict[str, Any],
    right_payload: dict[str, Any],
    left_value: int,
    right_value: int,
    suffix: str = "",
) -> dict[str, Any]:
    delta = left_value - right_value
    return {
        "id": row_id,
        "label": label,
        "left_profile": left_profile,
        "right_profile": right_profile,
        "left_value": f"{left_value}{suffix}",
        "right_value": f"{right_value}{suffix}",
        "left_raw": left_value,
        "right_raw": right_value,
        "delta": delta,
        "delta_label": f"{delta:+d}{suffix}",
        "status": _row_status(left_payload, right_payload),
        "manual_review_required": True,
        "is_approval": False,
    }


def _risk_row(
    *,
    left_profile: str,
    right_profile: str,
    left_payload: dict[str, Any],
    right_payload: dict[str, Any],
) -> dict[str, Any]:
    left_score = _int_value(left_payload, "risk_score")
    right_score = _int_value(right_payload, "risk_score")
    row = _numeric_row(
        row_id="risk_score",
        label="Risk score",
        left_profile=left_profile,
        right_profile=right_profile,
        left_payload=left_payload,
        right_payload=right_payload,
        left_value=left_score,
        right_value=right_score,
    )
    row["left_value"] = f"{left_score}/100 ({left_payload.get('risk_level', 'unknown')})"
    row["right_value"] = f"{right_score}/100 ({right_payload.get('risk_level', 'unknown')})"
    row["delta_label"] = f"{left_score - right_score:+d} point(s)"
    return row


def _comparison_rows(
    *,
    left_profile: str,
    right_profile: str,
    left_payload: dict[str, Any],
    right_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        _risk_row(
            left_profile=left_profile,
            right_profile=right_profile,
            left_payload=left_payload,
            right_payload=right_payload,
        ),
        _numeric_row(
            row_id="expected_screenshots",
            label="Expected screenshots",
            left_profile=left_profile,
            right_profile=right_profile,
            left_payload=left_payload,
            right_payload=right_payload,
            left_value=_nested_int(left_payload, "current_snapshot", "expected_count"),
            right_value=_nested_int(right_payload, "current_snapshot", "expected_count"),
        ),
        _numeric_row(
            row_id="actual_screenshots",
            label="Actual screenshots",
            left_profile=left_profile,
            right_profile=right_profile,
            left_payload=left_payload,
            right_payload=right_payload,
            left_value=_nested_int(left_payload, "current_snapshot", "actual_count"),
            right_value=_nested_int(right_payload, "current_snapshot", "actual_count"),
        ),
        _numeric_row(
            row_id="diff_screenshots",
            label="Diff screenshots",
            left_profile=left_profile,
            right_profile=right_profile,
            left_payload=left_payload,
            right_payload=right_payload,
            left_value=_nested_int(left_payload, "current_snapshot", "diff_count"),
            right_value=_nested_int(right_payload, "current_snapshot", "diff_count"),
        ),
        _numeric_row(
            row_id="disabled_screenshot_tests",
            label="Disabled screenshot tests",
            left_profile=left_profile,
            right_profile=right_profile,
            left_payload=left_payload,
            right_payload=right_payload,
            left_value=_nested_int(left_payload, "current_snapshot", "disabled_test_count"),
            right_value=_nested_int(right_payload, "current_snapshot", "disabled_test_count"),
        ),
        _numeric_row(
            row_id="changed_files_since_review",
            label="Changed files since latest review",
            left_profile=left_profile,
            right_profile=right_profile,
            left_payload=left_payload,
            right_payload=right_payload,
            left_value=_nested_int(left_payload, "delta_since_last_review", "changed_file_count"),
            right_value=_nested_int(right_payload, "delta_since_last_review", "changed_file_count"),
        ),
        _numeric_row(
            row_id="manual_review_recorded_steps",
            label="Manual-review recorded steps",
            left_profile=left_profile,
            right_profile=right_profile,
            left_payload=left_payload,
            right_payload=right_payload,
            left_value=_nested_int(left_payload, "latest_review", "recorded_steps"),
            right_value=_nested_int(right_payload, "latest_review", "recorded_steps"),
        ),
        _numeric_row(
            row_id="manual_review_pending_steps",
            label="Manual-review pending steps",
            left_profile=left_profile,
            right_profile=right_profile,
            left_payload=left_payload,
            right_payload=right_payload,
            left_value=_nested_int(left_payload, "latest_review", "pending_steps"),
            right_value=_nested_int(right_payload, "latest_review", "pending_steps"),
        ),
    ]


def _risk_delta_summary(left_profile: str, right_profile: str, rows: list[dict[str, Any]]) -> str:
    risk = next((row for row in rows if row.get("id") == "risk_score"), None)
    if not isinstance(risk, dict):
        return f"Cross-car comparison for {left_profile} vs {right_profile}."
    delta = _int_value(risk, "delta")
    if delta > 0:
        direction = f"{left_profile} is {delta} point(s) higher"
    elif delta < 0:
        direction = f"{right_profile} is {abs(delta)} point(s) higher"
    else:
        direction = "risk scores are equal"
    return f"Cross-car comparison for {left_profile} vs {right_profile}; {direction}."


def build_cross_car_comparison(
    *,
    workspace: Path | str | None = None,
    bmw_root: Path | str | None = None,
    left_profile: str | None = None,
    right_profile: str | None = None,
) -> dict[str, Any]:
    root = Path(workspace).resolve() if workspace is not None else Path.cwd()
    left, right = _profile_pair(left_profile, right_profile)
    left_payload = _safe_risk_score(left, root, bmw_root)
    right_payload = _safe_risk_score(right, root, bmw_root)
    rows = _comparison_rows(
        left_profile=left,
        right_profile=right,
        left_payload=left_payload,
        right_payload=right_payload,
    )
    payload = {
        "title": CROSS_CAR_COMPARISON_TITLE,
        "status": _row_status(left_payload, right_payload),
        "data_available": any(str(item.get("status", "")) == "available" for item in (left_payload, right_payload)),
        "workspace": str(root),
        "comparison_axis": "risk-score",
        "widget_label": "Risk Score",
        "left_profile": left,
        "right_profile": right,
        "profiles": [left, right],
        "profile_payloads": {
            left: left_payload,
            right: right_payload,
        },
        "comparison_rows": rows,
        "summary": _risk_delta_summary(left, right, rows),
        "guardrails": list(CROSS_CAR_COMPARISON_GUARDRAILS),
        "confluence_anchors": list(RISK_SCORE_CONFLUENCE_ANCHORS),
        "manual_review_required": True,
        "is_approval": False,
        "note": CROSS_CAR_COMPARISON_NOTE,
    }
    payload["text"] = render_cross_car_comparison_text(payload)
    payload["markdown"] = render_cross_car_comparison_markdown(payload)
    return payload


def render_cross_car_comparison_text(payload: dict[str, Any]) -> str:
    lines = [
        str(payload.get("title", CROSS_CAR_COMPARISON_TITLE)),
        f"Status: {payload.get('status', 'unknown')}",
        f"Profiles: {payload.get('left_profile', '')} vs {payload.get('right_profile', '')}",
        f"Widget: {payload.get('widget_label', 'Risk Score')}",
        str(payload.get("summary", "")),
        "Manual review remains required. Decision: not approval — evidence only.",
    ]
    return "\n".join(lines)


def render_cross_car_comparison_markdown(payload: dict[str, Any]) -> str:
    left = str(payload.get("left_profile", DEFAULT_LEFT_PROFILE))
    right = str(payload.get("right_profile", DEFAULT_RIGHT_PROFILE))
    lines = [
        f"# {payload.get('title', CROSS_CAR_COMPARISON_TITLE)}",
        "",
        f"> {CROSS_CAR_COMPARISON_NOTE}",
        "",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- Widget: `{payload.get('widget_label', 'Risk Score')}`",
        f"- Profiles: `{left}` vs `{right}`",
        f"- Summary: {payload.get('summary', '')}",
        "",
        f"| Signal | {left} | {right} | Delta | Status |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for row in payload.get("comparison_rows", []):
        if not isinstance(row, dict):
            continue
        lines.append(
            "| "
            f"{row.get('label', '')} | "
            f"{row.get('left_value', '')} | "
            f"{row.get('right_value', '')} | "
            f"{row.get('delta_label', '')} | "
            f"`{row.get('status', 'unknown')}` |"
        )
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            *[f"- {guardrail}" for guardrail in payload.get("guardrails", CROSS_CAR_COMPARISON_GUARDRAILS)],
        ]
    )
    return "\n".join(lines).rstrip() + "\n"
