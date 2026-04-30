# SGFX Team Demo Plan

Date: 30 April 2026

Purpose: show a team-feedback-ready SGFX alpha for Seriengrafik 3D Car QA workflows without claiming production readiness.

## Demo Goal

Show that SGFX can help a reviewer decide faster by collecting ticket scope, smoke status, screenshot-battery coverage, unresolved families, review-owner decisions, manual review state, and copy-ready handoff text in one place.

## Three-Minute Flow

1. Open Review Board.
2. Show ticket `IDCEVODEV-960073` and scope `NA8 / G78 / G50`.
3. Show factual status:
   - representative smoke: `3/3 passed`
   - screenshot battery: `24/27 covered`
   - candidate-ready: `18 exact`, `6 proxy`
   - unresolved exact family: `lights_OnlyCones`
4. Show decisions needed:
   - review-owner decision for unresolved exact family
   - final visual verdict
   - RaCo pass/fail signoff
   - Jira writeback blocked until access/process is clear
5. Open artifacts/gallery/logs from the board.
6. Copy review-owner update or morning digest.
7. Ask for workflow feedback.

## Demo-Safe Rules

- Do not resend the already-sent package unless Jana or Adrian asks.
- Do not chase `lights_OnlyCones` unless it is confirmed as delivery-blocking.
- Do not claim automated RaCo or Blender validation.
- Do not claim Jira/BMW writeback while access is blocked.
- Keep the wording on SG QA workflow support, review evidence, screenshot triage, daily digest, and structured decisions.

## Feedback Questions

- Would this help you review a 3D Car delivery faster?
- What is unclear?
- What would you still do manually?
- Which output would you trust?
- Which output would you ignore?
- What is missing before this becomes useful in daily work?

## Exit Criteria

- A teammate can understand the ticket state in under three minutes.
- They can identify what SGFX knows, what it does not know, and what is blocked by a human or by access.
- Feedback is captured as concrete follow-up items, not as broad feature wishes.
