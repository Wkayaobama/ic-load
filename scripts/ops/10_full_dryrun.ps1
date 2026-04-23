# 10_full_dryrun — runner --dry-run --enable-post-gold × 5 entities, PARALLEL.
# Emits artifacts/ops/10_full_dryrun_<entity>.csv from the run artifact JSON.
$ErrorActionPreference = "Stop"
$root = Resolve-Path "$PSScriptRoot\..\.."
Set-Location $root

$entities = @('company', 'contact', 'opportunity', 'communication', 'case')
$outDir = "artifacts/ops"
New-Item -Path $outDir -ItemType Directory -Force | Out-Null

$results = $entities | ForEach-Object -ThrottleLimit 5 -Parallel {
    $e = $_
    Set-Location $using:root
    $env:ICALPS_PGHOST     = $using:env:ICALPS_PGHOST
    $env:ICALPS_PGUSER     = $using:env:ICALPS_PGUSER
    $env:ICALPS_PGPASSWORD = $using:env:ICALPS_PGPASSWORD
    $env:ICALPS_PGPORT     = $using:env:ICALPS_PGPORT
    $env:ICALPS_PGDATABASE = $using:env:ICALPS_PGDATABASE

    $out = "artifacts/ops/10_full_dryrun_$e.csv"
    $log = "artifacts/ops/10_full_dryrun_$e.log"

    python -m pipeline.runner --entity $e --dry-run --enable-post-gold *>$log
    $runnerExit = $LASTEXITCODE

    python -c @"
import csv, json, sys, glob
entity = '$e'
files = sorted(glob.glob(f'artifacts/pipeline_run_{entity}_*.json'))
if not files: sys.stderr.write(f'{entity}: no artifact\n'); sys.exit(2)
data = json.load(open(files[-1]))
w = csv.writer(sys.stdout)
w.writerow(['stage','status','reason'])
for h in data.get('history', []):
    w.writerow([h.get('to',''), h.get('status',''), (h.get('details') or {}).get('reason','')])
"@ > $out
    $parseExit = $LASTEXITCODE

    [pscustomobject]@{
        entity      = $e
        runner_exit = $runnerExit
        parse_exit  = $parseExit
        log         = $log
        csv         = $out
    }
}

$results | Format-Table -AutoSize | Out-String | Write-Host

$bad = $results | Where-Object { $_.runner_exit -ne 0 -or $_.parse_exit -ne 0 }
if ($bad) {
    foreach ($b in $bad) {
        Write-Host "full_dryrun FAIL: $($b.entity)  runner=$($b.runner_exit)  parse=$($b.parse_exit)  see $($b.log)" -ForegroundColor Red
    }
    exit 1
}

Write-Host "full_dryrun csvs: $outDir/10_full_dryrun_<entity>.csv" -ForegroundColor Green
exit 0
