# Changelog

All notable changes to this project should be documented in this file.

The format follows Keep a Changelog style and uses a simple pre-release-friendly structure.

## [Unreleased]

### Added

- End-to-end CLI flow for `probe`, `materialize`, and `run`
- `retro-extract` CLI command for turning Whiteboard retro exports into structured pain/action artifacts
- Validation packs for `anchors`, `constants`, `carpaints`, and `project_sanity`
- JSON and HTML reporting with grouped findings and pack-level summaries
- Markdown QA handoff reporting with grouped findings, workflow context, and owner/action hints
- Smoke-test automation in `scripts/run_smoke_test.ps1`
- Source-drop analysis and audit documentation under `docs/`
- Workbook-backed and legacy-JSON-backed carpaint normalization
- SG-shaped project discovery and bundle materialization helpers
- GitHub issue forms, pull request template, and CI workflow

### Changed

- HTML reports now prioritize presentation-friendly grouped findings before raw detail tables
- Reports now carry workflow context like car model, trim, delivery phase, review target, and evidence source
- Smoke-test summary output now includes an executive snapshot and grouped takeaways
- Smoke-test flow now generates markdown handoff artifacts in addition to JSON and HTML reports
- README now documents the current local source-drop workflow and intended branch/release hygiene
- Generated outputs and local retro/source-drop folders are now ignored cleanly for a publishable repo state
- HTML reporting now stays compatible with Python 3.11 in CI
- GitHub Actions now use Node 24-ready `actions/checkout@v5` and `actions/setup-python@v6`

### Known Gaps

- True SG-native anchor scene exports are still not available in this workspace
- Real generated `*_Pivot_Master.json` and production `read_json_carpaints.py` inputs still need to be fetched
- The current real-source flow is based on OneDrive/tool drops and representative corpora, not yet on the final BMW-side source-of-truth paths
