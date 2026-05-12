# operator-cleanup.md — operator runbook for IcAlps stale-record cleanup

> Companion to `cleanup_runner_plan.md` (architecture + decisions). Sibling to
> `operator-library.md`. This file is operator-facing: concrete commands,
> gates, verification steps for Phases A → G.

---

## Branch + scope

All commands assume the same shell setup as the library_files runbook:

```powershell
cd C:\Users\ayaobama\Documents\AnthonySalesOps\Codebase\ic-load-jl-selective-changes
git checkout library-files-rest-sandbox-prod
```

Both pipelines share the branch, the DSN, and the prod token. They are
independent features running on the same infrastructure.

---

## Pre-flight checklist (one-time)

- [ ] Library_files Phase 10 is at status='attached' for the rows you intend
      to keep enriched. Cleanup does not technically block on this, but Phase F
      (property deletion) cannot run until library_files is fully migrated —
      the join keys (`icalps_company_id`, `icalps_contact_id`,
      `icalps_deal_id`) are excluded from the property manifest by default and
      gated behind `--include-join-keys --library-migration-complete`.
- [ ] `.env.icalps` (at the **Codebase root**, one level above any worktree)
      has `HUBSPOT_PROD_TOKEN` and `PROD_POSTGRES_DSN`. Both library and
      cleanup worktrees read this file via `find_dotenv` walk-up. Token needs
      the additional cleanup scopes:
      `crm.objects.{companies,contacts,deals}.write`,
      `crm.schemas.{companies,contacts,deals}.write`.
- [ ] All three approval gates **unset** for now (default = DRY-RUN):
      `ICALPS_APPROVE_ARCHIVE`, `ICALPS_APPROVE_GDPR_DELETE`,
      `ICALPS_APPROVE_PROP_DELETE`.
- [ ] `psql "$env:PROD_POSTGRES_DSN" -c "SELECT 1"` returns `1`.

---

## Phase A — Bootstrap (one time)

The runner calls `CleanupLedger.bootstrap()` automatically on first ledger
write. To **also** materialise the four selection views
(`fct_cleanup_companies`, `fct_cleanup_contacts`, `fct_cleanup_deals`,
`fct_cleanup_communication`), run the dedicated subcommand:

```powershell
uv run python -m pipeline.cleanup.runner bootstrap-views
```

Expect stderr: `bootstrap-views: created/refreshed staging.fct_cleanup_{companies,contacts,deals,communication}`.

Then verify ledger summary:

```powershell
uv run python -m pipeline.cleanup.runner status
```

Expect a `{}`-shaped JSON with `manifest`, `archives`, `gdpr`, `properties`
keys (all empty so far).

Then confirm tables AND views exist:

```powershell
psql "$env:PROD_POSTGRES_DSN" -c "
SELECT table_name, table_type
FROM information_schema.tables
WHERE table_schema = 'staging' AND table_name LIKE 'fct_cleanup_%'
UNION ALL
SELECT table_name, 'VIEW'
FROM information_schema.views
WHERE table_schema = 'staging' AND table_name LIKE 'fct_cleanup_%'
ORDER BY table_type, table_name;
"
```

Expect four `BASE TABLE` rows (`fct_cleanup_manifest`, `fct_cleanup_archives`,
`fct_cleanup_gdpr`, `fct_cleanup_properties`) plus four `VIEW` rows
(`fct_cleanup_companies`, `fct_cleanup_contacts`, `fct_cleanup_deals`,
`fct_cleanup_communication`).

**Communication caveat:** the `fct_cleanup_communication` view is
**selection-only** at this time. `cleanup archive --object communication`
is not wired — `selection.SUPPORTED_OBJECTS` excludes engagements. You can
snapshot the manifest from this view for review, but archiving comms
requires the engagement-dispatch work (separate scope).

---

## Phase B — Build the manifest

You define what counts as "stale." The runner does not invent a default
narrower than `IS NOT NULL`.

### Option 1 — inline predicate

```powershell
uv run python -m pipeline.cleanup.runner snapshot --object companies `
    --where "icalps_company_id IS NOT NULL AND lastmodifieddate < '2023-01-01'"

uv run python -m pipeline.cleanup.runner snapshot --object contacts `
    --where "icalps_contact_id IS NOT NULL AND lastmodifieddate < '2023-01-01'"

uv run python -m pipeline.cleanup.runner snapshot --object deals `
    --where "icalps_deal_id IS NOT NULL AND closedate < '2023-01-01'"
```

### Option 2 — durable selection view (preferred for repeatable cleanup)

Define one view per object capturing the staleness predicate:

```sql
CREATE OR REPLACE VIEW staging.fct_cleanup_companies AS
SELECT id::text         AS hubspot_id,
       icalps_company_id::text AS legacy_id,
       name             AS label
FROM hubspot.companies
WHERE icalps_company_id IS NOT NULL
  AND lastmodifieddate < '2023-01-01';
-- Repeat for contacts / deals with their own predicates.
```

Then snapshot from the view:

```powershell
uv run python -m pipeline.cleanup.runner snapshot --object companies `
    --source-view staging.fct_cleanup_companies
```

### Verification

```powershell
psql "$env:PROD_POSTGRES_DSN" -c "
SELECT object_type, COUNT(*) AS targeted
FROM staging.fct_cleanup_manifest
GROUP BY object_type ORDER BY object_type;
"
```

Spot-check 10 rows per object type:

```sql
SELECT * FROM staging.fct_cleanup_manifest
WHERE object_type = 'companies' ORDER BY random() LIMIT 10;
```

---

## Phase C — Overlap check vs library_files

Refuses to proceed if the cleanup manifest collides with attached library Notes.

```powershell
uv run python -m pipeline.cleanup.runner check-overlap
```

**Pass criterion:** `overlap check: 0 rows ... Safe to proceed.`

If there's overlap, three options:

1. Narrow the snapshot predicate to exclude record IDs that have library
   Notes (re-run Phase B).
2. Drop the offending records from the manifest manually:
   ```sql
   DELETE FROM staging.fct_cleanup_manifest m
   USING staging.fct_library_files f, staging.fct_file_notes_posted n
   WHERE n.legacy_library_id = f.legacy_library_id
     AND n.status = 'attached'
     AND ((m.object_type='companies' AND m.legacy_id = f.legacy_company_id::text)
       OR (m.object_type='contacts'  AND m.legacy_id = f.legacy_contact_id::text)
       OR (m.object_type='deals'     AND m.legacy_id = f.legacy_deal_id::text));
   ```
3. Re-run with `--allow-overlap` if the collision is intentional (e.g. you
   genuinely want to archive a record AND its library Notes). The Notes will
   be archived automatically alongside their parent.

---

## Phase D — Dry-run archive

Confirm the runner sees the right counts before any prod write.

```powershell
# Make sure all gates are unset
Remove-Item env:ICALPS_APPROVE_ARCHIVE      -ErrorAction SilentlyContinue
Remove-Item env:ICALPS_APPROVE_GDPR_DELETE  -ErrorAction SilentlyContinue
Remove-Item env:ICALPS_APPROVE_PROP_DELETE  -ErrorAction SilentlyContinue

uv run python -m pipeline.cleanup.runner archive --object deals
uv run python -m pipeline.cleanup.runner archive --object contacts
uv run python -m pipeline.cleanup.runner archive --object companies
```

**Expect:** banners say `Phase E: DRY`. Each summary's `attempted` matches
the manifest count from Phase B. Ledger fills with `status='dry_run'`.

---

## Phase D2 — Sandbox probe (optional)

Exercises the full archive → ledger code path against the sandbox HubSpot
portal before any prod write. Patterned after library_files Phase 7c.

Useful catch-classes: wrong object-type pluralisation in the URL, malformed
batch payload, ledger UPSERT failures, idempotent re-run behaviour. Not a
substitute for the dry-run, which is cheaper and catches selection bugs.

### Step D2.1 — seed test records in sandbox HubSpot

In the sandbox portal (`HUBSPOT_SANDBOX_PORTAL_ID=49610528`), manually create
three companies via UI or REST. Set `icalps_company_id` on each to a
distinguishable test value (e.g. `999000001`, `999000002`, `999000003`).
Note each sandbox HubSpot record id (visible in the company URL).

### Step D2.2 — materialise a sandbox-probe view in postgres

```sql
CREATE OR REPLACE VIEW staging.fct_cleanup_sandbox_probe_companies AS
SELECT '<sandbox_id_1>'::text AS hubspot_id, '999000001' AS legacy_id, 'sandbox-probe-1' AS label
UNION ALL
SELECT '<sandbox_id_2>'::text, '999000002', 'sandbox-probe-2'
UNION ALL
SELECT '<sandbox_id_3>'::text, '999000003', 'sandbox-probe-3';
```

### Step D2.3 — shadow the prod token with the sandbox token for this shell

```powershell
$prod_token_backup = $env:HUBSPOT_PROD_TOKEN
$env:HUBSPOT_PROD_TOKEN = $env:HUBSPOT_SANDBOX_TOKEN
```

The cleanup runner reads `HUBSPOT_PROD_TOKEN`. Shadowing it keeps the runner
unmodified while routing this session's REST calls to sandbox.

### Step D2.4 — snapshot from the sandbox-probe view, then archive

```powershell
uv run python -m pipeline.cleanup.runner snapshot --object companies `
    --source-view staging.fct_cleanup_sandbox_probe_companies

# Dry-run first
Remove-Item env:ICALPS_APPROVE_ARCHIVE -ErrorAction SilentlyContinue
uv run python -m pipeline.cleanup.runner archive --object companies

# Live
$env:ICALPS_APPROVE_ARCHIVE = "1"
uv run python -m pipeline.cleanup.runner archive --object companies
```

### Step D2.5 — verify in sandbox HubSpot UI

The three test companies should appear under "Recently deleted." The ledger
shows `status='archived'` for the sandbox ids. Re-running the archive command
should be a no-op (idempotency check).

### Step D2.6 — cleanup the probe state

```powershell
# Restore the real prod token
$env:HUBSPOT_PROD_TOKEN = $prod_token_backup
Remove-Item env:ICALPS_APPROVE_ARCHIVE
```

```sql
-- Drop the probe view and its ledger rows so the prod ledger is clean
DROP VIEW staging.fct_cleanup_sandbox_probe_companies;
DELETE FROM staging.fct_cleanup_manifest  WHERE label LIKE 'sandbox-probe-%';
DELETE FROM staging.fct_cleanup_archives  WHERE hubspot_id IN ('<sandbox_id_1>','<sandbox_id_2>','<sandbox_id_3>');
```

### Pass criterion for Phase D2

- All three test companies show in sandbox "Recently deleted"
- Archive ledger contains the three `status='archived'` rows during the probe
- Re-running archive is idempotent (no new rows, no errors)
- After cleanup queries, no probe rows remain in any `fct_cleanup_*` table

If any of those fail, do not proceed to Phase E. Triage in sandbox first.

---

## Phase E — Live archive (gated)

Order: deals → contacts → companies. Cosmetic, not technical — archives don't
cascade. But going bottom-up keeps the spot-checks readable.

```powershell
$env:ICALPS_APPROVE_ARCHIVE = "1"

uv run python -m pipeline.cleanup.runner archive --object deals
uv run python -m pipeline.cleanup.runner archive --object contacts
uv run python -m pipeline.cleanup.runner archive --object companies
```

### After each object

```sql
SELECT object_type, status, COUNT(*)
FROM staging.fct_cleanup_archives
GROUP BY object_type, status
ORDER BY object_type, status;
```

Then in **prod HubSpot UI** → Recently deleted → confirm a sample of 5–10
records appear there with the correct names.

### Pass criterion for Phase E

- All manifest rows for that object are at `status='archived'` in
  `staging.fct_cleanup_archives`.
- No rows at `status='failed'`. If any: re-run the same command — UPSERT
  retries them. Triage repeated failures via the `error` column.

### Re-upsert reminder

Records archived here remain in HubSpot's "Recently deleted" for ~90 days.
Their natural keys (especially **email** for contacts) are still held by the
archived row during that window. Re-upserting a contact by email during the
window will *restore the archived contact* rather than create a new one.
This is HubSpot behaviour, not a bug.

If you need a clean re-create under the same email, run Phase E2 next.

---

## Phase E2 — GDPR-delete contacts (irreversible, optional)

**Only run this if you are certain you do not want the archived contacts to
be restorable.** GDPR-delete is permanent. The 90-day "Recently deleted"
window is bypassed.

```powershell
$env:ICALPS_APPROVE_GDPR_DELETE = "1"

uv run python -m pipeline.cleanup.runner gdpr-delete-contacts
```

Verifies only contacts already at `status='archived'` are eligible.

### Verification

```sql
SELECT status, COUNT(*) FROM staging.fct_cleanup_gdpr GROUP BY status;
```

Expect: every eligible contact at `status='purged'`.

### Rollback

There is none. GDPR-delete is by design irreversible. The archived contact
and its email are gone from HubSpot's index permanently.

---

## Phase F — Property deletion (separate gate)

**Run only after the library_files migration is fully attached.** The default
property manifest excludes `icalps_company_id` / `icalps_contact_id` /
`icalps_deal_id` because `staging.fct_library_files` joins on those columns.

### Step F.1 — verify library_files is complete

```powershell
psql "$env:PROD_POSTGRES_DSN" -c "
SELECT
  (SELECT COUNT(*) FROM staging.fct_library_files) AS total,
  (SELECT COUNT(*) FROM staging.fct_file_notes_posted WHERE status='attached') AS attached;
"
```

Numbers should match. If not, do not proceed to Step F.5.

### Step F.2 — review the property manifest

```powershell
type pipeline\cleanup\properties_manifest.json
```

Confirm the lists match what you intend to delete. Edit and commit if needed.

### Step F.3 — dry-run

```powershell
Remove-Item env:ICALPS_APPROVE_PROP_DELETE -ErrorAction SilentlyContinue

uv run python -m pipeline.cleanup.runner delete-properties --object companies
uv run python -m pipeline.cleanup.runner delete-properties --object contacts
uv run python -m pipeline.cleanup.runner delete-properties --object deals
```

Banner shows `Phase F: DRY`. Ledger fills with `status='dry_run'`. No HubSpot
calls.

### Step F.4 — live, excluding join keys

```powershell
$env:ICALPS_APPROVE_PROP_DELETE = "1"

uv run python -m pipeline.cleanup.runner delete-properties --object companies
uv run python -m pipeline.cleanup.runner delete-properties --object contacts
uv run python -m pipeline.cleanup.runner delete-properties --object deals
```

Verify in HubSpot UI → Settings → Properties → filter by `icalps` → confirm
the manifest is gone (only the three join keys should remain).

### Step F.5 — live, including join keys (FINAL irreversible step)

Only after F.1 reconciles. Runner refuses if you pass only one of the two
flags:

```powershell
uv run python -m pipeline.cleanup.runner delete-properties --object companies `
    --include-join-keys --library-migration-complete
uv run python -m pipeline.cleanup.runner delete-properties --object contacts `
    --include-join-keys --library-migration-complete
uv run python -m pipeline.cleanup.runner delete-properties --object deals `
    --include-join-keys --library-migration-complete
```

After this step, the legacy IcAlps reconciliation keys cease to exist in
HubSpot's schema. Any future re-onboarding pipeline must use a different key.

---

## Phase G — Status snapshot for the operational record

```powershell
uv run python -m pipeline.cleanup.runner status > cleanup_status_$(Get-Date -Format yyyyMMdd).json
```

Append a "Cleanup" section to `salvation.md` with: cutover date, commit hash,
final per-object archive count, GDPR purge count, property deletion count.
Same convention as library_files Phase 11.

---

## Quick reference — env vars

| Variable | Purpose | Required for phase |
|---|---|---|
| `HUBSPOT_PROD_TOKEN` | prod portal token | E, E2, F |
| `PROD_POSTGRES_DSN`  | StackSync postgres DSN | B, C, D, E, E2, F, G |
| `ICALPS_APPROVE_ARCHIVE` | gate Phase E | E |
| `ICALPS_APPROVE_GDPR_DELETE` | gate Phase E2 | E2 |
| `ICALPS_APPROVE_PROP_DELETE` | gate Phase F | F |

## Quick reference — gate matrix

| `ARCHIVE` | `GDPR_DELETE` | `PROP_DELETE` | Result |
|---|---|---|---|
| unset | unset | unset | Pure dry-run regardless of subcommand. |
| `1` | unset | unset | `archive` writes; others still dry-run. |
| `1` | `1` | unset | `archive` + `gdpr-delete-contacts` write. |
| `1` | `1` | `1` | Full live mode. Operator opted into all three irreversibility tiers. |

## Quick reference — useful one-liners

```powershell
# Manifest counts
psql "$env:PROD_POSTGRES_DSN" -c "SELECT object_type, COUNT(*) FROM staging.fct_cleanup_manifest GROUP BY object_type"

# Archive ledger summary
psql "$env:PROD_POSTGRES_DSN" -c "SELECT object_type, status, COUNT(*) FROM staging.fct_cleanup_archives GROUP BY object_type, status ORDER BY object_type, status"

# Property ledger summary
psql "$env:PROD_POSTGRES_DSN" -c "SELECT object_type, status, COUNT(*) FROM staging.fct_cleanup_properties GROUP BY object_type, status ORDER BY object_type, status"

# Failed archives — pull error sample
psql "$env:PROD_POSTGRES_DSN" -c "SELECT object_type, hubspot_id, error FROM staging.fct_cleanup_archives WHERE status='failed' LIMIT 20"

# How much library_files work is left (gating Phase F.5)
psql "$env:PROD_POSTGRES_DSN" -c "SELECT (SELECT COUNT(*) FROM staging.fct_library_files) total, (SELECT COUNT(*) FROM staging.fct_file_notes_posted WHERE status='attached') attached"
```
