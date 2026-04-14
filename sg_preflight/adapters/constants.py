from __future__ import annotations

from pathlib import Path
from typing import Any

from sg_preflight.adapters.common import choose_json_input, load_json


def _set_by_path(target: dict[str, Any], path: str, value: Any) -> None:
    current = target
    parts = [part for part in path.split(".") if part]
    for part in parts[:-1]:
        next_value = current.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            current[part] = next_value
        current = next_value
    current[parts[-1]] = value


def normalize_constants_payload(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        for key in ("Pivot_Master", "pivot_master", "constants", "values", "data"):
            if key in data:
                inner = data[key]
                if isinstance(inner, (dict, list)):
                    return normalize_constants_payload(inner)
        return data

    if isinstance(data, list):
        normalized: dict[str, Any] = {}
        converted = False
        for item in data:
            if not isinstance(item, dict):
                continue
            path = item.get("path") or item.get("name") or item.get("key")
            if not isinstance(path, str) or not path:
                continue
            if "value" in item:
                value = item["value"]
            elif "expected" in item:
                value = item["expected"]
            elif "exported" in item:
                value = item["exported"]
            else:
                continue
            _set_by_path(normalized, path, value)
            converted = True
        if converted:
            return normalized

    raise ValueError("Unsupported constants format")


def normalize_constants_source(path: Path) -> dict[str, Any]:
    source_path = choose_json_input(
        path,
        ["*pivot*master*.json", "*constant*.json", "*.json"],
    )
    return normalize_constants_payload(load_json(source_path))
