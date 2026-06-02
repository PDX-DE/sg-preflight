param(
    [string]$RenderDocCmd = "",
    [string]$GameExe = "",
    [string]$WorkingDirectory = "",
    [string]$CaptureRoot = "",
    [int]$ThumbnailMaxSize = 1600,
    [switch]$DryRun,
    [switch]$ProcessOnly,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$GameArgs = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$cppRoot = Resolve-Path -LiteralPath (Join-Path $scriptRoot "..")
$repoRoot = Resolve-Path -LiteralPath (Join-Path $cppRoot "..")

function Resolve-FirstExistingPath {
    param([string[]]$Candidates)

    foreach ($candidate in $Candidates) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return ""
}

function Resolve-RenderDoc {
    if (-not [string]::IsNullOrWhiteSpace($RenderDocCmd)) {
        return Resolve-FirstExistingPath -Candidates @($RenderDocCmd)
    }

    $command = Get-Command renderdoccmd.exe -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    return ""
}

function Resolve-Game {
    if (-not [string]::IsNullOrWhiteSpace($GameExe)) {
        return Resolve-FirstExistingPath -Candidates @($GameExe)
    }

    return ""
}

function Format-CommandLine {
    param([string]$Exe, [string[]]$CommandArgs)

    $quoted = @("`"$Exe`"")
    foreach ($arg in $CommandArgs) {
        if ($arg -match '\s') {
            $quoted += "`"$arg`""
        }
        else {
            $quoted += $arg
        }
    }
    return ($quoted -join " ")
}

if ([string]::IsNullOrWhiteSpace($CaptureRoot)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $CaptureRoot = Join-Path $repoRoot "out\reference-captures\renderdoc-$stamp"
}

$CaptureRoot = [System.IO.Path]::GetFullPath($CaptureRoot)
$renderDoc = Resolve-RenderDoc
$game = Resolve-Game

if ([string]::IsNullOrWhiteSpace($renderDoc)) {
    throw "renderdoccmd.exe not found. Pass -RenderDocCmd or install RenderDoc under sgfx-rnd-tools."
}

if (-not $ProcessOnly -and [string]::IsNullOrWhiteSpace($game)) {
    throw "Reference application not found. Pass -GameExe with the reference application path."
}

if ([string]::IsNullOrWhiteSpace($WorkingDirectory) -and -not [string]::IsNullOrWhiteSpace($game)) {
    $WorkingDirectory = Split-Path -Parent $game
}

New-Item -ItemType Directory -Force -Path $CaptureRoot | Out-Null
$processedRoot = Join-Path $CaptureRoot "processed"
New-Item -ItemType Directory -Force -Path $processedRoot | Out-Null
$summaryPath = Join-Path $CaptureRoot "renderdoc-reference-summary.json"
$captureTemplate = Join-Path $CaptureRoot "sgfx-reference"

Write-Host "SGFX RenderDoc reference capture helper"
Write-Host "RenderDoc cmd: $renderDoc"
Write-Host "Reference application: $game"
Write-Host "Working dir: $WorkingDirectory"
Write-Host "Capture root: $CaptureRoot"
Write-Host ""
Write-Host "Four-key flow:"
Write-Host "1. Run this script without -DryRun."
Write-Host "2. At the title screen, press F12 once."
Write-Host "3. At the world map, press F12 once."
Write-Host "4. Quit the game; this script extracts thumbnails into the processed folder."
Write-Host ""
Write-Host "Clean-room line: captures are study evidence only; do not ship ripped assets; do not use Ghidra."

if (-not $ProcessOnly) {
    $captureArgs = @(
        "capture",
        "--wait-for-exit",
        "--opt-hook-children",
        "--capture-file", $captureTemplate,
        "--working-dir", $WorkingDirectory,
        $game
    ) + $GameArgs

    Write-Host ""
    Write-Host "RenderDoc launch:"
    Write-Host (Format-CommandLine -Exe $renderDoc -CommandArgs $captureArgs)

    if (-not $DryRun) {
        & $renderDoc @captureArgs
        if ($LASTEXITCODE -ne 0) {
            throw "RenderDoc capture launch failed with exit code $LASTEXITCODE"
        }
    }
}

$captures = @(Get-ChildItem -LiteralPath $CaptureRoot -Filter "*.rdc" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime)
$thumbs = @()
foreach ($capture in $captures) {
    $thumbPath = Join-Path $processedRoot "$($capture.BaseName)-thumb.png"
    $thumbArgs = @(
        "thumb",
        "--out", $thumbPath,
        "--format", "png",
        "--max-size", "$ThumbnailMaxSize",
        $capture.FullName
    )

    Write-Host ""
    Write-Host "Thumbnail extract:"
    Write-Host (Format-CommandLine -Exe $renderDoc -CommandArgs $thumbArgs)
    if (-not $DryRun) {
        & $renderDoc @thumbArgs
        if ($LASTEXITCODE -ne 0) {
            throw "RenderDoc thumbnail extraction failed for $($capture.FullName) with exit code $LASTEXITCODE"
        }
    }
    $thumbs += $thumbPath
}

$warning = ""
if (-not $DryRun -and -not $ProcessOnly -and $captures.Count -eq 0) {
    $warning = "No .rdc captures found under $CaptureRoot. Launch worked, but F12 captures were not saved there."
    Write-Warning $warning
}

$summary = [ordered]@{
    capture_root = $CaptureRoot
    processed_root = $processedRoot
    renderdoc_cmd = $renderDoc
    game_exe = $game
    working_directory = $WorkingDirectory
    dry_run = [bool]$DryRun
    process_only = [bool]$ProcessOnly
    capture_count = $captures.Count
    captures = @($captures | ForEach-Object { $_.FullName })
    thumbnails = $thumbs
    warning = $warning
    clean_room = "RenderDoc captures are output-observation study evidence only; no ripped assets in SGFX build; no Ghidra."
}
$summary | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $summaryPath -Encoding UTF8

Write-Host ""
Write-Host "RenderDoc reference summary: $summaryPath"
if ($captures.Count -eq 0) {
    Write-Host "No captures processed yet."
}
else {
    Write-Host "Processed $($captures.Count) RenderDoc capture(s)."
}
