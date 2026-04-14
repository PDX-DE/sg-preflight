from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

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
