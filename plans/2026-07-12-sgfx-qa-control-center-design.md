# SGFX QA Control Center — Unified Product Design

Status: approved by the user on 2026-07-12; C0 implementation planning and execution authorized

Date: 2026-07-12

Design baseline: `feature/sgfx-v02-qt-integration-20260710@6600f93`

Production-code baseline: `a736826`; all later commits through this design beat changed documentation only

## 1. Outcome

Replace the equal-weight Home launcher and the visible Clean-versus-Grafiks split with one SGFX QA Control Center: a calm, profile-scoped workspace that tells a Seriengrafik teammate what is being checked, which SGFX-owned checks can run safely, what evidence exists, which human or external gates remain, and what the next truthful action is.

The first implementation slice must let a teammate:

1. open SGFX without an assumed car model;
2. select an available profile from the live local registry;
3. run the SGFX-owned deterministic preflight from one dominant action;
4. understand the ordered QA pipeline without confusing order with completion;
5. inspect the latest local result and route into the relevant evidence or review surface;
6. see that manual, rack, performance, stakeholder, and delivery approval remain separately owned;
7. reach all specialist tools through the existing navigation, All tools, and `/`;
8. inspect a real selected-profile car preview when the approved local renderer and source are available, without making that preview a QA result;
9. expose an extraction-compatible evidence seam for the separately governed Ramses QA Observatory without starting that probe at C0 startup or broadening the Home capability surface; and
10. close the tool without changing BMW, Jira, SVN, source repositories, or external systems.

The car preview is an optional contextual accent for 3D-car scope. When available, it is rendered from the real selected profile's resolved local Ramses export and shown as a bounded turntable. It is not the organizing principle, a readiness indicator, a substitute for evidence, a reason to select a default model, or a required dependency.

There is one product and one state model. `Presentation view` removes secondary chrome from the same selected profile, gate, evidence, and capability set. `Open 3D inspection` is a focused drill-down backed by the existing external-process capability, not a second mode or alternate QA truth.

The approved Ramses-native program is specified separately in `plans/2026-07-12-sgfx-ramses-qa-observatory-design.md`. This Control Center slice establishes the safe truth path first. Ramses R0 follows as an independently gated implementation and later joins the same explicit one-button action only after its standalone evidence, isolation, package, and performance contracts pass.

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

### Pre-SGFX process coverage

The central path covers the documented work that existed before SGFX without turning every document into another Home surface:

| Documented work before SGFX | Control Center gate | Direct operator answer | Truth boundary |
|---|---|---|---|
| Identify the intended product, source, interface, retarget, and prerequisites. | Context | `Am I checking the intended profile and is its local source available?` | Missing hashes, variants, or source context remain `Not recorded`. |
| Compare Blender/raw content and review anchors, constants, carpaints, and project structure. | Asset integrity | `Which deterministic SGFX checks found what, and where is the evidence?` | The four SGFX packs do not replace visual Blender/RaCo review. |
| Export, execute automated tests, reconcile interfaces and disabled tests, and inspect package size. | Export & interface | `Which export/interface evidence exists, what is absent, and who owns the next step?` | Home never starts RaCo, BMW export, screenshots, or delivery commands implicitly. |
| Exercise country, trimline, drivetrain, equipment, roof, lighting, and effect combinations. | Variant coverage | `Which combinations are evidenced, missing, or outside the accepted reader?` | A single rendered view never implies variant coverage. |
| Produce and review expected, actual, diff, TAA, animation, and capture provenance. | Visual evidence | `What differs, under which capture conditions, and what needs human review?` | No universal comparator threshold or automatic visual approval is invented. |
| Perform Quality-Hero cross-tool review, product/LightFX review, rack/in-car testing, performance review, and exception handling. | Manual/runtime review | `Which named human or external review remains, and what evidence supports it?` | Activity, document presence, and local preflight never become approval. |
| Assemble documentation, integration provenance, retest hash, stakeholder state, and handoff. | Delivery & handoff | `What can be handed to BMW now, what is still open, and who owns it?` | SGFX prepares evidence and copy-ready handoff material; Jira posting and approval stay outside the main path. |

Every central item must reduce a real lookup, duplicate entry, ambiguous ownership handoff, or evidence-reconstruction step. If it cannot answer `what failed`, `where is the proof`, `who owns it`, or `what is the next safe action`, it stays in a specialist surface or out of the product.

## 3. Current SGFX reality

### What already exists

- `services.execute_profile_run` resolves and materializes a selected profile, runs `anchors`, `constants`, `carpaints`, and `project_sanity`, then writes JSON, HTML, Markdown, and a run record.
- `RunProfile` already carries a safe subset of context: profile ID/label, brand, lane, build/retarget type, optional interface version, retarget target, active-build state, and registry source.
- The Qt Quick shell already owns Home, profile selection, route validation, reduced motion, five navigation groups, all 19 surface descriptors, one maximum-two-reader coordinator, stale-result rejection, an exact eight-capability inventory, a dedicated effect worker, and opaque artifact handling.
- The existing SGFX C++ viewer resolves a selected profile to an available `exported.ramses`, preserves the authored Ramses pass graph, drives the exported camera-crane interface for QA perspectives and orbit, and can read back a real rendered frame. The cinematic proof already uses a render-on-demand local texture cache rather than a perpetual shell-frame readback.
- The current `sgfx::cine` library contains a small Ramses link probe, while the proven metadata, inventory, logic, lifecycle, and readback logic still lives in the real-scene and cinematic app files. The companion Ramses design grows that existing boundary by extraction; it does not create another renderer.
- The local C++ track pins Ramses 28.16.0 and has loaded a real Ramses 28.15.1/exporter 2.9.0/feature-level-2 scene. That is evidence for the current profile only, not a universal compatibility promise.
- The repository already carries Inter and Fredoka font files with SIL Open Font License 1.1 texts. The local Unleashed font files are not part of this product boundary and are not distributable through SGFX without separate proven licensing.
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

### Selected: one product with presentation and inspection drill-downs

There is no visible Clean/Grafiks mode choice. Grafiks' strongest original SGFX interaction work—spatial focus, decisive selection feedback, depth, scene-like transitions, contextual vehicle presentation, and restrained motion—is independently carried into the Qt/QML product. Presentation view is the same data with less chrome. Full 3D inspection is an explicit focused destination using the same canonical profile; returning restores the same QA context.

The existing external Grafiks/cinematic executable remains preserved as R&D/reference until its migration ledger classifies each part as original product contract, independently portable interaction behavior, or provenance-sensitive reference-only material. The product-facing inspector may reuse only the audited SGFX-owned Ramses viewer core, SGFX brand assets, and license-cleared dependencies.

### Selected: hybrid Ramses-native observatory behind the same evidence model

SGFX will use a narrow public-API C++ probe for structured scene/logic/renderer evidence, Python for canonical profile resolution and evidence normalization, and official RaCo/viewer/GPU tools only in separately gated specialist phases. The current Control Center plan supplies the integration seam; the companion design owns R0–R5 scope and graduation.

This avoids fragile log-only wrappers without duplicating Ramses. It also keeps deep diagnostics out of startup and Home until a specific finding or explicit operator action needs them.

### Rejected: car-first showroom or launcher

A large car-first showroom spends the most valuable space on an object that does not explain source correctness, failures, evidence, ownership, or the next QA action. A compact real-car turntable is retained only as selected-scope context and must yield space to the action and pipeline.

### Rejected: two visible UI modes

Two modes teach occasional operators that there may be two workflows or two truths, duplicate polish work, and make Grafiks look like an optional novelty. Presentation and 3D inspection are destinations inside one product, not alternate shells the operator must choose between.

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
11. **Reduce work, not merely clicks.** Central surfaces collapse evidence lookup, duplicate entry, ownership discovery, and handoff reconstruction without hiding missing evidence.
12. **Presentation never changes truth.** Reduced chrome, motion, and the real-car preview may improve focus, but cannot change capabilities, gate state, or evidence.
13. **Layered provenance.** Documented requirements, SDK-native opportunities, and research candidates are labelled separately and never presented as equivalent authority.
14. **Deep diagnostics are earned.** A candidate enters the daily one-button plan only after read-only isolation, false-positive, performance, and operator-value gates pass.

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
- Full 3D inspection and profile-scoped routes remain unavailable until a canonical profile is selected.

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

### Operator-value contract

The Control Center produces one concise, copy-ready evidence summary over the seven gates. It contains the canonical profile, accepted source fingerprint when available, latest deterministic findings, evidence provenance, named owners for open human/external gates, retest hash when recorded, and the exact next safe action. It contains no synthetic readiness score and does not post to Jira.

The first teammate pilot records a before/after baseline without telemetry or invented targets:

- time from usable app shell to the first intended QA action;
- time from a completed local preflight to the first actionable finding;
- number of separate surfaces or manual searches needed for the standard profile check;
- duplicate values manually re-entered while preparing a delivery/handoff note;
- presence of profile/source identity, finding, provenance, owner, and next-action fields in the resulting evidence summary; and
- elapsed operator time to prepare copy-ready BMW ticket or handoff material.

Measurements are local and opt-in or observed during the team pilot. SGFX may claim reduced workload, cognitive load, or ticket-preparation time only after the pilot demonstrates it; the design intent itself is not proof of improvement.

## 9. State semantics

The safe state vocabulary is closed and tested:

| State | Meaning | Allowed source |
|---|---|---|
| `selection_required` | No canonical profile is selected. | Shell selection state |
| `available` | The gate or action can be opened/run; no result is implied. | Registry/capability readiness |
| `not_checked` | No accepted persisted result exists for this profile. | Local history absence |
| `queued` | The safe local action is accepted but has not started. | Capability lifecycle |
| `running` | The safe local action is executing. | Capability lifecycle |
| `passed` | An exact deterministic SGFX check completed with zero errors and zero warnings inside its named scope. | Exact accepted check summary |
| `findings` | An exact deterministic SGFX check completed with warnings and no errors inside its named scope. | Exact accepted check summary |
| `failed` | An exact deterministic check reported errors or its action failed to execute. | Run/action record |
| `blocked` | Required local source/config or execution prerequisite is unavailable. | Audited action readiness |
| `evidence_required` | This gate needs an artifact or result SGFX has not accepted. | Gate contract |
| `human_required` | This gate requires a named human or external decision. | Gate contract or explicit review record |
| `unavailable` | The related surface or source cannot be used on this workstation. | Accepted reader/capability state |
| `not_applicable` | An explicit profile/config contract marks the gate irrelevant. | Explicit configuration only |
| `stale` | A persisted result is proven to target a different source/profile fingerprint. | Exact identity mismatch only |

Clock age alone does not create `stale` in this slice because no accepted universal freshness threshold exists. Until an exact fingerprint is available, Home shows the run timestamp without inferring staleness.

`passed` is never an overall profile, delivery, screenshot, manual-review, rack, or stakeholder verdict. In C0 only the exact four-pack summary can produce `passed` or `findings`; a later accepted R0 integration may use the same vocabulary only on its exact named check rows. The hub has no overall green state and no completion percentage.

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
- Help and All tools access; and
- optional `Presentation view`, which changes chrome only and is governed by the same controller state.

### Primary focus

- headline `Quality starts here`;
- one sentence explaining local checks, evidence, review, and delivery;
- one primary action from the next-safe-action contract;
- one secondary `How this works` action; and
- a compact contextual preview area.

Before selection, or whenever the audited renderer or readable source is unavailable, the preview uses an original generic vector silhouette. After an explicit profile selection and after the QA snapshot is ready, a separate below-normal-priority preview worker may render a bounded turntable from that profile's real local `exported.ramses`. A restored startup preference may reuse an already valid cache but must not start a new renderer during startup.

The turntable contract is deliberately finite:

- preserve the authored Ramses pass graph and use the exported camera-crane interface;
- render at most 24 low-resolution frames at no more than 480 × 270;
- play one approximately four-second revolution, then stop on the canonical three-quarter frame;
- replay only after explicit preview focus/activation, and allow Left/Right or pointer drag to scrub frames;
- show only the static canonical frame when reduced motion is active;
- pause frame playback while the preview is hidden, the window is inactive, or a diagnostic starts; and
- never use direct camera mutation as a Home fallback; if the authored interface or compatible scene is unavailable, show the generic static fallback.

The worker resolves the canonical profile through Python-owned registry logic. QML receives only an opaque preview token, safe state, frame count, and human-readable label. It never receives the scene path, source root, helper command, process handle, or unrestricted image location. Profile-generation checks reject stale frames before display.

The Ramses scene stays read-only and is never copied into SGFX. Derived preview frames live only in a size-capped local SGFX cache beneath the approved output root, remain untracked and undistributed, are excluded from evidence bundles and exports, and are invalidated by the scene fingerprint. One preview job may exist at a time; it is cancelled or discarded on profile change, diagnostic start, timeout, shutdown, or renderer failure. Failure is quiet and local: the generic silhouette returns with `Real preview unavailable`, while all QA actions remain usable.

The preview has no readiness color, no copied BMW or game asset in the package, no model-specific fallback, and no interaction required to complete QA. Its render success, frame count, freshness, or absence never changes a gate or next action.

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

The sidebar retains Home and the existing five navigation groups: Daily work, Delivery, Screenshots & coverage, Reviews & digests, and Setup & help. All tools remains a shell control. `Open 3D inspection` is a contextual preview drill-down and the product-facing label for the existing internal `grafiks.launch` capability; it is not a mode toggle, navigation group, or twentieth operational surface. All 19 descriptors remain reachable through the sidebar and `/`.

Presentation view hides the sidebar and compresses the context rail while keeping the same selected profile, selected gate, evidence, actions, and capability permissions. Esc restores normal chrome and focus. Entering or leaving Presentation view never reloads data or starts a renderer.

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

The companion Ramses R0 work does not alter this C0 contract. `sgfx_preflight` stays exactly four-pack until the standalone R0 probe and its separate integration slice pass. That later slice may add a conditional, SGFX-owned `ramses_r0` child stage under the same parent action without adding a capability or Home control; it may not relabel the existing external RaCo `scene_check` as safe.

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

Preview presentation is not part of QA state. A separate controller-owned channel may expose only `previewState`, an opaque current-generation image-provider token, bounded frame count, selected frame index, and safe label. None of those fields can reduce a gate or participate in the next-action reducer.

Home receives no raw path, command preview, subprocess output, exception text, credential state, external or filesystem URL, network client, source object, or unrestricted controller reference. Generated artifacts remain protected by the existing opaque-handle flow on the detailed run surface; the first Home slice navigates to that surface rather than revealing paths directly. Internal `image://` provider keys are controller-issued opaque presentation tokens, not artifact paths.

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
- A small `QaContextPreview.qml` owns generic scope art, opaque preview-frame playback, scrub input, visibility pausing, and reduced-motion behavior.
- A Python-side `PreviewCoordinator` owns canonical profile resolution, one below-normal-priority worker, scene fingerprinting, stale-generation rejection, cache limits, timeout, and diagnostic pre-emption. It exposes no path or process to QML.
- A narrow C++ preview helper is extracted from the existing SGFX Ramses viewer core. It preserves the authored pass graph and camera-crane interface and emits only bounded local turntable frames plus a machine-readable manifest beneath the approved cache root.
- The extraction keeps metadata, lifecycle, and frame-production units compatible with the companion R0 probe contract, but C0 emits preview presentation only and does not claim Ramses QA validation.
- `Main.qml` owns shell chrome, overlays, profile selection, controller invocation, and registered navigation.
- The existing presenter/renderers own the detailed Full QA page.
- `Theme.qml` owns the minimal color, type, spacing, motion, and reduced-motion tokens required by the design.

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
10. An explicit profile selection may schedule preview work only after the current snapshot is ready; restored startup state may read a valid cache but does not start the renderer.
11. Starting a diagnostic cancels or pre-empts preview generation and stops preview playback before the diagnostic enters `running`.

Malformed snapshot fields fail to a neutral `Local QA state unavailable` view while navigation and profile selection remain usable. Raw exception messages, paths, and commands never become Home copy.

A validator finding is not an application crash. Execution failure, deterministic errors, warnings, blocked prerequisites, missing evidence, and human review are displayed as distinct states.

## 18. Visual language

SGFX has one professional daily-driver visual system. It combines the Control Center's calm information density with independently implemented cinematic focus, depth, and transition qualities from the strongest Grafiks work.

- graphite canvas with layered neutral panels;
- mint/aqua for focus, selection, and the safe primary action;
- amber for findings, missing evidence, and human attention;
- red for deterministic errors or execution failure;
- green only for a completed zero-error/zero-warning SGFX deterministic result;
- strong type hierarchy, thin structural lines, calm spacing, and short copy;
- no fake telemetry, completion rings, decorative percentages, or marketing badges;
- Inter for operational text and data, with Fredoka restricted to the product mark, major profile/scene labels, and short display accents; both come from the repository's existing SIL Open Font License 1.1 assets;
- no network font, restricted local DynaFont, game font, new image pack, copied icon set, shader, web asset, or unreviewed production dependency; and
- no copied BMW infotainment, Nintendo, SEGA, Valve, Sonic, or other third-party layout or asset.

Game-menu and in-car influence is limited to abstract interaction qualities: one central focus, decisive selection feedback, spatially stable navigation, readable hierarchy, layered depth, and a compact command guide.

The local Unleashed installer implementation is a behavior reference only. SGFX independently implements the general choreography of structure first, focus/title second, and content third. No installer code, exact coordinate system, shader, artwork, sound, music, restricted font, or proprietary game asset enters SGFX. GPL-licensed reference code is not copied into the proprietary/internal product.

## 19. Motion, input, and accessibility

- Tab reaches profile selection, primary action, all gates, check rows, rail actions, and navigation.
- Left/Right moves between gates; Enter/Return/Space selects or opens.
- Focus is visible beyond color alone.
- Status is always written in text.
- Accessible names include gate, check, state, and destination.
- F1, F2, F5, F12, `/`, and Esc retain their current meanings.
- Reduced motion removes car movement, entrance stagger, and nonessential travel while retaining immediate focus and state feedback.
- Motion never delays action availability or changes semantic state.
- The shell is usable on its first stable frame; there is no non-skippable splash or installation-style wait in the daily tool.
- Initial structure/focus/content staging completes within 700 ms with a 45–70 ms item stagger. Focus and selection feedback use 120–180 ms; local panel changes use 220–320 ms; route and Presentation transitions use 420–560 ms.
- Refreshing evidence in place does not replay the full entrance. Major route, Presentation, and 3D-inspection transitions may use the longer token once per navigation event.
- Progress animation follows actual queued/running/completed state or a real backend progress value. Spinner, pulse, or sweep motion appears only while work is active; no fake percentage or timer-driven progress is permitted.
- The real-car turntable is the only allowed idle scene motion, runs for one revolution, then freezes. It does not loop continuously.

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
- Preview work uses a separate one-job below-normal-priority worker, starts only after an explicit selection and ready snapshot, and yields to diagnostics.
- Preview output is capped at 24 frames, 480 × 270 per frame, and a 256 MiB least-recently-used cache under the allowed SGFX output root. A 30-second generation timeout fails to the static fallback.
- The renderer process exits after generation; the Home page never performs continuous Ramses readback or keeps a hidden renderer alive for decoration.
- Preview playback stops when hidden or inactive, and reduced motion loads one frame only.
- Source roots are verified unchanged around the safe diagnostic.
- Output remains under the allowed SGFX output root.
- Home profile selection remains session state in this slice and adds no preference write.
- No Jira/network action, SVN mutation, BMW-source write, Git push, package publish, delivery, or external approval is introduced.
- The internal `grafiks.launch` capability remains optional and provenance-gated, but its product-facing label is `Open 3D inspection`; no visible mode toggle remains.
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
7. one-product shell copy plus same-data Presentation view;
8. the render-on-demand real-car preview adapter, bounded cache, and generic fallback;
9. the audited `Open 3D inspection` drill-down over the existing external-process capability;
10. clean-room motion tokens and the existing OFL typography assets;
11. rendered interaction/accessibility verification; and
12. exact-tree source, package, cache, provenance, and performance regression gates.

The implementation plan keeps the QA truth path independently shippable: profile neutrality, safe preflight, snapshot, and gate presentation must be GREEN before preview generation is enabled. Preview or inspector failure cannot delay or roll back the QA-first slice.

### Ramses program handoff

C0 does not implement or auto-run the Ramses R0 validator. It establishes:

- one canonical profile and source identity;
- one parent action/lifecycle model;
- protected output and artifact-handle boundaries;
- an extraction-compatible preview helper;
- exact gate/check-row slots for future accepted Ramses evidence; and
- a UI that can display `unavailable`, `findings`, or evidence without inventing an overall verdict.

R0 is the immediate next implementation cycle under `plans/2026-07-12-sgfx-ramses-qa-observatory-design.md`. Once R0 passes standalone gates, its integration slice may run it as a conditional SGFX-owned child of the same explicit action. R1–R5 each retain separate specification, planning, and graduation gates.

It does not implement these BMW-evidence gaps yet:

- a generalized trimline/drivetrain/equipment/roof/light variant matrix;
- carpaint design-review, CAF, CarLib, productive-state, SOP/EOP, and model-association coverage;
- deterministic TAA/animation capture control or a new comparator threshold;
- structured VRAM/GPU/CPU/size/loading/startup/baseline/min/max performance records;
- live rack, car, Artifactory, CI, Gerrit/CCB, Jira, or stakeholder integrations;
- explicit per-role PM, LightFX, TA, Design, Wombat, or CCB signoff records;
- new MINI/Rolls-Royce profile creation where source coverage is not locally proven; or
- a continuous real-time renderer inside Home, an unbounded animated preview, or copied infotainment/game UI.

Those are evidence-backed follow-on slices. Home may expose their absence and route to existing evidence, but it may not fabricate implementation or completion.

## 23. Verification and acceptance

Implementation follows RED → minimal implementation → GREEN → rendered interaction inspection → diff review.

Acceptance requires:

1. One SGFX product visibly centers QA context, one safe local action, seven ordered gates, latest local evidence, and the next truthful action; no Clean/Grafiks mode choice remains.
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
20. The final diff contains no unrelated cleanup, unapproved mandatory dependency, prohibited attribution, confidential dump content, absolute private path, or third-party asset.
21. Presentation view retains the exact profile, gate, evidence, action descriptors, and permissions; entering or leaving it performs no data reload or renderer launch.
22. A selected profile with a compatible resolved local scene can produce a real Ramses turntable through the authored pass graph and camera-crane interface; an unselected, unsupported, missing, timed-out, or failed scene shows the generic fallback without affecting QA.
23. QML receives no BMW scene/cache path or helper command. Preview tokens are current-generation and opaque; stale-profile frames are rejected.
24. The preview reads BMW source only, writes derived frames only beneath the bounded SGFX cache, never packages, exports, bundles, or commits the scene or frames, and proves the source tree unchanged.
25. Preview tests enforce one worker, below-normal execution, diagnostic pre-emption, 24-frame/480 × 270/256 MiB/30-second limits, process exit after generation, and quiet fallback.
26. Normal motion performs one finite turntable revolution and then freezes; reduced motion uses one static frame; hidden or inactive presentation performs no playback work.
27. Operational copy uses Inter and display accents use the existing OFL Fredoka asset. Package/provenance scans reject restricted DynaFont, game fonts, copied installer/game assets, external web assets, and unaudited Grafiks material.
28. Motion tests enforce the defined focus, panel, route, staging, reduced-motion, and real-progress contracts without delaying action availability.
29. `Open 3D inspection` retains the internal `grafiks.launch` capability ID and exact canonical profile input, restores the prior QA context on return, and exposes no second state model.
30. The teammate pilot records the local before/after operator-value measures and reports them as observed evidence; no productivity or ticket-speed claim is emitted from design intent alone.
31. C0 contains no Ramses R0 auto-run, RaCo invocation, cross-backend comparison, validation-layer activation, RenderDoc capture, performance capture, or research-candidate execution; the exact four-pack action remains mechanically provable until the companion R0 integration is separately accepted.

## 24. Explicit open evidence boundaries

- The May 2026 local Confluence catalogs are exhaustive for their captured manifests, not current live-service truth.
- The corpus does not define one universal screenshot acceptance threshold.
- Current screenshot automation scope conflicts by layer and date; Home must show provenance instead of resolving that conflict by assumption.
- Current performance pages establish what to measure, not one universal pass threshold.
- Warm and first-run acceptance on the exact current tree remains open under workstation load.
- External approvals remain outside SGFX until separately designed, authorized, and evidenced.
- The real-car preview is proven for compatible locally available Ramses exports, not every present or future profile; unsupported profiles retain the generic fallback.
- The local Unleashed installer and restricted font files are reference material, not product dependencies or redistributable assets.
- The operator-value baseline has not yet been measured with the Seriengrafik team; reduced workload, cognitive load, and BMW ticket-preparation time remain hypotheses until that pilot.
- The companion Ramses program is approved as a direction, but R0–R5 remain separate implementation claims. This document cannot be cited as evidence that any Ramses validator, cross-backend check, performance fingerprint, guided review, or GPU diagnostic already exists.

These OPEN items are acceptance constraints, not placeholders. No unresolved design choice blocks the written-spec review.
