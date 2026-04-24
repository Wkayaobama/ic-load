# 02_db — DB connectivity smoke. No CSV (boolean result, stdout only).
$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path "$PSScriptRoot\..\..")

uv run python -c @'
from context.db import get_connection
with get_connection() as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT current_database(), current_user, version()")
        db, user, ver = cur.fetchone()
print(f"connected  db={db}  user={user}  version={ver[:40]}")
'@
exit $LASTEXITCODE
