from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

from sg_preflight.cross_domain_delivery import CrossDomainItem, build_cross_domain_delivery_board
from sg_preflight.delivery_readiness import (
    STATUS_DELIVERED,
    STATUS_NOT_DELIVERED_YET,
    STATUS_UNKNOWN,
    DeliveryReadinessEntry,
    build_delivery_readiness_board,
)
from sg_preflight.bmw_delivery import LANE_IDCEVO
from sg_preflight.profiles import PROFILE_SCOPE_ALL, list_run_profiles, resolve_source_repo_root
from sg_preflight.tool_version_pins import compare_version, load_raco_pins, recommended_versions_text


_STATIC_PROFILE_SCOPE_BMW_ROOT = Path("__sgfx_static_profile_scope__")
RACK_TARGET_SCOPE_NOTE = (
    "IDCevo flash targets are taken from the documented profile list; IDCevo dirs outside that list "
    "are reported separately."
)
SVT_REFERENCE_NOTE = (
    "Reference only - operator stages this SVT from TALgen/Artifactory; SGFX does not verify the staged file."
)
MANUAL_REVIEW_BANNER = (
    "Evidence only - SGFX auto-checks the asset side for IDCevo flash targets from the documented profile list: "
    "exported RCA and version metadata. "
    "Delivery status is shown as planning context. Rack hardware, SVT staging, environment setup, "
    "flash outcome, and performance "
    "remain operator-confirmed/manual."
)
RACK_TARGET_INVENTORY_PROVENANCE = (
    "Reference - not live; documented in Confluence (PDX 400 Hardware-overview-IDC23-IDCEVO; "
    "PDX 010 Outlook Calendar), captured 2026-06-20; values may drift; "
    "SGFX does not measure or verify these."
)
KPI_EXPECTATION_PROVENANCE = (
    "Reference - not live; documented in Confluence (BMW 3D Car Performance Reports Summary; "
    "PDX 405 How-to-Profile), captured 2026-06-20; values may drift; "
    "SGFX does not measure or verify these."
)

_IDCEVO_SOURCE_ROOT = "Cars_IDCevo"
_KNOWN_DELIVERY_STATUSES = {STATUS_DELIVERED, STATUS_NOT_DELIVERED_YET, STATUS_UNKNOWN}


@dataclass(frozen=True)
class AssetCheck:
    key: str
    label: str
    passed: bool
    status: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "passed": self.passed,
            "status": self.status,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class RackBookingResource:
    label: str
    email: str
    resource_type: str

    def to_dict(self) -> dict[str, str]:
        return {
            "label": self.label,
            "email": self.email,
            "resource_type": self.resource_type,
        }

    @property
    def display_text(self) -> str:
        return f"{self.label} ({self.email})"


@dataclass(frozen=True)
class RackInventoryItem:
    id: str
    type: str
    ip: str
    software: str
    location: str
    connection: str
    notes: str
    booking_resource: str

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "type": self.type,
            "ip": self.ip,
            "software": self.software,
            "location": self.location,
            "connection": self.connection,
            "notes": self.notes,
            "booking_resource": self.booking_resource,
        }


@dataclass(frozen=True)
class RackInventoryReference:
    title: str
    anchor: str
    provenance_note: str
    racks: tuple[RackInventoryItem, ...]
    booking_resources: tuple[RackBookingResource, ...]
    reference_only: bool = True
    live: bool = False
    verified_by_sgfx: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "anchor": self.anchor,
            "provenance_note": self.provenance_note,
            "reference_only": self.reference_only,
            "live": self.live,
            "verified_by_sgfx": self.verified_by_sgfx,
            "racks": [rack.to_dict() for rack in self.racks],
            "booking_resources": [resource.to_dict() for resource in self.booking_resources],
        }


@dataclass(frozen=True)
class KpiReferenceMetric:
    name: str
    unit: str
    source_tool: str
    measurement: str
    report_fields: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "unit": self.unit,
            "source_tool": self.source_tool,
            "measurement": self.measurement,
            "report_fields": list(self.report_fields),
        }


@dataclass(frozen=True)
class KpiExpectationReference:
    title: str
    anchor: str
    provenance_note: str
    metrics: tuple[KpiReferenceMetric, ...]
    reference_only: bool = True
    live: bool = False
    measured_by_sgfx: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "anchor": self.anchor,
            "provenance_note": self.provenance_note,
            "reference_only": self.reference_only,
            "live": self.live,
            "measured_by_sgfx": self.measured_by_sgfx,
            "metrics": [metric.to_dict() for metric in self.metrics],
        }


RACK_BOOKING_RESOURCES: tuple[RackBookingResource, ...] = (
    RackBookingResource(
        label="Seriengrafik Rack BMW ITAI-1645",
        email="itai-1645@paradoxcat.com",
        resource_type="Equipment",
    ),
    RackBookingResource(
        label="Seriengrafik Rack Mini ITAI-1646",
        email="itai-1646@paradoxcat.com",
        resource_type="Equipment",
    ),
    RackBookingResource(
        label="Testrack Krusty ITAI-1647",
        email="itai-1647@paradoxcat.com",
        resource_type="Equipment",
    ),
)

RACK_TARGET_INVENTORY = RackInventoryReference(
    title="Rack Target Inventory Reference",
    anchor="PDX 400 Hardware-overview-IDC23-IDCEVO; PDX 010 Outlook Calendar",
    provenance_note=RACK_TARGET_INVENTORY_PROVENANCE,
    racks=(
        RackInventoryItem(
            id="ITAI-1906",
            type="IDCEVO",
            ip="169.254.166.99",
            software="26w13.2-2",
            location="MUC",
            connection="adb - USB or Ethernet",
            notes="Parking View not Operational",
            booking_resource=RACK_BOOKING_RESOURCES[0].display_text,
        ),
        RackInventoryItem(
            id="IDC23 Rack",
            type="IDC23",
            ip="169.254.8.177",
            software="",
            location="MUC",
            connection="adb - Ethernet",
            notes="",
            booking_resource=RACK_BOOKING_RESOURCES[0].display_text,
        ),
        RackInventoryItem(
            id="IDC23 Mini",
            type="Mini",
            ip="169.254.8.177",
            software="",
            location="MUC",
            connection="adb - Ethernet",
            notes="",
            booking_resource=RACK_BOOKING_RESOURCES[1].display_text,
        ),
    ),
    booking_resources=RACK_BOOKING_RESOURCES,
)

KPI_EXPECTATION_REFERENCE = KpiExpectationReference(
    title="KPI Expectation Reference",
    anchor="BMW 3D Car Performance Reports Summary; PDX 405 How-to-Profile",
    provenance_note=KPI_EXPECTATION_PROVENANCE,
    metrics=(
        KpiReferenceMetric(
            name="Carlib render time",
            unit="ms",
            source_tool="benchmark_carlib_perf.py / BMW Carlib Report",
            measurement="live-on-rack expectation (not captured by SGFX; not measured by SGFX)",
            report_fields=("Build Type", "Build ID", "Carlib Version", "Avg Time", "Min", "Max", "Runs"),
        ),
        KpiReferenceMetric(
            name="Test-app Compose->Rendered",
            unit="ms",
            source_tool="benchmark_testapp_perf.py / BMW Test-app Report",
            measurement="live-on-rack expectation (not captured by SGFX; not measured by SGFX)",
            report_fields=("Build Type", "Build ID", "Carlib Version", "Compose->Rendered", "Runs"),
        ),
        KpiReferenceMetric(
            name="Test-app Launch->Rendered",
            unit="ms",
            source_tool="benchmark_testapp_perf.py / BMW Test-app Report",
            measurement="live-on-rack expectation (not captured by SGFX; not measured by SGFX)",
            report_fields=("Build Type", "Build ID", "Carlib Version", "Launch->Rendered", "Runs"),
        ),
        KpiReferenceMetric(
            name="Profiling VRAM usage",
            unit="logcat value",
            source_tool='PDX 405 Asset Viewer / logcat "Total VRAM usage"',
            measurement="baseline delta on live rack (not captured by SGFX; not measured by SGFX)",
            report_fields=("Baseline", "Min Asset Load", "Max Asset Load"),
        ),
        KpiReferenceMetric(
            name="Profiling frame delta",
            unit="ms",
            source_tool='PDX 405 Asset Viewer / logcat "Avg frame delta"',
            measurement="baseline delta on live rack (not captured by SGFX; not measured by SGFX)",
            report_fields=("Baseline", "Min Asset Load", "Max Asset Load"),
        ),
    ),
)


@dataclass(frozen=True)
class OperatorChecklistItem:
    key: str
    label: str
    detail: str
    confluence_anchor: str
    operator_confirmed: bool = True
    auto_checked: bool = False
    status: str = "operator_confirmed_required"

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "detail": self.detail,
            "confluence_anchor": self.confluence_anchor,
            "operator_confirmed": self.operator_confirmed,
            "auto_checked": self.auto_checked,
            "status": self.status,
        }


@dataclass(frozen=True)
class DeliveryContext:
    status: str
    status_label: str
    version: str
    delivered_date: str
    note: str
    blocking: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "status_label": self.status_label,
            "version": self.version,
            "delivered_date": self.delivered_date,
            "note": self.note,
            "blocking": self.blocking,
        }


@dataclass(frozen=True)
class OutOfScopeIdcevoDir:
    source_root: str
    brand: str
    model_id: str
    relative_path: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "source_root": self.source_root,
            "brand": self.brand,
            "model_id": self.model_id,
            "relative_path": self.relative_path,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class MissingRackTargetDir:
    source_root: str
    brand: str
    model_id: str
    relative_path: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "source_root": self.source_root,
            "brand": self.brand,
            "model_id": self.model_id,
            "relative_path": self.relative_path,
            "reason": self.reason,
        }


OPERATOR_CHECKLIST: tuple[OperatorChecklistItem, ...] = (
    OperatorChecklistItem(
        key="swl_sec_role",
        label="SWL-Sec 2 role",
        detail="Operator confirms the required SWL-Sec role before rack work.",
        confluence_anchor="PDX 403#SWL-Sec 2 role",
    ),
    OperatorChecklistItem(
        key="artifactory_token_pat",
        label="Artifactory token and GitHub PAT",
        detail="Operator confirms Gradle properties contain the local Artifactory token and GitHub PAT.",
        confluence_anchor="PDX 403#Artifactory token and PAT",
    ),
    OperatorChecklistItem(
        key="android_studio",
        label="Android Studio",
        detail="Operator confirms Android Studio is installed for the rack workflow.",
        confluence_anchor="PDX 403#Android Studio",
    ),
    OperatorChecklistItem(
        key="e_sys",
        label="E-Sys",
        detail=r"Operator confirms E-Sys is installed at C:\EC-Apps\E-Sys.",
        confluence_anchor="PDX 403#E-Sys",
    ),
    OperatorChecklistItem(
        key="rack_connected_adb",
        label="Rack connected via adb",
        detail="Operator confirms the rack is visible in adb devices.",
        confluence_anchor="PDX 406#Rack adb connection",
    ),
    OperatorChecklistItem(
        key="pdx_svt_staged",
        label="PDX and SVT staged",
        detail="Operator confirms the PDX and matching SVT XML are downloaded and staged from Artifactory.",
        confluence_anchor="PDX 403#PDX and SVT staging",
    ),
    OperatorChecklistItem(
        key="mirror_protocol_loaded",
        label="Mirror Protocol loaded",
        detail="Operator confirms Mirror Protocol is loaded for the rack session.",
        confluence_anchor="PDX 406#Mirror Protocol",
    ),
)


@dataclass(frozen=True)
class RackReadinessEntry:
    source_root: str
    brand: str
    model_id: str
    relative_path: str
    asset_ready: bool
    asset_status: str
    asset_checks: tuple[AssetCheck, ...]
    blockers: tuple[str, ...]
    context_notes: tuple[str, ...]
    delivery_context: DeliveryContext
    expected_svt_filename: str
    expected_svt_status: str
    expected_svt_detail: str
    expected_svt_auto_checked: bool
    delivery_status: str
    delivery_status_label: str
    version: str
    ramses: str
    raco_headless: str
    raco_pin_status: str
    raco_pin_detail: str
    raco_recommended_versions: str
    rca_paths: tuple[str, ...]
    rca_total_bytes: int
    operator_checklist: tuple[OperatorChecklistItem, ...] = OPERATOR_CHECKLIST

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_root": self.source_root,
            "brand": self.brand,
            "model_id": self.model_id,
            "relative_path": self.relative_path,
            "asset_ready": self.asset_ready,
            "asset_status": self.asset_status,
            "asset_checks": [check.to_dict() for check in self.asset_checks],
            "blockers": list(self.blockers),
            "context_notes": list(self.context_notes),
            "delivery_context": self.delivery_context.to_dict(),
            "expected_svt_filename": self.expected_svt_filename,
            "expected_svt_status": self.expected_svt_status,
            "expected_svt_detail": self.expected_svt_detail,
            "expected_svt_auto_checked": self.expected_svt_auto_checked,
            "delivery_status": self.delivery_status,
            "delivery_status_label": self.delivery_status_label,
            "version": self.version,
            "ramses": self.ramses,
            "raco_headless": self.raco_headless,
            "raco_pin_status": self.raco_pin_status,
            "raco_pin_detail": self.raco_pin_detail,
            "raco_recommended_versions": self.raco_recommended_versions,
            "rca_paths": list(self.rca_paths),
            "rca_total_bytes": self.rca_total_bytes,
            "operator_checklist": [item.to_dict() for item in self.operator_checklist],
        }


@dataclass(frozen=True)
class RackReadinessBoard:
    repo_root: Path
    source_state: str
    generated_at_utc: str
    entries: tuple[RackReadinessEntry, ...]
    out_of_scope_idcevo_dirs: tuple[OutOfScopeIdcevoDir, ...] = ()
    missing_rack_target_dirs: tuple[MissingRackTargetDir, ...] = ()
    operator_checklist: tuple[OperatorChecklistItem, ...] = OPERATOR_CHECKLIST
    target_scope_note: str = RACK_TARGET_SCOPE_NOTE
    manual_review_banner: str = MANUAL_REVIEW_BANNER
    rack_inventory: RackInventoryReference = RACK_TARGET_INVENTORY
    kpi_reference: KpiExpectationReference = KPI_EXPECTATION_REFERENCE

    @property
    def counts(self) -> dict[str, Any]:
        status_counts = Counter(entry.asset_status for entry in self.entries)
        return {
            "entry_total": len(self.entries),
            "asset_ready_count": status_counts.get("asset_ready", 0),
            "asset_blocked_count": status_counts.get("asset_blocked", 0),
            "exported_count": sum(1 for entry in self.entries if any(check.key == "exported" and check.passed for check in entry.asset_checks)),
            "delivered_count": sum(1 for entry in self.entries if entry.delivery_status == STATUS_DELIVERED),
            "version_ok_count": sum(1 for entry in self.entries if any(check.key == "version_metadata" and check.passed for check in entry.asset_checks)),
            "operator_checklist_count": len(self.operator_checklist),
            "expected_svt_count": len(self.entries),
            "out_of_scope_idcevo_dir_count": len(self.out_of_scope_idcevo_dirs),
            "missing_rack_target_dir_count": len(self.missing_rack_target_dirs),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "repo_root": str(self.repo_root),
            "source_state": self.source_state,
            "generated_at_utc": self.generated_at_utc,
            "manual_review_banner": self.manual_review_banner,
            "target_scope_note": self.target_scope_note,
            "rack_inventory": self.rack_inventory.to_dict(),
            "kpi_reference": self.kpi_reference.to_dict(),
            "read_only": True,
            "manual_review_required": True,
            "is_approval": False,
            "counts": self.counts,
            "operator_checklist": [item.to_dict() for item in self.operator_checklist],
            "entries": [entry.to_dict() for entry in self.entries],
            "out_of_scope_idcevo_dirs": [entry.to_dict() for entry in self.out_of_scope_idcevo_dirs],
            "missing_rack_target_dirs": [entry.to_dict() for entry in self.missing_rack_target_dirs],
        }


def _now_iso(now: datetime | None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _target_model_token(model_id: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_]+", "_", model_id.strip()).strip("_").upper()
    if token.endswith("_EVO"):
        token = token[:-4]
    return token


def expected_svt_filename(model_id: str) -> str:
    return f"SVT_IDCEVO-WITHOUT_SWITCH_{_target_model_token(model_id)}_EVO.xml"


def _relative_path_key(value: str | Path) -> str:
    return str(value).replace("\\", "/").strip("/").casefold()


def _rack_target_profile_dirs(
    *,
    workspace_root: Path | None,
    source_root: Path,
    bmw_root: Path | None = None,
) -> dict[str, MissingRackTargetDir]:
    _ = bmw_root
    profiles = list_run_profiles(
        workspace_root,
        reference_repo_root=source_root,
        bmw_root=_STATIC_PROFILE_SCOPE_BMW_ROOT,
        profile_scope=PROFILE_SCOPE_ALL,
    )
    targets: dict[str, MissingRackTargetDir] = {}
    for profile in profiles:
        if profile.lane != LANE_IDCEVO:
            continue
        parts = profile.project_relative.parts
        if len(parts) >= 3 and parts[0] == _IDCEVO_SOURCE_ROOT:
            relative_path = str(profile.project_relative).replace("\\", "/")
            targets[_relative_path_key(relative_path)] = MissingRackTargetDir(
                source_root=parts[0],
                brand=parts[1],
                model_id=parts[2],
                relative_path=relative_path,
                reason="Documented rack-target profile has no delivery-readiness row in this checkout.",
            )
    return targets


def _is_rack_target(entry: DeliveryReadinessEntry, rack_target_paths: frozenset[str]) -> bool:
    return entry.source_root == _IDCEVO_SOURCE_ROOT and _relative_path_key(entry.relative_path) in rack_target_paths


def _out_of_scope_dir(entry: DeliveryReadinessEntry, rack_target_paths: frozenset[str]) -> OutOfScopeIdcevoDir | None:
    if entry.source_root != _IDCEVO_SOURCE_ROOT or _relative_path_key(entry.relative_path) in rack_target_paths:
        return None
    return OutOfScopeIdcevoDir(
        source_root=entry.source_root,
        brand=entry.brand,
        model_id=entry.model_id,
        relative_path=entry.relative_path,
        reason="IDCevo dir is not in the documented rack-target profile list; no SVT reference is fabricated.",
    )


def _cross_entry_map(entries: tuple[CrossDomainItem, ...]) -> dict[str, CrossDomainItem]:
    return {
        entry.relative_path: entry
        for entry in entries
        if entry.domain == "cars" and entry.relative_path.startswith(f"{_IDCEVO_SOURCE_ROOT}/")
    }


def _check_exported(cross_entry: CrossDomainItem | None) -> AssetCheck:
    rca_paths = cross_entry.rca_paths if cross_entry is not None else ()
    if rca_paths:
        return AssetCheck(
            key="exported",
            label="RCA export present",
            passed=True,
            status="ok",
            detail=f"{len(rca_paths)} RCA export file(s) found.",
        )
    return AssetCheck(
        key="exported",
        label="RCA export present",
        passed=False,
        status="blocked",
        detail="No RCA export found for this IDCevo car.",
    )


def _delivery_context(delivery_entry: DeliveryReadinessEntry, cross_entry: CrossDomainItem | None) -> DeliveryContext:
    status = cross_entry.delivery_status if cross_entry is not None else delivery_entry.status
    status_label = cross_entry.delivery_status_label if cross_entry is not None else delivery_entry.status_label
    version = cross_entry.version if cross_entry is not None else delivery_entry.version
    delivered_date = cross_entry.delivered_date if cross_entry is not None else delivery_entry.delivered_date
    if status not in _KNOWN_DELIVERY_STATUSES:
        status = STATUS_UNKNOWN
        status_label = "Unknown"
    if status == STATUS_DELIVERED:
        note = (
            f"Latest CHANGELOG entry is delivered{f' on {delivered_date}' if delivered_date else ''}. "
            "Delivery status is planning context and does not gate the asset-side checks."
        )
    elif status == STATUS_NOT_DELIVERED_YET:
        note = (
            "Latest CHANGELOG entry is not delivered. Delivery status is planning context and does not gate "
            "the asset-side checks."
        )
    else:
        note = (
            "Latest CHANGELOG delivery status is unknown. Delivery status is planning context and does not gate "
            "the asset-side checks."
        )
    return DeliveryContext(
        status=status,
        status_label=status_label,
        version=version,
        delivered_date=delivered_date,
        note=note,
    )


def _check_version_metadata(delivery_entry: DeliveryReadinessEntry, cross_entry: CrossDomainItem | None) -> AssetCheck:
    version = cross_entry.version if cross_entry is not None else delivery_entry.version
    ramses = cross_entry.ramses if cross_entry is not None else ""
    raco = cross_entry.raco_headless if cross_entry is not None else ""
    missing = []
    if not version:
        missing.append("version")
    if not ramses:
        missing.append("Ramses")
    if not raco:
        missing.append("RaCo Headless")
    if not missing:
        return AssetCheck(
            key="version_metadata",
            label="Version metadata present",
            passed=True,
            status="ok",
            detail=f"Version {version}; Ramses {ramses}; RaCo Headless {raco}.",
        )
    return AssetCheck(
        key="version_metadata",
        label="Version metadata present",
        passed=False,
        status="blocked",
        detail="Missing version metadata: " + ", ".join(missing) + ".",
    )


def _entry_from_delivery(
    delivery_entry: DeliveryReadinessEntry,
    cross_entry: CrossDomainItem | None,
    *,
    raco_pins: dict[str, Any],
) -> RackReadinessEntry:
    checks = (
        _check_exported(cross_entry),
        _check_version_metadata(delivery_entry, cross_entry),
    )
    blockers = tuple(check.detail for check in checks if not check.passed)
    asset_ready = not blockers
    delivery_context = _delivery_context(delivery_entry, cross_entry)
    context_notes = (delivery_context.note,)
    raco_headless = str(cross_entry.raco_headless or "") if cross_entry is not None else ""
    if raco_headless:
        raco_pin_status, raco_pin_detail = compare_version(raco_headless, raco_pins)
    else:
        raco_pin_status = "unknown"
        raco_pin_detail = "RaCo Headless version was not found in CHANGELOG metadata."
    return RackReadinessEntry(
        source_root=delivery_entry.source_root,
        brand=delivery_entry.brand,
        model_id=delivery_entry.model_id,
        relative_path=delivery_entry.relative_path,
        asset_ready=asset_ready,
        asset_status="asset_ready" if asset_ready else "asset_blocked",
        asset_checks=checks,
        blockers=blockers,
        context_notes=context_notes,
        delivery_context=delivery_context,
        expected_svt_filename=expected_svt_filename(delivery_entry.model_id),
        expected_svt_status="operator_staged_required",
        expected_svt_detail=SVT_REFERENCE_NOTE,
        expected_svt_auto_checked=False,
        delivery_status=cross_entry.delivery_status if cross_entry is not None else delivery_entry.status,
        delivery_status_label=cross_entry.delivery_status_label if cross_entry is not None else delivery_entry.status_label,
        version=cross_entry.version if cross_entry is not None else delivery_entry.version,
        ramses=str(cross_entry.ramses or "") if cross_entry is not None else "",
        raco_headless=raco_headless,
        raco_pin_status=raco_pin_status,
        raco_pin_detail=raco_pin_detail,
        raco_recommended_versions=recommended_versions_text(raco_pins),
        rca_paths=cross_entry.rca_paths if cross_entry is not None else (),
        rca_total_bytes=cross_entry.rca_total_bytes if cross_entry is not None else 0,
    )


def build_rack_readiness_board(
    repo_root: Path | str | None = None,
    *,
    workspace_root: Path | str | None = None,
    bmw_repo_root: Path | str | None = None,
    now: datetime | None = None,
) -> RackReadinessBoard:
    workspace = Path(workspace_root).resolve() if workspace_root is not None else None
    source_root = Path(repo_root).resolve() if repo_root is not None else resolve_source_repo_root(workspace)
    generated_at = _now_iso(now)
    if not source_root.exists():
        return RackReadinessBoard(
            repo_root=source_root,
            source_state="missing",
            generated_at_utc=generated_at,
            entries=(),
        )

    bmw_root = Path(bmw_repo_root).resolve() if bmw_repo_root is not None else None
    try:
        delivery_board = build_delivery_readiness_board(
            source_root,
            workspace_root=workspace,
            bmw_repo_root=bmw_root,
        )
        cross_board = build_cross_domain_delivery_board(
            source_root,
            workspace_root=workspace,
            bmw_repo_root=bmw_root,
            domains=("cars",),
            now=now,
        )
        rack_target_profiles = _rack_target_profile_dirs(workspace_root=workspace, source_root=source_root, bmw_root=bmw_root)
        rack_target_paths = frozenset(rack_target_profiles)
        cross_entries = _cross_entry_map(cross_board.entries)
        raco_pins = load_raco_pins(bmw_root)
        delivery_entry_paths = {
            _relative_path_key(delivery_entry.relative_path)
            for delivery_entry in delivery_board.entries
            if delivery_entry.source_root == _IDCEVO_SOURCE_ROOT
        }
        entries = tuple(
            sorted(
                (
                    _entry_from_delivery(
                        delivery_entry,
                        cross_entries.get(delivery_entry.relative_path),
                        raco_pins=raco_pins,
                    )
                    for delivery_entry in delivery_board.entries
                    if _is_rack_target(delivery_entry, rack_target_paths)
                ),
                key=lambda entry: (entry.brand.lower(), entry.model_id.lower(), entry.relative_path.lower()),
            )
        )
        out_of_scope = tuple(
            sorted(
                (
                    scope_entry
                    for delivery_entry in delivery_board.entries
                    for scope_entry in (_out_of_scope_dir(delivery_entry, rack_target_paths),)
                    if scope_entry is not None
                ),
                key=lambda entry: (entry.brand.lower(), entry.model_id.lower(), entry.relative_path.lower()),
            )
        )
        missing_targets = tuple(
            sorted(
                (target for key, target in rack_target_profiles.items() if key not in delivery_entry_paths),
                key=lambda entry: (entry.brand.lower(), entry.model_id.lower(), entry.relative_path.lower()),
            )
        )
    except Exception:
        return RackReadinessBoard(
            repo_root=source_root,
            source_state="error",
            generated_at_utc=generated_at,
            entries=(),
        )
    return RackReadinessBoard(
        repo_root=source_root,
        source_state="ready",
        generated_at_utc=generated_at,
        entries=entries,
        out_of_scope_idcevo_dirs=out_of_scope,
        missing_rack_target_dirs=missing_targets,
    )


def _markdown_cell(value: object) -> str:
    return str(value or "").replace("|", "\\|")


def rack_readiness_markdown(board: RackReadinessBoard) -> str:
    payload = board.to_dict()
    counts = payload["counts"]
    lines = [
        "# Rack Pre-Flash Readiness",
        "",
        str(payload["manual_review_banner"]),
        "",
        str(payload["target_scope_note"]),
        "",
        f"- source: `{payload['repo_root']}`",
        f"- generated: `{payload['generated_at_utc']}`",
        f"- IDCevo rack target rows: {counts['entry_total']}",
        f"- asset-ready rows: {counts['asset_ready_count']}",
        f"- asset-blocked rows: {counts['asset_blocked_count']}",
        f"- exported rows: {counts['exported_count']}",
        f"- delivered rows: {counts['delivered_count']}",
        f"- version metadata rows: {counts['version_ok_count']}",
        f"- IDCevo dirs outside current rack scope: {counts['out_of_scope_idcevo_dir_count']}",
        f"- documented rack targets with no delivery row: {counts['missing_rack_target_dir_count']}",
        "",
        "## Rack Target Inventory Reference",
        "",
        str(payload["rack_inventory"]["provenance_note"]),
        "",
        "| ID | Type | IP | Software | Location | Connection | Notes | Booking resource |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for rack in payload["rack_inventory"]["racks"]:
        lines.append(
            "| "
            + " | ".join(
                (
                    _markdown_cell(rack.get("id", "")),
                    _markdown_cell(rack.get("type", "")),
                    _markdown_cell(rack.get("ip", "")),
                    _markdown_cell(rack.get("software", "")),
                    _markdown_cell(rack.get("location", "")),
                    _markdown_cell(rack.get("connection", "")),
                    _markdown_cell(rack.get("notes", "")),
                    _markdown_cell(rack.get("booking_resource", "")),
                )
            )
            + " |"
        )
    lines.extend(
        (
            "",
            "Booking resources documented in Outlook:",
        )
    )
    for resource in payload["rack_inventory"]["booking_resources"]:
        lines.append(
            f"- {_markdown_cell(resource.get('label', ''))} "
            f"({_markdown_cell(resource.get('email', ''))}; {_markdown_cell(resource.get('resource_type', ''))})"
        )
    lines.extend(
        (
            "",
            "## KPI Expectation Reference",
            "",
            str(payload["kpi_reference"]["provenance_note"]),
            "",
            "These metrics are measured live on the rack and are not measured by SGFX.",
            "",
            "| Metric | Unit | Source/tool | Measurement | Report fields |",
            "| --- | --- | --- | --- | --- |",
        )
    )
    for metric in payload["kpi_reference"]["metrics"]:
        report_fields = metric.get("report_fields", [])
        fields_text = ", ".join(str(field) for field in report_fields) if isinstance(report_fields, list) else ""
        lines.append(
            "| "
            + " | ".join(
                (
                    _markdown_cell(metric.get("name", "")),
                    _markdown_cell(metric.get("unit", "")),
                    _markdown_cell(metric.get("source_tool", "")),
                    _markdown_cell(metric.get("measurement", "")),
                    _markdown_cell(fields_text),
                )
            )
            + " |"
        )
    lines.extend(
        (
            "",
            "## Asset-Side Auto Checks",
            "",
            "| Brand | Model | Asset status | Export | Version metadata | Expected SVT | Path |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        )
    )
    for entry in board.entries:
        checks = {check.key: check for check in entry.asset_checks}
        lines.append(
            "| "
            + " | ".join(
                (
                    _markdown_cell(entry.brand),
                    _markdown_cell(entry.model_id),
                    _markdown_cell(entry.asset_status),
                    _markdown_cell(checks["exported"].status),
                    _markdown_cell(checks["version_metadata"].status),
                    _markdown_cell(f"{entry.expected_svt_filename} ({entry.expected_svt_detail})"),
                    _markdown_cell(entry.relative_path),
                )
            )
            + " |"
        )
    if not board.entries:
        lines.append("|  |  | no rows |  |  |  |  |")
    lines.extend(
        (
            "",
            "## IDCevo Dirs Outside Current Rack Scope",
            "",
            "| Brand | Model | Path | Reason |",
            "| --- | --- | --- | --- |",
        )
    )
    for entry in board.out_of_scope_idcevo_dirs:
        lines.append(
            "| "
            + " | ".join(
                (
                    _markdown_cell(entry.brand),
                    _markdown_cell(entry.model_id),
                    _markdown_cell(entry.relative_path),
                    _markdown_cell(entry.reason),
                )
            )
            + " |"
        )
    if not board.out_of_scope_idcevo_dirs:
        lines.append("|  |  | no rows |  |")
    lines.extend(
        (
            "",
            "## Documented Rack Targets With No Delivery Row",
            "",
            "| Brand | Model | Path | Reason |",
            "| --- | --- | --- | --- |",
        )
    )
    for entry in board.missing_rack_target_dirs:
        lines.append(
            "| "
            + " | ".join(
                (
                    _markdown_cell(entry.brand),
                    _markdown_cell(entry.model_id),
                    _markdown_cell(entry.relative_path),
                    _markdown_cell(entry.reason),
                )
            )
            + " |"
        )
    if not board.missing_rack_target_dirs:
        lines.append("|  |  | no rows |  |")
    lines.extend(
        (
            "",
            "## Delivery Context",
            "",
            "Delivery status is planning context and is not an asset-ready blocker.",
            "",
            "| Brand | Model | Delivery status | Version | Date | Note |",
            "| --- | --- | --- | --- | --- | --- |",
        )
    )
    for entry in board.entries:
        lines.append(
            "| "
            + " | ".join(
                (
                    _markdown_cell(entry.brand),
                    _markdown_cell(entry.model_id),
                    _markdown_cell(entry.delivery_status_label),
                    _markdown_cell(entry.delivery_context.version),
                    _markdown_cell(entry.delivery_context.delivered_date),
                    _markdown_cell(entry.delivery_context.note),
                )
            )
            + " |"
        )
    lines.extend(
        (
            "",
            "## Operator-Confirmed Environment Checklist",
            "",
            "These items are operator-confirmed and not auto-checked by SGFX.",
            "",
        )
    )
    for item in board.operator_checklist:
        lines.append(f"- {item.label} ({item.status}; anchor: {item.confluence_anchor}) - {item.detail}")
    return "\n".join(lines).rstrip() + "\n"


def write_rack_readiness_board(
    board: RackReadinessBoard,
    output_root: Path,
) -> dict[str, str]:
    output_root.mkdir(parents=True, exist_ok=True)
    json_path = output_root / "rack-readiness.json"
    markdown_path = output_root / "rack-readiness.md"
    json_path.write_text(json.dumps(board.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    markdown_path.write_text(rack_readiness_markdown(board), encoding="utf-8")
    return {
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
    }
