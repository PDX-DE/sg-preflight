param(
    [string]$RamsesVersion = "28.16.0",
    [string]$RamsesInstall = "C:\ramses-28.16.0-install",
    [string]$ProfileId = "G65",
    [string]$SceneFile = "",
    [string]$BmwModelsRoot = "",
    [int]$Width = 1280,
    [int]$Height = 720,
    [int]$Frames = 120,
    [string]$EvidenceRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$cppRoot = Resolve-Path -LiteralPath (Join-Path $scriptRoot "..")
$repoRoot = Resolve-Path -LiteralPath (Join-Path $cppRoot "..")

if ([string]::IsNullOrWhiteSpace($EvidenceRoot)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $EvidenceRoot = Join-Path $repoRoot "out\cpp\ramses-shell-fusion-phase1-$($ProfileId.ToLowerInvariant())-$stamp"
}

New-Item -ItemType Directory -Force -Path $EvidenceRoot | Out-Null
$transcriptPath = Join-Path $EvidenceRoot "ramses-shell-fusion-phase1-transcript.txt"
$outputPath = Join-Path $EvidenceRoot "ramses-shell-fusion-phase1-output.txt"
$profilePath = Join-Path $EvidenceRoot "ramses-shell-fusion-profile.json"
$readbackPath = Join-Path $EvidenceRoot "ramses-shell-fusion-phase1-readback.bmp"
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
    $lines = & $Body 2>&1
    $exitCode = $LASTEXITCODE
    $lines | Tee-Object -FilePath $OutputPath
    if ($exitCode -ne 0) {
        throw "$Label failed with exit code $exitCode"
    }
}

Start-Transcript -LiteralPath $transcriptPath | Out-Null
try {
    Write-Host "SGFX Ramses shell fusion Phase 1"
    Write-Host "Ramses version: $RamsesVersion"
    Write-Host "Ramses install: $RamsesInstall"
    Write-Host "Profile id: $ProfileId"
    Write-Host "Scene file override: $SceneFile"
    Write-Host "BMW models root override: $BmwModelsRoot"
    Write-Host "Resolution: ${Width}x${Height}"
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
    "candidate_bmw_profile_ids": candidate_ids,
    "bmw_profile_id": resolved_bmw_profile_id,
    "bmw_models_root": resolved_models_root,
    "scene_file": str(scene_file),
    "attempted_scene_files": attempted,
}, sort_keys=True))
'@

        Write-Host "fusion profile resolver python: $pythonExe $($pythonPrefixArgs -join ' ')"
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
    Write-Host "fusion resolved profile id: $resolvedProfileId"
    Write-Host "fusion resolved BMW profile id: $($profile.bmw_profile_id)"
    Write-Host "fusion resolved BMW models root: $($profile.bmw_models_root)"
    Write-Host "fusion resolved scene file: $resolvedSceneFile"
    Write-Host "fusion profile evidence JSON: $profilePath"

    Push-Location $cppRoot
    try {
        Invoke-Native "configure SGFX C++ Ramses shell fusion probe" {
            cmake -S . -B $buildDir -G "Visual Studio 17 2022" -A x64 `
                "-DCMAKE_PREFIX_PATH=$RamsesInstall" `
                "-Dramses-shared-lib_DIR=$RamsesInstall\lib\ramses-shared-lib-$($RamsesVersion.Substring(0, $RamsesVersion.LastIndexOf('.')))\cmake" `
                "-DSGFX_CINE_RAMSES_VERSION=$RamsesVersion"
        }

        Invoke-Native "build SGFX C++ Ramses shell fusion probe" {
            cmake --build $buildDir --config Release --target sgfx_cine_ramses_shell_fusion_probe
        }
    }
    finally {
        Pop-Location
    }

    $fusionExe = Join-Path $buildDir "Release\sgfx_cine_ramses_shell_fusion_probe.exe"
    if (-not (Test-Path -LiteralPath $fusionExe)) {
        throw "Expected fusion probe executable was not built: $fusionExe"
    }

    Invoke-CaptureNative "run Ramses shell fusion Phase 1 probe" $outputPath {
        & $fusionExe `
            --profile-id $resolvedProfileId `
            --scene-file $resolvedSceneFile `
            --width $Width `
            --height $Height `
            --frames $Frames `
            --screenshot $readbackPath
    }

    $summary = [ordered]@{
        evidence_root = $EvidenceRoot
        output = $outputPath
        profile = $profilePath
        shell_readback = $readbackPath
        target = "sgfx_cine_ramses_shell_fusion_probe"
        profile_id = $resolvedProfileId
        scene_file = $resolvedSceneFile
        fusion_phase = "Phase 1: Ramses offscreen buffer -> readPixels RGBA8 -> SDL OpenGL 3.3 texture -> shell GL quad"
        resolution = "${Width}x${Height}"
        frames = $Frames
    }
    $summaryPath = Join-Path $EvidenceRoot "ramses-shell-fusion-phase1-summary.json"
    $summary | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
    Write-Host "SGFX Ramses shell fusion summary: $summaryPath"
    Write-Host "SGFX Ramses shell fusion Phase 1 evidence complete."
}
finally {
    Stop-Transcript | Out-Null
}
