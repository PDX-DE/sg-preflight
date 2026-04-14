param(
    [string]$OutputRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "out\smoke-test\latest"
}

if (Test-Path $OutputRoot) {
    Remove-Item -LiteralPath $OutputRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null

$stageResults = New-Object System.Collections.Generic.List[object]
$reportSpecs = New-Object System.Collections.Generic.List[object]
$scriptFailed = $false

function Add-StageResult {
    param(
        [string]$Name,
        [string]$Status,
        [int]$ExitCode,
        [string]$LogPath,
        [string]$Notes = ""
    )

    $stageResults.Add([pscustomobject]@{
            Name     = $Name
            Status   = $Status
            ExitCode = $ExitCode
            LogPath  = $LogPath
            Notes    = $Notes
        })
}

function Invoke-Stage {
    param(
        [string]$Name,
        [string[]]$Command,
        [int[]]$AcceptExitCodes = @(0)
    )

    $safeName = ($Name -replace "[^A-Za-z0-9_-]", "_")
    $logPath = Join-Path $OutputRoot "$safeName.log"

    Write-Host ""
    Write-Host "==> $Name" -ForegroundColor Cyan
    Write-Host ($Command -join " ")

    $stdoutPath = Join-Path $OutputRoot "$safeName.stdout.log"
    $stderrPath = Join-Path $OutputRoot "$safeName.stderr.log"
    $argumentList = if ($Command.Length -gt 1) { @($Command[1..($Command.Length - 1)]) } else { @() }

    $process = Start-Process `
        -FilePath $Command[0] `
        -ArgumentList $argumentList `
        -WorkingDirectory $repoRoot `
        -NoNewWindow `
        -Wait `
        -PassThru `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath

    $combined = New-Object System.Collections.Generic.List[string]
    if (Test-Path $stdoutPath) {
        foreach ($line in Get-Content $stdoutPath) {
            $combined.Add($line)
        }
    }
    if (Test-Path $stderrPath) {
        foreach ($line in Get-Content $stderrPath) {
            $combined.Add($line)
        }
    }

    if ($combined.Count -gt 0) {
        foreach ($line in $combined) {
            Write-Host $line
        }
        Set-Content -Path $logPath -Encoding UTF8 -Value $combined
    }
    else {
        Set-Content -Path $logPath -Encoding UTF8 -Value ""
    }

    Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue

    $exitCode = $process.ExitCode
    $passed = $AcceptExitCodes -contains $exitCode
    Add-StageResult -Name $Name -Status ($(if ($passed) { "passed" } else { "failed" })) -ExitCode $exitCode -LogPath $logPath

    return [pscustomobject]@{
        Passed   = $passed
        ExitCode = $exitCode
        LogPath  = $logPath
    }
}

function Add-SkippedStage {
    param(
        [string]$Name,
        [string]$Notes
    )

    $safeName = ($Name -replace "[^A-Za-z0-9_-]", "_")
    $logPath = Join-Path $OutputRoot "$safeName.log"
    Set-Content -Path $logPath -Encoding UTF8 -Value $Notes
    Add-StageResult -Name $Name -Status "skipped" -ExitCode 0 -LogPath $logPath -Notes $Notes
}

function Add-ReportSpec {
    param(
        [string]$Name,
        [string]$JsonPath,
        [string]$HtmlPath,
        [string]$MarkdownPath = ""
    )

    $reportSpecs.Add([pscustomobject]@{
            Name         = $Name
            JsonPath     = $JsonPath
            HtmlPath     = $HtmlPath
            MarkdownPath = $MarkdownPath
        })
}

function Get-SeverityRank {
    param(
        [string]$Severity
    )

    $value = if ($null -eq $Severity) { "" } else { $Severity.ToLowerInvariant() }
    switch ($value) {
        "error" { return 0 }
        "warning" { return 1 }
        "info" { return 2 }
        default { return 99 }
    }
}

function Get-ReportHeadline {
    param(
        [object]$Summary
    )

    if ($Summary.errors -gt 0) {
        return "Needs action before this can be treated as healthy"
    }
    if ($Summary.warnings -gt 0) {
        return "Usable signal, but still noisy and needs triage"
    }
    return "Clean run with no findings"
}

function Get-FindingGroups {
    param(
        [object]$Payload
    )

    $groups = @{}
    foreach ($pack in $Payload.packs) {
        foreach ($finding in $pack.findings) {
            $key = "$($pack.pack)||$($finding.severity)||$($finding.code)||$($finding.message)"
            if (-not $groups.ContainsKey($key)) {
                $groups[$key] = [pscustomobject]@{
                    Pack      = $pack.pack
                    Severity  = $finding.severity
                    Code      = $finding.code
                    Message   = $finding.message
                    Count     = 0
                    Locations = New-Object System.Collections.Generic.List[string]
                }
            }

            $group = $groups[$key]
            $group.Count += 1
            if (-not [string]::IsNullOrWhiteSpace([string]$finding.location) -and $group.Locations.Count -lt 4 -and -not $group.Locations.Contains([string]$finding.location)) {
                $group.Locations.Add([string]$finding.location)
            }
        }
    }

    return @(
        $groups.Values |
            Sort-Object `
                @{ Expression = { Get-SeverityRank -Severity $_.Severity }; Ascending = $true }, `
                @{ Expression = { $_.Count }; Ascending = $false }, `
                @{ Expression = { $_.Pack }; Ascending = $true }, `
                @{ Expression = { $_.Code }; Ascending = $true }
    )
}

function Write-Summary {
    $summaryPath = Join-Path $OutputRoot "SUMMARY.md"
    $lines = New-Object System.Collections.Generic.List[string]
    $reportSnapshots = New-Object System.Collections.Generic.List[object]

    $lines.Add("# SG Preflight Smoke Test")
    $lines.Add("")
    $lines.Add("Created at: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
    $lines.Add("Repo root: $repoRoot")
    $lines.Add("")

    foreach ($report in $reportSpecs) {
        if (-not (Test-Path $report.JsonPath)) {
            continue
        }

        $payload = Get-Content $report.JsonPath -Raw | ConvertFrom-Json
        $summary = $payload.summary
        $jsonName = Split-Path -Leaf $report.JsonPath
        $htmlName = Split-Path -Leaf $report.HtmlPath
        $markdownName = if ($report.MarkdownPath) { Split-Path -Leaf $report.MarkdownPath } else { "" }
        $headline = Get-ReportHeadline -Summary $summary
        $groupedFindings = Get-FindingGroups -Payload $payload
        $reportSnapshots.Add([pscustomobject]@{
                Name         = $report.Name
                JsonName     = $jsonName
                HtmlName     = $htmlName
                MarkdownName = $markdownName
                Errors       = $summary.errors
                Warnings     = $summary.warnings
                Info         = $summary.info
                Total        = $summary.total
                Headline     = $headline
                GroupedItems = $groupedFindings
                Packs        = $payload.packs
            })
    }

    $lines.Add("## Executive Snapshot")
    $lines.Add("")
    $lines.Add("| Run | Errors | Warnings | Total | Readout | HTML | Markdown | JSON |")
    $lines.Add("| --- | ---: | ---: | ---: | --- | --- | --- | --- |")
    foreach ($snapshot in $reportSnapshots) {
        $markdownCell = if ($snapshot.MarkdownName) { "[$($snapshot.MarkdownName)]($($snapshot.MarkdownName))" } else { "-" }
        $lines.Add("| $($snapshot.Name) | $($snapshot.Errors) | $($snapshot.Warnings) | $($snapshot.Total) | $($snapshot.Headline) | [$($snapshot.HtmlName)]($($snapshot.HtmlName)) | $markdownCell | [$($snapshot.JsonName)]($($snapshot.JsonName)) |")
    }

    $lines.Add("")
    $lines.Add("## Stage Results")
    $lines.Add("")
    $lines.Add("| Stage | Status | Exit | Log | Notes |")
    $lines.Add("| --- | --- | ---: | --- | --- |")
    foreach ($stage in $stageResults) {
        $logName = Split-Path -Leaf $stage.LogPath
        $notes = ($stage.Notes -replace "\|", "/")
        $lines.Add("| $($stage.Name) | $($stage.Status) | $($stage.ExitCode) | [$logName]($logName) | $notes |")
    }

    foreach ($snapshot in $reportSnapshots) {
        $lines.Add("")
        $lines.Add("## $($snapshot.Name)")
        $lines.Add("")
        $lines.Add("- Readout: $($snapshot.Headline)")
        $lines.Add("- JSON: [$($snapshot.JsonName)]($($snapshot.JsonName))")
        $lines.Add("- HTML: [$($snapshot.HtmlName)]($($snapshot.HtmlName))")
        if ($snapshot.MarkdownName) {
            $lines.Add("- Markdown handoff: [$($snapshot.MarkdownName)]($($snapshot.MarkdownName))")
        }
        $lines.Add("- Summary: errors=$($snapshot.Errors), warnings=$($snapshot.Warnings), info=$($snapshot.Info), total=$($snapshot.Total)")

        $lines.Add("")
        $lines.Add("Pack summary:")
        foreach ($pack in $snapshot.Packs) {
            $packSummary = $pack.summary
            $lines.Add("- Pack $($pack.pack): errors=$($packSummary.errors), warnings=$($packSummary.warnings), info=$($packSummary.info), total=$($packSummary.total)")
        }

        $lines.Add("")
        $lines.Add("Key takeaways:")
        $topGroups = @($snapshot.GroupedItems | Select-Object -First 6)
        if ($topGroups.Count -eq 0) {
            $lines.Add("- No findings")
        }
        else {
            foreach ($group in $topGroups) {
                $locationText = ""
                if ($group.Locations.Count -gt 0) {
                    $locationText = " Examples: $([string]::Join(', ', $group.Locations))."
                }
                $lines.Add("- [$($group.Severity)] $($group.Pack) / $($group.Code) x$($group.Count) - $($group.Message)$locationText")
            }
        }
    }

    Set-Content -Path $summaryPath -Encoding UTF8 -Value $lines
    Write-Host ""
    Write-Host "Summary written to: $summaryPath" -ForegroundColor Green
}

$unitTestResult = Invoke-Stage -Name "unit-tests" -Command @("python", "-m", "unittest", "discover", "-s", "tests", "-v")
if (-not $unitTestResult.Passed) {
    $scriptFailed = $true
}

$demoGoodJson = Join-Path $OutputRoot "demo-good.json"
$demoGoodHtml = Join-Path $OutputRoot "demo-good.html"
$demoGoodMarkdown = Join-Path $OutputRoot "demo-good.md"
$demoGoodResult = Invoke-Stage -Name "demo-good-run" -Command @(
    "python", "-m", "sg_preflight", "run",
    "--bundle", "demo\good",
    "--config", "config\sg_rules.json",
    "--json-out", $demoGoodJson,
    "--html-out", $demoGoodHtml,
    "--md-out", $demoGoodMarkdown,
    "--fail-on", "error"
)
Add-ReportSpec -Name "Demo Good" -JsonPath $demoGoodJson -HtmlPath $demoGoodHtml -MarkdownPath $demoGoodMarkdown
if (-not $demoGoodResult.Passed) {
    $scriptFailed = $true
}

$demoBrokenJson = Join-Path $OutputRoot "demo-broken.json"
$demoBrokenHtml = Join-Path $OutputRoot "demo-broken.html"
$demoBrokenMarkdown = Join-Path $OutputRoot "demo-broken.md"
$demoBrokenResult = Invoke-Stage -Name "demo-broken-run" -Command @(
    "python", "-m", "sg_preflight", "run",
    "--bundle", "demo\broken",
    "--config", "config\sg_rules.json",
    "--json-out", $demoBrokenJson,
    "--html-out", $demoBrokenHtml,
    "--md-out", $demoBrokenMarkdown,
    "--fail-on", "error"
) -AcceptExitCodes @(2)
Add-ReportSpec -Name "Demo Broken" -JsonPath $demoBrokenJson -HtmlPath $demoBrokenHtml -MarkdownPath $demoBrokenMarkdown
if (-not $demoBrokenResult.Passed) {
    $scriptFailed = $true
}

$introRoot = Join-Path $repoRoot "Introduction\Introduction\ramses-composer-docs-master"
$introBundle = Join-Path $OutputRoot "introduction-bundle"
if ((Test-Path $introRoot) -and (Test-Path (Join-Path $introRoot "export\manual.md"))) {
    $introMaterializeResult = Invoke-Stage -Name "introduction-materialize" -Command @(
        "python", "-m", "sg_preflight", "materialize",
        "--output-bundle", $introBundle,
        "--repo-root", $introRoot,
        "--project-root", $introRoot,
        "--context", "car_model=reference-docs",
        "--context", "trim_line=n/a",
        "--context", "delivery_phase=reference",
        "--context", "review_target=docs_sanity",
        "--context", "evidence_source=Introduction_corpus"
    )
    if ($introMaterializeResult.Passed) {
        $introJson = Join-Path $OutputRoot "introduction-project-sanity.json"
        $introHtml = Join-Path $OutputRoot "introduction-project-sanity.html"
        $introMarkdown = Join-Path $OutputRoot "introduction-project-sanity.md"
        $introRunResult = Invoke-Stage -Name "introduction-project-sanity-run" -Command @(
            "python", "-m", "sg_preflight", "run",
            "--bundle", $introBundle,
            "--config", "config\sg_rules.json",
            "--packs", "project_sanity",
            "--json-out", $introJson,
            "--html-out", $introHtml,
            "--md-out", $introMarkdown,
            "--fail-on", "never"
        )
        Add-ReportSpec -Name "Introduction Project Sanity" -JsonPath $introJson -HtmlPath $introHtml -MarkdownPath $introMarkdown
        if (-not $introRunResult.Passed) {
            $scriptFailed = $true
        }
    }
    else {
        $scriptFailed = $true
    }
}
else {
    Add-SkippedStage -Name "introduction-materialize" -Notes "Introduction reference corpus not found; skipped"
    Add-SkippedStage -Name "introduction-project-sanity-run" -Notes "Introduction reference corpus not found; skipped"
}

$currentRepoRoot = Join-Path $repoRoot "OneDrive_4_14-04-2026"
$currentProjectRoot = Join-Path $repoRoot "OneDrive_5_14-04-2026\Debug\MiniKombi"
$currentCarpaintSource = Join-Path $repoRoot "Markus_Delete\Documents\Carpaints.xlsx"
$currentBundle = Join-Path $OutputRoot "current-source-bundle"

if ((Test-Path $currentRepoRoot) -and (Test-Path $currentProjectRoot) -and (Test-Path $currentCarpaintSource)) {
    $currentMaterializeResult = Invoke-Stage -Name "current-source-materialize" -Command @(
        "python", "-m", "sg_preflight", "materialize",
        "--output-bundle", $currentBundle,
        "--repo-root", $currentRepoRoot,
        "--project-root", $currentProjectRoot,
        "--carpaints-source", $currentCarpaintSource,
        "--context", "car_model=MiniKombi",
        "--context", "trim_line=unknown",
        "--context", "delivery_phase=pre_access_reference",
        "--context", "review_target=current_source_drop",
        "--context", "evidence_source=OneDrive_and_local_tool_drops"
    )

    if ($currentMaterializeResult.Passed) {
        $currentJson = Join-Path $OutputRoot "current-source.json"
        $currentHtml = Join-Path $OutputRoot "current-source.html"
        $currentMarkdown = Join-Path $OutputRoot "current-source.md"
        $currentRunResult = Invoke-Stage -Name "current-source-run" -Command @(
            "python", "-m", "sg_preflight", "run",
            "--bundle", $currentBundle,
            "--config", "config\sg_rules.json",
            "--packs", "carpaints,project_sanity",
            "--json-out", $currentJson,
            "--html-out", $currentHtml,
            "--md-out", $currentMarkdown,
            "--fail-on", "never"
        )
        Add-ReportSpec -Name "Current Source Bundle" -JsonPath $currentJson -HtmlPath $currentHtml -MarkdownPath $currentMarkdown
        if (-not $currentRunResult.Passed) {
            $scriptFailed = $true
        }
    }
    else {
        $scriptFailed = $true
    }
}
else {
    Add-SkippedStage -Name "current-source-materialize" -Notes "Current source bundle inputs not found; skipped"
    Add-SkippedStage -Name "current-source-run" -Notes "Current source bundle inputs not found; skipped"
}

Write-Summary
exit $(if ($scriptFailed) { 1 } else { 0 })
