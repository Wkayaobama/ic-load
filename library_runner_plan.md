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

## Bronze input — `sql/library/files_icalps.csv`

Operator-supplied. **Not committed** (gitignored). 5,989 rows, 53 columns, BOM-prefixed UTF-8, Windows backslashes in `Libr_FilePath`.

Columns we consume (everything else passes through `stg_library_normalised` as-is for traceability and gets dropped before the mart):

| Bronze column | Role | Notes |
|---|---|---|
| `Libr_LibraryId` | PK → `legacy_library_id` | BIGINT |
| `Libr_CompanyId` | FK → `legacy_company_id` | join key against `hubspot.companies.icalps_company_id` |
| `Libr_PersonId` | FK → `legacy_contact_id` | join key against `hubspot.contacts.icalps_contact_id` |
| `Libr_OpportunityId` | FK → `legacy_deal_id` | join key against `hubspot.deals.icalps_deal_id` |
| `Libr_CaseId` | passthrough | tickets DEFERRED — same gate as Communication pipeline |
| `Libr_FilePath` | relative dir under `LIBRARY_BASE_DIR` | normalise `\` → `/` |
| `Libr_FileName` | filename + extension | image filter applied here |
| `Libr_FileSize` | sanity-check | flag rows where on-disk size differs |
| `Libr_Note` | candidate for `hs_note_body` | use when non-empty, else fallback template |
| `Libr_Type`, `Libr_Category` | optional metadata | could populate hidden note properties later |
| `Libr_Active`, `Libr_Deleted` | filter predicates | keep `Active='Y' AND (Deleted IS NULL OR Deleted=0)` |
| `Libr_CreatedDate` | candidate for `hs_timestamp` | else default to `now()` |
| `Libr_CreatedBy`, `Libr_UpdatedBy` | owner resolution candidate | optional, mirrors Communication R4 |

**Filter applied at silver:** `Active='Y' AND Deleted IN (NULL, 0) AND (Libr_CompanyId IS NOT NULL OR Libr_PersonId IS NOT NULL OR Libr_OpportunityId IS NOT NULL)`. The last clause drops the "Global Templates" rows visible in the sample — they have no record to associate to and would fail the Phase 2 "at least one association" guard anyway.

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

## Phase 7a — Bronze → silver normalisation

**Goal:** cleanse `sql/library/files_icalps.csv` into `staging.stg_library_normalised` so downstream queries can typed-join to `hubspot.*` reconciliation columns.

**Code surface (new):** `pipeline/library_files/silver_library.py`

```python
class LibrarySilverNormaliser:
    def __init__(self, dsn: str, bronze_csv: Path): ...
    def normalise(self) -> int:                  # returns row count written
        # 1. Read CSV with utf-8-sig (strip BOM)
        # 2. Trim fixed-width-padded strings
        # 3. Cast Libr_*Id columns to BIGINT (NULL preserved)
        # 4. Normalise Libr_FilePath: '\\' → '/', strip leading/trailing '/'
        # 5. Filter: Active='Y' AND Deleted IN (NULL, 0)
        #           AND (Libr_CompanyId|PersonId|OpportunityId) IS NOT NULL
        # 6. UPSERT into staging.stg_library_normalised
```

**DDL:**

```sql
CREATE TABLE IF NOT EXISTS staging.stg_library_normalised (
    legacy_library_id   BIGINT PRIMARY KEY,
    legacy_company_id   BIGINT,
    legacy_contact_id   BIGINT,
    legacy_deal_id      BIGINT,
    legacy_case_id      BIGINT,                  -- passthrough, deferred
    legacy_file_path    TEXT NOT NULL,           -- normalised forward-slash
    legacy_file_name    TEXT NOT NULL,
    libr_file_size      BIGINT,
    libr_note           TEXT,
    libr_type           TEXT,
    libr_category       TEXT,
    libr_status         TEXT,
    libr_created_by     INT,
    libr_updated_by     INT,
    libr_created_at     TIMESTAMPTZ,
    libr_updated_at     TIMESTAMPTZ,
    loaded_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**Tests:**
- [ ] Offline: small fixture CSV with 4 rows (3 valid, 1 "Global Templates" with no FKs) — assert silver writes 3 rows
- [ ] Offline: backslash → forward-slash normalisation
- [ ] Offline: BOM-prefixed UTF-8 read correctly
- [ ] Live (against your real postgres): run once, inspect row count and column types

**Pass criterion:** `SELECT count(*) FROM staging.stg_library_normalised` returns the count of valid rows from the bronze (rows passing the filter).

---

## Phase 7b — Source-mart SQL view (no dbt for v1)

**Goal:** compose `staging.stg_library_normalised` × `hubspot.{companies,contacts,deals}` into a single reconciled view that the runner reads from. Plain SQL, no dbt.

**DDL:**

```sql
CREATE OR REPLACE VIEW staging.fct_library_files AS
SELECT
    s.legacy_library_id::text   AS legacy_library_id,
    s.legacy_file_name          AS legacy_file_name,
    s.legacy_file_path          AS legacy_file_path,
    s.libr_note                 AS libr_note,
    s.legacy_company_id::text   AS legacy_company_id,
    s.legacy_contact_id::text   AS legacy_contact_id,
    s.legacy_deal_id::text      AS legacy_deal_id,
    hc.id::text                 AS hubspot_company_id,
    hp.id::text                 AS hubspot_contact_id,
    hd.id::text                 AS hubspot_deal_id
FROM staging.stg_library_normalised s
LEFT JOIN hubspot.companies hc ON hc.icalps_company_id = s.legacy_company_id
LEFT JOIN hubspot.contacts  hp ON hp.icalps_contact_id = s.legacy_contact_id
LEFT JOIN hubspot.deals     hd ON hd.icalps_deal_id    = s.legacy_deal_id
WHERE COALESCE(hc.id, hp.id, hd.id) IS NOT NULL;   -- at-least-one-match guard
```

`PostgresLibraryReader.DEFAULT_QUERY` already targets `staging.fct_library_files` — no code change needed once the view exists.

### dbt — pros, cons, recommendation

| | dbt model chain | Plain SQL view |
|---|---|---|
| **Pros** | Discoverable mart, schema-tested, mirrors `fct_communication_*` pattern | One file, runs anywhere with psycopg2, no extra build step |
| **Cons** | Adds dbt-duckdb to the runner stack, two-step invocation (`dbt build` then runner), heavy for a one-shot 6k-row migration | No automated tests on schema, no other consumer can SELECT it as a "modeled" object |

**Recommendation: skip dbt for v1.** Use the plain SQL view above. If we later want `fct_library_files` consumable by BI / downstream ETL, port the SELECT to `dbt/models/marts/fct_library_files.sql` — additive, no rework.

**Decision is yours.** I'll wait for your signal before committing to either path.

---

## Phase 7c — Live exercise of `PostgresLibraryReader` (sandbox writes only)

**Goal:** validate the full postgres → reader → uploader chain against real data. Sandbox stays the write target.

**Inputs:**
- `PROD_POSTGRES_DSN` populated in `.env`
- `staging.stg_library_normalised` and `staging.fct_library_files` already created (from Phase 7a/7b)
- `LIBRARY_BASE_DIR` pointing at the real legacy files folder
- One sandbox company seeded; override map keyed by the legacy_company_id of one chosen row

**Run:**

```bash
python -m pipeline.library_files.runner migrate \
    --library-base-dir "$LIBRARY_BASE_DIR" \
    --overrides-json overrides.json \
    --source postgres \
    --query "SELECT * FROM staging.fct_library_files WHERE legacy_library_id = '<chosen-row-id>'"
```

**Checklist:**

- [ ] Phase 7a + 7b complete
- [ ] Identify one row with a non-null `legacy_company_id` and a real on-disk file
- [ ] Seed one sandbox company; record its sandbox id
- [ ] Write `overrides.json` mapping the chosen `legacy_company_id` → that sandbox id
- [ ] Run the migrate command; inspect ledger
- [ ] Verify in HubSpot sandbox UI: file attached, note body populated (use `Libr_Note` if non-empty)

**Pass criterion:** ledger shows 1 row at `status='attached'`; sandbox UI confirms attachment + association.

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

## Phase 9 — Production-portal pilot (1 row, operator-chosen)

**The first time we write to prod HubSpot.** **Exactly one row**, hand-picked by the operator so it can be deleted cleanly if anything looks wrong.

**Configuration delta from Phase 7c:**
- Use `HUBSPOT_PROD_TOKEN` (a new env var) instead of `HUBSPOT_SANDBOX_TOKEN`
- Drop the override map entirely — `--no-overrides` flag, prod ids from postgres go straight to associations
- Both approval gates must be set
- WHERE clause targets exactly the chosen `legacy_library_id`

**Code surface:** `Settings.from_env(token_var="HUBSPOT_PROD_TOKEN")`. `runner.cmd_migrate` accepts `--no-overrides` flag that skips the override map and feeds postgres-resolved hubspot_*_ids straight to the uploader.

**Checklist:**

- [ ] Add `HUBSPOT_PROD_TOKEN` to `.env.example` (commented)
- [ ] Add `--no-overrides` flag to runner
- [ ] Operator picks one row by `legacy_library_id`, records it in advance, knows how to delete the resulting note + file from HubSpot UI
- [ ] Run with `WHERE legacy_library_id = '<chosen>'`
- [ ] Operator verifies in HubSpot prod UI: file attached, body matches expected, associated to correct record(s)
- [ ] Failed/partial → investigate; rollback the one row (DELETE note + file)

**Pass criterion:** the one row at `status='attached'`, manual UI inspection clean.

**Rollback for the single pilot row:**
```sql
SELECT hs_note_id, (SELECT hs_file_id FROM staging.fct_files_uploaded u WHERE u.legacy_library_id = n.legacy_library_id) AS hs_file_id
FROM staging.fct_file_notes_posted n
WHERE n.legacy_library_id = '<chosen>';
```
then `DELETE /crm/v3/objects/notes/{hs_note_id}` and `DELETE /files/v3/files/{hs_file_id}`.

**Rollback:** for any row the operator wants undone:
```sql
SELECT hs_note_id FROM staging.fct_file_notes_posted WHERE legacy_library_id = '...'
```
then `DELETE /crm/v3/objects/notes/{id}` (the file in `/files/v3/files/{id}` can be deleted separately if desired).

---

## Phase 9b — Pilot-batch (after Phase 9 green)

After the 1-row pilot is validated, expand to a small batch (suggest 10 rows). Same gates, same `--no-overrides`. Operator manually checks each note in HubSpot UI. Catches any class-of-row issues that the single pilot row didn't expose.

**Pass criterion:** 10/10 rows at `status='attached'`, manual inspection clean.

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

## Optional Phase A — port `staging.fct_library_files` view to dbt

**Only do this after a successful prod migration**, if a downstream consumer wants the mart available as a tested dbt object. The plain SQL view from Phase 7b works fine for the migrator itself; this is purely about ergonomics for other tools.

Pros/cons already covered in Phase 7b. If we go this route:
- `dbt/models/staging/stg_bronze_library.sql` — passthrough over `staging.stg_library_normalised`
- `dbt/models/intermediate/int_library_reconciled.sql` — the JOINs from the Phase 7b view
- `dbt/models/marts/fct_library_files.sql` — `{{ config(materialized='table') }}`
- Update `dbt/models/_sources/sources.yml` with `stg_library_normalised`
- Add tests in `dbt/models/marts/_marts__models.yml`

The migrator code is unchanged — it already SELECTs from `staging.fct_library_files` whether that's a SQL view or a dbt table.

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

## Decisions resolved

| # | Decision | Resolution |
|---|---|---|
| 1 | Ledger DSN | Reuse `PROD_POSTGRES_DSN`. Staging schema is writeable and not StackSync-mirrored. |
| 2 | Source mart prerequisite | **Build it as part of this plan** (Phase 7a + 7b). Starts from `sql/library/files_icalps.csv`. |
| 3 | Idempotency strategy | Ledger-only (no HubSpot-side dedup property). |
| 4 | Phase 9 pilot scope | **1 row, operator-chosen** (tightened from prior draft of 10). |
| 5 | dbt for v1 | **Skip.** Plain SQL view in Phase 7b. Reconsider only if a downstream consumer asks for it. |

## Open decisions still pending

1. Cutover authorization — who signs off Phase 9 commit-to-prod?
2. Note body source — confirm `Libr_Note` (when non-empty) over the generic template? Operator preference.
3. Ownership resolution — should `Libr_CreatedBy` / `Libr_UpdatedBy` be carried into HubSpot as note custom properties (mirroring the R4 owner work on Communication), or skipped for v1?
4. Bronze re-extraction cadence — one-shot (current 5,989-row CSV is the migration), or do we expect a refreshed bronze before cutover?

Answer 1 before Phase 9. Answers 2–4 before Phase 7a so silver normalisation captures what we want.
