# Operator UI Workflow

## Purpose

The operator UI is the local `run + inspect` surface for `sg-preflight`.

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

- canonical live profiles with explicit operator goals and focus areas
- current live signal for the real `G70`, `G65`, and `G45` slices when the latest matrix output is present
- compact readiness status for the local machine and mirrored SVN
- explicit QA-workflow-fit cards showing what is covered, partial, or blocked on the current machine
- cached mirror-health summary, with deeper detail behind foldouts
- recent persisted operator runs

### Run

For a selected profile, shows:

- why this profile is worth running
- current live signal for that slice, if available
- one-click canonical run action
- advanced options behind a foldout
- resolved SG source inputs
- detected `Pivot_Master`, `Module_constants`, `CarPaint`, and anchor scene paths

### Result

Shows:

- summary cards
- a decision summary for the run outcome
- grouped findings
- owner and action hints
- severity filtering
- per-finding evidence drilldown
- exact source file and line evidence for `project_sanity` reference findings
- direct Lua-file evidence for `project_sanity.unused_lua`

### Evidence

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
- do not claim that the UI replaces Blender visual checks
- do not claim that the UI replaces rack sessions
- do not claim that BMW screenshot smoke is already integrated

If BMW-side access is not present locally, the UI should show that honestly as a blocker instead of hiding it.
