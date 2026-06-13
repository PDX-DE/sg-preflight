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

## Grafiks mode implementation

The native shell implementation under `desktop_native/src/sgfx_shell/` is original SGFX code. It no longer carries adapted third-party image or audio assets; Grafiks runtime packaging uses SGFX-owned resources plus third-party libraries listed in this notice.

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
| `<workspace>/operator_state/activity_log.jsonl` | Append-only operator-action log written by SGFX CLI and native UI handlers. Vocabulary: `opened`, `ran`, `read`, `exported`, `refreshed`, `switched-profile`, `switched-mode`. Local-only and never posted. | Original SGFX data file. |
| `sg_preflight/activity_log.py` | Append and read helpers for the activity log JSONL. | Original SGFX code. |

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

## NiceGUI dependency

SGFX QA Preflight uses [NiceGUI](https://github.com/zauberzeug/nicegui) (MIT License) as the primary operator-dashboard UI framework. The 4 SGFX evidence pages (Delivery Checklist, Screenshot Test State, Daily Digest, Manual Review Companion) render as NiceGUI pages over the existing `sg_preflight/` data layer, launched as a native desktop window via `ui.run(native=True)`.

| Component | Version | License | Upstream | Current use |
| --- | --- | --- | --- | --- |
| NiceGUI | `nicegui[native]==3.11.1` | MIT | `https://github.com/zauberzeug/nicegui` | Primary operator-dashboard hosting, 4 evidence-page rendering, and native desktop window support via `ui.run(native=True)`; the `[native]` extra installs `pywebview` for native-window support |

NiceGUI is installed via `pip install nicegui[native]==3.11.1` and pinned in `pyproject.toml`. The upstream source is not vendored, modified, or distributed by SGFX. MIT license terms apply to NiceGUI's portion of the runtime; SGFX-original code (`sg_preflight/` data layer, NiceGUI page wrappers under `sg_preflight/dashboard/`, dashboard launcher CLI) stays under the existing internal proprietary license unless and until a formal codebase-wide license review changes that.

NiceGUI attribution:

```text
MIT License

Copyright (c) 2021 Zauberzeug GmbH

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## PySide6 dependency

SGFX QA Preflight uses [PySide6](https://wiki.qt.io/Qt_for_Python) for the packaged Clean desktop host. PySide6 is the official Python binding for Qt 6, distributed by The Qt Company. The PySide6 host embeds the NiceGUI Clean dashboard through Qt WebEngine; Grafiks mode is the separate C++ cinematic shell, not the PySide6 console.

| Component | Version | License | Upstream | Current use |
| --- | --- | --- | --- | --- |
| PySide6 | `6.11.1` observed in the build venv; project constraint `>=6.7,<7` | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only, with commercial Qt licensing available | `https://wiki.qt.io/Qt_for_Python` | Packaged Clean desktop host and embedded Qt WebEngine window |

PySide6 is installed through the `desktop` optional dependency group in `pyproject.toml`. The upstream source is not modified by SGFX. LGPL/GPL/commercial license terms apply to PySide6's portion of the runtime; SGFX-original code (`sg_preflight/` data layer, Clean host wrapper under `sg_preflight/desktop/`, dashboard launcher CLI) stays under the existing internal proprietary license unless and until a formal codebase-wide license review changes that.

PySide6 attribution:

```text
PySide6 is a Python binding for the Qt 6 framework. The community edition is
available under LGPLv3/GPLv2/GPLv3 licensing, and commercial Qt licensing is
available from The Qt Company. Full upstream license information is available at:
https://doc.qt.io/qtforpython-6/commercial/index.html
https://wiki.qt.io/Qt_for_Python
```

### LGPL-3.0 packaging note

The source-install path keeps PySide6 as a separate pip dependency. The Windows executable build may package PySide6 runtime files for operator convenience. Before any broader bundle distribution, keep the applicable LGPL/GPL/commercial-license text and upstream source links with the bundle, and route PySide6 replacement/commercial-license questions through the internal license review path.

### Packaging Rules

- Keep `LICENSE` and this `NOTICE.md` in any internal native-shell bundle.
- Do not treat unrelated local reference/resource folders as redistributable bundle inputs by default.
- Do not bundle mirrored `repositories/` or generated `out/` evidence unless there is a deliberate internal reason and a conscious opt-in.
- If OpenHTF is ever vendored or bundled directly, ship the matching Apache 2.0 license text alongside that component; the current alpha installs OpenHTF from PyPI instead.
- NiceGUI is a runtime dependency installed via pip. MIT license terms apply to the NiceGUI portion of any packaged bundle. If a bundle vendors NiceGUI for offline operator machines, ship the MIT LICENSE text from the NiceGUI upstream alongside the bundled package.
- PySide6 is a runtime dependency installed via pip for source installs and may be included in the Windows executable bundle for operator convenience. LGPL/GPL/commercial Qt license terms apply to the PySide6 portion of any packaged bundle; if PySide6 runtime files are bundled, keep the applicable license text and upstream source links available with the bundle and route replacement/commercial-license questions through internal license review.
- Do not add third-party image, audio, font, or code payloads to Grafiks packaging without adding the applicable notice and license text.

This notice is intentionally lightweight until the final company-side repository policy is defined, but it is now explicit enough for internal alpha packaging.
