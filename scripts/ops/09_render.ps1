# 09_render — static render.py check (no DB).
# Emits artifacts/ops/09_render.csv: kind,name,length,sha1
$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path "$PSScriptRoot\..\..")

$out = "artifacts/ops/09_render.csv"
New-Item -Path (Split-Path $out) -ItemType Directory -Force | Out-Null

uv run python -c @'
import csv, hashlib, sys
from sql.render import render_entity_upsert, render_engagement_upsert, render_association_bridge

w = csv.writer(sys.stdout)
w.writerow(["kind","name","length","sha1","ok"])
fail = 0

for entity in ("Company", "Person", "Opportunity"):
    try:
        sql = render_entity_upsert(entity)
        ok  = "INSERT INTO hubspot" in sql
        w.writerow(["upsert", entity, len(sql), hashlib.sha1(sql.encode()).hexdigest()[:12], "yes" if ok else "NO"])
        if not ok: fail += 1
    except Exception as e:
        w.writerow(["upsert", entity, 0, "", f"err:{e}"]); fail += 1

for ct in ("Calls", "Notes", "Tasks", "Meetings"):
    try:
        sql = render_engagement_upsert(ct)
        ok  = "INSERT INTO hubspot" in sql
        w.writerow(["engagement", ct, len(sql), hashlib.sha1(sql.encode()).hexdigest()[:12], "yes" if ok else "NO"])
        if not ok: fail += 1
    except Exception as e:
        w.writerow(["engagement", ct, 0, "", f"err:{e}"]); fail += 1

for ct in ("Calls", "Notes", "Tasks"):
    for tgt in ("company", "contact"):
        try:
            sql = render_association_bridge(ct, tgt)
            ok  = "INSERT INTO hubspot.associations_" in sql
            w.writerow(["assoc", f"{ct}->{tgt}", len(sql), hashlib.sha1(sql.encode()).hexdigest()[:12], "yes" if ok else "NO"])
            if not ok: fail += 1
        except Exception as e:
            w.writerow(["assoc", f"{ct}->{tgt}", 0, "", f"err:{e}"]); fail += 1

sys.exit(1 if fail else 0)
'@ > $out

$exit = $LASTEXITCODE
Write-Host "render csv: $out (exit $exit)" -ForegroundColor $(if ($exit -eq 0) { "Green" } else { "Red" })
exit $exit
