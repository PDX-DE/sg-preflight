from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sg_preflight.profiles import RunProfile, list_run_profiles
from sg_preflight.tool_readiness import probe_raco_runtime, representative_raco_scene


@dataclass(frozen=True)
class CheckerPrerequisite:
    key: str
    label: str
    path: str
    status: str

    def to_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "label": self.label,
            "path": self.path,
            "status": self.status,
        }


@dataclass(frozen=True)
class CheckerCatalogEntry:
    key: str
    label: str
    path: str
    kind: str
    scope: str
    state: str
    coverage: str
    summary: str
    operator_surface: str
    blockers: tuple[str, ...] = ()
    manual_steps: tuple[str, ...] = ()
    prerequisites: tuple[CheckerPrerequisite, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "path": self.path,
            "kind": self.kind,
            "scope": self.scope,
            "state": self.state,
            "coverage": self.coverage,
            "summary": self.summary,
            "operator_surface": self.operator_surface,
            "blockers": list(self.blockers),
            "manual_steps": list(self.manual_steps),
            "prerequisites": [item.to_dict() for item in self.prerequisites],
        }


def _workspace_root(explicit_root: Path | None = None) -> Path:
    return (explicit_root or Path(__file__).resolve().parents[1]).resolve()


def _env_or_default_path(env_keys: tuple[str, ...], default_paths: tuple[Path, ...]) -> Path:
    for key in env_keys:
        raw = os.environ.get(key, "").strip()
        if raw:
            return Path(raw)
    for path in default_paths:
        if path.exists():
            return path
    return default_paths[0]


def _mirror_root(root: Path) -> Path:
    return root / "repositories" / "trunk"


def _checkers_root(root: Path) -> Path:
    return _mirror_root(root) / ".pdx" / "checkers"


def _raco_headless_path(root: Path) -> Path:
    path = _env_or_default_path(
        ("SG_RACO_HEADLESS", "RACO_HEADLESS_EXE"),
        (
            root / "external" / "ramses" / "bin" / "RelWithDebInfo" / "RaCoHeadless.exe",
            root / "external" / "ramses" / "RaCoHeadless.exe",
            root.parent / "RamsesComposerWindows" / "bin" / "RelWithDebInfo" / "RaCoHeadless.exe",
            Path(r"C:\RamsesComposerWindows\bin\RelWithDebInfo\RaCoHeadless.exe"),
        ),
    )
    if path.exists():
        return path
    command_path = shutil.which("RaCoHeadless.exe")
    return Path(command_path) if command_path else path


def _bmw_models_repo_path(root: Path) -> Path:
    return _env_or_default_path(
        ("SG_CARMODELS_REPO",),
        (
            root / "external" / "digital-3d-car-models",
            root.parent / "digital-3d-car-models",
            Path(r"C:\repos\digital-3d-car-models"),
        ),
    )


def _delivery_checklist_paths(root: Path) -> dict[str, Path]:
    checklist_root = _checkers_root(root) / "deliveryChecklist"
    return {
        "root": checklist_root,
        "tool": checklist_root / "deliveryChecklist.exe",
        "helper": checklist_root / "deliveryChecklist.py",
        "readme": checklist_root / "README.md",
        "camera_crane": checklist_root / "cameraCrane.lua",
    }


def _viewer_candidates(bmw_repo: Path) -> list[Path]:
    if not bmw_repo.exists():
        return []
    matches: list[Path] = []
    seen: set[Path] = set()
    for pattern in ("ramses*viewer*.exe", "Ramses*Viewer*.exe"):
        try:
            for candidate in bmw_repo.rglob(pattern):
                resolved = candidate.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                matches.append(candidate)
                if len(matches) >= 4:
                    return matches
        except OSError:
            return matches
    return matches


def _prereq(key: str, label: str, path: Path) -> CheckerPrerequisite:
    return CheckerPrerequisite(
        key=key,
        label=label,
        path=str(path),
        status="available" if path.exists() else "missing",
    )


def _profile_action_surface(prefix: str, profiles: list[RunProfile]) -> str:
    if profiles:
        preview = ", ".join(f"{prefix}__{profile.profile_id.lower()}" for profile in profiles[:3])
        if len(profiles) > 3:
            preview += ", ..."
        return preview
    return f"{prefix}__<profile>"


def list_checker_catalog(
    workspace: Path | None = None,
    *,
    profiles: list[RunProfile] | None = None,
) -> list[CheckerCatalogEntry]:
    root = _workspace_root(workspace)
    live_profiles = profiles or list_run_profiles(root)
    mirror_root = _mirror_root(root)
    checkers_root = _checkers_root(root)
    delivery_paths = _delivery_checklist_paths(root)
    bmw_repo = _bmw_models_repo_path(root)
    raco_headless = _raco_headless_path(root)
    raco_probe_scene = representative_raco_scene(root)
    raco_headless_probe = probe_raco_runtime(raco_headless, raco_probe_scene, gui=False) if raco_headless.exists() else {
        "status": "missing",
        "detail": "A local `RaCoHeadless.exe` is not configured.",
        "probe_path": str(raco_probe_scene) if raco_probe_scene else "",
    }

    style_script = checkers_root / "code_style_checker" / "check_all_styles.py"
    execute_checks = checkers_root / "executeChecks.py"
    checkall_bat = checkers_root / "checkall.bat"
    checkcars_bat = checkers_root / "checkcars.bat"
    checkcars_idcevo_bat = checkers_root / "checkcars_IDCevo.bat"
    unused_script = checkers_root / "printNotUsedResources.py"
    scene_checker = mirror_root / "check_scenes.py"
    car_manager = bmw_repo / "ci" / "scripts" / "car_manager.py"
    test_main = bmw_repo / "ci" / "scripts" / "test" / "main.py"
    viewer_candidates = _viewer_candidates(bmw_repo)

    ready_profiles = [
        profile
        for profile in live_profiles
        if profile.source_project_root().exists() and profile.config_path.exists()
    ]
    unused_ready_profiles = [
        profile
        for profile in ready_profiles
        if (profile.source_project_root() / "resources").exists() and any(profile.source_project_root().rglob("*.rca"))
    ]
    bmw_targets_ready = any(profile.bmw_smoke_target.strip() for profile in live_profiles)
    delivery_assets_ready = all(
        path.exists() for key, path in delivery_paths.items() if key != "root"
    )
    bmw_helpers_ready = car_manager.exists() or test_main.exists()

    entries = [
        CheckerCatalogEntry(
            key="style_checker",
            label="code_style_checker/check_all_styles.py",
            path=str(style_script),
            kind="python",
            scope="workspace",
            state="ready" if style_script.exists() else "blocked",
            coverage="direct",
            summary=(
                "SG Preflight invokes the BMW style/license checker directly as the first phase of repo-checker actions."
                if style_script.exists()
                else "The mirrored BMW style/license checker is missing."
            ),
            operator_surface="repo_checker_all, repo_checker_idcevo, repo_checker_classic, repo_checker_profile__<profile>, qa_stack__<profile>",
            blockers=()
            if style_script.exists()
            else ("The mirrored `code_style_checker/check_all_styles.py` helper is missing.",),
            prerequisites=(
                _prereq("style_checker", "Style Checker Script", style_script),
            ),
        ),
        CheckerCatalogEntry(
            key="execute_checks",
            label="executeChecks.py",
            path=str(execute_checks),
            kind="python",
            scope="workspace",
            state="ready" if execute_checks.exists() else "blocked",
            coverage="direct",
            summary=(
                "SG Preflight invokes `executeChecks.py` directly for Lua, shader, tabbing, newline, and binary-location checks."
                if execute_checks.exists()
                else "The mirrored `executeChecks.py` helper is missing."
            ),
            operator_surface="repo_checker_all, repo_checker_idcevo, repo_checker_classic, repo_checker_profile__<profile>, qa_stack__<profile>",
            blockers=()
            if execute_checks.exists()
            else ("The mirrored `executeChecks.py` helper is missing.",),
            prerequisites=(
                _prereq("execute_checks", "executeChecks.py", execute_checks),
            ),
        ),
        CheckerCatalogEntry(
            key="checkall_bat",
            label="checkall.bat",
            path=str(checkall_bat),
            kind="batch",
            scope="workspace",
            state="ready" if checkall_bat.exists() and style_script.exists() and execute_checks.exists() and mirror_root.exists() else "blocked",
            coverage="reference",
            summary=(
                "SG Preflight does not call `checkall.bat` directly; it covers the same whole-repo scope through direct Python invocation with `repo_checker_all`."
                if checkall_bat.exists()
                else "The mirrored `checkall.bat` wrapper is missing."
            ),
            operator_surface="repo_checker_all",
            blockers=tuple(
                blocker
                for blocker in (
                    None if checkall_bat.exists() else "The mirrored `checkall.bat` wrapper is missing.",
                    None if style_script.exists() and execute_checks.exists() else "The underlying Python checker stack is incomplete locally.",
                    None if mirror_root.exists() else "The mirrored SG repo root is missing locally.",
                )
                if blocker
            ),
            prerequisites=(
                _prereq("checkall_bat", "checkall.bat", checkall_bat),
                _prereq("style_checker", "Style Checker Script", style_script),
                _prereq("execute_checks", "executeChecks.py", execute_checks),
            ),
        ),
        CheckerCatalogEntry(
            key="checkcars_bat",
            label="checkcars.bat",
            path=str(checkcars_bat),
            kind="batch",
            scope="workspace",
            state="ready" if checkcars_bat.exists() and style_script.exists() and execute_checks.exists() and (mirror_root / "Cars").exists() else "blocked",
            coverage="reference",
            summary=(
                "SG Preflight treats `checkcars.bat` as reference scope and covers the same classic-tree intent through direct Python repo-checker actions."
                if checkcars_bat.exists()
                else "The mirrored `checkcars.bat` wrapper is missing."
            ),
            operator_surface="repo_checker_classic, repo_checker_profile__<classic-profile>, qa_stack__<classic-profile>",
            blockers=tuple(
                blocker
                for blocker in (
                    None if checkcars_bat.exists() else "The mirrored `checkcars.bat` wrapper is missing.",
                    None if style_script.exists() and execute_checks.exists() else "The underlying Python checker stack is incomplete locally.",
                    None if (mirror_root / "Cars").exists() else "The mirrored `Cars` tree is missing locally.",
                )
                if blocker
            ),
            prerequisites=(
                _prereq("checkcars_bat", "checkcars.bat", checkcars_bat),
                _prereq("style_checker", "Style Checker Script", style_script),
                _prereq("execute_checks", "executeChecks.py", execute_checks),
                _prereq("cars_root", "Cars Root", mirror_root / "Cars"),
            ),
        ),
        CheckerCatalogEntry(
            key="checkcars_idcevo_bat",
            label="checkcars_IDCevo.bat",
            path=str(checkcars_idcevo_bat),
            kind="batch",
            scope="workspace",
            state="ready" if checkcars_idcevo_bat.exists() and style_script.exists() and execute_checks.exists() and (mirror_root / "Cars_IDCevo").exists() else "blocked",
            coverage="reference",
            summary=(
                "SG Preflight treats `checkcars_IDCevo.bat` as reference scope and covers the same IDCevo-tree intent through direct Python repo-checker actions."
                if checkcars_idcevo_bat.exists()
                else "The mirrored `checkcars_IDCevo.bat` wrapper is missing."
            ),
            operator_surface="repo_checker_idcevo, repo_checker_profile__<idcevo-profile>, qa_stack__<idcevo-profile>",
            blockers=tuple(
                blocker
                for blocker in (
                    None if checkcars_idcevo_bat.exists() else "The mirrored `checkcars_IDCevo.bat` wrapper is missing.",
                    None if style_script.exists() and execute_checks.exists() else "The underlying Python checker stack is incomplete locally.",
                    None if (mirror_root / "Cars_IDCevo").exists() else "The mirrored `Cars_IDCevo` tree is missing locally.",
                )
                if blocker
            ),
            prerequisites=(
                _prereq("checkcars_idcevo_bat", "checkcars_IDCevo.bat", checkcars_idcevo_bat),
                _prereq("style_checker", "Style Checker Script", style_script),
                _prereq("execute_checks", "executeChecks.py", execute_checks),
                _prereq("cars_idcevo_root", "Cars_IDCevo Root", mirror_root / "Cars_IDCevo"),
            ),
        ),
        CheckerCatalogEntry(
            key="print_not_used_resources",
            label="printNotUsedResources.py",
            path=str(unused_script),
            kind="python",
            scope="profile",
            state="ready" if unused_script.exists() and unused_ready_profiles else "partial" if unused_script.exists() else "blocked",
            coverage="direct",
            summary=(
                "SG Preflight invokes the unused-resource script directly per profile and keeps the result in the same action/evidence flow."
                if unused_script.exists() and unused_ready_profiles
                else "The script exists, but no current live profile is fully ready for a resource-to-scene usage scan."
                if unused_script.exists()
                else "The mirrored `printNotUsedResources.py` helper is missing."
            ),
            operator_surface=_profile_action_surface("unused_resources", ready_profiles)
            + ", "
            + _profile_action_surface("qa_stack", ready_profiles),
            blockers=tuple(
                blocker
                for blocker in (
                    None if unused_script.exists() else "The mirrored `printNotUsedResources.py` helper is missing.",
                    None if unused_ready_profiles else "No current live profile has both a `resources` tree and at least one `.rca` scene ready for this scan.",
                )
                if blocker
            ),
            prerequisites=(
                _prereq("unused_resources", "printNotUsedResources.py", unused_script),
            ),
        ),
        CheckerCatalogEntry(
            key="delivery_checklist",
            label="deliveryChecklist/*",
            path=str(delivery_paths["root"]),
            kind="mixed",
            scope="profile",
            state="ready" if delivery_assets_ready and bmw_repo.exists() and bmw_helpers_ready else "partial" if delivery_assets_ready else "blocked",
            coverage="wrapped",
            summary=(
                "SG Preflight surfaces the delivery-checklist stage as a real pre-delivery bridge and records its readiness in the shared action/evidence flow."
                if delivery_assets_ready and bmw_repo.exists() and bmw_helpers_ready
                else "SG Preflight now exposes the mirrored delivery-checklist assets and the missing BMW-side prerequisites, but the external checklist flow is still only partially available here."
                if delivery_assets_ready
                else "The mirrored `.pdx/checkers/deliveryChecklist` assets are incomplete locally."
            ),
            operator_surface=_profile_action_surface("delivery_checklist", ready_profiles)
            + ", "
            + _profile_action_surface("qa_stack", ready_profiles)
            + ", pre-delivery workflow stage",
            blockers=tuple(
                blocker
                for blocker in (
                    None if delivery_assets_ready else "The mirrored `.pdx/checkers/deliveryChecklist` assets are incomplete locally.",
                    None if bmw_repo.exists() else "Blocked on BMW Git access or a local `digital-3d-car-models` clone.",
                    None if bmw_helpers_ready else "The BMW-side `ci/scripts/car_manager.py` or `ci/scripts/test/main.py` helpers are not available locally.",
                )
                if blocker
            ),
            manual_steps=(
                "Excel/report packaging and delivery-note review remain human-owned even when the bridge is locally ready.",
                "Perspective screenshots still depend on the BMW-side script chain plus viewer/runtime setup.",
            ),
            prerequisites=(
                _prereq("delivery_checklist_tool", "deliveryChecklist.exe", delivery_paths["tool"]),
                _prereq("delivery_checklist_helper", "deliveryChecklist.py", delivery_paths["helper"]),
                _prereq("delivery_checklist_readme", "deliveryChecklist README", delivery_paths["readme"]),
                _prereq("delivery_checklist_camera_crane", "cameraCrane.lua", delivery_paths["camera_crane"]),
                _prereq("bmw_models_repo", "BMW Models Repo", bmw_repo),
                _prereq("bmw_car_manager", "BMW car_manager.py", car_manager),
                _prereq("bmw_test_main", "BMW test main.py", test_main),
            ),
        ),
        CheckerCatalogEntry(
            key="check_scenes",
            label="check_scenes.py",
            path=str(scene_checker),
            kind="python",
            scope="profile",
            state=(
                "ready"
                if scene_checker.exists() and raco_headless_probe["status"] == "available" and ready_profiles
                else "partial"
                if scene_checker.exists()
                else "blocked"
            ),
            coverage="direct",
            summary=(
                "SG Preflight invokes `check_scenes.py` directly when a locally compatible `RaCoHeadless.exe` can open representative SG scenes."
                if scene_checker.exists() and raco_headless_probe["status"] == "available" and ready_profiles
                else (
                    "The script is present, but the configured `RaCoHeadless.exe` cannot open the representative SG scene on this machine yet."
                    if scene_checker.exists() and raco_headless_probe["status"] == "incompatible"
                    else "The script is present, but direct scene execution is still gated by local RaCo runtime setup."
                )
                if scene_checker.exists()
                else "The mirrored `check_scenes.py` helper is missing."
            ),
            operator_surface=_profile_action_surface("scene_check", ready_profiles)
            + ", "
            + _profile_action_surface("qa_stack", ready_profiles),
            blockers=tuple(
                blocker
                for blocker in (
                    None if scene_checker.exists() else "The mirrored `check_scenes.py` helper is missing.",
                    None
                    if raco_headless_probe["status"] == "available"
                    else (
                        "A local `RaCoHeadless.exe` is not configured."
                        if raco_headless_probe["status"] == "missing"
                        else raco_headless_probe["detail"]
                    ),
                    None if ready_profiles else "No current live profile is ready for scene-check execution.",
                )
                if blocker
            ),
            prerequisites=(
                _prereq("scene_checker", "check_scenes.py", scene_checker),
                CheckerPrerequisite(
                    key="raco_headless",
                    label="RaCoHeadless.exe",
                    path=str(raco_headless),
                    status=raco_headless_probe["status"],
                ),
            ),
        ),
        CheckerCatalogEntry(
            key="bmw_smoke",
            label="BMW smoke",
            path=str(bmw_repo),
            kind="external",
            scope="profile",
            state="ready" if bmw_repo.exists() and bmw_helpers_ready and bmw_targets_ready else "partial" if bmw_repo.exists() and bmw_helpers_ready else "blocked",
            coverage="wrapped",
            summary=(
                "SG Preflight exposes the BMW smoke stage through the same action/result flow when repo access, helper scripts, and target mapping are present."
                if bmw_repo.exists() and bmw_helpers_ready and bmw_targets_ready
                else "SG Preflight can show the BMW smoke stage and its blockers, but this machine is still not fully ready to execute it end-to-end."
            ),
            operator_surface=_profile_action_surface("bmw_screenshot_smoke", ready_profiles)
            + ", pre-delivery workflow stage",
            blockers=tuple(
                blocker
                for blocker in (
                    None if bmw_repo.exists() else "Blocked on BMW Git access or a local `digital-3d-car-models` clone.",
                    None if bmw_helpers_ready else "The BMW-side screenshot helpers are not available locally.",
                    None if bmw_targets_ready else "BMW smoke target mapping for the current live profiles is not configured yet.",
                )
                if blocker
            ),
            manual_steps=(
                "Screenshot review and signoff remain human decisions even when the scripts run cleanly.",
            ),
            prerequisites=(
                _prereq("bmw_models_repo", "BMW Models Repo", bmw_repo),
                _prereq("bmw_car_manager", "BMW car_manager.py", car_manager),
                _prereq("bmw_test_main", "BMW test main.py", test_main),
                CheckerPrerequisite(
                    key="bmw_target_mapping",
                    label="BMW Target Mapping",
                    path="profile registry",
                    status="available" if bmw_targets_ready else "missing",
                ),
                CheckerPrerequisite(
                    key="ramses_viewer",
                    label="BMW Viewer Candidate",
                    path=str(viewer_candidates[0]) if viewer_candidates else "<none>",
                    status="available" if viewer_candidates else "missing",
                ),
            ),
        ),
    ]

    return entries
