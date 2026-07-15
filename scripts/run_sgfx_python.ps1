#Requires -Version 5.1
<#
Runs SGFX acceptance commands with a pinned CPython interpreter.

Resolution order: -Python parameter, SGFX_PYTHON environment variable, then
<repo>\.venv\Scripts\python.exe. Refuses the Microsoft Store python stub and
anything below CPython 3.10, prints the resolved interpreter to stderr as
evidence, and forwards the remaining arguments with -B so no bytecode is
written into source or bundle trees.
#>
[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$Python,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if (-not $Arguments -or $Arguments.Count -eq 0) {
    [Console]::Error.WriteLine('Usage: run_sgfx_python.ps1 [-Python <path>] <python arguments...>')
    exit 64
}

if (-not $Python) { $Python = $env:SGFX_PYTHON }
if (-not $Python) {
    $repoRoot = Split-Path -Parent $PSScriptRoot
    $Python = Join-Path $repoRoot '.venv\Scripts\python.exe'
}

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    [Console]::Error.WriteLine("SGFX Python not found: $Python")
    [Console]::Error.WriteLine('Create the repo .venv or set SGFX_PYTHON to a CPython 3.10+ interpreter.')
    exit 78
}
$resolved = (Resolve-Path -LiteralPath $Python).ProviderPath

if ($resolved -match '\\WindowsApps\\') {
    [Console]::Error.WriteLine("Refusing the Microsoft Store python stub: $resolved")
    exit 78
}

$versionText = & $resolved -c "import sys; print('.'.join(map(str, sys.version_info[:3])))" 2>$null
if ($LASTEXITCODE -ne 0 -or -not $versionText) {
    [Console]::Error.WriteLine("Interpreter probe failed: $resolved")
    exit 78
}
$version = [Version]([string]($versionText | Select-Object -First 1)).Trim()
if ($version -lt [Version]'3.10') {
    [Console]::Error.WriteLine("CPython 3.10+ required, found ${version}: $resolved")
    exit 78
}

[Console]::Error.WriteLine("sgfx-python $version $resolved")
$env:PYTHONDONTWRITEBYTECODE = '1'
& $resolved -B @Arguments
exit $LASTEXITCODE
