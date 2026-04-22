# 04_dry_run — runner --dry-run × 5 entities in PARALLEL.
# Reads each run's artifact JSON and emits per-entity CSV of stage transitions.
# Emits artifacts/ops/04_dry_run_<entity>.csv: stage,status,reason
$ErrorActionPreference = "Stop"

$entities = @('company', 'contact', 'opportunity', 'communication', 'case')
$outDir   = "artifacts/ops"
New-Item -Path $outDir -ItemType Directory -Force | Out-Null

$results = $entities | ForEach-Object -ThrottleLimit 5 -Parallel {
    $e = $_
    $out = "artifacts/ops/04_dry_run_$e.csv"
    # stdout/stderr → per-entity log; artifact JSON comes from runner itself
    $log = "artifacts/ops/04_dry_run_$e.log"

    $env:ICALPS_PGHOST     = $using:env:ICALPS_PGHOST
    $env:ICALPS_PGUSER     = $using:env:ICALPS_PGUSER
    $env:ICALPS_PGPASSWORD = $using:env:ICALPS_PGPASSWORD
    $env:ICALPS_PGPORT     = $using:env:ICALPS_PGPORT
    $env:ICALPS_PGDATABASE = $using:env:ICALPS_PGDATABASE

    python -m pipeline.runner --entity $e --dry-run *>$log
    $runnerExit = $LASTEXITCODE

    # Find the most recent artifact for this entity and convert to CSV.
    python -c @"
import csv, json, sys, glob
entity = '$e'
files = sorted(glob.glob(f'artifacts/pipeline_run_{entity}_*.json'))
if not files:
    sys.stderr.write(f'{entity}: no artifact\n'); sys.exit(2)
data = json.load(open(files[-1]))
w = csv.writer(sys.stdout)
w.writerow(['stage','status','reason'])
for h in data.get('history', []):
    details = h.get('details') or {}
    w.writerow([h.get('to',''), h.get('status',''), details.get('reason','')])
"@ > $out

    [pscustomobject]@{ entity = $e; runner_exit = $runnerExit; csv = $out }
}

$results | Format-Table | Out-String | Write-Host

$bad = $results | Where-Object { $_.runner_exit -ne 0 -and -not (Test-Path $_.csv) }
if ($bad) {
    Write-Host "dry-run failed for: $($bad.entity -join ',')" -ForegroundColor Red
    exit 1
}
Write-Host "dry-run csvs: $outDir/04_dry_run_<entity>.csv" -ForegroundColor Green
exit 0
