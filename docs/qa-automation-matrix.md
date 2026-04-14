# Manual check -> signal -> automation matrix

## 1. Anchor Points Test RaCo
Manual review:
- check anchor point naming
- confirm name matches actual position
- inspect the anchor list under `Anchorpoints_BoundingBox`

Automation:
- naming validation
- duplicate detection
- required anchor detection
- metadata-vs-name position mismatch detection

## 2. Constants Info Verification
Manual review:
- compare tire diameter
- compare suspension information
- compare reflections
- compare trim and engine context

Automation:
- required key presence
- numeric type validation
- exact match validation
- tolerance validation

## 3. CarPaints Test RaCo
Manual review:
- test colors quickly with helper scripts
- inspect for artefacts later

Automation before visual review:
- schema validation
- unique ID / unique name checks
- numeric range checks
- semantic material warnings

## 4. Project / Toolchain sanity
Manual pain:
- wrong paths
- wrong RaCo version
- unused Lua
- glTF import instability / topology drift

Automation:
- OneDrive root/path detection
- suspicious absolute path detection
- version policy check
- unused Lua detection
- glTF drift / reorder warnings
