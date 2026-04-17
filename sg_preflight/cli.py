from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sg_preflight.adapters.common import write_json as write_adapter_json
from sg_preflight.adapters.discovery import default_search_roots, probe_workspace
from sg_preflight.adapters.materialize import materialize_bundle
from sg_preflight.profiles import get_run_profile, list_run_profiles
from sg_preflight.qa_actions import execute_operator_action, get_operator_action, list_operator_actions
from sg_preflight.retro import parse_retro_export, write_retro_json, write_retro_markdown
from sg_preflight.services import (
    VALID_PACKS,
    RunRequest,
    execute_bundle_run,
    execute_profile_run,
    parse_name_value_pairs,
    parse_packs,
    sg_checker_catalog,
)


def _console_safe(text: str) -> str:
    encoding = sys.stdout.encoding or "utf-8"
    return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


def _console_report(report: object) -> None:
    summary = report.summary()
    print(_console_safe(f"Bundle: {report.bundle}"))
    print(
        _console_safe(
            f"Summary -> errors: {summary['errors']} | warnings: {summary['warnings']} | "
            f"info: {summary['info']} | total: {summary['total']}"
        )
    )
    print("-" * 80)
    for pack in report.packs:
        print(
            _console_safe(
                f"[{pack.pack}] errors={pack.error_count} warnings={pack.warning_count} "
                f"info={pack.info_count} total={len(pack.findings)}"
            )
        )
        for finding in pack.findings:
            loc = f" @ {finding.location}" if finding.location else ""
            print(
                _console_safe(
                    f"  - {finding.severity.upper():7s} {finding.code}{loc}: {finding.message}"
                )
            )


def _console_probe(report: dict[str, object]) -> None:
    print("Search roots:")
    for root in report.get("search_roots", []):
        print(f"  - {root}")

    candidates = report.get("repo_candidates", [])
    print("-" * 80)
    if not candidates:
        print("No SG-style repo roots were discovered under the provided search roots.")
        return

    for candidate in candidates:
        print(f"Repo candidate: {candidate['path']} (score={candidate['score']})")
        markers = candidate.get("markers", {})
        marker_text = ", ".join(
            key for key, enabled in markers.items() if enabled
        ) or "no markers"
        print(f"  markers: {marker_text}")

        project_roots = candidate.get("project_roots", [])
        if project_roots:
            print("  project roots:")
            for path in project_roots[:6]:
                print(f"    - {path}")

        known_assets = candidate.get("known_assets", {})
        for key, paths in known_assets.items():
            if not paths:
                continue
            print(f"  {key}:")
            for path in paths[:4]:
                print(f"    - {path}")
        print("-" * 80)


def _console_materialize(output: Path, written_files: list[Path], notes: list[str]) -> None:
    print(f"Bundle materialized at: {output.resolve()}")
    print("Written files:")
    for path in written_files:
        print(f"  - {path}")
    if notes:
        print("Notes:")
        for note in notes:
            print(f"  - {note}")


def _console_profiles(as_json: bool) -> None:
    profiles = list_run_profiles()
    if as_json:
        print(json.dumps([profile.to_dict() for profile in profiles], indent=2))
        return

    print("Live run profiles:")
    for profile in profiles:
        print(f"- {profile.profile_id}: {profile.label}")
        print(f"  project_root: {profile.project_root}")
        print(f"  config_path: {profile.config_path}")
        if profile.default_context:
            print(
                "  default_context: "
                + ", ".join(f"{key}={value}" for key, value in profile.default_context.items())
            )


def _console_actions(as_json: bool) -> None:
    actions = list_operator_actions()
    if as_json:
        print(json.dumps([action.to_dict() for action in actions], indent=2))
        return

    print("Operator QA actions:")
    for action in actions:
        state = "ready" if action.ready else "blocked"
        print(f"- {action.action_id}: {action.label} [{state}]")
        print(f"  {action.description}")
        if action.command_preview:
            print(f"  command: {action.command_preview}")
        if action.blocker_message:
            print(f"  blocker: {action.blocker_message}")


def _console_checkers(as_json: bool) -> None:
    checkers = sg_checker_catalog()
    if as_json:
        print(json.dumps(checkers, indent=2))
        return

    print("SG checker coverage:")
    for item in checkers:
        print(f"- {item['label']}: state={item['state']} coverage={item['coverage']}")
        print(f"  {item['summary']}")
        if item.get("operator_surface"):
            print(f"  operator surface: {item['operator_surface']}")
        blockers = item.get("blockers", [])
        if blockers:
            print("  blockers:")
            for blocker in blockers:
                print(f"    - {blocker}")


def _console_run_record(record: object, *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(record.to_dict(), indent=2, ensure_ascii=False))
        return

    print(f"Run ID: {record.run_id}")
    print(f"Profile: {record.profile_id} ({record.profile_label})")
    print(f"Status: {record.status}")
    if record.summary:
        summary = record.summary
        print(
            "Summary -> "
            f"errors: {summary['errors']} | warnings: {summary['warnings']} | "
            f"info: {summary['info']} | total: {summary['total']}"
        )
    if record.exit_code is not None:
        print(f"Exit code: {record.exit_code}")
    print(f"Output root: {record.paths['output_root']}")
    print(f"Bundle: {record.paths['bundle']}")
    print(f"JSON report: {record.paths['json_report']}")
    print(f"HTML report: {record.paths['html_report']}")
    print(f"Markdown report: {record.paths['markdown_report']}")
    if record.notes:
        print("Notes:")
        for note in record.notes:
            print(f"  - {note}")


def _console_action_record(record: object, *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(record.to_dict(), indent=2, ensure_ascii=False))
        return

    print(f"Action run ID: {record.run_id}")
    print(f"Action: {record.action_id} ({record.label})")
    print(f"Status: {record.status}")
    if record.profile_id:
        print(f"Profile: {record.profile_id}")
    if record.blocker_message:
        print(f"Blocker: {record.blocker_message}")
    if record.error_message:
        print(f"Error: {record.error_message}")
    print(f"Output root: {record.paths['output_root']}")
    print(f"Log: {record.paths['log']}")
    print(f"Summary JSON: {record.paths['summary_json']}")
    print(f"Summary Markdown: {record.paths['summary_md']}")
    if record.summary:
        for line in record.summary.get("lines", []):
            print(f"  - {line}")
    if record.artifacts:
        print("Artifacts:")
        for artifact in record.artifacts:
            print(f"  - {artifact.get('label', 'artifact')}: {artifact.get('path', '')}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sg-preflight")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run one or more validation packs against a bundle")
    run.add_argument("--bundle", required=True, help="Path to a validation bundle directory")
    run.add_argument("--config", required=True, help="Path to JSON config file")
    run.add_argument(
        "--packs",
        default="all",
        help="Comma-separated packs or 'all' (anchors,constants,carpaints,project_sanity)",
    )
    run.add_argument("--json-out", help="Write JSON report here")
    run.add_argument("--html-out", help="Write HTML report here")
    run.add_argument("--md-out", help="Write markdown QA handoff report here")
    run.add_argument(
        "--fail-on",
        default="error",
        choices=["error", "warning", "never"],
        help="Exit non-zero if findings reach this severity threshold",
    )

    profile_list = sub.add_parser("list-profiles", help="List canonical live run profiles")
    profile_list.add_argument("--json", action="store_true", help="Print profile registry as JSON")

    action_list = sub.add_parser("list-actions", help="List one-click SG QA actions")
    action_list.add_argument("--json", action="store_true", help="Print action registry as JSON")

    checker_list = sub.add_parser("list-checkers", help="List SG checker coverage and readiness")
    checker_list.add_argument("--json", action="store_true", help="Print checker coverage as JSON")

    run_profile = sub.add_parser("run-profile", help="Materialize and validate a canonical live profile")
    run_profile.add_argument("profile_id", help="Canonical profile id such as G70, G65, or G45")
    run_profile.add_argument(
        "--packs",
        default="all",
        help="Comma-separated packs or 'all' (anchors,constants,carpaints,project_sanity)",
    )
    run_profile.add_argument(
        "--fail-on",
        default="error",
        choices=["error", "warning", "never"],
        help="Exit non-zero if findings reach this severity threshold",
    )
    run_profile.add_argument("--output-root", help="Directory to write bundle, reports, and run.json")
    run_profile.add_argument(
        "--context",
        action="append",
        default=[],
        help="Override workflow/report context NAME=VALUE (repeatable)",
    )
    run_profile.add_argument("--json", action="store_true", help="Print run record as JSON")

    run_action = sub.add_parser("run-action", help="Execute one-click SG QA action")
    run_action.add_argument("action_id", help="Operator action id such as daily_live_matrix or repo_checker_idcevo")
    run_action.add_argument("--json", action="store_true", help="Print action record as JSON")

    ui = sub.add_parser("ui", help="Start the local operator UI")
    ui.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    ui.add_argument("--port", type=int, default=8765, help="Bind port (default: 8765)")
    ui.add_argument("--reload", action="store_true", help="Reload automatically when local UI files change")

    desktop = sub.add_parser(
        "desktop",
        help="Start the experimental desktop operator shell",
        description="Start the experimental desktop operator shell",
    )
    desktop.add_argument("--profile", help="Optional initial profile id to focus when the shell opens")

    demo_good = sub.add_parser("demo-good", help="Run the good demo bundle")
    demo_good.add_argument("--fail-on", default="error", choices=["error", "warning", "never"])

    demo_broken = sub.add_parser("demo-broken", help="Run the broken demo bundle")
    demo_broken.add_argument("--fail-on", default="error", choices=["error", "warning", "never"])

    probe = sub.add_parser("probe", help="Discover SG-style repo roots and likely input assets")
    probe.add_argument(
        "--search-root",
        action="append",
        dest="search_roots",
        help="Root directory to search (repeatable). Defaults to common repo locations.",
    )
    probe.add_argument("--json-out", help="Write discovery report JSON here")

    materialize = sub.add_parser(
        "materialize",
        help="Create a normalized validation bundle from SG-shaped inputs",
    )
    materialize.add_argument("--output-bundle", required=True, help="Bundle directory to write")
    materialize.add_argument("--repo-root", help="Seriengrafik repo root or trunk path")
    materialize.add_argument("--project-root", help="Specific car project root to scan")
    materialize.add_argument("--scene-source", help="Scene hierarchy dump or containing directory")
    materialize.add_argument(
        "--constants-expected-source",
        help="Expected constants JSON or containing directory",
    )
    materialize.add_argument(
        "--constants-exported-source",
        help="Exported constants JSON or containing directory",
    )
    materialize.add_argument("--carpaints-source", help="Carpaints JSON or containing directory")
    materialize.add_argument(
        "--carpaints-helper",
        help="Optional helper script such as read_json_carpaints.py",
    )
    materialize.add_argument("--raco-version", help="Override detected RaCo version")
    materialize.add_argument(
        "--env",
        action="append",
        default=[],
        help="Inject NAME=VALUE into the generated project manifest (repeatable)",
    )
    materialize.add_argument(
        "--context",
        action="append",
        default=[],
        help="Inject workflow/report context NAME=VALUE into the generated project manifest (repeatable)",
    )
    materialize.add_argument("--gltf-name", help="Label for optional glTF snapshot comparison")
    materialize.add_argument("--gltf-previous", help="Previous glTF object snapshot JSON")
    materialize.add_argument("--gltf-current", help="Current glTF object snapshot JSON")

    retro = sub.add_parser(
        "retro-extract",
        help="Parse a Whiteboard retro export into structured SG-preflight pain/action output",
    )
    retro.add_argument("--html", required=True, help="Path to exported Whiteboard HTML")
    retro.add_argument("--comments-json", help="Optional path to exported comments JSON")
    retro.add_argument("--json-out", help="Write structured retro JSON here")
    retro.add_argument("--md-out", help="Write structured retro markdown here")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    default_config = root / "config" / "sg_rules.json"

    if args.command == "run":
        try:
            packs = parse_packs(args.packs)
        except ValueError as exc:
            parser.error(str(exc))
            return 1

        result = execute_bundle_run(
            bundle_dir=Path(args.bundle),
            config_path=Path(args.config),
            packs=packs,
            fail_on=args.fail_on,
            json_out=Path(args.json_out) if args.json_out else None,
            html_out=Path(args.html_out) if args.html_out else None,
            markdown_out=Path(args.md_out) if args.md_out else None,
        )
        _console_report(result.report)
        return result.exit_code

    if args.command == "list-profiles":
        _console_profiles(args.json)
        return 0

    if args.command == "list-actions":
        _console_actions(args.json)
        return 0

    if args.command == "list-checkers":
        _console_checkers(args.json)
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

    if args.command == "run-action":
        try:
            action = get_operator_action(args.action_id)
        except KeyError as exc:
            parser.error(str(exc))
            return 1

        try:
            record = execute_operator_action(action)
        except Exception as exc:
            print(_console_safe(f"run-action failed: {exc}"), file=sys.stderr)
            return 1
        _console_action_record(record, as_json=args.json)
        return 0 if record.status in {"completed", "blocked"} else 1

    if args.command == "ui":
        from sg_preflight.ui import run_ui

        return run_ui(host=args.host, port=args.port, reload=args.reload)

    if args.command == "desktop":
        try:
            from sg_preflight.desktop.app import run_desktop_app
            return run_desktop_app(initial_profile_id=args.profile or "")
        except RuntimeError as exc:
            print(_console_safe(str(exc)), file=sys.stderr)
            return 1

    if args.command == "demo-good":
        result = execute_bundle_run(
            bundle_dir=root / "demo" / "good",
            config_path=default_config,
            packs=list(VALID_PACKS),
            fail_on=args.fail_on,
            json_out=root / "out" / "demo-good.json",
            html_out=root / "out" / "demo-good.html",
            markdown_out=root / "out" / "demo-good.md",
        )
        _console_report(result.report)
        return result.exit_code

    if args.command == "demo-broken":
        result = execute_bundle_run(
            bundle_dir=root / "demo" / "broken",
            config_path=default_config,
            packs=list(VALID_PACKS),
            fail_on=args.fail_on,
            json_out=root / "out" / "demo-broken.json",
            html_out=root / "out" / "demo-broken.html",
            markdown_out=root / "out" / "demo-broken.md",
        )
        _console_report(result.report)
        return result.exit_code

    if args.command == "probe":
        search_roots = [Path(raw) for raw in args.search_roots] if args.search_roots else default_search_roots()
        report = probe_workspace(search_roots)
        if args.json_out:
            write_adapter_json(Path(args.json_out), report)
        _console_probe(report)
        return 0

    if args.command == "materialize":
        try:
            env = parse_name_value_pairs(args.env)
            report_context = parse_name_value_pairs(args.context)
        except ValueError as exc:
            parser.error(str(exc))
            return 1

        result = materialize_bundle(
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
        _console_materialize(result.output_bundle, result.written_files, result.notes)
        return 0

    if args.command == "retro-extract":
        payload = parse_retro_export(
            Path(args.html),
            Path(args.comments_json) if args.comments_json else None,
        )
        if args.json_out:
            write_retro_json(payload, Path(args.json_out))
        if args.md_out:
            write_retro_markdown(payload, Path(args.md_out))
        print(
            "Retro summary -> "
            f"notes: {payload['summary']['notes']} | "
            f"pain_points: {payload['summary']['pain_points']} | "
            f"actions: {payload['summary']['actions']} | "
            f"comments: {payload['summary']['comments']}"
        )
        return 0

    parser.error(f"Unhandled command: {args.command}")
    return 1
