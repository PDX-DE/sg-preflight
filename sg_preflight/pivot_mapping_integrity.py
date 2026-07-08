"""Pivot / Position-Mapping referential integrity.

Each car profile authors two JSON files that have to agree: a Pivot_Master with a
``TRANSFORMS`` dict naming every motion transform the car has (Door_F_L, Lid_F_L,
Hood, ...), and a Position_Mapping with a ``positionMapping`` dict that aliases
authoring positions onto those transforms (``Lid_F -> Lid_F_L``). If a mapping
points at a transform the profile does not define, that position silently has no
motion to bind to — and it only shows up when the animation is exercised.

This reads both files per profile (read-only) and reports aliases whose target is
missing from that profile's TRANSFORMS. Because the same alias is authored across
sibling profiles, it also reports which profiles do define each missing target, so
a reviewer can tell an intentional difference from an omission. SGFX never modifies
the profile files.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

POSITION_MAPPING_SUFFIX = "_Position_Mapping.json"
PIVOT_MASTER_SUFFIX = "_Pivot_Master.json"
DEFAULT_SCAN_LIMIT = 4000


def _load_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, ValueError):
        return None


def read_position_mapping(path: Path | str) -> dict[str, str]:
    """Return the ``positionMapping`` alias dict of a Position_Mapping file."""

    data = _load_json(Path(path))
    if not isinstance(data, dict):
        return {}
    mapping = data.get("positionMapping")
    if not isinstance(mapping, dict):
        return {}
    return {str(key): str(value) for key, value in mapping.items() if isinstance(value, str)}


def read_pivot_transforms(path: Path | str) -> set[str]:
    """Return the set of ``TRANSFORMS`` keys of a Pivot_Master file."""

    data = _load_json(Path(path))
    if not isinstance(data, dict):
        return set()
    transforms = data.get("TRANSFORMS")
    if not isinstance(transforms, dict):
        return set()
    return {str(key) for key in transforms}


def broken_aliases(mapping: dict[str, str], transforms: set[str]) -> list[dict[str, str]]:
    """Aliases whose target is not a defined transform.

    Self-maps (``key == value``) and empty targets are not aliases and are ignored.
    """

    result: list[dict[str, str]] = []
    for position, target in mapping.items():
        if not target or position == target:
            continue
        if target not in transforms:
            result.append({"position": position, "target": target})
    return result


def _profile_name(mapping_path: Path) -> str:
    name = mapping_path.name
    if name.endswith(POSITION_MAPPING_SUFFIX):
        return name[: -len(POSITION_MAPPING_SUFFIX)]
    return mapping_path.stem


def _iter_mapping_files(root: Path, *, limit: int) -> tuple[list[Path], bool]:
    if root.is_file():
        return ([root] if root.name.endswith(POSITION_MAPPING_SUFFIX) else []), False
    if not root.is_dir():
        return [], False
    found: list[Path] = []
    truncated = False
    for path in sorted(root.rglob(f"*{POSITION_MAPPING_SUFFIX}")):
        if len(found) >= limit:
            truncated = True
            break
        found.append(path)
    return found, truncated


def build_pivot_mapping_board(
    root: Path | str,
    *,
    scan_limit: int = DEFAULT_SCAN_LIMIT,
) -> dict[str, Any]:
    """Scan every profile under ``root`` and report Position-Mapping/Pivot integrity."""

    root = Path(root)
    mapping_files, truncated = _iter_mapping_files(root, limit=scan_limit)
    if not mapping_files:
        return {
            "root": str(root),
            "state": "no_mapping_found",
            "profiles_scanned": 0,
            "profiles_paired": 0,
            "profiles_with_broken": 0,
            "total_broken": 0,
            "broken_by_profile": [],
            "targets": [],
            "unpaired": [],
            "truncated": truncated,
            "scan_limit": scan_limit,
        }

    transforms_by_profile: dict[str, set[str]] = {}
    broken_by_profile: list[dict[str, Any]] = []
    unpaired: list[str] = []
    paired = 0
    for mapping_path in mapping_files:
        profile = _profile_name(mapping_path)
        pivot_path = mapping_path.with_name(f"{profile}{PIVOT_MASTER_SUFFIX}")
        if not pivot_path.is_file():
            unpaired.append(profile)
            continue
        paired += 1
        mapping = read_position_mapping(mapping_path)
        transforms = read_pivot_transforms(pivot_path)
        transforms_by_profile[profile] = transforms
        broken = broken_aliases(mapping, transforms)
        if broken:
            broken_by_profile.append(
                {
                    "profile": profile,
                    "path": _display_relative(mapping_path, root),
                    "broken": broken,
                }
            )

    targets = _target_index(broken_by_profile, transforms_by_profile)
    return {
        "root": str(root),
        "state": "ok",
        "profiles_scanned": len(mapping_files),
        "profiles_paired": paired,
        "profiles_with_broken": len(broken_by_profile),
        "total_broken": sum(len(item["broken"]) for item in broken_by_profile),
        "broken_by_profile": broken_by_profile,
        "targets": targets,
        "unpaired": sorted(unpaired),
        "truncated": truncated,
        "scan_limit": scan_limit,
    }


def _target_index(
    broken_by_profile: list[dict[str, Any]],
    transforms_by_profile: dict[str, set[str]],
) -> list[dict[str, Any]]:
    missing: dict[str, set[str]] = {}
    for item in broken_by_profile:
        for alias in item["broken"]:
            missing.setdefault(alias["target"], set()).add(item["profile"])
    index: list[dict[str, Any]] = []
    for target, missing_in in sorted(missing.items()):
        present_in = sorted(p for p, tr in transforms_by_profile.items() if target in tr)
        index.append(
            {
                "target": target,
                "missing_in": sorted(missing_in),
                "present_in": present_in,
            }
        )
    return index


def _display_relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def pivot_mapping_board_markdown(board: dict[str, Any]) -> str:
    lines = ["# Pivot / Position-Mapping referential integrity", ""]
    if board.get("state") == "no_mapping_found":
        lines.append(f"No Position_Mapping files found under `{board.get('root', '')}`.")
        lines.append("")
        return "\n".join(lines)

    total = int(board.get("total_broken", 0))
    profiles = int(board.get("profiles_paired", 0))
    with_broken = int(board.get("profiles_with_broken", 0))
    if total == 0:
        lines.append(f"Every position alias resolves to a defined transform across {profiles} profile(s).")
    else:
        lines.append(f"{total} position alias(es) in {with_broken} profile(s) point at a transform the profile does not define.")
    lines.append("")
    lines.append(f"- Profiles scanned: {board.get('profiles_scanned', 0)} ({profiles} paired with a Pivot_Master)")
    if board.get("unpaired"):
        lines.append(f"- Profiles without a Pivot_Master: {', '.join(board.get('unpaired', []))}")
    if board.get("truncated"):
        lines.append(f"- Scan stopped at the {board.get('scan_limit')} profile cap; not every mapping was read.")
    lines.append("")

    if board.get("broken_by_profile"):
        lines.append("## Unresolved aliases by profile")
        lines.append("")
        lines.append("| Profile | Position | Missing target |")
        lines.append("| --- | --- | --- |")
        for item in board["broken_by_profile"]:
            for alias in item["broken"]:
                lines.append(f"| {item['profile']} | {alias['position']} | {alias['target']} |")
        lines.append("")

    if board.get("targets"):
        lines.append("## Where each missing target is defined")
        lines.append("")
        lines.append("| Missing target | Missing in | Defined in |")
        lines.append("| --- | --- | --- |")
        for target in board["targets"]:
            present = ", ".join(target["present_in"]) or "no scanned profile"
            lines.append(f"| {target['target']} | {', '.join(target['missing_in'])} | {present} |")
        lines.append("")
    return "\n".join(lines)


def write_pivot_mapping_board(board: dict[str, Any], output_path: Path | str) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(pivot_mapping_board_markdown(board), encoding="utf-8")
    return output_path
