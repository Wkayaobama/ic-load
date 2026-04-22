# Operational Checks — CLI Reference Card

Sequential validation playbook for the `w/foundation-restore` branch state.
Every section is **copy-pasteable** against a fresh shell from `ic-load/` as
the working directory. Later sections depend on earlier sections succeeding.

Assumes Postgres + bronze CSVs are already provisioned. The playbook does not
create data; it only verifies that the pipeline sees and processes what exists.

---

## 0. Prerequisites — environment

```bash
cd ic-load
cp ../.env.example .env      # only if you don't already have one
```

Required env vars (any of these two forms works):

```bash
# Form A — single JDBC URL (preferred)
export ICALPS_JDBC_URL="jdbc:postgresql://HOST:5432/postgres?user=USER&password=PASS"

# Form B — individual vars (also read by dbt profiles.yml)
export ICALPS_PGHOST=<host>
export ICALPS_PGPORT=5432
export ICALPS_PGDATABASE=postgres
export ICALPS_PGUSER=<user>
export ICALPS_PGPASSWORD=<rotated-secret>

# dbt subprocess knob (only needed for DBT_BUILD stage)
export ICALPS_DBT_COMMAND="dbt build --project-dir dbt --profiles-dir dbt"
```

**Success criterion:** `env | grep -E "^ICALPS_" | wc -l` returns ≥ 4.

---

## 1. Static validation — no DB, no subprocess

Verifies code parses and imports resolve after F1/F2/F3/F4 changes.

```bash
python -c "
from pipeline.state import PipelineStage
from pipeline.runner import PipelineHooks, build_default_hooks
from pipeline.hooks.pg_functions import install
from context.config import load_manifest, BRONZE_DIR, latest_bronze_path

assert PipelineStage.PG_FUNCTIONS_INSTALL, 'enum missing'
assert load_manifest().get('version'), 'MANIFEST.yaml not loaded'
assert BRONZE_DIR.exists(), f'bronze_layer missing at {BRONZE_DIR}'
assert latest_bronze_path('company'), 'no company CSV'
print('STATIC_OK')
"
```

**Success:** prints `STATIC_OK`.
**Failure modes:**
- `ModuleNotFoundError: pipeline.hooks.pg_functions` → F4 not merged / branch not checked out
- `AssertionError: enum missing` → `pipeline/state.py` unchanged
- `AssertionError: bronze_layer missing` → C fix not merged, or cwd not `ic-load/`
- `AssertionError: no company CSV` → `bronze_layer/Bronze_Company_*.csv` absent

---

## 2. DB connectivity

```bash
python -c "
from context.db import get_connection
with get_connection() as conn:
    with conn.cursor() as cur:
        cur.execute('SELECT current_database(), current_user, version()')
        db, user, ver = cur.fetchone()
print(f'CONNECTED db={db} user={user} version={ver[:40]}')
"
```

**Success:** prints `CONNECTED db=postgres user=<user> version=PostgreSQL 14…`.
**Failure:** env vars unset or Postgres unreachable → fix before proceeding.

---

## 3. Dry-run the runner — verify stage sequence

No DB mutation. Proves the hook wiring works end-to-end.

```bash
python -m pipeline.runner --entity company --dry-run 2>&1 | tee artifacts/dryrun_company.log
```

**Success:** first stage line reads
```
[SKIPPED]  PG_FUNCTIONS_INSTALL  reason=dry_run
```
followed by BRONZE_* stages running in order (BRONZE_LOAD / METADATA / WATERMARK / EXPORT, the last SKIPPED for dry_run).

**Repeat for each entity** to catch any entity-specific wiring bug:
```bash
for e in company contact opportunity communication case; do
    echo "=== $e ==="
    python -m pipeline.runner --entity $e --dry-run 2>&1 | grep -E "SKIPPED|SUCCESS|FAILED" | head -8
done
```

---

## 4. PG_FUNCTIONS_INSTALL — live install + verification

Installs schema + 15 functions. Safe to re-run (CREATE OR REPLACE / IF NOT EXISTS).

```bash
python -c "
from pipeline.hooks.pg_functions import install
result = install(dry_run=False)
print(result)
"
```

**Success:** prints `{'installed': [...16 paths...], 'count': 16, 'duration_s': 0.xxx, 'mode': 'executed'}` (the count is 16 because `sql/silver/00_hierarchy_schema.sql` runs ahead of the 15 MANIFEST functions).

Verify in Postgres:
```sql
-- Function count per schema
SELECT n.nspname AS schema, COUNT(*) AS fn_count
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname IN ('staging', 'silver') AND p.proname LIKE 'fn_%'
GROUP BY n.nspname;
-- Expected: staging=11, silver=4

-- Hierarchy tables
SELECT schemaname, tablename FROM pg_tables
WHERE schemaname = 'silver' AND tablename IN ('communication_hierarchy', 'company_tree');
-- Expected: 2 rows
```

**Failure:** `permission denied for schema staging` → Postgres role lacks CREATE. Fix: `GRANT CREATE ON SCHEMA staging TO <role>` as a DB admin.

---

## 5. Pre-dbt schema probe — baseline CSV

Dumps the current state of every staging table the pipeline cares about.

```bash
python scripts/probe_schemas.py --output artifacts/probe_pre_dbt.csv
```

**Success:** exit 0, prints `Wrote artifacts/probe_pre_dbt.csv — N rows (X ok, Y not_found, 0 errors)`. Pre-dbt, the `fct_communication_*` tables should report `not_found` (dbt hasn't run yet) — that's **expected**, not a failure.

Inspect:
```bash
head -5 artifacts/probe_pre_dbt.csv
awk -F, '$10 == "not_found" {print $2}' artifacts/probe_pre_dbt.csv | sort -u
# Expected: fct_communication_*, fct_custom_object_tasks, stg_custom_object_tasks
```

---

## 6. Silver normalisation (per entity)

Populates `staging.stg_{entity}_normalised` tables that both render.py and dbt
sources consume. Runs the Python `SilverNormaliser`.

```bash
python -c "
from pipeline.silver import SilverNormaliser
n = SilverNormaliser()
n.normalise_company()
n.normalise_contact()
n.normalise_opportunity()
n.normalise_communication()
print('SILVER_DONE')
"
```

Verify:
```sql
SELECT 'company' AS entity, COUNT(*) FROM staging.stg_company_normalised
UNION ALL SELECT 'contact',       COUNT(*) FROM staging.stg_contact_normalised
UNION ALL SELECT 'opportunity',   COUNT(*) FROM staging.stg_opportunity_normalised
UNION ALL SELECT 'communication', COUNT(*) FROM staging.stg_communication_normalised;
-- Expected: non-zero row counts for every entity you ran.
```

---

## 7. dbt build (communication only)

dbt-postgres via DuckDB + postgres_scanner. Requires `ICALPS_DBT_COMMAND`.

```bash
cd dbt
dbt deps                                              # installs dbt_utils (one-time)
dbt build --select +fct_communication_notes           # smoke — one mart and its upstream
dbt build                                             # full graph — all communication marts + tests
cd ..
```

Verify via artifacts:
```bash
ls dbt/target/run_results.json  dbt/target/manifest.json
python -c "
import json
rr = json.load(open('dbt/target/run_results.json'))
ok = sum(1 for r in rr['results'] if r['status'] in ('success', 'pass'))
fail = sum(1 for r in rr['results'] if r['status'] in ('error', 'fail'))
print(f'dbt results: {ok} ok, {fail} fail')
"
```

Or query Postgres directly:
```sql
SELECT table_name, (SELECT COUNT(*) FROM staging.fct_communication_notes) AS row_count
FROM information_schema.tables
WHERE table_schema = 'staging' AND table_name LIKE 'fct_communication_%'
ORDER BY table_name;
```

---

## 8. Post-dbt schema probe + diff

```bash
python scripts/probe_schemas.py --output artifacts/probe_post_dbt.csv
diff artifacts/probe_pre_dbt.csv artifacts/probe_post_dbt.csv | head -40
```

**Expected diff:**
- `fct_communication_*` rows change from `not_found` → `ok`, with `row_count > 0` and column lists populated
- `stg_*_normalised` rows should be **identical** (dbt does not touch silver Python output)

**Any other diff is a regression signal** worth investigating.

---

## 9. Gold upsert — static render check (no DB)

Confirms render.py still emits valid SQL for every entity, without executing.

```bash
python -c "
from sql.render import render_entity_upsert, render_engagement_upsert, render_association_bridge

for entity in ('Company', 'Person', 'Opportunity'):
    sql = render_entity_upsert(entity)
    assert 'INSERT INTO hubspot' in sql
    print(f'{entity:12s} upsert OK  ({len(sql)} chars)')

for ct in ('Calls', 'Notes', 'Tasks', 'Meetings'):
    sql = render_engagement_upsert(ct)
    assert 'INSERT INTO hubspot' in sql
    print(f'{ct:12s} engagement OK')

for ct in ('Calls', 'Notes', 'Tasks'):
    for tgt in ('company', 'contact'):
        sql = render_association_bridge(ct, tgt)
        assert 'INSERT INTO hubspot.associations_' in sql
        print(f'{ct}->{tgt:10s} assoc OK')
"
```

**Success:** every line prints `OK`.

---

## 10. Full runner dry-run per entity — end-to-end wiring

```bash
for e in company contact opportunity communication case; do
    python -m pipeline.runner --entity $e --dry-run --enable-post-gold \
        2>&1 | tail -5
    echo "---"
done
```

Inspect the most recent artifact:
```bash
ls -t artifacts/pipeline_run_*.json | head -1 | xargs cat | python -m json.tool | head -60
```

**Success:** every entity reaches `COMPLETE` status in its artifact history.

---

## 11. Live pipeline run (explicit gates)

**Once** you have verified all dry-runs. Touches production Postgres.

```bash
# Single entity, gold upsert only (stop before STACKSYNC)
python -m pipeline.runner --entity company --approve-gold

# Single entity, end-to-end including STACKSYNC + ASSOC_VALIDATE
python -m pipeline.runner --entity communication --approve-gold --enable-post-gold
```

**Success:** final line reads `Pipeline run SUCCESS. Artifact: pipeline_run_<entity>_<ts>.json`.
**Failure:** read the artifact's `history` array — the FAILED entry carries `reason` and stage-local `details`.

---

## 12. Association bridge — count check

After a communication run with `--enable-post-gold`:

```sql
SELECT
    'notes_company'   AS bridge, COUNT(*) FROM hubspot.associations_notes_company
UNION ALL SELECT 'notes_contact',   COUNT(*) FROM hubspot.associations_notes_contact
UNION ALL SELECT 'notes_deal',      COUNT(*) FROM hubspot.associations_notes_deal
UNION ALL SELECT 'calls_company',   COUNT(*) FROM hubspot.associations_calls_company
UNION ALL SELECT 'calls_contact',   COUNT(*) FROM hubspot.associations_calls_contact
UNION ALL SELECT 'tasks_company',   COUNT(*) FROM hubspot.associations_tasks_company
UNION ALL SELECT 'tasks_contact',   COUNT(*) FROM hubspot.associations_tasks_contact;
```

**Success:** non-zero counts wherever fct_communication_* has rows. If all zero,
check `runner.py::build_default_hooks()` — the original Commit-2 fix (pass
`execute_sql` into `association_runner`) must still be pending.

---

## Quick reference — failure → fix

| Symptom | Likely fix |
|---|---|
| `ModuleNotFoundError: pipeline.hooks` | Check out `w/foundation-restore` branch |
| `no_bronze_csv_found` | C fix not applied, or bronze_layer/ empty |
| `permission denied for schema staging/silver` | `GRANT CREATE ON SCHEMA ... TO <role>` |
| `dbt Compilation Error` | `dbt deps` never run, or `ICALPS_DBT_COMMAND` points at wrong dir |
| `RuntimeError: PostgreSQL connection not configured` | Set `ICALPS_JDBC_URL` or the 5 `ICALPS_PG*` vars |
| `association bridge returned 0 rows` | `fct_communication_*` empty (run dbt) **or** `AssociationBridgeExecutor` missing `execute_sql` callable |

---

## Commit provenance

All commands above reflect code on `w/foundation-restore`:

| Commit | Scope |
|---|---|
| `855864b` | BRONZE_DIR path fix (C) |
| `67e3738` | probe_schemas.py (Step 5 / Step 8) |
| `2ab7d1e` | PG_FUNCTIONS_INSTALL stage (Step 1, 3, 4) |
| `873ec54` | dbt project restore (Step 7, 8) |
