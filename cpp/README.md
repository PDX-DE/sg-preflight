# SGFX Cine C++ Track

This tree is the dev-side C++ cinematic walking skeleton. It is deliberately separate from `sg_preflight/`; the shipped Python tool remains the daily-driver and is treated as a read-only contract surface for this track.

## C-1 Ramses Link Probe

Current buildable Ramses target: `28.16.0`.

Reasoning:

- Project requirement: Ramses 28.x for RaCo 2.x exports.
- BMW/RaCo evidence pins the production G65 export to RaCo `2.9.0`, Ramses `28.15.1`, FeatureLevel `2`.
- David supplied the internal `ramses-logic-sdk` release `17.17.2`; its `ramses/` engine builds as Ramses `28.16.0`.
- C-3 uses the file metadata API to instantiate the framework at the export's exact feature level, then loads the real 28.15.1 scene on the 28.16.0 SDK.

The original public-source C-1 proof remains reproducible with Ramses `28.2.0`:

```powershell
.\cpp\scripts\run_c1_ramses_link_probe.ps1
```

The current 28.16.0 SDK install used by C-3 is `C:\ramses-28.16.0-install`.

Build Ramses from source first:

```powershell
git clone --recurse-submodules https://github.com/bmwcarit/ramses C:\tmp\ramses-28.2.0
git -C C:\tmp\ramses-28.2.0 checkout 28.2.0
cmake -S C:\tmp\ramses-28.2.0 -B C:\tmp\ramses-28.2.0-build -G "Visual Studio 17 2022" -A x64 `
  -DCMAKE_INSTALL_PREFIX=C:\tmp\ramses-28.2.0-install `
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 `
  -Dramses-sdk_BUILD_FULL_SHARED_LIB=ON `
  -Dramses-sdk_ENABLE_WINDOW_TYPE_WINDOWS=ON `
  -Dramses-sdk_WARNINGS_AS_ERRORS=OFF `
  -Dramses-sdk_BUILD_TESTS=OFF `
  -Dramses-sdk_BUILD_EXAMPLES=OFF
cmake --build C:\tmp\ramses-28.2.0-build --config Release --parallel
cmake --install C:\tmp\ramses-28.2.0-build --config Release
```

Configure and run the link probe:

```powershell
Push-Location cpp
cmake --preset vs2022-ramses-link `
  -DCMAKE_PREFIX_PATH=C:\tmp\ramses-28.2.0-install `
  -Dramses-shared-lib_DIR=C:\tmp\ramses-28.2.0-install\lib\ramses-shared-lib-28.2\cmake
cmake --build --preset vs2022-ramses-link-release
ctest --preset vs2022-ramses-link-release
Pop-Location
.\cpp\build\vs2022-ramses-link\Release\sgfx_cine_ramses_link_probe.exe
```

Expected output contains the configured Ramses version and:

```text
Ramses linked OK
```

## C-2 SDL3 Ramses HWND Embed

C-2 creates an SDL3-owned Win32 window, passes its HWND to Ramses with `DisplayConfig::setWindowsWindowHandle`, drives Ramses with `doOneLoop()`, and pumps both event systems (`SDL_PollEvent` for the host window plus Ramses renderer/scene-control dispatch).

To run the C-2 build/embed/evidence flow:

```powershell
.\cpp\scripts\run_c2_sdl_ramses_embed.ps1
```

Manual configure/build uses the same preset and Ramses install:

```powershell
Push-Location cpp
cmake --preset vs2022-ramses-link `
  -DCMAKE_PREFIX_PATH=C:\tmp\ramses-28.2.0-install `
  -Dramses-shared-lib_DIR=C:\tmp\ramses-28.2.0-install\lib\ramses-shared-lib-28.2\cmake
cmake --build --preset vs2022-ramses-link-release
Pop-Location
.\cpp\build\vs2022-ramses-link\Release\sgfx_cine_sdl_ramses_embed.exe --frames 180 --readback
```

Expected output contains:

```text
Ramses displayCreated result: Ok
Ramses scene state: Rendered
C-2 readPixels bright pixels: <nonzero>
C-2 SDL/Ramses HWND embed OK
```

## C-4 G65 Profile Overlay

C-4 keeps `sg_preflight/` read-only. The runner imports `sg_preflight.profiles` with Python bytecode disabled, reads the real `G65` `RunProfile`, writes evidence under `out/cpp/`, and passes the profile id to the SDL/Ramses app. The app renders that id as procedural block text next to the test triangle.

```powershell
.\cpp\scripts\run_c4_g65_profile_overlay.ps1
```

Expected output contains:

```text
C-4 sg_preflight profile id: G65
Ramses scene state: Rendered
C-4 readPixels bright pixels: <nonzero>
C-4 SDL/Ramses HWND embed OK
```

## C-3 Real G65 Ramses Scene

C-3 loads the real production G65 export from `C:\3D Car git\digital-3d-car-models\cars\BMW\G65_EVO\export\exported.ramses`, reads its metadata (`RamsesVersion 28.15.1`, exporter `2.9.0`, FeatureLevel `2`), creates the framework at that exact feature level, and renders into the SDL HWND using the 28.16.0 SDK.

```powershell
.\cpp\scripts\run_c3_g65_real_scene.ps1
```

Expected output contains:

```text
C-3 linked Ramses version: 28.16.0
C-3 scene metadata Ramses version: 28.15.1
C-3 scene metadata feature level: 2
Ramses scene state: Rendered
C-3 readPixels bright pixels: <nonzero>
C-3 real Ramses scene load/render OK
```

## Real Viewer Profile Run

The real-viewer runner keeps `sg_preflight/` read-only, resolves a profile id to an available BMW `exported.ramses`, builds against Ramses `28.16.0`, and renders the loaded scene through its authored Ramses pass graph. It does not create a presentation camera, create a presentation render pass, or retarget export render targets. The app sizes the SDL window from the scene's authored framebuffer render pass, maps the scene to the display framebuffer, ticks loaded `LogicEngine` objects every frame, and lets the export's 21-pass compositor present itself.

```powershell
.\cpp\scripts\run_real_viewer_profile.ps1 -ProfileId G65
```

Useful parameters:

```powershell
.\cpp\scripts\run_real_viewer_profile.ps1 -ProfileId G70 -Frames 180
.\cpp\scripts\run_real_viewer_profile.ps1 -ProfileId G65 -SceneFile "C:\3D Car git\digital-3d-car-models\cars\BMW\G65_EVO\export\exported.ramses"
.\cpp\scripts\run_real_viewer_profile.ps1 -ProfileId G65 -PerspectiveSet CID180_LHD -PerspectiveId CID_CARHUB_ALL_GOOD
.\cpp\scripts\run_real_viewer_profile.ps1 -ProfileId G65 -PerspectiveSet CID180_LHD -PerspectiveId CID_CARHUB_ALL_GOOD -Orbit
```

Leave `-AutoFrame`, `-Orbit`, and `-PerspectiveSet` off for the verified ramses-viewer style authored presentation. QA perspective selection resolves production `perspectives_*.json` files beside the selected car export, applies the selected view through the exported `Interface_CameraCrane` logic input, and keeps the authored compositor/pass graph intact. Free orbit is layered on the same logic input by adjusting yaw; direct camera mutation remains only a fallback if a car export has no camera-crane interface. `-ViewPreset` accepts `three-quarter`, `front`, `rear`, `left`, or `right` for that fallback path.

Expected output contains:

```text
Real viewer profile id: G65
Real viewer presentation mode: authored-passes
Real viewer logic engines/logic objects: <nonzero>/<nonzero>
Real viewer final framebuffer pass/camera/order/viewport: <pass>/<camera>/<order>/<width>x<height>
Real viewer authored view-control cameras: <camera>[+<camera>...]
Ramses scene state: Rendered
C-3 readPixels bright pixels: <nonzero>
C-3 real Ramses scene load/render OK
```

## Cinematic Shell Intro Slice

The cinematic shell slice adds an SDL3 + RmlUi app around the accepted viewer core. It renders the clean-room flow beat from `out/agent-control/CINEMATIC_BEHAVIOR_SPEC.md`: branded splash (`0.3s` fade in, `1.2s` hold, `0.3s` fade out) into hero title (`0.5s` flourish in, `1.6s` hold, `0.4s` out), using the measured house ease-out. Any key or mouse click during splash/title skips to the menu, where the 3D Car viewer is represented as the ready hub-zone target.

The current look pass follows `out/agent-control/CINEMATIC_LOOK_SPEC.md`: RmlUi is built with the FreeType font engine, Fredoka and Inter OFL fonts are loaded from `cpp/assets/fonts`, and David's own SGFX brand assets are loaded from `cpp/assets/brand`. The RmlUi image loader is still clean-room guarded: it refuses every texture except the allowlisted `logo_sgfx.png`, `framework_sgfx_logo.png`, `debug_icon.png`, and `sgfx_icon.png`.

The shell now uses RmlUi's GL3 renderer on an SDL3 OpenGL window. The Adventure Dawn sky is a native RmlUi linear-gradient decorator, and glow accents use GL3-backed box-shadow plus FreeType font effects. The custom SDL_Renderer gradient path is no longer the active renderer path.

The S3 menu slice is animated and navigable: items reveal over `0.25s` each with a `70ms` stagger, pointer hover/click and Up/Down + Enter/Space drive focus/activation, and the selected item uses a short pulse/spring feedback. The evidence runner captures a dedicated `menu-juice-readback.bmp` with the scripted pulse on `Start a QA pass`.

The fly-into-zone slice expands the 3D Car viewer card into a dedicated Ramses viewer-zone screen in `0.70s` and supports a `0.50s` back-out path in interactive mode. The asset swap point stays path-based: the shell reads its skin from the supplied asset root and still only loads the David-brand allowlist.

Double-click this to try the shell interactively:

```powershell
.\cpp\scripts\run_cinematic_shell_interactive.bat
```

It builds the current cinematic shell target if needed, launches the splash -> hero -> menu flow with the copied brand assets and fonts, and keeps the window open until it is closed. Keyboard and mouse controls are live; no scripted skip, pulse, or auto-exit is used in the default run.

```powershell
.\cpp\scripts\run_cinematic_shell_intro.ps1
```

Expected output contains:

```text
SGFX cinematic shell RmlUi version: 6.2
SGFX cinematic shell RmlUi font engine: freetype
SGFX cinematic shell renderer backend: RmlUi GL3
SGFX cinematic shell GL: Loaded OpenGL 3.3.
SGFX cinematic shell brand allowlist: logo_sgfx.png, framework_sgfx_logo.png, debug_icon.png, sgfx_icon.png
SGFX cinematic shell renderer look: native GL3 Adventure Dawn gradients + box-shadow glow accents
SGFX cinematic shell menu animation: item reveal 0.25s, stagger 70ms, feedback 120ms
SGFX cinematic shell menu controls: pointer hover/click, Up/Down, Enter/Space
SGFX cinematic shell fly-into-zone: 0.70s in, 0.50s back, 3D Car viewer core destination
SGFX cinematic shell skip: any key/click during splash or hero -> menu
SGFX cinematic shell viewer zone: sgfx_cine_ramses_real_scene is preserved as the 3D Car core
SGFX cinematic shell demo menu pulse fired: Start a QA pass
SGFX cinematic shell demo viewer fly-in fired
SGFX cinematic shell fly-into-zone beat OK
SGFX cinematic shell readback bright pixels: <nonzero>
SGFX cinematic shell splash->hero beat OK
```
