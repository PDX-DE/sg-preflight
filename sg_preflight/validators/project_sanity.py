from __future__ import annotations

from typing import Any

from sg_preflight.bundle import Bundle
from sg_preflight.models import Finding, PackResult
from sg_preflight.utils import (
    is_under_path,
    looks_like_posix_absolute,
    looks_like_windows_absolute,
    normalize_pathish,
)


def _tokenize_pathish(value: str) -> list[str]:
    normalized = normalize_pathish(value).replace("\\", "/")
    return [segment for segment in normalized.split("/") if segment and segment not in {".", ".."}]


def _looks_like_repo_relative_reference(value: str) -> bool:
    normalized = normalize_pathish(value).replace("\\", "/")
    return normalized.startswith("../") or normalized.startswith("/../")


def _looks_like_project_relative_reference(value: str, top_level_entries: set[str]) -> bool:
    normalized = normalize_pathish(value).replace("\\", "/")
    if not normalized.startswith("/"):
        return False
    segments = [segment for segment in normalized.split("/") if segment]
    if not segments:
        return False
    first = segments[0].lower()
    return first not in {".", ".."} and first in top_level_entries


def _contains_foreign_segment(value: str, current: str, candidates: list[str]) -> str | None:
    current_l = current.lower()
    segments = {segment.lower(): segment for segment in _tokenize_pathish(value)}
    for candidate in candidates:
        if candidate.lower() == current_l:
            continue
        match = segments.get(candidate.lower())
        if match:
            return match
    return None


def _coerce_path_reference(entry: Any) -> dict[str, Any] | None:
    if isinstance(entry, str):
        return {
            "value": entry,
            "source_path": "",
            "line_number": None,
            "line_text": "",
        }
    if not isinstance(entry, dict):
        return None

    value = entry.get("value")
    if not isinstance(value, str) or not value:
        return None

    line_number = entry.get("line_number")
    if not isinstance(line_number, int):
        line_number = None

    return {
        "value": value,
        "source_path": str(entry.get("source_path", "")),
        "line_number": line_number,
        "line_text": str(entry.get("line_text", "")),
    }


def _reference_details(reference: dict[str, Any], **extra: Any) -> dict[str, Any]:
    details: dict[str, Any] = {
        "source_path": reference.get("source_path", ""),
        "line_number": reference.get("line_number"),
        "line_text": reference.get("line_text", ""),
    }
    for key, value in extra.items():
        if value is None or value == "":
            continue
        details[key] = value
    return details


def validate_project_sanity(bundle: Bundle, config: dict[str, Any]) -> PackResult:
    result = PackResult(pack="project_sanity")
    manifest = bundle.project_manifest
    rules = config.get("project_sanity", {})

    if manifest is None:
        result.add(
            Finding(
                pack="project_sanity",
                code="project_sanity.missing_input",
                severity="error",
                message="project_manifest.json is missing from the bundle",
            )
        )
        return result

    project_root = str(manifest.get("project_root", ""))
    raco_version = str(manifest.get("raco_version", ""))
    path_references = manifest.get("path_references", [])
    lua_files = manifest.get("lua_files", [])
    gltf_imports = manifest.get("gltf_imports", [])
    env = manifest.get("env", {})
    report_context = manifest.get("report_context", {})
    identity = manifest.get("project_identity", {})
    current_brand = str(identity.get("brand", ""))
    current_model = str(identity.get("car_model", ""))
    known_brands = [str(value) for value in manifest.get("known_brands", []) if isinstance(value, str)]
    known_models = [str(value) for value in manifest.get("known_models", []) if isinstance(value, str)]
    project_top_level_entries = {
        str(value).lower()
        for value in manifest.get("project_top_level_entries", [])
        if isinstance(value, str)
    }

    if "onedrive" in normalize_pathish(project_root):
        result.add(
            Finding(
                pack="project_sanity",
                code="project_sanity.onedrive_root",
                severity="error",
                message="Project root points into OneDrive, which is unsafe for this workflow",
                location=project_root,
            )
        )

    policy = rules.get("raco_version_policy", {})
    recommended = set(policy.get("recommended", []))
    mode = policy.get("mode", "warn_if_not_recommended")
    if recommended and raco_version not in recommended:
        severity = "warning" if mode == "warn_if_not_recommended" else "error"
        result.add(
            Finding(
                pack="project_sanity",
                code="project_sanity.raco_version_not_recommended",
                severity=severity,
                message=f"RaCo version {raco_version!r} is not in recommended list {sorted(recommended)!r}",
                location="raco_version",
            )
        )

    required_env_vars = rules.get("required_env_vars", [])
    for key in required_env_vars:
        if not env.get(key):
            result.add(
                Finding(
                    pack="project_sanity",
                    code="project_sanity.missing_env_var",
                    severity="warning",
                    message=f"Required environment variable '{key}' is missing or empty in manifest",
                    location=key,
                )
            )

    required_context_fields = rules.get("required_context_fields", [])
    for key in required_context_fields:
        if not isinstance(report_context, dict) or not report_context.get(key):
            result.add(
                Finding(
                    pack="project_sanity",
                    code="project_sanity.missing_report_context",
                    severity="warning",
                    message=(
                        f"Required report context '{key}' is missing; findings will be harder to hand off"
                    ),
                    location=key,
                )
            )

    allowed_abs_prefixes = list(rules.get("allowed_absolute_prefixes", []))
    if project_root:
        allowed_abs_prefixes.append(project_root)
    for value in env.values():
        if isinstance(value, str) and value:
            allowed_abs_prefixes.append(value)

    for raw_reference in path_references:
        reference = _coerce_path_reference(raw_reference)
        if reference is None:
            continue
        raw_path = reference["value"]

        if "onedrive" in normalize_pathish(raw_path):
            result.add(
                Finding(
                    pack="project_sanity",
                    code="project_sanity.onedrive_path",
                    severity="error",
                    message="Reference points into OneDrive",
                    location=raw_path,
                    details=_reference_details(reference),
                )
            )

        if _looks_like_repo_relative_reference(raw_path):
            foreign_brand = _contains_foreign_segment(raw_path, current_brand, known_brands)
            if foreign_brand is not None:
                result.add(
                    Finding(
                        pack="project_sanity",
                        code="project_sanity.cross_brand_reference",
                        severity="warning",
                        message=(
                            f"Reference points to another brand ({foreign_brand}) instead of "
                            f"the current brand {current_brand or '<unknown>'}"
                        ),
                        location=raw_path,
                        details=_reference_details(reference, matched_brand=foreign_brand),
                    )
                )

            foreign_model = _contains_foreign_segment(raw_path, current_model, known_models)
            if foreign_model is not None:
                result.add(
                    Finding(
                        pack="project_sanity",
                        code="project_sanity.cross_car_reference",
                        severity="warning",
                        message=(
                            f"Reference points to another car model ({foreign_model}) instead of "
                            f"the current car {current_model or '<unknown>'}"
                        ),
                        location=raw_path,
                        details=_reference_details(reference, matched_model=foreign_model),
                    )
                )
            continue

        if _looks_like_project_relative_reference(raw_path, project_top_level_entries):
            continue

        is_absolute = looks_like_windows_absolute(raw_path) or looks_like_posix_absolute(raw_path)
        if is_absolute:
            allowed = any(is_under_path(raw_path, prefix) for prefix in allowed_abs_prefixes if prefix)
            if not allowed:
                result.add(
                    Finding(
                        pack="project_sanity",
                        code="project_sanity.suspicious_absolute_path",
                        severity="warning",
                        message="Absolute path is outside allowed project roots",
                        location=raw_path,
                        details=_reference_details(reference),
                    )
                )

    for lua_file in lua_files:
        if isinstance(lua_file, dict) and lua_file.get("referenced") is False:
            result.add(
                Finding(
                    pack="project_sanity",
                    code="project_sanity.unused_lua",
                    severity="warning",
                    message="Lua file is present but not referenced",
                    location=str(lua_file.get("path", "<unknown-lua>")),
                    details={
                        "source_path": str(lua_file.get("source_path", "")),
                        "referenced_by": list(lua_file.get("referenced_by", []))
                        if isinstance(lua_file.get("referenced_by"), list)
                        else [],
                    },
                )
            )

    for item in gltf_imports:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "<unnamed-import>"))
        previous = item.get("previous_objects", [])
        current = item.get("current_objects", [])

        if not isinstance(previous, list) or not isinstance(current, list):
            continue

        if len(previous) != len(current):
            result.add(
                Finding(
                    pack="project_sanity",
                    code="project_sanity.gltf_topology_drift",
                    severity="warning",
                    message=(
                        f"Object count changed from {len(previous)} to {len(current)}; "
                        "hot reload stability may be affected"
                    ),
                    location=name,
                )
            )

        if previous != current:
            prev_set = set(previous)
            curr_set = set(current)
            if prev_set == curr_set:
                result.add(
                    Finding(
                        pack="project_sanity",
                        code="project_sanity.gltf_reorder",
                        severity="warning",
                        message="Object order changed even though object set stayed the same",
                        location=name,
                    )
                )
            else:
                added = sorted(curr_set - prev_set)
                removed = sorted(prev_set - curr_set)
                result.add(
                    Finding(
                        pack="project_sanity",
                        code="project_sanity.gltf_object_set_changed",
                        severity="warning",
                        message=(
                            f"Import object set changed. Added={added!r}, removed={removed!r}"
                        ),
                        location=name,
                    )
                )

    return result
