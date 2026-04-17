# SG Preflight

A local SG-side QA / preflight / evidence tool for Seriengrafik / 3D Car, built around one shared Python validation engine.

This project helps operators run deterministic checks, inspect real source-of-truth files, generate reusable evidence, and prepare Jira / QA Hero / handoff notes before review, delivery, or integration.

See [LICENSE](LICENSE) for the internal proprietary license terms.

## Internal Notice

> [!IMPORTANT]
> This repository is internal capability tooling for Paradox Cat GmbH Seriengrafik / 3D Car work. Treat mirrored SVN content, generated evidence, and workflow notes as internal material unless an internal release process explicitly says otherwise.

This repository is being prepared as internal capability tooling for Paradox Cat GmbH Seriengrafik / 3D Car work.

- treat mirrored SVN content, generated reports, and workflow notes as internal material
- keep `repositories/`, `out/`, and similar local evidence paths untracked unless an internal release process explicitly requires otherwise
- prefer sanitized examples when sharing progress outside the direct project context

See [NOTICE.md](NOTICE.md) for the current handling note.

## Repository Status

- current maturity: working internal preflight framework with a broadened real BMW live-slice registry plus a local operator UI
- branch model: GitFlow-style `main`, `develop`, `feature/*`, `release/*`, `hotfix/*`
- contribution/review flow: see [CONTRIBUTING.md](CONTRIBUTING.md)
- security / sensitive-data handling: see [SECURITY.md](SECURITY.md)

## What it does

It validates four packs end-to-end:

1. **anchors**
   - checks `Anchorpoints_BoundingBox` and classic SG anchor families such as sensor / tire-pressure / scale packs
   - validates anchor naming
   - detects duplicates
   - checks required anchors
   - compares encoded anchor position against metadata when available
   - supports multiple config-driven anchor rule groups under one pack

2. **constants**
   - compares expected engineering values vs exported values
   - validates required keys
   - validates numeric types
   - enforces tolerances
   - validates exact-match fields like trim / engine

3. **carpaints**
   - validates schema and required keys
   - validates allowed finish types
   - validates numeric ranges
   - validates unique IDs and names
   - applies a few semantic cross-checks

4. **project_sanity**
   - flags OneDrive paths
   - flags suspicious absolute paths
   - checks recommended RaCo version policy
   - flags unreferenced Lua files
   - flags glTF topology drift and object reorder risk
   - checks required environment variables

## Why this scope

This tool is intentionally aimed at pain that is both:

- repeatedly mentioned in current 3D / SG onboarding and QA docs
- realistic to catch deterministically before manual visual review, rack time, or integration

## Current Surfaces

- Python core engine
- CLI over the same engine
- local web UI as the current lightweight operator surface for guided checks, report viewing, evidence, handoff, and teammate demos
- experimental desktop operator shell over the same engine for faster local file opening, blocker visibility, and checker-evidence triage without replacing the browser UI
  - current desktop v0 now translates the local UnleashedRecomp menu language into Qt chrome: scanline header bars, category-tab action strip, grid-framed panels, TV-static-style evidence framing, and a bottom button-guide band

## Quick start

From the project root:

```bash
python -m sg_preflight run \
  --bundle demo/good \
  --config config/sg_rules.json \
  --json-out out/good-report.json \
  --html-out out/good-report.html \
  --md-out out/good-report.md
```

Broken demo:

```bash
python -m sg_preflight run \
  --bundle demo/broken \
  --config config/sg_rules.json \
  --json-out out/broken-report.json \
  --html-out out/broken-report.html \
  --md-out out/broken-report.md
```

Run tests:

```bash
python -m unittest discover -s tests -v
```

This full test command now completes again in the current live-profile environment; the earlier timeout came from duplicate `project_sanity` manifest scans on the acceptance path and has been removed.

List the currently registered live profiles:

```bash
python -m sg_preflight list-profiles --json
```

Run one canonical live profile end-to-end:

```bash
python -m sg_preflight run-profile G70 --fail-on never
```

Start the local operator UI:

```bash
python -m sg_preflight ui --reload
```

Start the experimental desktop operator shell:

```bash
python -m pip install -e .[desktop]
python -m sg_preflight desktop --profile G65
```

List the one-click SG QA actions:

```bash
python -m sg_preflight list-actions --json
```

List the current SG checker coverage layer:

```bash
python -m sg_preflight list-checkers --json
```

Run the full daily live preflight matrix as one action:

```bash
python -m sg_preflight run-action daily_live_matrix
```

Run the recommended automated QA stack for one live car:

```bash
python -m sg_preflight run-action qa_stack__g65
```

Or use the PowerShell launcher/check script:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_operator_ui.ps1 -OpenBrowser
```

The operator UI serves locally at `http://127.0.0.1:8765/ui` by default.
It provides:

- Home: `What Changed?` is the primary start path; broader starts such as daily matrix, repo checker, and direct car picking are intentionally secondary
- Home: a second workflow-stage launcher now supports starts like `Before commit`, `Pre-delivery`, `Post-integration`, and `Jira / QA Hero evidence`
- Guided checks: show one recommended car first, then keep the other cars in a separate secondary section; the selected workflow stage stays attached when you start from the stage launcher
- Run: one primary button only, plus a visible `Files this check will use` block; quick-check and alternate actions stay behind foldouts, and workflow-stage context now persists into quick checks too
- Result: a primary `First Thing To Do` panel, direct source-file link for the first problem, a stage-aware handoff copy action, a `Stage Readiness` panel, and a `Changed Since Last Check` comparison against the previous completed run for the same profile
- Result and action pages: repo-checker, scene-check, unused-resource, and delivery-checklist runs now surface structured checker-derived evidence, including `Open these files first` guidance, concrete affected paths, and copy-ready SG checker references instead of only raw logs
- Live progress: long-running runs and actions now show a `NOW LOADING...` overlay with estimated progress, coarse ETA, full step visibility, persisted framework events, live action-log tail, and clickable per-step drilldown with nested child-status detail where available
- Guidance: Home, Run, and Result pages now include explicit "if you are unsure, do this" blocks so teammate pilots can stay on the main path without exploring every foldout
- Result and Files And Proof: evidence-completeness scoring, explicit proof/manual/blocked grouping, richer stage-specific exports for Jira / QA Hero / pre-delivery use, and a manual-review companion with screenshot-slot and Blender-vs-RaCo copy blocks
- Files And Proof: grouped `Reports`, `Source-of-truth files`, `Run metadata`, and checker-derived evidence links, with the first relevant SG file pinned when a finding exists plus the same stage-readiness summary for evidence completeness
- One-click actions for the wider SG QA flow:
  - daily live matrix
  - full mirrored repo checker coverage for `checkall.bat` scope, exposed as `repo_checker_all` without calling the batch wrapper directly
  - repo checker on workspace or per-car scope, now wrapping the SG checker stack through `code_style_checker\check_all_styles.py` plus `.pdx\checkers\executeChecks.py`
  - per-car unused-resource scan through `.pdx\checkers\printNotUsedResources.py`, now parsed into file-backed resource evidence
  - per-car delivery-checklist readiness bridge through `.pdx\checkers\deliveryChecklist`, now parsed into openable local checklist assets plus explicit BMW-side blocked follow-ups
  - per-car recommended QA stack
  - scene check when `RaCoHeadless.exe` is configured
  - BMW screenshot smoke as an explicit blocked stage until BMW-side access and target mapping exist

UI-triggered runs persist under `out\operator-ui\runs`.
Mirror-audit cache lives under `out\operator-ui\cache`.
One-click action records persist under `out\operator-ui\actions`.

Operator workflow notes live in [docs/operator-ui-workflow.md](docs/operator-ui-workflow.md).
Teammate pilot guidance lives in [docs/teammate-pilot-playbook.md](docs/teammate-pilot-playbook.md).
QA workflow alignment lives in [docs/qa-workflow-alignment.md](docs/qa-workflow-alignment.md).
SG checker coverage lives in [docs/sg-checker-coverage-matrix.md](docs/sg-checker-coverage-matrix.md).
Future desktop-shell research and visual-direction notes live under [docs/research](docs/research), while the experimental shell itself still wraps the same Python actions, reports, and evidence model.

Run the full smoke-test flow:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_smoke_test.ps1
```

This writes logs, JSON reports, HTML reports, markdown handoff reports, and a presentation-friendly summary to `out\smoke-test\latest`.

Run the real SG smoke flow against the copied SVN mirror:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_real_sg_smoke.ps1
```

This now runs the canonical `G70` profile through `run-profile` and writes bundle, reports, and `run.json` to `out\real-sg-smoke\latest`.

Run the additional live-car smokes:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_real_g65_smoke.ps1
powershell -ExecutionPolicy Bypass -File scripts\run_real_g45_smoke.ps1
```

Run the side-by-side live matrix:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_real_live_matrix_smoke.ps1
```

This writes a comparison summary plus per-car bundles, reports, and run records to `out\real-live-matrix\latest`.

> [!NOTE]
> The live matrix is still the best single command for showing the tool to the 3D team because it compares the strongest current demo slices side by side, even though the registry now supports a wider real BMW slice set.

Extract a structured pain/action summary from a Whiteboard retro export:

```bash
python -m sg_preflight retro-extract \
  --html "3D Car Delivery Retro/3D Car Delivery Retro.html" \
  --comments-json "3D Car Delivery Retro/3D Car Delivery Retro-comments.json" \
  --json-out out/retro-export.json \
  --md-out out/retro-export.md
```

Inspect likely SG repo roots and helper assets:

```bash
python -m sg_preflight probe
```

Materialize a normalized bundle from SG-shaped inputs:

```bash
python -m sg_preflight materialize ^
  --output-bundle out\real-bundle ^
  --repo-root C:\path\to\Seriengrafik\trunk ^
  --project-root C:\path\to\Seriengrafik\trunk\Cars\BMW\G70 ^
  --scene-source C:\path\to\scene_dump.json ^
  --constants-expected-source C:\path\to\Pivot_Master.json ^
  --constants-exported-source C:\path\to\constants_exported.json ^
  --carpaints-source C:\path\to\carpaints.json ^
  --carpaints-helper C:\path\to\read_json_carpaints.py ^
  --env SG_REPO=C:\path\to\Seriengrafik ^
  --env SG_CARMODELS_REPO=C:\path\to\digital-3d-car-models ^
  --context car_model=G70 ^
  --context trim_line=Sport ^
  --context delivery_phase=preview ^
  --context review_target=internal_rack ^
  --context evidence_source=local_export_and_constants
```

Live SG mirror workflow with the copied SVN inside this repo:

```powershell
python -m sg_preflight run-profile G70 `
  --output-root out\g70-live `
  --fail-on never
```

This writes:

- `out\g70-live\bundle\`
- `out\g70-live\g70-report.json`
- `out\g70-live\g70-report.html`
- `out\g70-live\g70-report.md`
- `out\g70-live\run.json`

The `materialize` command now auto-discovers these live SG inputs from `project_root` when they exist:

- `resources/*AnchorPoints/*.rca` for anchors
- `_Workfiles/_WorkFiles/json/*_Pivot_Master.json` for expected constants
- `_Common/constants/scripts/Module_constants_*.lua` for exported constants
- `Cars/<brand>/CarPaint.json` under `repo_root` for carpaint data

Current source-drop workflow with the files already in this workspace:

```powershell
python -m sg_preflight materialize `
  --output-bundle out\current-source-bundle `
  --repo-root OneDrive_4_14-04-2026 `
  --project-root OneDrive_5_14-04-2026\Debug\MiniKombi `
  --carpaints-source Markus_Delete\Documents\Carpaints.xlsx

python -m sg_preflight run `
  --bundle out\current-source-bundle `
  --config config\sg_rules.json `
  --packs carpaints,project_sanity `
  --json-out out\current-source-bundle.json `
  --html-out out\current-source-bundle.html `
  --md-out out\current-source-bundle.md `
  --fail-on never
```

Notes:

- `--carpaints-source` now accepts workbook-style `.xlsx` files in addition to JSON.
- SG `CarPaint.json` catalogs, `Pivot_Master.json`, `Module_constants_*.lua`, and zipped `.rca` anchor scenes are now supported directly.
- workbook and legacy SG-style carpaint sources are normalized into the current validation schema with explicit inference notes
- live SG `StyleID` semantics are normalized as `solid`, `metallic`, and `frozen` based on the shared carpaint interfaces
- live SG environment conventions `SG-Repo` and `SG-CarModels-Repo` are recognized alongside the older underscore-style variants
- `project_sanity` can already operate on the `MiniKombi` and `Introduction` corpora even before true 3D Car project roots arrive
- `project_sanity` now distinguishes SG-relative scene links and cross-car contamination from true filesystem absolute-path risks
- `--context` adds workflow/handoff metadata like car model, trim, delivery phase, and review target to the generated manifest
- `--md-out` writes a ticket/chat-friendly QA handoff report with grouped findings plus owner/action hints
- live configs now cover:
  - `config/sg_rules_live.json` for the widened IDCevo BMW family such as `G70`, `G50`, `G78`, and `NA0` / `NA5-NA8`
  - `config/sg_rules_live_g65.json` for the constants-heavy `G65` slice
  - `config/sg_rules_live_g45.json` for the classic BMW family such as `G45`, `G68`, `U10`, and `F70`

## Bundle contract

A bundle is a folder containing:

```text
scene_hierarchy.json
constants_expected.json
constants_exported.json
carpaints.json
project_manifest.json
```

That is the current PoC contract.

Later, real adapters can generate the same bundle from:
- Blender exports
- RaCo scenes or helper scripts
- existing internal JSON / constants sources
- project repo metadata

This repo now includes that first adapter layer:
- `probe` discovers SG-style repo roots and known helper assets
- `materialize` normalizes SG-shaped inputs into the bundle contract
- validators continue to operate only on the normalized bundle
- `list-profiles` exposes the canonical live-profile registry
- `run-profile` materializes and validates a canonical live slice in one step
- `ui` serves the local operator workflow over the same shared services

## Project structure

```text
sg-preflight/
  sg_preflight/
    adapters/
    validators/
  config/
  demo/
    good/
    broken/
  docs/
  tests/
```

## Exit codes

- `0` = no findings at or above threshold
- `2` = findings at or above threshold
- `1` = runtime / usage error

Default failure threshold is `error`.

## Workflow

This repo is still pre-publication, but it already follows a simple release hygiene shape:

> [!TIP]
> Use `develop` for ongoing integration work and keep feature branches short-lived. Reserve `main` for stable snapshots that are ready to represent the project internally.

- `main` is the stable release branch
- `develop` is the integration branch
- short-lived branches should use `feature/<topic>`, `release/<version>`, or `hotfix/<topic>`
- user-visible changes should update `CHANGELOG.md`
- keep repository ownership and handling aligned with `LICENSE`, `NOTICE.md`, and `SECURITY.md`
- run `python -m unittest discover -s tests -v` and `powershell -ExecutionPolicy Bypass -File scripts\run_smoke_test.ps1` before opening a merge request or PR
- run `powershell -ExecutionPolicy Bypass -File scripts\run_real_live_matrix_smoke.ps1` before presenting or reviewing the live SG slices
- GitHub repo hygiene includes PR templates, issue forms, and a basic CI workflow for the package and demo flows

See [CONTRIBUTING.md](CONTRIBUTING.md) for the intended branch and review flow.

## GitHub Hygiene

The repo already includes:

- issue forms for bug reports and feature requests
- a pull request template
- CI for unit tests and demo flows
- internal-use and security guidance for repository-facing docs

## Current limitations

This is already fully runnable, but it is still an early internal release:

> [!WARNING]
> The current live findings are useful production signal, not synthetic demo failures. A clean tooling run does not mean the car is clean; it means the deterministic checks completed successfully and the remaining findings are likely worth triage.
- the repo now supports a broader real BMW live-slice registry on the mirrored SG checkout, with the current strongest demo slices still centered on `G70`, `G65`, and `G45`
- the local operator UI is intentionally a simple local work surface over the same engine, not a separate second validation engine
- the framework is intended to improve the established SG QA flow, not replace BMW screenshot smoke, rack review, or Blender visual checks
- the current live matrix baseline is meaningful already:
  - `G70` surfaces a real duplicate BMW carpaint ID plus cross-car and unused-Lua warnings
  - `G65` surfaces real constant drift between `Pivot_Master` and `Module_constants`
  - `G45` proves the multi-family anchor support while still surfacing the shared duplicate BMW carpaint ID
- visual checks are not automated here
- rack / screenshot / trace integration is not yet wired in
- missing BMW-side access or a local `digital-3d-car-models` clone is still an explicit blocker for full screenshot-smoke coverage on this machine

The next real step is to widen coverage from the current BMW rollout into MINI variants while keeping the validation core unchanged.
