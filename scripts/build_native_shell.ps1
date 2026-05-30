param(
    [string]$BuildDir = "build/sgfx-alpha-0.1.0",
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$sourceDir = Join-Path $repoRoot "desktop_native"
$resolvedBuildDir = Join-Path $repoRoot $BuildDir
$iconPngPath = Join-Path $repoRoot "sgfx_icon.png"
$iconIcoPath = Join-Path $sourceDir "resources\exe_ico.ico"
$imguiTemplatePath = Join-Path $repoRoot "imgui.ini"

if (-not (Test-Path $iconPngPath)) {
    $iconPngPath = Join-Path $repoRoot "exe_ico.png"
}

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

function Set-ShellIniDefaults {
    param(
        [Parameter(Mandatory = $true)]
        [string]$IniPath
    )

    $iniContent = if (Test-Path $IniPath) { Get-Content -LiteralPath $IniPath -Raw } else { "" }
    $shellSection = "[sg_preflight_native_shell]`r`ndisplay_mode=clean`r`nmusic_enabled=0`r`nsfx_enabled=1`r`n"

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

$exePath = Join-Path $resolvedBuildDir "$Configuration\sg_preflight_native_shell.exe"
if (Test-Path $exePath) {
    $buildIniPath = Join-Path $resolvedBuildDir "$Configuration\imgui.ini"
    if (Test-Path $imguiTemplatePath) {
        Copy-Item -LiteralPath $imguiTemplatePath -Destination $buildIniPath -Force
    }
    Set-ShellIniDefaults -IniPath $buildIniPath

    $latestPathFile = Join-Path (Join-Path $repoRoot "build") "latest_native_shell_path.txt"
    Set-Content -Path $latestPathFile -Value $exePath -Encoding UTF8
    Write-Host "Built native shell:" $exePath
    Write-Host "Latest native shell pointer:" $latestPathFile
} else {
    Write-Warning "Build finished, but the expected executable was not found at $exePath"
}
