from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sg_preflight.config_loader import load_json


@dataclass
class Bundle:
    root: Path
    scene_hierarchy: dict[str, Any] | None
    constants_expected: dict[str, Any] | None
    constants_exported: dict[str, Any] | None
    carpaints: dict[str, Any] | list[Any] | None
    project_manifest: dict[str, Any] | None
    bundle_metadata: dict[str, Any] | None


def _maybe_load(path: Path) -> Any | None:
    return load_json(path) if path.exists() else None


def load_bundle(root: Path) -> Bundle:
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Bundle directory does not exist: {root}")

    return Bundle(
        root=root,
        scene_hierarchy=_maybe_load(root / "scene_hierarchy.json"),
        constants_expected=_maybe_load(root / "constants_expected.json"),
        constants_exported=_maybe_load(root / "constants_exported.json"),
        carpaints=_maybe_load(root / "carpaints.json"),
        project_manifest=_maybe_load(root / "project_manifest.json"),
        bundle_metadata=_maybe_load(root / "bundle_metadata.json"),
    )
