from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import json
from pathlib import Path
import re
from typing import Any

from sg_preflight.bmw_delivery import read_bmw_screenshot_state
from sg_preflight.delivery_checklist import read_delivery_checklist
from sg_preflight.export_size_analysis import read_export_size_analysis
from sg_preflight.manual_review import render_manual_review_markdown
from sg_preflight.profiles import get_run_profile
from sg_preflight.screenshot_review_viewer import build_screenshot_review_viewer
from sg_preflight.services import operator_ui_root
from sg_preflight.visual_review import build_visual_review_prep


@dataclass(frozen=True)
class QualityHeroReportBundle:
    payload: dict[str, Any]
    markdown_path: Path
    json_path: Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9_.-]+", "-", value.strip().casefold()).strip("-") or "item"


def _safe_status(payload: dict[str, Any]) -> str:
    return str(payload.get("status", "unknown") or "unknown")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON payload is not an object: {path}")
    return payload


def _latest_manual_review_session(
    *,
    profile_id: str,
    workspace: Path,
    ticket_id: str = "",
) -> dict[str, Any]:
    root = operator_ui_root(workspace) / "manual-reviews"
    if not root.exists():
        return {
            "status": "missing",
            "summary": {"recorded_steps": 0, "total_steps": 0, "pending_steps": 0},
            "steps": [],
            "note": "No manual-review session was found in the operator-local workspace.",
            "is_approval": False,
        }
    profile_slug = _slug(profile_id)
    ticket_slug = _slug(ticket_id) if ticket_id else "*"
    matches = [
        path
        for path in root.glob(f"{ticket_slug}/{profile_slug}/*/session.json")
        if path.is_file()
    ]
    if not matches and ticket_id:
        matches = [path for path in root.glob(f"*/{profile_slug}/*/session.json") if path.is_file()]
    if not matches:
        return {
            "status": "missing",
            "summary": {"recorded_steps": 0, "total_steps": 0, "pending_steps": 0},
            "steps": [],
            "note": "No manual-review session was found for this profile.",
            "is_approval": False,
        }
    latest = sorted(matches, key=lambda path: (path.stat().st_mtime, str(path)))[-1]
    session = _read_json(latest)
    session.setdefault("session_path", str(latest))
    session.setdefault("is_approval", False)
    return session


def _mime_for(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".bmp":
        return "image/bmp"
    return "image/png"


def _data_uri(path_value: str, *, max_bytes: int = 1_500_000) -> str:
    if not path_value:
        return ""
    path = Path(path_value)
    if not path.is_file() or path.stat().st_size > max_bytes:
        return ""
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{_mime_for(path)};base64,{encoded}"


def _screenshot_counts(viewer_payload: dict[str, Any]) -> dict[str, int]:
    counts = {
        "items": 0,
        "needs_review": 0,
        "missing_candidate": 0,
        "missing_baseline": 0,
        "dimension_mismatch": 0,
        "cosmetic_likely_pass": 0,
        "structural_likely_review": 0,
        "unclear_manual_review": 0,
    }
    items = viewer_payload.get("items", [])
    if not isinstance(items, list):
        return counts
    counts["items"] = len(items)
    for item in items:
        if not isinstance(item, dict):
            continue
        classification = str(item.get("classification", "")).strip()
        visual = str(item.get("visual_classification", "")).strip()
        if classification in counts:
            counts[classification] += 1
        if visual in counts:
            counts[visual] += 1
    return counts


def _thumbnail_items(viewer_payload: dict[str, Any], limit: int) -> list[dict[str, str]]:
    items = viewer_payload.get("items", [])
    if not isinstance(items, list):
        return []
    thumbnails: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        image_path = (
            str(item.get("diff_path", "") or "").strip()
            or str(item.get("actual_path", "") or "").strip()
            or str(item.get("expected_path", "") or "").strip()
        )
        data_uri = _data_uri(image_path)
        if not data_uri:
            continue
        thumbnails.append(
            {
                "key": str(item.get("key", "")).strip(),
                "classification": str(item.get("classification", "")).strip(),
                "visual_classification": str(item.get("visual_classification", "")).strip(),
                "image_data_uri": data_uri,
                "source_path": image_path,
            }
        )
        if len(thumbnails) >= limit:
            break
    return thumbnails


def _build_or_load_viewer(
    *,
    profile_id: str,
    workspace: Path,
    output_root: Path,
    bmw_root: Path | str | None,
    screenshot_viewer_json: Path | None,
) -> dict[str, Any]:
    if screenshot_viewer_json is not None:
        payload = _read_json(screenshot_viewer_json)
        payload.setdefault("json_path", str(screenshot_viewer_json))
        return payload

    profile = get_run_profile(profile_id, workspace, bmw_root=bmw_root)
    project_root = profile.source_project_root()
    prep = build_visual_review_prep(profile.profile_id, project_root)
    state = read_bmw_screenshot_state(
        profile.profile_id,
        workspace=workspace,
        bmw_root=bmw_root,
        sg_project_root=project_root,
    )
    candidate_roots = tuple(
        Path(value).resolve()
        for value in (str(state.get("actuals_root", "")).strip(),)
        if value and Path(value).is_dir()
    )
    diff_roots = tuple(
        Path(value).resolve()
        for value in (str(state.get("diff_root", "")).strip(),)
        if value and Path(value).is_dir()
    )
    expected_root_value = str(state.get("expected_root", "")).strip()
    bundle = build_screenshot_review_viewer(
        profile.profile_id,
        project_root,
        output_root / "screenshot-viewer",
        expected_root=Path(expected_root_value).resolve() if expected_root_value else None,
        candidate_roots=candidate_roots,
        diff_reference_roots=diff_roots,
        priority_names=tuple(str(item) for item in prep.priority_screenshots),
    )
    payload = bundle.viewer.to_dict()
    payload["json_path"] = str(bundle.json_path)
    payload["html_path"] = str(bundle.html_path)
    return payload


def build_quality_hero_report(
    *,
    profile_id: str,
    workspace: Path | str,
    output_root: Path | str,
    ticket_id: str = "",
    bmw_root: Path | str | None = None,
    screenshot_viewer_json: Path | str | None = None,
    thumbnail_limit: int = 4,
) -> QualityHeroReportBundle:
    clean_profile = profile_id.strip()
    if not clean_profile:
        raise ValueError("profile_id is required")
    workspace_path = Path(workspace).resolve()
    output_path = Path(output_root).resolve()
    output_path.mkdir(parents=True, exist_ok=True)

    profile = get_run_profile(clean_profile, workspace_path, bmw_root=bmw_root)
    project_root = profile.source_project_root()
    delivery = read_delivery_checklist(profile_id=profile.profile_id, workspace=workspace_path)
    export_size = read_export_size_analysis(profile_id=profile.profile_id, workspace=workspace_path, latest=True)
    screenshot_state = read_bmw_screenshot_state(
        profile.profile_id,
        workspace=workspace_path,
        bmw_root=bmw_root,
        sg_project_root=project_root,
    )
    viewer_payload = _build_or_load_viewer(
        profile_id=profile.profile_id,
        workspace=workspace_path,
        output_root=output_path,
        bmw_root=bmw_root,
        screenshot_viewer_json=Path(screenshot_viewer_json).resolve() if screenshot_viewer_json else None,
    )
    manual_review = _latest_manual_review_session(
        profile_id=profile.profile_id,
        workspace=workspace_path,
        ticket_id=ticket_id,
    )
    screenshot_counts = _screenshot_counts(viewer_payload)
    thumbnails = _thumbnail_items(viewer_payload, max(0, int(thumbnail_limit or 0)))

    payload = {
        "schema_version": 1,
        "profile_id": profile.profile_id,
        "ticket_id": ticket_id.strip(),
        "generated_at_utc": _utc_now(),
        "workspace": str(workspace_path),
        "project_root": str(project_root),
        "delivery_checklist": delivery,
        "export_size_analysis": export_size,
        "screenshot_state": screenshot_state,
        "screenshot_viewer": viewer_payload,
        "screenshot_counts": screenshot_counts,
        "manual_review": manual_review,
        "thumbnails": thumbnails,
        "guardrails": [
            "Manual review remains required.",
            "Decision: not approval — evidence only.",
            "BMW Git access is read-only. SGFX never modifies BMW source.",
            "Activity log is local-only — never posted to Jira, SVN, or BMW Git.",
        ],
        "is_approval": False,
    }
    markdown_path = output_path / f"quality-hero-review-{_slug(profile.profile_id)}.md"
    json_path = output_path / f"quality-hero-review-{_slug(profile.profile_id)}.json"
    payload["markdown_path"] = str(markdown_path)
    payload["json_path"] = str(json_path)
    markdown = render_quality_hero_report_markdown(payload)
    markdown_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return QualityHeroReportBundle(payload=payload, markdown_path=markdown_path, json_path=json_path)


def _status_line(label: str, payload: dict[str, Any]) -> str:
    summary = str(payload.get("summary", "")).strip()
    suffix = f" - {summary}" if summary else ""
    return f"- {label}: `{_safe_status(payload)}`{suffix}"


def _checks_markdown(payload: dict[str, Any], *, limit: int = 12) -> list[str]:
    checks = payload.get("checks", [])
    if not isinstance(checks, list) or not checks:
        return ["- No workbook check rows were available."]
    lines = []
    for check in checks[:limit]:
        if not isinstance(check, dict):
            continue
        label = str(check.get("label", check.get("key", "check"))).strip()
        status = str(check.get("status", "unknown")).strip()
        raw_value = str(check.get("raw_value", "")).strip()
        raw_suffix = f" ({raw_value})" if raw_value and raw_value.casefold() != status.casefold() else ""
        lines.append(f"- {label}: `{status}`{raw_suffix}")
    return lines or ["- No workbook check rows were available."]


def _manual_review_markdown(session: dict[str, Any]) -> list[str]:
    if not session.get("steps"):
        return [f"- Status: `{_safe_status(session)}`", f"- Note: {session.get('note', 'No manual-review session was found.')}"]
    rendered = render_manual_review_markdown(session).splitlines()
    return [line for line in rendered if line.strip()][:80]


def render_quality_hero_report_markdown(payload: dict[str, Any]) -> str:
    profile = str(payload.get("profile_id", "")).strip()
    ticket = str(payload.get("ticket_id", "")).strip()
    screenshot_counts = payload.get("screenshot_counts", {}) if isinstance(payload.get("screenshot_counts"), dict) else {}
    viewer = payload.get("screenshot_viewer", {}) if isinstance(payload.get("screenshot_viewer"), dict) else {}
    thumbnails = payload.get("thumbnails", []) if isinstance(payload.get("thumbnails"), list) else []
    lines = [
        f"# Quality-Hero Review Report - {profile}",
        "",
        f"Generated at: `{payload.get('generated_at_utc', '')}`",
        f"Ticket: `{ticket}`" if ticket else "Ticket: not provided",
        f"Project root: `{payload.get('project_root', '')}`",
        "",
        "This report collects local QA evidence for reviewer use. It is not a delivery signoff.",
        "",
        "## Guardrails",
    ]
    lines.extend(f"- {line}" for line in payload.get("guardrails", []))

    lines.extend(
        [
            "",
            "## Evidence Summary",
            _status_line("Delivery checklist", payload.get("delivery_checklist", {})),
            _status_line("Export-size analysis", payload.get("export_size_analysis", {})),
            _status_line("Screenshot test state", payload.get("screenshot_state", {})),
            f"- Screenshot viewer items: `{screenshot_counts.get('items', 0)}`",
            f"- Manual-review session: `{_safe_status(payload.get('manual_review', {}))}`",
            "",
            "## Workbook Stats",
        ]
    )
    lines.extend(_checks_markdown(payload.get("delivery_checklist", {})))
    export_size = payload.get("export_size_analysis", {})
    if isinstance(export_size, dict):
        lines.extend(
            [
                "",
                "## Export Size",
                f"- Workbook: `{export_size.get('workbook_path', '') or 'not found'}`",
                f"- Variants: `{export_size.get('variant_count', 0)}`",
            ]
        )
        variants = export_size.get("variants", [])
        if isinstance(variants, list) and variants:
            for variant in variants[:6]:
                if isinstance(variant, dict):
                    lines.append(f"- {variant.get('name', 'variant')}: `{variant.get('totals', {}).get('Total', '')}`")

    lines.extend(
        [
            "",
            "## Screenshot Review",
            f"- Expected root: `{payload.get('screenshot_state', {}).get('expected_root', '') or 'not found'}`",
            f"- Actual root: `{payload.get('screenshot_state', {}).get('actuals_root', '') or 'not found'}`",
            f"- Diff root: `{payload.get('screenshot_state', {}).get('diff_root', '') or 'not found'}`",
            f"- Viewer HTML: `{viewer.get('html_path', '') or viewer.get('triage_html_path', '') or 'not generated'}`",
            f"- Needs review: `{screenshot_counts.get('needs_review', 0)}`",
            f"- Missing candidate: `{screenshot_counts.get('missing_candidate', 0)}`",
            f"- Dimension mismatch: `{screenshot_counts.get('dimension_mismatch', 0)}`",
            f"- Structural review bucket: `{screenshot_counts.get('structural_likely_review', 0)}`",
            "",
            "| Screenshot | Classification | Visual bucket | Summary |",
            "| --- | --- | --- | --- |",
        ]
    )
    viewer_items = viewer.get("items", []) if isinstance(viewer.get("items", []), list) else []
    if viewer_items:
        for item in viewer_items[:20]:
            if isinstance(item, dict):
                lines.append(
                    "| "
                    + " | ".join(
                        [
                            str(item.get("key", "")).replace("|", "\\|"),
                            str(item.get("classification", "")).replace("|", "\\|"),
                            str(item.get("visual_classification", "")).replace("|", "\\|"),
                            str(item.get("summary", "")).replace("|", "\\|"),
                        ]
                    )
                    + " |"
                )
    else:
        lines.append("| none | not_run | not_run | No screenshot pairs were available. |")

    lines.extend(["", "## Screenshot Thumbnails"])
    if thumbnails:
        for item in thumbnails:
            if isinstance(item, dict):
                lines.extend(
                    [
                        f"### {item.get('key', 'screenshot')}",
                        f"- Classification: `{item.get('classification', '')}` / `{item.get('visual_classification', '')}`",
                        f"- Source path: `{item.get('source_path', '')}`",
                        f"<img alt=\"{item.get('key', 'screenshot')}\" src=\"{item.get('image_data_uri', '')}\" width=\"260\">",
                    ]
                )
    else:
        lines.append("- No embeddable screenshot thumbnails were available within the local size limit.")

    lines.extend(["", "## Manual Review"])
    manual_lines = _manual_review_markdown(payload.get("manual_review", {}))
    lines.extend(manual_lines)
    lines.extend(
        [
            "",
            "## Files",
            f"- JSON: `{payload.get('json_path', '')}`",
            f"- Markdown: `{payload.get('markdown_path', '')}`",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"
