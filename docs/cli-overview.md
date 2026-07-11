# SG Preflight CLI Overview

This page is the short operator-facing map for running SGFX QA Preflight from a terminal.

SGFX QA Preflight is an opt-in local QA support tool. CLI output is evidence and review guidance, not approval. Manual RaCo, Blender, screenshot, rack, and delivery review remain human-owned.

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

### Operator dashboard modes

```powershell
python -m sg_preflight dashboard run --workspace C:\repositories\trunk --ui-mode clean
python -m sg_preflight dashboard run --workspace C:\repositories\trunk --ui-mode grafiks
```

Clean mode launches the NiceGUI dashboard. Grafiks mode launches the experimental C++ cinematic shell when it is installed. Both modes read the same SGFX backend state and keep manual review human-owned.

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
python -m sg_preflight delivery-documentation read --profile <profile> --format json
python -m sg_preflight export-size-analysis read --profile <profile> --workspace C:\repositories\trunk --latest --format markdown
python -m sg_preflight screenshot-test-state read --profile <profile> --format json
python -m sg_preflight bmw-git-readiness read --profile <profile> --format markdown
python -m sg_preflight qa-hero-readiness read --profile <profile> --format markdown
```

These readers are read-only. They do not run BMW tools, do not write SVN or BMW Git, and do not decide whether a car is approved.

### Advanced Jira integration

```powershell
python -m sg_preflight integration jira weekly-tickets --workspace C:\repositories\trunk --format markdown
python -m sg_preflight integration jira post-comment --ticket IDCEVODEV-977874 --body-file out\jira-update.txt --format markdown
```

Both default invocations are pure previews. They do not load credentials or make a Jira request. Add `--confirm-network` to the weekly draft to include assigned tickets through a read-only GET. A comment write requires both the network gate and the named write confirmation:

```powershell
python -m sg_preflight integration jira post-comment --ticket IDCEVODEV-977874 --body-file out\jira-update.txt --confirm-network --auto-confirm --format json
```

Jira access is opt-in and confirmation-gated. Register credentials with `integration jira register --confirm-local-write`; do not paste a PAT into a command. SGFX does not auto-post, transition issues, or mark QA approval.

### Manual review companion

```powershell
python -m sg_preflight manual-review session --profile <profile> --ticket IDCEVODEV-977874 --markdown
python -m sg_preflight manual-review summary <session-id> --markdown
```

Manual-review commands create or render operator-recorded sessions. They do not auto-mark review steps as done.

### Deterministic preflight

```powershell
python -m sg_preflight run-profile <profile> --fail-on never --json
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
