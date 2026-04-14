# Workspace audit - 2026-04-13

## What was actually present

- Python package: `sg_preflight/`
- Config: `config/sg_rules.json`
- Demo bundles: `demo/good`, `demo/broken`
- Reports already generated in `out/`
- Tests: `tests/test_cli.py`
- Supporting notes: `docs/qa-automation-matrix.md`, `docs/retro-derived-priorities.md`, `docs/pain-points-derived-from-retro.md`

## What worked immediately

- `python -m unittest discover -s tests -v`
- `python -m sg_preflight demo-good`
- `python -m sg_preflight demo-broken`
- `python -m sg_preflight run --bundle demo/good --config config/sg_rules.json --json-out out/manual-good.json --html-out out/manual-good.html`

## What was demo-only

- The existing validators consumed only the normalized bundle contract:
  - `scene_hierarchy.json`
  - `constants_expected.json`
  - `constants_exported.json`
  - `carpaints.json`
  - `project_manifest.json`

- There was no adapter layer for:
  - discovering a real SG repo checkout
  - scanning an SG project root into `project_manifest.json`
  - normalizing a representative anchor hierarchy dump
  - normalizing `Pivot_Master` or constants exports
  - integrating with `read_json_carpaints.py`

## Immediate repair decisions

- Keep validators unchanged and add adapters in front of them.
- Add a discovery command to locate SG-style repo roots and helper assets.
- Add a materialization command to produce normalized bundles from real or representative inputs.
- Add a living assumptions file so the "known unknowns" stay explicit.
