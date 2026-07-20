# Maintainer's Guide — Seriengrafik: Project Quality-Hero

For anyone inheriting, reviewing, or extending this tool. It assumes you know Python and the
Seriengrafik delivery workflow, but nothing about this codebase.

## What this is

A local QA operator tool for the 3D-Car delivery workflow: it runs the pre-delivery checks (export
presence, reference integrity, screenshot-test state, delivery documentation, environment readiness),
collects the results as reviewable evidence, and packages that evidence for tickets and handovers.
It supports manual review — it does not replace it, and no check auto-approves anything.

## The three layers

1. **Python backend** (`sg_preflight/`) — the source of truth for all QA logic. Everything the GUIs
   show is computed here; both GUIs are views over the same functions.
2. **Two desktop shells**, both in `sg_preflight/desktop/`:
   - **Qt Quick shell** (`desktop/qml/` + `desktop/qt_quick_app.py`) — the packaged double-click
     default. Native QML; pages are declared in `sg_preflight/surface_registry.py` (19 surfaces, each
     with an enforced one-line subtitle).
   - **Clean window** (`desktop/clean_app.py`) — the NiceGUI dashboard (`sg_preflight/dashboard/`)
     hosted in a QtWebEngine window. Reachable with `--ui-mode clean`.
3. **CLI** (`sg_preflight/cli/`) — every action the GUIs can run, plus operator utilities.
   `python -m sg_preflight --help`; the action/example map lives in `cli/discoverability.py`
   (re-exported through the `cli/_common.py` facade).

## Module map (the ones you will actually touch)

| Area | Modules |
|---|---|
| One-button QA pass + gates | `qa_hub.py`, `services.py` |
| Delivery checks | `delivery_checklist.py`, `bmw_delivery.py`, `bmw_git_readiness.py` |
| Screenshot pipeline | `screenshot_capture.py`, `bmw_pipeline_diagnostics` data in `data/` |
| Reference integrity | `rca_reference_integrity.py` (uses the shared pruned walks in `adapters/common.py`) |
| Workbooks | `workbook_finder.py`, `workbook_generator.py`, `delivery_workbook_generation.py` |
| Evidence/reporting | `profile_summary.py`, `profile_export.py`, `ticket_proof.py`, `daily_snapshot.py` |
| Environment checks | `setup_doctor.py` (every check is a `_check_*` function returning a `SetupDoctorItem`; advisory checks use `required=False` and can never block readiness) |
| Jira (off the main path) | `jira_client.py`, `cli/jira.py` — CLI-only, network+write double-gated, PAT lives in the OS keychain and is only ever shown as a fingerprint |
| Ramses scene probe | `ramses_probe_runner.py` + the C++ helper under `cpp/` (own README) |

## Running, testing, building

- **Interpreter:** use the project venv's Python. Beware the Windows Store `python.exe` alias stub —
  it fakes import errors that look like broken code.
- **Tests:** `python -m unittest discover tests` (~1,100+ tests). When running from a staged bundle
  root, set `PYTHONDONTWRITEBYTECODE=1` and use `python -B`. Qt tests need a graphical
  `QGuiApplication` — a bare `QCoreApplication` created earlier in the process poisons every later
  QML load with "Qt Quick could not be initialized"; if the full suite fails where a module passes
  alone, bisect for an app-instance leak first, do not re-run on a flake theory.
- **Exe build:** `python scripts/build_sgfx_exe.py`. It refuses to start while the packaged exe is
  running. It assembles into a temp distpath and atomically swaps into `dist/sgfx-preflight/` — a
  killed build never corrupts the shipped bundle. Optional Grafiks binaries are included only when
  their env vars are set (see README, "Building the Windows Executable"); "not found; skipping
  optional copy" is normal.
- **Facade splits and mock.patch:** the large modules (dashboard, dependency onboarding, Jira
  client, evidence model) are facades re-exporting from focused sibling modules. Always patch at
  the facade (`sg_preflight.jira_client.X`, `sg_preflight.dependency_onboarding.X`) — a globals-sync
  wrapper re-reads the facade before each call, so facade patches work and sibling-level patches of
  facade-shared names are silently overwritten.
- **Launch health, not window titles:** a startup crash still shows a titled error dialog. To verify
  a build launches, check the process stays alive AND no new `%TEMP%\sgfx-preflight-startup-*.log`
  appeared.

## Where things land

Evidence and run outputs go under the operator's `~/sgfx_outputs/<profile>/...` and the workspace's
`out/` (gitignored). Operator-local state (Jira credentials config, dependency onboarding) lives in
`~/sgfx_operator_state/`; the PAT itself is in the OS keychain, never on disk or in reports.

## First review — a suggested path (~1–2 hours)

1. Read `README.md`, then `ARCHITECTURE.md` (short).
2. Run the tool once: `python -m sg_preflight dashboard run --workspace <trunk> --ui-mode qt-quick`,
   click through Home → Full QA Pass → Setup Doctor.
3. Read `surface_registry.py` top to bottom — it is the honest inventory of what the GUI claims to do.
4. Read `qa_hub.py` (the gates) and one checker end-to-end — `delivery_checklist.py` is
   representative.
5. Run the test suite for whatever you read: `python -m unittest tests.test_delivery_checklist`.
6. Anything surprising: `git log --follow <file>` — the history is granular and the commit messages
   explain the why.
