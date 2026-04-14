# Source Drop Analysis - 2026-04-14

## Scope

Audited these local source drops on `2026-04-14`:

- `OneDrive_1_14-04-2026`
- `OneDrive_2_14-04-2026`
- `OneDrive_3_14-04-2026`
- `OneDrive_4_14-04-2026`
- `OneDrive_5_14-04-2026`
- `Markus_Delete`
- `Introduction`
- top-level archives including `Introduction.zip`, `OneDrive_2_14-04-2026.zip`, `OneDrive_3_14-04-2026.zip`, `OneDrive_4_14-04-2026.zip`, `OneDrive_5_14-04-2026.zip`

The point of this pass was not to treat the drops as source-of-truth, but to answer:

- what is actually useful for `sg-preflight`
- what is reference-only
- what gives us real SG-shaped adapter leads
- what should stay out of git

## Quick Triage

| Source | Files | Size | Value |
| --- | ---: | ---: | --- |
| `OneDrive_1_14-04-2026` | 971 | 6462.99 MB | Tool depot, Ramses Composer archives, logic viewer, carpaint samples |
| `OneDrive_2_14-04-2026` | 256 | 5948.75 MB | Markus workspace snapshot, QA Doctor prototype, legacy Ramsifier/export code |
| `OneDrive_3_14-04-2026` | 262 | 20479.73 MB | Raw Blender/FBX source assets for many car codes |
| `OneDrive_4_14-04-2026` | 568 | 4873.81 MB | Highest-value adapter/source-script drop |
| `OneDrive_5_14-04-2026` | 782 | 942.83 MB | Best real corpus for `.rca`/`.lua` project sanity work |
| `Markus_Delete` | 500 | 4955.40 MB | Overlaps `OneDrive_4`, plus real carpaint workbooks and export docs |
| `Introduction` | 649 | 4163.90 MB | Ramses Composer docs, onboarding/reference pack, sample exports |

## OneDrive_1 Deep Dive

`OneDrive_1_14-04-2026` is useful, but not in a single uniform way.

### `Toolkit`

Current contents:

- `Toolkit/configurator_vars.gif`
- `Toolkit/Feature Requests.loop`
- two screenshots from late 2025

Assessment:

- This folder is mostly reference clutter.
- It does not currently give us parser inputs or adapter-ready artifacts.
- Keep it as context only; it is not a priority source for `sg-preflight`.

### `Tools`

This is the valuable part of the drop.

Most relevant extracted or inspectable surfaces:

- `Tools/PDX_SG-Toolkit/PDX_SG_Toolkit/sanitychecker.py`
- `Tools/PDX_SG-Toolkit/PDX_SG_Toolkit/raco.py`
- `Tools/PDX_SG-Toolkit/PDX_SG_Toolkit/carselector.py`
- `Tools/PDX_Blendifier/PDX_Blendifier/blendifier.py`
- `Tools/Car_Paint_Scale_Converter/2023-06-19/255_Scale/CarPaint.json`
- `Tools/Car_Paint_Scale_Converter/2023-06-19/0TO1_Scale/CarPaint.json`
- `Tools/Car_Paint_Scale_Converter/2023-06-19/JsonParse.py`
- `Tools/Zohan_Traceeditor/Zohan.py`
- `Tools/Zohan_Traceeditor/README.md`
- `Tools/Ramses_Logic_Viewer/...`
- `Tools/Ramses_Scene_Viewer/...`
- `Tools/Ramses_Composer_Current/...`

Why it matters:

- `PDX_SG_Toolkit/sanitychecker.py` is the strongest "do not reinvent blindly" signal in this folder.
- It already checks Blender/resource integrity and explicitly validates transform metadata against mapping data and `Pivot_Master.json`.
- `PDX_SG_Toolkit/raco.py` confirms the ecosystem expectation around `RaCoHeadless.exe`.
- `PDX_Blendifier/blendifier.py` confirms that `_Pivot_Master.json` is consumed downstream, not just generated upstream.
- `Car_Paint_Scale_Converter` gives us a real legacy carpaint JSON shape plus a concrete 255-to-0..1 normalization script.
- `Zohan_Traceeditor` is not a preflight input today, but it is a credible future source for trace/evidence workflows around `.json` and `.rctrace` scene traces.
- Ramses viewer/composer folders are mostly tool/runtime baggage, but they are still useful for version/path discovery and future headless/export integration checks.

Practical conclusion:

- `OneDrive_1_14-04-2026/Tools` is useful for `project_sanity`, `carpaints`, and future trace/evidence work.
- `OneDrive_1_14-04-2026/Toolkit` is low value for the current roadmap.

## OneDrive_2 Deep Dive

`OneDrive_2_14-04-2026` turned out to be more useful than the first audit captured.

Top-level shape:

- `Workspace/Markus_Delete/development/...`
- `__Workspace/`
- `__SourceFiles_Error.txt`
- `___All_Errors.txt`

Most relevant findings:

- `Workspace/Markus_Delete/development/QA_Doctor/init.py`
- `Workspace/Markus_Delete/development/QA_Doctor/qt_des_ui.py`
- `Workspace/Markus_Delete/development/QA_Doctor/COMPILE/PDX_QA_Doctor/PDX_QA_Doctor.exe`
- `Workspace/Markus_Delete/development/_Ramses_test/readme.md`
- `Workspace/Markus_Delete/development/_legacy/PDX_Ramsifier_Blender3.1/exportGltf.py`
- `Workspace/Markus_Delete/development/_legacy/PDX_Ramsifier_Blender3.1/ramsifier.py`
- several additional `development/*` packages mirroring later `OneDrive_4` surfaces

Why it matters:

- `QA_Doctor` is a concrete prior attempt at deterministic QA orchestration.
- Its check list explicitly includes:
  - `lua`
  - `shader`
  - `tabbing`
  - `newline`
  - `binary`
  - `export`
  - `screenshots`
- That is highly aligned with the current `sg-preflight` direction, especially around repeatable checks and evidence-first automation.
- `_Ramses_test/readme.md` shows there was already a Python helper layer for `.rca` scene access, which is relevant for future RaCo/project adapters.
- The error logs show this drop is incomplete: several `SourceFiles` and additional workspace folders were not downloaded.

Practical conclusion:

- `OneDrive_2` is now part of the useful audit corpus.
- It is especially valuable as product-history and backlog evidence, because it proves people already wanted centralized QA checks for export, binaries, Lua, and screenshots.
- It is not a direct replacement for current SG source-of-truth files, but it strengthens the case for `sg-preflight` as the next iteration of that capability.

## Best Finds

These are the most actionable files discovered in this pass.

### Constants / Pivot-Master leads

- `OneDrive_4_14-04-2026/Script-Snippets/pivot_json.py`
- `OneDrive_4_14-04-2026/Script-Snippets/U10_pivots_json.py`
- `OneDrive_4_14-04-2026/Script-Snippets/F55_pivots_json.py`
- `OneDrive_4_14-04-2026/Script-Snippets/F65_pivots_json.py`
- `OneDrive_4_14-04-2026/Script-Snippets/F66_pivots_json.py`
- `OneDrive_4_14-04-2026/Script-Snippets/F70_pivots_json.py`
- `OneDrive_4_14-04-2026/Script-Snippets/G45_pivots_json.py`
- `OneDrive_4_14-04-2026/Script-Snippets/G68_pivots_json.py`
- `OneDrive_4_14-04-2026/Script-Snippets/J01_pivots_json.py`
- `OneDrive_4_14-04-2026/Script-Snippets/J05_pivots_json.py`
- `OneDrive_4_14-04-2026/Script-Snippets/NA5_pivots_json.py`
- `OneDrive_4_14-04-2026/Script-Snippets/U06_pivots_json.py`
- `OneDrive_4_14-04-2026/Script-Snippets/U11_pivots_json.py`
- `OneDrive_4_14-04-2026/Script-Snippets/U12_pivots_json.py`
- `OneDrive_4_14-04-2026/Script-Snippets/U25_pivots_json.py`

What they tell us:

- SG already had Blender-side scripts that generate `*_Pivot_Master.json`.
- The expected JSON shape is no longer hypothetical: `TRANSFORMS`, `SUSPENSION`, and `REFLECTION` are explicit.
- These scripts depend on `*_Position_Mapping.json`, which is still missing from the drops and remains a required upstream fetch.

### Carpaint leads

- `OneDrive_4_14-04-2026/Script-Snippets/carpaint_jsonifier.py`
- `Markus_Delete/Documents/Carpaints.xlsx`
- `Markus_Delete/Documents/Carpaints_edited.xlsx`
- `OneDrive_1_14-04-2026/Tools/Car_Paint_Scale_Converter/2023-06-19/0TO1_Scale/CarPaint.json`
- `OneDrive_1_14-04-2026/Tools/Car_Paint_Scale_Converter/2023-06-19/255_Scale/CarPaint.json`

What they tell us:

- We now have a real workbook-to-JSON conversion script.
- The workbook layout is concrete enough to support a future workbook adapter.
- BMW and MINI workbook sheets do not look identical, so the adapter should not assume one uniform schema.
- The scale-converter JSON samples are useful fixtures for value normalization and schema tests.

### Project / repo structure leads

- `OneDrive_4_14-04-2026/development/PDX_Structifier/carmodel_data.json`
- `OneDrive_4_14-04-2026/development/PDX_Structifier/resource_mappings.json`
- `OneDrive_1_14-04-2026/Tools/PDX_Ramsifier/PDX_Ramsifier/resource_list.json`
- `OneDrive_4_14-04-2026/development/_legacy/PDX_Ramsifier_Blender3.1/resource_list.json`

What they tell us:

- `carmodel_data.json` is real and contains model metadata for BMW and MINI codes such as `F74`, `G45`, `U10`, `U11`, `U25`.
- `resource_mappings.json` encodes real resource groups and transform names like `ChargingFlaps`, `Door_F`, `Tailgates`, `Taillights`, `Rims`, `LightFX`.
- These files are strong candidates for future config seeding and pack-specific expectations.

### Ramses / RaCo / headless leads

- `OneDrive_4_14-04-2026/Script-Snippets/read_raco_output.py`
- `OneDrive_1_14-04-2026/Tools/Ramses_Logic_Viewer/currentExport/G05_main.lua`
- `OneDrive_1_14-04-2026/Tools/Ramses_Logic_Viewer/viewer/ramses-logic-viewer-headless.exe`
- `OneDrive_1_14-04-2026/Tools/Ramses_Composer_Current/...` multiple archived versions
- `Introduction/Introduction/ramses-composer-docs-master/introduction/manual.md`

What they tell us:

- The current SG ecosystem already leans on `RaCoHeadless.exe` and scripted exports.
- This aligns directly with the preflight roadmap item for headless export checks.
- The Introduction pack is reference material, but it gives a solid baseline for `.rca`, Lua, and glTF assumptions.

### Real `.rca` / `.lua` corpus

- `OneDrive_5_14-04-2026/Debug/MiniKombi/...`
- `Introduction/Introduction/ramses-composer-docs-master/...`

What they tell us:

- `OneDrive_5` contains a large real project-like tree: `35` `.rca` files and `240` `.lua` files.
- `Introduction` contains smaller but cleaner reference projects with `.rca`, `.lua`, `.gltf`, and docs.
- These are immediately useful for stress-testing `project_sanity`, even if they are not 3D Car export bundles.

## Per-Pack Assessment

### `project_sanity`

Most useful sources:

- `OneDrive_5_14-04-2026/Debug/MiniKombi`
- `Introduction/Introduction/ramses-composer-docs-master`
- `OneDrive_1_14-04-2026/Tools/...` for tool/version discovery

Current state:

- This is the pack that benefits most right now from the new drops.
- `sg-preflight materialize` already works against both the Introduction docs tree and the MiniKombi corpus.
- `sg-preflight run --packs project_sanity` now runs on both corpora.

Observed results:

- `Introduction` manifest/run: `0` errors, `52` warnings after tightening the absolute-path extractor.
- `MiniKombi` manifest/run: `1` error, `194` warnings.
- The MiniKombi `onedrive_root` error is correct and desirable.
- Most MiniKombi warnings are unused-Lua findings, which make this corpus useful for tuning reference detection and allowlists.

### `anchors`

Most useful sources:

- `OneDrive_3_14-04-2026/Shared 3D Assets/Sensors.blend`
- `OneDrive_3_14-04-2026/SourceFiles/...` raw Blender scenes
- `OneDrive_5_14-04-2026/Debug/Seriengrafik_2025-7-28-0-14-58_1.csv`

Current state:

- No real `Anchorpoints_BoundingBox` dump was found.
- No real `APN_BoundingBox_*` naming corpus was found.
- No anchor JSON export or hierarchy dump was found.

Conclusion:

- We still need one real anchor hierarchy export from SG/BMW.
- The current drops only provide scene-source candidates and metadata hints, not a direct adapter input.

### `constants`

Most useful sources:

- all `*_pivots_json.py` scripts in `OneDrive_4_14-04-2026/Script-Snippets`
- `OneDrive_4_14-04-2026/development/PDX_Structifier/carmodel_data.json`
- `OneDrive_4_14-04-2026/development/PDX_Structifier/resource_mappings.json`

Current state:

- We now know the expected Blender-side generator pattern for Pivot Master data.
- We still do not have actual `*_Position_Mapping.json` inputs or produced `*_Pivot_Master.json` outputs.

Conclusion:

- Constants adapter direction is much clearer now.
- The next required fetch is not conceptual anymore: it is a concrete `*_Position_Mapping.json` plus one real exported constants JSON.

### `carpaints`

Most useful sources:

- `Markus_Delete/Documents/Carpaints.xlsx`
- `Markus_Delete/Documents/Carpaints_edited.xlsx`
- `OneDrive_4_14-04-2026/Script-Snippets/carpaint_jsonifier.py`
- `OneDrive_1_14-04-2026/Tools/Car_Paint_Scale_Converter/.../CarPaint.json`

Current state:

- This is now the strongest non-demo adapter lead after `project_sanity`.
- The workbook format is visible enough to support a workbook-to-normalized-JSON adapter later.
- We still do not have the SG-side `read_json_carpaints.py` mentioned in onboarding docs.

Conclusion:

- We should eventually add an optional workbook adapter.
- We still need the real helper from `.pdx/raco/TestCarPaint/read_json_carpaints.py` to avoid drifting from company-side behavior.

## ZIP Findings

Useful nested archives:

- `Markus_Delete/MediaPool-Team_Test-Export/J01_U10_Testexport_20231123.zip`
  - contains two real FBX exports:
  - `J01_Core_Structure_BEV_Essential.fbx`
  - `U10_Core_Structure_ICE_Basis.fbx`
- `OneDrive_4_14-04-2026/development/PDX_Structifier.zip`
  - mostly a compact duplicate of the extracted `PDX_Structifier` folder
- `Introduction/Introduction/ID8_Linux-forReference/Vehicles_I20/I20_TRIMA.zip`
  - old packaged asset bundle with `bitmaps`, `meshes`, `shaders`, `scene.pbx`, `scene.ptx`

Mostly reference or archive baggage:

- large Ramses Composer version archives under `OneDrive_1_14-04-2026/Tools/Ramses_Composer_Current`
- `Introduction/Introduction/References/_Input/20211118/3D_Car_Full-Set_03_22.zip`
  - mostly screenshot/reference output
- `Introduction/Introduction/References/_Input/20211201/3DCar_Zoom_Rotation.zip`
  - single MP4
- `OneDrive_5_14-04-2026/Debug/Flakes.zip`
  - screenshot sequence, not adapter input

Archive quality note:

- `OneDrive_5_14-04-2026.zip` is readable with native tooling and exposes the expected `MiniKombi` corpus.
- `Introduction.zip`, `OneDrive_3_14-04-2026.zip`, `OneDrive_4_14-04-2026.zip`, and `OneDrive_5_14-04-2026.zip` were all checked at least once.
- In the second pass, `Introduction.zip`, `OneDrive_2_14-04-2026.zip`, `OneDrive_3_14-04-2026.zip`, and `OneDrive_4_14-04-2026.zip` reported `Damaged Zip archive` through native `tar.exe`, so they should not be treated as reliable archive sources without re-download or external extraction.
- The extracted folders remain the authoritative local source for those drops.

## Meeting Screenshot Notes

The screenshots from `2026-04-14` are useful as backlog evidence, not as parser input.

Visible signals:

- Jira domain on BMW side: `jira.cc.bmwgroup.net`
- issue key shown: `IDCEVODEV-960073`
- ticket title shown: `QA-Hero Sprint CW16`
- description link shown: `Quality-Hero: How to review the 3D car`
- visible DoD items include:
  - `headless export check bmw`
  - `screenshot tests bmws`
  - `format checker svn`
  - `check changelogs cars bmw`
  - `check readme cars bmw`
  - `asset review in raco (bmws)`
  - `check readme/changelogs cars shared bmw`

Why this matters:

- It validates that the preflight direction is aligned with real department expectations.
- It strengthens the case for deterministic checks, headless export validation, evidence generation, and readme/changelog sanity checks.

## Repo Changes Triggered By This Audit

- `.gitignore` now excludes the bulky local source drops and their top-level archives.
- `project_sanity` path extraction was tightened so URLs and markdown links do not flood reports as fake absolute paths.
- A regression test was added for that extractor behavior.

## Recommended Next Fetches

Highest-value missing inputs after this audit:

1. one real `*_Position_Mapping.json`
2. one real generated `*_Pivot_Master.json`
3. one real anchor hierarchy dump containing `Anchorpoints_BoundingBox`
4. the real `.pdx/raco/TestCarPaint/read_json_carpaints.py`
5. one real carpaint payload consumed by that helper
6. one small SG/BMW project root with `.rca` and Lua references from the actual 3D Car side

## Bottom Line

This batch was worth it.

- `OneDrive_4` and `Markus_Delete` materially improved the roadmap for `constants` and `carpaints`.
- `OneDrive_5` materially improved real-corpus testing for `project_sanity`.
- `Introduction` materially improved reference coverage for Ramses Composer structure and headless workflows.
- `anchors` is still blocked on one genuine SG export/hierarchy sample.

## Current Runnable Bundle

We can already build a non-demo bundle from the currently available local drops:

```powershell
python -m sg_preflight materialize `
  --output-bundle out\current-source-bundle `
  --repo-root OneDrive_4_14-04-2026 `
  --project-root OneDrive_5_14-04-2026\Debug\MiniKombi `
  --carpaints-source Markus_Delete\Documents\Carpaints.xlsx

python -m sg_preflight run `
  --bundle out\current-source-bundle `
  --config config\sg_rules.json `
  --packs carpaints,project_sanity `
  --json-out out\current-source-bundle.json `
  --html-out out\current-source-bundle.html `
  --fail-on never
```

Observed result on `2026-04-14`:

- `carpaints`: `1` error
  - duplicate `id` `WC68` for `mineral_red`
- `project_sanity`: `1` error, `194` warnings
  - the single error is the expected `onedrive_root` finding against the MiniKombi project root

This is not the final SG path yet, but it is already a real-source, non-demo workflow.
