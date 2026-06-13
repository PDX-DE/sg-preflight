from __future__ import annotations

from pathlib import Path

from sg_preflight.ticket_dod import TicketDoDItem, _BMW_DOC_URLS, _QUALITY_HERO_PROCESS_REFERENCE
from sg_preflight.ticket_evidence_packaging import _counts_by_kind_text, _display_path

def _bmw_surface_markdown(surface: BmwScreenshotSurface) -> str:
    lines = [
        f"# BMW screenshot surface - {surface.profile_id}",
        "",
        f"- SG profile: `{surface.profile_id}`",
        f"- BMW profile folder: `{surface.bmw_profile_id}`",
        f"- BMW repo root: `{surface.repo_root or 'not found'}`",
        f"- BMW cars root: `{surface.cars_root or 'not found'}`",
        f"- BMW car root: `{surface.car_root or 'not found'}`",
        f"- BMW CI scripts root: `{surface.ci_scripts_root or 'not found'}`",
        f"- BMW CI tools root: `{surface.ci_tools_root or 'not found'}`",
        f"- BMW CI README: `{surface.ci_readme_path or 'not found'}`",
        f"- BMW car_manager.py: `{surface.car_manager_path or 'not found'}`",
        f"- Export/tests root: `{surface.export_tests_root or 'not found'}`",
        f"- SG expected root: `{surface.sg_expected_root or 'not found'}` ({surface.sg_expected_count} image(s))",
        f"- BMW expected root: `{surface.bmw_expected_root or 'not found'}` ({surface.bmw_expected_count} image(s))",
        f"- BMW actuals root: `{surface.actuals_root or 'not found'}` ({surface.actual_count} image(s))",
        f"- BMW diff root: `{surface.diff_root or 'not found'}` ({surface.diff_count} image(s))",
        f"- BMW test config: `{surface.test_config_path or 'not found'}`",
        "",
        "## Documented BMW command surface",
        "- IDC_23 export command: `py ci/scripts/test/main.py export <CAR>` on `assets/idc23`",
        "- IDC_23 screenshot comparison command: `py ci/scripts/test/main.py screenshots --diff <CAR>` on `assets/idc23`",
        "- IDC_EVO export command: `py ci/scripts/car_manager.py export <CAR>` on `master`",
        "- IDC_EVO screenshot comparison command: `py ci/scripts/car_manager.py screenshots --diff <CAR>` on `master`",
        "- External RCA screenshot command: `py ci/scripts/car_manager.py screenshots_ext C:/PATH/TO/PROJECT.rca -b BMW`",
        "- Expected screenshot proof: the current repo writes into `export/tests/{expected,actuals,diff}`.",
        "- Expected export proof: captured export log plus the printed binary file sizes from the lane export command.",
        "",
        "## Notes",
    ]
    if surface.notes:
        lines.extend(f"- {note}" for note in surface.notes)
    else:
        lines.append("- No BMW-side notes were recorded for this profile.")
    return "\n".join(lines).rstrip() + "\n"

def _build_manual_review_index(ticket_id: str, contexts: tuple[_ProfileContext, ...]) -> str:
    lines = [
        f"# Manual Review Companion - {ticket_id}",
        "",
        "This index points to the packaged manual-review templates for each grounded slice.",
        "",
    ]
    for context in contexts:
        lines.extend(
            [
                f"## {context.profile.profile_id}",
                f"- Companion: `{context.manual_review_paths['companion']}`",
                f"- Manual review record: `{context.manual_review_paths['record']}`",
                f"- Screenshot evidence slots: `{context.manual_review_paths['slots']}`",
                f"- Blender vs RaCo checklist: `{context.manual_review_paths['blender_raco']}`",
                f"- Visual review checklist: `{context.manual_review_paths['visual_checklist']}`",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"

def _item_status_summary(
    report: ScreenshotTriageReport,
) -> str:
    return (
        f"{report.pair_count} baseline image(s) are already available locally. "
        f"Triage currently sees {report.missing_candidate_count} missing candidate pair(s), "
        f"{report.near_identical_count} near-identical pair(s), {report.needs_review_count} changed pair(s), "
        f"and {report.dimension_mismatch_count} dimension mismatch pair(s). Visual labels: "
        f"{report.cosmetic_likely_pass_count} cosmetic likely pass, "
        f"{report.structural_likely_review_count} structural likely review, "
        f"{report.unclear_manual_review_count} unclear manual review."
    )

def _select_attach_run(context: _ProfileContext) -> ActionRecord | None:
    for record in (
        *(record for record in context.manual_evidence_records if record.action_id.startswith("scene_check")),
        context.scene_record,
        *(record for record in context.manual_evidence_records if record.action_id.startswith("qa_stack")),
        context.stack_record,
    ):
        if record is not None:
            return record
    return None

def _attach_examples(contexts: tuple[_ProfileContext, ...], workspace: Path) -> tuple[str, ...]:
    blocks: list[str] = []
    for context in contexts:
        target = _select_attach_run(context)
        if target is None:
            continue
        profile_id = context.profile.profile_id
        block = "\n".join(
            [
                f"### {profile_id}",
                "```powershell",
                f'python -m sg_preflight.cli desktop-state attach-manual-evidence "{target.run_id}" --workspace "{workspace}" --kind screenshot --label "{profile_id} manual screenshot" --source "C:\\path\\to\\manual-shot.png"',
                f'python -m sg_preflight.cli desktop-state attach-manual-evidence "{target.run_id}" --workspace "{workspace}" --kind raco_note --label "{profile_id} RaCo note" --note "Scene checked: ..."',
                f'python -m sg_preflight.cli desktop-state attach-manual-evidence "{target.run_id}" --workspace "{workspace}" --kind blender_note --label "{profile_id} Blender note" --note "Workfile checked: ..."',
                f'python -m sg_preflight.cli desktop-state attach-manual-evidence "{target.run_id}" --workspace "{workspace}" --kind visual_review_checklist --label "{profile_id} visual checklist" --note "Project changelog reviewed: [x]"',
                "```",
            ]
        )
        blocks.append(block)
    return tuple(blocks)

def _test_case_area(key: str) -> str:
    name = Path(key).name.lower()
    if name.startswith("lights_"):
        return "Lighting and signal states"
    if name in {"cameraview", "default", "default_rear"}:
        return "Default and camera views"
    if name.startswith("glow_") or "godrays" in name:
        return "Glow and atmospheric effects"
    if name.startswith("groundfloor"):
        return "Ground and reflection"
    if name.startswith("highlighting_seats_"):
        return "Seat states and layouts"
    if name.startswith("highlighting_sensors_"):
        return "Sensor highlighting"
    if name.startswith("highlighting_doors") or name.startswith("highlighting_fuel") or name.startswith("highlighting_hood"):
        return "Body highlighting and access points"
    if "wheel" in name or "tire" in name or name.startswith("trimline_") or name.startswith("motion_"):
        return "Wheel and tire review"
    if name.startswith("customcolor_"):
        return "Custom colors and trimlines"
    return "Other"

def _possible_test_case_lines(context: _ProfileContext) -> list[str]:
    report = context.triage_bundle.report
    prep = context.prep
    lines = [
        f"### {context.profile.profile_id}",
        f"- Changelog heading: {prep.changelog_heading or 'not found'}",
        f"- Representative RaCo scene: `{prep.raco_scene_path or 'not found'}`",
        f"- Representative Blender workfile: `{prep.blender_workfile_path or 'not found'}`",
        f"- Screenshot baseline root: `{prep.screenshot_root or 'not found'}`",
        "- Priority screenshots: "
        + (", ".join(prep.priority_screenshots[:6]) if prep.priority_screenshots else "none detected"),
        "",
        "| Test-case area | Baselines | Current triage | Example screenshots |",
        "| --- | ---: | --- | --- |",
    ]
    groups: dict[str, list[str]] = {}
    for pair in report.pairs:
        groups.setdefault(_test_case_area(pair.key), []).append(Path(pair.key).name)

    ordered_areas = [
        "Lighting and signal states",
        "Default and camera views",
        "Glow and atmospheric effects",
        "Ground and reflection",
        "Body highlighting and access points",
        "Seat states and layouts",
        "Sensor highlighting",
        "Wheel and tire review",
        "Custom colors and trimlines",
        "Other",
    ]
    for area in ordered_areas:
        names = groups.get(area, [])
        if not names:
            continue
        missing = sum(
            1
            for pair in report.pairs
            if _test_case_area(pair.key) == area and pair.classification == "missing_candidate"
        )
        needs_review = sum(
            1
            for pair in report.pairs
            if _test_case_area(pair.key) == area and pair.classification == "needs_review"
        )
        structural = sum(
            1
            for pair in report.pairs
            if _test_case_area(pair.key) == area and pair.visual_classification == "structural_likely_review"
        )
        unclear = sum(
            1
            for pair in report.pairs
            if _test_case_area(pair.key) == area and pair.visual_classification == "unclear_manual_review"
        )
        state = (
            f"{missing} missing candidate"
            if missing
            else f"{structural} structural review signal"
            if structural
            else f"{unclear} unclear manual review"
            if unclear
            else f"{needs_review} needs review"
            if needs_review
            else "triage ready"
        )
        lines.append(f"| {area} | {len(names)} | {state} | {', '.join(names[:3])} |")
    lines.append("")
    return lines

def _review_status_markdown(bundle: TicketReviewBundle, *, package_root: Path | None = None) -> str:
    lines = [
        f"# Ticket Review Status - {bundle.ticket_id}",
        "",
        f"- Title: {bundle.title}",
        f"- Generated at: {bundle.generated_at_utc}",
        f"- Overall status: {bundle.overall_status}",
        f"- Profiles grounded locally: {', '.join(bundle.profile_ids) if bundle.profile_ids else 'none confirmed'}",
        f"- Source root: `{bundle.source_root}`",
    ]
    if bundle.source_revision:
        lines.append(f"- Source revision: `{bundle.source_revision}`")
    if bundle.source_mode:
        lines.append(f"- Source mode: `{bundle.source_mode}`")

    lines.extend(
        [
            "",
            "## Summary",
            (
                "Local SG-side evidence is grounded, but at least one concrete finding still needs owner handling and BMW-owned steps remain blocked."
                if bundle.findings
                else "Local SG-side evidence is grounded, but BMW-owned steps remain blocked or manual."
            ),
            "",
            "## Scope Note",
            bundle.scope_note or "No explicit scope note was provided.",
            "",
            "## Concrete Findings",
        ]
    )
    if bundle.findings:
        for finding in bundle.findings:
            location = finding.path or "path unavailable"
            if finding.line is not None and finding.path:
                location = f"{finding.path}:{finding.line}"
            lines.append(f"- [{finding.severity}] {finding.summary}")
            lines.append(f"  - Source: `{location}`")
            if finding.checkers:
                lines.append(f"  - Checker(s): `{','.join(finding.checkers)}`")
    else:
        lines.append("- No SG-side findings were surfaced in the current local evidence set.")

    lines.extend(
        [
            "",
            "## Manual Evidence Rollup",
            f"- Total attached evidence items: {len(bundle.manual_evidence)}",
            f"- Counts by kind: {_counts_by_kind_text(bundle.manual_evidence)}",
        ]
    )
    if bundle.manual_evidence:
        for item in bundle.manual_evidence:
            lines.append(f"- [{item.kind}] {item.label}")
            lines.append(f"  - Packaged path: `{_display_path(item.packaged_path, package_root)}`")

    lines.extend(["", "## Blockers"])
    if bundle.blockers:
        lines.extend(f"- {item}" for item in bundle.blockers)
    else:
        lines.append("- No unresolved blockers are currently listed.")

    lines.extend(["", "## Next Questions"])
    lines.extend(f"- {item}" for item in bundle.next_questions)

    lines.extend(["", "## Package Evidence"])
    if bundle.evidence_index:
        for item in bundle.evidence_index:
            lines.append(f"- {item.label}: `{_display_path(item.path, package_root)}`")
    else:
        lines.append("- No package evidence paths were recorded.")

    lines.extend(["", "## Notes"])
    lines.extend(f"- {item}" for item in bundle.notes)
    return "\n".join(lines).rstrip() + "\n"

def _dod_matrix_markdown(bundle: TicketReviewBundle, *, package_root: Path | None = None) -> str:
    lines = [
        f"# DoD Matrix - {bundle.ticket_id}",
        "",
        f"- Title: {bundle.title}",
        f"- Scope note: {bundle.scope_note or 'No explicit scope note was provided.'}",
        "",
        "| DoD item | Status | Summary | What can be done now | Blocked / next input | Owner hint |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in bundle.dod_items:
        lines.append(
            f"| {item.label} | {item.status} | {item.summary} | {item.what_can_be_done_now} | {item.blocked_next_input} | {item.owner_hint} |"
        )

    lines.extend(["", "## Evidence Paths"])
    for item in bundle.dod_items:
        lines.append(f"### {item.label}")
        if item.evidence:
            for evidence in item.evidence:
                lines.append(f"- {evidence.label}: `{_display_path(evidence.path, package_root)}`")
        else:
            lines.append("- No evidence linked yet.")

    lines.extend(
        [
            "",
            "## Manual Evidence Rollup",
            f"- Total attached evidence items: {len(bundle.manual_evidence)}",
            f"- Counts by kind: {_counts_by_kind_text(bundle.manual_evidence)}",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"

def _proposed_dod_wording(item: TicketDoDItem) -> str:
    proposed = {
        "headless_export_check_bmw": "Document exact BMW headless export command, expected success output, and latest verified execution evidence.",
        "screenshot_tests_bmws": "Review expected baselines, confirmed candidate/result root, deterministic diff triage, and human verdict for changed or missing pairs.",
        "format_checker_svn": "Run SG checker stack on the confirmed slice and record findings plus fix-vs-report decision.",
        "check_changelogs_cars_bmw": "Review latest car changelog and map intended changes to the screenshots or assets that must be checked.",
        "check_readme_cars_bmw": "Review car-local README/constants notes relevant to the confirmed slice before visual signoff.",
        "asset_review_in_raco_bmws": "Open the agreed RaCo scene, compare against Blender/workfiles, and attach manual note plus screenshot evidence.",
        "check_readme_changelogs_cars_shared_bmw": "Review the shared BMW modules actually touched by the confirmed ticket scope and attach notes.",
        "support": "Define what support means for this sprint: reporting channel, owner, cadence, and expected artifact package.",
    }
    return proposed.get(item.key, item.label)

def _required_evidence_text(item: TicketDoDItem) -> str:
    evidence_map = {
        "headless_export_check_bmw": "Command/script, execution log, success trace, and delivery-doc reference.",
        "screenshot_tests_bmws": "Baseline root, candidate/result root, triage report, diff artifacts if present, and human verdict note.",
        "format_checker_svn": "Repo-checker summary plus any concrete file/line findings.",
        "check_changelogs_cars_bmw": "Live changelog, SVN log lines, and reviewer note on intended changes.",
        "check_readme_cars_bmw": "Relevant README/constants docs plus reviewer note.",
        "asset_review_in_raco_bmws": "Representative `.rca`, Blender workfile, manual note, and screenshot where useful.",
        "check_readme_changelogs_cars_shared_bmw": "Relevant shared README/CHANGELOG docs plus reviewer note.",
        "support": "Teams/Jira-ready note, blockers, open questions, and owner clarification.",
    }
    return evidence_map.get(item.key, "Evidence still needs clarification.")

def _dod_update_draft_markdown(bundle: TicketReviewBundle) -> str:
    lines = [
        f"# DoD Update Draft - {bundle.ticket_id}",
        "",
        f"- Title: {bundle.title}",
        f"- Scope note: {bundle.scope_note or 'No explicit scope note was provided.'}",
        "- This is a refinement draft for Jira/Teams use while direct Jira writeback is still blocked.",
        "",
        "| Current Jira DoD item | Proposed clarified wording | Current state | Proposed owner | Required evidence | Why this wording is safer |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    rationale = {
        "headless_export_check_bmw": "It separates documentation/preconditions from actual BMW-side execution so the item cannot be claimed locally by accident.",
        "screenshot_tests_bmws": "It makes the missing candidate root explicit and keeps the verdict human-reviewed instead of pretending automation closed it.",
        "format_checker_svn": "It clarifies that the SG-side checker is locally executable and that ownership includes deciding whether to fix or report.",
        "check_changelogs_cars_bmw": "It links changelog review to actual review targets instead of treating the changelog as a box-tick.",
        "check_readme_cars_bmw": "It forces slice-scoped documentation review rather than assuming a generic README pass is enough.",
        "asset_review_in_raco_bmws": "It defines done-ness as scene review plus attached evidence, not only opening RaCo once.",
        "check_readme_changelogs_cars_shared_bmw": "It prevents reviewing every shared module blindly and focuses only on the ones that matter for scope.",
        "support": "It turns a vague label into a measurable reporting responsibility.",
    }
    for item in bundle.dod_items:
        lines.append(
            f"| {item.label} | {_proposed_dod_wording(item)} | {item.status} | {item.owner_hint} | {_required_evidence_text(item)} | {rationale.get(item.key, 'Clarify the item before it becomes a false green.')} |"
        )

    lines.extend(
        [
            "",
            "## Immediate recommendation",
            "- Keep G70 only as the earlier prototype/local dry run; do not present it as the current delivery scope.",
            "- Treat `NA8`, `G78`, and `G50` as the current confirmed delivery scope unless Jana adds more cars.",
            "- Ask Adrian / Hristofor / Stefan for the screenshot-result reading flow and the real candidate-output rule when the current `actuals/diff` folders are still empty.",
            "- Keep the current SG checker finding as a minor reported issue until someone decides whether it should be fixed now or only assigned.",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"

def _teams_update_markdown(bundle: TicketReviewBundle) -> str:
    finding_block = ""
    if bundle.findings:
        finding = bundle.findings[0]
        source = finding.path
        if finding.line is not None and finding.path:
            source = f"{finding.path}:{finding.line}"
        finding_block = (
            "Current concrete local SG-side finding:\n"
            f"- {source}\n"
            f"- {finding.summary}\n"
        )

    manual_block = (
        f"\nManual evidence harvested so far: {len(bundle.manual_evidence)} item(s); counts by kind: {_counts_by_kind_text(bundle.manual_evidence)}\n"
        if bundle.manual_evidence
        else ""
    )
    profile_text = ", ".join(bundle.profile_ids) if bundle.profile_ids else "no grounded slice yet"
    headless_item = next((item for item in bundle.dod_items if item.key == "headless_export_check_bmw"), None)
    screenshot_item = next((item for item in bundle.dod_items if item.key == "screenshot_tests_bmws"), None)
    bmw_block = (
        "- BMW repo snapshot and helper scripts are packaged locally, and representative local headless export proof is attached\n"
        "- representative smoke evidence is attached, broader candidate outputs exist for most wider scenarios, low/high beam have proxy coverage, and the remaining exact local technical blocker is `lights_OnlyCones`\n"
        if (headless_item and headless_item.status != "blocked") or (screenshot_item and screenshot_item.status != "blocked")
        else "- BMW Git / digital-3d-car-models\n"
    )
    return (
        f"# Teams Update - {bundle.ticket_id}\n\n"
        "Message\n\n"
        f"I prepared a grounded local SG-side review bundle for `{bundle.ticket_id}` from the real SVN context on this machine.\n"
        f"Current scope packaged here: {profile_text}.\n"
        f"Scope note: {bundle.scope_note}\n\n"
        f"{finding_block}\n"
        "What is already covered locally:\n"
        "- car changelog/readme review prep from the live SVN checkout\n"
        "- shared BMW README/CHANGELOG review prep\n"
        "- screenshot baseline/test-config discovery and BMW screenshot-surface packaging\n"
        "- representative RaCo/Blender entrypoints\n"
        "- SG-side repo checker / format flow evidence\n"
        f"{manual_block}\n"
        "What is still blocked on my side:\n"
        "- BMW Jira access\n"
        f"{bmw_block}"
        "- real pass/fail signoff for visual deltas\n\n"
        "What I still need from Adrian / Hristofor / Stefan:\n"
        "- confirmation whether the attached representative local export proof is accepted as DoD evidence\n"
        "- where screenshot result/candidate images are generated when the actuals/diff folders are empty\n"
        "- how screenshot-test pass/fail is normally read\n"
        "- what exactly counts as asset review in RaCo done\n"
        "- whether `lights_OnlyCones` should be treated as a delivery blocker or a follow-up\n"
    )

def _stakeholder_sync_markdown(bundle: TicketReviewBundle) -> str:
    profile_text = ", ".join(bundle.profile_ids) if bundle.profile_ids else "no grounded slice yet"
    lines = [
        f"# Stakeholder Sync Brief - {bundle.ticket_id}",
        "",
        "## Message For Jana",
        "I still do not have Jira access, but I can work from the screenshots and the live SVN checkout for now.",
        f"I prepared a grounded local SG-side review package from `C:\\repositories\\trunk` for {profile_text}.",
        f"Scope note: {bundle.scope_note}",
        "The package includes car changelog/readme material, shared BMW docs, screenshot baselines/test config, representative RaCo/Blender entrypoints, and SG-side checker output.",
    ]
    if bundle.findings:
        finding = bundle.findings[0]
        source = finding.path
        if finding.line is not None and finding.path:
            source = f"{finding.path}:{finding.line}"
        lines.extend(
            [
                "",
                "Current concrete local SG-side finding:",
                f"- {source}",
                f"- {finding.summary}",
            ]
        )
    lines.extend(
        [
            "",
            "What is still blocked on my side:",
            "- BMW Jira access",
            "- broader screenshot coverage still has one reproducible exact local runtime/content blocker on `lights_OnlyCones`; `lights_LowBeam` and `lights_HighBeam` are proxy-covered",
            "- real screenshot pass/fail verdicts are still manual review work for the candidate/proxy outputs",
            "",
            f"The confirmed delivery scope packaged here is `{profile_text}`. I still need a short sync with Adrian / Hristofor / Stefan on how screenshot-test results are read in practice, whether the attached local export proof is accepted as DoD evidence, and whether `lights_OnlyCones` is a delivery blocker or a follow-up.",
            "",
            "## Questions For Adrian / Hristofor / Stefan",
        ]
    )
    for question in bundle.next_questions[1:6]:
        lines.append(f"- {question}")
    lines.extend(
        [
            "",
            "## Recommended reporting path while Jira is blocked",
            "- Send the short status message to Jana.",
            "- Keep the ZIP private unless Jana explicitly asks for the full package.",
            "- Use the DoD matrix and owner matrix as the source of truth for current status and blockers.",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"

def _owner_matrix_markdown(bundle: TicketReviewBundle) -> str:
    lines = [
        f"# Owner Matrix - {bundle.ticket_id}",
        "",
        f"- Title: {bundle.title}",
        f"- Scope note: {bundle.scope_note or 'No explicit scope note was provided.'}",
        "",
        "| DoD item | Current state | Owner hint | Needs confirmation / next input |",
        "| --- | --- | --- | --- |",
    ]
    for item in bundle.dod_items:
        lines.append(f"| {item.label} | {item.status} | {item.owner_hint} | {item.blocked_next_input} |")
    return "\n".join(lines).rstrip() + "\n"

def _review_protocol_markdown(
    *,
    bundle: TicketReviewBundle,
    contexts: tuple[_ProfileContext, ...],
    workspace: Path,
    package_root: Path | None = None,
    manual_evidence_index_path: Path,
    manual_review_companion_path: Path,
    qa_capability_matrix_path: Path,
    three_d_qa_playbook_path: Path,
    repo_topology_reference_path: Path,
    delivery_surface_map_path: Path,
    raco_script_catalog_path: Path,
    delivery_target_catalog_path: Path,
) -> str:
    lines = [
        f"# Review Protocol - {bundle.ticket_id}",
        "",
        f"- Title: {bundle.title}",
        f"- Overall status: {bundle.overall_status}",
        f"- Scope note: {bundle.scope_note or 'No explicit scope note was provided.'}",
        "",
        "## Intent",
        "This ticket is treated as a delivery-week QA support and process-definition task.",
        "Use deterministic SG-side evidence first, keep manual review explicit, and keep BMW-owned steps marked as blocked until access or criteria are confirmed.",
        "",
        "## Verified reference surfaces",
    ]
    pdf_path = workspace / "GFX_Project_Overview_2026.pdf"
    if pdf_path.exists():
        lines.extend(
            [
                f"- Local project/process reference reviewed: `{pdf_path}` (reference only, not packaged).",
                "- Relevant process hints captured from that PDF: Jira documentation is mandatory, delivery documentation and performance-test results belong in Confluence, screenshot/manual review findings should be documented, and Blender-vs-RaCo comparison is expected before treating work as visually safe.",
            ]
        )
    lines.extend(
        [
            f"- {_QUALITY_HERO_PROCESS_REFERENCE}: local Confluence export/operator notes; live page access still requires login.",
        ]
    )
    for url in _BMW_DOC_URLS:
        lines.extend([f"- BMW reference page: `{url}`", "  - Reachable from this machine, but BMW Confluence login is still required."])
    lines.append(f"- Packaged manual-review index: `{_display_path(manual_review_companion_path, package_root)}`")
    lines.append(f"- Packaged QA capability matrix: `{_display_path(qa_capability_matrix_path, package_root)}`")
    lines.append(f"- Packaged 3D QA playbook: `{_display_path(three_d_qa_playbook_path, package_root)}`")
    lines.append(f"- Packaged repo topology reference: `{_display_path(repo_topology_reference_path, package_root)}`")
    lines.append(f"- Packaged delivery surface map: `{_display_path(delivery_surface_map_path, package_root)}`")
    lines.append(f"- Packaged RaCo script catalog: `{_display_path(raco_script_catalog_path, package_root)}`")
    lines.append(f"- Packaged delivery target catalog: `{_display_path(delivery_target_catalog_path, package_root)}`")

    lines.extend(
        [
            "",
            "## Workflow steps",
            "| DoD item | Current state | Owner hint | What to do now | Evidence expected |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    expected_evidence = {
        "headless_export_check_bmw": "Expected command/script, export log, success/failure trace, and delivery documentation entry once BMW access exists.",
        "screenshot_tests_bmws": "Expected baseline root, candidate/result root, deterministic triage JSON/HTML, optional diff artifacts, and a positive or negative test note.",
        "format_checker_svn": "Expected SG checker summary plus concrete path/line findings for anything surfaced on the live SVN slice.",
        "check_changelogs_cars_bmw": "Expected live car changelog, latest SVN log lines, and reviewer notes on intended changes.",
        "check_readme_cars_bmw": "Expected car README/constants docs plus reviewer notes on anything relevant to the delivery.",
        "asset_review_in_raco_bmws": "Expected representative `.rca` scene, Blender workfile, manual screenshot/note evidence, and Blender-vs-RaCo review notes.",
        "check_readme_changelogs_cars_shared_bmw": "Expected prioritized shared BMW README/CHANGELOG docs plus reviewer notes on affected modules.",
        "support": "Expected Teams/Jira-ready status note, blockers, findings, next questions, and ownership clarification.",
    }
    for item in bundle.dod_items:
        lines.append(
            f"| {item.label} | {item.status} | {item.owner_hint} | {item.what_can_be_done_now} | {expected_evidence.get(item.key, 'Expected evidence still needs clarification.')} |"
        )

    lines.extend(["", "## Possible test cases from current local slices"])
    for context in contexts:
        lines.extend(_possible_test_case_lines(context))

    lines.extend(
        [
            "## Manual Evidence Rollup",
            f"- Total attached evidence items: {len(bundle.manual_evidence)}",
            f"- Counts by kind: {_counts_by_kind_text(bundle.manual_evidence)}",
            f"- Packaged manual evidence index: `{_display_path(manual_evidence_index_path, package_root)}`",
            "",
            "## Attach Examples",
        ]
    )
    attach_blocks = _attach_examples(contexts, workspace)
    if attach_blocks:
        lines.extend(attach_blocks)
    else:
        lines.append("- No scene-check or qa-stack run is available yet for attach examples.")

    lines.extend(
        [
            "",
            "## Documentation expectations",
            "- Positive findings should still be documented, not only failures.",
            "- Manual visual review should capture Blender-vs-RaCo notes and at least one concrete evidence path or screenshot when something is questionable.",
            "- Use the packaged manual-review templates instead of starting free-form notes from scratch.",
            "- BMW-side delivery documentation and performance-test results remain external until access is granted.",
            "- The package outputs are intended to be copy-ready for Teams/Jira updates while direct Jira access is blocked.",
            "",
            "## Current blockers",
        ]
    )
    lines.extend(f"- {item}" for item in bundle.blockers)
    return "\n".join(lines).rstrip() + "\n"

def _manual_review_companion_markdown(ticket_id: str, contexts: tuple[_ProfileContext, ...]) -> str:
    return _build_manual_review_index(ticket_id, contexts)

def _review_owner_decisions_markdown(bundle: TicketReviewBundle) -> str:
    lines = [
        "# Review-owner decisions",
        "",
        f"- Ticket: `{bundle.ticket_id}`",
        f"- Scope: `{', '.join(bundle.profile_ids) if bundle.profile_ids else 'none confirmed'}`",
        "",
        "## lights_OnlyCones",
        "Decision: blocker / follow-up / accepted limitation / needs more investigation",
        "Owner:",
        "Date:",
        "Notes:",
        "",
        "## Screenshot candidate/proxy outputs",
        "Decision: accepted / needs changes / partial",
        "Owner:",
        "Date:",
        "Notes:",
        "",
        "## RaCo asset review",
        "Decision: passed / failed / not reviewed",
        "Owner:",
        "Date:",
        "Notes:",
        "",
        "## Jira writeback",
        "Status:",
        "Owner:",
        "",
        "## Additional review-owner notes",
        "",
        "- screenshot tests bmws:",
        "- check changelogs cars bmw:",
        "- check readme cars bmw:",
        "- check readme/changelogs cars shared bmw:",
        "",
    ]
    return "\n".join(lines)
