param(
    [Parameter(Mandatory=$true)][string]$Evidence,
    [Parameter(Mandatory=$true)][string]$Exe,
    [Parameter(Mandatory=$true)][string]$Workspace,
    [string]$Profile = "G65"
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "uia_readiness.ps1")

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

New-Item -ItemType Directory -Force -Path $Evidence | Out-Null
$process = $null
try {
    $args = @("dashboard", "run", "--profile", $Profile, "--workspace", $Workspace, "--ui-mode", "grafiks")
    $process = Start-Process -FilePath $Exe -ArgumentList $args -WorkingDirectory (Split-Path $Exe) -PassThru
    $title = Wait-SgfxWindowTitle -Process $process -Text "Grafiks Operator Console" -TimeoutSeconds 150
    $controls = Wait-SgfxSetupControlsReady -ProcessId $process.Id -TimeoutSeconds 90
    $postDialogReady = Wait-SgfxSetupControlsAfterDialogClose -ProcessId $process.Id -TimeoutSeconds 30
    $manifest = [ordered]@{
        recorded_at = [DateTimeOffset]::Now.ToString("yyyy-MM-dd HH:mm:ss zzz", [System.Globalization.CultureInfo]::InvariantCulture)
        profile = $Profile
        workspace = $Workspace
        window_title = $title
        process_id = $process.Id
        dependency_setup_visible = $true
        run_setup_visible = $null -ne $controls.RunSetup
        cancel_setup_visible = $null -ne $controls.CancelSetup
        run_setup_enabled = $controls.RunSetupEnabled
        cancel_setup_enabled = $controls.CancelSetupEnabled
        post_dialog_reattach_ready = $null -ne $postDialogReady.Panel
    }
    $path = Join-Path $Evidence "grafiks-setup-uia-probe.json"
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $path -Encoding UTF8
    Write-Output $path
} finally {
    if ($process) {
        Stop-SgfxProcessTree -RootId $process.Id
    }
}
