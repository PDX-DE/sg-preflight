from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from sg_preflight.activity_log import (
    append_activity_entry,
    activity_log_path,
    read_activity_entries,
    render_activity_log_text,
)
from sg_preflight.cli._common import (
    _console_safe,
    _emit_json,
    _emit_text,
    _json_text,
    _resolve_render_format,
)


def _stream_activity_log_tail(
    workspace: Path,
    *,
    profile: str,
    since: str,
    limit: int,
    interval: float,
    as_json: bool,
) -> int:
    log_path = activity_log_path(workspace)
    print(_console_safe(f"Tailing {log_path} (Ctrl-C to stop)"))
    seen_keys: set[str] = set()
    initial = read_activity_entries(workspace, profile=profile, since=since, limit=max(limit, 1000))
    for entry in initial.get("entries", []):
        seen_keys.add(_activity_entry_key(entry))
    try:
        while True:
            payload = read_activity_entries(workspace, profile=profile, since=since, limit=max(limit, 1000))
            new_entries = []
            for entry in payload.get("entries", []):
                key = _activity_entry_key(entry)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                new_entries.append(entry)
            if new_entries:
                for entry in reversed(new_entries):
                    if as_json:
                        print(_json_text(entry))
                    else:
                        print(_console_safe(
                            f"{entry.get('ts', '')} {entry.get('verb', '')} "
                            f"{entry.get('surface', '')} {entry.get('profile', '')} "
                            f"{entry.get('outcome', '')} {entry.get('note', '')}".rstrip()
                        ))
                try:
                    sys.stdout.flush()
                except OSError:
                    pass
            try:
                time.sleep(max(interval, 0.05))
            except KeyboardInterrupt:
                break
    except KeyboardInterrupt:
        print(_console_safe("\nactivity-log tail stopped."))
    return 0


def _activity_entry_key(entry: dict) -> str:
    return "|".join([
        str(entry.get("ts", "")),
        str(entry.get("verb", "")),
        str(entry.get("surface", "")),
        str(entry.get("profile", "")),
        str(entry.get("note", "")),
    ])


def _stream_live_state_tail(
    workspace: Path,
    *,
    interval: float,
    as_json: bool,
) -> int:
    from sg_preflight.live_state import live_state_path, read_live_state, render_live_state_text

    state_path = live_state_path(workspace)
    print(_console_safe(f"Tailing {state_path} (Ctrl-C to stop)"))
    last_ts = ""
    try:
        while True:
            payload = read_live_state(workspace)
            current_ts = str(payload.get("ts", ""))
            if current_ts and current_ts != last_ts:
                if as_json:
                    print(_json_text(payload))
                else:
                    print(_console_safe(render_live_state_text(payload)))
                    print(_console_safe("---"))
                try:
                    sys.stdout.flush()
                except OSError:
                    pass
                last_ts = current_ts
            try:
                time.sleep(max(interval, 0.05))
            except KeyboardInterrupt:
                break
    except KeyboardInterrupt:
        print(_console_safe("\nlive-state tail stopped."))
    return 0


def handle_activity_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.command == "activity-log":
        activity_root = Path(args.workspace).resolve()
        try:
            if args.activity_log_command == "read":
                if getattr(args, "tail", False):
                    return _stream_activity_log_tail(
                        activity_root,
                        profile=args.profile,
                        since=args.since,
                        limit=args.limit,
                        interval=float(getattr(args, "tail_interval", 0.5)),
                        as_json=_resolve_render_format(args, parser, formats=("text", "json")) == "json",
                    )
                payload = read_activity_entries(
                    activity_root,
                    profile=args.profile,
                    since=args.since,
                    limit=args.limit,
                )
                output_format = _resolve_render_format(args, parser, formats=("text", "json"))
                if output_format == "json":
                    _emit_json(payload, args)
                else:
                    _emit_text(render_activity_log_text(payload), args)
                return 0
            if args.activity_log_command == "append":
                entry = append_activity_entry(
                    activity_root,
                    verb=args.verb,
                    surface=args.surface,
                    profile=args.profile,
                    outcome=args.outcome,
                    note=args.note,
                )
                payload = {"note": "Activity entry appended locally.", "entry": entry}
                if args.json:
                    _emit_json(payload, args)
                else:
                    _emit_text(render_activity_log_text({"entries": [entry], "note": payload["note"]}), args)
                return 0
            parser.error(f"Unhandled activity-log command: {args.activity_log_command}")
            return 1
        except Exception as exc:
            print(_console_safe(f"activity-log failed: {exc}"), file=sys.stderr)
            return 1

    if args.command == "live-state":
        live_root = Path(args.workspace).resolve()
        as_json = _resolve_render_format(args, parser, formats=("text", "json")) == "json"
        try:
            if getattr(args, "tail", False):
                return _stream_live_state_tail(
                    live_root,
                    interval=float(getattr(args, "tail_interval", 0.25)),
                    as_json=as_json,
                )
            from sg_preflight.live_state import read_live_state, render_live_state_text
            payload = read_live_state(live_root)
            if as_json:
                _emit_json(payload, args)
            else:
                _emit_text(render_live_state_text(payload), args)
            return 0
        except Exception as exc:
            print(_console_safe(f"live-state failed: {exc}"), file=sys.stderr)
            return 1

    parser.error(f"Unhandled activity command: {args.command}")
    return 1
