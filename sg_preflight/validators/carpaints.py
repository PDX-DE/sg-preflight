from __future__ import annotations

from typing import Any

from sg_preflight.bundle import Bundle
from sg_preflight.models import Finding, PackResult
from sg_preflight.utils import is_number


def _coerce_entries(data: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        items = data.get("carpaints")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def validate_carpaints(bundle: Bundle, config: dict[str, Any]) -> PackResult:
    result = PackResult(pack="carpaints")
    payload = bundle.carpaints
    rules = config.get("carpaints", {})

    if payload is None:
        result.add(
            Finding(
                pack="carpaints",
                code="carpaints.missing_input",
                severity="error",
                message="carpaints.json is missing from the bundle",
            )
        )
        return result

    entries = _coerce_entries(payload)
    if not entries:
        result.add(
            Finding(
                pack="carpaints",
                code="carpaints.empty",
                severity="error",
                message="No carpaint entries were found",
            )
        )
        return result

    required_keys = set(rules.get("required_keys", []))
    allowed_finish = set(rules.get("allowed_finish", []))
    unique_indexes: dict[str, dict[Any, int]] = {
        key: {} for key in rules.get("unique_keys", [])
    }

    for idx, entry in enumerate(entries):
        name = entry.get("name", f"<entry-{idx}>")
        location = f"carpaint[{idx}]::{name}"

        missing = sorted(key for key in required_keys if key not in entry)
        for key in missing:
            result.add(
                Finding(
                    pack="carpaints",
                    code="carpaints.missing_key",
                    severity="error",
                    message=f"Missing required key '{key}'",
                    location=location,
                )
            )

        for key in rules.get("unique_keys", []):
            value = entry.get(key)
            if value in unique_indexes[key]:
                result.add(
                    Finding(
                        pack="carpaints",
                        code="carpaints.duplicate_unique_value",
                        severity="error",
                        message=f"Duplicate value for unique key '{key}': {value!r}",
                        location=location,
                    )
                )
            else:
                unique_indexes[key][value] = idx

        finish = entry.get("finish")
        if finish is not None and allowed_finish and finish not in allowed_finish:
            result.add(
                Finding(
                    pack="carpaints",
                    code="carpaints.invalid_finish",
                    severity="error",
                    message=f"Unsupported finish type: {finish!r}",
                    location=location,
                )
            )

        for key, (min_value, max_value) in rules.get("ranges", {}).items():
            if key not in entry:
                continue
            value = entry[key]
            if not is_number(value):
                result.add(
                    Finding(
                        pack="carpaints",
                        code="carpaints.not_numeric",
                        severity="error",
                        message=f"Field '{key}' must be numeric",
                        location=location,
                    )
                )
                continue
            if not (float(min_value) <= float(value) <= float(max_value)):
                result.add(
                    Finding(
                        pack="carpaints",
                        code="carpaints.out_of_range",
                        severity="error",
                        message=(
                            f"Field '{key}'={value!r} is outside range [{min_value}, {max_value}]"
                        ),
                        location=location,
                    )
                )

        for key, expected_len in rules.get("array_lengths", {}).items():
            if key not in entry:
                continue
            value = entry[key]
            if not isinstance(value, list) or len(value) != int(expected_len):
                result.add(
                    Finding(
                        pack="carpaints",
                        code="carpaints.invalid_array_length",
                        severity="error",
                        message=f"Field '{key}' must be a list of length {expected_len}",
                        location=location,
                    )
                )
                continue
            for component in value:
                if not is_number(component) or not (0.0 <= float(component) <= 1.0):
                    result.add(
                        Finding(
                            pack="carpaints",
                            code="carpaints.invalid_color_component",
                            severity="error",
                            message=(
                                f"Field '{key}' contains a non-normalized component {component!r}"
                            ),
                            location=location,
                        )
                    )
                    break

        roughness = entry.get("roughness")
        metallic = entry.get("metallic")

        if finish == "matte" and is_number(roughness) and float(roughness) < 0.5:
            result.add(
                Finding(
                    pack="carpaints",
                    code="carpaints.semantic_warning",
                    severity="warning",
                    message="Matte finish with very low roughness looks suspicious",
                    location=location,
                )
            )

        if finish == "metallic" and is_number(metallic) and float(metallic) < 0.5:
            result.add(
                Finding(
                    pack="carpaints",
                    code="carpaints.semantic_warning",
                    severity="warning",
                    message="Metallic finish with low metallic value looks suspicious",
                    location=location,
                )
            )

    return result
