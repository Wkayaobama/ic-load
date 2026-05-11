# operator-library.md — operator runbook for the IC'ALPS Library files migration

> Companion to `library_runner_plan.md` (architecture + decisions). This file
> is operator-facing: concrete commands, gates, verification steps for Phases
> 7c → 11.

---

## Glossary

### DSN — Data Source Name

A **DSN** is one string that bundles everything needed to connect to a database. Instead of passing `host`, `port`, `dbname`, `user`, `password` as separate arguments, you pass a single DSN string and the driver parses it.

Two common shapes for PostgreSQL:

```
# URI form (most common, what we use)
postgresql://USER:PASSWORD@HOST:PORT/DBNAME

# Keyword/value form (older, more verbose)
host=HOST port=PORT dbname=DBNAME user=USER password=PASSWORD
```

**Concrete example for our pipeline:**

```
PROD_POSTGRES_DSN=postgresql://postgres:s3cret@stacksync-host.postgres.stacksync.com:5432/postgres
```

This is the StackSync-hosted postgres where `hubspot.*` tables live (bidirectionally synced with prod HubSpot). Phase 7c onward needs **read-only** access to it via this DSN to look up `hubspot_company_id`, `hubspot_contact_id`, `hubspot_deal_id` for legacy IC'ALPS records. The runner picks the DSN up automatically from `.env` via `Settings.from_env()`; you never type it on the command line.

**Mental model:** think of the DSN as the postgres equivalent of a HubSpot API token — one string that authorizes everything your code does against that resource. Keep it in `.env`, never commit it, treat it like a secret.

---

## Branch + scope

All commands below assume:

```powershell
cd C:\Users\ayaobama\Documents\AnthonySalesOps\Codebase\ic-load-jl-selective-changes
git checkout library-files-rest-sandbox-prod
```

The sandbox-only snapshot branch `jl/library-files-rest-sandbox` is **frozen**. Production-direction work happens on `library-files-rest-sandbox-prod`.

---

## Pre-flight checklist (one-time before Phase 7c)

- [ ] `.env.icalps` populated at the **Codebase root** (one level up from any
      worktree, e.g. `C:\...\Codebase\.env.icalps`). The library and cleanup
      worktrees both read from it via `find_dotenv` walk-up:
  - `HUBSPOT_SANDBOX_TOKEN`, `HUBSPOT_SANDBOX_PORTAL_ID` (sandbox portal `49610528`)
  - `HUBSPOT_PROD_TOKEN` — for Phase 9 onward
  - `LIBRARY_BASE_DIR` — local folder where the legacy files live
  - `PROD_POSTGRES_DSN` — full URI to StackSync postgres
  - `ICALPS_APPROVE_FILES_UPLOAD` and `ICALPS_APPROVE_FILE_NOTES_POST` left **unset** for now (default = DRY-RUN)
  - Worktree-local `.env` still works as an override for ad-hoc debugging — process env > worktree `.env` > Codebase `.env.icalps`.
- [ ] `sql/library/files_icalps.csv` is in place (5,989 rows). Verify:
  ```powershell
  uv run python -c "from pipeline.library_files.silver_library import LibrarySilverNormaliser; from pathlib import Path; n = LibrarySilverNormaliser(Path('sql/library/files_icalps.csv')); list(n.parse()); print(n.stats)"
  ```
  Expect roughly: `total_rows=5989 written_rows=5622`.
- [ ] HubSpot sandbox app has Files API + Notes API + v4 Associations scopes
- [ ] You can run `psql "$env:PROD_POSTGRES_DSN" -c "SELECT 1"` and get back `1` (proves the DSN works)

---

## Phase 7c — First live exercise of `PostgresLibraryReader` (sandbox writes only)

**Goal:** wire postgres to the runner end-to-end. Read one row from prod postgres, override its FK to a seeded sandbox company, attach a real legacy file. Sandbox stays the write target — no prod HubSpot writes yet.

### Step 1 — Bootstrap silver + fct view (one time)

This loads the bronze CSV into `staging.stg_library_normalised` and creates the `staging.fct_library_files` view that joins to `hubspot.{companies,contacts,deals}`.

```powershell
uv run python -c @"
from pipeline.library_files.silver_library import LibrarySilverNormaliser
from pipeline.library_files.config import Settings
from pathlib import Path

settings = Settings.from_env()
n = LibrarySilverNormaliser(
    Path('sql/library/files_icalps.csv'),
    dsn=settings.prod_postgres_dsn,
)
stats = n.normalise()
n.install_fct_view()
print('silver:', stats)
"@
```

**Expect:** `written_rows=5622` and a successful view creation.

### Step 2 — Inspect the fct mart and pick a test row

```powershell
psql "$env:PROD_POSTGRES_DSN" -c "
SELECT legacy_library_id,
       legacy_company_id,
       hubspot_company_id,
       legacy_file_name,
       legacy_file_path
FROM staging.fct_library_files
WHERE hubspot_company_id IS NOT NULL
LIMIT 5;
"
```

Pick **one** `legacy_library_id` whose file you know exists on disk under `LIBRARY_BASE_DIR`.

### Step 3 — Seed a sandbox company and write `overrides.json`

```powershell
# Seed: create a sandbox company; capture its sandbox-side id from the response
uv run python -c @"
from pipeline.library_files.client import HubSpotClient
from pipeline.library_files.config import Settings
c = HubSpotClient.from_settings(Settings.from_env())
co = c.create_company(name='__icalps_phase7c_test__')
print('sandbox company id:', co['id'])
"@
```

Take that sandbox id and the prod `legacy_company_id` from step 2, then write the override map:

```powershell
@'
{
  "<PROD_LEGACY_COMPANY_ID>": {"company": "<SANDBOX_COMPANY_ID>"}
}
'@ | Set-Content overrides.json
```

### Step 4 — Dry-run pass (gates unset)

```powershell
# Make sure neither approval gate is set
Remove-Item env:ICALPS_APPROVE_FILES_UPLOAD -ErrorAction SilentlyContinue
Remove-Item env:ICALPS_APPROVE_FILE_NOTES_POST -ErrorAction SilentlyContinue

uv run python -m pipeline.library_files.runner migrate `
    --library-base-dir "$env:LIBRARY_BASE_DIR" `
    --overrides-json overrides.json `
    --source postgres `
    --query "SELECT * FROM staging.fct_library_files WHERE legacy_library_id = '<CHOSEN_ROW_ID>'"
```

**Expect:** banner says `Phase 1: DRY` and `Phase 2: DRY`. Ledger output shows one row with `status='dry_run'`. **Zero HubSpot writes.**

### Step 5 — Enable Phase 1 gate, re-run

```powershell
$env:ICALPS_APPROVE_FILES_UPLOAD = "1"

uv run python -m pipeline.library_files.runner migrate `
    --library-base-dir "$env:LIBRARY_BASE_DIR" `
    --overrides-json overrides.json `
    --source postgres `
    --query "SELECT * FROM staging.fct_library_files WHERE legacy_library_id = '<CHOSEN_ROW_ID>'"
```

**Expect:** banner says `Phase 1: LIVE` / `Phase 2: DRY`. Ledger row has an `hs_file_id` (file uploaded to sandbox) and `status='dry_run'` (Phase 2 didn't fire). **Verify in sandbox HubSpot UI** that the file appears under Files (not yet attached to anything).

### Step 6 — Enable Phase 2 gate, re-run for full round-trip

```powershell
$env:ICALPS_APPROVE_FILE_NOTES_POST = "1"

uv run python -m pipeline.library_files.runner migrate `
    --library-base-dir "$env:LIBRARY_BASE_DIR" `
    --overrides-json overrides.json `
    --source postgres `
    --query "SELECT * FROM staging.fct_library_files WHERE legacy_library_id = '<CHOSEN_ROW_ID>'"
```

**Expect:** banner says `Phase 1: LIVE` / `Phase 2: LIVE`. Ledger row has `status='attached'` with both `hs_file_id` and `hs_note_id`. **Verify in sandbox HubSpot UI** the seeded company shows the new note with the attached file.

### Pass criterion for Phase 7c

- Ledger shows the test row at `status='attached'`
- Sandbox HubSpot UI shows the file attached to a note, associated to the seeded company
- Idempotency check: re-run Step 6 → ledger reports same `hs_file_id` and `hs_note_id`, no new HubSpot resources created

---

## Phase 8 — Cutover gate (decision, not code)

No commands. Walk this checklist with yourself **before** any prod write.

- [ ] Phase 7c green end-to-end (Step 6 verified in HubSpot UI)
- [ ] Idempotency verified: ran Phase 7c twice in a row, second run was a no-op (zero new HubSpot resources, same ledger ids)
- [ ] DRY-RUN gate verified: with both gates unset, the migrator produced zero `staging.fct_files_uploaded` rows (confirmed via `psql ... -c "SELECT COUNT(*) FROM staging.fct_files_uploaded WHERE status = 'uploaded'"`)
- [ ] You have a HubSpot **prod** private app token with these scopes:
  - `crm.objects.notes.write`
  - `crm.objects.notes.read`
  - `crm.associations.write`
  - `files`
- [ ] You have a chosen pilot row picked in advance and know how to delete its note + file from HubSpot UI if anything looks wrong
- [ ] `staging.fct_library_files` row count > 0 (so there's actually work to do)

If any box is unchecked, fix it before Phase 9. **No exceptions.**

---

## Phase 9 — Production-portal pilot (one operator-chosen row)

**The first time we write to prod HubSpot.** Exactly one row. Manual UI verification per step.

### Configuration delta from Phase 7c

- Use **`HUBSPOT_PROD_TOKEN`** instead of `HUBSPOT_SANDBOX_TOKEN`. (This requires either:
  a. a small code change adding a `--token-env-var` flag to the runner, or
  b. temporarily swapping `.env` values. Pick one — code change is cleaner.)
- **Drop the override map.** Use prod ids directly. (Requires `--no-overrides` flag — small code change.)
- **Both gates** required.
- WHERE clause targets exactly the chosen `legacy_library_id`.

### Commands (after the small code changes above)

```powershell
$test_id = "<chosen legacy_library_id>"

# Step A — Dry-run first
Remove-Item env:ICALPS_APPROVE_FILES_UPLOAD -ErrorAction SilentlyContinue
Remove-Item env:ICALPS_APPROVE_FILE_NOTES_POST -ErrorAction SilentlyContinue

uv run python -m pipeline.library_files.runner migrate `
    --library-base-dir "$env:LIBRARY_BASE_DIR" `
    --no-overrides `
    --token-env-var HUBSPOT_PROD_TOKEN `
    --source postgres `
    --query "SELECT * FROM staging.fct_library_files WHERE legacy_library_id = '$test_id'"

# Inspect dry-run ledger output. Confirm targets look right.

# Step B — Enable gates and run live
$env:ICALPS_APPROVE_FILES_UPLOAD = "1"
$env:ICALPS_APPROVE_FILE_NOTES_POST = "1"

uv run python -m pipeline.library_files.runner migrate `
    --library-base-dir "$env:LIBRARY_BASE_DIR" `
    --no-overrides `
    --token-env-var HUBSPOT_PROD_TOKEN `
    --source postgres `
    --query "SELECT * FROM staging.fct_library_files WHERE legacy_library_id = '$test_id'"
```

### Manual verification

Open **prod** HubSpot. Navigate to the company / contact / deal record matched by your chosen row's `hubspot_company_id` (or `hubspot_contact_id` / `hubspot_deal_id`). Confirm:

- A new Note exists with body matching the file's `Libr_Note` (or blank if the bronze had no note)
- The file is attached to the Note
- The Note is associated to the right CRM record (not orphaned)

### Rollback (if anything looks wrong)

```sql
SELECT n.hs_note_id, u.hs_file_id
FROM staging.fct_file_notes_posted n
JOIN staging.fct_files_uploaded u USING (legacy_library_id)
WHERE n.legacy_library_id = '<chosen>';
```

Then in HubSpot UI delete the note (which detaches the file) and optionally the file from File Manager. Or via REST:

```
DELETE /crm/v3/objects/notes/{hs_note_id}
DELETE /files/v3/files/{hs_file_id}
```

After rollback, **set the ledger rows back to a re-runnable state**:

```sql
UPDATE staging.fct_file_notes_posted SET status='failed', error='manual_rollback'
WHERE legacy_library_id = '<chosen>';
UPDATE staging.fct_files_uploaded SET status='failed', error='manual_rollback'
WHERE legacy_library_id = '<chosen>';
```

(The ledger PK is `legacy_library_id`; UPSERT will overwrite on next run.)

### Pass criterion for Phase 9

- Exactly 1 row at `status='attached'` in `staging.fct_file_notes_posted`
- HubSpot UI inspection looks correct
- No unexpected entries in any ledger table

---

## Phase 9b — Pilot batch (10 rows)

After Phase 9 green. Same setup, expand to 10 rows.

```powershell
$env:ICALPS_APPROVE_FILES_UPLOAD = "1"
$env:ICALPS_APPROVE_FILE_NOTES_POST = "1"

uv run python -m pipeline.library_files.runner migrate `
    --library-base-dir "$env:LIBRARY_BASE_DIR" `
    --no-overrides `
    --token-env-var HUBSPOT_PROD_TOKEN `
    --source postgres `
    --query "SELECT * FROM staging.fct_library_files LIMIT 10"
```

Verify each of the 10 in HubSpot UI. **Pass criterion:** 10/10 at `status='attached'`, manual UI inspection clean.

---

## Phase 10 — Full production run

Remove the LIMIT. Phase 5's idempotency makes re-runs safe.

```powershell
$env:ICALPS_APPROVE_FILES_UPLOAD = "1"
$env:ICALPS_APPROVE_FILE_NOTES_POST = "1"

uv run python -m pipeline.library_files.runner migrate `
    --library-base-dir "$env:LIBRARY_BASE_DIR" `
    --no-overrides `
    --token-env-var HUBSPOT_PROD_TOKEN `
    --source postgres
```

### Monitoring while it runs

In a second shell, every 5–10 minutes:

```sql
-- ledger pulse
SELECT status, COUNT(*) FROM staging.fct_files_uploaded     GROUP BY status ORDER BY status;
SELECT status, COUNT(*) FROM staging.fct_file_notes_posted  GROUP BY status ORDER BY status;

-- error sample
SELECT legacy_library_id, error
FROM staging.fct_files_uploaded
WHERE status='failed' OR status='partial'
ORDER BY last_attempt_at DESC LIMIT 20;
```

Spot-check 5–10 random notes in HubSpot UI as the run progresses.

### Pass criterion for Phase 10

- ≥99% of `staging.fct_library_files` rows reach `status='attached'`
- Outliers (`status='failed'` or `'partial'`) categorised by error and triaged: file_not_found, association_failed, etc.
- Re-run with the same DSN + token resolves all transient failures (429s, network blips) — only "real" failures (file_not_found) remain

---

## Phase 11 — Documentation

After Phase 10 completes. Capture:

- [ ] `pipeline/library_files/README.md` — module overview, install steps, env vars, the two CLI sub-commands (`walk`, `migrate`) with example invocations, ledger DDL pointer, troubleshooting
- [ ] Add a "Library files migration" section to `salvation.md` pointing at the README, recording the prod cutover date + commit hash + final row count
- [ ] If any new dependencies were added during Phases 7–10, update `requirements.txt`
- [ ] Capture the prod-pilot ledger snapshot (final `status` distribution) somewhere durable for the operational record

---

## Quick reference — env vars

| Variable | Purpose | Required for phase |
|---|---|---|
| `HUBSPOT_SANDBOX_TOKEN` | sandbox API token | 7c |
| `HUBSPOT_SANDBOX_PORTAL_ID` | sandbox portal id (49610528) | 7c |
| `HUBSPOT_PROD_TOKEN` | prod API token | 9, 9b, 10 |
| `LIBRARY_BASE_DIR` | local folder of legacy files | all write phases |
| `PROD_POSTGRES_DSN` | StackSync postgres DSN (URI form) | 7a normalise(), 7c+ |
| `ICALPS_APPROVE_FILES_UPLOAD` | gate Phase 1 (file upload) | 7c step 5+, 9, 9b, 10 |
| `ICALPS_APPROVE_FILE_NOTES_POST` | gate Phase 2 (note + assoc) | 7c step 6+, 9, 9b, 10 |
| `LEDGER_TEST_DSN` (optional) | postgres DSN for the live ledger test | local dev only |

## Quick reference — useful one-liners

```powershell
# Silver row count
psql "$env:PROD_POSTGRES_DSN" -c "SELECT COUNT(*) FROM staging.stg_library_normalised"

# fct row count (silver minus rows with no HubSpot reconciliation)
psql "$env:PROD_POSTGRES_DSN" -c "SELECT COUNT(*) FROM staging.fct_library_files"

# Ledger summary
psql "$env:PROD_POSTGRES_DSN" -c "SELECT status, COUNT(*) FROM staging.fct_files_uploaded GROUP BY status"

# Find one test-eligible row (has HubSpot match)
psql "$env:PROD_POSTGRES_DSN" -c "SELECT legacy_library_id, legacy_file_name, hubspot_company_id FROM staging.fct_library_files WHERE hubspot_company_id IS NOT NULL LIMIT 1"

# How many rows still need processing
psql "$env:PROD_POSTGRES_DSN" -c @"
SELECT
  (SELECT COUNT(*) FROM staging.fct_library_files) AS total,
  (SELECT COUNT(*) FROM staging.fct_files_uploaded WHERE status='uploaded') AS uploaded,
  (SELECT COUNT(*) FROM staging.fct_file_notes_posted WHERE status='attached') AS attached;
"@
```

## Quick reference — gate matrix recap

| `ICALPS_APPROVE_FILES_UPLOAD` | `ICALPS_APPROVE_FILE_NOTES_POST` | Result |
|---|---|---|
| unset | unset | **DRY-RUN.** Banner prints. Ledger fills with `status='dry_run'`. Zero HubSpot writes. |
| `1` | unset | Phase 1 fires (files uploaded), Phase 2 dry-runs. |
| unset | `1` | Warning printed. Phase 2 cannot attach what was never uploaded — re-runs against existing ledger entries proceed. |
| `1` | `1` | Full live run. |
