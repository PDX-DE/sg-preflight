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
