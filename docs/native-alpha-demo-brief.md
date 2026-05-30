# SGFX: Project Quality-Hero Native Alpha Brief

This native shell is a **private alpha over the SG Preflight backend**, not a replacement engine.

## What It Is

- a local desktop operator shell over the existing Python SG checker / evidence backend
- a faster surface for SG-side review, file opening, evidence triage, and manual follow-up
- a truthful alpha that keeps blocked/manual stages visible instead of pretending the whole QA loop is automated

## What It Is Good At Right Now

- selecting a slice and running the real SG-side action flow
- showing live status, linked run output, evidence, files, reports, and copy-ready handoff text
- opening the first affected files quickly
- showing local readiness through Environment Doctor
- attaching manual evidence into the same action bundle

## What It Does Not Claim Yet

- BMW smoke is **blocked until BMW access, repo setup, and smoke scripts are real locally**
- Blender and RaCo are **readiness/opening/manual-review helpers**, not a full automated visual QA loop
- Jira / QA Hero automation is not the current truth; copy-ready notes come first

## Recommended Demo Story

1. Open the native shell.
2. Select `G70` or `G65`.
3. Choose `STACK` or `REPO`.
4. Review what will run.
5. Run it.
6. Open evidence and the first affected file.
7. Show Environment Doctor and Stages.
8. Say clearly that BMW remains blocked and Blender/RaCo remain manual-review helpers.

## Operator Message

Use the shell to get **deterministic SG-side evidence first**, then keep BMW blockers and manual visual-review steps explicit instead of losing them in chat or memory.
