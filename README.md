# SG Preflight

A Python-first internal framework for deterministic 3D Car QA preflight checks.

This project turns several current manual SG checks into repeatable validation with machine-readable and human-readable reports.

## What it does

It validates four packs end-to-end:

1. **anchors**
   - checks the `Anchorpoints_BoundingBox` subtree
   - validates anchor naming
   - detects duplicates
   - checks required anchors
   - compares encoded anchor position against metadata when available

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

Run the full smoke-test flow:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_smoke_test.ps1
```

This writes logs, JSON reports, HTML reports, markdown handoff reports, and a presentation-friendly summary to `out\smoke-test\latest`.

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
- workbook and legacy SG-style carpaint sources are normalized into the current validation schema with explicit inference notes
- `project_sanity` can already operate on the `MiniKombi` and `Introduction` corpora even before true 3D Car project roots arrive
- `--context` adds workflow/handoff metadata like car model, trim, delivery phase, and review target to the generated manifest
- `--md-out` writes a ticket/chat-friendly QA handoff report with grouped findings plus owner/action hints

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

- `main` is the stable release branch
- `develop` is the integration branch
- short-lived branches should use `feature/<topic>`, `release/<version>`, or `hotfix/<topic>`
- user-visible changes should update `CHANGELOG.md`
- run `python -m unittest discover -s tests -v` and `powershell -ExecutionPolicy Bypass -File scripts\run_smoke_test.ps1` before opening a merge request or PR
- GitHub repo hygiene includes PR templates, issue forms, and a basic CI workflow for the package and demo flows

See [CONTRIBUTING.md](CONTRIBUTING.md) for the intended branch and review flow.

## Current limitations

This is already fully runnable, but it is still an early internal release:
- direct SG/BMW source files are not in this workspace yet
- adapters are real and runnable, but some live formats still need representative files
- visual checks are not automated here
- rack / screenshot / trace integration is not yet wired in

The next real step is to swap the demo bundle for real SG-shaped files while keeping the validation core unchanged.
