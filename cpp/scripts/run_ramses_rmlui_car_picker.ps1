param(
    [string]$RamsesVersion = "28.16.0",
    [string]$RamsesInstall = "C:\ramses-28.16.0-install",
    [string]$CarsRoot = "C:\3D Car git\digital-3d-car-models\cars\BMW",
    [int]$CarPickIndex = 1,
    [int]$FusionFrames = 60,
    [int]$Frames = 230,
    [string]$EvidenceRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$cppRoot = Resolve-Path -LiteralPath (Join-Path $scriptRoot "..")
$repoRoot = Resolve-Path -LiteralPath (Join-Path $cppRoot "..")

if ([string]::IsNullOrWhiteSpace($EvidenceRoot)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $EvidenceRoot = Join-Path $repoRoot "out\cpp\ramses-rmlui-car-picker-$stamp"
}

New-Item -ItemType Directory -Force -Path $EvidenceRoot | Out-Null
$transcriptPath = Join-Path $EvidenceRoot "ramses-rmlui-car-picker-transcript.txt"
$outputPath = Join-Path $EvidenceRoot "ramses-rmlui-car-picker-output.txt"
$readbackPath = Join-Path $EvidenceRoot "ramses-rmlui-car-picker-readback.bmp"
$summaryPath = Join-Path $EvidenceRoot "ramses-rmlui-car-picker-summary.json"
$buildDir = Join-Path $cppRoot "build\vs2022-ramses-28.16"
$assetRoot = Join-Path $cppRoot "assets"
$fontRoot = Join-Path $assetRoot "fonts"

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

function Invoke-CaptureNative {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string]$OutputPath,
        [Parameter(Mandatory = $true)][scriptblock]$Body
    )

    Write-Host ""
    Write-Host "== $Label =="
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $lines = & $Body 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    $lines | Tee-Object -FilePath $OutputPath
    if ($exitCode -ne 0) {
        throw "$Label failed with exit code $exitCode"
    }
}

Start-Transcript -LiteralPath $transcriptPath | Out-Null
try {
    Write-Host "SGFX Ramses -> RmlUi car picker"
    Write-Host "Ramses version: $RamsesVersion"
    Write-Host "Ramses install: $RamsesInstall"
    Write-Host "Cars root: $CarsRoot"
    Write-Host "Demo car pick index: $CarPickIndex"
    Write-Host "Fusion producer frames: $FusionFrames"
    Write-Host "Evidence root: $EvidenceRoot"

    if (-not (Test-Path -LiteralPath $CarsRoot -PathType Container)) {
        throw "Cars root not found: $CarsRoot"
    }

    Push-Location $cppRoot
    try {
        Invoke-Native "configure SGFX C++ cinematic shell" {
            cmake -S . -B $buildDir -G "Visual Studio 17 2022" -A x64 `
                "-DCMAKE_PREFIX_PATH=$RamsesInstall" `
                "-Dramses-shared-lib_DIR=$RamsesInstall\lib\ramses-shared-lib-$($RamsesVersion.Substring(0, $RamsesVersion.LastIndexOf('.')))\cmake" `
                "-DSGFX_CINE_RAMSES_VERSION=$RamsesVersion"
        }

        Invoke-Native "build SGFX C++ cinematic shell" {
            cmake --build $buildDir --config Release --target sgfx_cine_cinematic_shell
        }
    }
    finally {
        Pop-Location
    }

    $shellExe = Join-Path $buildDir "Release\sgfx_cine_cinematic_shell.exe"
    if (-not (Test-Path -LiteralPath $shellExe -PathType Leaf)) {
        throw "Expected cinematic shell executable was not built: $shellExe"
    }

    Invoke-CaptureNative "run no-scene car picker shell smoke" $outputPath {
        & $shellExe `
            --frames $Frames `
            --skip-after-ms 500 `
            --demo-menu-focus 1 `
            --demo-enter-viewer-after-ms 850 `
            --demo-car-pick-index $CarPickIndex `
            --demo-car-pick-after-ms 550 `
            --fusion-cars-root $CarsRoot `
            --fusion-frames $FusionFrames `
            --no-delay `
            --asset-root $assetRoot `
            --font-root $fontRoot `
            --readback `
            --screenshot $readbackPath
    }

    $summary = [ordered]@{
        evidence_root = $EvidenceRoot
        target = "sgfx_cine_cinematic_shell"
        shell_slice = "Profile-agnostic in-shell 3D Car picker"
        ramses_version = $RamsesVersion
        cars_root = $CarsRoot
        initial_selection = "No --fusion-scene-file; shell chooses first discovered registry-ordered export"
        demo_pick_index = $CarPickIndex
        fusion_frames = $FusionFrames
        output = $outputPath
        readback = $readbackPath
        expected_final_state = "viewer-zone"
        expected_marker = "SGFX cinematic shell car picker beat OK"
        clean_room = "Real BMW Ramses exports only; no game art/assets"
    }
    $summary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
    Write-Host "SGFX car picker summary: $summaryPath"
    Write-Host "SGFX car picker evidence complete."
}
finally {
    Stop-Transcript | Out-Null
}
