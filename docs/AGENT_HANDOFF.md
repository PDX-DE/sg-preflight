# Agent Handoff

Date: 30 April 2026

## Current Goal

Prepare SGFX / Project Quality-Hero as a team-feedback-ready alpha for Seriengrafik 3D Car QA workflows.

## Working Directory

Use:

```text
C:\Users\DavidErikGarciaArena\Downloads\sg-preflight
```

The GitHub sync folder is separate:

```text
C:\Users\DavidErikGarciaArena\Documents\GitHub\sg-preflight
```

Do not work from the sync folder for this alpha pass.

## Architecture Rules

- Python backend/CLI owns QA logic and structured state.
- Web UI is the lightweight review/status surface.
- C++ native shell is the heavy local operator console.
- C++ consumes Python-generated JSON/state and must not duplicate QA logic.
- Markdown/HTML are outputs, not source-of-truth.
- Jira/BMW integrations must not be faked while access is blocked.

## Current Ticket Facts

- Ticket: `IDCEVODEV-960073`
- Scope: `NA8 / G78 / G50`
- Package was already sent to Adrian.
- Representative smoke: `3/3 passed`
- Screenshot battery: `24/27 covered`
- Candidate-ready: `18 exact`, `6 proxy`
- Exact unresolved runtime/content failures: `3`
- Only unresolved exact family: `lights_OnlyCones`

Do not resend the package unless Adrian or Jana asks. Do not chase `lights_OnlyCones` unless it is confirmed as delivery-blocking.

## Open Blockers

- Jira access still blocked.
- CodeCraft/BMW ecosystem access still incomplete.
- Review-owner decision pending.
- Final visual verdict pending.
- RaCo pass/fail signoff pending.

## Validation Expectations

- Run relevant Python tests.
- If native code changed, build the native shell.
- If native bundle logic changed, run the native bundle verifier.
- Report exact executable path and verifier output.
- Keep generated packages, BMW repo content, `out/`, local media, personal R&D files, and unrelated local assets out of git.
