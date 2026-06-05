from __future__ import annotations

import argparse
from importlib import import_module
from pathlib import Path
import sys

common = import_module("sg_preflight.cli")


DEV_COMMANDS = {
    "run",
    "ui",
    "demo-good",
    "demo-broken",
    "probe",
    "materialize",
    "retro-extract",
}


def handle_dev_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.command == "run":
        try:
            packs = common.parse_packs(args.packs)
        except ValueError as exc:
            parser.error(str(exc))
            return 1

        try:
            result = common.execute_bundle_run(
                bundle_dir=Path(args.bundle),
                config_path=Path(args.config),
                packs=packs,
                fail_on=args.fail_on,
                json_out=Path(args.json_out) if args.json_out else None,
                html_out=Path(args.html_out) if args.html_out else None,
                markdown_out=Path(args.md_out) if args.md_out else None,
            )
        except Exception as exc:
            print(common._console_safe(f"run failed: {exc}"), file=sys.stderr)
            return 1
        common._console_report(result.report)
        return result.exit_code

    if args.command == "ui":
        from sg_preflight.ui import run_ui

        return run_ui(host=args.host, port=args.port, reload=args.reload)

    if args.command == "demo-good":
        result = common.execute_bundle_run(
            bundle_dir=common.root / "demo" / "good",
            config_path=common.default_config,
            packs=list(common.VALID_PACKS),
            fail_on=args.fail_on,
            json_out=common.root / "out" / "demo-good.json",
            html_out=common.root / "out" / "demo-good.html",
            markdown_out=common.root / "out" / "demo-good.md",
        )
        common._console_report(result.report)
        return result.exit_code

    if args.command == "demo-broken":
        result = common.execute_bundle_run(
            bundle_dir=common.root / "demo" / "broken",
            config_path=common.default_config,
            packs=list(common.VALID_PACKS),
            fail_on=args.fail_on,
            json_out=common.root / "out" / "demo-broken.json",
            html_out=common.root / "out" / "demo-broken.html",
            markdown_out=common.root / "out" / "demo-broken.md",
        )
        common._console_report(result.report)
        return result.exit_code

    if args.command == "probe":
        search_roots = [Path(raw) for raw in args.search_roots] if args.search_roots else common.default_search_roots()
        report = common.probe_workspace(search_roots)
        if args.json_out:
            common.write_adapter_json(Path(args.json_out), report)
        common._console_probe(report)
        return 0

    if args.command == "materialize":
        try:
            env = common.parse_name_value_pairs(args.env)
            report_context = common.parse_name_value_pairs(args.context)
        except ValueError as exc:
            parser.error(str(exc))
            return 1

        result = common.materialize_bundle(
            output_bundle=Path(args.output_bundle),
            repo_root=Path(args.repo_root) if args.repo_root else None,
            project_root=Path(args.project_root) if args.project_root else None,
            scene_source=Path(args.scene_source) if args.scene_source else None,
            constants_expected_source=(
                Path(args.constants_expected_source) if args.constants_expected_source else None
            ),
            constants_exported_source=(
                Path(args.constants_exported_source) if args.constants_exported_source else None
            ),
            carpaints_source=Path(args.carpaints_source) if args.carpaints_source else None,
            carpaints_helper=Path(args.carpaints_helper) if args.carpaints_helper else None,
            env=env,
            report_context=report_context,
            raco_version=args.raco_version,
            gltf_name=args.gltf_name,
            gltf_previous=Path(args.gltf_previous) if args.gltf_previous else None,
            gltf_current=Path(args.gltf_current) if args.gltf_current else None,
        )
        common._console_materialize(result.output_bundle, result.written_files, result.notes)
        return 0

    if args.command == "retro-extract":
        payload = common.parse_retro_export(
            Path(args.html),
            Path(args.comments_json) if args.comments_json else None,
        )
        if args.json_out:
            common.write_retro_json(payload, Path(args.json_out))
        if args.md_out:
            common.write_retro_markdown(payload, Path(args.md_out))
        print(
            "Retro summary -> "
            f"notes: {payload['summary']['notes']} | "
            f"pain_points: {payload['summary']['pain_points']} | "
            f"actions: {payload['summary']['actions']} | "
            f"comments: {payload['summary']['comments']}"
        )
        return 0

    parser.error(f"Unhandled dev command: {args.command}")
    return 1
