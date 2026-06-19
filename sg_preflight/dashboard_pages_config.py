from __future__ import annotations

from functools import wraps
from pathlib import Path
from typing import Any, Callable


_MAIN_GLOBAL_NAMES = (
    "Any",
    "Callable",
    "Path",
    "STATUS_DELIVERED",
    "STATUS_NOT_DELIVERED_YET",
    "STATUS_UNKNOWN",
    "CAUTIOUS_BASELINE_LABEL",
    "IMPACT_REVIEW_LABEL",
    "MAPPING_REVIEW_LABEL",
    "MISSING_EXPECTED_LABEL",
    "NO_RUNTIME_LABEL",
    "SIGNIFICANT_CHANGE_LABEL",
    "UNREADABLE_LAYOUT_LABEL",
    "QUALITY_HERO_CONFLUENCE_ANCHOR",
    "DELIVERY_CHECKLIST_CONFLUENCE_ANCHOR",
    "BMW_PIPELINE_PYTHON_CONFLUENCE_ANCHOR",
    "SG_DAILY_CONFLUENCE_ANCHOR",
    "DASHBOARD_GUARDRAILS",
    "DELIVERY_CHECKLIST_EMPTY_NOTE",
    "SCREENSHOT_TEST_STATE_EMPTY_NOTE",
    "RISK_SCORE_EMPTY_NOTE",
    "CROSS_CAR_COMPARISON_EMPTY_NOTE",
    "DAILY_DIGEST_EMPTY_NOTE",
    "TEAM_DIGEST_BOARD_EMPTY_NOTE",
    "OPERATOR_HANDOFF_EMPTY_NOTE",
    "SCREENSHOT_TEST_STATE_OWNERSHIP_NOTE",
    "GENERATE_WORKBOOK_ACTION_ID",
    "GENERATE_WORKBOOK_ACTION_LABEL",
    "GENERATE_WORKBOOK_TIMEOUT_SECONDS",
    "SCREENSHOT_CAPTURE_ACTION_ID",
    "SCREENSHOT_CAPTURE_ACTION_LABEL",
    "SCREENSHOT_CAPTURE_TIMEOUT_SECONDS",
    "DAILY_DIGEST_BUILD_PACKAGE_ACTION_ID",
    "DAILY_DIGEST_BUILD_PACKAGE_ACTION_LABEL",
    "QUALITY_HERO_REPORT_ACTION_ID",
    "QUALITY_HERO_REPORT_ACTION_LABEL",
    "DAILY_DIGEST_TICKET_ID_PLACEHOLDER",
    "_DAILY_DIGEST_PARTIAL_SECTION_KEYS",
    "_source_repo_root_from_value",
    "_preferred_source_repo_root",
    "_source_repo_root_candidates",
    "_dashboard_status",
    "_payload_summary",
    "_payload_items",
    "_sanitized_payload",
    "_int_payload_value",
    "_screenshot_empty_note",
    "_reader_page",
    "_section_count",
    "_daily_digest_has_partial_signal",
    "_dashboard_active_ticket_id",
    "read_delivery_checklist",
    "build_delivery_workbook_trigger",
    "build_dependency_onboarding_status",
    "build_delivery_readiness_board",
    "build_cross_domain_delivery_board",
    "build_perspectives_inventory_board",
    "build_disabled_tests_board",
    "build_api_version_coverage_board",
    "build_country_variant_coverage_board",
    "build_export_size_trend_board",
    "build_setup_doctor_report",
    "list_workflows",
    "workflow_contracts",
    "build_onboarding_guide",
    "read_bmw_screenshot_state",
    "check_screenshot_capture_environment",
    "check_screenshot_export_artifact",
    "read_per_car_risk_score",
    "build_cross_car_comparison",
    "build_latest_daily_digest",
    "build_team_daily_digest_board",
    "build_operator_handoff_snapshot",
)


def _sync_main_globals() -> None:
    from sg_preflight.dashboard import main as dashboard_main

    for name in _MAIN_GLOBAL_NAMES:
        if hasattr(dashboard_main, name):
            globals()[name] = getattr(dashboard_main, name)


def _with_main_globals(func: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(func)
    def _wrapped(*args: Any, **kwargs: Any) -> Any:
        _sync_main_globals()
        return func(*args, **kwargs)

    return _wrapped


def _int_payload_value(payload: dict[str, Any], key: str) -> int:
    try:
        return int(payload.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0

def _screenshot_empty_note(payload: dict[str, Any]) -> str:
    if _int_payload_value(payload, "actual_count") == 0 and _int_payload_value(payload, "diff_count") == 0:
        return SCREENSHOT_TEST_STATE_EMPTY_NOTE
    return ""

def _reader_page(
    *,
    page_id: str,
    title: str,
    tagline: str,
    reader: Callable[[], dict[str, Any]],
    workspace: Path | str | None = None,
    ownership_note: str = "",
) -> dict[str, Any]:
    try:
        payload = reader()
    except Exception as exc:
        return {
            "id": page_id,
            "title": title,
            "tagline": tagline,
            "ownership_note": ownership_note,
            "status": "unknown",
            "data_available": False,
            "summary": f"{title} could not be read: {exc}",
            "items": [],
            "payload": {},
        }
    raw_status = str(payload.get("status", "unknown") or "unknown")
    data_available = bool(payload.get("data_available", False))
    page = {
        "id": page_id,
        "title": title,
        "tagline": tagline,
        "ownership_note": ownership_note,
        "status": _dashboard_status(raw_status, data_available),
        "raw_status": raw_status,
        "data_available": data_available,
        "summary": _payload_summary(payload, title, workspace=workspace),
        "items": _payload_items(payload),
        "payload": _sanitized_payload(payload),
    }
    if page_id == "screenshot-test-state":
        page["empty_state_note"] = _screenshot_empty_note(payload)
    return page

def _delivery_checklist_page(
    profile_id: str,
    workspace: Path,
    *,
    bmw_root: Path | str | None = None,
    setup_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    page = _reader_page(
        page_id="delivery-checklist",
        title="Delivery Checklist",
        tagline="Workbook evidence per delivery profile (read-only).",
        reader=lambda: read_delivery_checklist(
            profile_id=profile_id,
            workspace=workspace,
            bmw_root=bmw_root,
            enable_auto_generate=True,
        ),
        workspace=workspace,
    )
    page["confluence_anchors"] = [DELIVERY_CHECKLIST_CONFLUENCE_ANCHOR]
    page["setup_status"] = setup_status or build_dependency_onboarding_status(workspace=workspace, bmw_root=bmw_root)
    page["workbook_trigger"] = build_delivery_workbook_trigger(
        profile_id=profile_id,
        workspace=workspace,
        bmw_root=bmw_root,
    )
    if page.get("status") != "unavailable":
        return page
    page["empty_state_note"] = DELIVERY_CHECKLIST_EMPTY_NOTE
    preflight = page["workbook_trigger"].get("preflight", {})
    page["actions"] = [
        {
            "id": GENERATE_WORKBOOK_ACTION_ID,
            "label": GENERATE_WORKBOOK_ACTION_LABEL,
            "requires_confirmation": True,
            "timeout_seconds": GENERATE_WORKBOOK_TIMEOUT_SECONDS,
            "preflight": preflight,
            "disabled": not bool(preflight.get("can_run", False)),
            "confirmation_message": str(preflight.get("confirmation_message", "")),
            "confluence_anchor": DELIVERY_CHECKLIST_CONFLUENCE_ANCHOR,
        }
    ]
    return page

def _delivery_readiness_payload(
    workspace: Path,
    bmw_root: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    selected_repo_root = _source_repo_root_from_value(repo_root) or _preferred_source_repo_root(workspace)
    board = build_delivery_readiness_board(
        selected_repo_root,
        workspace_root=workspace,
        bmw_repo_root=Path(bmw_root) if bmw_root is not None else None,
    ).to_dict()
    counts = board.get("counts", {})
    catalog = board.get("catalog", {})
    source_state = str(board.get("source_state", "unknown"))
    ready = source_state == "ready"
    total = int(counts.get("total", 0) or 0)
    delivered = int(counts.get(STATUS_DELIVERED, 0) or 0)
    not_delivered = int(counts.get(STATUS_NOT_DELIVERED_YET, 0) or 0)
    unknown = int(counts.get(STATUS_UNKNOWN, 0) or 0)
    entries = [entry for entry in board.get("entries", []) if isinstance(entry, dict)]
    rows: list[dict[str, str]] = [
        {
            "label": "Reading from",
            "status": source_state,
            "detail": str(board.get("repo_root", "")),
        },
        {
            "label": "Cars listed",
            "status": str(total),
            "detail": f"{delivered} delivered; {not_delivered} not delivered yet; {unknown} unknown/no changelog.",
        },
        {
            "label": "BMW catalog",
            "status": str(catalog.get("catalog_state", "not_checked")),
            "detail": (
                f"{catalog.get('catalog_targets_mapped_count', 0)} mapped; "
                f"{catalog.get('catalog_targets_missing_dir_count', 0)} missing dirs; "
                f"{catalog.get('dirs_without_catalog_count', 0)} listed without catalog."
            ),
        },
    ]
    for entry in entries[:18]:
        date = str(entry.get("delivered_date", "")).strip()
        version = str(entry.get("version", "")).strip() or "version unknown"
        detail_parts = [
            str(entry.get("relative_path", "")).strip(),
            version,
        ]
        if date:
            detail_parts.append(date)
        rows.append(
            {
                "label": f"{entry.get('brand', '')} {entry.get('model_id', '')}".strip(),
                "status": str(entry.get("status_label", entry.get("status", "unknown"))),
                "detail": "; ".join(part for part in detail_parts if part),
            }
        )
    if len(entries) > 18:
        rows.append(
            {
                "label": "Additional cars",
                "status": str(len(entries) - 18),
                "detail": "Open the full payload or CLI export for the remaining rows.",
            }
        )
    board["status"] = "available" if ready else "missing"
    board["data_available"] = ready
    board["selected_source_root"] = str(board.get("repo_root", ""))
    board["source_root_candidates"] = _source_repo_root_candidates(workspace)
    board["summary"] = (
        f"{total} car(s): {delivered} delivered, {not_delivered} not delivered yet, "
        f"{unknown} unknown/no changelog. Reading from {board.get('repo_root', '')}. Source: {source_state}."
    )
    board["board_rows"] = rows
    return board

def _delivery_readiness_page(workspace: Path, *, bmw_root: Path | str | None = None) -> dict[str, Any]:
    page = _reader_page(
        page_id="delivery-readiness",
        title="Delivery Readiness",
        tagline="Per-car CHANGELOG delivery status from local SVN and BMW catalog evidence.",
        reader=lambda: _delivery_readiness_payload(workspace, bmw_root),
        workspace=workspace,
        ownership_note="Evidence only - delivery approval remains manual: SG peer, Wombat merge, and BMW CCB.",
    )
    page["confluence_anchors"] = [DELIVERY_CHECKLIST_CONFLUENCE_ANCHOR]
    payload = page.get("payload", {}) if isinstance(page.get("payload"), dict) else {}
    page["source_selector"] = {
        "selected_source_root": str(payload.get("selected_source_root", "")),
        "source_root_candidates": list(payload.get("source_root_candidates", [])),
    }
    return page

def _cross_domain_delivery_payload(
    workspace: Path,
    bmw_root: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    selected_repo_root = _source_repo_root_from_value(repo_root) or _preferred_source_repo_root(workspace)
    board = build_cross_domain_delivery_board(
        selected_repo_root,
        workspace_root=workspace,
        bmw_repo_root=Path(bmw_root) if bmw_root is not None else None,
    ).to_dict()
    counts = board.get("counts", {})
    if not isinstance(counts, dict):
        counts = {}
    by_domain = counts.get("by_domain", {})
    if not isinstance(by_domain, dict):
        by_domain = {}
    drift = counts.get("version_drift", {})
    if not isinstance(drift, dict):
        drift = {}
    source_state = str(board.get("source_state", "unknown"))
    ready = source_state == "ready"
    total = int(counts.get("total", 0) or 0)
    delivered = int(counts.get(STATUS_DELIVERED, 0) or 0)
    not_delivered = int(counts.get(STATUS_NOT_DELIVERED_YET, 0) or 0)
    unknown = int(counts.get(STATUS_UNKNOWN, 0) or 0)

    def _domain_total(domain_id: str) -> int:
        value = by_domain.get(domain_id, {})
        return int(value.get("total", 0) or 0) if isinstance(value, dict) else 0

    rows: list[dict[str, str]] = [
        {
            "label": "Reading from",
            "status": source_state,
            "detail": str(board.get("repo_root", "")),
        },
        {
            "label": "Scope",
            "status": str(total),
            "detail": (
                f"{_domain_total('cars')} Cars; "
                f"{_domain_total('widgets')} Widgets; "
                f"{_domain_total('ambient')} Ambient."
            ),
        },
        {
            "label": "Delivery status",
            "status": str(delivered),
            "detail": f"{not_delivered} not delivered yet; {unknown} unknown/no changelog.",
        },
        {
            "label": "Version drift",
            "status": str(len(drift.get("items", [])) if isinstance(drift.get("items", []), list) else 0),
            "detail": (
                f"Ramses max {drift.get('max_ramses') or 'not found'}; "
                f"RaCo Headless max {drift.get('max_raco_headless') or 'not found'}."
            ),
        },
    ]
    entries = [entry for entry in board.get("entries", []) if isinstance(entry, dict)]
    domain_labels = {"cars": "Cars", "widgets": "Widgets", "ambient": "Ambient"}
    for entry in entries[:18]:
        domain_id = str(entry.get("domain", ""))
        domain_label = domain_labels.get(domain_id, domain_id.title() or "Domain")
        version = str(entry.get("version", "")).strip() or "version unknown"
        brand = str(entry.get("brand", "")).strip()
        detail_parts = [
            str(entry.get("relative_path", "")).strip(),
            f"status {entry.get('delivery_status_label', '')}",
            version,
            f"Ramses {entry.get('ramses') or 'unknown'}",
            f"RaCo {entry.get('raco_headless') or 'unknown'}",
            f"{entry.get('rca_total_bytes', 0)} byte(s) RCA",
        ]
        if brand:
            detail_parts.insert(1, brand)
        rows.append(
            {
                "label": f"{domain_label} / {entry.get('item_id', '')}".strip(),
                "status": str(entry.get("delivery_status_label", entry.get("delivery_status", "unknown"))),
                "detail": "; ".join(part for part in detail_parts if part),
            }
        )
    if len(entries) > 18:
        rows.append(
            {
                "label": "Additional cross-domain rows",
                "status": str(len(entries) - 18),
                "detail": "Open the CLI JSON or evidence export for all Cars, Widgets, and Ambient rows.",
            }
        )
    board["status"] = "available" if ready else "missing"
    board["data_available"] = ready
    board["selected_source_root"] = str(board.get("repo_root", ""))
    board["source_root_candidates"] = _source_repo_root_candidates(workspace)
    board["summary"] = (
        f"{total} item(s) across Cars, Widgets, and Ambient: {delivered} delivered, "
        f"{not_delivered} not delivered yet, {unknown} unknown/no changelog; "
        f"version drift evidence: {len(drift.get('items', [])) if isinstance(drift.get('items', []), list) else 0} row(s). "
        f"Reading from {board.get('repo_root', '')}. Source: {source_state}."
    )
    board["board_rows"] = rows
    return board

def _cross_domain_delivery_page(workspace: Path, *, bmw_root: Path | str | None = None) -> dict[str, Any]:
    page = _reader_page(
        page_id="cross-domain-delivery",
        title="Cross-Domain Delivery",
        tagline="Cars, Widgets, and Ambient delivery/version evidence from local SVN.",
        reader=lambda: _cross_domain_delivery_payload(workspace, bmw_root),
        workspace=workspace,
        ownership_note=(
            "Evidence only - version drift is shown as review evidence, not an automated delivery verdict."
        ),
    )
    payload = page.get("payload", {}) if isinstance(page.get("payload"), dict) else {}
    page["source_selector"] = {
        "selected_source_root": str(payload.get("selected_source_root", "")),
        "source_root_candidates": list(payload.get("source_root_candidates", [])),
    }
    return page

def _perspectives_inventory_payload(
    workspace: Path,
    bmw_root: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    _ = bmw_root
    selected_repo_root = _source_repo_root_from_value(repo_root) or _preferred_source_repo_root(workspace)
    board = build_perspectives_inventory_board(
        selected_repo_root,
        workspace_root=workspace,
    ).to_dict()
    counts = board.get("counts", {})
    if not isinstance(counts, dict):
        counts = {}
    source_state = str(board.get("source_state", "unknown"))
    ready = source_state == "ready"
    car_total = _int_payload_value(counts, "car_total")
    file_total = _int_payload_value(counts, "file_total")
    brand_reference_count = _int_payload_value(counts, "brand_reference_count")
    display_group_count = _int_payload_value(counts, "display_type_group_count")
    peer_outlier_count = _int_payload_value(counts, "peer_outlier_count")
    structural_issue_count = _int_payload_value(counts, "structural_issue_count")
    malformed_count = _int_payload_value(counts, "malformed_file_count")
    no_perspectives_count = _int_payload_value(counts, "no_perspectives_count")
    rows: list[dict[str, str]] = [
        {
            "label": "Reading from",
            "status": source_state,
            "detail": str(board.get("repo_root", "")),
        },
        {
            "label": "Scope",
            "status": str(file_total),
            "detail": f"{car_total} car(s); {display_group_count} display-type group(s); {brand_reference_count} brand reference file(s).",
        },
        {
            "label": "Brand references",
            "status": str(brand_reference_count),
            "detail": "Brand-level perspectives files are shown as references and excluded from car peer groups.",
        },
        {
            "label": "Peer evidence",
            "status": str(peer_outlier_count),
            "detail": "Common scenes are inferred from same-display-type peers at a 60% threshold.",
        },
        {
            "label": "Structural checks",
            "status": str(structural_issue_count),
            "detail": f"{malformed_count} malformed file(s); {no_perspectives_count} car(s) with no perspectives files.",
        },
    ]
    entries = [entry for entry in board.get("entries", []) if isinstance(entry, dict)]
    for entry in entries[:18]:
        flags = entry.get("peer_flags", [])
        if isinstance(flags, list) and flags:
            peer_detail = "; ".join(str(flag) for flag in flags)
        else:
            peer_detail = str(entry.get("comparison_note", ""))
        structural_count = _int_payload_value(entry, "structural_issue_scene_count")
        detail_parts = [
            str(entry.get("relative_path", "")),
            f"{entry.get('scene_count', 0)} scene(s)",
            f"{structural_count} structural issue scene(s)",
            peer_detail,
        ]
        rows.append(
            {
                "label": f"{entry.get('display_type', '')} / {entry.get('model_id', '')}".strip(),
                "status": str(entry.get("scene_count", 0)),
                "detail": "; ".join(part for part in detail_parts if part),
            }
        )
    if len(entries) > 18:
        rows.append(
            {
                "label": "Additional perspectives rows",
                "status": str(len(entries) - 18),
                "detail": "Open the CLI JSON or evidence export for all perspectives inventory rows.",
            }
        )
    brand_references = [entry for entry in board.get("brand_reference_entries", []) if isinstance(entry, dict)]
    for entry in brand_references[:6]:
        rows.append(
            {
                "label": f"Brand reference / {entry.get('brand', '')} {entry.get('display_type', '')}".strip(),
                "status": str(entry.get("scene_count", 0)),
                "detail": f"{entry.get('relative_path', '')}; {entry.get('scene_count', 0)} scene(s).",
            }
        )
    if len(brand_references) > 6:
        rows.append(
            {
                "label": "Additional brand references",
                "status": str(len(brand_references) - 6),
                "detail": "Open the CLI JSON or evidence export for all brand-level perspectives references.",
            }
        )
    no_perspectives = [entry for entry in board.get("no_perspectives_entries", []) if isinstance(entry, dict)]
    if no_perspectives:
        rows.append(
            {
                "label": "Cars with no perspectives files",
                "status": str(len(no_perspectives)),
                "detail": "; ".join(str(entry.get("relative_path", "")) for entry in no_perspectives[:6]),
            }
        )
    board["status"] = "available" if ready else "missing"
    board["data_available"] = ready
    board["selected_source_root"] = str(board.get("repo_root", ""))
    board["source_root_candidates"] = _source_repo_root_candidates(workspace)
    board["summary"] = (
        f"{file_total} perspective file(s) across {car_total} car(s) and "
        f"{display_group_count} display-type group(s); {brand_reference_count} brand reference file(s); "
        f"peer evidence: {peer_outlier_count} row(s); "
        f"structural issue rows: {structural_issue_count}; malformed files: {malformed_count}. "
        f"Reading from {board.get('repo_root', '')}. Source: {source_state}."
    )
    board["board_rows"] = rows
    return board

def _perspectives_inventory_page(workspace: Path, *, bmw_root: Path | str | None = None) -> dict[str, Any]:
    page = _reader_page(
        page_id="perspectives-inventory",
        title="Perspectives Inventory",
        tagline="Perspectives scene inventory and same-display-type peer evidence from local SVN.",
        reader=lambda: _perspectives_inventory_payload(workspace, bmw_root),
        workspace=workspace,
        ownership_note=(
            "Evidence only - peer outliers describe same-display-type differences, "
            "not automated delivery verdicts."
        ),
    )
    payload = page.get("payload", {}) if isinstance(page.get("payload"), dict) else {}
    page["source_selector"] = {
        "selected_source_root": str(payload.get("selected_source_root", "")),
        "source_root_candidates": list(payload.get("source_root_candidates", [])),
    }
    return page

def _disabled_tests_payload(
    workspace: Path,
    bmw_root: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    selected_repo_root = _source_repo_root_from_value(repo_root) or _preferred_source_repo_root(workspace)
    board = build_disabled_tests_board(
        selected_repo_root,
        workspace_root=workspace,
        bmw_repo_root=Path(bmw_root) if bmw_root is not None else None,
    ).to_dict()
    counts = board.get("counts", {})
    if not isinstance(counts, dict):
        counts = {}
    baseline = board.get("baseline", {})
    if not isinstance(baseline, dict):
        baseline = {}
    entries = [entry for entry in board.get("entries", []) if isinstance(entry, dict)]
    rows: list[dict[str, str]] = [
        {
            "label": "Reading from",
            "status": str(board.get("source_state", "unknown")),
            "detail": str(board.get("repo_root", "")),
        },
        {
            "label": "Config coverage",
            "status": f"{counts.get('configured', 0)}/{counts.get('total', 0)}",
            "detail": f"{counts.get('no_config', 0)} car(s) have no export/tests/test_config.lua.",
        },
        {
            "label": "Disabled calls",
            "status": str(counts.get("disabled_call_total", 0)),
            "detail": (
                f"{counts.get('disabled_unique_total', 0)} unique disabled name(s); "
                f"{counts.get('added_call_total', 0)} addTest call(s)."
            ),
        },
        {
            "label": "Review flags",
            "status": str(counts.get("duplicate_entry_count", 0) + counts.get("baseline_review_entry_count", 0)),
            "detail": (
                f"{counts.get('duplicate_entry_count', 0)} duplicate-disable row(s); "
                f"{counts.get('baseline_review_entry_count', 0)} row(s) with {CAUTIOUS_BASELINE_LABEL}."
            ),
        },
        {
            "label": "Baseline evidence",
            "status": str(baseline.get("state", "unknown")),
            "detail": f"{baseline.get('test_count', 0)} discovered test name(s).",
        },
    ]
    for entry in entries[:18]:
        flags = []
        duplicates = entry.get("duplicate_disabled_tests", [])
        baseline_review = entry.get("baseline_review_disabled_tests", [])
        if isinstance(duplicates, list) and duplicates:
            flags.append("duplicates: " + ", ".join(str(name) for name in duplicates[:4]))
        if isinstance(baseline_review, list) and baseline_review:
            flags.append(CAUTIOUS_BASELINE_LABEL + ": " + ", ".join(str(name) for name in baseline_review[:4]))
        detail = (
            f"{entry.get('relative_path', '')}; off {entry.get('disabled_count', 0)}; "
            f"added {entry.get('added_count', 0)}"
        )
        if flags:
            detail += "; " + "; ".join(flags)
        rows.append(
            {
                "label": f"{entry.get('brand', '')} {entry.get('model_id', '')}".strip(),
                "status": str(entry.get("config_status", "unknown")),
                "detail": detail,
            }
        )
    if len(entries) > 18:
        rows.append(
            {
                "label": "Additional cars",
                "status": str(len(entries) - 18),
                "detail": "Open the CLI JSON or evidence export for the remaining rows.",
            }
        )
    board["status"] = "available" if str(board.get("source_state", "")) == "ready" else "missing"
    board["data_available"] = str(board.get("source_state", "")) == "ready"
    board["selected_source_root"] = str(board.get("repo_root", ""))
    board["source_root_candidates"] = _source_repo_root_candidates(workspace)
    board["summary"] = (
        f"{counts.get('configured', 0)}/{counts.get('total', 0)} car(s) have test_config.lua; "
        f"{counts.get('disabled_call_total', 0)} active disableTest call(s); "
        f"{counts.get('no_config', 0)} no-config row(s). Reading from {board.get('repo_root', '')}."
    )
    board["board_rows"] = rows
    return board

def _disabled_tests_page(workspace: Path, *, bmw_root: Path | str | None = None) -> dict[str, Any]:
    page = _reader_page(
        page_id="disabled-tests",
        title="Disabled Tests",
        tagline="Per-car disabled-test inventory from local test_config.lua files.",
        reader=lambda: _disabled_tests_payload(workspace, bmw_root),
        workspace=workspace,
        ownership_note=(
            "Evidence only. Review flags use cautious wording: "
            f"{CAUTIOUS_BASELINE_LABEL}."
        ),
    )
    payload = page.get("payload", {}) if isinstance(page.get("payload"), dict) else {}
    page["source_selector"] = {
        "selected_source_root": str(payload.get("selected_source_root", "")),
        "source_root_candidates": list(payload.get("source_root_candidates", [])),
    }
    return page

def _api_version_coverage_payload(
    workspace: Path,
    bmw_root: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    selected_repo_root = _source_repo_root_from_value(repo_root) or _preferred_source_repo_root(workspace)
    board = build_api_version_coverage_board(
        selected_repo_root,
        workspace_root=workspace,
        bmw_repo_root=Path(bmw_root) if bmw_root is not None else None,
    ).to_dict()
    counts = board.get("counts", {})
    if not isinstance(counts, dict):
        counts = {}
    refs = [item for item in board.get("shared_api_references", []) if isinstance(item, dict)]
    interface_rows = [item for item in board.get("interface_family_entries", []) if isinstance(item, dict)]
    impact_scans = [item for item in board.get("impact_scans", []) if isinstance(item, dict)]
    rows: list[dict[str, str]] = [
        {
            "label": "Reading from",
            "status": str(board.get("source_state", "unknown")),
            "detail": str(board.get("repo_root", "")),
        },
        {
            "label": "Shared API brands",
            "status": f"{counts.get('shared_brand_ready', 0)}/{counts.get('shared_brand_total', 0)}",
            "detail": "Current IDCevo shared MainInterfaces API versions from local CHANGELOG.md files.",
        },
        {
            "label": "HMI export families",
            "status": str(counts.get("interface_entry_total", 0)),
            "detail": f"{counts.get('interface_known', 0)} known; {counts.get('interface_unknown', 0)} unknown.",
        },
        {
            "label": "Impact hints",
            "status": str(counts.get("impact_review_car_count", 0)),
            "detail": f"{counts.get('impact_file_match_count', 0)} file match(es); {IMPACT_REVIEW_LABEL}.",
        },
        {
            "label": "BMW catalog",
            "status": str(board.get("catalog_state", "unknown")),
            "detail": str(board.get("catalog_path", "")),
        },
    ]
    for ref in refs:
        rows.append(
            {
                "label": f"{ref.get('brand', '')} shared API".strip(),
                "status": f"[{ref.get('current_version', '')}]",
                "detail": f"{ref.get('current_date', '')}; {ref.get('changelog_path', '')}",
            }
        )
    for entry in interface_rows[:10]:
        version = entry.get("hmi_interface_version")
        version_text = str(version) if version is not None else "unknown"
        rows.append(
            {
                "label": f"{entry.get('brand', '')} {entry.get('model_id', '')}".strip(),
                "status": version_text,
                "detail": (
                    f"{entry.get('hmi_family_label', '')}; catalog "
                    f"{entry.get('catalog_name') or entry.get('match_status', '')}; "
                    "not a per-car API compliance verdict."
                ),
            }
        )
    if len(interface_rows) > 10:
        rows.append(
            {
                "label": "Additional HMI rows",
                "status": str(len(interface_rows) - 10),
                "detail": "Open the CLI JSON or evidence export for all interface-family rows.",
            }
        )
    for scan in impact_scans[:8]:
        change = scan.get("change", {})
        if not isinstance(change, dict):
            change = {}
        target = f" -> {change.get('new_name')}" if change.get("new_name") else ""
        rows.append(
            {
                "label": f"API {change.get('api_version', '')} {change.get('change_type', '')}".strip(),
                "status": str(scan.get("matched_car_count", 0)),
                "detail": (
                    f"{change.get('old_name', '')}{target}; "
                    f"{scan.get('matched_file_count', 0)} file match(es); {IMPACT_REVIEW_LABEL}."
                ),
            }
        )
    board["status"] = "available" if str(board.get("source_state", "")) == "ready" else "missing"
    board["data_available"] = str(board.get("source_state", "")) == "ready"
    board["selected_source_root"] = str(board.get("repo_root", ""))
    board["source_root_candidates"] = _source_repo_root_candidates(workspace)
    board["summary"] = (
        f"{counts.get('shared_brand_ready', 0)}/{counts.get('shared_brand_total', 0)} shared API brand(s) ready; "
        f"{counts.get('interface_entry_total', 0)} HMI export-family row(s); "
        f"{counts.get('impact_review_car_count', 0)} car(s) with cautious impact hints. "
        f"Reading from {board.get('repo_root', '')}."
    )
    board["board_rows"] = rows
    return board

def _api_version_coverage_page(workspace: Path, *, bmw_root: Path | str | None = None) -> dict[str, Any]:
    page = _reader_page(
        page_id="api-version-coverage",
        title="API Version",
        tagline="Shared MainInterfaces API reference with cautious impact hints.",
        reader=lambda: _api_version_coverage_payload(workspace, bmw_root),
        workspace=workspace,
        ownership_note=(
            "Evidence only. Per-car API alignment is not recorded in the repo; "
            "impact hints are review prompts, not verdicts."
        ),
    )
    payload = page.get("payload", {}) if isinstance(page.get("payload"), dict) else {}
    page["source_selector"] = {
        "selected_source_root": str(payload.get("selected_source_root", "")),
        "source_root_candidates": list(payload.get("source_root_candidates", [])),
    }
    return page

def _country_variant_coverage_payload(
    workspace: Path,
    bmw_root: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    selected_repo_root = _source_repo_root_from_value(repo_root) or _preferred_source_repo_root(workspace)
    board = build_country_variant_coverage_board(
        selected_repo_root,
        workspace_root=workspace,
        bmw_repo_root=Path(bmw_root) if bmw_root is not None else None,
    ).to_dict()
    counts = board.get("counts", {})
    if not isinstance(counts, dict):
        counts = {}
    entries = [item for item in board.get("entries", []) if isinstance(item, dict)]
    expectations = [item for item in board.get("expectations", []) if isinstance(item, dict)]
    rows: list[dict[str, str]] = [
        {
            "label": "Reading from",
            "status": str(board.get("source_state", "unknown")),
            "detail": str(board.get("repo_root", "")),
        },
        {
            "label": "Country-coding rows",
            "status": str(counts.get("row_total", 0)),
            "detail": f"{counts.get('car_with_rows_count', 0)} car(s) with active countryCoding_* tests.",
        },
        {
            "label": "Expected baselines",
            "status": f"{counts.get('expected_present_count', 0)}/{counts.get('row_total', 0)}",
            "detail": f"{counts.get('expected_missing_count', 0)} row(s): {MISSING_EXPECTED_LABEL}.",
        },
        {
            "label": "Runtime screenshots",
            "status": str(counts.get("runtime_evidence_row_count", 0)),
            "detail": f"{counts.get('actual_present_count', 0)} actual; {counts.get('diff_present_count', 0)} diff; {NO_RUNTIME_LABEL}.",
        },
        {
            "label": "Review prompts",
            "status": str(counts.get("review_row_count", 0)),
            "detail": f"{counts.get('mapping_review_count', 0)} row(s): {MAPPING_REVIEW_LABEL}.",
        },
    ]
    for entry in entries[:18]:
        flags = entry.get("review_flags", [])
        flag_text = ""
        if isinstance(flags, list) and flags:
            flag_text = "; " + "; ".join(str(flag) for flag in flags[:3])
        rows.append(
            {
                "label": f"{entry.get('brand', '')} {entry.get('model_id', '')} {entry.get('test_name', '')}".strip(),
                "status": str(entry.get("country_variant_id", "")),
                "detail": (
                    f"{entry.get('relative_path', '')}; variant {entry.get('variant_name', '')}; "
                    f"expected {'yes' if entry.get('expected_present') else 'no'}; "
                    f"actual {'yes' if entry.get('actual_present') else 'no'}; "
                    f"diff {'yes' if entry.get('diff_present') else 'no'}"
                    f"{flag_text}"
                ),
            }
        )
    if len(entries) > 18:
        rows.append(
            {
                "label": "Additional country rows",
                "status": str(len(entries) - 18),
                "detail": "Open the CLI JSON or evidence export for all country-variant rows.",
            }
        )
    for expectation in expectations:
        expected_variants = expectation.get("expected_variants", [])
        observed_rows = expectation.get("observed_rows", [])
        if not isinstance(expected_variants, list):
            expected_variants = []
        if not isinstance(observed_rows, list):
            observed_rows = []
        rows.append(
            {
                "label": f"{expectation.get('car', '')} expectation".strip(),
                "status": str(len(expected_variants)),
                "detail": (
                    f"{expectation.get('feature', '')}; expected {', '.join(str(item) for item in expected_variants)}; "
                    f"observed {', '.join(str(item) for item in observed_rows) or 'none'}; "
                    f"{expectation.get('review_label', '')}"
                ),
            }
        )
    board["status"] = "available" if str(board.get("source_state", "")) == "ready" else "missing"
    board["data_available"] = str(board.get("source_state", "")) == "ready"
    board["selected_source_root"] = str(board.get("repo_root", ""))
    board["source_root_candidates"] = _source_repo_root_candidates(workspace)
    board["summary"] = (
        f"{counts.get('row_total', 0)} countryCoding row(s) across "
        f"{counts.get('car_with_rows_count', 0)} car(s); "
        f"{counts.get('expected_present_count', 0)}/{counts.get('row_total', 0)} expected baseline(s) present; "
        f"{counts.get('review_row_count', 0)} review prompt row(s). Reading from {board.get('repo_root', '')}."
    )
    board["board_rows"] = rows
    return board

def _country_variant_coverage_page(workspace: Path, *, bmw_root: Path | str | None = None) -> dict[str, Any]:
    page = _reader_page(
        page_id="country-variant-coverage",
        title="Country Variants",
        tagline="Country-coding test matrix with expected, actual, and diff evidence slots.",
        reader=lambda: _country_variant_coverage_payload(workspace, bmw_root),
        workspace=workspace,
        ownership_note=(
            "Evidence only. Missing baselines and country-table mismatches are review prompts, "
            "not automated verdicts."
        ),
    )
    payload = page.get("payload", {}) if isinstance(page.get("payload"), dict) else {}
    page["source_selector"] = {
        "selected_source_root": str(payload.get("selected_source_root", "")),
        "source_root_candidates": list(payload.get("source_root_candidates", [])),
    }
    return page

def _export_size_trend_payload(
    workspace: Path,
    bmw_root: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    _ = bmw_root
    selected_repo_root = _source_repo_root_from_value(repo_root) or _preferred_source_repo_root(workspace)
    board = build_export_size_trend_board(
        selected_repo_root,
        workspace_root=workspace,
    ).to_dict()
    counts = board.get("counts", {})
    if not isinstance(counts, dict):
        counts = {}
    layout_counts = counts.get("layout_counts", {})
    if not isinstance(layout_counts, dict):
        layout_counts = {}
    date_source_counts = counts.get("date_source_counts", {})
    if not isinstance(date_source_counts, dict):
        date_source_counts = {}
    changes = [item for item in board.get("trend_changes", []) if isinstance(item, dict)]
    workbooks = [item for item in board.get("workbooks", []) if isinstance(item, dict)]
    review_changes = [item for item in changes if item.get("review_flags")]
    rows: list[dict[str, str]] = [
        {
            "label": "Reading from",
            "status": str(board.get("source_state", "unknown")),
            "detail": str(board.get("workbook_dir", "")),
        },
        {
            "label": "Workbooks",
            "status": str(counts.get("workbook_count", 0)),
            "detail": f"{counts.get('profile_count', 0)} profile(s); {counts.get('parsed_workbook_count', 0)} parsed.",
        },
        {
            "label": "Overview layouts",
            "status": str(len(layout_counts)),
            "detail": "; ".join(f"{key}={value}" for key, value in sorted(layout_counts.items())),
        },
        {
            "label": "Date sources",
            "status": str(len(date_source_counts)),
            "detail": "; ".join(f"{key}={value}" for key, value in sorted(date_source_counts.items())),
        },
        {
            "label": "Review prompts",
            "status": str(counts.get("review_change_count", 0)),
            "detail": f"{SIGNIFICANT_CHANGE_LABEL}; {UNREADABLE_LAYOUT_LABEL}.",
        },
    ]
    for change in review_changes[:8]:
        rows.append(
            {
                "label": f"{change.get('profile_id', '')} size change".strip(),
                "status": f"{float(change.get('delta_percent', 0) or 0):.2f}%",
                "detail": (
                    f"{Path(str(change.get('previous_workbook', ''))).name} -> "
                    f"{Path(str(change.get('current_workbook', ''))).name}; "
                    f"delta {float(change.get('delta_total', 0) or 0):.2f}; "
                    f"{'; '.join(str(flag) for flag in change.get('review_flags', []))}"
                ),
            }
        )
    for change in [item for item in changes if not item.get("review_flags")][:10]:
        rows.append(
            {
                "label": f"{change.get('profile_id', '')} latest/prior".strip(),
                "status": f"{float(change.get('delta_percent', 0) or 0):.2f}%",
                "detail": (
                    f"{Path(str(change.get('previous_workbook', ''))).name} -> "
                    f"{Path(str(change.get('current_workbook', ''))).name}; "
                    f"delta {float(change.get('delta_total', 0) or 0):.2f}."
                ),
            }
        )
    unreadable = [item for item in workbooks if str(item.get("status", "")) != "parsed"]
    for workbook in unreadable[:6]:
        flags = workbook.get("review_flags", [])
        flag_text = "; ".join(str(flag) for flag in flags) if isinstance(flags, list) else ""
        rows.append(
            {
                "label": Path(str(workbook.get("relative_path", workbook.get("workbook_path", "")))).name,
                "status": str(workbook.get("status", "")),
                "detail": flag_text or UNREADABLE_LAYOUT_LABEL,
            }
        )
    board["status"] = "available" if str(board.get("source_state", "")) == "ready" else "missing"
    board["data_available"] = str(board.get("source_state", "")) == "ready"
    board["selected_source_root"] = str(board.get("repo_root", ""))
    board["source_root_candidates"] = _source_repo_root_candidates(workspace)
    board["summary"] = (
        f"{counts.get('workbook_count', 0)} export-size workbook(s) across "
        f"{counts.get('profile_count', 0)} profile(s); "
        f"{counts.get('trend_change_count', 0)} trend comparison(s); "
        f"{counts.get('review_change_count', 0)} review prompt(s). "
        f"Reading from {board.get('repo_root', '')}."
    )
    board["board_rows"] = rows
    return board

def _export_size_trend_page(workspace: Path, *, bmw_root: Path | str | None = None) -> dict[str, Any]:
    page = _reader_page(
        page_id="export-size-trend",
        title="Size Trend",
        tagline="Export-size workbook trends from local size_analysis evidence.",
        reader=lambda: _export_size_trend_payload(workspace, bmw_root),
        workspace=workspace,
        ownership_note=(
            "Evidence only. Size changes are review prompts, not delivery or regression verdicts."
        ),
    )
    payload = page.get("payload", {}) if isinstance(page.get("payload"), dict) else {}
    page["source_selector"] = {
        "selected_source_root": str(payload.get("selected_source_root", "")),
        "source_root_candidates": list(payload.get("source_root_candidates", [])),
    }
    return page

def _setup_doctor_payload(workspace: Path) -> dict[str, Any]:
    report = build_setup_doctor_report(workspace).to_dict()
    rows = []
    for item in report.get("items", []):
        if not isinstance(item, dict):
            continue
        detail_parts = [
            str(item.get("category", "")).strip(),
            "required" if item.get("required") else "optional",
            str(item.get("version", "")).strip(),
            f"recommended {item.get('recommended_version')}" if item.get("recommended_version") else "",
            f"validation {item.get('version_status')}" if item.get("version_status") else "",
            str(item.get("version_check_detail", "")).strip(),
            str(item.get("detail", "") or item.get("fix", "")).strip(),
        ]
        rows.append(
            {
                "label": str(item.get("label", item.get("key", "item"))),
                "status": str(item.get("status", "unknown")),
                "detail": "; ".join(part for part in detail_parts if part),
            }
        )
    report["status"] = "available" if bool(report.get("ready")) else "blocked"
    report["data_available"] = True
    version_validation = report.get("version_validation", {})
    validation_text = ""
    if isinstance(version_validation, dict):
        validation_text = (
            f" Version validation: {version_validation.get('ok', 0)} ok, "
            f"{version_validation.get('drift', 0)} drift, "
            f"{version_validation.get('unknown', 0)} unknown, "
            f"{version_validation.get('not_pinned', 0)} not pinned."
        )
    report["summary"] = (
        f"{report.get('headline', 'Setup status generated.')} "
        f"{report.get('found_count', 0)} found; "
        f"{report.get('required_missing_count', 0)} required missing; "
        f"{report.get('optional_missing_count', 0)} optional missing."
        f"{validation_text}"
    )
    report["board_rows"] = rows
    return report

def _setup_doctor_page(workspace: Path) -> dict[str, Any]:
    return _reader_page(
        page_id="setup-doctor",
        title="Setup Doctor",
        tagline="Detect local SGFX dependencies and show version guidance from documented pins.",
        reader=lambda: _setup_doctor_payload(workspace),
        workspace=workspace,
        ownership_note=(
            "Guidance only. Version drift is review evidence; no installer or file copy runs without operator confirmation."
        ),
    )

def _qa_workflows_payload(workspace: Path) -> dict[str, Any]:
    workflows = [summary.to_dict() for summary in list_workflows(workspace_root=workspace)]
    rows = []
    for workflow in workflows:
        profiles = ", ".join(str(profile) for profile in workflow.get("profiles", [])[:5]) or "profile-agnostic"
        if len(workflow.get("profiles", [])) > 5:
            profiles += ", ..."
        rows.append(
            {
                "label": str(workflow.get("name") or workflow.get("id") or "workflow"),
                "status": str(workflow.get("last_status", "not_started")),
                "detail": (
                    f"{workflow.get('check_count', 0)} check(s); "
                    f"{workflow.get('dod_count', 0)} DoD item(s); profiles: {profiles}."
                ),
            }
        )
    return {
        "schema_version": 1,
        "status": "available" if workflows else "unavailable",
        "data_available": bool(workflows),
        "summary": f"{len(workflows)} local QA workflow definition(s) available for reviewed operator runs.",
        "workflow_count": len(workflows),
        "workflows": workflows,
        "board_rows": rows,
    }

def _qa_workflows_page(workspace: Path) -> dict[str, Any]:
    return _reader_page(
        page_id="qa-workflows",
        title="QA Workflows",
        tagline="Local JSON workflow catalog with manual-attestation gates preserved.",
        reader=lambda: _qa_workflows_payload(workspace),
        workspace=workspace,
        ownership_note="Workflow checks can gather evidence; manual attestation stays operator-reviewed.",
    )

def _bmw_process_payload() -> dict[str, Any]:
    contracts = list(workflow_contracts())
    rows = []
    for contract in contracts:
        steps = contract.get("steps", ())
        evidence = contract.get("evidence", ())
        rows.append(
            {
                "label": str(contract.get("label", contract.get("key", "workflow"))),
                "status": "available",
                "detail": f"{len(steps)} step(s); {len(evidence)} evidence item(s). {contract.get('source', '')}",
            }
        )
    return {
        "schema_version": 1,
        "status": "available",
        "data_available": True,
        "summary": f"{len(contracts)} BMW process workflow contract(s) available for operator reference.",
        "contract_count": len(contracts),
        "contracts": contracts,
        "board_rows": rows,
    }

def _bmw_process_page() -> dict[str, Any]:
    page = _reader_page(
        page_id="bmw-process",
        title="BMW Process",
        tagline="Read-only workflow contracts for BMW interface, triage, and visual review paths.",
        reader=_bmw_process_payload,
        ownership_note="Reference only. SGFX does not write BMW Git, Jira, SVN, or delivery approval state.",
    )
    page["confluence_anchors"] = [BMW_PIPELINE_PYTHON_CONFLUENCE_ANCHOR, QUALITY_HERO_CONFLUENCE_ANCHOR]
    return page

def _onboarding_guide_page(
    profile_id: str,
    workspace: Path | str,
    *,
    setup_status: dict[str, Any],
    bmw_root: Path | str | None = None,
) -> dict[str, Any]:
    payload = build_onboarding_guide(
        profile_id,
        workspace=workspace,
        bmw_root=bmw_root,
        dependency_status=setup_status,
    )
    return {
        "id": "onboarding-guide",
        "title": "Onboarding Guide",
        "tagline": "New-operator path through setup, evidence pages, manual review, and handoff.",
        "status": str(payload.get("onboarding_status", "unknown")),
        "data_available": True,
        "summary": str(payload.get("summary", "")),
        "items": list(payload.get("items", [])),
        "payload": payload,
        "confluence_anchors": list(payload.get("confluence_anchors", [])),
    }

def _screenshot_test_state_page(
    profile_id: str,
    workspace: Path,
    *,
    bmw_root: Path | str | None = None,
) -> dict[str, Any]:
    page = _reader_page(
        page_id="screenshot-test-state",
        title="Screenshot Test State",
        tagline="BMW + MINI baseline / actual / diff counts per brand.",
        reader=lambda: read_bmw_screenshot_state(
            profile_id,
            workspace=workspace,
            bmw_root=bmw_root,
            sg_project_root=workspace,
        ),
        workspace=workspace,
        ownership_note=SCREENSHOT_TEST_STATE_OWNERSHIP_NOTE,
    )
    page["confluence_anchors"] = [QUALITY_HERO_CONFLUENCE_ANCHOR, BMW_PIPELINE_PYTHON_CONFLUENCE_ANCHOR]
    preflight = check_screenshot_capture_environment(
        profile_id=profile_id,
        workspace=workspace,
        bmw_root=bmw_root,
    )
    export_precheck = (
        check_screenshot_export_artifact(profile_id=profile_id, workspace=workspace, bmw_root=bmw_root)
        if bool(preflight.get("can_run", False))
        else {}
    )
    export_required = bool(export_precheck.get("export_required", False))
    export_message = (
        f" exported.ramses is missing at {export_precheck.get('exported_ramses_path', '')}; "
        "SGFX will run export first, then capture screenshots."
        if export_required
        else ""
    )
    page["actions"] = [
        {
            "id": SCREENSHOT_CAPTURE_ACTION_ID,
            "label": "Export then capture screenshots" if export_required else SCREENSHOT_CAPTURE_ACTION_LABEL,
            "requires_confirmation": True,
            "timeout_seconds": SCREENSHOT_CAPTURE_TIMEOUT_SECONDS,
            "preflight": preflight,
            "export_precheck": export_precheck,
            "requires_export_first": export_required,
            "disabled": not bool(preflight.get("can_run", False)),
            "confirmation_message": str(preflight.get("confirmation_message", "")) + export_message,
            "confluence_anchor": BMW_PIPELINE_PYTHON_CONFLUENCE_ANCHOR,
        }
    ]
    return page

def _risk_score_page(
    profile_id: str,
    workspace: Path,
    *,
    bmw_root: Path | str | None = None,
) -> dict[str, Any]:
    page = _reader_page(
        page_id="risk-score",
        title="Risk Score",
        tagline="Per-car review focus signal with delta since latest local manual review.",
        reader=lambda: read_per_car_risk_score(
            profile_id,
            workspace=workspace,
            bmw_root=bmw_root,
        ),
        workspace=workspace,
        ownership_note="Risk score focuses review order only; operator verdicts remain manual.",
    )
    payload = page.get("payload", {}) if isinstance(page.get("payload"), dict) else {}
    page["confluence_anchors"] = list(payload.get("confluence_anchors", []))
    if page.get("status") == "not_run":
        page["empty_state_note"] = RISK_SCORE_EMPTY_NOTE
    # internal milestone Part C wiring: attach the internal milestone sparkline to the risk-score page so
    # the dashboard live UI surfaces the same trend signal that already lands
    # in the internal milestone HTML + the internal milestone-extended risk-score CLI text output.
    try:
        from sg_preflight.full_qa_history import read_full_qa_run_list
        from sg_preflight.risk_sparkline import (
            build_sparkline_data,
            render_sparkline_svg,
            sparkline_fallback_text,
        )
        runs = read_full_qa_run_list(profile_id, limit=10)
        data = build_sparkline_data(runs, profile_id=profile_id)
        page["risk_sparkline"] = {
            "svg": render_sparkline_svg(data),
            "fallback": sparkline_fallback_text(data),
            "has_trend": bool(data.has_trend),
            "run_count": len(data.risk_scores),
        }
    except Exception:
        page["risk_sparkline"] = {"svg": "", "fallback": "", "has_trend": False, "run_count": 0}
    return page

def _cross_car_comparison_page(
    workspace: Path,
    *,
    bmw_root: Path | str | None = None,
) -> dict[str, Any]:
    page = _reader_page(
        page_id="cross-car-comparison",
        title="Cross-Car Comparison",
        tagline="G70 vs G65 risk-score widget side by side.",
        reader=lambda: build_cross_car_comparison(
            workspace=workspace,
            bmw_root=bmw_root,
            left_profile="G70",
            right_profile="G65",
        ),
        workspace=workspace,
        ownership_note="Read-only comparison of local risk-score evidence; no BMW source or network writes.",
    )
    payload = page.get("payload", {}) if isinstance(page.get("payload"), dict) else {}
    page["confluence_anchors"] = list(payload.get("confluence_anchors", []))
    if not page.get("items"):
        page["empty_state_note"] = CROSS_CAR_COMPARISON_EMPTY_NOTE
    return page

def _payload_items(payload: dict[str, Any]) -> list[dict[str, str]]:
    handoff_items = payload.get("handoff_items", [])
    if isinstance(handoff_items, list) and handoff_items:
        return [
            {
                "label": str(item.get("label", "item")),
                "status": str(item.get("status", "unknown")),
                "detail": str(item.get("detail", "")),
            }
            for item in handoff_items
            if isinstance(item, dict)
        ]
    comparison_rows = payload.get("comparison_rows", [])
    if isinstance(comparison_rows, list) and comparison_rows:
        return [
            {
                "label": str(item.get("label", "row")),
                "status": str(item.get("status", "unknown")),
                "detail": f"{item.get('left_value', '')} vs {item.get('right_value', '')}; {item.get('delta_label', '')}",
            }
            for item in comparison_rows
            if isinstance(item, dict)
        ]
    board_rows = payload.get("board_rows", [])
    if isinstance(board_rows, list) and board_rows:
        return [
            {
                "label": str(item.get("label", "row")),
                "status": str(item.get("status", "unknown")),
                "detail": str(item.get("detail", "")),
            }
            for item in board_rows
            if isinstance(item, dict)
        ]
    signals = payload.get("signals", [])
    if isinstance(signals, list) and signals:
        return [
            {
                "label": str(signal.get("id", "signal")),
                "status": str(signal.get("status", "unknown")),
                "detail": str(signal.get("detail", "")),
            }
            for signal in signals
            if isinstance(signal, dict)
        ]
    checks = payload.get("checks", [])
    if isinstance(checks, list) and checks:
        items = []
        for check in checks:
            if not isinstance(check, dict):
                continue
            items.append(
                {
                    "label": str(check.get("label", check.get("key", "check"))),
                    "status": str(check.get("status", "unknown")),
                    "detail": str(check.get("raw_value", "")),
                }
            )
        return items
    counts = []
    for key, label in (
        ("expected_count", "Expected"),
        ("actual_count", "Actual"),
        ("diff_count", "Diff"),
        ("disabled_test_count", "Disabled"),
        ("sg_perspectives_screenshot_count", "SG Perspectives"),
        ("sg_perspectives_comparison_count", "SG Comparisons"),
    ):
        if key in payload:
            counts.append({"label": label, "status": str(payload.get(key, 0)), "detail": ""})
    return counts

def _sanitized_payload(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "profile_id",
        "matched_profile_id",
        "brand",
        "status",
        "data_available",
        "summary",
        "workbook_path",
        "expected_count",
        "actual_count",
        "diff_count",
        "disabled_test_count",
        "expected_root",
        "actuals_root",
        "diff_root",
        "sg_perspectives_root",
        "sg_perspectives_latest_folder",
        "sg_perspectives_screenshot_count",
        "sg_perspectives_comparison_count",
        "risk_score",
        "risk_level",
        "current_snapshot",
        "latest_review",
        "delta_since_last_review",
        "signals",
        "confluence_anchors",
        "read_only",
        "manual_review_required",
        "is_approval",
        "note",
        "guidance",
        "share_decision",
        "sections",
        "profiles",
        "version_validation",
        "board_rows",
        "display_type_groups",
        "no_perspectives_entries",
        "brand_reference_entries",
        "selected_source_root",
        "source_root_candidates",
        "counts",
        "baseline",
        "comparison_axis",
        "comparison_rows",
        "left_profile",
        "right_profile",
        "widget_label",
        "handoff_count",
        "latest_handoff",
        "handoff_items",
    )
    return {key: payload[key] for key in allowed if key in payload}

def _section_count(section: object) -> int:
    if not isinstance(section, dict):
        return 0
    try:
        return int(section.get("count", 0) or 0)
    except (TypeError, ValueError):
        return 0

def _daily_digest_has_partial_signal(sections: dict[str, Any]) -> bool:
    for key in _DAILY_DIGEST_PARTIAL_SECTION_KEYS:
        if _section_count(sections.get(key)) > 0:
            return True
    return False

def _daily_digest_page(
    workspace: Path,
    profile_id: str,
    *,
    active_ticket_id: str = "",
    ticket_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = dict(ticket_context or {})
    default_ticket = str(context.get("active_ticket_id", active_ticket_id)).strip()
    ticket_hint = str(context.get("ticket_id_hint", default_ticket or DAILY_DIGEST_TICKET_ID_PLACEHOLDER)).strip()
    base_action = {
        "requires_ticket_id": True,
        "ticket_id_hint": ticket_hint or DAILY_DIGEST_TICKET_ID_PLACEHOLDER,
        "ticket_id_default": default_ticket,
        "ticket_id_source": str(context.get("ticket_id_source", "manual_entry")),
        "recent_ticket_ids": list(context.get("recent_ticket_ids", [])),
        "confluence_anchor": SG_DAILY_CONFLUENCE_ANCHOR,
    }
    actions = [
        {
            "id": DAILY_DIGEST_BUILD_PACKAGE_ACTION_ID,
            "label": DAILY_DIGEST_BUILD_PACKAGE_ACTION_LABEL,
            **base_action,
        },
        {
            "id": QUALITY_HERO_REPORT_ACTION_ID,
            "label": QUALITY_HERO_REPORT_ACTION_LABEL,
            **base_action,
        },
    ]
    try:
        digest = build_latest_daily_digest(workspace=workspace)
    except Exception as exc:
        return {
            "id": "daily-digest",
            "title": "Daily Digest",
            "tagline": "Morning status snapshot for the SG Daily standup.",
            "status": "unknown",
            "data_available": False,
            "summary": f"Daily digest could not be read: {exc}",
            "items": [],
            "actions": actions,
            "confluence_anchors": [SG_DAILY_CONFLUENCE_ANCHOR],
            "payload": {
                "profile_id": profile_id,
                "active_ticket_id": default_ticket,
                "ticket_id_source": str(context.get("ticket_id_source", "manual_entry")),
                "recent_ticket_ids": list(context.get("recent_ticket_ids", [])),
            },
        }
    sections = digest.get("sections", {}) if isinstance(digest, dict) else {}
    items: list[dict[str, str]] = []
    if isinstance(sections, dict):
        for key in ("what_landed_today", "workflow_status", "evidence_prepared"):
            section = sections.get(key, {})
            if not isinstance(section, dict):
                continue
            items.append(
                {
                    "label": str(section.get("heading", key.replace("_", " ").title())),
                    "status": str(section.get("count", 0)),
                    "detail": str(section.get("empty_message", "")) if not section.get("count") else "items available",
                }
            )
    raw_status = str(digest.get("status", "unknown"))
    data_available = bool(digest.get("data_available", False))
    has_partial = isinstance(sections, dict) and _daily_digest_has_partial_signal(sections)
    status_value = _dashboard_status(raw_status, data_available)
    if raw_status == "no_review_package" and has_partial:
        status_value = "incomplete"
    page = {
        "id": "daily-digest",
        "title": "Daily Digest",
        "tagline": "Morning status snapshot for the SG Daily standup.",
        "status": status_value,
        "raw_status": raw_status,
        "data_available": data_available or has_partial,
        "summary": str(digest.get("no_data_message", "Daily digest snapshot loaded.")),
        "items": items,
        "actions": actions,
        "confluence_anchors": [SG_DAILY_CONFLUENCE_ANCHOR],
        "payload": {
            "status": digest.get("status", "unknown"),
            "scope": digest.get("scope", []),
            "date": digest.get("date", ""),
            "active_ticket_id": default_ticket,
            "ticket_id_source": str(context.get("ticket_id_source", "manual_entry")),
            "recent_ticket_ids": list(context.get("recent_ticket_ids", [])),
        },
    }
    if raw_status == "no_review_package" or status_value == "incomplete":
        page["empty_state_note"] = DAILY_DIGEST_EMPTY_NOTE
    return page

def _deferred_daily_digest_page(profile_id: str, ticket_context: dict[str, Any] | None = None) -> dict[str, Any]:
    context = dict(ticket_context or {})
    default_ticket = str(context.get("active_ticket_id", "")).strip()
    ticket_hint = str(context.get("ticket_id_hint", default_ticket or DAILY_DIGEST_TICKET_ID_PLACEHOLDER)).strip()
    base_action = {
        "requires_ticket_id": True,
        "ticket_id_hint": ticket_hint or DAILY_DIGEST_TICKET_ID_PLACEHOLDER,
        "ticket_id_default": default_ticket,
        "ticket_id_source": str(context.get("ticket_id_source", "manual_entry")),
        "recent_ticket_ids": list(context.get("recent_ticket_ids", [])),
        "confluence_anchor": SG_DAILY_CONFLUENCE_ANCHOR,
    }
    return {
        "id": "daily-digest",
        "title": "Daily Digest",
        "tagline": "Morning status snapshot for the SG Daily standup.",
        "status": "not_run",
        "raw_status": "not_run",
        "data_available": False,
        "summary": f"Daily Digest for {profile_id} refreshes when opened.",
        "items": [],
        "actions": [
            {
                "id": DAILY_DIGEST_BUILD_PACKAGE_ACTION_ID,
                "label": DAILY_DIGEST_BUILD_PACKAGE_ACTION_LABEL,
                **base_action,
            },
            {
                "id": QUALITY_HERO_REPORT_ACTION_ID,
                "label": QUALITY_HERO_REPORT_ACTION_LABEL,
                **base_action,
            },
        ],
        "confluence_anchors": [SG_DAILY_CONFLUENCE_ANCHOR],
        "payload": {
            "profile_id": profile_id,
            "status": "not_run",
            "scope": [],
            "date": "",
            "active_ticket_id": default_ticket,
            "ticket_id_source": str(context.get("ticket_id_source", "manual_entry")),
            "recent_ticket_ids": list(context.get("recent_ticket_ids", [])),
        },
        "empty_state_note": "Open Daily Digest to load the local standup snapshot.",
        "deferred": True,
    }

def _team_digest_board_page(
    workspace: Path,
    profile_id: str,
    *,
    bmw_root: Path | str | None = None,
) -> dict[str, Any]:
    def _reader() -> dict[str, Any]:
        board = build_team_daily_digest_board(
            workspace=workspace,
            bmw_root=bmw_root,
            profiles=(profile_id, "G70", "G65"),
            ticket_id=_dashboard_active_ticket_id(workspace),
        )
        sections = board.get("sections", {}) if isinstance(board.get("sections"), dict) else {}
        rows: list[dict[str, Any]] = []
        share = board.get("share_decision", {}) if isinstance(board.get("share_decision"), dict) else {}
        rows.append(
            {
                "label": "Sharing model",
                "status": str(share.get("status", "unknown")),
                "detail": f"Selected: {share.get('selected_model', 'unknown')}",
            }
        )
        for section_key in ("risk_by_profile", "what_landed_today", "workflow_status"):
            section = sections.get(section_key, {}) if isinstance(sections, dict) else {}
            if not isinstance(section, dict):
                continue
            for item in section.get("items", [])[:4]:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label", item.get("profile_id", section.get("heading", section_key))))
                status = str(item.get("status", "unknown"))
                detail = str(item.get("detail", ""))
                if "risk_score" in item:
                    detail = f"risk {item.get('risk_score', 0)}/100; {detail}".strip()
                rows.append({"label": label, "status": status, "detail": detail})
        board["board_rows"] = rows
        return board

    page = _reader_page(
        page_id="team-digest-board",
        title="Team Digest Board",
        tagline="Local snapshot for standup review across selected car profiles.",
        reader=_reader,
        workspace=workspace,
        ownership_note="Default sharing model is local snapshot; SVN and Confluence sharing remain explicit gates.",
    )
    payload = page.get("payload", {}) if isinstance(page.get("payload"), dict) else {}
    page["confluence_anchors"] = list(payload.get("confluence_anchors", []))
    if not page.get("items"):
        page["empty_state_note"] = TEAM_DIGEST_BOARD_EMPTY_NOTE
    return page

def _deferred_team_digest_board_page(profile_id: str) -> dict[str, Any]:
    return {
        "id": "team-digest-board",
        "title": "Team Digest Board",
        "tagline": "Local snapshot for standup review across selected car profiles.",
        "ownership_note": "Default sharing model is local snapshot; SVN and Confluence sharing remain explicit gates.",
        "status": "not_run",
        "raw_status": "not_run",
        "data_available": False,
        "summary": f"Team Digest Board for {profile_id} refreshes when opened.",
        "items": [],
        "payload": {
            "profile_id": profile_id,
            "status": "not_run",
            "data_available": False,
            "share_decision": {
                "rationale": "Open this page to load the local team digest snapshot.",
                "options": [],
            },
            "board_rows": [],
        },
        "confluence_anchors": [],
        "empty_state_note": "Open Team Digest Board to load the local standup snapshot.",
        "deferred": True,
    }

def _operator_handoff_page(profile_id: str, workspace: Path) -> dict[str, Any]:
    page = _reader_page(
        page_id="operator-handoff",
        title="Operator Handoff",
        tagline="Record the stopping point before a shift handoff.",
        reader=lambda: build_operator_handoff_snapshot(workspace=workspace, profile_id=profile_id),
        workspace=workspace,
        ownership_note="Handoff records stay operator-local and are not posted to Jira, SVN, or BMW Git.",
    )
    payload = page.get("payload", {}) if isinstance(page.get("payload"), dict) else {}
    page["confluence_anchors"] = [SG_DAILY_CONFLUENCE_ANCHOR, QUALITY_HERO_CONFLUENCE_ANCHOR]
    if not payload.get("latest_handoff"):
        page["empty_state_note"] = OPERATOR_HANDOFF_EMPTY_NOTE
    return page

for _name in (
    "_int_payload_value",
    "_screenshot_empty_note",
    "_reader_page",
    "_delivery_checklist_page",
    "_delivery_readiness_payload",
    "_delivery_readiness_page",
    "_cross_domain_delivery_payload",
    "_cross_domain_delivery_page",
    "_perspectives_inventory_payload",
    "_perspectives_inventory_page",
    "_disabled_tests_payload",
    "_disabled_tests_page",
    "_api_version_coverage_payload",
    "_api_version_coverage_page",
    "_country_variant_coverage_payload",
    "_country_variant_coverage_page",
    "_export_size_trend_payload",
    "_export_size_trend_page",
    "_setup_doctor_payload",
    "_setup_doctor_page",
    "_qa_workflows_payload",
    "_qa_workflows_page",
    "_bmw_process_payload",
    "_bmw_process_page",
    "_onboarding_guide_page",
    "_screenshot_test_state_page",
    "_risk_score_page",
    "_cross_car_comparison_page",
    "_payload_items",
    "_sanitized_payload",
    "_section_count",
    "_daily_digest_has_partial_signal",
    "_daily_digest_page",
    "_deferred_daily_digest_page",
    "_team_digest_board_page",
    "_deferred_team_digest_board_page",
    "_operator_handoff_page",
):
    globals()[_name] = _with_main_globals(globals()[_name])

del _name

