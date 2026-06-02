param(
    [string]$RamsesVersion = "28.16.0",
    [string]$RamsesInstall = "C:\ramses-28.16.0-install",
    [switch]$SkipBuild,
    [int]$SmokeFrames = 0
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$cppRoot = Resolve-Path -LiteralPath (Join-Path $scriptRoot "..")
$buildDir = Join-Path $cppRoot "build\vs2022-ramses-28.16"
$ramsesMajorMinor = $RamsesVersion.Substring(0, $RamsesVersion.LastIndexOf("."))

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

if (-not $SkipBuild) {
    Push-Location $cppRoot
    try {
        Invoke-Native "configure SGFX C++ cinematic shell" {
            cmake -S . -B $buildDir -G "Visual Studio 17 2022" -A x64 `
                "-DCMAKE_PREFIX_PATH=$RamsesInstall" `
                "-Dramses-shared-lib_DIR=$RamsesInstall\lib\ramses-shared-lib-$ramsesMajorMinor\cmake" `
                "-DSGFX_CINE_RAMSES_VERSION=$RamsesVersion"
        }

        Invoke-Native "build SGFX C++ cinematic shell" {
            cmake --build $buildDir --config Release --target sgfx_cine_cinematic_shell
        }
    }
    finally {
        Pop-Location
    }
}

$shellExe = Join-Path $buildDir "Release\sgfx_cine_cinematic_shell.exe"
if (-not (Test-Path -LiteralPath $shellExe)) {
    throw "Expected cinematic shell executable was not found: $shellExe"
}

$shellDir = Split-Path -Parent $shellExe
$assetRoot = Join-Path $shellDir "assets"
if (-not (Test-Path -LiteralPath $assetRoot)) {
    $assetRoot = Join-Path $cppRoot "assets"
}
$fontRoot = Join-Path $assetRoot "fonts"

Write-Host ""
Write-Host "== launch SGFX cinematic shell =="
Write-Host "Executable: $shellExe"
Write-Host "Asset root: $assetRoot"
Write-Host "Font root: $fontRoot"

if ($SmokeFrames -gt 0) {
    $shellArgs = @(
        "--frames", "$SmokeFrames",
        "--no-delay",
        "--asset-root", "$assetRoot",
        "--font-root", "$fontRoot"
    )
}
else {
    $shellArgs = @(
        "--interactive",
        "--asset-root", "$assetRoot",
        "--font-root", "$fontRoot"
    )
}

Push-Location $shellDir
try {
    & $shellExe @shellArgs
    if ($LASTEXITCODE -ne 0) {
        throw "SGFX cinematic shell exited with code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
