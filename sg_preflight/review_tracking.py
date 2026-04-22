from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

_DEFAULT_DECISION_STATUS = "pending"
_PENDING_DECISION_STATUSES = {"", "pending", "needs_more_investigation", "not_reviewed"}


def _workspace_root(workspace: Path | str | None = None) -> Path:
    root = Path(workspace) if workspace is not None else Path(__file__).resolve().parents[1]
    return root.resolve()


def _tracking_root(workspace: Path | str | None = None) -> Path:
    return _workspace_root(workspace) / "out" / "review-tracking"


def _ticket_tracking_root(ticket_id: str, workspace: Path | str | None = None) -> Path:
    return _tracking_root(workspace) / ticket_id.strip()


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _normalize_status(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    return normalized or _DEFAULT_DECISION_STATUS


def _decision_pending(status: str) -> bool:
    return _normalize_status(status) in _PENDING_DECISION_STATUSES


def parse_review_decisions_markdown(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            if current is not None:
                sections.append(current)
            title = line[3:].strip()
            current = {
                "key": _slug(title),
                "title": title,
                "status": _DEFAULT_DECISION_STATUS,
                "owner": "",
                "date": "",
                "notes": "",
                "pending": True,
                "raw_lines": [],
            }
            continue
        if current is None:
            continue
        current["raw_lines"].append(raw_line)
        if ":" not in raw_line:
            continue
        field, value = raw_line.split(":", 1)
        field_key = field.strip().lower()
        field_value = value.strip()
        if field_key in {"decision", "status"}:
            status = _normalize_status(field_value)
            if "/" in field_value:
                status = _DEFAULT_DECISION_STATUS
            current["status"] = status
            current["pending"] = _decision_pending(status)
        elif field_key == "owner":
            current["owner"] = field_value
        elif field_key == "date":
            current["date"] = field_value
        elif field_key == "notes":
            current["notes"] = field_value
    if current is not None:
        sections.append(current)
    return sections


def _default_decisions_payload(ticket_id: str, fallback_sections: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    decisions: list[dict[str, Any]] = []
    for section in fallback_sections or []:
        title = str(section.get("title", "")).strip()
        if not title:
            continue
        status = _normalize_status(str(section.get("status", "")).strip())
        if "/" in str(section.get("fields", {}).get("Decision", "")):
            status = _DEFAULT_DECISION_STATUS
        decisions.append(
            {
                "key": str(section.get("key", "")) or _slug(title),
                "title": title,
                "status": status,
                "owner": str(section.get("owner", "")).strip(),
                "date": str(section.get("date", "")).strip(),
                "notes": str(section.get("notes", "")).strip(),
                "pending": _decision_pending(status),
            }
        )
    return {
        "ticket_id": ticket_id,
        "updated_at": _now_iso(),
        "decisions": decisions,
    }


def _decision_json_path(ticket_id: str, workspace: Path | str | None = None) -> Path:
    return _ticket_tracking_root(ticket_id, workspace) / "review-owner-decisions.json"


def _decision_markdown_path(ticket_id: str, workspace: Path | str | None = None) -> Path:
    return _ticket_tracking_root(ticket_id, workspace) / "review-owner-decisions.md"


def render_review_decisions_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Review-owner decisions",
        "",
        f"- Ticket: `{payload.get('ticket_id', '')}`",
        f"- Updated: `{payload.get('updated_at', '')}`",
        "",
    ]
    decisions = payload.get("decisions", [])
    if not decisions:
        lines.append("No review-owner decisions recorded yet.")
        lines.append("")
        return "\n".join(lines)
    for item in decisions:
        lines.extend(
            [
                f"## {item.get('title', item.get('key', 'Decision'))}",
                f"Status: {item.get('status', _DEFAULT_DECISION_STATUS)}",
                f"Owner: {item.get('owner', '')}",
                f"Date: {item.get('date', '')}",
                f"Notes: {item.get('notes', '')}",
                "",
            ]
        )
    return "\n".join(lines)


def load_review_decisions(
    ticket_id: str,
    workspace: Path | str | None = None,
    *,
    fallback_markdown_path: Path | None = None,
) -> dict[str, Any]:
    json_path = _decision_json_path(ticket_id, workspace)
    markdown_path = _decision_markdown_path(ticket_id, workspace)
    if json_path.exists():
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    else:
        fallback_sections = parse_review_decisions_markdown(fallback_markdown_path) if fallback_markdown_path else []
        payload = _default_decisions_payload(ticket_id, fallback_sections)
        _write_json(json_path, payload)
        _write_text(markdown_path, render_review_decisions_markdown(payload))
    decisions = []
    for raw in payload.get("decisions", []):
        title = str(raw.get("title", "")).strip() or str(raw.get("key", "")).strip()
        if not title:
            continue
        status = _normalize_status(str(raw.get("status", "")).strip())
        decisions.append(
            {
                "key": str(raw.get("key", "")) or _slug(title),
                "title": title,
                "status": status,
                "owner": str(raw.get("owner", "")).strip(),
                "date": str(raw.get("date", "")).strip(),
                "notes": str(raw.get("notes", "")).strip(),
                "pending": _decision_pending(status),
            }
        )
    normalized = {
        "ticket_id": ticket_id,
        "updated_at": str(payload.get("updated_at", "")).strip() or _now_iso(),
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
        "decisions": decisions,
        "pending_count": sum(1 for item in decisions if item["pending"]),
    }
    if not markdown_path.exists():
        _write_text(markdown_path, render_review_decisions_markdown(normalized))
    return normalized


def set_review_decision(
    ticket_id: str,
    decision_key: str,
    *,
    status: str,
    owner: str = "",
    note: str = "",
    date: str = "",
    title: str = "",
    workspace: Path | str | None = None,
    fallback_markdown_path: Path | None = None,
) -> dict[str, Any]:
    payload = load_review_decisions(ticket_id, workspace, fallback_markdown_path=fallback_markdown_path)
    key = _slug(decision_key)
    decisions = list(payload["decisions"])
    resolved_title = title.strip() or decision_key.strip()
    updated = False
    for item in decisions:
        if item["key"] != key:
            continue
        item["title"] = resolved_title or item["title"]
        item["status"] = _normalize_status(status)
        item["owner"] = owner.strip()
        item["date"] = date.strip() or _now_iso().split("T", 1)[0]
        item["notes"] = note.strip()
        item["pending"] = _decision_pending(item["status"])
        updated = True
        break
    if not updated:
        normalized_status = _normalize_status(status)
        decisions.append(
            {
                "key": key,
                "title": resolved_title,
                "status": normalized_status,
                "owner": owner.strip(),
                "date": date.strip() or _now_iso().split("T", 1)[0],
                "notes": note.strip(),
                "pending": _decision_pending(normalized_status),
            }
        )
    normalized = {
        "ticket_id": ticket_id,
        "updated_at": _now_iso(),
        "json_path": payload["json_path"],
        "markdown_path": payload["markdown_path"],
        "decisions": decisions,
        "pending_count": sum(1 for item in decisions if item["pending"]),
    }
    json_path = Path(normalized["json_path"])
    markdown_path = Path(normalized["markdown_path"])
    _write_json(json_path, {k: normalized[k] for k in ("ticket_id", "updated_at", "decisions")})
    _write_text(markdown_path, render_review_decisions_markdown(normalized))
    return normalized


def _external_json_path(ticket_id: str, workspace: Path | str | None = None) -> Path:
    return _ticket_tracking_root(ticket_id, workspace) / "external-findings.json"


def _external_markdown_path(ticket_id: str, workspace: Path | str | None = None) -> Path:
    return _ticket_tracking_root(ticket_id, workspace) / "external-findings.md"


def render_external_findings_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# External Findings",
        "",
        f"- Ticket: `{payload.get('ticket_id', '')}`",
        f"- Updated: `{payload.get('updated_at', '')}`",
        "",
    ]
    findings = payload.get("findings", [])
    if not findings:
        lines.append("No external findings recorded yet.")
        lines.append("")
        return "\n".join(lines)
    for item in findings:
        scope = ", ".join(item.get("scope", [])) or "n/a"
        related = ", ".join(item.get("related_investigation_surfaces", []))
        lines.extend(
            [
                f"## {item.get('finding')}",
                f"Source: {item.get('source', '')}",
                f"Reported by: {item.get('reported_by', '')}",
                f"Type: {item.get('type', '')}",
                f"Category: {item.get('category', '')}",
                f"Scope: {scope}",
                f"Owner: {item.get('owner', '')}",
                f"Status: {item.get('status', '')}",
                f"Note: {item.get('note', '')}",
            ]
        )
        if related:
            lines.append(f"Related investigation surfaces: {related}")
        lines.append("")
    return "\n".join(lines)


def load_external_findings(ticket_id: str, workspace: Path | str | None = None) -> dict[str, Any]:
    json_path = _external_json_path(ticket_id, workspace)
    markdown_path = _external_markdown_path(ticket_id, workspace)
    if json_path.exists():
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    else:
        payload = {
            "ticket_id": ticket_id,
            "updated_at": "",
            "findings": [],
        }
    findings = []
    for raw in payload.get("findings", []):
        finding_text = str(raw.get("finding", "")).strip()
        if not finding_text:
            continue
        findings.append(
            {
                "finding_id": str(raw.get("finding_id", "")) or _slug(f"{finding_text}-{','.join(raw.get('scope', []))}"),
                "source": str(raw.get("source", "")).strip(),
                "reported_by": str(raw.get("reported_by", "")).strip(),
                "type": str(raw.get("type", "")).strip() or "finding",
                "category": str(raw.get("category", "")).strip(),
                "scope": [str(item).strip() for item in raw.get("scope", []) if str(item).strip()],
                "finding": finding_text,
                "owner": str(raw.get("owner", "")).strip(),
                "status": str(raw.get("status", "")).strip() or "reported",
                "note": str(raw.get("note", "")).strip(),
                "related_investigation_surfaces": [
                    str(item).strip()
                    for item in raw.get("related_investigation_surfaces", [])
                    if str(item).strip()
                ],
            }
        )
    normalized = {
        "ticket_id": ticket_id,
        "updated_at": str(payload.get("updated_at", "")).strip(),
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
        "findings": findings,
        "count": len(findings),
        "reported_count": sum(1 for item in findings if item["status"].strip().lower() == "reported"),
        "related_investigation_surfaces": sorted(
            {
                surface
                for item in findings
                for surface in item.get("related_investigation_surfaces", [])
            }
        ),
    }
    if findings and not markdown_path.exists():
        _write_text(markdown_path, render_external_findings_markdown(normalized))
    return normalized


def add_external_finding(
    ticket_id: str,
    *,
    source: str,
    reported_by: str,
    category: str,
    scope: list[str] | tuple[str, ...],
    finding: str,
    owner: str = "",
    status: str = "reported",
    note: str = "",
    finding_type: str = "finding",
    related_investigation_surfaces: list[str] | tuple[str, ...] = (),
    workspace: Path | str | None = None,
) -> dict[str, Any]:
    payload = load_external_findings(ticket_id, workspace)
    normalized_scope = [str(item).strip() for item in scope if str(item).strip()]
    normalized_surfaces = [str(item).strip() for item in related_investigation_surfaces if str(item).strip()]
    finding_id = _slug(f"{finding}-{','.join(normalized_scope)}-{owner}")
    findings = [item for item in payload["findings"] if item["finding_id"] != finding_id]
    findings.append(
        {
            "finding_id": finding_id,
            "source": source.strip(),
            "reported_by": reported_by.strip(),
            "type": finding_type.strip() or "finding",
            "category": category.strip(),
            "scope": normalized_scope,
            "finding": finding.strip(),
            "owner": owner.strip(),
            "status": status.strip() or "reported",
            "note": note.strip(),
            "related_investigation_surfaces": normalized_surfaces,
        }
    )
    findings.sort(key=lambda item: (",".join(item["scope"]), item["finding"].casefold(), item["owner"].casefold()))
    normalized = {
        "ticket_id": ticket_id,
        "updated_at": _now_iso(),
        "json_path": payload["json_path"],
        "markdown_path": payload["markdown_path"],
        "findings": findings,
        "count": len(findings),
        "reported_count": sum(1 for item in findings if item["status"].strip().lower() == "reported"),
        "related_investigation_surfaces": sorted(
            {
                surface
                for item in findings
                for surface in item.get("related_investigation_surfaces", [])
            }
        ),
    }
    json_path = Path(normalized["json_path"])
    markdown_path = Path(normalized["markdown_path"])
    _write_json(json_path, {k: normalized[k] for k in ("ticket_id", "updated_at", "findings")})
    _write_text(markdown_path, render_external_findings_markdown(normalized))
    return normalized
