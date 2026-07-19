"""Catalog of available operator QA actions (preflight, repo checker, unused resources, delivery checklist, BMW smoke) and their per-profile resolution."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sg_preflight.bmw_process import bmw_interface_smoke_commands
from sg_preflight.profiles import (
    RunProfile,
    list_run_profiles,
    mirror_repo_root,
    resolve_source_repo_root,
)
from sg_preflight.services import prerequisite_status, workspace_root


SAFE_PREFLIGHT_PACKS = ("anchors", "constants", "carpaints", "project_sanity")

def operator_ui_actions_root(explicit_root: Path | None = None) -> Path:
    return workspace_root(explicit_root) / "out" / "operator-ui" / "actions"

def _repo_checker_paths(mirror_root: Path) -> tuple[Path, Path]:
    checkers_root = mirror_root / ".pdx" / "checkers"
    return (
        checkers_root / "code_style_checker" / "check_all_styles.py",
        checkers_root / "executeChecks.py",
    )

def _repo_checker_command_preview(style_script: Path, checker_script: Path, target: Path) -> str:
    return (
        f"{sys.executable} {style_script} {target} && "
        f"{sys.executable} {checker_script} {target}"
    )

def _unused_resources_script_path(mirror_root: Path) -> Path:
    return mirror_root / ".pdx" / "checkers" / "printNotUsedResources.py"

def _unused_resources_inputs(project_root: Path) -> tuple[Path, Path]:
    return project_root / "resources", project_root

def _unused_resources_command_preview(script: Path, project_root: Path) -> str:
    resources_root, rca_root = _unused_resources_inputs(project_root)
    return f"{sys.executable} {script} --res {resources_root} --rca {rca_root}"

def _delivery_checklist_paths(mirror_root: Path) -> dict[str, Path]:
    checklist_root = mirror_root / ".pdx" / "checkers" / "deliveryChecklist"
    return {
        "root": checklist_root,
        "tool": checklist_root / "deliveryChecklist.exe",
        "helper": checklist_root / "deliveryChecklist.py",
        "readme": checklist_root / "README.md",
        "camera_crane": checklist_root / "cameraCrane.lua",
    }

def _delivery_checklist_command_preview(profile: RunProfile) -> str:
    return (
        "internal: inspect mirrored deliveryChecklist assets and BMW-side prerequisites "
        f"for {profile.profile_id}"
    )

@dataclass(frozen=True)
class OperatorAction:
    action_id: str
    label: str
    description: str
    kind: str
    scope: str
    ready: bool
    blocker_message: str = ""
    profile_id: str = ""
    project_root: str = ""
    command_preview: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "label": self.label,
            "description": self.description,
            "kind": self.kind,
            "scope": self.scope,
            "ready": self.ready,
            "blocker_message": self.blocker_message,
            "profile_id": self.profile_id,
            "project_root": self.project_root,
            "command_preview": self.command_preview,
        }

def _status_map(root: Path) -> dict[str, dict[str, str]]:
    return {item["key"]: item for item in prerequisite_status(root)}

def _path_from_status(status_map: dict[str, dict[str, str]], key: str) -> Path:
    raw = status_map.get(key, {}).get("path", "")
    return Path(raw) if raw else Path()

def _status_value(status_map: dict[str, dict[str, str]], key: str) -> str:
    return str(status_map.get(key, {}).get("status", "")).strip().lower()

def _status_detail(status_map: dict[str, dict[str, str]], key: str) -> str:
    return str(status_map.get(key, {}).get("detail", "")).strip()

def _scene_runtime_blocker_message(status_map: dict[str, dict[str, str]]) -> str:
    raco_status = _status_value(status_map, "raco_headless")
    raco_detail = _status_detail(status_map, "raco_headless")
    if raco_status == "incompatible":
        detail = f" {raco_detail}" if raco_detail else ""
        return "Scene check is blocked because the configured `RaCoHeadless.exe` cannot open the representative SG scene." + detail
    return "Scene check needs both the mirrored `check_scenes.py` helper and a locally compatible `RaCoHeadless.exe`."

def _bmw_smoke_script_path(status_map: dict[str, dict[str, str]], profile: RunProfile) -> Path:
    bmw_repo = _path_from_status(status_map, "bmw_models_repo")
    if not bmw_repo:
        return Path()
    return bmw_repo / "ci" / "scripts" / (profile.bmw_smoke_runner or "car_manager.py")

def _bmw_smoke_blocker_message(status_map: dict[str, dict[str, str]], profile: RunProfile) -> str:
    bmw_repo = _path_from_status(status_map, "bmw_models_repo")
    script_path = _bmw_smoke_script_path(status_map, profile)
    if not bmw_repo.exists():
        return "BMW screenshot smoke needs a local `digital-3d-car-models` clone from BMW Git."
    if not script_path.exists():
        return "BMW screenshot smoke needs the `ci/scripts/car_manager.py` helper in the BMW models repo."
    if not profile.bmw_smoke_target.strip():
        return f"No BMW screenshot-smoke target mapping is configured for {profile.profile_id} yet."
    return ""


def _sgfx_preflight_action(profile: RunProfile) -> OperatorAction:
    source_project_root = profile.source_project_root()
    ready = source_project_root.exists() and profile.config_path.exists()
    return OperatorAction(
        action_id=f"sgfx_preflight__{profile.profile_id.lower()}",
        label="Run local QA checks",
        description=(
            f"Run the four deterministic SGFX validation packs for {profile.profile_id} "
            "without launching the broader QA stack or external tools."
        ),
        kind="sgfx_preflight",
        scope="profile",
        ready=ready,
        blocker_message=(
            "" if ready else f"The project root or config for {profile.profile_id} is missing."
        ),
        profile_id=profile.profile_id,
        project_root=str(source_project_root),
        command_preview="internal: run four deterministic SGFX packs",
    )


def list_sgfx_preflight_actions(
    workspace: Path | None = None,
    *,
    profiles: list[RunProfile] | None = None,
) -> list[OperatorAction]:
    root = workspace_root(workspace)
    live_profiles = profiles or list_run_profiles(root)
    return [_sgfx_preflight_action(profile) for profile in live_profiles]

def list_operator_actions(
    workspace: Path | None = None,
    *,
    profiles: list[RunProfile] | None = None,
) -> list[OperatorAction]:
    root = workspace_root(workspace)
    live_profiles = profiles or list_run_profiles(root)
    status_map = _status_map(root)
    source_root = resolve_source_repo_root(root)
    mirror_root = mirror_repo_root(root)
    style_script, checker_script = _repo_checker_paths(mirror_root)
    unused_resources_script = _unused_resources_script_path(mirror_root)
    delivery_checklist_paths = _delivery_checklist_paths(mirror_root)
    scene_checker = mirror_root / "check_scenes.py"
    raco_headless = _path_from_status(status_map, "raco_headless")
    checker_ready = style_script.exists() and checker_script.exists()
    scene_ready = scene_checker.exists() and raco_headless.exists() and _status_value(status_map, "raco_headless") == "available"

    actions = [
        OperatorAction(
            action_id="repo_checker_all",
            label="Run full repo checkers",
            description="Run the SG checker stack over the live SG repo root, matching `checkall.bat` scope without calling the batch wrapper directly.",
            kind="repo_checker",
            scope="workspace",
            ready=checker_ready and source_root.exists(),
            blocker_message=(
                ""
                if checker_ready and source_root.exists()
                else "The SG checker stack (`check_all_styles.py` + `executeChecks.py`) or live source repo root is missing."
            ),
            command_preview=_repo_checker_command_preview(
                style_script,
                checker_script,
                source_root,
            ),
        ),
        OperatorAction(
            action_id="daily_live_matrix",
            label="Run daily SG check",
            description="Run the recommended SG QA stack across the ready live SG slices and write one shared summary.",
            kind="daily_live_matrix",
            scope="workspace",
            ready=any(profile.source_project_root().exists() and profile.config_path.exists() for profile in live_profiles),
            blocker_message=(
                ""
                if any(profile.source_project_root().exists() and profile.config_path.exists() for profile in live_profiles)
                else "No ready live SG profiles are configured on this machine."
            ),
            command_preview="internal: run the recommended QA stack across all ready live profiles",
        ),
        OperatorAction(
            action_id="repo_checker_idcevo",
            label="Run IDCevo repo checkers",
            description="Run the SG checker stack over the mirrored `Cars_IDCevo` tree.",
            kind="repo_checker",
            scope="workspace",
            ready=checker_ready and (source_root / "Cars_IDCevo").exists(),
            blocker_message=(
                ""
                if checker_ready and (source_root / "Cars_IDCevo").exists()
                else "The SG checker stack (`check_all_styles.py` + `executeChecks.py`) or live `Cars_IDCevo` tree is missing."
            ),
            command_preview=_repo_checker_command_preview(
                style_script,
                checker_script,
                source_root / "Cars_IDCevo",
            ),
        ),
        OperatorAction(
            action_id="repo_checker_classic",
            label="Run classic repo checkers",
            description="Run the SG checker stack over the mirrored `Cars` tree.",
            kind="repo_checker",
            scope="workspace",
            ready=checker_ready and (source_root / "Cars").exists(),
            blocker_message=(
                ""
                if checker_ready and (source_root / "Cars").exists()
                else "The SG checker stack (`check_all_styles.py` + `executeChecks.py`) or live `Cars` tree is missing."
            ),
            command_preview=_repo_checker_command_preview(
                style_script,
                checker_script,
                source_root / "Cars",
            ),
        ),
    ]

    for profile in live_profiles:
        source_project_root = profile.source_project_root()
        actions.append(_sgfx_preflight_action(profile))
        actions.append(
            OperatorAction(
                action_id=f"qa_stack__{profile.profile_id.lower()}",
                label=f"Run recommended QA stack for {profile.profile_id}",
                description=(
                    f"Run the default preflight first, then every additional SG-side QA step that is available on this machine for {profile.profile_id}."
                ),
                kind="profile_stack",
                scope="profile",
                ready=source_project_root.exists() and profile.config_path.exists(),
                blocker_message=(
                    ""
                    if source_project_root.exists() and profile.config_path.exists()
                    else f"The project root or config for {profile.profile_id} is missing, so the recommended stack cannot start."
                ),
                profile_id=profile.profile_id,
                project_root=str(source_project_root),
                command_preview=(
                    "internal: standard preflight + repo checker + unused resource scan + scene check + delivery checklist readiness + BMW smoke readiness summary"
                ),
            )
        )
        actions.append(
            OperatorAction(
                action_id=f"repo_checker_profile__{profile.profile_id.lower()}",
                label=f"Run repo check for {profile.profile_id}",
                description=f"Run the SG checker stack only for the {profile.profile_id} project tree.",
                kind="repo_checker",
                scope="profile",
                ready=checker_ready and source_project_root.exists(),
                blocker_message=(
                    ""
                    if checker_ready and source_project_root.exists()
                    else (
                        f"The SG checker stack (`check_all_styles.py` + `executeChecks.py`) "
                        f"or project root for {profile.profile_id} is missing."
                    )
                ),
                profile_id=profile.profile_id,
                project_root=str(source_project_root),
                command_preview=_repo_checker_command_preview(
                    style_script,
                    checker_script,
                    source_project_root,
                ),
            )
        )
        actions.append(
            OperatorAction(
                action_id=f"unused_resources__{profile.profile_id.lower()}",
                label=f"Run unused resource scan for {profile.profile_id}",
                description=(
                    f"Run the SG unused-resource checker for the {profile.profile_id} project so leftover resource files can be reviewed before handoff."
                ),
                kind="unused_resources",
                scope="profile",
                ready=(
                    unused_resources_script.exists()
                    and source_project_root.exists()
                    and _unused_resources_inputs(source_project_root)[0].exists()
                    and any(source_project_root.rglob("*.rca"))
                ),
                blocker_message=(
                    ""
                    if (
                        unused_resources_script.exists()
                        and source_project_root.exists()
                        and _unused_resources_inputs(source_project_root)[0].exists()
                        and any(source_project_root.rglob("*.rca"))
                    )
                    else (
                        "Unused resource scan needs `printNotUsedResources.py`, a local `resources` tree, and at least one `.rca` scene under the project root."
                    )
                ),
                profile_id=profile.profile_id,
                project_root=str(source_project_root),
                command_preview=_unused_resources_command_preview(
                    unused_resources_script,
                    source_project_root,
                ),
            )
        )
        delivery_checklist_ready = source_project_root.exists() and all(
            path.exists()
            for key, path in delivery_checklist_paths.items()
            if key != "root"
        )
        actions.append(
            OperatorAction(
                action_id=f"delivery_checklist__{profile.profile_id.lower()}",
                label=f"Check delivery checklist readiness for {profile.profile_id}",
                description=(
                    f"Inspect the SG delivery-checklist bridge assets plus BMW-side prerequisites for {profile.profile_id} without pretending the external BMW flow runs here."
                ),
                kind="delivery_checklist",
                scope="profile",
                ready=delivery_checklist_ready,
                blocker_message=(
                    ""
                    if delivery_checklist_ready
                    else (
                        "Delivery checklist readiness needs the mirrored `.pdx/checkers/deliveryChecklist` assets "
                        "(`deliveryChecklist.exe`, `deliveryChecklist.py`, `README.md`, and `cameraCrane.lua`)."
                    )
                ),
                profile_id=profile.profile_id,
                project_root=str(source_project_root),
                command_preview=_delivery_checklist_command_preview(profile),
            )
        )
        actions.append(
            OperatorAction(
                action_id=f"scene_check__{profile.profile_id.lower()}",
                label=f"Run scene check for {profile.profile_id}",
                description=f"Run SG scene checking over every `.rca` under the {profile.profile_id} project tree.",
                kind="scene_check",
                scope="profile",
                ready=scene_ready and source_project_root.exists(),
                blocker_message=(
                    ""
                    if scene_ready and source_project_root.exists()
                    else (
                        "The mirrored `check_scenes.py` helper is missing."
                        if not scene_checker.exists()
                        else _scene_runtime_blocker_message(status_map)
                    )
                ),
                profile_id=profile.profile_id,
                project_root=str(source_project_root),
                command_preview=f"{sys.executable} {scene_checker} --raco {raco_headless} --dir {source_project_root}",
            )
        )
        bmw_smoke_blocker = _bmw_smoke_blocker_message(status_map, profile)
        bmw_script = _bmw_smoke_script_path(status_map, profile)
        target = profile.bmw_smoke_target.strip()
        actions.append(
            OperatorAction(
                action_id=f"bmw_screenshot_smoke__{profile.profile_id.lower()}",
                label=f"Run BMW screenshot smoke for {profile.profile_id}",
                description=(
                    f"Run BMW-side export and screenshot smoke for {profile.profile_id} when the BMW models repo and car mapping are available."
                ),
                kind="bmw_screenshot_smoke",
                scope="profile",
                ready=not bmw_smoke_blocker,
                blocker_message=bmw_smoke_blocker,
                profile_id=profile.profile_id,
                project_root=str(source_project_root),
                command_preview=(
                    " && ".join(
                        bmw_interface_smoke_commands(
                            target,
                            python_executable=sys.executable,
                            script=str(bmw_script),
                        )
                    )
                    if target
                    else "BMW screenshot smoke target mapping is not configured yet."
                ),
            )
        )

    return actions

def get_operator_action(
    action_id: str,
    workspace: Path | None = None,
    *,
    profiles: list[RunProfile] | None = None,
) -> OperatorAction:
    normalized = action_id.strip().lower()
    for action in list_operator_actions(workspace, profiles=profiles):
        if action.action_id.lower() == normalized:
            return action
    supported = ", ".join(action.action_id for action in list_operator_actions(workspace, profiles=profiles))
    raise KeyError(f"Unsupported action {action_id!r}. Supported actions: {supported}")
