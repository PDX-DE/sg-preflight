param(
    [string]$OutputRoot = "",
    [string[]]$Cars = @("G70", "G65", "G45")
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "out\real-live-matrix\latest"
}

$sgRepoRoot = Join-Path $repoRoot "repositories\trunk"
if (-not (Test-Path $sgRepoRoot)) {
    throw "Live SG mirror not found at $sgRepoRoot"
}

$profiles = @{
    "G70" = [pscustomobject]@{
        Name        = "G70"
        ProjectRoot = Join-Path $sgRepoRoot "Cars_IDCevo\BMW\G70"
        ConfigPath  = Join-Path $repoRoot "config\sg_rules_live.json"
        Context     = [ordered]@{
            car_model      = "G70"
            trim_line      = "Basis"
            delivery_phase = "svn_live_preflight"
            review_target  = "g70_end_to_end"
            evidence_source = "local_svn_mirror"
        }
    }
    "G65" = [pscustomobject]@{
        Name        = "G65"
        ProjectRoot = Join-Path $sgRepoRoot "Cars_IDCevo\BMW\G65"
        ConfigPath  = Join-Path $repoRoot "config\sg_rules_live_g65.json"
        Context     = [ordered]@{
            car_model      = "G65"
            trim_line      = "Basis"
            delivery_phase = "svn_live_preflight"
            review_target  = "g65_end_to_end"
            evidence_source = "local_svn_mirror"
        }
    }
    "G45" = [pscustomobject]@{
        Name        = "G45"
        ProjectRoot = Join-Path $sgRepoRoot "Cars\BMW\G45"
        ConfigPath  = Join-Path $repoRoot "config\sg_rules_live_g45.json"
        Context     = [ordered]@{
            car_model      = "G45"
            trim_line      = "Basis"
            delivery_phase = "svn_live_preflight"
            review_target  = "g45_anchor_family_preflight"
            evidence_source = "local_svn_mirror"
        }
    }
}

foreach ($car in $Cars) {
    if (-not $profiles.ContainsKey($car)) {
        throw "Unsupported car profile '$car'. Supported profiles: $([string]::Join(', ', $profiles.Keys))"
    }
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

function Add-ReportSpec {
    param(
        [string]$Name,
        [string]$Slug,
        [string]$JsonPath,
        [string]$HtmlPath,
        [string]$MarkdownPath
    )

    $reportSpecs.Add([pscustomobject]@{
            Name         = $Name
            Slug         = $Slug
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
        return "Needs action before this car can be treated as healthy"
    }
    if ($Summary.warnings -gt 0) {
        return "Usable signal, but still needs triage"
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

    $lines.Add("# SG Preflight Live Car Matrix")
    $lines.Add("")
    $lines.Add("Created at: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
    $lines.Add("Repo root: $repoRoot")
    $lines.Add("SG mirror: $sgRepoRoot")
    $lines.Add("Cars: $([string]::Join(', ', $Cars))")
    $lines.Add("")

    foreach ($report in $reportSpecs) {
        if (-not (Test-Path $report.JsonPath)) {
            continue
        }

        $payload = Get-Content $report.JsonPath -Raw | ConvertFrom-Json
        $summary = $payload.summary
        $jsonName = Split-Path -Leaf $report.JsonPath
        $htmlName = Split-Path -Leaf $report.HtmlPath
        $markdownName = Split-Path -Leaf $report.MarkdownPath
        $headline = Get-ReportHeadline -Summary $summary
        $groupedFindings = Get-FindingGroups -Payload $payload
        $reportSnapshots.Add([pscustomobject]@{
                Name         = $report.Name
                Slug         = $report.Slug
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
    $lines.Add("| Car | Errors | Warnings | Total | Readout | HTML | Markdown | JSON |")
    $lines.Add("| --- | ---: | ---: | ---: | --- | --- | --- | --- |")
    foreach ($snapshot in $reportSnapshots) {
        $htmlLink = "$($snapshot.Slug)/$($snapshot.HtmlName)"
        $markdownLink = "$($snapshot.Slug)/$($snapshot.MarkdownName)"
        $jsonLink = "$($snapshot.Slug)/$($snapshot.JsonName)"
        $lines.Add("| $($snapshot.Name) | $($snapshot.Errors) | $($snapshot.Warnings) | $($snapshot.Total) | $($snapshot.Headline) | [$($snapshot.HtmlName)]($htmlLink) | [$($snapshot.MarkdownName)]($markdownLink) | [$($snapshot.JsonName)]($jsonLink) |")
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
        $lines.Add("- HTML: [$($snapshot.HtmlName)]($($snapshot.Slug)/$($snapshot.HtmlName))")
        $lines.Add("- Markdown handoff: [$($snapshot.MarkdownName)]($($snapshot.Slug)/$($snapshot.MarkdownName))")
        $lines.Add("- JSON: [$($snapshot.JsonName)]($($snapshot.Slug)/$($snapshot.JsonName))")
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

foreach ($car in $Cars) {
    $profile = $profiles[$car]
    $slug = $car.ToLowerInvariant()
    $carOutputRoot = Join-Path $OutputRoot $slug
    New-Item -ItemType Directory -Path $carOutputRoot -Force | Out-Null

    if (-not (Test-Path $profile.ProjectRoot)) {
        Add-SkippedStage -Name "$slug-materialize" -Notes "Project root not found at $($profile.ProjectRoot)"
        Add-SkippedStage -Name "$slug-run" -Notes "Project root not found at $($profile.ProjectRoot)"
        $scriptFailed = $true
        continue
    }

    if (-not (Test-Path $profile.ConfigPath)) {
        Add-SkippedStage -Name "$slug-materialize" -Notes "Config not found at $($profile.ConfigPath)"
        Add-SkippedStage -Name "$slug-run" -Notes "Config not found at $($profile.ConfigPath)"
        $scriptFailed = $true
        continue
    }

    $bundleRoot = Join-Path $carOutputRoot "bundle"
    $jsonOut = Join-Path $carOutputRoot "$slug-report.json"
    $htmlOut = Join-Path $carOutputRoot "$slug-report.html"
    $markdownOut = Join-Path $carOutputRoot "$slug-report.md"

    $materializeCommand = @(
        "python", "-m", "sg_preflight", "materialize",
        "--output-bundle", $bundleRoot,
        "--repo-root", $sgRepoRoot,
        "--project-root", $profile.ProjectRoot,
        "--env", "SG-Repo=$sgRepoRoot",
        "--env", "SG-CarModels-Repo=$sgRepoRoot"
    )
    foreach ($entry in $profile.Context.GetEnumerator()) {
        $materializeCommand += @("--context", "$($entry.Key)=$($entry.Value)")
    }

    $materializeResult = Invoke-Stage -Name "$slug-materialize" -Command $materializeCommand
    if (-not $materializeResult.Passed) {
        $scriptFailed = $true
        continue
    }

    $runResult = Invoke-Stage -Name "$slug-run" -Command @(
        "python", "-m", "sg_preflight", "run",
        "--bundle", $bundleRoot,
        "--config", $profile.ConfigPath,
        "--json-out", $jsonOut,
        "--html-out", $htmlOut,
        "--md-out", $markdownOut,
        "--fail-on", "never"
    )
    Add-ReportSpec -Name $profile.Name -Slug $slug -JsonPath $jsonOut -HtmlPath $htmlOut -MarkdownPath $markdownOut
    if (-not $runResult.Passed) {
        $scriptFailed = $true
    }
}

Write-Summary
exit $(if ($scriptFailed) { 1 } else { 0 })
