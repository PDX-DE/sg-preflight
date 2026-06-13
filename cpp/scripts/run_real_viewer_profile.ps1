param(
    [string]$RamsesVersion = "28.16.0",
    [string]$RamsesInstall = "C:\ramses-28.16.0-install",
    [string]$ProfileId = "G65",
    [string]$SceneFile = "",
    [string]$BmwModelsRoot = "",
    [double]$Zoom = 1.0,
    [ValidateSet("three-quarter", "front", "rear", "left", "right")]
    [string]$ViewPreset = "three-quarter",
    [string]$PerspectiveSet = "",
    [string]$PerspectiveId = "",
    [string]$PerspectiveFile = "",
    [switch]$AutoFrame,
    [switch]$NoAutoFrame,
    [switch]$Orbit,
    [switch]$NoOrbit,
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
    $EvidenceRoot = Join-Path $repoRoot "out\cpp\real-viewer-profile-$($ProfileId.ToLowerInvariant())-$stamp"
}

New-Item -ItemType Directory -Force -Path $EvidenceRoot | Out-Null
$transcriptPath = Join-Path $EvidenceRoot "real-viewer-profile-transcript.txt"
$outputPath = Join-Path $EvidenceRoot "real-viewer-profile-output.txt"
$profilePath = Join-Path $EvidenceRoot "real-viewer-profile.json"
$screenshotPath = Join-Path $EvidenceRoot "real-viewer-profile-readback.png"
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
    Write-Host "SGFX real viewer profile run"
    Write-Host "Ramses version: $RamsesVersion"
    Write-Host "Ramses install: $RamsesInstall"
    Write-Host "Profile id: $ProfileId"
    Write-Host "Scene file override: $SceneFile"
    Write-Host "BMW models root override: $BmwModelsRoot"
    Write-Host "Presentation mode: authored-passes"
    Write-Host "Auto-frame authored camera: $($AutoFrame -and -not $NoAutoFrame)"
    Write-Host "Orbit authored camera: $($Orbit -and -not $NoOrbit)"
    Write-Host "Zoom: $Zoom"
    Write-Host "View preset: $ViewPreset"
    Write-Host "Perspective set: $PerspectiveSet"
    Write-Host "Perspective id: $PerspectiveId"
    Write-Host "Perspective file override: $PerspectiveFile"
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

        $resolveProfileScript = @'
import json
import os
import sys
from pathlib import Path

from sg_preflight.bmw_delivery import candidate_bmw_profile_ids
from sg_preflight.profiles import get_run_profile

profile_id = sys.argv[1]
explicit_models_root = sys.argv[2]
explicit_scene_file = sys.argv[3]
workspace = Path.cwd()
profile = get_run_profile(profile_id, workspace)

roots = []

def add_root(raw):
    if not raw:
        return
    path = Path(raw)
    if path not in roots:
        roots.append(path)

add_root(explicit_models_root)
for key in ("SG_BMW_CAR_MODELS_ROOT", "SG_CARMODELS_REPO", "SG-CarModels-Repo"):
    add_root(os.environ.get(key, "").strip())
add_root(Path(r"C:\3D Car git\digital-3d-car-models"))
add_root(workspace / "digital-3d-car-models")
add_root(workspace / "external" / "digital-3d-car-models")
add_root(workspace.parent / "digital-3d-car-models")
add_root(Path(r"C:\repos\digital-3d-car-models"))

candidate_ids = list(candidate_bmw_profile_ids(profile.profile_id))
attempted = []
scene_file = Path(explicit_scene_file) if explicit_scene_file else None
resolved_bmw_profile_id = ""
resolved_models_root = ""

if scene_file:
    attempted.append(str(scene_file))
else:
    for root in roots:
        for candidate_id in candidate_ids:
            candidate_scene = root / "cars" / "BMW" / candidate_id / "export" / "exported.ramses"
            attempted.append(str(candidate_scene))
            if candidate_scene.exists():
                scene_file = candidate_scene
                resolved_bmw_profile_id = candidate_id
                resolved_models_root = str(root)
                break
        if scene_file is not None:
            break

if scene_file is None or not scene_file.exists():
    raise SystemExit(
        "No exported.ramses found for profile "
        + profile.profile_id
        + ". Tried: "
        + json.dumps(attempted)
    )

print(json.dumps({
    "profile_id": profile.profile_id,
    "label": profile.label,
    "project_relative": str(profile.project_relative),
    "source_project_root": str(profile.source_project_root()),
    "evidence_source": profile.source_evidence_source(),
    "candidate_bmw_profile_ids": candidate_ids,
    "bmw_profile_id": resolved_bmw_profile_id,
    "bmw_models_root": resolved_models_root,
    "scene_file": str(scene_file),
    "attempted_scene_files": attempted,
}, sort_keys=True))
'@

        Write-Host "real-viewer profile resolver python: $pythonExe $($pythonPrefixArgs -join ' ')"
        $profileJson = & $pythonExe @pythonPrefixArgs -B -c $resolveProfileScript $ProfileId $BmwModelsRoot $SceneFile 2>&1
        if ($LASTEXITCODE -ne 0) {
            $profileJson | ForEach-Object { Write-Host $_ }
            throw "resolve profile scene failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }

    $profile = $profileJson | ConvertFrom-Json
    $resolvedProfileId = [string]$profile.profile_id
    $resolvedSceneFile = [string]$profile.scene_file
    $profileJson | Set-Content -LiteralPath $profilePath -Encoding UTF8
    Write-Host "real-viewer resolved profile id: $resolvedProfileId"
    Write-Host "real-viewer resolved BMW profile id: $($profile.bmw_profile_id)"
    Write-Host "real-viewer resolved BMW models root: $($profile.bmw_models_root)"
    Write-Host "real-viewer resolved scene file: $resolvedSceneFile"
    Write-Host "real-viewer profile evidence JSON: $profilePath"

    function Format-InvariantNumber {
        param([Parameter(Mandatory = $true)][double]$Value)
        return [string]::Format([Globalization.CultureInfo]::InvariantCulture, "{0:R}", $Value)
    }

    $resolvedPerspective = $null
    if (-not [string]::IsNullOrWhiteSpace($PerspectiveSet) -or -not [string]::IsNullOrWhiteSpace($PerspectiveFile)) {
        $candidatePerspectiveFiles = @()
        if (-not [string]::IsNullOrWhiteSpace($PerspectiveFile)) {
            $candidatePerspectiveFiles += $PerspectiveFile
        }
        else {
            $perspectiveFileName = $PerspectiveSet
            if (-not $perspectiveFileName.StartsWith("perspectives_", [StringComparison]::OrdinalIgnoreCase)) {
                $perspectiveFileName = "perspectives_$perspectiveFileName"
            }
            if (-not $perspectiveFileName.EndsWith(".json", [StringComparison]::OrdinalIgnoreCase)) {
                $perspectiveFileName = "$perspectiveFileName.json"
            }

            $sceneExportDir = Split-Path -Parent $resolvedSceneFile
            $sceneProfileDir = Split-Path -Parent $sceneExportDir
            $candidatePerspectiveFiles += (Join-Path $sceneProfileDir $perspectiveFileName)
            if (-not [string]::IsNullOrWhiteSpace([string]$profile.bmw_models_root)) {
                $candidatePerspectiveFiles += (Join-Path (Join-Path ([string]$profile.bmw_models_root) "cars\BMW") $perspectiveFileName)
            }
        }

        $resolvedPerspectiveFile = ""
        foreach ($candidatePerspectiveFile in $candidatePerspectiveFiles) {
            if (Test-Path -LiteralPath $candidatePerspectiveFile) {
                $resolvedPerspectiveFile = (Resolve-Path -LiteralPath $candidatePerspectiveFile).Path
                break
            }
        }
        if ([string]::IsNullOrWhiteSpace($resolvedPerspectiveFile)) {
            throw "No perspective file found. Tried: $($candidatePerspectiveFiles -join '; ')"
        }

        $perspectiveJson = Get-Content -LiteralPath $resolvedPerspectiveFile -Raw | ConvertFrom-Json
        $perspectiveProperties = @($perspectiveJson.PSObject.Properties)
        if ($perspectiveProperties.Count -eq 0) {
            throw "Perspective file has no top-level views: $resolvedPerspectiveFile"
        }

        $selectedPerspectiveId = $PerspectiveId
        if ([string]::IsNullOrWhiteSpace($selectedPerspectiveId)) {
            $defaultPerspective = $perspectiveProperties | Where-Object { $_.Name -eq "CID_CARHUB_ALL_GOOD" } | Select-Object -First 1
            if ($null -eq $defaultPerspective) {
                $defaultPerspective = $perspectiveProperties[0]
            }
            $selectedPerspectiveId = $defaultPerspective.Name
        }

        $selectedPerspective = $perspectiveJson.PSObject.Properties[$selectedPerspectiveId]
        if ($null -eq $selectedPerspective) {
            throw "Perspective id '$selectedPerspectiveId' was not found in $resolvedPerspectiveFile"
        }

        $perspectiveValue = $selectedPerspective.Value
        $resolvedPerspective = [pscustomobject]@{
            File = $resolvedPerspectiveFile
            Id = $selectedPerspectiveId
            AspectFromResolution = [bool]$perspectiveValue.AspectFromResolution_isEnabled
            Distance = [double]$perspectiveValue.CraneGimbal.Distance
            Yaw = [double]$perspectiveValue.CraneGimbal.Yaw
            Pitch = [double]$perspectiveValue.CraneGimbal.Pitch
            Roll = [double]$perspectiveValue.CraneGimbal.Roll
            HorizontalFov = [double]$perspectiveValue.Frustum.HorizontalFOV
            AspectRatio = [double]$perspectiveValue.Frustum.AspectRatio
            NearPlane = [double]$perspectiveValue.Frustum.NearPlane
            FarPlane = [double]$perspectiveValue.Frustum.FarPlane
            Scale = [double]$perspectiveValue.Scale
            OriginX = [double]$perspectiveValue.Origin[0]
            OriginY = [double]$perspectiveValue.Origin[1]
            OriginZ = [double]$perspectiveValue.Origin[2]
            ShiftX = [double]$perspectiveValue.ShiftXY[0]
            ShiftY = [double]$perspectiveValue.ShiftXY[1]
            ViewportOffsetX = [int]$perspectiveValue.Viewport.OffsetX
            ViewportOffsetY = [int]$perspectiveValue.Viewport.OffsetY
            ViewportWidth = [int]$perspectiveValue.Viewport.Width
            ViewportHeight = [int]$perspectiveValue.Viewport.Height
        }

        Write-Host "real-viewer resolved perspective file: $($resolvedPerspective.File)"
        Write-Host "real-viewer resolved perspective id: $($resolvedPerspective.Id)"
        Write-Host "real-viewer perspective distance/yaw/pitch/hfov: $($resolvedPerspective.Distance)/$($resolvedPerspective.Yaw)/$($resolvedPerspective.Pitch)/$($resolvedPerspective.HorizontalFov)"
    }

    Push-Location $cppRoot
    try {
        Invoke-Native "configure SGFX C++ real viewer app" {
            cmake -S . -B $buildDir -G "Visual Studio 17 2022" -A x64 `
                "-DCMAKE_PREFIX_PATH=$RamsesInstall" `
                "-Dramses-shared-lib_DIR=$RamsesInstall\lib\ramses-shared-lib-$($RamsesVersion.Substring(0, $RamsesVersion.LastIndexOf('.')))\cmake" `
                "-DSGFX_CINE_RAMSES_VERSION=$RamsesVersion"
        }

        Invoke-Native "build SGFX C++ real viewer app" {
            cmake --build $buildDir --config Release --target sgfx_cine_ramses_real_scene
        }
    }
    finally {
        Pop-Location
    }

    $sceneExe = Join-Path $buildDir "Release\sgfx_cine_ramses_real_scene.exe"
    $sceneArgs = @(
        "--profile-id", $resolvedProfileId,
        "--scene-file", $resolvedSceneFile,
        "--frames", "$Frames",
        "--zoom", "$Zoom",
        "--view-preset", $ViewPreset,
        "--readback",
        "--screenshot", $screenshotPath
    )
    if ($null -ne $resolvedPerspective) {
        $sceneArgs += @(
            "--qa-perspective-name", $resolvedPerspective.Id,
            "--qa-perspective-distance", (Format-InvariantNumber $resolvedPerspective.Distance),
            "--qa-perspective-yaw", (Format-InvariantNumber $resolvedPerspective.Yaw),
            "--qa-perspective-pitch", (Format-InvariantNumber $resolvedPerspective.Pitch),
            "--qa-perspective-roll", (Format-InvariantNumber $resolvedPerspective.Roll),
            "--qa-perspective-horizontal-fov", (Format-InvariantNumber $resolvedPerspective.HorizontalFov),
            "--qa-perspective-aspect-ratio", (Format-InvariantNumber $resolvedPerspective.AspectRatio),
            "--qa-perspective-near-plane", (Format-InvariantNumber $resolvedPerspective.NearPlane),
            "--qa-perspective-far-plane", (Format-InvariantNumber $resolvedPerspective.FarPlane),
            "--qa-perspective-aspect-from-resolution", "$($resolvedPerspective.AspectFromResolution)".ToLowerInvariant(),
            "--qa-perspective-scale", (Format-InvariantNumber $resolvedPerspective.Scale),
            "--qa-perspective-origin-x", (Format-InvariantNumber $resolvedPerspective.OriginX),
            "--qa-perspective-origin-y", (Format-InvariantNumber $resolvedPerspective.OriginY),
            "--qa-perspective-origin-z", (Format-InvariantNumber $resolvedPerspective.OriginZ),
            "--qa-perspective-shift-x", (Format-InvariantNumber $resolvedPerspective.ShiftX),
            "--qa-perspective-shift-y", (Format-InvariantNumber $resolvedPerspective.ShiftY),
            "--qa-perspective-viewport-offset-x", "$($resolvedPerspective.ViewportOffsetX)",
            "--qa-perspective-viewport-offset-y", "$($resolvedPerspective.ViewportOffsetY)",
            "--qa-perspective-viewport-width", "$($resolvedPerspective.ViewportWidth)",
            "--qa-perspective-viewport-height", "$($resolvedPerspective.ViewportHeight)",
            "--auto-frame"
        )
    }
    if ($AutoFrame -and $NoAutoFrame) {
        throw "-AutoFrame and -NoAutoFrame cannot both be set."
    }
    if ($Orbit -and $NoOrbit) {
        throw "-Orbit and -NoOrbit cannot both be set."
    }
    if ($AutoFrame -and -not $NoAutoFrame) {
        $sceneArgs += "--auto-frame"
    }
    if ($NoAutoFrame) {
        $sceneArgs += "--no-auto-frame"
    }
    if ($Orbit -and -not $NoOrbit) {
        $sceneArgs += "--orbit"
    }
    if ($NoOrbit) {
        $sceneArgs += "--no-orbit"
    }

    Write-Host ""
    Write-Host "== run SGFX C++ real viewer app =="
    $sceneOutput = & $sceneExe @sceneArgs 2>&1
    $sceneExitCode = $LASTEXITCODE
    $sceneOutput | Tee-Object -LiteralPath $outputPath
    if ($sceneExitCode -ne 0) {
        throw "run SGFX C++ real viewer app failed with exit code $sceneExitCode"
    }

    Write-Host ""
    Write-Host "SGFX real viewer profile run complete."
    Write-Host "Transcript: $transcriptPath"
    Write-Host "Output: $outputPath"
    Write-Host "Profile JSON: $profilePath"
    Write-Host "Readback PNG: $screenshotPath"
}
finally {
    Stop-Transcript | Out-Null
}
