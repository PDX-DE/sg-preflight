from __future__ import annotations

import argparse
from importlib import import_module
import json
import sys
from pathlib import Path

common = import_module("sg_preflight.cli")


def _console_delivery_readiness(payload: dict[str, object]) -> None:
    counts = payload.get("counts", {})
    if not isinstance(counts, dict):
        counts = {}
    print("Delivery Readiness")
    print(f"Source: {payload.get('repo_root', '')}")
    print(f"State: {payload.get('source_state', '')}")
    print(
        "Summary -> "
        f"total: {counts.get('total', 0)} | "
        f"delivered: {counts.get('delivered', 0)} | "
        f"not delivered yet: {counts.get('not_delivered_yet', 0)} | "
        f"unknown: {counts.get('unknown', 0)}"
    )
    print(str(payload.get("manual_approval_banner", "")))
    catalog = payload.get("catalog")
    if isinstance(catalog, dict):
        print(
            "Catalog -> "
            f"state: {catalog.get('catalog_state', '')} | "
            f"targets: {catalog.get('catalog_target_count', 0)} | "
            f"mapped: {catalog.get('catalog_targets_mapped_count', 0)} | "
            f"missing dirs: {catalog.get('catalog_targets_missing_dir_count', 0)} | "
            f"dirs without catalog: {catalog.get('dirs_without_catalog_count', 0)}"
        )
    artifacts = payload.get("artifacts")
    if isinstance(artifacts, dict):
        if artifacts.get("json_path"):
            print(f"JSON: {artifacts['json_path']}")
        if artifacts.get("markdown_path"):
            print(f"Markdown: {artifacts['markdown_path']}")
    print("-" * 80)
    entries = payload.get("entries", [])
    if not isinstance(entries, list) or not entries:
        print("No car delivery rows found.")
        return
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        version = entry.get("version") or "no version"
        date = f" / {entry['delivered_date']}" if entry.get("delivered_date") else ""
        print(
            common._console_safe(
                f"- {entry.get('source_root')}/{entry.get('brand')}/{entry.get('model_id')}: "
                f"{entry.get('status_label')} ({version}{date})"
            )
        )


def handle_delivery_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.command == "delivery-documentation":
        checklist_root = common._resolve_workspace(args)
        try:
            if args.delivery_checklist_command == "read":
                payload = common.read_delivery_checklist(
                    profile_id=args.profile,
                    workspace=checklist_root,
                    workbook_path=Path(args.workbook).resolve() if args.workbook else None,
                    brand=args.brand,
                    bmw_root=Path(args.bmw_root).resolve() if getattr(args, "bmw_root", None) else None,
                    enable_auto_generate=bool(getattr(args, "enable_auto_generate", True)),
                )
            else:
                parser.error(f"Unhandled delivery-documentation command: {args.delivery_checklist_command}")
                return 1
        except Exception as exc:
            print(common._console_safe(f"delivery-documentation failed: {exc}"), file=sys.stderr)
            return 1
        output_format = common._resolve_render_format(args, parser)
        if output_format == "json":
            common._emit_json(payload, args)
        elif output_format == "markdown":
            common._emit_text(common.render_delivery_checklist_markdown(payload), args)
        else:
            common._emit_text(common.render_delivery_checklist_text(payload), args)
        return 0

    if args.command == "delivery-workbook":
        workbook_root = common._resolve_workspace(args)
        try:
            if args.delivery_workbook_command == "trigger":
                payload = common.build_delivery_workbook_trigger(
                    profile_id=args.profile,
                    workspace=workbook_root,
                    bmw_root=Path(args.bmw_root).resolve() if getattr(args, "bmw_root", None) else None,
                    trusted_tool_mode=bool(getattr(args, "trusted_tool_mode", False)),
                )
            elif args.delivery_workbook_command == "find":
                from sg_preflight.workbook_finder import resolve_workbook, render_resolution_text

                bmw_root_value = Path(args.bmw_root).resolve() if getattr(args, "bmw_root", None) else None
                resolution = resolve_workbook(
                    args.profile,
                    workspace=workbook_root,
                    bmw_root=bmw_root_value,
                )
                payload = resolution.to_payload()
                if resolution.selected is None and getattr(args, "auto_generate", False):
                    try:
                        from sg_preflight.workbook_generator import auto_generate_if_raw_available

                        candidate = auto_generate_if_raw_available(
                            args.profile,
                            workspace=workbook_root,
                            bmw_root=bmw_root_value,
                        )
                        if candidate is not None:
                            resolution = resolve_workbook(
                                args.profile,
                                workspace=workbook_root,
                                bmw_root=bmw_root_value,
                            )
                            payload = resolution.to_payload()
                            payload["auto_generated"] = {
                                "path": str(candidate.path),
                                "source_classification": candidate.source_classification,
                            }
                        else:
                            payload["auto_generated"] = {
                                "status": "skipped",
                                "note": "No raw export-size data available in the documented locations.",
                            }
                    except ImportError as exc:
                        payload["auto_generated"] = {
                            "status": "unavailable",
                            "note": f"openpyxl is required for auto-generation: {exc}",
                        }
                output_format = common._resolve_render_format(args, parser, formats=("text", "json"))
                if output_format == "json":
                    common._emit_json(payload, args)
                else:
                    common._emit_text(render_resolution_text(resolution), args)
                return 0
            else:
                parser.error(f"Unhandled delivery-workbook command: {args.delivery_workbook_command}")
                return 1
        except Exception as exc:
            print(common._console_safe(f"delivery-workbook failed: {exc}"), file=sys.stderr)
            return 1
        output_format = common._resolve_render_format(args, parser)
        if output_format == "json":
            common._emit_json(payload, args)
        elif output_format == "markdown":
            common._emit_text(common.render_delivery_workbook_trigger_markdown(payload), args)
        else:
            common._emit_text(common.render_delivery_workbook_trigger_text(payload), args)
        return 0

    if args.command == "export-size-analysis":
        analysis_root = common._resolve_workspace(args)
        try:
            if args.export_size_analysis_command == "read":
                payload = common.read_export_size_analysis(
                    profile_id=args.profile,
                    workspace=analysis_root,
                    workbook_path=Path(args.workbook).resolve() if args.workbook else None,
                    date=args.date,
                    latest=args.latest or not args.date,
                )
            else:
                parser.error(f"Unhandled export-size-analysis command: {args.export_size_analysis_command}")
                return 1
        except Exception as exc:
            print(common._console_safe(f"export-size-analysis failed: {exc}"), file=sys.stderr)
            return 1
        output_format = common._resolve_render_format(args, parser)
        if output_format == "json":
            common._emit_json(payload, args)
        elif output_format == "markdown":
            common._emit_text(common.render_export_size_analysis_markdown(payload), args)
        else:
            common._emit_text(common.render_export_size_analysis_text(payload), args)
        return 0

    if args.command == "delivery-readiness":
        readiness_root = common._resolve_workspace(args)
        repo_root = Path(args.repo_root).resolve() if args.repo_root else None
        bmw_repo_root = Path(args.bmw_repo_root).resolve() if args.bmw_repo_root else None
        board = common.build_delivery_readiness_board(
            repo_root,
            workspace_root=readiness_root,
            bmw_repo_root=bmw_repo_root,
        )
        payload = board.to_dict()
        if args.output_root:
            payload["artifacts"] = common.write_delivery_readiness_board(board, Path(args.output_root).resolve())
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            common._console_delivery_readiness(payload)
        return 0

    parser.error(f"Unhandled delivery command: {args.command}")
    return 1
