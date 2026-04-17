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
- while making the current SG-side repo, delivery-checklist, and scene checks visible from the same local surface

See [qa-workflow-alignment.md](qa-workflow-alignment.md) for the current workflow fit, manual stages, and BMW-side blockers.
See [sg-checker-coverage-matrix.md](sg-checker-coverage-matrix.md) for the real SG checker inventory and current integration coverage.

The browser UI is the current lightweight operator surface for guided checks, report viewing, evidence, handoff, and teammate demos.
If a richer local shell is needed later for filesystem-heavy or tool-orchestration-heavy work, it should be a desktop wrapper over the same Python core rather than a replacement engine.
Future desktop-shell notes belong under `docs/research/` so the main workflow docs stay focused on SG QA reality, `.pdx/checkers`, evidence, readiness, and BMW blocker visibility.

## Start

From the repository root:

```bash
python -m sg_preflight ui --reload
```

PowerShell launcher:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_operator_ui.ps1 -OpenBrowser
```

Default address:

```text
http://127.0.0.1:8765/ui
```

Shared shell:

- dark mode is the default
- every page keeps a light/dark toggle in the header
- every page also keeps a guide toggle so teammate-facing help can be hidden without leaving the current view
- the header `What is this for?` helper gives the shortest explanation for first-time users or PM demos

## Views

### Home

Shows:

- a primary "what changed?" launcher for:
  - constants
  - anchors
  - carpaints
  - files, Lua, or references
- a workflow-stage launcher for:
  - before commit
  - before internal review
  - pre-delivery
  - post-integration
  - Jira / QA Hero evidence updates
- broader starts only as secondary choices:
  - check all live cars
  - run SG repo checkers
  - pick a car directly when you already know the slice
- a short first-time guide strip so teammates can understand the path in one read:
  - start with the change type
  - use workflow stage only if process context matters more than file type
  - open files and proof after the run
- canonical live profiles kept lower on the page as a secondary direct-entry path
- current live signal for the real `G70`, `G65`, and `G45` slices when the latest matrix output is present
- recent persisted checks and action runs
- setup, workflow-fit, and mirror-health detail behind foldouts instead of on the main path

### Guided Check

For a selected kind of change, shows:

- one recommended live car first when one slice is a stronger fit
- one direct button on that recommended card to run the smallest useful check
- other cars in a separate secondary section
- a link to the fuller per-car page when you need more control
- when launched from a workflow stage, keeps that stage attached to the next page and the eventual run record

### Run

For a selected profile, shows:

- one primary action only for that car
- guided pack-specific defaults when you arrive from the "what changed?" launcher
- stage-aware defaults when you arrive from the workflow-stage launcher
- why this profile is worth running
- current live signal for that slice, if available
- a visible `Files this check will use` block near the primary action
- the quick-check-only form behind a foldout
- the other actions for the car behind a foldout
- detected `Pivot_Master`, `Module_constants`, `CarPaint`, and anchor scene paths without making the operator hunt for them
- hidden context fields so stage-aware quick checks keep the same job/stage metadata as the primary button
- a first-time guide strip plus inline help popovers so the page explains when to trust the primary button and when to open the secondary foldouts

### Result

Shows:

- summary counts
- a primary `First Thing To Do` block for the first actionable finding
- owner and next-action text directly on that primary block
- the best matching source-file link for that first problem
- a primary handoff copy action for the first problem
- secondary quick-update and full-handoff copy actions, renamed per workflow stage where useful
- a clear `You are done when...` line for both problem and clean-run states
- a short secondary "what happened" and "do this next" layer
- a `Changed Since Last Check` panel that compares the current run against the previous completed run for the same profile and exposes a copy-ready diff update
- a more explicit `If You Feel Lost` block so a teammate can stay on one guided path instead of reading the whole result page
- a `Stage Readiness` panel that shows what this run already covers, what is still manual, and what remains blocked on the current machine
- an `Evidence Completeness` panel that separates local SG proof from full-stage readiness and makes proof/manual/blocked gaps explicit
- a `Stage-Specific Exports` panel with copy-ready Jira implementation updates, Jira positive and negative test notes, QA Hero notes, pre-delivery summaries, and delivery-doc snippets
- when recent repo-checker or scene-check actions exist for the same profile, stage exports now also cite concrete SG checker paths automatically instead of only generic checker-summary text
- a `Manual Review Companion` panel with Blender-vs-RaCo checklist text, screenshot evidence slots, and a copy-ready manual verification record
- sentence-case labels and section titles throughout the UI so the first read feels less like an internal debug surface
- grouped findings behind a foldout
- severity filtering
- per-finding drilldown behind a foldout
- exact source file and line evidence for `project_sanity` reference findings
- direct Lua-file evidence for `project_sanity.unused_lua`

### Files And Proof

Shows grouped direct links to:

- `Reports`
  - JSON / HTML / Markdown reports
- `Source-of-truth files`
  - the first relevant SG file pinned first when a finding exists
  - anchor `.rca`
  - `Pivot_Master.json`
  - `Module_constants_*.lua` or exported constants source
  - `CarPaint.json`
- `Run metadata`
  - bundle metadata
  - project manifest
  - run record JSON
- the same `Stage Readiness` summary so a teammate can see what evidence is still missing before the next workflow step
- the same `Evidence Completeness` panel so the proof/manual/blocked split stays visible on the evidence page
- the same stage-specific copy exports for ticket, QA Hero, pre-delivery, and delivery-doc work
- a `Checker evidence` section that pulls the latest completed repo-checker and scene-check outputs for the same profile, with direct `Open` links for the top file-backed hits when they exist
- the same manual-review companion so still-manual checks stay attached to the run evidence instead of living in chat memory

### Live Loading

Long-running runs and actions now switch to a large local `NOW LOADING...` overlay on the status page.

That overlay shows:

- estimated progress based on real persisted execution phases
- a coarse ETA once the run has enough progress to extrapolate
- the current phase label and a short detail sentence
- a clickable under-the-hood step list so operators can see whether the tool is materializing sources, scanning project-sanity data, running validators, or finalizing output
- a selectable per-step detail panel so clicking a step shows exact step events, current target path or command metadata, and nested child-status detail for wrapped automations
- persisted framework-event history so operators can see every recorded phase transition in order
- live action-log tail for long-running wrapped automations such as repo checker or scene check
- completed action pages for repo checker and scene check now prefer `Open these files first` plus structured checker evidence before dropping the operator into the raw log

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

The operator UI still targets canonical demo slices first, but the live registry now also includes broader real BMW coverage:

- `G70`
- `G65`
- `G45`

Additional widened support now includes slices such as:

- `G50`
- `G78`
- `NA0`
- `NA5`
- `NA6`
- `NA7`
- `NA8`
- `F70`
- `F74`
- `F78`
- `G48`
- `G68`
- `U06`
- `U10`
- `U11`
- `U12`

Ad-hoc arbitrary-path runs are intentionally secondary to keeping the shared live profile workflow stable.

## Workflow Boundary

Current expectation:

- use the UI to catch deterministic issues and produce evidence before manual review
- use the "what changed?" launcher first when you already know what kind of file or workflow step you touched
- use the workflow-stage launcher when the phase matters more than the file type, especially before commit, pre-delivery, after integration, or when you only need Jira / QA Hero evidence
- use the one-click QA actions when you want repo checker, delivery-checklist readiness, scene check, or the recommended per-car QA stack without touching terminals
- use `Show SG checker coverage` on Home when someone asks what real SG checker/tooling layer is available on this machine
- the repo-checker action now wraps the real SG checker stack more truthfully by running `check_all_styles.py` before `executeChecks.py`, so style/license plus Lua/shader/formatting coverage live under one operator action
- repo-checker and scene-check actions now parse their raw outputs into structured file-backed evidence, so action results, Files And Proof, stage readiness, and copy exports can point to concrete SG files instead of only saying that a checker ran
- the workspace action list now also exposes a full mirrored repo-checker path for `checkall.bat` scope as `repo_checker_all`
- the per-car action list now also exposes `printNotUsedResources.py` as an unused-resource scan, so leftover SG resource files can be checked from the same operator surface
- the per-car action list now also exposes the mirrored `deliveryChecklist` files as a readiness bridge, so SG-side delivery expectations and BMW-side blockers stay visible before smoke or handoff
- default to the full-check button when you just want the safest useful path for one car
- if the surface still feels noisy, ignore the secondary foldouts until after you have one result page
- do not claim that the UI replaces Blender visual checks
- do not claim that the UI replaces rack sessions
- do not claim that BMW screenshot smoke is fully usable on this machine until BMW access and target mapping exist

If BMW-side access is not present locally, the UI should show that honestly as a blocker instead of hiding it.
