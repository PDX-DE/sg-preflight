from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sg_preflight.bmw_delivery import candidate_bmw_profile_ids, discover_bmw_models_repo


QA_HERO_READINESS_BANNER = (
    "QA Hero readiness state is read-only from the local digital-3d-car-models clone. "
    "SGFX surfaces presence and counts only; the operator records the verdict per step per the Quality Hero checklist."
)
QA_HERO_READINESS_NOTE = (
    "Read-only Quality Hero readiness state. SGFX surfaces presence and counts only; the operator records the verdict per step."
)
_BRANDS = ("BMW", "MINI")


def _resolve_car_root(repo_root: Path, profile_id: str) -> tuple[str, str, Path, Path]:
    candidates = candidate_bmw_profile_ids(profile_id)
    for brand in _BRANDS:
        brand_root = repo_root / "cars" / brand
        for candidate in candidates:
            car_root = brand_root / candidate
            if car_root.exists():
                return brand, candidate, brand_root, car_root
    matched = candidates[0] if candidates else profile_id.strip()
    brand_root = repo_root / "cars" / "BMW"
    return "BMW", matched, brand_root, brand_root / matched


def _first_matching_dir(root: Path, *patterns: str) -> Path | None:
    if not root.exists():
        return None
    for pattern in patterns:
        matches = sorted(path for path in root.glob(pattern) if path.is_dir())
        if matches:
            return matches[0]
    return None


def _file_count(path: Path | None, *, suffixes: tuple[str, ...] = ()) -> int:
    if path is None or not path.exists():
        return 0
    if path.is_file():
        return 1 if not suffixes or path.suffix.lower() in suffixes else 0
    suffix_set = {suffix.lower() for suffix in suffixes}
    return sum(
        1
        for item in path.rglob("*")
        if item.is_file() and (not suffix_set or item.suffix.lower() in suffix_set)
    )


def _json_item_count(path: Path | None) -> int:
    if path is None or not path.exists() or not path.is_file():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return 0
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for key in ("paints", "colors", "items", "values"):
            value = data.get(key)
            if isinstance(value, list):
                return len(value)
            if isinstance(value, dict):
                return len(value)
        return len(data)
    return 0


def _subsystem(
    key: str,
    label: str,
    path: Path | None,
    *,
    file_count: int | None = None,
    count: int | None = None,
    count_label: str = "count",
) -> dict[str, Any]:
    resolved_file_count = _file_count(path) if file_count is None else file_count
    resolved_count = resolved_file_count if count is None else count
    present = bool(path and path.exists() and (resolved_file_count > 0 or resolved_count > 0))
    item = {
        "key": key,
        "label": label,
        "status": "present" if present else "missing",
        "path": str(path) if path and path.exists() else "",
        "file_count": resolved_file_count,
        "count": resolved_count,
    }
    item[count_label] = resolved_count
    return item


def _carpaint_catalog(brand_root: Path) -> Path | None:
    for name in ("CarPaint.json", "CarPaint_IDC23.json"):
        candidate = brand_root / name
        if candidate.exists():
            return candidate
    return None


def _profile_stem(matched_profile: str) -> str:
    return matched_profile[:-4] if matched_profile.endswith("_EVO") else matched_profile


def _profile_subsystems(brand_root: Path, car_root: Path, matched_profile: str) -> list[dict[str, Any]]:
    stem = _profile_stem(matched_profile)
    resources_root = car_root / "resources"
    logic_root = car_root / "logic"
    constants_root = car_root / "_Common" / "constants"
    carpaint_catalog = _carpaint_catalog(brand_root)
    perspective_files = sorted(car_root.glob("perspectives_*.json")) if car_root.exists() else []

    lightfx_root = _first_matching_dir(resources_root, f"RES_{stem}_LightFX", "*LightFX*")
    welcomefx_root = _first_matching_dir(resources_root, f"RES_{stem}_WelcomeFX", "*WelcomeFX*") or _first_matching_dir(
        logic_root, f"LOG_{stem}_WelcomeAnimation", "*WelcomeAnimation*"
    )
    shadesfx_root = _first_matching_dir(resources_root, f"RES_{stem}_ShadesFX", "*ShadesFX*") or _first_matching_dir(
        logic_root, "*Shades*"
    )
    anchor_root = _first_matching_dir(resources_root, f"RES_{stem}_AnchorPoints", "*AnchorPoints*")
    carpaint_count = _json_item_count(carpaint_catalog)

    return [
        _subsystem("lightfx", "LightFX resources", lightfx_root),
        _subsystem("welcomefx", "WelcomeFX resources", welcomefx_root),
        _subsystem("shadesfx", "ShadesFX resources", shadesfx_root),
        _subsystem("carpaint", "CarPaint catalog", carpaint_catalog, file_count=1 if carpaint_catalog else 0, count=carpaint_count, count_label="paint_count"),
        _subsystem("anchor_points", "Anchor point resources", anchor_root, count_label="anchor_count"),
        _subsystem("constants", "Constants files", constants_root if constants_root.exists() else None),
        _subsystem("perspectives", "Perspective JSON", car_root if perspective_files else None, file_count=len(perspective_files), count=len(perspective_files)),
    ]


def _base_payload(
    profile_id: str,
    *,
    repo_root: Path,
    brand: str,
    matched_profile: str,
    brand_root: Path,
    car_root: Path,
    status: str,
    summary: str,
    subsystems: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    items = subsystems or []
    available = sum(1 for item in items if item.get("status") == "present")
    return {
        "profile_id": profile_id.strip(),
        "matched_profile_id": matched_profile,
        "brand": brand,
        "status": status,
        "data_available": status == "available",
        "repo_root": str(repo_root) if repo_root.exists() else "",
        "brand_path": str(brand_root) if brand_root.exists() else "",
        "profile_path": str(car_root) if car_root.exists() else "",
        "subsystems": items,
        "available_count": available,
        "total_count": len(items),
        "summary": summary,
        "note": QA_HERO_READINESS_NOTE,
        "banner": QA_HERO_READINESS_BANNER,
        "is_approval": False,
    }


def read_qa_hero_readiness(
    profile_id: str,
    *,
    workspace: Path | str | None = None,
    bmw_root: Path | str | None = None,
) -> dict[str, Any]:
    workspace_path = Path(workspace).resolve() if workspace is not None else None
    repo_root = Path(bmw_root).resolve() if bmw_root is not None else discover_bmw_models_repo(workspace_path).resolve()
    requested = profile_id.strip()
    brand, matched_profile, brand_root, car_root = _resolve_car_root(repo_root, requested)
    if not repo_root.exists():
        return _base_payload(
            requested,
            repo_root=repo_root,
            brand=brand,
            matched_profile=matched_profile,
            brand_root=brand_root,
            car_root=car_root,
            status="no_bmw_root",
            summary=f"QA Hero readiness unavailable: digital-3d-car-models root not found at {repo_root}.",
        )
    if not car_root.exists():
        return _base_payload(
            requested,
            repo_root=repo_root,
            brand=brand,
            matched_profile=matched_profile,
            brand_root=brand_root,
            car_root=car_root,
            status="no_profile_folder",
            summary=f"QA Hero readiness unavailable: profile folder not found for {requested or 'profile'}.",
        )

    subsystems = _profile_subsystems(brand_root, car_root, matched_profile)
    available = sum(1 for item in subsystems if item["status"] == "present")
    summary = f"{matched_profile} QA Hero readiness: {available} of {len(subsystems)} subsystems present."
    return _base_payload(
        requested,
        repo_root=repo_root,
        brand=brand,
        matched_profile=matched_profile,
        brand_root=brand_root,
        car_root=car_root,
        status="available",
        summary=summary,
        subsystems=subsystems,
    )


def read_qa_hero_readiness_for_profiles(
    profile_ids: tuple[str, ...] | list[str],
    *,
    workspace: Path | str | None = None,
    bmw_root: Path | str | None = None,
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    payloads: list[dict[str, Any]] = []
    for profile_id in profile_ids:
        profile = str(profile_id).strip()
        if not profile or profile.casefold() in seen:
            continue
        seen.add(profile.casefold())
        payloads.append(read_qa_hero_readiness(profile, workspace=workspace, bmw_root=bmw_root))
    return payloads


def qa_hero_readiness_digest_items(state: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = state.get("qa_hero_readiness", [])
    if isinstance(raw_items, dict):
        raw_items = [raw_items]
    if not isinstance(raw_items, list):
        return []
    items: list[dict[str, Any]] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        profile = str(raw_item.get("matched_profile_id") or raw_item.get("profile_id") or "profile").strip()
        available = int(raw_item.get("available_count", 0) or 0)
        total = int(raw_item.get("total_count", 0) or 0)
        detail = str(raw_item.get("summary", "")).strip() or f"{available} of {total} QA Hero subsystems present."
        items.append(
            {
                "label": f"QA Hero readiness {profile}",
                "status": "prepared" if raw_item.get("data_available") else str(raw_item.get("status", "not_available")),
                "detail": detail,
                "source": "qa_hero_readiness",
                "path": str(raw_item.get("profile_path", "") or raw_item.get("repo_root", "")).strip(),
                "note": str(raw_item.get("note", QA_HERO_READINESS_NOTE)).strip(),
                "guidance": "Read-only QA Hero readiness guidance; SGFX surfaces presence and counts only.",
                "is_approval": False,
            }
        )
    return items


def _subsystem_markdown_line(item: dict[str, Any]) -> str:
    label = str(item.get("label", "Subsystem")).strip()
    status = str(item.get("status", "missing")).strip()
    path = str(item.get("path", "")).strip()
    count = int(item.get("count", 0) or 0)
    count_text = f"; count={count}" if count else ""
    path_text = f" - `{path}`" if path and status == "present" else ""
    return f"- {label}: `{status}`{count_text}{path_text}"


def render_qa_hero_readiness_markdown(payload: dict[str, Any]) -> str:
    lines = [
        QA_HERO_READINESS_BANNER,
        "",
        f"# QA Hero Readiness - {payload.get('profile_id', 'profile')}",
        "",
        f"- Matched brand/profile: `{payload.get('brand', '')} {payload.get('matched_profile_id', '')}`",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- Data available: `{str(bool(payload.get('data_available'))).lower()}`",
        f"- Subsystems present: `{payload.get('available_count', 0)} / {payload.get('total_count', 0)}`",
    ]
    profile_path = str(payload.get("profile_path", "")).strip()
    if profile_path:
        lines.append(f"- Profile folder: `{profile_path}`")
    summary = str(payload.get("summary", "")).strip()
    if summary:
        lines.extend(["", summary])
    subsystems = payload.get("subsystems", [])
    if isinstance(subsystems, list) and subsystems:
        lines.extend(["", "## Subsystems"])
        for item in subsystems:
            if isinstance(item, dict):
                lines.append(_subsystem_markdown_line(item))
    lines.extend(["", str(payload.get("note", QA_HERO_READINESS_NOTE)), "Manual review remains required."])
    return "\n".join(lines).rstrip() + "\n"


def render_qa_hero_readiness_text(payload: dict[str, Any]) -> str:
    lines = [
        QA_HERO_READINESS_BANNER,
        str(payload.get("summary", "QA Hero readiness unavailable.")),
        "Manual review remains required.",
    ]
    for item in payload.get("subsystems", []):
        if isinstance(item, dict):
            lines.append(f"- {item.get('label', 'Subsystem')}: {item.get('status', 'missing')}")
    return "\n".join(lines)
