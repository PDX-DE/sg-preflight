# SG Checker Coverage Matrix

This document tracks the real SG checker/tooling layer against the current `sg-preflight` integration surface.

Coverage labels used here:

- `direct`: `sg-preflight` invokes the underlying Python checker/tool directly.
- `wrapped`: `sg-preflight` exposes the stage and keeps it inside the shared action/result/evidence flow, but the step still depends on external tooling or later-stage prerequisites.
- `reference`: the original `.bat` wrapper exists in the mirrored repo, but `sg-preflight` intentionally uses the underlying Python tools instead of calling the batch file.

| Checker / stage | Real file(s) | What it does | SG Preflight coverage | Current operator surface | Main blockers / manual follow-up |
| --- | --- | --- | --- | --- | --- |
| `code_style_checker/check_all_styles.py` | `.pdx/checkers/code_style_checker/check_all_styles.py` | BMW style, formatting, and license-style checks | `direct` | `repo_checker_all`, `repo_checker_idcevo`, `repo_checker_classic`, `repo_checker_profile__<profile>`, `qa_stack__<profile>` | Blocked only when the mirrored script is missing; parsed style findings now feed the shared checker-evidence model |
| `executeChecks.py` | `.pdx/checkers/executeChecks.py` | Lua, shader, tabbing, newline, and binary-location checks with SG exclusions | `direct` | same repo-checker actions as above | Blocked only when the mirrored script is missing; parsed phase/file hits now feed the shared checker-evidence model |
| `checkall.bat` | `.pdx/checkers/checkall.bat` | Full-repo style + Lua + shader wrapper | `reference` | covered by `repo_checker_all` without calling the batch file | Batch exists for SG reference, but `sg-preflight` prefers direct Python invocation |
| `checkcars.bat` | `.pdx/checkers/checkcars.bat` | Classic `Cars` scope wrapper around style + Lua + shader checks | `reference` | covered by `repo_checker_classic` and relevant per-car repo-checker actions | Batch exists for SG reference; direct integration avoids shell-wrapper dependency |
| `checkcars_IDCevo.bat` | `.pdx/checkers/checkcars_IDCevo.bat` | `Cars_IDCevo` scope wrapper around style + Lua + shader checks | `reference` | covered by `repo_checker_idcevo` and relevant per-car repo-checker actions | Batch exists for SG reference; direct integration avoids shell-wrapper dependency |
| `printNotUsedResources.py` | `.pdx/checkers/printNotUsedResources.py` | Finds resource files not referenced by scanned `.rca` scenes | `direct` | `unused_resources__<profile>`, `qa_stack__<profile>` | Needs a live profile with `resources` plus at least one `.rca` scene; parsed output now yields file-backed unused-resource evidence in the shared operator flow |
| `deliveryChecklist/*` | `.pdx/checkers/deliveryChecklist/*`, `.pdx/checkers/deliveryChecklist/Delivery Data - BMW.xlsx` | BMW delivery helper GUI/tooling, perspectives, export-size reporting, Excel packaging bridge | `wrapped` | `delivery_checklist__<profile>`, `delivery-checklist read --profile <profile>`, `qa_stack__<profile>`, pre-delivery workflow stage | Still partial until BMW repo access plus `ci/scripts/car_manager.py` or `ci/scripts/test/main.py` exists locally; parsed readiness logs surface openable mirrored checklist assets; workbook read-in is read-only evidence guidance, not delivery approval |
| `check_scenes.py` | `check_scenes.py` | Runs scene checks with `RaCoHeadless.exe` and workbook output | `direct` | `scene_check__<profile>`, `qa_stack__<profile>` | Needs local `RaCoHeadless.exe`; parsed scene errors now carry scene-file and workbook-row evidence, but workbook review is still operator-facing rather than automatic approval |
| BMW smoke | BMW repo `ci/scripts/car_manager.py` or `ci/scripts/test/main.py` | BMW export, screenshots, and interface smoke | `wrapped` | `bmw_screenshot_smoke__<profile>`, pre-delivery workflow stage | Blocked without BMW repo access, helper scripts, viewer/runtime setup, and per-profile target mapping; screenshot review remains manual |

## Current reading

- `sg-preflight` now has one shared SG checker catalog in code and can dump it through `python -m sg_preflight list-checkers --json`.
- The operator UI Home view now exposes the same checker catalog under `Show SG checker coverage`.
- The browser UI remains the current operator surface, but checker discovery, action readiness, result artifacts, and workflow-stage messaging are all driven from the same SG-side reality.
- Future desktop-shell direction is tracked separately under `docs/research/`; this matrix stays focused on the current SG QA workflow surface instead of future visual-direction research.
- Repo checker, scene check, unused-resource scan, and delivery-checklist readiness now all feed one normalized checker-evidence payload, so action pages, Files And Proof, stage readiness, and copy exports can reuse the same file-backed evidence surface.
- The delivery-checklist workbook read-in is available as `python -m sg_preflight delivery-checklist read --profile <profile> --json`; it only reads the operator-local workbook and keeps final delivery judgement manual.
- The remaining maturity gap is no longer basic SG checker awareness or first-pass parsing for the main local SG-side actions; it is the remaining checker-adjacent outputs beyond these paths plus BMW-side access/execution.
