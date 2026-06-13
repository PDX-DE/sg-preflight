from __future__ import annotations

import argparse
from importlib import import_module
import json
import sys
from pathlib import Path

common = import_module("sg_preflight.cli")


def _console_ticket_review(result: object, *, as_json: bool = False) -> None:
    bundle = result.bundle
    if as_json:
        print(json.dumps(bundle.to_dict(), indent=2, ensure_ascii=False))
        return

    print(f"Ticket: {bundle.ticket_id} ({bundle.title})")
    print(f"Overall status: {bundle.overall_status}")
    print(f"Profiles: {', '.join(bundle.profile_ids) if bundle.profile_ids else 'none confirmed'}")
    print(f"Package root: {result.package_root}")
    print(f"ZIP: {result.zip_path}")
    print(f"Review status: {result.review_status_path}")
    print(f"DoD matrix: {result.dod_matrix_path}")
    print(f"DoD update draft: {result.dod_update_draft_path}")
    print(f"Teams update: {result.teams_update_path}")
    print(f"Stakeholder sync: {result.stakeholder_sync_path}")
    print(f"Review protocol: {result.review_protocol_path}")
    print(f"Owner matrix: {result.owner_matrix_path}")
    print(f"QA capability matrix: {result.qa_capability_matrix_path}")
    print(f"3D QA playbook: {result.three_d_qa_playbook_path}")
    print(f"Repo topology reference: {result.repo_topology_reference_path}")
    print(f"Delivery surface map: {result.delivery_surface_map_path}")
    print(f"RaCo script catalog: {result.raco_script_catalog_path}")
    print(f"Delivery target catalog: {result.delivery_target_catalog_path}")
    print(f"Manual review companion: {result.manual_review_companion_path}")
    print(f"Manual evidence index: {result.manual_evidence_index_path}")
    print(f"Manual evidence JSON: {result.manual_evidence_json_path}")
    print(f"Review-owner decisions: {result.review_owner_decisions_path}")
    print(f"Sent package manifest: {result.sent_package_manifest_path}")
    print(f"ZIP SHA256 sidecar: {result.zip_sha256_path}")
    if bundle.findings:
        print("Findings:")
        for finding in bundle.findings[:5]:
            location = finding.path
            if finding.line is not None and location:
                location = f"{location}:{finding.line}"
            print(f"  - [{finding.severity}] {finding.summary} :: {location or 'path unavailable'}")


def handle_evidence_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.command == "risk-score":
        risk_root = common._resolve_workspace(args)
        try:
            if args.risk_score_command == "read":
                payload = common.read_per_car_risk_score(
                    args.profile,
                    workspace=risk_root,
                    bmw_root=Path(args.bmw_root).resolve() if args.bmw_root else None,
                )
            else:
                parser.error(f"Unhandled risk-score command: {args.risk_score_command}")
                return 1
        except Exception as exc:
            print(common._console_safe(f"risk-score failed: {exc}"), file=sys.stderr)
            return 1
        output_format = common._resolve_render_format(args, parser)
        if output_format == "json":
            common._emit_json(payload, args)
        elif output_format == "markdown":
            common._emit_text(common.render_risk_score_markdown(payload), args)
        else:
            common._emit_text(common.render_risk_score_text(payload), args)
        return 0

    if args.command == "cross-car-comparison":
        comparison_root = common._resolve_workspace(args)
        try:
            if args.cross_car_comparison_command == "snapshot":
                payload = common.build_cross_car_comparison(
                    workspace=comparison_root,
                    bmw_root=Path(args.bmw_root).resolve() if args.bmw_root else None,
                    left_profile=args.left_profile,
                    right_profile=args.right_profile,
                )
            else:
                parser.error(f"Unhandled cross-car-comparison command: {args.cross_car_comparison_command}")
                return 1
        except Exception as exc:
            print(common._console_safe(f"cross-car-comparison failed: {exc}"), file=sys.stderr)
            return 1
        output_format = common._resolve_render_format(args, parser)
        if output_format == "json":
            common._emit_json(payload, args)
        elif output_format == "markdown":
            common._emit_text(common.render_cross_car_comparison_markdown(payload), args)
        else:
            common._emit_text(common.render_cross_car_comparison_text(payload), args)
        return 0

    if args.command == "profile-summary":
        if args.profile_summary_command == "build":
            from sg_preflight import __version__ as sgfx_version  # noqa: F401
            from sg_preflight.profile_summary import build_profile_summary, write_profile_summary_html

            workspace_path = Path(args.workspace).resolve()
            bmw_root_value = Path(args.bmw_root).resolve() if getattr(args, "bmw_root", None) else None
            output_path = Path(args.html_output).resolve()
            try:
                build_commit, exe_sha256 = common._build_metadata_for_summary()
                summary = build_profile_summary(
                    args.profile,
                    workspace=workspace_path,
                    bmw_root=bmw_root_value,
                    history_limit=int(getattr(args, "history_limit", 5)),
                    build_commit=build_commit,
                    exe_sha256=exe_sha256,
                    notes=list(getattr(args, "note", []) or []),
                )
            except Exception as exc:
                print(common._console_safe(f"profile-summary build failed: {exc}"), file=sys.stderr)
                return 1
            try:
                from sg_preflight.risk_sparkline import (
                    build_sparkline_data,
                    render_sparkline_svg,
                    sparkline_fallback_text,
                )

                spark_data = build_sparkline_data(summary.full_qa_runs)
                spark_svg = render_sparkline_svg(spark_data)
                spark_fallback = sparkline_fallback_text(spark_data)
            except Exception:
                spark_svg = ""
                spark_fallback = ""
            write_profile_summary_html(
                summary,
                output_path,
                sparkline_svg=spark_svg,
                sparkline_fallback_text=spark_fallback,
            )
            payload = summary.to_payload()
            payload["output_path"] = str(output_path)
            output_format = common._resolve_render_format(args, parser, formats=("text", "json"))
            if output_format == "json":
                common._emit_json(payload, args)
            else:
                common._emit_text(
                    common._console_safe(
                        f"Wrote {output_path}\n"
                        f"profile:    {summary.profile_id}\n"
                        f"generated:  {summary.generated_at_utc}\n"
                        f"workbook:   {payload.get('workbook', {}).get('status', 'unavailable')}\n"
                        f"jira:       {payload.get('jira_tickets', {}).get('status', 'unavailable')}\n"
                        f"runs:       {len(payload.get('full_qa_runs', []))} included"
                    ),
                    args,
                )
            return 0
        if args.profile_summary_command == "export":
            from sg_preflight.profile_export import export_profile_evidence
            from sg_preflight.profile_summary import build_profile_summary, render_profile_summary_html

            workspace_path = Path(args.workspace).resolve()
            bmw_root_value = Path(args.bmw_root).resolve() if getattr(args, "bmw_root", None) else None
            zip_output = Path(args.zip_output).resolve()
            try:
                build_commit, exe_sha256 = common._build_metadata_for_summary()
                summary = build_profile_summary(
                    args.profile,
                    workspace=workspace_path,
                    bmw_root=bmw_root_value,
                    history_limit=int(getattr(args, "history_limit", 10)),
                    build_commit=build_commit,
                    exe_sha256=exe_sha256,
                )
                try:
                    from sg_preflight.risk_sparkline import (
                        build_sparkline_data,
                        render_sparkline_svg,
                        sparkline_fallback_text,
                    )

                    spark_data = build_sparkline_data(summary.full_qa_runs)
                    spark_svg = render_sparkline_svg(spark_data)
                    spark_fallback = sparkline_fallback_text(spark_data)
                except Exception:
                    spark_svg = ""
                    spark_fallback = ""
                summary_html = render_profile_summary_html(
                    summary,
                    sparkline_svg=spark_svg,
                    sparkline_fallback_text=spark_fallback,
                )
                result = export_profile_evidence(
                    profile_id=args.profile,
                    workspace=workspace_path,
                    bmw_root=bmw_root_value,
                    output_path=zip_output,
                    activity_log_window_days=int(getattr(args, "activity_log_window_days", 7)),
                    build_commit=build_commit,
                    exe_sha256=exe_sha256,
                    summary_html=summary_html,
                )
            except Exception as exc:
                print(common._console_safe(f"profile-summary export failed: {exc}"), file=sys.stderr)
                return 1
            payload = result.to_payload()
            output_format = common._resolve_render_format(args, parser, formats=("text", "json"))
            if output_format == "json":
                common._emit_json(payload, args)
            else:
                lines = [
                    f"Wrote {result.zip_path}",
                    f"profile:        {result.profile_id}",
                    f"generated:      {result.generated_at_utc}",
                    f"entries:        {len(result.entries)}",
                    f"sanitization:   {len(result.sanitization_log)} action(s) logged",
                ]
                common._emit_text(common._console_safe("\n".join(lines)), args)
            return 0
        parser.error(f"Unhandled profile-summary command: {args.profile_summary_command}")
        return 1

    if args.command == "ticket-review":
        review_root = common._resolve_workspace(args)
        output_root = (
            Path(args.output_root).resolve()
            if args.output_root
            else common.default_ticket_review_output_root(args.ticket_id, review_root)
        )
        try:
            result = common.materialize_ticket_review_bundle(
                args.ticket_id,
                title=args.title or args.ticket_id,
                profile_ids=tuple(str(item).strip() for item in args.profile if str(item).strip()),
                workspace=review_root,
                output_root=output_root,
                scope_note=args.scope_note,
                candidate_roots=tuple(Path(item).resolve() for item in args.candidate_root if str(item).strip()),
                include_action_bundles=not args.sendable,
            )
        except Exception as exc:
            print(common._console_safe(f"ticket-review failed: {exc}"), file=sys.stderr)
            return 1
        common._console_ticket_review(result, as_json=args.json)
        return 0

    if args.command == "quality-hero-report":
        report_root = common._resolve_workspace(args)
        if args.quality_hero_report_command != "generate":
            parser.error(f"Unhandled quality-hero-report command: {args.quality_hero_report_command}")
            return 1
        output_root = (
            Path(args.output_root).resolve()
            if args.output_root
            else report_root / "out" / f"{str(args.profile).strip().lower()}-quality-hero-report"
        )
        try:
            bundle = common.build_quality_hero_report(
                profile_id=args.profile,
                workspace=report_root,
                output_root=output_root,
                ticket_id=args.ticket,
                bmw_root=args.bmw_root,
                screenshot_viewer_json=args.screenshot_viewer_json,
                thumbnail_limit=args.thumbnail_limit,
            )
            payload = dict(bundle.payload)
            attach_ticket = str(args.attach_ticket or "").strip()
            if attach_ticket:
                attachment = common.attach_jira_file_action(
                    attach_ticket,
                    bundle.markdown_path,
                    auto_confirm=bool(args.auto_confirm),
                )
                payload["jira_attachment"] = attachment
                bundle.json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            print(common._console_safe(f"quality-hero-report failed: {exc}"), file=sys.stderr)
            return 1
        output_format = common._resolve_render_format(args, parser, formats=("text", "json", "markdown", "html"))
        if output_format == "json":
            common._emit_json(payload, args)
        elif output_format == "markdown":
            common._emit_text(bundle.markdown_path.read_text(encoding="utf-8"), args)
        elif output_format == "html":
            common._emit_text(bundle.html_path.read_text(encoding="utf-8"), args)
        else:
            lines = [
                f"Quality-Hero report: {payload.get('profile_id', args.profile)}",
                f"Markdown: {bundle.markdown_path}",
                f"HTML: {bundle.html_path}",
                f"JSON: {bundle.json_path}",
            ]
            if payload.get("jira_attachment"):
                attachment = payload["jira_attachment"]
                lines.append(
                    f"Jira attachment: {attachment.get('status', 'unknown')} "
                    f"for {attachment.get('ticket', attach_ticket)}"
                )
            common._emit_text("\n".join(lines), args)
        return 0

    parser.error(f"Unhandled evidence command: {args.command}")
    return 1
