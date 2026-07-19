"""Verdict and review-priority scoring for daily snapshot battery results: risk keywords, ranking, and baseline gap detection."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


_REVIEW_PRIORITY_ORDER = {"P0": 3, "P1": 2, "P2": 1, "P3": 0}


_KNOWN_RISK_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("LightFX", ("lightfx", "lights_", "light_")),
    ("WelcomeFX", ("welcomefx", "welcome_animation", "welcome animation")),
    ("Iconic Glow", ("iconicglow", "iconic_glow", "iconic glow")),
    ("Selective Yellow", ("selectiveyellow", "selective_yellow", "selective yellow")),
    ("mirrors", ("mirror", "mirrors")),
    ("rims", ("rim", "rims", "wheel")),
    ("logos", ("logo", "logos")),
    ("flaps", ("flap", "flaps")),
    ("doors", ("door", "doors")),
    ("hood", ("hood",)),
    ("tailgate", ("tailgate",)),
    ("trimline", ("trimline", "trim_line")),
    ("country variant", ("countryvariant", "country_variant", "country variant")),
)


def _battery_verdict(
    *,
    expected_count: int,
    actual_count: int,
    diff_count: int,
    compare_ok: bool,
    status: str,
    missing_expected_baseline: str = "",
    target_output_present: bool = False,
    error: str = "",
    proxy_files: tuple[str, ...] | list[str] = (),
) -> str:
    if status == "blocked":
        return "blocked"
    if status == "proxy_completed" and proxy_files:
        return "proxy_candidate_ready"
    lowered_error = error.lower()
    if "viewer exited with code" in lowered_error:
        return "runtime_crash"
    if actual_count == 0 and diff_count == 0:
        return "blocked"
    if missing_expected_baseline:
        if actual_count > 0 and target_output_present:
            return "baseline_candidate_ready"
        if actual_count > 0 and not target_output_present:
            return "scenario_output_missing"
        return "baseline_missing"
    if "no such file or directory" in lowered_error and "expected" in lowered_error:
        return "baseline_missing"
    if expected_count == 0 and actual_count > 0:
        return "baseline_missing"
    if diff_count > 0:
        return "needs_manual_review"
    if compare_ok and expected_count > 0 and actual_count > 0:
        return "likely_ok"
    return "inconclusive"


def _extract_missing_expected_baseline(error: str) -> str:
    if not error:
        return ""
    match = re.search(r"No such file or directory:\s*'([^']+)'", error, flags=re.IGNORECASE)
    if not match:
        match = re.search(r"Expected screenshot missing:\s*([^\r\n]+)", error, flags=re.IGNORECASE)
    if not match:
        return ""
    missing_path = match.group(1).replace("\\\\", "\\")
    try:
        return Path(missing_path).name
    except OSError:
        return missing_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]


def _scenario_image_names(root: Path) -> tuple[str, ...]:
    if not root.exists() or not root.is_dir():
        return ()
    names = sorted(
        path.name
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES
    )
    return tuple(names)


def _battery_gap_recommendation(item: BmwBatteryResult) -> str:
    if item.verdict == "runtime_crash":
        return "Treat as a technical blocker before manual screenshot review."
    if item.verdict == "scenario_output_missing":
        return "Treat as config/output mismatch before human visual review."
    if item.verdict == "needs_manual_review":
        return "Open the diff payload and record a human pass/fail decision."
    if item.verdict == "baseline_candidate_ready":
        return "Candidate output exists; manual baseline review can start."
    if item.verdict == "proxy_candidate_ready":
        return "Proxy output exists; it validates local lamp-state rendering but not the exact beam-cone effect."
    if item.verdict == "likely_ok":
        return "Keep as low-priority evidence; no automatic verdict is implied."
    if item.verdict == "blocked":
        return "Unblock or rerun the screenshot check before visual comparison."
    return "Generate or locate the expected baseline before visual comparison."


def _review_priority_text_blob(item: BmwBatteryResult) -> str:
    parts = [
        item.filter_name,
        item.verdict,
        item.status,
        item.error,
        item.missing_expected_baseline,
        *item.actual_files,
        *item.expected_files,
        *item.diff_files,
        *item.proxy_files,
        *item.notes,
    ]
    compacted = " ".join(str(part) for part in parts if str(part).strip())
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", compacted)
    return f"{compacted} {spaced}".casefold()


def _review_priority_risk_labels(item: BmwBatteryResult) -> tuple[str, ...]:
    blob = _review_priority_text_blob(item)
    labels: list[str] = []
    for label, needles in _KNOWN_RISK_KEYWORDS:
        if any(needle.casefold() in blob for needle in needles):
            labels.append(label)
    return tuple(dict.fromkeys(labels))


def _review_priority_has_dimension_mismatch(item: BmwBatteryResult) -> bool:
    blob = _review_priority_text_blob(item)
    return "dimension mismatch" in blob or "size mismatch" in blob


def _review_priority_reason(item: BmwBatteryResult) -> str:
    if _review_priority_has_dimension_mismatch(item):
        reason = "Screenshot dimensions differ and need blocker-level triage before visual review."
    elif item.verdict == "needs_manual_review":
        reason = "Diff payload exists and needs a human pass/fail decision."
    elif item.verdict == "baseline_candidate_ready":
        reason = "Exact candidate output exists, but the baseline still needs a human review decision."
    elif item.verdict == "proxy_candidate_ready":
        reason = "Proxy output exists, but the exact requested screenshot still needs review."
    elif item.verdict == "likely_ok":
        reason = "Exact compare completed locally with no visible diff; keep as low-priority review evidence."
    elif item.verdict == "runtime_crash":
        reason = "Local BMW viewer/runtime crashed during this scenario."
    elif item.verdict == "scenario_output_missing":
        reason = "Requested screenshot candidate is missing or emitted under an unexpected name."
    elif item.verdict == "baseline_missing":
        reason = "Critical expected baseline is missing, so a reviewer cannot make a direct comparison yet."
    elif item.verdict == "blocked":
        reason = "Screenshot check is blocked before a candidate can be reviewed."
    else:
        reason = "Needs investigation before this screenshot can be treated as reviewed."
    risk_labels = _review_priority_risk_labels(item)
    if risk_labels:
        reason += f" Known-risk area: {', '.join(risk_labels)}."
    return reason


def _review_priority_score(item: BmwBatteryResult) -> int:
    base = 0
    if _review_priority_has_dimension_mismatch(item):
        base = 98
    elif item.verdict == "runtime_crash":
        base = 100
    elif item.verdict == "needs_manual_review":
        base = 88
    elif item.verdict in {"scenario_output_missing", "baseline_missing"}:
        base = 92
    elif item.verdict == "blocked":
        base = 94
    elif item.verdict == "proxy_candidate_ready":
        base = 72
    elif item.verdict == "baseline_candidate_ready":
        base = 55
    elif item.verdict == "likely_ok":
        base = 18

    family = item.filter_name.casefold()
    family_bonus = 0
    if family == "lights_onlycones":
        family_bonus = 16
    elif family in {"lights_highbeam", "lights_lowbeam"}:
        family_bonus = 10
    elif family.startswith("lights_"):
        family_bonus = 7
    elif family.startswith("openalldoors_"):
        family_bonus = 4
    elif family.startswith("welcome_animation_"):
        family_bonus = 2
    risk_bonus = 20 if _review_priority_risk_labels(item) else 0

    diff_bonus = min(max(item.diff_count, 0), 3) * 3
    actual_bonus = 4 if item.actual_count > 0 else 0
    target_bonus = 5 if item.target_output_present else 0
    proxy_bonus = 4 if item.proxy_files else 0
    return base + family_bonus + risk_bonus + diff_bonus + actual_bonus + target_bonus + proxy_bonus


def _review_priority_signals(item: BmwBatteryResult) -> tuple[str, ...]:
    signals: list[str] = []
    if _review_priority_has_dimension_mismatch(item):
        signals.append("dimension mismatch")
    if item.verdict == "runtime_crash":
        signals.append("runtime crash")
    if item.verdict == "needs_manual_review":
        signals.append("diff review needed")
    if item.verdict == "scenario_output_missing":
        signals.append("missing candidate")
    if item.verdict == "baseline_missing" or item.missing_expected_baseline:
        signals.append("missing baseline")
    if item.verdict == "proxy_candidate_ready":
        signals.append("proxy-only output")
    if item.verdict == "baseline_candidate_ready":
        signals.append("exact unresolved state")
    if item.verdict == "likely_ok":
        signals.append("unchanged exact compare")
    if item.verdict == "blocked":
        signals.append("blocked screenshot check")

    family = item.filter_name.casefold()
    if family == "lights_onlycones":
        signals.append("cone family")
    elif family in {"lights_highbeam", "lights_lowbeam"}:
        signals.append("beam family")
    elif family.startswith("lights_"):
        signals.append("lightfx family")

    if item.diff_count > 0:
        signals.append("diff present")
        signals.append(f"{item.diff_count} diff payload")
    if item.actual_count == 0:
        signals.append("no actual output")
    elif item.actual_count > 1:
        signals.append(f"{item.actual_count} actual outputs")
    if item.target_output_present:
        signals.append("target output present")
    if item.proxy_files:
        signals.append("proxy files present")
    signals.extend(f"known risk: {label}" for label in _review_priority_risk_labels(item))
    return tuple(dict.fromkeys(signals))


def _review_priority_level(item: BmwBatteryResult) -> str:
    if _review_priority_has_dimension_mismatch(item):
        return "P0"
    if item.verdict in {"runtime_crash", "scenario_output_missing", "baseline_missing", "blocked"}:
        return "P0"
    if item.verdict in {"needs_manual_review", "proxy_candidate_ready"}:
        return "P1"
    if item.verdict == "baseline_candidate_ready":
        return "P1" if _review_priority_risk_labels(item) else "P2"
    if item.verdict == "likely_ok":
        return "P2" if _review_priority_risk_labels(item) else "P3"
    return "P3"


def _review_priority_attention_category(level: str) -> str:
    if level == "P0":
        return "must inspect"
    if level == "P1":
        return "inspect before delivery"
    if level == "P2":
        return "normal review"
    return "low-priority / unchanged"


def _ranked_review_priority_key(item: BmwBatteryResult) -> tuple[int, int, int, int, str, str]:
    level = _review_priority_level(item)
    return (
        _REVIEW_PRIORITY_ORDER.get(level, 0),
        _review_priority_score(item),
        item.diff_count,
        item.actual_count,
        item.profile_id.upper(),
        item.filter_name.lower(),
    )


def _review_priority_payload(snapshot: DailyQaSnapshot) -> dict[str, Any]:
    items = sorted(
        snapshot.battery_results,
        key=_ranked_review_priority_key,
        reverse=True,
    )
    ranked = [
        {
            "profile_id": item.profile_id,
            "filter_name": item.filter_name,
            "verdict": item.verdict,
            "priority_level": _review_priority_level(item),
            "priority_score": _review_priority_score(item),
            "attention_category": _review_priority_attention_category(_review_priority_level(item)),
            "signals": list(_review_priority_signals(item)),
            "reason": _review_priority_reason(item),
            "recommendation": _battery_gap_recommendation(item),
            "expected_count": item.expected_count,
            "actual_count": item.actual_count,
            "diff_count": item.diff_count,
            "target_output_present": item.target_output_present,
            "proxy_files": list(item.proxy_files),
            "actual_files": list(item.actual_files),
            "log_path": item.log_path,
        }
        for item in items
        if item.filter_name.strip()
    ]
    return {
        "created_at": snapshot.created_at,
        "scope_profiles": list(snapshot.scope_profiles),
        "ranked_items": ranked,
        "top_five": ranked[:5],
    }


def _snapshot_failure_keys(snapshot: DailyQaSnapshot) -> set[str]:
    failure_keys: set[str] = set()
    for item in snapshot.smoke_results:
        if item.status != "completed" or item.diff_count > 0:
            failure_keys.add(f"smoke:{item.profile_id}:{item.smoke_test}")
    for item in snapshot.battery_results:
        if item.verdict in {"runtime_crash", "scenario_output_missing", "blocked", "baseline_missing", "needs_manual_review"}:
            failure_keys.add(f"battery:{item.profile_id}:{item.filter_name}")
    return failure_keys


def _snapshot_diff_keys(snapshot: DailyQaSnapshot) -> set[str]:
    diff_keys: set[str] = set()
    for item in snapshot.smoke_results:
        if item.diff_count > 0:
            diff_keys.add(f"smoke:{item.profile_id}:{item.smoke_test}")
    for item in snapshot.battery_results:
        if item.verdict == "needs_manual_review":
            diff_keys.add(f"battery:{item.profile_id}:{item.filter_name}")
    return diff_keys


def _snapshot_status_counts(snapshot: DailyQaSnapshot) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in snapshot.battery_results:
        counts[item.verdict] = counts.get(item.verdict, 0) + 1
    for item in snapshot.smoke_results:
        key = f"smoke_{item.status}"
        counts[key] = counts.get(key, 0) + 1
    return counts


def _daily_delta_payload(
    current: DailyQaSnapshot,
    previous: DailyQaSnapshot | None,
    *,
    current_output_root: Path,
    previous_output_root: Path | None = None,
) -> dict[str, Any]:
    if previous is None:
        return {
            "current_created_at": current.created_at,
            "previous_created_at": "",
            "current_output_root": str(current_output_root),
            "previous_output_root": "",
            "scope_profiles": list(current.scope_profiles),
            "new_failures": [],
            "resolved_failures": [],
            "new_screenshot_diffs": [],
            "unchanged_blockers": list(current.blocked_steps),
            "changed_counts": {"current": _snapshot_status_counts(current), "previous": {}},
            "top_five_to_review": list(current.top_review_items[:5]),
        }

    current_failures = _snapshot_failure_keys(current)
    previous_failures = _snapshot_failure_keys(previous)
    current_diffs = _snapshot_diff_keys(current)
    previous_diffs = _snapshot_diff_keys(previous)
    return {
        "current_created_at": current.created_at,
        "previous_created_at": previous.created_at,
        "current_output_root": str(current_output_root),
        "previous_output_root": str(previous_output_root) if previous_output_root is not None else "",
        "scope_profiles": list(current.scope_profiles),
        "new_failures": sorted(current_failures - previous_failures),
        "resolved_failures": sorted(previous_failures - current_failures),
        "new_screenshot_diffs": sorted(current_diffs - previous_diffs),
        "unchanged_blockers": sorted(set(current.blocked_steps).intersection(previous.blocked_steps)),
        "changed_counts": {
            "current": _snapshot_status_counts(current),
            "previous": _snapshot_status_counts(previous),
        },
        "top_five_to_review": list(current.top_review_items[:5]),
    }


def _group_battery_results_by_profile(battery_results: tuple[BmwBatteryResult, ...] | list[BmwBatteryResult]) -> dict[str, list[BmwBatteryResult]]:
    grouped: dict[str, list[BmwBatteryResult]] = {}
    for item in battery_results:
        grouped.setdefault(item.profile_id.strip().upper(), []).append(item)
    return grouped


def _beam_family_diagnostics(
    battery_results: tuple[BmwBatteryResult, ...] | list[BmwBatteryResult],
) -> tuple[str, ...]:
    diagnostics: list[str] = []
    for profile_id, items in sorted(_group_battery_results_by_profile(battery_results).items()):
        by_filter = {item.filter_name: item for item in items}
        control = by_filter.get("lights_drl_front")
        if control is None or control.actual_count <= 0:
            continue
        unresolved_filters = [
            name
            for name in ("lights_LowBeam", "lights_HighBeam", "lights_OnlyCones")
            if (item := by_filter.get(name)) is not None
            and item.actual_count <= 0
            and not item.proxy_files
        ]
        proxy_filters = [
            name
            for name in ("lights_LowBeam", "lights_HighBeam", "lights_OnlyCones")
            if (item := by_filter.get(name)) is not None and item.proxy_files
        ]
        if unresolved_filters:
            unresolved_text = ", ".join(f"`{name}`" for name in unresolved_filters)
            diagnostics.append(
                f"{profile_id}: control `lights_drl_front` generated screenshot payload, but {unresolved_text} still emitted no exact PNG output. "
                "Treat this as a beam-family runtime/content failure, not as a wider battery harness failure."
            )
        if proxy_filters:
            proxy_text = ", ".join(f"`{name}`" for name in proxy_filters)
            diagnostics.append(
                f"{profile_id}: exact beam-cone rendering still fails locally for {proxy_text}, but proxy lamp-state screenshots were generated with `LightCones_isVisible = false`."
            )
    return tuple(diagnostics)


def _battery_baseline_gap_payload(snapshot: DailyQaSnapshot) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for item in snapshot.battery_results:
        if item.verdict not in {"baseline_missing", "baseline_candidate_ready", "scenario_output_missing"}:
            continue
        missing_baseline = item.missing_expected_baseline or _extract_missing_expected_baseline(item.error)
        grouped.setdefault(item.profile_id, []).append(
            {
                "filter_name": item.filter_name,
                "verdict": item.verdict,
                "missing_expected_baseline": missing_baseline or "unknown expected file",
                "target_output_present": "yes" if item.target_output_present else "no",
                "actual_files": ", ".join(item.actual_files) if item.actual_files else "(none)",
                "recommendation": _battery_gap_recommendation(item),
                "error": item.error,
                "log_path": item.log_path,
            }
        )

    return {
        "created_at": snapshot.created_at,
        "scope_profiles": list(snapshot.scope_profiles),
        "profiles": [
            {
                "profile_id": profile_id,
                "gaps": gaps,
            }
            for profile_id, gaps in sorted(grouped.items())
        ],
    }
