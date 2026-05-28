from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html import escape
import json
import os
from pathlib import Path
import re
import shutil
import struct
from typing import Any
from urllib.parse import quote
import zlib

from sg_preflight.screenshot_triage import materialize_screenshot_triage


_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class DiffDeltaThresholds:
    green_max_percent: float = 0.5
    yellow_max_percent: float = 2.0


@dataclass(frozen=True)
class DiffDeltaBadge:
    status: str
    label: str = ""
    level: str = ""
    max_delta_percent: float | None = None
    max_x: int | None = None
    max_y: int | None = None
    backend: str = ""


@dataclass(frozen=True)
class DiffDeltaHistogramAxis:
    axis: str
    axis_length: int
    bins: tuple[int, ...] = ()
    peak_bin: int = -1
    peak_start: int | None = None
    peak_end: int | None = None
    peak_count: int = 0
    peak_label: str = ""


@dataclass(frozen=True)
class DiffDeltaHistogram:
    status: str
    threshold_percent: float = 0.0
    threshold_value: int = 0
    changed_pixel_count: int = 0
    total_pixel_count: int = 0
    changed_pixel_ratio: float | None = None
    x_axis: DiffDeltaHistogramAxis | None = None
    y_axis: DiffDeltaHistogramAxis | None = None
    backend: str = ""


@dataclass(frozen=True)
class _DecodedDiffImage:
    width: int
    height: int
    channel_max: bytes
    backend: str


@dataclass(frozen=True)
class ScreenshotReviewItem:
    key: str
    classification: str
    visual_classification: str
    summary: str
    visual_summary: str
    escalation_path: str = ""
    expected_path: str = ""
    actual_path: str = ""
    diff_path: str = ""
    expected_uri: str = ""
    actual_uri: str = ""
    diff_uri: str = ""
    diff_delta_label: str = ""
    diff_delta_level: str = ""
    diff_delta_percent: float | None = None
    diff_delta_x: int | None = None
    diff_delta_y: int | None = None
    diff_delta_backend: str = ""
    diff_histogram_status: str = "unavailable"
    diff_histogram_threshold_percent: float = 0.0
    diff_histogram_changed_pixel_count: int = 0
    diff_histogram_total_pixel_count: int = 0
    diff_histogram_changed_pixel_ratio: float | None = None
    diff_histogram_x_bins: tuple[int, ...] = ()
    diff_histogram_y_bins: tuple[int, ...] = ()
    diff_histogram_x_peak_label: str = ""
    diff_histogram_y_peak_label: str = ""
    diff_histogram_backend: str = ""
    changed_pixel_ratio: float | None = None
    mean_abs_diff: float | None = None
    review_score: float | None = None
    anomaly_hints: tuple[str, ...] = ()
    manual_verdict: str = "not_run"


@dataclass(frozen=True)
class ScreenshotReviewViewer:
    profile_id: str
    project_root: str
    generated_at_utc: str
    expected_root: str
    item_count: int
    triage_json_path: str
    triage_html_path: str
    notes: tuple[str, ...]
    guardrails: tuple[str, ...]
    items: tuple[ScreenshotReviewItem, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ScreenshotReviewViewerBundle:
    viewer: ScreenshotReviewViewer
    json_path: Path
    html_path: Path
    triage_json_path: Path
    triage_html_path: Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_asset_name(key: str, suffix: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", key.strip()).strip("._")
    if not cleaned:
        cleaned = "screenshot"
    return f"{cleaned[:120]}{suffix}"


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value


def diff_delta_thresholds_from_env() -> DiffDeltaThresholds:
    green = _env_float("SGFX_DIFF_DELTA_GREEN_MAX_PERCENT", 0.5)
    yellow = _env_float("SGFX_DIFF_DELTA_YELLOW_MAX_PERCENT", 2.0)
    if yellow < green:
        yellow = green
    return DiffDeltaThresholds(green_max_percent=green, yellow_max_percent=yellow)


def diff_histogram_threshold_percent_from_env() -> float:
    return _env_float("SGFX_DIFF_HISTOGRAM_MIN_DELTA_PERCENT", 0.0)


def diff_histogram_bin_count_from_env() -> int:
    return _env_int("SGFX_DIFF_HISTOGRAM_BINS", 96, minimum=8, maximum=240)


def _paeth_predictor(left: int, above: int, upper_left: int) -> int:
    estimate = left + above - upper_left
    left_distance = abs(estimate - left)
    above_distance = abs(estimate - above)
    upper_left_distance = abs(estimate - upper_left)
    if left_distance <= above_distance and left_distance <= upper_left_distance:
        return left
    if above_distance <= upper_left_distance:
        return above
    return upper_left


def _decode_png_max_channel(path: Path) -> _DecodedDiffImage | None:
    data = path.read_bytes()
    if not data.startswith(_PNG_SIGNATURE):
        return None
    offset = len(_PNG_SIGNATURE)
    width = 0
    height = 0
    bit_depth = 0
    color_type = -1
    compression = -1
    filter_method = -1
    interlace = -1
    palette: list[tuple[int, int, int]] = []
    idat_chunks: list[bytes] = []
    while offset + 8 <= len(data):
        length = int.from_bytes(data[offset : offset + 4], "big")
        chunk_type = data[offset + 4 : offset + 8]
        chunk_start = offset + 8
        chunk_end = chunk_start + length
        if chunk_end + 4 > len(data):
            return None
        chunk = data[chunk_start:chunk_end]
        offset = chunk_end + 4
        if chunk_type == b"IHDR":
            if len(chunk) != 13:
                return None
            width = int.from_bytes(chunk[0:4], "big")
            height = int.from_bytes(chunk[4:8], "big")
            bit_depth = int(chunk[8])
            color_type = int(chunk[9])
            compression = int(chunk[10])
            filter_method = int(chunk[11])
            interlace = int(chunk[12])
        elif chunk_type == b"PLTE":
            palette = [tuple(chunk[index : index + 3]) for index in range(0, len(chunk) - 2, 3)]
        elif chunk_type == b"IDAT":
            idat_chunks.append(chunk)
        elif chunk_type == b"IEND":
            break
    if width <= 0 or height <= 0 or not idat_chunks:
        return None
    if compression != 0 or filter_method != 0 or interlace != 0 or bit_depth != 8:
        return None
    channel_count_by_type = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
    channel_count = channel_count_by_type.get(color_type)
    if channel_count is None:
        return None
    if color_type == 3 and not palette:
        return None
    row_length = width * channel_count
    try:
        raw = zlib.decompress(b"".join(idat_chunks))
    except zlib.error:
        return None
    previous = bytearray(row_length)
    position = 0
    values = bytearray()
    for _y in range(height):
        if position >= len(raw):
            return None
        filter_type = raw[position]
        position += 1
        row = bytearray(raw[position : position + row_length])
        position += row_length
        if len(row) != row_length:
            return None
        for index, byte_value in enumerate(row):
            left = row[index - channel_count] if index >= channel_count else 0
            above = previous[index] if previous else 0
            upper_left = previous[index - channel_count] if previous and index >= channel_count else 0
            if filter_type == 1:
                row[index] = (byte_value + left) & 0xFF
            elif filter_type == 2:
                row[index] = (byte_value + above) & 0xFF
            elif filter_type == 3:
                row[index] = (byte_value + ((left + above) // 2)) & 0xFF
            elif filter_type == 4:
                row[index] = (byte_value + _paeth_predictor(left, above, upper_left)) & 0xFF
            elif filter_type != 0:
                return None
        if color_type == 0:
            values.extend(row)
        elif color_type == 2:
            for index in range(0, len(row), 3):
                values.append(max(row[index], row[index + 1], row[index + 2]))
        elif color_type == 3:
            for index in row:
                if index >= len(palette):
                    return None
                values.append(max(palette[index]))
        elif color_type == 4:
            for index in range(0, len(row), 2):
                values.append(row[index])
        elif color_type == 6:
            for index in range(0, len(row), 4):
                values.append(max(row[index], row[index + 1], row[index + 2]))
        previous = row
    expected_pixels = width * height
    if len(values) != expected_pixels:
        return None
    return _DecodedDiffImage(width=width, height=height, channel_max=bytes(values), backend="png")


def _decode_bmp_max_channel(path: Path) -> _DecodedDiffImage | None:
    data = path.read_bytes()
    if len(data) < 54 or data[:2] != b"BM":
        return None
    try:
        pixel_offset = struct.unpack_from("<I", data, 10)[0]
        dib_size = struct.unpack_from("<I", data, 14)[0]
    except struct.error:
        return None
    if dib_size < 40:
        return None
    try:
        width = struct.unpack_from("<i", data, 18)[0]
        raw_height = struct.unpack_from("<i", data, 22)[0]
        planes = struct.unpack_from("<H", data, 26)[0]
        bits_per_pixel = struct.unpack_from("<H", data, 28)[0]
        compression = struct.unpack_from("<I", data, 30)[0]
    except struct.error:
        return None
    if width <= 0 or raw_height == 0 or planes != 1 or compression != 0 or bits_per_pixel not in {24, 32}:
        return None
    height = abs(raw_height)
    top_down = raw_height < 0
    bytes_per_pixel = bits_per_pixel // 8
    row_size = ((bits_per_pixel * width + 31) // 32) * 4
    values = bytearray()
    for display_y in range(height):
        storage_y = display_y if top_down else height - 1 - display_y
        row_start = pixel_offset + (storage_y * row_size)
        row_end = row_start + row_size
        if row_start < 0 or row_end > len(data):
            return None
        row = data[row_start:row_end]
        for x in range(width):
            pixel = row[x * bytes_per_pixel : (x + 1) * bytes_per_pixel]
            if len(pixel) < 3:
                return None
            blue, green, red = pixel[0], pixel[1], pixel[2]
            values.append(max(red, green, blue))
    return _DecodedDiffImage(width=width, height=height, channel_max=bytes(values), backend="bmp")


def _decode_diff_image(path: Path) -> _DecodedDiffImage | None:
    if not path.is_file():
        return None
    if path.suffix.lower() == ".bmp":
        return _decode_bmp_max_channel(path)
    return _decode_png_max_channel(path) or _decode_bmp_max_channel(path)


def _max_delta_with_numpy(decoded: _DecodedDiffImage) -> tuple[int, int, int, str] | None:
    try:
        import numpy as np  # type: ignore[import-not-found]
    except Exception:
        return None
    try:
        array = np.frombuffer(decoded.channel_max, dtype=np.uint8).reshape((decoded.height, decoded.width))
        row_maxes = array.max(axis=1)
        column_maxes = array.max(axis=0)
        max_value = int(row_maxes.max())
        max_y = int(row_maxes.argmax())
        max_x = int(column_maxes.argmax())
    except Exception:
        return None
    return max_value, max_x, max_y, f"{decoded.backend}+numpy"


def _max_delta_fallback(decoded: _DecodedDiffImage) -> tuple[int, int, int, str]:
    values = decoded.channel_max
    column_maxes = [0] * decoded.width
    max_value = 0
    max_y = 0
    for y in range(decoded.height):
        row = values[y * decoded.width : (y + 1) * decoded.width]
        row_max = max(row) if row else 0
        if row_max > max_value:
            max_value = int(row_max)
            max_y = y
        for x, value in enumerate(row):
            if value > column_maxes[x]:
                column_maxes[x] = int(value)
    max_x = 0
    if column_maxes:
        column_value = max(column_maxes)
        max_x = column_maxes.index(column_value)
        max_value = max(max_value, column_value)
    return int(max_value), int(max_x), int(max_y), f"{decoded.backend}+python"


def _compute_diff_delta_badge_from_decoded(
    decoded: _DecodedDiffImage,
    thresholds: DiffDeltaThresholds,
) -> DiffDeltaBadge:
    result = _max_delta_with_numpy(decoded) or _max_delta_fallback(decoded)
    max_value, max_x, max_y, backend = result
    percent = round((max_value / 255.0) * 100.0, 3)
    if percent < thresholds.green_max_percent:
        level = "green"
    elif percent <= thresholds.yellow_max_percent:
        level = "yellow"
    else:
        level = "red"
    label = f"max-\u0394: {percent:.1f}% (x={max_x}, y={max_y})"
    return DiffDeltaBadge(
        status="available",
        label=label,
        level=level,
        max_delta_percent=percent,
        max_x=max_x,
        max_y=max_y,
        backend=backend,
    )


def compute_diff_delta_badge(
    diff_path: str | Path,
    *,
    thresholds: DiffDeltaThresholds | None = None,
) -> DiffDeltaBadge:
    path = Path(diff_path) if str(diff_path or "").strip() else Path()
    if not path:
        return DiffDeltaBadge(status="unavailable")
    try:
        decoded = _decode_diff_image(path)
    except OSError:
        decoded = None
    if decoded is None:
        return DiffDeltaBadge(status="unavailable")
    thresholds = thresholds or diff_delta_thresholds_from_env()
    return _compute_diff_delta_badge_from_decoded(decoded, thresholds)


def _threshold_percent_to_value(threshold_percent: float) -> int:
    if threshold_percent <= 0:
        return 0
    value = int(round((threshold_percent / 100.0) * 255.0))
    if value < 0:
        return 0
    if value > 255:
        return 255
    return value


def _axis_histogram(axis: str, axis_length: int, bins: list[int]) -> DiffDeltaHistogramAxis:
    if not bins:
        return DiffDeltaHistogramAxis(axis=axis, axis_length=axis_length)
    peak_count = max(bins)
    if peak_count <= 0:
        return DiffDeltaHistogramAxis(
            axis=axis,
            axis_length=axis_length,
            bins=tuple(bins),
            peak_bin=-1,
            peak_count=0,
            peak_label=f"{axis}=none",
        )
    peak_bin = bins.index(peak_count)
    bin_count = len(bins)
    peak_start = int((peak_bin * axis_length) // bin_count)
    peak_end = int((((peak_bin + 1) * axis_length) // bin_count) - 1)
    if peak_end < peak_start:
        peak_end = peak_start
    peak_label = f"{axis}={peak_start}" if peak_start == peak_end else f"{axis}={peak_start}-{peak_end}"
    return DiffDeltaHistogramAxis(
        axis=axis,
        axis_length=axis_length,
        bins=tuple(bins),
        peak_bin=peak_bin,
        peak_start=peak_start,
        peak_end=peak_end,
        peak_count=peak_count,
        peak_label=peak_label,
    )


def _compute_diff_delta_histogram_from_decoded(
    decoded: _DecodedDiffImage,
    *,
    threshold_percent: float,
    max_bins: int,
) -> DiffDeltaHistogram:
    total_pixels = decoded.width * decoded.height
    if total_pixels <= 0:
        return DiffDeltaHistogram(status="unavailable")
    threshold_value = _threshold_percent_to_value(threshold_percent)
    x_bin_count = max(1, min(max_bins, decoded.width))
    y_bin_count = max(1, min(max_bins, decoded.height))
    x_bins = [0] * x_bin_count
    y_bins = [0] * y_bin_count
    changed = 0
    values = decoded.channel_max
    for y in range(decoded.height):
        row_start = y * decoded.width
        y_bin = (y * y_bin_count) // decoded.height
        for x in range(decoded.width):
            if values[row_start + x] > threshold_value:
                x_bins[(x * x_bin_count) // decoded.width] += 1
                y_bins[y_bin] += 1
                changed += 1
    return DiffDeltaHistogram(
        status="available",
        threshold_percent=threshold_percent,
        threshold_value=threshold_value,
        changed_pixel_count=changed,
        total_pixel_count=total_pixels,
        changed_pixel_ratio=(changed / total_pixels) if total_pixels else None,
        x_axis=_axis_histogram("x", decoded.width, x_bins),
        y_axis=_axis_histogram("y", decoded.height, y_bins),
        backend=f"{decoded.backend}+python",
    )


def compute_diff_delta_histogram(
    diff_path: str | Path,
    *,
    threshold_percent: float | None = None,
    max_bins: int | None = None,
) -> DiffDeltaHistogram:
    path = Path(diff_path) if str(diff_path or "").strip() else Path()
    if not path:
        return DiffDeltaHistogram(status="unavailable")
    try:
        decoded = _decode_diff_image(path)
    except OSError:
        decoded = None
    if decoded is None:
        return DiffDeltaHistogram(status="unavailable")
    threshold = threshold_percent if threshold_percent is not None else diff_histogram_threshold_percent_from_env()
    if threshold < 0:
        threshold = 0.0
    bin_count = max_bins if max_bins is not None else diff_histogram_bin_count_from_env()
    if bin_count < 1:
        bin_count = 1
    return _compute_diff_delta_histogram_from_decoded(
        decoded,
        threshold_percent=threshold,
        max_bins=bin_count,
    )


def _compute_diff_review_metrics(diff_path: str | Path) -> tuple[DiffDeltaBadge, DiffDeltaHistogram]:
    path = Path(diff_path) if str(diff_path or "").strip() else Path()
    if not path:
        return DiffDeltaBadge(status="unavailable"), DiffDeltaHistogram(status="unavailable")
    try:
        decoded = _decode_diff_image(path)
    except OSError:
        decoded = None
    if decoded is None:
        return DiffDeltaBadge(status="unavailable"), DiffDeltaHistogram(status="unavailable")
    badge = _compute_diff_delta_badge_from_decoded(decoded, diff_delta_thresholds_from_env())
    histogram = _compute_diff_delta_histogram_from_decoded(
        decoded,
        threshold_percent=diff_histogram_threshold_percent_from_env(),
        max_bins=diff_histogram_bin_count_from_env(),
    )
    return badge, histogram


def _viewer_asset_uri(path_value: str, output_root: Path, asset_root: Path, slot: str, key: str) -> str:
    if not path_value:
        return ""
    source = Path(path_value)
    if not source.is_file():
        return ""
    suffix = source.suffix.lower() or ".png"
    target = asset_root / slot / _safe_asset_name(key, suffix)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    relative = target.relative_to(output_root).as_posix()
    return quote(relative, safe="/._-")


def _diff_lookup(diff_reference_roots: tuple[Path, ...]) -> dict[str, Path]:
    lookup: dict[str, Path] = {}

    def add_keys(relative: Path, path: Path) -> None:
        key_candidates = {relative.with_suffix("").as_posix().casefold(), relative.with_suffix("").name.casefold()}
        for key in tuple(key_candidates):
            for suffix in ("_color", "_diff"):
                if key.endswith(suffix):
                    key_candidates.add(key[: -len(suffix)])
        for key in key_candidates:
            lookup.setdefault(key, path)

    for root in diff_reference_roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES:
                try:
                    relative = path.relative_to(root)
                except ValueError:
                    relative = Path(path.name)
                add_keys(relative, path)
    return lookup


def build_screenshot_review_viewer(
    profile_id: str,
    project_root: Path,
    output_root: Path,
    *,
    expected_root: Path | None = None,
    candidate_roots: tuple[Path, ...] = (),
    diff_reference_roots: tuple[Path, ...] = (),
    priority_names: tuple[str, ...] = (),
    max_items: int = 80,
) -> ScreenshotReviewViewerBundle:
    output_root.mkdir(parents=True, exist_ok=True)
    triage_output_root = output_root / "triage"
    triage_bundle = materialize_screenshot_triage(
        profile_id,
        project_root,
        triage_output_root,
        expected_root=expected_root,
        candidate_roots=candidate_roots,
        diff_reference_roots=diff_reference_roots,
        priority_names=priority_names,
    )
    diff_lookup = _diff_lookup(diff_reference_roots)
    asset_root = output_root / "assets"

    items: list[ScreenshotReviewItem] = []
    for pair in triage_bundle.report.pairs[:max_items]:
        diff_path = pair.diff_image_path
        if not diff_path:
            diff_path = str(
                diff_lookup.get(pair.key.casefold())
                or diff_lookup.get(Path(pair.key).with_suffix("").name.casefold())
                or ""
            )
        delta_badge, delta_histogram = _compute_diff_review_metrics(diff_path)
        x_axis = delta_histogram.x_axis
        y_axis = delta_histogram.y_axis
        items.append(
            ScreenshotReviewItem(
                key=pair.key,
                classification=pair.classification,
                visual_classification=pair.visual_classification,
                summary=pair.summary,
                visual_summary=pair.visual_summary,
                escalation_path=pair.escalation_path,
                expected_path=pair.baseline_path,
                actual_path=pair.candidate_path,
                diff_path=diff_path,
                expected_uri=_viewer_asset_uri(pair.baseline_path, output_root, asset_root, "expected", pair.key),
                actual_uri=_viewer_asset_uri(pair.candidate_path, output_root, asset_root, "actual", pair.key),
                diff_uri=_viewer_asset_uri(diff_path, output_root, asset_root, "diff", pair.key),
                diff_delta_label=delta_badge.label,
                diff_delta_level=delta_badge.level,
                diff_delta_percent=delta_badge.max_delta_percent,
                diff_delta_x=delta_badge.max_x,
                diff_delta_y=delta_badge.max_y,
                diff_delta_backend=delta_badge.backend,
                diff_histogram_status=delta_histogram.status,
                diff_histogram_threshold_percent=delta_histogram.threshold_percent,
                diff_histogram_changed_pixel_count=delta_histogram.changed_pixel_count,
                diff_histogram_total_pixel_count=delta_histogram.total_pixel_count,
                diff_histogram_changed_pixel_ratio=delta_histogram.changed_pixel_ratio,
                diff_histogram_x_bins=x_axis.bins if x_axis else (),
                diff_histogram_y_bins=y_axis.bins if y_axis else (),
                diff_histogram_x_peak_label=x_axis.peak_label if x_axis else "",
                diff_histogram_y_peak_label=y_axis.peak_label if y_axis else "",
                diff_histogram_backend=delta_histogram.backend,
                changed_pixel_ratio=pair.changed_pixel_ratio,
                mean_abs_diff=pair.mean_abs_diff,
                review_score=pair.review_score,
                anomaly_hints=pair.anomaly_hints,
            )
        )

    viewer = ScreenshotReviewViewer(
        profile_id=profile_id,
        project_root=str(project_root.resolve()),
        generated_at_utc=_utc_now(),
        expected_root=triage_bundle.report.expected_root,
        item_count=len(items),
        triage_json_path=str(triage_bundle.json_path),
        triage_html_path=str(triage_bundle.html_path),
        notes=(
            "Side-by-side viewer for local screenshot evidence.",
            "Manual review remains required.",
            "Decision: not approval — evidence only.",
            "Use expected, actual, and diff panes together before recording any reviewer verdict.",
        ),
        guardrails=(
            "Manual review remains required.",
            "Decision: not approval — evidence only.",
            "BMW Git access is read-only. SGFX never modifies BMW source.",
            "Activity log is local-only — never posted to Jira, SVN, or BMW Git.",
        ),
        items=tuple(items),
    )
    json_path = output_root / "screenshot-review-viewer.json"
    html_path = output_root / "screenshot-review-viewer.html"
    json_path.write_text(json.dumps(viewer.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    html_path.write_text(_html(viewer), encoding="utf-8")
    return ScreenshotReviewViewerBundle(
        viewer=viewer,
        json_path=json_path,
        html_path=html_path,
        triage_json_path=triage_bundle.json_path,
        triage_html_path=triage_bundle.html_path,
    )


def _image_pane(label: str, slot: str) -> str:
    return f"""
      <section class="pane" data-pane="{escape(slot)}">
        <header>
          <span>{escape(label)}</span>
          <a data-open="{escape(slot)}" href="#" target="_blank" rel="noreferrer">open</a>
        </header>
        <div class="viewport" data-viewport="{escape(slot)}">
          <div class="missing" data-missing="{escape(slot)}">missing</div>
          <img data-image="{escape(slot)}" alt="{escape(label)} screenshot">
        </div>
        <footer data-path="{escape(slot)}"></footer>
      </section>
    """


def _script_json_payload(payload: str) -> str:
    return payload.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


def _format_percent(value: float | None, *, digits: int = 2) -> str:
    if value is None:
        return "unknown"
    return f"{value * 100.0:.{digits}f}%"


def _histogram_svg(bins: tuple[int, ...], *, orientation: str) -> str:
    if not bins:
        return '<div class="histogram-empty">Histogram unavailable</div>'
    peak = max(bins)
    if peak <= 0:
        return '<div class="histogram-empty">No changed pixels above threshold</div>'
    if orientation == "y":
        width = 56.0
        height = 132.0
        bin_height = height / len(bins)
        rects = []
        for index, count in enumerate(bins):
            bar_width = (count / peak) * (width - 6.0)
            y = index * bin_height
            rects.append(
                f'<rect x="0" y="{y:.2f}" width="{bar_width:.2f}" height="{max(1.0, bin_height - 0.7):.2f}" />'
            )
        return (
            '<svg class="histogram-svg histogram-y-strip" data-histogram-y '
            f'viewBox="0 0 {width:.0f} {height:.0f}" preserveAspectRatio="none" aria-label="y-axis histogram">'
            f'{"".join(rects)}</svg>'
        )
    width = 260.0
    height = 46.0
    bin_width = width / len(bins)
    rects = []
    for index, count in enumerate(bins):
        bar_height = (count / peak) * (height - 6.0)
        x = index * bin_width
        y = height - bar_height
        rects.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{max(1.0, bin_width - 0.6):.2f}" height="{bar_height:.2f}" />'
        )
    return (
        '<svg class="histogram-svg histogram-x-strip" data-histogram-x '
        f'viewBox="0 0 {width:.0f} {height:.0f}" preserveAspectRatio="none" aria-label="x-axis histogram">'
        f'{"".join(rects)}</svg>'
    )


def _histogram_html(item: ScreenshotReviewItem) -> str:
    if item.diff_histogram_status != "available":
        return ""
    ratio = _format_percent(item.diff_histogram_changed_pixel_ratio)
    total = item.diff_histogram_total_pixel_count
    changed = item.diff_histogram_changed_pixel_count
    x_label = item.diff_histogram_x_peak_label or "x=none"
    y_label = item.diff_histogram_y_peak_label or "y=none"
    return f"""
        <details class="delta-histogram sgfx-delta-histogram" data-histogram-row>
          <summary>Show positional histogram</summary>
          <div class="histogram-meta">
            <span>changed pixels: {changed} / {total} ({escape(ratio)})</span>
            <span>threshold: &gt; {item.diff_histogram_threshold_percent:.1f}%</span>
          </div>
          <div class="histogram-grid">
            <div class="histogram-main">
              <span>x-axis peak: {escape(x_label)}</span>
              {_histogram_svg(item.diff_histogram_x_bins, orientation="x")}
            </div>
            <div class="histogram-side">
              <span>y-axis peak: {escape(y_label)}</span>
              {_histogram_svg(item.diff_histogram_y_bins, orientation="y")}
            </div>
          </div>
        </details>
    """


def _item_button_html(item: ScreenshotReviewItem) -> str:
    level_class = f" delta-{item.diff_delta_level}" if item.diff_delta_level else ""
    delta_attrs = ""
    if item.diff_delta_level:
        delta_attrs += f' data-delta-level="{escape(item.diff_delta_level)}"'
    if item.diff_delta_percent is not None:
        delta_attrs += f' data-delta-percent="{item.diff_delta_percent:.3f}"'
    badge = (
        f'<em class="delta-badge delta-{escape(item.diff_delta_level)}">{escape(item.diff_delta_label)}</em>'
        if item.diff_delta_label
        else ""
    )
    histogram = _histogram_html(item)
    return (
        f'<article class="review-row{level_class}" data-review-row="{escape(item.key)}">'
        f'<button type="button" data-key="{escape(item.key)}"{delta_attrs} class="{level_class.strip()}">'
        f"<strong>{escape(item.key)}</strong>"
        f"<span>{escape(item.classification)} / {escape(item.visual_classification)}</span>"
        f"{badge}"
        "</button>"
        f"{histogram}"
        "</article>"
    )


def _html(viewer: ScreenshotReviewViewer) -> str:
    payload = _script_json_payload(json.dumps(viewer.to_dict(), ensure_ascii=False))
    item_buttons = "\n".join(_item_button_html(item) for item in viewer.items)
    guardrails = "".join(f"<li>{escape(line)}</li>" for line in viewer.guardrails)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Screenshot review viewer - {escape(viewer.profile_id)}</title>
  <style>
    :root {{
      --bg: #161616;
      --panel: #222;
      --panel-soft: #292929;
      --border: #3b3b3b;
      --fg: #e6e6e6;
      --muted: #aaa;
      --accent: #4ec9b0;
      --warning: #e8c07d;
      --delta-green: #57d68d;
      --delta-yellow: #e8c07d;
      --delta-red: #f07f72;
    }}
    html, body {{ min-height: 100%; margin: 0; background: var(--bg); color: var(--fg); font: 14px/1.45 "Segoe UI", Arial, sans-serif; }}
    body {{ display: grid; grid-template-columns: 310px minmax(0, 1fr); }}
    aside {{ min-height: 100vh; border-right: 1px solid var(--border); background: var(--panel); padding: 18px 14px; box-sizing: border-box; }}
    main {{ min-width: 0; padding: 18px; box-sizing: border-box; }}
    h1 {{ font-size: 18px; margin: 0 0 6px; }}
    .meta, .hint, li {{ color: var(--muted); font-size: 12px; }}
    .list {{ display: flex; flex-direction: column; gap: 8px; margin-top: 14px; max-height: calc(100vh - 210px); overflow: auto; }}
    .review-row {{ display: flex; flex-direction: column; gap: 6px; }}
    button[data-key] {{ text-align: left; border: 1px solid var(--border); border-left-width: 5px; border-radius: 6px; background: #1d1d1d; color: var(--fg); padding: 9px; cursor: pointer; }}
    .review-row button[data-key] {{ width: 100%; }}
    button[data-key].active {{ border-color: var(--accent); background: #20302d; }}
    button[data-key].delta-green {{ border-left-color: var(--delta-green); }}
    button[data-key].delta-yellow {{ border-left-color: var(--delta-yellow); }}
    button[data-key].delta-red {{ border-left-color: var(--delta-red); }}
    button[data-key] strong {{ display: block; overflow-wrap: anywhere; }}
    button[data-key] span {{ display: block; color: var(--muted); font-size: 12px; margin-top: 3px; }}
    .delta-badge {{ display: inline-flex; align-items: center; margin-top: 7px; padding: 2px 7px; border-radius: 999px; font-style: normal; font-size: 12px; line-height: 1.35; border: 1px solid var(--border); color: var(--muted); background: rgba(255, 255, 255, 0.04); }}
    .delta-badge.delta-green, .delta-detail.delta-green {{ color: var(--delta-green); border-color: rgba(87, 214, 141, 0.5); background: rgba(87, 214, 141, 0.12); }}
    .delta-badge.delta-yellow, .delta-detail.delta-yellow {{ color: var(--delta-yellow); border-color: rgba(232, 192, 125, 0.55); background: rgba(232, 192, 125, 0.12); }}
    .delta-badge.delta-red, .delta-detail.delta-red {{ color: var(--delta-red); border-color: rgba(240, 127, 114, 0.55); background: rgba(240, 127, 114, 0.13); }}
    .delta-histogram {{ border: 1px solid var(--border); border-radius: 6px; background: rgba(255, 255, 255, 0.025); padding: 7px 8px; }}
    .delta-histogram summary {{ cursor: pointer; color: var(--muted); font-size: 12px; list-style: none; }}
    .delta-histogram summary::-webkit-details-marker {{ display: none; }}
    .delta-histogram summary::before {{ content: "+"; display: inline-flex; align-items: center; justify-content: center; width: 14px; height: 14px; margin-right: 5px; border: 1px solid var(--border); border-radius: 50%; color: var(--accent); font-size: 11px; line-height: 1; }}
    .delta-histogram[open] summary::before {{ content: "-"; }}
    .histogram-meta {{ display: flex; flex-wrap: wrap; gap: 6px 10px; margin: 7px 0; color: var(--muted); font-size: 11px; }}
    .histogram-grid {{ display: grid; grid-template-columns: minmax(0, 1fr) 70px; gap: 8px; align-items: end; }}
    .histogram-main, .histogram-side {{ min-width: 0; color: var(--muted); font-size: 11px; }}
    .histogram-svg {{ display: block; margin-top: 4px; overflow: visible; }}
    .histogram-svg rect {{ fill: var(--accent); opacity: 0.78; }}
    .histogram-x-strip {{ width: 100%; height: 46px; border-bottom: 1px solid var(--border); }}
    .histogram-y-strip {{ width: 56px; height: 132px; border-left: 1px solid var(--border); }}
    .histogram-empty {{ margin-top: 4px; color: var(--muted); font-size: 11px; border: 1px dashed var(--border); border-radius: 6px; padding: 8px; }}
    .toolbar {{ display: flex; flex-wrap: wrap; align-items: center; gap: 12px; border: 1px solid var(--border); border-radius: 8px; background: var(--panel); padding: 10px 12px; margin-bottom: 12px; }}
    .toolbar label {{ color: var(--muted); }}
    .toolbar input {{ width: 220px; }}
    .summary {{ border: 1px solid var(--border); border-radius: 8px; background: var(--panel); padding: 12px; margin-bottom: 12px; }}
    .summary h2 {{ font-size: 16px; margin: 0 0 6px; overflow-wrap: anywhere; }}
    .summary p {{ margin: 4px 0; color: var(--muted); }}
    .summary .score {{ color: var(--warning); }}
    .summary .delta-detail {{ display: inline-flex; align-items: center; margin: 5px 0; padding: 2px 8px; border-radius: 999px; border: 1px solid var(--border); font-size: 12px; }}
    .panes {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; min-height: 68vh; }}
    .pane {{ border: 1px solid var(--border); border-radius: 8px; background: var(--panel); min-width: 0; display: flex; flex-direction: column; }}
    .pane header {{ display: flex; justify-content: space-between; gap: 10px; padding: 9px 10px; border-bottom: 1px solid var(--border); color: var(--fg); font-weight: 650; }}
    .pane header a {{ color: var(--accent); font-weight: 400; text-decoration: none; }}
    .viewport {{ position: relative; flex: 1; min-height: 420px; overflow: hidden; background: #050505; cursor: grab; }}
    .viewport.dragging {{ cursor: grabbing; }}
    .viewport img {{ position: absolute; top: 50%; left: 50%; max-width: none; transform-origin: 0 0; user-select: none; -webkit-user-drag: none; }}
    .missing {{ position: absolute; inset: 0; display: none; align-items: center; justify-content: center; color: var(--muted); border: 1px dashed #444; margin: 16px; border-radius: 8px; }}
    .pane footer {{ min-height: 34px; border-top: 1px solid var(--border); padding: 8px 10px; color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }}
    ul {{ padding-left: 18px; margin: 10px 0 0; }}
    @media (max-width: 1180px) {{ body {{ grid-template-columns: 1fr; }} aside {{ min-height: auto; border-right: 0; border-bottom: 1px solid var(--border); }} .list {{ max-height: 240px; }} .panes {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body data-sgfx-screenshot-viewer="true">
  <aside>
    <h1>Screenshot review viewer</h1>
    <div class="meta">Profile {escape(viewer.profile_id)} | {viewer.item_count} item(s)</div>
    <ul>{guardrails}</ul>
    <div class="list" data-list>{item_buttons or '<p class="hint">No screenshot pairs were generated.</p>'}</div>
  </aside>
  <main>
    <div class="toolbar">
      <label for="zoom">Sync zoom</label>
      <input id="zoom" data-zoom type="range" min="25" max="400" value="100">
      <span data-zoom-label>100%</span>
      <button type="button" data-reset>Reset pan</button>
    </div>
    <section class="summary">
      <h2 data-title>No screenshot selected</h2>
      <p data-summary>Select a screenshot from the left list.</p>
      <p data-visual></p>
      <p data-escalation></p>
      <p class="delta-detail" data-delta></p>
      <p class="score" data-score></p>
    </section>
    <section class="panes">
      {_image_pane("Expected", "expected")}
      {_image_pane("Actual", "actual")}
      {_image_pane("Diff", "diff")}
    </section>
  </main>
  <script id="sgfx-viewer-data" type="application/json">{payload}</script>
  <script>
    (() => {{
      const data = JSON.parse(document.getElementById('sgfx-viewer-data').textContent);
      const items = data.items || [];
      const byKey = new Map(items.map((item) => [item.key, item]));
      const title = document.querySelector('[data-title]');
      const summary = document.querySelector('[data-summary]');
      const visual = document.querySelector('[data-visual]');
      const escalation = document.querySelector('[data-escalation]');
      const delta = document.querySelector('[data-delta]');
      const score = document.querySelector('[data-score]');
      const zoomInput = document.querySelector('[data-zoom]');
      const zoomLabel = document.querySelector('[data-zoom-label]');
      const reset = document.querySelector('[data-reset]');
      const buttons = Array.from(document.querySelectorAll('button[data-key]'));
      const panes = ['expected', 'actual', 'diff'];
      const state = {{ scale: 1, x: 0, y: 0 }};

      const applyTransform = () => {{
        zoomLabel.textContent = `${{Math.round(state.scale * 100)}}%`;
        panes.forEach((name) => {{
          const image = document.querySelector(`[data-image="${{name}}"]`);
          if (!image || image.hidden) return;
          image.style.transform = `translate(${{state.x}}px, ${{state.y}}px) scale(${{state.scale}}) translate(-50%, -50%)`;
        }});
      }};

      const setPane = (name, uri, path) => {{
        const image = document.querySelector(`[data-image="${{name}}"]`);
        const missing = document.querySelector(`[data-missing="${{name}}"]`);
        const footer = document.querySelector(`[data-path="${{name}}"]`);
        const open = document.querySelector(`[data-open="${{name}}"]`);
        footer.textContent = path || 'missing';
        open.href = uri || '#';
        if (!uri) {{
          image.hidden = true;
          image.removeAttribute('src');
          missing.style.display = 'flex';
          return;
        }}
        missing.style.display = 'none';
        image.hidden = false;
        image.src = uri;
        image.onload = applyTransform;
      }};

      const select = (key) => {{
        const item = byKey.get(key) || items[0];
        if (!item) return;
        buttons.forEach((button) => button.classList.toggle('active', button.dataset.key === item.key));
        window.location.hash = encodeURIComponent(item.key);
        title.textContent = `${{item.key}} [${{item.classification}} / ${{item.visual_classification}}]`;
        summary.textContent = item.summary || '';
        visual.textContent = item.visual_summary || '';
        escalation.textContent = item.escalation_path ? `Escalation path: ${{item.escalation_path}}` : '';
        delta.textContent = item.diff_delta_label || '';
        delta.className = `delta-detail ${{item.diff_delta_level ? `delta-${{item.diff_delta_level}}` : ''}}`;
        delta.hidden = !item.diff_delta_label;
        score.textContent = item.review_score ? `Review score: ${{item.review_score.toFixed(2)}}` : '';
        setPane('expected', item.expected_uri, item.expected_path);
        setPane('actual', item.actual_uri, item.actual_path);
        setPane('diff', item.diff_uri, item.diff_path);
        applyTransform();
      }};

      buttons.forEach((button) => button.addEventListener('click', () => select(button.dataset.key)));
      zoomInput.addEventListener('input', () => {{
        state.scale = Number(zoomInput.value) / 100;
        applyTransform();
      }});
      reset.addEventListener('click', () => {{
        state.x = 0;
        state.y = 0;
        applyTransform();
      }});

      document.querySelectorAll('.viewport').forEach((viewport) => {{
        let drag = null;
        viewport.addEventListener('pointerdown', (event) => {{
          drag = {{ x: event.clientX, y: event.clientY, baseX: state.x, baseY: state.y }};
          viewport.classList.add('dragging');
          viewport.setPointerCapture(event.pointerId);
        }});
        viewport.addEventListener('pointermove', (event) => {{
          if (!drag) return;
          state.x = drag.baseX + event.clientX - drag.x;
          state.y = drag.baseY + event.clientY - drag.y;
          applyTransform();
        }});
        viewport.addEventListener('pointerup', () => {{
          drag = null;
          viewport.classList.remove('dragging');
        }});
      }});

      const hashKey = decodeURIComponent(window.location.hash.replace(/^#/, ''));
      select(hashKey && byKey.has(hashKey) ? hashKey : (items[0] && items[0].key));
    }})();
  </script>
</body>
</html>
"""
