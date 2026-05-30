from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import uuid
from typing import Any


OPERATOR_HANDOFF_TITLE = "Operator Handoff"
OPERATOR_HANDOFF_NOTE = (
    "Operator handoff is local-only shift context. It records the stopping point and next suggested step."
)
OPERATOR_HANDOFF_GUARDRAILS = (
    "Manual review remains required.",
    "Decision: not approval — evidence only.",
    "BMW Git access is read-only. SGFX never modifies BMW source.",
    "Activity log is local-only — never posted to Jira, SVN, or BMW Git.",
)
_FORBIDDEN_TEXT = (
    "approv" + "ed",
    "clear" + "ed",
    "signed-" + "off",
    "production-" + "ready",
    "validat" + "ed",
    "verifi" + "ed",
)


def operator_handoff_path(workspace: Path | str) -> Path:
    return Path(workspace).resolve() / "operator_state" / "operator_handoffs.jsonl"


def _utc_now(value: datetime | None = None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_ts(value: object) -> datetime:
    try:
        return datetime.fromisoformat(str(value or "").replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def _clean_profile(value: str) -> str:
    return str(value or "").strip().upper() or "PROFILE"


def _clean_text(value: str, *, field: str, required: bool = False) -> str:
    text = " ".join(str(value or "").strip().split())
    if required and not text:
        raise ValueError(f"{field} is required")
    folded = text.casefold()
    if any(token in folded for token in _FORBIDDEN_TEXT):
        raise ValueError(f"{field} must stay evidence-only and avoid approval wording")
    return text


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            entries.append(payload)
    return entries


def record_operator_handoff(
    *,
    workspace: Path | str,
    profile_id: str,
    ticket_id: str = "",
    stopping_point: str,
    next_step: str = "",
    note: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    root = Path(workspace).resolve()
    timestamp = _utc_now(now)
    profile = _clean_profile(profile_id)
    record = {
        "handoff_id": f"handoff-{timestamp.replace(':', '').replace('-', '').lower()}-{uuid.uuid4().hex[:8]}",
        "created_at_utc": timestamp,
        "profile_id": profile,
        "ticket_id": _clean_text(ticket_id, field="ticket_id"),
        "stopping_point": _clean_text(stopping_point, field="stopping_point", required=True),
        "next_step": _clean_text(next_step, field="next_step"),
        "note": _clean_text(note, field="note"),
        "status": "recorded",
        "manual_review_required": True,
        "is_approval": False,
    }
    path = operator_handoff_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return record


def list_operator_handoffs(
    *,
    workspace: Path | str,
    profile_id: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    profile = str(profile_id or "").strip().upper()
    entries = _read_jsonl(operator_handoff_path(workspace))
    if profile:
        entries = [entry for entry in entries if str(entry.get("profile_id", "")).upper() == profile]
    entries.sort(key=lambda entry: _parse_ts(entry.get("created_at_utc")), reverse=True)
    return entries[: max(1, limit)]


def latest_operator_handoff(*, workspace: Path | str, profile_id: str = "") -> dict[str, Any] | None:
    entries = list_operator_handoffs(workspace=workspace, profile_id=profile_id, limit=1)
    return entries[0] if entries else None


def build_operator_handoff_snapshot(
    *,
    workspace: Path | str | None = None,
    profile_id: str = "",
) -> dict[str, Any]:
    root = Path(workspace).resolve() if workspace is not None else Path.cwd()
    profile = _clean_profile(profile_id)
    entries = list_operator_handoffs(workspace=root, profile_id=profile, limit=12)
    latest = entries[0] if entries else {}
    handoff_items: list[dict[str, str]] = []
    if latest:
        handoff_items.extend(
            [
                {
                    "label": "Stopping point",
                    "status": "recorded",
                    "detail": str(latest.get("stopping_point", "")),
                },
                {
                    "label": "Next step",
                    "status": "recorded" if latest.get("next_step") else "not_run",
                    "detail": str(latest.get("next_step", "")) or "No next step recorded.",
                },
                {
                    "label": "Ticket",
                    "status": "recorded" if latest.get("ticket_id") else "not_run",
                    "detail": str(latest.get("ticket_id", "")) or "No ticket recorded.",
                },
            ]
        )
    status = "recorded" if latest else "not_run"
    summary = (
        f"Latest handoff for {profile}: {latest.get('stopping_point', '')}"
        if latest
        else f"No local handoff recorded for {profile}."
    )
    payload = {
        "title": OPERATOR_HANDOFF_TITLE,
        "status": status,
        "data_available": bool(latest),
        "workspace": str(root),
        "profile_id": profile,
        "handoff_count": len(entries),
        "latest_handoff": latest,
        "handoff_items": handoff_items,
        "summary": summary,
        "guardrails": list(OPERATOR_HANDOFF_GUARDRAILS),
        "manual_review_required": True,
        "is_approval": False,
        "note": OPERATOR_HANDOFF_NOTE,
        "path": str(operator_handoff_path(root)),
    }
    payload["text"] = render_operator_handoff_text(payload)
    payload["markdown"] = render_operator_handoff_markdown(payload)
    return payload


def render_operator_handoff_text(payload: dict[str, Any]) -> str:
    latest = payload.get("latest_handoff", {}) if isinstance(payload.get("latest_handoff"), dict) else {}
    lines = [
        str(payload.get("title", OPERATOR_HANDOFF_TITLE)),
        f"Status: {payload.get('status', 'unknown')}",
        f"Profile: {payload.get('profile_id', '')}",
        str(payload.get("summary", "")),
        "Manual review remains required. Decision: not approval — evidence only.",
    ]
    if latest:
        lines.extend(
            [
                f"Stopping point: {latest.get('stopping_point', '')}",
                f"Next step: {latest.get('next_step', '')}",
                f"Note: {latest.get('note', '')}",
            ]
        )
    return "\n".join(lines)


def render_operator_handoff_markdown(payload: dict[str, Any]) -> str:
    latest = payload.get("latest_handoff", {}) if isinstance(payload.get("latest_handoff"), dict) else {}
    lines = [
        f"# {payload.get('title', OPERATOR_HANDOFF_TITLE)}",
        "",
        f"> {OPERATOR_HANDOFF_NOTE}",
        "",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- Profile: `{payload.get('profile_id', '')}`",
        f"- Local record count: `{payload.get('handoff_count', 0)}`",
        f"- Summary: {payload.get('summary', '')}",
    ]
    if latest:
        lines.extend(
            [
                "",
                "## Latest Handoff",
                "",
                f"- Stopping point: {latest.get('stopping_point', '')}",
                f"- Next step: {latest.get('next_step', '') or 'not_run'}",
                f"- Note: {latest.get('note', '') or 'not_run'}",
            ]
        )
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            *[f"- {guardrail}" for guardrail in payload.get("guardrails", OPERATOR_HANDOFF_GUARDRAILS)],
        ]
    )
    return "\n".join(lines).rstrip() + "\n"
