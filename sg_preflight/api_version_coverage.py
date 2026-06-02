from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any

from sg_preflight.delivery_readiness import build_delivery_readiness_board
from sg_preflight.profiles import resolve_source_repo_root


EVIDENCE_ONLY_BANNER = (
    "API alignment per car is not recorded in the repo; this shows the shared API version "
    "+ cautious impact hints, not a per-car compliance verdict."
)
IMPACT_REVIEW_LABEL = "may reference a renamed or split shared API property - review"

_API_HEADER_RE = re.compile(r"^##\s+API VERSION:\s+\[(?P<version>\d+)\]\s*-\s*(?P<date>.+?)\s*$", re.MULTILINE)
_YAML_MODEL_RE = re.compile(r"^-\s+name:\s*(?P<value>.+?)\s*$")
_YAML_TOP_LEVEL_RE = re.compile(r"^\s{2}(?P<key>[A-Za-z_]+):\s*(?P<value>.*?)\s*$")
_YAML_NESTED_RE = re.compile(r"^\s{4}(?P<key>[A-Za-z_]+):\s*(?P<value>.*?)\s*$")
_RENAMED_RE = re.compile(
    r"Renamed\s+property\s+`(?P<old>[^`]+)`(?P<context>.*?)\bto\s+`(?P<new>[^`]+)`",
    re.IGNORECASE | re.DOTALL,
)
_SPLIT_RE = re.compile(r"Split\s+`(?P<old>[^`]+)`(?P<context>.*?)(?:\n\s*\n|$)", re.IGNORECASE | re.DOTALL)
_TICK_RE = re.compile(r"`([^`]+)`")
_CATALOG_CONFIG_PARTS = ("ci", "scripts", "common", "models_build_config.yaml")
_BMW_CATALOG_ENV_KEYS = (
    "Digital-3D-Car-Repo",
    "SG_BMW_CAR_MODELS_ROOT",
    "SG_CARMODELS_REPO",
    "SG-CarModels-Repo",
)
_BRAND_ALIASES = {
    "rr": "rollsroyce",
    "rollsroyce": "rollsroyce",
    "rolls_royce": "rollsroyce",
    "mgmbh": "mgmbh",
    "m": "mgmbh",
}
_IDCEVO_SHARED_BRANDS = ("BMW", "Alpina", "MGmbH", "RollsRoyce")
_TEXT_SUFFIXES = {
    ".lua",
    ".rca",
    ".rlogic",
    ".md",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
}


@dataclass(frozen=True)
class ApiImpactChange:
    api_version: str
    api_date: str
    change_type: str
    old_name: str
    new_name: str
    source_line: str
    brands: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_version": self.api_version,
            "api_date": self.api_date,
            "change_type": self.change_type,
            "old_name": self.old_name,
            "new_name": self.new_name,
            "source_line": self.source_line,
            "brands": list(self.brands),
        }


@dataclass(frozen=True)
class ApiChangelogEntry:
    api_version: str
    date: str
    header: str
    summary_lines: tuple[str, ...]
    impact_changes: tuple[ApiImpactChange, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_version": self.api_version,
            "date": self.date,
            "header": self.header,
            "summary_lines": list(self.summary_lines),
            "impact_changes": [change.to_dict() for change in self.impact_changes],
        }


@dataclass(frozen=True)
class SharedApiReference:
    source_root: str
    brand: str
    shared_root: str
    changelog_path: str
    state: str
    current_version: str
    current_date: str
    history: tuple[ApiChangelogEntry, ...]
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_root": self.source_root,
            "brand": self.brand,
            "shared_root": self.shared_root,
            "changelog_path": self.changelog_path,
            "state": self.state,
            "current_version": self.current_version,
            "current_date": self.current_date,
            "history_count": len(self.history),
            "history": [entry.to_dict() for entry in self.history],
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class CatalogModel:
    name: str
    brand: str
    target_type: str
    target: str
    hmi_source_folder: str
    hmi_interface_version: int | None
    additional_build_interface_version: int | None
    line_number: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "brand": self.brand,
            "target_type": self.target_type,
            "target": self.target,
            "hmi_source_folder": self.hmi_source_folder,
            "hmi_interface_version": self.hmi_interface_version,
            "additional_build_interface_version": self.additional_build_interface_version,
            "line_number": self.line_number,
        }


@dataclass(frozen=True)
class InterfaceFamilyEntry:
    source_root: str
    brand: str
    model_id: str
    relative_path: str
    catalog_name: str
    catalog_brand: str
    catalog_type: str
    hmi_interface_version: int | None
    hmi_family_label: str
    additional_build_interface_version: int | None
    match_status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_root": self.source_root,
            "brand": self.brand,
            "model_id": self.model_id,
            "relative_path": self.relative_path,
            "catalog_name": self.catalog_name,
            "catalog_brand": self.catalog_brand,
            "catalog_type": self.catalog_type,
            "hmi_interface_version": self.hmi_interface_version,
            "hmi_family_label": self.hmi_family_label,
            "additional_build_interface_version": self.additional_build_interface_version,
            "match_status": self.match_status,
        }


@dataclass(frozen=True)
class ImpactFileMatch:
    relative_path: str
    line_numbers: tuple[int, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "line_numbers": list(self.line_numbers),
        }


@dataclass(frozen=True)
class ImpactCarMatch:
    source_root: str
    brand: str
    model_id: str
    relative_path: str
    file_matches: tuple[ImpactFileMatch, ...]

    @property
    def file_count(self) -> int:
        return len(self.file_matches)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_root": self.source_root,
            "brand": self.brand,
            "model_id": self.model_id,
            "relative_path": self.relative_path,
            "file_count": self.file_count,
            "file_matches": [match.to_dict() for match in self.file_matches],
        }


@dataclass(frozen=True)
class ImpactScan:
    change: ApiImpactChange
    review_label: str
    matched_cars: tuple[ImpactCarMatch, ...]

    @property
    def matched_car_count(self) -> int:
        return len(self.matched_cars)

    @property
    def matched_file_count(self) -> int:
        return sum(match.file_count for match in self.matched_cars)

    def to_dict(self) -> dict[str, Any]:
        return {
            "change": self.change.to_dict(),
            "review_label": self.review_label,
            "matched_car_count": self.matched_car_count,
            "matched_file_count": self.matched_file_count,
            "matched_cars": [match.to_dict() for match in self.matched_cars],
        }


@dataclass(frozen=True)
class ApiVersionCoverageBoard:
    repo_root: Path
    source_state: str
    generated_at_utc: str
    shared_api_references: tuple[SharedApiReference, ...]
    interface_family_entries: tuple[InterfaceFamilyEntry, ...]
    impact_scans: tuple[ImpactScan, ...]
    catalog_state: str
    catalog_path: str
    catalog_notes: tuple[str, ...] = ()
    manual_review_banner: str = EVIDENCE_ONLY_BANNER

    @property
    def counts(self) -> dict[str, Any]:
        family_counts = Counter(
            str(entry.hmi_interface_version) if entry.hmi_interface_version is not None else "unknown"
            for entry in self.interface_family_entries
        )
        review_cars = {
            (match.source_root, match.brand, match.model_id)
            for scan in self.impact_scans
            for match in scan.matched_cars
        }
        return {
            "shared_brand_total": len(self.shared_api_references),
            "shared_brand_ready": sum(1 for item in self.shared_api_references if item.state == "ready"),
            "current_api_versions": sorted(
                {
                    f"{item.current_version}:{item.current_date}"
                    for item in self.shared_api_references
                    if item.current_version
                }
            ),
            "interface_entry_total": len(self.interface_family_entries),
            "interface_known": sum(1 for entry in self.interface_family_entries if entry.hmi_interface_version is not None),
            "interface_unknown": sum(1 for entry in self.interface_family_entries if entry.hmi_interface_version is None),
            "interface_family_counts": dict(sorted(family_counts.items())),
            "impact_change_count": len(self.impact_scans),
            "impact_review_car_count": len(review_cars),
            "impact_file_match_count": sum(scan.matched_file_count for scan in self.impact_scans),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "repo_root": str(self.repo_root),
            "source_state": self.source_state,
            "generated_at_utc": self.generated_at_utc,
            "manual_review_banner": self.manual_review_banner,
            "impact_review_label": IMPACT_REVIEW_LABEL,
            "catalog_state": self.catalog_state,
            "catalog_path": self.catalog_path,
            "catalog_notes": list(self.catalog_notes),
            "counts": self.counts,
            "shared_api_references": [item.to_dict() for item in self.shared_api_references],
            "interface_family_entries": [entry.to_dict() for entry in self.interface_family_entries],
            "impact_scans": [scan.to_dict() for scan in self.impact_scans],
        }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def _clean_yaml_value(value: str) -> str:
    return value.split("#", 1)[0].strip().strip("'\"")


def _parse_int(value: str) -> int | None:
    value = _clean_yaml_value(value)
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _normalize_brand(value: str) -> str:
    key = value.strip().lower().replace(" ", "").replace("-", "_")
    return _BRAND_ALIASES.get(key, key)


def _catalog_config_from_root(path: Path) -> Path:
    return path if path.name.lower() == "models_build_config.yaml" else path.joinpath(*_CATALOG_CONFIG_PARTS)


def _resolve_catalog_config_path(
    *,
    bmw_repo_root: Path | None,
    workspace_root: Path | None,
) -> Path:
    candidates: list[Path] = []
    if bmw_repo_root is not None:
        candidates.append(_catalog_config_from_root(Path(bmw_repo_root).resolve()))
    for key in _BMW_CATALOG_ENV_KEYS:
        raw = os.environ.get(key, "").strip()
        if raw:
            candidates.append(_catalog_config_from_root(Path(raw).expanduser()))
    if workspace_root is not None:
        workspace = Path(workspace_root).resolve()
        candidates.extend(
            _catalog_config_from_root(path)
            for path in (
                workspace / "digital-3d-car-models",
                workspace / "external" / "digital-3d-car-models",
                workspace.parent / "digital-3d-car-models",
            )
        )
    candidates.append(_catalog_config_from_root(Path(r"C:\3D Car git\digital-3d-car-models")))
    candidates.append(_catalog_config_from_root(Path(r"C:\repos\digital-3d-car-models")))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0] if candidates else Path()


def _parse_catalog_models(path: Path) -> tuple[CatalogModel, ...]:
    text = _read_text(path)
    models: list[CatalogModel] = []
    current: dict[str, str | int | None] | None = None
    section = ""

    def emit() -> None:
        nonlocal current
        if current is None:
            return
        name = str(current.get("name", "")).strip()
        if name:
            models.append(
                CatalogModel(
                    name=name,
                    brand=str(current.get("brand", "")).strip(),
                    target_type=str(current.get("type", "")).strip(),
                    target=str(current.get("target", "")).strip(),
                    hmi_source_folder=str(current.get("hmi_source_folder", "")).strip(),
                    hmi_interface_version=current.get("hmi_interface_version") if isinstance(current.get("hmi_interface_version"), int) else None,
                    additional_build_interface_version=(
                        current.get("additional_build_interface_version")
                        if isinstance(current.get("additional_build_interface_version"), int)
                        else None
                    ),
                    line_number=int(current.get("line_number", 0) or 0),
                )
            )
        current = None

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        model_match = _YAML_MODEL_RE.match(raw_line)
        if model_match is not None:
            emit()
            current = {"name": _clean_yaml_value(model_match.group("value")), "line_number": line_number}
            section = ""
            continue
        if current is None:
            continue
        top_match = _YAML_TOP_LEVEL_RE.match(raw_line)
        if top_match is not None:
            key = top_match.group("key")
            value = _clean_yaml_value(top_match.group("value"))
            if value == "":
                section = key
            else:
                current[key] = value
                section = ""
            continue
        nested_match = _YAML_NESTED_RE.match(raw_line)
        if nested_match is None:
            continue
        key = nested_match.group("key")
        value = nested_match.group("value")
        if section == "hmi":
            if key == "source_folder":
                current["hmi_source_folder"] = _clean_yaml_value(value)
            elif key == "interface_version":
                current["hmi_interface_version"] = _parse_int(value)
        elif section == "additional_build" and key == "interface_version":
            current["additional_build_interface_version"] = _parse_int(value)
    emit()
    return tuple(models)


def _load_catalog_models(
    *,
    bmw_repo_root: Path | None,
    workspace_root: Path | None,
) -> tuple[str, str, tuple[CatalogModel, ...], tuple[str, ...]]:
    path = _resolve_catalog_config_path(bmw_repo_root=bmw_repo_root, workspace_root=workspace_root)
    if not path.is_file():
        return "missing", str(path), (), ("BMW models catalog was not found; interface-family rows are marked unknown.",)
    try:
        return "ready", str(path), _parse_catalog_models(path), ()
    except OSError as exc:
        return "error", str(path), (), (f"BMW models catalog could not be read: {exc}",)


def _model_dir_id(model: CatalogModel) -> str:
    if model.target_type.lower() == "retarget":
        return model.name[:-4] if model.name.upper().endswith("_EVO") else model.name
    if model.hmi_source_folder:
        return model.hmi_source_folder
    return model.name[:-4] if model.name.upper().endswith("_EVO") else model.name


def _effective_hmi_version(model: CatalogModel, models_by_name: dict[str, CatalogModel]) -> int | None:
    if model.hmi_interface_version is not None:
        return model.hmi_interface_version
    if model.target and model.target in models_by_name:
        return models_by_name[model.target].hmi_interface_version
    return None


def _effective_source_folder(model: CatalogModel, models_by_name: dict[str, CatalogModel]) -> str:
    if model.hmi_source_folder:
        return model.hmi_source_folder
    if model.target and model.target in models_by_name:
        return models_by_name[model.target].hmi_source_folder
    return ""


def _version_family_labels(catalog_path: str) -> dict[int, str]:
    version_info = Path(catalog_path).parents[3] / "cars" / "version_info.json" if catalog_path else Path()
    try:
        payload = json.loads(version_info.read_text(encoding="utf-8"))
        versions = sorted(int(item) for item in payload.get("supportedVersions", []))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        versions = []
    labels: dict[int, str] = {}
    if versions:
        labels[versions[0]] = "IDC23 HMI export family"
        labels[versions[-1]] = "IDCevo HMI export family"
    labels.setdefault(12, "IDC23 HMI export family")
    labels.setdefault(24, "IDCevo HMI export family")
    return labels


def _shared_changelog_path(repo_root: Path, brand: str) -> Path | None:
    brand_root = repo_root / "Cars_IDCevo" / brand
    if not brand_root.is_dir():
        return None
    for candidate in sorted(brand_root.glob("_Shared*/MainInterfaces/CHANGELOG.md")):
        if candidate.is_file():
            return candidate
    return None


def _summary_lines(body: str, limit: int = 14) -> tuple[str, ...]:
    lines: list[str] = []
    for raw in body.splitlines():
        stripped = raw.strip()
        if not stripped or stripped == "---":
            continue
        if stripped.startswith("*") or stripped.startswith("-"):
            lines.append(stripped)
        if len(lines) >= limit:
            break
    return tuple(lines)


def _line_for_match(body: str, start: int) -> str:
    line_start = body.rfind("\n", 0, start) + 1
    line_end = body.find("\n", start)
    if line_end == -1:
        line_end = len(body)
    return body[line_start:line_end].strip()


def _impact_changes_for_entry(
    *,
    api_version: str,
    api_date: str,
    body: str,
    brand: str,
) -> tuple[ApiImpactChange, ...]:
    changes: list[ApiImpactChange] = []
    for match in _RENAMED_RE.finditer(body):
        changes.append(
            ApiImpactChange(
                api_version=api_version,
                api_date=api_date,
                change_type="renamed",
                old_name=match.group("old").strip(),
                new_name=match.group("new").strip(),
                source_line=_line_for_match(body, match.start()),
                brands=(brand,),
            )
        )
    for match in _SPLIT_RE.finditer(body):
        old_name = match.group("old").strip()
        new_names = tuple(name for name in _TICK_RE.findall(match.group("context")) if name != old_name)
        changes.append(
            ApiImpactChange(
                api_version=api_version,
                api_date=api_date,
                change_type="split",
                old_name=old_name,
                new_name=", ".join(new_names),
                source_line=_line_for_match(body, match.start()),
                brands=(brand,),
            )
        )
    return tuple(changes)


def _parse_shared_reference(repo_root: Path, brand: str) -> SharedApiReference:
    path = _shared_changelog_path(repo_root, brand)
    if path is None:
        return SharedApiReference(
            source_root="Cars_IDCevo",
            brand=brand,
            shared_root="",
            changelog_path="",
            state="missing",
            current_version="",
            current_date="",
            history=(),
            notes=("MainInterfaces CHANGELOG.md was not found.",),
        )
    text = _read_text(path)
    matches = list(_API_HEADER_RE.finditer(text))
    history: list[ApiChangelogEntry] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end() : end]
        api_version = match.group("version").strip()
        api_date = match.group("date").strip()
        history.append(
            ApiChangelogEntry(
                api_version=api_version,
                date=api_date,
                header=match.group(0).strip(),
                summary_lines=_summary_lines(body),
                impact_changes=_impact_changes_for_entry(
                    api_version=api_version,
                    api_date=api_date,
                    body=body,
                    brand=brand,
                ),
            )
        )
    if not history:
        return SharedApiReference(
            source_root="Cars_IDCevo",
            brand=brand,
            shared_root=path.parents[1].name,
            changelog_path=str(path),
            state="unparseable",
            current_version="",
            current_date="",
            history=(),
            notes=("No API VERSION header was parsed from the shared changelog.",),
        )
    return SharedApiReference(
        source_root="Cars_IDCevo",
        brand=brand,
        shared_root=path.parents[1].name,
        changelog_path=str(path),
        state="ready",
        current_version=history[0].api_version,
        current_date=history[0].date,
        history=tuple(history),
    )


def _merge_impact_changes(shared_refs: tuple[SharedApiReference, ...], limit_versions: int) -> tuple[ApiImpactChange, ...]:
    grouped: dict[tuple[str, str, str, str, str], set[str]] = defaultdict(set)
    exemplar: dict[tuple[str, str, str, str, str], ApiImpactChange] = {}
    for ref in shared_refs:
        for entry in ref.history[:limit_versions]:
            for change in entry.impact_changes:
                key = (change.api_version, change.change_type, change.old_name, change.new_name, change.source_line)
                grouped[key].add(ref.brand)
                exemplar[key] = change
    merged: list[ApiImpactChange] = []
    for key, brands in grouped.items():
        change = exemplar[key]
        merged.append(
            ApiImpactChange(
                api_version=change.api_version,
                api_date=change.api_date,
                change_type=change.change_type,
                old_name=change.old_name,
                new_name=change.new_name,
                source_line=change.source_line,
                brands=tuple(sorted(brands)),
            )
        )
    return tuple(sorted(merged, key=lambda item: (-int(item.api_version), item.change_type, item.old_name)))


def _catalog_model_for_entry(
    entry: dict[str, Any],
    models: tuple[CatalogModel, ...],
    models_by_name: dict[str, CatalogModel],
) -> CatalogModel | None:
    catalog_targets = entry.get("catalog_targets", [])
    if isinstance(catalog_targets, list):
        for target in catalog_targets:
            model = models_by_name.get(str(target))
            if model is not None:
                return model
    model_id = str(entry.get("model_id", "")).lower()
    brand = _normalize_brand(str(entry.get("brand", "")))
    candidates = [
        model
        for model in models
        if _normalize_brand(model.brand) == brand
        and (
            _model_dir_id(model).lower() == model_id
            or _effective_source_folder(model, models_by_name).lower() == model_id
            or model.name.lower() == model_id
        )
    ]
    return candidates[0] if len(candidates) == 1 else None


def _build_interface_entries(
    delivery_entries: list[dict[str, Any]],
    models: tuple[CatalogModel, ...],
    catalog_path: str,
) -> tuple[InterfaceFamilyEntry, ...]:
    models_by_name = {model.name: model for model in models}
    labels = _version_family_labels(catalog_path)
    rows: list[InterfaceFamilyEntry] = []
    for entry in delivery_entries:
        model = _catalog_model_for_entry(entry, models, models_by_name)
        version = _effective_hmi_version(model, models_by_name) if model is not None else None
        rows.append(
            InterfaceFamilyEntry(
                source_root=str(entry.get("source_root", "")),
                brand=str(entry.get("brand", "")),
                model_id=str(entry.get("model_id", "")),
                relative_path=str(entry.get("relative_path", "")),
                catalog_name=model.name if model is not None else "",
                catalog_brand=model.brand if model is not None else "",
                catalog_type=model.target_type if model is not None else "",
                hmi_interface_version=version,
                hmi_family_label=labels.get(version, "Unknown HMI export family") if version is not None else "Unknown HMI export family",
                additional_build_interface_version=(
                    model.additional_build_interface_version if model is not None else None
                ),
                match_status="catalog_mapped" if model is not None else "catalog_missing",
            )
        )
    return tuple(sorted(rows, key=lambda item: (item.source_root.lower(), item.brand.lower(), item.model_id.lower())))


def _scan_file_for_token(path: Path, token: str) -> tuple[int, ...]:
    try:
        text = _read_text(path)
    except OSError:
        return ()
    if token not in text:
        return ()
    return tuple(index for index, line in enumerate(text.splitlines(), start=1) if token in line)


def _iter_car_text_files(car_root: Path) -> tuple[Path, ...]:
    files: list[Path] = []
    for path in car_root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        files.append(path)
    return tuple(sorted(files))


def _impact_scans(
    repo_root: Path,
    delivery_entries: list[dict[str, Any]],
    changes: tuple[ApiImpactChange, ...],
) -> tuple[ImpactScan, ...]:
    scans: list[ImpactScan] = []
    idcevo_entries = [entry for entry in delivery_entries if str(entry.get("source_root", "")) == "Cars_IDCevo"]
    for change in changes:
        if not change.old_name:
            continue
        car_matches: list[ImpactCarMatch] = []
        for entry in idcevo_entries:
            relative = str(entry.get("relative_path", ""))
            car_root = repo_root / relative
            if not car_root.is_dir():
                continue
            file_matches: list[ImpactFileMatch] = []
            for path in _iter_car_text_files(car_root):
                lines = _scan_file_for_token(path, change.old_name)
                if lines:
                    file_matches.append(
                        ImpactFileMatch(
                            relative_path=str(path.relative_to(repo_root)).replace("\\", "/"),
                            line_numbers=lines,
                        )
                    )
            if file_matches:
                car_matches.append(
                    ImpactCarMatch(
                        source_root=str(entry.get("source_root", "")),
                        brand=str(entry.get("brand", "")),
                        model_id=str(entry.get("model_id", "")),
                        relative_path=relative,
                        file_matches=tuple(file_matches),
                    )
                )
        scans.append(
            ImpactScan(
                change=change,
                review_label=IMPACT_REVIEW_LABEL,
                matched_cars=tuple(sorted(car_matches, key=lambda item: (item.brand.lower(), item.model_id.lower()))),
            )
        )
    return tuple(scans)


def build_api_version_coverage_board(
    repo_root: Path | None = None,
    *,
    workspace_root: Path | None = None,
    bmw_repo_root: Path | None = None,
    impact_history_versions: int = 8,
) -> ApiVersionCoverageBoard:
    source_root = Path(repo_root).resolve() if repo_root is not None else resolve_source_repo_root(workspace_root).resolve()
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    catalog_state, catalog_path, models, catalog_notes = _load_catalog_models(
        bmw_repo_root=Path(bmw_repo_root).resolve() if bmw_repo_root is not None else None,
        workspace_root=workspace_root,
    )
    if not source_root.exists():
        return ApiVersionCoverageBoard(
            repo_root=source_root,
            source_state="missing",
            generated_at_utc=generated_at,
            shared_api_references=(),
            interface_family_entries=(),
            impact_scans=(),
            catalog_state=catalog_state,
            catalog_path=catalog_path,
            catalog_notes=catalog_notes,
        )
    shared_refs = tuple(_parse_shared_reference(source_root, brand) for brand in _IDCEVO_SHARED_BRANDS)
    delivery_board = build_delivery_readiness_board(
        source_root,
        workspace_root=workspace_root,
        bmw_repo_root=Path(bmw_repo_root).resolve() if bmw_repo_root is not None else None,
    ).to_dict()
    delivery_entries = [entry for entry in delivery_board.get("entries", []) if isinstance(entry, dict)]
    interface_entries = _build_interface_entries(delivery_entries, models, catalog_path)
    changes = _merge_impact_changes(shared_refs, max(1, int(impact_history_versions)))
    scans = _impact_scans(source_root, delivery_entries, changes)
    return ApiVersionCoverageBoard(
        repo_root=source_root,
        source_state="ready",
        generated_at_utc=generated_at,
        shared_api_references=shared_refs,
        interface_family_entries=interface_entries,
        impact_scans=scans,
        catalog_state=catalog_state,
        catalog_path=catalog_path,
        catalog_notes=catalog_notes,
    )


def api_version_coverage_markdown(board: ApiVersionCoverageBoard) -> str:
    payload = board.to_dict()
    counts = payload["counts"]
    lines = [
        "# API Version Reference",
        "",
        EVIDENCE_ONLY_BANNER,
        "",
        f"- source: `{payload['repo_root']}`",
        f"- generated: `{payload['generated_at_utc']}`",
        f"- shared API brands ready: {counts['shared_brand_ready']}/{counts['shared_brand_total']}",
        f"- HMI export-family rows: {counts['interface_entry_total']}",
        f"- impact changes scanned: {counts['impact_change_count']}",
        f"- cars with cautious impact hints: {counts['impact_review_car_count']}",
        f"- BMW catalog source: `{payload['catalog_path']}` ({payload['catalog_state']})",
        "",
        "## Shared API Versions (Cars_IDCevo MainInterfaces)",
        "",
        "| Brand | Current API | Date | Changelog |",
        "| --- | --- | --- | --- |",
    ]
    for item in board.shared_api_references:
        lines.append(
            f"| {item.brand} | {item.current_version or 'unknown'} | "
            f"{item.current_date or ''} | {item.changelog_path or item.state} |"
        )
    lines.extend(("", "## HMI Export-Family Coverage", "", "| Source | Brand | Model | HMI family | Catalog |", "| --- | --- | --- | --- | --- |"))
    for entry in board.interface_family_entries:
        version = str(entry.hmi_interface_version) if entry.hmi_interface_version is not None else "unknown"
        lines.append(
            f"| {entry.source_root} | {entry.brand} | {entry.model_id} | "
            f"{version} - {entry.hmi_family_label} | {entry.catalog_name or entry.match_status} |"
        )
    lines.extend(("", "## Cautious Impact Hints", ""))
    if not board.impact_scans:
        lines.append("- No rename/split impacts were parsed from the recent shared API history.")
    for scan in board.impact_scans:
        change = scan.change
        target = f" -> {change.new_name}" if change.new_name else ""
        lines.append(
            f"- API {change.api_version} {change.change_type}: `{change.old_name}`{target}; "
            f"{scan.matched_car_count} car(s), {scan.matched_file_count} file(s). {IMPACT_REVIEW_LABEL}."
        )
        for match in scan.matched_cars[:12]:
            lines.append(f"  - {match.brand}/{match.model_id}: {match.file_count} file(s)")
    return "\n".join(lines).rstrip() + "\n"


def write_api_version_coverage_board(board: ApiVersionCoverageBoard, output_root: Path) -> dict[str, str]:
    output_root.mkdir(parents=True, exist_ok=True)
    json_path = output_root / "api-version-coverage.json"
    markdown_path = output_root / "api-version-coverage.md"
    json_path.write_text(json.dumps(board.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    markdown_path.write_text(api_version_coverage_markdown(board), encoding="utf-8")
    return {
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
    }
