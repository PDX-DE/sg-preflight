from __future__ import annotations

import importlib.util
import json
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
from sg_preflight.config_loader import load_config, load_json
from sg_preflight.models import Report
from sg_preflight.profiles import RunProfile
from sg_preflight.reporting import write_html_report, write_json_report, write_markdown_report
from sg_preflight.utils import ensure_parent
from sg_preflight.validators.anchors import validate_anchors
from sg_preflight.validators.carpaints import validate_carpaints
from sg_preflight.validators.constants import validate_constants
from sg_preflight.validators.project_sanity import validate_project_sanity


VALID_PACKS = ("anchors", "constants", "carpaints", "project_sanity")


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

    for pack in packs:
        report.packs.append(pack_map[pack](bundle, config))

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
    preview = preview_profile_sources(profile)
    record.source_paths = dict(preview.source_paths)
    record.notes = list(preview.notes)
    save_run_record(record)

    record.status = "running"
    record.started_at_utc = utc_now()
    save_run_record(record)

    try:
        materialized = materialize_bundle(
            output_bundle=Path(record.paths["bundle"]),
            repo_root=profile.repo_root,
            project_root=profile.project_root,
            env={
                "SG-Repo": str(profile.repo_root),
                "SG-CarModels-Repo": str(profile.repo_root),
            },
            report_context=record.context,
        )
        record.notes = list(materialized.notes)
        record.source_paths = _record_source_paths(preview, record)
        save_run_record(record)

        result = execute_bundle_run(
            bundle_dir=Path(record.paths["bundle"]),
            config_path=profile.config_path,
            packs=list(request.packs),
            fail_on=request.fail_on,
            json_out=Path(record.paths["json_report"]),
            html_out=Path(record.paths["html_report"]),
            markdown_out=Path(record.paths["markdown_report"]),
        )
        record.summary = result.report.summary()
        record.exit_code = result.exit_code
        record.status = "completed"
        record.completed_at_utc = utc_now()
        record.source_paths = _record_source_paths(preview, record)
        save_run_record(record)
        return record
    except Exception as exc:
        record.status = "failed"
        record.exit_code = 1
        record.completed_at_utc = utc_now()
        record.error_message = str(exc)
        save_run_record(record)
        raise


def run_notes(record: RunRecord) -> list[str]:
    metadata = load_run_bundle_metadata(record)
    notes = metadata.get("notes", [])
    if isinstance(notes, list) and notes:
        return [str(item) for item in notes if item]
    return list(record.notes)


def prerequisite_status(repo_root: Path | None = None) -> list[dict[str, str]]:
    root = workspace_root(repo_root)
    mirror_root = root / "repositories" / "trunk"
    checks = [
        ("workspace_root", root),
        ("mirror_root", mirror_root),
        ("reference_root", Path(r"C:\repositories\trunk")),
        (
            "carpaint_helper",
            mirror_root / ".pdx" / "raco" / "scripts" / "testing" / "read_json_carpaints.py",
        ),
        ("scene_checker", mirror_root / "check_scenes.py"),
        ("carmodel_data", mirror_root / ".pdx" / "python" / "carmodel_data.json"),
        ("resource_mappings", mirror_root / ".pdx" / "python" / "resource_mappings.json"),
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
