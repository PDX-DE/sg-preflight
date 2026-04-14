from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sg_preflight.adapters.common import find_matches, walk_dirs


DISCOVERY_PATTERNS = {
    "read_json_carpaints": ["read_json_carpaints.py"],
    "carpaint_json": ["*carpaint*.json", "*paint*.json"],
    "carpaint_workbooks": ["*carpaint*.xlsx", "*paint*.xlsx"],
    "carpaint_helpers": ["carpaint_jsonifier.py"],
    "carmodel_data": ["carmodel_data.json"],
    "resource_mappings": ["resource_mappings.json", "resource_list.json"],
    "pivot_scripts": ["*pivots_json.py", "pivot_json.py"],
    "constants_dirs": ["*/constants/scripts", "*pivot*master*"],
    "helper_scripts": [
        "test_absolute_paths.py",
        "test_ucap_ign*.py",
        "test_unused_lu*.py",
        "test_unnused_lu*.py",
        "disable_msaa*.py",
        "debug_*.py",
        "*perspectivetraceplayer*",
        "*traceplayer*",
    ],
    "anchor_inputs": ["*anchor*.json", "*hierarchy*.json", "*scene*.json"],
}


def default_search_roots() -> list[Path]:
    raw_candidates = [
        os.environ.get("SG_REPO"),
        os.environ.get("SP_REPO"),
        os.environ.get("SG_CARMODELS_REPO"),
        r"C:\repos",
        r"C:\repositories",
        r"D:\repos",
        r"D:\repositories",
        r"E:\repos",
        r"E:\repositories",
    ]

    roots: list[Path] = []
    seen: set[str] = set()
    for raw in raw_candidates:
        if not raw:
            continue
        path = Path(raw)
        key = str(path).lower()
        if key in seen or not path.exists():
            continue
        seen.add(key)
        roots.append(path)
    return roots


def _candidate_markers(path: Path) -> dict[str, bool]:
    cars_dir = (path / "Cars").is_dir()
    pdx_dir = (path / ".pdx").is_dir()
    bmw_shared = (path / "Cars" / "BMW" / "_Shared").is_dir()
    mini_root = (path / "Cars" / "MINI").is_dir()
    return {
        "cars_dir": cars_dir,
        "pdx_dir": pdx_dir,
        "bmw_shared": bmw_shared,
        "mini_root": mini_root,
    }


def _candidate_score(markers: dict[str, bool]) -> int:
    return (
        (3 if markers["cars_dir"] else 0)
        + (3 if markers["pdx_dir"] else 0)
        + (1 if markers["bmw_shared"] else 0)
        + (1 if markers["mini_root"] else 0)
    )


def _list_project_roots(root: Path, limit: int = 12) -> list[str]:
    project_paths: list[str] = []
    for brand in ("BMW", "MINI"):
        brand_root = root / "Cars" / brand
        if not brand_root.is_dir():
            continue
        for child in sorted(brand_root.iterdir()):
            if not child.is_dir() or child.name.startswith("_"):
                continue
            project_paths.append(str(child.resolve()))
            if len(project_paths) >= limit:
                return project_paths
    return project_paths


def _inspect_candidate(root: Path) -> dict[str, Any]:
    markers = _candidate_markers(root)
    report: dict[str, Any] = {
        "path": str(root.resolve()),
        "score": _candidate_score(markers),
        "markers": markers,
        "project_roots": _list_project_roots(root),
        "known_assets": {},
    }

    for key, patterns in DISCOVERY_PATTERNS.items():
        matches = find_matches(
            root,
            patterns,
            include_dirs=(key == "constants_dirs"),
            limit=12,
        )
        report["known_assets"][key] = [str(path.resolve()) for path in matches]

    return report


def probe_workspace(search_roots: list[Path] | None = None) -> dict[str, Any]:
    roots = search_roots or default_search_roots()
    repo_candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    for search_root in roots:
        for path in walk_dirs(search_root, max_depth=4):
            markers = _candidate_markers(path)
            score = _candidate_score(markers)
            if score < 6:
                continue
            key = str(path.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            repo_candidates.append(_inspect_candidate(path))

    repo_candidates.sort(key=lambda item: (-int(item["score"]), item["path"]))
    return {
        "search_roots": [str(path.resolve()) for path in roots],
        "repo_candidates": repo_candidates,
    }
