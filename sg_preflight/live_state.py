"""H-26 live observability surface.

Writes a single JSON file at `<workspace>/operator_state/live_state.json`
that reflects the current dashboard state. Writes are debounced (default 250ms)
so high-frequency UI updates do not thrash the disk. The file is operator-local
and never crosses external boundaries — per [[feedback-secrets-never-in-chat]],
payloads carry no PAT, no credentials, and no absolute personal paths beyond
what is already in the workspace string itself.

Schema:

    {
      "ts": "<iso ms>",
      "dashboard_surface": "<str>",
      "profile_id": "<str>",
      "wizard_step_id": "<str>",
      "wizard_step_index": <int>,
      "wizard_step_total": <int>,
      "queued_acknowledgments": [<str>...],
      "running_subprocess": null | { "name": <str>, "started_at": "<iso ms>", "pid_present": <bool> },
      "last_operator_action": null | { "verb": <str>, "surface": <str>, "ts": "<iso ms>" },
      "last_error": null | <str>
    }

Backward-compat: agents tail the file via `sgfx-preflight.exe live-state --tail`.
The shape is versioned via the `schema_version` field for future extensibility.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import threading
import time
from typing import Any

LIVE_STATE_SCHEMA_VERSION = 1
DEFAULT_DEBOUNCE_MS = 250


def live_state_path(workspace: Path | str) -> Path:
    return Path(workspace).resolve() / "operator_state" / "live_state.json"


def _utc_now_ms(value: datetime | None = None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    iso = current.astimezone(timezone.utc).isoformat(timespec="milliseconds")
    return iso.replace("+00:00", "Z")


# Sanitization patterns — strip PAT-shaped strings + bearer tokens.
# Conservative: any 32+ char hex / alnum chunk that looks PAT-ish is masked.
_PAT_PATTERN = re.compile(r"\b([A-Za-z0-9_\-]{32,})\b")
_BEARER_PATTERN = re.compile(r"(?i)(bearer\s+)([A-Za-z0-9_\-\.]+)")
_PASSWORD_KEY_PATTERN = re.compile(r"(?i)(\"(?:password|pat|token|secret|api[_-]?key)\"\s*:\s*\")([^\"]*)(\")")


def sanitize_payload(value: Any) -> Any:
    """Recursively scrub PAT-like values from a payload before logging.

    Per [[feedback-secrets-never-in-chat]] — live_state.json + activity_log entries
    must never carry the raw credential value. Operator-local paths stay; tokens are
    replaced with `****<last4>` fingerprints when long enough, else `****`.
    """
    if isinstance(value, dict):
        return {key: sanitize_payload(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_payload(item) for item in value]
    if isinstance(value, str):
        # Heuristic: replace any bare 32+ char alnum token.
        def mask_pat(match: re.Match[str]) -> str:
            token = match.group(1)
            return f"****{token[-4:]}" if len(token) >= 4 else "****"

        text = _PAT_PATTERN.sub(mask_pat, value)
        text = _BEARER_PATTERN.sub(lambda m: f"{m.group(1)}****", text)
        text = _PASSWORD_KEY_PATTERN.sub(lambda m: f"{m.group(1)}****{m.group(3)}", text)
        return text
    return value


@dataclass(frozen=True)
class RunningSubprocess:
    name: str
    started_at: str
    pid_present: bool


@dataclass(frozen=True)
class LastOperatorAction:
    verb: str
    surface: str
    ts: str


@dataclass(frozen=True)
class LiveStateSnapshot:
    """In-memory live-state payload. Immutable so concurrent reads are safe."""

    dashboard_surface: str = ""
    profile_id: str = ""
    wizard_step_id: str = ""
    wizard_step_index: int = -1
    wizard_step_total: int = 0
    queued_acknowledgments: tuple[str, ...] = field(default_factory=tuple)
    running_subprocess: RunningSubprocess | None = None
    last_operator_action: LastOperatorAction | None = None
    last_error: str | None = None

    def to_payload(self, ts: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "schema_version": LIVE_STATE_SCHEMA_VERSION,
            "ts": ts or _utc_now_ms(),
            "dashboard_surface": self.dashboard_surface,
            "profile_id": self.profile_id,
            "wizard_step_id": self.wizard_step_id,
            "wizard_step_index": int(self.wizard_step_index),
            "wizard_step_total": int(self.wizard_step_total),
            "queued_acknowledgments": list(self.queued_acknowledgments),
            "running_subprocess": (
                asdict(self.running_subprocess)
                if self.running_subprocess is not None
                else None
            ),
            "last_operator_action": (
                asdict(self.last_operator_action)
                if self.last_operator_action is not None
                else None
            ),
            "last_error": self.last_error,
        }
        return sanitize_payload(body)


class DebouncedLiveStateWriter:
    """Coalesces high-frequency updates into ≤ one disk write per `debounce_ms`.

    Atomic write via tmp + replace so a partial write never corrupts the file
    for the tail-reader CLI. Thread-safe; safe to call from any NiceGUI handler.
    """

    def __init__(self, workspace: Path | str, *, debounce_ms: int = DEFAULT_DEBOUNCE_MS):
        self._path = live_state_path(workspace)
        self._debounce = max(int(debounce_ms), 0) / 1000.0
        self._lock = threading.Lock()
        self._last_write_at = 0.0
        self._pending: LiveStateSnapshot | None = None
        self._timer: threading.Timer | None = None
        self._closed = False

    @property
    def path(self) -> Path:
        return self._path

    def update(self, snapshot: LiveStateSnapshot) -> None:
        with self._lock:
            if self._closed:
                return
            self._pending = snapshot
            if self._debounce <= 0:
                self._flush_locked()
                return
            now = time.monotonic()
            elapsed = now - self._last_write_at
            if elapsed >= self._debounce:
                self._flush_locked()
                return
            if self._timer is None or not self._timer.is_alive():
                delay = max(self._debounce - elapsed, 0.0)
                self._timer = threading.Timer(delay, self._flush_async)
                self._timer.daemon = True
                self._timer.start()

    def flush(self) -> None:
        with self._lock:
            self._flush_locked()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            if self._timer is not None and self._timer.is_alive():
                self._timer.cancel()
                self._timer = None

    def _flush_async(self) -> None:
        with self._lock:
            self._flush_locked()

    def _flush_locked(self) -> None:
        if self._pending is None:
            return
        snapshot = self._pending
        self._pending = None
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        payload = snapshot.to_payload()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        tmp.replace(self._path)
        self._last_write_at = time.monotonic()


_writer_lock = threading.Lock()
_writer_cache: dict[str, DebouncedLiveStateWriter] = {}


def get_writer(workspace: Path | str, *, debounce_ms: int = DEFAULT_DEBOUNCE_MS) -> DebouncedLiveStateWriter:
    key = str(Path(workspace).resolve())
    with _writer_lock:
        writer = _writer_cache.get(key)
        if writer is None:
            writer = DebouncedLiveStateWriter(workspace, debounce_ms=debounce_ms)
            _writer_cache[key] = writer
        return writer


def write_live_state(workspace: Path | str, snapshot: LiveStateSnapshot) -> None:
    """Top-level convenience: debounced write through a per-workspace shared writer."""
    get_writer(workspace).update(snapshot)


def read_live_state(workspace: Path | str) -> dict[str, Any]:
    path = live_state_path(workspace)
    if not path.is_file():
        return {
            "status": "unavailable",
            "note": "Live state has not been written for this workspace yet.",
            "path": str(path),
        }
    try:
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("live_state.json is not an object")
        payload.setdefault("status", "available")
        payload.setdefault("path", str(path))
        return payload
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "status": "error",
            "note": f"Could not read live_state.json: {exc}",
            "path": str(path),
        }


def render_live_state_text(payload: dict[str, Any]) -> str:
    if payload.get("status") in {"unavailable", "error"}:
        return f"{payload.get('note', '')}\n{payload.get('path', '')}".strip()
    lines = [
        f"ts:                {payload.get('ts', '')}",
        f"surface:           {payload.get('dashboard_surface', '')}",
        f"profile:           {payload.get('profile_id', '')}",
        f"wizard_step:       {payload.get('wizard_step_id', '')} "
        f"({payload.get('wizard_step_index', -1)}/{payload.get('wizard_step_total', 0)})",
        f"queued_acks:       {', '.join(payload.get('queued_acknowledgments') or []) or '(none)'}",
    ]
    sub = payload.get("running_subprocess")
    if isinstance(sub, dict):
        lines.append(
            f"running_subprocess: {sub.get('name', '')} started_at={sub.get('started_at', '')} pid_present={sub.get('pid_present', False)}"
        )
    else:
        lines.append("running_subprocess: (none)")
    action = payload.get("last_operator_action")
    if isinstance(action, dict):
        lines.append(
            f"last_action:       {action.get('verb', '')} on {action.get('surface', '')} at {action.get('ts', '')}"
        )
    else:
        lines.append("last_action:       (none)")
    error = payload.get("last_error")
    lines.append(f"last_error:        {error if error else '(none)'}")
    return "\n".join(lines)
