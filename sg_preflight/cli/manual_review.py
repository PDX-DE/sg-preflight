"""Handles the manual-review CLI command family: session creation from scratch or
template, templates listing, auto-checks, assist, step recording, and RaCo/Blender
tool launch."""

from __future__ import annotations

import argparse
from importlib import import_module
import sys
from pathlib import Path

common = import_module("sg_preflight.cli")


def handle_manual_review_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.command == "manual-review":
        review_root = common._resolve_workspace(args)
        try:
            if args.manual_review_command == "session":
                if str(args.family or "").strip():
                    payload = common.create_manual_review_session_from_template(
                        profile_id=args.profile,
                        ticket_id=args.ticket,
                        family_id=args.family,
                        workspace=review_root,
                        output_root=Path(args.output_root).resolve() if args.output_root else None,
                        session_id=args.session_id,
                    )
                else:
                    payload = common.create_manual_review_session(
                        profile_id=args.profile,
                        ticket_id=args.ticket,
                        workspace=review_root,
                        output_root=Path(args.output_root).resolve() if args.output_root else None,
                        session_id=args.session_id,
                    )
            elif args.manual_review_command == "templates":
                payload = {
                    "status": "available",
                    "templates": list(common.list_car_review_templates()),
                    "manual_review_required": True,
                    "note": "Templates bootstrap local evidence checklists only; operator verdicts remain manual.",
                }
            elif args.manual_review_command == "auto-checks":
                payload = common.run_manual_review_auto_checks(args.profile, workspace=review_root)
            elif args.manual_review_command == "assist":
                payload = common.build_manual_review_assist(args.profile, workspace=review_root)
            elif args.manual_review_command == "record-step":
                payload = common.record_manual_review_step(
                    args.session_id,
                    args.step,
                    args.verdict,
                    workspace=review_root,
                    note=args.note,
                    screenshot=Path(args.screenshot).resolve() if args.screenshot else None,
                )
            elif args.manual_review_command == "summary":
                payload = common.load_manual_review_session(args.session_id, workspace=review_root)
            elif args.manual_review_command == "open-raco":
                payload = common.open_manual_review_tool(args.session_id, args.step, tool="raco", workspace=review_root)
            elif args.manual_review_command == "open-blender":
                payload = common.open_manual_review_tool(
                    args.session_id,
                    args.step,
                    tool="blender",
                    workspace=review_root,
                )
            else:
                parser.error(f"Unhandled manual-review command: {args.manual_review_command}")
                return 1
        except Exception as exc:
            print(common._console_safe(f"manual-review failed: {exc}"), file=sys.stderr)
            return 1
        if getattr(args, "json", False):
            common._console_desktop_payload(payload)
        elif getattr(args, "markdown", False) and args.manual_review_command == "auto-checks":
            print(common._console_safe(common.render_manual_review_auto_checks_markdown(payload)))
        elif getattr(args, "markdown", False) and args.manual_review_command == "assist":
            print(common._console_safe(common.render_manual_review_assist_markdown(payload)))
        elif getattr(args, "markdown", False) or args.manual_review_command == "summary":
            print(common._console_safe(common.render_manual_review_markdown(payload)))
        elif args.manual_review_command == "templates":
            print("Built-in car review templates:")
            for item in payload.get("templates", []):
                if isinstance(item, dict):
                    print(common._console_safe(f"- {item.get('family_id', '')}: {item.get('title', '')}"))
        elif args.manual_review_command == "auto-checks":
            print(common._console_safe(payload.get("summary", "Manual-review auto-checks complete.")))
        elif args.manual_review_command == "assist":
            print(common._console_safe(payload.get("summary", "Manual review assist complete.")))
        else:
            print(common._console_safe(f"Manual review session: {payload.get('session_id', '')}"))
            if payload.get("session_path"):
                print(common._console_safe(f"Session JSON: {payload['session_path']}"))
            if payload.get("markdown_path"):
                print(common._console_safe(f"Markdown: {payload['markdown_path']}"))
        return 0

    parser.error(f"Unhandled manual-review command: {args.command}")
    return 1
