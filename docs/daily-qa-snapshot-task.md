# Daily QA Snapshot Task

This workflow turns the local BMW+SG daily snapshot into a repeatable morning report.

## What it runs

The runner script:

- executes `daily-qa-snapshot` for the confirmed delivery scope
- runs the representative smoke path
- runs the broader screenshot battery by default
- regenerates the grounded `IDCEVODEV-960073` ticket bundle
- regenerates the coordinator-facing delivery-support package
- writes a small summary to `out/scheduled-daily-qa-summary.md`

Main script:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_daily_3d_car_qa_snapshot.ps1
```

Useful overrides:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_daily_3d_car_qa_snapshot.ps1 `
  -BmwRepoRoot C:\path\to\digital-3d-car-models `
  -Profiles NA8,G78,G50
```

`-Profiles` accepts either a comma-separated string or a PowerShell string array.

## Scheduling it

Optional registration script:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_daily_3d_car_qa_snapshot_task.ps1 `
  -DailyAt 08:00 `
  -BmwRepoRoot C:\path\to\digital-3d-car-models
```

That registers a Windows Task Scheduler job named:

- `SG Preflight Daily 3D QA Snapshot`

## Current intent

This is not a Jira/BMW-system replacement.

It is a morning-status layer for:

- local BMW export/screenshot smoke evidence
- broader screenshot battery gaps
- refreshed ticket packaging for the current delivery scope

## Known limits

- visual screenshot verdicts still need human review
- RaCo asset-review signoff still needs a human pass/fail judgment
- Jira writeback still remains external
- CodeCraft / QX / full BMW ecosystem access is still outside this script
