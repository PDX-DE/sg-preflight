[CmdletBinding()]
param(
    [switch]$ReferenceReady,
    [string]$PreviewScene = $env:SGFX_CINE_PREVIEW_SCENE
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$OutputRoot = Join-Path $RepoRoot "out\control-center-c0"
$JsonPath = Join-Path $OutputRoot "control-center-c0-verification.json"
$MarkdownPath = Join-Path $OutputRoot "control-center-c0-verification.md"
$Python = (Resolve-Path (Join-Path $RepoRoot "..\sg-preflight\.venv\Scripts\python.exe")).Path
$Bundle = Join-Path $RepoRoot "build\b\sgfx-preflight"
$CacheRoot = Join-Path $RepoRoot "out\preview-cache"
$ArtifactJson = "out/control-center-c0/control-center-c0-verification.json"
$ArtifactMarkdown = "out/control-center-c0/control-center-c0-verification.md"
$script:Gates = [System.Collections.Generic.List[object]]::new()

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
Set-Location $RepoRoot

function Get-TrackedFingerprint {
    param([string]$Root)

    $tracked = @(& git -C $Root ls-files)
    if ($LASTEXITCODE -ne 0) {
        throw "Tracked source inventory could not be read."
    }
    $records = [System.Collections.Generic.List[string]]::new()
    $totalBytes = [int64]0
    foreach ($relative in ($tracked | Sort-Object)) {
        $path = Join-Path $Root $relative
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "A tracked source file is unavailable."
        }
        $item = Get-Item -LiteralPath $path
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
        $totalBytes += $item.Length
        $records.Add("$relative`t$($item.Length)`t$($item.LastWriteTimeUtc.Ticks)`t$hash")
    }
    $bytes = [Text.Encoding]::UTF8.GetBytes(($records -join "`n"))
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        $digest = ([BitConverter]::ToString($algorithm.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $algorithm.Dispose()
    }
    return [ordered]@{
        tracked_file_count = $tracked.Count
        tracked_bytes = $totalBytes
        sha256 = $digest
    }
}

function Add-Gate {
    param(
        [string]$Id,
        [string]$Command,
        [string]$State,
        [string]$Reason,
        [string]$Artifact,
        [string]$Sha256 = ""
    )

    $script:Gates.Add([ordered]@{
        id = $Id
        command = $Command
        state = $State
        reason = $Reason
        artifact = $Artifact
        sha256 = $Sha256
    })
}

function Assert-LastExitCode {
    param([string]$Gate)

    if ($LASTEXITCODE -ne 0) {
        throw "$Gate failed with exit code $LASTEXITCODE."
    }
}

$commit = (& git -C $RepoRoot rev-parse HEAD).Trim().ToLowerInvariant()
Assert-LastExitCode "source-commit"
$status = (& git -C $RepoRoot status --porcelain --untracked-files=all) -join "`n"
Assert-LastExitCode "source-status"
if ($status.Trim()) {
    throw "The source worktree must be clean before Control Center verification."
}
$before = Get-TrackedFingerprint $RepoRoot

& $Python -B -m unittest tests.test_bundle_manifest tests.test_qt_quick_benchmark tests.test_qt_quick_preview -v
Assert-LastExitCode "focused-tests"
Add-Gate "focused-tests" "..\sg-preflight\.venv\Scripts\python.exe -B -m unittest tests.test_bundle_manifest tests.test_qt_quick_benchmark tests.test_qt_quick_preview -v" "PASS" "" $ArtifactJson

& $Python -B -m unittest tests.test_qml_format -v
Assert-LastExitCode "qml-format"
Add-Gate "qml-format" "..\sg-preflight\.venv\Scripts\python.exe -B -m unittest tests.test_qml_format -v" "PASS" "" $ArtifactJson

& $Python -B scripts\build_sgfx_exe.py --staged-only
Assert-LastExitCode "staged-bundle"
$ManifestPath = Join-Path $Bundle "bundle-manifest.json"
$ExecutablePath = Join-Path $Bundle "sgfx-preflight.exe"
if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf) -or -not (Test-Path -LiteralPath $ExecutablePath -PathType Leaf)) {
    throw "The staged Control Center bundle is incomplete."
}
$manifest = Get-Content -Raw -LiteralPath $ManifestPath | ConvertFrom-Json
if (
    $manifest.source_commit -ne $commit -or
    $manifest.ui_capability_count -ne 8 -or
    $manifest.surface_descriptor_count -ne 19 -or
    $manifest.qa_hub_schema_version -ne 1 -or
    -not $manifest.control_center_qml_present -or
    -not $manifest.product_fonts_licensed -or
    $manifest.ramses_preview_helper -notin @("included", "unavailable")
) {
    throw "The staged Control Center manifest does not satisfy the C0 contract."
}
$bundleSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $ExecutablePath).Hash.ToLowerInvariant()
Add-Gate "staged-bundle" "..\sg-preflight\.venv\Scripts\python.exe -B scripts\build_sgfx_exe.py --staged-only" "PASS" "" "build/b/sgfx-preflight/sgfx-preflight.exe" $bundleSha256

& $Python -B -m unittest tests.test_qt_quick_host.TestQtQuickShell.test_control_center_viewports_accessibility_fonts_and_focus_order -v
Assert-LastExitCode "headless-viewports"
Add-Gate "headless-viewports" "..\sg-preflight\.venv\Scripts\python.exe -B -m unittest tests.test_qt_quick_host.TestQtQuickShell.test_control_center_viewports_accessibility_fonts_and_focus_order -v # 1280 x 720; 1024 x 640" "PASS" "" $ArtifactJson

$helper = Join-Path $RepoRoot "cpp\bin\sgfx_cine_ramses_preview_cli.exe"
if ($PreviewScene -and (Test-Path -LiteralPath $PreviewScene -PathType Leaf) -and (Test-Path -LiteralPath $helper -PathType Leaf)) {
    $sceneBefore = (Get-FileHash -Algorithm SHA256 -LiteralPath $PreviewScene).Hash.ToLowerInvariant()
    $env:SGFX_CINE_PREVIEW_SCENE = (Resolve-Path -LiteralPath $PreviewScene).Path
    try {
        & $Python -B -m unittest tests.test_qt_quick_preview.TestNativePreviewHelper.test_local_compatible_scene_round_trips_through_the_coordinator_when_available -v
        Assert-LastExitCode "compatible-preview"
    }
    finally {
        Remove-Item Env:SGFX_CINE_PREVIEW_SCENE -ErrorAction SilentlyContinue
    }
    $sceneAfter = (Get-FileHash -Algorithm SHA256 -LiteralPath $PreviewScene).Hash.ToLowerInvariant()
    if ($sceneBefore -ne $sceneAfter) {
        throw "The compatible preview source changed during verification."
    }
    $preview = [ordered]@{ state = "PASS"; reason = ""; source_sha256 = $sceneBefore }
    Add-Gate "compatible-preview" "..\sg-preflight\.venv\Scripts\python.exe -B -m unittest tests.test_qt_quick_preview.TestNativePreviewHelper.test_local_compatible_scene_round_trips_through_the_coordinator_when_available -v" "PASS" "" $ArtifactJson $sceneBefore
}
else {
    $preview = [ordered]@{ state = "UNAVAILABLE"; reason = "PREVIEW_INPUTS_UNAVAILABLE"; source_sha256 = "" }
    Add-Gate "compatible-preview" "conditional local accepted scene and helper probe" "OPEN" "PREVIEW_INPUTS_UNAVAILABLE" $ArtifactJson
}

$cacheFiles = @()
if (Test-Path -LiteralPath $CacheRoot -PathType Container) {
    $cacheFiles = @(Get-ChildItem -LiteralPath $CacheRoot -Recurse -File -Filter "frame-*.png")
}
$cacheBytes = [int64](($cacheFiles | Measure-Object -Property Length -Sum).Sum)
$cacheLimit = 256 * 1024 * 1024
$maxFrames = 0
if ($cacheFiles.Count -gt 0) {
    $maxFrames = [int](($cacheFiles | Group-Object DirectoryName | ForEach-Object Count | Measure-Object -Maximum).Maximum)
}
if ($cacheBytes -gt $cacheLimit -or $maxFrames -gt 48) {
    throw "The preview cache exceeds the C0 bounds."
}
$cache = [ordered]@{
    frame_count = $cacheFiles.Count
    bytes = $cacheBytes
    byte_limit = $cacheLimit
    maximum_frames_per_entry = $maxFrames
    frame_limit = 48
}
Add-Gate "preview-cache" "bounded inventory of out/preview-cache/frame-*.png" "PASS" "" $ArtifactJson

if ($ReferenceReady) {
    $timingStatusRaw = & $Python -B scripts\benchmark_qt_quick.py --control-center-status --reference-ready
}
else {
    $timingStatusRaw = & $Python -B scripts\benchmark_qt_quick.py --control-center-status
}
Assert-LastExitCode "timing-status"
$timingStatus = ($timingStatusRaw -join "`n") | ConvertFrom-Json
$timing = [ordered]@{ state = $timingStatus.state; warm_start = $null; first_run = $null }
if ($ReferenceReady) {
    $warmRaw = & $Python -B scripts\benchmark_qt_quick.py --scenario warm-start --bundle $Bundle
    Assert-LastExitCode "timing-warm-start"
    $timing.warm_start = ($warmRaw -join "`n") | ConvertFrom-Json
    Add-Gate "timing-warm-start" "..\sg-preflight\.venv\Scripts\python.exe -B scripts\benchmark_qt_quick.py --scenario warm-start --bundle build\b\sgfx-preflight" "PASS" "" $ArtifactJson

    $firstRaw = & $Python -B scripts\benchmark_qt_quick.py --scenario first-run --bundle $Bundle
    Assert-LastExitCode "timing-first-run"
    $timing.first_run = ($firstRaw -join "`n") | ConvertFrom-Json
    Add-Gate "timing-first-run" "..\sg-preflight\.venv\Scripts\python.exe -B scripts\benchmark_qt_quick.py --scenario first-run --bundle build\b\sgfx-preflight" "PASS" "" $ArtifactJson
}
else {
    Add-Gate "timing" "..\sg-preflight\.venv\Scripts\python.exe -B scripts\benchmark_qt_quick.py --control-center-status" "OPEN" "OPEN_LOADED_WORKSTATION" $ArtifactJson
}

$after = Get-TrackedFingerprint $RepoRoot
if ($before.sha256 -ne $after.sha256 -or $before.tracked_bytes -ne $after.tracked_bytes -or $before.tracked_file_count -ne $after.tracked_file_count) {
    throw "Tracked source size, timestamp, or content changed during verification."
}
Add-Gate "source-integrity" "Get-TrackedFingerprint before and after local diagnostics, package, and preview" "PASS" "" $ArtifactJson $after.sha256

$openItems = @($script:Gates | Where-Object state -eq "OPEN" | ForEach-Object {
    [ordered]@{ id = $_.id; state = $_.state; reason = $_.reason }
})
$resultState = if ($openItems.Count -gt 0) { "PASS_WITH_OPEN" } else { "PASS" }
$record = [ordered]@{
    schema_version = 1
    source_commit = $commit
    state = $resultState
    gates = @($script:Gates)
    package = [ordered]@{
        executable_sha256 = $bundleSha256
        ui_capability_count = $manifest.ui_capability_count
        surface_descriptor_count = $manifest.surface_descriptor_count
        qa_hub_schema_version = $manifest.qa_hub_schema_version
        ramses_preview_helper = $manifest.ramses_preview_helper
    }
    viewports = @(
        [ordered]@{ width = 1280; height = 720; state = "PASS" },
        [ordered]@{ width = 1024; height = 640; state = "PASS" }
    )
    preview = $preview
    cache = $cache
    source_integrity = [ordered]@{ before = $before; after = $after; unchanged = $true }
    timing = $timing
    open_items = $openItems
    artifacts = [ordered]@{ json = $ArtifactJson; markdown = $ArtifactMarkdown }
}
$json = $record | ConvertTo-Json -Depth 20
[IO.File]::WriteAllText($JsonPath, $json + "`n", [Text.UTF8Encoding]::new($false))

$markdown = [System.Collections.Generic.List[string]]::new()
$markdown.Add("# SGFX QA Control Center C0 Verification")
$markdown.Add("")
$markdown.Add("- State: ``$resultState``")
$markdown.Add("- Source commit: ``$commit``")
$markdown.Add("- Package SHA-256: ``$bundleSha256``")
$markdown.Add("")
$markdown.Add("| Gate | Result | Reason | Evidence |")
$markdown.Add("|---|---|---|---|")
foreach ($gate in $script:Gates) {
    $evidence = if ($gate.sha256) { $gate.sha256 } else { $gate.artifact }
    $markdown.Add("| $($gate.id) | $($gate.state) | $($gate.reason) | $evidence |")
}
$markdown.Add("")
$markdown.Add("Tracked source size, modification timestamps, and SHA-256 inventory were unchanged across the local verification run.")
[IO.File]::WriteAllText($MarkdownPath, ($markdown -join "`n") + "`n", [Text.UTF8Encoding]::new($false))

Write-Output $ArtifactJson
Write-Output $ArtifactMarkdown
