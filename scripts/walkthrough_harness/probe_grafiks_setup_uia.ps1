param(
    [Parameter(Mandatory=$true)][string]$Evidence,
    [Parameter(Mandatory=$true)][string]$Exe,
    [Parameter(Mandatory=$true)][string]$Workspace,
    [string]$Profile = "G65"
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

New-Item -ItemType Directory -Force -Path $Evidence | Out-Null
$process = $null
try {
    $args = @("dashboard", "run", "--profile", $Profile, "--workspace", $Workspace, "--ui-mode", "grafiks")
    $process = Start-Process -FilePath $Exe -ArgumentList $args -WorkingDirectory (Split-Path $Exe) -PassThru
    $title = Wait-SgfxWindowTitle -Process $process -Text "SGFX" -TimeoutSeconds 150
    $controls = Wait-SgfxSetupControlsReady -ProcessId $process.Id -TimeoutSeconds 90
    $postDialogReady = Wait-SgfxSetupControlsAfterDialogClose -ProcessId $process.Id -TimeoutSeconds 30
    $screenshotPath = Join-Path $Evidence "grafiks-setup-uia.png"
    Save-SgfxWindowScreenshot -Process $process -Path $screenshotPath
    $manifest = [ordered]@{
        recorded_at = [DateTimeOffset]::Now.ToString("yyyy-MM-dd HH:mm:ss zzz", [System.Globalization.CultureInfo]::InvariantCulture)
        profile = $Profile
        workspace = $Workspace
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
    $path = Join-Path $Evidence "grafiks-setup-uia-probe.json"
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $path -Encoding UTF8
    Write-Output $path
} finally {
    if ($process) {
        Stop-SgfxProcessTree -RootId $process.Id
    }
}
