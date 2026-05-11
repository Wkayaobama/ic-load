# Operator sequel — after `library-files-cleanup-prod` merges to `main`

Companion to `2026-05-11-recovered.md`. The recovered doc covers what landed in code. This sequel covers what the **operator** does next, in order, with verification gates and rollback rituals at each step.

The merge of `library-files-cleanup-prod` → `main` puts five commits on main:

```
5b0c069  fix(runner): scope DBT_BUILD to communication only; restore _run_dbt
3d9297e  refactor(runner): drop duplicate dead-code defs in pipeline/runner.py
f64b060  feat(context): make salvage runner consume .env.icalps via two fixes
409e622  feat(library_files): add `unmigrate` subcommand + ledger rollback methods
d4e7083  docs: recovery notes for 2026-05-11 session — runner trifurcation + env load
```

After the merge, the operator follows the steps below.

---

## Step 0 — Pull main, populate `.env.icalps` once

```powershell
# Either work in an existing worktree
cd C:\Users\ayaobama\Documents\AnthonySalesOps\Codebase\ic-load-library-prod
git fetch origin
git pull origin main

# OR clone fresh against main
cd C:\Users\ayaobama\Documents\AnthonySalesOps\Codebase
git clone https://github.com/Wkayaobama/ic-load.git ic-load-fresh
cd ic-load-fresh
git checkout main
```

Populate the canonical secrets file at the Codebase root (one level above any worktree). This file is gitignored on every branch — it never travels through git.

```powershell
# Template lives in the repo
copy ic-load-library-prod\.env.icalps.example `
    C:\Users\ayaobama\Documents\AnthonySalesOps\Codebase\.env.icalps
notepad C:\Users\ayaobama\Documents\AnthonySalesOps\Codebase\.env.icalps
```

Required keys:
- `HUBSPOT_SANDBOX_TOKEN` (sandbox portal 49610528)
- `HUBSPOT_SANDBOX_PORTAL_ID=49610528`
- `HUBSPOT_PROD_TOKEN`
- `PROD_POSTGRES_DSN` — StackSync DSN (read access enough for ledger SELECTs; the runner needs write access only for ledger UPDATEs)
- `LIBRARY_BASE_DIR` — local path to the legacy file tree

**Approval gates** stay session-only — never put `ICALPS_APPROVE_*=1` in this file. Use inline `$env:ICALPS_APPROVE_X = "1"` before each gated run and `Remove-Item env:ICALPS_APPROVE_X` after.

---

## Step 1 — Verify env loading across all three runners

One-line smoke test per runner. Each prints `True` / non-empty values if the dotenv chain works.

```powershell
# A. Salvage runner — context.config triggers the dotenv walk-up on import
uv run python -c "import context.config; from context.db import is_postgres_configured; print('salvage_db_configured:', is_postgres_configured())"
# Expect: salvage_db_configured: True

# B. Library files runner — Settings.from_env() does its own walk-up
uv run python -c "from pipeline.library_files.config import Settings; s = Settings.from_env(); print('lib_token_len:', len(s.hubspot_token), 'dsn_len:', len(s.prod_postgres_dsn))"
# Expect: lib_token_len: 44 (or similar) dsn_len: ~130

# C. Cleanup runner — re-uses library_files.config.Settings, with prod token
uv run python -c "from pipeline.library_files.config import Settings; s = Settings.from_env(token_var='HUBSPOT_PROD_TOKEN'); print('cleanup_prod_token_len:', len(s.hubspot_token))"
# Expect: cleanup_prod_token_len: 44
```

If any returns `False` / empty values → `.env.icalps` is not where `find_dotenv` can reach. Check the file exists at `<Codebase>/.env.icalps` (one level above any worktree).

**Rollback ritual at this step:** none — read-only.

---

## Step 2 — Library files Phase 7c sandbox round-trip (re-run for fresh main)

This re-runs the operator-library.md Phase 7c sandbox round-trip against the freshly-merged main code. Purpose: confirm the ledger picks up correctly with the new env-loading + dotenv pattern.

```powershell
cd C:\Users\ayaobama\Documents\AnthonySalesOps\Codebase\ic-load-library-prod
# (or wherever you have main checked out)

# Step 2.1 — bootstrap silver + fct view (one-time per fresh DB)
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
# Expect: written_rows≈5622, view installed without DDL errors
```

```powershell
# Step 2.2 — pick a single row and run migrate against sandbox (DRY-RUN first)
uv run python -m pipeline.library_files.runner migrate `
    --library-base-dir $env:LIBRARY_BASE_DIR `
    --overrides-json overrides.json `
    --source postgres
# Expect: ledger entries with status="would_upload" / "would_attach"
```

```powershell
# Step 2.3 — LIVE phase 1 (file upload) with phase 2 still dry
$env:ICALPS_APPROVE_FILES_UPLOAD = "1"
uv run python -m pipeline.library_files.runner migrate `
    --library-base-dir $env:LIBRARY_BASE_DIR `
    --overrides-json overrides.json `
    --source postgres
Remove-Item env:ICALPS_APPROVE_FILES_UPLOAD
# Expect: ledger flips to status="uploaded" with hs_file_id populated
```

```powershell
# Step 2.4 — LIVE phase 2 (note + association)
$env:ICALPS_APPROVE_FILES_UPLOAD = "1"
$env:ICALPS_APPROVE_FILE_NOTES_POST = "1"
uv run python -m pipeline.library_files.runner migrate `
    --library-base-dir $env:LIBRARY_BASE_DIR `
    --overrides-json overrides.json `
    --source postgres
Remove-Item env:ICALPS_APPROVE_FILES_UPLOAD
Remove-Item env:ICALPS_APPROVE_FILE_NOTES_POST
# Expect: ledger flips to status="attached" with hs_note_id populated; sandbox shows the note
```

**Acceptance gate:** sandbox HubSpot UI shows the attached note + file on the target sandbox company.

**Rollback ritual:** run `unmigrate` (Step 3) — that's literally what it's for.

---

## Step 3 — `unmigrate` sandbox cleanup (the new path from commit `409e622`)

```powershell
# Step 3.1 — DRY-RUN: enumerate what would be deleted
uv run python -m pipeline.library_files.runner unmigrate
# Expect: JSON list of legacy_id + hs_note_id pairs with status="would_unattach"
```

```powershell
# Step 3.2 — LIVE: actually delete the notes
$env:ICALPS_APPROVE_UNMIGRATE = "1"
uv run python -m pipeline.library_files.runner unmigrate
Remove-Item env:ICALPS_APPROVE_UNMIGRATE
# Expect: every row reports status="unattached_via_unmigrate"; ledger flips to match
```

```powershell
# Step 3.3 — Idempotency check: re-run dry should find zero rows
uv run python -m pipeline.library_files.runner unmigrate
# Expect: "no attached rows in ledger — nothing to unmigrate", returns []
```

**Acceptance gate:** sandbox HubSpot UI shows the note is archived (DELETE on a HubSpot engagement archives it — restorable for 90 days per HubSpot's retention policy). Ledger query confirms `SELECT count(*) FROM staging.fct_file_notes_posted WHERE status='attached'` = 0.

**Rollback ritual:** if a note was wrongly archived, restore it via the HubSpot UI within 90 days. There is no `re-migrate` subcommand because re-migrate is just `migrate` — the ledger UPSERT will pick up where it left off.

---

## Step 4 — Cleanup pipeline Phase D2 sandbox-shadow probe

The cleanup runner has its own sandbox probe — Phase D2 in `operator-cleanup.md`. Pattern: seed sandbox companies, materialise a temporary postgres view of those sandbox IDs, shadow `HUBSPOT_PROD_TOKEN` with `HUBSPOT_SANDBOX_TOKEN` for the session, run `archive`, verify in sandbox UI, drop the view + reset env var.

```powershell
# Follow operator-cleanup.md Phase D2 exactly.
# Brief outline (refer to that file for the actual queries + verifications):

# 4.1 Seed sandbox companies via HubSpot UI or POST /companies (a few test rows)
# 4.2 Materialise: CREATE TEMP VIEW staging.fct_cleanup_sandbox AS SELECT ...
# 4.3 Shadow the token for this PowerShell session only:
$prevProd = $env:HUBSPOT_PROD_TOKEN
$env:HUBSPOT_PROD_TOKEN = $env:HUBSPOT_SANDBOX_TOKEN

# 4.4 Probe with the sandbox-shadow view
uv run python -m pipeline.cleanup.runner snapshot --object companies --source-view staging.fct_cleanup_sandbox
uv run python -m pipeline.cleanup.runner check-overlap
# Cross-pipeline guard: the cleanup manifest must NOT overlap library_files attached notes.
# If it does, check-overlap will fail with a clear message — fix the source view to exclude.

# 4.5 DRY archive (gate unset)
uv run python -m pipeline.cleanup.runner archive --object companies
# Expect: dry-run output, no API calls

# 4.6 LIVE archive against sandbox
$env:ICALPS_APPROVE_ARCHIVE = "1"
uv run python -m pipeline.cleanup.runner archive --object companies
Remove-Item env:ICALPS_APPROVE_ARCHIVE

# 4.7 Verify in sandbox UI, then teardown
$env:HUBSPOT_PROD_TOKEN = $prevProd
# DROP VIEW staging.fct_cleanup_sandbox;
```

**Acceptance gate:** sandbox shows the seeded companies as archived; ledger row state visible via `uv run python -m pipeline.cleanup.runner status`.

**Rollback ritual:** HubSpot archive is restorable for 90 days via the UI. If the wrong rows are archived, do not re-archive — restore in the UI and fix the source view.

---

## Step 5 — Salvage runner `--probe-mode` against communication

`--probe-mode` is the read-only path through the stage machine for the communication entity. It exercises dbt-build but skips gold validation + upsert. Use it to confirm the new dbt selector (commit `5b0c069`) actually builds the comm subgraph against the live StackSync postgres.

```powershell
# 5.1 Pre-flight: confirm `dbt` is available via uv extra
uv run --extra dbt dbt --version
# Expect: dbt Core 1.7+ with dbt-duckdb adapter

# 5.2 Probe-mode salvage run for communication
uv run python -m pipeline.runner --entity communication --probe-mode
# Expect: every stage reaches at least SKIPPED / SUCCESS; DBT_BUILD runs the
# selector "+fct_communication_calls +fct_communication_meetings ..." against
# the StackSync postgres via the postgres_scanner extension. No HubSpot writes.
```

**Acceptance gate:** `DBT_BUILD(S)` in the stage history (S = SUCCESS or SKIPPED — both acceptable). `GOLD_VALIDATE(S)` with `reason=probe_mode`. `GOLD_UPSERT(S)`. Artifact written to `artifacts/pipeline_run_communication_*.json`.

```powershell
# 5.3 Optional — preview-mode also exercises the gold/assoc SELECT paths read-only
uv run python -m pipeline.runner --entity communication --preview
# Same skip semantics; gold_previewer and association_previewer write candidate
# rows to artifacts/ops/ instead of INSERTing.
```

**Rollback ritual:** none — read-only.

---

## Step 6 — Prod cutover blockers (separate follow-up)

Before any prod write (Phase 9 — 1-row pilot, Phase 10 — full prod), the library_files runner needs two flags added in a follow-up commit (out of scope for this session):

- `--token-env-var <NAME>` so prod runs read `HUBSPOT_PROD_TOKEN` instead of the default `HUBSPOT_SANDBOX_TOKEN`.
- `--no-overrides` so prod runs use reconciled `hubspot.*.id` values directly, instead of the sandbox-id override map.

Track this work in memory `iteration_loops.md`. Do not attempt prod writes until both flags exist and are unit-tested.

The cleanup runner has the equivalent already: `TOKEN_ENV = "HUBSPOT_PROD_TOKEN"` is its default, so cleanup prod runs need no flag changes — just the operator setting `ICALPS_APPROVE_ARCHIVE=1` in a deliberate session.

---

## Step 7 — Prod pilot (Phase 9), then full prod (Phase 10) — library_files

(Requires Step 6 complete.)

```powershell
# 7.1 Phase 9 — 1-row prod pilot
$env:ICALPS_APPROVE_FILES_UPLOAD = "1"
$env:ICALPS_APPROVE_FILE_NOTES_POST = "1"
uv run python -m pipeline.library_files.runner migrate `
    --library-base-dir $env:LIBRARY_BASE_DIR `
    --overrides-json overrides.json `
    --source postgres `
    --token-env-var HUBSPOT_PROD_TOKEN `
    --no-overrides `
    --query "SELECT * FROM staging.fct_library_files WHERE legacy_library_id = <PILOT_ID> LIMIT 1"
Remove-Item env:ICALPS_APPROVE_FILES_UPLOAD
Remove-Item env:ICALPS_APPROVE_FILE_NOTES_POST
# Verify the single row landed in prod HubSpot via UI.
```

```powershell
# 7.2 Phase 9b — 10-row batch (same flags, looser WHERE)
# ... same shape as 7.1 with WHERE clause expanded to 10 rows ...

# 7.3 Phase 10 — full prod (no WHERE filter)
# ... only after Phase 9b is operator-confirmed green ...
```

**Acceptance gate at each phase:** every uploaded note shows correct association(s) in prod HubSpot UI + ledger reflects `status='attached'` for the uploaded set. **Stop immediately if any row produces `status='failed'` or `status='partial'`** — investigate before continuing.

**Rollback ritual:** `unmigrate` works against prod just as against sandbox (it uses whatever token + DSN are in env). The 90-day archive restore window applies in prod too. Run `unmigrate` against prod ONLY if Phase 9 surfaces a defect; do not use it as a normal teardown for prod.

---

## Step 8 — Cleanup prod (Phase E → F → G in operator-cleanup.md)

(Requires Step 4 sandbox probe green.)

The cleanup runbook has three irreversibility tiers:
- **Phase E** — `archive` companies/contacts/deals. 90-day restore window.
- **Phase E2** — `gdpr-delete-contacts`. Irreversible contact purge.
- **Phase F** — `delete-properties` with `--include-join-keys --library-migration-complete` two-flag guard. Irreversible schema deletion.

Each phase has its own gate; gates do not transfer. Confirm phase-by-phase per the runbook.

---

## Quick reference — every gate, every default

| Gate env var | Pipeline | Phase | Default | Irreversible? |
|---|---|---|---|---|
| `ICALPS_APPROVE_FILES_UPLOAD` | library_files | Phase 1 (file upload) | unset (DRY) | No — `unmigrate` rolls back |
| `ICALPS_APPROVE_FILE_NOTES_POST` | library_files | Phase 2 (note + assoc) | unset (DRY) | No — `unmigrate` rolls back |
| `ICALPS_APPROVE_UNMIGRATE` | library_files | (rollback) | unset (DRY) | No — HubSpot UI restores within 90d |
| `ICALPS_APPROVE_ARCHIVE` | cleanup | Phase E | unset (DRY) | No — HubSpot UI restores within 90d |
| `ICALPS_APPROVE_GDPR_DELETE` | cleanup | Phase E2 | unset (DRY) | **Yes — permanent purge** |
| `ICALPS_APPROVE_PROP_DELETE` | cleanup | Phase F | unset (DRY) | **Yes — permanent schema deletion** |
| `--approve-gold` (CLI flag) | salvage | GOLD_VALIDATE | unset (FAILED) | n/a — protects writes to `hubspot.*` |

---

## Decision points the operator owns (not me)

1. **When to populate `.env.icalps`** — Step 0. Do once, never commit.
2. **When to switch from sandbox to prod tokens** — Step 7 / Step 8. Use the explicit `--token-env-var` flag (Step 6 prerequisite for library_files; cleanup already prod-by-default).
3. **When to allow archive/delete operations** — set the appropriate `ICALPS_APPROVE_*=1` in a deliberate session, unset immediately after.
4. **When the pipeline is "done"** — when both library_files Phase 11 (docs) and cleanup Phase G (status confirmation) are green against prod.

---

## What to do if something breaks

| Symptom | First thing to check |
|---|---|
| `HUBSPOT_*_TOKEN is not set` | `.env.icalps` location — must be reachable by `find_dotenv` walk-up from cwd |
| `PostgreSQL connection is not configured` | Either `.env.icalps` missing the DSN or you're running pre-`f64b060` code |
| `_run_dbt is not defined` (NameError) | You're running pre-`5b0c069` code — pull main again |
| dbt build fails with `operator does not exist: character varying = bigint` | Old `init_fct_view.sql` — pull main; the cast direction was fixed in `e663a48` |
| Library migrate skips every row with "no rows resolved against override map" | `overrides.json` doesn't have the legacy ID — populate it, or use `--source postgres` |
| Unmigrate dry-run reports 0 rows but you know notes exist | The ledger row's `status` isn't `attached` — check the ledger directly |
| `cleanup.runner archive` fails on `check-overlap` | A row in the cleanup manifest is ALSO in `staging.fct_file_notes_posted` with `status='attached'` — exclude it from the cleanup source view |

---

## Closing — what "done" looks like

The operator's workstream is complete when:

- [ ] `.env.icalps` populated at Codebase root
- [ ] Step 1 smoke test green for all three runners
- [ ] Step 2 sandbox round-trip green (library_files Phase 7c re-confirmed against main code)
- [ ] Step 3 unmigrate idempotent against sandbox (DRY → LIVE → DRY-empty)
- [ ] Step 4 cleanup Phase D2 sandbox-shadow probe green
- [ ] Step 5 salvage runner probe-mode against communication green
- [ ] Step 6 follow-up commit landed (`--token-env-var` + `--no-overrides`)
- [ ] Step 7 Phase 9 (1-row prod pilot for library_files) green, then Phase 9b (10), then Phase 10 (full)
- [ ] Step 8 cleanup Phase E (archive) → Phase E2 (GDPR) → Phase F (properties) per cleanup runbook
- [ ] Phase 11 — docs updated (operator-library.md, operator-cleanup.md, README)

At that point the IcAlps → HubSpot migration is operator-complete. Code-side, this session's work has already merged to main.
