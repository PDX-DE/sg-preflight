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

## Scope

Current native-shell milestone:

- Dear ImGui + Win32 + DirectX 11 shell
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
- bottom button-guide band

## Build

Requirements:

- CMake 3.24+
- MSVC / Visual Studio C++ build tools
- Python available as `python` on PATH

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
build\native\Release\sg_preflight_native_shell.exe --workspace-root C:\path\to\sg-preflight
```

The CMake file fetches:

- Dear ImGui `v1.92.7-docking`
- `nlohmann/json` `v3.12.0`

## Notes

- This shell is Windows-first because the current operator environment is Windows.
- It is intentionally separate from the PySide shell so the native track can move toward a closer Unleashed-style interaction feel without cloning the Python engine.
- BMW stages remain blocker/readiness surfaces until BMW-side access and scripts exist locally.
