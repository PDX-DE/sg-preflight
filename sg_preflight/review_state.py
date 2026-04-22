from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from sg_preflight.review_messages import build_digest_json, build_morning_digest, build_review_owner_update
from sg_preflight.review_tracking import (
    REVIEW_DECISION_STATUS_OPTIONS,
    load_external_findings,
    load_review_decisions,
)

_REVIEW_PACKAGE_SUFFIX = "-review-package-"
_REVIEW_BUNDLE_SUFFIX = "-review-bundle.json"
_MANUAL_STATUSES = ("pending", "passed", "issue", "blocked")
_HIGH_PRIORITY_VERDICTS = {"runtime_crash", "scenario_output_missing", "baseline_missing"}
_PRIORITY_BASE_SCORES = {
    "runtime_crash": 100,
    "scenario_output_missing": 92,
    "baseline_missing": 90,
    "needs_manual_review": 88,
    "proxy_candidate_ready": 72,
    "baseline_candidate_ready": 55,
    "likely_ok": 18,
}


def _workspace_root(workspace: Path | str | None = None) -> Path:
    root = Path(workspace) if workspace is not None else Path(__file__).resolve().parents[1]
    return root.resolve()


def _out_root(workspace: Path | str | None = None) -> Path:
    return _workspace_root(workspace) / "out"


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _parse_iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest_progress(path: Path) -> int | None:
    if not path.exists():
        return None
    match = re.search(
        r"Visible DoD progress \(conservative\):\s*`?(\d+)%`?",
        path.read_text(encoding="utf-8"),
    )
    if not match:
        return None
    return int(match.group(1))


def _bundle_evidence_map(bundle_payload: dict[str, Any]) -> dict[str, dict[str, str]]:
    mapping: dict[str, dict[str, str]] = {}
    for item in bundle_payload.get("evidence_index", []):
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).strip()
        path = str(item.get("path", "")).strip()
        if not label or not path:
            continue
        mapping[label] = {
            "path": path,
            "detail": str(item.get("detail", "")).strip(),
        }
    return mapping


def _parse_markdown_bullet_path(path: Path | None, prefix: str) -> str:
    if path is None or not path.exists():
        return ""
    needle = f"- {prefix}:"
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line.startswith(needle):
            continue
        value = line.split(":", 1)[1].strip()
        if value.startswith("`") and value.endswith("`"):
            value = value[1:-1]
        return value.strip()
    return ""


def _manual_review_status(record_path: Path | None, *, has_scene: bool, has_blender: bool) -> str:
    if not has_scene and not has_blender:
        return "blocked"
    if record_path is None or not record_path.exists():
        return "pending"
    content = record_path.read_text(encoding="utf-8", errors="replace").lower()
    if "[x] yes" in content and "[x] no" not in content:
        return "passed"
    if "[x] no" in content:
        return "issue"
    return "pending"


def _manual_review_note(profile_id: str, status: str, unresolved_families: list[str]) -> str:
    lines = [
        f"{profile_id} manual review",
        f"- Status: {status}",
        "- Open the representative RaCo scene and Blender workfile.",
        "- Compare the candidate/proxy screenshots against intended changes.",
        "- Record pass / issue / blocked explicitly and attach screenshot evidence if needed.",
    ]
    if unresolved_families:
        lines.append(f"- Technical blocker to keep in mind: {', '.join(unresolved_families)}")
    return "\n".join(lines)


def _build_manual_review_profiles(
    package: dict[str, Any],
    *,
    workspace_root: Path,
    unresolved_families: list[str],
) -> list[dict[str, Any]]:
    bundle_json_path = Path(package["review_bundle_json"]["absolute_path"])
    bundle_payload = _load_json(bundle_json_path)
    evidence_map = _bundle_evidence_map(bundle_payload)
    candidate_gallery_path = str(package["candidate_gallery"]["absolute_path"]).strip()
    manual_profiles: list[dict[str, Any]] = []

    def _optional_path(path_text: str) -> Path | None:
        normalized = str(path_text).strip()
        return Path(normalized) if normalized else None

    for profile_id in package.get("scope", []):
        profile = str(profile_id).strip()
        if not profile:
            continue
        companion_path = _optional_path(evidence_map.get(f"{profile} manual review companion", {}).get("path", ""))
        record_path = _optional_path(evidence_map.get(f"{profile} manual review record", {}).get("path", ""))
        slots_path = _optional_path(evidence_map.get(f"{profile} screenshot evidence slots", {}).get("path", ""))
        blender_raco_path = _optional_path(evidence_map.get(f"{profile} Blender vs RaCo checklist", {}).get("path", ""))
        visual_checklist_path = _optional_path(evidence_map.get(f"{profile} visual review checklist", {}).get("path", ""))
        triage_path = _optional_path(evidence_map.get(f"{profile} screenshot triage", {}).get("path", ""))

        raco_scene_path = _parse_markdown_bullet_path(companion_path, "Representative RaCo scene")
        blender_workfile_path = _parse_markdown_bullet_path(companion_path, "Representative Blender workfile")
        baseline_root_path = _parse_markdown_bullet_path(companion_path, "Screenshot baseline root")
        bmw_actuals_root_path = _parse_markdown_bullet_path(companion_path, "BMW actuals root")
        bmw_diff_root_path = _parse_markdown_bullet_path(companion_path, "BMW diff root")

        has_scene = Path(raco_scene_path).exists() if raco_scene_path else False
        has_blender = Path(blender_workfile_path).exists() if blender_workfile_path else False
        status = _manual_review_status(record_path, has_scene=has_scene, has_blender=has_blender)

        manual_profiles.append(
            {
                "profile_id": profile,
                "status": status if status in _MANUAL_STATUSES else "pending",
                "summary": "Open the representative RaCo scene and Blender workfile, compare the current screenshot outputs, and record the human verdict explicitly.",
                "note": "Manual review is still human-owned. The tool only prepares the right assets, paths, and note text.",
                "copy_review_note_text": _manual_review_note(profile, status, unresolved_families),
                "raco_scene": _artifact_ref(Path(raco_scene_path) if raco_scene_path else None, package_root=None, workspace_root=workspace_root),
                "blender_workfile": _artifact_ref(Path(blender_workfile_path) if blender_workfile_path else None, package_root=None, workspace_root=workspace_root),
                "candidate_gallery": _artifact_ref(Path(candidate_gallery_path) if candidate_gallery_path else None, package_root=None, workspace_root=workspace_root),
                "screenshot_triage": _artifact_ref(triage_path, package_root=None, workspace_root=workspace_root),
                "manual_review_record": _artifact_ref(record_path, package_root=None, workspace_root=workspace_root),
                "screenshot_evidence_slots": _artifact_ref(slots_path, package_root=None, workspace_root=workspace_root),
                "blender_raco_checklist": _artifact_ref(blender_raco_path, package_root=None, workspace_root=workspace_root),
                "visual_review_checklist": _artifact_ref(visual_checklist_path, package_root=None, workspace_root=workspace_root),
                "baseline_root": _artifact_ref(Path(baseline_root_path) if baseline_root_path else None, package_root=None, workspace_root=workspace_root),
                "bmw_actuals_root": _artifact_ref(Path(bmw_actuals_root_path) if bmw_actuals_root_path else None, package_root=None, workspace_root=workspace_root),
                "bmw_diff_root": _artifact_ref(Path(bmw_diff_root_path) if bmw_diff_root_path else None, package_root=None, workspace_root=workspace_root),
            }
        )
    return manual_profiles


def _artifact_ref(path: Path | None, *, package_root: Path | None, workspace_root: Path) -> dict[str, Any]:
    if path is None:
        return {
            "absolute_path": "",
            "relative_path": "",
            "workspace_relative_path": "",
            "exists": False,
        }

    absolute = path.resolve()
    relative = ""
    workspace_relative = ""
    if package_root is not None:
        try:
            relative = absolute.relative_to(package_root.resolve()).as_posix()
        except ValueError:
            relative = ""
    try:
        workspace_relative = absolute.relative_to(workspace_root.resolve()).as_posix()
    except ValueError:
        workspace_relative = ""
    return {
        "absolute_path": str(absolute),
        "relative_path": relative,
        "workspace_relative_path": workspace_relative,
        "exists": absolute.exists(),
    }


def _family_priority_bonus(filter_name: str) -> int:
    family = str(filter_name).strip().casefold()
    if family == "lights_onlycones":
        return 16
    if family in {"lights_highbeam", "lights_lowbeam"}:
        return 10
    if family.startswith("lights_"):
        return 7
    if family.startswith("openalldoors_"):
        return 4
    if family.startswith("welcome_animation_"):
        return 2
    return 0


def _priority_score_from_payload(item: dict[str, Any], *, is_new: bool = False) -> int:
    verdict = str(item.get("verdict", "")).strip()
    raw_score = int(item.get("priority_score", 0) or 0)
    base_score = _PRIORITY_BASE_SCORES.get(verdict, 0)
    score = max(raw_score, base_score)
    score += _family_priority_bonus(str(item.get("filter_name", "")))
    score += min(max(int(item.get("diff_count", 0) or 0), 0), 3) * 3
    if int(item.get("actual_count", 0) or 0) > 0:
        score += 4
    if bool(item.get("target_output_present", False)):
        score += 5
    if item.get("proxy_files"):
        score += 4
    if is_new:
        score += 15
    return score


def _priority_level_from_payload(item: dict[str, Any], *, is_new: bool = False) -> str:
    verdict = str(item.get("verdict", "")).strip()
    if verdict in _HIGH_PRIORITY_VERDICTS:
        return "P0"
    if verdict == "needs_manual_review":
        return "P0" if is_new else "P1"
    if verdict == "proxy_candidate_ready":
        return "P1"
    if verdict == "baseline_candidate_ready":
        return "P1" if is_new and _family_priority_bonus(str(item.get("filter_name", ""))) >= 7 else "P2"
    if verdict == "likely_ok":
        return "P2" if is_new else "P3"
    return "P3"


def _priority_attention_category(item: dict[str, Any], *, is_new: bool = False) -> str:
    level = _priority_level_from_payload(item, is_new=is_new)
    if level == "P0":
        return "must inspect"
    if level == "P1":
        return "inspect before delivery"
    if level == "P2":
        return "inspect if time"
    return "low priority / unchanged"


def _priority_signals_from_payload(item: dict[str, Any], *, is_new: bool = False) -> list[str]:
    payload_signals = [str(signal).strip() for signal in item.get("signals", []) if str(signal).strip()]
    seen = {signal.casefold() for signal in payload_signals}

    def _append(text: str) -> None:
        key = text.casefold()
        if key not in seen:
            payload_signals.append(text)
            seen.add(key)

    verdict = str(item.get("verdict", "")).strip()
    if verdict == "needs_manual_review":
        _append("diff review needed")
    if verdict in _HIGH_PRIORITY_VERDICTS:
        _append("technical blocker")
    if is_new:
        _append("new since previous run")
    elif verdict == "likely_ok":
        _append("unchanged exact compare")
    return payload_signals


def _summarize_daily_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    smoke_results = payload.get("smoke_results", [])
    battery_results = payload.get("battery_results", [])
    exact_ready = sum(1 for item in battery_results if item.get("verdict") == "baseline_candidate_ready")
    proxy_ready = sum(1 for item in battery_results if item.get("verdict") == "proxy_candidate_ready")
    runtime_crash = sum(1 for item in battery_results if item.get("verdict") == "runtime_crash")
    unresolved_families = sorted(
        {
            str(item.get("filter_name", "")).strip()
            for item in battery_results
            if item.get("verdict") == "runtime_crash" and str(item.get("filter_name", "")).strip()
        }
    )
    return {
        "created_at": payload.get("created_at", ""),
        "scope_profiles": list(payload.get("scope_profiles", [])),
        "smoke_completed": sum(1 for item in smoke_results if str(item.get("status", "")).strip().lower() == "completed"),
        "smoke_total": len(smoke_results),
        "battery_total": len(battery_results),
        "exact_candidate_ready": exact_ready,
        "proxy_candidate_ready": proxy_ready,
        "runtime_crash": runtime_crash,
        "unresolved_families": unresolved_families,
        "top_review_items": list(payload.get("top_review_items", [])),
        "blocked_steps": list(payload.get("blocked_steps", [])),
    }


def _top_level_daily_snapshot_dirs(workspace: Path) -> list[Path]:
    out_root = _out_root(workspace)
    if not out_root.exists():
        return []
    roots = [
        path
        for path in out_root.iterdir()
        if path.is_dir() and path.name.startswith("daily-3d-car-qa-summary-")
    ]
    return sorted(roots, key=lambda item: item.stat().st_mtime, reverse=True)


def _review_bundle_paths(workspace: Path) -> list[Path]:
    out_root = _out_root(workspace)
    if not out_root.exists():
        return []
    return sorted(
        out_root.rglob(f"*{_REVIEW_BUNDLE_SUFFIX}"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )


def load_review_package(path: Path | str, workspace: Path | str | None = None) -> dict[str, Any]:
    workspace_root = _workspace_root(workspace)
    raw_path = Path(path)
    if raw_path.suffix.lower() == ".zip":
        package_root = raw_path.with_suffix("")
    elif raw_path.is_file():
        package_root = raw_path.parent
    else:
        package_root = raw_path
    package_root = package_root.resolve()

    bundle_candidates = list(package_root.glob(f"*{_REVIEW_BUNDLE_SUFFIX}"))
    if not bundle_candidates:
        raise FileNotFoundError(f"No review-bundle JSON found under {package_root}")
    bundle_json_path = bundle_candidates[0]
    bundle = _load_json(bundle_json_path)

    zip_path = package_root.with_suffix(".zip")
    sha256_path = Path(str(zip_path) + ".sha256")
    manifest_path = package_root / "SENT_PACKAGE_MANIFEST.md"
    decisions_path = package_root / "review-owner-decisions.md"
    dod_matrix_path = package_root / f"{bundle['ticket_id']}-dod-matrix.md"
    review_status_path = package_root / f"{bundle['ticket_id']}-review-status.md"
    teams_update_path = package_root / f"{bundle['ticket_id']}-teams-update.md"
    candidate_gallery_path = package_root / "artifacts" / "daily-snapshot" / "candidate-review-gallery.html"
    daily_snapshot_md_path = package_root / "artifacts" / "daily-snapshot" / "daily-3d-car-qa-summary.md"
    daily_snapshot_json_path = package_root / "artifacts" / "daily-snapshot" / "daily-3d-car-qa-summary.json"
    review_priority_md_path = package_root / "artifacts" / "daily-snapshot" / "review-priority-ranking.md"
    review_priority_json_path = package_root / "artifacts" / "daily-snapshot" / "review-priority-ranking.json"
    daily_delta_md_path = package_root / "artifacts" / "daily-snapshot" / "daily-qa-delta-summary.md"
    daily_delta_json_path = package_root / "artifacts" / "daily-snapshot" / "daily-qa-delta-summary.json"
    nested_reference = "refs" in {part.lower() for part in package_root.parts}

    return {
        "ticket_id": str(bundle.get("ticket_id", "")),
        "title": str(bundle.get("title", "")),
        "generated_at": str(bundle.get("generated_at_utc", "")),
        "overall_status": str(bundle.get("overall_status", "")),
        "scope": list(bundle.get("profile_ids", [])),
        "scope_note": str(bundle.get("scope_note", "")),
        "blockers": list(bundle.get("blockers", [])),
        "next_questions": list(bundle.get("next_questions", [])),
        "package_root": str(package_root),
        "zip_path": str(zip_path) if zip_path.exists() else "",
        "sha256_path": str(sha256_path) if sha256_path.exists() else "",
        "nested_reference": nested_reference,
        "visible_dod_progress_percent": _load_manifest_progress(manifest_path),
        "review_bundle_json": _artifact_ref(bundle_json_path, package_root=package_root, workspace_root=workspace_root),
        "manifest": _artifact_ref(manifest_path, package_root=package_root, workspace_root=workspace_root),
        "review_owner_decisions": _artifact_ref(decisions_path, package_root=package_root, workspace_root=workspace_root),
        "dod_matrix": _artifact_ref(dod_matrix_path, package_root=package_root, workspace_root=workspace_root),
        "review_status": _artifact_ref(review_status_path, package_root=package_root, workspace_root=workspace_root),
        "teams_update": _artifact_ref(teams_update_path, package_root=package_root, workspace_root=workspace_root),
        "candidate_gallery": _artifact_ref(candidate_gallery_path, package_root=package_root, workspace_root=workspace_root),
        "daily_snapshot_markdown": _artifact_ref(daily_snapshot_md_path, package_root=package_root, workspace_root=workspace_root),
        "daily_snapshot_json": _artifact_ref(daily_snapshot_json_path, package_root=package_root, workspace_root=workspace_root),
        "review_priority_markdown": _artifact_ref(review_priority_md_path, package_root=package_root, workspace_root=workspace_root),
        "review_priority_json": _artifact_ref(review_priority_json_path, package_root=package_root, workspace_root=workspace_root),
        "daily_delta_markdown": _artifact_ref(daily_delta_md_path, package_root=package_root, workspace_root=workspace_root),
        "daily_delta_json": _artifact_ref(daily_delta_json_path, package_root=package_root, workspace_root=workspace_root),
    }


def list_review_packages(workspace: Path | str | None = None) -> list[dict[str, Any]]:
    workspace_root = _workspace_root(workspace)
    packages = [load_review_package(path, workspace_root) for path in _review_bundle_paths(workspace_root)]
    return sorted(
        packages,
        key=lambda item: (
            item["nested_reference"],
            -_parse_iso_datetime(item["generated_at"]).timestamp() if item["generated_at"] else 0.0,
        ),
    )


def load_latest_review_package(ticket_id: str | None = None, workspace: Path | str | None = None) -> dict[str, Any]:
    packages = list_review_packages(workspace)
    if ticket_id:
        filtered = [item for item in packages if item["ticket_id"].lower() == ticket_id.strip().lower()]
    else:
        filtered = packages
    if not filtered:
        raise FileNotFoundError("No matching review package was found.")
    top_level = [item for item in filtered if not item["nested_reference"]]
    return top_level[0] if top_level else filtered[0]


def load_latest_daily_snapshot(workspace: Path | str | None = None) -> dict[str, Any]:
    workspace_root = _workspace_root(workspace)
    for snapshot_root in _top_level_daily_snapshot_dirs(workspace_root):
        json_path = snapshot_root / "daily-3d-car-qa-summary.json"
        md_path = snapshot_root / "daily-3d-car-qa-summary.md"
        if not json_path.exists():
            continue
        payload = _load_json(json_path)
        summary = _summarize_daily_snapshot(payload)
        return {
            "root": str(snapshot_root),
            "json_path": str(json_path),
            "markdown_path": str(md_path) if md_path.exists() else "",
            "summary": summary,
            "payload": payload,
        }
    raise FileNotFoundError("No top-level daily snapshot JSON was found.")


def load_review_priority(ticket_id: str | None = None, workspace: Path | str | None = None) -> dict[str, Any]:
    workspace_root = _workspace_root(workspace)
    package = load_latest_review_package(ticket_id, workspace_root)
    package_json_path = Path(package["review_priority_json"]["absolute_path"]) if package["review_priority_json"]["absolute_path"] else None
    package_md_path = Path(package["review_priority_markdown"]["absolute_path"]) if package["review_priority_markdown"]["absolute_path"] else None
    if package_json_path is not None and package_json_path.exists():
        json_path = package_json_path
        md_path = package_md_path
        source = "package"
    else:
        snapshot = load_latest_daily_snapshot(workspace_root)
        snapshot_root = Path(snapshot["root"])
        json_path = snapshot_root / "review-priority-ranking.json"
        md_path = snapshot_root / "review-priority-ranking.md"
        source = "daily_snapshot"
    if not json_path.exists():
        raise FileNotFoundError("No review-priority JSON artifact was found.")
    payload = _load_json(json_path)
    ranked_items = list(payload.get("ranked_items", []))
    for item in ranked_items:
        item["priority_score"] = _priority_score_from_payload(item, is_new=False)
        item["priority_level"] = _priority_level_from_payload(item, is_new=False)
        item["attention_category"] = _priority_attention_category(item, is_new=False)
        item["signals"] = _priority_signals_from_payload(item, is_new=False)
    ranked_items.sort(
        key=lambda item: (
            int(item.get("priority_score", 0)),
            str(item.get("profile_id", "")).upper(),
            str(item.get("filter_name", "")).lower(),
        ),
        reverse=True,
    )
    return {
        "source": source,
        "json_path": str(json_path),
        "markdown_path": str(md_path) if md_path.exists() else "",
        "created_at": str(payload.get("created_at", "")),
        "scope_profiles": list(payload.get("scope_profiles", [])),
        "ranked_items": ranked_items,
        "top_items": ranked_items[:5],
    }


def load_daily_delta(ticket_id: str | None = None, workspace: Path | str | None = None) -> dict[str, Any]:
    workspace_root = _workspace_root(workspace)
    package = load_latest_review_package(ticket_id, workspace_root)
    package_json_path = Path(package["daily_delta_json"]["absolute_path"]) if package["daily_delta_json"]["absolute_path"] else None
    package_md_path = Path(package["daily_delta_markdown"]["absolute_path"]) if package["daily_delta_markdown"]["absolute_path"] else None
    if package_json_path is not None and package_json_path.exists():
        json_path = package_json_path
        md_path = package_md_path
        source = "package"
    else:
        snapshot = load_latest_daily_snapshot(workspace_root)
        snapshot_root = Path(snapshot["root"])
        json_path = snapshot_root / "daily-qa-delta-summary.json"
        md_path = snapshot_root / "daily-qa-delta-summary.md"
        source = "daily_snapshot"
    if not json_path.exists():
        raise FileNotFoundError("No daily-delta JSON artifact was found.")
    payload = _load_json(json_path)
    return {
        "source": source,
        "json_path": str(json_path),
        "markdown_path": str(md_path) if md_path.exists() else "",
        "current_created_at": str(payload.get("current_created_at", "")),
        "previous_created_at": str(payload.get("previous_created_at", "")),
        "new_failures": list(payload.get("new_failures", [])),
        "resolved_failures": list(payload.get("resolved_failures", [])),
        "new_screenshot_diffs": list(payload.get("new_screenshot_diffs", [])),
        "unchanged_blockers": list(payload.get("unchanged_blockers", [])),
        "changed_counts": dict(payload.get("changed_counts", {})),
        "top_five_to_review": list(payload.get("top_five_to_review", [])),
    }


def load_review_owner_decisions(ticket_id: str | None = None, workspace: Path | str | None = None) -> dict[str, Any]:
    workspace_root = _workspace_root(workspace)
    package = load_latest_review_package(ticket_id, workspace_root)
    decisions_path = Path(package["review_owner_decisions"]["absolute_path"]) if package["review_owner_decisions"]["absolute_path"] else None
    if decisions_path is None or not decisions_path.exists():
        raise FileNotFoundError("No review-owner decisions template was found.")
    tracked = load_review_decisions(package["ticket_id"], workspace_root, fallback_markdown_path=decisions_path)
    return {
        "path": tracked["markdown_path"],
        "json_path": tracked["json_path"],
        "exists": True,
        "sections": tracked["decisions"],
        "pending_count": tracked["pending_count"],
        "updated_at": tracked["updated_at"],
    }


def load_external_review_findings(ticket_id: str | None = None, workspace: Path | str | None = None) -> dict[str, Any]:
    workspace_root = _workspace_root(workspace)
    package = load_latest_review_package(ticket_id, workspace_root)
    return load_external_findings(package["ticket_id"], workspace_root)


def verify_sendable_package(zip_path: Path | str, workspace: Path | str | None = None) -> dict[str, Any]:
    workspace_root = _workspace_root(workspace)
    raw = Path(zip_path)
    if raw.suffix.lower() == ".zip":
        package_root = raw.with_suffix("")
        archive_path = raw
    else:
        package_root = raw
        archive_path = raw.with_suffix(".zip")
    package_root = package_root.resolve()
    archive_path = archive_path.resolve()
    sha256_path = Path(str(archive_path) + ".sha256")

    required_files = {
        "review_bundle_json": package_root / next(
            (path.name for path in package_root.glob(f"*{_REVIEW_BUNDLE_SUFFIX}")),
            f"{package_root.name}-review-bundle.json",
        ),
        "manifest": package_root / "SENT_PACKAGE_MANIFEST.md",
        "review_owner_decisions": package_root / "review-owner-decisions.md",
        "candidate_gallery": package_root / "artifacts" / "daily-snapshot" / "candidate-review-gallery.html",
        "daily_snapshot_json": package_root / "artifacts" / "daily-snapshot" / "daily-3d-car-qa-summary.json",
        "daily_snapshot_markdown": package_root / "artifacts" / "daily-snapshot" / "daily-3d-car-qa-summary.md",
    }
    optional_files = {
        "review_priority_json": package_root / "artifacts" / "daily-snapshot" / "review-priority-ranking.json",
        "daily_delta_json": package_root / "artifacts" / "daily-snapshot" / "daily-qa-delta-summary.json",
    }

    missing_required = [key for key, path in required_files.items() if not path.exists()]
    missing_optional = [key for key, path in optional_files.items() if not path.exists()]
    zip_exists = archive_path.exists()
    sha_sidecar_exists = sha256_path.exists()

    sha_expected = ""
    sha_actual = ""
    sha_match = False
    if zip_exists:
        sha_actual = _file_sha256(archive_path)
    if sha_sidecar_exists:
        sha_expected = sha256_path.read_text(encoding="utf-8").strip().split(" ", 1)[0]
        sha_match = sha_expected.lower() == sha_actual.lower() if sha_actual else False

    errors: list[str] = []
    warnings: list[str] = []
    if not zip_exists:
        errors.append("Package ZIP is missing.")
    if missing_required:
        errors.extend(f"Missing required packaged artifact: {item}" for item in missing_required)
    if zip_exists and not sha_sidecar_exists:
        warnings.append("ZIP SHA256 sidecar is missing.")
    if zip_exists and sha_sidecar_exists and not sha_match:
        warnings.append("ZIP SHA256 sidecar does not match the current archive content.")
    warnings.extend(
        f"Optional package artifact is not bundled and will need snapshot fallback: {item}"
        for item in missing_optional
    )

    status = "ok"
    if errors:
        status = "error"
    elif warnings:
        status = "warning"

    return {
        "status": status,
        "package_root": str(package_root),
        "zip_path": str(archive_path) if zip_exists else "",
        "sha256_path": str(sha256_path) if sha_sidecar_exists else "",
        "sha256_expected": sha_expected,
        "sha256_actual": sha_actual,
        "sha256_match": sha_match,
        "required_files": {
            key: _artifact_ref(path, package_root=package_root, workspace_root=workspace_root)
            for key, path in required_files.items()
        },
        "optional_files": {
            key: _artifact_ref(path, package_root=package_root, workspace_root=workspace_root)
            for key, path in optional_files.items()
        },
        "errors": errors,
        "warnings": warnings,
    }


def build_review_board_state(ticket_id: str | None = None, workspace: Path | str | None = None) -> dict[str, Any]:
    workspace_root = _workspace_root(workspace)
    package = load_latest_review_package(ticket_id, workspace_root)
    daily_snapshot = load_latest_daily_snapshot(workspace_root)
    review_priority = load_review_priority(ticket_id, workspace_root)
    daily_delta = load_daily_delta(ticket_id, workspace_root)
    decisions = load_review_owner_decisions(ticket_id, workspace_root)
    external_findings = load_external_review_findings(ticket_id, workspace_root)
    verification = verify_sendable_package(package["zip_path"] or package["package_root"], workspace_root)

    snapshot_summary = daily_snapshot["summary"]
    blocker_list: list[str] = []
    for item in package["blockers"]:
        if item not in blocker_list:
            blocker_list.append(item)
    for item in snapshot_summary["blocked_steps"]:
        if item not in blocker_list:
            blocker_list.append(item)
    for item in verification["errors"] + verification["warnings"]:
        if item not in blocker_list:
            blocker_list.append(item)

    package_root = Path(package["package_root"])
    latest_snapshot_root = Path(daily_snapshot["root"])

    def _artifact_entry(label: str, path: str) -> dict[str, Any]:
        artifact_path = Path(path) if path else None
        return {
            "label": label,
            **_artifact_ref(artifact_path, package_root=package_root, workspace_root=workspace_root),
        }

    new_review_keys = {
        str(item).strip()
        for item in list(daily_delta["new_failures"]) + list(daily_delta["new_screenshot_diffs"])
        if str(item).strip()
    }

    def _priority_key(item: dict[str, Any]) -> str:
        profile_id = str(item.get("profile_id", "")).strip()
        filter_name = str(item.get("filter_name", "")).strip()
        return f"battery:{profile_id}:{filter_name}" if profile_id and filter_name else ""

    def _priority_level(item: dict[str, Any], *, is_new: bool) -> str:
        return _priority_level_from_payload(item, is_new=is_new)

    top_review_items = []
    for item in review_priority["ranked_items"]:
        item_key = _priority_key(item)
        is_new = item_key in new_review_keys
        top_review_items.append(
            {
                "profile_id": str(item.get("profile_id", "")),
                "filter_name": str(item.get("filter_name", "")),
                "verdict": str(item.get("verdict", "")),
                "priority_score": _priority_score_from_payload(item, is_new=is_new),
                "priority_level": str(item.get("priority_level", "")) or _priority_level(item, is_new=is_new),
                "attention_category": _priority_attention_category(item, is_new=is_new),
                "signals": _priority_signals_from_payload(item, is_new=is_new),
                "reason": str(item.get("reason", "")),
                "recommendation": str(item.get("recommendation", "")),
                "log_path": str(item.get("log_path", "")),
                "is_new_since_previous_run": is_new,
            }
        )
    top_review_items.sort(
        key=lambda item: (
            int(item.get("priority_score", 0)),
            str(item.get("profile_id", "")).upper(),
            str(item.get("filter_name", "")).lower(),
        ),
        reverse=True,
    )
    top_review_items = top_review_items[:5]

    delta_summary = {
        "has_previous_run": bool(str(daily_delta["previous_created_at"]).strip()),
        "new_failures_count": len(daily_delta["new_failures"]),
        "resolved_failures_count": len(daily_delta["resolved_failures"]),
        "new_screenshot_diffs_count": len(daily_delta["new_screenshot_diffs"]),
        "unchanged_blockers_count": len(daily_delta["unchanged_blockers"]),
        "new_failure_preview": list(daily_delta["new_failures"][:3]),
        "resolved_failure_preview": list(daily_delta["resolved_failures"][:3]),
        "new_screenshot_diff_preview": list(daily_delta["new_screenshot_diffs"][:3]),
        "unchanged_blocker_preview": list(daily_delta["unchanged_blockers"][:3]),
        "review_first_preview": list(daily_delta["top_five_to_review"][:3]),
        "headline": (
            f"+{len(daily_delta['new_failures'])} failures / "
            f"{len(daily_delta['resolved_failures'])} resolved / "
            f"{len(daily_delta['new_screenshot_diffs'])} new diffs / "
            f"{len(daily_delta['unchanged_blockers'])} unchanged blockers"
        ),
        "operator_signal": (
            "No previous run yet; use this as the initial baseline."
            if not str(daily_delta["previous_created_at"]).strip()
            else (
                f"Review {len(daily_delta['new_failures']) + len(daily_delta['new_screenshot_diffs'])} new changes first."
                if daily_delta["new_failures"] or daily_delta["new_screenshot_diffs"]
                else (
                    f"No new failures; {len(daily_delta['unchanged_blockers'])} blocker(s) remain unchanged."
                    if daily_delta["unchanged_blockers"]
                    else "No new failures or diffs; focus on the current review queue."
                )
            )
        ),
    }

    pending_decisions = [item["title"] for item in decisions["sections"] if item.get("pending", False)]
    if pending_decisions:
        operator_next_step = f"Resolve review-owner decision: {pending_decisions[0]}"
    elif top_review_items:
        operator_next_step = (
            f"Open gallery and inspect {top_review_items[0]['profile_id']} / {top_review_items[0]['filter_name']} "
            f"({top_review_items[0]['priority_level']})"
        )
    else:
        operator_next_step = "Open the package artifacts and confirm the current local QA state."

    state = {
        "ticket_id": package["ticket_id"],
        "title": package["title"],
        "scope": package["scope"] or snapshot_summary["scope_profiles"],
        "package_path": package["package_root"],
        "generated_at": package["generated_at"],
        "daily_snapshot_created_at": str(daily_snapshot["payload"].get("created_at", "")),
        "package_zip_path": package["zip_path"],
        "package_sha256_path": package["sha256_path"],
        "visible_dod_progress_percent": package["visible_dod_progress_percent"],
        "package_verification": verification,
        "dod_status_summary": {
            "overall_status": package["overall_status"],
            "blocker_count": len(package["blockers"]),
            "next_question_count": len(package["next_questions"]),
            "visible_progress_percent": package["visible_dod_progress_percent"],
        },
        "daily_snapshot_summary": snapshot_summary,
        "screenshot_battery_counts": {
            "total": snapshot_summary["battery_total"],
            "exact_candidate_ready": snapshot_summary["exact_candidate_ready"],
            "proxy_candidate_ready": snapshot_summary["proxy_candidate_ready"],
            "runtime_crash": snapshot_summary["runtime_crash"],
        },
        "unresolved_families": snapshot_summary["unresolved_families"],
        "review_priority": {
            "source": review_priority["source"],
            "json_path": review_priority["json_path"],
            "markdown_path": review_priority["markdown_path"],
            "top_items": top_review_items,
        },
        "daily_delta": {
            "source": daily_delta["source"],
            "json_path": daily_delta["json_path"],
            "markdown_path": daily_delta["markdown_path"],
            "current_created_at": daily_delta["current_created_at"],
            "previous_created_at": daily_delta["previous_created_at"],
            "new_failures": daily_delta["new_failures"],
            "resolved_failures": daily_delta["resolved_failures"],
            "new_screenshot_diffs": daily_delta["new_screenshot_diffs"],
            "unchanged_blockers": daily_delta["unchanged_blockers"],
            "changed_counts": daily_delta["changed_counts"],
            "top_five_to_review": daily_delta["top_five_to_review"],
        },
        "review_owner_decisions": {
            "path": decisions["path"],
            "json_path": decisions.get("json_path", ""),
            "pending_count": decisions["pending_count"],
            "status_options": list(REVIEW_DECISION_STATUS_OPTIONS),
            "pending_titles": [item["title"] for item in decisions["sections"] if item.get("pending", False)],
            "sections": decisions["sections"],
            "updated_at": decisions.get("updated_at", ""),
        },
        "external_findings": {
            "json_path": external_findings["json_path"],
            "markdown_path": external_findings["markdown_path"],
            "count": external_findings["count"],
            "reported_count": external_findings["reported_count"],
            "items": external_findings["findings"],
            "related_investigation_surfaces": external_findings["related_investigation_surfaces"],
            "headline": (
                f"{external_findings['reported_count']}/{external_findings['count']} reported"
                if external_findings["count"]
                else "No external findings recorded"
            ),
        },
        "open_items": blocker_list,
        "top_review_priority_items": top_review_items,
        "daily_delta_summary": delta_summary,
        "operator_next_step": operator_next_step,
        "manual_review_profiles": _build_manual_review_profiles(
            package,
            workspace_root=workspace_root,
            unresolved_families=snapshot_summary["unresolved_families"],
        ),
        "artifact_references": {
            "package_manifest": _artifact_entry("Package manifest", package["manifest"]["absolute_path"]),
            "review_owner_decisions": _artifact_entry("Review-owner decisions", decisions["path"]),
            "review_owner_decisions_json": _artifact_entry("Review-owner decisions JSON", decisions.get("json_path", "")),
            "dod_matrix": _artifact_entry("DoD matrix", package["dod_matrix"]["absolute_path"]),
            "review_status": _artifact_entry("Review status", package["review_status"]["absolute_path"]),
            "teams_update": _artifact_entry("Teams update", package["teams_update"]["absolute_path"]),
            "candidate_gallery": _artifact_entry("Candidate gallery", package["candidate_gallery"]["absolute_path"]),
            "package_daily_snapshot_json": _artifact_entry("Packaged daily snapshot JSON", package["daily_snapshot_json"]["absolute_path"]),
            "latest_daily_snapshot_json": _artifact_entry("Latest daily snapshot JSON", str(latest_snapshot_root / "daily-3d-car-qa-summary.json")),
            "latest_daily_snapshot_markdown": _artifact_entry("Latest daily snapshot markdown", str(latest_snapshot_root / "daily-3d-car-qa-summary.md")),
            "review_priority_json": _artifact_entry("Review-priority JSON", review_priority["json_path"]),
            "review_priority_markdown": _artifact_entry("Review-priority markdown", review_priority["markdown_path"]),
            "daily_delta_json": _artifact_entry("Daily delta JSON", daily_delta["json_path"]),
            "daily_delta_markdown": _artifact_entry("Daily delta markdown", daily_delta["markdown_path"]),
            "external_findings_json": _artifact_entry("External findings JSON", external_findings["json_path"]),
            "external_findings_markdown": _artifact_entry("External findings markdown", external_findings["markdown_path"]),
            "package_zip": _artifact_entry("Package ZIP", package["zip_path"]),
            "package_sha256": _artifact_entry("Package SHA256 sidecar", package["sha256_path"]),
        },
    }
    state["review_owner_update_text"] = build_review_owner_update(state)
    state["morning_digest"] = build_digest_json(state)
    state["morning_digest_text"] = build_morning_digest(state)
    return state
