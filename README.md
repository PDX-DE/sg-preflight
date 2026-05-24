# SGFX QA Preflight - Local Alpha

This folder is a local-alpha QA workflow support bundle for the Seriengrafik 3D Car team. It helps operators inspect local state, prepare evidence, prioritize review work, and run read-only checks against operator-local SVN and BMW Git content.

It is not a production deployment, not a delivery package, and not a replacement for the Quality Hero manual review checklist. Evidence and status output are review support only. Manual RaCo, Blender, emulator, screenshot, and delivery review remain human-owned.

## What This Alpha Contains

- Grafiks operator console: a PySide6 desktop shell over the same Python data layer used by the clean dashboard.
- Screenshot review prioritization: P0-P3 suggested review order with reasons and signals. No screenshots are hidden or approved by the tool.
- Daily / morning QA digest: JSON, text, and Markdown summaries for evidence prepared, blockers, manual review pending, waiting-for-owner state, workflow status, and suggested review order.
- Manual review companion: Quality Hero review steps surfaced for operator notes and verdict entry. `recorded_by_tool` stays false.
- Delivery checklist workbook reader: read-only ingestion of operator-local delivery checklist workbook data.
- Export-size analysis reader: read-only ingestion of operator-local `Cars\size_analysis\<profile>_<date>.xlsx` workbook data.
- Clean and Grafiks evidence surfaces: delivery checklist, screenshot test state, daily digest, and manual review companion render from the same Python readers.
- Screenshot test state reader: read-only BMW / MINI screenshot baseline and test-config state from local BMW Git.
- BMW Git readiness reader: read-only per-profile state from the local `digital-3d-car-models` checkout.
- QA Hero readiness reader: read-only presence and count checks for documented Quality Hero assets such as LightFX, WelcomeFX, ShadesFX, CarPaint, AnchorPoints, Constants, and Perspectives.
- CLI uniformity: read/status commands support `--format text|json|markdown` and `--output-path` / `--out` where relevant, while preserving compatible `--json` and `--markdown` aliases.
- Operator-local template store: save, show, run, list, and delete local command templates without sharing them or posting them anywhere.
- Clean dashboard mode: `python -m sg_preflight dashboard run --ui-mode clean` launches the neutral NiceGUI work view from source. The packaged Windows executable embeds that NiceGUI Clean layout inside a desktop window by default and lets the operator toggle to Grafiks inside the same `.exe`. Both modes are local evidence views and do not change backend QA logic.
- OpenHTF station MVP: local station surface for delivery checklist, screenshot test state, daily digest, and manual review companion phases. Internal OpenHTF execution state is evidence status only; manual review remains required.
- Confirmation-gated Jira posting: optional dry-run-first Jira comment posting through the CLI. Nothing posts unless the operator explicitly reruns with `--confirm`.
- Operator docs: concise CLI and JSON workflow guides are included under `docs/`.

## Included Files

- `sg_preflight/` - Python backend, CLI, state readers, digest generation, review support.
- `sg_preflight/desktop/` - PySide6 Grafiks operator console.
- `sg_preflight/desktop_original_pyside6_backup/` - preserved copy of the original PySide6 shell source.
- `desktop_native/` - deprecated C++ operator shell reference source kept in Git history; excluded from the standard SVN-stage alpha bundle.
- `scripts/` - helper scripts for build, smoke, packaging, and verification.
- `tests/` - automated tests shipped with the curated bundle.
- `config/` - SGFX rule and profile configuration.
- `docs/` - curated team-facing docs only.
- `dist\sgfx-preflight\sgfx-preflight.exe` - optional packaged Windows executable when the bundle is prepared from a built onedir executable folder.
- SGFX icons and logos: `sgfx_icon.png`, `framework_sgfx_logo.png`, `logo_sgfx.png`, `exe_ico.png`, `exe_ico.ico`, and `debug_icon.ico` support the Windows executable, Clean dashboard, Grafiks shell, and web favicon.
- Optional shortcuts: `SGFX Preflight - Clean Mode.lnk` and `SGFX Preflight - Grafiks Mode.lnk` can be generated during bundle packaging when the executable exists.
- Root metadata: `pyproject.toml`, `LICENSE`, `NOTICE.md`, `SECURITY.md`, `CONTRIBUTING.md`, this `README.md`, and a clean local-alpha `CHANGELOG.md`.

Internal coordination notes, research notes, generated `out/` artifacts, build outputs, local-only notes, local-only evidence files, audio files, BMW source content, and unrelated R&D material are intentionally not included.

## First Run / Sanity Checks

Run these commands from the bundle root:

```powershell
python -m sg_preflight --help
python -m sg_preflight list-profiles --format json
python -m sg_preflight desktop-state overview --profile-id <profile> --json
python -m sg_preflight daily-digest latest --format markdown
```

The daily digest is safe on a fresh checkout. If no review package exists yet, it returns a clean no-package summary and exits successfully.

`review-board latest --json` requires a generated or copied review package. On a fresh checkout it can report that no matching review package was found; that is expected for the SGFX QA Status Board compatibility surface.

## Operator Dashboard Modes

Clean mode is the default local operator dashboard:

```powershell
python -m sg_preflight dashboard run --workspace C:\repositories\trunk --ui-mode clean
```

Grafiks mode opens the PySide6 desktop console over the same SGFX evidence readers:

```powershell
python -m sg_preflight dashboard run --workspace C:\repositories\trunk --ui-mode grafiks
```

The direct alias remains available:

```powershell
python -m sg_preflight desktop --workspace C:\repositories\trunk --profile <profile>
```

When `dist\sgfx-preflight\sgfx-preflight.exe` is included in a prepared bundle, the same surfaces are available from one executable:

```powershell
.\dist\sgfx-preflight\sgfx-preflight.exe
.\dist\sgfx-preflight\sgfx-preflight.exe dashboard run --workspace C:\repositories\trunk --ui-mode clean
.\dist\sgfx-preflight\sgfx-preflight.exe dashboard run --workspace C:\repositories\trunk --ui-mode grafiks
.\dist\sgfx-preflight\sgfx-preflight.exe list-profiles --format json
```

Double-clicking the executable without arguments opens the embedded NiceGUI Clean layout in a desktop window. In the packaged executable, Clean and Grafiks dashboard requests stay inside the `.exe`; `--no-native` is reserved for local server diagnostics. The packaged desktop path does not open an external browser. Other commands keep the same CLI behaviour as `python -m sg_preflight`.

The legacy `python -m sg_preflight ui` command and `/ui` routes are deprecated compatibility surfaces. Use the packaged `.exe` Clean window or `dashboard run --ui-mode clean` for operator work.

## Building the Windows Executable

The executable is built with PyInstaller through the packaging extra:

```powershell
python -m pip install -e .[packaging,desktop]
python scripts\build_sgfx_exe.py
```

The build writes the folder `dist\sgfx-preflight\` with `sgfx-preflight.exe` and its support files. This avoids one-file extraction delays on launch. The executable embeds the SGFX app icon and includes the SGFX logo assets used by Clean, Grafiks, and the web review board. Generated `dist\` and `build\` folders remain local build outputs and are not source files.

## Optional OpenHTF Station Smoke

The station command starts a local OpenHTF-backed SGFX surface and opens a browser unless `--no-browser` is set:

```powershell
python -m sg_preflight station run --profile <profile> --workspace C:\repositories\trunk --port 0 --history out\openhtf-history --no-browser --once
```

The first MVP station run covers four daily operator phases: delivery checklist, screenshot test state, daily digest, and manual review companion. Missing local inputs can appear as missing execution state in the station; that is not a QA verdict.

## Real SVN / BMW Git Read-Only Checks

These commands read operator-local content only. They do not modify SVN or BMW Git:

```powershell
python -m sg_preflight delivery-checklist read --profile <profile> --workspace C:\repositories\trunk --format markdown
python -m sg_preflight export-size-analysis read --profile <profile> --workspace C:\repositories\trunk --latest --format markdown
python -m sg_preflight screenshot-test-state read --profile <profile> --format json
python -m sg_preflight bmw-git-readiness read --profile <profile> --format json
python -m sg_preflight qa-hero-readiness read --profile <profile> --format json
```

If a local dependency is missing, the tool reports the missing state. It should not pretend a check succeeded.

BMW pipeline execution uses lane-specific local roots: `Digital-3D-Car-Repo` points at the master BMW Git checkout for IDC_EVO, and `Digital-3D-Car-Repo-IDC23` points at a separate `assets/idc23` worktree for IDC_23. The IDC_23 worktree must include `ci/scripts/test/main.py` and `cars/BMW/_Shared`. If the default Python launcher is not the BMW pipeline environment, set `SG_BMW_PYTHON_EXE` or register `bmw_pipeline_python` in Dependency Setup.

## Optional Jira REST

Jira REST access is opt-in and confirmation-gated. Credentials are operator-local and are loaded from `SGFX_OPERATOR_STATE_DIR\jira_pat.json`, `~/sgfx_operator_state/jira_pat.json`, or `.\operator_state\jira_pat.json` in that order. The JSON shape is:

```json
{
  "jira_url": "https://jira.cc.bmwgroup.net",
  "pat": "<token>"
}
```

Check the local credential and ticket visibility with a read-only request:

```powershell
python -m sg_preflight jira status --ticket IDCEVODEV-1009244 --format json
```

Mutating commands preview first and do not send a Jira write request unless the operator reruns the exact action with `--auto-confirm`:

```powershell
python -m sg_preflight jira post-comment --ticket IDCEVODEV-1009244 --body "Preview smoke." --format json
```

The legacy `jira post` dry-run command remains available for wording-file previews; new Jira write actions use `post-comment`, `update-issue`, and `attach-file`.

## Tests

From the bundle root:

```powershell
python -m unittest discover -s tests -v
```

The curated bundle test count can differ from the source alpha test count because internal guard-only tests are excluded from the team-facing bundle. The latest bundle verification ran successfully with 190 tests OK and 3 skipped; the source alpha verification for the same tip ran 196 tests OK and 3 skipped.

## Deprecated C++ Reference Build

The `desktop_native/` tree is deprecated as of 2026-05-19. Python dashboard modes are the operator UI going forward. The C++ source remains in Git as historical reference through alpha.

```powershell
cmake -S desktop_native -B build/native-downloads -A x64
cmake --build build/native-downloads --config Release
powershell -ExecutionPolicy Bypass -File scripts\verify_native_shell_bundle.ps1 -BuildDir build/native-downloads -LaunchObserveSeconds 2
```

Generated `build/` and `out/` folders are local outputs and should not be committed.

## External Dependencies

This alpha does not ship third-party source, BMW source, or BMW assets. Some checks depend on local operator setup:

- BMW Git repository `digital-3d-car-models`, used as a read-only external dependency.
- Seriengrafik SVN trunk, usually available under `C:\repositories\trunk` on an operator machine.
- Ramses Composer / Headless / Logic for RaCo-side workflows.
- Blender with the SG-Toolkit for Blender visual review.
- OpenHTF, installed from PyPI through the project dependencies, for the optional station surface.
- Python 3.11 or later.

Profile configs may reference operator-local paths under `C:\repositories\trunk`. Adjust local configuration if your checkout uses a different path.

## Non-Destructive Behaviour

SGFX QA Preflight is designed to stay out of the way of active work:

- It does not write to BMW Git.
- It does not commit to SVN.
- It does not post to Jira.
- It does not mark manual visual review as done.
- It does not auto-approve screenshots or delivery evidence.
- It writes generated outputs under local output paths, normally `out/`, which must stay uncommitted.

If a command appears to modify source content unexpectedly, stop and report it. That is not intended behaviour.

## AI use

SGFX QA Preflight is **default-off** for AI. When you run the tool, it does not call any language model, image model, or third-party AI service. No telemetry, no inference, no "AI-assisted suggestion" that originated from a model query.

Where the tool surfaces "suggested" evidence — for example the per-step evidence hints in the Manual Review Companion — the suggestion comes from a deterministic local filesystem probe (file exists, directory has these files, workbook has these rows). The operator records every verdict; the tool never pre-decides.

The tool was developed with AI-assisted pair-coding (operator + AI agents collaborating on code, tests, docs, review). The shipped tool does not embed any of those agents and does not phone home to any AI service.

If a future iteration adds opt-in AI-assisted features (suggestion ranking, automated screenshot triage, etc.), they will land behind an explicit operator toggle and an explicit Confluence-anchored consent flow — same standing pattern as Jira posting (`--confirm` flag required; default is dry-run / off).

Manual review remains required. Decision: not approval — evidence only.
BMW Git access is read-only. SGFX never modifies BMW source.
Activity log is local-only — never posted to Jira, SVN, or BMW Git.

## What Still Requires Manual Review

Every visual or behavioral verdict remains a human decision. The Quality Hero review still requires operator review in the relevant tools, including:

- Blender Visual Check.
- Constants Info Verification.
- Final Look Comparison between RaCo, Blender, and Epic.
- Functionality Test in RaCo.
- Anchor Points Test in RaCo.
- CarPaints Test in RaCo.
- Documentation review for README / changelog accuracy.

The tool can suggest a review order, collect evidence, and surface waiting states. The human reviewer decides what is actually OK.

## Feedback

This is a local alpha intended for teammate review and process alignment. Please report missing checks, noisy output, unclear wording, or any behavior that does not match the real Seriengrafik / BMW workflow.
