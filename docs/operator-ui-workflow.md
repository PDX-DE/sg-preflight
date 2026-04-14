# Operator UI Workflow

## Purpose

The operator UI is the local `run + inspect` surface for `sg-preflight`.

It does not replace the deterministic Python engine.
It calls the same shared services used by:

- `python -m sg_preflight run`
- `python -m sg_preflight run-profile`
- `scripts\run_real_sg_smoke.ps1`
- `scripts\run_real_live_matrix_smoke.ps1`

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

- canonical live profiles
- prerequisite status for the local machine and mirrored SVN
- cached fast mirror-audit result
- most recent deep mirror-audit cache, if present
- recent persisted operator runs

### Run

For a selected profile, shows:

- resolved SG source inputs
- detected `Pivot_Master`, `Module_constants`, `CarPaint`, and anchor scene paths
- default workflow context fields
- pack selection
- launch action for a profile run

### Result

Shows:

- summary cards
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
