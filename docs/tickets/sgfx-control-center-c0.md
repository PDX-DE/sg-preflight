# SGFX QA Control Center C0

## Objective

Provide one profile-neutral QA workspace with a four-pack-only local action and seven truthful QA gates.

## Delivered

- `f38f0c7 fix(qt): require explicit profile selection` — starts without an invented profile and keeps an explicit valid operator choice canonical.
- `07ac1e9 feat(qa): add isolated local preflight action` — adds the exact selected-profile local action with only Anchors, Constants, Carpaints, and Project Sanity.
- `0ce1a5a feat(qt): expose audited home preflight` — exposes that one fail-closed Home action while preserving exactly eight UI capabilities.
- `6bac436 feat(qa): add control center truth model` — adds the frontend-neutral seven-gate snapshot, bounded records, deterministic next action, and safe copy-ready evidence.
- `7bf5240 feat(qt): build QA control center home` — replaces the Home tile grid with the selected-scope Control Center while preserving all 19 registered surfaces.
- `2ee87a6 feat(qa): align full QA evidence gates` — aligns detailed Full QA to the same seven gate IDs and adds bounded local evidence text without transport.
- `a1625e7 feat(qt): add same-data presentation view` — adds Presentation as a chrome-only view that preserves profile, evidence, action, and inspection identity.
- `d63d044 feat(qt): add bounded profile preview channel` — adds the opaque, single-worker preview/cache channel with strict frame, byte, time, stale-result, and fallback limits.
- `ff7bdb9 feat(ramses): add bounded authored preview helper` — adds the standalone Ramses helper for a finite authored turntable and strict manifest/output validation.
- `1e76769 feat(qt): finish control center interaction` — completes finite semantic motion, keyboard and screen-reader behavior, audited fonts, provenance checks, and both viewport layouts.
- `9c0d4a0 build: verify QA control center bundle` — adds fail-closed C0 package, cache, source-integrity, viewport, and optional-preview verification.
- `c6b4808 fix(qt): resolve selected profile preview scene` — resolves an available selected-profile scene through the preview-only BMW model root while leaving QA source roots unchanged.

## Acceptance evidence

### Focused tests

- Command: `..\sg-preflight\.venv\Scripts\python.exe -B -m unittest tests.test_bundle_manifest tests.test_qt_quick_benchmark tests.test_qt_quick_preview -v`
- Result: PASS.
- Artifact: `out/control-center-c0/control-center-c0-verification.json`.

### QML format

- Command: `..\sg-preflight\.venv\Scripts\python.exe -B -m unittest tests.test_qml_format -v`
- Result: PASS.
- Artifact: `out/control-center-c0/control-center-c0-verification.json`.

### Staged bundle

- Command: `..\sg-preflight\.venv\Scripts\python.exe -B scripts\build_sgfx_exe.py --staged-only`
- Result: PASS.
- Artifact: `build/b/sgfx-preflight/sgfx-preflight.exe`; SHA-256 `350b29a6d83119531e4c0850668d8cec248fc294418f918072e0a1b140e454d6`.

### Headless viewports

- Command: `..\sg-preflight\.venv\Scripts\python.exe -B -m unittest tests.test_qt_quick_host.TestQtQuickShell.test_control_center_viewports_accessibility_fonts_and_focus_order -v # 1280 x 720; 1024 x 640`
- Result: PASS.
- Artifact: `out/control-center-c0/control-center-c0-verification.json`.

### Compatible preview

- Command: `..\sg-preflight\.venv\Scripts\python.exe -B -m unittest tests.test_qt_quick_preview.TestNativePreviewHelper.test_local_compatible_scene_round_trips_through_the_coordinator_when_available -v`
- Result: PASS.
- Source SHA-256: `ef926f7e4b47a810bc4660ece0a433bd1267f7d769cfc79593cb93683d9b7ba0`.

### Preview cache

- Command: `bounded inventory of out/preview-cache/frame-*.png`
- Result: PASS.
- Artifact: `out/control-center-c0/control-center-c0-verification.json`.

### Timing

- Command: `..\sg-preflight\.venv\Scripts\python.exe -B scripts\benchmark_qt_quick.py --control-center-status`
- Result: OPEN — `OPEN_LOADED_WORKSTATION`.
- Artifact: `out/control-center-c0/control-center-c0-verification.json`.

### Source integrity

- Command: `Get-TrackedFingerprint before and after local diagnostics, package, and preview`
- Result: PASS.
- Source fingerprint SHA-256: `c8a0fcd45f799815f5f08d248e647e1037f28f8d5f1d9b27cfa0874626eb79fa`.

### Supplemental broad regression evidence

- Command: `..\sg-preflight\.venv\Scripts\python.exe -B -m unittest discover -s tests -v`; Result: OPEN after the 904.6-second execution window, with 262 completed `ok` results, no failure/error line, and no suite footer. The last completed test was `test_dashboard.NiceGuiDashboardModelTests.test_dashboard_snapshot_exposes_default_and_show_all_profile_sets_from_bmw_registry`. Artifact: `out/control-center-c0/full-unittest-discovery.log`; SHA-256 `03e64963b28bdec63372856df48fd5f78e2207f32b1e817e9bb89d1c6f3d82a2`.
- Command: `..\sg-preflight\.venv\Scripts\python.exe -B -m unittest tests.test_bundle_manifest tests.test_qt_quick_benchmark tests.test_qt_quick_preview tests.test_qml_format tests.test_qt_quick_host tests.test_qt_quick_core tests.test_qt_quick_capabilities tests.test_native_scaffold -v`; Result: PASS, 198 tests in 163.238 seconds. Artifact: `out/control-center-c0/affected-module-matrix.log`; SHA-256 `3f931c5731ec197d0c83891ff1b9debc493ed7a302cbaa6c868046e9be784b84`.
- Command: `powershell -ExecutionPolicy Bypass -File scripts\run_smoke_test.ps1`; Result: PASS for the demo-good and demo-broken report stages, with optional unavailable corpora explicitly skipped. Its duplicate unit-discovery stage is OPEN after the second accepted-window overrun and is not claimed as passed. Artifact: `out/smoke-test/latest/SUMMARY.md`; SHA-256 `fd6cf67a7149192ff3c2b2875f08d1282865dfbeb0800987dbf023277ce475bf`.

## Safety evidence

- Eight UI capabilities preserved.
- Nineteen registered surfaces preserved.
- No automatic Jira, SVN, BMW, delivery, rack, or vehicle action introduced.
- Source roots unchanged by local preflight and preview.

## Risks and open evidence

- `timing`: OPEN — `OPEN_LOADED_WORKSTATION`.

## Suggested Jira comment

C0 delivers a profile-neutral QA Control Center with explicit selection, one isolated four-pack local action, seven truthful gates, same-data Presentation, and a bounded selected-profile preview with an honest generic fallback.

The deterministic verifier passed focused tests, QML formatting, staged package validation, both headless viewport contracts, compatible selected-profile preview, cache bounds, and source-integrity checks. The accepted executable SHA-256 is `350b29a6d83119531e4c0850668d8cec248fc294418f918072e0a1b140e454d6`.

The release keeps eight UI capabilities and 19 registered surfaces. Local preflight and preview do not mutate source roots, and no automatic Jira, SVN, BMW, delivery, rack, or vehicle action was added.

Loaded-workstation timing remains OPEN as `OPEN_LOADED_WORKSTATION`; no warm-start or first-run performance claim is made from this run.
