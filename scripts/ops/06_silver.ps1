# 06_silver — VALIDATE normalised tables exist with data (legacy normaliser disabled).
# Silver normalization is done externally; this step validates stg_*_normalised tables.
# Emits artifacts/ops/06_silver_<entity>.csv: table,row_count,distinct_pk,null_pk
$ErrorActionPreference = "Stop"
$root = Resolve-Path "$PSScriptRoot\..\.."
Set-Location $root

# Cap BLAS threads per subprocess — see 04_dry_run.ps1 header for rationale.
$env:OPENBLAS_NUM_THREADS = "1"
$env:MKL_NUM_THREADS      = "1"
$env:OMP_NUM_THREADS      = "1"
$env:NUMEXPR_NUM_THREADS  = "1"

$entities = @('company', 'contact', 'opportunity', 'communication')
$outDir = "artifacts/ops"
New-Item -Path $outDir -ItemType Directory -Force | Out-Null

# entity → (normalised table, primary key column) — matches
# load_entity_translation_contract() in context/config.py
$meta = @{
    'company'       = @{ table = 'staging.stg_company_normalised';       pk = 'icalps_company_id'    }
    'contact'       = @{ table = 'staging.stg_contact_normalised';       pk = 'icalps_contact_id'    }
    'opportunity'   = @{ table = 'staging.stg_opportunity_normalised';   pk = 'icalps_deal_id'       }
    'communication' = @{ table = 'staging.stg_communication_normalised'; pk = 'comm_communicationid' }
}

$results = $entities | ForEach-Object -ThrottleLimit 4 -Parallel {
    $e     = $_
    Set-Location $using:root
    $env:ICALPS_PGHOST     = $using:env:ICALPS_PGHOST
    $env:ICALPS_PGUSER     = $using:env:ICALPS_PGUSER
    $env:ICALPS_PGPASSWORD = $using:env:ICALPS_PGPASSWORD
    $env:ICALPS_PGPORT     = $using:env:ICALPS_PGPORT
    $env:ICALPS_PGDATABASE = $using:env:ICALPS_PGDATABASE

    $table = ($using:meta)[$e].table
    $pk    = ($using:meta)[$e].pk
    $out   = "artifacts/ops/06_silver_$e.csv"

    # NOTE: Silver normalization already done externally. This step validates tables exist.
    # Legacy SilverNormaliser has schema mismatch with current stg_* tables.
    uv run python -c @"
import csv, sys
from context.db import get_connection

schema, table = '$table'.split('.')
pk = '$pk'
with get_connection() as conn:
    with conn.cursor() as cur:
        cur.execute(f'SELECT COUNT(*) FROM {schema}.{table}')
        rc = cur.fetchone()[0]
        if rc == 0:
            print(f'ERROR: {schema}.{table} has 0 rows', file=sys.stderr)
            sys.exit(1)
        cur.execute(f'SELECT COUNT(DISTINCT {pk}), COUNT(*) FILTER (WHERE {pk} IS NULL) FROM {schema}.{table}')
        distinct_pk, null_pk = cur.fetchone()

w = csv.writer(sys.stdout)
w.writerow(['table','row_count','distinct_pk','null_pk'])
w.writerow([f'{schema}.{table}', rc, distinct_pk, null_pk])
print(f'[06_silver] validated {schema}.{table}: {rc:,} rows, {distinct_pk:,} distinct PKs', file=sys.stderr)
"@ > $out
    $pyExit = $LASTEXITCODE

    [pscustomobject]@{ entity = $e; exit = $pyExit; csv = $out }
}

$results | Format-Table -AutoSize | Out-String | Write-Host

$bad = $results | Where-Object exit -ne 0
if ($bad) {
    Write-Host "silver FAIL for: $($bad.entity -join ',')" -ForegroundColor Red
    exit 1
}
Write-Host "silver csvs: $outDir/06_silver_<entity>.csv" -ForegroundColor Green
exit 0
