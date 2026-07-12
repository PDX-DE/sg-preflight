# SGFX Selected Car Workspace — Clean Mode Design

Status: approved direction; written for final design review

Date: 2026-07-12

Implementation baseline: `feature/sgfx-v02-qt-integration-20260710@a736826`

## 1. Outcome

Replace the current equal-weight Home tile grid with a Selected Car Workspace: one calm, central place that tells a teammate which car is active, what local evidence exists, what to do first, and where the three QA phases lead.

The workspace serves both occasional and experienced Seriengrafik operators:

1. Open SGFX.
2. Confirm the selected car.
3. Start the full preflight from one dominant action.
4. Move through evidence review and delivery documentation when needed.
5. Use All tools or `/` for specialist surfaces.
6. Close SGFX.

This is a presentation and information-architecture refinement. It adds no QA checker, integration, permission, write path, verdict, or external dependency.

## 2. Grounding

| State | Claim | Evidence |
|---|---|---|
| **VERIFIED** | Jana's July 9 hard lock requires a low-level tool that a colleague can open, run, and close, with no new front-of-tool complexity. | `out/agent-control/JANA_SYNC_2026-07-09_HARDLOCK.md` in the coordination checkout. |
| **VERIFIED** | The Qt Quick shell already has Home, five navigation groups, six canonical Home destinations, All-page jump, keyboard help, selected-profile state, reduced-motion timing, and 19 registered descriptors. | `sg_preflight/shell_registry.py`, `sg_preflight/surface_registry.py`, `sg_preflight/desktop/shell_model.py`, and `sg_preflight/desktop/qml/Main.qml`. |
| **VERIFIED** | The current Home payload contains only local activity, freshness, `available`/`not_run` status, and read-only/non-approval flags. | `sg_preflight/home_context.py`. |
| **VERIFIED** | The current Home presentation gives all six destinations equal visual weight in a three-column card grid. | `sg_preflight/desktop/qml/components/HomePage.qml`. |
| **VERIFIED** | The exact current bundle passed navigation and reader-stress gates, while current-tree warm start remains open under a heavily loaded workstation. | Newest `out/agent-control/STATE.md` checkpoint. |
| **INFERRED** | A task-oriented workspace will reduce the decision cost of the equal-card Home without hiding specialist capability. | It prioritizes the documented core workflow while retaining the exact route registry and jump palette. |
| **OPEN** | Delivery readiness cannot be truthfully summarized from the current Home contract. | No accepted shell summary currently combines Full QA, screenshot, manual-review, and delivery evidence into a delivery verdict. |

## 3. Decision record

### Selected: task-first Selected Car Workspace

Home becomes a workspace organized around the active car and the sequence `Preflight → Evidence review → Delivery`. One dominant action opens Full QA Pass. The remaining five canonical Home destinations are regrouped as supporting steps and team context. All 19 registered descriptors remain available through All tools, the navigation sidebar, and `/`.

This direction is selected because it is simpler for occasional users, still fast for specialists, and fits the existing route and payload contracts without inventing a new workflow engine.

### Rejected: polished launcher grid

Restyling six equal cards would improve appearance but preserve the current problem: Home still asks the operator to decide which tool matters before explaining the workflow.

### Rejected: question wizard

A question-led wizard would add interaction steps, require more state, and make experienced users answer prompts before reaching known destinations. It would also turn presentation polish into new workflow behavior.

### Rejected: synthetic readiness dashboard

Showing blocker counts, completion percentages, or `Ready for delivery` from incomplete inputs would be visually persuasive but operationally false. This design does not infer a QA verdict from activity history or color a car green merely because local activity exists.

## 4. Information architecture

### Home header

The Home header is compact and car-first:

- SGFX product mark and `Selected car workspace` label;
- selected profile control, always visible and keyboard-focusable with F2;
- All tools control, which reveals the existing navigation surface;
- Grafiks control, visually secondary and governed by the existing validated host state.

The selected profile is repeated in the workspace title so a screenshot or glance cannot lose car context.

### Primary workspace

The main focus area contains:

- an honest workspace-state label;
- the selected profile name;
- one short explanation of the next step;
- one dominant `Run Full QA Pass` action;
- a compact freshness label.

The action navigates to `full-qa-pass`; it does not bypass that page, invoke a new capability, or start a check from Home.

### QA journey

Three ordered stage panels communicate the workflow without pretending to track completion:

1. **Preflight** — Full QA Pass is primary; Setup Doctor is the supporting prerequisite view.
2. **Evidence review** — Screenshot Test State and Manual Review Companion remain distinct because automated evidence and human verdict ownership are different.
3. **Delivery** — Delivery documentation is the final evidence destination; it is not presented as approval or signoff.

The progression line communicates order only. A stage receives no completed checkmark unless a future accepted contract provides explicit completion evidence.

### Supporting context

Daily Digest appears as team context rather than a QA lifecycle stage. Latest local activity remains visible, newest first, with at most the five existing entries. Empty state copy is one sentence.

### Specialist access

All tools exposes the existing five navigation groups and every registered descriptor. `/` continues to open the jump palette. F1, F2, F5, F12, and Esc keep their current meanings. Home does not delete, rename, or duplicate specialist routes.

## 5. Truthful state model

The workspace state is presentation-only and derives from existing shell inputs:

| Input | Visible label | Tone | Primary action |
|---|---|---|---|
| `pageState` is `idle` or `loading` | `Reading local workspace` | neutral | disabled until profile/context is ready |
| context is ready but no profile is selected | `Choose a car profile` | neutral | disabled |
| ready payload has `status=not_run` or no activity | `Not checked in this workspace` | neutral | `Run Full QA Pass` |
| ready payload has local activity | `Local activity available` | accent/neutral | `Run Full QA Pass` |
| `pageState` is `error` | `Local activity unavailable` | warning | `Run Full QA Pass` remains available when a profile exists |

`Local activity available` means only that activity records exist. It must not use the success color or imply that QA passed.

State priority is `loading → no profile → error → activity/not checked`. This prevents stale payload fields from overriding the current shell condition.

The labels `Needs attention`, `Manual review pending`, and `Ready for delivery` are reserved. They may be introduced only through a separately tested, profile-scoped summary contract that defines authoritative inputs, priority rules, freshness, missing-data behavior, and manual-verdict ownership. That contract is outside this polish slice.

## 6. Component boundaries

The implementation should keep components narrow:

- `Main.qml` owns shell chrome, profile selection, overlays, route navigation, and sidebar visibility.
- `HomePage.qml` owns workspace composition and maps existing payload state to display state.
- A small reusable stage component owns a stage label, description, route actions, focus state, and accessibility metadata.
- A small reusable action row owns one route label and navigation request; it receives no controller object or capability.
- `Theme.qml` owns the visual tokens required by the workspace.
- Python registry and controller contracts remain unchanged unless a test proves a presentation field cannot be derived safely in QML.

Components communicate route IDs upward through `navigateRequested`. They never receive raw paths, commands, processes, credentials, network clients, or unrestricted controller access.

## 7. Data flow and error handling

1. The first frame renders the shell and neutral loading workspace.
2. The existing deferred `desktopController.initialize` schedules `shell_context` off the GUI thread.
3. The selected profile and current Home payload update the workspace.
4. Route actions emit a validated registered route ID to `desktopController.navigate`.
5. Existing stale-request identity rules reject late profile/page results.

Malformed or missing Home fields fall back to the neutral state and existing empty activity copy. An unavailable activity log does not disable navigation to Full QA or other registered evidence pages. No exception text, path, command, credential state, or transport detail is exposed in Home.

## 8. Visual language

Clean remains a professional daily-driver, not a second Grafiks skin.

- graphite canvas and layered neutral panels;
- mint accent for focus and the primary action;
- amber only for a real warning state;
- red only for an actual error or failed evidence state;
- green only where an accepted backend status explicitly means success;
- strong type hierarchy, restrained uppercase labels, generous spacing, and thin structural lines;
- no heavy blur, glow, glass, scanlines, decorative counters, or ornamental telemetry;
- no new image, font, icon pack, shader, or production dependency.

The clean-room game-UI influence is limited to useful abstract behavior: a clear central focus, ordered stage progression, decisive focus feedback, and a compact bottom command guide. No third-party branding, assets, coordinates, layouts, audio, source, or captures are transferred.

Qt Quick Controls Basic primitives and the existing `QtQml`/`QtQuick` import roots remain sufficient. The design must not widen the packaged QML module inventory.

## 9. Motion, input, and accessibility

- Hover/focus feedback uses existing `Theme.motionMicro` or `Theme.motionFeedback` timings.
- Page and stage entrance uses at most the existing short/emphasis timing and must not delay interaction.
- Reduced motion removes stagger, caps travel, and retains immediate focus/status feedback.
- Every route action is reachable by Tab and activates with Enter, Return, or Space.
- Focus is visible with more than color alone where practical, and accessible names include the destination.
- Status is always written in text; color never carries the only meaning.
- The bottom guide remains concise: `/ All tools · F1 Help · F2 Car · F5 Refresh · Esc Back`.

## 10. Responsive behavior

The existing 1280 × 720 reference surface and 1024 × 640 minimum remain contractual.

- At 1280 × 720, the workspace uses a broad primary column plus compact context column when space permits.
- At 1024 × 640, content may stack and scroll; no action overlaps, clips, or falls below a usable focus size.
- Home starts with the sidebar collapsed so the central workspace owns the first view. All tools reveals the sidebar; Esc closes it under the current overlay priority.
- Non-Home surfaces retain the existing page frame and navigation behavior.

No layout animation may trigger expensive relayout loops. Existing reference-scale and tile-layout probes may be adapted to workspace geometry but must retain equivalent minimum-size and no-overlap coverage.

## 11. Performance and safety invariants

- No new reader runs on startup or Home render.
- No existing operational page is eagerly materialized.
- No activity, session, dependency, preference, credential, or external state is written by default startup.
- Home route changes remain registry-validated and read-only.
- Manual review remains human-owned; Home records no verdict.
- No Jira/network action, SVN mutation, BMW-source write, Git push, package publish, or distribution is introduced.
- Grafiks remains optional, separately validated, and unavailable without approved provenance.
- The exact current warm-start and first-run results remain **OPEN**, not passed; this UI work must rerun affected performance gates and may not claim to cure workstation contention.

## 12. Implementation scope

Expected production files are limited to the Qt Quick shell, Home components, theme tokens, and tests that directly specify the new presentation. Python changes require a demonstrated missing contract and must not add a new reader or surface.

The slice does not:

- add readiness aggregation;
- change page payload meanings or checker logic;
- change the exact six Home destination IDs or 19 registered descriptor routes;
- modify explicit Clean, Qt Quick, browser-fallback, or Grafiks routing;
- flip the packaged no-argument default;
- alter Jira or weekly-ticket quarantine;
- import external UI templates or assets;
- rewrite non-Home renderer families.

## 13. Verification and acceptance

Implementation follows RED → minimal implementation → GREEN → rendered inspection → diff review.

Acceptance requires:

1. Home visibly centers the selected profile and one dominant Full QA action.
2. The ordered Preflight, Evidence review, and Delivery stages expose the same five workflow destinations, with Daily Digest retained as supporting context.
3. All six canonical Home route IDs remain present exactly once and navigate correctly.
4. All 19 descriptors remain available through All tools/sidebar and `/`.
5. Loading, empty, activity, and read-failure states use the exact truthful semantics in section 5.
6. No Home state implies QA approval, delivery readiness, or completed manual review.
7. Keyboard traversal, accessible names, visible focus, Esc behavior, and reduced motion pass focused runtime tests.
8. Rendered 1280 × 720 and 1024 × 640 captures show no clipping, overlap, illegible copy, false status color, or hidden primary action.
9. QML formatting and linting pass with only the existing `QtQml` and `QtQuick` roots.
10. Focused Qt shell/core/host, surface-registry, capability, Grafiks, packaging, and benchmark tests pass.
11. Navigation and reader-stress budgets pass on the exact committed tree.
12. Warm-start and first-run evidence is rerun when practical and reported truthfully as passed or open; the director's workstation-load waiver permits continuation but not a false pass claim.
13. Full discovery and package gates are rerun before any later Task 14 default-cutover decision.
14. The final diff contains no unrelated cleanup, new dependency, prohibited attribution, secret, raw private path, or third-party asset.

Task 14 reviews and the packaged default flip remain separate gates. This design may be accepted and implemented without representing the current Qt build as the packaged default.
