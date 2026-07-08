from __future__ import annotations

import base64
import html
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

PROOF_SCHEMA_VERSION = 1
PROOF_TOOL_LABEL = "Seriengrafik: Project Quality-Hero"
_THUMBNAIL_MAX_WIDTH = 460
_THUMBNAIL_LIMIT = 4

_TONE_BAD_TOKENS = ("fail", "error", "blocked", "missing", "unavailable", "not_found", "violation")
_TONE_WARN_TOKENS = ("warn", "partial", "pending", "not delivered", "not_delivered", "unknown", "stale", "not_run", "incompatible")
_TONE_GOOD_TOKENS = ("available", "ready", "ok", "pass", "delivered", "recorded", "green", "loaded")


def _tone(value: str) -> str:
    lowered = str(value).casefold()
    if any(token in lowered for token in _TONE_BAD_TOKENS):
        return "bad"
    if any(token in lowered for token in _TONE_WARN_TOKENS):
        return "warn"
    if any(token in lowered for token in _TONE_GOOD_TOKENS):
        return "good"
    return "plain"


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _thumbnail_data_uri(image_path: Path) -> str:
    from PIL import Image

    with Image.open(image_path) as image:
        image = image.convert("RGB")
        if image.width > _THUMBNAIL_MAX_WIDTH:
            ratio = _THUMBNAIL_MAX_WIDTH / image.width
            image = image.resize((_THUMBNAIL_MAX_WIDTH, max(1, int(image.height * ratio))))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=72)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


_PROOF_CSS = """
body{margin:0;padding:24px;background:#1e1e1e;color:#d4d4d4;font:14px/1.5 'Segoe UI',system-ui,sans-serif}
h1{font-size:20px;margin:0 0 4px}
h2{font-size:15px;margin:26px 0 6px;color:#e8e8e8;border-bottom:1px solid #333;padding-bottom:4px}
.sub{color:#8a8a8a;font-size:12px;margin-bottom:18px}
.note{color:#a8a8a8;font-size:13px;margin:4px 0 8px}
table{border-collapse:collapse;width:100%;margin:8px 0;font-size:13px}
th{background:#252526;color:#bdbdbd;text-align:left;padding:6px 10px;cursor:pointer;user-select:none;border:1px solid #333;white-space:nowrap}
th:hover{background:#2d2d30}
td{padding:5px 10px;border:1px solid #2a2a2a;vertical-align:top}
tr:nth-child(even) td{background:#232323}
.chip{display:inline-block;padding:1px 9px;border-radius:9px;font-size:12px;white-space:nowrap}
.chip.good{background:#1d3320;color:#89d185}
.chip.warn{background:#3a3117;color:#cca700}
.chip.bad{background:#3a1d1d;color:#f14c4c}
.chip.plain{background:#2d2d30;color:#bdbdbd}
.kv{margin:6px 0}
.kv span{display:inline-block;min-width:250px;color:#8a8a8a}
input.filter{background:#252526;border:1px solid #3a3a3a;color:#d4d4d4;padding:5px 9px;width:320px;border-radius:3px;margin:4px 0}
.gallery{display:flex;flex-wrap:wrap;gap:12px;margin:10px 0}
.gallery figure{margin:0;max-width:470px}
.gallery img{max-width:100%;border:1px solid #3a3a3a;border-radius:3px}
.gallery figcaption{font-size:12px;color:#8a8a8a;margin-top:3px}
footer{margin-top:34px;padding-top:10px;border-top:1px solid #333;color:#6f6f6f;font-size:12px}
footer div{margin:2px 0}
@media print{body{background:#fff;color:#111}}
"""

_PROOF_JS = """
document.querySelectorAll('table.sortable th').forEach(function(th){
  th.addEventListener('click', function(){
    var table = th.closest('table');
    var idx = Array.prototype.indexOf.call(th.parentNode.children, th);
    var rows = Array.prototype.slice.call(table.querySelectorAll('tbody tr'));
    var asc = th.dataset.asc !== 'true';
    th.dataset.asc = asc;
    rows.sort(function(a, b){
      var x = a.children[idx].innerText.trim();
      var y = b.children[idx].innerText.trim();
      var nx = parseFloat(x.replace(/[^0-9.-]/g, ''));
      var ny = parseFloat(y.replace(/[^0-9.-]/g, ''));
      if (!isNaN(nx) && !isNaN(ny) && x !== '' && y !== '') return asc ? nx - ny : ny - nx;
      return asc ? x.localeCompare(y) : y.localeCompare(x);
    });
    rows.forEach(function(r){ table.querySelector('tbody').appendChild(r); });
  });
});
document.querySelectorAll('input.filter').forEach(function(input){
  input.addEventListener('input', function(){
    var needle = input.value.toLowerCase();
    var table = document.getElementById(input.dataset.table);
    if (!table) return;
    table.querySelectorAll('tbody tr').forEach(function(row){
      row.style.display = row.innerText.toLowerCase().indexOf(needle) >= 0 ? '' : 'none';
    });
  });
});
"""


def render_proof_html(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    parts.append(f"<title>{html.escape(str(payload.get('title', 'Evidence report')))}</title>")
    parts.append(f"<style>{_PROOF_CSS}</style>")
    parts.append(f"<h1>{html.escape(str(payload.get('title', '')))}</h1>")
    ticket = str(payload.get("ticket", ""))
    generated = str(payload.get("generated_at_utc", ""))
    parts.append(
        f"<div class='sub'>{html.escape(ticket)} &middot; generated {html.escape(generated)} (UTC) "
        f"&middot; read-only evidence, no verdicts</div>"
    )
    intro = str(payload.get("intro", ""))
    if intro:
        parts.append(f"<div class='note'>{html.escape(intro)}</div>")

    for index, section in enumerate(payload.get("sections", [])):
        parts.append(f"<h2>{html.escape(str(section.get('heading', '')))}</h2>")
        note = str(section.get("note", ""))
        if note:
            parts.append(f"<div class='note'>{html.escape(note)}</div>")
        for label, value in section.get("keyvals", []):
            rendered_value = html.escape(str(value))
            if _tone(str(value)) != "plain":
                rendered_value = f"<span class='chip {_tone(str(value))}'>{rendered_value}</span>"
            parts.append(f"<div class='kv'><span>{html.escape(str(label))}</span>{rendered_value}</div>")
        table = section.get("table")
        if table and table.get("rows"):
            table_id = f"proof-table-{index}"
            columns = list(table.get("columns", []))
            parts.append(
                f"<input class='filter' data-table='{table_id}' placeholder='Filter rows...' type='text'>"
            )
            parts.append(f"<table class='sortable' id='{table_id}'><thead><tr>")
            for column in columns:
                parts.append(f"<th>{html.escape(str(column))}</th>")
            parts.append("</tr></thead><tbody>")
            tone_columns = set(table.get("tone_columns", []))
            for row in table.get("rows", []):
                parts.append("<tr>")
                for column in columns:
                    cell = str(row.get(column, ""))
                    escaped = html.escape(cell)
                    if column in tone_columns and cell:
                        escaped = f"<span class='chip {_tone(cell)}'>{escaped}</span>"
                    parts.append(f"<td>{escaped}</td>")
                parts.append("</tr>")
            parts.append("</tbody></table>")
        pre = str(section.get("pre", ""))
        if pre:
            parts.append(
                "<pre style='background:#252526;border:1px solid #333;padding:12px;overflow-x:auto;"
                f"font-size:12px;line-height:1.45'>{html.escape(pre)}</pre>"
            )
        images = section.get("images", [])
        if images:
            parts.append("<div class='gallery'>")
            for image in images:
                parts.append(
                    "<figure>"
                    f"<img alt='{html.escape(str(image.get('label', '')))}' src='{image.get('data_uri', '')}'>"
                    f"<figcaption>{html.escape(str(image.get('label', '')))}</figcaption>"
                    "</figure>"
                )
            parts.append("</div>")

    provenance = payload.get("provenance", {})
    parts.append("<footer>")
    parts.append(f"<div>Generated by {html.escape(PROOF_TOOL_LABEL)} on {html.escape(generated)} (UTC).</div>")
    for label, value in provenance.items():
        parts.append(f"<div>{html.escape(str(label))}: {html.escape(str(value))}</div>")
    parts.append(
        "<div>This report is generated evidence for manual review; it does not replace reviewer sign-off.</div>"
    )
    parts.append("</footer>")
    parts.append(f"<script>{_PROOF_JS}</script>")
    return "\n".join(parts) + "\n"


def _degraded_section(heading: str, reason: str) -> dict[str, Any]:
    return {
        "heading": heading,
        "note": f"This section could not be generated on this machine: {reason}",
        "keyvals": [("Section status", "unavailable")],
    }


def _delivery_sections(workspace: Path) -> list[dict[str, Any]]:
    from sg_preflight.bmw_delivery import discover_bmw_models_repo
    from sg_preflight.cross_domain_delivery import build_cross_domain_delivery_board

    sections: list[dict[str, Any]] = []
    try:
        bmw_repo = discover_bmw_models_repo(workspace)
        board = build_cross_domain_delivery_board(
            workspace_root=workspace,
            bmw_repo_root=bmw_repo if bmw_repo.exists() else None,
        ).to_dict()
    except Exception as exc:
        return [_degraded_section("Cross-domain delivery state", f"{type(exc).__name__}: {exc}")]
    counts = board.get("counts", {})
    drift = counts.get("version_drift", {})
    basis = drift.get("raco_basis", "max_observed")
    drift_note = (
        "RaCo drift is measured against the versions pinned in the BMW interface_versions.yaml."
        if basis == "pinned"
        else "RaCo drift falls back to the newest version observed across items (no pin file available)."
    )
    sections.append(
        {
            "heading": "Cross-domain delivery state",
            "note": "Live scan of the SG working copy: Cars, Widgets and Ambient CHANGELOG status in one place.",
            "keyvals": [
                ("Source", board.get("repo_root", "")),
                ("Items scanned", counts.get("total", 0)),
                ("Delivered", counts.get("delivered", 0)),
                ("Not delivered yet", counts.get("not_delivered_yet", 0)),
                ("Unknown / no changelog", counts.get("unknown", 0)),
            ],
            "table": {
                "columns": ["Domain", "Brand", "Item", "Status", "Version", "Ramses", "RaCo Headless", "Path"],
                "tone_columns": ["Status"],
                "rows": [
                    {
                        "Domain": entry.get("domain", ""),
                        "Brand": entry.get("brand", ""),
                        "Item": entry.get("item_id", ""),
                        "Status": entry.get("delivery_status_label", entry.get("delivery_status", "")),
                        "Version": entry.get("version", ""),
                        "Ramses": entry.get("ramses", ""),
                        "RaCo Headless": entry.get("raco_headless", ""),
                        "Path": entry.get("relative_path", ""),
                    }
                    for entry in board.get("entries", [])
                ],
            },
        }
    )
    sections.append(
        {
            "heading": "Version drift",
            "note": drift_note,
            "keyvals": [
                ("Drift basis", basis),
                ("Pinned RaCo versions", ", ".join(drift.get("raco_pinned_versions", [])) or "none"),
                ("Ramses drift rows", drift.get("ramses_drift_count", 0)),
                ("RaCo drift rows", drift.get("raco_headless_drift_count", 0)),
            ],
            "table": {
                "columns": ["Domain", "Item", "Ramses", "RaCo Headless", "Path"],
                "rows": [
                    {
                        "Domain": item.get("domain", ""),
                        "Item": item.get("item_id", ""),
                        "Ramses": item.get("ramses", ""),
                        "RaCo Headless": item.get("raco_headless", ""),
                        "Path": item.get("relative_path", ""),
                    }
                    for item in drift.get("items", [])
                ],
            },
        }
    )
    return sections


def _screenshot_sections(workspace: Path, profiles: tuple[str, ...]) -> list[dict[str, Any]]:
    from sg_preflight.bmw_delivery import read_bmw_screenshot_state

    rows: list[dict[str, Any]] = []
    image_entries: list[dict[str, str]] = []
    for profile in profiles:
        try:
            state = read_bmw_screenshot_state(profile, workspace=workspace)
        except Exception as exc:
            rows.append({"Profile": profile, "State": f"error: {type(exc).__name__}"})
            continue
        rows.append(
            {
                "Profile": profile,
                "State": state.get("status", ""),
                "Expected": state.get("expected_count", 0),
                "Actuals": state.get("actual_count", 0),
                "Diffs": state.get("diff_count", 0),
                "Disabled": state.get("disabled_test_count", 0),
                "Tests folder": state.get("export_tests_root", ""),
            }
        )
        if len(image_entries) < _THUMBNAIL_LIMIT:
            actuals_root = str(state.get("actuals_root", ""))
            if actuals_root and Path(actuals_root).exists():
                for png in sorted(Path(actuals_root).glob("*.png"))[: _THUMBNAIL_LIMIT - len(image_entries)]:
                    try:
                        image_entries.append(
                            {
                                "label": f"{profile}: {png.name} (rendered by the BMW screenshot pipeline)",
                                "data_uri": _thumbnail_data_uri(png),
                            }
                        )
                    except Exception:
                        continue
    return [
        {
            "heading": "Screenshot test state per profile",
            "note": (
                "Counts read directly from the BMW models repository test folders. "
                "Diff images stay non-voting under temporal anti-aliasing; a human reviewer stays in charge."
            ),
            "table": {
                "columns": ["Profile", "State", "Expected", "Actuals", "Diffs", "Disabled", "Tests folder"],
                "tone_columns": ["State"],
                "rows": rows,
            },
            "images": image_entries,
        }
    ]


def _digest_sections(workspace: Path) -> list[dict[str, Any]]:
    from sg_preflight.daily_digest import build_latest_daily_digest

    try:
        digest = build_latest_daily_digest(workspace=workspace)
    except Exception as exc:
        return [_degraded_section("Daily digest", f"{type(exc).__name__}: {exc}")]
    sections: list[dict[str, Any]] = [
        {
            "heading": "Daily digest snapshot",
            "note": "The morning summary the tool assembles from the latest local review state.",
            "keyvals": [
                ("Title", digest.get("title", "")),
                ("Date", digest.get("date", "")),
                ("Status", digest.get("status", "")),
                ("Scope", ", ".join(str(item) for item in digest.get("scope", []))),
                ("Summary", digest.get("summary", "")),
            ],
            "pre": str(digest.get("text", "")),
        }
    ]
    guardrails = digest.get("guardrails", [])
    if guardrails:
        sections.append(
            {
                "heading": "Digest guardrails",
                "note": "The digest states its own limits so nobody mistakes it for an approval.",
                "table": {
                    "columns": ["Guardrail"],
                    "rows": [{"Guardrail": str(item)} for item in guardrails],
                },
            }
        )
    return sections


def _manual_review_sections(workspace: Path) -> list[dict[str, Any]]:
    from sg_preflight.services import prerequisite_status

    try:
        payload = prerequisite_status(workspace)
    except Exception as exc:
        return [_degraded_section("Reviewer toolchain readiness", f"{type(exc).__name__}: {exc}")]
    return [
        {
            "heading": "Reviewer toolchain readiness",
            "note": (
                "Path-verified state of every tool a manual RaCo/Blender review depends on, "
                "as detected on this operator machine right now."
            ),
            "table": {
                "columns": ["Check", "Status", "Detail", "Path"],
                "tone_columns": ["Status"],
                "rows": [
                    {
                        "Check": item.get("label", item.get("key", "")),
                        "Status": item.get("status", ""),
                        "Detail": item.get("detail", ""),
                        "Path": item.get("path", ""),
                    }
                    for item in payload
                ],
            },
        }
    ]


def _observability_sections(workspace: Path) -> list[dict[str, Any]]:
    from sg_preflight.activity_log import read_activity_entries

    try:
        activity = read_activity_entries(workspace, limit=30)
        entries = activity.get("entries", []) if isinstance(activity, dict) else list(activity)
    except Exception as exc:
        return [_degraded_section("Operator activity trail", f"{type(exc).__name__}: {exc}")]
    return [
        {
            "heading": "Operator activity trail",
            "note": (
                "The most recent operator-local activity records: every board opened and every check run "
                "leaves a factual, timestamped line. No cloud service is involved."
            ),
            "keyvals": [("Entries shown", len(entries))],
            "table": {
                "columns": ["When", "Action", "Surface", "Profile", "Outcome", "Note"],
                "tone_columns": ["Outcome"],
                "rows": [
                    {
                        "When": entry.get("ts", ""),
                        "Action": entry.get("verb", ""),
                        "Surface": entry.get("surface", ""),
                        "Profile": entry.get("profile", ""),
                        "Outcome": entry.get("outcome", ""),
                        "Note": entry.get("note", ""),
                    }
                    for entry in entries
                ],
            },
        }
    ]


def _demo_sections(workspace: Path) -> list[dict[str, Any]]:
    from sg_preflight.dashboard.main import build_dashboard_snapshot

    try:
        snapshot = build_dashboard_snapshot("G65", workspace)
    except Exception as exc:
        return [_degraded_section("Operator dashboard page inventory", f"{type(exc).__name__}: {exc}")]
    pages = snapshot.get("pages", [])
    return [
        {
            "heading": "Operator dashboard page inventory",
            "note": (
                "Every page of the operator dashboard with its live data state on this machine — "
                "the same surface a walkthrough or demo session exercises."
            ),
            "keyvals": [("Pages", len(pages))],
            "table": {
                "columns": ["Page", "Status", "Summary"],
                "tone_columns": ["Status"],
                "rows": [
                    {
                        "Page": page.get("title", page.get("id", "")),
                        "Status": page.get("status", ""),
                        "Summary": str(page.get("summary", ""))[:160],
                    }
                    for page in pages
                ],
            },
        }
    ]


def _integration_sections(workspace: Path) -> list[dict[str, Any]]:
    from sg_preflight.jira_client import (
        load_jira_credentials,
        redact_jira_credentials,
        verify_jira_access,
    )

    sections: list[dict[str, Any]] = []
    try:
        credentials = load_jira_credentials()
        redacted = redact_jira_credentials(credentials)
        verification = verify_jira_access(credentials=credentials)
        sections.append(
            {
                "heading": "Jira connectivity",
                "note": (
                    "Live verification against the BMW Jira REST API using the operator's personal access "
                    "token. The token itself lives in the operator keychain and never appears in reports."
                ),
                "keyvals": [
                    ("Jira URL", redacted.get("jira_url", "")),
                    ("Token storage", "OS keychain via operator-local registration"),
                    ("Token fingerprint", redacted.get("pat_fingerprint", "")),
                    ("Connection", verification.get("connection", {}).get("status", "")),
                    ("HTTP status", verification.get("connection", {}).get("http_status", "")),
                ],
            }
        )
    except Exception as exc:
        sections.append(_degraded_section("Jira connectivity", f"{type(exc).__name__}: {exc}"))

    from sg_preflight.services import prerequisite_status

    try:
        payload = prerequisite_status(workspace)
        wanted = {
            "bmw_models_repo",
            "bmw_raw_workfiles_repo",
            "widget_shared_lib_repo",
            "bmw_car_manager_script",
            "bmw_test_main_script",
        }
        sections.append(
            {
                "heading": "BMW repository integration",
                "note": "Locally detected BMW-side repositories and pipeline entry points the tool works against.",
                "table": {
                    "columns": ["Integration", "Status", "Path"],
                    "tone_columns": ["Status"],
                    "rows": [
                        {
                            "Integration": item.get("label", ""),
                            "Status": item.get("status", ""),
                            "Path": item.get("path", ""),
                        }
                        for item in payload
                        if item.get("key") in wanted
                    ],
                },
            }
        )
    except Exception as exc:
        sections.append(_degraded_section("BMW repository integration", f"{type(exc).__name__}: {exc}"))
    return sections


PROOF_THEMES: dict[str, tuple[str, Callable[..., list[dict[str, Any]]]]] = {
    "delivery": ("Delivery preflight evidence", lambda workspace, **kw: _delivery_sections(workspace)),
    "screenshots": (
        "Screenshot review evidence",
        lambda workspace, **kw: _screenshot_sections(workspace, tuple(kw.get("profiles") or ("G65",))),
    ),
    "digest": ("Daily QA summary evidence", lambda workspace, **kw: _digest_sections(workspace)),
    "manual-review": ("Manual review support evidence", lambda workspace, **kw: _manual_review_sections(workspace)),
    "observability": ("Operator observability evidence", lambda workspace, **kw: _observability_sections(workspace)),
    "demo": ("Demo validation evidence", lambda workspace, **kw: _demo_sections(workspace)),
    "integration": ("Jira and BMW integration evidence", lambda workspace, **kw: _integration_sections(workspace)),
}


def build_ticket_proof(
    theme: str,
    *,
    ticket: str,
    workspace: Path | str | None = None,
    output_root: Path | str | None = None,
    profiles: tuple[str, ...] = (),
) -> dict[str, Any]:
    if theme not in PROOF_THEMES:
        raise ValueError(f"Unknown proof theme: {theme}. Known: {', '.join(sorted(PROOF_THEMES))}")
    workspace_path = Path(workspace).resolve() if workspace is not None else Path.cwd()
    title, section_builder = PROOF_THEMES[theme]
    sections = section_builder(workspace_path, profiles=profiles)
    generated = _now_utc_iso()
    payload = {
        "schema_version": PROOF_SCHEMA_VERSION,
        "title": title,
        "ticket": ticket,
        "theme": theme,
        "generated_at_utc": generated,
        "intro": (
            "Everything below was collected live from the working copies and pipelines on the "
            "operator machine at the time shown; nothing is mocked or hand-edited."
        ),
        "sections": sections,
        "provenance": {
            "Workspace": str(workspace_path),
            "Theme": theme,
            "Schema version": PROOF_SCHEMA_VERSION,
        },
    }
    result: dict[str, Any] = {"payload": payload}
    if output_root is not None:
        out_dir = Path(output_root)
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = generated.replace(":", "").replace("-", "").replace("T", "-")[:15]
        base = f"{ticket}-{theme}-proof-{stamp}"
        html_path = out_dir / f"{base}.html"
        json_path = out_dir / f"{base}.json"
        html_path.write_text(render_proof_html(payload), encoding="utf-8")
        json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        result["html_path"] = str(html_path)
        result["json_path"] = str(json_path)
    return result
