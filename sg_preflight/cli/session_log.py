"""CLI handlers for listing, reading, and exporting local session activity logs."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from sg_preflight.cli._common import _console_safe, _emit_json, _emit_text, _resolve_render_format
from sg_preflight.session_log import (
    export_session_log,
    latest_session_payload,
    list_session_logs,
    render_session_log_text,
)


def _list_payload(workspace: Path, *, limit: int) -> dict[str, object]:
    logs = list_session_logs(workspace, limit=limit)
    return {
        "workspace": str(workspace),
        "logs": [str(path) for path in logs],
        "count": len(logs),
    }


def _render_list_text(payload: dict[str, object]) -> str:
    logs = payload.get("logs")
    if not isinstance(logs, list) or not logs:
        return "No session logs found."
    lines = [f"Session logs for {payload.get('workspace', '')}:"]
    lines.extend(f"- {path}" for path in logs)
    return "\n".join(lines)


def handle_session_log_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    workspace_arg = str(getattr(args, "workspace", "") or "").strip()
    workspace = Path(
        workspace_arg
        or os.environ.get("SG_PREFLIGHT_ACTIVITY_WORKSPACE", "")
        or os.environ.get("SGFX_PREFLIGHT_WORKSPACE", "")
        or Path.cwd()
    ).resolve()
    output_format = _resolve_render_format(args, parser, formats=("text", "json"))
    try:
        if args.session_log_command == "latest":
            payload = latest_session_payload(workspace, tail=max(0, int(args.tail)))
            if output_format == "json":
                _emit_json(payload, args)
            else:
                _emit_text(render_session_log_text(payload), args)
            return 0
        if args.session_log_command == "list":
            payload = _list_payload(workspace, limit=max(0, int(args.limit)))
            if output_format == "json":
                _emit_json(payload, args)
            else:
                _emit_text(_render_list_text(payload), args)
            return 0
        if args.session_log_command == "export":
            payload = export_session_log(workspace, zip_output=args.zip_output)
            if output_format == "json":
                _emit_json(payload, args)
            else:
                _emit_text(
                    (
                        f"Session diagnostic export written to {payload['zip_path']}\n"
                        f"Included {len(payload['included_files'])} file(s)."
                    ),
                    args,
                )
            return 0
        parser.error(f"Unhandled session-log command: {args.session_log_command}")
        return 1
    except Exception as exc:
        print(_console_safe(f"session-log failed: {exc}"), file=sys.stderr)
        return 1
