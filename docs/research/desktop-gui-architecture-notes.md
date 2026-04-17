# Desktop GUI Architecture Notes

This is a research note for the desktop operator shell track.

## Current product shape

`sg-preflight` is currently strongest as:

- Python core engine
- CLI over the same engine
- local web UI over the same engine

That is the shipping product surface today.
An experimental Desktop Operator Shell v0 now exists, but it is still intentionally thin and still depends on the same Python core plus the same persisted action/run records.
A second experimental track now also exists under `desktop_native/`: a native C++ + Dear ImGui shell scaffold that still talks to the same Python backend instead of cloning the engine.

## Future direction

The future richer operator shell should be:

```text
Python core engine
  -> CLI
  -> local web UI
  -> desktop GUI wrapper
```

The important part is unchanged:

- browser UI stays useful
- desktop stays a wrapper
- the Python engine remains the product core

## Rules

- Do not replace the Python core.
- Do not fork the validation logic into a second engine.
- The desktop GUI should call into the same core services/actions/evidence model.
- The browser UI stays useful even after a desktop shell exists.
- Native frontends should prefer a simple process/JSON contract first:
  - `launch-action`
  - `desktop-state profiles`
  - `desktop-state actions`
  - `desktop-state blockers`
  - `desktop-state manual`
  - `desktop-state recent-actions`
  - `desktop-state snapshot`
  - `desktop-state recent-runs`
  - `desktop-state run-snapshot`

## Why a desktop shell is justified later

A browser-only surface becomes limiting once the workflow leans harder on:

- Blender / RaCo / RaCoHeadless orchestration
- local file opening and subprocess-heavy flows
- screenshot and image-evidence capture
- filesystem-heavy checker execution
- Excel/report packaging
- BMW-side scripts once access exists

At that point, a desktop wrapper becomes the better operator shell.

## Current v0 scope

The current experimental shell is intentionally narrow:

- live profile list
- recommended SG action list per profile
- background action execution over the existing action system
- progress, log-tail, and blocker visibility from the same persisted records
- checker-evidence `Open first` triage
- local file open / reveal actions

The native shell scaffold extends that with:

- recent-action browsing
- recent-run browsing
- native `Open first` evidence triage
- linked run/report drilldown from the same persisted records
- source-of-truth file browsing beside generated run outputs
- broader copy-ready export buttons from the same shared evidence and report payloads
- a Windows-first Dear ImGui shell that can move closer to the eventual broader 3D-department operator surface
- repo-root and local-Python auto-discovery so the built exe can still call the Python backend when launched from `build\...\Release`
- runtime discovery of the local `UnleashedRecompResources` bundle so the native shell can use real DDS chrome instead of only procedural approximations
- borderless fullscreen startup by default plus a calmer installer-style screen flow, so the native shell behaves more like a dedicated operator surface than a debug dashboard
- local WAV-based UI cues plus an optional looping installer-music toggle, both fed from the same local Unleashed resource bundle when it exists

What it still does not try to do:

- replace the browser UI
- replace report generation or handoff generation
- automate BMW-only stages that are still blocked here
- consume Unleashed's prebuilt font-atlas snapshot directly; the current native shell keeps direct OTF font loading for now because the upstream atlas is generated through a custom snapshot path and version-coupled ImGui data layout

## What should not change

- one validation core
- one action system
- one evidence model
- one result / handoff flow
- one source-of-truth story around mirrored SG checkers and external BMW blockers
