from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
from typing import Any


_OMITTED_KEYS = frozenset(
    {
        "args",
        "argv",
        "capabilities",
        "capability",
        "command",
        "commands",
        "credentials",
        "env",
        "environment",
        "executable",
        "executables",
        "href",
        "launch_command",
        "link_url",
        "process_environment",
        "subprocess_command",
        "uri",
        "url",
    }
)
_SENSITIVE_KEY_PARTS = frozenset(
    {"api_key", "authorization", "cookie", "credential", "password", "pat", "secret", "token"}
)
_OMITTED_KEY_PARTS = frozenset(
    {"capabilities", "capability", "command", "commands", "environment", "executable", "executables"}
)
_PATH_KEY_SUFFIXES = ("_dir", "_directory", "_file", "_path", "_root")
_PATH_BOUNDARY_PATTERN = r"(?=(?:,\s*|;\s*|\s+(?:and|or)\s+|\r?$|\n))"
_WINDOWS_PATH_PATTERN = re.compile(
    r"(?i)(?:"
    r"[A-Z]:[\\/].*?"
    r"|\\\\[^\\/\s]+[\\/][^\\/\s,;]+(?:[\\/].*?)?"
    r")"
    + _PATH_BOUNDARY_PATTERN
)
_POSIX_PATH_PATTERN = re.compile(r"(?<![:\w])/(?!/).*?" + _PATH_BOUNDARY_PATTERN)
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[^\s,;]+")
_URL_PATTERN = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s,;]+")
_INLINE_SECRET_PATTERN = re.compile(
    r"(?i)\b(token|password|secret|pat|api[_-]?key|authorization)\s*[:=]\s*[^\s,;]+"
)


def _safe_path_label(path: Path, workspace: Path) -> str:
    resolved = path.expanduser().resolve()
    try:
        relative = resolved.relative_to(workspace)
    except ValueError:
        return resolved.name
    return relative.as_posix() or "."


def _normalized_key(key: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(key or "").strip().casefold()).strip("_")


def _is_sensitive_key(key: str | None) -> bool:
    normalized = _normalized_key(key)
    padded = f"_{normalized}_"
    return any(f"_{part}_" in padded for part in _SENSITIVE_KEY_PARTS)


def _is_omitted_key(key: str | None) -> bool:
    normalized = _normalized_key(key)
    padded = f"_{normalized}_"
    return (
        normalized in _OMITTED_KEYS
        or any(f"_{part}_" in padded for part in _OMITTED_KEY_PARTS)
        or normalized.startswith(
            (
                "capability_",
                "command_",
                "environment_",
                "executable_",
                "process_environment_",
                "subprocess_",
            )
        )
        or normalized.endswith(
            ("_capability", "_command", "_environment", "_executable")
        )
    )


def _is_path_key(key: str | None) -> bool:
    normalized = _normalized_key(key)
    return normalized in {"file", "path", "root", "workspace"} or normalized.endswith(
        _PATH_KEY_SUFFIXES
    )


def _unsafe_mapping_key(key: str) -> bool:
    return bool(
        _URL_PATTERN.search(key)
        or _WINDOWS_PATH_PATTERN.search(key)
        or _POSIX_PATH_PATTERN.search(key)
        or _BEARER_PATTERN.search(key)
        or _INLINE_SECRET_PATTERN.search(key)
    )


def _path_name(value: str) -> str:
    candidate = value.strip().strip('"\'').rstrip(".,;:)")
    if re.match(r"(?i)^[A-Z]:[\\/]", candidate) or candidate.startswith("\\\\"):
        return PureWindowsPath(candidate).name or "$LOCAL_PATH"
    return PurePosixPath(candidate).name or "$LOCAL_PATH"


def _safe_path_text(value: str, workspace: Path) -> str:
    text = value.strip().strip('"\'')
    variants = {str(workspace), workspace.as_posix()}
    for variant in sorted(variants, key=len, reverse=True):
        if text.casefold().startswith(variant.casefold()):
            relative = text[len(variant) :].lstrip("\\/")
            return relative.replace("\\", "/") or "."
    if re.match(r"(?i)^[A-Z]:[\\/]", text) or text.startswith("\\\\") or text.startswith("/"):
        return _path_name(text)
    normalized = text.replace("\\", "/")
    if normalized == ".." or normalized.startswith("../"):
        return PurePosixPath(normalized).name
    return normalized


def _safe_text(value: str, workspace: Path, *, key: str | None = None) -> str:
    if _is_sensitive_key(key):
        return "****" if value else ""
    contains_redacted_content = bool(
        _URL_PATTERN.search(value)
        or _BEARER_PATTERN.search(value)
        or _INLINE_SECRET_PATTERN.search(value)
    )
    if _is_path_key(key) and not contains_redacted_content:
        return _safe_path_text(value, workspace)
    sanitized = value
    variants = {str(workspace), workspace.as_posix()}
    for variant in sorted(variants, key=len, reverse=True):
        if variant:
            sanitized = re.sub(re.escape(variant), "$WORKSPACE", sanitized, flags=re.IGNORECASE)
    sanitized = _URL_PATTERN.sub("$EXTERNAL_LINK", sanitized)
    sanitized = _WINDOWS_PATH_PATTERN.sub(lambda match: _path_name(match.group(0)), sanitized)
    sanitized = _POSIX_PATH_PATTERN.sub(lambda match: _path_name(match.group(0)), sanitized)
    sanitized = _BEARER_PATTERN.sub("Bearer ****", sanitized)
    sanitized = _INLINE_SECRET_PATTERN.sub(lambda match: f"{match.group(1)}=****", sanitized)
    return sanitized


def _adapt_value(value: Any, workspace: Path, *, key: str | None = None) -> Any:
    if _is_sensitive_key(key):
        return "" if value is None or (isinstance(value, str) and not value) else "****"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _safe_text(value, workspace, key=key)
    if isinstance(value, Path):
        return _safe_path_label(value, workspace)
    if isinstance(value, Enum):
        return _adapt_value(value.value, workspace, key=key)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        adapted_dataclass: dict[str, Any] = {}
        for field in fields(value):
            if _is_omitted_key(field.name) or _unsafe_mapping_key(field.name):
                continue
            adapted_dataclass[field.name] = _adapt_value(
                getattr(value, field.name),
                workspace,
                key=field.name,
            )
        return adapted_dataclass
    if isinstance(value, Mapping):
        adapted_mapping: dict[str, Any] = {}
        for item_key, item in value.items():
            output_key = str(item_key)
            if _is_omitted_key(output_key) or _unsafe_mapping_key(output_key):
                continue
            adapted_mapping[output_key] = _adapt_value(item, workspace, key=output_key)
        return adapted_mapping
    if isinstance(value, (set, frozenset)):
        adapted_items = [_adapt_value(item, workspace, key=key) for item in value]
        return sorted(adapted_items, key=lambda item: (type(item).__name__, repr(item)))
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, memoryview)):
        return [_adapt_value(item, workspace, key=key) for item in value]
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{len(value)} bytes>"
    return _safe_text(str(value), workspace, key=key)


def adapt_page_payload(payload: Mapping[str, Any], *, workspace: Path | str) -> dict[str, Any]:
    root = Path(workspace).resolve()
    return _adapt_value(payload, root)
