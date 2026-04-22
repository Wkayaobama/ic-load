# Dot-sourced by run_all.ps1. Loads ic-load/.env into $env:* if present.
# Safe no-op when .env is absent.

$envFile = Join-Path $PSScriptRoot "..\..\.env"
if (Test-Path $envFile) {
    Get-Content $envFile |
        Where-Object { $_ -notmatch '^\s*#' -and $_ -match '=' } |
        ForEach-Object {
            $key, $value = $_ -split '=', 2
            Set-Item -Path "env:$($key.Trim())" -Value $value.Trim()
        }
    Write-Host "env:  loaded from $envFile" -ForegroundColor DarkGray
} else {
    Write-Host "env:  no .env found — relying on inherited environment" -ForegroundColor DarkGray
}
