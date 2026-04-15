# Teammate Pilot Playbook

## Purpose

This playbook is for validating `sg-preflight` with real SG teammates.

The goal is not to prove that the code runs.
The code already runs.
The goal is to verify that QA, TA, 3D, and integration teammates can:

- understand what the tool checked
- understand why a finding exists
- find the right source-of-truth quickly
- decide who should act on a finding
- use the evidence output in handoff or triage

## How The System Works

`sg-preflight` has one deterministic validation engine.

The flow is:

1. A canonical live profile such as `G70`, `G65`, or `G45` resolves the real SG project root and config.
2. The materialization layer auto-discovers live SG inputs such as:
   - anchor `.rca`
   - `Pivot_Master.json`
   - `Module_constants_*.lua`
   - `CarPaint.json`
3. Those sources are normalized into the bundle contract:
   - `scene_hierarchy.json`
   - `constants_expected.json`
   - `constants_exported.json`
   - `carpaints.json`
   - `project_manifest.json`
4. Validators run only against that normalized bundle:
   - `anchors`
   - `constants`
   - `carpaints`
   - `project_sanity`
5. Reports are written as:
   - JSON
   - HTML
   - Markdown
6. The operator UI uses the same shared Python services and shows:
   - live profiles
   - one-click QA actions
   - resolved inputs
   - grouped findings
   - evidence drilldown
   - persistent run history

The UI is not a second engine.
It is a local front-end over the same run/materialize/report path.

It is also not the whole SG QA workflow.
It is the deterministic front end of that workflow.
BMW screenshot smoke, rack validation, and final visual approval remain adjacent or manual stages.

## What You Need

For the host machine:

- this repository checked out locally
- the in-repo SG mirror at `repositories\trunk`
- the machine-level reference checkout at `C:\repositories\trunk` for mirror audit
- Python with the project dependencies available
- PowerShell execution allowed for the local scripts

Recommended host checks:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_operator_ui.ps1 -CheckOnly
python -m unittest discover -s tests -v
powershell -ExecutionPolicy Bypass -File scripts\run_real_live_matrix_smoke.ps1
```

## What Teammates Need

For a hosted session on your machine:

- no local Python setup
- no local SG mirror
- only a browser if they are sitting at your machine
- or only screen share if you are driving

For a self-service session on their machine:

- this repository
- the mirrored SG content under `repositories\trunk`
- the reference checkout under `C:\repositories\trunk`
- Python plus the required UI packages:
  - `fastapi`
  - `jinja2`
  - `uvicorn`
  - `httpx`

They do not need Blender, Ramses Composer, or rack hardware to inspect current findings and evidence.
They also do not need BMW Git access if the goal is only to review the current preflight and evidence flow on your machine.

## Recommended Pilot Modes

### Mode 1: Host-Led Walkthrough

Best first step.

- You run the UI on your machine.
- The teammate focuses on whether the workflow is understandable.
- Use this for QA, TA, and integration stakeholders first.

### Mode 2: Pair Triage

Best for one real open finding.

- Start from a real live profile result.
- Open the evidence view.
- Ask the teammate to decide the likely owner and next action.

### Mode 3: Self-Service Trial

Best after the workflow is already stable.

- The teammate launches the UI on their own machine.
- They run one or more canonical profiles themselves.

## Session Flow

Use this sequence for a 20-30 minute pilot.

1. Start the UI:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_operator_ui.ps1 -OpenBrowser
```

2. Open Home and confirm:
   - live profiles are visible
   - prerequisites are mostly `available`
   - mirror-health information is visible

3. On Home, run one workspace action first if you want to show broader automation:
   - `Run Daily SG Check`
   - `Run IDCevo Repo Checkers`

4. Open one profile Run page and confirm the resolved inputs make sense.
   Start with:
   - `G70` for cross-car and unused-Lua signal
   - `G65` for real constants drift
   - `G45` for classic anchor-family coverage

5. Launch either:
   - `Run Standard Check` if you only want the deterministic preflight
   - `Run Recommended QA Stack For <car>` if you want the wider SG-side automation path from one button

6. On the Result page, ask the teammate:
   - Is the grouped summary understandable?
   - Is the "Do This Next" section enough to continue without you?
   - Can you tell what is important first?
   - Does the owner hint look credible?
   - Does the suggested action help or add noise?

7. Open one finding drilldown and one Evidence page link.

8. If you used a one-click QA action, open the action result page and ask:
   - Can you tell what this action ran without opening a terminal?
   - Is the blocker messaging honest enough when a step is not available on this machine?
   - Would you trust the action log and summary as a starting point?

9. Ask the teammate to answer:
   - What file is the source of truth?
   - Who should own this?
   - Would this help before rack or review?
   - What still feels like a black box?

10. Save the run and feedback.

11. Ask them to use the copy buttons:
   - `Copy Quick Update`
   - `Copy Full Handoff`
   - `Copy Finding`

The product target is that they should be able to hand the result off without rewriting it first.

## Where Evidence Lands

UI-triggered runs are written under:

```text
out/operator-ui/runs/<run-id>/
```

Each run contains:

- `run.json`
- `bundle\`
- `<profile>-report.json`
- `<profile>-report.html`
- `<profile>-report.md`

One-click QA actions are written under:

```text
out/operator-ui/actions/<action-run-id>/
```

Each action contains:

- `action.json`
- `action.log`
- `summary.json`
- `summary.md`
- generated action artifacts such as nested preflight reports

Matrix smoke output lands under:

```text
out/real-live-matrix/latest/
```

This is the best location for presentation-ready live evidence.

## Current Live Baseline

Verified on `2026-04-15` with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_real_live_matrix_smoke.ps1
```

Current results:

- `G70`: `1` error, `9` warnings
  - duplicate BMW carpaint ID
  - cross-car references into `G65`
  - several unused Lua files
- `G65`: `9` errors, `2` warnings
  - real `Pivot_Master` vs `Module_constants` drift
  - rim diameter deltas
  - tire width delta on `MPA`
  - duplicate BMW carpaint ID
- `G45`: `1` error, `2` warnings
  - classic anchor-family validation is clean
  - duplicate BMW carpaint ID
  - old `racoVersion` warning

Reference summary:

- [out/real-live-matrix/latest/SUMMARY.md](/c:/Users/DavidErikGarciaArena/Documents/GitHub/sg-preflight/out/real-live-matrix/latest/SUMMARY.md)

## Workflow Boundary To Explain In The Session

Say this plainly during the session:

- `sg-preflight` is meant to reduce what reaches rack, screenshot smoke, and delivery review
- it does not replace Blender visual review
- it does not replace rack approval
- it does not replace BMW-maintained screenshot smoke
- if BMW access is missing locally, that is a real blocker, not a tool omission to hide

## What Good Feedback Looks Like

Useful pilot feedback is concrete.

Ask teammates to point to one of these:

- a label they do not understand
- a finding that still does not reveal the correct owner
- a missing source link
- a confusing action hint
- a place where the copy-ready handoff text still needs manual rewriting
- a case where the grouped summary hides the real priority
- a place where they would still fall back to asking another person

Avoid generic feedback like "looks good" or "could be nicer."

## Suggested Questions

Use these in the session:

1. If you saw this before rack, would it save you time?
2. Can you tell what to open next without asking someone?
3. Is the distinction between summary, result, and evidence clear?
4. Which finding feels most trustworthy?
5. Which finding still needs manual interpretation?
6. What would stop you from using this without me present?

## Next Steps After The Pilot

After 3-5 sessions, group the feedback into:

- wording fixes
- missing evidence links
- wrong owner/action hints
- missing profiles or packs
- workflow friction

Do not start with a desktop wrapper unless the team explicitly says browser-plus-localhost is blocking adoption.
