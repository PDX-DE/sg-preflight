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


def _profile_card(profile: RunProfile) -> dict[str, Any]:
    preview = preview_profile_sources(profile)
    expected_sources = {
        "scene_hierarchy": "Anchor scene (.rca)",
        "constants_expected": "Pivot_Master.json",
        "constants_exported": "Module_constants / exported constants",
        "carpaints": "CarPaint.json",
    }
    missing_sources = [
        label
        for key, label in expected_sources.items()
        if key not in preview.source_paths
    ]
    return {
        "profile": profile,
        "preview": preview,
        "project_exists": profile.project_root.exists(),
        "config_exists": profile.config_path.exists(),
        "missing_sources": missing_sources,
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

    app.mount("/ui/static", StaticFiles(directory=str(_static_root())), name="ui_static")

    @app.get("/")
    async def root_redirect() -> RedirectResponse:
        return RedirectResponse(url="/ui", status_code=302)

    @app.get("/ui")
    async def home(request: Request) -> Any:
        fast_audit = _load_or_create_fast_audit(app)
        deep_audit = _load_cached_deep_audit(app)
        return app.state.templates.TemplateResponse(
            request,
            "home.html",
            {
                "profiles": [_profile_card(profile) for profile in app.state.profiles.values()],
                "recent_runs": list_recent_run_records(app.state.workspace_root),
                "prerequisites": prerequisite_status(app.state.workspace_root),
                "fast_audit": fast_audit,
                "deep_audit": deep_audit,
            },
        )

    @app.get("/ui/profiles/{profile_id}")
    async def run_view(request: Request, profile_id: str) -> Any:
        profile = _get_profile(app, profile_id)
        return app.state.templates.TemplateResponse(
            request,
            "run.html",
            {
                "profile": profile,
                "preview": preview_profile_sources(profile),
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
