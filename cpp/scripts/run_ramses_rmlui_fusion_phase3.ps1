param(
    [string]$RamsesVersion = "28.16.0",
    [string]$RamsesInstall = "C:\ramses-28.16.0-install",
    [string]$ProfileId = "G65",
    [string]$SceneFile = "C:\3D Car git\digital-3d-car-models\cars\BMW\G65_EVO\export\exported.ramses",
    [string]$PerspectiveSet = "CID170_LHD",
    [string]$PerspectiveId = "CID_ADAS_SENSORS_MAIN",
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
    $EvidenceRoot = Join-Path $repoRoot "out\cpp\ramses-rmlui-fusion-phase3-$($ProfileId.ToLowerInvariant())-$stamp"
}

New-Item -ItemType Directory -Force -Path $EvidenceRoot | Out-Null
$transcriptPath = Join-Path $EvidenceRoot "ramses-rmlui-fusion-phase3-transcript.txt"
$outputPath = Join-Path $EvidenceRoot "ramses-rmlui-fusion-phase3-output.txt"
$readbackPath = Join-Path $EvidenceRoot "ramses-rmlui-fusion-phase3-readback.bmp"
$summaryPath = Join-Path $EvidenceRoot "ramses-rmlui-fusion-phase3-summary.json"
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

Start-Transcript -LiteralPath $transcriptPath | Out-Null
try {
    Write-Host "SGFX Ramses -> RmlUi fusion Phase 3"
    Write-Host "Ramses version: $RamsesVersion"
    Write-Host "Ramses install: $RamsesInstall"
    Write-Host "Profile id: $ProfileId"
    Write-Host "Scene file: $SceneFile"
    Write-Host "Perspective set/id: $PerspectiveSet/$PerspectiveId"
    Write-Host "Resolution: ${Width}x${Height}"
    Write-Host "Shell frames: $Frames"
    Write-Host "Fusion frames: $FusionFrames"
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

        Invoke-CaptureNative "run Ramses -> RmlUi fusion Phase 3 shell" $outputPath {
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
                --fusion-perspective-id $PerspectiveId `
                --readback `
                --screenshot $readbackPath
        }
    }
    finally {
        Pop-Location
    }

    $summary = [ordered]@{
        evidence_root = $EvidenceRoot
        output = $outputPath
        shell_readback = $readbackPath
        target = "sgfx_cine_cinematic_shell"
        profile_id = $ProfileId
        scene_file = $SceneFile
        fusion_phase = "Phase 3: app-parsed perspectives_*.json -> C-3/C-4 camera-crane logic -> RmlUi QA picker over live Ramses texture"
        perspective_set = $PerspectiveSet
        perspective_id = $PerspectiveId
        resolution = "${Width}x${Height}"
        shell_frames = $Frames
        fusion_frames = $FusionFrames
        expected_visual = "Live grey G65 in the RmlUi viewer panel with the QA perspective picker composited over it."
    }
    $summary | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
    Write-Host "SGFX Ramses -> RmlUi fusion Phase 3 summary: $summaryPath"
    Write-Host "SGFX Ramses -> RmlUi fusion Phase 3 evidence complete."
}
finally {
    Stop-Transcript | Out-Null
}
