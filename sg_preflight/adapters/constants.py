from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sg_preflight.adapters.common import find_matches, load_json


NUMBER_PATTERN = re.compile(r"[-+]?\d+(?:\.\d+)?")


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


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _round_float(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


def _normalize_trim_name(name: str) -> str:
    normalized = name.strip()
    if normalized.startswith("TRIM_"):
        normalized = normalized[len("TRIM_") :]
    if normalized.isupper() and len(normalized) > 3:
        normalized = normalized.capitalize()
    return normalized


def _infer_project_metadata(path: Path) -> dict[str, str]:
    parts = list(path.resolve().parts)
    for marker in ("Cars", "Cars_IDCevo"):
        if marker in parts:
            index = parts.index(marker)
            if index + 2 < len(parts):
                return {
                    "generation": marker,
                    "brand": parts[index + 1],
                    "car_model": parts[index + 2],
                }
    return {}


def _normalize_front_rear(value: Any, *, scale: float = 1.0) -> dict[str, float] | None:
    numeric = _to_float(value)
    if numeric is not None:
        rounded = _round_float(numeric * scale)
        if rounded is None:
            return None
        return {"front": rounded, "rear": rounded}

    if isinstance(value, (list, tuple)) and len(value) >= 2:
        front = _to_float(value[0])
        rear = _to_float(value[1])
        if front is None or rear is None:
            return None
        return {
            "front": _round_float(front * scale),
            "rear": _round_float(rear * scale),
        }

    return None


def _normalize_trim_mapping(mapping: Any, *, scale: float = 1.0) -> dict[str, dict[str, float]]:
    if not isinstance(mapping, dict):
        return {}

    normalized: dict[str, dict[str, float]] = {}
    for key, value in mapping.items():
        pair = _normalize_front_rear(value, scale=scale)
        if pair is not None:
            normalized[_normalize_trim_name(str(key))] = pair
    return normalized


def _normalize_pivot_master_payload(data: dict[str, Any], *, source_path: Path | None = None) -> dict[str, Any]:
    metadata = _infer_project_metadata(source_path) if source_path else {}
    suspension = data.get("SUSPENSION", {})
    reflection = data.get("REFLECTION", {})

    normalized: dict[str, Any] = {
        "schema": "sg_pivot_master",
        **metadata,
    }

    wheelbase = _round_float(_to_float(suspension.get("Wheelbase")))
    if wheelbase is not None:
        normalized["wheelbase_m"] = wheelbase

    origin_offset = suspension.get("Origin_Offset")
    if isinstance(origin_offset, list) and len(origin_offset) >= 3:
        normalized["suspension_offset_m"] = {
            "x": _round_float(_to_float(origin_offset[0])),
            "y": _round_float(_to_float(origin_offset[2])),
            "z": _round_float(_to_float(origin_offset[1])),
        }

    tire_diameter = _normalize_trim_mapping(suspension.get("Tire_Diameter"))
    if tire_diameter:
        normalized["tire_diameter_cm"] = tire_diameter

    rim_diameter = _normalize_trim_mapping(suspension.get("Rim_Diameter"))
    if rim_diameter:
        normalized["rim_diameter_in"] = rim_diameter

    tire_width = _normalize_trim_mapping(suspension.get("Tire_Width"))
    if tire_width:
        normalized["tire_width_cm"] = tire_width

    wheel_distance = _normalize_trim_mapping(suspension.get("Wheel_Outer_Distance"), scale=0.01)
    if wheel_distance:
        normalized["wheel_distance_m"] = wheel_distance

    reflection_payload = {
        "car_height_m": _round_float(_to_float(reflection.get("Car_Height"))),
        "car_length_m": _round_float(_to_float(reflection.get("Car_Length"))),
        "hood_height_m": _round_float(_to_float(reflection.get("Hood_Height"))),
        "hood_length_m": _round_float(_to_float(reflection.get("Hood_Length"))),
        "trunk_height_m": _round_float(_to_float(reflection.get("Trunk_Height"))),
        "trunk_length_m": _round_float(_to_float(reflection.get("Trunk_Length"))),
        "x_offset_m": _round_float(-(_to_float(reflection.get("X_Offset")) or 0.0)),
    }
    reflection_payload = {
        key: value for key, value in reflection_payload.items() if value is not None
    }
    if reflection_payload:
        normalized["reflection"] = reflection_payload

    return normalized


def _parse_lua_assignment_number(text: str, constant_name: str) -> float | None:
    pattern = re.compile(rf"constants\.{re.escape(constant_name)}\s*=\s*({NUMBER_PATTERN.pattern})")
    match = pattern.search(text)
    if not match:
        return None
    return _to_float(match.group(1))


def _parse_lua_assignment_vector(text: str, constant_name: str) -> list[float] | None:
    pattern = re.compile(rf"constants\.{re.escape(constant_name)}\s*=\s*\{{([^}}]+)\}}", re.S)
    match = pattern.search(text)
    if not match:
        return None
    values = [_to_float(item) for item in NUMBER_PATTERN.findall(match.group(1))]
    if any(value is None for value in values):
        return None
    return [round(float(value), 6) for value in values if value is not None]


def _parse_lua_wheels_sizes(text: str) -> dict[str, dict[str, float]]:
    pattern = re.compile(
        r"(?:local\s+)?wheels\s*=\s*\{(?P<body>.*?)\}\s*constants\.WHEELS_SIZE_(?P<trim>[A-Za-z0-9_]+)\s*=\s*wheels",
        re.S,
    )
    payload: dict[str, dict[str, float]] = {}
    for match in pattern.finditer(text):
        body = match.group("body")
        trim = _normalize_trim_name(match.group("trim"))
        entry: dict[str, float] = {}
        for source_key, target_key in (
            ("Tire_Diameter", "tire_diameter_cm"),
            ("Tire_Diameter_Rim", "rim_diameter_in"),
            ("Tire_Width", "tire_width_cm"),
        ):
            number_match = re.search(
                rf"{re.escape(source_key)}\s*=\s*({NUMBER_PATTERN.pattern})",
                body,
            )
            if not number_match:
                continue
            value = _to_float(number_match.group(1))
            if value is not None:
                entry[target_key] = round(float(value), 6)
        if entry:
            payload[trim] = entry
    return payload


def _parse_lua_wheel_distance(text: str) -> dict[str, dict[str, float]]:
    pattern = re.compile(
        r"local\s+wheelDistance\s*=\s*\{(?P<body>.*?)\}\s*constants\.WHEEL_DISTANCE\s*=\s*wheelDistance",
        re.S,
    )
    match = pattern.search(text)
    if not match:
        return {}

    body = match.group("body")
    payload: dict[str, dict[str, float]] = {}
    for entry_match in re.finditer(r"([A-Za-z0-9_]+)\s*=\s*\{([^}]*)\}", body):
        trim = _normalize_trim_name(entry_match.group(1))
        numbers = [_to_float(item) for item in NUMBER_PATTERN.findall(entry_match.group(2))]
        if len(numbers) < 2 or any(value is None for value in numbers[:2]):
            continue
        payload[trim] = {
            "front": _round_float(float(numbers[0])),
            "rear": _round_float(float(numbers[1])),
        }
    return payload


def _normalize_module_constants_lua(text: str, *, source_path: Path | None = None) -> dict[str, Any]:
    metadata = _infer_project_metadata(source_path) if source_path else {}
    normalized: dict[str, Any] = {
        "schema": "sg_module_constants",
        **metadata,
    }

    wheelbase = _round_float(_parse_lua_assignment_number(text, "WHEELBASE"))
    if wheelbase is not None:
        normalized["wheelbase_m"] = wheelbase

    suspension_offset = _parse_lua_assignment_vector(text, "SUSPENSION_OFFSET")
    if suspension_offset is not None and len(suspension_offset) >= 3:
        normalized["suspension_offset_m"] = {
            "x": suspension_offset[0],
            "y": suspension_offset[1],
            "z": suspension_offset[2],
        }

    reflection_payload = {
        "car_height_m": _round_float(_parse_lua_assignment_number(text, "CAR_HEIGHT")),
        "car_length_m": _round_float(_parse_lua_assignment_number(text, "CAR_LENGTH")),
        "hood_height_m": _round_float(_parse_lua_assignment_number(text, "HOOD_HEIGHT")),
        "hood_length_m": _round_float(_parse_lua_assignment_number(text, "HOOD_LENGTH")),
        "trunk_height_m": _round_float(_parse_lua_assignment_number(text, "TRUNK_HEIGHT")),
        "trunk_length_m": _round_float(_parse_lua_assignment_number(text, "TRUNK_LENGTH")),
        "x_offset_m": _round_float(_parse_lua_assignment_number(text, "X_OFFSET")),
    }
    reflection_payload = {
        key: value for key, value in reflection_payload.items() if value is not None
    }
    if reflection_payload:
        normalized["reflection"] = reflection_payload

    wheel_sizes = _parse_lua_wheels_sizes(text)
    if wheel_sizes:
        normalized["tire_diameter_cm"] = {
            trim: {
                "front": values["tire_diameter_cm"],
                "rear": values["tire_diameter_cm"],
            }
            for trim, values in wheel_sizes.items()
            if "tire_diameter_cm" in values
        }
        normalized["rim_diameter_in"] = {
            trim: {
                "front": values["rim_diameter_in"],
                "rear": values["rim_diameter_in"],
            }
            for trim, values in wheel_sizes.items()
            if "rim_diameter_in" in values
        }
        normalized["tire_width_cm"] = {
            trim: {
                "front": values["tire_width_cm"],
                "rear": values["tire_width_cm"],
            }
            for trim, values in wheel_sizes.items()
            if "tire_width_cm" in values
        }

    wheel_distance = _parse_lua_wheel_distance(text)
    if wheel_distance:
        normalized["wheel_distance_m"] = wheel_distance

    return normalized


def normalize_constants_payload(data: Any, *, source_path: Path | None = None) -> dict[str, Any]:
    if isinstance(data, dict):
        if {"TRANSFORMS", "SUSPENSION", "REFLECTION"} & set(data):
            return _normalize_pivot_master_payload(data, source_path=source_path)

        for key in ("Pivot_Master", "pivot_master", "constants", "values", "data"):
            if key in data:
                inner = data[key]
                if isinstance(inner, (dict, list)):
                    return normalize_constants_payload(inner, source_path=source_path)
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


def _choose_constants_input(path: Path) -> Path:
    if path.is_file():
        return path
    if not path.exists():
        raise FileNotFoundError(f"Input path does not exist: {path}")

    matches = find_matches(
        path,
        [
            "*Pivot_Master.json",
            "Module_constants_*.lua",
            "*Position_Mapping.json",
            "*.json",
            "*.lua",
        ],
        limit=1,
    )
    if matches:
        return matches[0]
    raise FileNotFoundError(f"No constants input file found under: {path}")


def normalize_constants_source(path: Path) -> dict[str, Any]:
    source_path = _choose_constants_input(path)
    if source_path.suffix.lower() == ".lua":
        text = source_path.read_text(encoding="utf-8", errors="ignore")
        return _normalize_module_constants_lua(text, source_path=source_path)
    return normalize_constants_payload(load_json(source_path), source_path=source_path)
