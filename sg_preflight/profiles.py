from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sg_preflight.bmw_delivery import (
    LANE_IDC23,
    LANE_IDCEVO,
    LANE_UNKNOWN,
    BmwRegistryEntry,
    discover_bmw_models_repo,
    load_bmw_registry,
    resolve_bmw_profile_id,
    resolve_svn_profile_id,
)


DEFAULT_REFERENCE_REPO_ROOT = Path(r"C:\repositories\trunk")
PROFILE_SCOPE_ALL = "all"
PROFILE_SCOPE_DEFAULT = "default"
PROFILE_REGISTRY_DYNAMIC_SOURCE = "models_build_config.yaml"
PROFILE_REGISTRY_FALLBACK_SOURCE = "fallback_static_23"
_LANE_LABELS = {LANE_IDC23: "IDC_23", LANE_IDCEVO: "IDC_EVO", LANE_UNKNOWN: "unknown"}
_BRAND_FOLDER_BY_NAME = {
    "BMW": "BMW",
    "MINI": "MINI",
    "Alpina": "Alpina",
    "MGmbH": "MGmbH",
    "RollsRoyce": "RollsRoyce",
}
_BRAND_SORT_ORDER = {"BMW": 0, "MINI": 1, "Alpina": 2, "MGmbH": 3, "RollsRoyce": 4}
_LANE_SORT_ORDER = {LANE_IDC23: 0, LANE_IDCEVO: 1, LANE_UNKNOWN: 2}
_TYPE_SORT_ORDER = {"build": 0, "retarget": 1}


@dataclass(frozen=True)
class RunProfile:
    profile_id: str
    label: str
    repo_root: Path
    project_root: Path
    project_relative: Path
    config_path: Path
    bmw_smoke_target: str = ""
    bmw_smoke_runner: str = "car_manager.py"
    default_context: dict[str, str] = field(default_factory=dict)
    description: str = ""
    operator_goal: str = ""
    workflow_value: str = ""
    friendly_task: str = ""
    friendly_summary: str = ""
    focus_points: tuple[str, ...] = ()
    mirror_audit_targets: tuple[str, ...] = ()
    reference_repo_root: Path = DEFAULT_REFERENCE_REPO_ROOT
    bmw_profile_id: str = ""
    lane: str = LANE_UNKNOWN
    brand: str = "BMW"
    model_type: str = "build"
    interface_version: int | None = None
    retarget_target: str = ""
    active_build: bool = True
    registry_source: str = PROFILE_REGISTRY_FALLBACK_SOURCE

    def source_repo_root(self) -> Path:
        reference_root = self.reference_repo_root.resolve()
        if reference_root.exists():
            return reference_root
        return self.repo_root.resolve()

    def source_project_root(self) -> Path:
        reference_root = self.reference_repo_root.resolve()
        if reference_root.exists():
            candidate = (reference_root / self.project_relative).resolve()
            if candidate.exists():
                return candidate
        return self.project_root.resolve()

    def source_evidence_source(self) -> str:
        return "real_svn_checkout" if self.source_project_root() != self.project_root.resolve() else "local_svn_mirror"

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "label": self.label,
            "repo_root": str(self.repo_root),
            "project_root": str(self.project_root),
            "project_relative": str(self.project_relative),
            "config_path": str(self.config_path),
            "bmw_smoke_target": self.bmw_smoke_target,
            "bmw_smoke_runner": self.bmw_smoke_runner,
            "default_context": dict(self.default_context),
            "description": self.description,
            "operator_goal": self.operator_goal,
            "workflow_value": self.workflow_value,
            "friendly_task": self.friendly_task,
            "friendly_summary": self.friendly_summary,
            "focus_points": list(self.focus_points),
            "mirror_audit_targets": list(self.mirror_audit_targets),
            "reference_repo_root": str(self.reference_repo_root),
            "bmw_profile_id": self.bmw_profile_id,
            "lane": self.lane,
            "brand": self.brand,
            "type": self.model_type,
            "interface_version": self.interface_version,
            "retarget_target": self.retarget_target,
            "active_build": self.active_build,
            "registry_source": self.registry_source,
            "source_repo_root": str(self.source_repo_root()),
            "source_project_root": str(self.source_project_root()),
            "evidence_source": self.source_evidence_source(),
        }


def _workspace_root(explicit_root: Path | None = None) -> Path:
    return (explicit_root or Path(__file__).resolve().parents[1]).resolve()


def mirror_repo_root(workspace_root: Path | None = None) -> Path:
    return _workspace_root(workspace_root) / "repositories" / "trunk"


def resolve_source_repo_root(
    workspace_root: Path | None = None,
    *,
    reference_repo_root: Path | None = None,
) -> Path:
    reference_root = (reference_repo_root or DEFAULT_REFERENCE_REPO_ROOT).resolve()
    if reference_root.exists():
        return reference_root
    return mirror_repo_root(workspace_root)


def _generic_idcevo_profile_spec(profile_id: str) -> dict[str, Any]:
    return {
        "profile_id": profile_id,
        "label": f"BMW {profile_id} live slice",
        "project_relative": Path(f"Cars_IDCevo/BMW/{profile_id}"),
        "config_relative": Path("config/sg_rules_live.json"),
        "default_context": {
            "car_model": profile_id,
            "trim_line": "Basis",
            "delivery_phase": "svn_live_preflight",
            "review_target": f"{profile_id.lower()}_end_to_end",
            "evidence_source": "local_svn_mirror",
        },
        "description": f"Current IDCevo BMW {profile_id} live preflight slice.",
        "operator_goal": "Catch deterministic SG-side issues early on an additional live BMW slice before review or delivery pressure rises.",
        "workflow_value": "Useful when the team needs the same local preflight surface on a car beyond the original demo trio.",
        "friendly_task": "Run full SG preflight",
        "friendly_summary": "Use this when you need the same SG-side deterministic pass on another IDCevo BMW slice.",
        "focus_points": (
            "Anchor scene sanity on the live IDCevo slice",
            "Pivot_Master versus Module_constants drift",
            "Cross-car references, unused Lua, and shared carpaint signal",
        ),
        "mirror_audit_targets": (
            f"Cars_IDCevo/BMW/{profile_id}",
            "Cars/BMW/CarPaint.json",
        ),
    }


def _generic_classic_profile_spec(profile_id: str) -> dict[str, Any]:
    return {
        "profile_id": profile_id,
        "label": f"BMW {profile_id} classic slice",
        "project_relative": Path(f"Cars/BMW/{profile_id}"),
        "config_relative": Path("config/sg_rules_live_g45.json"),
        "default_context": {
            "car_model": profile_id,
            "trim_line": "Basis",
            "delivery_phase": "svn_live_preflight",
            "review_target": f"{profile_id.lower()}_classic_preflight",
            "evidence_source": "local_svn_mirror",
        },
        "description": f"Classic BMW {profile_id} validation slice.",
        "operator_goal": "Reuse the current classic-family checks on another real mirrored BMW slice without waiting for a new tool branch.",
        "workflow_value": "Useful when classic BMW work needs the same SG-side anchors, constants, and project-sanity path as G45.",
        "friendly_task": "Run classic slice check",
        "friendly_summary": "Use this when you need the existing classic-family preflight on another mirrored BMW slice.",
        "focus_points": (
            "Classic anchor-family coverage",
            "Pivot_Master versus Module_constants drift",
            "Legacy RaCo and project-sanity signal",
        ),
        "mirror_audit_targets": (
            f"Cars/BMW/{profile_id}",
            "Cars/BMW/CarPaint.json",
        ),
    }


def _profile_specs() -> tuple[dict[str, Any], ...]:
    canonical = (
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
            "friendly_task": "Find obvious delivery issues",
            "friendly_summary": "Use this when you want the quickest pass for cross-car references, unused Lua, and shared catalog problems.",
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
            "friendly_task": "Check engineering constants",
            "friendly_summary": "Use this when you need to confirm Pivot_Master and Module_constants still match before delivery pressure starts.",
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
            "friendly_task": "Check anchor setup",
            "friendly_summary": "Use this when you need a quick pass over anchor families and legacy project sanity.",
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

    idcevo_additional = tuple(
        _generic_idcevo_profile_spec(profile_id)
        for profile_id in ("G50", "G58", "G78", "NA0", "NA5", "NA6", "NA7", "NA8", "PINT", "PINT_RUEKO")
    )
    classic_additional = tuple(
        _generic_classic_profile_spec(profile_id)
        for profile_id in ("F70", "F74", "F78", "G48", "G68", "PINT_SUV", "U06", "U10", "U11", "U12")
    )
    return canonical + idcevo_additional + classic_additional


def _fallback_spec_map() -> dict[str, dict[str, Any]]:
    return {str(spec["profile_id"]).upper(): spec for spec in _profile_specs()}


def _lane_from_project_relative(project_relative: Path) -> str:
    first = project_relative.parts[0] if project_relative.parts else ""
    if first == "Cars_IDCevo":
        return LANE_IDCEVO
    if first == "Cars":
        return LANE_IDC23
    return LANE_UNKNOWN


def _profile_from_spec(
    spec: dict[str, Any],
    *,
    root: Path,
    repo_root: Path,
    reference_root: Path,
    registry_source: str = PROFILE_REGISTRY_FALLBACK_SOURCE,
    bmw_profile_id: str = "",
    lane: str = "",
    brand: str = "BMW",
    model_type: str = "build",
    interface_version: int | None = None,
    retarget_target: str = "",
    active_build: bool = True,
) -> RunProfile:
    project_relative = Path(spec["project_relative"])
    default_context = dict(spec["default_context"])
    if (reference_root / project_relative).exists():
        default_context["evidence_source"] = "real_svn_checkout"
    profile_id = str(spec["profile_id"])
    resolved_lane = lane or str(spec.get("lane", "")) or _lane_from_project_relative(project_relative)
    resolved_bmw_profile = bmw_profile_id or str(spec.get("bmw_profile_id", "")) or resolve_bmw_profile_id(profile_id)
    return RunProfile(
        profile_id=profile_id,
        label=str(spec["label"]),
        repo_root=repo_root,
        project_root=repo_root / project_relative,
        project_relative=project_relative,
        config_path=root / Path(spec["config_relative"]),
        bmw_smoke_target=str(spec.get("bmw_smoke_target", "")),
        bmw_smoke_runner=str(spec.get("bmw_smoke_runner", "car_manager.py")),
        default_context=default_context,
        description=str(spec.get("description", "")),
        operator_goal=str(spec.get("operator_goal", "")),
        workflow_value=str(spec.get("workflow_value", "")),
        friendly_task=str(spec.get("friendly_task", "")),
        friendly_summary=str(spec.get("friendly_summary", "")),
        focus_points=tuple(str(item) for item in spec.get("focus_points", ())),
        mirror_audit_targets=tuple(str(item) for item in spec.get("mirror_audit_targets", ())),
        reference_repo_root=reference_root,
        bmw_profile_id=resolved_bmw_profile,
        lane=resolved_lane,
        brand=brand,
        model_type=model_type,
        interface_version=interface_version,
        retarget_target=retarget_target,
        active_build=active_build,
        registry_source=registry_source,
    )


def _brand_folder(brand: str) -> str:
    return _BRAND_FOLDER_BY_NAME.get(brand, brand or "BMW")


def _dynamic_profile_spec(entry: BmwRegistryEntry, fallback_specs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    existing = fallback_specs.get(entry.profile_id.upper())
    if existing is not None and entry.brand == "BMW":
        spec = dict(existing)
    else:
        svn_profile = resolve_svn_profile_id(entry.profile_id)
        brand_folder = _brand_folder(entry.brand)
        project_base = "Cars_IDCevo" if entry.lane == LANE_IDCEVO else "Cars"
        model_label = entry.profile_id
        lane_label = _LANE_LABELS.get(entry.lane, entry.lane)
        type_label = entry.model_type or "model"
        target_label = f" -> {entry.target}" if entry.target else ""
        spec = {
            "profile_id": entry.profile_id,
            "label": f"{entry.brand} {model_label} {lane_label} {type_label}{target_label}",
            "project_relative": Path(project_base) / brand_folder / svn_profile,
            "config_relative": Path("config/sg_rules_live.json")
            if entry.lane == LANE_IDCEVO
            else Path("config/sg_rules_live_g45.json"),
            "default_context": {
                "car_model": svn_profile,
                "trim_line": "Basis",
                "delivery_phase": "svn_live_preflight",
                "review_target": f"{entry.profile_id.lower()}_preflight",
                "evidence_source": "local_svn_mirror",
            },
            "description": f"{entry.brand} {entry.bmw_profile_id} profile from BMW models_build_config.yaml.",
            "operator_goal": "Collect local SGFX evidence for the registered BMW pipeline profile.",
            "workflow_value": "Useful when the operator needs the same local evidence surfaces on a registered pipeline model.",
            "friendly_task": "Run SG preflight",
            "friendly_summary": "Use this registered pipeline profile for local evidence collection.",
            "focus_points": (
                "Registered BMW pipeline model",
                "SVN evidence lookup",
                "Manual review remains required",
            ),
            "mirror_audit_targets": (
                str(Path(project_base) / brand_folder / svn_profile),
                f"Cars/{brand_folder}/CarPaint.json",
            ),
        }
    spec["profile_id"] = entry.profile_id
    spec["bmw_profile_id"] = entry.bmw_profile_id
    spec["lane"] = entry.lane
    spec["brand"] = entry.brand
    spec["model_type"] = entry.model_type
    spec["interface_version"] = entry.interface_version
    spec["retarget_target"] = entry.target
    spec["active_build"] = entry.active_build
    return spec


def _profile_sort_key(profile: RunProfile) -> tuple[int, int, int, str]:
    return (
        _BRAND_SORT_ORDER.get(profile.brand, 99),
        _LANE_SORT_ORDER.get(profile.lane, 99),
        _TYPE_SORT_ORDER.get(profile.model_type, 99),
        profile.profile_id.casefold(),
    )


def _load_dynamic_profiles(
    *,
    root: Path,
    repo_root: Path,
    reference_root: Path,
    bmw_root: Path | str | None,
) -> list[RunProfile]:
    source_root = Path(bmw_root).resolve() if bmw_root is not None else discover_bmw_models_repo(root).resolve()
    entries = load_bmw_registry(source_root)
    if not entries:
        return []
    fallback_specs = _fallback_spec_map()
    profiles = [
        _profile_from_spec(
            _dynamic_profile_spec(entry, fallback_specs),
            root=root,
            repo_root=repo_root,
            reference_root=reference_root,
            registry_source=PROFILE_REGISTRY_DYNAMIC_SOURCE,
            bmw_profile_id=entry.bmw_profile_id,
            lane=entry.lane,
            brand=entry.brand,
            model_type=entry.model_type,
            interface_version=entry.interface_version,
            retarget_target=entry.target,
            active_build=entry.active_build,
        )
        for entry in entries
    ]
    return sorted(profiles, key=_profile_sort_key)


def list_run_profiles(
    workspace_root: Path | None = None,
    *,
    reference_repo_root: Path | None = None,
    bmw_root: Path | str | None = None,
    profile_scope: str = PROFILE_SCOPE_ALL,
) -> list[RunProfile]:
    root = _workspace_root(workspace_root)
    repo_root = mirror_repo_root(root)
    reference_root = (reference_repo_root or DEFAULT_REFERENCE_REPO_ROOT).resolve()

    profiles = _load_dynamic_profiles(root=root, repo_root=repo_root, reference_root=reference_root, bmw_root=bmw_root)
    if profile_scope == PROFILE_SCOPE_DEFAULT and profiles:
        return [profile for profile in profiles if profile.active_build]
    if profiles:
        return profiles

    fallback_profiles = []
    for spec in _profile_specs():
        fallback_profiles.append(
            _profile_from_spec(
                spec,
                root=root,
                repo_root=repo_root,
                reference_root=reference_root,
                registry_source=PROFILE_REGISTRY_FALLBACK_SOURCE,
            )
        )
    return fallback_profiles


def get_run_profile(
    profile_id: str,
    workspace_root: Path | None = None,
    *,
    reference_repo_root: Path | None = None,
    bmw_root: Path | str | None = None,
) -> RunProfile:
    normalized = profile_id.strip().lower()
    for profile in list_run_profiles(workspace_root, reference_repo_root=reference_repo_root, bmw_root=bmw_root):
        if profile.profile_id.lower() == normalized:
            return profile
    supported = ", ".join(
        profile.profile_id for profile in list_run_profiles(workspace_root, reference_repo_root=reference_repo_root, bmw_root=bmw_root)
    )
    raise KeyError(f"Unsupported profile {profile_id!r}. Supported profiles: {supported}")
