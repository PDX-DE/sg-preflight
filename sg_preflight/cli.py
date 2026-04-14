from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from sg_preflight.adapters.common import write_json as write_adapter_json
from sg_preflight.adapters.discovery import default_search_roots, probe_workspace
from sg_preflight.adapters.materialize import materialize_bundle
from sg_preflight.bundle import load_bundle
from sg_preflight.config_loader import load_config
from sg_preflight.models import Report
from sg_preflight.reporting import write_html_report, write_json_report, write_markdown_report
from sg_preflight.retro import parse_retro_export, write_retro_json, write_retro_markdown
from sg_preflight.validators.anchors import validate_anchors
from sg_preflight.validators.carpaints import validate_carpaints
from sg_preflight.validators.constants import validate_constants
from sg_preflight.validators.project_sanity import validate_project_sanity


VALID_PACKS = ("anchors", "constants", "carpaints", "project_sanity")


def _parse_packs(raw: str) -> list[str]:
    raw = raw.strip().lower()
    if raw == "all":
        return list(VALID_PACKS)
    items = [part.strip() for part in raw.split(",") if part.strip()]
    invalid = [pack for pack in items if pack not in VALID_PACKS]
    if invalid:
        raise ValueError(f"Unsupported packs: {', '.join(invalid)}")
    return items


def _console_report(report: Report) -> None:
    summary = report.summary()
    print(f"Bundle: {report.bundle}")
    print(
        f"Summary -> errors: {summary['errors']} | warnings: {summary['warnings']} | "
        f"info: {summary['info']} | total: {summary['total']}"
    )
    print("-" * 80)
    for pack in report.packs:
        print(
            f"[{pack.pack}] errors={pack.error_count} warnings={pack.warning_count} "
            f"info={pack.info_count} total={len(pack.findings)}"
        )
        for finding in pack.findings:
            loc = f" @ {finding.location}" if finding.location else ""
            print(
                f"  - {finding.severity.upper():7s} {finding.code}{loc}: {finding.message}"
            )


def _parse_env_overrides(values: list[str]) -> dict[str, str]:
    env: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise ValueError(f"Invalid --env value {item!r}; expected NAME=VALUE")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"Invalid --env value {item!r}; key cannot be empty")
        env[key] = value
    return env


def _build_report_context(bundle: Any) -> dict[str, Any]:
    manifest = getattr(bundle, "project_manifest", None)
    context: dict[str, Any] = {}
    if isinstance(manifest, dict):
        raw_context = manifest.get("report_context", {})
        if isinstance(raw_context, dict):
            context.update(raw_context)
        project_root = manifest.get("project_root")
        if project_root:
            context.setdefault("project_root", str(project_root))
        repo_root = manifest.get("repo_root")
        if repo_root:
            context.setdefault("repo_root", str(repo_root))
    return context


def _console_probe(report: dict[str, Any]) -> None:
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sg-preflight")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run one or more validation packs")
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


def _run(bundle_dir: Path, config_path: Path, packs: list[str], fail_on: str,
         json_out: Path | None = None, html_out: Path | None = None,
         md_out: Path | None = None) -> int:
    config = load_config(config_path)
    bundle = load_bundle(bundle_dir)

    report = Report(bundle=str(bundle_dir.resolve()), context=_build_report_context(bundle))
    pack_map = {
        "anchors": validate_anchors,
        "constants": validate_constants,
        "carpaints": validate_carpaints,
        "project_sanity": validate_project_sanity,
    }

    for pack in packs:
        report.packs.append(pack_map[pack](bundle, config))

    if json_out:
        write_json_report(report, json_out)
    if html_out:
        write_html_report(report, html_out, config)
    if md_out:
        write_markdown_report(report, md_out, config)

    _console_report(report)
    return 2 if report.has_threshold_or_worse(fail_on) else 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    default_config = root / "config" / "sg_rules.json"

    if args.command == "run":
        try:
            packs = _parse_packs(args.packs)
        except ValueError as exc:
            parser.error(str(exc))
            return 1
        return _run(
            bundle_dir=Path(args.bundle),
            config_path=Path(args.config),
            packs=packs,
            fail_on=args.fail_on,
            json_out=Path(args.json_out) if args.json_out else None,
            html_out=Path(args.html_out) if args.html_out else None,
            md_out=Path(args.md_out) if args.md_out else None,
        )

    if args.command == "demo-good":
        return _run(
            bundle_dir=root / "demo" / "good",
            config_path=default_config,
            packs=list(VALID_PACKS),
            fail_on=args.fail_on,
            json_out=root / "out" / "demo-good.json",
            html_out=root / "out" / "demo-good.html",
            md_out=root / "out" / "demo-good.md",
        )

    if args.command == "demo-broken":
        return _run(
            bundle_dir=root / "demo" / "broken",
            config_path=default_config,
            packs=list(VALID_PACKS),
            fail_on=args.fail_on,
            json_out=root / "out" / "demo-broken.json",
            html_out=root / "out" / "demo-broken.html",
            md_out=root / "out" / "demo-broken.md",
        )

    if args.command == "probe":
        search_roots = [Path(raw) for raw in args.search_roots] if args.search_roots else default_search_roots()
        report = probe_workspace(search_roots)
        if args.json_out:
            write_adapter_json(Path(args.json_out), report)
        _console_probe(report)
        return 0

    if args.command == "materialize":
        try:
            env = _parse_env_overrides(args.env)
            report_context = _parse_env_overrides(args.context)
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
