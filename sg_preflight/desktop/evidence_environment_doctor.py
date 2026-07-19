"""Assembles the desktop shell's environment/setup-doctor readiness items from backend prerequisite checks."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

from sg_preflight.services import prerequisite_status, workspace_root


@dataclass(frozen=True)
class DesktopEnvironmentItem:
    key: str
    category: str
    label: str
    state: str
    summary: str
    path: str
    next_action: str


def desktop_environment_doctor(workspace: Path | None = None) -> list[DesktopEnvironmentItem]:
    root = workspace_root(workspace)
    readiness = {item["key"]: item for item in prerequisite_status(root)}

    def _ready_from_prereq(key: str) -> bool:
        return str(readiness.get(key, {}).get("status", "")).strip().lower() == "available"

    def _status_from_prereq(key: str) -> str:
        return str(readiness.get(key, {}).get("status", "")).strip().lower()

    def _detail_from_prereq(key: str) -> str:
        return str(readiness.get(key, {}).get("detail", "")).strip()

    def _probe_path_from_prereq(key: str) -> str:
        return str(readiness.get(key, {}).get("probe_path", "")).strip()

    def _item(
        *,
        key: str,
        category: str,
        label: str,
        state: str,
        summary: str,
        path: str,
        next_action: str,
    ) -> DesktopEnvironmentItem:
        return DesktopEnvironmentItem(
            key=key,
            category=category,
            label=label,
            state=state,
            summary=summary,
            path=path,
            next_action=next_action,
        )

    sg_module_spec = importlib.util.find_spec("sg_preflight")
    sg_module_path = ""
    if sg_module_spec is not None:
        if sg_module_spec.origin:
            sg_module_path = str(Path(sg_module_spec.origin))
        elif sg_module_spec.submodule_search_locations:
            sg_module_path = str(next(iter(sg_module_spec.submodule_search_locations), ""))

    delivery_keys = (
        "delivery_checklist_tool",
        "delivery_checklist_helper",
        "delivery_checklist_readme",
        "delivery_checklist_camera_crane",
    )
    delivery_ready = sum(1 for key in delivery_keys if _ready_from_prereq(key))
    if delivery_ready == len(delivery_keys):
        delivery_state = "available"
        delivery_summary = "The mirrored delivery documentation assets are present locally. This remains SG-side readiness, not BMW execution."
    elif delivery_ready > 0:
        delivery_state = "partial"
        delivery_summary = "Some delivery documentation assets exist locally, but the mirrored set is incomplete."
    else:
        delivery_state = "blocked"
        delivery_summary = "The mirrored delivery documentation assets are not available locally yet."

    bmw_script_keys = (
        "bmw_screenshot_scripts",
        "bmw_car_manager_script",
        "bmw_test_main_script",
    )
    bmw_script_ready = sum(1 for key in bmw_script_keys if _ready_from_prereq(key))
    if bmw_script_ready == len(bmw_script_keys):
        bmw_scripts_state = "available"
        bmw_scripts_summary = "The BMW smoke helper script surface is present locally."
    elif bmw_script_ready > 0:
        bmw_scripts_state = "partial"
        bmw_scripts_summary = "Some BMW smoke helper files were found locally, but the full helper surface is incomplete."
    else:
        bmw_scripts_state = "blocked"
        bmw_scripts_summary = "BMW smoke helper scripts are still blocked on repo access and local checkout."

    output_root = root / "out" / "operator-ui"
    output_state = "not_run"
    output_summary = "Operator output write access is not probed during this read-only desktop overview."
    output_path = str(output_root)

    python_path = str(Path(sys.executable).resolve())
    python_ready = Path(python_path).exists()
    raco_headless_status = _status_from_prereq("raco_headless")
    raco_headless_detail = _detail_from_prereq("raco_headless")
    raco_headless_probe = _probe_path_from_prereq("raco_headless")
    raco_gui_status = _status_from_prereq("raco_gui")
    raco_gui_detail = _detail_from_prereq("raco_gui")
    raco_gui_probe = _probe_path_from_prereq("raco_gui")

    items = [
        _item(
            key="python_backend",
            category="Python backend",
            label="Python backend",
            state="available" if python_ready else "missing",
            summary=(
                "The shell has a concrete Python executable available for backend commands."
                if python_ready
                else "The shell does not have a working Python executable path for backend commands."
            ),
            path=python_path,
            next_action="Use the bundled environment or launch the shell with --python pointing at a working interpreter.",
        ),
        _item(
            key="sg_preflight_import",
            category="Python backend",
            label="sg_preflight import",
            state="available" if sg_module_spec is not None else "blocked",
            summary=(
                "The shared SG Preflight backend module can be imported by the active interpreter."
                if sg_module_spec is not None
                else "The active interpreter cannot import the shared SG Preflight backend module."
            ),
            path=sg_module_path or "sg_preflight",
            next_action="Install the workspace package into the active interpreter or switch the shell to the bundled environment.",
        ),
        _item(
            key="mirror_root",
            category="SG mirror",
            label="repositories/trunk mirror",
            state="available" if _ready_from_prereq("mirror_root") else "missing",
            summary=(
                "The mirrored Seriengrafik working tree is available locally."
                if _ready_from_prereq("mirror_root")
                else "The mirrored Seriengrafik working tree is missing locally."
            ),
            path=str(readiness.get("mirror_root", {}).get("path", "")),
            next_action="Sync the working mirror into repositories\\trunk before relying on SG-side checker coverage.",
        ),
        _item(
            key="checker_root",
            category="SG mirror",
            label=".pdx/checkers",
            state="available" if _ready_from_prereq("checker_root") else "missing",
            summary=(
                "The mirrored SG checker root is available."
                if _ready_from_prereq("checker_root")
                else "The mirrored SG checker root is missing."
            ),
            path=str(readiness.get("checker_root", {}).get("path", "")),
            next_action="Mirror the .pdx/checkers folder from Seriengrafik into the local workspace.",
        ),
        _item(
            key="execute_checks",
            category="SG mirror",
            label="executeChecks.py",
            state="available" if _ready_from_prereq("execute_checks") else "missing",
            summary=(
                "The main SG checker dispatcher is available locally."
                if _ready_from_prereq("execute_checks")
                else "The main SG checker dispatcher is missing locally."
            ),
            path=str(readiness.get("execute_checks", {}).get("path", "")),
            next_action="Mirror executeChecks.py into .pdx/checkers so repo and stack actions can stay truthful.",
        ),
        _item(
            key="unused_resource_checker",
            category="SG mirror",
            label="printNotUsedResources.py",
            state="available" if _ready_from_prereq("unused_resource_checker") else "missing",
            summary=(
                "The SG unused-resource checker is available locally."
                if _ready_from_prereq("unused_resource_checker")
                else "The SG unused-resource checker is missing locally."
            ),
            path=str(readiness.get("unused_resource_checker", {}).get("path", "")),
            next_action="Mirror printNotUsedResources.py into .pdx/checkers so unused-resource scans stay wired.",
        ),
        _item(
            key="delivery_checklist_assets",
            category="SG mirror",
            label="deliveryChecklist assets",
            state=delivery_state,
            summary=delivery_summary,
            path=str(readiness.get("delivery_checklist_tool", {}).get("path", "")),
            next_action="Keep this surface as a readiness bridge until the BMW-owned delivery execution path is actually available.",
        ),
        _item(
            key="raco_headless",
            category="Local tools",
            label="RaCoHeadless",
            state=(
                "available"
                if raco_headless_status == "available"
                else "partial"
                if raco_headless_status == "incompatible"
                else "missing"
            ),
            summary=(
                "RaCoHeadless is available for local scene-side readiness checks."
                if raco_headless_status == "available"
                else (
                    "RaCoHeadless exists locally, but the configured build cannot open the representative SG scene here."
                    + (f" {raco_headless_detail}" if raco_headless_detail else "")
                )
                if raco_headless_status == "incompatible"
                else "RaCoHeadless is not configured on this machine yet."
            ),
            path=str(readiness.get("raco_headless", {}).get("path", "")),
            next_action=(
                "Point SG_RACO_HEADLESS at a Ramses Composer build that can open the current SG scene feature level."
                + (f" Probe scene: {raco_headless_probe}" if raco_headless_probe else "")
            )
            if raco_headless_status == "incompatible"
            else "Set SG_RACO_HEADLESS or install the standard Ramses Composer build on this machine.",
        ),
        _item(
            key="raco_gui",
            category="Local tools",
            label="Ramses Composer / RaCo GUI",
            state=(
                "available"
                if raco_gui_status == "available" and raco_headless_status != "incompatible"
                else "partial"
                if raco_gui_status == "available"
                else "missing"
            ),
            summary=(
                "A Ramses Composer GUI executable is available for first-pass open-in-RaCo adapters."
                if raco_gui_status == "available" and raco_headless_status != "incompatible"
                else (
                    "A Ramses Composer GUI executable is available for manual open-in-RaCo adapters, but representative scene compatibility is still only partial because RaCoHeadless is not green yet."
                    + (f" {raco_headless_detail}" if raco_headless_detail else "")
                )
                if raco_gui_status == "available"
                else "No Ramses Composer GUI executable is configured locally yet."
            ),
            path=str(readiness.get("raco_gui", {}).get("path", "")),
            next_action=(
                "Point SG_RACO_HEADLESS at a Ramses Composer build that can open the current SG scene feature level, then keep the GUI adapter for manual review."
                + (f" Probe scene: {raco_headless_probe or raco_gui_probe}" if (raco_headless_probe or raco_gui_probe) else "")
            )
            if raco_gui_status == "available" and raco_headless_status == "incompatible"
            else "Set SG_RACO_GUI or install the standard Ramses Composer GUI build before exposing open-in-RaCo adapters.",
        ),
        _item(
            key="blender_executable",
            category="Local tools",
            label="Blender executable",
            state="available" if _ready_from_prereq("blender_executable") else "missing",
            summary=(
                "A Blender executable path is available for local opening/adapter flows."
                if _ready_from_prereq("blender_executable")
                else "No Blender executable path is configured locally yet."
            ),
            path=str(readiness.get("blender_executable", {}).get("path", "")),
            next_action="Set SG_BLENDER_EXE or install the standard Blender build before adding Blender-open adapters.",
        ),
        _item(
            key="bmw_models_repo",
            category="BMW / External",
            label="BMW digital-3d-car repo",
            state="available" if _ready_from_prereq("bmw_models_repo") else "blocked",
            summary=(
                "The BMW models repository is available locally."
                if _ready_from_prereq("bmw_models_repo")
                else "The BMW models repository is still blocked on access or local checkout."
            ),
            path=str(readiness.get("bmw_models_repo", {}).get("path", "")),
            next_action="Set SG_CARMODELS_REPO once access exists and the BMW repository is cloned locally.",
        ),
        _item(
            key="bmw_helper_scripts",
            category="BMW / External",
            label="BMW helper scripts",
            state=bmw_scripts_state,
            summary=bmw_scripts_summary,
            path=str(readiness.get("bmw_test_main_script", {}).get("path", "")),
            next_action="Treat BMW smoke as blocked until the repo, helper scripts, and target mapping are all present locally.",
        ),
        _item(
            key="jira_qa_hero",
            category="BMW / External",
            label="Jira / QA Hero",
            state="blocked",
            summary="Direct Jira or QA Hero integration is not connected here yet. The current product surface is copy export, not API automation.",
            path="copy exports only",
            next_action="Keep using the SG-side copy exports until the real ticket integration path is agreed and available.",
        ),
        _item(
            key="output_write_access",
            category="Operator output",
            label="out/operator-ui write access",
            state=output_state,
            summary=output_summary,
            path=output_path,
            next_action="Ensure the workspace output folder stays writable so evidence, screenshots, and action records can be persisted.",
        ),
    ]
    return items


def _state_counts(items: list[DesktopEnvironmentItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        state = item.state.strip().lower() or "unknown"
        counts[state] = counts.get(state, 0) + 1
    return counts
