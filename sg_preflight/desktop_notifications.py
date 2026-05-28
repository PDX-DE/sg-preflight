from __future__ import annotations

from datetime import datetime, timezone
import json
import platform
from pathlib import Path
import subprocess
from typing import Any

from sg_preflight.services import operator_ui_root


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_id(value: str) -> str:
    return "".join(character if character.isalnum() or character in "._-" else "_" for character in value) or "notification"


def _notification_root(workspace: Path | str) -> Path:
    root = operator_ui_root(Path(workspace).resolve()) / "notifications"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _powershell_script(title: str, message: str, timeout_ms: int) -> str:
    return f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$notify = New-Object System.Windows.Forms.NotifyIcon
$notify.Icon = [System.Drawing.SystemIcons]::Information
$notify.BalloonTipIcon = [System.Windows.Forms.ToolTipIcon]::Info
$notify.BalloonTipTitle = {json.dumps(title)}
$notify.BalloonTipText = {json.dumps(message)}
$notify.Text = "SGFX QA Preflight"
$notify.Visible = $true
$notify.ShowBalloonTip({max(timeout_ms, 1200)})
Start-Sleep -Milliseconds {max(timeout_ms, 1200)}
$notify.Visible = $false
$notify.Dispose()
"""


def notify_desktop_completion(
    *,
    title: str,
    message: str,
    workspace: Path | str,
    action_id: str = "",
    profile_id: str = "",
    evidence_path: Path | str | None = None,
    timeout_ms: int = 3500,
    dry_run: bool = False,
    runner: Any | None = None,
) -> dict[str, Any]:
    clean_title = title.strip() or "SGFX action complete"
    clean_message = message.strip() or "Local action completed."
    clean_action = action_id.strip() or "manual"
    clean_profile = profile_id.strip()
    record = {
        "status": "recorded",
        "delivery_status": "not_run",
        "shown": False,
        "title": clean_title,
        "message": clean_message,
        "action_id": clean_action,
        "profile_id": clean_profile,
        "evidence_path": str(evidence_path or ""),
        "created_at_utc": _utc_now(),
        "is_approval": False,
    }
    if dry_run:
        record["delivery_status"] = "skipped"
        record["detail"] = "Notification dry-run recorded without showing a desktop message."
    elif platform.system().casefold() != "windows":
        record["delivery_status"] = "unavailable"
        record["detail"] = "Desktop balloon notification is available only on Windows."
    else:
        command = [
            "powershell.exe",
            "-NoProfile",
            "-WindowStyle",
            "Hidden",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            _powershell_script(clean_title, clean_message, timeout_ms),
        ]
        try:
            completed = (runner or subprocess.run)(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(5, int(timeout_ms / 1000) + 5),
                check=False,
            )
        except Exception as exc:  # noqa: BLE001
            record["delivery_status"] = "failed"
            record["detail"] = str(exc)
        else:
            return_code = int(getattr(completed, "returncode", 1))
            record["delivery_status"] = "available" if return_code == 0 else "failed"
            record["shown"] = return_code == 0
            record["return_code"] = return_code
            record["method"] = "windows_shell_notification"
            stderr = str(getattr(completed, "stderr", "") or "").strip()
            if stderr:
                record["detail"] = stderr[-800:]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = _notification_root(workspace) / f"{stamp}-{_safe_id(clean_action)}.json"
    record["record_path"] = str(path)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return record


def notification_text(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"Notification: {payload.get('title', '')}",
            f"Status: {payload.get('delivery_status', 'unknown')}",
            f"Shown: {payload.get('shown', False)}",
            f"Record: {payload.get('record_path', '')}",
        ]
    )
