param(
    [string]$BmwRepoRoot = "",
    [string]$DailySnapshotOutputRoot = "",
    [string]$TicketBundleOutputRoot = "",
    [string]$DeliverySupportOutputRoot = "",
    [string[]]$Profiles = @("NA8", "G78", "G50"),
    [string]$SmokeTest = "openAllDoors_rightView",
    [switch]$SkipBatteryDefaults
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

$Profiles = @(
    $Profiles |
    ForEach-Object { $_ -split "," } |
    ForEach-Object { $_.Trim() } |
    Where-Object { $_ }
)

if (-not $DailySnapshotOutputRoot) {
    $DailySnapshotOutputRoot = Join-Path $repoRoot "out\daily-3d-car-qa-summary-live"
}
if (-not $TicketBundleOutputRoot) {
    $TicketBundleOutputRoot = Join-Path $repoRoot "out\IDCEVODEV-960073-delivery-scope-NA8-G78-G50"
}
if (-not $DeliverySupportOutputRoot) {
    $DeliverySupportOutputRoot = Join-Path $repoRoot "out\delivery-support-package-na8-g78-g50"
}
if ($BmwRepoRoot) {
    $env:SG_BMW_CAR_MODELS_ROOT = $BmwRepoRoot
}

$logRoot = Join-Path $repoRoot "out\scheduled-daily-qa-logs"
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null

$stageResults = New-Object System.Collections.Generic.List[object]

function Add-StageResult {
    param(
        [string]$Name,
        [string]$Status,
        [int]$ExitCode,
        [string]$LogPath
    )

    $stageResults.Add([pscustomobject]@{
            Name     = $Name
            Status   = $Status
            ExitCode = $ExitCode
            LogPath  = $LogPath
        })
}

function Invoke-Stage {
    param(
        [string]$Name,
        [string[]]$Command,
        [int[]]$AcceptExitCodes = @(0)
    )

    $safeName = ($Name -replace "[^A-Za-z0-9_-]", "_")
    $stdoutPath = Join-Path $logRoot "$safeName.stdout.log"
    $stderrPath = Join-Path $logRoot "$safeName.stderr.log"
    $combinedLogPath = Join-Path $logRoot "$safeName.log"
    $argumentList = if ($Command.Length -gt 1) { @($Command[1..($Command.Length - 1)]) } else { @() }

    Write-Host ""
    Write-Host "==> $Name" -ForegroundColor Cyan
    Write-Host ($Command -join " ")

    $process = Start-Process `
        -FilePath $Command[0] `
        -ArgumentList $argumentList `
        -WorkingDirectory $repoRoot `
        -NoNewWindow `
        -Wait `
        -PassThru `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath

    $combined = New-Object System.Collections.Generic.List[string]
    if (Test-Path $stdoutPath) {
        foreach ($line in Get-Content $stdoutPath) {
            $combined.Add($line)
        }
    }
    if (Test-Path $stderrPath) {
        foreach ($line in Get-Content $stderrPath) {
            $combined.Add($line)
        }
    }

    if ($combined.Count -gt 0) {
        foreach ($line in $combined) {
            Write-Host $line
        }
        Set-Content -Path $combinedLogPath -Encoding UTF8 -Value $combined
    }
    else {
        Set-Content -Path $combinedLogPath -Encoding UTF8 -Value ""
    }

    Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue

    $exitCode = $process.ExitCode
    $passed = $AcceptExitCodes -contains $exitCode
    Add-StageResult -Name $Name -Status ($(if ($passed) { "passed" } else { "failed" })) -ExitCode $exitCode -LogPath $combinedLogPath

    if (-not $passed) {
        throw "Stage '$Name' failed with exit code $exitCode. See $combinedLogPath"
    }
}

function Write-PythonStageScript {
    param(
        [string]$Name,
        [string]$Content
    )

    $scriptPath = Join-Path $logRoot "$Name.py"
    Set-Content -Path $scriptPath -Encoding UTF8 -Value $Content
    return $scriptPath
}

$profilesLiteral = ($Profiles | ForEach-Object { "'$_'" }) -join ", "

$dailyCommand = @(
    "python", "-m", "sg_preflight.cli", "daily-qa-snapshot",
    "--workspace", $repoRoot,
    "--output-root", $DailySnapshotOutputRoot,
    "--smoke-test", $SmokeTest
)
foreach ($profile in $Profiles) {
    $dailyCommand += @("--profile", $profile)
}
if (-not $SkipBatteryDefaults) {
    $dailyCommand += "--battery-defaults"
}
Invoke-Stage -Name "daily-qa-snapshot" -Command $dailyCommand

$ticketScriptPath = Write-PythonStageScript -Name "materialize_ticket_bundle" -Content @"
import sys
from pathlib import Path
sys.path.insert(0, r"$repoRoot")
from sg_preflight.ticket_review import materialize_ticket_review_bundle

result = materialize_ticket_review_bundle(
    "IDCEVODEV-960073",
    title="Quality-Hero: How to review the 3D car",
    profile_ids=($profilesLiteral,),
    scope_note="Confirmed delivery scope from Jana is NA8, G78, and G50. Earlier G70 work is only a prototype/local dry run and is not the current delivery scope.",
    workspace=Path(r"$repoRoot"),
    output_root=Path(r"$TicketBundleOutputRoot"),
)
print(result.package_root)
print(result.zip_path)
"@
Invoke-Stage -Name "ticket-review-package" -Command @("python", $ticketScriptPath)

$deliveryScriptPath = Write-PythonStageScript -Name "materialize_delivery_support_package" -Content @"
import sys
from pathlib import Path
sys.path.insert(0, r"$repoRoot")
from sg_preflight.delivery_support_package import materialize_delivery_support_package

result = materialize_delivery_support_package(
    workspace=Path(r"$repoRoot"),
    output_root=Path(r"$DeliverySupportOutputRoot"),
    grounded_profile_ids=($profilesLiteral,),
    grounded_scope_note="Confirmed delivery scope from Jana is NA8, G78, and G50. Earlier G70 work is only a prototype/local dry run and is not the current delivery scope.",
    coordinator_name="Jana",
    review_owner_group="Adrian / Hristofor / Stefan",
)
print(result.package_root)
print(result.zip_path)
"@
Invoke-Stage -Name "delivery-support-package" -Command @("python", $deliveryScriptPath)

$summaryLines = New-Object System.Collections.Generic.List[string]
$summaryLines.Add("# Scheduled Daily 3D Car QA Snapshot")
$summaryLines.Add("")
$summaryLines.Add("Generated at: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
$summaryLines.Add("Repo root: $repoRoot")
$summaryLines.Add("Profiles: $([string]::Join(', ', $Profiles))")
$summaryLines.Add("BMW repo root override: $(if ($BmwRepoRoot) { $BmwRepoRoot } else { 'auto-detect / existing env' })")
$summaryLines.Add("")
$summaryLines.Add("## Stage Results")
$summaryLines.Add("")
$summaryLines.Add("| Stage | Status | Exit | Log |")
$summaryLines.Add("| --- | --- | ---: | --- |")
foreach ($stage in $stageResults) {
    $logName = Split-Path -Leaf $stage.LogPath
    $summaryLines.Add("| $($stage.Name) | $($stage.Status) | $($stage.ExitCode) | [$logName](scheduled-daily-qa-logs/$logName) |")
}
$summaryLines.Add("")
$summaryLines.Add("## Output Roots")
$summaryLines.Add("")
$summaryLines.Add("- Daily snapshot: $DailySnapshotOutputRoot")
$summaryLines.Add("- Ticket bundle root: $TicketBundleOutputRoot")
$summaryLines.Add("- Delivery-support root: $DeliverySupportOutputRoot")
$summaryLines.Add("")
$summaryPath = Join-Path $repoRoot "out\scheduled-daily-qa-summary.md"
Set-Content -Path $summaryPath -Encoding UTF8 -Value $summaryLines

Write-Host ""
Write-Host "Scheduled daily snapshot summary written to: $summaryPath" -ForegroundColor Green
