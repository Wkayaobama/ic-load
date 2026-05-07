# library_runner — Plan for Phases 5 → 11

> Continues from the four committed units on `jl/library-files-rest-sandbox`.
> Sequential-thinking driven, no superpowers framework, sandbox-first.

## State at start of Phase 5

| Layer | Status | Lives in |
|---|---|---|
| HubSpot REST client (8 methods) | proven against sandbox | `pipeline/library_files/client.py` |
| Two-phase uploader + 429 retry | proven against sandbox | `pipeline/library_files/uploader.py` |
| Folder walker + image filter | proven against sandbox | `pipeline/library_files/walker.py` |
| Source readers (CSV + Postgres) | CSV proven, Postgres skeleton-only | `pipeline/library_files/sources.py` |
| Sandbox override map | proven (JSON round-trip + live use) | `pipeline/library_files/overrides.py` |
| CLI runner (`walk`, `migrate`) | proven for `walk`; `migrate` proven via in-process call | `pipeline/library_files/runner.py` |
| **Idempotency ledger** | **in-memory only** | — |
| **Approval gates** | **none** | — |
| **Prod-postgres live exercise** | **not run** | — |
| **Prod-portal writes** | **never executed** | — |

11 tests passing, 4 live against sandbox `49610528`.

## Mental model — what each phase buys

The work below moves the system from "proven in sandbox with synthetic data" to "running in production with operational guarantees". Three independent axes:

1. **Persistence** — survive crashes, re-run safely (Phase 5)
2. **Safety** — every prod write is intentional, never accidental (Phase 6)
3. **Cutover** — bridge from sandbox-writes to prod-writes (Phases 7 → 9 → 10)

Phases 5 and 6 are prerequisites for any prod write. Phase 7 stays sandbox-side. Phase 9 is the first prod write, and it's gated, small, and reversible.

---

## Phase 5 — Postgres-backed idempotency ledger

**Goal:** crash-safe two-phase uploads. Re-running the migrator skips legacy rows already at `status='attached'`.

**Where the tables live:** `staging.fct_files_uploaded` and `staging.fct_file_notes_posted`, in the postgres pointed at by `PROD_POSTGRES_DSN`. These are *our* staging tables — not StackSync-mirrored — so writing to them does not propagate anywhere.

**DDL (one-shot init):**

```sql
CREATE SCHEMA IF NOT EXISTS staging;

CREATE TABLE IF NOT EXISTS staging.fct_files_uploaded (
    legacy_library_id   TEXT PRIMARY KEY,
    hs_file_id          TEXT,
    status              TEXT NOT NULL,           -- pending|uploaded|failed
    error               TEXT,
    attempts            INT  NOT NULL DEFAULT 0,
    first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_attempt_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS staging.fct_file_notes_posted (
    legacy_library_id   TEXT PRIMARY KEY,
    hs_note_id          TEXT,
    idempotency_key     TEXT,                     -- 'icalps_libfile_'||legacy_library_id
    status              TEXT NOT NULL,            -- pending|attached|partial|failed
    error               TEXT,
    attempts            INT  NOT NULL DEFAULT 0,
    first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_attempt_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**Code surface (new file):** `pipeline/library_files/ledger.py` with one class:

```python
class PostgresLedger:
    def __init__(self, dsn: str): ...
    def bootstrap(self) -> None:                 # runs the DDL above (idempotent)
    def upload_skip_set(self) -> set[str]:       # legacy_ids where status='uploaded'
    def attach_skip_set(self) -> set[str]:       # legacy_ids where status='attached'
    def record_upload(self, entry: dict): ...    # UPSERT on legacy_library_id
    def record_attach(self, entry: dict): ...
```

**Wiring:** `HubSpotFileUploader.__init__` gains `ledger: PostgresLedger | None = None`. When non-None:
- Phase 1 starts by reading `upload_skip_set` and skipping rows already uploaded; calls `record_upload` after each REST call.
- Phase 2 starts by reading `attach_skip_set`; calls `record_attach` after each note creation.

When `None` (the existing tests), behavior is unchanged.

**Checklist:**

- [ ] Add `pipeline/library_files/ledger.py` with `PostgresLedger`
- [ ] Modify `HubSpotFileUploader` to accept and call `ledger` (no breaking changes — `None` is the default)
- [ ] Add `runner.py migrate --use-ledger` flag that constructs a `PostgresLedger(settings.prod_postgres_dsn)` and runs `bootstrap()` first
- [ ] Tests
  - [ ] Offline: in-memory fake of the ledger interface — assert pre-flight skip and UPSERT calls fire
  - [ ] Live sandbox + a *local* postgres (or a docker-compose'd one) — run twice, assert second run is a no-op
- [ ] Document the DDL in `pipeline/library_files/README.md` (Phase 11)

**Pass criterion:** running the migrator twice in succession against the sandbox produces zero new HubSpot resources on the second run.

**Open decision:** is `PROD_POSTGRES_DSN` the right place for the ledger, or do we want a separate `LEDGER_POSTGRES_DSN`? Default is to reuse PROD_POSTGRES_DSN since the staging schema is already writeable.

---

## Phase 6 — Approval gates (dry-run by default)

**Goal:** every REST write requires an explicit env-var opt-in. Without it, the runner enumerates + resolves but does not POST.

**Variables:**
- `ICALPS_APPROVE_FILES_UPLOAD=1` — Phase 1 may POST `/files/v3/files`
- `ICALPS_APPROVE_FILE_NOTES_POST=1` — Phase 2 may POST `/notes` and PUT `/associations`

**Behavior matrix:**

| upload gate | notes gate | result |
|---|---|---|
| unset | unset | DRY-RUN — print resolved rows + targets, exit 0, zero REST writes |
| set | unset | Phase 1 runs (files uploaded, ledger updated), Phase 2 dry-runs |
| set | set | Full live run |
| unset | set | DRY-RUN with warning — Phase 2 cannot run without uploaded files |

**Code surface:** `runner.cmd_migrate` reads both env vars at start, passes booleans to the uploader. `HubSpotFileUploader.upload_phase` and `attach_phase` each accept a `live: bool`; when `False`, append a `status='dry_run'` ledger entry without REST calls.

**Checklist:**

- [ ] Add gate reading + passthrough in `runner.cmd_migrate`
- [ ] Add `live` param to `upload_phase` and `attach_phase`
- [ ] Add a `STATUS_DRY_RUN` constant
- [ ] Tests
  - [ ] Offline: gates unset → no REST mocked, ledger shows all rows as `dry_run`
  - [ ] Offline: only Phase 1 gate set → Phase 1 mocks fire, Phase 2 stays dry-run
  - [ ] Live sandbox: both gates set → existing Unit 4 invariants still hold
- [ ] Update `.env.example` with the two gate vars (commented-out)

**Pass criterion:** `python -m pipeline.library_files.runner migrate ...` with no gates set produces zero entries in `staging.fct_files_uploaded`.

---

## Phase 7 — Live exercise of `PostgresLibraryReader` (sandbox writes only)

**Goal:** validate the postgres reader against the real prod schema. Sandbox stays the write target.

**Inputs needed:**
- `PROD_POSTGRES_DSN` populated in `.env`
- A small SQL query — start with `SELECT … FROM ... LIMIT 1` against whatever source mart exists in prod (or a hand-rolled query joining stg_library_normalised → hubspot.companies, etc., if the mart isn't built yet)
- One sandbox company seeded; override map keyed by the legacy_company_id returned by the query

**Run:**

```bash
python -m pipeline.library_files.runner migrate \
    --library-base-dir <path-to-real-files> \
    --overrides-json overrides.json \
    --source postgres \
    --query "SELECT legacy_library_id, legacy_file_name, legacy_file_path, legacy_company_id, NULL::text legacy_contact_id, NULL::text legacy_deal_id FROM staging.stg_library_normalised LIMIT 1"
```

**Checklist:**

- [ ] Confirm prod postgres credentials with the user
- [ ] Identify or build the source query
- [ ] Seed one sandbox company manually (or via a small `runner seed-sandbox` helper)
- [ ] Write `overrides.json` mapping that legacy_company_id → seeded sandbox id
- [ ] Run the migrate command above
- [ ] Inspect ledger entries; verify HubSpot UI shows the note + attachment on the sandbox company

**Pass criterion:** ledger shows 1 row at `status='attached'`; sandbox HubSpot UI confirms file is attached and associated.

**Open decision:** does the source mart `staging.stg_library_normalised` already exist in prod, or do we read straight from a Bronze CSV / write the SELECT inline? If neither exists, we need a Bronze extraction + silver normalization step first — that's a *separate* prerequisite belonging to the Bronze pipeline, not this plan.

---

## Phase 8 — Cutover gate (decision, not work)

A go/no-go checkpoint. **No code changes**, just a checklist with the user:

- [ ] Phase 5 ledger demonstrably idempotent on re-run
- [ ] Phase 6 gates demonstrably block writes when unset
- [ ] Phase 7 returned a clean ledger for ≥1 prod row
- [ ] Override map shape understood by the operator (the user)
- [ ] Sandbox UI inspection of Phase 7 confirms the attachment + association look correct end-to-end
- [ ] Operator has a HubSpot prod private app token with `crm.objects.notes.write`, `crm.objects.notes.read`, `crm.associations.write`, `files` scopes

If any box is unchecked, loop back. Only when all are checked: proceed to Phase 9.

---

## Phase 9 — Production-portal pilot (≤10 rows)

**The first time we write to prod HubSpot.** Tightly scoped, gated, manually verified per row.

**Configuration delta from Phase 7:**
- Use `HUBSPOT_PROD_TOKEN` (a new env var) instead of `HUBSPOT_SANDBOX_TOKEN`
- Drop the override map entirely — `--no-overrides` flag, prod ids from postgres go straight to associations
- Both approval gates must be set
- LIMIT 10 in the source query

**Code surface:** `Settings.from_env(token_var="HUBSPOT_PROD_TOKEN")`. `runner.cmd_migrate` accepts `--no-overrides` flag that skips the override map and feeds postgres-resolved hubspot_*_ids straight to the uploader.

**Checklist:**

- [ ] Add `HUBSPOT_PROD_TOKEN` to `.env.example` (commented)
- [ ] Add `--no-overrides` flag to runner
- [ ] Operator inspects HubSpot prod UI for each of the 10 created notes and confirms:
  - File attached
  - Body matches expected template
  - Associated to the correct company/contact/deal
- [ ] Failed/partial rows investigated, root-caused, ledger updated

**Pass criterion:** 10/10 rows at `status='attached'`, manual UI inspection clean.

**Rollback:** for any row the operator wants undone:
```sql
SELECT hs_note_id FROM staging.fct_file_notes_posted WHERE legacy_library_id = '...'
```
then `DELETE /crm/v3/objects/notes/{id}` (the file in `/files/v3/files/{id}` can be deleted separately if desired).

---

## Phase 10 — Full production run

LIMIT removed. Re-runs are safe (Phase 5 idempotency).

**Operator monitoring:**
- Tail ledger row counts every N minutes
- Watch 429/5xx rate (uploader logs them; consider adding structured logging in Phase 11)
- Spot-check 5–10 random notes in HubSpot UI

**Checklist:**

- [ ] Sized estimate from `SELECT count(*) FROM <source>`
- [ ] Disk space check on `LIBRARY_BASE_DIR`
- [ ] Run command captured (paste exact CLI used)
- [ ] Run completes; tally `status` distribution from ledger
- [ ] Failed/partial bucket investigated

**Pass criterion:** ≥99% rows at `status='attached'`. Outliers are categorised and triaged.

---

## Phase 11 — Documentation

- [ ] `pipeline/library_files/README.md` — module overview, install steps, .env vars, the two CLI sub-commands with example invocations, ledger DDL, troubleshooting
- [ ] Add a short "Library files migration" section to `salvation.md` pointing at the README and noting the prod cutover date
- [ ] Update `requirements.txt` if any new deps were added in Phases 5–10
- [ ] Capture the prod cutover commit hash + run timestamp in the README's "Operational history" section

---

## Optional Phase A — dbt source views

Only do this if you want `fct_library_files` queryable by other consumers (BI, data science, downstream ETL). The runner does not need it.

Three-model chain mirroring the original superpowers plan:
- `dbt/models/staging/stg_bronze_library.sql`
- `dbt/models/intermediate/int_library_reconciled.sql`
- `dbt/models/marts/fct_library_files.sql`
- `dbt/models/_sources/sources.yml` add `stg_library_normalised`
- `dbt/models/marts/_marts__models.yml` add `fct_library_files`
- `dbt/tests/assert_library_at_least_one_association.sql`

If we go this route, `runner.PostgresLibraryReader` switches its default query to `SELECT … FROM staging.fct_library_files`. No other code change.

## Optional Phase B — Gomplate schema_context.yaml entry

Only if we ever want template-driven SQL for this entity. This module uses REST end-to-end, so the value is low. Skip unless a concrete need emerges.

---

## Summary — REST endpoints called per phase

| Phase | New endpoints | Net behavior |
|---|---|---|
| 5 | none | ledger writes only (postgres) |
| 6 | none | gates can block all REST |
| 7 | same as Unit 4, against postgres source | sandbox writes |
| 9 | same endpoints, prod portal | first prod write |
| 10 | same | scaled prod write |

No new HubSpot endpoints are introduced after Unit 4. The remaining work is operational hardening, not protocol expansion.

## Open decisions tracked

1. Ledger DSN — same as `PROD_POSTGRES_DSN` (recommended) or separate?
2. Source mart for Phase 7 — does `staging.stg_library_normalised` already exist, or do we need an upstream Bronze step first?
3. Idempotency strategy for re-runs — ledger-only (recommended) vs HubSpot-side dedup property?
4. Cutover authorization — who signs off Phase 9?
5. dbt views (Phase A) — yes/no?

Surface these to the operator before Phase 5 begins.
