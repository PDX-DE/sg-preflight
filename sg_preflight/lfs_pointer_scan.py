"""Git-LFS pointer-stub scan driven by a repo's own .gitattributes.

A repository that stores large binaries in Git-LFS declares the tracked file types
in .gitattributes (``*.ramses filter=lfs``, ``*.png filter=lfs``, ...). If the
checkout was made without ``git lfs pull``, those files are still small text
pointer stubs (``version https://git-lfs.github.com/spec/v1`` ...) rather than the
real asset — and a scene or car then renders blank, which reads as a visual
regression and burns a review cycle.

This reads the repo's .gitattributes to learn which extensions are LFS-tracked
(rather than a hard-coded list), then checks the first bytes of those files for the
pointer prefix and reports any that are still stubs. Read-only.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec/v1"
_LFS_LINE_RE = re.compile(r"^\s*(?P<pattern>\S+)\s+(?P<attrs>.*filter=lfs.*)$")
DEFAULT_SCAN_LIMIT = 6000


def lfs_extensions_from_gitattributes(text: str) -> set[str]:
    """Return the lowercased file extensions marked ``filter=lfs``.

    Patterns are almost always extension-anchored (``*.png``,
    ``unity-stage/**/*.png``); the trailing extension is what matters for finding
    the tracked files on disk.
    """

    extensions: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = _LFS_LINE_RE.match(line)
        if not match:
            continue
        pattern = match.group("pattern")
        dot = pattern.rfind(".")
        if dot == -1:
            continue
        ext = pattern[dot:].lower()
        # Keep simple extensions like ".png"; skip anything with glob leftovers.
        if ext and all(ch.isalnum() for ch in ext[1:]) and len(ext) > 1:
            extensions.add(ext)
    return extensions


def _is_pointer_stub(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            head = handle.read(len(_LFS_POINTER_PREFIX))
    except OSError:
        return False
    return head == _LFS_POINTER_PREFIX


def scan_lfs_pointers(root: Path | str, *, scan_limit: int = DEFAULT_SCAN_LIMIT) -> dict[str, Any]:
    """Scan ``root`` for LFS-tracked files that are still un-pulled pointer stubs."""

    root = Path(root)
    gitattributes = root / ".gitattributes"
    if not gitattributes.is_file():
        return {"root": str(root), "state": "no_gitattributes", "lfs_extensions": [], "scanned_files": 0,
                "pointer_stub_count": 0, "pointer_files": [], "truncated": False, "scan_limit": scan_limit}
    try:
        extensions = lfs_extensions_from_gitattributes(gitattributes.read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        extensions = set()
    if not extensions:
        return {"root": str(root), "state": "no_lfs_tracked", "lfs_extensions": [], "scanned_files": 0,
                "pointer_stub_count": 0, "pointer_files": [], "truncated": False, "scan_limit": scan_limit}

    scanned = 0
    pointer_files: list[str] = []
    truncated = False
    for path in sorted(root.rglob("*")):
        if scanned >= scan_limit:
            truncated = True
            break
        if not path.is_file() or path.suffix.lower() not in extensions:
            continue
        scanned += 1
        if _is_pointer_stub(path):
            pointer_files.append(path.relative_to(root).as_posix())
    return {
        "root": str(root),
        "state": "lfs_pointers_detected" if pointer_files else "ok",
        "lfs_extensions": sorted(extensions),
        "scanned_files": scanned,
        "pointer_stub_count": len(pointer_files),
        "pointer_files": pointer_files,
        "truncated": truncated,
        "scan_limit": scan_limit,
    }


def lfs_pointer_scan_markdown(board: dict[str, Any]) -> str:
    lines = ["# Git-LFS pointer-stub scan", ""]
    state = board.get("state")
    if state == "no_gitattributes":
        lines.append(f"No `.gitattributes` under `{board.get('root', '')}` — nothing declares Git-LFS tracking here.")
        lines.append("")
        return "\n".join(lines)
    if state == "no_lfs_tracked":
        lines.append(f"`.gitattributes` under `{board.get('root', '')}` declares no `filter=lfs` file types.")
        lines.append("")
        return "\n".join(lines)

    count = int(board.get("pointer_stub_count", 0))
    if count == 0:
        lines.append(f"All {board.get('scanned_files', 0)} LFS-tracked file(s) are pulled - no un-smudged pointer stubs.")
    else:
        lines.append(f"{count} LFS-tracked file(s) are still un-pulled pointer stubs and would render as missing assets.")
    lines.append("")
    lines.append(f"- LFS-tracked extensions: {', '.join(board.get('lfs_extensions', [])) or 'none'}")
    lines.append(f"- Files checked: {board.get('scanned_files', 0)}")
    if board.get("truncated"):
        lines.append(f"- Scan stopped at the {board.get('scan_limit')} file cap; not every tracked file was checked.")
    lines.append("")
    if board.get("pointer_files"):
        lines.append("## Un-pulled pointer stubs")
        lines.append("")
        for name in board["pointer_files"][:50]:
            lines.append(f"- `{name}`")
        if len(board["pointer_files"]) > 50:
            lines.append(f"- ... and {len(board['pointer_files']) - 50} more")
        lines.append("")
        lines.append("Run `git lfs pull` in the checkout before trusting an export or screenshot pass.")
        lines.append("")
    return "\n".join(lines)


def write_lfs_pointer_scan(board: dict[str, Any], output_path: Path | str) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(lfs_pointer_scan_markdown(board), encoding="utf-8")
    return output_path
