# 01_static — Python import + parse check. No DB.
# Emits artifacts/ops/01_static.csv: module,status,error
$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path "$PSScriptRoot\..\..")

$out = "artifacts/ops/01_static.csv"
New-Item -Path (Split-Path $out) -ItemType Directory -Force | Out-Null

python -c @'
import csv, sys
modules = [
    "pipeline.state",
    "pipeline.runner",
    "pipeline.hooks.pg_functions",
    "pipeline.hooks._primitives",
    "pipeline.silver",
    "pipeline.bronze",
    "pipeline.gold",
    "pipeline.associations",
    "pipeline.dedupe",
    "pipeline.sync",
    "context.config",
    "context.db",
    "sql.render",
]
rows = []
fail = 0
for m in modules:
    try:
        __import__(m)
        rows.append((m, "ok", ""))
    except Exception as exc:
        rows.append((m, "fail", str(exc).replace("\n", " ")))
        fail += 1

w = csv.writer(sys.stdout)
w.writerow(["module", "status", "error"])
for r in rows: w.writerow(r)
sys.stderr.write(f"static: {len(modules)-fail} ok, {fail} fail\n")
sys.exit(1 if fail else 0)
'@ > $out

$exit = $LASTEXITCODE
Write-Host "static csv: $out (exit $exit)" -ForegroundColor $(if ($exit -eq 0) { "Green" } else { "Red" })
exit $exit
