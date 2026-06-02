param(
    [string]$RamsesVersion = "28.16.0",
    [string]$RamsesInstall = "C:\ramses-28.16.0-install",
    [string]$SceneFile = "C:\3D Car git\digital-3d-car-models\cars\BMW\G65_EVO\export\exported.ramses",
    [int]$Frames = 240,
    [string]$EvidenceRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$cppRoot = Resolve-Path -LiteralPath (Join-Path $scriptRoot "..")
$repoRoot = Resolve-Path -LiteralPath (Join-Path $cppRoot "..")

if ([string]::IsNullOrWhiteSpace($EvidenceRoot)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $EvidenceRoot = Join-Path $repoRoot "out\cpp\c3-g65-real-scene-$stamp"
}

New-Item -ItemType Directory -Force -Path $EvidenceRoot | Out-Null
$transcriptPath = Join-Path $EvidenceRoot "c3-g65-real-scene-transcript.txt"
$outputPath = Join-Path $EvidenceRoot "c3-g65-real-scene-output.txt"
$screenshotPath = Join-Path $EvidenceRoot "c3-g65-real-scene-readback.png"
$buildDir = Join-Path $cppRoot "build\vs2022-ramses-28.16"

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
    Write-Host "C-3 G65 real Ramses scene"
    Write-Host "Ramses version: $RamsesVersion"
    Write-Host "Ramses install: $RamsesInstall"
    Write-Host "Scene file: $SceneFile"
    Write-Host "Frames: $Frames"
    Write-Host "Evidence root: $EvidenceRoot"

    if (-not (Test-Path -LiteralPath $SceneFile -PathType Leaf)) {
        throw "Scene file not found: $SceneFile"
    }

    Push-Location $cppRoot
    try {
        Invoke-Native "configure SGFX C++ C-3 real scene app" {
            cmake -S . -B $buildDir -G "Visual Studio 17 2022" -A x64 `
                "-DCMAKE_PREFIX_PATH=$RamsesInstall" `
                "-Dramses-shared-lib_DIR=$RamsesInstall\lib\ramses-shared-lib-$($RamsesVersion.Substring(0, $RamsesVersion.LastIndexOf('.')))\cmake" `
                "-DSGFX_CINE_RAMSES_VERSION=$RamsesVersion"
        }

        Invoke-Native "build SGFX C++ C-3 real scene app" {
            cmake --build $buildDir --config Release --target sgfx_cine_ramses_real_scene
        }
    }
    finally {
        Pop-Location
    }

    $sceneExe = Join-Path $buildDir "Release\sgfx_cine_ramses_real_scene.exe"
    Write-Host ""
    Write-Host "== run SGFX C++ C-3 real scene app =="
    $sceneOutput = & $sceneExe --scene-file $SceneFile --frames $Frames --no-auto-frame --no-orbit --readback --screenshot $screenshotPath 2>&1
    $sceneExitCode = $LASTEXITCODE
    $sceneOutput | Tee-Object -LiteralPath $outputPath
    if ($sceneExitCode -ne 0) {
        throw "run SGFX C++ C-3 real scene app failed with exit code $sceneExitCode"
    }

    Write-Host ""
    Write-Host "C-3 G65 real scene complete."
    Write-Host "Transcript: $transcriptPath"
    Write-Host "Output: $outputPath"
    Write-Host "Readback PNG: $screenshotPath"
}
finally {
    Stop-Transcript | Out-Null
}
