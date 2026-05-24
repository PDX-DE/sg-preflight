param(
    [Parameter(Mandatory=$true)][string]$Evidence,
    [Parameter(Mandatory=$true)][string]$Exe,
    [Parameter(Mandatory=$true)][string]$Workspace,
    [string]$Profile = "G70",
    [string[]]$Profiles = @()
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "uia_readiness.ps1")

Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class SgfxProbeWindow {
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
}
"@

function Stop-SgfxProcessTree {
    param([Parameter(Mandatory=$true)][int]$RootId)

    $ids = New-Object System.Collections.Generic.List[int]
    $queue = New-Object System.Collections.Generic.Queue[int]
    $ids.Add($RootId)
    $queue.Enqueue($RootId)
    while ($queue.Count -gt 0) {
        $current = $queue.Dequeue()
        Get-CimInstance Win32_Process -Filter "ParentProcessId=$current" -ErrorAction SilentlyContinue | ForEach-Object {
            $childId = [int]$_.ProcessId
            if (-not $ids.Contains($childId)) {
                $ids.Add($childId)
                $queue.Enqueue($childId)
            }
        }
    }
    foreach ($id in @($ids | Sort-Object -Descending)) {
        $process = Get-Process -Id $id -ErrorAction SilentlyContinue
        if ($process -and -not $process.HasExited) {
            try {
                if ($process.MainWindowHandle -ne 0) {
                    [void]$process.CloseMainWindow()
                    Start-Sleep -Milliseconds 350
                }
            } catch {
            }
        }
    }
    foreach ($id in @($ids | Sort-Object -Descending)) {
        $process = Get-Process -Id $id -ErrorAction SilentlyContinue
        if ($process -and -not $process.HasExited) {
            Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
        }
    }
}

function Wait-SgfxWindowTitle {
    param(
        [Parameter(Mandatory=$true)][System.Diagnostics.Process]$Process,
        [Parameter(Mandatory=$true)][string]$Text,
        [int]$TimeoutSeconds = 90
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $Process.Refresh()
        if ($Process.HasExited) {
            throw "Process $($Process.Id) exited while waiting for title '$Text'."
        }
        if ($Process.MainWindowTitle -like "*$Text*") {
            return $Process.MainWindowTitle
        }
        Start-Sleep -Milliseconds 250
    }
    $Process.Refresh()
    throw "Timed out waiting for title '$Text'; last title '$($Process.MainWindowTitle)'."
}

function Save-SgfxWindowScreenshot {
    param(
        [Parameter(Mandatory=$true)][System.Diagnostics.Process]$Process,
        [Parameter(Mandatory=$true)][string]$Path
    )

    $Process.Refresh()
    if ($Process.MainWindowHandle -eq 0) {
        throw "Process $($Process.Id) has no main window handle for screenshot capture."
    }
    [void][SgfxProbeWindow]::SetForegroundWindow([IntPtr]$Process.MainWindowHandle)
    Start-Sleep -Milliseconds 500
    $rect = New-Object SgfxProbeWindow+RECT
    if (-not [SgfxProbeWindow]::GetWindowRect([IntPtr]$Process.MainWindowHandle, [ref]$rect)) {
        throw "GetWindowRect failed for process $($Process.Id)."
    }
    $width = [Math]::Max(1, $rect.Right - $rect.Left)
    $height = [Math]::Max(1, $rect.Bottom - $rect.Top)
    $bitmap = [System.Drawing.Bitmap]::new($width, $height)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.CopyFromScreen($rect.Left, $rect.Top, 0, 0, $bitmap.Size)
        $bitmap.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
    } finally {
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}

function Get-SgfxProbeProfiles {
    param(
        [string]$Primary,
        [string[]]$Requested
    )

    $phaseFMinimum = @("G65", "G70", "NA8", "F70", "U10")
    $ordered = New-Object System.Collections.Generic.List[string]
    $rawProfiles = New-Object System.Collections.Generic.List[string]
    if ($Requested -and $Requested.Count -gt 0) {
        foreach ($item in $Requested) {
            foreach ($part in ($item -split ",")) {
                $rawProfiles.Add($part)
            }
        }
    } elseif ($Primary) {
        $rawProfiles.Add($Primary)
    }
    $combined = @()
    $combined += $rawProfiles.ToArray()
    $combined += $phaseFMinimum
    foreach ($item in $combined) {
        $clean = ($item -as [string]).Trim().ToUpperInvariant()
        if ($clean -and -not $ordered.Contains($clean)) {
            $ordered.Add($clean)
        }
    }
    return $ordered.ToArray()
}

function Invoke-SgfxGrafiksProfileProbe {
    param(
        [Parameter(Mandatory=$true)][string]$CurrentProfile,
        [Parameter(Mandatory=$true)][string]$EvidenceRoot,
        [Parameter(Mandatory=$true)][string]$ExePath,
        [Parameter(Mandatory=$true)][string]$WorkspaceRoot,
        [bool]$MirrorRoot = $false
    )

    $profileEvidence = Join-Path (Join-Path $EvidenceRoot "profiles") $CurrentProfile
    New-Item -ItemType Directory -Force -Path $profileEvidence | Out-Null
    $process = $null
    try {
        $args = @("dashboard", "run", "--profile", $CurrentProfile, "--workspace", $WorkspaceRoot, "--ui-mode", "grafiks")
        $process = Start-Process -FilePath $ExePath -ArgumentList $args -WorkingDirectory (Split-Path $ExePath) -PassThru
        $title = Wait-SgfxWindowTitle -Process $process -Text "Seriengrafik: Project Quality-Hero" -TimeoutSeconds 150
        $controls = Wait-SgfxSetupControlsReady -ProcessId $process.Id -TimeoutSeconds 90
        $postDialogReady = Wait-SgfxSetupControlsAfterDialogClose -ProcessId $process.Id -TimeoutSeconds 30
        $screenshotPath = Join-Path $profileEvidence "grafiks-setup-uia.png"
        Save-SgfxWindowScreenshot -Process $process -Path $screenshotPath
        $manifest = [ordered]@{
            recorded_at = [DateTimeOffset]::Now.ToString("yyyy-MM-dd HH:mm:ss zzz", [System.Globalization.CultureInfo]::InvariantCulture)
            profile = $CurrentProfile
            workspace = $WorkspaceRoot
            window_title = $title
            process_id = $process.Id
            screenshot = $screenshotPath
            dependency_setup_visible = $true
            run_setup_visible = $null -ne $controls.RunSetup
            cancel_setup_visible = $null -ne $controls.CancelSetup
            run_setup_enabled = $controls.RunSetupEnabled
            cancel_setup_enabled = $controls.CancelSetupEnabled
            post_dialog_reattach_ready = $null -ne $postDialogReady.Panel
        }
        $profileManifestPath = Join-Path $profileEvidence "grafiks-setup-uia-probe.json"
        $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $profileManifestPath -Encoding UTF8
        if ($MirrorRoot) {
            Copy-Item -LiteralPath $screenshotPath -Destination (Join-Path $EvidenceRoot "grafiks-setup-uia.png") -Force
            $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $EvidenceRoot "grafiks-setup-uia-probe.json") -Encoding UTF8
        }
        return $manifest
    } finally {
        if ($process) {
            Stop-SgfxProcessTree -RootId $process.Id
        }
    }
}

New-Item -ItemType Directory -Force -Path $Evidence | Out-Null
$profileList = @(Get-SgfxProbeProfiles -Primary $Profile -Requested $Profiles)
$results = New-Object System.Collections.Generic.List[object]
for ($index = 0; $index -lt $profileList.Count; $index++) {
    $currentProfile = $profileList[$index]
    $results.Add((Invoke-SgfxGrafiksProfileProbe -CurrentProfile $currentProfile -EvidenceRoot $Evidence -ExePath $Exe -WorkspaceRoot $Workspace -MirrorRoot ($index -eq 0)))
}

$minimumProfiles = @("G65", "G70", "NA8", "F70", "U10")
$buggyProfiles = @("G70", "NA8")
$aggregate = [ordered]@{
    recorded_at = [DateTimeOffset]::Now.ToString("yyyy-MM-dd HH:mm:ss zzz", [System.Globalization.CultureInfo]::InvariantCulture)
    workspace = $Workspace
    profiles = $profileList
    minimum_profiles = $minimumProfiles
    results = $results.ToArray()
    assertions = [ordered]@{
        minimum_profile_set_covered = @($minimumProfiles | Where-Object { $profileList -contains $_ }).Count -eq $minimumProfiles.Count
        buggy_profile_covered = @($buggyProfiles | Where-Object { $profileList -contains $_ }).Count -gt 0
        dependency_setup_visible_all_profiles = @($results | Where-Object { -not $_.dependency_setup_visible }).Count -eq 0
        setup_controls_visible_all_profiles = @($results | Where-Object { -not ($_.run_setup_visible -and $_.cancel_setup_visible) }).Count -eq 0
        post_dialog_reattach_ready_all_profiles = @($results | Where-Object { -not $_.post_dialog_reattach_ready }).Count -eq 0
    }
}
$aggregatePath = Join-Path $Evidence "grafiks-setup-uia-probes.json"
$aggregate | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $aggregatePath -Encoding UTF8
Write-Output $aggregatePath
