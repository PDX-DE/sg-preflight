"""Rack performance / VRAM budget evidence from a RAMSES logcat capture.

When a car is exercised on a rack, the RAMSES engine emits periodic performance
lines to logcat: an average framerate, a frame-delta, and VRAM usage split into
total / static-resource / display-renderer, plus a CPU-usage line. Today SGFX has
a performance lane but no local runner — it can only ask the operator to paste in
external links. This reads an operator-supplied logcat capture (read-only), pulls
those numbers into per-metric samples and a summary, and — when the operator gives
a budget — reports which metrics sit within it.

The numbers are measured evidence for a human reviewer against the operator's own
budget; this is not a standalone pass/fail on visual QA.
"""

from __future__ import annotations

import re
from pathlib import Path
from statistics import fmean
from typing import Any

# RAMSES periodic-log line formats (engine output contract):
#   "Avg framerate: 7.49 FPS [minFrameTime 2370us, maxFrameTime 337774us], drawCalls (0/0/0), numFrames 17"
_NATIVE_FPS_RE = re.compile(r"Avg framerate:\s*([\d.]+)\s*FPS")
#   "Avg framerate=8.14fps target=33.00ms|30.00fps frames=18 avg delay=21.83ms interval=2.21s"
_AAR_FPS_RE = re.compile(r"Avg framerate=([\d.]+)fps")
_AAR_DELAY_RE = re.compile(r"avg delay=([\d.]+)ms")
#   "Avg frame delta 127.34ms min=33.07ms max=847.34ms"
_FRAME_DELTA_RE = re.compile(r"Avg frame delta\s+([\d.]+)ms")
#   "staticRes VRAM usage/cache (20746/0 KB)"
_STATIC_VRAM_RE = re.compile(r"staticRes VRAM usage/cache\s*\((\d+)/\d+\s*KB\)")
#   "DR VRAM usage 43597 KB"
_DR_VRAM_RE = re.compile(r"DR VRAM usage\s*(\d+)\s*KB")
#   "Total VRAM usage 64343 KB"
_TOTAL_VRAM_RE = re.compile(r"Total VRAM usage\s*(\d+)\s*KB")
#   "CPU usage: 42%"
_CPU_RE = re.compile(r"CPU usage:\s*(\d+)\s*%")

# metric key -> (regex, cast, "higher_is_better")
_METRICS: tuple[tuple[str, re.Pattern[str], type, bool], ...] = (
    ("fps", _NATIVE_FPS_RE, float, True),
    ("aar_fps", _AAR_FPS_RE, float, True),
    ("frame_delay_ms", _AAR_DELAY_RE, float, False),
    ("frame_delta_ms", _FRAME_DELTA_RE, float, False),
    ("vram_total_kb", _TOTAL_VRAM_RE, int, False),
    ("vram_static_kb", _STATIC_VRAM_RE, int, False),
    ("vram_dr_kb", _DR_VRAM_RE, int, False),
    ("cpu_percent", _CPU_RE, int, False),
)

# budget key -> (metric, kind) where kind is "min" (measured must be >= budget)
# or "max" (measured must be <= budget).
_BUDGET_RULES: dict[str, tuple[str, str]] = {
    "min_fps": ("fps", "min"),
    "max_frame_delta_ms": ("frame_delta_ms", "max"),
    "max_vram_total_kb": ("vram_total_kb", "max"),
    "max_vram_static_kb": ("vram_static_kb", "max"),
    "max_vram_dr_kb": ("vram_dr_kb", "max"),
    "max_cpu_percent": ("cpu_percent", "max"),
}


def parse_ramses_log(text: str) -> dict[str, Any]:
    """Pull RAMSES performance samples out of a logcat capture."""

    samples: dict[str, list[float]] = {key: [] for key, _, _, _ in _METRICS}
    matched_lines = 0
    for line in text.splitlines():
        line_matched = False
        for key, pattern, cast, _ in _METRICS:
            match = pattern.search(line)
            if match:
                try:
                    samples[key].append(cast(match.group(1)))
                except (ValueError, IndexError):
                    continue
                line_matched = True
        if line_matched:
            matched_lines += 1

    summary: dict[str, dict[str, float]] = {}
    for key, values in samples.items():
        if not values:
            continue
        summary[key] = {
            "count": len(values),
            "min": round(min(values), 2),
            "max": round(max(values), 2),
            "avg": round(fmean(values), 2),
        }
    return {"summary": summary, "matched_lines": matched_lines}


def evaluate_against_budget(
    summary: dict[str, dict[str, float]],
    budget: dict[str, float] | None,
) -> dict[str, Any]:
    """Compare a summary against an operator budget, metric by metric."""

    if not budget:
        return {"state": "measured_only", "checks": [], "over_budget": 0}
    checks: list[dict[str, Any]] = []
    over = 0
    for budget_key, limit in budget.items():
        rule = _BUDGET_RULES.get(budget_key)
        if rule is None:
            continue
        metric, kind = rule
        stats = summary.get(metric)
        if not stats:
            checks.append({"metric": metric, "budget_key": budget_key, "limit": limit, "status": "no_data"})
            continue
        # Compare the worst observed value against the limit.
        observed = stats["min"] if kind == "min" else stats["max"]
        if kind == "min":
            within = observed >= limit
        else:
            within = observed <= limit
        if not within:
            over += 1
        checks.append(
            {
                "metric": metric,
                "budget_key": budget_key,
                "limit": limit,
                "observed": observed,
                "status": "within_budget" if within else "over_budget",
            }
        )
    return {
        "state": "within_budget" if over == 0 else "over_budget",
        "checks": checks,
        "over_budget": over,
    }


def build_rack_performance_report(
    log_path: Path | str,
    *,
    budget: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Parse a RAMSES logcat capture and evaluate it against an optional budget."""

    path = Path(log_path)
    if not path.is_file():
        return {"state": "no_capture", "log_path": str(path), "summary": {}, "budget_evaluation": {}}
    text = path.read_text(encoding="utf-8", errors="ignore")
    parsed = parse_ramses_log(text)
    summary = parsed["summary"]
    evaluation = evaluate_against_budget(summary, budget)
    state = "no_samples" if not summary else evaluation.get("state", "measured_only")
    return {
        "state": state,
        "log_path": str(path),
        "matched_lines": parsed["matched_lines"],
        "summary": summary,
        "budget": budget or {},
        "budget_evaluation": evaluation,
    }


_METRIC_LABELS = {
    "fps": "Framerate (fps)",
    "aar_fps": "Scheduling framerate (fps)",
    "frame_delay_ms": "Frame delay (ms)",
    "frame_delta_ms": "Frame delta (ms)",
    "vram_total_kb": "VRAM total (KB)",
    "vram_static_kb": "VRAM static (KB)",
    "vram_dr_kb": "VRAM display-renderer (KB)",
    "cpu_percent": "CPU (%)",
}


def rack_performance_markdown(report: dict[str, Any]) -> str:
    lines = ["# Rack performance / VRAM", ""]
    state = report.get("state")
    if state == "no_capture":
        lines.append(f"No logcat capture found at `{report.get('log_path', '')}`.")
        lines.append("")
        return "\n".join(lines)
    if state == "no_samples":
        lines.append("The capture had no RAMSES performance lines to read.")
        lines.append(f"- Lines scanned with a match: {report.get('matched_lines', 0)}")
        lines.append("")
        return "\n".join(lines)

    evaluation = report.get("budget_evaluation") or {}
    if evaluation.get("state") == "within_budget":
        lines.append("Every metric with a budget is within it.")
    elif evaluation.get("state") == "over_budget":
        lines.append(f"{evaluation.get('over_budget', 0)} metric(s) are over the operator budget.")
    else:
        lines.append("Measured performance from the capture (no budget set, so nothing is judged).")
    lines.append("")

    summary = report.get("summary") or {}
    lines.append("| Metric | Min | Avg | Max | Samples |")
    lines.append("| --- | --- | --- | --- | --- |")
    for key, _, _, _ in _METRICS:
        stats = summary.get(key)
        if not stats:
            continue
        label = _METRIC_LABELS.get(key, key)
        lines.append(f"| {label} | {stats['min']} | {stats['avg']} | {stats['max']} | {stats['count']} |")
    lines.append("")

    checks = evaluation.get("checks") or []
    if checks:
        lines.append("## Against budget")
        lines.append("")
        lines.append("| Metric | Budget | Observed | Status |")
        lines.append("| --- | --- | --- | --- |")
        for check in checks:
            label = _METRIC_LABELS.get(check["metric"], check["metric"])
            observed = check.get("observed", "-")
            status = check["status"].replace("_", " ")
            lines.append(f"| {label} | {check.get('budget_key')}={check.get('limit')} | {observed} | {status} |")
        lines.append("")
    lines.append("_Measured evidence against the operator's budget; not a standalone visual-QA pass._")
    lines.append("")
    return "\n".join(lines)


def write_rack_performance_report(report: dict[str, Any], output_path: Path | str) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rack_performance_markdown(report), encoding="utf-8")
    return output_path
