from __future__ import annotations

import os
import re
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
    "test_absolute_paths.py",
    "test_ucap_ign*.py",
    "test_unused_lu*.py",
    "test_unnused_lu*.py",
    "disable_msaa*.py",
    "debug_*.py",
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
        if value.count("/") == 1 and "." not in value.rsplit("/", 1)[-1]:
            continue
        paths.add(value)
    return sorted(path for path in paths if path)


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

    return ""


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
    required = ["SG_REPO", "SP_REPO", "SG_CARMODELS_REPO"]
    payload = {key: os.environ.get(key, "") for key in required}
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
        "discovered_assets": [str(path.resolve()) for path in known_assets],
    }
