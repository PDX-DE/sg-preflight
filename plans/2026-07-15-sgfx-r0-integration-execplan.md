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

- [ ] Step 1: RED: `sgfx_core` runs exactly as today and its verdict is computed before and independently
      of R0; `ramses_r0` stage invokes `sg_preflight.ramses_probe_runner.run_probe` with the resolved
      helper/scene/perspective; every runner outcome maps to exactly one of finding-evidence /
      execution-failure / unavailable; core success + R0 unavailable is a successful preflight.
- [ ] Step 2: GREEN inside the existing action executor seam (`services.execute_profile_run` boundary);
      one run directory per attempt beneath the allowed SGFX output root; timeout terminates the helper and
      names the last proven phase.

## Task 3 — Check rows and gate projection

- [ ] Step 1: RED: probe evidence projects to exact Ramses check rows (metadata, validation, inventory,
      logic, lifecycle, frame) with the scoped-`passed` rule; next-action ordering; generation counter so a
      stale completion is discarded (req 23); Delivery/Handoff provably unaffected in every case.
- [ ] Step 2: GREEN in the evidence/presenter layer using the existing safe-projection contract; the frame
      artifact travels as an opaque handle (reqs 18/19).

## Task 4 — Concurrency interlock and Qt wiring

- [ ] Step 1: RED: the preview coordinator and the R0 stage share one exclusive render slot — starting one
      pre-empts/queues the other (req 22, and the recorded G78 crash-under-load rationale); Home audit
      tests prove no new capability/action/page appeared (the frozen eight-capability inventory holds).
- [ ] Step 2: GREEN; focused Qt host/presenter suites.

## Task 5 — Gates and acceptance

- [ ] Step 1: Focused aggregates for every touched module + the Home/capability boundary audit; full
      discovery footer on the integrated tree.
- [ ] Step 2: Independent adversarial review (fresh fleet, zero Critical/Important); real one-button run on
      a real export producing core verdicts plus R0 evidence rows end-to-end.
- [ ] Step 3: Ledger, changelog, STATE; the reqs 18/19/22/23 rows in the acceptance walk flip from
      N/A-standalone to PASS with evidence.
