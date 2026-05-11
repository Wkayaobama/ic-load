-- Phase 7a — staging.stg_library_normalised
--
-- Cleansed projection of sql/library/files_icalps.csv (5,989 rows × 53 cols).
-- Schema name is substituted by the Python loader against an allowlist regex.
-- Owner resolution columns populated by joining libr_created_by →
-- staging.stg_owner_resolution at silver time (best-effort).

CREATE SCHEMA IF NOT EXISTS {schema};

CREATE TABLE IF NOT EXISTS {schema}.stg_library_normalised (
    legacy_library_id      BIGINT PRIMARY KEY,
    legacy_company_id      BIGINT,
    legacy_contact_id      BIGINT,
    legacy_deal_id         BIGINT,
    legacy_case_id         BIGINT,
    legacy_file_path       TEXT NOT NULL,
    legacy_file_name       TEXT NOT NULL,
    libr_file_size         BIGINT,
    libr_note              TEXT,
    libr_type              TEXT,
    libr_category          TEXT,
    libr_status            TEXT,
    libr_created_by        INT,
    libr_updated_by        INT,
    libr_created_at        TEXT,
    libr_updated_at        TEXT,
    icalps_owner_email     TEXT,
    icalps_owner_fullname  TEXT,
    loaded_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_stg_library_company ON {schema}.stg_library_normalised(legacy_company_id);
CREATE INDEX IF NOT EXISTS idx_stg_library_contact ON {schema}.stg_library_normalised(legacy_contact_id);
CREATE INDEX IF NOT EXISTS idx_stg_library_deal    ON {schema}.stg_library_normalised(legacy_deal_id);
