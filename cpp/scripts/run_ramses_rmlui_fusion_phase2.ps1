param(
    [string]$RamsesVersion = "28.16.0",
    [string]$RamsesInstall = "C:\ramses-28.16.0-install",
    [string]$ProfileId = "G65",
    [string]$SceneFile = "",
    [string]$BmwModelsRoot = "",
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
    $EvidenceRoot = Join-Path $repoRoot "out\cpp\ramses-rmlui-fusion-phase2-$($ProfileId.ToLowerInvariant())-$stamp"
}

New-Item -ItemType Directory -Force -Path $EvidenceRoot | Out-Null
$transcriptPath = Join-Path $EvidenceRoot "ramses-rmlui-fusion-phase2-transcript.txt"
$outputPath = Join-Path $EvidenceRoot "ramses-rmlui-fusion-phase2-output.txt"
$profilePath = Join-Path $EvidenceRoot "ramses-rmlui-fusion-profile.json"
$resolverPath = Join-Path $EvidenceRoot "resolve-ramses-profile.py"
$readbackPath = Join-Path $EvidenceRoot "ramses-rmlui-fusion-phase2-readback.bmp"
$summaryPath = Join-Path $EvidenceRoot "ramses-rmlui-fusion-phase2-summary.json"
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
    Write-Host "SGFX Ramses -> RmlUi fusion Phase 2"
    Write-Host "Ramses version: $RamsesVersion"
    Write-Host "Ramses install: $RamsesInstall"
    Write-Host "Profile id: $ProfileId"
    Write-Host "Scene file override: $SceneFile"
    Write-Host "BMW models root override: $BmwModelsRoot"
    Write-Host "Resolution: ${Width}x${Height}"
    Write-Host "Shell frames: $Frames"
    Write-Host "Fusion frames: $FusionFrames"
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

profile_id = os.environ.get("SGFX_RESOLVE_PROFILE_ID") or (sys.argv[1] if len(sys.argv) > 1 else "")
explicit_models_root = os.environ.get("SGFX_RESOLVE_BMW_MODELS_ROOT") or (sys.argv[2] if len(sys.argv) > 2 else "")
explicit_scene_file = os.environ.get("SGFX_RESOLVE_SCENE_FILE") or (sys.argv[3] if len(sys.argv) > 3 else "")
if not profile_id:
    raise SystemExit("SGFX_RESOLVE_PROFILE_ID was not set and no profile id argument was provided")
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
        $resolveProfileScript | Set-Content -LiteralPath $resolverPath -Encoding UTF8
        $previousErrorActionPreference = $ErrorActionPreference
        $previousResolverProfileId = $env:SGFX_RESOLVE_PROFILE_ID
        $previousResolverModelsRoot = $env:SGFX_RESOLVE_BMW_MODELS_ROOT
        $previousResolverSceneFile = $env:SGFX_RESOLVE_SCENE_FILE
        $ErrorActionPreference = "Continue"
        try {
            $env:SGFX_RESOLVE_PROFILE_ID = $ProfileId
            $env:SGFX_RESOLVE_BMW_MODELS_ROOT = $BmwModelsRoot
            $env:SGFX_RESOLVE_SCENE_FILE = $SceneFile
            $profileJson = & $pythonExe @pythonPrefixArgs -B $resolverPath 2>&1
            $profileExitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
            if ($null -eq $previousResolverProfileId) { Remove-Item Env:\SGFX_RESOLVE_PROFILE_ID -ErrorAction SilentlyContinue } else { $env:SGFX_RESOLVE_PROFILE_ID = $previousResolverProfileId }
            if ($null -eq $previousResolverModelsRoot) { Remove-Item Env:\SGFX_RESOLVE_BMW_MODELS_ROOT -ErrorAction SilentlyContinue } else { $env:SGFX_RESOLVE_BMW_MODELS_ROOT = $previousResolverModelsRoot }
            if ($null -eq $previousResolverSceneFile) { Remove-Item Env:\SGFX_RESOLVE_SCENE_FILE -ErrorAction SilentlyContinue } else { $env:SGFX_RESOLVE_SCENE_FILE = $previousResolverSceneFile }
        }
        if ($profileExitCode -ne 0) {
            $profileJson | ForEach-Object { Write-Host $_ }
            throw "resolve profile scene failed with exit code $profileExitCode"
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
        if (-not (Test-Path -LiteralPath $shellExe)) {
            throw "Expected cinematic shell executable was not built: $shellExe"
        }

        Invoke-CaptureNative "run Ramses -> RmlUi fusion Phase 2 shell" $outputPath {
            & $shellExe `
                --frames $Frames `
                --skip-after-ms 500 `
                --demo-menu-focus 1 `
                --demo-enter-viewer-after-ms 850 `
                --no-delay `
                --asset-root (Join-Path $cppRoot "assets") `
                --font-root (Join-Path $cppRoot "assets\fonts") `
                --fusion-scene-file $resolvedSceneFile `
                --fusion-profile-id $resolvedProfileId `
                --fusion-frames $FusionFrames `
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
        profile = $profilePath
        resolver = $resolverPath
        shell_readback = $readbackPath
        target = "sgfx_cine_cinematic_shell"
        profile_id = $resolvedProfileId
        scene_file = $resolvedSceneFile
        fusion_phase = "Phase 2: Ramses offscreen buffer -> readPixels RGBA8 -> app GL texture -> RmlUi CallbackTexture decorator"
        resolution = "${Width}x${Height}"
        shell_frames = $Frames
        fusion_frames = $FusionFrames
        expected_visual = "Live G65 composited inside the RmlUi viewer panel with shell UI painted above it."
    }
    $summary | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
    Write-Host "SGFX Ramses -> RmlUi fusion summary: $summaryPath"
    Write-Host "SGFX Ramses -> RmlUi fusion Phase 2 evidence complete."
}
finally {
    Stop-Transcript | Out-Null
}
