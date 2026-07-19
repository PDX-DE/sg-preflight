"""Handles the full-qa-pass, bmw-pipeline-diagnostics, bmw-git-readiness, and
qa-hero-readiness CLI commands."""

from __future__ import annotations

import argparse
from importlib import import_module
import sys
from pathlib import Path

common = import_module("sg_preflight.cli")


def handle_readiness_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.command == "full-qa-pass":
        pass_root = common._resolve_workspace(args)
        try:
            if args.full_qa_pass_command == "run":
                payload = common.build_full_qa_pass(
                    args.profile,
                    workspace=pass_root,
                    bmw_root=Path(args.bmw_root).resolve() if getattr(args, "bmw_root", None) else None,
                    comparison_profile=args.comparison_profile,
                    trusted_tool_mode=bool(args.trusted_tool_mode),
                    halt_on_flagged_issue=not bool(args.no_halt),
                )
            else:
                parser.error(f"Unhandled full-qa-pass command: {args.full_qa_pass_command}")
                return 1
        except Exception as exc:
            print(common._console_safe(f"full-qa-pass failed: {exc}"), file=sys.stderr)
            return 1
        output_format = common._resolve_render_format(args, parser)
        if output_format == "json":
            common._emit_json(payload, args)
        elif output_format == "markdown":
            common._emit_text(common.render_full_qa_pass_markdown(payload), args)
        else:
            common._emit_text(common.render_full_qa_pass_text(payload), args)
        return 0

    if args.command == "bmw-pipeline-diagnostics":
        diagnostic_root = common._resolve_workspace(args)
        if args.bmw_pipeline_diagnostics_command != "missing-actuals":
            parser.error(f"Unhandled bmw-pipeline-diagnostics command: {args.bmw_pipeline_diagnostics_command}")
            return 1
        if not args.profile and not args.project_root:
            parser.error("bmw-pipeline-diagnostics missing-actuals needs either --profile or --project-root")
            return 1
        try:
            if args.project_root:
                project_root = Path(args.project_root).resolve()
                profile_id = args.profile or project_root.name
            else:
                profile = common.get_run_profile(args.profile, diagnostic_root, bmw_root=args.bmw_root)
                profile_id = profile.profile_id
                project_root = profile.source_project_root()
            output_root = (
                Path(args.output_root).resolve()
                if args.output_root
                else diagnostic_root / "out" / f"{str(profile_id).strip().lower()}-missing-actual-diagnostics"
            )
            payload = common.run_missing_actual_diagnostic_chain(
                profile_id=str(profile_id),
                workspace=diagnostic_root,
                bmw_root=Path(args.bmw_root).resolve() if args.bmw_root else None,
                project_root=project_root,
                expected_root=Path(args.expected_root).resolve() if args.expected_root else None,
                candidate_roots=tuple(Path(item).resolve() for item in args.candidate_root if str(item).strip()),
                diff_reference_roots=tuple(Path(item).resolve() for item in args.diff_root if str(item).strip()),
                output_root=output_root,
                operator_confirmed_read_refresh=bool(args.auto_confirm_read_refresh),
                retry_capture=bool(args.retry_capture),
                operator_confirmed_retry_capture=bool(args.auto_confirm_retry_capture),
            )
        except Exception as exc:
            print(common._console_safe(f"bmw-pipeline-diagnostics failed: {exc}"), file=sys.stderr)
            return 1
        output_format = common._resolve_render_format(args, parser)
        if output_format == "json":
            common._emit_json(payload, args)
        elif output_format == "markdown":
            common._emit_text(common.render_missing_actual_diagnostic_markdown(payload), args)
        else:
            common._emit_text(common.render_missing_actual_diagnostic_text(payload), args)
        return 0

    if args.command == "bmw-git-readiness":
        readiness_root = common._resolve_workspace(args)
        try:
            if args.bmw_git_readiness_command == "read":
                payload = common.read_bmw_git_readiness(
                    args.profile,
                    workspace=readiness_root,
                    bmw_root=Path(args.bmw_root).resolve() if args.bmw_root else None,
                )
            else:
                parser.error(f"Unhandled bmw-git-readiness command: {args.bmw_git_readiness_command}")
                return 1
        except Exception as exc:
            print(common._console_safe(f"bmw-git-readiness failed: {exc}"), file=sys.stderr)
            return 1
        output_format = common._resolve_render_format(args, parser)
        if output_format == "json":
            common._emit_json(payload, args)
        elif output_format == "markdown":
            common._emit_text(common.render_bmw_git_readiness_markdown(payload), args)
        else:
            common._emit_text(common.render_bmw_git_readiness_text(payload), args)
        return 0

    if args.command == "qa-hero-readiness":
        readiness_root = common._resolve_workspace(args)
        try:
            if args.qa_hero_readiness_command == "read":
                payload = common.read_qa_hero_readiness(
                    args.profile,
                    workspace=readiness_root,
                    bmw_root=Path(args.bmw_root).resolve() if args.bmw_root else None,
                )
            else:
                parser.error(f"Unhandled qa-hero-readiness command: {args.qa_hero_readiness_command}")
                return 1
        except Exception as exc:
            print(common._console_safe(f"qa-hero-readiness failed: {exc}"), file=sys.stderr)
            return 1
        output_format = common._resolve_render_format(args, parser)
        if output_format == "json":
            common._emit_json(payload, args)
        elif output_format == "markdown":
            common._emit_text(common.render_qa_hero_readiness_markdown(payload), args)
        else:
            common._emit_text(common.render_qa_hero_readiness_text(payload), args)
        return 0

    parser.error(f"Unhandled readiness command: {args.command}")
    return 1
