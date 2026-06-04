from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

from sg_preflight import __version__
from sg_preflight.adapters.common import write_json as write_adapter_json
from sg_preflight.adapters.discovery import default_search_roots, probe_workspace
from sg_preflight.adapters.materialize import materialize_bundle
from sg_preflight.activity_log import (
    append_activity_entry,
    read_activity_entries,
    render_activity_log_text,
)
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
from sg_preflight.bmw_pipeline_auto_fix import (
    render_missing_actual_diagnostic_markdown,
    render_missing_actual_diagnostic_text,
    run_missing_actual_diagnostic_chain,
)
from sg_preflight.cross_car_comparison import (
    build_cross_car_comparison,
    render_cross_car_comparison_markdown,
    render_cross_car_comparison_text,
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
    desktop_surface_items,
)
from sg_preflight.desktop_notifications import notification_text, notify_desktop_completion
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
from sg_preflight.delivery_workbook_generation import (
    build_delivery_workbook_trigger,
    render_delivery_workbook_trigger_markdown,
    render_delivery_workbook_trigger_text,
)
from sg_preflight.export_size_analysis import (
    read_export_size_analysis,
    render_export_size_analysis_markdown,
    render_export_size_analysis_text,
)
from sg_preflight.export_size_trend import (
    SIGNIFICANT_CHANGE_LABEL,
    UNREADABLE_LAYOUT_LABEL,
    build_export_size_trend_board,
    write_export_size_trend_board,
)
from sg_preflight.full_qa_pass import (
    build_full_qa_pass,
    render_full_qa_pass_markdown,
    render_full_qa_pass_text,
)
from sg_preflight.jira_client import (
    DEFAULT_BASE_URL_ENV,
    DEFAULT_TOKEN_ENV,
    JIRA_POSTING_BANNER,
    ConfigError,
    JiraPostError,
    attach_jira_file_action,
    jira_status,
    load_jira_comment_source,
    post_jira_comment,
    post_jira_comment_action,
    render_jira_post_markdown,
    render_jira_post_text,
    render_jira_action_markdown,
    render_jira_action_text,
    update_jira_issue_action,
    write_jira_credentials,
)
from sg_preflight.manual_review import (
    VALID_VERDICTS,
    build_manual_review_assist,
    create_manual_review_session,
    create_manual_review_session_from_template,
    list_car_review_templates,
    load_manual_review_session,
    open_manual_review_tool,
    record_manual_review_step,
    render_manual_review_assist_markdown,
    render_manual_review_auto_checks_markdown,
    render_manual_review_markdown,
    run_manual_review_auto_checks,
)
from sg_preflight.operator_handoff import (
    build_operator_handoff_snapshot,
    record_operator_handoff,
    render_operator_handoff_markdown,
    render_operator_handoff_text,
)
from sg_preflight.onboarding_assistant import (
    build_onboarding_guide,
    render_onboarding_guide_markdown,
    render_onboarding_guide_text,
)
from sg_preflight.qa_hero_readiness import (
    read_qa_hero_readiness,
    render_qa_hero_readiness_markdown,
    render_qa_hero_readiness_text,
)
from sg_preflight.delivery_readiness import (
    build_delivery_readiness_board,
    write_delivery_readiness_board,
)
from sg_preflight.api_version_coverage import (
    IMPACT_REVIEW_LABEL,
    build_api_version_coverage_board,
    write_api_version_coverage_board,
)
from sg_preflight.country_variant_coverage import (
    MAPPING_REVIEW_LABEL,
    MISSING_EXPECTED_LABEL,
    NO_RUNTIME_LABEL,
    build_country_variant_coverage_board,
    write_country_variant_coverage_board,
)
from sg_preflight.disabled_tests import (
    CAUTIOUS_BASELINE_LABEL,
    build_disabled_tests_board,
    write_disabled_tests_board,
)
from sg_preflight.profiles import get_run_profile, list_run_profiles
from sg_preflight.risk_scoring import (
    read_per_car_risk_score,
    render_risk_score_markdown,
    render_risk_score_text,
)
from sg_preflight.qa_actions import (
    attach_manual_evidence,
    build_action_record,
    execute_operator_action,
    get_operator_action,
    list_operator_actions,
    load_action_record,
    save_action_record,
)
from sg_preflight.quality_hero_report import build_quality_hero_report
from sg_preflight.review_messages import build_review_owner_update
from sg_preflight.review_tracking import (
    add_external_finding,
    load_external_findings,
    load_review_decisions,
    set_review_decision,
)
from sg_preflight.retro import parse_retro_export, write_retro_json, write_retro_markdown
from sg_preflight.screenshot_review_viewer import build_screenshot_review_viewer
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
from sg_preflight.subprocess_utils import sgfx_cli_command
from sg_preflight.setup_doctor import build_setup_doctor_report
from sg_preflight.daily_snapshot import materialize_daily_qa_snapshot
from sg_preflight.review_state import (
    build_review_board_state,
    list_review_packages,
    load_daily_delta,
    load_latest_review_package,
    load_review_priority,
    verify_sendable_package,
)
from sg_preflight.screenshot_triage import (
    DEFAULT_VISUAL_DIFF_THRESHOLDS,
    VisualDiffThresholds,
    materialize_screenshot_triage,
)
from sg_preflight.team_digest_board import (
    build_team_daily_digest_board,
    render_team_digest_board_markdown,
    render_team_digest_board_text,
)
from sg_preflight.ticket_review import (
    default_ticket_review_output_root,
    materialize_ticket_review_bundle,
)
from sg_preflight.template_store import (
    TEMPLATE_BANNER,
    TemplateStoreError,
    delete_template,
    list_templates,
    load_template,
    parse_template_args,
    record_template_run,
    save_template,
    template_cli_args,
    template_path,
)
from sg_preflight.visual_review import build_visual_review_prep


root = Path(__file__).resolve().parents[2]
default_config = root / "config" / "sg_rules.json"


def _is_frozen_exe() -> bool:
    return bool(getattr(sys, "frozen", False))


def _resolve_workspace(args: argparse.Namespace, fallback_root: Path = root) -> Path:
    return Path(args.workspace).resolve() if getattr(args, "workspace", None) else fallback_root


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


def _json_text(payload: object) -> str:
    return json.dumps(_json_ready(payload), indent=2, ensure_ascii=False)


def _add_render_options(
    parser: argparse.ArgumentParser,
    *,
    formats: tuple[str, ...] = ("text", "json", "markdown"),
) -> None:
    parser.add_argument(
        "--format",
        choices=formats,
        default="",
        help="Output format. Backward-compatible --json and --markdown aliases still work where available.",
    )
    parser.add_argument(
        "--output-path",
        "--out",
        dest="output_path",
        default="",
        help="Write rendered command output to this file instead of stdout.",
    )


def _resolve_render_format(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    *,
    default: str = "text",
    formats: tuple[str, ...] = ("text", "json", "markdown"),
) -> str:
    selected = str(getattr(args, "format", "") or "").strip().lower()
    legacy: list[str] = []
    if getattr(args, "json", False):
        legacy.append("json")
    if getattr(args, "markdown", False):
        legacy.append("markdown")
    unique_legacy = sorted(set(legacy))
    if len(unique_legacy) > 1:
        parser.error("--json and --markdown cannot be combined; use --format instead")
    if selected and unique_legacy and selected != unique_legacy[0]:
        parser.error(f"--format {selected} cannot be combined with --{unique_legacy[0]}")
    resolved = selected or (unique_legacy[0] if unique_legacy else default)
    if resolved not in formats:
        parser.error(f"--format {resolved} is not supported for this command")
    return resolved


def _emit_text(text: str, args: argparse.Namespace) -> None:
    output_path = str(getattr(args, "output_path", "") or "").strip()
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        return
    try:
        print(_console_safe(text))
    except OSError as exc:
        if _is_detached_frozen_stdout_error(exc):
            return
        raise


def _emit_json(payload: object, args: argparse.Namespace) -> None:
    _emit_text(_json_text(payload), args)


def _build_metadata_for_summary() -> tuple[str, str]:
    """Return (build_commit, exe_sha256) — best-effort, never raises."""
    commit = ""
    sha = ""
    try:
        from sg_preflight import __version__  # noqa: F401
        # Reuse the dashboard helpers when available.
        from sg_preflight.dashboard import main as dashboard_main
        try:
            commit = dashboard_main._dashboard_build_sha()
        except Exception:
            commit = ""
        try:
            sha = dashboard_main._dashboard_exe_sha256()
        except Exception:
            sha = ""
    except Exception:
        pass
    return commit or "unknown", sha or "unavailable"


def _emit_console(render: Callable[[], None], args: argparse.Namespace) -> None:
    output_path = str(getattr(args, "output_path", "") or "").strip()
    if not output_path:
        try:
            render()
        except OSError as exc:
            if _is_detached_frozen_stdout_error(exc):
                return
            raise
        return
    import io
    from contextlib import redirect_stdout

    stdout = io.StringIO()
    with redirect_stdout(stdout):
        render()
    _emit_text(stdout.getvalue().rstrip("\n"), args)


def _is_detached_frozen_stdout_error(exc: OSError) -> bool:
    return bool(_is_frozen_exe() and getattr(exc, "errno", None) == 22)


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
        state = "available" if action.ready else "blocked"
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
    from sg_preflight.cli.workflows import _console_workflow_status as render

    render(items, as_json=as_json)


def _console_setup_doctor(report: object, *, as_json: bool) -> None:
    payload = report.to_dict()
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    print(payload["headline"])
    print(f"Workspace: {payload['workspace_root']}")
    print(
        "Summary -> "
        f"found: {payload['found_count']} | "
        f"required missing: {payload['required_missing_count']} | "
        f"optional missing: {payload['optional_missing_count']}"
    )
    print(f"Mode: {payload['mode']}")
    next_action = payload.get("next_action", {})
    if isinstance(next_action, dict):
        print(f"Next action: {next_action.get('label', '')}")
        if next_action.get("detail"):
            print(f"  {next_action['detail']}")
    wizard_steps = payload.get("wizard_steps", [])
    if wizard_steps:
        print("-" * 80)
        print("Wizard steps:")
        for step in wizard_steps:
            if not isinstance(step, dict):
                continue
            print(f"- {step.get('label', '')}: {step.get('status', '')}")
            if step.get("detail"):
                print(f"  {step['detail']}")
    print("-" * 80)
    for item in payload["items"]:
        marker = "OK" if item["status"] == "found" else ("OPTIONAL" if not item["required"] else "MISSING")
        print(f"[{marker}] {item['label']} ({item['category']})")
        if item["version"]:
            print(f"  version: {item['version']}")
        if item["path"]:
            print(f"  path: {item['path']}")
        if item["detail"]:
            print(f"  detail: {item['detail']}")
        if item["status"] != "found" and item["fix"]:
            print(f"  fix: {item['fix']}")


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
    from sg_preflight.cli.actions import _console_action_record as render

    render(record, as_json=as_json)


def _console_ticket_review(result: object, *, as_json: bool = False) -> None:
    from sg_preflight.cli.evidence import _console_ticket_review as render

    render(result, as_json=as_json)


def _console_screenshot_triage(bundle: object, *, as_json: bool = False) -> None:
    from sg_preflight.cli.screenshots import _console_screenshot_triage as render

    render(bundle, as_json=as_json)


def _console_screenshot_review_viewer(bundle: object, *, as_json: bool = False) -> None:
    from sg_preflight.cli.screenshots import _console_screenshot_review_viewer as render

    render(bundle, as_json=as_json)


def _screenshot_triage_thresholds(args: argparse.Namespace) -> VisualDiffThresholds:
    from sg_preflight.cli.screenshots import _screenshot_triage_thresholds as thresholds

    return thresholds(args)


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


def _render_template_command(template: dict[str, object]) -> str:
    command = str(template.get("command") or "")
    args = [str(item) for item in template.get("args", []) if str(item)]
    return " ".join([command, *args]).strip()


def _render_template_result(payload: dict[str, object]) -> str:
    template = payload.get("template")
    lines = [str(payload.get("note") or TEMPLATE_BANNER)]
    status = str(payload.get("status") or "").strip()
    if status:
        lines.append(f"Status: {status}")
    if isinstance(template, dict):
        lines.append(f"Template: {template.get('name', '')}")
        lines.append(f"Command: {_render_template_command(template)}")
        description = str(template.get("description") or "").strip()
        if description:
            lines.append(f"Description: {description}")
        last_run_at = str(template.get("last_run_at") or "").strip()
        if last_run_at:
            lines.append(f"Last run: {last_run_at} ({template.get('last_run_outcome', '')})")
    path = str(payload.get("path") or "").strip()
    if path:
        lines.append(f"Path: {path}")
    return "\n".join(lines)


def _render_template_list(payload: dict[str, object]) -> str:
    lines = [str(payload.get("note") or TEMPLATE_BANNER)]
    templates = payload.get("templates")
    if not isinstance(templates, list) or not templates:
        lines.append("No templates saved.")
        return "\n".join(lines)
    for template in templates:
        if isinstance(template, dict):
            last_run_at = str(template.get("last_run_at") or "").strip() or "never"
            lines.append(f"- {template.get('name', '')}: {_render_template_command(template)} | last run: {last_run_at}")
    return "\n".join(lines)


def _extract_arg_value(raw_args: list[str], *names: str) -> str:
    for index, item in enumerate(raw_args):
        if item in names and index + 1 < len(raw_args):
            return raw_args[index + 1]
        for name in names:
            prefix = f"{name}="
            if item.startswith(prefix):
                return item[len(prefix) :]
    return ""


def _activity_surface(raw_args: list[str]) -> str:
    parts = [item for item in raw_args[:3] if item and not item.startswith("-")]
    return " ".join(parts[:2] if len(parts) > 1 else parts) or "sg-preflight"


def _activity_verb(raw_args: list[str]) -> str:
    surface = " ".join(raw_args[:3]).lower()
    if "export" in surface or "materialize" in surface or "package" in surface:
        return "exported"
    if "run" in surface:
        return "ran"
    if "refresh" in surface:
        return "refreshed"
    return "read"


def _record_cli_activity(raw_args: list[str], exit_code: int) -> None:
    # Skip self-recording for the observability surfaces themselves so they do
    # not pollute the very signal an operator is trying to inspect.
    if not raw_args or raw_args[0] in {"activity-log", "live-state"}:
        return
    import os

    workspace = _extract_arg_value(raw_args, "--workspace") or os.environ.get("SG_PREFLIGHT_ACTIVITY_WORKSPACE", "")
    if not workspace:
        return
    try:
        append_activity_entry(
            Path(workspace),
            verb=_activity_verb(raw_args),
            surface=_activity_surface(raw_args),
            profile=_extract_arg_value(raw_args, "--profile", "--profile-id"),
            outcome="ok" if exit_code == 0 else "error",
            note=f"cli exit {exit_code}",
        )
    except Exception:
        return


class _SgfxArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args: object, **kwargs: object) -> None:
        kwargs.setdefault("formatter_class", argparse.RawDescriptionHelpFormatter)
        super().__init__(*args, **kwargs)


class _VersionAction(argparse.Action):
    def __init__(self, option_strings: list[str], dest: str = argparse.SUPPRESS, **kwargs: object) -> None:
        super().__init__(option_strings=option_strings, dest=dest, nargs=0, **kwargs)

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        parser._print_message(f"{_version_text()}\n", sys.stdout)
        parser.exit(0)


_MAIN_ACTION_MAP: tuple[tuple[str, str, str], ...] = (
    (
        "full-qa-pass",
        "Run the local QA pass sequence for one car.",
        r"sgfx-preflight.exe full-qa-pass run --profile G65 --workspace C:\repositories\trunk --format json",
    ),
    (
        "dashboard",
        "Open the Clean or Grafiks operator dashboard.",
        r"sgfx-preflight.exe dashboard run --workspace C:\repositories\trunk --ui-mode clean",
    ),
    (
        "screenshot-test-state",
        "Read local screenshot expected/actual/diff state.",
        "sgfx-preflight.exe screenshot-test-state read --profile G65 --format json",
    ),
    (
        "screenshot-review-viewer",
        "Build the side-by-side expected/actual/diff viewer.",
        r"sgfx-preflight.exe screenshot-review-viewer build --profile F70 --workspace C:\repositories\trunk",
    ),
    (
        "delivery-workbook",
        "Inspect the delivery workbook generation trigger.",
        r"sgfx-preflight.exe delivery-workbook trigger --profile F70 --workspace C:\repositories\trunk --format json",
    ),
    (
        "delivery-checklist",
        "Read the operator-local delivery checklist workbook.",
        r"sgfx-preflight.exe delivery-checklist read --profile G65 --workspace C:\repositories\trunk --format markdown",
    ),
    (
        "export-size-analysis",
        "Read the operator-local size-analysis workbook.",
        r"sgfx-preflight.exe export-size-analysis read --profile G65 --workspace C:\repositories\trunk --latest --format markdown",
    ),
    (
        "quality-hero-report",
        "Generate Markdown or HTML review reports from local evidence.",
        r"sgfx-preflight.exe quality-hero-report generate --profile G70 --workspace C:\repositories\trunk --format html",
    ),
    (
        "jira",
        "Preview or confirmation-post Jira comments and attachments.",
        'sgfx-preflight.exe jira post-comment --ticket IDCEVODEV-1009239 --body "Local QA evidence is ready for review." --format json',
    ),
    (
        "daily-digest",
        "Build the latest copy-ready local daily digest.",
        r"sgfx-preflight.exe daily-digest latest --workspace C:\repositories\trunk --format markdown",
    ),
    (
        "team-digest-board",
        "Build the local team digest board snapshot.",
        r"sgfx-preflight.exe team-digest-board snapshot --profile G70 --profile G65 --workspace C:\repositories\trunk --format markdown",
    ),
    (
        "risk-score",
        "Read per-car local risk score with review deltas.",
        r"sgfx-preflight.exe risk-score read --profile G65 --workspace C:\repositories\trunk --format json",
    ),
    (
        "cross-car-comparison",
        "Compare two profiles with the same local risk widget.",
        r"sgfx-preflight.exe cross-car-comparison snapshot --profile G70 --comparison-profile G65 --workspace C:\repositories\trunk --format json",
    ),
    (
        "profile-summary",
        "Build a shareable per-profile HTML or export the full evidence zip.",
        r"sgfx-preflight.exe profile-summary build --profile G70 --workspace C:\repositories\trunk --html-output G70_summary.html",
    ),
    (
        "operator-handoff",
        "Record or read an operator-local stopping point.",
        r"sgfx-preflight.exe operator-handoff latest --profile G65 --workspace C:\repositories\trunk --format markdown",
    ),
    (
        "manual-review",
        "Create and update operator-recorded manual-review sessions.",
        r"sgfx-preflight.exe manual-review assist --profile G65 --workspace C:\repositories\trunk --format markdown",
    ),
    (
        "bmw-git-readiness",
        "Read local BMW Git profile readiness without writing to it.",
        "sgfx-preflight.exe bmw-git-readiness read --profile G65 --format json",
    ),
    (
        "qa-hero-readiness",
        "Read local Quality Hero asset-readiness signals.",
        "sgfx-preflight.exe qa-hero-readiness read --profile G65 --format json",
    ),
    ("list-profiles", "List canonical live run profiles.", "sgfx-preflight.exe list-profiles --format json"),
    ("list-actions", "List one-click local actions.", "sgfx-preflight.exe list-actions --format json"),
    ("template", "Manage operator-local saved command templates.", "sgfx-preflight.exe template list --format json"),
    (
        "onboarding-guide",
        "Read setup guidance for one profile.",
        r"sgfx-preflight.exe onboarding-guide read --profile G65 --workspace C:\repositories\trunk --format markdown",
    ),
    (
        "desktop-notification",
        "Record or show a local desktop notification.",
        'sgfx-preflight.exe desktop-notification send --title "SGFX check complete" --message "F70 pass finished." --dry-run --format json',
    ),
    (
        "daily-qa-snapshot",
        "Run the local daily QA snapshot for selected profiles.",
        r"sgfx-preflight.exe daily-qa-snapshot --profile G70 --workspace C:\repositories\trunk --no-smoke --json",
    ),
    (
        "ticket-review",
        "Generate a ticket-centered local review package.",
        r"sgfx-preflight.exe ticket-review IDCEVODEV-1009239 --profile G70 --workspace C:\repositories\trunk --json",
    ),
    (
        "review-board",
        "Inspect local review-board packages.",
        r"sgfx-preflight.exe review-board latest --workspace C:\repositories\trunk --json",
    ),
    ("workflow-status", "List workflow coverage and known partial areas.", "sgfx-preflight.exe workflow-status --json"),
    (
        "activity-log",
        "Read or tail the operator-local activity log.",
        r"sgfx-preflight.exe activity-log read --workspace C:\repositories\trunk --tail",
    ),
    (
        "live-state",
        "Read or tail the operator-local dashboard live-state telemetry.",
        r"sgfx-preflight.exe live-state --workspace C:\repositories\trunk --tail",
    ),
    ("station", "Run the optional local OpenHTF station surface.", r"sgfx-preflight.exe station run --profile G65 --workspace C:\repositories\trunk --no-browser --once"),
    ("desktop-state", "Inspect desktop-shell state snapshots.", r"sgfx-preflight.exe desktop-state overview --profile-id G65 --workspace C:\repositories\trunk --json"),
    ("run-action", "Execute one registered local action.", r"sgfx-preflight.exe run-action qa_stack__g65 --workspace C:\repositories\trunk --json"),
    ("launch-action", "Queue one registered local action for polling clients.", r"sgfx-preflight.exe launch-action qa_stack__g65 --workspace C:\repositories\trunk --json"),
    ("review-priority", "Inspect latest screenshot review-priority artifact.", r"sgfx-preflight.exe review-priority latest --workspace C:\repositories\trunk --json"),
    ("daily-delta", "Inspect latest daily QA delta artifact.", r"sgfx-preflight.exe daily-delta latest --workspace C:\repositories\trunk --json"),
    ("review-decisions", "Record and inspect review-owner decisions.", r"sgfx-preflight.exe review-decisions latest IDCEVODEV-1009239 --workspace C:\repositories\trunk --json"),
    ("external-findings", "Record and inspect external review findings.", r"sgfx-preflight.exe external-findings latest IDCEVODEV-1009239 --workspace C:\repositories\trunk --json"),
    ("run-profile", "Materialize and validate one canonical profile.", r"sgfx-preflight.exe run-profile G65 --output-root out\run-profile-g65 --json"),
    ("run", "Run validation packs against an existing bundle.", r"sgfx-preflight.exe run --bundle out\bundle --config config\sg_rules.json --packs anchors --fail-on warning"),
    ("list-checkers", "List checker coverage and readiness.", "sgfx-preflight.exe list-checkers --format json"),
    (
        "bmw-pipeline-diagnostics",
        "Inspect missing-actual diagnostics with confirmation-gated refresh actions.",
        r"sgfx-preflight.exe bmw-pipeline-diagnostics missing-actuals --profile F70 --workspace C:\repositories\trunk --format json",
    ),
    ("screenshot-triage", "Run deterministic screenshot triage.", r"sgfx-preflight.exe screenshot-triage --profile F70 --workspace C:\repositories\trunk --json"),
    ("materialize", "Create a normalized validation bundle from SG-shaped inputs.", r"sgfx-preflight.exe materialize --output-bundle out\bundle --repo-root C:\repositories\trunk"),
    ("probe", "Discover SG-style repository roots and likely inputs.", r"sgfx-preflight.exe probe --search-root C:\repositories\trunk"),
    # internal milestone: `demo-good`, `demo-broken`, `ui`, `retro-extract` subcommands stay
    # registered for backward compat but are hidden from the operator-facing
    # action map. They're dev / legacy entries that don't belong in the daily-
    # use list.
)


_COMMAND_EXAMPLES: dict[str, tuple[str, ...]] = {
    "full-qa-pass": (_MAIN_ACTION_MAP[0][2],),
    "full-qa-pass run": (_MAIN_ACTION_MAP[0][2],),
    "delivery-workbook": (_MAIN_ACTION_MAP[4][2],),
    "delivery-workbook trigger": (_MAIN_ACTION_MAP[4][2],),
    "jira": (
        "sgfx-preflight.exe jira status --ticket IDCEVODEV-1009244 --format json",
        _MAIN_ACTION_MAP[8][2],
    ),
    "jira post-comment": (_MAIN_ACTION_MAP[8][2],),
    "jira status": ("sgfx-preflight.exe jira status --ticket IDCEVODEV-1009244 --format json",),
    "jira register": (r"sgfx-preflight.exe jira register --jira-url https://jira.cc.bmwgroup.net --pat-file C:\secure\jira-pat.txt --format json",),
    "jira update-issue": ('sgfx-preflight.exe jira update-issue --ticket IDCEVODEV-1009239 --fields "{""fields"":{""labels"":[""sgfx""]}}" --format json',),
    "jira attach-file": (r"sgfx-preflight.exe jira attach-file --ticket IDCEVODEV-1009239 --file out\review.md --format json",),
    "screenshot-review-viewer": (_MAIN_ACTION_MAP[3][2],),
    "screenshot-review-viewer build": (_MAIN_ACTION_MAP[3][2],),
    "dashboard": (_MAIN_ACTION_MAP[1][2], r"sgfx-preflight.exe dashboard run --workspace C:\repositories\trunk --ui-mode grafiks"),
    "dashboard run": (_MAIN_ACTION_MAP[1][2],),
    "desktop-state": (r"sgfx-preflight.exe desktop-state overview --profile-id G65 --workspace C:\repositories\trunk --json",),
    "desktop-state overview": (r"sgfx-preflight.exe desktop-state overview --profile-id G65 --workspace C:\repositories\trunk --json",),
    "quality-hero-report": (_MAIN_ACTION_MAP[7][2],),
    "quality-hero-report generate": (_MAIN_ACTION_MAP[7][2],),
    "bmw-pipeline-diagnostics": (
        r"sgfx-preflight.exe bmw-pipeline-diagnostics missing-actuals --profile F70 --workspace C:\repositories\trunk --format json",
    ),
    "bmw-pipeline-diagnostics missing-actuals": (
        r"sgfx-preflight.exe bmw-pipeline-diagnostics missing-actuals --profile F70 --workspace C:\repositories\trunk --format json",
    ),
    "template": (_MAIN_ACTION_MAP[19][2],),
    "template save": ('sgfx-preflight.exe template save f70-pass --command full-qa-pass --args "run --profile F70 --workspace C:\\repositories\\trunk" --json',),
    "template run": ("sgfx-preflight.exe template run f70-pass",),
    "template list": (_MAIN_ACTION_MAP[19][2],),
    "template show": ("sgfx-preflight.exe template show f70-pass --json",),
    "template delete": ("sgfx-preflight.exe template delete f70-pass --json",),
    "manual-review": (_MAIN_ACTION_MAP[14][2],),
    "manual-review session": (r"sgfx-preflight.exe manual-review session --profile G65 --ticket IDCEVODEV-1009239 --workspace C:\repositories\trunk --format json",),
    "manual-review assist": (_MAIN_ACTION_MAP[14][2],),
    "manual-review auto-checks": (r"sgfx-preflight.exe manual-review auto-checks --profile G65 --workspace C:\repositories\trunk --format markdown",),
    "manual-review templates": ("sgfx-preflight.exe manual-review templates --json",),
    "manual-review record-step": (r"sgfx-preflight.exe manual-review record-step out\session.json --step blender_visual_check --verdict incomplete --note ""Needs reviewer follow-up."" --json",),
    "manual-review summary": (r"sgfx-preflight.exe manual-review summary out\session.json --format markdown",),
    "manual-review open-raco": (r"sgfx-preflight.exe manual-review open-raco out\session.json --step blender_visual_check --json",),
    "manual-review open-blender": (r"sgfx-preflight.exe manual-review open-blender out\session.json --step blender_visual_check --json",),
    "desktop-notification": (_MAIN_ACTION_MAP[21][2],),
    "desktop-notification send": (_MAIN_ACTION_MAP[21][2],),
}


def _main_help_epilog() -> str:
    lines = [
        "Daily-use action map (frequency ordered):",
    ]
    for command, description, example in _MAIN_ACTION_MAP:
        lines.append(f"  {command:<26} {description}")
        lines.append(f"    example: {example}")
    lines.append("")
    lines.append("Use 'sgfx-preflight.exe <action> --help' for flags and command-specific examples.")
    return "\n".join(lines)


def _command_path_from_prog(prog: str) -> str:
    parts = prog.split()
    if parts and parts[0] in {"sg-preflight", "sgfx-preflight.exe"}:
        parts = parts[1:]
    return " ".join(parts)


def _default_example_for(prog: str) -> str:
    path = _command_path_from_prog(prog)
    return f"sgfx-preflight.exe {path} --help".strip()


def _examples_epilog(parser: argparse.ArgumentParser) -> str:
    path = _command_path_from_prog(parser.prog)
    examples = _COMMAND_EXAMPLES.get(path, (None,))
    lines = ["Examples:"]
    for example in examples:
        lines.append(f"  {example or _default_example_for(parser.prog)}")
    return "\n".join(lines)


def _subparser_actions(parser: argparse.ArgumentParser) -> list[argparse._SubParsersAction]:  # type: ignore[attr-defined]
    return [action for action in parser._actions if isinstance(action, argparse._SubParsersAction)]


def _install_cli_discoverability(parser: argparse.ArgumentParser) -> None:
    parser.description = (
        "SGFX QA Preflight local command line. Commands read local evidence by default; Jira and SVN writes stay gated."
        f"\n\n{_main_help_epilog()}"
    )
    parser.epilog = None
    for action in _subparser_actions(parser):
        if action.dest == "command":
            action._choices_actions = []
    pending = [parser]
    while pending:
        current = pending.pop()
        for action in _subparser_actions(current):
            for child in action.choices.values():
                if child.epilog is None:
                    child.epilog = _examples_epilog(child)
                pending.append(child)


def _git_commit_short() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except Exception:
        return "unknown"
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else "unknown"


def _build_stamp() -> str:
    if _is_frozen_exe():
        try:
            timestamp = Path(sys.executable).stat().st_mtime
        except OSError:
            return "unknown"
        return datetime.fromtimestamp(timestamp, timezone.utc).replace(microsecond=0).isoformat()
    return "source"


def _version_text() -> str:
    return f"sg-preflight {__version__}; commit {_git_commit_short()}; build {_build_stamp()}; python {sys.version.split()[0]}"


def _default_prog() -> str:
    if _is_frozen_exe():
        return Path(sys.executable).name
    return "sg-preflight"


def _console_delivery_readiness(payload: dict[str, object]) -> None:
    from sg_preflight.cli.delivery import _console_delivery_readiness as render

    render(payload)


def _console_disabled_tests(payload: dict[str, object]) -> None:
    counts = payload.get("counts", {})
    if not isinstance(counts, dict):
        counts = {}
    baseline = payload.get("baseline", {})
    if not isinstance(baseline, dict):
        baseline = {}
    print("Disabled-Test Coverage")
    print(f"Source: {payload.get('repo_root', '')}")
    print(f"State: {payload.get('source_state', '')}")
    print(
        "Summary -> "
        f"total: {counts.get('total', 0)} | "
        f"configured: {counts.get('configured', 0)} | "
        f"no config: {counts.get('no_config', 0)} | "
        f"disabled calls: {counts.get('disabled_call_total', 0)} | "
        f"added calls: {counts.get('added_call_total', 0)}"
    )
    print(
        "Review flags -> "
        f"duplicates: {counts.get('duplicate_entry_count', 0)} | "
        f"{CAUTIOUS_BASELINE_LABEL}: {counts.get('baseline_review_entry_count', 0)}"
    )
    print(f"Baseline evidence: {baseline.get('state', '')} ({baseline.get('test_count', 0)} names)")
    print(str(payload.get("manual_review_banner", "")))
    artifacts = payload.get("artifacts")
    if isinstance(artifacts, dict):
        if artifacts.get("json_path"):
            print(f"JSON: {artifacts['json_path']}")
        if artifacts.get("markdown_path"):
            print(f"Markdown: {artifacts['markdown_path']}")
    print("-" * 80)
    entries = payload.get("entries", [])
    if not isinstance(entries, list) or not entries:
        print("No car test-config rows found.")
        return
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        flags = []
        duplicates = entry.get("duplicate_disabled_tests", [])
        baseline_review = entry.get("baseline_review_disabled_tests", [])
        if isinstance(duplicates, list) and duplicates:
            flags.append("duplicates: " + ", ".join(str(name) for name in duplicates))
        if isinstance(baseline_review, list) and baseline_review:
            flags.append(CAUTIOUS_BASELINE_LABEL + ": " + ", ".join(str(name) for name in baseline_review))
        detail = "; ".join(flags) if flags else "no review flags"
        print(
            _console_safe(
                f"- {entry.get('source_root')}/{entry.get('brand')}/{entry.get('model_id')}: "
                f"{entry.get('config_status')} | off {entry.get('disabled_count', 0)} | "
                f"added {entry.get('added_count', 0)} | {detail}"
            )
        )


def _console_api_version_coverage(payload: dict[str, object]) -> None:
    counts = payload.get("counts", {})
    if not isinstance(counts, dict):
        counts = {}
    print("API Version Reference")
    print(f"Source: {payload.get('repo_root', '')}")
    print(f"State: {payload.get('source_state', '')}")
    print(
        "Summary -> "
        f"shared brands: {counts.get('shared_brand_ready', 0)}/{counts.get('shared_brand_total', 0)} | "
        f"HMI rows: {counts.get('interface_entry_total', 0)} | "
        f"impact hints: {counts.get('impact_review_car_count', 0)} car(s)"
    )
    print(str(payload.get("manual_review_banner", "")))
    print(f"Impact label: {payload.get('impact_review_label', IMPACT_REVIEW_LABEL)}")
    print(f"Catalog: {payload.get('catalog_state', '')} ({payload.get('catalog_path', '')})")
    artifacts = payload.get("artifacts")
    if isinstance(artifacts, dict):
        if artifacts.get("json_path"):
            print(f"JSON: {artifacts['json_path']}")
        if artifacts.get("markdown_path"):
            print(f"Markdown: {artifacts['markdown_path']}")
    print("-" * 80)
    refs = payload.get("shared_api_references", [])
    if isinstance(refs, list):
        print("Shared API versions (Cars_IDCevo MainInterfaces):")
        for ref in refs:
            if isinstance(ref, dict):
                print(
                    _console_safe(
                        f"- {ref.get('brand', '')}: API [{ref.get('current_version', '')}] "
                        f"{ref.get('current_date', '')} ({ref.get('state', '')})"
                    )
                )
    interface_counts = counts.get("interface_family_counts", {})
    if isinstance(interface_counts, dict):
        print("HMI export-family rows: " + ", ".join(f"{key}={value}" for key, value in interface_counts.items()))
    scans = payload.get("impact_scans", [])
    if isinstance(scans, list):
        print("Cautious impact hints:")
        for scan in scans:
            if not isinstance(scan, dict):
                continue
            change = scan.get("change", {})
            if not isinstance(change, dict):
                change = {}
            target = f" -> {change.get('new_name')}" if change.get("new_name") else ""
            print(
                _console_safe(
                    f"- API {change.get('api_version', '')} {change.get('change_type', '')}: "
                    f"{change.get('old_name', '')}{target}; "
                    f"{scan.get('matched_car_count', 0)} car(s), {scan.get('matched_file_count', 0)} file(s)"
                )
            )


def _console_country_variant_coverage(payload: dict[str, object]) -> None:
    counts = payload.get("counts", {})
    if not isinstance(counts, dict):
        counts = {}
    print("Country-Variant Coverage")
    print(f"Source: {payload.get('repo_root', '')}")
    print(f"State: {payload.get('source_state', '')}")
    print(
        "Summary -> "
        f"country rows: {counts.get('row_total', 0)} | "
        f"cars: {counts.get('car_with_rows_count', 0)} | "
        f"expected: {counts.get('expected_present_count', 0)}/{counts.get('row_total', 0)} | "
        f"review rows: {counts.get('review_row_count', 0)}"
    )
    print(str(payload.get("manual_review_banner", "")))
    print(f"Missing expected label: {payload.get('missing_expected_label', MISSING_EXPECTED_LABEL)}")
    print(f"Mapping label: {payload.get('mapping_review_label', MAPPING_REVIEW_LABEL)}")
    print(f"Runtime label: {payload.get('no_runtime_label', NO_RUNTIME_LABEL)}")
    artifacts = payload.get("artifacts")
    if isinstance(artifacts, dict):
        if artifacts.get("json_path"):
            print(f"JSON: {artifacts['json_path']}")
        if artifacts.get("markdown_path"):
            print(f"Markdown: {artifacts['markdown_path']}")
    print("-" * 80)
    entries = payload.get("entries", [])
    if isinstance(entries, list):
        for entry in entries[:18]:
            if not isinstance(entry, dict):
                continue
            flags = entry.get("review_flags", [])
            flags_text = ""
            if isinstance(flags, list) and flags:
                flags_text = "; " + ", ".join(str(flag) for flag in flags[:3])
            print(
                _console_safe(
                    f"- {entry.get('relative_path', '')}: {entry.get('test_name', '')} "
                    f"ID {entry.get('country_variant_id', '')}; "
                    f"expected={'yes' if entry.get('expected_present') else 'no'} "
                    f"actual={'yes' if entry.get('actual_present') else 'no'} "
                    f"diff={'yes' if entry.get('diff_present') else 'no'}"
                    f"{flags_text}"
                )
            )
        if len(entries) > 18:
            print(f"... {len(entries) - 18} more row(s)")
    expectations = payload.get("expectations", [])
    if isinstance(expectations, list) and expectations:
        print("Process expectations:")
        for expectation in expectations:
            if not isinstance(expectation, dict):
                continue
            print(
                _console_safe(
                    f"- {expectation.get('car', '')}: expected "
                    f"{', '.join(str(item) for item in expectation.get('expected_variants', []))}; "
                    f"observed rows {', '.join(str(item) for item in expectation.get('observed_rows', [])) or 'none'}"
                )
            )


def _console_export_size_trend(payload: dict[str, object]) -> None:
    counts = payload.get("counts", {})
    if not isinstance(counts, dict):
        counts = {}
    print("Export Size Trend")
    print(f"Source: {payload.get('repo_root', '')}")
    print(f"State: {payload.get('source_state', '')}")
    print(
        "Summary -> "
        f"workbooks: {counts.get('workbook_count', 0)} | "
        f"profiles: {counts.get('profile_count', 0)} | "
        f"trend changes: {counts.get('trend_change_count', 0)} | "
        f"review changes: {counts.get('review_change_count', 0)}"
    )
    print(str(payload.get("manual_review_banner", "")))
    print(f"Review label: {payload.get('significant_change_label', SIGNIFICANT_CHANGE_LABEL)}")
    print(f"Unreadable label: {payload.get('unreadable_layout_label', UNREADABLE_LAYOUT_LABEL)}")
    artifacts = payload.get("artifacts")
    if isinstance(artifacts, dict):
        if artifacts.get("json_path"):
            print(f"JSON: {artifacts['json_path']}")
        if artifacts.get("markdown_path"):
            print(f"Markdown: {artifacts['markdown_path']}")
    print("-" * 80)
    changes = payload.get("trend_changes", [])
    if isinstance(changes, list):
        for change in changes[:18]:
            if not isinstance(change, dict):
                continue
            flags = change.get("review_flags", [])
            flags_text = ""
            if isinstance(flags, list) and flags:
                flags_text = "; " + ", ".join(str(flag) for flag in flags[:3])
            print(
                _console_safe(
                    f"- {change.get('profile_id', '')}: "
                    f"{Path(str(change.get('previous_workbook', ''))).name} -> "
                    f"{Path(str(change.get('current_workbook', ''))).name}; "
                    f"delta {float(change.get('delta_total', 0) or 0):.2f} "
                    f"({float(change.get('delta_percent', 0) or 0):.2f}%)"
                    f"{flags_text}"
                )
            )
        if len(changes) > 18:
            print(f"... {len(changes) - 18} more change row(s)")


def build_parser() -> argparse.ArgumentParser:
    parser = _SgfxArgumentParser(prog=_default_prog())
    parser.add_argument("--version", action=_VersionAction, help="Show version and build metadata")
    sub = parser.add_subparsers(dest="command", required=True, metavar="<action>")

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
    _add_render_options(profile_list, formats=("text", "json"))

    action_list = sub.add_parser("list-actions", help="List one-click SG QA actions")
    action_list.add_argument("--json", action="store_true", help="Print action registry as JSON")
    _add_render_options(action_list, formats=("text", "json"))

    checker_list = sub.add_parser("list-checkers", help="List SG checker coverage and readiness")
    checker_list.add_argument("--json", action="store_true", help="Print checker coverage as JSON")
    _add_render_options(checker_list, formats=("text", "json"))

    full_qa_pass = sub.add_parser(
        "full-qa-pass",
        help="Run the local full QA pass sequence for one car without posting results",
    )
    full_qa_pass_sub = full_qa_pass.add_subparsers(dest="full_qa_pass_command", required=True)
    full_qa_pass_run = full_qa_pass_sub.add_parser("run", help="Read the full QA pass sequence for one profile")
    full_qa_pass_run.add_argument("--workspace", help="Workspace root override")
    full_qa_pass_run.add_argument("--bmw-root", help="Explicit digital-3d-car-models checkout path")
    full_qa_pass_run.add_argument("--profile", required=True, help="Profile id such as G70")
    full_qa_pass_run.add_argument("--comparison-profile", default="G65", help="Comparison profile id such as G65")
    full_qa_pass_run.add_argument(
        "--automatic-mode",
        dest="trusted_tool_mode",
        action="store_true",
        default=True,
        help="Run local tool actions automatically when available while preserving Jira REST and SVN gates",
    )
    full_qa_pass_run.add_argument(
        "--manual-mode",
        dest="trusted_tool_mode",
        action="store_false",
        help="Require operator confirmation before each local tool action",
    )
    full_qa_pass_run.add_argument(
        "--trusted-tool-mode",
        dest="trusted_tool_mode",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    full_qa_pass_run.add_argument(
        "--no-halt",
        action="store_true",
        help="Continue read-only steps after flagged issues instead of skipping later steps",
    )
    full_qa_pass_run.add_argument("--json", action="store_true", help="Print the pass as JSON")
    full_qa_pass_run.add_argument("--markdown", action="store_true", help="Print the pass as Markdown")
    _add_render_options(full_qa_pass_run)

    delivery_checklist = sub.add_parser(
        "delivery-checklist",
        help="Read the operator-local delivery checklist workbook without writing to it",
    )
    delivery_checklist_sub = delivery_checklist.add_subparsers(dest="delivery_checklist_command", required=True)
    delivery_checklist_read = delivery_checklist_sub.add_parser("read", help="Read delivery checklist evidence for one profile")
    delivery_checklist_read.add_argument("--workspace", help="Workspace root override")
    delivery_checklist_read.add_argument("--profile", required=True, help="Profile id such as <profile>")
    delivery_checklist_read.add_argument("--brand", default="BMW", help="Workbook brand label such as BMW or Mini")
    delivery_checklist_read.add_argument("--workbook", help="Explicit delivery checklist workbook path")
    delivery_checklist_read.add_argument(
        "--bmw-root",
        help="Explicit digital-3d-car-models checkout path (enables multi-location finder + auto-generation)",
    )
    delivery_checklist_read.add_argument(
        "--no-auto-generate",
        dest="enable_auto_generate",
        action="store_false",
        default=True,
        help="Disable the raw-data to Format A xlsx auto-generation fallback",
    )
    delivery_checklist_read.add_argument("--json", action="store_true", help="Print delivery checklist payload as JSON")
    delivery_checklist_read.add_argument("--markdown", action="store_true", help="Print delivery checklist payload as Markdown")
    _add_render_options(delivery_checklist_read)

    delivery_workbook = sub.add_parser(
        "delivery-workbook",
        help="Inspect the confirmation-gated delivery workbook generation trigger",
    )
    delivery_workbook_sub = delivery_workbook.add_subparsers(dest="delivery_workbook_command", required=True)
    delivery_workbook_trigger = delivery_workbook_sub.add_parser("trigger", help="Read generation trigger status")
    delivery_workbook_trigger.add_argument("--workspace", help="Workspace root override")
    delivery_workbook_trigger.add_argument("--bmw-root", help="Explicit digital-3d-car-models checkout path")
    delivery_workbook_trigger.add_argument("--profile", required=True, help="Profile id such as G65")
    delivery_workbook_trigger.add_argument(
        "--automatic-mode",
        dest="trusted_tool_mode",
        action="store_true",
        help="Report Automatic mode without starting generation",
    )
    delivery_workbook_trigger.add_argument(
        "--manual-mode",
        dest="trusted_tool_mode",
        action="store_false",
        help="Report Manual mode without starting generation",
    )
    delivery_workbook_trigger.add_argument(
        "--trusted-tool-mode",
        dest="trusted_tool_mode",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    delivery_workbook_trigger.add_argument("--json", action="store_true", help="Print trigger as JSON")
    delivery_workbook_trigger.add_argument("--markdown", action="store_true", help="Print trigger as Markdown")
    _add_render_options(delivery_workbook_trigger)

    delivery_workbook_find = delivery_workbook_sub.add_parser(
        "find",
        help="Discover the size-analysis workbook across the documented Format A/B locations",
        description=(
            "Walks the eight documented size-analysis workbook locations and prints the "
            "selected (newest mtime) workbook + all candidates + the search paths. If no "
            "workbook is found AND raw export-size data is available locally, auto-"
            "generates a Format A workbook to ~/sgfx_outputs/<profile>/delivery-workbook/."
        ),
    )
    delivery_workbook_find.add_argument("--profile", required=True, help="Profile id such as G70")
    delivery_workbook_find.add_argument("--workspace", help="SVN trunk workspace root override")
    delivery_workbook_find.add_argument("--bmw-root", help="Explicit digital-3d-car-models checkout path")
    delivery_workbook_find.add_argument(
        "--auto-generate",
        action="store_true",
        help="When no workbook is found, attempt to auto-generate from raw BMW export-size data",
    )
    delivery_workbook_find.add_argument("--json", action="store_true", help="Print the resolution as JSON")
    _add_render_options(delivery_workbook_find, formats=("text", "json"))

    export_size = sub.add_parser(
        "export-size-analysis",
        help="Read the operator-local export-size analysis workbook without writing to it",
    )
    export_size_sub = export_size.add_subparsers(dest="export_size_analysis_command", required=True)
    export_size_read = export_size_sub.add_parser("read", help="Read export-size analysis evidence for one profile")
    export_size_read.add_argument("--workspace", help="Workspace root override")
    export_size_read.add_argument("--profile", required=True, help="Profile id such as <profile>")
    export_size_read.add_argument("--workbook", help="Explicit export-size analysis workbook path")
    export_size_date = export_size_read.add_mutually_exclusive_group()
    export_size_date.add_argument("--date", help="Workbook date as YYYYMMDD (for example: 20251002)")
    export_size_date.add_argument("--latest", action="store_true", help="Pick the newest matching workbook by date")
    export_size_read.add_argument("--json", action="store_true", help="Print export-size analysis payload as JSON")
    export_size_read.add_argument("--markdown", action="store_true", help="Print export-size analysis payload as Markdown")
    _add_render_options(export_size_read)

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
    screenshot_state_read.add_argument("--profile", required=True, help="Profile id such as <profile>")
    screenshot_state_read.add_argument("--json", action="store_true", help="Print screenshot test state as JSON")
    screenshot_state_read.add_argument("--markdown", action="store_true", help="Print screenshot test state as Markdown")
    _add_render_options(screenshot_state_read)

    bmw_pipeline_diagnostics = sub.add_parser(
        "bmw-pipeline-diagnostics",
        help="Inspect BMW pipeline missing-actual diagnostics with confirmation-gated refresh actions",
    )
    bmw_pipeline_diagnostics_sub = bmw_pipeline_diagnostics.add_subparsers(
        dest="bmw_pipeline_diagnostics_command",
        required=True,
    )
    missing_actuals = bmw_pipeline_diagnostics_sub.add_parser(
        "missing-actuals",
        help="Build the missing-actual diagnostic chain for one profile",
    )
    missing_actuals.add_argument("--workspace", help="Workspace root override")
    missing_actuals.add_argument("--bmw-root", help="Explicit digital-3d-car-models checkout path")
    missing_actuals.add_argument("--profile", help="Profile id such as F70")
    missing_actuals.add_argument("--project-root", help="Explicit BMW project root override")
    missing_actuals.add_argument("--expected-root", help="Explicit expected screenshot root")
    missing_actuals.add_argument(
        "--candidate-root",
        action="append",
        default=[],
        help="Explicit actual/candidate screenshot root (repeatable)",
    )
    missing_actuals.add_argument(
        "--diff-root",
        action="append",
        default=[],
        help="Explicit diff screenshot root (repeatable)",
    )
    missing_actuals.add_argument("--output-root", help="Directory to write diagnostic artifacts")
    missing_actuals.add_argument(
        "--auto-confirm-read-refresh",
        action="store_true",
        help="Confirm BMW Git/SVN read-refresh commands if discovered",
    )
    missing_actuals.add_argument(
        "--retry-capture",
        action="store_true",
        help="Retry BMW screenshot capture after diagnostics",
    )
    missing_actuals.add_argument(
        "--auto-confirm-retry-capture",
        action="store_true",
        help="Confirm the screenshot-capture retry action",
    )
    missing_actuals.add_argument("--json", action="store_true", help="Print diagnostic chain as JSON")
    missing_actuals.add_argument("--markdown", action="store_true", help="Print diagnostic chain as Markdown")
    _add_render_options(missing_actuals)

    risk_score = sub.add_parser(
        "risk-score",
        help="Read per-car local risk scoring with delta since latest manual review",
    )
    risk_score_sub = risk_score.add_subparsers(dest="risk_score_command", required=True)
    risk_score_read = risk_score_sub.add_parser("read", help="Read risk score for one profile")
    risk_score_read.add_argument("--workspace", help="Workspace root override")
    risk_score_read.add_argument("--bmw-root", help="Explicit digital-3d-car-models checkout path")
    risk_score_read.add_argument("--profile", required=True, help="Profile id such as <profile>")
    risk_score_read.add_argument("--json", action="store_true", help="Print risk score as JSON")
    risk_score_read.add_argument("--markdown", action="store_true", help="Print risk score as Markdown")
    _add_render_options(risk_score_read)

    cross_car_comparison = sub.add_parser(
        "cross-car-comparison",
        help="Compare two car profiles using the same local risk-score widget",
    )
    cross_car_comparison_sub = cross_car_comparison.add_subparsers(
        dest="cross_car_comparison_command",
        required=True,
    )
    cross_car_snapshot = cross_car_comparison_sub.add_parser(
        "snapshot",
        help="Read a side-by-side profile comparison",
    )
    cross_car_snapshot.add_argument("--workspace", help="Workspace root override")
    cross_car_snapshot.add_argument("--bmw-root", help="Explicit digital-3d-car-models checkout path")
    cross_car_snapshot.add_argument("--left-profile", default="G70", help="Left profile id such as G70")
    cross_car_snapshot.add_argument("--right-profile", default="G65", help="Right profile id such as G65")
    cross_car_snapshot.add_argument("--json", action="store_true", help="Print comparison as JSON")
    cross_car_snapshot.add_argument("--markdown", action="store_true", help="Print comparison as Markdown")
    _add_render_options(cross_car_snapshot)

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
    bmw_git_readiness_read.add_argument("--profile", required=True, help="Profile id such as <profile>")
    bmw_git_readiness_read.add_argument("--json", action="store_true", help="Print BMW Git readiness as JSON")
    bmw_git_readiness_read.add_argument("--markdown", action="store_true", help="Print BMW Git readiness as Markdown")
    _add_render_options(bmw_git_readiness_read)

    qa_hero_readiness = sub.add_parser(
        "qa-hero-readiness",
        help="Read local BMW/MINI QA Hero readiness signals without writing to BMW Git",
    )
    qa_hero_readiness_sub = qa_hero_readiness.add_subparsers(dest="qa_hero_readiness_command", required=True)
    qa_hero_readiness_read = qa_hero_readiness_sub.add_parser(
        "read",
        help="Read QA Hero readiness for one profile",
    )
    qa_hero_readiness_read.add_argument("--workspace", help="Workspace root override")
    qa_hero_readiness_read.add_argument("--bmw-root", help="Explicit digital-3d-car-models checkout path")
    qa_hero_readiness_read.add_argument("--profile", required=True, help="Profile id such as <profile>")
    qa_hero_readiness_read.add_argument("--json", action="store_true", help="Print QA Hero readiness as JSON")
    qa_hero_readiness_read.add_argument("--markdown", action="store_true", help="Print QA Hero readiness as Markdown")
    _add_render_options(qa_hero_readiness_read)

    workflow_list = sub.add_parser("workflow-status", help="List workflow coverage, partial areas, and blockers")
    workflow_list.add_argument("--json", action="store_true", help="Print workflow status as JSON")
    _add_render_options(workflow_list, formats=("text", "json"))

    doctor = sub.add_parser("doctor", help="Run the SGFX setup doctor")
    doctor.add_argument("--workspace", help="Workspace root override")
    doctor.add_argument("--json", action="store_true", help="Print setup doctor report as JSON")

    delivery_readiness = sub.add_parser(
        "delivery-readiness",
        help="Build the read-only delivery readiness board from car CHANGELOG.md files",
    )
    delivery_readiness.add_argument("--workspace", help="Workspace root override")
    delivery_readiness.add_argument("--repo-root", help="SVN trunk root override")
    delivery_readiness.add_argument("--bmw-repo-root", help="BMW digital-3d-car-models root override")
    delivery_readiness.add_argument("--output-root", help="Optional directory to write JSON and markdown evidence")
    delivery_readiness.add_argument("--json", action="store_true", help="Print delivery readiness payload as JSON")

    disabled_tests = sub.add_parser(
        "disabled-tests",
        help="Build the read-only disabled-test inventory from car test_config.lua files",
    )
    disabled_tests.add_argument("--workspace", help="Workspace root override")
    disabled_tests.add_argument("--repo-root", help="SVN trunk root override")
    disabled_tests.add_argument("--bmw-repo-root", help="BMW digital-3d-car-models root override")
    disabled_tests.add_argument("--output-root", help="Optional directory to write JSON and markdown evidence")
    disabled_tests.add_argument("--json", action="store_true", help="Print disabled-test payload as JSON")

    api_version_coverage = sub.add_parser(
        "api-version-coverage",
        help="Build the read-only shared API version reference and cautious impact scan",
    )
    api_version_coverage.add_argument("--workspace", help="Workspace root override")
    api_version_coverage.add_argument("--repo-root", help="SVN trunk root override")
    api_version_coverage.add_argument("--bmw-repo-root", help="BMW digital-3d-car-models root override")
    api_version_coverage.add_argument("--output-root", help="Optional directory to write JSON and markdown evidence")
    api_version_coverage.add_argument("--json", action="store_true", help="Print API version coverage payload as JSON")

    country_variant_coverage = sub.add_parser(
        "country-variant-coverage",
        help="Build the read-only country-variant screenshot evidence matrix",
    )
    country_variant_coverage.add_argument("--workspace", help="Workspace root override")
    country_variant_coverage.add_argument("--repo-root", help="SVN trunk root override")
    country_variant_coverage.add_argument("--bmw-repo-root", help="BMW digital-3d-car-models root override")
    country_variant_coverage.add_argument("--output-root", help="Optional directory to write JSON and markdown evidence")
    country_variant_coverage.add_argument("--json", action="store_true", help="Print country-variant coverage payload as JSON")

    export_size_trend = sub.add_parser(
        "export-size-trend",
        help="Build the read-only export-size workbook trend board",
    )
    export_size_trend.add_argument("--workspace", help="Workspace root override")
    export_size_trend.add_argument("--repo-root", help="SVN trunk root override")
    export_size_trend.add_argument("--output-root", help="Optional directory to write JSON and markdown evidence")
    export_size_trend.add_argument("--json", action="store_true", help="Print export-size trend payload as JSON")

    sub.add_parser(
        "list-workflows",
        help="List JSON-defined SG QA workflows under qa_workflows/",
    ).add_argument("--json", action="store_true", help="Print workflow registry as JSON")

    validate_workflow_p = sub.add_parser(
        "validate-workflow",
        help="Validate one or all workflow JSON files against the sgfx_qa_workflow schema",
    )
    validate_workflow_p.add_argument(
        "id_or_path",
        nargs="?",
        default="",
        help="Workflow id (e.g. idcevo_screenshot_changelog), absolute path, or empty to validate all",
    )
    validate_workflow_p.add_argument("--json", action="store_true", help="Print validation result as JSON")

    run_workflow_p = sub.add_parser(
        "run-workflow",
        help="Run a JSON-defined workflow by id (executes preflight_cli checks; manual_attestation -> pending)",
    )
    run_workflow_p.add_argument("workflow_id", help="Workflow id (matches the 'id' field in qa_workflows/<id>.json)")
    run_workflow_p.add_argument("--profile", default="", help="Optional profile id (G65, G70, ...) substituted into checks")
    run_workflow_p.add_argument("--ticket-id", default="", help="Optional ticket id substituted into checks")
    run_workflow_p.add_argument(
        "--output-root",
        default="",
        help="Override output root (defaults to <workspace>/out/qa_workflows/)",
    )
    run_workflow_p.add_argument("--json", action="store_true", help="Print run summary as JSON")

    profile_summary = sub.add_parser(
        "profile-summary",
        help="Build a self-contained per-profile HTML summary",
        description=(
            "Composes a self-contained dark-theme HTML page summarising one BMW "
            "profile: workbook status, active Jira tickets, recent Full QA Pass "
            "runs, manual-review state, escalation contacts, and Confluence "
            "anchors. Operator-local; no PAT / no personal paths in the output."
        ),
    )
    profile_summary_sub = profile_summary.add_subparsers(dest="profile_summary_command", required=True)
    profile_summary_build = profile_summary_sub.add_parser(
        "build", help="Render a shareable summary HTML for one profile"
    )
    profile_summary_build.add_argument("--profile", required=True, help="Profile id such as F70 or G70")
    profile_summary_build.add_argument("--workspace", required=True, help="SVN trunk workspace root override")
    profile_summary_build.add_argument("--bmw-root", help="Explicit digital-3d-car-models checkout path")
    profile_summary_build.add_argument(
        "--html-output",
        dest="html_output",
        required=True,
        help="Where to write the .html (parent directory auto-created)",
    )
    profile_summary_build.add_argument(
        "--history-limit",
        type=int,
        default=5,
        help="Number of recent Full QA Pass runs to include (default 5)",
    )
    profile_summary_build.add_argument(
        "--note",
        action="append",
        default=[],
        help="Optional operator note to include; pass multiple times for multiple notes",
    )
    profile_summary_build.add_argument(
        "--json",
        action="store_true",
        help="Print the data payload as JSON to stdout in addition to writing the HTML",
    )
    _add_render_options(profile_summary_build, formats=("text", "json"))

    profile_summary_export = profile_summary_sub.add_parser(
        "export",
        help="Bundle per-profile evidence into an operator-shareable zip",
        description=(
            "Bundles summary.html (from build) + screenshot-review/ PNGs + "
            "delivery-workbook/ + activity_log.jsonl (filtered to profile + "
            "last N days) + full_qa_history.json + manifest.json. PAT-shaped "
            "tokens are masked to ****<last4> and personal Windows paths "
            "collapsed to C:\\Users\\<operator>\\… before zip write."
        ),
    )
    profile_summary_export.add_argument("--profile", required=True, help="Profile id such as F70 or G70")
    profile_summary_export.add_argument("--workspace", required=True, help="SVN trunk workspace root override")
    profile_summary_export.add_argument("--bmw-root", help="Explicit digital-3d-car-models checkout path")
    profile_summary_export.add_argument(
        "--zip-output",
        dest="zip_output",
        required=True,
        help="Where to write the .zip (parent directory auto-created)",
    )
    profile_summary_export.add_argument(
        "--history-limit",
        type=int,
        default=10,
        help="Number of recent Full QA Pass runs to include in summary.html (default 10)",
    )
    profile_summary_export.add_argument(
        "--activity-log-window-days",
        type=int,
        default=7,
        help="Filter activity_log entries to the last N days (default 7)",
    )
    profile_summary_export.add_argument("--json", action="store_true", help="Print the export manifest as JSON")
    _add_render_options(profile_summary_export, formats=("text", "json"))

    activity_log = sub.add_parser("activity-log", help="Read or append the operator-local SGFX activity log")
    activity_log_sub = activity_log.add_subparsers(dest="activity_log_command", required=True)
    activity_read = activity_log_sub.add_parser("read", help="Read operator-local activity log entries")
    activity_read.add_argument("--workspace", required=True, help="Workspace root that owns operator_state/activity_log.jsonl")
    activity_read.add_argument("--profile", default="", help="Optional profile filter such as <profile>")
    activity_read.add_argument(
        "--since",
        default="all",
        help=(
            "Date filter: today, yesterday, this-week, all, or a duration like '5 min ago' / '30s' / '1h' / '2 days ago'"
        ),
    )
    activity_read.add_argument("--limit", type=int, default=100, help="Maximum entries to return")
    activity_read.add_argument("--json", action="store_true", help="Print activity log as JSON")
    activity_read.add_argument(
        "--tail",
        action="store_true",
        help="Stream new activity log entries as they are appended (Ctrl-C to stop)",
    )
    activity_read.add_argument(
        "--tail-interval",
        type=float,
        default=0.5,
        help="Polling interval in seconds for --tail mode (default 0.5)",
    )
    _add_render_options(activity_read, formats=("text", "json"))

    live_state = sub.add_parser(
        "live-state",
        help="Print or tail the operator-local SGFX dashboard live state",
        description=(
            "Reads <workspace>/operator_state/live_state.json which SGFX writes "
            "on every dashboard state change (debounced ~250ms). Operator-local; "
            "never crosses external boundaries; sanitized of credentials."
        ),
    )
    live_state.add_argument("--workspace", required=True, help="Workspace root that owns operator_state/live_state.json")
    live_state.add_argument(
        "--tail",
        action="store_true",
        help="Stream live state updates as they happen (Ctrl-C to stop)",
    )
    live_state.add_argument(
        "--tail-interval",
        type=float,
        default=0.25,
        help="Polling interval in seconds for --tail mode (default 0.25)",
    )
    live_state.add_argument("--json", action="store_true", help="Print live state as JSON")
    _add_render_options(live_state, formats=("text", "json"))

    activity_append = activity_log_sub.add_parser("append", help="Append one operator-local activity entry")
    activity_append.add_argument("--workspace", required=True, help="Workspace root that owns operator_state/activity_log.jsonl")
    activity_append.add_argument("--verb", required=True, help="Factual verb such as read, ran, refreshed, or opened")
    activity_append.add_argument("--surface", required=True, help="Surface identifier such as daily-digest")
    activity_append.add_argument("--profile", default="", help="Optional profile id such as <profile>")
    activity_append.add_argument("--outcome", default="ok", help="Outcome: ok, error, empty, or unavailable")
    activity_append.add_argument("--note", default="", help="Short operator-local note")
    activity_append.add_argument("--json", action="store_true", help="Print appended entry as JSON")

    template = sub.add_parser(
        "template",
        help="Manage operator-local saved command configurations",
        description=TEMPLATE_BANNER,
    )
    template_sub = template.add_subparsers(dest="template_command", required=True)
    template_save = template_sub.add_parser("save", help="Save one operator-local command template")
    template_save.add_argument("name", help="Template name")
    template_save.add_argument("--workspace", help="Workspace root override")
    template_save.add_argument("--command", dest="template_cli_command", required=True, help="SGFX CLI command name to save")
    template_save.add_argument("--args", default="", help="Command arguments to save, quoted as one string")
    template_save.add_argument("--description", default="", help="Short operator note for this template")
    template_save.add_argument("--replace", action="store_true", help="Replace an existing template with the same name")
    template_save.add_argument("--json", action="store_true", help="Print saved template metadata as JSON")

    template_run = template_sub.add_parser("run", help="Run one saved operator-local command template")
    template_run.add_argument("name", help="Template name")
    template_run.add_argument("--workspace", help="Workspace root override")
    template_run.add_argument("--args-override", default="", help="Override the saved argument string for this run")

    template_list = template_sub.add_parser("list", help="List saved operator-local command templates")
    template_list.add_argument("--workspace", help="Workspace root override")
    template_list.add_argument("--json", action="store_true", help="Print template list as JSON")

    template_show = template_sub.add_parser("show", help="Show one saved operator-local command template")
    template_show.add_argument("name", help="Template name")
    template_show.add_argument("--workspace", help="Workspace root override")
    template_show.add_argument("--json", action="store_true", help="Print template metadata as JSON")

    template_delete = template_sub.add_parser("delete", help="Delete one operator-local command template")
    template_delete.add_argument("name", help="Template name")
    template_delete.add_argument("--workspace", help="Workspace root override")
    template_delete.add_argument("--json", action="store_true", help="Print deleted template metadata as JSON")

    jira = sub.add_parser(
        "jira",
        help="Prepare or post Jira comments through confirmation-gated REST",
        description=JIRA_POSTING_BANNER,
    )
    jira_sub = jira.add_subparsers(dest="jira_command", required=True)
    jira_register = jira_sub.add_parser("register", help="Store operator-local Jira URL and PAT")
    jira_register.add_argument("--jira-url", default="", help="Jira base URL")
    jira_register.add_argument("--pat-file", help="Read the PAT from this local text file")
    jira_register.add_argument("--state-dir", help="Credential directory override; defaults to the operator profile")
    jira_register.add_argument("--force", action="store_true", help="Replace an existing credential file")
    _add_render_options(jira_register, formats=("text", "json", "markdown"))

    jira_status_parser = jira_sub.add_parser("status", help="Verify operator-local Jira credentials and connection")
    jira_status_parser.add_argument("--ticket", default="", help="Optional Jira ticket key to verify with a GET")
    jira_status_parser.add_argument("--api-version", choices=("2", "3"), default="2", help="Jira REST API version")
    _add_render_options(jira_status_parser, formats=("text", "json", "markdown"))

    jira_post_comment = jira_sub.add_parser("post-comment", help="Preview or post one Jira comment")
    jira_post_comment.add_argument("--ticket", required=True, help="Jira ticket key such as IDCEVODEV-1009244")
    jira_post_source = jira_post_comment.add_mutually_exclusive_group(required=True)
    jira_post_source.add_argument("--body", default="", help="Inline Jira comment body")
    jira_post_source.add_argument("--body-file", help="Read Jira comment body from this UTF-8 text file")
    jira_post_comment.add_argument("--api-version", choices=("2", "3"), default="2", help="Jira REST API version")
    jira_post_comment.add_argument("--auto-confirm", action="store_true", help="Post after the preview contract has been satisfied")
    _add_render_options(jira_post_comment, formats=("text", "json", "markdown"))

    jira_update_issue = jira_sub.add_parser("update-issue", help="Preview or update Jira issue fields")
    jira_update_issue.add_argument("--ticket", required=True, help="Jira ticket key such as IDCEVODEV-1009244")
    jira_update_issue.add_argument("--fields", required=True, help="JSON object of issue fields or {'fields': ...}")
    jira_update_issue.add_argument("--api-version", choices=("2", "3"), default="2", help="Jira REST API version")
    jira_update_issue.add_argument("--auto-confirm", action="store_true", help="Update after the preview contract has been satisfied")
    _add_render_options(jira_update_issue, formats=("text", "json", "markdown"))

    jira_attach_file = jira_sub.add_parser("attach-file", help="Preview or attach one file to Jira")
    jira_attach_file.add_argument("--ticket", required=True, help="Jira ticket key such as IDCEVODEV-1009244")
    jira_attach_file.add_argument("--file", required=True, help="Local file to attach")
    jira_attach_file.add_argument("--api-version", choices=("2", "3"), default="2", help="Jira REST API version")
    jira_attach_file.add_argument("--auto-confirm", action="store_true", help="Attach after the preview contract has been satisfied")
    _add_render_options(jira_attach_file, formats=("text", "json", "markdown"))

    jira_post = jira_sub.add_parser("post", help="Dry-run or confirmation-gated Jira comment post")
    jira_post.add_argument("--workspace", help="Workspace root override for local wording files")
    jira_post.add_argument("--ticket", required=True, help="Jira ticket key such as IDCEVODEV-977874")
    jira_source = jira_post.add_mutually_exclusive_group(required=True)
    jira_source.add_argument("--body", default="", help="Inline Jira comment body")
    jira_source.add_argument("--body-file", help="Read Jira comment body from this UTF-8 text file")
    jira_source.add_argument("--section", help="Read a numbered Markdown section from the wording source")
    jira_post.add_argument("--wording-file", help="Markdown wording source when --section is used")
    jira_post.add_argument("--base-url", help=f"Jira base URL override; otherwise uses {DEFAULT_BASE_URL_ENV}")
    jira_post.add_argument("--base-url-env", default=DEFAULT_BASE_URL_ENV, help="Environment variable containing the Jira base URL")
    jira_post.add_argument("--token-env", default=DEFAULT_TOKEN_ENV, help="Environment variable containing the Jira PAT")
    jira_post.add_argument("--api-version", choices=("2", "3"), default="2", help="Jira REST API version")
    jira_post.add_argument("--dry-run", action="store_true", help="Preview only; this is the default behavior")
    jira_post.add_argument("--confirm", action="store_true", help="Actually post the comment; requires base URL and PAT")
    jira_post.add_argument("--json", action="store_true", help="Print Jira post payload as JSON")
    _add_render_options(jira_post)

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
    screenshot_triage.add_argument(
        "--cosmetic-max-changed-ratio",
        type=float,
        default=DEFAULT_VISUAL_DIFF_THRESHOLDS.cosmetic_max_changed_ratio,
        help="Changed-pixel ratio at or below this value is treated as cosmetic in the visual label",
    )
    screenshot_triage.add_argument(
        "--cosmetic-max-mean-diff",
        type=float,
        default=DEFAULT_VISUAL_DIFF_THRESHOLDS.cosmetic_max_mean_abs_diff,
        help="Mean absolute diff at or below this value is treated as cosmetic in the visual label",
    )
    screenshot_triage.add_argument(
        "--structural-min-changed-ratio",
        type=float,
        default=DEFAULT_VISUAL_DIFF_THRESHOLDS.structural_min_changed_ratio,
        help="Changed-pixel ratio at or above this value is treated as structural in the visual label",
    )
    screenshot_triage.add_argument(
        "--structural-min-mean-diff",
        type=float,
        default=DEFAULT_VISUAL_DIFF_THRESHOLDS.structural_min_mean_abs_diff,
        help="Mean absolute diff at or above this value is treated as structural in the visual label",
    )
    screenshot_triage.add_argument(
        "--structural-min-review-score",
        type=float,
        default=DEFAULT_VISUAL_DIFF_THRESHOLDS.structural_min_review_score,
        help="Review score at or above this value is treated as structural in the visual label",
    )
    screenshot_triage.add_argument(
        "--external-vision",
        action="store_true",
        help="Record an explicit external-vision opt-in request; this local build does not call an external provider",
    )
    screenshot_triage.add_argument("--json", action="store_true", help="Print triage payload as JSON")

    screenshot_review_viewer = sub.add_parser(
        "screenshot-review-viewer",
        help="Build a side-by-side expected/actual/diff screenshot review viewer",
    )
    screenshot_review_viewer_sub = screenshot_review_viewer.add_subparsers(
        dest="screenshot_review_viewer_command",
        required=True,
    )
    screenshot_review_viewer_build = screenshot_review_viewer_sub.add_parser(
        "build",
        help="Materialize the local screenshot review viewer",
    )
    screenshot_review_viewer_build.add_argument("--profile", help="Canonical profile id such as G70")
    screenshot_review_viewer_build.add_argument("--project-root", help="Explicit project root override")
    screenshot_review_viewer_build.add_argument("--workspace", help="Workspace root override")
    screenshot_review_viewer_build.add_argument("--bmw-root", help="Explicit digital-3d-car-models checkout path")
    screenshot_review_viewer_build.add_argument("--expected-root", help="Explicit expected screenshot root")
    screenshot_review_viewer_build.add_argument(
        "--candidate-root",
        action="append",
        default=[],
        help="Explicit actual/candidate screenshot root (repeatable)",
    )
    screenshot_review_viewer_build.add_argument(
        "--diff-root",
        action="append",
        default=[],
        help="Explicit diff screenshot root (repeatable)",
    )
    screenshot_review_viewer_build.add_argument("--output-root", help="Directory to write viewer artifacts")
    screenshot_review_viewer_build.add_argument("--max-items", type=int, default=80, help="Maximum viewer rows")
    screenshot_review_viewer_build.add_argument("--json", action="store_true", help="Print viewer payload as JSON")

    quality_hero_report = sub.add_parser(
        "quality-hero-report",
        help="Generate Markdown and HTML Quality-Hero review reports from local evidence",
    )
    quality_hero_report_sub = quality_hero_report.add_subparsers(dest="quality_hero_report_command", required=True)
    quality_hero_report_generate = quality_hero_report_sub.add_parser(
        "generate",
        help="Build the review report bundle",
    )
    quality_hero_report_generate.add_argument("--profile", required=True, help="Profile id such as G70")
    quality_hero_report_generate.add_argument("--workspace", help="Workspace root for evidence reads")
    quality_hero_report_generate.add_argument("--bmw-root", help="Explicit digital-3d-car-models checkout path")
    quality_hero_report_generate.add_argument("--ticket", default="", help="Optional Jira ticket id for report context")
    quality_hero_report_generate.add_argument("--screenshot-viewer-json", help="Reuse an existing viewer JSON payload")
    quality_hero_report_generate.add_argument("--output-root", help="Directory to write report artifacts")
    quality_hero_report_generate.add_argument("--thumbnail-limit", type=int, default=4, help="Embedded screenshot thumbnail limit")
    quality_hero_report_generate.add_argument("--attach-ticket", default="", help="Optional Jira ticket id to attach the Markdown report")
    quality_hero_report_generate.add_argument("--auto-confirm", action="store_true", help="Attach the report after confirmation")
    _add_render_options(quality_hero_report_generate, formats=("text", "json", "markdown", "html"))

    desktop_notification = sub.add_parser(
        "desktop-notification",
        help="Record or show a desktop notification for completed local work",
    )
    desktop_notification_sub = desktop_notification.add_subparsers(dest="desktop_notification_command", required=True)
    desktop_notification_send = desktop_notification_sub.add_parser("send", help="Show one desktop notification")
    desktop_notification_send.add_argument("--workspace", help="Workspace root for the notification record")
    desktop_notification_send.add_argument("--title", required=True, help="Notification title")
    desktop_notification_send.add_argument("--message", required=True, help="Notification message")
    desktop_notification_send.add_argument("--action-id", default="", help="Related local action id")
    desktop_notification_send.add_argument("--profile", default="", help="Related profile id")
    desktop_notification_send.add_argument("--evidence-path", default="", help="Optional local evidence path")
    desktop_notification_send.add_argument("--dry-run", action="store_true", help="Record without showing a desktop message")
    _add_render_options(desktop_notification_send, formats=("text", "json"))

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
    _add_render_options(daily_digest_latest)

    team_digest_board = sub.add_parser(
        "team-digest-board",
        help="Build a local Team Daily Digest board snapshot",
    )
    team_digest_board_sub = team_digest_board.add_subparsers(dest="team_digest_board_command", required=True)
    team_digest_board_snapshot = team_digest_board_sub.add_parser("snapshot", help="Read the team digest board")
    team_digest_board_snapshot.add_argument("--workspace", help="Workspace root override")
    team_digest_board_snapshot.add_argument("--bmw-root", help="Explicit digital-3d-car-models checkout path")
    team_digest_board_snapshot.add_argument("--ticket-id", default="", help="Optional ticket id filter")
    team_digest_board_snapshot.add_argument(
        "--profile",
        action="append",
        default=[],
        help="Profile id to include on the board, repeatable (defaults to G70,G65)",
    )
    team_digest_board_snapshot.add_argument("--json", action="store_true", help="Print board as JSON")
    team_digest_board_snapshot.add_argument("--markdown", action="store_true", help="Print board as Markdown")
    _add_render_options(team_digest_board_snapshot)

    operator_handoff = sub.add_parser(
        "operator-handoff",
        help="Record or read an operator-local shift handoff",
    )
    operator_handoff_sub = operator_handoff.add_subparsers(dest="operator_handoff_command", required=True)
    operator_handoff_latest = operator_handoff_sub.add_parser("latest", help="Read the latest local handoff")
    operator_handoff_latest.add_argument("--workspace", help="Workspace root override")
    operator_handoff_latest.add_argument("--profile", required=True, help="Profile id such as G65")
    operator_handoff_latest.add_argument("--json", action="store_true", help="Print handoff as JSON")
    operator_handoff_latest.add_argument("--markdown", action="store_true", help="Print handoff as Markdown")
    _add_render_options(operator_handoff_latest)

    operator_handoff_record = operator_handoff_sub.add_parser("record", help="Record a local stopping point")
    operator_handoff_record.add_argument("--workspace", help="Workspace root override")
    operator_handoff_record.add_argument("--profile", required=True, help="Profile id such as G65")
    operator_handoff_record.add_argument("--ticket", default="", help="Optional ticket id")
    operator_handoff_record.add_argument("--stopping-point", required=True, help="Where the operator stopped")
    operator_handoff_record.add_argument("--next-step", default="", help="Suggested next local step")
    operator_handoff_record.add_argument("--note", default="", help="Optional operator-local note")
    operator_handoff_record.add_argument("--json", action="store_true", help="Print recorded handoff as JSON")
    operator_handoff_record.add_argument("--markdown", action="store_true", help="Print recorded handoff as Markdown")
    _add_render_options(operator_handoff_record)

    onboarding_guide = sub.add_parser(
        "onboarding-guide",
        help="Read the local onboarding guide for one profile",
    )
    onboarding_guide_sub = onboarding_guide.add_subparsers(dest="onboarding_guide_command", required=True)
    onboarding_guide_read = onboarding_guide_sub.add_parser("read", help="Read onboarding guidance")
    onboarding_guide_read.add_argument("--workspace", help="Workspace root override")
    onboarding_guide_read.add_argument("--bmw-root", help="Explicit digital-3d-car-models checkout path")
    onboarding_guide_read.add_argument("--profile", required=True, help="Profile id such as G65")
    onboarding_guide_read.add_argument("--json", action="store_true", help="Print guide as JSON")
    onboarding_guide_read.add_argument("--markdown", action="store_true", help="Print guide as Markdown")
    _add_render_options(onboarding_guide_read)

    manual_review = sub.add_parser(
        "manual-review",
        help="Create and update operator-recorded RaCo / Blender manual-review sessions",
    )
    manual_review_sub = manual_review.add_subparsers(dest="manual_review_command", required=True)
    manual_review_session = manual_review_sub.add_parser("session", help="Create a manual-review session")
    manual_review_session.add_argument("--profile", required=True, help="Profile id such as <profile>")
    manual_review_session.add_argument("--ticket", required=True, help="Ticket id such as IDCEVODEV-977874")
    manual_review_session.add_argument("--workspace", help="Workspace root override")
    manual_review_session.add_argument("--output-root", help="Optional output root for manual-review sessions")
    manual_review_session.add_argument("--session-id", help="Optional deterministic session id")
    manual_review_session.add_argument(
        "--family",
        default="",
        help="Optional review template family: bmw_idcevo, bmw_idc23, or mini",
    )
    manual_review_session.add_argument("--json", action="store_true", help="Print session as JSON")
    manual_review_session.add_argument("--markdown", action="store_true", help="Print session summary as Markdown")

    manual_review_templates = manual_review_sub.add_parser("templates", help="List built-in car review templates")
    manual_review_templates.add_argument("--json", action="store_true", help="Print templates as JSON")

    manual_review_auto = manual_review_sub.add_parser(
        "auto-checks",
        help="Run local evidence auto-checks for the manual-review companion",
    )
    manual_review_auto.add_argument("--profile", required=True, help="Profile id such as G65")
    manual_review_auto.add_argument("--workspace", help="Workspace root override")
    manual_review_auto.add_argument("--json", action="store_true", help="Print auto-checks as JSON")
    manual_review_auto.add_argument("--markdown", action="store_true", help="Print auto-checks as Markdown")

    manual_review_assist = manual_review_sub.add_parser(
        "assist",
        help="Suggest operator-confirmed starting verdicts from local evidence",
    )
    manual_review_assist.add_argument("--profile", required=True, help="Profile id such as G65")
    manual_review_assist.add_argument("--workspace", help="Workspace root override")
    manual_review_assist.add_argument("--json", action="store_true", help="Print review assist as JSON")
    manual_review_assist.add_argument("--markdown", action="store_true", help="Print review assist as Markdown")

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
    run_profile.add_argument("profile_id", help="Canonical profile id such as <profile>")
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

    dependency_setup_worker = sub.add_parser("dependency-setup-worker", help=argparse.SUPPRESS)
    dependency_setup_worker.add_argument("action_id", help=argparse.SUPPRESS)
    dependency_setup_worker.add_argument("--workspace", required=True, help=argparse.SUPPRESS)
    dependency_setup_worker.add_argument("--target-path", default="", help=argparse.SUPPRESS)
    dependency_setup_worker.add_argument("--source-path", default="", help=argparse.SUPPRESS)

    station = sub.add_parser("station", help="Run the SGFX OpenHTF station surface")
    station_sub = station.add_subparsers(dest="station_command", required=True)
    station_run = station_sub.add_parser("run", help="Start the local SGFX station")
    station_run.add_argument("--profile", required=True, help="Profile id such as <profile>")
    station_run.add_argument("--workspace", required=True, help="Workspace root for SGFX read-only checks")
    station_run.add_argument("--bmw-root", help="Explicit digital-3d-car-models checkout path")
    station_run.add_argument("--ui-mode", default="clean", choices=("clean", "grafiks"), help="Station presentation mode")
    station_run.add_argument("--port", type=int, default=0, help="Station port; 0 chooses an available port")
    station_run.add_argument("--history", default="out/openhtf-history", help="OpenHTF history folder")
    station_run.add_argument("--no-browser", action="store_true", help="Do not open a browser automatically")
    station_run.add_argument("--once", action="store_true", help="Run once and exit after the station publishes the result")

    dashboard = sub.add_parser("dashboard", help="Run the SGFX operator dashboard")
    dashboard_sub = dashboard.add_subparsers(dest="dashboard_command", required=True)
    dashboard_run = dashboard_sub.add_parser("run", help="Start the local SGFX operator dashboard")
    dashboard_run.add_argument(
        "--profile",
        default="",
        help="Optional profile id; defaults to the first registered profile from list-profiles",
    )
    dashboard_run.add_argument("--workspace", required=True, help="Workspace root for SGFX read-only checks")
    dashboard_run.add_argument("--bmw-root", help="Explicit digital-3d-car-models checkout path")
    dashboard_run.add_argument("--ui-mode", default=None, choices=("clean", "grafiks"), help="Dashboard presentation mode")
    dashboard_run.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    dashboard_run.add_argument("--port", type=int, default=0, help="Dashboard port; 0 chooses an available port")
    dashboard_run.add_argument("--no-native", action="store_true", help="Run a local server without opening a native window")
    dashboard_run.add_argument("--reload", action="store_true", help="Reload automatically when local dashboard files change")

    ui = sub.add_parser("ui", help="Deprecated legacy UI; use `dashboard run --ui-mode clean` for operator work")
    ui.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    ui.add_argument("--port", type=int, default=8765, help="Bind port (default: 8765)")
    ui.add_argument("--reload", action="store_true", help="Reload automatically when local UI files change")

    desktop_state = sub.add_parser(
        "desktop-state",
        help="Inspect native/desktop-shell state snapshots from the shared Python core",
    )
    desktop_state_sub = desktop_state.add_subparsers(dest="desktop_state_command", required=True)

    desktop_profiles_parser = desktop_state_sub.add_parser(
        "profiles",
        help="List available desktop profiles",
        description="List available desktop profiles",
    )
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
    desktop_actions_parser.add_argument("profile_id", help="Profile id such as <profile>")
    desktop_actions_parser.add_argument("--workspace", help="Workspace root override")
    desktop_actions_parser.add_argument("--json", action="store_true", help="Print action payload as JSON")

    desktop_blockers_parser = desktop_state_sub.add_parser("blockers", help="List blocker cards for one profile")
    desktop_blockers_parser.add_argument("profile_id", help="Profile id such as <profile>")
    desktop_blockers_parser.add_argument("--workspace", help="Workspace root override")
    desktop_blockers_parser.add_argument("--json", action="store_true", help="Print blocker payload as JSON")

    desktop_manual_parser = desktop_state_sub.add_parser("manual", help="List manual-review cards for one profile")
    desktop_manual_parser.add_argument("profile_id", help="Profile id such as <profile>")
    desktop_manual_parser.add_argument("--workspace", help="Workspace root override")
    desktop_manual_parser.add_argument("--json", action="store_true", help="Print manual-card payload as JSON")

    desktop_surfaces_parser = desktop_state_sub.add_parser(
        "surfaces",
        help="List Grafiks evidence surfaces for one profile",
    )
    desktop_surfaces_parser.add_argument("profile_id", help="Profile id such as <profile>")
    desktop_surfaces_parser.add_argument("--workspace", help="Workspace root override")
    desktop_surfaces_parser.add_argument("--json", action="store_true", help="Print surface payload as JSON")

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

    desktop_delivery_parser = desktop_state_sub.add_parser(
        "delivery-readiness",
        help="Load the Delivery Readiness board for native-shell consumers",
    )
    desktop_delivery_parser.add_argument("--workspace", help="Workspace root override")
    desktop_delivery_parser.add_argument("--repo-root", help="SVN trunk root override")
    desktop_delivery_parser.add_argument("--bmw-repo-root", help="BMW digital-3d-car-models root override")
    desktop_delivery_parser.add_argument("--json", action="store_true", help="Print delivery-readiness payload as JSON")

    desktop_disabled_parser = desktop_state_sub.add_parser(
        "disabled-tests",
        help="Load the disabled-test inventory for native-shell consumers",
    )
    desktop_disabled_parser.add_argument("--workspace", help="Workspace root override")
    desktop_disabled_parser.add_argument("--repo-root", help="SVN trunk root override")
    desktop_disabled_parser.add_argument("--bmw-repo-root", help="BMW digital-3d-car-models root override")
    desktop_disabled_parser.add_argument("--json", action="store_true", help="Print disabled-test payload as JSON")

    desktop_api_version_parser = desktop_state_sub.add_parser(
        "api-version-coverage",
        help="Load the API version reference for native-shell consumers",
    )
    desktop_api_version_parser.add_argument("--workspace", help="Workspace root override")
    desktop_api_version_parser.add_argument("--repo-root", help="SVN trunk root override")
    desktop_api_version_parser.add_argument("--bmw-repo-root", help="BMW digital-3d-car-models root override")
    desktop_api_version_parser.add_argument("--json", action="store_true", help="Print API version coverage payload as JSON")

    desktop_country_variant_parser = desktop_state_sub.add_parser(
        "country-variant-coverage",
        help="Load the country-variant coverage matrix for native-shell consumers",
    )
    desktop_country_variant_parser.add_argument("--workspace", help="Workspace root override")
    desktop_country_variant_parser.add_argument("--repo-root", help="SVN trunk root override")
    desktop_country_variant_parser.add_argument("--bmw-repo-root", help="BMW digital-3d-car-models root override")
    desktop_country_variant_parser.add_argument("--json", action="store_true", help="Print country-variant coverage payload as JSON")

    desktop_export_size_trend_parser = desktop_state_sub.add_parser(
        "export-size-trend",
        help="Load the export-size trend board for native-shell consumers",
    )
    desktop_export_size_trend_parser.add_argument("--workspace", help="Workspace root override")
    desktop_export_size_trend_parser.add_argument("--repo-root", help="SVN trunk root override")
    desktop_export_size_trend_parser.add_argument("--json", action="store_true", help="Print export-size trend payload as JSON")

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

    _install_cli_discoverability(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    exit_code = 1
    try:
        exit_code = _main_impl(raw_args)
        return exit_code
    finally:
        _record_cli_activity(raw_args, exit_code)


def _main_impl(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        try:
            packs = parse_packs(args.packs)
        except ValueError as exc:
            parser.error(str(exc))
            return 1

        try:
            result = execute_bundle_run(
                bundle_dir=Path(args.bundle),
                config_path=Path(args.config),
                packs=packs,
                fail_on=args.fail_on,
                json_out=Path(args.json_out) if args.json_out else None,
                html_out=Path(args.html_out) if args.html_out else None,
                markdown_out=Path(args.md_out) if args.md_out else None,
            )
        except Exception as exc:
            print(_console_safe(f"run failed: {exc}"), file=sys.stderr)
            return 1
        _console_report(result.report)
        return result.exit_code

    if args.command in {
        "list-profiles",
        "list-actions",
        "list-checkers",
        "doctor",
        "run-profile",
        "operator-handoff",
        "onboarding-guide",
        "desktop-notification",
    }:
        from sg_preflight.cli.support import handle_support_command

        return handle_support_command(args, parser)

    if args.command == "full-qa-pass":
        from sg_preflight.cli.readiness import handle_readiness_command

        return handle_readiness_command(args, parser)

    if args.command in {"delivery-checklist", "delivery-workbook", "export-size-analysis"}:
        from sg_preflight.cli.delivery import handle_delivery_command

        return handle_delivery_command(args, parser)

    if args.command == "screenshot-test-state":
        from sg_preflight.cli.screenshots import handle_screenshot_command

        return handle_screenshot_command(args, parser)

    if args.command == "bmw-pipeline-diagnostics":
        from sg_preflight.cli.readiness import handle_readiness_command

        return handle_readiness_command(args, parser)

    if args.command == "risk-score":
        from sg_preflight.cli.evidence import handle_evidence_command

        return handle_evidence_command(args, parser)

    if args.command == "cross-car-comparison":
        from sg_preflight.cli.evidence import handle_evidence_command

        return handle_evidence_command(args, parser)

    if args.command == "bmw-git-readiness":
        from sg_preflight.cli.readiness import handle_readiness_command

        return handle_readiness_command(args, parser)

    if args.command == "qa-hero-readiness":
        from sg_preflight.cli.readiness import handle_readiness_command

        return handle_readiness_command(args, parser)

    if args.command == "workflow-status":
        from sg_preflight.cli.workflows import handle_workflow_command

        return handle_workflow_command(args, parser)

    if args.command == "profile-summary":
        from sg_preflight.cli.evidence import handle_evidence_command

        return handle_evidence_command(args, parser)

    if args.command in {"activity-log", "live-state"}:
        from sg_preflight.cli.activity import handle_activity_command

        return handle_activity_command(args, parser)

    if args.command == "template":
        from sg_preflight.cli.templates import handle_template_command

        return handle_template_command(args, parser)

    if args.command == "jira":
        from sg_preflight.cli.jira import handle_jira_command

        return handle_jira_command(args, parser)

    if args.command == "delivery-readiness":
        from sg_preflight.cli.delivery import handle_delivery_command

        return handle_delivery_command(args, parser)

    if args.command in {
        "disabled-tests",
        "api-version-coverage",
        "country-variant-coverage",
        "export-size-trend",
    }:
        from sg_preflight.cli.boards import handle_board_command

        return handle_board_command(args, parser)

    if args.command == "list-workflows":
        from sg_preflight.cli.workflows import handle_workflow_command

        return handle_workflow_command(args, parser)

    if args.command == "validate-workflow":
        from sg_preflight.cli.workflows import handle_workflow_command

        return handle_workflow_command(args, parser)

    if args.command == "run-workflow":
        from sg_preflight.cli.workflows import handle_workflow_command

        return handle_workflow_command(args, parser)

    if args.command == "ticket-review":
        from sg_preflight.cli.evidence import handle_evidence_command

        return handle_evidence_command(args, parser)

    if args.command in {"screenshot-triage", "screenshot-review-viewer"}:
        from sg_preflight.cli.screenshots import handle_screenshot_command

        return handle_screenshot_command(args, parser)

    if args.command == "quality-hero-report":
        from sg_preflight.cli.evidence import handle_evidence_command

        return handle_evidence_command(args, parser)

    if args.command == "daily-qa-snapshot":
        from sg_preflight.cli.digest import handle_digest_command

        return handle_digest_command(args, parser)

    if args.command == "review-board":
        from sg_preflight.cli.reviews import handle_reviews_command

        return handle_reviews_command(args, parser)

    if args.command == "review-priority":
        from sg_preflight.cli.reviews import handle_reviews_command

        return handle_reviews_command(args, parser)

    if args.command == "daily-delta":
        from sg_preflight.cli.reviews import handle_reviews_command

        return handle_reviews_command(args, parser)

    if args.command in {"daily-digest", "team-digest-board"}:
        from sg_preflight.cli.digest import handle_digest_command

        return handle_digest_command(args, parser)

    if args.command == "manual-review":
        from sg_preflight.cli.manual_review import handle_manual_review_command

        return handle_manual_review_command(args, parser)

    if args.command == "review-decisions":
        from sg_preflight.cli.reviews import handle_reviews_command

        return handle_reviews_command(args, parser)

    if args.command == "external-findings":
        from sg_preflight.cli.reviews import handle_reviews_command

        return handle_reviews_command(args, parser)

    if args.command == "run-action":
        from sg_preflight.cli.actions import handle_action_command

        return handle_action_command(args, parser)

    if args.command == "launch-action":
        from sg_preflight.cli.actions import handle_action_command

        return handle_action_command(args, parser)

    if args.command == "run-action-worker":
        from sg_preflight.cli.actions import handle_action_command

        return handle_action_command(args, parser)

    if args.command == "dependency-setup-worker":
        from sg_preflight.cli.actions import handle_action_command

        return handle_action_command(args, parser)

    if args.command == "station":
        try:
            from sg_preflight.openhtf_support.dependency import OpenHtfUnavailable
            from sg_preflight.openhtf_support.station import run_station

            if args.station_command == "run":
                return run_station(
                    profile_id=args.profile,
                    workspace=Path(args.workspace),
                    bmw_root=Path(args.bmw_root).resolve() if args.bmw_root else None,
                    ui_mode=args.ui_mode,
                    port=args.port,
                    history_path=Path(args.history),
                    open_browser=not args.no_browser,
                    once=args.once,
                )
            parser.error(f"Unhandled station command: {args.station_command}")
            return 1
        except OpenHtfUnavailable as exc:
            print(_console_safe(str(exc)), file=sys.stderr)
            return 1
        except Exception as exc:
            print(_console_safe(f"station failed: {exc}"), file=sys.stderr)
            return 1

    if args.command == "dashboard":
        if args.dashboard_command == "run" and args.ui_mode == "grafiks":
            try:
                from sg_preflight.dashboard.main import run_grafiks_mode

                return run_grafiks_mode(
                    profile_id=args.profile or "",
                    workspace=Path(args.workspace),
                    bmw_root=Path(args.bmw_root).resolve() if args.bmw_root else None,
                )
            except Exception as exc:
                print(_console_safe(f"dashboard grafiks failed: {exc}"), file=sys.stderr)
                return 1
        use_desktop_shell = (
            args.dashboard_command == "run"
            and (
                _is_frozen_exe() and not args.no_native and args.ui_mode in {None, "clean"}
            )
        )
        if use_desktop_shell:
            try:
                import os

                _existing = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
                _flags = "--disable-background-timer-throttling --disable-backgrounding-occluded-windows --disable-renderer-backgrounding"
                os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (_existing + " " + _flags).strip()
                from sg_preflight.desktop.app import run_desktop_app

                return run_desktop_app(
                    workspace=Path(args.workspace),
                    initial_profile_id=args.profile or "",
                    initial_mode=args.ui_mode or "clean",
                )
            except RuntimeError as exc:
                print(_console_safe(str(exc)), file=sys.stderr)
                return 1
        try:
            from sg_preflight.dashboard.dependency import NiceGuiUnavailable
            from sg_preflight.dashboard.main import run_dashboard

            if args.dashboard_command == "run":
                return run_dashboard(
                    profile_id=args.profile,
                    workspace=Path(args.workspace),
                    bmw_root=Path(args.bmw_root).resolve() if args.bmw_root else None,
                    ui_mode=args.ui_mode,
                    host=args.host,
                    port=args.port,
                    native=not args.no_native,
                    reload=args.reload,
                )
            parser.error(f"Unhandled dashboard command: {args.dashboard_command}")
            return 1
        except NiceGuiUnavailable as exc:
            print(_console_safe(str(exc)), file=sys.stderr)
            return 1
        except Exception as exc:
            log_path = None
            if _is_frozen_exe():
                try:
                    from sg_preflight.exe_entry import write_startup_error_log

                    log_path = write_startup_error_log(exc)
                except Exception:
                    log_path = None
                if args.dashboard_command == "run" and not args.no_native:
                    raise
            message = f"dashboard failed: {exc}"
            if log_path is not None:
                message = f"{message}. Details were written to: {log_path}"
            print(_console_safe(message), file=sys.stderr)
            return 1

    if args.command == "ui":
        from sg_preflight.ui import run_ui

        return run_ui(host=args.host, port=args.port, reload=args.reload)

    if args.command == "desktop-state":
        from sg_preflight.cli.desktop_state import handle_desktop_state_command

        return handle_desktop_state_command(args, parser)

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
