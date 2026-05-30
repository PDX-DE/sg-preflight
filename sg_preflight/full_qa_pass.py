from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from sg_preflight.bmw_delivery import read_bmw_screenshot_state
from sg_preflight.bmw_pipeline_auto_fix import MISSING_ACTUAL_DIAGNOSTIC_ACTION_ID
from sg_preflight.cross_car_comparison import build_cross_car_comparison
from sg_preflight.delivery_checklist import read_delivery_checklist
from sg_preflight.delivery_workbook_generation import GENERATION_TYPICAL_RANGE_LABEL, build_delivery_workbook_trigger
from sg_preflight.manual_review import build_manual_review_assist
from sg_preflight.onboarding_assistant import build_onboarding_guide
from sg_preflight.operator_handoff import build_operator_handoff_snapshot
from sg_preflight.risk_scoring import read_per_car_risk_score
from sg_preflight.screenshot_capture import (
    SCREENSHOT_CAPTURE_ACTION_ID,
    SCREENSHOT_CAPTURE_ACTION_LABEL,
    SCREENSHOT_CAPTURE_TIMEOUT_SECONDS,
    check_screenshot_capture_environment,
)
from sg_preflight.team_digest_board import build_team_daily_digest_board


FULL_QA_PASS_GUARDRAILS = (
    "Manual review remains required.",
    "Decision: not approval — evidence only.",
    "BMW Git access is read-only. SGFX never modifies BMW source.",
    "Activity log is local-only — never posted to Jira, SVN, or BMW Git.",
)
FULL_QA_PASS_CONFLUENCE_ANCHORS = (
    "PDX_" + "SER" + "GFX/139_3D-Car/298_Quality-Hero-How-to-review-the-3D-car/page.txt",
    "PDX_"
    + "SER"
    + "GFX/311_Delivery-process/312_3D-Car---Delivery-and-Integration/"
    "315_How-to-3D-Cars-Delivery-Checklist----v0/page.txt",
    "PDX_"
    + "SER"
    + "GFX/016_Project-Management/024_How-to...-Seriesgraphics/029_Regular-Meetings/030_SG-Daily/page.txt",
)
_QUALITY_HERO_ANCHOR = FULL_QA_PASS_CONFLUENCE_ANCHORS[0]
_DELIVERY_ANCHOR = FULL_QA_PASS_CONFLUENCE_ANCHORS[1]
_SG_DAILY_ANCHOR = FULL_QA_PASS_CONFLUENCE_ANCHORS[2]
_SCREENSHOT_ANCHOR = (
    "PDX_"
    + "SER"
    + "GFX/139_3D-Car/225_3D-Car---RaCo-Implementation/226_How-to-screenshottest/page.txt"
)
FULL_QA_STEP_CONFLUENCE_ANCHORS = {
    "onboarding-guide": (_QUALITY_HERO_ANCHOR,),
    "delivery-checklist": (_DELIVERY_ANCHOR,),
    "delivery-workbook-trigger": (_DELIVERY_ANCHOR,),
    "screenshot-test-state": (_SCREENSHOT_ANCHOR,),
    "risk-score": (_QUALITY_HERO_ANCHOR,),
    "cross-car-comparison": (_QUALITY_HERO_ANCHOR,),
    "team-digest-board": (_SG_DAILY_ANCHOR,),
    "manual-review-assist": (_QUALITY_HERO_ANCHOR,),
    "operator-handoff": (_SG_DAILY_ANCHOR,),
}
_BLOCKING_SOURCE_STATUSES = {"failed", "missing", "unavailable"}
_INCOMPLETE_SOURCE_STATUSES = {"incomplete", "not_run", "pending", "not_available", "no_expected_baselines"}
FULL_QA_TRUSTED_MODE_NOTE = (
    "Automatic mode runs local tool actions when available. Jira REST and SVN gates still always prompt. "
    "Switch Automatic mode off for Manual mode."
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clean_profile(profile_id: str) -> str:
    return str(profile_id or "").strip().upper() or "PROFILE"


def _status(value: object, default: str = "unknown") -> str:
    text = str(value or "").strip().casefold()
    return text or default


def _summary(payload: dict[str, Any], fallback: str) -> str:
    return str(payload.get("summary", "") or payload.get("note", "") or fallback).strip()


def _step_status(source_status: str, *, operator_focus_count: int = 0, blocker_count: int = 0) -> str:
    if source_status == "failed":
        return "failed"
    if blocker_count or source_status in _BLOCKING_SOURCE_STATUSES:
        return "incomplete"
    if source_status in _INCOMPLETE_SOURCE_STATUSES:
        return "incomplete"
    if operator_focus_count:
        return "incomplete"
    return "passed"


def _confirmation_item_from_action(action: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_id": str(action.get("id", "")),
        "step_id": str(action.get("step_id", "")),
        "label": str(action.get("label", "Operator confirmation")),
        "status": "confirmation_pending",
        "detail": str(action.get("confirmation_message", "") or action.get("next_action", "")),
        "manual_review_required": True,
        "is_approval": False,
    }


def _confirmation_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not bool(payload.get("operator_confirmation_required", False)):
        return []
    return [
        {
            "action_id": str(payload.get("action_id", "")),
            "label": str(payload.get("label", "Operator confirmation")),
            "status": "incomplete",
            "detail": str(payload.get("confirmation_message", "") or payload.get("next_action", "")),
            "manual_review_required": True,
            "is_approval": False,
        }
    ]


def _action_prompt(label: str, detail: str) -> str:
    return (
        f"{label}: {detail} "
        "Manual review remains required. Decision: not approval — evidence only."
    ).strip()


def _step_confluence_anchors(step_id: str) -> list[str]:
    anchors = FULL_QA_STEP_CONFLUENCE_ANCHORS.get(step_id, (_QUALITY_HERO_ANCHOR,))
    return [anchor for anchor in anchors if str(anchor).strip()]


def _delivery_workbook_action(payload: dict[str, Any], *, trusted_tool_mode: bool) -> dict[str, Any] | None:
    if not bool(payload.get("can_start", False)):
        return None
    confirmation_message = str(payload.get("confirmation_message", "") or payload.get("next_action", ""))
    return {
        "id": str(payload.get("action_id", "generate-delivery-workbook")),
        "step_id": "delivery-workbook-trigger",
        "kind": "subprocess",
        "label": str(payload.get("label", "Generate delivery workbook")),
        "requires_confirmation": not trusted_tool_mode,
        "auto_confirm_allowed": True,
        "trusted_auto_confirm": bool(trusted_tool_mode),
        "hard_gate": "none",
        "timeout_seconds": int(payload.get("timeout_seconds", 600) or 600),
        "typical_range": str(payload.get("typical_range", GENERATION_TYPICAL_RANGE_LABEL)),
        "confirmation_message": _action_prompt(
            "Generate delivery workbook",
            confirmation_message or "Run the local BMW pipeline export helper for this profile.",
        ),
        "target_paths": [
            str(payload.get("preflight", {}).get("target_write_path", "")),
            str(payload.get("preflight", {}).get("native_output_path", "")),
        ],
        "enabled": True,
        "manual_review_required": True,
        "is_approval": False,
    }


def _screenshot_capture_action(
    profile_id: str,
    workspace: Path,
    bmw_root: Path | str | None,
    *,
    trusted_tool_mode: bool,
) -> dict[str, Any] | None:
    preflight = check_screenshot_capture_environment(profile_id=profile_id, workspace=workspace, bmw_root=bmw_root)
    can_run = bool(preflight.get("can_run", False))
    return {
        "id": SCREENSHOT_CAPTURE_ACTION_ID,
        "step_id": "screenshot-test-state",
        "kind": "subprocess",
        "label": SCREENSHOT_CAPTURE_ACTION_LABEL,
        "requires_confirmation": not trusted_tool_mode and can_run,
        "auto_confirm_allowed": can_run,
        "trusted_auto_confirm": bool(trusted_tool_mode and can_run),
        "hard_gate": "none",
        "timeout_seconds": SCREENSHOT_CAPTURE_TIMEOUT_SECONDS,
        "typical_range": "typical 2-10 min",
        "confirmation_message": _action_prompt(
            "Capture screenshots",
            (
                str(preflight.get("confirmation_message", "Run the BMW screenshot capture helper for this profile."))
                + " The BMW Ramses renderer may show a black offscreen-rendering window while screenshots are captured; "
                "SGFX streams the pipeline output here."
            ),
        ),
        "target_paths": [
            str(preflight.get("target_write_path", "")),
            str(preflight.get("native_output_path", "")),
        ],
        "enabled": can_run,
        "disabled_reason": str(preflight.get("disabled_reason", "")),
        "preflight": preflight,
        "manual_review_required": True,
        "is_approval": False,
    }


def _missing_actual_diagnostic_action(payload: dict[str, Any]) -> dict[str, Any] | None:
    expected = _int_value(payload, "expected_count")
    actual = _int_value(payload, "actual_count")
    missing_candidates = _int_value(payload, "missing_candidate_count")
    if expected <= 0 or (actual > 0 and missing_candidates <= 0):
        return None
    project_root = str(payload.get("car_root", "")).strip()
    expected_root = str(payload.get("expected_root", "")).strip()
    actuals_root = str(payload.get("actuals_root", "")).strip()
    diff_root = str(payload.get("diff_root", "")).strip()
    enabled = bool(project_root and expected_root)
    return {
        "id": MISSING_ACTUAL_DIAGNOSTIC_ACTION_ID,
        "step_id": "screenshot-test-state",
        "kind": "diagnostic_chain",
        "label": "Diagnose missing actuals",
        "summary": "Build the missing-actual diagnostic chain; read-refresh and retry stay confirmation-gated.",
        "requires_confirmation": False,
        "auto_confirm_allowed": False,
        "trusted_auto_confirm": False,
        "hard_gate": "read_refresh_and_retry_stay_gated",
        "typical_range": "typical <1 min",
        "project_root": project_root,
        "expected_root": expected_root,
        "candidate_roots": [actuals_root] if actuals_root else [],
        "diff_reference_roots": [diff_root] if diff_root else [],
        "target_paths": [path for path in (project_root, expected_root, actuals_root, diff_root) if path],
        "enabled": enabled,
        "disabled_reason": "" if enabled else "Missing BMW project root or expected screenshot root.",
        "manual_review_required": True,
        "is_approval": False,
    }


def _operator_action(
    *,
    action_id: str,
    step_id: str,
    label: str,
    kind: str,
    summary: str,
    target_page: str = "",
) -> dict[str, Any]:
    return {
        "id": action_id,
        "step_id": step_id,
        "kind": kind,
        "label": label,
        "summary": summary,
        "requires_confirmation": False,
        "auto_confirm_allowed": False,
        "trusted_auto_confirm": False,
        "hard_gate": "none",
        "target_page": target_page,
        "enabled": True,
        "manual_review_required": True,
        "is_approval": False,
    }


def _step_inline_actions(
    *,
    step_id: str,
    payload: dict[str, Any],
    profile_id: str,
    workspace: Path,
    bmw_root: Path | str | None,
    trusted_tool_mode: bool,
    operator_focus_count: int,
) -> list[dict[str, Any]]:
    if step_id == "delivery-workbook-trigger":
        action = _delivery_workbook_action(payload, trusted_tool_mode=trusted_tool_mode)
        return [action] if action is not None else []
    if step_id == "screenshot-test-state":
        expected = _int_value(payload, "expected_count")
        actual = _int_value(payload, "actual_count")
        diff = _int_value(payload, "diff_count")
        actions: list[dict[str, Any]] = []
        if expected > 0 and actual == 0 and diff == 0:
            action = _screenshot_capture_action(
                profile_id,
                workspace,
                bmw_root,
                trusted_tool_mode=trusted_tool_mode,
            )
            if action is not None:
                actions.append(action)
        diagnostic_action = _missing_actual_diagnostic_action(payload)
        if diagnostic_action is not None:
            actions.append(diagnostic_action)
        return actions
    if step_id == "risk-score" and operator_focus_count:
        signals = [
            signal
            for signal in payload.get("signals", [])
            if isinstance(signal, dict) and int(signal.get("weight", 0) or 0) > 0
        ]
        return [
            _operator_action(
                action_id="risk-reviewed",
                step_id=step_id,
                label="I've reviewed",
                kind="operator_ack",
                summary=f"Operator reviewed {len(signals)} active risk signal(s).",
            ),
            _operator_action(
                action_id="open-risk-score",
                step_id=step_id,
                label="Investigate further",
                kind="navigate",
                summary="Open the Risk Score page for details.",
                target_page="risk-score",
            ),
        ]
    if step_id == "manual-review-assist" and operator_focus_count:
        return [
            _operator_action(
                action_id="manual-review-recorded",
                step_id=step_id,
                label="I've recorded verdicts",
                kind="verify_manual_review",
                summary="Re-read manual-review state and pass only if all required verdicts are recorded.",
            ),
            _operator_action(
                action_id="open-manual-review",
                step_id=step_id,
                label="Continue reviewing",
                kind="navigate",
                summary="Open the Manual Review Companion page.",
                target_page="manual-review",
            ),
        ]
    if step_id == "operator-handoff" and operator_focus_count:
        return [
            _operator_action(
                action_id="record-handoff",
                step_id=step_id,
                label="Mark stopping point here",
                kind="handoff_form",
                summary="Record a local-only shift handoff for this profile.",
            )
        ]
    return []


def _int_value(payload: dict[str, Any], key: str) -> int:
    try:
        return int(payload.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _step(
    *,
    step_id: str,
    label: str,
    payload: dict[str, Any],
    source_status: str,
    summary: str,
    operator_focus_count: int = 0,
    blocker_count: int = 0,
    delicate: bool = False,
    critical: bool = False,
    inline_actions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    status = _step_status(source_status, operator_focus_count=operator_focus_count, blocker_count=blocker_count)
    actions = list(inline_actions or [])
    action_confirmations = [
        _confirmation_item_from_action(action)
        for action in actions
        if bool(action.get("requires_confirmation", False))
    ]
    if action_confirmations:
        status = "confirmation_pending"
    payload_confirmations = [] if actions else _confirmation_items(payload)
    return {
        "id": step_id,
        "label": label,
        "status": status,
        "source_status": source_status,
        "summary": summary,
        "operator_focus_count": operator_focus_count,
        "blocker_count": blocker_count,
        "delicate": delicate,
        "critical": critical,
        "operator_confirmation_required": bool(payload_confirmations) or bool(action_confirmations),
        "confirmation_items": [*payload_confirmations, *action_confirmations],
        "inline_actions": actions,
        "confluence_anchors": _step_confluence_anchors(step_id),
        "manual_review_required": True,
        "records_operator_verdict": False,
        "is_approval": False,
        "payload": payload,
    }


def _failed_step(step_id: str, label: str, exc: Exception) -> dict[str, Any]:
    return {
        "id": step_id,
        "label": label,
        "status": "failed",
        "source_status": "failed",
        "summary": f"{label} could not be read: {exc}",
        "operator_focus_count": 0,
        "blocker_count": 1,
        "delicate": False,
        "critical": True,
        "operator_confirmation_required": False,
        "confirmation_items": [],
        "inline_actions": [],
        "confluence_anchors": _step_confluence_anchors(step_id),
        "manual_review_required": True,
        "records_operator_verdict": False,
        "is_approval": False,
        "payload": {"status": "failed", "summary": str(exc), "manual_review_required": True, "is_approval": False},
    }


def _skipped_step(step_id: str, label: str, halted_label: str) -> dict[str, Any]:
    return {
        "id": step_id,
        "label": label,
        "status": "skipped",
        "source_status": "skipped",
        "summary": f"Skipped because {halted_label} needs operator attention first.",
        "operator_focus_count": 0,
        "blocker_count": 0,
        "delicate": False,
        "critical": False,
        "operator_confirmation_required": False,
        "confirmation_items": [],
        "inline_actions": [],
        "confluence_anchors": _step_confluence_anchors(step_id),
        "manual_review_required": True,
        "records_operator_verdict": False,
        "is_approval": False,
        "payload": {"status": "skipped", "manual_review_required": True, "is_approval": False},
    }


def _step_defs(
    profile_id: str,
    workspace: Path,
    bmw_root: Path | str | None,
    comparison_profile: str,
    trusted_tool_mode: bool,
) -> list[tuple[str, str, Callable[[], dict[str, Any]], bool, Callable[[dict[str, Any]], int], Callable[[dict[str, Any]], int], bool]]:
    profile = _clean_profile(profile_id)
    compare = _clean_profile(comparison_profile)
    return [
        (
            "onboarding-guide",
            "Onboarding guide",
            lambda: build_onboarding_guide(profile, workspace=workspace, bmw_root=bmw_root),
            True,
            lambda payload: len(payload.get("operator_focus_steps", [])) if _status(payload.get("onboarding_status")) != "available" else 0,
            lambda _payload: 0,
            False,
        ),
        (
            "delivery-checklist",
            "Delivery checklist",
            lambda: read_delivery_checklist(
                profile_id=profile,
                workspace=workspace,
                bmw_root=bmw_root,
                enable_auto_generate=True,
            ),
            True,
            lambda _payload: 0,
            lambda _payload: 0,
            False,
        ),
        (
            "delivery-workbook-trigger",
            "Delivery workbook trigger",
            lambda: build_delivery_workbook_trigger(
                profile_id=profile,
                workspace=workspace,
                bmw_root=bmw_root,
                trusted_tool_mode=trusted_tool_mode,
            ),
            True,
            lambda payload: 0 if bool(payload.get("can_start", False)) else len(payload.get("blockers", [])),
            lambda payload: len(payload.get("blockers", [])),
            True,
        ),
        (
            "screenshot-test-state",
            "Screenshot test state",
            lambda: read_bmw_screenshot_state(profile, workspace=workspace, bmw_root=bmw_root, sg_project_root=workspace),
            False,
            lambda _payload: 0,
            lambda _payload: 0,
            False,
        ),
        (
            "risk-score",
            "Risk score",
            lambda: read_per_car_risk_score(profile, workspace=workspace, bmw_root=bmw_root),
            False,
            lambda payload: len(
                [
                    signal
                    for signal in payload.get("signals", [])
                    if isinstance(signal, dict) and int(signal.get("weight", 0) or 0) > 0
                ]
            ),
            lambda _payload: 0,
            False,
        ),
        (
            "cross-car-comparison",
            "Cross-car comparison",
            lambda: build_cross_car_comparison(
                workspace=workspace,
                bmw_root=bmw_root,
                left_profile=profile,
                right_profile=compare,
            ),
            False,
            lambda _payload: 0,
            lambda _payload: 0,
            False,
        ),
        (
            "team-digest-board",
            "Team digest board",
            lambda: build_team_daily_digest_board(
                workspace=workspace,
                bmw_root=bmw_root,
                profiles=(profile, compare),
            ),
            False,
            lambda _payload: 0,
            lambda _payload: 0,
            False,
        ),
        (
            "manual-review-assist",
            "Manual review assist",
            lambda: build_manual_review_assist(profile, workspace=workspace),
            False,
            lambda payload: len(payload.get("operator_focus_steps", [])),
            lambda _payload: 0,
            False,
        ),
        (
            "operator-handoff",
            "Operator handoff",
            lambda: build_operator_handoff_snapshot(workspace=workspace, profile_id=profile),
            False,
            lambda payload: 0 if _status(payload.get("status")) == "recorded" else 1,
            lambda _payload: 0,
            False,
        ),
    ]


def build_full_qa_pass(
    profile_id: str,
    *,
    workspace: Path | str | None = None,
    bmw_root: Path | str | None = None,
    comparison_profile: str = "G65",
    trusted_tool_mode: bool = True,
    halt_on_flagged_issue: bool = True,
) -> dict[str, Any]:
    root = Path(workspace).resolve() if workspace is not None else Path.cwd()
    profile = _clean_profile(profile_id)
    halted = False
    halted_step = ""
    halt_reason = ""
    steps: list[dict[str, Any]] = []
    confirmations: list[dict[str, Any]] = []

    for step_id, label, reader, critical, focus_count, blocker_count, delicate in _step_defs(
        profile,
        root,
        bmw_root,
        comparison_profile,
        trusted_tool_mode,
    ):
        if halted and halt_on_flagged_issue:
            steps.append(_skipped_step(step_id, label, halted_step))
            continue
        try:
            payload = reader()
        except Exception as exc:  # noqa: BLE001
            step = _failed_step(step_id, label, exc)
        else:
            source_status = _status(payload.get("trigger_status", payload.get("status", "unknown")))
            focus = focus_count(payload)
            blockers = blocker_count(payload)
            inline_actions = _step_inline_actions(
                step_id=step_id,
                payload=payload,
                profile_id=profile,
                workspace=root,
                bmw_root=bmw_root,
                trusted_tool_mode=trusted_tool_mode,
                operator_focus_count=focus,
            )
            step = _step(
                step_id=step_id,
                label=label,
                payload=payload,
                source_status=source_status,
                summary=_summary(payload, f"{label} read locally."),
                operator_focus_count=focus,
                blocker_count=blockers,
                delicate=delicate,
                critical=critical,
                inline_actions=inline_actions,
            )
        steps.append(step)
        confirmations.extend(step.get("confirmation_items", []))
        if (
            halt_on_flagged_issue
            and not halted
            and bool(step.get("critical", False))
            and str(step.get("status", "")) in {"failed", "unavailable", "incomplete"}
        ):
            halted = True
            halted_step = str(step.get("label", label))
            halt_reason = str(step.get("summary", "A blocking issue needs operator attention."))

    counts = {status: 0 for status in ("passed", "confirmation_pending", "incomplete", "failed", "skipped", "unavailable")}
    for step in steps:
        status = str(step.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
    completed_count = counts.get("passed", 0)
    blocking_count = counts.get("failed", 0) + counts.get("unavailable", 0)
    focus_count = counts.get("incomplete", 0) + counts.get("confirmation_pending", 0)
    overall_status = "passed"
    if blocking_count:
        overall_status = "failed"
    elif halted or focus_count or confirmations:
        overall_status = "incomplete"
    progress_percent = int(round((completed_count / max(1, len(steps))) * 100))
    summary = (
        f"Full QA pass prepared {completed_count}/{len(steps)} step(s) for {profile}; "
        f"{focus_count} step(s) need operator focus and {len(confirmations)} confirmation item(s) are pending."
    )
    return {
        "schema_version": 1,
        "profile_id": profile,
        "comparison_profile": _clean_profile(comparison_profile),
        "workspace": str(root),
        "started_at_utc": _utc_now(),
        "status": overall_status,
        "run_status": overall_status,
        "trusted_tool_mode": bool(trusted_tool_mode),
        "halt_on_flagged_issue": bool(halt_on_flagged_issue),
        "halted": bool(halted),
        "halted_step": halted_step,
        "halt_reason": halt_reason,
        "progress": {
            "completed_steps": completed_count,
            "total_steps": len(steps),
            "percent": progress_percent,
        },
        "counts": counts,
        "steps": steps,
        "confirmation_items": confirmations,
        "trusted_auto_actions": [
            action
            for step in steps
            for action in step.get("inline_actions", [])
            if isinstance(action, dict) and bool(action.get("trusted_auto_confirm", False))
        ],
        "operator_confirmation_required": bool(confirmations) and not trusted_tool_mode,
        "manual_review_required": True,
        "records_operator_verdict": False,
        "is_approval": False,
        "guardrails": list(FULL_QA_PASS_GUARDRAILS),
        "confluence_anchors": list(FULL_QA_PASS_CONFLUENCE_ANCHORS),
        "trusted_tool_mode_note": FULL_QA_TRUSTED_MODE_NOTE,
        "summary": summary if not halted else f"{summary} Halted at {halted_step}: {halt_reason}",
        "next_action": (
            f"Resolve or confirm {halted_step}, then run the pass again."
            if halted
            else "Review incomplete steps and record manual-review verdicts only after operator inspection."
        ),
    }


def render_full_qa_pass_text(payload: dict[str, Any]) -> str:
    lines = [
        f"Run full QA pass - {payload.get('profile_id', '')}",
        str(payload.get("summary", "")),
        f"Status: {payload.get('status', 'unknown')}",
        f"Automatic mode: {payload.get('trusted_tool_mode', False)}",
        f"Operator confirmation required: {payload.get('operator_confirmation_required', False)}",
        "",
        "Guardrails:",
    ]
    lines.extend(f"- {guardrail}" for guardrail in payload.get("guardrails", []) if str(guardrail).strip())
    lines.extend(["", "Steps:"])
    for step in payload.get("steps", []):
        if isinstance(step, dict):
            lines.append(f"- [{step.get('status', 'unknown')}] {step.get('label', '')}: {step.get('summary', '')}")
    return "\n".join(lines).rstrip() + "\n"


def render_full_qa_pass_markdown(payload: dict[str, Any]) -> str:
    progress = payload.get("progress", {}) if isinstance(payload.get("progress"), dict) else {}
    lines = [
        f"# Run full QA pass - {payload.get('profile_id', '')}",
        "",
        str(payload.get("summary", "")),
        "",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- Progress: `{progress.get('completed_steps', 0)}/{progress.get('total_steps', 0)}`",
        f"- Automatic mode: `{payload.get('trusted_tool_mode', False)}`",
        f"- Operator confirmation required: `{payload.get('operator_confirmation_required', False)}`",
        "- Manual review required: yes",
        "- Decision: not approval; evidence only.",
        "",
        "## Guardrails",
    ]
    lines.extend(f"- {guardrail}" for guardrail in payload.get("guardrails", []) if str(guardrail).strip())
    lines.extend(["", "## Steps"])
    for step in payload.get("steps", []):
        if not isinstance(step, dict):
            continue
        lines.append(f"- `{step.get('status', 'unknown')}` **{step.get('label', '')}**: {step.get('summary', '')}")
    confirmations = [item for item in payload.get("confirmation_items", []) if isinstance(item, dict)]
    if confirmations:
        lines.extend(["", "## Confirmation Items"])
        lines.extend(f"- `{item.get('status', 'unknown')}` {item.get('label', '')}: {item.get('detail', '')}" for item in confirmations)
    return "\n".join(lines).rstrip() + "\n"
