"""Setup Doctor — detects and version-validates local tool and environment
prerequisites, and builds the readiness report and setup-wizard steps."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

from sg_preflight.bmw_delivery import discover_bmw_models_repo
from sg_preflight.dependency_onboarding import (
    BMW_CI_IMPORT_PROBE,
    BMW_CI_VENV_DIRNAME,
    BMW_PIPELINE_PYTHON_ENV,
    DIGITAL_3D_CAR_REPO_ENV,
    DIGITAL_3D_CAR_REPO_IDC23_ENV,
    load_dependency_onboarding_state,
)
from sg_preflight.profiles import mirror_repo_root, resolve_source_repo_root
from sg_preflight.subprocess_utils import hidden_subprocess_kwargs
from sg_preflight.tool_version_pins import (
    RAMSES_PIPELINE_PIN,
    RAMSES_PIPELINE_PIN_SOURCE,
    compare_python_requirement,
    compare_version,
    load_raco_pins,
    python_requirement,
    recommended_versions_text,
)


DOCTOR_SCHEMA_VERSION = 1

# PDX 3D-Car "How to screenshottest" page: BMW screenshot tests render to the operator's monitor
# resolution; below this the output is cropped and comparisons fail (multi-monitor widths add up).
SCREENSHOT_MIN_DISPLAY_WIDTH = 3340
SCREENSHOT_MIN_DISPLAY_HEIGHT = 1440


_WIZARD_STEP_GROUPS: tuple[dict[str, object], ...] = (
    {
        "key": "runtime",
        "label": "Runtime foundation",
        "summary": "Python, Qt WebEngine, and Ramses runtime files that let the local tool launch.",
        "item_keys": ("python_runtime", "qt_webengine_core", "ramses_sdk_runtime"),
    },
    {
        "key": "pipeline_tools",
        "label": "Pipeline tools",
        "summary": "RaCo, RaCoHeadless, and Blender paths used by the SGFX verification pipeline.",
        "item_keys": ("raco_headless", "raco_gui", "blender"),
    },
    {
        "key": "bmw_worktrees",
        "label": "BMW worktrees",
        "summary": "BMW Git worktrees, environment variables, and BMW-CI Python dependencies for pipeline checks.",
        "item_keys": ("bmw_git_worktree", "idc23_worktree", "bmw_ci_python_deps"),
    },
    {
        "key": "connected_extras",
        "label": "Connected extras",
        "summary": "Optional connected integrations that should not block local SGFX launch.",
        "item_keys": ("jira_pat",),
    },
)


def _count_items(items: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "found": sum(1 for item in items if item["status"] == "found"),
        "required_missing": sum(1 for item in items if item["required"] and item["status"] != "found"),
        "optional_missing": sum(1 for item in items if not item["required"] and item["status"] != "found"),
    }


def _wizard_step_status(counts: dict[str, int]) -> str:
    if counts["required_missing"]:
        return "missing"
    if counts["optional_missing"]:
        return "optional_missing"
    return "found"


def _wizard_step_detail(status: str, counts: dict[str, int]) -> str:
    if status == "missing":
        missing = counts["required_missing"]
        suffix = "s" if missing != 1 else ""
        return f"{missing} required blocker{suffix} in this setup step."
    if status == "optional_missing":
        return "Only optional connected extras are missing here; core launch is not blocked."
    return "All rows in this setup step are found."


def _build_wizard_steps(item_payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {str(item["key"]): item for item in item_payloads}
    steps: list[dict[str, Any]] = []
    for group in _WIZARD_STEP_GROUPS:
        item_keys = tuple(str(key) for key in group["item_keys"])
        items = [by_key[key] for key in item_keys if key in by_key]
        counts = _count_items(items)
        status = _wizard_step_status(counts)
        steps.append(
            {
                "key": str(group["key"]),
                "label": str(group["label"]),
                "summary": str(group["summary"]),
                "status": status,
                "detail": _wizard_step_detail(status, counts),
                "item_keys": list(item_keys),
                "found_count": counts["found"],
                "required_missing_count": counts["required_missing"],
                "optional_missing_count": counts["optional_missing"],
            }
        )
    return steps


def _build_next_action(
    *,
    ready: bool,
    blockers: list[dict[str, Any]],
    optional_missing: list[dict[str, Any]],
) -> dict[str, Any]:
    if blockers:
        item = blockers[0]
        return {
            "status": "blocked",
            "label": f"Fix {item['label']}",
            "detail": item.get("fix") or item.get("detail") or "Fix the first required setup blocker.",
            "item_key": item["key"],
            "href": f"/ui/setup#setup-item-{item['key']}",
            "blocking": True,
        }
    if ready and optional_missing:
        item = optional_missing[0]
        return {
            "status": "optional",
            "label": f"Optional: configure {item['label']}",
            "detail": item.get("fix") or item.get("detail") or "Optional setup can be completed later.",
            "item_key": item["key"],
            "href": f"/ui/setup#setup-item-{item['key']}",
            "blocking": False,
        }
    return {
        "status": "ready",
        "label": "Start normal SGFX checks",
        "detail": "All required setup rows are available on this machine.",
        "item_key": "",
        "href": "/ui",
        "blocking": False,
    }


def _build_shell_signal(
    *,
    ready: bool,
    headline: str,
    generated_at_utc: str,
    blockers: list[dict[str, Any]],
    next_action: dict[str, Any],
) -> dict[str, Any]:
    return {
        "kind": "setup_doctor",
        "schema_version": DOCTOR_SCHEMA_VERSION,
        "ready": ready,
        "headline": headline,
        "blocking_labels": [str(item["label"]) for item in blockers],
        "next_action_label": str(next_action["label"]),
        "next_action_href": str(next_action["href"]),
        "generated_at_utc": generated_at_utc,
    }


@dataclass(frozen=True)
class SetupDoctorItem:
    key: str
    label: str
    category: str
    required: bool
    status: str
    path: str = ""
    version: str = ""
    recommended_version: str = ""
    version_status: str = ""
    version_check_detail: str = ""
    detail: str = ""
    fix: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "category": self.category,
            "required": self.required,
            "status": self.status,
            "path": self.path,
            "version": self.version,
            "recommended_version": self.recommended_version,
            "version_status": self.version_status,
            "version_check_detail": self.version_check_detail,
            "detail": self.detail,
            "fix": self.fix,
            "blocking": self.required and self.status != "found",
        }


@dataclass(frozen=True)
class SetupDoctorReport:
    workspace_root: str
    generated_at_utc: str
    ready: bool
    required_missing_count: int
    optional_missing_count: int
    found_count: int
    items: tuple[SetupDoctorItem, ...]

    def to_dict(self) -> dict[str, Any]:
        item_payloads = [item.to_dict() for item in self.items]
        blockers = [item for item in item_payloads if item["required"] and item["status"] != "found"]
        optional_missing = [item for item in item_payloads if not item["required"] and item["status"] != "found"]
        headline = "You're ready." if self.ready else "Setup still has blockers."
        next_action = _build_next_action(
            ready=self.ready,
            blockers=blockers,
            optional_missing=optional_missing,
        )
        version_validation = _version_validation_summary(item_payloads)
        return {
            "schema_version": DOCTOR_SCHEMA_VERSION,
            "status": "ready" if self.ready else "blocked",
            "mode": "detect_and_validate",
            "workspace_root": self.workspace_root,
            "generated_at_utc": self.generated_at_utc,
            "ready": self.ready,
            "required_missing_count": self.required_missing_count,
            "optional_missing_count": self.optional_missing_count,
            "found_count": self.found_count,
            "version_validation": version_validation,
            "headline": headline,
            "blocking_items": blockers,
            "optional_missing_items": optional_missing,
            "next_action": next_action,
            "wizard_steps": _build_wizard_steps(item_payloads),
            "shell_signal": _build_shell_signal(
                ready=self.ready,
                headline=headline,
                generated_at_utc=self.generated_at_utc,
                blockers=blockers,
                next_action=next_action,
            ),
            "items": item_payloads,
        }


def _version_validation_summary(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"ok": 0, "drift": 0, "unknown": 0, "not_pinned": 0}
    for item in items:
        status = str(item.get("version_status", "")).strip()
        if status in counts:
            counts[status] += 1
    return counts


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env_value(*keys: str) -> str:
    for key in keys:
        raw = os.environ.get(key, "").strip()
        if raw:
            return raw
    return ""


def _env_path(*keys: str) -> Path | None:
    raw = _env_value(*keys)
    return Path(raw) if raw else None


def _first_existing(candidates: list[Path]) -> Path:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _which_or_candidate(executable: str, candidates: list[Path]) -> Path:
    command_path = shutil.which(executable)
    if command_path:
        return Path(command_path)
    return _first_existing(candidates)


def _version_from_command(command: list[str], timeout_seconds: float = 4.0) -> str:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""

    text = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part and part.strip())
    if not text:
        return ""
    return text.splitlines()[0].strip()


def _found_item(
    *,
    key: str,
    label: str,
    category: str,
    required: bool,
    path: Path,
    version: str = "",
    recommended_version: str = "",
    version_status: str = "",
    version_check_detail: str = "",
    detail: str = "",
    fix: str = "",
) -> SetupDoctorItem:
    return SetupDoctorItem(
        key=key,
        label=label,
        category=category,
        required=required,
        status="found",
        path=str(path),
        version=version,
        recommended_version=recommended_version,
        version_status=version_status,
        version_check_detail=version_check_detail,
        detail=detail,
        fix=fix,
    )


def _missing_item(
    *,
    key: str,
    label: str,
    category: str,
    required: bool,
    path: Path | str = "",
    detail: str,
    fix: str,
    version: str = "",
    recommended_version: str = "",
    version_status: str = "",
    version_check_detail: str = "",
) -> SetupDoctorItem:
    return SetupDoctorItem(
        key=key,
        label=label,
        category=category,
        required=required,
        status="missing",
        path=str(path),
        version=version,
        recommended_version=recommended_version,
        version_status=version_status,
        version_check_detail=version_check_detail,
        detail=detail,
        fix=fix,
    )


def _optional_missing_item(
    *,
    key: str,
    label: str,
    category: str,
    path: Path | str = "",
    detail: str,
    fix: str,
    version: str = "",
    recommended_version: str = "",
    version_status: str = "",
    version_check_detail: str = "",
) -> SetupDoctorItem:
    return SetupDoctorItem(
        key=key,
        label=label,
        category=category,
        required=False,
        status="optional_missing",
        path=str(path),
        version=version,
        recommended_version=recommended_version,
        version_status=version_status,
        version_check_detail=version_check_detail,
        detail=detail,
        fix=fix,
    )


def _raco_headless_candidates(root: Path, source_root: Path, mirror_root: Path) -> list[Path]:
    env_path = _env_path("SG_RACO_HEADLESS", "RACO_HEADLESS_EXE")
    candidates = [
        root / "external" / "ramses" / "bin" / "RelWithDebInfo" / "RaCoHeadless.exe",
        root / "external" / "ramses" / "RaCoHeadless.exe",
        root / "Ramses_Composer_Current" / "Ramses_Composer_Current" / "bin" / "RelWithDebInfo" / "RaCoHeadless.exe",
        source_root / "ci" / "tools" / "win32" / "raco" / "RaCoHeadless.exe",
        source_root / ".pdx" / "raco" / "RaCoHeadless.exe",
        mirror_root / "ci" / "tools" / "win32" / "raco" / "RaCoHeadless.exe",
        mirror_root / ".pdx" / "raco" / "RaCoHeadless.exe",
        Path(r"C:\RamsesComposerWindows\bin\RelWithDebInfo\RaCoHeadless.exe"),
    ]
    if env_path is not None:
        candidates.insert(0, env_path)
    return candidates


def _raco_gui_candidates(root: Path, source_root: Path, mirror_root: Path) -> list[Path]:
    env_path = _env_path("SG_RACO_GUI", "SG_RACO_EDITOR", "RACO_GUI_EXE")
    candidates = [
        root / "external" / "ramses" / "bin" / "RelWithDebInfo" / "RamsesComposer.exe",
        root / "external" / "ramses" / "RamsesComposer.exe",
        root / "Ramses_Composer_Current" / "Ramses_Composer_Current" / "bin" / "RelWithDebInfo" / "RamsesComposer.exe",
        source_root / "ci" / "tools" / "win32" / "raco" / "RamsesComposer.exe",
        mirror_root / "ci" / "tools" / "win32" / "raco" / "RamsesComposer.exe",
        Path(r"C:\RamsesComposerWindows\bin\RelWithDebInfo\RamsesComposer.exe"),
    ]
    if env_path is not None:
        candidates.insert(0, env_path)
    return candidates


def _blender_candidates(root: Path) -> list[Path]:
    env_path = _env_path("SG_BLENDER_EXE", "BLENDER_EXE")
    external_candidates = [
        child / "blender.exe"
        for child in sorted((root / "external").glob("blender*"))
        if child.is_dir()
    ]
    candidates = [
        root / "external" / "blender" / "blender.exe",
        root.parent / "Blender" / "blender.exe",
        Path(r"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe"),
        Path(r"C:\Program Files\Blender Foundation\Blender 4.4\blender.exe"),
        Path(r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe"),
        Path(r"C:\Program Files\Blender Foundation\Blender 4.1\blender.exe"),
        Path(r"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe"),
        Path(r"C:\Program Files\Blender Foundation\Blender 3.6\blender.exe"),
        *external_candidates,
    ]
    if env_path is not None:
        candidates.insert(0, env_path)
    return candidates


def _check_raco_headless(root: Path, source_root: Path, mirror_root: Path) -> SetupDoctorItem:
    raco_pins = load_raco_pins(discover_bmw_models_repo(root))
    recommended = recommended_versions_text(raco_pins)
    candidate = _which_or_candidate("RaCoHeadless.exe", _raco_headless_candidates(root, source_root, mirror_root))
    if not candidate.exists():
        return _missing_item(
            key="raco_headless",
            label="RaCoHeadless",
            category="Pipeline",
            required=True,
            path=candidate,
            detail="The scene-check and export pipeline cannot run without RaCoHeadless.",
            fix="Point SG_RACO_HEADLESS at RaCoHeadless.exe or install the designated Ramses Composer package from the team share.",
            recommended_version=recommended,
            version_status="unknown",
            version_check_detail=(
                f"RaCo guidance source: {raco_pins['source']}. Installed version was not detected because "
                "RaCoHeadless was not found."
            ),
        )
    version = _version_from_command([str(candidate), "--version"])
    version_status, version_detail = compare_version(version, raco_pins)
    return _found_item(
        key="raco_headless",
        label="RaCoHeadless",
        category="Pipeline",
        required=True,
        path=candidate,
        version=version,
        recommended_version=recommended,
        version_status=version_status,
        version_check_detail=f"{version_detail} Source: {raco_pins['source']}.",
        detail="Headless RaCo is present for scene checks and export verification.",
        fix="Keep this pinned to the project-designated RaCo version.",
    )


def _check_raco_gui(root: Path, source_root: Path, mirror_root: Path) -> SetupDoctorItem:
    candidate = _which_or_candidate("RamsesComposer.exe", _raco_gui_candidates(root, source_root, mirror_root))
    if not candidate.exists():
        return _missing_item(
            key="raco_gui",
            label="Ramses Composer",
            category="Pipeline",
            required=True,
            path=candidate,
            detail="The manual RaCo review surface is not configured.",
            fix="Point SG_RACO_GUI at RamsesComposer.exe or install the designated Ramses Composer package from the team share.",
        )
    return _found_item(
        key="raco_gui",
        label="Ramses Composer",
        category="Pipeline",
        required=True,
        path=candidate,
        detail="RaCo GUI is present. The doctor only checks the path; it does not open the GUI during startup.",
    )


def _check_blender(root: Path) -> SetupDoctorItem:
    candidate = _which_or_candidate("blender.exe", _blender_candidates(root))
    if not candidate.exists():
        return _missing_item(
            key="blender",
            label="Blender",
            category="Pipeline",
            required=True,
            path=candidate,
            detail="Blender is needed for the manual visual-review and pipeline helper path.",
            fix="Install the pinned Blender build or point SG_BLENDER_EXE at blender.exe.",
            version_status="not_pinned",
            version_check_detail="No pinned Blender version documented; detected only.",
        )
    version = _version_from_command([str(candidate), "--version"])
    return _found_item(
        key="blender",
        label="Blender",
        category="Pipeline",
        required=True,
        path=candidate,
        version=version,
        version_status="not_pinned",
        version_check_detail="No pinned Blender version documented; detected only.",
        detail="Blender is present for manual review and bpy-backed pipeline steps.",
    )


def _check_bmw_git(root: Path) -> SetupDoctorItem:
    env_path = _env_path("Digital-3D-Car-Repo", "SG_BMW_MODELS_REPO", "SG_CARMODELS_REPO")
    repo_path = env_path if env_path is not None else discover_bmw_models_repo(root)
    marker = repo_path / "ci" / "scripts" / "common" / "models_build_config.yaml"
    if not repo_path.exists():
        return _missing_item(
            key="bmw_git_worktree",
            label="BMW 3D Car Git Worktree",
            category="BMW",
            required=True,
            path=repo_path,
            detail="The BMW models repository is not available from the configured path.",
            fix="Clone or sync digital-3d-car-models, then set Digital-3D-Car-Repo to that worktree.",
        )
    detail = "BMW models worktree is present."
    if marker.exists():
        detail += " models_build_config.yaml was found."
    else:
        detail += " models_build_config.yaml was not found, so registry counts may be weaker."
    return _found_item(
        key="bmw_git_worktree",
        label="BMW 3D Car Git Worktree",
        category="BMW",
        required=True,
        path=repo_path,
        detail=detail,
        fix="Keep Digital-3D-Car-Repo pointed at this worktree.",
    )


def _check_idc23_worktree() -> SetupDoctorItem:
    env_path = _env_path("Digital-3D-Car-Repo-IDC23")
    expected = env_path if env_path is not None else Path("Digital-3D-Car-Repo-IDC23")
    if env_path is None or not env_path.exists():
        return _missing_item(
            key="idc23_worktree",
            label="IDC23 Worktree Env Var",
            category="BMW",
            required=True,
            path=expected,
            detail="Digital-3D-Car-Repo-IDC23 is missing or points at a path that does not exist.",
            fix="Create the IDC23 worktree, then set Digital-3D-Car-Repo-IDC23 to that path with setx.",
        )
    return _found_item(
        key="idc23_worktree",
        label="IDC23 Worktree Env Var",
        category="BMW",
        required=True,
        path=env_path,
        detail="Digital-3D-Car-Repo-IDC23 is set and points at an existing worktree.",
    )


def _registered_dependency_path(root: Path, *keys: str) -> Path | None:
    state = load_dependency_onboarding_state(root)
    registered_paths = state.get("registered_paths", {})
    if not isinstance(registered_paths, dict):
        return None
    for key in keys:
        raw = str(registered_paths.get(key, "")).strip()
        if raw:
            return Path(raw).expanduser()
    return None


def _bmw_ci_venv_python(repo_root: Path) -> Path:
    scripts_dir = "Scripts" if os.name == "nt" else "bin"
    executable = "python.exe" if os.name == "nt" else "python"
    return repo_root / BMW_CI_VENV_DIRNAME / scripts_dir / executable


def _bmw_ci_repo_roots(root: Path) -> list[Path]:
    candidates = [
        _env_path(DIGITAL_3D_CAR_REPO_ENV, "SG_BMW_MODELS_REPO", "SG_CARMODELS_REPO"),
        _env_path(DIGITAL_3D_CAR_REPO_IDC23_ENV),
        _registered_dependency_path(root, "digital_3d_car_repo"),
        _registered_dependency_path(root, "digital_3d_car_repo_idc23", "digital_3d_car_repo_assets_idc23"),
        discover_bmw_models_repo(root),
    ]
    roots: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate is None or not candidate.exists():
            continue
        resolved = candidate.resolve()
        normalized = os.path.normcase(str(resolved))
        if normalized in seen:
            continue
        seen.add(normalized)
        roots.append(resolved)
    return roots


def _resolve_bmw_ci_python(root: Path) -> tuple[Path | None, str]:
    override = os.environ.get(BMW_PIPELINE_PYTHON_ENV, "").strip()
    if override:
        path = Path(override).expanduser()
        if path.is_file():
            return path.resolve(), f"{BMW_PIPELINE_PYTHON_ENV} points to a Python executable."
        return None, f"{BMW_PIPELINE_PYTHON_ENV} is set, but the file does not exist: {path}"
    registered = _registered_dependency_path(root, "bmw_pipeline_python", "python", "python_executable")
    if registered is not None and registered.is_file():
        return registered.resolve(), "BMW pipeline Python is registered in dependency onboarding."
    for repo_root in _bmw_ci_repo_roots(root):
        candidate = _bmw_ci_venv_python(repo_root)
        if candidate.is_file():
            return candidate.resolve(), f"BMW-CI venv Python was found at {candidate}."
    fallback = _bmw_ci_venv_python(_bmw_ci_repo_roots(root)[0]) if _bmw_ci_repo_roots(root) else root / BMW_CI_VENV_DIRNAME
    return None, f"No BMW-CI Python was found at {fallback}."


def _check_bmw_ci_python_deps(root: Path) -> SetupDoctorItem:
    python_path, detail = _resolve_bmw_ci_python(root)
    if python_path is None:
        return _missing_item(
            key="bmw_ci_python_deps",
            label="BMW CI Python requirements",
            category="BMW",
            required=True,
            path="",
            detail=detail,
            fix="Run the 'Install BMW pipeline requirements' setup action from Setup Doctor / Dependency Onboarding.",
        )
    try:
        completed = subprocess.run(
            [str(python_path), "-c", BMW_CI_IMPORT_PROBE],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            **hidden_subprocess_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _missing_item(
            key="bmw_ci_python_deps",
            label="BMW CI Python requirements",
            category="BMW",
            required=True,
            path=python_path,
            detail=f"{detail} Import probe failed: {exc}",
            fix="Run the 'Install BMW pipeline requirements' setup action from Setup Doctor / Dependency Onboarding.",
        )
    if completed.returncode != 0:
        output = (completed.stderr or completed.stdout or "").strip()
        return _missing_item(
            key="bmw_ci_python_deps",
            label="BMW CI Python requirements",
            category="BMW",
            required=True,
            path=python_path,
            detail=f"{python_path} cannot import yaml and PIL yet. {output}",
            fix="Run the 'Install BMW pipeline requirements' setup action from Setup Doctor / Dependency Onboarding.",
        )
    return _found_item(
        key="bmw_ci_python_deps",
        label="BMW CI Python requirements",
        category="BMW",
        required=True,
        path=python_path,
        detail=f"{python_path} can import yaml and PIL. {detail}",
    )


def _qt_webengine_candidates(root: Path) -> list[Path]:
    return [
        root / "dist" / "sgfx-preflight" / "_internal" / "PySide6" / "Qt6WebEngineCore.dll",
        root / ".venv" / "Lib" / "site-packages" / "PySide6" / "Qt6WebEngineCore.dll",
        root / ".venv_bmw_ci" / "Lib" / "site-packages" / "PySide6" / "Qt6WebEngineCore.dll",
    ]


def _check_git_ignorecase(root: Path) -> SetupDoctorItem:
    # PDX onboarding (How-to-set-up-your-Laptop) requires `git config core.ignorecase false` so
    # case-only file differences in the BMW Git repos are tracked on Windows. Advisory only.
    label = "Git case sensitivity (core.ignorecase)"
    fix = "Run: git config core.ignorecase false --global (per the SG laptop-setup onboarding page)."
    env_path = _env_path("Digital-3D-Car-Repo", "SG_BMW_MODELS_REPO", "SG_CARMODELS_REPO")
    repo_path = env_path if env_path is not None else discover_bmw_models_repo(root)
    git = shutil.which("git")
    if git is None:
        return _missing_item(
            key="git_ignorecase", label=label, category="BMW", required=False, path="",
            detail="git was not found on PATH, so case sensitivity could not be verified.", fix=fix)
    anchor = repo_path if repo_path.exists() else root
    value = _version_from_command(
        [git, "-C", str(anchor), "config", "--get", "core.ignorecase"]).strip().casefold()
    if value == "false":
        return _found_item(
            key="git_ignorecase", label=label, category="BMW", required=False, path=anchor,
            detail="core.ignorecase is false; case-only file differences are tracked.",
            fix="Keep core.ignorecase set to false.")
    observed = value or "unset"
    return _missing_item(
        key="git_ignorecase", label=label, category="BMW", required=False, path=anchor,
        detail=f"core.ignorecase is {observed}; case-only file changes may go untracked on Windows.",
        fix=fix)


def _check_bmw_ci_python_version(root: Path) -> SetupDoctorItem:
    # PDX Tools page (CI update 25.11.2025): the 3D-Car screenshot tests need Python 3.12+.
    label = "BMW pipeline Python version"
    recommended = "3.12"
    fix = "Point the BMW pipeline Python at 3.12+ (SG Tools page: screenshot tests need Python 3.12)."
    python_path, detail = _resolve_bmw_ci_python(root)
    if python_path is None:
        # Absence of a pipeline Python is already surfaced by _check_bmw_ci_python_deps
        # (required). This advisory only speaks up when a Python exists but is below 3.12, so
        # stay quiet here rather than double-nagging.
        return _found_item(
            key="bmw_ci_python_version", label=label, category="BMW", required=False, path="",
            recommended_version=recommended,
            detail="No separate BMW pipeline Python is resolved yet; the 3.12 screenshot-test "
                   "pin is checked once one is provisioned.")
    raw = _version_from_command([str(python_path), "--version"])
    digits = "".join(c if c.isdigit() or c == "." else " " for c in raw).split()
    version = digits[0] if digits else ""
    # compare_python_requirement returns "drift" when confidently below the spec, "ok" when it
    # satisfies it, and "unknown"/"not_pinned" when it cannot tell. Only nag on a confident "drift";
    # advisory, so an unverifiable version stays quietly "found". Deliberately does NOT populate the
    # item's version_status/version_check_detail — those feed _version_validation_summary, which
    # tracks pinned graphics-tool versions (RaCo/Blender), not this interpreter check.
    requirement_status, _ = compare_python_requirement(version, ">=3.12") if version else ("unknown", "")
    if requirement_status != "drift":
        return _found_item(
            key="bmw_ci_python_version", label=label, category="BMW", required=False,
            path=python_path, version=version, recommended_version=recommended,
            detail=f"BMW pipeline Python is {version or 'unknown'}, at or above the 3.12 "
                   "screenshot-test pin." if version else
                   "The BMW pipeline Python did not report a version; 3.12+ is recommended.")
    return _missing_item(
        key="bmw_ci_python_version", label=label, category="BMW", required=False, path=python_path,
        version=version, recommended_version=recommended,
        detail=f"BMW pipeline Python is {version}; the 3D-car screenshot tests want 3.12+.", fix=fix)


def _virtual_screen_size() -> tuple[int, int] | None:
    # Full virtual-desktop bounding box across all monitors (Win32 SM_CXVIRTUALSCREEN /
    # SM_CYVIRTUALSCREEN). Returns None when it cannot be read (non-Windows, headless, no ctypes) so
    # the caller can stay quiet rather than nag on a machine where the check does not apply.
    # Deliberately does not touch process DPI awareness — that would be a global side effect on Qt.
    if os.name != "nt":
        return None
    try:
        import ctypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        width = int(user32.GetSystemMetrics(78))
        height = int(user32.GetSystemMetrics(79))
    except Exception:
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


def _check_screenshot_display_resolution(root: Path) -> SetupDoctorItem:
    # PDX 3D-Car "How to screenshottest" page: BMW screenshot tests render to the operator's monitor
    # resolution; below 3340x1440 the output is cropped and comparisons fail as if content drifted.
    # Multi-monitor widths add up; height takes the tallest monitor. Advisory pre-check so this is
    # caught before a run, not from a confusing failure afterwards.
    label = "Screenshot display resolution"
    fix = ("Use a display of at least 3340 x 1440 for BMW screenshot tests (multi-monitor widths add "
           "up; one monitor must be 1440+ tall), otherwise generated screenshots are cropped.")
    size = _virtual_screen_size()
    if size is None:
        return _found_item(
            key="screenshot_display_resolution", label=label, category="BMW", required=False, path="",
            detail="Display resolution could not be read on this host; the 3340 x 1440 screenshot "
                   "minimum is checked when running with a desktop session.")
    width, height = size
    if width >= SCREENSHOT_MIN_DISPLAY_WIDTH and height >= SCREENSHOT_MIN_DISPLAY_HEIGHT:
        return _found_item(
            key="screenshot_display_resolution", label=label, category="BMW", required=False, path="",
            detail=f"Desktop is {width} x {height}, at or above the 3340 x 1440 screenshot minimum.")
    return _missing_item(
        key="screenshot_display_resolution", label=label, category="BMW", required=False, path="",
        detail=f"Desktop is {width} x {height}; below the 3340 x 1440 screenshot minimum, generated "
               "screenshots will be cropped and the tests fail.", fix=fix)


def _check_qt_webengine(root: Path) -> SetupDoctorItem:
    candidate = _first_existing(_qt_webengine_candidates(root))
    if not candidate.exists():
        return _missing_item(
            key="qt_webengine_core",
            label="Qt6WebEngineCore.dll",
            category="Dashboard",
            required=True,
            path=candidate,
            detail="The dashboard build will not launch without the WebEngine runtime DLL.",
            fix="Place Qt6WebEngineCore.dll under dist\\sgfx-preflight\\_internal\\PySide6\\ or install the desktop extra into the active venv.",
        )
    return _found_item(
        key="qt_webengine_core",
        label="Qt6WebEngineCore.dll",
        category="Dashboard",
        required=True,
        path=candidate,
        detail=f"Dashboard WebEngine runtime found ({candidate.stat().st_size} bytes).",
    )


def _ramses_sdk_candidates(root: Path) -> list[Path]:
    env_path = _env_path("SG_RAMSES_SDK", "RAMSES_SDK_ROOT", "CMAKE_PREFIX_PATH")
    candidates = [
        root / "external" / "ramses",
        root / "cpp" / "build" / "vs2022-ramses-28.16" / "Release",
        Path(r"C:\ramses-28.16.0-install"),
    ]
    if env_path is not None:
        candidates.insert(0, env_path)
    return candidates


def _check_ramses_sdk(root: Path) -> SetupDoctorItem:
    candidates = _ramses_sdk_candidates(root)
    for candidate in candidates:
        cmake_config = candidate / "lib" / "ramses-shared-lib-28.16" / "cmake" / "ramses-shared-libConfig.cmake"
        release_dll = candidate / "ramses-shared-lib-headless.dll"
        install_dll = candidate / "bin" / "ramses-shared-lib-headless.dll"
        if candidate.exists() and (cmake_config.exists() or release_dll.exists() or install_dll.exists()):
            detail = "Ramses SDK/runtime is present."
            if cmake_config.exists():
                detail += " CMake config for 28.16 was found."
            if release_dll.exists() or install_dll.exists():
                detail += " Runtime DLLs are available."
            return _found_item(
                key="ramses_sdk_runtime",
                label="Ramses SDK / Runtime",
                category="Runtime",
                required=True,
                path=candidate,
                recommended_version=RAMSES_PIPELINE_PIN,
                version_status="ok",
                version_check_detail=(
                    f"Pipeline reference {RAMSES_PIPELINE_PIN} from {RAMSES_PIPELINE_PIN_SOURCE}; "
                    "presence check found the expected runtime files."
                ),
                detail=detail,
            )
    candidate = candidates[0]
    return _missing_item(
        key="ramses_sdk_runtime",
        label="Ramses SDK / Runtime",
        category="Runtime",
        required=True,
        path=candidate,
        detail="The Ramses SDK/runtime path was not found.",
        fix="Install Ramses 28.16.0 or build the C++ shell so the runtime DLLs are copied beside the executable.",
        recommended_version=RAMSES_PIPELINE_PIN,
        version_status="unknown",
        version_check_detail=(
            f"Pipeline reference {RAMSES_PIPELINE_PIN} from {RAMSES_PIPELINE_PIN_SOURCE}; "
            "presence check did not find the runtime files."
        ),
    )


def _check_python_runtime() -> SetupDoctorItem:
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    path = Path(sys.executable)
    specifier, source = python_requirement()
    version_status, version_detail = compare_python_requirement(f"Python {version}", specifier)
    if sys.version_info < (3, 10):
        return _missing_item(
            key="python_runtime",
            label="Python Runtime",
            category="Runtime",
            required=True,
            path=path,
            detail=f"Current Python is {version}; sg-preflight requires Python 3.10 or newer.",
            fix="Install Python 3.13 or run the tool from the bundled environment.",
            version=f"Python {version}",
            recommended_version=specifier,
            version_status=version_status,
            version_check_detail=f"{version_detail} Source: {source}.",
        )

    py_launcher = shutil.which("py")
    launcher_version = _version_from_command([py_launcher, "-3.13", "--version"]) if py_launcher else ""
    detail = "Current Python can run sg-preflight."
    if launcher_version:
        detail += f" py -3.13 reports: {launcher_version}."
    elif py_launcher:
        detail += " The py launcher exists, but py -3.13 did not report a version."
    else:
        detail += " The py launcher was not found; the active interpreter is still usable."
    return _found_item(
        key="python_runtime",
        label="Python Runtime",
        category="Runtime",
        required=True,
        path=path,
        version=f"Python {version}",
        recommended_version=specifier,
        version_status=version_status,
        version_check_detail=f"{version_detail} Source: {source}.",
        detail=detail,
    )


def _check_jira_pat() -> SetupDoctorItem:
    path = Path.home() / "sgfx_operator_state" / "jira_pat.json"
    if not path.exists():
        return _optional_missing_item(
            key="jira_pat",
            label="Jira PAT",
            category="Optional",
            path=path,
            detail="Jira writeback and inline ticket cards stay optional.",
            fix="Run sgfx-preflight.exe integration jira register --confirm-local-write only if you want Jira integration. The doctor checks the URL config path only; the PAT stays in the OS keychain.",
        )
    return _found_item(
        key="jira_pat",
        label="Jira PAT",
        category="Optional",
        required=False,
        path=path,
        detail="Jira URL config exists. PAT value was not read; it is expected to live in the OS keychain.",
    )


def build_setup_doctor_report(workspace: Path | None = None) -> SetupDoctorReport:
    root = (workspace or Path(__file__).resolve().parents[1]).resolve()
    mirror_root = mirror_repo_root(root)
    source_root = resolve_source_repo_root(root)
    items = (
        _check_raco_headless(root, source_root, mirror_root),
        _check_raco_gui(root, source_root, mirror_root),
        _check_blender(root),
        _check_bmw_git(root),
        _check_idc23_worktree(),
        _check_git_ignorecase(root),
        _check_bmw_ci_python_deps(root),
        _check_bmw_ci_python_version(root),
        _check_screenshot_display_resolution(root),
        _check_qt_webengine(root),
        _check_ramses_sdk(root),
        _check_python_runtime(),
        _check_jira_pat(),
    )
    required_missing = sum(1 for item in items if item.required and item.status != "found")
    optional_missing = sum(1 for item in items if not item.required and item.status != "found")
    found = sum(1 for item in items if item.status == "found")
    return SetupDoctorReport(
        workspace_root=str(root),
        generated_at_utc=_utc_now(),
        ready=required_missing == 0,
        required_missing_count=required_missing,
        optional_missing_count=optional_missing,
        found_count=found,
        items=items,
    )
