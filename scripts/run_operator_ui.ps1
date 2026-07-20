param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8765,
    [switch]$OpenBrowser,
    [switch]$CheckOnly,
    [ValidateRange(1, 300)]
    [int]$BrowserReadyTimeoutSeconds = 30
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

function Wait-OperatorUiReady {
    param(
        [string]$Url,
        [System.Diagnostics.Process]$ServerProcess,
        [int]$TimeoutSeconds
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if ($ServerProcess.HasExited) {
            throw "Operator UI exited with code $($ServerProcess.ExitCode) before $Url responded. Browser was not opened."
        }
        try {
            $response = Invoke-WebRequest -Uri $Url -Method Get -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return
            }
        }
        catch {
            # Connection failures are expected while the local server binds and builds its first response.
        }
        Start-Sleep -Milliseconds 200
    }
    throw "Operator UI did not respond at $Url within $TimeoutSeconds seconds. Browser was not opened."
}

Write-Host "Repository root: $repoRoot"
Write-Host "Operator UI target: http://$BindHost`:$Port"

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

Write-Host ""
Write-Host "Starting operator UI. Press Ctrl+C to stop." -ForegroundColor Green
$url = "http://$BindHost`:$Port"
$serverArguments = @(
    "-m", "sg_preflight", "dashboard", "run",
    "--workspace", $repoRoot,
    "--ui-mode", "clean",
    "--host", $BindHost,
    "--port", [string]$Port,
    "--no-native",
    "--reload"
)

if (-not $OpenBrowser) {
    & python @serverArguments
    exit $LASTEXITCODE
}

$processArguments = @(
    "-m", "sg_preflight", "dashboard", "run",
    "--workspace", ('"{0}"' -f $repoRoot),
    "--ui-mode", "clean",
    "--host", $BindHost,
    "--port", [string]$Port,
    "--no-native",
    "--reload"
)
$serverProcess = Start-Process -FilePath "python" -ArgumentList $processArguments -WorkingDirectory $repoRoot -NoNewWindow -PassThru
try {
    Wait-OperatorUiReady -Url $url -ServerProcess $serverProcess -TimeoutSeconds $BrowserReadyTimeoutSeconds
    Start-Process $url | Out-Null
    $serverProcess.WaitForExit()
    exit $serverProcess.ExitCode
}
catch {
    if (-not $serverProcess.HasExited) {
        Stop-Process -Id $serverProcess.Id
    }
    throw
}
