# cleanup_runner — Plan for IcAlps stale-record cleanup

> Sibling to `library_runner_plan.md`. Different feature, same infrastructure.
> Both run on `library-files-rest-sandbox-prod`; cleanup is exercised after
> library_files Phase 10 is green, but the two pipelines are technically
> independent — neither blocks the other.

## Why a sibling, not a sequential phase

The library_files pipeline migrates legacy attachments **onto records we want to keep**. The cleanup pipeline archives and de-schemas **records we want to drop**. The selection criteria are disjoint by definition: any record archived by cleanup was, by hypothesis, never a target of a library Note, and any record enriched by library_files is not a cleanup target.

This is a hypothesis, not a guarantee. The cleanup pre-flight cross-checks the manifest against the library-files ledger and aborts if the two sets overlap (see Phase C below). Operator can override with `--allow-overlap` after manual review.

## Shared infrastructure

Same branch, same DSN, same prod token, same gate pattern, same fct/staging schema. Reuses:

| Brick | From | Used for |
|---|---|---|
| `pipeline.library_files.client.HubSpotClient` | extended in place with archive + gdpr + property-delete methods | REST writes |
| `pipeline.library_files.config.Settings` | extended to take a `token_var` parameter so it can read `HUBSPOT_PROD_TOKEN` | env loading |
| `PROD_POSTGRES_DSN` | already in `.env` | selection + ledger |
| `staging` schema convention | matches `staging.fct_files_uploaded` etc. | new `staging.fct_*` cleanup tables |
| Gate pattern (`ICALPS_APPROVE_*=1`) | matches `ICALPS_APPROVE_FILES_UPLOAD` etc. | new gates for archive / gdpr / property-delete |

New surface is `pipeline/cleanup/`, parallel to `pipeline/library_files/`. Independent module, no circular import: cleanup imports library_files, never the other way around.

## Selection model

**The selection predicate is operator-defined**, not hardcoded. Default is `WHERE icalps_<entity>_id IS NOT NULL` — i.e. "every IcAlps-tagged record." That is too broad for a real cleanup; in practice operators narrow it via `--where` to capture "stale" semantics (e.g. last-activity threshold, tombstone flag, explicit ID list, etc.).

Two operator workflows supported:

1. **Inline predicate** (one-shot):
   ```
   python -m pipeline.cleanup snapshot --object companies \
       --where "icalps_company_id IS NOT NULL AND lastmodifieddate < '2023-01-01'"
   ```
2. **Materialised view** (durable, repeatable, reviewable):
   - Operator defines `staging.fct_cleanup_companies` (mart view) capturing the stale predicate.
   - Snapshot reads from that view directly: `--source-view staging.fct_cleanup_companies`.

The runner does not invent a default predicate beyond `IS NOT NULL`. Operator owns the definition of "stale."

## Phases

### Phase A — Schema + module bootstrap (one-time)
Init ledger DDL, extend `HubSpotClient`, install `pipeline/cleanup/` package. **No HubSpot calls.**

### Phase B — Manifest snapshot
`python -m pipeline.cleanup snapshot --object {companies,contacts,deals} [--where SQL | --source-view NAME]`
Writes to `staging.fct_cleanup_manifest`: one row per target with `(object_type, hubspot_id, legacy_id, label, snapshot_at)`. Idempotent on re-run for the same predicate. **No HubSpot calls.**

### Phase C — Overlap check vs library_files
`python -m pipeline.cleanup check-overlap`
Joins `fct_cleanup_manifest` against `staging.fct_file_notes_posted` (library ledger) on `hubspot_id`. Aborts with a non-zero exit if any cleanup target has had a library Note attached, unless `--allow-overlap` is given. **No HubSpot calls.**

### Phase D — Dry-run archive
`python -m pipeline.cleanup archive --object companies` with `ICALPS_APPROVE_ARCHIVE` unset.
Reads manifest, batches into 100-id chunks, prints what would be sent to `POST /crm/v3/objects/{type}/batch/archive`, writes ledger rows with `status='dry_run'`. **No HubSpot calls.**

### Phase E — Live archive (gated)
Same command, `ICALPS_APPROVE_ARCHIVE=1`. Calls batch archive, records `(status_code, response_body, archived_count)` in `staging.fct_cleanup_archives`. Idempotent: rows already at `status='archived'` are skipped on re-run.

Order: deals → contacts → companies (cosmetic, not technical — archives don't cascade).

### Phase E2 — GDPR-delete contacts (optional, irreversible)
`python -m pipeline.cleanup gdpr-delete-contacts` with `ICALPS_APPROVE_GDPR_DELETE=1`.
Only fires for contacts already at `status='archived'`. Calls `POST /crm/v3/objects/contacts/gdpr-delete` per id. Records outcome in `staging.fct_cleanup_gdpr`. **Permanent — no rollback.**

### Phase F — Property deletion (separate gate, separate run)
`python -m pipeline.cleanup delete-properties --object companies` with `ICALPS_APPROVE_PROP_DELETE=1`.
Reads `pipeline/cleanup/properties_manifest.json` (committed, reviewable). Calls `DELETE /crm/v3/properties/{type}/{name}` per property. 404 is treated as success (idempotent). Records outcome in `staging.fct_cleanup_properties`.

**Hard guard:** the `icalps_company_id` / `icalps_contact_id` / `icalps_deal_id` properties are *not* in the JSON manifest by default — they are the join keys for `staging.fct_library_files`. Operator must pass `--include-join-keys` to delete them, and the runner refuses unless library_files ledger shows `attached` == total or operator passes `--library-migration-complete`.

### Phase G — Verify + document
`python -m pipeline.cleanup status` prints per-object counts: snapshotted, archived, gdpr-deleted, properties-deleted. Operator records the final ledger snapshot in `salvation.md` (same convention as library_files Phase 11).

## Mental model — what each phase buys

1. **Persistence (B, C)** — manifest is durable, overlap check is durable; everything is auditable from postgres alone.
2. **Safety (D, E gates, F gate)** — every prod write is intentional; default is dry-run. Property deletion has its own gate so an operator running archive cannot accidentally delete a schema.
3. **Reversibility (E vs E2 vs F)** — archive is reversible for 90 days. GDPR-delete is irreversible. Property deletion is irreversible. Each lives behind its own gate so an operator opts into each level explicitly.

## Environment variables

| Variable | Purpose | Required for phase |
|---|---|---|
| `HUBSPOT_PROD_TOKEN` | prod portal token (shared with library_files Phase 9+) | E, E2, F |
| `PROD_POSTGRES_DSN` | StackSync postgres DSN | B, C, D, E, E2, F, G |
| `ICALPS_APPROVE_ARCHIVE` | gate Phase E (batch archive) | E |
| `ICALPS_APPROVE_GDPR_DELETE` | gate Phase E2 (contact GDPR-delete) | E2 |
| `ICALPS_APPROVE_PROP_DELETE` | gate Phase F (property deletion) | F |

Required scopes on `HUBSPOT_PROD_TOKEN`: in addition to the library_files set, add
`crm.objects.{companies,contacts,deals}.write`,
`crm.schemas.{companies,contacts,deals}.write`.

## Gate matrix

| `ICALPS_APPROVE_ARCHIVE` | `ICALPS_APPROVE_GDPR_DELETE` | `ICALPS_APPROVE_PROP_DELETE` | Result |
|---|---|---|---|
| unset | unset | unset | Pure dry-run regardless of subcommand. Banner prints. Ledger rows = `dry_run`. |
| `1` | unset | unset | `archive` writes; `gdpr-delete-contacts` and `delete-properties` still dry-run. |
| `1` | `1` | unset | `archive` + `gdpr-delete-contacts` write; properties still dry-run. |
| `1` | `1` | `1` | Full live mode. Operator has opted into all three irreversibility tiers. |

## Re-upsert semantics — the load-bearing question

Operator must understand this before running Phase E or F:

- **Archive does not free natural keys.** A contact's email remains uniquely owned by its archived row for ~90 days. Re-upserting a contact by email during that window restores the archived contact rather than creating a new one. To force a fresh record under the same email, GDPR-delete first (Phase E2).
- **Companies and deals have no enforced natural-key uniqueness by default.** Re-upserting after archive creates a fresh record. The archived one stays in "Recently deleted" for ~90 days.
- **Property deletion is forever.** It removes the column across all records, archived and live, in HubSpot's schema. After Phase F, the IcAlps legacy IDs cannot be used as upsert keys ever again. Any future re-onboarding pipeline must define a different reconciliation key.

Phase F therefore has the strongest gate and the `--include-join-keys` hard guard. It is intentionally awkward to run.

## Ledger DDL (Phase A)

```sql
CREATE SCHEMA IF NOT EXISTS staging;

CREATE TABLE IF NOT EXISTS staging.fct_cleanup_manifest (
    object_type    TEXT NOT NULL,                 -- 'companies' | 'contacts' | 'deals'
    hubspot_id     TEXT NOT NULL,
    legacy_id      TEXT,
    label          TEXT,
    snapshot_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (object_type, hubspot_id)
);

CREATE TABLE IF NOT EXISTS staging.fct_cleanup_archives (
    object_type    TEXT NOT NULL,
    hubspot_id     TEXT NOT NULL,
    status         TEXT NOT NULL,                 -- pending | dry_run | archived | failed
    error          TEXT,
    attempts       INT  NOT NULL DEFAULT 0,
    first_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (object_type, hubspot_id)
);

CREATE TABLE IF NOT EXISTS staging.fct_cleanup_gdpr (
    object_type    TEXT NOT NULL,                 -- 'contacts' only for now
    hubspot_id     TEXT NOT NULL,
    status         TEXT NOT NULL,                 -- pending | dry_run | purged | failed
    error          TEXT,
    attempts       INT  NOT NULL DEFAULT 0,
    first_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (object_type, hubspot_id)
);

CREATE TABLE IF NOT EXISTS staging.fct_cleanup_properties (
    object_type    TEXT NOT NULL,
    property_name  TEXT NOT NULL,
    status         TEXT NOT NULL,                 -- pending | dry_run | deleted | already_absent | failed
    http_status    INT,
    error          TEXT,
    attempts       INT  NOT NULL DEFAULT 0,
    first_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (object_type, property_name)
);
```

## File layout

```
pipeline/cleanup/
    __init__.py
    config.py                       # CleanupSettings.from_env(token_var=...)
    selection.py                    # snapshot queries; manifest writes
    archiver.py                     # batch archive + GDPR-delete orchestration
    properties.py                   # property deletion orchestration
    runner.py                       # CLI: snapshot, check-overlap, archive,
                                    #      gdpr-delete-contacts, delete-properties,
                                    #      status
    properties_manifest.json        # committed, reviewable list of properties to drop
    sql/init_cleanup_ledger.sql

pipeline/library_files/client.py    # extended with batch_archive_objects,
                                    # gdpr_delete_contact, delete_property
```

Tests are out of scope for the first cut; runner is exercised dry-run-first against prod, same operator pattern as library_files Phase 7c.
