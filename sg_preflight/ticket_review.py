from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile
from typing import Any, Iterable

from sg_preflight.bmw_delivery import BmwScreenshotSurface, inspect_bmw_screenshot_surface
from sg_preflight.daily_snapshot import (
    BmwBatteryResult,
    BmwConfigCheckResult,
    BmwSmokeResult,
    DailyQaSnapshot,
    DailyQaSnapshotResult,
    _battery_baseline_gap_payload,
    _render_battery_baseline_gaps_markdown,
    _render_candidate_review_gallery,
    _render_snapshot_markdown,
    find_latest_daily_qa_snapshot,
)
from sg_preflight.io_utils import read_json, write_json, write_text as _write_text
from sg_preflight.profiles import RunProfile, get_run_profile, resolve_source_repo_root
from sg_preflight.qa_actions import ActionRecord, load_action_record, operator_ui_actions_root
from sg_preflight.screenshot_triage import ScreenshotTriageBundle, ScreenshotTriageReport, materialize_screenshot_triage
from sg_preflight.services import prerequisite_status
from sg_preflight.ticket_evidence_packaging import (
    RacoManualReviewProbeResult,
    TicketFinding,
    TicketManualEvidenceItem,
    _action_ids_for_profile,
    _all_action_records,
    _bundle_evidence,
    _copy_file,
    _copy_manual_evidence_item,
    _copy_tree,
    _counts_by_kind_text,
    _current_support_blockers,
    _dedupe_evidence,
    _display_path,
    _dod_completion_percent,
    _extract_revision,
    _find_latest_raco_manual_review_probe,
    _fresh_output_root,
    _harvest_manual_evidence,
    _is_stale_followup,
    _latest_manual_evidence_record,
    _latest_native_verification_dir,
    _latest_record,
    _load_raco_manual_review_probe,
    _make_zip,
    _manual_evidence_counts,
    _manual_evidence_index_markdown,
    _manual_evidence_json_payload,
    _manual_evidence_key,
    _manual_followups,
    _manual_review_template_paths,
    _manual_review_texts,
    _materialize_manual_review_templates,
    _package_action_records,
    _package_daily_snapshot_result,
    _package_external_file,
    _package_live_source,
    _package_live_sources,
    _package_raco_manual_review_probe,
    _package_verification_dir,
    _packaged_source_evidence,
    _read_json,
    _record_findings,
    _resolve_snapshot_artifact_path,
    _safe_relative,
    _sent_package_manifest_markdown,
    _sha256_file,
    _slug,
    _support_blockers,
    _unique_records,
    _utc_now,
    _write_json,
    default_ticket_review_output_root,
)
from sg_preflight.ticket_dod import (
    ReviewEvidence,
    TicketDoDItem,
    _ACTION_KIND_IDS,
    _BMW_DOC_URLS,
    _DELIVERY_REFERENCE_SPECS,
    _DELIVERY_TARGET_SPECS,
    _MANUAL_EVIDENCE_ASSET_KINDS,
    _PROCESS_HINTS,
    _PROCESS_QUESTIONS,
    _QA_CAPABILITY_SPECS,
    _QA_CONFLUENCE_SNAPSHOT_DATE,
    _QUALITY_HERO_PROCESS_REFERENCE,
    _THREE_D_QA_TEST_CATALOG,
    _bundle_blockers,
    _bundle_notes,
    _bundle_questions,
    _delivery_surface_map_markdown,
    _delivery_target_catalog_markdown,
    _overall_status,
    _path_status,
    _qa_capability_matrix_markdown,
    _raco_script_catalog_markdown,
    _repo_topology_reference_markdown,
    _repository_layout_roots,
    _resolve_capability_paths,
    _three_d_qa_playbook_markdown,
)
from sg_preflight.visual_review import VisualReviewPrep, build_visual_review_prep


@dataclass(frozen=True)
class TicketReviewBundle:
    ticket_id: str
    title: str
    generated_at_utc: str
    overall_status: str
    profile_ids: tuple[str, ...]
    source_root: str
    source_revision: str = ""
    source_mode: str = ""
    scope_note: str = ""
    notes: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    next_questions: tuple[str, ...] = ()
    findings: tuple[TicketFinding, ...] = ()
    evidence_index: tuple[ReviewEvidence, ...] = ()
    dod_items: tuple[TicketDoDItem, ...] = ()
    manual_evidence: tuple[TicketManualEvidenceItem, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticket_id": self.ticket_id,
            "title": self.title,
            "generated_at_utc": self.generated_at_utc,
            "overall_status": self.overall_status,
            "profile_ids": list(self.profile_ids),
            "source_root": self.source_root,
            "source_revision": self.source_revision,
            "source_mode": self.source_mode,
            "scope_note": self.scope_note,
            "notes": list(self.notes),
            "blockers": list(self.blockers),
            "next_questions": list(self.next_questions),
            "findings": [item.to_dict() for item in self.findings],
            "evidence_index": [item.to_dict() for item in self.evidence_index],
            "dod_items": [item.to_dict() for item in self.dod_items],
            "manual_evidence": [item.to_dict() for item in self.manual_evidence],
        }


@dataclass(frozen=True)
class TicketReviewBundleResult:
    bundle: TicketReviewBundle
    package_root: Path
    bundle_json_path: Path
    review_status_path: Path
    dod_matrix_path: Path
    dod_update_draft_path: Path
    teams_update_path: Path
    stakeholder_sync_path: Path
    review_protocol_path: Path
    owner_matrix_path: Path
    qa_capability_matrix_path: Path
    three_d_qa_playbook_path: Path
    repo_topology_reference_path: Path
    delivery_surface_map_path: Path
    raco_script_catalog_path: Path
    delivery_target_catalog_path: Path
    manual_review_companion_path: Path
    manual_evidence_index_path: Path
    manual_evidence_json_path: Path
    review_owner_decisions_path: Path
    sent_package_manifest_path: Path
    zip_sha256_path: Path
    zip_path: Path


@dataclass
class _ProfileContext:
    profile: RunProfile
    prep: VisualReviewPrep
    bmw_surface: BmwScreenshotSurface
    triage_bundle: ScreenshotTriageBundle
    scene_record: ActionRecord | None
    stack_record: ActionRecord | None
    repo_record: ActionRecord | None
    delivery_record: ActionRecord | None
    manual_evidence_records: tuple[ActionRecord, ...]
    action_records_for_package: tuple[ActionRecord, ...]
    action_bundle_evidence: tuple[ReviewEvidence, ...]
    packaged_source_evidence: tuple[ReviewEvidence, ...]
    packaged_source_index: dict[str, ReviewEvidence]
    manual_review_paths: dict[str, Path]
    bmw_surface_markdown_path: Path
    bmw_surface_json_path: Path


def _bmw_surface_markdown(surface: BmwScreenshotSurface) -> str:
    lines = [
        f"# BMW screenshot surface - {surface.profile_id}",
        "",
        f"- SG profile: `{surface.profile_id}`",
        f"- BMW profile folder: `{surface.bmw_profile_id}`",
        f"- BMW repo root: `{surface.repo_root or 'not found'}`",
        f"- BMW cars root: `{surface.cars_root or 'not found'}`",
        f"- BMW car root: `{surface.car_root or 'not found'}`",
        f"- BMW CI scripts root: `{surface.ci_scripts_root or 'not found'}`",
        f"- BMW CI tools root: `{surface.ci_tools_root or 'not found'}`",
        f"- BMW CI README: `{surface.ci_readme_path or 'not found'}`",
        f"- BMW car_manager.py: `{surface.car_manager_path or 'not found'}`",
        f"- Export/tests root: `{surface.export_tests_root or 'not found'}`",
        f"- SG expected root: `{surface.sg_expected_root or 'not found'}` ({surface.sg_expected_count} image(s))",
        f"- BMW expected root: `{surface.bmw_expected_root or 'not found'}` ({surface.bmw_expected_count} image(s))",
        f"- BMW actuals root: `{surface.actuals_root or 'not found'}` ({surface.actual_count} image(s))",
        f"- BMW diff root: `{surface.diff_root or 'not found'}` ({surface.diff_count} image(s))",
        f"- BMW test config: `{surface.test_config_path or 'not found'}`",
        "",
        "## Documented BMW command surface",
        "- IDC_23 export command: `py ci/scripts/test/main.py export <CAR>` on `assets/idc23`",
        "- IDC_23 screenshot comparison command: `py ci/scripts/test/main.py screenshots --diff <CAR>` on `assets/idc23`",
        "- IDC_EVO export command: `py ci/scripts/car_manager.py export <CAR>` on `master`",
        "- IDC_EVO screenshot comparison command: `py ci/scripts/car_manager.py screenshots --diff <CAR>` on `master`",
        "- External RCA screenshot command: `py ci/scripts/car_manager.py screenshots_ext C:/PATH/TO/PROJECT.rca -b BMW`",
        "- Expected screenshot proof: the current repo writes into `export/tests/{expected,actuals,diff}`.",
        "- Expected export proof: captured export log plus the printed binary file sizes from the lane export command.",
        "",
        "## Notes",
    ]
    if surface.notes:
        lines.extend(f"- {note}" for note in surface.notes)
    else:
        lines.append("- No BMW-side notes were recorded for this profile.")
    return "\n".join(lines).rstrip() + "\n"


def _profile_context(
    *,
    ticket_id: str,
    profile_id: str,
    workspace: Path,
    package_root: Path,
    candidate_roots: tuple[Path, ...],
    source_root: Path,
    all_records: tuple[ActionRecord, ...],
    include_action_bundles: bool,
) -> _ProfileContext:
    profile = get_run_profile(profile_id, workspace)
    prep = build_visual_review_prep(profile.profile_id, profile.source_project_root(), repo_root=source_root)
    bmw_surface = inspect_bmw_screenshot_surface(
        profile.profile_id,
        workspace_root=workspace,
        sg_project_root=profile.source_project_root(),
    )
    triage_root = package_root / "artifacts" / "screenshot-triage" / profile.profile_id.lower()
    effective_expected_root = Path(bmw_surface.sg_expected_root or bmw_surface.bmw_expected_root) if (
        bmw_surface.sg_expected_root or bmw_surface.bmw_expected_root
    ) else None
    effective_candidate_roots = tuple(
        dict.fromkeys(
            [
                *(path.resolve() for path in candidate_roots),
                *(Path(bmw_surface.actuals_root).resolve() for _ in [0] if bmw_surface.actuals_root),
            ]
        )
    )
    effective_diff_roots = tuple(
        Path(bmw_surface.diff_root).resolve()
        for _ in [0]
        if bmw_surface.diff_root
    )
    triage_bundle = materialize_screenshot_triage(
        profile.profile_id,
        profile.source_project_root(),
        triage_root,
        expected_root=effective_expected_root,
        candidate_roots=effective_candidate_roots,
        diff_reference_roots=effective_diff_roots,
        priority_names=prep.priority_screenshots,
    )
    bmw_surface_root = package_root / "artifacts" / "bmw-surface" / profile.profile_id.lower()
    bmw_surface_markdown_path = bmw_surface_root / "surface.md"
    bmw_surface_json_path = bmw_surface_root / "surface.json"
    _write_text(bmw_surface_markdown_path, _bmw_surface_markdown(bmw_surface))
    _write_json(bmw_surface_json_path, bmw_surface.to_dict())

    action_ids = _action_ids_for_profile(profile.profile_id)
    scene_record = _latest_record(all_records, action_ids["scene"])
    stack_record = _latest_record(all_records, action_ids["stack"])
    repo_record = _latest_record(all_records, action_ids["repo"])
    delivery_record = _latest_record(all_records, action_ids["delivery"])
    manual_records = _unique_records(
        _latest_manual_evidence_record(all_records, action_id)
        for action_id in action_ids.values()
    )
    records_for_package = _unique_records((scene_record, stack_record, repo_record, delivery_record, *manual_records))
    action_bundle_evidence = ()
    if include_action_bundles:
        action_bundle_evidence = _package_action_records(records_for_package, package_root)

    source_paths = [
        prep.changelog_path,
        prep.constants_readme_path,
        *prep.project_readme_paths[:1],
        prep.screenshot_test_config_path,
        bmw_surface.test_config_path,
        bmw_surface.ci_readme_path,
        bmw_surface.car_manager_path,
        *prep.shared_doc_paths,
    ]
    packaged_source_evidence, packaged_source_index = _package_live_sources(source_paths, package_root, source_root)
    manual_review_paths = _manual_review_template_paths(package_root, profile.profile_id)

    context = _ProfileContext(
        profile=profile,
        prep=prep,
        bmw_surface=bmw_surface,
        triage_bundle=triage_bundle,
        scene_record=scene_record,
        stack_record=stack_record,
        repo_record=repo_record,
        delivery_record=delivery_record,
        manual_evidence_records=manual_records,
        action_records_for_package=records_for_package,
        action_bundle_evidence=action_bundle_evidence,
        packaged_source_evidence=packaged_source_evidence,
        packaged_source_index=packaged_source_index,
        manual_review_paths=manual_review_paths,
        bmw_surface_markdown_path=bmw_surface_markdown_path,
        bmw_surface_json_path=bmw_surface_json_path,
    )
    _materialize_manual_review_templates(ticket_id=ticket_id, context=context)
    return context


def _build_manual_review_index(ticket_id: str, contexts: tuple[_ProfileContext, ...]) -> str:
    lines = [
        f"# Manual Review Companion - {ticket_id}",
        "",
        "This index points to the packaged manual-review templates for each grounded slice.",
        "",
    ]
    for context in contexts:
        lines.extend(
            [
                f"## {context.profile.profile_id}",
                f"- Companion: `{context.manual_review_paths['companion']}`",
                f"- Manual review record: `{context.manual_review_paths['record']}`",
                f"- Screenshot evidence slots: `{context.manual_review_paths['slots']}`",
                f"- Blender vs RaCo checklist: `{context.manual_review_paths['blender_raco']}`",
                f"- Visual review checklist: `{context.manual_review_paths['visual_checklist']}`",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _item_status_summary(
    report: ScreenshotTriageReport,
) -> str:
    return (
        f"{report.pair_count} baseline image(s) are already available locally. "
        f"Triage currently sees {report.missing_candidate_count} missing candidate pair(s), "
        f"{report.near_identical_count} near-identical pair(s), {report.needs_review_count} changed pair(s), "
        f"and {report.dimension_mismatch_count} dimension mismatch pair(s). Visual labels: "
        f"{report.cosmetic_likely_pass_count} cosmetic likely pass, "
        f"{report.structural_likely_review_count} structural likely review, "
        f"{report.unclear_manual_review_count} unclear manual review."
    )


def _screenshot_surface_summary(contexts: tuple[_ProfileContext, ...]) -> str:
    if not contexts:
        return "No confirmed local slice is grounded yet, so screenshot-test evidence is intentionally not claimed."
    parts: list[str] = []
    for context in contexts:
        surface = context.bmw_surface
        report = context.triage_bundle.report
        part = (
            f"{context.profile.profile_id}: SG expected {surface.sg_expected_count}, "
            f"BMW expected {surface.bmw_expected_count}, actuals {surface.actual_count}, diff {surface.diff_count}"
        )
        if surface.export_tests_root:
            if surface.actual_count == 0 and surface.diff_count == 0:
                part += "; BMW screenshot surface exists but currently contains no screenshot payload"
            else:
                part += (
                    f"; triage pairs {report.pair_count}, needs review {report.needs_review_count}, "
                    f"structural labels {report.structural_likely_review_count}, "
                    f"unclear labels {report.unclear_manual_review_count}"
                )
        else:
            part += "; BMW export/tests surface not present locally"
        parts.append(part)
    return "<br>".join(parts)


def _headless_surface_summary(contexts: tuple[_ProfileContext, ...]) -> str:
    if not contexts:
        return "No confirmed local slice is grounded yet, so BMW headless-export readiness is intentionally not claimed."
    ready = [context for context in contexts if context.bmw_surface.car_manager_path]
    if ready:
        profiles = ", ".join(context.profile.profile_id for context in ready)
        return (
            f"BMW repo helpers are locally visible for {profiles}: `ci/scripts/car_manager.py` and the CI README are packaged. "
            "Representative local export proof should be attached separately wherever the daily snapshot contains completed smoke results; if review owners accept that proof, the remaining headless question is only whether any broader scenario coverage is still required."
        )
    return "The BMW headless-export helper surface is still not visible locally for the grounded slice(s)."


def _snapshot_smoke_results(
    snapshot_result: DailyQaSnapshotResult | None,
    contexts: tuple[_ProfileContext, ...],
) -> dict[str, Any]:
    if snapshot_result is None or not contexts:
        return {}

    scoped_profiles = {context.profile.profile_id.upper() for context in contexts}
    result_map = {
        item.profile_id.upper(): item
        for item in snapshot_result.snapshot.smoke_results
        if item.profile_id and item.profile_id.upper() in scoped_profiles
    }
    if not result_map or scoped_profiles - set(result_map):
        return {}
    return result_map


def _snapshot_battery_results(
    snapshot_result: DailyQaSnapshotResult | None,
    contexts: tuple[_ProfileContext, ...],
) -> dict[str, tuple[Any, ...]]:
    if snapshot_result is None or not contexts:
        return {}

    scoped_profiles = {context.profile.profile_id.upper() for context in contexts}
    result_map: dict[str, list[Any]] = {}
    for item in getattr(snapshot_result.snapshot, "battery_results", ()):
        profile_key = str(getattr(item, "profile_id", "")).upper()
        if not profile_key or profile_key not in scoped_profiles:
            continue
        result_map.setdefault(profile_key, []).append(item)
    if not result_map or scoped_profiles - set(result_map):
        return {}
    return {key: tuple(value) for key, value in result_map.items()}


def _select_attach_run(context: _ProfileContext) -> ActionRecord | None:
    for record in (
        *(record for record in context.manual_evidence_records if record.action_id.startswith("scene_check")),
        context.scene_record,
        *(record for record in context.manual_evidence_records if record.action_id.startswith("qa_stack")),
        context.stack_record,
    ):
        if record is not None:
            return record
    return None


def _attach_examples(contexts: tuple[_ProfileContext, ...], workspace: Path) -> tuple[str, ...]:
    blocks: list[str] = []
    for context in contexts:
        target = _select_attach_run(context)
        if target is None:
            continue
        profile_id = context.profile.profile_id
        block = "\n".join(
            [
                f"### {profile_id}",
                "```powershell",
                f'python -m sg_preflight.cli desktop-state attach-manual-evidence "{target.run_id}" --workspace "{workspace}" --kind screenshot --label "{profile_id} manual screenshot" --source "C:\\path\\to\\manual-shot.png"',
                f'python -m sg_preflight.cli desktop-state attach-manual-evidence "{target.run_id}" --workspace "{workspace}" --kind raco_note --label "{profile_id} RaCo note" --note "Scene checked: ..."',
                f'python -m sg_preflight.cli desktop-state attach-manual-evidence "{target.run_id}" --workspace "{workspace}" --kind blender_note --label "{profile_id} Blender note" --note "Workfile checked: ..."',
                f'python -m sg_preflight.cli desktop-state attach-manual-evidence "{target.run_id}" --workspace "{workspace}" --kind visual_review_checklist --label "{profile_id} visual checklist" --note "Project changelog reviewed: [x]"',
                "```",
            ]
        )
        blocks.append(block)
    return tuple(blocks)


def _test_case_area(key: str) -> str:
    name = Path(key).name.lower()
    if name.startswith("lights_"):
        return "Lighting and signal states"
    if name in {"cameraview", "default", "default_rear"}:
        return "Default and camera views"
    if name.startswith("glow_") or "godrays" in name:
        return "Glow and atmospheric effects"
    if name.startswith("groundfloor"):
        return "Ground and reflection"
    if name.startswith("highlighting_seats_"):
        return "Seat states and layouts"
    if name.startswith("highlighting_sensors_"):
        return "Sensor highlighting"
    if name.startswith("highlighting_doors") or name.startswith("highlighting_fuel") or name.startswith("highlighting_hood"):
        return "Body highlighting and access points"
    if "wheel" in name or "tire" in name or name.startswith("trimline_") or name.startswith("motion_"):
        return "Wheel and tire review"
    if name.startswith("customcolor_"):
        return "Custom colors and trimlines"
    return "Other"


def _possible_test_case_lines(context: _ProfileContext) -> list[str]:
    report = context.triage_bundle.report
    prep = context.prep
    lines = [
        f"### {context.profile.profile_id}",
        f"- Changelog heading: {prep.changelog_heading or 'not found'}",
        f"- Representative RaCo scene: `{prep.raco_scene_path or 'not found'}`",
        f"- Representative Blender workfile: `{prep.blender_workfile_path or 'not found'}`",
        f"- Screenshot baseline root: `{prep.screenshot_root or 'not found'}`",
        "- Priority screenshots: "
        + (", ".join(prep.priority_screenshots[:6]) if prep.priority_screenshots else "none detected"),
        "",
        "| Test-case area | Baselines | Current triage | Example screenshots |",
        "| --- | ---: | --- | --- |",
    ]
    groups: dict[str, list[str]] = {}
    for pair in report.pairs:
        groups.setdefault(_test_case_area(pair.key), []).append(Path(pair.key).name)

    ordered_areas = [
        "Lighting and signal states",
        "Default and camera views",
        "Glow and atmospheric effects",
        "Ground and reflection",
        "Body highlighting and access points",
        "Seat states and layouts",
        "Sensor highlighting",
        "Wheel and tire review",
        "Custom colors and trimlines",
        "Other",
    ]
    for area in ordered_areas:
        names = groups.get(area, [])
        if not names:
            continue
        missing = sum(
            1
            for pair in report.pairs
            if _test_case_area(pair.key) == area and pair.classification == "missing_candidate"
        )
        needs_review = sum(
            1
            for pair in report.pairs
            if _test_case_area(pair.key) == area and pair.classification == "needs_review"
        )
        structural = sum(
            1
            for pair in report.pairs
            if _test_case_area(pair.key) == area and pair.visual_classification == "structural_likely_review"
        )
        unclear = sum(
            1
            for pair in report.pairs
            if _test_case_area(pair.key) == area and pair.visual_classification == "unclear_manual_review"
        )
        state = (
            f"{missing} missing candidate"
            if missing
            else f"{structural} structural review signal"
            if structural
            else f"{unclear} unclear manual review"
            if unclear
            else f"{needs_review} needs review"
            if needs_review
            else "triage ready"
        )
        lines.append(f"| {area} | {len(names)} | {state} | {', '.join(names[:3])} |")
    lines.append("")
    return lines


def _build_dod_items(
    *,
    contexts: tuple[_ProfileContext, ...],
    workspace: Path,
    scope_note: str,
    manual_evidence: tuple[TicketManualEvidenceItem, ...],
    manual_evidence_index_path: Path,
    support_artifacts: tuple[ReviewEvidence, ...] = (),
    daily_snapshot: DailyQaSnapshotResult | None = None,
    raco_probe: RacoManualReviewProbeResult | None = None,
    include_action_bundles: bool = True,
) -> tuple[TicketDoDItem, ...]:
    scope_grounded = bool(contexts)
    screenshot_manual = tuple(item for item in manual_evidence if item.kind == "screenshot")
    asset_manual = tuple(item for item in manual_evidence if item.kind in _MANUAL_EVIDENCE_ASSET_KINDS)
    format_findings = tuple(finding for context in contexts for finding in _record_findings(context.repo_record))
    snapshot_results = _snapshot_smoke_results(daily_snapshot, contexts)
    snapshot_battery = _snapshot_battery_results(daily_snapshot, contexts)
    snapshot_diagnostics = tuple(daily_snapshot.snapshot.diagnostics) if daily_snapshot is not None else ()
    snapshot_smoke_completed = bool(snapshot_results) and all(
        item.status == "completed" for item in snapshot_results.values()
    )
    snapshot_headless_covered = snapshot_smoke_completed and all(
        item.exported_ramses_size > 0 for item in snapshot_results.values()
    )
    snapshot_screenshot_ready = snapshot_smoke_completed and all(
        item.expected_count > 0 and item.actual_count > 0 for item in snapshot_results.values()
    )
    snapshot_all_compare_ok = snapshot_screenshot_ready and all(
        item.compare_ok and item.diff_count == 0 for item in snapshot_results.values()
    )
    baselines_present = any(
        context.prep.screenshot_count > 0
        or context.bmw_surface.sg_expected_count > 0
        or context.bmw_surface.bmw_expected_count > 0
        for context in contexts
    )
    bmw_screenshot_surface_present = any(context.bmw_surface.export_tests_root for context in contexts)
    bmw_headless_surface_present = any(context.bmw_surface.car_manager_path for context in contexts)
    screenshot_status = (
        "partial"
        if snapshot_screenshot_ready or baselines_present or screenshot_manual or bmw_screenshot_surface_present
        else "blocked"
    )
    asset_status = "partial" if asset_manual else "manual_ready" if any(
        context.prep.raco_scene_path or context.prep.blender_workfile_path for context in contexts
    ) else "blocked"
    format_status = "covered_with_findings" if format_findings else "covered" if any(
        context.repo_record and context.repo_record.status == "completed" for context in contexts
    ) else "blocked"
    changelog_status = "prepared" if any(context.prep.changelog_path for context in contexts) else "blocked"
    readme_status = "prepared" if any(
        context.prep.constants_readme_path or context.prep.project_readme_paths for context in contexts
    ) else "blocked"
    shared_status = "prepared" if any(context.prep.shared_doc_paths for context in contexts) else "blocked"
    headless_status = "covered" if snapshot_headless_covered else "partial" if bmw_headless_surface_present else "blocked"
    raco_probe_ready = bool(raco_probe and {
        item.strip().upper() for item in raco_probe.profile_ids if item and item.strip()
    }.issuperset({context.profile.profile_id.upper() for context in contexts}))

    screenshot_evidence: list[ReviewEvidence] = []
    asset_evidence: list[ReviewEvidence] = []
    format_evidence: list[ReviewEvidence] = []
    changelog_evidence: list[ReviewEvidence] = []
    readme_evidence: list[ReviewEvidence] = []
    shared_evidence: list[ReviewEvidence] = []
    headless_evidence: list[ReviewEvidence] = []
    support_evidence: list[ReviewEvidence] = [
        _bundle_evidence("Ticket manual evidence index", manual_evidence_index_path),
        *support_artifacts,
    ]
    if daily_snapshot is not None:
        snapshot_rel = _bundle_evidence("Daily QA snapshot", daily_snapshot.markdown_path)
        snapshot_json_rel = _bundle_evidence("Daily QA snapshot JSON", daily_snapshot.json_path)
        screenshot_evidence.extend((snapshot_rel, snapshot_json_rel))
        headless_evidence.extend((snapshot_rel, snapshot_json_rel))
        support_evidence.extend((snapshot_rel, snapshot_json_rel))
        if daily_snapshot.battery_baseline_gaps_markdown_path is not None:
            baseline_rel = _bundle_evidence(
                "Battery baseline gaps",
                daily_snapshot.battery_baseline_gaps_markdown_path,
            )
            screenshot_evidence.append(baseline_rel)
            support_evidence.append(baseline_rel)
        if daily_snapshot.battery_baseline_gaps_json_path is not None:
            baseline_json_rel = _bundle_evidence(
                "Battery baseline gaps JSON",
                daily_snapshot.battery_baseline_gaps_json_path,
            )
            screenshot_evidence.append(baseline_json_rel)
            support_evidence.append(baseline_json_rel)
        if daily_snapshot.review_priority_markdown_path is not None:
            priority_rel = _bundle_evidence(
                "Review priority ranking",
                daily_snapshot.review_priority_markdown_path,
            )
            screenshot_evidence.append(priority_rel)
            support_evidence.append(priority_rel)
        if daily_snapshot.review_priority_json_path is not None:
            priority_json_rel = _bundle_evidence(
                "Review priority ranking JSON",
                daily_snapshot.review_priority_json_path,
            )
            screenshot_evidence.append(priority_json_rel)
            support_evidence.append(priority_json_rel)
        if daily_snapshot.delta_summary_markdown_path is not None:
            delta_rel = _bundle_evidence(
                "Daily QA delta summary",
                daily_snapshot.delta_summary_markdown_path,
            )
            support_evidence.append(delta_rel)
        if daily_snapshot.delta_summary_json_path is not None:
            delta_json_rel = _bundle_evidence(
                "Daily QA delta summary JSON",
                daily_snapshot.delta_summary_json_path,
            )
            support_evidence.append(delta_json_rel)
        if daily_snapshot.review_gallery_html_path is not None:
            review_gallery_rel = _bundle_evidence(
                "Candidate review gallery",
                daily_snapshot.review_gallery_html_path,
            )
            screenshot_evidence.append(review_gallery_rel)
            support_evidence.append(review_gallery_rel)
    if raco_probe is not None:
        probe_rel = _bundle_evidence("RaCo manual review probe", raco_probe.markdown_path)
        probe_json_rel = _bundle_evidence("RaCo manual review probe JSON", raco_probe.json_path)
        asset_evidence.extend((probe_rel, probe_json_rel))
        support_evidence.extend((probe_rel, probe_json_rel))

    for context in contexts:
        triage = context.triage_bundle
        prep = context.prep
        screenshot_evidence.extend(
            [
                _packaged_source_evidence(
                    context,
                    prep.screenshot_test_config_path or context.bmw_surface.test_config_path or "not found",
                    label="Screenshot test config",
                ),
                _bundle_evidence(f"{context.profile.profile_id} screenshot triage", triage.markdown_path),
                _bundle_evidence(f"{context.profile.profile_id} BMW screenshot surface", context.bmw_surface_markdown_path),
                _bundle_evidence("Screenshot evidence slots", context.manual_review_paths["slots"]),
                _bundle_evidence("Visual review checklist", context.manual_review_paths["visual_checklist"]),
            ]
        )
        asset_evidence.extend(
            [
                _bundle_evidence("Manual review companion", context.manual_review_paths["companion"]),
                _bundle_evidence("Manual review record", context.manual_review_paths["record"]),
                _bundle_evidence("Blender vs RaCo checklist", context.manual_review_paths["blender_raco"]),
            ]
        )
        if include_action_bundles and context.repo_record is not None:
            format_evidence.append(_bundle_evidence(f"{context.profile.profile_id} repo checker summary", context.repo_record.paths.get("summary_md", "")))
        if format_findings:
            first = format_findings[0]
            format_evidence.append(_bundle_evidence("First concrete finding", first.path or ""))
        if prep.changelog_path:
            changelog_evidence.append(_packaged_source_evidence(context, prep.changelog_path, label="Car changelog"))
        if prep.constants_readme_path:
            readme_evidence.append(_packaged_source_evidence(context, prep.constants_readme_path, label="Car README"))
        elif prep.project_readme_paths:
            readme_evidence.append(_packaged_source_evidence(context, prep.project_readme_paths[0], label="Car README"))
        if prep.shared_doc_paths:
            for path in prep.shared_doc_paths[:6]:
                shared_evidence.append(_packaged_source_evidence(context, path, label="Shared BMW doc"))
        if include_action_bundles and context.delivery_record is not None:
            headless_evidence.append(
                _bundle_evidence(
                    f"{context.profile.profile_id} delivery checklist summary",
                    context.delivery_record.paths.get("summary_md", ""),
                )
            )
        headless_evidence.extend(
            [
                _bundle_evidence(f"{context.profile.profile_id} BMW screenshot surface", context.bmw_surface_markdown_path),
                _packaged_source_evidence(context, context.bmw_surface.car_manager_path or "not found", label="BMW car_manager.py"),
                _packaged_source_evidence(context, context.bmw_surface.ci_readme_path or "not found", label="BMW CI README"),
            ]
        )
        snapshot_item = snapshot_results.get(context.profile.profile_id.upper())
        if snapshot_item is not None and snapshot_item.log_path:
            log_evidence = _bundle_evidence(
                f"{context.profile.profile_id} BMW smoke log",
                _resolve_snapshot_artifact_path(daily_snapshot, snapshot_item.log_path),
            )
            screenshot_evidence.append(log_evidence)
            headless_evidence.append(log_evidence)
        battery_items = snapshot_battery.get(context.profile.profile_id.upper(), ())
        if battery_items:
            seen_battery_logs: set[str] = set()
            for battery_item in battery_items:
                resolved_log_path = _resolve_snapshot_artifact_path(daily_snapshot, battery_item.log_path)
                if resolved_log_path in seen_battery_logs or resolved_log_path == "not found":
                    continue
                seen_battery_logs.add(resolved_log_path)
                screenshot_evidence.append(
                    _bundle_evidence(f"{context.profile.profile_id} BMW battery log", resolved_log_path)
                )
        support_evidence.append(_bundle_evidence("Scope note", scope_note))

    for item in manual_evidence:
        evidence = _bundle_evidence(f"{item.kind}: {item.label}", item.packaged_path)
        support_evidence.append(evidence)
        if item.kind == "screenshot":
            screenshot_evidence.append(evidence)
        if item.kind in _MANUAL_EVIDENCE_ASSET_KINDS:
            asset_evidence.append(evidence)

    triage_reports = [context.triage_bundle.report for context in contexts]
    screenshot_summary = _screenshot_surface_summary(contexts)
    if snapshot_results:
        snapshot_parts = []
        for context in contexts:
            item = snapshot_results.get(context.profile.profile_id.upper())
            if item is None:
                continue
            status_text = (
                "passed locally with no visible diff"
                if item.compare_ok and item.diff_count == 0
                else "needs manual review"
                if item.diff_count > 0
                else item.status
            )
            snapshot_parts.append(
                f"{context.profile.profile_id}: smoke `{item.smoke_test}` -> {status_text}; "
                f"expected {item.expected_count}, actual {item.actual_count}, diff {item.diff_count}, "
                f"Ramses {item.exported_ramses_size}b"
            )
            battery_items = snapshot_battery.get(context.profile.profile_id.upper(), ())
            if battery_items:
                verdict_counts: dict[str, int] = {}
                for battery_item in battery_items:
                    verdict = str(getattr(battery_item, "verdict", "")).strip() or "unknown"
                    verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
                snapshot_parts.append(
                    f"{context.profile.profile_id}: broader battery -> "
                    + ", ".join(f"{key} {value}" for key, value in sorted(verdict_counts.items()))
                )
        if snapshot_parts:
            for diagnostic in snapshot_diagnostics:
                snapshot_parts.append(f"battery diagnosis -> {diagnostic}")
            screenshot_summary = "<br>".join(snapshot_parts)

    headless_summary = _headless_surface_summary(contexts)
    if snapshot_results:
        executed = ", ".join(
            f"{item.profile_id} ({item.exported_ramses_size}b Ramses)"
            for item in snapshot_results.values()
            if item.status == "completed"
        )
        if executed:
            headless_summary = (
                f"Representative local BMW export proof is attached for {executed}. "
                "The smoke logs include `Export finished` and `File sizes` output from the BMW helper flow."
            )

    if snapshot_screenshot_ready:
        screenshot_next_input = (
            "Representative local smoke evidence is attached for the confirmed cars. Remaining work is the final visual verdict for exact/proxy-ready outputs plus review-owner confirmation on whether `lights_OnlyCones` is a delivery blocker or a follow-up."
            if snapshot_diagnostics
            else "Representative local smoke evidence is attached for the confirmed cars. Remaining work is broader scenario coverage plus human screenshot verdicts for any changed outputs once those scenarios emit the right targets."
        )
    else:
        screenshot_next_input = (
            "Need real screenshot payload for the confirmed cars when folders are empty, plus the normal pass/fail reading flow from Adrian / Hristofor / Stefan."
        )
    headless_next_input = (
        "Representative local BMW export proof is attached. Need review-owner confirmation whether this local proof is accepted as DoD evidence and whether any broader scenario coverage is still required."
        if snapshot_headless_covered
        else "Need captured `export finished` and file sizes output for one confirmed delivery car."
    )
    if snapshot_screenshot_ready:
        screenshot_now_text = (
            "Use the attached daily snapshot, smoke logs, triage outputs, and candidate gallery as the current source of truth. The representative smoke path is green, low/high beam have proxy coverage, and the remaining exact local blocker is `lights_OnlyCones`."
            if snapshot_diagnostics
            else "Use the attached daily snapshot, smoke logs, and triage outputs as the current source of truth. The representative smoke path is green, and the broader battery outputs can now be reviewed directly."
        )
    else:
        screenshot_now_text = (
            "Review the packaged baseline/test-config roots, BMW actuals/diff roots, and deterministic triage output. Treat every changed or missing pair as manual review work, not as an automatic regression verdict."
        )
    headless_now_text = (
        "Use the attached BMW smoke logs as export proof. They already capture `Export finished`, file sizes, and screenshot-compare results for the confirmed delivery cars."
        if snapshot_headless_covered
        else "Package the BMW CI README plus car_manager helper, document the expected `export finished` and file-sizes proof, and only execute the export once the local export proof can be captured."
    )

    return (
        TicketDoDItem(
            key="headless_export_check_bmw",
            label="headless export check bmw",
            status=headless_status,
            summary=headless_summary,
            what_can_be_done_now=headless_now_text,
            blocked_next_input=headless_next_input,
            owner_hint="BMW tooling owner / Adrian / Hristofor / Stefan",
            evidence=_dedupe_evidence(headless_evidence),
        ),
        TicketDoDItem(
            key="screenshot_tests_bmws",
            label="screenshot tests bmws",
            status=screenshot_status,
            summary=screenshot_summary if scope_grounded else "No confirmed local slice is grounded yet, so screenshot-test evidence is intentionally not claimed.",
            what_can_be_done_now=screenshot_now_text,
            blocked_next_input=screenshot_next_input,
            owner_hint="Adrian / Hristofor / Stefan for the reading flow",
            evidence=_dedupe_evidence(screenshot_evidence),
        ),
        TicketDoDItem(
            key="format_checker_svn",
            label="format checker svn",
            status=format_status,
            summary=(
                f"Local SG checker coverage exists for {len(contexts)} slice(s); {len(format_findings)} issue batch(es) or style issue(s) were surfaced."
                if format_findings
                else "Local SG checker coverage exists for the grounded slice(s)."
                if scope_grounded
                else "No confirmed local slice is grounded yet, so SG checker evidence is intentionally not attached to this ticket."
            ),
            what_can_be_done_now="Run or reuse the SG-side repo/style/executeChecks flow directly on the live SVN project root.",
            blocked_next_input="Needs a decision whether minor findings should be fixed now or only reported if SVN must stay untouched.",
            owner_hint="SG TA / code owner",
            evidence=_dedupe_evidence(format_evidence),
        ),
        TicketDoDItem(
            key="check_changelogs_cars_bmw",
            label="check changelogs cars bmw",
            status=changelog_status,
            summary=(
                "The live car changelog and recent SVN context are already available locally."
                if scope_grounded
                else "No confirmed local slice is grounded yet, so no car-specific changelog is being claimed for this ticket."
            ),
            what_can_be_done_now="Review the latest changelog section and recent SVN log lines before trusting screenshot differences.",
            blocked_next_input="Need confirmation whether any additional cars beyond the confirmed delivery scope also belong to this ticket, and which changelog entries should be treated as delivery-relevant.",
            owner_hint="Assigned reviewer once scope is confirmed",
            evidence=_dedupe_evidence(changelog_evidence),
        ),
        TicketDoDItem(
            key="check_readme_cars_bmw",
            label="check readme cars bmw",
            status=readme_status,
            summary=(
                "Car-local README material is already discoverable from the live SVN slice."
                if scope_grounded
                else "No confirmed local slice is grounded yet, so no car-specific README evidence is being claimed for this ticket."
            ),
            what_can_be_done_now="Review the current README/constant notes before closing manual visual review.",
            blocked_next_input="Need confirmation whether any additional cars beyond the confirmed delivery scope also belong to this ticket, and whether any extra README/constants notes must be reviewed.",
            owner_hint="Assigned reviewer once scope is confirmed",
            evidence=_dedupe_evidence(readme_evidence),
        ),
        TicketDoDItem(
            key="asset_review_in_raco_bmws",
            label="asset review in raco (bmws)",
            status=asset_status,
            summary=(
                "Manual evidence is already attached from real action bundles."
                if asset_manual
                else "Representative RaCo scenes are ready and the current headless probe shows them as launchable for the grounded slice(s)."
                if raco_probe_ready
                else "A representative RaCo scene is ready to open for manual review."
                if scope_grounded
                else "No confirmed local slice is grounded yet, so no specific RaCo/Blender review target is being claimed."
            ),
            what_can_be_done_now=(
                "Use the packaged RaCo manual review probe plus the manual-review templates, then open the representative `.rca` scene, compare against Blender/workfiles, and attach manual review notes/screenshots."
                if raco_probe_ready
                else "Open the representative `.rca` scene, compare against Blender/workfiles, and attach manual review notes/screenshots."
            ),
            blocked_next_input="Need agreed pass/fail criteria for what counts as the RaCo asset review being done, not just a scene-open check.",
            owner_hint="Adrian / Hristofor / Stefan for review criteria",
            evidence=_dedupe_evidence(asset_evidence),
        ),
        TicketDoDItem(
            key="check_readme_changelogs_cars_shared_bmw",
            label="check readme/changelogs cars shared bmw",
            status=shared_status,
            summary=(
                "Shared BMW docs are already prioritized from live shared-SVN context."
                if scope_grounded
                else "No confirmed local slice is grounded yet, so shared-module evidence is intentionally not attached."
            ),
            what_can_be_done_now="Review the prioritized shared BMW README and CHANGELOG set alongside the car changelog.",
            blocked_next_input="Need confirmation which `_Shared_IDCevo` or shared BMW modules actually changed for this delivery and must be reviewed.",
            owner_hint="Assigned reviewer once shared-module scope is confirmed",
            evidence=_dedupe_evidence(shared_evidence),
        ),
        TicketDoDItem(
            key="support",
            label="Support",
            status="needs_scope",
            summary="Support is not a verifiable DoD item until the owner and expected output are defined.",
            what_can_be_done_now="Use this bundle for status reporting, blockers, findings, and next-step questions while Jira access is blocked.",
            blocked_next_input="Need Jana to confirm whether the reporting flow is fixable findings -> Quality-Hero bug report channel and status/material -> Jana + Adrian, or if a different cadence/channel is required.",
            owner_hint="Jana",
            evidence=_dedupe_evidence(support_evidence),
        ),
    )


def _review_status_markdown(bundle: TicketReviewBundle, *, package_root: Path | None = None) -> str:
    lines = [
        f"# Ticket Review Status - {bundle.ticket_id}",
        "",
        f"- Title: {bundle.title}",
        f"- Generated at: {bundle.generated_at_utc}",
        f"- Overall status: {bundle.overall_status}",
        f"- Profiles grounded locally: {', '.join(bundle.profile_ids) if bundle.profile_ids else 'none confirmed'}",
        f"- Source root: `{bundle.source_root}`",
    ]
    if bundle.source_revision:
        lines.append(f"- Source revision: `{bundle.source_revision}`")
    if bundle.source_mode:
        lines.append(f"- Source mode: `{bundle.source_mode}`")

    lines.extend(
        [
            "",
            "## Summary",
            (
                "Local SG-side evidence is grounded, but at least one concrete finding still needs owner handling and BMW-owned steps remain blocked."
                if bundle.findings
                else "Local SG-side evidence is grounded, but BMW-owned steps remain blocked or manual."
            ),
            "",
            "## Scope Note",
            bundle.scope_note or "No explicit scope note was provided.",
            "",
            "## Concrete Findings",
        ]
    )
    if bundle.findings:
        for finding in bundle.findings:
            location = finding.path or "path unavailable"
            if finding.line is not None and finding.path:
                location = f"{finding.path}:{finding.line}"
            lines.append(f"- [{finding.severity}] {finding.summary}")
            lines.append(f"  - Source: `{location}`")
            if finding.checkers:
                lines.append(f"  - Checker(s): `{','.join(finding.checkers)}`")
    else:
        lines.append("- No SG-side findings were surfaced in the current local evidence set.")

    lines.extend(
        [
            "",
            "## Manual Evidence Rollup",
            f"- Total attached evidence items: {len(bundle.manual_evidence)}",
            f"- Counts by kind: {_counts_by_kind_text(bundle.manual_evidence)}",
        ]
    )
    if bundle.manual_evidence:
        for item in bundle.manual_evidence:
            lines.append(f"- [{item.kind}] {item.label}")
            lines.append(f"  - Packaged path: `{_display_path(item.packaged_path, package_root)}`")

    lines.extend(["", "## Blockers"])
    if bundle.blockers:
        lines.extend(f"- {item}" for item in bundle.blockers)
    else:
        lines.append("- No unresolved blockers are currently listed.")

    lines.extend(["", "## Next Questions"])
    lines.extend(f"- {item}" for item in bundle.next_questions)

    lines.extend(["", "## Package Evidence"])
    if bundle.evidence_index:
        for item in bundle.evidence_index:
            lines.append(f"- {item.label}: `{_display_path(item.path, package_root)}`")
    else:
        lines.append("- No package evidence paths were recorded.")

    lines.extend(["", "## Notes"])
    lines.extend(f"- {item}" for item in bundle.notes)
    return "\n".join(lines).rstrip() + "\n"


def _dod_matrix_markdown(bundle: TicketReviewBundle, *, package_root: Path | None = None) -> str:
    lines = [
        f"# DoD Matrix - {bundle.ticket_id}",
        "",
        f"- Title: {bundle.title}",
        f"- Scope note: {bundle.scope_note or 'No explicit scope note was provided.'}",
        "",
        "| DoD item | Status | Summary | What can be done now | Blocked / next input | Owner hint |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in bundle.dod_items:
        lines.append(
            f"| {item.label} | {item.status} | {item.summary} | {item.what_can_be_done_now} | {item.blocked_next_input} | {item.owner_hint} |"
        )

    lines.extend(["", "## Evidence Paths"])
    for item in bundle.dod_items:
        lines.append(f"### {item.label}")
        if item.evidence:
            for evidence in item.evidence:
                lines.append(f"- {evidence.label}: `{_display_path(evidence.path, package_root)}`")
        else:
            lines.append("- No evidence linked yet.")

    lines.extend(
        [
            "",
            "## Manual Evidence Rollup",
            f"- Total attached evidence items: {len(bundle.manual_evidence)}",
            f"- Counts by kind: {_counts_by_kind_text(bundle.manual_evidence)}",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _proposed_dod_wording(item: TicketDoDItem) -> str:
    proposed = {
        "headless_export_check_bmw": "Document exact BMW headless export command, expected success output, and latest verified execution evidence.",
        "screenshot_tests_bmws": "Review expected baselines, confirmed candidate/result root, deterministic diff triage, and human verdict for changed or missing pairs.",
        "format_checker_svn": "Run SG checker stack on the confirmed slice and record findings plus fix-vs-report decision.",
        "check_changelogs_cars_bmw": "Review latest car changelog and map intended changes to the screenshots or assets that must be checked.",
        "check_readme_cars_bmw": "Review car-local README/constants notes relevant to the confirmed slice before visual signoff.",
        "asset_review_in_raco_bmws": "Open the agreed RaCo scene, compare against Blender/workfiles, and attach manual note plus screenshot evidence.",
        "check_readme_changelogs_cars_shared_bmw": "Review the shared BMW modules actually touched by the confirmed ticket scope and attach notes.",
        "support": "Define what support means for this sprint: reporting channel, owner, cadence, and expected artifact package.",
    }
    return proposed.get(item.key, item.label)


def _required_evidence_text(item: TicketDoDItem) -> str:
    evidence_map = {
        "headless_export_check_bmw": "Command/script, execution log, success trace, and delivery-doc reference.",
        "screenshot_tests_bmws": "Baseline root, candidate/result root, triage report, diff artifacts if present, and human verdict note.",
        "format_checker_svn": "Repo-checker summary plus any concrete file/line findings.",
        "check_changelogs_cars_bmw": "Live changelog, SVN log lines, and reviewer note on intended changes.",
        "check_readme_cars_bmw": "Relevant README/constants docs plus reviewer note.",
        "asset_review_in_raco_bmws": "Representative `.rca`, Blender workfile, manual note, and screenshot where useful.",
        "check_readme_changelogs_cars_shared_bmw": "Relevant shared README/CHANGELOG docs plus reviewer note.",
        "support": "Teams/Jira-ready note, blockers, open questions, and owner clarification.",
    }
    return evidence_map.get(item.key, "Evidence still needs clarification.")


def _dod_update_draft_markdown(bundle: TicketReviewBundle) -> str:
    lines = [
        f"# DoD Update Draft - {bundle.ticket_id}",
        "",
        f"- Title: {bundle.title}",
        f"- Scope note: {bundle.scope_note or 'No explicit scope note was provided.'}",
        "- This is a refinement draft for Jira/Teams use while direct Jira writeback is still blocked.",
        "",
        "| Current Jira DoD item | Proposed clarified wording | Current state | Proposed owner | Required evidence | Why this wording is safer |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    rationale = {
        "headless_export_check_bmw": "It separates documentation/preconditions from actual BMW-side execution so the item cannot be claimed locally by accident.",
        "screenshot_tests_bmws": "It makes the missing candidate root explicit and keeps the verdict human-reviewed instead of pretending automation closed it.",
        "format_checker_svn": "It clarifies that the SG-side checker is locally executable and that ownership includes deciding whether to fix or report.",
        "check_changelogs_cars_bmw": "It links changelog review to actual review targets instead of treating the changelog as a box-tick.",
        "check_readme_cars_bmw": "It forces slice-scoped documentation review rather than assuming a generic README pass is enough.",
        "asset_review_in_raco_bmws": "It defines done-ness as scene review plus attached evidence, not only opening RaCo once.",
        "check_readme_changelogs_cars_shared_bmw": "It prevents reviewing every shared module blindly and focuses only on the ones that matter for scope.",
        "support": "It turns a vague label into a measurable reporting responsibility.",
    }
    for item in bundle.dod_items:
        lines.append(
            f"| {item.label} | {_proposed_dod_wording(item)} | {item.status} | {item.owner_hint} | {_required_evidence_text(item)} | {rationale.get(item.key, 'Clarify the item before it becomes a false green.')} |"
        )

    lines.extend(
        [
            "",
            "## Immediate recommendation",
            "- Keep G70 only as the earlier prototype/local dry run; do not present it as the current delivery scope.",
            "- Treat `NA8`, `G78`, and `G50` as the current confirmed delivery scope unless Jana adds more cars.",
            "- Ask Adrian / Hristofor / Stefan for the screenshot-result reading flow and the real candidate-output rule when the current `actuals/diff` folders are still empty.",
            "- Keep the current SG checker finding as a minor reported issue until someone decides whether it should be fixed now or only assigned.",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _teams_update_markdown(bundle: TicketReviewBundle) -> str:
    finding_block = ""
    if bundle.findings:
        finding = bundle.findings[0]
        source = finding.path
        if finding.line is not None and finding.path:
            source = f"{finding.path}:{finding.line}"
        finding_block = (
            "Current concrete local SG-side finding:\n"
            f"- {source}\n"
            f"- {finding.summary}\n"
        )

    manual_block = (
        f"\nManual evidence harvested so far: {len(bundle.manual_evidence)} item(s); counts by kind: {_counts_by_kind_text(bundle.manual_evidence)}\n"
        if bundle.manual_evidence
        else ""
    )
    profile_text = ", ".join(bundle.profile_ids) if bundle.profile_ids else "no grounded slice yet"
    headless_item = next((item for item in bundle.dod_items if item.key == "headless_export_check_bmw"), None)
    screenshot_item = next((item for item in bundle.dod_items if item.key == "screenshot_tests_bmws"), None)
    bmw_block = (
        "- BMW repo snapshot and helper scripts are packaged locally, and representative local headless export proof is attached\n"
        "- representative smoke evidence is attached, broader candidate outputs exist for most wider scenarios, low/high beam have proxy coverage, and the remaining exact local technical blocker is `lights_OnlyCones`\n"
        if (headless_item and headless_item.status != "blocked") or (screenshot_item and screenshot_item.status != "blocked")
        else "- BMW Git / digital-3d-car-models\n"
    )
    return (
        f"# Teams Update - {bundle.ticket_id}\n\n"
        "Message\n\n"
        f"I prepared a grounded local SG-side review bundle for `{bundle.ticket_id}` from the real SVN context on this machine.\n"
        f"Current scope packaged here: {profile_text}.\n"
        f"Scope note: {bundle.scope_note}\n\n"
        f"{finding_block}\n"
        "What is already covered locally:\n"
        "- car changelog/readme review prep from the live SVN checkout\n"
        "- shared BMW README/CHANGELOG review prep\n"
        "- screenshot baseline/test-config discovery and BMW screenshot-surface packaging\n"
        "- representative RaCo/Blender entrypoints\n"
        "- SG-side repo checker / format flow evidence\n"
        f"{manual_block}\n"
        "What is still blocked on my side:\n"
        "- BMW Jira access\n"
        f"{bmw_block}"
        "- real pass/fail signoff for visual deltas\n\n"
        "What I still need from Adrian / Hristofor / Stefan:\n"
        "- confirmation whether the attached representative local export proof is accepted as DoD evidence\n"
        "- where screenshot result/candidate images are generated when the actuals/diff folders are empty\n"
        "- how screenshot-test pass/fail is normally read\n"
        "- what exactly counts as asset review in RaCo done\n"
        "- whether `lights_OnlyCones` should be treated as a delivery blocker or a follow-up\n"
    )


def _stakeholder_sync_markdown(bundle: TicketReviewBundle) -> str:
    profile_text = ", ".join(bundle.profile_ids) if bundle.profile_ids else "no grounded slice yet"
    lines = [
        f"# Stakeholder Sync Brief - {bundle.ticket_id}",
        "",
        "## Message For Jana",
        "I still do not have Jira access, but I can work from the screenshots and the live SVN checkout for now.",
        f"I prepared a grounded local SG-side review package from `C:\\repositories\\trunk` for {profile_text}.",
        f"Scope note: {bundle.scope_note}",
        "The package includes car changelog/readme material, shared BMW docs, screenshot baselines/test config, representative RaCo/Blender entrypoints, and SG-side checker output.",
    ]
    if bundle.findings:
        finding = bundle.findings[0]
        source = finding.path
        if finding.line is not None and finding.path:
            source = f"{finding.path}:{finding.line}"
        lines.extend(
            [
                "",
                "Current concrete local SG-side finding:",
                f"- {source}",
                f"- {finding.summary}",
            ]
        )
    lines.extend(
        [
            "",
            "What is still blocked on my side:",
            "- BMW Jira access",
            "- broader screenshot coverage still has one reproducible exact local runtime/content blocker on `lights_OnlyCones`; `lights_LowBeam` and `lights_HighBeam` are proxy-covered",
            "- real screenshot pass/fail verdicts are still manual review work for the candidate/proxy outputs",
            "",
            f"The confirmed delivery scope packaged here is `{profile_text}`. I still need a short sync with Adrian / Hristofor / Stefan on how screenshot-test results are read in practice, whether the attached local export proof is accepted as DoD evidence, and whether `lights_OnlyCones` is a delivery blocker or a follow-up.",
            "",
            "## Questions For Adrian / Hristofor / Stefan",
        ]
    )
    for question in bundle.next_questions[1:6]:
        lines.append(f"- {question}")
    lines.extend(
        [
            "",
            "## Recommended reporting path while Jira is blocked",
            "- Send the short status message to Jana.",
            "- Keep the ZIP private unless Jana explicitly asks for the full package.",
            "- Use the DoD matrix and owner matrix as the source of truth for current status and blockers.",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _owner_matrix_markdown(bundle: TicketReviewBundle) -> str:
    lines = [
        f"# Owner Matrix - {bundle.ticket_id}",
        "",
        f"- Title: {bundle.title}",
        f"- Scope note: {bundle.scope_note or 'No explicit scope note was provided.'}",
        "",
        "| DoD item | Current state | Owner hint | Needs confirmation / next input |",
        "| --- | --- | --- | --- |",
    ]
    for item in bundle.dod_items:
        lines.append(f"| {item.label} | {item.status} | {item.owner_hint} | {item.blocked_next_input} |")
    return "\n".join(lines).rstrip() + "\n"


def _review_protocol_markdown(
    *,
    bundle: TicketReviewBundle,
    contexts: tuple[_ProfileContext, ...],
    workspace: Path,
    package_root: Path | None = None,
    manual_evidence_index_path: Path,
    manual_review_companion_path: Path,
    qa_capability_matrix_path: Path,
    three_d_qa_playbook_path: Path,
    repo_topology_reference_path: Path,
    delivery_surface_map_path: Path,
    raco_script_catalog_path: Path,
    delivery_target_catalog_path: Path,
) -> str:
    lines = [
        f"# Review Protocol - {bundle.ticket_id}",
        "",
        f"- Title: {bundle.title}",
        f"- Overall status: {bundle.overall_status}",
        f"- Scope note: {bundle.scope_note or 'No explicit scope note was provided.'}",
        "",
        "## Intent",
        "This ticket is treated as a delivery-week QA support and process-definition task.",
        "Use deterministic SG-side evidence first, keep manual review explicit, and keep BMW-owned steps marked as blocked until access or criteria are confirmed.",
        "",
        "## Verified reference surfaces",
    ]
    pdf_path = workspace / "GFX_Project_Overview_2026.pdf"
    if pdf_path.exists():
        lines.extend(
            [
                f"- Local project/process reference reviewed: `{pdf_path}` (reference only, not packaged).",
                "- Relevant process hints captured from that PDF: Jira documentation is mandatory, delivery documentation and performance-test results belong in Confluence, screenshot/manual review findings should be documented, and Blender-vs-RaCo comparison is expected before treating work as visually safe.",
            ]
        )
    lines.extend(
        [
            f"- {_QUALITY_HERO_PROCESS_REFERENCE}: local Confluence export/operator notes; live page access still requires login.",
        ]
    )
    for url in _BMW_DOC_URLS:
        lines.extend([f"- BMW reference page: `{url}`", "  - Reachable from this machine, but BMW Confluence login is still required."])
    lines.append(f"- Packaged manual-review index: `{_display_path(manual_review_companion_path, package_root)}`")
    lines.append(f"- Packaged QA capability matrix: `{_display_path(qa_capability_matrix_path, package_root)}`")
    lines.append(f"- Packaged 3D QA playbook: `{_display_path(three_d_qa_playbook_path, package_root)}`")
    lines.append(f"- Packaged repo topology reference: `{_display_path(repo_topology_reference_path, package_root)}`")
    lines.append(f"- Packaged delivery surface map: `{_display_path(delivery_surface_map_path, package_root)}`")
    lines.append(f"- Packaged RaCo script catalog: `{_display_path(raco_script_catalog_path, package_root)}`")
    lines.append(f"- Packaged delivery target catalog: `{_display_path(delivery_target_catalog_path, package_root)}`")

    lines.extend(
        [
            "",
            "## Workflow steps",
            "| DoD item | Current state | Owner hint | What to do now | Evidence expected |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    expected_evidence = {
        "headless_export_check_bmw": "Expected command/script, export log, success/failure trace, and delivery documentation entry once BMW access exists.",
        "screenshot_tests_bmws": "Expected baseline root, candidate/result root, deterministic triage JSON/HTML, optional diff artifacts, and a positive or negative test note.",
        "format_checker_svn": "Expected SG checker summary plus concrete path/line findings for anything surfaced on the live SVN slice.",
        "check_changelogs_cars_bmw": "Expected live car changelog, latest SVN log lines, and reviewer notes on intended changes.",
        "check_readme_cars_bmw": "Expected car README/constants docs plus reviewer notes on anything relevant to the delivery.",
        "asset_review_in_raco_bmws": "Expected representative `.rca` scene, Blender workfile, manual screenshot/note evidence, and Blender-vs-RaCo review notes.",
        "check_readme_changelogs_cars_shared_bmw": "Expected prioritized shared BMW README/CHANGELOG docs plus reviewer notes on affected modules.",
        "support": "Expected Teams/Jira-ready status note, blockers, findings, next questions, and ownership clarification.",
    }
    for item in bundle.dod_items:
        lines.append(
            f"| {item.label} | {item.status} | {item.owner_hint} | {item.what_can_be_done_now} | {expected_evidence.get(item.key, 'Expected evidence still needs clarification.')} |"
        )

    lines.extend(["", "## Possible test cases from current local slices"])
    for context in contexts:
        lines.extend(_possible_test_case_lines(context))

    lines.extend(
        [
            "## Manual Evidence Rollup",
            f"- Total attached evidence items: {len(bundle.manual_evidence)}",
            f"- Counts by kind: {_counts_by_kind_text(bundle.manual_evidence)}",
            f"- Packaged manual evidence index: `{_display_path(manual_evidence_index_path, package_root)}`",
            "",
            "## Attach Examples",
        ]
    )
    attach_blocks = _attach_examples(contexts, workspace)
    if attach_blocks:
        lines.extend(attach_blocks)
    else:
        lines.append("- No scene-check or qa-stack run is available yet for attach examples.")

    lines.extend(
        [
            "",
            "## Documentation expectations",
            "- Positive findings should still be documented, not only failures.",
            "- Manual visual review should capture Blender-vs-RaCo notes and at least one concrete evidence path or screenshot when something is questionable.",
            "- Use the packaged manual-review templates instead of starting free-form notes from scratch.",
            "- BMW-side delivery documentation and performance-test results remain external until access is granted.",
            "- The package outputs are intended to be copy-ready for Teams/Jira updates while direct Jira access is blocked.",
            "",
            "## Current blockers",
        ]
    )
    lines.extend(f"- {item}" for item in bundle.blockers)
    return "\n".join(lines).rstrip() + "\n"


def _manual_review_companion_markdown(ticket_id: str, contexts: tuple[_ProfileContext, ...]) -> str:
    return _build_manual_review_index(ticket_id, contexts)


def _review_owner_decisions_markdown(bundle: TicketReviewBundle) -> str:
    lines = [
        "# Review-owner decisions",
        "",
        f"- Ticket: `{bundle.ticket_id}`",
        f"- Scope: `{', '.join(bundle.profile_ids) if bundle.profile_ids else 'none confirmed'}`",
        "",
        "## lights_OnlyCones",
        "Decision: blocker / follow-up / accepted limitation / needs more investigation",
        "Owner:",
        "Date:",
        "Notes:",
        "",
        "## Screenshot candidate/proxy outputs",
        "Decision: accepted / needs changes / partial",
        "Owner:",
        "Date:",
        "Notes:",
        "",
        "## RaCo asset review",
        "Decision: passed / failed / not reviewed",
        "Owner:",
        "Date:",
        "Notes:",
        "",
        "## Jira writeback",
        "Status:",
        "Owner:",
        "",
        "## Additional review-owner notes",
        "",
        "- screenshot tests bmws:",
        "- check changelogs cars bmw:",
        "- check readme cars bmw:",
        "- check readme/changelogs cars shared bmw:",
        "",
    ]
    return "\n".join(lines)


def materialize_ticket_review_bundle(
    ticket_id: str,
    *,
    title: str = "",
    profile_ids: tuple[str, ...] = (),
    workspace: Path | None = None,
    output_root: Path | None = None,
    scope_note: str = "",
    candidate_roots: tuple[Path, ...] = (),
    include_action_bundles: bool = True,
) -> TicketReviewBundleResult:
    workspace_root = (workspace or Path(__file__).resolve().parents[1]).resolve()
    source_root = resolve_source_repo_root(workspace_root)
    desired_root = (output_root or default_ticket_review_output_root(ticket_id, workspace_root)).resolve()
    package_root = _fresh_output_root(desired_root)
    package_root.mkdir(parents=True, exist_ok=True)

    normalized_profiles = tuple(dict.fromkeys(item.strip() for item in profile_ids if item and item.strip()))

    effective_scope_note = (
        scope_note.strip()
        or (
            (
                "Current local evidence is grounded in the confirmed delivery scope "
                f"{', '.join(normalized_profiles)}."
            )
            if len(normalized_profiles) > 1
            else f"Current local evidence is grounded in {normalized_profiles[0]} as the first concrete live-SVN slice, not as confirmed final ticket scope."
            if normalized_profiles
            else "No car/slice is confirmed locally yet. This bundle is intentionally process-first and blocker-first until scope is confirmed."
        )
    )

    all_records = _all_action_records(workspace_root)
    contexts = tuple(
        _profile_context(
            ticket_id=ticket_id,
            profile_id=profile_id,
            workspace=workspace_root,
            package_root=package_root,
            candidate_roots=candidate_roots,
            source_root=source_root,
            all_records=all_records,
            include_action_bundles=include_action_bundles,
        )
        for profile_id in normalized_profiles
    )
    daily_snapshot = find_latest_daily_qa_snapshot(
        workspace_root,
        required_profiles=tuple(context.profile.profile_id for context in contexts),
    )
    if daily_snapshot is not None:
        daily_snapshot = _package_daily_snapshot_result(daily_snapshot, package_root)
    raco_probe = _find_latest_raco_manual_review_probe(
        workspace_root,
        required_profiles=tuple(context.profile.profile_id for context in contexts),
    )
    if raco_probe is not None:
        raco_probe = _package_raco_manual_review_probe(raco_probe, package_root)

    manual_evidence = _harvest_manual_evidence(contexts, package_root)
    manual_index_path = package_root / f"{ticket_id}-manual-evidence-index.md"
    manual_json_path = package_root / "artifacts" / "manual-evidence" / "index.json"
    qa_capability_matrix_path = package_root / f"{ticket_id}-qa-capability-matrix.md"
    three_d_qa_playbook_path = package_root / f"{ticket_id}-3d-qa-playbook.md"
    repo_topology_reference_path = package_root / f"{ticket_id}-repo-topology-reference.md"
    delivery_surface_map_path = package_root / f"{ticket_id}-delivery-surface-map.md"
    raco_script_catalog_path = package_root / f"{ticket_id}-raco-script-catalog.md"
    delivery_target_catalog_path = package_root / f"{ticket_id}-delivery-target-catalog.md"
    _write_text(
        manual_index_path,
        _manual_evidence_index_markdown(ticket_id=ticket_id, items=manual_evidence, package_root=package_root),
    )
    _write_json(manual_json_path, _manual_evidence_json_payload(ticket_id=ticket_id, items=manual_evidence))

    review_companion_path = package_root / f"{ticket_id}-manual-review-companion.md"
    _write_text(review_companion_path, _manual_review_companion_markdown(ticket_id, contexts))

    evidence_index: list[ReviewEvidence] = []
    for context in contexts:
        if not include_action_bundles:
            context.triage_bundle.html_path.unlink(missing_ok=True)
        evidence_index.extend(context.action_bundle_evidence)
        evidence_index.extend(context.packaged_source_evidence)
        evidence_index.extend(
            [
                _bundle_evidence(f"{context.profile.profile_id} screenshot triage", context.triage_bundle.markdown_path),
                _bundle_evidence(f"{context.profile.profile_id} screenshot triage JSON", context.triage_bundle.json_path),
                _bundle_evidence(f"{context.profile.profile_id} BMW screenshot surface", context.bmw_surface_markdown_path),
                _bundle_evidence(f"{context.profile.profile_id} BMW screenshot surface JSON", context.bmw_surface_json_path),
                _bundle_evidence(f"{context.profile.profile_id} manual review companion", context.manual_review_paths["companion"]),
                _bundle_evidence(f"{context.profile.profile_id} manual review record", context.manual_review_paths["record"]),
                _bundle_evidence(f"{context.profile.profile_id} screenshot evidence slots", context.manual_review_paths["slots"]),
                _bundle_evidence(f"{context.profile.profile_id} Blender vs RaCo checklist", context.manual_review_paths["blender_raco"]),
                _bundle_evidence(f"{context.profile.profile_id} visual review checklist", context.manual_review_paths["visual_checklist"]),
            ]
        )
    evidence_index.append(_bundle_evidence("Ticket manual review companion", review_companion_path))
    evidence_index.append(_bundle_evidence("Ticket manual evidence index", manual_index_path))
    evidence_index.append(_bundle_evidence("QA capability matrix", qa_capability_matrix_path))
    evidence_index.append(_bundle_evidence("3D QA playbook", three_d_qa_playbook_path))
    evidence_index.append(_bundle_evidence("Repo topology reference", repo_topology_reference_path))
    evidence_index.append(_bundle_evidence("Delivery surface map", delivery_surface_map_path))
    evidence_index.append(_bundle_evidence("RaCo script catalog", raco_script_catalog_path))
    evidence_index.append(_bundle_evidence("Delivery target catalog", delivery_target_catalog_path))
    if daily_snapshot is not None:
        evidence_index.append(_bundle_evidence("Daily QA snapshot", daily_snapshot.markdown_path))
        evidence_index.append(_bundle_evidence("Daily QA snapshot JSON", daily_snapshot.json_path))
        if daily_snapshot.battery_baseline_gaps_markdown_path is not None:
            evidence_index.append(_bundle_evidence("Battery baseline gaps", daily_snapshot.battery_baseline_gaps_markdown_path))
        if daily_snapshot.battery_baseline_gaps_json_path is not None:
            evidence_index.append(_bundle_evidence("Battery baseline gaps JSON", daily_snapshot.battery_baseline_gaps_json_path))
        if daily_snapshot.review_priority_markdown_path is not None:
            evidence_index.append(_bundle_evidence("Review priority ranking", daily_snapshot.review_priority_markdown_path))
        if daily_snapshot.review_priority_json_path is not None:
            evidence_index.append(_bundle_evidence("Review priority ranking JSON", daily_snapshot.review_priority_json_path))
        if daily_snapshot.delta_summary_markdown_path is not None:
            evidence_index.append(_bundle_evidence("Daily QA delta summary", daily_snapshot.delta_summary_markdown_path))
        if daily_snapshot.delta_summary_json_path is not None:
            evidence_index.append(_bundle_evidence("Daily QA delta summary JSON", daily_snapshot.delta_summary_json_path))
        if daily_snapshot.review_gallery_html_path is not None:
            evidence_index.append(_bundle_evidence("Candidate review gallery", daily_snapshot.review_gallery_html_path))
        scoped_profiles = {context.profile.profile_id.upper() for context in contexts}
        for item in daily_snapshot.snapshot.smoke_results:
            if item.profile_id.upper() in scoped_profiles and item.log_path:
                evidence_index.append(
                    _bundle_evidence(
                        f"{item.profile_id} BMW smoke log",
                        _resolve_snapshot_artifact_path(daily_snapshot, item.log_path),
                    )
                )
        seen_battery_log_paths: set[str] = set()
        for item in daily_snapshot.snapshot.battery_results:
            if item.profile_id.upper() not in scoped_profiles or not item.log_path:
                continue
            resolved_log_path = _resolve_snapshot_artifact_path(daily_snapshot, item.log_path)
            if resolved_log_path in seen_battery_log_paths or resolved_log_path == "not found":
                continue
            seen_battery_log_paths.add(resolved_log_path)
            evidence_index.append(_bundle_evidence(f"{item.profile_id} BMW battery log", resolved_log_path))
    if raco_probe is not None:
        evidence_index.append(_bundle_evidence("RaCo manual review probe", raco_probe.markdown_path))
        evidence_index.append(_bundle_evidence("RaCo manual review probe JSON", raco_probe.json_path))
    findings = tuple(finding for context in contexts for finding in _record_findings(context.repo_record))
    dod_items = _build_dod_items(
        contexts=contexts,
        workspace=workspace_root,
        scope_note=effective_scope_note,
        manual_evidence=manual_evidence,
        manual_evidence_index_path=manual_index_path,
        support_artifacts=(
            _bundle_evidence("QA capability matrix", qa_capability_matrix_path),
            _bundle_evidence("3D QA playbook", three_d_qa_playbook_path),
            _bundle_evidence("Repo topology reference", repo_topology_reference_path),
            _bundle_evidence("Delivery surface map", delivery_surface_map_path),
            _bundle_evidence("RaCo script catalog", raco_script_catalog_path),
            _bundle_evidence("Delivery target catalog", delivery_target_catalog_path),
        ),
        daily_snapshot=daily_snapshot,
        raco_probe=raco_probe,
        include_action_bundles=include_action_bundles,
    )
    bundle = TicketReviewBundle(
        ticket_id=ticket_id,
        title=title.strip() or ticket_id,
        generated_at_utc=_utc_now(),
        overall_status=_overall_status(dod_items),
        profile_ids=tuple(context.profile.profile_id for context in contexts),
        source_root=str(source_root),
        source_revision=_extract_revision(contexts[0].prep) if contexts else "",
        source_mode=contexts[0].prep.source_mode if contexts else "",
        scope_note=effective_scope_note,
        notes=_bundle_notes(effective_scope_note),
        blockers=_bundle_blockers(dod_items),
        next_questions=_bundle_questions(ticket_id, tuple(context.profile.profile_id for context in contexts)),
        findings=findings,
        evidence_index=_dedupe_evidence(evidence_index),
        dod_items=dod_items,
        manual_evidence=manual_evidence,
    )

    bundle_json_path = package_root / f"{ticket_id}-review-bundle.json"
    review_status_path = package_root / f"{ticket_id}-review-status.md"
    dod_matrix_path = package_root / f"{ticket_id}-dod-matrix.md"
    dod_update_draft_path = package_root / f"{ticket_id}-dod-update-draft.md"
    teams_update_path = package_root / f"{ticket_id}-teams-update.md"
    stakeholder_sync_path = package_root / f"{ticket_id}-stakeholder-sync.md"
    review_protocol_path = package_root / f"{ticket_id}-review-protocol.md"
    owner_matrix_path = package_root / f"{ticket_id}-owner-matrix.md"
    review_owner_decisions_path = package_root / "review-owner-decisions.md"
    sent_package_manifest_path = package_root / "SENT_PACKAGE_MANIFEST.md"

    _write_json(bundle_json_path, bundle.to_dict())
    _write_text(review_status_path, _review_status_markdown(bundle, package_root=package_root))
    _write_text(dod_matrix_path, _dod_matrix_markdown(bundle, package_root=package_root))
    _write_text(dod_update_draft_path, _dod_update_draft_markdown(bundle))
    _write_text(teams_update_path, _teams_update_markdown(bundle))
    _write_text(stakeholder_sync_path, _stakeholder_sync_markdown(bundle))
    _write_text(
        qa_capability_matrix_path,
        _qa_capability_matrix_markdown(
            ticket_id=ticket_id,
            source_root=source_root,
            workspace=workspace,
            scope_note=effective_scope_note,
            profile_ids=bundle.profile_ids,
        ),
    )
    _write_text(
        three_d_qa_playbook_path,
        _three_d_qa_playbook_markdown(
            ticket_id=ticket_id,
            source_root=source_root,
            bundle=bundle,
            contexts=contexts,
        ),
    )
    _write_text(
        repo_topology_reference_path,
        _repo_topology_reference_markdown(
            ticket_id=ticket_id,
            source_root=source_root,
            scope_note=effective_scope_note,
            profile_ids=bundle.profile_ids,
        ),
    )
    _write_text(
        delivery_surface_map_path,
        _delivery_surface_map_markdown(
            ticket_id=ticket_id,
            source_root=source_root,
            scope_note=effective_scope_note,
            workspace=workspace_root,
        ),
    )
    _write_text(
        raco_script_catalog_path,
        _raco_script_catalog_markdown(
            ticket_id=ticket_id,
            source_root=source_root,
            scope_note=effective_scope_note,
        ),
    )
    _write_text(
        delivery_target_catalog_path,
        _delivery_target_catalog_markdown(
            ticket_id=ticket_id,
            scope_note=effective_scope_note,
        ),
    )
    _write_text(
        review_protocol_path,
        _review_protocol_markdown(
            bundle=bundle,
            contexts=contexts,
            workspace=workspace_root,
            package_root=package_root,
            manual_evidence_index_path=manual_json_path,
            manual_review_companion_path=review_companion_path,
            qa_capability_matrix_path=qa_capability_matrix_path,
            three_d_qa_playbook_path=three_d_qa_playbook_path,
            repo_topology_reference_path=repo_topology_reference_path,
            delivery_surface_map_path=delivery_surface_map_path,
            raco_script_catalog_path=raco_script_catalog_path,
            delivery_target_catalog_path=delivery_target_catalog_path,
        ),
    )
    _write_text(owner_matrix_path, _owner_matrix_markdown(bundle))
    _write_text(review_owner_decisions_path, _review_owner_decisions_markdown(bundle))

    zip_path = _make_zip(package_root)
    zip_sha256_path = zip_path.with_suffix(zip_path.suffix + ".sha256")
    zip_sha256_path.write_text(f"{_sha256_file(zip_path)} *{zip_path.name}\n", encoding="utf-8")
    _write_text(
        sent_package_manifest_path,
        _sent_package_manifest_markdown(
            bundle=bundle,
            package_root=package_root,
            zip_path=zip_path,
            zip_sha256_path=zip_sha256_path,
            key_files=(
                dod_matrix_path,
                review_status_path,
                teams_update_path,
                stakeholder_sync_path,
                review_owner_decisions_path,
                manual_index_path,
            ),
        ),
    )
    zip_path = _make_zip(package_root)
    zip_sha256_path.write_text(f"{_sha256_file(zip_path)} *{zip_path.name}\n", encoding="utf-8")
    return TicketReviewBundleResult(
        bundle=bundle,
        package_root=package_root,
        bundle_json_path=bundle_json_path,
        review_status_path=review_status_path,
        dod_matrix_path=dod_matrix_path,
        dod_update_draft_path=dod_update_draft_path,
        teams_update_path=teams_update_path,
        stakeholder_sync_path=stakeholder_sync_path,
        review_protocol_path=review_protocol_path,
        owner_matrix_path=owner_matrix_path,
        qa_capability_matrix_path=qa_capability_matrix_path,
        three_d_qa_playbook_path=three_d_qa_playbook_path,
        repo_topology_reference_path=repo_topology_reference_path,
        delivery_surface_map_path=delivery_surface_map_path,
        raco_script_catalog_path=raco_script_catalog_path,
        delivery_target_catalog_path=delivery_target_catalog_path,
        manual_review_companion_path=review_companion_path,
        manual_evidence_index_path=manual_index_path,
        manual_evidence_json_path=manual_json_path,
        review_owner_decisions_path=review_owner_decisions_path,
        sent_package_manifest_path=sent_package_manifest_path,
        zip_sha256_path=zip_sha256_path,
        zip_path=zip_path,
    )
