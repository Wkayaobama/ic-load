# Dot-sourced by run_all.ps1. Loads ic-load/.env into $env:* if present,
# and caps BLAS thread pool sizes so parallel stages don't exhaust memory.
#
# Why cap BLAS threads
# --------------------
# pipeline.dedupe imports pandas at module load. Pandas eagerly allocates an
# OpenBLAS thread pool sized to the full CPU count on every process start —
# even when no matrix op runs. With `ForEach-Object -Parallel -ThrottleLimit 5`
# and N cores, 5 simultaneous `uv run python` invocations request 5 × N
# worker threads upfront, which can exceed available RAM and raise
# `OpenBLAS error: Memory allocation still failed after 10 retries`.
# Setting the caps to 1 here forces each subprocess to single-threaded BLAS.
# Pipeline work (SQL, I/O) is unaffected — actual matrix math happens only
# in legacy code paths that aren't on the dry-run/preview critical path.
$env:OPENBLAS_NUM_THREADS = "1"
$env:MKL_NUM_THREADS      = "1"
$env:OMP_NUM_THREADS      = "1"
$env:NUMEXPR_NUM_THREADS  = "1"

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
