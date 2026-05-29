"""H-30 consolidated profile dashboard HTML composer.

Builds a self-contained dark-theme HTML page summarising one BMW profile:

- Header: profile id + last successful run timestamp + risk score chip
- Workbook section (from H-27 workbook_finder + classification)
- Active Jira tickets (from H-17 read-only REST search)
- Last N Full QA Pass runs (from H-22 + H-30 list-based history)
- Manual review state summary
- Escalation contacts + Confluence anchors

The page is fully operator-local: no PAT in the HTML, no personal Windows
paths in any cell (`C:\\Users\\<name>\\…` redacted to `~\\…`), no embedded
external resources. All CSS is inlined. PNG thumbnails may be embedded as
base64 (operator flag) or referenced relatively (default — H-32 zip bundles
the PNGs alongside).
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import escape as html_escape
import json
from pathlib import Path
import re
from typing import Any

PROFILE_SUMMARY_SCHEMA_VERSION = 1

# Per [[feedback-team-wording]] — natural prose, no codenames, no overclaim.
GUARDRAILS = (
    "Manual review remains required.",
    "Decision: not approval — evidence only.",
    "BMW Git access is read-only. SGFX never modifies BMW source.",
    "Activity log is local-only — never posted to Jira, SVN, or BMW Git.",
)

ESCALATION_CONTACTS = (
    ("Data prep / CI team", "see the 3D Cars Delivery Checklist Confluence page for current owner + ticket queue"),
    ("Topic Owner", "the per-feature TO recorded in the Jira epic for this profile"),
    ("SGFX tool questions", "Seriengrafik / 3D Car team"),
)

CONFLUENCE_ANCHORS = (
    ("Quality-Hero — How to review the 3D car", "PDX_SERGFX/139_3D-Car/298_Quality-Hero-How-to-review-the-3D-car"),
    ("3D Cars Delivery Checklist v0", "PDX_SERGFX/311_Delivery-process/312_3D-Car---Delivery-and-Integration/315_How-to-3D-Cars-Delivery-Checklist----v0"),
    ("How to screenshottest", "PDX_SERGFX/139_3D-Car/225_3D-Car---RaCo-Implementation/226_How-to-screenshottest"),
    ("SG Daily routine", "PDX_SERGFX/016_Project-Management/024_How-to...-Seriesgraphics/029_Regular-Meetings/030_SG-Daily"),
)


@dataclass(frozen=True)
class ProfileSummary:
    profile_id: str
    generated_at_utc: str
    build_commit: str
    exe_sha256: str
    workbook: dict[str, Any] = field(default_factory=dict)
    risk_score: dict[str, Any] = field(default_factory=dict)
    jira_tickets: dict[str, Any] = field(default_factory=dict)
    full_qa_runs: list[dict[str, Any]] = field(default_factory=list)
    manual_review: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": PROFILE_SUMMARY_SCHEMA_VERSION,
            "profile_id": self.profile_id,
            "generated_at_utc": self.generated_at_utc,
            "build_commit": self.build_commit,
            "exe_sha256": self.exe_sha256,
            "workbook": self.workbook,
            "risk_score": self.risk_score,
            "jira_tickets": self.jira_tickets,
            "full_qa_runs": list(self.full_qa_runs),
            "manual_review": self.manual_review,
            "notes": list(self.notes),
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


_PERSONAL_PATH_RE = re.compile(r"(?i)([A-Z]:\\Users\\)([^\\/]+)")
_PERSONAL_PAT_RE = re.compile(r"\b([A-Za-z0-9_\-]{32,})\b")


def redact_personal_paths(value: str) -> str:
    """Replace `C:\\Users\\<name>\\…` with `C:\\Users\\<operator>\\…` so the HTML
    can travel between machines without leaking the local username."""
    if not value:
        return value
    return _PERSONAL_PATH_RE.sub(r"\1<operator>", value)


def sanitize_text(value: object) -> str:
    """Personal-path + PAT scrub for any operator-facing string before render."""
    text = "" if value is None else str(value)
    text = redact_personal_paths(text)
    # Conservative PAT mask: long alnum runs collapse to ****<last4>.
    def _mask(match: re.Match[str]) -> str:
        token = match.group(1)
        # Don't mask version hashes (40-char git SHA) or .exe SHAs (64 hex chars,
        # all lowercase) — those are legitimate operator-facing identifiers.
        if re.fullmatch(r"[0-9a-f]{40}", token.lower()) or re.fullmatch(r"[0-9a-f]{64}", token.lower()):
            return token
        return f"****{token[-4:]}" if len(token) >= 4 else "****"
    return _PERSONAL_PAT_RE.sub(_mask, text)


def _risk_chip_html(risk: dict[str, Any]) -> str:
    if not isinstance(risk, dict) or risk.get("status") == "unavailable":
        return '<span class="sgfx-chip sgfx-chip-muted">risk unavailable</span>'
    level = str(risk.get("risk_level") or risk.get("level") or "unknown").strip().casefold()
    score = risk.get("risk_score") or risk.get("score")
    score_text = ""
    try:
        if score is not None:
            score_text = f" — {int(score)}"
    except (TypeError, ValueError):
        score_text = ""
    chip_class = "sgfx-chip-muted"
    if level in {"green", "low"}:
        chip_class = "sgfx-chip-green"
    elif level in {"yellow", "medium"}:
        chip_class = "sgfx-chip-yellow"
    elif level in {"red", "high", "critical"}:
        chip_class = "sgfx-chip-red"
    return f'<span class="sgfx-chip {chip_class}">risk {html_escape(level)}{html_escape(score_text)}</span>'


def _workbook_section_html(workbook: dict[str, Any]) -> str:
    if not isinstance(workbook, dict) or workbook.get("status") == "unavailable":
        candidate_count = int(workbook.get("candidate_count") or 0) if isinstance(workbook, dict) else 0
        return (
            '<section class="sgfx-card">'
            '<h2>Delivery workbook</h2>'
            '<p class="sgfx-muted">No size-analysis workbook resolved in any of the documented locations.</p>'
            f'<p class="sgfx-muted">Searched {candidate_count} candidates across SVN + BMW Git + operator-local auto-gen.</p>'
            '<p class="sgfx-muted">Run <code>sgfx-preflight.exe delivery-workbook find --auto-generate</code> '
            'to attempt automatic generation from raw export-size data if available.</p>'
            '</section>'
        )
    selected = workbook.get("selected") if isinstance(workbook.get("selected"), dict) else {}
    classification = str(selected.get("source_classification") or "from_ci")
    workbook_format = str(selected.get("workbook_format") or "unknown")
    path = sanitize_text(selected.get("path", ""))
    mtime_iso = sanitize_text(selected.get("mtime_iso", ""))
    size_bytes = selected.get("size_bytes", 0)
    classification_label = "Auto-generated locally" if classification == "auto_generated_locally" else "From CI"
    return (
        '<section class="sgfx-card">'
        '<h2>Delivery workbook</h2>'
        f'<p class="sgfx-classification sgfx-classification-{html_escape(classification)}">{html_escape(classification_label)}</p>'
        f'<p><strong>Workbook:</strong> <code>{html_escape(path)}</code></p>'
        f'<p class="sgfx-muted">Format: {html_escape(workbook_format)} · mtime: {html_escape(mtime_iso)} · size: {int(size_bytes)} bytes</p>'
        '</section>'
    )


def _jira_section_html(jira: dict[str, Any]) -> str:
    if not isinstance(jira, dict) or jira.get("status") != "available":
        summary = sanitize_text(jira.get("summary", "Jira tickets unavailable.") if isinstance(jira, dict) else "Jira tickets unavailable.")
        return (
            '<section class="sgfx-card">'
            '<h2>Active Jira tickets</h2>'
            f'<p class="sgfx-muted">{html_escape(summary)}</p>'
            '</section>'
        )
    tickets = [t for t in jira.get("tickets", []) if isinstance(t, dict)]
    if not tickets:
        return (
            '<section class="sgfx-card">'
            '<h2>Active Jira tickets</h2>'
            '<p class="sgfx-muted">No open profile-matched tickets returned.</p>'
            '</section>'
        )
    rows: list[str] = []
    for ticket in tickets:
        key = html_escape(sanitize_text(ticket.get("key", "")))
        status = html_escape(sanitize_text(ticket.get("status", "unknown")))
        summary = html_escape(sanitize_text(ticket.get("summary", "")))
        url = ticket.get("url", "")
        key_cell = (
            f'<a href="{html_escape(url)}" target="_blank" rel="noopener noreferrer">{key}</a>'
            if isinstance(url, str) and url
            else key
        )
        rows.append(
            f'<tr><td>{key_cell}</td><td><span class="sgfx-pill">{status}</span></td><td>{summary}</td></tr>'
        )
    return (
        '<section class="sgfx-card">'
        '<h2>Active Jira tickets</h2>'
        '<table class="sgfx-table"><thead><tr><th>Key</th><th>Status</th><th>Summary</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
        '</section>'
    )


def _runs_section_html(runs: list[dict[str, Any]]) -> str:
    if not runs:
        return (
            '<section class="sgfx-card">'
            '<h2>Recent Full QA Pass runs</h2>'
            '<p class="sgfx-muted">No recorded runs yet for this profile.</p>'
            '</section>'
        )
    rows: list[str] = []
    for run in runs:
        ts = html_escape(sanitize_text(run.get("completed_at_utc", "")))
        status = html_escape(sanitize_text(run.get("status", "")))
        summary = html_escape(sanitize_text(run.get("summary", "")))
        passed = int(run.get("passed_steps", 0) or 0)
        incomplete = int(run.get("incomplete_steps", 0) or 0)
        failed = int(run.get("failed_steps", 0) or 0)
        risk_score = run.get("risk_score")
        risk_text = f" · risk {int(risk_score)}" if isinstance(risk_score, (int, float)) else ""
        rows.append(
            f'<tr>'
            f'<td>{ts}</td>'
            f'<td><span class="sgfx-pill">{status}</span></td>'
            f'<td class="sgfx-muted">passed {passed} · incomplete {incomplete} · failed {failed}{html_escape(risk_text)}</td>'
            f'<td class="sgfx-muted">{summary}</td>'
            '</tr>'
        )
    return (
        '<section class="sgfx-card">'
        '<h2>Recent Full QA Pass runs</h2>'
        '<table class="sgfx-table"><thead><tr><th>Completed (UTC)</th><th>Status</th><th>Counts</th><th>Summary</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
        '</section>'
    )


def _manual_review_section_html(manual: dict[str, Any]) -> str:
    if not isinstance(manual, dict) or not manual:
        return (
            '<section class="sgfx-card">'
            '<h2>Manual review</h2>'
            '<p class="sgfx-muted">No manual-review session recorded yet for this profile.</p>'
            '</section>'
        )
    completed = int(manual.get("completed_steps", 0) or 0)
    pending = int(manual.get("pending_steps", 0) or 0)
    flagged = int(manual.get("flagged_steps", 0) or 0)
    started_at = html_escape(sanitize_text(manual.get("started_at_utc", "")))
    last_at = html_escape(sanitize_text(manual.get("updated_at_utc", "")))
    return (
        '<section class="sgfx-card">'
        '<h2>Manual review</h2>'
        f'<p>Completed steps: <strong>{completed}</strong> · Pending: <strong>{pending}</strong> · Flagged: <strong>{flagged}</strong></p>'
        f'<p class="sgfx-muted">Started {started_at} · last update {last_at}</p>'
        '</section>'
    )


def _escalation_section_html() -> str:
    contacts = "".join(
        f'<dt>{html_escape(role)}</dt><dd class="sgfx-muted">{html_escape(detail)}</dd>'
        for role, detail in ESCALATION_CONTACTS
    )
    anchors = "".join(
        f'<li><span class="sgfx-anchor-title">{html_escape(title)}</span>'
        f' <code>{html_escape(anchor)}</code></li>'
        for title, anchor in CONFLUENCE_ANCHORS
    )
    return (
        '<section class="sgfx-card">'
        '<h2>Escalation contacts &amp; Confluence anchors</h2>'
        f'<dl class="sgfx-contacts">{contacts}</dl>'
        f'<ul class="sgfx-anchors">{anchors}</ul>'
        '</section>'
    )


def _guardrails_html() -> str:
    items = "".join(f'<li>{html_escape(line)}</li>' for line in GUARDRAILS)
    return f'<ul class="sgfx-guardrails">{items}</ul>'


def _embedded_css() -> str:
    return """
    :root {
      --sgfx-bg: #1e1e1e;
      --sgfx-bg-elev: #252526;
      --sgfx-bg-card: #2b2b2b;
      --sgfx-border: #3c3c3c;
      --sgfx-fg: #d4d4d4;
      --sgfx-fg-muted: #9da3a8;
      --sgfx-fg-strong: #ececec;
      --sgfx-accent: #4ec9b0;
      --sgfx-yellow: #e8c07d;
      --sgfx-red: #f07f72;
      --sgfx-green: #57d68d;
    }
    html, body { background: var(--sgfx-bg); color: var(--sgfx-fg); font: 14px/1.5 "Segoe UI", "Cascadia Code", Arial, sans-serif; margin: 0; }
    .sgfx-shell { max-width: 960px; margin: 0 auto; padding: 24px; }
    h1 { font-size: 22px; margin: 0 0 4px; color: var(--sgfx-fg-strong); }
    h2 { font-size: 16px; margin: 0 0 8px; color: var(--sgfx-fg-strong); }
    p { margin: 6px 0; }
    code { color: var(--sgfx-accent); background: var(--sgfx-bg-elev); padding: 1px 5px; border-radius: 4px; font-size: 12px; word-break: break-all; }
    a { color: var(--sgfx-accent); }
    .sgfx-meta { color: var(--sgfx-fg-muted); font-size: 12px; }
    .sgfx-card { background: var(--sgfx-bg-card); border: 1px solid var(--sgfx-border); border-radius: 8px; padding: 16px; margin: 12px 0; }
    .sgfx-classification { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px; margin-bottom: 8px; }
    .sgfx-classification-auto_generated_locally { color: var(--sgfx-yellow); border: 1px solid rgba(232,192,125,0.4); background: rgba(232,192,125,0.1); }
    .sgfx-classification-from_ci { color: var(--sgfx-green); border: 1px solid rgba(87,214,141,0.4); background: rgba(87,214,141,0.1); }
    .sgfx-chip { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px; }
    .sgfx-chip-muted { color: var(--sgfx-fg-muted); border: 1px solid var(--sgfx-border); }
    .sgfx-chip-green { color: var(--sgfx-green); border: 1px solid rgba(87,214,141,0.45); background: rgba(87,214,141,0.1); }
    .sgfx-chip-yellow { color: var(--sgfx-yellow); border: 1px solid rgba(232,192,125,0.45); background: rgba(232,192,125,0.1); }
    .sgfx-chip-red { color: var(--sgfx-red); border: 1px solid rgba(240,127,114,0.45); background: rgba(240,127,114,0.1); }
    .sgfx-pill { display: inline-block; padding: 1px 7px; border-radius: 4px; background: var(--sgfx-bg-elev); border: 1px solid var(--sgfx-border); font-size: 11px; color: var(--sgfx-fg-muted); }
    .sgfx-muted { color: var(--sgfx-fg-muted); font-size: 12px; }
    .sgfx-table { width: 100%; border-collapse: collapse; margin-top: 6px; }
    .sgfx-table th, .sgfx-table td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--sgfx-border); font-size: 12px; }
    .sgfx-table th { color: var(--sgfx-fg-muted); font-weight: 600; }
    .sgfx-contacts { margin: 0; }
    .sgfx-contacts dt { color: var(--sgfx-fg-strong); margin-top: 6px; }
    .sgfx-anchors { padding-left: 18px; margin: 8px 0 0; }
    .sgfx-anchors li { margin: 4px 0; }
    .sgfx-anchor-title { color: var(--sgfx-fg-strong); }
    .sgfx-guardrails { padding-left: 18px; margin: 8px 0 0; color: var(--sgfx-fg-muted); font-size: 12px; }
    .sgfx-sparkline { display: inline-block; vertical-align: middle; margin-left: 12px; }
    .sgfx-sparkline-fallback { color: var(--sgfx-fg-muted); font-size: 11px; }
    """


def render_profile_summary_html(
    summary: ProfileSummary,
    *,
    sparkline_svg: str = "",
    sparkline_fallback_text: str = "",
) -> str:
    """Return a fully self-contained dark-theme HTML page for one profile.

    `sparkline_svg` + `sparkline_fallback_text` come from H-31; passing them
    empty here keeps H-30 standalone-usable until H-31 wires the trend signal.
    """
    title = html_escape(f"SGFX profile summary — {summary.profile_id}")
    risk_chip = _risk_chip_html(summary.risk_score)
    if sparkline_svg:
        risk_chip += f'<span class="sgfx-sparkline">{sparkline_svg}</span>'
    elif sparkline_fallback_text:
        risk_chip += (
            f'<span class="sgfx-sparkline-fallback">{html_escape(sparkline_fallback_text)}</span>'
        )
    notes_html = ""
    if summary.notes:
        items = "".join(f"<li>{html_escape(sanitize_text(note))}</li>" for note in summary.notes)
        notes_html = f'<section class="sgfx-card"><h2>Notes</h2><ul>{items}</ul></section>'
    body = (
        f'<header class="sgfx-card">'
        f'<h1>SGFX profile summary — {html_escape(summary.profile_id)}</h1>'
        f'<p>Generated {html_escape(summary.generated_at_utc)} · build {html_escape(summary.build_commit)} · '
        f'.exe SHA <code>{html_escape(summary.exe_sha256)}</code></p>'
        f'<p>{risk_chip}</p>'
        f'</header>'
        f'{_workbook_section_html(summary.workbook)}'
        f'{_jira_section_html(summary.jira_tickets)}'
        f'{_runs_section_html(summary.full_qa_runs)}'
        f'{_manual_review_section_html(summary.manual_review)}'
        f'{notes_html}'
        f'{_escalation_section_html()}'
        f'<footer class="sgfx-card sgfx-meta">'
        f'{_guardrails_html()}'
        f'</footer>'
    )
    return (
        "<!DOCTYPE html>"
        '<html lang="en"><head><meta charset="utf-8">'
        f"<title>{title}</title>"
        f"<style>{_embedded_css()}</style>"
        '</head><body><div class="sgfx-shell">'
        f"{body}"
        "</div></body></html>"
    )


def build_profile_summary(
    profile_id: str,
    *,
    workspace: Path | str,
    bmw_root: Path | str | None = None,
    home: Path | str | None = None,
    history_limit: int = 5,
    build_commit: str = "",
    exe_sha256: str = "",
    jira_max_results: int = 5,
    notes: list[str] | None = None,
) -> ProfileSummary:
    """Compose the data layer for one profile by stitching H-11 / H-17 / H-22 /
    H-26 / H-27 sources together. Operator-local; no PAT crosses any boundary."""
    profile = str(profile_id or "").strip().upper()
    if not profile:
        raise ValueError("profile_id is required")
    workbook_payload: dict[str, Any] = {}
    try:
        from sg_preflight.workbook_finder import resolve_workbook
        resolution = resolve_workbook(profile, workspace=workspace, bmw_root=bmw_root)
        workbook_payload = resolution.to_payload()
    except Exception:
        workbook_payload = {"status": "unavailable", "candidate_count": 0}
    risk_payload: dict[str, Any] = {}
    try:
        from sg_preflight.risk_scoring import read_per_car_risk_score
        risk_payload = read_per_car_risk_score(profile, workspace=Path(workspace))
        if not isinstance(risk_payload, dict):
            risk_payload = {}
    except Exception:
        risk_payload = {}
    jira_payload: dict[str, Any] = {"status": "unavailable", "tickets": []}
    try:
        from sg_preflight.jira_client import search_jira_profile_tickets
        jira_payload = search_jira_profile_tickets(profile, max_results=jira_max_results, timeout_seconds=8)
    except Exception:
        jira_payload = {"status": "unavailable", "tickets": [], "summary": "Jira tickets unavailable."}
    full_qa_runs: list[dict[str, Any]] = []
    try:
        from sg_preflight.full_qa_history import read_full_qa_run_list
        home_path = Path(home).resolve() if home is not None else None
        full_qa_runs = read_full_qa_run_list(profile, home=home_path, limit=history_limit)
    except Exception:
        full_qa_runs = []
    # H-30: manual-review state surfaces via the dashboard wizard today (per H-11);
    # the profile summary defers to "no session recorded" until H-32 / a follow-up
    # exposes a per-profile session reader. Honest empty state, never silent
    # collapse to a passing claim.
    manual_payload: dict[str, Any] = {}
    return ProfileSummary(
        profile_id=profile,
        generated_at_utc=_utc_now(),
        build_commit=str(build_commit or ""),
        exe_sha256=str(exe_sha256 or ""),
        workbook=workbook_payload,
        risk_score=risk_payload,
        jira_tickets=jira_payload,
        full_qa_runs=full_qa_runs,
        manual_review=manual_payload,
        notes=list(notes or []),
    )


def write_profile_summary_html(
    summary: ProfileSummary,
    output_path: Path,
    *,
    sparkline_svg: str = "",
    sparkline_fallback_text: str = "",
) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    html_text = render_profile_summary_html(
        summary,
        sparkline_svg=sparkline_svg,
        sparkline_fallback_text=sparkline_fallback_text,
    )
    output_path.write_text(html_text, encoding="utf-8")
    return output_path
