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


def handle_jira_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.command == "jira":
        jira_root = common._resolve_workspace(args)
        try:
            if args.jira_command == "register":
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
            elif args.jira_command == "status":
                payload = common.jira_status(
                    ticket=args.ticket,
                    api_version=args.api_version,
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
                )
            elif args.jira_command == "attach-file":
                payload = common.attach_jira_file_action(
                    args.ticket,
                    Path(args.file),
                    api_version=args.api_version,
                    auto_confirm=args.auto_confirm,
                )
            elif args.jira_command == "post":
                if args.dry_run and args.confirm:
                    parser.error("--dry-run and --confirm cannot be combined")
                    return 1
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
                    source=source.source,
                    section=source.section,
                )
            else:
                parser.error(f"Unhandled jira command: {args.jira_command}")
                return 1
        except (ConfigError, JiraPostError) as exc:
            label = "Jira post failed" if args.jira_command == "post" else "Jira REST failed"
            print(common._console_safe(f"{label}: {exc}"), file=sys.stderr)
            return 1
        output_format = common._resolve_render_format(args, parser)
        if output_format == "json":
            common._emit_json(payload, args)
        elif output_format == "markdown":
            renderer = render_jira_post_markdown if args.jira_command == "post" else render_jira_action_markdown
            common._emit_text(renderer(payload), args)
        else:
            renderer = render_jira_post_text if args.jira_command == "post" else render_jira_action_text
            common._emit_text(renderer(payload), args)
        return 0

    parser.error(f"Unhandled jira command: {args.command}")
    return 1
