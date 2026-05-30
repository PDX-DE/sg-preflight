Set-StrictMode -Version Latest

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class SgfxHarnessInput {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);
}
"@

function New-SgfxUiaCondition {
    param(
        [Parameter(Mandatory=$true)][int]$ProcessId,
        [string]$Name = "",
        [string]$AutomationId = ""
    )

    $conditions = @(
        [System.Windows.Automation.PropertyCondition]::new(
            [System.Windows.Automation.AutomationElement]::ProcessIdProperty,
            $ProcessId
        )
    )
    if (-not [string]::IsNullOrWhiteSpace($Name)) {
        $conditions += [System.Windows.Automation.PropertyCondition]::new(
            [System.Windows.Automation.AutomationElement]::NameProperty,
            $Name
        )
    }
    if (-not [string]::IsNullOrWhiteSpace($AutomationId)) {
        $conditions += [System.Windows.Automation.PropertyCondition]::new(
            [System.Windows.Automation.AutomationElement]::AutomationIdProperty,
            $AutomationId
        )
    }

    if ($conditions.Count -eq 1) {
        return $conditions[0]
    }
    return [System.Windows.Automation.AndCondition]::new([System.Windows.Automation.Condition[]]$conditions)
}

function Get-SgfxProcessWindowElement {
    param([Parameter(Mandatory=$true)][int]$ProcessId)

    $root = [System.Windows.Automation.AutomationElement]::RootElement
    $condition = New-SgfxUiaCondition -ProcessId $ProcessId
    $windows = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $condition)
    foreach ($window in $windows) {
        try {
            if ($window.Current.NativeWindowHandle -ne 0) {
                return $window
            }
        } catch {
        }
    }
    return $null
}

function Wait-SgfxUiElement {
    param(
        [Parameter(Mandatory=$true)][int]$ProcessId,
        [System.Windows.Automation.AutomationElement]$Parent = $null,
        [string]$Name = "",
        [string]$AutomationId = "",
        [int]$TimeoutSeconds = 30,
        [System.Windows.Automation.TreeScope]$Scope = [System.Windows.Automation.TreeScope]::Descendants
    )

    if ([string]::IsNullOrWhiteSpace($Name) -and [string]::IsNullOrWhiteSpace($AutomationId)) {
        throw "Wait-SgfxUiElement needs Name or AutomationId."
    }

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastError = ""
    while ((Get-Date) -lt $deadline) {
        try {
            $searchRoot = $Parent
            if ($null -eq $searchRoot) {
                $searchRoot = Get-SgfxProcessWindowElement -ProcessId $ProcessId
            }
            if ($null -ne $searchRoot) {
                $condition = New-SgfxUiaCondition -ProcessId $ProcessId -Name $Name -AutomationId $AutomationId
                $element = $searchRoot.FindFirst($Scope, $condition)
                if ($null -ne $element) {
                    return $element
                }
            }
        } catch {
            $lastError = $_.Exception.Message
        }
        Start-Sleep -Milliseconds 250
    }

    $selector = @()
    if (-not [string]::IsNullOrWhiteSpace($Name)) { $selector += "Name='$Name'" }
    if (-not [string]::IsNullOrWhiteSpace($AutomationId)) { $selector += "AutomationId='$AutomationId'" }
    throw "Timed out waiting for UIA element $($selector -join ', ') in process $ProcessId. Last UIA error: $lastError"
}

function Wait-SgfxDependencySetupPanel {
    param(
        [Parameter(Mandatory=$true)][int]$ProcessId,
        [int]$TimeoutSeconds = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastError = ""
    while ((Get-Date) -lt $deadline) {
        try {
            $mainWindow = Get-SgfxProcessWindowElement -ProcessId $ProcessId
            if ($null -ne $mainWindow) {
                $panel = Wait-SgfxUiElement -ProcessId $ProcessId -Parent $mainWindow -Name "Dependency Setup" -TimeoutSeconds 1
                if ($null -ne $panel) {
                    return $panel
                }
            }
        } catch {
            $lastError = $_.Exception.Message
        }
        Start-Sleep -Milliseconds 250
    }
    throw "Timed out re-attaching to the Dependency Setup panel for process $ProcessId. Last UIA error: $lastError"
}

function Wait-SgfxSetupControlsReady {
    param(
        [Parameter(Mandatory=$true)][int]$ProcessId,
        [int]$TimeoutSeconds = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastError = ""
    while ((Get-Date) -lt $deadline) {
        try {
            $panel = Wait-SgfxDependencySetupPanel -ProcessId $ProcessId -TimeoutSeconds 1
            $run = Wait-SgfxUiElement -ProcessId $ProcessId -Parent $panel -Name "Run Setup" -TimeoutSeconds 1
            $cancel = Wait-SgfxUiElement -ProcessId $ProcessId -Parent $panel -Name "Cancel Setup" -TimeoutSeconds 1
            return [pscustomobject]@{
                Panel = $panel
                RunSetup = $run
                CancelSetup = $cancel
                RunSetupEnabled = [bool]$run.Current.IsEnabled
                CancelSetupEnabled = [bool]$cancel.Current.IsEnabled
            }
        } catch {
            $lastError = $_.Exception.Message
        }
        Start-Sleep -Milliseconds 250
    }
    throw "Timed out waiting for Dependency Setup controls after re-attach. Last UIA error: $lastError"
}

function Invoke-SgfxUiElement {
    param(
        [Parameter(Mandatory=$true)][int]$ProcessId,
        [System.Windows.Automation.AutomationElement]$Parent = $null,
        [string]$Name = "",
        [string]$AutomationId = "",
        [int]$TimeoutSeconds = 30
    )

    $element = Wait-SgfxUiElement -ProcessId $ProcessId -Parent $Parent -Name $Name -AutomationId $AutomationId -TimeoutSeconds $TimeoutSeconds
    try {
        $pattern = $element.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
        $pattern.Invoke()
        return [pscustomobject]@{ method = "uia_invoke"; name = $Name; automation_id = $AutomationId }
    } catch {
        try {
            $pattern = $element.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
            $pattern.Toggle()
            return [pscustomobject]@{ method = "uia_toggle"; name = $Name; automation_id = $AutomationId }
        } catch {
            $rect = $element.Current.BoundingRectangle
            if ($rect.Width -le 0 -or $rect.Height -le 0) {
                throw "UIA element is present but has no clickable bounds."
            }
            $window = Get-SgfxProcessWindowElement -ProcessId $ProcessId
            if ($null -ne $window) {
                [void][SgfxHarnessInput]::SetForegroundWindow([IntPtr]$window.Current.NativeWindowHandle)
            }
            $x = [int]($rect.Left + ($rect.Width / 2))
            $y = [int]($rect.Top + ($rect.Height / 2))
            [void][SgfxHarnessInput]::SetCursorPos($x, $y)
            [SgfxHarnessInput]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
            Start-Sleep -Milliseconds 80
            [SgfxHarnessInput]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
            return [pscustomobject]@{ method = "mouse_click_fallback"; name = $Name; automation_id = $AutomationId; x = $x; y = $y }
        }
    }
}

function Invoke-SgfxSetupRunButton {
    param(
        [Parameter(Mandatory=$true)][int]$ProcessId,
        [int]$TimeoutSeconds = 30
    )

    $controls = Wait-SgfxSetupControlsReady -ProcessId $ProcessId -TimeoutSeconds $TimeoutSeconds
    $result = Invoke-SgfxUiElement -ProcessId $ProcessId -Parent $controls.Panel -Name "Run Setup" -TimeoutSeconds $TimeoutSeconds
    return [pscustomobject]@{ invoke = $result; before = $controls }
}

function Wait-SgfxSetupControlsAfterDialogClose {
    param(
        [Parameter(Mandatory=$true)][int]$ProcessId,
        [int]$TimeoutSeconds = 30
    )

    return Wait-SgfxSetupControlsReady -ProcessId $ProcessId -TimeoutSeconds $TimeoutSeconds
}
