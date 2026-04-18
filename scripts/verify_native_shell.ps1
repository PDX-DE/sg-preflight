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
}
"@

$log = New-Object System.Collections.Generic.List[string]
$log.Add("Native shell verification")
$log.Add("Created: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
$log.Add("Executable: $ExePath")
$log.Add("Output: $OutputRoot")
$log.Add("")

$shell = New-Object -ComObject WScript.Shell
$launchArgs = @("--windowed", "--width", "1280", "--height", "720")
$process = $null

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
    $bitmap = New-Object System.Drawing.Bitmap $width, $height
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.CopyFromScreen($rect.Left, $rect.Top, 0, 0, $bitmap.Size)
        $targetPath = Join-Path $OutputRoot "$Name.png"
        $bitmap.Save($targetPath, [System.Drawing.Imaging.ImageFormat]::Png)
        $log.Add("[$Name] screenshot: $targetPath")
        $log.Add("[$Name] bounds: left=$($rect.Left) top=$($rect.Top) width=$width height=$height")
        $log.Add("")
    }
    finally {
        $graphics.Dispose()
        $bitmap.Dispose()
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
    $shell.SendKeys($Keys)
    Start-Sleep -Milliseconds $SettleMs
}

try {
    $process = Start-Process -FilePath $ExePath -ArgumentList $launchArgs -WorkingDirectory $repoRoot -PassThru
    Wait-ForMainWindow -TargetProcess $process
    Start-Sleep -Milliseconds $InitialSettleMs

    Capture-Stage -TargetProcess $process -Name "intro"

    Send-Key -TargetProcess $process -Keys "{ENTER}" -SettleMs $ScreenSettleMs
    Capture-Stage -TargetProcess $process -Name "select"

    Send-Key -TargetProcess $process -Keys "{ENTER}" -SettleMs $ScreenSettleMs
    Capture-Stage -TargetProcess $process -Name "review"

    if (-not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
        Start-Sleep -Milliseconds 300
    }

    $process = Start-Process -FilePath $ExePath -ArgumentList $launchArgs -WorkingDirectory $repoRoot -PassThru
    Wait-ForMainWindow -TargetProcess $process
    Start-Sleep -Milliseconds $InitialSettleMs

    Capture-Stage -TargetProcess $process -Name "prompt_intro"

    Send-Key -TargetProcess $process -Keys "{ESC}" -SettleMs $PromptSettleMs
    Capture-Stage -TargetProcess $process -Name "prompt_banner"

    Send-Key -TargetProcess $process -Keys "{ENTER}" -SettleMs $PromptSettleMs
    Capture-Stage -TargetProcess $process -Name "prompt_choices"

    $quitStart = Get-Date
    Send-Key -TargetProcess $process -Keys "{ENTER}" -SettleMs 100

    $waitDeadline = (Get-Date).AddSeconds(10)
    while (-not $process.HasExited -and (Get-Date) -lt $waitDeadline) {
        Start-Sleep -Milliseconds 100
        $process.Refresh()
    }

    $quitMs = [int]((Get-Date) - $quitStart).TotalMilliseconds
    if (-not $process.HasExited) {
        $log.Add("[close] process did not exit within timeout; forcing shutdown")
        Stop-Process -Id $process.Id -Force
    } else {
        $log.Add("[close] process exited after ${quitMs}ms")
    }
}
finally {
    if (-not $process.HasExited) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
    Write-VerificationLog
}

Write-Host "Native shell verification output:" $OutputRoot
