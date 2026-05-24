# Changelog - SGFX QA Preflight (local alpha)

This changelog covers the curated SVN handover bundle only. Internal
working-tree history, coordination notes, and generated evidence are kept
outside this bundle.

## [Unreleased - local alpha]

### Added
- Native operator observability: read-only overview panel sourced from the Python `desktop-state overview` endpoint.
- Screenshot review prioritization: P0-P3 suggested review order for screenshot candidates. This is guidance, not a verdict.
- Daily / morning QA digest: JSON, text, and Markdown status summaries with evidence, blockers, manual-review pending, waiting-owner, and suggested-review-order sections.
- RaCo / Blender manual-review companion: operator-recorded manual-review sessions with Quality Hero step focus and no automatic verdict recording.
- Delivery-checklist and export-size analysis readers: read-only ingestion of operator-local workbook evidence.
- BMW / MINI screenshot-test state and BMW Git readiness surfaces: read-only local dependency visibility for profile-level QA readiness.
- QA Hero readiness surface: read-only presence/count summary for documented 3D Car review subsystems.
- CLI usability updates: consistent `--format text|json|markdown` rendering and `--output-path` / `--out` file output for supported read/status commands.
- CLI and JSON workflow guides for operators adding or running checks through existing Python-owned SGFX surfaces.
- Operator-local template store: save, show, run, list, and delete local command templates without sharing them or posting them anywhere.
- Clean-first display mode for the native shell and SGFX QA Status Board. This is presentation-only and does not change backend QA logic.
- Confirmation-gated Jira posting: optional dry-run-first Jira comment posting through the CLI. A real post requires operator-provided Jira configuration and an explicit `--confirm` flag.
- Dark IDE-style theme as the default operator surface with readable contrast and a single shipped theme.
- Operator-friendly logo branding in place of redundant header text across the sidebar, main header, and About panel.
- Animated F1-F12 hotkey popup with debug icon: pressing a function key shows a brief evidence overlay with a one-line explainer.
- Setup detection fast-path: when RaCo, Blender, RaCoHeadless, and the BMW Git checkout are present locally, SGFX detects them and skips manual setup ceremony.
- Cross-panel dependency consistency: Dependency Setup and Generate Workbook pre-flight read from the same operator-local registration source.
- Empty-state guidance per evidence page: Screenshot Test State, Daily Digest, Manual Review, Delivery Checklist, and the completed-setup welcome card explain unavailable local data.
- Auto-detect active ticket for Daily Digest from operator state, current branch, activity log, or operator entry.
- Manual Review evidence hints per Quality-Hero step: SGFX surfaces available or missing local evidence while keeping `manual_review_required: true`.
- Build review package progress UI: confirmation gate, hidden subprocess, live stdout tail, file-activity feed, elapsed time hint, and cancel button.
- Blender 4.1.1 opt-in auto-fetch with operator consent and local path registration.
- IDC_23 and IDC_EVO BMW pipeline lane routing from the BMW Git `models_build_config.yaml` source of truth.
- SVN-side profile name mapping: SGFX strips `_EVO` where needed for SVN-mirror reads.
- Dynamic profile registry from BMW Git with active-build defaults and Show-all access to the full registered set.
- Three honest `unavailable` classifications with Confluence anchors: BMW Git car not onboarded, BMW export succeeded but workbook not yet generated, and IDC_23 worktree setup missing.
- Per-page Confluence anchor surfacing for delivery checklist, Quality-Hero workflow, BMW pipeline Python, SG Daily, manual review, and About surfaces.
- Reusable env-gated real BMW pipeline probe for delivery export and screenshot capture evidence across G65, G70, NA8, F70, and U10.
- Multi-profile walkthrough harness for Clean Playwright and Grafiks UIA evidence across the five-profile set.
- BMW pipeline copy-on-completion output: generated workbook evidence and screenshot actual/diff evidence are copied into `workspace/out/<profile>/` while the native BMW working path remains visible in the evidence payload.

### Fixed
- `daily-digest latest --markdown` is safe on a fresh checkout and returns a clear no-review-package summary instead of failing.
- Native shell resource discovery uses generic SGFX resource roots and skips generated/build folders.
- Team-facing wording avoids approval, automation, production, codenames, and R&D leakage claims.
- The refreshed SVN staging bundle is curated from the SGFX QA Preflight alpha branch and ships only the clean-room README / CHANGELOG and curated documentation.
- BMW pipeline subprocess invocation contract: SGFX profile ids resolve to BMW model ids via filesystem-driven lookup against `cars/<brand>/<id>/`.
- Nonzero BMW screenshot exit no longer reports wrapper failure when actual/diff evidence is available; manual review remains required.
- BMW pipeline Python preference defaults to the Windows Python Launcher when no operator registration or override is set.
- Window and tab titles are unified to `Seriengrafik: Project Quality-Hero` across Clean, Grafiks, and OpenHTF station surfaces.
- Quality-Hero file presence no longer pre-selects a manual-review verdict; SGFX records evidence status and leaves verdict recording to the operator.
- Dependency auto-onboarding fast-path now writes detected install paths immediately so setup and pre-flight surfaces agree.

### Known limitations
- Local alpha for teammate review and SGFX workflow support.
- Manual RaCo, Blender, emulator, screenshot, and delivery review remain required.
- `review-board latest --json` requires a generated or copied review package.
- Some profile paths are operator-local and may need configuration on each workstation.
- Jira posting, SVN commits, BMW Git writes, and manual-review verdicts remain human-owned gates.
- IDC_23 lane execution requires a separate local `assets/idc23` worktree with `cars/BMW/_Shared/` present.
- Real BMW pipeline subprocess validation in the walkthrough harness runs only when the operator intentionally sets `SGFX_REAL_BMW_PIPELINE_AVAILABLE=1`.
- Alpina, MGmbH, and RollsRoyce brand-specific UX surface work is partial; these brands are registered but do not yet have dedicated evidence pages.
- `Cars_IDCevo/size_analysis/` is not yet populated by the data-prep / CI team; EVO workbooks currently appear in the unified `Cars/size_analysis/` location.
