param(
    [string]$RamsesVersion = "28.16.0",
    [string]$RamsesInstall = "C:\ramses-28.16.0-install",
    [int]$SplashFrames = 70,
    [int]$HeroFrames = 210,
    [int]$SkipFrames = 300,
    [int]$MenuJuiceFrames = 96,
    [int]$FlyIntoFrames = 156,
    [int]$SkipAfterMs = 700,
    [string]$EvidenceRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$cppRoot = Resolve-Path -LiteralPath (Join-Path $scriptRoot "..")
$repoRoot = Resolve-Path -LiteralPath (Join-Path $cppRoot "..")

if ([string]::IsNullOrWhiteSpace($EvidenceRoot)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $EvidenceRoot = Join-Path $repoRoot "out\cpp\cinematic-shell-intro-$stamp"
}

New-Item -ItemType Directory -Force -Path $EvidenceRoot | Out-Null
$transcriptPath = Join-Path $EvidenceRoot "cinematic-shell-intro-transcript.txt"
$splashOutputPath = Join-Path $EvidenceRoot "splash-hold-output.txt"
$heroOutputPath = Join-Path $EvidenceRoot "hero-hold-output.txt"
$skipOutputPath = Join-Path $EvidenceRoot "skip-to-menu-output.txt"
$menuJuiceOutputPath = Join-Path $EvidenceRoot "menu-juice-output.txt"
$flyIntoOutputPath = Join-Path $EvidenceRoot "fly-into-viewer-output.txt"
$splashReadbackPath = Join-Path $EvidenceRoot "splash-hold-readback.bmp"
$heroReadbackPath = Join-Path $EvidenceRoot "hero-hold-readback.bmp"
$skipReadbackPath = Join-Path $EvidenceRoot "skip-to-menu-readback.bmp"
$menuJuiceReadbackPath = Join-Path $EvidenceRoot "menu-juice-readback.bmp"
$flyIntoReadbackPath = Join-Path $EvidenceRoot "fly-into-viewer-readback.bmp"
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
    Write-Host "SGFX cinematic shell intro run"
    Write-Host "Ramses version: $RamsesVersion"
    Write-Host "Ramses install: $RamsesInstall"
    Write-Host "Splash frames: $SplashFrames"
    Write-Host "Hero frames: $HeroFrames"
    Write-Host "Skip frames: $SkipFrames"
    Write-Host "Menu juice frames: $MenuJuiceFrames"
    Write-Host "Fly-into frames: $FlyIntoFrames"
    Write-Host "Skip after ms: $SkipAfterMs"
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

    Invoke-CaptureNative "run splash-hold readback" $splashOutputPath {
        & $shellExe `
            --frames $SplashFrames `
            --no-delay `
            --asset-root $assetRoot `
            --font-root $fontRoot `
            --readback `
            --screenshot $splashReadbackPath
    }

    Invoke-CaptureNative "run hero-hold readback" $heroOutputPath {
        & $shellExe `
            --frames $HeroFrames `
            --no-delay `
            --asset-root $assetRoot `
            --font-root $fontRoot `
            --readback `
            --screenshot $heroReadbackPath
    }

    Invoke-CaptureNative "run scripted skip-to-menu readback" $skipOutputPath {
        & $shellExe `
            --frames $SkipFrames `
            --skip-after-ms $SkipAfterMs `
            --no-delay `
            --asset-root $assetRoot `
            --font-root $fontRoot `
            --readback `
            --screenshot $skipReadbackPath
    }

    Invoke-CaptureNative "run animated menu juice readback" $menuJuiceOutputPath {
        & $shellExe `
            --frames $MenuJuiceFrames `
            --skip-after-ms 500 `
            --demo-menu-focus 1 `
            --demo-menu-pulse-after-ms 760 `
            --no-delay `
            --asset-root $assetRoot `
            --font-root $fontRoot `
            --readback `
            --screenshot $menuJuiceReadbackPath
    }

    Invoke-CaptureNative "run fly-into-viewer readback" $flyIntoOutputPath {
        & $shellExe `
            --frames $FlyIntoFrames `
            --skip-after-ms 500 `
            --demo-menu-focus 1 `
            --demo-enter-viewer-after-ms 850 `
            --no-delay `
            --asset-root $assetRoot `
            --font-root $fontRoot `
            --readback `
            --screenshot $flyIntoReadbackPath
    }

    $summary = [ordered]@{
        evidence_root = $EvidenceRoot
        splash_output = $splashOutputPath
        splash_readback = $splashReadbackPath
        hero_output = $heroOutputPath
        hero_readback = $heroReadbackPath
        skip_output = $skipOutputPath
        skip_readback = $skipReadbackPath
        menu_juice_output = $menuJuiceOutputPath
        menu_juice_readback = $menuJuiceReadbackPath
        fly_into_output = $flyIntoOutputPath
        fly_into_readback = $flyIntoReadbackPath
        target = "sgfx_cine_cinematic_shell"
        rmlui = "6.2"
        rmlui_font_engine = "freetype"
        renderer_backend = "RmlUi GL3"
        renderer_look = "native GL3 Adventure Dawn gradients + box-shadow glow accents"
        menu_animation = "0.25s item reveal, 70ms stagger, pointer/keyboard focus, 120ms pulse feedback"
        fly_into_zone = "3D Car viewer card expands to viewer-zone destination over 0.70s; back-out path 0.50s via Escape/Backspace in interactive mode"
        brand_assets = @("logo_sgfx.png", "framework_sgfx_logo.png", "debug_icon.png", "sgfx_icon.png")
        fonts = @("Fredoka.ttf", "Inter.ttf")
        timings = "splash 0.3/1.2/0.3s; hero 0.5/1.6/0.4s; any key/click skips to menu"
    }
    $summaryPath = Join-Path $EvidenceRoot "cinematic-shell-intro-summary.json"
    $summary | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
    Write-Host "SGFX cinematic shell summary: $summaryPath"
    Write-Host "SGFX cinematic shell intro evidence complete."
}
finally {
    Stop-Transcript | Out-Null
}
