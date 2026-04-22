# 11_load — GATED live upsert. Runs the real runner with --approve-gold.
# Requires BOTH -Entity and -Confirm. Never invoked by run_all.ps1 unless
# -IncludeLoad is passed AND these two parameters are also supplied.
#
#   .\scripts\ops\11_load.ps1 -Entity company -Confirm
#
param(
    [Parameter(Mandatory=$false)][string]$Entity,
    [switch]$Confirm
)
$ErrorActionPreference = "Stop"

if (-not $Entity -or -not $Confirm) {
    Write-Host "USAGE: .\scripts\ops\11_load.ps1 -Entity <name> -Confirm" -ForegroundColor Yellow
    Write-Host "Entities: company | contact | opportunity | communication | case" -ForegroundColor DarkGray
    Write-Host "Skipping — no mutation performed." -ForegroundColor DarkGray
    exit 0
}

$allowed = @('company','contact','opportunity','communication','case')
if ($Entity -notin $allowed) {
    Write-Host "Unknown entity '$Entity'. Expected one of: $($allowed -join ', ')" -ForegroundColor Red
    exit 1
}

Write-Host "live upsert: entity=$Entity (runner --approve-gold)" -ForegroundColor Yellow
python -m pipeline.runner --entity $Entity --approve-gold
exit $LASTEXITCODE
