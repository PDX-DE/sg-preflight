from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any

from sg_preflight.bmw_delivery import candidate_bmw_profile_ids, discover_bmw_models_repo


BMW_GIT_READINESS_BANNER = (
    "BMW Git per-profile readiness is read-only from the local digital-3d-car-models clone. "
    "SGFX does not write to BMW Git or fetch from the remote."
)
_NOTE = "Read-only BMW Git per-profile readiness surface. SGFX does not write to BMW Git or fetch from the remote."
_BRANDS = ("BMW", "MINI")


def _empty_commit() -> dict[str, str]:
    return {"sha": "", "short_sha": "", "author": "", "author_date": "", "subject": ""}


def _latest_bmw_commit(repo_root: Path, relative_path: str) -> dict[str, str]:
    if not repo_root.exists() or not (repo_root / ".git").exists():
        return _empty_commit()
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "log",
                "-1",
                "--format=%H%x1f%h%x1f%an%x1f%ai%x1f%s",
                "--",
                relative_path,
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return _empty_commit()
    if result.returncode != 0 or not result.stdout.strip():
        return _empty_commit()
    parts = result.stdout.strip().split("\x1f", 4)
    while len(parts) < 5:
        parts.append("")
    return {
        "sha": parts[0],
        "short_sha": parts[1],
        "author": parts[2],
        "author_date": parts[3],
        "subject": parts[4],
    }


def _resolve_car_root(repo_root: Path, profile_id: str) -> tuple[str, str, Path]:
    candidates = candidate_bmw_profile_ids(profile_id)
    for brand in _BRANDS:
        brand_root = repo_root / "cars" / brand
        for candidate in candidates:
            car_root = brand_root / candidate
            if car_root.exists():
                return brand, candidate, car_root
    matched = candidates[0] if candidates else profile_id.strip()
    return "BMW", matched, repo_root / "cars" / "BMW" / matched


def _path_present(path: Path | None) -> bool:
    return path is not None and path.exists()


def _path_text(path: Path | None) -> str:
    return str(path) if _path_present(path) else ""


def _find_readme(car_root: Path, brand_root: Path, matched_profile: str) -> Path | None:
    candidates = [
        car_root / "README.md",
        car_root / f"README_{matched_profile}.md",
        brand_root / "README_IDCevo.md",
    ]
    stripped = matched_profile[:-4] if matched_profile.endswith("_EVO") else matched_profile
    if stripped != matched_profile:
        candidates.append(car_root / f"README_{stripped}.md")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _find_main_scene(car_root: Path, matched_profile: str) -> Path | None:
    main_root = car_root / "main"
    stripped = matched_profile[:-4] if matched_profile.endswith("_EVO") else matched_profile
    candidates = [
        main_root / f"Main_{matched_profile}.rca",
        main_root / f"Main_{stripped}.rca",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    matches = sorted(main_root.glob("*.rca")) if main_root.exists() else []
    return matches[0] if matches else None


def _find_test_config(car_root: Path) -> Path | None:
    tests_root = car_root / "export" / "tests"
    candidates = [
        tests_root / "test_config.lua",
        tests_root / "test_config_tmp.lua",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    matches = sorted(tests_root.glob("test_config*.lua")) if tests_root.exists() else []
    return matches[0] if matches else None


def _first_perspective(car_root: Path) -> Path | None:
    matches = sorted(car_root.glob("perspectives_*.json")) if car_root.exists() else []
    return matches[0] if matches else None


def _check_item(key: str, label: str, present: bool, path: Path | str | None = "") -> dict[str, str]:
    path_text = str(path) if path else ""
    return {
        "key": key,
        "label": label,
        "status": "present" if present else "missing",
        "path": path_text,
    }


def _base_payload(
    profile_id: str,
    *,
    repo_root: Path,
    brand: str,
    matched_profile: str,
    car_root: Path,
    status: str,
    summary: str,
    readiness_checks: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    checks = readiness_checks or []
    available = sum(1 for item in checks if item.get("status") == "present")
    return {
        "profile_id": profile_id.strip(),
        "matched_profile_id": matched_profile,
        "brand": brand,
        "status": status,
        "data_available": status == "available",
        "repo_root": str(repo_root) if repo_root.exists() else "",
        "profile_path": str(car_root) if car_root.exists() else "",
        "latest_commit": _empty_commit(),
        "readme_present": False,
        "workfiles_present": False,
        "main_scene_path": "",
        "main_scene_present": False,
        "test_config_present": False,
        "perspectives_present": False,
        "changelog_present": False,
        "lids_json_present": False,
        "readiness_checks": checks,
        "available_check_count": available,
        "check_count": len(checks),
        "summary": summary,
        "note": _NOTE,
        "is_approval": False,
    }


def read_bmw_git_readiness(
    profile_id: str,
    *,
    workspace: Path | str | None = None,
    bmw_root: Path | str | None = None,
) -> dict[str, Any]:
    workspace_path = Path(workspace).resolve() if workspace is not None else None
    repo_root = Path(bmw_root).resolve() if bmw_root is not None else discover_bmw_models_repo(workspace_path).resolve()
    requested = profile_id.strip()
    brand, matched_profile, car_root = _resolve_car_root(repo_root, requested)
    if not repo_root.exists():
        return _base_payload(
            requested,
            repo_root=repo_root,
            brand=brand,
            matched_profile=matched_profile,
            car_root=car_root,
            status="no_bmw_root",
            summary=f"BMW Git readiness unavailable: digital-3d-car-models root not found at {repo_root}.",
        )
    if not (repo_root / ".git").exists():
        return _base_payload(
            requested,
            repo_root=repo_root,
            brand=brand,
            matched_profile=matched_profile,
            car_root=car_root,
            status="git_unreadable",
            summary=f"BMW Git readiness unavailable: {repo_root} is not a readable Git checkout.",
        )
    if not car_root.exists():
        return _base_payload(
            requested,
            repo_root=repo_root,
            brand=brand,
            matched_profile=matched_profile,
            car_root=car_root,
            status="no_profile_folder",
            summary=f"BMW Git readiness unavailable: profile folder not found for {requested or 'profile'}.",
        )

    brand_root = repo_root / "cars" / brand
    relative_profile_path = f"cars/{brand}/{matched_profile}"
    latest_commit = _latest_bmw_commit(repo_root, relative_profile_path)
    readme_path = _find_readme(car_root, brand_root, matched_profile)
    workfiles_root = car_root / "_Workfiles"
    main_scene = _find_main_scene(car_root, matched_profile)
    test_config = _find_test_config(car_root)
    perspective = _first_perspective(car_root)
    changelog = car_root / "CHANGELOG.md"
    lids_json = car_root / "lids.json"

    readiness_checks = [
        _check_item("profile_folder", "Profile folder", True, car_root),
        _check_item("latest_commit", "Latest profile commit", bool(latest_commit["sha"]), latest_commit["short_sha"]),
        _check_item("readme", "README", _path_present(readme_path), readme_path),
        _check_item("workfiles", "_Workfiles", workfiles_root.exists(), workfiles_root),
        _check_item("main_scene", "Main scene", _path_present(main_scene), main_scene),
        _check_item("test_config", "Screenshot test config", _path_present(test_config), test_config),
        _check_item("perspectives", "Perspectives JSON", _path_present(perspective), perspective),
        _check_item("changelog", "Changelog", changelog.exists(), changelog),
        _check_item("lids_json", "lids.json", lids_json.exists(), lids_json),
    ]
    available = sum(1 for item in readiness_checks if item["status"] == "present")
    commit_suffix = ""
    if latest_commit["short_sha"]:
        author = latest_commit["author"]
        date_text = latest_commit["author_date"]
        commit_suffix = f"; latest commit {latest_commit['short_sha']}"
        if author:
            commit_suffix += f" by {author}"
        if date_text:
            commit_suffix += f" on {date_text}"
    summary = f"{matched_profile} readiness: {available} of {len(readiness_checks)} checks present{commit_suffix}."
    payload = _base_payload(
        requested,
        repo_root=repo_root,
        brand=brand,
        matched_profile=matched_profile,
        car_root=car_root,
        status="available",
        summary=summary,
        readiness_checks=readiness_checks,
    )
    payload.update(
        {
            "latest_commit": latest_commit,
            "readme_present": _path_present(readme_path),
            "workfiles_present": workfiles_root.exists(),
            "main_scene_path": _path_text(main_scene),
            "main_scene_present": _path_present(main_scene),
            "test_config_present": _path_present(test_config),
            "perspectives_present": _path_present(perspective),
            "changelog_present": changelog.exists(),
            "lids_json_present": lids_json.exists(),
            "available_check_count": available,
            "check_count": len(readiness_checks),
        }
    )
    return payload


def read_bmw_git_readiness_for_profiles(
    profile_ids: list[str] | tuple[str, ...],
    *,
    workspace: Path | str | None = None,
    bmw_root: Path | str | None = None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for profile_id in profile_ids:
        profile = str(profile_id).strip()
        if not profile or profile.casefold() in seen:
            continue
        seen.add(profile.casefold())
        items.append(read_bmw_git_readiness(profile, workspace=workspace, bmw_root=bmw_root))
    return items


def bmw_git_readiness_digest_items(state: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = state.get("bmw_git_readiness", [])
    if isinstance(raw_items, dict):
        raw_items = [raw_items]
    if not isinstance(raw_items, list):
        return []
    items: list[dict[str, Any]] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        profile = str(raw_item.get("matched_profile_id") or raw_item.get("profile_id") or "profile").strip()
        available = int(raw_item.get("available_check_count", 0) or 0)
        total = int(raw_item.get("check_count", 0) or 0)
        detail = str(raw_item.get("summary", "")).strip() or f"{available} of {total} readiness checks present."
        items.append(
            {
                "label": f"BMW Git readiness {profile}",
                "status": "prepared" if raw_item.get("data_available") else str(raw_item.get("status", "not_available")),
                "detail": detail,
                "source": "bmw_git_readiness",
                "path": str(raw_item.get("profile_path", "") or raw_item.get("repo_root", "")).strip(),
                "note": str(raw_item.get("note", _NOTE)).strip(),
                "guidance": "Read-only BMW Git context only; manual review and delivery ownership remain required.",
                "is_approval": False,
            }
        )
    return items


def _check_summary_line(item: dict[str, str]) -> str:
    label = item.get("label", "check")
    status = item.get("status", "missing")
    path = item.get("path", "")
    suffix = f" - `{path}`" if path and status == "present" else ""
    return f"- {label}: `{status}`{suffix}"


def render_bmw_git_readiness_markdown(payload: dict[str, Any]) -> str:
    lines = [
        BMW_GIT_READINESS_BANNER,
        "",
        f"# BMW Git Readiness - {payload.get('profile_id', 'profile')}",
        "",
        f"- Matched brand/profile: `{payload.get('brand', '')} {payload.get('matched_profile_id', '')}`",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- Data available: `{str(bool(payload.get('data_available'))).lower()}`",
    ]
    repo_root = str(payload.get("repo_root", "")).strip()
    profile_path = str(payload.get("profile_path", "")).strip()
    if repo_root:
        lines.append(f"- Repository: `{repo_root}`")
    if profile_path:
        lines.append(f"- Profile folder: `{profile_path}`")
    latest_commit = payload.get("latest_commit", {})
    if isinstance(latest_commit, dict) and latest_commit.get("short_sha"):
        subject = str(latest_commit.get("subject", "")).strip()
        author_date = str(latest_commit.get("author_date", "")).strip()
        suffix = f" - {subject}" if subject else ""
        date_suffix = f" ({author_date})" if author_date else ""
        lines.append(f"- Latest profile commit: `{latest_commit['short_sha']}`{date_suffix}{suffix}")
    summary = str(payload.get("summary", "")).strip()
    if summary:
        lines.extend(["", summary])
    checks = payload.get("readiness_checks", [])
    if isinstance(checks, list) and checks:
        lines.extend(["", "## Readiness Checks"])
        for item in checks:
            if isinstance(item, dict):
                lines.append(_check_summary_line({str(k): str(v) for k, v in item.items()}))
    lines.extend(["", str(payload.get("note", _NOTE)), "Manual review remains required."])
    return "\n".join(lines).rstrip() + "\n"


def render_bmw_git_readiness_text(payload: dict[str, Any]) -> str:
    lines = [
        BMW_GIT_READINESS_BANNER,
        str(payload.get("summary", "BMW Git readiness unavailable.")),
        "Manual review remains required.",
    ]
    for item in payload.get("readiness_checks", []):
        if isinstance(item, dict):
            lines.append(f"- {item.get('label', 'check')}: {item.get('status', 'missing')}")
    return "\n".join(lines)
