from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import zipfile

from sg_preflight.ticket_review import TicketReviewBundleResult, materialize_ticket_review_bundle


_DEFAULT_GROUNDED_TICKET = "IDCEVODEV-960073"
_DEFAULT_SCOPE_TICKET = "IDCEVODEV-977874"
_DEFAULT_GROUNDED_TITLE = "Quality-Hero: How to review the 3D car"
_DEFAULT_GROUNDED_PROFILE = "G70"
_DEFAULT_GROUNDED_SCOPE_NOTE = "G70 is only the first concrete live-SVN slice, not confirmed final scope."
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


def _done_items(result: TicketReviewBundleResult) -> tuple[str, ...]:
    return tuple(
        item.label
        for item in result.bundle.dod_items
        if item.status in {"prepared", "covered", "covered_with_findings", "partial", "manual_ready"}
    )


def _blocked_items(result: TicketReviewBundleResult) -> tuple[str, ...]:
    return tuple(item for item in result.bundle.blockers)


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
            "- new-chat continuation brief: `05_codex_continuation_brief.md`",
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
            f"- grounded local slice: `{', '.join(grounded.bundle.profile_ids) if grounded.bundle.profile_ids else 'none confirmed'}`",
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
        "| SG-local delivery-week QA support | strong and grounded | 92% |",
        f"| `{grounded.bundle.ticket_id}` visible DoD progress | grounded on local SVN evidence | {grounded_percent}% |",
        f"| `{scope_first.bundle.ticket_id}` concrete execution | scope-first only, needs real ticket detail | {scope_percent}% |",
        "| BMW-side end-to-end execution | still blocked by access/runtime gaps | 15% |",
        "",
        "## What is already done",
        "",
    ]
    lines.extend(f"- `{item}`" for item in _done_items(grounded))
    lines.extend(
        [
            f"- concrete SG-side finding already surfaced: {_first_finding_line(grounded)}",
            f"- full grounded evidence bundle is packaged under `{_relative(grounded.package_root, package_root)}`",
            f"- full scope-first bundle is packaged under `{_relative(scope_first.package_root, package_root)}`",
            "",
            "## What is still blocked",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in _blocked_items(grounded))
    lines.extend(
        [
            "- BMW Git / `digital-3d-car-models` is still not locally executable from this machine.",
            "- BMW screenshot smoke execution is still blocked.",
            "- BMW headless export proof flow is still blocked.",
            "- Jira writeback is still blocked.",
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
            "The framework already did most of the SG-local preparation work. The biggest remaining gaps are BMW-blocked execution and still-manual visual judgment, not missing local groundwork.",
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
    return (
        "# Message To Coordinator\n\n"
        "Suggested Teams update:\n\n"
        f"> I prepared the current delivery-week QA support package for {coordinator_name}, grounded on the live "
        f"`{', '.join(grounded.bundle.profile_ids) if grounded.bundle.profile_ids else 'local slice'}` slice for "
        f"`{grounded.bundle.ticket_id}` and a scope-first package for `{scope_first.bundle.ticket_id}`.  \n"
        "> On the SG-local side, the tool/framework already covers changelog and README review prep, shared BMW doc prioritization, "
        "screenshot baseline packaging/triage entrypoints, manual-review templates, and the SG-side repo/style checker flow.  \n"
        f"> I already have one concrete SG-side finding: {_first_finding_line(grounded)}.  \n"
        "> What is still blocked is the BMW-owned side: BMW Git/scripts, headless export execution, screenshot smoke execution, and Jira write access.  \n"
        f"> What I still need from {review_owner_group} is the exact screenshot-test reading flow, what counts as `asset review in raco (bmws)` done, and the real proof command/output for the BMW headless-export step.  \n"
        f"> The package is here: `{package_root}` and the grounded ticket bundle is here: `{_relative(grounded.package_root, package_root)}`.\n"
    )


def _review_owners_update_markdown(
    *,
    package_root: Path,
    grounded: TicketReviewBundleResult,
    coordinator_name: str,
    review_owner_group: str,
) -> str:
    return (
        "# Message To Review Owners\n\n"
        "Suggested Teams update:\n\n"
        f"> I already packaged the SG-local side of the delivery-week review for `{grounded.bundle.ticket_id}` from the real SVN slice "
        f"`{', '.join(grounded.bundle.profile_ids) if grounded.bundle.profile_ids else 'none confirmed'}` for {coordinator_name}.  \n"
        "> I have changelog/readme/shared-doc coverage, screenshot baselines and triage output, manual-review templates, and the SG-side repo checker result.  \n"
        f"> Current concrete SG-side finding: {_first_finding_line(grounded)}.  \n"
        f"> I still need your help on the parts {coordinator_name} pointed me to:  \n"
        "> 1. What is the exact screenshot-test reading flow and source-of-truth folder for candidate results?  \n"
        "> 2. What exactly counts as `asset review in raco (bmws)` done?  \n"
        "> 3. What is the exact proving command/output for `headless export check bmw` once BMW-side access exists?  \n"
        "> 4. Should the SG-side checker finding be fixed now or only reported for delivery-week tracking?  \n"
        f"> Package root: `{package_root}`.  \n"
        f"> Review-owner group captured for this package: `{review_owner_group}`.\n"
    )


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
        f"2. Ask {review_owner_group} for the exact screenshot-reading flow and headless-export proof flow.",
        "3. Use the grounded ticket bundle for manual screenshot and RaCo review, not for fake BMW-side signoff.",
        f"4. Keep `{scope_first.bundle.ticket_id}` in scope-first mode until a concrete local slice or real ticket detail is confirmed.",
        "",
        "## If more automation is possible after clarification",
        "",
        "- automate better changelog-to-screenshot priority mapping",
        "- improve packaging of screenshot candidate/result roots once the real BMW-side folder is known",
        "- automate more of the SG-side manual-review evidence capture",
        "- encode a stronger decision framework for when a DoD item is `prepared`, `partial`, or `done`",
        "",
        "## Things not to fake",
        "",
        "- BMW screenshot smoke execution",
        "- BMW headless export execution",
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
        "# Codex Continuation Brief",
        "",
        "Use this package as the starting point in a new chat.",
        "",
        "## Mission",
        "- continue automating what is still possible locally for delivery-week QA workflow support",
        "- keep improving `sg-preflight` as a grounded SG/Seriengrafik QA framework, not just a UI experiment",
        "",
        "## Ground truth",
        f"- grounded ticket: `{grounded.bundle.ticket_id}`",
        f"- grounded slice: `{', '.join(grounded.bundle.profile_ids) if grounded.bundle.profile_ids else 'none confirmed'}`",
        f"- secondary ticket: `{scope_first.bundle.ticket_id}`",
        f"- source root: `{grounded.bundle.source_root}`",
        f"- first concrete finding: {_first_finding_line(grounded)}",
        "",
        "## Already done",
        "- SG-local review packaging",
        "- screenshot baseline triage support",
        "- QA capability matrix and 3D QA playbook",
        "- repo topology and delivery surface references",
        "- RaCo script catalog and delivery target catalog",
        "",
        "## Still left",
        "- BMW-blocked execution",
        "- rack-only validation",
        "- manual visual verdicts",
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
    grounded_profile_id: str = _DEFAULT_GROUNDED_PROFILE,
    grounded_scope_note: str = _DEFAULT_GROUNDED_SCOPE_NOTE,
    scope_ticket_id: str = _DEFAULT_SCOPE_TICKET,
    coordinator_name: str = _DEFAULT_COORDINATOR_NAME,
    review_owner_group: str = _DEFAULT_REVIEW_OWNER_GROUP,
) -> DeliverySupportPackageResult:
    workspace_root = (workspace or Path(__file__).resolve().parents[1]).resolve()
    package_root = _fresh_output_root((output_root or default_delivery_support_package_output_root(workspace_root)).resolve())
    package_root.mkdir(parents=True, exist_ok=True)

    references_root = package_root / "references"
    grounded = materialize_ticket_review_bundle(
        grounded_ticket_id,
        title=grounded_title,
        profile_ids=(grounded_profile_id,),
        workspace=workspace_root,
        output_root=references_root / grounded_ticket_id / grounded_ticket_id,
        scope_note=grounded_scope_note,
    )
    scope_first = materialize_ticket_review_bundle(
        scope_ticket_id,
        workspace=workspace_root,
        output_root=references_root / scope_ticket_id / scope_ticket_id,
    )

    brief_path = package_root / "00_delivery_support_brief.md"
    progress_path = package_root / "01_current_progress.md"
    coordinator_update_path = package_root / "02_message_to_coordinator.md"
    review_owners_update_path = package_root / "03_message_to_review_owners.md"
    next_steps_path = package_root / "04_next_steps.md"
    continuation_path = package_root / "05_codex_continuation_brief.md"

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
