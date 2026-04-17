# SG Preflight Status - 2026-04-14

## Update - 2026-04-17

Current local status on `feature/live-sg-matrix-and-anchor-groups`:

- the AssetRipper export at `C:\Users\DavidErikGarciaArena\Downloads\AssetRipper_export_20260417_024445\ExportedProject` has now been validated as a real Unity project layout with `Assets`, `Packages`, and `ProjectSettings`
- the recovered export still points to `Unity 2019.2.21f1` via `ProjectSettings\ProjectVersion.txt`
- the export includes recovered gameplay/runtime C# source under `Assets\Scripts\Assembly-CSharp`, with `79` `.cs` files currently visible on disk
- representative recovered files include `GameManager.cs`, `PlayerBase.cs`, `AudioManager.cs`, `CameraEffects.cs`, and `DayNightCycle.cs`
- the exact legacy Unity editor `2019.2.21f1` is now installed locally under `C:\Users\DavidErikGarciaArena\AppData\Local\UnityEditors\2019.2.21f1`
- an actual editor open attempt against the exported project was executed on this machine
- the remaining blocker is no longer "we have not tried it"; the editor exits before project import because Unity licensing is not activated locally, with the logged failure `Unity has not been activated with a valid License`
- SG-side impact: the export/source-code recovery is confirmed, but a fully successful "opened in Unity here" claim still depends on a valid local Unity license/sign-in

## Update - 2026-04-16

Current local status on `feature/live-sg-matrix-and-anchor-groups`:

- the canonical live acceptance path still centers on `G70`, `G65`, and `G45`, but the live registry is now widened across additional real BMW slices such as `G50`, `G78`, `NA5`, `F70`, `G68`, and `U10`
- the full `python -m unittest discover -s tests -v` run now completes again on this machine instead of timing out in the acceptance path
- operator results now compare the current run against the previous completed run for the same profile
- long-running runs and actions now expose a live `NOW LOADING...` overlay with estimated progress, under-the-hood phase visibility, a coarse ETA, and clickable per-step drilldown with nested child progress where available
- result and evidence views now expose evidence-completeness scoring, richer Jira / QA Hero / pre-delivery exports, and a manual-review companion instead of only generic handoff text
- Home, Run, and Result now push more explicit "if you are unsure, do this" guidance so teammate pilots have a simpler path through the UI

## What This Project Is

`sg-preflight` is an internal Python-first preflight and evidence framework for Seriengrafik / 3D Car QA.

The goal is not to build a flashy dashboard first.
The goal is to catch deterministic issues earlier, reduce obvious rack-session findings, and turn repeated manual checks into reusable evidence.

In practical terms, it is now a shared Python engine with two operator surfaces:

- ingests SG-shaped source inputs
- normalizes them into a stable bundle contract
- runs deterministic validation packs
- writes JSON, HTML, and Markdown reports that QA, TA, and pipeline people can read
- serves a local operator UI for simple daily checks and file-backed proof

## What It Does Today

The repo is runnable today from the terminal.

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
- `python -m sg_preflight ui --reload`
- `python -m sg_preflight demo-good`
- `python -m sg_preflight demo-broken`

Current operator UI surfaces:

- Home
- Run
- Result
- Files And Proof

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

## Why It Matters

This project directly maps to the pain points raised in onboarding, retro material, and current SG/BMW workflow conversations:

- too many obvious findings appear too late
- repeated checks are still manual or fragmented
- source-of-truth is hard to locate
- integration feels like a black box
- evidence is weak or inconsistent

`sg-preflight` addresses that by creating one deterministic layer in front of manual review and integration.

## Most Useful Local Sources Found So Far

High-value local source buckets:

- `OneDrive_1_14-04-2026`
  - tool depot, PDX SG Toolkit, Blendifier, carpaint scale converter, Zohan trace editor
- `OneDrive_2_14-04-2026`
  - QA Doctor prototype, legacy Ramsifier/export code, `.rca` helper context
- `OneDrive_4_14-04-2026`
  - pivot generator scripts, `carmodel_data.json`, `resource_mappings.json`
- `OneDrive_5_14-04-2026`
  - best current `.rca` / `.lua` corpus for `project_sanity`
- `Markus_Delete`
  - real carpaint workbooks and overlapping dev surfaces
- `Introduction`
  - Ramses Composer docs and smaller reference corpora

Important note:

- the extracted folders are usable
- several top-level ZIPs are damaged or unreadable with native tooling on this machine
- the extracted folders should be treated as the reliable local source

## Current Blockers

These do not stop current progress, but they still block the next jump beyond the current widened BMW rollout:

- MINI live profile rollout
- optional direct RaCo-runtime checks such as `check_scenes.py`
- richer integration hooks beyond local preflight and evidence capture

## Exact Files Still Needed From SG/BMW

When access improves further, the highest-value next fetches are:

1. additional live SG/BMW project roots beyond the current three-car baseline
2. representative MINI-side live slices to widen coverage beyond BMW
3. practical RaCo-runtime entry points that can be called non-interactively from the local workflow

## Current Strategic Position

The project is currently strongest in two areas:

- `project_sanity`
  - because we already have real-ish corpora to scan
- `carpaints`
  - because we already have workbook and legacy JSON sources to normalize

The next most important engineering slice is:

- `constants`
  - using the pivot-script ecosystem plus SG metadata sources we already have

After that:

- improve evidence-oriented reporting so large corpora produce summaries, not just warning floods
- return to `anchors` as soon as a genuine SG hierarchy sample arrives

## One-Sentence Description For Others

`sg-preflight` is an internal QA preflight and evidence layer for Seriengrafik 3D Car that turns scattered manual checks into repeatable validation, persistent run records, and operator-friendly evidence before integration and rack review.
