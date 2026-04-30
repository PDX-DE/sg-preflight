# SG Preflight Status - 2026-04-14

## Update - 2026-04-17

Current local status on `feature/operator-ui-ux`:

- `sg-preflight` is now a working SG-side QA / preflight / evidence toolkit over one shared Python engine
- the current operator surfaces are the CLI and the local browser UI; any future desktop GUI must wrap the same engine rather than replace it
- the tool now carries a real SG checker coverage layer for `.pdx/checkers` instead of treating repo checks as a parallel custom universe
- the recommended per-car QA stack now includes repo checker coverage, unused-resource scans, delivery-checklist readiness, scene checks when available, and explicit BMW smoke blocker visibility
- the strongest remaining gaps are BMW-side access/execution and deeper file-level parsing of checker outputs into even stronger handoff evidence

## Update - 2026-04-16

Current local status on `feature/live-sg-matrix-and-anchor-groups`:

- the canonical live acceptance path still centers on `G70`, `G65`, and `G45`, but the live registry is now widened across additional real BMW slices such as `G50`, `G78`, `NA5`, `F70`, `G68`, and `U10`
- the full `python -m unittest discover -s tests -v` run now completes again on this machine instead of timing out in the acceptance path
- operator results now compare the current run against the previous completed run for the same profile
- long-running runs and actions now expose a live `NOW LOADING...` overlay with estimated progress, under-the-hood phase visibility, a coarse ETA, and clickable per-step drilldown with nested child progress where available
- result and evidence views now expose evidence-completeness scoring, richer Jira / QA Hero / pre-delivery exports, and a manual-review companion instead of only generic handoff text
- Home, Run, and Result now push more explicit "if you are unsure, do this" guidance so teammate pilots have a simpler path through the UI

## What This Project Is

`sg-preflight` is an internal Python-first SG QA / preflight / evidence toolkit for Seriengrafik / 3D Car.

The goal is not to build a flashy dashboard or a fake all-in-one replacement workflow.
The goal is to catch deterministic issues earlier, reduce obvious rack-session findings, route operators to the right source-of-truth files, and turn repeated manual checks into reusable evidence.

In practical terms, it is now a shared Python engine with two operator surfaces:

- ingests SG-shaped source inputs
- normalizes them into a stable bundle contract
- runs deterministic validation packs and SG-side checker wrappers
- writes JSON, HTML, and Markdown reports that QA, TA, and pipeline people can read
- serves a local browser UI for daily checks, file-backed proof, and handoff copy
- keeps future desktop-shell research separate from the current SG QA product surface

## What It Does Today

The repo is runnable today from the terminal and from the local browser UI.

Current validation packs:

- `anchors`
  - validates anchor naming and expected anchors against a normalized scene hierarchy bundle
- `constants`
  - compares expected vs exported values with exact checks and numeric tolerances
- `carpaints`
  - validates normalized carpaint payloads, including workbook-derived sources
- `project_sanity`
  - checks path hygiene, OneDrive risks, environment assumptions, Lua reference hygiene, and optional glTF drift

Current CLI surfaces:

- `python -m sg_preflight probe`
- `python -m sg_preflight materialize`
- `python -m sg_preflight run`
- `python -m sg_preflight list-profiles`
- `python -m sg_preflight run-profile`
- `python -m sg_preflight list-checkers`
- `python -m sg_preflight ui --reload`
- `python -m sg_preflight demo-good`
- `python -m sg_preflight demo-broken`

Current operator UI surfaces:

- Home
- Guided Check
- Workflow Stage
- Run
- Result
- Files And Proof

Current one-click QA actions:

- daily live matrix
- repo checker on full mirrored scope or per-car scope
- per-car unused-resource scan
- per-car delivery-checklist readiness bridge
- scene check when `RaCoHeadless.exe` is configured
- BMW screenshot smoke as an explicit blocked stage until BMW-side access exists

## Current Product Surface

The browser UI is the current lightweight operator shell.

It is the right surface today for:

- guided checks
- report viewing
- evidence and handoff copy
- action orchestration
- run history
- teammate demos

A future desktop GUI may still become the better operator shell later when the workflow needs tighter local-system-heavy integration around Blender, RaCo, local file opening, screenshot capture, filesystem packaging, or BMW-side scripts.

That future desktop shell must wrap the existing Python engine, services, actions, reports, and evidence model.
It is research and future architecture, not the current product identity.

## What It Already Proves

This is no longer only a demo-bundle toy.

It already proves that we can:

- scan SG-shaped local sources
- discover helper assets and repo-like structures
- materialize a normalized validation bundle
- run multiple packs end-to-end on non-demo local corpora
- generate machine-readable and human-readable reports

Working local source-backed slices today:

- `project_sanity`
  - driven by the `MiniKombi` corpus and other local source trees
- `carpaints`
  - driven by workbook `.xlsx` files and legacy SG-style JSON

## Real SG Checker Coverage

The tool no longer ignores the mirrored SG checker layer under `.pdx/checkers`.

Current real checker-aware coverage:

- `code_style_checker\check_all_styles.py`
  - wrapped directly through repo-checker actions
- `.pdx\checkers\executeChecks.py`
  - wrapped directly through repo-checker actions
- `.pdx\checkers\printNotUsedResources.py`
  - wrapped directly as per-car unused-resource actions
- `.pdx\checkers\deliveryChecklist`
  - exposed as a truthful readiness bridge in the same action/result/evidence flow
- `check_scenes.py`
  - exposed directly when `RaCoHeadless.exe` is configured
- BMW smoke
  - visible as a real blocked stage, not hidden or faked

The detailed checker-by-checker mapping lives in [sg-checker-coverage-matrix.md](sg-checker-coverage-matrix.md).

## Evidence And Handoff State

Current evidence model strengths:

- persistent run records
- persistent action records
- JSON / HTML / Markdown reporting
- grouped findings with owner/action hints
- stage readiness and evidence completeness
- copy-ready Jira / QA Hero / pre-delivery / delivery-doc exports
- manual-review companion text for Blender vs RaCo and screenshot evidence slots

## Why It Matters

This project directly maps to the pain points raised in onboarding, retro material, and current SG/BMW workflow conversations:

- too many obvious findings appear too late
- repeated checks are still manual or fragmented
- source-of-truth is hard to locate
- integration feels like a black box
- evidence is weak or inconsistent

`sg-preflight` addresses that by creating one deterministic layer in front of manual review and integration.

## Current Blockers

These do not stop current SG-side progress, but they still block the next major jump:

- BMW repo access and helper scripts for real screenshot/export/interface smoke
- BMW smoke target mapping per live profile
- end-to-end delivery-checklist execution beyond the current readiness bridge
- deeper file-level parsing of SG checker outputs into even stronger handoff artifacts
- MINI live profile rollout

## Current Strategic Position

The project is currently strongest in two areas:

- deterministic local SG-side preflight and evidence generation
- truthful workflow routing across current SG checkers, manual review, and BMW blockers

The next most important engineering slice is:

- deeper evidence parsing for repo-checker, scene-check, and related SG-side action outputs

After that:

- integrate BMW-side smoke properly once access exists
- decide on a future desktop shell only when the richer local workflow actually demands it
- keep that future desktop shell built on the same Python core instead of fragmenting the product

## One-Sentence Description For Others

`sg-preflight` is an internal SG-side QA / preflight / evidence tool for Seriengrafik 3D Car that runs deterministic checks, exposes the real `.pdx/checkers` workflow, and turns daily review and delivery prep into reusable evidence before integration and rack review.
