param(
    [string]$ExePath = "",
    [string]$OutputRoot = "",
    [string]$ProfileId = "",
    [string]$ActionId = "",
    [int]$InitialSettleMs = 8000,
    [int]$ScreenSettleMs = 2200,
    [int]$PromptSettleMs = 1000,
    [int]$RunObserveSeconds = 600,
    [int]$RunCompletionTimeoutSeconds = 30,
    [int]$CaptureTimeoutSeconds = 20
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
if ($ProfileId) {
    $launchArgs += @("--profile", $ProfileId)
}
if ($ActionId) {
    $launchArgs += @("--action", $ActionId)
}
$process = $null
$previousTraceEnv = $env:SG_PREFLIGHT_NATIVE_TRACE_FILE
$previousCaptureEnv = $env:SG_PREFLIGHT_NATIVE_CAPTURE_DIR
$env:SG_PREFLIGHT_NATIVE_TRACE_FILE = $tracePath
$env:SG_PREFLIGHT_NATIVE_CAPTURE_DIR = $OutputRoot

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
    $targetPath = Join-Path $OutputRoot "$Name.png"
    $requestPath = Join-Path $OutputRoot "capture-request.txt"

    if (Test-Path $targetPath) {
        Remove-Item -LiteralPath $targetPath -Force
    }
    if (Test-Path $requestPath) {
        Remove-Item -LiteralPath $requestPath -Force
    }

    Set-Content -Path $requestPath -Value $Name -Encoding ASCII -NoNewline
    $deadline = (Get-Date).AddSeconds($CaptureTimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Path $targetPath) {
            $targetItem = Get-Item -LiteralPath $targetPath
            if ($targetItem.Length -gt 0) {
                $log.Add("[$Name] screenshot: $targetPath")
                $log.Add("[$Name] bytes: $($targetItem.Length)")
                $log.Add("")
                return
            }
        }
        Start-Sleep -Milliseconds 120
    }

    throw "Timed out waiting for native screenshot $targetPath"
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

function Wait-ForAnyTracePattern {
    param(
        [string]$Path,
        [string[]]$Patterns,
        [int]$TimeoutSeconds = 12
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $text = Get-TraceText -Path $Path
        foreach ($pattern in $Patterns) {
            if ($text -match [regex]::Escape($pattern)) {
                $log.Add("[trace] matched: $pattern")
                return $pattern
            }
        }
        Start-Sleep -Milliseconds 150
    }

    $log.Add("[trace] missing any: $($Patterns -join ' | ')")
    return ""
}

try {
    $process = Start-Process -FilePath $ExePath -ArgumentList $launchArgs -WorkingDirectory $repoRoot -PassThru
    Wait-ForMainWindow -TargetProcess $process
    Start-Sleep -Milliseconds $InitialSettleMs
    if (-not (Wait-ForTracePattern -Path $tracePath -Pattern "UI initial_load_complete" -TimeoutSeconds 25)) {
        [void](Wait-ForTracePattern -Path $tracePath -Pattern "UI initial_load_failed" -TimeoutSeconds 2)
    }

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

    if ($RunObserveSeconds -gt 0) {
        $observeDeadline = (Get-Date).AddSeconds($RunObserveSeconds)
        while ((Get-Date) -lt $observeDeadline) {
            Start-Sleep -Seconds 10
            $process.Refresh()
            if ($process.HasExited) {
                break
            }
        }
    }
    Capture-Stage -TargetProcess $process -Name "run_after_observe"

    $runCompleted = Wait-ForTracePattern -Path $tracePath -Pattern "still_running=false" -TimeoutSeconds $RunCompletionTimeoutSeconds
    if ($runCompleted) {
        Send-Key -TargetProcess $process -Keys "{ENTER}" -SettleMs $ScreenSettleMs
        $runAdvancePattern = Wait-ForAnyTracePattern -Path $tracePath -Patterns @(
            "UI screen_change from=RUN to=EVIDENCE",
            "UI screen_change from=RUN to=FILES",
            "UI screen_change from=RUN to=ENV"
        ) -TimeoutSeconds 6

        if ($runAdvancePattern -eq "UI screen_change from=RUN to=EVIDENCE") {
            Capture-Stage -TargetProcess $process -Name "evidence"
            Send-Key -TargetProcess $process -Keys "{ENTER}" -SettleMs $ScreenSettleMs
            [void](Wait-ForAnyTracePattern -Path $tracePath -Patterns @(
                "UI screen_change from=EVIDENCE to=FILES",
                "UI screen_change from=EVIDENCE to=ENV"
            ) -TimeoutSeconds 6)
        }

        if ($runAdvancePattern -in @("UI screen_change from=RUN to=FILES", "UI screen_change from=EVIDENCE to=FILES")) {
            Capture-Stage -TargetProcess $process -Name "files"
            Send-Key -TargetProcess $process -Keys "{ENTER}" -SettleMs $ScreenSettleMs
            [void](Wait-ForTracePattern -Path $tracePath -Pattern "UI screen_change from=FILES to=ENV" -TimeoutSeconds 6)
            $runAdvancePattern = "UI screen_change from=FILES to=ENV"
        }

        if ($runAdvancePattern -in @("UI screen_change from=RUN to=ENV", "UI screen_change from=EVIDENCE to=ENV", "UI screen_change from=FILES to=ENV")) {
            Capture-Stage -TargetProcess $process -Name "environment"
            Send-Key -TargetProcess $process -Keys "{ENTER}" -SettleMs $ScreenSettleMs
            [void](Wait-ForTracePattern -Path $tracePath -Pattern "UI screen_change from=ENV to=STAGES" -TimeoutSeconds 6)
            Capture-Stage -TargetProcess $process -Name "stages"
        }
    } else {
        $log.Add("[flow] run did not complete within $RunCompletionTimeoutSeconds seconds; skipped deeper screen capture")
    }

    if (-not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
        Start-Sleep -Milliseconds 300
    }

    $process = Start-Process -FilePath $ExePath -ArgumentList $launchArgs -WorkingDirectory $repoRoot -PassThru
    Wait-ForMainWindow -TargetProcess $process
    Start-Sleep -Milliseconds $InitialSettleMs
    if (-not (Wait-ForTracePattern -Path $tracePath -Pattern "UI initial_load_complete" -TimeoutSeconds 25)) {
        [void](Wait-ForTracePattern -Path $tracePath -Pattern "UI initial_load_failed" -TimeoutSeconds 2)
    }
    Wait-ForTraceIdle -Path $tracePath

    Capture-Stage -TargetProcess $process -Name "prompt_intro"

    Send-Key -TargetProcess $process -Keys "{ESC}" -SettleMs $PromptSettleMs
    [void](Wait-ForTracePattern -Path $tracePath -Pattern 'UI prompt_open title="QUIT SERGFX"' -TimeoutSeconds 6)
    Capture-Stage -TargetProcess $process -Name "prompt_banner"

    Send-Key -TargetProcess $process -Keys "{ENTER}" -SettleMs $PromptSettleMs
    [void](Wait-ForTracePattern -Path $tracePath -Pattern 'UI prompt_controls_open title="QUIT SERGFX"' -TimeoutSeconds 6)
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
    if ($null -eq $previousCaptureEnv) {
        Remove-Item Env:SG_PREFLIGHT_NATIVE_CAPTURE_DIR -ErrorAction SilentlyContinue
    } else {
        $env:SG_PREFLIGHT_NATIVE_CAPTURE_DIR = $previousCaptureEnv
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
