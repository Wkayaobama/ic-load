# 04_dry_run — runner --dry-run × 5 entities in PARALLEL.
# Reads each run's artifact JSON and emits per-entity CSV of stage transitions.
# Emits artifacts/ops/04_dry_run_<entity>.csv: stage,status,reason
$ErrorActionPreference = "Stop"
$root = Resolve-Path "$PSScriptRoot\..\.."
Set-Location $root

$entities = @('company', 'contact', 'opportunity', 'communication', 'case')
$outDir   = "artifacts/ops"
New-Item -Path $outDir -ItemType Directory -Force | Out-Null

$results = $entities | ForEach-Object -ThrottleLimit 5 -Parallel {
    $e = $_
    # Child runspace needs its own cwd + env propagation.
    Set-Location $using:root
    $env:ICALPS_PGHOST     = $using:env:ICALPS_PGHOST
    $env:ICALPS_PGUSER     = $using:env:ICALPS_PGUSER
    $env:ICALPS_PGPASSWORD = $using:env:ICALPS_PGPASSWORD
    $env:ICALPS_PGPORT     = $using:env:ICALPS_PGPORT
    $env:ICALPS_PGDATABASE = $using:env:ICALPS_PGDATABASE

    $out = "artifacts/ops/04_dry_run_$e.csv"
    $log = "artifacts/ops/04_dry_run_$e.log"

    python -m pipeline.runner --entity $e --dry-run *>$log
    $runnerExit = $LASTEXITCODE

    # Parse the most recent artifact — only if runner actually produced one.
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

# A stage is bad if the runner crashed OR we couldn't parse its artifact.
$bad = $results | Where-Object { $_.runner_exit -ne 0 -or $_.parse_exit -ne 0 }
if ($bad) {
    foreach ($b in $bad) {
        Write-Host "dry-run FAIL: $($b.entity)  runner=$($b.runner_exit)  parse=$($b.parse_exit)  see $($b.log)" -ForegroundColor Red
    }
    exit 1
}

Write-Host "dry-run csvs: $outDir/04_dry_run_<entity>.csv" -ForegroundColor Green
exit 0
