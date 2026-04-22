from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
_BMW_PROFILE_OVERRIDES = {
    "G50": "G50_EVO",
    "G65": "G65_EVO",
    "G70": "G70_EVO",
    "G78": "G78_EVO",
    "NA0": "NA0_EVO",
    "NA5": "NA5_EVO",
    "NA6": "NA6_EVO",
    "NA8": "NA8_EVO",
}


def _workspace_root(explicit_root: Path | None = None) -> Path:
    return (explicit_root or Path(__file__).resolve().parents[1]).resolve()


def _candidate_repo_paths(root: Path) -> tuple[Path, ...]:
    return (
        root / "digital-3d-car-models",
        root / "external" / "digital-3d-car-models",
        root.parent / "digital-3d-car-models",
        Path(r"C:\repos\digital-3d-car-models"),
    )


def discover_bmw_models_repo(workspace_root: Path | None = None) -> Path:
    root = _workspace_root(workspace_root)
    for key in ("SG_BMW_CAR_MODELS_ROOT", "SG_CARMODELS_REPO", "SG-CarModels-Repo"):
        raw = os.environ.get(key, "").strip()
        if raw:
            return Path(raw)
    for candidate in _candidate_repo_paths(root):
        if candidate.exists():
            return candidate
    return _candidate_repo_paths(root)[0]


def candidate_bmw_profile_ids(profile_id: str) -> tuple[str, ...]:
    normalized = profile_id.strip().upper()
    if not normalized:
        return ()
    candidates: list[str] = []
    for item in (
        _BMW_PROFILE_OVERRIDES.get(normalized, ""),
        normalized,
        f"{normalized}_EVO",
    ):
        if item and item not in candidates:
            candidates.append(item)
    return tuple(candidates)


def resolve_bmw_profile_id(profile_id: str, repo_root: Path | None = None) -> str:
    repo = (repo_root or Path()).resolve() if repo_root else Path()
    if repo:
        bmw_root = repo / "cars" / "BMW"
        for candidate in candidate_bmw_profile_ids(profile_id):
            if (bmw_root / candidate).exists():
                return candidate
    candidates = candidate_bmw_profile_ids(profile_id)
    return candidates[0] if candidates else profile_id.strip()


def _image_count(root: Path) -> int:
    if not root.exists() or not root.is_dir():
        return 0
    return sum(1 for path in root.rglob("*") if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES)


def _find_test_config(tests_root: Path) -> Path:
    direct = tests_root / "test_config.lua"
    if direct.exists():
        return direct
    temp = tests_root / "test_config_tmp.lua"
    if temp.exists():
        return temp
    matches = sorted(tests_root.glob("test_config*.lua")) if tests_root.exists() else []
    return matches[0] if matches else Path()


@dataclass(frozen=True)
class BmwScreenshotSurface:
    profile_id: str
    bmw_profile_id: str
    repo_root: str = ""
    cars_root: str = ""
    car_root: str = ""
    ci_scripts_root: str = ""
    ci_tools_root: str = ""
    ci_readme_path: str = ""
    car_manager_path: str = ""
    export_tests_root: str = ""
    sg_expected_root: str = ""
    bmw_expected_root: str = ""
    actuals_root: str = ""
    diff_root: str = ""
    test_config_path: str = ""
    sg_expected_count: int = 0
    bmw_expected_count: int = 0
    actual_count: int = 0
    diff_count: int = 0
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def inspect_bmw_screenshot_surface(
    profile_id: str,
    *,
    workspace_root: Path | None = None,
    sg_project_root: Path | None = None,
) -> BmwScreenshotSurface:
    repo_root = discover_bmw_models_repo(workspace_root).resolve()
    cars_root = repo_root / "cars" / "BMW"
    bmw_profile_id = resolve_bmw_profile_id(profile_id, repo_root)
    car_root = cars_root / bmw_profile_id
    export_tests_root = car_root / "export" / "tests"
    actuals_root = export_tests_root / "actuals"
    diff_root = export_tests_root / "diff"
    bmw_expected_root = export_tests_root / "expected"
    ci_scripts_root = repo_root / "ci" / "scripts"
    ci_tools_root = repo_root / "ci" / "tools"
    ci_readme_path = ci_scripts_root / "README.md"
    car_manager_path = ci_scripts_root / "car_manager.py"
    sg_expected_root = (sg_project_root.resolve() / "export" / "tests" / "expected") if sg_project_root else Path()
    test_config_path = _find_test_config(export_tests_root)

    notes: list[str] = []
    if export_tests_root.exists():
        notes.append("BMW export/tests surface is present locally.")
    else:
        notes.append("BMW export/tests surface is not present locally for this profile.")
    if actuals_root.exists() and _image_count(actuals_root) == 0:
        notes.append("BMW actuals root exists but currently contains no screenshot payload.")
    if diff_root.exists() and _image_count(diff_root) == 0:
        notes.append("BMW diff root exists but currently contains no diff payload.")
    if not bmw_expected_root.exists():
        notes.append("No BMW expected root is visible in the local snapshot for this profile.")
    if not sg_expected_root.exists():
        notes.append("No SG expected baseline root is available under the live SVN slice for this profile.")
    if test_config_path.exists() and test_config_path.name != "test_config.lua":
        notes.append(f"BMW uses `{test_config_path.name}` in this snapshot instead of `test_config.lua`.")

    return BmwScreenshotSurface(
        profile_id=profile_id,
        bmw_profile_id=bmw_profile_id,
        repo_root=str(repo_root) if repo_root.exists() else "",
        cars_root=str(cars_root) if cars_root.exists() else "",
        car_root=str(car_root) if car_root.exists() else "",
        ci_scripts_root=str(ci_scripts_root) if ci_scripts_root.exists() else "",
        ci_tools_root=str(ci_tools_root) if ci_tools_root.exists() else "",
        ci_readme_path=str(ci_readme_path) if ci_readme_path.exists() else "",
        car_manager_path=str(car_manager_path) if car_manager_path.exists() else "",
        export_tests_root=str(export_tests_root) if export_tests_root.exists() else "",
        sg_expected_root=str(sg_expected_root) if sg_expected_root.exists() else "",
        bmw_expected_root=str(bmw_expected_root) if bmw_expected_root.exists() else "",
        actuals_root=str(actuals_root) if actuals_root.exists() else "",
        diff_root=str(diff_root) if diff_root.exists() else "",
        test_config_path=str(test_config_path) if test_config_path.exists() else "",
        sg_expected_count=_image_count(sg_expected_root),
        bmw_expected_count=_image_count(bmw_expected_root),
        actual_count=_image_count(actuals_root),
        diff_count=_image_count(diff_root),
        notes=tuple(notes),
    )
