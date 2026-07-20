# Operator Truth and Resilience Repair ExecPlan

Date: 2026-07-20

Status: approved queue; implementation starts after the accepted Qt Quick UX repair and the urgent cross-shell Esc contract correction at `79d921c`.

## Objective

Close five verified operator-path defects without adding pages, action kinds, data sources, production dependencies, or default-launch behavior. Each slice is RED-first, independently reviewable, independently committed, and verified through its direct tests plus the neighboring surfaces it feeds.

The final exclusive test discovery, executable rebuild, manifest provenance check, and process health check happen only after all five slices and the separate documentation-only gated disposition are complete.

## Invariants

- Status presentation distinguishes execution state, evidence availability, and QA outcome. Unknown values are neutral and readable; they never inherit a positive or negative tone through substring matching.
- Viewing evidence is read-only. GET requests never change source bytes, hashes, timestamps, or artifact provenance.
- A deferred Clean-page failure remains visible until a successful retry or navigation replaces it. Last-good content is identified as stale rather than silently presented as current.
- The Clean launcher opens a browser only after the local URL responds or after a bounded timeout reports a clear failure.
- An executable-directory fallback is not evidence of a valid SG workspace.
- Setup and onboarding remain reachable without a selected car.
- First-run eligibility ends only through explicit dismissal/completion, not incidental dependency-state persistence.
- Existing Qt Quick and Clean launch modes remain functional. No default executable behavior changes.
- No code restores the gated workflow-stage entry. That item receives backlog and documentation corrections only.
- No push, SVN write, publish, secret access, hook bypass, or new dependency is permitted.

## Baseline and preflight evidence

- Qt Quick UX slices: `0250e6a`, `8fdc9de`, `cd81f54`, `86df3e6`.
- Urgent cross-shell Esc repair: `79d921c`.
- Pre-repair exclusive discovery: 1,207 tests, one deterministic Esc contract failure, eight skipped.
- Esc repair gates: focused 8 tests OK; dashboard/Qt Quick/shared-registry neighbors 214 tests OK; compile, QML format, and diff checks clean.

Before Slice 1, cross-check the completed Qt Quick work for these residuals and record evidence rather than reimplementing accepted behavior:

- Home 3D inspection launch honors the existing `canLaunch` contract.
- A matching successful handoff record clears its draft; stale or failed completion does not.
- `PageFrame` owns busy/result/error feedback for capability execution, explicit refresh, and artifact reveal.
- performance payloads name first paint, page ready, and actions ready separately while keeping the documented compatibility field.

Any uncovered residual joins the smallest matching slice below; it does not create a new page or backend capability.

## Slice 1 — Exact status truthfulness

### Entry criteria

- Capture RED cases for the actual hub states `findings`, `queued`, `running`, `recorded`, `not_recorded`, `external`, and `human_review`.
- Capture `not_available` against the Clean tone classifier so it cannot match `available` by substring.
- Capture a Home payload containing findings and prove that its aggregate label is not `Available`.

### Implementation boundary

- Replace substring-based Clean tone selection with exact normalized sets.
- Give the Qt Quick badge an explicit label/tone mapping that separates execution, evidence, outcome, and neutral states.
- Apply the same vocabulary to gate details and Home aggregation.
- Reconcile deprecated browser templates that still collapse completed/running/other into misleading positive or warning classes.
- Unknown values use a sanitized human-readable label and neutral tone; they are never rewritten to `Not run`.

### Gates

- Direct status-mapping tests for Qt Quick, Home/gate presentation, Clean, and deprecated templates.
- Neighbor suites: `tests.test_qa_hub`, `tests.test_qt_quick_presenters`, the focused Qt Quick host status cases, focused dashboard status cases, and focused UI template cases.
- Compileall, QML format, LF check for touched QML, and diff checks.
- Commit subject: `Make operator status labels truthful`.

## Slice 2 — Read-only evidence viewing

### Entry criteria

- RED test a themed HTML view through `/ui/files` and assert the artifact bytes, SHA-256, size, and mtime remain unchanged.
- Repeat the view and assert the same invariants.
- Assert the raw response remains byte-identical to the original artifact.

### Implementation boundary

- Apply theme changes to response content only.
- Remove every GET-path write-back to the source artifact.
- Preserve existing path admission, content-type, missing-file, and raw-download behavior.

### Gates

- Focused `/ui/files` tests, then the complete `tests.test_ui` module and direct report/file-serving neighbors.
- Compileall and diff checks.
- Commit subject: `Keep evidence views read only`.

## Slice 3 — Durable Clean errors and launcher readiness

### Entry criteria

- RED test an accepted deferred page-load failure and an accepted snapshot-refresh failure: both must produce durable error state, a retry path, and stale last-good labeling where content exists.
- Keep stale-token failures invisible.
- RED test that the PowerShell launcher waits for HTTP readiness before opening a browser and fails clearly after a bounded timeout.

### Implementation boundary

- Extend the existing load-token/state contract instead of adding a parallel error system.
- Render a durable in-page error with Retry through the existing Clean page frame/panel path.
- Preserve last-good content only when marked stale and scoped to the same page/profile generation.
- Poll the bound local HTTP URL before `Start-Process`; do not change the server command, bind defaults, or double-click executable path.

### Gates

- Focused load-token and launcher-script tests, then complete dashboard load-token neighbors and the launcher smoke/source contract tests.
- Compileall and diff checks.
- Commit subject: `Persist Clean load failures`.

## Slice 4 — First-run orientation integrity

### Entry criteria

- RED test that an executable-directory fallback without SG markers is reported as unresolved, not as a valid workspace.
- RED test Setup Doctor and onboarding route admission with no selected profile.
- RED test that dependency auto-detection may write dependency state without clearing first-run eligibility.
- RED test explicit dismissal/completion as the only state transition that ends first-run guidance.

### Implementation boundary

- Separate workspace candidate display from validated-workspace truth.
- Keep profile-free setup/help navigation available while car-scoped actions remain guarded.
- Persist an explicit first-run dismissal/completion bit independent of dependency discovery.
- Reuse existing state files and schemas where backward-compatible; no migration dependency.

### Gates

- Focused setup/workspace/first-run tests, then Setup Doctor, dependency onboarding, dashboard snapshot, Qt Quick host/controller, and executable-entry neighbors.
- Compileall, QML format if QML changes, LF check, and diff checks.
- Commit subject: `Preserve first run orientation`.

## Slice 5 — CI and acceptance reconciliation

### Entry criteria

- Pin a source test showing Windows CI installs the existing desktop extra and runs the shipped-default Qt suites with the offscreen platform.
- Identify acceptance plans whose active wording is superseded by the current cutover and add an explicit historical banner without rewriting their evidence.
- Do not update README counts until a reproduced footer exists for the final tree.

### Implementation boundary

- Change Windows CI from editable base install to the existing desktop extra.
- Add a dedicated offscreen Qt test step that exercises the shipped-default shell; do not skip or weaken tests.
- Mark superseded plans historical using a short top-of-file banner.
- Update verification documentation only from reproduced current-tree footers. If the final exclusive footer is still pending, leave the numeric README count unchanged and record that reconciliation as the final-gate action.

### Gates

- Workflow/source contract tests, YAML parse or repository-standard validation, targeted Qt suite offscreen locally, documentation wording scan, compileall, QML format, and diff checks.
- Commit subject: `Test the packaged Qt default in CI`.

## Gated documentation-only disposition

After Slice 5, add the documented Clean workflow-stage mismatch to the canonical QA-gaps backlog using exact citations from `docs/operator-ui-workflow.md` and `docs/qa-workflow-alignment.md`. Correct those documents so they state that workflow-stage starts belong to the deprecated browser flow and are not present in the current Clean shell. State that any restoration requires Technical Owner and Product/Project Coordination approval.

No route, action, control, service, or backend code changes are allowed in this disposition. Commit it separately with subject `Document the gated workflow stage gap`.

## Final acceptance

1. Confirm the worktree is clean and no competing test/build/UI process is running.
2. Run one exclusive `python -B -m unittest discover -s tests -t .` with bytecode disabled and capture the exact footer.
3. If and only if the suite is green, reconcile the README source-count sentence to that reproduced footer in a documentation-only commit, then rerun only the count/source contract test plus diff checks. The full footer remains evidence for the code tree; the count-only commit must not touch executable code or tests.
4. Rebuild with `python -B scripts/build_sgfx_exe.py`. If the known destination swap is blocked, use the documented staged-bundle mirror recovery and record it honestly.
5. Verify `bundle-manifest.json` `source_commit` equals HEAD.
6. Launch the no-args executable, require it alive for at least ten seconds, and verify zero new startup logs and zero QtWebEngineProcess children. Smoke `--ui-mode clean` without changing defaults.
7. Run final compileall, QML format, line-ending, diff, and wording checks.
8. Write the one-page operator summary and append the final durable handoff beat.

If the same failure repeats three times, stop and report the exact blocker. A deterministic failure is fixed and reverified; it is never rerun under a flake theory.

## Recovery point

On interruption, read the latest top block of `out/agent-control/STATE.md`, then the physical tail of `out/agent-handoffs/codex_to_claude.md`. Resume at the first slice without an accepted commit and gate footer. Never infer completion from this plan alone.
