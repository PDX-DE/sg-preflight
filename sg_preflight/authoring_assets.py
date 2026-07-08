"""Authoring-only asset inventory (Blender ``special/`` workfiles).

Each car profile keeps authoring-only Blender files in a ``special/`` folder next to
its exportable workfiles: helper geometry, wheel-pivot rigs, ground-shadow bakes,
boolean cutters, and files explicitly marked ``NOEXPORT``. These never ship, but a
reviewer or a new technical artist has no easy way to see, per profile, which
authoring assets exist or which are deliberately non-exportable — SGFX has no
awareness of them today.

This catalogs those files per profile (read-only), flags the ``NOEXPORT`` ones, and
builds a cross-profile presence view so an outlier (a profile missing an asset its
siblings all have, or carrying an unusual one) is visible. It reports facts, not a
verdict.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

BLEND_SUFFIX = ".blend"
NOEXPORT_MARKER = "NOEXPORT"
DEFAULT_SCAN_LIMIT = 4000


def _normalize_asset(file_stem: str, profile: str) -> tuple[str, bool]:
    """Return (asset name without profile prefix / NOEXPORT marker, is_noexport)."""

    name = file_stem
    prefix = f"{profile}_"
    if name.startswith(prefix):
        name = name[len(prefix):]
    is_noexport = NOEXPORT_MARKER.lower() in file_stem.lower()
    # Strip a trailing _NOEXPORT token so the asset groups with its exportable kin.
    tokens = [t for t in name.split("_") if t.upper() != NOEXPORT_MARKER]
    normalized = "_".join(tokens) or name
    return normalized, is_noexport


def _profile_from_path(special_dir: Path) -> str:
    # .../cars/BMW/<PROFILE>/_WorkFiles/blender/special
    for parent in special_dir.parents:
        grandparent = parent.parent
        if grandparent is not None and grandparent.name.upper() == "BMW":
            return parent.name
    return special_dir.parts[-4] if len(special_dir.parts) >= 4 else special_dir.name


def build_authoring_asset_board(
    root: Path | str,
    *,
    scan_limit: int = DEFAULT_SCAN_LIMIT,
) -> dict[str, Any]:
    """Catalog authoring-only ``special/`` Blender files per profile under ``root``."""

    root = Path(root)
    if not root.is_dir():
        return _empty_board(root, scan_limit)

    by_profile: dict[str, dict[str, Any]] = {}
    asset_presence: dict[str, set[str]] = {}
    noexport: list[dict[str, str]] = []
    collected: list[tuple[str, Path]] = []
    scanned = 0
    truncated = False
    for path in sorted(root.rglob(f"*{BLEND_SUFFIX}")):
        if scanned >= scan_limit:
            truncated = True
            break
        parts = [p.lower() for p in path.parts]
        if "special" not in parts or "blender" not in parts:
            continue
        scanned += 1
        profile = _profile_from_path(path.parent)
        collected.append((profile, path))
        asset, is_noexport = _normalize_asset(path.stem, profile)
        record = by_profile.setdefault(profile, {"profile": profile, "assets": [], "noexport": []})
        if asset not in record["assets"]:
            record["assets"].append(asset)
        asset_presence.setdefault(asset, set()).add(profile)
        if is_noexport:
            record["noexport"].append(path.name)
            noexport.append({"profile": profile, "file": path.name})

    if not by_profile:
        return _empty_board(root, scan_limit)

    known_profiles = set(by_profile)
    mismatched: list[dict[str, str]] = []
    for profile, path in collected:
        if path.stem.startswith(f"{profile}_"):
            continue
        leading = path.stem.split("_", 1)[0]
        donor = next((p for p in known_profiles if p != profile and path.stem.startswith(f"{p}_")), "")
        mismatched.append(
            {
                "profile": profile,
                "file": path.name,
                "leading_token": leading,
                "looks_copied_from": donor,
            }
        )

    profiles = sorted(by_profile)
    assets = [
        {"asset": asset, "present_in": sorted(present), "count": len(present)}
        for asset, present in asset_presence.items()
    ]
    assets.sort(key=lambda item: (-item["count"], item["asset"]))
    return {
        "root": str(root),
        "state": "ok",
        "profiles_scanned": len(profiles),
        "profiles_with_special": len(profiles),
        "special_files": scanned,
        "assets": assets,
        "noexport": sorted(noexport, key=lambda item: (item["profile"], item["file"])),
        "mismatched_prefix": sorted(mismatched, key=lambda item: (item["profile"], item["file"])),
        "by_profile": [by_profile[p] for p in profiles],
        "truncated": truncated,
        "scan_limit": scan_limit,
    }


def _empty_board(root: Path, scan_limit: int) -> dict[str, Any]:
    return {
        "root": str(root),
        "state": "no_special_found",
        "profiles_scanned": 0,
        "profiles_with_special": 0,
        "special_files": 0,
        "assets": [],
        "noexport": [],
        "mismatched_prefix": [],
        "by_profile": [],
        "truncated": False,
        "scan_limit": scan_limit,
    }


def authoring_asset_board_markdown(board: dict[str, Any]) -> str:
    lines = ["# Authoring-only asset inventory", ""]
    if board.get("state") == "no_special_found":
        lines.append(f"No `special/` authoring folders found under `{board.get('root', '')}`.")
        lines.append("")
        return "\n".join(lines)

    profiles = int(board.get("profiles_with_special", 0))
    files = int(board.get("special_files", 0))
    noexport = board.get("noexport") or []
    mismatched = board.get("mismatched_prefix") or []
    lines.append(
        f"{files} authoring-only file(s) across {profiles} profile(s); "
        f"{len(noexport)} marked NOEXPORT; {len(mismatched)} with a mismatched profile prefix."
    )
    lines.append("")
    if board.get("truncated"):
        lines.append(f"- Scan stopped at the {board.get('scan_limit')} file cap; not every workfile was read.")
        lines.append("")

    if mismatched:
        lines.append("## Files with a mismatched profile prefix")
        lines.append("")
        lines.append("These sit in one profile's `special/` folder but are named for another - usually a donor")
        lines.append("copy that was not renamed. Worth confirming the profile owns its own authoring assets.")
        lines.append("")
        lines.append("| Profile | File | Named for |")
        lines.append("| --- | --- | --- |")
        for item in mismatched:
            named = item.get("looks_copied_from") or item.get("leading_token", "")
            lines.append(f"| {item['profile']} | {item['file']} | {named} |")
        lines.append("")

    if noexport:
        lines.append("## NOEXPORT-marked files")
        lines.append("")
        lines.append("| Profile | File |")
        lines.append("| --- | --- |")
        for item in noexport:
            lines.append(f"| {item['profile']} | {item['file']} |")
        lines.append("")

    assets = board.get("assets") or []
    if assets:
        lines.append("## Authoring assets across profiles")
        lines.append("")
        lines.append("| Asset | Profiles | Present in |")
        lines.append("| --- | --- | --- |")
        for asset in assets:
            present = ", ".join(asset["present_in"])
            lines.append(f"| {asset['asset']} | {asset['count']} | {present} |")
        lines.append("")
    return "\n".join(lines)


def write_authoring_asset_board(board: dict[str, Any], output_path: Path | str) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(authoring_asset_board_markdown(board), encoding="utf-8")
    return output_path
