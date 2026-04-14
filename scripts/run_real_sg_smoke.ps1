param(
    [string]$OutputRoot = ""
)

if (-not $OutputRoot) {
    $OutputRoot = Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..")).Path "out\real-sg-smoke\latest"
}

& (Join-Path $PSScriptRoot "run_real_live_matrix_smoke.ps1") -Cars @("G70") -OutputRoot $OutputRoot
exit $LASTEXITCODE
