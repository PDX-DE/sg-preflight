# Next Chat Handoff Prompt

> [!IMPORTANT]
> Treat this repository, the mirrored SVN content under `repositories/`, generated reports, screenshots, and workflow notes as internal Paradox Cat GmbH material.

Use the following prompt to continue work in a new chat without losing context:

```text
You are continuing an internal tooling effort for Paradox Cat GmbH, Seriengrafik / 3D Car.

Work from the existing repository state exactly as it exists on disk. Do not restart from generic assumptions. Audit the actual workspace first, understand what already works, and continue from there.

## Who I am

I am David Erik García Arenas (`@Hawaiiiiii` on personal GitHub), a full-stack developer / creative technologist working across AI, automation, real-time systems, 3D graphics, and technical tooling.

I recently finished an FCT at Paradox Cat GmbH as a Test Automation Engineer and, since `2026-04-01`, I am in a paid extended internship / new role as a **3D Pipeline QA Engineer**.

## Strategic objective

I have roughly 4 months to mature this into a useful internal tool and present it in a company talk in the second week of September 2026, around 15 days before my contract ends on `2026-09-30`.

The real goal is not a flashy toy. The goal is to leave behind an internal capability that:
- catches deterministic issues earlier
- reduces obvious findings before rack sessions
- turns repeated manual checks into reusable automation
- generates usable evidence instead of vague comments
- improves observability across the Blender -> glTF/export -> Ramses Composer -> integration flow
- makes me difficult to replace and supports conversion to a full-time contract

## Internal ownership / repo policy

Assume this repo belongs on the company side (`PDX-DE` or equivalent internal org space), not personal GitHub first.

This is internal capability tooling. Keep the repo professional, GitFlow-oriented, and publication-safe:
- proprietary/internal-use license
- internal notice and security handling
- GitHub issue forms / PR templates / CI
- no AI-ish branding or stray assistant wording in repo-facing docs

## Current repo and environment

Current workspace root:
`C:\Users\DavidErikGarciaArena\Documents\GitHub\sg-preflight`

Mirrored Seriengrafik SVN inside the repo:
`C:\Users\DavidErikGarciaArena\Documents\GitHub\sg-preflight\repositories`

There is also a live machine-level checkout area in:
`C:\repositories`

Treat `C:\repositories` as read-only reference input for analysis when needed.
Treat the in-repo `repositories\` mirror as the working mirrored source base for building and testing adapters.

## Core product thesis

This should remain **one framework**, not several unrelated scripts.

Working name:
- `sg-preflight`

Purpose:
- deterministic preflight
- evidence generation
- observability layer for Seriengrafik 3D Car QA / integration
- later possibly richer operator-facing surfaces

## Language strategy

Do not overengineer a multi-language architecture too early, but do not artificially lock the project to Python forever.

Current rule:
- Python first for CLI, adapters, validators, config, reporting, tests
- Lua selectively if rules must live inside Ramses / Logic
- Kotlin later if Android-side integration or build/test hooks become real
- C++ later if native/runtime/performance/UI needs justify it

The next chat should explicitly explore a GUI/tooling direction too, but it must still build on the existing Python framework instead of throwing it away.

## What already exists and works

The repo is already runnable and no longer demo-only.

Current implemented capabilities:
- CLI entry point: `python -m sg_preflight ...`
- packs:
  - `anchors`
  - `constants`
  - `carpaints`
  - `project_sanity`
- JSON / HTML / Markdown reports
- presentation-friendly grouped findings
- smoke automation
- GitHub hygiene files
- proprietary/internal repo posture

Current real live slices:
- `G70` live slice
- `G65` live slice
- `G45` classic BMW slice

Current real live support includes:
- live `Pivot_Master.json`
- live `Module_constants_*.lua`
- live `CarPaint.json`
- zipped `.rca` anchor scenes
- SG-style repo discovery and materialization
- project_sanity on real SG-shaped project roots

Current important files / commands:
- `config/sg_rules_live.json`
- `config/sg_rules_live_g65.json`
- `config/sg_rules_live_g45.json`
- `scripts/run_real_sg_smoke.ps1`
- `scripts/run_real_g65_smoke.ps1`
- `scripts/run_real_g45_smoke.ps1`
- `scripts/run_real_live_matrix_smoke.ps1`
- `docs/assumptions-and-decisions.md`
- `docs/next-chat-handoff-prompt-2026-04-14.md`

Useful commands:
- `python -m unittest discover -s tests -v`
- `powershell -ExecutionPolicy Bypass -File scripts\run_smoke_test.ps1`
- `powershell -ExecutionPolicy Bypass -File scripts\run_real_live_matrix_smoke.ps1`

## Current live baseline findings

The tool is now surfacing real project signal, not just demo failures.

Current meaningful live findings:
- `G70`
  - duplicate BMW carpaint ID
  - cross-car references to `G65`
  - a handful of unreferenced Lua files
- `G65`
  - real drift between `Pivot_Master` and `Module_constants`
    - rim diameter differences
    - tire width differences
  - a small set of unused-Lua warnings
- `G45`
  - anchor validation for classic scale / tire-pressure / sensor families works
  - duplicate BMW carpaint ID still appears
  - old `racoVersion` warning appears

## Important technical decisions already made

- Keep the normalized bundle contract as the validator boundary.
  Adapters can evolve without rewriting the validation core.

- Keep `anchors` as one pack.
  Do not split sensor / tire-pressure / scale anchors into separate packs.
  The validator already supports multiple config-driven rule groups.

- Keep CLI + JSON/HTML/Markdown first.
  Do not jump straight to a flashy dashboard and ignore the deterministic core.

- The repo already has a proprietary/internal-use posture.
  Do not replace it with an open-source license.

- SG-relative scene links and cross-car contamination must be distinguished from true filesystem absolute-path risks.

## Team pain points that must keep shaping the backlog

Use the onboarding notes and especially the `3D Car Delivery Retro` from `2026-04-14` as a pain map.

Important recurring pains include:
- testing happens too late
- too many obvious findings survive until rack/review
- QA/integration knowledge is fragmented
- process/ownership is unclear
- documentation and ticket structure are confusing
- correct car-specific source-of-truth is hard to find
- integration behaves like a black box
- multiple manual build/move/debug steps create friction
- handoff and evidence quality are weak

The next phase should continue to solve these pains concretely, not just technically.

## What to do next in the new chat

### 1. Re-audit the mirrored SVN deeply

Reanalyze the SVG/SVN-style source trees carefully:
- the mirrored repo copy inside:
  `C:\Users\DavidErikGarciaArena\Documents\GitHub\sg-preflight\repositories`
- the machine-level source tree in:
  `C:\repositories`

Important:
- `C:\repositories` is read-only reference input for analysis
- do not modify anything there
- use it to compare whether the in-repo mirror is complete, stale, or structurally different

You should inspect real folders and scripts deeply, not only filenames.

### 2. Identify the best path from CLI-first framework to usable GUI tooling

The next serious direction is to explore a GUI/framework/tooling surface on top of the existing engine.

Goal:
- friendly-user and baby-simple for the team
- usable by non-programmers
- useful inside QA / TA / 3D / integration contexts
- still grounded in the existing deterministic engine

Do not throw the Python framework away.
Instead, evaluate and propose the best architecture for:
- Python backend/core staying intact
- possible GUI/client layer
- possible use of C++, C, Kotlin, or other language only when justified

Possible directions may include:
- Python backend + desktop shell
- Python backend + local web UI
- native wrapper over the Python validation/reporting core
- richer evidence explorer
- workflow-oriented operator view

But do not jump blindly. First analyze the repo and real team pain.

### 3. Use the retro to drive UX and workflow, not only validation

The GUI/tooling direction should directly help with:
- making findings understandable
- giving clearer ownership/action hints
- reducing confusion around workflow/order/dependencies
- making evidence easier to inspect and hand off
- making the framework useful for people who do not want to run raw CLI commands

### 4. Stay end-to-end and keep everything working

No placeholder-only scaffolding.

Every iteration must leave behind:
- runnable code
- verified commands
- updated docs
- tests where possible
- explicit assumptions

### 5. Keep repo/professional hygiene strong

- follow GitFlow conventions
- keep docs clean and internal-facing
- keep AI-ish or assistant-ish wording out of published repo-facing docs
- use GitHub callouts where they help readability
- update changelog and relevant docs for meaningful changes

## Output style for the next chat

At the start of each substantial turn, provide:
1. brief status
2. what you inspected
3. what you changed
4. what still blocks progress
5. the next best action

Be skeptical, concrete, and execution-oriented.
Prefer code, diffs, commands, tests, and repo edits over vague brainstorming.
Only ask questions when truly blocked or when a choice has real architectural consequences.

## North star

This project should evolve from a deterministic preflight CLI into a reusable internal capability for 3D Car QA / integration / evidence generation, and eventually a genuinely friendly tool that the team would actually want to use.

The point is not to make a flashy toy.
The point is to reduce friction, reduce obvious failures, improve traceability, and leave behind something the department would miss if I left.
```
