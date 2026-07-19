# Architecture

## Overview

`sg_preflight` is a delivery quality-assurance toolkit for 3D vehicle data. It reads a
local working copy of the vehicle repositories (SVN trunk and Git model repos), runs a
battery of structural and content checks against the materialized scene data, and turns
the results into reviewable evidence: console reports, JSON/Markdown exports, screenshot
review queues, delivery workbooks, and a web dashboard. It is built for daily operator
use — one person preparing a model for delivery — and is profile-driven, so the same
checks run identically across every vehicle variant rather than hard-coding any single
model. The package is arranged in clear layers, with a small set of foundation modules
that everything else depends on.

## Layered architecture

Data moves left to right: raw files on disk are discovered and materialized into typed
bundles, the bundles are validated, validation output is aggregated and scored, and the
result is surfaced through a CLI, a desktop host, and a web dashboard. Optional
integrations (issue tracker, external test harness) sit at the edges and never couple
into the core.

```
        ┌─────────────────────────── core / utilities ───────────────────────────┐
        │  profiles · services · models · bundle · config_loader · assets         │
        │  utils · subprocess_utils                                                │
        └──────────────────────────────────┬──────────────────────────────────────┘
                                            │ (used by every layer)
   on-disk repos                            ▼
   (SVN trunk,        ┌─────────────┐   ┌─────────────┐   ┌──────────────────────┐
    Git models)  ──▶  │  adapters   │──▶│ validators  │──▶│  domain: readers +   │
                      │  (IO /      │   │  (checkers) │   │  builders + BMW-     │
                      │ discovery / │   │             │   │  specific            │
                      │ materialize)│   │             │   │                      │
                      └─────────────┘   └─────────────┘   └──────────┬───────────┘
                                                                     │ evidence,
                                                                     │ reports,
                                                                     ▼ exports
                          ┌──────────── surfaces ──────────────────────────────┐
                          │  cli  ·  desktop host  ·  web dashboard  ·  reporting│
                          └──────────────────────┬──────────────────────────────┘
                                                 │
                          ┌──────── optional integrations (edge) ──────────────┐
                          │  Jira client   ·   OpenHTF station   ·   exports    │
                          └─────────────────────────────────────────────────────┘
```

### 1. Adapters / IO — discover and materialize
Walk the working copy, parse the on-disk formats (anchors, car paints, constants,
project manifests), and normalize them into typed, in-memory bundles. This is the only
layer that knows the raw file layout. JSON read/write and file-walking primitives live
in `adapters/common.py`.

### 2. Validators / checkers — verify rules
Take a materialized bundle and check it against the rules for that domain (anchors,
car paints, constants, project sanity). Validators are pure: bundle in, findings out.

### 3. Domain — aggregate and build
Two flavors:
- **Readers** aggregate state over time and across sources: activity logs, delivery
  checklists, QA history, review state, risk scores, export-size trends, coverage
  boards (API version, country variant).
- **Builders** compose findings into deliverable artifacts: daily snapshots and
  digests, delivery workbooks, manual-review sessions, screenshot triage and review
  galleries, ticket-review bundles, readiness assessments, cross-car comparisons.
- **BMW-specific** domain logic resolves the model registry, inspects screenshot
  surface state, checks Git delivery readiness, and runs pipeline diagnostics.

### 4. Surfaces — present to the operator
- **CLI** (`sg_preflight/cli/` package) routes the full command surface across every subsystem:
  `_common.py` holds the parser and `main()`, `discoverability.py` the action/example map,
  `console_render.py` the console output, `session_activity.py` the CLI activity log, and one
  module per command family (`jira.py`, `dashboard.py`, `evidence.py`, ...).
- **Desktop host** (`desktop/`) hosts two native shells over the same evidence model,
  theme, and file operations: the PySide6/QtWebEngine Clean window
  (`desktop/clean_app.py`, selected by `--ui-mode clean`) and the Qt Quick QML shell
  (`desktop/qml/` and `desktop/qt_quick_app.py`, selected by `--ui-mode qt-quick`).
- **Web dashboard** (`dashboard/`) renders the aggregated boards and workflow pages.
- **Reporting** (`reporting.py`, plus per-module renderers) produces HTML, JSON, and
  Markdown output.

### 5. Optional integrations — edges
- **Jira client** (`jira_client.py`) posts comments / updates / attachments via REST.
- **OpenHTF** (`openhtf_support/`) plugs checks into an external test-station harness.
These are opt-in and isolated, so the core has no hard dependency on them.

## Core hub modules

A handful of modules are imported by most of the tree. They define the shared
vocabulary every other layer speaks. Change them carefully — the blast radius is large.

| Module | Role | ~Importers |
|---|---|---|
| `bmw_delivery.py` | Model registry and profile/brand/lane resolution; defines `BmwRegistryEntry`, `BmwModelConfigRecord`, screenshot surfaces | 21 |
| `profiles.py` | `RunProfile` definition and repository-root resolution — the execution context for every check | 20 |
| `utils.py` | Path normalization, data traversal, validation helpers | 14 |
| `services.py` | Run-request orchestration, progress tracking, report generation, operator UI paths | 14 |
| `subprocess_utils.py` | Subprocess management (hidden-window spawn on Windows), CLI command building | 10 |
| `models.py` | `Finding` and `PackResult` — the result vocabulary for all checks | 7 |
| `bundle.py` | `Bundle` — aggregated scene hierarchy, constants, car paints | 5 |
| `adapters/common.py` | JSON I/O, file walking, shared discovery primitives | 5 |
| `assets.py` | Runtime asset-path resolution for frozen executables and development | 4 |

`bmw_delivery` and `profiles` together are the spine: a profile names a vehicle context;
the registry resolves it to concrete repository paths, brand, and surfaces. Everything
downstream is "run check X under profile P."

## Data flow

1. **Read.** An operator picks a `RunProfile`. `profiles.py` resolves the repo root;
   `bmw_delivery.py` resolves the model/brand/lane and the relevant screenshot surfaces.
2. **Materialize.** The adapters layer walks the working copy and turns raw anchors /
   car paints / constants / manifests into a typed `Bundle`.
3. **Check.** Validators run their rules against the bundle and emit `Finding`s; BMW
   domain modules add registry/pipeline/screenshot-state checks; subprocess-backed
   actions (`subprocess_utils.py`) invoke the external pipeline where needed.
4. **Aggregate.** Reader modules fold findings into history, risk scores, coverage
   boards, and readiness state.
5. **Build & surface.** Builder modules compose snapshots, digests, workbooks, review
   sessions, and ticket bundles. These are rendered to console / JSON / Markdown / HTML
   and shown through the CLI, desktop host, or web dashboard.
6. **Integrate (optional).** Results can be posted to the issue tracker via the Jira
   client or run inside an OpenHTF station; exports are written to a chosen output path.

## Integration boundaries

- **Jira client** — `jira_client.py` is the only module that talks to the issue
  tracker, over REST with token auth. Credentials are read from the operator's OS
  keychain, never passed through the application's own data path. All Jira-touching CLI
  commands funnel through this one client.
- **OpenHTF** — `openhtf_support/` (phases, plugs, station, outcomes) adapts the
  existing check functions into an external test-station harness. It depends on the
  domain layer, not the reverse, so the core runs with or without OpenHTF installed.
- **Desktop host** — `desktop/` (PySide6) and `dashboard/` (web) are presentation
  hosts over the same data layer. They read evidence and call into services/builders;
  they hold no business rules of their own. The frozen-executable entry path
  (`exe_entry.py`) wires startup-error logging for double-click launches.

## Module map (by layer)

| Layer | Representative modules |
|---|---|
| core / utilities | `profiles.py`, `services.py`, `models.py`, `bundle.py`, `config_loader.py`, `assets.py`, `utils.py`, `subprocess_utils.py`, `profile_*` |
| adapters / IO | `adapters/common.py`, `discovery.py`, `materialize.py`, `anchors.py`, `carpaints.py`, `constants.py`, `project_sanity.py` |
| validators | `validators/anchors.py`, `carpaints.py`, `constants.py`, `project_sanity.py` |
| domain — readers | `activity_log.py`, `delivery_checklist.py`, `delivery_readiness.py`, `export_size_*.py`, `full_qa_history.py`, `review_state.py`, `risk_scoring.py`, `api_version_coverage.py`, `country_variant_coverage.py` |
| domain — builders | `daily_snapshot.py`, `daily_digest.py`, `delivery_workbook_generation.py`, `manual_review.py`, `screenshot_*.py`, `ticket_review.py`, `visual_review.py`, `full_qa_pass.py`, `qa_actions.py`, `qa_hero_readiness.py`, `quality_hero_report.py`, `setup_doctor.py`, `onboarding_assistant.py`, `dependency_onboarding.py`, `cross_car_comparison.py` |
| domain — BMW-specific | `bmw_delivery.py`, `bmw_process.py`, `bmw_git_readiness.py`, `bmw_pipeline_diagnostics.py`, `bmw_pipeline_auto_fix.py`, `checker_catalog.py`, `checker_evidence.py`, `tool_readiness.py` |
| surfaces — CLI / entry | `cli/` (package), `exe_entry.py`, `__main__.py`, `ui.py`, `live_state.py` |
| surfaces — desktop | `desktop/app.py`, `evidence_model.py`, `clean_host.py`, `file_ops.py`, `theme.py`, `desktop_notifications.py` |
| surfaces — dashboard | `dashboard/main.py`, `dashboard/dependency.py` |
| reporting | `reporting.py`, `review_tracking.py`, `retro.py`, `feedback_routing.py` |
| utilities (support) | `template_store.py`, `workbook_finder.py`, `workbook_generator.py`, `delivery_support_package.py` |
| optional integrations | `jira_client.py`, `openhtf_support/*` |

## Notable size hotspots

The former monoliths were decomposed behavior-preservingly: the CLI is the `cli/` package
(parser in `_common.py`, ~2,200 lines, with the action map, console rendering, and session
logging in focused siblings), the Clean dashboard is `dashboard/main.py` (~2,300 lines, render
route + facade) plus focused siblings (`snapshot.py`, `panels_*.py`) and the
`dashboard_workflows/` package. The remaining large files have honest structural floors:
`dashboard_workflows/renderers.py` (~3,400 lines, dominated by one closure-bound panel tree),
`ui.py` (~3,000 lines, deprecated legacy web view kept for compatibility), and
`dependency_onboarding.py` (~2,500 lines). Further splitting of those would require
behavior-changing restructures and is deliberately deferred.
