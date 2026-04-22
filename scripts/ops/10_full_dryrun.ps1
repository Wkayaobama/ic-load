# 10_full_dryrun — runner --dry-run --enable-post-gold × 5 entities, PARALLEL.
# Emits artifacts/ops/10_full_dryrun_<entity>.csv from the run artifact JSON.
$ErrorActionPreference = "Stop"

$entities = @('company', 'contact', 'opportunity', 'communication', 'case')
$outDir = "artifacts/ops"
New-Item -Path $outDir -ItemType Directory -Force | Out-Null

$results = $entities | ForEach-Object -ThrottleLimit 5 -Parallel {
    $e   = $_
    $out = "artifacts/ops/10_full_dryrun_$e.csv"
    $log = "artifacts/ops/10_full_dryrun_$e.log"

    $env:ICALPS_PGHOST     = $using:env:ICALPS_PGHOST
    $env:ICALPS_PGUSER     = $using:env:ICALPS_PGUSER
    $env:ICALPS_PGPASSWORD = $using:env:ICALPS_PGPASSWORD
    $env:ICALPS_PGPORT     = $using:env:ICALPS_PGPORT
    $env:ICALPS_PGDATABASE = $using:env:ICALPS_PGDATABASE

    python -m pipeline.runner --entity $e --dry-run --enable-post-gold *>$log
    $runnerExit = $LASTEXITCODE

    python -c @"
import csv, json, sys, glob
entity = '$e'
files = sorted(glob.glob(f'artifacts/pipeline_run_{entity}_*.json'))
if not files: sys.stderr.write('no artifact\n'); sys.exit(2)
data = json.load(open(files[-1]))
w = csv.writer(sys.stdout)
w.writerow(['stage','status','reason'])
for h in data.get('history', []):
    w.writerow([h.get('to',''), h.get('status',''), (h.get('details') or {}).get('reason','')])
"@ > $out

    [pscustomobject]@{ entity = $e; runner_exit = $runnerExit; csv = $out }
}

$results | Format-Table | Out-String | Write-Host

$bad = $results | Where-Object { $_.runner_exit -ne 0 -and -not (Test-Path $_.csv) }
if ($bad) {
    Write-Host "full_dryrun failed for: $($bad.entity -join ',')" -ForegroundColor Red
    exit 1
}
Write-Host "full_dryrun csvs: $outDir/10_full_dryrun_<entity>.csv" -ForegroundColor Green
exit 0
