# Contributing

This repo is being shaped as internal capability tooling for Seriengrafik / 3D Car QA and integration.

Read [LICENSE](LICENSE), [NOTICE.md](NOTICE.md), and [SECURITY.md](SECURITY.md) before attaching mirrored source data, internal screenshots, or generated evidence to issues, PRs, or docs.

> [!IMPORTANT]
> Do not attach mirrored SVN content, confidential screenshots, or generated evidence to public issues, public PRs, or external chats. Keep repository handling aligned with the internal proprietary license and notice files.

## Branching

Use a lightweight GitFlow-style branch model:

> [!TIP]
> Default to `feature/<topic>` from `develop`, merge back into `develop`, and only promote to `main` when the result is a stable internal milestone.

- `main`
  - stable, releasable state
  - only merge reviewed work that is ready to represent the project
- `develop`
  - integration branch for ongoing work
  - default target for feature work while the project is still evolving quickly
- `feature/<topic>`
  - short-lived branches for focused work
  - examples: `feature/constants-adapter`, `feature/report-grouping`
- `release/<version>`
  - used when preparing a tagged release or internal milestone snapshot
- `hotfix/<topic>`
  - used for urgent fixes against `main`

## Change Hygiene

Before opening a PR or merge request:

> [!NOTE]
> For live SG work, also run the real matrix smoke when the change touches adapters, live configs, or reporting that is used in the mirrored-SVN flows.

1. Run `python -m unittest discover -s tests -v`
2. Run `powershell -ExecutionPolicy Bypass -File scripts\run_smoke_test.ps1`
3. Inspect `out/smoke-test/latest/SUMMARY.md`
4. Inspect the generated HTML report for the affected flow
5. Update `CHANGELOG.md` for user-visible changes

## Pull Request Expectations

PRs should stay focused and explain:

- what changed
- why it matters for SG / 3D Car QA or integration
- what was verified locally
- what still depends on missing SG/BMW-side access or files

Prefer small vertical slices over wide placeholder scaffolding.

Use branch names and titles that describe the actual work, for example:

- `feature/g70-live-project-sanity`
- `feature/pivot-master-constants-adapter`
- `hotfix/python311-ci-compat`

## Reporting Standard

Changes should preserve:

- CLI-first execution
- JSON output for automation
- HTML output for human review
- readable evidence for QA / TA / Pipeline people, not only for programmers

## Scope Guardrails

Until real production access is fully available:

- prefer adapters over manual data re-entry
- prefer wrapping or normalizing existing SG helper scripts over reimplementing blindly
- keep assumptions explicit in `docs/assumptions-and-decisions.md`
- do not add a dashboard or GUI before the deterministic preflight core is strong

## Release Notes

For milestone snapshots, add or update:

- `CHANGELOG.md`
- any affected docs in `docs/`
- smoke-test outputs if they are being used as demo evidence
- repository-facing notices when handling or publication expectations change
