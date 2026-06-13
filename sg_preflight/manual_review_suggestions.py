from __future__ import annotations

from pathlib import Path
from typing import Any

from sg_preflight.export_size_analysis import read_export_size_analysis
from sg_preflight.screenshot_triage import build_screenshot_triage
from sg_preflight.services import operator_ui_root

from sg_preflight.manual_review_templates import (
    AUTO_CHECK_NOTE,
    REVIEW_ASSIST_GUARDRAILS,
    REVIEW_ASSIST_NOTE,
    VALID_VERDICTS,
    _BMW_SCRIPT_CONFLUENCE_SOURCE,
    _CONFLUENCE_SOURCE,
    _DELIVERY_CONFLUENCE_SOURCE,
    _EVIDENCE_AVAILABLE,
    _EVIDENCE_MISSING,
    _PENDING_VERDICT,
    QUALITY_HERO_STEPS,
    _profile_project_roots,
    _slug,
    _workspace,
)


def _first_existing(candidates: list[Path]) -> Path | None:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _first_glob(root: Path, patterns: tuple[str, ...]) -> Path | None:
    if not root.exists():
        return None
    for pattern in patterns:
        matches = sorted(path for path in root.glob(pattern) if path.exists())
        if matches:
            return matches[0]
    return None


def _manual_suggestion_marker(workspace: Path | str | None, profile_id: str, slug: str) -> Path | None:
    root = _workspace(workspace)
    profile = _slug(profile_id)
    step = _slug(slug)
    candidates = [
        root / "operator_state" / "manual_review_suggestions" / profile / f"{step}.passed",
        root / "operator_state" / "manual_review_suggestions" / profile / f"{step}.ok",
        root / "operator_state" / "manual_review_suggestions" / f"{profile}_{step}.passed",
        root / "operator_state" / "manual_review_suggestions" / f"{profile}_{step}.ok",
    ]
    return _first_existing(candidates)


def _auto_check_fields(
    *,
    status: str,
    kind: str,
    summary: str,
    paths: list[Path] | None = None,
    metrics: dict[str, Any] | None = None,
    operator_focus_status: str = "incomplete",
    operator_focus_reason: str = "Operator records the manual-review verdict.",
) -> dict[str, Any]:
    return {
        "auto_check_status": status,
        "auto_check_kind": kind,
        "auto_check_summary": summary,
        "auto_check_paths": [str(path) for path in (paths or []) if path],
        "auto_check_metrics": dict(metrics or {}),
        "operator_focus_status": operator_focus_status,
        "operator_focus_reason": operator_focus_reason,
        "auto_check_is_approval": False,
    }


def _suggestion(
    reason: str,
    paths: list[Path] | None = None,
    *,
    kind: str = "file_presence",
    auto_check_status: str = _EVIDENCE_AVAILABLE,
    metrics: dict[str, Any] | None = None,
    operator_focus_reason: str = "Operator records the manual-review verdict.",
) -> dict[str, Any]:
    auto_paths = paths or []
    return {
        "suggested_verdict": "",
        "suggestion_status": _EVIDENCE_AVAILABLE,
        "evidence_status": _EVIDENCE_AVAILABLE,
        "suggestion_reason": reason,
        "suggestion_paths": [str(path) for path in auto_paths if path],
        **_auto_check_fields(
            status=auto_check_status,
            kind=kind,
            summary=reason,
            paths=auto_paths,
            metrics=metrics,
            operator_focus_reason=operator_focus_reason,
        ),
        "manual_review_required": True,
        "recorded_by_tool": True,
        "is_approval": False,
    }


def _missing_suggestion(
    reason: str,
    paths: list[Path] | None = None,
    *,
    kind: str = "file_presence",
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    auto_paths = paths or []
    return {
        "suggested_verdict": "",
        "suggestion_status": _EVIDENCE_MISSING,
        "evidence_status": _EVIDENCE_MISSING,
        "suggestion_reason": reason,
        "suggestion_paths": [str(path) for path in auto_paths if path],
        **_auto_check_fields(
            status=_EVIDENCE_MISSING,
            kind=kind,
            summary=reason,
            paths=auto_paths,
            metrics=metrics,
        ),
        "manual_review_required": True,
        "recorded_by_tool": True,
        "is_approval": False,
    }


def _blender_suggestion(profile_id: str, workspace: Path | str | None, roots: list[Path]) -> dict[str, Any]:
    for root in roots:
        blend = _first_glob(root, ("_WorkFiles/**/*.blend", "_Workfiles/**/*.blend", "**/*.blend"))
        if blend is not None:
            return _suggestion("Blender scene file found; manual visual review remains required.", [blend])
    return _missing_suggestion("No Blender scene file was found for this profile.", roots[:1])


def _constants_suggestion(profile_id: str, workspace: Path | str | None, roots: list[Path]) -> dict[str, Any]:
    clean = profile_id.strip()
    for root in roots:
        pivot = _first_glob(
            root,
            (
                f"_WorkFiles/json/*{clean}*Pivot_Master*.json",
                f"_Workfiles/json/*{clean}*Pivot_Master*.json",
                "_WorkFiles/json/*Pivot_Master*.json",
                "_Workfiles/json/*Pivot_Master*.json",
            ),
        )
        module = _first_glob(
            root,
            (
                f"_Common/constants/scripts/*{clean}*.lua",
                "_Common/constants/scripts/Module_constants*.lua",
                "_Common/constants/**/*.lua",
            ),
        )
        if pivot is not None and module is not None:
            return _suggestion(
                "Pivot_Master and Module_constants files are present; manual value review remains required.",
                [pivot, module],
            )
        if pivot is not None or module is not None:
            found = [path for path in (pivot, module) if path is not None]
            return _missing_suggestion("Only one constants source was found; operator should complete the comparison.", found)
    return _missing_suggestion("No Pivot_Master or Module_constants source was found for this profile.", roots[:1])


def _unique_path_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(text)
    return unique


def _auto_check_root(workspace: Path | str | None, profile_id: str) -> Path:
    return operator_ui_root(_workspace(workspace)) / "manual-review-auto-checks" / _slug(profile_id)


def _visual_diff_metrics(report: Any) -> dict[str, Any]:
    return {
        "visual_diff": {
            "pair_count": int(getattr(report, "pair_count", 0)),
            "unchanged_count": int(getattr(report, "unchanged_count", 0)),
            "near_identical_count": int(getattr(report, "near_identical_count", 0)),
            "needs_review_count": int(getattr(report, "needs_review_count", 0)),
            "missing_candidate_count": int(getattr(report, "missing_candidate_count", 0)),
            "missing_baseline_count": int(getattr(report, "missing_baseline_count", 0)),
            "dimension_mismatch_count": int(getattr(report, "dimension_mismatch_count", 0)),
            "cosmetic_likely_pass_count": int(getattr(report, "cosmetic_likely_pass_count", 0)),
            "structural_likely_review_count": int(getattr(report, "structural_likely_review_count", 0)),
            "unclear_manual_review_count": int(getattr(report, "unclear_manual_review_count", 0)),
            "external_classifier_status": str(getattr(report, "external_classifier_status", "")),
            "image_backend": str(getattr(report, "image_backend", "")),
        }
    }


def _visual_diff_suggestion(profile_id: str, workspace: Path | str | None, roots: list[Path]) -> dict[str, Any]:
    for root in roots:
        if not root.exists():
            continue
        tests_root = root / "export" / "tests"
        if not tests_root.exists():
            continue
        diff_root = _auto_check_root(workspace, profile_id) / "visual-diffs"
        try:
            report = build_screenshot_triage(profile_id, root, diff_root=diff_root)
        except Exception as exc:  # noqa: BLE001
            return _missing_suggestion(
                f"Visual diff auto-check could not read local screenshot evidence: {exc}",
                [tests_root],
                kind="visual_diff",
                metrics={"visual_diff": {"error": str(exc)}},
            )
        paths: list[Path] = []
        expected_root = str(getattr(report, "expected_root", "")).strip()
        if expected_root:
            paths.append(Path(expected_root))
        paths.extend(Path(str(item.path)) for item in getattr(report, "candidate_roots", ()) if str(item.path).strip())
        paths.extend(Path(str(item.path)) for item in getattr(report, "diff_roots", ()) if str(item.path).strip())
        if diff_root.exists():
            paths.append(diff_root)
        metrics = _visual_diff_metrics(report)
        pair_count = metrics["visual_diff"]["pair_count"]
        if pair_count <= 0:
            return _missing_suggestion(
                "Visual diff auto-check found screenshot folders but no comparable image pairs.",
                paths or [tests_root],
                kind="visual_diff",
                metrics=metrics,
            )
        focus_count = (
            metrics["visual_diff"]["needs_review_count"]
            + metrics["visual_diff"]["missing_candidate_count"]
            + metrics["visual_diff"]["missing_baseline_count"]
            + metrics["visual_diff"]["dimension_mismatch_count"]
            + metrics["visual_diff"]["structural_likely_review_count"]
            + metrics["visual_diff"]["unclear_manual_review_count"]
        )
        if focus_count:
            return _suggestion(
                f"Visual diff auto-check reviewed {pair_count} screenshot pair(s); {focus_count} item(s) remain for operator focus.",
                paths or [tests_root],
                kind="visual_diff",
                auto_check_status="incomplete",
                metrics=metrics,
                operator_focus_reason="Screenshot differences or gaps require operator review before recording a verdict.",
            )
        return _suggestion(
            f"Visual diff auto-check reviewed {pair_count} screenshot pair(s); operator still confirms the final look.",
            paths or [tests_root],
            kind="visual_diff",
            metrics=metrics,
        )
    return _missing_suggestion(
        "No screenshot test folders were found for this profile.",
        roots[:1],
        kind="visual_diff",
    )


def _final_look_suggestion(profile_id: str, workspace: Path | str | None, roots: list[Path]) -> dict[str, Any]:
    file_payload: dict[str, Any] | None = None
    for root in roots:
        blend = _first_glob(root, ("_WorkFiles/**/*.blend", "_Workfiles/**/*.blend", "**/*.blend"))
        expected = _first_glob(root, ("export/tests/expected/*", "export/tests/**/*.png", "export/tests/**/*.jpg"))
        if blend is not None and expected is not None:
            file_payload = _suggestion(
                "Blender scene and screenshot baseline output are present; manual final-look review remains required.",
                [blend, expected],
            )
            break
        if blend is not None or expected is not None:
            found = [path for path in (blend, expected) if path is not None]
            file_payload = _missing_suggestion(
                "Only partial final-look evidence was found; operator should compare RaCo, Blender, and Epic.",
                found,
            )
            break
    if file_payload is None:
        file_payload = _missing_suggestion("No final-look comparison evidence was found for this profile.", roots[:1])
    visual_payload = _visual_diff_suggestion(profile_id, workspace, roots)
    if str(visual_payload.get("auto_check_kind", "")) != "visual_diff":
        return file_payload
    merged = dict(file_payload)
    merged["auto_check_kind"] = "visual_diff"
    merged["auto_check_status"] = str(visual_payload.get("auto_check_status", _EVIDENCE_MISSING))
    merged["auto_check_summary"] = (
        f"{file_payload.get('suggestion_reason', '')} "
        f"{visual_payload.get('auto_check_summary', visual_payload.get('suggestion_reason', ''))}"
    ).strip()
    merged["auto_check_metrics"] = dict(visual_payload.get("auto_check_metrics", {}))
    merged["operator_focus_status"] = str(visual_payload.get("operator_focus_status", "incomplete"))
    merged["operator_focus_reason"] = str(
        visual_payload.get("operator_focus_reason", "Operator records the manual-review verdict.")
    )
    merged["auto_check_paths"] = _unique_path_strings(
        [*merged.get("auto_check_paths", []), *visual_payload.get("auto_check_paths", [])]
    )
    merged["suggestion_paths"] = _unique_path_strings(
        [*merged.get("suggestion_paths", []), *visual_payload.get("suggestion_paths", [])]
    )
    if str(file_payload.get("evidence_status", "")) == _EVIDENCE_AVAILABLE:
        merged["evidence_status"] = _EVIDENCE_AVAILABLE
        merged["suggestion_status"] = _EVIDENCE_AVAILABLE
    return merged


def _workbook_variance_suggestion(profile_id: str, workspace: Path | str | None) -> dict[str, Any]:
    payload = read_export_size_analysis(profile_id=profile_id, workspace=_workspace(workspace), latest=True)
    workbook_path = str(payload.get("workbook_path", "")).strip()
    paths = [Path(workbook_path)] if workbook_path else []
    variant_count = int(payload.get("variant_count", 0) or 0)
    metrics = {
        "workbook_variance": {
            "status": str(payload.get("status", "unknown")),
            "data_available": bool(payload.get("data_available", False)),
            "variant_count": variant_count,
            "workbook_date": str(payload.get("workbook_date", "")),
            "worksheet": str(payload.get("worksheet", "")),
        }
    }
    if payload.get("data_available"):
        status = _EVIDENCE_AVAILABLE if variant_count > 0 else "incomplete"
        return _suggestion(
            f"Export-size workbook variance auto-check found {variant_count} variant row(s); operator still checks relevant RaCo behavior.",
            paths,
            kind="workbook_variance",
            auto_check_status=status,
            metrics=metrics,
            operator_focus_reason="Workbook rows identify coverage targets; operator records the manual-review verdict.",
        )
    return _missing_suggestion(
        f"Export-size workbook variance auto-check unavailable: {payload.get('summary', '')}",
        paths,
        kind="workbook_variance",
        metrics=metrics,
    )


def _marker_suggestion(
    *,
    profile_id: str,
    workspace: Path | str | None,
    slug: str,
    found_reason: str,
    missing_reason: str,
) -> dict[str, Any]:
    marker = _manual_suggestion_marker(workspace, profile_id, slug)
    if marker is not None:
        return _suggestion(found_reason, [marker], kind="operator_marker")
    return _missing_suggestion(
        missing_reason,
        [_workspace(workspace) / "operator_state" / "manual_review_suggestions"],
        kind="operator_marker",
    )


def _functionality_suggestion(profile_id: str, workspace: Path | str | None, roots: list[Path]) -> dict[str, Any]:
    marker = _manual_suggestion_marker(workspace, profile_id, "functionality_test_raco")
    if marker is not None:
        return _suggestion(
            "Functionality test marker found; operator still confirms RaCo behavior.",
            [marker],
            kind="operator_marker",
        )
    workbook_payload = _workbook_variance_suggestion(profile_id, workspace)
    if str(workbook_payload.get("evidence_status", "")) == _EVIDENCE_AVAILABLE:
        return workbook_payload
    for root in roots:
        resource = _first_glob(
            root,
            (
                "**/*LightFX*",
                "**/*WelcomeFX*",
                "**/*WelcomeAnimation*",
                "**/*ShadesFX*",
                "**/*CountryVariant*",
            ),
        )
        if resource is not None:
            return _suggestion(
                "Functionality-related LightFX/WelcomeFX resource evidence found; operator still confirms behavior in RaCo.",
                [resource],
                kind="file_presence",
            )
    return workbook_payload


def _anchor_points_suggestion(profile_id: str, workspace: Path | str | None, roots: list[Path]) -> dict[str, Any]:
    marker = _manual_suggestion_marker(workspace, profile_id, "anchor_points_test_raco")
    if marker is not None:
        return _suggestion(
            "Anchor-points test marker found; operator still confirms anchor placement.",
            [marker],
            kind="operator_marker",
        )
    for root in roots:
        anchor = _first_glob(
            root,
            (
                "**/*AnchorPoints*",
                "**/*Anchorpoints*",
                "**/*Anchor_Points*",
                "**/*APN*",
                "**/*BoundingBox*",
            ),
        )
        if anchor is not None:
            return _suggestion(
                "Anchor-point resource evidence found; operator still confirms anchor placement in RaCo.",
                [anchor],
                kind="file_presence",
            )
    return _missing_suggestion(
        "No anchor-point resource evidence was found for this profile.",
        roots[:1],
        kind="file_presence",
    )


def _carpaints_suggestion(profile_id: str, workspace: Path | str | None, roots: list[Path]) -> dict[str, Any]:
    marker = _manual_suggestion_marker(workspace, profile_id, "carpaints_test_raco")
    if marker is not None:
        return _suggestion(
            "CarPaints test marker found; operator still confirms material output.",
            [marker],
            kind="operator_marker",
        )
    for root in roots:
        candidates = [
            root / "_Common" / "CarPaint.json",
            root / "_Common" / "CarPaint_IDC23.json",
            root.parent / "CarPaint.json",
            root.parent / "CarPaint_IDC23.json",
        ]
        catalog = _first_existing(candidates)
        if catalog is None:
            catalog = _first_glob(
                root,
                (
                    "**/*CarPaint*.json",
                    "**/*carpaint*.json",
                    "**/*Lackcode*.json",
                    "**/*Lackcodes*.json",
                    "**/*read_json_carpaints*.py",
                ),
            )
        if catalog is not None:
            return _suggestion(
                "CarPaint catalog or helper evidence found; operator still confirms material output in RaCo.",
                [catalog],
                kind="file_presence",
            )
    return _missing_suggestion(
        "No CarPaint catalog or helper evidence was found for this profile.",
        roots[:1],
        kind="file_presence",
    )


def _documentation_suggestion(profile_id: str, workspace: Path | str | None, roots: list[Path]) -> dict[str, Any]:
    for root in roots:
        changelog = _first_existing([root / "CHANGELOG.md", root / "Changelog.md", root / "changelog.md"])
        readme = _first_existing([root / "README.md", root / "Readme.md", root / "readme.md"])
        if changelog is not None and readme is not None:
            return _suggestion(
                "README and changelog files are present; manual documentation review remains required.",
                [readme, changelog],
            )
        if changelog is not None or readme is not None:
            found = [path for path in (readme, changelog) if path is not None]
            return _missing_suggestion("Only partial documentation evidence was found; operator should review scope manually.", found)
    return _missing_suggestion("No README or changelog was found for this profile.", roots[:1])


def suggest_manual_review_verdicts(
    profile_id: str,
    *,
    workspace: Path | str | None = None,
) -> dict[str, Any]:
    return run_manual_review_auto_checks(profile_id, workspace=workspace)


def run_manual_review_auto_checks(
    profile_id: str,
    *,
    workspace: Path | str | None = None,
) -> dict[str, Any]:
    roots = _profile_project_roots(profile_id, workspace)
    suggestions = {
        "blender_visual_check": _blender_suggestion(profile_id, workspace, roots),
        "constants_info_verification": _constants_suggestion(profile_id, workspace, roots),
        "final_look_comparison_raco_blender_epic": _final_look_suggestion(profile_id, workspace, roots),
        "functionality_test_raco": _functionality_suggestion(profile_id, workspace, roots),
        "anchor_points_test_raco": _anchor_points_suggestion(profile_id, workspace, roots),
        "carpaints_test_raco": _carpaints_suggestion(profile_id, workspace, roots),
        "documentation_review": _documentation_suggestion(profile_id, workspace, roots),
    }
    focus_steps = [
        slug
        for slug, suggestion in suggestions.items()
        if str(suggestion.get("auto_check_status", "")).strip() in {_EVIDENCE_MISSING, "incomplete"}
    ]
    return {
        "profile_id": profile_id.strip(),
        "status": "available",
        "auto_execution_status": "available",
        "project_roots": [str(root) for root in roots],
        "suggestions": suggestions,
        "steps": [
            {
                "slug": step.slug,
                "title": step.title,
                **suggestions.get(step.slug, {}),
            }
            for step in QUALITY_HERO_STEPS
        ],
        "operator_focus_steps": focus_steps,
        "manual_review_required": True,
        "summary": (
            f"Manual-review auto-checks prepared evidence for {len(suggestions)} step(s); "
            f"{len(focus_steps)} step(s) still need operator focus before verdict recording."
        ),
        "note": f"Evidence hints never select a manual-review verdict; the operator records each verdict. {AUTO_CHECK_NOTE}",
        "recorded_by_tool": True,
        "is_approval": False,
        "confluence_anchors": [_CONFLUENCE_SOURCE, _DELIVERY_CONFLUENCE_SOURCE, _BMW_SCRIPT_CONFLUENCE_SOURCE],
    }


def _review_assist_verdict(step: dict[str, Any]) -> tuple[str, str]:
    evidence_status = str(step.get("evidence_status", "")).strip()
    auto_check_status = str(step.get("auto_check_status", "")).strip()
    auto_check_kind = str(step.get("auto_check_kind", "")).strip()
    if evidence_status == _EVIDENCE_AVAILABLE and auto_check_kind == "operator_marker":
        return "passed", "Existing operator marker found; operator still confirms before recording."
    if auto_check_status == _EVIDENCE_AVAILABLE:
        return "incomplete", "Evidence is available, but the manual check still needs operator confirmation."
    if auto_check_status == "incomplete":
        return "incomplete", "Local evidence points to remaining review focus before recording a verdict."
    if evidence_status == _EVIDENCE_MISSING or auto_check_status == _EVIDENCE_MISSING:
        return "incomplete", "Required evidence is missing or unavailable; operator should keep this step incomplete."
    return "incomplete", "No local evidence was strong enough to suggest a completed verdict."


def build_manual_review_assist_from_auto_checks(auto_check_payload: dict[str, Any]) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    counts = {verdict: 0 for verdict in VALID_VERDICTS}
    for step in auto_check_payload.get("steps", []):
        if not isinstance(step, dict):
            continue
        verdict, reason = _review_assist_verdict(step)
        if verdict in counts:
            counts[verdict] += 1
        steps.append(
            {
                "slug": str(step.get("slug", "")).strip(),
                "title": str(step.get("title", "")).strip(),
                "suggested_verdict": verdict,
                "suggestion_reason": reason,
                "evidence_status": str(step.get("evidence_status", "")).strip(),
                "auto_check_status": str(step.get("auto_check_status", "")).strip(),
                "auto_check_kind": str(step.get("auto_check_kind", "")).strip(),
                "auto_check_summary": str(step.get("auto_check_summary", "")).strip(),
                "operator_confirmation_required": True,
                "manual_review_required": True,
                "is_approval": False,
            }
        )
    focus_count = sum(1 for step in steps if step["suggested_verdict"] != "passed")
    return {
        "schema_version": 1,
        "profile_id": str(auto_check_payload.get("profile_id", "")).strip(),
        "status": "available",
        "assist_status": "available",
        "mode": "local_evidence_rules",
        "steps": steps,
        "counts": counts,
        "operator_focus_steps": [step["slug"] for step in steps if step["suggested_verdict"] != "passed"],
        "manual_review_required": True,
        "operator_confirmation_required": True,
        "records_operator_verdict": False,
        "recorded_by_tool": False,
        "is_approval": False,
        "summary": (
            f"Review Assist prepared {len(steps)} suggested starting point(s); "
            f"{focus_count} step(s) still need operator focus before recording."
        ),
        "note": REVIEW_ASSIST_NOTE,
        "guardrails": list(REVIEW_ASSIST_GUARDRAILS),
        "confluence_anchors": list(auto_check_payload.get("confluence_anchors", []))
        or [_CONFLUENCE_SOURCE, _DELIVERY_CONFLUENCE_SOURCE, _BMW_SCRIPT_CONFLUENCE_SOURCE],
    }


def apply_manual_review_suggestions(
    steps: list[dict[str, Any]],
    *,
    profile_id: str,
    workspace: Path | str | None = None,
    auto_check_payload: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    payload = auto_check_payload if auto_check_payload is not None else suggest_manual_review_verdicts(profile_id, workspace=workspace)
    suggestions = payload.get("suggestions", {}) if isinstance(payload, dict) else {}
    decorated: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        copy = dict(step)
        slug = str(copy.get("slug", "")).strip()
        suggestion = suggestions.get(slug, {}) if isinstance(suggestions, dict) else {}
        if isinstance(suggestion, dict) and str(copy.get("verdict", _PENDING_VERDICT)).strip() == _PENDING_VERDICT:
            copy["suggested_verdict"] = str(suggestion.get("suggested_verdict", "")).strip()
            copy["suggestion_status"] = str(suggestion.get("suggestion_status", "")).strip()
            copy["evidence_status"] = str(suggestion.get("evidence_status", "")).strip()
            copy["suggestion_reason"] = str(suggestion.get("suggestion_reason", "")).strip()
            copy["suggestion_paths"] = list(suggestion.get("suggestion_paths", []))
            copy["auto_check_status"] = str(suggestion.get("auto_check_status", "not_run")).strip()
            copy["auto_check_kind"] = str(suggestion.get("auto_check_kind", "")).strip()
            copy["auto_check_summary"] = str(suggestion.get("auto_check_summary", "")).strip()
            copy["auto_check_paths"] = list(suggestion.get("auto_check_paths", []))
            copy["auto_check_metrics"] = dict(suggestion.get("auto_check_metrics", {}))
            copy["operator_focus_status"] = str(suggestion.get("operator_focus_status", "incomplete")).strip()
            copy["operator_focus_reason"] = str(suggestion.get("operator_focus_reason", "")).strip()
            copy["manual_review_required"] = True
            copy["suggestion_is_approval"] = False
        decorated.append(copy)
    return decorated
