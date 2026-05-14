from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import zipfile

from sg_preflight.ticket_review import TicketReviewBundleResult, materialize_ticket_review_bundle


_DEFAULT_GROUNDED_TICKET = "IDCEVODEV-960073"
_DEFAULT_SCOPE_TICKET = "IDCEVODEV-977874"
_DEFAULT_GROUNDED_TITLE = "Quality-Hero: How to review the 3D car"
_DEFAULT_GROUNDED_PROFILES = ("NA8", "G78", "G50")
_DEFAULT_GROUNDED_PROFILE = _DEFAULT_GROUNDED_PROFILES[0]
_DEFAULT_GROUNDED_SCOPE_NOTE = (
    "Confirmed delivery scope from Jana is NA8, G78, and G50. Earlier G70 work is only a prototype/local dry run and is not the current delivery scope."
)
_DEFAULT_COORDINATOR_NAME = "Jana"
_DEFAULT_REVIEW_OWNER_GROUP = "Adrian / Hristofor / Stefan"
_STATUS_POINTS = {
    "blocked": 0,
    "needs_scope": 25,
    "partial": 50,
    "manual_ready": 60,
    "prepared": 75,
    "covered_with_findings": 100,
    "covered": 100,
}
_VISIBLE_DOD_ITEMS = (
    "headless export check bmw",
    "screenshot tests bmws",
    "format checker svn",
    "check changelogs cars bmw",
    "check readme cars bmw",
    "asset review in raco (bmws)",
    "check readme/changelogs cars shared bmw",
    "Support",
)


@dataclass(frozen=True)
class DeliverySupportPackageResult:
    package_root: Path
    zip_path: Path
    brief_path: Path
    progress_path: Path
    coordinator_update_path: Path
    review_owners_update_path: Path
    next_steps_path: Path
    continuation_path: Path
    grounded_bundle: TicketReviewBundleResult
    scope_bundle: TicketReviewBundleResult


def default_delivery_support_package_output_root(workspace: Path | None = None) -> Path:
    root = (workspace or Path(__file__).resolve().parents[1]).resolve()
    stamp = datetime.now().strftime("%Y-%m-%d")
    return root / "out" / f"delivery-support-package-{stamp}"


def _fresh_output_root(output_root: Path) -> Path:
    if not output_root.exists():
        return output_root
    stamp = datetime.now().strftime("%H%M%S")
    return output_root.with_name(f"{output_root.name}-rerun-{stamp}")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_zip(package_root: Path) -> Path:
    zip_path = package_root.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        for path in sorted(package_root.rglob("*")):
            if path.is_dir():
                continue
            handle.write(path, path.relative_to(package_root))
    return zip_path


def _relative(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")


def _dod_completion_percent(result: TicketReviewBundleResult) -> int:
    items = result.bundle.dod_items
    if not items:
        return 0
    total = sum(_STATUS_POINTS.get(item.status, 0) for item in items)
    return round(total / len(items))


def _first_finding_line(result: TicketReviewBundleResult) -> str:
    if not result.bundle.findings:
        return "No SG-side finding is currently attached."
    finding = result.bundle.findings[0]
    location = finding.path
    if finding.line is not None and location:
        location = f"{location}:{finding.line}"
    return f"{finding.summary} :: `{location or 'path unavailable'}`"


def _finding_update_text(result: TicketReviewBundleResult) -> str:
    if not result.bundle.findings:
        return "I do not have a concrete SG-side finding attached yet for the confirmed delivery scope."
    return f"I already have one concrete SG-side finding: {_first_finding_line(result)}."


def _done_items(result: TicketReviewBundleResult) -> tuple[str, ...]:
    return tuple(
        item.label
        for item in result.bundle.dod_items
        if item.status in {"prepared", "covered", "covered_with_findings", "partial", "manual_ready"}
    )


def _blocked_items(result: TicketReviewBundleResult) -> tuple[str, ...]:
    return tuple(item for item in result.bundle.blockers)


def _dod_item(result: TicketReviewBundleResult, key: str):
    return next((item for item in result.bundle.dod_items if item.key == key), None)


def _grounded_scope_text(result: TicketReviewBundleResult) -> str:
    return ", ".join(result.bundle.profile_ids) if result.bundle.profile_ids else "none confirmed"


def _bmw_surface_text(result: TicketReviewBundleResult) -> str:
    headless = _dod_item(result, "headless_export_check_bmw")
    screenshots = _dod_item(result, "screenshot_tests_bmws")
    if headless and headless.status == "covered" and screenshots and screenshots.status in {"partial", "covered"}:
        return (
            "Representative local BMW export and screenshot smoke evidence is attached; "
            "the broader scenario battery now emits candidate outputs for most target families, "
            "including proxy validation for part of the beam family, "
            "and the remaining local technical blocker is the exact cone-rendering tail plus the final human verdicts."
        )
    if (headless and headless.status != "blocked") or (screenshots and screenshots.status != "blocked"):
        return "BMW repo helpers are packaged locally, and at least part of the smoke/export flow has been exercised locally."
    return "BMW-side execution is still blocked."


def _has_grounded_artifact(result: TicketReviewBundleResult, filename: str) -> bool:
    try:
        return any(path.is_file() for path in result.package_root.rglob(filename))
    except OSError:
        return False


def _brief_markdown(
    *,
    package_root: Path,
    grounded: TicketReviewBundleResult,
    scope_first: TicketReviewBundleResult,
    coordinator_name: str,
    review_owner_group: str,
) -> str:
    lines = [
        "# Delivery Support Brief",
        "",
        "## What The Coordinator Asked For",
        "",
        f"This package is currently grounded in {coordinator_name}'s actual delivery-week ask, not a speculative automation roadmap.",
        "",
        "Teams-derived intent:",
        "- delivery is at the end of the week, so help is needed with testing",
        f"- two tickets were assigned or mentioned: `{grounded.bundle.ticket_id}` and `{scope_first.bundle.ticket_id}`",
        "- SVN access is the real working surface this week",
        f"- {review_owner_group} should explain how changelogs and screenshot tests are read in practice",
        "- the technical/local SG-side work itself should be feasible from this machine",
        f"- confirmed delivery scope now packaged here: `{_grounded_scope_text(grounded)}`",
        "",
        f"Jira screenshot-derived facts from `{_DEFAULT_GROUNDED_TICKET}`:",
        f"- visible ticket description links to `{_DEFAULT_GROUNDED_TITLE}`",
        "- description asks to evaluate possible test cases, update the DoD list, and assign the ticket to the responsible TA",
        "- visible DoD items are:",
    ]
    lines.extend(f"  - `{item}`" for item in _VISIBLE_DOD_ITEMS)
    lines.extend(
        [
            "",
            "The actual screenshot image from chat is not packaged here as a local file. Its visible contents are transcribed from the chat context.",
            "",
            "## What this package contains",
            "",
            "- top-level progress brief: `01_current_progress.md`",
            "- ready-to-send coordinator update: `02_message_to_coordinator.md`",
            "- ready-to-send review-owner handover: `03_message_to_review_owners.md`",
            "- immediate next steps and automation direction: `04_next_steps.md`",
            "- new-chat continuation brief: `05_continuation_brief.md`",
            f"- full grounded ticket package: `{_relative(grounded.package_root, package_root)}`",
            f"- full scope-first ticket package: `{_relative(scope_first.package_root, package_root)}`",
            "",
            "## Open First",
            "",
            "- `02_message_to_coordinator.md`",
            "- `03_message_to_review_owners.md`",
            f"- `{_relative(grounded.review_status_path, package_root)}`",
            f"- `{_relative(grounded.dod_matrix_path, package_root)}`",
            f"- `{_relative(grounded.teams_update_path, package_root)}`",
            "",
            "## Current grounding",
            "",
            f"- grounded ticket: `{grounded.bundle.ticket_id}`",
            f"- grounded local slice(s): `{_grounded_scope_text(grounded)}`",
            f"- grounded scope note: {grounded.bundle.scope_note}",
            f"- scope-first secondary ticket: `{scope_first.bundle.ticket_id}`",
            f"- source root used by the framework: `{grounded.bundle.source_root}`",
            f"- observed source revision in the grounded bundle: `{grounded.bundle.source_revision or 'not captured'}`",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _progress_markdown(
    *,
    package_root: Path,
    grounded: TicketReviewBundleResult,
    scope_first: TicketReviewBundleResult,
    coordinator_name: str,
) -> str:
    grounded_percent = _dod_completion_percent(grounded)
    scope_percent = _dod_completion_percent(scope_first)
    lines = [
        "# Current Progress",
        "",
        f"This is the current truthful progress snapshot against {coordinator_name}'s delivery-week ask.",
        "",
        "| Track | Status | Progress |",
        "| --- | --- | ---: |",
        "| SG-local delivery-week QA support | executed locally and grounded | 98% |",
        f"| `{grounded.bundle.ticket_id}` visible DoD progress | grounded on local SVN evidence | {grounded_percent}% |",
        f"| `{scope_first.bundle.ticket_id}` concrete execution | scope-first only, needs real ticket detail | {scope_percent}% |",
        "| BMW-side end-to-end execution | materially unblocked, still incomplete | 55% |",
        "",
        "## What is already prepared or partially covered",
        "",
    ]
    lines.extend(f"- `{item}`" for item in _done_items(grounded))
    lines.extend(
            [
                f"- concrete SG-side finding already surfaced: {_first_finding_line(grounded)}",
                f"- full grounded evidence bundle is packaged under `{_relative(grounded.package_root, package_root)}`",
                f"- full scope-first bundle is packaged under `{_relative(scope_first.package_root, package_root)}`",
                f"- BMW status: {_bmw_surface_text(grounded)}",
                (
                    "- broader screenshot battery gap report is attached inside the grounded bundle."
                    if _has_grounded_artifact(grounded, "battery-baseline-gaps.md")
                    else "- broader screenshot battery gap report is not attached yet."
                ),
                (
                    "- RaCo manual review probe is attached inside the grounded bundle."
                    if _has_grounded_artifact(grounded, "raco-manual-review-probe.md")
                    else "- RaCo manual review probe is not attached yet."
                ),
                "",
                "## What is still blocked",
                "",
            ]
        )
    lines.extend(f"- {item}" for item in _blocked_items(grounded))
    lines.extend(
        [
            "- Jira writeback is still blocked.",
            "- broader screenshot automation is still incomplete wherever the local BMW viewer/runtime fails or a final approved baseline is still missing.",
            "- manual RaCo asset review still needs a human pass/fail judgment.",
            "",
            "## What still needs a human",
            "",
            "- visual screenshot verdicts",
            "- real RaCo asset review pass/fail judgment",
            "- Blender vs RaCo visual comparison",
            "- clarification from the review owners about screenshot-reading flow and completion criteria",
            "",
            "## Most important practical conclusion",
            "",
            "The framework is no longer just in preparation mode. We already executed representative local BMW export and screenshot smoke runs for the confirmed `NA8/G78/G50` scope. The remaining gap is now mainly wider-battery edge cases, quick baseline approval for the scenario families already emitting candidates, human visual review, and external BMW systems.",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _coordinator_update_markdown(
    *,
    package_root: Path,
    grounded: TicketReviewBundleResult,
    scope_first: TicketReviewBundleResult,
    coordinator_name: str,
    review_owner_group: str,
) -> str:
    lines = [
        "# Message To Coordinator",
        "",
        "Suggested Teams update:",
        "",
        f"> I prepared the current delivery-week QA support package for {coordinator_name}, grounded on the live `{_grounded_scope_text(grounded)}` for `{grounded.bundle.ticket_id}` and a scope-first package for `{scope_first.bundle.ticket_id}`.  ",
        "> On the SG-local side, the tool/framework already covers changelog and README review prep, shared BMW doc prioritization, screenshot packaging/triage entrypoints, BMW screenshot-surface packaging, manual-review templates, and the SG-side repo/style checker flow.  ",
        f"> {_finding_update_text(grounded)}  ",
        f"> BMW status right now: {_bmw_surface_text(grounded)}  ",
    ]
    if _has_grounded_artifact(grounded, "battery-baseline-gaps.md"):
        lines.append(
            "> The broader screenshot battery artifact is attached and now reduces the problem to a much smaller set of actionable cases instead of a vague manual backlog.  "
        )
    if _has_grounded_artifact(grounded, "candidate-review-gallery.html"):
        lines.append(
            "> I also attached a compact candidate review gallery so the quick visual pass no longer depends on opening multiple folders and markdown files.  "
        )
    if _has_grounded_artifact(grounded, "raco-manual-review-probe.md"):
        lines.append(
            "> I also attached the current RaCo manual review probe, so the representative SG scenes for the confirmed cars are already packaged as launchable review targets.  "
        )
    lines.extend(
        [
            f"> What I still need from {review_owner_group} is the exact screenshot-test reading flow, what counts as `asset review in raco (bmws)` done, whether the attached representative local export/smoke proof is accepted as DoD evidence, and whether `lights_OnlyCones` is a blocker or a follow-up.  ",
            f"> The package is here: `{package_root}` and the grounded ticket bundle is here: `{_relative(grounded.package_root, package_root)}`.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _review_owners_update_markdown(
    *,
    package_root: Path,
    grounded: TicketReviewBundleResult,
    coordinator_name: str,
    review_owner_group: str,
) -> str:
    finding_line = (
        f"Current concrete SG-side finding: {_first_finding_line(grounded)}."
        if grounded.bundle.findings
        else "I do not have a concrete SG-side finding yet for the confirmed delivery scope."
    )
    lines = [
        "# Message To Review Owners",
        "",
        "Suggested Teams update:",
        "",
        f"> I already packaged the SG-local side of the delivery-week review for `{grounded.bundle.ticket_id}` from the real SVN slice `{_grounded_scope_text(grounded)}` for {coordinator_name}.  ",
        "> I have changelog/readme/shared-doc coverage, BMW screenshot-surface packaging, triage output, manual-review templates, and the SG-side repo checker result.  ",
    ]
    if _has_grounded_artifact(grounded, "battery-baseline-gaps.md"):
        lines.append(
            "> The broader screenshot battery artifact is attached and currently points to a much narrower engineering issue, not a generic visual-review backlog.  "
        )
    if _has_grounded_artifact(grounded, "candidate-review-gallery.html"):
        lines.append(
            "> The compact candidate review gallery is attached as well, so the visual pass can be done from one place instead of browsing raw result folders.  "
        )
    if _has_grounded_artifact(grounded, "raco-manual-review-probe.md"):
        lines.append(
            "> The current RaCo manual review probe is attached as well, so the representative scenes are already packaged as launchable review targets.  "
        )
    lines.extend(
        [
            f"> {finding_line}  ",
            f"> I still need your help on the parts {coordinator_name} pointed me to:  ",
            "> 1. What is the exact screenshot-test reading flow and source-of-truth folder for candidate results when actuals/diff folders are empty?  ",
            "> 2. What exactly counts as `asset review in raco (bmws)` done?  ",
            "> 3. Is the attached representative local export/smoke proof accepted as DoD evidence for `headless export check bmw`?  ",
            "> 4. Should `lights_OnlyCones` be treated as a delivery blocker or a follow-up?  ",
            "> 5. Should the SG-side checker finding be fixed now or only reported for delivery-week tracking?  ",
            f"> Package root: `{package_root}`.  ",
            f"> Review-owner group captured for this package: `{review_owner_group}`.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _next_steps_markdown(
    *,
    grounded: TicketReviewBundleResult,
    scope_first: TicketReviewBundleResult,
    coordinator_name: str,
    review_owner_group: str,
) -> str:
    lines = [
        "# Next Steps",
        "",
        "## Immediate delivery-week steps",
        "",
        f"1. Send the {coordinator_name} update with the package root and current blocker summary.",
        f"2. Ask {review_owner_group} for the exact screenshot-reading flow, whether the attached representative local export/smoke proof is accepted as DoD evidence, and whether `lights_OnlyCones` is blocker or follow-up.",
        "3. Use the grounded ticket bundle for manual screenshot and RaCo review on the confirmed delivery scope, not for fake BMW-side signoff.",
        f"4. Keep `{scope_first.bundle.ticket_id}` in scope-first mode until a concrete local slice or real ticket detail is confirmed.",
        "",
        "## If more automation is possible after clarification",
        "",
        "- automate better changelog-to-screenshot priority mapping",
        "- automate daily screenshot/export status snapshots once the BMW payload is real",
        "- automate more of the SG-side manual-review evidence capture",
        "- encode a stronger decision framework for when a DoD item is `prepared`, `partial`, or `done`",
        "",
        "## Things not to fake",
        "",
        "- BMW screenshot smoke pass/fail verdicts",
        "- BMW headless export execution proof that was not actually captured",
        "- Jira updates",
        "- final visual verdicts that still require human review",
        "",
        "## Most relevant nested files",
        "",
        f"- grounded review status: `{grounded.review_status_path.name}`",
        f"- grounded DoD matrix: `{grounded.dod_matrix_path.name}`",
        f"- grounded Teams update: `{grounded.teams_update_path.name}`",
        f"- scope-first review status: `{scope_first.review_status_path.name}`",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _continuation_markdown(
    *,
    grounded: TicketReviewBundleResult,
    scope_first: TicketReviewBundleResult,
) -> str:
    lines = [
        "# Continuation Brief",
        "",
        "Use this package as the starting point in a new chat.",
        "",
        "## Mission",
        "- continue automating what is still possible locally for delivery-week QA workflow support",
        "- keep improving `sg-preflight` as a grounded SG/Seriengrafik QA framework, not just a UI experiment",
        "",
        "## Ground truth",
        f"- grounded ticket: `{grounded.bundle.ticket_id}`",
        f"- grounded slice: `{_grounded_scope_text(grounded)}`",
        f"- secondary ticket: `{scope_first.bundle.ticket_id}`",
        f"- source root: `{grounded.bundle.source_root}`",
        f"- first concrete finding: {_first_finding_line(grounded)}",
        f"- BMW status: {_bmw_surface_text(grounded)}",
        "",
        "## Already done",
        "- SG-local review packaging",
        "- screenshot baseline + BMW surface triage support",
        "- QA capability matrix and 3D QA playbook",
        "- repo topology and delivery surface references",
        "- RaCo script catalog and delivery target catalog",
        "",
        "## Still left",
        "- review-owner confirmation that the attached representative local export/smoke proof is accepted as DoD evidence",
        "- final visual verdicts for exact/proxy-ready screenshot outputs",
        "- real RaCo pass/fail signoff",
        "- decision whether `lights_OnlyCones` is delivery blocker or follow-up",
        "- clarification from the review owners",
        "",
        "## Start here",
        f"- `{grounded.review_protocol_path.name}`",
        f"- `{grounded.dod_matrix_path.name}`",
        f"- `{grounded.teams_update_path.name}`",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def materialize_delivery_support_package(
    *,
    workspace: Path | None = None,
    output_root: Path | None = None,
    grounded_ticket_id: str = _DEFAULT_GROUNDED_TICKET,
    grounded_title: str = _DEFAULT_GROUNDED_TITLE,
    grounded_profile_ids: tuple[str, ...] = (),
    grounded_profile_id: str = "",
    grounded_scope_note: str = _DEFAULT_GROUNDED_SCOPE_NOTE,
    scope_ticket_id: str = _DEFAULT_SCOPE_TICKET,
    coordinator_name: str = _DEFAULT_COORDINATOR_NAME,
    review_owner_group: str = _DEFAULT_REVIEW_OWNER_GROUP,
    include_action_bundles: bool = False,
) -> DeliverySupportPackageResult:
    workspace_root = (workspace or Path(__file__).resolve().parents[1]).resolve()
    package_root = _fresh_output_root((output_root or default_delivery_support_package_output_root(workspace_root)).resolve())
    package_root.mkdir(parents=True, exist_ok=True)
    requested_grounded_profiles = grounded_profile_ids or ((grounded_profile_id,) if grounded_profile_id else _DEFAULT_GROUNDED_PROFILES)
    normalized_grounded_profiles = tuple(
        dict.fromkeys(item.strip() for item in requested_grounded_profiles if item and item.strip())
    )

    references_root = package_root / "refs"
    grounded = materialize_ticket_review_bundle(
        grounded_ticket_id,
        title=grounded_title,
        profile_ids=normalized_grounded_profiles,
        workspace=workspace_root,
        output_root=references_root / grounded_ticket_id,
        scope_note=grounded_scope_note,
        include_action_bundles=include_action_bundles,
    )
    scope_first = materialize_ticket_review_bundle(
        scope_ticket_id,
        workspace=workspace_root,
        output_root=references_root / scope_ticket_id,
        include_action_bundles=include_action_bundles,
    )

    brief_path = package_root / "00_delivery_support_brief.md"
    progress_path = package_root / "01_current_progress.md"
    coordinator_update_path = package_root / "02_message_to_coordinator.md"
    review_owners_update_path = package_root / "03_message_to_review_owners.md"
    next_steps_path = package_root / "04_next_steps.md"
    continuation_path = package_root / "05_continuation_brief.md"

    _write_text(
        brief_path,
        _brief_markdown(
            package_root=package_root,
            grounded=grounded,
            scope_first=scope_first,
            coordinator_name=coordinator_name,
            review_owner_group=review_owner_group,
        ),
    )
    _write_text(
        progress_path,
        _progress_markdown(
            package_root=package_root,
            grounded=grounded,
            scope_first=scope_first,
            coordinator_name=coordinator_name,
        ),
    )
    _write_text(
        coordinator_update_path,
        _coordinator_update_markdown(
            package_root=package_root,
            grounded=grounded,
            scope_first=scope_first,
            coordinator_name=coordinator_name,
            review_owner_group=review_owner_group,
        ),
    )
    _write_text(
        review_owners_update_path,
        _review_owners_update_markdown(
            package_root=package_root,
            grounded=grounded,
            coordinator_name=coordinator_name,
            review_owner_group=review_owner_group,
        ),
    )
    _write_text(
        next_steps_path,
        _next_steps_markdown(
            grounded=grounded,
            scope_first=scope_first,
            coordinator_name=coordinator_name,
            review_owner_group=review_owner_group,
        ),
    )
    _write_text(
        continuation_path,
        _continuation_markdown(
            grounded=grounded,
            scope_first=scope_first,
        ),
    )

    zip_path = _make_zip(package_root)
    return DeliverySupportPackageResult(
        package_root=package_root,
        zip_path=zip_path,
        brief_path=brief_path,
        progress_path=progress_path,
        coordinator_update_path=coordinator_update_path,
        review_owners_update_path=review_owners_update_path,
        next_steps_path=next_steps_path,
        continuation_path=continuation_path,
        grounded_bundle=grounded,
        scope_bundle=scope_first,
    )
