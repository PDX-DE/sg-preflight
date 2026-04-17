from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def normalize_local_path(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    text = str(path).strip().strip('"').strip("'")
    if not text:
        return None
    candidate = Path(text).expanduser()
    try:
        return candidate.resolve(strict=False)
    except OSError:
        return candidate


def can_open_path(path: str | Path | None) -> bool:
    normalized = normalize_local_path(path)
    return normalized is not None and normalized.exists()


def can_reveal_path(path: str | Path | None) -> bool:
    normalized = normalize_local_path(path)
    if normalized is None:
        return False
    return normalized.exists() or normalized.parent.exists()


def build_open_command(path: str | Path, *, platform_name: str | None = None) -> tuple[str, ...]:
    normalized = normalize_local_path(path)
    if normalized is None:
        return ()
    platform_name = platform_name or sys.platform
    if platform_name.startswith("win"):
        return ("cmd", "/c", "start", "", str(normalized))
    if platform_name == "darwin":
        return ("open", str(normalized))
    return ("xdg-open", str(normalized))


def build_reveal_command(path: str | Path, *, platform_name: str | None = None) -> tuple[str, ...]:
    normalized = normalize_local_path(path)
    if normalized is None:
        return ()
    platform_name = platform_name or sys.platform
    if platform_name.startswith("win"):
        return ("explorer", "/select,", str(normalized))
    if platform_name == "darwin":
        return ("open", "-R", str(normalized))
    target = normalized if normalized.is_dir() else normalized.parent
    return ("xdg-open", str(target))


def open_local_path(path: str | Path) -> bool:
    normalized = normalize_local_path(path)
    if normalized is None or not normalized.exists():
        return False
    if sys.platform.startswith("win") and hasattr(os, "startfile"):
        os.startfile(str(normalized))
        return True
    command = build_open_command(normalized)
    if not command:
        return False
    subprocess.Popen(command)
    return True


def reveal_in_file_manager(path: str | Path) -> bool:
    normalized = normalize_local_path(path)
    if normalized is None:
        return False
    if not normalized.exists() and not normalized.parent.exists():
        return False
    command = build_reveal_command(normalized)
    if not command:
        return False
    subprocess.Popen(command)
    return True
