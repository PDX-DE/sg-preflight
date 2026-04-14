param(
    [string]$OutputRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "out\real-sg-smoke\latest"
}

$sgRepoRoot = Join-Path $repoRoot "repositories\trunk"
$g70ProjectRoot = Join-Path $sgRepoRoot "Cars_IDCevo\BMW\G70"
$liveConfig = Join-Path $repoRoot "config\sg_rules_live.json"

if (-not (Test-Path $sgRepoRoot)) {
    throw "Live SG mirror not found at $sgRepoRoot"
}

if (-not (Test-Path $g70ProjectRoot)) {
    throw "Live G70 project root not found at $g70ProjectRoot"
}

if (Test-Path $OutputRoot) {
    Remove-Item -LiteralPath $OutputRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null

function Invoke-Step {
    param(
        [string]$Name,
        [string[]]$Command,
        [int[]]$AcceptExitCodes = @(0)
    )

    Write-Host ""
    Write-Host "==> $Name" -ForegroundColor Cyan
    Write-Host ($Command -join " ")

    $stdoutPath = Join-Path $OutputRoot "$Name.stdout.log"
    $stderrPath = Join-Path $OutputRoot "$Name.stderr.log"
    $argumentList = if ($Command.Length -gt 1) { @($Command[1..($Command.Length - 1)]) } else { @() }

    $process = Start-Process `
        -FilePath $Command[0] `
        -ArgumentList $argumentList `
        -WorkingDirectory $repoRoot `
        -NoNewWindow `
        -Wait `
        -PassThru `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath

    if (Test-Path $stdoutPath) {
        Get-Content $stdoutPath
    }
    if (Test-Path $stderrPath) {
        Get-Content $stderrPath
    }

    if (-not ($AcceptExitCodes -contains $process.ExitCode)) {
        throw "Step '$Name' failed with exit code $($process.ExitCode)"
    }
}

$bundleRoot = Join-Path $OutputRoot "g70-bundle"
$jsonOut = Join-Path $OutputRoot "g70-report.json"
$htmlOut = Join-Path $OutputRoot "g70-report.html"
$markdownOut = Join-Path $OutputRoot "g70-report.md"

Invoke-Step -Name "materialize-g70" -Command @(
    "python", "-m", "sg_preflight", "materialize",
    "--output-bundle", $bundleRoot,
    "--repo-root", $sgRepoRoot,
    "--project-root", $g70ProjectRoot,
    "--env", "SG-Repo=$sgRepoRoot",
    "--env", "SG-CarModels-Repo=$sgRepoRoot",
    "--context", "car_model=G70",
    "--context", "trim_line=Basis",
    "--context", "delivery_phase=svn_live_preflight",
    "--context", "review_target=g70_end_to_end",
    "--context", "evidence_source=local_svn_mirror"
)

Invoke-Step -Name "run-g70" -Command @(
    "python", "-m", "sg_preflight", "run",
    "--bundle", $bundleRoot,
    "--config", $liveConfig,
    "--json-out", $jsonOut,
    "--html-out", $htmlOut,
    "--md-out", $markdownOut,
    "--fail-on", "never"
)

Write-Host ""
Write-Host "Real SG smoke bundle: $bundleRoot" -ForegroundColor Green
Write-Host "JSON report: $jsonOut" -ForegroundColor Green
Write-Host "HTML report: $htmlOut" -ForegroundColor Green
Write-Host "Markdown handoff: $markdownOut" -ForegroundColor Green
