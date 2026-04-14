from __future__ import annotations

from pathlib import Path
from typing import Any


def get_by_path(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise KeyError(path)
    return current


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def looks_like_windows_absolute(path: str) -> bool:
    return len(path) >= 3 and path[1:3] == ":\\"


def looks_like_posix_absolute(path: str) -> bool:
    return path.startswith("/")


def normalize_pathish(value: str) -> str:
    return value.replace("/", "\\").lower()


def is_under_path(candidate: str, root: str) -> bool:
    candidate_n = normalize_pathish(candidate)
    root_n = normalize_pathish(root).rstrip("\\")
    return candidate_n == root_n or candidate_n.startswith(root_n + "\\")


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
