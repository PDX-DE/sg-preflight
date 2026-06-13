param(
    [string]$RamsesVersion = "28.16.0",
    [string]$RamsesInstall = "C:\ramses-28.16.0-install",
    [string]$ProfileId = "G65",
    [string]$SceneFile = "C:\3D Car git\digital-3d-car-models\cars\BMW\G65_EVO\export\exported.ramses",
    [string]$PerspectiveSet = "CID170_LHD",
    [string]$PerspectiveId = "CID_CARHUB_ALL_GOOD",
    [int]$FusionFrames = 60,
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
    $EvidenceRoot = Join-Path $repoRoot "out\cpp\ramses-rmlui-planet-hub-h3-$stamp"
}

New-Item -ItemType Directory -Force -Path $EvidenceRoot | Out-Null
$transcriptPath = Join-Path $EvidenceRoot "ramses-rmlui-planet-hub-h3-transcript.txt"
$summaryPath = Join-Path $EvidenceRoot "ramses-rmlui-planet-hub-h3-summary.json"
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
    Write-Host "SGFX Ramses -> RmlUi planet hub H3"
    Write-Host "Ramses version: $RamsesVersion"
    Write-Host "Ramses install: $RamsesInstall"
    Write-Host "Profile id: $ProfileId"
    Write-Host "Scene file: $SceneFile"
    Write-Host "Perspective set/id: $PerspectiveSet/$PerspectiveId"
    Write-Host "Fusion producer frames: $FusionFrames"
    Write-Host "Planet producer frames: $PlanetFrames"
    Write-Host "Planet render size: ${PlanetRenderWidth}x${PlanetRenderHeight}"
    Write-Host "Evidence root: $EvidenceRoot"

    if (-not (Test-Path -LiteralPath $SceneFile -PathType Leaf)) {
        throw "Scene file not found: $SceneFile"
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

    $enterOutputPath = Join-Path $EvidenceRoot "ramses-rmlui-planet-hub-h3-enter-output.txt"
    $enterReadbackPath = Join-Path $EvidenceRoot "ramses-rmlui-planet-hub-h3-enter-readback.bmp"
    $roundtripOutputPath = Join-Path $EvidenceRoot "ramses-rmlui-planet-hub-h3-roundtrip-output.txt"
    $roundtripReadbackPath = Join-Path $EvidenceRoot "ramses-rmlui-planet-hub-h3-roundtrip-readback.bmp"

    $baseArgs = @(
        "--skip-after-ms", "500",
        "--demo-menu-focus", "2",
        "--demo-enter-viewer-after-ms", "850",
        "--demo-hub-node-enter-after-ms", "450",
        "--hub-planet",
        "--hub-nodes",
        "--hub-planet-frames", "$PlanetFrames",
        "--hub-planet-render-width", "$PlanetRenderWidth",
        "--hub-planet-render-height", "$PlanetRenderHeight",
        "--fusion-scene-file", "$SceneFile",
        "--fusion-profile-id", "$ProfileId",
        "--fusion-frames", "$FusionFrames",
        "--fusion-perspective-set", "$PerspectiveSet",
        "--fusion-perspective-id", "$PerspectiveId",
        "--no-delay",
        "--asset-root", "$assetRoot",
        "--font-root", "$fontRoot",
        "--readback"
    )

    Invoke-CaptureNative "run H3 planet -> live 3D Car viewer" $enterOutputPath {
        & $shellExe @baseArgs `
            --frames 230 `
            --screenshot $enterReadbackPath
    }

    Invoke-CaptureNative "run H3 planet -> live 3D Car viewer -> planet roundtrip" $roundtripOutputPath {
        & $shellExe @baseArgs `
            --frames 312 `
            --demo-viewer-back-after-ms 550 `
            --screenshot $roundtripReadbackPath
    }

    $summary = [ordered]@{
        evidence_root = $EvidenceRoot
        target = "sgfx_cine_cinematic_shell"
        hub_slice = "H3: 3D Car capital node flies into the fused live Ramses car viewer and returns to the planet hub"
        profile_id = $ProfileId
        scene_file = $SceneFile
        perspective_set = $PerspectiveSet
        perspective_id = $PerspectiveId
        ramses_version = $RamsesVersion
        planet_pipe = "Ramses procedural scene -> offscreen buffer -> readPixels -> RmlUi-owned CallbackTexture decorator"
        car_pipe = "BMW Ramses export -> offscreen buffer -> readPixels -> borrowed RmlUi CallbackTexture decorator"
        enter = [ordered]@{
            output = $enterOutputPath
            readback = $enterReadbackPath
            expected_final_state = "viewer-zone"
        }
        roundtrip = [ordered]@{
            output = $roundtripOutputPath
            readback = $roundtripReadbackPath
            expected_final_state = "hub"
        }
        clean_room = "SGFX-owned planet/nodes plus real BMW survey export; no game art/assets"
    }
    $summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
    Write-Host "SGFX planet hub H3 summary: $summaryPath"
    Write-Host "SGFX planet hub H3 evidence complete."
}
finally {
    Stop-Transcript | Out-Null
}
