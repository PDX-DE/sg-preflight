param(
    [string]$BuildDir = "build/sergfx-alpha-0.1.0",
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$sourceDir = Join-Path $repoRoot "desktop_native"
$resolvedBuildDir = Join-Path $repoRoot $BuildDir
$iconPngPath = Join-Path $repoRoot "exe_ico.png"
$iconIcoPath = Join-Path $sourceDir "resources\exe_ico.ico"

$cmakeCommand = Get-Command cmake -ErrorAction SilentlyContinue
if (-not $cmakeCommand) {
    $fallbackCmake = "C:\Program Files\CMake\bin\cmake.exe"
    if (Test-Path $fallbackCmake) {
        $cmakeCommand = Get-Item $fallbackCmake
    }
}

if (-not $cmakeCommand) {
    throw "CMake is required to build the native shell. Install CMake 3.24+ and Visual Studio C++ build tools first."
}

if (Test-Path $iconPngPath) {
    @"
from pathlib import Path
from PIL import Image

png_path = Path(r"$iconPngPath")
ico_path = Path(r"$iconIcoPath")
image = Image.open(png_path).convert("RGBA")
image.save(
    ico_path,
    format="ICO",
    sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
)
"@ | python -
}

$cmakePath = if ($cmakeCommand.PSObject.Properties.Name -contains "Source") {
    $cmakeCommand.Source
} else {
    $cmakeCommand.FullName
}

& $cmakePath -S $sourceDir -B $resolvedBuildDir -A x64
if ($LASTEXITCODE -ne 0) {
    throw "CMake configure failed for the native shell."
}

& $cmakePath --build $resolvedBuildDir --config $Configuration
if ($LASTEXITCODE -ne 0) {
    throw "CMake build failed for the native shell."
}

$exePath = Join-Path $resolvedBuildDir "$Configuration\sg_preflight_native_shell.exe"
if (Test-Path $exePath) {
    $latestPathFile = Join-Path (Join-Path $repoRoot "build") "latest_native_shell_path.txt"
    Set-Content -Path $latestPathFile -Value $exePath -Encoding UTF8
    Write-Host "Built native shell:" $exePath
    Write-Host "Latest native shell pointer:" $latestPathFile
} else {
    Write-Warning "Build finished, but the expected executable was not found at $exePath"
}
