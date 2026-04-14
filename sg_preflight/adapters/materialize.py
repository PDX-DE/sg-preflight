from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sg_preflight.adapters.common import find_matches
from sg_preflight.adapters.anchors import normalize_scene_hierarchy_source
from sg_preflight.adapters.carpaints import normalize_carpaints_source
from sg_preflight.adapters.common import write_json
from sg_preflight.adapters.constants import normalize_constants_source
from sg_preflight.adapters.project_sanity import build_project_manifest


@dataclass
class MaterializeResult:
    output_bundle: Path
    written_files: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _infer_project_metadata(project_root: Path) -> dict[str, str]:
    parts = list(project_root.resolve().parts)
    for marker in ("Cars", "Cars_IDCevo"):
        if marker in parts:
            index = parts.index(marker)
            if index + 2 < len(parts):
                return {
                    "generation": marker,
                    "brand": parts[index + 1],
                    "car_model": parts[index + 2],
                }
    return {}


def _auto_discover_scene_source(project_root: Path) -> Path | None:
    matches = find_matches(
        project_root,
        [
            "resources/*AnchorPoints/*.rca",
            "resources/*AnchorPoints*.rca",
            "*AnchorPoints/*.rca",
            "*AnchorPoints*.rca",
            "*anchor*.json",
            "*scene*.json",
        ],
        limit=1,
    )
    return matches[0] if matches else None


def _auto_discover_constants_expected(project_root: Path) -> Path | None:
    matches = find_matches(
        project_root,
        [
            "_Workfiles/json/*_Pivot_Master.json",
            "_WorkFiles/json/*_Pivot_Master.json",
            "*_Pivot_Master.json",
        ],
        limit=1,
    )
    return matches[0] if matches else None


def _auto_discover_constants_exported(project_root: Path) -> Path | None:
    for pattern in (
        "_Common/constants/scripts/Module_constants_*.lua",
        "_Common/constants/scripts/Config_CarModel.lua",
        "export/scripts/Config_CarModel.lua",
        "main/scripts/Logic_Suspension.lua",
    ):
        matches = find_matches(project_root, [pattern], limit=1)
        if matches:
            return matches[0]
    return None


def _auto_discover_carpaints_source(repo_root: Path, project_root: Path | None) -> Path | None:
    metadata = _infer_project_metadata(project_root) if project_root else {}
    brand = metadata.get("brand")

    candidate_paths: list[Path] = []
    if brand:
        candidate_paths.append(repo_root / "Cars" / brand / "CarPaint.json")
    candidate_paths.extend(find_matches(repo_root, ["*CarPaint.json"], limit=5))

    seen: set[str] = set()
    for path in candidate_paths:
        resolved = str(path.resolve()) if path.exists() else str(path)
        if resolved in seen:
            continue
        seen.add(resolved)
        if path.exists():
            return path
    return None


def materialize_bundle(
    *,
    output_bundle: Path,
    repo_root: Path | None = None,
    project_root: Path | None = None,
    scene_source: Path | None = None,
    constants_expected_source: Path | None = None,
    constants_exported_source: Path | None = None,
    carpaints_source: Path | None = None,
    carpaints_helper: Path | None = None,
    env: dict[str, str] | None = None,
    report_context: dict[str, str] | None = None,
    raco_version: str | None = None,
    gltf_name: str | None = None,
    gltf_previous: Path | None = None,
    gltf_current: Path | None = None,
) -> MaterializeResult:
    result = MaterializeResult(output_bundle=output_bundle.resolve())
    output_bundle.mkdir(parents=True, exist_ok=True)

    if project_root is not None:
        project_root = project_root.resolve()
    if repo_root is not None:
        repo_root = repo_root.resolve()

    if scene_source is None and project_root is not None:
        scene_source = _auto_discover_scene_source(project_root)
        if scene_source is not None:
            result.notes.append(
                f"Auto-discovered scene source from project_root: {scene_source.resolve()}"
            )

    if constants_expected_source is None and project_root is not None:
        constants_expected_source = _auto_discover_constants_expected(project_root)
        if constants_expected_source is not None:
            result.notes.append(
                "Auto-discovered expected constants source from project_root: "
                f"{constants_expected_source.resolve()}"
            )

    if constants_exported_source is None and project_root is not None:
        constants_exported_source = _auto_discover_constants_exported(project_root)
        if constants_exported_source is not None:
            result.notes.append(
                "Auto-discovered exported constants source from project_root: "
                f"{constants_exported_source.resolve()}"
            )

    if carpaints_source is None and repo_root is not None:
        carpaints_source = _auto_discover_carpaints_source(repo_root, project_root)
        if carpaints_source is not None:
            result.notes.append(
                f"Auto-discovered carpaint source from repo_root: {carpaints_source.resolve()}"
            )

    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "sources": {},
        "notes": result.notes,
    }

    if scene_source is not None:
        target = output_bundle / "scene_hierarchy.json"
        write_json(target, normalize_scene_hierarchy_source(scene_source))
        result.written_files.append(target.resolve())
        metadata["sources"]["scene_hierarchy"] = str(scene_source.resolve())
    else:
        result.notes.append("scene_hierarchy.json was not materialized; anchors stays unavailable")

    if constants_expected_source is not None:
        target = output_bundle / "constants_expected.json"
        write_json(target, normalize_constants_source(constants_expected_source))
        result.written_files.append(target.resolve())
        metadata["sources"]["constants_expected"] = str(constants_expected_source.resolve())
    else:
        result.notes.append(
            "constants_expected.json was not materialized; constants pack will fail if run"
        )

    if constants_exported_source is not None:
        target = output_bundle / "constants_exported.json"
        write_json(target, normalize_constants_source(constants_exported_source))
        result.written_files.append(target.resolve())
        metadata["sources"]["constants_exported"] = str(constants_exported_source.resolve())
    else:
        result.notes.append(
            "constants_exported.json was not materialized; constants pack will fail if run"
        )

    if carpaints_source is not None:
        target = output_bundle / "carpaints.json"
        payload, note = normalize_carpaints_source(
            carpaints_source,
            helper_path=carpaints_helper,
        )
        write_json(target, payload)
        result.written_files.append(target.resolve())
        metadata["sources"]["carpaints"] = str(carpaints_source.resolve())
        if carpaints_helper is not None:
            metadata["sources"]["carpaints_helper"] = str(carpaints_helper.resolve())
        if note:
            result.notes.append(note)
    else:
        result.notes.append("carpaints.json was not materialized; carpaints pack stays unavailable")

    manifest_root = repo_root or project_root
    manifest_project = project_root or repo_root
    if manifest_root is not None and manifest_project is not None:
        target = output_bundle / "project_manifest.json"
        manifest = build_project_manifest(
            repo_root=manifest_root,
            project_root=manifest_project,
            env=env,
            report_context=report_context,
            raco_version=raco_version,
            gltf_name=gltf_name,
            gltf_previous_path=gltf_previous,
            gltf_current_path=gltf_current,
        )
        write_json(target, manifest)
        result.written_files.append(target.resolve())
        metadata["sources"]["project_manifest_root"] = str(manifest_root.resolve())
        metadata["sources"]["project_manifest_project"] = str(manifest_project.resolve())
        if report_context:
            metadata["sources"]["report_context"] = "cli/materialize overrides"
    else:
        result.notes.append(
            "project_manifest.json was not materialized; project_sanity pack stays unavailable"
        )

    metadata_path = output_bundle / "bundle_metadata.json"
    write_json(metadata_path, metadata)
    result.written_files.append(metadata_path.resolve())
    return result
