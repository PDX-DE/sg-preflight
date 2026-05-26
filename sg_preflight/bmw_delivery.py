from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


DIGITAL_3D_CAR_REPO_ENV = "Digital-3D-Car-Repo"
DIGITAL_3D_CAR_REPO_IDC23_ENV = "Digital-3D-Car-Repo-IDC23"
BMW_MODEL_CONFIG_RELATIVE = Path("ci") / "scripts" / "common" / "models_build_config.yaml"
LANE_IDC23 = "idc_23"
LANE_IDCEVO = "idc_evo"
LANE_UNKNOWN = "unknown"
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
_BMW_PROFILE_OVERRIDES = {
    "G58": "G58_EVO",
    "G50": "G50_EVO",
    "G65": "G65_EVO",
    "G70": "G70_EVO",
    "G78": "G78_EVO",
    "NA0": "NA0_EVO",
    "NA5": "NA5_EVO",
    "NA6": "NA6_EVO",
    "NA8": "NA8_EVO",
}
_BRAND_FOLDERS = {
    "BMW": "BMW",
    "MINI": "MINI",
    "ALPINA": "Alpina",
    "MGMBH": "MGmbH",
    "ROLLSROYCE": "RollsRoyce",
}
_BRAND_PROFILE_PREFIXES = {
    "MINI": "MINI",
    "ALPINA": "ALPINA",
    "MGMBH": "MGMBH",
    "ROLLSROYCE": "ROLLSROYCE",
}
_SCREENSHOT_BRANDS = tuple(_BRAND_FOLDERS.values())


@dataclass(frozen=True)
class BmwModelConfigRecord:
    name: str
    brand: str = ""
    model_type: str = ""
    hmi_interface_version: int | None = None
    additional_interface_version: int | None = None
    target: str = ""


@dataclass(frozen=True)
class BmwRegistryEntry:
    profile_id: str
    bmw_profile_id: str
    lane: str
    model_type: str
    brand: str
    interface_version: int | None = None
    target: str = ""
    active_build: bool = False
    registry_source: str = "models_build_config.yaml"

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "bmw_profile_id": self.bmw_profile_id,
            "lane": self.lane,
            "type": self.model_type,
            "brand": self.brand,
            "interface_version": self.interface_version,
            "target": self.target,
            "active_build": self.active_build,
            "registry_source": self.registry_source,
        }


def _workspace_root(explicit_root: Path | None = None) -> Path:
    return (explicit_root or Path(__file__).resolve().parents[1]).resolve()


def _candidate_repo_paths(root: Path) -> tuple[Path, ...]:
    return (
        root / "digital-3d-car-models",
        root / "external" / "digital-3d-car-models",
        root.parent / "digital-3d-car-models",
        Path(r"C:\3D Car git\digital-3d-car-models"),
        Path(r"C:\repos\digital-3d-car-models"),
    )


def discover_bmw_models_repo(workspace_root: Path | None = None) -> Path:
    root = _workspace_root(workspace_root)
    candidates = _candidate_repo_paths(root)
    for candidate in candidates[:3]:
        if candidate.exists():
            return candidate
    for key in (DIGITAL_3D_CAR_REPO_ENV, "SG_BMW_CAR_MODELS_ROOT", "SG_CARMODELS_REPO", "SG-CarModels-Repo"):
        raw = os.environ.get(key, "").strip()
        if raw:
            return Path(raw)
    for candidate in candidates[3:]:
        if candidate.exists():
            return candidate
    return candidates[0]


def _yaml_scalar(value: str) -> str:
    cleaned = value.strip()
    if cleaned.startswith(("'", '"')) and cleaned.endswith(("'", '"')) and len(cleaned) >= 2:
        return cleaned[1:-1]
    return cleaned


def _int_scalar(value: str) -> int | None:
    try:
        return int(_yaml_scalar(value))
    except ValueError:
        return None


def _brand_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _canonical_brand(value: str) -> str:
    compact = _brand_key(value)
    return {
        "bmw": "BMW",
        "mini": "MINI",
        "alpina": "Alpina",
        "mgmbh": "MGmbH",
        "rollsroyce": "RollsRoyce",
    }.get(compact, value.strip() or "BMW")


def _brand_folder(value: str) -> str:
    return _BRAND_FOLDERS.get(_canonical_brand(value).upper(), _canonical_brand(value))


def _brand_profile_prefix(value: str) -> str:
    return _BRAND_PROFILE_PREFIXES.get(_canonical_brand(value).upper(), "")


def _strip_evo_suffix(value: str) -> str:
    normalized = value.strip().upper()
    return normalized[:-4] if normalized.endswith("_EVO") else normalized


def _strip_known_brand_prefix(value: str) -> tuple[str, str]:
    normalized = value.strip().upper()
    for brand_key, prefix in _BRAND_PROFILE_PREFIXES.items():
        token = f"{prefix}_"
        if normalized.startswith(token):
            return _canonical_brand(brand_key), normalized[len(token) :]
    return "", normalized


def _parse_models_build_config(text: str) -> tuple[BmwModelConfigRecord, ...]:
    records: list[BmwModelConfigRecord] = []
    current: dict[str, Any] | None = None
    section = ""

    def flush() -> None:
        if current and current.get("name"):
            records.append(
                BmwModelConfigRecord(
                    name=str(current.get("name", "")).strip().upper(),
                    brand=_canonical_brand(str(current.get("brand", "")).strip()),
                    model_type=str(current.get("type", "")).strip().casefold(),
                    hmi_interface_version=current.get("hmi_interface_version"),
                    additional_interface_version=current.get("additional_interface_version"),
                    target=str(current.get("target", "")).strip().upper(),
                )
            )

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped == "---" or stripped.startswith("#"):
            continue
        if stripped.startswith("- name:"):
            flush()
            current = {"name": _yaml_scalar(stripped.split(":", 1)[1])}
            section = ""
            continue
        if current is None:
            continue
        if stripped.endswith(":"):
            section = stripped[:-1].strip().casefold()
            continue
        if ":" not in stripped:
            continue
        key, raw_value = (part.strip() for part in stripped.split(":", 1))
        value = _yaml_scalar(raw_value)
        key = key.casefold()
        if section == "hmi" and key == "interface_version":
            current["hmi_interface_version"] = _int_scalar(value)
        elif section == "additional_build" and key == "interface_version":
            current["additional_interface_version"] = _int_scalar(value)
        elif not section:
            current[key] = value
    flush()
    return tuple(records)


@lru_cache(maxsize=16)
def _load_model_config_records_cached(repo_root: str) -> tuple[BmwModelConfigRecord, ...]:
    config_path = Path(repo_root) / BMW_MODEL_CONFIG_RELATIVE
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError:
        return ()
    return _parse_models_build_config(text)


def load_bmw_model_config_records(repo_root: Path | str) -> tuple[BmwModelConfigRecord, ...]:
    return _load_model_config_records_cached(str(Path(repo_root).resolve()))


def _model_config_by_name(repo_root: Path | str) -> dict[str, BmwModelConfigRecord]:
    return {record.name: record for record in load_bmw_model_config_records(repo_root)}


def _lane_for_model(record: BmwModelConfigRecord) -> str:
    if record.model_type == "retarget" or record.name.endswith("_EVO"):
        return LANE_IDCEVO
    if record.hmi_interface_version is None:
        return LANE_UNKNOWN
    if record.hmi_interface_version >= 24:
        return LANE_IDCEVO
    return LANE_IDC23


def _matching_model_config_record(profile_id: str, repo_root: Path | str) -> BmwModelConfigRecord | None:
    brand_hint, _base_profile = _strip_known_brand_prefix(profile_id)
    records = load_bmw_model_config_records(repo_root)
    for candidate in candidate_bmw_profile_ids(profile_id):
        for record in records:
            if record.name != candidate.upper():
                continue
            if brand_hint and _canonical_brand(record.brand) != brand_hint:
                continue
            return record
    return None


def detect_lane(profile_id: str, *, bmw_root: Path | str | None) -> str:
    if bmw_root is None:
        return LANE_UNKNOWN
    if not load_bmw_model_config_records(bmw_root):
        return LANE_UNKNOWN
    record = _matching_model_config_record(profile_id, bmw_root)
    return _lane_for_model(record) if record is not None else LANE_UNKNOWN


def resolve_svn_profile_id(profile_id: str) -> str:
    _brand_hint, normalized = _strip_known_brand_prefix(profile_id)
    return _strip_evo_suffix(normalized)


def candidate_bmw_profile_ids(profile_id: str) -> tuple[str, ...]:
    _brand_hint, normalized = _strip_known_brand_prefix(profile_id)
    if not normalized:
        return ()
    candidates: list[str] = []
    stripped = _strip_evo_suffix(normalized)
    items = [normalized]
    if normalized.endswith("_EVO"):
        items.append(stripped)
    else:
        items.insert(0, _BMW_PROFILE_OVERRIDES.get(stripped, ""))
        items.append(f"{stripped}_EVO")
    for item in items:
        if item and item not in candidates:
            candidates.append(item)
    return tuple(candidates)


def _brand_search_order(profile_id: str) -> tuple[str, ...]:
    brand_hint, _base_profile = _strip_known_brand_prefix(profile_id)
    if not brand_hint:
        return _SCREENSHOT_BRANDS
    preferred = _brand_folder(brand_hint)
    return (preferred, *tuple(brand for brand in _SCREENSHOT_BRANDS if brand != preferred))


def resolve_bmw_profile_id(profile_id: str, repo_root: Path | None = None) -> str:
    repo = (repo_root or Path()).resolve() if repo_root else Path()
    if repo:
        for brand in _brand_search_order(profile_id):
            brand_root = repo / "cars" / brand
            for candidate in candidate_bmw_profile_ids(profile_id):
                if (brand_root / candidate).exists():
                    return candidate
    candidates = candidate_bmw_profile_ids(profile_id)
    return candidates[0] if candidates else profile_id.strip()


def _resolve_car_root(repo_root: Path, profile_id: str) -> tuple[str, str, Path, Path]:
    candidates = candidate_bmw_profile_ids(profile_id)
    for brand in _brand_search_order(profile_id):
        brand_root = repo_root / "cars" / brand
        for candidate in candidates:
            car_root = brand_root / candidate
            if car_root.exists():
                return brand, candidate, brand_root, car_root

    record = _matching_model_config_record(profile_id, repo_root)
    if record is not None and record.model_type == "retarget" and record.target:
        brand = _brand_folder(record.brand)
        brand_root = repo_root / "cars" / brand
        target_root = brand_root / record.target
        if target_root.exists():
            return brand, record.name, brand_root, target_root

    fallback_brand = "BMW"
    matched = candidates[0] if candidates else profile_id.strip()
    brand_root = repo_root / "cars" / fallback_brand
    return fallback_brand, matched, brand_root, brand_root / matched


def _registry_base_profile_id(record: BmwModelConfigRecord) -> str:
    base = _strip_evo_suffix(record.name)
    prefix = _brand_profile_prefix(record.brand)
    return f"{prefix}_{base}" if prefix else base


def _registry_exact_profile_id(record: BmwModelConfigRecord) -> str:
    prefix = _brand_profile_prefix(record.brand)
    return f"{prefix}_{record.name}" if prefix else record.name


def _registry_entry_from_record(
    record: BmwModelConfigRecord,
    *,
    base_counts: Counter[str],
) -> BmwRegistryEntry:
    base_profile_id = _registry_base_profile_id(record)
    profile_id = base_profile_id
    if base_counts[base_profile_id] > 1 and record.name.endswith("_EVO"):
        profile_id = _registry_exact_profile_id(record)
    interface_version = record.hmi_interface_version
    if interface_version is None:
        interface_version = record.additional_interface_version
    model_type = record.model_type or "unknown"
    return BmwRegistryEntry(
        profile_id=profile_id,
        bmw_profile_id=record.name,
        lane=_lane_for_model(record),
        model_type=model_type,
        brand=_canonical_brand(record.brand),
        interface_version=interface_version,
        target=record.target,
        active_build=model_type == "build",
    )


def load_bmw_registry(repo_root: Path | str) -> tuple[BmwRegistryEntry, ...]:
    records = load_bmw_model_config_records(repo_root)
    base_counts = Counter(_registry_base_profile_id(record) for record in records)
    return tuple(_registry_entry_from_record(record, base_counts=base_counts) for record in records)


def find_bmw_registry_entry(profile_id: str, repo_root: Path | str) -> BmwRegistryEntry | None:
    requested = profile_id.strip().casefold()
    if not requested:
        return None
    for entry in load_bmw_registry(repo_root):
        aliases = {
            entry.profile_id.casefold(),
            entry.bmw_profile_id.casefold(),
            resolve_svn_profile_id(entry.profile_id).casefold(),
            resolve_svn_profile_id(entry.bmw_profile_id).casefold(),
        }
        if requested in aliases:
            return entry
    return None


def _image_count(root: Path) -> int:
    if not root.exists() or not root.is_dir():
        return 0
    return sum(1 for path in root.rglob("*") if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES)


def _natural_sort_key(path: Path) -> tuple[Any, ...]:
    parts: list[Any] = []
    for chunk in re.split(r"(\d+)", path.name.casefold()):
        if not chunk:
            continue
        parts.append(int(chunk) if chunk.isdigit() else chunk)
    return tuple(parts)


def _comparison_image_count(root: Path) -> int:
    if not root.exists() or not root.is_dir():
        return 0
    count = 0
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _IMAGE_SUFFIXES:
            continue
        haystack = " ".join(part.casefold() for part in (*path.parts, path.stem))
        if "comparison" in haystack or "compare" in haystack or "diff" in haystack:
            count += 1
    return count


def _candidate_prespectives_profile_dirs(root: Path, profile_id: str) -> tuple[Path, ...]:
    profile = resolve_svn_profile_id(profile_id)
    candidates = []
    for item in (profile_id.strip().upper(), profile):
        if item and item not in candidates:
            candidates.append(item)
    base_candidates = (
        root / ".pdx" / "checkers" / "prespectivesTests",
        root / "repositories" / "trunk" / ".pdx" / "checkers" / "prespectivesTests",
    )
    return tuple(base / candidate / "perspectives_CID_2to1" for base in base_candidates for candidate in candidates)


def _latest_prespectives_folder(root: Path, profile_id: str) -> Path | None:
    matches: list[Path] = []
    for candidate in _candidate_prespectives_profile_dirs(root, profile_id):
        if not candidate.is_dir():
            continue
        matches.extend(path for path in candidate.iterdir() if path.is_dir())
    if not matches:
        return None
    return sorted(matches, key=_natural_sort_key)[-1]


def _find_test_config(tests_root: Path) -> Path:
    direct = tests_root / "test_config.lua"
    if direct.exists():
        return direct
    temp = tests_root / "test_config_tmp.lua"
    if temp.exists():
        return temp
    matches = sorted(tests_root.glob("test_config*.lua")) if tests_root.exists() else []
    return matches[0] if matches else Path()


def _disabled_test_count(test_config_path: Path) -> int:
    if not test_config_path.exists() or not test_config_path.is_file():
        return 0
    try:
        text = test_config_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    return len(re.findall(r"\bdisableTest\s*\(", text))


@dataclass(frozen=True)
class BmwScreenshotSurface:
    profile_id: str
    bmw_profile_id: str
    brand: str = "BMW"
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
    sg_perspectives_root: str = ""
    sg_perspectives_latest_folder: str = ""
    sg_perspectives_screenshot_count: int = 0
    sg_perspectives_comparison_count: int = 0
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def inspect_bmw_screenshot_surface(
    profile_id: str,
    *,
    workspace_root: Path | None = None,
    sg_project_root: Path | None = None,
    bmw_root: Path | str | None = None,
) -> BmwScreenshotSurface:
    repo_root = Path(bmw_root).resolve() if bmw_root is not None else discover_bmw_models_repo(workspace_root).resolve()
    brand, bmw_profile_id, cars_root, car_root = _resolve_car_root(repo_root, profile_id)
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
    prespectives_root = _latest_prespectives_folder(_workspace_root(workspace_root), profile_id)
    prespectives_found = prespectives_root is not None

    notes: list[str] = []
    if export_tests_root.exists():
        notes.append(f"{brand} export/tests surface is present locally.")
    else:
        notes.append("BMW export/tests surface is not present locally for this profile.")
    if actuals_root.exists() and _image_count(actuals_root) == 0:
        notes.append("BMW actuals root exists but currently contains no screenshot payload.")
    if diff_root.exists() and _image_count(diff_root) == 0:
        notes.append("BMW diff root exists but currently contains no diff payload.")
    if not bmw_expected_root.exists():
        notes.append("No BMW expected root is visible in the local snapshot for this profile.")
    if not sg_project_root or not sg_expected_root.exists():
        notes.append("No SG expected baseline root is available under the live SVN slice for this profile.")
    if prespectives_found:
        notes.append("SG prespectivesTests output is present locally for this profile.")
    else:
        notes.append("No SG prespectivesTests output is available under the live SVN workspace for this profile.")
    if test_config_path.exists() and test_config_path.name != "test_config.lua":
        notes.append(f"BMW uses `{test_config_path.name}` in this snapshot instead of `test_config.lua`.")

    return BmwScreenshotSurface(
        profile_id=profile_id,
        bmw_profile_id=bmw_profile_id,
        brand=brand,
        repo_root=str(repo_root) if repo_root.exists() else "",
        cars_root=str(cars_root) if cars_root.exists() else "",
        car_root=str(car_root) if car_root.exists() else "",
        ci_scripts_root=str(ci_scripts_root) if ci_scripts_root.exists() else "",
        ci_tools_root=str(ci_tools_root) if ci_tools_root.exists() else "",
        ci_readme_path=str(ci_readme_path) if ci_readme_path.exists() else "",
        car_manager_path=str(car_manager_path) if car_manager_path.exists() else "",
        export_tests_root=str(export_tests_root) if export_tests_root.exists() else "",
        sg_expected_root=str(sg_expected_root) if sg_project_root and sg_expected_root.exists() else "",
        bmw_expected_root=str(bmw_expected_root) if bmw_expected_root.exists() else "",
        actuals_root=str(actuals_root) if actuals_root.exists() else "",
        diff_root=str(diff_root) if diff_root.exists() else "",
        test_config_path=str(test_config_path) if test_config_path.exists() else "",
        sg_expected_count=_image_count(sg_expected_root) if sg_project_root else 0,
        bmw_expected_count=_image_count(bmw_expected_root),
        actual_count=_image_count(actuals_root),
        diff_count=_image_count(diff_root),
        sg_perspectives_root=str(prespectives_root.parent) if prespectives_found else "",
        sg_perspectives_latest_folder=str(prespectives_root) if prespectives_found else "",
        sg_perspectives_screenshot_count=_image_count(prespectives_root) if prespectives_found else 0,
        sg_perspectives_comparison_count=_comparison_image_count(prespectives_root) if prespectives_found else 0,
        notes=tuple(notes),
    )


SCREENSHOT_STATE_BANNER = (
    "Screenshot test state is read-only from local BMW/MINI Git/SVN screenshot folders. "
    "SGFX does not run screenshot tests or approve screenshots."
)
_SCREENSHOT_STATE_NOTE = "Read-only screenshot test state; manual review remains required; not approval or delivery signoff."


def _surface_status(surface: BmwScreenshotSurface) -> str:
    if (
        surface.bmw_expected_count > 0
        and surface.actual_count == 0
        and surface.diff_count == 0
        and surface.sg_perspectives_screenshot_count == 0
    ):
        return "incomplete"
    if surface.bmw_expected_count > 0 or surface.sg_perspectives_screenshot_count > 0:
        return "available"
    if surface.export_tests_root:
        return "no_expected_baselines"
    if surface.car_root:
        return "no_export_tests"
    return "unavailable"


def read_bmw_screenshot_state(
    profile_id: str,
    *,
    workspace: Path | str | None = None,
    bmw_root: Path | str | None = None,
    sg_project_root: Path | str | None = None,
) -> dict[str, Any]:
    workspace_path = Path(workspace).resolve() if workspace is not None else None
    sg_root = Path(sg_project_root).resolve() if sg_project_root is not None else None
    surface = inspect_bmw_screenshot_surface(
        profile_id,
        workspace_root=workspace_path,
        sg_project_root=sg_root,
        bmw_root=bmw_root,
    )
    status = _surface_status(surface)
    disabled_count = _disabled_test_count(Path(surface.test_config_path)) if surface.test_config_path else 0
    if status == "incomplete":
        summary = (
            f"{surface.bmw_expected_count} expected / 0 actual / 0 diff screenshot file(s). "
            "No actual screenshots captured yet; run screenshot capture before treating this step as evidence."
        )
    elif surface.bmw_expected_count or surface.actual_count or surface.diff_count:
        summary = (
            f"{surface.bmw_expected_count} expected / {surface.actual_count} actual / "
            f"{surface.diff_count} diff screenshot file(s)"
        )
    else:
        summary = f"screenshot test state unavailable for {profile_id.strip() or 'profile'}"
    if surface.sg_perspectives_screenshot_count:
        summary += (
            f"; SG prespectivesTests latest folder has {surface.sg_perspectives_screenshot_count} screenshot file(s)"
            f" and {surface.sg_perspectives_comparison_count} comparison file(s)"
        )
    return {
        "profile_id": surface.profile_id,
        "matched_profile_id": surface.bmw_profile_id,
        "brand": surface.brand,
        "status": status,
        "data_available": status in {"available", "incomplete"},
        "repo_root": surface.repo_root,
        "car_root": surface.car_root,
        "export_tests_root": surface.export_tests_root,
        "expected_root": surface.bmw_expected_root,
        "actuals_root": surface.actuals_root,
        "diff_root": surface.diff_root,
        "sg_perspectives_root": surface.sg_perspectives_root,
        "sg_perspectives_latest_folder": surface.sg_perspectives_latest_folder,
        "test_config_path": surface.test_config_path,
        "expected_count": surface.bmw_expected_count,
        "actual_count": surface.actual_count,
        "diff_count": surface.diff_count,
        "sg_perspectives_screenshot_count": surface.sg_perspectives_screenshot_count,
        "sg_perspectives_comparison_count": surface.sg_perspectives_comparison_count,
        "disabled_test_count": disabled_count,
        "sg_expected_count": surface.sg_expected_count,
        "notes": list(surface.notes),
        "summary": summary,
        "note": _SCREENSHOT_STATE_NOTE,
        "guidance": "Suggested screenshot review input only; compare expected, actuals, and diff folders before recording any reviewer verdict.",
        "is_approval": False,
    }


def read_bmw_screenshot_states_for_profiles(
    profile_ids: tuple[str, ...] | list[str],
    *,
    workspace: Path | str | None = None,
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    payloads: list[dict[str, Any]] = []
    for profile_id in profile_ids:
        profile = str(profile_id).strip()
        if not profile or profile.casefold() in seen:
            continue
        seen.add(profile.casefold())
        payloads.append(read_bmw_screenshot_state(profile, workspace=workspace))
    return payloads


def bmw_screenshot_state_digest_items(state: dict[str, Any]) -> list[dict[str, Any]]:
    payloads = state.get("bmw_screenshot_state", [])
    if not isinstance(payloads, list):
        return []
    items: list[dict[str, Any]] = []
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        profile = str(payload.get("profile_id", "")).strip()
        matched = str(payload.get("matched_profile_id", "")).strip()
        brand = str(payload.get("brand", "")).strip()
        matched_label = f"{brand} {matched}".strip() if brand and matched else matched
        label_profile = f"{profile} / {matched_label}" if profile and matched_label and profile != matched_label else profile or matched_label
        expected = int(payload.get("expected_count", 0) or 0)
        actual = int(payload.get("actual_count", 0) or 0)
        diff = int(payload.get("diff_count", 0) or 0)
        disabled = int(payload.get("disabled_test_count", 0) or 0)
        sg_perspectives = int(payload.get("sg_perspectives_screenshot_count", 0) or 0)
        detail = f"{expected} expected / {actual} actual / {diff} diff"
        if disabled:
            detail += f" / {disabled} disabled in test_config"
        if sg_perspectives:
            detail += f" / {sg_perspectives} SG prespectivesTests screenshots"
        items.append(
            {
                "source": "bmw_screenshot_state",
                "label": f"Screenshot test state ({label_profile or 'profile'})",
                "status": str(payload.get("status", "")).strip() or "unknown",
                "detail": detail,
                "path": str(payload.get("expected_root", "")).strip(),
                "note": str(payload.get("note", _SCREENSHOT_STATE_NOTE)).strip(),
                "guidance": str(payload.get("guidance", "")).strip()
                or "Suggested screenshot review input only; reviewer verdict required.",
                "is_approval": False,
            }
        )
    return items


def render_bmw_screenshot_state_text(payload: dict[str, Any]) -> str:
    lines = [
        SCREENSHOT_STATE_BANNER,
        f"Profile: {payload.get('profile_id', '')} ({payload.get('brand', 'BMW')} {payload.get('matched_profile_id', '')})",
        f"Status: {payload.get('status', '')}",
        f"Counts: {payload.get('expected_count', 0)} expected / {payload.get('actual_count', 0)} actual / {payload.get('diff_count', 0)} diff",
        (
            "SG prespectivesTests: "
            f"{payload.get('sg_perspectives_screenshot_count', 0)} screenshot / "
            f"{payload.get('sg_perspectives_comparison_count', 0)} comparison"
        ),
        f"Disabled tests in config: {payload.get('disabled_test_count', 0)}",
        f"Expected root: {payload.get('expected_root', '') or 'not found'}",
        f"Actuals root: {payload.get('actuals_root', '') or 'not found'}",
        f"Diff root: {payload.get('diff_root', '') or 'not found'}",
        f"SG prespectivesTests root: {payload.get('sg_perspectives_latest_folder', '') or 'not found'}",
        str(payload.get("note", _SCREENSHOT_STATE_NOTE)),
    ]
    return "\n".join(lines)


def render_bmw_screenshot_state_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# Screenshot Test State - {payload.get('profile_id', '') or 'profile'}",
        "",
        f"> {SCREENSHOT_STATE_BANNER}",
        "",
        f"- Matched brand/profile: `{payload.get('brand', 'BMW')} {payload.get('matched_profile_id', '')}`",
        f"- Status: `{payload.get('status', '')}`",
        f"- Expected baselines: `{payload.get('expected_count', 0)}`",
        f"- Actual screenshots: `{payload.get('actual_count', 0)}`",
        f"- Diff screenshots: `{payload.get('diff_count', 0)}`",
        f"- SG prespectivesTests screenshots: `{payload.get('sg_perspectives_screenshot_count', 0)}`",
        f"- SG prespectivesTests comparisons: `{payload.get('sg_perspectives_comparison_count', 0)}`",
        f"- Disabled tests in config: `{payload.get('disabled_test_count', 0)}`",
        f"- Expected root: `{payload.get('expected_root', '') or 'not found'}`",
        f"- Actuals root: `{payload.get('actuals_root', '') or 'not found'}`",
        f"- Diff root: `{payload.get('diff_root', '') or 'not found'}`",
        f"- SG prespectivesTests root: `{payload.get('sg_perspectives_latest_folder', '') or 'not found'}`",
        "",
        f"> {payload.get('note', _SCREENSHOT_STATE_NOTE)}",
        f"> {payload.get('guidance', 'Suggested screenshot review input only; reviewer verdict required.')}",
    ]
    return "\n".join(lines).rstrip() + "\n"
