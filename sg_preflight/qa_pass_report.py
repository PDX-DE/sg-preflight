"""Builds the Full QA Pass HTML report and its exportable evidence ZIP, including
screenshot-diff row collection and rendering."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape as html_escape
import json
from pathlib import Path
import re
import shutil
from typing import Any, Callable
import zipfile

from sg_preflight.full_qa_history import read_full_qa_run_list
from sg_preflight.profile_export import (
    ExportManifestEntry,
    _redact_manifest_path,
    _scrub_text_file,
    export_profile_evidence,
)
from sg_preflight.profile_summary import sanitize_text
from sg_preflight.quality_hero_report import _data_uri
from sg_preflight.risk_sparkline import (
    build_sparkline_data,
    render_sparkline_svg,
    sparkline_fallback_text,
)
from sg_preflight.screenshot_review_viewer import (
    compute_diff_delta_badge,
    compute_diff_delta_histogram,
    compute_diff_regression_badge,
)


REPORT_SCHEMA_VERSION = 1
DEFAULT_IMAGE_MAX_BYTES = 1_500_000
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
_JSON_ESCAPED_USER_PATH_RE = re.compile(r"(?i)([A-Z]:\\\\Users\\\\)([^\\\\/]+)")


@dataclass(frozen=True)
class QaPassReportBundle:
    profile_id: str
    html_path: Path
    output_root: Path
    generated_at_utc: str
    screenshot_row_count: int
    dropped_image_notes: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "profile_id": self.profile_id,
            "html_path": str(self.html_path),
            "output_root": str(self.output_root),
            "generated_at_utc": self.generated_at_utc,
            "screenshot_row_count": self.screenshot_row_count,
            "dropped_image_notes": list(self.dropped_image_notes),
        }


@dataclass(frozen=True)
class QaPassReportZipResult:
    profile_id: str
    zip_path: Path
    generated_at_utc: str
    screenshot_row_count: int
    image_count: int
    entries: tuple[ExportManifestEntry, ...] = ()
    dropped_image_notes: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "profile_id": self.profile_id,
            "zip_path": str(self.zip_path),
            "generated_at_utc": self.generated_at_utc,
            "screenshot_row_count": self.screenshot_row_count,
            "image_count": self.image_count,
            "entries": [
                {
                    "archive_name": entry.archive_name,
                    "source_path": _redact_manifest_path(entry.source_path),
                    "bytes": entry.bytes,
                    "sanitized": entry.sanitized,
                }
                for entry in self.entries
            ],
            "dropped_image_notes": list(self.dropped_image_notes),
        }


@dataclass(frozen=True)
class _ImageRef:
    src: str
    note: str = ""


@dataclass(frozen=True)
class _ScreenshotReviewSummary:
    diff_count: int
    row_count: int
    not_rendered_count: int
    not_rendered_reason: str
    detail_text: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clean_profile(profile_id: object) -> str:
    return str(profile_id or "").strip().upper() or "PROFILE"


def _safe_token(value: object, fallback: str = "item") -> str:
    token = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip()).strip("._")
    return token[:120] if token else fallback


def _safe_profile_token(profile_id: str) -> str:
    return _safe_token(profile_id.lower(), "profile")


def _clean_text(value: object) -> str:
    return sanitize_text(value).strip()


def _h(value: object) -> str:
    return html_escape(_clean_text(value), quote=True)


def _scrub_report_text(content: str) -> tuple[str, int]:
    scrubbed, count = _scrub_text_file(content)
    escaped_scrubbed = _JSON_ESCAPED_USER_PATH_RE.sub(r"\1<operator>", scrubbed)
    if escaped_scrubbed != scrubbed:
        count += 1
    return escaped_scrubbed, count


def _int_value(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _as_list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _steps(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for step in _as_list(payload.get("steps")) if isinstance(step, dict)]


def _step_payload(step: dict[str, Any]) -> dict[str, Any]:
    value = step.get("payload", {})
    return value if isinstance(value, dict) else {}


def _step_by_id(payload: dict[str, Any], step_id: str) -> dict[str, Any]:
    for step in _steps(payload):
        if str(step.get("id", "")) == step_id:
            return step
    return {}


def _payloads_with_evidence(payload: dict[str, Any]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = [payload]
    for step in _steps(payload):
        step_payload = _step_payload(step)
        if step_payload:
            payloads.append(step_payload)
        copied = step_payload.get("copied_evidence", {})
        if isinstance(copied, dict):
            payloads.append(copied)
    copied_top = payload.get("copied_evidence", {})
    if isinstance(copied_top, dict):
        payloads.append(copied_top)
    return payloads


def _screenshot_key_candidates(relative_path: Path) -> list[str]:
    normalized = relative_path.as_posix().casefold()
    candidates = [normalized]
    stem = relative_path.stem
    suffix = relative_path.suffix
    suffixes = ("_diff", "-diff", "_color", "-color", "_rgb", "-rgb", "_delta", "-delta", "_mask", "-mask")
    for marker in suffixes:
        if stem.casefold().endswith(marker):
            candidates.append(relative_path.with_name(stem[: -len(marker)] + suffix).as_posix().casefold())
    parts = stem.split("_")
    while len(parts) > 1:
        parts = parts[:-1]
        candidates.append(relative_path.with_name("_".join(parts) + suffix).as_posix().casefold())
    return list(dict.fromkeys(candidates))


def _screenshot_path_lookup(root: Path) -> dict[str, Path]:
    if not root.is_dir():
        return {}
    lookup: dict[str, Path] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            relative = path.relative_to(root).as_posix().casefold()
        except ValueError:
            relative = path.name.casefold()
        lookup[relative] = path
    return lookup


def _matching_screenshot_path(relative_path: Path, lookup: dict[str, Path]) -> Path | None:
    for key in _screenshot_key_candidates(relative_path):
        path = lookup.get(key)
        if path is not None:
            return path
    return None


def _review_row_key(relative_path: Path) -> str:
    for marker in ("_diff", "-diff", "_color", "-color", "_rgb", "-rgb", "_delta", "-delta", "_mask", "-mask"):
        if relative_path.stem.casefold().endswith(marker):
            return relative_path.with_name(relative_path.stem[: -len(marker)] + relative_path.suffix).as_posix()
    return relative_path.as_posix()


def _screenshot_rows_from_output_root(output_root: Path) -> list[dict[str, str]]:
    diff_root = output_root / "diff"
    if not diff_root.is_dir():
        return []
    expected_root = output_root / "expected"
    actuals_root = output_root / "actuals"
    expected_lookup = _screenshot_path_lookup(expected_root)
    actual_lookup = _screenshot_path_lookup(actuals_root)
    rows: list[dict[str, str]] = []
    for diff_path in sorted(diff_root.rglob("*")):
        if not diff_path.is_file():
            continue
        try:
            diff_relative = diff_path.relative_to(diff_root)
        except ValueError:
            diff_relative = Path(diff_path.name)
        expected_path = _matching_screenshot_path(diff_relative, expected_lookup)
        actual_path = _matching_screenshot_path(diff_relative, actual_lookup)
        expected_relative = ""
        actual_relative = ""
        if expected_path is not None:
            try:
                expected_relative = str(Path("expected") / expected_path.relative_to(expected_root)).replace("\\", "/")
            except ValueError:
                expected_relative = str(Path("expected") / expected_path.name).replace("\\", "/")
        if actual_path is not None:
            try:
                actual_relative = str(Path("actuals") / actual_path.relative_to(actuals_root)).replace("\\", "/")
            except ValueError:
                actual_relative = str(Path("actuals") / actual_path.name).replace("\\", "/")
        diff_relative_path = str(Path("diff") / diff_relative).replace("\\", "/")
        key = _review_row_key(diff_relative)
        rows.append(
            {
                "key": key,
                "label": key,
                "expected_path": str(expected_path or ""),
                "actual_path": str(actual_path or ""),
                "diff_path": str(diff_path),
                "expected_relative_path": expected_relative,
                "actual_relative_path": actual_relative,
                "diff_relative_path": diff_relative_path,
            }
        )
    return rows


def collect_screenshot_review_rows(payload: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()

    def append_row(row: dict[str, Any]) -> None:
        normalized = {
            "key": _clean_text(row.get("key") or row.get("label") or ""),
            "label": _clean_text(row.get("label") or row.get("key") or ""),
            "expected_path": str(row.get("expected_path", "") or "").strip(),
            "actual_path": str(row.get("actual_path", "") or "").strip(),
            "diff_path": str(row.get("diff_path", "") or "").strip(),
            "expected_relative_path": _clean_text(row.get("expected_relative_path", "")),
            "actual_relative_path": _clean_text(row.get("actual_relative_path", "")),
            "diff_relative_path": _clean_text(row.get("diff_relative_path", "")),
        }
        key = (
            normalized["key"],
            normalized["expected_path"],
            normalized["actual_path"],
            normalized["diff_path"],
        )
        if key in seen:
            return
        seen.add(key)
        if not normalized["label"]:
            normalized["label"] = normalized["key"] or Path(normalized["diff_path"]).stem or "screenshot diff"
        if not normalized["key"]:
            normalized["key"] = normalized["label"]
        rows.append(normalized)

    for candidate in _payloads_with_evidence(payload):
        raw_rows = candidate.get("screenshot_review_rows", [])
        if not isinstance(raw_rows, list):
            continue
        for row in raw_rows:
            if not isinstance(row, dict):
                continue
            append_row(row)
    target_count = _authoritative_screenshot_diff_count(payload)
    if target_count <= len(rows):
        return rows
    scanned_roots: set[Path] = set()
    for candidate in _payloads_with_evidence(payload):
        root_value = str(candidate.get("sgfx_output_root") or candidate.get("output_root") or "").strip()
        if not root_value:
            continue
        output_root = Path(root_value)
        try:
            resolved_root = output_root.resolve()
        except OSError:
            resolved_root = output_root
        if resolved_root in scanned_roots:
            continue
        scanned_roots.add(resolved_root)
        for row in _screenshot_rows_from_output_root(output_root):
            append_row(row)
            if len(rows) >= target_count:
                break
        if len(rows) >= target_count:
            break
    return rows


def _authoritative_screenshot_diff_count(payload: dict[str, Any]) -> int:
    for candidate in _payloads_with_evidence(payload):
        diff_count = _int_value(candidate.get("diff_count"))
        if diff_count:
            return diff_count
    return 0


def _screenshot_diff_count(payload: dict[str, Any], rows: list[dict[str, str]]) -> int:
    return _authoritative_screenshot_diff_count(payload) or len(rows)


def _screenshot_gap_reason(payload: dict[str, Any]) -> str:
    for candidate in _payloads_with_evidence(payload):
        reason = _clean_text(
            candidate.get("screenshot_review_rows_omitted_reason")
            or candidate.get("screenshot_review_rows_gap_reason")
            or candidate.get("not_rendered_reason")
            or ""
        )
        if reason:
            return reason
        omitted = _int_value(candidate.get("screenshot_review_rows_omitted"))
        limit = _int_value(candidate.get("screenshot_review_row_limit"))
        if omitted:
            if limit:
                return f"the screenshot row collector attached only the first {limit} rows"
            return "the screenshot row collector omitted rows from the payload"
    return "the report payload contained fewer screenshot review rows than the authoritative diff count"


def _screenshot_review_summary(payload: dict[str, Any], rows: list[dict[str, str]]) -> _ScreenshotReviewSummary:
    diff_count = _screenshot_diff_count(payload, rows)
    row_count = len(rows)
    not_rendered = max(0, diff_count - row_count)
    reason = _screenshot_gap_reason(payload) if not_rendered else ""
    if not_rendered:
        detail = (
            f"{diff_count} differences - {row_count} shown side-by-side - "
            f"{not_rendered} not rendered ({reason})"
        )
    elif diff_count:
        detail = f"{diff_count} differences - {row_count} shown side-by-side"
    else:
        detail = "No screenshot differences were attached"
    return _ScreenshotReviewSummary(
        diff_count=diff_count,
        row_count=row_count,
        not_rendered_count=not_rendered,
        not_rendered_reason=reason,
        detail_text=detail,
    )


def _risk_payload(payload: dict[str, Any]) -> dict[str, Any]:
    step = _step_by_id(payload, "risk-score")
    risk_payload = _step_payload(step)
    if risk_payload:
        return risk_payload
    top = payload.get("risk_score", {})
    return top if isinstance(top, dict) else {}


def _risk_score_and_level(payload: dict[str, Any]) -> tuple[int | None, str]:
    risk = _risk_payload(payload)
    raw_score = risk.get("risk_score", risk.get("score"))
    score: int | None
    try:
        score = int(raw_score) if raw_score is not None and raw_score != "" else None
    except (TypeError, ValueError):
        score = None
    if score is not None:
        score = max(0, min(100, score))
    level = _clean_text(risk.get("risk_level") or risk.get("level") or "unknown").casefold()
    return score, level or "unknown"


def _manual_review_payload(payload: dict[str, Any]) -> dict[str, Any]:
    step = _step_by_id(payload, "manual-review-assist")
    return _step_payload(step)


def _manual_review_item_count(payload: dict[str, Any]) -> int:
    manual = _manual_review_payload(payload)
    focus = [item for item in _as_list(manual.get("operator_focus_steps")) if str(item).strip()]
    if focus:
        return len(focus)
    manual_steps = [step for step in _as_list(manual.get("steps")) if isinstance(step, dict)]
    if manual_steps:
        return sum(1 for step in manual_steps if str(step.get("suggested_verdict", "")).strip() != "passed")
    confirmations = [item for item in _as_list(payload.get("confirmation_items")) if isinstance(item, dict)]
    return len(confirmations)


def build_qa_pass_report_summary(payload: dict[str, Any]) -> dict[str, Any]:
    profile = _clean_profile(payload.get("profile_id"))
    steps = _steps(payload)
    counts = payload.get("counts", {}) if isinstance(payload.get("counts"), dict) else {}
    passed_count = _int_value(counts.get("passed"))
    if not passed_count and steps:
        passed_count = sum(1 for step in steps if str(step.get("status", "")).strip() == "passed")
    total_steps = len(steps) or _int_value((payload.get("progress") or {}).get("total_steps") if isinstance(payload.get("progress"), dict) else 0)
    rows = collect_screenshot_review_rows(payload)
    screenshot_summary = _screenshot_review_summary(payload, rows)
    manual_count = _manual_review_item_count(payload)
    risk_score, risk_level = _risk_score_and_level(payload)
    hero_text = (
        f"{profile} - {passed_count} checks passed - "
        f"{screenshot_summary.detail_text} + {manual_count} manual items need your review"
    )
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "profile_id": profile,
        "passed_count": passed_count,
        "total_steps": total_steps,
        "screenshot_diff_count": screenshot_summary.diff_count,
        "screenshot_row_count": screenshot_summary.row_count,
        "screenshot_not_rendered_count": screenshot_summary.not_rendered_count,
        "screenshot_not_rendered_reason": screenshot_summary.not_rendered_reason,
        "screenshot_review_detail": screenshot_summary.detail_text,
        "manual_review_item_count": manual_count,
        "risk_score": risk_score,
        "risk_level": risk_level,
        "status": _clean_text(payload.get("status") or payload.get("run_status") or "unknown"),
        "summary": _clean_text(payload.get("summary", "")),
        "hero_text": hero_text,
        "manual_review_required": bool(payload.get("manual_review_required", True)),
        "is_approval": False,
    }


def _size_label(size: int) -> str:
    if size >= 1_000_000:
        return f"{size / 1_000_000:.1f} MB"
    if size >= 1_000:
        return f"{size / 1_000:.1f} KB"
    return f"{size} B"


def _path_if_image(path_value: str) -> Path | None:
    path_text = str(path_value or "").strip()
    if not path_text:
        return None
    path = Path(path_text)
    if path.suffix.casefold() not in _IMAGE_SUFFIXES or not path.is_file():
        return None
    return path


def _dashboard_asset_ref(path: Path, *, output_root: Path, role: str, index: int, key: str) -> _ImageRef:
    asset_dir = output_root / "assets" / "screenshot-diffs"
    asset_dir.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix if path.suffix else ".png"
    name = f"{index:03d}-{role}-{_safe_token(key, 'screenshot')}{suffix.casefold()}"
    destination = asset_dir / name
    try:
        shutil.copy2(path, destination)
    except OSError as exc:
        return _ImageRef("", f"{role} image unavailable: {path.name} ({exc})")
    return _ImageRef(f"assets/screenshot-diffs/{destination.name}")


def _export_asset_ref(path: Path, *, max_bytes: int, role: str) -> _ImageRef:
    try:
        size = path.stat().st_size
    except OSError as exc:
        return _ImageRef("", f"{role} image unavailable: {path.name} ({exc})")
    if size > max_bytes:
        return _ImageRef("", f"{role} image skipped: {path.name} is {_size_label(size)}, over the per-image cap of {_size_label(max_bytes)}.")
    uri = _data_uri(str(path), max_bytes=max_bytes)
    if not uri:
        return _ImageRef("", f"{role} image unavailable: {path.name}")
    return _ImageRef(uri)


def _image_ref(
    path_value: str,
    *,
    mode: str,
    output_root: Path | None,
    image_max_bytes: int,
    role: str,
    index: int,
    key: str,
) -> _ImageRef:
    path = _path_if_image(path_value)
    if path is None:
        return _ImageRef("", f"{role} image missing")
    if mode == "dashboard" and output_root is not None:
        return _dashboard_asset_ref(path, output_root=output_root, role=role, index=index, key=key)
    return _export_asset_ref(path, max_bytes=image_max_bytes, role=role)


def _axis_histogram_html(axis: Any, *, label: str) -> str:
    bins = tuple(getattr(axis, "bins", ()) or ())
    if not bins:
        return ""
    max_value = max(bins) or 1
    stride = max(1, len(bins) // 48)
    sampled = bins[::stride][:48]
    bars = "".join(
        f'<span style="height:{max(4, int((value / max_value) * 100))}%"></span>'
        for value in sampled
    )
    peak = _h(getattr(axis, "peak_label", "") or "")
    return (
        f'<div class="sgfx-histogram-axis">'
        f'<span>{html_escape(label)}</span><div class="sgfx-histogram-bars">{bars}</div>'
        f'<em>{peak}</em></div>'
    )


def _histogram_html(diff_path: str) -> str:
    if not diff_path:
        return ""
    histogram = compute_diff_delta_histogram(diff_path, max_bins=48)
    if histogram.status != "available":
        return ""
    changed = ""
    if histogram.changed_pixel_ratio is not None:
        changed = f"{histogram.changed_pixel_ratio * 100:.2f}% changed pixels"
    axes = "".join(
        item
        for item in (
            _axis_histogram_html(histogram.x_axis, label="X"),
            _axis_histogram_html(histogram.y_axis, label="Y"),
        )
        if item
    )
    if not axes:
        return ""
    return f'<div class="sgfx-histogram"><strong>{html_escape(changed)}</strong>{axes}</div>'


def _enriched_screenshot_rows(
    payload: dict[str, Any],
    *,
    mode: str,
    output_root: Path | None,
    image_max_bytes: int,
) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    profile = _clean_profile(payload.get("profile_id"))
    enriched: list[dict[str, Any]] = []
    dropped_notes: list[str] = []
    for index, row in enumerate(collect_screenshot_review_rows(payload), start=1):
        key = row["key"] or row["label"] or f"screenshot-{index}"
        expected = _image_ref(
            row.get("expected_path", ""),
            mode=mode,
            output_root=output_root,
            image_max_bytes=image_max_bytes,
            role="expected",
            index=index,
            key=key,
        )
        actual = _image_ref(
            row.get("actual_path", ""),
            mode=mode,
            output_root=output_root,
            image_max_bytes=image_max_bytes,
            role="actual",
            index=index,
            key=key,
        )
        diff = _image_ref(
            row.get("diff_path", ""),
            mode=mode,
            output_root=output_root,
            image_max_bytes=image_max_bytes,
            role="diff",
            index=index,
            key=key,
        )
        for note in (expected.note, actual.note, diff.note):
            if note:
                dropped_notes.append(f"{row['label']}: {note}")
        delta_badge = compute_diff_delta_badge(row.get("diff_path", ""))
        regression_badge = compute_diff_regression_badge(
            profile,
            row.get("diff_path", ""),
            key=key,
            current=delta_badge,
        )
        enriched.append(
            {
                **row,
                "index": index,
                "expected_src": expected.src,
                "actual_src": actual.src,
                "diff_src": diff.src,
                "diff_delta_label": delta_badge.label,
                "diff_delta_level": delta_badge.level,
                "diff_regression_label": regression_badge.label,
                "diff_regression_level": regression_badge.level,
                "histogram_html": _histogram_html(row.get("diff_path", "")),
            }
        )
    return enriched, tuple(dropped_notes)


def _risk_gauge_svg(score: int | None, level: str) -> str:
    if score is None:
        return (
            '<svg class="sgfx-risk-gauge" viewBox="0 0 140 86" role="img" aria-label="Risk score unavailable">'
            '<path class="gauge-track" d="M20 70 A50 50 0 0 1 120 70"></path>'
            '<text x="70" y="58" text-anchor="middle">n/a</text>'
            '<text x="70" y="76" text-anchor="middle">risk unavailable</text>'
            '</svg>'
        )
    score = max(0, min(100, int(score)))
    dash = 157
    offset = dash - int(dash * (score / 100))
    level_class = "high" if score >= 60 else "medium" if score >= 30 else "low"
    label = f"Risk {score}/100, {level or level_class}"
    return (
        f'<svg class="sgfx-risk-gauge sgfx-risk-{level_class}" viewBox="0 0 140 86" role="img" aria-label="{html_escape(label)}">'
        '<path class="gauge-track" d="M20 70 A50 50 0 0 1 120 70"></path>'
        f'<path class="gauge-value" d="M20 70 A50 50 0 0 1 120 70" stroke-dasharray="{dash}" stroke-dashoffset="{offset}"></path>'
        f'<text x="70" y="54" text-anchor="middle">{score}</text>'
        f'<text x="70" y="76" text-anchor="middle">{_h(level or level_class)}</text>'
        '</svg>'
    )


def _sparkline_html(profile_id: str, *, run_history: list[dict[str, Any]] | None, home: Path | None) -> str:
    runs = run_history if run_history is not None else read_full_qa_run_list(profile_id, home=home)
    data = build_sparkline_data(runs, profile_id=profile_id)
    svg = render_sparkline_svg(data, width=150, height=28)
    if svg:
        return f'<div class="sgfx-trend"><span>Risk trend</span>{svg}</div>'
    return f'<div class="sgfx-trend sgfx-trend-muted"><span>Risk trend</span><em>{_h(sparkline_fallback_text(data))}</em></div>'


def _field_value(row: dict[str, Any], names: tuple[str, ...], fallback: str = "") -> str:
    for name in names:
        value = row.get(name)
        if value is not None and str(value).strip():
            return _clean_text(value)
    return fallback


def _table_html(title: str, columns: tuple[tuple[str, tuple[str, ...]], ...], rows: list[dict[str, Any]], *, empty: str) -> str:
    if not rows:
        return (
            f'<section class="sgfx-section"><h2>{html_escape(title)}</h2>'
            f'<p class="sgfx-muted">{html_escape(empty)}</p></section>'
        )
    header = "".join(
        f'<th><button type="button" data-sort-key="{index}">{html_escape(label)}</button></th>'
        for index, (label, _keys) in enumerate(columns)
    )
    body_rows: list[str] = []
    for row in rows:
        cells = []
        for _label, keys in columns:
            cells.append(f"<td>{_h(_field_value(row, keys))}</td>")
        body_rows.append(f"<tr>{''.join(cells)}</tr>")
    return (
        f'<section class="sgfx-section"><h2>{html_escape(title)}</h2>'
        '<div class="sgfx-table-wrap"><table data-sortable-table="true">'
        f"<thead><tr>{header}</tr></thead><tbody>{''.join(body_rows)}</tbody></table></div></section>"
    )


def _rows_from_payload(payload: dict[str, Any], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = value.get("items") or value.get("tickets") or value.get("checks") or value.get("entries")
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
    return []


def _delivery_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for step_id in ("delivery-readiness", "delivery-checklist", "delivery-workbook-trigger"):
        step = _step_by_id(payload, step_id)
        if not step:
            continue
        step_payload = _step_payload(step)
        extracted = _rows_from_payload(step_payload, ("checks", "items", "entries", "delivery_checks"))
        if extracted:
            rows.extend(extracted[:12])
        else:
            rows.append(
                {
                    "label": step.get("label", step_id),
                    "status": step.get("status", step_payload.get("status", "")),
                    "detail": step.get("summary", step_payload.get("summary", "")),
                }
            )
    return rows


def _jira_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for candidate in [payload, *[_step_payload(step) for step in _steps(payload)]]:
        rows.extend(_rows_from_payload(candidate, ("tickets", "jira_tickets", "my_tickets")))
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = _field_value(row, ("key", "ticket_id", "id", "summary"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique[:25]


def _risk_signal_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return _rows_from_payload(_risk_payload(payload), ("signals",))[:25]


def _disabled_test_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for step in _steps(payload):
        step_payload = _step_payload(step)
        if "disabled" not in str(step.get("id", "")).casefold() and "disabled" not in str(step.get("label", "")).casefold():
            continue
        rows.extend(_rows_from_payload(step_payload, ("disabled_tests", "items", "entries")))
        count = _int_value(step_payload.get("disabled_call_total") or step_payload.get("disabled_count"))
        if count and not rows:
            rows.append(
                {
                    "label": step.get("label", "Disabled tests"),
                    "status": step_payload.get("status", step.get("status", "")),
                    "detail": f"{count} disabled test call(s) found.",
                }
            )
    if not rows:
        risk = _risk_payload(payload)
        current = risk.get("current_snapshot", {}) if isinstance(risk.get("current_snapshot"), dict) else {}
        count = _int_value(current.get("disabled_test_count"))
        if count:
            rows.append({"label": "Current snapshot", "status": "review", "detail": f"{count} disabled test(s) in config."})
    return rows[:25]


def _manual_review_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    manual = _manual_review_payload(payload)
    rows = [step for step in _as_list(manual.get("steps")) if isinstance(step, dict)]
    if rows:
        return rows
    focus = [str(item).strip() for item in _as_list(manual.get("operator_focus_steps")) if str(item).strip()]
    return [{"title": item, "suggested_verdict": "incomplete", "suggestion_reason": "Operator focus is still required."} for item in focus]


def _summary_step_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "label": step.get("label", ""),
            "status": step.get("status", ""),
            "detail": step.get("summary", ""),
        }
        for step in _steps(payload)
    ]


def _image_slot_html(label: str, src: str) -> str:
    if not src:
        return f'<div class="sgfx-image-pane sgfx-image-missing"><strong>{html_escape(label)}</strong><span>missing</span></div>'
    return (
        f'<div class="sgfx-image-pane"><strong>{html_escape(label)}</strong>'
        f'<div class="sgfx-image-viewport"><img src="{html_escape(src, quote=True)}" alt="{html_escape(label)} screenshot"></div></div>'
    )


def _screenshot_gap_note_html(summary: dict[str, Any]) -> str:
    not_rendered = _int_value(summary.get("screenshot_not_rendered_count"))
    if not not_rendered:
        return ""
    return (
        '<div class="sgfx-visible-note" data-sgfx-diff-gap="true">'
        "<strong>Screenshot row gap</strong>"
        f"<p>{_h(summary.get('screenshot_review_detail'))}</p>"
        "</div>"
    )


def _screenshot_section(rows: list[dict[str, Any]], dropped_notes: tuple[str, ...], summary: dict[str, Any]) -> str:
    detail = _clean_text(summary.get("screenshot_review_detail")) or "No screenshot differences were attached"
    gap_note = _screenshot_gap_note_html(summary)
    notes = ""
    if dropped_notes:
        items = "".join(f"<li>{_h(note)}</li>" for note in dropped_notes[:30])
        more = ""
        if len(dropped_notes) > 30:
            more = f"<li>{len(dropped_notes) - 30} additional image note(s) omitted from this view.</li>"
        notes = f'<div class="sgfx-visible-note"><strong>Image notes</strong><ul>{items}{more}</ul></div>'
    if not rows:
        return (
            '<section class="sgfx-section sgfx-screenshot-review" id="screenshots">'
            "<h2>Screenshot review</h2>"
            f'<p class="sgfx-muted">{_h(detail)}</p>'
            f"{gap_note}{notes}</section>"
        )
    cards: list[str] = []
    for row in rows:
        delta = ""
        if row.get("diff_delta_label"):
            level = _safe_token(row.get("diff_delta_level"), "unknown")
            delta = f'<span class="sgfx-badge sgfx-delta-{level}">{_h(row.get("diff_delta_label"))}</span>'
        regression = ""
        if row.get("diff_regression_label"):
            level = _safe_token(row.get("diff_regression_level"), "unknown")
            regression = f'<span class="sgfx-badge sgfx-regression-{level}">{_h(row.get("diff_regression_label"))}</span>'
        cards.append(
            '<article class="sgfx-diff-card" data-sgfx-diff-row="true" '
            f'data-key="{_h(row.get("key"))}">'
            '<div class="sgfx-diff-card-head">'
            f'<h3>{_h(row.get("label") or row.get("key"))}</h3><div>{delta}{regression}</div>'
            '</div>'
            '<div class="sgfx-image-grid">'
            f'{_image_slot_html("Expected", str(row.get("expected_src", "")))}'
            f'{_image_slot_html("Actual", str(row.get("actual_src", "")))}'
            f'{_image_slot_html("Diff", str(row.get("diff_src", "")))}'
            '</div>'
            f'{row.get("histogram_html", "")}'
            '</article>'
        )
    return (
        '<section class="sgfx-section sgfx-screenshot-review" id="screenshots">'
        '<div class="sgfx-section-head"><div><h2>Screenshot review</h2>'
        f"<p>{_h(detail)}</p></div>"
        '<label class="sgfx-zoom-control" for="sgfx-zoom">Zoom '
        '<input id="sgfx-zoom" type="range" min="25" max="400" value="100" step="5">'
        '<span id="sgfx-zoom-value">100%</span></label></div>'
        f"{gap_note}{notes}{''.join(cards)}</section>"
    )


def _css() -> str:
    return """
    :root {
      color-scheme: dark;
      --sgfx-bg: #111315;
      --sgfx-panel: #191d21;
      --sgfx-panel-2: #20262b;
      --sgfx-border: #34404a;
      --sgfx-text: #edf2f5;
      --sgfx-muted: #aab5bd;
      --sgfx-green: #57d68d;
      --sgfx-yellow: #e8c07d;
      --sgfx-red: #f07f72;
      --sgfx-blue: #7bb7ff;
      --sgfx-zoom: 1;
    }
    * { box-sizing: border-box; }
    body { margin: 0; background: var(--sgfx-bg); color: var(--sgfx-text); font: 14px/1.5 "Segoe UI", Arial, sans-serif; }
    a { color: var(--sgfx-blue); }
    .sgfx-page { max-width: 1520px; margin: 0 auto; padding: 28px; }
    .sgfx-hero { display: grid; grid-template-columns: minmax(0, 1fr) 220px; gap: 20px; align-items: center; padding: 24px; background: var(--sgfx-panel); border: 1px solid var(--sgfx-border); border-radius: 8px; }
    .sgfx-hero h1 { margin: 0 0 10px; font-size: 30px; line-height: 1.15; letter-spacing: 0; }
    .sgfx-hero p { margin: 0; color: var(--sgfx-muted); }
    .sgfx-hero-stats { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }
    .sgfx-stat { min-width: 120px; padding: 10px 12px; background: var(--sgfx-panel-2); border: 1px solid var(--sgfx-border); border-radius: 8px; }
    .sgfx-stat strong { display: block; font-size: 22px; }
    .sgfx-stat span { color: var(--sgfx-muted); font-size: 12px; }
    .sgfx-risk-gauge { width: 180px; max-width: 100%; }
    .sgfx-risk-gauge path { fill: none; stroke-width: 12; stroke-linecap: round; }
    .gauge-track { stroke: #303842; }
    .gauge-value { stroke: var(--sgfx-green); }
    .sgfx-risk-medium .gauge-value { stroke: var(--sgfx-yellow); }
    .sgfx-risk-high .gauge-value { stroke: var(--sgfx-red); }
    .sgfx-risk-gauge text { fill: var(--sgfx-text); font-weight: 700; font-size: 18px; }
    .sgfx-risk-gauge text:last-child { fill: var(--sgfx-muted); font-weight: 500; font-size: 10px; text-transform: uppercase; }
    .sgfx-trend { display: flex; align-items: center; gap: 10px; margin-top: 10px; color: var(--sgfx-muted); }
    .sgfx-trend svg { background: #15191d; border: 1px solid var(--sgfx-border); border-radius: 6px; padding: 3px; }
    .sgfx-section { margin-top: 18px; padding: 20px; background: var(--sgfx-panel); border: 1px solid var(--sgfx-border); border-radius: 8px; }
    .sgfx-section h2 { margin: 0 0 12px; font-size: 20px; letter-spacing: 0; }
    .sgfx-section-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 14px; }
    .sgfx-section-head p { margin: 4px 0 0; color: var(--sgfx-muted); }
    .sgfx-muted { color: var(--sgfx-muted); }
    .sgfx-visible-note { border: 1px solid #655934; background: #2a2518; border-radius: 8px; padding: 12px; margin-bottom: 14px; color: #f0d69a; }
    .sgfx-visible-note ul { margin: 8px 0 0; padding-left: 20px; }
    .sgfx-zoom-control { display: flex; align-items: center; gap: 8px; color: var(--sgfx-muted); white-space: nowrap; }
    .sgfx-zoom-control input { width: 180px; }
    .sgfx-diff-card { border: 1px solid var(--sgfx-border); background: #15191d; border-radius: 8px; padding: 14px; margin-top: 14px; }
    .sgfx-diff-card-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
    .sgfx-diff-card h3 { margin: 0; font-size: 16px; overflow-wrap: anywhere; }
    .sgfx-badge { display: inline-flex; align-items: center; margin-left: 8px; padding: 4px 8px; border: 1px solid var(--sgfx-border); border-radius: 999px; color: var(--sgfx-muted); font-size: 12px; }
    .sgfx-delta-green, .sgfx-regression-green, .sgfx-regression-stable { color: var(--sgfx-green); }
    .sgfx-delta-yellow, .sgfx-regression-yellow, .sgfx-regression-watch { color: var(--sgfx-yellow); }
    .sgfx-delta-red, .sgfx-regression-red, .sgfx-regression-regressed { color: var(--sgfx-red); }
    .sgfx-image-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
    .sgfx-image-pane { min-width: 0; }
    .sgfx-image-pane strong { display: block; margin-bottom: 6px; color: var(--sgfx-muted); font-size: 12px; text-transform: uppercase; }
    .sgfx-image-viewport { height: 280px; overflow: auto; border: 1px solid var(--sgfx-border); border-radius: 6px; background: #0b0d0f; cursor: grab; }
    .sgfx-image-viewport.dragging { cursor: grabbing; }
    .sgfx-image-viewport img { display: block; width: calc(100% * var(--sgfx-zoom)); max-width: none; image-rendering: auto; }
    .sgfx-image-missing { display: grid; place-items: center; min-height: 280px; border: 1px dashed var(--sgfx-border); border-radius: 6px; color: var(--sgfx-muted); }
    .sgfx-histogram { margin-top: 12px; padding: 10px; background: #101316; border: 1px solid var(--sgfx-border); border-radius: 6px; }
    .sgfx-histogram strong { display: block; margin-bottom: 8px; color: var(--sgfx-muted); font-weight: 500; }
    .sgfx-histogram-axis { display: grid; grid-template-columns: 20px minmax(0, 1fr) 160px; align-items: center; gap: 8px; margin-top: 6px; color: var(--sgfx-muted); font-size: 12px; }
    .sgfx-histogram-bars { height: 34px; display: flex; align-items: end; gap: 1px; }
    .sgfx-histogram-bars span { flex: 1; background: var(--sgfx-blue); min-width: 2px; opacity: .85; }
    .sgfx-table-wrap { overflow: auto; border: 1px solid var(--sgfx-border); border-radius: 8px; }
    table { width: 100%; border-collapse: collapse; min-width: 640px; }
    th, td { padding: 9px 10px; border-bottom: 1px solid var(--sgfx-border); vertical-align: top; text-align: left; }
    th button { appearance: none; border: 0; background: transparent; color: var(--sgfx-text); font: inherit; font-weight: 700; cursor: pointer; padding: 0; }
    td { color: var(--sgfx-muted); }
    .sgfx-footer { margin: 22px 0 0; padding: 16px 4px; color: var(--sgfx-muted); }
    @media (max-width: 900px) {
      .sgfx-page { padding: 14px; }
      .sgfx-hero { grid-template-columns: 1fr; }
      .sgfx-image-grid { grid-template-columns: 1fr; }
      .sgfx-section-head { align-items: flex-start; flex-direction: column; }
      .sgfx-image-viewport, .sgfx-image-missing { height: 220px; }
    }
    """


def _js() -> str:
    return """
    (() => {
      const zoom = document.getElementById('sgfx-zoom');
      const zoomValue = document.getElementById('sgfx-zoom-value');
      if (zoom) {
        const applyZoom = () => {
          document.documentElement.style.setProperty('--sgfx-zoom', String(Number(zoom.value || 100) / 100));
          if (zoomValue) zoomValue.textContent = `${zoom.value}%`;
        };
        zoom.addEventListener('input', applyZoom);
        applyZoom();
      }
      document.querySelectorAll('.sgfx-image-viewport').forEach((pane) => {
        let dragging = false;
        let startX = 0;
        let startY = 0;
        let scrollLeft = 0;
        let scrollTop = 0;
        pane.addEventListener('pointerdown', (event) => {
          dragging = true;
          pane.classList.add('dragging');
          pane.setPointerCapture(event.pointerId);
          startX = event.clientX;
          startY = event.clientY;
          scrollLeft = pane.scrollLeft;
          scrollTop = pane.scrollTop;
        });
        pane.addEventListener('pointermove', (event) => {
          if (!dragging) return;
          pane.scrollLeft = scrollLeft - (event.clientX - startX);
          pane.scrollTop = scrollTop - (event.clientY - startY);
        });
        const stop = () => { dragging = false; pane.classList.remove('dragging'); };
        pane.addEventListener('pointerup', stop);
        pane.addEventListener('pointercancel', stop);
        pane.addEventListener('lostpointercapture', stop);
      });
      document.querySelectorAll('[data-sortable-table]').forEach((table) => {
        table.querySelectorAll('th button').forEach((button) => {
          button.addEventListener('click', () => {
            const key = Number(button.dataset.sortKey || 0);
            const tbody = table.querySelector('tbody');
            const rows = Array.from(tbody.querySelectorAll('tr'));
            const direction = button.dataset.direction === 'asc' ? 'desc' : 'asc';
            button.dataset.direction = direction;
            rows.sort((left, right) => {
              const a = (left.children[key]?.textContent || '').trim().toLowerCase();
              const b = (right.children[key]?.textContent || '').trim().toLowerCase();
              return direction === 'asc' ? a.localeCompare(b) : b.localeCompare(a);
            });
            rows.forEach((row) => tbody.appendChild(row));
          });
        });
      });
    })();
    """


def render_qa_pass_report_html(
    payload: dict[str, Any],
    *,
    mode: str = "export",
    output_root: Path | str | None = None,
    image_max_bytes: int = DEFAULT_IMAGE_MAX_BYTES,
    run_history: list[dict[str, Any]] | None = None,
    home: Path | str | None = None,
) -> str:
    if mode not in {"dashboard", "export"}:
        raise ValueError("mode must be 'dashboard' or 'export'")
    root = Path(output_root).resolve() if output_root is not None else None
    profile = _clean_profile(payload.get("profile_id"))
    generated_at = _utc_now()
    summary = build_qa_pass_report_summary(payload)
    rows, dropped_notes = _enriched_screenshot_rows(
        payload,
        mode=mode,
        output_root=root,
        image_max_bytes=max(1, int(image_max_bytes)),
    )
    risk_score, risk_level = _risk_score_and_level(payload)
    trend_html = _sparkline_html(profile, run_history=run_history, home=Path(home).resolve() if home is not None else None)
    step_table = _table_html(
        "Run steps",
        (("Step", ("label",)), ("Status", ("status",)), ("Detail", ("detail", "summary"))),
        _summary_step_rows(payload),
        empty="No step summary was attached to this Full QA Pass result.",
    )
    delivery_table = _table_html(
        "Delivery readiness",
        (("Check", ("label", "name", "id", "model_id")), ("Status", ("status", "state")), ("Detail", ("detail", "summary", "reason"))),
        _delivery_rows(payload),
        empty="No delivery readiness rows were attached to this pass.",
    )
    jira_table = _table_html(
        "Jira tickets",
        (("Ticket", ("key", "ticket_id", "id")), ("Status", ("status", "fields.status.name")), ("Summary", ("summary", "title"))),
        _jira_rows(payload),
        empty="No Jira ticket rows were attached to this pass.",
    )
    risk_table = _table_html(
        "Risk signals",
        (("Signal", ("id", "label")), ("Status", ("status",)), ("Detail", ("detail", "summary", "reason", "weight"))),
        _risk_signal_rows(payload),
        empty="No active risk signals were attached.",
    )
    disabled_table = _table_html(
        "Disabled tests",
        (("Item", ("label", "name", "test_name")), ("Status", ("status", "state")), ("Detail", ("detail", "summary", "relative_path"))),
        _disabled_test_rows(payload),
        empty="No disabled-test rows were attached.",
    )
    manual_table = _table_html(
        "Manual-review checklist",
        (("Step", ("title", "slug", "label")), ("Suggested verdict", ("suggested_verdict", "verdict")), ("Reason", ("suggestion_reason", "auto_check_summary", "detail"))),
        _manual_review_rows(payload),
        empty="No manual-review checklist was attached, but manual review still remains required.",
    )
    guardrails = [
        _clean_text(item)
        for item in _as_list(payload.get("guardrails"))
        if str(item).strip()
    ]
    guardrail_html = "".join(f"<li>{_h(item)}</li>" for item in guardrails)
    footer_body = (
        f"<ul>{guardrail_html}</ul>"
        if guardrail_html
        else "<p>Manual review remains required before any delivery decision.</p>"
    )
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>QA Pass Report - {_h(profile)}</title><style>{_css()}</style></head>"
        '<body><main class="sgfx-page">'
        '<section class="sgfx-hero">'
        '<div>'
        f"<h1>{_h(summary['hero_text'])}</h1>"
        f"<p>{_h(summary.get('summary') or 'Full QA Pass evidence prepared locally.')}</p>"
        '<div class="sgfx-hero-stats">'
        f"<div class=\"sgfx-stat\"><strong>{_h(summary['passed_count'])}</strong><span>checks passed</span></div>"
        f"<div class=\"sgfx-stat\"><strong>{_h(summary['screenshot_diff_count'])}</strong><span>screenshot diffs</span></div>"
        f"<div class=\"sgfx-stat\"><strong>{_h(summary['manual_review_item_count'])}</strong><span>manual items</span></div>"
        f"<div class=\"sgfx-stat\"><strong>{_h(summary['status'])}</strong><span>run status</span></div>"
        "</div>"
        f"{trend_html}"
        "</div>"
        f"<div>{_risk_gauge_svg(risk_score, risk_level)}</div>"
        "</section>"
        f"{_screenshot_section(rows, dropped_notes, summary)}"
        f"{step_table}{delivery_table}{jira_table}{risk_table}{disabled_table}{manual_table}"
        '<footer class="sgfx-footer">'
        f"<p>Generated {html_escape(generated_at)}. Evidence only - manual review remains required. This report is not an approval record.</p>"
        f"{footer_body}"
        "</footer>"
        f"<script>{_js()}</script></main></body></html>"
    )


def write_qa_pass_report_html(
    *,
    profile_id: str,
    payload: dict[str, Any],
    output_root: Path | str,
    mode: str = "dashboard",
    image_max_bytes: int = DEFAULT_IMAGE_MAX_BYTES,
    run_history: list[dict[str, Any]] | None = None,
    home: Path | str | None = None,
) -> QaPassReportBundle:
    profile = _clean_profile(profile_id or payload.get("profile_id"))
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    html = render_qa_pass_report_html(
        {**payload, "profile_id": profile},
        mode=mode,
        output_root=root,
        image_max_bytes=image_max_bytes,
        run_history=run_history,
        home=home,
    )
    scrubbed_html, _scrub_count = _scrub_report_text(html)
    html_path = root / "qa-pass-report.html"
    html_path.write_text(scrubbed_html, encoding="utf-8")
    rows = collect_screenshot_review_rows(payload)
    dropped = tuple(re.findall(r"<li>(.*?)</li>", scrubbed_html)) if "Image notes" in scrubbed_html else ()
    return QaPassReportBundle(
        profile_id=profile,
        html_path=html_path,
        output_root=root,
        generated_at_utc=_utc_now(),
        screenshot_row_count=len(rows),
        dropped_image_notes=tuple(html_escape(note) for note in dropped),
    )


def _archive_image_name(row: dict[str, str], *, role: str, index: int, path: Path) -> str:
    suffix = path.suffix.casefold() if path.suffix else ".png"
    key = _safe_token(row.get("key") or row.get("label") or path.stem, "screenshot")
    return f"screenshots/{role}/{index:03d}-{key}{suffix}"


def _append_qa_zip_members(
    zip_path: Path,
    *,
    profile_id: str,
    payload: dict[str, Any],
    html: str,
    generated_at_utc: str,
) -> tuple[tuple[ExportManifestEntry, ...], int]:
    rows = collect_screenshot_review_rows(payload)
    entries: list[ExportManifestEntry] = []
    image_count = 0
    scrubbed_html, html_scrub_count = _scrub_report_text(html)
    scrubbed_payload, payload_scrub_count = _scrub_report_text(json.dumps(payload, indent=2, ensure_ascii=False))
    with zipfile.ZipFile(zip_path, "a", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("qa-pass-report.html", scrubbed_html.encode("utf-8"))
        entries.append(
            ExportManifestEntry(
                archive_name="qa-pass-report.html",
                source_path="<rendered in-memory>",
                bytes=len(scrubbed_html.encode("utf-8")),
                sanitized=html_scrub_count > 0,
            )
        )
        zf.writestr("full_qa_payload.json", scrubbed_payload.encode("utf-8"))
        entries.append(
            ExportManifestEntry(
                archive_name="full_qa_payload.json",
                source_path="<full-qa payload in-memory>",
                bytes=len(scrubbed_payload.encode("utf-8")),
                sanitized=payload_scrub_count > 0,
            )
        )
        for index, row in enumerate(rows, start=1):
            for role, key in (("expected", "expected_path"), ("actual", "actual_path"), ("diff", "diff_path")):
                path = _path_if_image(row.get(key, ""))
                if path is None:
                    continue
                try:
                    blob = path.read_bytes()
                except OSError:
                    continue
                archive_name = _archive_image_name(row, role=role, index=index, path=path)
                zf.writestr(archive_name, blob)
                image_count += 1
                entries.append(
                    ExportManifestEntry(
                        archive_name=archive_name,
                        source_path=str(path),
                        bytes=len(blob),
                        sanitized=False,
                    )
                )
        manifest = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "profile_id": profile_id,
            "generated_at_utc": generated_at_utc,
            "screenshot_row_count": len(rows),
            "image_count": image_count,
            "entries": [
                {
                    "archive_name": entry.archive_name,
                    "source_path": _redact_manifest_path(entry.source_path),
                    "bytes": entry.bytes,
                    "sanitized": entry.sanitized,
                }
                for entry in entries
            ],
            "guardrails": [
                "Manual review remains required.",
                "Decision: not approval - evidence only.",
                "This ZIP is local evidence; no Jira, SVN, or BMW Git write is performed by export.",
            ],
        }
        zf.writestr("qa_pass_report_manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"))
    return tuple(entries), image_count


def export_qa_pass_report_zip(
    *,
    profile_id: str,
    workspace: Path | str,
    payload: dict[str, Any],
    output_path: Path | str,
    bmw_root: Path | str | None = None,
    home: Path | str | None = None,
    image_max_bytes: int = DEFAULT_IMAGE_MAX_BYTES,
    build_commit: str = "",
    exe_sha256: str = "",
    run_history: list[dict[str, Any]] | None = None,
) -> QaPassReportZipResult:
    profile = _clean_profile(profile_id or payload.get("profile_id"))
    output_zip = Path(output_path).resolve()
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    generated_at = _utc_now()
    report_payload = {**payload, "profile_id": profile}
    html = render_qa_pass_report_html(
        report_payload,
        mode="export",
        image_max_bytes=image_max_bytes,
        run_history=run_history,
        home=home,
    )
    base_result = export_profile_evidence(
        profile_id=profile,
        workspace=workspace,
        output_path=output_zip,
        bmw_root=bmw_root,
        home=home,
        build_commit=build_commit,
        exe_sha256=exe_sha256,
        summary_html=html,
    )
    qa_entries, image_count = _append_qa_zip_members(
        output_zip,
        profile_id=profile,
        payload=report_payload,
        html=html,
        generated_at_utc=generated_at,
    )
    return QaPassReportZipResult(
        profile_id=profile,
        zip_path=output_zip,
        generated_at_utc=generated_at,
        screenshot_row_count=len(collect_screenshot_review_rows(report_payload)),
        image_count=image_count,
        entries=tuple(base_result.entries) + qa_entries,
    )


def default_qa_pass_report_zip_path(output_root: Path | str, profile_id: str, *, now: Callable[[], str] | None = None) -> Path:
    stamp = (now or (lambda: datetime.now().strftime("%Y%m%d-%H%M%S")))()
    safe_profile = _safe_profile_token(profile_id)
    return Path(output_root).resolve() / "exports" / f"{safe_profile}-qa-pass-report-{stamp}.zip"
