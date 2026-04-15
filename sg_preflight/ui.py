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
from sg_preflight.qa_actions import (
    build_action_record,
    execute_operator_action,
    get_operator_action,
    list_operator_actions,
    list_recent_action_records,
    load_action_record,
    save_action_record as save_action_task_record,
)
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
    qa_workflow_status,
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


def _doc_file_link(root: Path, relative_path: str) -> dict[str, str]:
    path = root / relative_path
    return {
        "path": str(path),
        "href": f"/ui/files?path={path}" if path.exists() else "",
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


def _task_cards(root: Path, profiles: list[RunProfile]) -> list[dict[str, Any]]:
    cards = []
    for profile in profiles:
        profile_card = _profile_card(root, profile)
        cards.append(
            {
                "profile_id": profile.profile_id,
                "label": profile.label,
                "title": profile.friendly_task or profile.label,
                "summary": profile.friendly_summary or profile.workflow_value or profile.operator_goal,
                "href": f"/ui/profiles/{profile.profile_id}",
                "button_label": f"Open {profile.profile_id}",
                "status": profile_card["readiness_label"],
                "is_ready": profile_card["is_ready"],
                "highlights": list(profile.focus_points[:2]),
                "live_signal": profile_card["live_signal"],
            }
        )
    return cards


def _guided_job_specs() -> tuple[dict[str, Any], ...]:
    return (
        {
            "key": "full",
            "label": "I changed one car",
            "short_label": "Full car check",
            "description": "Safest default when you touched one car and want the widest useful check before review.",
            "launch_mode": "action",
            "packs": ["anchors", "constants", "carpaints", "project_sanity"],
            "button_template": "Run Full Check For {profile_id}",
            "highlights": (
                "Runs the widest useful SG-side flow on this machine",
                "Best first stop before review, rack, or handoff",
            ),
            "best_profiles": ("G70", "G65", "G45"),
            "profile_help": {
                "G70": "Best first stop when you touched general delivery files and want broad sanity checks.",
                "G65": "Best first stop when you touched one car and also want constants evidence.",
                "G45": "Best first stop when you touched a classic slice and want low-noise anchor sanity.",
            },
        },
        {
            "key": "constants",
            "label": "I changed constants",
            "short_label": "Constants check",
            "description": "Use this when you touched Pivot_Master, Module_constants, or engineering values.",
            "launch_mode": "run",
            "packs": ["constants"],
            "button_template": "Run Constants Check For {profile_id}",
            "highlights": (
                "Checks expected vs exported engineering values",
                "Best when you want hard evidence for a value mismatch",
            ),
            "best_profiles": ("G65",),
            "profile_help": {
                "G65": "Best current live slice for constants drift and engineering-value evidence.",
                "G70": "Useful if you changed G70 constants and want a fast value-only pass.",
                "G45": "Useful if you changed classic constants and only want the constants pack.",
            },
        },
        {
            "key": "anchors",
            "label": "I changed anchors",
            "short_label": "Anchor check",
            "description": "Use this when you changed anchor names, positions, or the anchor scene itself.",
            "launch_mode": "run",
            "packs": ["anchors"],
            "button_template": "Run Anchor Check For {profile_id}",
            "highlights": (
                "Checks anchor naming and required-anchor rules",
                "Best before opening Ramses Composer for manual anchor review",
            ),
            "best_profiles": ("G45",),
            "profile_help": {
                "G45": "Best current live slice for classic anchor-family sanity.",
                "G70": "Useful if you changed the G70 anchor scene and want a quick structure pass.",
                "G65": "Useful if you changed the G65 anchor scene and want a quick structure pass.",
            },
        },
        {
            "key": "carpaints",
            "label": "I changed car paints",
            "short_label": "Carpaint check",
            "description": "Use this when you touched CarPaint IDs, names, finish values, or paint metadata.",
            "launch_mode": "run",
            "packs": ["carpaints"],
            "button_template": "Run Carpaint Check For {profile_id}",
            "highlights": (
                "Checks duplicate IDs and normalized paint data",
                "Best before any rack-side paint review",
            ),
            "best_profiles": ("G70", "G65", "G45"),
            "profile_help": {
                "G70": "Good first stop for shared BMW CarPaint issues on the live IDCevo side.",
                "G65": "Good first stop if you want shared BMW CarPaint issues plus the G65 live slice.",
                "G45": "Good first stop if you want the same shared BMW catalog checked from the classic side.",
            },
        },
        {
            "key": "delivery_sanity",
            "label": "I changed files, Lua, or references",
            "short_label": "File sanity check",
            "description": "Use this when you changed scene links, Lua files, export paths, or delivery-facing project files.",
            "launch_mode": "run",
            "packs": ["project_sanity"],
            "button_template": "Run File Sanity For {profile_id}",
            "highlights": (
                "Checks cross-car references, unused Lua, and path risks",
                "Best before delivery review or repo handoff",
            ),
            "best_profiles": ("G70",),
            "profile_help": {
                "G70": "Best current live slice for cross-car references and unused-Lua signal.",
                "G65": "Useful if you changed G65 project files and want a project-sanity-only pass.",
                "G45": "Useful if you changed classic project files and want legacy sanity only.",
            },
        },
    )


def _guided_job_map() -> dict[str, dict[str, Any]]:
    return {str(item["key"]).lower(): dict(item) for item in _guided_job_specs()}


def _get_guided_job(job_key: str | None) -> dict[str, Any] | None:
    if not job_key:
        return None
    return _guided_job_map().get(str(job_key).strip().lower())


def _guided_job_cards() -> list[dict[str, Any]]:
    cards = []
    for item in _guided_job_specs():
        cards.append(
            {
                "key": item["key"],
                "label": item["label"],
                "short_label": item["short_label"],
                "description": item["description"],
                "highlights": list(item["highlights"]),
                "href": f"/ui/start/{item['key']}",
            }
        )
    return cards


_SOURCE_FILE_LABELS = {
    "scene_hierarchy": "Anchor RCA",
    "constants_expected": "Pivot_Master",
    "constants_exported": "Module_constants / exported constants",
    "carpaints": "CarPaint catalog",
}

_SOURCE_FILE_ORDER = (
    "scene_hierarchy",
    "constants_expected",
    "constants_exported",
    "carpaints",
)


def _guided_profile_cards(root: Path, profiles: list[RunProfile], job: dict[str, Any]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    best_profiles = {str(item).upper() for item in job.get("best_profiles", ())}
    profile_help = job.get("profile_help", {})

    for profile in profiles:
        profile_card = _profile_card(root, profile)
        if job["launch_mode"] == "action":
            launch = {
                "kind": "action",
                "action_id": f"qa_stack__{profile.profile_id.lower()}",
                "button_label": str(job["button_template"]).format(profile_id=profile.profile_id),
            }
        else:
            launch = {
                "kind": "run",
                "profile_id": profile.profile_id,
                "packs": list(job["packs"]),
                "job_key": job["key"],
                "job_label": job["short_label"],
                "button_label": str(job["button_template"]).format(profile_id=profile.profile_id),
            }

        cards.append(
            {
                "profile": profile,
                "live_signal": profile_card["live_signal"],
                "is_ready": profile_card["is_ready"],
                "readiness_label": profile_card["readiness_label"],
                "is_best_match": profile.profile_id.upper() in best_profiles,
                "job_summary": str(profile_help.get(profile.profile_id, profile.friendly_summary or profile.workflow_value or profile.operator_goal)),
                "launch": launch,
            }
        )

    cards.sort(
        key=lambda item: (
            0 if item["is_best_match"] else 1,
            0 if item["is_ready"] else 1,
            item["profile"].profile_id,
        )
    )
    return cards


def _guided_profile_sections(root: Path, profiles: list[RunProfile], job: dict[str, Any]) -> dict[str, Any]:
    cards = _guided_profile_cards(root, profiles, job)
    primary = next((item for item in cards if item["is_best_match"]), cards[0] if cards else None)
    others = [item for item in cards if primary is None or item["profile"].profile_id != primary["profile"].profile_id]
    return {
        "primary_profile": primary,
        "other_profiles": others,
    }


def _action_cards(root: Path, profiles: list[RunProfile], *, scope: str, profile_id: str = "") -> list[dict[str, Any]]:
    cards = []
    for action in list_operator_actions(root, profiles=profiles):
        if action.scope != scope:
            continue
        if profile_id and action.profile_id.lower() != profile_id.lower():
            continue
        cards.append(
            {
                "action_id": action.action_id,
                "label": action.label,
                "description": action.description,
                "ready": action.ready,
                "status_label": "Ready" if action.ready else "Blocked",
                "blocker_message": action.blocker_message,
                "command_preview": action.command_preview,
            }
    )
    return cards


def _source_file_cards(preview: Any) -> list[dict[str, str]]:
    source_paths = getattr(preview, "source_paths", {}) or {}
    cards: list[dict[str, str]] = []

    for key in _SOURCE_FILE_ORDER:
        value = str(source_paths.get(key, "")).strip()
        if not value:
            continue
        cards.append(_path_evidence(_SOURCE_FILE_LABELS.get(key, key.replace("_", " ").title()), value))

    for key, value in source_paths.items():
        if key in _SOURCE_FILE_ORDER or not str(value).strip():
            continue
        cards.append(_path_evidence(str(key).replace("_", " ").title(), str(value)))
    return cards


def _primary_launch(profile: RunProfile, selected_job: dict[str, Any] | None) -> dict[str, Any]:
    if selected_job is not None and selected_job.get("launch_mode") == "run":
        return {
            "kind": "run",
            "title": f"Best default if you changed {str(selected_job['short_label']).lower()}",
            "description": "Run the smallest useful deterministic check for that kind of change, then open the first problem.",
            "button_label": str(selected_job["button_template"]).format(profile_id="This Car"),
            "packs": list(selected_job["packs"]),
            "job_key": str(selected_job["key"]),
            "job_label": str(selected_job["short_label"]),
            "checklist": [
                *(f"Run only the {pack} pack for this car" for pack in selected_job["packs"]),
                "Skip the wider SG-side stack unless you open the secondary actions below.",
            ],
        }

    return {
        "kind": "action",
        "title": f"Best default for {profile.profile_id}",
        "description": "Run the full SG-side check path that is available on this machine for this car.",
        "button_label": "Run Full Check For This Car",
        "action_id": f"qa_stack__{profile.profile_id.lower()}",
        "checklist": [
            "Run the normal preflight for anchors, constants, carpaints, and project sanity.",
            "Run the SG repo checker for this car when it is available here.",
            "Run scene check or BMW smoke only when the local machine is ready for them.",
        ],
    }


def _primary_prerequisites(root: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    all_items = prerequisite_status(root)
    primary_keys = {
        "workspace_root",
        "mirror_root",
        "reference_root",
        "bmw_models_repo",
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
            "title": "Fix these before moving on",
            "body": "There is at least one red problem. Start with the first one below before rack, review, or handoff.",
        }
    if summary["warnings"] > 0:
        return {
            "tone": "warning",
            "title": "Read these before review",
            "body": "Nothing is red, but there are still yellow findings that need an owner or a clear decision.",
        }
    return {
        "tone": "ok",
        "title": "This check looks clean",
        "body": "No deterministic problems were found at this level. Open files and proof only if someone asks for evidence.",
    }


def _dedupe_links(items: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        key = (
            str(item.get("label", "")),
            str(item.get("value", "")),
            str(item.get("href", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _first_problem(
    record: Any,
    decision_summary: dict[str, str] | None,
    grouped_findings: list[dict[str, Any]],
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    if not grouped_findings:
        title = decision_summary["title"] if decision_summary is not None else "This check looks clean"
        return {
            "is_clean": True,
            "tone": "ok",
            "title": "You are done unless someone asks for proof",
            "summary": title,
            "message": (
                decision_summary["body"]
                if decision_summary is not None
                else "No deterministic problems were found."
            ),
            "owner": "No owner routing is needed.",
            "action": "Share a clean-run handoff only if someone needs evidence.",
            "occurrence_label": "0 occurrences",
            "open_link": _path_evidence("HTML report", record.paths.get("html_report")),
            "done_line": "You are done when you have either moved on or shared the clean-run handoff.",
            "copy_text": "",
            "location": "",
            "pack": "",
            "code": "",
            "severity": "ok",
        }

    top = grouped_findings[0]
    raw = next(
        (
            finding
            for finding in findings
            if finding["pack"] == top["pack"]
            and finding["code"] == top["code"]
            and finding["message"] == top["message"]
            and finding["severity"] == top["severity"]
        ),
        findings[0] if findings else None,
    )
    evidence_link = next(
        (item for item in (raw.get("evidence", []) if raw is not None else []) if item.get("href")),
        None,
    )
    severity = str(top["severity"]).lower()
    if severity == "error":
        title = "Start with this red problem"
    elif severity == "warning":
        title = "Start with this yellow problem"
    else:
        title = "Start with this signal"

    return {
        "is_clean": False,
        "tone": severity,
        "title": title,
        "summary": f"{top['pack']} / {top['code']}",
        "message": str(top["message"]),
        "owner": str(top.get("owner", "")).strip() or "No owner hint yet",
        "action": str(top.get("action", "")).strip() or "Open the linked file and decide the next owner.",
        "occurrence_label": f"{top['count']} occurrence(s)",
        "open_link": evidence_link
        or {
            "label": "Files And Proof",
            "value": record.paths.get("html_report", ""),
            "href": f"/ui/runs/{record.run_id}/evidence",
            "kind": "path",
        },
        "done_line": "You are done when this problem has an owner, a source file, and a copied handoff.",
        "copy_text": raw.get("copy_text", "") if raw is not None else "",
        "location": raw.get("location", "") if raw is not None else "",
        "pack": str(top["pack"]),
        "code": str(top["code"]),
        "severity": severity,
    }


def _next_steps(report: Report, presentation: dict[str, Any]) -> list[str]:
    summary = report.summary()
    grouped = list(presentation.get("grouped_findings", []))
    steps: list[str] = []

    if summary["errors"] > 0:
        steps.append("Open the first red problem and understand that one before looking at anything else.")
    elif summary["warnings"] > 0:
        steps.append("Open the first yellow problem and decide whether it needs a fix or only a note.")
    else:
        steps.append("This check is clean. You only need to open files if someone asks for proof.")

    if grouped:
        top = grouped[0]
        action = str(top.get("action", "")).strip() or "Open the linked file and decide the next owner."
        steps.append(f"Start with {top['pack']} / {top['code']}. {action}")
        owner = str(top.get("owner", "")).strip()
        if owner:
            steps.append(f"If you hand this off, send the quick update to {owner}.")
        else:
            steps.append("If you hand this off, copy the quick update below and attach the HTML report if needed.")
    else:
        steps.append("Use the quick update below if you need to say that the check completed cleanly.")
        steps.append("Do not attach extra files unless someone asks for them.")

    return steps[:3]


def _quick_update_text(
    record: Any,
    report: Report,
    decision_summary: dict[str, str],
    grouped_findings: list[dict[str, Any]],
) -> str:
    job_label = str(record.context.get("operator_job_label", "")).strip()
    title = f"SG Preflight {job_label} for {record.profile_id}" if job_label else f"SG Preflight check for {record.profile_id}"
    summary = report.summary()
    lines = [
        title,
        f"Result: {decision_summary['title']}",
        f"Counts: {summary['errors']} errors, {summary['warnings']} warnings, {summary['info']} info, {summary['total']} total",
        "",
        "Start here:",
    ]

    if not grouped_findings:
        lines.append("No grouped findings were raised.")
    else:
        for item in grouped_findings[:3]:
            lines.append(
                f"- [{str(item['severity']).upper()}] {item['pack']} / {item['code']} x{item['count']}: {item['message']}"
            )
            owner = str(item.get("owner", "")).strip()
            action = str(item.get("action", "")).strip()
            if owner:
                lines.append(f"  Owner: {owner}")
            if action:
                lines.append(f"  Action: {action}")

    lines.extend(
        [
            "",
            "Open if needed:",
            f"HTML report: {record.paths.get('html_report', '')}",
            f"Project root: {record.project_root}",
        ]
    )
    return "\n".join(line for line in lines if line is not None).strip()


def _problem_handoff_text(record: Any, first_problem: dict[str, Any]) -> str:
    if first_problem.get("is_clean"):
        lines = [
            f"SG Preflight clean run for {record.profile_id}",
            "Result: no deterministic problems were found in this run.",
            f"HTML report: {record.paths.get('html_report', '')}",
            f"Files and proof: /ui/runs/{record.run_id}/evidence",
        ]
        return "\n".join(lines).strip()

    lines = [
        f"SG Preflight first problem for {record.profile_id}",
        f"Problem: {str(first_problem.get('severity', '')).upper()} - {first_problem.get('pack', '')} / {first_problem.get('code', '')}",
        f"Message: {first_problem.get('message', '')}",
        f"Owner: {first_problem.get('owner', '')}",
        f"Action: {first_problem.get('action', '')}",
    ]
    location = str(first_problem.get("location", "")).strip()
    if location:
        lines.append(f"Location: {location}")
    open_link = first_problem.get("open_link", {})
    if open_link and open_link.get("value"):
        lines.append(f"{open_link.get('label', 'Open')}: {open_link.get('value', '')}")
    lines.append(f"HTML report: {record.paths.get('html_report', '')}")
    return "\n".join(lines).strip()


def _handoff_options(
    record: Any,
    quick_update_text: str,
    full_handoff_text: str,
    first_problem: dict[str, Any],
) -> dict[str, Any]:
    primary_label = (
        "Copy Clean Run Handoff" if first_problem.get("is_clean") else "Copy Handoff For This Problem"
    )
    primary_text = _problem_handoff_text(record, first_problem)
    return {
        "primary": {
            "target_id": "copy-primary-handoff",
            "label": primary_label,
            "text": primary_text,
        },
        "secondary": [
            {
                "target_id": "copy-quick-update",
                "label": "Copy Quick Update",
                "text": quick_update_text,
            },
            {
                "target_id": "copy-full-handoff",
                "label": "Copy Full Handoff",
                "text": full_handoff_text or quick_update_text,
            },
        ],
    }


def _load_text_file(path_value: str) -> str:
    if not path_value:
        return ""
    path = Path(path_value)
    if not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _finding_copy_text(finding: dict[str, Any]) -> str:
    lines = [
        f"{str(finding['severity']).upper()} - {finding['pack']} / {finding['code']}",
        f"Message: {finding['message']}",
    ]
    if finding.get("location"):
        lines.append(f"Location: {finding['location']}")
    owner = str(finding.get("owner", "")).strip()
    action = str(finding.get("action", "")).strip()
    if owner:
        lines.append(f"Owner: {owner}")
    if action:
        lines.append(f"Action: {action}")
    for item in finding.get("evidence", [])[:4]:
        value = str(item.get("value", "")).strip()
        if value:
            lines.append(f"{item['label']}: {value}")
    return "\n".join(lines).strip()


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


def _run_action_background(action_id: str, run_id: str, root: Path) -> None:
    try:
        action = get_operator_action(action_id, root)
        record = load_action_record(run_id, root)
        execute_operator_action(action, root, record=record)
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
            rows[-1]["copy_text"] = _finding_copy_text(rows[-1])
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


def _evidence_sections(record: Any, first_problem: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    report_links = _dedupe_links(
        [
            _path_evidence("HTML report", record.paths.get("html_report")),
            _path_evidence("Markdown report", record.paths.get("markdown_report")),
            _path_evidence("JSON report", record.paths.get("json_report")),
        ]
    )
    source_links = [
        _path_evidence("Anchor RCA", record.source_paths.get("scene_hierarchy")),
        _path_evidence("Pivot_Master", record.source_paths.get("constants_expected")),
        _path_evidence("Module_constants / exported constants", record.source_paths.get("constants_exported")),
        _path_evidence("CarPaint catalog", record.source_paths.get("carpaints")),
    ]
    if first_problem is not None:
        open_link = first_problem.get("open_link", {})
        if open_link.get("href") and open_link.get("value"):
            source_links.insert(0, dict(open_link))
    source_links = _dedupe_links([link for link in source_links if link.get("href") or link.get("value")])
    metadata_links = _dedupe_links(
        [
            _path_evidence("Project manifest", record.paths.get("project_manifest")),
            _path_evidence("Bundle metadata", record.paths.get("bundle_metadata")),
            _path_evidence("Run record", record.paths.get("run_record")),
            _path_evidence("Bundle root", record.paths.get("bundle")),
            _path_evidence("Project root", record.project_root),
        ]
    )
    return [
        {
            "key": "reports",
            "title": "Reports",
            "description": "Use these when you need the run summary in HTML, Markdown, or JSON.",
            "links": report_links,
        },
        {
            "key": "source_truth",
            "title": "Source-of-truth files",
            "description": "Open these when you need the SG file behind the current finding.",
            "links": source_links,
        },
        {
            "key": "run_metadata",
            "title": "Run metadata",
            "description": "Generated metadata and bookkeeping for this run.",
            "links": metadata_links,
        },
    ]


def _action_links(record: Any) -> list[dict[str, str]]:
    links = [
        _path_evidence("Action log", record.paths.get("log")),
        _path_evidence("Summary Markdown", record.paths.get("summary_md")),
        _path_evidence("Summary JSON", record.paths.get("summary_json")),
    ]
    for artifact in getattr(record, "artifacts", []):
        path = str(artifact.get("path", "")).strip()
        label = str(artifact.get("label", "Artifact")).strip() or "Artifact"
        if path:
            links.append(_path_evidence(label, path))
    return [link for link in links if link["href"] or link["value"]]


def _action_result_view(record: Any) -> dict[str, Any]:
    links = _action_links(record)
    open_now = [link for link in links if link.get("href")][:3]
    summary_lines = list(record.summary.get("lines", [])) if isinstance(record.summary, dict) else []

    if record.status == "completed":
        return {
            "title": "This automation finished",
            "body": summary_lines[0] if summary_lines else "The SG-side action completed.",
            "what_ran": record.command_preview or "Internal SG QA action",
            "next_steps": summary_lines[1:4] or ["Open the summary markdown if you need to hand this off."],
            "open_now": open_now,
        }
    if record.status == "blocked":
        blocker = record.blocker_message or "This action is blocked on the current machine."
        return {
            "title": "This automation is blocked here",
            "body": blocker,
            "what_ran": record.command_preview or "Internal SG QA action",
            "next_steps": [
                "Read the blocker below before trying to run this again.",
                "Use the normal preflight path if you still need SG-side evidence today.",
            ],
            "open_now": open_now,
        }
    if record.status == "failed":
        return {
            "title": "This automation failed before completion",
            "body": record.error_message or "Open the action log first and inspect the failure.",
            "what_ran": record.command_preview or "Internal SG QA action",
            "next_steps": [
                "Open the action log first.",
                "Fix the local failure or blocker before re-running.",
            ],
            "open_now": open_now,
        }
    return {
        "title": "This automation is still running",
        "body": "Wait for the page to refresh, then open the summary or log.",
        "what_ran": record.command_preview or "Internal SG QA action",
        "next_steps": ["Stay on this page until the status changes."],
        "open_now": open_now,
    }


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
        ordered_profiles = list(app.state.profiles.values())
        return app.state.templates.TemplateResponse(
            request,
            "home.html",
            {
                "profiles": [
                    _profile_card(app.state.workspace_root, profile)
                    for profile in ordered_profiles
                ],
                "guided_jobs": _guided_job_cards(),
                "task_cards": _task_cards(app.state.workspace_root, ordered_profiles),
                "workspace_actions": _action_cards(
                    app.state.workspace_root,
                    ordered_profiles,
                    scope="workspace",
                ),
                "recent_runs": list_recent_run_records(app.state.workspace_root),
                "recent_actions": list_recent_action_records(app.state.workspace_root),
                "primary_prerequisites": primary_prereqs,
                "secondary_prerequisites": secondary_prereqs,
                "fast_audit": _audit_view_model(fast_audit),
                "deep_audit": _audit_view_model(deep_audit),
                "matrix_summary": _summary_file_link(app.state.workspace_root),
                "workflow_alignment": _doc_file_link(
                    app.state.workspace_root,
                    "docs/qa-workflow-alignment.md",
                ),
                "workflow_steps": qa_workflow_status(
                    app.state.workspace_root,
                    profiles=list(app.state.profiles.values()),
                ),
            },
        )

    @app.get("/ui/start/{job_key}")
    async def guided_job_view(request: Request, job_key: str) -> Any:
        job = _get_guided_job(job_key)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Unknown guided job {job_key!r}")
        ordered_profiles = list(app.state.profiles.values())
        sections = _guided_profile_sections(app.state.workspace_root, ordered_profiles, job)
        return app.state.templates.TemplateResponse(
            request,
            "guided_job.html",
            {
                "job": job,
                "primary_profile": sections["primary_profile"],
                "other_profiles": sections["other_profiles"],
            },
        )

    @app.get("/ui/profiles/{profile_id}")
    async def run_view(request: Request, profile_id: str, job: str | None = None) -> Any:
        profile = _get_profile(app, profile_id)
        preview = _cached_preview(app, profile)
        selected_job = _get_guided_job(job)
        primary_launch = _primary_launch(profile, selected_job)
        profile_actions = _action_cards(
            app.state.workspace_root,
            list(app.state.profiles.values()),
            scope="profile",
            profile_id=profile.profile_id,
        )
        secondary_actions = [
            item
            for item in profile_actions
            if item["action_id"] != primary_launch.get("action_id", "")
        ]
        selected_packs = (
            list(selected_job["packs"])
            if selected_job is not None and selected_job["launch_mode"] == "run"
            else ["anchors", "constants", "carpaints", "project_sanity"]
        )
        return app.state.templates.TemplateResponse(
            request,
            "run.html",
            {
                "profile": profile,
                "preview": preview,
                "card": _profile_card(app.state.workspace_root, profile),
                "selected_job": selected_job,
                "primary_launch": primary_launch,
                "source_file_cards": _source_file_cards(preview),
                "selected_packs": selected_packs,
                "profile_actions": secondary_actions,
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

    @app.post("/ui/api/actions")
    async def create_action(request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Expected a JSON object")
        action_id = str(payload.get("action_id", "")).strip()
        if not action_id:
            raise HTTPException(status_code=400, detail="action_id is required")
        action = get_operator_action(action_id, app.state.workspace_root, profiles=list(app.state.profiles.values()))
        if action.ready:
            record = build_action_record(action, app.state.workspace_root)
            save_action_task_record(record)
        else:
            record = execute_operator_action(action, app.state.workspace_root)
        if action.ready:
            background_tasks.add_task(_run_action_background, action.action_id, record.run_id, app.state.workspace_root)
        return JSONResponse(
            {
                "run_id": record.run_id,
                "result_url": f"/ui/actions/{record.run_id}",
                "status_url": f"/ui/api/actions/{record.run_id}",
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
        decision_summary = _decision_summary(report) if report is not None else None
        grouped_findings = presentation["grouped_findings"] if presentation is not None else []
        quick_update_text = (
            _quick_update_text(record, report, decision_summary, grouped_findings)
            if report is not None and decision_summary is not None
            else ""
        )
        full_handoff_text = _load_text_file(record.paths.get("markdown_report", ""))
        first_problem = (
            _first_problem(record, decision_summary, grouped_findings, findings)
            if report is not None and decision_summary is not None
            else None
        )
        evidence_sections = (
            _evidence_sections(record, first_problem)
            if first_problem is not None
            else []
        )
        handoff_options = (
            _handoff_options(record, quick_update_text, full_handoff_text, first_problem)
            if first_problem is not None
            else {}
        )
        job_label = str(record.context.get("operator_job_label", "")).strip()
        return app.state.templates.TemplateResponse(
            request,
            "result.html",
            {
                "record": record,
                "report": report,
                "presentation": presentation,
                "findings": findings,
                "decision_summary": decision_summary,
                "top_groups": grouped_findings[:3] if presentation is not None else [],
                "first_problem": first_problem,
                "next_steps": _next_steps(report, presentation) if report is not None and presentation is not None else [],
                "handoff_options": handoff_options,
                "evidence_sections": evidence_sections,
                "job_label": job_label,
                "notes": run_notes(record),
            },
        )

    @app.get("/ui/runs/{run_id}/evidence")
    async def evidence_view(request: Request, run_id: str) -> Any:
        record = load_run_record(run_id, app.state.workspace_root)
        report = load_run_report(record)
        config = load_run_config(record) if report is not None else {}
        presentation = build_report_presentation(report, config) if report is not None else None
        findings = _finding_rows(report, record, config) if report is not None else []
        decision_summary = _decision_summary(report) if report is not None else None
        grouped_findings = presentation["grouped_findings"] if presentation is not None else []
        first_problem = (
            _first_problem(record, decision_summary, grouped_findings, findings)
            if report is not None and decision_summary is not None
            else None
        )
        return app.state.templates.TemplateResponse(
            request,
            "evidence.html",
            {
                "record": record,
                "first_problem": first_problem,
                "evidence_sections": _evidence_sections(record, first_problem),
            },
        )

    @app.get("/ui/actions/{run_id}")
    async def action_view(request: Request, run_id: str) -> Any:
        record = load_action_record(run_id, app.state.workspace_root)
        links = _action_links(record)
        return app.state.templates.TemplateResponse(
            request,
            "action.html",
            {
                "record": record,
                "links": links,
                "action_result": _action_result_view(record),
                "log_text": _load_text_file(record.paths.get("log", "")),
            },
        )

    @app.get("/ui/api/runs")
    async def recent_runs_api() -> JSONResponse:
        return JSONResponse([record.to_dict() for record in list_recent_run_records(app.state.workspace_root)])

    @app.get("/ui/api/runs/{run_id}")
    async def run_status_api(run_id: str) -> JSONResponse:
        record = load_run_record(run_id, app.state.workspace_root)
        return JSONResponse(record.to_dict())

    @app.get("/ui/api/actions/{run_id}")
    async def action_status_api(run_id: str) -> JSONResponse:
        record = load_action_record(run_id, app.state.workspace_root)
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
