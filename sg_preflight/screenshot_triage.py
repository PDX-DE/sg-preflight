from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
from typing import Any

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


@dataclass(frozen=True)
class VisualDiffThresholds:
    cosmetic_max_changed_ratio: float = 0.001
    cosmetic_max_mean_abs_diff: float = 1.0
    structural_min_changed_ratio: float = 0.08
    structural_min_mean_abs_diff: float = 8.0
    structural_min_review_score: float = 45.0


DEFAULT_VISUAL_DIFF_THRESHOLDS = VisualDiffThresholds()


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
    anomaly_hints: tuple[str, ...] = ()
    diff_image_path: str = ""
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


def _auto_review_signals(
    baseline: Any,
    candidate: Any,
    *,
    changed_ratio: float,
    mean_abs_diff: float,
) -> tuple[float, tuple[str, ...]]:
    if ImageOps is None or ImageStat is None or ImageFilter is None:
        return 0.0, ()

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

    score = min(
        100.0,
        (changed_ratio * 120.0)
        + (mean_abs_diff * 2.5)
        + brightness_shift
        + (edge_delta * 1.75)
        + alpha_shift,
    )
    return round(score, 2), tuple(dict.fromkeys(hints))


def _visual_diff_classification(
    classification: str,
    *,
    changed_ratio: float | None,
    mean_abs_diff: float | None,
    review_score: float | None,
    anomaly_hints: tuple[str, ...],
    thresholds: VisualDiffThresholds,
) -> tuple[str, str]:
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


def _missing_candidate_summary(profile_id: str, project_root: Path, key: str) -> str:
    profile_root = project_root.name or str(profile_id or "PROFILE").upper()
    test_name = Path(str(key)).with_suffix("").name or "<test>"
    diff_hint = Path("cars") / "BMW" / profile_root / "export" / "tests" / "diff" / f"{test_name}_*.png"
    config_hint = Path("cars") / "BMW" / profile_root / "export" / "tests" / "test_config.lua"
    return (
        "BMW pipeline did not render an actual image for this test.\n\n"
        "Likely cause: scene init / shader load / missing-asset issue at BMW pipeline level.\n\n"
        "Investigate:\n"
        f"- Check disk: {diff_hint.as_posix()} absent\n"
        f"- Check BMW Git test config for `{test_name}` scene: {config_hint.as_posix()}\n"
        "- Check BMW Ramses error logs (often fall back to pink/magenta when textures/shaders fail to load)\n\n"
        "Operator action: identify root cause and escalate to data prep / CI team if BMW Git asset issue."
    )


def _diff_metrics(
    baseline_path: Path,
    candidate_path: Path,
    *,
    diff_root: Path,
    key: str,
) -> tuple[str, str, tuple[int, int], tuple[int, int], bool, float | None, float | None, float | None, tuple[str, ...], str]:
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
        )

    baseline = _load_rgba(baseline_path)
    candidate = _load_rgba(candidate_path)
    if baseline is None or candidate is None:
        return "needs_review", "Image backend could not load one of the files. Needs human review.", (), (), False, None, None, None, (), ""

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
        )

    diff = ImageChops.difference(baseline, candidate)
    diff_mask = _nonzero_diff_mask(diff)
    if diff_mask.getbbox() is None:
        return "unchanged", "Images are pixel-identical.", baseline_size, candidate_size, True, 0.0, 0.0, 0.0, (), ""

    histogram = diff_mask.point(lambda value: 255 if value else 0).histogram()
    total_pixels = baseline_size[0] * baseline_size[1]
    changed_pixels = total_pixels - int(histogram[0] if histogram else 0)
    changed_ratio = changed_pixels / total_pixels if total_pixels else 0.0
    stat = ImageStat.Stat(diff)
    mean_abs_diff = sum(float(value) for value in stat.mean) / len(stat.mean)

    classification = "near_identical" if changed_ratio <= _NEAR_IDENTICAL_RATIO and mean_abs_diff <= _NEAR_IDENTICAL_MEAN else "needs_review"
    review_score, anomaly_hints = _auto_review_signals(
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
    for key in ordered_keys:
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
            summary = _missing_candidate_summary(profile_id, resolved_project_root, key)
            visual_classification, visual_summary = _visual_diff_classification(
                classification,
                changed_ratio=None,
                mean_abs_diff=None,
                review_score=None,
                anomaly_hints=(),
                thresholds=visual_thresholds,
            )
            pair = ScreenshotPair(
                key=key,
                classification=classification,
                visual_classification=visual_classification,
                summary=summary,
                visual_summary=visual_summary,
                escalation_path="data_prep_or_ci_team",
                baseline_path=str(baseline_path),
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
                anomaly_hints=anomaly_hints,
                diff_image_path=diff_path,
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
    notes.append("Classifications are conservative. `needs_review` is not a regression verdict.")
    notes.append(
        "Visual diff labels are conservative evidence buckets. Manual review remains required."
    )
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
