from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sg_preflight.cli._common import (
    RunRequest,
    _console_actions,
    _console_checkers,
    _console_profiles,
    _console_run_record,
    _console_safe,
    _console_setup_doctor,
    _emit_console,
    _emit_json,
    _emit_text,
    _resolve_render_format,
    _resolve_workspace,
    build_onboarding_guide,
    build_operator_handoff_snapshot,
    build_setup_doctor_report,
    execute_profile_run,
    get_run_profile,
    notification_text,
    notify_desktop_completion,
    parse_name_value_pairs,
    parse_packs,
    record_operator_handoff,
    render_onboarding_guide_markdown,
    render_onboarding_guide_text,
    render_operator_handoff_markdown,
    render_operator_handoff_text,
)


SUPPORT_COMMANDS = {
    "list-profiles",
    "list-actions",
    "list-checkers",
    "doctor",
    "run-profile",
    "operator-handoff",
    "onboarding-guide",
    "desktop-notification",
}


def handle_support_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.command == "list-profiles":
        output_format = _resolve_render_format(args, parser, formats=("text", "json"))
        _emit_console(lambda: _console_profiles(output_format == "json"), args)
        return 0

    if args.command == "list-actions":
        output_format = _resolve_render_format(args, parser, formats=("text", "json"))
        _emit_console(lambda: _console_actions(output_format == "json"), args)
        return 0

    if args.command == "list-checkers":
        output_format = _resolve_render_format(args, parser, formats=("text", "json"))
        _emit_console(lambda: _console_checkers(output_format == "json"), args)
        return 0

    if args.command == "doctor":
        doctor_root = _resolve_workspace(args)
        _console_setup_doctor(build_setup_doctor_report(doctor_root), as_json=args.json)
        return 0

    if args.command == "desktop-notification":
        notification_root = _resolve_workspace(args)
        if args.desktop_notification_command != "send":
            parser.error(f"Unhandled desktop-notification command: {args.desktop_notification_command}")
            return 1
        try:
            payload = notify_desktop_completion(
                title=args.title,
                message=args.message,
                workspace=notification_root,
                action_id=args.action_id,
                profile_id=args.profile,
                evidence_path=args.evidence_path,
                dry_run=bool(args.dry_run),
            )
        except Exception as exc:
            print(_console_safe(f"desktop-notification failed: {exc}"), file=sys.stderr)
            return 1
        output_format = _resolve_render_format(args, parser, formats=("text", "json"))
        if output_format == "json":
            _emit_json(payload, args)
        else:
            _emit_text(notification_text(payload), args)
        return 0

    if args.command == "operator-handoff":
        handoff_root = _resolve_workspace(args)
        try:
            if args.operator_handoff_command == "latest":
                payload = build_operator_handoff_snapshot(workspace=handoff_root, profile_id=args.profile)
            elif args.operator_handoff_command == "record":
                record_operator_handoff(
                    workspace=handoff_root,
                    profile_id=args.profile,
                    ticket_id=args.ticket,
                    stopping_point=args.stopping_point,
                    next_step=args.next_step,
                    note=args.note,
                )
                payload = build_operator_handoff_snapshot(workspace=handoff_root, profile_id=args.profile)
            else:
                parser.error(f"Unhandled operator-handoff command: {args.operator_handoff_command}")
                return 1
        except Exception as exc:
            print(_console_safe(f"operator-handoff failed: {exc}"), file=sys.stderr)
            return 1
        output_format = _resolve_render_format(args, parser)
        if output_format == "json":
            _emit_json(payload, args)
        elif output_format == "markdown":
            _emit_text(render_operator_handoff_markdown(payload), args)
        else:
            _emit_text(render_operator_handoff_text(payload), args)
        return 0

    if args.command == "onboarding-guide":
        guide_root = _resolve_workspace(args)
        try:
            if args.onboarding_guide_command == "read":
                payload = build_onboarding_guide(
                    args.profile,
                    workspace=guide_root,
                    bmw_root=Path(args.bmw_root).resolve() if getattr(args, "bmw_root", None) else None,
                )
            else:
                parser.error(f"Unhandled onboarding-guide command: {args.onboarding_guide_command}")
                return 1
        except Exception as exc:
            print(_console_safe(f"onboarding-guide failed: {exc}"), file=sys.stderr)
            return 1
        output_format = _resolve_render_format(args, parser)
        if output_format == "json":
            _emit_json(payload, args)
        elif output_format == "markdown":
            _emit_text(render_onboarding_guide_markdown(payload), args)
        else:
            _emit_text(render_onboarding_guide_text(payload), args)
        return 0

    if args.command == "run-profile":
        try:
            packs = parse_packs(args.packs)
            context = parse_name_value_pairs(args.context)
            profile = get_run_profile(args.profile_id)
        except (ValueError, KeyError) as exc:
            parser.error(str(exc))
            return 1

        try:
            record = execute_profile_run(
                profile,
                RunRequest(
                    profile_id=profile.profile_id,
                    packs=packs,
                    fail_on=args.fail_on,
                    context_overrides=context,
                    output_root=Path(args.output_root) if args.output_root else None,
                ),
            )
        except Exception as exc:
            print(_console_safe(f"run-profile failed: {exc}"), file=sys.stderr)
            return 1
        _console_run_record(record, as_json=args.json)
        return record.exit_code or 0

    parser.error(f"Unhandled support command: {args.command}")
    return 1
