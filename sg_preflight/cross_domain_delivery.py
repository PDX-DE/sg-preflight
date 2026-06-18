from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Iterable

from sg_preflight.delivery_readiness import (
    STATUS_DELIVERED,
    STATUS_NOT_DELIVERED_YET,
    STATUS_UNKNOWN,
    ChangelogClassification,
    classify_changelog_text,
)
from sg_preflight.io_utils import read_text
from sg_preflight.profiles import resolve_source_repo_root


EVIDENCE_ONLY_BANNER = (
    "Evidence only - cross-domain delivery and version data is read from local CHANGELOG, README, "
    "and RCA files; manual review remains required."
)

_HEADER_RE = re.compile(r"^##\s+\[[^\]]+\].*$", re.MULTILINE)
_METADATA_RE = re.compile(r"^>\s*_(?P<label>[^:]+):\s*(?P<value>.*?)_\s*$", re.IGNORECASE | re.MULTILINE)
_INTERFACES_HEADING_RE = re.compile(r"^##\s+Interfaces Overview\s*$", re.IGNORECASE)
_NEXT_HEADING_RE = re.compile(r"^##\s+")
_VERSION_NUMBER_RE = re.compile(r"\d+")
_IGNORED_DIR_NAMES = {
    "maininterfaces",
    "camera_crane",
    "cameracrane",
    "shared-component",
    "shared-components",
    "shared_component",
    "shared_components",
}


@dataclass(frozen=True)
class DomainSpec:
    domain_id: str
    label: str
    root_dirs: tuple[str, ...]
    brand_level: bool
    changelog_relative: Path
    rca_glob: str
    readme_relative: Path


DOMAIN_SPECS: dict[str, DomainSpec] = {
    "cars": DomainSpec(
        domain_id="cars",
        label="Cars",
        root_dirs=("Cars", "Cars_IDCevo"),
        brand_level=True,
        changelog_relative=Path("CHANGELOG.md"),
        rca_glob="export/Export_{item_id}.rca",
        readme_relative=Path("README.md"),
    ),
    "widgets": DomainSpec(
        domain_id="widgets",
        label="Widgets",
        root_dirs=("Widgets", "Widgets_IDCevo"),
        brand_level=True,
        changelog_relative=Path("Main") / "CHANGELOG.md",
        rca_glob="Main/{item_id}.rca",
        readme_relative=Path("Main") / "README.md",
    ),
    "ambient": DomainSpec(
        domain_id="ambient",
        label="Ambient",
        root_dirs=("AmbientLayer",),
        brand_level=False,
        changelog_relative=Path("CHANGELOG.md"),
        rca_glob="export_*/*.rca",
        readme_relative=Path("README.md"),
    ),
}


@dataclass(frozen=True)
class CrossDomainItem:
    domain: str
    brand: str
    item_id: str
    relative_path: str
    version: str
    delivered_date: str
    delivery_status: str
    delivery_status_label: str
    changelog_header: str
    changelog_path: str
    has_changelog: bool
    ramses: str | None
    raco_headless: str | None
    ramses_logic: str | None
    feature_level: str | None
    api_version: str | None
    rca_paths: tuple[str, ...]
    rca_total_bytes: int
    interfaces_summary: str | None
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "brand": self.brand,
            "item_id": self.item_id,
            "relative_path": self.relative_path,
            "version": self.version,
            "delivered_date": self.delivered_date,
            "delivery_status": self.delivery_status,
            "delivery_status_label": self.delivery_status_label,
            "changelog_header": self.changelog_header,
            "changelog_path": self.changelog_path,
            "has_changelog": self.has_changelog,
            "ramses": self.ramses,
            "raco_headless": self.raco_headless,
            "ramses_logic": self.ramses_logic,
            "feature_level": self.feature_level,
            "api_version": self.api_version,
            "rca_paths": list(self.rca_paths),
            "rca_total_bytes": self.rca_total_bytes,
            "interfaces_summary": self.interfaces_summary,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class CrossDomainDeliveryBoard:
    repo_root: Path
    source_state: str
    generated_at_utc: str
    domains: tuple[str, ...]
    entries: tuple[CrossDomainItem, ...]
    manual_review_banner: str = EVIDENCE_ONLY_BANNER

    @property
    def counts(self) -> dict[str, Any]:
        status_counts = Counter(entry.delivery_status for entry in self.entries)
        by_domain: dict[str, dict[str, int]] = {}
        for domain in self.domains:
            domain_entries = [entry for entry in self.entries if entry.domain == domain]
            domain_status_counts = Counter(entry.delivery_status for entry in domain_entries)
            by_domain[domain] = {
                "total": len(domain_entries),
                STATUS_DELIVERED: domain_status_counts.get(STATUS_DELIVERED, 0),
                STATUS_NOT_DELIVERED_YET: domain_status_counts.get(STATUS_NOT_DELIVERED_YET, 0),
                STATUS_UNKNOWN: domain_status_counts.get(STATUS_UNKNOWN, 0),
                "no_changelog": sum(1 for entry in domain_entries if not entry.has_changelog),
            }
        return {
            "total": len(self.entries),
            STATUS_DELIVERED: status_counts.get(STATUS_DELIVERED, 0),
            STATUS_NOT_DELIVERED_YET: status_counts.get(STATUS_NOT_DELIVERED_YET, 0),
            STATUS_UNKNOWN: status_counts.get(STATUS_UNKNOWN, 0),
            "no_changelog": sum(1 for entry in self.entries if not entry.has_changelog),
            "by_domain": by_domain,
            "rca_total_bytes": sum(entry.rca_total_bytes for entry in self.entries),
            "version_drift": _version_drift_summary(self.entries),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "repo_root": str(self.repo_root),
            "source_state": self.source_state,
            "generated_at_utc": self.generated_at_utc,
            "domains": list(self.domains),
            "manual_review_banner": self.manual_review_banner,
            "read_only": True,
            "manual_review_required": True,
            "is_approval": False,
            "counts": self.counts,
            "entries": [entry.to_dict() for entry in self.entries],
        }


def _relative_path(path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError:
        relative = path
    return str(relative).replace("\\", "/")


def _ignored_dir(path: Path) -> bool:
    name = path.name.strip().lower()
    return name.startswith("_") or name in _IGNORED_DIR_NAMES


def _latest_changelog_section(text: str) -> str:
    match = _HEADER_RE.search(text)
    if match is None:
        return text
    next_match = _HEADER_RE.search(text, match.end())
    return text[match.start() : next_match.start() if next_match is not None else len(text)]


def _parse_version_metadata(changelog_text: str) -> dict[str, str | None]:
    metadata: dict[str, str | None] = {
        "ramses": None,
        "raco_headless": None,
        "ramses_logic": None,
        "feature_level": None,
        "api_version": None,
    }
    section = _latest_changelog_section(changelog_text)
    for match in _METADATA_RE.finditer(section):
        label = re.sub(r"[^a-z0-9]+", " ", match.group("label").strip().casefold()).strip()
        value = match.group("value").strip()
        if label in {"ramses composer headless", "ramses composer", "raco headless", "raco"}:
            metadata["raco_headless"] = value
        elif label == "ramses":
            metadata["ramses"] = value
        elif label == "ramses logic":
            metadata["ramses_logic"] = value
        elif label == "feature level":
            metadata["feature_level"] = value
        elif label == "api version":
            metadata["api_version"] = value
    return metadata


def _interfaces_summary(readme_path: Path) -> str | None:
    if not readme_path.is_file():
        return None
    try:
        lines = read_text(readme_path).splitlines()
    except OSError:
        return None
    in_section = False
    bullet_count = 0
    for line in lines:
        stripped = line.strip()
        if in_section and _NEXT_HEADING_RE.match(stripped):
            break
        if _INTERFACES_HEADING_RE.match(stripped):
            in_section = True
            continue
        if in_section and stripped.startswith(("-", "*")):
            bullet_count += 1
    if not in_section:
        return None
    if bullet_count == 0:
        return "Interfaces Overview present without bullet summary."
    return f"{bullet_count} interface bullet(s) under Interfaces Overview."


def _classification_for_missing_changelog() -> ChangelogClassification:
    return ChangelogClassification(
        status=STATUS_UNKNOWN,
        status_label="No changelog",
        version="",
        delivered_date="",
        header="",
        detail="No CHANGELOG.md was found for this item.",
    )


def _read_changelog(changelog_path: Path) -> tuple[ChangelogClassification, dict[str, str | None], tuple[str, ...]]:
    if not changelog_path.is_file():
        return _classification_for_missing_changelog(), _parse_version_metadata(""), ("No CHANGELOG.md",)
    try:
        text = read_text(changelog_path)
    except OSError as exc:
        return (
            ChangelogClassification(
                status=STATUS_UNKNOWN,
                status_label="Unreadable changelog",
                version="",
                delivered_date="",
                header="",
                detail=f"CHANGELOG.md could not be read: {exc}",
            ),
            _parse_version_metadata(""),
            (f"CHANGELOG.md could not be read: {exc}",),
        )
    return classify_changelog_text(text), _parse_version_metadata(text), ()


def _rca_paths(item_dir: Path, repo_root: Path, spec: DomainSpec, item_id: str) -> tuple[tuple[str, ...], int]:
    pattern = spec.rca_glob.format(item_id=item_id)
    paths = tuple(sorted(path for path in item_dir.glob(pattern) if path.is_file()))
    total = 0
    relative_paths: list[str] = []
    for path in paths:
        relative_paths.append(_relative_path(path, repo_root))
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return tuple(relative_paths), total


def _item_dirs(repo_root: Path, spec: DomainSpec) -> Iterable[tuple[str, Path]]:
    for root_name in spec.root_dirs:
        source_root = repo_root / root_name
        if not source_root.is_dir():
            continue
        if spec.brand_level:
            for brand_dir in sorted((path for path in source_root.iterdir() if path.is_dir()), key=lambda path: path.name.lower()):
                if _ignored_dir(brand_dir):
                    continue
                for item_dir in sorted((path for path in brand_dir.iterdir() if path.is_dir()), key=lambda path: path.name.lower()):
                    if _ignored_dir(item_dir):
                        continue
                    yield brand_dir.name, item_dir
        else:
            for item_dir in sorted((path for path in source_root.iterdir() if path.is_dir()), key=lambda path: path.name.lower()):
                if _ignored_dir(item_dir):
                    continue
                yield "", item_dir


def _entry_from_item(repo_root: Path, spec: DomainSpec, brand: str, item_dir: Path) -> CrossDomainItem:
    changelog_path = item_dir / spec.changelog_relative
    classification, metadata, notes = _read_changelog(changelog_path)
    rca_paths, rca_total = _rca_paths(item_dir, repo_root, spec, item_dir.name)
    return CrossDomainItem(
        domain=spec.domain_id,
        brand=brand,
        item_id=item_dir.name,
        relative_path=_relative_path(item_dir, repo_root),
        version=classification.version,
        delivered_date=classification.delivered_date,
        delivery_status=classification.status,
        delivery_status_label=classification.status_label,
        changelog_header=classification.header,
        changelog_path=_relative_path(changelog_path, repo_root) if changelog_path.is_file() else "",
        has_changelog=changelog_path.is_file(),
        ramses=metadata["ramses"],
        raco_headless=metadata["raco_headless"],
        ramses_logic=metadata["ramses_logic"],
        feature_level=metadata["feature_level"],
        api_version=metadata["api_version"],
        rca_paths=rca_paths,
        rca_total_bytes=rca_total,
        interfaces_summary=_interfaces_summary(item_dir / spec.readme_relative),
        notes=notes,
    )


def _version_key(value: str) -> tuple[int, ...]:
    numbers = tuple(int(match.group(0)) for match in _VERSION_NUMBER_RE.finditer(value))
    return numbers or (0,)


def _max_version(values: Iterable[str | None]) -> str:
    present = [value for value in values if value]
    if not present:
        return ""
    return max(present, key=_version_key)


def _version_drift_summary(entries: tuple[CrossDomainItem, ...]) -> dict[str, Any]:
    max_ramses = _max_version(entry.ramses for entry in entries)
    max_raco = _max_version(entry.raco_headless for entry in entries)
    ramses_drift = [
        entry for entry in entries if max_ramses and entry.ramses and entry.ramses != max_ramses
    ]
    raco_drift = [
        entry for entry in entries if max_raco and entry.raco_headless and entry.raco_headless != max_raco
    ]
    drift_entries = tuple(
        sorted(
            {entry.relative_path: entry for entry in [*ramses_drift, *raco_drift]}.values(),
            key=lambda entry: (entry.domain, entry.relative_path.lower()),
        )
    )
    return {
        "max_ramses": max_ramses,
        "max_raco_headless": max_raco,
        "ramses_drift_count": len(ramses_drift),
        "raco_headless_drift_count": len(raco_drift),
        "items": [
            {
                "domain": entry.domain,
                "relative_path": entry.relative_path,
                "item_id": entry.item_id,
                "ramses": entry.ramses,
                "raco_headless": entry.raco_headless,
            }
            for entry in drift_entries
        ],
    }


def _domain_ids(domains: Iterable[str] | None) -> tuple[str, ...]:
    if domains is None:
        return tuple(DOMAIN_SPECS)
    normalized = tuple(str(domain).strip().casefold() for domain in domains if str(domain).strip())
    unknown = [domain for domain in normalized if domain not in DOMAIN_SPECS]
    if unknown:
        raise ValueError(f"Unknown cross-domain delivery domain(s): {', '.join(unknown)}")
    return normalized


def _now_iso(now: datetime | None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def build_cross_domain_delivery_board(
    repo_root: Path | str | None = None,
    *,
    workspace_root: Path | str | None = None,
    bmw_repo_root: Path | str | None = None,
    domains: Iterable[str] | None = None,
    now: datetime | None = None,
) -> CrossDomainDeliveryBoard:
    _ = bmw_repo_root
    workspace = Path(workspace_root).resolve() if workspace_root is not None else None
    source_root = Path(repo_root).resolve() if repo_root is not None else resolve_source_repo_root(workspace)
    domain_ids = _domain_ids(domains)
    generated_at = _now_iso(now)
    if not source_root.exists():
        return CrossDomainDeliveryBoard(
            repo_root=source_root,
            source_state="missing",
            generated_at_utc=generated_at,
            domains=domain_ids,
            entries=(),
        )
    entries: list[CrossDomainItem] = []
    for domain_id in domain_ids:
        spec = DOMAIN_SPECS[domain_id]
        entries.extend(_entry_from_item(source_root, spec, brand, item_dir) for brand, item_dir in _item_dirs(source_root, spec))
    return CrossDomainDeliveryBoard(
        repo_root=source_root,
        source_state="ready",
        generated_at_utc=generated_at,
        domains=domain_ids,
        entries=tuple(sorted(entries, key=lambda entry: (entry.domain, entry.relative_path.lower()))),
    )


def _markdown_cell(value: object) -> str:
    return str(value or "").replace("|", "\\|")


def cross_domain_delivery_markdown(board: CrossDomainDeliveryBoard) -> str:
    payload = board.to_dict()
    counts = payload["counts"]
    drift = counts["version_drift"]
    lines = [
        "# Cross-Domain Delivery & Version Board",
        "",
        str(payload["manual_review_banner"]),
        "",
        f"- source: `{payload['repo_root']}`",
        f"- generated: `{payload['generated_at_utc']}`",
        f"- total items: {counts['total']}",
        f"- delivered: {counts[STATUS_DELIVERED]}",
        f"- not delivered yet: {counts[STATUS_NOT_DELIVERED_YET]}",
        f"- unknown/no changelog: {counts[STATUS_UNKNOWN]}",
        f"- RCA total bytes: {counts['rca_total_bytes']}",
        "",
        "| Domain | Brand | Item | Status | Version | Ramses | RaCo Headless | RCA bytes | Path |",
        "| --- | --- | --- | --- | --- | --- | --- | ---: | --- |",
    ]
    for entry in board.entries:
        lines.append(
            "| "
            + " | ".join(
                (
                    _markdown_cell(entry.domain),
                    _markdown_cell(entry.brand),
                    _markdown_cell(entry.item_id),
                    _markdown_cell(entry.delivery_status_label),
                    _markdown_cell(entry.version),
                    _markdown_cell(entry.ramses),
                    _markdown_cell(entry.raco_headless),
                    str(entry.rca_total_bytes),
                    _markdown_cell(entry.relative_path),
                )
            )
            + " |"
        )
    lines.extend(
        (
            "",
            "## Version Drift Evidence",
            "",
            f"- Ramses max: {drift['max_ramses'] or 'not found'}",
            f"- RaCo Headless max: {drift['max_raco_headless'] or 'not found'}",
            f"- Ramses drift rows: {drift['ramses_drift_count']}",
            f"- RaCo Headless drift rows: {drift['raco_headless_drift_count']}",
        )
    )
    items = drift.get("items", [])
    if isinstance(items, list) and items:
        lines.append("")
        for item in items:
            if not isinstance(item, dict):
                continue
            lines.append(
                "- "
                f"{item.get('relative_path', '')}: "
                f"Ramses {item.get('ramses') or 'unknown'}, "
                f"RaCo Headless {item.get('raco_headless') or 'unknown'}"
            )
    return "\n".join(lines).rstrip() + "\n"


def write_cross_domain_delivery_board(
    board: CrossDomainDeliveryBoard,
    output_root: Path,
) -> dict[str, str]:
    output_root.mkdir(parents=True, exist_ok=True)
    json_path = output_root / "cross-domain-delivery.json"
    markdown_path = output_root / "cross-domain-delivery.md"
    json_path.write_text(json.dumps(board.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    markdown_path.write_text(cross_domain_delivery_markdown(board), encoding="utf-8")
    return {
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
    }
