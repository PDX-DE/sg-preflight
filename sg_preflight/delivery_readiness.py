from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any

from sg_preflight.profiles import resolve_source_repo_root


STATUS_DELIVERED = "delivered"
STATUS_NOT_DELIVERED_YET = "not_delivered_yet"
STATUS_UNKNOWN = "unknown"

MANUAL_APPROVAL_BANNER = (
    "Evidence only - delivery approval remains manual: SG peer approval, Wombat merge, and BMW CCB."
)

_HEADER_RE = re.compile(r"^##\s+\[(?P<version>[^\]]+)\](?P<rest>.*)$", re.MULTILINE)
_DATE_RE = re.compile(r"\b(?P<date>\d{4}-\d{2}-\d{2}|\d{8})\b")
_PENDING_RE = re.compile(r"deliv|delv|releas", re.IGNORECASE)
_YAML_MODEL_RE = re.compile(r"^-\s+name:\s*(?P<value>.+?)\s*$")
_YAML_TOP_LEVEL_RE = re.compile(r"^\s{2}(?P<key>[A-Za-z_]+):\s*(?P<value>.*?)\s*$")
_YAML_NESTED_RE = re.compile(r"^\s{4}(?P<key>[A-Za-z_]+):\s*(?P<value>.*?)\s*$")
_SHARED_COMPONENT_NAMES = {
    "maininterfaces",
    "camera_crane",
    "cameracrane",
    "shared-component",
    "shared-components",
    "shared_component",
    "shared_components",
}
_REAL_CAR_DIR_NAMES = {"export", "logic", "main", "resources"}
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
}


@dataclass(frozen=True)
class ChangelogClassification:
    status: str
    status_label: str
    version: str
    delivered_date: str
    header: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {
            "status": self.status,
            "status_label": self.status_label,
            "version": self.version,
            "delivered_date": self.delivered_date,
            "header": self.header,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class CatalogTarget:
    name: str
    brand: str
    target_type: str
    source_folder: str
    target: str
    line_number: int

    def to_dict(self) -> dict[str, str | int]:
        return {
            "name": self.name,
            "brand": self.brand,
            "target_type": self.target_type,
            "source_folder": self.source_folder,
            "target": self.target,
            "model_dir_id": _catalog_model_dir_id(self),
            "line_number": self.line_number,
        }


@dataclass(frozen=True)
class CatalogTargetMapping:
    target_name: str
    catalog_brand: str
    target_type: str
    model_dir_id: str
    mapped_relative_paths: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_name": self.target_name,
            "catalog_brand": self.catalog_brand,
            "target_type": self.target_type,
            "model_dir_id": self.model_dir_id,
            "mapped_relative_paths": list(self.mapped_relative_paths),
        }


@dataclass(frozen=True)
class CatalogReconciliation:
    catalog_state: str
    catalog_path: str
    catalog_target_count: int
    catalog_targets_mapped_count: int
    catalog_targets_missing_dir_count: int
    dirs_without_catalog_count: int
    catalog_targets_mapped: tuple[CatalogTargetMapping, ...] = ()
    catalog_targets_missing_dir: tuple[CatalogTargetMapping, ...] = ()
    dirs_without_catalog: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "catalog_state": self.catalog_state,
            "catalog_path": self.catalog_path,
            "catalog_target_count": self.catalog_target_count,
            "catalog_targets_mapped_count": self.catalog_targets_mapped_count,
            "catalog_targets_missing_dir_count": self.catalog_targets_missing_dir_count,
            "dirs_without_catalog_count": self.dirs_without_catalog_count,
            "catalog_targets_mapped": [item.to_dict() for item in self.catalog_targets_mapped],
            "catalog_targets_missing_dir": [item.to_dict() for item in self.catalog_targets_missing_dir],
            "dirs_without_catalog": list(self.dirs_without_catalog),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class DeliveryReadinessEntry:
    source_root: str
    brand: str
    model_id: str
    status: str
    status_label: str
    version: str
    delivered_date: str
    latest_header: str
    changelog_path: str
    model_dir_path: str
    relative_path: str
    has_changelog: bool
    catalog_targets: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_root": self.source_root,
            "brand": self.brand,
            "model_id": self.model_id,
            "status": self.status,
            "status_label": self.status_label,
            "version": self.version,
            "delivered_date": self.delivered_date,
            "latest_header": self.latest_header,
            "changelog_path": self.changelog_path,
            "model_dir_path": self.model_dir_path,
            "relative_path": self.relative_path,
            "has_changelog": self.has_changelog,
            "catalog_targets": list(self.catalog_targets),
        }


@dataclass(frozen=True)
class DeliveryReadinessBoard:
    repo_root: Path
    source_state: str
    generated_at_utc: str
    entries: tuple[DeliveryReadinessEntry, ...]
    skipped_count: int = 0
    catalog: CatalogReconciliation | None = None

    @property
    def counts(self) -> dict[str, int]:
        counts = {
            "total": len(self.entries),
            STATUS_DELIVERED: 0,
            STATUS_NOT_DELIVERED_YET: 0,
            STATUS_UNKNOWN: 0,
        }
        for entry in self.entries:
            counts[entry.status] = counts.get(entry.status, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "repo_root": str(self.repo_root),
            "source_state": self.source_state,
            "generated_at_utc": self.generated_at_utc,
            "manual_approval_banner": MANUAL_APPROVAL_BANNER,
            "counts": dict(self.counts),
            "skipped_count": self.skipped_count,
            "catalog": (
                self.catalog.to_dict()
                if self.catalog is not None
                else CatalogReconciliation(
                    catalog_state="not_checked",
                    catalog_path="",
                    catalog_target_count=0,
                    catalog_targets_mapped_count=0,
                    catalog_targets_missing_dir_count=0,
                    dirs_without_catalog_count=0,
                ).to_dict()
            ),
            "entries": [entry.to_dict() for entry in self.entries],
        }


@dataclass(frozen=True)
class _ModelCandidate:
    source_root: str
    brand: str
    model_id: str
    model_dir: Path
    catalog_targets: tuple[CatalogTarget, ...]


def classify_changelog_text(text: str) -> ChangelogClassification:
    match = _HEADER_RE.search(text)
    if match is None:
        return ChangelogClassification(
            status=STATUS_UNKNOWN,
            status_label="Unknown",
            version="",
            delivered_date="",
            header="",
            detail="No latest version header was found.",
        )

    version = match.group("version").strip()
    rest = match.group("rest").strip()
    header = match.group(0).strip()
    date_match = _DATE_RE.search(rest)
    if date_match is not None:
        return ChangelogClassification(
            status=STATUS_DELIVERED,
            status_label="Delivered",
            version=version,
            delivered_date=date_match.group("date"),
            header=header,
            detail=f"Latest changelog entry has delivery date {date_match.group('date')}.",
        )
    if _PENDING_RE.search(rest):
        return ChangelogClassification(
            status=STATUS_NOT_DELIVERED_YET,
            status_label="Not delivered yet",
            version=version,
            delivered_date="",
            header=header,
            detail="Latest changelog entry is marked as not delivered yet.",
        )
    return ChangelogClassification(
        status=STATUS_UNKNOWN,
        status_label="Unknown",
        version=version,
        delivered_date="",
        header=header,
        detail="Latest changelog entry does not match a known delivery marker.",
    )


def _has_excluded_segment(path: Path) -> bool:
    for part in path.parts:
        normalized = part.strip().lower()
        if normalized.startswith("_") or normalized in _SHARED_COMPONENT_NAMES:
            return True
    return False


def _clean_yaml_value(value: str) -> str:
    return value.split("#", 1)[0].strip().strip("'\"")


def _catalog_model_dir_id(target: CatalogTarget) -> str:
    name = target.name.strip()
    if target.target_type.lower() == "retarget":
        return name[:-4] if name.upper().endswith("_EVO") else name
    if target.source_folder:
        return target.source_folder
    return name[:-4] if name.upper().endswith("_EVO") else name


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
        candidates.append(_catalog_config_from_root(bmw_repo_root.resolve()))
    for key in _BMW_CATALOG_ENV_KEYS:
        raw = os.environ.get(key, "").strip()
        if raw:
            candidates.append(_catalog_config_from_root(Path(raw).expanduser()))
    if workspace_root is not None:
        workspace = workspace_root.resolve()
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


def _parse_catalog_targets(path: Path) -> tuple[CatalogTarget, ...]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="replace")

    targets: list[CatalogTarget] = []
    current: dict[str, str | int] | None = None
    section = ""

    def emit() -> None:
        nonlocal current
        if current is None:
            return
        name = str(current.get("name", "")).strip()
        if not name:
            current = None
            return
        source_folder = str(current.get("parking_source_folder") or current.get("hmi_source_folder") or "").strip()
        targets.append(
            CatalogTarget(
                name=name,
                brand=str(current.get("brand", "")).strip(),
                target_type=str(current.get("type", "")).strip(),
                source_folder=source_folder,
                target=str(current.get("target", "")).strip(),
                line_number=int(current.get("line_number", 0)),
            )
        )
        current = None

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        model_match = _YAML_MODEL_RE.match(raw_line)
        if model_match is not None:
            emit()
            current = {
                "name": _clean_yaml_value(model_match.group("value")),
                "line_number": line_number,
            }
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
        if section in {"hmi", "parking"}:
            nested_match = _YAML_NESTED_RE.match(raw_line)
            if nested_match is not None and nested_match.group("key") == "source_folder":
                current[f"{section}_source_folder"] = _clean_yaml_value(nested_match.group("value"))
    emit()
    return tuple(targets)


def _load_catalog_targets(
    *,
    bmw_repo_root: Path | None,
    workspace_root: Path | None,
) -> tuple[str, str, tuple[CatalogTarget, ...], tuple[str, ...]]:
    path = _resolve_catalog_config_path(bmw_repo_root=bmw_repo_root, workspace_root=workspace_root)
    if not path.is_file():
        note = "BMW models catalog was not found; no-CHANGELOG inclusion uses folder structure only."
        return "missing", str(path) if path else "", (), (note,)
    try:
        targets = _parse_catalog_targets(path)
    except OSError as exc:
        return "error", str(path), (), (f"BMW models catalog could not be read: {exc}",)
    return "ready", str(path), targets, ()


def _catalog_targets_for_model(
    catalog_targets: tuple[CatalogTarget, ...],
    *,
    brand: str,
    model_id: str,
) -> tuple[CatalogTarget, ...]:
    matches = tuple(target for target in catalog_targets if _catalog_model_dir_id(target).lower() == model_id.lower())
    if not matches:
        return ()
    brand_key = _normalize_brand(brand)
    brand_matches = tuple(target for target in matches if _normalize_brand(target.brand) == brand_key)
    return brand_matches or matches


def _looks_like_real_car(model_dir: Path) -> bool:
    return all((model_dir / name).is_dir() for name in _REAL_CAR_DIR_NAMES)


def _child_dirs(path: Path) -> tuple[Path, ...]:
    try:
        children = list(path.iterdir())
    except OSError:
        return ()
    return tuple(sorted((child for child in children if child.is_dir()), key=lambda child: child.name.lower()))


def _candidate_model_dirs(repo_root: Path, catalog_targets: tuple[CatalogTarget, ...]) -> tuple[_ModelCandidate, ...]:
    candidates: list[_ModelCandidate] = []
    for source_name in ("Cars", "Cars_IDCevo"):
        source_root = repo_root / source_name
        if not source_root.is_dir():
            continue
        for brand_dir in _child_dirs(source_root):
            if _has_excluded_segment(brand_dir.relative_to(source_root)):
                continue
            for model_dir in _child_dirs(brand_dir):
                relative_model = model_dir.relative_to(source_root)
                if _has_excluded_segment(relative_model):
                    continue
                changelog_path = model_dir / "CHANGELOG.md"
                target_matches = _catalog_targets_for_model(
                    catalog_targets,
                    brand=brand_dir.name,
                    model_id=model_dir.name,
                )
                if changelog_path.is_file() or _looks_like_real_car(model_dir) or target_matches:
                    candidates.append(
                        _ModelCandidate(
                            source_root=source_name,
                            brand=brand_dir.name,
                            model_id=model_dir.name,
                            model_dir=model_dir,
                            catalog_targets=tuple(sorted(target_matches, key=lambda target: target.name.lower())),
                        )
                    )
    return tuple(candidates)


def _changelogs_under(source_root: Path) -> tuple[Path, ...]:
    try:
        return tuple(path for path in source_root.rglob("CHANGELOG.md") if path.is_file())
    except OSError:
        return ()


def _all_delivery_changelogs(repo_root: Path) -> tuple[Path, ...]:
    changelogs: list[Path] = []
    for source_name in ("Cars", "Cars_IDCevo"):
        source_root = repo_root / source_name
        if source_root.is_dir():
            changelogs.extend(_changelogs_under(source_root))
    return tuple(changelogs)


def _entry_from_model_dir(repo_root: Path, candidate: _ModelCandidate) -> DeliveryReadinessEntry:
    changelog_path = candidate.model_dir / "CHANGELOG.md"
    has_changelog = changelog_path.is_file()
    if has_changelog:
        try:
            text = changelog_path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            text = changelog_path.read_text(encoding="utf-8", errors="replace")
        classification = classify_changelog_text(text)
    else:
        classification = ChangelogClassification(
            status=STATUS_UNKNOWN,
            status_label="No changelog",
            version="",
            delivered_date="",
            header="",
            detail="No CHANGELOG.md was found for this model directory.",
        )
    relative = candidate.model_dir.relative_to(repo_root)
    return DeliveryReadinessEntry(
        source_root=candidate.source_root,
        brand=candidate.brand,
        model_id=candidate.model_id,
        status=classification.status,
        status_label=classification.status_label,
        version=classification.version,
        delivered_date=classification.delivered_date,
        latest_header=classification.header,
        changelog_path=str(changelog_path) if has_changelog else "",
        model_dir_path=str(candidate.model_dir),
        relative_path=str(relative).replace("\\", "/"),
        has_changelog=has_changelog,
        catalog_targets=tuple(target.name for target in candidate.catalog_targets),
    )


def _build_catalog_reconciliation(
    *,
    catalog_state: str,
    catalog_path: str,
    catalog_targets: tuple[CatalogTarget, ...],
    entries: tuple[DeliveryReadinessEntry, ...],
    notes: tuple[str, ...],
) -> CatalogReconciliation:
    entries_by_model: dict[str, list[DeliveryReadinessEntry]] = {}
    for entry in entries:
        entries_by_model.setdefault(entry.model_id.lower(), []).append(entry)

    mapped: list[CatalogTargetMapping] = []
    missing: list[CatalogTargetMapping] = []
    dirs_with_catalog: set[str] = set()
    for target in catalog_targets:
        model_dir_id = _catalog_model_dir_id(target)
        model_entries = entries_by_model.get(model_dir_id.lower(), [])
        brand_key = _normalize_brand(target.brand)
        brand_entries = [entry for entry in model_entries if _normalize_brand(entry.brand) == brand_key]
        matched_entries = brand_entries or model_entries
        relative_paths = tuple(sorted(entry.relative_path for entry in matched_entries))
        mapping = CatalogTargetMapping(
            target_name=target.name,
            catalog_brand=target.brand,
            target_type=target.target_type,
            model_dir_id=model_dir_id,
            mapped_relative_paths=relative_paths,
        )
        if relative_paths:
            mapped.append(mapping)
            dirs_with_catalog.update(relative_paths)
        else:
            missing.append(mapping)

    dirs_without_catalog = tuple(
        sorted(entry.relative_path for entry in entries if entry.relative_path not in dirs_with_catalog)
    )
    return CatalogReconciliation(
        catalog_state=catalog_state,
        catalog_path=catalog_path,
        catalog_target_count=len(catalog_targets),
        catalog_targets_mapped_count=len(mapped),
        catalog_targets_missing_dir_count=len(missing),
        dirs_without_catalog_count=len(dirs_without_catalog),
        catalog_targets_mapped=tuple(mapped),
        catalog_targets_missing_dir=tuple(missing),
        dirs_without_catalog=dirs_without_catalog,
        notes=notes,
    )


def build_delivery_readiness_board(
    repo_root: Path | None = None,
    *,
    workspace_root: Path | None = None,
    bmw_repo_root: Path | None = None,
) -> DeliveryReadinessBoard:
    source_root = (repo_root or resolve_source_repo_root(workspace_root)).resolve()
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    catalog_state, catalog_path, catalog_targets, catalog_notes = _load_catalog_targets(
        bmw_repo_root=bmw_repo_root,
        workspace_root=workspace_root,
    )
    if not source_root.exists():
        return DeliveryReadinessBoard(
            repo_root=source_root,
            source_state="missing",
            generated_at_utc=generated_at,
            entries=(),
            catalog=_build_catalog_reconciliation(
                catalog_state=catalog_state,
                catalog_path=catalog_path,
                catalog_targets=catalog_targets,
                entries=(),
                notes=catalog_notes,
            ),
        )

    all_changelogs = _all_delivery_changelogs(source_root)
    candidates = _candidate_model_dirs(source_root, catalog_targets)
    entries = tuple(
        sorted(
            (_entry_from_model_dir(source_root, candidate) for candidate in candidates),
            key=lambda item: (item.source_root.lower(), item.brand.lower(), item.model_id.lower()),
        )
    )
    included_changelog_count = sum(1 for entry in entries if entry.has_changelog)
    return DeliveryReadinessBoard(
        repo_root=source_root,
        source_state="ready",
        generated_at_utc=generated_at,
        entries=entries,
        skipped_count=max(0, len(all_changelogs) - included_changelog_count),
        catalog=_build_catalog_reconciliation(
            catalog_state=catalog_state,
            catalog_path=catalog_path,
            catalog_targets=catalog_targets,
            entries=entries,
            notes=catalog_notes,
        ),
    )


def delivery_readiness_markdown(board: DeliveryReadinessBoard) -> str:
    payload = board.to_dict()
    counts = payload["counts"]
    catalog = payload["catalog"]
    lines = [
        "# Delivery Readiness",
        "",
        MANUAL_APPROVAL_BANNER,
        "",
        f"- source: `{payload['repo_root']}`",
        f"- generated: `{payload['generated_at_utc']}`",
        f"- total cars: {counts['total']}",
        f"- delivered: {counts[STATUS_DELIVERED]}",
        f"- not delivered yet: {counts[STATUS_NOT_DELIVERED_YET]}",
        f"- unknown: {counts[STATUS_UNKNOWN]}",
        f"- shared or component changelogs skipped: {payload['skipped_count']}",
        f"- BMW catalog source: `{catalog['catalog_path']}` ({catalog['catalog_state']})",
        f"- BMW catalog targets: {catalog['catalog_target_count']}",
        f"- catalog targets mapped to listed dirs: {catalog['catalog_targets_mapped_count']}",
        f"- catalog targets with no listed dir: {catalog['catalog_targets_missing_dir_count']}",
        f"- listed dirs without catalog entry: {catalog['dirs_without_catalog_count']}",
        "",
        "| Source | Brand | Model | Status | Version | Date | Latest header |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for entry in board.entries:
        header = (entry.latest_header or "No CHANGELOG.md found").replace("|", "\\|")
        lines.append(
            "| "
            + " | ".join(
                (
                    entry.source_root,
                    entry.brand,
                    entry.model_id,
                    entry.status_label,
                    entry.version or "",
                    entry.delivered_date or "",
                    header,
                )
            )
            + " |"
        )
    missing_targets = catalog.get("catalog_targets_missing_dir", [])
    if isinstance(missing_targets, list) and missing_targets:
        lines.extend(("", "## Catalog Targets With No Listed Dir", ""))
        for item in missing_targets:
            if not isinstance(item, dict):
                continue
            lines.append(f"- {item.get('target_name', '')}: model dir `{item.get('model_dir_id', '')}`")
    dirs_without_catalog = catalog.get("dirs_without_catalog", [])
    if isinstance(dirs_without_catalog, list) and dirs_without_catalog:
        lines.extend(("", "## Listed Dirs Without Catalog Entry", ""))
        for item in dirs_without_catalog:
            lines.append(f"- `{item}`")
    return "\n".join(lines).rstrip() + "\n"


def write_delivery_readiness_board(
    board: DeliveryReadinessBoard,
    output_root: Path,
) -> dict[str, str]:
    output_root.mkdir(parents=True, exist_ok=True)
    json_path = output_root / "delivery-readiness.json"
    markdown_path = output_root / "delivery-readiness.md"
    json_path.write_text(json.dumps(board.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    markdown_path.write_text(delivery_readiness_markdown(board), encoding="utf-8")
    return {
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
    }
