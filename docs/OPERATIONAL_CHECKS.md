# Operational Checks — CLI Reference Card (Windows / PowerShell 7+)

Sequential validation playbook for the `w/foundation-restore` branch.
Every command is **PowerShell 7+ (`pwsh`)** and copy-pasteable from `ic-load\`
as the working directory. Later sections depend on earlier sections passing.

Requires: PowerShell 7 (`pwsh.exe`). `powershell.exe` (Windows PowerShell 5.1)
works for most blocks but its here-strings and `ForEach-Object -Parallel` behave
differently. If you're on 5.1, install 7 from `winget install Microsoft.PowerShell`.

Bash users (Git Bash / WSL) can follow the same sections — Python invocations
are identical; shell plumbing differs. A companion bash version is left as
future work; the semantics match.

---

## 0. Prerequisites — environment

Change directory and set required env vars for the current session.

```powershell
Set-Location ic-load

# Option A — set the five PG vars inline (clear the session later with Remove-Item env:ICALPS_*)
$env:ICALPS_PGHOST     = "2219-revops.pgm5k8mhg52j6k63k3dd54em0v.postgres.stacksync.com"
$env:ICALPS_PGPORT     = "5432"
$env:ICALPS_PGDATABASE = "postgres"
$env:ICALPS_PGUSER     = "postgres"
$env:ICALPS_PGPASSWORD = "<rotated-secret>"     # rotate before running — see SECURITY NOTE in .env comments
$env:ICALPS_DBT_COMMAND = "dbt build --project-dir dbt --profiles-dir dbt"

# Option B — load from a local .env (use only if .env exists and is gitignored)
Get-Content .env |
    Where-Object { $_ -notmatch '^\s*#' -and $_ -match '=' } |
    ForEach-Object {
        $name, $value = $_ -split '=', 2
        Set-Item -Path "env:$($name.Trim())" -Value $value.Trim()
    }
```

**Success criterion:**
```powershell
Get-ChildItem env:ICALPS_* | Measure-Object | Select-Object -ExpandProperty Count
# Expect: 6 (five PG vars + ICALPS_DBT_COMMAND)
```

---

## 1. Static validation — no DB, no subprocess

Verifies code parses and imports resolve after F1 / C / F4 changes.

```powershell
python -c @'
from pipeline.state import PipelineStage
from pipeline.runner import PipelineHooks, build_default_hooks
from pipeline.hooks.pg_functions import install
from context.config import load_manifest, BRONZE_DIR, latest_bronze_path

assert PipelineStage.PG_FUNCTIONS_INSTALL, "enum missing"
assert load_manifest().get("version"), "MANIFEST.yaml not loaded"
assert BRONZE_DIR.exists(), f"bronze_layer missing at {BRONZE_DIR}"
assert latest_bronze_path("company"), "no company CSV"
print("STATIC_OK")
'@
```

**Success:** prints `STATIC_OK`.
**Failure modes:**
- `ModuleNotFoundError: pipeline.hooks.pg_functions` → F4 not merged or branch not checked out
- `AssertionError: enum missing` → `pipeline\state.py` unchanged
- `AssertionError: bronze_layer missing` → C fix not merged, or cwd not `ic-load\`
- `AssertionError: no company CSV` → `bronze_layer\Bronze_Company_*.csv` absent

---

## 2. DB connectivity

```powershell
python -c @'
from context.db import get_connection
with get_connection() as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT current_database(), current_user, version()")
        db, user, ver = cur.fetchone()
print(f"CONNECTED db={db} user={user} version={ver[:40]}")
'@
```

**Success:** `CONNECTED db=postgres user=postgres version=PostgreSQL 14…`.
**Failure:** env vars unset or Postgres unreachable → fix before proceeding.

---

## 3. Dry-run the runner — verify stage sequence

No DB mutation. Proves hook wiring end-to-end.

```powershell
python -m pipeline.runner --entity company --dry-run *>&1 |
    Tee-Object -FilePath artifacts\dryrun_company.log
```

**Success:** first stage line reads
```
[SKIPPED]  PG_FUNCTIONS_INSTALL  reason=dry_run
```
followed by BRONZE_* stages in order (the last, BRONZE_EXPORT, SKIPPED for dry_run).

**Repeat for each entity:**
```powershell
foreach ($e in 'company', 'contact', 'opportunity', 'communication', 'case') {
    Write-Host "=== $e ===" -ForegroundColor Cyan
    python -m pipeline.runner --entity $e --dry-run *>&1 |
        Select-String -Pattern 'SKIPPED|SUCCESS|FAILED' |
        Select-Object -First 8
}
```

---

## 4. PG_FUNCTIONS_INSTALL — live install + verification

Installs schema + 15 functions. Idempotent (CREATE OR REPLACE / IF NOT EXISTS).

```powershell
python -c @'
from pipeline.hooks.pg_functions import install
result = install(dry_run=False)
print(result)
'@
```

**Success:** prints `{'installed': [...16 paths...], 'count': 16, 'duration_s': 0.xxx, 'mode': 'executed'}`. Count is 16 because `sql/silver/00_hierarchy_schema.sql` runs ahead of the 15 MANIFEST functions.

Verify from psql or any Postgres client:
```sql
SELECT n.nspname AS schema, COUNT(*) AS fn_count
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname IN ('staging', 'silver') AND p.proname LIKE 'fn_%'
GROUP BY n.nspname;
-- Expected: staging=11, silver=4

SELECT schemaname, tablename FROM pg_tables
WHERE schemaname = 'silver' AND tablename IN ('communication_hierarchy', 'company_tree');
-- Expected: 2 rows
```

**Failure:** `permission denied for schema staging` → role lacks CREATE. DB admin action: `GRANT CREATE ON SCHEMA staging TO <role>;`.

---

## 5. Pre-dbt schema probe — baseline CSV

Dumps current state of every staging table the pipeline cares about.

```powershell
python scripts\probe_schemas.py --output artifacts\probe_pre_dbt.csv
```

**Success:** exit 0, message `Wrote artifacts\probe_pre_dbt.csv — N rows (X ok, Y not_found, 0 errors)`. Pre-dbt the `fct_communication_*` tables report `not_found` — **expected**, not a failure.

Inspect:
```powershell
Get-Content artifacts\probe_pre_dbt.csv -TotalCount 5

Import-Csv artifacts\probe_pre_dbt.csv |
    Where-Object status -eq 'not_found' |
    Select-Object -ExpandProperty table -Unique
# Expected: fct_communication_*, fct_custom_object_tasks, stg_custom_object_tasks
```

---

## 6. Silver normalisation (per entity)

Populates `staging.stg_{entity}_normalised` via Python `SilverNormaliser`.

```powershell
python -c @'
from pipeline.silver import SilverNormaliser
n = SilverNormaliser()
n.normalise_company()
n.normalise_contact()
n.normalise_opportunity()
n.normalise_communication()
print("SILVER_DONE")
'@
```

Verify:
```sql
SELECT 'company' AS entity, COUNT(*) FROM staging.stg_company_normalised
UNION ALL SELECT 'contact',       COUNT(*) FROM staging.stg_contact_normalised
UNION ALL SELECT 'opportunity',   COUNT(*) FROM staging.stg_opportunity_normalised
UNION ALL SELECT 'communication', COUNT(*) FROM staging.stg_communication_normalised;
-- Expected: non-zero counts for every entity you ran.
```

---

## 7. dbt build (communication only)

dbt-postgres via DuckDB + `postgres_scanner`. Requires `ICALPS_DBT_COMMAND`
and that the `ICALPS_PG*` env vars are populated (profiles.yml reads them
via `env_var` Jinja).

```powershell
Set-Location dbt

dbt deps                                              # installs dbt_utils (one-time)
dbt build --select +fct_communication_notes           # smoke — one mart + upstream
dbt build                                             # full graph — marts + tests

Set-Location ..
```

Verify via artifacts:
```powershell
Get-ChildItem dbt\target\run_results.json, dbt\target\manifest.json

python -c @'
import json
rr = json.load(open("dbt/target/run_results.json"))
ok   = sum(1 for r in rr["results"] if r["status"] in ("success", "pass"))
fail = sum(1 for r in rr["results"] if r["status"] in ("error", "fail"))
print(f"dbt results: {ok} ok, {fail} fail")
'@
```

Or query Postgres:
```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'staging' AND table_name LIKE 'fct_communication_%'
ORDER BY table_name;
```

---

## 8. Post-dbt schema probe + diff

```powershell
python scripts\probe_schemas.py --output artifacts\probe_post_dbt.csv

# Compare the two CSVs (SideIndicator column shows =>/<= for side of difference)
Compare-Object `
    (Get-Content artifacts\probe_pre_dbt.csv) `
    (Get-Content artifacts\probe_post_dbt.csv) |
    Select-Object -First 40

# Alternative — built-in fc.exe (line-level diff)
fc.exe artifacts\probe_pre_dbt.csv artifacts\probe_post_dbt.csv | Select-Object -First 40
```

**Expected diff:**
- `fct_communication_*` rows flip `not_found` → `ok`, `row_count > 0`, columns populated
- `stg_*_normalised` rows **identical** (dbt does not touch silver Python output)

Any other diff is a regression signal.

---

## 9. Gold upsert — static render check (no DB)

Confirms render.py emits valid SQL for every entity, without executing.

```powershell
python -c @'
from sql.render import render_entity_upsert, render_engagement_upsert, render_association_bridge

for entity in ("Company", "Person", "Opportunity"):
    sql = render_entity_upsert(entity)
    assert "INSERT INTO hubspot" in sql
    print(f"{entity:12s} upsert OK  ({len(sql)} chars)")

for ct in ("Calls", "Notes", "Tasks", "Meetings"):
    sql = render_engagement_upsert(ct)
    assert "INSERT INTO hubspot" in sql
    print(f"{ct:12s} engagement OK")

for ct in ("Calls", "Notes", "Tasks"):
    for tgt in ("company", "contact"):
        sql = render_association_bridge(ct, tgt)
        assert "INSERT INTO hubspot.associations_" in sql
        print(f"{ct}->{tgt:10s} assoc OK")
'@
```

**Success:** every line prints `OK`.

---

## 10. Full runner dry-run per entity — end-to-end wiring

```powershell
foreach ($e in 'company', 'contact', 'opportunity', 'communication', 'case') {
    python -m pipeline.runner --entity $e --dry-run --enable-post-gold *>&1 |
        Select-Object -Last 5
    Write-Host "---" -ForegroundColor DarkGray
}
```

Inspect the most recent artifact:
```powershell
Get-ChildItem artifacts\pipeline_run_*.json |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1 |
    Get-Content |
    python -m json.tool |
    Select-Object -First 60
```

**Success:** every entity reaches `COMPLETE` status in its artifact `history`.

---

## 11. Live pipeline run (explicit gates)

**Only after** every dry-run passed. Touches production Postgres.

```powershell
# Single entity, gold upsert only (stops before STACKSYNC)
python -m pipeline.runner --entity company --approve-gold

# Single entity, full end-to-end including STACKSYNC + ASSOC_VALIDATE
python -m pipeline.runner --entity communication --approve-gold --enable-post-gold
```

**Success:** final line `Pipeline run SUCCESS. Artifact: pipeline_run_<entity>_<ts>.json`.
**Failure:** read the artifact's `history` array — the FAILED entry carries `reason` + stage-local `details`.

---

## 12. Association bridge — count check

After a communication run with `--enable-post-gold`:

```sql
SELECT 'notes_company'   AS bridge, COUNT(*) FROM hubspot.associations_notes_company
UNION ALL SELECT 'notes_contact',   COUNT(*) FROM hubspot.associations_notes_contact
UNION ALL SELECT 'notes_deal',      COUNT(*) FROM hubspot.associations_notes_deal
UNION ALL SELECT 'calls_company',   COUNT(*) FROM hubspot.associations_calls_company
UNION ALL SELECT 'calls_contact',   COUNT(*) FROM hubspot.associations_calls_contact
UNION ALL SELECT 'tasks_company',   COUNT(*) FROM hubspot.associations_tasks_company
UNION ALL SELECT 'tasks_contact',   COUNT(*) FROM hubspot.associations_tasks_contact;
```

**Success:** non-zero counts wherever `fct_communication_*` has rows.
**All zero:** `runner.py::build_default_hooks()` needs the pending Commit-2 fix
(`association_runner` must receive an `execute_sql` callable).

---

## Quick reference — failure → fix

| Symptom | Likely fix |
|---|---|
| `ModuleNotFoundError: pipeline.hooks` | Check out `w/foundation-restore` branch |
| `no_bronze_csv_found` | C fix not applied, or `bronze_layer\` empty |
| `permission denied for schema staging\|silver` | `GRANT CREATE ON SCHEMA ... TO <role>` |
| `dbt Compilation Error` | `dbt deps` never run, or `ICALPS_DBT_COMMAND` points at wrong dir |
| `RuntimeError: PostgreSQL connection not configured` | Set `ICALPS_JDBC_URL` or the 5 `ICALPS_PG*` vars |
| `association bridge returned 0 rows` | `fct_communication_*` empty (run dbt) **or** `AssociationBridgeExecutor` missing `execute_sql` callable |
| `ParseError` on here-strings | Running in PowerShell 5.1 — upgrade to 7+ (`winget install Microsoft.PowerShell`) |

---

## PowerShell gotchas for this playbook

1. **Here-strings** — `@'...'@` (single-quoted, literal). The closing `'@` **must be at column 0** on its own line. Indenting it is a parse error.
2. **`*>&1`** redirects every stream (stdout, stderr, warning, verbose, debug) to the success stream. Use this instead of `2>&1` when you want to pipe runner errors into `Tee-Object` / `Select-String`.
3. **`Set-Item -Path "env:$name" -Value $value`** vs `$env:VAR = "value"` — both work; the Set-Item form is needed when `$name` is dynamic (as in the .env loader in Section 0).
4. **Pipeline exit codes** — `$LASTEXITCODE` reflects the last native program's exit. PowerShell's `$?` is a boolean and flips on any error in the pipeline, so prefer `$LASTEXITCODE` after a `python` / `dbt` invocation.
5. **CRLF line endings** — git will normalise on commit (hence the `LF will be replaced by CRLF` warnings during `git add`). Harmless for Python / SQL / YAML in this repo.

---

## Commit provenance

All commands above reflect code on `w/foundation-restore`:

| Commit | Scope |
|---|---|
| `57202b1` | `.gitignore` hardening (keeps `.env` out of Git) |
| `725ab68` | This document (Windows rewrite replaces the bash original in-place) |
| `855864b` | BRONZE_DIR path fix (C) |
| `67e3738` | `scripts\probe_schemas.py` (sections 5, 8) |
| `2ab7d1e` | PG_FUNCTIONS_INSTALL stage (sections 1, 3, 4) |
| `873ec54` | dbt project restore (sections 7, 8) |
