param(
    [string]$BuildDir = "build/native-pda",
    [string]$BundleDir = "build/native-bundle",
    [string]$Configuration = "Release",
    [switch]$Zip
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$resolvedBuildDir = Join-Path $repoRoot $BuildDir
$resolvedBundleDir = Join-Path $repoRoot $BundleDir
$exePath = Join-Path $resolvedBuildDir "$Configuration\sg_preflight_native_shell.exe"

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
        robocopy $Source $Destination /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
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

if (-not (Test-Path $exePath)) {
    throw "Native shell executable was not found at $exePath. Build it first."
}

if (Test-Path $resolvedBundleDir) {
    Remove-Item -LiteralPath $resolvedBundleDir -Recurse -Force
}

New-Item -ItemType Directory -Path $resolvedBundleDir | Out-Null
$workspaceDir = Join-Path $resolvedBundleDir "workspace"
$pythonDir = Join-Path $resolvedBundleDir "python"
$resourcesDir = Join-Path $resolvedBundleDir "resources"
$fontsDir = Join-Path $resolvedBundleDir "fonts"

foreach ($dir in @($workspaceDir, $pythonDir, $resourcesDir, $fontsDir)) {
    New-Item -ItemType Directory -Path $dir | Out-Null
}

Copy-Tree -Source $exePath -Destination (Join-Path $resolvedBundleDir "sg_preflight_native_shell.exe")

$latestPathFile = Join-Path (Join-Path $repoRoot "build") "latest_native_shell_path.txt"
Set-Content -Path $latestPathFile -Value (Join-Path $resolvedBundleDir "sg_preflight_native_shell.exe") -Encoding UTF8

$pythonExe = (& python -c "import sys; print(sys.executable)").Trim()
if (-not $pythonExe) {
    throw "Could not resolve the current Python interpreter."
}
$pythonRoot = Split-Path -Parent $pythonExe
Copy-Tree -Source $pythonRoot -Destination $pythonDir

$workspaceItems = @(
    "sg_preflight",
    "config",
    "repositories",
    "scripts",
    "out",
    "demo",
    "pyproject.toml",
    "README.md",
    "CHANGELOG.md",
    "LICENSE",
    "NOTICE.md",
    "SECURITY.md"
)
foreach ($item in $workspaceItems) {
    $source = Join-Path $repoRoot $item
    if (Test-Path $source) {
        Copy-Tree -Source $source -Destination (Join-Path $workspaceDir $item)
    }
}

$resourceCandidates = @(
    (Join-Path $repoRoot "UnleashedRecompResources-main\UnleashedRecompResources-main"),
    (Join-Path $repoRoot "UnleashedRecompResources-main"),
    (Join-Path $repoRoot "UnleashedRecompResources"),
    (Join-Path $repoRoot "UnleashedRecomp-1.0.3\UnleashedRecomp-1.0.3\UnleashedRecompResources"),
    (Join-Path $repoRoot "Unleashed Recomp - Windows (Complete Installation) 1.0.3\resources")
)
$resourceRoot = $null
foreach ($candidate in $resourceCandidates) {
    if ((Test-Path $candidate) -and (Test-Path (Join-Path $candidate "images\common\general_window.dds")) -and (Test-Path (Join-Path $candidate "images\options_menu\options_static.dds"))) {
        $resourceRoot = $candidate
        break
    }
}
if ($resourceRoot) {
    Copy-Tree -Source $resourceRoot -Destination $resourcesDir
}

$downloadsDir = Join-Path $env:USERPROFILE "Downloads"
$fontNeedles = @(
    @{ Pattern = "*Seurat*.otf"; Target = "FOT-SeuratPro-M.otf" },
    @{ Pattern = "*NewRodin*.otf"; Target = "FOT-NewRodinPro-DB.otf" },
    @{ Pattern = "DFSoGeiStd-W7.otf"; Target = "DFSoGeiStd-W7.otf" },
    @{ Pattern = "DFHeiStd-W7.otf"; Target = "DFHeiStd-W7.otf" }
)
foreach ($font in $fontNeedles) {
    $match = Get-ChildItem -Path $downloadsDir -Recurse -File -Filter $font.Pattern -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($match) {
        Copy-Tree -Source $match.FullName -Destination (Join-Path $fontsDir $font.Target)
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

$manifest = [ordered]@{
    exe = (Join-Path $resolvedBundleDir "sg_preflight_native_shell.exe")
    python = (Join-Path $pythonDir "python.exe")
    workspace = $workspaceDir
    resources = if ($resourceRoot) { $resourcesDir } else { "" }
    fonts = $fontsDir
    built_from = $exePath
}
$manifest | ConvertTo-Json -Depth 3 | Set-Content -Path (Join-Path $resolvedBundleDir "bundle_manifest.json") -Encoding UTF8

if ($Zip) {
    $zipPath = "$resolvedBundleDir.zip"
    if (Test-Path $zipPath) {
        Remove-Item -LiteralPath $zipPath -Force
    }
    Compress-Archive -Path (Join-Path $resolvedBundleDir "*") -DestinationPath $zipPath
    Write-Host "Portable bundle archive:" $zipPath
}

Write-Host "Portable bundle:" $resolvedBundleDir
Write-Host "Bundle exe:" (Join-Path $resolvedBundleDir "sg_preflight_native_shell.exe")
