# Assumptions and decisions

## 2026-04-13

- Keep the normalized bundle contract as the stable validator boundary.
  This lets adapters change as we learn more about SG/BMW source formats without rewriting the validation core each time.

- Python stays the primary implementation language.
  Lua, Kotlin, and C++ remain future integration options, not starting constraints.

- The current machine-visible workspace does not contain a live `C:\repos\Seriengrafik` checkout.
  I also did not find `read_json_carpaints.py` or `carmodel_data.json` under the local user profile during this audit.

- Because the live SG repo is not present yet, the first "real adapter" work is implemented as:
  - SG-style repo discovery
  - bundle materialization from SG-shaped inputs
  - project_sanity manifest generation from a real repo/project root when available
  - format-normalizing adapters for anchor hierarchy dumps, constants JSON, and carpaints JSON/helper scripts

- Unknown file formats must be treated honestly.
  If we only know the path family, the adapter should support discovery and explicit handoff rather than inventing a fake parser.

- Generated reports belong in `out/` and should stay untracked by default.

## Files still needed from SG/BMW side

- A representative export-scene hierarchy dump containing `Anchorpoints_BoundingBox`
- One real `Pivot_Master` JSON example
- One exported constants JSON example from the integrated side
- The actual `read_json_carpaints.py` plus one compatible carpaints JSON input
- One representative project root containing `.lua` references and any path-heavy `.rca` or manifest files

## 2026-04-14

- Earlier audit assumptions about missing SG helper assets are no longer valid.
  The mirrored SVN under `repositories/trunk` does contain:
  - `.pdx\raco\scripts\testing\read_json_carpaints.py`
  - `.pdx\python\carmodel_data.json`
  - `.pdx\python\resource_mappings.json`
  - `check_scenes.py`
  - `.pdx\raco\json\anchorpoints\anchorpoint_data*.json`

- The copied mirror under `repositories/trunk` is now the live SG source base for development.
  It is good enough to stop relying on OneDrive-only examples for the first real slice.

- The first end-to-end live validation target is `Cars_IDCevo/BMW/G70`.
  It currently gives us:
  - real bounding-box anchors in `RES_G70_AnchorPoints.rca`
  - real `G70_Pivot_Master.json`
  - real `Module_constants_G70.lua`
  - real BMW-wide `CarPaint.json`

- SG carpaint `StyleID` meaning is now treated as source-of-truth from the shared interfaces:
  - `0 = Uni/solid`
  - `1 = Metallic`
  - `2 = Frozen`

- SG `.rca` files store several path flavors that must not be confused with OS-absolute filesystem paths:
  - repo-relative references like `../../../G65/...`
  - project-relative references like `/logic/...` or `/_Common/...`
  These need dedicated classification in `project_sanity` instead of generic absolute-path warnings.

- The current live `G70` smoke baseline is useful even before rack/runtime integration:
  - one real duplicate carpaint ID in BMW `CarPaint.json`
  - real cross-car references to `G65`
  - a small set of genuinely unreferenced Lua files

- Remaining high-value gaps are now narrower:
  - extend the live rules beyond the first `G70` slice
  - support non-bounding-box anchor packs such as sensor / tire-pressure / scale anchors
  - optionally wrap RaCo runtime checks like `check_scenes.py` when a usable `RaCoHeadless.exe` is available

- The next serious live rollout after `G70` is now:
  - `G65` as the second IDCevo end-to-end car
  - `G45` as the first classic BMW anchor-family expansion target

- Multi-family anchors stay inside the existing `anchors` pack.
  The validator now supports multiple config-driven anchor rule groups instead of splitting sensor / tire-pressure / scale checks into separate packs.

- `G45` constants validation currently focuses on the non-noisy shared paths between `Pivot_Master` and `Module_constants`.
  This avoids flooding the report with trim-name normalization ambiguity while still keeping the live report useful.

- The current live three-car matrix is a meaningful baseline:
  - `G70` highlights cross-car references and one duplicate BMW carpaint ID
  - `G65` highlights real rim/tire-width drift between `Pivot_Master` and `Module_constants`
  - `G45` validates classic anchor families and still surfaces the shared duplicate BMW carpaint ID

- The v1 GUI direction is now fixed:
  - local web UI first
  - FastAPI + Jinja templates + vanilla JS
  - one shared Python service layer for CLI, smoke scripts, and UI
  - thin desktop wrapper only later if team adoption requires it

- Canonical live car definitions must live in Python, not PowerShell.
  `list-profiles` and `run-profile` are now the supported profile entry points for operators and automation.

- UI-triggered runs persist under `out/operator-ui/runs`.
  Cached fast and deep mirror-audit artifacts persist under `out/operator-ui/cache`.

- Mirror audit stays two-tier:
  - fast cached checks for configured live slices by default
  - manual deep full-trunk comparison only when an operator explicitly asks for it

## 2026-04-15

- `sg-preflight` is now explicitly positioned as the deterministic front end of the existing SG 3D Car QA workflow.
  It should improve that workflow, not pretend to replace Blender visual review, BMW screenshot smoke, rack validation, or designer approval.

- BMW-side access remains a real blocker for full workflow coverage on this machine.
  Until a local `digital-3d-car-models` clone and BMW-side access are available, screenshot smoke and parts of the rack-adjacent flow must stay marked as blocked or external.

- `check_scenes.py` and related repo-side helpers are part of the intended workflow alignment, but not yet part of the current execution path.
  The next wrapper target on the SG side is direct optional scene checking once `RaCoHeadless.exe` handling is reliable enough.
