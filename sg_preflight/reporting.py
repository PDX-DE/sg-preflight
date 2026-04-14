from __future__ import annotations

import json
from collections import defaultdict
from html import escape
from pathlib import Path
from typing import Any

from sg_preflight.models import Report
from sg_preflight.utils import ensure_parent


SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def _severity_rank(value: str) -> int:
    return SEVERITY_ORDER.get(value.lower(), 99)


def _format_occurrence_label(count: int) -> str:
    suffix = "occurrence" if count == 1 else "occurrences"
    return f"{count} {suffix}"


def _group_findings(report: Report) -> list[dict[str, object]]:
    groups: dict[tuple[str, str, str, str], dict[str, object]] = {}

    for pack in report.packs:
        for finding in pack.findings:
            severity = finding.severity.lower()
            key = (pack.pack, severity, finding.code, finding.message)
            group = groups.get(key)
            if group is None:
                group = {
                    "pack": pack.pack,
                    "severity": severity,
                    "code": finding.code,
                    "message": finding.message,
                    "count": 0,
                    "locations": [],
                }
                groups[key] = group

            group["count"] = int(group["count"]) + 1
            if finding.location:
                locations = group["locations"]
                if isinstance(locations, list) and finding.location not in locations and len(locations) < 5:
                    locations.append(finding.location)

    return sorted(
        groups.values(),
        key=lambda item: (
            _severity_rank(str(item["severity"])),
            -int(item["count"]),
            str(item["pack"]),
            str(item["code"]),
            str(item["message"]),
        ),
    )


def _reporting_rules(config: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {}
    value = config.get("reporting", {})
    return value if isinstance(value, dict) else {}


def _context_items(report: Report, rules: dict[str, Any]) -> list[dict[str, str]]:
    if not isinstance(report.context, dict):
        return []

    labels = rules.get("context_labels", {})
    order = [str(item) for item in rules.get("context_field_order", []) if item]
    ordered_keys: list[str] = []
    for key in order:
        if report.context.get(key):
            ordered_keys.append(key)
    for key in sorted(report.context):
        if key not in ordered_keys and report.context.get(key):
            ordered_keys.append(key)

    items = []
    for key in ordered_keys:
        value = report.context.get(key)
        if value is None or str(value).strip() == "":
            continue
        label = str(labels.get(key, key.replace("_", " ").title()))
        items.append({"key": key, "label": label, "value": str(value)})
    return items


def _finding_hint(pack: str, code: str, rules: dict[str, Any]) -> dict[str, str]:
    code_hints = rules.get("code_hints", {})
    pack_owner_hints = rules.get("pack_owner_hints", {})
    pack_action_hints = rules.get("pack_action_hints", {})

    code_hint = code_hints.get(code, {}) if isinstance(code_hints, dict) else {}
    owner = ""
    action = ""
    if isinstance(code_hint, dict):
        owner = str(code_hint.get("owner", "")).strip()
        action = str(code_hint.get("action", "")).strip()

    if not owner and isinstance(pack_owner_hints, dict):
        owner = str(pack_owner_hints.get(pack, "")).strip()
    if not action and isinstance(pack_action_hints, dict):
        action = str(pack_action_hints.get(pack, "")).strip()

    return {"owner": owner, "action": action}


def _action_items(report: Report, rules: dict[str, Any]) -> list[dict[str, object]]:
    items = []
    for group in _group_findings(report):
        hint = _finding_hint(str(group["pack"]), str(group["code"]), rules)
        items.append({**group, **hint})
    return items


def build_report_presentation(
    report: Report,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rules = _reporting_rules(config)
    grouped_findings = []
    for item in _group_findings(report):
        hint = _finding_hint(str(item["pack"]), str(item["code"]), rules)
        grouped_findings.append({**item, **hint})

    return {
        "summary": report.summary(),
        "context_items": _context_items(report, rules),
        "grouped_findings": grouped_findings,
        "action_items": _action_items(report, rules),
    }


def finding_hint(pack: str, code: str, config: dict[str, Any] | None = None) -> dict[str, str]:
    return _finding_hint(pack, code, _reporting_rules(config))


def write_json_report(report: Report, output_path: Path) -> None:
    ensure_parent(output_path)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(report.to_dict(), handle, indent=2, ensure_ascii=False)


def write_markdown_report(
    report: Report,
    output_path: Path,
    config: dict[str, Any] | None = None,
) -> None:
    ensure_parent(output_path)
    rules = _reporting_rules(config)
    presentation = build_report_presentation(report, config)
    summary = presentation["summary"]
    context_items = presentation["context_items"]
    grouped_findings = presentation["grouped_findings"]
    action_items = presentation["action_items"][:8]

    if summary["errors"] > 0:
        readout = "Needs action before this can be treated as healthy."
    elif summary["warnings"] > 0:
        readout = "Usable signal, but still needs triage."
    else:
        readout = "Clean run with no findings."

    lines: list[str] = [
        "# SG Preflight QA Handoff",
        "",
        f"- Bundle: `{report.bundle}`",
        f"- Readout: {readout}",
        (
            f"- Summary: errors={summary['errors']}, warnings={summary['warnings']}, "
            f"info={summary['info']}, total={summary['total']}"
        ),
    ]

    if context_items:
        lines.extend(["", "## Workflow Context", ""])
        for item in context_items:
            lines.append(f"- {item['label']}: {item['value']}")

    lines.extend(["", "## Suggested Next Actions", ""])
    if not action_items:
        lines.append("- No actions needed.")
    else:
        for item in action_items:
            label = _format_occurrence_label(int(item["count"]))
            lines.append(
                f"- [{str(item['severity']).upper()}] {item['pack']} / {item['code']} ({label})"
            )
            action = str(item.get("action", "")).strip()
            owner = str(item.get("owner", "")).strip()
            locations = item.get("locations", [])
            if action:
                lines.append(f"Action: {action}")
            if owner:
                lines.append(f"Owner: {owner}")
            if isinstance(locations, list) and locations:
                lines.append(f"Examples: {', '.join(str(location) for location in locations[:4])}")
            lines.append(f"Why: {item['message']}")
            lines.append("")

    lines.extend(["## Pack Summary", ""])
    for pack in report.packs:
        lines.append(
            f"- {pack.pack}: errors={pack.error_count}, warnings={pack.warning_count}, "
            f"info={pack.info_count}, total={len(pack.findings)}"
        )

    lines.extend(["", "## Grouped Findings", ""])
    if not grouped_findings:
        lines.append("- No findings.")
    else:
        for item in grouped_findings:
            hint = _finding_hint(str(item["pack"]), str(item["code"]), rules)
            label = _format_occurrence_label(int(item["count"]))
            lines.append(
                f"- [{str(item['severity']).upper()}] {item['pack']} / {item['code']} ({label})"
            )
            lines.append(f"Message: {item['message']}")
            locations = item.get("locations", [])
            if isinstance(locations, list) and locations:
                lines.append(f"Sample locations: {', '.join(str(location) for location in locations[:4])}")
            if hint["owner"]:
                lines.append(f"Owner hint: {hint['owner']}")
            if hint["action"]:
                lines.append(f"Suggested action: {hint['action']}")
            lines.append("")

    with output_path.open("w", encoding="utf-8") as handle:
        handle.write("\n".join(lines).strip() + "\n")


def write_html_report(
    report: Report,
    output_path: Path,
    config: dict[str, Any] | None = None,
) -> None:
    ensure_parent(output_path)
    rules = _reporting_rules(config)
    presentation = build_report_presentation(report, config)
    summary = presentation["summary"]
    grouped_findings = presentation["grouped_findings"]
    context_items = presentation["context_items"]
    action_items = presentation["action_items"][:8]
    groups_by_pack: dict[str, list[dict[str, object]]] = defaultdict(list)
    for item in grouped_findings:
        groups_by_pack[str(item["pack"])].append(item)

    detail_rows = []
    pack_rows = []
    pack_cards = []
    group_rows = []
    notable_rows = []
    action_rows = []
    context_cards = []
    full_sections = []

    for item in context_items:
        context_cards.append(
            "<article class='context-card'>"
            f"<strong>{escape(item['label'])}</strong>"
            f"<div class='context-value'>{escape(item['value'])}</div>"
            "</article>"
        )

    for pack in report.packs:
        status_label = (
            "clean"
            if not pack.findings
            else f"{pack.error_count} errors, {pack.warning_count} warnings, {pack.info_count} info"
        )
        pack_rows.append(
            "<tr>"
            f"<td>{escape(pack.pack)}</td>"
            f"<td>{pack.error_count}</td>"
            f"<td>{pack.warning_count}</td>"
            f"<td>{pack.info_count}</td>"
            f"<td>{len(pack.findings)}</td>"
            f"<td>{escape(status_label)}</td>"
            "</tr>"
        )

        highlights = groups_by_pack.get(pack.pack, [])[:3]
        if highlights:
            highlight_items = []
            for item in highlights:
                count = int(item["count"])
                label = _format_occurrence_label(count)
                highlight_items.append(
                    "<li>"
                    f"<span class='issue-code'>{escape(str(item['code']))}</span> "
                    f"<span class='issue-count'>{escape(label)}</span>"
                    "</li>"
                )
            highlight_markup = f"<ul class='pack-highlight-list'>{''.join(highlight_items)}</ul>"
        else:
            highlight_markup = "<p class='muted'>No findings in this pack.</p>"

        pack_cards.append(
            "<article class='pack-card'>"
            f"<h3>{escape(pack.pack)}</h3>"
            f"<p class='pack-status'>{escape(status_label)}</p>"
            f"{highlight_markup}"
            "</article>"
        )

        section_rows = []
        for finding in pack.findings:
            severity = finding.severity.lower()
            details = json.dumps(finding.details, ensure_ascii=False) if finding.details else ""
            rendered_row = (
                f"<tr class='severity-{escape(severity)}'>"
                f"<td>{escape(finding.severity.upper())}</td>"
                f"<td>{escape(finding.code)}</td>"
                f"<td>{escape(finding.location or '')}</td>"
                f"<td>{escape(finding.message)}</td>"
                f"<td><code>{escape(details)}</code></td>"
                "</tr>"
            )
            detail_rows.append(
                f"<tr class='severity-{escape(severity)}'>"
                f"<td>{escape(pack.pack)}</td>"
                f"<td>{escape(finding.severity.upper())}</td>"
                f"<td>{escape(finding.code)}</td>"
                f"<td>{escape(finding.location or '')}</td>"
                f"<td>{escape(finding.message)}</td>"
                f"<td><code>{escape(details)}</code></td>"
                "</tr>"
            )
            section_rows.append(rendered_row)

        section_table = "\n".join(section_rows) or "<tr><td colspan='5'>No findings</td></tr>"
        full_sections.append(
            "<details class='pack-details'>"
            f"<summary>{escape(pack.pack)} "
            f"({pack.error_count} errors, {pack.warning_count} warnings, {pack.info_count} info)</summary>"
            "<table>"
            "<thead>"
            "<tr>"
            "<th>Severity</th>"
            "<th>Code</th>"
            "<th>Location</th>"
            "<th>Message</th>"
            "<th>Details</th>"
            "</tr>"
            "</thead>"
            f"<tbody>{section_table}</tbody>"
            "</table>"
            "</details>"
        )

    for item in grouped_findings:
        locations = item["locations"]
        if isinstance(locations, list) and locations:
            sample_locations = "<br />".join(f"<code>{escape(str(location))}</code>" for location in locations)
        else:
            sample_locations = "<span class='muted'>No location</span>"

        count = int(item["count"])
        owner = str(item.get("owner", "")).strip()
        action = str(item.get("action", "")).strip()
        owner_html = escape(owner) if owner else "<span class='muted'>No owner hint</span>"
        action_html = escape(action) if action else "<span class='muted'>No action hint</span>"
        group_rows.append(
            f"<tr class='severity-{escape(str(item['severity']))}'>"
            f"<td>{escape(str(item['pack']))}</td>"
            f"<td>{escape(str(item['severity']).upper())}</td>"
            f"<td>{escape(str(item['code']))}</td>"
            f"<td>{escape(_format_occurrence_label(count))}</td>"
            f"<td>{sample_locations}</td>"
            f"<td>{escape(str(item['message']))}</td>"
            f"<td>{owner_html}</td>"
            f"<td>{action_html}</td>"
            "</tr>"
        )

    for item in grouped_findings[:8]:
        count = int(item["count"])
        label = _format_occurrence_label(count)
        locations = item["locations"]
        location_text = ""
        if isinstance(locations, list) and locations:
            location_text = f" Examples: {', '.join(str(location) for location in locations[:3])}."
        notable_rows.append(
            "<li>"
            f"<span class='severity-pill severity-{escape(str(item['severity']))}'>{escape(str(item['severity']).upper())}</span> "
            f"<strong>{escape(str(item['pack']))}</strong> / "
            f"<span class='issue-code'>{escape(str(item['code']))}</span> "
            f"<span class='issue-count'>{escape(label)}</span><br />"
            f"{escape(str(item['message']))}{escape(location_text)}"
            "</li>"
        )

    for item in action_items:
        label = _format_occurrence_label(int(item["count"]))
        locations = item.get("locations", [])
        sample_locations = ""
        if isinstance(locations, list) and locations:
            sample_locations = (
                "<p class='muted'>Examples: "
                + escape(", ".join(str(location) for location in locations[:4]))
                + "</p>"
            )
        action_rows.append(
            "<article class='action-card'>"
            f"<div class='action-head'><span class='severity-pill severity-{escape(str(item['severity']))}'>"
            f"{escape(str(item['severity']).upper())}</span>"
            f"<span class='issue-code'>{escape(str(item['pack']))} / {escape(str(item['code']))}</span>"
            f"<span class='issue-count'>{escape(label)}</span></div>"
            f"<p>{escape(str(item['message']))}</p>"
            f"<p><strong>Owner hint:</strong> {escape(str(item.get('owner', '') or 'No owner hint'))}</p>"
            f"<p><strong>Suggested action:</strong> {escape(str(item.get('action', '') or 'No action hint'))}</p>"
            f"{sample_locations}"
            "</article>"
        )

    detail_table = "\n".join(detail_rows) or "<tr><td colspan='6'>No findings</td></tr>"
    pack_table = "\n".join(pack_rows)
    grouped_table = "\n".join(group_rows) or "<tr><td colspan='8'>No grouped findings</td></tr>"
    pack_cards_markup = "\n".join(pack_cards)
    context_cards_markup = "\n".join(context_cards)
    action_cards_markup = "\n".join(action_rows)
    notable_markup = (
        f"<ul class='notable-list'>{''.join(notable_rows)}</ul>"
        if notable_rows
        else "<p class='muted'>No notable findings.</p>"
    )
    full_sections_markup = "\n".join(full_sections)
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>SG Preflight Report</title>
<style>
:root {{
  --bg: #f6f3eb;
  --panel: #fffdf8;
  --panel-strong: #f1ebdc;
  --border: #d8cfbc;
  --text: #1f2328;
  --muted: #645c4b;
  --accent: #6d8b74;
  --error: #b54a3b;
  --warning: #c58c27;
  --info: #4c7498;
}}
body {{
  font-family: "Segoe UI", Arial, Helvetica, sans-serif;
  margin: 2rem;
  background: linear-gradient(180deg, #f4efe3 0%, #f8f6f0 100%);
  color: var(--text);
}}
h1, h2, h3 {{
  margin-bottom: 0.4rem;
}}
h1 {{
  margin-top: 0;
}}
.hero {{
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 1.5rem;
  margin-bottom: 1.5rem;
  box-shadow: 0 8px 24px rgba(38, 34, 23, 0.06);
}}
.hero p {{
  margin: 0.2rem 0 0;
}}
.summary,
.context-grid,
.pack-grid,
.action-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 0.9rem;
  margin-bottom: 1.5rem;
}}
.summary {{
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
}}
.card,
.context-card,
.pack-card,
.action-card {{
  background: var(--panel);
  padding: 1rem;
  border-radius: 12px;
  border: 1px solid var(--border);
  box-shadow: 0 8px 24px rgba(38, 34, 23, 0.04);
}}
.card strong,
.context-card strong {{
  color: var(--muted);
  text-transform: uppercase;
  font-size: 0.8rem;
  letter-spacing: 0.04em;
}}
.card-value,
.context-value {{
  font-size: 1.1rem;
  margin-top: 0.35rem;
  font-weight: 600;
}}
.card-value {{
  font-size: 1.8rem;
}}
.card-errors .card-value {{
  color: var(--error);
}}
.card-warnings .card-value {{
  color: var(--warning);
}}
.card-info .card-value {{
  color: var(--info);
}}
.card-total .card-value {{
  color: var(--accent);
}}
.section {{
  margin-bottom: 1.5rem;
}}
.pack-card h3,
.action-card p {{
  margin-top: 0;
}}
.pack-status {{
  color: var(--muted);
  font-weight: 600;
}}
.pack-highlight-list,
.notable-list {{
  margin: 0.6rem 0 0;
  padding-left: 1.2rem;
}}
.pack-highlight-list li,
.notable-list li {{
  margin-bottom: 0.5rem;
}}
.action-head {{
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
  margin-bottom: 0.75rem;
}}
table {{
  width: 100%;
  border-collapse: collapse;
  background: var(--panel);
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 8px 24px rgba(38, 34, 23, 0.04);
}}
th, td {{
  border: 1px solid var(--border);
  padding: 0.6rem;
  text-align: left;
  vertical-align: top;
}}
th {{
  background: var(--panel-strong);
}}
.small {{
  color: var(--muted);
}}
code {{
  white-space: pre-wrap;
  word-break: break-word;
  font-family: Consolas, "Courier New", monospace;
  font-size: 0.92em;
}}
.muted {{
  color: var(--muted);
}}
.issue-code {{
  font-family: Consolas, "Courier New", monospace;
}}
.issue-count {{
  color: var(--muted);
  font-weight: 600;
  margin-left: 0.35rem;
}}
.severity-pill {{
  display: inline-block;
  min-width: 4.5rem;
  padding: 0.15rem 0.45rem;
  margin-right: 0.1rem;
  border-radius: 999px;
  font-size: 0.8rem;
  font-weight: 700;
  text-align: center;
  color: white;
}}
.severity-pill.severity-error {{
  background: var(--error);
}}
.severity-pill.severity-warning {{
  background: var(--warning);
}}
.severity-pill.severity-info {{
  background: var(--info);
}}
.pack-details {{
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 0.75rem 1rem;
  margin-bottom: 1rem;
}}
.pack-details summary {{
  cursor: pointer;
  font-weight: 700;
  margin-bottom: 0.75rem;
}}
.severity-error td {{
  background: rgba(181, 74, 59, 0.10);
}}
.severity-warning td {{
  background: rgba(197, 140, 39, 0.10);
}}
.severity-info td {{
  background: rgba(76, 116, 152, 0.10);
}}
</style>
</head>
<body>
<section class="hero">
  <h1>SG Preflight Report</h1>
  <p class="small"><strong>Bundle:</strong> {escape(report.bundle)}</p>
  <p class="small">Presentation-friendly summary first, with workflow context and handoff guidance before the raw findings.</p>
</section>
<div class="summary">
  <div class="card card-errors"><strong>Errors</strong><div class="card-value">{summary["errors"]}</div></div>
  <div class="card card-warnings"><strong>Warnings</strong><div class="card-value">{summary["warnings"]}</div></div>
  <div class="card card-info"><strong>Info</strong><div class="card-value">{summary["info"]}</div></div>
  <div class="card card-total"><strong>Total</strong><div class="card-value">{summary["total"]}</div></div>
</div>

<section class="section">
<h2>Workflow Context</h2>
<div class="context-grid">
  {context_cards_markup or "<p class='muted'>No workflow context was provided for this run.</p>"}
</div>
</section>

<section class="section">
<h2>Suggested Next Actions</h2>
<div class="action-grid">
  {action_cards_markup or "<p class='muted'>No actions needed.</p>"}
</div>
</section>

<section class="section">
<h2>Pack Highlights</h2>
<div class="pack-grid">
  {pack_cards_markup}
</div>
</section>

<section class="section">
<h2>Pack Summary</h2>
<table>
  <thead>
    <tr>
      <th>Pack</th>
      <th>Errors</th>
      <th>Warnings</th>
      <th>Info</th>
      <th>Total</th>
      <th>Status</th>
    </tr>
  </thead>
  <tbody>
    {pack_table}
  </tbody>
</table>
</section>

<section class="section">
<h2>Grouped Findings</h2>
<table>
  <thead>
    <tr>
      <th>Pack</th>
      <th>Severity</th>
      <th>Code</th>
      <th>Count</th>
      <th>Sample Locations</th>
      <th>Message</th>
      <th>Owner Hint</th>
      <th>Suggested Action</th>
    </tr>
  </thead>
  <tbody>
    {grouped_table}
  </tbody>
</table>
</section>

<section class="section">
<h2>Notable Findings</h2>
{notable_markup}
</section>

<section class="section">
<h2>Full Findings</h2>
{full_sections_markup}
</section>

<section class="section">
<h2>Flat Finding Table</h2>
<details class="pack-details">
  <summary>Open full flat table</summary>
  <table>
    <thead>
      <tr>
        <th>Pack</th>
        <th>Severity</th>
        <th>Code</th>
        <th>Location</th>
        <th>Message</th>
        <th>Details</th>
      </tr>
    </thead>
    <tbody>
      {detail_table}
    </tbody>
  </table>
</details>
</section>
</body>
</html>
"""
    with output_path.open("w", encoding="utf-8") as handle:
        handle.write(html)
