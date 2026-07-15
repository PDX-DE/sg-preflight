# SGFX Ramses R0 ExecPlan (right-sized)

> **For agentic workers:** Use superpowers:executing-plans with superpowers:test-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking. RED tests come first in every task.

**Status:** ACTIVE. Supersedes `plans/2026-07-13-sgfx-ramses-r0-standalone-implementation-plan.md` (see its banner). The acceptance bar is unchanged: all 28 requirements in `plans/2026-07-12-sgfx-ramses-qa-observatory-design.md` section 24, plus the section 26 evidence boundaries.

**Goal:** Build and accept the standalone, noninteractive Ramses R0 probe: bounded metadata, native validation, structural inventory, one default-state logic update, lifecycle evidence (Available → Ready → Rendered), at most one 480×270 authored-frame readback, stable black/non-render classification, before/after source-mutation proof, and a versioned JSON report — without changing the four-pack action, Control Center truth, packaged default, or external systems.

**Architecture:** `sgfx::cine` (`cpp/CMakeLists.txt` target `sgfx_cine`) remains the only Ramses implementation boundary. Probe logic is extracted into focused library units beside the accepted authored preview renderer/lifecycle path (`cpp/src/ramses_preview.cpp`); `cpp/src/ramses_probe.cpp` grows from its existing stub. A new `sgfx_cine_ramses_probe` executable only parses strict typed arguments and writes an atomic native report. Python (`sg_preflight/ramses_probe_runner.py`) resolves inputs, launches the helper, validates the native report fail-closed, and publishes the final evidence bundle. No second renderer or scene parser is created (req 3).

**Tech stack:** C++17, CMake/CTest (configured tree `build/cine-c0`), Ramses 28.16.0 public SDK, SDL3, existing nlohmann_json 3.12.0, Python 3.13 (repo venv) standard library, unittest, PowerShell. No new production dependency (req 28).

## Global constraints

- Worktree `C:\Users\DavidErikGarciaArena\Downloads\sg-preflight-v02-qt-integration`, branch `feature/sgfx-v02-qt-integration-20260710`. Local commits only; no push, no SVN.
- All acceptance Python commands run through `scripts/run_sgfx_python.ps1` (pinned interpreter: `SGFX_PYTHON` or repo `.venv`, refuses the WindowsApps store stub, enforces CPython ≥ 3.10, runs `-B` with `PYTHONDONTWRITEBYTECODE=1` and prints the resolved interpreter as evidence).
- One backend only: CLI token `opengl`, mapped exactly to the proven `EDeviceType::GLES_3_0` path. GL 4.x / Vulkan comparison belongs to R2.
- Native probe binaries and native tests build and run in the `Release` configuration of `build/cine-c0`. The installed Ramses 28.16.0 SDK ships release-only DLLs; Debug-config consumers silently corrupt STL-carrying SDK returns (verified 2026-07-15: empty `ValidationReport`s and a segfault in Debug, correct findings in Release). Scenes are validated only after a successful flush or file load; direct `validate()` on structurally incomplete client objects is not exercised.
- At most one 480×270 authored-frame readback per run; it is evidence, never visual approval (req 13). R0 never creates or mutates a camera, render pass, source scene, perspective, or baseline.
- Drive only the exported `Interface_CameraCrane` contract when a validated perspective file and ID are supplied; JSON key `AspectFromResolution_isEnabled` maps only to runtime property `AutoAspect`, with no alias or C0-prototype fallback (req 14). Missing input/root/property tree ⇒ explicit missing-contract result, and metadata/validation lanes continue.
- Output caps: native JSON ≤ 2 MiB, final report ≤ 4 MiB, PNG ≤ 1 MiB, each retained console stream ≤ 256 KiB. The helper writes atomically and only beneath the supplied output root (req 15); output and source roots are disjoint; every passed scene/perspective input has an identical before/after SHA-256 (req 16).
- Native report and final `RamsesProbeReport` are separately versioned schema 1; probe version 0.1.0. Unknown fields, enum values, phase order, output files, helper names, profile identities, or artifact paths fail closed (reqs 8, 17).
- The standalone slice touches no QML, no capability, no `sg_preflight/qa_actions.py`, no `sg_preflight/qa_hub.py` (reqs 1, 2, 18, 19, 20). One-button `ramses_r0` integration is a separate later plan gated on standalone acceptance (req 21).
- Synthetic fixtures contain no BMW data or private absolute paths (req 24). Real exports are consumed read-only from their existing locations.
- Timing budgets (60 s probe / 30 s readback) are measured and reported; they remain OPEN rather than silently normalized (req 27).

## Task 1 — Pinned Python launcher

- [x] Step 1: Add `scripts/run_sgfx_python.ps1` (small, reviewable): resolve interpreter from `-Python` / `SGFX_PYTHON` / repo `.venv`; reject missing interpreter and the store stub with a clear message; probe and enforce CPython ≥ 3.10; forward remaining arguments with `-B`; propagate the child exit code.
- [x] Step 2: Smoke: launcher runs `-c` one-liners under PowerShell 7 and Windows PowerShell 5.1; missing-interpreter and stub paths exit nonzero without launching anything.
- [x] Step 3: Commit.

## Task 2 — Native probe units (RED first)

- [x] Step 1: RED: add `cpp/tests/ramses_probe_units_test.cpp` (CTest) covering: metadata/compatibility facts collection; validation-finding capture preserving severity, message, object type/id/name-when-available, and source class (req 6); duplicate/empty names not colliding finding identity (req 7); structural/resource inventory counts; logic-update success, cycle/runtime failure, executed/skipped nodes, and timing evidence (req 9); frame classification covering every stable black/non-render code plus the undetermined fallback (req 11). Helper-crash vs validation-finding separation (req 12) is covered at the runner layer in Task 4.
- [x] Step 2: GREEN: extract/implement the units in `cpp/src/ramses_probe.cpp` + `cpp/include/sgfx/cine/…`, reusing the preview renderer/lifecycle path; metadata-only lanes never initialize the renderer (req 5).
- [x] Step 3: Lifecycle tests: success plus missing Available, Ready, Rendered, and readback events, each with bounded termination (req 10) — deterministic `drive_probe_lifecycle` driver with one shared budget, mirroring the accepted preview `waitFor` semantics.
- [x] Step 4: Build + run in `build/cine-c0` (Release); commit.

## Task 3 — `sgfx_cine_ramses_probe` executable

- [x] Step 1: RED: argument/contract tests — accepts only validated typed arguments; rejects unknown options, output escape, invalid profile identity, unsupported backend (req 4).
- [x] Step 2: GREEN (no-renderer lanes): strict argv parsing; phase orchestration (arguments → metadata → scene_load → validation → inventory → logic → perspective → frame, exact order; exact status set `completed`/`failed`/`not_run`/`not_requested`, where `not_requested` marks the optional frame lane when no perspective is supplied); versioned native report (schema 1, probe 0.1.0, exact top-level key set with reserved `lifecycle`/`frame` nulls); atomic confined `ramses-probe-native.json` writer (2 MiB cap, no-replace, tmp+rename); deterministic exit codes 0/64/65/74; truthful classified failure reports. Frame outcome and classification enums are fail-closed on the runner side.
- [x] Step 3: Build + CTest (Release) + real-binary smoke (usage → 64, missing scene → 65 with failure report); commit.
- [x] Step 4: Authored-frame/lifecycle lane (`--perspective` + `--perspective-id`): shared render support extracted to `cpp/src/ramses_render_support.h` (preview refactored onto it, behavior-identical); strict perspective parser from the proven cinematic_shell contract; one 480×270 readback driven via `AutoAspect`-only camera-crane semantics across interface AND script crane roots (real exports can keep the interface unlinked — proven on G50); lifecycle evidence recorded through `drive_probe_lifecycle` (30 s budget, measured); frame classified and `first-frame.png` written only after successful readback (1 MiB cap); explicit `missing_contract` result at exit 0 when the property tree is absent (req 14); real-renderer test proves the full pipeline with a deterministic black frame, and the real G50 export classifies **content** under a framing view.

## Task 4 — Python runner and final report

- [x] Step 1: RED: `tests/test_ramses_probe_runner.py` — request construction; helper launch; fail-closed native-report validation; rejection matrix for malformed, partial, stale-generation, mismatched-profile, mismatched-source, untrusted-helper, and escaped-path reports (req 17); helper-crash vs validation-finding separation (req 12); before/after digest proof (req 16); final `ramses-r0-evidence.json` + `RamsesProbeReport` schema. 23 tests.
- [x] Step 2: GREEN: `sg_preflight/ramses_probe_runner.py` (standard library only), runnable via `scripts/run_sgfx_python.ps1 -m sg_preflight.ramses_probe_runner`; helper console streams retained as `stdout.log`/`stderr.log` (256 KiB caps).
- [x] Step 3: Committed (`248e388`, `a18f170`).

## Task 5 — Synthetic end-to-end and package/process gates

- [x] Step 1: Synthetic scene end-to-end: native suite drives a saved synthetic scene through every phase including a real-renderer black frame; runner suite drives a fake helper through success/crash/classified/mutation paths; fixtures BMW-free (req 24).
- [ ] Step 2: Package/process/exact-tree gates: unittest aggregate for the touched modules, process-lifecycle check (no orphan helper), `git diff --check`, diff review confirming no unrelated cinematic/UI refactor and no new mandatory dependency (req 28, 25).
- [ ] Step 3: Commit.

## Task 6 — Real local smoke and acceptance

- [x] Step 1: Real local smoke DONE against two real staging exports (G50, G78) with the real `perspectives_CID_2to1.json` view `CID_CCM_FRONT`: all eight phases completed with truthful evidence (72/68 real findings, full inventories, executed logic, complete lifecycles ~2-2.9 s, frames classified black — a documented scene-state diagnostic, not visual approval). One G78 helper crash under concurrent load was classified truthfully and did not reproduce (OPEN flake). Budgets measured, remain OPEN (req 27). Evidence under `out/r0-smoke/`.
- [ ] Step 2: Walk all 28 section-24 requirements with an evidence row each; independent review of the full diff; resolve findings.
- [ ] Step 3: Ledger checkpoint, changelog note, final commit. Standalone Acceptance Gate passes; the separate one-button integration slice may then be planned.
