from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
import re
from typing import Any

from sg_preflight.bmw_pipeline_diagnostics import diagnostic_pattern_anchors

try:
    from PIL import Image, ImageChops, ImageFilter, ImageOps, ImageStat
except ImportError:  # pragma: no cover - exercised through graceful fallback
    Image = None
    ImageChops = None
    ImageFilter = None
    ImageOps = None
    ImageStat = None


_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
_CANDIDATE_DIR_NAMES = (
    "actual",
    "candidate",
    "candidates",
    "current",
    "generated",
    "output",
    "outputs",
    "result",
    "results",
)
_DIFF_DIR_NAMES = (
    "diff",
    "diffs",
    "difference",
    "differences",
)
_CLASSIFICATION_PRIORITY = {
    "needs_review": 0,
    "dimension_mismatch": 1,
    "missing_candidate": 2,
    "missing_baseline": 3,
    "near_identical": 4,
    "unchanged": 5,
}
_NEAR_IDENTICAL_RATIO = 0.001
_NEAR_IDENTICAL_MEAN = 1.0
BMW_COMPARATOR_BLOCK_CONFIG_LIST: tuple[tuple[int, float], ...] = (
    (1, 0.10),
    (2, 0.05),
    (4, 0.01),
    (8, 0.005),
    (16, 0.001),
)
BMW_COMPARATOR_SOURCE = "ci/scripts/asset_testing/image_cmp.py BLOCK_CONFIG_LIST"
BMW_COMPARATOR_ENVELOPE_WARNING = (
    "Warning: visual thresholds exceed the BMW comparator envelope; SGFX will still surface the "
    "BMW-parity signal and will not label BMW-failing pairs as cosmetic."
)


@dataclass(frozen=True)
class VisualDiffThresholds:
    cosmetic_max_changed_ratio: float = 0.001
    cosmetic_max_mean_abs_diff: float = 1.0
    structural_min_changed_ratio: float = 0.08
    structural_min_mean_abs_diff: float = 8.0
    structural_min_review_score: float = 45.0


DEFAULT_VISUAL_DIFF_THRESHOLDS = VisualDiffThresholds()


def visual_thresholds_exceed_bmw_envelope(thresholds: VisualDiffThresholds) -> bool:
    return (
        thresholds.cosmetic_max_changed_ratio > DEFAULT_VISUAL_DIFF_THRESHOLDS.cosmetic_max_changed_ratio
        or thresholds.cosmetic_max_mean_abs_diff > DEFAULT_VISUAL_DIFF_THRESHOLDS.cosmetic_max_mean_abs_diff
    )


@dataclass(frozen=True)
class BmwComparatorTier:
    delta_threshold: int
    allowed_fraction: float
    actual_fraction: float
    pixel_count: int
    total_pixels: int
    passed: bool


@dataclass(frozen=True)
class ScreenshotRoot:
    kind: str
    path: str
    image_count: int


@dataclass(frozen=True)
class ScreenshotPair:
    key: str
    classification: str
    visual_classification: str
    summary: str
    visual_summary: str = ""
    escalation_path: str = ""
    baseline_path: str = ""
    candidate_path: str = ""
    baseline_size: tuple[int, int] | tuple[()] = ()
    candidate_size: tuple[int, int] | tuple[()] = ()
    exact_match: bool = False
    changed_pixel_ratio: float | None = None
    mean_abs_diff: float | None = None
    review_score: float | None = None
    psnr_db: float | None = None
    laplacian_variance_ratio: float | None = None
    anomaly_hints: tuple[str, ...] = ()
    diff_image_path: str = ""
    diagnostic_chain_status: str = ""
    diagnostic_chain_steps: tuple[dict[str, str], ...] = ()
    diagnostic_pattern_ids: tuple[str, ...] = ()
    escalation_message: str = ""
    bmw_comparator_would_pass: bool | None = None
    bmw_comparator_summary: str = ""
    bmw_comparator_tiers: tuple[BmwComparatorTier, ...] = ()
    priority: bool = False


@dataclass(frozen=True)
class ScreenshotTriageReport:
    profile_id: str
    project_root: str
    generated_at_utc: str
    expected_root: str = ""
    diff_roots: tuple[ScreenshotRoot, ...] = ()
    candidate_roots: tuple[ScreenshotRoot, ...] = ()
    pair_count: int = 0
    unchanged_count: int = 0
    near_identical_count: int = 0
    needs_review_count: int = 0
    missing_candidate_count: int = 0
    missing_baseline_count: int = 0
    dimension_mismatch_count: int = 0
    cosmetic_likely_pass_count: int = 0
    structural_likely_review_count: int = 0
    unclear_manual_review_count: int = 0
    visual_thresholds: VisualDiffThresholds = field(default_factory=lambda: DEFAULT_VISUAL_DIFF_THRESHOLDS)
    external_classifier_status: str = "disabled"
    image_backend: str = "none"
    bmw_comparator_source: str = BMW_COMPARATOR_SOURCE
    bmw_disabled_test_count: int = 0
    priority_keys: tuple[str, ...] = ()
    pairs: tuple[ScreenshotPair, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ScreenshotTriageBundle:
    report: ScreenshotTriageReport
    json_path: Path
    markdown_path: Path
    html_path: Path
    diff_root: Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _find_expected_root(project_root: Path, explicit_root: Path | None = None) -> Path | None:
    if explicit_root is not None:
        resolved = explicit_root.resolve()
        return resolved if resolved.exists() else None
    candidate = project_root / "export" / "tests" / "expected"
    return candidate.resolve() if candidate.exists() else None


def _discover_candidate_roots(
    project_root: Path,
    explicit_roots: tuple[Path, ...] = (),
) -> tuple[tuple[Path, str], ...]:
    matches: list[tuple[Path, str]] = []
    seen: set[Path] = set()

    def consider(path: Path, kind: str, *, allow_empty: bool = False) -> None:
        if not path.exists() or not path.is_dir():
            return
        resolved = path.resolve()
        if resolved in seen:
            return
        image_count = sum(1 for item in resolved.rglob("*") if item.is_file() and item.suffix.lower() in _IMAGE_SUFFIXES)
        if image_count <= 0 and not allow_empty:
            return
        seen.add(resolved)
        matches.append((resolved, kind))

    for path in explicit_roots:
        consider(path, "operator-supplied", allow_empty=True)

    tests_root = project_root / "export" / "tests"
    if tests_root.exists():
        expected_root = _find_expected_root(project_root)
        for name in _CANDIDATE_DIR_NAMES:
            consider(tests_root / name, "auto-detected")
        for child in sorted(tests_root.iterdir()):
            if not child.is_dir():
                continue
            lowered = child.name.lower()
            if expected_root is not None and child.resolve() == expected_root:
                continue
            if lowered in _CANDIDATE_DIR_NAMES or any(token in lowered for token in ("candidate", "result", "output", "actual")):
                consider(child, "auto-detected")
    return tuple(matches)


def _discover_diff_roots(
    project_root: Path,
    explicit_roots: tuple[Path, ...] = (),
) -> tuple[tuple[Path, str], ...]:
    matches: list[tuple[Path, str]] = []
    seen: set[Path] = set()

    def consider(path: Path, kind: str, *, allow_empty: bool = False) -> None:
        if not path.exists() or not path.is_dir():
            return
        resolved = path.resolve()
        if resolved in seen:
            return
        image_count = sum(1 for item in resolved.rglob("*") if item.is_file() and item.suffix.lower() in _IMAGE_SUFFIXES)
        if image_count <= 0 and not allow_empty:
            return
        seen.add(resolved)
        matches.append((resolved, kind))

    for path in explicit_roots:
        consider(path, "operator-supplied", allow_empty=True)

    tests_root = project_root / "export" / "tests"
    if tests_root.exists():
        for name in _DIFF_DIR_NAMES:
            consider(tests_root / name, "auto-detected")
        for child in sorted(tests_root.iterdir()):
            if not child.is_dir():
                continue
            lowered = child.name.lower()
            if lowered in _DIFF_DIR_NAMES or "diff" in lowered:
                consider(child, "auto-detected")
    return tuple(matches)


def _image_map(root: Path) -> dict[str, Path]:
    mapping: dict[str, Path] = {}
    if not root.exists():
        return mapping
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _IMAGE_SUFFIXES:
            continue
        relative = path.relative_to(root)
        key = str(relative.with_suffix("")).replace("\\", "/").lower()
        mapping.setdefault(key, path.resolve())
    return mapping


def _normalize_test_key(value: str) -> str:
    return Path(str(value or "").replace("\\", "/")).with_suffix("").as_posix().casefold()


def _test_key_aliases(key: str) -> set[str]:
    normalized = _normalize_test_key(key)
    aliases = {normalized}
    name = Path(normalized).name
    if name:
        aliases.add(name.casefold())
    return aliases


def _disabled_test_names(project_root: Path) -> set[str]:
    config_path = project_root / "export" / "tests" / "test_config.lua"
    try:
        text = config_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    disabled: set[str] = set()
    for match in re.finditer(r"\bdisableTest\s*\((.*?)\)", text, flags=re.IGNORECASE | re.DOTALL):
        call_body = match.group(1)
        for quote_match in re.finditer(r"['\"]([^'\"]+)['\"]", call_body):
            name = _normalize_test_key(quote_match.group(1))
            if name:
                disabled.add(name)
                disabled.add(Path(name).name.casefold())
    return disabled


def _is_disabled_test_key(key: str, disabled_tests: set[str]) -> bool:
    if not disabled_tests:
        return False
    return bool(_test_key_aliases(key) & disabled_tests)


def _ordered_keys(
    baseline_map: dict[str, Path],
    candidate_map: dict[str, Path],
    priority_keys: tuple[str, ...],
) -> list[str]:
    all_keys = set(baseline_map) | set(candidate_map)
    normalized_priority = [Path(item).with_suffix("").name.lower() for item in priority_keys]

    def sort_key(key: str) -> tuple[int, int, str]:
        name = Path(key).name.lower()
        priority = 1
        index = len(normalized_priority)
        if name in normalized_priority:
            priority = 0
            index = normalized_priority.index(name)
        return (priority, index, key)

    return sorted(all_keys, key=sort_key)


def _load_rgba(path: Path) -> Any | None:
    if Image is None:
        return None
    with Image.open(path) as handle:
        return handle.convert("RGBA")


def _binary_identical(first: Path, second: Path) -> bool:
    return first.read_bytes() == second.read_bytes()


def _nonzero_diff_mask(diff: Any) -> Any:
    channels = diff.split()
    if not channels:
        return diff
    mask = channels[0]
    for channel in channels[1:]:
        mask = ImageChops.lighter(mask, channel)
    return mask


def _bmw_comparator_from_diff(diff_mask: Any, total_pixels: int) -> tuple[bool, str, tuple[BmwComparatorTier, ...]]:
    if total_pixels <= 0:
        return False, "BMW comparator would fail: image has no pixels.", ()
    histogram = diff_mask.histogram()
    tiers: list[BmwComparatorTier] = []
    would_pass = True
    for threshold, allowed_fraction in BMW_COMPARATOR_BLOCK_CONFIG_LIST:
        pixel_count = int(sum(histogram[threshold + 1 :])) if histogram else 0
        actual_fraction = pixel_count / total_pixels
        tier_passed = actual_fraction <= allowed_fraction
        would_pass = would_pass and tier_passed
        tiers.append(
            BmwComparatorTier(
                delta_threshold=threshold,
                allowed_fraction=allowed_fraction,
                actual_fraction=actual_fraction,
                pixel_count=pixel_count,
                total_pixels=total_pixels,
                passed=tier_passed,
            )
        )
    if would_pass:
        return True, "BMW comparator would pass this pair.", tuple(tiers)
    failing = next((tier for tier in tiers if not tier.passed), tiers[-1])
    return (
        False,
        (
            "BMW comparator would fail this pair: "
            f"{failing.pixel_count}/{failing.total_pixels} pixels exceed delta > {failing.delta_threshold} "
            f"({failing.actual_fraction:.3%} > {failing.allowed_fraction:.3%})."
        ),
        tuple(tiers),
    )


_LAPLACIAN_KERNEL = (0, -1, 0, -1, 4, -1, 0, -1, 0)


def _image_quality_metrics(baseline_gray: Any, candidate_gray: Any) -> dict[str, float | None]:
    import math

    diff_histogram = ImageChops.difference(baseline_gray, candidate_gray).histogram()
    total = sum(diff_histogram)
    mse = (
        sum(count * (value * value) for value, count in enumerate(diff_histogram)) / total
        if total
        else 0.0
    )
    psnr_db = round(10.0 * math.log10((255.0 * 255.0) / mse), 2) if mse > 0 else None

    # Pillow clips negative kernel responses to zero; both sides clip alike, so the
    # variance ratio stays a comparable sharpness signal even if absolute values differ
    # from an unclipped Laplacian.
    kernel = ImageFilter.Kernel((3, 3), _LAPLACIAN_KERNEL, scale=1)
    baseline_var = float(ImageStat.Stat(baseline_gray.filter(kernel)).var[0])
    candidate_var = float(ImageStat.Stat(candidate_gray.filter(kernel)).var[0])
    ratio = round(candidate_var / baseline_var, 4) if baseline_var > 0 else None
    return {"psnr_db": psnr_db, "laplacian_variance_ratio": ratio}


def _auto_review_signals(
    baseline: Any,
    candidate: Any,
    *,
    changed_ratio: float,
    mean_abs_diff: float,
) -> tuple[float, tuple[str, ...], dict[str, float | None]]:
    if ImageOps is None or ImageStat is None or ImageFilter is None:
        return 0.0, (), {}

    baseline_gray = ImageOps.grayscale(baseline)
    candidate_gray = ImageOps.grayscale(candidate)
    baseline_brightness = float(ImageStat.Stat(baseline_gray).mean[0])
    candidate_brightness = float(ImageStat.Stat(candidate_gray).mean[0])
    brightness_shift = abs(candidate_brightness - baseline_brightness)

    baseline_alpha = float(ImageStat.Stat(baseline.getchannel("A")).mean[0])
    candidate_alpha = float(ImageStat.Stat(candidate.getchannel("A")).mean[0])
    alpha_shift = abs(candidate_alpha - baseline_alpha)

    baseline_edges = baseline_gray.filter(ImageFilter.FIND_EDGES)
    candidate_edges = candidate_gray.filter(ImageFilter.FIND_EDGES)
    edge_delta = float(ImageStat.Stat(ImageChops.difference(baseline_edges, candidate_edges)).mean[0])

    hints: list[str] = []
    if changed_ratio >= 0.35:
        hints.append("possible camera/state mismatch or large scene-level delta")
    if mean_abs_diff >= 12.0 and changed_ratio <= 0.08:
        hints.append("possible localized artifact or material/shader drift")
    if brightness_shift >= 10.0 and edge_delta <= 6.0:
        hints.append("possible lighting/shader delta")
    if edge_delta >= 12.0 and changed_ratio >= 0.03:
        hints.append("possible geometry/camera/normal mismatch")
    if alpha_shift >= 8.0:
        hints.append("possible transparency/mask issue")
    if (
        changed_ratio >= 0.05
        and mean_abs_diff >= 8.0
        and brightness_shift < 10.0
        and edge_delta < 12.0
    ):
        hints.append("possible texture/material patch")

    quality = _image_quality_metrics(baseline_gray, candidate_gray)
    ratio = quality.get("laplacian_variance_ratio")
    if ratio is not None and ratio <= 0.90:
        hints.append("possible sharpness/detail loss (Laplacian variance dropped)")

    score = min(
        100.0,
        (changed_ratio * 120.0)
        + (mean_abs_diff * 2.5)
        + brightness_shift
        + (edge_delta * 1.75)
        + alpha_shift,
    )
    return round(score, 2), tuple(dict.fromkeys(hints)), quality


def _visual_diff_classification(
    classification: str,
    *,
    changed_ratio: float | None,
    mean_abs_diff: float | None,
    review_score: float | None,
    anomaly_hints: tuple[str, ...],
    thresholds: VisualDiffThresholds,
    bmw_comparator_would_pass: bool | None = None,
) -> tuple[str, str]:
    if bmw_comparator_would_pass is False:
        return (
            "structural_likely_review",
            "BMW comparator would fail this pair; manual review remains required.",
        )
    if classification in {"unchanged", "near_identical"}:
        return (
            "cosmetic_likely_pass",
            "Pixel delta is absent or below the cosmetic threshold; manual review remains required.",
        )
    if classification in {"missing_candidate", "missing_baseline"}:
        return (
            "unclear_manual_review",
            "Required image evidence is missing, so the screenshot needs operator review.",
        )
    if classification == "dimension_mismatch":
        return (
            "structural_likely_review",
            "Image dimensions differ, which is treated as a structural review signal.",
        )
    if changed_ratio is None or mean_abs_diff is None:
        return (
            "unclear_manual_review",
            "Image comparison metrics are unavailable, so the screenshot needs operator review.",
        )
    if (
        changed_ratio <= thresholds.cosmetic_max_changed_ratio
        and mean_abs_diff <= thresholds.cosmetic_max_mean_abs_diff
    ):
        return (
            "cosmetic_likely_pass",
            "Pixel delta is within the cosmetic threshold; manual review remains required.",
        )
    structural_hint = any(
        token in hint.lower()
        for hint in anomaly_hints
        for token in ("geometry", "camera", "normal", "state mismatch")
    )
    if (
        changed_ratio >= thresholds.structural_min_changed_ratio
        or mean_abs_diff >= thresholds.structural_min_mean_abs_diff
        or (review_score or 0.0) >= thresholds.structural_min_review_score
        or structural_hint
    ):
        return (
            "structural_likely_review",
            "Pixel delta crosses structural-review thresholds or carries a geometry/camera signal.",
        )
    return (
        "unclear_manual_review",
        "Pixel delta is above cosmetic tolerance but below structural thresholds; operator review is required.",
    )


def _missing_candidate_diagnostics(profile_id: str, project_root: Path, key: str) -> dict[str, Any]:
    profile_root = project_root.name or str(profile_id or "PROFILE").upper()
    test_name = Path(str(key)).with_suffix("").name or "<test>"
    diff_hint = Path("cars") / "BMW" / profile_root / "export" / "tests" / "diff" / f"{test_name}_*.png"
    config_hint = Path("cars") / "BMW" / profile_root / "export" / "tests" / "test_config.lua"
    config_path = project_root / "export" / "tests" / "test_config.lua"
    config_status = "missing"
    config_detail = f"BMW Git test config was not found at {config_hint.as_posix()}."
    if config_path.is_file():
        try:
            config_text = config_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            config_status = "unavailable"
            config_detail = f"BMW Git test config exists but could not be read at {config_hint.as_posix()}."
        else:
            config_status = "available" if test_name in config_text else "incomplete"
            config_detail = (
                f"BMW Git test config is readable and mentions `{test_name}`."
                if config_status == "available"
                else f"BMW Git test config is readable but `{test_name}` was not found."
            )
    pattern_ids = ("actual_image_not_rendered_diff_missing", "magenta_tint_in_actual_image")
    anchors = diagnostic_pattern_anchors("actual_image_not_rendered_diff_missing", "magenta_tint_in_actual_image")
    steps = (
        {
            "id": "actual-image",
            "label": "Actual image",
            "status": "missing",
            "detail": f"Expected actual image is absent; diff hint: {diff_hint.as_posix()} absent.",
        },
        {
            "id": "test-config",
            "label": "BMW Git test config",
            "status": config_status,
            "detail": config_detail,
        },
        {
            "id": "known-patterns",
            "label": "Known diagnostic patterns",
            "status": "available",
            "detail": "Missing actual/diff output and context-dependent magenta guidance are available.",
        },
        {
            "id": "read-refresh",
            "label": "BMW Git/SVN read-refresh",
            "status": "confirmation_pending",
            "detail": "Operator confirmation is required before git pull or svn update.",
        },
        {
            "id": "retry-capture",
            "label": "Retry screenshot capture",
            "status": "not_run",
            "detail": "Retry after read-refresh or after correcting a missing reference.",
        },
        {
            "id": "asset-doctor",
            "label": "Asset doctor",
            "status": "not_run",
            "detail": "Scan referenced scene, texture, shader, and environment files if retry still misses the actual image.",
        },
    )
    escalation_message = (
        f"{profile_root} `{test_name}`: actual screenshot image is missing. "
        f"Check `{config_hint.as_posix()}` and expected diff path `{diff_hint.as_posix()}`. "
        "If operator-confirmed read-refresh and retry still do not produce the actual image, escalate to data prep / CI team."
    )
    return {
        "status": "incomplete",
        "test_name": test_name,
        "diff_hint": diff_hint.as_posix(),
        "config_hint": config_hint.as_posix(),
        "pattern_ids": pattern_ids,
        "anchors": anchors,
        "steps": steps,
        "escalation_message": escalation_message,
    }


def _missing_candidate_summary(profile_id: str, project_root: Path, key: str) -> str:
    diagnostics = _missing_candidate_diagnostics(profile_id, project_root, key)
    diff_hint = str(diagnostics["diff_hint"])
    config_hint = str(diagnostics["config_hint"])
    test_name = str(diagnostics["test_name"])
    anchors = tuple(str(anchor) for anchor in diagnostics.get("anchors", ()))
    anchor_lines = "\n".join(f"- {anchor}" for anchor in anchors) or "- unavailable"
    return (
        "BMW pipeline did not render an actual image for this test.\n\n"
        "This result is incomplete until SGFX can produce the actual image or exhaust the diagnostic chain. "
        "Manual review remains required.\n\n"
        "Pink/magenta content is context-dependent: it can be intentional test background, declared placeholder "
        "graphics, or a missing/mislinked dependency. Color alone is not used as the verdict.\n\n"
        "Investigate:\n"
        f"- Check disk: expected actual image is absent; diff hint: {diff_hint} absent\n"
        f"- Check BMW Git test config for `{test_name}` scene: {config_hint}\n"
        "- Check referenced scene, texture, shader, and environment files.\n"
        "- If the operator confirms, refresh BMW Git and SVN read-only sources, then retry.\n"
        "- If still missing, use asset-doctor findings and the copy-ready escalation message.\n\n"
        f"Diagnostic anchors:\n{anchor_lines}\n\n"
        "Operator action: run the diagnostic chain and escalate to data prep / CI team if the actual image stays missing."
    )


def _diff_metrics(
    baseline_path: Path,
    candidate_path: Path,
    *,
    diff_root: Path,
    key: str,
) -> tuple[
    str,
    str,
    tuple[int, int],
    tuple[int, int],
    bool,
    float | None,
    float | None,
    float | None,
    tuple[str, ...],
    str,
    bool | None,
    str,
    tuple[BmwComparatorTier, ...],
    dict[str, float | None],
]:
    if Image is None or ImageChops is None or ImageOps is None or ImageStat is None:
        exact_match = _binary_identical(baseline_path, candidate_path)
        classification = "unchanged" if exact_match else "needs_review"
        summary = (
            "Images are byte-identical."
            if exact_match
            else "Pillow is not available, so only byte-level comparison ran. Needs human review."
        )
        return (
            classification,
            summary,
            (),
            (),
            exact_match,
            0.0 if exact_match else None,
            0.0 if exact_match else None,
            0.0 if exact_match else None,
            (),
            "",
            None,
            "BMW comparator unavailable because the image backend is not available.",
            (),
            {},
        )

    baseline = _load_rgba(baseline_path)
    candidate = _load_rgba(candidate_path)
    if baseline is None or candidate is None:
        return (
            "needs_review",
            "Image backend could not load one of the files. Needs human review.",
            (),
            (),
            False,
            None,
            None,
            None,
            (),
            "",
            None,
            "BMW comparator unavailable because one image could not be loaded.",
            (),
            {},
        )

    baseline_size = tuple(int(value) for value in baseline.size)
    candidate_size = tuple(int(value) for value in candidate.size)
    if baseline_size != candidate_size:
        return (
            "dimension_mismatch",
            f"Dimension mismatch: baseline {baseline_size[0]}x{baseline_size[1]} vs candidate {candidate_size[0]}x{candidate_size[1]}.",
            baseline_size,
            candidate_size,
            False,
            None,
            None,
            None,
            (),
            "",
            False,
            "BMW comparator would fail: image dimensions differ.",
            (),
            {},
        )

    diff = ImageChops.difference(baseline, candidate)
    diff_mask = _nonzero_diff_mask(diff)
    total_pixels = baseline_size[0] * baseline_size[1]
    bmw_would_pass, bmw_summary, bmw_tiers = _bmw_comparator_from_diff(diff_mask, total_pixels)
    if diff_mask.getbbox() is None:
        return (
            "unchanged",
            "Images are pixel-identical.",
            baseline_size,
            candidate_size,
            True,
            0.0,
            0.0,
            0.0,
            (),
            "",
            bmw_would_pass,
            bmw_summary,
            bmw_tiers,
            {},
        )

    histogram = diff_mask.point(lambda value: 255 if value else 0).histogram()
    changed_pixels = total_pixels - int(histogram[0] if histogram else 0)
    changed_ratio = changed_pixels / total_pixels if total_pixels else 0.0
    stat = ImageStat.Stat(diff)
    mean_abs_diff = sum(float(value) for value in stat.mean) / len(stat.mean)

    classification = "near_identical" if changed_ratio <= _NEAR_IDENTICAL_RATIO and mean_abs_diff <= _NEAR_IDENTICAL_MEAN else "needs_review"
    review_score, anomaly_hints, quality_metrics = _auto_review_signals(
        baseline,
        candidate,
        changed_ratio=changed_ratio,
        mean_abs_diff=mean_abs_diff,
    )
    summary = (
        f"Near-identical drift: {changed_ratio:.4%} changed pixels, mean absolute diff {mean_abs_diff:.3f}."
        if classification == "near_identical"
        else f"Visual change detected: {changed_ratio:.4%} changed pixels, mean absolute diff {mean_abs_diff:.3f}. Needs human review."
    )

    diff_path = ""
    if diff_root:
        diff_root.mkdir(parents=True, exist_ok=True)
        safe_name = key.replace("/", "__").replace("\\", "__")
        diff_path = str((diff_root / f"{safe_name}.png").resolve())
        ImageOps.autocontrast(diff_mask).save(diff_path)

    return (
        classification,
        summary,
        baseline_size,
        candidate_size,
        False,
        changed_ratio,
        mean_abs_diff,
        review_score if classification == "needs_review" else 0.0,
        anomaly_hints if classification == "needs_review" else (),
        diff_path,
        bmw_would_pass,
        bmw_summary,
        bmw_tiers,
        quality_metrics,
    )


def build_screenshot_triage(
    profile_id: str,
    project_root: Path,
    *,
    expected_root: Path | None = None,
    candidate_roots: tuple[Path, ...] = (),
    diff_reference_roots: tuple[Path, ...] = (),
    priority_names: tuple[str, ...] = (),
    diff_root: Path | None = None,
    visual_thresholds: VisualDiffThresholds = DEFAULT_VISUAL_DIFF_THRESHOLDS,
    external_classifier_requested: bool = False,
) -> ScreenshotTriageReport:
    resolved_project_root = project_root.resolve()
    resolved_expected_root = _find_expected_root(resolved_project_root, expected_root)
    discovered_candidates = _discover_candidate_roots(resolved_project_root, candidate_roots)
    discovered_diff_roots = _discover_diff_roots(resolved_project_root, diff_reference_roots)
    baseline_map = _image_map(resolved_expected_root) if resolved_expected_root is not None else {}

    candidate_map: dict[str, Path] = {}
    candidate_root_items: list[ScreenshotRoot] = []
    for root, root_kind in discovered_candidates:
        root_map = _image_map(root)
        candidate_root_items.append(
            ScreenshotRoot(
                kind=root_kind,
                path=str(root),
                image_count=len(root_map),
            )
        )
        for key, path in root_map.items():
            candidate_map.setdefault(key, path)

    diff_root_items = [
        ScreenshotRoot(
            kind=root_kind,
            path=str(root),
            image_count=len(_image_map(root)),
        )
        for root, root_kind in discovered_diff_roots
    ]

    pairs: list[ScreenshotPair] = []
    counts = {
        "unchanged": 0,
        "near_identical": 0,
        "needs_review": 0,
        "missing_candidate": 0,
        "missing_baseline": 0,
        "dimension_mismatch": 0,
    }
    visual_counts = {
        "cosmetic_likely_pass": 0,
        "structural_likely_review": 0,
        "unclear_manual_review": 0,
    }

    ordered_keys = _ordered_keys(baseline_map, candidate_map, priority_names)
    normalized_priority = {Path(item).with_suffix("").name.lower() for item in priority_names}
    disabled_tests = _disabled_test_names(resolved_project_root)
    skipped_disabled_count = 0
    for key in ordered_keys:
        if _is_disabled_test_key(key, disabled_tests):
            skipped_disabled_count += 1
            continue
        baseline_path = baseline_map.get(key)
        candidate_path = candidate_map.get(key)
        priority = Path(key).name.lower() in normalized_priority

        if baseline_path is None:
            classification = "missing_baseline"
            summary = "Candidate exists but no matching baseline was found."
            visual_classification, visual_summary = _visual_diff_classification(
                classification,
                changed_ratio=None,
                mean_abs_diff=None,
                review_score=None,
                anomaly_hints=(),
                thresholds=visual_thresholds,
                bmw_comparator_would_pass=None,
            )
            pair = ScreenshotPair(
                key=key,
                classification=classification,
                visual_classification=visual_classification,
                summary=summary,
                visual_summary=visual_summary,
                candidate_path=str(candidate_path) if candidate_path else "",
                priority=priority,
            )
        elif candidate_path is None:
            classification = "missing_candidate"
            diagnostics = _missing_candidate_diagnostics(profile_id, resolved_project_root, key)
            summary = _missing_candidate_summary(profile_id, resolved_project_root, key)
            visual_classification, visual_summary = _visual_diff_classification(
                classification,
                changed_ratio=None,
                mean_abs_diff=None,
                review_score=None,
                anomaly_hints=(),
                thresholds=visual_thresholds,
                bmw_comparator_would_pass=None,
            )
            pair = ScreenshotPair(
                key=key,
                classification=classification,
                visual_classification=visual_classification,
                summary=summary,
                visual_summary=visual_summary,
                escalation_path="data_prep_or_ci_team",
                baseline_path=str(baseline_path),
                diagnostic_chain_status=str(diagnostics.get("status", "incomplete")),
                diagnostic_chain_steps=tuple(
                    item for item in diagnostics.get("steps", ()) if isinstance(item, dict)
                ),
                diagnostic_pattern_ids=tuple(str(item) for item in diagnostics.get("pattern_ids", ())),
                escalation_message=str(diagnostics.get("escalation_message", "")),
                priority=priority,
            )
        else:
            (
                classification,
                summary,
                baseline_size,
                candidate_size,
                exact_match,
                changed_ratio,
                mean_abs_diff,
                review_score,
                anomaly_hints,
                diff_path,
                bmw_would_pass,
                bmw_summary,
                bmw_tiers,
                quality_metrics,
            ) = _diff_metrics(
                baseline_path,
                candidate_path,
                diff_root=diff_root or Path(),
                key=key,
            )
            visual_classification, visual_summary = _visual_diff_classification(
                classification,
                changed_ratio=changed_ratio,
                mean_abs_diff=mean_abs_diff,
                review_score=review_score,
                anomaly_hints=anomaly_hints,
                thresholds=visual_thresholds,
                bmw_comparator_would_pass=bmw_would_pass,
            )
            pair = ScreenshotPair(
                key=key,
                classification=classification,
                visual_classification=visual_classification,
                summary=summary,
                visual_summary=visual_summary,
                baseline_path=str(baseline_path),
                candidate_path=str(candidate_path),
                baseline_size=baseline_size,
                candidate_size=candidate_size,
                exact_match=exact_match,
                changed_pixel_ratio=changed_ratio,
                mean_abs_diff=mean_abs_diff,
                review_score=review_score,
                psnr_db=quality_metrics.get("psnr_db"),
                laplacian_variance_ratio=quality_metrics.get("laplacian_variance_ratio"),
                anomaly_hints=anomaly_hints,
                diff_image_path=diff_path,
                bmw_comparator_would_pass=bmw_would_pass,
                bmw_comparator_summary=bmw_summary,
                bmw_comparator_tiers=bmw_tiers,
                priority=priority,
            )

        counts[classification] += 1
        visual_counts[pair.visual_classification] += 1
        pairs.append(pair)

    pairs.sort(
        key=lambda item: (
            0 if item.priority else 1,
            _CLASSIFICATION_PRIORITY.get(item.classification, 99),
            -(item.review_score or 0.0),
            item.key,
        )
    )

    notes = []
    if resolved_expected_root is None:
        notes.append("No `export/tests/expected` baseline root was detected under the project.")
    if resolved_expected_root is not None and not discovered_candidates:
        notes.append("No candidate screenshot root was detected locally. This is preparation/triage scaffolding only.")
    if discovered_candidates:
        notes.append(
            "Candidate screenshot roots were detected locally: "
            + ", ".join(f"{Path(item.path).name} ({item.kind})" for item in candidate_root_items[:4])
        )
        if not any(item.image_count > 0 for item in candidate_root_items):
            notes.append("Candidate roots are present, but they currently contain no screenshot image payload.")
    if diff_root_items:
        notes.append(
            "Reference diff roots were detected locally: "
            + ", ".join(f"{Path(item.path).name} ({item.kind})" for item in diff_root_items[:4])
        )
        if not any(item.image_count > 0 for item in diff_root_items):
            notes.append("Reference diff roots are present, but they currently contain no diff image payload.")
    if skipped_disabled_count:
        notes.append(
            f"Skipped {skipped_disabled_count} BMW-disabled screenshot test(s) from `export/tests/test_config.lua`."
        )
    notes.append("Classifications are conservative. `needs_review` is not a regression verdict.")
    notes.append(
        "Visual diff labels are conservative evidence buckets. Manual review remains required."
    )
    notes.append(f"BMW comparator parity signal follows `{BMW_COMPARATOR_SOURCE}` and is evidence, not approval.")
    if visual_thresholds_exceed_bmw_envelope(visual_thresholds):
        notes.append(BMW_COMPARATOR_ENVELOPE_WARNING)
    notes.append("Auto anomaly hints are heuristic triage signals, not defect verdicts.")
    external_classifier_status = "disabled"
    if external_classifier_requested:
        external_classifier_status = "unavailable"
        notes.append(
            "External vision classifier was requested, but no provider is configured in this local build; no external service call was made."
        )
    else:
        notes.append("External vision classifier is disabled by default; no external service call was made.")
    if Image is None:
        notes.append("Pillow is not available, so only byte-level fallback comparison can run.")

    return ScreenshotTriageReport(
        profile_id=profile_id,
        project_root=str(resolved_project_root),
        generated_at_utc=_utc_now(),
        expected_root=str(resolved_expected_root) if resolved_expected_root is not None else "",
        diff_roots=tuple(diff_root_items),
        candidate_roots=tuple(candidate_root_items),
        pair_count=len(pairs),
        unchanged_count=counts["unchanged"],
        near_identical_count=counts["near_identical"],
        needs_review_count=counts["needs_review"],
        missing_candidate_count=counts["missing_candidate"],
        missing_baseline_count=counts["missing_baseline"],
        dimension_mismatch_count=counts["dimension_mismatch"],
        cosmetic_likely_pass_count=visual_counts["cosmetic_likely_pass"],
        structural_likely_review_count=visual_counts["structural_likely_review"],
        unclear_manual_review_count=visual_counts["unclear_manual_review"],
        visual_thresholds=visual_thresholds,
        external_classifier_status=external_classifier_status,
        image_backend="pillow" if Image is not None else "none",
        bmw_disabled_test_count=skipped_disabled_count,
        priority_keys=tuple(item for item in priority_names if item),
        pairs=tuple(pairs),
        notes=tuple(notes),
    )


def _markdown(report: ScreenshotTriageReport) -> str:
    lines = [
        f"# Screenshot triage - {report.profile_id}",
        "",
        f"Generated at: {report.generated_at_utc}",
        f"Project root: `{report.project_root}`",
        f"Expected root: `{report.expected_root}`" if report.expected_root else "Expected root: not found",
        f"Image backend: `{report.image_backend}`",
        "",
        "## Summary",
        f"- Pairs considered: {report.pair_count}",
        f"- Unchanged: {report.unchanged_count}",
        f"- Near-identical: {report.near_identical_count}",
        f"- Needs review: {report.needs_review_count}",
        f"- Missing candidate: {report.missing_candidate_count}",
        f"- Missing baseline: {report.missing_baseline_count}",
        f"- Dimension mismatch: {report.dimension_mismatch_count}",
        f"- Visual cosmetic likely pass: {report.cosmetic_likely_pass_count}",
        f"- Visual structural likely review: {report.structural_likely_review_count}",
        f"- Visual unclear manual review: {report.unclear_manual_review_count}",
        f"- BMW-disabled tests skipped: {report.bmw_disabled_test_count}",
        f"- BMW comparator source: `{report.bmw_comparator_source}`",
        f"- External classifier status: `{report.external_classifier_status}`",
        (
            "- Visual thresholds: "
            f"cosmetic <= {report.visual_thresholds.cosmetic_max_changed_ratio:.6f} changed ratio / "
            f"{report.visual_thresholds.cosmetic_max_mean_abs_diff:.3f} mean diff; "
            f"structural >= {report.visual_thresholds.structural_min_changed_ratio:.6f} changed ratio / "
            f"{report.visual_thresholds.structural_min_mean_abs_diff:.3f} mean diff / "
            f"{report.visual_thresholds.structural_min_review_score:.2f} review score"
        ),
        "",
        "## Candidate roots",
    ]
    if report.candidate_roots:
        for item in report.candidate_roots:
            lines.append(f"- `{item.path}` ({item.image_count} image(s), {item.kind})")
    else:
        lines.append("- No candidate root detected.")

    lines.extend(["", "## Reference diff roots"])
    if report.diff_roots:
        for item in report.diff_roots:
            lines.append(f"- `{item.path}` ({item.image_count} image(s), {item.kind})")
    else:
        lines.append("- No reference diff root detected.")

    lines.extend(["", "## Notes"])
    lines.extend(f"- {line}" for line in report.notes)

    lines.extend(["", "## Pair results"])
    if report.pairs:
        for pair in report.pairs[:40]:
            lines.append(f"- {pair.key} [{pair.classification} / {pair.visual_classification}]")
            lines.append(f"  - {pair.summary}")
            if pair.visual_summary:
                lines.append(f"  - Visual label: `{pair.visual_classification}` - {pair.visual_summary}")
            if pair.bmw_comparator_summary:
                bmw_state = (
                    "pass"
                    if pair.bmw_comparator_would_pass is True
                    else "fail"
                    if pair.bmw_comparator_would_pass is False
                    else "unavailable"
                )
                lines.append(f"  - BMW comparator: {bmw_state} - {pair.bmw_comparator_summary}")
                for tier in pair.bmw_comparator_tiers:
                    tier_state = "pass" if tier.passed else "fail"
                    lines.append(
                        "    - "
                        f"> {tier.delta_threshold}: {tier.pixel_count}/{tier.total_pixels} "
                        f"({tier.actual_fraction:.3%}) <= {tier.allowed_fraction:.3%} [{tier_state}]"
                    )
            if pair.escalation_path:
                lines.append(f"  - Escalation path: `{pair.escalation_path}`")
            if pair.review_score:
                lines.append(f"  - Review score: `{pair.review_score:.2f}`")
            if pair.anomaly_hints:
                lines.append(f"  - Auto hints: `{'; '.join(pair.anomaly_hints)}`")
            if pair.baseline_path:
                lines.append(f"  - Baseline: `{pair.baseline_path}`")
            if pair.candidate_path:
                lines.append(f"  - Candidate: `{pair.candidate_path}`")
            if pair.diff_image_path:
                lines.append(f"  - Diff: `{pair.diff_image_path}`")
    else:
        lines.append("- No screenshot pairs were generated.")
    return "\n".join(lines).strip() + "\n"


def _html(report: ScreenshotTriageReport) -> str:
    rows = []
    for pair in report.pairs:
        baseline_uri = Path(pair.baseline_path).resolve().as_uri() if pair.baseline_path else ""
        candidate_uri = Path(pair.candidate_path).resolve().as_uri() if pair.candidate_path else ""
        diff_uri = Path(pair.diff_image_path).resolve().as_uri() if pair.diff_image_path else ""
        baseline = (
            f'<a href="{escape(baseline_uri)}" target="_blank" rel="noreferrer"><img src="{escape(baseline_uri)}" alt="{escape(pair.key)} baseline"></a>'
            if baseline_uri
            else "<div class='missing'>No baseline</div>"
        )
        candidate = (
            f'<a href="{escape(candidate_uri)}" target="_blank" rel="noreferrer"><img src="{escape(candidate_uri)}" alt="{escape(pair.key)} candidate"></a>'
            if candidate_uri
            else "<div class='missing'>No candidate</div>"
        )
        diff = (
            f'<a href="{escape(diff_uri)}" target="_blank" rel="noreferrer"><img src="{escape(diff_uri)}" alt="{escape(pair.key)} diff"></a>'
            if diff_uri
            else "<div class='missing'>No diff</div>"
        )
        bmw_state = (
            "pass"
            if pair.bmw_comparator_would_pass is True
            else "fail"
            if pair.bmw_comparator_would_pass is False
            else "unavailable"
        )
        bmw_rows = "".join(
            "<tr>"
            f"<td>&gt; {tier.delta_threshold}</td>"
            f"<td>{tier.pixel_count}/{tier.total_pixels}</td>"
            f"<td>{tier.actual_fraction:.3%}</td>"
            f"<td>{tier.allowed_fraction:.3%}</td>"
            f"<td>{'pass' if tier.passed else 'fail'}</td>"
            "</tr>"
            for tier in pair.bmw_comparator_tiers
        )
        bmw_html = ""
        if pair.bmw_comparator_summary:
            bmw_html = (
                f"<p><strong>BMW comparator:</strong> {escape(bmw_state)} - "
                f"{escape(pair.bmw_comparator_summary)}</p>"
                + (
                    "<table class='bmw-tiers'><thead><tr><th>Delta</th><th>Pixels</th>"
                    "<th>Actual</th><th>Allowed</th><th>Result</th></tr></thead>"
                    f"<tbody>{bmw_rows}</tbody></table>"
                    if bmw_rows
                    else ""
                )
            )
        rows.append(
            (
                "<article class='pair'>"
                f"<h2>{escape(pair.key)} [{escape(pair.classification)} / {escape(pair.visual_classification)}]</h2>"
                f"<p>{escape(pair.summary)}</p>"
                + (
                    f"<p><strong>Visual label:</strong> {escape(pair.visual_classification)} - {escape(pair.visual_summary)}</p>"
                    if pair.visual_summary
                    else ""
                )
                + bmw_html
                + (
                    f"<p><strong>Escalation path:</strong> {escape(pair.escalation_path)}</p>"
                    if pair.escalation_path
                    else ""
                )
                + (
                    f"<p><strong>Review score:</strong> {pair.review_score:.2f}</p>"
                    if pair.review_score
                    else ""
                )
                + (
                    f"<p><strong>Auto hints:</strong> {escape('; '.join(pair.anomaly_hints))}</p>"
                    if pair.anomaly_hints
                    else ""
                )
                + "<div class='grid'>"
                + f"<div><strong>Baseline</strong>{baseline}</div>"
                + f"<div><strong>Candidate</strong>{candidate}</div>"
                + f"<div><strong>Diff</strong>{diff}</div>"
                + "</div>"
                + "</article>"
            )
        )

    notes = "".join(f"<li>{escape(note)}</li>" for note in report.notes)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Screenshot triage - {escape(report.profile_id)}</title>
  <style>
    body {{ background:#0d1117; color:#e6edf3; font:15px/1.5 Segoe UI,sans-serif; margin:0; padding:24px; }}
    h1,h2 {{ color:#ffd36a; }}
    .grid {{ display:grid; gap:16px; grid-template-columns:repeat(3,minmax(220px,1fr)); }}
    .pair {{ margin:24px 0; padding:16px; border:1px solid rgba(255,255,255,0.12); border-radius:12px; background:#161b22; }}
    .bmw-tiers {{ border-collapse:collapse; margin:8px 0 12px; width:100%; color:#c9d1d9; font-size:13px; }}
    .bmw-tiers th, .bmw-tiers td {{ border:1px solid rgba(255,255,255,0.12); padding:4px 6px; text-align:left; }}
    img {{ width:100%; height:auto; background:#000; border-radius:8px; }}
    .missing {{ padding:24px; border:1px dashed rgba(255,255,255,0.15); border-radius:8px; color:#9aa4b2; }}
    code {{ color:#8fe4a4; }}
  </style>
</head>
<body>
  <h1>Screenshot triage - {escape(report.profile_id)}</h1>
  <p><strong>Project root:</strong> <code>{escape(report.project_root)}</code></p>
  <p><strong>Expected root:</strong> <code>{escape(report.expected_root or "not found")}</code></p>
  <p><strong>Summary:</strong> {report.pair_count} pair(s), {report.needs_review_count} needs review, {report.missing_candidate_count} missing candidate, {report.dimension_mismatch_count} dimension mismatch.</p>
  <p><strong>Visual labels:</strong> {report.cosmetic_likely_pass_count} cosmetic likely pass, {report.structural_likely_review_count} structural likely review, {report.unclear_manual_review_count} unclear manual review. External classifier: {escape(report.external_classifier_status)}.</p>
  <p><strong>BMW comparator source:</strong> <code>{escape(report.bmw_comparator_source)}</code></p>
  <ul>{notes}</ul>
  {''.join(rows) if rows else '<p>No screenshot pairs were generated.</p>'}
</body>
</html>
"""


def materialize_screenshot_triage(
    profile_id: str,
    project_root: Path,
    output_root: Path,
    *,
    expected_root: Path | None = None,
    candidate_roots: tuple[Path, ...] = (),
    diff_reference_roots: tuple[Path, ...] = (),
    priority_names: tuple[str, ...] = (),
    visual_thresholds: VisualDiffThresholds = DEFAULT_VISUAL_DIFF_THRESHOLDS,
    external_classifier_requested: bool = False,
) -> ScreenshotTriageBundle:
    output_root.mkdir(parents=True, exist_ok=True)
    diff_root = output_root / "diffs"
    report = build_screenshot_triage(
        profile_id,
        project_root,
        expected_root=expected_root,
        candidate_roots=candidate_roots,
        diff_reference_roots=diff_reference_roots,
        priority_names=priority_names,
        diff_root=diff_root,
        visual_thresholds=visual_thresholds,
        external_classifier_requested=external_classifier_requested,
    )
    json_path = output_root / "screenshot-triage.json"
    markdown_path = output_root / "screenshot-triage.md"
    html_path = output_root / "screenshot-triage.html"
    json_path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    html_path.write_text(_html(report), encoding="utf-8")
    return ScreenshotTriageBundle(
        report=report,
        json_path=json_path,
        markdown_path=markdown_path,
        html_path=html_path,
        diff_root=diff_root,
    )
