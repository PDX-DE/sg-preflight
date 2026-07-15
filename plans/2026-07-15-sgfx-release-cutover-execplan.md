# SGFX Release & Cutover ExecPlan — Qt Quick default

> **For agentic workers:** Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. This plan
> revives the historical Task 14 release contract (commit `ce7514e`) on the current tree.

**Status:** ACTIVE after standalone R0 acceptance. This is the Jana-critical track: the team still runs the
pre-simplification Clean default; everything Jana asked for ships only when the delivered QA Control Center
becomes the double-click default.

**Goal:** Flip the packaged no-argument default from Clean (NiceGUI) to the Qt Quick QA Control Center on a
fully gated, evidence-backed release: exact-tree test footers, offline safety probes, QML gates, an exact
rebuilt bundle, the four performance budgets, and two independent zero-Critical/Important reviews — then
rebuild, hash, and re-verify from the committed cutover.

**Baseline facts (verified 2026-07-15):** `DEFAULT_DOUBLE_CLICK_ARGS = ["dashboard", "run", "--ui-mode",
"clean"]` at `sg_preflight/exe_entry.py:17`; staged C0 bundle identifies `c6b4808`; installed/last-good
`dist/` bundle identifies `a736826`; the release candidate additionally carries the R0 probe, the Jana
early-exit fix (`3d69fef`), and the preview dual-generation camera fix (`c8afcc2` — required for real
IDCevo turntables, proven on the real G50 export).

## Global constraints

- Worktree `sg-preflight-v02-qt-integration`, branch `feature/sgfx-v02-qt-integration-20260710`. Local
  commits only; no push, no SVN, no distribution until David's explicit go.
- Clean is hidden, not deleted: it stays reachable via the explicit `--ui-mode clean` argument (Jana's
  "off the main path, don't delete" rule); only the no-argument default changes.
- Cold-start gates (warm p50/p95, official first-run) run ONLY on a reference-ready workstation. Never
  terminate the operator's processes or change the power plan autonomously — David prepares the machine.
- Python acceptance commands run through `scripts/run_sgfx_python.ps1`; native tests in Release only.
- No new mandatory dependency; team-facing text human-voiced; no codenames or AI mentions anywhere.

## Task 1 — Candidate evidence on the exact tree

- [ ] Step 1: Full unittest discovery to a COMPLETE footer on the candidate head (attempt 3 in flight,
      process verified alive). Focused aggregate DONE: `tests.test_bundle_manifest` +
      `test_qt_quick_benchmark` + `test_qt_quick_preview` + `test_surface_registry` +
      `test_ramses_probe_runner` — **Ran 85, OK (1 skip), 74.7 s**, complete footer at
      `out/control-center-c0/focused-aggregate-2026-07-15.log`.
- [x] Step 2: Offline CLI safety matrix — all nine multi-format smokes exit 0 (2026-07-15 evening).
      Contract note: `delivery-documentation read` now requires an explicit `--profile` (C0
      profile-neutrality working as designed); Jira probes report `connection_status: not_run`,
      `network_confirmed: false`, zero transport.
- [x] Step 3: `tests.test_qml_format` 4/4; `pyside6-qmllint` over all 17 QML files — five
      `unqualified` warnings, all on the Python-injected `sgfxProductFonts` context property (invisible
      to static analysis by nature, guarded at use sites, pre-existing C0 code) — accepted with
      rationale, flagged for the Task 4 reviews; `compileall` clean over `sg_preflight`/`scripts`/`tests`;
      `git diff --check` clean across the whole R0 range; attribution/codename/private-path/credential
      scans clean (all hits inspected: legitimate domain text and regex-pattern definitions).

## Task 2 — Exact bundle

- [ ] Step 1: Build via `scripts/build_sgfx_exe.py`; staged-then-swap; manifest commit MUST equal HEAD;
      Qt QML roots exactly `QtQml,QtQuick`; Grafiks omitted; zero checkout paths in the manifest.
- [ ] Step 2: Frozen probes exit 0 (`--help`, packaging import probe); hidden-shell lifecycle check
      (start, 8 s alive, graceful close, zero leftover processes, workspace removed).

## Task 3 — Performance gates (one exact tree)

- [ ] Step 1: Navigation gate (120/120 acknowledgements within budgets) and 60-second reader-stress gate
      with the readiness handshake.
- [ ] Step 2: On a reference-ready workstation (David-gated): 1 priming + 7 diagnostic warm launches with
      margin below 2500 ms, then the official 20-sample warm gate and official five-directory first-run
      attempt. A third same-error first-run failure is a hard stop — never weaken budgets to pass.

## Task 4 — Independent reviews

- [ ] Step 1: Two independent parity/safety reviews of the full cutover diff (multi-agent allowed for one;
      the second must be a separately-prompted adversarial pass). Zero Critical/Important to proceed.
- [ ] Step 2: Resolve findings; re-run affected gates.

## Task 5 — Cutover and re-verification

- [ ] Step 1: Flip `DEFAULT_DOUBLE_CLICK_ARGS` to the Qt Quick shell; update README/CHANGELOG with the
      cutover note in plain human wording; commit.
- [ ] Step 2: Rebuild from the committed cutover head; hash the executable; rerun decisive gates (frozen
      probes, navigation, reader stress) on the rebuilt bundle; atomic swap into `dist/` as last-good.
- [ ] Step 3: Durable records — STATE.md, ledger beat, changelog, and the copy-ready teammate note for the
      pilot. Distribution beyond this machine stays David-gated.
