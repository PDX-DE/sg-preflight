param(
    [string]$RamsesVersion = "28.16.0",
    [string]$RamsesInstall = "C:\ramses-28.16.0-install",
    [int]$Frames = 168,
    [int]$SkipAfterMs = 500,
    [int]$EnterHubAfterMs = 850,
    [int]$PlanetFrames = 48,
    [int]$PlanetRenderWidth = 1024,
    [int]$PlanetRenderHeight = 768,
    [string]$EvidenceRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$cppRoot = Resolve-Path -LiteralPath (Join-Path $scriptRoot "..")
$repoRoot = Resolve-Path -LiteralPath (Join-Path $cppRoot "..")

if ([string]::IsNullOrWhiteSpace($EvidenceRoot)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $EvidenceRoot = Join-Path $repoRoot "out\cpp\ramses-rmlui-planet-hub-h1-$stamp"
}

New-Item -ItemType Directory -Force -Path $EvidenceRoot | Out-Null
$transcriptPath = Join-Path $EvidenceRoot "ramses-rmlui-planet-hub-h1-transcript.txt"
$outputPath = Join-Path $EvidenceRoot "ramses-rmlui-planet-hub-h1-output.txt"
$readbackPath = Join-Path $EvidenceRoot "ramses-rmlui-planet-hub-h1-readback.bmp"
$summaryPath = Join-Path $EvidenceRoot "ramses-rmlui-planet-hub-h1-summary.json"
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
    $lines = & $Body 2>&1
    $exitCode = $LASTEXITCODE
    $lines | Tee-Object -FilePath $OutputPath
    if ($exitCode -ne 0) {
        throw "$Label failed with exit code $exitCode"
    }
}

Start-Transcript -LiteralPath $transcriptPath | Out-Null
try {
    Write-Host "SGFX Ramses -> RmlUi planet hub H1"
    Write-Host "Ramses version: $RamsesVersion"
    Write-Host "Ramses install: $RamsesInstall"
    Write-Host "Frames: $Frames"
    Write-Host "Skip after ms: $SkipAfterMs"
    Write-Host "Enter hub after ms: $EnterHubAfterMs"
    Write-Host "Planet producer frames: $PlanetFrames"
    Write-Host "Planet render size: ${PlanetRenderWidth}x${PlanetRenderHeight}"
    Write-Host "Asset root: $assetRoot"
    Write-Host "Font root: $fontRoot"
    Write-Host "Evidence root: $EvidenceRoot"

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
    if (-not (Test-Path -LiteralPath $shellExe)) {
        throw "Expected cinematic shell executable was not built: $shellExe"
    }

    Invoke-CaptureNative "run Ramses -> RmlUi planet hub H1 shell" $outputPath {
        & $shellExe `
            --frames $Frames `
            --skip-after-ms $SkipAfterMs `
            --demo-menu-focus 2 `
            --demo-enter-viewer-after-ms $EnterHubAfterMs `
            --hub-planet `
            --hub-planet-frames $PlanetFrames `
            --hub-planet-render-width $PlanetRenderWidth `
            --hub-planet-render-height $PlanetRenderHeight `
            --no-delay `
            --asset-root $assetRoot `
            --font-root $fontRoot `
            --readback `
            --screenshot $readbackPath
    }

    $summary = [ordered]@{
        evidence_root = $EvidenceRoot
        output = $outputPath
        readback = $readbackPath
        target = "sgfx_cine_cinematic_shell"
        hub_slice = "H1: procedural SGFX planet rendered by Ramses and surfaced in RmlUi"
        ramses_version = $RamsesVersion
        renderer_backend = "RmlUi GL3"
        planet_pipe = "Ramses procedural scene -> offscreen buffer -> readPixels -> RmlUi-owned CallbackTexture decorator"
        planet_render_size = "${PlanetRenderWidth}x${PlanetRenderHeight}"
        planet_producer_frames = $PlanetFrames
        menu_route = "Modules / Pipelines -> Seriengrafik world hub"
        clean_room = "SGFX-owned procedural faceted sphere; not Earth; no game art/assets"
    }
    $summary | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
    Write-Host "SGFX planet hub H1 summary: $summaryPath"
    Write-Host "SGFX planet hub H1 evidence complete."
}
finally {
    Stop-Transcript | Out-Null
}
