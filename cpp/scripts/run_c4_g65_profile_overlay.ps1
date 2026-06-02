param(
    [string]$RamsesVersion = "28.2.0",
    [string]$RamsesInstall = "C:\tmp\ramses-28.2.0-install",
    [int]$Frames = 180,
    [string]$EvidenceRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$cppRoot = Resolve-Path -LiteralPath (Join-Path $scriptRoot "..")
$repoRoot = Resolve-Path -LiteralPath (Join-Path $cppRoot "..")

if ([string]::IsNullOrWhiteSpace($EvidenceRoot)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $EvidenceRoot = Join-Path $repoRoot "out\cpp\c4-g65-profile-overlay-$stamp"
}

New-Item -ItemType Directory -Force -Path $EvidenceRoot | Out-Null
$transcriptPath = Join-Path $EvidenceRoot "c4-g65-profile-overlay-transcript.txt"
$outputPath = Join-Path $EvidenceRoot "c4-g65-profile-overlay-output.txt"
$profilePath = Join-Path $EvidenceRoot "c4-g65-profile.json"
$screenshotPath = Join-Path $EvidenceRoot "c4-g65-profile-overlay-readback.png"

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][scriptblock]$Body
    )

    Write-Host ""
    Write-Host "== $Label =="
    & $Body
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

Start-Transcript -LiteralPath $transcriptPath | Out-Null
try {
    Write-Host "C-4 G65 sg_preflight profile overlay"
    Write-Host "Ramses version: $RamsesVersion"
    Write-Host "Ramses install: $RamsesInstall"
    Write-Host "Frames: $Frames"
    Write-Host "Evidence root: $EvidenceRoot"

    Push-Location $repoRoot
    try {
        $env:PYTHONDONTWRITEBYTECODE = "1"
        $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
        $pythonExe = ""
        $pythonPrefixArgs = @()
        if (Test-Path -LiteralPath $venvPython) {
            $pythonExe = $venvPython
        }
        else {
            $pythonCommand = Get-Command py -ErrorAction SilentlyContinue
            if ($null -eq $pythonCommand) {
                throw "No usable Python interpreter found. Expected .venv\Scripts\python.exe or py.exe."
            }
            $pythonExe = $pythonCommand.Source
            $pythonPrefixArgs = @("-3")
        }

        Write-Host "C-4 sg_preflight python: $pythonExe $($pythonPrefixArgs -join ' ')"
        $profileJson = & $pythonExe @pythonPrefixArgs -B -c "import json; from pathlib import Path; from sg_preflight.profiles import get_run_profile; p = get_run_profile('G65', Path.cwd()); print(json.dumps({'profile_id': p.profile_id, 'label': p.label, 'project_relative': str(p.project_relative), 'config_path': str(p.config_path), 'source_project_root': str(p.source_project_root()), 'evidence_source': p.source_evidence_source()}, sort_keys=True))"
        if ($LASTEXITCODE -ne 0) {
            throw "read sg_preflight G65 profile failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }

    $profile = $profileJson | ConvertFrom-Json
    $profileId = [string]$profile.profile_id
    $profileJson | Set-Content -LiteralPath $profilePath -Encoding UTF8
    Write-Host "C-4 sg_preflight profile id: $profileId"
    Write-Host "C-4 sg_preflight profile label: $($profile.label)"
    Write-Host "C-4 sg_preflight profile relative path: $($profile.project_relative)"
    Write-Host "C-4 sg_preflight evidence source: $($profile.evidence_source)"
    Write-Host "C-4 sg_preflight profile evidence JSON: $profilePath"

    Push-Location $cppRoot
    try {
        Invoke-Native "configure SGFX C++ C-4 profile overlay app" {
            cmake --preset vs2022-ramses-link `
                "-DCMAKE_PREFIX_PATH=$RamsesInstall" `
                "-Dramses-shared-lib_DIR=$RamsesInstall\lib\ramses-shared-lib-$($RamsesVersion.Substring(0, $RamsesVersion.LastIndexOf('.')))\cmake" `
                "-DSGFX_CINE_RAMSES_VERSION=$RamsesVersion"
        }

        Invoke-Native "build SGFX C++ C-4 profile overlay app" {
            cmake --build --preset vs2022-ramses-link-release
        }
    }
    finally {
        Pop-Location
    }

    $embedExe = Join-Path $cppRoot "build\vs2022-ramses-link\Release\sgfx_cine_sdl_ramses_embed.exe"
    Write-Host ""
    Write-Host "== run SGFX C++ C-4 profile overlay app =="
    $embedOutput = & $embedExe --frames $Frames --readback --screenshot $screenshotPath --profile-id $profileId 2>&1
    $embedExitCode = $LASTEXITCODE
    $embedOutput | Tee-Object -LiteralPath $outputPath
    if ($embedExitCode -ne 0) {
        throw "run SGFX C++ C-4 profile overlay app failed with exit code $embedExitCode"
    }

    Write-Host ""
    Write-Host "C-4 G65 profile overlay complete."
    Write-Host "Transcript: $transcriptPath"
    Write-Host "Output: $outputPath"
    Write-Host "Profile JSON: $profilePath"
    Write-Host "Readback PNG: $screenshotPath"
}
finally {
    Stop-Transcript | Out-Null
}
