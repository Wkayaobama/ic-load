# 08_probe_post — post-dbt schema snapshot + diff against pre.
# Emits artifacts/probe_post_dbt.csv and artifacts/ops/08_diff.csv
#   (8_diff columns: side,schema,table,column,detail — side ∈ {pre_only,post_only,common_changed})
$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path "$PSScriptRoot\..\..")

$pre  = "artifacts/probe_pre_dbt.csv"
$post = "artifacts/probe_post_dbt.csv"
$diff = "artifacts/ops/08_diff.csv"
New-Item -Path (Split-Path $diff) -ItemType Directory -Force | Out-Null

uv run python scripts/probe_schemas.py --output $post
if ($LASTEXITCODE -ne 0) { Write-Host "probe_post failed" -ForegroundColor Red; exit 1 }

if (-not (Test-Path $pre)) {
    Write-Host "no $pre — skipping diff (run 05_probe_pre first)" -ForegroundColor Yellow
    exit 0
}

uv run python -c @"
import csv, sys

def rows(path):
    return list(csv.DictReader(open(path, encoding='utf-8')))

pre  = {(r['schema'], r['table'], r['column']): r for r in rows('$pre')}
post = {(r['schema'], r['table'], r['column']): r for r in rows('$post')}

w = csv.writer(sys.stdout)
w.writerow(['side','schema','table','column','detail'])
for key in sorted(pre.keys() | post.keys()):
    p, q = pre.get(key), post.get(key)
    if   p and not q: w.writerow(['pre_only',  *key, ''])
    elif q and not p: w.writerow(['post_only', *key, ''])
    else:
        changes = []
        for field in ('data_type','is_nullable','row_count','distinct_pk_count','null_pk_count','status'):
            if p.get(field) != q.get(field):
                changes.append(f'{field}:{p.get(field)}->{q.get(field)}')
        if changes:
            w.writerow(['common_changed', *key, ';'.join(changes)])
"@ > $diff

$diffLines = (Get-Content $diff | Measure-Object -Line).Lines
Write-Host "diff csv: $diff ($($diffLines - 1) differences)" -ForegroundColor Green
exit 0
