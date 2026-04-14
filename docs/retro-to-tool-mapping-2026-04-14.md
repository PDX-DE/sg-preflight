# Retro To Tool Mapping - 2026-04-14

This note maps the `3D Car Delivery Retro` pain points to the current `sg-preflight` capability and the next technical steps.

## Pain Point Coverage

### Avoidable Findings During Reviews

Current tool support:

- grouped validation findings across `anchors`, `constants`, `carpaints`, and `project_sanity`
- HTML summary for stakeholder review
- markdown QA handoff with grouped findings, sample locations, owner hints, and suggested actions

Impact:

- repeated deterministic issues are easier to catch before review
- the tool now produces evidence that can be pasted into chat, tickets, or review threads

### Missing QA From The Beginning

Current tool support:

- CLI-first preflight that can run before later integration or rack review
- smoke-test automation to show end-to-end usage
- demo and source-drop corpora that let the workflow be exercised before full access lands

Impact:

- the project is positioned as an earlier gate, not just a late diagnostic script

### Findings Lack Context / People Need To Reinvestigate Basics

Current tool support:

- `materialize --context NAME=VALUE`
- `project_sanity` validation for missing workflow context
- markdown handoff output carrying:
  - car model
  - trim line
  - delivery phase
  - review target
  - evidence source
  - project root / repo root

Impact:

- findings can now be handed off with better context instead of raw validator output only

### Workflow / Ownership Chaos

Current tool support:

- config-driven owner hints by pack and finding code
- config-driven suggested actions by pack and finding code
- grouped evidence that is easier to route to the likely owner

Impact:

- the tool now helps structure triage instead of only reporting faults

### Early Rack / Emulator Reviews Were Helpful

Current tool support:

- `project_sanity` and current-source runs already work on real-ish local corpora
- smoke flow demonstrates a pre-review check path that can be expanded toward rack/emulator readiness later

Impact:

- the tool is already aligned with "run earlier, not only at the end"

### Integration Testing Knowledge Spread Too Thin

Current tool support:

- repeatable CLI flow
- smoke-test automation
- markdown handoff output
- documentation and workflow scaffolding

Impact:

- reduces dependence on oral knowledge for the first wave of deterministic checks

## What Is Already Strong

- `project_sanity`
- report grouping and handoff output
- local source-drop ingestion for `carpaints`
- smoke-test automation and presentation-friendly outputs

## What Still Needs Real SG/BMW Inputs

- true `anchors` scene export support
- true `Pivot_Master` / constants generation inputs
- real `read_json_carpaints.py` ecosystem integration
- stronger rack/emulator/runtime integration once those surfaces are accessible

## Recommended Next Technical Slice

1. Build the `constants` adapter from the pivot-script ecosystem already present in the workspace.
2. Reduce `project_sanity` noise for known reference-corpus false positives.
3. Once access lands, swap source-drop references for real SG/BMW data without changing the validator/report core.
