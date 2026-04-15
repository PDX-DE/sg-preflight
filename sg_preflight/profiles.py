from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_REFERENCE_REPO_ROOT = Path(r"C:\repositories\trunk")


@dataclass(frozen=True)
class RunProfile:
    profile_id: str
    label: str
    repo_root: Path
    project_root: Path
    config_path: Path
    default_context: dict[str, str] = field(default_factory=dict)
    description: str = ""
    operator_goal: str = ""
    workflow_value: str = ""
    focus_points: tuple[str, ...] = ()
    mirror_audit_targets: tuple[str, ...] = ()
    reference_repo_root: Path = DEFAULT_REFERENCE_REPO_ROOT

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "label": self.label,
            "repo_root": str(self.repo_root),
            "project_root": str(self.project_root),
            "config_path": str(self.config_path),
            "default_context": dict(self.default_context),
            "description": self.description,
            "operator_goal": self.operator_goal,
            "workflow_value": self.workflow_value,
            "focus_points": list(self.focus_points),
            "mirror_audit_targets": list(self.mirror_audit_targets),
            "reference_repo_root": str(self.reference_repo_root),
        }


def _workspace_root(explicit_root: Path | None = None) -> Path:
    return (explicit_root or Path(__file__).resolve().parents[1]).resolve()


def _profile_specs() -> tuple[dict[str, Any], ...]:
    return (
        {
            "profile_id": "G70",
            "label": "BMW G70 live slice",
            "project_relative": Path("Cars_IDCevo/BMW/G70"),
            "config_relative": Path("config/sg_rules_live.json"),
            "default_context": {
                "car_model": "G70",
                "trim_line": "Basis",
                "delivery_phase": "svn_live_preflight",
                "review_target": "g70_end_to_end",
                "evidence_source": "local_svn_mirror",
            },
            "description": "Current IDCevo BMW G70 live preflight slice.",
            "operator_goal": "Catch cross-car contamination, unused Lua, and shared catalog issues before rack or review.",
            "workflow_value": "Best when QA or integration needs a quick answer about obvious preventable findings.",
            "focus_points": (
                "Cross-car references into another BMW live slice",
                "Unused Lua files that survived into the project root",
                "Shared BMW CarPaint catalog duplication",
            ),
            "mirror_audit_targets": (
                "Cars_IDCevo/BMW/G70",
                "Cars/BMW/CarPaint.json",
            ),
        },
        {
            "profile_id": "G65",
            "label": "BMW G65 live slice",
            "project_relative": Path("Cars_IDCevo/BMW/G65"),
            "config_relative": Path("config/sg_rules_live_g65.json"),
            "default_context": {
                "car_model": "G65",
                "trim_line": "Basis",
                "delivery_phase": "svn_live_preflight",
                "review_target": "g65_end_to_end",
                "evidence_source": "local_svn_mirror",
            },
            "description": "Current IDCevo BMW G65 live preflight slice.",
            "operator_goal": "Surface engineering drift between Pivot_Master and exported Module_constants early.",
            "workflow_value": "Best when TA, QA, or integration needs hard evidence for value mismatches before delivery pressure starts.",
            "focus_points": (
                "Rim diameter mismatches by trim",
                "Tire width drift in exported constants",
                "Low-noise baseline for constants-focused triage",
            ),
            "mirror_audit_targets": (
                "Cars_IDCevo/BMW/G65",
                "Cars/BMW/CarPaint.json",
            ),
        },
        {
            "profile_id": "G45",
            "label": "BMW G45 classic slice",
            "project_relative": Path("Cars/BMW/G45"),
            "config_relative": Path("config/sg_rules_live_g45.json"),
            "default_context": {
                "car_model": "G45",
                "trim_line": "Basis",
                "delivery_phase": "svn_live_preflight",
                "review_target": "g45_anchor_family_preflight",
                "evidence_source": "local_svn_mirror",
            },
            "description": "Classic BMW G45 anchor-family validation slice.",
            "operator_goal": "Validate classic anchor families and legacy project sanity without depending on the IDCevo slice layout.",
            "workflow_value": "Best when you need a clean demonstration of anchor-family coverage and legacy-version signal.",
            "focus_points": (
                "Classic scale, tire-pressure, and sensor anchor families",
                "Legacy RaCo version policy checks",
                "Shared BMW CarPaint catalog duplication",
            ),
            "mirror_audit_targets": (
                "Cars/BMW/G45",
                "Cars/BMW/CarPaint.json",
            ),
        },
    )


def list_run_profiles(
    workspace_root: Path | None = None,
    *,
    reference_repo_root: Path | None = None,
) -> list[RunProfile]:
    root = _workspace_root(workspace_root)
    repo_root = root / "repositories" / "trunk"
    reference_root = (reference_repo_root or DEFAULT_REFERENCE_REPO_ROOT).resolve()

    profiles = []
    for spec in _profile_specs():
        profiles.append(
            RunProfile(
                profile_id=str(spec["profile_id"]),
                label=str(spec["label"]),
                repo_root=repo_root,
                project_root=repo_root / Path(spec["project_relative"]),
                config_path=root / Path(spec["config_relative"]),
                default_context=dict(spec["default_context"]),
                description=str(spec.get("description", "")),
                operator_goal=str(spec.get("operator_goal", "")),
                workflow_value=str(spec.get("workflow_value", "")),
                focus_points=tuple(str(item) for item in spec.get("focus_points", ())),
                mirror_audit_targets=tuple(str(item) for item in spec.get("mirror_audit_targets", ())),
                reference_repo_root=reference_root,
            )
        )
    return profiles


def get_run_profile(
    profile_id: str,
    workspace_root: Path | None = None,
    *,
    reference_repo_root: Path | None = None,
) -> RunProfile:
    normalized = profile_id.strip().lower()
    for profile in list_run_profiles(workspace_root, reference_repo_root=reference_repo_root):
        if profile.profile_id.lower() == normalized:
            return profile
    supported = ", ".join(profile.profile_id for profile in list_run_profiles(workspace_root))
    raise KeyError(f"Unsupported profile {profile_id!r}. Supported profiles: {supported}")
