"""Markdown rendering for the daily QA snapshot: review priority ranking, daily delta, battery baseline gaps, and the candidate review gallery."""

from __future__ import annotations

import json
import os
from html import escape
from pathlib import Path
from typing import Any

from sg_preflight.daily_snapshot_scoring import (
    _battery_baseline_gap_payload,
    _battery_gap_recommendation,
    _daily_delta_payload,
    _review_priority_payload,
    _review_priority_score,
)


def _render_review_priority_markdown(snapshot: DailyQaSnapshot) -> str:
    payload = _review_priority_payload(snapshot)
    lines = [
        "# Screenshot Review Priority Ranking",
        "",
        f"- Generated: `{snapshot.created_at}`",
        f"- Scope: `{', '.join(snapshot.scope_profiles)}`",
        "- This is deterministic operator ranking, not final visual signoff.",
        "",
        "| Priority | Profile | Scenario | Verdict | Reason | Recommendation |",
        "| ---: | --- | --- | --- | --- | --- |",
    ]
    for item in payload["ranked_items"]:
        lines.append(
            f"| {item['priority_level']} ({item['priority_score']}) | {item['profile_id']} | `{item['filter_name']}` | "
            f"`{item['verdict']}` | {item['reason']} | {item['recommendation']} |"
        )
    if not payload["ranked_items"]:
        lines.append("| 0 | - | - | - | No ranked screenshot items in this snapshot. | - |")
    lines.extend(["", "## Top 5 To Review", ""])
    for item in payload["top_five"]:
        lines.append(
            f"- {item['profile_id']}: `{item['filter_name']}` -> `{item['verdict']}` "
            f"({item['priority_level']} / {item['priority_score']})"
        )
    if not payload["top_five"]:
        lines.append("- No screenshot items require ranking in this snapshot.")
    lines.append("")
    return "\n".join(lines)


def _render_daily_delta_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Daily QA Delta Summary",
        "",
        f"- Current run: `{payload.get('current_created_at', '')}`",
        f"- Previous run: `{payload.get('previous_created_at', '') or 'none'}`",
        f"- Current output root: `{payload.get('current_output_root', '')}`",
    ]
    previous_output_root = str(payload.get("previous_output_root", "")).strip()
    if previous_output_root:
        lines.append(f"- Previous output root: `{previous_output_root}`")
    lines.extend(
        [
            "",
            "## New Failures",
        ]
    )
    new_failures = payload.get("new_failures", [])
    if new_failures:
        lines.extend(f"- `{item}`" for item in new_failures)
    else:
        lines.append("- None")
    lines.extend(["", "## Resolved Failures"])
    resolved_failures = payload.get("resolved_failures", [])
    if resolved_failures:
        lines.extend(f"- `{item}`" for item in resolved_failures)
    else:
        lines.append("- None")
    lines.extend(["", "## New Screenshot Diffs"])
    new_diffs = payload.get("new_screenshot_diffs", [])
    if new_diffs:
        lines.extend(f"- `{item}`" for item in new_diffs)
    else:
        lines.append("- None")
    lines.extend(["", "## Unchanged Blockers"])
    unchanged = payload.get("unchanged_blockers", [])
    if unchanged:
        lines.extend(f"- {item}" for item in unchanged)
    else:
        lines.append("- None")
    lines.extend(["", "## Changed Counts", "", "```json", json.dumps(payload.get("changed_counts", {}), indent=2, ensure_ascii=False), "```", "", "## Top 5 To Review"])
    top = payload.get("top_five_to_review", [])
    if top:
        lines.extend(f"- {item}" for item in top)
    else:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)


def _render_candidate_review_gallery(snapshot: DailyQaSnapshot, *, html_root: Path | None = None) -> str:
    sections: list[str] = [
        "<!doctype html>",
        "<html lang=\"en\">",
        "<head>",
        "<meta charset=\"utf-8\">",
        "<title>Candidate Review Gallery</title>",
        "<style>",
        "body { font-family: Segoe UI, Arial, sans-serif; margin: 24px; background: #111827; color: #f3f4f6; }",
        "h1, h2, h3 { margin-bottom: 0.4rem; }",
        ".note { color: #cbd5e1; max-width: 70rem; }",
        ".card { background: #1f2937; border: 1px solid #374151; border-radius: 12px; padding: 16px; margin: 16px 0; }",
        ".meta { color: #d1d5db; margin-bottom: 12px; }",
        ".gallery { display: flex; flex-wrap: wrap; gap: 16px; }",
        ".shot { background: #0f172a; border-radius: 8px; padding: 12px; width: min(31rem, 100%); }",
        ".shot img { max-width: 100%; height: auto; display: block; background: #000; border-radius: 6px; }",
        ".tag { display: inline-block; padding: 2px 8px; border-radius: 999px; background: #2563eb; color: #eff6ff; font-size: 12px; margin-right: 8px; }",
        ".tag.warn { background: #b45309; color: #fffbeb; }",
        ".tag.ok { background: #166534; color: #ecfdf5; }",
        ".tag.proxy { background: #7c3aed; color: #f5f3ff; }",
        ".summary { display: flex; flex-wrap: wrap; gap: 12px; margin: 16px 0 24px; }",
        ".summary .item { background: #0f172a; border: 1px solid #374151; border-radius: 10px; padding: 10px 12px; min-width: 14rem; }",
        ".recommendation { color: #cbd5e1; margin: 10px 0 0; }",
        "code { color: #bfdbfe; }",
        "</style>",
        "</head>",
        "<body>",
        "<h1>Candidate Review Gallery</h1>",
        "<p class=\"note\">This gallery flattens the broader screenshot battery into a quick visual pass. It is intended to reduce manual navigation overhead, not to replace final signoff.</p>",
    ]

    items = [
        item
        for item in snapshot.battery_results
        if item.verdict in {"baseline_candidate_ready", "proxy_candidate_ready", "needs_manual_review", "likely_ok"}
    ]
    items.sort(
        key=lambda item: (
            _review_priority_score(item),
            item.profile_id.upper(),
            item.filter_name.lower(),
        ),
        reverse=True,
    )
    if not items:
        sections.extend(
            [
                "<p>No candidate-ready or reviewable screenshot outputs were found in this snapshot.</p>",
                "</body>",
                "</html>",
            ]
        )
        return "\n".join(sections)

    verdict_counts: dict[str, int] = {}
    for item in items:
        verdict_counts[item.verdict] = verdict_counts.get(item.verdict, 0) + 1
    sections.extend(
        [
            "<div class=\"summary\">",
            f"<div class=\"item\"><strong>Total reviewable items</strong><br>{len(items)}</div>",
            f"<div class=\"item\"><strong>Needs manual diff review</strong><br>{verdict_counts.get('needs_manual_review', 0)}</div>",
            f"<div class=\"item\"><strong>Exact baseline candidates</strong><br>{verdict_counts.get('baseline_candidate_ready', 0)}</div>",
            f"<div class=\"item\"><strong>Proxy candidates</strong><br>{verdict_counts.get('proxy_candidate_ready', 0)}</div>",
            f"<div class=\"item\"><strong>Likely OK exact compares</strong><br>{verdict_counts.get('likely_ok', 0)}</div>",
            "</div>",
        ]
    )

    for item in items:
        priority_score = _review_priority_score(item)
        recommendation = (
            "Review the diff payload and decide pass/fail."
            if item.verdict == "needs_manual_review"
            else _battery_gap_recommendation(item)
        )
        verdict_tag_class = "ok" if item.verdict == "likely_ok" else "proxy" if item.verdict == "proxy_candidate_ready" else "warn" if item.verdict == "needs_manual_review" else ""
        sections.extend(
            [
                "<div class=\"card\">",
                f"<h2>{escape(item.profile_id)} / <code>{escape(item.filter_name)}</code></h2>",
                "<div class=\"meta\">",
                f"<span class=\"tag {verdict_tag_class}\">{escape(item.verdict)}</span>",
                f"<span class=\"tag\">priority {priority_score}</span>",
                f"<span>Expected {item.expected_count} | Actual {item.actual_count} | Diff {item.diff_count}</span>",
                "</div>",
                "<div class=\"gallery\">",
            ]
        )
        actual_root = Path(item.results_root) / "tests" / "actuals"
        proxy_root = Path(item.results_root) / "tests" / "proxy_actuals"
        shot_names = item.actual_files
        shot_root = actual_root
        shot_label = "actual"
        if item.verdict == "proxy_candidate_ready" and item.proxy_files:
            shot_names = item.proxy_files
            shot_root = proxy_root
            shot_label = "proxy"
        for name in shot_names:
            image_path = (shot_root / name).resolve()
            if not image_path.exists():
                continue
            image_src = image_path.as_uri()
            image_display_path = str(image_path)
            if html_root is not None:
                image_src = Path(os.path.relpath(image_path, html_root.parent)).as_posix()
                image_display_path = image_src
            sections.extend(
                [
                    "<div class=\"shot\">",
                    f"<h3>{escape(name)} <span class=\"tag {'proxy' if shot_label == 'proxy' else 'warn'}\">{escape(shot_label)}</span></h3>",
                    f"<img src=\"{escape(image_src)}\" alt=\"{escape(name)}\">",
                    f"<p><code>{escape(image_display_path)}</code></p>",
                    "</div>",
                ]
            )
        sections.extend(
            [
                "</div>",
                f"<p class=\"recommendation\"><strong>Suggested next action:</strong> {escape(recommendation)}</p>",
                "</div>",
            ]
        )

    sections.extend(["</body>", "</html>"])
    return "\n".join(sections)


def _render_battery_baseline_gaps_markdown(snapshot: DailyQaSnapshot) -> str:
    payload = _battery_baseline_gap_payload(snapshot)
    lines = [
        "# Broader Screenshot Battery - Baseline And Output Gaps",
        "",
    ]

    profiles = payload.get("profiles", [])
    if not profiles:
        lines.append("No missing expected baselines were inferred from the current broader battery run.")
        lines.append("")
        return "\n".join(lines)

    for profile in profiles:
        profile_id = str(profile.get("profile_id", "")).strip() or "unknown"
        lines.extend(
            [
                f"## {profile_id}",
                "",
            ]
        )
        for gap in profile.get("gaps", []):
            filter_name = str(gap.get("filter_name", "")).strip() or "unknown"
            verdict = str(gap.get("verdict", "")).strip() or "unknown"
            missing_baseline = str(gap.get("missing_expected_baseline", "")).strip() or "unknown expected file"
            target_output_present = str(gap.get("target_output_present", "")).strip() or "no"
            actual_files = str(gap.get("actual_files", "")).strip() or "(none)"
            recommendation = str(gap.get("recommendation", "")).strip()
            lines.append(
                f"- `{filter_name}` -> verdict `{verdict}`; missing expected baseline `{missing_baseline}`; "
                f"target output present `{target_output_present}`; actual files `{actual_files}`"
            )
            if recommendation:
                lines.append(f"  Recommendation: {recommendation}")
        lines.append("")

    return "\n".join(lines)


def _render_snapshot_markdown(snapshot: DailyQaSnapshot) -> str:
    lines = [
        f"# Daily 3D Car QA Summary",
        "",
        f"- Generated: `{snapshot.created_at}`",
        f"- Scope: `{', '.join(snapshot.scope_profiles)}`",
        f"- BMW repo root: `{snapshot.bmw_repo_root or 'not found'}`",
        "",
        "## Config Check",
        "",
        f"- Status: `{snapshot.config_check.status}`",
        f"- Python: `{snapshot.config_check.python_exe}`",
        f"- Log: `{snapshot.config_check.log_path}`",
    ]
    if snapshot.config_check.error:
        lines.append(f"- Error: `{snapshot.config_check.error}`")
    if snapshot.config_check.output_excerpt:
        lines.extend(
            [
                "",
                "```text",
                snapshot.config_check.output_excerpt.rstrip(),
                "```",
            ]
        )

    lines.extend(
        [
            "",
            "## Smoke Results",
            "",
            "| Profile | Status | Smoke Test | Ramses Bytes | Expected | Actual | Diff | Compare |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for item in snapshot.smoke_results:
        lines.append(
            f"| {item.profile_id} | {item.status} | `{item.smoke_test}` | "
            f"{item.exported_ramses_size} | {item.expected_count} | {item.actual_count} | {item.diff_count} | "
            f"{'passed' if item.compare_ok else 'not-passed'} |"
        )
    for item in snapshot.smoke_results:
        lines.extend(
            [
                "",
                f"### {item.profile_id}",
                "",
                f"- BMW profile: `{item.bmw_profile_id}`",
                f"- SG project root: `{item.sg_project_root}`",
                f"- Test config: `{item.bmw_test_config_path or 'not found'}`",
                f"- Log: `{item.log_path}`",
            ]
        )
        if item.error:
            lines.append(f"- Error: `{item.error}`")
        if item.notes:
            lines.append("- Notes:")
            for note in item.notes:
                lines.append(f"  - {note}")

    if snapshot.battery_results:
        lines.extend(
            [
                "",
                "## Broader Screenshot Battery",
                "",
                "| Profile | Filter | Verdict | Expected | Actual | Diff | Log |",
                "| --- | --- | --- | ---: | ---: | ---: | --- |",
            ]
        )
        for item in snapshot.battery_results:
            lines.append(
                f"| {item.profile_id} | `{item.filter_name}` | {item.verdict} | "
                f"{item.expected_count} | {item.actual_count} | {item.diff_count} | `{item.log_path}` |"
            )

    lines.extend(
        [
            "",
            "## Diagnostics",
            "",
        ]
    )
    if snapshot.diagnostics:
        lines.extend(f"- {item}" for item in snapshot.diagnostics)
    else:
        lines.append("- No grouped cross-scenario diagnosis was inferred from the current battery run.")

    lines.extend(
        [
            "",
            "## Top Review Items",
            "",
        ]
    )
    if snapshot.top_review_items:
        lines.extend(f"- {item}" for item in snapshot.top_review_items)
    else:
        lines.append("- No immediate review items were inferred from the current smoke pass.")

    lines.extend(
        [
            "",
            "## Blocked Steps",
            "",
        ]
    )
    if snapshot.blocked_steps:
        lines.extend(f"- {item}" for item in snapshot.blocked_steps)
    else:
        lines.append("- No blockers were detected in this local snapshot.")

    if snapshot.notes:
        lines.extend(
            [
                "",
                "## Notes",
                "",
            ]
        )
        lines.extend(f"- {item}" for item in snapshot.notes)

    lines.append("")
    return "\n".join(lines)
