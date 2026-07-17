"""RaCo external-project reference integrity.

A RaCo project (`.rca`) can reference other `.rca` files it depends on — a shared
camera, a `_Shared`/`_Common` prefab, a stage. Those references live in the
`externalProjects` block of the zipped project JSON as relative paths resolved from
the referencing project's own directory. If one moves or is not checked out, RaCo
silently loads a broken scene and a reviewer only finds out by opening it.

This module reads those references (read-only) and reports which ones resolve on
disk and which are broken, for every `.rca` under a root. SGFX never modifies the
project files.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from sg_preflight.adapters.common import walk_files

RCA_SUFFIX = ".rca"
STATUS_RESOLVED = "resolved"
STATUS_MISSING = "missing"
DEFAULT_SCAN_LIMIT = 2000


def _load_rca_json(path: Path) -> Any | None:
    try:
        if not zipfile.is_zipfile(path):
            return None
        with zipfile.ZipFile(path) as archive:
            members = [name for name in archive.namelist() if name.lower().endswith(".json")]
            if not members:
                return None
            return json.loads(archive.read(members[0]).decode("utf-8", errors="ignore"))
    except (OSError, zipfile.BadZipFile, ValueError):
        return None


def read_rca_external_projects(rca_path: Path | str) -> list[dict[str, Any]]:
    """Return the external-project references one `.rca` declares.

    Each entry is resolved against the `.rca`'s own directory and carries an
    existence flag. Returns an empty list when the file is not a readable RaCo
    project or declares no external projects.
    """

    rca_path = Path(rca_path)
    data = _load_rca_json(rca_path)
    if not isinstance(data, dict):
        return []
    external = data.get("externalProjects")
    if not isinstance(external, dict):
        return []
    base = rca_path.resolve().parent
    references: list[dict[str, Any]] = []
    for key, entry in external.items():
        if not isinstance(entry, dict):
            continue
        relative = str(entry.get("path", "") or "").strip()
        name = str(entry.get("name", "") or "").strip()
        resolved_path = ""
        exists = False
        if relative:
            candidate = base / relative
            try:
                resolved = candidate.resolve()
            except OSError:
                resolved = candidate
            resolved_path = str(resolved)
            try:
                exists = resolved.is_file()
            except OSError:
                exists = False
        references.append(
            {
                "id": str(key),
                "name": name,
                "path": relative,
                "resolved_path": resolved_path,
                "status": STATUS_RESOLVED if exists else STATUS_MISSING,
            }
        )
    return references


def _iter_rca_files(root: Path, *, limit: int) -> tuple[list[Path], bool]:
    if root.is_file():
        return ([root] if root.suffix.lower() == RCA_SUFFIX else []), False
    if not root.is_dir():
        return [], False
    # Route through the shared pruned walk: raw rglob re-descends .svn/out/build/operator_state
    # trees the rest of the tool already skips, which made this report take 70-90s on a full
    # SVN mirror. Those directories never hold authored reference assets, so pruning is
    # result-preserving. Size filtering stays off so large .rca files are still found.
    matches = sorted(walk_files(root, suffixes={RCA_SUFFIX}, max_bytes=None))
    found = matches[:limit]
    truncated = len(matches) > limit
    return found, truncated


def build_rca_reference_board(
    root: Path | str,
    *,
    scan_limit: int = DEFAULT_SCAN_LIMIT,
) -> dict[str, Any]:
    """Scan every `.rca` under ``root`` and report external-reference integrity."""

    root = Path(root)
    rca_files, truncated = _iter_rca_files(root, limit=scan_limit)
    if not rca_files:
        return {
            "root": str(root),
            "state": "no_rca_found",
            "scanned_files": 0,
            "files_with_references": 0,
            "total_references": 0,
            "resolved": 0,
            "missing": 0,
            "broken": [],
            "truncated": truncated,
            "scan_limit": scan_limit,
        }

    files_with_references = 0
    total_references = 0
    resolved = 0
    missing = 0
    broken: list[dict[str, Any]] = []
    for rca_path in rca_files:
        references = read_rca_external_projects(rca_path)
        if references:
            files_with_references += 1
        for reference in references:
            total_references += 1
            if reference["status"] == STATUS_RESOLVED:
                resolved += 1
            else:
                missing += 1
                broken.append(
                    {
                        "rca": _display_relative(rca_path, root),
                        "name": reference["name"],
                        "path": reference["path"],
                        "resolved_path": reference["resolved_path"],
                    }
                )
    return {
        "root": str(root),
        "state": "ok",
        "scanned_files": len(rca_files),
        "files_with_references": files_with_references,
        "total_references": total_references,
        "resolved": resolved,
        "missing": missing,
        "broken": broken,
        "truncated": truncated,
        "scan_limit": scan_limit,
    }


def _display_relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def rca_reference_board_markdown(board: dict[str, Any]) -> str:
    lines = ["# RaCo external-project reference integrity", ""]
    if board.get("state") == "no_rca_found":
        lines.append(f"No RaCo projects (`.rca`) found under `{board.get('root', '')}`.")
        lines.append("")
        return "\n".join(lines)

    missing = int(board.get("missing", 0))
    total = int(board.get("total_references", 0))
    scanned = int(board.get("scanned_files", 0))
    with_refs = int(board.get("files_with_references", 0))
    headline = (
        f"All {total} external reference(s) resolve."
        if missing == 0
        else f"{missing} of {total} external reference(s) are broken."
    )
    lines.append(headline)
    lines.append("")
    lines.append(f"- Projects scanned: {scanned} ({with_refs} declare external references)")
    lines.append(f"- References resolved: {board.get('resolved', 0)}")
    lines.append(f"- References broken: {missing}")
    if board.get("truncated"):
        lines.append(f"- Scan stopped at the {board.get('scan_limit')} project cap; not every `.rca` was read.")
    lines.append("")
    broken = board.get("broken") or []
    if broken:
        lines.append("## Broken references")
        lines.append("")
        lines.append("| Project | Reference | Declared path | Expected on disk |")
        lines.append("| --- | --- | --- | --- |")
        for item in broken:
            lines.append(
                f"| {item.get('rca', '')} | {item.get('name', '')} | "
                f"`{item.get('path', '')}` | `{item.get('resolved_path', '')}` |"
            )
        lines.append("")
    return "\n".join(lines)


def write_rca_reference_board(board: dict[str, Any], output_path: Path | str) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rca_reference_board_markdown(board), encoding="utf-8")
    return output_path
