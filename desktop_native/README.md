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

## Scope

Current native-shell milestone:

- Dear ImGui + Win32 + DirectX 11 shell
- live profile list
- action tabs
- recent action browsing
- action launch + polling
- top checker-evidence rendering
- blocker/manual stage visibility
- local open / reveal actions
- copy-ready Jira / QA Hero / handoff surfaces
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
- `nlohmann/json` `v3.9.1`

## Notes

- This shell is Windows-first because the current operator environment is Windows.
- It is intentionally separate from the PySide shell so the native track can move toward a closer Unleashed-style interaction feel without cloning the Python engine.
- BMW stages remain blocker/readiness surfaces until BMW-side access and scripts exist locally.
