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

### Fixed
- `daily-digest latest --markdown` is safe on a fresh checkout and returns a clear no-review-package summary instead of failing.
- Native shell resource discovery uses generic SGFX resource roots and skips generated/build folders.
- Team-facing wording avoids approval, automation, production, codenames, and R&D leakage claims.
- The refreshed SVN staging bundle is curated from the SGFX QA Preflight alpha branch and ships only the clean-room README / CHANGELOG and curated documentation.

### Known limitations
- Local alpha for teammate review and SGFX workflow support.
- Manual RaCo, Blender, emulator, screenshot, and delivery review remain required.
- `review-board latest --json` requires a generated or copied review package.
- Some profile paths are operator-local and may need configuration on each workstation.
- Jira posting, SVN commits, BMW Git writes, and manual-review verdicts remain human-owned gates.
