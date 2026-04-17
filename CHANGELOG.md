# Changelog

All notable changes to this project should be documented in this file.

The format follows Keep a Changelog style and uses a simple pre-release-friendly structure.

## [Unreleased]

### Added

- Internal proprietary `LICENSE` for repository ownership and internal-use handling
- End-to-end CLI flow for `probe`, `materialize`, and `run`
- Canonical live-profile registry for `G70`, `G65`, and `G45`, now widened with additional real BMW slices such as `G50`, `G78`, `NA0`, `NA5-NA8`, `F70`, `F74`, `F78`, `G48`, `G68`, `U06`, `U10`, `U11`, and `U12`
- Shared Python service layer for bundle execution, report generation, and persistent run records
- Local FastAPI/Jinja operator UI with Home, Run, Result, and Files And Proof views
- PowerShell operator-UI launcher/check script for teammate sessions
- Cached fast mirror audit plus on-demand deep mirror audit for the mirrored SVN
- CLI surfaces for `list-profiles`, `run-profile`, and `ui`
- CLI surfaces for `list-actions` and `run-action`
- `retro-extract` CLI command for turning Whiteboard retro exports into structured pain/action artifacts
- Validation packs for `anchors`, `constants`, `carpaints`, and `project_sanity`
- JSON and HTML reporting with grouped findings and pack-level summaries
- Markdown QA handoff reporting with grouped findings, workflow context, and owner/action hints
- Smoke-test automation in `scripts/run_smoke_test.ps1`
- Real-SG smoke automation in `scripts/run_real_sg_smoke.ps1`
- Additional live smoke scripts for `G65`, `G45`, and a side-by-side live matrix summary
- Source-drop analysis and audit documentation under `docs/`
- Workbook-backed and legacy-JSON-backed carpaint normalization
- SG-shaped project discovery and bundle materialization helpers
- GitHub issue forms, pull request template, and CI workflow
- Internal repository notices via `NOTICE.md`, `SECURITY.md`, and GitHub issue-template config
- Next-chat handoff prompt in `docs/next-chat-handoff-prompt-2026-04-14.md`
- Explicit QA-workflow alignment note for mapping SG Preflight against the current SG / Quality-Hero process
- Live SG config in `config/sg_rules_live.json` for a first real `G70` end-to-end slice
- Live SG configs for `G65` and classic `G45`
- Anchor validation support for multiple config-driven rule groups such as scale, tire-pressure, and sensor anchors

### Changed

- The top operator path is now a real clickable tutorial rail with arrows, plain-language hints, and page-specific jump targets on Home, guided starts, workflow-stage starts, Run, Result, Files And Proof, and Action pages, so teammates can click straight to the next relevant section instead of treating the strip as decorative chrome
- Operator and report spacing is now less cramped at normal desktop widths: page shells, hero blocks, section heads, guide cards, and standalone SG HTML reports all have wider insets and calmer padding for side-by-side demo use
- AssetRipper export verification is now grounded in a real local Unity validation pass: the recovered project was confirmed as a `2019.2.21f1` Unity project with `Assets` / `Packages` / `ProjectSettings` plus recovered `Assembly-CSharp` sources, and the exact legacy editor is now installed locally; the remaining blocker is explicitly narrowed to local Unity licensing because the editor exits with `Unity has not been activated with a valid License` before full project open/import
- Operator UI now uses a darker sharper mission-control visual system inspired by the locally available Project06/P-06 menu code: left-anchored shell, compact title bars, clearer four-step route strip, slimmer section density, bevelled controls, and a refit loading screen that matches the same interface language instead of reading like a generic internal dashboard
- SG-generated HTML reports and the `/ui/files` report path now pick up the same darker mission-control visual system, so report pages like `g45-report.html` no longer fall back to the old beige standalone styling when opened from the operator flow
- Full `python -m unittest discover -s tests -v` coverage now completes on this machine again because live `project_sanity` manifest generation no longer spends minutes in duplicate path/Lua scans
- Operator loading overlay now stays hidden on ordinary pages until a real run or action actually starts, fixing the stuck `NOW LOADING...` state on `/ui`
- Operator loading overlay now lets the operator click individual steps to inspect exact per-step detail, step-specific events, nested child progress, target paths, and current commands instead of only showing one flat status strip
- Operator UI Home now starts with common QA-task entry points so teammates can choose by intent instead of profile code first
- Operator UI Home now keeps `What Changed?` as the only primary start path above the fold and demotes daily matrix, repo checker, and direct car-picking to secondary entry points
- Operator UI now also supports workflow-stage starts for before commit, before review, pre-delivery, post-integration, and Jira / QA Hero evidence work, while carrying that stage context into run results and Files And Proof
- Operator UI and CLI now expose one-click SG QA actions for the wider workflow, including daily live matrix, repo checker, recommended per-car QA stack, scene check, and explicit BMW smoke blockers
- Guided checks now show one recommended car first and move the remaining cars into a separate secondary section
- Run pages now push one default full-check path and keep the quick-check path secondary
- Run pages now use one explicit primary launch model, surface `Files this check will use` near the main action, and keep quick-check customization plus secondary actions behind foldouts
- Operator UI language and layout now reduce framework detail by default so teammates can start from daily jobs, not tooling concepts
- Operator UI now defaults to dark mode, keeps a persistent light/dark toggle in the shared header, and also lets teammates hide or show the in-page guide layer without leaving the current screen
- Home, guided, run, result, evidence, and action pages now lead with a clearer first-time path, inline "what is this?" help popovers, and more explicit step-by-step copy for teammate and PM demos
- Visible UI labels now use cleaner sentence case instead of old title-case wording across headings, buttons, exports, and helper flows
- Demo-critical action, result, and Files And Proof pages now use a wider denser layout so the useful summary fits at normal desktop zoom instead of forcing narrow centered browsing
- Expanded live-loading detail now behaves like a real scrollable full-screen surface instead of a clipped fixed modal, and the shared CSS/JS asset URLs now include a cache-busting version so local browsers pick up UI fixes immediately
- The loading overlay now uses a native code retro game-style loading card instead of the plain `NOW LOADING...` heading and spinner, while keeping the real SG progress, ETA, logs, and exact-step drilldown below it
- The loading overlay now uses a simpler Sonic-06-style native screen based on the real local `R.gif` frame timing and placement, renders before the page body content on running/queued pages to reduce first-paint flicker, and keeps the expanded live-detail area from re-rendering noisily when the underlying step data has not changed
- The native Sonic-06-style loading screen now uses a smaller lower-contrast wordmark, a darker flatter plate, and a discrete 23-frame chromatic-split loop so the on-screen result lands closer to the local gif reference instead of a generic CSS interpretation
- The Project06 source drop that is locally present was used where it was actually useful: the web loader now borrows the original project's loading-screen mode ideas and UI-gradient treatment patterns at the HTML/CSS/JS layer, without pretending that the missing Unity retail art assets or scenes are available here
- Operator UI now starts from "what changed?" guided launchers so teammates can choose constants, anchors, carpaints, or file/reference sanity before choosing a car
- Run pages now expose a recommended QA stack action per car so teammates can launch the available SG-side automation from one button
- Result pages now include a short "do this next" section plus copy-ready quick-update, full-handoff, and per-finding text
- Result pages now compare the current run against the previous completed run for the same profile so operators can see new findings, resolved findings, count deltas, and copy a diff-ready status update
- Result and evidence pages now show a stage-readiness summary so operators can see what proof is ready and what remains manual or blocked for the selected workflow step
- Result and Files And Proof now add evidence-completeness scoring, explicit local-vs-full-stage readiness counts, and clearer proof/manual/blocked grouping per workflow stage
- Result and Files And Proof now expose richer copy-ready exports for Jira implementation updates, Jira positive and negative test notes, QA Hero notes, pre-delivery summaries, and delivery-document snippets
- Result and Files And Proof now include a manual-review companion with Blender-vs-RaCo checklist text, screenshot evidence slots, and copy-ready manual verification records
- Result pages now center one `First Thing To Do` panel, pin the best matching source file for the top finding, and make a problem-specific handoff copy action primary
- Home, Run, and Result pages now add more explicit "if you are unsure, do this" guidance so teammate pilots can stay on the recommended path instead of browsing the whole surface
- Run and action result pages now expose a live `NOW LOADING...` overlay with estimated progress, coarse ETA, full step visibility, persisted framework-event history, and live action-log tail while long checks are still running
- Files And Proof now groups outputs into `Reports`, `Source-of-truth files`, and `Run metadata`, with the first relevant SG file pinned first
- Action result pages now mirror the same plain-language flow as run results for completed, blocked, and failed SG-side actions
- Operator UI now restarts cleanly during local work via `python -m sg_preflight ui --reload`, and stale local server/template mismatches now fall back to warnings instead of crashing result pages
- Operator UI Home now shows where the tool fits in the real SG QA workflow, including explicit covered / partial / blocked stages
- Operator readiness now surfaces the BMW screenshot-test repo as a first-class prerequisite instead of hiding BMW-side blockers
- Operator UI Home/Run/Result flow now prioritizes operator decisions, current live signal, and clearer next actions instead of raw filesystem detail
- Operator UI first-load work is lighter because Home no longer scans every live profile for full source discovery up front
- Operator UI now uses retro-driven profile goals and focus areas so teammates can see why each live slice is worth running
- HTML reports now prioritize presentation-friendly grouped findings before raw detail tables
- Reports now carry workflow context like car model, trim, delivery phase, review target, and evidence source
- Real SG smoke scripts now consume the shared `run-profile` path instead of duplicating profile definitions in PowerShell
- Findings now carry richer evidence details for operator drilldown, including duplicate carpaint metadata and anchor-rule context
- `project_sanity` now persists exact source-file and line evidence for path-reference findings and unused Lua drilldown
- Mirror-audit notes are now visible on the operator Home page so sampled deep-audit drift is easier to interpret
- One-click action records now persist under `out/operator-ui/actions` with logs, summaries, and generated artifacts
- Smoke-test summary output now includes an executive snapshot and grouped takeaways
- Smoke-test flow now generates markdown handoff artifacts in addition to JSON and HTML reports
- README now documents the current local source-drop workflow and intended branch/release hygiene
- README and docs now include a teammate pilot playbook for real operator-session validation
- Generated outputs and local retro/source-drop folders are now ignored cleanly for a publishable repo state
- HTML reporting now stays compatible with Python 3.11 in CI
- GitHub Actions now use Node 24-ready `actions/checkout@v5` and `actions/setup-python@v6`
- CI now treats `demo-broken` as an expected-failure fixture and accepts exit code `2` explicitly
- `materialize` now auto-discovers live SG inputs such as `RES_*_AnchorPoints.rca`, `*_Pivot_Master.json`, `Module_constants_*.lua`, and `CarPaint.json`
- `anchors` normalization now supports zipped `.rca` scene bundles directly
- `constants` normalization now supports real SG `Pivot_Master` JSON and `Module_constants_*.lua` sources
- SG discovery and project-sanity helpers now recognize live helper script names and hyphenated SG environment conventions
- Legacy SG `CarPaint.json` normalization now uses live `StyleID` semantics plus actual clearcoat/undercoat fields when available
- `project_sanity` now reads `racoVersion` directly from zipped `.rca` payloads and classifies SG-relative scene links separately from true absolute-path risks
- `project_sanity` text indexing now falls back to plain-text `.rca` files when a scene is not zipped, which removes false `unused_lua` warnings in SG-shaped fixtures
- Real live `G70` smoke output is now much cleaner: cross-car contamination and unused Lua survive as actionable warnings, while SG-internal relative links no longer flood the report
- Repository metadata now marks the package as proprietary/internal-use in `pyproject.toml`
- Live reporting and smoke automation now support side-by-side comparison across `G70`, `G65`, and `G45`
- Anchor root selection now prefers the richest matching subtree when SG scenes contain duplicate root names

### Known Gaps

- MINI coverage is still missing even though BMW profile coverage is now much broader
- The operator UI is intentionally local-first; a thin desktop wrapper is still deferred until adoption requires one-click packaging
- Direct RaCo-runtime execution of helper scripts such as `read_json_carpaints.py` is still not part of the current CLI-first flow
- Full BMW screenshot-smoke coverage still depends on BMW-side access and a local `digital-3d-car-models` clone
- BMW smoke target mapping for the canonical live profiles is still missing, so the new action remains intentionally blocked even after BMW repo access is restored
