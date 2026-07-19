"""Shared tier for dependency onboarding: operator-state persistence, generic
path-probe helpers, the `DependencySetupJob` job-runner (start-command
construction, poll/cancel, tail/size formatting), and the status/action/result
dict builders every dependency domain module uses.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import wraps
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, Callable

if os.name == "nt":
    import msvcrt
else:
    import fcntl

from sg_preflight.subprocess_utils import sgfx_cli_command
from sg_preflight.utils import ensure_parent


def _sync_onboarding_globals(target_globals: dict[str, Any]) -> None:
    """Refresh names this module shares with the facade before a call runs.

    Sibling modules keep their own copies of every helper they import from
    each other (Python globals are per-module). A test that does
    `mock.patch.object(dependency_onboarding, "_helper", ...)` only rebinds
    the facade's copy, so a moved function calling `_helper(...)` as a bare
    name would silently miss the patch. Re-syncing the calling module's
    globals from the live facade right before the call keeps every existing
    `sg_preflight.dependency_onboarding.*` mock.patch target intercepting,
    exactly as it did when everything lived in one module.
    """
    from sg_preflight import dependency_onboarding as _onboarding_facade

    for name in list(target_globals.keys()):
        if name.startswith("__"):
            continue
        if hasattr(_onboarding_facade, name):
            target_globals[name] = getattr(_onboarding_facade, name)


def _with_onboarding_globals(func: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(func)
    def _wrapper(*args: Any, **kwargs: Any) -> Any:
        _sync_onboarding_globals(func.__globals__)
        return func(*args, **kwargs)

    return _wrapper


ONBOARDING_STATE_FILENAME = "dependency_onboarding.json"


ONBOARDING_STATE_LOCK_FILENAME = "dependency_onboarding.lock"


DEPENDENCY_SETUP_TIMEOUT_SECONDS = 900


DEPENDENCY_SETUP_STDOUT_TAIL_LINES = 20


DEPENDENCY_SETUP_STDOUT_TAIL_BYTES = 2000


DEPENDENCY_SETUP_FILE_ACTIVITY_LIMIT = 20


DEPENDENCY_STATE_REPLACE_RETRY_ATTEMPTS = 3


DEPENDENCY_STATE_REPLACE_ATTEMPTS = DEPENDENCY_STATE_REPLACE_RETRY_ATTEMPTS


DEPENDENCY_STATE_REPLACE_RETRY_SECONDS = 0.01


_DEPENDENCY_STATE_LOCK = threading.RLock()


_DEPENDENCY_STATE_TRANSACTIONS = threading.local()


_KNOWN_REGISTERED_PATHS = {
    "raco_gui",
    "raco_headless",
    "blender",
    "bmw_pipeline_python",
    "digital_3d_car_repo",
    "digital_3d_car_repo_idc23",
    "digital_3d_car_repo_assets_idc23",
}


@dataclass
class DependencySetupJob:
    action_id: str
    workspace: Path
    process: subprocess.Popen[bytes]
    command: list[str]
    stdout_path: Path
    stderr_path: Path
    started_monotonic: float
    started_wall_time: float
    timeout_seconds: int
    typical_range: str
    target_path: Path | None = None
    source_path: Path | None = None
    completed: bool = False


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _workspace(workspace: Path | str) -> Path:
    return Path(workspace).resolve()


def operator_state_root(workspace: Path | str) -> Path:
    return _workspace(workspace) / "operator_state"


def dependency_onboarding_state_path(workspace: Path | str) -> Path:
    return operator_state_root(workspace) / ONBOARDING_STATE_FILENAME


def dependency_onboarding_state_lock_path(workspace: Path | str) -> Path:
    return operator_state_root(workspace) / ONBOARDING_STATE_LOCK_FILENAME


def _held_dependency_state_transactions() -> dict[str, Any]:
    process_id = os.getpid()
    transaction_state = getattr(_DEPENDENCY_STATE_TRANSACTIONS, "state", None)
    if transaction_state is not None and transaction_state[0] != process_id:
        for handle in transaction_state[1].values():
            try:
                handle.close()
            except OSError:
                pass
        transaction_state = None
    if transaction_state is None:
        transaction_state = (process_id, {})
        _DEPENDENCY_STATE_TRANSACTIONS.state = transaction_state
    return transaction_state[1]


def _acquire_dependency_state_file_lock(handle: Any) -> None:
    handle.seek(0)
    if os.name == "nt":
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _release_dependency_state_file_lock(handle: Any) -> None:
    handle.seek(0)
    if os.name == "nt":
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _dependency_state_transaction(workspace: Path | str) -> Iterator[None]:
    lock_path = dependency_onboarding_state_lock_path(workspace)
    lock_key = os.path.normcase(str(lock_path))
    with _DEPENDENCY_STATE_LOCK:
        held_transactions = _held_dependency_state_transactions()
        if lock_key in held_transactions:
            yield
            return

        ensure_parent(lock_path)
        handle = lock_path.open("a+b")
        acquired = False
        try:
            _acquire_dependency_state_file_lock(handle)
            acquired = True
            held_transactions[lock_key] = handle
            yield
        finally:
            held_transactions.pop(lock_key, None)
            try:
                if acquired:
                    _release_dependency_state_file_lock(handle)
            finally:
                handle.close()


def has_operator_state(workspace: Path | str) -> bool:
    root = operator_state_root(workspace)
    if not root.exists():
        return False
    try:
        return any(root.iterdir())
    except OSError:
        return False


def load_dependency_onboarding_state(workspace: Path | str) -> dict[str, Any]:
    with _DEPENDENCY_STATE_LOCK:
        path = dependency_onboarding_state_path(workspace)
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}


def _write_dependency_onboarding_state(workspace: Path | str, state: dict[str, Any]) -> dict[str, Any]:
    with _dependency_state_transaction(workspace):
        state["updated_at_utc"] = _utc_now()
        output_path = dependency_onboarding_state_path(workspace)
        ensure_parent(output_path)
        temp_path = output_path.with_name(f".{output_path.name}.{os.getpid()}.{time.time_ns()}.tmp")
        try:
            temp_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
            for attempt in range(DEPENDENCY_STATE_REPLACE_ATTEMPTS):
                try:
                    temp_path.replace(output_path)
                    break
                except PermissionError:
                    if attempt + 1 == DEPENDENCY_STATE_REPLACE_ATTEMPTS:
                        raise
                    time.sleep(DEPENDENCY_STATE_REPLACE_RETRY_SECONDS)
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
        return state


def record_dependency_path(*, workspace: Path | str, key: str, path: Path | str) -> dict[str, Any]:
    clean_key = key.strip()
    if clean_key not in _KNOWN_REGISTERED_PATHS:
        raise KeyError(f"Unsupported dependency key: {key}")
    target = Path(path).expanduser().resolve()
    with _dependency_state_transaction(workspace):
        state = load_dependency_onboarding_state(workspace)
        registered_paths = state.setdefault("registered_paths", {})
        if not isinstance(registered_paths, dict):
            registered_paths = {}
            state["registered_paths"] = registered_paths
        registered_paths[clean_key] = str(target)
        state["source"] = "dependency onboarding"
        return _write_dependency_onboarding_state(workspace, state)


def _same_registered_path(current: Path | None, target: Path) -> bool:
    if current is None:
        return False
    try:
        return os.path.normcase(str(current.expanduser().resolve())) == os.path.normcase(str(target.resolve()))
    except (OSError, RuntimeError):
        try:
            current_text = str(current.expanduser())
        except RuntimeError:
            current_text = str(current)
        return os.path.normcase(current_text) == os.path.normcase(str(target))


def _auto_register_dependency_path(
    state: dict[str, Any],
    *,
    workspace: Path | str,
    key: str,
    path: Path | str | None,
) -> bool:
    clean_key = key.strip()
    if clean_key not in _KNOWN_REGISTERED_PATHS or path is None:
        return False
    target = Path(path).expanduser().resolve()
    if _same_registered_path(_registered_path(state, clean_key), target):
        return False
    registered_paths = state.setdefault("registered_paths", {})
    if not isinstance(registered_paths, dict):
        registered_paths = {}
        state["registered_paths"] = registered_paths
    registered_paths[clean_key] = str(target)
    state["source"] = str(state.get("source") or "dependency onboarding fast-path")
    state["last_auto_registered_key"] = clean_key
    return True


def _registered_paths_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    registered_paths = state.get("registered_paths", {})
    return dict(registered_paths) if isinstance(registered_paths, dict) else {}


def _persist_auto_detected_dependency_paths(
    workspace: Path | str,
    *,
    original_paths: dict[str, Any],
    detected_state: dict[str, Any],
) -> None:
    detected_paths = _registered_paths_snapshot(detected_state)
    auto_changes = {
        key: value
        for key, value in detected_paths.items()
        if key in _KNOWN_REGISTERED_PATHS
        and (key not in original_paths or original_paths[key] != value)
    }
    if not auto_changes:
        return

    with _dependency_state_transaction(workspace):
        latest_state = load_dependency_onboarding_state(workspace)
        latest_paths = _registered_paths_snapshot(latest_state)
        applied_keys: list[str] = []
        for key, value in auto_changes.items():
            if (key in latest_paths) != (key in original_paths):
                continue
            if key in latest_paths and latest_paths[key] != original_paths[key]:
                continue
            latest_paths[key] = value
            applied_keys.append(key)
        if not applied_keys:
            return
        latest_state["registered_paths"] = latest_paths
        latest_state["source"] = str(
            latest_state.get("source")
            or detected_state.get("source")
            or "dependency onboarding fast-path"
        )
        latest_state["last_auto_registered_key"] = applied_keys[-1]
        _write_dependency_onboarding_state(workspace, latest_state)


def _registered_path(state: dict[str, Any], key: str) -> Path | None:
    registered_paths = state.get("registered_paths", {})
    if not isinstance(registered_paths, dict):
        return None
    raw = str(registered_paths.get(key, "")).strip()
    return Path(raw).expanduser() if raw else None


def _existing_file(candidates: list[Path | None]) -> Path | None:
    seen: set[str] = set()
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            path = candidate.expanduser()
        except RuntimeError:
            continue
        normalized = str(path).casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        if path.is_file():
            return path.resolve()
    return None


def _existing_dir(candidates: list[Path | None]) -> Path | None:
    seen: set[str] = set()
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            path = candidate.expanduser()
        except RuntimeError:
            continue
        normalized = str(path).casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        if path.is_dir():
            return path.resolve()
    return None


def _env_path(keys: tuple[str, ...]) -> Path | None:
    for key in keys:
        raw = os.environ.get(key, "").strip()
        if raw:
            return Path(raw).expanduser()
    return None


def _find_executable(executable_name: str) -> Path | None:
    found = shutil.which(executable_name)
    if found:
        return Path(found).resolve()
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:
        return None
    subkey = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{executable_name}"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, subkey) as key:
                value, _kind = winreg.QueryValueEx(key, "")
        except OSError:
            continue
        candidate = Path(str(value).strip('"'))
        if candidate.is_file():
            return candidate.resolve()
    return None


def _glob_dirs(parent: Path, pattern: str, limit: int = 12) -> list[Path]:
    if not parent.is_dir():
        return []
    try:
        return [path for path in sorted(parent.glob(pattern)) if path.is_dir()][:limit]
    except OSError:
        return []


def _status_item(
    *,
    key: str,
    label: str,
    status: str,
    detail: str,
    path: Path | str | None = None,
    confluence_anchor: str,
    setup_action: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "detail": detail,
        "path": str(path or ""),
        "confluence_anchor": confluence_anchor,
        "setup_action": setup_action or {},
    }


def _setup_action(
    *,
    action_id: str,
    label: str,
    dependency_key: str,
    status: str,
    confirmation_message: str,
    effects: list[str],
    confluence_anchor: str,
    can_run_now: bool = False,
    command_preview: str = "",
    target_path: Path | str | None = None,
    source_path: Path | str | None = None,
    requires_admin: bool = False,
    operator_inputs: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": action_id,
        "label": label,
        "dependency_key": dependency_key,
        "status": status,
        "requires_confirmation": True,
        "confirmation_message": confirmation_message,
        "effects": effects,
        "confluence_anchor": confluence_anchor,
        "can_run_now": can_run_now,
        "command_preview": command_preview,
        "target_path": str(target_path or ""),
        "source_path": str(source_path or ""),
        "requires_admin": requires_admin,
        "operator_inputs": operator_inputs or [],
    }


def _setup_result(
    *,
    status: str,
    action_id: str,
    summary: str,
    path: Path | str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": status,
        "action_id": action_id,
        "summary": summary,
        "recorded_by_tool": True,
        "is_approval": False,
    }
    if path is not None:
        payload["path"] = str(path)
    payload.update(extra)
    return payload


def _elapsed_label(elapsed_seconds: float) -> str:
    elapsed = max(0, int(elapsed_seconds))
    minutes, seconds = divmod(elapsed, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _tail_text(path: Path, limit: int = DEPENDENCY_SETUP_STDOUT_TAIL_BYTES) -> str:
    if not path.is_file():
        return ""
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    return data[-limit:].decode("utf-8", errors="replace")


def _tail_lines(path: Path, limit: int = DEPENDENCY_SETUP_STDOUT_TAIL_LINES) -> list[str]:
    text = _tail_text(path)
    if not text:
        return []
    return text.splitlines()[-limit:]


def _combined_tail_lines(stdout_path: Path, stderr_path: Path) -> list[str]:
    lines = list(_tail_lines(stdout_path))
    lines.extend(f"stderr: {line}" for line in _tail_lines(stderr_path))
    return lines[-DEPENDENCY_SETUP_STDOUT_TAIL_LINES:]


def _size_label(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    kib = size_bytes / 1024
    if kib < 1024:
        return f"{kib:.0f} KB"
    mib = kib / 1024
    return f"{mib:.1f} MB"


def _file_activity_from_roots(
    roots: list[Path | None],
    started_wall_time: float,
    limit: int = DEPENDENCY_SETUP_FILE_ACTIVITY_LIMIT,
) -> list[dict[str, Any]]:
    entries: list[tuple[float, dict[str, Any]]] = []
    threshold = started_wall_time - 1.0
    seen: set[str] = set()
    for root in roots:
        if root is None:
            continue
        try:
            base = root.expanduser().resolve()
        except OSError:
            continue
        candidates = [base]
        if base.is_dir():
            try:
                candidates.extend(path for path in base.iterdir())
            except OSError:
                continue
        for path in candidates:
            normalized = str(path).casefold()
            if normalized in seen or not path.exists():
                continue
            seen.add(normalized)
            try:
                stat = path.stat()
            except OSError:
                continue
            last_activity = max(stat.st_mtime, stat.st_ctime)
            if last_activity < threshold:
                continue
            event = "created" if stat.st_ctime >= threshold else "modified"
            size_label = _size_label(int(stat.st_size)) if path.is_file() else "folder"
            try:
                relative = str(path.relative_to(base))
            except ValueError:
                relative = path.name
            if relative == ".":
                relative = path.name
            entries.append(
                (
                    last_activity,
                    {
                        "event": event,
                        "path": str(path),
                        "relative_path": relative,
                        "size_bytes": int(stat.st_size),
                        "size_label": size_label,
                        "summary": f"{event.title()} `{relative}` ({size_label})",
                    },
                )
            )
    return [item for _timestamp, item in sorted(entries, key=lambda pair: pair[0], reverse=True)[:limit]]


def _dependency_setup_worker_command(
    *,
    action_id: str,
    workspace: Path,
    target_path: Path | str | None,
    source_path: Path | str | None,
) -> list[str]:
    command = sgfx_cli_command("dependency-setup-worker", action_id, "--workspace", str(workspace))
    if target_path:
        command.extend(["--target-path", str(target_path)])
    if source_path:
        command.extend(["--source-path", str(source_path)])
    return command


def _last_json_payload(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    for line in reversed(lines):
        raw = line.strip()
        if not raw.startswith("{") or not raw.endswith("}"):
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        return payload if isinstance(payload, dict) else {}
    return {}


def _dependency_setup_progress_payload(job: DependencySetupJob, *, elapsed_seconds: float) -> dict[str, Any]:
    return {
        "action_id": job.action_id,
        "workspace": str(job.workspace),
        "status": "incomplete",
        "phase": "running",
        "completed": False,
        "exit_code": None,
        "command": list(job.command),
        "timeout_seconds": job.timeout_seconds,
        "elapsed_seconds": int(max(0, elapsed_seconds)),
        "elapsed_label": _elapsed_label(elapsed_seconds),
        "typical_range": job.typical_range,
        "timed_out": False,
        "canceled": False,
        "summary": "Dependency setup running.",
        "stdout_tail": _tail_text(job.stdout_path),
        "stdout_tail_lines": _combined_tail_lines(job.stdout_path, job.stderr_path),
        "stderr_tail": _tail_text(job.stderr_path),
        "stdout_path": str(job.stdout_path),
        "stderr_path": str(job.stderr_path),
        "file_activity": _file_activity_from_roots(
            [job.stdout_path.parent, job.target_path],
            job.started_wall_time,
        ),
        "recorded_by_tool": True,
        "is_approval": False,
    }


def _dependency_setup_result(
    job: DependencySetupJob,
    *,
    exit_code: int,
    status: str,
    summary: str,
    timed_out: bool = False,
    canceled: bool = False,
) -> dict[str, Any]:
    elapsed_seconds = time.monotonic() - job.started_monotonic
    payload = _last_json_payload(job.stdout_path)
    if not payload:
        payload = {
            "status": status,
            "action_id": job.action_id,
            "summary": summary,
            "recorded_by_tool": True,
            "is_approval": False,
        }
    payload.update(
        {
            "action_id": job.action_id,
            "workspace": str(job.workspace),
            "completed": True,
            "exit_code": exit_code,
            "command": list(job.command),
            "timeout_seconds": job.timeout_seconds,
            "elapsed_seconds": int(max(0, elapsed_seconds)),
            "elapsed_label": _elapsed_label(elapsed_seconds),
            "typical_range": job.typical_range,
            "timed_out": timed_out,
            "canceled": canceled,
            "stdout_tail": _tail_text(job.stdout_path),
            "stdout_tail_lines": _combined_tail_lines(job.stdout_path, job.stderr_path),
            "stderr_tail": _tail_text(job.stderr_path),
            "stdout_path": str(job.stdout_path),
            "stderr_path": str(job.stderr_path),
            "file_activity": _file_activity_from_roots(
                [job.stdout_path.parent, job.target_path],
                job.started_wall_time,
            ),
            "recorded_by_tool": True,
            "is_approval": False,
        }
    )
    payload.setdefault("status", status)
    payload.setdefault("summary", summary)
    return payload


def poll_dependency_setup_action(job: DependencySetupJob) -> dict[str, Any] | None:
    if job.completed:
        return _dependency_setup_result(
            job,
            exit_code=job.process.returncode or 0,
            status="unknown",
            summary="Dependency setup job already completed.",
        )
    exit_code = job.process.poll()
    elapsed = time.monotonic() - job.started_monotonic
    if exit_code is None and elapsed < job.timeout_seconds:
        return _dependency_setup_progress_payload(job, elapsed_seconds=elapsed)
    if exit_code is None:
        job.process.terminate()
        try:
            job.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            job.process.kill()
            job.process.wait(timeout=5)
        job.completed = True
        return _dependency_setup_result(
            job,
            exit_code=job.process.returncode if job.process.returncode is not None else -1,
            status="failed",
            summary=f"Dependency setup timed out after {job.timeout_seconds} seconds.",
            timed_out=True,
        )
    job.completed = True
    return _dependency_setup_result(
        job,
        exit_code=exit_code,
        status="recorded" if exit_code == 0 else "failed",
        summary=(
            "Dependency setup completed."
            if exit_code == 0
            else f"Dependency setup failed with exit code {exit_code}."
        ),
    )


def cancel_dependency_setup_action(job: DependencySetupJob) -> dict[str, Any]:
    if job.process.poll() is None:
        job.process.terminate()
        try:
            job.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            job.process.kill()
            job.process.wait(timeout=5)
    job.completed = True
    return _dependency_setup_result(
        job,
        exit_code=job.process.returncode if job.process.returncode is not None else -1,
        status="failed",
        summary="Dependency setup canceled by operator.",
        canceled=True,
    )


# Re-resolve collaborators through the live `dependency_onboarding` facade on
# every call, so `mock.patch.object(dependency_onboarding, "_name", ...)`
# keeps intercepting now that callers and callees can live in different files.
_utc_now = _with_onboarding_globals(_utc_now)
_workspace = _with_onboarding_globals(_workspace)
operator_state_root = _with_onboarding_globals(operator_state_root)
dependency_onboarding_state_path = _with_onboarding_globals(dependency_onboarding_state_path)
dependency_onboarding_state_lock_path = _with_onboarding_globals(dependency_onboarding_state_lock_path)
_held_dependency_state_transactions = _with_onboarding_globals(_held_dependency_state_transactions)
_acquire_dependency_state_file_lock = _with_onboarding_globals(_acquire_dependency_state_file_lock)
_release_dependency_state_file_lock = _with_onboarding_globals(_release_dependency_state_file_lock)
_dependency_state_transaction = _with_onboarding_globals(_dependency_state_transaction)
has_operator_state = _with_onboarding_globals(has_operator_state)
load_dependency_onboarding_state = _with_onboarding_globals(load_dependency_onboarding_state)
_write_dependency_onboarding_state = _with_onboarding_globals(_write_dependency_onboarding_state)
record_dependency_path = _with_onboarding_globals(record_dependency_path)
_same_registered_path = _with_onboarding_globals(_same_registered_path)
_auto_register_dependency_path = _with_onboarding_globals(_auto_register_dependency_path)
_registered_paths_snapshot = _with_onboarding_globals(_registered_paths_snapshot)
_persist_auto_detected_dependency_paths = _with_onboarding_globals(_persist_auto_detected_dependency_paths)
_registered_path = _with_onboarding_globals(_registered_path)
_existing_file = _with_onboarding_globals(_existing_file)
_existing_dir = _with_onboarding_globals(_existing_dir)
_env_path = _with_onboarding_globals(_env_path)
_find_executable = _with_onboarding_globals(_find_executable)
_glob_dirs = _with_onboarding_globals(_glob_dirs)
_status_item = _with_onboarding_globals(_status_item)
_setup_action = _with_onboarding_globals(_setup_action)
_setup_result = _with_onboarding_globals(_setup_result)
_elapsed_label = _with_onboarding_globals(_elapsed_label)
_tail_text = _with_onboarding_globals(_tail_text)
_tail_lines = _with_onboarding_globals(_tail_lines)
_combined_tail_lines = _with_onboarding_globals(_combined_tail_lines)
_size_label = _with_onboarding_globals(_size_label)
_file_activity_from_roots = _with_onboarding_globals(_file_activity_from_roots)
_dependency_setup_worker_command = _with_onboarding_globals(_dependency_setup_worker_command)
_last_json_payload = _with_onboarding_globals(_last_json_payload)
_dependency_setup_progress_payload = _with_onboarding_globals(_dependency_setup_progress_payload)
_dependency_setup_result = _with_onboarding_globals(_dependency_setup_result)
poll_dependency_setup_action = _with_onboarding_globals(poll_dependency_setup_action)
cancel_dependency_setup_action = _with_onboarding_globals(cancel_dependency_setup_action)
