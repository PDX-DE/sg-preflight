"""Shared dashboard panel-rendering helpers: status tone/chip, Confluence
anchor rendering, tooltip attachment, generic reader-row/page-panel
rendering, the source-root reader panel, first-run/about/changed-profiles
cards, and the clipboard-copy JS helpers every page panel builds on.
"""

from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from sg_preflight.dashboard_pages_config import _payload_items
from sg_preflight.dashboard_preferences import _payload_summary, _source_repo_root_from_value
from sg_preflight.screenshot_review_viewer import compute_diff_delta_badge, compute_diff_regression_badge
from sg_preflight.dashboard.snapshot import DASHBOARD_GUARDRAILS, SETUP_COMPLETE_NOTE
from sg_preflight.status_presentation import (
    BAD_STATUSES,
    GOOD_STATUSES,
    WARN_STATUSES,
    status_label,
    status_tone,
)

DASHBOARD_BRAND_LOGO_ASSET = "logo_sgfx.png"
VERBOSE_TOOLTIP_ENV = "SGFX_DASHBOARD_VERBOSE_TOOLTIPS"
CONFLUENCE_DUMP_SPACE_KEY = "PDX_SERGFX"
CONFLUENCE_DUMP_PREFIX = f"{CONFLUENCE_DUMP_SPACE_KEY}/"
LONG_RUNNING_NOTIFICATION_SECONDS = 30

_STATUS_TONE_BAD_TOKENS = tuple(sorted(BAD_STATUSES))
_STATUS_TONE_WARN_TOKENS = tuple(sorted(WARN_STATUSES))
_STATUS_TONE_GOOD_TOKENS = tuple(sorted(GOOD_STATUSES))


def _status_tone(status: str) -> str:
    return status_tone(status)


def _render_status_chip(ui: Any, status: str) -> None:
    label = status_label(status)
    ui.badge(label).classes(f"sgfx-status sgfx-tone-{_status_tone(status)}")


def _page_confluence_anchors(page: dict[str, Any]) -> list[str]:
    anchors = page.get("confluence_anchors", [])
    if isinstance(anchors, str):
        anchors = [anchors]
    if not isinstance(anchors, list):
        return []
    return [str(anchor).strip() for anchor in anchors if str(anchor).strip()]


def _confluence_dump_root() -> Path:
    return Path(os.environ.get("SGFX_CONFLUENCE_DUMP_ROOT", Path.home() / "Downloads" / "confluence-readable-dumps"))


def _confluence_anchor_relative_path(anchor: str) -> str:
    clean = anchor.strip()
    if ".txt" in clean:
        clean = clean[: clean.index(".txt") + 4]
    elif ":" in clean:
        clean = clean.split(":", 1)[0]
    clean = clean.strip().replace("\\", "/").lstrip("/")
    prefix = CONFLUENCE_DUMP_PREFIX
    if clean and not clean.startswith((prefix, "BMW_3DCar/")):
        clean = prefix + clean
    return clean


def _confluence_anchor_path(anchor: str) -> Path | None:
    relative = _confluence_anchor_relative_path(anchor)
    if not relative:
        return None
    path = (_confluence_dump_root() / relative).resolve()
    return path if path.is_file() else None


def _confluence_anchor_url(anchor: str) -> str:
    path = _confluence_anchor_path(anchor)
    if path is None:
        return ""
    try:
        relative = path.relative_to(_confluence_dump_root().resolve())
    except ValueError:
        return ""
    return "/sgfx-confluence/" + quote(str(relative).replace("\\", "/"), safe="/")


def _render_confluence_anchor(ui: Any, anchor: str) -> None:
    with ui.row().classes("sgfx-doc-link-row"):
        ui.label(f"Confluence anchor: {anchor}").classes("sgfx-muted")
        url = _confluence_anchor_url(anchor)
        if url:
            ui.button(
                "Copy doc link",
                on_click=lambda url=url, anchor=anchor: _copy_dashboard_link_to_clipboard(ui, url, anchor),
            ).props("flat dense no-caps").classes("sgfx-doc-link")
        else:
            ui.label("View doc unavailable").classes("sgfx-muted")


def _image_mime(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".bmp":
        return "image/bmp"
    return "image/png"


def _dashboard_data_uri(path_value: str, *, max_bytes: int = 3_000_000) -> str:
    path = Path(str(path_value or ""))
    if path.suffix.casefold() not in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
        return ""
    if not path.is_file():
        return ""
    try:
        if path.stat().st_size > max_bytes:
            return ""
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return ""
    return f"data:{_image_mime(path)};base64,{encoded}"


def _pipeline_traceback(result: dict[str, Any]) -> dict[str, str]:
    payload = result.get("pipeline_traceback", {})
    if not isinstance(payload, dict) or not bool(payload.get("detected", False)):
        return {}
    summary = str(payload.get("summary", "")).strip()
    details = str(payload.get("technical_details", "")).strip()
    if not summary and not details:
        return {}
    return {"summary": summary, "technical_details": details}


def _screenshot_review_visual_rows(result: dict[str, Any], *, limit: int = 4) -> list[dict[str, str]]:
    rows = result.get("screenshot_review_rows", [])
    if not isinstance(rows, list):
        return []
    profile_id = str(result.get("profile_id", "")).strip()
    visual_rows: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        expected_src = _dashboard_data_uri(str(row.get("expected_path", "")))
        actual_src = _dashboard_data_uri(str(row.get("actual_path", "")))
        diff_path = str(row.get("diff_path", "")).strip()
        diff_src = _dashboard_data_uri(diff_path)
        delta_badge = compute_diff_delta_badge(diff_path)
        regression_badge = compute_diff_regression_badge(
            profile_id,
            diff_path,
            key=str(row.get("key", "") or row.get("label", "")).strip(),
            current=delta_badge,
        )
        if not any((expected_src, actual_src, diff_src)):
            continue
        visual_rows.append(
            {
                "key": str(row.get("key", "") or row.get("label", "")).strip(),
                "label": str(row.get("label", "") or row.get("key", "")).strip(),
                "expected_src": expected_src,
                "actual_src": actual_src,
                "diff_src": diff_src,
                "expected_path": str(row.get("expected_path", "")).strip(),
                "actual_path": str(row.get("actual_path", "")).strip(),
                "diff_path": diff_path,
                "diff_delta_label": delta_badge.label,
                "diff_delta_level": delta_badge.level,
                "diff_regression_label": regression_badge.label,
                "diff_regression_level": regression_badge.level,
            }
        )
        if len(visual_rows) >= limit:
            break
    return visual_rows


def _file_activity_visual_items(result: dict[str, Any], *, limit: int = 4) -> list[dict[str, str]]:
    activity = result.get("file_activity", [])
    if not isinstance(activity, list):
        return []
    items: list[dict[str, str]] = []
    for entry in activity:
        if not isinstance(entry, dict):
            continue
        path = str(entry.get("path", "")).strip()
        data_uri = _dashboard_data_uri(path)
        if not data_uri:
            continue
        relative = str(entry.get("relative_path", Path(path).name)).strip()
        items.append(
            {
                "label": relative or Path(path).name,
                "detail": str(entry.get("summary", "") or entry.get("size_label", "")),
                "src": data_uri,
            }
        )
        if len(items) >= limit:
            break
    return items


def _render_page_confluence_anchors(ui: Any, page: dict[str, Any]) -> None:
    for anchor in _page_confluence_anchors(page):
        _render_confluence_anchor(ui, anchor)


def _dashboard_verbose_tooltips_enabled() -> bool:
    value = os.environ.get(VERBOSE_TOOLTIP_ENV, "").strip().casefold()
    return value not in {"0", "false", "no", "off"}


def _attach_tooltip(ui: Any, element: Any, text: str) -> Any:
    if not text.strip() or not _dashboard_verbose_tooltips_enabled():
        return element
    with element:
        ui.tooltip(text).props("delay=900").classes("sgfx-thinking-tooltip")
    return element


def _render_reader_rows(ui: Any, rows: list[dict[str, str]]) -> None:
    if rows:
        toned_rows = []
        for row in rows:
            status = str(row.get("status", ""))
            toned_rows.append(
                {**row, "status": status_label(status), "status_tone": _status_tone(status)}
            )
        table = ui.table(
            columns=[
                {"name": "label", "label": "Item", "field": "label", "align": "left"},
                {"name": "status", "label": "Status", "field": "status", "align": "left"},
                {"name": "detail", "label": "Detail", "field": "detail", "align": "left"},
            ],
            rows=toned_rows,
            row_key="label",
        ).classes("sgfx-table")
        table.add_slot(
            "body-cell-status",
            '<q-td key="status" :props="props">'
            "<span :class=\"'sgfx-status-cell sgfx-tone-' + (props.row.status_tone || 'neutral')\">"
            "{{ props.value }}</span></q-td>",
        )
        _attach_tooltip(ui, table, "Evidence rows are read from local files only.")
    else:
        ui.label("No rows loaded for this page.").classes("sgfx-muted")


def _reader_rows_from_payload(payload: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "label": str(item.get("label", "")),
            "status": str(item.get("status", "")),
            "detail": str(item.get("detail", "")),
        }
        for item in _payload_items(payload)
        if isinstance(item, dict)
    ]


def _render_source_root_reader_panel(
    ui: Any,
    page: dict[str, Any],
    workspace: Path,
    *,
    bmw_root: Path | str | None = None,
    payload_builder: Callable[..., dict[str, Any]],
) -> None:
    payload = page.get("payload", {}) if isinstance(page.get("payload"), dict) else {}
    selector = page.get("source_selector", {}) if isinstance(page.get("source_selector"), dict) else {}
    selected_source = str(selector.get("selected_source_root") or payload.get("selected_source_root") or "")
    source_candidates = [
        str(candidate)
        for candidate in selector.get("source_root_candidates", payload.get("source_root_candidates", []))
        if str(candidate).strip()
    ]
    with _attach_tooltip(
        ui,
        ui.column().classes("sgfx-page-panel"),
        "Read-only evidence card for the selected local SVN checkout.",
    ):
        with ui.row().classes("items-center justify-between full-width"):
            ui.label(str(page["title"])).classes("sgfx-panel-title")
            _render_status_chip(ui, str(page.get("status", "unknown")))
        ui.label(str(page["tagline"])).classes("sgfx-panel-tagline")
        _render_page_confluence_anchors(ui, page)
        summary_label = ui.label(_strip_standing_disclaimers(str(page.get("summary", "")))).classes("sgfx-summary")
        standing_note = ui.label(_STANDING_PANEL_NOTE).classes("sgfx-muted sgfx-standing-note")
        ownership_note = str(page.get("ownership_note", "")).strip()
        if ownership_note:
            _attach_tooltip(ui, standing_note, ownership_note)
        _render_empty_state_note(ui, page)
        source_input = ui.input(label="SVN trunk root", value=selected_source).classes("full-width")
        source_status = ui.label(f"Reading from: {selected_source or 'auto-discovery'}").classes("sgfx-muted")
        rows_host = ui.column().classes("full-width")
        reload_buttons: list[Any] = []

        def _render_payload_rows(next_payload: dict[str, Any]) -> None:
            rows_host.clear()
            with rows_host:
                _render_reader_rows(ui, _reader_rows_from_payload(next_payload))

        async def _reload() -> None:
            from nicegui import run as nicegui_run

            for button in reload_buttons:
                try:
                    button.disable()
                except Exception:
                    pass
            source_status.text = f"Refreshing from: {source_input.value or 'auto-discovery'}"
            rows_host.clear()
            with rows_host:
                ui.linear_progress(value=0).props("indeterminate").classes("full-width")
                ui.label("Reloading source evidence off the UI event loop...").classes("sgfx-muted")
            try:
                next_payload = await nicegui_run.io_bound(
                    payload_builder,
                    workspace,
                    bmw_root,
                    repo_root=_source_repo_root_from_value(source_input.value),
                )
            except Exception as exc:  # noqa: BLE001
                summary_label.text = f"{page['title']} could not be read: {exc}"
                source_status.text = "Reading from: unavailable"
                rows_host.clear()
                with rows_host:
                    ui.label("No rows loaded for this page.").classes("sgfx-muted")
                return
            finally:
                for button in reload_buttons:
                    try:
                        button.enable()
                    except Exception:
                        pass
            summary_label.text = _strip_standing_disclaimers(
                _payload_summary(next_payload, str(page["title"]), workspace=workspace)
            )
            source_status.text = f"Reading from: {next_payload.get('repo_root', source_input.value)}"
            _render_payload_rows(next_payload)
            ui.notify(f"{page['title']} refreshed.")

        async def _use_source_candidate(value: str) -> None:
            source_input.value = value
            await _reload()

        with ui.row().classes("items-center"):
            reload_button = _attach_tooltip(
                ui,
                ui.button("Reload", on_click=_reload).props("no-caps"),
                "Reload this evidence page from the selected local SVN checkout.",
            )
            reload_buttons.append(reload_button)
            for candidate in source_candidates[:4]:
                label = Path(candidate).name or candidate
                candidate_button = _attach_tooltip(
                    ui,
                    ui.button(label, on_click=lambda value=candidate: _use_source_candidate(value)).props(
                        "flat no-caps"
                    ),
                    f"Use {candidate}",
                )
                reload_buttons.append(candidate_button)
        _render_payload_rows(payload)


_STANDING_DISCLAIMER_RE = re.compile(
    r"\s*Manual review (?:remains|stays) required(?:\s+before any verdict is recorded)?"
    r"[.;]?(?:\s*Decision: not approval\s*[—-]\s*evidence only[.;]?)?(?:\s*this is not an approval[.;]?)?",
    re.IGNORECASE,
)
_STANDING_PANEL_NOTE = "Read-only · Evidence only · Review stays manual"


def _strip_standing_disclaimers(text: str) -> str:
    stripped = _STANDING_DISCLAIMER_RE.sub(" ", str(text or ""))
    return re.sub(r"\s{2,}", " ", stripped).strip()


def _render_page_panel(ui: Any, page: dict[str, Any]) -> None:
    with _attach_tooltip(
        ui,
        ui.column().classes("sgfx-page-panel"),
        "Read-only evidence card for the selected local workspace and profile.",
    ):
        with ui.row().classes("items-center justify-between full-width"):
            title_label = ui.label(str(page["title"])).classes("sgfx-panel-title")
            ownership_note = str(page.get("ownership_note", "")).strip()
            if ownership_note:
                _attach_tooltip(ui, title_label, ownership_note)
            _render_status_chip(ui, str(page.get("status", "unknown")))
        ui.label(str(page["tagline"])).classes("sgfx-panel-tagline")
        _render_page_confluence_anchors(ui, page)
        summary = _strip_standing_disclaimers(str(page.get("summary", "")))
        if summary:
            ui.label(summary).classes("sgfx-summary")
        ui.label(_STANDING_PANEL_NOTE).classes("sgfx-muted sgfx-standing-note")
        _render_empty_state_note(ui, page)
        rows = [
            {
                "label": str(item.get("label", "")),
                "status": str(item.get("status", "")),
                "detail": _strip_standing_disclaimers(str(item.get("detail", ""))),
            }
            for item in page.get("items", [])
            if isinstance(item, dict)
        ]
        _render_reader_rows(ui, rows)


def _render_empty_state_note(ui: Any, page: dict[str, Any]) -> None:
    note = str(page.get("empty_state_note", "")).strip()
    if note:
        ui.label(note).classes("sgfx-warning")


def _render_first_run_welcome(
    ui: Any,
    snapshot: dict[str, Any],
    open_setup: Callable[[], None] | None = None,
    open_full_qa: Callable[[], None] | None = None,
) -> None:
    welcome = snapshot.get("welcome", {})
    if not isinstance(welcome, dict) or not welcome.get("show"):
        return
    with ui.column().classes("sgfx-page-panel sgfx-first-launch-card").props("data-sgfx-first-launch-card=true"):
        with ui.row().classes("items-center justify-between full-width"):
            ui.label(str(welcome.get("title", "Welcome"))).classes("sgfx-panel-title")
            with ui.row().classes("items-center sgfx-first-launch-actions"):
                _render_status_chip(ui, "incomplete")
                ui.html(
                    '<button type="button" class="sgfx-link-button" '
                    'data-sgfx-dismiss-onboarding="true" '
                    'onclick="window.sgfxDismissFirstLaunch && window.sgfxDismissFirstLaunch()">'
                    "Don't show again</button>",
                    sanitize=False,
                )
        ui.label(str(welcome.get("summary", ""))).classes("sgfx-summary")
        with ui.row().classes("sgfx-first-launch-actions"):
            if open_full_qa is not None:
                _attach_tooltip(
                    ui,
                    ui.button("Full QA Pass", on_click=open_full_qa).props("color=primary no-caps dense"),
                    "Open the one-pass wizard for the selected profile.",
                )
            setup_action_count = int(welcome.get("setup_action_count", 0) or 0)
            if open_setup is not None and setup_action_count > 0:
                _attach_tooltip(
                    ui,
                    ui.button("Run setup", on_click=open_setup).props("flat no-caps dense"),
                    "Open dependency setup; no system changes run without confirmation.",
                )
            elif setup_action_count == 0:
                ui.label(str(welcome.get("setup_complete_note", SETUP_COMPLETE_NOTE))).classes("sgfx-muted")


def _render_changed_profiles_card(
    ui: Any,
    snapshot: dict[str, Any],
    *,
    open_batch: Callable[[list[str]], None] | None = None,
) -> None:
    payload = snapshot.get("changed_profiles", {})
    if not isinstance(payload, dict):
        return
    status = str(payload.get("status", "unknown"))
    changed_profiles = [item for item in payload.get("changed_profiles", []) if isinstance(item, dict)]
    changed_ids = [str(item.get("profile_id", "")).strip() for item in changed_profiles if str(item.get("profile_id", "")).strip()]
    with ui.column().classes("sgfx-page-panel sgfx-changed-profiles-card"):
        with ui.row().classes("items-center justify-between full-width"):
            ui.label("Changed since last run").classes("sgfx-panel-title")
            _render_status_chip(ui, "incomplete" if changed_profiles else status)
        if status == "unavailable":
            ui.label("Change-detection unavailable; refresh manually.").classes("sgfx-warning")
            ui.label("Check BMW Git and SVN paths in setup if this persists.").classes("sgfx-muted")
            return
        ui.label(str(payload.get("summary", ""))).classes("sgfx-summary")
        if not changed_profiles:
            ui.label("No profiles changed since the last successful local run.").classes("sgfx-muted")
            return
        rows = [
            {
                "profile": str(item.get("profile_id", "")),
                "last_run": str(item.get("last_qa_pass_at", "")) or "not_run",
                "newest_config": str(item.get("newest_config_mtime", "")) or "unknown",
                "path": str(item.get("newest_config_path", "")),
            }
            for item in changed_profiles[:12]
        ]
        ui.table(
            columns=[
                {"name": "profile", "label": "Profile", "field": "profile", "align": "left"},
                {"name": "last_run", "label": "Last run", "field": "last_run", "align": "left"},
                {"name": "newest_config", "label": "Newest config", "field": "newest_config", "align": "left"},
                {"name": "path", "label": "Path", "field": "path", "align": "left"},
            ],
            rows=rows,
            row_key="profile",
        ).classes("sgfx-table")
        if open_batch is not None and changed_ids:
            _attach_tooltip(
                ui,
                ui.button("Run Full QA Pass on all", on_click=lambda: open_batch(changed_ids)).props("color=primary"),
                "Open the batch Full QA Pass runner with these changed profiles selected.",
            )


def _render_about_panel(ui: Any, content: dict[str, Any] | None = None) -> None:
    if isinstance(content, dict):
        payload = content
    else:
        from sg_preflight.dashboard import main as _main_mod

        payload = _main_mod.ABOUT_CONTENT
    with _attach_tooltip(
        ui,
        ui.column().classes("sgfx-page-panel"),
        "About this local-only preflight surface and its documented evidence anchors.",
    ):
        with ui.row().classes("items-center sgfx-brand-lockup"):
            ui.image(f"/sgfx-dashboard-assets/{DASHBOARD_BRAND_LOGO_ASSET}").classes("sgfx-about-logo")
            ui.label(str(payload.get("heading", "About"))).classes("sgfx-panel-title")
        ui.label(str(payload.get("description", ""))).classes("sgfx-summary")
        ui.label(str(payload.get("version_placeholder", ""))).classes("sgfx-muted")
        anchors = payload.get("confluence_anchors", ())
        if anchors:
            ui.label("Confluence anchors").classes("sgfx-panel-title")
            for label, anchor in anchors:
                ui.label(f"{label} — {anchor}").classes("sgfx-shortcut")
        disclosure_lines = tuple(payload.get("data_handling_disclosure", ()))
        if disclosure_lines:
            ui.label(str(disclosure_lines[0])).classes("sgfx-panel-title")
            for line in disclosure_lines[1:]:
                ui.label(str(line)).classes("sgfx-summary")
        for guardrail in DASHBOARD_GUARDRAILS:
            ui.label(str(guardrail)).classes("sgfx-guardrail")


def _copy_dashboard_text_to_clipboard(ui: Any, text: str, label: str) -> None:
    clean_text = str(text or "").strip()
    clean_label = str(label or "text").strip()
    if not clean_text:
        try:
            ui.notify(f"No text available for {clean_label}.", position="bottom")
        except Exception:
            pass
        return
    try:
        ui.run_javascript(
            """
            (async () => {
              const text = __SGFX_COPY_TEXT__;
              const label = __SGFX_COPY_LABEL__;
              const notify = (message, color) => {
                if (window.Quasar && window.Quasar.Notify && typeof window.Quasar.Notify.create === 'function') {
                  window.Quasar.Notify.create({ message, position: 'bottom', color, timeout: 4500 });
                } else {
                  console.log(message);
                }
              };
              const fallbackCopy = () => {
                const textarea = document.createElement('textarea');
                textarea.value = text;
                textarea.setAttribute('readonly', '');
                textarea.style.position = 'fixed';
                textarea.style.left = '-9999px';
                textarea.style.top = '0';
                document.body.appendChild(textarea);
                textarea.focus();
                textarea.select();
                let copied = false;
                try {
                  copied = document.execCommand('copy');
                } finally {
                  document.body.removeChild(textarea);
                }
                return copied;
              };
              let copied = false;
              let lastError = null;
              try {
                if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
                  await navigator.clipboard.writeText(text);
                  copied = true;
                }
              } catch (err) {
                lastError = err;
                console.warn('navigator.clipboard.writeText failed', err);
              }
              if (!copied) {
                try {
                  copied = fallbackCopy();
                } catch (err) {
                  lastError = err;
                  console.warn('document.execCommand copy fallback failed', err);
                }
              }
              if (copied) {
                notify(`Copied to clipboard: ${label}`, 'positive');
              } else {
                console.warn('clipboard copy failed', lastError);
                notify(`Couldn't copy automatically. Text: ${text}`, 'warning');
              }
            })();
            """.replace("__SGFX_COPY_TEXT__", json.dumps(clean_text)).replace(
                "__SGFX_COPY_LABEL__", json.dumps(clean_label)
            )
        )
    except Exception:
        try:
            ui.notify(f"Couldn't start clipboard copy. Text: {clean_text}", position="bottom")
        except Exception:
            pass


def _copy_dashboard_link_to_clipboard(ui: Any, url: str, label: str) -> None:
    clean_url = str(url or "").strip()
    clean_label = str(label or clean_url or "link").strip()
    if not clean_url:
        try:
            ui.notify(f"No URL available for {clean_label}.", position="bottom")
        except Exception:
            pass
        return
    try:
        ui.run_javascript(
            """
            (async () => {
              const text = __SGFX_COPY_TEXT__;
              const label = __SGFX_COPY_LABEL__;
              const notify = (message, color) => {
                if (window.Quasar && window.Quasar.Notify && typeof window.Quasar.Notify.create === 'function') {
                  window.Quasar.Notify.create({ message, position: 'bottom', color, timeout: 4500 });
                } else {
                  console.log(message);
                }
              };
              const fallbackCopy = () => {
                const textarea = document.createElement('textarea');
                textarea.value = text;
                textarea.setAttribute('readonly', '');
                textarea.style.position = 'fixed';
                textarea.style.left = '-9999px';
                textarea.style.top = '0';
                document.body.appendChild(textarea);
                textarea.focus();
                textarea.select();
                let copied = false;
                try {
                  copied = document.execCommand('copy');
                } finally {
                  document.body.removeChild(textarea);
                }
                return copied;
              };
              let copied = false;
              let lastError = null;
              try {
                if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
                  await navigator.clipboard.writeText(text);
                  copied = true;
                }
              } catch (err) {
                lastError = err;
                console.warn('navigator.clipboard.writeText failed', err);
              }
              if (!copied) {
                try {
                  copied = fallbackCopy();
                } catch (err) {
                  lastError = err;
                  console.warn('document.execCommand copy fallback failed', err);
                }
              }
              if (copied) {
                notify(`Copied to clipboard: ${label}`, 'positive');
              } else {
                console.warn('clipboard copy failed', lastError);
                notify(`Couldn't copy automatically. Link: ${text}`, 'warning');
              }
            })();
            """.replace("__SGFX_COPY_TEXT__", json.dumps(clean_url)).replace(
                "__SGFX_COPY_LABEL__", json.dumps(clean_label)
            )
        )
    except Exception:
        try:
            ui.notify(f"Couldn't start clipboard copy. Link: {clean_url}", position="bottom")
        except Exception:
            pass
