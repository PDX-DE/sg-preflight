## Internal Notice

`sg-preflight` is being developed as internal capability tooling for Paradox Cat GmbH Seriengrafik / 3D Car workflows.

See [LICENSE](LICENSE) for the governing internal proprietary license.

> [!WARNING]
> Mirrored SVN content, generated reports, screenshots, and workflow notes in this repo should be treated as internal company material by default.

- Treat repository contents, mirrored source data, screenshots, reports, and workflow notes as internal work material.
- Do not publish copied SVN content, BMW/SG assets, or project-specific outputs to public repositories.
- Keep generated evidence under `out/` and mirrored source trees such as `repositories/` untracked unless a deliberate internal release process says otherwise.
- When preparing internal milestones, prefer sanitized examples and avoid embedding confidential asset payloads directly into docs or issue discussions.
- Treat unrelated local reference/resource folders as local-only inputs unless a cleared internal distribution path exists for those assets.

## Third-Party Notice Stub

The native shell currently relies on the following third-party components. Keep this notice with any internal portable bundle or other packaged native-shell milestone.

| Component | Version | License | Upstream | Current use |
| --- | --- | --- | --- | --- |
| Dear ImGui | `v1.92.7-docking` | MIT | `https://github.com/ocornut/imgui` | Native shell UI runtime, Win32 backend, DX12 backend |
| nlohmann/json | `v3.12.0` | MIT | `https://github.com/nlohmann/json` | Backend bridge payload parsing and JSON transport |

## Grafiks UI assets

The native operator-shell Grafiks display mode (`--ui-mode grafiks`) carries UI chrome textures and audio cues adapted from the following open-source project. The clean display mode (`--ui-mode clean`, default) does not depend on these adapted assets.

| Destination file | Upstream project | Upstream license | Upstream URL | Source path within upstream tree |
| --- | --- | --- | --- | --- |
| `desktop_native/assets/images/common/raw/general_window.png` | sonic3air | GPL-3.0 | https://github.com/Eukaryot/sonic3air | `Oxygen/oxygenengine/data/images/messagewindow_frame.png` |
| `desktop_native/assets/images/common/raw/select.png` | sonic3air | GPL-3.0 | https://github.com/Eukaryot/sonic3air | `Oxygen/sonic3air/data/images/menu/achievements_frame.png` |
| `desktop_native/assets/images/common/raw/light.png` | sonic3air | GPL-3.0 | https://github.com/Eukaryot/sonic3air | `Oxygen/sonic3air/data/images/menu/mainmenu_bg_separator.png` |
| `desktop_native/assets/images/common/raw/options_static.png` | sonic3air | GPL-3.0 | https://github.com/Eukaryot/sonic3air | `Oxygen/sonic3air/data/images/menu/options_topbar_bg.png` |
| `desktop_native/assets/images/common/raw/options_static_flash.png` | sonic3air | GPL-3.0 | https://github.com/Eukaryot/sonic3air | `Oxygen/oxygenengine/data/sprites/input/touch_overlay_highlight.png` |
| `desktop_native/assets/sounds/ui_cursor.wav` | sonic3air (source-pick mapping pending) | GPL-3.0 | https://github.com/Eukaryot/sonic3air | Format-converted source mapping pending |
| `desktop_native/assets/sounds/ui_confirm.wav` | sonic3air (source-pick mapping pending) | GPL-3.0 | https://github.com/Eukaryot/sonic3air | Format-converted source mapping pending |
| `desktop_native/assets/sounds/ui_cancel.wav` | sonic3air (source-pick mapping pending) | GPL-3.0 | https://github.com/Eukaryot/sonic3air | Format-converted source mapping pending |
| `desktop_native/assets/sounds/ui_panel_open.wav` | sonic3air (source-pick mapping pending) | GPL-3.0 | https://github.com/Eukaryot/sonic3air | Format-converted source mapping pending |
| `desktop_native/assets/sounds/ui_panel_close.wav` | sonic3air (source-pick mapping pending) | GPL-3.0 | https://github.com/Eukaryot/sonic3air | Format-converted source mapping pending |
| `desktop_native/assets/sounds/ui_page.wav` | sonic3air (source-pick mapping pending) | GPL-3.0 | https://github.com/Eukaryot/sonic3air | Format-converted source mapping pending |

Adapted files use SGFX-neutral destination filenames. The upstream license text ships alongside the adapted assets at `desktop_native/assets/LICENSE-sonic3air`. Full upstream source remains publicly available at the URL above.

These adapted assets are treated as GPL-3.0-scoped assets. A formal codebase-wide license review for non-asset code is deferred and tracked separately.

## Grafiks-mode menu-architecture inspiration

The native shell menu architecture for SGFX QA Preflight (class hierarchy, action-handler patterns, menu state organization, tab strip, and scrollable rows layout convention) is inspired by the open-source [sonic3air project](https://github.com/Eukaryot/sonic3air) (GPL-3.0).

The current SGFX implementation under `desktop_native/src/sgfx_shell/` is original code. No sonic3air source files are imported or distributed in this codebase. The shell uses fresh Win32/GDI immediate-mode drawing and a lightweight presentation; it does not contain sonic3air's renderer, sprite system, transition pipeline, animation banks, custom-font system, or audio-event system.

Full GPL-3.0 attribution will apply if and when sonic3air rendering subsystems (sprite batching, transition pipeline, animation banks, custom-font rendering, audio cues) are extracted in a future Grafiks update. Until then, this acknowledgement of architectural inspiration is the complete attribution scope for menu architecture.

### Four-repurpose integration

| Repurpose | Implementation surface | What it changes |
| --- | --- | --- |
| Templates tab | `desktop_native/src/sgfx_shell/sgfx_settings_menu.cpp` | Action handlers call the existing `sg_preflight/template_store.py` API. Templates persist to `<workspace>/templates/<name>.json`. |
| Activity Log tab | `desktop_native/src/sgfx_shell/sgfx_digest_menu.cpp` | Adds Daily Digest, Readiness and Hygiene, and Activity Log views. The new operator-local JSONL file stays local and is never posted to Jira, SVN, or BMW Git. |
| Diagnostic Mode overlay | `desktop_native/src/sgfx_shell/sgfx_diagnostic_overlay.cpp` | Provides read-only environment health checks for local paths, runtime prerequisites, alpha Git tip, Confluence anchor status, and free disk space. |
| Theme and Accessibility tab | `desktop_native/src/sgfx_shell/sgfx_settings_menu.cpp` | Adds UI mode, font size, high-DPI scale, and contrast settings rows persisted through the local INI. |

### Operator-local data files introduced by this shell update

| File | Purpose | License scope |
| --- | --- | --- |
| `<workspace>/operator_state/activity_log.jsonl` | Append-only operator-action log written by SGFX CLI and native UI handlers. Vocabulary: `opened`, `ran`, `read`, `exported`, `refreshed`, `switched-profile`, `switched-mode`. Local-only and never posted. | Original SGFX data file. Not derived from sonic3air. |
| `sg_preflight/activity_log.py` | Append and read helpers for the activity log JSONL. | Original SGFX code. Not derived from sonic3air. |

### Future attribution

If a later Grafiks update extracts sonic3air rendering subsystems, this section will be updated with the specific upstream files, adapted subsystem table, and license implications for that future work.

## OpenHTF dependency

SGFX QA Preflight uses OpenHTF as the local station runtime for phase execution, station UI hosting, and run history. The dependency is installed from PyPI and is not vendored or modified in this repository.

| Component | Version | License | Upstream | Current use |
| --- | --- | --- | --- | --- |
| OpenHTF | `1.6.1` | Apache 2.0 | https://github.com/google/openhtf | Operator console hosting, phase execution, station UI, and run history |

OpenHTF attribution:

```text
Copyright 2014 Google Inc.

Licensed under the Apache License, Version 2.0.
You may obtain a copy of the License at https://www.apache.org/licenses/LICENSE-2.0
```

### Packaging Rules

- Keep `LICENSE` and this `NOTICE.md` in any internal native-shell bundle.
- Do not treat unrelated local reference/resource folders as redistributable bundle inputs by default.
- Do not bundle mirrored `repositories/` or generated `out/` evidence unless there is a deliberate internal reason and a conscious opt-in.
- Keep upstream license texts under `desktop_native/assets/LICENSE-*` alongside any adapted Grafiks UI assets they apply to; do not strip license texts from a packaged bundle.
- If OpenHTF is ever vendored or bundled directly, ship the matching Apache 2.0 license text alongside that component; the current alpha installs OpenHTF from PyPI instead.
- The clean display mode (`--ui-mode clean`, default) does not depend on the adapted Grafiks UI assets and remains usable without them.
- The Grafiks-mode binary at this snapshot is original SGFX code; it does not bundle sonic3air source files. The upstream license text at `desktop_native/assets/LICENSE-sonic3air` covers the adapted assets. A future Grafiks update may extract sonic3air rendering subsystems; if that happens, this notice will grow to full GPL-3.0 attribution and the license text will cover the additional adapted source.

This notice is intentionally lightweight until the final company-side repository policy is defined, but it is now explicit enough for internal alpha packaging.
