# 00_preflight — verify required env vars are present. No side effects.
$ErrorActionPreference = "Stop"

$required = @(
    'ICALPS_PGHOST',
    'ICALPS_PGUSER',
    'ICALPS_PGPASSWORD'
)

$missing = @($required | Where-Object { -not (Get-Item "env:$_" -ErrorAction SilentlyContinue) })

if ($missing.Count -gt 0) {
    Write-Host "MISSING env vars: $($missing -join ', ')" -ForegroundColor Red
    exit 1
}

Write-Host "preflight ok  (host=$env:ICALPS_PGHOST user=$env:ICALPS_PGUSER db=$($env:ICALPS_PGDATABASE))" -ForegroundColor Green
exit 0
