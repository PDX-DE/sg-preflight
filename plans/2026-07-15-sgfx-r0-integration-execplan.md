# SGFX R0 One-Button Integration ExecPlan

> **For agentic workers:** Use superpowers:executing-plans with superpowers:test-driven-development.
> Entry criterion: the Standalone R0 Acceptance Gate in `plans/2026-07-15-sgfx-ramses-r0-execplan.md` has
> passed. This slice implements design §13 (one-button integration contract) and §14 (error/lifecycle
> semantics) of `plans/2026-07-12-sgfx-ramses-qa-observatory-design.md`, and closes acceptance
> requirements 18, 19, 22, and 23 that are N/A-standalone today.

**Goal:** Evolve the existing `sgfx_preflight__<profile>` action into a bounded two-stage plan — mandatory
`sgfx_core` (anchors, constants, carpaints, project sanity, exactly as today) plus conditional `ramses_r0`
(the accepted probe) — with no new capability ID, Home page, button, toggle, or QML-supplied action.

## Hard rules (from design §13/§14 — restated, not weakened)

- R0 runs automatically only when the packaged helper (pinned SHA-256) and the canonical resolved scene
  are ready; missing prerequisites yield `unavailable`, never a core-preflight failure.
- R0 findings affect only exact Ramses check rows and next-action ordering. A zero-error/zero-warning R0
  row may use scoped `passed`; its containing gate, profile, delivery, and approval state stay independent.
- The Asset gate stays four-pack; Export & Interface may show metadata/validation; Visual Evidence may show
  the bounded authored frame as evidence never approval; Review/Runtime may show lifecycle and logic
  evidence; Delivery/Handoff never becomes passed from R0.
- Native validation errors are findings; helper crash / malformed report / source mutation / output escape /
  identity mismatch / untrusted digest are execution failures; missing prerequisites are unavailable or
  blocked — the three families never blur (the runner already enforces this).
- Preview and R0 never run concurrently for the same or different profile (req 22); a stale R0 completion
  can never replace current profile state (req 23); QML receives only bounded safe rows and opaque artifact
  handles — no console paths or raw native errors (reqs 18/19).
- Console logs stay protected artifacts under the run's output root; partial JSON is never accepted.

## Task 1 — Packaged helper readiness

- [x] Step 1: RED bundling tests DONE: probe helper ships beside the preview runtime (shared
      Ramses/SDL DLLs, byte-parity verified against the Release tree) under
      `_internal/cpp/bin/sgfx_cine_ramses_probe.exe` with a build-recorded SHA-256
      (`ramses_probe_helper` / `ramses_probe_helper_sha256` manifest fields); missing helper is a
      deterministic recorded skip; probe-without-runtime rejected; staged validation verifies the
      shipped digest.
- [x] Step 2: GREEN DONE (`69e18b2`): `copy_probe_helper` + manifest schema + staged validation;
      `resolve_packaged_probe_helper` returns path+digest or the exact missing prerequisite
      (manifest_unavailable / manifest_malformed / helper_not_packaged / helper_missing /
      helper_digest_mismatch). Suites 113/113. REAL proof: freshly rebuilt Release helper accepted
      into `cpp/bin` (usage smoke exit 64, CTest 3/3); real `--staged-only` build exit 0 with
      `included` + digest in the manifest; resolver ready against the real bundle; the PACKAGED
      helper ran the real G45 export end-to-end (completed, exit 0, six phases, evidence written).

## Task 2 — Two-stage action plan (runner side)

- [x] Step 1: RED DONE: four executor tests prove `sgfx_core` unchanged (the pre-existing
      core-only test passes unmodified; verdict sealed before the stage), the probe launches with
      the resolved helper/scene, every outcome maps to exactly one family (evidence /
      execution_failure / unavailable — matrix-tested incl. helper_crash, worktree_status_changed,
      scene_incompatible, scene_unavailable), core success + R0 unavailable = successful preflight,
      and a missing scene never launches the helper.
- [x] Step 2: GREEN DONE (`5d3c089`): `_execute_ramses_r0_stage` at the existing
      `_execute_sgfx_preflight` seam; per-attempt run directory `<record output root>/ramses-r0`;
      the runner's terminating timeout applies (helper killed, `helper_timeout` execution failure —
      console streams stay protected under the run root); scene resolution mirrors the accepted
      preview (source checkout first, local project fallback); stage is wrapped and structurally
      non-fatal. Scoped note: the frame/perspective lane stays `not_requested` in this stage — the
      authored-frame evidence row joins via Task 3's projection with an explicitly configured
      perspective. Suites: qa_actions + qa_hub + services + runner 69/69.

## Task 3 — Check rows and gate projection

- [x] Step 1: RED DONE (`d62f531`): probe evidence projects to exact Ramses rows — `ramses-validation`
      on Export & interface (scoped `passed` when clean, `findings` with counts, `failed` on execution
      failure) and `ramses-logic` on Review (`recorded`); gate states are computed before the rows are
      appended so no gate verdict can change; Delivery/Handoff and the four-pack Asset gate proven
      byte-identical with and without probe data; `unavailable` adds nothing; the probe payload travels
      inside the same record snapshot as the core verdict, so a stale completion can never pair old rows
      with a newer core result (req 23). Scoped notes: lifecycle/frame rows join when the frame lane is
      explicitly configured (stage currently runs the headless lanes); next-action ordering deliberately
      unchanged (permitted by section 13's "may").
- [x] Step 2: GREEN DONE in the hub's safe-projection layer: every row field passes the bounded-text
      sanitizers, `latestLocalRun` keeps its exact key set, no path or raw native error can reach QML
      (reqs 18/19). The evidence file is recorded in the action record's artifacts and paths
      (`ramses_r0_evidence`, plus protected `ramses_r0_stdout`/`ramses_r0_stderr` console paths that
      are never exposed as reveal artifacts); wiring probe artifacts into the QML opaque-handle
      registry joins the frame-lane slice, which is when a visual artifact first exists.
      Suites: hub 15/15, presenters+capabilities 35/35, ui 22/22.

## Task 4 — Concurrency interlock and Qt wiring

- [x] Step 1: RED DONE (`eb4469a`): one exclusive render slot — starting a diagnostic pre-empts the
      preview (pre-existing, test kept), and a preview requested while an effect holds the slot is
      queued with its launch permission preserved and started when the effect finishes (req 22; the
      recorded G78 crash-under-concurrent-render rationale). Honest scope: the interlock test drives
      the slot with a stand-in long-running effect — the guarantee holds for ANY effect (the slot is
      capability-generic, so the probe-carrying preflight is covered by the same code path), and the
      real probe-in-action case is exercised end to end by the real one-button run; reqs 22/23 flip in
      the acceptance walk on that combined evidence, not on the stand-in test alone. Home audit: the
      frozen eight-capability inventory test and the full capabilities suite pass unchanged — no new
      capability, action, page, button, or toggle.
- [x] Step 2: GREEN; focused suites: preview 17/17, core+capabilities 87/87, hub 13/13, ui 22/22.

## Task 5 — Gates and acceptance

- [x] Step 1: DONE — touched-suite aggregates 173/173 at the final tree (qa_actions, qa_hub,
      runner 51, bundle-manifest, native-scaffold, preview); Home/capability boundary audit via the
      unchanged capabilities suite; exclusive integrated-tree footer **Ran 1171, OK (8 skips),
      DISCOVERY_EXIT=0 at `f310cd3`**.
- [x] Step 2: DONE — independent adversarial review `wf_f876765c` (fresh 16-agent fleet): 10
      confirmed, ZERO Critical, all resolved (`86ad3ba`); the verification loop then ran to closure
      (10 → 1 → 3 → 2 → 4 → 7 → 1 → 2 → 0 across nine rounds, both final lenses empty), landing the
      structural `environment_error` mechanism, the tree-kill/reap hardening, and the atomic
      evidence-claim consistency across every surface. Real one-button run at the final tree on the
      real G45 export: core verdicts sealed + R0 evidence rows end to end
      (`out/r0-smoke/onebutton-final-rhm_deig`).
- [x] Step 3: DONE — ledger beat, changelog entry, STATE; acceptance-walk rows 18/19/22/23 flipped
      to PASS with evidence. **ONE-BUTTON INTEGRATION GATES PASSED 2026-07-16 19:55 +02:00.**
