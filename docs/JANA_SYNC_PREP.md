# Jana Sync Prep

Date: 30 April 2026

## Short Status

SGFX / Project Quality-Hero is ready to show as a team-feedback alpha, centered on the Review Board. It is useful for status, evidence, screenshot triage, package traceability, manual review support, and decision tracking. It is not ready to claim production integration.

## What Is Already Done

- Python backend / CLI for SG QA checks and evidence.
- Web Review Board for quick status and review.
- Native C++ local operator shell for logs, artifacts, manual review actions, and local-heavy workflows.
- Ticket package generation.
- Screenshot battery and candidate review gallery.
- Daily QA digest.
- Review-owner decision tracking.
- External findings tracking.
- Copy-ready status updates.
- Package verification.

## What Was Proven On Real Work

- Used on `IDCEVODEV-960073`.
- Confirmed scope: `NA8 / G78 / G50`.
- Representative local BMW export/smoke: `3/3 passed`.
- Screenshot battery: `24/27 covered`.
- Only unresolved exact family: `lights_OnlyCones`.
- Remaining items are review-owner, visual verdict, RaCo signoff, Jira, or BMW/access-bound.

## What Is Still Prototype

- Native UI flow needs team feedback.
- Team adoption is not validated yet.
- The exact best review workflow needs teammate input.
- RaCo/Blender manual signoff wording still needs agreement.
- Daily automatic run process should remain opt-in until the team confirms value.
- Jira/BMW integration depends on access and process clarity.

## What I Need

- Jira access.
- Feedback from 3D colleagues on whether the Review Board workflow matches real QA work.
- Confirmation on what counts as done for screenshot and RaCo/manual review.
- Formal tickets so SGFX work can be prioritized correctly.

## If Asked Why C++

The Python layer remains the QA backend because it is best for automation, data parsing, reporting, and integration with existing scripts.

The C++ shell is the native operator surface. It is useful for local-heavy workflows: responsive UI, log visibility, artifact opening, keyboard-driven interaction, screenshot/manual evidence workflows, and future RaCo/Blender/BMW tool orchestration.

## Current Ticket Snapshot

- Ticket: `IDCEVODEV-960073`
- Scope: `NA8 / G78 / G50`
- Package: already sent to Adrian
- Representative smoke: `3/3 passed`
- Screenshot battery: `24/27 covered`
- Candidate-ready: `18 exact`, `6 proxy`
- Exact unresolved runtime/content failures: `3`
- Only unresolved exact family: `lights_OnlyCones`
- `lights_LowBeam` and `lights_HighBeam` are proxy-covered, not exact-pass

## Decisions Needed

- Is `lights_OnlyCones` delivery-blocking or a follow-up?
- Who owns final screenshot visual verdict?
- Who records RaCo pass/fail signoff?
- Where should Jira writeback live once access/process is confirmed?

## Blockers

- Jira access still blocked.
- CodeCraft/BMW ecosystem access still incomplete.
- Final review-owner decision is outside the tool.
- RaCo/Blender pass/fail remains explicit manual review.

## Ticket Proposals

### 1. SGFX Quality-Hero: prepare demo-safe alpha for team feedback

- Goal: make SGFX safe to show to Jana and selected 3D teammates.
- Why it matters: avoids confusing SGFX with unrelated R&D and keeps the demo focused on QA workflow value.
- Acceptance criteria: Review Board is easy to open; docs/UI use SGFX wording; optional local assets/audio are not required; blocked integrations are labeled blocked.
- Blockers: final reviewer audience and demo timing.
- Expected output: demo-safe local build, 3-minute demo plan, and short feedback questions.

### 2. SGFX Quality-Hero: validate Review Board workflow with 3D teammates

- Goal: test whether the Review Board helps reviewers understand ticket state faster.
- Why it matters: team adoption depends on trust and reduced repeated status explaining.
- Acceptance criteria: teammates can identify scope, smoke status, screenshot counts, unresolved family, decisions needed, and artifacts without guidance.
- Blockers: availability of Jana/Adrian or trusted teammates.
- Expected output: feedback notes and prioritized fixes.

### 3. SGFX Quality-Hero: daily 3D Car QA digest prototype

- Goal: produce a copy-ready daily status summary from current SGFX state.
- Why it matters: daily reporting is still possible while Jira access is blocked.
- Acceptance criteria: digest separates passed checks, unresolved families, decisions needed, blockers, and next actions.
- Blockers: agreement on who receives the digest and which tickets/slices belong in it.
- Expected output: Teams/daily-ready digest text.

### 4. SGFX Quality-Hero: screenshot candidate ranking and review-priority scoring

- Goal: rank screenshot candidates so reviewers inspect the most useful evidence first.
- Why it matters: screenshot triage should reduce visual-review effort, not create another list to manually sort.
- Acceptance criteria: candidates are grouped as exact, proxy, unresolved, and P0-P3 priority; rationale is visible; proxy coverage is not called exact-pass.
- Blockers: reviewer feedback on which ranking signals are trusted.
- Expected output: ranked gallery and review-priority summary.

### 5. SGFX Quality-Hero: RaCo and Blender manual review support

- Goal: support manual review handoff without pretending external tools are automated.
- Why it matters: RaCo/Blender review remains a human signoff step.
- Acceptance criteria: OPEN RACO and OPEN BLENDER are explicit; status/note/evidence can be attached; no default auto-launch.
- Blockers: local tool paths and agreed manual signoff wording.
- Expected output: manual review note plus attached screenshot/manual evidence.

### 6. SGFX Quality-Hero: external findings and review-owner decision tracking

- Goal: record human decisions and external findings beside SGFX evidence.
- Why it matters: important review context currently lives in chat or memory.
- Acceptance criteria: finding source, reporter, scope, owner, status, and note can be stored; review-owner decisions can be updated and copied.
- Blockers: agreement on owner/status vocabulary.
- Expected output: structured decision/finding state and copy-ready updates.

### 7. SGFX Quality-Hero: BMW/Jira integration readiness

- Goal: prepare integration boundaries without faking blocked writeback.
- Why it matters: adapters should be ready once access and process are clear.
- Acceptance criteria: access blockers are visible; proposed fields/events are documented; no Jira writeback runs without confirmed access/process.
- Blockers: Jira access, CodeCraft/BMW ecosystem access, and writeback policy.
- Expected output: integration-readiness checklist and adapter contract proposal.

## Ask

Confirm which ticket proposal Jana wants created first, and whether the alpha should be shown to one or two trusted teammates before broader visibility.
