# 3D Car Delivery Retro - 2026-04-14

## Source

- Raw export folder: `3D Car Delivery Retro/`
- Files inspected:
  - `3D Car Delivery Retro/3D Car Delivery Retro.html`
  - `3D Car Delivery Retro/3D Car Delivery Retro-comments.json`

## Verdict

This export is useful.

It is not a technical source-of-truth for file formats, adapters, or SG data structures, but it is a strong:

- pain map
- workflow gap map
- testing-process input
- backlog prioritization input
- justification artifact for why `sg-preflight` should exist

## What Was In The Export

- `46` unique board notes extracted from the Whiteboard HTML
- `1` comment thread in the JSON export
- `250` raw `aria-label` entries in the HTML, collapsing to `72` unique labels after deduplication
- the extra labels were mostly:
  - author attribution
  - last-edited markers
  - shape/layout metadata
  - one comment hint marker

Approximate note distribution by board color:

- `21` soft red notes
- `9` yellow notes
- `5` soft blue notes
- `5` soft cyan notes
- `4` violet notes
- `1` soft orange note
- `1` green note

The comment thread also reinforced three points:

- updating
- standardization
- persistent responsibility by `1/2` people

## Deep HTML Audit Addendum

A deeper HTML pass confirmed that the board is mostly made of:

- sticky-note text
- author attribution labels
- layout/shape metadata
- one visible comment hint

The deep pass did **not** reveal hidden technical SG file references or adapter inputs.

It did, however, surface a few workflow/action details that were embedded inside the Whiteboard content and are worth preserving explicitly:

- `Sync about QA-Hero Testing Process`
  - `Adrian creates meeting`
- `Internal Rack Session should be one week earlier`
  - `PC organises the meeting`
  - `DC is responsible for approval`
  - `TO is responsible for fixes getting done`
- `AO for Lights is baked before LightFX creation`
  - `3D artist and TA working on G58 Lights and LightFX`
  - `Jana adds to ticket DoDs`
- `Create tickets and meetings for AO investigations`
  - `Jarek will take over investigation ticket`
- `Create meeting with PMs, PC, DC and TO`
  - focus: future responsibility for welcome lights, light FX, and light carpet

This deep pass also confirmed that the earlier long yellow note contained important operational sub-points:

- spread responsibility and testing capabilities
- new bug report chat with thread layout
- decide whether all findings should become tickets or only selected categories
- emulator / QA-Hero / remote-rack capability should not be limited to one person
- Romanian office will also get a rack
- define relevant functions and success/fail states per car
- share integration-testing knowledge, including rack flashing
- include enough context in findings so fixers do not need to rediscover basics
- move cubings and internal rack testing earlier in the schedule

## Strongest Themes

### 1. Testing Is Too Late And Too Thin

Repeated notes pointed to:

- missing QA from the beginning
- early testing being very helpful
- early rack/emulator reviews being a huge help
- too little time after rack test before preview delivery
- finishing too close to delivery for meaningful review
- testing knowledge spread too thin
- too few people able to do integration tests

This strongly supports `sg-preflight` as an earlier deterministic gate rather than a late-stage review helper only.

### 2. Workflow And Ownership Are Blurry

Repeated notes pointed to:

- no ownership around `LightFX`, welcome animation, and light carpet
- ticket chaos with PCs and light reviews
- rack cubing not being structured
- workflow definition missing
- unclear ownership of final approval
- too much time spent organizing tickets and next steps
- explicit coordination assignments only appearing late inside retro action notes

This supports keeping the tool focused on:

- explicit evidence
- repeatable validation packs
- context-rich findings
- documented assumptions and contracts

### 3. Avoidable Findings Are A Known Problem

Directly relevant notes included:

- avoidable findings during reviews
- early externalized rack/emulator reviews helped a lot
- give enough context for findings so fixes do not require re-investigation

This is almost a direct description of the value proposition for the current CLI/reporting work.

### 4. AO / LightFX / WheelFX Need Clarification

Repeated notes pointed to:

- AO being overused or unclear
- AO for lights needing an agreed workflow
- bumper AO / "light painting" needing investigation
- WheelFX and wheel-cap geometry causing recurring delivery pain

This is useful for roadmap shaping, but it is not yet a direct adapter source. It suggests future pack/rule opportunities once concrete data sources are available.

### 5. Perspectives / BMW Design Flow Is Friction Heavy

The retro also called out:

- perspective workflow being frustrating
- BMW review timing being poor
- need for a better system around Perspectives / BMW Design

This matters because it reinforces the need for better evidence and prep before BMW-facing reviews.

### 6. Documentation / Standardization / Ownership Need To Be Persistent

The comment thread added a useful layer that the sticky notes alone did not state as directly:

- updating of dates and references matters
- a separate coordinated document for working references is needed
- structure and nomenclature should be standardized
- responsibility should stay persistent instead of being diffuse

This supports:

- config-driven rules instead of tribal knowledge
- explicit assumptions/decisions docs
- stable handoff context in markdown/HTML outputs

## Most Relevant Notes For `sg-preflight`

These notes map especially well to the tool:

- "Avoidable Findings during reviews"
- "Missing QA from the beginning"
- "Early Rack/Emulator reviews ... huge help ... We should integrate them in our workflow"
- "We need more people that can do the integration tests"
- "Define testing process, relevant functions per car and success and probably fail-states per function"
- "Provide enough context for findings, so that already established information doesn't need to be investigated by the person fixing the issues"
- "Internal Rack Session should be one week earlier"
- "AO for Lights is baked before LightFX creation ..."

There was also one note explicitly describing the project direction:

- "Building an internal CLI-first QA preflight and evidence layer for Seriengrafik 3D Car ..."

## What This Means For The Backlog

This retro strengthens the case for these priorities:

1. Keep `project_sanity` and reporting strong because they already create actionable evidence.
2. Push `constants` next because it is the most buildable real-source slice still missing.
3. Keep findings grouped, contextual, and presentation-friendly for non-programmer stakeholders.
4. Preserve a clear path toward earlier review support, not just post-failure diagnostics.
5. Treat rack/emulator/integration readiness as a future extension area once the deterministic packs are stable.
6. Keep owner/action hints and handoff context in the reporting layer because the retro clearly showed coordination ambiguity.

## What This Does Not Give Us

This export does **not** provide:

- real SG anchor dumps
- real `Pivot_Master` JSON
- real `read_json_carpaints.py`
- authoritative file schemas
- direct adapter inputs

So it should be used as a prioritization and communication source, not as a parser/input reference.

## Recommendation

Keep this retro in the project memory as:

- a justification artifact for the tool
- a roadmap/prioritization input
- a stakeholder communication aid

Do not treat it as source-of-truth for implementation details.
