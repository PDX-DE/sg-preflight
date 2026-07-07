from __future__ import annotations

import argparse
from importlib import import_module
import json
import sys
from pathlib import Path

from sg_preflight.screenshot_triage import (
    BMW_COMPARATOR_ENVELOPE_WARNING,
    VisualDiffThresholds,
    visual_thresholds_exceed_bmw_envelope,
)

common = import_module("sg_preflight.cli")


def _console_screenshot_triage(bundle: object, *, as_json: bool = False) -> None:
    report = bundle.report
    if as_json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        return

    print(f"Screenshot triage: {report.profile_id}")
    print(f"Project root: {report.project_root}")
    print(f"Expected root: {report.expected_root or 'not found'}")
    print(
        "Summary -> "
        f"pairs: {report.pair_count} | "
        f"unchanged: {report.unchanged_count} | "
        f"near-identical: {report.near_identical_count} | "
        f"needs review: {report.needs_review_count} | "
        f"missing candidate: {report.missing_candidate_count} | "
        f"missing baseline: {report.missing_baseline_count} | "
        f"dimension mismatch: {report.dimension_mismatch_count}"
    )
    print(
        "Visual labels -> "
        f"cosmetic_likely_pass: {report.cosmetic_likely_pass_count} | "
        f"structural_likely_review: {report.structural_likely_review_count} | "
        f"unclear_manual_review: {report.unclear_manual_review_count} | "
        f"external classifier: {report.external_classifier_status}"
    )
    print(f"Markdown: {bundle.markdown_path}")
    print(f"HTML: {bundle.html_path}")
    print(f"JSON: {bundle.json_path}")


def _console_screenshot_review_viewer(bundle: object, *, as_json: bool = False) -> None:
    viewer = bundle.viewer
    if as_json:
        print(json.dumps(viewer.to_dict(), indent=2, ensure_ascii=True))
        return

    print(f"Screenshot review viewer: {viewer.profile_id}")
    print(f"Project root: {viewer.project_root}")
    print(f"Expected root: {viewer.expected_root or 'not found'}")
    print(f"Items: {viewer.item_count}")
    print(f"HTML: {bundle.html_path}")
    print(f"JSON: {bundle.json_path}")
    print(f"Triage JSON: {bundle.triage_json_path}")


def _screenshot_triage_thresholds(args: argparse.Namespace) -> VisualDiffThresholds:
    return VisualDiffThresholds(
        cosmetic_max_changed_ratio=args.cosmetic_max_changed_ratio,
        cosmetic_max_mean_abs_diff=args.cosmetic_max_mean_diff,
        structural_min_changed_ratio=args.structural_min_changed_ratio,
        structural_min_mean_abs_diff=args.structural_min_mean_diff,
        structural_min_review_score=args.structural_min_review_score,
    )


def handle_screenshot_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.command == "screenshot-test-state":
        screenshot_state_root = common._resolve_workspace(args)
        try:
            if args.screenshot_test_state_command == "read":
                payload = common.read_bmw_screenshot_state(
                    args.profile,
                    workspace=screenshot_state_root,
                )
            else:
                parser.error(f"Unhandled screenshot-test-state command: {args.screenshot_test_state_command}")
                return 1
        except Exception as exc:
            print(common._console_safe(f"screenshot-test-state failed: {exc}"), file=sys.stderr)
            return 1
        output_format = common._resolve_render_format(args, parser)
        if output_format == "json":
            common._emit_json(payload, args)
        elif output_format == "markdown":
            common._emit_text(common.render_bmw_screenshot_state_markdown(payload), args)
        else:
            common._emit_text(common.render_bmw_screenshot_state_text(payload), args)
        return 0

    if args.command == "screenshot-triage":
        triage_root = common._resolve_workspace(args)
        if not args.profile and not args.project_root:
            parser.error("screenshot-triage needs either --profile or --project-root")
            return 1
        try:
            if args.profile:
                profile = common.get_run_profile(args.profile, triage_root)
                profile_id = profile.profile_id
                project_root = profile.source_project_root()
            else:
                project_root = Path(args.project_root).resolve()
                profile_id = project_root.name
            prep = common.build_visual_review_prep(profile_id, project_root)
            output_root = (
                Path(args.output_root).resolve()
                if args.output_root
                else triage_root / "out" / f"{profile_id.lower()}-screenshot-triage"
            )
            visual_thresholds = _screenshot_triage_thresholds(args)
            if visual_thresholds_exceed_bmw_envelope(visual_thresholds):
                print(common._console_safe(BMW_COMPARATOR_ENVELOPE_WARNING), file=sys.stderr)
            bundle = common.materialize_screenshot_triage(
                profile_id,
                project_root,
                output_root,
                candidate_roots=tuple(Path(item).resolve() for item in args.candidate_root if str(item).strip()),
                priority_names=tuple(str(item) for item in prep.priority_screenshots),
                visual_thresholds=visual_thresholds,
                external_classifier_requested=args.external_vision,
            )
        except Exception as exc:
            print(common._console_safe(f"screenshot-triage failed: {exc}"), file=sys.stderr)
            return 1
        common._console_screenshot_triage(bundle, as_json=args.json)
        return 0

    if args.command == "screenshot-review-viewer":
        viewer_root = common._resolve_workspace(args)
        if args.screenshot_review_viewer_command != "build":
            parser.error(f"Unhandled screenshot-review-viewer command: {args.screenshot_review_viewer_command}")
            return 1
        if not args.profile and not args.project_root:
            parser.error("screenshot-review-viewer build needs either --profile or --project-root")
            return 1
        try:
            if args.profile:
                profile = common.get_run_profile(args.profile, viewer_root, bmw_root=args.bmw_root)
                profile_id = profile.profile_id
                project_root = profile.source_project_root()
            else:
                project_root = Path(args.project_root).resolve()
                profile_id = project_root.name
            prep = common.build_visual_review_prep(profile_id, project_root)
            output_root = (
                Path(args.output_root).resolve()
                if args.output_root
                else viewer_root / "out" / f"{profile_id.lower()}-screenshot-review-viewer"
            )
            bundle = common.build_screenshot_review_viewer(
                profile_id,
                project_root,
                output_root,
                expected_root=Path(args.expected_root).resolve() if args.expected_root else None,
                candidate_roots=tuple(Path(item).resolve() for item in args.candidate_root if str(item).strip()),
                diff_reference_roots=tuple(Path(item).resolve() for item in args.diff_root if str(item).strip()),
                priority_names=tuple(str(item) for item in prep.priority_screenshots),
                max_items=max(1, int(args.max_items or 80)),
            )
        except Exception as exc:
            print(common._console_safe(f"screenshot-review-viewer failed: {exc}"), file=sys.stderr)
            return 1
        common._console_screenshot_review_viewer(bundle, as_json=args.json)
        return 0

    parser.error(f"Unhandled screenshot command: {args.command}")
    return 1
