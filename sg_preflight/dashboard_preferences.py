"""Reads and writes the dashboard's persisted operator preferences: run mode, active ticket, theme, and desktop notification settings."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import os
import platform
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Callable

from sg_preflight.profiles import PROFILE_SCOPE_DEFAULT, list_run_profiles
from sg_preflight.subprocess_utils import hidden_subprocess_kwargs
from sg_preflight.utils import ensure_parent


CANONICAL_SOURCE_REPO_ROOT = Path(r"C:\repositories\trunk")
DASHBOARD_PREFERENCES_FILENAME = "dashboard_preferences.json"
DEFAULT_DASHBOARD_RUN_MODE = "automatic"
DASHBOARD_RUN_MODE_CHOICES = ("automatic", "manual")
THEME_CHOICES = ["clean"]
FEEDBACK_EMAIL_ENV = "SGFX_FEEDBACK_EMAIL"
DEFAULT_FEEDBACK_EMAIL = "david-erik.garcia-arenas@paradoxcat.com"
DESKTOP_NOTIFICATIONS_ENV = "SGFX_DESKTOP_NOTIFICATIONS"
_DASHBOARD_TICKET_FALLBACK = "IDCEVODEV-977874"
_TICKET_ID_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
_MISSING_STATUSES = {
    "missing",
    "no_review_package",
    "no_overview_sheet",
    "not_found",
}
_UNKNOWN_STATUSES = {"error", "failed", "unreadable", "unknown"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _workspace(workspace: Path | str) -> Path:
    return Path(workspace).resolve()


def _path_label(path: Path | str) -> str:
    value = Path(path)
    return value.name or str(value)


def _source_repo_root_candidates(workspace: Path | str) -> list[str]:
    candidates: list[Path] = [CANONICAL_SOURCE_REPO_ROOT]
    for key in ("SG_SOURCE_REPO_ROOT", "SG_REPO"):
        raw = os.environ.get(key, "").strip()
        if raw:
            candidates.append(Path(raw).expanduser())
    workspace_path = Path(workspace).resolve()
    candidates.extend((workspace_path, workspace_path / "repositories" / "trunk"))
    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        text = str(candidate.resolve() if candidate.exists() else candidate)
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(text)
    return unique


def _preferred_source_repo_root(workspace: Path | str) -> Path | None:
    for raw in _source_repo_root_candidates(workspace):
        candidate = Path(raw).expanduser()
        if candidate.is_dir() and ((candidate / "Cars").is_dir() or (candidate / "Cars_IDCevo").is_dir()):
            return candidate.resolve()
    return None


def _source_repo_root_from_value(value: str | Path | None) -> Path | None:
    raw = str(value or "").strip().strip('"')
    return Path(raw).expanduser().resolve() if raw else None


def _abbreviate_workspace_text(text: str, workspace: Path | str | None) -> str:
    if workspace is None:
        return text
    root = Path(workspace).resolve()
    root_text = str(root)
    if root_text not in text:
        return text
    return text.replace(root_text, _path_label(root))


def _payload_summary(payload: dict[str, Any], fallback: str, *, workspace: Path | str | None = None) -> str:
    raw = payload.get("summary", "")
    if isinstance(raw, dict):
        raw = ""
    text = str(raw or payload.get("no_data_message", "") or payload.get("note", "") or fallback)
    return _abbreviate_workspace_text(text, workspace)


def _clean_theme(ui_mode: str | None) -> str:
    value = str(ui_mode or "clean").strip().casefold()
    return value if value in THEME_CHOICES else "clean"


def _profile_option_label(option: dict[str, Any]) -> str:
    brand = str(option.get("brand", "BMW") or "BMW")
    lane = str(option.get("lane", "unknown") or "unknown")
    model_type = str(option.get("type", "build") or "build")
    label = f"{brand} / {lane} / {option['id']}"
    target = str(option.get("retarget_target", "") or "")
    if model_type == "retarget" and target:
        label = f"{label} -> {target}"
    elif model_type and model_type != "build":
        label = f"{label} ({model_type})"
    return label


def dashboard_profile_options(
    *,
    bmw_root: Path | str | None = None,
    profile_scope: str = PROFILE_SCOPE_DEFAULT,
) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    for profile in list_run_profiles(bmw_root=bmw_root, profile_scope=profile_scope):
        option: dict[str, Any] = {
            "id": profile.profile_id,
            "label": profile.label,
            "bmw_profile_id": profile.bmw_profile_id,
            "lane": profile.lane,
            "brand": profile.brand,
            "type": profile.model_type,
            "interface_version": profile.interface_version,
            "retarget_target": profile.retarget_target,
            "active_build": profile.active_build,
            "registry_source": profile.registry_source,
        }
        option["select_label"] = _profile_option_label(option)
        options.append(option)
    return options


def _resolve_dashboard_profile_id(
    profile_id: str | None,
    options: list[dict[str, str]],
    *,
    workspace: Path | str | None = None,
    fallback_options: list[dict[str, str]] | None = None,
) -> str:
    requested = str(profile_id or "").strip()
    if not requested:
        preferred = _dashboard_preferred_profile_id(workspace, options) if workspace is not None else ""
        if preferred:
            return preferred
        fallbacks = fallback_options or options
        return fallbacks[0]["id"] if fallbacks else options[0]["id"] if options else ""
    for option in options:
        if option["id"].casefold() == requested.casefold():
            return option["id"]
    return requested.upper()


def _dashboard_profile_known(profile_id: str, options: list[dict[str, str]]) -> bool:
    return any(option["id"].casefold() == profile_id.casefold() for option in options)


def _dashboard_status(raw_status: str, data_available: bool = False) -> str:
    status = raw_status.strip().casefold()
    if data_available and status in {"available", "recorded", "ok"}:
        return "available"
    if status in _MISSING_STATUSES:
        return "missing"
    if status in _UNKNOWN_STATUSES:
        return "unknown"
    if status in {"not_run", "not-run", "not run", "pending"}:
        return "not_run"
    if status in {"not_available", "unavailable", "no_workbook", "profile_not_found"}:
        return "unavailable"
    return status or "unknown"


def _operator_state_path(workspace: Path | str, filename: str) -> Path:
    return _workspace(workspace) / "operator_state" / filename


def _dashboard_preferences_path(workspace: Path | str) -> Path:
    return _operator_state_path(workspace, DASHBOARD_PREFERENCES_FILENAME)


def _read_operator_state_json(workspace: Path | str, filename: str) -> dict[str, Any]:
    path = _operator_state_path(workspace, filename)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_operator_state_json(workspace: Path | str, filename: str, payload: dict[str, Any]) -> Path:
    path = _operator_state_path(workspace, filename)
    ensure_parent(path)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    temp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(path)
    return path


def _clean_dashboard_run_mode(value: Any) -> str:
    text = str(value or DEFAULT_DASHBOARD_RUN_MODE).strip().casefold()
    if text in {"manual", "0", "false", "off", "disabled"}:
        return "manual"
    return "automatic"


def _clean_feedback_email(value: Any) -> str:
    configured = str(value or "").strip()
    return configured if configured and re.fullmatch(r"[A-Za-z0-9._%+\-@,;]+", configured) else ""


def _clean_default_ticket_id(value: Any) -> str:
    ticket_id = str(value or "").strip().upper()
    return ticket_id if _TICKET_ID_PATTERN.fullmatch(ticket_id) else _DASHBOARD_TICKET_FALLBACK


def _clean_grafiks_shell_exe(value: Any) -> str:
    raw = str(value or "").strip().strip('"')
    return str(Path(raw).expanduser()) if raw else ""


def _dashboard_default_ticket_id(workspace: Path | str) -> str:
    payload = _read_operator_state_json(workspace, DASHBOARD_PREFERENCES_FILENAME)
    return _clean_default_ticket_id(payload.get("default_ticket_id") or payload.get("active_ticket_id"))


def _dashboard_run_mode(workspace: Path | str) -> str:
    payload = _read_operator_state_json(workspace, DASHBOARD_PREFERENCES_FILENAME)
    return _clean_dashboard_run_mode(payload.get("run_mode"))


def _dashboard_grafiks_shell_exe_preference(workspace: Path | str | None) -> str:
    if workspace is None:
        return ""
    payload = _read_operator_state_json(workspace, DASHBOARD_PREFERENCES_FILENAME)
    return _clean_grafiks_shell_exe(payload.get("grafiks_shell_exe"))


def _profile_id_from_preferences(payload: dict[str, Any], options: list[dict[str, Any]] | None) -> str:
    profile_id = str(payload.get("profile_id") or payload.get("last_profile_id") or "").strip()
    if not profile_id:
        return ""
    if options is None:
        return profile_id
    option_ids = {str(option.get("id", "")).casefold(): str(option.get("id", "")) for option in options}
    return option_ids.get(profile_id.casefold(), "")


def load_dashboard_settings(
    workspace: Path | str,
    *,
    profile_options: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = _read_operator_state_json(workspace, DASHBOARD_PREFERENCES_FILENAME)
    default_ticket_id = _clean_default_ticket_id(payload.get("default_ticket_id") or payload.get("active_ticket_id"))
    grafiks_shell_exe = _clean_grafiks_shell_exe(payload.get("grafiks_shell_exe"))
    return {
        "schema_version": int(payload.get("schema_version", 1) or 1),
        "theme": _clean_theme(str(payload.get("theme", "clean"))),
        "profile_id": _profile_id_from_preferences(payload, profile_options),
        "run_mode": _clean_dashboard_run_mode(payload.get("run_mode")),
        "desktop_notifications_enabled": _dashboard_notifications_enabled(workspace),
        "feedback_email": _dashboard_feedback_recipient(workspace),
        "default_ticket_id": default_ticket_id,
        "grafiks_shell_exe": grafiks_shell_exe,
        "settings_path": str(_dashboard_preferences_path(workspace)),
        "local_storage_note": "Settings are stored locally on this machine and never leave it.",
    }


def save_dashboard_settings(
    workspace: Path | str,
    *,
    profile_id: str | None = None,
    run_mode: str | None = None,
    desktop_notifications_enabled: bool | None = None,
    feedback_email: str | None = None,
    default_ticket_id: str | None = None,
    grafiks_shell_exe: Path | str | None = None,
    theme: str | None = None,
) -> dict[str, Any]:
    payload = _read_operator_state_json(workspace, DASHBOARD_PREFERENCES_FILENAME)
    payload["schema_version"] = 1
    if profile_id is not None:
        clean_profile = str(profile_id or "").strip()
        if clean_profile:
            payload["profile_id"] = clean_profile
            payload["last_profile_id"] = clean_profile
    if run_mode is not None:
        payload["run_mode"] = _clean_dashboard_run_mode(run_mode)
    if desktop_notifications_enabled is not None:
        payload["desktop_notifications_enabled"] = bool(desktop_notifications_enabled)
    if feedback_email is not None:
        clean_email = _clean_feedback_email(feedback_email)
        if clean_email:
            payload["feedback_email"] = clean_email
        else:
            payload.pop("feedback_email", None)
    if default_ticket_id is not None:
        payload["default_ticket_id"] = _clean_default_ticket_id(default_ticket_id)
    if grafiks_shell_exe is not None:
        clean_path = _clean_grafiks_shell_exe(grafiks_shell_exe)
        if clean_path:
            payload["grafiks_shell_exe"] = clean_path
        else:
            payload.pop("grafiks_shell_exe", None)
    if theme is not None:
        payload["theme"] = _clean_theme(theme)
    payload["updated_at_utc"] = _utc_now()
    _write_operator_state_json(workspace, DASHBOARD_PREFERENCES_FILENAME, payload)
    return payload


def _dashboard_feedback_recipient(workspace: Path | str) -> str:
    from sg_preflight.feedback_routing import load_feedback_routing

    routing = load_feedback_routing()
    if routing.config_loaded and routing.email_recipient:
        return routing.email_recipient
    payload = _read_operator_state_json(workspace, DASHBOARD_PREFERENCES_FILENAME)
    for raw in (payload.get("feedback_email"), os.environ.get(FEEDBACK_EMAIL_ENV, ""), routing.email_recipient):
        configured = str(raw or "").strip()
        if configured and re.fullmatch(r"[A-Za-z0-9._%+\-@,;]+", configured):
            return configured
    return routing.email_recipient or DEFAULT_FEEDBACK_EMAIL


def _candidate_git_roots() -> list[Path]:
    roots: list[Path] = []
    for start in (Path(__file__).resolve(), Path.cwd().resolve(), Path(sys.executable).resolve()):
        roots.extend([start, *start.parents])
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root).casefold()
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


@lru_cache(maxsize=1)
def _dashboard_build_sha() -> str:
    for root in _candidate_git_roots():
        if not (root / ".git").exists():
            continue
        try:
            completed = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=root,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                text=True,
                timeout=3,
                check=False,
                **hidden_subprocess_kwargs(),
            )
        except Exception:
            continue
        value = completed.stdout.strip()
        if completed.returncode == 0 and value:
            try:
                dirty = subprocess.run(
                    ["git", "status", "--short", "--untracked-files=no"],
                    cwd=root,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    text=True,
                    timeout=3,
                    check=False,
                    **hidden_subprocess_kwargs(),
                )
            except Exception:
                return value
            suffix = "-dirty" if dirty.returncode == 0 and dirty.stdout.strip() else ""
            return f"{value}{suffix}"
    return "unknown"


@lru_cache(maxsize=1)
def _dashboard_exe_sha256() -> str:
    if not getattr(sys, "frozen", False):
        return "source-run"
    executable = Path(sys.executable)
    if not executable.is_file():
        return "unavailable"
    digest = hashlib.sha256()
    try:
        with executable.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return "unavailable"
    return digest.hexdigest().upper()


def _dashboard_feedback_context(workspace: Path | str) -> dict[str, str]:
    from sg_preflight.feedback_routing import load_feedback_routing

    routing = load_feedback_routing()
    return {
        "to": _dashboard_feedback_recipient(workspace),
        "teams_recipient": routing.teams_recipient,
        "primary": routing.primary,
        "subject_prefix": routing.subject_prefix,
        "build_sha": _dashboard_build_sha(),
        "exe_sha": _dashboard_exe_sha256(),
        "os_version": platform.platform(),
    }


def _dashboard_preferred_profile_id(workspace: Path | str | None, options: list[dict[str, str]]) -> str:
    if workspace is None:
        return ""
    option_ids = {str(option["id"]).casefold(): str(option["id"]) for option in options}
    for filename in (DASHBOARD_PREFERENCES_FILENAME, "dashboard_context.json", "operator_context.json"):
        payload = _read_operator_state_json(workspace, filename)
        for key in ("profile_id", "active_profile_id", "selected_profile_id", "last_profile_id"):
            raw = str(payload.get(key, "")).strip()
            if raw and raw.casefold() in option_ids:
                return option_ids[raw.casefold()]
    return ""


def resolve_explicit_dashboard_profile(
    *,
    workspace: Path | str,
    options: list[dict[str, str]],
) -> str:
    return _dashboard_preferred_profile_id(workspace, options)


def _write_dashboard_profile_preference(workspace: Path | str, profile_id: str) -> dict[str, Any]:
    return save_dashboard_settings(workspace, profile_id=profile_id)


def _bool_preference(value: Any, *, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().casefold()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _dashboard_notifications_enabled(workspace: Path | str) -> bool:
    env_value = os.environ.get(DESKTOP_NOTIFICATIONS_ENV)
    if env_value is not None:
        return _bool_preference(env_value, default=True)
    payload = _read_operator_state_json(workspace, DASHBOARD_PREFERENCES_FILENAME)
    return _bool_preference(payload.get("desktop_notifications_enabled"), default=True)


def _write_dashboard_notifications_preference(workspace: Path | str, enabled: bool) -> dict[str, Any]:
    return save_dashboard_settings(workspace, desktop_notifications_enabled=enabled)


def _full_qa_profile_output_token(profile_id: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(profile_id or "unknown").strip()).strip("._-")
    return (token or "unknown").lower()


def _full_qa_wizard_state_path(profile_id: str, *, home: Path | None = None) -> Path:
    root = Path(home).resolve() if home is not None else Path.home().resolve()
    return root / "sgfx_outputs" / _full_qa_profile_output_token(profile_id) / ".wizard_state.json"


def _read_full_qa_wizard_state(profile_id: str, *, home: Path | None = None) -> dict[str, Any]:
    path = _full_qa_wizard_state_path(profile_id, home=home)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_full_qa_wizard_state(profile_id: str, payload: dict[str, Any], *, home: Path | None = None) -> Path:
    path = _full_qa_wizard_state_path(profile_id, home=home)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    temp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    temp_path.replace(path)
    return path


def _delete_full_qa_wizard_state(profile_id: str, *, home: Path | None = None) -> None:
    try:
        _full_qa_wizard_state_path(profile_id, home=home).unlink()
    except FileNotFoundError:
        return


def _ticket_id_from_payload(payload: dict[str, Any]) -> str:
    for key in ("active_ticket_id", "ticket_id", "jira_ticket", "jira_ticket_id", "ticket"):
        raw = str(payload.get(key, "")).strip().upper()
        if raw and _TICKET_ID_PATTERN.fullmatch(raw):
            return raw
    return ""


def _dashboard_ticket_from_operator_state(workspace: Path | str) -> str:
    for filename in ("dashboard_context.json", "operator_context.json", "active_ticket.json"):
        ticket_id = _ticket_id_from_payload(_read_operator_state_json(workspace, filename))
        if ticket_id:
            return ticket_id
    return ""


def _dashboard_ticket_from_git_branch(workspace: Path | str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(_workspace(workspace)), "rev-parse", "--abbrev-ref", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            text=True,
            timeout=2,
            **hidden_subprocess_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if completed.returncode != 0:
        return ""
    match = _TICKET_ID_PATTERN.search(str(completed.stdout or "").upper())
    return match.group(0) if match else ""


def _ticket_ids_from_activity_log(workspace: Path | str, *, limit: int = 6) -> list[str]:
    path = _workspace(workspace) / "operator_state" / "activity_log.jsonl"
    if not path.is_file():
        return []
    tickets: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in reversed(lines):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            payload = {"note": line}
        haystack = json.dumps(payload, ensure_ascii=False) if isinstance(payload, dict) else str(payload)
        for match in _TICKET_ID_PATTERN.finditer(haystack.upper()):
            ticket_id = match.group(0)
            if ticket_id not in tickets:
                tickets.append(ticket_id)
                if len(tickets) >= limit:
                    return tickets
    return tickets


def _write_active_ticket_state(workspace: Path | str, ticket_id: str, *, source: str) -> dict[str, Any]:
    clean_ticket = ticket_id.strip().upper()
    if not _TICKET_ID_PATTERN.fullmatch(clean_ticket):
        raise ValueError(f"Unsupported ticket ID: {ticket_id}")
    path = _operator_state_path(workspace, "active_ticket.json")
    payload = _read_operator_state_json(workspace, "active_ticket.json")
    payload.update(
        {
            "active_ticket_id": clean_ticket,
            "ticket_id": clean_ticket,
            "source": source.strip() or "operator",
            "updated_at_utc": _utc_now(),
        }
    )
    ensure_parent(path)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    temp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(path)
    return payload


def _daily_digest_ticket_context(
    workspace: Path | str,
    *,
    ticket_id_placeholder: str,
    ticket_from_operator_state: Callable[[Path | str], str] | None = None,
    ticket_from_git_branch: Callable[[Path | str], str] | None = None,
) -> dict[str, Any]:
    operator_state = ticket_from_operator_state or _dashboard_ticket_from_operator_state
    git_branch = ticket_from_git_branch or _dashboard_ticket_from_git_branch
    active_ticket = _ticket_id_from_payload(_read_operator_state_json(workspace, "active_ticket.json"))
    recent_ticket_ids = _ticket_ids_from_activity_log(workspace)
    if active_ticket:
        return {
            "active_ticket_id": active_ticket,
            "ticket_id_hint": active_ticket,
            "ticket_id_source": "active_ticket_file",
            "recent_ticket_ids": recent_ticket_ids,
        }
    operator_ticket = operator_state(workspace)
    if operator_ticket:
        return {
            "active_ticket_id": operator_ticket,
            "ticket_id_hint": operator_ticket,
            "ticket_id_source": "operator_state",
            "recent_ticket_ids": recent_ticket_ids,
        }
    branch_ticket = git_branch(workspace)
    if branch_ticket:
        return {
            "active_ticket_id": branch_ticket,
            "ticket_id_hint": branch_ticket,
            "ticket_id_source": "git_branch",
            "recent_ticket_ids": recent_ticket_ids,
        }
    if recent_ticket_ids:
        return {
            "active_ticket_id": recent_ticket_ids[0],
            "ticket_id_hint": recent_ticket_ids[0],
            "ticket_id_source": "activity_log",
            "recent_ticket_ids": recent_ticket_ids,
        }
    return {
        "active_ticket_id": "",
        "ticket_id_hint": ticket_id_placeholder,
        "ticket_id_source": "manual_entry",
        "recent_ticket_ids": [],
    }


def _dashboard_active_ticket_id(
    workspace: Path | str,
    *,
    fallback_ticket_id: str = _DASHBOARD_TICKET_FALLBACK,
    ticket_from_operator_state: Callable[[Path | str], str] | None = None,
    ticket_from_git_branch: Callable[[Path | str], str] | None = None,
) -> str:
    operator_state = ticket_from_operator_state or _dashboard_ticket_from_operator_state
    git_branch = ticket_from_git_branch or _dashboard_ticket_from_git_branch
    state_ticket = operator_state(workspace)
    if state_ticket:
        return state_ticket
    for key in ("SGFX_ACTIVE_TICKET_ID", "SGFX_DASHBOARD_TICKET_ID"):
        raw = os.environ.get(key, "").strip().upper()
        if raw and _TICKET_ID_PATTERN.fullmatch(raw):
            return raw
    branch_ticket = git_branch(workspace)
    if branch_ticket:
        return branch_ticket
    return _dashboard_default_ticket_id(workspace) if fallback_ticket_id == _DASHBOARD_TICKET_FALLBACK else fallback_ticket_id


def load_dashboard_preference(workspace: Path | str) -> str:
    payload = _read_operator_state_json(workspace, DASHBOARD_PREFERENCES_FILENAME)
    return _clean_theme(str(payload.get("theme", "clean")))


def save_dashboard_preference(workspace: Path | str, theme: str) -> dict[str, Any]:
    return save_dashboard_settings(workspace, theme=theme)
