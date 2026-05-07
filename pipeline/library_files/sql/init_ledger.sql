-- Idempotency ledger for library-file → HubSpot Note migration.
--
-- These tables are OUR staging tables — not StackSync-mirrored. Writing to
-- them does NOT propagate to HubSpot. They exist solely so the migrator can
-- skip already-succeeded rows on re-runs after crashes or partial failures.
--
-- Schema name is substituted by the Python loader against a strict allowlist
-- (regex ^[a-z_][a-z0-9_]*$) to prevent injection — schema identifiers cannot
-- be passed as parameters in psycopg2.
--
-- Idempotency key for notes: 'icalps_libfile_' || legacy_library_id, used
-- both as a forensics aid and as a hidden suffix in hs_note_body.

CREATE SCHEMA IF NOT EXISTS {schema};

CREATE TABLE IF NOT EXISTS {schema}.fct_files_uploaded (
    legacy_library_id   TEXT PRIMARY KEY,
    hs_file_id          TEXT,
    status              TEXT NOT NULL,           -- pending | uploaded | failed
    error               TEXT,
    attempts            INT  NOT NULL DEFAULT 0,
    first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_attempt_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS {schema}.fct_file_notes_posted (
    legacy_library_id   TEXT PRIMARY KEY,
    hs_note_id          TEXT,
    idempotency_key     TEXT,
    status              TEXT NOT NULL,           -- pending | attached | partial | failed
    error               TEXT,
    attempts            INT  NOT NULL DEFAULT 0,
    first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_attempt_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
