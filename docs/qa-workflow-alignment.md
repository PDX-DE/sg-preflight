# QA Workflow Alignment

## Purpose

This note maps `sg-preflight` against the current Seriengrafik 3D Car QA workflow.

The intent is explicit:

- improve the established SG QA flow
- reduce avoidable findings before rack, review, and delivery pressure
- make evidence and ownership clearer
- stay honest about what is still manual or BMW-side

`sg-preflight` is not a replacement for Blender visual review, rack approval, or BMW-maintained screenshot smoke.

## Current Workflow Fit

### 1. Deterministic preflight before review

Current status: covered

What this means:

- canonical live runs exist for `G70`, `G65`, and `G45`
- the framework auto-discovers SG inputs from the mirrored SVN
- the current engine validates:
  - anchors
  - constants
  - carpaints
  - project sanity
- JSON, HTML, Markdown, and persistent run metadata are generated on every run

This is the part of the QA workflow that `sg-preflight` already owns directly.

### 2. Constants verification against source-of-truth

Current status: covered for the live slices

What this means:

- `Pivot_Master.json` and `Module_constants_*.lua` are already materialized into the normalized bundle
- real value drift is visible now, especially on `G65`
- the operator UI exposes both values and both source files in the drilldown

This directly supports the existing manual "Constants Info Verification" step.

### 3. Anchor point sanity before manual scene inspection

Current status: covered for the supported anchor families

What this means:

- zipped `.rca` anchor scenes are parsed
- classic SG anchor families such as sensor, tire-pressure, and scale anchors are supported
- evidence links point back to the source scene used by the run

This does not replace the manual Abstract Scene View check in Ramses Composer, but it reduces obvious naming and structure issues before a person spends time in the scene.

### 4. Project sanity and repository hygiene

Current status: covered for the current deterministic scope

What this means:

- SG-relative references are classified separately from real absolute-path risks
- cross-car contamination can be surfaced explicitly
- unreferenced Lua files are reported
- evidence includes exact source file and line information where available

This supports the existing repo-level sanity work and reduces black-box debugging.

### 5. Repo checker and `check_scenes.py`

Current status: partial

What this means:

- the mirrored repo already contains `check_scenes.py`
- the UI now exposes this stage as part of the real workflow
- `sg-preflight` does not yet execute `check_scenes.py` or other RaCo runtime checks directly

Current blocker:

- direct execution depends on a local `RaCoHeadless.exe` and a stable wrapper contract

### 6. BMW screenshot / export / interface smoke

Current status: blocked or adjacent, depending on machine access

What this means:

- this remains a real part of the SG QA workflow
- it is still maintained on the BMW / Team Wombat side
- `sg-preflight` does not execute those scripts today

Current blocker:

- without BMW Git access and a local `digital-3d-car-models` clone, this stage cannot be validated end-to-end from this machine

Even after access is available, the intended role of `sg-preflight` is still upstream:
catch deterministic issues before the heavier BMW smoke runs start.

### 7. Rack, carpaint tuning, and manual visual approval

Current status: manual and hardware-dependent

What this means:

- rack work, designer approval, and final visual judgement remain manual
- carpaint catalog sanity can be preflighted here
- final look approval on rack is still outside the current automation boundary

Current blocker:

- full end-to-end validation requires rack access, BMW-side setup, and usually `adb`

`sg-preflight` should reduce the number of avoidable issues that reach rack sessions.

### 8. Delivery handoff and traceable evidence

Current status: covered

What this means:

- reports and run records can be attached to triage and delivery discussions
- grouped findings help make ownership and next action more explicit
- the operator UI makes non-CLI inspection possible for teammates

This addresses a concrete pain from the retro: weak handoff and vague comments.

## What The Tool Should Improve

Based on the retro and SG QA notes, the tool should continue to improve these concrete problems:

- findings arrive too late
- ownership is unclear
- source-of-truth is hard to find
- integration feels like a black box
- evidence is weak or scattered
- repeated manual checks are not reusable

The product direction should stay anchored to those workflow failures, not generic feature growth.

## What Is Intentionally Still Out Of Scope

These are not claimed as solved by the current framework:

- Blender visual quality review
- final look comparison between Blender, RaCo, and Epic
- hardware-specific rack behavior
- BMW screenshot baseline management
- profiler / size-analysis execution
- Jira / PR automation against BMW-side systems

Some of these may become integration points later, but they should not be presented as already solved.

## Immediate Next Integrations

The highest-value next workflow integrations are:

1. wrap `check_scenes.py` behind a stable optional adapter once `RaCoHeadless.exe` handling is reliable
2. expose clearer handoff blocks for findings so teammates can copy evidence into tickets without rephrasing it
3. keep widening live-profile coverage beyond `G70`, `G65`, and `G45`
4. add BMW screenshot-smoke readiness and documentation without pretending local BMW access already exists
