from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile
from typing import Any, Iterable

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
)
from sg_preflight.io_utils import read_json, write_json, write_text as _write_text
from sg_preflight.qa_actions import ActionRecord, load_action_record, operator_ui_actions_root
from sg_preflight.services import prerequisite_status
from sg_preflight.ticket_dod import ReviewEvidence

@dataclass(frozen=True)
class RacoManualReviewProbeResult:
    output_root: Path
    markdown_path: Path
    json_path: Path
    profile_ids: tuple[str, ...]

@dataclass(frozen=True)
class TicketFinding:
    severity: str
    summary: str
    path: str = ""
    line: int | None = None
    checkers: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

@dataclass(frozen=True)
class TicketManualEvidenceItem:
    profile_id: str
    source_run_id: str
    source_action_id: str
    kind: str
    label: str
    original_path: str
    packaged_path: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def default_ticket_review_output_root(ticket_id: str, workspace: Path | None = None) -> Path:
    root = (workspace or Path(__file__).resolve().parents[1]).resolve()
    stamp = datetime.now().strftime("%Y-%m-%d")
    return root / "out" / f"{ticket_id}-review-package-{stamp}"

def _fresh_output_root(output_root: Path) -> Path:
    if not output_root.exists():
        return output_root
    stamp = datetime.now().strftime("%H%M%S")
    return output_root.with_name(f"{output_root.name}-rerun-{stamp}")

def _slug(value: str) -> str:
    lowered = re.sub(r"[^a-z0-9._-]+", "-", value.strip().lower())
    lowered = lowered.strip("-._")
    return lowered or "item"

def _write_json(path: Path, payload: dict[str, Any]) -> None:
    write_json(path, payload)

def _read_json(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    return payload if isinstance(payload, dict) else {}

def _safe_relative(path: Path, root: Path) -> Path | None:
    try:
        return path.resolve().relative_to(root.resolve())
    except ValueError:
        return None

def _copy_file(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return destination
    if source.resolve() != destination.resolve():
        shutil.copy2(source.resolve(), destination)
    return destination

def _copy_tree(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return destination
    shutil.copytree(source.resolve(), destination)
    return destination

def _dedupe_evidence(items: Iterable[ReviewEvidence]) -> tuple[ReviewEvidence, ...]:
    seen: set[tuple[str, str]] = set()
    ordered: list[ReviewEvidence] = []
    for item in items:
        key = (item.label.lower(), item.path.lower())
        if key in seen:
            continue
        seen.add(key)
        ordered.append(item)
    return tuple(ordered)

def _bundle_evidence(label: str, path: str | Path, detail: str = "") -> ReviewEvidence:
    normalized = str(path)
    if normalized in {"", ".", "not found"}:
        normalized = "not found"
    return ReviewEvidence(label=label, path=normalized, detail=detail)

def _display_path(path: str | Path, package_root: Path | None = None) -> str:
    normalized = str(path).strip()
    if normalized in {"", ".", "not found"}:
        return "not found"
    if package_root is not None:
        try:
            relative = _safe_relative(Path(normalized), package_root)
        except (OSError, ValueError):
            relative = None
        if relative is not None:
            return str(relative).replace("\\", "/")
    return normalized.replace("\\", "/")

def _all_action_records(workspace: Path) -> tuple[ActionRecord, ...]:
    actions_root = operator_ui_actions_root(workspace)
    if not actions_root.exists():
        return ()

    records: list[ActionRecord] = []
    for candidate in sorted(actions_root.iterdir(), reverse=True):
        record_path = candidate / "action.json"
        if not record_path.exists():
            continue
        try:
            records.append(load_action_record(record_path, workspace))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    records.sort(key=lambda item: item.created_at_utc, reverse=True)
    return tuple(records)

def _latest_record(records: tuple[ActionRecord, ...], action_id: str) -> ActionRecord | None:
    normalized = action_id.strip().lower()
    for record in records:
        if record.action_id.strip().lower() == normalized:
            return record
    return None

def _latest_manual_evidence_record(records: tuple[ActionRecord, ...], action_id: str) -> ActionRecord | None:
    normalized = action_id.strip().lower()
    for record in records:
        if record.action_id.strip().lower() != normalized:
            continue
        if record.manual_evidence:
            return record
    return None

def _unique_records(records: Iterable[ActionRecord | None]) -> tuple[ActionRecord, ...]:
    seen: set[str] = set()
    ordered: list[ActionRecord] = []
    for record in records:
        if record is None or record.run_id in seen:
            continue
        seen.add(record.run_id)
        ordered.append(record)
    return tuple(ordered)

def _action_ids_for_profile(profile_id: str) -> dict[str, str]:
    lowered = profile_id.strip().lower()
    return {
        "scene": f"scene_check__{lowered}",
        "stack": f"qa_stack__{lowered}",
        "repo": f"repo_checker_profile__{lowered}",
        "delivery": f"delivery_checklist__{lowered}",
    }

def _package_action_records(
    records: tuple[ActionRecord, ...],
    package_root: Path,
) -> tuple[ReviewEvidence, ...]:
    evidence: list[ReviewEvidence] = []
    for record in records:
        output_root = Path(record.paths.get("output_root", "")).resolve()
        if not output_root.exists():
            continue
        packaged_root = package_root / "artifacts" / "actions" / record.run_id
        try:
            _copy_tree(output_root, packaged_root)
        except OSError:
            continue
        evidence.append(_bundle_evidence(f"{record.label} bundle", packaged_root))
    return tuple(evidence)

def _package_live_source(
    path: str | Path,
    package_root: Path,
    source_root: Path,
) -> ReviewEvidence | None:
    source = Path(path).resolve()
    if not source.exists() or not source.is_file():
        return None
    relative = _safe_relative(source, source_root)
    if relative is None:
        destination = package_root / "source" / "external" / _slug(source.parent.name) / source.name
    else:
        destination = package_root / "source" / relative
    _copy_file(source, destination)
    return _bundle_evidence(source.name, destination)

def _package_live_sources(
    paths: Iterable[str],
    package_root: Path,
    source_root: Path,
) -> tuple[tuple[ReviewEvidence, ...], dict[str, ReviewEvidence]]:
    packaged: list[ReviewEvidence] = []
    packaged_index: dict[str, ReviewEvidence] = {}
    for item in paths:
        evidence = _package_live_source(item, package_root, source_root)
        if evidence is not None:
            packaged.append(evidence)
            try:
                packaged_index[str(Path(item).resolve())] = evidence
            except OSError:
                packaged_index[str(item)] = evidence
    return _dedupe_evidence(packaged), packaged_index

def _package_external_file(
    *,
    label: str,
    path: str | Path,
    package_root: Path,
    relative_dir: str | Path,
) -> ReviewEvidence | None:
    source = Path(path).resolve()
    if not source.exists() or not source.is_file():
        return None
    destination = package_root / relative_dir / source.name
    _copy_file(source, destination)
    return _bundle_evidence(label, destination)

def _packaged_source_evidence(
    context: _ProfileContext,
    source_path: str | Path,
    *,
    label: str | None = None,
    detail: str = "",
) -> ReviewEvidence:
    normalized = str(source_path).strip()
    if normalized in {"", ".", "not found"}:
        return _bundle_evidence(label or "not found", "not found", detail)
    try:
        key = str(Path(normalized).resolve())
    except OSError:
        key = normalized
    packaged = context.packaged_source_index.get(key)
    if packaged is not None:
        return ReviewEvidence(label=label or packaged.label, path=packaged.path, detail=detail or packaged.detail)
    return _bundle_evidence(label or Path(normalized).name, normalized, detail)

def _load_raco_manual_review_probe(output_root: Path) -> RacoManualReviewProbeResult | None:
    root = output_root.resolve()
    markdown_path = root / "raco-manual-review-probe.md"
    json_path = root / "raco-manual-review-probe.json"
    if not markdown_path.exists() or not json_path.exists():
        return None
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, list):
        return None
    profile_ids = tuple(
        dict.fromkeys(
            str(item.get("profile_id", "")).strip()
            for item in payload
            if isinstance(item, dict) and str(item.get("profile_id", "")).strip()
        )
    )
    return RacoManualReviewProbeResult(
        output_root=root,
        markdown_path=markdown_path,
        json_path=json_path,
        profile_ids=profile_ids,
    )

def _find_latest_raco_manual_review_probe(
    workspace: Path,
    *,
    required_profiles: tuple[str, ...] = (),
) -> RacoManualReviewProbeResult | None:
    out_root = workspace / "out"
    if not out_root.exists():
        return None

    normalized_required = {item.strip().upper() for item in required_profiles if item and item.strip()}
    candidates: list[RacoManualReviewProbeResult] = []
    for directory in out_root.glob("raco-manual-review-probe-*"):
        if not directory.is_dir():
            continue
        loaded = _load_raco_manual_review_probe(directory)
        if loaded is None:
            continue
        available_profiles = {item.upper() for item in loaded.profile_ids}
        if normalized_required and not normalized_required.issubset(available_profiles):
            continue
        candidates.append(loaded)

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (
            item.json_path.stat().st_mtime if item.json_path.exists() else 0,
            item.output_root.name,
        ),
        reverse=True,
    )
    return candidates[0]

def _package_daily_snapshot_result(
    result: DailyQaSnapshotResult,
    package_root: Path,
) -> DailyQaSnapshotResult:
    packaged_root = package_root / "artifacts" / "daily-snapshot"
    logs_root = packaged_root / "logs"
    images_root = packaged_root / "images"

    def _copy_log(log_path: str) -> str:
        normalized = str(log_path).strip()
        if not normalized:
            return normalized
        source = Path(normalized)
        if not source.exists() or not source.is_file():
            return normalized
        destination = logs_root / source.name
        _copy_file(source, destination)
        return str(Path("logs") / destination.name).replace("\\", "/")

    def _copy_named_files(source_root: Path, destination_root: Path, names: tuple[str, ...]) -> tuple[str, ...]:
        copied: list[str] = []
        for name in names:
            source = source_root / name
            if not source.exists() or not source.is_file():
                continue
            _copy_file(source, destination_root / name)
            copied.append(name)
        return tuple(copied)

    packaged_config = BmwConfigCheckResult(
        status=result.snapshot.config_check.status,
        python_exe=result.snapshot.config_check.python_exe,
        repo_root=result.snapshot.config_check.repo_root,
        log_path=_copy_log(result.snapshot.config_check.log_path),
        output_excerpt=result.snapshot.config_check.output_excerpt,
        error=result.snapshot.config_check.error,
    )

    packaged_smoke_results: list[BmwSmokeResult] = []
    for item in result.snapshot.smoke_results:
        packaged_smoke_results.append(
            BmwSmokeResult(
                profile_id=item.profile_id,
                bmw_profile_id=item.bmw_profile_id,
                status=item.status,
                smoke_test=item.smoke_test,
                python_exe=item.python_exe,
                sg_project_root=item.sg_project_root,
                bmw_test_config_path=item.bmw_test_config_path,
                log_path=_copy_log(item.log_path),
                exported_ramses_size=item.exported_ramses_size,
                exported_rlogic_size=item.exported_rlogic_size,
                expected_count=item.expected_count,
                actual_count=item.actual_count,
                diff_count=item.diff_count,
                compare_ok=item.compare_ok,
                error=item.error,
                notes=item.notes,
            )
        )

    packaged_battery_results: list[BmwBatteryResult] = []
    for item in result.snapshot.battery_results:
        scenario_root = images_root / item.profile_id.lower() / _slug(item.filter_name)
        actual_source_root = Path(item.results_root) / "tests" / "actuals"
        diff_source_root = Path(item.results_root) / "tests" / "diff"
        proxy_source_root = Path(item.results_root) / "tests" / "proxy_actuals"
        actual_files = _copy_named_files(actual_source_root, scenario_root / "tests" / "actuals", item.actual_files)
        diff_files = _copy_named_files(diff_source_root, scenario_root / "tests" / "diff", item.diff_files)
        proxy_files = _copy_named_files(proxy_source_root, scenario_root / "tests" / "proxy_actuals", item.proxy_files)
        packaged_battery_results.append(
            BmwBatteryResult(
                profile_id=item.profile_id,
                bmw_profile_id=item.bmw_profile_id,
                filter_name=item.filter_name,
                verdict=item.verdict,
                status=item.status,
                results_root=str(scenario_root),
                log_path=_copy_log(item.log_path),
                expected_count=item.expected_count,
                actual_count=item.actual_count,
                diff_count=item.diff_count,
                compare_ok=item.compare_ok,
                error=item.error,
                missing_expected_baseline=item.missing_expected_baseline,
                actual_files=actual_files,
                expected_files=item.expected_files,
                diff_files=diff_files,
                proxy_files=proxy_files,
                target_output_present=item.target_output_present,
                notes=item.notes,
            )
        )

    packaged_snapshot = DailyQaSnapshot(
        created_at=result.snapshot.created_at,
        scope_profiles=result.snapshot.scope_profiles,
        bmw_repo_root=result.snapshot.bmw_repo_root,
        config_check=packaged_config,
        smoke_results=tuple(packaged_smoke_results),
        battery_results=tuple(packaged_battery_results),
        diagnostics=result.snapshot.diagnostics,
        blocked_steps=result.snapshot.blocked_steps,
        top_review_items=result.snapshot.top_review_items,
        notes=result.snapshot.notes,
    )

    packaged_markdown = packaged_root / result.markdown_path.name
    packaged_json = packaged_root / result.json_path.name
    _write_text(packaged_markdown, _render_snapshot_markdown(packaged_snapshot))
    _write_json(packaged_json, packaged_snapshot.to_dict())

    packaged_gaps_markdown: Path | None = None
    packaged_gaps_json: Path | None = None
    packaged_review_gallery_html: Path | None = None
    packaged_review_priority_markdown: Path | None = None
    packaged_review_priority_json: Path | None = None
    packaged_delta_summary_markdown: Path | None = None
    packaged_delta_summary_json: Path | None = None
    if packaged_snapshot.battery_results:
        packaged_gaps_markdown = packaged_root / "battery-baseline-gaps.md"
        packaged_gaps_json = packaged_root / "battery-baseline-gaps.json"
        _write_text(packaged_gaps_markdown, _render_battery_baseline_gaps_markdown(packaged_snapshot))
        _write_json(packaged_gaps_json, _battery_baseline_gap_payload(packaged_snapshot))
        packaged_review_gallery_html = packaged_root / "candidate-review-gallery.html"
        _write_text(
            packaged_review_gallery_html,
            _render_candidate_review_gallery(packaged_snapshot, html_root=packaged_review_gallery_html),
        )
        if result.review_priority_markdown_path is not None:
            packaged_review_priority_markdown = packaged_root / "review-priority-ranking.md"
            _copy_file(result.review_priority_markdown_path, packaged_review_priority_markdown)
        if result.review_priority_json_path is not None:
            packaged_review_priority_json = packaged_root / "review-priority-ranking.json"
            _copy_file(result.review_priority_json_path, packaged_review_priority_json)
    if result.delta_summary_markdown_path is not None:
        packaged_delta_summary_markdown = packaged_root / "daily-qa-delta-summary.md"
        _copy_file(result.delta_summary_markdown_path, packaged_delta_summary_markdown)
    if result.delta_summary_json_path is not None:
        packaged_delta_summary_json = packaged_root / "daily-qa-delta-summary.json"
        _copy_file(result.delta_summary_json_path, packaged_delta_summary_json)

    return DailyQaSnapshotResult(
        output_root=packaged_root,
        snapshot=packaged_snapshot,
        markdown_path=packaged_markdown,
        json_path=packaged_json,
        battery_baseline_gaps_markdown_path=packaged_gaps_markdown,
        battery_baseline_gaps_json_path=packaged_gaps_json,
        review_gallery_html_path=packaged_review_gallery_html,
        review_priority_markdown_path=packaged_review_priority_markdown,
        review_priority_json_path=packaged_review_priority_json,
        delta_summary_markdown_path=packaged_delta_summary_markdown,
        delta_summary_json_path=packaged_delta_summary_json,
    )

def _package_raco_manual_review_probe(
    probe: RacoManualReviewProbeResult,
    package_root: Path,
) -> RacoManualReviewProbeResult:
    packaged_markdown = package_root / "artifacts" / "raco-probe" / probe.markdown_path.name
    packaged_json = package_root / "artifacts" / "raco-probe" / probe.json_path.name
    _copy_file(probe.markdown_path, packaged_markdown)
    _copy_file(probe.json_path, packaged_json)
    return RacoManualReviewProbeResult(
        output_root=packaged_markdown.parent,
        markdown_path=packaged_markdown,
        json_path=packaged_json,
        profile_ids=probe.profile_ids,
    )

def _resolve_snapshot_artifact_path(snapshot_result: DailyQaSnapshotResult | None, path: str | Path) -> str:
    normalized = str(path).strip()
    if normalized in {"", ".", "not found"}:
        return "not found"
    candidate = Path(normalized)
    if candidate.is_absolute() or snapshot_result is None:
        return str(candidate)
    return str((snapshot_result.output_root / candidate).resolve())

def _latest_native_verification_dir(workspace: Path) -> Path | None:
    verification_root = workspace / "build" / "native-installer-fullscreen" / "verification"
    if not verification_root.exists():
        return None
    candidates = [path for path in verification_root.iterdir() if path.is_dir()]
    if not candidates:
        return None
    candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return candidates[0]

def _package_verification_dir(workspace: Path, package_root: Path) -> ReviewEvidence | None:
    latest_verification = _latest_native_verification_dir(workspace)
    if latest_verification is None or not latest_verification.exists():
        return None
    destination = package_root / "artifacts" / "verification" / latest_verification.name
    _copy_tree(latest_verification, destination)
    return _bundle_evidence("Latest native verification", destination)

def _manual_review_template_paths(package_root: Path, profile_id: str) -> dict[str, Path]:
    base = package_root / "artifacts" / "manual-review" / profile_id.lower()
    return {
        "base": base,
        "companion": base / "manual-review-companion.md",
        "record": base / "manual-review-record.md",
        "slots": base / "screenshot-evidence-slots.md",
        "blender_raco": base / "blender-vs-raco-checklist.md",
        "visual_checklist": base / "visual-review-checklist.md",
    }

def _manual_review_texts(
    *,
    ticket_id: str,
    context: _ProfileContext,
) -> dict[str, str]:
    prep = context.prep
    report = context.triage_bundle.report
    triage_path = context.triage_bundle.markdown_path
    priority = ", ".join(prep.priority_screenshots[:8]) if prep.priority_screenshots else "none detected"
    profile_id = context.profile.profile_id
    common_header = [
        f"- Ticket: {ticket_id}",
        f"- Profile: {profile_id}",
        f"- Changelog heading: {prep.changelog_heading or 'not found'}",
        f"- Representative RaCo scene: `{prep.raco_scene_path or 'not found'}`",
        f"- Representative Blender workfile: `{prep.blender_workfile_path or 'not found'}`",
        f"- Screenshot baseline root: `{report.expected_root or prep.screenshot_root or 'not found'}`",
        f"- BMW actuals root: `{context.bmw_surface.actuals_root or 'not found'}`",
        f"- BMW diff root: `{context.bmw_surface.diff_root or 'not found'}`",
        f"- Screenshot triage: `{triage_path}`",
    ]
    return {
        "companion": "\n".join(
            [
                f"# Manual review companion - {profile_id}",
                "",
                *common_header,
                "",
                "Included templates:",
                f"- Manual review record: `{context.manual_review_paths['record']}`",
                f"- Screenshot evidence slots: `{context.manual_review_paths['slots']}`",
                f"- Blender vs RaCo checklist: `{context.manual_review_paths['blender_raco']}`",
                f"- Visual review checklist: `{context.manual_review_paths['visual_checklist']}`",
                "",
                "Use these templates to keep still-manual review explicit instead of pretending the deterministic run replaced it.",
                "",
            ]
        ),
        "record": "\n".join(
            [
                f"# Manual review record - {profile_id}",
                "",
                *[
                    line
                    for line in common_header[:-1]
                ],
                f"- Current screenshot triage: {report.pair_count} pair(s), {report.missing_candidate_count} missing candidate, {report.needs_review_count} needs review, {report.dimension_mismatch_count} dimension mismatch",
                "",
                "Manual checks:",
                "- Blender vs RaCo compared: [ ] yes [ ] no",
                "- Multi-angle review completed: [ ] yes [ ] no",
                "- Screenshot evidence attached: [ ] yes [ ] no",
                "- Rack / BMW smoke blocker documented: [ ] yes [ ] no",
                "- Changelog-reviewed intended changes confirmed: [ ] yes [ ] no",
                "",
                "Notes:",
                "-",
                "",
            ]
        ),
        "slots": "\n".join(
            [
                f"# Screenshot evidence slots - {profile_id}",
                "",
                f"- Ticket: {ticket_id}",
                f"- Profile: {profile_id}",
                f"- Baseline root: `{report.expected_root or prep.screenshot_root or 'not found'}`",
                f"- BMW actuals root: `{context.bmw_surface.actuals_root or 'not found'}`",
                f"- BMW diff root: `{context.bmw_surface.diff_root or 'not found'}`",
                f"- Triage report: `{triage_path}`",
                f"- Suggested baseline checks first: {priority}",
                "",
                "- Front 3/4:",
                "- Rear 3/4:",
                "- Side or wheel-area detail:",
                "- Interior or close-up if relevant:",
                "- Problem-focused proof shot:",
                "- Notes:",
                "-",
                "",
            ]
        ),
        "blender_raco": "\n".join(
            [
                f"# Blender vs RaCo checklist - {profile_id}",
                "",
                f"- Ticket: {ticket_id}",
                f"- Profile: {profile_id}",
                f"- RaCo scene: `{prep.raco_scene_path or 'not found'}`",
                f"- Blender workfile: `{prep.blender_workfile_path or 'not found'}`",
                "",
                "- Scene opens without missing-resource surprise: [ ]",
                "- Major camera/state alignment reviewed: [ ]",
                "- Material/light intent compared: [ ]",
                "- Geometry/asset presence compared: [ ]",
                "- Any mismatch documented with note or screenshot: [ ]",
                "",
                "Notes:",
                "-",
                "",
            ]
        ),
        "visual_checklist": "\n".join(
            [
                f"# Visual review checklist - {profile_id}",
                "",
                f"- Ticket: {ticket_id}",
                f"- Profile: {profile_id}",
                f"- Changelog heading: {prep.changelog_heading or 'not found'}",
                "",
                "- Changelog reviewed before interpreting screenshot drift: [ ]",
                "- Priority baselines reviewed first: [ ]",
                "- Shared BMW docs checked if relevant: [ ]",
                "- Blender/RaCo cross-check done: [ ]",
                "- Screenshot evidence attached where useful: [ ]",
                "- Blockers documented instead of guessed: [ ]",
                "",
                "Notes:",
                "-",
                "",
            ]
        ),
    }

def _materialize_manual_review_templates(
    *,
    ticket_id: str,
    context: _ProfileContext,
) -> dict[str, Path]:
    texts = _manual_review_texts(ticket_id=ticket_id, context=context)
    for key, text in texts.items():
        output_key = {
            "companion": "companion",
            "record": "record",
            "slots": "slots",
            "blender_raco": "blender_raco",
            "visual_checklist": "visual_checklist",
        }[key]
        _write_text(context.manual_review_paths[output_key], text)
    return context.manual_review_paths

def _extract_revision(prep: VisualReviewPrep) -> str:
    for line in prep.project_svn_info_lines:
        match = re.search(r"(?i)\brevision:\s*(\d+)", line)
        if match:
            return match.group(1)
        match = re.search(r"(?i)\blast changed rev:\s*(\d+)", line)
        if match:
            return match.group(1)
    return ""

def _record_findings(record: ActionRecord | None) -> tuple[TicketFinding, ...]:
    if record is None or not isinstance(record.summary, dict):
        return ()
    checker_evidence = record.summary.get("checker_evidence")
    if not isinstance(checker_evidence, dict):
        return ()
    top_paths = checker_evidence.get("top_paths", [])
    affected_files = checker_evidence.get("affected_files", [])

    findings: list[TicketFinding] = []
    seen: set[tuple[str, int | None, str]] = set()
    for item in top_paths if isinstance(top_paths, list) and top_paths else affected_files:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", ""))
        line = item.get("line") if isinstance(item.get("line"), int) else None
        summary = str(item.get("message", "")).strip()
        severity = str(item.get("severity", "info")).strip() or "info"
        checkers = tuple(str(value) for value in item.get("checkers", []) if value)
        if not checkers and item.get("checker"):
            checkers = (str(item["checker"]),)
        if not summary:
            continue
        key = (path.lower(), line, summary.lower())
        if key in seen:
            continue
        seen.add(key)
        findings.append(
            TicketFinding(
                severity=severity,
                summary=summary if line is None else f"{summary} ({Path(path).name}:{line})",
                path=path,
                line=line,
                checkers=checkers,
            )
        )
    return tuple(findings)

def _manual_followups(record: ActionRecord | None) -> tuple[str, ...]:
    if record is None or not isinstance(record.summary, dict):
        return ()
    checker_evidence = record.summary.get("checker_evidence")
    if not isinstance(checker_evidence, dict):
        return ()
    raw = checker_evidence.get("manual_followups", [])
    return tuple(str(item) for item in raw if item)

def _manual_evidence_key(raw: dict[str, str]) -> tuple[str, str, str]:
    path_text = str(raw.get("path", "")).strip()
    normalized_path = path_text
    if path_text:
        try:
            normalized_path = str(Path(path_text).resolve())
        except OSError:
            normalized_path = path_text
    else:
        normalized_path = f"note::{str(raw.get('note', '')).strip()}"
    return (
        normalized_path.lower(),
        str(raw.get("kind", "")).strip().lower(),
        str(raw.get("label", "")).strip().lower(),
    )

def _copy_manual_evidence_item(
    *,
    package_root: Path,
    profile_id: str,
    record: ActionRecord,
    raw: dict[str, str],
) -> TicketManualEvidenceItem | None:
    kind = str(raw.get("kind", "")).strip() or "manual_evidence"
    label = str(raw.get("label", "")).strip() or kind
    note = str(raw.get("note", "")).strip()
    original_path = str(raw.get("path", "")).strip()
    package_dir = package_root / "artifacts" / "manual-evidence" / profile_id.lower() / record.run_id
    package_dir.mkdir(parents=True, exist_ok=True)

    packaged_path: Path
    if original_path:
        source = Path(original_path)
        if source.exists():
            packaged_path = package_dir / source.name
            if len(str(packaged_path)) >= 240:
                suffix = source.suffix or ".bin"
                evidence_id = str(raw.get("id", "")).strip()[:8]
                packaged_path = package_dir / f"{_slug(kind)}-{evidence_id or 'evidence'}{suffix}"
            _copy_file(source, packaged_path)
        else:
            packaged_path = package_dir / f"{_slug(kind)}-{_slug(label)}.md"
            _write_text(packaged_path, (note or f"Missing original path: {original_path}") + "\n")
    else:
        packaged_path = package_dir / f"{_slug(kind)}-{_slug(label)}.md"
        if len(str(packaged_path)) >= 240:
            evidence_id = str(raw.get("id", "")).strip()[:8]
            packaged_path = package_dir / f"{_slug(kind)}-{evidence_id or 'note'}.md"
        _write_text(packaged_path, (note or label) + "\n")

    return TicketManualEvidenceItem(
        profile_id=profile_id,
        source_run_id=record.run_id,
        source_action_id=record.action_id,
        kind=kind,
        label=label,
        original_path=original_path,
        packaged_path=str(packaged_path),
        note=note,
    )

def _harvest_manual_evidence(
    contexts: tuple[_ProfileContext, ...],
    package_root: Path,
) -> tuple[TicketManualEvidenceItem, ...]:
    harvested: list[TicketManualEvidenceItem] = []
    seen: set[tuple[str, str, str]] = set()
    for context in contexts:
        for record in context.manual_evidence_records:
            for raw in record.manual_evidence:
                if not isinstance(raw, dict):
                    continue
                key = _manual_evidence_key(raw)
                if key in seen:
                    continue
                seen.add(key)
                item = _copy_manual_evidence_item(
                    package_root=package_root,
                    profile_id=context.profile.profile_id,
                    record=record,
                    raw=raw,
                )
                if item is not None:
                    harvested.append(item)
    return tuple(harvested)

def _manual_evidence_counts(items: tuple[TicketManualEvidenceItem, ...]) -> Counter[str]:
    return Counter(item.kind for item in items)

def _counts_by_kind_text(items: tuple[TicketManualEvidenceItem, ...]) -> str:
    counts = _manual_evidence_counts(items)
    if not counts:
        return "none"
    return ", ".join(f"{key}={counts[key]}" for key in sorted(counts))

def _manual_evidence_index_markdown(
    *,
    ticket_id: str,
    items: tuple[TicketManualEvidenceItem, ...],
    package_root: Path | None = None,
) -> str:
    lines = [
        f"# Ticket Manual Evidence Index - {ticket_id}",
        "",
        f"- Total attached evidence items: {len(items)}",
        f"- Counts by kind: {_counts_by_kind_text(items)}",
        "",
    ]
    if not items:
        lines.append("- No manual evidence was harvested from the relevant action bundles.")
        lines.append("")
        return "\n".join(lines)

    lines.append("## Items")
    for item in items:
        lines.extend(
            [
                f"- [{item.kind}] {item.label}",
                f"  - Profile: {item.profile_id}",
                f"  - Source action: {item.source_action_id}",
                f"  - Source run: {item.source_run_id}",
                f"  - Original path: `{item.original_path or 'n/a'}`",
                f"  - Packaged path: `{_display_path(item.packaged_path, package_root)}`",
            ]
        )
        if item.note:
            lines.append(f"  - Note: {item.note}")
    lines.append("")
    return "\n".join(lines)

def _manual_evidence_json_payload(
    *,
    ticket_id: str,
    items: tuple[TicketManualEvidenceItem, ...],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "ticket_id": ticket_id,
        "generated_at_utc": _utc_now(),
        "counts_by_kind": dict(_manual_evidence_counts(items)),
        "items": [item.to_dict() for item in items],
    }

def _current_support_blockers(workspace: Path) -> tuple[str, ...]:
    readiness = {item["key"]: item for item in prerequisite_status(workspace)}
    blockers: list[str] = []
    bmw_models = readiness.get("bmw_models_repo", {})
    bmw_car_manager = readiness.get("bmw_car_manager_script", {})
    bmw_test_main = readiness.get("bmw_test_main_script", {})
    bmw_readme = readiness.get("bmw_screenshot_scripts", {})
    if bmw_models.get("status") != "available":
        blockers.append(f"{bmw_models.get('label', 'bmw_models_repo')} missing locally. Path: {bmw_models.get('path', '')}")
    if (
        bmw_car_manager.get("status") != "available"
        and bmw_test_main.get("status") != "available"
    ):
        blockers.append(
            "BMW screenshot/headless helpers are missing locally. "
            f"car_manager path: {bmw_car_manager.get('path', '')}"
        )
    if bmw_readme.get("status") != "available":
        blockers.append(
            f"{bmw_readme.get('label', 'BMW screenshot scripts README')} missing locally. "
            f"Path: {bmw_readme.get('path', '')}"
        )
    return tuple(blockers)

def _is_stale_followup(
    followup: str,
    readiness: dict[str, dict[str, str]],
) -> bool:
    text = followup.lower()
    if "bmw delivery repo is missing locally" in text:
        return readiness.get("bmw_models_repo", {}).get("status") == "available"
    if "car_manager.py" in text:
        return readiness.get("bmw_car_manager_script", {}).get("status") == "available"
    if "test/main.py" in text:
        return (
            readiness.get("bmw_car_manager_script", {}).get("status") == "available"
            or readiness.get("bmw_test_main_script", {}).get("status") == "available"
        )
    if "ci/scripts/readme" in text or "screenshot scripts" in text:
        return readiness.get("bmw_screenshot_scripts", {}).get("status") == "available"
    return False

def _support_blockers(workspace: Path, delivery_record: ActionRecord | None) -> tuple[str, ...]:
    readiness = {item["key"]: item for item in prerequisite_status(workspace)}
    blockers = list(_current_support_blockers(workspace))
    for followup in _manual_followups(delivery_record):
        if _is_stale_followup(followup, readiness):
            continue
        if followup not in blockers:
            blockers.append(followup)
    return tuple(blockers)

def _make_zip(package_root: Path) -> Path:
    zip_path = package_root.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        for path in sorted(package_root.rglob("*")):
            if path.is_dir():
                continue
            handle.write(path, path.relative_to(package_root))
    return zip_path

def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def _dod_completion_percent(bundle: TicketReviewBundle) -> int:
    status_points = {
        "blocked": 0,
        "needs_scope": 25,
        "partial": 50,
        "manual_ready": 60,
        "prepared": 75,
        "covered_with_findings": 100,
        "covered": 100,
    }
    if not bundle.dod_items:
        return 0
    total = sum(status_points.get(item.status, 0) for item in bundle.dod_items)
    return round(total / len(bundle.dod_items))

def _sent_package_manifest_markdown(
    *,
    bundle: TicketReviewBundle,
    package_root: Path,
    zip_path: Path,
    zip_sha256_path: Path,
    key_files: tuple[Path, ...],
) -> str:
    lines = [
        "# SENT PACKAGE MANIFEST",
        "",
        f"- Ticket ID: `{bundle.ticket_id}`",
        f"- Title: {bundle.title}",
        f"- Scope: `{', '.join(bundle.profile_ids) if bundle.profile_ids else 'none confirmed'}`",
        f"- Generated at UTC: `{bundle.generated_at_utc}`",
        f"- Overall status: `{bundle.overall_status}`",
        f"- Visible DoD progress (conservative): `{_dod_completion_percent(bundle)}%`",
        f"- Package folder: `{package_root.name}`",
        f"- ZIP name: `{zip_path.name}`",
        f"- ZIP size bytes: `{zip_path.stat().st_size}`",
        f"- ZIP SHA256 sidecar: `{zip_sha256_path.name}`",
        "- ZIP SHA256 is recorded in the sidecar file to avoid self-referential checksum drift inside the archive.",
        "",
        "## Important included files",
    ]
    for path in key_files:
        lines.append(f"- `{_display_path(path, package_root)}`")
    lines.extend(["", "## Known open blockers"])
    if bundle.blockers:
        lines.extend(f"- {item}" for item in bundle.blockers)
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Distribution record",
            "- Sent status: not recorded automatically",
            "- Sent to:",
            "- Sent on:",
            "- Notes:",
            "",
        ]
    )
    return "\n".join(lines)
