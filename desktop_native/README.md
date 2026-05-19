# Native Operator Shell

> Deprecated 2026-05-19. Python desktop shell at `sg_preflight/desktop/` is the operator UI going forward. This directory is kept as historical reference through alpha.

This is the native local operator shell track for `sg-preflight`.

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

- Dear ImGui + Win32 + DirectX 12 shell
- repo-root auto-discovery from the built executable path, so the native shell can launch `python -m sg_preflight` from `build\...\Release` without a manual workspace override
- SGFX QA Status Board entry for ticket/scope, smoke status, screenshot-battery counts, unresolved families, decisions needed, copy-ready updates, and artifact links
- live profile list
- action tabs
- recent action browsing
- recent run/result browsing
- action launch + polling
- top checker-evidence rendering
- linked run-report drilldown beside action state
- run outputs and source-of-truth file panels
- blocker/manual stage visibility
- explicit manual review support for RaCo and Blender
- local open / reveal actions
- broader copy/export surfaces for Jira, QA Hero, pre-delivery, delivery-doc, quick-update, and full handoff text
- Environment Doctor readiness page for backend, mirrored SG checker coverage, RaCo/Blender readiness, BMW blockers, and output write access
- bottom button-guide band
- work-focused startup by default, with background audio disabled

## Manual Review Boundary

The native shell can show readiness, open local paths, attach manual screenshot evidence, and copy manual review notes.

It does not run RaCo or Blender automatically, does not embed external applications, and does not turn manual review into an automated pass/fail claim.

## Build

Requirements:

- CMake 3.24+
- MSVC / Visual Studio C++ build tools
- Python available as `python` on PATH
  - optional but preferred: a local `.venv\Scripts\python.exe` or `venv\Scripts\python.exe` in the repo root, which the native shell auto-detects

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

Verify the default safe bundle:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify_native_shell_bundle.ps1
```

The CMake file fetches:

- Dear ImGui `v1.92.7-docking`
- `nlohmann/json` `v3.12.0`

## Notes

- This shell is Windows-first because the current operator environment is Windows.
- It is intentionally separate from the PySide shell and still consumes the same Python backend state.
- Package staging defaults to a private-alpha bundle: repo mirrors, generated evidence, optional reference resources, optional fonts, and optional audio are excluded unless explicitly requested.
- `scripts/package_native_shell_bundle.ps1` keeps the build pointer and writes a separate bundle pointer under `build/latest_native_shell_bundle_path.txt`.
- BMW stages remain blocker/readiness surfaces until BMW-side access and scripts exist locally.
