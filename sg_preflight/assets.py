from __future__ import annotations

import sys
from pathlib import Path


def _source_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _candidate_roots() -> list[Path]:
    roots: list[Path] = []
    bundle_root = getattr(sys, "_MEIPASS", "")
    if bundle_root:
        roots.append(Path(str(bundle_root)).resolve())
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
    roots.append(_source_root())
    roots.append(Path.cwd().resolve())

    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root).casefold()
        if key not in seen:
            unique.append(root)
            seen.add(key)
    return unique


def runtime_asset_path(relative_path: str | Path) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute():
        return relative
    for root in _candidate_roots():
        candidate = root / relative
        if candidate.is_file():
            return candidate
    return _candidate_roots()[0] / relative


def runtime_asset_root() -> Path:
    icon = runtime_asset_path("sgfx_icon.png")
    if icon.is_file():
        return icon.parent
    return _candidate_roots()[0]
