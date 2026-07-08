from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sg_preflight.bmw_delivery import (
    discover_bmw_models_repo,
    discover_bmw_raw_repo,
    inspect_raw_checkout_health,
)

STATUS_MATCHED = "matched"
STATUS_SOURCE_ONLY = "source_only"
STATUS_DELIVERY_ONLY = "delivery_only"

EVIDENCE_BANNER = (
    "Evidence only: this board compares folder structure between the raw workfiles repository and "
    "the models delivery repository. It does not judge content quality; review stays manual."
)

_MODEL_MARKER_NAMES = ("CHANGELOG.md", "export", "main", "resources", "logic")
_RENAME_SUFFIXES = ("", "_EVO", "_BEV")
_RAW_KIND_FOLDERS = ("blender", "json", "photoshop")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _workfiles_dir(profile_dir: Path) -> Path | None:
    try:
        for child in profile_dir.iterdir():
            if child.is_dir() and child.name.casefold() == "_workfiles":
                return child
    except OSError:
        return None
    return None


def _raw_profile_detail(workfiles: Path) -> dict[str, int]:
    detail: dict[str, int] = {}
    for kind in _RAW_KIND_FOLDERS:
        kind_dir = workfiles / kind
        if not kind_dir.exists():
            continue
        try:
            detail[kind] = sum(1 for item in kind_dir.iterdir() if item.is_file())
        except OSError:
            detail[kind] = 0
    return detail


def _scan_raw(raw_root: Path) -> tuple[dict[tuple[str, str], dict[str, Any]], list[dict[str, str]], list[str]]:
    profiles: dict[tuple[str, str], dict[str, Any]] = {}
    unknown: list[dict[str, str]] = []
    shared: list[str] = []
    cars_root = raw_root / "cars"
    if not cars_root.exists():
        return profiles, unknown, shared
    for brand_dir in sorted(cars_root.iterdir()):
        if not brand_dir.is_dir():
            continue
        for profile_dir in sorted(brand_dir.iterdir()):
            if not profile_dir.is_dir():
                continue
            if profile_dir.name.startswith("_"):
                shared.append(f"{brand_dir.name}/{profile_dir.name}")
                continue
            workfiles = _workfiles_dir(profile_dir)
            if workfiles is None:
                unknown.append(
                    {
                        "path": f"{brand_dir.name}/{profile_dir.name}",
                        "reason": "No _WorkFiles folder found; not classified as an authoring profile.",
                    }
                )
                continue
            profiles[(brand_dir.name, profile_dir.name)] = {
                "workfiles_folder": workfiles.name,
                "detail": _raw_profile_detail(workfiles),
            }
    return profiles, unknown, shared


def _scan_models(models_root: Path) -> tuple[dict[tuple[str, str], list[str]], list[dict[str, str]], list[str]]:
    profiles: dict[tuple[str, str], list[str]] = {}
    skipped: list[dict[str, str]] = []
    shared: list[str] = []
    cars_root = models_root / "cars"
    if not cars_root.exists():
        return profiles, skipped, shared
    for brand_dir in sorted(cars_root.iterdir()):
        if not brand_dir.is_dir() or brand_dir.name.startswith("_") or brand_dir.name == "licenses":
            continue
        for profile_dir in sorted(brand_dir.iterdir()):
            if not profile_dir.is_dir():
                continue
            if profile_dir.name.startswith("_"):
                shared.append(f"{brand_dir.name}/{profile_dir.name}")
                continue
            markers = [name for name in _MODEL_MARKER_NAMES if (profile_dir / name).exists()]
            if not markers:
                skipped.append(
                    {
                        "path": f"{brand_dir.name}/{profile_dir.name}",
                        "reason": "No delivery markers (CHANGELOG.md/export/main/resources/logic) found.",
                    }
                )
                continue
            profiles[(brand_dir.name, profile_dir.name)] = markers
    return profiles, skipped, shared


def _match_models_name(
    raw_key: tuple[str, str], models_profiles: dict[tuple[str, str], list[str]]
) -> tuple[str, str] | None:
    brand, name = raw_key
    for suffix in _RENAME_SUFFIXES:
        candidate = (brand, f"{name}{suffix}")
        if candidate in models_profiles:
            return candidate
    return None


def build_raw_models_parity_board(
    *,
    raw_root: Path | str | None = None,
    models_root: Path | str | None = None,
    workspace_root: Path | str | None = None,
) -> dict[str, Any]:
    workspace = Path(workspace_root).resolve() if workspace_root is not None else None
    raw_path = Path(raw_root).resolve() if raw_root is not None else discover_bmw_raw_repo(workspace)
    models_path = (
        Path(models_root).resolve() if models_root is not None else discover_bmw_models_repo(workspace)
    )
    generated = _now_iso()

    raw_state = "ready" if (raw_path / "cars").exists() else "missing"
    models_state = "ready" if (models_path / "cars").exists() else "missing"

    raw_profiles, raw_unknown, raw_shared = _scan_raw(raw_path)
    models_profiles, models_skipped, models_shared = _scan_models(models_path)

    rows: list[dict[str, Any]] = []
    claimed_models: set[tuple[str, str]] = set()
    for raw_key in sorted(raw_profiles):
        models_key = _match_models_name(raw_key, models_profiles)
        raw_info = raw_profiles[raw_key]
        if models_key is None:
            rows.append(
                {
                    "brand": raw_key[0],
                    "raw_profile": raw_key[1],
                    "models_profile": "",
                    "status": STATUS_SOURCE_ONLY,
                    "raw_workfiles": raw_info["detail"],
                    "models_markers": [],
                    "note": "Authoring sources exist but no matching delivery folder was found.",
                }
            )
            continue
        claimed_models.add(models_key)
        rows.append(
            {
                "brand": raw_key[0],
                "raw_profile": raw_key[1],
                "models_profile": models_key[1],
                "status": STATUS_MATCHED,
                "raw_workfiles": raw_info["detail"],
                "models_markers": models_profiles[models_key],
                "note": "",
            }
        )
    for models_key in sorted(models_profiles):
        if models_key in claimed_models:
            continue
        rows.append(
            {
                "brand": models_key[0],
                "raw_profile": "",
                "models_profile": models_key[1],
                "status": STATUS_DELIVERY_ONLY,
                "raw_workfiles": {},
                "models_markers": models_profiles[models_key],
                "note": "Delivery folder exists but no local authoring source was found in the raw repository.",
            }
        )
    rows.sort(key=lambda row: (row["brand"], row["raw_profile"] or row["models_profile"]))

    status_counts = {
        STATUS_MATCHED: sum(1 for row in rows if row["status"] == STATUS_MATCHED),
        STATUS_SOURCE_ONLY: sum(1 for row in rows if row["status"] == STATUS_SOURCE_ONLY),
        STATUS_DELIVERY_ONLY: sum(1 for row in rows if row["status"] == STATUS_DELIVERY_ONLY),
    }
    lfs_health = inspect_raw_checkout_health(raw_path) if raw_state == "ready" else {
        "state": "not_present",
        "sampled": 0,
        "pointer_count": 0,
        "pointer_files": [],
    }
    return {
        "schema_version": 1,
        "generated_at_utc": generated,
        "read_only": True,
        "manual_review_banner": EVIDENCE_BANNER,
        "raw_root": str(raw_path),
        "models_root": str(models_path),
        "raw_state": raw_state,
        "models_state": models_state,
        "raw_lfs_health": lfs_health,
        "counts": {"total": len(rows), **status_counts},
        "entries": rows,
        "raw_unknown": raw_unknown,
        "raw_shared": raw_shared,
        "models_skipped": models_skipped,
        "models_shared": models_shared,
    }


def raw_models_parity_markdown(board: dict[str, Any]) -> str:
    counts = board["counts"]
    lines = [
        "# Raw vs Models Parity Board",
        "",
        str(board["manual_review_banner"]),
        "",
        f"- raw workfiles repository: `{board['raw_root']}` ({board['raw_state']})",
        f"- models delivery repository: `{board['models_root']}` ({board['models_state']})",
        f"- generated: `{board['generated_at_utc']}`",
        f"- matched: {counts[STATUS_MATCHED]} | source only: {counts[STATUS_SOURCE_ONLY]} | delivery only: {counts[STATUS_DELIVERY_ONLY]}",
    ]
    lfs = board.get("raw_lfs_health", {})
    if lfs.get("state") == "lfs_pointers_detected":
        lines.append(
            f"- WARNING: {lfs.get('pointer_count', 0)} sampled raw files are Git LFS pointer stubs; run 'git lfs pull' before trusting raw-side details."
        )
    lines.extend(
        [
            "",
            "| Brand | Raw profile | Models profile | Status | Raw workfiles | Models markers | Note |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in board["entries"]:
        workfiles = ", ".join(f"{kind}: {count}" for kind, count in row["raw_workfiles"].items())
        lines.append(
            f"| {row['brand']} | {row['raw_profile']} | {row['models_profile']} | {row['status']} "
            f"| {workfiles} | {', '.join(row['models_markers'])} | {row['note']} |"
        )
    for label, bucket_key, reason_key in (
        ("Unclassified raw folders", "raw_unknown", "reason"),
        ("Skipped models folders", "models_skipped", "reason"),
    ):
        bucket = board.get(bucket_key, [])
        if bucket:
            lines.extend(["", f"## {label}", ""])
            for item in bucket:
                lines.append(f"- `{item['path']}` — {item[reason_key]}")
    return "\n".join(lines).rstrip() + "\n"


def write_raw_models_parity_board(
    board: dict[str, Any], output_root: Path | str
) -> dict[str, str]:
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "raw-models-parity.json"
    markdown_path = out_dir / "raw-models-parity.md"
    json_path.write_text(json.dumps(board, indent=2, ensure_ascii=False), encoding="utf-8")
    markdown_path.write_text(raw_models_parity_markdown(board), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}
