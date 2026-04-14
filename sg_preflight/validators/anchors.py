from __future__ import annotations

from itertools import product
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
    matches = [current for current in _walk_nodes(node) if current.get("name") == root_name]
    if not matches:
        return None
    return max(matches, key=lambda current: len(_walk_nodes(current)))


def _parse_anchor_name(
    name: str,
    *,
    prefix: str,
    depth_tokens: set[str],
    vertical_tokens: set[str],
    lateral_tokens: set[str],
) -> tuple[str, tuple[str, str, str]]:
    if not name.startswith(prefix):
        raise ValueError(f"Anchor must start with {prefix}")

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
    if depth not in depth_tokens:
        raise ValueError(f"Depth token must be one of {sorted(depth_tokens)!r}")
    if vertical not in vertical_tokens:
        raise ValueError(f"Vertical token must be one of {sorted(vertical_tokens)!r}")
    if lateral not in lateral_tokens:
        raise ValueError(f"Lateral token must be one of {sorted(lateral_tokens)!r}")

    return part, (depth, vertical, lateral)


def _expected_anchor_names(rules: dict[str, Any], prefix: str) -> set[str]:
    explicit = {str(item).strip() for item in rules.get("expected_anchor_names", []) if str(item).strip()}
    if explicit:
        return explicit

    expected_parts = rules.get("expected_parts", [])
    positions = rules.get("position_tokens", {})
    depth_values = positions.get("depth", ["F", "B"])
    vertical_values = positions.get("vertical", ["U", "D"])
    lateral_values = positions.get("lateral", ["L", "R"])

    generated: set[str] = set()
    for part, depth, vertical, lateral in product(
        expected_parts,
        depth_values,
        vertical_values,
        lateral_values,
    ):
        generated.add(f"{prefix}{part}_{depth}_{vertical}_{lateral}")
    return generated


def _default_node_name_prefix(prefix: str) -> str:
    if not prefix:
        return ""
    return prefix.split("_", 1)[0]


def _rule_groups(rules: dict[str, Any]) -> list[dict[str, Any]]:
    configured = rules.get("rule_groups")
    if isinstance(configured, list) and configured:
        groups: list[dict[str, Any]] = []
        for index, raw_group in enumerate(configured, start=1):
            if not isinstance(raw_group, dict):
                continue
            group = dict(raw_group)
            group.setdefault("name", f"group_{index}")
            prefix = str(group.get("prefix", ""))
            group.setdefault("node_name_prefix", _default_node_name_prefix(prefix))
            groups.append(group)
        if groups:
            return groups

    legacy = dict(rules)
    prefix = str(legacy.get("prefix", "APN_BoundingBox_"))
    legacy.setdefault("name", "bounding_box")
    legacy["prefix"] = prefix
    legacy.setdefault("node_name_prefix", _default_node_name_prefix(prefix))
    return [legacy]


def _validate_rule_group(
    result: PackResult,
    scene: dict[str, Any],
    rules: dict[str, Any],
) -> None:
    group_name = str(rules.get("name", "anchors"))
    root_name = str(rules.get("root_name", "Anchorpoints_BoundingBox"))
    prefix = str(rules.get("prefix", ""))
    node_name_prefix = str(rules.get("node_name_prefix", _default_node_name_prefix(prefix)))
    positions = rules.get("position_tokens", {})
    depth_tokens = set(positions.get("depth", ["F", "B"]))
    vertical_tokens = set(positions.get("vertical", ["U", "D"]))
    lateral_tokens = set(positions.get("lateral", ["L", "R"]))
    uses_structured_name = bool(
        rules.get("position_tokens")
        or rules.get("allowed_parts")
        or rules.get("expected_parts")
    )

    root = _find_root(scene, root_name)
    if root is None:
        result.add(
            Finding(
                pack="anchors",
                code="anchors.missing_root",
                severity="error",
                message=f"Could not find root node '{root_name}' for anchor rule group '{group_name}'",
                location=root_name,
                details={"rule_group": group_name, "root_name": root_name},
            )
        )
        return

    nodes = [child for child in _walk_nodes(root) if child is not root]
    names_seen: dict[str, int] = {}

    for node in nodes:
        name = str(node.get("name", ""))
        if node_name_prefix and not name.startswith(node_name_prefix):
            continue

        names_seen[name] = names_seen.get(name, 0) + 1

        if prefix and not name.startswith(prefix):
            result.add(
                Finding(
                    pack="anchors",
                    code="anchors.invalid_name",
                    severity="error",
                    message=f"Anchor must start with {prefix}",
                    location=name or "<unnamed>",
                    details={"rule_group": group_name, "root_name": root_name},
                )
            )
            continue

        if not uses_structured_name:
            continue

        try:
            part, position = _parse_anchor_name(
                name,
                prefix=prefix,
                depth_tokens=depth_tokens,
                vertical_tokens=vertical_tokens,
                lateral_tokens=lateral_tokens,
            )
        except ValueError as exc:
            result.add(
                Finding(
                    pack="anchors",
                    code="anchors.invalid_name",
                    severity="error",
                    message=str(exc),
                    location=name or "<unnamed>",
                    details={"rule_group": group_name, "root_name": root_name},
                )
            )
            continue

        allowed_parts = {str(item) for item in rules.get("allowed_parts", []) if str(item).strip()}
        if allowed_parts and part not in allowed_parts:
            result.add(
                Finding(
                    pack="anchors",
                    code="anchors.unknown_part",
                    severity="warning",
                    message=f"Anchor part '{part}' is not listed in allowed_parts",
                    location=name,
                    details={"rule_group": group_name, "root_name": root_name},
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
                        details={
                            "rule_group": group_name,
                            "root_name": root_name,
                            "name_position": expected,
                            "metadata_position": actual_position,
                        },
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
                    details={"rule_group": group_name, "root_name": root_name},
                )
            )

    expected_anchors = _expected_anchor_names(rules, prefix)
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
                    details={"rule_group": group_name, "root_name": root_name},
                )
            )


def validate_anchors(bundle: Bundle, config: dict[str, Any]) -> PackResult:
    result = PackResult(pack="anchors")
    scene = bundle.scene_hierarchy
    rules = config.get("anchors", {})

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

    for group in _rule_groups(rules):
        _validate_rule_group(result, scene, group)

    return result
