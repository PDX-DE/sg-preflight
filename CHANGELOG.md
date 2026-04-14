# Changelog

All notable changes to this project should be documented in this file.

The format follows Keep a Changelog style and uses a simple pre-release-friendly structure.

## [Unreleased]

### Added

- Internal proprietary `LICENSE` for repository ownership and internal-use handling
- End-to-end CLI flow for `probe`, `materialize`, and `run`
- Canonical live-profile registry for `G70`, `G65`, and `G45`
- Shared Python service layer for bundle execution, report generation, and persistent run records
- Local FastAPI/Jinja operator UI with Home, Run, Result, and Evidence views
- Cached fast mirror audit plus on-demand deep mirror audit for the mirrored SVN
- CLI surfaces for `list-profiles`, `run-profile`, and `ui`
- `retro-extract` CLI command for turning Whiteboard retro exports into structured pain/action artifacts
- Validation packs for `anchors`, `constants`, `carpaints`, and `project_sanity`
- JSON and HTML reporting with grouped findings and pack-level summaries
- Markdown QA handoff reporting with grouped findings, workflow context, and owner/action hints
- Smoke-test automation in `scripts/run_smoke_test.ps1`
- Real-SG smoke automation in `scripts/run_real_sg_smoke.ps1`
- Additional live smoke scripts for `G65`, `G45`, and a side-by-side live matrix summary
- Source-drop analysis and audit documentation under `docs/`
- Workbook-backed and legacy-JSON-backed carpaint normalization
- SG-shaped project discovery and bundle materialization helpers
- GitHub issue forms, pull request template, and CI workflow
- Internal repository notices via `NOTICE.md`, `SECURITY.md`, and GitHub issue-template config
- Next-chat handoff prompt in `docs/next-chat-handoff-prompt-2026-04-14.md`
- Live SG config in `config/sg_rules_live.json` for a first real `G70` end-to-end slice
- Live SG configs for `G65` and classic `G45`
- Anchor validation support for multiple config-driven rule groups such as scale, tire-pressure, and sensor anchors

### Changed

- HTML reports now prioritize presentation-friendly grouped findings before raw detail tables
- Reports now carry workflow context like car model, trim, delivery phase, review target, and evidence source
- Real SG smoke scripts now consume the shared `run-profile` path instead of duplicating profile definitions in PowerShell
- Findings now carry richer evidence details for operator drilldown, including duplicate carpaint metadata and anchor-rule context
- `project_sanity` now persists exact source-file and line evidence for path-reference findings and unused Lua drilldown
- Mirror-audit notes are now visible on the operator Home page so sampled deep-audit drift is easier to interpret
- Smoke-test summary output now includes an executive snapshot and grouped takeaways
- Smoke-test flow now generates markdown handoff artifacts in addition to JSON and HTML reports
- README now documents the current local source-drop workflow and intended branch/release hygiene
- Generated outputs and local retro/source-drop folders are now ignored cleanly for a publishable repo state
- HTML reporting now stays compatible with Python 3.11 in CI
- GitHub Actions now use Node 24-ready `actions/checkout@v5` and `actions/setup-python@v6`
- CI now treats `demo-broken` as an expected-failure fixture and accepts exit code `2` explicitly
- `materialize` now auto-discovers live SG inputs such as `RES_*_AnchorPoints.rca`, `*_Pivot_Master.json`, `Module_constants_*.lua`, and `CarPaint.json`
- `anchors` normalization now supports zipped `.rca` scene bundles directly
- `constants` normalization now supports real SG `Pivot_Master` JSON and `Module_constants_*.lua` sources
- SG discovery and project-sanity helpers now recognize live helper script names and hyphenated SG environment conventions
- Legacy SG `CarPaint.json` normalization now uses live `StyleID` semantics plus actual clearcoat/undercoat fields when available
- `project_sanity` now reads `racoVersion` directly from zipped `.rca` payloads and classifies SG-relative scene links separately from true absolute-path risks
- `project_sanity` text indexing now falls back to plain-text `.rca` files when a scene is not zipped, which removes false `unused_lua` warnings in SG-shaped fixtures
- Real live `G70` smoke output is now much cleaner: cross-car contamination and unused Lua survive as actionable warnings, while SG-internal relative links no longer flood the report
- Repository metadata now marks the package as proprietary/internal-use in `pyproject.toml`
- Live reporting and smoke automation now support side-by-side comparison across `G70`, `G65`, and `G45`
- Anchor root selection now prefers the richest matching subtree when SG scenes contain duplicate root names

### Known Gaps

- The first live real-source rollout now covers `G70`, `G65`, and `G45`, but additional BMW/MINI cars still need profile rollout
- The operator UI is intentionally local-first; a thin desktop wrapper is still deferred until adoption requires one-click packaging
- Direct RaCo-runtime execution of helper scripts such as `read_json_carpaints.py` is still not part of the current CLI-first flow
