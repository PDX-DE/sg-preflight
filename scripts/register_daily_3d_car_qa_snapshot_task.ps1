param(
    [string]$TaskName = "SG Preflight Daily 3D QA Snapshot",
    [string]$DailyAt = "08:00",
    [string]$BmwRepoRoot = "",
    [string[]]$Profiles = @("NA8", "G78", "G50"),
    [switch]$SkipBatteryDefaults
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runnerPath = Join-Path $PSScriptRoot "run_daily_3d_car_qa_snapshot.ps1"

if (-not (Test-Path $runnerPath)) {
    throw "Runner script not found: $runnerPath"
}

$extraArgs = @()
if ($Profiles.Count -gt 0) {
    $extraArgs += @("-Profiles", ($Profiles -join ","))
}
if ($BmwRepoRoot) {
    $extraArgs += @("-BmwRepoRoot", $BmwRepoRoot)
}
if ($SkipBatteryDefaults) {
    $extraArgs += "-SkipBatteryDefaults"
}

$runnerArguments = @(
    "-ExecutionPolicy", "Bypass",
    "-File", ('"{0}"' -f $runnerPath)
) + $extraArgs

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ($runnerArguments -join " ")
$trigger = New-ScheduledTaskTrigger -Daily -At ([datetime]::ParseExact($DailyAt, "HH:mm", $null))
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Runs sg-preflight daily BMW+SG QA snapshot and regenerates the delivery support bundles." `
    -Force | Out-Null

Write-Host "Registered scheduled task: $TaskName" -ForegroundColor Green
Write-Host "Schedule: daily at $DailyAt"
Write-Host "Runner: $runnerPath"
