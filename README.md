# SGFX QA Preflight - Local Alpha

This folder is a local-alpha QA workflow support bundle for the Seriengrafik 3D Car team. It helps operators inspect local state, prepare evidence, prioritize review work, and run read-only checks against operator-local SVN and BMW Git content.

It is not a production deployment, not a delivery package, and not a replacement for the Quality Hero manual review checklist. Evidence and status output are review support only. Manual RaCo, Blender, emulator, screenshot, and delivery review remain human-owned.

## What This Alpha Contains

- Native operator observability: a read-only overview panel in the native shell, sourced from Python desktop state.
- Screenshot review prioritization: P0-P3 suggested review order with reasons and signals. No screenshots are hidden or approved by the tool.
- Daily / morning QA digest: JSON, text, and Markdown summaries for evidence prepared, blockers, manual review pending, waiting-for-owner state, workflow status, and suggested review order.
- Manual review companion: Quality Hero review steps surfaced for operator notes and verdict entry. `recorded_by_tool` stays false.
- Delivery checklist workbook reader: read-only ingestion of operator-local delivery checklist workbook data.
- Export-size analysis reader: read-only ingestion of operator-local `Cars\size_analysis\<profile>_<date>.xlsx` workbook data.
- Native and Web evidence surfaces: export-size evidence can be shown in the native operator shell and SGFX QA Status Board.
- Screenshot test state reader: read-only BMW / MINI screenshot baseline and test-config state from local BMW Git.
- BMW Git readiness reader: read-only per-profile state from the local `digital-3d-car-models` checkout.
- QA Hero readiness reader: read-only presence and count checks for documented Quality Hero assets such as LightFX, WelcomeFX, ShadesFX, CarPaint, AnchorPoints, Constants, and Perspectives.
- CLI uniformity: read/status commands support `--format text|json|markdown` and `--output-path` / `--out` where relevant, while preserving compatible `--json` and `--markdown` aliases.
- Operator-local template store: save, show, run, list, and delete local command templates without sharing them or posting them anywhere.
- Clean-first display mode: native shell and SGFX QA Status Board default to a neutral SGFX work view; the SGFX-branded view is optional and does not change backend QA logic.
- Confirmation-gated Jira posting: optional dry-run-first Jira comment posting through the CLI. Nothing posts unless the operator explicitly reruns with `--confirm`.
- Operator docs: concise CLI and JSON workflow guides are included under `docs/`.

## Included Files

- `sg_preflight/` - Python backend, CLI, state readers, digest generation, review support.
- `desktop_native/` - native C++ operator shell source and CMake files.
- `scripts/` - helper scripts for build, smoke, packaging, and verification.
- `tests/` - automated tests shipped with the curated bundle.
- `config/` - SGFX rule and profile configuration.
- `docs/` - curated team-facing docs only.
- Root metadata: `pyproject.toml`, `LICENSE`, `NOTICE.md`, `SECURITY.md`, `CONTRIBUTING.md`, this `README.md`, and a clean local-alpha `CHANGELOG.md`.

Internal coordination notes, research notes, generated `out/` artifacts, build outputs, local-only notes, local-only evidence files, audio files, BMW source content, and unrelated R&D material are intentionally not included.

## First Run / Sanity Checks

Run these commands from the bundle root:

```powershell
python -m sg_preflight --help
python -m sg_preflight list-profiles --format json
python -m sg_preflight desktop-state overview --profile-id G65 --json
python -m sg_preflight daily-digest latest --format markdown
```

The daily digest is safe on a fresh checkout. If no review package exists yet, it returns a clean no-package summary and exits successfully.

`review-board latest --json` requires a generated or copied review package. On a fresh checkout it can report that no matching review package was found; that is expected for the SGFX QA Status Board compatibility surface.

## Real SVN / BMW Git Read-Only Checks

These commands read operator-local content only. They do not modify SVN or BMW Git:

```powershell
python -m sg_preflight delivery-checklist read --profile G65 --workspace C:\repositories\trunk --format markdown
python -m sg_preflight export-size-analysis read --profile G65 --workspace C:\repositories\trunk --latest --format markdown
python -m sg_preflight screenshot-test-state read --profile G65 --format json
python -m sg_preflight bmw-git-readiness read --profile G65 --format json
python -m sg_preflight qa-hero-readiness read --profile G65 --format json
```

If a local dependency is missing, the tool reports the missing state. It should not pretend a check succeeded.

## Optional Jira Dry Run

Jira posting is opt-in and confirmation-gated. A dry run is the default:

```powershell
python -m sg_preflight jira post --ticket IDCEVODEV-977874 --body "Dry run smoke." --format json
```

The command prints what would be posted and does not send a network request. A real post requires operator-provided Jira configuration and an explicit `--confirm` flag in that invocation.

## Tests

From the bundle root:

```powershell
python -m unittest discover -s tests -v
```

The curated bundle test count can differ from the source alpha test count because internal guard-only tests are excluded from the team-facing bundle. The latest bundle verification ran successfully with 190 tests OK and 3 skipped; the source alpha verification for the same tip ran 196 tests OK and 3 skipped.

## Optional Native Build

```powershell
cmake -S desktop_native -B build/native-downloads -A x64
cmake --build build/native-downloads --config Release
powershell -ExecutionPolicy Bypass -File scripts\verify_native_shell_bundle.ps1 -BuildDir build/native-downloads -LaunchObserveSeconds 2
```

Generated `build/` and `out/` folders are local outputs and should not be committed.

## External Dependencies

This alpha does not ship third-party source, BMW source, or BMW assets. Some checks depend on local operator setup:

- BMW Git repository `digital-3d-car-models`, used as a read-only external dependency.
- Seriengrafik SVN trunk, usually available under `C:\repositories\trunk` on an operator machine.
- Ramses Composer / Headless / Logic for RaCo-side workflows.
- Blender with the SG-Toolkit for Blender visual review.
- Python 3.11 or later.

Profile configs may reference operator-local paths under `C:\repositories\trunk`. Adjust local configuration if your checkout uses a different path.

## Non-Destructive Behaviour

SGFX QA Preflight is designed to stay out of the way of active work:

- It does not write to BMW Git.
- It does not commit to SVN.
- It does not post to Jira.
- It does not mark manual visual review as done.
- It does not auto-approve screenshots or delivery evidence.
- It writes generated outputs under local output paths, normally `out/`, which must stay uncommitted.

If a command appears to modify source content unexpectedly, stop and report it. That is not intended behaviour.

## What Still Requires Manual Review

Every visual or behavioral verdict remains a human decision. The Quality Hero review still requires operator review in the relevant tools, including:

- Blender Visual Check.
- Constants Info Verification.
- Final Look Comparison between RaCo, Blender, and Epic.
- Functionality Test in RaCo.
- Anchor Points Test in RaCo.
- CarPaints Test in RaCo.
- Documentation review for README / changelog accuracy.

The tool can suggest a review order, collect evidence, and surface waiting states. The human reviewer decides what is actually OK.

## Feedback

This is a local alpha intended for teammate review and process alignment. Please report missing checks, noisy output, unclear wording, or any behavior that does not match the real Seriengrafik / BMW workflow.
