param(
    [string]$BuildDir = "",
    [string]$BundleDir = "",
    [string]$Configuration = "Release",
    [string]$OutputRoot = "",
    [int]$LaunchTimeoutSeconds = 45,
    [int]$LaunchObserveSeconds = 5
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

$timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "build\native-bundle-verification\auto-$timestamp"
}
if (-not $BundleDir) {
    $BundleDir = "build/native-bundle-verification/package-$timestamp"
}

if (Test-Path $OutputRoot) {
    Remove-Item -LiteralPath $OutputRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null

$log = New-Object System.Collections.Generic.List[string]
$log.Add("Native shell safe-bundle verification")
$log.Add("Created: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
$log.Add("BundleDir: $BundleDir")
$log.Add("Output: $OutputRoot")
$log.Add("")

function Write-VerificationLog {
    Set-Content -Path (Join-Path $OutputRoot "verification.log") -Encoding UTF8 -Value $log
}

function Assert-True {
    param(
        [Parameter(Mandatory = $true)]
        [bool]$Condition,
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    if (-not $Condition) {
        throw $Message
    }
}

function Test-WarningContains {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Warnings,
        [Parameter(Mandatory = $true)]
        [string]$Needle
    )

    foreach ($warning in $Warnings) {
        if ([string]$warning -like "*$Needle*") {
            return $true
        }
    }
    return $false
}

function Wait-ForMainWindow {
    param(
        [Parameter(Mandatory = $true)]
        [System.Diagnostics.Process]$TargetProcess,
        [Parameter(Mandatory = $true)]
        [int]$TimeoutSeconds
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $TargetProcess.Refresh()
        if ($TargetProcess.HasExited) {
            throw "Bundled native shell exited before a main window became available."
        }
        if ($TargetProcess.MainWindowHandle -ne 0) {
            return
        }
        Start-Sleep -Milliseconds 250
    }

    throw "Timed out waiting for the bundled native shell window."
}

try {
    $packageArgs = @(
        "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $repoRoot "scripts\package_native_shell_bundle.ps1"),
        "-BundleDir", $BundleDir,
        "-Configuration", $Configuration
    )
    if ($BuildDir) {
        $packageArgs += @("-BuildDir", $BuildDir)
    }

    $log.Add("[package] packaging safe bundle with default flags")
    & powershell @packageArgs
    if ($LASTEXITCODE -ne 0) {
        throw "package_native_shell_bundle.ps1 failed with exit code $LASTEXITCODE"
    }

    $resolvedBundleDir = Join-Path $repoRoot $BundleDir
    $bundleExePath = Join-Path $resolvedBundleDir "sg_preflight_native_shell.exe"
    $manifestPath = Join-Path $resolvedBundleDir "bundle_manifest.json"
    $bundleIniPath = Join-Path $resolvedBundleDir "imgui.ini"
    $workspaceDir = Join-Path $resolvedBundleDir "workspace"
    $resourcesDir = Join-Path $resolvedBundleDir "resources"

    Assert-True (Test-Path $bundleExePath) "Bundled native shell exe was not found at $bundleExePath"
    Assert-True (Test-Path $manifestPath) "Bundle manifest is missing at $manifestPath"

    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $warnings = @($manifest.warnings)

    Assert-True (-not [bool]$manifest.include_repo_mirror) "Safe bundle unexpectedly included the repo mirror."
    Assert-True (-not [bool]$manifest.include_evidence) "Safe bundle unexpectedly included generated evidence."
    Assert-True (-not [bool]$manifest.include_reference_resources) "Safe bundle unexpectedly included reference resources."
    Assert-True (-not [bool]$manifest.include_music) "Safe bundle unexpectedly included music."

    Assert-True (-not (Test-Path (Join-Path $workspaceDir "repositories"))) "Safe bundle still contains workspace\\repositories."
    Assert-True (-not (Test-Path (Join-Path $workspaceDir "out"))) "Safe bundle still contains workspace\\out."
    Assert-True (-not (Test-Path (Join-Path $workspaceDir "SERGFX.wav"))) "Safe bundle still contains SERGFX.wav."
    Assert-True (-not (Test-Path (Join-Path $workspaceDir "SERGFX.mp3"))) "Safe bundle still contains SERGFX.mp3."
    Assert-True (-not (Test-Path (Join-Path $workspaceDir "BAChefPeePee.wav"))) "Safe bundle still contains BAChefPeePee.wav."
    Assert-True (-not (Test-Path (Join-Path $workspaceDir "BAChefPeePee.mp3"))) "Safe bundle still contains BAChefPeePee.mp3."

    $ddsFiles = @()
    if (Test-Path $resourcesDir) {
        $ddsFiles = @(Get-ChildItem -LiteralPath $resourcesDir -Recurse -File -Filter *.dds -ErrorAction SilentlyContinue)
    }
    Assert-True ($ddsFiles.Count -eq 0) "Safe bundle still contains reference DDS resources."

    Assert-True (Test-WarningContains -Warnings $warnings -Needle "Repo mirror omitted by default.") "Bundle manifest warning for omitted repo mirror is missing."
    Assert-True (Test-WarningContains -Warnings $warnings -Needle "Generated evidence was omitted by default.") "Bundle manifest warning for omitted evidence is missing."
    Assert-True (Test-WarningContains -Warnings $warnings -Needle "Reference Unleashed-style DDS resources were omitted by default.") "Bundle manifest warning for omitted reference resources is missing."
    Assert-True (Test-WarningContains -Warnings $warnings -Needle "Optional music tracks were omitted by default") "Bundle manifest warning for omitted music is missing."

    Assert-True (Test-Path $bundleIniPath) "Bundled imgui.ini is missing."
    $bundleIniContent = Get-Content -LiteralPath $bundleIniPath -Raw
    Assert-True ($bundleIniContent -match "(?m)^music_enabled=0\r?$") "Bundled imgui.ini did not disable music by default."

    $log.Add("[assert] manifest exists and safe-default flags are false")
    $log.Add("[assert] repo mirror, evidence, music, and reference resources are absent")
    $log.Add("[assert] manifest warnings and bundle imgui.ini are correct")

    $tracePath = Join-Path $OutputRoot "bundle-backend-trace.log"
    $previousTraceEnv = $env:SG_PREFLIGHT_NATIVE_TRACE_FILE
    $env:SG_PREFLIGHT_NATIVE_TRACE_FILE = $tracePath

    $process = $null
    try {
        $process = Start-Process -FilePath $bundleExePath -ArgumentList @("--windowed", "--width", "1280", "--height", "720") -WorkingDirectory $resolvedBundleDir -PassThru
        Wait-ForMainWindow -TargetProcess $process -TimeoutSeconds $LaunchTimeoutSeconds
        $log.Add("[launch] bundled native shell window detected")
        Start-Sleep -Seconds $LaunchObserveSeconds
    }
    finally {
        if ($null -ne $process -and -not $process.HasExited) {
            Stop-Process -Id $process.Id -Force
            $log.Add("[launch] bundled native shell process stopped after smoke launch")
        }
        $env:SG_PREFLIGHT_NATIVE_TRACE_FILE = $previousTraceEnv
    }

    if (Test-Path $tracePath) {
        $tracePreview = Get-Content -LiteralPath $tracePath | Select-Object -First 12
        $log.Add("")
        $log.Add("[trace]")
        foreach ($line in $tracePreview) {
            $log.Add($line)
        }
    }

    Write-VerificationLog
    Write-Host "Native shell safe-bundle verification output:" $OutputRoot
} catch {
    $log.Add("")
    $log.Add("[error] $($_.Exception.Message)")
    Write-VerificationLog
    throw
}
