"""CLI activity-log and session-log recording glue invoked around every command run.

Owns the raw-argv parsing helpers plus the activity-log entry writer and the
session-log start/event recorders that `main()` calls around every invocation.
"""

from __future__ import annotations

from pathlib import Path

from sg_preflight.activity_log import append_activity_entry


def _extract_arg_value(raw_args: list[str], *names: str) -> str:
    for index, item in enumerate(raw_args):
        if item in names and index + 1 < len(raw_args):
            return raw_args[index + 1]
        for name in names:
            prefix = f"{name}="
            if item.startswith(prefix):
                return item[len(prefix) :]
    return ""


def _activity_surface(raw_args: list[str]) -> str:
    parts = [item for item in raw_args[:3] if item and not item.startswith("-")]
    return " ".join(parts[:2] if len(parts) > 1 else parts) or "sg-preflight"


def _activity_verb(raw_args: list[str]) -> str:
    surface = " ".join(raw_args[:3]).lower()
    if "export" in surface or "materialize" in surface or "package" in surface:
        return "exported"
    if "run" in surface:
        return "ran"
    if "refresh" in surface:
        return "refreshed"
    return "read"


def _is_jira_integration_invocation(raw_args: list[str]) -> bool:
    return len(raw_args) > 1 and raw_args[0:2] == ["integration", "jira"]


def _record_cli_activity(raw_args: list[str], exit_code: int) -> None:
    # Skip self-recording for the observability surfaces themselves so they do
    # not pollute the very signal an operator is trying to inspect.
    if (
        not raw_args
        or raw_args[0] in {"activity-log", "live-state", "session-log"}
        or _is_jira_integration_invocation(raw_args)
    ):
        return
    import os

    workspace = _extract_arg_value(raw_args, "--workspace") or os.environ.get("SG_PREFLIGHT_ACTIVITY_WORKSPACE", "")
    if not workspace:
        return
    try:
        append_activity_entry(
            Path(workspace),
            verb=_activity_verb(raw_args),
            surface=_activity_surface(raw_args),
            profile=_extract_arg_value(raw_args, "--profile", "--profile-id"),
            outcome="ok" if exit_code == 0 else "error",
            note=f"cli exit {exit_code}",
        )
    except Exception:
        return


def _session_log_workspace(raw_args: list[str]) -> Path:
    import os

    workspace = (
        _extract_arg_value(raw_args, "--workspace")
        or os.environ.get("SG_PREFLIGHT_ACTIVITY_WORKSPACE", "")
        or os.environ.get("SGFX_PREFLIGHT_WORKSPACE", "")
    )
    return Path(workspace).resolve() if workspace else Path.cwd().resolve()


def _start_cli_session_log(raw_args: list[str]) -> None:
    if (raw_args and raw_args[0] == "session-log") or _is_jira_integration_invocation(raw_args):
        return
    try:
        from sg_preflight.session_log import event as session_event
        from sg_preflight.session_log import install_exception_hooks, start_session_log

        workspace = _session_log_workspace(raw_args)
        start_session_log(workspace, surface=_activity_surface(raw_args), detail={"command": list(raw_args)})
        install_exception_hooks()
        session_event(
            source="cli",
            surface=_activity_surface(raw_args),
            profile=_extract_arg_value(raw_args, "--profile", "--profile-id"),
            message="CLI invocation started",
            detail={"command": list(raw_args), "workspace": str(workspace)},
        )
    except Exception:
        return


def _record_cli_session_event(raw_args: list[str], exit_code: int) -> None:
    if (raw_args and raw_args[0] == "session-log") or _is_jira_integration_invocation(raw_args):
        return
    try:
        from sg_preflight.session_log import event as session_event

        session_event(
            source="cli",
            surface=_activity_surface(raw_args),
            profile=_extract_arg_value(raw_args, "--profile", "--profile-id"),
            message="CLI invocation completed",
            level="info" if exit_code == 0 else "error",
            detail={"command": list(raw_args), "exit_code": exit_code},
        )
    except Exception:
        return
