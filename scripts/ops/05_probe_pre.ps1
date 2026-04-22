# 05_probe_pre — baseline schema snapshot BEFORE silver normalisation and dbt.
# Emits artifacts/probe_pre_dbt.csv (the canonical baseline).
$ErrorActionPreference = "Stop"

$out = "artifacts/probe_pre_dbt.csv"
New-Item -Path (Split-Path $out) -ItemType Directory -Force | Out-Null

python scripts/probe_schemas.py --output $out
exit $LASTEXITCODE
