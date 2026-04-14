from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from sg_preflight.adapters.common import find_matches, load_json


def _normalize_node(node: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {
        "name": str(node.get("name", node.get("id", "<unnamed>"))),
    }

    metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
    if "bbox_position" in node and "bbox_position" not in metadata:
        metadata = dict(metadata)
        metadata["bbox_position"] = node["bbox_position"]
    if metadata:
        normalized["metadata"] = metadata

    children = node.get("children", [])
    if isinstance(children, list):
        normalized["children"] = [
            _normalize_node(child) for child in children if isinstance(child, dict)
        ]
    return normalized


def _build_tree_from_nodes(nodes: list[Any]) -> dict[str, Any]:
    node_payloads: dict[str, dict[str, Any]] = {}
    key_by_name: dict[str, str] = {}
    roots: list[str] = []

    for idx, raw_node in enumerate(nodes):
        if not isinstance(raw_node, dict):
            continue
        key = str(raw_node.get("id", raw_node.get("uuid", f"node-{idx}")))
        payload = {
            "name": str(raw_node.get("name", key)),
            "metadata": {},
            "children": [],
            "_parent": raw_node.get("parent", raw_node.get("parent_id")),
            "_child_refs": raw_node.get("children", []),
        }
        if "bbox_position" in raw_node:
            payload["metadata"]["bbox_position"] = raw_node["bbox_position"]
        if isinstance(raw_node.get("metadata"), dict):
            payload["metadata"].update(raw_node["metadata"])
        if not payload["metadata"]:
            payload.pop("metadata")
        node_payloads[key] = payload
        key_by_name[payload["name"]] = key

    for key, payload in node_payloads.items():
        parent_ref = payload.pop("_parent", None)
        child_refs = payload.pop("_child_refs", [])
        if parent_ref is None:
            roots.append(key)
        else:
            parent_key = str(parent_ref)
            parent_key = parent_key if parent_key in node_payloads else key_by_name.get(parent_key, "")
            if parent_key and parent_key in node_payloads:
                node_payloads[parent_key]["children"].append(payload)
            else:
                roots.append(key)

        if isinstance(child_refs, list):
            for child_ref in child_refs:
                child_key = str(child_ref)
                child_key = child_key if child_key in node_payloads else key_by_name.get(child_key, "")
                child_payload = node_payloads.get(child_key)
                if child_payload and child_payload not in payload["children"]:
                    payload["children"].append(child_payload)

    unique_roots = []
    seen_roots: set[str] = set()
    for key in roots:
        if key in seen_roots:
            continue
        unique_roots.append(node_payloads[key])
        seen_roots.add(key)

    if len(unique_roots) == 1:
        return unique_roots[0]
    return {"name": "ExportScene", "children": unique_roots}


def _extract_rca_children(value: Any) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]

    if isinstance(value, dict):
        properties = value.get("properties", [])
        if isinstance(properties, list):
            refs = []
            for item in properties:
                if isinstance(item, dict) and isinstance(item.get("value"), str):
                    refs.append(item["value"])
            return refs

    return []


def _extract_rca_translation(properties: dict[str, Any]) -> list[float] | None:
    translation = properties.get("translation")
    if not isinstance(translation, dict):
        return None

    values: list[float] = []
    for axis in ("x", "y", "z"):
        axis_payload = translation.get(axis)
        if not isinstance(axis_payload, dict):
            return None
        value = axis_payload.get("value")
        if not isinstance(value, (int, float)):
            return None
        values.append(round(float(value), 6))
    return values


def _build_tree_from_rca_instances(instances: list[Any]) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    child_refs: dict[str, list[str]] = {}
    referenced_nodes: set[str] = set()

    for instance in instances:
        if not isinstance(instance, dict):
            continue
        properties = instance.get("properties")
        if not isinstance(properties, dict):
            continue

        object_id = properties.get("objectID")
        object_name = properties.get("objectName")
        if not isinstance(object_id, str) or not isinstance(object_name, str):
            continue

        node: dict[str, Any] = {"name": object_name, "children": []}
        metadata: dict[str, Any] = {}
        translation = _extract_rca_translation(properties)
        if translation is not None:
            metadata["translation"] = translation
        if metadata:
            node["metadata"] = metadata

        nodes[object_id] = node
        child_refs[object_id] = _extract_rca_children(properties.get("children"))

    for parent_id, refs in child_refs.items():
        parent = nodes.get(parent_id)
        if parent is None:
            continue
        for child_id in refs:
            child = nodes.get(child_id)
            if child is None or child in parent["children"]:
                continue
            parent["children"].append(child)
            referenced_nodes.add(child_id)

    roots = [node for object_id, node in nodes.items() if object_id not in referenced_nodes]
    if len(roots) == 1:
        return roots[0]
    return {"name": "ExportScene", "children": roots}


def _load_rca_json(path: Path) -> Any:
    if path.suffix.lower() == ".json":
        return load_json(path)

    with zipfile.ZipFile(path) as archive:
        json_members = [name for name in archive.namelist() if name.lower().endswith(".json")]
        if not json_members:
            raise ValueError(f"No JSON payload found inside RCA archive: {path}")
        payload = archive.read(json_members[0]).decode("utf-8")
    return json.loads(payload)


def normalize_scene_hierarchy_payload(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        for key in ("scene", "root", "hierarchy"):
            if key in data:
                return normalize_scene_hierarchy_payload(data[key])
        if "name" in data:
            return _normalize_node(data)
        for key in ("nodes", "objects"):
            value = data.get(key)
            if isinstance(value, list):
                return _build_tree_from_nodes(value)
    if isinstance(data, list):
        return _build_tree_from_nodes(data)
    raise ValueError("Unsupported scene hierarchy format")


def _choose_scene_input(path: Path) -> Path:
    if path.is_file():
        return path
    if not path.exists():
        raise FileNotFoundError(f"Input path does not exist: {path}")

    matches = find_matches(
        path,
        [
            "*AnchorPoints/*.rca",
            "*AnchorPoints.rca",
            "*.rca",
            "*anchor*.json",
            "*hierarchy*.json",
            "*scene*.json",
        ],
        limit=1,
    )
    if matches:
        return matches[0]
    raise FileNotFoundError(f"No anchor scene input found under: {path}")


def normalize_scene_hierarchy_source(path: Path) -> dict[str, Any]:
    source_path = _choose_scene_input(path)
    if source_path.suffix.lower() == ".rca" or source_path.name.lower().endswith(".rca.json"):
        payload = _load_rca_json(source_path)
        if isinstance(payload, dict) and isinstance(payload.get("instances"), list):
            return _build_tree_from_rca_instances(payload["instances"])
        raise ValueError(f"Unsupported RCA anchor payload: {source_path}")
    return normalize_scene_hierarchy_payload(load_json(source_path))
