"""Handles the confirmation-gated Jira REST CLI commands: register, status,
weekly-tickets, post-comment, update-issue, attach-file, and post."""

from __future__ import annotations

import argparse
import getpass
from importlib import import_module
import json
import sys
from pathlib import Path

from sg_preflight.jira_client import (
    ConfigError,
    JiraPostError,
    render_jira_action_markdown,
    render_jira_action_text,
    render_jira_post_markdown,
    render_jira_post_text,
)

common = import_module("sg_preflight.cli")


def _jira_registration_preview(args: argparse.Namespace) -> dict[str, object]:
    jira_url = str(args.jira_url or "").strip().rstrip("/")
    credential_path = (
        str(Path(args.state_dir).expanduser() / "jira_pat.json")
        if args.state_dir
        else "operator profile (resolved after confirmation)"
    )
    return {
        "status": "skipped",
        "action": "register",
        "dry_run": True,
        "confirm_local_write_required": True,
        "local_write_confirmed": False,
        "credential": {
            "jira_url": jira_url,
            "credential_path": credential_path,
            "pat_loaded": False,
        },
        "confirmation": {
            "title": "Store Jira credentials?",
            "warning": "The Jira URL config is written locally and the PAT is stored in the OS keychain.",
        },
        "guard": "No PAT source was read and no credential state was written. Re-run with --confirm-local-write.",
        "is_approval": False,
    }


def handle_jira_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.command == "integration" and args.integration_command == "jira":
        try:
            if args.jira_command == "register":
                if not args.confirm_local_write:
                    payload = _jira_registration_preview(args)
                else:
                    jira_url = str(args.jira_url or "").strip() or input("Jira URL: ").strip()
                    if args.pat_file:
                        pat = Path(args.pat_file).expanduser().read_text(encoding="utf-8").strip()
                    else:
                        pat = getpass.getpass("Jira PAT: ").strip()
                    payload = common.write_jira_credentials(
                        jira_url=jira_url,
                        pat=pat,
                        state_dir=Path(args.state_dir).expanduser() if args.state_dir else None,
                        overwrite=args.force,
                    )
                    payload.update(
                        {
                            "action": "register",
                            "dry_run": False,
                            "confirm_local_write_required": False,
                            "local_write_confirmed": True,
                        }
                    )
            elif args.jira_command == "status":
                payload = common.jira_status(
                    ticket=args.ticket,
                    api_version=args.api_version,
                    confirm_network=args.confirm_network,
                )
            elif args.jira_command == "weekly-tickets":
                payload = common.build_weekly_ticket_draft(
                    since=args.since,
                    workspace=common._resolve_workspace(args),
                    confirm_network=args.confirm_network,
                )
            elif args.jira_command == "post-comment":
                source = common.load_jira_comment_source(
                    body=args.body,
                    body_file=Path(args.body_file).resolve() if args.body_file else None,
                )
                payload = common.post_jira_comment_action(
                    args.ticket,
                    source.body,
                    api_version=args.api_version,
                    auto_confirm=args.auto_confirm,
                    confirm_network=args.confirm_network,
                    source=source.source,
                    section=source.section,
                )
            elif args.jira_command == "update-issue":
                try:
                    fields = json.loads(args.fields)
                except json.JSONDecodeError as exc:
                    raise JiraPostError(f"--fields must be valid JSON: {exc}") from exc
                payload = common.update_jira_issue_action(
                    args.ticket,
                    fields,
                    api_version=args.api_version,
                    auto_confirm=args.auto_confirm,
                    confirm_network=args.confirm_network,
                )
            elif args.jira_command == "attach-file":
                payload = common.attach_jira_file_action(
                    args.ticket,
                    Path(args.file),
                    api_version=args.api_version,
                    auto_confirm=args.auto_confirm,
                    confirm_network=args.confirm_network,
                )
            elif args.jira_command == "post":
                if args.dry_run and args.confirm:
                    parser.error("--dry-run and --confirm cannot be combined")
                    return 1
                jira_root = common._resolve_workspace(args)
                source = common.load_jira_comment_source(
                    body=args.body,
                    body_file=Path(args.body_file).resolve() if args.body_file else None,
                    section=args.section,
                    wording_file=Path(args.wording_file).resolve() if args.wording_file else None,
                    workspace=jira_root,
                )
                payload = common.post_jira_comment(
                    args.ticket,
                    source.body,
                    base_url=args.base_url,
                    base_url_env=args.base_url_env,
                    token_env=args.token_env,
                    api_version=args.api_version,
                    confirm=args.confirm,
                    confirm_network=args.confirm_network,
                    source=source.source,
                    section=source.section,
                )
            else:
                parser.error(f"Unhandled jira command: {args.jira_command}")
                return 1
        except (ConfigError, JiraPostError, ValueError) as exc:
            if args.jira_command == "weekly-tickets":
                label = "weekly-tickets failed"
            else:
                label = "Jira post failed" if args.jira_command == "post" else "Jira REST failed"
            print(common._console_safe(f"{label}: {exc}"), file=sys.stderr)
            return 1
        output_format = common._resolve_render_format(args, parser)
        if output_format == "json":
            common._emit_json(payload, args)
        elif output_format == "markdown":
            if args.jira_command == "weekly-tickets":
                renderer = common.render_weekly_ticket_draft_markdown
            else:
                renderer = render_jira_post_markdown if args.jira_command == "post" else render_jira_action_markdown
            common._emit_text(renderer(payload), args)
        else:
            if args.jira_command == "weekly-tickets":
                renderer = common.render_weekly_ticket_draft_text
            else:
                renderer = render_jira_post_text if args.jira_command == "post" else render_jira_action_text
            common._emit_text(renderer(payload), args)
        return 0

    parser.error(f"Unhandled jira command: {args.command}")
    return 1
