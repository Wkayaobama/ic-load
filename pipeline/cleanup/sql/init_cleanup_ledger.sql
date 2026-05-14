-- Cleanup ledger DDL.
--
-- These tables sit alongside staging.fct_files_uploaded and
-- staging.fct_file_notes_posted from the library_files pipeline. They are
-- OUR staging tables — not StackSync-mirrored. Writing to them does NOT
-- propagate to HubSpot.
--
-- Schema name is substituted by the Python loader against a strict allowlist
-- (regex ^[a-z_][a-z0-9_]*$). Identifiers cannot be passed as parameters in
-- psycopg2.

CREATE SCHEMA IF NOT EXISTS {schema};

-- Phase B output: durable list of records targeted for cleanup. Operator
-- writes here via `cleanup snapshot`. Source-of-truth for everything that
-- follows.
CREATE TABLE IF NOT EXISTS {schema}.fct_cleanup_manifest (
    object_type    TEXT NOT NULL,                 -- 'companies' | 'contacts' | 'deals'
    hubspot_id     TEXT NOT NULL,
    legacy_id      TEXT,                          -- icalps_company_id / icalps_contact_id / icalps_deal_id
    label          TEXT,                          -- name / firstname+lastname / dealname for human review
    snapshot_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (object_type, hubspot_id)
);

-- Phase E ledger: one row per (object_type, hubspot_id) we tried to archive.
-- Idempotent: re-runs UPSERT, status='archived' rows are skipped on re-run.
CREATE TABLE IF NOT EXISTS {schema}.fct_cleanup_archives (
    object_type     TEXT NOT NULL,
    hubspot_id      TEXT NOT NULL,
    status          TEXT NOT NULL,                -- pending | dry_run | archived | failed
    error           TEXT,
    attempts        INT  NOT NULL DEFAULT 0,
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (object_type, hubspot_id)
);

-- Phase E2 ledger: contact GDPR-delete outcomes. Permanent — these contacts
-- cannot be restored. Same primary key shape so it joins cleanly with the
-- manifest.
CREATE TABLE IF NOT EXISTS {schema}.fct_cleanup_gdpr (
    object_type     TEXT NOT NULL,                -- 'contacts' (others not supported by HubSpot)
    hubspot_id      TEXT NOT NULL,
    status          TEXT NOT NULL,                -- pending | dry_run | purged | failed
    error           TEXT,
    attempts        INT  NOT NULL DEFAULT 0,
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (object_type, hubspot_id)
);

-- Operator-curated 'Group' rename queue. Records listed here get a PATCH
-- against /crm/v3/objects/{object_type}/{id} updating their `name` property
-- to a 'Group'-suffixed form. Used after the Phase 1 wipe to flag preserved
-- conglomerate anchors as multi-stakeholder Group records.
-- Idempotent: status='applied' rows are skipped on re-run; revert is a
-- separate runner action that PATCHes back to original_name.
CREATE TABLE IF NOT EXISTS {schema}.fct_cleanup_groups (
    object_type      TEXT NOT NULL,
    hubspot_id       TEXT NOT NULL,
    original_name    TEXT,          -- captured pre-PATCH for revert
    target_name      TEXT NOT NULL, -- the new name (typically <original> Group)
    status           TEXT NOT NULL DEFAULT 'pending',  -- pending|applied|reverted|failed
    error            TEXT,
    source           TEXT,
    added_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_attempt_at  TIMESTAMPTZ,
    PRIMARY KEY (object_type, hubspot_id)
);

-- Operator-curated safe-list. Records listed here are EXEMPT from archive
-- (the inverse of fct_cleanup_* views which list deletion targets).
-- Read at archive() time in pipeline/cleanup/archiver.py — load-bearing,
-- not just a selection-time filter, so post-snapshot edits are honoured.
-- Valid object_type values: 'companies' | 'contacts' | 'deals' | 'calls'
--                          | 'notes' | 'tasks' | 'meetings'. No CHECK
-- constraint to keep coupling with selection.SUPPORTED_OBJECTS loose.
CREATE TABLE IF NOT EXISTS {schema}.fct_cleanup_exemptions (
    object_type    TEXT NOT NULL,
    hubspot_id     TEXT NOT NULL,
    legacy_id      TEXT,
    label          TEXT,
    reason         TEXT,
    source         TEXT,
    added_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (object_type, hubspot_id)
);

-- Phase F ledger: property-deletion outcomes. property_name is HubSpot's
-- internal name (lowercase). 404 from HubSpot is captured as
-- status='already_absent' and treated as success on re-run.
CREATE TABLE IF NOT EXISTS {schema}.fct_cleanup_properties (
    object_type     TEXT NOT NULL,
    property_name   TEXT NOT NULL,
    status          TEXT NOT NULL,                -- pending | dry_run | deleted | already_absent | failed
    http_status     INT,
    error           TEXT,
    attempts        INT  NOT NULL DEFAULT 0,
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (object_type, property_name)
);
