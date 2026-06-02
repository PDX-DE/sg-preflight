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
    $EvidenceRoot = Join-Path $repoRoot "out\cpp\c2-sdl-ramses-embed-$stamp"
}

New-Item -ItemType Directory -Force -Path $EvidenceRoot | Out-Null
$transcriptPath = Join-Path $EvidenceRoot "c2-sdl-ramses-embed-transcript.txt"
$outputPath = Join-Path $EvidenceRoot "c2-sdl-ramses-embed-output.txt"
$screenshotPath = Join-Path $EvidenceRoot "c2-sdl-ramses-embed-readback.png"

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
    Write-Host "C-2 SDL3 Ramses HWND embed"
    Write-Host "Ramses version: $RamsesVersion"
    Write-Host "Ramses install: $RamsesInstall"
    Write-Host "Frames: $Frames"
    Write-Host "Evidence root: $EvidenceRoot"

    Push-Location $cppRoot
    try {
        Invoke-Native "configure SGFX C++ C-2 embed app" {
            cmake --preset vs2022-ramses-link `
                "-DCMAKE_PREFIX_PATH=$RamsesInstall" `
                "-Dramses-shared-lib_DIR=$RamsesInstall\lib\ramses-shared-lib-$($RamsesVersion.Substring(0, $RamsesVersion.LastIndexOf('.')))\cmake" `
                "-DSGFX_CINE_RAMSES_VERSION=$RamsesVersion"
        }

        Invoke-Native "build SGFX C++ C-2 embed app" {
            cmake --build --preset vs2022-ramses-link-release
        }
    }
    finally {
        Pop-Location
    }

    $embedExe = Join-Path $cppRoot "build\vs2022-ramses-link\Release\sgfx_cine_sdl_ramses_embed.exe"
    Write-Host ""
    Write-Host "== run SGFX C++ C-2 embed app =="
    $embedOutput = & $embedExe --frames $Frames --readback --screenshot $screenshotPath 2>&1
    $embedExitCode = $LASTEXITCODE
    $embedOutput | Tee-Object -LiteralPath $outputPath
    if ($embedExitCode -ne 0) {
        throw "run SGFX C++ C-2 embed app failed with exit code $embedExitCode"
    }

    Write-Host ""
    Write-Host "C-2 SDL/Ramses embed complete."
    Write-Host "Transcript: $transcriptPath"
    Write-Host "Output: $outputPath"
    Write-Host "Readback PNG: $screenshotPath"
}
finally {
    Stop-Transcript | Out-Null
}
