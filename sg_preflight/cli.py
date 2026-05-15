from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
import json
import subprocess
import sys
from pathlib import Path

from sg_preflight.adapters.common import write_json as write_adapter_json
from sg_preflight.adapters.discovery import default_search_roots, probe_workspace
from sg_preflight.adapters.materialize import materialize_bundle
from sg_preflight.bmw_delivery import (
    read_bmw_screenshot_state,
    render_bmw_screenshot_state_markdown,
    render_bmw_screenshot_state_text,
)
from sg_preflight.bmw_git_readiness import (
    read_bmw_git_readiness,
    render_bmw_git_readiness_markdown,
    render_bmw_git_readiness_text,
)
from sg_preflight.desktop.evidence_model import (
    desktop_action_snapshot,
    desktop_actions_for_profile,
    desktop_blocker_items,
    desktop_environment_doctor,
    desktop_manual_cards,
    desktop_operator_overview,
    desktop_profiles,
    desktop_recent_actions,
    desktop_recent_runs,
    desktop_run_snapshot,
)
from sg_preflight.daily_digest import (
    build_latest_daily_digest,
    render_daily_digest_markdown,
    render_daily_digest_text,
)
from sg_preflight.delivery_checklist import (
    read_delivery_checklist,
    render_delivery_checklist_markdown,
    render_delivery_checklist_text,
)
from sg_preflight.export_size_analysis import (
    read_export_size_analysis,
    render_export_size_analysis_markdown,
    render_export_size_analysis_text,
)
from sg_preflight.manual_review import (
    VALID_VERDICTS,
    create_manual_review_session,
    load_manual_review_session,
    open_manual_review_tool,
    record_manual_review_step,
    render_manual_review_markdown,
)
from sg_preflight.profiles import get_run_profile, list_run_profiles
from sg_preflight.qa_actions import (
    attach_manual_evidence,
    build_action_record,
    execute_operator_action,
    get_operator_action,
    list_operator_actions,
    load_action_record,
    save_action_record,
)
from sg_preflight.review_messages import build_review_owner_update
from sg_preflight.review_tracking import (
    add_external_finding,
    load_external_findings,
    load_review_decisions,
    set_review_decision,
)
from sg_preflight.retro import parse_retro_export, write_retro_json, write_retro_markdown
from sg_preflight.services import (
    VALID_PACKS,
    RunRequest,
    execute_bundle_run,
    execute_profile_run,
    parse_name_value_pairs,
    parse_packs,
    qa_workflow_status,
    sg_checker_catalog,
)
from sg_preflight.daily_snapshot import materialize_daily_qa_snapshot
from sg_preflight.review_state import (
    build_review_board_state,
    list_review_packages,
    load_daily_delta,
    load_latest_review_package,
    load_review_priority,
    verify_sendable_package,
)
from sg_preflight.screenshot_triage import materialize_screenshot_triage
from sg_preflight.ticket_review import (
    default_ticket_review_output_root,
    materialize_ticket_review_bundle,
)
from sg_preflight.visual_review import build_visual_review_prep


def _console_safe(text: str) -> str:
    encoding = sys.stdout.encoding or "utf-8"
    return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


def _json_ready(payload: object) -> object:
    if is_dataclass(payload):
        return asdict(payload)
    if isinstance(payload, list):
        return [_json_ready(item) for item in payload]
    if isinstance(payload, tuple):
        return [_json_ready(item) for item in payload]
    if isinstance(payload, dict):
        return {str(key): _json_ready(value) for key, value in payload.items()}
    return payload


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


def _console_workflow_status(items: list[dict[str, object]], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(items, indent=2, ensure_ascii=False))
        return

    print("Workflow status:")
    for item in items:
        print(f"- {item['label']}: state={item['state']}")
        print(f"  {item['summary']}")
        blockers = item.get("blockers", [])
        if blockers:
            print("  blockers:")
            for blocker in blockers:
                print(f"    - {blocker}")


def _console_desktop_payload(payload: object) -> None:
    print(json.dumps(_json_ready(payload), indent=2, ensure_ascii=False))


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


def _console_screenshot_triage(bundle: object, *, as_json: bool = False) -> None:
    report = bundle.report
    if as_json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        return

    print(f"Screenshot triage: {report.profile_id}")
    print(f"Project root: {report.project_root}")
    print(f"Expected root: {report.expected_root or 'not found'}")
    print(
        "Summary -> "
        f"pairs: {report.pair_count} | "
        f"unchanged: {report.unchanged_count} | "
        f"near-identical: {report.near_identical_count} | "
        f"needs review: {report.needs_review_count} | "
        f"missing candidate: {report.missing_candidate_count} | "
        f"missing baseline: {report.missing_baseline_count} | "
        f"dimension mismatch: {report.dimension_mismatch_count}"
    )
    print(f"Markdown: {bundle.markdown_path}")
    print(f"HTML: {bundle.html_path}")
    print(f"JSON: {bundle.json_path}")


def _console_daily_snapshot(result: object, *, as_json: bool = False) -> None:
    snapshot = result.snapshot
    if as_json:
        print(json.dumps(snapshot.to_dict(), indent=2, ensure_ascii=False))
        return

    print("Daily 3D Car QA Summary")
    print(f"Generated: {snapshot.created_at}")
    print(f"Scope: {', '.join(snapshot.scope_profiles)}")
    print(f"BMW repo root: {snapshot.bmw_repo_root}")
    print(f"Config check: {snapshot.config_check.status}")
    print(f"Markdown: {result.markdown_path}")
    print(f"JSON: {result.json_path}")
    if getattr(result, "review_priority_markdown_path", None):
        print(f"Review priority ranking: {result.review_priority_markdown_path}")
    if getattr(result, "delta_summary_markdown_path", None):
        print(f"Daily delta summary: {result.delta_summary_markdown_path}")
    if snapshot.smoke_results:
        print("Smoke results:")
        for item in snapshot.smoke_results:
            print(
                _console_safe(
                    f"  - {item.profile_id}: status={item.status} smoke={item.smoke_test} "
                    f"ramses={item.exported_ramses_size}b expected={item.expected_count} "
                    f"actual={item.actual_count} diff={item.diff_count} "
                    f"compare={'passed' if item.compare_ok else 'not-passed'}"
                )
            )
    if getattr(snapshot, "battery_results", ()):
        print("Battery results:")
        for item in snapshot.battery_results:
            print(
                _console_safe(
                    f"  - {item.profile_id}: filter={item.filter_name} verdict={item.verdict} "
                    f"expected={item.expected_count} actual={item.actual_count} diff={item.diff_count}"
                )
            )
    if snapshot.top_review_items:
        print("Top review items:")
        for item in snapshot.top_review_items:
            print(f"  - {item}")
    if snapshot.blocked_steps:
        print("Blocked steps:")
        for item in snapshot.blocked_steps:
            print(f"  - {item}")


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

    delivery_checklist = sub.add_parser(
        "delivery-checklist",
        help="Read the operator-local delivery checklist workbook without writing to it",
    )
    delivery_checklist_sub = delivery_checklist.add_subparsers(dest="delivery_checklist_command", required=True)
    delivery_checklist_read = delivery_checklist_sub.add_parser("read", help="Read delivery checklist evidence for one profile")
    delivery_checklist_read.add_argument("--workspace", help="Workspace root override")
    delivery_checklist_read.add_argument("--profile", required=True, help="Profile id such as G65")
    delivery_checklist_read.add_argument("--brand", default="BMW", help="Workbook brand label such as BMW or Mini")
    delivery_checklist_read.add_argument("--workbook", help="Explicit delivery checklist workbook path")
    delivery_checklist_read.add_argument("--json", action="store_true", help="Print delivery checklist payload as JSON")
    delivery_checklist_read.add_argument("--markdown", action="store_true", help="Print delivery checklist payload as Markdown")

    export_size = sub.add_parser(
        "export-size-analysis",
        help="Read the operator-local export-size analysis workbook without writing to it",
    )
    export_size_sub = export_size.add_subparsers(dest="export_size_analysis_command", required=True)
    export_size_read = export_size_sub.add_parser("read", help="Read export-size analysis evidence for one profile")
    export_size_read.add_argument("--workspace", help="Workspace root override")
    export_size_read.add_argument("--profile", required=True, help="Profile id such as G65")
    export_size_read.add_argument("--workbook", help="Explicit export-size analysis workbook path")
    export_size_date = export_size_read.add_mutually_exclusive_group()
    export_size_date.add_argument("--date", help="Workbook date as YYYYMMDD (for example: 20251002)")
    export_size_date.add_argument("--latest", action="store_true", help="Pick the newest matching workbook by date")
    export_size_read.add_argument("--json", action="store_true", help="Print export-size analysis payload as JSON")
    export_size_read.add_argument("--markdown", action="store_true", help="Print export-size analysis payload as Markdown")

    screenshot_state = sub.add_parser(
        "screenshot-test-state",
        help="Read local BMW/MINI screenshot expected/actual/diff state without running screenshot tests",
    )
    screenshot_state_sub = screenshot_state.add_subparsers(dest="screenshot_test_state_command", required=True)
    screenshot_state_read = screenshot_state_sub.add_parser(
        "read",
        help="Read screenshot test state for one profile",
    )
    screenshot_state_read.add_argument("--workspace", help="Workspace root override")
    screenshot_state_read.add_argument("--profile", required=True, help="Profile id such as G65")
    screenshot_state_read.add_argument("--json", action="store_true", help="Print screenshot test state as JSON")
    screenshot_state_read.add_argument("--markdown", action="store_true", help="Print screenshot test state as Markdown")

    bmw_git_readiness = sub.add_parser(
        "bmw-git-readiness",
        help="Read local BMW/MINI Git per-profile readiness without writing to BMW Git",
    )
    bmw_git_readiness_sub = bmw_git_readiness.add_subparsers(dest="bmw_git_readiness_command", required=True)
    bmw_git_readiness_read = bmw_git_readiness_sub.add_parser(
        "read",
        help="Read BMW/MINI Git readiness for one profile",
    )
    bmw_git_readiness_read.add_argument("--workspace", help="Workspace root override")
    bmw_git_readiness_read.add_argument("--bmw-root", help="Explicit digital-3d-car-models checkout path")
    bmw_git_readiness_read.add_argument("--profile", required=True, help="Profile id such as G65")
    bmw_git_readiness_read.add_argument("--json", action="store_true", help="Print BMW Git readiness as JSON")
    bmw_git_readiness_read.add_argument("--markdown", action="store_true", help="Print BMW Git readiness as Markdown")

    workflow_list = sub.add_parser("workflow-status", help="List workflow coverage, partial areas, and blockers")
    workflow_list.add_argument("--json", action="store_true", help="Print workflow status as JSON")

    ticket_review = sub.add_parser(
        "ticket-review",
        help="Generate a ticket-centered QA support package from live action records and SVN-backed review prep",
    )
    ticket_review.add_argument("ticket_id", help="Ticket id such as IDCEVODEV-960073")
    ticket_review.add_argument("--title", default="", help="Ticket title override")
    ticket_review.add_argument(
        "--profile",
        action="append",
        default=[],
        help="Profile id to ground locally, repeatable (for example: --profile G70)",
    )
    ticket_review.add_argument("--workspace", help="Workspace root override")
    ticket_review.add_argument("--output-root", help="Output directory for the generated package")
    ticket_review.add_argument("--scope-note", default="", help="Explicit scope caveat or note to include")
    ticket_review.add_argument(
        "--candidate-root",
        action="append",
        default=[],
        help="Explicit candidate screenshot root (repeatable)",
    )
    ticket_review.add_argument(
        "--sendable",
        action="store_true",
        help="Generate the clean sendable package variant (no internal action bundles).",
    )
    ticket_review.add_argument("--json", action="store_true", help="Print bundle payload as JSON")

    screenshot_triage = sub.add_parser(
        "screenshot-triage",
        help="Run deterministic screenshot triage over expected baselines and any detected candidate roots",
    )
    screenshot_triage.add_argument("--profile", help="Canonical profile id such as G70")
    screenshot_triage.add_argument("--project-root", help="Explicit project root override")
    screenshot_triage.add_argument(
        "--candidate-root",
        action="append",
        default=[],
        help="Explicit candidate screenshot root (repeatable)",
    )
    screenshot_triage.add_argument("--workspace", help="Workspace root override")
    screenshot_triage.add_argument("--output-root", help="Directory to write triage artifacts")
    screenshot_triage.add_argument("--json", action="store_true", help="Print triage payload as JSON")

    daily_snapshot = sub.add_parser(
        "daily-qa-snapshot",
        help="Run the local BMW+SG daily QA snapshot for confirmed delivery cars",
    )
    daily_snapshot.add_argument(
        "--profile",
        action="append",
        default=[],
        help="Profile id to include in the snapshot, repeatable (defaults to NA8,G78,G50)",
    )
    daily_snapshot.add_argument("--workspace", help="Workspace root override")
    daily_snapshot.add_argument("--output-root", help="Directory to write snapshot artifacts")
    daily_snapshot.add_argument(
        "--smoke-test",
        default="openAllDoors_rightView",
        help="Smoke test filter to run through the BMW screenshot flow",
    )
    daily_snapshot.add_argument(
        "--no-smoke",
        action="store_true",
        help="Skip per-profile smoke runs and only materialize environment/config status",
    )
    daily_snapshot.add_argument(
        "--battery-defaults",
        action="store_true",
        help="Run the curated broader screenshot battery in addition to the representative smoke test",
    )
    daily_snapshot.add_argument(
        "--battery-filter",
        action="append",
        default=[],
        help="Additional broader screenshot battery filter to run (repeatable)",
    )
    daily_snapshot.add_argument("--json", action="store_true", help="Print snapshot payload as JSON")

    review_board = sub.add_parser(
        "review-board",
        help="Inspect the latest ticket review package/operator state as structured JSON",
    )
    review_board_sub = review_board.add_subparsers(dest="review_board_command", required=True)

    review_board_list = review_board_sub.add_parser("list", help="List discovered review packages")
    review_board_list.add_argument("--workspace", help="Workspace root override")
    review_board_list.add_argument("--json", action="store_true", help="Print package list as JSON")

    review_board_latest = review_board_sub.add_parser("latest", help="Load the latest review-board state")
    review_board_latest.add_argument("--workspace", help="Workspace root override")
    review_board_latest.add_argument("--ticket-id", help="Optional ticket id filter")
    review_board_latest.add_argument("--json", action="store_true", help="Print review-board state as JSON")

    review_board_copy = review_board_sub.add_parser(
        "copy-update",
        help="Build the copy-ready review-owner update from the latest review-board state",
    )
    review_board_copy.add_argument("--workspace", help="Workspace root override")
    review_board_copy.add_argument("--ticket-id", help="Optional ticket id filter")
    review_board_copy.add_argument("--json", action="store_true", help="Print review-owner update payload as JSON")

    review_board_verify = review_board_sub.add_parser("verify", help="Verify one sendable package")
    review_board_verify_group = review_board_verify.add_mutually_exclusive_group(required=True)
    review_board_verify_group.add_argument("--latest", action="store_true", help="Verify the latest package")
    review_board_verify_group.add_argument("--path", help="Package root or ZIP path to verify")
    review_board_verify.add_argument("--workspace", help="Workspace root override")
    review_board_verify.add_argument("--ticket-id", help="Optional ticket id filter for --latest")
    review_board_verify.add_argument("--json", action="store_true", help="Print verification payload as JSON")

    review_priority = sub.add_parser(
        "review-priority",
        help="Inspect latest screenshot review-priority artifacts as structured JSON",
    )
    review_priority_sub = review_priority.add_subparsers(dest="review_priority_command", required=True)
    review_priority_latest = review_priority_sub.add_parser("latest", help="Load latest review-priority artifact")
    review_priority_latest.add_argument("--workspace", help="Workspace root override")
    review_priority_latest.add_argument("--ticket-id", help="Optional ticket id filter")
    review_priority_latest.add_argument("--json", action="store_true", help="Print review-priority payload as JSON")

    daily_delta = sub.add_parser(
        "daily-delta",
        help="Inspect latest daily QA delta artifacts as structured JSON",
    )
    daily_delta_sub = daily_delta.add_subparsers(dest="daily_delta_command", required=True)
    daily_delta_latest = daily_delta_sub.add_parser("latest", help="Load latest daily QA delta artifact")
    daily_delta_latest.add_argument("--workspace", help="Workspace root override")
    daily_delta_latest.add_argument("--ticket-id", help="Optional ticket id filter")
    daily_delta_latest.add_argument("--json", action="store_true", help="Print daily-delta payload as JSON")

    daily_digest = sub.add_parser(
        "daily-digest",
        help="Build the copy-ready daily QA digest from the latest review-board state",
    )
    daily_digest_sub = daily_digest.add_subparsers(dest="daily_digest_command", required=True)
    daily_digest_latest = daily_digest_sub.add_parser("latest", help="Load the latest daily QA digest")
    daily_digest_latest.add_argument("--workspace", help="Workspace root override")
    daily_digest_latest.add_argument("--ticket-id", help="Optional ticket id filter")
    daily_digest_latest.add_argument("--json", action="store_true", help="Print daily digest payload as JSON")
    daily_digest_latest.add_argument("--markdown", action="store_true", help="Print daily digest as Markdown")

    manual_review = sub.add_parser(
        "manual-review",
        help="Create and update operator-recorded RaCo / Blender manual-review sessions",
    )
    manual_review_sub = manual_review.add_subparsers(dest="manual_review_command", required=True)
    manual_review_session = manual_review_sub.add_parser("session", help="Create a manual-review session")
    manual_review_session.add_argument("--profile", required=True, help="Profile id such as G65")
    manual_review_session.add_argument("--ticket", required=True, help="Ticket id such as IDCEVODEV-977874")
    manual_review_session.add_argument("--workspace", help="Workspace root override")
    manual_review_session.add_argument("--output-root", help="Optional output root for manual-review sessions")
    manual_review_session.add_argument("--session-id", help="Optional deterministic session id")
    manual_review_session.add_argument("--json", action="store_true", help="Print session as JSON")
    manual_review_session.add_argument("--markdown", action="store_true", help="Print session summary as Markdown")

    manual_review_record = manual_review_sub.add_parser("record-step", help="Record one reviewer verdict")
    manual_review_record.add_argument("session_id", help="Manual-review session id or session.json path")
    manual_review_record.add_argument("--workspace", help="Workspace root override")
    manual_review_record.add_argument("--step", required=True, help="Step slug such as blender_visual_check")
    manual_review_record.add_argument("--verdict", required=True, choices=VALID_VERDICTS, help="Reviewer-recorded verdict")
    manual_review_record.add_argument("--note", default="", help="Reviewer note")
    manual_review_record.add_argument("--screenshot", default="", help="Optional existing screenshot path")
    manual_review_record.add_argument("--json", action="store_true", help="Print updated session as JSON")
    manual_review_record.add_argument("--markdown", action="store_true", help="Print updated session as Markdown")

    manual_review_summary = manual_review_sub.add_parser("summary", help="Render one manual-review session")
    manual_review_summary.add_argument("session_id", help="Manual-review session id or session.json path")
    manual_review_summary.add_argument("--workspace", help="Workspace root override")
    manual_review_summary.add_argument("--json", action="store_true", help="Print session as JSON")
    manual_review_summary.add_argument("--markdown", action="store_true", help="Print session summary as Markdown")

    for command_name, tool_name in (("open-raco", "raco"), ("open-blender", "blender")):
        open_parser = manual_review_sub.add_parser(command_name, help=f"Open {tool_name} for a manual-review step")
        open_parser.add_argument("session_id", help="Manual-review session id or session.json path")
        open_parser.add_argument("--workspace", help="Workspace root override")
        open_parser.add_argument("--step", required=True, help="Step slug to open for")
        open_parser.add_argument("--json", action="store_true", help="Print launch payload as JSON")

    review_decisions = sub.add_parser(
        "review-decisions",
        help="Record and inspect review-owner decisions using JSON as source-of-truth",
    )
    review_decisions_sub = review_decisions.add_subparsers(dest="review_decisions_command", required=True)
    review_decisions_latest = review_decisions_sub.add_parser("latest", help="Load latest review-owner decision state")
    review_decisions_latest.add_argument("ticket_id", help="Ticket id such as IDCEVODEV-960073")
    review_decisions_latest.add_argument("--workspace", help="Workspace root override")
    review_decisions_latest.add_argument("--json", action="store_true", help="Print decision payload as JSON")
    review_decisions_set = review_decisions_sub.add_parser("set", help="Set one review-owner decision")
    review_decisions_set.add_argument("ticket_id", help="Ticket id such as IDCEVODEV-960073")
    review_decisions_set.add_argument("decision_key", help="Decision key or title, such as lights_OnlyCones")
    review_decisions_set.add_argument("--status", required=True, help="Decision status such as follow_up or blocker")
    review_decisions_set.add_argument("--owner", default="", help="Decision owner")
    review_decisions_set.add_argument("--note", default="", help="Decision note")
    review_decisions_set.add_argument("--date", default="", help="Decision date override")
    review_decisions_set.add_argument("--title", default="", help="Optional display title override")
    review_decisions_set.add_argument("--workspace", help="Workspace root override")
    review_decisions_set.add_argument("--json", action="store_true", help="Print updated decision payload as JSON")

    external_findings = sub.add_parser(
        "external-findings",
        help="Record and inspect external findings such as Teams/Jira/manual review notes",
    )
    external_findings_sub = external_findings.add_subparsers(dest="external_findings_command", required=True)
    external_findings_latest = external_findings_sub.add_parser("latest", help="Load latest external findings")
    external_findings_latest.add_argument("ticket_id", help="Ticket id such as IDCEVODEV-960073")
    external_findings_latest.add_argument("--workspace", help="Workspace root override")
    external_findings_latest.add_argument("--json", action="store_true", help="Print findings payload as JSON")
    external_findings_add = external_findings_sub.add_parser("add", help="Add one external finding")
    external_findings_add.add_argument("ticket_id", help="Ticket id such as IDCEVODEV-960073")
    external_findings_add.add_argument("--source", required=True, help="Source such as Teams / 3D Car - Bug Reports / Jana")
    external_findings_add.add_argument("--reported-by", required=True, help="Reporter name")
    external_findings_add.add_argument("--category", required=True, help="Category such as changelog")
    external_findings_add.add_argument("--type", dest="finding_type", default="finding", help="Finding type label")
    external_findings_add.add_argument("--scope", action="append", required=True, help="Scope item, repeatable or comma-separated")
    external_findings_add.add_argument("--finding", required=True, help="Finding text")
    external_findings_add.add_argument("--owner", default="", help="Named owner for the finding")
    external_findings_add.add_argument("--status", default="reported", help="Finding status")
    external_findings_add.add_argument("--note", default="", help="Optional note")
    external_findings_add.add_argument("--related-surface", action="append", default=[], help="Related investigation surface, repeatable")
    external_findings_add.add_argument("--workspace", help="Workspace root override")
    external_findings_add.add_argument("--json", action="store_true", help="Print updated findings payload as JSON")

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
    run_action.add_argument("--workspace", help="Workspace root override")
    run_action.add_argument("--json", action="store_true", help="Print action record as JSON")

    launch_action = sub.add_parser(
        "launch-action",
        help="Queue one-click SG QA action and return immediately for polling clients",
    )
    launch_action.add_argument("action_id", help="Operator action id such as daily_live_matrix or qa_stack__g65")
    launch_action.add_argument("--workspace", help="Workspace root override")
    launch_action.add_argument("--json", action="store_true", help="Print the queued action record as JSON")

    run_action_worker = sub.add_parser("run-action-worker", help=argparse.SUPPRESS)
    run_action_worker.add_argument("action_id", help=argparse.SUPPRESS)
    run_action_worker.add_argument("--run-id", required=True, help=argparse.SUPPRESS)
    run_action_worker.add_argument("--workspace", required=True, help=argparse.SUPPRESS)

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

    desktop_state = sub.add_parser(
        "desktop-state",
        help="Inspect native/desktop-shell state snapshots from the shared Python core",
    )
    desktop_state_sub = desktop_state.add_subparsers(dest="desktop_state_command", required=True)

    desktop_profiles_parser = desktop_state_sub.add_parser("profiles", help="List ready desktop profiles")
    desktop_profiles_parser.add_argument("--workspace", help="Workspace root override")
    desktop_profiles_parser.add_argument("--json", action="store_true", help="Print profile payload as JSON")

    desktop_overview_parser = desktop_state_sub.add_parser(
        "overview",
        help="Load compact native-shell startup and heartbeat state",
    )
    desktop_overview_parser.add_argument("--profile-id", help="Optional profile filter")
    desktop_overview_parser.add_argument("--workspace", help="Workspace root override")
    desktop_overview_parser.add_argument("--json", action="store_true", help="Print overview payload as JSON")

    desktop_actions_parser = desktop_state_sub.add_parser("actions", help="List desktop actions for one profile")
    desktop_actions_parser.add_argument("profile_id", help="Profile id such as G65")
    desktop_actions_parser.add_argument("--workspace", help="Workspace root override")
    desktop_actions_parser.add_argument("--json", action="store_true", help="Print action payload as JSON")

    desktop_blockers_parser = desktop_state_sub.add_parser("blockers", help="List blocker cards for one profile")
    desktop_blockers_parser.add_argument("profile_id", help="Profile id such as G65")
    desktop_blockers_parser.add_argument("--workspace", help="Workspace root override")
    desktop_blockers_parser.add_argument("--json", action="store_true", help="Print blocker payload as JSON")

    desktop_manual_parser = desktop_state_sub.add_parser("manual", help="List manual-review cards for one profile")
    desktop_manual_parser.add_argument("profile_id", help="Profile id such as G65")
    desktop_manual_parser.add_argument("--workspace", help="Workspace root override")
    desktop_manual_parser.add_argument("--json", action="store_true", help="Print manual-card payload as JSON")

    desktop_snapshot_parser = desktop_state_sub.add_parser("snapshot", help="Load one desktop action snapshot")
    desktop_snapshot_parser.add_argument("run_id_or_path", help="Action run id or action.json path")
    desktop_snapshot_parser.add_argument("--workspace", help="Workspace root override")
    desktop_snapshot_parser.add_argument("--json", action="store_true", help="Print snapshot payload as JSON")

    desktop_recent_parser = desktop_state_sub.add_parser(
        "recent-actions",
        help="List recent action records for desktop-shell browsing",
    )
    desktop_recent_parser.add_argument("--profile-id", help="Optional profile filter")
    desktop_recent_parser.add_argument("--limit", type=int, default=12, help="Maximum number of actions to return")
    desktop_recent_parser.add_argument("--workspace", help="Workspace root override")
    desktop_recent_parser.add_argument("--json", action="store_true", help="Print recent-action payload as JSON")

    desktop_recent_runs_parser = desktop_state_sub.add_parser(
        "recent-runs",
        help="List recent run records for desktop-shell browsing",
    )
    desktop_recent_runs_parser.add_argument("--profile-id", help="Optional profile filter")
    desktop_recent_runs_parser.add_argument("--limit", type=int, default=12, help="Maximum number of runs to return")
    desktop_recent_runs_parser.add_argument("--workspace", help="Workspace root override")
    desktop_recent_runs_parser.add_argument("--json", action="store_true", help="Print recent-run payload as JSON")

    desktop_run_snapshot_parser = desktop_state_sub.add_parser(
        "run-snapshot",
        help="Load one desktop run snapshot",
    )
    desktop_run_snapshot_parser.add_argument("run_id_or_path", help="Run id or run.json path")
    desktop_run_snapshot_parser.add_argument("--workspace", help="Workspace root override")
    desktop_run_snapshot_parser.add_argument("--json", action="store_true", help="Print run snapshot payload as JSON")

    desktop_environment_parser = desktop_state_sub.add_parser(
        "environment",
        help="Load the native environment-doctor readiness surface",
    )
    desktop_environment_parser.add_argument("--workspace", help="Workspace root override")
    desktop_environment_parser.add_argument("--json", action="store_true", help="Print environment payload as JSON")

    desktop_review_board_parser = desktop_state_sub.add_parser(
        "review-board",
        help="Load the latest review-board state for native-shell consumers",
    )
    desktop_review_board_parser.add_argument("--ticket-id", help="Optional ticket id filter")
    desktop_review_board_parser.add_argument("--workspace", help="Workspace root override")
    desktop_review_board_parser.add_argument("--json", action="store_true", help="Print review-board payload as JSON")

    desktop_attach_manual_parser = desktop_state_sub.add_parser(
        "attach-manual-evidence",
        help="Attach manual evidence into one action bundle",
    )
    desktop_attach_manual_parser.add_argument("run_id_or_path", help="Action run id or action.json path")
    desktop_attach_manual_parser.add_argument("--kind", required=True, help="Evidence kind such as screenshot or blender_note")
    desktop_attach_manual_parser.add_argument("--label", default="", help="Optional evidence label override")
    desktop_attach_manual_parser.add_argument("--source", default="", help="Optional source file to copy into the action bundle")
    desktop_attach_manual_parser.add_argument("--note", default="", help="Optional note text for note-based evidence")
    desktop_attach_manual_parser.add_argument("--workspace", help="Workspace root override")
    desktop_attach_manual_parser.add_argument("--json", action="store_true", help="Print attachment payload as JSON")

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
        help="Parse a team retrospective export into structured SG-preflight pain/action output",
        description="Parse a team retrospective export into structured SG-preflight pain/action output",
    )
    retro.add_argument("--html", required=True, help="Path to exported team retrospective HTML")
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

    if args.command == "delivery-checklist":
        checklist_root = Path(args.workspace).resolve() if getattr(args, "workspace", None) else root
        try:
            if args.delivery_checklist_command == "read":
                payload = read_delivery_checklist(
                    profile_id=args.profile,
                    workspace=checklist_root,
                    workbook_path=Path(args.workbook).resolve() if args.workbook else None,
                    brand=args.brand,
                )
            else:
                parser.error(f"Unhandled delivery-checklist command: {args.delivery_checklist_command}")
                return 1
        except Exception as exc:
            print(_console_safe(f"delivery-checklist failed: {exc}"), file=sys.stderr)
            return 1
        if args.json:
            _console_desktop_payload(payload)
        elif args.markdown:
            print(_console_safe(render_delivery_checklist_markdown(payload)))
        else:
            print(_console_safe(render_delivery_checklist_text(payload)))
        return 0

    if args.command == "export-size-analysis":
        analysis_root = Path(args.workspace).resolve() if getattr(args, "workspace", None) else root
        try:
            if args.export_size_analysis_command == "read":
                payload = read_export_size_analysis(
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
            print(_console_safe(f"export-size-analysis failed: {exc}"), file=sys.stderr)
            return 1
        if args.json:
            _console_desktop_payload(payload)
        elif args.markdown:
            print(_console_safe(render_export_size_analysis_markdown(payload)))
        else:
            print(_console_safe(render_export_size_analysis_text(payload)))
        return 0

    if args.command == "screenshot-test-state":
        screenshot_state_root = Path(args.workspace).resolve() if getattr(args, "workspace", None) else root
        try:
            if args.screenshot_test_state_command == "read":
                payload = read_bmw_screenshot_state(
                    args.profile,
                    workspace=screenshot_state_root,
                )
            else:
                parser.error(f"Unhandled screenshot-test-state command: {args.screenshot_test_state_command}")
                return 1
        except Exception as exc:
            print(_console_safe(f"screenshot-test-state failed: {exc}"), file=sys.stderr)
            return 1
        if args.json:
            _console_desktop_payload(payload)
        elif args.markdown:
            print(_console_safe(render_bmw_screenshot_state_markdown(payload)))
        else:
            print(_console_safe(render_bmw_screenshot_state_text(payload)))
        return 0

    if args.command == "bmw-git-readiness":
        readiness_root = Path(args.workspace).resolve() if getattr(args, "workspace", None) else root
        try:
            if args.bmw_git_readiness_command == "read":
                payload = read_bmw_git_readiness(
                    args.profile,
                    workspace=readiness_root,
                    bmw_root=Path(args.bmw_root).resolve() if args.bmw_root else None,
                )
            else:
                parser.error(f"Unhandled bmw-git-readiness command: {args.bmw_git_readiness_command}")
                return 1
        except Exception as exc:
            print(_console_safe(f"bmw-git-readiness failed: {exc}"), file=sys.stderr)
            return 1
        if args.json:
            _console_desktop_payload(payload)
        elif args.markdown:
            print(_console_safe(render_bmw_git_readiness_markdown(payload)))
        else:
            print(_console_safe(render_bmw_git_readiness_text(payload)))
        return 0

    if args.command == "workflow-status":
        items = qa_workflow_status(root)
        _console_workflow_status(items, as_json=args.json)
        return 0

    if args.command == "ticket-review":
        review_root = Path(args.workspace).resolve() if args.workspace else root
        output_root = (
            Path(args.output_root).resolve()
            if args.output_root
            else default_ticket_review_output_root(args.ticket_id, review_root)
        )
        try:
            result = materialize_ticket_review_bundle(
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
            print(_console_safe(f"ticket-review failed: {exc}"), file=sys.stderr)
            return 1
        _console_ticket_review(result, as_json=args.json)
        return 0

    if args.command == "screenshot-triage":
        triage_root = Path(args.workspace).resolve() if args.workspace else root
        if not args.profile and not args.project_root:
            parser.error("screenshot-triage needs either --profile or --project-root")
            return 1
        try:
            if args.profile:
                profile = get_run_profile(args.profile, triage_root)
                profile_id = profile.profile_id
                project_root = profile.source_project_root()
            else:
                project_root = Path(args.project_root).resolve()
                profile_id = project_root.name
            prep = build_visual_review_prep(profile_id, project_root)
            output_root = (
                Path(args.output_root).resolve()
                if args.output_root
                else triage_root / "out" / f"{profile_id.lower()}-screenshot-triage"
            )
            bundle = materialize_screenshot_triage(
                profile_id,
                project_root,
                output_root,
                candidate_roots=tuple(Path(item).resolve() for item in args.candidate_root if str(item).strip()),
                priority_names=tuple(str(item) for item in prep.priority_screenshots),
            )
        except Exception as exc:
            print(_console_safe(f"screenshot-triage failed: {exc}"), file=sys.stderr)
            return 1
        _console_screenshot_triage(bundle, as_json=args.json)
        return 0

    if args.command == "daily-qa-snapshot":
        snapshot_root = Path(args.workspace).resolve() if args.workspace else root
        output_root = Path(args.output_root).resolve() if args.output_root else None
        profile_ids = tuple(str(item).strip() for item in args.profile if str(item).strip())
        battery_filters = tuple(str(item).strip() for item in args.battery_filter if str(item).strip())
        if args.battery_defaults:
            battery_filters = (
                "default",
                "openAllDoors_",
                "lights_drl_front",
                "lights_LowBeam",
                "lights_HighBeam",
                "lights_OnlyCones",
                "welcome_animation_",
                "automatic_Doors_",
                "highlighting_Doors",
            ) + tuple(item for item in battery_filters if item not in {
                "default",
                "openAllDoors_",
                "lights_drl_front",
                "lights_LowBeam",
                "lights_HighBeam",
                "lights_OnlyCones",
                "welcome_animation_",
                "automatic_Doors_",
                "highlighting_Doors",
            })
        try:
            result = materialize_daily_qa_snapshot(
                workspace_root=snapshot_root,
                output_root=output_root,
                profile_ids=profile_ids or ("NA8", "G78", "G50"),
                run_smoke=not args.no_smoke,
                smoke_test=args.smoke_test,
                battery_filters=battery_filters,
            )
        except Exception as exc:
            print(_console_safe(f"daily-qa-snapshot failed: {exc}"), file=sys.stderr)
            return 1
        _console_daily_snapshot(result, as_json=args.json)
        return 0

    if args.command == "review-board":
        review_root = Path(args.workspace).resolve() if getattr(args, "workspace", None) else root
        try:
            if args.review_board_command == "list":
                payload = list_review_packages(review_root)
            elif args.review_board_command == "latest":
                payload = build_review_board_state(args.ticket_id, review_root)
            elif args.review_board_command == "copy-update":
                state = build_review_board_state(args.ticket_id, review_root)
                payload = {
                    "ticket_id": state["ticket_id"],
                    "scope": state["scope"],
                    "generated_at": state["generated_at"],
                    "package_path": state["package_path"],
                    "text": build_review_owner_update(state),
                }
            elif args.review_board_command == "verify":
                if args.latest:
                    latest = build_review_board_state(args.ticket_id, review_root)
                    payload = verify_sendable_package(latest["package_zip_path"] or latest["package_path"], review_root)
                else:
                    payload = verify_sendable_package(args.path, review_root)
            else:
                parser.error(f"Unhandled review-board command: {args.review_board_command}")
                return 1
        except Exception as exc:
            print(_console_safe(f"review-board failed: {exc}"), file=sys.stderr)
            return 1
        if args.review_board_command == "copy-update" and not args.json:
            print(_console_safe(str(payload["text"])))
        else:
            _console_desktop_payload(payload)
        return 0

    if args.command == "review-priority":
        review_root = Path(args.workspace).resolve() if getattr(args, "workspace", None) else root
        try:
            if args.review_priority_command == "latest":
                payload = load_review_priority(args.ticket_id, review_root)
            else:
                parser.error(f"Unhandled review-priority command: {args.review_priority_command}")
                return 1
        except Exception as exc:
            print(_console_safe(f"review-priority failed: {exc}"), file=sys.stderr)
            return 1
        _console_desktop_payload(payload)
        return 0

    if args.command == "daily-delta":
        delta_root = Path(args.workspace).resolve() if getattr(args, "workspace", None) else root
        try:
            if args.daily_delta_command == "latest":
                payload = load_daily_delta(args.ticket_id, delta_root)
            else:
                parser.error(f"Unhandled daily-delta command: {args.daily_delta_command}")
                return 1
        except Exception as exc:
            print(_console_safe(f"daily-delta failed: {exc}"), file=sys.stderr)
            return 1
        _console_desktop_payload(payload)
        return 0

    if args.command == "daily-digest":
        digest_root = Path(args.workspace).resolve() if getattr(args, "workspace", None) else root
        try:
            if args.daily_digest_command == "latest":
                payload = build_latest_daily_digest(args.ticket_id, digest_root)
            else:
                parser.error(f"Unhandled daily-digest command: {args.daily_digest_command}")
                return 1
        except Exception as exc:
            print(_console_safe(f"daily-digest failed: {exc}"), file=sys.stderr)
            return 1
        if args.json:
            _console_desktop_payload(payload)
        elif args.markdown:
            print(_console_safe(render_daily_digest_markdown(payload)))
        else:
            print(_console_safe(render_daily_digest_text(payload)))
        return 0

    if args.command == "manual-review":
        review_root = Path(args.workspace).resolve() if getattr(args, "workspace", None) else root
        try:
            if args.manual_review_command == "session":
                payload = create_manual_review_session(
                    profile_id=args.profile,
                    ticket_id=args.ticket,
                    workspace=review_root,
                    output_root=Path(args.output_root).resolve() if args.output_root else None,
                    session_id=args.session_id,
                )
            elif args.manual_review_command == "record-step":
                payload = record_manual_review_step(
                    args.session_id,
                    args.step,
                    args.verdict,
                    workspace=review_root,
                    note=args.note,
                    screenshot=Path(args.screenshot).resolve() if args.screenshot else None,
                )
            elif args.manual_review_command == "summary":
                payload = load_manual_review_session(args.session_id, workspace=review_root)
            elif args.manual_review_command == "open-raco":
                payload = open_manual_review_tool(args.session_id, args.step, tool="raco", workspace=review_root)
            elif args.manual_review_command == "open-blender":
                payload = open_manual_review_tool(args.session_id, args.step, tool="blender", workspace=review_root)
            else:
                parser.error(f"Unhandled manual-review command: {args.manual_review_command}")
                return 1
        except Exception as exc:
            print(_console_safe(f"manual-review failed: {exc}"), file=sys.stderr)
            return 1
        if getattr(args, "json", False):
            _console_desktop_payload(payload)
        elif getattr(args, "markdown", False) or args.manual_review_command == "summary":
            print(_console_safe(render_manual_review_markdown(payload)))
        else:
            print(_console_safe(f"Manual review session: {payload.get('session_id', '')}"))
            if payload.get("session_path"):
                print(_console_safe(f"Session JSON: {payload['session_path']}"))
            if payload.get("markdown_path"):
                print(_console_safe(f"Markdown: {payload['markdown_path']}"))
        return 0

    if args.command == "review-decisions":
        tracking_root = Path(args.workspace).resolve() if getattr(args, "workspace", None) else root
        try:
            if args.review_decisions_command == "latest":
                package = load_latest_review_package(args.ticket_id, tracking_root)
                fallback_path = Path(package["review_owner_decisions"]["absolute_path"]) if package["review_owner_decisions"]["absolute_path"] else None
                payload = load_review_decisions(args.ticket_id, tracking_root, fallback_markdown_path=fallback_path)
            elif args.review_decisions_command == "set":
                package = load_latest_review_package(args.ticket_id, tracking_root)
                fallback_path = Path(package["review_owner_decisions"]["absolute_path"]) if package["review_owner_decisions"]["absolute_path"] else None
                payload = set_review_decision(
                    args.ticket_id,
                    args.decision_key,
                    status=args.status,
                    owner=args.owner,
                    note=args.note,
                    date=args.date,
                    title=args.title,
                    workspace=tracking_root,
                    fallback_markdown_path=fallback_path,
                )
            else:
                parser.error(f"Unhandled review-decisions command: {args.review_decisions_command}")
                return 1
        except Exception as exc:
            print(_console_safe(f"review-decisions failed: {exc}"), file=sys.stderr)
            return 1
        _console_desktop_payload(payload)
        return 0

    if args.command == "external-findings":
        tracking_root = Path(args.workspace).resolve() if getattr(args, "workspace", None) else root
        try:
            if args.external_findings_command == "latest":
                payload = load_external_findings(args.ticket_id, tracking_root)
            elif args.external_findings_command == "add":
                scopes: list[str] = []
                for item in args.scope:
                    scopes.extend(part.strip() for part in str(item).split(",") if part.strip())
                payload = add_external_finding(
                    args.ticket_id,
                    source=args.source,
                    reported_by=args.reported_by,
                    category=args.category,
                    scope=scopes,
                    finding=args.finding,
                    owner=args.owner,
                    status=args.status,
                    note=args.note,
                    finding_type=args.finding_type,
                    related_investigation_surfaces=args.related_surface,
                    workspace=tracking_root,
                )
            else:
                parser.error(f"Unhandled external-findings command: {args.external_findings_command}")
                return 1
        except Exception as exc:
            print(_console_safe(f"external-findings failed: {exc}"), file=sys.stderr)
            return 1
        _console_desktop_payload(payload)
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
            action_root = Path(args.workspace).resolve() if args.workspace else root
            action = get_operator_action(args.action_id, action_root)
        except KeyError as exc:
            parser.error(str(exc))
            return 1

        try:
            record = execute_operator_action(action, action_root)
        except Exception as exc:
            print(_console_safe(f"run-action failed: {exc}"), file=sys.stderr)
            return 1
        _console_action_record(record, as_json=args.json)
        return 0 if record.status in {"completed", "blocked"} else 1

    if args.command == "launch-action":
        action_root = Path(args.workspace).resolve() if args.workspace else root
        try:
            action = get_operator_action(args.action_id, action_root)
        except KeyError as exc:
            parser.error(str(exc))
            return 1

        record = build_action_record(action, action_root)
        save_action_record(record)
        worker_command = [
            sys.executable,
            "-m",
            "sg_preflight",
            "run-action-worker",
            action.action_id,
            "--run-id",
            record.run_id,
            "--workspace",
            str(action_root),
        ]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            subprocess.Popen(
                worker_command,
                cwd=action_root,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        except OSError as exc:
            print(_console_safe(f"launch-action failed: {exc}"), file=sys.stderr)
            return 1
        _console_action_record(record, as_json=args.json)
        return 0

    if args.command == "run-action-worker":
        action_root = Path(args.workspace).resolve()
        try:
            action = get_operator_action(args.action_id, action_root)
            record = load_action_record(args.run_id, action_root)
            result = execute_operator_action(action, action_root, record=record)
        except Exception as exc:
            print(_console_safe(f"run-action-worker failed: {exc}"), file=sys.stderr)
            return 1
        return 0 if result.status in {"completed", "blocked"} else 1

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

    if args.command == "desktop-state":
        state_root = Path(args.workspace).resolve() if getattr(args, "workspace", None) else root
        if args.desktop_state_command == "profiles":
            payload = desktop_profiles(state_root)
        elif args.desktop_state_command == "overview":
            payload = desktop_operator_overview(
                state_root,
                profile_id=args.profile_id or "",
            )
        elif args.desktop_state_command == "actions":
            payload = desktop_actions_for_profile(args.profile_id, state_root)
        elif args.desktop_state_command == "blockers":
            payload = desktop_blocker_items(args.profile_id, state_root)
        elif args.desktop_state_command == "manual":
            payload = desktop_manual_cards(args.profile_id, state_root)
        elif args.desktop_state_command == "snapshot":
            payload = desktop_action_snapshot(args.run_id_or_path, state_root)
        elif args.desktop_state_command == "recent-actions":
            payload = desktop_recent_actions(
                state_root,
                profile_id=args.profile_id or "",
                limit=args.limit,
            )
        elif args.desktop_state_command == "recent-runs":
            payload = desktop_recent_runs(
                state_root,
                profile_id=args.profile_id or "",
                limit=args.limit,
            )
        elif args.desktop_state_command == "run-snapshot":
            payload = desktop_run_snapshot(args.run_id_or_path, state_root)
        elif args.desktop_state_command == "environment":
            payload = desktop_environment_doctor(state_root)
        elif args.desktop_state_command == "review-board":
            payload = build_review_board_state(args.ticket_id or None, state_root)
        elif args.desktop_state_command == "attach-manual-evidence":
            payload = attach_manual_evidence(
                args.run_id_or_path,
                state_root,
                kind=args.kind,
                label=args.label,
                source_path=args.source,
                note=args.note,
            )
        else:
            parser.error(f"Unhandled desktop-state command: {args.desktop_state_command}")
            return 1

        if getattr(args, "json", False):
            _console_desktop_payload(payload)
        else:
            _console_desktop_payload(payload)
        return 0

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


if __name__ == "__main__":
    raise SystemExit(main())
