# JSON Workflow Guide

This page explains the current JSON-driven parts of SG Preflight and how to adjust them safely.

SG Preflight uses JSON as configuration and evidence metadata. Python remains the source of truth for validation logic. JSON files choose rules, paths, labels, tolerances, and operator-facing hints; they do not add new approval logic by themselves.

## Current JSON Inputs

| File | Purpose | Team-facing note |
| --- | --- | --- |
| `config/sg_rules.json` | Portable default rules for anchors, constants, carpaints, project sanity, and reporting hints | Uses environment-variable style setup and is safest for a clean checkout |
| `config/sg_rules_live.json` | Live SG/BMW profile rules for the broader local operator setup | May reference operator-local SVN paths |
| `config/sg_rules_live_g45.json` | Classic BMW family profile rules | Operator-local paths must match the machine running the check |
| `config/sg_rules_live_g65.json` | G65-focused constants and anchor rules | Intended for the current G65 local alpha slice |
| `<workspace>/templates/*.json` | Operator-local saved command templates created by `template save` | Local convenience only; not shared between operators and not approval logic |

Generated JSON under `out/` is evidence output. It is not committed and is not a config source.

## What Can Be Changed in JSON

These are safe, intended edits when the profile or checklist changes:

- anchor naming prefixes, allowed parts, expected parts, and position tokens
- constants `numeric_paths`, tolerances, and `exact_paths`
- carpaint required keys, allowed finish values, unique keys, numeric ranges, and array lengths
- project-sanity required context fields, required environment variables, and approved absolute prefixes
- reporting labels, owner hints, action hints, and code-specific guidance

Do not use JSON edits to claim a review verdict. If a new workflow needs new parsing or validation behavior, add Python code and tests first, then expose the knobs in JSON.

## Example: Add a Constants Check

Add a new numeric path under `constants.numeric_paths`:

```json
{
  "path": "reflection.hood_length_m",
  "tolerance": 0.001
}
```

The next run compares that expected value against the exported constants payload when both sides exist. Missing data is reported as evidence for the operator to review.

## Example: Add an Anchor Part

Add the part to `anchors.allowed_parts` and, if the profile requires it, to `anchors.expected_parts`:

```json
{
  "allowed_parts": ["Hood", "Roof", "Trunk", "ChargeFlap"],
  "expected_parts": ["Hood", "Roof", "Trunk", "ChargeFlap"]
}
```

This changes the deterministic anchor sanity rules only. The manual RaCo Abstract Scene View review remains required.

## Example: Add Reporting Guidance

Add or adjust a `reporting.code_hints` entry:

```json
{
  "anchors.invalid_name": {
    "action": "Rename the anchor to match the SG naming convention before export."
  }
}
```

This affects operator guidance text in generated reports. It does not change severity or approval state.

## Error Handling

Malformed JSON is reported with the file path, line, and column, for example:

```text
Malformed JSON in config\sg_rules_live_g65.json: line 12, column 4: Expecting value
```

Daily digest workflow-status also degrades to an explicit `not_available` entry if workflow status cannot be calculated. That keeps the morning summary usable while still showing the blocker.

## Operator-Local Command Templates

Templates store a command name and argument list so an operator can rerun a known local command without retyping it:

```powershell
python -m sg_preflight template save morning-digest --command daily-digest --args "latest --format markdown"
python -m sg_preflight template run morning-digest
```

The template JSON lives under `<workspace>\templates\`. It is a local convenience layer over existing Python CLI commands. It does not introduce new QA logic, does not share templates with other operators, and does not post to Jira or any team channel.

## Review Checklist for JSON Changes

- Run `python -m sg_preflight list-profiles --format json`.
- Run the affected profile, for example `python -m sg_preflight run-profile G65 --fail-on never --json`.
- Run the daily digest: `python -m sg_preflight daily-digest latest --format markdown`.
- Confirm generated output says evidence/guidance, not approval.
- Keep operator-local paths documented; do not copy BMW Git or SVN source content into this repository.
