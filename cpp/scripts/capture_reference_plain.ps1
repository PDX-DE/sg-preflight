param(
    [string]$GameExe = "",
    [string]$WorkingDirectory = "",
    [string]$CaptureRoot = "",
    [int]$MaxDurationSeconds = 120,
    [int]$IntervalSeconds = 5,
    [int]$VideoSeconds = 60,
    [string[]]$GameArgs = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$cppRoot = Resolve-Path -LiteralPath (Join-Path $scriptRoot "..")
$repoRoot = Resolve-Path -LiteralPath (Join-Path $cppRoot "..")

function Resolve-FirstExistingPath {
    param([string[]]$Candidates)

    foreach ($candidate in $Candidates) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return ""
}

function Resolve-Game {
    if (-not [string]::IsNullOrWhiteSpace($GameExe)) {
        return Resolve-FirstExistingPath -Candidates @($GameExe)
    }

    return ""
}

function Resolve-Ffmpeg {
    $command = Get-Command ffmpeg.exe -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    return ""
}

function Save-DesktopScreenshot {
    param([string]$Path)

    $bounds = [System.Windows.Forms.SystemInformation]::VirtualScreen
    $bitmap = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.CopyFromScreen($bounds.Left, $bounds.Top, 0, 0, $bounds.Size)
        $bitmap.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
    }
    finally {
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}

if ([string]::IsNullOrWhiteSpace($CaptureRoot)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $CaptureRoot = Join-Path $repoRoot "out\reference-captures\plain-$stamp"
}

$CaptureRoot = [System.IO.Path]::GetFullPath($CaptureRoot)
$screensRoot = Join-Path $CaptureRoot "screens"
$summaryPath = Join-Path $CaptureRoot "plain-reference-summary.json"
$game = Resolve-Game
$ffmpeg = Resolve-Ffmpeg

if ([string]::IsNullOrWhiteSpace($game)) {
    throw "Reference application not found. Pass -GameExe with the reference application path."
}

if ([string]::IsNullOrWhiteSpace($WorkingDirectory)) {
    $WorkingDirectory = Split-Path -Parent $game
}

$MaxDurationSeconds = [Math]::Max(1, $MaxDurationSeconds)
$IntervalSeconds = [Math]::Max(1, $IntervalSeconds)
$VideoSeconds = [Math]::Max(1, [Math]::Min($VideoSeconds, $MaxDurationSeconds))

New-Item -ItemType Directory -Force -Path $screensRoot | Out-Null

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

Write-Host "SGFX plain reference capture fallback"
Write-Host "Reference application: $game"
Write-Host "Working dir: $WorkingDirectory"
Write-Host "Capture root: $CaptureRoot"
Write-Host "Screenshot interval: $IntervalSeconds second(s), max duration: $MaxDurationSeconds second(s)"
Write-Host "Clean-room line: captures are study evidence only; do not ship ripped assets; do not use Ghidra."
Write-Host ""
Write-Host "Fallback flow:"
Write-Host "1. Let this script launch the game."
Write-Host "2. Navigate to title/world-map views while it captures desktop stills."
Write-Host "3. Close the game when enough evidence is visible."
Write-Host ""

$videoPath = Join-Path $CaptureRoot "desktop-slow.mp4"
$videoProcess = $null
if (-not [string]::IsNullOrWhiteSpace($ffmpeg)) {
    $ffmpegArgs = @(
        "-y",
        "-f", "gdigrab",
        "-framerate", "15",
        "-i", "desktop",
        "-t", "$VideoSeconds",
        $videoPath
    )
    Write-Host "Starting ffmpeg desktop video capture: $videoPath"
    $videoProcess = Start-Process -FilePath $ffmpeg -ArgumentList $ffmpegArgs -PassThru -WindowStyle Hidden
}
else {
    Write-Host "ffmpeg.exe not found; recording PNG stills only."
}

$gameStart = @{
    FilePath = $game
    WorkingDirectory = $WorkingDirectory
    PassThru = $true
}
if ($GameArgs.Count -gt 0) {
    $gameStart.ArgumentList = $GameArgs
}
$gameProcess = Start-Process @gameStart
$start = Get-Date
$screenshots = @()
$index = 0

while ($true) {
    $gameProcess.Refresh()
    $elapsed = ((Get-Date) - $start).TotalSeconds
    if ($gameProcess.HasExited -or $elapsed -ge $MaxDurationSeconds) {
        break
    }

    $path = Join-Path $screensRoot ("plain-reference-{0:D3}.png" -f $index)
    Save-DesktopScreenshot -Path $path
    $screenshots += $path
    Write-Host "Saved screenshot: $path"
    $index += 1
    Start-Sleep -Seconds $IntervalSeconds
}

$gameProcess.Refresh()
$gameStillRunning = -not $gameProcess.HasExited
if ($gameStillRunning) {
    Write-Warning "Capture max duration reached while the game is still running. Close the game manually when done."
}

if ($videoProcess) {
    $videoProcess.Refresh()
    if (-not $videoProcess.HasExited) {
        Wait-Process -Id $videoProcess.Id -Timeout ($VideoSeconds + 5) -ErrorAction SilentlyContinue
        $videoProcess.Refresh()
    }
}

$videoExists = Test-Path -LiteralPath $videoPath -PathType Leaf
$videoBytes = 0
if ($videoExists) {
    $videoBytes = (Get-Item -LiteralPath $videoPath).Length
}

$summary = [ordered]@{
    capture_root = $CaptureRoot
    screens_root = $screensRoot
    game_exe = $game
    working_directory = $WorkingDirectory
    max_duration_seconds = $MaxDurationSeconds
    interval_seconds = $IntervalSeconds
    screenshot_count = $screenshots.Count
    screenshots = $screenshots
    ffmpeg = $ffmpeg
    video_path = $(if ($videoExists) { $videoPath } else { "" })
    video_bytes = $videoBytes
    game_still_running = $gameStillRunning
    clean_room = "Plain screenshots/video are output-observation study evidence only; no ripped assets in SGFX build; no Ghidra."
}
$summary | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $summaryPath -Encoding UTF8

Write-Host ""
Write-Host "Plain reference summary: $summaryPath"
Write-Host "Saved $($screenshots.Count) screenshot(s)."
if ($videoExists) {
    Write-Host "Saved video: $videoPath ($videoBytes bytes)"
}
