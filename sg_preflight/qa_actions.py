from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import openpyxl

from sg_preflight.profiles import RunProfile, list_run_profiles
from sg_preflight.services import (
    RunRequest,
    build_progress_payload,
    execute_profile_run,
    prerequisite_status,
    utc_now,
    workspace_root,
    write_json_file,
)


ACTION_PROGRESS_PLANS: dict[str, tuple[tuple[str, str], ...]] = {
    "daily_live_matrix": (
        ("queued", "Queued"),
        ("profiles", "Run live profiles"),
        ("finalize", "Finalize shared summary"),
    ),
    "profile_stack": (
        ("queued", "Queued"),
        ("preflight", "Run standard preflight"),
        ("repo_checker", "Run repo checker"),
        ("scene_check", "Run scene check"),
        ("bmw_smoke", "Check BMW smoke readiness"),
        ("finalize", "Finalize action record"),
    ),
    "repo_checker": (
        ("queued", "Queued"),
        ("execute", "Run checker"),
        ("parse", "Parse checker output"),
        ("finalize", "Finalize action record"),
    ),
    "bmw_screenshot_smoke": (
        ("queued", "Queued"),
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
}


def operator_ui_actions_root(explicit_root: Path | None = None) -> Path:
    return workspace_root(explicit_root) / "out" / "operator-ui" / "actions"


@dataclass(frozen=True)
class OperatorAction:
    action_id: str
    label: str
    description: str
    kind: str
    scope: str
    ready: bool
    blocker_message: str = ""
    profile_id: str = ""
    project_root: str = ""
    command_preview: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "label": self.label,
            "description": self.description,
            "kind": self.kind,
            "scope": self.scope,
            "ready": self.ready,
            "blocker_message": self.blocker_message,
            "profile_id": self.profile_id,
            "project_root": self.project_root,
            "command_preview": self.command_preview,
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
    paths: dict[str, str] = field(default_factory=dict)
    artifacts: list[dict[str, str]] = field(default_factory=list)
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
            "paths": dict(self.paths),
            "artifacts": [dict(item) for item in self.artifacts],
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
            paths=dict(payload.get("paths", {}))
            if isinstance(payload.get("paths"), dict)
            else {},
            artifacts=[dict(item) for item in artifacts if isinstance(item, dict)],
            summary=payload.get("summary") if isinstance(payload.get("summary"), dict) else None,
            notes=[str(item) for item in payload.get("notes", []) if item],
            progress=dict(payload.get("progress", {}))
            if isinstance(payload.get("progress"), dict)
            else None,
        )


def _status_map(root: Path) -> dict[str, dict[str, str]]:
    return {item["key"]: item for item in prerequisite_status(root)}


def _path_from_status(status_map: dict[str, dict[str, str]], key: str) -> Path:
    raw = status_map.get(key, {}).get("path", "")
    return Path(raw) if raw else Path()


def _bmw_smoke_script_path(status_map: dict[str, dict[str, str]], profile: RunProfile) -> Path:
    bmw_repo = _path_from_status(status_map, "bmw_models_repo")
    if not bmw_repo:
        return Path()
    return bmw_repo / "ci" / "scripts" / (profile.bmw_smoke_runner or "car_manager.py")


def _bmw_smoke_blocker_message(status_map: dict[str, dict[str, str]], profile: RunProfile) -> str:
    bmw_repo = _path_from_status(status_map, "bmw_models_repo")
    script_path = _bmw_smoke_script_path(status_map, profile)
    if not bmw_repo.exists():
        return "BMW screenshot smoke needs a local `digital-3d-car-models` clone from BMW Git."
    if not script_path.exists():
        return "BMW screenshot smoke needs the `ci/scripts/car_manager.py` helper in the BMW models repo."
    if not profile.bmw_smoke_target.strip():
        return f"No BMW screenshot-smoke target mapping is configured for {profile.profile_id} yet."
    return ""


def list_operator_actions(
    workspace: Path | None = None,
    *,
    profiles: list[RunProfile] | None = None,
) -> list[OperatorAction]:
    root = workspace_root(workspace)
    live_profiles = profiles or list_run_profiles(root)
    status_map = _status_map(root)
    mirror_root = root / "repositories" / "trunk"
    checker_script = mirror_root / ".pdx" / "checkers" / "executeChecks.py"
    scene_checker = mirror_root / "check_scenes.py"
    raco_headless = _path_from_status(status_map, "raco_headless")
    checker_ready = checker_script.exists()
    scene_ready = scene_checker.exists() and raco_headless.exists()

    actions = [
        OperatorAction(
            action_id="daily_live_matrix",
            label="Run Daily SG Check",
            description="Run the standard preflight across the configured live SG slices and write one shared summary.",
            kind="daily_live_matrix",
            scope="workspace",
            ready=bool(live_profiles),
            blocker_message="" if live_profiles else "No live SG profiles are configured on this machine.",
            command_preview="internal: run all configured live profiles with fail_on=never",
        ),
        OperatorAction(
            action_id="repo_checker_idcevo",
            label="Run IDCevo Repo Checkers",
            description="Run the SG checker stack over the mirrored `Cars_IDCevo` tree.",
            kind="repo_checker",
            scope="workspace",
            ready=checker_ready and (mirror_root / "Cars_IDCevo").exists(),
            blocker_message=(
                ""
                if checker_ready and (mirror_root / "Cars_IDCevo").exists()
                else "The mirrored checker stack or `Cars_IDCevo` tree is missing."
            ),
            command_preview=f"{sys.executable} {checker_script} {mirror_root / 'Cars_IDCevo'}",
        ),
        OperatorAction(
            action_id="repo_checker_classic",
            label="Run Classic Repo Checkers",
            description="Run the SG checker stack over the mirrored `Cars` tree.",
            kind="repo_checker",
            scope="workspace",
            ready=checker_ready and (mirror_root / "Cars").exists(),
            blocker_message=(
                ""
                if checker_ready and (mirror_root / "Cars").exists()
                else "The mirrored checker stack or `Cars` tree is missing."
            ),
            command_preview=f"{sys.executable} {checker_script} {mirror_root / 'Cars'}",
        ),
    ]

    for profile in live_profiles:
        actions.append(
            OperatorAction(
                action_id=f"qa_stack__{profile.profile_id.lower()}",
                label=f"Run Recommended QA Stack For {profile.profile_id}",
                description=(
                    f"Run the default preflight first, then every additional SG-side QA step that is available on this machine for {profile.profile_id}."
                ),
                kind="profile_stack",
                scope="profile",
                ready=profile.project_root.exists() and profile.config_path.exists(),
                blocker_message=(
                    ""
                    if profile.project_root.exists() and profile.config_path.exists()
                    else f"The project root or config for {profile.profile_id} is missing, so the recommended stack cannot start."
                ),
                profile_id=profile.profile_id,
                project_root=str(profile.project_root),
                command_preview=(
                    "internal: standard preflight + repo checker + scene check if available + BMW smoke readiness summary"
                ),
            )
        )
        actions.append(
            OperatorAction(
                action_id=f"repo_checker_profile__{profile.profile_id.lower()}",
                label=f"Run Repo Check For {profile.profile_id}",
                description=f"Run the SG checker stack only for the {profile.profile_id} project tree.",
                kind="repo_checker",
                scope="profile",
                ready=checker_ready and profile.project_root.exists(),
                blocker_message=(
                    ""
                    if checker_ready and profile.project_root.exists()
                    else f"The mirrored checker stack or project root for {profile.profile_id} is missing."
                ),
                profile_id=profile.profile_id,
                project_root=str(profile.project_root),
                command_preview=f"{sys.executable} {checker_script} {profile.project_root}",
            )
        )
        actions.append(
            OperatorAction(
                action_id=f"scene_check__{profile.profile_id.lower()}",
                label=f"Run Scene Check For {profile.profile_id}",
                description=f"Run SG scene checking over every `.rca` under the {profile.profile_id} project tree.",
                kind="scene_check",
                scope="profile",
                ready=scene_ready and profile.project_root.exists(),
                blocker_message=(
                    ""
                    if scene_ready and profile.project_root.exists()
                    else "Scene check needs both the mirrored `check_scenes.py` helper and a local `RaCoHeadless.exe`."
                ),
                profile_id=profile.profile_id,
                project_root=str(profile.project_root),
                command_preview=f"{sys.executable} {scene_checker} --raco {raco_headless} --dir {profile.project_root}",
            )
        )
        bmw_smoke_blocker = _bmw_smoke_blocker_message(status_map, profile)
        bmw_script = _bmw_smoke_script_path(status_map, profile)
        target = profile.bmw_smoke_target.strip()
        actions.append(
            OperatorAction(
                action_id=f"bmw_screenshot_smoke__{profile.profile_id.lower()}",
                label=f"Run BMW Screenshot Smoke For {profile.profile_id}",
                description=(
                    f"Run BMW-side export and screenshot smoke for {profile.profile_id} when the BMW models repo and car mapping are available."
                ),
                kind="bmw_screenshot_smoke",
                scope="profile",
                ready=not bmw_smoke_blocker,
                blocker_message=bmw_smoke_blocker,
                profile_id=profile.profile_id,
                project_root=str(profile.project_root),
                command_preview=(
                    f"{sys.executable} {bmw_script} export {target} && "
                    f"{sys.executable} {bmw_script} screenshots --diff {target}"
                    if target
                    else "BMW screenshot smoke target mapping is not configured yet."
                ),
            )
        )

    return actions


def get_operator_action(
    action_id: str,
    workspace: Path | None = None,
    *,
    profiles: list[RunProfile] | None = None,
) -> OperatorAction:
    normalized = action_id.strip().lower()
    for action in list_operator_actions(workspace, profiles=profiles):
        if action.action_id.lower() == normalized:
            return action
    supported = ", ".join(action.action_id for action in list_operator_actions(workspace, profiles=profiles))
    raise KeyError(f"Unsupported action {action_id!r}. Supported actions: {supported}")


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
            "log": str(output_root / "action.log"),
            "summary_json": str(output_root / "summary.json"),
            "summary_md": str(output_root / "summary.md"),
            "xlsx_report": str(output_root / "scene-check.xlsx"),
        },
    )


def save_action_record(record: ActionRecord) -> None:
    write_json_file(Path(record.paths["run_record"]), record.to_dict())


def _set_action_progress(
    record: ActionRecord,
    *,
    step_key: str,
    percent: int,
    label: str,
    detail: str = "",
) -> None:
    plan = ACTION_PROGRESS_PLANS.get(record.kind, (("queued", "Queued"), ("finalize", "Finalize action record")))
    record.progress = build_progress_payload(
        plan,
        step_key=step_key,
        percent=percent,
        label=label,
        detail=detail,
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


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _artifact(label: str, path: Path) -> dict[str, str]:
    return {"label": label, "path": str(path)}


def _nested_action_record(parent: ActionRecord, action: OperatorAction, slug: str) -> ActionRecord:
    output_root = Path(parent.paths["output_root"]) / slug
    return ActionRecord(
        run_id=f"{parent.run_id}-{slug}",
        action_id=action.action_id,
        label=action.label,
        kind=action.kind,
        scope=action.scope,
        status="running",
        created_at_utc=parent.created_at_utc,
        started_at_utc=utc_now(),
        completed_at_utc=None,
        workspace_root=parent.workspace_root,
        profile_id=action.profile_id,
        project_root=action.project_root,
        command_preview=action.command_preview,
        blocker_message=action.blocker_message,
        paths={
            "output_root": str(output_root),
            "run_record": str(output_root / "action.json"),
            "log": str(output_root / "action.log"),
            "summary_json": str(output_root / "summary.json"),
            "summary_md": str(output_root / "summary.md"),
            "xlsx_report": str(output_root / "scene-check.xlsx"),
        },
    )


def _log(record: ActionRecord, text: str) -> None:
    log_path = Path(record.paths["log"])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(text.rstrip() + "\n")


def _summary_md_lines(summary: dict[str, Any]) -> list[str]:
    lines = [
        f"# {summary.get('title', 'SG Preflight QA Action')}",
        "",
    ]
    for item in summary.get("lines", []):
        lines.append(f"- {item}")
    return lines


def _save_action_summary(record: ActionRecord) -> None:
    if record.summary is None:
        return
    write_json_file(Path(record.paths["summary_json"]), record.summary)
    _write_text(Path(record.paths["summary_md"]), "\n".join(_summary_md_lines(record.summary)).strip() + "\n")


def _parse_repo_checker_output(output: str) -> dict[str, Any]:
    phase_matches = re.findall(r"starting\s+(\w+)\s+on\s+(\d+)\s+files", output, flags=re.IGNORECASE)
    error_matches = [int(value) for value in re.findall(r"(\d+)\s+errors found", output, flags=re.IGNORECASE)]
    phases = [f"{name}: {count} file(s)" for name, count in phase_matches]
    error_total = sum(error_matches)
    lines = []
    if phases:
        lines.extend(phases)
    lines.append(f"Reported error batches: {error_total}")
    return {
        "title": "Repo Checker Result",
        "lines": lines,
        "phase_count": len(phase_matches),
        "reported_error_batches": error_total,
    }


def _scene_error_blocks(output: str) -> list[str]:
    errors: list[str] = []
    current = ""
    collecting = False
    for line in output.splitlines():
        if line.startswith("[E]"):
            if current:
                errors.append(current)
            current = line
            collecting = True
            continue
        if collecting and (line.startswith("[") or not line.strip()):
            if current:
                errors.append(current)
            current = ""
            collecting = False
            continue
        if collecting:
            current += "\n" + line
    if current:
        errors.append(current)
    return errors


def _execute_daily_live_matrix(record: ActionRecord, root: Path) -> tuple[dict[str, Any], list[dict[str, str]], list[str]]:
    profiles = list_run_profiles(root)
    lines = []
    artifacts: list[dict[str, str]] = []
    notes: list[str] = []
    output_root = Path(record.paths["output_root"])
    total_profiles = max(len(profiles), 1)

    _set_action_progress(
        record,
        step_key="profiles",
        percent=10,
        label="Running live profile matrix",
        detail=f"Preparing {len(profiles)} live profile run(s).",
    )

    for index, profile in enumerate(profiles, start=1):
        matrix_percent = 10 + int((index - 1) / total_profiles * 75)
        _set_action_progress(
            record,
            step_key="profiles",
            percent=matrix_percent,
            label=f"Running {profile.profile_id}",
            detail=f"Live matrix {index}/{len(profiles)}: materializing and validating {profile.profile_id}.",
        )
        child_output = output_root / profile.profile_id.lower()
        child = execute_profile_run(
            profile,
            RunRequest(
                profile_id=profile.profile_id,
                fail_on="never",
                output_root=child_output,
                run_id=profile.profile_id.lower(),
            ),
            root,
        )
        child_summary = child.summary or {}
        lines.append(
            f"{profile.profile_id}: {child_summary.get('errors', 0)} errors, {child_summary.get('warnings', 0)} warnings, {child_summary.get('info', 0)} info"
        )
        notes.extend(f"{profile.profile_id}: {note}" for note in child.notes[:3])
        artifacts.extend(
            [
                _artifact(f"{profile.profile_id} HTML report", Path(child.paths["html_report"])),
                _artifact(f"{profile.profile_id} Markdown report", Path(child.paths["markdown_report"])),
                _artifact(f"{profile.profile_id} JSON report", Path(child.paths["json_report"])),
            ]
        )
        _log(record, f"{profile.profile_id}: completed with {child_summary}")

    _set_action_progress(
        record,
        step_key="finalize",
        percent=92,
        label="Finalizing daily matrix",
        detail="Writing the shared SG live-matrix summary and artifacts.",
    )
    summary = {
        "title": "Daily SG Check",
        "lines": lines,
        "profile_count": len(profiles),
    }
    return summary, artifacts, notes


def _execute_profile_stack(record: ActionRecord, root: Path) -> tuple[dict[str, Any], list[dict[str, str]], list[str]]:
    profile = next(
        candidate
        for candidate in list_run_profiles(root)
        if candidate.profile_id.lower() == record.profile_id.lower()
    )
    lines: list[str] = []
    artifacts: list[dict[str, str]] = []
    notes: list[str] = []

    _set_action_progress(
        record,
        step_key="preflight",
        percent=12,
        label="Running standard preflight",
        detail=f"Starting the recommended deterministic check for {profile.profile_id}.",
    )
    preflight_output = Path(record.paths["output_root"]) / "standard-preflight"
    preflight = execute_profile_run(
        profile,
        RunRequest(
            profile_id=profile.profile_id,
            fail_on="never",
            output_root=preflight_output,
            run_id=f"{profile.profile_id.lower()}-stack",
        ),
        root,
    )
    preflight_summary = preflight.summary or {}
    lines.append(
        "Standard preflight: "
        f"{preflight_summary.get('errors', 0)} errors, "
        f"{preflight_summary.get('warnings', 0)} warnings, "
        f"{preflight_summary.get('info', 0)} info"
    )
    artifacts.extend(
        [
            _artifact("Standard preflight HTML report", Path(preflight.paths["html_report"])),
            _artifact("Standard preflight Markdown report", Path(preflight.paths["markdown_report"])),
            _artifact("Standard preflight JSON report", Path(preflight.paths["json_report"])),
            _artifact("Standard preflight run record", Path(preflight.paths["run_record"])),
        ]
    )
    notes.extend(f"Preflight: {note}" for note in preflight.notes[:3])

    repo_action = get_operator_action(
        f"repo_checker_profile__{profile.profile_id.lower()}",
        root,
        profiles=[profile],
    )
    _set_action_progress(
        record,
        step_key="repo_checker",
        percent=46,
        label="Checking SG repo hygiene",
        detail=f"Running mirrored repo checker coverage for {profile.profile_id}.",
    )
    if repo_action.ready:
        repo_record = _nested_action_record(record, repo_action, "repo-checker")
        repo_summary, repo_artifacts, _ = _execute_repo_checker(repo_record, root)
        lines.append(
            "Repo checker: "
            f"{repo_summary.get('reported_error_batches', 0)} reported error batches across "
            f"{repo_summary.get('phase_count', 0)} phases"
        )
        artifacts.extend(repo_artifacts)
    else:
        lines.append(f"Repo checker: blocked - {repo_action.blocker_message}")

    scene_action = get_operator_action(
        f"scene_check__{profile.profile_id.lower()}",
        root,
        profiles=[profile],
    )
    _set_action_progress(
        record,
        step_key="scene_check",
        percent=68,
        label="Checking RaCo scenes",
        detail=f"Running scene-check coverage for {profile.profile_id} where local RaCo is available.",
    )
    if scene_action.ready:
        scene_record = _nested_action_record(record, scene_action, "scene-check")
        scene_summary, scene_artifacts, _ = _execute_scene_check(scene_record, root)
        lines.append(
            "Scene check: "
            f"{scene_summary.get('checked_scenes', 0)} scenes checked, "
            f"{scene_summary.get('scenes_with_errors', 0)} with errors"
        )
        artifacts.extend(scene_artifacts)
    else:
        lines.append(f"Scene check: blocked - {scene_action.blocker_message}")

    bmw_action = get_operator_action(
        f"bmw_screenshot_smoke__{profile.profile_id.lower()}",
        root,
        profiles=[profile],
    )
    _set_action_progress(
        record,
        step_key="bmw_smoke",
        percent=86,
        label="Checking BMW smoke stage",
        detail=f"Evaluating BMW-side screenshot smoke coverage for {profile.profile_id}.",
    )
    if bmw_action.ready:
        bmw_record = _nested_action_record(record, bmw_action, "bmw-screenshot-smoke")
        bmw_summary, bmw_artifacts, _ = _execute_bmw_screenshot_smoke(bmw_record, root)
        lines.extend(f"BMW screenshot smoke: {line}" for line in bmw_summary.get("lines", []))
        artifacts.extend(bmw_artifacts)
    else:
        lines.append(f"BMW screenshot smoke: blocked - {bmw_action.blocker_message}")

    summary = {
        "title": f"Recommended QA Stack - {profile.profile_id}",
        "lines": lines,
        "profile_id": profile.profile_id,
    }
    return summary, artifacts, notes


def _execute_repo_checker(record: ActionRecord, root: Path) -> tuple[dict[str, Any], list[dict[str, str]], list[str]]:
    mirror_root = root / "repositories" / "trunk"
    checker_script = mirror_root / ".pdx" / "checkers" / "executeChecks.py"
    target = Path(record.project_root) if record.project_root else (
        mirror_root / ("Cars_IDCevo" if record.action_id == "repo_checker_idcevo" else "Cars")
    )
    env = os.environ.copy()
    env["SG-Repo"] = str(mirror_root)
    _set_action_progress(
        record,
        step_key="execute",
        percent=24,
        label="Running SG repo checker",
        detail=f"Launching checker stack on {target}.",
    )
    result = subprocess.run(
        [sys.executable, str(checker_script), str(target)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    output = ((result.stdout or "") + ("\n" + result.stderr if result.stderr else "")).strip()
    _write_text(Path(record.paths["log"]), output + ("\n" if output else ""))
    _set_action_progress(
        record,
        step_key="parse",
        percent=78,
        label="Parsing SG repo checker output",
        detail="Summarizing checker phases and reported error batches.",
    )
    summary = _parse_repo_checker_output(output)
    summary["return_code"] = result.returncode
    if result.returncode != 0:
        summary.setdefault("lines", []).append(f"Process returned exit code {result.returncode}.")
    artifacts = [_artifact("Checker log", Path(record.paths["log"]))]
    return summary, artifacts, []


def _execute_bmw_screenshot_smoke(record: ActionRecord, root: Path) -> tuple[dict[str, Any], list[dict[str, str]], list[str]]:
    profile = next(
        candidate
        for candidate in list_run_profiles(root)
        if candidate.profile_id.lower() == record.profile_id.lower()
    )
    status_map = _status_map(root)
    bmw_repo = _path_from_status(status_map, "bmw_models_repo")
    script_path = _bmw_smoke_script_path(status_map, profile)
    target = profile.bmw_smoke_target.strip()
    scripts_root = bmw_repo / "ci" / "scripts"

    _set_action_progress(
        record,
        step_key="export",
        percent=28,
        label="Running BMW export",
        detail=f"Launching BMW export for target {target}.",
    )
    export_process = subprocess.run(
        [sys.executable, str(script_path), "export", target],
        cwd=scripts_root,
        capture_output=True,
        text=True,
        check=False,
    )
    _set_action_progress(
        record,
        step_key="screenshots",
        percent=68,
        label="Running BMW screenshots",
        detail=f"Capturing screenshot diff output for target {target}.",
    )
    screenshots_process = subprocess.run(
        [sys.executable, str(script_path), "screenshots", "--diff", target],
        cwd=scripts_root,
        capture_output=True,
        text=True,
        check=False,
    )
    combined_log = "\n\n".join(
        [
            "=== export ===",
            (export_process.stdout or "").strip(),
            (export_process.stderr or "").strip(),
            "=== screenshots ===",
            (screenshots_process.stdout or "").strip(),
            (screenshots_process.stderr or "").strip(),
        ]
    ).strip()
    _write_text(Path(record.paths["log"]), combined_log + ("\n" if combined_log else ""))

    summary = {
        "title": "BMW Screenshot Smoke Result",
        "lines": [
            f"Target: {target}",
            f"Export exit code: {export_process.returncode}",
            f"Screenshot exit code: {screenshots_process.returncode}",
        ],
        "target": target,
        "export_exit_code": export_process.returncode,
        "screenshots_exit_code": screenshots_process.returncode,
    }
    artifacts = [_artifact("BMW screenshot smoke log", Path(record.paths["log"]))]
    return summary, artifacts, []


def _execute_scene_check(record: ActionRecord, root: Path) -> tuple[dict[str, Any], list[dict[str, str]], list[str]]:
    status_map = _status_map(root)
    raco_exe = _path_from_status(status_map, "raco_headless")
    project_root = Path(record.project_root)
    scenes = sorted(project_root.rglob("*.rca"))
    total_scenes = max(len(scenes), 1)
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    scene_errors = 0
    log_lines: list[str] = []

    _set_action_progress(
        record,
        step_key="discover",
        percent=12,
        label="Discovering scenes",
        detail=f"Found {len(scenes)} `.rca` scene(s) under {project_root}.",
    )

    for index, scene in enumerate(scenes, start=1):
        scene_percent = 18 + int((index - 1) / total_scenes * 68)
        _set_action_progress(
            record,
            step_key="execute",
            percent=scene_percent,
            label=f"Checking scene {index}/{len(scenes)}",
            detail=str(scene),
        )
        log_lines.append(f"Checking scene: {scene}")
        result = subprocess.run(
            [str(raco_exe), "-p", str(scene), "-l", "3"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        output = ((result.stdout or "") + ("\n" + result.stderr if result.stderr else "")).strip()
        if output:
            log_lines.append(output)
        errors = _scene_error_blocks(output)
        if not errors:
            continue

        scene_errors += 1
        sheet = workbook.create_sheet()
        sheet.append([str(scene)])
        title_cell = sheet.cell(column=1, row=1)
        title_cell.font = openpyxl.styles.Font(size=16, bold=True)
        for item in errors:
            sheet.append([item])
        sheet.column_dimensions["A"].width = 155
        for cell in sheet["A"]:
            cell.alignment = openpyxl.styles.Alignment(wrap_text=True)

    _write_text(Path(record.paths["log"]), "\n".join(log_lines).strip() + ("\n" if log_lines else ""))
    artifacts = [_artifact("Scene checker log", Path(record.paths["log"]))]
    if workbook.sheetnames:
        workbook_path = Path(record.paths["xlsx_report"])
        workbook_path.parent.mkdir(parents=True, exist_ok=True)
        workbook.save(workbook_path)
        artifacts.append(_artifact("Scene checker workbook", workbook_path))
    workbook.close()

    summary = {
        "title": "Scene Check Result",
        "lines": [
            f"Checked scenes: {len(scenes)}",
            f"Scenes with errors: {scene_errors}",
        ],
        "checked_scenes": len(scenes),
        "scenes_with_errors": scene_errors,
    }
    return summary, artifacts, []


def execute_operator_action(
    action: OperatorAction,
    workspace: Path | None = None,
    *,
    record: ActionRecord | None = None,
) -> ActionRecord:
    root = workspace_root(workspace)
    record = record or build_action_record(action, root)
    _set_action_progress(
        record,
        step_key="queued",
        percent=0,
        label="Queued locally",
        detail=f"Preparing {action.label}.",
    )

    if not action.ready:
        record.status = "blocked"
        record.completed_at_utc = utc_now()
        record.summary = {
            "title": action.label,
            "lines": [action.blocker_message or "This action is blocked on the current machine."],
        }
        record.progress = {
            **build_progress_payload(
                ACTION_PROGRESS_PLANS.get(action.kind, (("queued", "Queued"),)),
                step_key="queued",
                percent=100,
                label="Blocked on this machine",
                detail=action.blocker_message or "This action is blocked on the current machine.",
            ),
            "state": "blocked",
        }
        _save_action_summary(record)
        save_action_record(record)
        return record

    record.status = "running"
    record.started_at_utc = utc_now()
    _set_action_progress(
        record,
        step_key="queued",
        percent=4,
        label="Starting automation",
        detail=f"Launching {action.label}.",
    )

    try:
        if action.kind == "daily_live_matrix":
            summary, artifacts, notes = _execute_daily_live_matrix(record, root)
        elif action.kind == "profile_stack":
            summary, artifacts, notes = _execute_profile_stack(record, root)
        elif action.kind == "repo_checker":
            summary, artifacts, notes = _execute_repo_checker(record, root)
        elif action.kind == "bmw_screenshot_smoke":
            summary, artifacts, notes = _execute_bmw_screenshot_smoke(record, root)
        elif action.kind == "scene_check":
            summary, artifacts, notes = _execute_scene_check(record, root)
        else:
            raise ValueError(f"Unsupported action kind: {action.kind}")

        record.summary = summary
        record.artifacts = artifacts
        record.notes = notes
        record.status = "completed"
        record.completed_at_utc = utc_now()
        record.progress = build_progress_payload(
            ACTION_PROGRESS_PLANS.get(action.kind, (("queued", "Queued"),)),
            step_key="finalize",
            percent=100,
            label="Action completed",
            detail="The generated files and summary are ready to open.",
        )
        _save_action_summary(record)
        save_action_record(record)
        return record
    except Exception as exc:
        record.status = "failed"
        record.error_message = str(exc)
        record.completed_at_utc = utc_now()
        record.progress = dict(record.progress or {})
        record.progress.update(
            {
                "label": "Action failed",
                "detail": str(exc),
            }
        )
        save_action_record(record)
        raise
