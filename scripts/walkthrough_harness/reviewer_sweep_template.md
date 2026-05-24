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
