"""Persists operator-action runs on disk: ActionRecord build/save/load, progress events, and manual evidence attachments."""

from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sg_preflight.qa_operator_actions import OperatorAction, operator_ui_actions_root
from sg_preflight.services import build_progress_payload, utc_now, workspace_root, write_json_file

ACTION_PROGRESS_PLANS: dict[str, tuple[tuple[str, str], ...]] = {
    "sgfx_preflight": (
        ("queued", "Queued"),
        ("preflight", "Run local QA checks"),
        ("finalize", "Finalize action record"),
    ),
    "daily_live_matrix": (
        ("queued", "Queued"),
        ("profiles", "Run live profiles"),
        ("finalize", "Finalize shared summary"),
    ),
    "profile_stack": (
        ("queued", "Queued"),
        ("preflight", "Run standard preflight"),
        ("repo_checker", "Run repo checker"),
        ("unused_resources", "Run unused resource scan"),
        ("scene_check", "Run scene check"),
        ("delivery_checklist", "Check delivery checklist readiness"),
        ("bmw_smoke", "Check BMW smoke readiness"),
        ("finalize", "Finalize action record"),
    ),
    "repo_checker": (
        ("queued", "Queued"),
        ("style", "Run style checker"),
        ("execute", "Run checker"),
        ("parse", "Parse checker output"),
        ("finalize", "Finalize action record"),
    ),
    "bmw_screenshot_smoke": (
        ("queued", "Queued"),
        ("interface", "Run BMW interface smoke"),
        ("export", "Run BMW export"),
        ("screenshots", "Run BMW screenshots"),
        ("finalize", "Finalize action record"),
    ),
    "scene_check": (
        ("queued", "Queued"),
        ("discover", "Discover scenes"),
        ("execute", "Run scene checks"),
        ("finalize", "Finalize action record"),
    ),
    "unused_resources": (
        ("queued", "Queued"),
        ("execute", "Run scan"),
        ("parse", "Parse scan output"),
        ("finalize", "Finalize action record"),
    ),
    "delivery_checklist": (
        ("queued", "Queued"),
        ("inspect", "Inspect checklist bridge"),
        ("summarize", "Summarize readiness"),
        ("finalize", "Finalize action record"),
    ),
}

@dataclass
class ActionRecord:
    run_id: str
    action_id: str
    label: str
    kind: str
    scope: str
    status: str
    created_at_utc: str
    started_at_utc: str | None
    completed_at_utc: str | None
    workspace_root: str
    profile_id: str = ""
    project_root: str = ""
    command_preview: str = ""
    blocker_message: str = ""
    error_message: str = ""
    exit_code: int | None = None
    paths: dict[str, str] = field(default_factory=dict)
    artifacts: list[dict[str, str]] = field(default_factory=list)
    manual_evidence: list[dict[str, str]] = field(default_factory=list)
    summary: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)
    progress: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "run_id": self.run_id,
            "action_id": self.action_id,
            "label": self.label,
            "kind": self.kind,
            "scope": self.scope,
            "status": self.status,
            "created_at_utc": self.created_at_utc,
            "started_at_utc": self.started_at_utc,
            "completed_at_utc": self.completed_at_utc,
            "workspace_root": self.workspace_root,
            "profile_id": self.profile_id,
            "project_root": self.project_root,
            "command_preview": self.command_preview,
            "blocker_message": self.blocker_message,
            "error_message": self.error_message,
            "exit_code": self.exit_code,
            "paths": dict(self.paths),
            "artifacts": [dict(item) for item in self.artifacts],
            "manual_evidence": [dict(item) for item in self.manual_evidence],
            "summary": self.summary,
            "notes": list(self.notes),
            "progress": dict(self.progress) if isinstance(self.progress, dict) else None,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ActionRecord":
        artifacts = payload.get("artifacts", [])
        return cls(
            run_id=str(payload.get("run_id", "")),
            action_id=str(payload.get("action_id", "")),
            label=str(payload.get("label", "")),
            kind=str(payload.get("kind", "")),
            scope=str(payload.get("scope", "")),
            status=str(payload.get("status", "")),
            created_at_utc=str(payload.get("created_at_utc", "")),
            started_at_utc=payload.get("started_at_utc"),
            completed_at_utc=payload.get("completed_at_utc"),
            workspace_root=str(payload.get("workspace_root", "")),
            profile_id=str(payload.get("profile_id", "")),
            project_root=str(payload.get("project_root", "")),
            command_preview=str(payload.get("command_preview", "")),
            blocker_message=str(payload.get("blocker_message", "")),
            error_message=str(payload.get("error_message", "")),
            exit_code=payload.get("exit_code"),
            paths=dict(payload.get("paths", {}))
            if isinstance(payload.get("paths"), dict)
            else {},
            artifacts=[dict(item) for item in artifacts if isinstance(item, dict)],
            manual_evidence=[dict(item) for item in payload.get("manual_evidence", []) if isinstance(item, dict)],
            summary=payload.get("summary") if isinstance(payload.get("summary"), dict) else None,
            notes=[str(item) for item in payload.get("notes", []) if item],
            progress=dict(payload.get("progress", {}))
            if isinstance(payload.get("progress"), dict)
            else None,
        )

def _default_action_run_id(action_id: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{action_id.lower()}-{uuid.uuid4().hex[:6]}"

def build_action_record(action: OperatorAction, workspace: Path | None = None) -> ActionRecord:
    root = workspace_root(workspace)
    run_id = _default_action_run_id(action.action_id)
    output_root = operator_ui_actions_root(root) / run_id
    return ActionRecord(
        run_id=run_id,
        action_id=action.action_id,
        label=action.label,
        kind=action.kind,
        scope=action.scope,
        status="queued",
        created_at_utc=utc_now(),
        started_at_utc=None,
        completed_at_utc=None,
        workspace_root=str(root),
        profile_id=action.profile_id,
        project_root=action.project_root,
        command_preview=action.command_preview,
        blocker_message=action.blocker_message,
        paths={
            "output_root": str(output_root),
            "run_record": str(output_root / "action.json"),
            "action_record": str(output_root / "action.json"),
            "log": str(output_root / "action.log"),
            "summary_json": str(output_root / "summary.json"),
            "summary_md": str(output_root / "summary.md"),
            "xlsx_report": str(output_root / "scene-check.xlsx"),
            "manual_evidence_root": str(output_root / "manual-evidence"),
            "manual_evidence_index": str(output_root / "manual-evidence" / "attachments.json"),
        },
    )

def save_action_record(record: ActionRecord) -> None:
    write_json_file(Path(record.paths["run_record"]), record.to_dict())

def _manual_evidence_root(record: ActionRecord) -> Path:
    configured = str(record.paths.get("manual_evidence_root", "")).strip()
    if configured:
        return Path(configured)
    return Path(record.paths["output_root"]) / "manual-evidence"

def _manual_evidence_index_path(record: ActionRecord) -> Path:
    configured = str(record.paths.get("manual_evidence_index", "")).strip()
    if configured:
        return Path(configured)
    return _manual_evidence_root(record) / "attachments.json"

def _manual_evidence_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9._-]+", "-", value.strip().lower())
    slug = slug.strip("-._")
    return slug or "manual-evidence"

def _manual_evidence_default_label(kind: str, source_path: Path | None = None) -> str:
    if kind == "screenshot":
        return "Local manual screenshot evidence"
    if kind == "blender_note":
        return "Blender review note"
    if kind == "raco_note":
        return "RaCo review note"
    if kind == "visual_review_checklist":
        return "Visual review checklist"
    if kind == "verification_note":
        return "Manual verification note"
    if kind == "external_file" and source_path is not None:
        return source_path.name
    return "Manual evidence"

def _manual_evidence_default_note(kind: str, label: str) -> str:
    templates = {
        "blender_note": (
            f"{label}\n\n"
            "- Area checked:\n"
            "- What matched in Blender:\n"
            "- What still needs SG / RaCo follow-up:\n"
        ),
        "raco_note": (
            f"{label}\n\n"
            "- Scene checked:\n"
            "- What matched in RaCo:\n"
            "- What still needs SG follow-up:\n"
        ),
        "visual_review_checklist": (
            f"{label}\n\n"
            "- Project changelog reviewed: [ ]\n"
            "- Screenshot baseline set reviewed: [ ]\n"
            "- Blender scene opened: [ ]\n"
            "- RaCo scene opened: [ ]\n"
            "- Blender vs RaCo compared: [ ]\n"
            "- Key camera / perspective checked: [ ]\n"
            "- Screenshot captured: [ ]\n"
            "- Constants / README notes checked: [ ]\n"
            "- Finding documented: [ ]\n"
            "- Notes:\n"
        ),
        "verification_note": (
            f"{label}\n\n"
            "- What was verified:\n"
            "- Result:\n"
            "- Remaining blocker or follow-up:\n"
        ),
    }
    return templates.get(kind, f"{label}\n")

def _manual_evidence_target_path(record: ActionRecord, kind: str, label: str, source_path: Path | None = None) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = source_path.suffix if source_path is not None and source_path.suffix else ".md"
    basename = f"{stamp}-{_manual_evidence_slug(kind)}-{_manual_evidence_slug(label)}-{uuid.uuid4().hex[:6]}{suffix}"
    return _manual_evidence_root(record) / basename

def _write_manual_evidence_index(record: ActionRecord) -> None:
    write_json_file(
        _manual_evidence_index_path(record),
        {
            "schema_version": 1,
            "run_id": record.run_id,
            "items": [dict(item) for item in record.manual_evidence],
        },
    )

def attach_manual_evidence(
    run_id_or_path: str | Path,
    workspace: Path | None = None,
    *,
    kind: str,
    label: str = "",
    source_path: str = "",
    note: str = "",
) -> dict[str, str]:
    root = workspace_root(workspace)
    record = load_action_record(run_id_or_path, root)
    source = Path(source_path).expanduser() if source_path.strip() else None
    if source is not None and not source.exists():
        raise FileNotFoundError(f"Manual evidence source was not found: {source}")

    manual_root = _manual_evidence_root(record)
    manual_root.mkdir(parents=True, exist_ok=True)

    resolved_label = label.strip() or _manual_evidence_default_label(kind, source)
    resolved_note = note.strip()
    target_path = _manual_evidence_target_path(record, kind, resolved_label, source)

    if kind in {"blender_note", "raco_note", "visual_review_checklist", "verification_note"}:
        text = resolved_note or _manual_evidence_default_note(kind, resolved_label)
        target_path.write_text(text.strip() + "\n", encoding="utf-8")
        resolved_note = text.strip()
    elif source is not None:
        source_resolved = source.resolve()
        target_resolved = target_path.resolve()
        if source_resolved != target_resolved:
            shutil.copy2(source_resolved, target_resolved)
        else:
            target_path = source_resolved
    else:
        raise ValueError("Manual evidence attachment requires a source file or a note-based kind.")

    entry = {
        "id": uuid.uuid4().hex,
        "kind": kind.strip(),
        "label": resolved_label,
        "path": str(target_path),
        "note": resolved_note,
        "source_path": str(source.resolve()) if source is not None else "",
        "created_at_utc": utc_now(),
    }
    record.manual_evidence.append(entry)
    record.artifacts.append(_artifact(resolved_label, target_path))
    _write_manual_evidence_index(record)
    save_action_record(record)
    return entry

def _progress_event(
    step_key: str,
    label: str,
    detail: str = "",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "timestamp_utc": utc_now(),
        "step_key": step_key,
        "label": label,
        "detail": detail,
    }
    if meta:
        payload["meta"] = dict(meta)
    return payload

def _merged_progress_events(
    existing: dict[str, Any] | None,
    *,
    step_key: str,
    label: str,
    detail: str = "",
    meta: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    raw_events = existing.get("events", []) if isinstance(existing, dict) else []
    events = [dict(item) for item in raw_events if isinstance(item, dict)]
    if (
        not events
        or events[-1].get("step_key") != step_key
        or events[-1].get("label") != label
        or events[-1].get("detail") != detail
        or (
            isinstance(meta, dict)
            and dict(events[-1].get("meta", {})) != dict(meta)
        )
    ):
        events.append(_progress_event(step_key, label, detail, meta))
    return events[-60:]

def _set_action_progress(
    record: ActionRecord,
    *,
    step_key: str,
    percent: int,
    label: str,
    detail: str = "",
    meta: dict[str, Any] | None = None,
) -> None:
    plan = ACTION_PROGRESS_PLANS.get(record.kind, (("queued", "Queued"), ("finalize", "Finalize action record")))
    events = _merged_progress_events(
        record.progress,
        step_key=step_key,
        label=label,
        detail=detail,
        meta=meta,
    )
    record.progress = build_progress_payload(
        plan,
        step_key=step_key,
        percent=percent,
        label=label,
        detail=detail,
        events=events,
    )
    save_action_record(record)

def load_action_record(path_or_run_id: str | Path, workspace: Path | None = None) -> ActionRecord:
    candidate = Path(path_or_run_id)
    if candidate.exists():
        record_path = candidate if candidate.is_file() else candidate / "action.json"
    else:
        record_path = operator_ui_actions_root(workspace) / str(path_or_run_id) / "action.json"
    payload = json.loads(record_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Action record must contain a JSON object: {record_path}")
    return ActionRecord.from_dict(payload)

def list_recent_action_records(workspace: Path | None = None, limit: int = 12) -> list[ActionRecord]:
    records: list[ActionRecord] = []
    actions_root = operator_ui_actions_root(workspace)
    if not actions_root.exists():
        return records

    for path in actions_root.iterdir():
        record_path = path / "action.json"
        if not record_path.exists():
            continue
        try:
            records.append(load_action_record(record_path, workspace))
        except (OSError, ValueError, json.JSONDecodeError):
            continue

    records.sort(key=lambda item: item.created_at_utc, reverse=True)
    return records[:limit]

def _artifact(label: str, path: Path) -> dict[str, str]:
    return {"label": label, "path": str(path)}
