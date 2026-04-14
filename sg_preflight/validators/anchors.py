from __future__ import annotations

from typing import Any

from sg_preflight.bundle import Bundle
from sg_preflight.models import Finding, PackResult


def _walk_nodes(node: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = [node]
    for child in node.get("children", []):
        if isinstance(child, dict):
            nodes.extend(_walk_nodes(child))
    return nodes


def _find_root(node: dict[str, Any], root_name: str) -> dict[str, Any] | None:
    for current in _walk_nodes(node):
        if current.get("name") == root_name:
            return current
    return None


def _parse_anchor_name(name: str) -> tuple[str, tuple[str, str, str]]:
    prefix = "APN_BoundingBox_"
    if not name.startswith(prefix):
        raise ValueError("Anchor must start with APN_BoundingBox_")

    remainder = name[len(prefix):]
    tokens = remainder.split("_")
    if len(tokens) < 4:
        raise ValueError("Anchor name must contain part and 3 position tokens")

    part_tokens = tokens[:-3]
    pos_tokens = tokens[-3:]
    if not all(part_tokens):
        raise ValueError("Vehicle part section is empty")
    part = "_".join(part_tokens)

    depth, vertical, lateral = pos_tokens
    if depth not in {"F", "B"}:
        raise ValueError("Depth token must be F or B")
    if vertical not in {"U", "D"}:
        raise ValueError("Vertical token must be U or D")
    if lateral not in {"L", "R"}:
        raise ValueError("Lateral token must be L or R")

    return part, (depth, vertical, lateral)


def validate_anchors(bundle: Bundle, config: dict[str, Any]) -> PackResult:
    result = PackResult(pack="anchors")
    scene = bundle.scene_hierarchy
    rules = config.get("anchors", {})
    root_name = rules.get("root_name", "Anchorpoints_BoundingBox")

    if scene is None:
        result.add(
            Finding(
                pack="anchors",
                code="anchors.missing_input",
                severity="error",
                message="scene_hierarchy.json is missing from the bundle",
            )
        )
        return result

    root = _find_root(scene, root_name)
    if root is None:
        result.add(
            Finding(
                pack="anchors",
                code="anchors.missing_root",
                severity="error",
                message=f"Could not find root node '{root_name}'",
                location=root_name,
            )
        )
        return result

    nodes = [child for child in _walk_nodes(root) if child is not root]
    names_seen: dict[str, int] = {}

    for node in nodes:
        name = str(node.get("name", ""))
        names_seen[name] = names_seen.get(name, 0) + 1

        try:
            part, position = _parse_anchor_name(name)
        except ValueError as exc:
            result.add(
                Finding(
                    pack="anchors",
                    code="anchors.invalid_name",
                    severity="error",
                    message=str(exc),
                    location=name or "<unnamed>",
                )
            )
            continue

        allowed_parts = set(rules.get("allowed_parts", []))
        if allowed_parts and part not in allowed_parts:
            result.add(
                Finding(
                    pack="anchors",
                    code="anchors.unknown_part",
                    severity="warning",
                    message=f"Anchor part '{part}' is not listed in allowed_parts",
                    location=name,
                )
            )

        metadata = node.get("metadata", {})
        actual_position = metadata.get("bbox_position")
        if isinstance(actual_position, list) and len(actual_position) == 3:
            expected = list(position)
            if actual_position != expected:
                result.add(
                    Finding(
                        pack="anchors",
                        code="anchors.position_mismatch",
                        severity="error",
                        message=(
                            "Anchor name encodes a different position than metadata "
                            f"(name={expected}, metadata={actual_position})"
                        ),
                        location=name,
                        details={"name_position": expected, "metadata_position": actual_position},
                    )
                )

    for name, count in names_seen.items():
        if count > 1:
            result.add(
                Finding(
                    pack="anchors",
                    code="anchors.duplicate_name",
                    severity="error",
                    message=f"Duplicate anchor name appears {count} times",
                    location=name,
                )
            )

    expected_anchors = set(rules.get("expected_anchor_names", []))
    if expected_anchors:
        missing = sorted(expected_anchors - set(names_seen))
        for name in missing:
            result.add(
                Finding(
                    pack="anchors",
                    code="anchors.missing_expected",
                    severity="error",
                    message="Expected anchor is missing",
                    location=name,
                )
            )

    return result
