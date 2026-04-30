# SGFX Alpha Remaining Work

Date: 30 April 2026

Purpose: keep the SGFX / Project Quality-Hero alpha focused on workflow validation, not extra UI polish.

## Done In Repo

- Demo-safe defaults are in place for team-facing docs, web entry, native startup, and safe native bundling.
- Review Board is easy to reach from the Web UI.
- Review Board can show ticket/scope, smoke status, screenshot-battery counts, unresolved exact family, decisions needed, artifacts, copy-ready update, daily digest, external findings, and review-owner decisions.
- Three-minute demo plan exists.
- Jana sync prep and ticket proposals exist.
- Teammate feedback capture template exists.
- Teams/daily status wording exists.
- Native bundle verifier checks that default packages omit repo mirror, generated evidence, optional audio, and optional reference UI resources.

## Tool-Side Next

- Review Board workflow validation: use the existing demo plan and feedback template with selected 3D teammates.
- After feedback, convert concrete issues into follow-up ticket acceptance criteria.
- Keep improving daily digest, screenshot ranking, manual review support, external findings, review-owner decisions, and package verification only when they reduce repeated QA work or improve trust.
- Keep Jira/BMW adapter work limited to readiness and contracts until access and process are clear.

## Human Or Access Blocked

- Jira access.
- CodeCraft/BMW ecosystem access.
- Review-owner decision on unresolved exact family.
- Final screenshot visual verdict.
- RaCo pass/fail signoff.
- Teammate feedback on workflow fit.
- Jana confirmation on which SGFX tickets should be created first.

## Do Not Start Yet

- Do not resend the existing ticket package unless Jana or Adrian asks.
- Do not chase unresolved exact lighting work unless it is confirmed as delivery-blocking.
- Do not add Jira writeback before access and process are confirmed.
- Do not register scheduled tasks automatically.
- Do not auto-launch RaCo or Blender during default runs.
- Do not embed external applications.
- Do not add visual-review automation claims.
- Do not spend more time on native UI fidelity before validating the Review Board workflow.

## Next Decision

Show the Review Board workflow to one trusted teammate and record feedback in [TEAM_FEEDBACK_CAPTURE.md](TEAM_FEEDBACK_CAPTURE.md). If that feedback is useful, bring the summary to Jana's sync and ask which ticket should be created first.
