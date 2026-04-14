from __future__ import annotations

from typing import Any

from sg_preflight.bundle import Bundle
from sg_preflight.models import Finding, PackResult
from sg_preflight.utils import get_by_path, is_number


def _safe_get(data: dict[str, Any], path: str) -> tuple[bool, Any]:
    try:
        return True, get_by_path(data, path)
    except KeyError:
        return False, None


def validate_constants(bundle: Bundle, config: dict[str, Any]) -> PackResult:
    result = PackResult(pack="constants")
    expected = bundle.constants_expected
    exported = bundle.constants_exported
    rules = config.get("constants", {})

    if expected is None:
        result.add(
            Finding(
                pack="constants",
                code="constants.missing_expected_input",
                severity="error",
                message="constants_expected.json is missing from the bundle",
            )
        )
        return result

    if exported is None:
        result.add(
            Finding(
                pack="constants",
                code="constants.missing_exported_input",
                severity="error",
                message="constants_exported.json is missing from the bundle",
            )
        )
        return result

    for item in rules.get("numeric_paths", []):
        path = item["path"]
        tolerance = float(item.get("tolerance", 0.0))

        ok_expected, expected_value = _safe_get(expected, path)
        ok_exported, exported_value = _safe_get(exported, path)

        if not ok_expected:
            result.add(
                Finding(
                    pack="constants",
                    code="constants.expected_key_missing",
                    severity="error",
                    message="Required numeric key is missing from expected constants",
                    location=path,
                )
            )
            continue

        if not ok_exported:
            result.add(
                Finding(
                    pack="constants",
                    code="constants.exported_key_missing",
                    severity="error",
                    message="Required numeric key is missing from exported constants",
                    location=path,
                )
            )
            continue

        if not is_number(expected_value):
            result.add(
                Finding(
                    pack="constants",
                    code="constants.expected_not_numeric",
                    severity="error",
                    message=f"Expected value is not numeric: {expected_value!r}",
                    location=path,
                )
            )
            continue

        if not is_number(exported_value):
            result.add(
                Finding(
                    pack="constants",
                    code="constants.exported_not_numeric",
                    severity="error",
                    message=f"Exported value is not numeric: {exported_value!r}",
                    location=path,
                )
            )
            continue

        delta = abs(float(expected_value) - float(exported_value))
        if delta > tolerance:
            result.add(
                Finding(
                    pack="constants",
                    code="constants.out_of_tolerance",
                    severity="error",
                    message=(
                        f"Value differs by {delta:.3f}, which is above tolerance {tolerance:.3f}"
                    ),
                    location=path,
                    details={"expected": expected_value, "exported": exported_value, "delta": delta},
                )
            )

    for item in rules.get("exact_paths", []):
        path = item["path"]
        ok_expected, expected_value = _safe_get(expected, path)
        ok_exported, exported_value = _safe_get(exported, path)

        if not ok_expected:
            result.add(
                Finding(
                    pack="constants",
                    code="constants.expected_key_missing",
                    severity="error",
                    message="Required exact-match key is missing from expected constants",
                    location=path,
                )
            )
            continue

        if not ok_exported:
            result.add(
                Finding(
                    pack="constants",
                    code="constants.exported_key_missing",
                    severity="error",
                    message="Required exact-match key is missing from exported constants",
                    location=path,
                )
            )
            continue

        if expected_value != exported_value:
            result.add(
                Finding(
                    pack="constants",
                    code="constants.exact_mismatch",
                    severity="error",
                    message=(
                        f"Expected {expected_value!r} but exported {exported_value!r}"
                    ),
                    location=path,
                )
            )

    return result
