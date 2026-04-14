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


@dataclass
class MaterializeInputs:
    repo_root: Path | None = None
    project_root: Path | None = None
    scene_source: Path | None = None
    constants_expected_source: Path | None = None
    constants_exported_source: Path | None = None
    carpaints_source: Path | None = None
    carpaints_helper: Path | None = None
    notes: list[str] = field(default_factory=list)

    def source_map(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        if self.scene_source is not None:
            mapping["scene_hierarchy"] = str(self.scene_source.resolve())
        if self.constants_expected_source is not None:
            mapping["constants_expected"] = str(self.constants_expected_source.resolve())
        if self.constants_exported_source is not None:
            mapping["constants_exported"] = str(self.constants_exported_source.resolve())
        if self.carpaints_source is not None:
            mapping["carpaints"] = str(self.carpaints_source.resolve())
        if self.carpaints_helper is not None:
            mapping["carpaints_helper"] = str(self.carpaints_helper.resolve())
        if self.repo_root is not None:
            mapping["project_manifest_root"] = str(self.repo_root.resolve())
        if self.project_root is not None:
            mapping["project_manifest_project"] = str(self.project_root.resolve())
        return mapping


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


def resolve_materialize_inputs(
    *,
    repo_root: Path | None = None,
    project_root: Path | None = None,
    scene_source: Path | None = None,
    constants_expected_source: Path | None = None,
    constants_exported_source: Path | None = None,
    carpaints_source: Path | None = None,
    carpaints_helper: Path | None = None,
) -> MaterializeInputs:
    resolved = MaterializeInputs(
        repo_root=repo_root.resolve() if repo_root is not None else None,
        project_root=project_root.resolve() if project_root is not None else None,
        scene_source=scene_source.resolve() if scene_source is not None else None,
        constants_expected_source=(
            constants_expected_source.resolve() if constants_expected_source is not None else None
        ),
        constants_exported_source=(
            constants_exported_source.resolve() if constants_exported_source is not None else None
        ),
        carpaints_source=carpaints_source.resolve() if carpaints_source is not None else None,
        carpaints_helper=carpaints_helper.resolve() if carpaints_helper is not None else None,
    )

    if resolved.scene_source is None and resolved.project_root is not None:
        resolved.scene_source = _auto_discover_scene_source(resolved.project_root)
        if resolved.scene_source is not None:
            resolved.notes.append(
                f"Auto-discovered scene source from project_root: {resolved.scene_source.resolve()}"
            )

    if resolved.constants_expected_source is None and resolved.project_root is not None:
        resolved.constants_expected_source = _auto_discover_constants_expected(resolved.project_root)
        if resolved.constants_expected_source is not None:
            resolved.notes.append(
                "Auto-discovered expected constants source from project_root: "
                f"{resolved.constants_expected_source.resolve()}"
            )

    if resolved.constants_exported_source is None and resolved.project_root is not None:
        resolved.constants_exported_source = _auto_discover_constants_exported(resolved.project_root)
        if resolved.constants_exported_source is not None:
            resolved.notes.append(
                "Auto-discovered exported constants source from project_root: "
                f"{resolved.constants_exported_source.resolve()}"
            )

    if resolved.carpaints_source is None and resolved.repo_root is not None:
        resolved.carpaints_source = _auto_discover_carpaints_source(
            resolved.repo_root,
            resolved.project_root,
        )
        if resolved.carpaints_source is not None:
            resolved.notes.append(
                f"Auto-discovered carpaint source from repo_root: {resolved.carpaints_source.resolve()}"
            )

    return resolved


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
    inputs = resolve_materialize_inputs(
        repo_root=repo_root,
        project_root=project_root,
        scene_source=scene_source,
        constants_expected_source=constants_expected_source,
        constants_exported_source=constants_exported_source,
        carpaints_source=carpaints_source,
        carpaints_helper=carpaints_helper,
    )
    result.notes.extend(inputs.notes)

    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "sources": inputs.source_map(),
        "notes": result.notes,
    }

    if inputs.scene_source is not None:
        target = output_bundle / "scene_hierarchy.json"
        write_json(target, normalize_scene_hierarchy_source(inputs.scene_source))
        result.written_files.append(target.resolve())
    else:
        result.notes.append("scene_hierarchy.json was not materialized; anchors stays unavailable")

    if inputs.constants_expected_source is not None:
        target = output_bundle / "constants_expected.json"
        write_json(target, normalize_constants_source(inputs.constants_expected_source))
        result.written_files.append(target.resolve())
    else:
        result.notes.append(
            "constants_expected.json was not materialized; constants pack will fail if run"
        )

    if inputs.constants_exported_source is not None:
        target = output_bundle / "constants_exported.json"
        write_json(target, normalize_constants_source(inputs.constants_exported_source))
        result.written_files.append(target.resolve())
    else:
        result.notes.append(
            "constants_exported.json was not materialized; constants pack will fail if run"
        )

    if inputs.carpaints_source is not None:
        target = output_bundle / "carpaints.json"
        payload, note = normalize_carpaints_source(
            inputs.carpaints_source,
            helper_path=inputs.carpaints_helper,
        )
        write_json(target, payload)
        result.written_files.append(target.resolve())
        if note:
            result.notes.append(note)
    else:
        result.notes.append("carpaints.json was not materialized; carpaints pack stays unavailable")

    manifest_root = inputs.repo_root or inputs.project_root
    manifest_project = inputs.project_root or inputs.repo_root
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
