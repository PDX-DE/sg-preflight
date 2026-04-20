# Native Operator Shell

This is the experimental native desktop shell track for `sg-preflight`.

It does not replace the Python core.
It calls the same action system and evidence model through the shared CLI/JSON contract:

- `python -m sg_preflight launch-action ...`
- `python -m sg_preflight desktop-state profiles ...`
- `python -m sg_preflight desktop-state actions ...`
- `python -m sg_preflight desktop-state blockers ...`
- `python -m sg_preflight desktop-state manual ...`
- `python -m sg_preflight desktop-state recent-actions ...`
- `python -m sg_preflight desktop-state snapshot ...`
- `python -m sg_preflight desktop-state recent-runs ...`
- `python -m sg_preflight desktop-state run-snapshot ...`
- `python -m sg_preflight desktop-state environment ...`

## Scope

Current native-shell milestone:

- Dear ImGui (Guillermo referencia) + Win32 + DirectX 12 shell
- repo-root auto-discovery from the built executable path, so the native shell can launch `python -m sg_preflight` from `build\...\Release` without a manual workspace override
- live profile list
- action tabs
- recent action browsing
- recent run/result browsing
- action launch + polling
- top checker-evidence rendering
- linked run-report drilldown beside action state
- run outputs and source-of-truth file panels
- blocker/manual stage visibility
- local open / reveal actions
- broader copy/export surfaces for Jira, QA Hero, pre-delivery, delivery-doc, quick-update, and full handoff text
- Environment Doctor readiness page for backend, mirrored SG checker coverage, RaCo/Blender readiness, BMW blockers, and output write access
- bottom button-guide band
- borderless fullscreen startup by default, so the shell reads like a dedicated operator surface instead of a floating tool window
- calmer installer-style wizard flow instead of one dense dashboard:
  - `INTRO`
  - `SELECT`
  - `REVIEW`
  - `RUN`
  - `EVIDENCE`
  - `FILES`
  - `ENV`
  - `STAGES`
- presentation:
  - the shell keeps the heavier Unleashed-inspired SGFX Project Quality-Hero chrome by default
  - readability tuning should happen inside that same presentation layer instead of splitting the product into separate work/cinematic modes
- translated Unleashed-style shell systems in native code instead of stock ImGui widgets:
  - animated scanline header bars
  - amber title + activity-square choreography
  - grid-framed dark panels
  - animated action-tab highlight motion
  - selection cards for profiles, recent runs, evidence, and artifacts
  - local cue hooks for cursor / confirm / error feedback
  - installer-style screen transitions and hero treatment
- runtime Unleashed resource discovery:
  - auto-detects a local `UnleashedRecompResources` / `UnleashedRecompResources-main` bundle when present beside the repo
  - loads the real `general_window.dds`, `select.dds`, `light.dds`, and `options_static*.dds` textures into the DX12 shell when those local reference assets are present
  - keeps direct OTF font loading temporarily instead of consuming `im_font_atlas.bin` because the upstream atlas is tied to the custom `ImFontAtlasSnapshot` path and exact ImGui snapshot format
  - loads local WAV cues and optional installer background music from that same bundle, with shell-side toggles under `STAGES`
  - intentionally does not render Sonic/cast character art in the operator shell; the native track now keeps the reference language abstract and workflow-first

## Build

Requirements:

- CMake 3.24+
- MSVC / Visual Studio C++ build tools
- Python available as `python` on PATH
  - optional but preferred: a local `.venv\Scripts\python.exe` or `venv\Scripts\python.exe` in the repo root, which the native shell now auto-detects

Configure:

```powershell
cmake -S desktop_native -B build/native -A x64
```

Build:

```powershell
cmake --build build/native --config Release
```

Run:

```powershell
build\native\Release\sg_preflight_native_shell.exe
```

Manual `--workspace-root` and `--python` overrides still work when needed.

Optional native-shell startup overrides:

```powershell
build\native\Release\sg_preflight_native_shell.exe --profile F70 --action repo_checker_profile__f70
```

The CMake file fetches:

- Dear ImGui `v1.92.7-docking`
- `nlohmann/json` `v3.12.0`

## Notes

- This shell is Windows-first because the current operator environment is Windows.
- It is intentionally separate from the PySide shell so the native track can move toward a closer Unleashed-style interaction feel without cloning the Python engine.
- Package staging now defaults to a safer private-alpha bundle: repo mirrors, generated evidence, reference DDS bundles, optional fonts, and music are excluded unless explicitly requested.
- the current runtime default is the heavier cinematic-style SGFX Project Quality-Hero presentation, with readability and spacing tuned inside that same shell instead of switching to a separate work mode.
- Local UnleashedRecomp resource folders should be treated as reference-only inputs unless there is a cleared internal redistribution path for those assets.
- BMW stages remain blocker/readiness surfaces until BMW-side access and scripts exist locally.
- The current font path intentionally prefers direct local OTF files when available, because the upstream `im_font_atlas.bin` is a prebuilt snapshot generated for Unleashed's custom font-loading path rather than a drop-in ImGui runtime asset here.
