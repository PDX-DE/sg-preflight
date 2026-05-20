param(
    [string]$BuildDir = "",
    [string]$BundleDir = "build/sgfx-alpha-0.1.0-bundle",
    [string]$Configuration = "Release",
    [switch]$Zip,
    [switch]$IncludeRepoMirror,
    [switch]$IncludeEvidence,
    [switch]$IncludeReferenceResources,
    [switch]$IncludeFonts,
    [switch]$IncludeMusic,
    [string]$ReferenceResourcesRoot = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$resolvedBundleDir = Join-Path $repoRoot $BundleDir
$latestPathFile = Join-Path (Join-Path $repoRoot "build") "latest_native_shell_path.txt"
$latestBundlePathFile = Join-Path (Join-Path $repoRoot "build") "latest_native_shell_bundle_path.txt"

if ($BuildDir) {
    $resolvedBuildDir = Join-Path $repoRoot $BuildDir
    $exePath = Join-Path $resolvedBuildDir "$Configuration\sg_preflight_native_shell.exe"
} elseif (Test-Path $latestPathFile) {
    $exePath = (Get-Content $latestPathFile -Raw).Trim()
    $resolvedBuildDir = Split-Path -Parent $exePath
} else {
    $resolvedBuildDir = Join-Path $repoRoot "build/sgfx-alpha-0.1.0"
    $exePath = Join-Path $resolvedBuildDir "$Configuration\sg_preflight_native_shell.exe"
}

function Copy-Tree {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Source,
        [Parameter(Mandatory = $true)]
        [string]$Destination
    )

    if (-not (Test-Path $Source)) {
        return
    }

    $item = Get-Item -LiteralPath $Source
    if ($item.PSIsContainer) {
        New-Item -ItemType Directory -Path $Destination -Force | Out-Null
        $robocopyArgs = @($Source, $Destination, "/E", "/R:1", "/W:1", "/NFL", "/NDL", "/NJH", "/NJS", "/NC", "/NS", "/NP", "/XD", ".svn", ".git")
        robocopy @robocopyArgs | Out-Null
        if ($LASTEXITCODE -ge 8) {
            throw "robocopy failed while copying '$Source' to '$Destination' (exit $LASTEXITCODE)."
        }
        return
    }

    $parent = Split-Path -Parent $Destination
    if ($parent) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    Copy-Item -LiteralPath $Source -Destination $Destination -Force
}

function Remove-Tree {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path $Path)) {
        return
    }

    $emptyDir = Join-Path ([System.IO.Path]::GetTempPath()) ("sg-preflight-empty-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $emptyDir | Out-Null
    try {
        robocopy $emptyDir $Path /MIR /R:1 /W:1 /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
        if ($LASTEXITCODE -ge 8) {
            throw "robocopy failed while clearing '$Path' (exit $LASTEXITCODE)."
        }
    }
    finally {
        if (Test-Path $emptyDir) {
            Remove-Item -LiteralPath $emptyDir -Recurse -Force
        }
    }

    if (-not (Test-Path $Path)) {
        return
    }
}

if (-not (Test-Path $exePath)) {
    throw "Native shell executable was not found at $exePath. Build it first."
}

if (Test-Path $resolvedBundleDir) {
    Remove-Tree -Path $resolvedBundleDir
}

New-Item -ItemType Directory -Path $resolvedBundleDir -Force | Out-Null
$workspaceDir = Join-Path $resolvedBundleDir "workspace"
$pythonDir = Join-Path $resolvedBundleDir "python"
$resourcesDir = Join-Path $resolvedBundleDir "resources"
$fontsDir = Join-Path $resolvedBundleDir "fonts"

foreach ($dir in @($workspaceDir, $pythonDir, $resourcesDir, $fontsDir)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
}

Copy-Tree -Source $exePath -Destination (Join-Path $resolvedBundleDir "sg_preflight_native_shell.exe")

$sgfxExeDir = Join-Path $repoRoot "dist\sgfx-preflight"
$sgfxExePath = Join-Path $sgfxExeDir "sgfx-preflight.exe"
if (Test-Path $sgfxExePath) {
    Copy-Tree -Source $sgfxExeDir -Destination (Join-Path $resolvedBundleDir "dist\sgfx-preflight")
}

$bundleAssetItems = @(
    @{ Source = "sgfx_icon.png"; Destination = "sgfx_icon.png" },
    @{ Source = "framework_sgfx_logo.png"; Destination = "framework_sgfx_logo.png" },
    @{ Source = "logo_sgfx.png"; Destination = "logo_sgfx.png" },
    @{ Source = "exe_ico.png"; Destination = "exe_ico.png" },
    @{ Source = "desktop_native\resources\exe_ico.ico"; Destination = "exe_ico.ico" },
    @{ Source = "desktop_native\resources\debug_icon.ico"; Destination = "debug_icon.ico" }
)
foreach ($asset in $bundleAssetItems) {
    $source = Join-Path $repoRoot $asset.Source
    if (Test-Path $source) {
        Copy-Tree -Source $source -Destination (Join-Path $resolvedBundleDir $asset.Destination)
    }
}

$directxItems = @(
    @{ Source = (Join-Path $repoRoot "D3D12"); Destination = (Join-Path $resolvedBundleDir "D3D12") },
    @{ Source = (Join-Path $repoRoot "dxcompiler.dll"); Destination = (Join-Path $resolvedBundleDir "dxcompiler.dll") },
    @{ Source = (Join-Path $repoRoot "dxil.dll"); Destination = (Join-Path $resolvedBundleDir "dxil.dll") }
)
foreach ($item in $directxItems) {
    if (Test-Path $item.Source) {
        Copy-Tree -Source $item.Source -Destination $item.Destination
    }
}

Set-Content -Path $latestBundlePathFile -Value (Join-Path $resolvedBundleDir "sg_preflight_native_shell.exe") -Encoding UTF8

$pythonInfoJson = (& python -c "import json, sys; print(json.dumps({'executable': sys.executable, 'prefix': sys.prefix, 'base_prefix': sys.base_prefix}))").Trim()
if (-not $pythonInfoJson) {
    throw "Could not resolve the current Python interpreter."
}
$pythonInfo = $pythonInfoJson | ConvertFrom-Json
$pythonExe = [string]$pythonInfo.executable
$pythonSourceRoot = if ([string]$pythonInfo.prefix -ne [string]$pythonInfo.base_prefix) {
    [string]$pythonInfo.prefix
} else {
    Split-Path -Parent $pythonExe
}
$pythonExeRelative = if (Test-Path (Join-Path $pythonSourceRoot "Scripts\python.exe")) {
    "Scripts\python.exe"
} else {
    Split-Path -Leaf $pythonExe
}
Copy-Tree -Source $pythonSourceRoot -Destination $pythonDir
$bundledPythonExe = Join-Path $pythonDir $pythonExeRelative

$workspaceItems = @(
    "sg_preflight",
    "config",
    "scripts",
    "demo",
    "pyproject.toml",
    "README.md",
    "LICENSE",
    "NOTICE.md",
    "SECURITY.md",
    "debug_icon.png",
    "sgfx_icon.png",
    "exe_ico.png",
    "framework_sgfx_logo.png",
    "logo_sgfx.png",
    "desktop_native\resources\debug_icon.ico",
    "desktop_native\resources\exe_ico.ico",
    "kb_key_F1.png",
    "kb_key_F2.png",
    "kb_key_F3.png",
    "kb_key_F4.png"
)
if ($IncludeRepoMirror) {
    $workspaceItems += "repositories"
}
if ($IncludeEvidence) {
    $workspaceItems += "out"
}
foreach ($item in $workspaceItems) {
    $source = Join-Path $repoRoot $item
    if (Test-Path $source) {
        Copy-Tree -Source $source -Destination (Join-Path $workspaceDir $item)
    }
}

$musicEnabledValue = if ($IncludeMusic) { "1" } else { "0" }

function Set-ShellIniDefaults {
    param(
        [Parameter(Mandatory = $true)]
        [string]$IniPath,
        [Parameter(Mandatory = $true)]
        [string]$MusicEnabledValue
    )

    $iniContent = if (Test-Path $IniPath) { Get-Content -LiteralPath $IniPath -Raw } else { "" }
    $shellSection = "[sg_preflight_native_shell]`r`ndisplay_mode=clean`r`nmusic_enabled=$MusicEnabledValue`r`nsfx_enabled=1`r`n"

    if ($iniContent -match "(?ms)^\[sg_preflight_native_shell\].*?(?=^\[|\z)") {
        $iniContent = [regex]::Replace(
            $iniContent,
            "(?ms)^\[sg_preflight_native_shell\].*?(?=^\[|\z)",
            $shellSection,
            1
        )
    } elseif ([string]::IsNullOrWhiteSpace($iniContent)) {
        $iniContent = $shellSection
    } else {
        $iniContent = $iniContent.TrimEnd() + "`r`n`r`n" + $shellSection
    }

    Set-Content -Path $IniPath -Value $iniContent -Encoding UTF8
}

$bundleIniTemplatePath = Join-Path $repoRoot "imgui.ini"
$bundleIniPath = Join-Path $resolvedBundleDir "imgui.ini"
if (Test-Path $bundleIniTemplatePath) {
    Copy-Tree -Source $bundleIniTemplatePath -Destination $bundleIniPath
}
Set-ShellIniDefaults -IniPath $bundleIniPath -MusicEnabledValue $musicEnabledValue

$resourceCandidates = @()
if ($ReferenceResourcesRoot) {
    $resourceCandidates += $ReferenceResourcesRoot
}
$genericReferenceResources = Join-Path $repoRoot "resources\reference-ui"
if (Test-Path $genericReferenceResources) {
    $resourceCandidates += $genericReferenceResources
}
$resourceRoot = $null
$sgfxAssetRoot = Join-Path $repoRoot "desktop_native\assets"
if (Test-Path (Join-Path $sgfxAssetRoot "images\common\raw\general_window.png")) {
    Copy-Tree -Source $sgfxAssetRoot -Destination $resourcesDir
}
if ($IncludeReferenceResources) {
    foreach ($candidate in $resourceCandidates) {
        if ((Test-Path $candidate) -and (Test-Path (Join-Path $candidate "images\common\raw\general_window.png")) -and (Test-Path (Join-Path $candidate "images\common\raw\options_static.png"))) {
            $resourceRoot = $candidate
            break
        }
    }
}
if ($resourceRoot) {
    Copy-Tree -Source $resourceRoot -Destination $resourcesDir
}

$downloadsDir = Join-Path $env:USERPROFILE "Downloads"
$fontNeedles = @(
    @{ Pattern = "*NewRodin*.otf"; Target = "FOT-NewRodinPro-DB.otf" },
    @{ Pattern = "DFSoGeiStd-W7.otf"; Target = "DFSoGeiStd-W7.otf" },
    @{ Pattern = "DFHeiStd-W7.otf"; Target = "DFHeiStd-W7.otf" }
)
foreach ($font in $fontNeedles) {
    if ($IncludeFonts) {
        $match = Get-ChildItem -Path $downloadsDir -Recurse -File -Filter $font.Pattern -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($match) {
            Copy-Tree -Source $match.FullName -Destination (Join-Path $fontsDir $font.Target)
        }
    }
}

$launchPs1 = @'
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

$bundleRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$exe = Join-Path $bundleRoot "sg_preflight_native_shell.exe"
& $exe @Args
'@
Set-Content -Path (Join-Path $resolvedBundleDir "run_native_shell.ps1") -Value $launchPs1 -Encoding UTF8

$launchBat = @'
@echo off
set SCRIPT_DIR=%~dp0
"%SCRIPT_DIR%sg_preflight_native_shell.exe" %*
'@
Set-Content -Path (Join-Path $resolvedBundleDir "run_native_shell.bat") -Value $launchBat -Encoding ASCII

function New-SgfxShortcut {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$Arguments
    )

    $target = Join-Path $resolvedBundleDir "dist\sgfx-preflight\sgfx-preflight.exe"
    if (-not (Test-Path $target)) {
        return
    }

    $shortcutPath = Join-Path $resolvedBundleDir $Name
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $target
    $shortcut.Arguments = $Arguments
    $shortcut.WorkingDirectory = $resolvedBundleDir
    $shortcut.IconLocation = $target
    $shortcut.Save()
}

New-SgfxShortcut -Name "SGFX Preflight - Clean Mode.lnk" -Arguments "dashboard run --ui-mode clean"
New-SgfxShortcut -Name "SGFX Preflight - Grafiks Mode.lnk" -Arguments "dashboard run --ui-mode grafiks"

$manifest = [ordered]@{
    exe = (Join-Path $resolvedBundleDir "sg_preflight_native_shell.exe")
    sgfx_preflight_exe = if (Test-Path (Join-Path $resolvedBundleDir "dist\sgfx-preflight\sgfx-preflight.exe")) { (Join-Path $resolvedBundleDir "dist\sgfx-preflight\sgfx-preflight.exe") } else { "" }
    python = $bundledPythonExe
    workspace = $workspaceDir
    resources = if ((Test-Path $resourcesDir) -and ((Get-ChildItem -LiteralPath $resourcesDir -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1))) { $resourcesDir } else { "" }
    fonts = if ($IncludeFonts) { $fontsDir } else { "" }
    d3d12 = if (Test-Path (Join-Path $resolvedBundleDir "D3D12")) { (Join-Path $resolvedBundleDir "D3D12") } else { "" }
    dxcompiler = if (Test-Path (Join-Path $resolvedBundleDir "dxcompiler.dll")) { (Join-Path $resolvedBundleDir "dxcompiler.dll") } else { "" }
    dxil = if (Test-Path (Join-Path $resolvedBundleDir "dxil.dll")) { (Join-Path $resolvedBundleDir "dxil.dll") } else { "" }
    built_from = $exePath
    include_repo_mirror = [bool]$IncludeRepoMirror
    include_evidence = [bool]$IncludeEvidence
    include_reference_resources = [bool]$IncludeReferenceResources
    include_fonts = [bool]$IncludeFonts
    include_music = [bool]$IncludeMusic
    warnings = @(
        if (-not $IncludeRepoMirror) { "Repo mirror omitted by default. Live SG slice discovery will stay empty unless an external mirror is provided." }
        if (-not $IncludeEvidence) { "Generated evidence was omitted by default." }
        if (-not $IncludeReferenceResources) { "Optional reference UI resources were omitted by default." }
        if (-not $IncludeFonts) { "Optional shell fonts were omitted by default; runtime will fall back to bundled/system fonts when needed." }
        if (-not $IncludeMusic) { "Optional audio tracks were omitted by default and bundle-root imgui.ini was set to music_enabled=0." }
    ) | Where-Object { $_ }
}
$manifest | ConvertTo-Json -Depth 3 | Set-Content -Path (Join-Path $resolvedBundleDir "bundle_manifest.json") -Encoding UTF8

if ($Zip) {
    $zipPath = "$resolvedBundleDir.zip"
    if (Test-Path $zipPath) {
        Remove-Item -LiteralPath $zipPath -Force
    }
    @"
from pathlib import Path
import os
import zipfile

bundle_dir = Path(r"$resolvedBundleDir")
zip_path = Path(r"$zipPath")

def nt_long_path(path: Path) -> str:
    resolved = str(path.resolve())
    if os.name == "nt" and not resolved.startswith("\\\\?\\"):
        return "\\\\?\\" + resolved
    return resolved

with zipfile.ZipFile(nt_long_path(zip_path), "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
    for file_path in bundle_dir.rglob("*"):
        if file_path.is_file():
            archive.write(nt_long_path(file_path), file_path.relative_to(bundle_dir).as_posix())
"@ | python -
    Write-Host "Portable bundle archive:" $zipPath
}

Write-Host "Portable bundle:" $resolvedBundleDir
Write-Host "Bundle exe:" (Join-Path $resolvedBundleDir "sg_preflight_native_shell.exe")
Write-Host "Latest bundle pointer:" $latestBundlePathFile
