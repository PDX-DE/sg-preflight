# Changelog

All notable changes to this project should be documented in this file.

The format follows Keep a Changelog style and uses a simple pre-release-friendly structure.

## [Unreleased]

### Timeline

#### 2026-04-18

- working tree: the native C++ shell now starts directly on the English SG intro instead of forcing the language screen, restores the original `Español` label for the reserved language list, and ports the quit/leave-run prompt closer to the OG two-stage Unleashed message-window rhythm with a banner-first open, a second pause-window reveal for the Yes/No chooser, and a more faithful selection-card animation path
- working tree: the native C++ shell now runs on a real D3D12 + ImGui DX12 renderer instead of the old D3D11 path, so the fullscreen installer shell, DDS chrome, and bundled `D3D12/` runtime payload finally match the intended DX12 packaging direction instead of only shipping dormant support files
- working tree: the native C++ shell now adds a real pre-intro language selector and shell-owned localization layer for `EN`, `ES`, `DE`, and `RO`, so the installer-style shell can enter the SG operator flow through a dedicated language screen while translating its own headers, prompts, guide labels, status lines, and main installer pages without rewriting backend/checker truth
- working tree: the native C++ shell now renames the installer header to SG Preflight, remaps real Unleashed pause/window/decide WAV cues onto hover, confirm, page-transition, and prompt-close behavior, swaps the bottom guide to keyboard-first prompts/hotkeys, ports the quit prompt and shell close-out closer to the OG message-window flow, and moves `Run`, `Evidence`, `Files`, and `Stages` onto the same installer canvas model instead of the older boxed dashboard layout; portable bundle staging now also carries the root `D3D12/`, `dxcompiler.dll`, and `dxil.dll` payload while excluding mirrored `.svn` metadata from the copied workspace
- working tree: the native C++ shell now renders the actual installer backdrop through a transparent root window, ports the OG continuous right-side canvas and compact in-container next-button treatment onto `Introduction`, `Select`, and `Review`, and keeps the left image slot reserved with a non-character placeholder so later replacement art can drop into the real installer composition without reopening the layout model
- working tree: the native C++ shell now paints immediately and hydrates the Python desktop-state backend on a background thread, which removes the blank white hung startup window from the plain build and keeps the DX11 shell responsive while initial profiles/actions/blockers/recent state load
- working tree: the native C++ shell now partially resets its body composition toward the real installer-wizard structure instead of layering SG dashboard panels over installer chrome: `Introduction`, `Select`, and `Review` are rebuilt around the main installer container, selection lives inside the primary page again, and the copy is tightened around SG operator choices/readiness instead of text-wall explanation
- working tree: the refreshed plain native build is smoke-verified at `build/native-installer-fullscreen/Release/sg_preflight_native_shell.exe`; a portable restage toward `..\sgpf-native-bundle\sg_preflight_native_shell.exe` was started but did not finish inside the current tooling window, so `build/latest_native_shell_path.txt` was returned to the smoke-verified plain build path instead of advertising an incomplete bundle
- working tree: the native C++ shell now uses the full viewport instead of the work-area viewport, loads the real installer left-image set plus `miles_electric_icon`, keeps the loading spinner/pulse strictly in the actual run/install phase, and anchors the main page closer to the OG installer container layout instead of the extra top flow panel
- working tree: the latest plain native build is smoke-verified at `build/native-installer-fullscreen/Release/sg_preflight_native_shell.exe`, and the latest portable another-PC bundle is staged at `..\sgpf-native-bundle/sg_preflight_native_shell.exe` with `build/latest_native_shell_path.txt` updated to that bundled exe
- working tree: the native C++ shell now ports more of the real `installer_wizard.cpp` draw layer directly, including top/bottom scanline-bar treatment, installer-style borders, bottom navigation button containers, page-specific button-guide behavior, and message-prompt/modal rhythm
- working tree: the current installer-layer build is smoke-verified at `build/native-installer-layer/Release/sg_preflight_native_shell.exe`, and the refreshed another-PC bundle is staged at `build/native-installer-layer-bundle/sg_preflight_native_shell.exe` with `build/latest_native_shell_path.txt` updated to that bundled exe

#### 2026-04-17

- `18f3d05` `fix(ui): refresh generated report styling`
- `b52a933` `fix(ui): restore readable light mode`
- `cc5da75` `fix(ui): repair guide card layout`
- `dce4741` `fix(ui): compact operator tutorial rail`
- `447af66` `refactor(ui): add guided tutorial path`
- `94b566c` `docs(status): record unity export validation`
- `396762d` `feat(reporting): restyle SG html report outputs`
- `a19f1e5` `refactor(ui): apply mission-control operator styling`
- `e4ef4d6` `refactor(ui): apply project06 loading treatment`
- `4818249` `refactor(ui): tune native loading animation`
- `bf4be12` `fix(ui): tighten native loading screen match`
- `87c073c` `feat(ui): add native loading screen easter egg`
- `9bba8c1` `fix(ui): stop live loading from jumping to top`
- `d50f870` `fix(ui): make live loading detail scrollable`
- `e3ff320` `fix(ui): widen and compress demo pages`
- `c4dcb3e` `feat(ui): add dark mode and clearer operator guidance`
- `2021122` `feat(operator): align qa actions with sg checker flow`
- working tree: SG checker coverage now has a shared discovery/catalog layer, `checkall.bat` scope is covered through `repo_checker_all`, and the main docs now split current operator-surface narrative from future desktop-shell research
- working tree: the main status/docs narrative now treats the browser UI as the current SG QA operator surface, keeps future desktop GUI work explicitly research-only, and removes Unity/AssetRipper recovery notes from the main product-status story
- working tree: repo-checker and scene-check runs now parse frozen real checker outputs into structured file-level evidence, and that evidence now flows through action pages, Files And Proof, stage readiness, and stage-specific copy exports
- working tree: unused-resource and delivery-checklist actions now feed the same structured checker-evidence flow, and the Python 3.11-incompatible nested f-string in `ui.py` is fixed so GitHub Actions can import the operator UI again
- working tree: `qa_stack` now aggregates child checker evidence into one parent payload, and the first experimental PySide6 desktop operator shell can run the same SG actions, show the same checker evidence, expose blockers/manual cards, and open local files without replacing the browser UI
- working tree: the desktop shell now translates the local UnleashedRecomp options-menu language into Qt chrome with scanline header bars, category tabs, grid-framed panels, TV-static evidence framing, and a bottom button-guide band while keeping the SG QA product framing intact
- working tree: `daily_live_matrix` now runs the ready per-profile QA stacks and aggregates their child checker evidence into one fleet-level `Open first` surface, the CLI now exposes `launch-action` plus `desktop-state` polling commands for native clients, and an experimental `desktop_native/` C++ + Dear ImGui shell scaffold now sits over that same Python backend contract
- working tree: the native C++ shell now browses both recent actions and recent runs, drills from action state into linked run outputs and source-of-truth files, exposes broader copy/export surfaces from the shared evidence model, and the Windows build helper now resolves a standard local `cmake.exe` install path instead of assuming PATH is already refreshed
- working tree: the native C++ shell now auto-discovers the repo root and local Python from the built executable path, so `build\...\Release\sg_preflight_native_shell.exe` stops pointing at the build folder, and the native chrome now translates more of the local UnleashedRecomp systems into custom UI: animated scanline bars, amber title-square motion, framed panels, animated action tabs, selection cards, and cue hooks instead of stock ImGui widgets
- working tree: the native C++ shell now ports the real UnleashedRecomp menu timing/layout systems more directly from `DrawTitle`, `DrawContainer`, `DrawCategories`, and `ButtonGuide`: the shell uses a fixed 1280x720 virtual canvas, source-style category motion, side-aligned bottom guide layout, proportional body fonts instead of `Consolas`, and no longer trips the Dear ImGui parent-boundary warning in the button-guide path
- working tree: the native C++ shell now auto-discovers a local `UnleashedRecompResources` bundle, loads the real `general_window.dds`, `select.dds`, `light.dds`, and `options_static*.dds` textures into the D3D11 UI, and keeps direct OTF font loading temporarily instead of the upstream `im_font_atlas.bin` snapshot path
- working tree: the native C++ shell now starts borderless fullscreen by default, swaps the overloaded dashboard for an installer-style `Select` / `Run` / `Evidence` / `Files` / `Stages` screen flow, tones down the noisiest Unleashed texture overlays, and adds local WAV UI cues plus an optional installer-music toggle sourced from the same resource bundle
- working tree: the native C++ shell no longer renders character/cast art from installer textures, keeps the Unleashed reference language abstract, simplifies the fullscreen background/static load for smoother frame pacing, and makes each step read more like a dedicated page than a flashing wall of panels
- working tree: the native C++ shell now defaults to the current monitor's native size instead of letterboxing a fixed 1280x720 canvas, supports `--windowed --width --height` overrides, falls back to D3D11 WARP when hardware device creation fails, and retunes the PDA framing toward calmer teal/amber readability instead of flat neon-green smear
- working tree: the native C++ shell now recognizes a portable bundle layout with sibling `workspace`, `python`, `resources`, and `fonts` folders, the build script writes `build/latest_native_shell_path.txt` after successful native builds, and a new `scripts/package_native_shell_bundle.ps1` can stage a copyable another-PC test bundle around the current exe
- working tree: the native C++ shell now ports the installer-wizard flow more directly instead of relying on the older dashboard-screen model: it uses a real `Introduction -> Select -> Review -> Run -> Evidence -> Files -> Stages` page sequence, a shared wizard-flow rail, installer-style back/next navigation, frame-based page-transition timing, and a calmer left-context/right-content layout that keeps SG QA semantics while following the OG installer rhythm more closely
- working tree: the portable native-shell bundle script now clears long-path staging folders more reliably before copying the refreshed wizard-port build, so another-PC test bundles can be restaged from deep mirrored-SVN workspaces without manual cleanup

#### 2026-04-16

- `0376165` `feat(ui): deepen evidence workflow and progress drilldown`
- `1ed615a` `fix(ui): unstick loading overlay and expand live progress detail`
- `5b50a34` `feat(ui): add live progress and previous-run diffing`
- `3aa8e84` `feat(ui): add workflow-stage operator starts`

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

- The repo now has a shared SG checker catalog in code, exposed through `python -m sg_preflight list-checkers --json`, the Home `Show SG checker coverage` foldout, and the new `docs/sg-checker-coverage-matrix.md` source-of-truth note
- The workspace action list now includes `repo_checker_all`, which covers the full mirrored repo scope behind `checkall.bat` through direct Python invocation instead of calling the batch wrapper
- Main docs now keep the product identity focused on SG QA / evidence / handoff work, while future desktop-shell architecture and Unleashed-inspired visual-direction notes live under `docs/research/`
- Pre-delivery workflow status, run-page action lists, and the recommended per-car QA stack now surface a delivery-checklist readiness bridge based on the mirrored `.pdx\checkers\deliveryChecklist` assets, so SG-side delivery expectations sit visibly between deterministic proof and BMW-side smoke
- Delivery-checklist actions now write their own readiness summary and log, including mirrored checklist assets plus BMW repo/helper discovery, instead of pretending the external BMW-owned checklist flow is runnable end-to-end on this machine
- Per-car QA actions now also wrap `.pdx\checkers\printNotUsedResources.py`, and the recommended QA stack now includes a local unused-resource scan before the later manual or BMW-blocked stages
- Repo-checker actions now wrap the real SG checker stack more truthfully by running `code_style_checker\check_all_styles.py` before `.pdx\checkers\executeChecks.py`, and their summaries now report style/license scope plus execute-check phase coverage instead of pretending the wrapper is only one script
- Repo-checker and scene-check actions now parse their raw logs into a shared checker-evidence payload, backed by frozen real-output fixtures, so the UI can show `Open these files first`, surface concrete affected paths, and cite SG checker file evidence directly in Jira / QA Hero / delivery copy blocks
- Unused-resource and delivery-checklist actions now also parse into the shared checker-evidence payload, so operators can open unused files or mirrored checklist assets directly while blocked BMW prerequisites stay visible as follow-up text instead of being buried in summary-only logs
- The top operator path is now a real clickable tutorial rail with arrows, plain-language hints, and page-specific jump targets on Home, guided starts, workflow-stage starts, Run, Result, Files And Proof, and Action pages, so teammates can click straight to the next relevant section instead of treating the strip as decorative chrome
- The tutorial rail is now compact and readable at normal desktop widths instead of stretching into one tall band; step cards wrap cleanly, use a real arrow separator, and keep the helper text in a usable width
- Guide cards under the hero no longer dump their paragraph text into the narrow step-number column, so the three-step walkthrough reads in normal sentences instead of one word per line
- Light mode now repaints the shared mission-control chrome with bright readable surfaces instead of leaving the late dark-skin overrides in place, so the header, tutorial rail, hero, cards, and buttons stay legible after the theme toggle
- Legacy SG HTML report files now get upgraded to the current operator-report skin when opened through `/ui/files`, and file links now carry a fresh-cache timestamp so old beige report responses stop sticking in the browser
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
