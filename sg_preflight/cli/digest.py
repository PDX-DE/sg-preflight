from __future__ import annotations

import argparse
from importlib import import_module
import sys
from pathlib import Path

common = import_module("sg_preflight.cli")


_BATTERY_DEFAULT_FILTERS = (
    "default",
    "openAllDoors_",
    "lights_drl_front",
    "lights_LowBeam",
    "lights_HighBeam",
    "lights_OnlyCones",
    "welcome_animation_",
    "automatic_Doors_",
    "highlighting_Doors",
)


def handle_digest_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.command == "daily-qa-snapshot":
        snapshot_root = common._resolve_workspace(args)
        output_root = Path(args.output_root).resolve() if args.output_root else None
        profile_ids = tuple(str(item).strip() for item in args.profile if str(item).strip())
        battery_filters = tuple(str(item).strip() for item in args.battery_filter if str(item).strip())
        if args.battery_defaults:
            battery_filters = _BATTERY_DEFAULT_FILTERS + tuple(
                item for item in battery_filters if item not in _BATTERY_DEFAULT_FILTERS
            )
        try:
            result = common.materialize_daily_qa_snapshot(
                workspace_root=snapshot_root,
                output_root=output_root,
                profile_ids=profile_ids or ("NA8", "G78", "G50"),
                run_smoke=not args.no_smoke,
                smoke_test=args.smoke_test,
                battery_filters=battery_filters,
            )
        except Exception as exc:
            print(common._console_safe(f"daily-qa-snapshot failed: {exc}"), file=sys.stderr)
            return 1
        common._console_daily_snapshot(result, as_json=args.json)
        return 0

    if args.command == "daily-digest":
        digest_root = common._resolve_workspace(args)
        try:
            if args.daily_digest_command == "latest":
                payload = common.build_latest_daily_digest(args.ticket_id, digest_root)
            else:
                parser.error(f"Unhandled daily-digest command: {args.daily_digest_command}")
                return 1
        except Exception as exc:
            print(common._console_safe(f"daily-digest failed: {exc}"), file=sys.stderr)
            return 1
        output_format = common._resolve_render_format(args, parser)
        if output_format == "json":
            common._emit_json(payload, args)
        elif output_format == "markdown":
            common._emit_text(common.render_daily_digest_markdown(payload), args)
        else:
            common._emit_text(common.render_daily_digest_text(payload), args)
        return 0

    if args.command == "team-digest-board":
        board_root = common._resolve_workspace(args)
        try:
            if args.team_digest_board_command == "snapshot":
                payload = common.build_team_daily_digest_board(
                    workspace=board_root,
                    bmw_root=Path(args.bmw_root).resolve() if args.bmw_root else None,
                    profiles=tuple(args.profile),
                    ticket_id=args.ticket_id,
                )
            else:
                parser.error(f"Unhandled team-digest-board command: {args.team_digest_board_command}")
                return 1
        except Exception as exc:
            print(common._console_safe(f"team-digest-board failed: {exc}"), file=sys.stderr)
            return 1
        output_format = common._resolve_render_format(args, parser)
        if output_format == "json":
            common._emit_json(payload, args)
        elif output_format == "markdown":
            common._emit_text(common.render_team_digest_board_markdown(payload), args)
        else:
            common._emit_text(common.render_team_digest_board_text(payload), args)
        return 0

    parser.error(f"Unhandled digest command: {args.command}")
    return 1
