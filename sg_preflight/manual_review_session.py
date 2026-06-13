from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import uuid
from typing import Any

from sg_preflight.services import operator_ui_root, utc_now
from sg_preflight.utils import ensure_parent

from sg_preflight.manual_review_templates import (
    MANUAL_REVIEW_HEADER,
    REVIEW_FOCUS_NOTE,
    VALID_VERDICTS,
    _CONFLUENCE_SOURCE,
    _PENDING_VERDICT,
    _SESSION_FILENAME,
    _VERDICT_ALIASES,
    QUALITY_HERO_STEPS,
    _slug,
    _workspace,
    get_car_review_template,
    review_template_for_profile,
)


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
    from sg_preflight.manual_review import render_manual_review_markdown

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


def create_manual_review_session_from_template(
    *,
    profile_id: str,
    ticket_id: str,
    family_id: str = "",
    workspace: Path | str | None = None,
    output_root: Path | str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    template = (
        get_car_review_template(family_id)
        if str(family_id or "").strip()
        else review_template_for_profile(profile_id, workspace=workspace)
    )
    session = create_manual_review_session(
        profile_id=profile_id,
        ticket_id=ticket_id,
        workspace=workspace,
        output_root=output_root,
        session_id=session_id,
    )
    anchors = list(dict.fromkeys([_CONFLUENCE_SOURCE, *template.get("confluence_anchors", [])]))
    session["car_family_template"] = template
    session["family_id"] = str(template.get("family_id", ""))
    session["evidence_checklist"] = list(template.get("evidence_checklist", []))
    session["confluence_anchors"] = anchors
    session["manual_review_required"] = True
    session["is_approval"] = False
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


def _string_list(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(item).strip() for item in values if str(item).strip()]


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
