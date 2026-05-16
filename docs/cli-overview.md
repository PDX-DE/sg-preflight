# SG Preflight CLI Overview

This page is the short operator-facing map for running SG Preflight from a terminal.

SG Preflight is an opt-in local QA support tool. CLI output is evidence and review guidance, not approval. Manual RaCo, Blender, screenshot, rack, and delivery review remain human-owned.

## Command Shape

Most read/status commands follow this shape:

```powershell
python -m sg_preflight <command> <subcommand> --profile <PROFILE> --format <text|json|markdown>
```

For commands that support file output, add either flag:

```powershell
--output-path <path>
--out <path>
```

Backward-compatible aliases still work:

```powershell
--json
--markdown
```

Do not combine `--format markdown` with `--json`, or `--format json` with `--markdown`.

## Common Examples

### Registry and readiness

```powershell
python -m sg_preflight list-profiles --format json --out out\profiles.json
python -m sg_preflight list-actions --format json
python -m sg_preflight list-checkers --format json
python -m sg_preflight workflow-status --format text
```

### Daily and morning status input

```powershell
python -m sg_preflight daily-digest latest --format markdown --out out\morning-digest.md
python -m sg_preflight daily-digest latest --format json --out out\morning-digest.json
```

On a fresh checkout with no review package, `daily-digest latest` exits 0 and prints a clear no-package summary with the setup hint for `ticket-review`.

### Operator-local command templates

```powershell
python -m sg_preflight template save morning-digest --command daily-digest --args "latest --format markdown"
python -m sg_preflight template list
python -m sg_preflight template show morning-digest
python -m sg_preflight template run morning-digest
python -m sg_preflight template delete morning-digest
```

Templates are saved as JSON under the current workspace's `templates\` folder. They are local saved command configurations, not shared workflow definitions and not approval logic.

### SG / BMW evidence readers

```powershell
python -m sg_preflight delivery-checklist read --profile G65 --format json
python -m sg_preflight export-size-analysis read --profile G65 --workspace C:\repositories\trunk --latest --format markdown
python -m sg_preflight screenshot-test-state read --profile G65 --format json
python -m sg_preflight bmw-git-readiness read --profile G65 --format markdown
python -m sg_preflight qa-hero-readiness read --profile G65 --format markdown
```

These readers are read-only. They do not run BMW tools, do not write SVN or BMW Git, and do not decide whether a car is approved.

### Jira comment posting

```powershell
python -m sg_preflight jira post --ticket IDCEVODEV-977874 --body-file out\jira-update.txt --format markdown
python -m sg_preflight jira post --ticket IDCEVODEV-977874 --section 19 --wording-file HANDOVER_WORDING.md --format json
```

The default is a dry run. It prints the ticket, endpoint preview, source, and comment body but sends no HTTP request. To post, set a base URL and PAT through environment variables and add `--confirm` to that single command:

```powershell
$env:BMW_JIRA_BASE_URL="https://jira.example"
$env:BMW_JIRA_PAT="<personal-access-token>"
python -m sg_preflight jira post --ticket IDCEVODEV-977874 --body-file out\jira-update.txt --confirm
```

Jira posting is opt-in and confirmation-gated. SGFX does not auto-post, does not transition issues, and does not mark QA approval.

### Manual review companion

```powershell
python -m sg_preflight manual-review session --profile G65 --ticket IDCEVODEV-977874 --markdown
python -m sg_preflight manual-review summary <session-id> --markdown
```

Manual-review commands create or render operator-recorded sessions. They do not auto-mark review steps as done.

### Deterministic preflight

```powershell
python -m sg_preflight run-profile G65 --fail-on never --json
python -m sg_preflight run-action qa_stack__g65 --json
```

`run` still uses its established report-file flags:

```powershell
python -m sg_preflight run --bundle demo\good --config config\sg_rules.json --json-out out\report.json --html-out out\report.html --md-out out\report.md
```

## Troubleshooting

- If a read command reports `not_available`, check the local SVN or BMW Git path first.
- If a command reports malformed JSON, fix the named config file and rerun.
- If a command writes no console output while using `--out`, check the output file path. This is expected.
- If a command shows evidence, treat it as review input. It is not a signoff.
