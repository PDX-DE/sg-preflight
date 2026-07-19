"""Session-scoped JSONL event log — records UI/subprocess/exception events, installs
crash hooks, and exports a scrubbed session bundle."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import sys
import threading
import traceback
from typing import Any
import zipfile

from sg_preflight.io_utils import read_jsonl
from sg_preflight.live_state import sanitize_payload
from sg_preflight.time_utils import utc_now_ms

SESSION_LOG_TAIL_LIMIT = 20
SESSION_LOG_EXPORT_LOG_LIMIT_BYTES = 2 * 1024 * 1024
_VALID_LEVELS = {"info", "warning", "error"}
_VALID_SOURCES = {"ui", "subprocess", "exception", "cli"}

_current_log: SessionLog | None = None
_current_lock = threading.Lock()
_hooks_installed = False
_previous_sys_excepthook: Any = None
_previous_threading_excepthook: Any = None


def session_log_dir(workspace: Path | str) -> Path:
    return Path(workspace).resolve() / "operator_state" / "sessions"


def session_log_path(workspace: Path | str, *, started_at: str | None = None, pid: int | None = None) -> Path:
    from datetime import datetime, timezone
    import os

    if started_at:
        safe_stamp = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in started_at).strip("-")
    else:
        safe_stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    safe_pid = int(pid if pid is not None else os.getpid())
    return session_log_dir(workspace) / f"{safe_stamp}-{safe_pid}.jsonl"


def _normalize_detail(detail: Any) -> str:
    if detail is None:
        return ""
    if isinstance(detail, str):
        return detail
    try:
        return json.dumps(detail, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(detail)


def _record(
    *,
    source: str,
    surface: str,
    message: str,
    detail: Any = "",
    level: str = "info",
    profile: str = "",
) -> dict[str, str]:
    safe_level = level if level in _VALID_LEVELS else "info"
    safe_source = source if source in _VALID_SOURCES else "cli"
    payload = {
        "ts": utc_now_ms(),
        "level": safe_level,
        "source": safe_source,
        "surface": str(surface or ""),
        "profile": str(profile or ""),
        "message": str(message or ""),
        "detail": _normalize_detail(detail),
    }
    scrubbed = sanitize_payload(payload)
    return {key: str(scrubbed.get(key, "")) for key in payload}


@dataclass
class SessionLog:
    workspace: Path
    path: Path
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    event_count: int = 0
    error_count: int = 0

    def event(
        self,
        *,
        source: str,
        surface: str,
        message: str,
        detail: Any = "",
        level: str = "info",
        profile: str = "",
    ) -> dict[str, str]:
        record = _record(
            source=source,
            surface=surface,
            message=message,
            detail=detail,
            level=level,
            profile=profile,
        )
        line = json.dumps(record, ensure_ascii=False, sort_keys=True)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.write("\n")
            self.event_count += 1
            if record["level"] == "error":
                self.error_count += 1
        return record

    def exception(self, *, surface: str, exc: BaseException, profile: str = "", message: str = "Unhandled exception") -> dict[str, str]:
        detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        return self.event(
            source="exception",
            surface=surface,
            message=message,
            detail=detail,
            level="error",
            profile=profile,
        )

    def close_summary(self, *, surface: str, profile: str = "", message: str = "Session ended") -> dict[str, str]:
        return self.event(
            source="ui",
            surface=surface,
            message=message,
            detail={"event_count": self.event_count, "error_count": self.error_count, "path": str(self.path)},
            level="info",
            profile=profile,
        )


def start_session_log(
    workspace: Path | str,
    *,
    source: str = "cli",
    surface: str = "session",
    detail: Any = "",
    reuse_current: bool = True,
) -> SessionLog:
    global _current_log

    workspace_path = Path(workspace).resolve()
    with _current_lock:
        if reuse_current and _current_log is not None and _current_log.workspace == workspace_path:
            return _current_log
        session = SessionLog(workspace=workspace_path, path=session_log_path(workspace_path))
        _current_log = session
    start_detail = {"workspace": str(workspace_path)}
    if detail != "":
        start_detail["detail"] = detail
    session.event(source=source, surface=surface, message="Session log started", detail=start_detail)
    return session


def current_session_log() -> SessionLog | None:
    return _current_log


def event(
    *,
    source: str,
    surface: str,
    message: str,
    detail: Any = "",
    level: str = "info",
    profile: str = "",
) -> dict[str, str] | None:
    current = current_session_log()
    if current is None:
        return None
    return current.event(source=source, surface=surface, message=message, detail=detail, level=level, profile=profile)


def exception_event(*, surface: str, exc: BaseException, profile: str = "", message: str = "Unhandled exception") -> dict[str, str] | None:
    current = current_session_log()
    if current is None:
        return None
    return current.exception(surface=surface, exc=exc, profile=profile, message=message)


def install_exception_hooks() -> None:
    global _hooks_installed, _previous_sys_excepthook, _previous_threading_excepthook

    if _hooks_installed:
        return
    _hooks_installed = True
    _previous_sys_excepthook = sys.excepthook
    _previous_threading_excepthook = getattr(threading, "excepthook", None)

    def _sys_hook(exc_type: type[BaseException], exc: BaseException, tb: Any) -> None:
        try:
            detail = "".join(traceback.format_exception(exc_type, exc, tb))
            event(source="exception", surface="sys.excepthook", message="Unhandled main-thread exception", detail=detail, level="error")
        except Exception:
            pass
        if _previous_sys_excepthook is not None:
            _previous_sys_excepthook(exc_type, exc, tb)

    def _thread_hook(args: threading.ExceptHookArgs) -> None:
        try:
            thread_name = getattr(args.thread, "name", "") if args.thread is not None else ""
            detail = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
            event(
                source="exception",
                surface=f"threading.excepthook:{thread_name}" if thread_name else "threading.excepthook",
                message="Unhandled worker-thread exception",
                detail=detail,
                level="error",
            )
        except Exception:
            pass
        if _previous_threading_excepthook is not None:
            _previous_threading_excepthook(args)

    sys.excepthook = _sys_hook
    threading.excepthook = _thread_hook


def list_session_logs(workspace: Path | str, *, limit: int = 20) -> list[Path]:
    root = session_log_dir(workspace)
    if not root.exists():
        return []
    paths = [path for path in root.glob("*.jsonl") if path.is_file()]
    paths.sort(key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
    return paths[: max(0, int(limit))]


def latest_session_log(workspace: Path | str) -> Path | None:
    logs = list_session_logs(workspace, limit=1)
    return logs[0] if logs else None


def read_session_records(path: Path | str, *, tail: int | None = None) -> list[dict[str, Any]]:
    records = read_jsonl(Path(path))
    if tail is None:
        return records
    return records[-max(0, int(tail)) :]


def latest_session_payload(workspace: Path | str, *, tail: int = SESSION_LOG_TAIL_LIMIT) -> dict[str, Any]:
    path = latest_session_log(workspace)
    if path is None:
        return {"path": "", "records": [], "note": "No session logs found."}
    return {"path": str(path), "records": read_session_records(path, tail=tail)}


def render_session_log_text(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    path = str(payload.get("path", "") or "")
    if path:
        lines.append(f"Session log: {path}")
    note = str(payload.get("note", "") or "")
    if note:
        lines.append(note)
    records = payload.get("records")
    if isinstance(records, list):
        for record in records:
            if not isinstance(record, dict):
                continue
            prefix = " ".join(
                part for part in [
                    str(record.get("ts", "")),
                    str(record.get("level", "")),
                    str(record.get("source", "")),
                    str(record.get("surface", "")),
                    str(record.get("profile", "")),
                ] if part
            )
            message = str(record.get("message", "") or "")
            detail = str(record.get("detail", "") or "")
            line = f"{prefix} {message}".strip()
            if detail:
                line = f"{line} | {detail}"
            lines.append(line)
    return "\n".join(lines) if lines else "No session logs found."


def _recover_workspace_log_path(workspace: Path, requested: Path) -> Path | None:
    name = requested.name
    if not name:
        return None
    root = workspace.resolve() / "operator_state"
    if not root.is_dir():
        return None
    matches = [path for path in root.rglob(name) if path.is_file()]
    if not matches:
        return None
    matches.sort(key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
    return matches[0].resolve()


def _iter_referenced_log_paths(workspace: Path, records: list[dict[str, Any]]) -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()
    keys = {"stderr_path", "log_path"}
    for record in records:
        detail = record.get("detail", "")
        payload: Any = detail
        if isinstance(detail, str):
            try:
                payload = json.loads(detail)
            except json.JSONDecodeError:
                payload = {}
        if not isinstance(payload, dict):
            continue
        for key in keys:
            value = payload.get(key)
            if not value:
                continue
            path = Path(str(value))
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            if not resolved.is_file():
                recovered = _recover_workspace_log_path(workspace, path)
                if recovered is None:
                    continue
                resolved = recovered
            if resolved in seen:
                continue
            seen.add(resolved)
            paths.append(resolved)
    return paths


def _scrubbed_text_from_file(path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    omitted = 0
    if len(data) > SESSION_LOG_EXPORT_LOG_LIMIT_BYTES:
        omitted = len(data) - SESSION_LOG_EXPORT_LOG_LIMIT_BYTES
        data = data[-SESSION_LOG_EXPORT_LOG_LIMIT_BYTES:]
    text = data.decode("utf-8", errors="replace")
    text = str(sanitize_payload(text))
    if omitted:
        text = f"[{omitted} leading bytes omitted by SGFX session-log export]\n{text}"
    return text


def export_session_log(
    workspace: Path | str,
    *,
    zip_output: Path | str,
    source_path: Path | str | None = None,
) -> dict[str, Any]:
    source = Path(source_path).resolve() if source_path is not None else latest_session_log(workspace)
    if source is None or not source.is_file():
        raise FileNotFoundError("No session log found to export.")
    output = Path(zip_output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    records = read_session_records(source)
    scrubbed_jsonl = "".join(
        json.dumps(sanitize_payload(record), ensure_ascii=False, sort_keys=True) + "\n"
        for record in records
    )
    referenced = _iter_referenced_log_paths(Path(workspace).resolve(), records)
    included: list[str] = []
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("session-log.jsonl", scrubbed_jsonl)
        included.append("session-log.jsonl")
        for index, path in enumerate(referenced, start=1):
            archive_name = f"referenced/{index:02d}-{path.name}"
            archive.writestr(archive_name, _scrubbed_text_from_file(path))
            included.append(archive_name)
    return {
        "zip_path": str(output),
        "session_log_path": str(source),
        "included_files": included,
        "referenced_log_count": len(referenced),
    }


def _reset_session_log_for_tests() -> None:
    global _current_log

    with _current_lock:
        _current_log = None
