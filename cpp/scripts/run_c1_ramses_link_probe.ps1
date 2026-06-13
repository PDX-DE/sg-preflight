param(
    [string]$RamsesVersion = "28.2.0",
    [string]$RamsesRoot = "C:\tmp\ramses-28.2.0",
    [string]$RamsesBuild = "C:\tmp\ramses-28.2.0-build",
    [string]$RamsesInstall = "C:\tmp\ramses-28.2.0-install",
    [string]$EvidenceRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$cppRoot = Resolve-Path -LiteralPath (Join-Path $scriptRoot "..")
$repoRoot = Resolve-Path -LiteralPath (Join-Path $cppRoot "..")

if ([string]::IsNullOrWhiteSpace($EvidenceRoot)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $EvidenceRoot = Join-Path $repoRoot "out\cpp\c1-ramses-link-$stamp"
}

New-Item -ItemType Directory -Force -Path $EvidenceRoot | Out-Null
$transcriptPath = Join-Path $EvidenceRoot "c1-ramses-link-transcript.txt"
$probeOutputPath = Join-Path $EvidenceRoot "link-probe-output.txt"

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
    Write-Host "C-1 Ramses link probe"
    Write-Host "Ramses version: $RamsesVersion"
    Write-Host "Ramses root: $RamsesRoot"
    Write-Host "Ramses build: $RamsesBuild"
    Write-Host "Ramses install: $RamsesInstall"
    Write-Host "Evidence root: $EvidenceRoot"

    if (-not (Test-Path -LiteralPath (Join-Path $RamsesRoot ".git"))) {
        Invoke-Native "clone Ramses with submodules" {
            git clone --recurse-submodules https://github.com/bmwcarit/ramses $RamsesRoot
        }
    }

    Invoke-Native "fetch Ramses tags" {
        git -C $RamsesRoot fetch --tags
    }

    Invoke-Native "checkout Ramses version" {
        git -C $RamsesRoot checkout $RamsesVersion
    }

    Invoke-Native "update Ramses submodules" {
        git -C $RamsesRoot submodule update --init --recursive
    }

    $msvcHeaderPatchPath = Join-Path $RamsesRoot "src\client\impl\logic\RenderGroupBindingElementsImpl.h"
    $msvcHeaderPatchText = Get-Content -Raw -LiteralPath $msvcHeaderPatchPath
    if ($msvcHeaderPatchText -notmatch "#include <string>") {
        $msvcHeaderPatchText = $msvcHeaderPatchText -replace "#include <vector>", "#include <string>`r`n#include <utility>`r`n#include <vector>"
        Set-Content -NoNewline -LiteralPath $msvcHeaderPatchPath -Value $msvcHeaderPatchText
        Write-Host "Applied Ramses 28.2.0 MSVC 19.44 compatibility include patch."
    }

    Invoke-Native "configure Ramses" {
        cmake -S $RamsesRoot -B $RamsesBuild -G "Visual Studio 17 2022" -A x64 `
            "-DCMAKE_INSTALL_PREFIX=$RamsesInstall" `
            "-DCMAKE_POLICY_VERSION_MINIMUM=3.5" `
            "-Dramses-sdk_BUILD_FULL_SHARED_LIB=ON" `
            "-Dramses-sdk_ENABLE_WINDOW_TYPE_WINDOWS=ON" `
            "-Dramses-sdk_WARNINGS_AS_ERRORS=OFF" `
            "-Dramses-sdk_BUILD_TESTS=OFF" `
            "-Dramses-sdk_BUILD_EXAMPLES=OFF"
    }

    Invoke-Native "build Ramses" {
        cmake --build $RamsesBuild --config Release --parallel
    }

    Invoke-Native "install Ramses" {
        cmake --install $RamsesBuild --config Release
    }

    Push-Location $cppRoot
    try {
        Invoke-Native "configure SGFX C++ link probe" {
            cmake --preset vs2022-ramses-link `
                "-DCMAKE_PREFIX_PATH=$RamsesInstall" `
                "-Dramses-shared-lib_DIR=$RamsesInstall\lib\ramses-shared-lib-$($RamsesVersion.Substring(0, $RamsesVersion.LastIndexOf('.')))\cmake" `
                "-DSGFX_CINE_RAMSES_VERSION=$RamsesVersion"
        }

        Invoke-Native "build SGFX C++ link probe" {
            cmake --build --preset vs2022-ramses-link-release
        }

        Invoke-Native "ctest SGFX C++ link probe" {
            ctest --preset vs2022-ramses-link-release
        }
    }
    finally {
        Pop-Location
    }

    $probeExe = Join-Path $cppRoot "build\vs2022-ramses-link\Release\sgfx_cine_ramses_link_probe.exe"
    Write-Host ""
    Write-Host "== run SGFX C++ link probe =="
    $probeOutput = & $probeExe 2>&1
    $probeExitCode = $LASTEXITCODE
    $probeOutput | Tee-Object -LiteralPath $probeOutputPath
    if ($probeExitCode -ne 0) {
        throw "run SGFX C++ link probe failed with exit code $probeExitCode"
    }

    Write-Host ""
    Write-Host "C-1 link probe complete."
    Write-Host "Transcript: $transcriptPath"
    Write-Host "Probe output: $probeOutputPath"
}
finally {
    Stop-Transcript | Out-Null
}
