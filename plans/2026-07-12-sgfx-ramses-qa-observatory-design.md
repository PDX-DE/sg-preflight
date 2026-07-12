# SGFX Ramses QA Observatory — Program Design

Status: approved direction; written-spec review required before implementation planning

Date: 2026-07-12

Design baseline: `feature/sgfx-v02-qt-integration-20260710@6600f93`

Production-code baseline: `a736826`; later commits changed documentation only

Companion product design: `plans/2026-07-12-sgfx-qa-control-center-design.md`

## 1. Outcome

Turn the locally installed Ramses and Ramses Composer toolchain into a structured, read-only 3D QA evidence system behind the single SGFX QA Control Center.

The finished program must let a Seriengrafik teammate select one profile, start one safe local QA run, and receive:

1. the existing deterministic SGFX asset findings;
2. exact Ramses export identity and compatibility evidence;
3. object-linked scene and logic validation findings;
4. renderer-lifecycle and first-visible-frame evidence;
5. a classified explanation when a scene does not render;
6. the affected gate, object, perspective, variant, or artifact when that relationship is proven;
7. the next safe automated or human action;
8. copy-ready evidence without Jira posting; and
9. explicit separation between completed automation, missing evidence, and human or external approval.

The normal operator still sees one product, one selected profile, one primary action, seven gates, and progressive disclosure. Ramses is an evidence substrate, not another Home page, mode, capability set, or competing truth.

## 2. Program decomposition and order

The full goal spans independent subsystems and must not become one mega-change.

| Phase | Cohesive result | Planning boundary |
|---|---|---|
| `C0` | QA Control Center truth path, profile neutrality, four-pack safe preflight, evidence spine, preview, and inspection handoff | Existing companion design and its own ExecPlan |
| `R0` | Ramses metadata, native validation, structural manifest, logic/lifecycle smoke, authored-frame evidence, and black-frame classification | First Ramses spec and ExecPlan |
| `R1` | Read-only RaCo authoring audit, interface and trace scenarios, animation checks, and logic profiling | Separate accepted spec and ExecPlan |
| `R2` | Backend/shader portability, perceptual and temporal visual assistance, and diagnostic 3D lenses | Separate accepted spec and ExecPlan |
| `R3` | Contextual performance fingerprints over Ramses, platform, and accepted trace evidence | Separate accepted spec and ExecPlan |
| `R4` | Semantic change/impact graph, coverage heatmap, object history, guided 3D review, and copy-ready root-cause summary | Separate accepted spec and ExecPlan |
| `R5` | Scratch fault injection, lifecycle endurance, failure-triggered GPU validation/capture, and minimal-reproduction assistance | Separate accepted spec and ExecPlan |

`C0` establishes the safe UI and evidence truth path first. `R0` follows immediately and may share a release milestone, but it remains independently testable and reversible. `R1`–`R5` cannot be pulled into an earlier plan merely because the public API exists.

“One button” means every graduated, SGFX-owned, local, bounded, read-only stage can run from one explicit operator action. It does not mean automatically starting experimental tools, source-mutating scripts, BMW export commands, RaCo authoring operations, rack work, Jira, SVN, CI, or delivery.

## 3. Verified local ground truth

- The workstation's `ramses-28.16.0-install` installation provides the Ramses 28.16 public headers, libraries, renderer, and tools used by the current C++ track.
- The locally mirrored Ramses Composer 2.9.0 changelog records Ramses 28.15.1, while the current SGFX C++ target pins Ramses 28.16.0.
- The proven local export metadata is Ramses 28.15.1, exporter 2.9.0, feature level 2, loaded through the 28.16.0 SDK.
- `cpp/apps/ramses_real_scene.cpp` already reads scene metadata, loads the real export, inventories scene objects, preserves authored render passes, updates `LogicEngine` objects, drives `Interface_CameraCrane`, reaches `RendererSceneState::Rendered`, and performs `readPixels`.
- `cpp/apps/cinematic_shell.cpp` already contains a bounded render-on-demand offscreen path and the authored-perspective turntable proof.
- `cpp/include/sgfx/cine/ramses_probe.h` and `cpp/src/ramses_probe.cpp` currently prove only framework linkage. They are the correct library boundary to grow; the inspection logic should be extracted from the app files instead of duplicated.
- The C++ build already pins `nlohmann_json`; a JSON report does not require a new production dependency.
- Ramses 28.16 exposes object validation reports, issue severity/message/object origin, scene metadata, scene iteration, logic update reports, scene states, versioned flush acknowledgements, offscreen buffers, readback, data linking, picking, upload timing controls, and periodic performance logs.
- The Qt shell already has an exact eight-capability inventory, one effect executor, stale-identity rejection, opaque artifact handling, and a protected `diagnostic.run` seam.
- `sg_preflight/checker_evidence.py` already normalizes severity, checker, rule, subject path, evidence, follow-up, and source kind for existing tools. Ramses evidence should extend that model rather than create a second reporting universe.
- The companion Control Center design maps the fully reconciled local BMW/PDX corpus into seven gates and preserves the captured May 2026 versus live-current authority boundary.

## 4. Primary-source research foundation

Public research supplies architecture and candidate techniques. It does not create BMW requirements.

| Primary source | Verified capability or lesson | SGFX consequence |
|---|---|---|
| [Ramses viewer](https://ramses-sdk.readthedocs.io/en/latest/viewer.html) | The official viewer is intended to inspect binary scenes, exercise logic inputs, execute Lua tests, and capture screenshots; headless mode omits rendering. | Reuse official behavior contracts and keep logic-only versus rendered evidence distinct. |
| [Ramses Core](https://ramses-sdk.readthedocs.io/en/latest/core.html) | Client validation finds expensive scene issues; renderer state changes are asynchronous and may produce no event when prerequisites are unmet. | Use object-linked findings and application-owned phase timeouts; never wait forever or equate no callback with success. |
| [Ramses Logic](https://ramses-sdk.readthedocs.io/en/stable/logic.html) | Logic update reports expose executed/skipped nodes and timings, and scene validation is recommended alongside logic validation. | Profile real scenarios over several updates and preserve scene/logic findings as separate evidence. |
| [Ramses profiling](https://ramses-sdk.readthedocs.io/en/latest/profiling.html) | RPER logs expose flushes, object/resource counts and sizes, update peaks, frame time, draw calls, uploads, and VRAM/cache data. | Build contextual performance fingerprints instead of inventing one threshold. |
| [Ramses version compatibility](https://ramses-sdk.readthedocs.io/en/main/versions.html) | The ecosystem recommends matched toolchain versions and records compatibility/migration caveats. | Record Composer, exporter, Logic, Ramses, feature level, and backend in every report; classify drift rather than assuming compatibility. |
| [RaCo Python API](https://ramses-composer.readthedocs.io/en/latest/advanced/python_api/README.html) | RaCoHeadless can report errors and enumerate instances, links, external projects, feature levels, properties, and object identities, but the same API can mutate projects. | R1 uses an audited read-only script, source hashes, and scratch copies for any operation capable of writing. |
| [RaCo export](https://ramses-composer.readthedocs.io/en/latest/basics/export/README.html) | GUI export shows Ramses validator errors/warnings; published headless documentation warns that export may overwrite and may not perform the same visible validation. | Never treat export exit status alone as validation; verify the installed binary and run explicit validation. |
| [RaCo TracePlayer](https://ramses-composer.readthedocs.io/en/stable/advanced/traceplayer/README.html) | Captured traces and predefined state sequences can drive named interface properties for debugging and scene validation. | R1 turns curated traces into reproducible scenario evidence and coverage, not unbounded random input. |
| [Vulkan validation](https://docs.vulkan.org/guide/latest/validation_overview.html) | Validation catches invalid Vulkan usage but is development-only and materially affects performance. | R5 enables it only in an isolated SGFX diagnostic build or failure rerun; never ship it enabled. |
| [Vulkan Profiles](https://docs.vulkan.org/guide/latest/vulkan_profiles.html) | Profiles describe required features, formats, extensions, and limits for classes of devices. | R2 can compare against a team-supplied target profile; absence of a target remains `Not recorded`. |
| [SPIR-V Tools](https://github.com/KhronosGroup/SPIRV-Tools) and [glslang](https://github.com/KhronosGroup/glslang) | Khronos supplies reference shader front-end, SPIR-V validation, reduction, and fuzzing tools. | R2 validates generated modules when available; R5 may minimize a failing shader in scratch without modifying source. |
| [glTF Validator](https://github.com/KhronosGroup/glTF-Validator) | The validator emits JSON issues and asset statistics for schema, references, buffers, NaN values, transforms, animations, images, and extensions. | R1/R2 may ingest upstream glTF reports when the source asset exists; no new glTF requirement is invented. |
| [OpenUSD Validation Registry](https://openusd.org/dev/api/class_usd_validation_registry.html) | Validators and suites carry metadata, object/error sites, categories, and optional fixers. | Borrow the registry/suite and object-site pattern; do not add an OpenUSD dependency or auto-apply fixes. |
| [NVIDIA FLIP](https://github.com/NVlabs/flip) | FLIP produces perceptual error maps for rendered-image comparison. | R2 may offer a review-assistance map after licensing and false-positive evaluation; it cannot define a universal pass threshold. |
| [NIST combinatorial testing](https://csrc.nist.gov/Projects/automated-combinatorial-testing-for-software/faqs) | Covering arrays can exercise t-way parameter interactions with far fewer cases than the full Cartesian product. | R1 may generate constrained interface/variant scenarios only from a reviewed input model and report exact coverage strength. |
| [RenderDoc](https://github.com/baldurk/renderdoc) | RenderDoc captures and replays SGFX-owned OpenGL/Vulkan programs; its in-application API can delimit offscreen work. | R5 captures only a failing or explicitly requested SGFX frame and keeps capture/replay compatibility evidence. |
| [Perfetto metrics](https://perfetto.dev/docs/analysis/metrics) | Trace Processor turns existing traces into repeatable CPU, memory, startup, and custom metrics. | R3 reads accepted target traces when supplied; it does not silently start rack/ADB capture. |

## 5. Architecture decision

### Selected: hybrid Ramses-native evidence adapter

Use a narrow SGFX C++ probe for structured SDK evidence, the existing Python action/evidence system for orchestration and normalization, official tools for their specialized roles, and one Control Center state model.

The probe owns no policy about BMW approval. It reports facts and typed failures. Python maps those facts to SGFX gates, provenance, safe next actions, and protected artifacts.

### Rejected: command-line wrapper only

Wrapping viewer and RaCo output is useful for a prototype but leaves object identity, lifecycle phase, compatibility, and failure taxonomy dependent on unstable prose logs.

### Rejected: new custom renderer or scene format

Reimplementing Ramses duplicates the production renderer, creates a false oracle, expands maintenance and packaging risk, and does not improve the documented operator workflow.

### Rejected: always-on deep diagnostics

Continuous rendering, validation layers, RenderDoc, broad RaCo scans, full trace replay, and exhaustive variants would degrade startup, consume workstation resources, and overwhelm occasional operators.

## 6. Product invariants

1. One product and one evidence model.
2. Home remains `select → run → review → close`.
3. No new front-of-tool page or capability is created for Ramses.
4. Every claim identifies its source class and exact evidence.
5. Scene, project, and BMW source roots are read-only.
6. No automatic baseline update, source fix, export, delivery, approval, or Jira post.
7. Missing evidence stays missing.
8. Advanced diagnostics appear only after a relevant finding or explicit operator request.
9. A rendering failure cannot block the four existing deterministic packs.
10. A clean R0 probe is not an overall QA, visual, rack, performance, stakeholder, or delivery pass.
11. The packaged product can operate without the optional Ramses helper; degradation is explicit and local.
12. Research candidates graduate only after feasibility, isolation, false-positive, performance, and operator-value evidence.

## 7. Provenance classes and graduation

Every validator or finding declares one class:

- `DOCUMENTED_REQUIRED`: directly supported by an exact local BMW/PDX process need.
- `SDK_NATIVE_OPPORTUNITY`: enabled by public Ramses/RaCo APIs and clearly reduces an existing evidence gap.
- `RESEARCH_CANDIDATE`: derived from public engineering research or another validator ecosystem and not represented as a BMW requirement.

A candidate may become part of the safe one-button plan only when:

1. the input and output contracts are deterministic and versioned;
2. execution is local, bounded, read-only, and cancellable before start;
3. source before/after fingerprints prove isolation;
4. false positives and unsupported cases are measured on representative profiles;
5. workstation cost is measured;
6. the finding has a clear owner and next action;
7. at least one teammate pilot demonstrates reduced lookup, diagnosis, or handoff work; and
8. Jana's no-front-complexity rule still holds.

## 8. Normalized Ramses evidence contract

`RamsesProbeReport` is a versioned JSON artifact beneath the approved SGFX output root:

```text
schemaVersion
probeVersion
profileId
sourceFingerprint
startedAt
completedAt
environment
sceneMetadata
phases[]
inventory
logic
lifecycle
firstFrame
findings[]
artifacts[]
sourceMutationCheck
```

`environment` records SGFX commit, probe build digest, Ramses/Logic/exporter/Composer versions when known, feature level, backend, OS, GPU/driver identifiers when available, display/offscreen settings, and the exact scenario ID. Unknown fields are explicit.

Each finding contains:

```text
findingId
ruleId
provenanceClass
severity
message
subject
evidenceRefs[]
affectedGateIds[]
nextActionId
confidence
```

`subject` may identify a scene, Ramses object type/id/name, logic engine/node/property, render pass/target, camera/perspective, resource, or lifecycle phase. Names are not assumed unique. A scene object ID is stable only within the exact source fingerprint.

Cross-run object history uses a separate semantic signature and confidence. Low-confidence matches are not linked automatically. Home receives only safe summaries and opaque artifact handles; detailed reports may retain local paths only inside protected output artifacts.

Finding IDs are deterministic from report version, rule, exact source fingerprint, and exact subject identity. Changing tool version or source fingerprint creates a new evidence identity rather than silently reusing an old verdict.

## 9. R0 components

### `sgfx::cine::RamsesProbe`

Grow the existing small library target into focused metadata, validation, inventory, logic, lifecycle, and authored-frame units. Extract proven code from `ramses_real_scene.cpp` and `cinematic_shell.cpp`; do not duplicate or broadly refactor unrelated cinematic UI code.

### `sgfx_ramses_probe`

A narrow noninteractive executable accepts validated scene/perspective input paths, canonical profile ID, output directory, scenario ID, one strict configured backend value, dimensions, and timeout contract from the Python adapter. R0 runs one backend; selecting and comparing two backends belongs to R2. The helper emits one JSON report and bounded diagnostic artifacts. It accepts no arbitrary command or output path from QML.

### `ramses_probe_adapter.py`

Python owns canonical profile/scene resolution, helper provenance, safe argument construction, process lifecycle, timeout, output-root validation, JSON-schema validation, source before/after fingerprinting, and normalization into existing checker evidence.

### Action orchestration

`qa_actions.py` remains the only action executor. It records core preflight and R0 as separate stages under one parent action after R0 graduates. A failed or unavailable R0 stage cannot erase completed four-pack evidence.

### Evidence reduction

`qa_hub.py` maps only accepted report fields to exact check rows. It does not parse console prose, infer approval, calculate an overall score, or expose raw paths.

## 10. R0 data flow

1. The operator explicitly starts the current canonical profile action.
2. Python runs the four mandatory deterministic packs.
3. If the packaged R0 helper and a canonical compatible local export are available, Python creates a current-generation R0 stage.
4. Python hashes every exact input file passed to the helper, records a before-status snapshot for the containing Git worktree when available, and proves that the output root is disjoint from all source roots.
5. The helper reads metadata before loading and creates the framework at the scene feature level.
6. The helper loads the scene without editing or saving it.
7. Native Ramses validation produces typed issues tied to originating objects where available.
8. The helper emits a structural and resource manifest.
9. Logic engines update once at authored/default state with update reporting enabled; errors and cycles become findings.
10. The helper sets up the authored display/pass/camera contract, maps the scene, and observes lifecycle events with application-owned deadlines.
11. If the exported camera-crane interface and canonical authored perspective exist, the helper drives that exact contract; direct camera mutation is not an R0 fallback.
12. The helper reads one bounded authored frame and classifies the first failing phase or visible-frame outcome.
13. JSON and bounded artifacts are written atomically beneath the supplied output root.
14. Python re-hashes every passed input, compares the optional worktree status snapshot byte-for-byte, and validates the report, paths, source fingerprint, helper digest, profile identity, and generation.
15. The parent action persists separate core and R0 results.
16. Home refreshes current evidence; a stale completion remains on disk but cannot replace current UI state.

## 11. R0 checks

R0 contains only:

- scene presence, size, digest, and readable metadata;
- Ramses/exporter version and feature-level compatibility evidence;
- native scene validation issues with object origin when available;
- counts and names for scene objects, nodes, mesh nodes, cameras, render passes, render groups, render targets/buffers, resources, data objects, pickables, scene references, and logic engines where the public API exposes them;
- duplicate/empty-name facts without assuming names must be unique;
- non-finite transform, camera, viewport, and bounds findings where values are publicly readable and the rule is exact;
- authored framebuffer/pass/camera contract facts;
- one default-state logic update, dependency-cycle/runtime failure, total update time, executed/skipped node counts, and slowest-node evidence;
- lifecycle phase requests/events/timings through Available, Ready, and Rendered;
- versioned flush acknowledgement when applicable;
- one bounded authored-perspective readback whose local frame is excluded from packages, handoffs, commits, and exports by default;
- first-frame pixel statistics sufficient to distinguish readback failure from clear-only output;
- helper/tool/environment provenance; and
- source before/after mutation proof.

Warnings remain warnings. Unsupported inspection fields remain unsupported. R0 does not infer that an unused-looking object is defective without an exact rule.

## 12. Black-frame and non-render classification

Native validation findings remain an orthogonal finding set because a scene may contain validation errors and still produce a frame. The render-outcome classifier reports `visible_frame_observed` when a visible frame exists. Otherwise it reports the first proven blocking or missing phase and preserves validation findings plus all preceding evidence:

1. `scene_unresolved`;
2. `metadata_unreadable`;
3. `toolchain_incompatible`;
4. `scene_load_failed`;
5. `logic_update_failed`;
6. `display_or_offscreen_setup_failed`;
7. `scene_available_timeout`;
8. `scene_ready_timeout`;
9. `scene_rendered_timeout`;
10. `authored_pass_or_camera_contract_missing`;
11. `readback_request_failed`;
12. `readback_timeout`;
13. `clear_only_frame`; or
14. `visible_frame_observed`.

The classifier never replaces native error messages. It adds a stable phase code, safe explanation, evidence references, and next action. If more than one cause is plausible and evidence cannot rank them, the primary classification is `undetermined_after_<last-proven-phase>`.

## 13. One-button integration contract

The first C0 implementation keeps `sgfx_preflight__<profile>` exactly four-pack and independently shippable.

After standalone R0 acceptance, a separate integration slice evolves the same action into a bounded plan:

- mandatory stage `sgfx_core`: anchors, constants, carpaints, project sanity;
- conditional stage `ramses_r0`: the exact probe described here;
- no new capability ID, Home page, button, toggle, or action supplied by QML;
- R0 runs automatically only when the packaged helper and canonical scene are ready;
- missing R0 prerequisites produce `unavailable`, not a core-preflight failure;
- R0 findings affect only exact Ramses check rows and next-action ordering;
- an accepted zero-error/zero-warning R0 check row may use scoped `passed`, while its containing gate, profile, delivery, and approval state remain independent;
- the Asset gate continues to reflect the four deterministic packs;
- Export & Interface may show metadata/validation evidence;
- Visual Evidence may show the bounded authored frame as evidence, never a visual approval;
- Review/Runtime may show lifecycle and logic evidence; and
- Delivery/Handoff never becomes passed from R0.

RaCo, BMW scripts, trace replay, cross-backend runs, performance capture, RenderDoc, validation layers, rack work, and external systems remain outside this automatic plan until their own phase explicitly graduates them. Failure-triggered deep diagnostics still require a separate operator action.

## 14. Error and lifecycle semantics

- Native validation errors are deterministic findings, not process crashes.
- A helper crash, malformed report, source mutation, output escape, identity mismatch, or unsupported helper digest is an execution failure.
- Missing scene/helper/backend is unavailable or blocked according to the exact prerequisite.
- Lifecycle requests have explicit deadlines because Ramses may emit no event when prerequisites are unmet.
- Timeouts identify the last proven phase and terminate the helper without an indefinite GUI wait.
- Console logs are retained as protected artifacts but never become the primary machine contract.
- Partial JSON is written to a temporary file and never accepted.
- Any passed-input digest change, worktree-status change, or output/source overlap fails closed and quarantines the result from current UI state. When no worktree status is available, the report states that the guard covers only the exact hashed inputs and the implementation review remains responsible for proving that the helper has no other write path.
- QML receives sanitized summaries and opaque handles only.

## 15. R0 non-goals

R0 does not:

- load or modify an `.rca` project;
- start Ramses Composer or RaCoHeadless;
- export or overwrite a Ramses/Logic file;
- change logic interface inputs beyond the exact authored camera perspective contract;
- run TracePlayer;
- compare OpenGL and Vulkan;
- define a screenshot threshold;
- claim asset/resource optimization;
- capture target/rack performance;
- use RenderDoc or Vulkan validation layers;
- inject failures;
- auto-fix, delete, rename, relink, save, or baseline content;
- create cross-run object history; or
- copy a BMW scene or derived frame into a package, repository, ticket, or external system.

## 16. R1 — authoring, interfaces, traces, and logic

R1 adds an audited read-only RaCo Python adapter that records project feature level, active errors, external projects, instances, object/property types, links, read-only/external-reference state, source URIs, tags/layers, animations, and interface schemas. Source hashes before and after are mandatory.

Curated interface scenarios include:

- exact documented examples;
- boundary values accepted by a reviewed schema;
- state-transition sequences;
- production traces supplied for lawful local use;
- authored perspectives; and
- constrained t-way combinations generated from a reviewed NIST-style input model.

The report states the factors, values, exclusions, t-way strength, covered combinations, uncovered combinations, and executed scenario IDs. Pairwise or t-way coverage is never described as exhaustive.

Logic profiling runs several updates for named normal and worst-case scenarios, recording executed/skipped/dirty nodes, link activation, topology-sort time, total update time, and slowest nodes. No universal logic budget is invented.

## 17. R2 — visual, backend, and shader portability

R2 may add:

- OpenGL versus Vulkan render comparison under identical authored inputs;
- Composer Vulkan-compatible evidence;
- team-supplied target Vulkan Profile capability checks;
- glslang compilation and `spirv-val` validation for supported shader artifacts;
- ingestion of glTF Validator JSON for source glTF/GLB assets;
- expected/actual/diff and perceptual FLIP error maps;
- short temporal sequences for flicker, shimmer, discontinuity, TAA, and intermittent-frame review;
- object ID, render pass, depth, normals, tangents, UV, wireframe, and overdraw diagnostic lenses; and
- failure-linked navigation into 3D inspection.

All image metrics remain review evidence until profile/scenario-specific thresholds are approved from representative data. Baselines are never updated automatically. Cross-backend differences are classified by provenance and do not automatically identify which backend is correct.

## 18. R3 — performance fingerprints

R3 combines:

- scene and Logic file sizes;
- cold load, Available, Ready, Rendered, and first-visible-frame timings;
- steady frame time and draw calls;
- logic update statistics;
- RPER flush, object, action, scene-update, resource, upload, frame, and VRAM/cache statistics;
- shader compile/cache evidence;
- accepted target DLT/Perfetto/benchmark evidence when supplied; and
- exact hardware, driver, backend, OS, toolchain, profile, and scenario identity.

Performance is compared only against a compatible baseline. Results record warmup, sample count, median, p95, min/max, workstation load, and noise/exclusion rules. A profile/hardware budget requires explicit authority; the captured Confluence KPI categories alone do not create one.

## 19. R4 — evidence graph and guided review

R4 adds:

- semantic scene manifests and source-to-export comparisons;
- change-aware object/resource/render/logic diffs;
- root-cause grouping that collapses derivative symptoms without hiding them;
- affected perspective/variant/state relationships when proven;
- review-completeness heatmaps for automated, manual, stale, missing, and not-applicable evidence;
- confidence-scored cross-run object history;
- a guided 3D review tour that focuses the exact object or authored camera when mapping exists;
- operator verdict receipts distinct from approval; and
- a copy-ready summary containing identity, finding, evidence, impact, owner, and next action.

The graph stores evidence relationships, not causal certainty. A causal edge is labelled `verified`, `inferred`, or `open`. Low-confidence object matching or impact mapping is shown as a candidate and never drives automatic approval.

## 20. R5 — resilience and deep GPU diagnostics

R5 runs only against SGFX-owned executables and disposable materializations:

- repeated load/publish/map/render/unmap/unload/restart endurance;
- missing-resource, invalid-reference, corrupt-file, incompatible-feature, invalid-display, timeout, and process-crash fault cases;
- Vulkan core, synchronization, GPU-assisted, best-practice, or shader-printf validation in explicitly selected development probes;
- failure-triggered RenderDoc capture with exact capture/replay environment;
- SPIR-V validation, semantic-preserving fuzzing, and reducer-assisted minimal failure cases where lawful and supported; and
- clean process/resource teardown checks.

Validation layers are never shipped enabled. RenderDoc is never always-on. Fault injection never touches the actual BMW source tree. A reduced shader or scene fragment is diagnostic evidence only and is not written back automatically.

## 21. 3D inspection experience

The car remains a contextual visual focus, but 3D inspection turns it into an evidence navigator:

- selecting a finding focuses a mapped object, pass, camera, or perspective;
- the panel shows the exact finding, source class, evidence, confidence, and next action;
- expected/actual/diff or a diagnostic lens appears only when available;
- Left/Right advances through unresolved findings;
- Enter opens the protected artifact or records a permitted local review verdict;
- Esc returns to the identical Control Center profile, gate, and evidence state; and
- an unmapped finding stays textual rather than guessing a camera or object.

The guided review tour is R4. R0 exposes only enough subject identity and authored-frame evidence to avoid designing an incompatible future contract.

## 22. Performance and concurrency

- Control Center startup never starts Ramses.
- C0 core preflight remains usable without R0.
- One SGFX effect executes at a time.
- Preview and R0 share a coordinator policy so they do not load the same scene concurrently.
- A diagnostic pre-empts or cancels queued preview work.
- R0 is one bounded child process with an overall 60-second budget and a 30-second Rendered/readback sub-budget; timeout evidence is OPEN until measured on representative profiles.
- R1–R5 define separate budgets from measured evidence before implementation.
- Deep visual/performance/GPU jobs never run on the GUI thread.
- Repeated/endurance tests are explicit specialist actions, not Home behavior.
- Derived frames, logs, reports, traces, and captures use size-capped local retention policies defined by their phase.

## 23. Safety, confidentiality, and provenance

- Public SDK headers and documentation are the implementation authority.
- Private/internal source may be inspected only as a behavioral oracle under the existing lawful clean-room rule; no proprietary implementation is copied.
- No confidential Confluence body, BMW scene, screenshot, trace, capture, source path, remote URL, credential, or secret is embedded in the product or committed report fixture.
- Fixtures use synthetic scenes and sanitized reports.
- Exact scene/perspective inputs are hashed before and after, source/output roots cannot overlap, and a containing Git worktree status is compared when available.
- Outputs are contained beneath the configured SGFX output root.
- Helper executables and optional tools require pinned provenance, digest, license/dependency inventory, and packaged-runtime verification.
- No network request is needed for a QA run.
- No Jira, SVN, Git push, Artifactory, CI, rack, vehicle, or external approval action is added.
- Suggested fixes remain text. Automatic fixers are out of scope.

## 24. R0 verification and acceptance

R0 implementation follows RED → minimal extraction → GREEN → real synthetic scene → approved real local smoke → diff review.

Acceptance requires:

1. The existing Control Center and four-pack action stay independently GREEN.
2. The exact eight-capability inventory remains unchanged.
3. The probe is extracted into focused library units; no second renderer or scene parser is created.
4. The CLI accepts only validated typed arguments from Python and rejects unknown options, output escape, invalid profile identity, and unsupported backend.
5. Metadata-only failure cases do not initialize the renderer unnecessarily.
6. Native validation issues preserve severity, message, object type/id/name when available, and source class.
7. Duplicate or empty names do not collide finding identity.
8. The report schema, enum values, phase order, finding identity, and path policy are exact and versioned.
9. Logic update success, cycle/runtime failure, executed/skipped nodes, and timing evidence are covered by synthetic tests.
10. Lifecycle tests cover success plus missing Available, Ready, Rendered, and readback events with bounded termination.
11. Black-frame classification covers every stable code and the undetermined fallback.
12. A validation finding is not misclassified as a helper crash.
13. A visible authored frame is not treated as visual approval.
14. No authored camera-crane interface produces an explicit missing-contract result; direct camera mutation does not occur.
15. The helper writes atomically and only beneath the supplied output root.
16. Every passed scene/perspective input has an identical before/after digest, output/source roots are disjoint, and an available containing-worktree status is identical.
17. Malformed, partial, stale-generation, mismatched-profile, mismatched-source, untrusted-helper, and escaped-path reports are rejected.
18. Console paths and raw native errors do not enter QML.
19. Home receives only bounded safe rows and opaque artifact handles.
20. R0 absence or failure cannot erase or change four-pack results.
21. The one-button integration occurs only after standalone R0 gates pass.
22. Preview and R0 cannot run concurrently for the same or different profile.
23. A current R0 completion refreshes exact check rows; a stale completion cannot replace current profile state.
24. Synthetic package fixtures contain no BMW data or private paths.
25. CMake, unit, integration, QML, package, process-lifecycle, and exact-tree gates pass.
26. A real local compatible export reaches the expected phase or produces a truthful classified failure; historical logs alone are insufficient.
27. The 60/30-second budgets are measured and remain OPEN or are revised through an evidence-backed spec amendment before release.
28. The final diff contains no unrelated cinematic/UI refactor or new mandatory dependency.

## 25. Phase graduation gates

Each later phase must show:

1. an exact documented gap or clearly labelled research hypothesis;
2. public or accepted local API feasibility;
3. isolated read-only execution;
4. synthetic regression fixtures;
5. representative-profile false-positive/unsupported-case evidence;
6. bounded performance and storage;
7. a clear owner and next action for every finding;
8. no new Home complexity;
9. no invented approval or universal threshold;
10. teammate pilot value; and
11. its own approved spec, ExecPlan, verification record, and changelog.

Failed candidates remain available as research notes or explicit specialist experiments; they do not quietly enter the daily workflow.

## 26. Open evidence boundaries

- The installed SDK proves API availability, not that every current/future BMW export is compatible.
- The local Composer/Ramses version relationship must be reported per scene; one successful 28.15.1-on-28.16.0 load is not a universal compatibility promise.
- Public version matrices may lag the installed internal toolchain; live binary/version metadata wins for local evidence.
- No current universal screenshot, perceptual, temporal, shader, logic, lifecycle, or performance threshold is authorized.
- A semantic object identity across exports is not guaranteed; confidence-gated matching remains future work.
- Native validation cannot prove artistic correctness, intended product behavior, variant completeness, target-driver behavior, rack performance, or stakeholder approval.
- Headless export behavior must be verified against the installed RaCo binary before any future export contract.
- Target Vulkan Profile, GPU/driver fleet, accepted traces, and representative performance baselines are not yet supplied.
- FLIP, combinatorial generation, RenderDoc automation, SPIR-V reduction/fuzzing, and Perfetto readers are research candidates until their phase gates pass.
- The May 2026 Confluence capture is not proof of current live or permission-hidden documentation.
- Operator-value improvement remains a hypothesis until the planned teammate pilot records it.

These boundaries are acceptance constraints, not placeholders.
