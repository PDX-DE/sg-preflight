"""H-31 risk score sparkline — visual trend signal for one profile.

Pulls the last N risk scores from `full_qa_history.read_full_qa_run_list`,
renders an inline SVG bar chart (no external charting library), and exposes
an ASCII-block fallback (`▁▂▃▄▅▆▇█`) for CLI text rendering. When fewer than
three runs are recorded, the helpers honestly emit an "Insufficient history"
fallback instead of a misleading sparkline per `[[phase-j-automated-verdict-trajectory]]`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


MIN_RUNS_FOR_TREND = 3

# 1/8 → full-block ASCII steps for CLI rendering.
_ASCII_BLOCKS = ("▁", "▂", "▃", "▄", "▅", "▆", "▇", "█")


@dataclass(frozen=True)
class SparklineData:
    profile_id: str = ""
    risk_scores: tuple[int, ...] = ()
    risk_levels: tuple[str, ...] = ()
    completed_at: tuple[str, ...] = ()
    has_trend: bool = False
    fallback_reason: str = ""


def _normalize_score(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):  # avoid bool-as-int
        return None
    if isinstance(value, (int, float)):
        if not isinstance(value, int):
            value = int(value)
        if value < 0 or value > 100:
            return None
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        score = int(float(text))
    except (TypeError, ValueError):
        return None
    if score < 0 or score > 100:
        return None
    return score


def build_sparkline_data(
    runs: Sequence[dict],
    *,
    profile_id: str = "",
) -> SparklineData:
    """Walk the run list (newest-first, matching `read_full_qa_run_list`) and
    return a `SparklineData` with the recovered risk scores in CHRONOLOGICAL
    order (oldest→newest). When fewer than `MIN_RUNS_FOR_TREND` runs have a
    parseable risk score, returns `has_trend=False` so the caller can render
    the honest "Insufficient history" fallback rather than a misleading chart.
    """
    if not runs:
        return SparklineData(profile_id=profile_id, fallback_reason="No recorded runs")
    scores: list[int] = []
    levels: list[str] = []
    timestamps: list[str] = []
    for entry in runs:
        if not isinstance(entry, dict):
            continue
        score = _normalize_score(entry.get("risk_score"))
        if score is None:
            continue
        scores.append(score)
        levels.append(str(entry.get("risk_level", "") or ""))
        timestamps.append(str(entry.get("completed_at_utc", "") or ""))
    # Convert newest-first to chronological order so a left-to-right sparkline
    # reads as time progressing.
    scores.reverse()
    levels.reverse()
    timestamps.reverse()
    if len(scores) < MIN_RUNS_FOR_TREND:
        return SparklineData(
            profile_id=profile_id,
            risk_scores=tuple(scores),
            risk_levels=tuple(levels),
            completed_at=tuple(timestamps),
            has_trend=False,
            fallback_reason=f"Insufficient history ({len(scores)} run{'s' if len(scores) != 1 else ''})",
        )
    return SparklineData(
        profile_id=profile_id,
        risk_scores=tuple(scores),
        risk_levels=tuple(levels),
        completed_at=tuple(timestamps),
        has_trend=True,
    )


def render_sparkline_svg(
    data: SparklineData,
    *,
    width: int = 96,
    height: int = 18,
    bar_padding: int = 1,
) -> str:
    """Inline SVG bar chart. Returns an empty string when `has_trend` is False
    so callers can defer to `sparkline_fallback_text`."""
    if not data.has_trend or not data.risk_scores:
        return ""
    scores = data.risk_scores
    bar_count = len(scores)
    if bar_count == 0:
        return ""
    # Risk scores in the SGFX risk_scoring module live on 0–100; map directly.
    max_score = 100
    bar_width = max(2, (width - bar_padding * (bar_count - 1)) // bar_count)
    bars: list[str] = []
    for index, score in enumerate(scores):
        ratio = max(0.0, min(1.0, score / max_score))
        bar_height = max(2, int(round((height - 2) * ratio)))
        x = index * (bar_width + bar_padding)
        y = height - bar_height
        # Per-bar colour by score band: green <30, yellow 30-59, red ≥60.
        if score >= 60:
            colour = "#f07f72"
        elif score >= 30:
            colour = "#e8c07d"
        else:
            colour = "#57d68d"
        bars.append(
            f'<rect x="{x}" y="{y}" width="{bar_width}" height="{bar_height}" fill="{colour}" '
            f'data-score="{score}"></rect>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="Risk score over last {bar_count} runs">'
        f'{"".join(bars)}'
        '</svg>'
    )


def render_sparkline_ascii(data: SparklineData) -> str:
    """ASCII unicode-block sparkline for CLI text output.

    Returns an empty string when the trend is unavailable so the caller can
    surface `fallback_reason` instead.
    """
    if not data.has_trend or not data.risk_scores:
        return ""
    blocks: list[str] = []
    for score in data.risk_scores:
        ratio = max(0.0, min(1.0, score / 100.0))
        # Map 0–1 → 0..7 indices into the block ramp.
        index = min(len(_ASCII_BLOCKS) - 1, int(round(ratio * (len(_ASCII_BLOCKS) - 1))))
        blocks.append(_ASCII_BLOCKS[index])
    return "".join(blocks)


def sparkline_fallback_text(data: SparklineData) -> str:
    """Operator-facing fallback when the sparkline can't render honestly."""
    if data.has_trend:
        return ""
    return data.fallback_reason or "Insufficient history"
