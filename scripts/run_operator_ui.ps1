param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8765,
    [switch]$OpenBrowser,
    [switch]$CheckOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

function Invoke-Check {
    param(
        [string]$Name,
        [string[]]$Command
    )

    Write-Host ""
    Write-Host "==> $Name" -ForegroundColor Cyan
    Write-Host ($Command -join " ")

    & $Command[0] $Command[1..($Command.Length - 1)]
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "Check '$Name' failed with exit code $exitCode."
    }
}

Write-Host "Repository root: $repoRoot"
Write-Host "Operator UI target: http://$BindHost`:$Port/ui"

Invoke-Check -Name "list-profiles" -Command @("python", "-m", "sg_preflight", "list-profiles", "--json")
Invoke-Check -Name "ui-import" -Command @(
    "python",
    "-c",
    "from sg_preflight.ui import create_app; app = create_app(); print(app.title)"
)

if ($CheckOnly) {
    Write-Host ""
    Write-Host "Operator UI checks passed." -ForegroundColor Green
    exit 0
}

if ($OpenBrowser) {
    Start-Process "http://$BindHost`:$Port/ui" | Out-Null
}

Write-Host ""
Write-Host "Starting operator UI. Press Ctrl+C to stop." -ForegroundColor Green
& python -m sg_preflight ui --host $BindHost --port $Port --reload
exit $LASTEXITCODE
