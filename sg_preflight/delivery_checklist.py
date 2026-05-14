from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import re
from typing import Any

from openpyxl import load_workbook

from sg_preflight.bmw_delivery import candidate_bmw_profile_ids


WORKBOOK_NAME = "Delivery Data - BMW.xlsx"
READ_ONLY_BANNER = (
    "Delivery checklist data is read-only from the operator-local Excel workbook. "
    "SGFX does not run the delivery checklist or modify the workbook."
)
_CHECK_COLUMNS = {
    "export_size": "Export Size",
    "screenshots": "Screenshots",
    "interface": "Interface",
    "perspectives": "Perspectives",
}
_PROFILE_KEYS = {"profile_id", "car", "car_model", "model", "vehicle", "baureihe"}
_HEADER_ALIASES = {
    "profile": "profile_id",
    "profileid": "profile_id",
    "car": "car",
    "carmodel": "car_model",
    "model": "model",
    "vehicle": "vehicle",
    "baureihe": "baureihe",
    "lasttested": "last_tested",
    "lasttest": "last_tested",
    "tested": "last_tested",
    "date": "last_tested",
    "timestamp": "last_tested",
    "svnrevision": "svn_revision",
    "svnrev": "svn_revision",
    "svn": "svn_revision",
    "changelogrevision": "changelog_revision",
    "changelogrev": "changelog_revision",
    "changelog": "changelog_revision",
    "exportsize": "export_size",
    "export": "export_size",
    "screenshots": "screenshots",
    "screenshot": "screenshots",
    "interface": "interface",
    "perspectives": "perspectives",
    "perspective": "perspectives",
}


def _workspace_root(workspace: Path | str | None = None) -> Path:
    root = Path(workspace) if workspace is not None else Path(__file__).resolve().parents[1]
    return root.resolve()


def _brand_label(brand: str | None) -> str:
    value = str(brand or "BMW").strip()
    return value.upper() if value.casefold() == "bmw" else value.title()


def _workbook_name_for_brand(brand: str | None) -> str:
    return f"Delivery Data - {_brand_label(brand)}.xlsx"


def resolve_delivery_checklist_workbook(
    *,
    workspace: Path | str | None = None,
    workbook_path: Path | str | None = None,
    brand: str | None = "BMW",
) -> Path:
    if workbook_path is not None:
        return Path(workbook_path).resolve()
    root = _workspace_root(workspace)
    workbook_name = _workbook_name_for_brand(brand)
    candidates = (
        root / "repositories" / "trunk" / ".pdx" / "checkers" / "deliveryChecklist" / workbook_name,
        root / ".pdx" / "checkers" / "deliveryChecklist" / workbook_name,
        root / workbook_name,
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0].resolve()


def _header_key(value: object) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())
    return _HEADER_ALIASES.get(normalized, "")


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="minutes")
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()


def _profile_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _candidate_profile_tokens(profile_id: str) -> set[str]:
    tokens = {_profile_token(item) for item in candidate_bmw_profile_ids(profile_id)}
    normalized = profile_id.strip()
    if normalized:
        tokens.add(_profile_token(normalized))
    return {token for token in tokens if token}


def _normalize_status(value: object) -> str:
    raw = _cell_text(value)
    if not raw:
        return "pending"
    normalized = re.sub(r"[^a-z0-9]+", " ", raw.casefold()).strip()
    compact = normalized.replace(" ", "")
    if compact in {"na", "n/a", "notapplicable", "notavailable", "skip", "skipped"}:
        return "not_applicable"
    if compact in {"ok", "pass", "passed", "done", "green", "success", "successful", "yes", "true"}:
        return "passed"
    if compact in {"nok", "notok", "fail", "failed", "failure", "error", "red", "false"}:
        return "failed"
    if "block" in normalized:
        return "blocked"
    if compact in {"pending", "open", "todo", "wip", "waiting"}:
        return "pending"
    return normalized.replace(" ", "_") or "unknown"


def _status_text(status: str) -> str:
    return status.replace("_", " ")


def _workbook_metadata(workbook_path: Path, *, brand: str | None, row_count: int = 0) -> dict[str, Any]:
    stat = workbook_path.stat() if workbook_path.exists() else None
    return {
        "brand": _brand_label(brand),
        "file_size": int(stat.st_size) if stat else 0,
        "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds") if stat else "",
        "row_count": row_count,
    }


def _missing_payload(
    profile_id: str,
    workbook_path: Path,
    status: str,
    summary: str,
    *,
    brand: str | None,
) -> dict[str, Any]:
    return {
        "profile_id": profile_id.strip(),
        "matched_profile_id": "",
        "status": status,
        "data_available": False,
        "workbook_path": str(workbook_path),
        "worksheet": "",
        "row": 0,
        "last_tested": "",
        "svn_revision": "",
        "changelog_revision": "",
        "workbook_metadata": _workbook_metadata(workbook_path, brand=brand),
        "checks": [],
        "summary": summary,
        "note": "Read-only delivery-checklist evidence guidance; not approval or delivery signoff.",
        "is_approval": False,
    }


def _row_mapping(values: tuple[object, ...], header: dict[int, str]) -> dict[str, object]:
    mapped: dict[str, object] = {}
    for index, canonical in header.items():
        if index < len(values):
            mapped[canonical] = values[index]
    return mapped


def _find_header(values: tuple[object, ...]) -> dict[int, str]:
    header: dict[int, str] = {}
    for index, value in enumerate(values):
        key = _header_key(value)
        if key:
            header[index] = key
    has_profile = any(key in _PROFILE_KEYS for key in header.values())
    has_check = any(key in _CHECK_COLUMNS for key in header.values())
    return header if has_profile and has_check else {}


def read_delivery_checklist(
    *,
    profile_id: str,
    workspace: Path | str | None = None,
    workbook_path: Path | str | None = None,
    brand: str | None = "BMW",
) -> dict[str, Any]:
    workbook = resolve_delivery_checklist_workbook(workspace=workspace, workbook_path=workbook_path, brand=brand)
    profile = profile_id.strip()
    if not workbook.exists():
        return _missing_payload(
            profile,
            workbook,
            "no_workbook",
            f"delivery-checklist data unavailable: workbook not found for {profile or 'profile'}: {workbook}",
            brand=brand,
        )

    candidate_tokens = _candidate_profile_tokens(profile)
    try:
        loaded = load_workbook(workbook, read_only=True, data_only=True)
    except Exception as exc:
        return _missing_payload(
            profile,
            workbook,
            "unreadable",
            f"delivery-checklist data unavailable: workbook could not be read: {exc}",
            brand=brand,
        )

    try:
        workbook_row_count = 0
        for worksheet in loaded.worksheets:
            header: dict[int, str] = {}
            for row_index, values in enumerate(worksheet.iter_rows(values_only=True), start=1):
                workbook_row_count += 1
                if not header:
                    header = _find_header(values)
                    continue
                mapped = _row_mapping(values, header)
                profile_value = next((_cell_text(mapped.get(key)) for key in _PROFILE_KEYS if mapped.get(key)), "")
                if not profile_value:
                    continue
                if _profile_token(profile_value) not in candidate_tokens:
                    continue
                checks = [
                    {
                        "key": key,
                        "label": label,
                        "status": _normalize_status(mapped.get(key)),
                        "raw_value": _cell_text(mapped.get(key)),
                    }
                    for key, label in _CHECK_COLUMNS.items()
                    if key in mapped
                ]
                check_summary = "; ".join(
                    f"{item['label']} {_status_text(str(item['status']))}" for item in checks
                )
                summary = f"Delivery checklist {profile}: {check_summary}." if check_summary else f"Delivery checklist {profile}: no check columns found."
                return {
                    "profile_id": profile,
                    "matched_profile_id": profile_value,
                    "status": "available",
                    "data_available": True,
                    "workbook_path": str(workbook),
                    "worksheet": worksheet.title,
                    "row": row_index,
                    "last_tested": _cell_text(mapped.get("last_tested")),
                    "svn_revision": _cell_text(mapped.get("svn_revision")),
                    "changelog_revision": _cell_text(mapped.get("changelog_revision")),
                    "workbook_metadata": _workbook_metadata(workbook, brand=brand, row_count=workbook_row_count),
                    "checks": checks,
                    "summary": summary,
                    "note": "Read-only delivery-checklist evidence guidance; not approval or delivery signoff.",
                    "is_approval": False,
                }
    finally:
        loaded.close()

    return _missing_payload(
        profile,
        workbook,
        "profile_not_found",
        f"delivery-checklist data unavailable: workbook was found, but no row matched {profile}.",
        brand=brand,
    )


def read_delivery_checklists_for_profiles(
    profile_ids: list[str] | tuple[str, ...],
    *,
    workspace: Path | str | None = None,
    workbook_path: Path | str | None = None,
    brand: str | None = "BMW",
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for profile_id in profile_ids:
        payload = read_delivery_checklist(profile_id=profile_id, workspace=workspace, workbook_path=workbook_path, brand=brand)
        items.append(payload)
    return items


def delivery_checklist_digest_items(state: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = state.get("delivery_checklist", [])
    if isinstance(raw_items, dict):
        raw_items = [raw_items]
    if not isinstance(raw_items, list):
        return []
    items: list[dict[str, Any]] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        profile = str(raw_item.get("profile_id", "")).strip() or "profile"
        detail = str(raw_item.get("summary", "")).strip()
        if not detail:
            check_parts = [
                f"{check.get('label', check.get('key', 'check'))} {_status_text(str(check.get('status', 'pending')))}"
                for check in raw_item.get("checks", [])
                if isinstance(check, dict)
            ]
            detail = "; ".join(check_parts)
        items.append(
            {
                "label": f"Delivery checklist {profile}",
                "status": "prepared" if raw_item.get("data_available") else str(raw_item.get("status", "not_available")),
                "detail": detail,
                "source": "delivery_checklist",
                "path": str(raw_item.get("workbook_path", "")).strip(),
                "note": "Read-only delivery-checklist evidence guidance; not approval or delivery signoff.",
            }
        )
    return items


def render_delivery_checklist_markdown(payload: dict[str, Any]) -> str:
    lines = [
        READ_ONLY_BANNER,
        "",
        f"# Delivery Checklist Evidence - {payload.get('profile_id', 'profile')}",
        "",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- Data available: `{str(bool(payload.get('data_available'))).lower()}`",
    ]
    workbook_path = str(payload.get("workbook_path", "")).strip()
    if workbook_path:
        lines.append(f"- Workbook: `{workbook_path}`")
    metadata = payload.get("workbook_metadata", {})
    if isinstance(metadata, dict):
        brand = str(metadata.get("brand", "")).strip()
        modified_at = str(metadata.get("modified_at", "")).strip()
        row_count = int(metadata.get("row_count", 0) or 0)
        if brand:
            lines.append(f"- Brand: `{brand}`")
        if modified_at:
            lines.append(f"- Workbook modified: `{modified_at}`")
        if row_count:
            lines.append(f"- Rows scanned: `{row_count}`")
    summary = str(payload.get("summary", "")).strip()
    if summary:
        lines.extend(["", summary])
    checks = payload.get("checks", [])
    if isinstance(checks, list) and checks:
        lines.extend(["", "## Recorded Tests"])
        for check in checks:
            if not isinstance(check, dict):
                continue
            label = str(check.get("label", check.get("key", "check"))).strip()
            status = _status_text(str(check.get("status", "pending")))
            raw_value = str(check.get("raw_value", "")).strip()
            suffix = f" (raw: `{raw_value}`)" if raw_value and raw_value.casefold() != status.casefold() else ""
            lines.append(f"- {label}: `{status}`{suffix}")
    lines.extend(["", "Manual delivery review remains required."])
    return "\n".join(lines).rstrip() + "\n"


def render_delivery_checklist_text(payload: dict[str, Any]) -> str:
    lines = [
        READ_ONLY_BANNER,
        str(payload.get("summary", "Delivery checklist status unavailable.")),
        "Manual delivery review remains required.",
    ]
    workbook_path = str(payload.get("workbook_path", "")).strip()
    if workbook_path:
        lines.append(f"Workbook: {workbook_path}")
    for check in payload.get("checks", []):
        if not isinstance(check, dict):
            continue
        label = str(check.get("label", check.get("key", "check"))).strip()
        status = _status_text(str(check.get("status", "pending")))
        raw_value = str(check.get("raw_value", "")).strip()
        suffix = f" (raw: {raw_value})" if raw_value and raw_value.casefold() != status.casefold() else ""
        lines.append(f"- {label}: {status}{suffix}")
    return "\n".join(lines)
