from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from sg_preflight.bmw_delivery import discover_bmw_models_repo, resolve_bmw_profile_id
from sg_preflight.full_qa_history import read_full_qa_run_history
from sg_preflight.profiles import PROFILE_SCOPE_DEFAULT, RunProfile, list_run_profiles


CONFIG_SUFFIXES = {".lua", ".yaml", ".yml", ".json"}


def _parse_utc(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_utc(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _latest_config_mtime(root: Path) -> dict[str, Any]:
    if not root.is_dir():
        return {"status": "missing", "root": str(root), "newest_mtime": "", "newest_path": ""}
    newest_mtime = 0.0
    newest_path = ""
    try:
        candidates = root.rglob("*")
        for path in candidates:
            if not path.is_file() or path.suffix.lower() not in CONFIG_SUFFIXES:
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime > newest_mtime:
                newest_mtime = mtime
                newest_path = str(path)
    except OSError:
        return {"status": "unavailable", "root": str(root), "newest_mtime": "", "newest_path": ""}
    if not newest_path:
        return {"status": "missing", "root": str(root), "newest_mtime": "", "newest_path": ""}
    return {
        "status": "available",
        "root": str(root),
        "newest_mtime": _format_utc(newest_mtime),
        "newest_path": newest_path,
    }


def _newest_source(sources: list[dict[str, Any]]) -> tuple[datetime | None, str]:
    newest: datetime | None = None
    newest_path = ""
    for source in sources:
        if source.get("status") != "available":
            continue
        parsed = _parse_utc(str(source.get("newest_mtime", "")))
        if parsed is not None and (newest is None or parsed > newest):
            newest = parsed
            newest_path = str(source.get("newest_path", ""))
    return newest, newest_path


def _bmw_profile_root(profile: RunProfile, bmw_repo: Path) -> Path:
    bmw_id = profile.bmw_profile_id or resolve_bmw_profile_id(profile.profile_id, bmw_repo)
    return bmw_repo / "cars" / profile.brand / bmw_id


def detect_changed_profiles_since_last_run(
    *,
    workspace: Path | str,
    bmw_root: Path | str | None = None,
    profiles: Iterable[RunProfile] | None = None,
) -> dict[str, Any]:
    workspace_path = Path(workspace).resolve()
    bmw_repo = Path(bmw_root).resolve() if bmw_root is not None else discover_bmw_models_repo(workspace_path).resolve()
    profile_list = (
        list(profiles)
        if profiles is not None
        else list_run_profiles(workspace_path, bmw_root=bmw_repo, profile_scope=PROFILE_SCOPE_DEFAULT)
    )
    rows: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    unavailable_count = 0
    not_run_count = 0
    for profile in profile_list:
        history = read_full_qa_run_history(profile.profile_id)
        last_raw = str(history.get("last_successful_run_at", "")).strip()
        last_run = _parse_utc(last_raw)
        if last_run is None:
            not_run_count += 1
        sources = [
            {"source": "bmw_git", **_latest_config_mtime(_bmw_profile_root(profile, bmw_repo))},
            {"source": "svn", **_latest_config_mtime(profile.source_project_root())},
        ]
        if not any(source.get("status") == "available" for source in sources):
            unavailable_count += 1
        newest, newest_path = _newest_source(sources)
        changed_since_last = bool(last_run is not None and newest is not None and newest > last_run)
        status = (
            "changed"
            if changed_since_last
            else "not_run"
            if last_run is None
            else "available"
            if newest is not None
            else "unavailable"
        )
        row = {
            "profile_id": profile.profile_id,
            "label": profile.label,
            "status": status,
            "changed_since_last_run": changed_since_last,
            "last_qa_pass_at": last_raw,
            "newest_config_mtime": newest.isoformat().replace("+00:00", "Z") if newest is not None else "",
            "newest_config_path": newest_path,
            "sources": sources,
            "manual_review_required": True,
            "is_approval": False,
        }
        rows.append(row)
        if changed_since_last:
            changed.append(row)
    status = "unavailable" if rows and unavailable_count == len(rows) else "available"
    if not rows:
        status = "unavailable"
    summary = (
        "Change-detection unavailable; refresh manually."
        if status == "unavailable"
        else f"{len(changed)} profile(s) changed since last successful local run; {not_run_count} without run history."
    )
    return {
        "schema_version": 1,
        "status": status,
        "workspace": str(workspace_path),
        "bmw_root": str(bmw_repo),
        "summary": summary,
        "changed_count": len(changed),
        "not_run_count": not_run_count,
        "unavailable_count": unavailable_count,
        "changed_profile_ids": [str(row["profile_id"]) for row in changed],
        "changed_profiles": changed,
        "profiles": rows,
        "manual_review_required": True,
        "is_approval": False,
    }
