from __future__ import annotations

import json
import os
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Iterable, Iterator

from sg_preflight.utils import ensure_parent


SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".idea",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}

TEXT_SUFFIXES = {
    ".cfg",
    ".conf",
    ".ini",
    ".json",
    ".lua",
    ".md",
    ".py",
    ".rca",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, data: Any) -> None:
    ensure_parent(path)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)


def _prune_dirs(dirnames: list[str]) -> None:
    dirnames[:] = [name for name in dirnames if name not in SKIP_DIR_NAMES]


def walk_dirs(root: Path, max_depth: int = 4) -> Iterator[Path]:
    if not root.exists() or not root.is_dir():
        return

    root = root.resolve()
    root_depth = len(root.parts)
    for dirpath, dirnames, _filenames in os.walk(root):
        current = Path(dirpath)
        depth = len(current.parts) - root_depth
        _prune_dirs(dirnames)
        if depth > max_depth:
            dirnames[:] = []
            continue
        yield current


def walk_files(
    root: Path,
    *,
    suffixes: set[str] | None = None,
    max_bytes: int | None = 2_000_000,
) -> Iterator[Path]:
    if not root.exists() or not root.is_dir():
        return

    for dirpath, dirnames, filenames in os.walk(root):
        _prune_dirs(dirnames)
        current = Path(dirpath)
        for filename in filenames:
            path = current / filename
            if suffixes and path.suffix.lower() not in suffixes:
                continue
            if max_bytes is not None:
                try:
                    if path.stat().st_size > max_bytes:
                        continue
                except OSError:
                    continue
            yield path


def find_matches(
    root: Path,
    patterns: Iterable[str],
    *,
    include_dirs: bool = False,
    limit: int = 20,
) -> list[Path]:
    normalized_patterns = [pattern.lower() for pattern in patterns]
    matches: list[Path] = []

    if include_dirs:
        for path in walk_dirs(root, max_depth=8):
            rel = path.relative_to(root).as_posix().lower()
            name = path.name.lower()
            if any(fnmatch(name, pattern) or fnmatch(rel, pattern) for pattern in normalized_patterns):
                matches.append(path)
                if len(matches) >= limit:
                    return matches

    for path in walk_files(root, max_bytes=None):
        rel = path.relative_to(root).as_posix().lower()
        name = path.name.lower()
        if any(fnmatch(name, pattern) or fnmatch(rel, pattern) for pattern in normalized_patterns):
            matches.append(path)
            if len(matches) >= limit:
                break

    return matches


def choose_json_input(path: Path, preferred_patterns: Iterable[str]) -> Path:
    if path.is_file():
        return path
    if not path.exists():
        raise FileNotFoundError(f"Input path does not exist: {path}")

    preferred = find_matches(path, preferred_patterns, limit=1)
    if preferred:
        return preferred[0]

    fallbacks = sorted(walk_files(path, suffixes={".json"}))
    if not fallbacks:
        raise FileNotFoundError(f"No JSON file found under: {path}")
    return fallbacks[0]


def to_display_path(path: Path, root: Path | None = None) -> str:
    if root is None:
        return str(path.resolve())
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())
