# SGFX Roadmap Next

Date: 30 April 2026

## P0 - Team-Feedback Alpha

Goal: make SGFX demo-safe and useful for teammate feedback.

Acceptance criteria:

- Review Board is the primary demo entry.
- Team-facing docs and UI use SGFX / Quality-Hero wording.
- No unrelated R&D/prototype assets are required for the demo.
- Current ticket status shows scope, smoke, screenshot battery, unresolved family, decisions needed, and artifacts.
- Copy-ready update and morning digest are available.
- Jira/BMW blocked state is explicit.

## P1 - Operator Observability

Goal: make local execution understandable while a run or action is in progress.

Acceptance criteria:

- Current phase is visible.
- Current command/action is visible.
- Log tail is visible.
- Produced artifacts are visible.
- Initializing states are shown instead of transient missing-state errors.
- Backend failures point to the action log or command that failed.

## P1 - Manual Review Support

Goal: support manual RaCo/Blender review without pretending it is automated.

Acceptance criteria:

- OPEN RACO is explicit.
- OPEN BLENDER is explicit.
- Manual review status can be recorded.
- Screenshot/manual evidence can be attached.
- Copy-ready manual review note is available.
- Default runs do not auto-launch RaCo or Blender.

## P1 - Feedback Capture

Goal: convert teammate feedback into usable workflow decisions.

Acceptance criteria:

- Feedback template exists in [TEAM_FEEDBACK_CAPTURE.md](TEAM_FEEDBACK_CAPTURE.md).
- Questions focus on speed, trust, unclear output, manual work left, and daily-use gaps.
- Feedback is attached to the relevant SGFX follow-up ticket.

## P2 - Future Workflow Hardening

Goal: prepare for broader daily use after team feedback.

Acceptance criteria:

- Daily digest is reviewed with real team input.
- External findings can be captured from web/native surfaces.
- Review-owner decisions can be edited from web/native surfaces.
- Package verification remains reproducible.
- Jira/BMW adapters are prepared only after access and process are clear.
