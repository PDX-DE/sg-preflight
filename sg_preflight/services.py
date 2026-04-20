from __future__ import annotations

import importlib.util
import json
import os
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sg_preflight.adapters.materialize import (
    MaterializeInputs,
    MaterializeResult,
    materialize_bundle,
    resolve_materialize_inputs,
)
from sg_preflight.bundle import load_bundle
from sg_preflight.checker_catalog import list_checker_catalog
from sg_preflight.config_loader import load_config, load_json
from sg_preflight.models import Report
from sg_preflight.profiles import RunProfile, list_run_profiles
from sg_preflight.reporting import write_html_report, write_json_report, write_markdown_report
from sg_preflight.utils import ensure_parent
from sg_preflight.validators.anchors import validate_anchors
from sg_preflight.validators.carpaints import validate_carpaints
from sg_preflight.validators.constants import validate_constants
from sg_preflight.validators.project_sanity import validate_project_sanity


VALID_PACKS = ("anchors", "constants", "carpaints", "project_sanity")
RUN_PROGRESS_PLAN = (
    ("queued", "Queued"),
    ("preview", "Resolve source inputs"),
    ("scene_hierarchy", "Read anchor scene"),
    ("constants_expected", "Read expected constants"),
    ("constants_exported", "Read exported constants"),
    ("carpaints", "Read carpaint catalog"),
    ("manifest_raco", "Detect RaCo version"),
    ("manifest_paths", "Scan path references"),
    ("manifest_lua", "Inspect Lua references"),
    ("validate_anchors", "Validate anchors"),
    ("validate_constants", "Validate constants"),
    ("validate_carpaints", "Validate carpaints"),
    ("validate_project_sanity", "Validate project sanity"),
    ("write_reports", "Write reports"),
    ("finalize", "Finalize run record"),
)


def workspace_root(explicit_root: Path | None = None) -> Path:
    return (explicit_root or Path(__file__).resolve().parents[1]).resolve()


def operator_ui_root(explicit_root: Path | None = None) -> Path:
    return workspace_root(explicit_root) / "out" / "operator-ui"


def operator_ui_runs_root(explicit_root: Path | None = None) -> Path:
    return operator_ui_root(explicit_root) / "runs"


def operator_ui_cache_root(explicit_root: Path | None = None) -> Path:
    return operator_ui_root(explicit_root) / "cache"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json_file(path: Path, payload: Any) -> None:
    ensure_parent(path)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def parse_packs(raw: str | list[str]) -> list[str]:
    if isinstance(raw, list):
        items = [str(item).strip().lower() for item in raw if str(item).strip()]
    else:
        value = raw.strip().lower()
        if value == "all":
            return list(VALID_PACKS)
        items = [part.strip() for part in value.split(",") if part.strip()]

    invalid = [pack for pack in items if pack not in VALID_PACKS]
    if invalid:
        raise ValueError(f"Unsupported packs: {', '.join(invalid)}")
    return items or list(VALID_PACKS)


def parse_name_value_pairs(values: list[str]) -> dict[str, str]:
    payload: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise ValueError(f"Invalid NAME=VALUE entry {item!r}")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"Invalid NAME=VALUE entry {item!r}; key cannot be empty")
        payload[key] = value
    return payload


def build_report_context(bundle: Any) -> dict[str, Any]:
    manifest = getattr(bundle, "project_manifest", None)
    context: dict[str, Any] = {}
    if isinstance(manifest, dict):
        raw_context = manifest.get("report_context", {})
        if isinstance(raw_context, dict):
            context.update(raw_context)
        project_root = manifest.get("project_root")
        if project_root:
            context.setdefault("project_root", str(project_root))
        repo_root = manifest.get("repo_root")
        if repo_root:
            context.setdefault("repo_root", str(repo_root))
    return context


@dataclass
class MaterializePreview:
    source_paths: dict[str, str]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_paths": dict(self.source_paths),
            "notes": list(self.notes),
        }


@dataclass
class BundleRunResult:
    report: Report
    exit_code: int
    json_out: Path | None = None
    html_out: Path | None = None
    markdown_out: Path | None = None


@dataclass
class RunRequest:
    profile_id: str
    packs: list[str] = field(default_factory=lambda: list(VALID_PACKS))
    fail_on: str = "never"
    context_overrides: dict[str, str] = field(default_factory=dict)
    output_root: Path | None = None
    run_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "packs": list(self.packs),
            "fail_on": self.fail_on,
            "context_overrides": dict(self.context_overrides),
            "output_root": str(self.output_root) if self.output_root else "",
            "run_id": self.run_id or "",
        }


@dataclass
class RunRecord:
    run_id: str
    profile_id: str
    profile_label: str
    status: str
    created_at_utc: str
    started_at_utc: str | None
    completed_at_utc: str | None
    fail_on: str
    packs: list[str]
    context: dict[str, str]
    repo_root: str
    project_root: str
    config_path: str
    reference_repo_root: str
    paths: dict[str, str]
    source_paths: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    summary: dict[str, int] | None = None
    exit_code: int | None = None
    error_message: str = ""
    progress: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "run_id": self.run_id,
            "profile_id": self.profile_id,
            "profile_label": self.profile_label,
            "status": self.status,
            "created_at_utc": self.created_at_utc,
            "started_at_utc": self.started_at_utc,
            "completed_at_utc": self.completed_at_utc,
            "fail_on": self.fail_on,
            "packs": list(self.packs),
            "context": dict(self.context),
            "repo_root": self.repo_root,
            "project_root": self.project_root,
            "config_path": self.config_path,
            "reference_repo_root": self.reference_repo_root,
            "paths": dict(self.paths),
            "source_paths": dict(self.source_paths),
            "notes": list(self.notes),
            "summary": dict(self.summary) if isinstance(self.summary, dict) else None,
            "exit_code": self.exit_code,
            "error_message": self.error_message,
            "progress": dict(self.progress) if isinstance(self.progress, dict) else None,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RunRecord":
        return cls(
            run_id=str(payload.get("run_id", "")),
            profile_id=str(payload.get("profile_id", "")),
            profile_label=str(payload.get("profile_label", "")),
            status=str(payload.get("status", "")),
            created_at_utc=str(payload.get("created_at_utc", "")),
            started_at_utc=payload.get("started_at_utc"),
            completed_at_utc=payload.get("completed_at_utc"),
            fail_on=str(payload.get("fail_on", "never")),
            packs=[str(item) for item in payload.get("packs", []) if item],
            context=dict(payload.get("context", {}))
            if isinstance(payload.get("context"), dict)
            else {},
            repo_root=str(payload.get("repo_root", "")),
            project_root=str(payload.get("project_root", "")),
            config_path=str(payload.get("config_path", "")),
            reference_repo_root=str(payload.get("reference_repo_root", "")),
            paths=dict(payload.get("paths", {}))
            if isinstance(payload.get("paths"), dict)
            else {},
            source_paths=dict(payload.get("source_paths", {}))
            if isinstance(payload.get("source_paths"), dict)
            else {},
            notes=[str(item) for item in payload.get("notes", []) if item],
            summary=dict(payload.get("summary", {}))
            if isinstance(payload.get("summary"), dict)
            else None,
            exit_code=payload.get("exit_code"),
            error_message=str(payload.get("error_message", "")),
            progress=dict(payload.get("progress", {}))
            if isinstance(payload.get("progress"), dict)
            else None,
        )


def preview_profile_sources(profile: RunProfile) -> MaterializePreview:
    inputs = resolve_materialize_inputs(
        repo_root=profile.repo_root,
        project_root=profile.project_root,
    )
    return MaterializePreview(source_paths=inputs.source_map(), notes=inputs.notes)


def execute_bundle_run(
    *,
    bundle_dir: Path,
    config_path: Path,
    packs: list[str],
    fail_on: str,
    json_out: Path | None = None,
    html_out: Path | None = None,
    markdown_out: Path | None = None,
    progress_callback: Any | None = None,
) -> BundleRunResult:
    config = load_config(config_path)
    bundle = load_bundle(bundle_dir)

    report = Report(bundle=str(bundle_dir.resolve()), context=build_report_context(bundle))
    pack_map = {
        "anchors": validate_anchors,
        "constants": validate_constants,
        "carpaints": validate_carpaints,
        "project_sanity": validate_project_sanity,
    }
    pack_progress = {
        "anchors": ("validate_anchors", 74, "Validating anchors"),
        "constants": ("validate_constants", 79, "Validating constants"),
        "carpaints": ("validate_carpaints", 84, "Validating carpaint catalog"),
        "project_sanity": ("validate_project_sanity", 89, "Validating project sanity"),
    }

    for pack in packs:
        if progress_callback is not None:
            step_key, percent, label = pack_progress.get(pack, ("write_reports", 90, f"Validating {pack}"))
            progress_callback(
                step_key,
                percent,
                label,
                f"Running the `{pack}` validator against the materialized SG bundle.",
            )
        report.packs.append(pack_map[pack](bundle, config))

    if progress_callback is not None:
        progress_callback(
            "write_reports",
            94,
            "Writing reports",
            "Persisting JSON, HTML, and Markdown outputs for the current run.",
        )
    if json_out:
        write_json_report(report, json_out)
    if html_out:
        write_html_report(report, html_out, config)
    if markdown_out:
        write_markdown_report(report, markdown_out, config)

    exit_code = 2 if report.has_threshold_or_worse(fail_on) else 0
    return BundleRunResult(
        report=report,
        exit_code=exit_code,
        json_out=json_out,
        html_out=html_out,
        markdown_out=markdown_out,
    )


def _default_run_id(profile_id: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{profile_id.lower()}-{uuid.uuid4().hex[:8]}"


def _resolved_context(profile: RunProfile, request: RunRequest) -> dict[str, str]:
    context = dict(profile.default_context)
    context.update(request.context_overrides)
    return context


def _run_output_root(
    profile: RunProfile,
    request: RunRequest,
    repo_root: Path | None = None,
) -> tuple[str, Path]:
    if request.output_root is not None:
        run_id = request.run_id or request.output_root.resolve().name
        return run_id, request.output_root.resolve()

    run_id = request.run_id or _default_run_id(profile.profile_id)
    root = operator_ui_runs_root(repo_root) / run_id
    return run_id, root.resolve()


def build_run_record(
    profile: RunProfile,
    request: RunRequest,
    repo_root: Path | None = None,
) -> RunRecord:
    run_id, output_root = _run_output_root(profile, request, repo_root)
    slug = profile.profile_id.lower()
    return RunRecord(
        run_id=run_id,
        profile_id=profile.profile_id,
        profile_label=profile.label,
        status="queued",
        created_at_utc=utc_now(),
        started_at_utc=None,
        completed_at_utc=None,
        fail_on=request.fail_on,
        packs=list(request.packs),
        context=_resolved_context(profile, request),
        repo_root=str(profile.repo_root),
        project_root=str(profile.project_root),
        config_path=str(profile.config_path),
        reference_repo_root=str(profile.reference_repo_root),
        paths={
            "output_root": str(output_root),
            "bundle": str(output_root / "bundle"),
            "json_report": str(output_root / f"{slug}-report.json"),
            "html_report": str(output_root / f"{slug}-report.html"),
            "markdown_report": str(output_root / f"{slug}-report.md"),
            "run_record": str(output_root / "run.json"),
            "bundle_metadata": str(output_root / "bundle" / "bundle_metadata.json"),
            "project_manifest": str(output_root / "bundle" / "project_manifest.json"),
        },
    )


def save_run_record(record: RunRecord) -> None:
    write_json_file(Path(record.paths["run_record"]), record.to_dict())


def build_progress_payload(
    plan: tuple[tuple[str, str], ...],
    *,
    step_key: str,
    percent: int,
    label: str,
    detail: str = "",
    events: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    percent = max(0, min(int(percent), 100))
    active_seen = False
    step_found = False
    steps: list[dict[str, str]] = []
    for key, step_label in plan:
        if percent >= 100:
            state = "done"
        elif key == step_key:
            state = "active"
            active_seen = True
            step_found = True
        elif active_seen:
            state = "pending"
        else:
            state = "done"
        steps.append({"key": key, "label": step_label, "state": state})

    if not step_found and steps and percent < 100:
        steps[0]["state"] = "active"
        for item in steps[1:]:
            item["state"] = "pending"

    event_items = [dict(item) for item in events] if events else []
    step_details: list[dict[str, Any]] = []
    for step in steps:
        matching_events = [
            dict(item)
            for item in event_items
            if str(item.get("step_key", "")).strip() == step["key"]
        ]
        latest_event = matching_events[-1] if matching_events else {}
        step_details.append(
            {
                "key": step["key"],
                "label": step["label"],
                "state": step["state"],
                "detail": detail if step["key"] == step_key else str(latest_event.get("detail", "")).strip(),
                "last_label": str(latest_event.get("label", "")).strip(),
                "last_timestamp_utc": str(latest_event.get("timestamp_utc", "")).strip(),
                "events": matching_events[-8:],
                "meta": dict(latest_event.get("meta", {}))
                if isinstance(latest_event.get("meta"), dict)
                else {},
            }
        )

    return {
        "percent": percent,
        "step_key": step_key,
        "label": label,
        "detail": detail,
        "steps": steps,
        "events": event_items,
        "step_details": step_details,
    }


def _progress_event(
    step_key: str,
    label: str,
    detail: str = "",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "timestamp_utc": utc_now(),
        "step_key": step_key,
        "label": label,
        "detail": detail,
    }
    if meta:
        payload["meta"] = dict(meta)
    return payload


def _merged_progress_events(
    existing: dict[str, Any] | None,
    *,
    step_key: str,
    label: str,
    detail: str = "",
    meta: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    raw_events = existing.get("events", []) if isinstance(existing, dict) else []
    events = [dict(item) for item in raw_events if isinstance(item, dict)]
    if (
        not events
        or events[-1].get("step_key") != step_key
        or events[-1].get("label") != label
        or events[-1].get("detail") != detail
        or (
            isinstance(meta, dict)
            and dict(events[-1].get("meta", {})) != dict(meta)
        )
    ):
        events.append(_progress_event(step_key, label, detail, meta))
    return events[-40:]


def _set_run_progress(
    record: RunRecord,
    *,
    step_key: str,
    percent: int,
    label: str,
    detail: str = "",
    meta: dict[str, Any] | None = None,
) -> None:
    events = _merged_progress_events(
        record.progress,
        step_key=step_key,
        label=label,
        detail=detail,
        meta=meta,
    )
    record.progress = build_progress_payload(
        RUN_PROGRESS_PLAN,
        step_key=step_key,
        percent=percent,
        label=label,
        detail=detail,
        events=events,
    )
    save_run_record(record)


def load_run_record(path_or_run_id: str | Path, repo_root: Path | None = None) -> RunRecord:
    candidate = Path(path_or_run_id)
    if candidate.exists():
        record_path = candidate if candidate.is_file() else candidate / "run.json"
    else:
        record_path = operator_ui_runs_root(repo_root) / str(path_or_run_id) / "run.json"
    payload = load_json(record_path)
    if not isinstance(payload, dict):
        raise ValueError(f"Run record must contain a JSON object: {record_path}")
    return RunRecord.from_dict(payload)


def list_recent_run_records(repo_root: Path | None = None, limit: int = 12) -> list[RunRecord]:
    records: list[RunRecord] = []
    runs_root = operator_ui_runs_root(repo_root)
    if not runs_root.exists():
        return records

    for path in runs_root.iterdir():
        record_path = path / "run.json"
        if not record_path.exists():
            continue
        try:
            records.append(load_run_record(record_path))
        except (OSError, ValueError, json.JSONDecodeError):
            continue

    records.sort(key=lambda item: item.created_at_utc, reverse=True)
    return records[:limit]


def load_run_report(record: RunRecord) -> Report | None:
    report_path = Path(record.paths.get("json_report", ""))
    if not report_path.exists():
        return None
    payload = load_json(report_path)
    if not isinstance(payload, dict):
        return None
    return Report.from_dict(payload)


def load_run_config(record: RunRecord) -> dict[str, Any]:
    return load_config(Path(record.config_path))


def load_run_bundle_metadata(record: RunRecord) -> dict[str, Any]:
    bundle_metadata_path = Path(record.paths.get("bundle_metadata", ""))
    if not bundle_metadata_path.exists():
        return {}
    payload = load_json(bundle_metadata_path)
    return payload if isinstance(payload, dict) else {}


def _record_source_paths(preview: MaterializePreview, record: RunRecord) -> dict[str, str]:
    source_paths = dict(preview.source_paths)
    bundle_metadata = load_run_bundle_metadata(record)
    sources = bundle_metadata.get("sources", {})
    if isinstance(sources, dict):
        for key, value in sources.items():
            if value:
                source_paths[str(key)] = str(value)
    return source_paths


def execute_profile_run(profile: RunProfile, request: RunRequest, repo_root: Path | None = None) -> RunRecord:
    record = build_run_record(profile, request, repo_root)
    _set_run_progress(
        record,
        step_key="queued",
        percent=0,
        label="Queued locally",
        detail="Preparing the SG-side run record and source preview.",
    )
    _set_run_progress(
        record,
        step_key="preview",
        percent=2,
        label="Resolving source inputs",
        detail=f"Looking up live SG source files for {profile.profile_id}.",
    )
    preview = preview_profile_sources(profile)
    record.source_paths = dict(preview.source_paths)
    record.notes = list(preview.notes)
    save_run_record(record)

    record.status = "running"
    record.started_at_utc = utc_now()
    _set_run_progress(
        record,
        step_key="scene_hierarchy",
        percent=6,
        label="Preparing SG sources",
        detail=f"Materializing {profile.profile_id} from the mirrored live slice.",
    )

    try:
        def progress_callback(step_key: str, percent: int, label: str, detail: str = "") -> None:
            _set_run_progress(
                record,
                step_key=step_key,
                percent=percent,
                label=label,
                detail=detail,
            )

        materialized = materialize_bundle(
            output_bundle=Path(record.paths["bundle"]),
            repo_root=profile.repo_root,
            project_root=profile.project_root,
            env={
                "SG-Repo": str(profile.repo_root),
                "SG-CarModels-Repo": str(profile.repo_root),
            },
            report_context=record.context,
            progress_callback=progress_callback,
        )
        record.notes = list(materialized.notes)
        record.source_paths = _record_source_paths(preview, record)
        save_run_record(record)

        _set_run_progress(
            record,
            step_key="write_reports",
            percent=90,
            label="Validating packs and writing reports",
            detail="Running deterministic validators and generating HTML, Markdown, and JSON output.",
        )
        result = execute_bundle_run(
            bundle_dir=Path(record.paths["bundle"]),
            config_path=profile.config_path,
            packs=list(request.packs),
            fail_on=request.fail_on,
            json_out=Path(record.paths["json_report"]),
            html_out=Path(record.paths["html_report"]),
            markdown_out=Path(record.paths["markdown_report"]),
            progress_callback=progress_callback,
        )
        record.summary = result.report.summary()
        record.exit_code = result.exit_code
        record.status = "completed"
        record.completed_at_utc = utc_now()
        record.source_paths = _record_source_paths(preview, record)
        _set_run_progress(
            record,
            step_key="finalize",
            percent=100,
            label="Run completed",
            detail="The reports and SG source-of-truth links are ready to open.",
        )
        return record
    except Exception as exc:
        record.status = "failed"
        record.exit_code = 1
        record.completed_at_utc = utc_now()
        record.error_message = str(exc)
        existing_progress = dict(record.progress or {})
        failure_step = str(existing_progress.get("step_key", "finalize")).strip() or "finalize"
        events = _merged_progress_events(
            existing_progress,
            step_key=failure_step,
            label="Run failed",
            detail=str(exc),
        )
        record.progress = build_progress_payload(
            RUN_PROGRESS_PLAN,
            step_key=failure_step,
            percent=int(existing_progress.get("percent", 100) or 100),
            label="Run failed",
            detail=str(exc),
            events=events,
        )
        save_run_record(record)
        raise


def run_notes(record: RunRecord) -> list[str]:
    metadata = load_run_bundle_metadata(record)
    notes = metadata.get("notes", [])
    if isinstance(notes, list) and notes:
        return [str(item) for item in notes if item]
    return list(record.notes)


def _env_or_default_path(env_keys: tuple[str, ...], default_paths: tuple[Path, ...]) -> tuple[Path, bool]:
    for key in env_keys:
        raw = os.environ.get(key, "").strip()
        if raw:
            return Path(raw), True
    for path in default_paths:
        if path.exists():
            return path, False
    return default_paths[0], False


def _raco_headless_path(root: Path) -> Path:
    path, from_env = _env_or_default_path(
        ("SG_RACO_HEADLESS", "RACO_HEADLESS_EXE"),
        (
            root / "external" / "ramses" / "RaCoHeadless.exe",
            root.parent / "RamsesComposerWindows" / "bin" / "RelWithDebInfo" / "RaCoHeadless.exe",
            Path(r"C:\RamsesComposerWindows\bin\RelWithDebInfo\RaCoHeadless.exe"),
        ),
    )
    if from_env:
        return path

    command_path = shutil.which("RaCoHeadless.exe")
    if command_path:
        return Path(command_path)
    return path


def _blender_executable_path(root: Path) -> Path:
    path, from_env = _env_or_default_path(
        ("SG_BLENDER_EXE", "BLENDER_EXE"),
        (
            root / "external" / "blender" / "blender.exe",
            root.parent / "Blender" / "blender.exe",
            Path(r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe"),
            Path(r"C:\Program Files\Blender Foundation\Blender 4.1\blender.exe"),
            Path(r"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe"),
            Path(r"C:\Program Files\Blender Foundation\Blender 3.6\blender.exe"),
        ),
    )
    if from_env:
        return path

    command_path = shutil.which("blender.exe")
    if command_path:
        return Path(command_path)
    return path


def _bmw_models_repo_path(root: Path) -> Path:
    path, _ = _env_or_default_path(
        ("SG_CARMODELS_REPO",),
        (
            root / "external" / "digital-3d-car-models",
            root.parent / "digital-3d-car-models",
            Path(r"C:\repos\digital-3d-car-models"),
        ),
    )
    return path


def _delivery_checklist_root(root: Path) -> Path:
    return root / "repositories" / "trunk" / ".pdx" / "checkers" / "deliveryChecklist"


def prerequisite_status(repo_root: Path | None = None) -> list[dict[str, str]]:
    root = workspace_root(repo_root)
    mirror_root = root / "repositories" / "trunk"
    checker_root = mirror_root / ".pdx" / "checkers"
    bmw_models_repo = _bmw_models_repo_path(root)
    delivery_checklist_root = _delivery_checklist_root(root)
    raco_headless = _raco_headless_path(root)
    blender_executable = _blender_executable_path(root)
    checks = [
        ("workspace_root", root),
        ("mirror_root", mirror_root),
        ("checker_root", checker_root),
        ("reference_root", Path(r"C:\repositories\trunk")),
        ("bmw_models_repo", bmw_models_repo),
        ("execute_checks", checker_root / "executeChecks.py"),
        ("unused_resource_checker", checker_root / "printNotUsedResources.py"),
        (
            "carpaint_helper",
            mirror_root / ".pdx" / "raco" / "scripts" / "testing" / "read_json_carpaints.py",
        ),
        ("scene_checker", mirror_root / "check_scenes.py"),
        ("raco_headless", raco_headless),
        ("blender_executable", blender_executable),
        ("carmodel_data", mirror_root / ".pdx" / "python" / "carmodel_data.json"),
        ("resource_mappings", mirror_root / ".pdx" / "python" / "resource_mappings.json"),
        ("delivery_checklist_tool", delivery_checklist_root / "deliveryChecklist.exe"),
        ("delivery_checklist_helper", delivery_checklist_root / "deliveryChecklist.py"),
        ("delivery_checklist_readme", delivery_checklist_root / "README.md"),
        ("delivery_checklist_camera_crane", delivery_checklist_root / "cameraCrane.lua"),
        ("bmw_car_manager_script", bmw_models_repo / "ci" / "scripts" / "car_manager.py"),
        ("bmw_test_main_script", bmw_models_repo / "ci" / "scripts" / "test" / "main.py"),
    ]

    payload = []
    for key, path in checks:
        payload.append(
            {
                "key": key,
                "label": key.replace("_", " ").title(),
                "path": str(path),
                "status": "available" if path.exists() else "missing",
            }
        )

    screenshot_readme = bmw_models_repo / "ci" / "scripts" / "README.md"
    payload.append(
        {
            "key": "bmw_screenshot_scripts",
            "label": "BMW Screenshot Scripts",
            "path": str(screenshot_readme),
            "status": "available" if screenshot_readme.exists() else "missing",
        }
    )

    anchorpoint_dir = mirror_root / ".pdx" / "raco" / "json" / "anchorpoints"
    anchorpoint_files = sorted(anchorpoint_dir.glob("anchorpoint_data*.json")) if anchorpoint_dir.exists() else []
    payload.append(
        {
            "key": "anchorpoint_catalogs",
            "label": "Anchorpoint Catalogs",
            "path": str(anchorpoint_dir),
            "status": "available" if anchorpoint_files else "missing",
            }
        )

    adb_path = shutil.which("adb")
    payload.append(
        {
            "key": "adb",
            "label": "ADB",
            "path": adb_path or "adb",
            "status": "available" if adb_path else "missing",
        }
    )

    for package in ("fastapi", "jinja2", "uvicorn", "httpx"):
        payload.append(
            {
                "key": f"python_package_{package}",
                "label": f"Python Package {package}",
                "path": package,
                "status": "available" if importlib.util.find_spec(package) else "missing",
            }
        )

    return payload


def sg_checker_catalog(
    repo_root: Path | None = None,
    *,
    profiles: list[RunProfile] | None = None,
) -> list[dict[str, Any]]:
    root = workspace_root(repo_root)
    live_profiles = profiles if profiles is not None else list_run_profiles(root)
    return [item.to_dict() for item in list_checker_catalog(root, profiles=live_profiles)]


def qa_workflow_status(
    repo_root: Path | None = None,
    profiles: list[RunProfile] | None = None,
) -> list[dict[str, Any]]:
    root = workspace_root(repo_root)
    readiness = {item["key"]: item for item in prerequisite_status(root)}
    live_profiles = profiles if profiles is not None else list_run_profiles(root)
    checker_map = {
        item["key"]: item
        for item in sg_checker_catalog(
            root,
            profiles=live_profiles,
        )
    }
    ready_profiles = [
        profile
        for profile in live_profiles
        if profile.project_root.exists() and profile.config_path.exists()
    ]

    bmw_models_ready = readiness.get("bmw_models_repo", {}).get("status") == "available"
    bmw_scripts_ready = readiness.get("bmw_screenshot_scripts", {}).get("status") == "available"
    bmw_car_manager_ready = readiness.get("bmw_car_manager_script", {}).get("status") == "available"
    bmw_test_main_ready = readiness.get("bmw_test_main_script", {}).get("status") == "available"
    adb_ready = readiness.get("adb", {}).get("status") == "available"
    bmw_targets_ready = any(profile.bmw_smoke_target.strip() for profile in live_profiles)
    delivery_checklist_ready = all(
        readiness.get(key, {}).get("status") == "available"
        for key in (
            "delivery_checklist_tool",
            "delivery_checklist_helper",
            "delivery_checklist_readme",
            "delivery_checklist_camera_crane",
        )
    )
    checker_stack_ready = (
        checker_map.get("style_checker", {}).get("state") == "ready"
        and checker_map.get("execute_checks", {}).get("state") == "ready"
    )
    unused_resources_state = checker_map.get("print_not_used_resources", {}).get("state", "blocked")
    scene_checker_state = checker_map.get("check_scenes", {}).get("state", "blocked")
    delivery_state = checker_map.get("delivery_checklist", {}).get("state", "blocked")
    bmw_catalog_state = checker_map.get("bmw_smoke", {}).get("state", "blocked")

    return [
        {
            "key": "deterministic_preflight",
            "label": "Deterministic preflight before review",
            "state": "covered" if ready_profiles else "blocked",
            "summary": (
                f"{len(ready_profiles)} canonical live profile(s) are ready for anchors, constants, carpaints, and project-sanity checks."
                if ready_profiles
                else "No canonical live profile is currently ready on this machine."
            ),
            "sg_preflight_role": (
                "This is the current core scope: catch deterministic issues early on the mirrored SG slices and persist reusable evidence."
            ),
            "blockers": []
            if ready_profiles
            else ["The mirrored SG live slices or their configs are missing on this machine."],
        },
        {
            "key": "repo_scene_checks",
            "label": "SG checker stack and scene-check path",
            "state": (
                "covered"
                if checker_stack_ready and unused_resources_state == "ready" and scene_checker_state == "ready"
                else "partial"
                if checker_stack_ready or unused_resources_state != "blocked" or scene_checker_state != "blocked"
                else "blocked"
            ),
            "summary": (
                "The operator UI can run the SG checker stack (`check_all_styles.py` + `executeChecks.py`), unused-resource scan, and scene-check path from the same local surface."
                if checker_stack_ready and unused_resources_state == "ready" and scene_checker_state == "ready"
                else "The operator UI can run the SG checker stack here, and it also knows about unused-resource or scene-check coverage, but at least one SG-side checker path is still only partial."
                if checker_stack_ready or unused_resources_state != "blocked" or scene_checker_state != "blocked"
                else "SG checker discovery is not ready on this machine."
            ),
            "sg_preflight_role": (
                "The framework now catalogs the real SG checker stack and exposes the usable parts as one-click actions alongside the standard preflight flow."
            ),
            "blockers": [
                blocker
                for blocker in (
                    None if checker_stack_ready else "The mirrored repo-checker Python stack is incomplete locally.",
                    None if unused_resources_state != "blocked" else "The unused-resource checker is not ready for the current live profiles.",
                    None if scene_checker_state != "blocked" else "The scene-check helper is not ready for the current machine setup.",
                )
                if blocker
            ],
        },
        {
            "key": "delivery_checklist",
            "label": "BMW delivery checklist bridge",
            "state": "partial" if delivery_state != "blocked" else "blocked",
            "summary": (
                "The mirrored SG delivery-checklist assets are present locally, so the operator surface can show the checklist bridge and its BMW-side prerequisites honestly."
                if delivery_state != "blocked" and not (bmw_models_ready and (bmw_car_manager_ready or bmw_test_main_ready))
                else "The mirrored SG delivery-checklist assets and BMW-side helpers are both present locally, but the checklist flow still remains an externally owned step."
                if delivery_state != "blocked"
                else "The mirrored `.pdx/checkers/deliveryChecklist` assets are not complete on this machine."
            ),
            "sg_preflight_role": (
                "SG Preflight now exposes the real delivery-checklist bridge as part of the operator workflow instead of pretending BMW-side delivery steps do not exist."
            ),
            "blockers": [
                blocker
                for blocker in (
                    None
                    if delivery_checklist_ready
                    else "The mirrored `.pdx/checkers/deliveryChecklist` assets are incomplete locally.",
                    None
                    if bmw_models_ready
                    else "Blocked on BMW Git access or a local `digital-3d-car-models` clone.",
                    None
                    if bmw_car_manager_ready or bmw_test_main_ready
                    else "The BMW-side `ci/scripts/car_manager.py` or `ci/scripts/test/main.py` helpers are not available locally.",
                )
                if blocker
            ],
        },
        {
            "key": "bmw_screenshot_smoke",
            "label": "BMW screenshot / export / interface smoke",
            "state": "partial" if bmw_catalog_state != "blocked" else "blocked",
            "summary": (
                "The BMW-side smoke stage is exposed as a one-click action, but it still depends on BMW repo access and per-car target mapping."
                if bmw_models_ready and bmw_scripts_ready and not bmw_targets_ready
                else "The BMW-side smoke stage can be launched from the same operator surface when local prerequisites and car mapping exist."
                if bmw_models_ready and bmw_scripts_ready and bmw_targets_ready
                else "This machine does not currently have the BMW-side screenshot-test prerequisites in place."
            ),
            "sg_preflight_role": (
                "SG Preflight should reduce avoidable failures before this stage, and it now surfaces the BMW smoke stage as an explicit action instead of a hidden external dependency."
            ),
            "blockers": [
                blocker
                for blocker in (
                    None
                    if bmw_models_ready
                    else "Blocked on BMW Git access or a local `digital-3d-car-models` clone.",
                    None
                    if bmw_scripts_ready
                    else "The BMW screenshot-script README under `ci/scripts` is not available locally.",
                    None
                    if bmw_targets_ready
                    else "BMW smoke target mapping for the current live profiles is not configured yet.",
                )
                if blocker
            ],
        },
        {
            "key": "rack_review",
            "label": "Rack, carpaint, and manual visual review",
            "state": "partial" if adb_ready and bmw_models_ready else "blocked",
            "summary": (
                "Rack and final visual approval remain manual, hardware-driven stages even when the local machine is prepared."
                if adb_ready and bmw_models_ready
                else "Rack-side validation is not currently runnable from this machine setup."
            ),
            "sg_preflight_role": (
                "The framework is meant to reduce what reaches rack sessions, not pretend to replace rack, Blender visual review, or designer approval."
            ),
            "blockers": [
                blocker
                for blocker in (
                    None if adb_ready else "ADB is not available locally for rack connectivity checks.",
                    None
                    if bmw_models_ready
                    else "BMW-side access is missing, so the full rack-adjacent workflow cannot be validated end-to-end yet.",
                )
                if blocker
            ],
        },
        {
            "key": "handoff_evidence",
            "label": "Triage and delivery handoff evidence",
            "state": "covered",
            "summary": "Run records plus JSON, HTML, and Markdown outputs are already available for reuse in triage, reviews, and follow-up.",
            "sg_preflight_role": (
                "This is already part of the working product: persistent evidence that helps QA, TA, integration, and delivery discussions start from the same artifact."
            ),
            "blockers": [],
        },
    ]
