# Changelog - Seriengrafik: Project Quality-Hero (local alpha)

This changelog covers the curated SVN handover bundle only. Internal
working-tree history, coordination notes, and generated evidence are kept
outside this bundle.

## [Unreleased - local alpha]

### Added
- Standalone Ramses R0 probe: a noninteractive native helper plus Python runner that records scene metadata, native validation findings, structural inventory, logic-update evidence, renderer lifecycle timing, and at most one 480x270 authored-frame readback with an honest content/black/undetermined classification. Evidence only - it never approves anything; runs are local, read-only against the source scene, and hash-verified end to end.
- The one-button profile preflight now runs the packaged Ramses scene probe as a second stage when its pinned helper and the resolved scene are available: validation, structure, and logic evidence appear as scoped check rows next to the existing gates, and a missing helper simply reports as unavailable without affecting the local QA result.
- Pinned Python launcher (`scripts/run_sgfx_python.ps1`) so test and evidence commands always run on the intended local interpreter.
- The C0 Control Center entries describe a staged local candidate that has since become the installed default; see the double-click cutover entry below.
- Cut the installed/default double-click path over to the native Qt Quick shell (`dashboard run --ui-mode qt-quick`); the NiceGUI Clean dashboard remains available via `--ui-mode clean`.
- The Qt Quick Full QA Pass and batch pages bind their actions to the car selected in the profile dropdown: the local QA run control appears first for that car, a busy banner names the action while it runs, and a persistent result panel shows the status, summary lines, and evidence path after it completes.
- Profile-neutral QA Control Center startup with explicit operator selection instead of an invented default profile.
- One selected-profile local preflight action limited to Anchors, Constants, Carpaints, and Project Sanity.
- Seven truthful Home and Full QA gates with bounded copy-ready evidence and a deterministic next safe action.
- Same-data Presentation mode that changes chrome without changing the selected profile, evidence, action, or inspection identity.
- Bounded selected-profile Ramses turntable preview with an opaque cache channel and an honest generic fallback when the compatible scene or helper is unavailable.
- Product-facing `Open 3D inspection` naming while the internal typed Grafiks capability remains unchanged.
- Native operator observability: read-only overview panel sourced from the Python `desktop-state overview` endpoint.
- Screenshot review prioritization: P0-P3 suggested review order for screenshot candidates. This is guidance, not a verdict.
- Daily / morning QA digest: JSON, text, and Markdown status summaries with evidence, blockers, manual-review pending, waiting-owner, and suggested-review-order sections.
- RaCo / Blender manual-review companion: operator-recorded manual-review sessions with Quality Hero step focus and no automatic verdict recording.
- Delivery documentation and export-size analysis readers: read-only ingestion of operator-local workbook evidence.
- BMW / MINI screenshot-test state and BMW Git readiness surfaces: read-only local dependency visibility for profile-level QA readiness.
- QA Hero readiness surface: read-only presence/count summary for documented 3D Car review subsystems.
- CLI usability updates: consistent `--format text|json|markdown` rendering and `--output-path` / `--out` file output for supported read/status commands.
- CLI and JSON workflow guides for operators adding or running checks through existing Python-owned SGFX surfaces.
- Operator-local template store: save, show, run, list, and delete local command templates without sharing them or posting them anywhere.
- Clean-first display mode for the native shell and SGFX QA Status Board. This is presentation-only and does not change backend QA logic.
- Advanced Jira integration: previews and the weekly ticket draft live under `integration jira`; verification and write behavior use separate explicit gates.
- Dark IDE-style theme as the default operator surface with readable contrast and a single shipped theme.
- Operator-friendly logo branding in place of redundant header text across the sidebar, main header, and About panel.
- Animated F1-F12 hotkey popup with debug icon: pressing a function key shows a brief evidence overlay with a one-line explainer.
- Setup detection fast-path: when RaCo, Blender, RaCoHeadless, and the BMW Git checkout are present locally, SGFX detects them and skips manual setup ceremony.
- Cross-panel dependency consistency: Dependency Setup and Generate Workbook pre-flight read from the same operator-local registration source.
- Empty-state guidance per evidence page: Screenshot Test State, Daily Digest, Manual Review, Delivery documentation, and the completed-setup welcome card explain unavailable local data.
- Auto-detect active ticket for Daily Digest from operator state, current branch, activity log, or operator entry.
- Manual Review evidence hints per Quality-Hero step: SGFX surfaces available or missing local evidence while keeping `manual_review_required: true`.
- Build review package progress UI: confirmation gate, background subprocess, live stdout tail, file-activity feed, elapsed time hint, and cancel button.
- Blender 4.1.1 opt-in auto-fetch with operator consent and local path registration.
- IDC_23 and IDC_EVO BMW pipeline lane routing from the BMW Git `models_build_config.yaml` source of truth.
- SVN-side profile name mapping: SGFX strips `_EVO` where needed for SVN-mirror reads.
- Dynamic profile registry from BMW Git with active-build defaults and Show-all access to the full registered set.
- Three honest `unavailable` classifications with Confluence anchors: BMW Git car not onboarded, BMW export succeeded but workbook not yet generated, and IDC_23 worktree setup missing.
- Per-page Confluence anchor surfacing for delivery documentation, Quality-Hero workflow, BMW pipeline Python, SG Daily, manual review, and About surfaces.
- Reusable env-gated real BMW pipeline probe for delivery export and screenshot capture evidence across G65, G70, NA8, F70, and U10.
- Multi-profile walkthrough evidence across the five-profile set for Clean and Grafiks.
- BMW pipeline copy-on-completion output: generated workbook evidence and screenshot actual/diff evidence are copied into `workspace/out/<profile>/` while the native BMW working path remains visible in the evidence payload.

### Data handling
- Runtime: local-only. The shipped tool reads operator-local files and does not call any external service or send telemetry. Operator records every verdict.
- Suggested evidence: deterministic local filesystem probes (file exists, directory contains these files, workbook has these rows). The tool does not pre-decide.
- Advanced `integration jira` previews load no credentials and make no network request. `--confirm-network` permits Jira verification and weekly-ticket GETs; a Jira write also needs its action-specific confirmation.

### Fixed
- Operator actions now work when the workspace is the SVN trunk checkout itself, not only a wrapper folder holding a nested `repositories/trunk` mirror: mirror-path resolution recognizes a flat checkout, profile rules configs fall back to the packaged copy when the workspace carries none, and the exe bundle ships `config/`.
- On a flat trunk checkout the post-run source-protection guard no longer treats the workspace's own `out/` evidence writes as a source mutation, so completed diagnostics stop being misreported as failed.
- The selected-profile 3D turntable preview now works with current-generation IDCevo exports as well as older ones: the camera interface accepts both authored aspect-property generations, verified against a real staged export.
- A 3D shell that closes immediately after launch is now always reported as a failed launch, even when it exits with code 0, so the operator sees an honest fallback message instead of a silent no-op.
- Kept dashboard/profile evidence local and current: stale page or refresh completions are ignored, profile summaries do not run Jira lookup, legacy Jira credential reads remain non-mutating, and dependency registrations use atomic cross-process transactions.
- Focused the default Clean shell on Home, 18 operational evidence surfaces, and nav-only About. Personal-ticket, duplicate readiness, parked analysis, settings, automatic Jira lookup, and dashboard report-attachment controls are no longer registered on the default path.
- Moved the weekly ticket draft to `integration jira weekly-tickets`; its default preview is log-free, leaves credential and cache state untouched, and keeps the former command only as hidden argv compatibility.
- `daily-digest latest --markdown` is safe on a fresh checkout and returns a clear no-review-package summary instead of failing.
- Native shell resource discovery uses generic SGFX resource roots and skips generated/build folders.
- Reviewed all team-facing text for a clear, consistent voice.
- The SVN handover bundle ships the README, CHANGELOG, and curated operator documentation.
- BMW pipeline subprocess invocation contract: SGFX profile ids resolve to BMW model ids via filesystem-driven lookup against `cars/<brand>/<id>/`.
- Nonzero BMW screenshot exit no longer reports wrapper failure when actual/diff evidence is available; manual review remains required.
- BMW pipeline Python preference defaults to the Windows Python Launcher when no operator registration or override is set.
- Window and tab titles are unified to `Seriengrafik: Project Quality-Hero` across Clean, Grafiks, and station surfaces.
- Quality-Hero file presence no longer pre-selects a manual-review verdict; SGFX records evidence status and leaves verdict recording to the operator.
- Dependency auto-onboarding fast-path now writes detected install paths immediately so setup and pre-flight surfaces agree.

### Known limitations
- The C0 Ramses preview is a finite rendered turntable sequence, not a continuously interactive embedded real-time viewport.
- Warm-start and first-run Control Center timing remain open until measured on a reference-ready workstation.
- Local alpha for teammate review and SGFX workflow support.
- Manual RaCo, Blender, emulator, screenshot, and delivery review remain required.
- `review-board latest --json` requires a generated or copied review package.
- Some profile paths are operator-local and may need configuration on each workstation.
- Jira posting, SVN commits, BMW Git writes, and manual-review verdicts remain human-owned gates.
- IDC_23 lane execution requires a separate local `assets/idc23` worktree with `cars/BMW/_Shared/` present.
- Real BMW pipeline subprocess validation in the walkthrough harness runs only when the operator intentionally sets `SGFX_REAL_BMW_PIPELINE_AVAILABLE=1`.
- Alpina, MGmbH, and RollsRoyce brand-specific UX surface work is partial; these brands are registered but do not yet have dedicated evidence pages.
- `Cars_IDCevo/size_analysis/` is not yet populated by the data-prep / CI team; EVO workbooks currently appear in the unified `Cars/size_analysis/` location.
