from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Iterable

from sg_preflight.io_utils import read_text
from sg_preflight.profiles import resolve_source_repo_root


EVIDENCE_ONLY_BANNER = (
    "Evidence only - perspectives inventory and peer-comparison data is read from local "
    "perspectives_*.json files; manual review remains required."
)

CAR_ROOTS = ("Cars", "Cars_IDCevo")
CORE_CAMERA_FIELDS = ("CraneGimbal", "Frustum", "Viewport")
_REAL_CAR_DIR_NAMES = {"export", "logic", "main", "resources"}
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
class SceneStructuralIssue:
    scene_id: str
    missing_fields: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "missing_fields": list(self.missing_fields),
        }


@dataclass(frozen=True)
class PerspectivesEntry:
    source_root: str
    brand: str
    model_id: str
    relative_path: str
    display_type: str
    perspective_path: str
    scene_count: int
    valid_scene_count: int
    structural_issue_scene_count: int
    scenes: tuple[str, ...]
    scenes_missing_core_fields: tuple[SceneStructuralIssue, ...]
    malformed_json: bool = False
    malformed_detail: str = ""
    missing_common_scenes: tuple[str, ...] = ()
    unique_scenes: tuple[str, ...] = ()
    peer_flags: tuple[str, ...] = ()
    comparison_note: str = ""
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_root": self.source_root,
            "brand": self.brand,
            "model_id": self.model_id,
            "relative_path": self.relative_path,
            "display_type": self.display_type,
            "perspective_path": self.perspective_path,
            "file_present": True,
            "scene_count": self.scene_count,
            "valid_scene_count": self.valid_scene_count,
            "structural_issue_scene_count": self.structural_issue_scene_count,
            "scenes": list(self.scenes),
            "scenes_missing_core_fields": [issue.to_dict() for issue in self.scenes_missing_core_fields],
            "malformed_json": self.malformed_json,
            "malformed_detail": self.malformed_detail,
            "missing_common_scenes": list(self.missing_common_scenes),
            "unique_scenes": list(self.unique_scenes),
            "peer_flags": list(self.peer_flags),
            "comparison_note": self.comparison_note,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class NoPerspectivesEntry:
    source_root: str
    brand: str
    model_id: str
    relative_path: str
    notes: tuple[str, ...] = ("No perspectives_*.json file found for this car directory.",)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_root": self.source_root,
            "brand": self.brand,
            "model_id": self.model_id,
            "relative_path": self.relative_path,
            "file_present": False,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class DisplayTypeGroup:
    display_type: str
    car_count: int
    parseable_car_count: int
    common_scene_threshold: int
    common_scenes: tuple[str, ...]
    comparison_status: str
    comparison_note: str
    scene_presence: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "display_type": self.display_type,
            "car_count": self.car_count,
            "parseable_car_count": self.parseable_car_count,
            "common_scene_threshold": self.common_scene_threshold,
            "common_scenes": list(self.common_scenes),
            "comparison_status": self.comparison_status,
            "comparison_note": self.comparison_note,
            "scene_presence": dict(sorted(self.scene_presence.items())),
        }


@dataclass(frozen=True)
class PerspectivesInventoryBoard:
    repo_root: Path
    source_state: str
    generated_at_utc: str
    entries: tuple[PerspectivesEntry, ...]
    no_perspectives_entries: tuple[NoPerspectivesEntry, ...]
    display_type_groups: dict[str, DisplayTypeGroup]
    manual_review_banner: str = EVIDENCE_ONLY_BANNER

    @property
    def counts(self) -> dict[str, Any]:
        display_type_counts = Counter(entry.display_type for entry in self.entries)
        structural_issue_entries = [
            entry for entry in self.entries if entry.scenes_missing_core_fields
        ]
        return {
            "car_total": len(
                {
                    (entry.source_root, entry.brand, entry.model_id)
                    for entry in self.entries
                }
                | {
                    (entry.source_root, entry.brand, entry.model_id)
                    for entry in self.no_perspectives_entries
                }
            ),
            "file_total": len(self.entries),
            "display_type_group_count": len(self.display_type_groups),
            "compared_display_type_group_count": sum(
                1 for group in self.display_type_groups.values() if group.comparison_status == "compared"
            ),
            "peer_outlier_count": sum(1 for entry in self.entries if entry.peer_flags),
            "malformed_file_count": sum(1 for entry in self.entries if entry.malformed_json),
            "structural_issue_count": len(structural_issue_entries),
            "no_perspectives_count": len(self.no_perspectives_entries),
            "scene_total": sum(entry.scene_count for entry in self.entries),
            "by_display_type": dict(sorted(display_type_counts.items())),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "repo_root": str(self.repo_root),
            "source_state": self.source_state,
            "generated_at_utc": self.generated_at_utc,
            "manual_review_banner": self.manual_review_banner,
            "read_only": True,
            "manual_review_required": True,
            "is_approval": False,
            "counts": self.counts,
            "display_type_groups": {
                display_type: group.to_dict()
                for display_type, group in sorted(self.display_type_groups.items())
            },
            "entries": [entry.to_dict() for entry in self.entries],
            "no_perspectives_entries": [entry.to_dict() for entry in self.no_perspectives_entries],
        }


@dataclass(frozen=True)
class _CarDir:
    source_root: str
    brand: str
    model_id: str
    path: Path


def _relative_path(path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError:
        relative = path
    return str(relative).replace("\\", "/")


def _ignored_dir(path: Path) -> bool:
    name = path.name.strip().lower()
    return name.startswith("_") or name in _IGNORED_DIR_NAMES


def _child_dirs(path: Path) -> tuple[Path, ...]:
    try:
        children = list(path.iterdir())
    except OSError:
        return ()
    return tuple(sorted((child for child in children if child.is_dir()), key=lambda child: child.name.lower()))


def _perspective_files(model_dir: Path) -> tuple[Path, ...]:
    try:
        paths = list(model_dir.glob("perspectives_*.json"))
    except OSError:
        return ()
    return tuple(sorted((path for path in paths if path.is_file()), key=lambda path: path.name.lower()))


def _looks_like_real_car(model_dir: Path) -> bool:
    return all((model_dir / name).is_dir() for name in _REAL_CAR_DIR_NAMES)


def _has_car_marker(model_dir: Path) -> bool:
    return bool(_perspective_files(model_dir)) or (model_dir / "CHANGELOG.md").is_file() or _looks_like_real_car(model_dir)


def _car_dirs(repo_root: Path) -> tuple[_CarDir, ...]:
    cars: list[_CarDir] = []
    for source_root in CAR_ROOTS:
        root = repo_root / source_root
        if not root.is_dir():
            continue
        for brand_dir in _child_dirs(root):
            if _ignored_dir(brand_dir):
                continue
            if _perspective_files(brand_dir):
                cars.append(
                    _CarDir(
                        source_root=source_root,
                        brand=brand_dir.name,
                        model_id=brand_dir.name,
                        path=brand_dir,
                    )
                )
            for model_dir in _child_dirs(brand_dir):
                if _ignored_dir(model_dir):
                    continue
                if _has_car_marker(model_dir):
                    cars.append(
                        _CarDir(
                            source_root=source_root,
                            brand=brand_dir.name,
                            model_id=model_dir.name,
                            path=model_dir,
                        )
                    )
    return tuple(sorted(cars, key=lambda car: (car.source_root, car.brand.lower(), car.model_id.lower())))


def _display_type(path: Path) -> str:
    stem = path.stem
    prefix = "perspectives_"
    if stem.startswith(prefix):
        return stem[len(prefix) :]
    return stem


def _read_perspectives_json(path: Path) -> tuple[dict[str, Any], bool, str]:
    try:
        text = read_text(path)
        parsed = json.loads(text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {}, True, f"Malformed JSON: {exc}"
    if not isinstance(parsed, dict):
        return {}, True, "Malformed JSON: top-level value is not an object."
    return parsed, False, ""


def _entry_from_file(repo_root: Path, car: _CarDir, path: Path) -> PerspectivesEntry:
    parsed, malformed, malformed_detail = _read_perspectives_json(path)
    scene_ids: list[str] = []
    structural_issues: list[SceneStructuralIssue] = []
    notes: list[str] = []
    if malformed:
        notes.append(malformed_detail)
    else:
        for scene_id, scene_payload in sorted(parsed.items(), key=lambda item: str(item[0]).lower()):
            scene_name = str(scene_id)
            scene_ids.append(scene_name)
            if isinstance(scene_payload, dict):
                missing = tuple(field for field in CORE_CAMERA_FIELDS if field not in scene_payload)
            else:
                missing = CORE_CAMERA_FIELDS
            if missing:
                structural_issues.append(SceneStructuralIssue(scene_id=scene_name, missing_fields=missing))
    return PerspectivesEntry(
        source_root=car.source_root,
        brand=car.brand,
        model_id=car.model_id,
        relative_path=_relative_path(car.path, repo_root),
        display_type=_display_type(path),
        perspective_path=_relative_path(path, repo_root),
        scene_count=len(scene_ids),
        valid_scene_count=len(scene_ids) - len(structural_issues),
        structural_issue_scene_count=len(structural_issues),
        scenes=tuple(scene_ids),
        scenes_missing_core_fields=tuple(structural_issues),
        malformed_json=malformed,
        malformed_detail=malformed_detail,
        notes=tuple(notes),
    )


def _no_perspectives_entry(repo_root: Path, car: _CarDir) -> NoPerspectivesEntry:
    return NoPerspectivesEntry(
        source_root=car.source_root,
        brand=car.brand,
        model_id=car.model_id,
        relative_path=_relative_path(car.path, repo_root),
    )


def _group_entries(entries: Iterable[PerspectivesEntry]) -> dict[str, list[PerspectivesEntry]]:
    groups: dict[str, list[PerspectivesEntry]] = {}
    for entry in entries:
        groups.setdefault(entry.display_type, []).append(entry)
    return groups


def _apply_peer_comparison(
    entries: tuple[PerspectivesEntry, ...],
) -> tuple[tuple[PerspectivesEntry, ...], dict[str, DisplayTypeGroup]]:
    groups = _group_entries(entries)
    updated_by_path: dict[str, PerspectivesEntry] = {entry.perspective_path: entry for entry in entries}
    display_groups: dict[str, DisplayTypeGroup] = {}
    for display_type, group_entries in sorted(groups.items()):
        parseable_entries = [entry for entry in group_entries if not entry.malformed_json]
        presence = Counter(
            scene
            for entry in parseable_entries
            for scene in set(entry.scenes)
        )
        parseable_count = len(parseable_entries)
        if parseable_count < 3:
            note = f"too few peers to compare ({parseable_count})"
            display_groups[display_type] = DisplayTypeGroup(
                display_type=display_type,
                car_count=len(group_entries),
                parseable_car_count=parseable_count,
                common_scene_threshold=0,
                common_scenes=(),
                comparison_status="too_few_peers",
                comparison_note=note,
                scene_presence=dict(presence),
            )
            for entry in group_entries:
                if entry.malformed_json:
                    entry_note = "malformed JSON; peer comparison skipped"
                else:
                    entry_note = note
                updated_by_path[entry.perspective_path] = replace(entry, comparison_note=entry_note)
            continue

        threshold = math.ceil(parseable_count * 0.6)
        common_scenes = tuple(sorted(scene for scene, count in presence.items() if count >= threshold))
        display_groups[display_type] = DisplayTypeGroup(
            display_type=display_type,
            car_count=len(group_entries),
            parseable_car_count=parseable_count,
            common_scene_threshold=threshold,
            common_scenes=common_scenes,
            comparison_status="compared",
            comparison_note=f"compared against {parseable_count} {display_type} cars",
            scene_presence=dict(presence),
        )
        for entry in group_entries:
            if entry.malformed_json:
                updated_by_path[entry.perspective_path] = replace(
                    entry,
                    comparison_note="malformed JSON; peer comparison skipped",
                )
                continue
            scene_set = set(entry.scenes)
            missing_common = tuple(scene for scene in common_scenes if scene not in scene_set)
            unique_scenes = tuple(sorted(scene for scene in scene_set if presence.get(scene, 0) == 1))
            flags = tuple(
                [f"{scene} (present in {presence[scene]}/{parseable_count} {display_type} cars)" for scene in missing_common]
                + [f"{scene} unique to this car among {display_type} peers" for scene in unique_scenes]
            )
            updated_by_path[entry.perspective_path] = replace(
                entry,
                missing_common_scenes=missing_common,
                unique_scenes=unique_scenes,
                peer_flags=flags,
                comparison_note=f"compared against {parseable_count} {display_type} cars",
            )
    updated = tuple(updated_by_path[entry.perspective_path] for entry in entries)
    return updated, display_groups


def _now_iso(now: datetime | None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def build_perspectives_inventory_board(
    repo_root: Path | str | None = None,
    *,
    workspace_root: Path | str | None = None,
    now: datetime | None = None,
) -> PerspectivesInventoryBoard:
    workspace = Path(workspace_root).resolve() if workspace_root is not None else None
    source_root = Path(repo_root).resolve() if repo_root is not None else resolve_source_repo_root(workspace)
    generated_at = _now_iso(now)
    if not source_root.exists():
        return PerspectivesInventoryBoard(
            repo_root=source_root,
            source_state="missing",
            generated_at_utc=generated_at,
            entries=(),
            no_perspectives_entries=(),
            display_type_groups={},
        )
    entries: list[PerspectivesEntry] = []
    no_perspectives: list[NoPerspectivesEntry] = []
    for car in _car_dirs(source_root):
        files = _perspective_files(car.path)
        if not files:
            no_perspectives.append(_no_perspectives_entry(source_root, car))
            continue
        entries.extend(_entry_from_file(source_root, car, path) for path in files)
    compared_entries, display_groups = _apply_peer_comparison(
        tuple(sorted(entries, key=lambda entry: (entry.display_type, entry.relative_path.lower(), entry.perspective_path.lower())))
    )
    return PerspectivesInventoryBoard(
        repo_root=source_root,
        source_state="ready",
        generated_at_utc=generated_at,
        entries=compared_entries,
        no_perspectives_entries=tuple(
            sorted(no_perspectives, key=lambda entry: (entry.source_root, entry.brand.lower(), entry.model_id.lower()))
        ),
        display_type_groups=display_groups,
    )


def _markdown_cell(value: object) -> str:
    return str(value or "").replace("|", "\\|")


def perspectives_inventory_markdown(board: PerspectivesInventoryBoard) -> str:
    payload = board.to_dict()
    counts = payload["counts"]
    lines = [
        "# Perspectives Inventory & Consistency Board",
        "",
        str(payload["manual_review_banner"]),
        "",
        f"- source: `{payload['repo_root']}`",
        f"- generated: `{payload['generated_at_utc']}`",
        f"- cars: {counts['car_total']}",
        f"- perspective files: {counts['file_total']}",
        f"- display-type groups: {counts['display_type_group_count']}",
        f"- peer outlier rows: {counts['peer_outlier_count']}",
        f"- malformed files: {counts['malformed_file_count']}",
        f"- structural issue rows: {counts['structural_issue_count']}",
        "",
        "## Display-Type Groups",
        "",
    ]
    groups = payload["display_type_groups"]
    if isinstance(groups, dict) and groups:
        for display_type, group in groups.items():
            if not isinstance(group, dict):
                continue
            common = ", ".join(str(scene) for scene in group.get("common_scenes", [])) or "none"
            lines.append(
                f"- {display_type}: {group.get('comparison_note', '')}; common scenes: {common}"
            )
    else:
        lines.append("- none")
    lines.extend(
        (
            "",
            "| Source | Brand | Model | Display type | Scenes | Structural issues | Peer evidence | Path |",
            "| --- | --- | --- | --- | ---: | --- | --- | --- |",
        )
    )
    for entry in board.entries:
        structural = "; ".join(
            f"{issue.scene_id} missing {', '.join(issue.missing_fields)}"
            for issue in entry.scenes_missing_core_fields
        )
        peer = "; ".join(entry.peer_flags) or entry.comparison_note
        lines.append(
            "| "
            + " | ".join(
                (
                    _markdown_cell(entry.source_root),
                    _markdown_cell(entry.brand),
                    _markdown_cell(entry.model_id),
                    _markdown_cell(entry.display_type),
                    str(entry.scene_count),
                    _markdown_cell(structural),
                    _markdown_cell(peer),
                    _markdown_cell(entry.relative_path),
                )
            )
            + " |"
        )
    if board.no_perspectives_entries:
        lines.extend(("", "## Cars With No Perspectives Files", ""))
        for entry in board.no_perspectives_entries:
            lines.append(f"- {entry.relative_path}")
    return "\n".join(lines).rstrip() + "\n"


def write_perspectives_inventory_board(
    board: PerspectivesInventoryBoard,
    output_root: Path,
) -> dict[str, str]:
    output_root.mkdir(parents=True, exist_ok=True)
    json_path = output_root / "perspectives-inventory.json"
    markdown_path = output_root / "perspectives-inventory.md"
    json_path.write_text(json.dumps(board.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    markdown_path.write_text(perspectives_inventory_markdown(board), encoding="utf-8")
    return {
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
    }
