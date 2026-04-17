param(
    [string]$BuildDir = "build/native",
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$sourceDir = Join-Path $repoRoot "desktop_native"
$resolvedBuildDir = Join-Path $repoRoot $BuildDir

if (-not (Get-Command cmake -ErrorAction SilentlyContinue)) {
    throw "CMake is required to build the native shell. Install CMake 3.24+ and Visual Studio C++ build tools first."
}

cmake -S $sourceDir -B $resolvedBuildDir -A x64
cmake --build $resolvedBuildDir --config $Configuration

$exePath = Join-Path $resolvedBuildDir "$Configuration\sg_preflight_native_shell.exe"
if (Test-Path $exePath) {
    Write-Host "Built native shell:" $exePath
} else {
    Write-Warning "Build finished, but the expected executable was not found at $exePath"
}
