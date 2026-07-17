# External R&D Boundary

Date: 30 April 2026

## Rule

SGFX / Project Quality-Hero is the team-facing internal QA/preflight framework for Seriengrafik 3D Car workflows.

Personal R&D reference projects are separate, personal UI/UX exploration work. They are observed dev-side only and are not the team-facing product. Nothing from them — assets, names, or code — enters this repository. Only behavioral notes (what a pattern does and why it is useful) may cross the boundary.

## What May Transfer

- Native UI architecture ideas
- Runtime state patterns
- Controller and overlay patterns
- Timing/transition lessons
- Keyboard guide patterns
- Rendering and responsiveness lessons

## What Must Not Transfer

- Third-party branding
- Copied proprietary assets
- Local evidence dumps
- Unexplained external dependencies
- Personal R&D naming in team-facing demo screens
- Any dependency that is not needed for SG QA workflow support

## Team-Facing Language

Use:

- native UI R&D
- local operator shell
- SG QA workflow support
- review evidence
- screenshot triage
- daily digest
- RaCo/Blender manual review support
- structured decision tracking

Avoid naming the personal R&D source or project when preparing Jana/team messages. If a pattern came from R&D, describe the SGFX behavior and its QA value instead.

## Acceptance Criteria

- SGFX docs can be read by a teammate without extra R&D explanation.
- SGFX builds and demos do not require personal R&D assets.
- SGFX decisions are justified by QA workflow value, not by visual inspiration.
