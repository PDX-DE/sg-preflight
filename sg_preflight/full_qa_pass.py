from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from sg_preflight.bmw_delivery import read_bmw_screenshot_state
from sg_preflight.cross_car_comparison import build_cross_car_comparison
from sg_preflight.delivery_checklist import read_delivery_checklist
from sg_preflight.delivery_workbook_generation import build_delivery_workbook_trigger
from sg_preflight.manual_review import build_manual_review_assist
from sg_preflight.onboarding_assistant import build_onboarding_guide
from sg_preflight.operator_handoff import build_operator_handoff_snapshot
from sg_preflight.risk_scoring import read_per_car_risk_score
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
_BLOCKING_SOURCE_STATUSES = {"failed", "missing", "unavailable"}


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
    if operator_focus_count:
        return "incomplete"
    return "passed"


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
) -> dict[str, Any]:
    status = _step_status(source_status, operator_focus_count=operator_focus_count, blocker_count=blocker_count)
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
        "operator_confirmation_required": bool(payload.get("operator_confirmation_required", False)),
        "confirmation_items": _confirmation_items(payload),
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
            lambda: read_delivery_checklist(profile_id=profile, workspace=workspace),
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
    trusted_tool_mode: bool = False,
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

    counts = {status: 0 for status in ("passed", "incomplete", "failed", "skipped", "unavailable")}
    for step in steps:
        status = str(step.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
    completed_count = counts.get("passed", 0)
    blocking_count = counts.get("failed", 0) + counts.get("unavailable", 0)
    focus_count = counts.get("incomplete", 0)
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
        "operator_confirmation_required": bool(confirmations) and not trusted_tool_mode,
        "manual_review_required": True,
        "records_operator_verdict": False,
        "is_approval": False,
        "guardrails": list(FULL_QA_PASS_GUARDRAILS),
        "confluence_anchors": list(FULL_QA_PASS_CONFLUENCE_ANCHORS),
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
        f"Trusted tool mode: {payload.get('trusted_tool_mode', False)}",
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
        f"- Trusted tool mode: `{payload.get('trusted_tool_mode', False)}`",
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
