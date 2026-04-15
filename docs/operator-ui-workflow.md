# Operator UI Workflow

## Purpose

The operator UI is the local daily-use surface for `sg-preflight`.

It does not replace the deterministic Python engine.
It calls the same shared services used by:

- `python -m sg_preflight run`
- `python -m sg_preflight run-profile`
- `scripts\run_real_sg_smoke.ps1`
- `scripts\run_real_live_matrix_smoke.ps1`

It also does not replace the full SG QA workflow.
It is the deterministic front end of that workflow:

- before rack
- before BMW screenshot smoke
- before delivery handoff
- while making the current SG-side repo and scene checks runnable from the same local surface

See [qa-workflow-alignment.md](qa-workflow-alignment.md) for the current workflow fit, manual stages, and BMW-side blockers.

## Start

From the repository root:

```bash
python -m sg_preflight ui
```

PowerShell launcher:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_operator_ui.ps1 -OpenBrowser
```

Default address:

```text
http://127.0.0.1:8765/ui
```

## Views

### Home

Shows:

- a "what changed?" launcher for:
  - constants
  - anchors
  - carpaints
  - files, Lua, or references
- three obvious jobs first:
  - check one car
  - check all live cars
  - run SG repo checkers
- canonical live profiles with plain-language goals and focus areas
- current live signal for the real `G70`, `G65`, and `G45` slices when the latest matrix output is present
- recent persisted checks and action runs
- setup, workflow-fit, and mirror-health detail behind foldouts instead of on the main path

### Guided Check

For a selected kind of change, shows:

- the plain-language job first
- the best live car to start with when one slice is a stronger fit
- one direct button per car to run the smallest useful check
- a link to the fuller per-car page when you need more control

### Run

For a selected profile, shows:

- one primary action for that car
- guided pack-specific defaults when you arrive from the "what changed?" launcher
- why this profile is worth running
- current live signal for that slice, if available
- a quick-check-only form for the deterministic preflight path
- advanced options behind a foldout
- resolved SG source inputs
- detected `Pivot_Master`, `Module_constants`, `CarPaint`, and anchor scene paths

### Result

Shows:

- summary counts
- a plain "what happened" block
- a plain "who should look at it" block
- a plain "open this now" block
- a short "do this now" section
- copy-ready quick-update and full-handoff actions
- grouped findings behind a foldout
- severity filtering
- per-finding drilldown behind a foldout
- exact source file and line evidence for `project_sanity` reference findings
- direct Lua-file evidence for `project_sanity.unused_lua`

### Files And Proof

Shows direct links to:

- JSON / HTML / Markdown reports
- bundle metadata
- project manifest
- anchor `.rca`
- `Pivot_Master.json`
- `Module_constants_*.lua` or exported constants source
- `CarPaint.json`
- run record JSON

## Persistence

Every operator-launched run writes a stable run record under:

```text
out/operator-ui/runs/<run-id>/
```

Each run directory contains:

- `run.json`
- `bundle/`
- `<profile>-report.json`
- `<profile>-report.html`
- `<profile>-report.md`

One-click QA actions write a parallel record under:

```text
out/operator-ui/actions/<action-run-id>/
```

Each action directory contains:

- `action.json`
- `action.log`
- `summary.json`
- `summary.md`
- any generated artifacts such as nested preflight reports or scene-check workbooks

Mirror-audit cache lives under:

```text
out/operator-ui/cache/
```

## Mirror Audit

Current behavior:

- fast audit compares configured live targets between `repositories\trunk` and `C:\repositories\trunk`
- deep audit compares the full mirrored `trunk` on demand
- cached audit notes are shown on the Home page to explain sampled drift
- current known deep drift is limited to `Playground\RaCoSceneMerging_PoC`

## Current Scope

The operator UI currently targets canonical live slices first:

- `G70`
- `G65`
- `G45`

Ad-hoc arbitrary-path runs are intentionally secondary to keeping the shared live profile workflow stable.

## Workflow Boundary

Current expectation:

- use the UI to catch deterministic issues and produce evidence before manual review
- use the "what changed?" launcher first when you already know what kind of file or workflow step you touched
- use the one-click QA actions when you want repo checker, scene check, or the recommended per-car QA stack without touching terminals
- default to the full-check button when you just want the safest useful path for one car
- do not claim that the UI replaces Blender visual checks
- do not claim that the UI replaces rack sessions
- do not claim that BMW screenshot smoke is fully usable on this machine until BMW access and target mapping exist

If BMW-side access is not present locally, the UI should show that honestly as a blocker instead of hiding it.
