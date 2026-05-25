from __future__ import annotations

from pathlib import Path
from typing import Any

from sg_preflight.dependency_onboarding import build_dependency_onboarding_status
from sg_preflight.manual_review import review_template_for_profile


ONBOARDING_GUIDE_GUARDRAILS = (
    "Manual review remains required.",
    "Decision: not approval — evidence only.",
    "BMW Git access is read-only. SGFX never modifies BMW source.",
    "Activity log is local-only — never posted to Jira, SVN, or BMW Git.",
)
ONBOARDING_CONFLUENCE_ANCHOR = "003_Onboarding/004_Onboarding-for-new-team-members:143-145"


def _workspace(workspace: Path | str) -> Path:
    return Path(workspace).resolve()


def _string_list(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(item).strip() for item in values if str(item).strip()]


def _guide_step(
    *,
    key: str,
    label: str,
    status: str,
    detail: str,
    next_action: str,
    confluence_anchor: str = "",
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "detail": detail,
        "next_action": next_action,
        "confluence_anchor": confluence_anchor,
        "manual_review_required": True,
        "is_approval": False,
    }


def build_onboarding_guide(
    profile_id: str,
    *,
    workspace: Path | str,
    bmw_root: Path | str | None = None,
    dependency_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = _workspace(workspace)
    clean_profile = profile_id.strip()
    setup_status = dependency_status or build_dependency_onboarding_status(workspace=root, bmw_root=bmw_root)
    setup_counts = setup_status.get("counts", {}) if isinstance(setup_status.get("counts"), dict) else {}
    setup_actions = [action for action in setup_status.get("actions", []) if isinstance(action, dict)]
    template = review_template_for_profile(clean_profile, workspace=root)
    setup_step_status = str(setup_status.get("status", "unknown")).strip() or "unknown"
    setup_next_action = (
        "Open Delivery Checklist -> Dependency setup and run only the confirmed setup action."
        if setup_actions
        else "No setup action is pending; continue to evidence pages."
    )
    steps = [
        _guide_step(
            key="dependency-setup",
            label="Dependency setup",
            status=setup_step_status,
            detail=str(setup_status.get("summary", "")),
            next_action=setup_next_action,
            confluence_anchor=ONBOARDING_CONFLUENCE_ANCHOR,
        ),
        _guide_step(
            key="profile-template",
            label="Profile review template",
            status="available",
            detail=(
                f"{template.get('title', 'Review template')} selected for "
                f"{template.get('brand', '')} / {template.get('lane', '')}."
            ),
            next_action="Use the template checklist before recording manual-review verdicts.",
            confluence_anchor=ONBOARDING_CONFLUENCE_ANCHOR,
        ),
        _guide_step(
            key="evidence-pages",
            label="Evidence pages",
            status="not_run",
            detail="Read Delivery Checklist, Screenshot Test State, Risk Score, and Cross-Car Comparison for this car.",
            next_action="Open each evidence page and review local file status before recording findings.",
        ),
        _guide_step(
            key="manual-review",
            label="Manual Review Companion",
            status="not_run",
            detail="Record the seven Quality-Hero review steps locally after inspecting RaCo, Blender, and evidence.",
            next_action="Start a review session, inspect each step, then record operator verdicts.",
        ),
        _guide_step(
            key="handoff",
            label="Operator handoff",
            status="not_run",
            detail="Record the stopping point before handing off to another teammate or before the next walkthrough.",
            next_action="Use Operator Handoff after evidence review or when pausing the run.",
        ),
    ]
    anchors = list(
        dict.fromkeys(
            [
                ONBOARDING_CONFLUENCE_ANCHOR,
                *_string_list(setup_status.get("confluence_anchors", [])),
                *_string_list(template.get("confluence_anchors", [])),
            ]
        )
    )
    incomplete_steps = [step["key"] for step in steps if step["status"] != "available"]
    return {
        "schema_version": 1,
        "profile_id": clean_profile,
        "status": "available",
        "onboarding_status": "available" if setup_step_status == "available" else "incomplete",
        "workspace": str(root),
        "setup_status": setup_status,
        "setup_counts": dict(setup_counts),
        "setup_action_count": len(setup_actions),
        "review_template": template,
        "steps": steps,
        "items": [
            {
                "label": step["label"],
                "status": step["status"],
                "detail": f"{step['detail']} Next: {step['next_action']}",
            }
            for step in steps
        ],
        "operator_focus_steps": incomplete_steps,
        "manual_review_required": True,
        "operator_confirmation_required": bool(setup_actions),
        "records_operator_verdict": False,
        "is_approval": False,
        "summary": (
            f"Onboarding guide prepared {len(steps)} local step(s) for {clean_profile}; "
            f"{len(incomplete_steps)} step(s) still need operator action."
        ),
        "guardrails": list(ONBOARDING_GUIDE_GUARDRAILS),
        "confluence_anchors": anchors,
    }


def render_onboarding_guide_text(payload: dict[str, Any]) -> str:
    lines = [
        f"Onboarding Guide - {payload.get('profile_id', '')}",
        str(payload.get("summary", "")),
        "",
        "Guardrails:",
    ]
    lines.extend(f"- {guardrail}" for guardrail in payload.get("guardrails", []) if str(guardrail).strip())
    lines.extend(["", "Steps:"])
    for step in payload.get("steps", []):
        if not isinstance(step, dict):
            continue
        lines.append(f"- [{step.get('status', 'unknown')}] {step.get('label', '')}: {step.get('next_action', '')}")
    return "\n".join(lines).rstrip() + "\n"


def render_onboarding_guide_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# Onboarding Guide - {payload.get('profile_id', '')}",
        "",
        str(payload.get("summary", "")),
        "",
        "- Manual review required: yes",
        "- Decision: not approval; evidence only.",
        f"- Setup actions requiring confirmation: {payload.get('setup_action_count', 0)}",
    ]
    anchors = payload.get("confluence_anchors", [])
    if isinstance(anchors, list) and anchors:
        lines.extend(["", "## Confluence Anchors"])
        lines.extend(f"- `{anchor}`" for anchor in anchors if str(anchor).strip())
    lines.extend(["", "## Steps"])
    for step in payload.get("steps", []):
        if not isinstance(step, dict):
            continue
        lines.append(f"### {step.get('label', '')}")
        lines.append(f"- Status: `{step.get('status', 'unknown')}`")
        lines.append(f"- Detail: {step.get('detail', '')}")
        lines.append(f"- Next: {step.get('next_action', '')}")
        lines.append("- Manual review required: yes")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
