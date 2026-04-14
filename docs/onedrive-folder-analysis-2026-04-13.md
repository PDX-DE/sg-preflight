# OneDrive folder analysis - 2026-04-13

Source analyzed: `OneDrive_1_13-04-2026/`

## High-level result

This archive is useful as a partial reference snapshot, but not as a direct replacement for a live SG repo checkout.

- Total files: `3878`
- Actual files present: `331`
- Placeholder / missing-file entries: `3547`

Most of the useful material is under `Additional 3D Assets/`.
Most of the SG-shaped clues are in missing-file placeholder logs under `___All_Errors.txt` and `__*`.

## What is actually present

### Real files by top-level area

- `Additional 3D Assets/`: `296` files
- `CAD Data/`: `33` files
- `Confluence Uploads/`: `1` file
- root: `250716NA5_Funktionsübersicht.xlsm`

### Real file types present

- `.png`: `132`
- `.psd`: `38`
- `.zip`: `31`
- `.mp4`: `27`
- `.dds`: `19`
- `.mov`: `14`
- `.txt`: `10`
- `.jpg`: `10`
- `.gltf`: `6`
- `.texturePath`: `4`
- `.tga`: `4`
- `.rgb`: `3`
- `.pptx`: `3`
- `.aep`: `3`
- plus a few singleton files such as `.csv`, `.pdf`, `.blend`, `.xlsm`

## Direct usefulness for sg-preflight

### 1. `project_sanity`

This is the pack that benefits the most from this archive.

Useful surviving inputs:
- [U25_BEV_SPEZ.fbx.texturePath](</c:/Users/DavidErikGarciaArena/Documents/GitHub/sg-preflight/OneDrive_1_13-04-2026/CAD Data/U25/20230320/Interieur/U25_BEV_SPEZ.fbx.texturePath>)
- [U25_BEV_SPEZ.fbx.texturePath](</c:/Users/DavidErikGarciaArena/Documents/GitHub/sg-preflight/OneDrive_1_13-04-2026/CAD Data/U25/20230222/BEV/U25_BEV/Interieur/U25_BEV_SPEZ.fbx.texturePath>)
- [U25_BEV_SPEZ.fbx.texturePath](</c:/Users/DavidErikGarciaArena/Documents/GitHub/sg-preflight/OneDrive_1_13-04-2026/CAD Data/U25/20221117/U25_BEV/Interieur/U25_BEV_SPEZ.fbx.texturePath>)
- [U11_INT_Serie.fbx.texturePath](</c:/Users/DavidErikGarciaArena/Documents/GitHub/sg-preflight/OneDrive_1_13-04-2026/CAD Data/U11/U11_ICE/Interieur/U11_INT_Serie.fbx.texturePath>)

Observed path signal:
- three `U25` texture-path files point to `P:\30_Querschnitt\34_Nutzererlebnismodelle_XR\01_Fahrzeugprojekte_(DTK)\LU_M\U25\15_SERIENGRAFIK\INTERIEUR`
- this is useful for path-risk / environment / absolute-reference heuristics

Useful real glTF inputs for generic topology checks:
- [AD_Santa_Simple_V3.gltf](</c:/Users/DavidErikGarciaArena/Documents/GitHub/sg-preflight/OneDrive_1_13-04-2026/Additional 3D Assets/Festival Mode/_source/AD_Santa_NoTexture_V3/AD_Santa_Simple_V3.gltf>)
- [AD_SantaClaus_20210727.gltf](</c:/Users/DavidErikGarciaArena/Documents/GitHub/sg-preflight/OneDrive_1_13-04-2026/Additional 3D Assets/Festival Mode/_source/AD_SantaClaus_V1/AD_SantaClaus_20210727.gltf>)
- [Christmas_Santa.gltf](</c:/Users/DavidErikGarciaArena/Documents/GitHub/sg-preflight/OneDrive_1_13-04-2026/Additional 3D Assets/Festival Mode/_source/AD_Christmas_Santa_Simplified_V2/Christmas_Santa.gltf>)
- [shadowplane.gltf](</c:/Users/DavidErikGarciaArena/Documents/GitHub/sg-preflight/OneDrive_1_13-04-2026/Additional 3D Assets/Festival Mode/export/meshes/shadowplane.gltf>)
- [santaA.gltf](</c:/Users/DavidErikGarciaArena/Documents/GitHub/sg-preflight/OneDrive_1_13-04-2026/Additional 3D Assets/Festival Mode/export/meshes/santaA.gltf>)
- [santaB.gltf](</c:/Users/DavidErikGarciaArena/Documents/GitHub/sg-preflight/OneDrive_1_13-04-2026/Additional 3D Assets/Festival Mode/export/meshes/santaB.gltf>)

These are not 3D Car SG files, but they are real glTFs and can help exercise generic glTF object-set / topology checks.

### 2. `anchors`

No direct anchor input survives in usable form.

Not found as real files:
- `Anchorpoints_BoundingBox`
- `APN_BoundingBox_*`
- real anchor JSON dumps

Important clue from placeholder logs:
- missing `Confluence Uploads/02_3D Car/02_3DCar - BMW/02_BMW Cars/F74/anchorpoint_data_F74.json`

This strongly suggests that anchor-related JSON exports did exist upstream and are worth fetching properly.

### 3. `constants`

No direct constants source survived in usable form.

Not found as real files:
- `Pivot_Master`
- `constants/scripts`
- exported constants JSON
- `carmodel_data.json`

The only nearby structured survivor is:
- [Öffnungswinkel_U10.csv](</c:/Users/DavidErikGarciaArena/Documents/GitHub/sg-preflight/OneDrive_1_13-04-2026/Confluence Uploads/02_3D Car/02_3DCar - BMW/02_BMW Cars/U10/Opening Angle/Öffnungswinkel_U10.csv>)

Its content is a single semicolon-separated line:
- `23;52;64;67;72`

That may be useful later as a car-specific engineering reference, but it is not enough to drive the current `constants` pack.

### 4. `carpaints`

This archive is useful for carpaint references, but not for direct carpaint validation yet.

Not found as real files:
- `read_json_carpaints.py`
- carpaint JSON payloads
- material/config schemas used by the current pack

Important upstream clues from placeholder logs:
- missing AXF lacquer inputs under `Carpaints/_Input/20230817/Lacks/*.axf`
- missing many MINI Blender-based color adjustment scenes under `.../Carpaints/.../F55_BlenderShaders*.blend`
- missing `CarPaint_N.png` files in several CAD sourceimage folders

That makes the archive valuable for identifying source families, but not yet for direct ingestion by the current `carpaints` adapter.

## What is missing for the current framework

These were not found as real files:

- no real `.json` inputs relevant to the packs
- no real `.py` helper scripts
- no `.lua`
- no `.rca`
- no `read_json_carpaints.py`
- no `Pivot_Master`
- no `carmodel_data.json`
- no `Anchorpoints_BoundingBox` / `APN_BoundingBox_*`

## Best clues hidden in placeholder logs

The placeholder logs are the most valuable part of this archive for source discovery.

They show evidence of upstream files such as:

- `F74/anchorpoint_data_F74.json`
- `BMW_F70_SensorPositions.blend`
- `BMW_F70_SensorPositions.xlsx`
- `BMW_F74_SensorPositions.blend`
- `BMW_F74_SensorPositions.xlsx`
- `BMW_G45_SensorPositions.blend`
- `BMW_G45_SensorPositions.xlsx`
- `BMW_U10_SensorPositions.blend`
- `BMW_U10_SensorPositions.xlsx`
- `U10_SensorPositions.png`
- many MINI `F55_BlenderShaders_*.blend` carpaint files
- AXF lacquer inputs for carpaint references

This means the archive is still strategically useful, even when the actual files are missing.

## Recommendation

Treat this folder as:

- useful for reference mining
- useful for identifying the next exact fetch targets
- mildly useful for `project_sanity` heuristics and generic glTF tests
- not sufficient yet for direct real-data implementation of `anchors`, `constants`, or `carpaints`

## Best next fetches from SG/BMW side

If we want the next real adapter pass, the best files to fetch are:

1. one real `anchorpoint_data_*.json` file
2. one real `BMW_*_SensorPositions.blend` plus companion `.xlsx` if available
3. one real `Pivot_Master*.json`
4. one real exported constants JSON
5. the actual `read_json_carpaints.py`
6. one real carpaint JSON or other structured carpaint payload used with that helper
7. one small real SG project root containing `.lua` and `.rca` references

## Bottom line

This archive is worth keeping.

It does not unblock full real-input integration by itself, but it gives us:

- concrete filenames to ask SG/BMW for
- evidence that anchor/carpaint/sensor-position artifacts exist upstream
- a few real structured files we can use for generic path and glTF sanity work
