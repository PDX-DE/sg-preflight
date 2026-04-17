param(
    [string]$BuildDir = "build/native",
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$sourceDir = Join-Path $repoRoot "desktop_native"
$resolvedBuildDir = Join-Path $repoRoot $BuildDir

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
    Write-Host "Built native shell:" $exePath
} else {
    Write-Warning "Build finished, but the expected executable was not found at $exePath"
}
