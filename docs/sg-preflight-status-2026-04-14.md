# SG Preflight Status - 2026-04-14

## What This Project Is

`sg-preflight` is an internal Python-first preflight and evidence framework for Seriengrafik / 3D Car QA.

The goal is not to build a flashy dashboard first.
The goal is to catch deterministic issues earlier, reduce obvious rack-session findings, and turn repeated manual checks into reusable evidence.

In practical terms, it is shaping into a CLI tool that:

- ingests SG-shaped source inputs
- normalizes them into a stable bundle contract
- runs deterministic validation packs
- writes JSON and HTML reports that QA, TA, and pipeline people can read

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
- `python -m sg_preflight demo-good`
- `python -m sg_preflight demo-broken`

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

These do not stop all progress, but they do block the next jump to truly SG-native validation:

- no real anchor hierarchy export containing `Anchorpoints_BoundingBox`
- no real `*_Position_Mapping.json`
- no real generated `*_Pivot_Master.json`
- no real `.pdx/raco/TestCarPaint/read_json_carpaints.py`
- no small current 3D Car project root from the actual SG/BMW side with representative `.rca`, Lua, and export outputs together

## Exact Files Still Needed From SG/BMW

When access improves, the highest-value fetches are:

1. one real anchor scene dump or hierarchy export containing `Anchorpoints_BoundingBox`
2. one real `*_Position_Mapping.json`
3. one real generated `*_Pivot_Master.json`
4. one real exported constants JSON from the integrated/exported side
5. the real `.pdx/raco/TestCarPaint/read_json_carpaints.py`
6. one real carpaint payload consumed by that helper
7. one small real SG/BMW project root with `.rca`, `.lua`, and export references

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

`sg-preflight` is an internal CLI-first QA preflight layer for Seriengrafik 3D Car that turns scattered manual checks into repeatable validation and evidence before integration and rack review.
