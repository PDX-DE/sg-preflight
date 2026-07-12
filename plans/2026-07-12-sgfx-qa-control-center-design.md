# SGFX QA Control Center — Clean Mode Design

Status: approved direction; written-spec review required before implementation planning

Date: 2026-07-12

Design baseline: `feature/sgfx-v02-qt-integration-20260710@f99a321`

Production-code baseline: `a736826`; the later `f99a321` commit changed documentation only

## 1. Outcome

Replace the equal-weight Home launcher and the superseded car-centered proposal with one QA Control Center: a calm, profile-scoped workspace that tells a Seriengrafik teammate what is being checked, which SGFX-owned checks can run safely, what evidence exists, which human or external gates remain, and what the next truthful action is.

The first implementation slice must let a teammate:

1. open SGFX without an assumed car model;
2. select an available profile from the live local registry;
3. run the SGFX-owned deterministic preflight from one dominant action;
4. understand the ordered QA pipeline without confusing order with completion;
5. inspect the latest local result and route into the relevant evidence or review surface;
6. see that manual, rack, performance, stakeholder, and delivery approval remain separately owned;
7. reach all specialist tools through the existing navigation, All tools, and `/`; and
8. close the tool without changing BMW, Jira, SVN, source repositories, or external systems.

The car preview is an optional contextual accent for 3D-car scope. It is not the organizing principle, a readiness indicator, a substitute for evidence, or a required dependency.

## 2. Evidence foundation and authority

The design is grounded in the full locally captured Confluence baseline and the current SGFX implementation.

For compact references in this document:

- `BMW:` means the operator-local `confluence-readable-dumps/BMW_3DCar/` root.
- `PDX:` means the operator-local `confluence-readable-dumps/PDX_SERGFX/` root.

The dump itself remains local research material and is not copied into this repository.

### Corpus coverage

| State | Claim | Evidence |
|---|---|---|
| **VERIFIED** | The latest local catalogs contain 1,582 logical pages: 1,144 BMW and 438 PDX, both with zero pending. | `BMW:00_INDEX.md:3-13`; `PDX:00_INDEX.md:7-13` |
| **VERIFIED** | BMW also catalogs 4,037 intentionally uncaptured generated PR/test leaves. Their identities were classified, but their bodies are not evidence of a pass or failure. | `BMW:02_IGNORED.md:1-5`, `:4037-4041` |
| **VERIFIED** | The BMW readable tree has 1,134 stale full/truncated-path aliases. The canonical unit is an indexed logical page, not a recursive file count. | Reconciliation against `BMW:00_INDEX.md` and the raw catalog |
| **VERIFIED** | The local export snapshot was generated on 2026-05-13. | `confluence-readable-dumps/README.md:3-18` |
| **OPEN** | The local catalogs cannot prove that current live, permission-hidden, collapsed, or later-created Confluence pages do not exist. | Offline-capture boundary |

### Operational evidence

| Design requirement | State | Confluence evidence |
|---|---|---|
| Ordered QA pipeline | **VERIFIED** | Current flow includes product/input correctness, Blender/raw comparison, RaCo manual/script/screen checks, product and LightFX review, rack testing, and stakeholder cubing. `BMW:001_3DCar/002_3D-Car-Sync---Meeting-Notes/832_Seriesgraphics/876_GFX-Meetings/879_2026-04-28-Quality-brainstorming/page.txt:20-31` |
| Source export and automated asset tests | **VERIFIED** | `.rca` projects are exported, tested, packaged, checked, compressed, and uploaded; Lua tests run through Python and RaCo Headless. `BMW:001_3DCar/002_3D-Car-Sync---Meeting-Notes/085_3D-Car-Assets/661_Integration-Pipeline/663_Delivery-Process/664_3D-Car-exporting-and-testing/page.txt:1-31` |
| QA is broader than pass/fail | **VERIFIED** | The Quality Hero overview includes export/interface/screenshots, formatting, size, Blender/RaCo comparison, functionality, anchors, carpaints, and special cases. `PDX:139_3D-Car/298_Quality-Hero-How-to-review-the-3D-car/page.txt:14-83`, `:108-155` |
| Profile context is multidimensional | **VERIFIED** | Retargeted and target assets can intentionally differ; development/release hashes and interface versions identify delivered assets. `BMW:001_3DCar/002_3D-Car-Sync---Meeting-Notes/689_Onboarding/703_3D-Car-Technische-Ubergabe/page.txt:170-194` |
| Variant coverage is behaviorally significant | **VERIFIED** | Country coding changes both visual selection and dependent light behavior. `BMW:001_3DCar/002_3D-Car-Sync---Meeting-Notes/705_Tips-Tricks/831_Country-Variant-Logic/page.txt:1-10`, `:38-86` |
| Carpaint readiness is not merely schema validity | **VERIFIED** | Captured status distinguishes missing, default, preliminary/unreviewed, and design-reviewed entries. `BMW:001_3DCar/002_3D-Car-Sync---Meeting-Notes/976_CRON-Testing/977_PR-64/978_CommitHash-78cdc7db-PR-64/980_CarPaints-PR-64-78cdc7db/page.txt:9-24` |
| Screenshot evidence needs provenance and deterministic capture state | **VERIFIED** | BMW notes describe incomplete screenshot coverage, a TAA dependency, fuzzy-logic work, and flaky tests. `BMW:001_3DCar/002_3D-Car-Sync---Meeting-Notes/832_Seriesgraphics/926_SG-Regular-Meetings/934_Gfx-Assets-Tech-Round/page.txt:161-176`; `BMW:001_3DCar/002_3D-Car-Sync---Meeting-Notes/832_Seriesgraphics/926_SG-Regular-Meetings/936_Weekly-3D-Car-Sync/page.txt:1989-2000`; `BMW:001_3DCar/002_3D-Car-Sync---Meeting-Notes/971_Effort-Overview/page.txt:720-755` |
| Performance evidence is contextual | **VERIFIED** | The documented set includes VRAM, GPU/CPU, asset size, loading/startup time, baseline, minimum, maximum, and delta. `BMW:001_3DCar/002_3D-Car-Sync---Meeting-Notes/832_Seriesgraphics/962_GFX-Technical-Support/965_SG-Performance-KPIs-and-Benchmarking-How-To/page.txt:19-54` |
| Automated and manual gates coexist | **VERIFIED** | Unit/instrumented/screenshot tests run in CI while rack/in-car and performance review remain manual in the captured process. `BMW:001_3DCar/002_3D-Car-Sync---Meeting-Notes/966_Testing-Approach-Team-WOMBAT/page.txt:5-38` |
| Delivery requires linked provenance | **VERIFIED** | Integration uses linked asset updates, a documented retest hash, ownership fields, and downstream coordination. `BMW:001_3DCar/002_3D-Car-Sync---Meeting-Notes/832_Seriesgraphics/915_SG-Process-Definitions/918_SG-3D-Car-Delivery-Process/page.txt:21-51` |
| Perspective approval is human evidence | **VERIFIED** | Perspective work retains references, RaCo screenshots, documentation, and explicit BMW Design approval. `BMW:001_3DCar/002_3D-Car-Sync---Meeting-Notes/832_Seriesgraphics/834_GFX3DCar---Perspectives-Documentation/page.txt:1053-1116` |
| PDX is not uniformly current authority | **VERIFIED** | PDX marks its 3D Car, related-assets, Widgets, and Sicht/Absicht material as heavily outdated since 2025 and points current IDCEvo work to BMW Confluence. `PDX:002_Getting-Started---SG-Confluence-Overview/page.txt:14-18`, `:43-45`, `:85-91` |
| Universal screenshot thresholds | **OPEN** | The corpus documents threshold tuning and flakiness but no authoritative cross-project numerical acceptance contract. |

Meeting notes, backlog pages, and WIP documents establish observed pain or intent, not automatic acceptance criteria. Current source code and explicit process pages take priority where they disagree.

## 3. Current SGFX reality

### What already exists

- `services.execute_profile_run` resolves and materializes a selected profile, runs `anchors`, `constants`, `carpaints`, and `project_sanity`, then writes JSON, HTML, Markdown, and a run record.
- `RunProfile` already carries a safe subset of context: profile ID/label, brand, lane, build/retarget type, optional interface version, retarget target, active-build state, and registry source.
- The Qt Quick shell already owns Home, profile selection, route validation, reduced motion, five navigation groups, all 19 surface descriptors, one maximum-two-reader coordinator, stale-result rejection, an exact eight-capability inventory, a dedicated effect worker, and opaque artifact handling.
- Local action records and run records already provide bounded persisted history.
- Existing specialist surfaces cover setup, disabled tests, API version, country variants, size, screenshot evidence, risk, manual review, handoff, delivery documentation, workflow guidance, and digests.

### What is currently wrong for a QA-first Home

- `home_context.build_home_context` exposes only five recent local activity entries and freshness. It has no profile-scoped QA snapshot.
- `full_qa_pass._step_defs` starts with onboarding and delivery surfaces, treats comparison and digest as QA steps, and does not invoke the four-pack deterministic profile run.
- `diagnostic.run` has lifecycle handling but its concrete audit currently allows only the read-only delivery-checklist bridge and only on Full QA pages.
- The existing `profile_stack` action is unsafe as Home's one-click action. When locally ready, it can execute repo checkers, unused-resource scanning, RaCo scene checks, and BMW interface/export/screenshot commands. Home must never expose that aggregate as an implicit safe local preflight.
- Qt shell startup chooses the first fallback profile when no explicit preference exists. Generic UI copy and several comparison/digest paths also contain G65/G70 assumptions.
- The registered Cross-Car Comparison subtitle names G70 and G65 even when neither is the operator's intended comparison.

These are product-contract gaps, not reasons to widen the front end with unrestricted process, filesystem, or command access.

## 4. Decision record

### Selected: QA Control Center with a Pipeline Spine

Home centers one selected scope, one safe local action, the ordered QA gates, the latest local evidence, and the next truthful action. Gate detail uses plain language first and progressive technical detail second.

This direction matches the real process, is understandable without command-line knowledge, preserves specialist depth, and can be implemented through the existing registry/controller/capability architecture.

### Rejected: car-first showroom or launcher

A large rotating car is visually attractive but spends the most valuable space on an object that does not explain source correctness, failures, evidence, ownership, or the next QA action. A compact preview remains allowed only as selected-scope context.

### Rejected: dense enterprise dashboard

Showing every metric, ticket, matrix, and artifact at once would intimidate occasional operators, encourage invented aggregate scores, and make missing evidence look like a product failure. Detail belongs behind the selected gate and specialist routes.

### Rejected: question wizard

A wizard would force experienced users through prompts, add state, and hide the stable source-to-delivery model. The pipeline itself is the guidance; the operator selects a gate only when deeper help is needed.

### Rejected: existing profile stack as the primary action

The current stack crosses the safe boundary into optional external executables and BMW-owned flows. A Home action named `Run local QA checks` must be narrower and mechanically incapable of starting those commands.

## 5. Product principles

1. **QA first.** Home answers what is being checked, what SGFX knows, what remains, and what to do next.
2. **Evidence before verdict.** A document, screenshot, action record, or opened page is not automatically a pass.
3. **One safe primary action.** The dominant action runs only SGFX-owned deterministic checks.
4. **Profile neutrality.** No car model is an implicit default, comparison peer, team favorite, or generic UI example.
5. **Progressive disclosure.** Plain-language summary is always visible; commands, raw logs, paths, and specialist controls stay on their existing protected surfaces.
6. **Ownership remains visible.** Deterministic SGFX results, operator review, BMW/external evidence, and approvals are distinct.
7. **Order is not completion.** The Pipeline Spine communicates sequence; it never becomes a synthetic progress percentage.
8. **No surprise external work.** BMW export, screenshot, RaCo, rack, Jira, SVN, and delivery actions require separate explicit contracts and confirmation.
9. **Local-first startup.** Home performs bounded local reads only and starts no expensive checker.
10. **One shared model.** Occasional users, reviewers, and developers see different depth over the same state—not separate truths.

## 6. Personas and jobs

### Occasional operator or artist

Needs a visible selected profile, one recommended starting action, prerequisite guidance, plain-language findings, evidence navigation, and no command syntax requirement.

### Developer or pipeline operator

Needs exact profile context, deterministic pack results, run freshness, failure classification, artifact access through protected handles, and links into raw evidence or specialist routes.

### Reviewer, Topic Owner, Project Coordinator, or Project Manager

Needs missing evidence, human/external ownership, blockers, latest run context, and handoff state without a false delivery verdict.

All three use the same `QaHubSnapshot`; the UI changes density, not meaning.

## 7. Profile and scope contract

### Selection

- Profile options come only from the live local registry.
- An existing explicit locally persisted preference may be restored when it is still canonical; this slice adds no new preference write.
- If there is no valid explicit preference, Home starts with no selected profile and asks the operator to choose one.
- Registry order must never select a model implicitly.
- Selecting a profile invalidates the previous snapshot, action descriptor, run presentation, and gate detail before new state is accepted.
- Grafiks and profile-scoped routes remain unavailable until a canonical profile is selected.

### Safe context projection

Home may expose only these `RunProfile` fields:

- profile ID and label;
- brand;
- lane/platform label;
- build versus retarget type;
- interface version when recorded;
- retarget target when recorded;
- active-build state;
- registry-source label normalized to operator language; and
- source/config availability as a boolean state, never a raw path.

Missing branch, build hash, release hash, country, trimline, drivetrain, equipment, handedness, display, perspective, rack, or delivery context is rendered as `Not recorded`, not guessed from the car model.

The first slice does not create a universal BMW QA-profile object. It projects only fields SGFX already owns and leaves the remaining context visible as missing evidence.

The current profile registry makes 3D Car the only implemented Home scope. The component model keeps scope labels and the preview conditional so later topics can be designed without rewriting the shell, but this slice does not invent a topic selector or pretend that non-car profiles already exist.

## 8. Pipeline Spine

The seven gates are ordered, selectable, keyboard navigable, and backed by stable IDs. A selected gate reveals its checks and related routes.

| Gate | Purpose | Initial check rows | Ownership | Existing routes |
|---|---|---|---|---|
| `context` | Confirm the intended scope and source availability. | Profile selection; brand/lane/type; interface/retarget context; local prerequisites | SGFX projection plus operator choice | `setup-doctor`, `bmw-process`, `qa-workflows` |
| `asset` | Run and inspect deterministic SG-side checks. | Anchors; constants; carpaints; project sanity | SGFX automated | `full-qa-pass` for detailed run presentation |
| `export_interface` | Collect export, interface, disabled-test, and size evidence. | Export result; API/interface; disabled tests; package size | Mixed local/external evidence | `api-version-coverage`, `disabled-tests`, `export-size-trend` |
| `variants` | Make configured product combinations explicit. | Country; trim/drivetrain; equipment/roof; lighting/effects | Evidence and specialist review | `country-variant-coverage` |
| `visual` | Review expected, actual, difference, and capture context. | Expected; actual; diff; capture provenance | Automated candidate plus human review | `screenshot-test-state` |
| `review_runtime` | Preserve operator, rack, performance, and exception ownership. | Quality-Hero review; rack; performance; accepted exceptions | Human/external | `manual-review`, `risk-score` |
| `delivery_handoff` | Collect documentation, integration, and stopping-point evidence. | Delivery documentation; integration evidence; stakeholder/CCB state; handoff | Human/external | `delivery-checklist`, `operator-handoff` |

The first implementation slice provides a real automated state only for `context` and `asset`. Other gates truthfully show `Evidence required`, `Human review`, `Not recorded`, or an explicit persisted state already owned by an accepted reader. Opening a page, viewing a document, or recording activity never upgrades a gate to passed.

Onboarding and daily/team digests remain supporting context, not QA gates. Cross-car comparison is a specialist tool and never a required pipeline step.

## 9. State semantics

The safe state vocabulary is closed and tested:

| State | Meaning | Allowed source |
|---|---|---|
| `selection_required` | No canonical profile is selected. | Shell selection state |
| `available` | The gate or action can be opened/run; no result is implied. | Registry/capability readiness |
| `not_checked` | No accepted persisted result exists for this profile. | Local history absence |
| `queued` | The safe local action is accepted but has not started. | Capability lifecycle |
| `running` | The safe local action is executing. | Capability lifecycle |
| `passed` | The completed deterministic SGFX preflight has zero errors and zero warnings. | Exact four-pack summary only |
| `findings` | The deterministic run completed with warnings and no errors. | Exact four-pack summary only |
| `failed` | A deterministic pack reported errors or the action failed to execute. | Run/action record |
| `blocked` | Required local source/config or execution prerequisite is unavailable. | Audited action readiness |
| `evidence_required` | This gate needs an artifact or result SGFX has not accepted. | Gate contract |
| `human_required` | This gate requires a named human or external decision. | Gate contract or explicit review record |
| `unavailable` | The related surface or source cannot be used on this workstation. | Accepted reader/capability state |
| `not_applicable` | An explicit profile/config contract marks the gate irrelevant. | Explicit configuration only |
| `stale` | A persisted result is proven to target a different source/profile fingerprint. | Exact identity mismatch only |

Clock age alone does not create `stale` in this slice because no accepted universal freshness threshold exists. Until an exact fingerprint is available, Home shows the run timestamp without inferring staleness.

`passed` is never an overall profile, delivery, screenshot, manual-review, rack, or stakeholder verdict. The hub has no overall green state and no completion percentage.

## 10. Next-safe-action rules

Rules are evaluated in this order:

1. No canonical profile → `Choose a profile`.
2. Source/config unavailable → `Open Setup Doctor`.
3. Local action queued/running → show lifecycle state and the allowed queued-cancel control.
4. No local preflight → `Run local QA checks`.
5. Local preflight failed → `Review asset failures`.
6. Local preflight has warnings → `Review asset findings`.
7. Local preflight passed → `Open Export & Interface evidence`.
8. Later gates never collapse into `Ready for delivery`; each retains its own evidence or owner action.

The next action is deterministic from the snapshot and capability state. QML does not reimplement the priority rules.

## 11. Home information architecture

### Header

- SGFX product mark and `QA Control Center` label;
- scope label such as `3D Car`;
- profile selector showing `Choose profile` when empty;
- Clean mode state;
- Help and All tools access; and
- optional Grafiks control, secondary to QA and governed by the existing host validation.

### Primary focus

- headline `Quality starts here`;
- one sentence explaining local checks, evidence, review, and delivery;
- one primary action from the next-safe-action contract;
- one secondary `How this works` action; and
- a compact contextual preview area.

The first slice uses an original generic vector silhouette. Loading an approved profile asset is a later separately reviewed slice. The preview has no readiness color, copied BMW or game asset, model-specific fallback, or interaction required for QA. Subtle ambient movement is optional; reduced motion makes it static.

### Pipeline Spine and gate detail

- seven equal gate selectors with index, short label, and text state;
- left/right arrow navigation between gates;
- selected gate title and explanation;
- up to four initial check rows with exact state and destination;
- no decorative progress percentage; and
- no green connecting line that implies downstream completion.

### Context rail

- exact next safe action;
- latest local SGFX preflight timestamp and summary;
- human/external gates with explicit `No evidence` or ownership text; and
- local-only safety note.

### Navigation

The sidebar retains Home and the existing five navigation groups: Daily work, Delivery, Screenshots & coverage, Reviews & digests, and Setup & help. All tools and Grafiks remain separate shell controls. The implementation does not create mockup-only `Runs`, `Evidence`, or `Review` routes and does not add a twentieth operational surface. All 19 descriptors remain reachable through the sidebar and `/`.

## 12. Safe local execution contract

### New narrow action

Add one profile-scoped operator action:

- action ID: `sgfx_preflight__<canonical-profile>`;
- kind: `sgfx_preflight`;
- label: `Run local QA checks`;
- readiness: selected profile source project and config exist; and
- executor: one call to `services.execute_profile_run` using exactly `anchors`, `constants`, `carpaints`, and `project_sanity`.

The action writes only beneath the configured SGFX output root and returns its action/run record plus generated reports. It must not call:

- `profile_stack`;
- repo checkers;
- unused-resource scripts;
- RaCo Headless scene checks;
- delivery-checklist executables;
- BMW `car_manager.py`;
- BMW interface, export, or screenshot commands;
- Jira, SVN, Git push, Artifactory, CI, rack, or vehicle systems; or
- arbitrary commands supplied by QML.

### Existing capability boundary

Keep the exact eight-capability inventory. Extend `diagnostic.run` to Home only for the new audited `sgfx_preflight` action.

The audit must require all of the following:

- exact kind `sgfx_preflight`;
- exact action ID/profile relationship;
- canonical current profile;
- profile scope;
- project root contained in configured read-only roots;
- output root contained in the allowed SGFX output root;
- returned output paths contained under that output root;
- no source-root mutation before/after execution;
- current page/profile/generation identity;
- one effect at a time; and
- safe lifecycle/error text.

The existing delivery-checklist audit remains available only where already accepted. `profile_stack`, BMW smoke, scene checks, repo checkers, and other kinds remain rejected by the Qt Home audit.

Queued cancellation remains truthful: cancellation is offered only while the future can actually be cancelled. Once execution starts, the UI must not claim an in-process cancel that the current executor cannot provide.

After a successful current-page execution, Home schedules a fresh shell-context read. A stale completion may persist its output record but may not overwrite the newly selected profile or current UI.

## 13. `QaHubSnapshot` contract

Add a small frontend-neutral module, preferably `sg_preflight/qa_hub.py`, that owns gate definitions, state reduction, and next-action priority. `home_context.py` continues to own bounded recent activity; the shell-context loader combines both safe projections.

The QML-safe payload is versioned and contains only:

```text
schemaVersion
scopeLabel
selectedProfile
profileOptions
contextFields[]
gates[]
selectedGateId
latestLocalRun
nextAction
activity[]
readOnly
isApproval
```

Each gate contains only stable IDs, labels, plain summaries, safe state, related registered route IDs, and check-row presentation. `latestLocalRun` contains action/run ID, timestamp, lifecycle state, and numeric errors/warnings/info where available.

Home receives no raw path, command preview, subprocess output, exception text, credential state, URL, network client, source object, or unrestricted controller reference. Generated artifacts remain protected by the existing opaque-handle flow on the detailed run surface; the first Home slice navigates to that surface rather than revealing paths directly.

Snapshot reads are bounded to:

- the selected `RunProfile` safe projection;
- at most 12 recent local action records and 12 recent run records;
- the existing five-entry activity log; and
- static registered route metadata.

Home startup does not invoke page loaders, scan BMW repositories, recurse source trees, materialize bundles, parse screenshots, run validators, or contact a service.

## 14. Full QA and surface alignment

The `full-qa-pass` route remains the detailed run/evidence surface and retains its stable ID. Its presentation and read-only step order must align with the same seven gates.

Required corrections:

- put profile/source context first;
- put latest SGFX local preflight and its four packs under Asset integrity;
- group API, disabled tests, size, and export evidence under Export & Interface;
- add the existing country-variant surface under Variants;
- keep screenshots under Visual Evidence;
- place risk/manual review before delivery;
- place delivery documentation/workbook/integration/handoff last;
- remove onboarding, cross-car comparison, and team digest from pass/fail step semantics; and
- keep every external/manual item explicitly non-approval unless its own accepted record says otherwise.

The page does not auto-run the new local preflight on load and does not auto-run BMW actions. It may expose the same audited explicit local-preflight action.

Batch Full QA may reuse the safe local action sequentially only after the single-profile contract is GREEN. It must not inherit the existing broad `profile_stack` behavior under the new label.

## 15. Profile-neutral defaults and copy

The implementation slice must remove implicit named-car behavior from generic runtime and UI paths it touches:

- Qt Home restores only a valid explicit preference; otherwise selection is empty.
- Cross-car comparison requires an explicit second profile or shows `Choose comparison`.
- Team Digest receives explicit/configured profile IDs; an absent list does not become G70/G65.
- Full QA has no implicit comparison profile and comparison is not a QA gate.
- Evidence-model convenience loaders do not append G70/G65.
- The Cross-Car Comparison subtitle is model-neutral.
- CLI help uses `<profile>` or a clearly labelled example rather than presenting G65 as a generic default.

Named models remain valid in profile definitions and focused test fixtures. They may appear in UI only because the operator selected them or because an evidence record names them.

Changing profile registry order must not change an empty selection, comparison target, team digest scope, or Home action.

## 16. Component boundaries

- `qa_hub.py` owns immutable gate definitions, safe snapshot projection, state reduction, and next-action rules.
- `home_context.py` owns bounded activity only and composes no verdict.
- `qa_operator_actions.py` declares the narrow local action.
- `qa_actions.py` executes that one action through the existing profile-run service.
- `ui_capabilities.py` owns the fail-closed audit and unchanged eight-capability inventory.
- `qt_quick_controller.py` owns shell/action discovery, lifecycle, stale identity, refresh, and capability invocation.
- `HomePage.qml` owns composition only.
- A small `QaPipelineSpine.qml` owns gate selection and keyboard traversal.
- A small `QaGateDetail.qml` owns check rows and route requests.
- A small contextual-preview component owns decorative scope art and reduced-motion behavior.
- `Main.qml` owns shell chrome, overlays, profile selection, controller invocation, and registered navigation.
- The existing presenter/renderers own the detailed Full QA page.
- `Theme.qml` owns the minimal tokens required by the design.

QML emits stable route/action IDs upward. It never constructs an action ID from arbitrary text, opens a path, starts a process, or receives a command.

## 17. Data flow and failure handling

1. The first frame renders the neutral shell and QA Control Center skeleton.
2. The off-thread shell-context read loads profile options, the valid explicit preference if any, bounded activity, and the safe QA snapshot.
3. With no selected profile, Home shows `Choose profile` and no runnable profile action.
4. Profile selection increments generation, clears old gate/action state, and loads the new snapshot.
5. The primary button invokes the exact capability descriptor already present in the current Home payload.
6. The dedicated effect worker writes only SGFX output records and reports.
7. Lifecycle signals update queued/running/completed/failed presentation.
8. A current successful completion reloads the snapshot; stale results are ignored by UI identity checks.
9. Gate and check-row navigation emits only registered route IDs.

Malformed snapshot fields fail to a neutral `Local QA state unavailable` view while navigation and profile selection remain usable. Raw exception messages, paths, and commands never become Home copy.

A validator finding is not an application crash. Execution failure, deterministic errors, warnings, blocked prerequisites, missing evidence, and human review are displayed as distinct states.

## 18. Visual language

Clean remains a professional daily driver, not a second Grafiks skin.

- graphite canvas with layered neutral panels;
- mint/aqua for focus, selection, and the safe primary action;
- amber for findings, missing evidence, and human attention;
- red for deterministic errors or execution failure;
- green only for a completed zero-error/zero-warning SGFX deterministic result;
- strong type hierarchy, thin structural lines, calm spacing, and short copy;
- no fake telemetry, completion rings, decorative percentages, or marketing badges;
- no new font, image pack, icon dependency, shader, web asset, or production dependency; and
- no copied BMW infotainment, Nintendo, SEGA, Valve, Sonic, or other third-party layout or asset.

Game-menu and in-car influence is limited to abstract interaction qualities: one central focus, decisive selection feedback, spatially stable navigation, readable hierarchy, and a compact command guide.

## 19. Motion, input, and accessibility

- Tab reaches profile selection, primary action, all gates, check rows, rail actions, and navigation.
- Left/Right moves between gates; Enter/Return/Space selects or opens.
- Focus is visible beyond color alone.
- Status is always written in text.
- Accessible names include gate, check, state, and destination.
- F1, F2, F5, F12, `/`, and Esc retain their current meanings.
- Reduced motion removes car movement, entrance stagger, and nonessential travel while retaining immediate focus and state feedback.
- Motion never delays action availability or changes semantic state.

## 20. Responsive behavior

The existing 1280 × 720 reference and 1024 × 640 minimum remain contractual.

At 1280 × 720:

- collapsed navigation, broad center workspace, and compact context rail fit without scroll overflow;
- the contextual preview remains smaller than the action/pipeline region; and
- four gate-detail rows remain visible.

At 1024 × 640:

- navigation width and context rail contract without hiding the primary action;
- seven gate selectors remain legible and keyboard reachable;
- no button, popover, or gate detail is clipped; and
- vertical scrolling is allowed only inside the central content region when translated copy requires it.

Profile popovers render above the workspace stacking boundary. Geometry tests must exercise the open popover, not only static screenshots.

## 21. Performance and safety invariants

- No checker, operational page loader, or BMW repository scan runs at startup; only the new bounded shell snapshot read is added.
- No operational page is eagerly materialized.
- Snapshot reads are bounded and off the GUI thread.
- Only one effect executes at a time.
- Source roots are verified unchanged around the safe diagnostic.
- Output remains under the allowed SGFX output root.
- Home profile selection remains session state in this slice and adds no preference write.
- No Jira/network action, SVN mutation, BMW-source write, Git push, package publish, delivery, or external approval is introduced.
- Grafiks remains optional and provenance-gated.
- The exact warm-start and first-run acceptance remains OPEN under the director's loaded-laptop waiver; this design may continue but may not claim a performance pass.
- The packaged no-argument default remains unchanged until the separate Task 14 review/cutover gates pass.

## 22. Implementation boundary

This written design covers one cohesive implementation plan:

1. profile-neutral Qt selection and generic copy;
2. the narrow SGFX local-preflight action;
3. fail-closed Home diagnostic exposure through the existing capability;
4. the bounded QA snapshot and next-action reducer;
5. QA Control Center QML components;
6. detailed Full QA ordering/presentation alignment;
7. rendered interaction/accessibility verification; and
8. exact-tree source, package, and performance regression gates.

It does not implement these BMW-evidence gaps yet:

- a generalized trimline/drivetrain/equipment/roof/light variant matrix;
- carpaint design-review, CAF, CarLib, productive-state, SOP/EOP, and model-association coverage;
- deterministic TAA/animation capture control or a new comparator threshold;
- structured VRAM/GPU/CPU/size/loading/startup/baseline/min/max performance records;
- live rack, car, Artifactory, CI, Gerrit/CCB, Jira, or stakeholder integrations;
- explicit per-role PM, LightFX, TA, Design, Wombat, or CCB signoff records;
- new MINI/Rolls-Royce profile creation where source coverage is not locally proven; or
- a real-time 3D renderer or copied infotainment UI.

Those are evidence-backed follow-on slices. Home may expose their absence and route to existing evidence, but it may not fabricate implementation or completion.

## 23. Verification and acceptance

Implementation follows RED → minimal implementation → GREEN → rendered interaction inspection → diff review.

Acceptance requires:

1. Home visibly centers QA context, one safe local action, seven ordered gates, latest local evidence, and the next truthful action.
2. No model is selected without a valid explicit local preference or operator selection.
3. The generic UI and runtime paths touched by the slice contain no implicit G65/G70 default or comparison pair.
4. `sgfx_preflight__<profile>` runs exactly the four deterministic packs and writes only inside the allowed output root.
5. Negative tests prove Home rejects `profile_stack`, BMW smoke, scene-check, repo-checker, unused-resource, delivery executable, malformed ID, noncanonical profile, stale action, source-root mutation, and output-root escape.
6. The exact eight-capability inventory remains unchanged.
7. Home refreshes after a current successful local run; a stale completion cannot overwrite a new profile or page.
8. Gate-state reducer tests cover every state and the exact next-action priority.
9. Completed warnings render `findings`; only zero-error/zero-warning deterministic output renders `passed`.
10. Human/external gates never render as passed from activity, page visibility, document existence, or a local preflight result.
11. Full QA presents the same gate order and removes onboarding, digest, and comparison from pass/fail semantics.
12. All 19 registered descriptors remain present exactly once and reachable through navigation and `/`.
13. Profile options, snapshot payloads, actions, and QML contain no raw source/output path, command, URL, credential, secret, or unsanitized exception.
14. Keyboard traversal, accessible names, focus, popover stacking, Esc behavior, and reduced motion pass focused runtime tests.
15. Rendered 1280 × 720 and 1024 × 640 captures show no overflow, overlap, clipped action, false status color, or car-dominant hierarchy.
16. QML formatting and linting pass with only the existing `QtQml` and `QtQuick` roots.
17. Focused Home, hub reducer, actions, capability, controller, presenter, registry, Grafiks, and package tests pass.
18. Full discovery, exact bundle checks, navigation, and reader-stress gates pass before any later default-cutover decision.
19. Warm-start and first-run evidence is rerun when the workstation is reference-ready and reported as passed or OPEN, never inferred.
20. The final diff contains no unrelated cleanup, new dependency, prohibited attribution, confidential dump content, absolute private path, or third-party asset.

## 24. Explicit open evidence boundaries

- The May 2026 local Confluence catalogs are exhaustive for their captured manifests, not current live-service truth.
- The corpus does not define one universal screenshot acceptance threshold.
- Current screenshot automation scope conflicts by layer and date; Home must show provenance instead of resolving that conflict by assumption.
- Current performance pages establish what to measure, not one universal pass threshold.
- Warm and first-run acceptance on the exact current tree remains open under workstation load.
- External approvals remain outside SGFX until separately designed, authorized, and evidenced.

These OPEN items are acceptance constraints, not placeholders. No unresolved design choice blocks the written-spec review.
