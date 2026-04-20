# BMW Access Integration Checklist

Use this when BMW-side access finally lands so the first day is spent wiring the tool, not rediscovering prerequisites.

## Scope

This checklist is for the blocked BMW-side portion of SGFX Project Quality-Hero / SG Preflight:

- BMW repo detection
- BMW smoke-script discovery
- target mapping
- first dry run
- first evidence bundle

It is not a promise that BMW smoke is already integrated. It is the intake path to make that integration honest and repeatable.

## Identity And Access

- [ ] QX number received and recorded
- [ ] BMW email active and usable
- [ ] BMW Git access confirmed
- [ ] Jira access confirmed
- [ ] QA Hero access confirmed

Notes:

- Record the exact onboarding date.
- Record who approved access.
- Record any environment or VPN requirement that affects local execution.

## Local Repo Setup

- [ ] `digital-3d-car-models` clone path is known
- [ ] `SG_CARMODELS_REPO` points to that clone
- [ ] the clone opens locally without auth failures
- [ ] the repo is on the expected branch or baseline

Suggested record:

```text
BMW repo path:

SG_CARMODELS_REPO:

Branch / baseline:
```

## Smoke Script Discovery

- [ ] `ci/scripts/test/main.py` found
- [ ] `ci/scripts/car_manager.py` found
- [ ] any helper wrapper or entry script for screenshot smoke found
- [ ] required config or data files identified
- [ ] required Python or toolchain version noted

Suggested record:

```text
Smoke entrypoint:

Car manager path:

Extra helper scripts:

Required runtime / python:
```

## Target Mapping

- [ ] first working BMW target identified for `G70`
- [ ] first working BMW target identified for `G65`
- [ ] target mapping pattern understood for the rest of the supported SG profiles
- [ ] mapping documented somewhere stable before implementation

Suggested mapping table:

```text
G70 -> 
G65 -> 
G45 -> 
G50 -> 
G78 -> 
NA0 -> 
NA5 -> 
NA6 -> 
NA7 -> 
NA8 -> 
F70 -> 
F74 -> 
F78 -> 
G48 -> 
G68 -> 
U06 -> 
U10 -> 
U11 -> 
U12 -> 
```

## First Dry Run

- [ ] environment variables exported
- [ ] smoke command runs locally without immediate setup failure
- [ ] one known car target selected
- [ ] raw logs captured
- [ ] output folder confirmed
- [ ] current blocker, if any, recorded exactly

Suggested record:

```text
Command used:

Working directory:

Selected target:

Exit code:

Observed blocker:
```

## First Evidence Bundle

- [ ] first screenshot smoke artifacts located
- [ ] first raw log captured
- [ ] first output folder revealed in Explorer
- [ ] first evidence copied into SG-side handoff bundle
- [ ] first summary note written for Jira / QA Hero / handoff

Evidence to retain:

- raw command
- raw log
- screenshot output path
- exact target used
- exact repo path used
- exact failure or success summary

## SGFX Project Quality-Hero Integration Notes

When the checklist starts passing, wire the native shell in this order:

1. BMW repo detection
2. BMW smoke-script detection
3. target mapping per profile
4. dry-run command preview
5. blocked vs runnable stage state
6. first screenshot-smoke bridge

Keep the native shell honest:

- `missing`: access or files are not present
- `partial`: repo exists but target mapping or scripts are incomplete
- `blocked`: access is still pending or policy prevents execution
- `ready`: the local machine can execute the BMW-side smoke path for at least one known target

## Current Reality

As of `2026-04-20`, this remains blocked until BMW access is available on this machine.
