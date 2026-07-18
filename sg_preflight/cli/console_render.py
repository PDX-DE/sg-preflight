"""Console text/JSON renderers for CLI command output.

Owns the `_console_*` printers and the saved-template summary text builders,
plus the small text/JSON helpers (`_console_safe`, `_json_ready`, `_json_text`)
they share so this module never needs to import the `_common` facade.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path

from sg_preflight.api_version_coverage import IMPACT_REVIEW_LABEL
from sg_preflight.country_variant_coverage import (
    MAPPING_REVIEW_LABEL,
    MISSING_EXPECTED_LABEL,
    NO_RUNTIME_LABEL,
)
from sg_preflight.disabled_tests import CAUTIOUS_BASELINE_LABEL
from sg_preflight.export_size_trend import SIGNIFICANT_CHANGE_LABEL, UNREADABLE_LAYOUT_LABEL
from sg_preflight.profiles import list_run_profiles
from sg_preflight.qa_actions import list_operator_actions
from sg_preflight.screenshot_triage import VisualDiffThresholds
from sg_preflight.services import sg_checker_catalog
from sg_preflight.template_store import TEMPLATE_BANNER


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
    validation = payload.get("version_validation", {})
    if isinstance(validation, dict):
        print(
            "Version validation -> "
            f"ok: {validation.get('ok', 0)} | "
            f"drift: {validation.get('drift', 0)} | "
            f"unknown: {validation.get('unknown', 0)} | "
            f"not_pinned: {validation.get('not_pinned', 0)}"
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
        if item.get("recommended_version"):
            print(f"  recommended: {item['recommended_version']}")
        if item.get("version_status"):
            print(f"  validation: {item['version_status']}")
        if item.get("version_check_detail"):
            print(f"  version detail: {item['version_check_detail']}")
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


def _console_cross_domain_delivery(payload: dict[str, object]) -> None:
    counts = payload.get("counts", {})
    if not isinstance(counts, dict):
        counts = {}
    drift = counts.get("version_drift", {})
    if not isinstance(drift, dict):
        drift = {}
    print("Cross-Domain Delivery")
    print(f"Source: {payload.get('repo_root', '')}")
    print(f"State: {payload.get('source_state', '')}")
    print(
        "Summary -> "
        f"items: {counts.get('total', 0)} | "
        f"delivered: {counts.get('delivered', 0)} | "
        f"not delivered yet: {counts.get('not_delivered_yet', 0)} | "
        f"unknown/no changelog: {counts.get('unknown', 0)}"
    )
    print(
        "Version drift -> "
        f"Ramses max {drift.get('max_ramses') or 'not found'} "
        f"({drift.get('ramses_drift_count', 0)} row(s)); "
        f"RaCo Headless max {drift.get('max_raco_headless') or 'not found'} "
        f"({drift.get('raco_headless_drift_count', 0)} row(s))"
    )
    if drift.get("raco_basis") == "pinned":
        pinned = drift.get("raco_pinned_versions") or []
        print(
            f"RaCo drift measured against pinned versions {', '.join(str(v) for v in pinned)} "
            f"from {drift.get('raco_pin_source', '')}"
        )
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
        print("No cross-domain delivery rows found.")
        return
    for entry in entries[:18]:
        if not isinstance(entry, dict):
            continue
        print(
            _console_safe(
                f"- {entry.get('relative_path', '')}: {entry.get('delivery_status_label', '')}; "
                f"version {entry.get('version') or 'unknown'}; "
                f"Ramses {entry.get('ramses') or 'unknown'}; "
                f"RaCo {entry.get('raco_headless') or 'unknown'}; "
                f"{entry.get('rca_total_bytes', 0)} byte(s)"
            )
        )
    if len(entries) > 18:
        print(f"... {len(entries) - 18} more row(s)")


def _console_perspectives_inventory(payload: dict[str, object]) -> None:
    counts = payload.get("counts", {})
    if not isinstance(counts, dict):
        counts = {}
    print("Perspectives Inventory")
    print(f"Source: {payload.get('repo_root', '')}")
    print(f"State: {payload.get('source_state', '')}")
    print(
        "Summary -> "
        f"cars: {counts.get('car_total', 0)} | "
        f"files: {counts.get('file_total', 0)} | "
        f"display groups: {counts.get('display_type_group_count', 0)} | "
        f"peer outlier rows: {counts.get('peer_outlier_count', 0)} | "
        f"structural issue rows: {counts.get('structural_issue_count', 0)}"
    )
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
        print("No perspectives inventory rows found.")
        return
    for entry in entries[:18]:
        if not isinstance(entry, dict):
            continue
        flags = entry.get("peer_flags", [])
        if isinstance(flags, list) and flags:
            evidence = "; ".join(str(flag) for flag in flags)
        else:
            evidence = str(entry.get("comparison_note", ""))
        print(
            _console_safe(
                f"- {entry.get('relative_path', '')} {entry.get('display_type', '')}: "
                f"{entry.get('scene_count', 0)} scene(s); {evidence}"
            )
        )
    if len(entries) > 18:
        print(f"... {len(entries) - 18} more row(s)")


def _console_rack_readiness(payload: dict[str, object]) -> None:
    counts = payload.get("counts", {})
    if not isinstance(counts, dict):
        counts = {}
    print("Rack Pre-Flash Readiness")
    print(f"Source: {payload.get('repo_root', '')}")
    print(f"State: {payload.get('source_state', '')}")
    print(
        "Summary -> "
        f"IDCevo rows: {counts.get('entry_total', 0)} | "
        f"asset ready: {counts.get('asset_ready_count', 0)} | "
        f"asset blocked: {counts.get('asset_blocked_count', 0)} | "
        f"exported: {counts.get('exported_count', 0)} | "
        f"version metadata: {counts.get('version_ok_count', 0)} | "
        f"delivery context delivered: {counts.get('delivered_count', 0)} | "
        f"out of scope: {counts.get('out_of_scope_idcevo_dir_count', 0)} | "
        f"missing targets: {counts.get('missing_rack_target_dir_count', 0)}"
    )
    print(str(payload.get("manual_review_banner", "")))
    if payload.get("target_scope_note"):
        print(str(payload.get("target_scope_note", "")))
    artifacts = payload.get("artifacts")
    if isinstance(artifacts, dict):
        if artifacts.get("json_path"):
            print(f"JSON: {artifacts['json_path']}")
        if artifacts.get("markdown_path"):
            print(f"Markdown: {artifacts['markdown_path']}")
    print("-" * 80)
    rack_inventory = payload.get("rack_inventory")
    if isinstance(rack_inventory, dict):
        print("Rack Target Inventory Reference")
        print(_console_safe(str(rack_inventory.get("provenance_note", ""))))
        racks = rack_inventory.get("racks", [])
        if isinstance(racks, list):
            for rack in racks:
                if not isinstance(rack, dict):
                    continue
                print(
                    _console_safe(
                        f"- {rack.get('id', '')} ({rack.get('type', '')}): "
                        f"ip {rack.get('ip', '')}; sw {rack.get('software', '') or 'not listed'}; "
                        f"{rack.get('location', '')}; {rack.get('connection', '')}; "
                        f"booking {rack.get('booking_resource', '')}"
                        f"{'; ' + str(rack.get('notes', '')) if rack.get('notes') else ''}"
                    )
                )
        resources = rack_inventory.get("booking_resources", [])
        if isinstance(resources, list) and resources:
            print("Booking resources:")
            for resource in resources:
                if isinstance(resource, dict):
                    print(
                        _console_safe(
                            f"- {resource.get('label', '')} ({resource.get('email', '')}; "
                            f"{resource.get('resource_type', '')})"
                        )
                    )
        print("-" * 80)
    kpi_reference = payload.get("kpi_reference")
    if isinstance(kpi_reference, dict):
        print("KPI Expectation Reference")
        print(_console_safe(str(kpi_reference.get("provenance_note", ""))))
        print("These metrics are measured live on the rack and are not measured by SGFX.")
        metrics = kpi_reference.get("metrics", [])
        if isinstance(metrics, list):
            for metric in metrics:
                if not isinstance(metric, dict):
                    continue
                fields = metric.get("report_fields", [])
                fields_text = ", ".join(str(field) for field in fields) if isinstance(fields, list) else ""
                print(
                    _console_safe(
                        f"- {metric.get('name', '')} [{metric.get('unit', '')}]: "
                        f"{metric.get('source_tool', '')}; {metric.get('measurement', '')}; "
                        f"fields {fields_text}"
                    )
                )
        print("-" * 80)
    entries = payload.get("entries", [])
    out_of_scope = payload.get("out_of_scope_idcevo_dirs", [])
    if not isinstance(out_of_scope, list):
        out_of_scope = []
    missing_targets = payload.get("missing_rack_target_dirs", [])
    if not isinstance(missing_targets, list):
        missing_targets = []
    if (not isinstance(entries, list) or not entries) and not out_of_scope and not missing_targets:
        print("No rack readiness rows found.")
        return
    if isinstance(entries, list) and entries:
        for entry in entries[:18]:
            if not isinstance(entry, dict):
                continue
            blockers = entry.get("blockers", [])
            if isinstance(blockers, list) and blockers:
                evidence = "; ".join(str(blocker) for blocker in blockers[:3])
            else:
                evidence = "asset-side checks passed"
            context_notes = entry.get("context_notes", [])
            context_note = ""
            if isinstance(context_notes, list) and context_notes:
                context_note = str(context_notes[0]).strip()
            print(
                _console_safe(
                    f"- {entry.get('relative_path', '')}: {entry.get('asset_status', '')}; "
                    f"SVT {entry.get('expected_svt_filename', '')} ({entry.get('expected_svt_detail', '')}); {evidence}"
                    f"{'; ' + context_note if context_note else ''}"
                )
            )
        if len(entries) > 18:
            print(f"... {len(entries) - 18} more row(s)")
    if out_of_scope:
        print("IDCevo dirs outside current rack scope:")
        for entry in out_of_scope[:18]:
            if isinstance(entry, dict):
                print(_console_safe(f"- {entry.get('relative_path', '')}: {entry.get('reason', '')}"))
        if len(out_of_scope) > 18:
            print(f"... {len(out_of_scope) - 18} more out-of-scope row(s)")
    if missing_targets:
        print("Documented rack targets with no delivery row:")
        for entry in missing_targets[:18]:
            if isinstance(entry, dict):
                print(_console_safe(f"- {entry.get('relative_path', '')}: {entry.get('reason', '')}"))
        if len(missing_targets) > 18:
            print(f"... {len(missing_targets) - 18} more missing target row(s)")


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
