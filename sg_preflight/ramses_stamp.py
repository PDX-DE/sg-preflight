"""RAMSES scene-file version stamps and export consistency.

Every exported `.ramses` scene begins with a plaintext header stamp, e.g.
``[RamsesVersion:28.14.0].[GitHash:15e266db8f].[FeatureLevel:2]``. A head unit or
app integrates against one RAMSES runtime, so the scenes delivered together are
normally expected to share an engine version and feature level. When a tree mixes
versions or feature levels it usually means some profiles were not re-exported
after an engine or feature-level bump — a real integration risk that is otherwise
invisible because the stamp lives inside the binary.

This module reads those stamps (read-only) and reports the engine versions and
feature levels present across a tree, with a breakdown of how many scenes fall in
each bucket, so a reviewer can see at a glance whether the delivery is consistent.
It surfaces the split; it does not decide whether a mix is intentional. SGFX never
modifies the scene files.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

RAMSES_SUFFIX = ".ramses"
_STAMP_READ_BYTES = 256
# The bracketed fields are separated by non-printable bytes in the binary header,
# so each field is matched independently rather than as one fixed sequence.
_VERSION_RE = re.compile(rb"\[RamsesVersion:([^\]]*)\]")
_GIT_RE = re.compile(rb"\[GitHash:([^\]]*)\]")
_LEVEL_RE = re.compile(rb"\[FeatureLevel:([^\]]*)\]")
DEFAULT_SCAN_LIMIT = 4000


def read_ramses_stamp(path: Path | str) -> dict[str, str] | None:
    """Return the version stamp of a `.ramses` file, or None if absent/unreadable."""

    path = Path(path)
    try:
        with path.open("rb") as handle:
            head = handle.read(_STAMP_READ_BYTES)
    except OSError:
        return None
    version = _VERSION_RE.search(head)
    if not version:
        return None
    git = _GIT_RE.search(head)
    level = _LEVEL_RE.search(head)
    return {
        "ramses_version": version.group(1).decode("ascii", errors="replace"),
        "git_hash": git.group(1).decode("ascii", errors="replace") if git else "",
        "feature_level": level.group(1).decode("ascii", errors="replace") if level else "",
    }


def _iter_ramses_files(root: Path, *, limit: int) -> tuple[list[Path], bool]:
    if root.is_file():
        return ([root] if root.suffix.lower() == RAMSES_SUFFIX else []), False
    if not root.is_dir():
        return [], False
    found: list[Path] = []
    truncated = False
    for path in sorted(root.rglob(f"*{RAMSES_SUFFIX}")):
        if len(found) >= limit:
            truncated = True
            break
        found.append(path)
    return found, truncated


def _display_relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


_MAX_EXAMPLES = 6


def build_ramses_stamp_board(
    root: Path | str,
    *,
    scan_limit: int = DEFAULT_SCAN_LIMIT,
) -> dict[str, Any]:
    """Scan every `.ramses` under ``root`` for engine-version/feature-level consistency."""

    root = Path(root)
    files, truncated = _iter_ramses_files(root, limit=scan_limit)
    if not files:
        return {
            "root": str(root),
            "state": "no_ramses_found",
            "scanned_files": 0,
            "stamped_files": 0,
            "unreadable_files": 0,
            "ramses_versions": [],
            "feature_levels": [],
            "mixed_versions": False,
            "mixed_feature_levels": False,
            "breakdown": [],
            "truncated": truncated,
            "scan_limit": scan_limit,
        }

    buckets: dict[tuple[str, str], list[str]] = {}
    versions: set[str] = set()
    feature_levels: set[str] = set()
    stamped = 0
    unreadable = 0
    for path in files:
        stamp = read_ramses_stamp(path)
        if stamp is None:
            unreadable += 1
            continue
        stamped += 1
        versions.add(stamp["ramses_version"])
        feature_levels.add(stamp["feature_level"])
        key = (stamp["ramses_version"], stamp["feature_level"])
        buckets.setdefault(key, []).append(_display_relative(path, root))

    breakdown = [
        {
            "ramses_version": version,
            "feature_level": level,
            "count": len(paths),
            "examples": sorted(paths)[:_MAX_EXAMPLES],
        }
        for (version, level), paths in buckets.items()
    ]
    breakdown.sort(key=lambda item: (-item["count"], item["ramses_version"], item["feature_level"]))

    return {
        "root": str(root),
        "state": "ok",
        "scanned_files": len(files),
        "stamped_files": stamped,
        "unreadable_files": unreadable,
        "ramses_versions": sorted(versions),
        "feature_levels": sorted(feature_levels),
        "mixed_versions": len(versions) > 1,
        "mixed_feature_levels": len(feature_levels) > 1,
        "breakdown": breakdown,
        "truncated": truncated,
        "scan_limit": scan_limit,
    }


def ramses_stamp_board_markdown(board: dict[str, Any]) -> str:
    lines = ["# RAMSES export consistency", ""]
    if board.get("state") == "no_ramses_found":
        lines.append(f"No RAMSES scenes (`.ramses`) found under `{board.get('root', '')}`.")
        lines.append("")
        return "\n".join(lines)

    versions = board.get("ramses_versions") or []
    levels = board.get("feature_levels") or []
    mixed = board.get("mixed_versions") or board.get("mixed_feature_levels")
    stamped = int(board.get("stamped_files", 0))
    if not mixed:
        one_version = versions[0] if versions else "unknown"
        one_level = levels[0] if levels else "unknown"
        lines.append(f"All {stamped} scene(s) export at RAMSES {one_version}, feature level {one_level}.")
    else:
        parts = []
        if board.get("mixed_versions"):
            parts.append(f"{len(versions)} RAMSES versions")
        if board.get("mixed_feature_levels"):
            parts.append(f"{len(levels)} feature levels")
        lines.append(
            f"Scenes span {' and '.join(parts)} - worth confirming this split is intentional. Breakdown below."
        )
    lines.append("")
    lines.append(f"- Scenes scanned: {board.get('scanned_files', 0)} ({stamped} carry a stamp)")
    lines.append(f"- RAMSES versions present: {', '.join(versions) if versions else 'none'}")
    lines.append(f"- Feature levels present: {', '.join(levels) if levels else 'none'}")
    if board.get("unreadable_files"):
        lines.append(f"- Scenes without a readable stamp: {board.get('unreadable_files')}")
    if board.get("truncated"):
        lines.append(f"- Scan stopped at the {board.get('scan_limit')} scene cap; not every `.ramses` was read.")
    lines.append("")
    breakdown = board.get("breakdown") or []
    if breakdown:
        lines.append("## By engine version and feature level")
        lines.append("")
        lines.append("| RAMSES | FeatureLevel | Scenes | Examples |")
        lines.append("| --- | --- | --- | --- |")
        for bucket in breakdown:
            examples = ", ".join(bucket.get("examples", []))
            more = bucket["count"] - len(bucket.get("examples", []))
            if more > 0:
                examples += f", +{more} more"
            lines.append(
                f"| {bucket['ramses_version']} | {bucket['feature_level']} | {bucket['count']} | {examples} |"
            )
        lines.append("")
    return "\n".join(lines)


def write_ramses_stamp_board(board: dict[str, Any], output_path: Path | str) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(ramses_stamp_board_markdown(board), encoding="utf-8")
    return output_path
