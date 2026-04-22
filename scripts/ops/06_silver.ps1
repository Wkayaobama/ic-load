# 06_silver — run SilverNormaliser.normalise_<entity> in PARALLEL.
# Emits artifacts/ops/06_silver_<entity>.csv: table,row_count,distinct_pk,null_pk
$ErrorActionPreference = "Stop"

$entities = @('company', 'contact', 'opportunity', 'communication')
$outDir = "artifacts/ops"
New-Item -Path $outDir -ItemType Directory -Force | Out-Null

# Map entity → (normalised table, primary key column)
# Matches load_entity_translation_contract() in context/config.py
$meta = @{
    'company'       = @{ table = 'staging.stg_company_normalised';       pk = 'comp_companyid'        }
    'contact'       = @{ table = 'staging.stg_contact_normalised';       pk = 'pers_personid'         }
    'opportunity'   = @{ table = 'staging.stg_opportunity_normalised';   pk = 'oppo_opportunityid'    }
    'communication' = @{ table = 'staging.stg_communication_normalised'; pk = 'comm_communicationid'  }
}

$results = $entities | ForEach-Object -ThrottleLimit 4 -Parallel {
    $e     = $_
    $table = ($using:meta)[$e].table
    $pk    = ($using:meta)[$e].pk
    $out   = "artifacts/ops/06_silver_$e.csv"

    # Propagate DB env
    $env:ICALPS_PGHOST     = $using:env:ICALPS_PGHOST
    $env:ICALPS_PGUSER     = $using:env:ICALPS_PGUSER
    $env:ICALPS_PGPASSWORD = $using:env:ICALPS_PGPASSWORD
    $env:ICALPS_PGPORT     = $using:env:ICALPS_PGPORT
    $env:ICALPS_PGDATABASE = $using:env:ICALPS_PGDATABASE

    # Run normaliser then snapshot table health.
    python -c @"
import csv, sys
from pipeline.silver import SilverNormaliser
from context.db import get_connection

normaliser = SilverNormaliser()
method = 'normalise_' + '$e'
getattr(normaliser, method)()

schema, table = '$table'.split('.')
pk = '$pk'
with get_connection() as conn:
    with conn.cursor() as cur:
        cur.execute(f'SELECT COUNT(*) FROM {schema}.{table}')
        rc = cur.fetchone()[0]
        cur.execute(f'SELECT COUNT(DISTINCT {pk}), COUNT(*) FILTER (WHERE {pk} IS NULL) FROM {schema}.{table}')
        distinct_pk, null_pk = cur.fetchone()

w = csv.writer(sys.stdout)
w.writerow(['table','row_count','distinct_pk','null_pk'])
w.writerow([f'{schema}.{table}', rc, distinct_pk, null_pk])
"@ > $out

    [pscustomobject]@{ entity = $e; exit = $LASTEXITCODE; csv = $out }
}

$results | Format-Table | Out-String | Write-Host

$bad = $results | Where-Object exit -ne 0
if ($bad) {
    Write-Host "silver failed for: $($bad.entity -join ',')" -ForegroundColor Red
    exit 1
}
Write-Host "silver csvs: $outDir/06_silver_<entity>.csv" -ForegroundColor Green
exit 0
