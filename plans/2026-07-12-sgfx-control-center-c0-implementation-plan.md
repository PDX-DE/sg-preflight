# SGFX QA Control Center C0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the equal-weight Qt Home launcher with one profile-neutral SGFX QA Control Center that runs exactly the four deterministic local packs, presents seven truthful QA gates, preserves the existing 19 surfaces and eight capabilities, and provides bounded presentation/inspection polish without changing the QA truth model.

**Architecture:** Python owns canonical profile resolution, the narrow action, evidence reduction, lifecycle, and all filesystem/process boundaries. Qt/QML receives one sanitized `QaHubSnapshot`, opaque preview tokens, and typed capability descriptors; it composes the experience but never derives verdicts or constructs commands. The QA truth path graduates before the optional Ramses turntable, and the current packaged default remains unchanged until its separate cutover gate.

**Tech Stack:** Python 3.10+ (`unittest`, PySide6/Qt Quick), existing SGFX action/run persistence, QML with the existing `QtQuick`, `QtQuick.Controls`, `QtQuick.Layouts`, and `SGFX 1.0` roots, C++20/CMake with the installed Ramses SDK, SDL3, and existing `nlohmann_json` target.

## Global Constraints

- Run Python verification with `..\sg-preflight\.venv\Scripts\python.exe -B`; do not use the Store Python stub.
- Preserve exactly the eight IDs in `UI_CAPABILITIES`; C0 adds no ninth capability.
- Preserve all 19 registered operational surface descriptors and the five existing navigation groups.
- With no valid explicit local preference or operator selection, the selected profile is the empty string; registry order must never select a car.
- The Home action ID is exactly `sgfx_preflight__<canonical-profile>`, kind exactly `sgfx_preflight`, and packs exactly `anchors`, `constants`, `carpaints`, `project_sanity`.
- The Home action may read only accepted source roots and may write only below the configured SGFX `out` root. It must not call `profile_stack`, repo checkers, unused-resource checks, RaCo, BMW tools, Jira, SVN, Git push, CI, rack, or vehicle systems.
- C0 does not implement or auto-run Ramses R0 validation. Preview evidence is presentation-only and cannot reduce a gate.
- QML receives no raw path, command, URL, credential, environment, exception, source object, network client, or unrestricted process handle.
- Human and external gates never become `passed` from page visibility, activity, a local preflight, or document presence.
- `Presentation view` changes chrome only. It must not reload data, start a renderer, or change profile, gate, evidence, action descriptors, or permissions.
- Preview limits are 24 frames, 480 x 270 per frame, a 256 MiB LRU cache, one below-normal-priority worker, and a 30-second timeout. Reduced motion uses one static frame.
- Reference sizes remain 1280 x 720 and 1024 x 640. The primary action and all seven gates remain keyboard reachable at both sizes.
- Use repository-owned OFL Inter for operational text and OFL Fredoka only for short display accents. Add no network font, restricted DynaFont, game font, copied asset, or new production dependency.
- Keep Jira posting and Clockodo submission outside the product. Produce copy-ready Jira evidence and an accurate local time ledger; never fabricate duration.
- Do not change the no-argument packaged default in C0. No push, SVN write, package publish, or external service mutation is part of this plan.

---

## File and Responsibility Map

### QA truth path

- Create `sg_preflight/qa_hub.py`: immutable seven-gate definitions, safe state reducer, latest local preflight projection, copy-ready evidence summary, and deterministic next-action rules.
- Modify `sg_preflight/home_context.py`: retain bounded five-entry activity only; compose no verdict.
- Modify `sg_preflight/dashboard_preferences.py`: expose an explicit-preference-only reader without changing existing NiceGUI fallback behavior.
- Modify `sg_preflight/desktop/qt_quick_controller.py`: accept empty selection, discover the one Home action off-thread, enforce stale identity, refresh Home after a current completion, and publish sanitized lifecycle state.
- Modify `sg_preflight/qa_operator_actions.py`: declare the exact profile-scoped `sgfx_preflight` action.
- Modify `sg_preflight/qa_actions.py`: execute only the four deterministic packs beneath the action output root.
- Modify `sg_preflight/qa_action_persistence.py`: add the `sgfx_preflight` progress plan.
- Modify `sg_preflight/desktop/ui_capabilities.py`: extend `diagnostic.run` ownership to Home and fail closed on every non-approved action while leaving the inventory at eight.
- Modify `sg_preflight/full_qa_pass.py` and `sg_preflight/desktop/page_presenter.py`: align the detailed Full QA evidence order with the same seven gates without auto-running anything.

### Product shell

- Replace `sg_preflight/desktop/qml/components/HomePage.qml`: one selected scope, primary action, Pipeline Spine, gate detail, local evidence, and next action.
- Create `sg_preflight/desktop/qml/components/QaPipelineSpine.qml`: ordered gate selection and keyboard traversal.
- Create `sg_preflight/desktop/qml/components/QaGateDetail.qml`: check rows and registered-route requests.
- Create `sg_preflight/desktop/qml/components/QaContextPreview.qml`: generic art, opaque frames, bounded playback, scrub input, and reduced-motion behavior.
- Modify `sg_preflight/desktop/qml/Main.qml`: one-product copy, Presentation view, typed action wiring, inspection handoff, and context restoration.
- Modify `sg_preflight/desktop/qml/SGFX/Theme.qml`: semantic type, spacing, depth, and bounded motion tokens.
- Modify `sg_preflight/desktop/qt_quick_app.py`: load the two repository-owned fonts and register the preview image provider without exposing paths to QML.

### Bounded preview

- Create `sg_preflight/desktop/preview_coordinator.py`: profile/scene resolution, one-worker scheduling, source fingerprint, timeout, cache budget, stale rejection, and diagnostic pre-emption.
- Create `sg_preflight/desktop/preview_image_provider.py`: opaque generation-bound image keys backed only by accepted cache frames.
- Create `cpp/include/sgfx/cine/ramses_preview.h`: public preview request/result contract.
- Create `cpp/src/ramses_preview.cpp`: authored-pass scene lifecycle and bounded readback implementation extracted from the existing viewer seam.
- Create `cpp/apps/ramses_preview_cli.cpp`: strict local CLI and machine-readable manifest writer.
- Modify `cpp/CMakeLists.txt`: build, test, install, and copy runtime DLLs for the preview helper.
- Modify `scripts/build_sgfx_exe.py` and `sg_preflight/bundle_manifest.py`: package and prove the helper/fonts only when the exact audited assets exist.

### Verification and records

- Create `tests/test_qa_hub.py`: gate reducer, next-action, sanitization, bounded reads, and copy-ready summary tests.
- Modify `tests/test_qa_actions.py`: narrow action registry/execution and forbidden-call regression tests.
- Modify `tests/test_qt_quick_capabilities.py`: Home audit, output/source containment, lifecycle, and unchanged inventory tests.
- Modify `tests/test_qt_quick_core.py`: empty selection, snapshot, stale completion, and controller refresh tests.
- Modify `tests/test_qt_quick_host.py`: rendered Home, Presentation, accessibility, geometry, and same-data tests.
- Create `tests/test_qt_quick_preview.py`: cache, timeout, opaque token, stale generation, pre-emption, and reduced-motion tests.
- Modify `tests/test_qt_quick_grafiks.py`, `tests/test_qt_quick_presenters.py`, `tests/test_full_qa_pass.py`, `tests/test_bundle_manifest.py`, and `tests/test_qml_format.py`: inspection, gate alignment, package, provenance, and format regressions.
- Create `docs/tickets/sgfx-control-center-c0.md`: Jira-ready scope, acceptance, implementation, test, risk, and artifact sections.
- Create `docs/worklogs/sgfx-control-center-c0.md`: timestamped factual work ledger with start/end, elapsed time, task, result, and commit; no automatic Clockodo write.
- Create `docs/pilots/sgfx-control-center-c0-pilot.md`: opt-in before/after teammate-pilot worksheet with the six approved operator-value measures and no invented target.
- Modify `CHANGELOG.md`: user-visible C0 behavior only after its corresponding code is green.

---

### Task 1: Make Qt profile selection explicit and neutral

**Files:**
- Modify: `sg_preflight/dashboard_preferences.py:146-164,427-438`
- Modify: `sg_preflight/desktop/qt_quick_controller.py:198-255,304-389,1139-1166`
- Modify: `sg_preflight/desktop/qt_quick_app.py:107-177`
- Modify: `sg_preflight/cross_car_comparison.py:19-34,245-320`
- Modify: `sg_preflight/team_digest_board.py:27-38,131-170`
- Modify: `sg_preflight/dashboard_pages_config.py:970-990,1328-1345`
- Modify: `sg_preflight/dashboard/main.py:550-560,2638-2655`
- Modify: `sg_preflight/desktop/evidence_model.py:1070-1100`
- Modify: `sg_preflight/full_qa_pass.py:605-630`
- Modify: `sg_preflight/cli/_common.py:1665-1680,1880-1895,2645-2660`
- Modify: `tests/test_qt_quick_core.py:1847-2033`
- Modify: `tests/test_qt_quick_host.py:733-929`
- Modify: `tests/test_cross_car_comparison.py`
- Modify: `tests/test_team_digest_board.py`
- Modify: `tests/test_full_qa_pass.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `dashboard_profile_options(*, bmw_root, profile_scope)` and local operator-state JSON readers.
- Produces: `resolve_explicit_dashboard_profile(*, workspace, bmw_root) -> str`; `load_shell_context(...)["selected_profile_id"]` may be `""`; `DesktopController.currentProfileId` remains `""` until an explicit valid choice exists.

- [x] **Step 1: Write failing explicit-selection tests**

Add tests that distinguish an absent preference, a valid persisted preference, an invalid persisted preference, and an explicit runtime argument:

```python
def test_shell_context_keeps_selection_empty_without_valid_explicit_input(self) -> None:
    from sg_preflight.desktop.qt_quick_controller import load_shell_context

    with tempfile.TemporaryDirectory() as temp_dir:
        payload = load_shell_context(
            workspace=Path(temp_dir),
            profile_id="",
            profile_resolver=lambda **_kwargs: "",
        )

    self.assertGreater(len(payload["profile_options"]), 0)
    self.assertEqual(payload["selected_profile_id"], "")

def test_shell_context_accepts_only_a_canonical_explicit_profile(self) -> None:
    from sg_preflight.desktop.qt_quick_controller import load_shell_context

    with tempfile.TemporaryDirectory() as temp_dir:
        payload = load_shell_context(
            workspace=Path(temp_dir),
            profile_id="g45",
            profile_resolver=lambda **_kwargs: "",
        )

    self.assertEqual(payload["selected_profile_id"], "G45")
```

Update the headless host test so an omitted profile remains empty and no file is written; keep the existing explicit `G70` selection test.

- [x] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
..\sg-preflight\.venv\Scripts\python.exe -B -m unittest tests.test_qt_quick_core.TestQtShellRoute tests.test_qt_quick_host.TestQtQuickHostRuntime -v
```

Expected: FAIL because `load_shell_context` currently falls back to `options[0]` and the host resolves an omitted profile.

- [x] **Step 3: Add an explicit-preference-only reader**

Keep `_resolve_dashboard_profile_id` unchanged for the NiceGUI surfaces and add this narrow public function:

```python
def resolve_explicit_dashboard_profile(
    *,
    workspace: Path | str,
    options: list[dict[str, str]],
) -> str:
    return _dashboard_preferred_profile_id(workspace, options)
```

In `resolve_dashboard_profile`, call the new reader over the full registry options and return `""` when no valid local preference exists. In `load_shell_context`, remove both first-option fallbacks:

```python
requested = str(profile_id or "").strip()
selected = next(
    (option["id"] for option in options if option["id"].casefold() == requested.casefold()),
    "",
)
if not selected and not requested:
    resolved = profile_resolver(workspace=Path(workspace).resolve(), bmw_root=bmw_root)
    selected = next(
        (option["id"] for option in options if option["id"].casefold() == resolved.casefold()),
        "",
    )
```

Allow `_accept_shell_profile` to accept `selected_profile_id == ""`; reject only a non-empty noncanonical selection. Update options first, then emit `currentProfileChanged` only when the canonical or empty value actually differs.

- [x] **Step 4: Run the profile-neutral gates and verify GREEN**

Run:

```powershell
..\sg-preflight\.venv\Scripts\python.exe -B -m unittest tests.test_qt_quick_core.TestQtShellRoute tests.test_qt_quick_core.TestQtPageReadSafety tests.test_qt_quick_host.TestQtQuickShell tests.test_qt_quick_host.TestQtQuickHostRuntime -v
```

Expected: PASS; omitted selection is empty, explicit selection remains canonical, reads remain off-thread, and no preference file is written.

- [x] **Step 5: Write failing generic-default regression tests**

Require cross-car comparison to return `status="not_recorded"` and `summary="Choose two profiles to compare."` until two distinct explicit profiles are supplied. Require an absent Team Digest profile list to remain empty. Require Full QA's comparison profile default and the three CLI parser defaults to be empty strings/tuples. Scan generic runtime/QML copy touched by C0 for an implicit G65/G70 pair while allowing profile registry definitions and explicitly labelled CLI examples.

```python
def test_generic_surfaces_do_not_invent_a_profile_pair(self) -> None:
    comparison = build_cross_car_comparison(workspace=self.root, left_profile="", right_profile="")
    digest = build_team_daily_digest_board(workspace=self.root, profiles=None)
    self.assertEqual(comparison["status"], "not_recorded")
    self.assertEqual((comparison["left_profile"], comparison["right_profile"]), ("", ""))
    self.assertEqual(digest["profiles"], [])
    self.assertEqual(digest["risk_items"], [])
```

- [x] **Step 6: Run the generic-default tests and verify RED**

Run:

```powershell
..\sg-preflight\.venv\Scripts\python.exe -B -m unittest tests.test_cross_car_comparison tests.test_team_digest_board tests.test_full_qa_pass tests.test_cli -v
```

Expected: FAIL because the current cross-car, Team Digest, Full QA comparison, desktop convenience readers, and CLI parsers inject G70/G65.

- [x] **Step 7: Remove implicit profile pairs without deleting real profile definitions**

Set comparison defaults and `DEFAULT_TEAM_PROFILES` to empty values. `_profile_pair` returns `("", "")` unless both distinct explicit inputs are present. `build_cross_car_comparison` returns a neutral no-data payload before calling any risk reader when that contract is unmet. `_unique_profiles(None)` returns `()` rather than restoring a pair. Make the Cross-Car subtitle model-neutral, pass explicit selected/configured profiles from callers, set Full QA's `comparison_profile` default to `""`, and change CLI defaults to empty while retaining clearly labelled examples in help text.

Do not remove `G65`, `G70`, or any other genuine profile from `profiles.py`, BMW target maps, evidence fixtures, or focused example tests.

- [x] **Step 8: Run profile-neutral product regressions**

Run:

```powershell
..\sg-preflight\.venv\Scripts\python.exe -B -m unittest tests.test_cross_car_comparison tests.test_team_digest_board tests.test_full_qa_pass tests.test_cli tests.test_qt_quick_core tests.test_qt_quick_host -v
```

Expected: PASS; explicit profile examples still work, but no generic default or registry ordering chooses G65/G70.

- [x] **Step 9: Commit the neutral-selection boundary**

```powershell
git add sg_preflight/dashboard_preferences.py sg_preflight/desktop/qt_quick_controller.py sg_preflight/desktop/qt_quick_app.py sg_preflight/cross_car_comparison.py sg_preflight/team_digest_board.py sg_preflight/dashboard_pages_config.py sg_preflight/dashboard/main.py sg_preflight/desktop/evidence_model.py sg_preflight/full_qa_pass.py sg_preflight/cli/_common.py tests/test_qt_quick_core.py tests/test_qt_quick_host.py tests/test_cross_car_comparison.py tests/test_team_digest_board.py tests/test_full_qa_pass.py tests/test_cli.py
git commit -m "fix(qt): require explicit profile selection"
```

### Task 2: Add the exact four-pack `sgfx_preflight` action

**Files:**
- Modify: `sg_preflight/qa_operator_actions.py:123-371`
- Modify: `sg_preflight/qa_action_persistence.py:15-55`
- Modify: `sg_preflight/qa_actions.py:566-823,1392-1462`
- Modify: `tests/test_qa_actions.py:58-326`

**Interfaces:**
- Consumes: `services.execute_profile_run(profile, RunRequest, repo_root) -> RunRecord`, `VALID_PACKS`, and existing action persistence.
- Produces: `SAFE_PREFLIGHT_PACKS: tuple[str, ...]`; `OperatorAction(kind="sgfx_preflight")`; `_execute_sgfx_preflight(record, root) -> tuple[dict[str, Any], list[dict[str, str]], list[str]]`.

- [x] **Step 1: Write failing registry and isolation tests**

Add tests that assert the exact action contract and patch every forbidden executor seam to fail if touched:

```python
def test_sgfx_preflight_action_is_exact_profile_scoped_and_ready(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        profile = create_temp_g65_profile(root)
        action = get_operator_action("sgfx_preflight__g65", root, profiles=[profile])

    self.assertEqual(action.action_id, "sgfx_preflight__g65")
    self.assertEqual(action.kind, "sgfx_preflight")
    self.assertEqual(action.scope, "profile")
    self.assertEqual(action.profile_id, "G65")
    self.assertTrue(action.ready)
    self.assertEqual(action.command_preview, "internal: run four deterministic SGFX packs")

def test_execute_sgfx_preflight_calls_only_the_four_pack_service(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        profile = create_temp_g65_profile(root)
        action = get_operator_action("sgfx_preflight__g65", root, profiles=[profile])
        completed = _completed_profile_run(root, profile)
        with mock.patch("sg_preflight.qa_actions.execute_profile_run", return_value=completed) as execute:
            with mock.patch("sg_preflight.qa_actions._execute_profile_stack", side_effect=AssertionError):
                record = execute_operator_action(action, root)

    request = execute.call_args.args[1]
    self.assertEqual(request.packs, ["anchors", "constants", "carpaints", "project_sanity"])
    self.assertEqual(Path(request.output_root), Path(record.paths["output_root"]) / "preflight")
    self.assertEqual(record.status, "completed")
```

The fixture `_completed_profile_run` must return a real `RunRecord` with report paths beneath the supplied action output root and summary counts `errors=0`, `warnings=1`, `info=2`.

- [x] **Step 2: Run action tests and verify RED**

Run:

```powershell
..\sg-preflight\.venv\Scripts\python.exe -B -m unittest tests.test_qa_actions.TestQaActions -v
```

Expected: FAIL because no `sgfx_preflight` action or executor branch exists.

- [x] **Step 3: Declare the narrow action and progress plan**

Add:

```python
SAFE_PREFLIGHT_PACKS = ("anchors", "constants", "carpaints", "project_sanity")
```

For each profile, append this action before the broader stack:

```python
OperatorAction(
    action_id=f"sgfx_preflight__{profile.profile_id.lower()}",
    label="Run local QA checks",
    description=f"Run the four deterministic SGFX validation packs for {profile.profile_id}.",
    kind="sgfx_preflight",
    scope="profile",
    ready=source_project_root.exists() and profile.config_path.exists(),
    blocker_message=(
        ""
        if source_project_root.exists() and profile.config_path.exists()
        else f"The project root or config for {profile.profile_id} is missing."
    ),
    profile_id=profile.profile_id,
    project_root=str(source_project_root),
    command_preview="internal: run four deterministic SGFX packs",
)
```

Add an `ACTION_PROGRESS_PLANS["sgfx_preflight"]` sequence containing only `queued`, `preflight`, and `finalize`.

- [x] **Step 4: Implement the minimal isolated executor**

```python
def _execute_sgfx_preflight(
    record: ActionRecord,
    root: Path,
) -> tuple[dict[str, Any], list[dict[str, str]], list[str]]:
    profile = next(
        item for item in list_run_profiles(root)
        if item.profile_id.casefold() == record.profile_id.casefold()
    )
    child_output = Path(record.paths["output_root"]) / "preflight"
    child = execute_profile_run(
        profile,
        RunRequest(
            profile_id=profile.profile_id,
            packs=list(SAFE_PREFLIGHT_PACKS),
            fail_on="never",
            output_root=child_output,
            run_id=f"{record.run_id}-preflight",
        ),
        root,
    )
    child_paths = {
        f"preflight_{key}": str(value)
        for key, value in child.paths.items()
        if str(value).strip()
    }
    record.paths.update(child_paths)
    counts = child.summary or {}
    summary = {
        "title": f"Local QA checks - {profile.profile_id}",
        "profile_id": profile.profile_id,
        "packs": list(SAFE_PREFLIGHT_PACKS),
        "errors": int(counts.get("errors", 0) or 0),
        "warnings": int(counts.get("warnings", 0) or 0),
        "info": int(counts.get("info", 0) or 0),
        "child_run_id": child.run_id,
        "lines": [
            f"Four-pack result: {int(counts.get('errors', 0) or 0)} errors, "
            f"{int(counts.get('warnings', 0) or 0)} warnings, "
            f"{int(counts.get('info', 0) or 0)} info"
        ],
    }
    artifacts = [
        _artifact("Local QA HTML report", Path(child.paths["html_report"])),
        _artifact("Local QA Markdown report", Path(child.paths["markdown_report"])),
        _artifact("Local QA JSON report", Path(child.paths["json_report"])),
        _artifact("Local QA run record", Path(child.paths["run_record"])),
    ]
    return summary, artifacts, list(child.notes[:3])
```

Dispatch this branch before `profile_stack`. Do not call `_visual_review_prep_entries` for `sgfx_preflight`; it can reference sources outside the bounded action output. Preserve visual-review prep for existing action kinds.

- [x] **Step 5: Run action isolation and persistence tests**

Run:

```powershell
..\sg-preflight\.venv\Scripts\python.exe -B -m unittest tests.test_qa_actions tests.test_run_profile_acceptance -v
```

Expected: PASS; the new action returns only four-pack evidence, while existing action kinds remain unchanged.

- [x] **Step 6: Commit the four-pack backend**

```powershell
git add sg_preflight/qa_operator_actions.py sg_preflight/qa_action_persistence.py sg_preflight/qa_actions.py tests/test_qa_actions.py
git commit -m "feat(qa): add isolated local preflight action"
```

### Task 3: Expose only the narrow action through Home's existing capability

**Files:**
- Modify: `sg_preflight/desktop/ui_capabilities.py:15-328`
- Modify: `sg_preflight/desktop/qt_quick_controller.py:304-680,839-966,993-1166`
- Modify: `tests/test_qt_quick_capabilities.py:19-132,332-1176`
- Modify: `tests/test_qt_quick_core.py:1770-2033`

**Interfaces:**
- Consumes: exact `OperatorAction`, current controller identity, configured read-only roots, and action output root.
- Produces: `audit_ui_diagnostic_action(..., expected_profile_id: str = "", owning_page_id: str = "") -> bool`; one sanitized `diagnostic.run` descriptor inside the current Home payload.

- [x] **Step 1: Write the failing fail-closed audit matrix**

Extend the inventory test to require `diagnostic.run.owning_pages == ("home", "full-qa-pass", "batch-full-qa-pass")` while `len(UI_CAPABILITIES) == 8`. Add table-driven negatives for `profile_stack`, repo checker, unused resources, scene check, BMW smoke, malformed ID, mismatched profile, workspace scope, missing project root, source escape, output escape, and reparse points.

```python
accepted = audit_ui_diagnostic_action(
    action,
    read_only_roots=(source,),
    output_root=output,
    allowed_output_root=root / "out",
    expected_profile_id="G45",
    owning_page_id="home",
)
self.assertTrue(accepted)
```

Add controller tests proving no action is published while selection is empty and exactly `sgfx_preflight__g45` is published after selecting G45.

- [x] **Step 2: Run focused capability tests and verify RED**

Run:

```powershell
..\sg-preflight\.venv\Scripts\python.exe -B -m unittest tests.test_qt_quick_capabilities.TestUiCapabilityInventory tests.test_qt_quick_capabilities.TestCapabilityControllerIntegration tests.test_qt_quick_core.TestQtShellRoute -v
```

Expected: FAIL because Home is not an owner, the audit only accepts delivery checklist, and shell-context reads publish no actions.

- [x] **Step 3: Implement the exact two-policy audit**

Keep delivery-checklist acceptance only for the two detailed Full QA pages. For Home, accept only this predicate:

```python
if owning_page_id == "home":
    return (
        action.kind == "sgfx_preflight"
        and action.scope == "profile"
        and action.profile_id.casefold() == expected_profile_id.casefold()
        and action.action_id.casefold() == f"sgfx_preflight__{expected_profile_id.casefold()}"
        and bool(action.ready)
        and bool(action.project_root)
        and _contained(Path(action.project_root), read_only_roots)
        and _output_root_is_allowed(output_root, allowed_output_root)
    )
```

Every other Home kind returns `False`. Retain the existing exact delivery-checklist predicate for `full-qa-pass` and `batch-full-qa-pass`.

- [x] **Step 4: Discover Home actions inside the shell worker**

Inside `_schedule_shell_context`, after adapting the shell payload, read its canonical `selected_profile_id`; only when non-empty list operator actions and append the one accepted descriptor:

```python
adapted["actions"] = [
    capability_descriptor(
        "diagnostic.run",
        label="Run local QA checks",
        action_id=action.action_id,
    )
    for action in raw_actions
    if audit_ui_diagnostic_action(
        action,
        read_only_roots=diagnostic_read_roots,
        output_root=diagnostic_output_root,
        allowed_output_root=workspace / "out",
        expected_profile_id=selected_profile_id,
        owning_page_id="home",
    )
]
```

This remains off the GUI thread. Do not publish `command_preview`, paths, blocker detail, or action objects.

- [x] **Step 5: Extend invocation and current-completion refresh**

Allow `runDiagnostic` from `home`, `full-qa-pass`, and `batch-full-qa-pass`. Pass current page/profile into the audit. On a successful current Home completion, schedule a new shell-context read; on a stale completion, persist the backend record but change no route, selection, payload, or error state.

```python
if succeeded and is_current_page and self._current_identity is None:
    self._clear_artifacts()
    if self._current_route_id == HOME_ROUTE_ID:
        self._schedule_shell_context()
    else:
        self.refresh()
```

- [x] **Step 6: Run capability, source-mutation, output-containment, and stale-result tests**

Run:

```powershell
..\sg-preflight\.venv\Scripts\python.exe -B -m unittest tests.test_qt_quick_capabilities tests.test_qt_quick_core.TestQtShellRoute -v
```

Expected: PASS; inventory remains eight, only the exact Home action is enabled, source mutation and output escape fail, one effect runs at a time, queued cancellation stays truthful, and current completion refreshes Home.

- [x] **Step 7: Commit the Home capability boundary**

```powershell
git add sg_preflight/desktop/ui_capabilities.py sg_preflight/desktop/qt_quick_controller.py tests/test_qt_quick_capabilities.py tests/test_qt_quick_core.py
git commit -m "feat(qt): expose audited home preflight"
```

### Task 4: Build the frontend-neutral `QaHubSnapshot`

**Files:**
- Create: `sg_preflight/qa_hub.py`
- Modify: `sg_preflight/home_context.py:13-62`
- Modify: `sg_preflight/desktop/qt_quick_controller.py:222-255`
- Create: `tests/test_qa_hub.py`
- Modify: `tests/test_dashboard.py:50-122`
- Modify: `tests/test_qt_quick_core.py:1770-2033`

**Interfaces:**
- Consumes: sanitized profile options, the selected profile ID, current capability descriptors, at most 12 `ActionRecord` values, at most 12 `RunRecord` values, and five activity rows.
- Produces: `build_qa_hub_snapshot(...)-> dict[str, Any]` with exactly the approved top-level contract; `render_qa_evidence_summary(snapshot) -> str` for local copy-ready use.

- [x] **Step 1: Write reducer and contract tests first**

Create `tests/test_qa_hub.py` with table cases for empty selection, action available, queued/running, completed zero findings, completed warnings, completed errors, execution failure, and malformed records. Assert all seven gates remain ordered and that human/external gates do not become passed.

```python
EXPECTED_GATE_IDS = (
    "context",
    "asset",
    "interface",
    "variants",
    "visual",
    "review",
    "delivery",
)

def test_completed_warnings_are_findings_and_never_overall_green(self) -> None:
    snapshot = build_qa_hub_snapshot(
        workspace=self.root,
        profile_options=[{"id": "G45", "label": "G45"}],
        selected_profile_id="G45",
        actions=[self._action_descriptor("sgfx_preflight__g45")],
        action_records=[self._record(errors=0, warnings=2, info=1)],
        run_records=[],
        activity=[],
    )
    states = {gate["id"]: gate["state"] for gate in snapshot["gates"]}
    self.assertEqual(states["asset"], "findings")
    self.assertEqual(states["review"], "human_review")
    self.assertNotIn("overallStatus", snapshot)
    self.assertNotIn("percent", repr(snapshot))
```

Add a recursive safety assertion rejecting absolute paths, `://`, command keys, credential keys, and raw exceptions anywhere in the returned snapshot.

- [x] **Step 2: Run the new tests and verify RED**

Run:

```powershell
..\sg-preflight\.venv\Scripts\python.exe -B -m unittest tests.test_qa_hub -v
```

Expected: FAIL because `sg_preflight.qa_hub` does not exist.

- [x] **Step 3: Implement immutable gate definitions and exact state reduction**

Use frozen, slotted definitions:

```python
@dataclass(frozen=True, slots=True)
class QaGateDefinition:
    gate_id: str
    label: str
    route_ids: tuple[str, ...]
    default_state: str
    owner_label: str


QA_GATES = (
    QaGateDefinition("context", "Project context", ("setup-doctor",), "not_recorded", "Operator"),
    QaGateDefinition("asset", "Asset integrity", ("full-qa-pass",), "not_run", "Seriengrafik"),
    QaGateDefinition("interface", "Export & interface", ("api-version-coverage", "disabled-tests", "export-size-trend"), "external", "Pipeline owner"),
    QaGateDefinition("variants", "Variants", ("country-variant-coverage",), "not_recorded", "Topic owner"),
    QaGateDefinition("visual", "Visual evidence", ("screenshot-test-state",), "external", "Visual reviewer"),
    QaGateDefinition("review", "Review & decisions", ("risk-score", "manual-review"), "human_review", "Reviewer"),
    QaGateDefinition("delivery", "Delivery & handoff", ("delivery-checklist", "operator-handoff"), "human_review", "Project coordinator"),
)
```

Accept an action record only when `kind == "sgfx_preflight"`, `profile_id` matches, and `action_id == f"sgfx_preflight__{profile.casefold()}"`. For a completed record, errors or warnings produce `findings`; only zero errors and zero warnings produce `passed`. Never infer freshness from wall-clock age.

- [x] **Step 4: Implement deterministic next-action priority**

```python
def _next_action(
    selected_profile_id: str,
    asset_state: str,
    action: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not selected_profile_id:
        return {"kind": "select_profile", "label": "Choose profile", "routeId": "", "capabilityId": "", "actionId": ""}
    if asset_state in {"queued", "running"}:
        return {"kind": "wait", "label": "Local QA checks are running", "routeId": "", "capabilityId": "", "actionId": ""}
    if asset_state == "failed":
        return {"kind": "retry", "label": "Retry local QA checks", **_action_identity(action)}
    if asset_state == "findings":
        return {"kind": "review", "label": "Review local findings", "routeId": "full-qa-pass", "capabilityId": "page.navigate", "actionId": ""}
    if asset_state in {"not_run", "not_recorded"} and action is not None:
        return {"kind": "run", "label": "Run local QA checks", **_action_identity(action)}
    return {"kind": "review", "label": "Continue with export and interface evidence", "routeId": "api-version-coverage", "capabilityId": "page.navigate", "actionId": ""}
```

No QML code may duplicate this priority.

- [x] **Step 5: Compose the bounded snapshot in the shell loader**

Keep `build_home_context` unchanged except for explicitly limiting its responsibility to activity. In `load_shell_context`, call `list_recent_action_records(workspace, limit=12)` and `list_recent_run_records(workspace, limit=12)` under narrow exception handling, then build the snapshot. Merge profile options and `selected_profile_id` into the approved camel-case Qt projection only once.

The top-level result must contain exactly:

```python
{
    "schemaVersion": 1,
    "scopeLabel": "3D Car QA",
    "selectedProfile": {"id": selected, "label": selected_label} if selected else {},
    "profileOptions": safe_options,
    "contextFields": context_fields,
    "gates": gates,
    "selectedGateId": "asset" if selected else "context",
    "latestLocalRun": latest_local_run,
    "nextAction": next_action,
    "activity": activity[:5],
    "readOnly": True,
    "isApproval": False,
}
```

Store copy-ready text inside `latestLocalRun["evidenceSummary"]`; do not add another top-level key.

- [x] **Step 6: Run reducer, shell, and bounded-read tests**

Run:

```powershell
..\sg-preflight\.venv\Scripts\python.exe -B -m unittest tests.test_qa_hub tests.test_dashboard.TestHomeContext tests.test_qt_quick_core.TestQtShellRoute tests.test_qt_quick_core.TestQtPageReadSafety -v
```

Expected: PASS; startup performs bounded record reads only, every state and priority is covered, and the snapshot contains no unsafe value.

- [x] **Step 7: Commit the QA truth model**

```powershell
git add sg_preflight/qa_hub.py sg_preflight/home_context.py sg_preflight/desktop/qt_quick_controller.py tests/test_qa_hub.py tests/test_dashboard.py tests/test_qt_quick_core.py
git commit -m "feat(qa): add control center truth model"
```

### Task 5: Replace the Home tile grid with the QA Control Center

**Files:**
- Replace: `sg_preflight/desktop/qml/components/HomePage.qml`
- Create: `sg_preflight/desktop/qml/components/QaPipelineSpine.qml`
- Create: `sg_preflight/desktop/qml/components/QaGateDetail.qml`
- Create: `sg_preflight/desktop/qml/components/QaContextPreview.qml`
- Modify: `sg_preflight/desktop/qml/Main.qml:12-372`
- Modify: `sg_preflight/desktop/qml/SGFX/Theme.qml`
- Modify: `tests/test_qt_quick_host.py:472-837`
- Modify: `tests/test_qml_format.py`

**Interfaces:**
- Consumes: `DesktopController.currentPayload`, `capabilityState`, `capabilityError`, and only the descriptors already present in `payload.nextAction`/`payload.actions`.
- Produces: QML signals `profileRequested(string)`, `actionRequested(string, var)`, `routeRequested(string)`, `gateSelected(string)`, and `inspectionRequested()`; no command construction.

- [x] **Step 1: Write failing source and headless runtime tests**

Require the four component files, reject the old six-tile grid, and assert one primary action plus the seven exact gate IDs.

```python
self.assertNotIn("homeTileRepeater", home_source)
self.assertIn("QaPipelineSpine", home_source)
self.assertIn("QaGateDetail", home_source)
self.assertIn("QaContextPreview", home_source)
self.assertNotIn("Grafiks", main_source)
self.assertIn("Open 3D inspection", main_source)
```

At runtime, inspect `pipelineGateIds`, `primaryActionLabel`, `selectedGateId`, and `visibleCheckRowCount` at both contract sizes. When selection is empty, expect `Choose profile` and `primaryActionEnabled == False`.

- [x] **Step 2: Run the Home contract and verify RED**

Run:

```powershell
..\sg-preflight\.venv\Scripts\python.exe -B -m unittest tests.test_qt_quick_host.TestQtQuickShell tests.test_qml_format -v
```

Expected: FAIL because the old launcher grid is still present and the new components do not exist.

- [x] **Step 3: Add semantic visual and motion tokens**

Extend `Theme.qml` with stable tokens rather than page-local numbers:

```qml
readonly property string operationalFont: "Inter"
readonly property string displayFont: "Fredoka"
readonly property int space1: 6
readonly property int space2: 10
readonly property int space3: 16
readonly property int space4: 24
readonly property int focusDuration: 160
readonly property int panelDuration: 280
readonly property int routeDuration: 500
readonly property int entranceLimit: 700
readonly property int entranceStagger: 55
```

Keep all existing status colors and reduced-motion helpers.

- [x] **Step 4: Implement ordered gate selection in `QaPipelineSpine.qml`**

The component must derive nothing beyond keyboard selection:

```qml
Item {
    id: root
    required property var gates
    required property string selectedGateId
    required property bool reducedMotion
    signal gateSelected(string gateId)
    readonly property var gateIds: {
        const ids = [];
        for (let index = 0; index < gates.length; ++index)
            ids.push(gates[index].id);
        return ids;
    }
    function move(delta) {
        const current = Math.max(0, gateIds.indexOf(selectedGateId));
        const next = Math.max(0, Math.min(gateIds.length - 1, current + delta));
        if (gateIds.length > 0)
            gateSelected(gateIds[next]);
    }
    Keys.onLeftPressed: move(-1)
    Keys.onRightPressed: move(1)
}
```

Each delegate writes state as text, has an accessible name containing label and state, and shows focus with border plus shape/weight—not color alone.

- [x] **Step 5: Implement gate details and central Home composition**

`QaGateDetail.qml` renders at most four rows without changing their state and emits only registered `routeId`. `HomePage.qml` exposes exact test properties and delegates all actions upward:

```qml
readonly property var snapshot: payload && payload.schemaVersion === 1 ? payload : ({})
readonly property var gates: snapshot.gates || []
readonly property string primaryActionLabel: snapshot.nextAction ? snapshot.nextAction.label || "" : ""
readonly property bool primaryActionEnabled: Boolean(
    snapshot.selectedProfile && snapshot.selectedProfile.id
    && snapshot.nextAction && snapshot.nextAction.capabilityId
    && pageState === "ready" && !capabilityBusy
)
```

Clicking the primary action forwards its existing `capabilityId` and `actionId`; Home does not concatenate `sgfx_preflight__` itself.

- [x] **Step 6: Wire Main without exposing a second product mode**

Rename every product-facing Grafiks label to `Open 3D inspection` while retaining the internal capability and host object. Bind Home signals to typed controller calls. Keep all 19 sidebar routes and `/` jump entries.

- [x] **Step 7: Format QML and run rendered headless tests**

Run:

```powershell
..\sg-preflight\.venv\Scripts\python.exe -B scripts\check_qml_format.py
..\sg-preflight\.venv\Scripts\python.exe -B -m unittest tests.test_qt_quick_host tests.test_qt_quick_capabilities.TestCapabilityQmlBindings tests.test_qml_format -v
```

Expected: PASS with exact QML roots, no old tile grid, no raw action construction, seven keyboard-reachable gates, and no overflow at 1280 x 720 or 1024 x 640.

- [x] **Step 8: Commit the QA-first Home**

```powershell
git add sg_preflight/desktop/qml tests/test_qt_quick_host.py tests/test_qml_format.py
git commit -m "feat(qt): build QA control center home"
```

### Task 6: Align detailed Full QA and produce copy-ready local evidence

**Files:**
- Modify: `sg_preflight/full_qa_pass.py:500-770`
- Modify: `sg_preflight/desktop/page_presenter.py`
- Modify: `sg_preflight/desktop/qml/renderers/WorkflowRenderer.qml`
- Modify: `tests/test_full_qa_pass.py`
- Modify: `tests/test_qt_quick_presenters.py`
- Modify: `tests/test_qt_quick_host.py`

**Interfaces:**
- Consumes: the exact seven `QA_GATES`, existing read-only page payloads, and the same audited local-preflight action descriptor.
- Produces: `steps` in the seven-gate order; `evidence_summary` with profile, counts, provenance, owners, retest hash when recorded, and next safe action; no Jira transport.

- [x] **Step 1: Write failing gate-order and semantic tests**

```python
self.assertEqual(
    [step["id"] for step in payload["steps"]],
    ["context", "asset", "interface", "variants", "visual", "review", "delivery"],
)
self.assertNotIn("onboarding", repr(payload["steps"]).casefold())
self.assertNotIn("comparison", repr(payload["steps"]).casefold())
self.assertNotIn("digest", repr(payload["steps"]).casefold())
self.assertFalse(payload["is_approval"])
```

Assert the country-variant route appears under `variants`, risk/manual review precede delivery, and no load triggers the local action or BMW work.

- [x] **Step 2: Run Full QA and presenter tests and verify RED**

Run:

```powershell
..\sg-preflight\.venv\Scripts\python.exe -B -m unittest tests.test_full_qa_pass tests.test_qt_quick_presenters -v
```

Expected: FAIL because the existing step model still mixes onboarding, comparison, and digest into QA semantics.

- [x] **Step 3: Rebuild the read-only step assembly around gate IDs**

Use a single ordered tuple imported from `qa_hub`. Each step owns existing evidence only:

```python
gate_payloads = {
    "context": _context_gate(profile, onboarding),
    "asset": _asset_gate(profile, latest_local_preflight),
    "interface": _interface_gate(api_version, disabled_tests, export_size),
    "variants": _variants_gate(country_variant),
    "visual": _visual_gate(screenshot_state),
    "review": _review_gate(risk, manual_review),
    "delivery": _delivery_gate(checklist, workbook, integration, handoff),
}
steps = [gate_payloads[definition.gate_id] for definition in QA_GATES]
```

Keep onboarding as optional context copy outside `steps`; keep comparison and digest as separate routes only.

- [x] **Step 4: Add one copy-ready evidence summary**

Build text exclusively from accepted fields:

```python
evidence_summary = "\n".join(
    [
        f"Profile: {profile}",
        f"Local checks: {errors} errors, {warnings} warnings, {info} info",
        f"Provenance: {provenance or 'Not recorded'}",
        f"Open owner: {owner or 'Not recorded'}",
        f"Retest hash: {retest_hash or 'Not recorded'}",
        f"Next action: {next_action_label}",
    ]
)
```

Do not include a readiness score, approval wording, a raw path, or a Jira call.

- [x] **Step 5: Run aligned Full QA, presenter, and QML tests**

Run:

```powershell
..\sg-preflight\.venv\Scripts\python.exe -B -m unittest tests.test_full_qa_pass tests.test_qt_quick_presenters tests.test_qt_quick_host.TestQtQuickTask10QmlContract -v
```

Expected: PASS; Full QA and Home share gate order, detailed evidence remains read-only until explicit action, and all renderers preserve their stable keys.

- [x] **Step 6: Commit detailed evidence alignment**

```powershell
git add sg_preflight/full_qa_pass.py sg_preflight/desktop/page_presenter.py sg_preflight/desktop/qml/renderers/WorkflowRenderer.qml tests/test_full_qa_pass.py tests/test_qt_quick_presenters.py tests/test_qt_quick_host.py
git commit -m "feat(qa): align full QA evidence gates"
```

### Task 7: Add same-data Presentation view and the existing inspection handoff

**Files:**
- Modify: `sg_preflight/desktop/qml/Main.qml`
- Modify: `sg_preflight/desktop/qml/components/HomePage.qml`
- Modify: `tests/test_qt_quick_host.py`
- Modify: `tests/test_qt_quick_grafiks.py`

**Interfaces:**
- Consumes: the current controller payload, current profile, selected gate, and existing `grafiks.launch` host/capability.
- Produces: QML-only `presentationView: bool`; exact QA context survives both chrome changes and a 3D-inspection round trip.

- [x] **Step 1: Write failing same-data and naming tests**

At runtime capture this tuple before, during, and after Presentation view:

```python
truth = (
    runtime.controller.currentProfileId,
    root.property("selectedGateId"),
    json.dumps(runtime.controller.currentPayload.get("gates", []), sort_keys=True),
    json.dumps(runtime.controller.currentPayload.get("actions", []), sort_keys=True),
)
```

Assert the tuple never changes, the controller generation does not advance, no shell/page loader is called, and no preview request begins merely from entering Presentation. Update Grafiks tests so only internal IDs retain `grafiks`; user-facing QML copy says `Open 3D inspection`.

- [x] **Step 2: Run host and inspection tests and verify RED**

Run:

```powershell
..\sg-preflight\.venv\Scripts\python.exe -B -m unittest tests.test_qt_quick_host.TestQtQuickShell tests.test_qt_quick_grafiks -v
```

Expected: FAIL because Presentation view does not exist and visible Grafiks copy remains.

- [x] **Step 3: Implement Presentation as chrome state only**

Add to `Main.qml`:

```qml
property bool presentationView: false
readonly property string selectedGateId: homePage.selectedGateId
function setPresentation(enabled) {
    presentationView = enabled;
    sidebarOpen = !enabled;
    Qt.callLater(homePage.restoreFocus);
}
```

The Presentation control calls `setPresentation(true)`. Esc first exits overlays, then Presentation, then follows existing back/exit guidance. Bind widths and visibility only; do not call `refresh`, `initialize`, `navigate`, `selectProfile`, or any preview method.

- [x] **Step 4: Rename only the product-facing inspection surface**

Keep `grafiks.launch`, `GrafiksHostAdapter`, provenance checks, and internal object names. Change visible labels and safe errors to `3D inspection`. The launch input remains exactly:

```qml
window.desktopController.invokeCapability(
    "grafiks.launch",
    {"profile_id": window.desktopController.currentProfileId}
)
```

The existing external host hides and restores the same Qt root; add a test proving current profile, selected gate, payload, and route are unchanged after restoration.

- [x] **Step 5: Run same-data, keyboard, and host-restoration tests**

Run:

```powershell
..\sg-preflight\.venv\Scripts\python.exe -B -m unittest tests.test_qt_quick_host tests.test_qt_quick_grafiks -v
```

Expected: PASS; Presentation and inspection are destinations inside one product, not alternate QA state models.

- [x] **Step 6: Commit presentation and inspection polish**

```powershell
git add sg_preflight/desktop/qml/Main.qml sg_preflight/desktop/qml/components/HomePage.qml tests/test_qt_quick_host.py tests/test_qt_quick_grafiks.py
git commit -m "feat(qt): add same-data presentation view"
```

### Task 8: Add the bounded Python preview coordinator and opaque image channel

**Files:**
- Create: `sg_preflight/desktop/preview_coordinator.py`
- Create: `sg_preflight/desktop/preview_image_provider.py`
- Modify: `sg_preflight/desktop/qt_quick_controller.py`
- Modify: `sg_preflight/desktop/qt_quick_app.py`
- Modify: `sg_preflight/desktop/qml/components/QaContextPreview.qml`
- Create: `tests/test_qt_quick_preview.py`

**Interfaces:**
- Consumes: a canonical `RunProfile`, an internally resolved compatible `exported.ramses`, a fixed audited helper executable, controller generation, selected profile, reduced-motion flag, and diagnostic lifecycle.
- Produces: controller properties `previewState`, `previewToken`, `previewFrameCount`, `previewFrameIndex`, `previewLabel`; slot `selectPreviewFrame(int) -> bool`; `image://sgfx-preview/<opaque-token>/<index>` only.

- [ ] **Step 1: Write failing scheduling, cache, and secrecy tests**

Create a fake helper that writes a manifest and tiny PNG fixtures beneath the supplied output directory. Cover success, missing scene, unsupported profile, timeout, oversized manifest, stale generation, stale profile, diagnostic pre-emption, hidden playback, and reduced motion.

```python
def test_stale_generation_never_publishes_a_token(self) -> None:
    coordinator = self._coordinator(helper=self.fake_helper)
    first = coordinator.request(profile=self.profile, generation=4, reduced_motion=False)
    coordinator.invalidate(generation=5)
    self.fake_helper.complete(first.request_id)
    self.assertEqual(coordinator.public_state().state, "fallback")
    self.assertEqual(coordinator.public_state().token, "")

def test_public_state_contains_no_path_or_command(self) -> None:
    rendered = repr(asdict(self.coordinator.public_state()))
    self.assertNotIn(str(self.root), rendered)
    self.assertNotIn(".ramses", rendered)
    self.assertNotIn(".exe", rendered)
```

- [ ] **Step 2: Run preview tests and verify RED**

Run:

```powershell
..\sg-preflight\.venv\Scripts\python.exe -B -m unittest tests.test_qt_quick_preview -v
```

Expected: FAIL because the coordinator and provider do not exist.

- [ ] **Step 3: Define a strict internal/public split**

```python
@dataclass(frozen=True, slots=True)
class PreviewPublicState:
    state: str = "fallback"
    token: str = ""
    frame_count: int = 0
    frame_index: int = 0
    label: str = "Static profile preview"


@dataclass(frozen=True, slots=True)
class _PreviewRequest:
    request_id: str
    generation: int
    profile_id: str
    scene_path: Path
    source_sha256: str
    output_root: Path
    frame_limit: int
```

Only `PreviewPublicState` crosses into controller properties. The request, path, command, process, manifest path, and cache entry remain private.

- [ ] **Step 4: Implement one-worker scheduling and hard limits**

Use `ThreadPoolExecutor(max_workers=1, thread_name_prefix="sgfx-preview")`. Build the helper argument list internally from fixed flags. On Windows pass `CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS`. Enforce before publication:

```python
if not 1 <= len(frames) <= (1 if reduced_motion else 24):
    raise PreviewRejected("frame count")
if any(width > 480 or height > 270 for width, height in dimensions):
    raise PreviewRejected("frame dimensions")
if any(not frame.resolve().is_relative_to(request.output_root.resolve()) for frame in frames):
    raise PreviewRejected("frame containment")
```

Use `subprocess.run(..., timeout=30, check=False, capture_output=True, text=True)`; sanitize every failure to the generic fallback. Never expose stdout/stderr.

- [ ] **Step 5: Implement the 256 MiB cache and opaque provider**

Cache key is SHA-256 over schema version, canonical profile, scene content hash, helper hash/version, frame limit, and reduced-motion mode. Reject links/reparse points. Evict least-recently-used completed entries until total accepted frame bytes are at most `256 * 1024 * 1024`.

`PreviewImageProvider` maps a random controller-issued token to immutable accepted frame paths and returns a `QImage`; QML never receives the path. Invalidate token mappings on profile/generation change and shutdown.

- [ ] **Step 6: Integrate lifecycle and diagnostic pre-emption**

Schedule only after an explicit profile selection and a ready current snapshot. Startup may reuse a valid cache but may not launch the helper. Before `diagnostic.run` becomes running, call `preview_coordinator.preempt()` and set playback inactive. A queued preview future may cancel; a running helper is terminated through the coordinator's owned process handle and returns to fallback.

- [ ] **Step 7: Bind bounded QML playback**

`QaContextPreview.qml` plays one revolution only when visible, active, not reduced motion, and `frameCount > 1`. Its timer advances at a derived interval and stops permanently at the last frame. Scrubbing clamps to valid indices and calls `selectPreviewFrame`; it never constructs a filesystem URL.

- [ ] **Step 8: Run preview, controller, and QML tests**

Run:

```powershell
..\sg-preflight\.venv\Scripts\python.exe -B -m unittest tests.test_qt_quick_preview tests.test_qt_quick_core tests.test_qt_quick_capabilities tests.test_qt_quick_host -v
```

Expected: PASS; preview failure is quiet and cannot affect QA state, and no private input appears in controller/QML output.

- [ ] **Step 9: Commit the bounded preview channel**

```powershell
git add sg_preflight/desktop/preview_coordinator.py sg_preflight/desktop/preview_image_provider.py sg_preflight/desktop/qt_quick_controller.py sg_preflight/desktop/qt_quick_app.py sg_preflight/desktop/qml/components/QaContextPreview.qml tests/test_qt_quick_preview.py
git commit -m "feat(qt): add bounded profile preview channel"
```

### Task 9: Extract the Ramses authored-pass preview helper

**Files:**
- Create: `cpp/include/sgfx/cine/ramses_preview.h`
- Create: `cpp/src/ramses_preview.cpp`
- Create: `cpp/apps/ramses_preview_cli.cpp`
- Modify: `cpp/CMakeLists.txt`
- Create: `cpp/tests/ramses_preview_contract_test.cpp`
- Modify: `tests/test_qt_quick_preview.py`

**Interfaces:**
- Consumes: one local `.ramses` file, one contained output directory, maximum frame count/dimensions, timeout owned by the Python caller, and the authored camera-crane interface when compatible.
- Produces: contained PNG frames plus `preview-manifest.json`; exit `0` only when the manifest is complete. It does not produce QA validation findings.

- [ ] **Step 1: Write a C++ contract test before implementation**

The header contract is exact:

```cpp
namespace sgfx::cine
{
struct RamsesPreviewRequest
{
    std::filesystem::path scene_path;
    std::filesystem::path output_root;
    std::uint32_t width{480};
    std::uint32_t height{270};
    std::uint32_t frame_count{24};
    bool reduced_motion{false};
};

struct RamsesPreviewResult
{
    bool rendered{false};
    std::string safe_reason;
    std::vector<std::filesystem::path> frames;
    std::string ramses_version;
    std::uint32_t feature_level{0};
};

RamsesPreviewResult render_ramses_preview(const RamsesPreviewRequest& request);
}
```

Test request validation without loading BMW data: missing scene, non-directory output parent, width `481`, height `271`, frame count `25`, and linked output must all fail with safe enum-like reasons and no file write.

- [ ] **Step 2: Configure and run the contract target to verify RED**

Run:

```powershell
cmake -S cpp -B build\cine-c0 -A x64 -DSGFX_CINE_RAMSES_DIR=C:\ramses-28.16.0-install
cmake --build build\cine-c0 --config RelWithDebInfo --target sgfx_cine_ramses_preview_contract_test
ctest --test-dir build\cine-c0 -C RelWithDebInfo -R sgfx_cine_ramses_preview_contract --output-on-failure
```

Expected: build or test FAIL because the helper contract is absent.

- [ ] **Step 3: Extract shared scene lifecycle from the proven viewer seam**

Move only SGFX-authored reusable behavior from `cpp/apps/ramses_real_scene.cpp`/`cpp/apps/cinematic_shell.cpp` into `ramses_preview.cpp`: framework/client creation, scene load, renderer/display/offscreen buffer, scene mapping, flush, publish, subscribe, state transitions, authored render-pass preservation, camera-crane interface lookup, bounded logic updates, readPixels, and teardown. Do not copy SDK internals or proprietary project data.

The helper must wait with explicit deadlines for `Ready`, `Available`, `Rendered`, and pixel-read completion. Any missing callback or incompatible authored interface returns a safe reason; it never waits indefinitely and never substitutes direct camera mutation.

- [ ] **Step 4: Render a finite authored turntable**

For normal motion, set only the accepted authored camera-crane rotation input for `frame / frame_count * 360`. Run the necessary logic update, flush, render one frame, read pixels, encode PNG, then continue. For reduced motion, render one authored frame without rotation travel. After the final frame, stop and destroy all Ramses objects.

- [ ] **Step 5: Emit the strict manifest from the CLI**

The CLI accepts only:

```text
--scene <file> --output-root <dir> --width <1..480> --height <1..270> --frames <1..24> [--reduced-motion]
```

Write with `nlohmann_json`:

```json
{
  "schema_version": 1,
  "state": "rendered",
  "frame_count": 24,
  "width": 480,
  "height": 270,
  "frames": ["frame-000.png"],
  "ramses_version": "<runtime version>",
  "feature_level": 1
}
```

Frame entries are relative filenames only. On failure, write no frames and print only one safe reason token to stderr.

- [ ] **Step 6: Build and run helper contract tests**

Run:

```powershell
cmake --build build\cine-c0 --config RelWithDebInfo --target sgfx_cine_ramses_preview_cli sgfx_cine_ramses_preview_contract_test
ctest --test-dir build\cine-c0 -C RelWithDebInfo -R "sgfx_cine_(ramses_link_probe|ramses_preview_contract)" --output-on-failure
```

Expected: PASS; helper enforces all limits and the existing Ramses link probe remains green.

- [ ] **Step 7: Run one compatible local-scene smoke without packaging its frames**

Use a locally resolved compatible `exported.ramses`, write only below a temporary SGFX output directory, hash the source tree before/after, then validate the manifest through `PreviewCoordinator`. Record only counts, dimensions, hashes, lifecycle states, and the temporary artifact location in the local verification log; do not commit or package the scene/frames.

- [ ] **Step 8: Commit the authored preview helper**

```powershell
git add cpp/include/sgfx/cine/ramses_preview.h cpp/src/ramses_preview.cpp cpp/apps/ramses_preview_cli.cpp cpp/tests/ramses_preview_contract_test.cpp cpp/CMakeLists.txt tests/test_qt_quick_preview.py
git commit -m "feat(ramses): add bounded authored preview helper"
```

### Task 10: Finish typography, motion, accessibility, and responsive interaction

**Files:**
- Modify: `sg_preflight/desktop/qt_quick_app.py`
- Modify: `sg_preflight/desktop/qml/SGFX/Theme.qml`
- Modify: `sg_preflight/desktop/qml/Main.qml`
- Modify: `sg_preflight/desktop/qml/components/HomePage.qml`
- Modify: `sg_preflight/desktop/qml/components/QaPipelineSpine.qml`
- Modify: `sg_preflight/desktop/qml/components/QaGateDetail.qml`
- Modify: `sg_preflight/desktop/qml/components/QaContextPreview.qml`
- Modify: `scripts/build_sgfx_exe.py`
- Modify: `tests/test_qt_quick_host.py`
- Modify: `tests/test_bundle_manifest.py`
- Modify: `tests/test_qml_format.py`

**Interfaces:**
- Consumes: repository assets `cpp/assets/fonts/Inter.ttf`, `cpp/assets/fonts/Fredoka.ttf`, and their OFL texts; the established reduced-motion flag and real lifecycle states.
- Produces: registered font-family names, bounded transition tokens, accessible traversal, and valid geometry at both contract viewports.

- [ ] **Step 1: Write failing font, motion, accessibility, and geometry tests**

Require font registration success or a safe system fallback, but never a network or protected font. Reject any QML animation tied to a fake percentage or an infinite loop. At runtime:

```python
self.assertEqual(payload["gateCount"], 7)
self.assertTrue(payload["allAccessibleNamesPresent"])
self.assertTrue(payload["primaryActionVisible"])
self.assertTrue(payload["layoutWithinViewport"])
self.assertLessEqual(payload["entranceDuration"], 700)
self.assertEqual(payload["reducedTravel"], 8)
self.assertEqual(payload["reducedStagger"], 0)
```

Run these assertions at 1280 x 720 and 1024 x 640 with the profile popover open and four detail rows present.

- [ ] **Step 2: Run visual-contract tests and verify RED**

Run:

```powershell
..\sg-preflight\.venv\Scripts\python.exe -B -m unittest tests.test_qt_quick_host.TestQtQuickShell tests.test_bundle_manifest tests.test_qml_format -v
```

Expected: FAIL until font assets, final focus behavior, and the new component geometry are packaged and tested.

- [ ] **Step 3: Register the two audited fonts before QML load**

In `qt_quick_app.py`:

```python
def _load_product_fonts() -> dict[str, str]:
    families: dict[str, str] = {}
    for key, relative in (
        ("operational", "cpp/assets/fonts/Inter.ttf"),
        ("display", "cpp/assets/fonts/Fredoka.ttf"),
    ):
        font_id = QFontDatabase.addApplicationFont(str(runtime_asset_path(relative)))
        names = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
        families[key] = names[0] if names else ""
    return families
```

Expose only family names, never asset paths. Operational labels fall back to the platform sans family; display accents fall back to operational.

- [ ] **Step 4: Apply finite, semantic motion**

Use structure -> focus/title -> content staging once per route/Presentation event. Keep the action enabled from the first stable frame. Use only real `queued`, `running`, `completed`, or backend progress values for active motion. The preview animation has `loops: 1`; all other decorative loops are forbidden.

- [ ] **Step 5: Complete keyboard and screen-reader behavior**

Tab order is profile, primary action, gates, check rows, context actions, then navigation. Left/Right changes gate; Enter/Return/Space activates. Focus is indicated by border and scale/weight. Every status is text. Esc follows overlay -> Presentation -> navigation/back -> exit-guidance priority.

- [ ] **Step 6: Package fonts plus OFL texts and scan provenance**

Add all four exact files to the PyInstaller data inputs. Extend the manifest/provenance scan to require both OFL texts and reject filenames or hashes associated with DynaFont, Sonic/game fonts, copied installer resources, URLs, and unaudited external assets.

- [ ] **Step 7: Format QML and run interaction gates**

Run:

```powershell
..\sg-preflight\.venv\Scripts\python.exe -B scripts\check_qml_format.py
..\sg-preflight\.venv\Scripts\python.exe -B -m unittest tests.test_qt_quick_host tests.test_qt_quick_grafiks tests.test_qt_quick_preview tests.test_bundle_manifest tests.test_qml_format -v
```

Expected: PASS; focus, reduced motion, semantic color/text, finite animation, viewports, fonts, and provenance are all covered.

- [ ] **Step 8: Commit interaction and typography**

```powershell
git add sg_preflight/desktop/qt_quick_app.py sg_preflight/desktop/qml scripts/build_sgfx_exe.py tests/test_qt_quick_host.py tests/test_bundle_manifest.py tests/test_qml_format.py
git commit -m "feat(qt): finish control center interaction"
```

### Task 11: Prove package, startup, cache, and source-tree invariants

**Files:**
- Modify: `sg_preflight/bundle_manifest.py`
- Modify: `scripts/build_sgfx_exe.py`
- Modify: `scripts/benchmark_qt_quick.py`
- Create: `scripts/verify_control_center_c0.ps1`
- Modify: `tests/test_bundle_manifest.py`
- Modify: `tests/test_qt_quick_benchmark.py`
- Modify: `tests/test_qt_quick_preview.py`

**Interfaces:**
- Consumes: staged PyInstaller bundle, helper executable/DLLs, QML tree, font assets/licenses, preview cache, and read-only source roots.
- Produces: machine-readable `control-center-c0-verification.json` with commit, package hashes, capability/surface counts, viewport results, startup samples, cache totals, source before/after hashes, and explicit OPEN fields.

- [ ] **Step 1: Write failing manifest and verifier tests**

Require these manifest facts without private absolute paths:

```python
self.assertEqual(manifest["ui_capability_count"], 8)
self.assertEqual(manifest["surface_descriptor_count"], 19)
self.assertEqual(manifest["qa_hub_schema_version"], 1)
self.assertTrue(manifest["control_center_qml_present"])
self.assertTrue(manifest["product_fonts_licensed"])
self.assertIn(manifest["ramses_preview_helper"], {"included", "unavailable"})
```

If the helper is unavailable, package must retain the generic fallback and state `unavailable`; it must not fail the independently green QA truth path.

- [ ] **Step 2: Run bundle and benchmark tests and verify RED**

Run:

```powershell
..\sg-preflight\.venv\Scripts\python.exe -B -m unittest tests.test_bundle_manifest tests.test_qt_quick_benchmark tests.test_qt_quick_preview -v
```

Expected: FAIL until C0 metadata and exact cache/source invariants are recorded.

- [ ] **Step 3: Extend staged-bundle validation**

Validate the Control Center QML components, font/license files, optional audited preview helper and runtime DLLs, and exact `QtQml`/`QtQuick` module envelope. Reject repository mirrors, generated evidence, preview frames, BMW scenes, source roots, credentials, and private path strings.

- [ ] **Step 4: Add the deterministic verification script**

`scripts/verify_control_center_c0.ps1` must:

1. resolve the repo and approved output root;
2. run focused Python tests;
3. run QML formatting;
4. build/validate the staged bundle without swapping the accepted default;
5. run headless 1280 x 720 and 1024 x 640 interaction probes;
6. run compatible preview smoke only when a local accepted scene/helper is available;
7. compare source-tree file size/mtime/hash evidence before and after diagnostics/preview;
8. calculate cache bytes and frame limits;
9. run warm/first-run benchmark only when the workstation reference-ready flag is supplied; otherwise record `OPEN_LOADED_WORKSTATION`; and
10. write one JSON plus one Markdown summary below `out/control-center-c0/`.

It must stop on a failed gate and must never call Jira, Clockodo, SVN, Git push, BMW export, screenshot capture, rack, or vehicle commands.

- [ ] **Step 5: Run the package verifier from the exact tree**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_control_center_c0.ps1
```

Expected: all deterministic gates PASS; preview is PASS or explicit `UNAVAILABLE`; loaded-laptop timing is PASS or explicit `OPEN_LOADED_WORKSTATION`; no source mutation and no forbidden bundled content.

- [ ] **Step 6: Run the broad Python suite and existing smoke gates**

Run:

```powershell
..\sg-preflight\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
powershell -ExecutionPolicy Bypass -File scripts\run_smoke_test.ps1
```

Expected: PASS. If the full suite exceeds its accepted execution window, preserve the log, report the exact last completed test, and run all affected modules explicitly; do not claim full discovery passed.

- [ ] **Step 7: Review the complete diff for hard-lock violations**

Run:

```powershell
git diff --check
git diff --stat a736826..HEAD
git status --short
rg -n -i "co-authored-by|generated with|written by ai|assistant|clockodo|jira.*post|svn commit|git push" sg_preflight cpp scripts tests docs CHANGELOG.md
```

Expected: clean whitespace; no attribution; Clockodo appears only in the local worklog documentation; Jira appears only as copy-ready evidence or existing explicit integrations, never a new automatic Home action.

- [ ] **Step 8: Commit package and verification gates**

```powershell
git add sg_preflight/bundle_manifest.py scripts/build_sgfx_exe.py scripts/benchmark_qt_quick.py scripts/verify_control_center_c0.ps1 tests/test_bundle_manifest.py tests/test_qt_quick_benchmark.py tests/test_qt_quick_preview.py
git commit -m "build: verify QA control center bundle"
```

### Task 12: Record Jira-ready delivery evidence and factual Clockodo time entries

**Files:**
- Create: `docs/tickets/sgfx-control-center-c0.md`
- Create: `docs/worklogs/sgfx-control-center-c0.md`
- Create: `docs/pilots/sgfx-control-center-c0-pilot.md`
- Modify: `CHANGELOG.md`
- Modify: `out/agent-control/STATE.md` in the main SGFX checkout only as the final durable pointer
- Append: `out/agent-handoffs/codex_to_claude.md` in the main SGFX checkout only

**Interfaces:**
- Consumes: accepted commits, test commands/results, verification JSON/Markdown, artifact hashes, actual local timestamps, and explicit OPEN items.
- Produces: copy-ready Jira ticket text and manual Clockodo entry rows. It performs no network call and records no guessed time.

- [ ] **Step 1: Create the Jira-ready ticket record from verified evidence**

Use this exact structure and source every populated line from the accepted implementation commits and verification artifacts:

```markdown
# SGFX QA Control Center C0

## Objective
Provide one profile-neutral QA workspace with a four-pack-only local action and seven truthful QA gates.

## Delivered
List one bullet per accepted C0 commit. Each bullet contains the short SHA from `git log --format="%h %s"`, its subject, and the concrete user-visible or safety behavior proven by that commit.

## Acceptance evidence
For every C0 verification gate, write three bullets: the exact command from `control-center-c0-verification.json`, `Result: PASS` or `Result: OPEN` plus its recorded reason, and the workspace-relative artifact path or SHA-256 from the same record.

## Safety evidence
- Eight UI capabilities preserved.
- Nineteen registered surfaces preserved.
- No automatic Jira, SVN, BMW, delivery, rack, or vehicle action introduced.
- Source roots unchanged by local preflight and preview.

## Risks and open evidence
Copy only entries whose state is `OPEN` in the accepted verification record. Omit this section when that list is empty.

## Suggested Jira comment
Write four short paragraphs derived from the sections above: delivered behavior; deterministic verification; safety invariants; then remaining OPEN evidence. Do not introduce a claim absent from those sections.
```

Do not include confidential Confluence text, secrets, absolute private paths, unsupported productivity claims, or approval language.

- [ ] **Step 2: Create the Clockodo-friendly work ledger using actual timestamps**

Use one row per implementation beat:

```markdown
# SGFX QA Control Center C0 Worklog

| Date | Start | End | Elapsed | Work package | Verified result | Commit |
|---|---:|---:|---:|---|---|---|
```

Populate the first row from the planning beat's recorded start/end timestamps and plan commit. Populate later rows only when their durable handoff or verification log contains both endpoints. Calculate elapsed from those values, round only according to the user's Clockodo practice, and keep the unrounded timestamps in the ledger. Do not infer time for frozen windows, idle periods, or earlier chats without durable timestamps.

- [ ] **Step 3: Update the changelog from shipped behavior only**

Create the opt-in teammate-pilot worksheet before updating the changelog. It records, for both the pre-C0 path and C0 path: time from usable shell to intended QA action; time from completed local preflight to first actionable finding; number of separate surfaces/manual searches; duplicate values re-entered for handoff; presence of profile/source/finding/provenance/owner/next-action fields; and elapsed time to prepare copy-ready BMW ticket/handoff material. Each observation includes participant role, profile, local timestamp, observation method, and consent/opt-in state. It defines no target and emits no improvement claim until paired observations exist.

- [ ] **Step 4: Update the changelog from shipped behavior only**

Add concise bullets for explicit selection, local QA action, seven-gate Control Center, Presentation, bounded preview/fallback, and inspection naming. Keep preview or performance claims marked unavailable/open when their gates did not pass.

- [ ] **Step 5: Verify documentation against code and logs**

Run:

```powershell
$markers = @(('T' + 'BD'), ('T' + 'ODO'), ('PLACE' + 'HOLDER'), ('REPLACE' + '_ME'), ('UNKNOWN' + '_DURATION'), ('TARGET' + '_PERCENT')) -join '|'
rg -n $markers docs\tickets\sgfx-control-center-c0.md docs\worklogs\sgfx-control-center-c0.md docs\pilots\sgfx-control-center-c0-pilot.md
git diff --check
git show --check --oneline HEAD
```

Expected: no template markers remain, every PASS has a concrete command/result, every duration has real timestamps, and every OPEN item remains explicit.

- [ ] **Step 6: Commit the delivery record**

```powershell
git add docs/tickets/sgfx-control-center-c0.md docs/worklogs/sgfx-control-center-c0.md docs/pilots/sgfx-control-center-c0-pilot.md CHANGELOG.md
git commit -m "docs: record control center delivery evidence"
```

- [ ] **Step 7: Update durable recovery files after the commit**

Append a physically-last beat to the main checkout's `out/agent-control/STATE.md` and `out/agent-handoffs/codex_to_claude.md` with:

- active worktree, branch, and exact HEAD;
- accepted C0 task/commit list;
- verified commands and artifact paths;
- explicit OPEN items;
- the exact next action: write the R0 ExecPlan from `plans/2026-07-12-sgfx-ramses-qa-observatory-design.md`; and
- a real Europe/Berlin timestamp plus the required beat sign-off.

Verify both blocks are physically last. These ignored recovery files are not part of the integration commit.

---

## C0 Graduation Gate

C0 is complete only when Tasks 1-12 are checked, every task commit exists, the deterministic verifier is green, the full affected suite is green, source/package/provenance scans are clean, and remaining timing/scene availability is explicitly PASS or OPEN. Preview unavailability may not block the QA truth path, but it must retain the generic fallback and cannot be described as implemented for that machine.

After C0 acceptance, write a separate RED-first R0 implementation plan from `plans/2026-07-12-sgfx-ramses-qa-observatory-design.md`. Do not silently add R0 to `sgfx_preflight`; standalone R0 acceptance and a separate integration gate remain mandatory.

## Self-Review Record

- **Spec coverage:** Tasks 1-7 cover profile neutrality, the exact four-pack action, capability audit, snapshot/reducer, seven-gate Home, Full QA alignment, Presentation, and inspection. Tasks 8-10 cover the bounded preview, authored Ramses helper, clean-room motion, fonts, accessibility, and responsive behavior. Tasks 11-12 cover package/source/performance gates, Jira-ready evidence, Clockodo-friendly factual time records, changelog, and durable recovery.
- **Subsystem boundary:** The independently shippable QA truth path ends after Task 7. Tasks 8-10 cannot weaken or roll back it. R0-R5 remain separate plans.
- **Type consistency:** `selected_profile_id`/`currentProfileId` use canonical string or empty string; `SAFE_PREFLIGHT_PACKS` is a tuple but `RunRequest.packs` receives a list; QML gets camel-case snapshot keys and only typed capability/action IDs; preview paths stay in private Python/C++ types.
- **Placeholder scan:** Plan instructions contain no deferred-work marker, “similar to” shortcut, fake evidence row, guessed duration, or unspecified error-handling step.
- **Safety:** No step authorizes a push, SVN/BMW/Jira/Clockodo write, default cutover, confidential asset copy, or external publication.

## Execution Mode

The user delegated the implementation approach to Lexus and asked for end-to-end completion. Use **Inline Execution** with `superpowers:executing-plans`, in task order, with RED/GREEN and commit checkpoints. Do not dispatch subagents unless the user explicitly changes that instruction.
