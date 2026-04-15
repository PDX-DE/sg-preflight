from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sg_preflight.mirror_audit import (
    MirrorAuditReport,
    load_cached_audit,
    run_deep_mirror_audit,
    run_fast_mirror_audit,
    save_cached_audit,
)
from sg_preflight.models import Finding, Report
from sg_preflight.profiles import RunProfile, list_run_profiles
from sg_preflight.reporting import build_report_presentation, finding_hint
from sg_preflight.services import (
    RunRequest,
    build_run_record,
    execute_profile_run,
    list_recent_run_records,
    load_run_config,
    load_run_record,
    load_run_report,
    operator_ui_cache_root,
    parse_packs,
    prerequisite_status,
    preview_profile_sources,
    run_notes,
    save_run_record,
    workspace_root,
)


def _templates() -> Jinja2Templates:
    return Jinja2Templates(directory=str(Path(__file__).with_name("templates")))


def _static_root() -> Path:
    return Path(__file__).with_name("static")


def _profile_map(profiles: list[RunProfile]) -> dict[str, RunProfile]:
    return {profile.profile_id.lower(): profile for profile in profiles}


def _get_profile(app: FastAPI, profile_id: str) -> RunProfile:
    profile = app.state.profiles.get(profile_id.lower())
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Unknown profile {profile_id!r}")
    return profile


def _cache_paths(root: Path) -> tuple[Path, Path]:
    cache_root = operator_ui_cache_root(root)
    return cache_root / "mirror-audit-fast.json", cache_root / "mirror-audit-deep.json"


def _load_or_create_fast_audit(app: FastAPI) -> MirrorAuditReport:
    fast_cache, _ = _cache_paths(app.state.workspace_root)
    report = load_cached_audit(fast_cache)
    if report is None:
        report = run_fast_mirror_audit(list(app.state.profiles.values()))
        save_cached_audit(fast_cache, report)
    return report


def _load_cached_deep_audit(app: FastAPI) -> MirrorAuditReport | None:
    _, deep_cache = _cache_paths(app.state.workspace_root)
    return load_cached_audit(deep_cache)


def _severity_rank(value: str) -> int:
    severity = value.lower()
    if severity == "error":
        return 0
    if severity == "warning":
        return 1
    if severity == "info":
        return 2
    return 99


def _report_headline(summary: dict[str, int]) -> str:
    if summary.get("errors", 0) > 0:
        return "Needs action before review or rack."
    if summary.get("warnings", 0) > 0:
        return "Useful signal is present, but triage is still needed."
    return "No deterministic findings at the selected threshold."


def _summarize_report(report: Report) -> dict[str, Any]:
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for pack in report.packs:
        for finding in pack.findings:
            key = (finding.severity.lower(), finding.code, finding.message)
            item = grouped.setdefault(
                key,
                {
                    "severity": finding.severity.lower(),
                    "code": finding.code,
                    "message": finding.message,
                    "count": 0,
                    "examples": [],
                },
            )
            item["count"] += 1
            if finding.location and len(item["examples"]) < 2 and finding.location not in item["examples"]:
                item["examples"].append(finding.location)

    highlights = sorted(
        grouped.values(),
        key=lambda item: (
            _severity_rank(str(item["severity"])),
            -int(item["count"]),
            str(item["code"]),
        ),
    )[:3]
    summary = report.summary()
    return {
        "summary": summary,
        "headline": _report_headline(summary),
        "highlights": highlights,
    }


def _latest_matrix_artifact(root: Path, profile: RunProfile, suffix: str) -> Path:
    slug = profile.profile_id.lower()
    return root / "out" / "real-live-matrix" / "latest" / slug / f"{slug}-report.{suffix}"


def _latest_matrix_signal(root: Path, profile: RunProfile) -> dict[str, Any] | None:
    report_path = _latest_matrix_artifact(root, profile, "json")
    if not report_path.exists():
        return None
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None

    report = Report.from_dict(payload)
    summary = _summarize_report(report)
    html_path = _latest_matrix_artifact(root, profile, "html")
    markdown_path = _latest_matrix_artifact(root, profile, "md")
    return {
        "created_at": report_path.stat().st_mtime,
        "json_path": str(report_path),
        "html_path": str(html_path) if html_path.exists() else "",
        "markdown_path": str(markdown_path) if markdown_path.exists() else "",
        **summary,
    }


def _summary_file_link(root: Path) -> dict[str, str]:
    summary_path = root / "out" / "real-live-matrix" / "latest" / "SUMMARY.md"
    return {
        "path": str(summary_path),
        "href": f"/ui/files?path={summary_path}" if summary_path.exists() else "",
    }


def _profile_card(root: Path, profile: RunProfile) -> dict[str, Any]:
    live_signal = _latest_matrix_signal(root, profile)
    is_ready = profile.project_root.exists() and profile.config_path.exists()
    return {
        "profile": profile,
        "project_exists": profile.project_root.exists(),
        "config_exists": profile.config_path.exists(),
        "is_ready": is_ready,
        "readiness_label": "Ready for operator run" if is_ready else "Needs local setup attention",
        "live_signal": live_signal,
    }


def _primary_prerequisites(root: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    all_items = prerequisite_status(root)
    primary_keys = {
        "workspace_root",
        "mirror_root",
        "reference_root",
        "python_package_fastapi",
        "python_package_jinja2",
        "python_package_uvicorn",
    }
    primary = [item for item in all_items if item["key"] in primary_keys]
    secondary = [item for item in all_items if item["key"] not in primary_keys]
    return primary, secondary


def _audit_view_model(report: MirrorAuditReport | None) -> dict[str, Any]:
    if report is None:
        return {
            "status": "unknown",
            "created_at_utc": "",
            "entry_count": 0,
            "drift_count": 0,
            "entries": [],
            "notes": [],
            "sample_differences": [],
        }

    entries = sorted(
        report.entries,
        key=lambda item: (0 if item.status != "match" else 1, item.label.lower()),
    )
    sample_differences: list[str] = []
    for entry in entries:
        for difference in entry.sample_differences:
            if difference not in sample_differences:
                sample_differences.append(difference)
            if len(sample_differences) >= 8:
                break
        if len(sample_differences) >= 8:
            break

    return {
        "status": report.status,
        "created_at_utc": report.created_at_utc,
        "entry_count": len(report.entries),
        "drift_count": sum(1 for entry in report.entries if entry.status != "match"),
        "entries": entries[:6],
        "notes": list(report.notes),
        "sample_differences": sample_differences,
    }


def _cached_preview(app: FastAPI, profile: RunProfile) -> Any:
    key = profile.profile_id.lower()
    cached = app.state.preview_cache.get(key)
    if cached is None:
        cached = preview_profile_sources(profile)
        app.state.preview_cache[key] = cached
    return cached


def _decision_summary(report: Report) -> dict[str, str]:
    summary = report.summary()
    if summary["errors"] > 0:
        return {
            "tone": "error",
            "title": "Not ready for handoff yet",
            "body": "Resolve the error-level findings first, then use the grouped findings below to decide ownership and sequencing.",
        }
    if summary["warnings"] > 0:
        return {
            "tone": "warning",
            "title": "Triage before rack or review",
            "body": "No error-level findings were raised, but warnings still need explicit ownership or acceptance.",
        }
    return {
        "tone": "ok",
        "title": "Deterministic checks are clean",
        "body": "Use the evidence and context sections for handoff or documentation if this run is part of a delivery checkpoint.",
    }


def _coerce_run_payload(payload: dict[str, Any]) -> tuple[str, RunRequest]:
    profile_id = str(payload.get("profile_id", "")).strip()
    if not profile_id:
        raise HTTPException(status_code=400, detail="profile_id is required")

    raw_packs = payload.get("packs", [])
    packs = parse_packs(
        [str(item).strip().lower() for item in raw_packs if str(item).strip()]
        or ["anchors", "constants", "carpaints", "project_sanity"]
    )

    context = payload.get("context", {})
    if not isinstance(context, dict):
        context = {}

    fail_on = str(payload.get("fail_on", "never") or "never")
    return profile_id, RunRequest(
        profile_id=profile_id,
        packs=packs,
        fail_on=fail_on,
        context_overrides={
            str(key): str(value)
            for key, value in context.items()
            if str(key).strip() and str(value).strip()
        },
    )


def _run_profile_background(profile: RunProfile, request: RunRequest, root: Path) -> None:
    try:
        execute_profile_run(profile, request, root)
    except Exception:
        return


def _finding_rows(report: Report, record: Any, config: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for pack in report.packs:
        for index, finding in enumerate(pack.findings, start=1):
            hint = finding_hint(pack.pack, finding.code, config)
            rows.append(
                {
                    "finding_id": f"{pack.pack}-{index}-{finding.code}",
                    "pack": pack.pack,
                    "severity": finding.severity.lower(),
                    "code": finding.code,
                    "location": finding.location or "",
                    "message": finding.message,
                    "details_json": json.dumps(finding.details, indent=2, ensure_ascii=False)
                    if finding.details
                    else "",
                    "owner": hint["owner"],
                    "action": hint["action"],
                    "evidence": _finding_evidence(finding, record),
                }
            )
    return rows


def _path_evidence(label: str, path: str | None) -> dict[str, str]:
    href = ""
    if path:
        candidate = Path(path)
        if candidate.exists() and candidate.is_file():
            href = f"/ui/files?path={path}"
    return {
        "label": label,
        "value": path or "",
        "href": href,
        "kind": "path",
    }


def _value_evidence(label: str, value: Any) -> dict[str, str]:
    return {
        "label": label,
        "value": "" if value is None else str(value),
        "href": "",
        "kind": "value",
    }


def _finding_evidence(finding: Finding, record: Any) -> list[dict[str, str]]:
    evidence: list[dict[str, str]] = []
    source_paths = getattr(record, "source_paths", {}) or {}

    if finding.pack == "constants":
        evidence.append(_value_evidence("Lookup path", finding.location or ""))
        evidence.append(_value_evidence("Expected value", finding.details.get("expected")))
        evidence.append(_value_evidence("Exported value", finding.details.get("exported")))
        evidence.append(_value_evidence("Delta", finding.details.get("delta")))
        evidence.append(_path_evidence("Pivot_Master source", source_paths.get("constants_expected")))
        evidence.append(_path_evidence("Exported constants source", source_paths.get("constants_exported")))
        return [item for item in evidence if item["value"] or item["href"]]

    if finding.pack == "carpaints":
        evidence.append(_value_evidence("Normalized entry", finding.location or ""))
        evidence.append(_value_evidence("Unique key", finding.details.get("unique_key")))
        evidence.append(_value_evidence("Duplicate value", finding.details.get("duplicate_value")))
        evidence.append(_value_evidence("First index", finding.details.get("first_index")))
        evidence.append(_value_evidence("Current index", finding.details.get("current_index")))
        evidence.append(_path_evidence("CarPaint source", source_paths.get("carpaints")))
        return [item for item in evidence if item["value"] or item["href"]]

    if finding.pack == "project_sanity":
        if finding.code == "project_sanity.unused_lua":
            evidence.append(_value_evidence("Lua file", finding.location or ""))
            evidence.append(_path_evidence("Lua source", finding.details.get("source_path")))
        else:
            evidence.append(_value_evidence("Reference", finding.location or ""))
            evidence.append(_path_evidence("Source file", finding.details.get("source_path")))
            evidence.append(_value_evidence("Line number", finding.details.get("line_number")))
            evidence.append(_value_evidence("Line text", finding.details.get("line_text")))
            evidence.append(_value_evidence("Matched brand", finding.details.get("matched_brand")))
            evidence.append(_value_evidence("Matched car model", finding.details.get("matched_model")))
        evidence.append(_path_evidence("Project manifest", record.paths.get("project_manifest")))
        evidence.append(_path_evidence("Project root", record.project_root))
        return [item for item in evidence if item["value"] or item["href"]]

    if finding.pack == "anchors":
        evidence.append(_value_evidence("Anchor / root", finding.location or ""))
        evidence.append(_value_evidence("Rule group", finding.details.get("rule_group")))
        evidence.append(_value_evidence("Anchor root", finding.details.get("root_name")))
        evidence.append(_path_evidence("Anchor scene source", source_paths.get("scene_hierarchy")))
        return [item for item in evidence if item["value"] or item["href"]]

    if finding.location:
        evidence.append(_value_evidence("Location", finding.location))
    return evidence


def _evidence_links(record: Any) -> list[dict[str, str]]:
    links = [
        _path_evidence("JSON report", record.paths.get("json_report")),
        _path_evidence("HTML report", record.paths.get("html_report")),
        _path_evidence("Markdown report", record.paths.get("markdown_report")),
        _path_evidence("Bundle metadata", record.paths.get("bundle_metadata")),
        _path_evidence("Project manifest", record.paths.get("project_manifest")),
        _path_evidence("Bundle root", record.paths.get("bundle")),
        _path_evidence("Run record", record.paths.get("run_record")),
        _path_evidence("Anchor RCA", record.source_paths.get("scene_hierarchy")),
        _path_evidence("Pivot_Master", record.source_paths.get("constants_expected")),
        _path_evidence("Module_constants / exported constants", record.source_paths.get("constants_exported")),
        _path_evidence("CarPaint catalog", record.source_paths.get("carpaints")),
    ]
    return [link for link in links if link["href"] or link["value"]]


def _allowed_roots(app: FastAPI) -> list[Path]:
    roots = {app.state.workspace_root.resolve(), Path(r"C:\repositories").resolve()}
    for profile in app.state.profiles.values():
        roots.add(profile.repo_root.resolve())
        roots.add(profile.reference_repo_root.resolve())
    return list(roots)


def _is_allowed_file(app: FastAPI, path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for root in _allowed_roots(app):
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def create_app(
    *,
    root: Path | None = None,
    profiles: list[RunProfile] | None = None,
) -> FastAPI:
    app = FastAPI(title="SG Preflight Operator UI")
    app.state.workspace_root = workspace_root(root)
    app.state.profiles = _profile_map(profiles or list_run_profiles(app.state.workspace_root))
    app.state.templates = _templates()
    app.state.preview_cache = {}

    app.mount("/ui/static", StaticFiles(directory=str(_static_root())), name="ui_static")

    @app.get("/")
    async def root_redirect() -> RedirectResponse:
        return RedirectResponse(url="/ui", status_code=302)

    @app.get("/ui")
    async def home(request: Request) -> Any:
        fast_audit = _load_or_create_fast_audit(app)
        deep_audit = _load_cached_deep_audit(app)
        primary_prereqs, secondary_prereqs = _primary_prerequisites(app.state.workspace_root)
        return app.state.templates.TemplateResponse(
            request,
            "home.html",
            {
                "profiles": [
                    _profile_card(app.state.workspace_root, profile)
                    for profile in app.state.profiles.values()
                ],
                "recent_runs": list_recent_run_records(app.state.workspace_root),
                "primary_prerequisites": primary_prereqs,
                "secondary_prerequisites": secondary_prereqs,
                "fast_audit": _audit_view_model(fast_audit),
                "deep_audit": _audit_view_model(deep_audit),
                "matrix_summary": _summary_file_link(app.state.workspace_root),
            },
        )

    @app.get("/ui/profiles/{profile_id}")
    async def run_view(request: Request, profile_id: str) -> Any:
        profile = _get_profile(app, profile_id)
        preview = _cached_preview(app, profile)
        return app.state.templates.TemplateResponse(
            request,
            "run.html",
            {
                "profile": profile,
                "preview": preview,
                "card": _profile_card(app.state.workspace_root, profile),
                "packs": ["anchors", "constants", "carpaints", "project_sanity"],
            },
        )

    @app.post("/ui/api/runs")
    async def create_run(request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Expected a JSON object")

        profile_id, run_request = _coerce_run_payload(payload)
        profile = _get_profile(app, profile_id)
        record = build_run_record(profile, run_request, app.state.workspace_root)
        run_request.run_id = record.run_id
        save_run_record(record)
        background_tasks.add_task(
            _run_profile_background,
            profile,
            run_request,
            app.state.workspace_root,
        )
        return JSONResponse(
            {
                "run_id": record.run_id,
                "result_url": f"/ui/runs/{record.run_id}",
                "status_url": f"/ui/api/runs/{record.run_id}",
            },
            status_code=202,
        )

    @app.get("/ui/runs/{run_id}")
    async def result_view(request: Request, run_id: str) -> Any:
        record = load_run_record(run_id, app.state.workspace_root)
        report = load_run_report(record)
        config = load_run_config(record) if report is not None else {}
        presentation = build_report_presentation(report, config) if report is not None else None
        findings = _finding_rows(report, record, config) if report is not None else []
        return app.state.templates.TemplateResponse(
            request,
            "result.html",
            {
                "record": record,
                "report": report,
                "presentation": presentation,
                "findings": findings,
                "decision_summary": _decision_summary(report) if report is not None else None,
                "top_groups": presentation["grouped_findings"][:3] if presentation is not None else [],
                "notes": run_notes(record),
            },
        )

    @app.get("/ui/runs/{run_id}/evidence")
    async def evidence_view(request: Request, run_id: str) -> Any:
        record = load_run_record(run_id, app.state.workspace_root)
        return app.state.templates.TemplateResponse(
            request,
            "evidence.html",
            {
                "record": record,
                "links": _evidence_links(record),
            },
        )

    @app.get("/ui/api/runs")
    async def recent_runs_api() -> JSONResponse:
        return JSONResponse([record.to_dict() for record in list_recent_run_records(app.state.workspace_root)])

    @app.get("/ui/api/runs/{run_id}")
    async def run_status_api(run_id: str) -> JSONResponse:
        record = load_run_record(run_id, app.state.workspace_root)
        return JSONResponse(record.to_dict())

    @app.get("/ui/audits/mirror/deep")
    async def run_deep_audit() -> RedirectResponse:
        profiles = list(app.state.profiles.values())
        if not profiles:
            return RedirectResponse(url="/ui", status_code=302)
        report = run_deep_mirror_audit(profiles[0].repo_root, profiles[0].reference_repo_root)
        _, deep_cache = _cache_paths(app.state.workspace_root)
        save_cached_audit(deep_cache, report)
        return RedirectResponse(url="/ui", status_code=302)

    @app.get("/ui/files")
    async def file_proxy(path: str) -> FileResponse:
        target = Path(path)
        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        if not _is_allowed_file(app, target):
            raise HTTPException(status_code=403, detail="Path is outside allowed roots")
        return FileResponse(target)

    return app


def run_ui(host: str = "127.0.0.1", port: int = 8765) -> int:
    try:
        import uvicorn
    except ImportError:
        print(
            "The operator UI requires fastapi, jinja2, and uvicorn to be installed.",
            file=sys.stderr,
        )
        return 1

    url = f"http://{host}:{port}/ui"
    print(f"SG Preflight Operator UI listening at {url}")
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")
    return 0
