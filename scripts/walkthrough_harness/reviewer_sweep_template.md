# SGFX Reviewer Sweep Template

Use this checklist for each staging parity sweep that claims cross-panel, multi-profile, or runtime-harness consistency.

## Runtime Evidence

- Verify `page-guardrail-delivery-probes.json` includes `multi_profile_assertions.minimum_profile_set_covered: true`.
- Verify the Clean harness profile list includes at least `G65`, `G70`, `NA8`, `F70`, and `U10`.
- Verify `multi_profile_assertions.buggy_profile_covered: true`.
- Verify `multi_profile_assertions.cross_panel_preflight_exercised: true`.
- Verify `multi_profile_assertions.cross_panel_consistency: true`.
- Verify `multi_profile_assertions.setup_actions_confirmation_gated: true`.
- Verify `multi_profile_assertions.outcome_vocab_strict: true`.
- Verify each per-profile folder exists under `profiles/<profile>/` and has four page screenshots plus four HTML captures.
- Verify `grafiks-setup-uia-probes.json` includes the same minimum profile set and passes all aggregate assertions.

## Real BMW Pipeline Evidence

- Run `scripts/walkthrough_harness/probe_bmw_pipeline_real.py` only when `SGFX_REAL_BMW_PIPELINE_AVAILABLE=1` is intentionally set on the review machine.
- Verify `probe-summary.json` exists under the G-7 evidence folder.
- Verify `probe-summary.json` records `gate_enabled: true` for a real-subprocess sweep, or `status: skipped` when the gate was not set.
- Verify `profiles` includes at least `G65`, `G70`, `NA8`, `F70`, and `U10`.
- Verify `actions` includes `delivery_export` and `screenshot_capture`.
- Verify `minimum_profile_set_real_subprocess_evidence_recorded: true`.
- Verify `lane_coverage.idc_evo.real_subprocess_evidence_recorded: true`.
- Verify `lane_coverage.idc_23.real_subprocess_evidence_recorded: true`.
- Verify each default profile in `profile_coverage` records both actions as invoked.
- Verify each real action record contains `real_subprocess_invoked: true`, `is_approval: false`, command evidence, and stdout/stderr paths when logs are available.
- Treat `unavailable` records as environment/data-prep evidence to classify, not as SGFX approval or rejection.

## Frozen-.exe Smoke per Subprocess-Spawning Feature

Source-tree `python -m sg_preflight.cli` evidence is necessary but not sufficient. Every feature that spawns a subprocess must also be smoked from the staged frozen `.exe` (PyInstaller onedir at `dist/sgfx-preflight/sgfx-preflight.exe`), because the frozen runtime changes `sys.executable`, working directory, `_MEIPASS`, and `subprocess.Popen` defaults. A source-tree pass does not prove the .exe works.

Subprocess-spawning features in scope (enumerate from `sg_preflight/` grep on `subprocess.(run|Popen|check_call|check_output|call)`):

- BMW delivery workbook export (`delivery_workbook_generation.py`, IDC_EVO + IDC_23 lanes).
- BMW screenshot capture (`screenshot_capture.py`, IDC_EVO + IDC_23 lanes).
- Dashboard build-review-package (`dashboard/main.py` spawning `ticket-review` CLI).
- Clean host launch (`desktop/clean_host.py` spawning NiceGUI server for QWebEngineView embedding).
- Dependency auto-onboarding (`dependency_onboarding.py` spawning installers / `git clone`).
- Desktop notification toast (`desktop_notifications.py` Windows toast invocation).
- Daily snapshot / digest fan-out (`daily_snapshot.py`, `daily_digest.py`) if they shell out.
- Manual review / visual review companions (`manual_review.py`, `visual_review.py`) if they shell out.
- File ops open/reveal (`desktop/file_ops.py` `explorer.exe` / `start` invocations).

Per-feature smoke evidence required:

- The smoke command was issued against the staged `dist/sgfx-preflight/sgfx-preflight.exe`, NOT a source-tree `python -m` invocation. Record the resolved `.exe` path in the evidence payload.
- No visible CMD window flashed during the run. Verify `subprocess_utils.install_no_window_subprocess_patch()` or `hidden_subprocess_kwargs()` is on the spawn path; record `creationflags_no_window: true` in the evidence payload for Windows.
- Subprocess exit code captured + recorded (`exit_code: <int>` in evidence payload). A nonzero exit must be classified honestly (`status: unavailable` with reason) and never wrapped as `available`.
- Stdout + stderr captured to log files under the evidence folder (`logs/<feature>-<profile>.{stdout,stderr}.log`). Empty logs are recorded as zero-byte files, not omitted.
- Anti-overclaim discipline preserved: `is_approval: false`, `manual_review_required: true`, and (for write actions) `confirm_required: true` survive the frozen-runtime payload unchanged.
- For BMW pipeline subprocesses, verify the spawned interpreter is the EXTERNAL Python (system / `py.exe` / operator-registered), NOT the frozen SGFX runtime. Record `spawned_interpreter` in the evidence payload and confirm it is not the same path as the running `.exe`.
- For SGFX-internal re-invocations (e.g. `ticket-review` from `build-review-package`), verify the spawn resolves back to the running `.exe` (or its bundled entry point), NOT a host-system `python` that may be absent. Record `spawned_interpreter` equal to the running `.exe` path.
- `_MEIPASS` and other PyInstaller-only env vars are NOT leaked into the spawned subprocess's environment (it must inherit a clean env). Record `env_clean: true` after spot-checking the subprocess's effective env when available.
- Working directory at spawn time is recorded; CWD must be a writeable operator-local path, never the `dist/sgfx-preflight/_internal/` bundle interior.

Evidence layout convention:

- All frozen-.exe smoke evidence lives under `out/walkthrough-evidence-<sha>-<ts>/frozen-exe-smoke/<feature>/` with `summary.json` per feature + per-profile subfolders when applicable.
- `summary.json` carries the keys above plus `frozen_exe_path`, `frozen_exe_sha256`, `started_at_utc`, `completed_at_utc`, and the per-action result list.
- A `frozen-exe-smoke/index.json` aggregates per-feature pass/fail/unavailable so a reviewer can verify the full enumeration was covered.

Reviewer assertions:

- Verify `frozen-exe-smoke/index.json` exists and enumerates EVERY subprocess-spawning feature listed above. A missing feature is a REVISE verdict, not a skip.
- Verify each per-feature `summary.json` records `frozen_exe_path` ending in `dist/sgfx-preflight/sgfx-preflight.exe` (or the documented bundle entry point).
- Verify `frozen_exe_sha256` matches the SHA256 of the actual on-disk `.exe` at sweep time.
- Verify `creationflags_no_window: true` for every Windows spawn; absence is a REVISE verdict.
- Verify `is_approval: false` for every payload; presence of `is_approval: true` anywhere is an immediate REVISE.
- Treat any frozen-.exe smoke result that differs from the matching source-tree harness result as a real regression, not a flake. The .exe is the shipped artifact; source-tree green does not override .exe red.

## Cross-Panel Consistency

- Do not accept G65-only evidence for dependency consistency.
- Compare the Dependency setup panel against Generate delivery workbook pre-flight for `G70` or `NA8` at minimum.
- For each compared dependency, setup status and pre-flight status must match on the same machine state.
- If a Generate pre-flight does not render for a profile because the workbook evidence is already available, record that profile as skipped and verify another required profile exercises the pre-flight.

## Standing Guardrails

- Manual review remains required.
- Decision: not approval — evidence only.
- BMW Git access is read-only. SGFX never modifies BMW source.
- Activity log is local-only — never posted to Jira, SVN, or BMW Git.
