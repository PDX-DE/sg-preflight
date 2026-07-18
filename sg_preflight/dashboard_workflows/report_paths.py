"""QA pass report and screenshot review viewer output paths, plus the
dashboard-triggered report build/export and viewer materialization helpers.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from sg_preflight.dashboard_workflows.state_bridge import _with_main_globals
from sg_preflight.qa_pass_report import (
    default_qa_pass_report_zip_path,
    export_qa_pass_report_zip,
    write_qa_pass_report_html,
)


def _screenshot_review_viewer_output_root(workspace: Path, profile_id: str) -> Path:
    safe_profile = re.sub(r"[^A-Za-z0-9_.-]+", "_", profile_id.strip().lower() or "profile")
    return operator_ui_root(workspace) / "screenshot-review-viewer" / safe_profile


def _missing_actual_diagnostics_output_root(workspace: Path, profile_id: str) -> Path:
    safe_profile = re.sub(r"[^A-Za-z0-9_.-]+", "_", profile_id.strip().lower() or "profile")
    return operator_ui_root(workspace) / "missing-actual-diagnostics" / safe_profile


def _screenshot_review_viewer_url(profile_id: str, item_key: str = "") -> str:
    safe_profile = re.sub(r"[^A-Za-z0-9_.-]+", "_", profile_id.strip().lower() or "profile")
    url = f"/sgfx-operator-ui/screenshot-review-viewer/{safe_profile}/screenshot-review-viewer.html"
    if item_key:
        url += f"#{quote(item_key, safe='')}"
    return url


def _qa_pass_report_output_root(workspace: Path, profile_id: str) -> Path:
    safe_profile = re.sub(r"[^A-Za-z0-9_.-]+", "_", profile_id.strip().lower() or "profile")
    return operator_ui_root(workspace) / "qa-pass-report" / safe_profile


def _qa_pass_report_url(profile_id: str) -> str:
    safe_profile = re.sub(r"[^A-Za-z0-9_.-]+", "_", profile_id.strip().lower() or "profile")
    return f"/sgfx-operator-ui/qa-pass-report/{safe_profile}/qa-pass-report.html"


def build_dashboard_qa_pass_report(
    *,
    workspace: Path | str,
    profile_id: str,
    payload: dict[str, Any],
    output_root: Path | str | None = None,
) -> dict[str, Any]:
    workspace_path = Path(workspace).resolve()
    clean_profile = profile_id.strip().upper()
    if not clean_profile:
        raise ValueError("Profile ID required to build the QA Pass report.")
    report_root = Path(output_root).resolve() if output_root else _qa_pass_report_output_root(workspace_path, clean_profile)
    bundle = write_qa_pass_report_html(
        profile_id=clean_profile,
        payload=payload,
        output_root=report_root,
        mode="dashboard",
    )
    result = bundle.to_payload()
    result["url"] = _qa_pass_report_url(clean_profile)
    return result


def export_dashboard_qa_pass_report(
    *,
    workspace: Path | str,
    profile_id: str,
    payload: dict[str, Any],
    bmw_root: Path | str | None = None,
    output_root: Path | str | None = None,
) -> dict[str, Any]:
    workspace_path = Path(workspace).resolve()
    clean_profile = profile_id.strip().upper()
    if not clean_profile:
        raise ValueError("Profile ID required to export the QA Pass report.")
    report_root = Path(output_root).resolve() if output_root else _qa_pass_report_output_root(workspace_path, clean_profile)
    zip_path = default_qa_pass_report_zip_path(report_root, clean_profile)
    result = export_qa_pass_report_zip(
        profile_id=clean_profile,
        workspace=workspace_path,
        bmw_root=bmw_root,
        payload=payload,
        output_path=zip_path,
    )
    payload_result = result.to_payload()
    payload_result["zip_size_bytes"] = zip_path.stat().st_size if zip_path.is_file() else 0
    return payload_result


def _materialize_screenshot_review_viewer_for_dashboard(
    profile_id: str,
    workspace: Path,
    *,
    bmw_root: Path | str | None = None,
) -> Any:
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
    return build_screenshot_review_viewer(
        profile.profile_id,
        project_root,
        _screenshot_review_viewer_output_root(workspace, profile.profile_id),
        expected_root=Path(expected_root_value).resolve() if expected_root_value else None,
        candidate_roots=candidate_roots,
        diff_reference_roots=diff_roots,
        priority_names=tuple(str(item) for item in prep.priority_screenshots),
    )


_screenshot_review_viewer_output_root = _with_main_globals(_screenshot_review_viewer_output_root)
_missing_actual_diagnostics_output_root = _with_main_globals(_missing_actual_diagnostics_output_root)
_qa_pass_report_output_root = _with_main_globals(_qa_pass_report_output_root)
_qa_pass_report_url = _with_main_globals(_qa_pass_report_url)
build_dashboard_qa_pass_report = _with_main_globals(build_dashboard_qa_pass_report)
export_dashboard_qa_pass_report = _with_main_globals(export_dashboard_qa_pass_report)
_screenshot_review_viewer_url = _with_main_globals(_screenshot_review_viewer_url)
_materialize_screenshot_review_viewer_for_dashboard = _with_main_globals(_materialize_screenshot_review_viewer_for_dashboard)
