from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import uuid
from typing import Any

from sg_preflight.profiles import get_run_profile
from sg_preflight.services import operator_ui_root, prerequisite_status, utc_now
from sg_preflight.utils import ensure_parent
from sg_preflight.subprocess_utils import hidden_subprocess_kwargs


MANUAL_REVIEW_HEADER = (
    "Manual review companion. Operator records the verdict per step. "
    "Not a tool-generated review or approval."
)
REVIEW_FOCUS_NOTE = "Review guidance only; the operator records the verdict."

VALID_VERDICTS = ("passed", "failed", "skipped", "incomplete")
_VERDICT_ALIASES = {
    "pass": "passed",
    "fail": "failed",
    "blocked": "incomplete",
    "not_applicable": "skipped",
}
_PENDING_VERDICT = "not_run"
_EVIDENCE_AVAILABLE = "available"
_EVIDENCE_MISSING = "missing"
_SESSION_FILENAME = "session.json"
_CONFLUENCE_SOURCE = (
    "PDX_" + "SER" + "GFX/139_3D-Car/298_Quality-Hero-How-to-review-the-3D-car/page.txt"
)


@dataclass(frozen=True)
class ManualReviewStepTemplate:
    slug: str
    title: str
    guidance: tuple[str, ...]
    tool_hint: str
    review_focus: tuple[str, ...] = ()
    evidence_prompt: str = ""

    def to_session_step(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "title": self.title,
            "guidance": list(self.guidance),
            "tool_hint": self.tool_hint,
            "review_focus": list(self.review_focus),
            "review_focus_note": REVIEW_FOCUS_NOTE,
            "evidence_prompt": self.evidence_prompt,
            "suggested_verdict": "",
            "suggestion_status": "not_run",
            "evidence_status": "not_run",
            "suggestion_reason": "",
            "suggestion_paths": [],
            "manual_review_required": True,
            "operator_verdict": "",
            "verdict": _PENDING_VERDICT,
            "note": "",
            "screenshot_path": "",
            "recorded_at_utc": "",
            "recorded_by_tool": False,
        }


QUALITY_HERO_STEPS: tuple[ManualReviewStepTemplate, ...] = (
    ManualReviewStepTemplate(
        slug="blender_visual_check",
        title="Blender Visual Check",
        tool_hint="blender",
        guidance=(
            "Open the relevant car for testing using an up to date SG-Toolkit in Blender.",
            "Rotate car and look for artefacts and missing or broken meshes.",
            "Test naming and Blender pipeline setup including naming in the outliner.",
            "Go through Trimlines and test color change and material change options in the Analyze section.",
            "Test light functionality including Iconic Glow, position lights and Selective Yellow for relevant country variants.",
            "Check Logos, Lights, Side Mirrors, Rims and Flaps with extra care.",
        ),
        review_focus=(
            "Logos",
            "LightFX",
            "Iconic Glow",
            "Selective Yellow",
            "Side mirrors",
            "Rims",
            "Flaps",
            "Trimlines",
            "Country variants",
            "Material artifacts",
        ),
        evidence_prompt="Attach representative Blender screenshots for visible artifacts or country-variant light concerns.",
    ),
    ManualReviewStepTemplate(
        slug="constants_info_verification",
        title="Constants Info Verification",
        tool_hint="manual",
        guidance=(
            "Use the information provided in the car's Epic.",
            "Check the Constants script in _Common/constants/scripts or the Pivot_Master file in _Workfiles/json.",
            "Compare Tire Diameter.",
            "Compare Suspension information.",
            "Compare Reflections.",
        ),
        review_focus=(
            "Constants",
            "Tire diameter",
            "Suspension",
            "Reflections",
            "Pivot_Master",
            "Epic comparison",
        ),
        evidence_prompt="Record the Epic source and constants source checked; attach screenshots only when useful for reviewer follow-up.",
    ),
    ManualReviewStepTemplate(
        slug="final_look_comparison_raco_blender_epic",
        title="Final Look Comparison RaCo & Blender & Epic",
        tool_hint="raco_blender",
        guidance=(
            "Open the Blender and RaCo export scenes of the relevant car plus the Epic.",
            "Compare the Blender scene to the exported and final look of the RaCo car.",
            "Check Logos, Lights, Side Mirrors, Rims and Flaps with extra care.",
            "Using the IDCEvo README, compare EngineType, CountryVariants, TrimLines and light functionality.",
        ),
        review_focus=(
            "RaCo vs Blender",
            "EngineType",
            "Country variants",
            "Trimlines",
            "Logos",
            "Lights",
            "Side mirrors",
            "Rims",
            "Flaps",
        ),
        evidence_prompt="Attach paired Blender/RaCo screenshots when the final look differs or requires owner follow-up.",
    ),
    ManualReviewStepTemplate(
        slug="functionality_test_raco",
        title="Functionality Test RaCo",
        tool_hint="raco",
        guidance=(
            "With the already open scenes compare animations, lights and Iconic Glow between Blender and RaCo.",
            "Activate WelcomeFX animations and check exterior light, loop state and animation ID behaviour.",
            "Make sure Trimlines, Country variants and Exterior lights show relevant changes from Blender to RaCo scenes.",
            r"Use C:\repos\Seriengrafik\trunk\.pdx\carmodel_data.json for engine and Trimline combinations.",
        ),
        review_focus=(
            "Animations",
            "LightFX",
            "WelcomeFX",
            "Iconic Glow",
            "Exterior lights",
            "Country variants",
            "Trimlines",
        ),
        evidence_prompt="Record the animation and light combination tested and attach proof for incomplete or failing states.",
    ),
    ManualReviewStepTemplate(
        slug="anchor_points_test_raco",
        title="Anchor Points Test RaCo",
        tool_hint="raco",
        guidance=(
            "Open the car's Export scene and add the Abstract Scene View if it is not already set up.",
            "Change Highlight option to Transparency.",
            "In the Scene Graph go to Anchorpoints_BoundingBox and inspect the anchor points on screen.",
            "Use the camera gimble and confirm each anchor point matches the actual tested position.",
            'Naming convention: APN_BoundingBox_"vehicle_part"_"Position".',
        ),
        review_focus=(
            "Anchor points",
            "Bounding boxes",
            "Naming convention",
            "Vehicle part positions",
            "Abstract Scene View",
        ),
        evidence_prompt="Record the anchor family inspected and attach a RaCo screenshot when an anchor is missing or misaligned.",
    ),
    ManualReviewStepTemplate(
        slug="carpaints_test_raco",
        title="CarPaints Test RaCo",
        tool_hint="raco",
        guidance=(
            "Have the 3D Car git set up for testing using the Confluence instructions.",
            "Open the PythonRunner view in the scene and import read_json_carpaints.py.",
            "Use the car paints in the script and test different materials in multiple angles.",
            "Check for artefacts between color or Met/Mat options.",
            "Use the available colors listed at the top of the script.",
        ),
        review_focus=(
            "CarPaint / Lackcode",
            "Color variants",
            "Met/Mat options",
            "Material artifacts",
            "Multiple viewing angles",
        ),
        evidence_prompt="Record the color/material combinations tested and attach screenshots for visible paint or material artifacts.",
    ),
    ManualReviewStepTemplate(
        slug="documentation_review",
        title="Documentation Review",
        tool_hint="manual",
        guidance=(
            "Review 3DCar and Widget documentation relevant to the current ticket.",
            "Check changelog and README content against what was actually delivered.",
            "Keep documentation findings separate from visual verdicts.",
        ),
        review_focus=(
            "README",
            "Changelog",
            "Delivery notes",
            "Ticket scope",
            "Manual findings",
        ),
        evidence_prompt="Record documentation mismatches without marking visual review complete.",
    ),
)

QUALITY_HERO_STEP_TITLES = tuple(step.title for step in QUALITY_HERO_STEPS)


def _workspace(workspace: Path | str | None) -> Path:
    return Path(workspace).resolve() if workspace is not None else Path(__file__).resolve().parents[1]


def _slug(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in value.strip())
    return "_".join(part for part in slug.split("_") if part)


def _profile_project_roots(profile_id: str, workspace: Path | str | None) -> list[Path]:
    root = _workspace(workspace)
    clean_profile = profile_id.strip()
    direct_candidates = [
        root / "Cars_IDCevo" / "BMW" / clean_profile,
        root / "Cars" / "BMW" / clean_profile,
        root / "repositories" / "trunk" / "Cars_IDCevo" / "BMW" / clean_profile,
        root / "repositories" / "trunk" / "Cars" / "BMW" / clean_profile,
    ]
    direct_existing = [path.resolve() for path in direct_candidates if path.exists()]
    if direct_existing:
        return direct_existing
    candidates = list(direct_candidates)
    try:
        profile = get_run_profile(clean_profile, root)
    except KeyError:
        profile = None
    if profile is not None:
        candidates.extend([profile.project_root, profile.source_project_root()])
    seen: set[str] = set()
    ordered: list[Path] = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        key = str(resolved).casefold()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(resolved)
    existing = [path for path in ordered if path.exists()]
    return existing or ordered[:1]


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


def _suggestion(reason: str, paths: list[Path] | None = None) -> dict[str, Any]:
    return {
        "suggested_verdict": "",
        "suggestion_status": _EVIDENCE_AVAILABLE,
        "evidence_status": _EVIDENCE_AVAILABLE,
        "suggestion_reason": reason,
        "suggestion_paths": [str(path) for path in (paths or []) if path],
        "manual_review_required": True,
        "recorded_by_tool": True,
        "is_approval": False,
    }


def _missing_suggestion(reason: str, paths: list[Path] | None = None) -> dict[str, Any]:
    return {
        "suggested_verdict": "",
        "suggestion_status": _EVIDENCE_MISSING,
        "evidence_status": _EVIDENCE_MISSING,
        "suggestion_reason": reason,
        "suggestion_paths": [str(path) for path in (paths or []) if path],
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


def _final_look_suggestion(profile_id: str, workspace: Path | str | None, roots: list[Path]) -> dict[str, Any]:
    for root in roots:
        blend = _first_glob(root, ("_WorkFiles/**/*.blend", "_Workfiles/**/*.blend", "**/*.blend"))
        expected = _first_glob(root, ("export/tests/expected/*", "export/tests/**/*.png", "export/tests/**/*.jpg"))
        if blend is not None and expected is not None:
            return _suggestion(
                "Blender scene and screenshot baseline output are present; manual final-look review remains required.",
                [blend, expected],
            )
        if blend is not None or expected is not None:
            found = [path for path in (blend, expected) if path is not None]
            return _missing_suggestion("Only partial final-look evidence was found; operator should compare RaCo, Blender, and Epic.", found)
    return _missing_suggestion("No final-look comparison evidence was found for this profile.", roots[:1])


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
        return _suggestion(found_reason, [marker])
    return _missing_suggestion(missing_reason, [_workspace(workspace) / "operator_state" / "manual_review_suggestions"])


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
    roots = _profile_project_roots(profile_id, workspace)
    suggestions = {
        "blender_visual_check": _blender_suggestion(profile_id, workspace, roots),
        "constants_info_verification": _constants_suggestion(profile_id, workspace, roots),
        "final_look_comparison_raco_blender_epic": _final_look_suggestion(profile_id, workspace, roots),
        "functionality_test_raco": _marker_suggestion(
            profile_id=profile_id,
            workspace=workspace,
            slug="functionality_test_raco",
            found_reason="Functionality test marker found; operator still confirms RaCo behavior.",
            missing_reason="No functionality-test marker was found for this profile.",
        ),
        "anchor_points_test_raco": _marker_suggestion(
            profile_id=profile_id,
            workspace=workspace,
            slug="anchor_points_test_raco",
            found_reason="Anchor-points test marker found; operator still confirms anchor placement.",
            missing_reason="No anchor-points test marker was found for this profile.",
        ),
        "carpaints_test_raco": _marker_suggestion(
            profile_id=profile_id,
            workspace=workspace,
            slug="carpaints_test_raco",
            found_reason="CarPaints test marker found; operator still confirms material output.",
            missing_reason="No CarPaints test marker was found for this profile.",
        ),
        "documentation_review": _documentation_suggestion(profile_id, workspace, roots),
    }
    return {
        "profile_id": profile_id.strip(),
        "status": "available",
        "project_roots": [str(root) for root in roots],
        "suggestions": suggestions,
        "note": "Evidence hints never select a manual-review verdict; the operator records each verdict.",
        "recorded_by_tool": True,
        "is_approval": False,
    }


def apply_manual_review_suggestions(
    steps: list[dict[str, Any]],
    *,
    profile_id: str,
    workspace: Path | str | None = None,
) -> list[dict[str, Any]]:
    payload = suggest_manual_review_verdicts(profile_id, workspace=workspace)
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
            copy["manual_review_required"] = True
            copy["suggestion_is_approval"] = False
        decorated.append(copy)
    return decorated


def _normalize_verdict(value: object) -> str:
    clean = str(value or "").strip().lower()
    return _VERDICT_ALIASES.get(clean, clean)


def _session_root(
    *,
    ticket_id: str,
    profile_id: str,
    session_id: str,
    workspace: Path | str | None,
    output_root: Path | str | None = None,
) -> Path:
    base = Path(output_root).resolve() if output_root is not None else operator_ui_root(_workspace(workspace)) / "manual-reviews"
    return base / _slug(ticket_id) / _slug(profile_id) / _slug(session_id)


def _default_session_id(profile_id: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{_slug(profile_id)}-{stamp}-{uuid.uuid4().hex[:8]}"


def _summarize_steps(steps: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {
        "total_steps": len(steps),
        "recorded_steps": 0,
        "pending_steps": 0,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "incomplete": 0,
    }
    for step in steps:
        verdict = _normalize_verdict(step.get("verdict", _PENDING_VERDICT))
        if verdict == _PENDING_VERDICT:
            counts["pending_steps"] += 1
            continue
        counts["recorded_steps"] += 1
        if verdict in counts:
            counts[verdict] += 1
    return counts


def _write_session(session: dict[str, Any]) -> dict[str, Any]:
    summary = _summarize_steps(list(session.get("steps", [])))
    session["summary"] = summary
    session["status"] = "recorded" if summary.get("recorded_steps", 0) else _PENDING_VERDICT
    path = Path(str(session["session_path"]))
    ensure_parent(path)
    markdown_path = path.with_name("manual-review-summary.md")
    session["markdown_path"] = str(markdown_path)
    markdown_path.write_text(render_manual_review_markdown(session), encoding="utf-8")
    path.write_text(json.dumps(session, indent=2, ensure_ascii=False), encoding="utf-8")
    return session


def create_manual_review_session(
    *,
    profile_id: str,
    ticket_id: str,
    workspace: Path | str | None = None,
    output_root: Path | str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    clean_profile = profile_id.strip()
    clean_ticket = ticket_id.strip()
    if not clean_profile:
        raise ValueError("profile_id is required")
    if not clean_ticket:
        raise ValueError("ticket_id is required")
    clean_session = (session_id or _default_session_id(clean_profile)).strip()
    session_path_slug = _slug(clean_session)
    root = _session_root(
        ticket_id=clean_ticket,
        profile_id=clean_profile,
        session_id=session_path_slug,
        workspace=workspace,
        output_root=output_root,
    )
    session = {
        "schema_version": 1,
        "session_id": clean_session,
        "ticket_id": clean_ticket,
        "profile_id": clean_profile,
        "status": _PENDING_VERDICT,
        "created_at_utc": utc_now(),
        "updated_at_utc": utc_now(),
        "source": _CONFLUENCE_SOURCE,
        "header": MANUAL_REVIEW_HEADER,
        "session_root": str(root),
        "session_path": str(root / _SESSION_FILENAME),
        "markdown_path": str(root / "manual-review-summary.md"),
        "steps": [step.to_session_step() for step in QUALITY_HERO_STEPS],
    }
    return _write_session(session)


def _candidate_session_paths(session_id_or_path: str | Path, workspace: Path | str | None) -> list[Path]:
    raw = Path(str(session_id_or_path))
    if raw.exists():
        return [raw if raw.is_file() else raw / _SESSION_FILENAME]
    root = operator_ui_root(_workspace(workspace)) / "manual-reviews"
    if not root.exists():
        return []
    session_slug = _slug(str(session_id_or_path))
    return sorted(root.glob(f"*/*/{session_slug}/{_SESSION_FILENAME}"))


def load_manual_review_session(session_id_or_path: str | Path, *, workspace: Path | str | None = None) -> dict[str, Any]:
    matches = [path for path in _candidate_session_paths(session_id_or_path, workspace) if path.is_file()]
    if not matches:
        raise FileNotFoundError(f"No manual review session found for {session_id_or_path}")
    if len(matches) > 1:
        raise ValueError(f"Manual review session id is ambiguous: {session_id_or_path}")
    payload = json.loads(matches[0].read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Manual review session is not a JSON object: {matches[0]}")
    return payload


def _find_step(session: dict[str, Any], step_slug: str) -> dict[str, Any]:
    clean_slug = _slug(step_slug)
    for step in session.get("steps", []):
        if isinstance(step, dict) and str(step.get("slug", "")).strip() == clean_slug:
            return step
    raise KeyError(f"Unknown manual review step: {step_slug}")


def record_manual_review_step(
    session_id_or_path: str | Path,
    step_slug: str,
    verdict: str,
    *,
    workspace: Path | str | None = None,
    note: str = "",
    screenshot: Path | str | None = None,
    suggested_verdict: str = "",
) -> dict[str, Any]:
    clean_verdict = verdict.strip().lower()
    clean_verdict = _normalize_verdict(clean_verdict)
    if clean_verdict not in VALID_VERDICTS:
        raise ValueError(f"Unsupported manual review verdict: {verdict}")
    session = load_manual_review_session(session_id_or_path, workspace=workspace)
    step = _find_step(session, step_slug)
    screenshot_path = ""
    if screenshot is not None and str(screenshot).strip():
        candidate = Path(screenshot).resolve()
        if not candidate.is_file():
            raise FileNotFoundError(f"Manual review screenshot does not exist: {candidate}")
        screenshot_path = str(candidate)
    step["verdict"] = clean_verdict
    clean_suggestion = _normalize_verdict(suggested_verdict)
    if clean_suggestion in VALID_VERDICTS:
        step["suggested_verdict"] = clean_suggestion
    step["operator_verdict"] = clean_verdict
    step["note"] = note.strip()
    step["screenshot_path"] = screenshot_path
    step["recorded_at_utc"] = utc_now()
    step["recorded_by_tool"] = False
    session["updated_at_utc"] = utc_now()
    return _write_session(session)


def _step_markdown(step: dict[str, Any]) -> list[str]:
    title = str(step.get("title", "")).strip()
    slug = str(step.get("slug", "")).strip()
    verdict = _normalize_verdict(step.get("verdict", _PENDING_VERDICT)) or _PENDING_VERDICT
    lines = [f"### {title}", f"- Step: `{slug}`", f"- Verdict: [{verdict}]"]
    review_focus = _string_list(step.get("review_focus", []))
    if review_focus:
        lines.append("- Review focus: " + ", ".join(review_focus))
    evidence_prompt = str(step.get("evidence_prompt", "")).strip()
    if evidence_prompt:
        lines.append(f"- Evidence prompt: {evidence_prompt}")
    review_focus_note = str(step.get("review_focus_note", "")).strip()
    if review_focus_note:
        lines.append(f"- Review focus note: {review_focus_note}")
    suggested = _normalize_verdict(step.get("suggested_verdict", ""))
    if suggested in VALID_VERDICTS:
        lines.append(f"- Suggested verdict: [{suggested}]")
        reason = str(step.get("suggestion_reason", "")).strip()
        if reason:
            lines.append(f"- Suggestion reason: {reason}")
    evidence_status = str(step.get("evidence_status", "")).strip()
    if evidence_status in {_EVIDENCE_AVAILABLE, _EVIDENCE_MISSING}:
        lines.append(f"- Evidence status: `{evidence_status}`")
        reason = str(step.get("suggestion_reason", "")).strip()
        if reason:
            lines.append(f"- Evidence note: {reason}")
        lines.append("- Manual review required: yes")
    operator_verdict = _normalize_verdict(step.get("operator_verdict", ""))
    if operator_verdict in VALID_VERDICTS:
        lines.append(f"- Operator verdict: [{operator_verdict}]")
    if step.get("note"):
        lines.append(f"- Reviewer note: {step['note']}")
    if step.get("screenshot_path"):
        lines.append(f"- Screenshot: `{step['screenshot_path']}`")
    guidance = step.get("guidance", [])
    if isinstance(guidance, list) and guidance:
        lines.append("- Guidance:")
        lines.extend(f"  - {item}" for item in guidance if str(item).strip())
    return lines


def _string_list(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(item).strip() for item in values if str(item).strip()]


def render_manual_review_markdown(session: dict[str, Any]) -> str:
    lines = [
        f"# Manual review session - {session.get('ticket_id', '')} / {session.get('profile_id', '')}",
        "",
        MANUAL_REVIEW_HEADER,
        "",
        f"- Session: `{session.get('session_id', '')}`",
        f"- Status: `{session.get('status', 'in_progress')}`",
        f"- Source: `{session.get('source', _CONFLUENCE_SOURCE)}`",
        "- Manual RaCo / Blender / screenshot review remains required.",
        "",
        "## Summary",
    ]
    summary = session.get("summary", {}) if isinstance(session.get("summary", {}), dict) else {}
    lines.extend(
        [
            f"- Recorded steps: {summary.get('recorded_steps', 0)}/{summary.get('total_steps', 0)}",
            f"- Not-run steps: {summary.get('pending_steps', 0)}",
            "",
            "## Steps",
        ]
    )
    for step in session.get("steps", []):
        if isinstance(step, dict):
            lines.extend(_step_markdown(step))
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _manual_review_root(workspace: Path | str | None) -> Path:
    return operator_ui_root(_workspace(workspace)) / "manual-reviews"


def list_manual_review_sessions(
    *,
    workspace: Path | str | None = None,
    ticket_id: str | None = None,
) -> list[dict[str, Any]]:
    root = _manual_review_root(workspace)
    if not root.exists():
        return []
    sessions: list[dict[str, Any]] = []
    for path in sorted(root.glob("*/*/*/session.json")):
        try:
            session = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(session, dict):
            continue
        if ticket_id and str(session.get("ticket_id", "")).strip().casefold() != ticket_id.strip().casefold():
            continue
        sessions.append(session)
    return sessions


def manual_review_digest_items(
    *,
    workspace: Path | str | None = None,
    ticket_id: str | None = None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for session in list_manual_review_sessions(workspace=workspace, ticket_id=ticket_id):
        pending = [
            step for step in session.get("steps", [])
            if isinstance(step, dict) and str(step.get("verdict", _PENDING_VERDICT)).strip() == _PENDING_VERDICT
        ]
        for step in pending:
            review_focus = _string_list(step.get("review_focus", []))
            review_focus_detail = f" Review focus: {', '.join(review_focus)}." if review_focus else ""
            items.append(
                {
                    "label": f"{session.get('profile_id', '')} {session.get('session_id', '')} {step.get('slug', '')}".strip(),
                    "status": "not_run",
                    "detail": (
                        f"Operator verdict required for {step.get('title', step.get('slug', 'manual review step'))}."
                        f"{review_focus_detail}"
                    ),
                    "session_id": str(session.get("session_id", "")),
                    "step_slug": str(step.get("slug", "")),
                    "path": str(session.get("session_path", "")),
                    "review_focus": review_focus,
                    "evidence_prompt": str(step.get("evidence_prompt", "")).strip(),
                    "note": f"{REVIEW_FOCUS_NOTE} Manual review companion only; not a tool-generated verdict.",
                }
            )
    return items


def _status_item(key: str, workspace: Path | str | None) -> dict[str, str]:
    statuses = prerequisite_status(_workspace(workspace))
    for item in statuses:
        if item.get("key") == key:
            return item
    return {"status": "missing", "path": "", "detail": ""}


def open_manual_review_tool(
    session_id_or_path: str | Path,
    step_slug: str,
    *,
    tool: str,
    workspace: Path | str | None = None,
    launch: bool = True,
) -> dict[str, Any]:
    session = load_manual_review_session(session_id_or_path, workspace=workspace)
    step = _find_step(session, step_slug)
    normalized_tool = tool.strip().lower()
    if normalized_tool not in {"raco", "blender"}:
        raise ValueError(f"Unsupported manual review tool: {tool}")
    status_key = "raco_gui" if normalized_tool == "raco" else "blender_executable"
    status = _status_item(status_key, workspace)
    if str(status.get("status", "")).strip().lower() != "available":
        label = "Ramses Composer / RaCo" if normalized_tool == "raco" else "Blender"
        raise RuntimeError(f"{label} is not configured for manual review launching.")
    executable = Path(str(status.get("path", ""))).resolve()
    command = [str(executable)]
    if launch:
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **hidden_subprocess_kwargs())
    return {
        "session_id": session["session_id"],
        "step": {
            "slug": str(step.get("slug", "")),
            "title": str(step.get("title", "")),
            "verdict": str(step.get("verdict", _PENDING_VERDICT)),
        },
        "tool": normalized_tool,
        "status": "launched" if launch else "ready",
        "command": command,
    }
