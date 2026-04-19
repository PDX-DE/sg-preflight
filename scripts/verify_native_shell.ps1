param(
    [string]$ExePath = "",
    [string]$OutputRoot = "",
    [int]$InitialSettleMs = 8000,
    [int]$ScreenSettleMs = 2200,
    [int]$PromptSettleMs = 1000
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

if (-not $ExePath) {
    $latestPointer = Join-Path $repoRoot "build\latest_native_shell_path.txt"
    if (-not (Test-Path $latestPointer)) {
        throw "Latest native shell pointer was not found at $latestPointer"
    }
    $ExePath = (Get-Content $latestPointer -Raw).Trim()
}

if (-not (Test-Path $ExePath)) {
    throw "Native shell executable was not found at $ExePath"
}

if (-not $OutputRoot) {
    $timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
    $OutputRoot = Join-Path $repoRoot "build\native-installer-fullscreen\verification\auto-$timestamp"
}

if (Test-Path $OutputRoot) {
    Remove-Item -LiteralPath $OutputRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
$tracePath = Join-Path $OutputRoot "backend-trace.log"
if (Test-Path $tracePath) {
    Remove-Item -LiteralPath $tracePath -Force
}

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;

public static class NativeShellVerify {
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }

    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);

    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

    [DllImport("user32.dll")]
    public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdcBlt, int nFlags);

    [DllImport("user32.dll")]
    public static extern bool PostMessage(IntPtr hWnd, uint Msg, UIntPtr wParam, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern void keybd_event(byte bVk, byte bScan, int dwFlags, int dwExtraInfo);
}
"@

$log = New-Object System.Collections.Generic.List[string]
$log.Add("Native shell verification")
$log.Add("Created: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
$log.Add("Executable: $ExePath")
$log.Add("Output: $OutputRoot")
$log.Add("Trace: $tracePath")
$log.Add("")

$shell = New-Object -ComObject WScript.Shell
$launchArgs = @("--windowed", "--width", "1280", "--height", "720")
$process = $null
$previousTraceEnv = $env:SG_PREFLIGHT_NATIVE_TRACE_FILE
$env:SG_PREFLIGHT_NATIVE_TRACE_FILE = $tracePath

function Write-VerificationLog {
    Set-Content -Path (Join-Path $OutputRoot "verification.log") -Encoding UTF8 -Value $log
}

function Wait-ForMainWindow {
    param(
        [System.Diagnostics.Process]$TargetProcess,
        [int]$TimeoutSeconds = 20
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $TargetProcess.Refresh()
        if ($TargetProcess.HasExited) {
            throw "Native shell exited before the verification flow could attach."
        }
        if ($TargetProcess.MainWindowHandle -ne 0) {
            return
        }
        Start-Sleep -Milliseconds 200
    }

    throw "Timed out waiting for the native shell window."
}

function Get-WindowRect {
    param([System.Diagnostics.Process]$TargetProcess)

    $rect = New-Object NativeShellVerify+RECT
    if (-not [NativeShellVerify]::GetWindowRect($TargetProcess.MainWindowHandle, [ref]$rect)) {
        throw "GetWindowRect failed for the native shell window."
    }
    return $rect
}

function Activate-Window {
    param([System.Diagnostics.Process]$TargetProcess)

    $TargetProcess.Refresh()
    [void][NativeShellVerify]::ShowWindow($TargetProcess.MainWindowHandle, 9)
    [void][NativeShellVerify]::SetForegroundWindow($TargetProcess.MainWindowHandle)
    [void]$shell.AppActivate($TargetProcess.Id)
    Start-Sleep -Milliseconds 250
}

function Capture-Stage {
    param(
        [System.Diagnostics.Process]$TargetProcess,
        [string]$Name
    )

    Activate-Window -TargetProcess $TargetProcess
    $rect = Get-WindowRect -TargetProcess $TargetProcess
    $width = [Math]::Max(1, $rect.Right - $rect.Left)
    $height = [Math]::Max(1, $rect.Bottom - $rect.Top)
    $targetPath = Join-Path $OutputRoot "$Name.png"

    function Save-CaptureBitmap {
        param(
            [IntPtr]$WindowHandle,
            [int]$CaptureLeft,
            [int]$CaptureTop,
            [int]$CaptureWidth,
            [int]$CaptureHeight
        )

        $bitmap = New-Object System.Drawing.Bitmap $CaptureWidth, $CaptureHeight
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        try {
            try {
                $hdc = $graphics.GetHdc()
                try {
                    if (-not [NativeShellVerify]::PrintWindow($WindowHandle, $hdc, 0)) {
                        throw "PrintWindow failed"
                    }
                }
                finally {
                    $graphics.ReleaseHdc($hdc)
                }
            }
            catch {
                $graphics.CopyFromScreen($CaptureLeft, $CaptureTop, 0, 0, $bitmap.Size)
            }
            $bitmap.Save($targetPath, [System.Drawing.Imaging.ImageFormat]::Png)
        }
        finally {
            $graphics.Dispose()
            $bitmap.Dispose()
        }
    }

    try {
        Save-CaptureBitmap -WindowHandle $TargetProcess.MainWindowHandle -CaptureLeft $rect.Left -CaptureTop $rect.Top -CaptureWidth $width -CaptureHeight $height
        $log.Add("[$Name] screenshot: $targetPath")
        $log.Add("[$Name] bounds: left=$($rect.Left) top=$($rect.Top) width=$width height=$height")
        $log.Add("")
    }
    catch {
        Start-Sleep -Milliseconds 300
        try {
            Save-CaptureBitmap -WindowHandle $TargetProcess.MainWindowHandle -CaptureLeft $rect.Left -CaptureTop $rect.Top -CaptureWidth $width -CaptureHeight $height
            $log.Add("[$Name] screenshot: $targetPath")
            $log.Add("[$Name] bounds: left=$($rect.Left) top=$($rect.Top) width=$width height=$height (retry)")
            $log.Add("")
        }
        catch {
            $screenBounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
            Save-CaptureBitmap -WindowHandle $TargetProcess.MainWindowHandle -CaptureLeft $screenBounds.Left -CaptureTop $screenBounds.Top -CaptureWidth $screenBounds.Width -CaptureHeight $screenBounds.Height
            $log.Add("[$Name] screenshot fallback: $targetPath")
            $log.Add("[$Name] requested bounds failed; used primary screen fallback")
            $log.Add("")
        }
    }
}

function Send-Key {
    param(
        [System.Diagnostics.Process]$TargetProcess,
        [string]$Keys,
        [int]$SettleMs = 1000
    )

    Activate-Window -TargetProcess $TargetProcess
    $log.Add("[input] $Keys")
    $virtualKey = switch ($Keys) {
        "{ENTER}" { 0x0D; break }
        "{ESC}" { 0x1B; break }
        "{F1}" { 0x70; break }
        "L" { 0x4C; break }
        "P" { 0x50; break }
        default { $null }
    }
    if ($null -ne $virtualKey) {
        $keyParam = [UIntPtr]::new([uint32]$virtualKey)
        $postedDown = [NativeShellVerify]::PostMessage($TargetProcess.MainWindowHandle, 0x0100, $keyParam, [IntPtr]::Zero)
        Start-Sleep -Milliseconds 40
        $postedUp = [NativeShellVerify]::PostMessage($TargetProcess.MainWindowHandle, 0x0101, $keyParam, [IntPtr]::Zero)
        if (-not ($postedDown -and $postedUp)) {
            [NativeShellVerify]::keybd_event([byte]$virtualKey, 0, 0, 0)
            Start-Sleep -Milliseconds 40
            [NativeShellVerify]::keybd_event([byte]$virtualKey, 0, 2, 0)
        }
    } else {
        $shell.SendKeys($Keys)
    }
    Start-Sleep -Milliseconds $SettleMs
}

function Wait-ForTraceIdle {
    param(
        [string]$Path,
        [int]$TimeoutSeconds = 30,
        [int]$StableMs = 1800
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastSize = -1L
    $stableSince = $null

    while ((Get-Date) -lt $deadline) {
        $currentSize = if (Test-Path $Path) { (Get-Item $Path).Length } else { -1L }
        if ($currentSize -eq $lastSize -and $currentSize -ge 0) {
            if ($null -eq $stableSince) {
                $stableSince = Get-Date
            }
            if (((Get-Date) - $stableSince).TotalMilliseconds -ge $StableMs) {
                $log.Add("[trace] idle after $currentSize bytes")
                return
            }
        } else {
            $stableSince = $null
            $lastSize = $currentSize
        }
        Start-Sleep -Milliseconds 250
    }

    $log.Add("[trace] idle wait timed out")
}

function Get-TraceText {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        return ""
    }

    try {
        return Get-Content -LiteralPath $Path -Raw -ErrorAction Stop
    }
    catch {
        return ""
    }
}

function Wait-ForTracePattern {
    param(
        [string]$Path,
        [string]$Pattern,
        [int]$TimeoutSeconds = 12
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $text = Get-TraceText -Path $Path
        if ($text -match [regex]::Escape($Pattern)) {
            $log.Add("[trace] matched: $Pattern")
            return $true
        }
        Start-Sleep -Milliseconds 150
    }

    $log.Add("[trace] missing: $Pattern")
    return $false
}

try {
    $process = Start-Process -FilePath $ExePath -ArgumentList $launchArgs -WorkingDirectory $repoRoot -PassThru
    Wait-ForMainWindow -TargetProcess $process
    Start-Sleep -Milliseconds $InitialSettleMs

    Capture-Stage -TargetProcess $process -Name "intro"
    Wait-ForTraceIdle -Path $tracePath

    Send-Key -TargetProcess $process -Keys "{ENTER}" -SettleMs $ScreenSettleMs
    Capture-Stage -TargetProcess $process -Name "select"

    Send-Key -TargetProcess $process -Keys "{F1}" -SettleMs $PromptSettleMs
    [void](Wait-ForTracePattern -Path $tracePath -Pattern 'UI prompt_open title="Help"' -TimeoutSeconds 6)
    Capture-Stage -TargetProcess $process -Name "help_select"
    Send-Key -TargetProcess $process -Keys "{ENTER}" -SettleMs $PromptSettleMs

    Send-Key -TargetProcess $process -Keys "{ENTER}" -SettleMs $ScreenSettleMs
    Capture-Stage -TargetProcess $process -Name "review"

    Send-Key -TargetProcess $process -Keys "{ENTER}" -SettleMs 2600
    Capture-Stage -TargetProcess $process -Name "run"

    Start-Sleep -Milliseconds 3200
    Capture-Stage -TargetProcess $process -Name "run_after_3s"

    if (-not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
        Start-Sleep -Milliseconds 300
    }

    $process = Start-Process -FilePath $ExePath -ArgumentList $launchArgs -WorkingDirectory $repoRoot -PassThru
    Wait-ForMainWindow -TargetProcess $process
    Start-Sleep -Milliseconds $InitialSettleMs
    Wait-ForTraceIdle -Path $tracePath

    Capture-Stage -TargetProcess $process -Name "prompt_intro"

    Send-Key -TargetProcess $process -Keys "{ESC}" -SettleMs $PromptSettleMs
    [void](Wait-ForTracePattern -Path $tracePath -Pattern 'UI prompt_open title="QUIT SG PREFLIGHT"' -TimeoutSeconds 6)
    Capture-Stage -TargetProcess $process -Name "prompt_banner"

    Send-Key -TargetProcess $process -Keys "{ENTER}" -SettleMs $PromptSettleMs
    [void](Wait-ForTracePattern -Path $tracePath -Pattern 'UI prompt_controls_open title="QUIT SG PREFLIGHT"' -TimeoutSeconds 6)
    Capture-Stage -TargetProcess $process -Name "prompt_choices"

    $quitStart = Get-Date
    Send-Key -TargetProcess $process -Keys "{ENTER}" -SettleMs 100
    [void](Wait-ForTracePattern -Path $tracePath -Pattern "UI exit_begin" -TimeoutSeconds 8)

    $waitDeadline = (Get-Date).AddSeconds(12)
    while (-not $process.HasExited -and (Get-Date) -lt $waitDeadline) {
        Start-Sleep -Milliseconds 100
        $process.Refresh()
    }

    $quitMs = [int]((Get-Date) - $quitStart).TotalMilliseconds
    if (-not $process.HasExited) {
        [void](Wait-ForTracePattern -Path $tracePath -Pattern "UI exit_complete" -TimeoutSeconds 2)
        $log.Add("[close] process did not exit within timeout; forcing shutdown")
        Stop-Process -Id $process.Id -Force
    } else {
        $log.Add("[close] process exited after ${quitMs}ms")
    }
}
finally {
    if ($null -ne $process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
    if ($null -eq $previousTraceEnv) {
        Remove-Item Env:SG_PREFLIGHT_NATIVE_TRACE_FILE -ErrorAction SilentlyContinue
    } else {
        $env:SG_PREFLIGHT_NATIVE_TRACE_FILE = $previousTraceEnv
    }
    if (Test-Path $tracePath) {
        $traceSize = (Get-Item $tracePath).Length
        $log.Add("[trace] backend trace captured ($traceSize bytes)")
    } else {
        $log.Add("[trace] backend trace file was not created")
    }
    Write-VerificationLog
}

Write-Host "Native shell verification output:" $OutputRoot
