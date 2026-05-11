# Recovery notes — `library-files-cleanup-prod` (2026-05-11)

This session recovered four loose ends on `library-files-cleanup-prod` so the branch can land on `main` cleanly and the operator can probe live without environment-loading surprises. All four landed as discrete commits with independent verification gates.

## Commits landed (in order)

| SHA | Title | Scope |
|---|---|---|
| `5b0c069` | `fix(runner): scope DBT_BUILD to communication only; restore _run_dbt` | salvage runner — DBT_BUILD bug fix |
| `3d9297e` | `refactor(runner): drop duplicate dead-code defs in pipeline/runner.py` | salvage runner — merge-debris cleanup |
| `f64b060` | `feat(context): make salvage runner consume .env.icalps via two fixes` | env loading — unblocks live probe |
| `409e622` | `feat(library_files): add ``unmigrate`` subcommand + ledger rollback methods` | library_files — sandbox rollback path |

(`5b0c069` was pushed earlier; the other three are local until the push at the end of this doc.)

## 1. The salvage runner `_run_dbt` NameError + the trifurcation

### Symptom

`uv run python -m pipeline.runner --entity <any-of-5> --dry-run` crashed at `pipeline/runner.py:197`:

```
NameError: name '_run_dbt' is not defined
```

All five entity dry-runs (`communication`, `company`, `contact`, `opportunity`, `case`) hit the same traceback before reaching `DEDUPE_GUARD`.

### Root cause

A prior refactor had deleted `_run_dbt` but left the call site, plus three duplicate function defs from a bad merge (`_run_pg_functions_install`, `_run_dedupe_guard`, `_run_gold_validate` — each defined twice; Python uses the later def, the earlier def had the wrong signature and was unreachable dead code).

### Fix (commit `5b0c069`)

Restored `_run_dbt(ctx, entity, dry_run, hooks)` as an entity-scoped orchestrator. Mirrors the `pipeline.library_files.runner` pattern (one `--select` per pipeline subgraph). New module constant maps each entity to its dbt slice:

```python
DBT_SELECT_BY_ENTITY: dict[str, str | None] = {
    "company":     None,    # no dbt models for company in this DAG
    "contact":     None,    # no dbt models for contact
    "opportunity": None,    # no dbt models for opportunity
    "case":        None,    # no dbt models for case
    "communication": (
        "+fct_communication_calls +fct_communication_meetings "
        "+fct_communication_notes +fct_communication_tasks "
        "+fct_communication_email_meetings "
        "+fct_communication_bridge +fct_communication_rank "
        "+fct_custom_object_tasks"
    ),
}
```

Non-comm entities transition `DBT_BUILD → SKIPPED reason=no_dbt_models_for_entity` instead of cascading into the comm subgraph through shared `stg_hubspot_*` views.

### Why three runners, not one

The dbt problem surfaced the architectural reality that this repo runs **three distinct CLIs**, each owning a narrow dbt subprocess (or none). Forcing them into one orchestrator with one dbt build would have meant any failure in one pipeline blocks all entities.

```
ENTITY                    RUNNER                                  DBT SCOPE
─────────────────────────────────────────────────────────────────────────────────────────
company, contact,         pipeline.runner                         communication-only
opportunity, case,        (salvage runner — stage machine,        (see DBT_SELECT_BY_ENTITY)
communication             entity-driven)                          for other entities → SKIPPED

library files             pipeline.library_files.runner           NONE — uses raw SQL view at
                          (walk / migrate / unmigrate)            pipeline/library_files/sql/
                                                                  init_fct_view.sql
                                                                  (intentional per init_fct_view
                                                                  comment: "Phase 7b — plain SQL
                                                                  view, no dbt for v1")

stale CRM records         pipeline.cleanup.runner                 NONE — uses Python + SQL
                          (snapshot / check-overlap /             templates rendered through
                          archive / gdpr-delete /                 sql/render.py
                          delete-properties / status)
```

Each runner has:
- Its own argparse subparsers
- Its own approval-gate env-vars (default DRY-RUN)
- Its own ledger (or no ledger)
- Independent dbt scope (or none)

Salvation principle preserved: "the clean runner stops at Gold by default; no post-Gold path runs implicitly." Each runner is an opt-in entry point; none triggers the others.

## 2. Salvage runner couldn't read `.env.icalps` (the operator-blocker)

### Symptom

After populating `.env.icalps` at the Codebase root, library + cleanup runners worked but the salvage runner still saw empty env vars. `context/db.py:get_connection()` raised `"PostgreSQL connection is not configured"` on the first DB-touching stage.

### Root cause (two layers)

1. `context/config.py` never called `dotenv.load_dotenv`. The salvage runner imports `context.config` but no module on its import path triggered the dotenv walk-up.
2. `context/db.py:postgres_config()` read PostgreSQL credentials from `ICALPS_JDBC_URL` / `DATABASE_URL` / `ICALPS_PG*` — but `.env.icalps` carries the DSN under `PROD_POSTGRES_DSN` (the canonical name shared with `pipeline.library_files` / `pipeline.cleanup`). So even after fix #1 the salvage runner would silently fail to connect.

### Fix (commit `f64b060`)

**`context/config.py`** — two-stage dotenv load at module import time, mirroring the pattern in `pipeline/library_files/config.py:Settings.from_env`:

```python
load_dotenv(find_dotenv(filename=".env.icalps", usecwd=True))   # canonical secrets
load_dotenv(find_dotenv(usecwd=True), override=True)            # worktree-local .env wins
```

Precedence: process env > worktree `.env` > `.env.icalps`. `find_dotenv` walks up from cwd, so it works from any subdirectory inside any worktree.

**`context/db.py`** — add `PROD_POSTGRES_DSN` as a third recognised JDBC-URL fallback:

```python
jdbc = (
    os.getenv("ICALPS_JDBC_URL")
    or os.getenv("DATABASE_URL")
    or os.getenv("PROD_POSTGRES_DSN")  # ← new; canonical name in .env.icalps
)
```

All three runners now read the same secret from the same file by the same name.

### Verified

```
configured: True
host: 2219-revops.pgm5k8mhg52j6k63k3dd54em0v.postgres.stacksync.com
port: 5432
database: postgres
user_set: True
password_set: True
```

## 3. `.env` semantics for a fresh clone targeting `main`

**Q.** When I (the operator) clone from `main` after this branch is merged, will the dotenv pattern work?

**A. Yes.** Here is why, with sequential reasoning:

1. **`.env.icalps` is gitignored.** It never lives in any branch — not on `library-files-cleanup-prod`, not on `main`, not anywhere. Only `.env.icalps.example` is tracked. So cloning `main` neither delivers nor expects the populated file.
2. **The loader code IS tracked.** Commit `f64b060` (this branch) puts `dotenv.load_dotenv(find_dotenv(filename=".env.icalps", usecwd=True))` in `context/config.py` at module import time. After merge to `main`, anyone cloning `main` gets that loader.
3. **`find_dotenv(usecwd=True)` walks UP from cwd.** It searches the current directory, then its parent, then grandparent, …, until it finds a file named `.env.icalps` or hits the filesystem root.
4. **The operator places `.env.icalps` at the Codebase root** (one level above the worktree, per `env_vars.md` memory). The walk-up reaches it from any subdirectory of any worktree on any branch.
5. **Therefore:** after `git clone https://github.com/Wkayaobama/ic-load.git` from `main`, the operator only needs to:
   - copy `.env.icalps.example` → `<Codebase>/.env.icalps`
   - fill in `HUBSPOT_SANDBOX_TOKEN`, `HUBSPOT_PROD_TOKEN`, `PROD_POSTGRES_DSN`, `LIBRARY_BASE_DIR`, `HUBSPOT_SANDBOX_PORTAL_ID=49610528`
   - `uv run python -m pipeline.runner ...` (or library_files / cleanup) — the loader fires automatically.

No branch-specific behaviour. No "this only works on cleanup-prod." The dependency is on the operator's local filesystem, not on git state.

## 4. The `unmigrate` rollback path (commit `409e622`)

### Why

The Phase 7c sandbox probe attaches library files as HubSpot Notes via `runner migrate`. Until this commit there was no operator path to roll them back — only `client.delete_note()` as a primitive, called from 5 unit-test cleanup fixtures. Clearing sandbox state between probe iterations required a one-off `uv run python -c "..."` snippet.

### What landed

Three additions in `pipeline/library_files/`:

```
runner.py    + APPROVE_UNMIGRATE_ENV = "ICALPS_APPROVE_UNMIGRATE"
             + cmd_unmigrate(args) → 60 LOC, mirrors cmd_migrate
             + sub.add_parser("unmigrate", ...) — peer to walk / migrate

ledger.py    + PostgresLedger.load_attached_rows() → list[dict]
             + PostgresLedger.record_unattach(legacy_id, status, error) → None
             + LedgerLike Protocol extended with both signatures

tests/test_unit8_unmigrate.py
             + 4 offline cases (empty ledger, dry-run, live-all-succeed,
               live-partial-failure). Uses the same FakeLedger pattern as
               test_unit5_ledger.py, requests_mock for the HubSpot DELETE
               endpoint.
```

### Operator surface

```powershell
cd C:\Users\ayaobama\Documents\AnthonySalesOps\Codebase\ic-load-library-prod

# DRY-RUN — enumerate what would be deleted, no API calls
uv run python -m pipeline.library_files.runner unmigrate

# LIVE — delete the notes
$env:ICALPS_APPROVE_UNMIGRATE = "1"
uv run python -m pipeline.library_files.runner unmigrate
Remove-Item env:ICALPS_APPROVE_UNMIGRATE
```

Idempotent: second invocation finds 0 rows (status is now `unattached_via_unmigrate`, not `attached`).

### Pattern coverage across all entities

Asked: is unmigrate universal? Answer: the **shape** is universal (gate + ledger SELECT + per-row API call + ledger flip), the implementations are sibling-scoped:

| Target | Runner | Subcommand | Gate |
|---|---|---|---|
| Engagements (library files) | `pipeline.library_files.runner` | `unmigrate` | `ICALPS_APPROVE_UNMIGRATE` |
| CRM records (companies/contacts/deals) | `pipeline.cleanup.runner` | `archive --object X` | `ICALPS_APPROVE_ARCHIVE` |
| GDPR contact purge | `pipeline.cleanup.runner` | `gdpr-delete-contacts` | `ICALPS_APPROVE_GDPR_DELETE` |
| Property schema | `pipeline.cleanup.runner` | `delete-properties` | `ICALPS_APPROVE_PROP_DELETE` |

No single runner needs to "know about" every entity. The operator picks the right runner for the right target. Communication unmigrate is the obvious future extension once Communication gets a ledger (per memory `ledger_extensions.md`); not built speculatively today.

## 5. Verification evidence

All gates green before each push-eligible commit:

```
AST parse                  pipeline/runner.py, library_files/runner.py, library_files/ledger.py   → all ok
Salvage runner dry-runs    communication, company, contact, opportunity, case                      → 5/5 SUCCESS COMPLETE
library_files unit tests   pytest pipeline/library_files/tests/                                    → 29 passed, 1 skipped
                           (the skipped test needs LEDGER_TEST_DSN — live postgres path)
CLI parses                 uv run python -m pipeline.library_files.runner --help                   → walk / migrate / unmigrate listed
env round-trip             import context.config → HUBSPOT_*_TOKEN / PROD_POSTGRES_DSN / LIBRARY_BASE_DIR  surface in os.environ
                           postgres_config() → is_postgres_configured() == True                     → DSN parses to host/port/user/password
```

## 6. Operator handoff (the live probe)

After these commits land on `origin/library-files-cleanup-prod` and the PR opens against `main`:

```powershell
# 0. Codebase root has .env.icalps populated (one level above any worktree)
cd C:\Users\ayaobama\Documents\AnthonySalesOps\Codebase\ic-load-library-prod

# 1. Verify ledger row exists from prior Phase 7c probe
uv run python -c "from pipeline.library_files.ledger import PostgresLedger; from pipeline.library_files.config import Settings; s = Settings.from_env(); l = PostgresLedger(s.prod_postgres_dsn); print('attached:', len(l.attach_skip_set()))"

# 2. DRY-RUN unmigrate — confirm row identification, no API call
uv run python -m pipeline.library_files.runner unmigrate

# 3. LIVE unmigrate
$env:ICALPS_APPROVE_UNMIGRATE = "1"
uv run python -m pipeline.library_files.runner unmigrate
Remove-Item env:ICALPS_APPROVE_UNMIGRATE

# 4. Idempotency check — second dry-run should find 0 rows
uv run python -m pipeline.library_files.runner unmigrate

# 5. Verify in sandbox HubSpot UI that the note is archived

# 6. Open PR to main once the above sequence is green
gh pr create --base main --head library-files-cleanup-prod --title "..." --body "..."
```

## 7. Out of scope (separate follow-ups)

- `--token-env-var` flag on `pipeline.library_files.runner` (so prod runs read `HUBSPOT_PROD_TOKEN` instead of sandbox by switch). Tracked in memory `iteration_loops.md`.
- `--no-overrides` flag (skip the sandbox-id override map in prod).
- Phase 9 prod pilot (1-row) for library files.
- Communication unmigrate (waits on a Communication ledger first).
- Adding automated tests to `pipeline/cleanup/` — runbook + gates are today's control surface.
- `dbt/models/**/*library*` files — intentionally deferred per `init_fct_view.sql:1` comment.
