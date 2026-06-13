param(
    [string]$RamsesVersion = "28.16.0",
    [string]$RamsesInstall = "C:\ramses-28.16.0-install",
    [string]$ProfileId = "G65",
    [string]$SceneFile = "C:\3D Car git\digital-3d-car-models\cars\BMW\G65_EVO\export\exported.ramses",
    [string]$PerspectiveSet = "CID170_LHD",
    [string[]]$PerspectiveIds = @("CID_CARHUB_ALL_GOOD", "CID_ADAS_SENSORS_MAIN"),
    [int]$Width = 1280,
    [int]$Height = 720,
    [int]$Frames = 156,
    [int]$FusionFrames = 60,
    [string]$EvidenceRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$cppRoot = Resolve-Path -LiteralPath (Join-Path $scriptRoot "..")
$repoRoot = Resolve-Path -LiteralPath (Join-Path $cppRoot "..")

if ([string]::IsNullOrWhiteSpace($EvidenceRoot)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $EvidenceRoot = Join-Path $repoRoot "out\cpp\ramses-rmlui-fusion-phase4-$($ProfileId.ToLowerInvariant())-$stamp"
}

New-Item -ItemType Directory -Force -Path $EvidenceRoot | Out-Null
$transcriptPath = Join-Path $EvidenceRoot "ramses-rmlui-fusion-phase4-transcript.txt"
$summaryPath = Join-Path $EvidenceRoot "ramses-rmlui-fusion-phase4-summary.json"
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

function ConvertTo-SafeName {
    param([Parameter(Mandatory = $true)][string]$Value)
    return ($Value.ToLowerInvariant() -replace '[^a-z0-9_-]', '-')
}

Start-Transcript -LiteralPath $transcriptPath | Out-Null
try {
    Write-Host "SGFX Ramses -> RmlUi fusion Phase 4"
    Write-Host "Ramses version: $RamsesVersion"
    Write-Host "Ramses install: $RamsesInstall"
    Write-Host "Profile id: $ProfileId"
    Write-Host "Scene file: $SceneFile"
    Write-Host "Perspective set: $PerspectiveSet"
    Write-Host "Perspective ids: $($PerspectiveIds -join ', ')"
    Write-Host "Resolution: ${Width}x${Height}"
    Write-Host "Shell frames: $Frames"
    Write-Host "Fusion max producer frames: $FusionFrames"
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

        $shellExe = Join-Path $buildDir "Release\sgfx_cine_cinematic_shell.exe"
        if (-not (Test-Path -LiteralPath $shellExe -PathType Leaf)) {
            throw "Expected cinematic shell executable was not built: $shellExe"
        }

        $runSummaries = @()
        foreach ($perspectiveId in $PerspectiveIds) {
            $safePerspectiveId = ConvertTo-SafeName $perspectiveId
            $outputPath = Join-Path $EvidenceRoot "ramses-rmlui-fusion-phase4-$safePerspectiveId-output.txt"
            $readbackPath = Join-Path $EvidenceRoot "ramses-rmlui-fusion-phase4-$safePerspectiveId-readback.bmp"

            Invoke-CaptureNative "run Ramses -> RmlUi fusion Phase 4 shell ($perspectiveId)" $outputPath {
                & $shellExe `
                    --width $Width `
                    --height $Height `
                    --frames $Frames `
                    --skip-after-ms 500 `
                    --demo-menu-focus 1 `
                    --demo-enter-viewer-after-ms 850 `
                    --no-delay `
                    --asset-root (Join-Path $cppRoot "assets") `
                    --font-root (Join-Path $cppRoot "assets\fonts") `
                    --fusion-scene-file $SceneFile `
                    --fusion-profile-id $ProfileId `
                    --fusion-frames $FusionFrames `
                    --fusion-perspective-set $PerspectiveSet `
                    --fusion-perspective-id $perspectiveId `
                    --readback `
                    --screenshot $readbackPath
            }

            $runSummaries += [ordered]@{
                perspective_id = $perspectiveId
                output = $outputPath
                shell_readback = $readbackPath
            }
        }
    }
    finally {
        Pop-Location
    }

    $summary = [ordered]@{
        evidence_root = $EvidenceRoot
        target = "sgfx_cine_cinematic_shell"
        profile_id = $ProfileId
        scene_file = $SceneFile
        fusion_phase = "Phase 4: adaptive render-on-demand Ramses readPixels/cache plus per-view validation"
        perspective_set = $PerspectiveSet
        perspectives = $runSummaries
        resolution = "${Width}x${Height}"
        shell_frames = $Frames
        fusion_max_producer_frames = $FusionFrames
        expected_visual = "Live grey G65 in the RmlUi viewer panel for CID_CARHUB_ALL_GOOD and CID_ADAS_SENSORS_MAIN."
    }
    $summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
    Write-Host "SGFX Ramses -> RmlUi fusion Phase 4 summary: $summaryPath"
    Write-Host "SGFX Ramses -> RmlUi fusion Phase 4 evidence complete."
}
finally {
    Stop-Transcript | Out-Null
}
