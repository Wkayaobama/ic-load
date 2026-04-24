# 07_dbt — dbt deps + dbt build (communication only today).
# Emits artifacts/ops/07_dbt.csv from target/run_results.json:
#   unique_id,status,rows_affected,execution_time
$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path "$PSScriptRoot\..\..")

$out = "artifacts/ops/07_dbt.csv"
New-Item -Path (Split-Path $out) -ItemType Directory -Force | Out-Null

Push-Location dbt
try {
    uv run --extra dbt dbt deps
    if ($LASTEXITCODE -ne 0) { throw "dbt deps failed (exit $LASTEXITCODE)" }

    uv run --extra dbt dbt build
    $dbtExit = $LASTEXITCODE
} finally {
    Pop-Location
}

# Parse run_results regardless of dbt exit — partial failures should still be visible.
uv run python -c @'
import csv, json, sys, os
path = "dbt/target/run_results.json"
if not os.path.exists(path):
    sys.stderr.write("no run_results.json\n"); sys.exit(2)
data = json.load(open(path))
w = csv.writer(sys.stdout)
w.writerow(["unique_id","status","rows_affected","execution_time_s"])
for r in data.get("results", []):
    w.writerow([
        r.get("unique_id",""),
        r.get("status",""),
        (r.get("adapter_response") or {}).get("rows_affected",""),
        round(r.get("execution_time", 0.0), 2),
    ])
'@ > $out

Write-Host "dbt csv: $out (dbt exit $dbtExit)" -ForegroundColor $(if ($dbtExit -eq 0) { "Green" } else { "Yellow" })
exit $dbtExit
