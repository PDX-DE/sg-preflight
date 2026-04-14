from __future__ import annotations

import json
import os
import re
import zipfile
from pathlib import Path
from typing import Any, Mapping

from sg_preflight.adapters.common import (
    TEXT_SUFFIXES,
    find_matches,
    load_json,
    to_display_path,
    walk_files,
)


WINDOWS_PATH_PATTERN = re.compile(r"[A-Za-z]:[\\/][^\s\"'\r\n]+")
POSIX_PATH_PATTERN = re.compile(r"(?<![A-Za-z0-9])(/[A-Za-z0-9._-][A-Za-z0-9._/@%+,:=~-]*)")
RELATIVE_REPO_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(/?(?:\.\.[\\/])+[A-Za-z0-9._-][A-Za-z0-9._/@%+,:=~\\-]*)"
)
URL_PATTERN = re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]*://[^\s)>\"]+")
MARKDOWN_INLINE_LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
RACO_VERSION_PATTERN = re.compile(r"\b(\d+\.\d+\.\d+)\b")
KNOWN_ASSET_PATTERNS = [
    "read_json_carpaints.py",
    "carpaint_jsonifier.py",
    "*carpaint*.xlsx",
    "*paint*.xlsx",
    "carmodel_data.json",
    "resource_mappings.json",
    "resource_list.json",
    "*pivots_json.py",
    "pivot_json.py",
    "*pivot_master.json",
    "*position_mapping.json",
    "module_constants_*.lua",
    "test_absolute_paths.py",
    "test_absolute_path.py",
    "test_ucap_ign*.py",
    "test_ucap_ignore.py",
    "test_unused_lu*.py",
    "test_unused_lua_files.py",
    "test_unnused_lu*.py",
    "disable_msaa*.py",
    "debug_*.py",
    "check_scenes.py",
    "*perspectivetraceplayer*",
    "*traceplayer*",
]


def _clean_path_token(token: str) -> str:
    return token.rstrip(".,;:)]}>'\"")


def _strip_urls_and_markdown_links(text: str) -> str:
    sanitized = URL_PATTERN.sub(" ", text)
    sanitized = MARKDOWN_INLINE_LINK_PATTERN.sub(" ", sanitized)
    return sanitized


def _extract_absolute_paths(text: str) -> list[str]:
    sanitized = _strip_urls_and_markdown_links(text)
    paths = {_clean_path_token(match.group(0)) for match in WINDOWS_PATH_PATTERN.finditer(sanitized)}
    for match in POSIX_PATH_PATTERN.finditer(sanitized):
        value = _clean_path_token(match.group(1))
        if value.startswith("//"):
            continue
        first_segment = value.split("/", 2)[1] if value.startswith("/") and "/" in value[1:] else ""
        if value in {"/.", "/.."} or first_segment in {".", ".."}:
            continue
        if value.count("/") == 1 and "." not in value.rsplit("/", 1)[-1]:
            continue
        paths.add(value)
    return sorted(path for path in paths if path)


def _extract_relative_repo_paths(text: str) -> list[str]:
    sanitized = _strip_urls_and_markdown_links(text)
    paths = {_clean_path_token(match.group(1)) for match in RELATIVE_REPO_PATH_PATTERN.finditer(sanitized)}
    return sorted(path for path in paths if path)


def _read_rca_json_text(path: Path) -> str | None:
    try:
        if not zipfile.is_zipfile(path):
            return None
        with zipfile.ZipFile(path) as archive:
            json_members = [name for name in archive.namelist() if name.lower().endswith(".json")]
            if not json_members:
                return None
            return archive.read(json_members[0]).decode("utf-8", errors="ignore")
    except (OSError, zipfile.BadZipFile):
        return None


def _load_rca_json(path: Path) -> Any | None:
    payload = _read_rca_json_text(path)
    if payload is None:
        return None
    try:
        return json.loads(payload)
    except ValueError:
        return None


def _load_text_index(roots: list[Path]) -> list[tuple[Path, str]]:
    index: list[tuple[Path, str]] = []
    seen: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            paths = [root]
        else:
            paths = list(walk_files(root, suffixes=TEXT_SUFFIXES))
        for path in paths:
            key = str(path.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            try:
                if path.suffix.lower() == ".rca":
                    text = _read_rca_json_text(path)
                    if text is None:
                        continue
                else:
                    text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            index.append((path, text))
    return index


def _discover_known_assets(repo_root: Path) -> list[Path]:
    return find_matches(repo_root, KNOWN_ASSET_PATTERNS, limit=40)


def _collect_path_references(project_root: Path, repo_root: Path) -> list[str]:
    del repo_root
    references: set[str] = set()
    for _path, text in _load_text_index([project_root]):
        references.update(_extract_absolute_paths(text))
        references.update(_extract_relative_repo_paths(text))
    return sorted(references)


def _collect_lua_files(project_root: Path) -> list[dict[str, Any]]:
    text_index = _load_text_index([project_root])
    lowered_texts = [(path, text.lower()) for path, text in text_index]
    lua_files = []

    for path in walk_files(project_root, suffixes={".lua"}):
        relative = to_display_path(path, project_root).replace("\\", "/")
        relative_l = relative.lower()
        name_l = path.name.lower()
        referenced = any(
            other_path.resolve() != path.resolve()
            and (relative_l in text or name_l in text)
            for other_path, text in lowered_texts
        )
        lua_files.append({"path": relative, "referenced": referenced})

    lua_files.sort(key=lambda item: item["path"])
    return lua_files


def _detect_raco_version(project_root: Path, repo_root: Path, explicit: str | None) -> str:
    if explicit:
        return explicit

    env_value = os.environ.get("RACO_VERSION")
    if env_value:
        return env_value

    candidate_files = find_matches(
        repo_root,
        ["raco_version.txt", ".raco-version", "*raco*version*.txt", "*raco*version*.json"],
        limit=5,
    )
    for path in candidate_files:
        try:
            if path.suffix.lower() == ".json":
                data = load_json(path)
                if isinstance(data, dict):
                    value = data.get("version") or data.get("raco_version")
                    if isinstance(value, str) and value:
                        return value
            else:
                text = path.read_text(encoding="utf-8", errors="ignore")
                match = RACO_VERSION_PATTERN.search(text)
                if match:
                    return match.group(1)
        except OSError:
            continue

    rca_candidates = find_matches(project_root, ["*.rca"], limit=5)
    for path in rca_candidates:
        data = _load_rca_json(path)
        if isinstance(data, dict):
            version = data.get("racoVersion")
            if isinstance(version, list) and all(isinstance(item, int) for item in version):
                return ".".join(str(item) for item in version)
            if isinstance(version, str) and version:
                return version

    return ""


def _infer_project_identity(project_root: Path) -> dict[str, str]:
    parts = list(project_root.resolve().parts)
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


def _discover_repo_catalog(repo_root: Path, identity: Mapping[str, str]) -> tuple[list[str], list[str]]:
    generation = identity.get("generation")
    brand = identity.get("brand")
    if not generation or not brand:
        return [], []

    generation_root = repo_root / generation
    known_brands: list[str] = []
    if generation_root.exists():
        try:
            known_brands = sorted(
                path.name
                for path in generation_root.iterdir()
                if path.is_dir() and not path.name.startswith("_")
            )
        except OSError:
            known_brands = []

    brand_root = generation_root / brand
    known_models: list[str] = []
    if brand_root.exists():
        try:
            known_models = sorted(
                path.name
                for path in brand_root.iterdir()
                if path.is_dir() and not path.name.startswith("_")
            )
        except OSError:
            known_models = []

    return known_brands, known_models


def _discover_project_top_level_entries(project_root: Path) -> list[str]:
    if not project_root.exists():
        return []
    try:
        entries: set[str] = set()
        for path in project_root.iterdir():
            entries.add(path.name)
            if not path.is_dir():
                continue
            try:
                for child in path.iterdir():
                    if child.is_dir():
                        entries.add(child.name)
            except OSError:
                continue
        return sorted(entries)
    except OSError:
        return []


def _load_gltf_snapshot(path: Path) -> list[str]:
    data = load_json(path)
    if isinstance(data, list):
        values = data
    elif isinstance(data, dict):
        for key in ("objects", "nodes", "current_objects", "previous_objects"):
            if isinstance(data.get(key), list):
                values = data[key]
                break
        else:
            values = []
    else:
        values = []

    objects = []
    for value in values:
        if isinstance(value, str):
            objects.append(value)
        elif isinstance(value, dict):
            name = value.get("name") or value.get("id")
            if isinstance(name, str):
                objects.append(name)
    return objects


def _build_env_payload(overrides: Mapping[str, str] | None) -> dict[str, str]:
    required = [
        "SG_REPO",
        "SP_REPO",
        "SG_CARMODELS_REPO",
        "SG-Repo",
        "SG-CarModels-Repo",
    ]
    payload = {key: os.environ.get(key, "") for key in required}

    if payload["SG_REPO"] and not payload["SG-Repo"]:
        payload["SG-Repo"] = payload["SG_REPO"]
    if payload["SG-Repo"] and not payload["SG_REPO"]:
        payload["SG_REPO"] = payload["SG-Repo"]

    if payload["SG_CARMODELS_REPO"] and not payload["SG-CarModels-Repo"]:
        payload["SG-CarModels-Repo"] = payload["SG_CARMODELS_REPO"]
    if payload["SG-CarModels-Repo"] and not payload["SG_CARMODELS_REPO"]:
        payload["SG_CARMODELS_REPO"] = payload["SG-CarModels-Repo"]

    if overrides:
        payload.update({key: value for key, value in overrides.items() if value is not None})
    return payload


def _build_report_context_payload(overrides: Mapping[str, str] | None) -> dict[str, str]:
    if not overrides:
        return {}
    return {
        key: value
        for key, value in overrides.items()
        if key and value is not None and str(value).strip()
    }


def build_project_manifest(
    *,
    repo_root: Path,
    project_root: Path,
    env: Mapping[str, str] | None = None,
    report_context: Mapping[str, str] | None = None,
    workflow_contract: Mapping[str, Any] | None = None,
    raco_version: str | None = None,
    gltf_name: str | None = None,
    gltf_previous_path: Path | None = None,
    gltf_current_path: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    project_root = project_root.resolve()
    gltf_imports: list[dict[str, Any]] = []
    project_identity = _infer_project_identity(project_root)
    known_brands, known_models = _discover_repo_catalog(repo_root, project_identity)
    project_top_level_entries = _discover_project_top_level_entries(project_root)

    if gltf_previous_path and gltf_current_path:
        gltf_imports.append(
            {
                "name": gltf_name or "gltf_import",
                "previous_objects": _load_gltf_snapshot(gltf_previous_path.resolve()),
                "current_objects": _load_gltf_snapshot(gltf_current_path.resolve()),
            }
        )

    known_assets = _discover_known_assets(repo_root)
    return {
        "project_root": str(project_root),
        "repo_root": str(repo_root),
        "raco_version": _detect_raco_version(project_root, repo_root, raco_version),
        "path_references": _collect_path_references(project_root, repo_root),
        "lua_files": _collect_lua_files(project_root),
        "gltf_imports": gltf_imports,
        "env": _build_env_payload(env),
        "report_context": _build_report_context_payload(report_context),
        "workflow_contract": dict(workflow_contract) if workflow_contract else {},
        "project_identity": project_identity,
        "known_brands": known_brands,
        "known_models": known_models,
        "project_top_level_entries": project_top_level_entries,
        "discovered_assets": [str(path.resolve()) for path in known_assets],
    }
