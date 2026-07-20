# Qt Quick operator UX repair specification

Date: 2026-07-20
Status: Approved implementation specification
Scope: Existing Qt Quick shell surfaces and their existing controller capabilities
Out of scope: new action kinds, new pages, new data sources, new dependencies, executable default changes, network writes, and changes to the Clean shell

## Purpose

The Qt Quick shell must make the selected-car workflow obvious to a first-time operator. Every page must say what it does, keep the selected car visible, present one dominant next action, report every action through one feedback idiom, and provide a visible route Home. Page structure must paint before expensive local readiness probes finish.

This document is both the UX specification and the implementation ExecPlan. It precedes every QML change. The stable route IDs and existing backend capabilities remain the compatibility boundary.

## Entry criteria and invariants

Entry criteria:

- The independent review ledger exists in the control-plane output area.
- The live implementation baseline is clean and its Qt controller, presenter, host, registry, format, and compile gates are green.
- The owner has explicitly sanctioned repair of existing Qt Quick usability and performance behavior.

Invariants:

- The selected profile is canonicalized by the controller before an action is admitted.
- Diagnostics remain limited to the audited `sgfx_preflight` and `delivery_checklist` kinds and remain output-bounded.
- Flat-trunk workspaces may write only beneath the existing workspace output area; source changes elsewhere still fail closed.
- Artifact handles remain opaque, current-generation, current-page, current-profile, and revalidated at reveal time.
- Manual review remains an operator verdict. The shell does not claim approval or replace review.
- No page reader or readiness probe runs on the GUI thread.
- Stale page, readiness, preview, artifact, and action completions cannot update a newer route/profile generation.
- Qt Quick remains the packaged default and the Clean shell remains launchable through its existing mode switch.
- QML remains LF-only and formatted by the repository gate.

## Information architecture

Stable route IDs do not change. Visible names and summaries change where the current label promises work the Qt shell cannot perform.

### Home

- Visible name: `QA overview`.
- Job: show the selected car, the seven-gate snapshot, and the single best existing next action.
- Primary action: the existing selected-car next action supplied by the Home payload. When no car is selected, the profile selector is the primary task; do not show a disabled button pretending to choose a profile.
- Secondary actions: route exploration and one existing 3D inspection entry. Do not show duplicate equally prominent inspection controls on Home.
- The `Local QA checks` gate row is navigation and must say so. Its label becomes `Open selected-car checks`; it must not look like a run button.

### Selected-car checks (`full-qa-pass`)

- Visible name: `Selected-Car Checks`.
- Job: show readiness evidence and run already-audited local checks for exactly the selected car.
- Primary action: the existing selected-car preflight diagnostic when admitted.
- Secondary actions: the existing delivery-readiness diagnostic and Refresh. Secondary actions use quieter styling and remain visibly separate from the primary action.
- If readiness is still loading, the page structure and evidence render immediately; the primary-action area says that local actions are being checked.
- If no diagnostic is admitted, the page remains useful as evidence and gives an honest unavailable state with Refresh as the fallback action.

### Batch evidence (`batch-full-qa-pass`)

- Visible name: `Batch QA Evidence`.
- Job: show existing batch run evidence/history only.
- Primary action: Refresh local evidence.
- The Qt page publishes no diagnostic run action because it has no multi-profile selection surface. It must not imply that the selected-car diagnostic is a batch run.

### Comparison evidence (`cross-car-comparison`)

- Visible name: `Comparison Evidence`.
- Job: show existing comparison evidence when a pair was supplied elsewhere.
- Primary action: Refresh local evidence.
- When no pair exists, say that no comparison evidence is available in this shell. Do not instruct the operator to choose inputs the page cannot accept.

### Manual review

- Job: select an existing review step and record one operator verdict.
- Primary action: Record verdict.
- Refresh and artifact reveal are secondary.
- A step must be explicitly reachable and selectable by pointer or keyboard before its verdict is recorded.

### Operator handoff

- Job: record a bounded stopping point for the selected car.
- Primary action: Record handoff.
- Refresh is secondary.
- On a successful matching completion, clear the submitted form and keep Record disabled until new input exists.

### Read-only evidence and setup pages

- The visible title describes the evidence or setup status already supplied by that route.
- Primary action: Refresh local evidence.
- Artifact reveal is secondary and always reports success or failure through shared feedback.

## Shell orientation

The shell must answer three questions without opening a palette:

1. Where am I? Show `Home / <page title>` on every non-Home page and identify the current page in navigation.
2. What car am I looking at? Show a persistent selected-car badge in normal and presentation layouts. The profile selector remains the edit control; the badge is read-only context.
3. How do I get back? Show a visible Home control on every non-Home page. The sidebar remains available, and the jump palette remains an accelerator rather than the only route.

Esc behavior is deterministic and ordered:

1. Close the topmost open overlay.
2. Exit presentation mode.
3. From a non-Home page, navigate Home.
4. From Home, show existing exit guidance.

Esc never hides the sidebar. Footer and help text describe this exact contract.

## Primary and secondary actions

- Exactly one primary action is visually dominant on each ready page.
- The primary action always applies to the selected car when the page is profile-scoped.
- A form-owned Record button is the page primary action on Manual review and Operator handoff.
- On Selected-Car Checks, the first admitted selected-car preflight action is primary. Other admitted diagnostics and Refresh are secondary.
- On read-only pages, Refresh is primary. Artifact reveal is secondary.
- Disabled controls explain why they are disabled. A disabled control cannot stand in for a different control the operator must use.
- Action labels start with a verb and describe the actual effect. Navigation labels use `Open`; execution labels use `Run`, `Record`, `Reveal`, or `Refresh`.

## Shared feedback idiom

PageFrame owns one feedback region used by every existing capability:

- Busy banner: visible only while the current action is queued or running; includes the action label and selected car when applicable.
- Result card: replaces the busy banner on matching completion and contains a bounded status plus safe result lines.
- Error card: uses the same region and remains until another action starts, the context changes, or the operator dismisses it through existing navigation/refresh behavior.
- Output labels remain adapted and must not expose an absolute private path.

Feedback is scoped by route ID, profile ID, and page generation. A completion from an old context may finish safely but cannot appear on the current page. Diagnostic, manual-review, handoff, Refresh, and artifact-reveal actions all use the same visible lifecycle. The controller may extend its existing feedback payload with identity and existing-capability metadata; it does not add a capability.

## Progressive loading and perceived speed

The current diagnostic page worker waits for page evidence and the full local action inventory, including the runtime probe, before publishing ready content. The repair splits this into two read-only phases:

1. Page phase: load, adapt, present, and publish page evidence and artifacts. Set the page to ready immediately after this phase.
2. Action-readiness phase: enumerate and audit the existing selected-car actions off the GUI thread. While it runs, the action area shows a bounded readiness message. Publish admitted actions only if route, profile, and generation still match.

Readiness failure does not discard already-presented page evidence. It changes only the action area to an honest unavailable state and leaves Refresh available. Navigation, profile change, refresh, and shutdown invalidate or cancel stale readiness work. The existing two-thread page coordinator remains the concurrency boundary; no new dependency or data source is introduced.

Performance evidence uses two distinct terms:

- Shell first paint: the first acknowledged frame, regardless of content state.
- Page ready: the first frame after structural page evidence reaches ready or error.

The benchmark must not call the first metric page readiness. A targeted gate holds the action lister open and proves that page structure becomes ready before readiness is released.

## Motion and feel

Only neutral interaction principles cross the clean-room boundary:

- Spatial decisiveness: navigation changes have a clear origin and destination; content does not drift decoratively.
- Focus hierarchy: one active row or primary action receives the strongest emphasis; neighboring content stays stable.
- Active-state-only progress: spinners, progress motion, and working emphasis appear only for work that is actually pending or running.
- Snappy transitions: use the shell’s existing finite motion token for short state changes. Do not add ornamental loops.
- State before flourish: focus, selected state, busy state, completion, and error must be legible without animation.
- Reduced motion: the existing reduced-motion setting collapses travel and stagger, stops preview playback, and leaves immediate opacity/state changes. Every workflow remains complete with motion reduced.

No reference implementation, asset, shader, measurement, audio, typeface, name, or source identifier is part of this specification or may enter the shipped tree.

## Accessibility floor

- Every actionable control has an explicit `Accessible.name` that describes its effect.
- Static status rows are not exposed as buttons and are not tab stops.
- Review rows are focusable selectable controls with selected state and Enter/Space activation.
- Handoff fields have distinct names; multiline editors provide an explicit Tab route to their Record button.
- Header traversal includes profile selector, presentation control, the available inspection control, and the page primary action in visual order.
- Modal overlays own focus, expose dialog semantics, cycle focus internally, and restore a deterministic shell target when closed.
- Home, sidebar, visible Home control, jump palette, and Esc all remain keyboard-operable.
- Existing normal and compact viewport tests remain green and are extended to the new focus order and orientation controls.
- Live screen-reader speech remains an explicit manual acceptance check; offscreen accessibility inspection is supporting evidence, not a substitute.

## Implementation slices

Each slice begins with a failing regression where the behavior is testable. After each slice, run the touched suite, its immediate neighbors, compileall, QML format, inspect the diff, and commit only that slice.

### Slice 1 — honest routes and orientation

Files:

- `sg_preflight/surface_registry.py`
- `sg_preflight/shell_registry.py`
- `sg_preflight/qa_hub.py`
- `sg_preflight/desktop/qml/Main.qml`
- `sg_preflight/desktop/qml/components/HomePage.qml`
- `sg_preflight/desktop/qml/components/NavigationSidebar.qml`
- `sg_preflight/desktop/qml/components/PageFrame.qml`
- `tests/test_surface_registry.py`
- `tests/test_qt_quick_host.py`
- `tests/test_qt_quick_capabilities.py`

RED gates:

- Registry expectations use the new visible names and honest subtitles.
- Home’s checks row is asserted to navigate with an `Open` label.
- Runtime Esc from a non-Home route returns Home and leaves navigation available.
- Selected car and breadcrumb/Home controls remain effectively visible in normal and presentation layouts.
- Batch no longer admits a selected-car diagnostic action.

Verification:

```powershell
python -B -m unittest tests.test_surface_registry tests.test_qt_quick_capabilities
python -B -m unittest tests.test_qt_quick_host
python -B -m compileall -q sg_preflight
python -B scripts/check_qml_format.py
```

### Slice 2 — one action hierarchy and shared feedback

Files:

- `sg_preflight/desktop/qt_quick_controller.py`
- `sg_preflight/desktop/qml/components/PageFrame.qml`
- `sg_preflight/desktop/qml/renderers/WorkflowRenderer.qml`
- `sg_preflight/desktop/qml/renderers/ReviewRenderer.qml`
- one focused QML component under `sg_preflight/desktop/qml/components/` if PageFrame would otherwise duplicate the feedback/action layout
- `tests/test_qt_quick_capabilities.py`
- `tests/test_qt_quick_host.py`

RED gates:

- A completed diagnostic is absent after route or profile identity changes.
- Busy/result/error feedback is visible for existing diagnostic, manual-review, handoff, and artifact-reveal paths.
- The selected page exposes exactly one primary action; remaining actions are secondary.
- Successful matching handoff clears its fields and disables repeat submission.
- Handoff inputs have non-empty accessible names.

Verification:

```powershell
python -B -m unittest tests.test_qt_quick_capabilities
python -B -m unittest tests.test_qt_quick_host
python -B -m compileall -q sg_preflight
python -B scripts/check_qml_format.py
```

### Slice 3 — progressive action readiness

Files:

- `sg_preflight/desktop/qt_quick_controller.py`
- `sg_preflight/desktop/task_pool.py` only if the existing coordinator needs a narrowly tested cancellation hook
- `sg_preflight/desktop/qml/components/PageFrame.qml`
- `tests/test_qt_quick_core.py`
- `tests/test_qt_quick_capabilities.py`
- `tests/test_qt_quick_benchmark.py`

RED gates:

- A gated action lister cannot prevent base page evidence from reaching ready.
- Admitted actions arrive later without returning PageFrame to its blocking loading state.
- A readiness error preserves the ready page and exposes an action-unavailable state.
- Old readiness results are ignored after navigation, profile change, refresh, and shutdown.
- Benchmark output distinguishes first paint from page ready.

Verification:

```powershell
python -B -m unittest tests.test_qt_quick_core tests.test_qt_quick_capabilities tests.test_qt_quick_benchmark
python -B -m unittest tests.test_qt_quick_host
python -B -m compileall -q sg_preflight
python -B scripts/check_qml_format.py
```

### Slice 4 — keyboard, modal focus, and reduced motion

Files:

- `sg_preflight/desktop/qml/Main.qml`
- `sg_preflight/desktop/qml/components/JumpPalette.qml`
- `sg_preflight/desktop/qml/components/ShortcutHelp.qml`
- `sg_preflight/desktop/qml/components/QaGateDetail.qml`
- `sg_preflight/desktop/qml/renderers/ReviewRenderer.qml`
- `sg_preflight/desktop/qml/renderers/WorkflowRenderer.qml`
- `tests/test_qt_quick_host.py`

RED gates:

- Review rows are reachable in order and Enter/Space changes the selected step.
- Static checks are absent from tab order; routing checks remain reachable.
- Help, diagnostics, and jump overlays own and contain focus, then restore it.
- Header controls and page primary action follow visual order.
- Every new or changed control has a non-empty accessible name.
- Reduced motion preserves all state changes with bounded or zero travel/stagger.

Verification:

```powershell
python -B -m unittest tests.test_qt_quick_host
python -B -m unittest tests.test_qt_quick_capabilities tests.test_qt_quick_presenters
python -B -m compileall -q sg_preflight
python -B scripts/check_qml_format.py
```

## Final acceptance

- Both existing shells launch through their current mode selections.
- Selected car, current page, visible Home path, and one primary action are evident at normal and compact viewports.
- No action is silent and no old-context result appears on a new route or car.
- Base page evidence paints before a gated expensive readiness probe completes.
- Keyboard-only completion covers navigation, review selection, handoff, overlays, Refresh, and admitted diagnostics.
- `python -B -m unittest discover -s tests -t .` runs exclusively and passes once after all slices.
- The executable is rebuilt from final HEAD and the no-args health check confirms the process remains alive for at least ten seconds, creates no new startup log, and has no QtWebEngineProcess child.
- The bundle manifest source commit equals final HEAD.
- The final diff contains no reference material, private path, attribution trailer, internal nickname, new dependency, or default executable behavior change.

## Rollback boundaries

Every slice is an independent commit. If a slice fails its gates, revert only that slice before continuing; do not weaken capability admission, path containment, stale-result checks, or accessibility assertions to make a gate pass. Three consecutive failures with the same root error halt the order for owner direction.
