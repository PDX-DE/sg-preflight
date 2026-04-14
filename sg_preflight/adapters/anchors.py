from __future__ import annotations

from pathlib import Path
from typing import Any

from sg_preflight.adapters.common import choose_json_input, load_json


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


def normalize_scene_hierarchy_source(path: Path) -> dict[str, Any]:
    source_path = choose_json_input(
        path,
        ["*anchor*.json", "*hierarchy*.json", "*scene*.json"],
    )
    return normalize_scene_hierarchy_payload(load_json(source_path))
