# 10b_preview — runner --preview × 5 entities, PARALLEL.
#
# Read-only simulation of gold upsert + association bridge: executes the
# SELECT portion of each rendered SQL, writes candidate-row CSVs to
# artifacts/ops/. No hubspot.* writes.
#
# Per entity, emits:
#   gold_preview_<entity>.csv                         (what would be INSERT/UPDATEd in hubspot.<table>)
#   gold_preview_engagement_<type>.csv   (for comm)   (one per engagement type)
#   assoc_preview_<comm>_<target>.csv    (for comm)   (one per association pattern)
#
# Also emits per-entity run log: 10b_preview_<entity>.log
#
# Prereqs (expected to have passed already):
#   04_dry_run.ps1       runner stages wire up
#   05_probe_pre.ps1     baseline staging schema
#   06_silver.ps1        staging.stg_*_normalised populated
#   07_dbt.ps1           staging.fct_communication_* populated (needed for engagement+assoc preview)
#
# Skipping this stage is safe — it's a preview check, not a data mutation.
$ErrorActionPreference = "Stop"
$root = Resolve-Path "$PSScriptRoot\..\.."
Set-Location $root

# Cap BLAS threads per subprocess — see 04_dry_run.ps1 header for rationale.
$env:OPENBLAS_NUM_THREADS = "1"
$env:MKL_NUM_THREADS      = "1"
$env:OMP_NUM_THREADS      = "1"
$env:NUMEXPR_NUM_THREADS  = "1"

$entities = @('company', 'contact', 'opportunity', 'communication', 'case')
$outDir   = "artifacts/ops"
New-Item -Path $outDir -ItemType Directory -Force | Out-Null

$results = $entities | ForEach-Object -ThrottleLimit 5 -Parallel {
    $e = $_
    Set-Location $using:root
    $env:ICALPS_PGHOST     = $using:env:ICALPS_PGHOST
    $env:ICALPS_PGUSER     = $using:env:ICALPS_PGUSER
    $env:ICALPS_PGPASSWORD = $using:env:ICALPS_PGPASSWORD
    $env:ICALPS_PGPORT     = $using:env:ICALPS_PGPORT
    $env:ICALPS_PGDATABASE = $using:env:ICALPS_PGDATABASE

    $log = "artifacts/ops/10b_preview_$e.log"
    # --preview skips --approve-gold gate (SELECT only) and the dbt stage is
    # re-run as dry-run to avoid double-execution. --enable-post-gold ensures
    # the assoc_preview path fires for communication.
    # --skip-validation bypasses STOP-level silver checks since 07_dbt passed.
    uv run python -m pipeline.runner --entity $e --preview --enable-post-gold --skip-validation *>$log
    $runnerExit = $LASTEXITCODE

    # Count CSVs produced for this entity
    $csvs = Get-ChildItem "artifacts/ops" -Filter "gold_preview_*.csv" -ErrorAction SilentlyContinue
    if ($e -eq 'communication') {
        $csvs += Get-ChildItem "artifacts/ops" -Filter "assoc_preview_*.csv" -ErrorAction SilentlyContinue
    }

    [pscustomobject]@{
        entity      = $e
        runner_exit = $runnerExit
        csv_count   = ($csvs | Measure-Object).Count
        log         = $log
    }
}

$results | Format-Table -AutoSize | Out-String | Write-Host

$bad = $results | Where-Object { $_.runner_exit -ne 0 }
if ($bad) {
    foreach ($b in $bad) {
        Write-Host "preview FAIL: $($b.entity)  runner=$($b.runner_exit)  see $($b.log)" -ForegroundColor Red
    }
    exit 1
}

$totalCsvs = (Get-ChildItem $outDir -Filter "gold_preview_*.csv" -ErrorAction SilentlyContinue | Measure-Object).Count
$totalCsvs += (Get-ChildItem $outDir -Filter "assoc_preview_*.csv" -ErrorAction SilentlyContinue | Measure-Object).Count
Write-Host "preview csvs: $outDir/{gold_preview,assoc_preview}_*.csv  ($totalCsvs files)" -ForegroundColor Green
exit 0
