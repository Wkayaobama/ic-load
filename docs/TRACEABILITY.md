# Pipeline Traceability — Operator Debugging Guide

**Status:** production requirement, not optional.

Every stage in `pipeline.state.PipelineStage` must be traceable from log line
to root cause without reading implementation source. This document specifies
the tooling (VS Code extensions) and the per-stage diagnostic path.

The `.vscode/` folder at the repo root ships the actual workspace
configuration — extensions, settings, tasks, and database connection skeleton.
Opening the workspace in VS Code for the first time prompts to install the
recommended extensions listed in `.vscode/extensions.json`.

See IC_Load_Production_Plan.md §7.5 for the docstring contract that makes
this possible at the hook level. This document adds the tooling layer on top.

---

## 1. Required VS Code Extensions

Shipped in `.vscode/extensions.json` — VS Code prompts to install on first
workspace open.

### 1.1 dbt Power User

**Extension ID:** `innoverio.vscode-dbt-power-user`

**Why it matters for traceability:**
- Renders model lineage (DAG) — click `fct_company_silver` and walk upstream
  to `int_company_reconciled` → `stg_company` → raw source.
- Compiles a model inline — see the actual SQL dbt generates from the
  template, not just the source.
- Runs a single model (`Cmd+Shift+R` on the model name) — reproduces a
  failing `DBT_MARTS` transition in isolation without re-running the pipeline.
- Shows test results inline — `DBT_TEST_SILVER` failures surface in the
  editor with failing row counts.

**Configuration:**
- `.vscode/settings.json` declares `dbt.dbtIntegration: "core"` and
  `dbt.dbtPythonPathOverride` pointing to the repo's Python env.
- `profiles.yml` must be reachable from `$DBT_PROFILES_DIR` (defaults to
  `./dbt` per `.env.example`).

**Minimum workflow for debugging a failed dbt stage:**
```
1. Read the failed log line:
     [FAILED ] DBT_MARTS selector=fct_opportunity_silver
2. In VS Code, open dbt/models/marts/fct_opportunity_silver.sql
3. Cmd+Shift+P → "dbt Power User: Compile current model"
4. The compiled SQL opens in a split panel.
5. Copy-paste into the Database Client query window (below).
6. Run manually to see the full Postgres error with row context.
```

### 1.2 Database Client (PostgreSQL)

**Extension ID:** `cweijan.vscode-database-client2`

**Why it matters for traceability:**
- Query `staging.*` and `hubspot.*` without leaving the editor.
- Reconciliation queries saved as snippets so every operator runs the same
  diagnostic SQL (see `docs/diagnostic_queries.sql`).
- Diff-style result viewer — compare before/after of `GOLD_UPSERT`.

**Configuration:**
- `.vscode/settings.json` declares a `database-client.connections` entry
  named `ic-load-staging`. Credentials are empty by design — fill from
  `.env` or the VS Code secret store.
- The `docs/diagnostic_queries.sql` file is a loadable snippet library;
  right-click → "Run on database-client.ic-load-staging".

---

## 2. Per-Stage Debugging Procedure

When a pipeline run fails, the log's stage block names the failed stage. Use
this table to walk from stage name → hook module → diagnostic tool/query.

| Failed stage | Hook module | Primary tool | First query / action |
|---|---|---|---|
| `PG_FUNCTIONS_INSTALL` | `pipeline/hooks/pg_functions.py` | Database Client | `SELECT routine_name FROM information_schema.routines WHERE routine_schema = 'staging';` |
| `BRONZE_LOAD` | `pipeline/hooks/bronze.py` | File explorer | Verify CSV exists at `$BRONZE_CSV_DIR`; filename matches `Bronze_{Entity}.csv` |
| `BRONZE_EXPORT` | `pipeline/hooks/bronze.py` | Database Client | `SELECT COUNT(*) FROM staging.stg_{entity};` — should match log `row_count` |
| `SILVER_NORMALISE` | `pipeline/silver.py` (legacy) | Database Client | Inspect `staging.stg_{entity}_normalised`; compare row count to bronze |
| `SILVER_VALIDATE` | `pipeline/hooks/silver_validator.py` | YAML editor | Open `ValidationRules/icalps_crm_schema.yaml`; search for the assertion named in `stop_check_names[0]` |
| `DBT_STAGING` / `DBT_INTERMEDIATE` / `DBT_MARTS` | `pipeline/hooks/dbt.py` | dbt Power User | Open the failing model, "Compile current model", paste into Database Client |
| `DBT_TEST_SILVER` / `DBT_TEST_MARTS` | `pipeline/hooks/dbt.py` | dbt Power User | Right-click failed test → "Run test"; inspect `dbt/target/run_results.json` |
| `DEDUPE_GUARD` | `pipeline/hooks/dedupe.py` | VS Code JSON | Open `artifacts/dedupe_probe_{entity}_{run_id}.json`; review pairs by score |
| `GOLD_UPSERT` | `pipeline/hooks/gold.py` | Database Client | Run `duplicate-keys-{entity}` snippet; check `staging.fct_{entity}_silver` for NULLs in NOT-NULL columns |
| `STACKSYNC_SYNC` | `pipeline/hooks/sync.py` | Database Client | Run `uuid-coverage` snippet; if < 50%, check StackSync dashboard externally |
| `ASSOC_VALIDATE` | `pipeline/hooks/associations.py` | Database Client | Inspect `hubspot.associations_*`; compare `pass_a_inserted` vs `pass_b_inserted` |
| `POST_RUN_VERIFY` | `pipeline/hooks/post_run_verify.py` | JSON + Database Client | Open `artifacts/post_run_verify_{entity}_{run_id}.json`; run failing metric's SQL manually |

---

## 3. Log Artifact Locations

| Artifact | Path | Contents |
|---|---|---|
| State machine JSON | `artifacts/pipeline_run_{entity}_{run_id}.json` | Every stage transition with timestamps, details, status |
| Structured log (Phase 5) | `artifacts/logs/pipeline_run_{entity}_{run_id}.log` | Human-readable per-stage blocks (§8.2 format) |
| dbt run results | `dbt/target/run_results.json` | Node-level status, execution time, error messages |
| dbt manifest | `dbt/target/manifest.json` | Model dependency graph |
| StackSync log (cumulative) | `artifacts/stacksync_sync_log.md` | Sync coverage measurements across runs |
| Dedupe probe output | `artifacts/dedupe_probe_{entity}_{run_id}.json` | Candidate duplicate pairs with scores |
| Post-run verification | `artifacts/post_run_verify_{entity}_{run_id}.json` | Reconciliation rate, association coverage, warnings |
| Rendered SQL | `sql/rendered/*.sql` | Exact SQL executed — useful for manual re-run |

**Debugging walk from a failed run:**

1. Run fails → shell exit code ≠ 0, artifact written.
2. Open `artifacts/pipeline_run_{entity}_{run_id}.json`.
3. Find the last `status == "FAILED"` entry — that's the failure stage.
4. Read that entry's `details` dict — contains reason, error context.
5. Cross-reference §2 table → hook module path.
6. Open hook module → read its "Common failure modes" docstring section.
7. Match error text to a documented failure mode → follow diagnostic path.
8. If not documented: update the docstring after resolving. Docstrings are
   the source of truth for operator knowledge.

---

## 4. Reproducing a Failure Locally

### 4.1 dbt model failure

Use `.vscode/tasks.json` → "dbt: run failing model" task (Cmd+Shift+P →
"Run Task"), which prompts for the model name. Or shell:

```bash
cd dbt
dbt run --select {failing_model} --full-refresh
dbt test --select {failing_model}
dbt debug
```

Compiled SQL lands at `dbt/target/compiled/{project}/models/.../file.sql`.
Paste into the Database Client for the real Postgres error.

### 4.2 Gold upsert failure

```bash
# 1. Re-render SQL without executing
python -m pipeline.runner --entity {X} --dry-run --resume-from GOLD_UPSERT
# Output: sql/rendered/upsert_{entity}.sql

# 2. Open in VS Code, run inside rollback transaction via Database Client:
#    BEGIN;
#    <paste rendered SQL>
#    ROLLBACK;
# 3. Inspect error with full context, fix upstream silver, re-run
```

### 4.3 Association bridge failure

```bash
python -m pipeline.runner --entity communication --assoc-only --dry-run
# Output: sql/rendered/association_*.sql
# Inspect each rendered file; run individually in Database Client
```

### 4.4 Resume from a specific stage

```bash
python -m pipeline.runner --entity {X} --resume-from {STAGE_NAME}
```

`{STAGE_NAME}` is an enum value in `pipeline.state.PipelineStage`
(e.g. `GOLD_UPSERT`, `ASSOC_VALIDATE`, `DBT_MARTS`). Resume loads the
latest run artifact for that entity and skips stages with lower `.value`.

---

## 5. Operator Checklist Before Reporting a Bug

Before filing an issue on a failed run:

- [ ] Opened the artifact JSON and identified the failed stage
- [ ] Opened the hook module and read the "Common failure modes" docstring
- [ ] Ran the stage's primary diagnostic query from §2
- [ ] Reproduced the failure via `--resume-from {STAGE}` or the §4 procedure
- [ ] Captured the exact Postgres error text (not the pipeline's wrapper)
- [ ] Confirmed whether failure is code-level (bug) or data-level (upstream
      IC'ALPS or HubSpot state)

If all six are checked and the cause is still unclear, the hook docstring is
incomplete. Update it as part of the fix — don't fix the bug silently.

---

## 6. Traceability is a Contract

Adding a new stage or hook without:

1. A §7.5 docstring block in the hook module
2. An entry in §2 of this document (hook module + primary tool)
3. A documented failure mode with diagnosis path

is considered incomplete work. Phase 3+ migration is gated on these.
