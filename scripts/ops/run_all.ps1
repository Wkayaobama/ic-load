# run_all — driver. Serial stage execution, parallelism inside individual stages.
# Additive-only: never modifies pipeline code; each stage shells out to Python / dbt / psql.
#
# Usage
# -----
#   .\scripts\ops\run_all.ps1
#   .\scripts\ops\run_all.ps1 -StartAt 05_probe_pre    # resume from a stage
#   .\scripts\ops\run_all.ps1 -StopAt  07_dbt          # stop after a stage
#   .\scripts\ops\run_all.ps1 -Force                   # ignore .done sentinels
#   .\scripts\ops\run_all.ps1 -IncludeLoad             # allow 11_load to run (still needs its own -Entity -Confirm)
#
# Sentinel semantics
# ------------------
#   On success, each stage writes artifacts/ops/<stage>.done with an ISO timestamp.
#   On re-run, stages with a sentinel are SKIPPED unless -Force.
#   To retry a single stage: delete its .done file, or pass -StartAt <stage>.
param(
    [string]$StartAt,
    [string]$StopAt,
    [switch]$Force,
    [switch]$IncludeLoad
)
$ErrorActionPreference = "Stop"

# Pin cwd at the ic-load project root so every stage can import context/ and
# pipeline/ regardless of where the driver was invoked from.
Set-Location (Resolve-Path "$PSScriptRoot\..\..")

. "$PSScriptRoot\_env.ps1"

New-Item -Path "artifacts/ops" -ItemType Directory -Force | Out-Null

$stages = Get-ChildItem "$PSScriptRoot\[0-9][0-9]_*.ps1" | Sort-Object Name
$total  = $stages.Count
$index  = 0

foreach ($stage in $stages) {
    $index++
    $name = $stage.BaseName

    if ($name -eq '11_load' -and -not $IncludeLoad) {
        Write-Host "[${index}/${total}]  SKIP  $name   (use -IncludeLoad to enable)" -ForegroundColor DarkGray
        continue
    }

    if ($StartAt -and ($name -lt $StartAt)) {
        Write-Host "[${index}/${total}]  SKIP  $name   (StartAt=$StartAt)" -ForegroundColor DarkGray
        continue
    }

    $sentinel = "artifacts/ops/$name.done"
    if ((Test-Path $sentinel) -and -not $Force) {
        Write-Host "[${index}/${total}]  SKIP  $name   (sentinel present, -Force to override)" -ForegroundColor DarkGray
        continue
    }

    Write-Host ""
    Write-Host "[${index}/${total}]  >>>  $name" -ForegroundColor Cyan
    $t0 = Get-Date
    & $stage.FullName
    $exit = $LASTEXITCODE
    $dur  = (Get-Date) - $t0

    if ($exit -ne 0) {
        Write-Host "[${index}/${total}]  FAIL  $name   (exit $exit, $([int]$dur.TotalSeconds)s)" -ForegroundColor Red
        exit 1
    }

    Set-Content -Path $sentinel -Value "ok $(Get-Date -Format o) duration_s=$([int]$dur.TotalSeconds)"
    Write-Host "[${index}/${total}]  OK    $name   ($([int]$dur.TotalSeconds)s)" -ForegroundColor Green

    if ($StopAt -and ($name -eq $StopAt)) {
        Write-Host "Stopping at $StopAt per flag." -ForegroundColor Yellow
        break
    }
}

Write-Host ""
Write-Host "ALL STAGES OK" -ForegroundColor Green
