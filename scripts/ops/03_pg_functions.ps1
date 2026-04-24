# 03_pg_functions — install 15 pg functions + verify in pg_proc.
# Idempotent (CREATE OR REPLACE / IF NOT EXISTS).
# Emits artifacts/ops/03_pg_functions.csv: schema,function,installed,verified
$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path "$PSScriptRoot\..\..")

$out = "artifacts/ops/03_pg_functions.csv"
New-Item -Path (Split-Path $out) -ItemType Directory -Force | Out-Null

uv run python -c @'
import csv, sys
from pipeline.hooks.pg_functions import install
from context.db import get_connection

# Install
result = install(dry_run=False)
installed_paths = set(result["installed"])

# Verify against pg_proc
with get_connection() as conn:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT n.nspname, p.proname
            FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname IN ('staging', 'silver') AND p.proname LIKE 'fn_%'
            ORDER BY n.nspname, p.proname
        """)
        present = {(s, f) for (s, f) in cur.fetchall()}

w = csv.writer(sys.stdout)
w.writerow(["schema", "function", "installed", "verified_in_pg_proc"])
fail = 0
for path in sorted(installed_paths):
    if not path.startswith("sql/functions/fn_"):
        continue
    fn_name = path.split("/")[-1].replace(".sql", "")
    schema = "silver" if fn_name in {"fn_build_communication_hierarchy","fn_build_company_tree","fn_traverse_hierarchy","fn_get_hierarchy_json"} else "staging"
    verified = (schema, fn_name) in present
    if not verified: fail += 1
    w.writerow([schema, fn_name, "yes", "yes" if verified else "NO"])

sys.stderr.write(f"pg_functions: {result['count']} installed, {len(present)} verified, {fail} missing from pg_proc\n")
sys.exit(1 if fail else 0)
'@ > $out

$exit = $LASTEXITCODE
Write-Host "pg_functions csv: $out (exit $exit)" -ForegroundColor $(if ($exit -eq 0) { "Green" } else { "Red" })
exit $exit
